"""RQ queue + connection factory for audit jobs.

Centralized so every caller (the API endpoint, future cron, tests) goes
through the same factory and gets the same queue name, connection, and
job-timeout policy. Uses the sync ``redis`` client because RQ is sync.
The async client used by ``audit_events`` talks to the same Redis server
so events publish-ordered correctly across both clients.
"""
import json

from redis import Redis
from rq import Queue
from rq.job import Job

from app.config import settings

# Selenium audits should never legitimately take 10 minutes. Anything
# longer means Chrome hung or a scraper is stuck — let RQ kill it.
_JOB_TIMEOUT_SECONDS = 600

# Match audit_events.py — same stream key + same MAXLEN policy. If those
# constants ever drift here vs. there, replays will silently break.
_STREAM_MAXLEN = 1000


redis_conn = Redis.from_url(settings.redis_url)
audit_queue = Queue("audits", connection=redis_conn)


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
    )
