"""RQ queue + connection factory for audit jobs.

Centralized so every caller (the API endpoint, future cron, tests) goes
through the same factory and gets the same queue name, connection, and
job-timeout policy. Uses the sync ``redis`` client because RQ is sync.
The async client used by ``audit_events`` talks to the same Redis server
so events publish-ordered correctly across both clients.
"""
import json
import logging
from datetime import datetime, timezone

from redis import Redis
from rq import Queue
from rq.job import Job

from app.config import settings

logger = logging.getLogger(__name__)

# Selenium audits should never legitimately take 10 minutes. Anything
# longer means Chrome hung or a scraper is stuck — let RQ kill it.
_JOB_TIMEOUT_SECONDS = 600

# Match audit_events.py — same stream key + same MAXLEN policy. If those
# constants ever drift here vs. there, replays will silently break.
_STREAM_MAXLEN = 1000

# Match audit_events.py too — terminal events set this TTL on the stream
# key so completed audits don't accumulate forever in Redis.
_STREAM_TTL_SECONDS = 24 * 60 * 60


redis_conn = Redis.from_url(settings.redis_url)
audit_queue = Queue("audits", connection=redis_conn)

# Phase 4 — low-priority queue for heavy competitor work (cache refreshes
# and Discovery Scans). Routed to a dedicated worker process so a half-hour
# Selenium discovery run can't starve a user's live self-audit. See
# ``scripts/run_competitor_worker.py``.
competitor_queue = Queue("competitor_jobs", connection=redis_conn)

# Cache refreshes are short (one Maps page) but Discovery Scans can run for
# 10+ minutes. The latter sets the ceiling.
_COMPETITOR_REFRESH_TIMEOUT_SECONDS = 180
_DISCOVERY_SCAN_TIMEOUT_SECONDS = 60 * 30


def _ensure_stream_exists(audit_id: int) -> None:
    """XADD a placeholder so the audit's Redis Stream key exists before
    the job is enqueued.

    A fast SSE client can connect to ``/audits/{id}/stream`` the
    millisecond after ``POST /api/audits`` returns. XREAD on a missing
    key just blocks (it doesn't 404), but we still want a deterministic
    "stream is live" marker on the bus before any worker touches it.
    Subscribers ignore the ``audit_queued`` type — the frontend only
    listens for ``audit_started`` and the section/terminal events.
    """
    redis_conn.xadd(
        f"audit:{audit_id}:events",
        {"data": json.dumps({"type": "audit_queued", "audit_id": audit_id})},
        maxlen=_STREAM_MAXLEN,
        approximate=True,
    )


def on_audit_job_failure(job, connection, exc_type, exc_value, traceback) -> None:
    """RQ ``on_failure`` callback — runs after a job fails for any reason.

    The runner's own try/except handles Python-level exceptions and writes
    ``audits.status=failed`` + publishes ``audit_failed`` before re-raising.
    But it can't catch signal-level deaths (Selenium-Chrome SIGSEGV, OOM
    kills, container restarts mid-run) — those kill the worker process
    before any Python code runs. RQ still notices the dead job and invokes
    this callback, so this is the last line of defence: it makes sure the
    DB row never gets stuck at ``running`` and the live SSE screen always
    sees a terminal event.

    Idempotent against the in-process handler: if the runner already
    marked the audit ``done`` or ``failed``, we don't touch it.
    """
    audit_id = job.args[0] if job.args else None
    if audit_id is None:
        return

    # Local imports — RQ workers shouldn't pay the DB/model import cost
    # at module load time, only when a job actually fails.
    from app.db import SessionLocal
    from app.models import Audit
    from app.models.enums import AuditStatus

    error_text = repr(exc_value) if exc_value else "Worker crashed unexpectedly"

    try:
        db = SessionLocal()
        try:
            audit = db.get(Audit, audit_id)
            if audit and audit.status not in (AuditStatus.done, AuditStatus.failed):
                audit.status = AuditStatus.failed
                audit.error_message = error_text
                audit.finished_at = datetime.now(timezone.utc)
                db.commit()
        finally:
            db.close()
    except Exception:
        logger.exception("on_audit_job_failure: DB update failed for audit_id=%s", audit_id)

    stream_key = f"audit:{audit_id}:events"
    payload = json.dumps(
        {"type": "audit_failed", "error": error_text, "audit_id": audit_id}
    )
    try:
        connection.xadd(
            stream_key,
            {"data": payload},
            maxlen=_STREAM_MAXLEN,
            approximate=True,
        )
        connection.expire(stream_key, _STREAM_TTL_SECONDS)
    except Exception:
        logger.exception("on_audit_job_failure: stream publish failed for audit_id=%s", audit_id)


def enqueue_audit(audit_id: int) -> Job:
    """Enqueue an audit job and return the RQ ``Job`` handle.

    Guarantees the SSE stream key exists before the job is visible to
    workers, so callers don't need to remember the ordering.
    """
    _ensure_stream_exists(audit_id)
    return audit_queue.enqueue(
        "app.workers.audit_jobs.run_audit_job",
        audit_id,
        job_timeout=_JOB_TIMEOUT_SECONDS,
        on_failure=on_audit_job_failure,
    )


def enqueue_competitor_refresh(cache_key: str, maps_url: str) -> Job:
    """Enqueue a background cache refresh for one competitor URL.

    Driven by the daily cron in ``services.competitor_refresh``. Idempotent
    against duplicate cache_keys *within a single dispatch tick* (the
    dispatcher dedupes); RQ itself doesn't suppress structurally-identical
    jobs, so two ticks scheduled within a refresh window can technically
    enqueue twice. That's harmless — the second run just overwrites the
    cache row with a fresher value.
    """
    return competitor_queue.enqueue(
        "app.workers.competitor_jobs.refresh_cache_job",
        cache_key,
        maps_url,
        job_timeout=_COMPETITOR_REFRESH_TIMEOUT_SECONDS,
    )


def enqueue_discovery_scan(scan_id: int) -> Job:
    """Enqueue a user-initiated Discovery Scan.

    ``at_front=True`` so a paid user who just clicked "Scan" doesn't sit
    behind a backlog of cron-driven refresh jobs. Discovery Scans are
    explicitly user-triggered and (per ``services.discovery_scan``) capped
    to one per calendar month, so jumping the queue can't be abused into a
    denial-of-service on routine refreshes.
    """
    return competitor_queue.enqueue(
        "app.workers.competitor_jobs.discovery_scan_job",
        scan_id,
        job_timeout=_DISCOVERY_SCAN_TIMEOUT_SECONDS,
        at_front=True,
    )
