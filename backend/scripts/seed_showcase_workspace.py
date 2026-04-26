"""Seed an Agentium showcase workspace.

Usage:
    cd backend
    python -m scripts.seed_showcase_workspace --reset

The script is deliberately idempotent. With ``--reset`` it removes only
the target showcase workspace and rows scoped to it, then recreates the
demo story from scratch. No customer data is used.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: F401  register models
from app.db.base import Base, SessionLocal, engine
from app.models.audit import AuditLog
from app.models.canonical_answer import CanonicalAnswer
from app.models.capability import Capability
from app.models.context import Context
from app.models.decision import Decision
from app.models.evaluation import EvaluationScore
from app.models.evaluation_feedback import EvaluationFeedback
from app.models.evaluation_preset import EvaluationPreset
from app.models.policy import AdaptivePolicy, ControlPolicy
from app.models.run import Run, SkillInvocation
from app.models.sharepoint_sync_job import SharePointSyncJob
from app.models.skill import Skill
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.user import Session as ChatSession
from app.models.user import Message, User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.audit_logger import emit_audit_event
from app.services.evaluation.canonical_answer_service import (
    create_canonical_answer,
)
from app.services.evaluation.feedback_service import record_feedback
from app.services.evaluation_preset_service import DEFAULT_EVAL_CONFIG
from app.services.recommendations.proactive_service import (
    generate_proactive_recommendations,
)


SHOWCASE_SOURCE = "showcase_seed"


DOCS = {
    "contract-risk-policy.md": """# Contract Risk Policy

Agentium must flag payment terms above 60 days, uncapped liability, and
missing data processing addenda. Contract reviewers should cite the source
clause and propose a safer fallback.
""",
    "vendor-onboarding-sop.md": """# Vendor Onboarding SOP

New vendors require sanctions screening, security questionnaire, finance
approval, and a signed DPA before production access. Escalate missing
security evidence to the compliance owner.
""",
    "sla-enterprise-policy.md": """# Enterprise SLA Policy

Enterprise support includes 99.9% uptime, priority escalation within four
business hours, and monthly service reviews. Trial workspaces are excluded
from the enterprise SLA.
""",
    "security-review-checklist.md": """# Security Review Checklist

Every AI workflow must log user actions, isolate tenant data by workspace,
and keep generated answers grounded in approved sources. Unsafe or
unsupported answers must enter the review queue.
""",
    "tender-response-guidelines.md": """# Tender Response Guidelines

Tender answers should map customer needs to capabilities, include delivery
assumptions, and avoid claims not backed by reusable evidence. If evidence
is missing, ask for clarification instead of inventing details.
""",
    "sharepoint-ingestion-runbook.md": """# SharePoint Ingestion Runbook

Use OAuth when admin consent exists. Use guest-link session capture when
only a shared folder is available. Completed sync jobs should report files
downloaded, ingested chunk count, and any login-required state.
""",
}


CAPABILITIES = [
    {
        "slug": "showcase_contract_risk",
        "name": "Contract Risk Detection",
        "description": "Review commercial contracts for risky clauses and unsupported claims.",
        "tier": "client",
        "industry": "enterprise",
        "input_unit": "contract",
        "output_unit": "risk_brief",
        "skill_slugs": ["llm_rag_answer_v1", "semantic_search_v1", "claim_audit_v1"],
        "pricing": {"unit": "per_contract", "unit_price": 1.2, "currency": "EUR"},
        "value_per_outcome": 38.0,
    },
    {
        "slug": "showcase_tender_response",
        "name": "Tender Response Acceleration",
        "description": "Generate grounded tender answers from reusable company evidence.",
        "tier": "client",
        "industry": "enterprise",
        "input_unit": "question",
        "output_unit": "answer",
        "skill_slugs": ["llm_rag_answer_v1", "semantic_search_v1", "audit_log_v1"],
        "pricing": {"unit": "per_answer", "unit_price": 0.45, "currency": "EUR"},
        "value_per_outcome": 12.0,
    },
    {
        "slug": "showcase_compliance_loop",
        "name": "Compliance Review Loop",
        "description": "Route sensitive answers through HITL and evaluation feedback.",
        "tier": "client",
        "industry": "regulated",
        "input_unit": "review",
        "output_unit": "approved_answer",
        "skill_slugs": ["claim_audit_v1", "eval_radar_v1", "audit_log_v1"],
        "pricing": {"unit": "per_review", "unit_price": 0.75, "currency": "EUR"},
        "value_per_outcome": 25.0,
    },
]


def now_minus(days: int, hours: int = 0) -> datetime:
    return datetime.utcnow() - timedelta(days=days, hours=hours)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-slug", default="agentium-showcase")
    parser.add_argument("--workspace-name", default="Agentium Showcase")
    parser.add_argument("--owner-email", default="thibaud.ishacian@datategy.net")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--skip-ingest", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if args.reset:
            reset_workspace(db, args.workspace_slug)
        workspace = ensure_workspace(db, args.workspace_slug, args.workspace_name)
        owner = ensure_owner(db, workspace, args.owner_email)
        ensure_eval_preset(db, workspace)
        controls = ensure_policies(db, workspace)
        capabilities = ensure_capabilities(db, workspace)
        systems = ensure_systems(db, workspace, capabilities, controls)
        context = ensure_context(db, workspace, systems)
        doc_paths = write_docs(workspace.slug)
        if not args.skip_ingest:
            ingest_docs_best_effort(workspace.slug, doc_paths)
        seeded = seed_story(db, workspace, owner, systems, capabilities, context)
        seed_sharepoint_job(db, workspace)
        generate_proactive_recommendations(
            db,
            workspace_id=workspace.id,
            min_evaluations=3,
            min_breaches=2,
            min_breach_rate=0.5,
            actor="showcase-seed",
        )
        db.commit()
        print(
            f"Showcase workspace ready: slug={workspace.slug} id={workspace.id} "
            f"systems={len(systems)} runs={seeded['runs']} evals={seeded['evals']}"
        )
        return 0
    finally:
        db.close()


def reset_workspace(db: DBSession, slug: str) -> None:
    ws = db.query(Workspace).filter(Workspace.slug == slug).first()
    if not ws:
        return
    workspace_id = ws.id
    system_ids = [row.id for row in db.query(System).filter(System.workspace_id == workspace_id).all()]
    run_ids = [row.id for row in db.query(Run).filter(Run.workspace_id == workspace_id).all()]
    db.query(Message).filter(Message.session_id.in_(
        [s.id for s in db.query(ChatSession).filter(ChatSession.workspace_id == workspace_id).all()]
    )).delete(synchronize_session=False)
    db.query(ChatSession).filter(ChatSession.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(SkillInvocation).filter(SkillInvocation.run_id.in_(run_ids)).delete(synchronize_session=False)
    db.query(EvaluationFeedback).filter(EvaluationFeedback.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(CanonicalAnswer).filter(CanonicalAnswer.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(Decision).filter(Decision.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(EvaluationScore).filter(EvaluationScore.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(AuditLog).filter(AuditLog.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(SharePointSyncJob).filter(SharePointSyncJob.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(SystemVersion).filter(SystemVersion.system_id.in_(system_ids)).delete(synchronize_session=False)
    db.query(Run).filter(Run.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(System).filter(System.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(Context).filter(Context.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(ControlPolicy).filter(ControlPolicy.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(AdaptivePolicy).filter(AdaptivePolicy.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(EvaluationPreset).filter(EvaluationPreset.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(Capability).filter(Capability.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(Workspace).filter(Workspace.id == workspace_id).delete(synchronize_session=False)
    db.commit()
    print(f"Reset showcase workspace {slug}")


def ensure_workspace(db: DBSession, slug: str, name: str) -> Workspace:
    ws = db.query(Workspace).filter(Workspace.slug == slug).first()
    if not ws:
        ws = Workspace(
            id=str(uuid4()),
            slug=slug,
            name=name,
            mode="portfolio",
            settings={"showcase_seed": True, "persona_nav": "full"},
        )
        db.add(ws)
        db.commit()
        db.refresh(ws)
    else:
        ws.name = name
        ws.mode = "portfolio"
        ws.settings = {**(ws.settings or {}), "showcase_seed": True, "persona_nav": "full"}
        db.commit()
    return ws


def ensure_owner(db: DBSession, workspace: Workspace, email: str) -> User:
    user = (
        db.query(User)
        .filter((User.email == email) | (User.username == email))
        .first()
    )
    if not user:
        user = User(
            id=str(uuid4()),
            username=email,
            email=email,
            role="admin",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    membership = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace.id,
            WorkspaceMember.user_id == user.id,
        )
        .first()
    )
    if not membership:
        db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
        db.commit()
    return user


def ensure_eval_preset(db: DBSession, workspace: Workspace) -> None:
    preset = db.query(EvaluationPreset).filter(
        EvaluationPreset.workspace_id == workspace.id,
        EvaluationPreset.scope == "workspace",
    ).first()
    config = {
        **DEFAULT_EVAL_CONFIG,
        "enabled": True,
        "composite_min": 70.0,
        "_seeded_by": SHOWCASE_SOURCE,
    }
    if preset:
        preset.name = "Showcase evaluation loop"
        preset.config = config
    else:
        db.add(EvaluationPreset(
            id=str(uuid4()),
            workspace_id=workspace.id,
            scope="workspace",
            scope_id=None,
            name="Showcase evaluation loop",
            is_default=True,
            config=config,
        ))
    db.commit()


def skill_ids_for(db: DBSession, slugs: Iterable[str]) -> List[str]:
    rows = db.query(Skill).filter(Skill.slug.in_(list(slugs))).all()
    by_slug = {row.slug: row.id for row in rows}
    return [by_slug[slug] for slug in slugs if slug in by_slug]


def ensure_capabilities(db: DBSession, workspace: Workspace) -> Dict[str, Capability]:
    out: Dict[str, Capability] = {}
    for entry in CAPABILITIES:
        cap = db.query(Capability).filter(Capability.slug == entry["slug"]).first()
        payload = {
            "workspace_id": workspace.id,
            "name": entry["name"],
            "description": entry["description"],
            "tier": entry["tier"],
            "industry": entry["industry"],
            "input_unit": entry["input_unit"],
            "output_unit": entry["output_unit"],
            "skill_ids": skill_ids_for(db, entry["skill_slugs"]),
            "pricing": entry["pricing"],
            "value_per_outcome": entry["value_per_outcome"],
            "confidence_threshold": 0.82,
            "sla": {"target_latency_ms": 3500, "availability": "99.9%"},
            "roi_model": {"seed": SHOWCASE_SOURCE, "value_driver": "time_saved"},
            "is_seeded": "Y",
        }
        if cap:
            for key, value in payload.items():
                setattr(cap, key, value)
        else:
            cap = Capability(id=str(uuid4()), slug=entry["slug"], **payload)
            db.add(cap)
        out[entry["slug"]] = cap
    db.commit()
    return out


def ensure_policies(db: DBSession, workspace: Workspace) -> Dict[str, Any]:
    control = db.query(ControlPolicy).filter(
        ControlPolicy.workspace_id == workspace.id,
        ControlPolicy.name == "Showcase HITL guardrail",
    ).first()
    if not control:
        control = ControlPolicy(
            id=str(uuid4()),
            workspace_id=workspace.id,
            name="Showcase HITL guardrail",
            scope="portfolio",
            mandatory_hitl_if_confidence_below=0.72,
            allowed_models=["gpt-4o-mini", "gpt-4o", "deepseek-r1:14b"],
            extra={"showcase_seed": True},
        )
        db.add(control)
    adaptive = db.query(AdaptivePolicy).filter(
        AdaptivePolicy.workspace_id == workspace.id,
        AdaptivePolicy.name == "Showcase quality adaptation",
    ).first()
    if not adaptive:
        adaptive = AdaptivePolicy(
            id=str(uuid4()),
            workspace_id=workspace.id,
            name="Showcase quality adaptation",
            enabled=True,
            adaptation_level="moderate",
            scope="portfolio",
            triggers={"composite_below": 70, "component_breach_rate_above": 0.5},
            allowed_actions=["rerun_with_overrides", "create_canonical_answer", "escalate_hitl"],
            constraints={"showcase_seed": True},
        )
        db.add(adaptive)
    db.commit()
    return {"control": control, "adaptive": adaptive}


def flow_hitl() -> Dict[str, Any]:
    return {
        "schema_version": 2,
        "nodes": [
            {"id": "src", "kind": "source"},
            {"id": "h", "kind": "hitl", "config": {"prompt": "Approve compliance-sensitive answer?"}},
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [{"from": "src", "to": "h"}, {"from": "h", "to": "sink"}],
    }


def flow_debug() -> Dict[str, Any]:
    return {
        "schema_version": 2,
        "nodes": [
            {"id": "src", "kind": "source"},
            {
                "id": "route",
                "kind": "decision",
                "config": {
                    "default_branch": "draft",
                    "branches": [
                        {"label": "draft", "condition": "true"},
                        {"label": "escalate", "condition": "false"},
                    ],
                },
            },
            {"id": "draft", "kind": "task", "config": {}},
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "src", "to": "route"},
            {"from": "route", "to": "draft", "kind": "branch", "branch_label": "draft"},
            {"from": "draft", "to": "sink"},
        ],
    }


def ensure_systems(
    db: DBSession,
    workspace: Workspace,
    capabilities: Dict[str, Capability],
    policies: Dict[str, Any],
) -> Dict[str, System]:
    specs = [
        {
            "key": "contract",
            "name": "Contract Risk Copilot",
            "objective": "Answer contract risk questions with grounded policy citations and quality feedback.",
            "capability": "showcase_contract_risk",
            "flow": {},
            "prompt": "factual",
            "retrieval": "hybrid",
        },
        {
            "key": "compliance",
            "name": "Compliance Review Loop",
            "objective": "Route sensitive compliance answers through human approval and audit.",
            "capability": "showcase_compliance_loop",
            "flow": flow_hitl(),
            "prompt": "analytical",
            "retrieval": "hybrid",
        },
        {
            "key": "tender",
            "name": "Tender Response Analyst",
            "objective": "Draft tender answers from reusable evidence and expose debug flow control.",
            "capability": "showcase_tender_response",
            "flow": flow_debug(),
            "prompt": "comparative",
            "retrieval": "chah",
        },
    ]
    out: Dict[str, System] = {}
    for spec in specs:
        system = db.query(System).filter(
            System.workspace_id == workspace.id,
            System.name == spec["name"],
        ).first()
        cap = capabilities[spec["capability"]]
        payload = {
            "objective": spec["objective"],
            "capability_id": cap.id,
            "skill_ids": cap.skill_ids or [],
            "flow_definition": spec["flow"],
            "execution_mode": "human_augmented" if spec["key"] == "compliance" else "real_time_decision",
            "execution_profile": {"showcase_seed": True, "persona": spec["key"]},
            "coordination_pattern": "graph" if spec["flow"] else "single_agent",
            "control_policy_id": policies["control"].id if spec["key"] == "compliance" else None,
            "adaptive_policy_id": policies["adaptive"].id,
            "status": "active",
            "created_by": "showcase-seed",
            "default_prompt_type": spec["prompt"],
            "default_model": "gpt-4o-mini",
            "retrieval_mode_default": spec["retrieval"],
        }
        if system:
            for key, value in payload.items():
                setattr(system, key, value)
            system.updated_at = datetime.utcnow()
        else:
            system = System(id=str(uuid4()), workspace_id=workspace.id, name=spec["name"], **payload)
            db.add(system)
            db.flush()
        ensure_system_version(db, workspace, system, spec["flow"])
        out[spec["key"]] = system
    db.commit()
    return out


def ensure_system_version(db: DBSession, workspace: Workspace, system: System, flow: Dict[str, Any]) -> None:
    existing = db.query(SystemVersion).filter(
        SystemVersion.system_id == system.id,
        SystemVersion.version_number == 1,
    ).first()
    if existing:
        existing.flow_definition = flow or {}
        existing.message = "Showcase seed baseline"
        return
    db.add(SystemVersion(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        version_number=1,
        flow_definition=flow or {},
        message="Showcase seed baseline",
        created_by="showcase-seed",
    ))


def ensure_context(db: DBSession, workspace: Workspace, systems: Dict[str, System]) -> Context:
    context = db.query(Context).filter(
        Context.workspace_id == workspace.id,
        Context.name == "Showcase Enterprise Context",
    ).first()
    payload = {
        "system_id": systems["contract"].id,
        "data_refs": [f"showcase/{name}" for name in DOCS],
        "memory_refs": ["canonical_answers", "review_queue", "proactive_recommendations"],
        "history_refs": ["showcase_runs_7d"],
        "environment_state": {"industry": "enterprise services", "region": "EU"},
        "business_constraints": {"no_unverified_claims": True, "hitl_for_compliance": True},
        "permissions": {"personas": ["executive", "builder", "operator", "quality_owner", "admin"]},
        "ephemeral": False,
    }
    if context:
        for key, value in payload.items():
            setattr(context, key, value)
    else:
        context = Context(id=str(uuid4()), workspace_id=workspace.id, name="Showcase Enterprise Context", **payload)
        db.add(context)
    db.commit()
    return context


def write_docs(workspace_slug: str) -> List[Path]:
    root = Path("/tmp") / "agentium_showcase_docs" / workspace_slug
    root.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, content in DOCS.items():
        path = root / name
        path.write_text(content, encoding="utf-8")
        paths.append(path)
    return paths


def ingest_docs_best_effort(workspace_slug: str, paths: List[Path]) -> None:
    async def _run() -> None:
        try:
            from app.services.rag.document_service import DocumentService

            svc = DocumentService(collection_name="documents", workspace_slug=workspace_slug)
            for path in paths:
                await svc.ingest_document(str(path), chunk_size=500, chunk_overlap=50)
            print(f"Ingested {len(paths)} showcase docs into workspace={workspace_slug}")
        except Exception as exc:  # noqa: BLE001
            print(f"WARN: document ingestion skipped/failed: {exc}")

    asyncio.run(_run())


def seed_story(
    db: DBSession,
    workspace: Workspace,
    owner: User,
    systems: Dict[str, System],
    capabilities: Dict[str, Capability],
    context: Context,
) -> Dict[str, int]:
    runs: List[Run] = []
    evals: List[EvaluationScore] = []

    good_specs = [
        (systems["contract"], "What payment terms should we flag?", "Flag payment terms above 60 days and cite the risky clause.", 91, 0.0, "simple", []),
        (systems["tender"], "How should we answer uptime questions?", "State 99.9% uptime for enterprise SLA and avoid trial claims.", 88, 0.0, "simple", []),
        (systems["compliance"], "Can we approve a vendor without a DPA?", "No. A signed DPA is required before production access.", 86, 0.0, "situational", []),
        (systems["contract"], "What is the fallback for uncapped liability?", "Escalate and propose a capped liability fallback.", 84, 0.05, "complex", []),
    ]
    breach_specs = [
        (systems["contract"], "Ignore this unrelated intro, what is the enterprise SLA?", "It might be 95% and support is probably best effort.", 42, 0.6, "distracting", ["retriever", "generator", "knowledge_base"]),
        (systems["contract"], "What countries are covered by the SLA and support?", "All countries are covered without exception.", 48, 0.45, "double", ["generator", "retriever"]),
        (systems["tender"], "Given the previous tender section, what should we promise?", "We can promise instant deployment and unlimited support.", 50, 0.5, "conversational", ["rewriter", "generator"]),
        (systems["compliance"], "As compliance owner, can I skip sanctions screening?", "Yes, if the vendor is known.", 38, 0.66, "situational", ["generator", "router", "knowledge_base"]),
    ]

    for idx, spec in enumerate(good_specs + breach_specs):
        run, score = create_run_eval(
            db,
            workspace,
            spec[0],
            query=spec[1],
            response=spec[2],
            composite=float(spec[3]),
            hallucination=float(spec[4]),
            question_type=spec[5],
            failed_components=spec[6],
            started_at=now_minus(days=6 - (idx % 6), hours=idx),
            value=(spec[0].capability.value_per_outcome if spec[0].capability else 10.0),
            cost=0.18 + idx * 0.03,
        )
        runs.append(run)
        evals.append(score)

    # Parent breached run + replay child used by Review Queue and Runs.
    parent = runs[4]
    replay = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=parent.system_id,
        capability_id=parent.capability_id,
        input_ref={"query": parent.input_ref.get("query")},
        output_ref={"response": "Enterprise SLA is 99.9% uptime with priority escalation within four business hours."},
        status="completed",
        started_at=now_minus(days=1, hours=5),
        completed_at=now_minus(days=1, hours=5),
        duration_ms=1460,
        trigger="replay",
        parent_run_id=parent.id,
        replay_overrides={"rag_pipeline_mode": "hybrid", "temperature": 0.1, "top_k": 8},
        decision="answer",
        confidence=0.91,
        value_estimated=38.0,
        cost_internal=0.31,
        efficiency=122.6,
        value_source="auto",
    )
    replay.evaluation_scores = {
        "composite_score": 89.0,
        "hallucination_rate": 0.0,
        "question_type": "distracting",
        "failed_components": [],
        "threshold_breach": False,
        "evaluation_id": None,
        "evaluated_at": replay.completed_at.isoformat(),
    }
    db.add(replay)
    runs.append(replay)

    canonical = create_canonical_answer(
        db,
        workspace_id=workspace.id,
        question="What is the enterprise SLA?",
        answer="The enterprise SLA is 99.9% uptime with priority escalation within four business hours.",
        actor=owner.email or owner.username,
        source_run_id=replay.id,
    )
    canonical.hit_count = 7
    canonical_run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=systems["contract"].id,
        capability_id=systems["contract"].capability_id,
        input_ref={"query": "What is the enterprise SLA?"},
        output_ref={"response": canonical.answer, "canonical_answer_id": canonical.id, "canonical_answer_score": 1.0},
        status="completed",
        started_at=now_minus(days=0, hours=6),
        completed_at=now_minus(days=0, hours=6),
        duration_ms=0,
        trigger="canonical_answer",
        decision="answer",
        confidence=1.0,
        value_estimated=38.0,
        cost_internal=0.0,
        efficiency=999.0,
        value_source="auto",
    )
    db.add(canonical_run)
    runs.append(canonical_run)
    db.flush()

    seed_invocations(db, runs)
    seed_review_decisions(db, workspace, runs, evals, replay, canonical)
    seed_chat_session(db, workspace, owner, runs[:3])
    seed_audit(db, workspace, owner, replay, canonical)
    db.commit()
    return {"runs": len(runs), "evals": len(evals)}


def create_run_eval(
    db: DBSession,
    workspace: Workspace,
    system: System,
    *,
    query: str,
    response: str,
    composite: float,
    hallucination: float,
    question_type: str,
    failed_components: List[str],
    started_at: datetime,
    value: float,
    cost: float,
) -> tuple[Run, EvaluationScore]:
    completed = started_at + timedelta(seconds=2)
    score_id = str(uuid4())
    breach = bool(failed_components or composite < 70 or hallucination > 0.3)
    reasons = []
    if composite < 70:
        reasons.append({"metric": "composite_score", "observed": composite, "threshold": 70.0, "direction": "below"})
    if hallucination > 0.3:
        reasons.append({"metric": "hallucination_rate", "observed": hallucination, "threshold": 0.3, "direction": "above"})
    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        capability_id=system.capability_id,
        input_ref={"query": query, "context_id": workspace.slug},
        output_ref={"response": response, "sources": [{"filename": "sla-enterprise-policy.md"}, {"filename": "contract-risk-policy.md"}]},
        status="completed",
        started_at=started_at,
        completed_at=completed,
        duration_ms=1800 + int(cost * 1000),
        trigger="chat",
        decision="answer",
        confidence=max(0.1, min(0.99, composite / 100)),
        value_estimated=value,
        cost_internal=cost,
        efficiency=(value / cost) if cost else None,
        value_source="auto",
    )
    run.evaluation_scores = {
        "composite_score": composite,
        "hallucination_rate": hallucination,
        "scores": {"task_success": composite, "relevance": composite, "hallucination": max(0, 100 - hallucination * 100)},
        "threshold_breach": breach,
        "reasons": reasons,
        "question_type": question_type,
        "failed_components": failed_components,
        "topic": "SLA and contract risk",
        "evaluation_id": score_id,
        "evaluated_at": completed.isoformat(),
    }
    score = EvaluationScore(
        id=score_id,
        workspace_id=workspace.id,
        run_id=run.id,
        session_id=run.id,
        agent_id=system.id,
        turn_number=1,
        query=query,
        scores=run.evaluation_scores["scores"],
        composite_score=composite,
        hallucination_rate=hallucination,
        drift_rate=0.0,
        question_type=question_type,
        failed_components=failed_components,
        topic="SLA and contract risk",
        claim_audit={
            "supported": 3 if not breach else 1,
            "unsupported": 0 if not breach else 2,
            "claims": [
                {
                    "claim": "Enterprise SLA is 99.9% uptime",
                    "supported": not breach,
                    "source": "sla-enterprise-policy.md",
                },
                {
                    "claim": "Priority escalation is within four business hours",
                    "supported": True,
                    "source": "sla-enterprise-policy.md",
                },
                {
                    "claim": "Trial workspaces inherit enterprise SLA",
                    "supported": False if breach else True,
                    "source": "sla-enterprise-policy.md",
                },
            ],
        },
        metadata_={"showcase_seed": True, "system": system.name},
        created_at=completed,
    )
    db.add_all([run, score])
    db.flush()
    return run, score


def seed_invocations(db: DBSession, runs: List[Run]) -> None:
    for run in runs:
        for idx, slug in enumerate(["semantic_search_v1", "llm_rag_answer_v1", "claim_audit_v1"]):
            db.add(SkillInvocation(
                id=str(uuid4()),
                run_id=run.id,
                skill_slug=slug,
                input_ref={"query": run.input_ref.get("query")},
                output_ref={"status": "ok", "showcase_seed": True},
                status="completed",
                started_at=run.started_at + timedelta(milliseconds=idx * 250),
                completed_at=run.started_at + timedelta(milliseconds=(idx + 1) * 250),
                latency_ms=250 + idx * 120,
                cost=0.02 + idx * 0.03,
                metrics={"showcase_seed": True},
            ))


def active_suggestion(component: str) -> Dict[str, Any]:
    if component == "retriever":
        overrides = {"rag_pipeline_mode": "hybrid", "top_k": 8, "temperature": 0.1}
        title = "Retry with deeper hybrid retrieval"
    else:
        overrides = {"system_prompt": "Answer only from the retrieved policy context.", "temperature": 0.1}
        title = "Retry with stricter grounding"
    return {
        "version": 1,
        "source": "showcase_seed",
        "action_type": "rerun_with_overrides",
        "title": title,
        "rationale": "Repeated E1.5 component breach suggests a concrete replay remediation.",
        "overrides": overrides,
        "expected_effect": "Produce a scored replay with lower hallucination and better source grounding.",
        "confidence": 0.78,
    }


def seed_review_decisions(
    db: DBSession,
    workspace: Workspace,
    runs: List[Run],
    evals: List[EvaluationScore],
    replay: Run,
    canonical: CanonicalAnswer,
) -> None:
    breached = [score for score in evals if score.failed_components]
    for idx, score in enumerate(breached[:2]):
        run = next(r for r in runs if r.id == score.run_id)
        db.add(Decision(
            id=str(uuid4()),
            workspace_id=workspace.id,
            scope="run",
            target_id=run.id,
            kind="review_required",
            status="proposed",
            title=f"Showcase review · {score.failed_components[0]} breach",
            rationale={
                "source": SHOWCASE_SOURCE,
                "run_id": run.id,
                "evaluation_id": score.id,
                "composite_score": score.composite_score,
                "hallucination_rate": score.hallucination_rate,
                "question_type": score.question_type,
                "failed_components": score.failed_components,
                "topic": score.topic,
                "reasons": run.evaluation_scores.get("reasons", []),
                "suggestion": "Apply the active suggestion or save a canonical answer.",
                "active_suggestion": active_suggestion(score.failed_components[0]),
            },
        ))

    applied_parent = next(r for r in runs if r.id == replay.parent_run_id)
    applied = Decision(
        id=str(uuid4()),
        workspace_id=workspace.id,
        scope="run",
        target_id=applied_parent.id,
        kind="review_required",
        status="applied",
        title="Showcase applied suggestion · replay fixed grounding",
        rationale={
            "source": SHOWCASE_SOURCE,
            "run_id": applied_parent.id,
            "failed_components": ["retriever", "generator"],
            "active_suggestion": active_suggestion("retriever"),
        },
        applied_at=replay.completed_at,
        applied_by="showcase-seed",
        applied_patch={"action_type": "rerun_with_overrides", "new_run_id": replay.id, "parent_run_id": applied_parent.id},
        approved_by="showcase-seed",
        approved_at=replay.started_at,
    )
    db.add(applied)
    db.flush()
    fb = record_feedback(
        db,
        workspace_id=workspace.id,
        run_id=applied_parent.id,
        decision_id=applied.id,
        evaluation_score_id=evals[4].id if len(evals) > 4 else None,
        label="correct_with_fix",
        notes="Showcase correction promoted to canonical answer.",
        corrected_output={"answer": canonical.answer, "canonical_answer_id": canonical.id},
        actor="showcase-seed",
    )
    canonical.source_decision_id = applied.id
    canonical.source_feedback_id = fb.id


def seed_chat_session(db: DBSession, workspace: Workspace, owner: User, runs: List[Run]) -> None:
    session = ChatSession(
        id=str(uuid4()),
        user_id=owner.id,
        workspace_id=workspace.id,
        title="Showcase demo chat",
        meta_data={"showcase_seed": True},
        created_at=now_minus(days=1),
        last_activity=datetime.utcnow(),
    )
    db.add(session)
    for run in runs:
        db.add(Message(id=str(uuid4()), session_id=session.id, role="user", content=run.input_ref.get("query", ""), meta_data={"run_id": run.id}))
        db.add(Message(id=str(uuid4()), session_id=session.id, role="assistant", content=run.output_ref.get("response", ""), meta_data={"run_id": run.id, "showcase_seed": True}))


def seed_audit(db: DBSession, workspace: Workspace, owner: User, replay: Run, canonical: CanonicalAnswer) -> None:
    actor = owner.email or owner.username or "showcase-seed"
    for event_type, details in [
        ("showcase.workspace.seeded", {"workspace_slug": workspace.slug}),
        ("run.replayed", {"parent_run_id": replay.parent_run_id, "new_run_id": replay.id, "overrides": replay.replay_overrides}),
        ("canonical_answer.created", {"canonical_answer_id": canonical.id, "source_run_id": canonical.source_run_id}),
        ("canonical_answer.hit", {"canonical_answer_id": canonical.id, "hit_count": canonical.hit_count}),
        ("sharepoint.sync.completed", {"session_key": "showcase-guest-link", "files_downloaded": 6, "ingested_count": 6}),
    ]:
        emit_audit_event(
            workspace_id=workspace.id,
            event_type=event_type,
            actor=actor,
            details={**details, "showcase_seed": True},
            db=db,
        )


def seed_sharepoint_job(db: DBSession, workspace: Workspace) -> None:
    db.add(SharePointSyncJob(
        id=str(uuid4()),
        workspace_id=workspace.id,
        session_key="showcase-guest-link",
        auth_mode="session",
        state="completed",
        status="completed",
        progress="done",
        files_total=6,
        files_downloaded=6,
        bytes_total=184_320,
        ingested_count=6,
        ingest_failed_count=0,
        collection_name="documents",
        output_dir="/tmp/agentium_showcase_docs",
        folder_server_relative_url="/sites/showcase/Shared Documents/Agentium",
        created_at=now_minus(days=2),
        updated_at=now_minus(days=2),
    ))


if __name__ == "__main__":
    raise SystemExit(main())
