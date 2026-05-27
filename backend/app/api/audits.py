import json
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

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
    AuditQuotaResponse,
)
from app.services import audit_events
from app.services import auth as auth_service
from app.services import subscriptions as subs_service
from app.services.audit_view import build_audit_detail
from app.workers.queue import enqueue_audit

router = APIRouter()


def _user_owns_business(business: Business, user: User) -> bool:
    return business.user_id == user.id


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _audit_usage_this_week(db: Session, user_id: int) -> tuple[int, datetime]:
    """Audits the user has started in the rolling 7-day window.

    Rolling window (not calendar week) so the user can predict exactly
    when the next slot frees up — ``(window_start, started_at + 7d)``.
    Returns the count and the timestamp at which the oldest audit in the
    window ages out (i.e., when one slot reopens).

    ``failed`` audits are excluded from the count — the runner only
    marks an audit failed when Maps couldn't load (so no useful work
    was done) or when an unrecoverable crash short-circuits the
    pipeline. In both cases the user shouldn't have a quota slot
    consumed by something that effectively didn't run. Pending/running
    audits still count so a stuck job can't be retried into a quota
    overrun.
    """
    now = _now_naive()
    window_start = now - timedelta(days=7)
    audits_in_window: list[Audit] = (
        db.query(Audit)
        .join(Business, Audit.business_id == Business.id)
        .filter(
            Business.user_id == user_id,
            Audit.started_at >= window_start,
            Audit.status != AuditStatus.failed,
        )
        .order_by(Audit.started_at)
        .all()
    )
    used = len(audits_in_window)
    # The next reset is when the oldest in-window audit hits its
    # 7-day anniversary. If we have no audits in the window, "reset" is
    # meaningless — return now + 7d as a stable upper bound.
    if audits_in_window:
        next_reset = audits_in_window[0].started_at + timedelta(days=7)
    else:
        next_reset = now + timedelta(days=7)
    return used, next_reset


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

    # Weekly quota applies to ALL audits — manual + scheduled —
    # since 2026-05-26. The old bypass for ``trigger='scheduled'`` was
    # built when auto-audits were free / automatic; under the opt-in
    # model the user explicitly chose to schedule the business, so each
    # auto-fire is just as much "the user spending a slot" as a manual
    # click is. The dispatcher itself also pre-checks the quota and
    # skips when full, so this gate is the belt to its suspenders.
    weekly_limit = subs_service.TIER_LIMITS[user.plan]["audits_per_week"]
    used, next_reset = _audit_usage_this_week(db, user.id)
    if used >= weekly_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "audit_weekly_limit",
                "message": (
                    f"You've used your {weekly_limit} audit"
                    f"{'s' if weekly_limit != 1 else ''} for this week."
                ),
                "tier": user.plan.value,
                "limit": weekly_limit,
                "used": used,
                "next_reset_at": next_reset.isoformat(),
            },
        )

    # Guard against stacking audits on a business that already has one
    # in-flight (pending or running). The on_failure callback in
    # workers/queue.py guarantees nothing stays in those states forever,
    # so this can't lock a user out of re-auditing after a crash.
    in_flight = (
        db.query(Audit)
        .filter(
            Audit.business_id == payload.business_id,
            Audit.status.in_([AuditStatus.pending, AuditStatus.running]),
        )
        .order_by(desc(Audit.id))
        .first()
    )
    if in_flight is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "audit_in_flight",
                "message": "An audit is already running for this business.",
                "running_audit_id": in_flight.id,
            },
        )

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


@router.get("/audits/quota", response_model=AuditQuotaResponse)
def get_audit_quota(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> AuditQuotaResponse:
    """Rolling 7-day audit usage + tier limit for the Audit tab counter.

    Frontend uses this to gate the Run-audit CTA. Defined ahead of the
    ``/{audit_id}`` GET so FastAPI's path matching doesn't try to route
    ``quota`` as an id.
    """
    limit = subs_service.TIER_LIMITS[user.plan]["audits_per_week"]
    used, period_end = _audit_usage_this_week(db, user.id)
    return AuditQuotaResponse(
        used=used,
        limit=limit,
        remaining=max(0, limit - used),
        period_end=period_end,
        tier=user.plan.value,
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
