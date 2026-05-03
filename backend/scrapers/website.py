"""Real website scraper.

Static HTML fetch via httpx (no Selenium needed) + BeautifulSoup parse for the
small set of head-of-page signals the audit cares about: title, meta
description, OG image, JSON-LD LocalBusiness, viewport, HTTPS.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from bs4 import BeautifulSoup

from scrapers.driver import DEFAULT_USER_AGENT
from scrapers.types import BusinessInput, RecommendationDraft, SectionResult

logger = logging.getLogger(__name__)

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

    raw["has_jsonld_localbusiness"] = _has_localbusiness_jsonld(soup)

    viewport = head.find("meta", attrs={"name": lambda v: v and v.lower() == "viewport"})
    raw["mobile_viewport"] = bool(viewport and viewport.get("content"))

    score = _score_website(raw)
    recommendations = _recommendations(raw)
    return SectionResult(score=score, status="done", raw_data=raw, recommendations=recommendations)


def _normalize_url(url: str) -> str:
    url = url.strip()
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _has_localbusiness_jsonld(soup: BeautifulSoup) -> bool:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        text = script.string or script.get_text() or ""
        if not text.strip():
            continue
        try:
            data = json.loads(text)
        except (ValueError, json.JSONDecodeError):
            continue
        if _jsonld_contains_localbusiness(data):
            return True
    return False


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


def _jsonld_contains_localbusiness(data: Any) -> bool:
    if isinstance(data, list):
        return any(_jsonld_contains_localbusiness(item) for item in data)
    if isinstance(data, dict):
        graph = data.get("@graph")
        if isinstance(graph, list) and any(_jsonld_contains_localbusiness(g) for g in graph):
            return True
        type_field = data.get("@type")
        if isinstance(type_field, str):
            return type_field.lower() in _LOCALBUSINESS_TYPES
        if isinstance(type_field, list):
            return any(isinstance(t, str) and t.lower() in _LOCALBUSINESS_TYPES for t in type_field)
    return False


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


def _recommendations(raw: dict[str, Any]) -> list[RecommendationDraft]:
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
                    "1. Write a 1-2 sentence summary of what you do (e.g. \"Cosy specialty café in "
                    "Calicut serving single-origin coffee and fresh bakes.\").\n"
                    "2. Open your site's settings (most builders have an SEO panel) and paste it "
                    "into the **Meta description** field.\n"
                    "3. If you're hand-coding, add `<meta name=\"description\" content=\"…\" />` to "
                    "the `<head>` of your homepage.\n"
                    "4. Re-check the preview in Google's mobile-friendly tool to confirm it shows."
                ),
                estimated_impact="big",
                estimated_time="5 min",
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
            )
        )

    return recs
