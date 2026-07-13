"""Subscription routes.

Three surfaces:
  - ``POST /api/subscriptions/checkout`` (authed): start an upgrade. Returns a
    payload that drives either the Razorpay Checkout modal (when keys are
    configured) or an in-app mock-success flow (when they aren't).
  - ``POST /api/subscriptions/webhook`` (unauthed): Razorpay webhook receiver.
    Razorpay can't carry session cookies, so authentication is via the optional
    HMAC signature header verified in the service layer.
  - ``GET /api/subscriptions/me`` (authed): current tier + limits + the most
    recent subscription row. Same shape the Billing page renders against.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth_deps import current_user
from app.db import get_db
from app.models import User
from app.schemas.subscription import (
    CheckoutRequest,
    CheckoutResponse,
    SubscriptionInfo,
    SubscriptionState,
    TierLimits,
)
from app.services import subscriptions as subs_service

logger = logging.getLogger(__name__)

router = APIRouter()


def _build_state(db: Session, user: User) -> SubscriptionState:
    limits = subs_service.limits_for_tier(user.plan)
    business_count = subs_service.count_active_businesses(db, user.id)
    latest = subs_service.latest_subscription(db, user.id)
    sub_info: SubscriptionInfo | None = None
    if latest is not None:
        sub_info = SubscriptionInfo(
            id=latest.id,
            plan_tier=latest.plan_tier,
            status=latest.status.value,
            razorpay_subscription_id=latest.razorpay_subscription_id,
            next_billing_date=latest.next_billing_date,
            cancelled_at=latest.cancelled_at,
        )
    return SubscriptionState(
        tier=user.plan.value,
        limits=TierLimits(**limits),
        business_count=business_count,
        can_add_business=business_count < limits["businesses"],
        subscription=sub_info,
    )


@router.get("/subscriptions/me", response_model=SubscriptionState)
def my_subscription(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> SubscriptionState:
    return _build_state(db, user)


@router.post(
    "/subscriptions/checkout",
    response_model=CheckoutResponse,
    status_code=status.HTTP_201_CREATED,
)
def start_checkout(
    payload: CheckoutRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> CheckoutResponse:
    if payload.plan_tier not in subs_service.PLAN_TIER_TO_USER_PLAN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown plan tier: {payload.plan_tier!r}",
        )
    try:
        result = subs_service.create_checkout(db, user, payload.plan_tier)
    except subs_service.LiveTierChangeUnsupported as exc:
        # W5 — live plan switches aren't supported yet; refuse cleanly rather
        # than double-billing. 409 so the frontend can show "contact support".
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except RuntimeError as exc:
        # Configuration error (e.g. plan id missing) — surface a clean 500
        # so the operator can fix it rather than silently mocking.
        logger.exception("checkout failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )
    return CheckoutResponse(
        mock=result["mock"],
        razorpay_subscription_id=result.get("razorpay_subscription_id"),
        razorpay_key_id=result.get("razorpay_key_id"),
        plan_tier=result["plan_tier"],
        short_url=result.get("short_url"),
    )


@router.post("/subscriptions/cancel", response_model=SubscriptionState)
def cancel_subscription(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> SubscriptionState:
    """Cancel the user's active subscription and drop them to Free.

    Idempotent: cancelling with nothing active just returns current state.
    Downgrades (Max → Pro) are a separate flow — POST /subscriptions/checkout
    with ``plan_tier='paid'``.
    """
    subs_service.cancel_active_subscription(db, user)
    db.refresh(user)
    return _build_state(db, user)


@router.post("/subscriptions/webhook")
async def razorpay_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_razorpay_signature: str | None = Header(default=None),
) -> dict[str, object]:
    """Receive subscription events from Razorpay.

    Auth note: this endpoint is intentionally unauthenticated — webhooks come
    from Razorpay's servers, not from a user session. Integrity is enforced by
    ``verify_webhook_signature`` (HMAC-SHA256 over the raw body) when a secret
    is configured. In dev with no secret set, the endpoint accepts unsigned
    requests so a local curl can simulate events.
    """
    raw = await request.body()
    if not subs_service.verify_webhook_signature(raw, x_razorpay_signature):
        raise HTTPException(status_code=400, detail="invalid signature")

    try:
        event = json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON body")

    result = subs_service.handle_webhook_event(db, event)
    logger.info("razorpay webhook %s -> %s", event.get("event"), result)
    # Always 200; Razorpay treats anything else as a delivery failure and
    # retries. Even "ignored" events should ack so we don't get spammed.
    return result
