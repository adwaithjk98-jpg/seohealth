from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class InsightReport(Base):
    """A user-submitted "this insight looks wrong" report.

    We STORE these (not just email them) for two reasons:
    * the founder can spot patterns — the most-reported recommendation type
      is a real quality bug worth fixing, not noise;
    * context (which audit, which rec, the reason) is captured automatically
      so a fix can happen without going back to the user.

    Recommendation rows cascade-delete with their audit when pruned, so the
    FK is ``SET NULL`` and the rec's identifying fields (title, section) are
    denormalized here — a report stays self-describing after the underlying
    recommendation is gone.
    """

    __tablename__ = "insight_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    business_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audit_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recommendation_id: Mapped[int | None] = mapped_column(
        ForeignKey("recommendations.id", ondelete="SET NULL"), nullable=True
    )
    # Denormalized so the report is self-describing after the rec is pruned.
    section: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rec_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # One of: incorrect | outdated | not_applicable | other (validated at the API).
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Founder triage flag — flips true once the report has been looked at.
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship()
