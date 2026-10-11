"""Unit tests for the in-memory Run event bus.

The bus is a pure-Python coroutine coordination primitive — these tests
cover the three behaviours the SSE endpoint and the DAG walker rely on:

1. A subscriber registered *before* the publisher writes receives every
   event in FIFO order.
2. :meth:`RunEventBus.close` fires the sentinel so subscribers' loops
   terminate cleanly rather than hanging.
3. A subscriber that connects *after* a channel was closed doesn't
   block — it resolves ``None`` on the first pull.
"""
from __future__ import annotations

import asyncio

import pytest

from app.services.run_engine.events import RunEventBus


@pytest.mark.asyncio
async def test_subscriber_receives_events_in_order() -> None:
    bus = RunEventBus()
    sub = bus.subscribe("run-1")

    bus.publish("run-1", {"kind": "run_start"})
    bus.publish("run-1", {"kind": "node_start", "node_id": "n1"})
    bus.publish("run-1", {"kind": "node_end", "node_id": "n1"})
    bus.close("run-1")

    got = []
    while True:
        event = await sub.next_event()
        if event is None:
            break
        got.append(event["kind"])
    assert got == ["run_start", "node_start", "node_end"]
    await sub.aclose()


@pytest.mark.asyncio
async def test_late_subscriber_does_not_see_past_events() -> None:
    # The bus is not a replay log — events published before subscribe
    # are discarded. The SSE endpoint is responsible for replaying
    # persisted checkpoints separately.
    bus = RunEventBus()
    bus.publish("run-2", {"kind": "node_start"})

    sub = bus.subscribe("run-2")
    bus.publish("run-2", {"kind": "node_end"})
    bus.close("run-2")

    seen = []
    while True:
        event = await sub.next_event()
        if event is None:
            break
        seen.append(event["kind"])
    assert seen == ["node_end"]


@pytest.mark.asyncio
async def test_subscribe_after_close_resolves_immediately() -> None:
    bus = RunEventBus()
    bus.close("run-3")  # close a never-opened channel
    # Simulate: a client subscribes but somehow the channel already
    # closed (e.g. the walker finished before the HTTP handler got the
    # lock). We must not hang — next_event returns None right away.
    bus.publish("run-3", {"kind": "ignored"})  # no-op

    # Mimic the "already closed" branch: open a fresh channel, close it,
    # then subscribe.
    bus.publish("run-3-live", {"kind": "ignored"})
    bus.close("run-3-live")
    sub = bus.subscribe("run-3-live")
    event = await asyncio.wait_for(sub.next_event(), timeout=0.5)
    assert event is None


@pytest.mark.asyncio
async def test_multiple_subscribers_fan_out() -> None:
    bus = RunEventBus()
    a = bus.subscribe("run-4")
    b = bus.subscribe("run-4")

    bus.publish("run-4", {"kind": "hello"})
    bus.close("run-4")

    assert (await a.next_event())["kind"] == "hello"
    assert (await b.next_event())["kind"] == "hello"
    assert await a.next_event() is None
    assert await b.next_event() is None
