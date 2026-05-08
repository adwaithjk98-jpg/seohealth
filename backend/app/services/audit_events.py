"""Redis-backed pub/sub for audit progress events.

Each audit owns one Redis Stream key (``audit:{audit_id}:events``). The
runner publishes events via XADD; SSE handlers subscribe via XREAD BLOCK
starting from ``0-0``, which replays every prior event before tailing new
ones. Streams give us durability + replay-from-start in one primitive —
exactly the late-subscriber behaviour the previous in-memory buffer
provided, but visible across processes (so a future RQ worker process
and the API process share the same bus).

The ``audit_completed`` / ``audit_failed`` event is the terminal signal.
Subscribers close the iterator after delivering it; the stream key gets
a 24h TTL set on that terminal publish so completed audits don't
accumulate forever in Redis.

Redis is a hard dependency. There is no in-process fallback: if Redis is
down, ``publish`` / ``subscribe`` will raise loudly and the audit will
fail visibly.
"""
import json
from collections.abc import AsyncIterator
from typing import Any

import redis.asyncio as aioredis

from app.config import settings

# Cap each audit's stream so a stuck or runaway audit can't grow unbounded.
# Approximate trimming (`MAXLEN ~ N`) is much cheaper than exact and is fine
# here — the runner emits at most ~3 events per section across ~5 sections.
_STREAM_MAXLEN = 1000

# Once an audit terminates, expire the stream key after this. Long enough
# that a late SSE reconnect or page refresh still sees the full replay,
# short enough that finished audits don't pile up in Redis.
_STREAM_TTL_SECONDS = 24 * 60 * 60

# Block up to this long per XREAD call. The loop just retries on timeout,
# so this only affects shutdown latency for a stuck subscriber.
_XREAD_BLOCK_MS = 30_000

# Event types that signal the audit is done. Publishing one sets the TTL;
# delivering one to a subscriber closes the iterator.
_TERMINAL_EVENT_TYPES = {"audit_completed", "audit_failed"}


_redis_client: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.redis_url, decode_responses=True
        )
    return _redis_client


def _stream_key(audit_id: int) -> str:
    return f"audit:{audit_id}:events"


class AuditStream:
    """Per-audit handle over the Redis-backed event bus.

    Public surface is preserved from the previous in-memory implementation
    so the runner and SSE endpoint don't need to change.
    """

    def __init__(self, audit_id: int) -> None:
        self.audit_id = audit_id
        self.key = _stream_key(audit_id)

    async def publish(self, event: dict[str, Any]) -> None:
        client = _get_redis()
        await client.xadd(
            self.key,
            {"data": json.dumps(event)},
            maxlen=_STREAM_MAXLEN,
            approximate=True,
        )
        if event.get("type") in _TERMINAL_EVENT_TYPES:
            await client.expire(self.key, _STREAM_TTL_SECONDS)

    async def close(self) -> None:
        # No-op for the Redis backend. The terminal event (audit_completed
        # / audit_failed) is what tells subscribers to stop iterating, and
        # the TTL set in publish() is what ages the key out of Redis.
        return

    @property
    def closed(self) -> bool:
        # Kept for parity with the previous in-memory bus's surface.
        return False

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        client = _get_redis()
        last_id = "0-0"  # replay from the start of the stream
        while True:
            response = await client.xread(
                {self.key: last_id}, block=_XREAD_BLOCK_MS
            )
            if not response:
                continue  # block timeout; keep waiting
            for _stream_name, entries in response:
                for entry_id, fields in entries:
                    last_id = entry_id
                    payload = fields.get("data")
                    if payload is None:
                        continue
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    yield event
                    if event.get("type") in _TERMINAL_EVENT_TYPES:
                        return


def get_or_create_stream(audit_id: int) -> AuditStream:
    return AuditStream(audit_id)


def get_stream(audit_id: int) -> AuditStream | None:
    return AuditStream(audit_id)
