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
  miss and fall back to the in-line Places API fetch on the user's clock.
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
from app.models import Business, Competitor, CompetitorMetricCache, User
from app.models.enums import UserPlan
from app.services.competitor_cache import normalize_maps_url
from app.workers.queue import enqueue_competitor_refresh

logger = logging.getLogger(__name__)

# Refresh proactively just before the read-side TTL expires. See module
# docstring for the rationale on the 1-day buffer.
# Pro (and any non-Max) refresh threshold: ~weekly (one day short of 7 so the
# next audit doesn't see a just-expired cache). Max refreshes ~twice a week.
REFRESH_OLDER_THAN_DAYS = 6
MAX_REFRESH_OLDER_THAN_DAYS = 3


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _collect_tracked(db: DbSession) -> dict[str, tuple[str, int]]:
    """Return ``{normalized_key: (maps_url, refresh_days)}`` for every active
    tracked competitor.

    ``refresh_days`` is the *tightest* cadence among the users tracking that
    competitor: if any Max user tracks it, it refreshes on the Max cadence
    (~twice a week) — which benefits every user sharing that cache row, since
    the cache is URL-scoped and deduped. Everyone else gets the weekly cadence.
    """
    rows = (
        db.query(Competitor.maps_url, User.plan)
        .join(Business, Competitor.business_id == Business.id)
        .join(User, Business.user_id == User.id)
        .filter(
            Competitor.archived_at.is_(None),
            Competitor.maps_url.is_not(None),
        )
        .all()
    )
    out: dict[str, tuple[str, int]] = {}
    for maps_url, plan in rows:
        if not maps_url:
            continue
        key = normalize_maps_url(maps_url)
        if not key:
            continue
        days = MAX_REFRESH_OLDER_THAN_DAYS if plan == UserPlan.max else REFRESH_OLDER_THAN_DAYS
        if key in out:
            url, existing_days = out[key]
            out[key] = (url, min(existing_days, days))
        else:
            out[key] = (maps_url, days)
    return out


def _stale_keys(
    db: DbSession, tracked: dict[str, tuple[str, int]]
) -> set[str]:
    """Return the subset of tracked keys whose cache row is missing or older
    than that key's own refresh window (Max-tracked keys use the tighter 3-day
    window; everyone else 6). A key with no cache row is stale by definition.
    """
    if not tracked:
        return set()
    now = _now_naive()
    last_by_key: dict[str, datetime | None] = {}
    rows = (
        db.query(
            CompetitorMetricCache.cache_key,
            CompetitorMetricCache.last_scraped_at,
        )
        .filter(CompetitorMetricCache.cache_key.in_(list(tracked.keys())))
        .all()
    )
    for key, last_scraped_at in rows:
        last_by_key[key] = last_scraped_at

    stale: set[str] = set()
    for key, (_url, refresh_days) in tracked.items():
        last = last_by_key.get(key)
        if last is None or last < now - timedelta(days=refresh_days):
            stale.add(key)
    return stale


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
        tracked = _collect_tracked(db)
        if not tracked:
            summary: dict[str, int | str] = {
                "tracked_unique": 0,
                "enqueued_count": 0,
                "ran_at": _now_naive().isoformat(),
            }
            logger.info("competitor refresh dispatch: %s", summary)
            return summary

        stale = _stale_keys(db, tracked)
        for key in stale:
            maps_url = tracked[key][0]
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
