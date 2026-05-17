"""Auto-audit dispatcher — the heart of Phase 3's recurring-audit engine.

Two surfaces:

* ``dispatch_due_audits()`` is enqueued by rq-scheduler on a daily cron
  (see ``scripts/run_scheduler.py``). It scans every non-archived business
  belonging to a paid user, checks the last completed audit's age, and
  enqueues a fresh ``scheduled`` audit for anything past its weekly
  cadence. Free-tier businesses are intentionally excluded — auto-audits
  are a paid feature (AuditAppPlan §8 "Pricing model" + the upgrade
  banner the dashboard shows free users).

* ``next_auto_audit_at()`` is a read-side helper consumed by the
  businesses API so the dashboard can render "Next auto-audit scheduled
  for …" without a second round-trip.

The dispatcher is fully idempotent: if a business already has a pending /
running audit (queued by an earlier tick, or kicked off manually) it's
skipped, so the worker never sees duplicates.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc
from sqlalchemy.orm import Session as DbSession

from app.db import SessionLocal
from app.models import Audit, Business, User
from app.models.enums import AuditStatus, AuditTrigger, UserPlan
from app.workers.queue import enqueue_audit

logger = logging.getLogger(__name__)

# Paid tier: weekly. Free tier: no auto-audits (the prompt's constraint
# checklist: "Are free users restricted from auto-audits? Yes"). If we ever
# introduce a free-tier monthly cadence the only change here is mapping
# UserPlan.free -> 30.
_PAID_CADENCE_DAYS = 7


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
    """True if any audit for this business is still pending or running.

    Mirrors ``_running_audit_id`` in api/businesses.py — we don't want the
    scheduler to stack a second job on top of one already in flight.
    """
    return (
        db.query(Audit.id)
        .filter(
            Audit.business_id == business_id,
            Audit.status.in_([AuditStatus.pending, AuditStatus.running]),
        )
        .first()
        is not None
    )


def next_auto_audit_at(
    db: DbSession, business: Business, user: User
) -> datetime | None:
    """When the next auto-audit will fire for this (business, user) pair.

    Returns ``None`` if the user isn't on a tier that gets auto-audits, or
    the business is archived. Returns ``now`` (clamped to "today") when the
    business is already past due — the next scheduler tick will pick it up.
    """
    if user.plan != UserPlan.paid:
        return None
    if business.archived_at is not None:
        return None
    last = _last_completed_at(db, business.id)
    if last is None:
        return _now_naive()
    due_at = last + timedelta(days=_PAID_CADENCE_DAYS)
    now = _now_naive()
    return due_at if due_at > now else now


def dispatch_due_audits() -> dict[str, int | str]:
    """Scheduler entrypoint. Returns a small summary so the worker log shows
    what the tick actually did.

    Opens its own ``SessionLocal()`` — RQ workers are sync and never see the
    FastAPI request-scoped session, so this function has to be self-contained.
    """
    now = _now_naive()
    db = SessionLocal()
    enqueued: list[int] = []
    skipped_active = 0
    skipped_not_due = 0
    examined = 0
    try:
        # One join + one round-trip; the dispatcher should be fast enough to
        # run inside a single scheduler tick even at a few thousand businesses.
        rows = (
            db.query(Business, User)
            .join(User, Business.user_id == User.id)
            .filter(
                Business.archived_at.is_(None),
                User.plan == UserPlan.paid,
            )
            .all()
        )
        for business, _user in rows:
            examined += 1
            if _has_active_audit(db, business.id):
                skipped_active += 1
                continue
            last = _last_completed_at(db, business.id)
            if last is not None and (now - last) < timedelta(
                days=_PAID_CADENCE_DAYS
            ):
                skipped_not_due += 1
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
        summary: dict[str, int | str] = {
            "examined": examined,
            "enqueued_count": len(enqueued),
            "enqueued_audit_ids": ",".join(str(i) for i in enqueued),
            "skipped_active": skipped_active,
            "skipped_not_due": skipped_not_due,
            "ran_at": now.isoformat(),
        }
        logger.info("auto-audit dispatch: %s", summary)
        return summary
    finally:
        db.close()
