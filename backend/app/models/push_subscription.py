from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class PushSubscription(Base):
    """A single Web Push endpoint for one of a user's browsers/devices.

    One row per browser ``PushSubscription``. The *presence* of any row for a
    user is the "push enabled" state — there's no separate boolean on the user.
    Endpoints are globally unique (the push service issues one per
    subscription), so a re-subscribe upserts onto the existing row. Endpoints
    the push service reports as gone (HTTP 404/410) are pruned by the sender.
    """

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # The push service endpoint URL. FCM / Mozilla endpoints run long, so give
    # it room; unique so a device's re-subscribe updates in place.
    endpoint: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    # Encryption material from the browser ``PushSubscription.keys``.
    p256dh: Mapped[str] = mapped_column(String(255), nullable=False)
    auth: Mapped[str] = mapped_column(String(255), nullable=False)
    # Best-effort device label for debugging / a future "manage devices" view.
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="push_subscriptions")
