from datetime import datetime

from pydantic import BaseModel, Field


class CompetitorCreateRequest(BaseModel):
    """Body for ``POST /api/businesses/{id}/competitors``.

    ``maps_url`` is required — we identify competitors by their Maps listing,
    not by a (name, city) tuple, because the user is picking a specific
    nearby business to follow. ``name`` is optional; if omitted the scraper
    will fill it on the first observation.
    """

    maps_url: str = Field(min_length=8, max_length=1024)
    name: str | None = Field(default=None, max_length=255)


class CompetitorObservationResponse(BaseModel):
    id: int
    audit_id: int
    rating: float | None
    review_count: int | None
    observed_at: datetime


class CompetitorResponse(BaseModel):
    id: int
    business_id: int
    name: str
    maps_url: str | None
    added_at: datetime
    # The most recent observation surfaced inline so the dashboard can render
    # the current rating + review count without a second round-trip.
    latest_rating: float | None = None
    latest_review_count: int | None = None
    latest_observed_at: datetime | None = None
    observation_count: int = 0


class TrendPoint(BaseModel):
    """One point on the business trend chart.

    ``observed_at`` is the audit's ``finished_at`` for the business series
    and ``observation.observed_at`` for competitors — both naive-UTC so the
    frontend's `${iso}Z` parsing path keeps working unchanged.
    """

    audit_id: int
    observed_at: datetime
    rating: float | None
    review_count: int | None


class CompetitorTrend(BaseModel):
    competitor_id: int
    name: str
    observations: list[TrendPoint]


class BusinessTrendsResponse(BaseModel):
    business: list[TrendPoint]
    competitors: list[CompetitorTrend]
