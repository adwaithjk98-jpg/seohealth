"""Founder-only stats panel.

`GET /api/admin/stats` — the numbers no external dashboard has (users, the
free/Pro/Max split, conversion, DB-derived MRR, signups, audit queue depth, and
server headroom), each mapped to a scaling trigger. Gated by `admin_user`,
which 404s anyone not in `settings.admin_emails`, so the surface isn't even
discoverable. Money truth still lives in the Razorpay dashboard; this is the
at-a-glance founder view.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth_deps import admin_user
from app.db import get_db
from app.models import Audit, Subscription, User
from app.models.enums import SubscriptionStatus, UserPlan

router = APIRouter()

# Monthly price per paid tier (INR). Mirrors the Razorpay plans; used only to
# estimate MRR from current plan counts. Source of truth for billing is
# Razorpay; this is the at-a-glance number.
_TIER_MONTHLY_INR = {UserPlan.paid: 549, UserPlan.max: 2500}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _mem_free_pct() -> int | None:
    """Free RAM % from /proc/meminfo (Linux/prod). None on macOS dev (no /proc)."""
    try:
        info: dict[str, int] = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, rest = line.partition(":")
                if rest:
                    info[k.strip()] = int(rest.strip().split()[0])  # value in kB
        total, avail = info.get("MemTotal"), info.get("MemAvailable")
        if total and avail:
            return round(avail / total * 100)
    except (OSError, ValueError):
        pass
    return None


def _server_health() -> dict:
    try:
        load_1m = round(os.getloadavg()[0], 2)
    except (OSError, AttributeError):
        load_1m = None
    try:
        du = shutil.disk_usage("/")
        disk_free_pct = round(du.free / du.total * 100)
    except OSError:
        disk_free_pct = None
    return {
        "load_avg_1m": load_1m,
        "disk_free_pct": disk_free_pct,
        "ram_free_pct": _mem_free_pct(),
    }


def _queue_depths() -> dict:
    # Imported lazily so a Redis hiccup degrades this one field instead of
    # 500-ing the whole panel.
    try:
        from app.workers.queue import audit_queue, competitor_queue

        return {"audits": audit_queue.count, "competitors": competitor_queue.count}
    except Exception:
        return {"audits": None, "competitors": None}


@router.get("/admin/stats")
def admin_stats(
    db: Session = Depends(get_db),
    _admin: User = Depends(admin_user),
) -> dict:
    now = _now()

    plan_counts = dict(db.query(User.plan, func.count(User.id)).group_by(User.plan).all())
    free = plan_counts.get(UserPlan.free, 0)
    pro = plan_counts.get(UserPlan.paid, 0)
    mx = plan_counts.get(UserPlan.max, 0)
    total = free + pro + mx
    paid = pro + mx

    def _since(days: int) -> int:
        return (
            db.query(func.count(User.id))
            .filter(User.signup_date >= now - timedelta(days=days))
            .scalar()
            or 0
        )

    audits_7d = (
        db.query(func.count(Audit.id))
        .filter(Audit.started_at >= now - timedelta(days=7))
        .scalar()
        or 0
    )
    active_subs = (
        db.query(func.count(Subscription.id))
        .filter(Subscription.status == SubscriptionStatus.active)
        .scalar()
        or 0
    )

    return {
        "as_of": now.isoformat(),
        "users": {
            "total": total,
            "free": free,
            "pro": pro,
            "max": mx,
            "paid": paid,
            "conversion_pct": round(paid / total * 100, 1) if total else 0.0,
        },
        "revenue": {
            "mrr_inr": pro * _TIER_MONTHLY_INR[UserPlan.paid]
            + mx * _TIER_MONTHLY_INR[UserPlan.max],
            "active_subscriptions": active_subs,
        },
        "growth": {
            "signups_7d": _since(7),
            "signups_30d": _since(30),
            "audits_7d": audits_7d,
        },
        # "is the single worker keeping up?" — the 2nd-worker trigger.
        "queue_depth": _queue_depths(),
        # The real server-upgrade signal (watch RAM/load, not user count).
        "server": _server_health(),
    }
