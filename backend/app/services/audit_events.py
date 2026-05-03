"""In-memory pub/sub for audit progress events.

Each audit gets one AuditStream. The runner publishes events; SSE handlers
subscribe and replay buffered events from the start, then await new ones.
Buffering means a client connecting milliseconds after the audit starts still
sees every event. Streams live for the life of the process.
"""
import asyncio
from collections.abc import AsyncIterator
from typing import Any


class AuditStream:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self._closed = False
        self._cond = asyncio.Condition()

    async def publish(self, event: dict[str, Any]) -> None:
        async with self._cond:
            self.events.append(event)
            self._cond.notify_all()

    async def close(self) -> None:
        async with self._cond:
            self._closed = True
            self._cond.notify_all()

    @property
    def closed(self) -> bool:
        return self._closed

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        idx = 0
        while True:
            async with self._cond:
                while idx >= len(self.events) and not self._closed:
                    await self._cond.wait()
                if idx >= len(self.events) and self._closed:
                    return
                event = self.events[idx]
                idx += 1
            yield event


_streams: dict[int, AuditStream] = {}


def get_or_create_stream(audit_id: int) -> AuditStream:
    if audit_id not in _streams:
        _streams[audit_id] = AuditStream()
    return _streams[audit_id]


def get_stream(audit_id: int) -> AuditStream | None:
    return _streams.get(audit_id)
