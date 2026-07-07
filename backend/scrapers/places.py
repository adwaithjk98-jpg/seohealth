"""Google Places API (New) HTTP client.

Replaces the Selenium ``maps.py`` scraper as the data source for the Maps
audit pillar and competitor refresh. Two endpoints, one normalized shape:

* :func:`place_details` — GET ``/v1/places/{id}``; the cheap recurring read once
  we've stored a ``place_id`` (Enterprise SKU, ~$20/1k). Returns ``None`` when
  the id is NOT_FOUND so the caller can self-heal by re-resolving.
* :func:`search_text` — POST ``/v1/places:searchText``; resolves a ``place_id``
  from a name+city the first time (and on self-heal). Enterprise SKU, ~$35/1k.

Both normalize to :class:`PlaceRecord`. Field masks are pinned to the fields we
need; ``rating`` + ``userRatingCount`` force the Enterprise tier, and opening
hours / website / phone / address / photos / primaryType ride in that same
tier at no extra cost. We deliberately NEVER request ``reviews`` (review text is
the pricier Atmosphere SKU) — the aggregate rating + count is all the audit uses.

Cost guardrail (memory ``places_api_cost_guardrail``): callers must NOT loop
:func:`place_details` per discovery candidate. Discovery lives in the separate
``audit_scraper`` engine; this module only serves the audit + competitor paths,
which read exactly one place each.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_BASE = "https://places.googleapis.com/v1"
_TIMEOUT_SECONDS = 20.0

# Enterprise-tier field mask. ``rating``/``userRatingCount`` force Enterprise;
# everything else here is same-or-lower tier so it adds no cost. NEVER add
# ``reviews`` (review text = Atmosphere, a pricier SKU) — we only need the
# aggregate rating. ``googleMapsUri``/``businessStatus`` are for discovery (a
# real Maps link + open/closed status); harmless to the audit path, no cost bump.
_DETAILS_FIELD_MASK = (
    "id,displayName,rating,userRatingCount,websiteUri,nationalPhoneNumber,"
    "regularOpeningHours,primaryTypeDisplayName,formattedAddress,photos,"
    "googleMapsUri,businessStatus"
)
# Text Search returns the same objects nested under ``places`` — prefix each.
_SEARCH_FIELD_MASK = ",".join(
    f"places.{field}" for field in _DETAILS_FIELD_MASK.split(",")
)

# Text Search caps at 20 results/page and 60 total (3 pages via nextPageToken).
_SEARCH_PAGE_SIZE = 20
_SEARCH_MAX_RESULTS = 60

# Places API (New) returns at most this many photo references per place, so
# ``photo_count`` saturates here — we can tell "few" from "plenty" but not an
# exact total above the cap. The Maps scorer is written to account for this.
PHOTO_CAP = 10


class PlacesUnavailable(RuntimeError):
    """The Places API couldn't be reached or returned an error we can't
    attribute to "listing not found" — a missing/invalid key, quota/429, a
    5xx, or a network failure. Callers should treat the section as
    failed-to-measure (not the user's fault), never score it 0.
    """


@dataclass
class PlaceRecord:
    """Normalized snapshot of one place, shared by both endpoints.

    ``None`` means "the API didn't return this field for this place." Field
    names mirror what ``maps.py`` builds its ``raw_data`` dict + competitor
    metrics from, so the migration stayed invisible to every caller.
    """

    place_id: str | None = None
    name: str | None = None
    rating: float | None = None
    review_count: int | None = None
    category: str | None = None
    website_url: str | None = None
    phone: str | None = None
    address: str | None = None
    has_hours: bool = False
    photo_count: int | None = None
    # Discovery-only extras (the audit path ignores these).
    google_maps_uri: str | None = None
    business_status: str | None = None


def _localized_text(value: Any) -> str | None:
    """Places wraps display strings as ``{"text": ..., "languageCode": ...}``."""
    if isinstance(value, dict):
        text = value.get("text")
        return text or None
    if isinstance(value, str):
        return value or None
    return None


def _normalize(place: dict[str, Any]) -> PlaceRecord:
    photos = place.get("photos") or []
    return PlaceRecord(
        place_id=place.get("id"),
        name=_localized_text(place.get("displayName")),
        rating=place.get("rating"),
        review_count=place.get("userRatingCount"),
        category=_localized_text(place.get("primaryTypeDisplayName")),
        website_url=place.get("websiteUri") or None,
        phone=place.get("nationalPhoneNumber") or None,
        address=place.get("formattedAddress") or None,
        has_hours=bool(place.get("regularOpeningHours")),
        photo_count=min(len(photos), PHOTO_CAP),
        google_maps_uri=place.get("googleMapsUri") or None,
        business_status=place.get("businessStatus") or None,
    )


def _error_detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        return body.get("error", {}).get("message") or resp.text[:200]
    except ValueError:
        return resp.text[:200]


async def place_details(place_id: str) -> PlaceRecord | None:
    """Fetch a single place by its stored ``place_id``.

    Returns ``None`` when the id is NOT_FOUND (Google occasionally re-IDs or
    retires a listing) — the signal for the caller to re-resolve via
    :func:`search_text` and overwrite the stored id. Raises
    :class:`PlacesUnavailable` on any other failure.
    """
    if not settings.places_api_key:
        raise PlacesUnavailable("PLACES_API_KEY is not configured")
    if not place_id:
        return None

    headers = {
        "X-Goog-Api-Key": settings.places_api_key,
        "X-Goog-FieldMask": _DETAILS_FIELD_MASK,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.get(f"{_BASE}/places/{place_id}", headers=headers)
    except httpx.HTTPError as exc:
        raise PlacesUnavailable(f"Place Details request failed: {exc}") from exc

    if resp.status_code == 200:
        return _normalize(resp.json())
    # A stored/extracted id can go stale (Google re-IDs a listing → 404) or be
    # malformed (corrupted, or a bad id scraped from a Maps URL → 400 "not a
    # valid Place ID"). Both mean "re-resolve via search", not "fail the audit".
    detail = _error_detail(resp)
    if resp.status_code == 404 or (
        resp.status_code == 400 and "place id" in detail.lower()
    ):
        logger.info(
            "Place Details %s for place_id=%s; treating as not-found (self-heal)",
            resp.status_code,
            place_id,
        )
        return None
    raise PlacesUnavailable(
        f"Place Details returned HTTP {resp.status_code}: {detail}"
    )


async def search_text(query: str, *, max_results: int = 1) -> list[PlaceRecord]:
    """Resolve places from a free-text query (e.g. ``"<name> <city>"``).

    ``max_results=1`` (default) is the audit/self-heal use — one best match.
    Discovery passes a higher ``max_results`` (up to ``_SEARCH_MAX_RESULTS``=60)
    and paginates via ``nextPageToken`` (≤20/page). Each request is one billed
    Text Search call, so cost ≈ pages fetched — NEVER a Place Details per
    candidate (that's the cost guardrail). Returns an empty list when nothing
    matched; raises :class:`PlacesUnavailable` on an API/network failure.
    """
    if not settings.places_api_key:
        raise PlacesUnavailable("PLACES_API_KEY is not configured")
    if not query or not query.strip():
        return []

    want = max(1, min(max_results, _SEARCH_MAX_RESULTS))
    headers = {
        "X-Goog-Api-Key": settings.places_api_key,
        "X-Goog-FieldMask": _SEARCH_FIELD_MASK,
        "Content-Type": "application/json",
    }
    records: list[PlaceRecord] = []
    page_token: str | None = None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            while len(records) < want:
                body: dict[str, Any] = {
                    "textQuery": query.strip(),
                    "pageSize": min(_SEARCH_PAGE_SIZE, want - len(records)),
                }
                # When paginating, textQuery must stay identical to page 1.
                if page_token:
                    body["pageToken"] = page_token
                resp = await client.post(
                    f"{_BASE}/places:searchText", headers=headers, json=body
                )
                if resp.status_code != 200:
                    raise PlacesUnavailable(
                        f"Text Search returned HTTP {resp.status_code}: "
                        f"{_error_detail(resp)}"
                    )
                data = resp.json()
                records.extend(_normalize(p) for p in (data.get("places") or []))
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
    except httpx.HTTPError as exc:
        raise PlacesUnavailable(f"Text Search request failed: {exc}") from exc

    return records[:want]
