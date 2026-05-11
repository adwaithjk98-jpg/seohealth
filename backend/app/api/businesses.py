from fastapi import APIRouter, Depends, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.auth_deps import current_user
from app.db import get_db
from app.models import Business, User
from app.schemas.business import BusinessCreateRequest, BusinessResponse

router = APIRouter()


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

    business = Business(
        user_id=user.id,
        name=name,
        city=city,
        country=payload.country.strip() or "India",
        maps_url=(payload.maps_url or None) and payload.maps_url.strip(),
        website=website,
        ig_handle=ig_handle,
    )
    db.add(business)
    db.commit()
    db.refresh(business)

    return BusinessResponse(
        id=business.id,
        name=business.name,
        city=business.city,
        country=business.country,
        maps_url=business.maps_url,
        website=business.website,
        ig_handle=business.ig_handle,
        added_at=business.added_at,
    )


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
    return [
        BusinessResponse(
            id=b.id,
            name=b.name,
            city=b.city,
            country=b.country,
            maps_url=b.maps_url,
            website=b.website,
            ig_handle=b.ig_handle,
            added_at=b.added_at,
        )
        for b in rows
    ]
