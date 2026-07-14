"""Seed an Agentium showcase workspace.

Usage:
    cd backend
    python -m scripts.seed_showcase_workspace \
      --owner-email "${AGENTIUM_EMAIL:?AGENTIUM_EMAIL is required}" --reset

The script is deliberately idempotent. With ``--reset`` it removes only
the target showcase workspace and rows scoped to it, then recreates the
demo story from scratch. No customer data is used.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm.attributes import flag_modified

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
from app.models.knowledge_collection import (
    KnowledgeCollection,
    KnowledgeCollectionSource,
    WorkerJob,
)
from app.models.knowledge_guide import KnowledgeGuide
from app.models.intelligence import FeedSource, SafetyFilter, SemanticTarget
from app.models.policy import AdaptivePolicy, ControlPolicy
from app.models.rag_preset import RagPreset
from app.models.run import Run, SkillInvocation
from app.models.sharepoint_sync_job import SharePointSyncJob
from app.models.skill import Skill
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.user import Session as ChatSession
from app.models.user import Message, User
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember
from app.models.workspace_job import WorkspaceJob
from app.services.audit_logger import emit_audit_event
from app.services.evaluation.canonical_answer_service import (
    create_canonical_answer,
)
from app.services.evaluation.feedback_service import record_feedback
from app.services.evaluation_preset_service import DEFAULT_EVAL_CONFIG
from app.services.knowledge_collections import (
    create_or_get_collection,
    record_ingested_sources,
    update_collection_status,
)
from app.services.knowledge_guides import create_guide, update_guide
from app.services.rag.knowledge_scopes import normalize_knowledge_scopes
from app.services.recommendations.proactive_service import (
    generate_proactive_recommendations,
)
from app.services.skills_registry import seed_skills_and_capabilities
from app.services.systems.bootstrap import ensure_workspace_chat_system_default


SHOWCASE_SOURCE = "showcase_seed"


# --- Workstream 5: universal orchestration baseline + Knowledge Capture -------
# Everything below stays GENERIC (family=generic): no "project" concept, no
# project codes, no project inventory and no cross-project matching. NorthForge
# is an invented OEM and every identifier is fictional.
NOTICES_COLLECTION = "agentium-showcase-notices"
NOTICES_SCOPE = "agentium-showcase-notices"
NOTICES_GUIDE_TITLE = "NorthForge Notices - Knowledge Guide"
EXPERT_FICHE_COLLECTION = "agentium-showcase-expert-fiche"
SHOWCASE_ADVISOR_PROFILE = "showcase_advisor"
CAPTURE_CAPABILITY_SLUG = "expert_knowledge_capture"
CAPTURE_CONTEXT_NAME = "Showcase Knowledge Capture Context"
CAPTURE_SYSTEM_NAME = "Knowledge Capture"
SHOWCASE_SEED_ACTOR = "system:showcase-seed"

# Generic business_interpretation grounding with a domain-neutral disclaimer
# (not tied to any industrial client). Demonstrates the universal default.
SHOWCASE_BALANCED_GROUNDING = {
    "default_mode": "balanced",
    "allowed_modes": ["strict", "balanced"],
    "fallback_disclaimer": (
        "Business interpretation to confirm: indexed sources stay authoritative and "
        "any documented value must be verified in the source notice."
    ),
    "strict_guard": "business_interpretation",
}
SHOWCASE_WORKSPACE_GROUNDING = {
    "default_mode": "strict",
    "allowed_modes": ["strict", "balanced"],
    "fallback_disclaimer": SHOWCASE_BALANCED_GROUNDING["fallback_disclaimer"],
    "strict_guard": "business_interpretation",
}
# Session-loop voice defaults (continuous streaming loop), generic.
SHOWCASE_VOICE_LOOP = {
    "default_mode": "session_loop",
    "enabled_default": True,
    "auto_endpoint": True,
    "auto_send_final_transcript": True,
    "auto_rearm_after_tts": True,
    "barge_in": True,
    "commands_enabled": True,
}


# Synthetic NorthForge product/operations corpus. Identifiers (PMP-700, BRG-22,
# SNS-09, VORTEX-5, FLT-3, GSK-8, LUB-40) are catalog references, never projects.
NOTICES_DOCS = {
    "northforge-pmp-700-operating-manual.md": """# NorthForge PMP-700 Operating Manual

The PMP-700 is a high-pressure process pump rated for 700 bar continuous duty.
Nominal flow is 42 L/min at 1450 rpm. Start the pump only after the FLT-3
filtration cartridge is seated and the suction line is primed. The PMP-700 uses
two BRG-22 roller bearings on the drive shaft and a GSK-8 gasket on the head.
Do not exceed the 700 bar setpoint; the relief valve opens at 735 bar.
""",
    "northforge-pmp-700-maintenance.md": """# NorthForge PMP-700 Maintenance Procedure

Preventive maintenance for the PMP-700 runs every 2000 operating hours. Replace
the FLT-3 filtration cartridge, inspect both BRG-22 bearings for play, and renew
the GSK-8 head gasket. Re-lubricate the bearings with LUB-40 service grease
(18 g per bearing). Torque the head bolts to 95 Nm in a cross pattern. Record
the bearing temperature; a BRG-22 above 80 C indicates misalignment or wear.
""",
    "northforge-brg-22-bearing-service.md": """# NorthForge BRG-22 Bearing Service Notice

The BRG-22 is a sealed roller bearing used on the PMP-700 pump and the VORTEX-5
line drive. Service life is 12000 hours under LUB-40 lubrication. Replace the
BRG-22 if radial play exceeds 0.08 mm or if running temperature stays above
80 C. Always replace bearings in pairs on the pump drive shaft. Do not reuse a
BRG-22 once removed.
""",
    "northforge-sns-09-sensor-calibration.md": """# NorthForge SNS-09 Sensor Calibration

The SNS-09 family covers proximity, pressure and temperature variants. The
proximity SNS-09 switches at 4 mm; the pressure SNS-09 spans 0-800 bar with a
4-20 mA output; the temperature SNS-09 spans -20 to 150 C. Calibrate the
pressure SNS-09 against a reference gauge at 0, 350 and 700 bar. A drift above
1.5% of span requires replacement. Mount the proximity SNS-09 flush to avoid
false triggers.
""",
    "northforge-vortex-5-operations-guide.md": """# NorthForge VORTEX-5 Operations Guide

The VORTEX-5 is the flagship production line built around one PMP-700 pump, the
SNS-09 sensor set and the BRG-22 line drive bearings. Normal throughput is 320
units/hour. Start-up sequence: energize controls, confirm all SNS-09 sensors
report healthy, prime the PMP-700, then release the line interlock. The VORTEX-5
trips if any pressure SNS-09 exceeds 720 bar or a BRG-22 over-temperature alarm
is raised.
""",
    "northforge-spare-parts-catalog.md": """# NorthForge Spare Parts Catalog

Spare parts list for the VORTEX-5 line and PMP-700 pump:

- PMP-700: high-pressure process pump assembly.
- BRG-22: roller bearing (order in pairs for the pump drive).
- SNS-09: sensor (specify proximity, pressure or temperature variant).
- FLT-3: filtration cartridge (replace every 2000 hours).
- GSK-8: gasket / O-ring seal kit for the pump head.
- LUB-40: service lubricant, 400 g cartridge.

Quote the part number when ordering. Lead time for PMP-700 assemblies is 6 weeks.
""",
    "northforge-vortex-5-commissioning-checklist.md": """# NorthForge VORTEX-5 Commissioning Checklist

Before first production run on a VORTEX-5 line:

1. Verify the PMP-700 relief valve opens at 735 bar.
2. Confirm both BRG-22 bearings are greased with LUB-40.
3. Calibrate every pressure SNS-09 at 0, 350 and 700 bar.
4. Seat a new FLT-3 cartridge and confirm the GSK-8 gasket is in place.
5. Run the start-up interlock test and record the trip thresholds.

Sign off the checklist before releasing the line to operations.
""",
    "northforge-safety-conformity.md": """# NorthForge Safety and Declaration of Conformity

The VORTEX-5 line and PMP-700 pump carry a declaration of conformity for the
machinery and pressure-equipment directives. Apply lockout/tagout before any
maintenance on the PMP-700 or BRG-22 bearings. The 700 bar circuit must be
depressurized and verified at zero before opening the GSK-8 sealed head. Only
trained personnel may bypass an SNS-09 safety sensor, and only during
commissioning.
""",
    "northforge-troubleshooting-faq.md": """# NorthForge Troubleshooting FAQ

Common faults on the VORTEX-5 line:

- Low pressure at the PMP-700: check the FLT-3 cartridge for clogging and prime
  the suction line.
- BRG-22 over-temperature alarm: check alignment and re-grease with LUB-40.
- Pressure SNS-09 reads drift: recalibrate, replace if drift exceeds 1.5% span.
- Head weeping: replace the GSK-8 gasket and re-torque the head bolts to 95 Nm.

If a fault references an identifier not present in the indexed notices, say so
rather than answering from a different product.
""",
}


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
    "translation-suite-sovereign-runbook.md": """# Translation Suite Sovereign Runbook

The Translation Suite runs inside the sovereign runtime boundary. Source
archives, DITA topics, translation memory, glossary libraries, model prompts
and reviewer corrections remain tenant scoped. Batches pin model versions,
record SHA256 manifests and expose replay/resubmission lineage for every
delivery decision.
""",
    "translation-suite-dita-guardrails.md": """# Translation Suite DITA Guardrails

DITA delivery requires byte-equal preservation of conkeyref placeholders,
root attributes, xml:lang, xtrf, cite tags, INDEX entries and translate=no
fragments. The guardrail gate blocks packaging when CDC E1 strict invariants
fail, then creates a replay with targeted overrides.
""",
    "translation-suite-j2450-qa.md": """# Translation Suite J2450 QA

The QA loop uses seven agent identities aligned with SAE J2450 categories:
Wrong Term, Syntactic Error, Omission, Word Structure, Misspelling,
Punctuation and Miscellaneous. Each agent emits severity, evidence, proposed
fix and convergence state before the supervisor computes the release verdict.
""",
    "translation-suite-model-routing.md": """# Translation Suite Model Routing

Default routing uses local vLLM for translation, local embeddings for BGE-M3
retrieval and a sovereign evaluation model for QA. Token budgets, retry limits,
parallel topic count, provider fallback policy and data-residency constraints
are declared per run and frozen in the audit trail.
""",
}


TRANSLATION_TARGET_LANGS = [
    "ar-SA",
    "bg-BG",
    "ca-ES",
    "cs-CZ",
    "da-DK",
    "de-DE",
    "el-GR",
    "en-GB",
    "es-ES",
    "es-XX",
    "et-EE",
    "fa-IR",
    "fi-FI",
    "he-IL",
    "hi-IN",
    "hr-HR",
    "hu-HU",
    "it-IT",
    "ja-JP",
    "ka-GE",
    "kk-KZ",
    "ko-KR",
    "lt-LT",
    "lv-LV",
    "mn-MN",
    "nl-NL",
    "no-NO",
    "pl-PL",
    "pt-BR",
    "pt-PT",
    "ro-RO",
    "ru-RU",
    "sk-SK",
    "sl-SI",
    "sr-RS",
    "sv-SE",
    "tr-TR",
    "uk-UA",
    "zh-CN",
]

TRANSLATION_SKILL_SLUGS = [
    "translation_archive_ingest_v1",
    "translation_memory_retrieve_v1",
    "translation_label_index_resolve_v1",
    "translation_pivot_normalize_v1",
    "translation_fanout_v1",
    "translation_j2450_qa_v1",
    "translation_post_guard_v1",
    "translation_cdt_gate_v1",
    "translation_package_delivery_v1",
    "audit_log_v1",
]


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
    {
        "slug": "showcase_translation_suite",
        "name": "Translation Suite",
        "description": "Run sovereign DITA translation batches with replay, agent QA, RBAC and audit-ready delivery gates.",
        "tier": "client",
        "industry": "regulated_translation",
        "input_unit": "dita_batch",
        "output_unit": "accepted_delivery",
        "skill_slugs": TRANSLATION_SKILL_SLUGS,
        "pricing": {"unit": "per_1000_source_words", "unit_price": 0.82, "currency": "EUR"},
        "value_per_outcome": 4_800.0,
        "confidence_threshold": 0.94,
        "sla": {
            "availability": "99.95%",
            "batch_completion_target_hours": 36,
            "max_replay_sla_hours": 4,
            "data_residency": "EU sovereign boundary",
        },
        "roi_model": {
            "seed": SHOWCASE_SOURCE,
            "value_driver": "lsp_cost_avoidance_plus_cycle_time",
            "baseline": "professional LSP delivery",
        },
    },
]


def now_minus(days: int, hours: int = 0) -> datetime:
    return datetime.utcnow() - timedelta(days=days, hours=hours)


def _non_empty_owner_email(value: str) -> str:
    owner_email = value.strip()
    if not owner_email:
        raise argparse.ArgumentTypeError("--owner-email must not be empty")
    return owner_email


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-slug", default="agentium-showcase")
    parser.add_argument("--workspace-name", default="Agentium Showcase")
    parser.add_argument(
        "--owner-email",
        required=True,
        type=_non_empty_owner_email,
        help="Existing Agentium account to provision as workspace owner",
    )
    parser.add_argument(
        "--smoke-user",
        default="alice@acme.test",
        help="Demo persona provisioned as a workspace member so the documented smoke runs out of the box; set empty to skip",
    )
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
        owner = ensure_member(db, workspace, args.owner_email, role="owner")
        if args.smoke_user and args.smoke_user != args.owner_email:
            ensure_member(db, workspace, args.smoke_user, role="owner")
        seed_skills_and_capabilities(db)
        ensure_eval_preset(db, workspace)
        controls = ensure_policies(db, workspace)
        capabilities = ensure_capabilities(db, workspace)
        systems = ensure_systems(db, workspace, capabilities, controls)
        context = ensure_context(db, workspace, systems)
        knowledge = seed_knowledge_and_capture(db, workspace, skip_ingest=args.skip_ingest)
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
        print(
            "Knowledge baseline ready: "
            f"collection={knowledge['notices_collection']} scope={knowledge['scope']} "
            f"profile={knowledge['profile']} guide={knowledge['guide_key']} "
            f"capture_system={knowledge['capture_system_id'] or 'skipped'} "
            f"expert_fiche={knowledge['expert_fiche_collection']} "
            f"chat_system={knowledge['chat_system_id'] or 'skipped'}"
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
    db.query(WorkspaceJob).filter(WorkspaceJob.workspace_id == workspace_id).delete(synchronize_session=False)
    # Knowledge baseline + capture rows (Workstream 5). Delete children before
    # the knowledge_collections parent to stay FK-safe.
    db.query(KnowledgeCollectionSource).filter(KnowledgeCollectionSource.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(WorkerJob).filter(WorkerJob.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(KnowledgeGuide).filter(KnowledgeGuide.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(KnowledgeCollection).filter(KnowledgeCollection.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(SystemVersion).filter(SystemVersion.system_id.in_(system_ids)).delete(synchronize_session=False)
    db.query(Run).filter(Run.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(System).filter(System.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(Context).filter(Context.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(ControlPolicy).filter(ControlPolicy.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(AdaptivePolicy).filter(AdaptivePolicy.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(EvaluationPreset).filter(EvaluationPreset.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(Capability).filter(Capability.workspace_id == workspace_id).delete(synchronize_session=False)
    # Workspace-scoped config/intelligence rows with a direct FK to workspaces.
    db.query(RagPreset).filter(RagPreset.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(SafetyFilter).filter(SafetyFilter.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(SemanticTarget).filter(SemanticTarget.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(FeedSource).filter(FeedSource.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(WorkspaceIAMConfig).filter(WorkspaceIAMConfig.workspace_id == workspace_id).delete(synchronize_session=False)
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


def ensure_member(db: DBSession, workspace: Workspace, email: str, role: str = "owner") -> User:
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
        db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=role))
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
            "confidence_threshold": entry.get("confidence_threshold", 0.82),
            "sla": entry.get("sla", {"target_latency_ms": 3500, "availability": "99.9%"}),
            "roi_model": entry.get("roi_model", {"seed": SHOWCASE_SOURCE, "value_driver": "time_saved"}),
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
    translation_control = db.query(ControlPolicy).filter(
        ControlPolicy.workspace_id == workspace.id,
        ControlPolicy.name.in_(["Translation Suite sovereign guardrail", "PMI Translation sovereign guardrail"]),
    ).first()
    translation_extra = {
        "showcase_seed": True,
        "brand": "PMI Sovereign Stack",
        "sovereignty": {
            "data_residency": "EU sovereign boundary",
            "external_llm_egress": False,
            "model_versions_frozen_by_batch": True,
            "artifact_hashing": "sha256_manifest",
        },
        "agent_identity": {
            "batch_agent": "agent.translation.batch",
            "qa_supervisor": "agent.translation.qa_supervisor",
            "delivery_gate": "agent.translation.delivery_gate",
        },
        "rbac": {
            "operator": ["create_batch", "replay_failed_topics"],
            "reviewer": ["approve_cdt_gate", "reject_delivery"],
            "auditor": ["read_audit", "export_manifest"],
            "admin": ["manage_models", "manage_policies"],
        },
    }
    if translation_control:
        translation_control.name = "Translation Suite sovereign guardrail"
        translation_control.max_cost_per_decision = 1_200.0
        translation_control.max_latency_ms = 36 * 60 * 60 * 1000
        translation_control.mandatory_hitl_if_confidence_below = 0.94
        translation_control.allowed_models = [
            "sovereign-vllm:unsloth/gpt-oss-20b-BF16",
            "sovereign-qa:gpt-oss-120b",
            "embedding:bge-m3",
        ]
        translation_control.allowed_skills = TRANSLATION_SKILL_SLUGS
        translation_control.extra = translation_extra
    else:
        translation_control = ControlPolicy(
            id=str(uuid4()),
            workspace_id=workspace.id,
            name="Translation Suite sovereign guardrail",
            scope="capability",
            max_cost_per_decision=1_200.0,
            max_latency_ms=36 * 60 * 60 * 1000,
            mandatory_hitl_if_confidence_below=0.94,
            allowed_models=[
                "sovereign-vllm:unsloth/gpt-oss-20b-BF16",
                "sovereign-qa:gpt-oss-120b",
                "embedding:bge-m3",
            ],
            allowed_skills=TRANSLATION_SKILL_SLUGS,
            extra=translation_extra,
        )
        db.add(translation_control)
    translation_adaptive = db.query(AdaptivePolicy).filter(
        AdaptivePolicy.workspace_id == workspace.id,
        AdaptivePolicy.name.in_(["Translation Suite replay adaptation", "PMI Translation replay adaptation"]),
    ).first()
    translation_triggers = {
        "cdc_e1_violation": "replay_topic_with_strict_placeholders",
        "j2450_above": 1.0,
        "qa_oscillation_after_loops": 5,
        "token_budget_above_percent": 85,
    }
    translation_actions = [
        "rerun_failed_topics",
        "switch_to_pivot_repair",
        "escalate_cdt_review",
        "freeze_delivery",
        "resubmit_manifest",
    ]
    translation_constraints = {
        "showcase_seed": True,
        "max_replays_per_topic": 3,
        "preserve_original_archive_hash": True,
        "human_approval_required_for_sftp_push": True,
    }
    if translation_adaptive:
        translation_adaptive.name = "Translation Suite replay adaptation"
        translation_adaptive.enabled = True
        translation_adaptive.adaptation_level = "conservative"
        translation_adaptive.scope = "capability"
        translation_adaptive.triggers = translation_triggers
        translation_adaptive.allowed_actions = translation_actions
        translation_adaptive.constraints = translation_constraints
    else:
        translation_adaptive = AdaptivePolicy(
            id=str(uuid4()),
            workspace_id=workspace.id,
            name="Translation Suite replay adaptation",
            enabled=True,
            adaptation_level="conservative",
            scope="capability",
            triggers=translation_triggers,
            allowed_actions=translation_actions,
            constraints=translation_constraints,
        )
        db.add(translation_adaptive)
    db.commit()
    return {
        "control": control,
        "adaptive": adaptive,
        "translation_control": translation_control,
        "translation_adaptive": translation_adaptive,
    }


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


PROJECT_MT_PROMPT_ROOT = "/Users/thib/Developer/PAPAI/project-mt/OM/generic_code"


def _project_mt_sources(*relative_paths: str) -> List[str]:
    return [f"{PROJECT_MT_PROMPT_ROOT}/{path}" for path in relative_paths]


def translation_prompt_contract(stage: str) -> Dict[str, Any]:
    base_builder = {
        "source_repo": PROJECT_MT_PROMPT_ROOT,
        "assembly_mode": "showcase_editable_prompt_contract",
        "runtime_placeholders": [
            "{source_lang}",
            "{target_lang}",
            "{topic_local_glossary_json}",
            "{locale_variant_instruction}",
            "{locale_translation_hints}",
            "{example_prompt}",
        ],
        "sovereignty": {
            "external_llm_egress": False,
            "model_boundary": "sovereign_vllm",
            "tenant_scope": "workspace:pmi",
        },
    }

    common_output = [
        "Keep tenant data, prompts, translation memory and reviewer corrections inside the sovereign runtime boundary.",
        "Preserve DITA/XML structure, root attributes, profiling attributes, numbers, dates, cite tags and translate=no fragments.",
        "Preserve every <ph conkeyref=\"...\"/> placeholder at the same structural position unless the node is explicitly reporting a violation.",
        "Emit auditable state with batch_id, topic_id, target_lang, agent_identity, model_ref, prompt_hash and deterministic token counters.",
    ]

    contracts: Dict[str, Dict[str, Any]] = {
        "flow": {
            "base_system_prompt": (
                "Translation Suite orchestrates sovereign DITA translation batches through archive ingest, "
                "translation memory retrieval, label/index resolution, F1 pivot normalization, F2 multilingual "
                "fan-out, J2450 QA, CDC E1 deterministic guards, human CDT approval and delivery packaging. "
                "Every autonomous step must be replayable, attributable to a distinct agent identity, and "
                "fully auditable."
            ),
            "system_prompt_builder": {
                **base_builder,
                "source_files": _project_mt_sources(
                    "prompts/trans_sys_prompt_agent_1.txt",
                    "prompts/trans_sys_prompt_agent_2_only.txt",
                    "prompts/check_sys_prompt.txt",
                    "prompts/sys_label_checker.txt",
                    "assets/rag_translator.py",
                    "assets/post_guards.py",
                ),
                "prompt_stack_order": [
                    "flow.base_system_prompt",
                    "node.system_prompt",
                    "node.rag_user_prompt_builder",
                    "node.answer_shaping_instructions",
                    "runtime.guardrail_contract",
                ],
            },
            "answer_shaping_instructions": common_output
            + [
                "Prefer deterministic, machine-readable payloads over prose when the node feeds another pipeline stage.",
                "Make replay and resubmission decisions explicit instead of silently repairing safety-critical defects.",
            ],
        },
        "translation_archive_ingest_v1": {
            "system_prompt": (
                "You are the Translation Suite archive ingestion agent. Validate the incoming 4D DITA source "
                "archive before any model invocation. Verify manifest SHA256, tenant scope, archive completeness, "
                "topic count, source language folder, DITA root attributes and metadata-only handling. Do not "
                "translate. Emit deterministic ingestion evidence for downstream replay."
            ),
            "system_prompt_builder": {
                **base_builder,
                "source_files": _project_mt_sources(
                    "assets/script_validator.py",
                    "assets/history_preparation_and_validation.py",
                    "assets/config.py",
                ),
                "inputs": ["source_archive_ref", "manifest_sha256", "tenant_scope", "topic_count"],
            },
            "rag_user_prompt_builder": {
                "retrieval_scope": "archive_manifest_only",
                "evidence_required": ["manifest_hash", "topic_inventory", "language_folder", "tenant_scope"],
            },
            "answer_shaping_instructions": common_output
            + [
                "Return an ingestion report with pass/fail checks, normalized topic inventory and replay checkpoint id.",
                "Never expose raw customer source content in the report; reference topic ids and hashes.",
            ],
        },
        "translation_memory_retrieve_v1": {
            "system_prompt": (
                "You are the sovereign translation memory retrieval agent. Build the topic-local memory bundle "
                "used by F1 and F2 from reviewed bilingual examples, glossary mappings and BGE-M3 retrieval. "
                "Prioritize exact and near-exact automotive service matches, then surface terminology constraints "
                "without leaking tenant data outside the workspace."
            ),
            "system_prompt_builder": {
                **base_builder,
                "source_files": _project_mt_sources(
                    "assets/rag_translator.py",
                    "assets/topic_glossary.py",
                    "assets/embedding_api.py",
                    "prompts/glossary_automotive.json",
                ),
                "inputs": ["topic_id", "source_lang", "target_lang", "k_examples", "translation_history_base"],
            },
            "rag_user_prompt_builder": {
                "retrieval_scope": "reviewed_translation_memory",
                "assembly_order": ["exact_examples", "near_examples", "topic_local_glossary", "locale_hints"],
                "max_examples": 2,
            },
            "answer_shaping_instructions": common_output
            + [
                "Return JSON containing exact_matches, near_matches, topic_local_glossary_json and retrieval_token_count.",
                "Do not synthesize examples; every example must include its memory reference id.",
            ],
        },
        "translation_label_index_resolve_v1": {
            "system_prompt": (
                "You are the label and index resolver for Translation Suite. Resolve REFERENT, INDEX and "
                "TEXTES-LOCA-GAMA library findings before translation. Preserve opaque <ph conkeyref=\"...\"/> "
                "placeholders byte-for-byte, keep @@ immutable markers only when the source carries an equivalent "
                "marker, and classify indexterm text as translatable content unless protected by conkeyref, cite "
                "or translate=no."
            ),
            "system_prompt_builder": {
                **base_builder,
                "source_files": _project_mt_sources(
                    "prompts/sys_label_checker.txt",
                    "prompts/trans_sys_prompt_agent_2_only_label_index.txt",
                    "prompts/trans_user_prompt_agent_2_only_label_index.txt",
                    "assets/index_lib_findings_manifest.py",
                    "assets/index_library_aware_guards.py",
                ),
                "inputs": ["source_xml", "library_ref_path", "topic_local_glossary_json"],
            },
            "rag_user_prompt_builder": {
                "retrieval_scope": "referent_index_textes_loca_gama",
                "labels": ["REFERENT", "INDEX", "TEXTES-LOCA-GAMA"],
            },
            "answer_shaping_instructions": common_output
            + [
                "Return a structured label/index resolution plan and immutable placeholder inventory.",
                "Do not replace a conkeyref placeholder with its resolved glossary token.",
            ],
        },
        "translation_pivot_normalize_v1": {
            "system_prompt": (
                "You are a professional {source_lang}-to-{target_lang} translator specializing in Renault "
                "automotive service DITA content. This is the F1 pivot pass, typically fr-FR to en-GB. Produce "
                "a clean pivot consumed by F2 fan-out; terminology drift here is multiplied across every target "
                "locale. Strictly follow reviewed examples when a match exists. If no match exists, translate "
                "with automotive service terminology, complete semantic fidelity and no additions. Preserve all "
                "XML/DITA tags, root topic attributes, profiling attributes, numbers and dates. Preserve every "
                "<ph conkeyref=\"REFERENT/...\"/>, <ph conkeyref=\"GAMA/...\"/> and <ph conkeyref=\"OPTIONS/...\"/> "
                "placeholder exactly, without adding the literal term beside it. Use {topic_local_glossary_json} "
                "consistently within the topic. Output only translated DITA XML; no Markdown, no explanation."
            ),
            "system_prompt_builder": {
                **base_builder,
                "source_files": _project_mt_sources(
                    "prompts/trans_sys_prompt_agent_1.txt",
                    "prompts/trans_user_prompt_agent_2_only.txt",
                    "assets/topic_glossary.py",
                    "assets/prompt_overlays.py",
                ),
                "inputs": ["source_xml", "source_lang", "target_lang", "topic_local_glossary_json", "example_prompt"],
            },
            "rag_user_prompt_builder": {
                "retrieval_scope": "f1_pivot_examples",
                "assembly_order": ["topic_local_glossary_json", "locale_variant_instruction", "locale_translation_hints", "example_prompt"],
            },
            "answer_shaping_instructions": common_output
            + [
                "Output only the en-GB pivot DITA XML, starting with XML declaration or the root element and ending with the root closing tag.",
                "Keep topic-local terminology stable across b, entry, title, p, li and indexterm content.",
            ],
        },
        "translation_fanout_v1": {
            "system_prompt": (
                "You are a professional {source_lang}-to-{target_lang} translator specializing in Renault "
                "automotive service DITA content. Translate the pivot into accurate {target_lang} while strictly "
                "following reviewed examples, tone, terminology and locale hints. Do not return {source_lang}; "
                "the output must be 100% {target_lang} except content explicitly protected by conkeyref, cite or "
                "translate=no. Preserve XML/DITA tags, root topic attributes, profiling attributes, numbers and "
                "dates. Opaque <ph conkeyref=\"...\"/> placeholders are never translated, duplicated, moved, dropped "
                "or replaced by their literal glossary token. Editorial <ph brand=\"...\">text</ph> elements are "
                "content: keep the wrapper and brand attribute exactly, but translate the inner text. Preserve "
                "paragraph text around placeholders; never collapse a paragraph to a placeholder-only paragraph "
                "when the source contains safety-critical surrounding text. CDC E1 STRICT: every REFERENT "
                "placeholder must appear at the same structural position with the same conkeyref value. Output "
                "only translated DITA XML; no Markdown fences, no prefixes, no explanations and nothing after "
                "the root closing tag."
            ),
            "system_prompt_builder": {
                **base_builder,
                "source_files": _project_mt_sources(
                    "prompts/trans_sys_prompt_agent_2_only.txt",
                    "prompts/trans_user_prompt_agent_2_only.txt",
                    "assets/cdc_e1_strict_inlining.py",
                    "assets/token_glossary_duplicate.py",
                    "assets/empty_paragraph_around_conkeyref.py",
                ),
                "inputs": [
                    "pivot_xml",
                    "source_lang",
                    "target_lang",
                    "topic_local_glossary_json",
                    "locale_variant_instruction",
                    "locale_translation_hints",
                    "example_prompt",
                ],
            },
            "rag_user_prompt_builder": {
                "retrieval_scope": "f2_target_locale_examples",
                "assembly_order": ["pivot_xml", "target_locale_memory", "locale_hints", "cdc_e1_guard_context"],
                "parallelism_key": "target_lang",
            },
            "answer_shaping_instructions": common_output
            + [
                "Output only translated DITA XML for the target locale.",
                "Never inline canonical glossary tokens such as OK, P, ISOFIX, Airbag, AdBlue, ABS or ESC beside their placeholder.",
                "For inflected languages, apply grammar in surrounding text while keeping the placeholder unchanged.",
            ],
        },
        "translation_j2450_qa_v1": {
            "system_prompt": (
                "You are the Translation Suite J2450 QA supervisor. Compare source and target XML line by line, "
                "then coordinate seven SAE J2450 agent categories: WT, SE, OM, SA, SP, PE and ME. Correct missing "
                "or misplaced tags, placeholder count/order/position defects, untranslated content, omissions, "
                "terminology drift and punctuation or formatting defects. Preserve valid target-language wording "
                "when no defect is proven. Return corrected target XML plus structured QA evidence for convergence."
            ),
            "system_prompt_builder": {
                **base_builder,
                "source_files": _project_mt_sources(
                    "prompts/check_sys_prompt.txt",
                    "prompts/check_user_prompt.txt",
                    "prompts/qa_refine_sys.txt",
                    "assets/QA_agents.py",
                    "assets/QA_coherence_agent.py",
                ),
                "inputs": ["source_xml", "target_xml", "source_lang", "target_lang", "j2450_registry"],
            },
            "rag_user_prompt_builder": {
                "retrieval_scope": "qa_examples_and_j2450_findings",
                "agent_categories": ["WT", "SE", "OM", "SA", "SP", "PE", "ME"],
                "max_iterations": 5,
            },
            "answer_shaping_instructions": common_output
            + [
                "Return corrected_target_xml, findings, severities, evidence_spans and convergence_state.",
                "Block convergence when a CDC E1 placeholder, XML integrity or omission defect remains.",
            ],
        },
        "translation_post_guard_v1": {
            "system_prompt": (
                "You are the deterministic CDC E1 post-guard agent. Validate translated DITA without creative "
                "rewriting. Enforce XML parseability, conkeyref byte-equality, placeholder structural parity, "
                "root attribute preservation, translate=no protection, indexterm policy, RTL directionality and "
                "LLM artifact sanitation. If a hard invariant fails, freeze delivery and emit BLOCK_RELEASE with "
                "a targeted replay plan instead of silently repairing the batch."
            ),
            "system_prompt_builder": {
                **base_builder,
                "source_files": _project_mt_sources(
                    "assets/post_guards.py",
                    "assets/cdc_e1_strict_inlining.py",
                    "assets/output_sanitizer.py",
                    "assets/llm_artefact_sanitizer.py",
                    "assets/span_contract.py",
                ),
                "inputs": ["source_xml", "candidate_xml", "target_lang", "qa_report"],
            },
            "rag_user_prompt_builder": {
                "retrieval_scope": "guardrail_policy_only",
                "blocking_modes": ["cdc_e1_strict", "xml_integrity", "j2450_gate"],
            },
            "answer_shaping_instructions": common_output
            + [
                "Return guardrail_verdict, blocking_findings, replay_overrides and a hash of the checked artifact.",
                "Never downgrade a safety-critical CDC E1 defect to a warning.",
            ],
        },
        "release_gate": {
            "system_prompt": (
                "You are the Translation Suite release gate policy agent. Evaluate QA convergence, CDC E1 guard "
                "results, manifest hashes, replay lineage, RBAC state and human-approval requirements before any "
                "delivery action. Return one deterministic verdict: ACCEPT_4D, ACCEPT_4D_WITH_VARIANCES, "
                "NEEDS_REVIEW or BLOCK_RELEASE."
            ),
            "system_prompt_builder": {
                **base_builder,
                "source_files": _project_mt_sources("assets/post_guards.py", "assets/metrics.py", "assets/topic_metrics.py"),
                "inputs": ["qa_report", "guardrail_report", "manifest", "replay_lineage"],
            },
            "answer_shaping_instructions": common_output
            + [
                "Return verdict, reason_codes, required_next_step and audit_event_type.",
                "Route BLOCK_RELEASE and NEEDS_REVIEW to remediation; route accepted verdicts to CDT approval.",
            ],
        },
        "cdt_gate": {
            "system_prompt": (
                "You are preparing the CDT human approval packet. Present the reviewer with the batch identity, "
                "accepted verdict, residual variances, manifest hashes, J2450 summary, CDC E1 guard summary, "
                "agent identities and simulated SFTP destination. Do not approve automatically; record the human "
                "decision as the authority for package release."
            ),
            "system_prompt_builder": {
                **base_builder,
                "source_files": _project_mt_sources("assets/metrics.py", "assets/history_preparation_and_validation.py"),
                "inputs": ["accepted_manifest", "qa_summary", "guardrail_summary", "reviewer_identity"],
            },
            "answer_shaping_instructions": common_output
            + [
                "Return approval_request, reviewer_scope, evidence_links and required_signoff.",
                "Keep the final release decision attributable to human.translation.reviewer.",
            ],
        },
        "translation_package_delivery_v1": {
            "system_prompt": (
                "You are the Translation Suite delivery packager. After an accepted release gate and CDT approval, "
                "package translated DITA output, QA report, CDC guard report, replay lineage, manifest and SHA256 "
                "hashes. Simulate SFTP delivery evidence without external egress and write the delivery ledger entry."
            ),
            "system_prompt_builder": {
                **base_builder,
                "source_files": _project_mt_sources(
                    "assets/output_sanitizer.py",
                    "assets/history_preparation_and_validation.py",
                    "assets/metrics.py",
                ),
                "inputs": ["approved_manifest", "artifact_hashes", "delivery_channel", "reviewer_decision"],
            },
            "answer_shaping_instructions": common_output
            + [
                "Return package_ref, manifest_sha256, delivery_receipt_ref and immutable audit ledger id.",
                "Do not package artifacts when human approval or accepted verdict evidence is missing.",
            ],
        },
        "translation_replay_remediation_v1": {
            "system_prompt": (
                "You are the replay remediation planner for Translation Suite. For a blocked topic or language, "
                "freeze delivery, isolate the failed invariant, pin the same model and prompt versions, and create "
                "a bounded replay/resubmission plan with explicit overrides. Preserve parent_run_id lineage and "
                "make every retry auditable."
            ),
            "system_prompt_builder": {
                **base_builder,
                "source_files": _project_mt_sources(
                    "assets/post_guards.py",
                    "assets/history_preparation_and_validation.py",
                    "assets/smart_rate_limiter.py",
                ),
                "inputs": ["blocked_run_id", "blocking_findings", "replay_overrides", "max_replays_per_topic"],
            },
            "answer_shaping_instructions": common_output
            + [
                "Return replay_plan, target_topics, replay_overrides, parent_run_id and resubmission_deadline.",
                "Never mutate the original failed run; create new stateful replay lineage.",
            ],
        },
    }
    return contracts.get(stage, contracts["flow"])


def flow_translation_suite() -> Dict[str, Any]:
    def task(
        node_id: str,
        label: str,
        skill_slug: str,
        description: str,
        *,
        agent_identity: str,
        config: Optional[Dict[str, Any]] = None,
        prompt_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "id": node_id,
            "kind": "task",
            "label": label,
            "config": {"skill_slug": skill_slug, **(config or {})},
            "data": {
                "description": description,
                "agent_identity": agent_identity,
                "runtime_ref": f"showcase.translation_suite.{skill_slug}",
                "prompt_contract": translation_prompt_contract(prompt_key or skill_slug),
            },
        }

    nodes = [
        {"id": "src", "kind": "source", "label": "4D archive"},
        task(
            "archive_ingest",
            "Archive ingest",
            "translation_archive_ingest_v1",
            "Verify source archive hash, manifest, topic count and tenant scope.",
            agent_identity="agent.translation.ingest",
            config={"artifact_policy": "metadata_only_showcase"},
        ),
        task(
            "memory_retrieve",
            "Translation memory",
            "translation_memory_retrieve_v1",
            "Retrieve reviewed bilingual examples from sovereign translation memory.",
            agent_identity="agent.translation.memory",
            config={"embedding_model": "BAAI/bge-m3", "k_examples": 2},
        ),
        task(
            "label_resolve",
            "Label and index resolver",
            "translation_label_index_resolve_v1",
            "Resolve REFERENT, INDEX and TEXTES-LOCA-GAMA values in memory, then preserve placeholders in delivery.",
            agent_identity="agent.translation.structure",
            config={"preserve_conkeyref_byte_equal": True},
        ),
        task(
            "pivot_normalize",
            "F1 pivot normalization",
            "translation_pivot_normalize_v1",
            "Normalize fr-FR source into a clean en-GB pivot while preserving DITA structure.",
            agent_identity="agent.translation.f1_pivot",
            config={"source_lang": "fr-FR", "pivot_lang": "en-GB"},
        ),
        task(
            "fanout",
            "F2 multilingual fan-out",
            "translation_fanout_v1",
            "Translate the pivot into target locales with bounded parallelism and frozen model routing.",
            agent_identity="agent.translation.f2_fanout",
            config={"target_count": len(TRANSLATION_TARGET_LANGS), "num_parallel_topics": 5},
        ),
        task(
            "qa_loop",
            "J2450 QA loop",
            "translation_j2450_qa_v1",
            "Run seven SAE J2450 QA agents plus supervisor convergence.",
            agent_identity="agent.translation.qa_supervisor",
            config={"limit_qa_loop": 5, "severity_policy": "no_error"},
        ),
        task(
            "post_guards",
            "CDC E1 post-guards",
            "translation_post_guard_v1",
            "Apply deterministic XML, placeholder, RTL and LLM-artifact guards.",
            agent_identity="agent.translation.guardrails",
            config={"blocking_modes": ["cdc_e1_strict", "xml_integrity", "j2450_gate"]},
        ),
        {
            "id": "release_gate",
            "kind": "decision",
            "label": "Release gate",
            "config": {
                "default_branch": "accept",
                "branches": [
                    {"label": "accept", "condition": "ctx.verdict in ['ACCEPT_4D', 'ACCEPT_4D_WITH_VARIANCES']"},
                    {"label": "remediate", "condition": "ctx.verdict in ['NEEDS_REVIEW', 'BLOCK_RELEASE']"},
                ],
            },
            "data": {
                "description": "Deterministic verdict before any delivery action.",
                "agent_identity": "agent.translation.delivery_gate",
                "prompt_contract": translation_prompt_contract("release_gate"),
            },
        },
        {
            "id": "cdt_gate",
            "kind": "hitl",
            "label": "CDT approval",
            "config": {"prompt": "Approve Translation Suite delivery manifest?"},
            "data": {
                "description": "Human approval gate for governed deliveries and SFTP push.",
                "agent_identity": "human.translation.reviewer",
                "prompt_contract": translation_prompt_contract("cdt_gate"),
            },
        },
        task(
            "package_delivery",
            "Package and deliver",
            "translation_package_delivery_v1",
            "Package DITA output, manifest, SHA256 hashes and simulated SFTP delivery evidence.",
            agent_identity="agent.translation.delivery",
            config={"delivery_channel": "simulated_sftp", "push_requires_human_approval": True},
        ),
        task(
            "remediation",
            "Replay remediation",
            "translation_cdt_gate_v1",
            "Freeze the delivery and create a replay/resubmission plan for failed topics.",
            agent_identity="agent.translation.replay",
            config={"mode": "replay_plan", "max_replays_per_topic": 3},
            prompt_key="translation_replay_remediation_v1",
        ),
        {"id": "sink", "kind": "sink", "label": "Delivery ledger"},
    ]
    return {
        "schema_version": 2,
        "variant": "translation_suite",
        "prompt_contract": translation_prompt_contract("flow"),
        "runtime_contract": {
            "brand": "PMI Sovereign Stack",
            "execution": "stateful_batch_with_replay",
            "white_label": True,
            "source_system": "project-mt/OM/generic_code",
        },
        "nodes": nodes,
        "edges": [
            {"from": "src", "to": "archive_ingest"},
            {"from": "archive_ingest", "to": "memory_retrieve"},
            {"from": "memory_retrieve", "to": "label_resolve"},
            {"from": "label_resolve", "to": "pivot_normalize"},
            {"from": "pivot_normalize", "to": "fanout"},
            {"from": "fanout", "to": "qa_loop"},
            {"from": "qa_loop", "to": "post_guards"},
            {"from": "post_guards", "to": "release_gate"},
            {"from": "release_gate", "to": "cdt_gate", "kind": "branch", "branch_label": "accept"},
            {"from": "cdt_gate", "to": "package_delivery"},
            {"from": "package_delivery", "to": "sink"},
            {"from": "release_gate", "to": "remediation", "kind": "branch", "branch_label": "remediate"},
            {"from": "remediation", "to": "sink"},
        ],
    }


def translation_agent_identities() -> Dict[str, Dict[str, Any]]:
    return {
        "agent.translation.ingest": {
            "role": "archive_ingest",
            "permissions": ["translation_batch.read", "translation_batch.create"],
            "credential_scope": "tenant:pmi:source_archive",
        },
        "agent.translation.memory": {
            "role": "memory_retrieval",
            "permissions": ["translation_memory.read"],
            "credential_scope": "tenant:pmi:faiss_bge_m3",
        },
        "agent.translation.structure": {
            "role": "dita_structure_guard",
            "permissions": ["translation_batch.read", "guardrail.execute"],
            "credential_scope": "tenant:pmi:dita_library",
        },
        "agent.translation.f1_pivot": {
            "role": "pivot_normalizer",
            "permissions": ["model.invoke", "translation_batch.execute"],
            "credential_scope": "model:sovereign-vllm:gpt-oss-20b",
        },
        "agent.translation.f2_fanout": {
            "role": "language_fanout",
            "permissions": ["model.invoke", "translation_batch.execute"],
            "credential_scope": "model:sovereign-vllm:gpt-oss-20b",
        },
        "agent.translation.qa_supervisor": {
            "role": "j2450_supervisor",
            "permissions": ["qa_agent.execute", "guardrail.execute"],
            "credential_scope": "model:sovereign-qa:gpt-oss-120b",
        },
        "agent.translation.guardrails": {
            "role": "deterministic_post_guard",
            "permissions": ["guardrail.execute", "delivery.freeze"],
            "credential_scope": "tenant:pmi:guardrail_policy",
        },
        "agent.translation.delivery": {
            "role": "delivery_packager",
            "permissions": ["delivery.package", "delivery.sftp_simulate"],
            "credential_scope": "tenant:pmi:delivery_manifest",
        },
        "human.translation.reviewer": {
            "role": "cdt_reviewer",
            "permissions": ["translation_batch.approve", "delivery.release"],
            "credential_scope": "workspace_role:reviewer",
        },
    }


def translation_rbac_matrix() -> Dict[str, List[str]]:
    return {
        "viewer": ["translation_batch.read", "audit_log.read"],
        "operator": [
            "translation_batch.create",
            "translation_batch.execute",
            "translation_batch.replay",
            "delivery.package",
        ],
        "translation_reviewer": [
            "translation_batch.read",
            "translation_batch.approve",
            "delivery.release",
            "audit_log.read",
        ],
        "auditor": ["translation_batch.read", "audit_log.read", "audit_log.export"],
        "admin": ["model_policy.manage", "agent_identity.manage", "policy.manage", "rbac.manage"],
    }


def translation_config_snapshot(batch_id: str = "PMI-KANGOO3-2026-06") -> Dict[str, Any]:
    return {
        "brand": "PMI Sovereign Stack",
        "white_label": True,
        "source_architecture": {
            "repo": "/Users/thib/Developer/PAPAI/project-mt/OM/generic_code",
            "pipeline": "DITA archive -> F1 pivot -> F2 fan-out -> J2450 QA -> CDC E1 guards -> CDT delivery",
            "integration_mode": "showcase_simulation_only",
        },
        "batch": {
            "batch_id": batch_id,
            "source_lang": "fr-FR",
            "pivot_lang": "en-GB",
            "target_langs": TRANSLATION_TARGET_LANGS,
            "source_archive_ref": "dita://pmi/kangoo3/owner_manual/source/fr-FR/archive.zip",
            "manifest_sha256": "7b8d1a9a6c2f76c2f3d6f2d4e16e4b90b2ef9e74fbd0a2f2a6f9f1b8e8c2d01d",
            "topic_count": 184,
            "source_words": 128_420,
        },
        "translation_job": {
            "gpu_ids": [0, 1],
            "rag_enabled": True,
            "translation_history_base": "history/renault_kangoo3_reviewed",
            "library_ref_path": "library/referent_index_textes_loca_gama.xlsx",
            "kb_dir": "kb/faiss_bge_m3_pmi_sovereign",
            "llm_provider": "sovereign_vllm",
            "safety_priority_threshold": 0.94,
            "num_parallel_topics": 5,
            "limit_qa_loop": 5,
        },
        "model_routing": {
            "translation": {
                "provider": "local_vllm",
                "model": "unsloth/gpt-oss-20b-BF16",
                "temperature": 0,
                "seed": 2450,
                "egress": "disabled",
            },
            "qa": {
                "provider": "sovereign_qa",
                "model": "gpt-oss-120b",
                "temperature": 0,
            },
            "embedding": {"provider": "local", "model": "BAAI/bge-m3"},
        },
        "guardrails": {
            "dita_preservation": [
                "conkeyref",
                "xml:lang",
                "xtrf",
                "cite",
                "INDEX",
                "translate=no",
                "root_attributes",
            ],
            "cdc_e1_strict": True,
            "j2450_categories": ["WT", "SE", "OM", "SA", "SP", "PE", "ME"],
            "blocking_verdicts": ["BLOCK_RELEASE", "REJECT"],
            "accepted_verdicts": ["ACCEPT_4D", "ACCEPT_4D_WITH_VARIANCES"],
        },
        "security": {
            "sovereignty": {
                "data_residency": "EU sovereign boundary",
                "external_llm_egress": False,
                "artifact_hashing": "sha256_manifest",
                "tenant_scope": "workspace:pmi",
            },
            "agent_identities": translation_agent_identities(),
            "rbac": translation_rbac_matrix(),
        },
        "observability": {
            "audit_tool_calls": True,
            "persist_checkpoints": True,
            "replay_lineage": True,
            "token_counters": ["prompt_tokens", "completion_tokens", "retrieval_tokens"],
            "delivery_evidence": ["manifest", "j2450_report", "cdc_guard_report", "simulated_sftp_receipt"],
        },
        "scaling": {
            "max_concurrent_language_jobs": 4,
            "max_parallel_topics": 5,
            "state_backend": "workspace_job_ledger",
            "resubmission_sla_hours": 4,
        },
        "token_performance": {
            "determinism": "temperature_0_seed_2450",
            "budget_prompt_tokens": 18_500_000,
            "budget_completion_tokens": 9_200_000,
            "actual_prompt_tokens": 14_870_000,
            "actual_completion_tokens": 6_240_000,
            "cache_hit_rate": 0.71,
        },
        "delivery": {
            "package_format": "dita_zip_plus_reports",
            "delivery_channel": "simulated_sftp",
            "cdt_gate_required": True,
            "acceptance_verdict": "ACCEPT_4D",
        },
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
        {
            "key": "translation",
            "name": "Translation Suite",
            "objective": (
                "Operate sovereign DITA translation batches with stateful replay, "
                "agent identity controls, deterministic guardrails and audit-ready delivery."
            ),
            "capability": "showcase_translation_suite",
            "flow": flow_translation_suite(),
            "prompt": "procedural",
            "retrieval": "hybrid",
            "execution_mode": "batch_processing",
            "coordination_pattern": "multi_agent_dag",
            "default_model": "sovereign-vllm:unsloth/gpt-oss-20b-BF16",
        },
    ]
    out: Dict[str, System] = {}
    for spec in specs:
        system = db.query(System).filter(
            System.workspace_id == workspace.id,
            System.name == spec["name"],
        ).first()
        cap = capabilities[spec["capability"]]
        if spec["key"] == "translation":
            policies["translation_control"].target_id = cap.id
            policies["translation_adaptive"].target_id = cap.id
        payload = {
            "objective": spec["objective"],
            "capability_id": cap.id,
            "skill_ids": cap.skill_ids or [],
            "flow_definition": spec["flow"],
            "settings": {
                "showcase_seed": True,
                "surface": "system",
                "system_type": "translation_suite" if spec["key"] == "translation" else spec["key"],
                "brand": "PMI Sovereign Stack" if spec["key"] == "translation" else "Agentium Showcase",
                **(
                    {"translation_suite": translation_config_snapshot()}
                    if spec["key"] == "translation"
                    else {}
                ),
            },
            "execution_mode": spec.get("execution_mode") or ("human_augmented" if spec["key"] == "compliance" else "real_time_decision"),
            "execution_profile": (
                {
                    "showcase_seed": True,
                    "persona": "translation_operator",
                    "stateful_execution": True,
                    "replay_supported": True,
                    "resubmission_supported": True,
                    "scaling": {"max_concurrent_language_jobs": 4, "gpu_pool": "sovereign-aigrid"},
                    "token_budget": {"input_tokens": 18_500_000, "output_tokens": 9_200_000, "determinism": "temperature_0"},
                }
                if spec["key"] == "translation"
                else {"showcase_seed": True, "persona": spec["key"]}
            ),
            "coordination_pattern": spec.get("coordination_pattern") or ("graph" if spec["flow"] else "single_agent"),
            "control_policy_id": (
                policies["translation_control"].id
                if spec["key"] == "translation"
                else policies["control"].id if spec["key"] == "compliance" else None
            ),
            "adaptive_policy_id": policies["translation_adaptive"].id if spec["key"] == "translation" else policies["adaptive"].id,
            "status": "active",
            "created_by": "showcase-seed",
            "default_prompt_type": spec["prompt"],
            "default_model": spec.get("default_model") or "gpt-4o-mini",
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
    translation_context = db.query(Context).filter(
        Context.workspace_id == workspace.id,
        Context.name == "PMI Sovereign Translation Context",
    ).first()
    translation_payload = {
        "system_id": systems["translation"].id,
        "data_refs": [
            "showcase/translation-suite-sovereign-runbook.md",
            "showcase/translation-suite-dita-guardrails.md",
            "showcase/translation-suite-j2450-qa.md",
            "showcase/translation-suite-model-routing.md",
            "dita://pmi/kangoo3/owner_manual/source/fr-FR/archive.zip",
            "manifest://pmi/kangoo3/sha256/7b8d1a9a-simulated",
        ],
        "memory_refs": [
            "translation_memory:renault_kangoo3_reviewed",
            "faiss:bge-m3:pmi_sovereign_tm_v12",
            "glossary:REFERENT_INDEX_TEXTES_LOCA_GAMA",
            "j2450_registry:wt_se_om_sa_sp_pe_me",
            "replay_lineage:cdc_e1_strict",
        ],
        "history_refs": [
            "project-mt/OM/generic_code/translation_job.py",
            "project-mt/OM/generic_code/ts_api/orchestrator.py",
            "project-mt/OM/generic_code/ts/dod.py",
            "batch_history:pmi_kangoo3_accept_4d",
        ],
        "environment_state": {
            "industry": "regulated translation",
            "region": "EU sovereign boundary",
            "source_lang": "fr-FR",
            "pivot_lang": "en-GB",
            "target_lang_count": len(TRANSLATION_TARGET_LANGS),
        },
        "business_constraints": {
            "external_llm_egress": False,
            "conkeyref_byte_equal": True,
            "human_approval_before_sftp": True,
            "replay_resubmission_required": True,
            "audit_every_tool_call": True,
        },
        "permissions": {
            "personas": ["operator", "translation_reviewer", "auditor", "admin"],
            "agent_identities": translation_agent_identities(),
            "rbac": translation_rbac_matrix(),
        },
        "ephemeral": False,
    }
    if translation_context:
        for key, value in translation_payload.items():
            setattr(translation_context, key, value)
    else:
        translation_context = Context(
            id=str(uuid4()),
            workspace_id=workspace.id,
            name="PMI Sovereign Translation Context",
            **translation_payload,
        )
        db.add(translation_context)
    db.flush()
    systems["translation"].context_id = translation_context.id
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


# --- Workstream 5 helpers -----------------------------------------------------
def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def write_notices_docs(workspace_slug: str) -> List[Path]:
    root = Path("/tmp") / "agentium_showcase_notices" / workspace_slug
    root.mkdir(parents=True, exist_ok=True)
    paths: List[Path] = []
    for name, content in NOTICES_DOCS.items():
        path = root / name
        path.write_text(content, encoding="utf-8")
        paths.append(path)
    return paths


def ensure_notices_collection(db: DBSession, workspace: Workspace) -> KnowledgeCollection:
    return create_or_get_collection(
        db,
        workspace=workspace,
        name="NorthForge Notices (Showcase)",
        description=(
            "Synthetic NorthForge product and operations notices for the universal "
            "retrieval demo. No customer data and no project concept."
        ),
        slug=NOTICES_COLLECTION,
    )


def ensure_expert_fiche_collection(db: DBSession, workspace: Workspace) -> KnowledgeCollection:
    return create_or_get_collection(
        db,
        workspace=workspace,
        name="NorthForge Expert Fiches (Showcase)",
        description=(
            "Destination collection for validated expert-capture fiches in the "
            "showcase workspace."
        ),
        slug=EXPERT_FICHE_COLLECTION,
    )


def ingest_notices_best_effort(
    db: DBSession,
    workspace: Workspace,
    collection: KnowledgeCollection,
    paths: List[Path],
) -> None:
    async def _run() -> List[Dict[str, Any]]:
        from app.services.rag.document_service import DocumentService

        svc = DocumentService(collection_name=collection.slug, workspace_slug=workspace.slug)
        results: List[Dict[str, Any]] = []
        for path in paths:
            res = await svc.ingest_document(
                str(path),
                chunk_size=500,
                chunk_overlap=50,
                collection_slug=collection.slug,
                workspace_id=workspace.id,
                collection_id=collection.id,
            )
            results.append(res or {})
        return results

    try:
        results = asyncio.run(_run())
        document_names = [path.name for path in paths]
        chunk_total = sum(int((res or {}).get("chunks_processed") or 0) for res in results)
        record_ingested_sources(
            db,
            collection=collection,
            ingest_result={"results": results},
            document_names=document_names,
            origin=SHOWCASE_SOURCE,
        )
        update_collection_status(
            db,
            collection.id,
            status="ready",
            document_names=document_names,
            document_count=len(document_names),
            chunk_count=chunk_total,
        )
        db.commit()
        print(
            f"Ingested {len(paths)} NorthForge notices into collection={collection.slug} "
            f"chunks={chunk_total}"
        )
    except Exception as exc:  # noqa: BLE001 - ingestion is best-effort
        db.rollback()
        print(f"WARN: notices ingestion skipped/failed: {exc}")


def _notices_guide_markdown() -> str:
    return (_repo_root() / "docs" / "showcase-notices-knowledge-guide.md").read_text(encoding="utf-8")


def publish_notices_guide(db: DBSession, workspace: Workspace, *, collection_slug: str) -> str:
    markdown = _notices_guide_markdown()
    user = SimpleNamespace(id=None, email=SHOWCASE_SEED_ACTOR, username=SHOWCASE_SEED_ACTOR)
    existing = (
        db.query(KnowledgeGuide)
        .filter(
            KnowledgeGuide.workspace_id == workspace.id,
            KnowledgeGuide.target_type == "collection",
            KnowledgeGuide.target_ref == collection_slug,
            KnowledgeGuide.title == NOTICES_GUIDE_TITLE,
            KnowledgeGuide.is_current.is_(True),
        )
        .first()
    )
    if existing:
        guide = update_guide(
            db,
            workspace,
            existing.guide_key,
            patch={"markdown": markdown, "status": "published"},
            user=user,
        )
        return guide.guide_key
    guide = create_guide(
        db,
        workspace,
        target_type="collection",
        target_ref=collection_slug,
        title=NOTICES_GUIDE_TITLE,
        markdown=markdown,
        status="published",
        user=user,
    )
    return guide.guide_key


def _showcase_profile_defaults(scope_key: str) -> Dict[str, Any]:
    return {
        "key": SHOWCASE_ADVISOR_PROFILE,
        "label": "Showcase Advisor",
        "subtitle": "NorthForge notices · grounded product & operations answers",
        "default_knowledge_scope": scope_key,
        "executive_mode": False,
        "tone": "technical_advisor",
        "grounding": dict(SHOWCASE_BALANCED_GROUNDING),
    }


def upsert_showcase_chat_settings(
    db: DBSession,
    workspace: Workspace,
    *,
    scope_key: str,
    collection_slug: str,
    expert_fiche_collection: str,
) -> None:
    """Stamp generic family, scope, advisor profile, grounding, source_policy
    and voice-loop defaults so the workspace chat System reflects the UNIVERSAL
    template (no project concept)."""
    settings = dict(workspace.settings or {})
    # Keep the family GENERIC so the chat System resolves the universal default
    # template rather than any industrial opt-in layer.
    settings["family"] = "generic"

    chat = _as_dict(settings.get("chat"))
    chat["grounding"] = {**SHOWCASE_WORKSPACE_GROUNDING, **_as_dict(chat.get("grounding"))}
    settings["chat"] = chat

    voice_loop = {**SHOWCASE_VOICE_LOOP, **_as_dict(settings.get("voice_loop"))}
    voice_loop["default_mode"] = "session_loop"
    voice_loop["enabled_default"] = True
    settings["voice_loop"] = voice_loop

    # Universal source policy: generic preservation + Knowledge Capture wiring.
    # No prefer_exact_references / reject_cross_project_sources / project terms.
    source_policy = _as_dict(settings.get("source_policy"))
    source_policy.update(
        {
            "mode": "workspace_scoped",
            "require_citations": True,
            "preserve_user_terms": True,
            "preserve_reference_types": ["document_name", "part_number", "identifier"],
            "expert_fiche_collection": expert_fiche_collection,
            "expert_review_required": True,
            "expert_fiche_correction_enabled": True,
        }
    )
    settings["source_policy"] = source_policy

    scopes = normalize_knowledge_scopes(settings.get("knowledge_scopes"))
    next_scope = {
        "key": scope_key,
        "label": "NorthForge Notices",
        "description": (
            "Synthetic NorthForge product and operations notices for the universal "
            "retrieval demo."
        ),
        "collection_slugs": [collection_slug],
        "default_mode": "chah",
        "top_k": 8,
        "is_default": True,
    }
    scopes = [scope for scope in scopes if scope["key"] != scope_key]
    for scope in scopes:
        scope["is_default"] = False
    scopes.append(next_scope)
    settings["knowledge_scopes"] = scopes

    raw_profiles = settings.get("assistant_profiles")
    profiles = (
        [dict(profile) for profile in raw_profiles if isinstance(profile, Mapping)]
        if isinstance(raw_profiles, list)
        else []
    )
    profiles = [p for p in profiles if str(p.get("key") or "") != SHOWCASE_ADVISOR_PROFILE]
    profiles.append(_showcase_profile_defaults(scope_key))
    settings["assistant_profiles"] = profiles
    settings["assistant_profile_default"] = SHOWCASE_ADVISOR_PROFILE

    workspace.settings = settings
    flag_modified(workspace, "settings")
    db.add(workspace)


def ensure_capture_context(
    db: DBSession,
    workspace: Workspace,
    *,
    collection_slug: str,
) -> Context:
    context = (
        db.query(Context)
        .filter(Context.workspace_id == workspace.id, Context.name == CAPTURE_CONTEXT_NAME)
        .first()
    )
    payload = {
        "data_refs": [collection_slug],
        "memory_refs": ["expert_fiche_proposals", "capture_review_queue"],
        "history_refs": ["showcase_capture_sessions"],
        "environment_state": {
            # Knowledge Capture reads context.environment_state.collection to
            # ground interviews on the connected knowledge base.
            "collection": collection_slug,
            "collection_name": collection_slug,
            "industry": "enterprise services",
            "region": "EU",
            "capture_domain": "product_operations",
        },
        "business_constraints": {
            "expert_review_required": True,
            "hitl_before_publish": True,
            "no_unverified_claims": True,
        },
        "permissions": {"personas": ["operator", "expert", "quality_owner", "admin"]},
        "ephemeral": False,
    }
    if context:
        for key, value in payload.items():
            setattr(context, key, value)
    else:
        context = Context(
            id=str(uuid4()),
            workspace_id=workspace.id,
            name=CAPTURE_CONTEXT_NAME,
            **payload,
        )
        db.add(context)
    db.flush()
    return context


def ensure_capture_system(
    db: DBSession,
    workspace: Workspace,
    *,
    capability: Capability,
    context: Context,
    collection_slug: str,
    expert_fiche_collection: str,
) -> System:
    system = (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.name == CAPTURE_SYSTEM_NAME)
        .first()
    )
    payload = {
        "objective": (
            "Run guided expert interviews that turn tacit product and operations "
            "knowledge into reviewable knowledge-base fiches, grounded in the "
            "NorthForge notices."
        ),
        "capability_id": capability.id,
        "skill_ids": list(capability.skill_ids or []),
        "flow_definition": {},
        "settings": {
            "showcase_seed": True,
            "surface": "system",
            "system_type": "knowledge_capture",
            "brand": "Agentium Showcase",
            "capture": {
                "source_collection": collection_slug,
                "expert_fiche_collection": expert_fiche_collection,
                "expert_review_required": True,
            },
        },
        "execution_mode": "human_augmented",
        "execution_profile": {
            "showcase_seed": True,
            "persona": "knowledge_capture",
            "hitl": True,
        },
        "coordination_pattern": "single_agent",
        "context_id": context.id,
        "status": "active",
        "created_by": "showcase-seed",
        "default_prompt_type": "analytical",
        "default_model": "gpt-4o-mini",
        "retrieval_mode_default": "chah",
    }
    if system:
        for key, value in payload.items():
            setattr(system, key, value)
        system.updated_at = datetime.utcnow()
    else:
        system = System(id=str(uuid4()), workspace_id=workspace.id, name=CAPTURE_SYSTEM_NAME, **payload)
        db.add(system)
        db.flush()
    ensure_system_version(db, workspace, system, {})
    return system


def seed_knowledge_and_capture(
    db: DBSession,
    workspace: Workspace,
    *,
    skip_ingest: bool,
) -> Dict[str, Any]:
    """Workstream 5: universal retrieval baseline + Knowledge Capture wiring.

    Idempotent and reset-safe. Creates the synthetic notices collection, the
    expert-fiche destination, the published Knowledge Guide, the generic
    scope/profile/source_policy, the capture Context + System, and refreshes the
    workspace chat System so the universal template is visualizable.
    """
    notices = ensure_notices_collection(db, workspace)
    expert_fiche = ensure_expert_fiche_collection(db, workspace)
    db.commit()

    upsert_showcase_chat_settings(
        db,
        workspace,
        scope_key=NOTICES_SCOPE,
        collection_slug=notices.slug,
        expert_fiche_collection=expert_fiche.slug,
    )
    db.commit()

    guide_key = publish_notices_guide(db, workspace, collection_slug=notices.slug)
    db.commit()

    capture_system_id: Optional[str] = None
    capability = (
        db.query(Capability).filter(Capability.slug == CAPTURE_CAPABILITY_SLUG).first()
    )
    if capability is None:
        print(
            f"WARN: capability '{CAPTURE_CAPABILITY_SLUG}' not seeded; "
            "skipping Knowledge Capture System wiring"
        )
    else:
        capture_context = ensure_capture_context(db, workspace, collection_slug=notices.slug)
        capture_system = ensure_capture_system(
            db,
            workspace,
            capability=capability,
            context=capture_context,
            collection_slug=notices.slug,
            expert_fiche_collection=expert_fiche.slug,
        )
        capture_context.system_id = capture_system.id
        db.add(capture_context)
        db.commit()
        capture_system_id = capture_system.id

    chat_system = ensure_workspace_chat_system_default(db, workspace.id)

    if not skip_ingest:
        paths = write_notices_docs(workspace.slug)
        ingest_notices_best_effort(db, workspace, notices, paths)

    return {
        "notices_collection": notices.slug,
        "expert_fiche_collection": expert_fiche.slug,
        "guide_key": guide_key,
        "scope": NOTICES_SCOPE,
        "profile": SHOWCASE_ADVISOR_PROFILE,
        "capture_system_id": capture_system_id,
        "chat_system_id": chat_system.id if chat_system else None,
    }


def seed_story(
    db: DBSession,
    workspace: Workspace,
    owner: User,
    systems: Dict[str, System],
    capabilities: Dict[str, Capability],
    context: Optional[Context] = None,
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
    translation_seed = seed_translation_story(db, workspace, owner, systems["translation"])
    runs.extend(translation_seed["runs"])
    evals.extend(translation_seed["evals"])
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


def translation_checkpoints(
    *,
    verdict: str,
    started_at: datetime,
    blocked_topic: Optional[str] = None,
) -> List[Dict[str, Any]]:
    stages = [
        ("archive_ingest", "created", 6),
        ("memory_retrieve", "retrieved", 11),
        ("label_resolve", "resolved", 16),
        ("pivot_normalize", "completed", 26),
        ("fanout", "completed", 58),
        ("qa_loop", "completed", 81),
        ("post_guards", "completed", 88),
        ("release_gate", verdict, 91),
        ("cdt_gate", "approved" if verdict.startswith("ACCEPT") else "review_required", 94),
        ("package_delivery", "completed" if verdict.startswith("ACCEPT") else "frozen", 100),
    ]
    checkpoints = []
    for idx, (stage, status, progress) in enumerate(stages):
        checkpoints.append(
            {
                "kind": "translation_stage",
                "stage": stage,
                "status": status,
                "progress": progress,
                "timestamp": (started_at + timedelta(minutes=idx * 3)).isoformat(),
                "verdict": verdict if stage in {"release_gate", "package_delivery"} else None,
                "blocked_topic": blocked_topic if blocked_topic and stage in {"post_guards", "release_gate"} else None,
            }
        )
    return checkpoints


def translation_output_summary(
    *,
    verdict: str,
    replayed_topics: int = 0,
    blocked_topic: Optional[str] = None,
) -> Dict[str, Any]:
    accepted = verdict.startswith("ACCEPT")
    return {
        "verdict": verdict,
        "delivery_status": "ship_ready" if accepted else "frozen_for_replay",
        "accepted_target_langs": len(TRANSLATION_TARGET_LANGS) if accepted else 0,
        "topics_total": 184,
        "topics_replayed": replayed_topics,
        "blocked_topic": blocked_topic,
        "quality": {
            "j2450_weighted_score": 0.18 if accepted else 1.42,
            "cdc_e1_violations": 0 if accepted else 1,
            "xml_integrity": "pass" if accepted else "blocked",
            "placeholder_preservation": "byte_equal" if accepted else "mismatch_detected",
        },
        "artifacts": {
            "manifest": "manifest://pmi/kangoo3/accept_4d_manifest.json",
            "j2450_report": "report://pmi/kangoo3/j2450_summary.pdf",
            "cdc_guard_report": "report://pmi/kangoo3/cdc_e1_guardrails.json",
            "delivery_package": "sftp://simulated/pmi/kangoo3/ACCEPT_4D/package.zip" if accepted else None,
        },
        "sovereignty": {
            "external_llm_egress": False,
            "model_versions_frozen": True,
            "audit_export_ready": True,
        },
    }


def create_translation_run(
    db: DBSession,
    workspace: Workspace,
    system: System,
    *,
    title: str,
    status: str,
    verdict: str,
    started_at: datetime,
    duration_minutes: int,
    confidence: float,
    value: float,
    cost: float,
    trigger: str,
    parent_run_id: Optional[str] = None,
    replay_overrides: Optional[Dict[str, Any]] = None,
    blocked_topic: Optional[str] = None,
    replayed_topics: int = 0,
) -> tuple[Run, EvaluationScore]:
    completed_at = started_at + timedelta(minutes=duration_minutes)
    score_id = str(uuid4())
    failed_components = [] if verdict.startswith("ACCEPT") else ["guardrail", "post_processing", "delivery_gate"]
    composite = 96.0 if verdict.startswith("ACCEPT") else 61.0
    hallucination = 0.0 if verdict.startswith("ACCEPT") else 0.04
    config = translation_config_snapshot()
    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        capability_id=system.capability_id,
        input_ref={
            "title": title,
            "suite": "Translation Suite",
            "configuration": config,
            "requested_verdict": verdict,
            "replay_parent_run_id": parent_run_id,
        },
        output_ref=translation_output_summary(
            verdict=verdict,
            replayed_topics=replayed_topics,
            blocked_topic=blocked_topic,
        ),
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=float(duration_minutes * 60 * 1000),
        trigger=trigger,
        parent_run_id=parent_run_id,
        replay_overrides=replay_overrides,
        decision=verdict,
        confidence=confidence,
        value_estimated=value,
        cost_internal=cost,
        efficiency=(value / cost) if cost else None,
        value_source="auto",
        checkpoints=translation_checkpoints(verdict=verdict, started_at=started_at, blocked_topic=blocked_topic),
        flow_snapshot=system.flow_definition,
    )
    run.evaluation_scores = {
        "composite_score": composite,
        "hallucination_rate": hallucination,
        "scores": {
            "task_success": composite,
            "dita_integrity": 100.0 if verdict.startswith("ACCEPT") else 62.0,
            "j2450_quality": 98.0 if verdict.startswith("ACCEPT") else 71.0,
            "sovereignty": 100.0,
            "auditability": 100.0,
        },
        "threshold_breach": bool(failed_components),
        "failed_components": failed_components,
        "question_type": "translation_batch",
        "topic": "PMI DITA translation delivery",
        "evaluation_id": score_id,
        "evaluated_at": completed_at.isoformat(),
    }
    score = EvaluationScore(
        id=score_id,
        workspace_id=workspace.id,
        run_id=run.id,
        session_id=run.id,
        agent_id=system.id,
        turn_number=1,
        query=title,
        scores=run.evaluation_scores["scores"],
        composite_score=composite,
        hallucination_rate=hallucination,
        drift_rate=0.0,
        question_type="translation_batch",
        failed_components=failed_components,
        topic="PMI DITA translation delivery",
        claim_audit={
            "supported": 6,
            "unsupported": 0 if verdict.startswith("ACCEPT") else 1,
            "claims": [
                {"claim": "No external LLM egress", "supported": True, "source": "translation-suite-model-routing.md"},
                {"claim": "CDC E1 conkeyref preservation passed", "supported": verdict.startswith("ACCEPT"), "source": "translation-suite-dita-guardrails.md"},
                {"claim": "J2450 QA agents converged", "supported": verdict.startswith("ACCEPT"), "source": "translation-suite-j2450-qa.md"},
                {"claim": "Delivery requires CDT approval", "supported": True, "source": "translation-suite-sovereign-runbook.md"},
            ],
        },
        metadata_={
            "showcase_seed": True,
            "system": system.name,
            "brand": "PMI Sovereign Stack",
            "verdict": verdict,
            "replay_parent_run_id": parent_run_id,
        },
        created_at=completed_at,
    )
    db.add_all([run, score])
    db.flush()
    seed_translation_invocations(
        db,
        run,
        verdict=verdict,
        blocked_topic=blocked_topic,
        replayed_topics=replayed_topics,
    )
    return run, score


def seed_translation_invocations(
    db: DBSession,
    run: Run,
    *,
    verdict: str,
    blocked_topic: Optional[str] = None,
    replayed_topics: int = 0,
) -> None:
    config = run.input_ref.get("configuration", {}) if isinstance(run.input_ref, dict) else {}
    accepted = verdict.startswith("ACCEPT")
    stages = [
        ("translation_archive_ingest_v1", "agent.translation.ingest", 420_000, 0.48, {"topics": 184, "archive_hash": config.get("batch", {}).get("manifest_sha256")}),
        ("translation_memory_retrieve_v1", "agent.translation.memory", 680_000, 0.92, {"examples": 368, "cache_hit_rate": 0.71}),
        ("translation_label_index_resolve_v1", "agent.translation.structure", 540_000, 0.36, {"labels_resolved": 1_248, "protected_placeholders": 3_912}),
        ("translation_pivot_normalize_v1", "agent.translation.f1_pivot", 2_940_000, 18.75, {"pivot_lang": "en-GB", "segments": 8_620}),
        ("translation_fanout_v1", "agent.translation.f2_fanout", 8_820_000, 96.40, {"target_langs": len(TRANSLATION_TARGET_LANGS), "parallel_topics": 5}),
        ("translation_j2450_qa_v1", "agent.translation.qa_supervisor", 2_160_000, 24.10, {"agents": ["WT", "SE", "OM", "SA", "SP", "PE", "ME"], "loop_count": 3 if accepted else 5}),
        ("translation_post_guard_v1", "agent.translation.guardrails", 780_000, 2.20, {"cdc_e1_violations": 0 if accepted else 1, "blocked_topic": blocked_topic}),
        ("translation_cdt_gate_v1", "human.translation.reviewer", 180_000, 0.0, {"approval": "approved" if accepted else "review_required", "replayed_topics": replayed_topics}),
        ("translation_package_delivery_v1", "agent.translation.delivery", 520_000, 1.85, {"delivery_status": "simulated_sftp_receipt" if accepted else "frozen"}),
        ("audit_log_v1", "agent.translation.delivery_gate", 40_000, 0.01, {"event_type": "translation_suite.run.completed", "verdict": verdict}),
    ]
    started = run.started_at or datetime.utcnow()
    for idx, (slug, agent_identity, latency_ms, cost, output) in enumerate(stages):
        stage_started = started + timedelta(minutes=idx * 3)
        status = "completed"
        if not accepted and slug == "translation_package_delivery_v1":
            status = "cancelled"
        db.add(SkillInvocation(
            id=str(uuid4()),
            run_id=run.id,
            skill_slug=slug,
            input_ref={
                "batch_id": config.get("batch", {}).get("batch_id", "PMI-KANGOO3-2026-06"),
                "target_langs": config.get("batch", {}).get("target_langs", TRANSLATION_TARGET_LANGS),
                "agent_identity": agent_identity,
                "rbac_scope": translation_agent_identities().get(agent_identity, {}).get("credential_scope"),
                "policy": "Translation Suite sovereign guardrail",
            },
            output_ref={
                "status": status,
                "verdict": verdict,
                "showcase_seed": True,
                **output,
            },
            status=status,
            started_at=stage_started,
            completed_at=stage_started + timedelta(milliseconds=latency_ms),
            latency_ms=float(latency_ms),
            cost=cost,
            metrics={
                "prompt_tokens": 120_000 + idx * 18_000,
                "completion_tokens": 54_000 + idx * 7_500,
                "deterministic": True,
                "external_egress": False,
            },
            trace={
                "tool_call_id": f"pmi-ts-{run.id[:8]}-{idx + 1:02d}",
                "agent_identity": agent_identity,
                "rbac_scope": translation_agent_identities().get(agent_identity, {}).get("credential_scope"),
                "checkpoint_index": idx,
                "stateful_replay_key": f"{run.id}:{slug}",
                "source_architecture_ref": "project-mt/OM/generic_code",
            },
        ))


def seed_translation_jobs(
    db: DBSession,
    workspace: Workspace,
    owner: User,
    system: System,
    runs: Dict[str, Run],
) -> None:
    actor_id = owner.id
    job_specs = [
        (
            "translation_suite_batch",
            "KANGOO3 39-locale fan-out",
            runs["accepted"],
            "completed",
            "completed",
            100,
            {"verdict": "ACCEPT_4D", "target_langs": len(TRANSLATION_TARGET_LANGS), "topics": 184},
        ),
        (
            "translation_suite_guardrail",
            "CDC E1 strict guardrail block",
            runs["blocked"],
            "completed",
            "reviewing",
            91,
            {"verdict": "BLOCK_RELEASE", "blocked_topic": "KANGOO3-OM-0423.dita"},
        ),
        (
            "translation_suite_replay",
            "Replay blocked CDC E1 topics",
            runs["replay"],
            "completed",
            "completed",
            100,
            {"verdict": "ACCEPT_4D_WITH_VARIANCES", "replayed_topics": 3},
        ),
        (
            "translation_suite_delivery",
            "ACCEPT_4D package and simulated SFTP handoff",
            runs["delivery"],
            "completed",
            "completed",
            100,
            {"verdict": "ACCEPT_4D", "receipt": "sftp://simulated/pmi/kangoo3/receipt.json"},
        ),
    ]
    for kind, title, run, status, stage, progress, result in job_specs:
        created_at = (run.started_at or datetime.utcnow()) - timedelta(minutes=5)
        db.add(WorkspaceJob(
            id=str(uuid4()),
            workspace_id=workspace.id,
            system_id=system.id,
            run_id=run.id,
            kind=kind,
            title=title,
            status=status,
            progress=progress,
            stage=stage,
            input_ref={
                "configuration": translation_config_snapshot(),
                "run_id": run.id,
            },
            result={
                "showcase_seed": True,
                "brand": "PMI Sovereign Stack",
                "dod": [
                    "archive_parsed",
                    "translation_complete",
                    "j2450_report",
                    "dita_validated",
                    "archive_packaged",
                    "cdt_notified",
                    "delivered_to_4d",
                ],
                **result,
            },
            events=[
                {"status": "created", "at": created_at.isoformat(), "actor": "agent.translation.batch"},
                {"status": "queued", "at": (created_at + timedelta(minutes=1)).isoformat(), "actor": "agent.translation.batch"},
                {"status": "running", "at": (created_at + timedelta(minutes=2)).isoformat(), "actor": "agent.translation.f2_fanout"},
                {"status": stage, "at": (run.completed_at or datetime.utcnow()).isoformat(), "actor": "agent.translation.delivery_gate"},
            ],
            created_by_user_id=actor_id,
            created_at=created_at,
            queued_at=created_at + timedelta(minutes=1),
            started_at=created_at + timedelta(minutes=2),
            completed_at=run.completed_at,
            updated_at=run.completed_at or datetime.utcnow(),
        ))


def seed_translation_decisions(
    db: DBSession,
    workspace: Workspace,
    owner: User,
    runs: Dict[str, Run],
) -> None:
    actor = owner.email or owner.username or "showcase-seed"
    db.add(Decision(
        id=str(uuid4()),
        workspace_id=workspace.id,
        scope="run",
        target_id=runs["blocked"].id,
        kind="guardrail_block",
        status="applied",
        title="CDC E1 guardrail blocked delivery and opened replay",
        rationale={
            "source": SHOWCASE_SOURCE,
            "brand": "PMI Sovereign Stack",
            "blocked_topic": "KANGOO3-OM-0423.dita",
            "violation": "conkeyref placeholder mismatch",
            "active_suggestion": {
                "action_type": "rerun_failed_topics",
                "overrides": {
                    "mode": "pivot_repair",
                    "preserve_conkeyref_byte_equal": True,
                    "target_topics": ["KANGOO3-OM-0423.dita", "KANGOO3-OM-0440.dita", "KANGOO3-OM-0451.dita"],
                },
                "confidence": 0.92,
            },
        },
        impact_estimate={"risk_avoided": "blocked defective 4D package", "resubmission_sla_hours": 4},
        approved_by=actor,
        approved_at=runs["blocked"].completed_at,
        applied_by="agent.translation.delivery_gate",
        applied_at=runs["blocked"].completed_at,
        applied_patch={"new_run_id": runs["replay"].id, "parent_run_id": runs["blocked"].id},
    ))
    db.add(Decision(
        id=str(uuid4()),
        workspace_id=workspace.id,
        scope="run",
        target_id=runs["delivery"].id,
        kind="delivery_release",
        status="applied",
        title="CDT approved ACCEPT_4D delivery manifest",
        rationale={
            "source": SHOWCASE_SOURCE,
            "brand": "PMI Sovereign Stack",
            "verdict": "ACCEPT_4D",
            "human_gate": "human.translation.reviewer",
            "audit_export_ready": True,
        },
        impact_estimate={"value_estimated": runs["delivery"].value_estimated, "lsp_cycle_time_reduced_days": 11},
        approved_by=actor,
        approved_at=runs["delivery"].completed_at,
        applied_by="agent.translation.delivery",
        applied_at=runs["delivery"].completed_at,
        applied_patch={"delivery_receipt": "sftp://simulated/pmi/kangoo3/receipt.json"},
    ))


def seed_translation_audit(
    db: DBSession,
    workspace: Workspace,
    owner: User,
    runs: Dict[str, Run],
) -> None:
    actor = owner.email or owner.username or "showcase-seed"
    events = [
        ("translation_suite.batch.configured", runs["accepted"], {"target_lang_count": len(TRANSLATION_TARGET_LANGS), "external_llm_egress": False}),
        ("translation_suite.agent.tool_call_audited", runs["accepted"], {"skill_slug": "translation_j2450_qa_v1", "agent_identity": "agent.translation.qa_supervisor"}),
        ("translation_suite.guardrail.blocked", runs["blocked"], {"blocked_topic": "KANGOO3-OM-0423.dita", "verdict": "BLOCK_RELEASE"}),
        ("translation_suite.run.replayed", runs["replay"], {"parent_run_id": runs["blocked"].id, "new_run_id": runs["replay"].id}),
        ("translation_suite.delivery.accepted", runs["delivery"], {"verdict": "ACCEPT_4D", "receipt": "sftp://simulated/pmi/kangoo3/receipt.json"}),
    ]
    for event_type, run, details in events:
        emit_audit_event(
            workspace_id=workspace.id,
            event_type=event_type,
            actor=actor,
            details={**details, "run_id": run.id, "showcase_seed": True, "brand": "PMI Sovereign Stack"},
            trace_id=run.id,
            agent_id=details.get("agent_identity") or "agent.translation.delivery_gate",
            db=db,
        )


def seed_translation_story(
    db: DBSession,
    workspace: Workspace,
    owner: User,
    system: System,
) -> Dict[str, Any]:
    runs: List[Run] = []
    evals: List[EvaluationScore] = []

    accepted, accepted_score = create_translation_run(
        db,
        workspace,
        system,
        title="KANGOO3 qualification batch - 39 locale fan-out",
        status="completed",
        verdict="ACCEPT_4D",
        started_at=now_minus(days=4, hours=6),
        duration_minutes=214,
        confidence=0.972,
        value=9_600.0,
        cost=144.25,
        trigger="scheduler",
    )
    runs.append(accepted)
    evals.append(accepted_score)

    blocked, blocked_score = create_translation_run(
        db,
        workspace,
        system,
        title="CDC E1 strict post-guard blocked conkeyref drift",
        status="completed",
        verdict="BLOCK_RELEASE",
        started_at=now_minus(days=3, hours=9),
        duration_minutes=93,
        confidence=0.78,
        value=0.0,
        cost=42.80,
        trigger="manual",
        blocked_topic="KANGOO3-OM-0423.dita",
    )
    runs.append(blocked)
    evals.append(blocked_score)

    replay, replay_score = create_translation_run(
        db,
        workspace,
        system,
        title="Replay failed topics with pivot repair and placeholder lock",
        status="completed",
        verdict="ACCEPT_4D_WITH_VARIANCES",
        started_at=now_minus(days=2, hours=13),
        duration_minutes=48,
        confidence=0.951,
        value=4_800.0,
        cost=21.60,
        trigger="replay",
        parent_run_id=blocked.id,
        replay_overrides={
            "mode": "pivot_repair",
            "target_topics": ["KANGOO3-OM-0423.dita", "KANGOO3-OM-0440.dita", "KANGOO3-OM-0451.dita"],
            "preserve_conkeyref_byte_equal": True,
            "temperature": 0,
        },
        replayed_topics=3,
    )
    runs.append(replay)
    evals.append(replay_score)

    delivery, delivery_score = create_translation_run(
        db,
        workspace,
        system,
        title="CDT approved ACCEPT_4D package and simulated SFTP handoff",
        status="completed",
        verdict="ACCEPT_4D",
        started_at=now_minus(days=1, hours=4),
        duration_minutes=31,
        confidence=0.989,
        value=12_400.0,
        cost=7.25,
        trigger="hitl",
        parent_run_id=replay.id,
        replay_overrides={"resubmission_manifest": "manifest://pmi/kangoo3/replay_accept_4d.json"},
        replayed_topics=3,
    )
    runs.append(delivery)
    evals.append(delivery_score)

    run_map = {"accepted": accepted, "blocked": blocked, "replay": replay, "delivery": delivery}
    seed_translation_jobs(db, workspace, owner, system, run_map)
    seed_translation_decisions(db, workspace, owner, run_map)
    seed_translation_audit(db, workspace, owner, run_map)
    return {"runs": runs, "evals": evals, "run_map": run_map}


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
