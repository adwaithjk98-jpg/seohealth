"""7-day global cache for tracked-competitor Maps scrapes (Phase 4).

The audit runner enumerates each business's tracked competitors and asks the
Maps scraper for fresh rating + review_count. Without this layer, two users
who track the same listing would scrape it twice — Selenium pays the Chrome
spin-up + network round-trip per call, and we burn a real proxy/IP budget on
duplicated work.

This module sits between the runner and ``scrapers.fetch_competitor_metrics``:

  1. For each requested ``(competitor_id, maps_url)``, look up the global
     ``competitor_metric_cache`` row by normalized URL.
  2. If the row exists *and* its ``last_scraped_at`` is within the TTL, build
     a ``CompetitorMetrics`` from the cached fields and skip Selenium for that
     URL.
  3. Otherwise add the URL to a "scrape now" list, hand it off to the live
     scraper, then UPSERT the result back into the cache so the next caller
     (different user, different audit) gets a cache hit.

The return value matches what ``fetch_competitor_metrics`` produces, so the
runner stays a one-line swap.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.orm import Session as DbSession

from app.models import CompetitorMetricCache
from scrapers import CompetitorMetrics, fetch_competitor_metrics
from scrapers.types import ProgressCb

logger = logging.getLogger(__name__)


# 7 days per the Phase 4 prompt. The chart-resolution cost of a stale point is
# bounded — even paid users only re-audit weekly, so the absolute worst case
# is one missed Bakehouse-Cafe-just-got-100-reviews delta surfaced a week late.
CACHE_TTL_DAYS = 7


def normalize_maps_url(url: str) -> str:
    """Best-effort normalization so equivalent Maps URLs share one cache row.

    Google emits several shapes (``/maps/place/<slug>/@lat,lng,15z/data=...``,
    ``goo.gl/maps/...`` shorteners, ``g.co/kgs/...`` knowledge-graph links).
    We don't try to resolve shorteners — that would itself cost a request —
    just lowercase the host, drop the query string and fragment, and trim a
    trailing slash. This collapses the common case where two tracked rows
    differ only in tracking params or session-scoped ``data=`` payloads.

    Two listings with genuinely different normalized URLs will get two cache
    rows; that's safe (just slightly less efficient than a place_id key).
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw.rstrip("/").lower()
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, "", ""))


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _is_fresh(row: CompetitorMetricCache, now: datetime) -> bool:
    return (now - row.last_scraped_at) < timedelta(days=CACHE_TTL_DAYS)


def _load_cache_rows(
    db: DbSession, keys: list[str]
) -> dict[str, CompetitorMetricCache]:
    if not keys:
        return {}
    rows = (
        db.query(CompetitorMetricCache)
        .filter(CompetitorMetricCache.cache_key.in_(keys))
        .all()
    )
    return {row.cache_key: row for row in rows}


def upsert_metric_cache(
    db: DbSession,
    cache_key: str,
    maps_url: str,
    metric: CompetitorMetrics,
    now: datetime | None = None,
) -> None:
    """Insert-or-update one cache row for the given scraped result.

    We persist even when the scrape errored — the cached row records the
    failure ``last_error`` so we don't immediately re-try on the next audit.
    The row is rewritten on every successful scrape, which is what bumps
    ``last_scraped_at`` and resets the TTL window.

    Does *not* commit — the caller controls transaction boundaries so
    multiple upserts in one fetch round trip as a single transaction.
    """
    if now is None:
        now = _now_naive()
    row = (
        db.query(CompetitorMetricCache)
        .filter(CompetitorMetricCache.cache_key == cache_key)
        .one_or_none()
    )
    if row is None:
        row = CompetitorMetricCache(
            cache_key=cache_key,
            maps_url=maps_url,
            name=metric.name,
            rating=metric.rating,
            review_count=metric.review_count,
            last_scraped_at=now,
            last_error=metric.error,
        )
        db.add(row)
    else:
        row.maps_url = maps_url
        row.name = metric.name if metric.name is not None else row.name
        # Don't overwrite a known-good rating with a None from a failed scrape.
        if metric.rating is not None:
            row.rating = metric.rating
        if metric.review_count is not None:
            row.review_count = metric.review_count
        row.last_scraped_at = now
        row.last_error = metric.error


async def fetch_competitor_metrics_cached(
    db: DbSession,
    competitors: list[tuple[int, str]],
    *,
    progress: ProgressCb = None,
) -> list[CompetitorMetrics]:
    """Drop-in replacement for ``fetch_competitor_metrics`` with global caching.

    Partition the inputs by cache freshness, scrape only the stale set, then
    splice cached + freshly-scraped results back into the original input
    order. The returned list always has exactly one entry per input.

    ``progress`` is only invoked for entries we actually scrape — cache hits
    are silent, since the SSE stream shouldn't show "scraping competitor X"
    when we didn't.
    """
    if not competitors:
        return []

    now = _now_naive()
    keys_by_index: list[str] = [
        normalize_maps_url(maps_url) for _, maps_url in competitors
    ]
    cache_rows = _load_cache_rows(db, [k for k in keys_by_index if k])

    results: list[CompetitorMetrics | None] = [None] * len(competitors)
    to_scrape: list[tuple[int, str]] = []
    scrape_indices: list[int] = []
    cache_hits = 0

    for idx, (competitor_id, maps_url) in enumerate(competitors):
        key = keys_by_index[idx]
        row = cache_rows.get(key)
        if row is not None and _is_fresh(row, now):
            results[idx] = CompetitorMetrics(
                competitor_id=competitor_id,
                name=row.name,
                rating=row.rating,
                review_count=row.review_count,
                error=row.last_error,
            )
            cache_hits += 1
        else:
            to_scrape.append((competitor_id, maps_url))
            scrape_indices.append(idx)

    logger.info(
        "competitor cache: %d hit / %d miss (ttl_days=%d)",
        cache_hits,
        len(to_scrape),
        CACHE_TTL_DAYS,
    )

    if to_scrape:
        scraped = await fetch_competitor_metrics(to_scrape, progress=progress)
        # ``fetch_competitor_metrics`` preserves input order, so zip is safe.
        for slot, metric in zip(scrape_indices, scraped):
            results[slot] = metric
            key = keys_by_index[slot]
            maps_url = competitors[slot][1]
            if key:
                upsert_metric_cache(db, key, maps_url, metric, now)
        db.commit()

    # All slots must be populated by here — if not, the scraper returned
    # fewer rows than we asked for, which is a contract bug worth surfacing.
    for idx, slot in enumerate(results):
        if slot is None:
            raise RuntimeError(
                f"competitor cache: scraper returned no result for index {idx}"
            )
    return [slot for slot in results if slot is not None]
