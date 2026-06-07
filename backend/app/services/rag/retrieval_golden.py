"""Golden retrieval cases and source/evidence evaluation helpers.

Golden cases validate retrieval evidence, not generated answer prose. This
keeps the suite useful for Agentium retrieval quality without encouraging
question-to-answer hardcoding.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_GOLDEN_BATCH = (
    Path(__file__).resolve().parents[2]
    / "resources"
    / "retrieval_golden"
    / "andritz_spl_dense.json"
)


@dataclass(frozen=True)
class RetrievalGoldenCase:
    id: str
    query: str
    collection: str
    expected_sources: tuple[str, ...]
    expected_evidence_terms: tuple[str, ...]
    expected_intent: str
    forbidden_route: str | None = None
    latency_profile: str = "fast"
    min_expected_sources: int = 1

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "RetrievalGoldenCase":
        return cls(
            id=str(payload["id"]),
            query=str(payload["query"]),
            collection=str(payload.get("collection") or "documents"),
            expected_sources=tuple(str(item) for item in payload.get("expected_sources") or ()),
            expected_evidence_terms=tuple(str(item) for item in payload.get("expected_evidence_terms") or ()),
            expected_intent=str(payload.get("expected_intent") or "content_search"),
            forbidden_route=str(payload.get("forbidden_route") or "") or None,
            latency_profile=str(payload.get("latency_profile") or "fast"),
            min_expected_sources=max(1, int(payload.get("min_expected_sources") or 1)),
        )

    def to_request(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "context_collection": self.collection,
            "latency_profile": self.latency_profile,
        }


def load_retrieval_golden_cases(path: str | Path | None = None) -> list[RetrievalGoldenCase]:
    target = Path(path) if path else DEFAULT_GOLDEN_BATCH
    data = json.loads(target.read_text(encoding="utf-8"))
    raw_cases = data.get("cases") if isinstance(data, Mapping) else data
    if not isinstance(raw_cases, list):
        raise ValueError(f"Golden retrieval batch {target} must contain a cases[] list")
    return [RetrievalGoldenCase.from_mapping(item) for item in raw_cases if isinstance(item, Mapping)]


def _normalise(value: Any) -> str:
    return " ".join(str(value or "").lower().replace("_", " ").replace("-", " ").split())


def _source_label(meta: Mapping[str, Any]) -> str:
    for key in ("document_filename", "filename", "source", "source_name", "title", "document_id"):
        value = meta.get(key)
        if value:
            return str(value)
    return ""


def _selected_source_labels(context: Mapping[str, Any], *, top_n: int = 5) -> list[str]:
    trace = context.get("retrieval_trace")
    if isinstance(trace, Mapping):
        selected = trace.get("selected_sources")
        if isinstance(selected, list):
            labels: list[str] = []
            for item in selected[:top_n]:
                if not isinstance(item, Mapping):
                    continue
                label = item.get("document_filename") or item.get("source") or item.get("document_id")
                if label:
                    labels.append(str(label))
            if labels:
                return labels

    labels = []
    for meta in (context.get("metadatas") or [])[:top_n]:
        if isinstance(meta, Mapping):
            label = _source_label(meta)
            if label:
                labels.append(label)
    return labels


def _context_text(context: Mapping[str, Any], *, top_n: int = 24) -> str:
    parts: list[str] = []
    for chunk in (context.get("chunks") or [])[:top_n]:
        parts.append(str(chunk or ""))
    for meta in (context.get("metadatas") or [])[:top_n]:
        if isinstance(meta, Mapping):
            parts.append(" ".join(str(value or "") for value in meta.values()))
    return _normalise(" ".join(parts))


def evaluate_retrieval_golden_case(
    case: RetrievalGoldenCase,
    context: Mapping[str, Any],
    *,
    top_n: int = 5,
) -> dict[str, Any]:
    labels = _selected_source_labels(context, top_n=top_n)
    labels_text = _normalise(" ".join(labels))
    expected_sources = list(case.expected_sources)
    matched_sources = [
        source
        for source in expected_sources
        if _normalise(source) and _normalise(source) in labels_text
    ]
    context_text = _context_text(context)
    missing_evidence_terms = [
        term
        for term in case.expected_evidence_terms
        if _normalise(term) and _normalise(term) not in context_text
    ]
    metrics = context.get("metrics") if isinstance(context.get("metrics"), Mapping) else {}
    dense_policy = str(metrics.get("dense_policy") or context.get("dense_policy") or "")
    forbidden_route_hit = bool(case.forbidden_route and case.forbidden_route in dense_policy)
    passed = (
        len(matched_sources) >= min(case.min_expected_sources, max(len(expected_sources), 1))
        and not missing_evidence_terms
        and not forbidden_route_hit
    )
    return {
        "id": case.id,
        "passed": passed,
        "matched_sources": matched_sources,
        "selected_sources": labels,
        "missing_sources": [source for source in expected_sources if source not in matched_sources],
        "missing_evidence_terms": missing_evidence_terms,
        "forbidden_route_hit": forbidden_route_hit,
        "dense_policy": dense_policy or None,
    }
