from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.config import settings
from app.ratelimit import limiter
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.auth_deps import current_user
from app.db import get_db
from app.models import Audit, Business, Recommendation, User
from app.models.enums import AuditStatus, RecommendationFixStatus, UserPlan
from app.schemas.business import (
    BusinessCreateRequest,
    BusinessProfileUpdateRequest,
    BusinessResponse,
    BusinessScheduleRequest,
)
from app.services import subscriptions as subs_service
from app.services.audit_summary import grade_from_score
from app.services.audit_view import TREND_THRESHOLD
from app.services.auto_audit import allowed_cadences, next_auto_audit_at
from app.services.pillar_optout import enabled_pillars
from app.services.scoring import overall_from_section_scores
from scrapers.ig_graph import discover_business
from scrapers.instagram import IG_UNAVAILABLE_NOT_BUSINESS_NOTE

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


def _audit_overall_score(audit: Audit, business: Business) -> int | None:
    # One shared rule (services/scoring): mean of sections whose score is not
    # None (a measured 0 counts, unmeasurable None doesn't; status is never the
    # filter), with opted-out pillars excluded so a website-less café isn't
    # scored as if a 0/100 website pillar were dragging it down.
    return overall_from_section_scores(
        ((s.section.value, s.score) for s in audit.sections),
        enabled_pillars(business),
    )


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


def _open_count_for_audit(db: Session, audit_id: int | None) -> int:
    """Open recommendations on a single audit. Cheap; used by the
    single-business endpoints. The list endpoint batches via
    ``_open_counts_by_audit`` to avoid an N+1."""
    if audit_id is None:
        return 0
    return (
        db.query(func.count(Recommendation.id))
        .filter(
            Recommendation.audit_id == audit_id,
            Recommendation.fix_status == RecommendationFixStatus.open,
        )
        .scalar()
        or 0
    )


def _open_counts_by_audit(
    db: Session, audit_ids: list[int]
) -> dict[int, int]:
    """Map ``audit_id`` → open-recommendation count for the listing path."""
    if not audit_ids:
        return {}
    rows = (
        db.query(Recommendation.audit_id, func.count(Recommendation.id))
        .filter(
            Recommendation.audit_id.in_(audit_ids),
            Recommendation.fix_status == RecommendationFixStatus.open,
        )
        .group_by(Recommendation.audit_id)
        .all()
    )
    return {audit_id: count for audit_id, count in rows}


def _to_response(
    db: Session,
    b: Business,
    user: User,
    *,
    open_count: int | None = None,
) -> BusinessResponse:
    completed = _latest_two_completed(db, b.id)
    latest = completed[0] if completed else None
    prev = completed[1] if len(completed) > 1 else None
    latest_score = _audit_overall_score(latest, b) if latest else None
    prev_score = _audit_overall_score(prev, b) if prev else None
    if open_count is None:
        open_count = _open_count_for_audit(db, latest.id if latest else None)
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
        open_recommendations_count=open_count,
        audit_schedule_cadence=b.audit_schedule_cadence,
        next_auto_audit_at=next_auto_audit_at(db, b, user),
        business_type=b.business_type,
        has_website=b.has_website,
        has_instagram=b.has_instagram,
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
@limiter.limit(settings.rate_limit_create)
def create_business(
    request: Request,
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
        # FTUE answers, all nullable. Defaults fall through to NULL
        # when the caller is a legacy script that doesn't send them —
        # the dashboard banner picks those up and prompts the user.
        business_type=payload.business_type,
        has_website=payload.has_website,
        has_instagram=payload.has_instagram,
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
    # Batch the latest-audit lookups so we can ask for open counts in one
    # query rather than N. ``_to_response`` recomputes ``latest`` per
    # business, but that's a cheap two-row query already cached at the
    # ORM level once we touch the same audits here.
    latest_audit_ids: list[int] = []
    for b in rows:
        completed = _latest_two_completed(db, b.id)
        if completed:
            latest_audit_ids.append(completed[0].id)
    open_counts = _open_counts_by_audit(db, latest_audit_ids)
    out: list[BusinessResponse] = []
    for b in rows:
        completed = _latest_two_completed(db, b.id)
        latest_id = completed[0].id if completed else None
        out.append(
            _to_response(db, b, user, open_count=open_counts.get(latest_id, 0))
        )
    return out


@router.get("/businesses/{business_id}", response_model=BusinessResponse)
def get_business(
    business_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> BusinessResponse:
    biz = db.get(Business, business_id)
    if biz is None or biz.user_id != user.id or biz.archived_at is not None:
        raise HTTPException(status_code=404, detail="business not found")
    return _to_response(db, biz, user)


@router.get("/businesses/{business_id}/instagram-eligibility")
async def get_instagram_eligibility(
    business_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, object | None]:
    """Cheap pre-audit probe: can we read this business's IG via the Graph API?

    Lets the UI warn *before* the user spends a (quota-limited) audit on a
    handle whose stats we can't fetch. Uses ``business_discovery`` (cached 6h,
    no audit-quota cost). Returns ``eligible``:
    - ``True``  → it's a Business/Creator account; IG will be tracked.
    - ``False`` → not a Business/Creator account (show the nudge). ``note`` set.
    - ``None``  → unknown (no handle, or a transient Graph/token error) — the
      caller should stay silent rather than guess.
    """
    biz = db.get(Business, business_id)
    if biz is None or biz.user_id != user.id or biz.archived_at is not None:
        raise HTTPException(status_code=404, detail="business not found")

    handle = (biz.ig_handle or "").strip().lstrip("@") or None
    if not handle:
        return {"handle": None, "eligible": None, "reason": "no_handle", "note": None}

    result = await discover_business(handle)
    if result.ok:
        return {"handle": handle, "eligible": True, "reason": None, "note": None}
    if result.status == "not_eligible":
        return {
            "handle": handle,
            "eligible": False,
            "reason": "not_business_account",
            "note": IG_UNAVAILABLE_NOT_BUSINESS_NOTE,
        }
    # Transient our-side error (token/rate/network) — don't claim anything.
    return {"handle": handle, "eligible": None, "reason": "fetch_error", "note": None}


@router.delete(
    "/businesses/{business_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def archive_business(
    business_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    """Soft-archive one of the user's businesses.

    Mirrors the competitor archive shape: sets ``archived_at`` rather
    than deleting, so audit history + competitor observations survive
    in case the user wants their data later. The dashboard query
    already filters on ``archived_at IS NULL``, so the row drops out
    of every list-view but stays addressable via direct id (useful
    for support / re-activation paths). Re-adding the same business
    later goes through ``create_business`` which already short-
    circuits via ``_find_existing_business``.
    """
    biz = db.get(Business, business_id)
    if biz is None or biz.user_id != user.id:
        raise HTTPException(status_code=404, detail="business not found")
    if biz.archived_at is None:
        biz.archived_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/businesses/{business_id}/schedule",
    response_model=BusinessResponse,
)
def set_business_schedule(
    business_id: int,
    payload: BusinessScheduleRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> BusinessResponse:
    """Set or clear the auto-audit cadence for one of the user's businesses.

    Payload: ``{"cadence": "weekly" | "biweekly" | "monthly" | null}``.
    Null clears the schedule (opt-out). Validated by the schema.

    Paid-tier-gated — auto-audits are a paid feature. Free users hit
    402 and can't enable a schedule even if they hand-craft a request.
    The dispatcher itself defends against this anyway (only paid users
    are walked), but rejecting at the API saves the user a confused
    "I scheduled it but nothing happened" loop.
    """
    biz = db.get(Business, business_id)
    if biz is None or biz.user_id != user.id or biz.archived_at is not None:
        raise HTTPException(status_code=404, detail="business not found")
    if user.plan == UserPlan.free and payload.cadence is not None:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "schedule_paid_only",
                "message": "Scheduled audits are a paid-tier feature. Upgrade to enable a schedule.",
                "tier": user.plan.value,
            },
        )
    # Twice-weekly is a Max perk. Pro tops out at weekly.
    if payload.cadence is not None and payload.cadence not in allowed_cadences(user.plan):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "cadence_not_allowed",
                "message": "Twice-weekly auto-audits are a Max feature. Upgrade to Max for it.",
                "tier": user.plan.value,
            },
        )
    biz.audit_schedule_cadence = payload.cadence
    db.commit()
    db.refresh(biz)
    return _to_response(db, biz, user)


@router.patch(
    "/businesses/{business_id}/profile",
    response_model=BusinessResponse,
)
def update_business_profile(
    business_id: int,
    payload: BusinessProfileUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> BusinessResponse:
    """FTUE questionnaire writes — ``business_type`` and the
    ``has_website`` / ``has_instagram`` opt-out flags.

    Only non-NULL fields in the payload are applied, so the dashboard
    banner can patch one answer at a time without resetting the others.
    Re-enabling a pillar (``has_website=true`` after a previous False)
    is allowed; the next audit picks the pillar back up automatically.
    """
    biz = db.get(Business, business_id)
    if biz is None or biz.user_id != user.id or biz.archived_at is not None:
        raise HTTPException(status_code=404, detail="business not found")
    if payload.business_type is not None:
        biz.business_type = payload.business_type
    if payload.has_website is not None:
        biz.has_website = payload.has_website
    if payload.has_instagram is not None:
        biz.has_instagram = payload.has_instagram
    db.commit()
    db.refresh(biz)
    return _to_response(db, biz, user)
