"""Operational health signals shared by ``/api/health`` and the admin panel.

Two things the plain DB-ping health check can't tell you:
  * **queue depth** — is the single worker keeping up, or is a backlog growing?
  * **scheduler heartbeat** — did the hourly auto-audit dispatcher actually run
    recently, or is the cron silently dead?

Both are read from the same Redis the workers + scheduler use. Everything
degrades softly: a Redis hiccup yields ``None`` for the affected field instead
of raising, so a health probe never 500s on a transient blip.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.workers.queue import audit_queue, competitor_queue, redis_conn

# Redis key the auto-audit dispatcher stamps every time it runs. Since the
# dispatcher fires hourly (scripts.run_scheduler), a value older than a couple
# of hours means the cron→queue→worker path has gone dead — which is exactly
# the failure a solo operator otherwise never notices.
_LAST_DISPATCH_KEY = "ops:scheduler:last_dispatch_at"

# The dispatcher runs at the top of every hour; 2h of silence is comfortably
# past "we missed a tick" and into "something is broken", without flapping
# around the hour boundary.
_DISPATCH_STALE_AFTER_SECONDS = 2 * 60 * 60


def record_dispatch_beat() -> None:
    """Stamp 'the auto-audit dispatcher just ran'. Best-effort by design —
    a Redis failure here must never break an actual dispatch, so we swallow."""
    try:
        redis_conn.set(_LAST_DISPATCH_KEY, datetime.now(timezone.utc).isoformat())
    except Exception:
        pass


def _last_dispatch_iso() -> str | None:
    try:
        raw = redis_conn.get(_LAST_DISPATCH_KEY)
    except Exception:
        return None
    if raw is None:
        return None
    return raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)


def queue_depths() -> dict:
    """Job counts per queue. ``None`` per field if Redis is unreachable."""
    try:
        return {"audits": audit_queue.count, "competitors": competitor_queue.count}
    except Exception:
        return {"audits": None, "competitors": None}


def scheduler_status() -> dict:
    """Last-dispatch timestamp + a glanceable ``stale`` flag.

    ``stale`` is ``None`` (unknown) when no beat has been recorded yet — e.g.
    a freshly-started process that hasn't reached the first top-of-hour — so a
    just-deployed box doesn't look broken. Once a beat exists, ``stale`` is a
    plain bool."""
    iso = _last_dispatch_iso()
    if iso is None:
        return {"last_dispatch_at": None, "last_dispatch_age_seconds": None, "stale": None}
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds()
    except Exception:
        return {"last_dispatch_at": iso, "last_dispatch_age_seconds": None, "stale": None}
    return {
        "last_dispatch_at": iso,
        "last_dispatch_age_seconds": int(age),
        "stale": age > _DISPATCH_STALE_AFTER_SECONDS,
    }
