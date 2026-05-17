from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class BusinessCreateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=255)
    country: str = Field(default="India", max_length=255)
    maps_url: str | None = Field(default=None, max_length=1024)
    website: str | None = Field(default=None, max_length=1024)
    ig_handle: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def must_identify_business(self) -> "BusinessCreateRequest":
        has_name_city = bool(self.name and self.name.strip()) and bool(
            self.city and self.city.strip()
        )
        has_maps_url = bool(self.maps_url and self.maps_url.strip())
        if not has_name_city and not has_maps_url:
            raise ValueError("provide a business name and city, or a Google Maps URL")
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
    # Phase 3 — when the auto-audit scheduler will next consider this business.
    # ``null`` for free-tier users (auto-audits are paid-only); the dashboard
    # uses this both to render "Next auto-audit scheduled for …" and to gate
    # the "Upgrade to unlock weekly auto-audits" banner.
    next_auto_audit_at: datetime | None = None
