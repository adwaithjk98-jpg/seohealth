from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import UserPlan

if TYPE_CHECKING:
    from app.models.business import Business
    from app.models.session import Session
    from app.models.subscription import Subscription


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    magic_link_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    magic_link_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    plan: Mapped[UserPlan] = mapped_column(
        Enum(UserPlan, name="user_plan"), default=UserPlan.free, nullable=False
    )
    signup_date: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    businesses: Mapped[list["Business"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    sessions: Mapped[list["Session"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
