"""Seed premium video-demo values for Agentium Showcase and Octocity.

Usage:
    poetry run python -m app.cli.seed_agentium_video_demo

This intentionally avoids resetting either workspace. It only replaces rows
tagged with ``video_demo = agentium_clevel_v1`` and updates demo-safe workspace
settings used by the filmed Connector and Hypervisor surfaces.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

import app.models  # noqa: F401  register SQLAlchemy models
from app.db.base import SessionLocal
from app.models.capability import Capability
from app.models.decision import Decision
from app.models.evaluation import EvaluationScore
from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.models.workspace import Workspace
from app.services.audit_logger import emit_audit_event
from app.services.mission_room import ensure_octocity_mission_room_workspace
from app.services.skills_registry import seed_skills_and_capabilities

SHOWCASE_SLUG = "agentium-showcase"
VIDEO_DEMO_TAG = "agentium_clevel_v1"


PORTFOLIO_RUNS: tuple[dict[str, Any], ...] = (
    {
        "system": "Agentium Workspace Chat",
        "capability_slug": "video_workspace_assistant",
        "capability_name": "Workspace Assistant",
        "title": "Executive answer grounded across SharePoint and policy corpus",
        "decision": "answer_grounded",
        "value": 18_500.0,
        "cost": 42.0,
        "confidence": 0.94,
        "duration_ms": 1240,
        "query": "Give the CEO a sourced answer on the strategic KPI drift.",
        "response": "Synthesized the answer from governed knowledge, cited sources and opened an audit trace.",
        "skills": ["semantic_search_v1", "llm_rag_answer_v1", "claim_audit_v1", "audit_log_v1"],
    },
    {
        "system": "Tender Response Analyst",
        "capability_slug": "video_tender_response",
        "capability_name": "Tender Response Acceleration",
        "title": "RFP response generated with human review gate",
        "decision": "review_ready",
        "value": 72_000.0,
        "cost": 185.0,
        "confidence": 0.91,
        "duration_ms": 2860,
        "query": "Draft a compliant response for a strategic procurement section.",
        "response": "Generated a compliant answer pack, flagged two risks and routed the final version to human review.",
        "skills": ["semantic_search_v1", "llm_rag_answer_v1", "claim_audit_v1", "audit_log_v1"],
    },
    {
        "system": "Translation Suite",
        "capability_slug": "video_translation_suite",
        "capability_name": "Translation Suite",
        "title": "Sovereign multilingual delivery package accepted",
        "decision": "delivery_released",
        "value": 128_000.0,
        "cost": 940.0,
        "confidence": 0.97,
        "duration_ms": 31 * 60 * 1000,
        "query": "Run a regulated translation batch with QA replay and audit export.",
        "response": "Accepted 39-language delivery after replaying failed topics and preserving XML integrity.",
        "skills": ["translation_j2450_qa_v1", "audit_log_v1"],
    },
    {
        "system": "Compliance Review Loop",
        "capability_slug": "video_compliance_loop",
        "capability_name": "Compliance Review Loop",
        "title": "Vendor onboarding blocked before policy breach",
        "decision": "blocked_and_escalated",
        "value": 46_000.0,
        "cost": 118.0,
        "confidence": 0.89,
        "duration_ms": 1980,
        "query": "Can this vendor be approved without data processing evidence?",
        "response": "Blocked the request, cited the missing DPA and created a remediation path for legal review.",
        "skills": ["claim_audit_v1", "semantic_search_v1", "audit_log_v1"],
    },
    {
        "system": "Contract Risk Copilot",
        "capability_slug": "video_contract_risk",
        "capability_name": "Contract Risk Detection",
        "title": "Liability clause remediated with approved fallback",
        "decision": "fallback_proposed",
        "value": 34_000.0,
        "cost": 76.0,
        "confidence": 0.92,
        "duration_ms": 1620,
        "query": "Identify contract risk and propose a safe fallback clause.",
        "response": "Detected uncapped liability, produced a capped fallback and linked the policy source.",
        "skills": ["semantic_search_v1", "llm_rag_answer_v1", "audit_log_v1"],
    },
)


def _workspace(db, slug: str) -> Workspace:
    workspace = db.query(Workspace).filter(Workspace.slug == slug).first()
    if not workspace:
        raise RuntimeError(f"Workspace not found: {slug}. Seed it first.")
    return workspace


def _system_by_name(db, workspace: Workspace, name: str) -> System | None:
    return (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.name == name)
        .first()
    )


def _ensure_video_capability(db, workspace: Workspace, spec: dict[str, Any], system: System) -> Capability:
    slug = str(spec["capability_slug"])
    capability = db.query(Capability).filter(Capability.slug == slug).first()
    if not capability:
        capability = Capability(slug=slug)
        db.add(capability)
    capability.workspace_id = workspace.id
    capability.name = str(spec["capability_name"])
    capability.description = (
        f"Synthetic C-level video capability for {system.name}: governed design, runtime execution, "
        "observable outcomes and executive value tracking."
    )
    capability.tier = "client"
    capability.industry = "cross-industry"
    capability.input_unit = "governed_run"
    capability.output_unit = "audited_outcome"
    capability.skill_ids = list(system.skill_ids or spec.get("skills") or [])
    capability.pricing = {"unit": "per_outcome", "unit_price": float(spec["cost"]), "currency": "USD"}
    capability.value_per_outcome = float(spec["value"])
    capability.confidence_threshold = 0.85
    capability.sla = {"max_latency_ms": int(spec["duration_ms"]), "review": "human_in_the_loop"}
    capability.roi_model = {
        "type": "video_demo_value_minus_cost",
        "video_demo": VIDEO_DEMO_TAG,
        "estimated_value": float(spec["value"]),
        "internal_cost": float(spec["cost"]),
    }
    capability.is_seeded = "Y"
    system.capability_id = capability.id
    return capability


def _cleanup_video_rows(db, workspace: Workspace) -> int:
    runs = (
        db.query(Run)
        .filter(Run.workspace_id == workspace.id)
        .all()
    )
    tagged_run_ids = [
        run.id
        for run in runs
        if isinstance(run.input_ref, dict) and run.input_ref.get("video_demo") == VIDEO_DEMO_TAG
    ]
    deleted = 0
    if tagged_run_ids:
        deleted += db.query(SkillInvocation).filter(SkillInvocation.run_id.in_(tagged_run_ids)).delete(synchronize_session=False)
        deleted += db.query(EvaluationScore).filter(EvaluationScore.run_id.in_(tagged_run_ids)).delete(synchronize_session=False)
        deleted += db.query(Decision).filter(
            Decision.workspace_id == workspace.id,
            Decision.target_id.in_(tagged_run_ids),
        ).delete(synchronize_session=False)
        deleted += db.query(Run).filter(Run.id.in_(tagged_run_ids)).delete(synchronize_session=False)
    tagged_decision_ids = [
        decision.id
        for decision in db.query(Decision).filter(Decision.workspace_id == workspace.id).all()
        if isinstance(decision.rationale, dict) and decision.rationale.get("video_demo") == VIDEO_DEMO_TAG
    ]
    if tagged_decision_ids:
        deleted += db.query(Decision).filter(Decision.id.in_(tagged_decision_ids)).delete(synchronize_session=False)
    return deleted


def _enhance_connectors(workspace: Workspace) -> None:
    settings = dict(workspace.settings or {})
    connectors = dict(settings.get("connectors") or {})
    connectors.update(
        {
            "sharepoint": {
                "enabled": True,
                "status": "connected",
                "label": "Microsoft SharePoint",
                "scope": "executive-policy-libraries",
            },
            "teams": {
                "enabled": True,
                "status": "connected",
                "label": "Microsoft Teams",
                "scope": "decision-room-notifications",
            },
            "secure_deposit": {
                "enabled": True,
                "status": "connected",
                "label": "SFTP secure deposit",
            },
            "rest_api": {
                "enabled": True,
                "status": "connected",
                "label": "External operational APIs",
            },
            "visual_streams": {
                "enabled": True,
                "status": "connected",
                "label": "Live visual signals",
            },
        }
    )
    settings["connectors"] = connectors
    settings["calendar"] = {
        **dict(settings.get("calendar") or {}),
        "connector_id": "institutional_calendar",
        "connector_label": "Executive calendar",
        "mode": "internal_shared",
    }
    settings["visual_intelligence"] = {
        **dict(settings.get("visual_intelligence") or {}),
        "enabled": True,
        "capture_cadence_minutes": 15,
    }
    settings["video_demo"] = {
        "profile": VIDEO_DEMO_TAG,
        "positioning": "C-level AI operating system demo",
        "updated_at": datetime.utcnow().isoformat(),
    }
    workspace.settings = settings


def _seed_portfolio_runs(db, workspace: Workspace) -> tuple[int, int]:
    created_runs = 0
    created_decisions = 0
    now = datetime.utcnow()
    for idx, spec in enumerate(PORTFOLIO_RUNS):
        system = _system_by_name(db, workspace, spec["system"])
        if not system:
            continue
        capability = _ensure_video_capability(db, workspace, spec, system)
        started = now - timedelta(minutes=idx * 8 + 2)
        completed = started + timedelta(milliseconds=spec["duration_ms"])
        run_id = str(uuid4())
        run = Run(
            id=run_id,
            workspace_id=workspace.id,
            system_id=system.id,
            capability_id=capability.id,
            input_ref={
                "video_demo": VIDEO_DEMO_TAG,
                "title": spec["title"],
                "query": spec["query"],
                "connectors": ["sharepoint", "teams", "secure_deposit", "rest_api"],
            },
            output_ref={
                "response": spec["response"],
                "sources": [
                    {"filename": "executive-policy-library.md", "connector": "sharepoint"},
                    {"filename": "runtime-audit-trace.json", "connector": "agentium"},
                ],
                "portfolio_impact": {
                    "value_estimated": spec["value"],
                    "cost_internal": spec["cost"],
                    "roi": round((spec["value"] - spec["cost"]) / spec["cost"], 2),
                },
            },
            status="completed",
            started_at=started,
            completed_at=completed,
            duration_ms=spec["duration_ms"],
            trigger="video_demo",
            decision=spec["decision"],
            confidence=spec["confidence"],
            value_estimated=spec["value"],
            cost_internal=spec["cost"],
            efficiency=spec["value"] / spec["cost"],
            value_source="operator",
            operator_value_note="Synthetic C-level video demo value model.",
            checkpoints=[
                {"stage": "grounding", "status": "completed", "progress": 32},
                {"stage": "policy_control", "status": "completed", "progress": 58},
                {"stage": "human_review", "status": "completed", "progress": 81},
                {"stage": "audit_export", "status": "completed", "progress": 100},
            ],
            flow_snapshot=system.flow_definition,
        )
        score_id = str(uuid4())
        run.evaluation_scores = {
            "evaluation_id": score_id,
            "composite_score": round(spec["confidence"] * 100, 1),
            "hallucination_rate": 0.0,
            "threshold_breach": False,
            "scores": {
                "task_success": round(spec["confidence"] * 100, 1),
                "grounding": 96.0,
                "auditability": 100.0,
                "business_value": 98.0,
            },
            "topic": "C-level portfolio demo",
            "video_demo": VIDEO_DEMO_TAG,
        }
        db.add(run)
        db.add(
            EvaluationScore(
                id=score_id,
                workspace_id=workspace.id,
                run_id=run_id,
                session_id=run_id,
                agent_id=system.id,
                turn_number=1,
                query=spec["query"],
                scores=run.evaluation_scores["scores"],
                composite_score=run.evaluation_scores["composite_score"],
                hallucination_rate=0.0,
                drift_rate=0.0,
                question_type="executive_portfolio",
                failed_components=[],
                topic="C-level portfolio demo",
                claim_audit={"supported": 4, "unsupported": 0, "video_demo": VIDEO_DEMO_TAG},
                metadata_={"video_demo": VIDEO_DEMO_TAG, "system": system.name},
                created_at=completed,
            )
        )
        for skill_idx, skill_slug in enumerate(spec["skills"]):
            db.add(
                SkillInvocation(
                    id=str(uuid4()),
                    run_id=run_id,
                    skill_slug=skill_slug,
                    input_ref={"video_demo": VIDEO_DEMO_TAG, "query": spec["query"]},
                    output_ref={"status": "ok", "connector_bound": skill_idx < 2},
                    status="completed",
                    started_at=started + timedelta(milliseconds=skill_idx * 260),
                    completed_at=started + timedelta(milliseconds=(skill_idx + 1) * 260),
                    latency_ms=260 + skill_idx * 90,
                    cost=round(spec["cost"] / max(1, len(spec["skills"])), 2),
                    metrics={"video_demo": VIDEO_DEMO_TAG},
                )
            )
        db.add(
            Decision(
                id=str(uuid4()),
                workspace_id=workspace.id,
                scope="run",
                target_id=run_id,
                kind="recommendation",
                status="proposed",
                title=f"Scale {system.name} after high-value governed run",
                rationale={
                    "video_demo": VIDEO_DEMO_TAG,
                    "source": "agentium_video_seed",
                    "confidence": spec["confidence"],
                    "decision": spec["decision"],
                    "why_now": "High ROI, audited execution and reusable flow pattern detected.",
                },
                impact_estimate={
                    "value_estimated": spec["value"],
                    "cost_internal": spec["cost"],
                    "roi": round((spec["value"] - spec["cost"]) / spec["cost"], 2),
                    "recommended_action": "increase_budget_and_enable_runtime_monitoring",
                },
                created_at=completed,
            )
        )
        emit_audit_event(
            workspace_id=workspace.id,
            event_type="video_demo.portfolio_run.seeded",
            actor="agentium-video-seed",
            details={
                "video_demo": VIDEO_DEMO_TAG,
                "system": system.name,
                "run_id": run_id,
                "value_estimated": spec["value"],
                "cost_internal": spec["cost"],
            },
            trace_id=run_id,
            agent_id=system.id,
            db=db,
        )
        created_runs += 1
        created_decisions += 1
    return created_runs, created_decisions


def main() -> None:
    with SessionLocal() as db:
        seed_skills_and_capabilities(db)
        showcase = _workspace(db, SHOWCASE_SLUG)
        deleted = _cleanup_video_rows(db, showcase)
        _enhance_connectors(showcase)
        runs, decisions = _seed_portfolio_runs(db, showcase)
        octocity_report = ensure_octocity_mission_room_workspace(db)
        db.commit()
    print(
        {
            "showcase_workspace": SHOWCASE_SLUG,
            "video_demo": VIDEO_DEMO_TAG,
            "deleted_previous_rows": deleted,
            "portfolio_runs_seeded": runs,
            "recommendations_seeded": decisions,
            "octocity_mission_room": octocity_report,
        }
    )


if __name__ == "__main__":
    main()
