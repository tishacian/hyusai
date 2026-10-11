"""Token-level streaming primitives for the Run engine (Vague D / D2).

The sequential walker and the DAG walker both persist node-level
checkpoints (``node_start``, ``node_end``, ``run_end``…). Those are
coarse — they describe the *shape* of execution but never the *contents*
of the LLM's answer as it's being generated. Historically the cockpit
had to wait for ``node_end`` to display the completed text, which made
real-time perception atrocious even when the underlying LLM was
streaming.

This module bridges the gap by letting streaming-capable skills hand
back a ``TokenSink`` callable that publishes ``token_delta`` events to
the in-memory :mod:`app.services.run_engine.events` bus. The SSE
endpoint (``GET /runs/{id}/stream``) forwards them untouched.

Design constraints
------------------

* **Zero persistence.** Tokens land on the live bus only; the final
  concatenated text is already persisted in
  :class:`SkillInvocation.output_ref` so replay can reconstruct the
  typewriter client-side without bloating ``Run.checkpoints``.
* **Best-effort.** If the bus is closed or no subscriber exists,
  :meth:`publish` is a no-op, so the skill never blocks on an absent
  consumer. The sink object itself is inert when the bus is idle.
* **Lightweight throttling.** A single LLM easily emits 50+ tokens per
  second; that's already acceptable for an SSE channel, but we coalesce
  rapid-fire chunks into slightly larger bursts (flush on
  ``min_flush_interval_s`` elapsed OR ``min_flush_chars`` accumulated)
  so the network frame count stays bounded. Consumers still see the
  text evolve at sub-second granularity which reads as "real-time".
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from app.core.logging import get_logger

from .events import RunEventBus, bus as default_bus

logger = get_logger(__name__)


TokenSink = Callable[[str], None]
"""Callable used by streaming skills to push text deltas.

Skills treat the sink as fire-and-forget: they pass whatever chunk of
text they just received from the upstream LLM and never inspect the
return value. A ``None`` sink (passed via ``ctx.get("token_sink")``
returning ``None``) means streaming is disabled and the skill should
fall back to its non-streaming code path.
"""


@dataclass
class _TokenBuffer:
    """Small coalescing buffer shared by one ``TokenSink`` closure."""

    text: str = ""
    seq: int = 0
    last_flush_at: float = field(default_factory=time.monotonic)


def make_token_sink(
    run_id: str,
    node_id: Optional[str],
    invocation_id: Optional[str],
    *,
    bus: RunEventBus = default_bus,
    min_flush_chars: int = 8,
    min_flush_interval_s: float = 0.04,
) -> TokenSink:
    """Return a closure that publishes ``token_delta`` events.

    Parameters
    ----------
    run_id, node_id, invocation_id
        Identifiers stamped on every event so the cockpit can route
        deltas to the right terminal line. ``node_id`` / ``invocation_id``
        may be ``None`` when the caller lacks a DAG node (e.g. chat
        endpoints): the frontend then groups by ``run_id`` only.
    bus
        Overridable for tests.
    min_flush_chars, min_flush_interval_s
        Coalesce chunks smaller than ``min_flush_chars`` until either
        the buffer grows past that threshold or
        ``min_flush_interval_s`` elapsed since the last flush. A final
        :meth:`flush_token_sink` call drains whatever remains.
    """
    buf = _TokenBuffer()

    def _publish(text: str) -> None:
        buf.seq += 1
        bus.publish(
            run_id,
            {
                "kind": "token_delta",
                "node_id": node_id,
                "invocation_id": invocation_id,
                "text": text,
                "seq": buf.seq,
            },
        )

    def sink(chunk: str) -> None:
        if not chunk:
            return
        buf.text += chunk
        now = time.monotonic()
        if (
            len(buf.text) >= min_flush_chars
            or (now - buf.last_flush_at) >= min_flush_interval_s
        ):
            flush_text = buf.text
            buf.text = ""
            buf.last_flush_at = now
            _publish(flush_text)

    sink._buf = buf  # type: ignore[attr-defined]
    sink._publish = _publish  # type: ignore[attr-defined]
    return sink


def flush_token_sink(sink: Optional[TokenSink]) -> None:
    """Drain any residual buffered text from ``sink``.

    Call this right before emitting ``node_end`` so the last partial
    burst (smaller than ``min_flush_chars``) still reaches the client.
    Safe to call with ``None`` or with a sink built by another factory
    (we only act on sinks we created).
    """
    if sink is None:
        return
    buf = getattr(sink, "_buf", None)
    publish = getattr(sink, "_publish", None)
    if buf is None or publish is None:
        return
    if buf.text:
        pending = buf.text
        buf.text = ""
        publish(pending)
