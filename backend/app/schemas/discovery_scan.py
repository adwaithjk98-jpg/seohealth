from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DiscoveryScanCreateRequest(BaseModel):
    """Body for ``POST /api/discovery-scans``.

    All fields except ``query`` have sensible defaults so the smallest
    possible payload (`{"query": "cafes in Kochi"}`) succeeds. ``fields``
    is passed through to the audit_scraper subprocess verbatim — the
    engine accepts any column it knows how to populate.
    """

    query: str = Field(min_length=1, max_length=512)
    num_leads: int = Field(default=20, ge=1, le=100)
    fields: list[str] = Field(default_factory=lambda: ["name", "rating", "phone"])
    filters: str | None = Field(default=None, max_length=1024)
    business_id: int | None = None


class DiscoveryScanResponse(BaseModel):
    id: int
    user_id: int
    business_id: int | None
    query: str
    num_leads: int
    fields: list[str]
    filters: str | None
    status: str
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result_count: int | None
    # Populated only once the worker finishes. The frontend should poll
    # ``GET /api/discovery-scans/{id}`` until ``status`` is terminal.
    results: list[dict[str, Any]] | None = None
    error_message: str | None = None
