from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.business import Business
    from app.models.competitor_observation import CompetitorObservation


class Competitor(Base):
    __tablename__ = "competitors"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    maps_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Manual-add modal lets users pre-seed IG + website so the audit
    # pipeline can skip the Maps-listing → social-link extraction step on
    # the first observation. Both are optional — the scraper still
    # discovers them from the Maps listing when omitted.
    instagram_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Resolved Places API (New) id, backfilled by the competitor refresh job so
    # future refreshes read the exact listing via a cheap Place Details call.
    google_place_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    added_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    business: Mapped["Business"] = relationship(back_populates="competitors")
    observations: Mapped[list["CompetitorObservation"]] = relationship(
        back_populates="competitor", cascade="all, delete-orphan"
    )
