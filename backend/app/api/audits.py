import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Cookie, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.auth_deps import current_user
from app.config import settings
from app.db import get_db
from app.models import Audit, Business, User
from app.models.enums import AuditStatus, AuditTrigger
from app.schemas.audit import (
    AuditCreateRequest,
    AuditCreateResponse,
    AuditDetailResponse,
)
from app.services import audit_events
from app.services import auth as auth_service
from app.services.audit_view import build_audit_detail
from app.workers.queue import enqueue_audit

router = APIRouter()


def _user_owns_business(business: Business, user: User) -> bool:
    return business.user_id == user.id


def _load_audit_for_user(db: Session, audit_id: int, user: User) -> Audit:
    audit = db.get(Audit, audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="audit not found")
    business = db.get(Business, audit.business_id)
    # Treat "audit owned by another user" as 404 — don't leak existence.
    if business is None or not _user_owns_business(business, user):
        raise HTTPException(status_code=404, detail="audit not found")
    return audit


@router.post(
    "/audits",
    response_model=AuditCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_audit(
    payload: AuditCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> AuditCreateResponse:
    business = db.get(Business, payload.business_id)
    if business is None or not _user_owns_business(business, user):
        raise HTTPException(status_code=404, detail="business not found")

    audit = Audit(
        business_id=payload.business_id,
        status=AuditStatus.pending,
        trigger=AuditTrigger(payload.trigger),
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)

    # enqueue_audit() XADDs a stream marker before pushing the job, so a
    # fast SSE client connecting after this returns sees a live stream
    # key and not an empty one.
    try:
        enqueue_audit(audit.id)
    except RedisConnectionError:
        # Redis unreachable — drop the orphan row so the user doesn't see
        # an audit stuck at `pending` forever, then surface a clean 503.
        # No fallback to in-process execution: that would defeat the
        # queue's capacity control and hide the outage.
        db.delete(audit)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audit queue unavailable, please try again shortly",
        )

    return AuditCreateResponse(
        audit_id=audit.id,
        status=audit.status.value,
        stream_url=f"/api/audits/{audit.id}/stream",
        started_at=audit.started_at,
    )


@router.get("/audits/{audit_id}", response_model=AuditDetailResponse)
def get_audit_detail(
    audit_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> AuditDetailResponse:
    audit = _load_audit_for_user(db, audit_id, user)
    return AuditDetailResponse(**build_audit_detail(db, audit))


@router.get(
    "/businesses/{business_id}/latest-audit",
    response_model=AuditDetailResponse,
)
def get_latest_audit_for_business(
    business_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> AuditDetailResponse:
    business = db.get(Business, business_id)
    if business is None or not _user_owns_business(business, user):
        raise HTTPException(status_code=404, detail="business not found")

    audit = (
        db.query(Audit)
        .filter(Audit.business_id == business_id, Audit.status == AuditStatus.done)
        .order_by(desc(Audit.finished_at), desc(Audit.id))
        .first()
    )
    if audit is None:
        raise HTTPException(
            status_code=404, detail="no completed audit yet for this business"
        )
    return AuditDetailResponse(**build_audit_detail(db, audit))


def _format_sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


@router.get("/audits/{audit_id}/stream")
def stream_audit(
    audit_id: int,
    db: Session = Depends(get_db),
    session: str | None = Cookie(default=None, alias=settings.session_cookie_name),
) -> StreamingResponse:
    # EventSource doesn't support custom headers, but it does send cookies on
    # same-origin requests. Authenticate manually via the session cookie so we
    # can return a streaming response on success.
    if not session:
        raise HTTPException(status_code=401, detail="not authenticated")
    db_session = auth_service.get_session_by_token(db, session)
    if db_session is None:
        raise HTTPException(status_code=401, detail="session expired or invalid")

    audit = db.get(Audit, audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="audit not found")
    business = db.get(Business, audit.business_id)
    if business is None or business.user_id != db_session.user_id:
        raise HTTPException(status_code=404, detail="audit not found")

    audit_status_value = audit.status.value

    async def event_generator() -> AsyncIterator[str]:
        stream = audit_events.get_stream(audit_id)
        if stream is None:
            yield _format_sse(
                "audit_state",
                {
                    "audit_id": audit_id,
                    "status": audit_status_value,
                    "note": "no live stream available; read the audit record for full state",
                },
            )
            return

        async for event in stream.subscribe():
            yield _format_sse(event.get("type", "message"), event)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
