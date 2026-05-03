from fastapi import FastAPI

from app.api.audits import router as audits_router
from app.api.auth import router as auth_router
from app.api.businesses import router as businesses_router
from app.api.health import router as health_router
from app.api.recommendations import router as recommendations_router

app = FastAPI(title="AuditHealth API", version="0.1.0")

app.include_router(health_router, prefix="/api", tags=["health"])
app.include_router(auth_router, prefix="/api", tags=["auth"])
app.include_router(businesses_router, prefix="/api", tags=["businesses"])
app.include_router(audits_router, prefix="/api", tags=["audits"])
app.include_router(recommendations_router, prefix="/api", tags=["recommendations"])
