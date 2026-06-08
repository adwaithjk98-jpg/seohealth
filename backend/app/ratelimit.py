"""Shared slowapi limiter.

Lives in its own module so route modules can import it for the
``@limiter.limit(...)`` decorator without a circular import back through
``app.main``. In-memory storage is fine for the single-process dev/small-prod
deployment; switch ``storage_uri`` to Redis if we ever run multiple uvicorn
workers behind gunicorn.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings

limiter = Limiter(
    key_func=get_remote_address,
    enabled=settings.rate_limit_enabled,
)
