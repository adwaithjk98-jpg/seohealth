"""Real website scraper.

Static HTML fetch via httpx (no Selenium needed) + BeautifulSoup parse for the
small set of head-of-page signals the audit cares about: title, meta
description, OG image, JSON-LD LocalBusiness, viewport, HTTPS.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from scrapers.types import BusinessInput, RecommendationDraft, SectionResult

logger = logging.getLogger(__name__)

# Desktop Chrome UA for the static HTML fetch — some sites gate a bare httpx
# client. (Relocated here when the Selenium driver module was removed; this is
# the module's only remaining consumer.)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

REQUEST_TIMEOUT_S = 15.0
MAX_BYTES = 1_500_000  # plenty for parsing the <head>; we don't need full pages


async def audit_website(business: BusinessInput) -> SectionResult:
    if not business.website:
        return SectionResult(
            score=0,
            status="failed",
            raw_data={"error": "no website provided"},
            recommendations=[
                RecommendationDraft(
                    severity="high",
                    title="Add your website to your business profile",
                    body_markdown=(
                        "**Why it matters**\n\n"
                        "Without a website link in your profile we can't audit it for the basics "
                        "(meta description, link previews, schema). Even a one-page Carrd or "
                        "Linktree gives you something to point Google and customers at.\n\n"
                        "**How to fix it**\n\n"
                        "1. Add your homepage URL on the **Add business** page in this app.\n"
                        "2. If you don't have a website yet, set up a free one-pager on Carrd / "
                        "Linktree / Google Sites with your hours, address, phone, and menu.\n"
                        "3. Re-run the audit so we can give it a proper check."
                    ),
                    estimated_impact="big",
                    estimated_time="30 min",
                )
            ],
        )

    url = _normalize_url(business.website)
    raw: dict[str, Any] = {"url": url, "loaded": False, "https": url.lower().startswith("https://")}

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=REQUEST_TIMEOUT_S,
            headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "text/html,*/*"},
        ) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        raw["error"] = f"fetch failed: {exc}"
        return SectionResult(score=0, status="failed", raw_data=raw, recommendations=[])

    raw["status_code"] = resp.status_code
    raw["final_url"] = str(resp.url)
    raw["https"] = str(resp.url).lower().startswith("https://")

    if resp.status_code >= 400:
        raw["error"] = f"server returned HTTP {resp.status_code}"
        return SectionResult(score=0, status="failed", raw_data=raw, recommendations=[])

    body = resp.text[:MAX_BYTES]
    raw["loaded"] = True

    soup = BeautifulSoup(body, "lxml")
    head = soup.head or soup

    title_el = head.find("title")
    raw["has_title"] = bool(title_el and (title_el.get_text() or "").strip())
    raw["title"] = (title_el.get_text() or "").strip() if title_el else None

    desc = head.find("meta", attrs={"name": lambda v: v and v.lower() == "description"})
    desc_content = (desc.get("content") if desc else None) or ""
    raw["has_meta_description"] = bool(desc_content.strip())
    raw["meta_description"] = desc_content.strip() or None

    og_image = head.find("meta", attrs={"property": lambda v: v and v.lower() == "og:image"})
    og_content = (og_image.get("content") if og_image else None) or ""
    raw["has_og_image"] = bool(og_content.strip())

    has_jsonld, jsonld_phone, jsonld_address = _extract_localbusiness_contact(soup)
    raw["has_jsonld_localbusiness"] = has_jsonld

    viewport = head.find("meta", attrs={"name": lambda v: v and v.lower() == "viewport"})
    raw["mobile_viewport"] = bool(viewport and viewport.get("content"))

    raw["phone"] = jsonld_phone or _extract_first_tel(soup)
    raw["address"] = jsonld_address

    ig_handle = _extract_instagram_handle(soup)
    if ig_handle:
        raw["instagram_handle"] = ig_handle

    # IG-on-website cross-check (FTUE follow-up). When the user has a
    # stated handle, the audit verifies that the website actually links
    # to *that* IG profile — a missing link or a mismatched one is a
    # real visibility issue (customers + crawlers can't follow the path
    # from site → social). Stored as a tri-state so the sub-check
    # renderer can speak to each case:
    #   "linked"     → matches the stated handle ✓
    #   "missing"    → no IG link found at all
    #   "mismatch"   → links to a different IG handle than stated
    #   "no_input"   → user hasn't told us their handle, can't compare
    user_ig = (business.ig_handle or "").lstrip("@").lower() or None
    site_ig = (ig_handle or "").lower() or None
    if not user_ig:
        raw["ig_link_state"] = "no_input"
    elif site_ig is None:
        raw["ig_link_state"] = "missing"
    elif site_ig == user_ig:
        raw["ig_link_state"] = "linked"
    else:
        raw["ig_link_state"] = "mismatch"
        raw["ig_link_actual"] = site_ig
        raw["ig_link_expected"] = user_ig

    score = _score_website(raw)
    recommendations = _recommendations(raw, business)
    discovered: dict[str, str | None] = {}
    if ig_handle:
        discovered["ig_handle"] = ig_handle
    return SectionResult(
        score=score,
        status="done",
        raw_data=raw,
        recommendations=recommendations,
        discovered_fields=discovered,
    )


def _normalize_url(url: str) -> str:
    url = url.strip()
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _extract_localbusiness_contact(
    soup: BeautifulSoup,
) -> tuple[bool, str | None, str | None]:
    """Walk JSON-LD blocks, return (found, telephone, address) for the first
    LocalBusiness-typed node we encounter.

    Address may be a plain string or a nested ``PostalAddress`` object —
    when nested, we concatenate streetAddress, addressLocality,
    addressRegion, postalCode in that order, comma-separated.
    """
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        text = script.string or script.get_text() or ""
        if not text.strip():
            continue
        try:
            data = json.loads(text)
        except (ValueError, json.JSONDecodeError):
            continue
        node = _find_localbusiness_node(data)
        if node is None:
            continue
        phone = _stringify_phone(node.get("telephone"))
        address = _stringify_address(node.get("address"))
        return True, phone, address
    return False, None, None


def _find_localbusiness_node(data: Any) -> dict[str, Any] | None:
    if isinstance(data, list):
        for item in data:
            found = _find_localbusiness_node(item)
            if found is not None:
                return found
        return None
    if not isinstance(data, dict):
        return None
    graph = data.get("@graph")
    if isinstance(graph, list):
        for item in graph:
            found = _find_localbusiness_node(item)
            if found is not None:
                return found
    type_field = data.get("@type")
    if isinstance(type_field, str) and type_field.lower() in _LOCALBUSINESS_TYPES:
        return data
    if isinstance(type_field, list) and any(
        isinstance(t, str) and t.lower() in _LOCALBUSINESS_TYPES for t in type_field
    ):
        return data
    return None


def _stringify_phone(value: Any) -> str | None:
    if isinstance(value, list) and value:
        value = value[0]
    if isinstance(value, str):
        s = value.strip()
        return s or None
    return None


_ADDRESS_FIELDS = ("streetAddress", "addressLocality", "addressRegion", "postalCode")


def _stringify_address(value: Any) -> str | None:
    if isinstance(value, list) and value:
        value = value[0]
    if isinstance(value, str):
        s = value.strip()
        return s or None
    if isinstance(value, dict):
        parts: list[str] = []
        for key in _ADDRESS_FIELDS:
            piece = value.get(key)
            if isinstance(piece, str) and piece.strip():
                parts.append(piece.strip())
        return ", ".join(parts) if parts else None
    return None


def _extract_first_tel(soup: BeautifulSoup) -> str | None:
    """Fallback when JSON-LD didn't yield a phone: first <a href='tel:...'>."""
    anchor = soup.find("a", href=lambda h: isinstance(h, str) and h.lower().startswith("tel:"))
    if anchor is None:
        return None
    href = anchor.get("href") or ""
    target = href.split(":", 1)[1].strip() if ":" in href else ""
    return target or None


_LOCALBUSINESS_TYPES = {
    "localbusiness",
    "restaurant",
    "cafe",
    "store",
    "hairsalon",
    "beautysalon",
    "medicalbusiness",
    "dentist",
    "gym",
    "lodgingbusiness",
    "professionalservice",
    "foodestablishment",
}


# Match `instagram.com/<handle>` (with or without `www.`, http or https).
# The handle group accepts the IG-allowed character set (alphanumeric, `.`, `_`)
# and stops at the next slash / query / fragment.
_IG_HREF_PATTERN = re.compile(
    r"^https?://(?:www\.)?instagram\.com/([A-Za-z0-9._]+)/?(?:[?#].*)?$",
    re.IGNORECASE,
)
# Reserved IG paths that look like a handle but aren't profiles.
_IG_RESERVED_PATHS = frozenset(
    {
        "p",
        "reel",
        "reels",
        "explore",
        "direct",
        "stories",
        "tv",
        "accounts",
        "about",
        "developer",
        "legal",
        "press",
        "web",
        "challenge",
        "sessions",
    }
)


def _extract_instagram_handle(soup: BeautifulSoup) -> str | None:
    """Return the first valid Instagram profile handle linked from the page."""
    for anchor in soup.find_all("a", href=True):
        href = (anchor.get("href") or "").strip()
        if not href:
            continue
        m = _IG_HREF_PATTERN.match(href)
        if not m:
            continue
        candidate = m.group(1)
        if candidate.lower() in _IG_RESERVED_PATHS:
            continue
        # IG handles are 1–30 chars; reject obviously bad shapes.
        if not (1 <= len(candidate) <= 30):
            continue
        return candidate
    return None


# --- scoring + recommendations ----------------------------------------------


def _score_website(raw: dict[str, Any]) -> int:
    score = 30
    if raw.get("loaded"):
        score += 15
    if raw.get("https"):
        score += 10
    if raw.get("has_title"):
        score += 10
    if raw.get("has_meta_description"):
        score += 15
    if raw.get("has_og_image"):
        score += 10
    if raw.get("mobile_viewport"):
        score += 5
    if raw.get("has_jsonld_localbusiness"):
        score += 10
    return max(0, min(100, score))


# Type-specific example lines for the meta-description rec. The old copy
# gave everyone the café example — a B2B supplier reading "single-origin
# coffee and fresh bakes" is exactly the generic-filler feeling the product
# promises to avoid. Keyed by the FTUE ``business_type``; city is spliced in
# so the example reads like *their* pitch, not a template.
_META_EXAMPLES: dict[str, str] = {
    "cafe": "Cosy specialty café in {city} serving single-origin coffee and fresh bakes.",
    "salon": "Friendly salon in {city} for cuts, colour, and bridal styling — walk-ins welcome.",
    "retail": "Neighbourhood store in {city} for everyday essentials and local favourites.",
    "service": "Reliable local service in {city} — quick quotes and on-time visits.",
    "supplier": "Trusted wholesale supplier in {city} — quality stock, dependable delivery.",
}
_META_EXAMPLE_DEFAULT = "Family-run business in {city} known for friendly service and fair prices."


def _meta_description_example(business: BusinessInput) -> str:
    template = _META_EXAMPLES.get(business.business_type or "", _META_EXAMPLE_DEFAULT)
    return template.format(city=business.city)


def _recommendations(raw: dict[str, Any], business: BusinessInput) -> list[RecommendationDraft]:
    recs: list[RecommendationDraft] = []

    if not raw.get("https"):
        recs.append(
            RecommendationDraft(
                severity="high",
                title="Switch your website to HTTPS",
                body_markdown=(
                    "**Why it matters**\n\n"
                    "Browsers warn visitors that non-HTTPS sites aren't secure, and Google ranks "
                    "secure pages higher. Most hosts include a free certificate via Let's Encrypt.\n\n"
                    "**How to fix it**\n\n"
                    "1. Check your hosting dashboard for an **SSL** or **HTTPS** toggle.\n"
                    "2. Enable it (most providers handle the certificate automatically).\n"
                    "3. Set up a redirect so `http://` URLs forward to `https://`.\n"
                    "4. Re-test in an incognito window — the padlock should now appear."
                ),
                estimated_impact="big",
                estimated_time="professional help",
                verify_signal="website.https",
            )
        )

    if not raw.get("has_meta_description"):
        recs.append(
            RecommendationDraft(
                severity="high",
                title="Add a meta description to your homepage",
                body_markdown=(
                    "**Why it matters**\n\n"
                    "Right now Google is making up its own one-line summary of your site, which "
                    "often picks the wrong sentence. A custom meta description is your chance to "
                    "write the pitch that shows up in search results.\n\n"
                    "**How to fix it**\n\n"
                    "1. Write a 1-2 sentence summary of what you do (e.g. "
                    f"\"{_meta_description_example(business)}\").\n"
                    "2. Open your site's settings (most builders have an SEO panel) and paste it "
                    "into the **Meta description** field.\n"
                    "3. If you're hand-coding, add `<meta name=\"description\" content=\"…\" />` to "
                    "the `<head>` of your homepage.\n"
                    "4. Re-check the preview in Google's mobile-friendly tool to confirm it shows."
                ),
                estimated_impact="big",
                estimated_time="5 min",
                verify_signal="website.has_meta_description",
            )
        )

    if not raw.get("has_og_image"):
        recs.append(
            RecommendationDraft(
                severity="medium",
                title="Add an Open Graph image",
                body_markdown=(
                    "**Why it matters**\n\n"
                    "When someone shares your website on WhatsApp, Instagram, or Twitter, the "
                    "preview is bare — no image, just the URL. An Open Graph image makes those "
                    "links look professional and gets clicked more.\n\n"
                    "**How to fix it**\n\n"
                    "1. Pick or shoot a clean photo: storefront, signature dish, or logo on a "
                    "warm background. Aim for 1200×630 pixels.\n"
                    "2. Upload it to your site's media library.\n"
                    "3. In your site's SEO settings, paste the image URL into **Open Graph image** "
                    "(or add `<meta property=\"og:image\" content=\"…\" />` to the `<head>`).\n"
                    "4. Test the preview at opengraph.xyz to confirm it renders."
                ),
                estimated_impact="medium",
                estimated_time="10 min",
                verify_signal="website.has_og_image",
            )
        )

    if not raw.get("has_jsonld_localbusiness"):
        recs.append(
            RecommendationDraft(
                severity="medium",
                title="Add LocalBusiness schema markup",
                body_markdown=(
                    "**Why it matters**\n\n"
                    "This is a small JSON snippet that tells Google your hours, address, and phone "
                    "in a structured way. Sites with it often get a richer Maps card and the "
                    "review-stars under their search result.\n\n"
                    "**How to fix it**\n\n"
                    "1. Use Google's **Structured Data Markup Helper** to generate the snippet.\n"
                    "2. Pick **LocalBusiness**, paste your homepage URL, and tag the address, phone, "
                    "and hours visible on the page.\n"
                    "3. Copy the JSON-LD it generates.\n"
                    "4. Paste it into the `<head>` of your homepage. If your site builder doesn't "
                    "support custom code, this is a good 30-minute job for a developer."
                ),
                estimated_impact="medium",
                estimated_time="professional help",
                verify_signal="website.has_jsonld_localbusiness",
            )
        )

    if not raw.get("mobile_viewport"):
        recs.append(
            RecommendationDraft(
                severity="medium",
                title="Add a mobile viewport tag",
                body_markdown=(
                    "**Why it matters**\n\n"
                    "Without a viewport meta tag, your site renders at desktop width on phones — "
                    "tiny text, awkward zooming. Most local-business traffic is mobile.\n\n"
                    "**How to fix it**\n\n"
                    "1. Add `<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">` "
                    "to the `<head>` of every page.\n"
                    "2. Most modern site builders include this by default; check the theme settings.\n"
                    "3. Re-test on a phone or with Chrome DevTools' device emulator."
                ),
                estimated_impact="medium",
                estimated_time="5 min",
                verify_signal="website.mobile_viewport",
            )
        )

    ig_state = raw.get("ig_link_state")
    if ig_state == "missing":
        recs.append(
            RecommendationDraft(
                severity="medium",
                title="Link your Instagram from your website",
                body_markdown=(
                    "**Why it matters**\n\n"
                    "Right now there's no path from your homepage to your Instagram. Visitors "
                    "who land via Google can't follow you, and Google itself uses cross-links "
                    "between your site and social profiles to confirm you're a single, "
                    "trustworthy business.\n\n"
                    "**How to fix it**\n\n"
                    "1. Add an Instagram icon or link in your footer (or header) pointing to "
                    "`https://instagram.com/<your handle>`.\n"
                    "2. Make it `<a target=\"_blank\" rel=\"noopener\">` so it opens in a new tab.\n"
                    "3. Re-run this audit to confirm the link is detected."
                ),
                estimated_impact="medium",
                estimated_time="5 min",
                verify_signal="website.ig_linked",
            )
        )
    elif ig_state == "mismatch":
        actual = raw.get("ig_link_actual") or "another account"
        expected = raw.get("ig_link_expected") or "your handle"
        recs.append(
            RecommendationDraft(
                severity="high",
                title="Your website links to a different Instagram account",
                body_markdown=(
                    "**Why it matters**\n\n"
                    f"You told us your Instagram is `@{expected}`, but your website links to "
                    f"`@{actual}`. That's a brand-consistency problem — visitors and search "
                    "engines now see two different identities for the same business, and "
                    "anyone clicking the link from your site lands on the wrong profile.\n\n"
                    "**How to fix it**\n\n"
                    "1. Decide which handle is the right one (the one on your business cards "
                    "and Google Maps listing is usually canonical).\n"
                    "2. Update the link in your website's footer / header to point to that "
                    "handle.\n"
                    "3. If the wrong handle is actually the canonical one, update it in your "
                    "SEO Health profile via Edit business details.\n"
                    "4. Re-run this audit to confirm."
                ),
                estimated_impact="big",
                estimated_time="5 min",
                verify_signal="website.ig_linked",
            )
        )

    return recs
