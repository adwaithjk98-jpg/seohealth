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


class RecommendationUpdateRequest(BaseModel):
    fix_status: str = Field(..., pattern="^(open|done|dismissed)$")
