"""Real Instagram scraper.

Instagram aggressively blocks automated full-page scraping, but a logged-out
GET on a public profile still returns enough OpenGraph metadata to extract
followers / posts / handle / bio link. We parse those tags rather than try to
hydrate the React app.

Failure modes:
- No handle on file → SectionResult(failed) with a "tell us your IG" rec.
- 404 / login wall / rate-limit → SectionResult(failed) with the response code.
- Parse failure on otherwise-valid HTML → SectionResult(partial) with whatever
  we managed to extract.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from scrapers.ig_graph import fetch_business_discovery
from scrapers.types import BusinessInput, RecommendationDraft, SectionResult

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 15.0
INSTAGRAM_BASE = "https://www.instagram.com"

# Headers a real Chrome navigation sends when typing a URL into the address
# bar. Instagram now keys its bot heuristics off the presence of Sec-Fetch-*
# (those headers were standardised in 2019 and every browser sends them) —
# without them, anonymous fetches get the bare app shell with the meta tags
# stripped, and our regex extraction sees a login wall. With them, the same
# request returns the og:description tag carrying followers / following /
# posts. See claude_prompts for the discovery trail.
#
# The User-Agent must also be a real-looking browser; an iPhone Safari UA gets
# the friendliest payload empirically, but desktop Chrome paired with the full
# Sec-Fetch-* set works fine and is a safer default for follow-on logged-in
# parsing (which we may add later).
_PROFILE_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

# OG description on a public IG profile reads:
#   "1,518 Followers, 234 Following, 15 Posts - See Instagram photos and ..."
META_PATTERN = re.compile(
    r"([\d,\.]+[KMm]?)\s+Followers?,\s+([\d,\.]+[KMm]?)\s+Following,\s+([\d,\.]+[KMm]?)\s+Posts?",
    re.IGNORECASE,
)
EXTERNAL_URL_PATTERN = re.compile(r'"external_url"\s*:\s*"([^"]+)"')
BIOGRAPHY_PATTERN = re.compile(r'"biography"\s*:\s*"((?:[^"\\]|\\.)*)"')

# Phone-number formats seen in IG bios — international (`+91 …`, `+1 …`) and
# bare 10-digit Indian. Allow common separators (space, dash, dot, parens) and
# require a digit count that rules out random IDs / order numbers.
_PHONE_PATTERNS = (
    re.compile(r"\+\d[\d\s().\-]{8,17}\d"),  # any +CC … (>= 10 digits total)
    re.compile(r"(?<!\d)[6-9]\d{9}(?!\d)"),    # bare Indian mobile (starts 6-9)
)


async def audit_instagram(business: BusinessInput) -> SectionResult:
    handle = _normalize_handle(business.ig_handle)
    if not handle:
        return SectionResult(
            score=0,
            status="failed",
            raw_data={"error": "no instagram handle on file"},
            recommendations=[
                RecommendationDraft(
                    severity="medium",
                    title="Add your Instagram handle to your business profile",
                    body_markdown=(
                        "**Why it matters**\n\n"
                        "We can't audit your Instagram presence until we know which account is "
                        "yours. It's also a good prompt to make sure customers can find you on "
                        "the platform they likely use most.\n\n"
                        "**How to fix it**\n\n"
                        "1. Add your Instagram username on the **Edit business** page in this app.\n"
                        "2. If you don't have a business Instagram yet, take 10 minutes to set one "
                        "up — pick a clear handle that matches your business name.\n"
                        "3. Re-run the audit so we can give it a proper check."
                    ),
                    estimated_impact="medium",
                    estimated_time="5 min",
                )
            ],
        )

    url = f"{INSTAGRAM_BASE}/{handle}/"

    # Model A: prefer the Graph API ``business_discovery`` read when configured.
    # It returns reliable public stats with no login wall; ``None`` means
    # disabled / unconfigured / unreachable, so we fall through to the scraper.
    if settings.ig_graph_enabled:
        graph = await fetch_business_discovery(handle)
        if graph is not None:
            return _finalize_result(_raw_from_graph(handle, url, graph))

    raw: dict[str, Any] = {"handle": handle, "url": url, "source": "og"}

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=REQUEST_TIMEOUT_S,
            headers=_PROFILE_FETCH_HEADERS,
        ) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        raw["error"] = f"fetch failed: {exc}"
        return SectionResult(score=0, status="failed", raw_data=raw, recommendations=[])

    raw["status_code"] = resp.status_code

    if resp.status_code == 404:
        raw["error"] = "profile not found"
        return SectionResult(score=0, status="failed", raw_data=raw, recommendations=[])
    if resp.status_code >= 400:
        raw["error"] = f"instagram returned HTTP {resp.status_code}"
        return SectionResult(score=0, status="failed", raw_data=raw, recommendations=[])

    body = resp.text
    soup = BeautifulSoup(body, "lxml")

    followers, following, posts = _extract_meta_counts(soup, body)
    if followers is not None:
        raw["followers"] = followers
    if following is not None:
        raw["following"] = following
    if posts is not None:
        raw["post_count"] = posts

    biography = _extract_biography(body)
    if biography is not None:
        raw["biography"] = biography

    external_url = _extract_external_url(body)
    raw["bio_has_website_link"] = bool(external_url)
    if external_url:
        raw["external_url"] = external_url

    raw["bio_has_location"] = _bio_has_location(biography)
    raw["phone"] = _extract_phone(biography, body)
    # IG profiles don't reliably surface a postal address; NAP comparison
    # treats Instagram address as n/a by design.
    raw["address"] = None

    # Recent-activity / last-post requires the (auth-walled) GraphQL feed.
    # Leave None so the dashboard sub-check renders neutrally.
    raw["last_post_days_ago"] = None

    if "followers" not in raw and "post_count" not in raw:
        # Login wall: Instagram returned the sign-in page instead of the
        # profile, so anything we "parsed" off it is the chrome of that page,
        # not the merchant's bio. Strip the bio_* sub-checks (they'd render as
        # misleading "Missing" labels on the dashboard) and keep only the
        # identification + error fields.
        return SectionResult(
            score=0,
            status="failed",
            raw_data={
                "handle": handle,
                "url": url,
                "status_code": raw.get("status_code"),
                "error": "could not parse profile (likely login wall)",
            },
            recommendations=[_login_wall_rec(handle)],
        )

    return _finalize_result(raw)


# --- result assembly ---------------------------------------------------------


def _finalize_result(raw: dict[str, Any]) -> SectionResult:
    """Score + draft recs for a populated ``raw`` dict (Graph or OG path).

    ``done`` when we have both follower and post counts; ``partial`` otherwise.
    Shared by both data sources so they produce identical dashboard output.
    """
    score = _score_instagram(raw)
    recommendations = _recommendations(raw)
    status = "done" if "followers" in raw and "post_count" in raw else "partial"
    return SectionResult(
        score=score, status=status, raw_data=raw, recommendations=recommendations
    )


def _raw_from_graph(handle: str, url: str, graph: dict[str, Any]) -> dict[str, Any]:
    """Build the scraper's ``raw`` vocabulary from a business_discovery payload.

    Mirrors what the OG-tag path produces so scoring, recs, NAP cross-checks and
    the dashboard render identically regardless of where the numbers came from.
    The bio-derived signals (website link, location, phone) are recomputed here
    with the same helpers the scraper uses. ``following`` / ``last_post_days_ago``
    aren't exposed by business_discovery for a discovered account, so they stay
    ``None`` (the dashboard renders those sub-checks neutrally).
    """
    biography = graph.get("biography")
    external_url = graph.get("external_url")
    raw: dict[str, Any] = {"handle": handle, "url": url, "source": "graph"}
    if graph.get("followers") is not None:
        raw["followers"] = graph["followers"]
    if graph.get("post_count") is not None:
        raw["post_count"] = graph["post_count"]
    if biography is not None:
        raw["biography"] = biography
    raw["bio_has_website_link"] = bool(external_url)
    if external_url:
        raw["external_url"] = external_url
    raw["bio_has_location"] = _bio_has_location(biography)
    raw["phone"] = _extract_phone(biography, "")
    raw["address"] = None
    raw["following"] = None
    raw["last_post_days_ago"] = None
    if graph.get("display_name"):
        raw["display_name"] = graph["display_name"]
    if graph.get("profile_picture_url"):
        raw["profile_picture_url"] = graph["profile_picture_url"]
    return raw


# --- parsing helpers ---------------------------------------------------------


def _normalize_handle(handle: str | None) -> str | None:
    if not handle:
        return None
    h = handle.strip().lstrip("@")
    if h.startswith("http"):
        # accept full URL too
        h = h.rstrip("/").rsplit("/", 1)[-1]
    return h or None


def _extract_meta_counts(soup: BeautifulSoup, body: str) -> tuple[int | None, int | None, int | None]:
    desc_el = soup.find("meta", attrs={"property": "og:description"}) or soup.find(
        "meta", attrs={"name": "description"}
    )
    desc = (desc_el.get("content") if desc_el else None) or ""
    text_sources = [desc, body]
    for source in text_sources:
        if not source:
            continue
        m = META_PATTERN.search(source)
        if m:
            return _to_int(m.group(1)), _to_int(m.group(2)), _to_int(m.group(3))
    return None, None, None


def _to_int(value: str) -> int | None:
    """Parse Instagram-style human counts: '1,518', '12.3K', '1.2M'."""
    s = value.strip().replace(",", "")
    multiplier = 1
    if s.endswith(("K", "k")):
        multiplier = 1_000
        s = s[:-1]
    elif s.endswith(("M", "m")):
        multiplier = 1_000_000
        s = s[:-1]
    try:
        return int(float(s) * multiplier)
    except ValueError:
        return None


def _extract_external_url(body: str) -> str | None:
    m = EXTERNAL_URL_PATTERN.search(body)
    if not m:
        return None
    url = m.group(1).encode("utf-8").decode("unicode_escape")
    return url or None


def _extract_biography(body: str) -> str | None:
    m = BIOGRAPHY_PATTERN.search(body)
    if not m:
        return None
    raw = m.group(1)
    try:
        return raw.encode("utf-8").decode("unicode_escape")
    except UnicodeDecodeError:
        return raw


_LOCATION_HINTS = re.compile(
    r"\b(?:located|location|address|near|in|opp|opposite|behind|beside)\b", re.IGNORECASE
)


def _extract_phone(biography: str | None, body: str) -> str | None:
    """First plausible phone number found in the bio, then the page body."""
    sources = [biography or "", body or ""]
    for source in sources:
        if not source:
            continue
        for pattern in _PHONE_PATTERNS:
            m = pattern.search(source)
            if m:
                return m.group(0).strip()
    return None


def _bio_has_location(biography: str | None) -> bool:
    if not biography:
        return False
    if "📍" in biography or "🏠" in biography:
        return True
    return bool(_LOCATION_HINTS.search(biography))


# --- scoring + recommendations ----------------------------------------------


def _login_wall_rec(handle: str) -> RecommendationDraft:
    """Explain the login-wall case as a finding so the user gets context for
    the F grade instead of the "Nothing flagged" empty state.
    """
    return RecommendationDraft(
        severity="medium",
        title="Instagram hid your profile from us behind a login wall",
        body_markdown=(
            "**Why it matters**\n\n"
            f"We tried to read **@{handle}** without logging in, but "
            "Instagram returned its sign-in page instead of your profile. "
            "That doesn't mean anything is wrong with your account — it's a "
            "platform-wide change Instagram made to discourage scraping. It "
            "does mean we can't measure followers, posts, or recent activity "
            "for you on this audit.\n\n"
            "**How to fix it**\n\n"
            "1. Open Instagram and confirm **@" + handle + "** is set to a "
            "**Business** or **Creator** account, not Private — a Private "
            "profile makes this problem permanent.\n"
            "2. From a fresh logged-out browser tab, visit "
            f"`https://www.instagram.com/{handle}/` and check that you can "
            "see followers and post count without being asked to log in.\n"
            "3. If even logged-out you can't see those numbers, Instagram is "
            "currently rate-limiting profile previews — re-run this audit in "
            "a day or two and it usually works again."
        ),
        estimated_impact="medium",
        estimated_time="5 min",
    )


def _score_instagram(raw: dict[str, Any]) -> int:
    score = 40
    followers = raw.get("followers") or 0
    if followers >= 5000:
        score += 25
    elif followers >= 1000:
        score += 20
    elif followers >= 250:
        score += 10
    elif followers >= 50:
        score += 5

    posts = raw.get("post_count") or 0
    if posts >= 50:
        score += 15
    elif posts >= 12:
        score += 10
    elif posts >= 5:
        score += 5
    else:
        score -= 5

    if raw.get("bio_has_website_link"):
        score += 15
    if raw.get("bio_has_location"):
        score += 5

    return max(0, min(100, score))


def _recommendations(raw: dict[str, Any]) -> list[RecommendationDraft]:
    recs: list[RecommendationDraft] = []

    if not raw.get("bio_has_website_link"):
        recs.append(
            RecommendationDraft(
                severity="medium",
                title="Add your website link to your Instagram bio",
                body_markdown=(
                    "**Why it matters**\n\n"
                    "Right now your bio doesn't link out to your website, so people who discover "
                    "you on Instagram have nowhere to go to book, buy, or read more. The bio link "
                    "is the single most valuable spot on your profile.\n\n"
                    "**How to fix it**\n\n"
                    "1. Open Instagram → your profile → **Edit profile**.\n"
                    "2. In the **Website** field, paste your homepage URL.\n"
                    "3. If you have multiple links to share, use a free tool like Linktree or "
                    "Beacons and paste that URL instead.\n"
                    "4. Save and view your profile to confirm it's tappable."
                ),
                estimated_impact="medium",
                estimated_time="2 min",
            )
        )

    if not raw.get("bio_has_location"):
        recs.append(
            RecommendationDraft(
                severity="low",
                title="Mention your city in your Instagram bio",
                body_markdown=(
                    "**Why it matters**\n\n"
                    "Locals scanning your bio decide in two seconds whether you're nearby. "
                    "Adding your neighbourhood or city up front removes that friction.\n\n"
                    "**How to fix it**\n\n"
                    "1. Open Instagram → your profile → **Edit profile**.\n"
                    "2. In the bio, add a 📍 emoji followed by your neighbourhood and city.\n"
                    "3. If you have a physical storefront, also pin your location with the "
                    "**Add location** option so it tags your posts."
                ),
                estimated_impact="small",
                estimated_time="2 min",
            )
        )

    posts = raw.get("post_count") or 0
    if posts < 5:
        recs.append(
            RecommendationDraft(
                severity="medium",
                title="Build a baseline of 10 posts",
                body_markdown=(
                    "**Why it matters**\n\n"
                    "An almost-empty grid signals \"inactive business\" to anyone who lands on "
                    "your profile. Even a small library of 10 posts changes the first impression.\n\n"
                    "**How to fix it**\n\n"
                    "1. Pick 10 photos you already have: storefront, products, team, customers.\n"
                    "2. Write one-line captions in your real voice (skip the corporate tone).\n"
                    "3. Post 2–3 a week so the activity looks natural, not bulk-uploaded.\n"
                    "4. Save 3 posts as a Reel — the algorithm rewards it heavily."
                ),
                estimated_impact="medium",
                estimated_time="2 hours total",
            )
        )

    return recs
