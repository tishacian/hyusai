"""Unit tests for the token streaming primitives (Vague D / D2).

Covers the three behaviours the run engine relies on:

1. ``make_token_sink`` publishes ``token_delta`` events carrying
   ``run_id`` / ``node_id`` / ``invocation_id`` / ``seq`` on the bus.
2. The sink coalesces sub-threshold chunks and releases bigger bursts,
   i.e. the cockpit never gets a separate frame for every single
   character of a fast streaming LLM.
3. ``flush_token_sink`` drains whatever is still in the coalescing
   buffer so the tail of the completion arrives before ``node_end``.
"""
from __future__ import annotations

import asyncio

import pytest

from app.services.run_engine.events import RunEventBus
from app.services.run_engine.streaming import flush_token_sink, make_token_sink


@pytest.mark.asyncio
async def test_sink_publishes_token_delta_events() -> None:
    bus = RunEventBus()
    sub = bus.subscribe("run-1")
    sink = make_token_sink(
        "run-1", "node-1", "inv-1", bus=bus, min_flush_chars=1, min_flush_interval_s=0.0
    )

    sink("Hello ")
    sink("world")
    bus.close("run-1")

    events = []
    while True:
        event = await sub.next_event()
        if event is None:
            break
        events.append(event)
    await sub.aclose()

    assert [e["kind"] for e in events] == ["token_delta", "token_delta"]
    assert [e["text"] for e in events] == ["Hello ", "world"]
    assert [e["seq"] for e in events] == [1, 2]
    assert all(e["node_id"] == "node-1" and e["invocation_id"] == "inv-1" for e in events)


@pytest.mark.asyncio
async def test_sink_coalesces_small_chunks() -> None:
    bus = RunEventBus()
    sub = bus.subscribe("run-2")
    sink = make_token_sink(
        "run-2",
        "n1",
        "inv-2",
        bus=bus,
        # Require at least 4 chars buffered before flushing + a long
        # interval so the time-based escape hatch never fires within
        # this synchronous call sequence.
        min_flush_chars=4,
        min_flush_interval_s=10.0,
    )

    sink("a")
    sink("b")
    sink("c")  # still under 4 chars → no publish yet.

    sink("de")  # buffer is now "abcde" ≥ 4 → flush.
    flush_token_sink(sink)
    bus.close("run-2")

    events = []
    while True:
        event = await sub.next_event()
        if event is None:
            break
        events.append(event)
    await sub.aclose()

    assert [e["text"] for e in events] == ["abcde"]
    assert events[0]["seq"] == 1


@pytest.mark.asyncio
async def test_flush_drains_residual_buffer() -> None:
    bus = RunEventBus()
    sub = bus.subscribe("run-3")
    sink = make_token_sink(
        "run-3", "n1", "inv-3", bus=bus, min_flush_chars=100, min_flush_interval_s=10.0
    )

    sink("tail")  # too small to flush on its own.
    flush_token_sink(sink)
    bus.close("run-3")

    events = []
    while True:
        event = await sub.next_event()
        if event is None:
            break
        events.append(event)
    await sub.aclose()

    assert len(events) == 1
    assert events[0]["text"] == "tail"
    assert events[0]["kind"] == "token_delta"


@pytest.mark.asyncio
async def test_flush_is_safe_on_none() -> None:
    # Called by the engine even when streaming was never enabled.
    flush_token_sink(None)


@pytest.mark.asyncio
async def test_empty_chunks_are_ignored() -> None:
    bus = RunEventBus()
    sub = bus.subscribe("run-4")
    sink = make_token_sink(
        "run-4", "n1", "inv-4", bus=bus, min_flush_chars=1, min_flush_interval_s=0.0
    )

    sink("")
    sink(None)  # type: ignore[arg-type]
    flush_token_sink(sink)
    bus.close("run-4")

    events = []
    while True:
        event = await sub.next_event()
        if event is None:
            break
        events.append(event)
    await sub.aclose()

    assert events == []
