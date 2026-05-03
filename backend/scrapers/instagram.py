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

from scrapers.driver import DEFAULT_USER_AGENT
from scrapers.types import BusinessInput, RecommendationDraft, SectionResult

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 15.0
INSTAGRAM_BASE = "https://www.instagram.com"

# OG description on a public IG profile reads:
#   "1,518 Followers, 234 Following, 15 Posts - See Instagram photos and ..."
META_PATTERN = re.compile(
    r"([\d,\.]+[KMm]?)\s+Followers?,\s+([\d,\.]+[KMm]?)\s+Following,\s+([\d,\.]+[KMm]?)\s+Posts?",
    re.IGNORECASE,
)
EXTERNAL_URL_PATTERN = re.compile(r'"external_url"\s*:\s*"([^"]+)"')
BIOGRAPHY_PATTERN = re.compile(r'"biography"\s*:\s*"((?:[^"\\]|\\.)*)"')


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
    raw: dict[str, Any] = {"handle": handle, "url": url}

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=REQUEST_TIMEOUT_S,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml",
            },
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

    # Recent-activity / last-post requires the (auth-walled) GraphQL feed.
    # Leave None so the dashboard sub-check renders neutrally.
    raw["last_post_days_ago"] = None

    if "followers" not in raw and "post_count" not in raw:
        raw["error"] = "could not parse profile (likely login wall)"
        return SectionResult(score=0, status="failed", raw_data=raw, recommendations=[])

    score = _score_instagram(raw)
    recommendations = _recommendations(raw)

    status = "done" if "followers" in raw and "post_count" in raw else "partial"
    return SectionResult(score=score, status=status, raw_data=raw, recommendations=recommendations)


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


def _bio_has_location(biography: str | None) -> bool:
    if not biography:
        return False
    if "📍" in biography or "🏠" in biography:
        return True
    return bool(_LOCATION_HINTS.search(biography))


# --- scoring + recommendations ----------------------------------------------


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
