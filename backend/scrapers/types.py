from dataclasses import dataclass, field
from typing import Any


@dataclass
class BusinessInput:
    name: str
    city: str
    country: str
    maps_url: str | None = None
    website: str | None = None
    ig_handle: str | None = None


@dataclass
class RecommendationDraft:
    severity: str
    title: str
    body_markdown: str
    estimated_impact: str | None = None
    estimated_time: str | None = None


@dataclass
class SectionResult:
    score: int
    status: str
    raw_data: dict[str, Any]
    recommendations: list[RecommendationDraft] = field(default_factory=list)
