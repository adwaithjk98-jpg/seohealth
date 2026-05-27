from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.audit import Audit
    from app.models.competitor import Competitor
    from app.models.user import User


class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    maps_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    website: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    ig_handle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str] = mapped_column(String(255), nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # User-set auto-audit cadence. ``None`` = no schedule (the default
    # for newly-added businesses as of 2026-05-26 — auto-audits are
    # now opt-in). Allowed values: ``'weekly'``, ``'biweekly'``,
    # ``'monthly'``. Enforced application-side; SQLite/Postgres see a
    # short string. The cron in ``services/auto_audit.py`` only fires
    # for businesses with a cadence set, and each auto-audit consumes
    # one quota slot like a manual audit would.
    audit_schedule_cadence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # FTUE questionnaire answers (added 2026-05-27). All nullable so
    # legacy rows that pre-date the questionnaire can be detected and
    # prompted; the dashboard banner targets businesses where
    # ``business_type IS NULL``. ``has_website`` / ``has_instagram`` are
    # explicit opt-outs that hide the matching pillar from the scoring
    # average and filter pillar-targeted recommendations.
    business_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    has_website: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_instagram: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    user: Mapped["User"] = relationship(back_populates="businesses")
    audits: Mapped[list["Audit"]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )
    competitors: Mapped[list["Competitor"]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )
