"""Callable wrappers for canonical Skills.

Each wrapper translates a typed canonical-skill input into a real call
against the existing OmniRAG service layer. Wrappers are intentionally
thin — they never introduce new business logic.

Runtime status (returned by `bound_slugs()`) is tri-state:
 - ``bound``     : an actual implementation module is resolvable and will be invoked.
 - ``stub``      : a placeholder that logs + returns a degraded payload (no hard-fail).
 - ``unbound``   : no wrapper declared for that slug (falls through to `_unimplemented`).

The check happens lazily on first use, cached in
``_RESOLVED_STATUS`` so the admin `/skills/runtime-health` endpoint is
cheap to call. Imports of the underlying services stay lazy to avoid
pulling heavy deps at registry introspection time.
"""
from __future__ import annotations

import importlib
import base64
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from app.core.logging import get_logger

logger = get_logger(__name__)

SkillCallable = Callable[[Dict[str, Any], Optional[Dict[str, Any]]], Awaitable[Dict[str, Any]]]


# ---------------------------------------------------------------------------
# Fallbacks
# ---------------------------------------------------------------------------
async def _unimplemented(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    raise NotImplementedError(
        "This canonical skill has no runtime wrapper bound. Add it to `_REGISTRY` in "
        "`skills_registry/wrappers.py` or mark it as a stub."
    )


async def _stub(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Degraded placeholder for skills whose runtime is not yet available."""
    logger.info("skills_registry: stub invocation", payload_keys=list(payload.keys()))
    return {
        "status": "degraded",
        "warning": "runtime_unavailable",
        "input_echo": payload,
    }


# ---------------------------------------------------------------------------
# Concrete wrappers
# ---------------------------------------------------------------------------
async def _llm_rag_answer_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.rag.rag_service import answer

    ctx = ctx or {}
    result = await answer(
        query=payload["query"],
        context_id=payload.get("context_id"),
        workspace_id=ctx.get("workspace_id"),
        session_id=payload.get("session_id"),
        rag_mode_override=(
            payload.get("rag_pipeline_mode")
            or payload.get("rag_mode_override")
            or ctx.get("retrieval_mode_default")
        ),
        prompt_type=payload.get("prompt_type") or ctx.get("default_prompt_type"),
        model=payload.get("model") or ctx.get("default_model"),
        provider=payload.get("provider"),
        # Forward the run-engine sink so the orchestrator's text
        # chunks are rebroadcast as SSE token_delta events in real
        # time (Vague D / D2). Non-streaming callers simply don't pass
        # the sink and observe no behavioural change.
        token_sink=ctx.get("token_sink"),
    )
    return {
        "answer": result.get("answer", ""),
        "citations": result.get("citations", []),
        "decision_steps": result.get("decision_steps", []),
        "meta": result.get("meta", {}),
    }


async def _semantic_search_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.rag.document_service import DocumentService
    from app.services.rag.pipeline_retrieval import retrieve_for_mode

    ctx = ctx or {}
    workspace_slug = ctx.get("workspace_slug")
    doc_svc = DocumentService(workspace_slug=workspace_slug)
    top_k = int(payload.get("top_k", 5))
    mode = payload.get("mode") or "hybrid"
    result = await retrieve_for_mode(
        doc_svc,
        payload["query"],
        mode=mode,
        top_k=top_k,
        use_hybrid=mode != "naive",
    )
    return {
        "results": [
            {"content": c, "score": s} for c, s in zip(result.chunks, result.scores)
        ],
        "pipeline": result.pipeline,
        "label": result.label,
        "reason": result.reason,
        "detail": result.detail,
    }


async def _document_ingestion_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.rag.document_service import DocumentService

    ctx = ctx or {}
    doc_svc = DocumentService(workspace_slug=ctx.get("workspace_slug"))
    file_path = payload.get("file_path") or payload.get("filename")
    if not file_path:
        raise ValueError("document_ingestion_v1: 'file_path' or 'filename' required")
    result = await doc_svc.ingest_document(file_path)
    return {
        "doc_id": result.get("document_id"),
        "chunks": result.get("chunks_processed", 0),
        "status": result.get("status"),
    }


async def _eval_radar_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.evaluation.judge import get_judge_service

    judge = get_judge_service()
    evaluation = await judge.evaluate(
        query=payload.get("query", ""),
        response=payload["answer"],
        system_prompt=payload.get("system_prompt", ""),
        context_chunks=payload.get("context_chunks"),
        turn_number=payload.get("turn_number", 1),
    )
    return {
        "axes": evaluation.get("scores", {}),
        "overall": evaluation.get("composite_score"),
        "hallucination_rate": evaluation.get("hallucination_rate"),
        "drift_rate": evaluation.get("drift_rate"),
        "note": evaluation.get("overall_note"),
    }


async def _claim_audit_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.evaluation.judge import get_judge_service

    judge = get_judge_service()
    evaluation = await judge.evaluate(
        query=payload.get("query", ""),
        response=payload["answer"],
        system_prompt=payload.get("system_prompt", ""),
        context_chunks=payload.get("citations"),
        turn_number=payload.get("turn_number", 1),
    )
    audit = evaluation.get("claim_audit") or {}
    claims = audit.get("claims", [])
    supported = audit.get("supported", 0)
    total = max(1, len(claims))
    verdict = "supported" if supported / total >= 0.8 else "partial" if supported else "unsupported"
    return {
        "claims": claims,
        "verdict": verdict,
        "supported": supported,
        "unsupported": audit.get("unsupported", 0),
    }


async def _intelligence_batch_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.db.base import SessionLocal
    from app.models.workspace import Workspace
    from app.services.intelligence.batch import get_dashboard_data, run_batch
    from app.services.intelligence.knowledge_sync import sync_intelligence_to_knowledge

    ctx = ctx or {}
    ingested = 0
    errors = 0
    events: list[str] = []
    knowledge_sync: dict[str, Any] = {"status": "skipped"}
    target_id = (payload.get("target_id") or (payload.get("feed_ids") or [None])[0])
    async for event in run_batch(
        target_id=target_id,
        workspace_id=ctx.get("workspace_id"),
    ):
        kind = event.get("type") or event.get("status")
        if kind:
            events.append(str(kind))
        if event.get("type") == "article_stored":
            ingested += 1
        if event.get("type") == "error" or event.get("status") == "error":
            errors += 1

    workspace_id = ctx.get("workspace_id") or payload.get("workspace_id")
    if workspace_id:
        db = SessionLocal()
        try:
            workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
            if workspace:
                dashboard = get_dashboard_data(db, workspace_id=workspace.id)
                knowledge_sync = await sync_intelligence_to_knowledge(
                    db,
                    workspace,
                    dashboard_payload=dashboard,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "intelligence_batch_v1.knowledge_sync_failed",
                workspace_id=workspace_id,
                error=str(exc),
            )
            knowledge_sync = {"status": "error", "error": str(exc)}
        finally:
            db.close()
    return {"ingested": ingested, "errors": errors, "events": events, "knowledge_sync": knowledge_sync}


def _workspace_from_context(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Any:
    ctx = ctx or {}
    workspace_id = ctx.get("workspace_id") or payload.get("workspace_id") or "demo-workspace"
    workspace_slug = ctx.get("workspace_slug") or payload.get("workspace_slug") or "workspace"
    workspace_name = payload.get("workspace_name") or workspace_slug
    return SimpleNamespace(id=workspace_id, slug=workspace_slug, name=workspace_name)


async def _ministerial_briefing_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.mission_room import briefing_payload

    workspace = _workspace_from_context(payload, ctx)
    briefing = briefing_payload(workspace)
    return {
        "briefing": briefing,
        "sources": briefing.get("sources", []),
        "status": "ready",
    }


async def _news_signal_synthesis_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.mission_room import news_payload

    workspace = _workspace_from_context(payload, ctx)
    news = news_payload(workspace)
    return {
        "summary": news.get("summary"),
        "signals": news.get("signals", []),
        "sources": news.get("sources", []),
    }


async def _project_risk_explainer_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.mission_room import projects_payload

    workspace = _workspace_from_context(payload, ctx)
    projects = projects_payload(workspace)
    project_id = payload.get("project_id") or payload.get("target_id")
    project = next(
        (item for item in projects.get("projects", []) if item.get("id") == project_id),
        (projects.get("projects") or [None])[0],
    )
    if not project:
        return {"status": "no_project", "project": None, "explanation": {}, "sources": []}
    return {
        "project": project,
        "explanation": {
            "cause": project.get("cause"),
            "risk": project.get("risk"),
            "options": project.get("options", []),
            "advisory_only": True,
        },
        "sources": project.get("sources", []),
    }


async def _territorial_signal_map_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.mission_room import map_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        return map_payload(workspace, db=db)
    finally:
        if owns_db:
            db.close()


async def _scenario_generate_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.scenario_engine import generate_scenarios

    return {
        "options": generate_scenarios(
            target_kind=str(payload.get("target_kind") or "cabinet"),
            target_id=str(payload.get("target_id") or ""),
            risk_level=str(payload.get("risk_level") or "medium"),
            source_refs=list(payload.get("source_refs") or []),
            agenda_pressure=int(payload.get("agenda_pressure") or 0),
            signal_strength=int(payload.get("signal_strength") or 50),
            context=dict(payload.get("context") or {}),
        )
    }


async def _scenario_compare_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.scenario_engine import compare_scenarios

    return compare_scenarios(list(payload.get("options") or []))


async def _scenario_recommend_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.scenario_engine import recommend_scenario

    return recommend_scenario(
        target_kind=str(payload.get("target_kind") or "cabinet"),
        target_id=str(payload.get("target_id") or ""),
        risk_level=str(payload.get("risk_level") or "medium"),
        source_refs=list(payload.get("source_refs") or []),
        agenda_pressure=int(payload.get("agenda_pressure") or 0),
        signal_strength=int(payload.get("signal_strength") or 50),
        context=dict(payload.get("context") or {}),
    )


async def _instruction_draft_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.mission_room import draft_instruction_payload

    ctx = ctx or {}
    workspace = _workspace_from_context(payload, ctx)
    actor = ctx.get("actor") or payload.get("actor") or "system:instruction_draft_v1"
    return draft_instruction_payload(
        workspace=workspace,
        actor=str(actor),
        target_id=payload.get("target_id") or payload.get("project_id") or "proj-health-north",
        target_type=payload.get("target_type") or "project",
        instruction_type=payload.get("instruction_type") or "dircab_instruction",
        db=ctx.get("db"),
    )


def _calendar_db_and_workspace(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> tuple[Any, Any]:
    from app.db.base import SessionLocal
    from app.models.workspace import Workspace

    ctx = ctx or {}
    db = ctx.get("db")
    owns_db = False
    if db is None:
        db = SessionLocal()
        owns_db = True
    workspace_id = ctx.get("workspace_id") or payload.get("workspace_id")
    workspace_slug = ctx.get("workspace_slug") or payload.get("workspace_slug")
    query = db.query(Workspace)
    workspace = None
    if workspace_id:
        workspace = query.filter(Workspace.id == workspace_id).first()
    if workspace is None and workspace_slug:
        workspace = query.filter(Workspace.slug == workspace_slug).first()
    if workspace is None:
        if owns_db:
            db.close()
        raise ValueError("calendar skill requires workspace_id or workspace_slug")
    return db, workspace


async def _calendar_read_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.workspace_calendar import list_events, serialize_event

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        events = list_events(db, workspace, status=payload.get("status"))
        return {"events": [serialize_event(event, workspace=workspace) for event in events], "workspace_id": workspace.id}
    finally:
        if owns_db:
            db.close()


async def _calendar_create_event_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.workspace_calendar import calendar_write_policy, create_event, serialize_event

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        start_at = datetime.fromisoformat(str(payload["start_at"]).replace("Z", "+00:00")).replace(tzinfo=None)
        end_at = (
            datetime.fromisoformat(str(payload["end_at"]).replace("Z", "+00:00")).replace(tzinfo=None)
            if payload.get("end_at")
            else None
        )
        if calendar_write_policy(workspace) == "approval_required":
            return {"status": "proposal", "applied": False, "proposal": payload}
        event = create_event(
            db,
            workspace,
            None,
            title=str(payload["title"]),
            start_at=start_at,
            end_at=end_at,
            location=str(payload.get("location") or ""),
            description=str(payload.get("description") or ""),
            participants=list(payload.get("participants") or []),
            priority=str(payload.get("priority") or "medium"),
            metadata={"created_from": "skill", "skill_slug": "calendar_create_event_v1"},
        )
        db.commit()
        return {"status": "applied", "applied": True, "event": serialize_event(event, workspace=workspace)}
    finally:
        if owns_db:
            db.close()


async def _calendar_update_event_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.workspace_calendar import calendar_write_policy, serialize_event, update_event

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        if calendar_write_policy(workspace) == "approval_required":
            return {"status": "proposal", "applied": False, "proposal": payload}
        updates = dict(payload.get("updates") or {})
        for key in ("title", "description", "location", "participants", "priority", "status", "start_at", "end_at"):
            if key in payload and key not in updates:
                updates[key] = payload[key]
        event = update_event(db, workspace, None, str(payload["event_id"]), updates=updates)
        db.commit()
        return {"status": "applied", "applied": True, "event": serialize_event(event, workspace=workspace)}
    finally:
        if owns_db:
            db.close()


async def _calendar_cancel_event_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.workspace_calendar import calendar_write_policy, cancel_event, serialize_event

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        if calendar_write_policy(workspace) == "approval_required":
            return {"status": "proposal", "applied": False, "proposal": payload}
        event = cancel_event(db, workspace, None, str(payload["event_id"]), reason=str(payload.get("reason") or "skill"))
        db.commit()
        return {"status": "applied", "applied": True, "event": serialize_event(event, workspace=workspace)}
    finally:
        if owns_db:
            db.close()


async def _calendar_daily_summary_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from datetime import date as dt_date

    from app.services.workspace_calendar import summary_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        day = dt_date.fromisoformat(str(payload["day"])) if payload.get("day") else None
        return summary_payload(db, workspace, day=day)
    finally:
        if owns_db:
            db.close()


async def _action_plan_create_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.action_plans import action_planner_write_policy, create_action_item, serialize_action_item

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        if action_planner_write_policy(workspace) == "approval_required":
            return {"status": "proposal", "applied": False, "proposal": payload}
        item = create_action_item(
            db,
            workspace,
            None,
            title=str(payload["title"]),
            description=str(payload.get("description") or ""),
            target_kind=str(payload.get("target_kind") or "cabinet"),
            target_id=str(payload.get("target_id") or ""),
            target_label=str(payload.get("target_label") or ""),
            priority=str(payload.get("priority") or "medium"),
            due_at=payload.get("due_at"),
            owner_label=str(payload.get("owner_label") or "Cabinet"),
            source_kind=str(payload.get("source_kind") or "skill"),
            source_id=str(payload.get("source_id") or ""),
            metadata={"created_from": "skill", "skill_slug": "action_plan_create_v1"},
        )
        db.commit()
        return {"status": "applied", "applied": True, "item": serialize_action_item(item)}
    finally:
        if owns_db:
            db.close()


async def _action_plan_reschedule_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.action_plans import action_planner_write_policy, serialize_action_item, update_action_item

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        if action_planner_write_policy(workspace) == "approval_required":
            return {"status": "proposal", "applied": False, "proposal": payload}
        item = update_action_item(db, workspace, None, str(payload["item_id"]), {"due_at": payload.get("due_at"), "status": "planned"})
        db.commit()
        return {"status": "applied", "applied": True, "item": serialize_action_item(item)}
    finally:
        if owns_db:
            db.close()


async def _action_plan_status_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.action_plans import list_action_items, serialize_action_item, summary_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        rows = list_action_items(db, workspace, status=payload.get("status"), include_cancelled=bool(payload.get("include_cancelled", True)))
        return {"items": [serialize_action_item(row) for row in rows], "summary": summary_payload(db, workspace)}
    finally:
        if owns_db:
            db.close()


async def _action_plan_cancel_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.action_plans import action_planner_write_policy, cancel_action_item, serialize_action_item

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        if action_planner_write_policy(workspace) == "approval_required":
            return {"status": "proposal", "applied": False, "proposal": payload}
        item = cancel_action_item(db, workspace, None, str(payload["item_id"]), reason=str(payload.get("reason") or "skill"))
        db.commit()
        return {"status": "applied", "applied": True, "item": serialize_action_item(item)}
    finally:
        if owns_db:
            db.close()


async def _time_context_set_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.demo_time_context import demo_time_context_defaults

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        settings = dict(workspace.settings or {})
        defaults = demo_time_context_defaults(workspace)
        mode = str(payload.get("mode") or defaults["mode"])
        settings["demo_time_context"] = {
            "mode": mode,
            "current_date": str(payload.get("current_date") or payload.get("date") or defaults["current_date"]),
            "current_time": str(payload.get("current_time") or defaults.get("current_time") or "10:30:00"),
            "label": str(payload.get("label") or defaults["label"]),
            "timezone": str(payload.get("timezone") or defaults["timezone"]),
            "lock_fixed": bool(payload.get("lock_fixed") or payload.get("locked") or mode.lower() == "fixed"),
        }
        workspace.settings = settings
        db.add(workspace)
        db.commit()
        return {"status": "applied", "applied": True, "demo_time_context": settings["demo_time_context"]}
    finally:
        if owns_db:
            db.close()


async def _briefing_priorities_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.mission_room import ATTENTION_REQUIRED, cockpit_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        cockpit = cockpit_payload(workspace, db=db)
        priorities = []
        for item in (cockpit.get("attention_required") or ATTENTION_REQUIRED)[:3]:
            priorities.append(
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "summary": item.get("sentence") or item.get("summary"),
                    "deadline": item.get("deadline"),
                    "tone": item.get("tone"),
                    "sources": item.get("source_refs") or item.get("sources") or [],
                }
            )
        return {"status": "ready", "priorities": priorities, "cockpit": {"decision_sentence": cockpit.get("decision_sentence")}}
    finally:
        if owns_db:
            db.close()


def _load_prefet_report_text() -> str:
    from pathlib import Path

    candidates = [
        Path(__file__).resolve().parents[3] / "docs" / "demo-data" / "sentinel-ci-kb" / "rapport-prefet-nawa-2026-05-10.md",
        Path(__file__).resolve().parents[2] / ".." / "docs" / "demo-data" / "sentinel-ci-kb" / "rapport-prefet-nawa-2026-05-10.md",
    ]
    for path in candidates:
        if path.exists():
            return path.read_text(encoding="utf-8")
    return ""


async def _summarize_long_document_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    document_id = str(payload.get("document_id") or "report-prefet-nawa-2026-05-10")
    focus_topics = list(payload.get("focus_topics") or ["cacao", "diversification", "infrastructures"])
    report_text = _load_prefet_report_text()
    citations = [
        {
            "source_id": "src-prefet-nawa-report-001",
            "document_id": document_id,
            "title": "Rapport Prefet Nawa — 10 mai 2026",
            "sent_at": "2026-05-10",
            "pages": 70,
        }
    ]
    key_topics = [topic for topic in focus_topics if topic.lower() in report_text.lower()] or focus_topics
    summary_lines = [
        "Monsieur le Vice Premier Ministre, synthese des derniers echanges avec le Prefet de Nawa (rapport du 10 mai, ~70 pages) :",
        "- Contexte : region Nawa / Soubre, filiere cacao dominante, pression sur prix FCFA et infrastructures.",
        "- Points saillants : besoin de sechoirs, routes secondaires, electrifiation et diversification cultures.",
        "- Risques : volatilite prix export, dependance monoculture, fenetre climatique.",
        "- Recommandations prefet : transformation locale a court terme, montee en charge cooperative, financement mixte.",
    ]
    if "cacao" in report_text.lower():
        summary_lines.append("- Emergence cacao : sections filiere et chiffrage publics confirment un gap transformation ~4,2-6,8 Mds FCFA.")
    return {
        "status": "ready",
        "summary_markdown": "\n".join(summary_lines),
        "key_topics": key_topics,
        "citations": citations,
        "document_id": document_id,
    }


async def _generate_recommendations_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    topic = str(payload.get("topic") or "cacao_diversification")
    chiffrage = bool(payload.get("chiffrage", True))
    options = [
        {
            "label": "Petite industrie transformation + diversification cultures",
            "summary": "Unité locale de transformation cacao + ananas/culture de couverture ; impact emploi Soubre.",
            "cost_estimate": "4,2 Mds FCFA" if chiffrage else None,
            "infra_required": ["Sechoirs", "Mini-usine", "Routes secondaires"],
            "confidence": 0.78,
        },
        {
            "label": "Cooperative regionale renforcee",
            "summary": "Montee en charge cooperative existante, formation qualite export et tracabilite.",
            "cost_estimate": "1,6 Mds FCFA" if chiffrage else None,
            "infra_required": ["Centres de collecte", "Formation"],
            "confidence": 0.71,
        },
        {
            "label": "PPP infrastructure sechoirs",
            "summary": "Partenariat public-prive sur sechoirs solaires ; partage risque prix.",
            "cost_estimate": "6,8 Mds FCFA" if chiffrage else None,
            "infra_required": ["Sechoirs solaires", "Electrification"],
            "confidence": 0.66,
        },
    ]
    return {
        "status": "ready",
        "topic": topic,
        "options": options,
        "sources": [{"source_id": "src-prefet-nawa-report-001", "document_id": "report-prefet-nawa-2026-05-10"}],
        "human_validation_required": True,
    }


async def _draft_email_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    template_kind = str(payload.get("template_kind") or "customs_priority")
    target_id = str(payload.get("target_id") or "")
    context_refs = list(payload.get("context_refs") or [])
    if template_kind == "customs_priority":
        return {
            "status": "draft",
            "template_kind": template_kind,
            "subject": (
                "Priorisation dedouanement — composants drones Aerostar Dynamics, "
                "Centre Formation Drones Napié (cargo-abidjan-supply-001)"
            ),
            "recipient": "Direction generale des Douanes — Cellule Port Abidjan",
            "body_markdown": (
                "Monsieur le Directeur,\n\n"
                "Je vous prie de bien vouloir accorder une priorisation de traitement a la cargaison "
                "**MV ATLANTIC TRADER** (ref. cargo-abidjan-supply-001, IMO 9876543) : composants drones "
                "Aerostar Dynamics importes depuis la cote Est des Etats-Unis (hangars de formation, "
                "terrains d'apprentissage, laboratoires de cartographie) destines au "
                "**Centre International de Formation aux Métiers des Drones de Napié** "
                "(ref. proj-drone-centre-napie, region Poro / Nord ; investissement 100 M USD / 60 Mds FCFA ; "
                "alignement Côte d'Ivoire Innovation 2030).\n\n"
                "Le retard actuel (de l'ordre de 120 jours sur la sequence ouverture du centre) impacte le "
                "calendrier de demarrage des formations FAA et la perception institutionnelle du projet sur zone.\n\n"
                "Merci de me confirmer la fenetre de dedouanement envisagee.\n\n"
                "Bien cordialement,\nCabinet Vice Premier Ministre"
            ),
            "sources": [
                {"source_id": "src-maritime-paa-001"},
                {"source_id": "src-cabinet-brief-001", "project_id": "proj-drone-centre-napie"},
                {
                    "source_id": "src-abidjan-net-drone-napie-2025-07-16",
                    "title": "Abidjan.net — Lancement Centre Formation Drones Napié (16/07/2025)",
                    "kind": "rss_news_ci",
                },
            ],
            "requires_validation": True,
        }
    if template_kind == "customs_derogation":
        return {
            "status": "draft",
            "template_kind": template_kind,
            "subject": (
                "Demande de derogation operationnelle — cargaison composants drones "
                "Centre Formation Napié (MV Atlantic Trader)"
            ),
            "recipient": "Direction generale des Douanes — Chef de la cellule portuaire Abidjan",
            "body_markdown": (
                "Monsieur le Chef de la cellule douaniere,\n\n"
                "Faisant suite au proces-verbal de non-conformite declarative du 18 mai 2026 "
                "(ref. DGD-CI/CPA/PV-2026-05-018, page 2), je vous saisis pour solliciter une "
                "**derogation operationnelle ciblee** au benefice du cargo MV ATLANTIC TRADER "
                "(IMO 9876543, MMSI 627012345, ref. cargo-abidjan-supply-001).\n\n"
                "**Le cargo MV Atlantic Trader est distinct du lot non conforme** (LOT-INTRA-IMP-2026-05-018). "
                "Sa cargaison — composants drones AerostarDynamics (hangars de formation, terrains "
                "d'apprentissage, laboratoires de cartographie), importes depuis la cote Est des Etats-Unis — "
                "est exclusivement destinee au **Centre International de Formation aux Métiers des Drones "
                "de Napié** (ref. proj-drone-centre-napie, region Poro / Nord ; partenariat Agence de "
                "Developpement Regional du Poro, Aerostar Dynamics et CEPICI ; alignement Côte d'Ivoire "
                "Innovation 2030 ; investissement 100 M USD / 60 Mds FCFA ; cf. Abidjan.net, "
                "16 juillet 2025).\n\n"
                "Le gel temporaire du couloir d'entree Vridi, motive par la non-conformite d'un **autre** lot, "
                "affecte par effet collateral la cargaison drones Napié sans qu'aucune anomalie declarative "
                "n'ait ete relevee a son encontre.\n\n"
                "Au vu :\n"
                "- de la distinction documentaire claire entre les deux lots ;\n"
                "- du calendrier de livraison engageant l'ouverture du Centre Formation Drones de Napié "
                "(retard cumule de l'ordre de 120 jours en Q2 2026) ;\n"
                "- et de l'absence totale de non-conformite sur le lot drones Napié,\n\n"
                "je sollicite votre accord pour une derogation operationnelle permettant le dedouanement "
                "anticipe du cargo MV Atlantic Trader sous reserve des controles physiques habituels.\n\n"
                "Demande advisory soumise a validation Cabinet et a confirmation du ministere de l'Economie "
                "avant transmission officielle.\n\n"
                "Bien cordialement,\nCabinet Vice Premier Ministre"
            ),
            "sources": [
                {
                    "source_id": "customs-record-non-conformite-2026-05",
                    "title": "PV douanes - non conformite declarative (18 mai)",
                    "kind": "customs_pv",
                    "page": 2,
                },
                {"source_id": "src-maritime-paa-001"},
                {"source_id": "src-cabinet-brief-001", "project_id": "proj-drone-centre-napie"},
                {
                    "source_id": "src-abidjan-net-drone-napie-2025-07-16",
                    "title": "Abidjan.net — Lancement Centre Formation Drones Napié (16/07/2025)",
                    "kind": "rss_news_ci",
                },
            ],
            "context_refs": context_refs,
            "requires_validation": True,
            "advisory_only": True,
            "target_id": target_id or "cargo-abidjan-supply-001",
        }
    if template_kind == "strategic_report_long":
        return {
            "status": "draft",
            "template_kind": template_kind,
            "subject": "Rapport strategique - Diversification cacao region Nawa (anacarde transformee)",
            "recipient": "Cabinet Vice Premier Ministre + Ministere Economie + Ministere Agriculture",
            "body_markdown": (
                "# Rapport strategique - Diversification cacao region Nawa\n\n"
                "## Synthese executive\n"
                "L'option **anacarde transformee** ressort prioritaire (note Banque mondiale 2024, "
                "Reuters 2025, EUDR). Chiffrage indicatif : 4,2 - 6,8 Mds FCFA.\n\n"
                "## Classement des 7 cultures evaluees\n"
                "1. Anacarde transformee (prioritaire)\n"
                "2. Cooperative cacao tracable (court terme)\n"
                "3. Hevea (complement)\n"
                "4. Banane premium (niche)\n"
                "5. PPP sechoirs solaires (infrastructure)\n"
                "6. Palmier a huile RSPO (risque EUDR)\n"
                "7. Statu quo (non recommande)\n\n"
                "## Citations\n"
                "- Banque mondiale - Note climat-developpement 2024\n"
                "- Reglement europeen anti-deforestation (EUDR)\n"
                "- Reuters 2025 - filiere cajou Cote d'Ivoire\n"
                "- Rapport Prefet Nawa - 10 mai 2026 (pp. 42-58)\n\n"
                "Document **advisory-only** soumis a validation Conseil des Ministres."
            ),
            "sources": [
                {"source_id": "report-prefet-nawa-2026-05-10"},
                {"source_id": "sentinel-ci-anacarde-diversification-v1"},
                {"source_id": "src-banque-mondiale-2024"},
                {"source_id": "src-eudr-2023"},
                {"source_id": "src-reuters-cajou-2025"},
            ],
            "context_refs": context_refs,
            "requires_validation": True,
            "advisory_only": True,
            "target_id": target_id,
        }
    return {
        "status": "draft",
        "template_kind": template_kind,
        "subject": "Rapport de diversification cacao — region Nawa (arbitrage cabinet)",
        "recipient": "Ministere de l'Economie — Direction filieres",
        "body_markdown": (
            "# Rapport de diversification cacao — Nawa\n\n"
            "## Contexte\nSuite au rapport Prefet Nawa (10 mai) et aux echanges a Soubre.\n\n"
            "## Option recommandee\nPetite industrie de transformation + diversification cultures.\n\n"
            "## Chiffrage indicatif\n4,2 a 6,8 milliards FCFA (ordres de grandeur publics).\n\n"
            "## Prochaines etapes\nArbitrage cabinet, puis RDV ministere de l'Economie."
        ),
        "sources": [{"source_id": "src-prefet-nawa-report-001", "document_id": "report-prefet-nawa-2026-05-10"}],
        "requires_validation": True,
        "target_id": target_id,
    }


async def _causal_drill_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Drill the evidence graph following ``caused_by`` from ``last_focus``.

    Used by ``aya.explain_why`` (Phase A). Returns a path with citations
    so the chat answer can chain "pourquoi -> pourquoi" with sources.
    """
    from app.models.workspace import Workspace
    from app.services.mission_room import evidence_graph_trace

    ctx = ctx or {}
    db = ctx.get("db")
    workspace_id = ctx.get("workspace_id")
    from_node = str(payload.get("from_node") or payload.get("last_focus") or "zone-nord")
    relation = str(payload.get("relation") or "caused_by")
    depth = int(payload.get("depth") or 4)

    if not db or not workspace_id:
        return {"status": "error", "reason": "missing_workspace_context", "path": []}
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        return {"status": "error", "reason": "workspace_not_found", "path": []}

    trace = evidence_graph_trace(workspace, from_node=from_node, relation=relation, depth=depth, db=db)
    path = trace.get("path") or []
    next_step = path[1] if len(path) > 1 else None
    next_node = (next_step or {}).get("node") or {}
    first_edge = ((path[0] if path else {}) or {}).get("edge") or {}
    return {
        "status": "ready",
        "from_node": from_node,
        "relation": relation,
        "depth": depth,
        "path": path,
        "next_focus": next_node.get("id") or from_node,
        "next_surface": next_node.get("next_surface") or {},
        "explanation": first_edge.get("explanation"),
        "narrative_short": next_node.get("narrative_short"),
        "citations": [
            {"source_id": str(ref), "kind": "evidence_ref"}
            for ref in (next_node.get("evidence_refs") or [])
        ],
    }


async def _update_meeting_agenda_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Propose adding agenda items to a workspace calendar event.

    Phase H: produces a confirmation-drawer payload first (no DB write).
    Actual write happens through the calendar PATCH endpoint after the
    Vice Premier Ministre confirms.
    """
    from app.models.workspace import Workspace
    from app.services.workspace_calendar import list_events, serialize_event

    ctx = ctx or {}
    db = ctx.get("db")
    workspace_id = ctx.get("workspace_id")
    if not db or not workspace_id:
        return {"status": "error", "reason": "missing_workspace_context"}
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        return {"status": "error", "reason": "workspace_not_found"}

    event_id = payload.get("event_id")
    agenda_items = list(payload.get("agenda_items") or [])
    if not agenda_items:
        agenda_items = [
            {
                "id": "agenda-cacao-diversification",
                "title": "Point cacao - diversification anacarde (proposition AYA)",
                "order": 99,
                "priority": "high",
                "owner_proposer": "AYA",
                "decision_required": True,
                "source_refs": [
                    "report-prefet-nawa-2026-05-10",
                    "sentinel-ci-anacarde-diversification-v1",
                ],
            }
        ]

    event = None
    if event_id:
        event = next((row for row in list_events(db, workspace) if row.id == event_id), None)
    if event is None:
        for row in list_events(db, workspace, status="scheduled"):
            meta = row.meta_data or {}
            if meta.get("seed_id") == "evt-prefet-nawa" or meta.get("context_ref") == "report-prefet-nawa-2026-05-10":
                event = row
                break
        if event is None:
            events = list_events(db, workspace, status="scheduled")
            event = events[0] if events else None

    if event is None:
        return {"status": "error", "reason": "no_event_found"}

    return {
        "status": "proposal",
        "applied": False,
        "requires_validation": True,
        "event_id": event.id,
        "event_title": event.title,
        "event_summary": serialize_event(event, workspace=workspace),
        "metadata": {"agenda_items": agenda_items},
        "audit_event": "calendar.event.agenda_items.proposed",
    }


async def _schedule_meeting_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.demo_time_context import resolve_demo_date
    from app.services.workspace_calendar import summary_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        day = resolve_demo_date(workspace)
        cal = summary_payload(db, workspace, day=day)
        windows = cal.get("free_slots") or cal.get("available_windows") or []
        slot = windows[0] if windows else {"start": f"{day.isoformat()}T16:30:00", "end": f"{day.isoformat()}T17:15:00"}
        draft_id = f"draft-{uuid.uuid4().hex[:12]}"
        proposed = {
            "date": day.isoformat(),
            "time": str(slot.get("start", "")).split("T")[-1][:5] if isinstance(slot.get("start"), str) else "16:30",
            "location": "Ministere de l'Economie — Plateau",
            "duration_min": int(payload.get("duration_min") or 45),
            "participants": ["Vice Premier Ministre", "Ministre de l'Economie", "AYA"],
            "topic": payload.get("topic") or "Diversification cacao",
        }
        return {
            "status": "proposal",
            "applied": False,
            "requires_validation": True,
            "proposed_slot": proposed,
            "calendar_event_draft_id": draft_id,
            "proposal": proposed,
        }
    finally:
        if owns_db:
            db.close()


async def _territorial_action_window_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.mission_room import map_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        body = map_payload(workspace, db=db)
        target_id = payload.get("target_id") or payload.get("zone_id")
        windows = body.get("recommended_windows") or []
        if target_id:
            windows = [window for window in windows if window.get("target_id") == target_id] or windows
        return {"status": "ready", "recommended_windows": windows, "map": body.get("map")}
    finally:
        if owns_db:
            db.close()


async def _map_layer_read_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.workspace_maps import ensure_workspace_map_seed, mission_room_map_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        ensure_workspace_map_seed(db, workspace)
        return mission_room_map_payload(db, workspace)
    finally:
        if owns_db:
            db.close()


async def _map_zone_score_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.workspace_jobs import create_workspace_job, serialize_job
    from app.services.workspace_maps import ensure_workspace_map_seed, get_workspace_map, score_map_zones

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        ensure_workspace_map_seed(db, workspace)
        map_row = get_workspace_map(db, workspace, str(payload.get("map_slug") or payload.get("map_id") or "sentinel-ci-strategic-map"))
        job = create_workspace_job(
            db,
            workspace,
            None,
            kind="map_zone_scoring",
            title=f"Scoring carte · {map_row.name}",
            input_ref={"map_id": map_row.id, "slug": map_row.slug},
            status="queued",
        )
        result = score_map_zones(db, workspace, map_row, job=job)
        db.commit()
        return {"job": serialize_job(job), "result": result}
    finally:
        if owns_db:
            db.close()


async def _map_signal_attach_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from uuid import uuid4

    from app.models.workspace_map import WorkspaceMapSignal, WorkspaceMapZone
    from app.services.workspace_maps import ensure_workspace_map_seed, get_workspace_map

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        ensure_workspace_map_seed(db, workspace)
        map_row = get_workspace_map(db, workspace, str(payload.get("map_slug") or payload.get("map_id") or "sentinel-ci-strategic-map"))
        zone = (
            db.query(WorkspaceMapZone)
            .filter(WorkspaceMapZone.map_id == map_row.id, WorkspaceMapZone.zone_key == str(payload["zone_key"]))
            .first()
        )
        if not zone:
            return {"status": "not_found", "warning": "map_zone_not_found"}
        signal = WorkspaceMapSignal(
            id=str(uuid4()),
            map_id=map_row.id,
            zone_id=zone.id,
            source_kind=str(payload.get("source_kind") or "skill"),
            source_id=str(payload.get("source_id") or ""),
            title=str(payload["title"]),
            summary=str(payload.get("summary") or ""),
            weight=int(payload.get("weight") or 10),
            confidence=float(payload.get("confidence") or 0.65),
            occurred_at=datetime.utcnow(),
            meta_data=dict(payload.get("metadata") or {}),
        )
        db.add(signal)
        db.commit()
        return {"status": "attached", "signal": {"id": signal.id, "zone_key": zone.zone_key, "title": signal.title}}
    finally:
        if owns_db:
            db.close()


async def _map_recommendation_generate_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.workspace_maps import ensure_workspace_map_seed, mission_room_map_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        ensure_workspace_map_seed(db, workspace)
        body = mission_room_map_payload(db, workspace)
        recommendations = []
        for zone in body.get("zones") or []:
            recommendations.extend(zone.get("scenario_options") or [])
        return {"recommendations": recommendations, "score_summary": body.get("score_summary") or {}}
    finally:
        if owns_db:
            db.close()


async def _map_command_apply_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.workspace_maps import build_map_command, ensure_workspace_map_seed

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        ensure_workspace_map_seed(db, workspace)
        command = build_map_command(
            db,
            workspace,
            map_id_or_slug=str(payload.get("map_slug") or payload.get("map_id") or "sentinel-ci-strategic-map"),
            intent=str(payload.get("intent") or "focus_zone"),
            target=payload.get("target"),
            layers=payload.get("layers"),
            basemap=payload.get("basemap"),
            camera=payload.get("camera"),
            annotation=payload.get("annotation"),
        )
        db.commit()
        return {"status": "ready", **command}
    finally:
        if owns_db:
            db.close()


async def _source_registry_refresh_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.mission_room import cockpit_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        cockpit = cockpit_payload(workspace, db=db)
        return {
            "status": "ready",
            "source_health": cockpit.get("source_freshness") or {},
            "layers": cockpit.get("monitoring_layers") or [],
            "decision_posture": cockpit.get("decision_posture") or {},
        }
    finally:
        if owns_db:
            db.close()


async def _osint_signal_prioritize_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.mission_room import news_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        news = news_payload(workspace, db=db)
        return {
            "status": "ready",
            "priorities": news.get("executive_alerts") or news.get("signals") or [],
            "geographic_tiers": news.get("geographic_priority") or news.get("geo_sections") or [],
            "source_health": news.get("source_health") or {},
        }
    finally:
        if owns_db:
            db.close()


async def _rumor_origin_trace_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.mission_room import news_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        news = news_payload(workspace, db=db)
        trace = (news.get("social_listening") or {}).get("rumor_origins") or []
        rumor = trace[0] if trace else (news.get("rumor_trace") or {})
        return {
            "status": "ready",
            "trace": rumor,
            "social_listening": news.get("social_listening") or {},
            "advisory_only": True,
        }
    finally:
        if owns_db:
            db.close()


async def _evidence_graph_build_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.mission_room import evidence_graph_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        return evidence_graph_payload(workspace, db=db)
    finally:
        if owns_db:
            db.close()


async def _situation_posture_score_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.mission_room import cockpit_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        cockpit = cockpit_payload(workspace, db=db)
        posture = cockpit.get("decision_posture") or {}
        return {
            "status": "ready",
            "score": posture.get("score"),
            "label": posture.get("label"),
            "axes": posture.get("axes") or [],
            "modes": posture.get("modes") or [],
        }
    finally:
        if owns_db:
            db.close()


async def _maritime_snapshot_read_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.workspace_maps import ensure_workspace_map_seed, mission_room_map_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        ensure_workspace_map_seed(db, workspace)
        mapped = mission_room_map_payload(db, workspace)
        map_system = mapped.get("map_system") or {}
        return {
            "status": "ready",
            "maritime_snapshot": map_system.get("maritime_snapshot") or {},
            "source_health": (map_system.get("source_health") or {}),
            "ports": (map_system.get("maritime_snapshot") or {}).get("ports") or [],
            "events": (map_system.get("maritime_snapshot") or {}).get("events") or [],
        }
    finally:
        if owns_db:
            db.close()


async def _decision_option_rank_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.mission_room import decisions_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        decisions = decisions_payload(workspace, db=db)
        options = list(payload.get("options") or decisions.get("scenario_options") or [])
        ranked = sorted(
            options,
            key=lambda item: (
                int(item.get("recommended_score") or item.get("score") or item.get("impact") or 0),
                int(item.get("confidence") or 0),
            ),
            reverse=True,
        )
        return {
            "status": "ready",
            "recommended": ranked[0] if ranked else None,
            "alternatives": ranked[1:],
            "human_validation_required": True,
        }
    finally:
        if owns_db:
            db.close()


async def _draft_response_email_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.mission_room import draft_instruction_payload

    ctx = ctx or {}
    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not ctx.get("db")
    try:
        return draft_instruction_payload(
            workspace=workspace,
            actor=str(ctx.get("actor") or payload.get("actor") or "system:draft_response_email_v1"),
            target_id=str(payload.get("target_id") or "package-rumeur-emoi"),
            target_type=str(payload.get("target_type") or "communication_email"),
            instruction_type=str(payload.get("instruction_type") or "response_email"),
            db=db,
        )
    finally:
        if owns_db:
            db.close()


async def _visual_source_read_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.visual_intelligence import dashboard_payload, ensure_visual_intelligence_seed

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        ensure_visual_intelligence_seed(db, workspace)
        return dashboard_payload(db, workspace)
    finally:
        if owns_db:
            db.close()


async def _visual_snapshot_capture_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.visual_intelligence import (
        dispatch_visual_capture_job,
        ensure_visual_intelligence_seed,
        get_source,
        list_sources,
        queue_visual_capture,
    )

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        ensure_visual_intelligence_seed(db, workspace)
        source_id = payload.get("source_id")
        source = get_source(db, workspace, str(source_id)) if source_id else (list_sources(db, workspace)[0])
        job = queue_visual_capture(db, workspace, source)
        db.commit()
        task_id = dispatch_visual_capture_job(db, workspace, job, source)
        db.commit()
        return {"job_id": job.id, "status": job.status, "task_id": task_id}
    finally:
        if owns_db:
            db.close()


async def _visual_snapshot_analyze_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.models.workspace_visual import WorkspaceVisualObservation
    from app.services.visual_intelligence import serialize_observation

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        capture_id = str(payload.get("capture_id") or "")
        observation = (
            db.query(WorkspaceVisualObservation)
            .filter(WorkspaceVisualObservation.workspace_id == workspace.id, WorkspaceVisualObservation.capture_id == capture_id)
            .order_by(WorkspaceVisualObservation.created_at.desc())
            .first()
        )
        if not observation:
            return {"status": "not_found", "warning": "visual_observation_not_found"}
        return {"status": "ready", "observation": serialize_observation(observation)}
    finally:
        if owns_db:
            db.close()


async def _visual_observation_sync_knowledge_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.models.workspace_visual import WorkspaceVisualObservation
    from app.services.visual_intelligence import VISUAL_COLLECTION_SLUG, sync_observation_to_knowledge

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        observation_id = str(payload.get("observation_id") or "")
        observation = (
            db.query(WorkspaceVisualObservation)
            .filter(WorkspaceVisualObservation.workspace_id == workspace.id, WorkspaceVisualObservation.id == observation_id)
            .first()
        )
        if not observation:
            return {"status": "not_found", "warning": "visual_observation_not_found"}
        object_key = sync_observation_to_knowledge(db, workspace, observation)
        db.commit()
        return {"status": "synced", "collection": VISUAL_COLLECTION_SLUG, "object_key": object_key}
    finally:
        if owns_db:
            db.close()


async def _sharepoint_ingestion_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    # Real ingestion goes through the OAuth/MSAL flow in
    # `app.services.connectors.sharepoint_otp.ingester`. Triggering that
    # flow from a background skill still needs a tenant-scoped token
    # context, which is not currently passed in. Until the builder
    # surfaces that, we return a structured degraded response rather
    # than crash the run.
    logger.info(
        "sharepoint_ingestion_v1: degraded (missing tenant token context)",
        site_url=payload.get("site_url"),
    )
    return {
        "files": 0,
        "skipped": 0,
        "status": "degraded",
        "warning": "sharepoint_token_context_unavailable",
    }


async def _voice_transcribe_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.voice_runtime import get_voice_runtime_provider

    provider = get_voice_runtime_provider((payload.get("provider") or "cascade_openai"))
    audio_bytes = _audio_bytes_from_payload(payload)
    result = await provider.transcribe(
        audio_bytes,
        filename=payload.get("filename") or "recording.webm",
        content_type=payload.get("content_type") or "audio/webm",
        language=payload.get("language") or payload.get("input_language") or "fr",
    )
    return {
        "transcript": result.get("transcript") or result.get("text", ""),
        "text": result.get("text", ""),
        "model": result.get("model"),
        "provider": result.get("provider"),
        "fallback": result.get("fallback", False),
    }


async def _voice_tts_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.voice_runtime import get_voice_runtime_provider

    provider = get_voice_runtime_provider((payload.get("provider") or "cascade_openai"))
    result = await provider.synthesize_bytes(
        payload["text"],
        voice=payload.get("voice"),
        instructions=payload.get("instructions"),
    )
    return {
        "audio_url": None,
        "audio_base64": result.get("audio_base64"),
        "content_type": result.get("content_type"),
        "model": result.get("model"),
        "provider": result.get("provider"),
        "bytes": result.get("bytes"),
    }


async def _voice_realtime_session_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.voice_runtime import (
        build_openai_realtime_session,
        list_voice_runtime_providers,
        resolve_voice_runtime_slug,
    )

    ctx = ctx or {}
    provider = resolve_voice_runtime_slug(payload.get("provider") or ctx.get("voice_provider"))
    session = build_openai_realtime_session(
        model=payload.get("model"),
        voice=payload.get("voice") or "marin",
        instructions=payload.get("instructions"),
        input_language=payload.get("language") or payload.get("input_language"),
        output_language=payload.get("output_language"),
        capability=payload.get("capability") or "voice2voice_interaction",
        metadata={"transport": payload.get("transport") or "backend_ws"},
    )
    catalog = list_voice_runtime_providers()
    provider_meta = next((item for item in catalog.get("providers", []) if item.get("slug") == provider), None)
    return {
        "provider": provider,
        "model": payload.get("model"),
        "transport": payload.get("transport") or "backend_ws",
        "session": session if provider == "openai_realtime" else None,
        "capabilities": (provider_meta or {}).get("capabilities", {}),
        "fallback_policy": payload.get("fallback_policy") or "cascade_openai",
        "events": catalog.get("events", []),
    }


async def _voice_realtime_transcribe_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.voice_runtime import get_voice_runtime_provider

    provider = get_voice_runtime_provider(payload.get("provider") or "cascade_openai")
    audio_bytes = _audio_bytes_from_payload(payload)
    result = await provider.transcribe(
        audio_bytes,
        filename=payload.get("filename") or "recording.webm",
        content_type=payload.get("content_type") or "audio/webm",
        language=payload.get("language") or payload.get("input_language") or "fr",
    )
    text = result.get("text") or result.get("transcript") or ""
    return {
        "transcript": text,
        "text": text,
        "text_events": [
            {"type": "text.partial", "text": text, "provider": result.get("provider")},
            {"type": "text.final", "text": text, "provider": result.get("provider")},
        ],
        "model": result.get("model"),
        "provider": result.get("provider"),
        "requested_provider": result.get("requested_provider") or payload.get("provider"),
        "fallback": result.get("fallback", False),
        "fallback_reason": result.get("fallback_reason"),
    }


async def _voice_realtime_speak_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.voice_runtime import get_voice_runtime_provider

    provider = get_voice_runtime_provider(payload.get("provider") or "cascade_openai")
    result = await provider.synthesize_bytes(
        payload["text"],
        voice=payload.get("voice"),
        instructions=payload.get("instructions"),
    )
    return {
        "audio_base64": result.get("audio_base64"),
        "content_type": result.get("content_type"),
        "model": result.get("model"),
        "provider": result.get("provider"),
        "requested_provider": result.get("requested_provider") or payload.get("provider"),
        "bytes": result.get("bytes"),
        "fallback": result.get("fallback", False),
        "events": [{"type": "audio.out", "bytes": result.get("bytes"), "provider": result.get("provider")}],
    }


async def _voice_realtime_translate_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.voice_runtime import get_voice_runtime_provider

    provider = get_voice_runtime_provider(payload.get("provider") or "openai_realtime")
    if not provider.capabilities.get("translation"):
        return {
            "status": "degraded",
            "warning": "provider_capability_unsupported",
            "provider": provider.slug,
            "source_text": payload.get("text") or "",
            "translated_text": payload.get("text") or "",
        }
    return {
        "status": "deferred",
        "provider": provider.slug,
        "model": payload.get("model"),
        "source_language": payload.get("source_language") or payload.get("language"),
        "target_language": payload.get("target_language") or payload.get("output_language"),
        "events": ["translation.partial", "translation.final"],
    }


async def _voice_oracle_turn_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.knowledge_capture import evaluate_expert_answer

    evaluation = evaluate_expert_answer(
        answer=payload.get("answer") or payload.get("text") or "",
        question=payload.get("question"),
        gap=payload.get("gap"),
    )
    verdict = evaluation.get("verdict")
    action = "next_prompt" if verdict != "sufficient" else "capture_fact"
    return {
        "action": action,
        "evaluation": evaluation,
        "events": [{"type": "oracle.action", "action": action, "verdict": verdict}],
    }


async def _voice_tandem_oracle_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.voice_tandem_oracle import VoiceTandemOracle

    ctx = ctx or {}
    oracle = VoiceTandemOracle(min_interval_ms=0, min_delta_chars=0)
    turn_id = str(payload.get("turn_id") or ctx.get("turn_id") or "flow-turn")
    duration_ms = int(payload.get("duration_ms") or 0)
    events: list[Dict[str, Any]] = []
    partial_text = payload.get("partial_text") or payload.get("text")
    if partial_text:
        events.extend(
            oracle.observe_partial(
                str(partial_text),
                turn_id=turn_id,
                input_state={
                    "transcript_state": "partial",
                    "provider": payload.get("provider"),
                    "transport": payload.get("transport") or "backend_ws",
                },
                output_state={"oracle_state": "thinking"},
                duration_ms=duration_ms,
                force=True,
            )
        )
    final_text = payload.get("final_text") or (payload.get("text") if payload.get("is_final") else None)
    if final_text:
        events.extend(
            oracle.commit_final(
                str(final_text),
                turn_id=turn_id,
                evaluation=payload.get("evaluation") if isinstance(payload.get("evaluation"), dict) else None,
                next_prompt=payload.get("next_prompt"),
                sources=payload.get("sources") if isinstance(payload.get("sources"), list) else None,
                duration_ms=duration_ms,
            )
        )
    return {
        "mode": "tandem_oracle",
        "committed": any(event.get("type") == "oracle.commit" for event in events),
        "events": events,
        "provider": payload.get("provider"),
        "transport": payload.get("transport") or "backend_ws",
        "fallback_policy": payload.get("fallback_policy"),
    }


def _audio_bytes_from_payload(payload: Dict[str, Any]) -> bytes:
    if payload.get("audio_bytes"):
        raw = payload["audio_bytes"]
        if isinstance(raw, bytes):
            return raw
        if isinstance(raw, str):
            return raw.encode("latin1")
        return bytes(raw)
    if payload.get("audio_base64"):
        return base64.b64decode(payload["audio_base64"])
    audio_ref = payload.get("audio_ref")
    if audio_ref:
        path = Path(audio_ref)
        if not path.exists() or not path.is_file():
            raise ValueError("voice_transcribe_v1: audio_ref does not resolve to a local file")
        return path.read_bytes()
    raise ValueError("voice_transcribe_v1: one of audio_bytes, audio_base64 or audio_ref is required")


async def _knowledge_gap_analysis_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.knowledge_capture import build_knowledge_gaps

    return {
        "gaps": build_knowledge_gaps(
            objective=payload["objective"],
            expert_profile=payload.get("expert_profile"),
            context_snapshot=payload.get("context") or {},
            knowledge_refs=payload.get("knowledge_refs") or [],
        )
    }


async def _expert_interview_plan_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.knowledge_capture import build_interview_plan

    return {
        "plan": build_interview_plan(
            objective=payload["objective"],
            expert_profile=payload.get("expert_profile"),
            duration_minutes=int(payload.get("duration_minutes") or 20),
            gaps=payload.get("gaps") or [],
            context_snapshot=payload.get("context") or {},
        )
    }


async def _expert_answer_evaluator_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.knowledge_capture import evaluate_expert_answer

    return evaluate_expert_answer(
        answer=payload["answer"],
        question=payload.get("question"),
        gap=payload.get("gap"),
    )


async def _capture_structuring_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    # The persisted endpoint uses `structure_capture_payload` on an ORM
    # session. The skill contract also supports already-serialized session
    # payloads for DAG/runtime callers.
    session = payload["session"]
    transcript = session.get("transcript") or []
    evaluations = session.get("evaluations") or []
    captured_facts = session.get("captured_facts") or [
        {
            "id": f"fact-{turn.get('id')}",
            "text": turn.get("text", ""),
            "source": "expert_session",
            "confidence": next(
                (ev.get("score") for ev in evaluations if ev.get("turn_id") == turn.get("id")),
                0.5,
            ),
            "needs_review": True,
        }
        for turn in transcript
        if turn.get("speaker") == "expert"
    ]
    proposal = {
        "session_id": session.get("id"),
        "title": session.get("title"),
        "objective": session.get("objective"),
        "captured_facts": captured_facts,
        "open_questions": [
            {
                "gap_id": ev.get("gap_id"),
                "reason": ev.get("verdict"),
                "follow_up": ev.get("follow_up"),
            }
            for ev in evaluations
            if ev.get("verdict") != "sufficient"
        ],
        "transcript": transcript,
        "review": {"required": True},
    }
    return {"proposal": proposal}


async def _audit_log_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    event_id = str(uuid.uuid4())
    logger.info(
        "audit_log_v1: event",
        event_id=event_id,
        event_type=payload.get("event_type"),
        workspace_id=(ctx or {}).get("workspace_id"),
        ts=datetime.utcnow().isoformat(),
        details=payload.get("details") or {},
    )
    return {"id": event_id, "status": "recorded"}


async def _ollama_llm_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.model_clients.ollama_client import OllamaClient

    client = OllamaClient()
    model = payload.get("model") or "deepseek-r1:14b"
    result = await client.generate(model=model, prompt=payload["prompt"])
    return {
        "completion": result.get("response") or result.get("content", ""),
        "model": model,
    }


async def _azure_llm_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    # Azure OpenAI is OpenAI-compatible — reuse the OpenAI client.
    from app.services.model_clients.openai_client import OpenAIClient

    client = OpenAIClient()
    if not client.api_key:
        return {
            "completion": "",
            "status": "degraded",
            "warning": "openai_key_unavailable",
        }

    ctx = ctx or {}
    token_sink = ctx.get("token_sink")
    model = payload.get("model") or "gpt-4o-mini"
    prompt = payload["prompt"]

    # Stream token-by-token when the run engine provided a sink (Vague D
    # / D2). Every delta is pushed to the live SSE bus so the cockpit's
    # Execution terminal can render a typewriter effect; we also
    # accumulate the final text so the non-streaming contract
    # (`completion` field) keeps working for replay.
    if callable(token_sink):
        try:
            parts: list[str] = []
            async for chunk in client.stream(model=model, prompt=prompt):
                delta = chunk.get("delta") or ""
                if delta:
                    parts.append(delta)
                    token_sink(delta)
            return {
                "completion": "".join(parts),
                "model": model,
                "streamed": True,
            }
        except Exception as exc:  # noqa: BLE001 — fall back to non-streaming
            logger.warning(
                "azure_llm_v1: streaming failed, falling back",
                error=str(exc),
            )

    result = await client.generate(model=model, prompt=prompt)
    return {
        "completion": result.get("content", ""),
        "model": result.get("model"),
        "usage": result.get("usage", {}),
    }


async def _chain_naive_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.rag.chains import answer_naive

    ctx = ctx or {}
    return await answer_naive(
        query=payload["query"],
        context_id=payload.get("context_id"),
        workspace_id=ctx.get("workspace_id"),
        top_k=payload.get("top_k"),
    )


async def _chain_hybrid_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.rag.chains import answer_hybrid

    ctx = ctx or {}
    return await answer_hybrid(
        query=payload["query"],
        context_id=payload.get("context_id"),
        workspace_id=ctx.get("workspace_id"),
        top_k=payload.get("top_k"),
    )


async def _chain_mixed_hah_v1(payload: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services.rag.chains import answer_mixed_hah

    ctx = ctx or {}
    return await answer_mixed_hah(
        query=payload["query"],
        context_id=payload.get("context_id"),
        workspace_id=ctx.get("workspace_id"),
        top_k=payload.get("top_k"),
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
# (slug -> (callable, expected_module_path|None, status_hint))
# ``expected_module_path`` is the module whose import must succeed for
# the wrapper to be considered `bound`. A ``None`` path means the
# wrapper is self-contained (loggers, stubs, in-process helpers).
_REGISTRY: Dict[str, Tuple[SkillCallable, Optional[str], str]] = {
    "llm_rag_answer_v1":       (_llm_rag_answer_v1,       "app.services.rag.rag_service",          "bound"),
    "semantic_search_v1":      (_semantic_search_v1,      "app.services.rag.pipeline_retrieval",   "bound"),
    "document_ingestion_v1":   (_document_ingestion_v1,   "app.services.rag.document_service",     "bound"),
    "eval_radar_v1":           (_eval_radar_v1,           "app.services.evaluation.judge",         "bound"),
    "claim_audit_v1":          (_claim_audit_v1,          "app.services.evaluation.judge",         "bound"),
    "intelligence_batch_v1":   (_intelligence_batch_v1,   "app.services.intelligence.batch",       "bound"),
    "ministerial_briefing_v1": (_ministerial_briefing_v1, "app.services.mission_room",             "bound"),
    "news_signal_synthesis_v1": (_news_signal_synthesis_v1, "app.services.mission_room",           "bound"),
    "project_risk_explainer_v1": (_project_risk_explainer_v1, "app.services.mission_room",         "bound"),
    "territorial_signal_map_v1": (_territorial_signal_map_v1, "app.services.mission_room",         "bound"),
    "instruction_draft_v1":    (_instruction_draft_v1,    "app.services.mission_room",             "bound"),
    "scenario_generate_v1":    (_scenario_generate_v1,    "app.services.scenario_engine",          "bound"),
    "scenario_compare_v1":     (_scenario_compare_v1,     "app.services.scenario_engine",          "bound"),
    "scenario_recommend_v1":   (_scenario_recommend_v1,   "app.services.scenario_engine",          "bound"),
    "calendar_read_v1":        (_calendar_read_v1,        "app.services.workspace_calendar",       "bound"),
    "calendar_create_event_v1": (_calendar_create_event_v1, "app.services.workspace_calendar",     "bound"),
    "calendar_update_event_v1": (_calendar_update_event_v1, "app.services.workspace_calendar",     "bound"),
    "calendar_cancel_event_v1": (_calendar_cancel_event_v1, "app.services.workspace_calendar",     "bound"),
    "calendar_daily_summary_v1": (_calendar_daily_summary_v1, "app.services.workspace_calendar",   "bound"),
    "action_plan_create_v1":    (_action_plan_create_v1,    "app.services.action_plans",           "bound"),
    "action_plan_reschedule_v1": (_action_plan_reschedule_v1, "app.services.action_plans",         "bound"),
    "action_plan_status_v1":    (_action_plan_status_v1,    "app.services.action_plans",           "bound"),
    "action_plan_cancel_v1":    (_action_plan_cancel_v1,    "app.services.action_plans",           "bound"),
    "time_context_set_v1":      (_time_context_set_v1,      "app.services.demo_time_context",    "bound"),
    "briefing_priorities_v1":     (_briefing_priorities_v1,     "app.services.mission_room",           "bound"),
    "summarize_long_document_v1": (_summarize_long_document_v1, "app.services.mission_room",           "bound"),
    "generate_recommendations_v1": (_generate_recommendations_v1, "app.services.mission_room",          "bound"),
    "draft_email_v1":           (_draft_email_v1,           "app.services.mission_room",             "bound"),
    "causal_drill_v1":          (_causal_drill_v1,          "app.services.mission_room",             "bound"),
    "update_meeting_agenda_v1": (_update_meeting_agenda_v1, "app.services.workspace_calendar",       "bound"),
    "schedule_meeting_v1":      (_schedule_meeting_v1,      "app.services.workspace_calendar",     "bound"),
    "territorial_action_window_v1": (_territorial_action_window_v1, "app.services.mission_room",   "bound"),
    "map_layer_read_v1":        (_map_layer_read_v1,        "app.services.workspace_maps",          "bound"),
    "map_zone_score_v1":        (_map_zone_score_v1,        "app.services.workspace_maps",          "bound"),
    "map_signal_attach_v1":     (_map_signal_attach_v1,     "app.services.workspace_maps",          "bound"),
    "map_recommendation_generate_v1": (_map_recommendation_generate_v1, "app.services.workspace_maps", "bound"),
    "map_command_apply_v1":     (_map_command_apply_v1,     "app.services.workspace_maps",          "bound"),
    "source_registry_refresh_v1": (_source_registry_refresh_v1, "app.services.mission_room",          "bound"),
    "osint_signal_prioritize_v1": (_osint_signal_prioritize_v1, "app.services.mission_room",          "bound"),
    "rumor_origin_trace_v1":    (_rumor_origin_trace_v1,    "app.services.mission_room",             "bound"),
    "evidence_graph_build_v1":  (_evidence_graph_build_v1,  "app.services.mission_room",             "bound"),
    "situation_posture_score_v1": (_situation_posture_score_v1, "app.services.mission_room",          "bound"),
    "maritime_snapshot_read_v1": (_maritime_snapshot_read_v1, "app.services.workspace_maps",          "bound"),
    "decision_option_rank_v1":  (_decision_option_rank_v1,  "app.services.mission_room",             "bound"),
    "draft_response_email_v1":  (_draft_response_email_v1,  "app.services.mission_room",             "bound"),
    "visual_source_read_v1":    (_visual_source_read_v1,    "app.services.visual_intelligence",     "bound"),
    "visual_snapshot_capture_v1": (_visual_snapshot_capture_v1, "app.services.visual_intelligence",  "bound"),
    "visual_snapshot_analyze_v1": (_visual_snapshot_analyze_v1, "app.services.visual_intelligence",  "bound"),
    "visual_observation_sync_knowledge_v1": (_visual_observation_sync_knowledge_v1, "app.services.visual_intelligence", "bound"),
    "sharepoint_ingestion_v1": (_sharepoint_ingestion_v1, None,                                    "stub"),
    "voice_transcribe_v1":     (_voice_transcribe_v1,     "app.services.voice_runtime",            "bound"),
    "voice_tts_v1":            (_voice_tts_v1,            "app.services.voice_runtime",            "bound"),
    "voice_realtime_session_v1": (_voice_realtime_session_v1, "app.services.voice_runtime",         "bound"),
    "voice_realtime_transcribe_v1": (_voice_realtime_transcribe_v1, "app.services.voice_runtime",   "bound"),
    "voice_realtime_speak_v1":  (_voice_realtime_speak_v1, "app.services.voice_runtime",            "bound"),
    "voice_realtime_translate_v1": (_voice_realtime_translate_v1, "app.services.voice_runtime",     "bound"),
    "voice_oracle_turn_v1":     (_voice_oracle_turn_v1,   "app.services.knowledge_capture",         "bound"),
    "voice_tandem_oracle_v1":   (_voice_tandem_oracle_v1, "app.services.voice_tandem_oracle",       "bound"),
    "knowledge_gap_analysis_v1": (_knowledge_gap_analysis_v1, "app.services.knowledge_capture",     "bound"),
    "expert_interview_plan_v1": (_expert_interview_plan_v1, "app.services.knowledge_capture",      "bound"),
    "expert_answer_evaluator_v1": (_expert_answer_evaluator_v1, "app.services.knowledge_capture",  "bound"),
    "capture_structuring_v1":  (_capture_structuring_v1,  "app.services.knowledge_capture",        "bound"),
    "audit_log_v1":            (_audit_log_v1,            None,                                    "bound"),
    "ollama_llm_v1":           (_ollama_llm_v1,           "app.services.model_clients.ollama_client", "bound"),
    "azure_llm_v1":            (_azure_llm_v1,            "app.services.model_clients.openai_client", "bound"),
    "chain_naive_v1":          (_chain_naive_v1,          "app.services.rag.chains.naive",         "bound"),
    "chain_hybrid_v1":         (_chain_hybrid_v1,         "app.services.rag.chains.hybrid",        "bound"),
    "chain_mixed_hah_v1":      (_chain_mixed_hah_v1,      "app.services.rag.chains.mixed_hah",     "bound"),
}

_RESOLVED_STATUS: Dict[str, str] = {}


def resolve(slug: str) -> SkillCallable:
    """Return the runtime callable bound to a skill slug.

    Unknown slugs fall through to ``_unimplemented``.
    """
    entry = _REGISTRY.get(slug)
    if entry is None:
        return _unimplemented
    return entry[0]


def runtime_status(slug: str) -> str:
    """Return ``bound`` | ``stub`` | ``unbound`` for a slug.

    Evaluates the dependency import on first call so we catch missing
    modules without forcing eager imports at startup.
    """
    if slug in _RESOLVED_STATUS:
        return _RESOLVED_STATUS[slug]
    entry = _REGISTRY.get(slug)
    if entry is None:
        _RESOLVED_STATUS[slug] = "unbound"
        return "unbound"
    _, module_path, hint = entry
    if module_path is None:
        _RESOLVED_STATUS[slug] = hint
        return hint
    try:
        importlib.import_module(module_path)
        _RESOLVED_STATUS[slug] = "bound"
        return "bound"
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "skills_registry: dependency import failed — marking stub",
            slug=slug,
            module=module_path,
            error=str(exc),
        )
        _RESOLVED_STATUS[slug] = "stub"
        return "stub"


def bound_slugs() -> Dict[str, str]:
    """Return `{slug: status}` for every registered skill (tri-state)."""
    return {slug: runtime_status(slug) for slug in _REGISTRY}


def registry_snapshot() -> Dict[str, Dict[str, Any]]:
    """Richer report for admin / observability endpoints."""
    snap: Dict[str, Dict[str, Any]] = {}
    for slug, (_fn, module_path, hint) in _REGISTRY.items():
        snap[slug] = {
            "status": runtime_status(slug),
            "declared_status": hint,
            "module": module_path,
        }
    return snap
