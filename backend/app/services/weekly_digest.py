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
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import User
from app.models.enums import UserPlan
from app.services.email_service import send_weekly_digest_email
from app.services.weekly_insights import build_report_index


logger = logging.getLogger(__name__)


def build_user_digest(db: Session, user: User, dashboard_base_url: str) -> dict | None:
    """Assemble the Weekly Insights *teaser* email payload for one user.

    Shares the same engine as the in-app scroll report (``build_report_index``)
    so the email's per-business headline is exactly the report's lead. The
    email is a doorway: one headline per business + a link to the full in-app
    scroll. Returns ``None`` when the user has no completed audits across any
    active business — a teaser with nothing to tease is worse than no email.
    """
    index = build_report_index(db, user)
    rows = index.get("businesses") or []
    if not rows:
        return None

    greeting = (user.display_name or user.email.split("@", 1)[0] or "there").strip()
    return {
        "greeting_name": greeting,
        "businesses": [
            {
                "name": r["business"]["name"],
                "lead_headline": r.get("lead_headline"),
                "score": r.get("score"),
            }
            for r in rows
        ],
        "insights_url": f"{dashboard_base_url.rstrip('/')}/weekly-insights",
    }


def dispatch_weekly_digests(
    db: Session | None = None,
    dashboard_base_url: str | None = None,
) -> dict[str, int]:
    """Walk every paid user, build a digest, send.

    Returns a small summary the scheduler can log. Doesn't raise on
    individual send failures — one user's Resend hiccup shouldn't tank
    the rest of the batch.

    ``dashboard_base_url`` defaults to ``settings.frontend_base_url`` (the
    real public site URL in prod, e.g. https://seohealth.in) so the Weekly
    Insights email links resolve correctly. The scheduler calls this with no
    args, so that default is what production actually uses.
    """
    if dashboard_base_url is None:
        dashboard_base_url = settings.frontend_base_url
    owns_session = db is None
    if db is None:
        db = SessionLocal()
    sent = 0
    skipped_no_data = 0
    failed = 0
    try:
        paid_users = (
            db.query(User)
            .filter(
                # Both Pro and Max get the digest — only Free is excluded. (The
                # old `== paid` here silently dropped Max users.)
                User.plan != UserPlan.free,
                # Honor the per-user opt-out.
                User.weekly_digest_enabled.is_(True),
            )
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
