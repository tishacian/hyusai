"""Offline retrieval evaluation helpers.

This module is intentionally model-agnostic. Candidate embeddings such as
``bge-m3`` are evaluated from exported retrieval rows before any global
embedding setting is changed.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EmbeddingEvalCandidate:
    name: str
    embedding_provider: str
    embedding_model: str
    collection_suffix: str
    comparison_role: str = "exact_model_candidate"
    embedding_dimensions: int | None = None
    notes: str | None = None
    mutates_global_settings: bool = False


@dataclass(frozen=True)
class RetrievalEvalCase:
    query: str
    expected_document_ids: tuple[str, ...]
    results: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    metrics: Mapping[str, Any] = field(default_factory=dict)
    case_id: str | None = None


def bge_m3_candidate() -> EmbeddingEvalCandidate:
    return EmbeddingEvalCandidate(
        name="bge-m3",
        embedding_provider="openai_compatible_or_local",
        embedding_model="bge-m3",
        collection_suffix="__eval_bge_m3",
        comparison_role="exact_model_candidate",
        notes=(
            "Exact bge-m3 evaluation must use an isolated candidate collection "
            "built by a local, TEI, vLLM, or sentence-transformers provider. "
            "The OpenAI API does not host this model."
        ),
        mutates_global_settings=False,
    )


def openai_text_embedding_3_large_candidate(
    *,
    dimensions: int | None = None,
) -> EmbeddingEvalCandidate:
    suffix = "__eval_openai_text_embedding_3_large"
    if dimensions:
        suffix = f"{suffix}_{int(dimensions)}d"
    return EmbeddingEvalCandidate(
        name="openai-text-embedding-3-large",
        embedding_provider="openai",
        embedding_model="text-embedding-3-large",
        collection_suffix=suffix,
        comparison_role="dense_equivalent_candidate",
        embedding_dimensions=dimensions,
        notes=(
            "OpenAI dense embedding candidate. It can compete with the dense "
            "leg but does not provide bge-m3 sparse or late-interaction outputs."
        ),
        mutates_global_settings=False,
    )


def embedding_eval_candidate(
    name: str | None = None,
    *,
    dimensions: int | None = None,
) -> EmbeddingEvalCandidate:
    key = re.sub(r"[^a-z0-9]+", "-", str(name or "bge-m3").strip().lower()).strip("-")
    if key in {"bge-m3", "baai-bge-m3"}:
        return bge_m3_candidate()
    if key in {
        "openai-text-embedding-3-large",
        "text-embedding-3-large",
        "openai-large",
        "openai-dense",
    }:
        return openai_text_embedding_3_large_candidate(dimensions=dimensions)
    raise ValueError(
        "Unsupported embedding eval candidate. "
        "Use 'bge-m3' or 'openai-text-embedding-3-large'."
    )


def candidate_collection_name(
    base_collection: str,
    *,
    candidate: EmbeddingEvalCandidate | None = None,
) -> str:
    candidate = candidate or bge_m3_candidate()
    base = str(base_collection or "").strip()
    if not base:
        raise ValueError("base_collection is required")
    if base.endswith(candidate.collection_suffix):
        return base
    return f"{base}{candidate.collection_suffix}"


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        stripped = value.strip()
        return (stripped,) if stripped else ()
    if isinstance(value, Mapping):
        return ()
    if isinstance(value, Iterable):
        return tuple(str(item).strip() for item in value if str(item or "").strip())
    stripped = str(value).strip()
    return (stripped,) if stripped else ()


def _normalise_result_row(row: Any) -> Mapping[str, Any]:
    if isinstance(row, Mapping):
        return dict(row)
    return {"text": str(row)}


def _case_results(raw: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    for key in ("results", "retrieval_results", "rows", "chunks", "sources"):
        value = raw.get(key)
        if isinstance(value, Sequence) and not isinstance(value, str | bytes):
            return tuple(_normalise_result_row(item) for item in value)
    return ()


def _case_metrics(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in ("metrics", "retrieval_metrics"):
        value = raw.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    trace = raw.get("retrieval_trace")
    if isinstance(trace, Mapping) and isinstance(trace.get("metrics"), Mapping):
        return dict(trace["metrics"])
    return {}


def _case_expected_ids(raw: Mapping[str, Any]) -> tuple[str, ...]:
    for key in (
        "expected_document_ids",
        "expected_documents",
        "expected_doc_ids",
        "expected_sources",
        "expected_source_labels",
    ):
        values = _string_tuple(raw.get(key))
        if values:
            return values
    return ()


def _case_id(raw: Mapping[str, Any], fallback: str | None = None) -> str | None:
    for key in ("case_id", "id", "name"):
        value = str(raw.get(key) or "").strip()
        if value:
            return value
    return fallback


def _case_query(raw: Mapping[str, Any]) -> str:
    for key in ("query", "question", "prompt"):
        value = str(raw.get(key) or "").strip()
        if value:
            return value
    return ""


def retrieval_eval_case_from_mapping(
    payload: Mapping[str, Any],
    *,
    fallback_case_id: str | None = None,
) -> RetrievalEvalCase:
    query = _case_query(payload)
    if not query:
        label = _case_id(payload, fallback=fallback_case_id) or "<unknown>"
        raise ValueError(f"Retrieval eval case {label!r} is missing query/question")
    return RetrievalEvalCase(
        query=query,
        expected_document_ids=_case_expected_ids(payload),
        results=_case_results(payload),
        metrics=_case_metrics(payload),
        case_id=_case_id(payload, fallback=fallback_case_id),
    )


def _json_payload_from_path(path: str | Path) -> Any:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if target.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]


def _raw_cases_from_payload(payload: Any) -> list[tuple[str | None, Mapping[str, Any]]]:
    if isinstance(payload, list):
        return [(None, item) for item in payload if isinstance(item, Mapping)]
    if not isinstance(payload, Mapping):
        raise ValueError("Retrieval eval export must be a JSON object, array, or JSONL rows")

    cases = payload.get("cases")
    if isinstance(cases, list):
        return [(None, item) for item in cases if isinstance(item, Mapping)]

    if _case_query(payload) and any(key in payload for key in ("results", "retrieval_results", "rows", "chunks", "sources")):
        return [(None, payload)]

    rows: list[tuple[str | None, Mapping[str, Any]]] = []
    for key, value in payload.items():
        if isinstance(value, Mapping) and _case_query(value):
            rows.append((str(key), value))
    if rows:
        return rows

    raise ValueError("Retrieval eval export must contain cases[] or case mappings")


def load_retrieval_eval_cases(path: str | Path) -> list[RetrievalEvalCase]:
    payload = _json_payload_from_path(path)
    return [
        retrieval_eval_case_from_mapping(row, fallback_case_id=fallback_id)
        for fallback_id, row in _raw_cases_from_payload(payload)
    ]


def _case_pair_key(case: RetrievalEvalCase, index: int, *, prefer_index: bool) -> str:
    if prefer_index:
        return f"#{index}"
    return case.case_id or case.query or f"#{index}"


def align_retrieval_eval_case_pairs(
    baseline_cases: Iterable[RetrievalEvalCase],
    candidate_cases: Iterable[RetrievalEvalCase],
) -> tuple[list[RetrievalEvalCase], list[RetrievalEvalCase], dict[str, Any]]:
    baseline_rows = list(baseline_cases)
    candidate_rows = list(candidate_cases)
    prefer_index = not any(case.case_id for case in baseline_rows + candidate_rows)

    candidate_by_key = {
        _case_pair_key(case, index, prefer_index=prefer_index): case
        for index, case in enumerate(candidate_rows)
    }
    paired_baseline: list[RetrievalEvalCase] = []
    paired_candidate: list[RetrievalEvalCase] = []
    missing_candidate: list[str] = []
    expected_mismatch: list[str] = []

    for index, baseline in enumerate(baseline_rows):
        key = _case_pair_key(baseline, index, prefer_index=prefer_index)
        candidate = candidate_by_key.pop(key, None)
        if candidate is None:
            missing_candidate.append(key)
            continue

        baseline_expected = baseline.expected_document_ids
        candidate_expected = candidate.expected_document_ids
        if baseline_expected and candidate_expected and set(baseline_expected) != set(candidate_expected):
            expected_mismatch.append(key)
        expected = baseline_expected or candidate_expected
        paired_baseline.append(
            replace(baseline, expected_document_ids=expected, case_id=baseline.case_id or candidate.case_id)
        )
        paired_candidate.append(
            replace(candidate, expected_document_ids=expected, case_id=candidate.case_id or baseline.case_id)
        )

    return paired_baseline, paired_candidate, {
        "paired_cases": len(paired_baseline),
        "baseline_cases": len(baseline_rows),
        "candidate_cases": len(candidate_rows),
        "missing_candidate_cases": missing_candidate,
        "extra_candidate_cases": sorted(candidate_by_key),
        "expected_mismatch_cases": expected_mismatch,
        "aligned_by": "index" if prefer_index else "case_id_or_query",
    }


def _result_document_id(row: Mapping[str, Any]) -> str:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    return str(
        metadata.get("document_id")
        or row.get("document_id")
        or metadata.get("id")
        or row.get("id")
        or metadata.get("document_filename")
        or row.get("document_filename")
        or metadata.get("filename")
        or row.get("filename")
        or metadata.get("source")
        or row.get("source")
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
            "comparison_role": candidate.comparison_role,
            "embedding_dimensions": candidate.embedding_dimensions,
            "notes": candidate.notes,
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


def embedding_candidate_eval_report_from_exports(
    *,
    candidate: EmbeddingEvalCandidate,
    baseline_export: str | Path,
    candidate_export: str | Path,
    base_collection: str | None = None,
    ks: tuple[int, ...] = (1, 3, 5, 10),
) -> dict[str, Any]:
    baseline_cases = load_retrieval_eval_cases(baseline_export)
    candidate_cases = load_retrieval_eval_cases(candidate_export)
    paired_baseline, paired_candidate, alignment = align_retrieval_eval_case_pairs(
        baseline_cases,
        candidate_cases,
    )
    report = embedding_candidate_eval_report(
        candidate=candidate,
        baseline_cases=paired_baseline,
        candidate_cases=paired_candidate,
        ks=ks,
    )
    report["inputs"] = {
        "baseline_export": str(Path(baseline_export)),
        "candidate_export": str(Path(candidate_export)),
        "base_collection": base_collection,
        "candidate_collection": (
            candidate_collection_name(base_collection, candidate=candidate)
            if base_collection
            else None
        ),
    }
    report["alignment"] = alignment
    return report
