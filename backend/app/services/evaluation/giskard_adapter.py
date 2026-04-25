"""Optional Giskard/RAGET integration.

This module is intentionally not imported by the chat/orchestrator path.
It gives us a narrow adapter for offline jobs (manual "generate eval set",
nightly QA, future E1.5.5b Hypervisor suggestions) while Agentium remains
usable if the optional ``giskard[llm]`` dependency is not installed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Optional


class GiskardUnavailable(RuntimeError):
    """Raised when optional Giskard features are used without the extra dep."""


@dataclass(frozen=True)
class KnowledgeBaseRow:
    text: str
    metadata: Optional[Mapping[str, Any]] = None


def _import_giskard_rag():
    try:
        from giskard.rag import KnowledgeBase, evaluate, generate_testset  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise GiskardUnavailable(
            "Giskard is not installed. Install backend/requirements_giskard.txt "
            "on the offline eval worker to enable RAGET testset generation."
        ) from exc
    return KnowledgeBase, evaluate, generate_testset


def is_giskard_available() -> bool:
    try:
        _import_giskard_rag()
        return True
    except GiskardUnavailable:
        return False


def configure_giskard_models(
    *,
    llm_model: Optional[str] = None,
    embedding_model: Optional[str] = None,
    api_base: Optional[str] = None,
    disable_structured_output: bool = False,
) -> None:
    """Configure Giskard's LiteLLM-backed model defaults.

    Giskard RAGET needs an embedding model even to build a KnowledgeBase.
    Keeping this explicit avoids surprising network calls from import-time
    defaults and makes the offline worker contract obvious.
    """
    try:
        import giskard  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise GiskardUnavailable(
            "Giskard is not installed. Install backend/requirements_giskard.txt "
            "on the offline eval worker to enable RAGET testset generation."
        ) from exc

    kwargs: dict[str, Any] = {}
    if api_base:
        kwargs["api_base"] = api_base
    if llm_model:
        giskard.llm.set_llm_model(
            llm_model,
            disable_structured_output=disable_structured_output,
            **kwargs,
        )
    if embedding_model:
        giskard.llm.set_embedding_model(embedding_model, **kwargs)


def make_knowledge_base(rows: Iterable[KnowledgeBaseRow]):
    """Build a Giskard KnowledgeBase from Agentium document chunks."""
    KnowledgeBase, _, _ = _import_giskard_rag()
    try:
        import pandas as pd  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise GiskardUnavailable(
            "Giskard RAGET requires pandas; install backend/requirements_giskard.txt."
        ) from exc

    records = [
        {
            "text": row.text,
            "metadata": dict(row.metadata or {}),
        }
        for row in rows
        if row.text and row.text.strip()
    ]
    try:
        return KnowledgeBase.from_pandas(pd.DataFrame(records), columns=["text"])
    except ValueError as exc:
        if "No embeddings model set" in str(exc):
            raise GiskardUnavailable(
                "Giskard KnowledgeBase requires an embedding model. Call "
                "configure_giskard_models(embedding_model=...) before "
                "make_knowledge_base/generate_rag_testset."
            ) from exc
        raise


def generate_rag_testset(
    rows: Iterable[KnowledgeBaseRow],
    *,
    num_questions: int = 30,
    language: Optional[str] = None,
    agent_description: Optional[str] = None,
    min_knowledge_rows: int = 8,
):
    """Generate a synthetic QA testset from Agentium KB rows.

    Returns Giskard's QATestset object. Callers should persist it as JSONL
    or convert to pandas; the adapter does not introduce a new Agentium
    table yet because E1.5.3 only needs online run analytics.
    """
    rows_list = [row for row in rows if row.text and row.text.strip()]
    if len(rows_list) < min_knowledge_rows:
        raise GiskardUnavailable(
            "Giskard RAGET topic discovery needs a non-trivial knowledge base. "
            f"Got {len(rows_list)} usable rows; require at least {min_knowledge_rows}."
        )
    _, _, generate_testset = _import_giskard_rag()
    kb = make_knowledge_base(rows_list)
    kwargs: dict[str, Any] = {"num_questions": num_questions}
    if language:
        kwargs["language"] = language
    if agent_description:
        kwargs["agent_description"] = agent_description
    return generate_testset(kb, **kwargs)


def evaluate_rag_testset(
    answer_fn: Callable[..., str],
    testset: Any,
    rows: Iterable[KnowledgeBaseRow],
):
    """Run Giskard RAGET evaluation against an Agentium answer function."""
    _, evaluate, _ = _import_giskard_rag()
    kb = make_knowledge_base(rows)
    return evaluate(answer_fn, testset=testset, knowledge_base=kb)
