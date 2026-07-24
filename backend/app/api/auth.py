import re
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session as DbSession

from app.schemas.subscription import (
    SubscriptionInfo,
    SubscriptionState,
    TierLimits,
)

from app.auth_deps import current_user, is_admin
from app.config import settings
from app.db import get_db
from app.models import User
from app.models.discovery_scan import DiscoveryScan
from app.ratelimit import limiter
from app.services import auth as auth_service
from app.services import email_service
from app.services import subscriptions as subs_service

router = APIRouter()

# Permissive email check — we're not validating deliverability, just shape.
# Real validation happens implicitly when the magic link gets clicked.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Characters we tolerate in a typed phone number before counting digits.
_PHONE_ALLOWED_RE = re.compile(r"^[0-9+\-()\s]+$")


def _normalize_phone(v: str | None) -> str | None:
    """Light, shape-only phone cleanup — mirrors the permissive email check.

    Empty/whitespace → ``None`` (the field is optional). Otherwise collapse
    internal whitespace and keep the number roughly as typed; we don't force
    E.164 here (that's the WhatsApp send build's job, once we know the country).
    A number with fewer than 7 or more than 15 digits, or stray characters, is
    rejected so obvious junk doesn't get stored.
    """
    if v is None:
        return None
    cleaned = " ".join(v.split())
    if not cleaned:
        return None
    if not _PHONE_ALLOWED_RE.match(cleaned):
        raise ValueError("not a valid phone number")
    digits = sum(c.isdigit() for c in cleaned)
    if digits < 7 or digits > 15:
        raise ValueError("not a valid phone number")
    return cleaned


class RequestLinkBody(BaseModel):
    email: str
    # Optional signup number — the S1 (WhatsApp recap) foundation. Blank on a
    # returning login is fine; it's only *collected* here, never required.
    phone: str | None = None

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("not a valid email address")
        return v

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, v: str | None) -> str | None:
        return _normalize_phone(v)


class VerifyTokenBody(BaseModel):
    token: str


class MeResponse(BaseModel):
    id: int
    email: str
    plan: str
    # Friendly greeting label. NULL until the user fills the FTUE
    # questionnaire; the frontend falls back to the email-prefix.
    display_name: str | None = None
    # Optional contact number (S1 WhatsApp-recap foundation). NULL until given.
    phone: str | None = None
    # Whether the weekly digest email is on for this user (account-page toggle).
    weekly_digest_enabled: bool = True
    # Founder/admin flag — lets the SPA show the admin stats link only to admins.
    # The /api/admin/* endpoints enforce this server-side too.
    is_admin: bool = False
    # Phase 3 — subscription tier + hard caps + most-recent subscription row,
    # so the SPA can render Billing state and gate "Add business" without a
    # second round-trip.
    subscription_state: SubscriptionState | None = None


class UpdateMeBody(BaseModel):
    """PATCH /auth/me payload. Only fields the user can self-update —
    no plan, no email, no admin knobs."""

    display_name: str | None = Field(default=None, max_length=120)
    # Passing "" clears the saved number (→ NULL). Same shape check as signup.
    phone: str | None = Field(default=None, max_length=32)
    weekly_digest_enabled: bool | None = Field(default=None)

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, v: str | None) -> str | None:
        # Preserve "" as an explicit clear signal; normalise anything else.
        if v is not None and v.strip() == "":
            return ""
        return _normalize_phone(v)


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
        display_name=user.display_name,
        phone=user.phone,
        weekly_digest_enabled=user.weekly_digest_enabled,
        is_admin=is_admin(user),
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
@limiter.limit(settings.rate_limit_request_link)
def request_magic_link(
    request: Request,
    payload: RequestLinkBody,
    db: DbSession = Depends(get_db),
) -> dict[str, str]:
    """Issue a magic-link email (or, in dev, print it to the console).

    On success returns 202. We don't reveal whether the email is registered —
    that prevents an attacker from enumerating accounts. If the email
    provider rejects the send, surface a 500 so the user knows to retry
    rather than silently dropping their sign-in attempt.
    """
    _, token = auth_service.issue_magic_link(db, payload.email, payload.phone)
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


@router.patch("/auth/me", response_model=MeResponse)
def update_me(
    payload: UpdateMeBody,
    db: DbSession = Depends(get_db),
    user: User = Depends(current_user),
) -> MeResponse:
    """Self-update for user-editable fields. Today: ``display_name`` only.

    Empty string is treated as "clear the name" → stored as NULL so the
    frontend falls back to the email-prefix again.
    """
    if payload.display_name is not None:
        cleaned = payload.display_name.strip()
        user.display_name = cleaned or None
    if payload.phone is not None:
        # Already normalised by the validator; "" means "clear it" → NULL.
        user.phone = payload.phone or None
    if payload.weekly_digest_enabled is not None:
        user.weekly_digest_enabled = payload.weekly_digest_enabled
    db.commit()
    db.refresh(user)
    return _build_me_response(db, user)


def _to_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


@router.get("/auth/me/export")
def export_my_data(
    db: DbSession = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    """Self-service data export — everything we hold for this user, as JSON.

    Satisfies the "user can get their data" requirement (DPDP / Play Store).
    Walks the ORM relationships, so it stays correct as the schema grows.
    """
    businesses = []
    for biz in user.businesses:
        businesses.append(
            {
                "id": biz.id,
                "name": biz.name,
                "city": biz.city,
                "maps_url": biz.maps_url,
                "website": biz.website,
                "ig_handle": biz.ig_handle,
                "business_type": biz.business_type,
                "added_at": _to_iso(biz.added_at),
                "archived_at": _to_iso(biz.archived_at),
                "audits": [
                    {
                        "id": a.id,
                        "status": a.status.value,
                        "trigger": a.trigger.value,
                        "started_at": _to_iso(a.started_at),
                        "finished_at": _to_iso(a.finished_at),
                        "sections": [
                            {
                                "section": s.section.value,
                                "score": s.score,
                                "status": s.status.value,
                            }
                            for s in a.sections
                        ],
                        "recommendations": [
                            {
                                "section": r.section.value,
                                "title": r.title,
                                "severity": r.severity.value,
                                "fix_status": r.fix_status.value,
                            }
                            for r in a.recommendations
                        ],
                    }
                    for a in biz.audits
                ],
                "competitors": [
                    {
                        "name": c.name,
                        "maps_url": c.maps_url,
                        "website_url": c.website_url,
                        "instagram_url": c.instagram_url,
                    }
                    for c in biz.competitors
                ],
            }
        )
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "profile": {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "phone": user.phone,
            "plan": user.plan.value,
            "signup_date": _to_iso(user.signup_date),
            "weekly_digest_enabled": user.weekly_digest_enabled,
        },
        "businesses": businesses,
        "subscriptions": [
            {
                "plan_tier": s.plan_tier,
                "status": s.status.value,
                "next_billing_date": _to_iso(s.next_billing_date),
                "cancelled_at": _to_iso(s.cancelled_at),
            }
            for s in user.subscriptions
        ],
    }


@router.delete("/auth/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_account(
    response: Response,
    db: DbSession = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    """Hard-delete the account and everything attached to it.

    Businesses → audits → sections/recs/observations and competitors all
    cascade via ORM relationships. Discovery scans have no cascade
    relationship, so we clear them explicitly first. Then the session cookie
    is cleared so the SPA drops to signed-out state.
    """
    db.query(DiscoveryScan).filter(DiscoveryScan.user_id == user.id).delete(
        synchronize_session=False
    )
    db.delete(user)
    db.commit()
    _clear_session_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


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
