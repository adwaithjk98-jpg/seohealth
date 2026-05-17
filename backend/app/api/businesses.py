from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.auth_deps import current_user
from app.db import get_db
from app.models import Audit, Business, User
from app.models.enums import AuditStatus
from app.schemas.business import BusinessCreateRequest, BusinessResponse
from app.services import subscriptions as subs_service
from app.services.audit_summary import grade_from_score
from app.services.audit_view import TREND_THRESHOLD
from app.services.auto_audit import next_auto_audit_at

router = APIRouter()


def _trend(current: int | None, previous: int | None) -> str | None:
    if current is None or previous is None:
        return None
    diff = current - previous
    if diff >= TREND_THRESHOLD:
        return "up"
    if diff <= -TREND_THRESHOLD:
        return "down"
    return "flat"


def _audit_overall_score(audit: Audit) -> int | None:
    scores = [s.score for s in audit.sections if s.score is not None]
    return round(sum(scores) / len(scores)) if scores else None


def _latest_two_completed(db: Session, business_id: int) -> list[Audit]:
    return (
        db.query(Audit)
        .filter(
            Audit.business_id == business_id,
            Audit.status == AuditStatus.done,
        )
        .order_by(desc(Audit.finished_at), desc(Audit.id))
        .limit(2)
        .all()
    )


def _running_audit_id(db: Session, business_id: int) -> int | None:
    """A "running" audit is anything that hasn't reached a terminal state.

    Includes ``pending`` (queued, worker not yet picked up) and ``running``
    (worker actively processing). Used to gate re-audit and add-business
    so a stuck or in-flight audit doesn't get stacked on by an impatient
    user. The on_failure callback in workers/queue.py guarantees no audit
    sits in either state forever — RQ will transition it to ``failed``.
    """
    audit = (
        db.query(Audit)
        .filter(
            Audit.business_id == business_id,
            Audit.status.in_([AuditStatus.pending, AuditStatus.running]),
        )
        .order_by(desc(Audit.id))
        .first()
    )
    return audit.id if audit else None


def _to_response(db: Session, b: Business, user: User) -> BusinessResponse:
    completed = _latest_two_completed(db, b.id)
    latest = completed[0] if completed else None
    prev = completed[1] if len(completed) > 1 else None
    latest_score = _audit_overall_score(latest) if latest else None
    prev_score = _audit_overall_score(prev) if prev else None
    return BusinessResponse(
        id=b.id,
        name=b.name,
        city=b.city,
        country=b.country,
        maps_url=b.maps_url,
        website=b.website,
        ig_handle=b.ig_handle,
        added_at=b.added_at,
        latest_score=latest_score,
        latest_grade=grade_from_score(latest_score) if latest_score is not None else None,
        latest_trend=_trend(latest_score, prev_score),
        latest_audit_id=latest.id if latest else None,
        latest_audit_finished_at=latest.finished_at if latest else None,
        running_audit_id=_running_audit_id(db, b.id),
        next_auto_audit_at=next_auto_audit_at(db, b, user),
    )


def _find_existing_business(
    db: Session, user_id: int, name: str, city: str, maps_url: str | None
) -> Business | None:
    """Return a non-archived business that matches by maps_url (canonical
    identity) or by case-insensitive (name, city). Lets duplicate submits
    short-circuit to the existing record instead of cluttering the dashboard.
    """
    q = db.query(Business).filter(
        Business.user_id == user_id, Business.archived_at.is_(None)
    )
    if maps_url:
        by_url = q.filter(Business.maps_url == maps_url).first()
        if by_url is not None:
            return by_url
    return q.filter(
        func.lower(Business.name) == name.lower(),
        func.lower(Business.city) == city.lower(),
    ).first()


@router.post(
    "/businesses",
    response_model=BusinessResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_business(
    payload: BusinessCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> BusinessResponse:
    name = (payload.name or "").strip() or "My business"
    city = (payload.city or "").strip() or "Unknown"

    website = (payload.website or "").strip() or None
    ig_handle = (payload.ig_handle or "").strip().lstrip("@") or None
    maps_url = (payload.maps_url or "").strip() or None

    existing = _find_existing_business(db, user.id, name, city, maps_url)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "business_exists",
                "message": "You already have this business on your dashboard.",
                "existing_business_id": existing.id,
            },
        )

    # Free: 1 business. Paid: 3. Enforced here (not just in the UI) so a curl
    # or stale tab can't bypass the cap. AuditAppPlan §8 — "Pricing model".
    business_limit = subs_service.user_business_limit(user)
    current_count = subs_service.count_active_businesses(db, user.id)
    if current_count >= business_limit:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "business_limit_reached",
                "message": (
                    "You've reached the limit for your plan. Upgrade to add more businesses."
                ),
                "tier": user.plan.value,
                "limit": business_limit,
                "business_count": current_count,
            },
        )

    business = Business(
        user_id=user.id,
        name=name,
        city=city,
        country=payload.country.strip() or "India",
        maps_url=maps_url,
        website=website,
        ig_handle=ig_handle,
    )
    db.add(business)
    db.commit()
    db.refresh(business)

    return _to_response(db, business, user)


@router.get("/businesses", response_model=list[BusinessResponse])
def list_businesses(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[BusinessResponse]:
    rows = (
        db.query(Business)
        .filter(Business.user_id == user.id, Business.archived_at.is_(None))
        .order_by(desc(Business.added_at))
        .all()
    )
    return [_to_response(db, b, user) for b in rows]
