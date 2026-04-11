"""ACC (Agent Cognitive Compressor) MVP — bounded memory control for multi-turn agents.
Inspired by Bousetouane 2026 — simplified schema for demo."""
import json
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class CompressedCognitiveState(BaseModel):
    """CCS — the sole persistent internal representation across turns."""
    episodic_trace: str = Field(default="", description="What changed this turn")
    semantic_gist: str = Field(default="", description="Dominant intent or topic")
    focal_entities: list[str] = Field(default_factory=list, description="Key entities tracked")
    goal_orientation: str = Field(default="", description="Current persistent objective")
    constraints: list[str] = Field(default_factory=list, description="Active rules and safety constraints")
    predictive_cue: str = Field(default="", description="Expected next operation")
    uncertainty_level: str = Field(default="low", description="low / medium / high")
    turn_number: int = Field(default=0)
    token_count: int = Field(default=0, description="Approximate token size of this CCS")


CCS_COMPRESS_PROMPT = """You are a Cognitive Compressor for an AI agent. Your role is to produce a bounded cognitive state that replaces (not appends to) the previous state.

## Previous Cognitive State (turn {prev_turn}):
{previous_ccs}

## Current Turn Interaction:
User query: {query}
Agent response summary: {response_summary}

## Instructions:
Produce the next Compressed Cognitive State. Preserve only decision-critical information.
Discard redundant or stale content. Keep the state compact (under 300 tokens).

Return ONLY valid JSON matching this schema:
{{
  "episodic_trace": "What changed this turn (1-2 sentences)",
  "semantic_gist": "The dominant intent/topic now",
  "focal_entities": ["entity1", "entity2"],
  "goal_orientation": "Current persistent objective",
  "constraints": ["constraint1", "constraint2"],
  "predictive_cue": "Expected next user action or agent operation",
  "uncertainty_level": "low|medium|high"
}}"""


class ACCController:
    """Manages per-session Compressed Cognitive State."""

    def __init__(self):
        self._llm = None
        self._sessions: dict[str, CompressedCognitiveState] = {}

    def _get_llm(self):
        if self._llm is None:
            from app.llm.llm import LLM
            self._llm = LLM(provider=settings.default_provider, api_key=settings.openai_api_key)
        return self._llm

    def get_state(self, session_id: str) -> Optional[CompressedCognitiveState]:
        return self._sessions.get(session_id)

    def get_state_for_prompt(self, session_id: str) -> str:
        ccs = self._sessions.get(session_id)
        if not ccs or ccs.turn_number == 0:
            return ""
        return (
            f"\n[Cognitive State — Turn {ccs.turn_number}]\n"
            f"Gist: {ccs.semantic_gist}\n"
            f"Entities: {', '.join(ccs.focal_entities)}\n"
            f"Goal: {ccs.goal_orientation}\n"
            f"Constraints: {'; '.join(ccs.constraints)}\n"
            f"Uncertainty: {ccs.uncertainty_level}\n"
            f"Predictive cue: {ccs.predictive_cue}\n"
        )

    async def compress(self, session_id: str, query: str, response: str) -> CompressedCognitiveState:
        prev = self._sessions.get(session_id, CompressedCognitiveState())
        llm = self._get_llm()

        prev_json = prev.model_dump_json(indent=2) if prev.turn_number > 0 else "(initial state)"
        prompt = CCS_COMPRESS_PROMPT.format(
            prev_turn=prev.turn_number,
            previous_ccs=prev_json,
            query=query,
            response_summary=response[:800],
        )

        try:
            result = await llm.complete(prompt=prompt, model="gpt-4o-mini", temperature=0.2, max_tokens=500)
            text = result.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            data = json.loads(text)
            ccs = CompressedCognitiveState(
                episodic_trace=data.get("episodic_trace", ""),
                semantic_gist=data.get("semantic_gist", ""),
                focal_entities=data.get("focal_entities", []),
                goal_orientation=data.get("goal_orientation", ""),
                constraints=data.get("constraints", []),
                predictive_cue=data.get("predictive_cue", ""),
                uncertainty_level=data.get("uncertainty_level", "low"),
                turn_number=prev.turn_number + 1,
                token_count=len(text.split()),
            )
        except Exception as e:
            logger.error(f"ACC compression failed: {e}")
            ccs = CompressedCognitiveState(
                episodic_trace=f"Turn {prev.turn_number + 1}: {query[:100]}",
                semantic_gist=prev.semantic_gist or query[:100],
                focal_entities=prev.focal_entities,
                goal_orientation=prev.goal_orientation,
                constraints=prev.constraints,
                predictive_cue="continue",
                uncertainty_level="medium",
                turn_number=prev.turn_number + 1,
                token_count=prev.token_count,
            )

        self._sessions[session_id] = ccs
        return ccs

    def clear_session(self, session_id: str):
        self._sessions.pop(session_id, None)

    def all_sessions(self) -> dict:
        return {
            sid: ccs.model_dump()
            for sid, ccs in self._sessions.items()
        }


_acc = None

def get_acc_controller() -> ACCController:
    global _acc
    if _acc is None:
        _acc = ACCController()
    return _acc
