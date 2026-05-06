"""Magic-link auth + session management.

Flow:
  1. POST /api/auth/request-link with {email}.
     - Find or create the user.
     - Generate a magic-link token (random URL-safe string), store on
       ``users.magic_link_token`` with a short TTL.
     - Hand the link to ``email_service.send_magic_link_email`` for delivery
       (Resend in production, stdout fallback when no API key is configured).
  2. User clicks the link, which points at the FRONTEND
     (``/auth/verify?token=...``). The frontend page POSTs the token to
     /api/auth/verify.
  3. POST /api/auth/verify with {token}.
     - Match token + check expiry.
     - Clear the magic-link fields. Stamp ``last_login``.
     - Insert a row in ``sessions`` with a fresh random session token + expiry.
     - Return the session token; the API layer sets it as an HttpOnly cookie.
  4. Subsequent requests carry the cookie. ``current_user`` looks the session
     up, returns the User, and bumps ``last_used_at``.

Why two tokens (magic-link + session)?
  - The magic-link token is single-use and short-lived (15 min). It only
    proves "the user controls this email address right now."
  - The session token is the long-lived credential that authenticates every
    subsequent request. Separating them lets us expire / revoke each one
    independently and limits the blast radius if a magic link leaks.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.models import Session, User


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _generate_token(nbytes: int = 32) -> str:
    # token_urlsafe is base64url; 32 random bytes -> ~43 character string,
    # well under our String(128) column.
    return secrets.token_urlsafe(nbytes)


# --- Magic link ---------------------------------------------------------------


def issue_magic_link(db: DbSession, email: str) -> tuple[User, str]:
    """Find-or-create the user, issue a fresh magic-link token, return the token."""
    email_norm = email.strip().lower()
    user = db.query(User).filter_by(email=email_norm).one_or_none()
    if user is None:
        user = User(email=email_norm)
        db.add(user)
        db.flush()

    token = _generate_token()
    user.magic_link_token = token
    user.magic_link_expires_at = _now() + timedelta(minutes=settings.magic_link_ttl_minutes)
    db.commit()
    db.refresh(user)
    return user, token


def magic_link_url(token: str) -> str:
    base = settings.frontend_base_url.rstrip("/")
    return f"{base}/auth/verify?token={token}"


# --- Sessions -----------------------------------------------------------------


def consume_magic_link(db: DbSession, token: str) -> User | None:
    """Validate a magic-link token. Returns the User on success, or None."""
    if not token:
        return None
    user = db.query(User).filter_by(magic_link_token=token).one_or_none()
    if user is None:
        return None
    if user.magic_link_expires_at is None or user.magic_link_expires_at < _now():
        # Expired — clear it so the same token can't be reused.
        user.magic_link_token = None
        user.magic_link_expires_at = None
        db.commit()
        return None

    user.magic_link_token = None
    user.magic_link_expires_at = None
    user.last_login = _now()
    db.commit()
    db.refresh(user)
    return user


def create_session(db: DbSession, user: User) -> Session:
    expires_at = _now() + timedelta(days=settings.session_ttl_days)
    session = Session(
        user_id=user.id,
        token=_generate_token(),
        expires_at=expires_at,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session_by_token(db: DbSession, token: str) -> Session | None:
    if not token:
        return None
    session = db.query(Session).filter_by(token=token).one_or_none()
    if session is None:
        return None
    if session.expires_at < _now():
        # Expired — clean it up. Don't leak invalid sessions back.
        db.delete(session)
        db.commit()
        return None
    return session


def touch_session(db: DbSession, session: Session) -> None:
    session.last_used_at = _now()
    db.commit()


def delete_session_by_token(db: DbSession, token: str) -> None:
    if not token:
        return
    session = db.query(Session).filter_by(token=token).one_or_none()
    if session is not None:
        db.delete(session)
        db.commit()


def session_max_age_seconds() -> int:
    return settings.session_ttl_days * 24 * 60 * 60
