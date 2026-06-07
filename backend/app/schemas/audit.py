from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AuditCreateRequest(BaseModel):
    business_id: int = Field(..., gt=0)
    trigger: str = Field(default="manual", pattern="^(manual|scheduled)$")


class AuditCreateResponse(BaseModel):
    audit_id: int
    status: str
    stream_url: str
    started_at: datetime


class SubCheckResponse(BaseModel):
    label: str
    status: str  # 'good' | 'warn' | 'bad' | 'info'
    value: str | None = None
    detail: str | None = None


class RecommendationResponse(BaseModel):
    id: int
    section: str
    severity: str
    title: str
    body_markdown: str
    estimated_impact: str | None
    estimated_time: str | None
    fix_status: str
    marked_done_at: datetime | None


class AuditSectionResponse(BaseModel):
    section: str
    label: str
    emoji: str
    tagline: str
    score: int | None
    grade: str
    status: str
    summary: str | None
    raw_data: dict[str, Any] | None
    sub_checks: list[SubCheckResponse]
    previous_score: int | None = None
    trend: str | None = None  # 'up' | 'down' | 'flat' | None
    recommendations: list[RecommendationResponse]


class BusinessSummary(BaseModel):
    id: int
    name: str
    city: str
    country: str


class SinceLastCheckItem(BaseModel):
    title: str
    section: str
    severity: str | None = None
    verify_signal: str | None = None
    was_marked_done: bool | None = None


class SinceLastCheck(BaseModel):
    """Fix-loop summary: what changed since the previous audit. All
    buckets are empty + ``prev_finished_at`` is None when this is the
    first audit for the business."""

    confirmed: list[SinceLastCheckItem] = []
    unverified_done: list[SinceLastCheckItem] = []
    new: list[SinceLastCheckItem] = []
    prev_finished_at: datetime | None = None


class AuditDetailResponse(BaseModel):
    audit_id: int
    business: BusinessSummary
    status: str
    trigger: str
    started_at: datetime
    finished_at: datetime | None
    error_message: str | None = None
    overall_score: int | None
    overall_grade: str
    previous_overall_score: int | None = None
    overall_trend: str | None = None  # 'up' | 'down' | 'flat' | None
    sections: list[AuditSectionResponse]
    open_recommendations_count: int
    done_recommendations_count: int
    since_last_check: SinceLastCheck = SinceLastCheck()


class RecommendationUpdateRequest(BaseModel):
    fix_status: str = Field(..., pattern="^(open|done|dismissed)$")


class AuditQuotaResponse(BaseModel):
    """Manual + scheduled audits the user has started in the rolling 7-day window.

    The frontend Audit tab reads this for the "X of Y this week" counter
    and disables the Run-audit CTA when ``used >= limit``. ``period_end``
    is naive-UTC so the existing ``${iso}Z`` parsing path keeps working.
    """

    used: int
    limit: int
    remaining: int
    period_end: datetime
    tier: str
