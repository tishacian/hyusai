"""Run retrieval golden cases against the live RAG stack.

This is intentionally retrieval-only: it validates selected sources and
evidence terms, never generated answer prose. Run from the backend container:

    python -m scripts.run_retrieval_golden_live --workspace andritz --batch andritz_spl_dense.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from app.db.base import SessionLocal
from app.models.workspace import Workspace
from app.services.rag.context import retrieve_rag_context
from app.services.rag.retrieval_golden import (
    evaluate_retrieval_golden_case,
    load_retrieval_golden_cases,
)

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "app" / "resources" / "retrieval_golden"


def _batch_path(name: str) -> Path:
    path = Path(name)
    if path.exists():
        return path
    return GOLDEN_DIR / name


def _workspace(slug: str) -> Workspace:
    db = SessionLocal()
    try:
        workspace = db.query(Workspace).filter(Workspace.slug == slug).first()
        if not workspace:
            raise SystemExit(f"Workspace not found: {slug}")
        return workspace
    finally:
        db.close()


def _latency_profile(metrics: dict[str, Any]) -> Any:
    if metrics.get("latency_profile"):
        return metrics.get("latency_profile")
    budget = metrics.get("latency_budget")
    if isinstance(budget, dict):
        return budget.get("profile")
    return None


async def _run_case(case, *, workspace: Workspace, timeout: float, source_policy: dict[str, Any]) -> dict[str, Any]:
    request = case.to_request()
    request.update(
        {
            "workspace_id": workspace.id,
            "workspace_slug": workspace.slug,
            "retrieval_profile": request.get("retrieval_profile") or "chat",
            "source_policy": source_policy,
        }
    )
    started = time.perf_counter()
    try:
        context = await asyncio.wait_for(retrieve_rag_context(request), timeout=timeout)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        result = evaluate_retrieval_golden_case(case, context)
        metrics = context.get("metrics") if isinstance(context.get("metrics"), dict) else {}
        result.update(
            {
                "elapsed_ms": elapsed_ms,
                "latency_profile": case.latency_profile,
                "collection": case.collection,
                "pipeline": context.get("pipeline"),
                "chunks": len(context.get("chunks") or []),
                "sparse_status": metrics.get("sparse_status"),
                "sparse_backend": metrics.get("sparse_backend"),
                "sparse_fallback_reason": metrics.get("sparse_fallback_reason"),
                "cross_encoder_status": metrics.get("cross_encoder_status"),
                "cross_encoder_ms": metrics.get("cross_encoder_ms"),
                "retrieval_latency_profile": _latency_profile(metrics),
            }
        )
        return result
    except Exception as exc:  # noqa: BLE001 - report every case, keep the batch moving.
        return {
            "id": case.id,
            "language": case.language,
            "passed": False,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "latency_profile": case.latency_profile,
            "collection": case.collection,
            "error": f"{type(exc).__name__}: {exc}",
        }


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    workspace = _workspace(args.workspace)
    source_policy = {"reject_cross_project_sources": not args.allow_cross_project_sources}
    cases = []
    for batch in args.batch:
        for case in load_retrieval_golden_cases(_batch_path(batch)):
            cases.append((batch, case))
    if args.limit:
        cases = cases[: args.limit]

    results = []
    started = time.perf_counter()
    for index, (batch, case) in enumerate(cases, start=1):
        result = await _run_case(
            case,
            workspace=workspace,
            timeout=float(args.case_timeout),
            source_policy=source_policy,
        )
        result["batch"] = batch
        results.append(result)
        status = "PASS" if result.get("passed") else "FAIL"
        print(f"[{index:03d}/{len(cases):03d}] {status} {case.id} {result.get('elapsed_ms')}ms", flush=True)

    passed = sum(1 for item in results if item.get("passed"))
    summary = {
        "workspace": workspace.slug,
        "batches": args.batch,
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": round((passed / len(results)) * 100.0, 2) if results else 0.0,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "results": results,
    }
    if args.output:
        Path(args.output).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default="andritz", help="Workspace slug")
    parser.add_argument("--batch", action="append", default=None, help="Golden batch filename/path")
    parser.add_argument("--limit", type=int, default=0, help="Optional first-N case limit")
    parser.add_argument("--case-timeout", type=float, default=90.0, help="Seconds per case")
    parser.add_argument("--output", default="", help="Write JSON report to this path")
    parser.add_argument(
        "--allow-cross-project-sources",
        action="store_true",
        help="Disable the chat source_policy cross-project guard for this probe",
    )
    args = parser.parse_args()
    if not args.batch:
        args.batch = ["andritz_spl_dense.json"]
    summary = asyncio.run(_run(args))
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
