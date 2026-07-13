"""Native Discovery Scan engine — Places API (New), no Selenium.

Replaces the ``audit_scraper`` subprocess. A Discovery Scan sources competitor
candidates from **Places Text Search** (Google's own relevance order, paginated
to 60), qualifies them top-down against the filter DSL until ``num_leads`` are
kept, then best-effort enriches each keeper's ``instagram_url`` from its website.

🚨 Cost guardrail (memory ``places_api_cost_guardrail``): every candidate field
comes from the Text Search response — we make **zero Place Details calls per
candidate**. Deep-enrichment of a single listing only happens later, when a user
actually *tracks* one (the Part-A competitor path). So cost ≈ pages fetched
(1–3 Text Search calls), NOT ≈ candidates evaluated.

Ports the deterministic filter DSL (``parse_filters`` / ``evaluate_filter`` /
``_parse_numeric``) from the old engine verbatim so qualification behaviour is
unchanged. What the old engine got via Selenium field modules (IG followers,
email, etc.) isn't available here for arbitrary fields — the default field set
(name/address/category/rating/review_count/maps_url/website/instagram_url) is
fully served by Text Search + the website→IG enrichment below.

Deferred (see ``places_api_setup.md`` §8): the old engine's ``{template}``
sub-area fan-out (grid-split) to escape the 60-result ceiling on dense urban
categories. v1 uses a single query; add fan-out only if real usage needs it
(it multiplies Text Search cost).
"""

from __future__ import annotations

import asyncio
import logging
import re

import httpx
from bs4 import BeautifulSoup
from contextlib import aclosing

from scrapers.places import PlaceRecord, PlacesUnavailable, search_text_pages
from scrapers.website import DEFAULT_USER_AGENT, _extract_instagram_handle

logger = logging.getLogger(__name__)

# Discovery returns a small buffer beyond ``num_leads`` so the caller's
# post-hoc roster dedupe (``competitor_jobs._filter_out_own_roster``, which
# drops the user's own business + already-tracked rivals *after* the engine
# returns) doesn't leave the user short of what they asked for. The RQ job
# caps the deduped list back down to ``num_leads`` (PLACES_MIGRATION_CLOSEOUT
# F1). Only used when there are no enrichment filters — otherwise we keep the
# full sourced buffer for enrichment rejections to backfill against.
_ROSTER_DEDUPE_HEADROOM = 10


class DiscoveryError(RuntimeError):
    """Discovery couldn't complete (Places API unavailable, network, etc.).

    Named distinctly so the RQ job can flip the scan to ``failed`` and surface
    a message, mirroring the old ``CompetitorScraperError`` contract.
    """


# Fields served directly from a Places Text Search record, before any
# enrichment — the analogue of the old engine's ``MAPS_DATA_KEYS``. Filters on
# these apply at the cheap Stage-1 pass; filters on anything else (e.g.
# ``instagram_url``) apply after enrichment.
MAPS_DATA_KEYS = {
    "name",
    "rating",
    "review_count",
    "website",
    "phone",
    "address",
    "category",
    "maps_url",
    "business_status",
}

# Enrichment concurrency + per-site budget for the website→IG fetch.
_ENRICH_CONCURRENCY = 8
_ENRICH_TIMEOUT_SECONDS = 8.0


# ---------------------------------------------------------------------------
# Filter DSL — ported verbatim from audit_scraper/scrape_competitors.py
# (Selenium-free; only print→logger). Keeping the exact grammar means saved
# user filter strings ("rating>4.0", "category~=cafe", "website=yes") behave
# identically to the old engine.
# ---------------------------------------------------------------------------
def _parse_numeric(val_str: object) -> float:
    """Parse a numeric value, tolerant of surrounding text + k/M suffix.
    Handles: "4.3", "4.3 stars", "1,234", "1.2K", "2M"."""
    s = str(val_str).strip().replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*([kKmM]?)", s)
    if not m:
        raise ValueError(f"no numeric token in {val_str!r}")
    num = float(m.group(1))
    suffix = m.group(2).lower()
    if suffix == "k":
        num *= 1_000
    elif suffix == "m":
        num *= 1_000_000
    return num


def parse_filters(filter_string: str | None) -> list[dict]:
    """Parse 'rating>4.0,category~=cafe,website=yes' into structured conditions.

    ``~=`` = contains (case-insensitive), ``!~`` = not-contains. ``=yes/no`` on a
    field become existence checks. Multiple ``field~=X`` rules on one field
    collapse into a single OR group (single-valued fields can't AND-match two
    substrings).
    """
    if not filter_string:
        return []
    filters: list[dict] = []
    for part in filter_string.split(","):
        part = part.strip()
        if not part:
            continue
        # Order matters: longer ops first so `>=` doesn't get parsed as `>`.
        m = re.match(r"^(\w+)\s*(>=|<=|!=|!~|~=|>|<|=)\s*(.+)$", part)
        if not m:
            logger.warning("discovery filter: could not parse %r, skipping", part)
            continue
        field, op, val_raw = m.group(1), m.group(2), m.group(3).strip()

        if op not in ("~=", "!~") and val_raw.lower() in ("yes", "true"):
            filters.append(
                {"field": field, "op": op, "existence": True, "expect_exists": op != "!="}
            )
        elif op not in ("~=", "!~") and val_raw.lower() in ("no", "none", "false"):
            filters.append(
                {"field": field, "op": op, "existence": True, "expect_exists": op == "!="}
            )
        else:
            try:
                filters.append(
                    {"field": field, "op": op, "value": _parse_numeric(val_raw), "existence": False}
                )
            except ValueError:
                filters.append(
                    {"field": field, "op": op, "value": val_raw, "existence": False}
                )

    # Collapse multiple `field~=X` rules on the same field into one OR group.
    collapsed: list[dict] = []
    group_idx: dict[str, int] = {}
    for f in filters:
        if f["op"] == "~=" and not f["existence"]:
            if f["field"] in group_idx:
                existing = collapsed[group_idx[f["field"]]]
                existing.setdefault("values", [existing["value"]]).append(f["value"])
                continue
            group_idx[f["field"]] = len(collapsed)
        collapsed.append(f)
    return collapsed


def evaluate_filter(data: dict, filt: dict) -> bool:
    """Evaluate one filter against a lead dict. True = lead passes."""
    raw_val = data.get(filt["field"])
    if isinstance(raw_val, str) and raw_val.strip() == "":
        raw_val = None

    if filt["existence"]:
        return bool(raw_val) == filt["expect_exists"]

    if raw_val is None:  # missing data cannot be compared → fails
        return False
    op = filt["op"]
    if op in ("~=", "!~"):
        actual_s = str(raw_val).lower()
        if op == "~=":
            candidates = filt.get("values", [filt["value"]])
            return any(str(c).lower() in actual_s for c in candidates)
        return str(filt["value"]).lower() not in actual_s
    try:
        actual = _parse_numeric(raw_val)
        target = filt["value"]
        if op == ">":
            return actual > target
        if op == "<":
            return actual < target
        if op == ">=":
            return actual >= target
        if op == "<=":
            return actual <= target
        if op == "=":
            return actual == target
        if op == "!=":
            return actual != target
    except (ValueError, TypeError):
        actual_s = str(raw_val).lower()
        target_s = str(filt["value"]).lower()
        if op == "=":
            return actual_s == target_s
        if op == "!=":
            return actual_s != target_s
    return False


# ---------------------------------------------------------------------------
# Record → result dict
# ---------------------------------------------------------------------------
def _base_value(rec: PlaceRecord, field: str) -> object | None:
    """Value for a Text-Search-available field. Unknown/enriched fields → None."""
    return {
        "name": rec.name,
        "rating": rec.rating,
        "review_count": rec.review_count,
        "website": rec.website_url,
        "phone": rec.phone,
        "address": rec.address,
        "category": rec.category,
        "maps_url": rec.google_maps_uri,
        "business_status": rec.business_status,
    }.get(field)


def _record_to_dict(rec: PlaceRecord, fields: list[str]) -> dict:
    """Build the result dict with exactly the requested ``fields`` as keys.

    ``instagram_url`` starts as ``None`` and is filled by enrichment. Fields
    Places can't supply (email, followers, facebook_url, …) stay ``None`` — the
    old engine scraped those with Selenium; unsupported in the API-only path.

    ``place_id`` is always attached as a metadata key, independent of the
    requested ``fields``: we already hold the exact Places id at scan time, and
    threading it to the track path lets a tracked ``Competitor`` pin the precise
    listing (cheap Place Details) instead of re-resolving by name+city on first
    refresh — which can silently match the wrong branch and pin it forever
    (PLACES_MIGRATION_CLOSEOUT F2). Old scans predate this key, so consumers
    must ``.get('place_id')`` and fall back to the name+city search path.
    """
    result = {field: _base_value(rec, field) for field in fields}
    result["place_id"] = rec.place_id
    return result


# ---------------------------------------------------------------------------
# Enrichment: website → instagram_url (best-effort, parallel, non-Places)
# ---------------------------------------------------------------------------
async def _instagram_from_website(
    client: httpx.AsyncClient, website: str, sem: asyncio.Semaphore
) -> str | None:
    """Fetch a site and return its linked Instagram URL, or None. Never raises."""
    try:
        async with sem:
            resp = await client.get(website, follow_redirects=True)
        if resp.status_code != 200 or "text/html" not in resp.headers.get("content-type", ""):
            return None
        handle = _extract_instagram_handle(BeautifulSoup(resp.text, "lxml"))
        return f"https://instagram.com/{handle}" if handle else None
    except Exception:
        logger.debug("discovery IG enrich failed for %s", website, exc_info=True)
        return None


async def _enrich_instagram(leads: list[dict]) -> None:
    """Fill ``instagram_url`` in place for leads that have a website."""
    targets = [d for d in leads if d.get("website")]
    if not targets:
        return
    sem = asyncio.Semaphore(_ENRICH_CONCURRENCY)
    headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "text/html,*/*"}
    async with httpx.AsyncClient(timeout=_ENRICH_TIMEOUT_SECONDS, headers=headers) as client:
        urls = await asyncio.gather(
            *(_instagram_from_website(client, d["website"], sem) for d in targets)
        )
    for d, url in zip(targets, urls):
        d["instagram_url"] = url


# ---------------------------------------------------------------------------
# Public entry — the discovery_scan_job calls this
# ---------------------------------------------------------------------------
async def discover_competitors(
    query: str,
    num_leads: int,
    fields: list[str],
    filters: str | None = None,
) -> list[dict]:
    """Return up to ``num_leads`` qualified competitor dicts for ``query``.

    ``query`` is a free-text Maps-style search ("cafes in Kochi") whose locality
    is carried by the text itself — no explicit lat/lng bias needed. ``fields``
    are the keys each result dict must carry. ``filters`` is the DSL string.
    Raises :class:`DiscoveryError` if Places is unavailable.
    """
    parsed = parse_filters(filters)
    maps_filters = [f for f in parsed if f["field"] in MAPS_DATA_KEYS]
    enrichment_filters = [f for f in parsed if f["field"] not in MAPS_DATA_KEYS]
    need_ig = "instagram_url" in fields or any(
        f["field"] == "instagram_url" for f in enrichment_filters
    )
    target_buffer = num_leads + _ROSTER_DEDUPE_HEADROOM

    # Stage 1: source candidates page-by-page (Google's relevance order) and
    # qualify each against the Maps-level filters as it arrives. With no
    # enrichment filters, nothing downstream can reject a maps-qualified lead,
    # so we stop paginating the moment we have ``target_buffer`` of them —
    # usually one Text Search page instead of three (cost lever F1; Text Search
    # bills per request, not per result). With enrichment filters, later stages
    # can still reject, so we drain every available page to keep the full buffer
    # for enrichment rejections to backfill against.
    maps_qualified: list[dict] = []
    sourced = 0
    try:
        async with aclosing(search_text_pages(query)) as pages:
            async for page in pages:
                sourced += len(page)
                for rec in page:
                    lead = _record_to_dict(rec, fields)
                    if all(evaluate_filter(lead, f) for f in maps_filters):
                        maps_qualified.append(lead)
                if not enrichment_filters and len(maps_qualified) >= target_buffer:
                    break
    except PlacesUnavailable as exc:
        raise DiscoveryError(f"Places Text Search unavailable: {exc}") from exc

    consider = maps_qualified if enrichment_filters else maps_qualified[:target_buffer]

    # Stage 2: best-effort IG enrichment for the candidates we might return.
    if need_ig:
        await _enrich_instagram(consider)

    # Stage 3: apply enrichment-level filters + cap at the buffer. The RQ job
    # trims to ``num_leads`` after dropping the user's own roster, so returning
    # this small headroom is what keeps that dedupe from starving the result.
    results: list[dict] = []
    for lead in consider:
        if enrichment_filters and not all(
            evaluate_filter(lead, f) for f in enrichment_filters
        ):
            continue
        results.append(lead)
        if len(results) >= target_buffer:
            break

    logger.info(
        "discovery: query=%r sourced=%d maps_qualified=%d returned=%d",
        query,
        sourced,
        len(maps_qualified),
        len(results),
    )
    return results
