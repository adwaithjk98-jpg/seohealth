"""Sync RQ entrypoint that bridges into the async audit runner.

RQ workers are sync processes. ``audit_runner.run_audit`` is an async
coroutine that already opens its own ``SessionLocal()`` and publishes
``audit_failed`` to the bus before re-raising on error. This wrapper
is the bridge — one ``asyncio.run`` call, then log + re-raise so RQ
marks the job as failed.

Keep this thin. The state machine stays in ``audit_runner.run_audit``.
"""
import asyncio
import logging

from app.services.audit_runner import run_audit

logger = logging.getLogger(__name__)


def run_audit_job(audit_id: int) -> None:
    try:
        asyncio.run(run_audit(audit_id))
    except Exception:
        logger.exception("audit job failed: audit_id=%s", audit_id)
        raise
