"""Discovery Scan gate, request creation, and quota accounting (Phase 4 §3).

Two responsibilities:

1. **Gating** — ``assert_can_run`` raises a structured ``HTTPException`` if
   the caller's tier doesn't unlock Discovery Scans, or if they've already
   used their monthly quota. Designed to be called from the API layer (it
   knows about ``HTTPException``) so a single dependency-style call is all
   the route needs.

2. **Persistence** — ``create_scan`` writes a ``DiscoveryScan`` row in
   ``pending`` status, returns the new row, and the caller enqueues the
   matching RQ job. Recording the row *before* enqueueing means a worker
   crash on the way to ``running`` still leaves a row the rate limiter can
   count — paid users can't double-tap "Scan" to bypass the cap.

Mocked subscription
-------------------
The gate uses ``user.plan`` (a real DB column already populated by the
existing Razorpay/mock checkout flow). If the subscription system isn't
configured (``RAZORPAY_KEY_ID`` empty), the mock checkout still flips
``user.plan`` to ``paid``, so this gate behaves correctly in both modes.
"""

from __future__ import annotations

import logging
from calendar import monthrange
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session as DbSession

from app.models import DiscoveryScan, User
from app.models.enums import DiscoveryScanStatus, UserPlan
from app.services import subscriptions as subs_service

logger = logging.getLogger(__name__)


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _current_month_window(now: datetime) -> tuple[datetime, datetime]:
    """Return [start, end) of the calendar month containing ``now``.

    Calendar month (not "last 30 days") because the rate-limit semantics
    the user sees in the UI are easier to reason about: "you used your
    monthly Discovery Scan on the 4th; the next one unlocks on the 1st".
    A rolling-30-day window would surprise users with off-by-one denials.
    """
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    _, last_day = monthrange(now.year, now.month)
    if now.month == 12:
        end = start.replace(year=now.year + 1, month=1)
    else:
        end = start.replace(month=now.month + 1)
    # ``last_day`` is unused here — kept the import to make the math
    # obvious; the end is just the first of next month.
    _ = last_day
    return start, end


def count_scans_this_month(db: DbSession, user: User) -> int:
    """How many Discovery Scans this user has requested in the current month.

    Counts all rows regardless of status — see module docstring on why
    failed attempts still consume quota.
    """
    start, end = _current_month_window(_now_naive())
    return (
        db.query(DiscoveryScan)
        .filter(
            DiscoveryScan.user_id == user.id,
            DiscoveryScan.requested_at >= start,
            DiscoveryScan.requested_at < end,
        )
        .count()
    )


def assert_can_run(db: DbSession, user: User) -> None:
    """Raise ``HTTPException`` if this user cannot start a Discovery Scan now.

    Two failure modes, mapped to distinct HTTP codes so the frontend can
    show different copy:

    * ``402 Payment Required`` — free tier. Body advertises the upgrade.
    * ``429 Too Many Requests`` — paid tier, monthly quota exhausted.
      Body includes ``next_reset_at`` (first day of next month) so the UI
      can show "next scan unlocks on …".
    """
    if user.plan != UserPlan.paid:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "discovery_scan_paid_only",
                "message": (
                    "Discovery Scan is a paid-tier feature. Upgrade to "
                    "run bulk competitor searches."
                ),
                "tier": user.plan.value,
            },
        )

    limit = subs_service.user_discovery_scan_monthly_limit(user)
    used = count_scans_this_month(db, user)
    if used >= limit:
        _, end = _current_month_window(_now_naive())
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "discovery_scan_monthly_limit",
                "message": (
                    f"You've used your {limit} Discovery Scan(s) for this month. "
                    "The quota resets on the 1st."
                ),
                "tier": user.plan.value,
                "limit": limit,
                "used": used,
                "next_reset_at": end.isoformat(),
            },
        )


def create_scan(
    db: DbSession,
    user: User,
    *,
    query: str,
    num_leads: int,
    fields: list[str],
    filters: str | None = None,
    business_id: int | None = None,
) -> DiscoveryScan:
    """Persist a ``pending`` Discovery Scan row.

    The caller is responsible for enqueueing the matching RQ job (the gate
    + persistence is the same regardless of which queue the work lands on;
    keeping that decision out of this service avoids a circular import on
    the workers package).
    """
    scan = DiscoveryScan(
        user_id=user.id,
        business_id=business_id,
        query=query.strip(),
        num_leads=num_leads,
        fields_csv=",".join(fields),
        filters=filters,
        status=DiscoveryScanStatus.pending,
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return scan


def scan_to_dict(scan: DiscoveryScan) -> dict[str, Any]:
    """Serialize a scan row for the API response.

    Centralized so the POST (returns the freshly-created row) and the GET
    (returns the row plus its results) share one shape. The frontend can
    render either by checking ``status``.
    """
    return {
        "id": scan.id,
        "user_id": scan.user_id,
        "business_id": scan.business_id,
        "query": scan.query,
        "num_leads": scan.num_leads,
        "fields": scan.fields_csv.split(",") if scan.fields_csv else [],
        "filters": scan.filters,
        "status": scan.status.value,
        "requested_at": scan.requested_at,
        "started_at": scan.started_at,
        "finished_at": scan.finished_at,
        "result_count": scan.result_count,
        "results": scan.results_json,
        "error_message": scan.error_message,
    }
