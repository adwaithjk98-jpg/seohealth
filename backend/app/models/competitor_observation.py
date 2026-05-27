from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.audit import Audit
    from app.models.competitor import Competitor


class CompetitorObservation(Base):
    __tablename__ = "competitor_observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    competitor_id: Mapped[int] = mapped_column(
        ForeignKey("competitors.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Nullable since 2026-05-26 — the weekly ``competitor_refresh`` cron
    # now writes observation rows independent of any user audit (so
    # competitor trend points keep landing even in weeks the user
    # doesn't run an audit). Rows from the legacy in-audit path still
    # carry a real ``audit_id``; cron-written rows carry ``NULL``.
    audit_id: Mapped[int | None] = mapped_column(
        ForeignKey("audits.id", ondelete="CASCADE"), index=True, nullable=True
    )
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Social metrics surfaced by the audit pipeline when the competitor's
    # Maps listing exposes an Instagram link. Both are nullable — they stay
    # ``None`` for competitors without a discoverable IG handle, or until
    # the scraper is wired to extract them.
    instagram_followers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    instagram_posts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    competitor: Mapped["Competitor"] = relationship(back_populates="observations")
    audit: Mapped["Audit"] = relationship(back_populates="competitor_observations")
