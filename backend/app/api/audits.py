import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Audit, Business
from app.models.enums import AuditStatus, AuditTrigger
from app.schemas.audit import (
    AuditCreateRequest,
    AuditCreateResponse,
    AuditDetailResponse,
)
from app.services import audit_events
from app.services.audit_runner import run_audit
from app.services.audit_view import build_audit_detail

router = APIRouter()


@router.post(
    "/audits",
    response_model=AuditCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_audit(
    payload: AuditCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> AuditCreateResponse:
    business = db.get(Business, payload.business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="business not found")

    audit = Audit(
        business_id=payload.business_id,
        status=AuditStatus.pending,
        trigger=AuditTrigger(payload.trigger),
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)

    audit_events.get_or_create_stream(audit.id)
    background_tasks.add_task(run_audit, audit.id)

    return AuditCreateResponse(
        audit_id=audit.id,
        status=audit.status.value,
        stream_url=f"/api/audits/{audit.id}/stream",
        started_at=audit.started_at,
    )


@router.get("/audits/{audit_id}", response_model=AuditDetailResponse)
def get_audit_detail(audit_id: int, db: Session = Depends(get_db)) -> AuditDetailResponse:
    audit = db.get(Audit, audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="audit not found")
    return AuditDetailResponse(**build_audit_detail(db, audit))


@router.get(
    "/businesses/{business_id}/latest-audit",
    response_model=AuditDetailResponse,
)
def get_latest_audit_for_business(
    business_id: int, db: Session = Depends(get_db)
) -> AuditDetailResponse:
    business = db.get(Business, business_id)
    if business is None:
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
def stream_audit(audit_id: int, db: Session = Depends(get_db)) -> StreamingResponse:
    audit = db.get(Audit, audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="audit not found")

    async def event_generator() -> AsyncIterator[str]:
        stream = audit_events.get_stream(audit_id)
        if stream is None:
            yield _format_sse(
                "audit_state",
                {
                    "audit_id": audit_id,
                    "status": audit.status.value,
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
