from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_db
from app.services import ops_health

router = APIRouter()


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    """Liveness + a phone-glanceable ops snapshot.

    The DB ping is the only hard gate (503 if it fails). ``queue_depth`` and
    ``scheduler`` are best-effort signals — they degrade to ``None`` on a Redis
    hiccup rather than failing the probe, so "is the box up?" and "is the cron
    silently dead?" are answerable from one unauthenticated curl.
    """
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"database unavailable: {exc.__class__.__name__}",
        ) from exc
    return {
        "status": "ok",
        "database": "connected",
        "queue_depth": ops_health.queue_depths(),
        "scheduler": ops_health.scheduler_status(),
    }
