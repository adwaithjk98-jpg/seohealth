"""One round trip for the app's cold open.

Opening the app used to cost three *serial* API calls before anything could
paint: ``/api/businesses`` (the dashboard layout loader), then
``/api/businesses/{id}/latest-audit`` (gated behind ``await parent()`` in the
page loader), then ``/api/auth/session`` from the root layout's ``onMount``.
On a 1-vCPU box each one is a fresh connection, a session lookup and a query
round trip, and the user stares at an empty shell for the sum of all three.

``GET /api/home`` returns the same three payloads in one response, composed
from the exact builders the individual endpoints use (``build_me_response``,
``build_business_list``, ``build_audit_detail``) so the consolidated shape can
never drift from them.

Two deliberate choices:

- **It never 401s.** Like ``/auth/session``, an absent or dead session returns
  200 with ``user: null`` so the SPA's own gate can redirect without the
  browser logging a red 401 on every cold open. Ownership checks still live on
  the individual endpoints; nothing here is reachable without a valid session.
- **It does not touch the session.** Session expiry is absolute
  (``Session.expires_at``), not sliding — ``last_used_at`` is informational —
  so refreshing it here would buy nothing and cost a write + commit on the
  single hottest endpoint in the app. ``/auth/session``, the probe this
  replaces, already behaved this way.
"""

from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from app.api.audits import latest_completed_audit
from app.api.auth import MeResponse, build_me_response
from app.api.businesses import build_business_list
from app.config import settings
from app.db import get_db
from app.models import Business, User
from app.schemas.audit import AuditDetailResponse
from app.schemas.business import BusinessResponse
from app.services import auth as auth_service
from app.services.audit_view import build_audit_detail

router = APIRouter()


class HomeResponse(BaseModel):
    """Everything the home screen needs to paint, in one payload.

    ``user`` is null when signed out, in which case ``businesses`` is null too
    (not ``[]`` — the frontend distinguishes "not signed in" from "signed in
    with no businesses yet", which are very different screens).
    """

    user: MeResponse | None = None
    businesses: list[BusinessResponse] | None = None
    # The hero audit is only sent for single-business accounts, matching what
    # the home screen actually renders: one business gets the status-first
    # score ring, multi-business (Max) accounts get the card grid and would
    # only pay for a payload they never show.
    hero_audit: AuditDetailResponse | None = None


def _resolve_user(db: DbSession, token: str | None) -> User | None:
    """Session cookie → User, or None. Never raises — see the module docstring."""
    if not token:
        return None
    db_session = auth_service.get_session_by_token(db, token)
    if db_session is None:
        return None
    return db.get(User, db_session.user_id)


@router.get("/home", response_model=HomeResponse)
def home(
    db: DbSession = Depends(get_db),
    session: str | None = Cookie(default=None, alias=settings.session_cookie_name),
) -> HomeResponse:
    user = _resolve_user(db, session)
    if user is None:
        return HomeResponse(user=None, businesses=None, hero_audit=None)

    me = build_me_response(db, user)
    businesses = build_business_list(db, user)

    hero_audit = None
    if len(businesses) == 1 and businesses[0].latest_audit_id is not None:
        # build_business_list already proved ownership (it only ever returns
        # the caller's own rows), so this re-read is a plain primary-key get.
        biz = db.get(Business, businesses[0].id)
        if biz is not None:
            audit = latest_completed_audit(db, biz.id)
            if audit is not None:
                hero_audit = AuditDetailResponse(**build_audit_detail(db, audit))

    return HomeResponse(user=me, businesses=businesses, hero_audit=hero_audit)
