"""Weekly digest assembly + dispatch.

Builds a per-user payload that summarises every active business's
state since the last digest: score + delta, confirmed fixes, new
findings, and the single highest-impact open recommendation. Paid-tier
only — free users don't get the digest (and don't generate enough
audit cadence to make one useful).

Triggered weekly by the scheduler (see ``scripts/run_scheduler.py``).
Idempotent at the calling layer: if a digest dispatch runs twice in
the same week, both runs will send — there's no de-dup table. Cron
the dispatch at a quiet time once a week and accept that as the
contract; we'll add a ``last_digest_sent_at`` column if we ever need
to harden it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Audit, Business, User
from app.models.enums import AuditStatus, UserPlan
from app.services.audit_view import build_audit_detail
from app.services.email_service import send_weekly_digest_email


logger = logging.getLogger(__name__)


def _latest_two_audits(db: Session, business_id: int) -> list[Audit]:
    return (
        db.query(Audit)
        .filter(
            Audit.business_id == business_id,
            Audit.status == AuditStatus.done,
        )
        .order_by(desc(Audit.finished_at), desc(Audit.id))
        .limit(2)
        .all()
    )


def _top_open_finding(detail: dict) -> str | None:
    """Pick the highest-severity open recommendation across sections.

    Severity ranking mirrors the frontend's ``severityRank`` so the
    digest's "top finding" agrees with what the user sees on the
    dashboard. ``None`` when the business has no open recs (lovely
    state — the digest still mentions the score).
    """
    severity_rank = {"high": 0, "medium": 1, "low": 2}
    candidates: list[dict] = []
    for sec in detail.get("sections", []):
        for rec in sec.get("recommendations", []):
            if rec.get("fix_status") != "open":
                continue
            candidates.append(rec)
    if not candidates:
        return None
    candidates.sort(key=lambda r: (severity_rank.get(r.get("severity"), 99), r.get("id") or 0))
    return candidates[0].get("title")


def build_user_digest(db: Session, user: User, dashboard_base_url: str) -> dict | None:
    """Assemble the digest payload for one user.

    Returns ``None`` when the user has no completed audits across any
    active business — there's nothing to summarise yet, and a digest
    that says "no data" is worse than no email.
    """
    active = (
        db.query(Business)
        .filter(Business.user_id == user.id, Business.archived_at.is_(None))
        .order_by(Business.added_at)
        .all()
    )
    business_rows: list[dict] = []
    for biz in active:
        recent = _latest_two_audits(db, biz.id)
        if not recent:
            continue
        latest = recent[0]
        prev = recent[1] if len(recent) > 1 else None
        detail = build_audit_detail(db, latest)
        score = detail.get("overall_score")
        prev_score = (
            build_audit_detail(db, prev).get("overall_score") if prev is not None else None
        )
        delta = (score - prev_score) if (score is not None and prev_score is not None) else None
        since = detail.get("since_last_check") or {}
        business_rows.append(
            {
                "id": biz.id,
                "name": biz.name,
                "score": score,
                "delta": delta,
                "confirmed_count": len(since.get("confirmed") or []),
                "new_count": len(since.get("new") or []),
                "top_finding": _top_open_finding(detail),
            }
        )
    if not business_rows:
        return None

    greeting = (user.display_name or user.email.split("@", 1)[0] or "there").strip()
    return {
        "greeting_name": greeting,
        "businesses": business_rows,
        "dashboard_url": f"{dashboard_base_url.rstrip('/')}/dashboard",
    }


def dispatch_weekly_digests(
    db: Session | None = None,
    dashboard_base_url: str = "https://adwaiths-macbook-air.taileffa22.ts.net",
) -> dict[str, int]:
    """Walk every paid user, build a digest, send.

    Returns a small summary the scheduler can log. Doesn't raise on
    individual send failures — one user's Resend hiccup shouldn't tank
    the rest of the batch.
    """
    owns_session = db is None
    if db is None:
        db = SessionLocal()
    sent = 0
    skipped_no_data = 0
    failed = 0
    try:
        paid_users = (
            db.query(User)
            .filter(User.plan == UserPlan.paid)
            .all()
        )
        for user in paid_users:
            try:
                payload = build_user_digest(db, user, dashboard_base_url)
                if payload is None:
                    skipped_no_data += 1
                    continue
                send_weekly_digest_email(user.email, payload)
                sent += 1
            except Exception:  # noqa: BLE001
                logger.exception(
                    "weekly_digest: send failed for user %s (id=%s)", user.email, user.id
                )
                failed += 1
        summary = {
            "sent": sent,
            "skipped_no_data": skipped_no_data,
            "failed": failed,
            "paid_user_count": len(paid_users),
            "ran_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        }
        logger.info("dispatch_weekly_digests: %s", summary)
        return summary
    finally:
        if owns_session:
            db.close()


# Re-export for the scheduler so it can register the cron without
# importing email_service directly.
__all__ = ["build_user_digest", "dispatch_weekly_digests"]
