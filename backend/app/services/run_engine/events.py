"""In-memory event bus for live Run streaming.

Runtime components (sequential walker, DAG walker, future skill wrappers)
publish small structured events keyed by ``run_id``. HTTP consumers
(``GET /runs/{id}/stream`` SSE) subscribe to the same key and receive the
events in arrival order through an :class:`asyncio.Queue`.

Design goals
------------
* Single-process only — this is an in-memory bus, not Redis / NATS. A
  multi-worker deployment needs a broker swap (mark in the bus API so a
  future backend can drop in without touching callers).
* Never blocks the walker — :meth:`publish` is synchronous and uses
  ``put_nowait`` so the DAG engine can emit events without ``await``.
* Safe for short replay-then-live streams — subscribers iterate until the
  bus closes the run or the HTTP client disconnects.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from app.core.logging import get_logger

logger = get_logger(__name__)


class _RunChannel:
    """One fan-out channel per ``run_id`` — holds every live subscriber queue."""

    __slots__ = ("subscribers", "closed")

    def __init__(self) -> None:
        self.subscribers: List[asyncio.Queue[Dict[str, Any]]] = []
        self.closed: bool = False


class RunSubscription:
    """Handle on a single subscriber queue.

    Use :meth:`next_event` to pull the next event (or ``None`` on close)
    and :meth:`aclose` to unregister the queue from the bus.
    """

    __slots__ = ("_bus", "_run_id", "_queue", "_closed")

    def __init__(self, bus: "RunEventBus", run_id: str, queue: asyncio.Queue) -> None:
        self._bus = bus
        self._run_id = run_id
        self._queue = queue
        self._closed = False

    async def next_event(self) -> Optional[Dict[str, Any]]:
        if self._closed:
            return None
        event = await self._queue.get()
        if event.get("__sentinel__"):
            self._closed = True
            return None
        return event

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._bus._unregister(self._run_id, self._queue)


class RunEventBus:
    """Fan-out bus keyed by ``run_id``.

    Subscribers are independent — each gets its own unbounded queue so a
    slow SSE client can't back-pressure the walker. Publishers are
    fire-and-forget.
    """

    _SENTINEL: Dict[str, Any] = {"__sentinel__": True}

    def __init__(self) -> None:
        self._channels: Dict[str, _RunChannel] = {}

    def publish(self, run_id: str, event: Dict[str, Any]) -> None:
        """Non-blocking publish. No-op when nobody is listening."""
        channel = self._channels.get(run_id)
        if not channel or channel.closed:
            return
        for q in list(channel.subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "run_event_bus: subscriber queue full, dropping", run_id=run_id
                )

    def close(self, run_id: str) -> None:
        """Signal to every subscriber that no more events will arrive.

        Each subscriber's iterator ends naturally after draining the
        remaining events in its queue.

        If the channel doesn't exist yet (walker finished before any
        HTTP consumer connected), we still materialise it in a closed
        state so any *late* subscriber resolves immediately on its
        first ``next_event`` instead of hanging on an empty queue.
        Without this, there's a tight race where ``close()`` looks like
        a no-op and the subsequent ``subscribe()`` creates a fresh
        open channel that never gets a sentinel.
        """
        channel = self._channels.get(run_id)
        if channel is None:
            channel = _RunChannel()
            channel.closed = True
            self._channels[run_id] = channel
            return
        if channel.closed:
            return
        channel.closed = True
        for q in list(channel.subscribers):
            try:
                q.put_nowait(self._SENTINEL)
            except asyncio.QueueFull:
                pass

    def subscribe(self, run_id: str) -> RunSubscription:
        """Register a new subscriber and return its handle.

        Synchronous on purpose — the caller must invoke it before any
        ``await`` that could yield control to the publishing coroutine,
        so no events are missed between the subscribe and the first
        ``next_event`` call.
        """
        channel = self._channels.setdefault(run_id, _RunChannel())
        q: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        if channel.closed:
            # Already closed: queue the sentinel immediately so the
            # subscriber resolves on first next_event and tears down.
            q.put_nowait(self._SENTINEL)
        channel.subscribers.append(q)
        return RunSubscription(self, run_id, q)

    def _unregister(self, run_id: str, queue: asyncio.Queue) -> None:
        channel = self._channels.get(run_id)
        if not channel:
            return
        if queue in channel.subscribers:
            channel.subscribers.remove(queue)
        if not channel.subscribers and channel.closed:
            self._channels.pop(run_id, None)

    def is_live(self, run_id: str) -> bool:
        """Return ``True`` when the channel exists and is not closed."""
        channel = self._channels.get(run_id)
        return bool(channel and not channel.closed)


# Process-wide singleton — imported by both the run engine and the SSE
# endpoint. Swap this module behind a Redis pub/sub facade when we move
# to multi-worker deployment.
bus = RunEventBus()
