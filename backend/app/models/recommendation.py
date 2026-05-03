from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import (
    AuditSectionName,
    RecommendationFixStatus,
    RecommendationSeverity,
)

if TYPE_CHECKING:
    from app.models.audit import Audit


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    audit_id: Mapped[int] = mapped_column(
        ForeignKey("audits.id", ondelete="CASCADE"), index=True, nullable=False
    )
    section: Mapped[AuditSectionName] = mapped_column(
        Enum(AuditSectionName, name="audit_section_name"), nullable=False
    )
    severity: Mapped[RecommendationSeverity] = mapped_column(
        Enum(RecommendationSeverity, name="recommendation_severity"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_impact: Mapped[str | None] = mapped_column(String(64), nullable=True)
    estimated_time: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fix_status: Mapped[RecommendationFixStatus] = mapped_column(
        Enum(RecommendationFixStatus, name="recommendation_fix_status"),
        default=RecommendationFixStatus.open,
        nullable=False,
    )
    marked_done_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    audit: Mapped["Audit"] = relationship(back_populates="recommendations")
