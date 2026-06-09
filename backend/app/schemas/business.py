from datetime import datetime

from pydantic import BaseModel, Field, model_validator


ALLOWED_BUSINESS_TYPES = frozenset(
    {"cafe", "salon", "retail", "service", "supplier", "other"}
)


class BusinessCreateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=255)
    country: str = Field(default="India", max_length=255)
    maps_url: str | None = Field(default=None, max_length=1024)
    website: str | None = Field(default=None, max_length=1024)
    ig_handle: str | None = Field(default=None, max_length=255)
    # FTUE questionnaire answers. ``None`` is accepted so legacy
    # callers / tests don't break, but the home-page form sends an
    # explicit value for all three.
    business_type: str | None = Field(default=None, max_length=32)
    has_website: bool | None = Field(default=None)
    has_instagram: bool | None = Field(default=None)

    @model_validator(mode="after")
    def must_identify_business(self) -> "BusinessCreateRequest":
        has_name_city = bool(self.name and self.name.strip()) and bool(
            self.city and self.city.strip()
        )
        has_maps_url = bool(self.maps_url and self.maps_url.strip())
        if not has_name_city and not has_maps_url:
            raise ValueError("provide a business name and city, or a Google Maps URL")
        if self.business_type is not None and self.business_type not in ALLOWED_BUSINESS_TYPES:
            raise ValueError(
                f"business_type must be one of {sorted(ALLOWED_BUSINESS_TYPES)} or null"
            )
        return self


class BusinessResponse(BaseModel):
    id: int
    name: str
    city: str
    country: str
    maps_url: str | None
    website: str | None
    ig_handle: str | None
    added_at: datetime
    # Latest-audit summary so the dashboard listing can render a grade chip,
    # trend arrow and an "audit in progress" badge in a single round-trip.
    latest_score: int | None = None
    latest_grade: str | None = None
    latest_trend: str | None = None  # 'up' | 'down' | 'flat' | None
    latest_audit_id: int | None = None
    latest_audit_finished_at: datetime | None = None
    running_audit_id: int | None = None
    # Open recommendations on the latest completed audit. Surfaces on
    # the dashboard "View all insights" card so the user sees a real
    # number worth tapping for, instead of generic copy.
    open_recommendations_count: int = 0
    # Opt-in auto-audit settings. ``audit_schedule_cadence`` is set by the
    # user via PATCH /businesses/{id}/schedule; ``next_auto_audit_at`` is
    # the computed firing time (``null`` when no cadence is set).
    audit_schedule_cadence: str | None = None
    next_auto_audit_at: datetime | None = None
    # FTUE questionnaire answers. ``None`` = "we never asked"; the
    # dashboard surfaces a prompt for these. ``has_website`` /
    # ``has_instagram`` False means the user explicitly opted out of
    # that pillar — the scoring average + pillar grid hide it.
    business_type: str | None = None
    has_website: bool | None = None
    has_instagram: bool | None = None


# Allowed cadence values are intentionally short — they show up in the
# DB as plain strings and the UI maps them to friendly labels.
# "twice-weekly" is valid here (schema-level); whether a given user may pick it
# is gated by tier in the schedule endpoint (Max-only).
ALLOWED_SCHEDULE_CADENCES = frozenset({"twice-weekly", "weekly", "biweekly", "monthly"})


class BusinessProfileUpdateRequest(BaseModel):
    """PATCH /businesses/{id}/profile — FTUE questionnaire writes.

    All fields are optional; only those that are non-``None`` get
    applied. To clear a field, the caller still has to pass the
    explicit ``None`` plus a sentinel (we don't support that today,
    since the FTUE flow only ever sets values forward).
    """

    business_type: str | None = Field(default=None, max_length=32)
    has_website: bool | None = Field(default=None)
    has_instagram: bool | None = Field(default=None)

    @model_validator(mode="after")
    def normalize_business_type(self) -> "BusinessProfileUpdateRequest":
        if self.business_type is not None and self.business_type not in ALLOWED_BUSINESS_TYPES:
            raise ValueError(
                f"business_type must be one of {sorted(ALLOWED_BUSINESS_TYPES)} or null"
            )
        return self


class BusinessScheduleRequest(BaseModel):
    """Payload for PATCH /businesses/{id}/schedule.

    ``cadence=None`` (or empty) clears the schedule (opt-out). Any other
    value must be one of ``ALLOWED_SCHEDULE_CADENCES`` — validated below
    so the dispatcher never has to defend against typos.
    """

    cadence: str | None = Field(default=None)

    @model_validator(mode="after")
    def normalize_cadence(self) -> "BusinessScheduleRequest":
        if self.cadence is None:
            return self
        value = self.cadence.strip().lower() or None
        if value is not None and value not in ALLOWED_SCHEDULE_CADENCES:
            raise ValueError(
                f"cadence must be one of {sorted(ALLOWED_SCHEDULE_CADENCES)} or null"
            )
        self.cadence = value
        return self
