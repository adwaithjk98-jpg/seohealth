import re

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session as DbSession

from app.auth_deps import current_user
from app.config import settings
from app.db import get_db
from app.models import User
from app.services import auth as auth_service

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

    Always returns 202. We don't reveal whether the email is registered —
    that prevents an attacker from enumerating accounts.
    """
    _, token = auth_service.issue_magic_link(db, payload.email)
    auth_service.deliver_magic_link(payload.email, auth_service.magic_link_url(token))
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
    return MeResponse(id=user.id, email=user.email, plan=user.plan.value)


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


@router.get("/auth/me", response_model=MeResponse)
def me(user: User = Depends(current_user)) -> MeResponse:
    return MeResponse(id=user.id, email=user.email, plan=user.plan.value)
