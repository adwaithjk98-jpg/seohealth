"""Discovery Scan request + result history (Phase 4 — heavy bulk discovery).

One row per user-initiated Discovery Scan. Doubles as:

* the **rate-limit ledger** for ``services.discovery_scan`` (monthly cap is
  enforced by counting rows in the current calendar month);
* the **job state record** the RQ worker updates as it runs the scrape
  (``pending`` → ``running`` → ``done`` / ``failed``);
* the **result store** for the GET endpoint that the frontend polls once
  the worker writes ``results_json``.

We persist every attempt, but the rate limiter (``services.discovery_scan.
count_scans_this_month``) counts only ``pending`` / ``running`` / ``done`` rows
— a 10-second double-click still can't beat the cap (the pending row counts),
while a ``failed`` scan (post-Places-migration ≈ our infra fell over, not the
user's fault) is refunded rather than burning the user's one monthly slot.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import DiscoveryScanStatus


class DiscoveryScan(Base):
    __tablename__ = "discovery_scans"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Nullable because Discovery Scans can be triggered against a "I'm
    # researching a new market" query that isn't tied to one of the user's
    # existing businesses. When set, the UI can render results next to the
    # business that prompted the scan.
    business_id: Mapped[int | None] = mapped_column(
        ForeignKey("businesses.id", ondelete="SET NULL"), nullable=True
    )
    query: Mapped[str] = mapped_column(String(512), nullable=False)
    num_leads: Mapped[int] = mapped_column(Integer, nullable=False)
    # CSV of fields the scraper should populate per result. CSV (not JSON
    # array) so it survives unchanged when we pass it back to the scraper
    # subprocess, whose CLI takes a comma-joined string.
    fields_csv: Mapped[str] = mapped_column(String(1024), nullable=False)
    filters: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[DiscoveryScanStatus] = mapped_column(
        Enum(DiscoveryScanStatus, name="discovery_scan_status"),
        nullable=False,
        default=DiscoveryScanStatus.pending,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    result_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    results_json: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
