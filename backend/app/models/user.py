from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, String, func, text

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import UserPlan

if TYPE_CHECKING:
    from app.models.business import Business
    from app.models.push_subscription import PushSubscription
    from app.models.session import Session
    from app.models.subscription import Subscription


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    # Friendly greeting label. NULL until the user fills it in via the
    # FTUE questionnaire; the dashboard falls back to the email-prefix.
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Optional contact number, collected at signup (one nullable field). This
    # is the pre-beta foundation for S1 (WhatsApp-first weekly recaps): the
    # channel needs a number on file before the feature ships. Stored lightly
    # cleaned, as the user typed it — E.164 normalisation is deferred to the
    # WhatsApp send build. NULL until the user provides one.
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    magic_link_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    magic_link_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    plan: Mapped[UserPlan] = mapped_column(
        Enum(UserPlan, name="user_plan"), default=UserPlan.free, nullable=False
    )
    signup_date: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Whether the user receives the weekly digest email. Default on; the
    # account page + the email's unsubscribe link flip it. Dispatch filters on
    # it so opt-out is honored before we ever send to real users.
    weekly_digest_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )

    businesses: Mapped[list["Business"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    sessions: Mapped[list["Session"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    push_subscriptions: Mapped[list["PushSubscription"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
