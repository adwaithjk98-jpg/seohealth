from typing import TYPE_CHECKING, Any

from sqlalchemy import Enum, ForeignKey, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import AuditSectionName, AuditSectionStatus

if TYPE_CHECKING:
    from app.models.audit import Audit


class AuditSection(Base):
    __tablename__ = "audit_sections"

    id: Mapped[int] = mapped_column(primary_key=True)
    audit_id: Mapped[int] = mapped_column(
        ForeignKey("audits.id", ondelete="CASCADE"), index=True, nullable=False
    )
    section: Mapped[AuditSectionName] = mapped_column(
        Enum(AuditSectionName, name="audit_section_name"), nullable=False
    )
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[AuditSectionStatus] = mapped_column(
        Enum(AuditSectionStatus, name="audit_section_status"), nullable=False
    )
    raw_data_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    audit: Mapped["Audit"] = relationship(back_populates="sections")
