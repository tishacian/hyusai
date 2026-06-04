"""Shared retrieval profile contract.

Profiles keep the RAG engine invariant across surfaces while changing only the
latency/quality knobs each surface is allowed to use.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

RetrievalProfileName = Literal["oracle_fast", "chat", "deep_async"]


@dataclass(frozen=True)
class RetrievalProfile:
    name: RetrievalProfileName
    latency_profile: Literal["fast", "balanced", "deep"]
    max_top_k: int
    max_source_display_k: int
    max_synthesis_k: int
    max_candidate_pool_k: int
    deadline_seconds: float | None = None
    force_mode: str | None = None
    allow_hah_chah: bool = True
    allow_cross_encoder: bool = True

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


RETRIEVAL_PROFILE_ALIASES = {
    "oracle": "oracle_fast",
    "oracle-fast": "oracle_fast",
    "oracle_fast": "oracle_fast",
    "kc": "oracle_fast",
    "knowledge_capture": "oracle_fast",
    "chat": "chat",
    "deep": "deep_async",
    "deep-async": "deep_async",
    "deep_async": "deep_async",
}

RETRIEVAL_PROFILES: dict[RetrievalProfileName, RetrievalProfile] = {
    "oracle_fast": RetrievalProfile(
        name="oracle_fast",
        latency_profile="fast",
        max_top_k=8,
        max_source_display_k=8,
        max_synthesis_k=12,
        max_candidate_pool_k=20,
        deadline_seconds=2.5,
        force_mode="naive",
        allow_hah_chah=False,
        allow_cross_encoder=False,
    ),
    "chat": RetrievalProfile(
        name="chat",
        latency_profile="balanced",
        max_top_k=12,
        max_source_display_k=24,
        max_synthesis_k=24,
        max_candidate_pool_k=80,
        allow_hah_chah=True,
        allow_cross_encoder=True,
    ),
    "deep_async": RetrievalProfile(
        name="deep_async",
        latency_profile="deep",
        max_top_k=24,
        max_source_display_k=24,
        max_synthesis_k=48,
        max_candidate_pool_k=200,
        allow_hah_chah=True,
        allow_cross_encoder=True,
    ),
}


def normalize_retrieval_profile_name(value: object, *, latency_profile: str) -> RetrievalProfileName:
    requested = RETRIEVAL_PROFILE_ALIASES.get(str(value or "").strip().lower())
    if requested in RETRIEVAL_PROFILES:
        return requested  # type: ignore[return-value]
    if latency_profile == "deep":
        return "deep_async"
    return "chat"


def retrieval_profile_for(name: object) -> RetrievalProfile:
    normalized = RETRIEVAL_PROFILE_ALIASES.get(str(name or "").strip().lower()) or str(name or "chat")
    return RETRIEVAL_PROFILES.get(normalized, RETRIEVAL_PROFILES["chat"])  # type: ignore[arg-type]
