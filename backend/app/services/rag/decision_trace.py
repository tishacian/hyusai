"""Canonical, human-readable retrieval decision trace.

The trace is intentionally explanatory: it summarizes existing telemetry and
does not make routing decisions.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4


TRACE_VERSION = 1


def build_retrieval_decision_trace(
    *,
    request: Mapping[str, Any] | None = None,
    context: Mapping[str, Any] | None = None,
    metrics: Mapping[str, Any] | None = None,
    trace_source: str = "runtime",
) -> dict[str, Any]:
    """Build a stable trace from already-produced retrieval telemetry."""
    req = _as_dict(request)
    ctx = _as_dict(context)
    raw_metrics = _as_dict(metrics) or _as_dict(ctx.get("metrics")) or _as_dict(ctx.get("retrieval_metrics"))
    retrieval_plan = _as_dict(
        _first_present(
            raw_metrics.get("retrieval_plan"),
            ctx.get("retrieval_plan"),
            raw_metrics.get("policy"),
        )
    )
    retrieval_scope = _as_dict(
        _first_present(
            raw_metrics.get("retrieval_scope"),
            ctx.get("retrieval_scope"),
            raw_metrics.get("scope"),
        )
    )
    latency_budget = _as_dict(_first_present(raw_metrics.get("latency_budget"), ctx.get("latency_budget")))
    selected_sources = _selected_sources(raw_metrics, ctx)
    selected_route = _selected_route(raw_metrics, ctx)
    query_type = _query_type(raw_metrics, retrieval_plan, retrieval_scope, selected_route)
    latency_profile = str(
        _first_present(
            raw_metrics.get("latency_profile"),
            ctx.get("latency_profile"),
            latency_budget.get("profile"),
            req.get("latency_profile"),
        )
        or ""
    ) or None
    retrieval_profile = str(
        _first_present(
            raw_metrics.get("retrieval_profile"),
            ctx.get("retrieval_profile"),
            latency_budget.get("retrieval_profile"),
            req.get("retrieval_profile"),
        )
        or ""
    ) or None
    layers = _layers(retrieval_plan, raw_metrics)
    fallbacks = _fallbacks(raw_metrics, ctx)
    deep_search = _deep_search(raw_metrics, ctx)
    route_reason = _route_reason(raw_metrics, ctx, retrieval_scope, retrieval_plan, layers)
    trace = {
        "version": TRACE_VERSION,
        "trace_id": str(_first_present(raw_metrics.get("trace_id"), ctx.get("trace_id")) or uuid4()),
        "summary": _summary(selected_route, query_type, latency_profile, route_reason),
        "query_type": query_type,
        "latency_profile": latency_profile,
        "retrieval_profile": retrieval_profile,
        "selected_route": selected_route,
        "route_reason": route_reason,
        "tradeoff": _tradeoff(latency_profile, selected_route, raw_metrics, deep_search),
        "collection_scope": _collection_scope(raw_metrics, ctx, retrieval_scope),
        "layers": layers,
        "quality_controls": _quality_controls(raw_metrics, ctx, req),
        "fallbacks": fallbacks,
        "deep_search": deep_search,
        "answer_shaping": _answer_shaping(raw_metrics, ctx, req),
        "timings": _as_dict(raw_metrics.get("stage_timings")),
        "candidate_counts": _as_dict(raw_metrics.get("candidate_counts")),
        "selected_sources": selected_sources,
        "trace_source": trace_source if trace_source in {"runtime", "backfilled_partial"} else "runtime",
    }
    return _strip_none(trace)


def build_trivial_retrieval_decision_trace(
    *,
    reason: str | None = None,
    query: str | None = None,
    trace_source: str = "runtime",
) -> dict[str, Any]:
    return build_retrieval_decision_trace(
        request={"query": query or ""},
        metrics={
            "bypassed": True,
            "trivial_bypass": True,
            "reason": reason or "trivial",
            "pipeline": "trivial_bypass",
            "mode_label": "trivial_bypass",
            "duration_ms": 0,
            "stage_timings": {"total_ms": 0},
            "candidate_counts": {"chunks_retrieved": 0},
        },
        trace_source=trace_source,
    )


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _selected_route(metrics: Mapping[str, Any], context: Mapping[str, Any]) -> str:
    if metrics.get("trivial_bypass") or metrics.get("bypassed") or context.get("trivial_bypass"):
        return "trivial_bypass"
    if context.get("canonical_answer_hit") or metrics.get("canonical_answer_id"):
        return "canonical_answer"
    pipeline = str(_first_present(metrics.get("pipeline"), context.get("pipeline")) or "").strip()
    if pipeline:
        return pipeline
    mode_label = str(_first_present(metrics.get("mode_label"), context.get("mode_label")) or "").strip()
    if mode_label:
        return mode_label
    dense_policy = str(_first_present(metrics.get("dense_policy"), context.get("dense_policy")) or "").strip()
    if dense_policy:
        return dense_policy
    return "retrieval"


def _query_type(
    metrics: Mapping[str, Any],
    plan: Mapping[str, Any],
    scope: Mapping[str, Any],
    selected_route: str,
) -> str:
    if selected_route == "trivial_bypass":
        return "trivial"
    if selected_route == "canonical_answer":
        return "canonical"
    intent = str(_first_present(scope.get("intent"), plan.get("intent"), metrics.get("intent")) or "").strip()
    if intent:
        return intent
    if selected_route in {"collection_inventory", "dense_coarse_inventory"}:
        return "catalogue"
    if metrics.get("comparative_status") or metrics.get("comparative_plan"):
        return "comparative"
    return "content_search"


def _layers(plan: Mapping[str, Any], metrics: Mapping[str, Any]) -> list[dict[str, Any]]:
    layers = _as_dict(plan.get("layers"))
    out: list[dict[str, Any]] = []
    for key, raw in layers.items():
        layer = _as_dict(raw)
        out.append(
            _strip_none(
                {
                    "key": str(key),
                    "enabled": bool(layer.get("enabled")),
                    "status": layer.get("status") or ("enabled" if layer.get("enabled") else "skipped"),
                    "reason": layer.get("reason"),
                    "budget_ms": layer.get("budget_ms"),
                    "top_k": layer.get("top_k"),
                }
            )
        )
    if not out:
        for key, status_key in (
            ("sparse", "sparse_status"),
            ("cross_encoder", "cross_encoder_status"),
        ):
            status = metrics.get(status_key)
            if status:
                out.append({"key": key, "enabled": str(status) == "ok" or str(status) == "applied", "status": status})
    return out


def _collection_scope(
    metrics: Mapping[str, Any],
    context: Mapping[str, Any],
    scope: Mapping[str, Any],
) -> dict[str, Any]:
    collections = _first_present(
        metrics.get("collections_touched"),
        context.get("collections_touched"),
        context.get("collections"),
        scope.get("collections"),
    )
    if not isinstance(collections, list):
        single = _first_present(context.get("collection"), metrics.get("collection"))
        collections = [single] if single else []
    return _strip_none(
        {
            "knowledge_scope": _first_present(context.get("knowledge_scope"), metrics.get("knowledge_scope")),
            "collection": _first_present(context.get("collection"), metrics.get("collection")),
            "collections": [str(item) for item in collections if item],
            "filters": scope.get("filters"),
            "intent": scope.get("intent"),
            "dense": scope.get("dense"),
            "source_count": scope.get("source_count"),
            "chunk_count": scope.get("chunk_count"),
            "confidence": _first_present(metrics.get("scope_confidence"), scope.get("confidence")),
            "reason": _first_present(metrics.get("scope_reason"), scope.get("reason")),
        }
    )


def _quality_controls(metrics: Mapping[str, Any], context: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    return _strip_none(
        {
            "sparse_status": _first_present(metrics.get("sparse_status"), context.get("sparse_status")),
            "sparse_backend": _first_present(metrics.get("sparse_backend"), context.get("sparse_backend")),
            "cross_encoder_status": _first_present(metrics.get("cross_encoder_status"), context.get("cross_encoder_status")),
            "cross_encoder_model": metrics.get("cross_encoder_model"),
            "cross_encoder_ms": metrics.get("cross_encoder_ms"),
            "score_threshold_applied": _first_present(
                metrics.get("score_threshold_applied"),
                context.get("score_threshold_applied"),
            ),
            "dense_policy": _first_present(metrics.get("dense_policy"), context.get("dense_policy")),
            "dense_only": _first_present(metrics.get("dense_only"), context.get("dense_only")),
            "retrieval_policy": metrics.get("retrieval_policy"),
            "source_policy": _first_present(context.get("source_policy"), request.get("source_policy")),
        }
    )


def _fallbacks(metrics: Mapping[str, Any], context: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key in ("fallback_reason", "sparse_fallback_reason", "retrieval_fallback"):
        value = _first_present(metrics.get(key), context.get(key))
        if value:
            out.append({"kind": key, "reason": str(value)})
    if metrics.get("deadline_exceeded"):
        out.append({"kind": "deadline_exceeded", "reason": "retrieval_deadline_exceeded"})
    errors = _first_present(metrics.get("collection_errors"), context.get("collection_errors"))
    if isinstance(errors, list):
        for item in errors[:5]:
            if isinstance(item, Mapping):
                out.append({"kind": "collection_error", "reason": str(item.get("error") or item)})
    return out


def _deep_search(metrics: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    job_id = _first_present(metrics.get("deep_job_id"), context.get("deep_job_id"))
    return _strip_none(
        {
            "recommended": bool(_first_present(metrics.get("deep_retrieval_recommended"), context.get("deep_retrieval_recommended"))),
            "launched": bool(job_id),
            "job_id": job_id,
            "status": _first_present(metrics.get("deep_status"), context.get("deep_status")),
            "poll_url": _first_present(metrics.get("deep_poll_url"), context.get("deep_poll_url")),
        }
    )


def _answer_shaping(metrics: Mapping[str, Any], context: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    return _strip_none(
        {
            "prompt_type": _first_present(context.get("prompt_type"), request.get("prompt_type"), metrics.get("prompt_type")),
            "grounding_mode": _first_present(context.get("grounding_mode"), request.get("grounding_mode"), metrics.get("grounding_mode")),
            "response_language": _first_present(context.get("response_language"), request.get("response_language")),
            "require_sources": _first_present(context.get("require_sources"), request.get("require_sources")),
        }
    )


def _selected_sources(metrics: Mapping[str, Any], context: Mapping[str, Any]) -> list[dict[str, Any]]:
    trace = _as_dict(metrics.get("retrieval_trace"))
    selected = metrics.get("selected_sources") or trace.get("selected_sources") or context.get("selected_sources")
    if not isinstance(selected, list):
        selected = context.get("sources")
    out: list[dict[str, Any]] = []
    if not isinstance(selected, list):
        return out
    for item in selected[:8]:
        if not isinstance(item, Mapping):
            continue
        out.append(
            _strip_none(
                {
                    "label": _first_present(
                        item.get("label"),
                        item.get("title"),
                        item.get("document_filename"),
                        item.get("source"),
                        item.get("document_id"),
                    ),
                    "document_id": item.get("document_id"),
                    "collection": _first_present(item.get("collection"), item.get("collection_name")),
                    "score": item.get("score"),
                    "chunks": item.get("chunks"),
                }
            )
        )
    return out


def _route_reason(
    metrics: Mapping[str, Any],
    context: Mapping[str, Any],
    scope: Mapping[str, Any],
    plan: Mapping[str, Any],
    layers: list[dict[str, Any]],
) -> str:
    for value in (
        context.get("mode_reason"),
        metrics.get("mode_reason"),
        metrics.get("scope_reason"),
        scope.get("reason"),
        plan.get("reason"),
    ):
        if value:
            return str(value)
    enabled_layers = [str(item.get("key")) for item in layers if item.get("enabled")]
    if enabled_layers:
        return f"Enabled layers: {', '.join(enabled_layers[:5])}"
    return "Default retrieval route selected from workspace policy."


def _tradeoff(
    latency_profile: str | None,
    selected_route: str,
    metrics: Mapping[str, Any],
    deep_search: Mapping[str, Any],
) -> str:
    if selected_route == "trivial_bypass":
        return "Skipped retrieval to preserve latency for a trivial turn."
    if selected_route in {"collection_inventory", "dense_coarse_inventory"}:
        return "Used inventory/coarse evidence to avoid an expensive global scan."
    if deep_search.get("recommended") and not deep_search.get("launched"):
        return "Direct answer stayed bounded; Deep Search is recommended for higher recall."
    if latency_profile == "deep":
        return "Prioritized exhaustive recall over latency."
    if latency_profile == "balanced":
        return "Balanced latency with source recall and reranking quality controls."
    if latency_profile == "fast":
        return "Prioritized response latency with bounded retrieval."
    if metrics.get("dense_only"):
        return "Sparse/hybrid path was unavailable or degraded, so retrieval stayed dense-only."
    return "Selected the route that matched the query and workspace retrieval policy."


def _summary(route: str, query_type: str, latency_profile: str | None, reason: str) -> str:
    profile = latency_profile or "default"
    return f"{route} selected for {query_type} query under {profile} latency profile: {reason}"


def _strip_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_strip_none(item) for item in value if item is not None]
    return value
