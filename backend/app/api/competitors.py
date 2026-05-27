"""Competitor CRUD routes (Phase 4 — paid-tier feature).

Three endpoints, all scoped to a business the caller owns:
  - ``POST   /api/businesses/{id}/competitors``     add by Maps URL
  - ``GET    /api/businesses/{id}/competitors``     list active competitors
  - ``DELETE /api/businesses/{id}/competitors/{cid}`` archive (soft delete)

Tier rules: free users get ``402 Payment Required`` on POST; paid users
cap at ``TIER_LIMITS[paid]["competitors"]`` (3 today). The cap is enforced
here, not just in the UI, so a curl or stale tab can't bypass it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.auth_deps import current_user
from app.db import get_db
from app.models import Audit, AuditSection, Business, Competitor, CompetitorObservation, User
from app.models.enums import AuditSectionName, AuditStatus
from app.schemas.competitor import (
    BusinessTrendsResponse,
    CompetitorCreateRequest,
    CompetitorResponse,
    CompetitorTrend,
    HubInsightsResponse,
    InsightCardResponse,
    InsightFactResponse,
    TrendPoint,
)
from app.services import competitor_insights as insights_service
from app.services import subscriptions as subs_service
from app.services import visibility_score as visibility_service
from app.services.competitor_cache import normalize_maps_url
from app.workers.queue import enqueue_competitor_refresh

logger = logging.getLogger(__name__)

router = APIRouter()


def _kick_first_refresh(maps_url: str | None) -> None:
    """Best-effort: enqueue an immediate refresh for a newly-tracked competitor.

    Without this, a freshly-added competitor's trend chart is blank for
    up to a week — the daily ``competitor_refresh`` cron only acts on
    rows whose cache entry is stale (>6 days). A brand new row has no
    cache entry, but the cron only fires once per day, so users still
    saw "we'll start drawing your line on the next refresh" up to ~24h
    after Track. Enqueueing here lands the first observation in seconds.

    Silent on Redis-down: the cron path is still in place so the
    competitor will be picked up on the next nightly tick.
    """
    if not maps_url:
        return
    try:
        key = normalize_maps_url(maps_url)
        if key:
            enqueue_competitor_refresh(key, maps_url)
    except Exception:
        logger.exception("immediate competitor refresh enqueue failed for %r", maps_url)


def _own_business_or_404(db: Session, user: User, business_id: int) -> Business:
    business = (
        db.query(Business)
        .filter(
            Business.id == business_id,
            Business.user_id == user.id,
            Business.archived_at.is_(None),
        )
        .one_or_none()
    )
    if business is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="business not found",
        )
    return business


def _latest_observation_map(
    db: Session, competitor_ids: list[int]
) -> dict[int, CompetitorObservation]:
    """Map competitor_id → most recent observation row, in one query.

    Avoids the N+1 we'd get from looping ``order_by ... limit 1`` per
    competitor on the listing endpoint.
    """
    if not competitor_ids:
        return {}
    rows: list[CompetitorObservation] = (
        db.query(CompetitorObservation)
        .filter(CompetitorObservation.competitor_id.in_(competitor_ids))
        .order_by(desc(CompetitorObservation.observed_at), desc(CompetitorObservation.id))
        .all()
    )
    latest: dict[int, CompetitorObservation] = {}
    for row in rows:
        latest.setdefault(row.competitor_id, row)
    return latest


def _observation_counts(db: Session, competitor_ids: list[int]) -> dict[int, int]:
    if not competitor_ids:
        return {}
    rows = (
        db.query(
            CompetitorObservation.competitor_id,
            func.count(CompetitorObservation.id),
        )
        .filter(CompetitorObservation.competitor_id.in_(competitor_ids))
        .group_by(CompetitorObservation.competitor_id)
        .all()
    )
    return {cid: count for cid, count in rows}


def _to_response(
    competitor: Competitor,
    latest: CompetitorObservation | None,
    observation_count: int,
) -> CompetitorResponse:
    visibility = (
        visibility_service.compute(
            rating=latest.rating,
            review_count=latest.review_count,
            instagram_followers=latest.instagram_followers,
        )
        if latest is not None
        else None
    )
    return CompetitorResponse(
        id=competitor.id,
        business_id=competitor.business_id,
        name=competitor.name,
        maps_url=competitor.maps_url,
        instagram_url=competitor.instagram_url,
        website_url=competitor.website_url,
        added_at=competitor.added_at,
        latest_rating=latest.rating if latest else None,
        latest_review_count=latest.review_count if latest else None,
        latest_instagram_followers=latest.instagram_followers if latest else None,
        latest_instagram_posts=latest.instagram_posts if latest else None,
        latest_visibility_score=visibility,
        latest_observed_at=latest.observed_at if latest else None,
        observation_count=observation_count,
    )


@router.get(
    "/businesses/{business_id}/competitors",
    response_model=list[CompetitorResponse],
)
def list_competitors(
    business_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[CompetitorResponse]:
    _own_business_or_404(db, user, business_id)
    competitors = (
        db.query(Competitor)
        .filter(
            Competitor.business_id == business_id,
            Competitor.archived_at.is_(None),
        )
        .order_by(Competitor.added_at)
        .all()
    )
    ids = [c.id for c in competitors]
    latest_map = _latest_observation_map(db, ids)
    counts = _observation_counts(db, ids)
    return [
        _to_response(c, latest_map.get(c.id), counts.get(c.id, 0))
        for c in competitors
    ]


@router.post(
    "/businesses/{business_id}/competitors",
    response_model=CompetitorResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_competitor(
    business_id: int,
    payload: CompetitorCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> CompetitorResponse:
    business = _own_business_or_404(db, user, business_id)

    limit = subs_service.user_competitor_limit(user)
    if limit <= 0:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "competitors_paid_only",
                "message": "Competitor tracking is a paid-tier feature. Upgrade to add competitors.",
                "tier": user.plan.value,
                "limit": limit,
            },
        )

    maps_url = payload.maps_url.strip()
    if not maps_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="maps_url is required",
        )

    existing_dup = (
        db.query(Competitor)
        .filter(
            Competitor.business_id == business.id,
            Competitor.archived_at.is_(None),
            Competitor.maps_url == maps_url,
        )
        .first()
    )
    if existing_dup is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "competitor_exists",
                "message": "You're already tracking this competitor.",
                "existing_competitor_id": existing_dup.id,
            },
        )

    # If the user previously tracked this competitor and archived them,
    # un-archive the original row instead of creating a duplicate.
    # Otherwise a re-add stranded the old observations on a dead row +
    # spawned a fresh one with no history. We update name / IG / website
    # from the new payload in case the user is correcting a typo.
    existing_archived = (
        db.query(Competitor)
        .filter(
            Competitor.business_id == business.id,
            Competitor.archived_at.isnot(None),
            Competitor.maps_url == maps_url,
        )
        .order_by(Competitor.archived_at.desc())
        .first()
    )
    if existing_archived is not None:
        # Cap still applies — un-archiving counts toward it just like
        # a fresh add would.
        revival_count = (
            db.query(Competitor)
            .join(Business, Competitor.business_id == Business.id)
            .filter(
                Business.user_id == user.id,
                Business.archived_at.is_(None),
                Competitor.archived_at.is_(None),
            )
            .count()
        )
        if revival_count >= limit:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "code": "competitor_limit_reached",
                    "message": (
                        f"Your plan allows up to {limit} competitors total. "
                        "Remove one to bring this archived one back."
                    ),
                    "tier": user.plan.value,
                    "limit": limit,
                    "competitor_count": revival_count,
                },
            )
        existing_archived.archived_at = None
        name_override = (payload.name or "").strip()
        if name_override:
            existing_archived.name = name_override
        ig_override = (payload.instagram_url or "").strip()
        if ig_override:
            existing_archived.instagram_url = ig_override
        web_override = (payload.website_url or "").strip()
        if web_override:
            existing_archived.website_url = web_override
        db.commit()
        db.refresh(existing_archived)
        _kick_first_refresh(existing_archived.maps_url)
        latest_map = _latest_observation_map(db, [existing_archived.id])
        counts = _observation_counts(db, [existing_archived.id])
        return _to_response(
            existing_archived,
            latest=latest_map.get(existing_archived.id),
            observation_count=counts.get(existing_archived.id, 0),
        )

    # Phase 4.6: cap is total across all of the user's businesses (not
    # per-business). Join through Business so a user can't sidestep the
    # cap by spreading competitors across each of their businesses.
    current_count = (
        db.query(Competitor)
        .join(Business, Competitor.business_id == Business.id)
        .filter(
            Business.user_id == user.id,
            Business.archived_at.is_(None),
            Competitor.archived_at.is_(None),
        )
        .count()
    )
    if current_count >= limit:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "competitor_limit_reached",
                "message": f"Your plan allows up to {limit} competitors total. Remove one to add another.",
                "tier": user.plan.value,
                "limit": limit,
                "competitor_count": current_count,
            },
        )

    name = (payload.name or "").strip() or "Competitor"
    instagram_url = (payload.instagram_url or "").strip() or None
    website_url = (payload.website_url or "").strip() or None
    competitor = Competitor(
        business_id=business.id,
        name=name,
        maps_url=maps_url,
        instagram_url=instagram_url,
        website_url=website_url,
    )
    db.add(competitor)
    db.commit()
    db.refresh(competitor)
    _kick_first_refresh(competitor.maps_url)
    return _to_response(competitor, latest=None, observation_count=0)


@router.get(
    "/businesses/{business_id}/trends",
    response_model=BusinessTrendsResponse,
)
def get_business_trends(
    business_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> BusinessTrendsResponse:
    """Time-series rating + review_count for the chart on the business page.

    Returns two parallel histories so the frontend can overlay them on a
    single chart: the user's own business (pulled from each completed
    audit's Maps section ``raw_data_json``) and one series per active
    competitor (pulled from ``competitor_observations``).
    """
    _own_business_or_404(db, user, business_id)

    audits: list[Audit] = (
        db.query(Audit)
        .filter(
            Audit.business_id == business_id,
            Audit.status == AuditStatus.done,
        )
        .order_by(Audit.finished_at, Audit.id)
        .all()
    )
    audit_ids = [a.id for a in audits]

    maps_sections: dict[int, AuditSection] = {}
    if audit_ids:
        rows: list[AuditSection] = (
            db.query(AuditSection)
            .filter(
                AuditSection.audit_id.in_(audit_ids),
                AuditSection.section == AuditSectionName.maps,
            )
            .all()
        )
        for row in rows:
            maps_sections[row.audit_id] = row

    business_points: list[TrendPoint] = []
    for audit in audits:
        maps = maps_sections.get(audit.id)
        raw = (maps.raw_data_json or {}) if maps else {}
        rating = raw.get("rating") if isinstance(raw, dict) else None
        review_count = raw.get("review_count") if isinstance(raw, dict) else None
        ig_followers = (
            raw.get("instagram_followers") if isinstance(raw, dict) else None
        )
        ig_posts = raw.get("instagram_posts") if isinstance(raw, dict) else None
        if (
            rating is None
            and review_count is None
            and ig_followers is None
            and ig_posts is None
        ):
            # Skip audits that couldn't read Maps at all — plotting all-null
            # would just be a phantom point with no signal.
            continue
        business_points.append(
            TrendPoint(
                audit_id=audit.id,
                observed_at=audit.finished_at or audit.started_at,
                rating=float(rating) if rating is not None else None,
                review_count=int(review_count) if review_count is not None else None,
                instagram_followers=int(ig_followers) if ig_followers is not None else None,
                instagram_posts=int(ig_posts) if ig_posts is not None else None,
                visibility_score=visibility_service.compute(
                    rating=float(rating) if rating is not None else None,
                    review_count=int(review_count) if review_count is not None else None,
                    instagram_followers=int(ig_followers) if ig_followers is not None else None,
                ),
            )
        )

    competitors: list[Competitor] = (
        db.query(Competitor)
        .filter(
            Competitor.business_id == business_id,
            Competitor.archived_at.is_(None),
        )
        .order_by(Competitor.added_at, Competitor.id)
        .all()
    )

    competitor_trends: list[CompetitorTrend] = []
    if competitors:
        comp_ids = [c.id for c in competitors]
        obs_rows: list[CompetitorObservation] = (
            db.query(CompetitorObservation)
            .filter(CompetitorObservation.competitor_id.in_(comp_ids))
            .order_by(CompetitorObservation.observed_at, CompetitorObservation.id)
            .all()
        )
        by_comp: dict[int, list[CompetitorObservation]] = {}
        for row in obs_rows:
            by_comp.setdefault(row.competitor_id, []).append(row)
        for comp in competitors:
            comp_obs = by_comp.get(comp.id, [])
            competitor_trends.append(
                CompetitorTrend(
                    competitor_id=comp.id,
                    name=comp.name,
                    observations=[
                        TrendPoint(
                            audit_id=o.audit_id,
                            observed_at=o.observed_at,
                            rating=o.rating,
                            review_count=o.review_count,
                            instagram_followers=o.instagram_followers,
                            instagram_posts=o.instagram_posts,
                            visibility_score=visibility_service.compute(
                                rating=o.rating,
                                review_count=o.review_count,
                                instagram_followers=o.instagram_followers,
                            ),
                        )
                        for o in comp_obs
                    ],
                )
            )

    return BusinessTrendsResponse(
        business=business_points,
        competitors=competitor_trends,
    )


@router.delete(
    "/businesses/{business_id}/competitors/{competitor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def archive_competitor(
    business_id: int,
    competitor_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    _own_business_or_404(db, user, business_id)
    competitor = (
        db.query(Competitor)
        .filter(
            Competitor.id == competitor_id,
            Competitor.business_id == business_id,
            Competitor.archived_at.is_(None),
        )
        .one_or_none()
    )
    if competitor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="competitor not found",
        )
    competitor.archived_at = datetime.now(timezone.utc)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/businesses/{business_id}/competitor-insights",
    response_model=HubInsightsResponse,
)
def get_competitor_insights(
    business_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> HubInsightsResponse:
    """Hub insight cards for one business (top winning factor + opportunity).

    The deterministic math in ``services.competitor_insights`` decides which
    cards (if any) are honest; the LLM is only a phrasing layer. Empty
    ``cards`` means there isn't enough comparable data yet, not an error.
    """
    _own_business_or_404(db, user, business_id)
    cards = insights_service.build_hub_insights(db, user, business_id)
    return HubInsightsResponse(
        business_id=business_id,
        cards=[
            InsightCardResponse(
                headline=c.headline,
                sentence=c.sentence,
                fact=InsightFactResponse(
                    kind=c.fact.kind,
                    metric=c.fact.metric,
                    user_value=c.fact.user_value,
                    competitor_average=c.fact.competitor_average,
                    competitor_sample_size=c.fact.competitor_sample_size,
                    delta=c.fact.delta,
                ),
            )
            for c in cards
        ],
    )
