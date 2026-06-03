#!/usr/bin/env python3
"""Probe SPL dense-retrieval guardrails on a live Agentium backend.

The default path is read-only: login, collection diagnostics, retrieval plan
preview, and artifact-job dry-runs. It proves that catalogue questions bypass
RAG and that auto/hybrid/HAH/C-HAH Quick Ask plans stay bounded on a dense SPL
collection before any Qdrant, sparse, rerank, LLM, or WorkerJob work starts.

Optional flags:
  --run-chat          sends real chat/completion requests and persists normal
                      chat Runs; use only for UX latency measurement.
  --run-stream        sends real chat/stream requests and checks SSE UX
                      health; use only for end-to-end stream measurement.
  --create-deep-job   queues one rag_deep_retrieval WorkerJob.

Usage:
  AGENTIUM_HOST=https://agentium.papai.ai \
  AGENTIUM_EMAIL=... \
  AGENTIUM_PASSWORD=... \
  WORKSPACE_SLUG=andritz \
  python3 scripts/probe_spl_retrieval_scaling.py

  # Or reuse an existing bearer token:
  AGENTIUM_BASE_URL=https://agentium.papai.ai \
  AGENTIUM_TOKEN=... \
  WORKSPACE_SLUG=andritz \
  python3 scripts/probe_spl_retrieval_scaling.py
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from typing import Any


DEFAULT_COLLECTION = "andritz-notices-techniques-spl-pilot"
DEFAULT_CATALOGUE_QUERY = "De quelles donnees disposes-tu ?"
DEFAULT_SCOPED_CATALOGUE_QUERY = "Quels fichiers ACJ100 as-tu dans cette collection ?"
DEFAULT_CONTENT_QUERY = "Analyse les procedures de securite SPL"
DEFAULT_MODES = ("auto", "hybrid", "hah", "chah")


@dataclass
class ProbeCheck:
    label: str
    passed: bool
    required: bool = True
    details: dict[str, Any] | None = None


def _api_base(host: str) -> str:
    base = host.rstrip("/")
    if not base.endswith("/api/v1"):
        base = f"{base}/api/v1"
    return base


def _json_request(
    *,
    api_base: str,
    method: str,
    path: str,
    token: str | None = None,
    workspace_slug: str | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 12.0,
) -> tuple[int, Any, str]:
    url = path if path.startswith("http") else f"{api_base}/{path.lstrip('/')}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if workspace_slug:
        headers["X-Workspace-Slug"] = workspace_slug
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ctx) as response:
            text = response.read().decode("utf-8", errors="replace")
            return response.status, _decode_json(text), text
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        return exc.code, _decode_json(text), text
    except (urllib.error.URLError, socket.timeout, ssl.SSLError, ConnectionError) as exc:
        return 0, {"error": str(exc)}, str(exc)


def _decode_json(text: str) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text[:1000]}


def _login(args: argparse.Namespace) -> str:
    status, payload, _ = _json_request(
        api_base=args.api_base,
        method="POST",
        path="/auth/login",
        body={
            "email": args.email,
            "password": args.password,
            "workspace_slug": args.workspace_slug,
            "remember_me": False,
        },
        timeout=args.timeout,
    )
    if status != 200 or not isinstance(payload, dict):
        raise SystemExit(f"login failed: HTTP {status} payload={payload!r}")
    token = payload.get("access_token") or payload.get("token")
    if not token:
        raise SystemExit(f"login did not return a token: {payload!r}")
    return str(token)


def _record(
    checks: list[ProbeCheck],
    label: str,
    passed: bool,
    *,
    required: bool = True,
    details: dict[str, Any] | None = None,
) -> None:
    checks.append(ProbeCheck(label=label, passed=bool(passed), required=required, details=details or {}))


def _collection_filter(collection: str) -> dict[str, str]:
    return {"collection_slug": collection}


def _chat_body(
    *,
    query: str,
    collection: str,
    mode: str,
    latency_profile: str = "fast",
    max_tokens: int = 180,
    extra_filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    retrieval_filters = _collection_filter(collection)
    retrieval_filters.update(extra_filters or {})
    return {
        "query": query,
        "stream": False,
        "latency_profile": latency_profile,
        "rag_pipeline_mode": mode,
        "retrieval_filters": retrieval_filters,
        "max_tokens": max_tokens,
        "temperature": 0,
        "top_k": 999,
        "candidate_pool_k": 999,
        "synthesis_k": 999,
        "source_display_k": 999,
    }


def _get_diagnostics(args: argparse.Namespace, token: str) -> tuple[int, Any]:
    return _json_request(
        api_base=args.api_base,
        method="GET",
        path=f"/documents/collections/{urllib.parse.quote(args.collection)}/diagnostics",
        token=token,
        workspace_slug=args.workspace_slug,
        timeout=args.timeout,
    )[:2]


def _get_inventory(args: argparse.Namespace, token: str, *, params: dict[str, Any] | None = None) -> tuple[int, Any]:
    query = urllib.parse.urlencode({key: value for key, value in (params or {}).items() if value not in (None, "")})
    suffix = f"?{query}" if query else ""
    return _json_request(
        api_base=args.api_base,
        method="GET",
        path=f"/documents/collections/{urllib.parse.quote(args.collection)}/inventory{suffix}",
        token=token,
        workspace_slug=args.workspace_slug,
        timeout=args.timeout,
    )[:2]


def _plan_preview(
    args: argparse.Namespace,
    token: str,
    *,
    query: str,
    mode: str,
    extra_filters: dict[str, Any] | None = None,
) -> tuple[int, Any, int]:
    started = time.time()
    status, payload, _ = _json_request(
        api_base=args.api_base,
        method="POST",
        path="/chat/retrieval-plan-preview",
        token=token,
        workspace_slug=args.workspace_slug,
        body=_chat_body(
            query=query,
            collection=args.collection,
            mode=mode,
            max_tokens=args.max_tokens,
            extra_filters=extra_filters,
        ),
        timeout=args.timeout,
    )
    return status, payload, int((time.time() - started) * 1000)


def _run_chat(args: argparse.Namespace, token: str, *, query: str, mode: str) -> tuple[int, Any, int]:
    started = time.time()
    status, payload, _ = _json_request(
        api_base=args.api_base,
        method="POST",
        path="/chat/completion",
        token=token,
        workspace_slug=args.workspace_slug,
        body=_chat_body(query=query, collection=args.collection, mode=mode, max_tokens=args.max_tokens),
        timeout=max(args.timeout, args.fast_budget_seconds + 4.0),
    )
    return status, payload, int((time.time() - started) * 1000)


def _stream_chat(args: argparse.Namespace, token: str, *, query: str, mode: str) -> tuple[int, dict[str, Any], int]:
    started = time.time()
    body = _chat_body(query=query, collection=args.collection, mode=mode, max_tokens=args.max_tokens)
    body["stream"] = True
    url = f"{args.api_base}/chat/stream"
    data = json.dumps(body).encode("utf-8")
    headers = {
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "X-Workspace-Slug": args.workspace_slug,
    }
    request = urllib.request.Request(url, data=data, method="POST", headers=headers)
    ctx = ssl.create_default_context()
    first_event_ms: int | None = None
    first_text_ms: int | None = None
    first_retrieval_ms: int | None = None
    done = False
    timed_out = False
    stream_deadline_exceeded = False
    retrieval_details: dict[str, Any] = {}
    event_counts: dict[str, int] = {}
    sample_events: list[dict[str, Any]] = []
    status = 0
    try:
        with urllib.request.urlopen(
            request,
            timeout=max(args.timeout, args.stream_budget_seconds + 4.0),
            context=ctx,
        ) as response:
            status = int(response.status)
            for raw_line in response:
                elapsed_ms = int((time.time() - started) * 1000)
                if elapsed_ms > int(args.stream_budget_seconds * 1000):
                    stream_deadline_exceeded = True
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data_text = line[5:].strip()
                if data_text == "[DONE]":
                    done = True
                    break
                payload = _decode_json(data_text)
                if not isinstance(payload, dict):
                    continue
                if first_event_ms is None:
                    first_event_ms = elapsed_ms
                chunk_type = str(payload.get("chunk_type") or "unknown")
                event_counts[chunk_type] = event_counts.get(chunk_type, 0) + 1
                if len(sample_events) < 12:
                    sample_events.append(
                        {
                            "elapsed_ms": elapsed_ms,
                            "chunk_type": chunk_type,
                            "phase": payload.get("phase"),
                            "code": payload.get("code"),
                        }
                    )
                if chunk_type == "retrieval":
                    if first_retrieval_ms is None:
                        first_retrieval_ms = elapsed_ms
                    details = payload.get("details")
                    if isinstance(details, dict):
                        for key in (
                            "dense_policy",
                            "fallback_reason",
                            "retrieval_fallback",
                            "retrieval_scope",
                            "scope_confidence",
                            "scope_reason",
                            "latency_budget",
                            "deep_job_id",
                            "deep_status",
                        ):
                            if details.get(key) is not None:
                                retrieval_details[key] = details.get(key)
                elif chunk_type == "text" and payload.get("content") and first_text_ms is None:
                    first_text_ms = elapsed_ms
                elif chunk_type == "error":
                    timed_out = timed_out or payload.get("code") == "CHAT_STREAM_TIMEOUT"
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        text = exc.read().decode("utf-8", errors="replace")
        return status, {"error": _decode_json(text), "raw": text[:1000]}, int((time.time() - started) * 1000)
    except (urllib.error.URLError, socket.timeout, ssl.SSLError, ConnectionError) as exc:
        return 0, {"error": str(exc)}, int((time.time() - started) * 1000)

    elapsed_ms = int((time.time() - started) * 1000)
    return (
        status,
        {
            "done": done,
            "chat_stream_timeout": timed_out,
            "stream_deadline_exceeded": stream_deadline_exceeded,
            "first_event_ms": first_event_ms,
            "first_retrieval_ms": first_retrieval_ms,
            "first_text_ms": first_text_ms,
            "elapsed_ms": elapsed_ms,
            "event_counts": event_counts,
            "retrieval_details": retrieval_details,
            "sample_events": sample_events,
        },
        elapsed_ms,
    )


def _dry_run_artifact_job(args: argparse.Namespace, token: str, kind: str) -> tuple[int, Any]:
    return _json_request(
        api_base=args.api_base,
        method="POST",
        path=f"/documents/collections/{urllib.parse.quote(args.collection)}/retrieval-artifact-jobs",
        token=token,
        workspace_slug=args.workspace_slug,
        body={"kind": kind, "dry_run": True},
        timeout=args.timeout,
    )[:2]


def _create_deep_job(args: argparse.Namespace, token: str) -> tuple[int, Any, int]:
    started = time.time()
    body = _chat_body(
        query=args.content_query,
        collection=args.collection,
        mode=args.deep_mode,
        latency_profile="deep",
        max_tokens=args.max_tokens,
    )
    body["deep_retrieval"] = True
    status, payload, _ = _json_request(
        api_base=args.api_base,
        method="POST",
        path="/chat/deep-retrieval-jobs",
        token=token,
        workspace_slug=args.workspace_slug,
        body=body,
        timeout=args.timeout,
    )
    return status, payload, int((time.time() - started) * 1000)


def _check_diagnostics(checks: list[ProbeCheck], status: int, payload: Any, args: argparse.Namespace) -> None:
    is_dict = isinstance(payload, dict)
    _record(checks, "diagnostics_http_200", status == 200 and is_dict, details={"status": status})
    if not is_dict:
        return
    dense = bool(payload.get("dense"))
    _record(
        checks,
        "collection_is_dense",
        dense if args.expect_dense else True,
        details={
            "dense": dense,
            "ledger_source_count": payload.get("ledger_source_count"),
            "ledger_chunk_sum": payload.get("ledger_chunk_sum"),
            "vector_points": payload.get("vector_points"),
        },
    )
    feature_status = payload.get("feature_status") if isinstance(payload.get("feature_status"), dict) else {}
    _record(
        checks,
        "diagnostics_exposes_feature_status",
        bool(feature_status),
        details={"feature_status_keys": sorted(feature_status.keys()) if feature_status else []},
    )


def _check_scoped_inventory(checks: list[ProbeCheck], status: int, payload: Any, args: argparse.Namespace) -> None:
    is_dict = isinstance(payload, dict)
    _record(checks, "scoped_inventory_http_200", status == 200 and is_dict, details={"status": status})
    if not is_dict:
        return
    source_count = int(payload.get("source_count") or 0)
    sources_total = int(payload.get("sources_total") or 0)
    filters = payload.get("source_filters") if isinstance(payload.get("source_filters"), dict) else {}
    _record(
        checks,
        "scoped_inventory_filter_applied",
        filters.get("project_code") == args.scope_project_code
        and source_count > 0
        and 0 < sources_total <= source_count,
        details={
            "source_count": source_count,
            "sources_total": sources_total,
            "source_filters": filters,
        },
    )


def _check_plan(
    checks: list[ProbeCheck],
    *,
    label: str,
    status: int,
    payload: Any,
    elapsed_ms: int,
    expected_policy: set[str],
    args: argparse.Namespace,
) -> None:
    is_dict = isinstance(payload, dict)
    _record(checks, f"{label}_plan_http_200", status == 200 and is_dict, details={"status": status, "elapsed_ms": elapsed_ms})
    if not is_dict:
        return
    budget = payload.get("latency_budget") if isinstance(payload.get("latency_budget"), dict) else {}
    plan = payload.get("retrieval_plan") if isinstance(payload.get("retrieval_plan"), dict) else {}
    guardrails = plan.get("guardrails") if isinstance(plan.get("guardrails"), dict) else {}
    layers = plan.get("layers") if isinstance(plan.get("layers"), dict) else {}
    dense_qdrant = layers.get("dense_qdrant") if isinstance(layers.get("dense_qdrant"), dict) else {}
    hah_chah = layers.get("hah_chah") if isinstance(layers.get("hah_chah"), dict) else {}
    sparse = layers.get("sparse") if isinstance(layers.get("sparse"), dict) else {}
    dense_policy = str(payload.get("dense_policy") or "")
    _record(
        checks,
        f"{label}_policy_safe",
        dense_policy in expected_policy,
        details={"dense_policy": dense_policy, "expected": sorted(expected_policy)},
    )
    _record(
        checks,
        f"{label}_candidate_pool_bounded",
        int(payload.get("candidate_pool_k") or budget.get("candidate_pool_k") or 0) <= 20,
        details={"candidate_pool_k": payload.get("candidate_pool_k"), "latency_budget": budget},
    )
    _record(
        checks,
        f"{label}_no_user_scope_gate",
        guardrails.get("user_scope_required") is False,
        details={"guardrails": guardrails},
    )
    _record(
        checks,
        f"{label}_no_global_chunk_search",
        guardrails.get("global_chunk_search_allowed") is False or dense_policy == "catalogue_inventory",
        details={"guardrails": guardrails, "dense_qdrant": dense_qdrant},
    )
    _record(
        checks,
        f"{label}_no_hah_chah_fanout_in_fast",
        hah_chah.get("enabled") is False or payload.get("latency_profile") != "fast",
        details={"hah_chah": hah_chah, "sparse": sparse},
    )
    scope = payload.get("retrieval_scope") if isinstance(payload.get("retrieval_scope"), dict) else {}
    filters = scope.get("filters") if isinstance(scope.get("filters"), dict) else {}
    if label == "catalogue_scoped":
        _record(
            checks,
            "catalogue_scoped_filter_visible",
            filters.get("project_code") == args.scope_project_code,
            details={"retrieval_scope": scope},
        )
    _record(
        checks,
        f"{label}_preview_fast",
        elapsed_ms <= int(args.preview_budget_ms),
        required=False,
        details={"elapsed_ms": elapsed_ms, "budget_ms": args.preview_budget_ms},
    )


def _check_chat(
    checks: list[ProbeCheck],
    *,
    label: str,
    status: int,
    payload: Any,
    elapsed_ms: int,
    args: argparse.Namespace,
) -> None:
    is_dict = isinstance(payload, dict)
    _record(checks, f"{label}_chat_http_200", status == 200 and is_dict, details={"status": status, "elapsed_ms": elapsed_ms})
    if not is_dict:
        return
    budget = payload.get("latency_budget") if isinstance(payload.get("latency_budget"), dict) else {}
    _record(
        checks,
        f"{label}_chat_under_fast_budget",
        elapsed_ms <= int(args.fast_budget_seconds * 1000),
        details={"elapsed_ms": elapsed_ms, "budget_seconds": args.fast_budget_seconds},
    )
    _record(
        checks,
        f"{label}_chat_candidate_pool_bounded",
        int(budget.get("candidate_pool_k") or 0) <= 20,
        details={"latency_budget": budget},
    )
    _record(
        checks,
        f"{label}_chat_policy_visible",
        bool(payload.get("dense_policy")),
        details={"dense_policy": payload.get("dense_policy"), "scope_confidence": payload.get("scope_confidence")},
    )


def _check_stream(
    checks: list[ProbeCheck],
    *,
    label: str,
    status: int,
    payload: Any,
    elapsed_ms: int,
    args: argparse.Namespace,
) -> None:
    is_dict = isinstance(payload, dict)
    _record(checks, f"{label}_stream_http_200", status == 200 and is_dict, details={"status": status, "elapsed_ms": elapsed_ms})
    if not is_dict:
        return
    retrieval_details = payload.get("retrieval_details") if isinstance(payload.get("retrieval_details"), dict) else {}
    event_counts = payload.get("event_counts") if isinstance(payload.get("event_counts"), dict) else {}
    saw_retrieval = int(event_counts.get("retrieval") or 0) > 0
    latency_budget = retrieval_details.get("latency_budget") if isinstance(retrieval_details.get("latency_budget"), dict) else {}
    first_event_ms = payload.get("first_event_ms")
    first_retrieval_ms = payload.get("first_retrieval_ms")
    first_text_ms = payload.get("first_text_ms")
    fast_budget_ms = int(args.fast_budget_seconds * 1000)
    _record(
        checks,
        f"{label}_stream_no_chat_timeout",
        payload.get("chat_stream_timeout") is False,
        details={"sample_events": payload.get("sample_events")},
    )
    _record(
        checks,
        f"{label}_stream_done",
        payload.get("done") is True and payload.get("stream_deadline_exceeded") is False,
        details={
            "done": payload.get("done"),
            "stream_deadline_exceeded": payload.get("stream_deadline_exceeded"),
            "elapsed_ms": elapsed_ms,
            "stream_budget_seconds": args.stream_budget_seconds,
        },
    )
    _record(
        checks,
        f"{label}_stream_first_event_fast",
        isinstance(first_event_ms, int) and first_event_ms <= fast_budget_ms,
        details={"first_event_ms": first_event_ms, "budget_ms": fast_budget_ms},
    )
    _record(
        checks,
        f"{label}_stream_retrieval_fast",
        first_retrieval_ms is None or (isinstance(first_retrieval_ms, int) and first_retrieval_ms <= fast_budget_ms),
        details={"first_retrieval_ms": first_retrieval_ms, "budget_ms": fast_budget_ms},
    )
    _record(
        checks,
        f"{label}_stream_first_text_fast",
        isinstance(first_text_ms, int) and first_text_ms <= fast_budget_ms,
        details={"first_text_ms": first_text_ms, "budget_ms": fast_budget_ms},
    )
    _record(
        checks,
        f"{label}_stream_candidate_pool_bounded",
        int(latency_budget.get("candidate_pool_k") or 0) <= 20 if saw_retrieval else True,
        details={"latency_budget": latency_budget, "event_counts": event_counts},
    )
    _record(
        checks,
        f"{label}_stream_policy_visible",
        bool(retrieval_details.get("dense_policy")) if saw_retrieval else True,
        details={"retrieval_details": retrieval_details, "event_counts": event_counts},
    )


def _write_report(args: argparse.Namespace, report: dict[str, Any]) -> None:
    if not args.output:
        return
    directory = os.path.dirname(args.output)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2, default=str)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host",
        default=os.environ.get("AGENTIUM_HOST") or os.environ.get("AGENTIUM_BASE_URL", "https://agentium.papai.ai"),
    )
    parser.add_argument("--workspace-slug", default=os.environ.get("WORKSPACE_SLUG", "andritz"))
    parser.add_argument("--token", default=os.environ.get("AGENTIUM_TOKEN", ""))
    parser.add_argument("--email", default=os.environ.get("AGENTIUM_EMAIL", ""))
    parser.add_argument("--password", default=os.environ.get("AGENTIUM_PASSWORD", ""))
    parser.add_argument("--collection", default=os.environ.get("SPL_COLLECTION", DEFAULT_COLLECTION))
    parser.add_argument("--catalogue-query", default=os.environ.get("PROBE_CATALOGUE_QUERY", DEFAULT_CATALOGUE_QUERY))
    parser.add_argument(
        "--scoped-catalogue-query",
        default=os.environ.get("PROBE_SCOPED_CATALOGUE_QUERY", DEFAULT_SCOPED_CATALOGUE_QUERY),
    )
    parser.add_argument("--scope-project-code", default=os.environ.get("PROBE_SCOPE_PROJECT_CODE", "ACJ100"))
    parser.add_argument("--content-query", default=os.environ.get("PROBE_CONTENT_QUERY", DEFAULT_CONTENT_QUERY))
    parser.add_argument("--modes", default=os.environ.get("PROBE_MODES", ",".join(DEFAULT_MODES)))
    parser.add_argument("--deep-mode", default=os.environ.get("PROBE_DEEP_MODE", "chah"))
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("PROBE_TIMEOUT", "12.0")))
    parser.add_argument("--fast-budget-seconds", type=float, default=float(os.environ.get("PROBE_FAST_BUDGET_SECONDS", "8.0")))
    parser.add_argument("--stream-budget-seconds", type=float, default=float(os.environ.get("PROBE_STREAM_BUDGET_SECONDS", "30.0")))
    parser.add_argument("--preview-budget-ms", type=int, default=int(os.environ.get("PROBE_PREVIEW_BUDGET_MS", "1500")))
    parser.add_argument("--max-tokens", type=int, default=int(os.environ.get("PROBE_MAX_TOKENS", "180")))
    parser.add_argument("--output", default=os.environ.get("PROBE_OUTPUT", "/private/tmp/spl-retrieval-scaling-probe.json"))
    parser.add_argument("--run-chat", action="store_true", default=os.environ.get("PROBE_RUN_CHAT", "0") == "1")
    parser.add_argument("--run-stream", action="store_true", default=os.environ.get("PROBE_RUN_STREAM", "0") == "1")
    parser.add_argument("--create-deep-job", action="store_true", default=os.environ.get("PROBE_CREATE_DEEP_JOB", "0") == "1")
    parser.add_argument("--expect-dense", action="store_true", default=os.environ.get("PROBE_EXPECT_DENSE", "1") != "0")
    args = parser.parse_args(argv)
    args.api_base = _api_base(args.host)
    args.modes_list = [mode.strip().lower() for mode in args.modes.split(",") if mode.strip()]
    if not args.token and (not args.email or not args.password):
        raise SystemExit("Provide AGENTIUM_TOKEN or both AGENTIUM_EMAIL and AGENTIUM_PASSWORD")
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    token = str(args.token or "").strip() or _login(args)
    checks: list[ProbeCheck] = []
    artifacts: dict[str, Any] = {}

    diag_status, diagnostics = _get_diagnostics(args, token)
    artifacts["diagnostics"] = diagnostics
    _check_diagnostics(checks, diag_status, diagnostics, args)

    inventory_status, inventory = _get_inventory(
        args,
        token,
        params={"project_code": args.scope_project_code, "source_limit": 20, "sort": "chunk_count", "sort_dir": "desc"},
    )
    artifacts["scoped_inventory"] = inventory
    _check_scoped_inventory(checks, inventory_status, inventory, args)

    cat_status, cat_plan, cat_elapsed = _plan_preview(
        args,
        token,
        query=args.catalogue_query,
        mode="auto",
    )
    artifacts["catalogue_plan"] = cat_plan
    _check_plan(
        checks,
        label="catalogue",
        status=cat_status,
        payload=cat_plan,
        elapsed_ms=cat_elapsed,
        expected_policy={"catalogue_inventory"},
        args=args,
    )

    scoped_cat_status, scoped_cat_plan, scoped_cat_elapsed = _plan_preview(
        args,
        token,
        query=args.scoped_catalogue_query,
        mode="auto",
        extra_filters={"project_code": args.scope_project_code},
    )
    artifacts["catalogue_scoped_plan"] = scoped_cat_plan
    _check_plan(
        checks,
        label="catalogue_scoped",
        status=scoped_cat_status,
        payload=scoped_cat_plan,
        elapsed_ms=scoped_cat_elapsed,
        expected_policy={"catalogue_inventory"},
        args=args,
    )

    mode_plans: dict[str, Any] = {}
    for mode in args.modes_list:
        status, payload, elapsed = _plan_preview(args, token, query=args.content_query, mode=mode)
        mode_plans[mode] = payload
        _check_plan(
            checks,
            label=f"quick_{mode}",
            status=status,
            payload=payload,
            elapsed_ms=elapsed,
            expected_policy={"fast_scoped_dense_auto", "fast_scoped_dense"},
            args=args,
        )
    artifacts["mode_plans"] = mode_plans

    artifact_dry_runs: dict[str, Any] = {}
    for kind in ("summary_index_rebuild", "sparse_index_rebuild", "qdrant_sparse_reindex"):
        status, payload = _dry_run_artifact_job(args, token, kind)
        artifact_dry_runs[kind] = payload
        _record(
            checks,
            f"artifact_{kind}_dry_run",
            status == 200 and isinstance(payload, dict) and payload.get("status") == "dry_run",
            details={"status": status, "payload": payload if isinstance(payload, dict) else None},
        )
    artifacts["artifact_dry_runs"] = artifact_dry_runs

    if args.run_chat:
        chat_runs: dict[str, Any] = {}
        for mode in args.modes_list:
            status, payload, elapsed = _run_chat(args, token, query=args.content_query, mode=mode)
            chat_runs[mode] = {"status": status, "elapsed_ms": elapsed, "payload": payload}
            _check_chat(checks, label=f"quick_{mode}", status=status, payload=payload, elapsed_ms=elapsed, args=args)
        artifacts["chat_runs"] = chat_runs

    if args.run_stream:
        stream_runs: dict[str, Any] = {}
        for mode in args.modes_list:
            status, payload, elapsed = _stream_chat(args, token, query=args.content_query, mode=mode)
            stream_runs[mode] = {"status": status, "elapsed_ms": elapsed, "payload": payload}
            _check_stream(checks, label=f"quick_{mode}", status=status, payload=payload, elapsed_ms=elapsed, args=args)
        artifacts["stream_runs"] = stream_runs

    if args.create_deep_job:
        status, payload, elapsed = _create_deep_job(args, token)
        artifacts["deep_job"] = payload
        _record(
            checks,
            "deep_job_created",
            status == 200 and isinstance(payload, dict) and payload.get("kind") == "rag_deep_retrieval",
            details={"status": status, "elapsed_ms": elapsed, "poll_url": payload.get("poll_url") if isinstance(payload, dict) else None},
        )

    failed_required = [check for check in checks if check.required and not check.passed]
    failed_optional = [check for check in checks if not check.required and not check.passed]
    report = {
        "target": {
            "host": args.host,
            "workspace_slug": args.workspace_slug,
            "collection": args.collection,
            "modes": args.modes_list,
            "run_chat": args.run_chat,
            "run_stream": args.run_stream,
            "create_deep_job": args.create_deep_job,
        },
        "summary": {
            "passed": len(checks) - len(failed_required) - len(failed_optional),
            "failed_required": len(failed_required),
            "failed_optional": len(failed_optional),
            "total": len(checks),
        },
        "checks": [asdict(check) for check in checks],
        "artifacts": artifacts,
    }
    _write_report(args, report)

    for check in checks:
        prefix = "PASS" if check.passed else ("WARN" if not check.required else "FAIL")
        detail = f" {json.dumps(check.details, ensure_ascii=False, default=str)}" if check.details else ""
        print(f"[{prefix}] {check.label}{detail}")
    if args.output:
        print(f"[INFO] wrote {args.output}")
    return 1 if failed_required else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
