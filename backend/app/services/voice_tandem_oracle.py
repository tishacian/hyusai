"""Provider-neutral tandem oracle for realtime voice loops.

The oracle models the KAME-style pattern without binding Agentium to KAME,
Moshi, OpenAI Realtime or any GPU runtime: fast voice events keep flowing while
background reasoning emits advisory signals. The latest signal wins, older
signals are explicitly superseded, and only committed final turns should drive
governed Knowledge updates.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class VoiceMicroTurn:
    turn_id: str
    partial_seq: int
    duration_ms: int
    text: str
    input_state: Dict[str, Any] = field(default_factory=dict)
    output_state: Dict[str, Any] = field(default_factory=dict)
    is_final: bool = False

    def as_payload(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "partial_seq": self.partial_seq,
            "duration_ms": self.duration_ms,
            "input_state": self.input_state,
            "output_state": self.output_state,
            "is_final": self.is_final,
        }


@dataclass
class VoiceOracleSignal:
    oracle_id: str
    turn_id: str
    partial_seq: int
    action: str
    content: str
    confidence: float
    reason: str
    sources: List[Dict[str, Any]] = field(default_factory=list)
    supersedes: str | None = None
    created_ms: int = field(default_factory=_now_ms)
    micro_turn: VoiceMicroTurn | None = None

    def as_payload(self) -> Dict[str, Any]:
        payload = {
            "oracle_id": self.oracle_id,
            "turn_id": self.turn_id,
            "partial_seq": self.partial_seq,
            "action": self.action,
            "content": self.content,
            "confidence": self.confidence,
            "reason": self.reason,
            "sources": self.sources,
            "supersedes": self.supersedes,
            "created_ms": self.created_ms,
            "mode": "tandem_oracle",
        }
        if self.micro_turn:
            payload["micro_turn"] = self.micro_turn.as_payload()
        return payload


class VoiceTandemOracle:
    """Small, deterministic oracle scheduler used by WS, skills and tests.

    It does not perform provider-specific reasoning itself. It decides when a
    partial transcript is meaningful enough to surface a background-oracle
    delta, and it stamps final capture decisions with enough ordering metadata
    for clients and audit to apply the "latest oracle wins" rule safely.
    """

    def __init__(self, *, min_interval_ms: int = 350, min_delta_chars: int = 24) -> None:
        self.min_interval_ms = max(0, int(min_interval_ms))
        self.min_delta_chars = max(0, int(min_delta_chars))
        self._active_signal: VoiceOracleSignal | None = None
        self._last_partial_text = ""
        self._last_partial_at = 0.0
        self._partial_seq = 0

    @property
    def partial_seq(self) -> int:
        return self._partial_seq

    def observe_partial(
        self,
        text: str,
        *,
        turn_id: str,
        input_state: Dict[str, Any] | None = None,
        output_state: Dict[str, Any] | None = None,
        sources: Iterable[Dict[str, Any]] | None = None,
        duration_ms: int = 0,
        force: bool = False,
    ) -> list[Dict[str, Any]]:
        normalized = " ".join(str(text or "").split())
        if not normalized:
            return []
        if not force and not self._should_emit_partial(normalized):
            return []

        self._partial_seq += 1
        micro_turn = VoiceMicroTurn(
            turn_id=turn_id,
            partial_seq=self._partial_seq,
            duration_ms=max(0, int(duration_ms)),
            text=normalized,
            input_state=input_state or {"transcript_state": "partial"},
            output_state=output_state or {"oracle_state": "thinking"},
        )
        previous = self._active_signal
        signal = VoiceOracleSignal(
            oracle_id=str(uuid.uuid4()),
            turn_id=turn_id,
            partial_seq=self._partial_seq,
            action="keep_listening",
            content=self._delta_content(normalized),
            confidence=0.35,
            reason="partial_transcript_progress",
            sources=list(sources or []),
            supersedes=previous.oracle_id if previous else None,
            micro_turn=micro_turn,
        )
        self._active_signal = signal
        self._last_partial_text = normalized
        self._last_partial_at = time.perf_counter()
        return self._signal_events(signal, event_type="oracle.delta", previous=previous)

    def emit_hint(
        self,
        hint_text: str,
        *,
        turn_id: str,
        subtopic_id: str | None = None,
        sources: Iterable[Dict[str, Any]] | None = None,
        kb_excerpt: str | None = None,
        oracle_id: str | None = None,
    ) -> list[Dict[str, Any]]:
        """Surface a non-vocal capture hint (no next_prompt injection)."""
        normalized = " ".join(str(hint_text or "").split())
        if not normalized:
            return []
        self._partial_seq += 1
        previous = self._active_signal
        signal = VoiceOracleSignal(
            oracle_id=oracle_id or str(uuid.uuid4()),
            turn_id=turn_id,
            partial_seq=self._partial_seq,
            action="hint",
            content=normalized[:80],
            confidence=0.78,
            reason="capture_hint",
            sources=list(sources or []),
            supersedes=previous.oracle_id if previous else None,
            micro_turn=VoiceMicroTurn(
                turn_id=turn_id,
                partial_seq=self._partial_seq,
                duration_ms=0,
                text=normalized,
                input_state={"transcript_state": "partial"},
                output_state={"oracle_state": "hint", "subtopic_id": subtopic_id, "kb_excerpt": kb_excerpt},
            ),
        )
        self._active_signal = signal
        events = self._signal_events(signal, event_type="oracle.action", previous=previous)
        events.append(
            {
                "type": "capture.hint_pushed",
                "payload": {
                    **signal.as_payload(),
                    "hint": normalized[:80],
                    "subtopic_id": subtopic_id,
                    "kb_excerpt": kb_excerpt,
                },
            }
        )
        return events

    def commit_final(
        self,
        text: str,
        *,
        turn_id: str,
        evaluation: Dict[str, Any] | None = None,
        next_prompt: str | None = None,
        sources: Iterable[Dict[str, Any]] | None = None,
        duration_ms: int = 0,
    ) -> list[Dict[str, Any]]:
        normalized = " ".join(str(text or "").split())
        self._partial_seq += 1
        previous = self._active_signal
        action = self._commit_action(evaluation=evaluation, next_prompt=next_prompt)
        signal = VoiceOracleSignal(
            oracle_id=str(uuid.uuid4()),
            turn_id=turn_id,
            partial_seq=self._partial_seq,
            action=action,
            content=str(next_prompt or normalized or "Final transcript committed."),
            confidence=self._commit_confidence(evaluation),
            reason="final_transcript_committed",
            sources=list(sources or self._sources_from_evaluation(evaluation)),
            supersedes=previous.oracle_id if previous else None,
            micro_turn=VoiceMicroTurn(
                turn_id=turn_id,
                partial_seq=self._partial_seq,
                duration_ms=max(0, int(duration_ms)),
                text=normalized,
                input_state={"transcript_state": "final"},
                output_state={"oracle_state": "committed", "action": action},
                is_final=True,
            ),
        )
        self._active_signal = None
        self._last_partial_text = ""
        events = self._signal_events(signal, event_type="oracle.action", previous=previous)
        events.append({"type": "oracle.commit", "payload": signal.as_payload()})
        return events

    def timeout(self, *, turn_id: str, reason: str = "oracle_timeout") -> list[Dict[str, Any]]:
        previous = self._active_signal
        if not previous:
            return []
        self._active_signal = None
        return [
            {
                "type": "oracle.superseded",
                "payload": {
                    "oracle_id": previous.oracle_id,
                    "turn_id": turn_id,
                    "partial_seq": previous.partial_seq,
                    "reason": reason,
                    "superseded_by": None,
                    "mode": "tandem_oracle",
                },
            }
        ]

    def _should_emit_partial(self, normalized: str) -> bool:
        now = time.perf_counter()
        if self._last_partial_text and abs(len(normalized) - len(self._last_partial_text)) < self.min_delta_chars:
            return False
        elapsed_ms = int((now - self._last_partial_at) * 1000) if self._last_partial_at else self.min_interval_ms
        return elapsed_ms >= self.min_interval_ms

    def _signal_events(
        self,
        signal: VoiceOracleSignal,
        *,
        event_type: str,
        previous: VoiceOracleSignal | None,
    ) -> list[Dict[str, Any]]:
        events: list[Dict[str, Any]] = []
        if previous:
            events.append(
                {
                    "type": "oracle.superseded",
                    "payload": {
                        "oracle_id": previous.oracle_id,
                        "turn_id": previous.turn_id,
                        "partial_seq": previous.partial_seq,
                        "reason": "latest_oracle_wins",
                        "superseded_by": signal.oracle_id,
                        "mode": "tandem_oracle",
                    },
                }
            )
        events.append({"type": event_type, "payload": signal.as_payload()})
        if signal.micro_turn:
            events.append(
                {
                    "type": "runtime.metric",
                    "payload": {
                        "metric": "micro_turn",
                        "value_ms": signal.micro_turn.duration_ms,
                        "turn_id": signal.turn_id,
                        "partial_seq": signal.partial_seq,
                        "input_state": signal.micro_turn.input_state,
                        "output_state": signal.micro_turn.output_state,
                        "mode": "tandem_oracle",
                    },
                }
            )
        return events

    @staticmethod
    def _delta_content(text: str) -> str:
        if len(text) <= 160:
            return text
        return f"{text[:157]}..."

    @staticmethod
    def _commit_action(*, evaluation: Dict[str, Any] | None, next_prompt: str | None) -> str:
        if next_prompt:
            return "next_prompt"
        verdict = str((evaluation or {}).get("verdict") or "").lower()
        action = str((evaluation or {}).get("action") or "").lower()
        if action == "hint":
            return "hint"
        if verdict in {"sufficient", "accepted", "complete"}:
            return "capture_fact"
        if verdict in {"needs_followup", "needs_more_detail", "insufficient"}:
            return "ask_followup"
        return "commit_transcript"

    @staticmethod
    def _commit_confidence(evaluation: Dict[str, Any] | None) -> float:
        raw = (evaluation or {}).get("confidence") or (evaluation or {}).get("score")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return 0.7
        return max(0.0, min(1.0, value if value <= 1 else value / 100))

    @staticmethod
    def _sources_from_evaluation(evaluation: Dict[str, Any] | None) -> list[Dict[str, Any]]:
        if not evaluation:
            return []
        for key in ("sources", "evidence", "citations"):
            value = evaluation.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []
