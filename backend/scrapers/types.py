from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


# Optional progress callback a scraper can call to narrate sub-phase events
# (e.g. "found_listing", "read_reviews") to the live-analysis stream. The
# runner injects an implementation; passing None turns intermediate events
# into a no-op so scrapers can still be called standalone (tests, debug).
ProgressCb = Callable[[str, dict[str, Any] | None], None] | None


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
    # Which pillar the user would actually *edit* to fix this finding.
    # Usually equals the emitting scraper's section (a Maps finding →
    # ``fix_target='maps'``), but cross-pillar NAP findings can target
    # a specific source: "missing IG handle" → ``fix_target='instagram'``.
    # Lets the read path drop recs whose target is an opted-out pillar.
    fix_target: str | None = None
    # Stable key (e.g. ``website.has_meta_description``) that the
    # fix-loop verifier uses to confirm the underlying signal is
    # positive on a subsequent audit. None for recs we can't auto-
    # verify — those still work, they just don't trigger a
    # "Confirmed fix" moment when the next audit runs.
    verify_signal: str | None = None


@dataclass
class SectionResult:
    score: int
    status: str
    raw_data: dict[str, Any]
    recommendations: list[RecommendationDraft] = field(default_factory=list)
    # Channel for one scraper to hand a discovered value (e.g. website URL,
    # Instagram handle) to a later phase without taking a DB session itself.
    # The runner is responsible for the null-only merge into the Business row.
    discovered_fields: dict[str, str | None] = field(default_factory=dict)
