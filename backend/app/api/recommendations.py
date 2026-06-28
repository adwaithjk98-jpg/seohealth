import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth_deps import current_user
from app.db import get_db
from app.models import Audit, Business, InsightReport, Recommendation, User
from app.models.enums import RecommendationFixStatus
from app.schemas.audit import (
    RecommendationResponse,
    RecommendationUpdateRequest,
)
from app.services import email_service

logger = logging.getLogger(__name__)

router = APIRouter()


class ReportInsightRequest(BaseModel):
    """A user flagging a recommendation as wrong.

    ``reason`` is a fixed set so reports are groupable in the founder panel;
    ``note`` is the optional free-text "what's actually wrong" detail.
    """

    reason: Literal["incorrect", "outdated", "not_applicable", "other"]
    note: str | None = Field(default=None, max_length=1000)


@router.patch("/recommendations/{rec_id}", response_model=RecommendationResponse)
def update_recommendation(
    rec_id: int,
    payload: RecommendationUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> RecommendationResponse:
    rec = db.get(Recommendation, rec_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="recommendation not found")

    # Ownership chain: recommendation -> audit -> business -> user.
    audit = db.get(Audit, rec.audit_id)
    business = db.get(Business, audit.business_id) if audit is not None else None
    if business is None or business.user_id != user.id:
        raise HTTPException(status_code=404, detail="recommendation not found")

    new_status = RecommendationFixStatus(payload.fix_status)
    rec.fix_status = new_status

    if new_status is RecommendationFixStatus.done:
        rec.marked_done_at = datetime.now(timezone.utc)
    else:
        # Re-opening or dismissing clears the done timestamp.
        rec.marked_done_at = None

    db.commit()
    db.refresh(rec)

    return RecommendationResponse(
        id=rec.id,
        section=rec.section.value,
        severity=rec.severity.value,
        title=rec.title,
        body_markdown=rec.body_markdown,
        estimated_impact=rec.estimated_impact,
        estimated_time=rec.estimated_time,
        fix_status=rec.fix_status.value,
        marked_done_at=rec.marked_done_at,
    )


@router.post(
    "/recommendations/{rec_id}/report",
    status_code=status.HTTP_204_NO_CONTENT,
)
def report_recommendation(
    rec_id: int,
    payload: ReportInsightRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    """File a 'this insight looks wrong' report against a recommendation.

    Persists the report (so the founder can spot patterns) and best-effort
    emails the founder. The rec's identifying fields are denormalized onto
    the report so it survives the rec's cascade-delete when its audit is
    pruned. Ownership is enforced via the rec -> audit -> business -> user
    chain, same as the mark-as-done PATCH.
    """
    rec = db.get(Recommendation, rec_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="recommendation not found")

    audit = db.get(Audit, rec.audit_id)
    business = db.get(Business, audit.business_id) if audit is not None else None
    if business is None or business.user_id != user.id:
        raise HTTPException(status_code=404, detail="recommendation not found")

    report = InsightReport(
        user_id=user.id,
        business_id=business.id,
        audit_id=rec.audit_id,
        recommendation_id=rec.id,
        section=rec.section.value,
        rec_title=rec.title,
        reason=payload.reason,
        note=(payload.note or None),
    )
    db.add(report)
    db.commit()

    # Best-effort founder ping — the report row is already safe, so a flaky
    # email provider never costs us the signal.
    try:
        email_service.send_insight_report_email(
            user_email=user.email,
            business_name=business.name,
            section=rec.section.value,
            rec_title=rec.title,
            reason=payload.reason,
            note=payload.note,
        )
    except Exception:
        logger.exception("insight-report email failed for rec_id=%s", rec_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
