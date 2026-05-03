from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth_deps import current_user
from app.db import get_db
from app.models import Audit, Business, Recommendation, User
from app.models.enums import RecommendationFixStatus
from app.schemas.audit import (
    RecommendationResponse,
    RecommendationUpdateRequest,
)

router = APIRouter()


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
