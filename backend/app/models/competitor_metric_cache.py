"""Global cross-user cache for competitor Maps metrics (Phase 4 cost defense).

Two unrelated users tracking the same place ("Bakehouse Cafe") would otherwise
hit Selenium for the same Maps URL once per audit. This table holds one row per
distinct (normalized) ``maps_url`` with the last-known rating + review_count
and a ``last_scraped_at`` timestamp. ``services.competitor_cache`` reads it on
the way in and writes back on the way out.

Lifetime: rows live forever; staleness is decided per-read against the TTL in
``services.competitor_cache.CACHE_TTL_DAYS``.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CompetitorMetricCache(Base):
    __tablename__ = "competitor_metric_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Normalized form of the Maps URL — see ``competitor_cache.normalize_maps_url``.
    # Unique so a UPSERT can collapse concurrent scrapes of the same place.
    cache_key: Mapped[str] = mapped_column(
        String(1024), nullable=False, unique=True, index=True
    )
    maps_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_scraped_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
