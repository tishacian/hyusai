"""Offline retrieval evaluation helpers.

This module is intentionally model-agnostic. Candidate embeddings such as
``bge-m3`` are evaluated from exported retrieval rows before any global
embedding setting is changed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class EmbeddingEvalCandidate:
    name: str
    embedding_provider: str
    embedding_model: str
    collection_suffix: str
    mutates_global_settings: bool = False


@dataclass(frozen=True)
class RetrievalEvalCase:
    query: str
    expected_document_ids: tuple[str, ...]
    results: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    metrics: Mapping[str, Any] = field(default_factory=dict)


def bge_m3_candidate() -> EmbeddingEvalCandidate:
    return EmbeddingEvalCandidate(
        name="bge-m3",
        embedding_provider="candidate",
        embedding_model="bge-m3",
        collection_suffix="__eval_bge_m3",
        mutates_global_settings=False,
    )


def _result_document_id(row: Mapping[str, Any]) -> str:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    return str(
        metadata.get("document_id")
        or row.get("document_id")
        or metadata.get("id")
        or row.get("id")
        or ""
    ).strip()


def _has_validated_provenance(row: Mapping[str, Any]) -> bool:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    values = {
        str(metadata.get("status") or "").strip().lower(),
        str(metadata.get("review_status") or "").strip().lower(),
        str(metadata.get("validation_status") or "").strip().lower(),
        str(metadata.get("source_kind") or "").strip().lower(),
        str(metadata.get("source_family") or "").strip().lower(),
    }
    return bool(values & {"accepted", "approved", "official", "published", "ready", "reviewed", "validated", "verified", "manual", "notice"})


def score_retrieval_cases(
    cases: Iterable[RetrievalEvalCase],
    *,
    ks: tuple[int, ...] = (1, 3, 5, 10),
) -> dict[str, Any]:
    rows = list(cases)
    total = len(rows)
    if total == 0:
        return {
            "cases": 0,
            "recall_at_k": {str(k): 0.0 for k in ks},
            "validated_provenance_rate": 0.0,
            "dense_only_rate": 0.0,
            "hybrid_ok_rate": 0.0,
        }

    recall_hits = {k: 0 for k in ks}
    validated_provenance = 0
    dense_only = 0
    hybrid_ok = 0
    for case in rows:
        expected = {str(item) for item in case.expected_document_ids if str(item or "").strip()}
        result_doc_ids = [_result_document_id(row) for row in case.results]
        for k in ks:
            if expected and expected.intersection(result_doc_ids[:k]):
                recall_hits[k] += 1
        if any(_has_validated_provenance(row) for row in case.results):
            validated_provenance += 1
        if bool(case.metrics.get("dense_only")):
            dense_only += 1
        if str(case.metrics.get("sparse_status") or "").strip().lower() == "ok":
            hybrid_ok += 1

    return {
        "cases": total,
        "recall_at_k": {str(k): recall_hits[k] / total for k in ks},
        "validated_provenance_rate": validated_provenance / total,
        "dense_only_rate": dense_only / total,
        "hybrid_ok_rate": hybrid_ok / total,
    }


def embedding_candidate_eval_report(
    *,
    candidate: EmbeddingEvalCandidate,
    baseline_cases: Iterable[RetrievalEvalCase],
    candidate_cases: Iterable[RetrievalEvalCase],
    ks: tuple[int, ...] = (1, 3, 5, 10),
) -> dict[str, Any]:
    """Compare a candidate embedding collection without touching global settings."""
    baseline_scores = score_retrieval_cases(baseline_cases, ks=ks)
    candidate_scores = score_retrieval_cases(candidate_cases, ks=ks)
    recall_delta = {
        str(k): candidate_scores["recall_at_k"].get(str(k), 0.0)
        - baseline_scores["recall_at_k"].get(str(k), 0.0)
        for k in ks
    }
    scalar_deltas = {
        key: candidate_scores.get(key, 0.0) - baseline_scores.get(key, 0.0)
        for key in ("validated_provenance_rate", "dense_only_rate", "hybrid_ok_rate")
    }
    isolated = bool(
        candidate.collection_suffix
        and candidate.collection_suffix.startswith("__eval_")
        and not candidate.mutates_global_settings
    )
    return {
        "candidate": {
            "name": candidate.name,
            "embedding_provider": candidate.embedding_provider,
            "embedding_model": candidate.embedding_model,
            "collection_suffix": candidate.collection_suffix,
            "mutates_global_settings": candidate.mutates_global_settings,
        },
        "isolated_candidate": isolated,
        "global_settings_mutation_allowed": False,
        "baseline": baseline_scores,
        "candidate_scores": candidate_scores,
        "delta": {
            "recall_at_k": recall_delta,
            **scalar_deltas,
        },
    }
