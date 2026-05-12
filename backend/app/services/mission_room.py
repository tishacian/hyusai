"""SENTINEL-CI demo mission-room fixtures and bootstrap helpers.

The mission room is intentionally implemented as an Agentium workspace pattern,
not as a tenant-special case. Runtime surfaces read the current workspace, while
this module provides a portable demo seed and deterministic advisory payloads.
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any, Dict, Iterable, Optional
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.core.iam.roles import WORKSPACE_CONTRIBUTOR, WORKSPACE_OWNER, legacy_role_for_template
from app.models.capability import Capability
from app.models.intelligence import FeedSource, SafetyFilter, SemanticTarget
from app.models.knowledge_collection import KnowledgeCollection
from app.models.rag_preset import RagPreset
from app.models.skill import Skill
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.audit_logger import emit_audit_event


SENTINEL_WORKSPACE_SLUG = "sentinel-ci"
SENTINEL_WORKSPACE_NAME = "SENTINEL-CI"
MISSION_ROOM_ROUTE = "/hypervisor/mission-room"


SOURCES = [
    {
        "id": "src-cabinet-brief-001",
        "label": "Note cabinet - situation nord",
        "kind": "internal_note",
        "confidence": 0.86,
        "age": "06:40",
    },
    {
        "id": "src-press-rfi-017",
        "label": "Flux presse Afrique - tensions locales",
        "kind": "rss_press",
        "confidence": 0.72,
        "age": "08:12",
    },
    {
        "id": "src-project-sante-042",
        "label": "Dossier projet - centres de sante frontaliers",
        "kind": "project_record",
        "confidence": 0.81,
        "age": "hier",
    },
    {
        "id": "src-agenda-jour-015",
        "label": "Agenda ministeriel autorise",
        "kind": "calendar",
        "confidence": 0.94,
        "age": "aujourd'hui",
    },
]

AGENDA = [
    {
        "time": "08:30",
        "title": "Conseil Defense restreint",
        "location": "Salle du Conseil - Plateau",
        "tone": "urgent",
    },
    {
        "time": "11:00",
        "title": "Point presse hebdomadaire",
        "location": "Salle presse ministere",
        "tone": "watch",
    },
    {
        "time": "13:00",
        "title": "Dejeuner Ambassadeur de France",
        "location": "Residence officielle",
        "tone": "neutral",
    },
    {
        "time": "15:00",
        "title": "Revue operations Sahel",
        "location": "Centre de commandement",
        "tone": "watch",
    },
    {
        "time": "17:40",
        "title": "Audience parlementaire",
        "location": "Assemblee Nationale",
        "tone": "neutral",
    },
]

PRIORITIES = [
    {
        "id": "prio-meeting-france",
        "kind": "next_meeting",
        "title": "Dejeuner Ambassadeur de France",
        "summary": "Trois points sensibles : cooperation FR-CI, image presse, suivi projets frontaliers.",
        "deadline": "dans 1h46",
        "sources": ["src-agenda-jour-015", "src-cabinet-brief-001"],
        "tone": "info",
    },
    {
        "id": "prio-security-north",
        "kind": "urgent",
        "title": "Situation securitaire nord",
        "summary": "Rumeurs recurrentes + projet social en retard : renforcement de coordination recommande.",
        "deadline": "avant conseil restreint",
        "sources": ["src-cabinet-brief-001", "src-press-rfi-017"],
        "tone": "critical",
    },
    {
        "id": "prio-mail-konaté",
        "kind": "mail",
        "title": "Email prioritaire - Gen. Konate",
        "summary": "Demande d'arbitrage sur reception de materiels et communication preventive.",
        "deadline": "09:15",
        "sources": ["src-cabinet-brief-001"],
        "tone": "watch",
    },
]

NEWS_SIGNALS = [
    {
        "id": "news-001",
        "title": "Rumeur persistante sur retards de programmes sociaux au nord",
        "risk_level": "high",
        "sentiment": "negative",
        "summary": "Plusieurs reprises presse et canaux locaux convergent vers un risque de perception d'abandon.",
        "source": "Presse nationale + flux RSS Afrique",
        "sources": ["src-press-rfi-017"],
    },
    {
        "id": "news-002",
        "title": "Cooperation FR-CI : reprise positive apres annonce infrastructure",
        "risk_level": "medium",
        "sentiment": "positive",
        "summary": "Le narratif institutionnel s'ameliore, mais reste fragile si les livrables terrain glissent.",
        "source": "Presse internationale",
        "sources": ["src-press-rfi-017", "src-project-sante-042"],
    },
    {
        "id": "news-003",
        "title": "Tensions nord CI : besoin d'un message preventif non militaire",
        "risk_level": "high",
        "sentiment": "mixed",
        "summary": "Signal faible recurrent ; action proposee : communication locale + rencontre autorites.",
        "source": "Veille ouverte",
        "sources": ["src-cabinet-brief-001"],
    },
]

PROJECTS = [
    {
        "id": "proj-health-north",
        "name": "Centres de sante frontaliers - Nord",
        "weather": "red",
        "progress": 63,
        "expected": 78,
        "delay_days": 24,
        "owner": "Direction programmes territoriaux",
        "cause": "Livraison et validation administrative retardees.",
        "risk": "Decalage de reception avant periode critique et amplification de rumeurs locales.",
        "options": [
            "Relance cabinet",
            "Arbitrage budgetaire",
            "Mission terrain",
            "Reunion fournisseur",
            "Replanification",
        ],
        "sources": ["src-project-sante-042", "src-cabinet-brief-001"],
    },
    {
        "id": "proj-civic-radio",
        "name": "Communication civique regionale",
        "weather": "orange",
        "progress": 71,
        "expected": 76,
        "delay_days": 8,
        "owner": "Service communication",
        "cause": "Elements de langage non valides pour deux regions sensibles.",
        "risk": "Fenetre presse courte avant conseil restreint.",
        "options": ["Validation elements de langage", "Brief prefets", "Point presse cible"],
        "sources": ["src-press-rfi-017", "src-agenda-jour-015"],
    },
    {
        "id": "proj-border-logistics",
        "name": "Logistique preventive zones frontalieres",
        "weather": "green",
        "progress": 82,
        "expected": 80,
        "delay_days": 0,
        "owner": "Cellule coordination terrain",
        "cause": "Flux stabilises, coordination interministerielle active.",
        "risk": "Surveillance a maintenir sur deux corridors.",
        "options": ["Maintien surveillance", "Brief hebdomadaire", "Suivi carte"],
        "sources": ["src-cabinet-brief-001"],
    },
]

MAP_ZONES = [
    {
        "id": "zone-nord",
        "name": "Nord",
        "level": 85,
        "tone": "critical",
        "centroid": {"x": 410, "y": 98},
        "polygon": "374,62 455,74 489,130 444,168 366,152 342,105",
        "signals": ["Projet social en retard", "Rumeurs recurrentes", "Faible presence institutionnelle"],
        "recommendations": ["Rencontre autorites locales", "Communication ciblee", "Mission terrain non militaire"],
        "sources": ["src-cabinet-brief-001", "src-project-sante-042", "src-press-rfi-017"],
    },
    {
        "id": "zone-ouest",
        "name": "Ouest",
        "level": 45,
        "tone": "watch",
        "centroid": {"x": 300, "y": 220},
        "polygon": "263,158 347,171 369,260 315,319 244,282 229,205",
        "signals": ["Flux transfrontaliers", "Besoin de couverture institutionnelle"],
        "recommendations": ["Brief prefectoral", "Suivi logistique", "Coordination regionale"],
        "sources": ["src-cabinet-brief-001"],
    },
    {
        "id": "zone-centre",
        "name": "Centre",
        "level": 25,
        "tone": "stable",
        "centroid": {"x": 430, "y": 272},
        "polygon": "371,176 470,169 511,248 476,334 382,327 342,258",
        "signals": ["Situation stable", "Projet prioritaire dans les temps"],
        "recommendations": ["Maintien veille", "Capitaliser sur communication positive"],
        "sources": ["src-project-sante-042"],
    },
    {
        "id": "zone-sud",
        "name": "Sud",
        "level": 15,
        "tone": "stable",
        "centroid": {"x": 420, "y": 410},
        "polygon": "340,335 492,344 536,438 463,499 334,473 296,390",
        "signals": ["Couverture institutionnelle forte"],
        "recommendations": ["Aucune action urgente", "Veille presse standard"],
        "sources": ["src-agenda-jour-015"],
    },
    {
        "id": "zone-est",
        "name": "Est",
        "level": 55,
        "tone": "watch",
        "centroid": {"x": 558, "y": 257},
        "polygon": "493,143 596,166 629,263 581,356 497,327 520,238",
        "signals": ["Tension mediatique", "Besoin de communication preventive"],
        "recommendations": ["Communication ciblee", "Reunion coordination", "Suivi projet local"],
        "sources": ["src-press-rfi-017"],
    },
]


def _clone(value: Any) -> Any:
    return copy.deepcopy(value)


def source_index() -> list[dict[str, Any]]:
    return _clone(SOURCES)


def overview_payload(workspace: Workspace) -> dict[str, Any]:
    return {
        "workspace": {"id": workspace.id, "slug": workspace.slug, "name": workspace.name},
        "title": "Bonjour, Ministre.",
        "date_label": "Mercredi 15 Avril 2026",
        "mode": "demo",
        "briefing_status": "ready",
        "priorities": _clone(PRIORITIES),
        "kpis": {
            "press_alerts": 16,
            "negative_articles": 16,
            "emails": 5,
            "urgent_emails": 2,
            "meetings": 5,
            "next_meeting_in": "1h46",
            "reputation_score": 50,
            "analyzed_articles": 80,
            "ops_operational_pct": 68,
            "ops_watch_pct": 22,
            "ops_critical_pct": 10,
        },
        "threat_trend": [42, 39, 41, 55, 49, 60, 38, 69],
        "communications_flow": [
            {"hour": "06h", "institutional": 12, "press": 8},
            {"hour": "08h", "institutional": 35, "press": 26},
            {"hour": "10h", "institutional": 46, "press": 34},
            {"hour": "12h", "institutional": 29, "press": 31},
            {"hour": "14h", "institutional": 38, "press": 28},
            {"hour": "16h", "institutional": 43, "press": 30},
            {"hour": "18h", "institutional": 22, "press": 18},
            {"hour": "20h", "institutional": 8, "press": 5},
        ],
        "agenda": _clone(AGENDA),
        "zones": [{"name": z["name"], "level": z["level"], "tone": z["tone"]} for z in MAP_ZONES],
        "reputation": {
            "score": 63,
            "delta": 5,
            "trend": [51, 45, 57, 43, 49, 60, 63],
        },
        "media_sources": [
            {"label": "Presse nationale", "coverage": 72, "count": 45},
            {"label": "Presse internationale", "coverage": 58, "count": 28},
            {"label": "Reseaux sociaux", "coverage": 41, "count": 156},
            {"label": "Agences de presse", "coverage": 65, "count": 18},
        ],
        "latest_alerts": _clone(NEWS_SIGNALS),
        "keywords": [
            {"label": "Ministere Defense", "count": 340, "delta": 12},
            {"label": "FACI", "count": 280, "delta": 8},
            {"label": "Sahel CI", "count": 195, "delta": 24},
            {"label": "Budget militaire", "count": 120, "delta": -5},
            {"label": "Cooperation France", "count": 95, "delta": 3},
        ],
        "assistant_prompts": [
            "Prepare-moi le brief pour le conseil restreint de 8h30.",
            "Pourquoi l'alerte Nord est-elle prioritaire ?",
            "Quelles zones demandent une action preventive non militaire ?",
        ],
        "sources": source_index(),
    }


def briefing_payload(workspace: Workspace) -> dict[str, Any]:
    return {
        "workspace": {"id": workspace.id, "slug": workspace.slug, "name": workspace.name},
        "title": "Briefing quotidien ministre",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "sections": [
            {
                "id": "situation",
                "title": "Situation du jour",
                "content": "La journee combine un conseil restreint, un point presse et un sujet nord prioritaire. Les signaux presse convergent avec un retard projet territorial.",
                "sources": ["src-cabinet-brief-001", "src-press-rfi-017"],
            },
            {
                "id": "risks",
                "title": "Risques principaux",
                "content": "Risque d'amplification mediatique au Nord si aucune action institutionnelle visible n'est annoncee avant la fin de journee.",
                "sources": ["src-project-sante-042", "src-press-rfi-017"],
            },
            {
                "id": "decisions",
                "title": "Decisions attendues",
                "content": "Arbitrer une mission terrain non militaire, valider les elements de langage presse et decider d'une relance cabinet sur le projet rouge.",
                "sources": ["src-agenda-jour-015", "src-project-sante-042"],
            },
            {
                "id": "talking_points",
                "title": "Elements de langage",
                "content": "Insister sur la coordination preventive, la continuite des services publics et le suivi transparent des projets territoriaux.",
                "sources": ["src-cabinet-brief-001"],
            },
        ],
        "actions": [
            {"id": "act-brief-dircab", "label": "Créer instruction Directeur de cabinet", "target": "proj-health-north"},
            {"id": "act-press-lines", "label": "Valider éléments de langage presse", "target": "proj-civic-radio"},
            {"id": "act-map-zones", "label": "Afficher carte des zones prioritaires", "target": "zone-nord"},
        ],
        "sources": source_index(),
    }


def projects_payload(workspace: Workspace) -> dict[str, Any]:
    return {
        "workspace": {"id": workspace.id, "slug": workspace.slug, "name": workspace.name},
        "summary": {
            "total": len(PROJECTS),
            "red": sum(1 for p in PROJECTS if p["weather"] == "red"),
            "orange": sum(1 for p in PROJECTS if p["weather"] == "orange"),
            "green": sum(1 for p in PROJECTS if p["weather"] == "green"),
        },
        "projects": _clone(PROJECTS),
        "sources": source_index(),
    }


def map_payload(workspace: Workspace) -> dict[str, Any]:
    return {
        "workspace": {"id": workspace.id, "slug": workspace.slug, "name": workspace.name},
        "question": "Quelles zones necessitent une action preventive non militaire ce mois-ci ?",
        "map": {
            "country": "Cote d'Ivoire",
            "view_box": "200 40 470 480",
            "projection": "illustrative_exec_demo",
            "accuracy": "strategic_demo_not_geospatial_reference",
        },
        "zones": _clone(MAP_ZONES),
        "sources": source_index(),
    }


def news_payload(workspace: Workspace) -> dict[str, Any]:
    return {
        "workspace": {"id": workspace.id, "slug": workspace.slug, "name": workspace.name},
        "signals": _clone(NEWS_SIGNALS),
        "summary": "Trois signaux dominent : retards sociaux au nord, perception de cooperation FR-CI, et besoin d'une communication preventive non militaire.",
        "sources": source_index(),
    }


def draft_instruction_payload(
    *,
    workspace: Workspace,
    actor: str,
    target_id: str,
    target_type: str,
    instruction_type: str = "dircab_instruction",
    db: Optional[DBSession] = None,
) -> dict[str, Any]:
    project = next((p for p in PROJECTS if p["id"] == target_id), None)
    zone = next((z for z in MAP_ZONES if z["id"] == target_id), None)
    title = project["name"] if project else zone["name"] if zone else target_id
    if project:
        body = (
            f"Merci de preparer sous 24h une note d'arbitrage sur le projet '{project['name']}'. "
            f"Le projet est a {project['progress']}% au lieu de {project['expected']}%, "
            f"avec un retard estime de {project['delay_days']} jours. Cause probable : {project['cause']} "
            f"Risque identifie : {project['risk']} Proposer trois options : relance cabinet, mission terrain "
            "non militaire, ou replanification avec jalons de controle."
        )
        sources = project["sources"]
    elif zone:
        body = (
            f"Merci de coordonner une action preventive non militaire sur la zone {zone['name']}. "
            f"Niveau d'alerte {zone['level']}%. Signaux : {', '.join(zone['signals'])}. "
            f"Actions proposees : {', '.join(zone['recommendations'])}."
        )
        sources = zone["sources"]
    else:
        body = "Merci de preparer une instruction cabinet sur le sujet signale, avec sources, risque et options d'action."
        sources = []

    payload = {
        "status": "draft",
        "requires_validation": True,
        "sent": False,
        "instruction_type": instruction_type,
        "target_type": target_type,
        "target_id": target_id,
        "title": f"Instruction cabinet - {title}",
        "recipient": "Directeur de cabinet",
        "body": body,
        "sources": sources,
        "control": {
            "human_authority_required": True,
            "external_delivery": "disabled_in_demo",
            "audit": "recorded",
        },
    }
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="mission_room.instruction.drafted",
        actor=actor,
        details=payload,
    )
    return payload


def _slug_skill_ids(db: DBSession, slugs: Iterable[str]) -> list[str]:
    rows = db.query(Skill).filter(Skill.slug.in_(list(slugs))).all()
    by_slug = {row.slug: row.id for row in rows}
    return [by_slug[slug] for slug in slugs if slug in by_slug]


def _capability_by_slug(db: DBSession, slug: str) -> Optional[Capability]:
    return db.query(Capability).filter(Capability.slug == slug).first()


def _ensure_collection(db: DBSession, workspace: Workspace, slug: str, name: str, description: str) -> None:
    existing = (
        db.query(KnowledgeCollection)
        .filter(KnowledgeCollection.workspace_id == workspace.id, KnowledgeCollection.slug == slug)
        .first()
    )
    if existing:
        existing.name = name
        existing.description = description
        return
    db.add(
        KnowledgeCollection(
            workspace_id=workspace.id,
            slug=slug,
            name=name,
            description=description,
            status="created",
            document_names=[],
            vector_collection_name=f"{workspace.slug}__{slug}",
            artifact_prefix=f"workspaces/{workspace.id}/collections/{slug}",
            embedding_model="text-embedding-3-small",
            chunking_method="semantic",
            chunking_params={"demo": True, "source": "sentinel-ci"},
        )
    )


def _ensure_feed(db: DBSession, workspace: Workspace, name: str, url: str, category: str) -> None:
    existing = (
        db.query(FeedSource)
        .filter(FeedSource.workspace_id == workspace.id, FeedSource.url == url)
        .first()
    )
    if existing:
        existing.name = name
        existing.category = category
        existing.active = True
        return
    db.add(
        FeedSource(
            id=str(uuid4()),
            workspace_id=workspace.id,
            name=name,
            url=url,
            category=category,
            refresh_interval=3600,
            active=True,
        )
    )


def _ensure_target(db: DBSession, workspace: Workspace) -> None:
    name = "SENTINEL-CI ministerial signals"
    existing = (
        db.query(SemanticTarget)
        .filter(SemanticTarget.workspace_id == workspace.id, SemanticTarget.name == name)
        .first()
    )
    if existing:
        return
    db.add(
        SemanticTarget(
            id=str(uuid4()),
            workspace_id=workspace.id,
            name=name,
            description=(
                "Defense, government continuity, Cote d'Ivoire, ministerial briefing, "
                "public action, weak signals, logistics, territorial projects and crisis communication."
            ),
            keywords=["Cote d'Ivoire", "ministere", "defense", "Sahel", "rumeur", "projet", "cooperation"],
            relevance_threshold=0.18,
            active=True,
        )
    )


def _ensure_filter(db: DBSession, workspace: Workspace) -> None:
    name = "Ministerial demo safety"
    existing = (
        db.query(SafetyFilter)
        .filter(SafetyFilter.workspace_id == workspace.id, SafetyFilter.name == name)
        .first()
    )
    if existing:
        return
    db.add(
        SafetyFilter(
            id=str(uuid4()),
            workspace_id=workspace.id,
            name=name,
            prompt_template=(
                "Flag unsafe operational instructions, personal data exposure, or unsourced escalatory claims. "
                "Allow neutral public-interest news summaries and advisory non-military recommendations."
            ),
            severity="flag",
            active=True,
        )
    )


def _ensure_rag_preset(db: DBSession, workspace: Workspace) -> None:
    name = "SENTINEL-CI C-HAH briefing preset"
    existing = (
        db.query(RagPreset)
        .filter(RagPreset.workspace_id == workspace.id, RagPreset.name == name)
        .first()
    )
    config = {
        "mode": "chah",
        "topK": 6,
        "promptType": "executive_briefing",
        "asyncRetrieval": True,
        "sourcePolicy": "sources_required",
        "experience": {"demoSafeProviderLabels": True, "advisoryOnly": True},
    }
    if existing:
        existing.config = config
        existing.is_default = True
        return
    db.add(
        RagPreset(
            workspace_id=workspace.id,
            name=name,
            scope="workspace",
            scope_id=None,
            config=config,
            is_default=True,
        )
    )


def _flow(slug: str, skill_slugs: list[str], label: str) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [
        {"id": "source.workspace_signals", "type": "source", "label": "Workspace signals", "position": {"x": 40, "y": 120}},
    ]
    edges: list[dict[str, Any]] = []
    previous = "source.workspace_signals"
    for idx, skill_slug in enumerate(skill_slugs):
        node_id = f"skill.{skill_slug}"
        nodes.append(
            {
                "id": node_id,
                "type": "skill",
                "kind": "task",
                "label": skill_slug.replace("_v1", "").replace("_", " ").title(),
                "position": {"x": 320 + idx * 280, "y": 120},
                "config": {"skill_slug": skill_slug},
            }
        )
        edges.append({"from": previous, "to": node_id, "kind": "data"})
        previous = node_id
    nodes.append({"id": "sink.advisory_output", "type": "sink", "label": label, "position": {"x": 360 + len(skill_slugs) * 280, "y": 120}})
    edges.append({"from": previous, "to": "sink.advisory_output", "kind": "control"})
    return {
        "schema_version": 2,
        "variant": slug,
        "template_id": f"sentinel-ci-{slug}",
        "template_name": label,
        "nodes": nodes,
        "edges": edges,
        "policy": {"advisory_only": True, "human_validation_required": True, "sources_required": True},
        "retrieval": {"mode": "chah", "top_k": 6, "non_blocking": True},
        "voice_runtime": {"capability": "voice2voice_interaction", "transport": "backend_ws"},
    }


def _ensure_system(
    db: DBSession,
    workspace: Workspace,
    *,
    name: str,
    objective: str,
    capability_slug: str,
    skill_slugs: list[str],
    variant: str,
    execution_mode: str = "human_augmented",
) -> Optional[System]:
    capability = _capability_by_slug(db, capability_slug)
    if not capability:
        return None
    skill_ids = _slug_skill_ids(db, skill_slugs)
    existing = (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.name == name)
        .first()
    )
    flow = _flow(variant, skill_slugs, name)
    if existing:
        existing.objective = objective
        existing.capability_id = capability.id
        existing.skill_ids = skill_ids
        existing.flow_definition = flow
        existing.status = "active"
        existing.execution_mode = execution_mode
        existing.coordination_pattern = "multi_agent" if len(skill_slugs) > 2 else "single_agent"
        existing.retrieval_mode_default = "chah"
        existing.execution_profile = {
            "demo": True,
            "advisory_only": True,
            "default_route": MISSION_ROOM_ROUTE,
            "voice": "voice2voice_interaction",
        }
        return existing
    system = System(
        workspace_id=workspace.id,
        name=name,
        objective=objective,
        capability_id=capability.id,
        skill_ids=skill_ids,
        flow_definition=flow,
        execution_mode=execution_mode,
        execution_profile={
            "demo": True,
            "advisory_only": True,
            "default_route": MISSION_ROOM_ROUTE,
            "voice": "voice2voice_interaction",
        },
        coordination_pattern="multi_agent" if len(skill_slugs) > 2 else "single_agent",
        status="active",
        created_by="system:sentinel_ci_seed",
        retrieval_mode_default="chah",
    )
    db.add(system)
    return system


def ensure_sentinel_ci_workspace(db: DBSession) -> dict[str, int | str]:
    """Create/update the portable government mission-room demo workspace."""
    workspace = db.query(Workspace).filter(Workspace.slug == SENTINEL_WORKSPACE_SLUG).first()
    created = 0
    if not workspace:
        workspace = Workspace(
            id=str(uuid4()),
            name=SENTINEL_WORKSPACE_NAME,
            slug=SENTINEL_WORKSPACE_SLUG,
            mode="demo",
            settings={},
        )
        db.add(workspace)
        db.flush()
        created = 1
    workspace.name = SENTINEL_WORKSPACE_NAME
    workspace.mode = "demo"
    settings = dict(workspace.settings or {})
    settings.update(
        {
            "demo_profile": "government_mission_room",
            "default_route": MISSION_ROOM_ROUTE,
            "hide_provider_details": True,
            "mission_room": {"enabled": True, "country": "Cote d'Ivoire", "label": "ARIA"},
        }
    )
    workspace.settings = settings

    members_added = 0
    users = db.query(User).filter(User.is_active.is_(True)).all()
    for index, user in enumerate(users):
        existing = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.user_id == user.id)
            .first()
        )
        if existing:
            continue
        role_template = WORKSPACE_OWNER if user.role == "admin" or index == 0 else WORKSPACE_CONTRIBUTOR
        db.add(
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=user.id,
                role=legacy_role_for_template(role_template),
                role_template=role_template,
                custom_labels=["demo:true", "domain:government"],
            )
        )
        members_added += 1

    for slug, name, description in (
        ("sentinel-ci-ministerial-briefs", "SENTINEL-CI Ministerial Briefs", "Briefings, agenda syntheses and validated talking points."),
        ("sentinel-ci-open-intelligence", "SENTINEL-CI Open Intelligence", "RSS, public news and weak-signal summaries for the demo workspace."),
        ("sentinel-ci-projects", "SENTINEL-CI Strategic Projects", "Synthetic project records and advisory risk explanations."),
        ("sentinel-ci-territorial-map", "SENTINEL-CI Territorial Map", "Illustrative zones, signals and non-military action recommendations."),
    ):
        _ensure_collection(db, workspace, slug, name, description)

    for name, url, category in (
        ("France 24 Afrique", "https://www.france24.com/fr/afrique/rss", "afrique"),
        ("RFI Afrique", "https://www.rfi.fr/fr/afrique/rss", "afrique"),
        ("BBC Africa", "https://feeds.bbci.co.uk/news/world/africa/rss.xml", "africa"),
    ):
        _ensure_feed(db, workspace, name, url, category)
    _ensure_target(db, workspace)
    _ensure_filter(db, workspace)
    _ensure_rag_preset(db, workspace)

    system_specs = [
        {
            "name": "ARIA / SENTINEL-CI Mission Room",
            "objective": "Consolider briefing, signaux faibles, projets, carte et actions ministerielles sous controle humain.",
            "capability_slug": "government_mission_room",
            "skill_slugs": [
                "ministerial_briefing_v1",
                "news_signal_synthesis_v1",
                "project_risk_explainer_v1",
                "territorial_signal_map_v1",
                "instruction_draft_v1",
                "voice_tandem_oracle_v1",
                "audit_log_v1",
            ],
            "variant": "government_mission_room",
        },
        {
            "name": "Briefing Quotidien Ministre",
            "objective": "Produire un briefing sourcé : priorites, risques, decisions attendues, actions et elements de langage.",
            "capability_slug": "ministerial_daily_briefing",
            "skill_slugs": ["ministerial_briefing_v1", "llm_rag_answer_v1", "audit_log_v1"],
            "variant": "ministerial_daily_briefing",
        },
        {
            "name": "Veille Presse & Signaux Faibles",
            "objective": "Agreger RSS, presse et signaux faibles pour detecter les sujets sensibles avant escalation.",
            "capability_slug": "open_intelligence_watch",
            "skill_slugs": ["intelligence_batch_v1", "news_signal_synthesis_v1", "audit_log_v1"],
            "variant": "intelligence",
            "execution_mode": "continuous_monitoring",
        },
        {
            "name": "Pilotage Projets Strategiques",
            "objective": "Expliquer les projets rouges, causes probables, risques et options d'arbitrage.",
            "capability_slug": "strategic_project_pilotage",
            "skill_slugs": ["project_risk_explainer_v1", "semantic_search_v1", "instruction_draft_v1", "audit_log_v1"],
            "variant": "strategic_project_pilotage",
        },
        {
            "name": "Carte Strategique Executive",
            "objective": "Afficher les zones d'action preventive non militaire avec signaux, sources et recommandations.",
            "capability_slug": "territorial_action_map",
            "skill_slugs": ["territorial_signal_map_v1", "chain_mixed_hah_v1", "audit_log_v1"],
            "variant": "territorial_action_map",
        },
        {
            "name": "Instructions Cabinet",
            "objective": "Rediger des brouillons d'instruction sourcés, advisory-only, soumis à validation humaine.",
            "capability_slug": "executive_instruction_drafting",
            "skill_slugs": ["instruction_draft_v1", "claim_audit_v1", "audit_log_v1"],
            "variant": "executive_instruction_drafting",
        },
    ]
    systems_created = 0
    for spec in system_specs:
        before = db.query(System).filter(System.workspace_id == workspace.id, System.name == spec["name"]).count()
        _ensure_system(db, workspace, **spec)
        if before == 0:
            systems_created += 1

    db.commit()
    return {
        "workspace_slug": workspace.slug,
        "workspace_created": created,
        "members_added": members_added,
        "systems_created": systems_created,
    }
