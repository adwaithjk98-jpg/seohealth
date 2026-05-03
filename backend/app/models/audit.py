from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import AuditStatus, AuditTrigger

if TYPE_CHECKING:
    from app.models.audit_section import AuditSection
    from app.models.business import Business
    from app.models.competitor_observation import CompetitorObservation
    from app.models.recommendation import Recommendation


class Audit(Base):
    __tablename__ = "audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[AuditStatus] = mapped_column(
        Enum(AuditStatus, name="audit_status"),
        default=AuditStatus.pending,
        nullable=False,
    )
    trigger: Mapped[AuditTrigger] = mapped_column(
        Enum(AuditTrigger, name="audit_trigger"),
        default=AuditTrigger.manual,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    business: Mapped["Business"] = relationship(back_populates="audits")
    sections: Mapped[list["AuditSection"]] = relationship(
        back_populates="audit", cascade="all, delete-orphan"
    )
    recommendations: Mapped[list["Recommendation"]] = relationship(
        back_populates="audit", cascade="all, delete-orphan"
    )
    competitor_observations: Mapped[list["CompetitorObservation"]] = relationship(
        back_populates="audit", cascade="all, delete-orphan"
    )
