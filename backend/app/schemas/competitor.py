from datetime import datetime

from pydantic import BaseModel, Field


class CompetitorCreateRequest(BaseModel):
    """Body for ``POST /api/businesses/{id}/competitors``.

    ``maps_url`` is required — we identify competitors by their Maps listing,
    not by a (name, city) tuple, because the user is picking a specific
    nearby business to follow. ``name`` is optional; if omitted the scraper
    will fill it on the first observation.

    ``instagram_url`` and ``website_url`` are optional pre-seeds for the
    manual-add modal — they let the audit-side scraper skip the
    Maps-listing → social-link extraction on the first observation.
    """

    maps_url: str = Field(min_length=8, max_length=1024)
    name: str | None = Field(default=None, max_length=255)
    instagram_url: str | None = Field(default=None, max_length=1024)
    website_url: str | None = Field(default=None, max_length=1024)


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
    instagram_url: str | None = None
    website_url: str | None = None
    added_at: datetime
    # The most recent observation surfaced inline so the dashboard can render
    # the current rating + review count without a second round-trip.
    latest_rating: float | None = None
    latest_review_count: int | None = None
    latest_instagram_followers: int | None = None
    latest_instagram_posts: int | None = None
    latest_observed_at: datetime | None = None
    observation_count: int = 0


class TrendPoint(BaseModel):
    """One point on the business trend chart.

    ``observed_at`` is the audit's ``finished_at`` for the business series
    and ``observation.observed_at`` for competitors — both naive-UTC so the
    frontend's `${iso}Z` parsing path keeps working unchanged.

    Instagram metrics are nullable per side: the user-side series sources
    them from the Maps audit section's ``raw_data_json``; the competitor
    side reads them from ``CompetitorObservation`` columns. Either may be
    absent for a given point — the chart skips null values.
    """

    audit_id: int
    observed_at: datetime
    rating: float | None
    review_count: int | None
    instagram_followers: int | None = None
    instagram_posts: int | None = None


class CompetitorTrend(BaseModel):
    competitor_id: int
    name: str
    observations: list[TrendPoint]


class BusinessTrendsResponse(BaseModel):
    business: list[TrendPoint]
    competitors: list[CompetitorTrend]


class InsightFactResponse(BaseModel):
    """Structured fact used by the Hub's Insight Cards.

    The fact is the source of truth — ``sentence`` is just an LLM (or
    fallback) phrasing of the same numbers. Clients should prefer
    ``sentence`` for display but can use the raw fields for badges/tooltips.
    """

    kind: str  # "winning" | "opportunity"
    metric: str  # "rating" | "review_count"
    user_value: float
    competitor_average: float
    competitor_sample_size: int
    delta: float


class InsightCardResponse(BaseModel):
    headline: str
    sentence: str
    fact: InsightFactResponse


class HubInsightsResponse(BaseModel):
    business_id: int
    cards: list[InsightCardResponse]
