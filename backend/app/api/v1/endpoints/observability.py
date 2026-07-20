"""Workspace observability endpoints."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_workspace
from app.db.base import get_db
from app.models.evaluation import EvaluationScore
from app.models.run import Run
from app.models.system import System
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services.evaluation_preset_service import DEFAULT_EVAL_CONFIG

router = APIRouter()


@router.get("/workspace-overview")
async def workspace_overview(
    window: str = Query("24h"),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    since = _parse_window(window)
    systems = (
        db.query(System)
        .filter(System.workspace_id == workspace.id)
        .order_by(System.status.desc(), System.updated_at.desc())
        .all()
    )
    runs = (
        db.query(Run)
        .filter(
            Run.workspace_id == workspace.id,
            or_(Run.started_at >= since, Run.completed_at >= since),
        )
        .order_by(Run.started_at.desc())
        .limit(200)
        .all()
    )
    jobs = (
        db.query(WorkspaceJob)
        .filter(
            WorkspaceJob.workspace_id == workspace.id,
            or_(WorkspaceJob.updated_at >= since, WorkspaceJob.created_at >= since),
        )
        .order_by(WorkspaceJob.updated_at.desc(), WorkspaceJob.created_at.desc())
        .limit(100)
        .all()
    )
    evaluations = (
        db.query(EvaluationScore)
        .filter(EvaluationScore.workspace_id == workspace.id, EvaluationScore.created_at >= since)
        .order_by(EvaluationScore.created_at.desc())
        .limit(100)
        .all()
    )

    system_rows = [_system_row(system, runs) for system in systems]
    job_rows = [_job_row(job) for job in jobs[:30]]
    retrieval_decisions = _retrieval_decision_summary(runs)
    alerts = _alerts(runs, jobs, evaluations)
    return {
        "window": window,
        "since": since.isoformat(),
        "generated_at": datetime.utcnow().isoformat(),
        "workspace": {
            "id": workspace.id,
            "slug": workspace.slug,
            "name": workspace.name,
        },
        "summary": {
            "active_systems": sum(1 for s in systems if (s.status or "") == "active"),
            "runs_total": len(runs),
            "runs_completed": sum(1 for r in runs if r.status == "completed"),
            "runs_failed": sum(1 for r in runs if r.status == "failed"),
            "runs_running": sum(
                1
                for r in runs
                if r.status in {"pending", "running", "hitl_pending", "debug_pending", "waiting_subflows"}
            ),
            "avg_latency_ms": _avg([r.duration_ms for r in runs if r.duration_ms is not None]),
            "p95_latency_ms": _p95([r.duration_ms for r in runs if r.duration_ms is not None]),
            "jobs_total": len(jobs),
            "jobs_active": sum(1 for j in jobs if j.status in {"created", "queued", "running"}),
            "jobs_failed": sum(1 for j in jobs if j.status == "failed"),
            "evaluations_total": len(evaluations),
            "alerts_total": len(alerts),
            "retrieval_traces_total": retrieval_decisions["total"],
            "retrieval_traces_missing": retrieval_decisions["missing"],
            "sparse_timeouts": retrieval_decisions["quality"]["sparse_timeouts"],
            "sparse_fallbacks": retrieval_decisions["quality"]["sparse_fallbacks"],
            "cross_encoder_issues": retrieval_decisions["quality"]["cross_encoder_issues"],
            "deep_recommended": retrieval_decisions["quality"]["deep_recommended"],
            "deep_launched": retrieval_decisions["quality"]["deep_launched"],
        },
        "retrieval_decisions": retrieval_decisions,
        "systems": system_rows,
        "jobs": job_rows,
        "evaluations": _evaluation_summary(evaluations),
        "alerts": alerts[:20],
        "timeline": _timeline(runs, jobs, evaluations)[:40],
    }


def _parse_window(raw: str) -> datetime:
    value = (raw or "24h").strip().lower()
    now = datetime.utcnow()
    try:
        if value.endswith("h"):
            return now - timedelta(hours=max(1, min(24 * 14, int(value[:-1]))))
        if value.endswith("d"):
            return now - timedelta(days=max(1, min(90, int(value[:-1]))))
    except ValueError:
        pass
    return now - timedelta(hours=24)


def _system_row(system: System, runs: list[Run]) -> dict[str, Any]:
    related = [r for r in runs if r.system_id == system.id]
    latest = related[0] if related else None
    settings = system.settings or {}
    return {
        "id": system.id,
        "name": system.name,
        "status": system.status,
        "capability_id": system.capability_id,
        "surface": settings.get("surface"),
        "system_type": settings.get("system_type"),
        "route": "/chat" if settings.get("surface") == "chat" else f"/systems/{system.id}",
        "runs_total": len(related),
        "runs_completed": sum(1 for r in related if r.status == "completed"),
        "runs_failed": sum(1 for r in related if r.status == "failed"),
        "avg_latency_ms": _avg([r.duration_ms for r in related if r.duration_ms is not None]),
        "latest_run_id": latest.id if latest else None,
        "latest_run_status": latest.status if latest else None,
        "latest_run_at": _time(latest.started_at if latest else None),
    }


def _job_row(job: WorkspaceJob) -> dict[str, Any]:
    route = "/observability"
    if job.kind == "sftp_reconciliation":
        route = "/connectors/sftp"
    elif job.run_id:
        route = f"/runs/{job.run_id}"
    elif job.system_id:
        route = f"/systems/{job.system_id}"
    elif job.kind == "rag_deep_retrieval":
        route = "/chat"
    return {
        "id": job.id,
        "kind": job.kind,
        "title": job.title,
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "error": job.error,
        "system_id": job.system_id,
        "run_id": job.run_id,
        "route": route,
        "created_at": _time(job.created_at),
        "updated_at": _time(job.updated_at),
    }


def _evaluation_summary(rows: list[EvaluationScore]) -> dict[str, Any]:
    thresholds = DEFAULT_EVAL_CONFIG
    breaches = [_evaluation_breached(row, thresholds) for row in rows]
    latest = rows[0] if rows else None
    return {
        "total": len(rows),
        "avg_composite": _avg(
            [row.composite_score for row in rows if row.composite_score is not None]
        ),
        "avg_hallucination_rate": _avg(
            [row.hallucination_rate for row in rows if row.hallucination_rate is not None]
        ),
        "breaches": sum(1 for item in breaches if item),
        "latest": _evaluation_row(latest) if latest else None,
        "thresholds": {
            "composite_min": thresholds.get("composite_min"),
            "hallucination_max": thresholds.get("hallucination_max"),
        },
    }


def _retrieval_decision_summary(runs: list[Run]) -> dict[str, Any]:
    routes: Counter[str] = Counter()
    query_types: Counter[str] = Counter()
    sparse_timeouts = 0
    sparse_fallbacks = 0
    cross_encoder_issues = 0
    deep_recommended = 0
    deep_launched = 0
    traced = 0
    missing = 0

    for run in runs:
        trace = _run_retrieval_decision_trace(run)
        if not trace:
            if _run_expects_retrieval_trace(run):
                missing += 1
            continue
        traced += 1
        route = str(trace.get("selected_route") or "unknown")
        query_type = str(trace.get("query_type") or "unknown")
        routes[route] += 1
        query_types[query_type] += 1
        quality = (
            trace.get("quality_controls") if isinstance(trace.get("quality_controls"), dict) else {}
        )
        sparse_status = str(quality.get("sparse_status") or "").lower()
        cross_encoder_status = str(quality.get("cross_encoder_status") or "").lower()
        fallbacks = trace.get("fallbacks") if isinstance(trace.get("fallbacks"), list) else []
        if "timeout" in sparse_status:
            sparse_timeouts += 1
        if any(
            "sparse" in str(item.get("kind") or "").lower()
            for item in fallbacks
            if isinstance(item, dict)
        ):
            sparse_fallbacks += 1
        if cross_encoder_status and cross_encoder_status not in {
            "applied",
            "ok",
            "skipped",
            "disabled",
            "not_applicable",
        }:
            cross_encoder_issues += 1
        deep = trace.get("deep_search") if isinstance(trace.get("deep_search"), dict) else {}
        if deep.get("recommended"):
            deep_recommended += 1
        if deep.get("launched"):
            deep_launched += 1

    return {
        "total": traced,
        "missing": missing,
        "routes": [{"route": key, "count": value} for key, value in routes.most_common()],
        "query_types": [
            {"query_type": key, "count": value} for key, value in query_types.most_common()
        ],
        "quality": {
            "sparse_timeouts": sparse_timeouts,
            "sparse_fallbacks": sparse_fallbacks,
            "cross_encoder_issues": cross_encoder_issues,
            "deep_recommended": deep_recommended,
            "deep_launched": deep_launched,
        },
    }


def _run_retrieval_decision_trace(run: Run) -> dict[str, Any] | None:
    output = run.output_ref if isinstance(run.output_ref, dict) else {}
    candidates: list[Any] = [
        output.get("retrieval_decision_trace"),
        (output.get("retrieval_metrics") or {}).get("retrieval_decision_trace")
        if isinstance(output.get("retrieval_metrics"), dict)
        else None,
        (output.get("meta") or {}).get("retrieval_decision_trace")
        if isinstance(output.get("meta"), dict)
        else None,
    ]
    for invocation in getattr(run, "invocations", []) or []:
        for payload in (invocation.metrics, invocation.output_ref, invocation.trace):
            if isinstance(payload, dict):
                candidates.append(payload.get("retrieval_decision_trace"))
                metrics = payload.get("retrieval_metrics")
                if isinstance(metrics, dict):
                    candidates.append(metrics.get("retrieval_decision_trace"))
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return None


def _run_expects_retrieval_trace(run: Run) -> bool:
    if (run.trigger or "") in {"chat", "chat_agentic"}:
        return True
    output = run.output_ref if isinstance(run.output_ref, dict) else {}
    return any(key in output for key in ("retrieval_metrics", "retrieval_scope", "retrieval_plan"))


def _alerts(
    runs: list[Run],
    jobs: list[WorkspaceJob],
    evaluations: list[EvaluationScore],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for run in runs:
        if run.status == "failed":
            out.append(
                _alert(
                    "run_failed",
                    "neg",
                    f"Run failed · {run.error or run.id}",
                    f"/runs/{run.id}",
                    run.started_at,
                )
            )
        if _is_unsourced_chat_run(run):
            out.append(
                _alert(
                    "run_without_sources",
                    "warn",
                    "Chat answer completed without workspace sources",
                    f"/runs/{run.id}",
                    run.started_at,
                )
            )
        trace = _run_retrieval_decision_trace(run)
        if not trace and _run_expects_retrieval_trace(run):
            out.append(
                _alert(
                    "retrieval_trace_missing",
                    "warn",
                    "Retrieval decision trace missing on chat/retrieval run",
                    f"/runs/{run.id}",
                    run.started_at,
                )
            )
        if trace:
            quality = (
                trace.get("quality_controls")
                if isinstance(trace.get("quality_controls"), dict)
                else {}
            )
            sparse_status = str(quality.get("sparse_status") or "").lower()
            cross_encoder_status = str(quality.get("cross_encoder_status") or "").lower()
            if "timeout" in sparse_status:
                out.append(
                    _alert(
                        "sparse_timeout",
                        "warn",
                        "Sparse retrieval timeout; vector fallback used",
                        f"/runs/{run.id}",
                        run.started_at,
                    )
                )
            if cross_encoder_status and cross_encoder_status not in {
                "applied",
                "ok",
                "skipped",
                "disabled",
                "not_applicable",
            }:
                out.append(
                    _alert(
                        "cross_encoder_issue",
                        "warn",
                        f"Cross-encoder status · {cross_encoder_status}",
                        f"/runs/{run.id}",
                        run.started_at,
                    )
                )
    for job in jobs:
        if job.status == "failed":
            route = "/connectors/sftp" if job.kind == "sftp_reconciliation" else "/observability"
            out.append(
                _alert(
                    "job_failed",
                    "neg",
                    f"{job.kind} failed · {job.error or job.title}",
                    route,
                    job.updated_at,
                )
            )
    thresholds = DEFAULT_EVAL_CONFIG
    for row in evaluations:
        if _evaluation_breached(row, thresholds):
            out.append(
                _alert(
                    "evaluation_breach",
                    "warn",
                    f"Evaluation breach · score {_score_label(row.composite_score)}",
                    f"/runs/{row.run_id}" if row.run_id else "/observability/quality",
                    row.created_at,
                )
            )
    return sorted(out, key=lambda item: item.get("timestamp") or "", reverse=True)


def _timeline(
    runs: list[Run],
    jobs: list[WorkspaceJob],
    evaluations: list[EvaluationScore],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for run in runs:
        trace = _run_retrieval_decision_trace(run)
        items.append(
            {
                "id": f"run:{run.id}",
                "kind": "run",
                "tone": _status_tone(run.status),
                "label": f"Run {run.status} · {run.trigger or 'manual'}",
                "timestamp": _time(run.started_at),
                "route": f"/runs/{run.id}",
                "meta": {
                    "duration_ms": run.duration_ms,
                    "system_id": run.system_id,
                    "retrieval_route": trace.get("selected_route") if trace else None,
                    "query_type": trace.get("query_type") if trace else None,
                },
            }
        )
    for job in jobs:
        items.append(
            {
                "id": f"job:{job.id}",
                "kind": "job",
                "tone": _status_tone(job.status),
                "label": f"{job.kind} · {job.status}",
                "timestamp": _time(job.updated_at or job.created_at),
                "route": _job_row(job)["route"],
                "meta": {"stage": job.stage, "progress": job.progress},
            }
        )
    for row in evaluations:
        items.append(
            {
                "id": f"eval:{row.id}",
                "kind": "evaluation",
                "tone": "warn" if _evaluation_breached(row, DEFAULT_EVAL_CONFIG) else "pos",
                "label": f"Evaluation · {_score_label(row.composite_score)}/100",
                "timestamp": _time(row.created_at),
                "route": f"/runs/{row.run_id}" if row.run_id else "/observability/quality",
                "meta": {"hallucination_rate": row.hallucination_rate},
            }
        )
    return sorted(items, key=lambda item: item.get("timestamp") or "", reverse=True)


def _evaluation_row(row: EvaluationScore) -> dict[str, Any]:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "agent_id": row.agent_id,
        "composite_score": row.composite_score,
        "hallucination_rate": row.hallucination_rate,
        "drift_rate": row.drift_rate,
        "question_type": row.question_type,
        "created_at": _time(row.created_at),
    }


def _evaluation_breached(row: EvaluationScore, thresholds: dict[str, Any]) -> bool:
    composite_min = float(thresholds.get("composite_min") or 70.0)
    hallucination_max = float(thresholds.get("hallucination_max") or 0.3)
    return bool(
        (row.composite_score or 0.0) < composite_min
        or (row.hallucination_rate or 0.0) > hallucination_max
    )


def _is_unsourced_chat_run(run: Run) -> bool:
    if (run.trigger or "") not in {"chat", "chat_agentic"} or run.status != "completed":
        return False
    output = run.output_ref if isinstance(run.output_ref, dict) else {}
    if output.get("trivial_bypass"):
        return False
    if (run.trigger or "") == "chat_agentic" and _is_expected_agentic_abstention(output):
        return False
    sources = output.get("sources")
    return isinstance(sources, list) and len(sources) == 0


def _is_expected_agentic_abstention(output: dict[str, Any]) -> bool:
    """Distinguish governed/clarifying terminals from uncited answers."""

    meta = output.get("meta") if isinstance(output.get("meta"), dict) else {}
    route = str(output.get("route") or meta.get("route") or "").strip().lower()
    if route in {
        "agentic_review",
        "agentic_review_rejected",
        "agentic_blocked",
        "agentic_abstain",
    }:
        return True

    action = str(output.get("action") or "").strip().lower()
    if action in {"clarify", "reject_oos"}:
        return True

    answer = str(output.get("answer") or output.get("response") or "").strip()
    clarifying_question = str(output.get("clarifying_question") or "").strip()
    if clarifying_question and (not answer or answer == clarifying_question):
        return True

    oos_reason = str(output.get("oos_reason") or "").strip()
    if oos_reason and (not answer or answer == oos_reason):
        return True
    reason = str(output.get("reason") or "").strip()
    return bool(reason and (not answer or answer == reason))


def _alert(
    kind: str, tone: str, label: str, route: str, timestamp: Optional[datetime]
) -> dict[str, Any]:
    return {
        "id": f"{kind}:{route}:{_time(timestamp)}",
        "kind": kind,
        "tone": tone,
        "label": label[:240],
        "route": route,
        "timestamp": _time(timestamp),
    }


def _score_label(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.1f}"


def _avg(values: list[Optional[float]]) -> Optional[float]:
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return None
    return round(sum(clean) / len(clean), 3)


def _p95(values: list[Optional[float]]) -> Optional[float]:
    clean = sorted(float(v) for v in values if v is not None)
    if not clean:
        return None
    index = min(len(clean) - 1, int(round((len(clean) - 1) * 0.95)))
    return round(clean[index], 3)


def _status_tone(status: Optional[str]) -> str:
    if status in {"completed", "applied"}:
        return "pos"
    if status in {"failed", "cancelled"}:
        return "neg"
    if status in {
        "running", "queued", "pending", "created", "hitl_pending", "debug_pending",
        "waiting_subflows",
    }:
        return "warn"
    return "info"


def _time(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None
