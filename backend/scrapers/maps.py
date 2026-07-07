"""Google Maps audit pillar + competitor metrics, backed by the Places API (New).

Fetches a business's Maps listing (by stored ``place_id`` when we have one,
else by resolving a name+city query) and pulls rating, review count, category
and a few presence signals (hours, website link, photos). The Selenium scraper
this replaced is gone — everything here is a plain async HTTP call via
:mod:`scrapers.places`, so no headless browser is involved.

Public surface (kept stable so every caller stayed a no-op swap):
- :func:`audit_maps` — the Maps pillar for the user's own business.
- :func:`fetch_competitor_metrics` — bulk rating/review snapshot for competitors.
- :class:`CompetitorMetrics`, :class:`CompetitorScrapeTarget`.

Failure modes:
- Places API unreachable / bad key / quota (429) / 5xx → ``audit_maps`` raises
  ``RuntimeError``; the runner marks the section failed-to-measure and continues
  with the rest of the audit (it is NOT scored 0 — that isn't the user's fault).
- Listing genuinely not found (search returns nothing, stored id retired and
  re-search empty) → ``SectionResult(status="failed", score=0)`` with a
  "we couldn't find your listing" recommendation, so the dashboard explains it.

``place_id`` strategy: a stored ``google_place_id`` makes every recurring read a
cheap Place Details call and pins the audit to the exact listing so name/city
fuzziness can't silently start tracking the wrong business. When a stored id
stops resolving we self-heal by re-searching and handing the new id back to the
runner via ``discovered_fields`` (business) / ``CompetitorMetrics`` (competitor).
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from dataclasses import dataclass
from typing import Any

from scrapers.places import (
    PHOTO_CAP,
    PlaceRecord,
    PlacesUnavailable,
    place_details,
    search_text,
)
from scrapers.types import BusinessInput, ProgressCb, RecommendationDraft, SectionResult

logger = logging.getLogger(__name__)

# Google Maps place URLs embed the canonical place id as a ``ChIJ…`` token. We
# only trust that form — the hex ``0x…:0x…`` CID that some share links carry is
# not a valid Places API (New) resource id, so we'd rather fall through to a
# name+city search than send an id Place Details will reject.
_PLACE_ID_PATTERN = re.compile(r"(ChIJ[0-9A-Za-z_-]+)")


def _emit(progress: ProgressCb, step: str, detail: dict | None = None) -> None:
    if progress is None:
        return
    try:
        progress(step, detail)
    except Exception:
        # Narration is best-effort — never let it tank a real audit.
        logger.debug("maps progress callback failed for step=%s", step, exc_info=True)


def _extract_place_id(url: str | None) -> str | None:
    if not url:
        return None
    m = _PLACE_ID_PATTERN.search(url)
    return m.group(1) if m else None


def _search_query(name: str | None, city: str | None) -> str:
    return " ".join(part for part in (name, city) if part).strip()


def _maps_place_link(place_id: str | None) -> str | None:
    if not place_id:
        return None
    return f"https://www.google.com/maps/place/?q=place_id:{place_id}"


def _maps_search_link(business: BusinessInput) -> str:
    query = urllib.parse.quote_plus(_search_query(business.name, business.city))
    return f"https://www.google.com/maps/search/{query}"


# --- Own-business Maps pillar ------------------------------------------------


async def audit_maps(
    business: BusinessInput, *, progress: ProgressCb = None
) -> SectionResult:
    """Run the Maps audit for a business against the Places API.

    ``progress`` (optional) is the callback the runner injects so the scraper
    can narrate sub-phases (looking_up → reading_listing → found_listing) to
    the live-analysis stream. Old call sites that don't supply it get the old
    silent behavior.
    """
    _emit(progress, "looking_up", {"target": "Google Maps"})
    try:
        rec = await _resolve_listing(business)
    except PlacesUnavailable as exc:
        # Key/quota/network/5xx — not the user's fault. Raise so the runner
        # marks the section failed-to-measure rather than scoring it 0.
        raise RuntimeError(f"Places API unavailable: {exc}") from exc

    _emit(progress, "reading_listing")
    if rec is None:
        _emit(progress, "listing_not_found")
        raw = {"found": False, "url": business.maps_url or _maps_search_link(business)}
        return SectionResult(
            score=0,
            status="failed",
            raw_data=raw,
            recommendations=[_listing_not_found_rec(business)],
        )

    raw = _record_to_raw(rec)
    raw["url"] = (
        _maps_place_link(rec.place_id)
        or business.maps_url
        or _maps_search_link(business)
    )
    _emit(
        progress,
        "found_listing",
        {
            "name": raw.get("name"),
            "rating": raw.get("rating"),
            "review_count": raw.get("review_count"),
        },
    )

    score = _score_maps(raw)
    recommendations = _recommendations(raw)
    discovered: dict[str, str | None] = {}
    if rec.website_url:
        discovered["website"] = rec.website_url
    # Hand a freshly-resolved place_id back so the runner can persist it
    # (null-only merge) — turns the next audit into a cheap Place Details read.
    if rec.place_id and rec.place_id != business.google_place_id:
        discovered["google_place_id"] = rec.place_id
    return SectionResult(
        score=score,
        status="done",
        raw_data=raw,
        recommendations=recommendations,
        discovered_fields=discovered,
    )


async def _resolve_listing(business: BusinessInput) -> PlaceRecord | None:
    """Resolve a business to a Places record, cheapest route first.

    1. Stored ``google_place_id`` → Place Details (self-heals to search on a
       stale/invalid id).
    2. A ``ChIJ…`` id embedded in a user-supplied Maps URL → Place Details.
    3. Text Search by name + city (the reliable primary path).

    Returns ``None`` only when every route came up empty (genuine not-found).
    """
    if business.google_place_id:
        rec = await place_details(business.google_place_id)
        if rec is not None:
            return rec
        logger.info(
            "stored place_id %s no longer resolves; re-searching %r in %r",
            business.google_place_id,
            business.name,
            business.city,
        )

    url_id = _extract_place_id(business.maps_url)
    if url_id and url_id != business.google_place_id:
        rec = await place_details(url_id)
        if rec is not None:
            return rec

    results = await search_text(
        _search_query(business.name, business.city), max_results=1
    )
    return results[0] if results else None


def _record_to_raw(rec: PlaceRecord) -> dict[str, Any]:
    """Build the ``raw_data`` dict the score/recommendations/render code reads.

    Mirrors the key set the old Selenium ``_extract_panel`` produced so nothing
    downstream had to change. ``responds_to_reviews`` and
    ``recent_review_count_30d`` stay at their old conservative defaults — the
    Places API doesn't expose them (and the Selenium path hardcoded them too).
    """
    raw: dict[str, Any] = {"found": True, "name": rec.name}
    if rec.rating is not None:
        raw["rating"] = rec.rating
    if rec.review_count is not None:
        raw["review_count"] = rec.review_count
    if rec.category:
        raw["category"] = rec.category
    raw["has_hours"] = rec.has_hours
    raw["has_website_link"] = bool(rec.website_url)
    if rec.website_url:
        raw["website_url"] = rec.website_url
    raw["phone"] = rec.phone
    raw["address"] = rec.address
    raw["photo_count"] = rec.photo_count
    raw["responds_to_reviews"] = False
    raw["recent_review_count_30d"] = None
    return raw


def _listing_not_found_rec(business: BusinessInput) -> RecommendationDraft:
    """Surfaces the "we couldn't find your Maps listing" case as a finding.
    Without this, the dashboard's section detail rendered an F grade *and* the
    cheery "Nothing flagged here — this pillar is in good shape!" empty state,
    which left the user with no idea what to fix.
    """
    by_url = business.maps_url is not None
    return RecommendationDraft(
        severity="high",
        title="We couldn't find your Google Maps listing",
        body_markdown=(
            "**Why it matters**\n\n"
            "Google Maps is where most local customers find a business. If we "
            "can't pull up your listing from "
            + ("the URL you provided" if by_url else f"a search for **{business.name}** in **{business.city}**")
            + ", search engines probably can't either — that means missed calls, "
            "missed bookings, and a weaker local ranking overall.\n\n"
            "**How to fix it**\n\n"
            "1. Search for your business name in Google Maps from your phone "
            "and confirm a profile actually exists.\n"
            "2. If it does, copy the share link from Maps and paste it on the "
            "**Add business** page here — that gives us a direct route in.\n"
            "3. If it doesn't, claim or create a free **Google Business "
            "Profile** at business.google.com using the same business name "
            "and address you use everywhere else.\n"
            "4. Re-run this audit once the listing is live."
        ),
        estimated_impact="big",
        estimated_time="30 min",
    )


def _score_maps(raw: dict[str, Any]) -> int:
    score = 50
    rating = raw.get("rating")
    review_count = raw.get("review_count") or 0
    if rating is not None:
        if rating >= 4.5:
            score += 20
        elif rating >= 4.0:
            score += 15
        elif rating >= 3.5:
            score += 5
        else:
            score -= 10
    if review_count >= 500:
        score += 15
    elif review_count >= 100:
        score += 10
    elif review_count >= 25:
        score += 5

    if raw.get("has_hours"):
        score += 5
    if raw.get("has_website_link"):
        score += 5

    # Places API (New) returns at most PHOTO_CAP (10) photo references, so
    # ``photo_count`` saturates at 10 — we can distinguish "sparse" (<10) from
    # "plenty" (>=10) but no finer. Reward a well-photographed listing at the
    # cap and penalise a sparse one. (The old Selenium path used a 30+ bonus
    # that simply isn't observable through the API.)
    photo_count = raw.get("photo_count") or 0
    if photo_count >= PHOTO_CAP:
        score += 5
    elif photo_count < 10:
        score -= 5

    return max(0, min(100, score))


def _recommendations(raw: dict[str, Any]) -> list[RecommendationDraft]:
    recs: list[RecommendationDraft] = []

    if not raw.get("has_hours"):
        recs.append(
            RecommendationDraft(
                severity="high",
                title="Add your opening hours to Google Maps",
                body_markdown=(
                    "**Why it matters**\n\n"
                    "Hours are the single most-checked field on a Maps listing. If they're "
                    "missing, customers assume you might be closed and pick a competitor.\n\n"
                    "**How to fix it**\n\n"
                    "1. Open Google Maps → search your business → tap **Edit profile**.\n"
                    "2. Choose **Hours** and fill in each day, including any weekly closures.\n"
                    "3. Add **Special hours** for upcoming holidays so customers see accurate info.\n"
                    "4. Save and re-check from a logged-out browser to confirm they show."
                ),
                estimated_impact="big",
                estimated_time="10 min",
            )
        )

    if not raw.get("has_website_link"):
        recs.append(
            RecommendationDraft(
                severity="high",
                title="Link your website from your Maps listing",
                body_markdown=(
                    "**Why it matters**\n\n"
                    "A linked website is a clear quality signal to Google and to customers. "
                    "It also lets you measure traffic from Maps in your analytics.\n\n"
                    "**How to fix it**\n\n"
                    "1. Open Google Maps → your listing → **Edit profile** → **Contact**.\n"
                    "2. Paste your homepage URL into the **Website** field.\n"
                    "3. Save and reload Maps in a private window to confirm it appears."
                ),
                estimated_impact="medium",
                estimated_time="5 min",
            )
        )

    photo_count = raw.get("photo_count") or 0
    if photo_count < 10:
        recs.append(
            RecommendationDraft(
                severity="medium",
                title="Add 5 more photos to your listing",
                body_markdown=(
                    "**Why it matters**\n\n"
                    "Listings with 30+ recent photos get many more profile views. Customers "
                    "scroll the photos before deciding whether to visit.\n\n"
                    "**How to fix it**\n\n"
                    "1. Take 5 phone photos: storefront, interior, two popular items, the team.\n"
                    "2. Open Google Maps → your listing → **Add photo**.\n"
                    "3. Upload them across a week (not all at once) so they look natural.\n"
                    "4. Re-shoot every season — bright daylight photos perform best."
                ),
                estimated_impact="small",
                estimated_time="15 min",
            )
        )

    rating = raw.get("rating")
    review_count = raw.get("review_count") or 0
    if review_count < 25:
        recs.append(
            RecommendationDraft(
                severity="high",
                title="Ask 10 happy customers for a review this month",
                body_markdown=(
                    "**Why it matters**\n\n"
                    "Below 25 reviews you're invisible against established competitors. The "
                    "fastest, cheapest lift you can give your ranking is more recent reviews.\n\n"
                    "**How to fix it**\n\n"
                    "1. From Google Maps → your listing → **Share**, copy your review link.\n"
                    "2. Send it personally to your 10 most loyal customers (WhatsApp / SMS works).\n"
                    "3. Print a small card with a QR code at the till for walk-ins.\n"
                    "4. Aim for 2–3 new reviews a week — steady is better than a sudden burst."
                ),
                estimated_impact="big",
                estimated_time="30 min",
            )
        )
    elif rating is not None and rating < 4.0:
        recs.append(
            RecommendationDraft(
                severity="medium",
                title="Reply to recent negative reviews",
                body_markdown=(
                    "**Why it matters**\n\n"
                    "A polite owner reply softens the impact of a 1- or 2-star review and "
                    "shows future customers that you take feedback seriously.\n\n"
                    "**How to fix it**\n\n"
                    "1. Open Google Maps → your listing → **Reviews**, sort by lowest.\n"
                    "2. For each, thank them, apologise briefly, and offer to make it right offline.\n"
                    "3. Avoid arguing in the reply — it reads worse than the review itself.\n"
                    "4. Address the root cause internally so the next batch of reviews trends up."
                ),
                estimated_impact="medium",
                estimated_time="20 min",
                verify_signal="maps.replies_to_reviews",
            )
        )

    return recs


# --- Competitor metrics -----------------------------------------------------


@dataclass
class CompetitorMetrics:
    """Lightweight metric snapshot for one competitor listing.

    Phase 4 originally tracked rating + review_count per audit; 4.6 added
    Instagram follower + post count slots for the Market matrix / Deep Dive.
    Both IG fields stay ``None`` here — Places doesn't surface them; the
    competitor refresh job fills them from the IG Graph API separately.
    ``error`` is populated when the listing failed to resolve so the caller can
    persist a "we tried" row with null metrics without aborting the batch.
    ``google_place_id`` is the resolved id so the refresh job can backfill it
    onto the Competitor row (cheaper, pinned future reads).
    """

    competitor_id: int
    name: str | None = None
    rating: float | None = None
    review_count: int | None = None
    instagram_followers: int | None = None
    instagram_posts: int | None = None
    website_url: str | None = None
    instagram_url: str | None = None
    google_place_id: str | None = None
    error: str | None = None


@dataclass
class CompetitorScrapeTarget:
    """Per-competitor input to the bulk metric fetcher.

    Resolution prefers a stored ``google_place_id`` (cheap, exact), then a
    ``ChIJ…`` id from ``maps_url``, then a name+city Text Search. ``maps_url``
    also stays as a fallback query source when name/city aren't available.
    """

    competitor_id: int
    maps_url: str | None
    name: str | None = None
    city: str | None = None
    google_place_id: str | None = None


async def fetch_competitor_metrics(
    competitors: list[CompetitorScrapeTarget],
    *,
    progress: ProgressCb = None,
) -> list[CompetitorMetrics]:
    """Pull rating + review_count (+ website / place_id) per competitor.

    Sequential — the per-listing work is a single cheap HTTP call, and keeping
    it ordered lets callers ``zip`` the results back to their inputs.
    """
    results: list[CompetitorMetrics] = []
    for target in competitors:
        _emit(progress, "competitor_started", {"competitor_id": target.competitor_id})
        metric = await _fetch_one_competitor(target)
        results.append(metric)
        _emit(
            progress,
            "competitor_finished",
            {
                "competitor_id": target.competitor_id,
                "rating": metric.rating,
                "review_count": metric.review_count,
                "error": metric.error,
            },
        )
    return results


async def _fetch_one_competitor(target: CompetitorScrapeTarget) -> CompetitorMetrics:
    try:
        rec = await _resolve_competitor(target)
    except PlacesUnavailable as exc:
        # Record the failure on this row only — never abort the whole batch.
        return CompetitorMetrics(
            competitor_id=target.competitor_id, error=f"places_unavailable: {exc}"
        )
    if rec is None:
        return CompetitorMetrics(
            competitor_id=target.competitor_id, error="listing not found"
        )
    return CompetitorMetrics(
        competitor_id=target.competitor_id,
        name=rec.name,
        rating=rec.rating,
        review_count=rec.review_count,
        website_url=rec.website_url,
        # Places (New) doesn't surface an Instagram link — the website scraper
        # and discovery engine remain the IG-handle sources.
        instagram_url=None,
        google_place_id=rec.place_id,
    )


async def _resolve_competitor(target: CompetitorScrapeTarget) -> PlaceRecord | None:
    if target.google_place_id:
        rec = await place_details(target.google_place_id)
        if rec is not None:
            return rec
    url_id = _extract_place_id(target.maps_url)
    if url_id and url_id != target.google_place_id:
        rec = await place_details(url_id)
        if rec is not None:
            return rec
    if target.name and target.city:
        results = await search_text(
            _search_query(target.name, target.city), max_results=1
        )
        if results:
            return results[0]
    return None
