"""FastAPI dependencies for authenticated routes.

Reads the session cookie, looks up the matching ``Session`` row, and yields
the owning ``User``. Returns 401 when:
  - the cookie is missing or empty
  - the session token is unknown (or has expired and was just cleaned up)
  - the user is missing (cascade should make this unreachable, but the check
    keeps things explicit)
"""

from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.db import get_db
from app.models import User
from app.services import auth as auth_service


def current_user(
    db: DbSession = Depends(get_db),
    session: str | None = Cookie(default=None, alias=settings.session_cookie_name),
) -> User:
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="not authenticated",
        )
    db_session = auth_service.get_session_by_token(db, session)
    if db_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="session expired or invalid",
        )
    user = db.get(User, db_session.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="user no longer exists",
        )
    auth_service.touch_session(db, db_session)
    return user


def is_admin(user: User) -> bool:
    """True iff the user's email is in the configured admin allowlist."""
    admins = {e.strip().lower() for e in settings.admin_emails.split(",") if e.strip()}
    return bool(admins) and user.email.strip().lower() in admins


def admin_user(user: User = Depends(current_user)) -> User:
    """Like current_user, but only for admins. Returns **404** (not 403) to
    non-admins so the admin surface isn't even discoverable."""
    if not is_admin(user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return user
