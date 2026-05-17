import re

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session as DbSession

from app.schemas.subscription import (
    SubscriptionInfo,
    SubscriptionState,
    TierLimits,
)

from app.auth_deps import current_user
from app.config import settings
from app.db import get_db
from app.models import User
from app.services import auth as auth_service
from app.services import email_service
from app.services import subscriptions as subs_service

router = APIRouter()

# Permissive email check — we're not validating deliverability, just shape.
# Real validation happens implicitly when the magic link gets clicked.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RequestLinkBody(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("not a valid email address")
        return v


class VerifyTokenBody(BaseModel):
    token: str


class MeResponse(BaseModel):
    id: int
    email: str
    plan: str
    # Phase 3 — subscription tier + hard caps + most-recent subscription row,
    # so the SPA can render Billing state and gate "Add business" without a
    # second round-trip.
    subscription_state: SubscriptionState | None = None


def _build_me_response(db: DbSession, user: User) -> "MeResponse":
    limits = subs_service.limits_for_tier(user.plan)
    business_count = subs_service.count_active_businesses(db, user.id)
    latest = subs_service.latest_subscription(db, user.id)
    sub_info = None
    if latest is not None:
        sub_info = SubscriptionInfo(
            id=latest.id,
            plan_tier=latest.plan_tier,
            status=latest.status.value,
            razorpay_subscription_id=latest.razorpay_subscription_id,
            next_billing_date=latest.next_billing_date,
            cancelled_at=latest.cancelled_at,
        )
    state = SubscriptionState(
        tier=user.plan.value,
        limits=TierLimits(**limits),
        business_count=business_count,
        can_add_business=business_count < limits["businesses"],
        subscription=sub_info,
    )
    return MeResponse(
        id=user.id,
        email=user.email,
        plan=user.plan.value,
        subscription_state=state,
    )


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=auth_service.session_max_age_seconds(),
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        samesite="lax",
        secure=settings.session_cookie_secure,
        httponly=True,
    )


@router.post("/auth/request-link", status_code=status.HTTP_202_ACCEPTED)
def request_magic_link(
    payload: RequestLinkBody,
    db: DbSession = Depends(get_db),
) -> dict[str, str]:
    """Issue a magic-link email (or, in dev, print it to the console).

    On success returns 202. We don't reveal whether the email is registered —
    that prevents an attacker from enumerating accounts. If the email
    provider rejects the send, surface a 500 so the user knows to retry
    rather than silently dropping their sign-in attempt.
    """
    _, token = auth_service.issue_magic_link(db, payload.email)
    try:
        email_service.send_magic_link_email(
            payload.email, auth_service.magic_link_url(token)
        )
    except email_service.EmailDeliveryError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="We couldn't send your sign-in email. Please try again in a moment.",
        )
    return {"message": "If that email is valid, a sign-in link is on its way."}


@router.post("/auth/verify", response_model=MeResponse)
def verify_magic_link(
    payload: VerifyTokenBody,
    response: Response,
    db: DbSession = Depends(get_db),
) -> MeResponse:
    user = auth_service.consume_magic_link(db, payload.token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This sign-in link is invalid or has expired.",
        )
    session = auth_service.create_session(db, user)
    _set_session_cookie(response, session.token)
    return _build_me_response(db, user)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    db: DbSession = Depends(get_db),
    session: str | None = Cookie(default=None, alias=settings.session_cookie_name),
) -> Response:
    if session:
        auth_service.delete_session_by_token(db, session)
    _clear_session_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


class SessionResponse(BaseModel):
    """Always 200 — ``user`` is null when not signed in.

    Lets the SPA's "am I logged in?" probe run without browsers logging a
    red 401 to the console on every page load. The signed-in check itself
    is enforced by ``current_user`` on protected endpoints, not by 401-ing
    this one.
    """

    user: MeResponse | None = None


@router.get("/auth/me", response_model=MeResponse)
def me(
    db: DbSession = Depends(get_db),
    user: User = Depends(current_user),
) -> MeResponse:
    return _build_me_response(db, user)


@router.get("/auth/session", response_model=SessionResponse)
def session_probe(
    db: DbSession = Depends(get_db),
    session: str | None = Cookie(default=None, alias=settings.session_cookie_name),
) -> SessionResponse:
    if not session:
        return SessionResponse(user=None)
    db_session = auth_service.get_session_by_token(db, session)
    if db_session is None:
        return SessionResponse(user=None)
    user = db.get(User, db_session.user_id)
    if user is None:
        return SessionResponse(user=None)
    return SessionResponse(user=_build_me_response(db, user))
