"""Daily off-peak dispatcher for tracked-competitor cache refreshes (Phase 4).

Cron entrypoint, fired at 02:00 UTC by ``scripts/run_scheduler.py``. Walks
every active ``Competitor`` row, projects it down to its normalized cache
key, and enqueues one refresh job per distinct key whose cached metrics are
stale (or missing).

Design notes
------------
* Refresh threshold is **6 days**, deliberately one day shorter than the
  read-side TTL in ``competitor_cache.CACHE_TTL_DAYS`` (7d). That way the
  cache always has a fresh entry by the time a real audit asks for it —
  if we refreshed at exactly 7 days, the very next audit would see a cache
  miss and fall back to the in-line Selenium scrape on the user's clock.
* Deduplication is keyed on the *normalized* maps_url. Two users tracking
  the same listing produce one refresh job between them — which is the
  whole point of the global cache.
* Jobs land in the low-priority ``competitor_jobs`` queue, drained by a
  dedicated worker process (``scripts.run_competitor_worker``). Self-audit
  workers never see them, so live user traffic is never slowed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session as DbSession

from app.db import SessionLocal
from app.models import Competitor, CompetitorMetricCache
from app.services.competitor_cache import normalize_maps_url
from app.workers.queue import enqueue_competitor_refresh

logger = logging.getLogger(__name__)

# Refresh proactively just before the read-side TTL expires. See module
# docstring for the rationale on the 1-day buffer.
REFRESH_OLDER_THAN_DAYS = 6


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _staleness_cutoff() -> datetime:
    return _now_naive() - timedelta(days=REFRESH_OLDER_THAN_DAYS)


def _collect_tracked_keys(db: DbSession) -> dict[str, str]:
    """Return ``{normalized_key: maps_url}`` for every active tracked competitor.

    Picks one canonical ``maps_url`` per normalized key (whichever the DB
    returns first). The cache row stores the normalized form anyway, so any
    representative URL works for triggering Selenium.
    """
    rows = (
        db.query(Competitor.maps_url)
        .filter(
            Competitor.archived_at.is_(None),
            Competitor.maps_url.is_not(None),
        )
        .all()
    )
    keys: dict[str, str] = {}
    for (maps_url,) in rows:
        if not maps_url:
            continue
        key = normalize_maps_url(maps_url)
        if not key:
            continue
        keys.setdefault(key, maps_url)
    return keys


def _stale_keys(
    db: DbSession, candidate_keys: list[str]
) -> set[str]:
    """Return the subset of ``candidate_keys`` whose cache row is missing or stale.

    Implementation: one ``SELECT cache_key, last_scraped_at`` round trip.
    A key with no cache row is stale by definition (cold).
    """
    if not candidate_keys:
        return set()
    cutoff = _staleness_cutoff()
    fresh: set[str] = set()
    rows = (
        db.query(
            CompetitorMetricCache.cache_key,
            CompetitorMetricCache.last_scraped_at,
        )
        .filter(CompetitorMetricCache.cache_key.in_(candidate_keys))
        .all()
    )
    for key, last_scraped_at in rows:
        if last_scraped_at is not None and last_scraped_at >= cutoff:
            fresh.add(key)
    return {k for k in candidate_keys if k not in fresh}


def refresh_due_competitors() -> dict[str, int | str]:
    """Scheduler entrypoint. Returns a small summary for the worker log.

    Idempotent within a single tick: dedupes by normalized cache key before
    enqueueing. Two ticks scheduled close together can still enqueue twice
    if the first batch hasn't drained yet — that's harmless (second pass
    just rewrites the same cache row a few minutes later).
    """
    db = SessionLocal()
    enqueued: list[str] = []
    try:
        tracked = _collect_tracked_keys(db)
        if not tracked:
            summary: dict[str, int | str] = {
                "tracked_unique": 0,
                "enqueued_count": 0,
                "ran_at": _now_naive().isoformat(),
            }
            logger.info("competitor refresh dispatch: %s", summary)
            return summary

        stale = _stale_keys(db, list(tracked.keys()))
        for key in stale:
            maps_url = tracked[key]
            try:
                enqueue_competitor_refresh(key, maps_url)
                enqueued.append(key)
            except Exception:
                logger.exception(
                    "competitor refresh dispatch: enqueue failed for key=%s", key
                )
        summary = {
            "tracked_unique": len(tracked),
            "stale_count": len(stale),
            "enqueued_count": len(enqueued),
            "refresh_older_than_days": REFRESH_OLDER_THAN_DAYS,
            "ran_at": _now_naive().isoformat(),
        }
        logger.info("competitor refresh dispatch: %s", summary)
        return summary
    finally:
        db.close()
