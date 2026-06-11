"""Web Push subscription management.

The browser subscribes via the PushManager, then POSTs the resulting
subscription here so the backend can push to it later (scheduled-audit-done and
competitor-moved notifications). The VAPID *public* key is served to the
frontend so it can build the ``applicationServerKey`` at subscribe time — the
backend stays the single source of truth for the keypair.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth_deps import current_user
from app.config import settings
from app.db import get_db
from app.models import User
from app.models.push_subscription import PushSubscription

router = APIRouter(prefix="/push", tags=["push"])


class PushKeys(BaseModel):
    p256dh: str
    auth: str


class SubscribePayload(BaseModel):
    endpoint: str = Field(min_length=1, max_length=512)
    keys: PushKeys


class UnsubscribePayload(BaseModel):
    endpoint: str = Field(min_length=1, max_length=512)


@router.get("/vapid-public-key")
def vapid_public_key() -> dict[str, str]:
    """Public VAPID key for the browser's ``applicationServerKey``.

    Empty string when push isn't configured — the frontend treats that as
    "push unavailable" and hides the toggle.
    """
    return {"public_key": settings.vapid_public_key}


@router.post("/subscribe", status_code=status.HTTP_204_NO_CONTENT)
def subscribe(
    payload: SubscribePayload,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    """Upsert the caller's push subscription, keyed on the endpoint.

    Endpoints are globally unique (the push service issues one per
    subscription), so if the same endpoint re-appears — e.g. the user signed
    in on a device a different account had subscribed before — we re-point it
    at the current user and refresh its keys.
    """
    existing = (
        db.query(PushSubscription)
        .filter(PushSubscription.endpoint == payload.endpoint)
        .first()
    )
    ua = (request.headers.get("user-agent", "") or "")[:400] or None
    if existing is not None:
        existing.user_id = user.id
        existing.p256dh = payload.keys.p256dh
        existing.auth = payload.keys.auth
        existing.user_agent = ua
    else:
        db.add(
            PushSubscription(
                user_id=user.id,
                endpoint=payload.endpoint,
                p256dh=payload.keys.p256dh,
                auth=payload.keys.auth,
                user_agent=ua,
            )
        )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/unsubscribe", status_code=status.HTTP_204_NO_CONTENT)
def unsubscribe(
    payload: UnsubscribePayload,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    """Delete the caller's subscription for this endpoint (idempotent)."""
    db.query(PushSubscription).filter(
        PushSubscription.endpoint == payload.endpoint,
        PushSubscription.user_id == user.id,
    ).delete(synchronize_session=False)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
