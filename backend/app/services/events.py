"""In-process pub/sub bus for realtime topology + wireless events.

The web layer is event-driven: mutating endpoints (node/link create, update,
delete; map device placement) *publish* a typed event here, and every connected
``/ws/topology`` socket *subscribes* and relays it to its client. This decouples
the request path from the fan-out path — a POST /nodes returns immediately while
the broadcast happens off the back of an ``asyncio.Queue``.

v0.1 is single-process (one uvicorn worker). The interface is deliberately the
same shape you'd put in front of Redis pub/sub (``infra/redis-design.md``):
``publish(topic, event)`` + an async iterator of events. When we scale to
multiple workers, only :class:`TopologyBus` is swapped for a Redis-backed
implementation — subscribers and publishers are untouched.

Back-pressure: each subscriber has a bounded queue. If a slow client can't keep
up, its *oldest* events are dropped (a fresh snapshot supersedes stale deltas)
rather than blocking the publisher or growing memory without bound.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from functools import lru_cache
from typing import Any, AsyncIterator

logger = logging.getLogger("netforge.events")

# A project_id sentinel meaning "events not scoped to a single project".
GLOBAL = "*"


class _Subscriber:
    """A single connected client's event queue, optionally project-scoped."""

    __slots__ = ("queue", "project_id")

    def __init__(self, project_id: str | None, maxsize: int) -> None:
        self.project_id = project_id
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=maxsize)

    def offer(self, event: dict[str, Any]) -> None:
        """Non-blocking enqueue; drop oldest on overflow so we never block the
        publisher or unbounded-grow memory."""
        if self.queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self.queue.get_nowait()  # evict oldest
        with contextlib.suppress(asyncio.QueueFull):
            self.queue.put_nowait(event)


class TopologyBus:
    """Fan-out hub. Thread-confined to the event loop (no locks needed)."""

    def __init__(self, sub_maxsize: int = 256) -> None:
        self._subs: set[_Subscriber] = set()
        self._sub_maxsize = sub_maxsize

    def publish(self, event: dict[str, Any], project_id: str | None = None) -> None:
        """Fan an event out to all matching subscribers. Safe to call from sync
        request handlers — it never awaits."""
        delivered = 0
        for sub in self._subs:
            if (
                sub.project_id is None
                or project_id is None
                or sub.project_id == project_id
            ):
                sub.offer(event)
                delivered += 1
        if delivered:
            logger.debug("event %s -> %d subs", event.get("type"), delivered)

    @contextlib.asynccontextmanager
    async def subscription(self, project_id: str | None = None):
        """Async context manager yielding an event iterator for one client."""
        sub = _Subscriber(project_id, self._sub_maxsize)
        self._subs.add(sub)
        try:
            yield self._iter(sub)
        finally:
            self._subs.discard(sub)

    async def _iter(self, sub: _Subscriber) -> AsyncIterator[dict[str, Any]]:
        while True:
            yield await sub.queue.get()

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)


@lru_cache(maxsize=1)
def get_bus() -> TopologyBus:
    """Process-wide singleton event bus."""
    return TopologyBus()
