"""Discovery Scan endpoints (Phase 4 §3).

Two routes:

  - ``POST   /api/discovery-scans``         — gate + persist + enqueue.
  - ``GET    /api/discovery-scans/{id}``    — fetch one scan's status/results.

Both are paid-tier-only; the POST additionally enforces a monthly quota.
Gating lives in ``services.discovery_scan.assert_can_run`` so a future
``/api/discovery-scans/preview`` (e.g. "what's my next reset date?") can
share the same logic without duplicating the HTTP shape.

The actual scrape runs in the background on the low-priority
``competitor_jobs`` queue. The POST returns the freshly-created row in
``pending`` status; the frontend polls the GET until ``status`` is terminal.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.auth_deps import current_user
from app.db import get_db
from app.models import Business, DiscoveryScan, User
from app.models.enums import DiscoveryScanStatus
from app.schemas.discovery_scan import (
    DiscoveryScanCreateRequest,
    DiscoveryScanResponse,
)
from app.services import discovery_scan as discovery_service
from app.workers.queue import enqueue_discovery_scan

router = APIRouter()


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


@router.post(
    "/discovery-scans",
    response_model=DiscoveryScanResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_discovery_scan(
    payload: DiscoveryScanCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DiscoveryScanResponse:
    """Gate, persist, and enqueue a new Discovery Scan.

    Returns ``202 Accepted`` because the work is asynchronous — the scrape
    happens on the background worker, the response is just the job handle.
    """
    # Validate business ownership *before* the gate, so a free user
    # passing someone else's business_id sees the 404 they expect rather
    # than leaking that the business exists via a 402 response.
    if payload.business_id is not None:
        _own_business_or_404(db, user, payload.business_id)

    discovery_service.assert_can_run(db, user)

    scan = discovery_service.create_scan(
        db,
        user,
        query=payload.query,
        num_leads=payload.num_leads,
        fields=payload.fields,
        filters=payload.filters,
        business_id=payload.business_id,
    )

    try:
        enqueue_discovery_scan(scan.id)
    except Exception:
        # If the enqueue fails (Redis down), the row stays at ``pending``
        # and the rate limiter will still count it. That's intentional:
        # a paid user shouldn't be able to retry indefinitely on infra
        # failures — surface the problem instead. Operators can clean up
        # stranded ``pending`` rows from the dashboard.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="discovery scan queue is currently unavailable",
        )

    return DiscoveryScanResponse(**discovery_service.scan_to_dict(scan))


@router.get(
    "/discovery-scans",
    response_model=list[DiscoveryScanResponse],
)
def list_discovery_scans(
    business_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[DiscoveryScanResponse]:
    """List the caller's prior discovery scans, most recent first.

    Used by the "Add competitors" gateway to decide whether to offer
    revisiting an earlier scan (preferred — zero scraper cost) vs.
    forcing a new one. Optional ``business_id`` filter scopes the
    list to scans anchored to one of the user's businesses.

    Only ``done`` scans are returned. A ``pending`` or ``failed`` row
    has nothing to revisit and would just confuse the gateway.
    """
    q = db.query(DiscoveryScan).filter(
        DiscoveryScan.user_id == user.id,
        DiscoveryScan.status == DiscoveryScanStatus.done,
    )
    if business_id is not None:
        q = q.filter(DiscoveryScan.business_id == business_id)
    rows = q.order_by(desc(DiscoveryScan.finished_at)).limit(20).all()
    return [DiscoveryScanResponse(**discovery_service.scan_to_dict(s)) for s in rows]


@router.get(
    "/discovery-scans/{scan_id}",
    response_model=DiscoveryScanResponse,
)
def get_discovery_scan(
    scan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DiscoveryScanResponse:
    """Fetch one scan owned by the caller. Returns 404 for someone else's row."""
    scan = (
        db.query(DiscoveryScan)
        .filter(DiscoveryScan.id == scan_id, DiscoveryScan.user_id == user.id)
        .one_or_none()
    )
    if scan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="discovery scan not found",
        )
    return DiscoveryScanResponse(**discovery_service.scan_to_dict(scan))
