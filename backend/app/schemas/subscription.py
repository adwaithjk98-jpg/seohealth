from datetime import datetime

from pydantic import BaseModel


class TierLimits(BaseModel):
    """Hard caps applied to a tier. Mirrors AuditAppPlan §8 ("Pricing model").

    Kept in this shape so the frontend can render the limit + remaining count
    without duplicating the rules. Add new caps (competitors, audits/week) here
    as paid-tier features come online.
    """

    businesses: int
    audits_per_week: int
    competitors: int = 0


class SubscriptionInfo(BaseModel):
    """A single subscription row, as the frontend cares about it."""

    id: int
    plan_tier: str
    status: str
    razorpay_subscription_id: str | None = None
    next_billing_date: datetime | None = None
    cancelled_at: datetime | None = None


class SubscriptionState(BaseModel):
    """Aggregate billing state for the signed-in user.

    Used by /api/auth/me, /api/subscriptions/me, and the Billing page so each
    surface speaks the same shape. ``tier`` is the user's effective tier
    (``free`` / ``paid``); ``subscription`` is the most recent paid row when
    present, otherwise null.
    """

    tier: str
    limits: TierLimits
    business_count: int
    can_add_business: bool
    subscription: SubscriptionInfo | None = None


class CheckoutRequest(BaseModel):
    plan_tier: str = "paid"


class CheckoutResponse(BaseModel):
    """Response from POST /api/subscriptions/checkout.

    Two shapes:
      - When Razorpay keys are configured: the frontend opens the Razorpay
        Checkout JS modal with ``razorpay_subscription_id`` + ``key_id``.
        ``mock`` is ``false``.
      - When keys are absent (dev / no-cost prompt-block builds): the backend
        has already activated the subscription server-side. ``mock`` is
        ``true`` and the frontend just reloads its auth state.
    """

    mock: bool
    razorpay_subscription_id: str | None = None
    razorpay_key_id: str | None = None
    plan_tier: str
    short_url: str | None = None
