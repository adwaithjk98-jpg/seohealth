"""Auto-audit dispatcher — opt-in, cadence-aware, quota-aware (Phase 5.x).

Two surfaces:

* ``dispatch_due_audits()`` is enqueued by rq-scheduler on a daily cron
  (see ``scripts/run_scheduler.py``). It scans every non-archived business
  whose owner has **explicitly enabled** a schedule
  (``Business.audit_schedule_cadence`` set), checks the cadence interval
  against the last completed audit, and enqueues a fresh ``scheduled``
  audit for anything past due — *provided* the user still has weekly
  audit quota left. If the user is out of slots, the business is
  skipped this tick; the next nightly tick will try again.

* ``next_auto_audit_at()`` is a read-side helper consumed by the
  businesses API so the dashboard can render "Next auto-audit scheduled
  for …" without a second round-trip. Returns ``None`` when no cadence
  is set.

The dispatcher is fully idempotent: if a business already has a pending
or running audit (queued by an earlier tick, or kicked off manually) it's
skipped, so the worker never sees duplicates.

Architectural notes (2026-05-26 shift):

* Auto-audits used to fire automatically for every paid user's business
  on a fixed 7-day cadence. That was changed to **opt-in per business**
  because users want control over when their slots get spent — surprise
  audits chewed through the weekly cap without consent.
* Auto-audits no longer bypass the user's manual-audit quota. The
  ``create_audit`` endpoint and this dispatcher both gate on the same
  ``_audit_usage_this_week`` count, so scheduled + manual audits share
  one bucket.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc
from sqlalchemy.orm import Session as DbSession

from app.db import SessionLocal
from app.models import Audit, Business, User
from app.models.enums import AuditStatus, AuditTrigger, UserPlan
from app.services import subscriptions as subs_service
from app.workers.queue import enqueue_audit

logger = logging.getLogger(__name__)


# Cadence → interval in days. Add new values here when the UI gains them.
_CADENCE_DAYS: dict[str, int] = {
    "weekly": 7,
    "biweekly": 14,
    "monthly": 30,
}


def _now_naive() -> datetime:
    # Postgres columns in this project are stored naive-UTC (see Audit.finished_at);
    # comparing timezone-aware values would raise. Keep everything naive-UTC.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _last_completed_at(db: DbSession, business_id: int) -> datetime | None:
    audit = (
        db.query(Audit)
        .filter(
            Audit.business_id == business_id,
            Audit.status == AuditStatus.done,
        )
        .order_by(desc(Audit.finished_at), desc(Audit.id))
        .first()
    )
    if audit is None or audit.finished_at is None:
        return None
    return audit.finished_at


def _has_active_audit(db: DbSession, business_id: int) -> bool:
    """True if any audit for this business is still pending or running."""
    return (
        db.query(Audit.id)
        .filter(
            Audit.business_id == business_id,
            Audit.status.in_([AuditStatus.pending, AuditStatus.running]),
        )
        .first()
        is not None
    )


def _cadence_days(cadence: str | None) -> int | None:
    if cadence is None:
        return None
    return _CADENCE_DAYS.get(cadence)


def _audit_count_this_week(db: DbSession, user_id: int) -> int:
    """Mirror of ``api/audits._audit_usage_this_week`` count side.

    Duplicating the SQL here (instead of importing) keeps the dispatcher
    free of FastAPI request-cycle imports. If the rolling-window rule
    ever changes, both call sites must update together — there's a
    matching ``audits._audit_usage_this_week`` comment for symmetry.
    """
    window_start = _now_naive() - timedelta(days=7)
    return (
        db.query(Audit.id)
        .join(Business, Audit.business_id == Business.id)
        .filter(
            Business.user_id == user_id,
            Audit.started_at >= window_start,
            Audit.status != AuditStatus.failed,
        )
        .count()
    )


def next_auto_audit_at(
    db: DbSession, business: Business, user: User
) -> datetime | None:
    """When the next auto-audit will fire for this (business, user) pair.

    Returns ``None`` when:
      * the user isn't on a tier that gets auto-audits,
      * the business is archived,
      * **or the business has no cadence set** (the opt-in default).

    Returns ``now`` (clamped) when the business is past due — the next
    scheduler tick will pick it up if the user has quota.
    """
    if user.plan == UserPlan.free:
        return None
    if business.archived_at is not None:
        return None
    days = _cadence_days(business.audit_schedule_cadence)
    if days is None:
        return None
    last = _last_completed_at(db, business.id)
    if last is None:
        return _now_naive()
    due_at = last + timedelta(days=days)
    now = _now_naive()
    return due_at if due_at > now else now


# Schedule spread: instead of one daily 06:00 thundering herd that dumps every
# due audit into the queue at once (where a single worker drains them serially
# and competes with live user audits), the dispatcher runs HOURLY and each
# business only fires in its own deterministic hour bucket. id % 24 spreads the
# daily load evenly across 24 hours with zero per-business state. A weekly audit
# lands at the same hour each week (its bucket); cadence is unaffected.
_SPREAD_BUCKETS = 24


def _hour_bucket(business_id: int) -> int:
    """Deterministic 0–23 hour slot for a business. Stable across runs."""
    return business_id % _SPREAD_BUCKETS


def dispatch_due_audits(force_all: bool = False) -> dict[str, int | str]:
    """Scheduler entrypoint. Returns a small summary for the worker log.

    Walks every non-archived paid-tier business that has a cadence set,
    enqueues a scheduled audit if past due, skips when the user is out of
    weekly quota or the business already has an in-flight audit. Per-user
    quota counter is recomputed *as we go* so a user with multiple
    overdue businesses doesn't blow past their cap in a single tick.

    Runs hourly; each due business only fires in its own ``id % 24`` hour
    bucket, spreading the load across the day. Pass ``force_all=True`` to
    bypass the hour gate (e.g. a manual "run every due audit now").
    """
    now = _now_naive()
    db = SessionLocal()
    enqueued: list[int] = []
    skipped_active = 0
    skipped_not_due = 0
    skipped_no_quota = 0
    skipped_off_hour = 0
    examined = 0
    try:
        rows = (
            db.query(Business, User)
            .join(User, Business.user_id == User.id)
            .filter(
                Business.archived_at.is_(None),
                Business.audit_schedule_cadence.is_not(None),
                User.plan != UserPlan.free,
            )
            .all()
        )

        # Cache per-user quota usage across iterations so we don't
        # SELECT for every row.
        used_by_user: dict[int, int] = {}
        limit_by_user: dict[int, int] = {}

        for business, user in rows:
            examined += 1
            # Schedule spread: only this hour's bucket fires (unless forced).
            # Cheapest gate first, so we skip ~23/24 of rows before any
            # per-business queries.
            if not force_all and _hour_bucket(business.id) != now.hour:
                skipped_off_hour += 1
                continue
            if _has_active_audit(db, business.id):
                skipped_active += 1
                continue
            days = _cadence_days(business.audit_schedule_cadence)
            if days is None:
                # Defensive: filter already excluded NULL, but a typo
                # like ``'weeky'`` would slip through with days=None.
                # Treat as "no schedule" and skip silently.
                skipped_not_due += 1
                continue
            last = _last_completed_at(db, business.id)
            if last is not None and (now - last) < timedelta(days=days):
                skipped_not_due += 1
                continue

            # Quota gate. Manual + scheduled share one bucket.
            if user.id not in used_by_user:
                used_by_user[user.id] = _audit_count_this_week(db, user.id)
                limit_by_user[user.id] = subs_service.TIER_LIMITS[user.plan][
                    "audits_per_week"
                ]
            if used_by_user[user.id] >= limit_by_user[user.id]:
                skipped_no_quota += 1
                continue

            audit = Audit(
                business_id=business.id,
                status=AuditStatus.pending,
                trigger=AuditTrigger.scheduled,
            )
            db.add(audit)
            db.commit()
            db.refresh(audit)
            enqueue_audit(audit.id)
            enqueued.append(audit.id)
            used_by_user[user.id] += 1

        summary: dict[str, int | str] = {
            "examined": examined,
            "enqueued_count": len(enqueued),
            "enqueued_audit_ids": ",".join(str(i) for i in enqueued),
            "skipped_active": skipped_active,
            "skipped_not_due": skipped_not_due,
            "skipped_no_quota": skipped_no_quota,
            "skipped_off_hour": skipped_off_hour,
            "ran_at": now.isoformat(),
        }
        logger.info("auto-audit dispatch: %s", summary)
        return summary
    finally:
        db.close()
