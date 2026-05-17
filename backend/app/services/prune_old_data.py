"""Prune heavy payloads off old audits to keep Postgres storage in check.

What it does
------------
Finds every audit whose ``finished_at`` is older than ``PRUNE_OLDER_THAN_DAYS``
(default 30) and zeroes out the heavy columns hanging off it:

* ``audit_sections.raw_data_json`` — per-scraper JSON dump (Maps, Website,
  Instagram, NAP). This is by far the biggest payload — Maps alone carries
  the full place panel summary. We set it to ``NULL``.

The lightweight rows (``audits``, ``audit_sections.score/status``,
``recommendations``, ``competitor_observations``) are left untouched so the
historical trend charts, recommendation history, and competitor overlays
keep rendering correctly. Only the bulk JSON payloads — which the UI never
re-reads after the audit is complete — get cleared.

Trigger surface
---------------
* ``scripts/run_scheduler.py`` registers this as a daily cron alongside the
  auto-audit dispatcher (see ``_PRUNE_FUNC``), so the periodic sweep
  happens even on quiet days.
* ``audit_runner.run_audit`` opportunistically enqueues a prune at the tail
  of every completed audit so storage stays trimmed without depending on
  the long-running scheduler process being healthy.

Both surfaces ultimately call ``prune_old_audit_data`` below, which is
idempotent — re-running it never re-clears already-NULL rows because the
WHERE clause filters those out.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session as DbSession

from app.db import SessionLocal
from app.models import Audit, AuditSection

logger = logging.getLogger(__name__)

# How old an audit must be (by ``finished_at``) before its raw payloads are
# eligible for pruning. Override with ``PRUNE_OLDER_THAN_DAYS`` if you ever
# want a longer/shorter retention window in a specific environment.
PRUNE_OLDER_THAN_DAYS = int(os.getenv("PRUNE_OLDER_THAN_DAYS", "30"))


def _cutoff() -> datetime:
    # Audit timestamps in this project are stored naive-UTC (see
    # Audit.finished_at) — comparing tz-aware values would raise. Match
    # the convention so the WHERE clause is valid on Postgres.
    return (datetime.now(timezone.utc) - timedelta(days=PRUNE_OLDER_THAN_DAYS)).replace(
        tzinfo=None
    )


def prune_old_audit_data(db: DbSession | None = None) -> dict[str, int | str]:
    """NULL heavy payload columns on audits older than the retention window.

    Returns a small summary dict so the caller (scheduler or audit runner)
    can log what the sweep actually did.

    Accepts an optional pre-opened ``Session`` for unit tests; in production
    callers it opens and closes its own ``SessionLocal``.
    """
    owns_session = db is None
    if db is None:
        db = SessionLocal()
    cutoff = _cutoff()
    try:
        # One UPDATE … FROM audits — sets raw_data_json to NULL on every
        # section row whose parent audit has been "done" for longer than the
        # retention window. ``is_not(None)`` skips rows we've already pruned
        # so re-runs do zero work.
        stmt = (
            update(AuditSection)
            .where(
                AuditSection.audit_id.in_(
                    db.query(Audit.id).filter(
                        Audit.finished_at.is_not(None),
                        Audit.finished_at < cutoff,
                    )
                ),
                AuditSection.raw_data_json.is_not(None),
            )
            .values(raw_data_json=None)
            .execution_options(synchronize_session=False)
        )
        result = db.execute(stmt)
        db.commit()
        rows_pruned = int(result.rowcount or 0)
        summary: dict[str, int | str] = {
            "rows_pruned": rows_pruned,
            "cutoff": cutoff.isoformat(),
            "retention_days": PRUNE_OLDER_THAN_DAYS,
        }
        logger.info("prune_old_audit_data: %s", summary)
        return summary
    finally:
        if owns_session:
            db.close()
