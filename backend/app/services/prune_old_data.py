"""Prune heavy payloads off old audits to keep Postgres storage in check.

What it does
------------
Finds every audit whose ``finished_at`` is older than ``PRUNE_OLDER_THAN_DAYS``
(default 30) and zeroes out the heavy columns hanging off it:

* ``audit_sections.raw_data_json`` — per-scraper JSON dump (Maps, Website,
  Instagram, NAP). This is by far the biggest payload — Maps alone carries
  the full place panel summary. We set it to ``NULL``.
* ``recommendations.body_markdown`` — the "why it matters / how to fix it"
  markdown body. Hundreds of bytes per row, ~10 rows per audit. After the
  retention window the user is past acting on the finding; only the title
  + severity are needed for the historical recommendation list. We set the
  body to ``NULL`` and lazy-fall-back to a short stub on the section
  detail page if someone digs into an old audit.

The lightweight rows + columns (``audits``, ``audit_sections.score/status``,
``recommendations.title/severity/fix_status``, ``competitor_observations``)
are left untouched so the historical trend charts, the sparkline on each
dashboard card, the recommendation history, and competitor overlays keep
rendering correctly. Only the bulky payloads — which the UI never re-reads
in steady state after the audit window closes — get cleared.

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
WHERE clauses filter those out.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session as DbSession

from app.db import SessionLocal
from app.models import Audit, AuditSection, Recommendation

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
        # Subquery — every audit older than the retention window. Used by
        # both UPDATEs below so the cutoff is computed once and both
        # tables get pruned against the same set of audits.
        old_audit_ids = db.query(Audit.id).filter(
            Audit.finished_at.is_not(None),
            Audit.finished_at < cutoff,
        )

        # 1) NULL raw_data_json on AuditSection rows. ``is_not(None)``
        # skips already-pruned rows so re-runs are free.
        section_stmt = (
            update(AuditSection)
            .where(
                AuditSection.audit_id.in_(old_audit_ids),
                AuditSection.raw_data_json.is_not(None),
            )
            .values(raw_data_json=None)
            .execution_options(synchronize_session=False)
        )
        section_result = db.execute(section_stmt)

        # 2) NULL body_markdown on Recommendation rows. We keep title +
        # severity + fix_status so historical "you marked this done" /
        # "this re-appeared" surfaces still work; the multi-paragraph
        # body is the only big column. Sentinel string makes section-
        # detail rendering predictable when someone digs into an old
        # audit ("(Details no longer kept — re-run to refresh.)").
        rec_stmt = (
            update(Recommendation)
            .where(
                Recommendation.audit_id.in_(old_audit_ids),
                Recommendation.body_markdown.is_not(None),
                Recommendation.body_markdown != "",
                Recommendation.body_markdown.notlike("(Details no longer kept%"),
            )
            .values(body_markdown="(Details no longer kept after the retention window — re-run the audit to refresh.)")
            .execution_options(synchronize_session=False)
        )
        rec_result = db.execute(rec_stmt)

        db.commit()
        section_rows = int(section_result.rowcount or 0)
        rec_rows = int(rec_result.rowcount or 0)
        summary: dict[str, int | str] = {
            "section_rows_pruned": section_rows,
            "recommendation_rows_pruned": rec_rows,
            # Kept for backwards compat with anything that read the old
            # ``rows_pruned`` key (e.g. log-greps in `/tmp/audit_*.log`).
            "rows_pruned": section_rows + rec_rows,
            "cutoff": cutoff.isoformat(),
            "retention_days": PRUNE_OLDER_THAN_DAYS,
        }
        logger.info("prune_old_audit_data: %s", summary)
        return summary
    finally:
        if owns_session:
            db.close()
