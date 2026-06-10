import sentry_sdk
from fastapi import FastAPI
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from app.config import settings
from app.ratelimit import limiter
from app.api.admin import router as admin_router
from app.api.audits import router as audits_router
from app.api.auth import router as auth_router
from app.api.businesses import router as businesses_router
from app.api.competitors import router as competitors_router
from app.api.discovery_scan import router as discovery_scan_router
from app.api.health import router as health_router
from app.api.recommendations import router as recommendations_router
from app.api.subscriptions import router as subscriptions_router

# Error monitoring. No-op until SENTRY_DSN is set (dev default is empty), so
# this is safe to leave wired in every environment.
if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        environment=settings.app_env,
    )

app = FastAPI(title="AuditHealth API", version="0.1.0")

# Rate limiting (slowapi). The limiter is attached to app state and a handler
# turns over-limit hits into a clean 429 instead of a 500.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(health_router, prefix="/api", tags=["health"])
app.include_router(admin_router, prefix="/api", tags=["admin"])
app.include_router(auth_router, prefix="/api", tags=["auth"])
app.include_router(businesses_router, prefix="/api", tags=["businesses"])
app.include_router(competitors_router, prefix="/api", tags=["competitors"])
app.include_router(audits_router, prefix="/api", tags=["audits"])
app.include_router(recommendations_router, prefix="/api", tags=["recommendations"])
app.include_router(subscriptions_router, prefix="/api", tags=["subscriptions"])
app.include_router(discovery_scan_router, prefix="/api", tags=["discovery-scans"])
