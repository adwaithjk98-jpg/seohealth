"""Subscription state machine + Razorpay test-mode integration.

Two execution modes, switched on whether Razorpay credentials are configured:

1. **Live test-mode** (``RAZORPAY_KEY_ID`` + ``RAZORPAY_KEY_SECRET`` set)
   ``create_checkout`` calls Razorpay's subscriptions.create API, returns the
   ``razorpay_subscription_id`` + key_id, and persists a row in
   ``subscriptions`` with ``status=past_due``. The actual activation happens
   when Razorpay POSTs a ``subscription.charged`` event to
   ``/api/subscriptions/webhook``.

2. **Mock mode** (keys missing)
   ``create_checkout`` skips the HTTP call, mints a synthetic
   ``sub_mock_<random>`` identifier, persists the row as ``status=active``,
   and bumps ``users.plan`` to ``paid`` in-band. The frontend just reloads
   auth state. This keeps Phase 3 work runnable with zero external
   dependencies and zero cost — see AuditAppPlan §9 (Phase 3 strategy).

Webhook handling
----------------
Razorpay fires ``subscription.charged`` on first payment and on each renewal,
and ``subscription.cancelled`` when the subscription stops. We treat both as
idempotent: charged → active + bump user.plan; cancelled → cancelled +
fallback user.plan to free (only when no other active subscription remains).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import desc
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.models import Business, Subscription, User
from app.models.enums import SubscriptionStatus, UserPlan

logger = logging.getLogger(__name__)

# Limits per AuditAppPlan §8 ("Pricing model"). Centralised here so /api/auth/me,
# /api/subscriptions/me, and the business-create guard share one source of truth.
TIER_LIMITS: dict[UserPlan, dict[str, int]] = {
    UserPlan.free: {
        "businesses": 1,
        "audits_per_week": 1,
        "competitors": 0,
        # Phase 4 §3: free users cannot run Discovery Scans at all. The
        # gating service raises 402 well before consulting this number,
        # but keep it 0 here so any future "did this user use any quota?"
        # check returns the right answer for both tiers.
        "discovery_scans_per_month": 0,
    },
    UserPlan.paid: {
        "businesses": 3,
        "audits_per_week": 7,
        # Phase 4.6: the cap is now total across *all* of the user's
        # businesses, not per-business. The Hub counter reads this as
        # "X / 4 added" — see api/competitors.add_competitor for the
        # enforcement change.
        "competitors": 4,
        # One bulk Discovery Scan per calendar month per the prompt. Bump
        # here when the higher pricing tier lands.
        "discovery_scans_per_month": 1,
    },
}

PAID_PLAN_TIER = "paid"
_RAZORPAY_API_BASE = "https://api.razorpay.com/v1"
# 12 cycles ≈ 1 year of monthly billing. Razorpay requires a fixed count.
_DEFAULT_TOTAL_COUNT = 12


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --- Configuration helpers ----------------------------------------------------


def is_razorpay_configured() -> bool:
    """True iff we have enough credentials to call Razorpay's API."""
    return bool(settings.razorpay_key_id and settings.razorpay_key_secret)


def limits_for_tier(tier: UserPlan) -> dict[str, int]:
    return TIER_LIMITS[tier]


# --- Read helpers -------------------------------------------------------------


def latest_subscription(db: DbSession, user_id: int) -> Subscription | None:
    return (
        db.query(Subscription)
        .filter(Subscription.user_id == user_id)
        .order_by(desc(Subscription.id))
        .first()
    )


def active_subscription(db: DbSession, user_id: int) -> Subscription | None:
    return (
        db.query(Subscription)
        .filter(
            Subscription.user_id == user_id,
            Subscription.status == SubscriptionStatus.active,
        )
        .order_by(desc(Subscription.id))
        .first()
    )


def count_active_businesses(db: DbSession, user_id: int) -> int:
    return (
        db.query(Business)
        .filter(Business.user_id == user_id, Business.archived_at.is_(None))
        .count()
    )


def user_business_limit(user: User) -> int:
    return TIER_LIMITS[user.plan]["businesses"]


def can_user_add_business(db: DbSession, user: User) -> bool:
    return count_active_businesses(db, user.id) < user_business_limit(user)


def user_competitor_limit(user: User) -> int:
    return TIER_LIMITS[user.plan]["competitors"]


def user_discovery_scan_monthly_limit(user: User) -> int:
    """Number of Discovery Scans this user's tier allows per calendar month.

    Centralised so the gate, the /api/auth/me payload, and any future
    "you've used X of Y" UI hint share one source of truth.
    """
    return TIER_LIMITS[user.plan]["discovery_scans_per_month"]


# --- Razorpay HTTP client (test mode) -----------------------------------------


def _razorpay_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    auth = (settings.razorpay_key_id, settings.razorpay_key_secret)
    with httpx.Client(timeout=15.0) as client:
        res = client.post(f"{_RAZORPAY_API_BASE}{path}", json=body, auth=auth)
    if res.status_code >= 400:
        logger.warning(
            "Razorpay API %s returned %s: %s", path, res.status_code, res.text
        )
        res.raise_for_status()
    return res.json()


def _create_razorpay_subscription(plan_id: str) -> dict[str, Any]:
    """Call Razorpay subscriptions.create. Returns the raw response.

    Razorpay returns at minimum ``id`` (the ``sub_xxx`` identifier) and
    ``short_url`` (a hosted-checkout link, useful for the no-JS fallback).
    """
    return _razorpay_post(
        "/subscriptions",
        {
            "plan_id": plan_id,
            "total_count": _DEFAULT_TOTAL_COUNT,
            "customer_notify": 1,
        },
    )


# --- State transitions --------------------------------------------------------


def _ensure_user_plan(db: DbSession, user: User, plan: UserPlan) -> None:
    if user.plan != plan:
        user.plan = plan


def _activate_subscription(
    db: DbSession,
    user: User,
    razorpay_subscription_id: str | None,
    plan_tier: str = PAID_PLAN_TIER,
) -> Subscription:
    """Insert-or-update the subscription row + bump the user to paid.

    Looking up by ``razorpay_subscription_id`` keeps the webhook idempotent:
    Razorpay can deliver the same event twice and we won't double-insert.
    """
    row: Subscription | None = None
    if razorpay_subscription_id:
        row = (
            db.query(Subscription)
            .filter(
                Subscription.razorpay_subscription_id == razorpay_subscription_id
            )
            .one_or_none()
        )
    if row is None:
        row = Subscription(
            user_id=user.id,
            razorpay_subscription_id=razorpay_subscription_id,
            plan_tier=plan_tier,
            status=SubscriptionStatus.active,
        )
        db.add(row)
    else:
        row.status = SubscriptionStatus.active
        row.plan_tier = plan_tier
        row.cancelled_at = None
    _ensure_user_plan(db, user, UserPlan.paid)
    db.commit()
    db.refresh(row)
    db.refresh(user)
    return row


def _cancel_subscription(
    db: DbSession,
    razorpay_subscription_id: str,
) -> Subscription | None:
    row = (
        db.query(Subscription)
        .filter(Subscription.razorpay_subscription_id == razorpay_subscription_id)
        .one_or_none()
    )
    if row is None:
        logger.info(
            "subscription.cancelled webhook for unknown id=%s — ignoring",
            razorpay_subscription_id,
        )
        return None
    row.status = SubscriptionStatus.cancelled
    row.cancelled_at = _now()

    # If the user has no other active subscriptions, fall back to free.
    user = db.get(User, row.user_id)
    if user is not None:
        still_active = (
            db.query(Subscription)
            .filter(
                Subscription.user_id == user.id,
                Subscription.status == SubscriptionStatus.active,
                Subscription.id != row.id,
            )
            .first()
        )
        if still_active is None:
            _ensure_user_plan(db, user, UserPlan.free)

    db.commit()
    db.refresh(row)
    return row


def _mark_past_due(
    db: DbSession,
    user: User,
    razorpay_subscription_id: str,
    plan_tier: str = PAID_PLAN_TIER,
) -> Subscription:
    """Persist a pending row when Razorpay is configured.

    The row is upgraded to ``active`` once ``subscription.charged`` arrives via
    webhook. Persisting it here means /api/subscriptions/me can show "checkout
    started, awaiting payment" without depending on the webhook firing first.
    """
    row = Subscription(
        user_id=user.id,
        razorpay_subscription_id=razorpay_subscription_id,
        plan_tier=plan_tier,
        status=SubscriptionStatus.past_due,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# --- Public service API -------------------------------------------------------


def create_checkout(db: DbSession, user: User) -> dict[str, Any]:
    """Start an upgrade. Returns the payload the frontend needs to proceed.

    Two paths (see module docstring): real Razorpay vs mock. Both are safe to
    call repeatedly; an already-active user just gets their existing
    subscription back as a no-op.
    """
    existing = active_subscription(db, user.id)
    if existing is not None:
        return {
            "mock": not is_razorpay_configured(),
            "razorpay_subscription_id": existing.razorpay_subscription_id,
            "razorpay_key_id": settings.razorpay_key_id or None,
            "plan_tier": existing.plan_tier,
            "short_url": None,
            "already_active": True,
        }

    if not is_razorpay_configured():
        mock_id = f"sub_mock_{secrets.token_hex(8)}"
        _activate_subscription(db, user, mock_id, PAID_PLAN_TIER)
        return {
            "mock": True,
            "razorpay_subscription_id": mock_id,
            "razorpay_key_id": None,
            "plan_tier": PAID_PLAN_TIER,
            "short_url": None,
        }

    if not settings.razorpay_paid_plan_id:
        raise RuntimeError(
            "RAZORPAY_PAID_PLAN_ID must be set when Razorpay credentials are "
            "configured. Create a plan in the Razorpay dashboard (Test Mode) "
            "and paste its id (e.g. plan_xxxxxxxx) into the env var."
        )

    rzp = _create_razorpay_subscription(settings.razorpay_paid_plan_id)
    razorpay_subscription_id = rzp["id"]
    _mark_past_due(db, user, razorpay_subscription_id, PAID_PLAN_TIER)
    return {
        "mock": False,
        "razorpay_subscription_id": razorpay_subscription_id,
        "razorpay_key_id": settings.razorpay_key_id,
        "plan_tier": PAID_PLAN_TIER,
        "short_url": rzp.get("short_url"),
    }


def verify_webhook_signature(body_bytes: bytes, signature: str | None) -> bool:
    """Verify Razorpay's HMAC-SHA256 webhook signature.

    Returns True when no secret is configured (dev convenience). In production,
    set ``RAZORPAY_WEBHOOK_SECRET`` so unsigned requests are rejected.
    """
    if not settings.razorpay_webhook_secret:
        return True
    if not signature:
        return False
    expected = hmac.new(
        settings.razorpay_webhook_secret.encode("utf-8"),
        msg=body_bytes,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def handle_webhook_event(
    db: DbSession,
    event: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch a Razorpay webhook payload.

    Supported events:
      - ``subscription.charged`` / ``subscription.activated`` → activate row
      - ``subscription.cancelled`` / ``subscription.completed`` / ``halted`` → cancel row

    Unknown events are logged and ignored (Razorpay sends a lot of chatter
    we don't subscribe to). The function never raises on an unrecognised
    shape; it just returns ``{handled: False, reason: ...}``.
    """
    event_type = event.get("event")
    payload = event.get("payload", {})
    sub_entity = (payload.get("subscription") or {}).get("entity") or {}
    razorpay_subscription_id = sub_entity.get("id")

    if not event_type:
        return {"handled": False, "reason": "missing event type"}
    if not razorpay_subscription_id:
        return {"handled": False, "reason": "missing subscription id"}

    if event_type in {"subscription.charged", "subscription.activated"}:
        row = (
            db.query(Subscription)
            .filter(
                Subscription.razorpay_subscription_id == razorpay_subscription_id
            )
            .one_or_none()
        )
        if row is None:
            return {
                "handled": False,
                "reason": "unknown razorpay_subscription_id",
            }
        user = db.get(User, row.user_id)
        if user is None:
            return {"handled": False, "reason": "user missing"}
        _activate_subscription(db, user, razorpay_subscription_id, row.plan_tier)
        return {"handled": True, "event": event_type, "status": "active"}

    if event_type in {
        "subscription.cancelled",
        "subscription.completed",
        "subscription.halted",
    }:
        _cancel_subscription(db, razorpay_subscription_id)
        return {"handled": True, "event": event_type, "status": "cancelled"}

    return {"handled": False, "reason": f"event {event_type} ignored"}
