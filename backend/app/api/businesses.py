from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Business, User
from app.schemas.business import BusinessCreateRequest, BusinessResponse

router = APIRouter()

# Stand-in until magic-link auth lands. Every business created via the public
# form is attached to this single shared user; swap to the authenticated user
# when auth is wired up (see AuditAppPlan.md §5).
_DEMO_USER_EMAIL = "demo@example.com"


def _get_or_create_demo_user(db: Session) -> User:
    user = db.query(User).filter_by(email=_DEMO_USER_EMAIL).one_or_none()
    if user is None:
        user = User(email=_DEMO_USER_EMAIL)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


@router.post(
    "/businesses",
    response_model=BusinessResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_business(
    payload: BusinessCreateRequest,
    db: Session = Depends(get_db),
) -> BusinessResponse:
    user = _get_or_create_demo_user(db)

    name = (payload.name or "").strip() or "My business"
    city = (payload.city or "").strip() or "Unknown"

    business = Business(
        user_id=user.id,
        name=name,
        city=city,
        country=payload.country.strip() or "India",
        maps_url=(payload.maps_url or None) and payload.maps_url.strip(),
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
        added_at=business.added_at,
    )
