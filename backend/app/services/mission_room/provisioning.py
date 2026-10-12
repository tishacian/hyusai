"""Idempotent provisioning of the SENTINEL-CI and Octocity Mission Room workspaces."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.models.capability import Capability
from app.models.intelligence import FeedSource, SafetyFilter, SemanticTarget
from app.models.knowledge_collection import KnowledgeCollection
from app.models.knowledge_guide import KnowledgeGuide
from app.models.rag_preset import RagPreset
from app.models.skill import Skill
from app.models.system import System
from app.models.workspace import Workspace
from app.services.action_plans import (
    ensure_action_plan_seed,
)
from app.services.demo_time_context import demo_time_context_defaults
from app.services.iam.app_entitlements import (
    lock_workspace_for_app_entitlement_mutation,
)
from app.services.systems import flow_publication
from app.services.visual_intelligence import (
    ensure_visual_intelligence_seed,
)
from app.services.workspace_calendar import (
    ensure_calendar_seed,
)
from app.services.workspace_maps import (
    ensure_workspace_map_seed,
)
from app.services.mission_room.profile import (
    MISSION_ROOM_ROOT,
    MISSION_ROOM_ROUTE,
    OCTOCITY_ASSISTANT_NAME,
    OCTOCITY_MISSION_ROOM_PROFILE,
    OCTOCITY_WORKSPACE_NAME,
    OCTOCITY_WORKSPACE_SLUG,
    SENTINEL_ASSISTANT_NAME,
    SENTINEL_EVIDENCE_GRAPH_COLLECTION,
    SENTINEL_MARITIME_INTELLIGENCE_COLLECTION,
    SENTINEL_MISSION_ROOM_PROFILE,
    SENTINEL_WORKSPACE_NAME,
    SENTINEL_WORKSPACE_SLUG,
    _ensure_workspace_members,
    _octocity_owner_emails,
    is_octocity_mission_room,
    logger,
    present_payload_for_workspace,
)
from app.services.mission_room.fixtures import (
    NAVIGATION_ITEMS,
    OCTOCITY_NAVIGATION_ITEMS,
    SENTINEL_KNOWLEDGE_GUIDES,
    SENTINEL_NEWS_FEEDS,
)
from app.services.mission_room.payloads import (
    _clone,
)


def _slug_skill_ids(db: DBSession, slugs: Iterable[str]) -> list[str]:
    rows = db.query(Skill).filter(Skill.slug.in_(list(slugs))).all()
    by_slug = {row.slug: row.id for row in rows}
    return [by_slug[slug] for slug in slugs if slug in by_slug]


def _capability_by_slug(db: DBSession, slug: str) -> Optional[Capability]:
    return db.query(Capability).filter(Capability.slug == slug).first()


def _ensure_collection(
    db: DBSession, workspace: Workspace, slug: str, name: str, description: str
) -> None:
    source = "octocity" if is_octocity_mission_room(workspace) else "sentinel-ci"
    existing = (
        db.query(KnowledgeCollection)
        .filter(KnowledgeCollection.workspace_id == workspace.id, KnowledgeCollection.slug == slug)
        .first()
    )
    if existing:
        existing.name = name
        existing.description = description
        existing.chunking_params = {
            **(existing.chunking_params or {}),
            "demo": True,
            "source": source,
        }
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
            chunking_params={"demo": True, "source": source},
        )
    )


def _ensure_sentinel_knowledge_guides(db: DBSession, workspace: Workspace) -> int:
    """Seed workspace-scoped Knowledge Guides without rewriting history."""
    changed = 0
    now = datetime.utcnow()
    for spec in SENTINEL_KNOWLEDGE_GUIDES:
        current = (
            db.query(KnowledgeGuide)
            .filter(
                KnowledgeGuide.workspace_id == workspace.id,
                KnowledgeGuide.guide_key == spec["guide_key"],
                KnowledgeGuide.is_current.is_(True),
            )
            .first()
        )
        if (
            current
            and current.target_type == spec["target_type"]
            and current.target_ref == spec["target_ref"]
            and current.title == spec["title"]
            and current.markdown == spec["markdown"]
            and current.status == "published"
        ):
            continue
        version = 1
        supersedes_id = None
        if current:
            current.is_current = False
            db.add(current)
            version = int(current.version or 1) + 1
            supersedes_id = current.id
        db.add(
            KnowledgeGuide(
                id=str(uuid4()),
                guide_key=spec["guide_key"],
                workspace_id=workspace.id,
                target_type=spec["target_type"],
                target_ref=spec["target_ref"],
                title=spec["title"],
                markdown=spec["markdown"],
                status="published",
                version=version,
                is_current=True,
                supersedes_id=supersedes_id,
                created_by_user_id=None,
                created_at=now,
                published_at=now,
            )
        )
        changed += 1
    return changed


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


def _cleanup_sentinel_demo_artifacts(db: DBSession, workspace: Workspace) -> int:
    """Hide ad hoc QA artifacts from executive Sentinel surfaces."""
    from app.models.action_plan import WorkspaceActionItem
    from app.models.calendar import WorkspaceCalendarEvent

    cleaned = 0
    for pattern in ("%agenda qa wiring%", "%qa wiring%", "%codex qa%"):
        rows = (
            db.query(WorkspaceCalendarEvent)
            .filter(
                WorkspaceCalendarEvent.workspace_id == workspace.id,
                WorkspaceCalendarEvent.status != "cancelled",
                WorkspaceCalendarEvent.title.ilike(pattern),
            )
            .all()
        )
        for row in rows:
            row.status = "cancelled"
            row.updated_at = datetime.utcnow()
            row.meta_data = {**(row.meta_data or {}), "hidden_by_demo_clean": True}
            cleaned += 1

    for pattern in (
        "action cabinet ajoutee%",
        "action cabinet ajoutée%",
        "aya, action cabinet%",
        "%resume les prochaines etapes%",
        "%résume les prochaines étapes%",
    ):
        rows = (
            db.query(WorkspaceActionItem)
            .filter(
                WorkspaceActionItem.workspace_id == workspace.id,
                WorkspaceActionItem.status != "cancelled",
                WorkspaceActionItem.title.ilike(pattern),
            )
            .all()
        )
        for row in rows:
            row.status = "cancelled"
            row.updated_at = datetime.utcnow()
            row.meta_data = {**(row.meta_data or {}), "hidden_by_demo_clean": True}
            cleaned += 1
    return cleaned


def _ensure_target(db: DBSession, workspace: Workspace) -> None:
    name = "SENTINEL-CI ministerial signals"
    description = (
        "Cote d'Ivoire ministerial watch with geographic priority CI -> CEDEAO -> Africa -> World: "
        "domestic politics, public emotion, social rumors, government continuity, territorial security, "
        "industrial/government project steering, regional diplomacy, cooperation narratives and crisis communication."
    )
    keywords = [
        "Cote d'Ivoire",
        "Ivory Coast",
        "Abidjan",
        "Yamoussoukro",
        "politique ivoirienne",
        "politique interieure",
        "Afrique de l'Ouest",
        "CEDEAO",
        "West Africa",
        "Sahel",
        "Golfe de Guinee",
        "Port d'Abidjan",
        "San-Pedro",
        "douanes",
        "maritime",
        "AIS",
        "congestion portuaire",
        "presidence",
        "vice-premier-ministre",
        "securite",
        "rumeur",
        "reseaux sociaux",
        "social listening",
        "emoi public",
        "projet public",
        "pilotage industriel",
        "cooperation",
    ]
    existing = (
        db.query(SemanticTarget)
        .filter(SemanticTarget.workspace_id == workspace.id, SemanticTarget.name == name)
        .first()
    )
    if existing:
        existing.description = description
        existing.keywords = keywords
        existing.relevance_threshold = 0.16
        existing.active = True
        return
    db.add(
        SemanticTarget(
            id=str(uuid4()),
            workspace_id=workspace.id,
            name=name,
            description=description,
            keywords=keywords,
            relevance_threshold=0.16,
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
    existing_by_name = (
        db.query(RagPreset)
        .filter(RagPreset.workspace_id == workspace.id, RagPreset.name == name)
        .first()
    )
    existing_default = (
        db.query(RagPreset)
        .filter(
            RagPreset.workspace_id == workspace.id,
            RagPreset.scope == "workspace",
            RagPreset.scope_id == workspace.id,
            RagPreset.is_default.is_(True),
        )
        .first()
    )
    config = {
        "mode": "chah",
        "ragPipelineMode": "chah",
        "rag_pipeline_mode": "chah",
        "ragVectorDBType": "qdrant",
        "ragCollectionName": "sentinel-ci-open-intelligence",
        "topK": 6,
        "ragTopK": 6,
        "promptType": "executive_briefing",
        "asyncRetrieval": True,
        "sourcePolicy": "sources_required",
        "experience": {"demoSafeProviderLabels": True, "advisoryOnly": True},
    }
    existing = existing_default or existing_by_name
    if existing:
        if existing_by_name and existing_by_name.id != existing.id:
            existing_by_name.is_default = False
        existing.name = name
        existing.config = config
        existing.scope = "workspace"
        existing.scope_id = workspace.id
        existing.workspace_id = workspace.id
        existing.is_default = True
        return
    db.add(
        RagPreset(
            workspace_id=workspace.id,
            name=name,
            scope="workspace",
            scope_id=workspace.id,
            config=config,
            is_default=True,
        )
    )


def _flow(
    slug: str, skill_slugs: list[str], label: str, *, template_prefix: str = "sentinel-ci"
) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [
        {
            "id": "source.workspace_signals",
            "type": "source",
            "label": "Workspace signals",
            "position": {"x": 40, "y": 120},
        },
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
    nodes.append(
        {
            "id": "sink.advisory_output",
            "type": "sink",
            "label": label,
            "position": {"x": 360 + len(skill_slugs) * 280, "y": 120},
        }
    )
    edges.append({"from": previous, "to": "sink.advisory_output", "kind": "control"})
    return {
        "schema_version": 2,
        "variant": slug,
        "template_id": f"{template_prefix}-{slug}",
        "template_name": label,
        "nodes": nodes,
        "edges": edges,
        "policy": {
            "advisory_only": True,
            "human_validation_required": True,
            "sources_required": True,
        },
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
    legacy_names: Optional[list[str]] = None,
    template_prefix: str = "sentinel-ci",
    created_by: str = "system:sentinel_ci_seed",
) -> Optional[System]:
    capability = _capability_by_slug(db, capability_slug)
    if not capability:
        return None
    skill_ids = _slug_skill_ids(db, skill_slugs)
    existing = (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.name.in_([name, *(legacy_names or [])]))
        .first()
    )
    flow = _flow(variant, skill_slugs, name, template_prefix=template_prefix)
    if existing:
        existing.name = name
        existing.objective = objective
        existing.capability_id = capability.id
        existing.skill_ids = skill_ids
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
        flow_publication.reconcile_system_flow(
            db,
            system=existing,
            workspace=workspace,
            flow_definition=flow,
            actor=created_by,
            publish_if_owned=True,
            ownership_prefix=created_by,
            message="Mission Room seed Flow reconciliation",
        )
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
        created_by=created_by,
        retrieval_mode_default="chah",
    )
    db.add(system)
    flow_publication.initialize_new_system_publication_if_enabled(
        db,
        system=system,
        workspace=workspace,
        actor=created_by,
    )
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
    else:
        workspace = lock_workspace_for_app_entitlement_mutation(db, workspace.id)
    workspace.name = SENTINEL_WORKSPACE_NAME
    workspace.mode = "demo"
    settings = dict(workspace.settings or {})
    settings.update(
        {
            # The family is what selects the Sentinel CI adapters (app.tenants);
            # a workspace seeded after migration 058 would otherwise be generic.
            "family": "sentinel_ci",
            "demo_profile": "government_mission_room",
            "default_route": MISSION_ROOM_ROUTE,
            "hide_provider_details": True,
            "workspace_app_shell": "immersive",
            "workspace_app_label": SENTINEL_WORKSPACE_NAME,
            "workspace_app_default_view": "cockpit",
            "calendar": {
                "mode": "internal_shared",
                "connector_id": "institutional_calendar",
                "connector_label": "Agenda institutionnel",
                "write_policy": "direct",
                "timezone": "Africa/Abidjan",
            },
            "demo_time_context": demo_time_context_defaults(),
            "action_planner": {
                "write_policy": "direct",
                "default_owner": "Cabinet",
                "advisory_only": True,
            },
            "actions": {
                "enabled_packs": [
                    "global_voice_v1",
                    "sentinel_ci_aya_v1",
                    "sentinel_ci_aya_security_v1",
                ],
                "confirmation_policy": "confirm_side_effects",
                "legacy_adapters": ["aya_action_plans"],
            },
            "voice_loop": {
                "default_mode": "session_loop",
                "enabled_default": False,
                "manual_start_required": True,
                "auto_send_final_transcript": True,
                "auto_endpoint": True,
                "auto_rearm_after_tts": True,
                "barge_in": True,
                "commands_enabled": True,
                "command_packs": [
                    "global_voice_v1",
                    "sentinel_ci_aya_v1",
                    "sentinel_ci_aya_security_v1",
                ],
                "trigger_word": "AYA",
                "stop_phrases": ["stop", "pause", "on peut s'arreter la", "annule", "arrete"],
                "silence_ms": 1050,
                "min_speech_ms": 320,
                "max_turn_ms": 45000,
                "cooldown_ms": 450,
            },
            "voice_output": {
                "latency_profile": "fast",
                "voice": "nova",
                "flush_first_chars": 18,
                "flush_next_chars": 56,
                "flush_timeout_ms": 450,
                "interrupt_on_user_speech": True,
            },
            "document_intelligence": {
                "enabled": True,
                "default_profile": "sentinel_ci_ministerial",
                "profiles": [
                    {
                        "key": "sentinel_ci_ministerial",
                        "label": "SENTINEL-CI ministerial documents",
                        "synonyms": {
                            "briefing": ["note cabinet", "fiche", "brief", "elements de langage"],
                            "decision": ["arbitrage", "instruction", "validation", "deadline"],
                            "territory": ["zone", "region", "district", "frontiere", "port"],
                        },
                        "max_candidate_facts": 1800,
                        "max_evidence_rows": 18,
                    }
                ],
                "ocr": {
                    "enabled": True,
                    "provider_priority": ["tesseract_local", "ppocr_service"],
                    "languages": ["fra", "eng"],
                    "min_confidence": 0.45,
                    "timeout_seconds": 20,
                    "required": False,
                    "openai_vision_enabled": False,
                },
                "citation_policy": "raw_source_first_page_section_paragraph",
            },
            "visual_intelligence": {
                "enabled": True,
                "capture_cadence_minutes": 60,
                "allowed_adapters": ["demo_static", "http_image", "browser_screenshot"],
                "storage_policy": "snapshot_only_no_continuous_recording",
                "analysis_policy": "no_identification_no_biometrics",
                "source_model": "live_webcam_embed_layer",
            },
            "feature_flag": {
                "security_live_osint": False,
            },
            "connectors": {
                "institutional_calendar": {
                    "enabled": True,
                    "status": "connected",
                    "mode": "internal_shared",
                    "label": "Agenda institutionnel",
                },
                "visual_streams": {
                    "enabled": True,
                    "status": "connected",
                    "mode": "live_webcam_embed_layer",
                    "label": "Flux visuels institutionnels",
                },
            },
            "assistant_profile_default": "vigie_executive",
            "knowledge_scopes": [
                {
                    "key": "vigie",
                    "label": "Presse + Rumeurs + Projets + Carte",
                    "description": "Sources qualifiees CI, CEDEAO, internationales et signaux sociaux publics pour briefing gouvernemental.",
                    "collection_slugs": [
                        "sentinel-ci-open-intelligence",
                        "sentinel-ci-projects",
                        "sentinel-ci-ministerial-briefs",
                        "sentinel-ci-territorial-map",
                        "sentinel-ci-territorial-intelligence",
                        "sentinel-ci-visual-intelligence",
                        SENTINEL_MARITIME_INTELLIGENCE_COLLECTION,
                        SENTINEL_EVIDENCE_GRAPH_COLLECTION,
                        "sentinel-ci-security-briefs",
                    ],
                    "default_mode": "chah",
                    "top_k": 8,
                    "is_default": True,
                },
                {
                    "key": "open_intelligence",
                    "label": "Presse, rumeurs et signaux faibles",
                    "description": "Articles RSS, syntheses News Lab et origines de rumeurs publiques consolides.",
                    "collection_slugs": ["sentinel-ci-open-intelligence"],
                    "default_mode": "chah",
                    "top_k": 8,
                    "is_default": False,
                },
            ],
            "assistant_profiles": [
                {
                    "key": "vigie_executive",
                    "label": SENTINEL_ASSISTANT_NAME,
                    "subtitle": "Assistante stratégique · Sources qualifiees",
                    "default_knowledge_scope": "vigie",
                    "executive_mode": True,
                    "tone": "ministerial",
                    "grounding": {
                        "default_mode": "balanced",
                        "allowed_modes": ["strict", "balanced"],
                        "fallback_disclaimer": "Je n'ai pas de source workspace sur ce point ; analyse générale à valider :",
                        "strict_guard": "default",
                    },
                    "actions": {
                        "enabled_packs": [
                            "global_voice_v1",
                            "sentinel_ci_aya_v1",
                            "sentinel_ci_aya_security_v1",
                        ],
                        "confirmation_policy": "confirm_side_effects",
                    },
                    "voice_loop": {
                        "default_mode": "session_loop",
                        "enabled_default": False,
                        "manual_start_required": True,
                        "auto_send_final_transcript": True,
                        "auto_endpoint": True,
                        "auto_rearm_after_tts": True,
                        "barge_in": True,
                        "commands_enabled": True,
                        "command_packs": [
                            "global_voice_v1",
                            "sentinel_ci_aya_v1",
                            "sentinel_ci_aya_security_v1",
                        ],
                    },
                    "voice_output": {
                        "latency_profile": "fast",
                        "voice": "nova",
                        "flush_first_chars": 18,
                        "flush_next_chars": 56,
                        "flush_timeout_ms": 450,
                        "interrupt_on_user_speech": True,
                    },
                    "response_style": {
                        "address_as": "Monsieur le Vice Premier Ministre",
                        "tone": "formel",
                        "format": "brief_gouvernemental_court",
                        "max_bullets": 4,
                    },
                    "allowed_actions": [
                        "cite_sources",
                        "draft_instruction",
                        "open_news_lab",
                        "read_calendar",
                        "create_calendar_event",
                        "update_calendar_event",
                        "cancel_calendar_event",
                        "create_action_plan",
                        "reschedule_action_plan",
                        "status_action_plan",
                        "cancel_action_plan",
                        "set_time_context",
                        "read_visual_observations",
                        "capture_visual_snapshot",
                        "control_strategic_map",
                        "read_social_signals",
                        "trace_rumor_origin",
                        "explain_geographic_priority",
                        "focus_evidence_graph",
                        "rank_decision_options",
                        "draft_response_email",
                        "read_maritime_snapshot",
                    ],
                    "allowed_calendar_actions": [
                        "read_calendar",
                        "create_calendar_event",
                        "update_calendar_event",
                        "cancel_calendar_event",
                    ],
                    "hidden_controls": [
                        "provider",
                        "model",
                        "system_picker",
                        "retrieval",
                        "reasoning",
                        "voice_runtime",
                    ],
                    "prompt_pack": [
                        {
                            "icon": "newspaper",
                            "label": "Synthèse du jour",
                            "prompt": "Quels signaux nécessitent une attention cabinet aujourd'hui ?",
                        },
                        {
                            "icon": "shield-check",
                            "label": "Sources et confiance",
                            "prompt": "Quelles sources soutiennent cette alerte ?",
                        },
                        {
                            "icon": "check-circle",
                            "label": "Décision requise",
                            "prompt": "Quels arbitrages sont attendus cette semaine ?",
                        },
                        {
                            "icon": "message-square",
                            "label": "Langage public",
                            "prompt": "Prépare des éléments de langage prudents et sourcés.",
                        },
                        {
                            "icon": "pulse",
                            "label": "Origine rumeur",
                            "prompt": "D'ou vient la rumeur prioritaire et quelle action recommandes-tu ?",
                        },
                        {
                            "icon": "layers",
                            "label": "Double lecture",
                            "prompt": "Separe politique interieure ivoirienne et perception internationale.",
                        },
                        {
                            "icon": "crosshair",
                            "label": "Carte region",
                            "prompt": "Montre la lecture CEDEAO autour de la Cote d'Ivoire.",
                        },
                    ],
                }
            ],
            "mission_room": {
                "enabled": True,
                "profile": SENTINEL_MISSION_ROOM_PROFILE,
                "country": "Cote d'Ivoire",
                "country_code": "CI",
                "region_scope": ["Cote d'Ivoire", "West Africa", "Sahel", "Gulf of Guinea"],
                "news_source_policy": "African public RSS first; synthetic demo fixtures only when feeds are unavailable.",
                "label": SENTINEL_ASSISTANT_NAME,
                "root_route": MISSION_ROOM_ROOT,
                "default_view": "cockpit",
                "navigation": NAVIGATION_ITEMS,
            },
        }
    )
    workspace.settings = settings

    # Workspace bootstrap must never grant IAM access implicitly. SENTINEL-CI is
    # seeded as a portable demo workspace, while memberships are managed through
    # the normal invite/admin flow so newly-created platform users cannot leak
    # into the workspace on a later seed run.
    members_added = 0

    for slug, name, description in (
        (
            "sentinel-ci-ministerial-briefs",
            "SENTINEL-CI Ministerial Briefs",
            "Briefings, agenda syntheses and validated talking points.",
        ),
        (
            "sentinel-ci-open-intelligence",
            "SENTINEL-CI Open Intelligence",
            "Public news and weak-signal summaries for ministerial watch.",
        ),
        (
            "sentinel-ci-projects",
            "SENTINEL-CI Strategic Projects",
            "Strategic project records and decision-support risk explanations.",
        ),
        (
            "sentinel-ci-territorial-map",
            "SENTINEL-CI Territorial Map",
            "Territorial zones, signals and non-military action recommendations.",
        ),
        (
            "sentinel-ci-territorial-intelligence",
            "SENTINEL-CI Territorial Intelligence",
            "Fused territorial scores from news, projects, agenda, visual observations and recommended action windows.",
        ),
        (
            "sentinel-ci-visual-intelligence",
            "SENTINEL-CI Visual Intelligence",
            "Visual snapshots and observations from authorized workspace streams.",
        ),
        (
            SENTINEL_MARITIME_INTELLIGENCE_COLLECTION,
            "SENTINEL-CI Maritime Intelligence",
            "Port, customs and Gulf of Guinea signals used by AYA for executive briefings.",
        ),
        (
            SENTINEL_EVIDENCE_GRAPH_COLLECTION,
            "SENTINEL-CI Evidence Graph",
            "Entities, rumors, sources, locations, projects and decisions connected for AYA.",
        ),
        (
            "sentinel-ci-security-briefs",
            "SENTINEL-CI Security Briefs",
            "Security posture briefs, Sahel OSINT notes, defense council syntheses and rumor dossiers used by AYA S3 actions.",
        ),
    ):
        _ensure_collection(db, workspace, slug, name, description)
    knowledge_guides_changed = _ensure_sentinel_knowledge_guides(db, workspace)

    for name, url, category in SENTINEL_NEWS_FEEDS:
        _ensure_feed(db, workspace, name, url, category)
    _ensure_target(db, workspace)
    _ensure_filter(db, workspace)
    _ensure_rag_preset(db, workspace)
    ensure_calendar_seed(db, workspace)
    ensure_action_plan_seed(db, workspace)
    cleaned_demo_artifacts = _cleanup_sentinel_demo_artifacts(db, workspace)

    system_specs = [
        {
            "name": "SENTINEL-CI Mission Room",
            "legacy_names": ["ARIA / SENTINEL-CI Mission Room"],
            "objective": "Consolider briefing, signaux faibles, projets, carte et actions ministerielles sous controle humain.",
            "capability_slug": "government_mission_room",
            "skill_slugs": [
                "ministerial_briefing_v1",
                "news_signal_synthesis_v1",
                "project_risk_explainer_v1",
                "territorial_signal_map_v1",
                "instruction_draft_v1",
                "scenario_generate_v1",
                "scenario_compare_v1",
                "scenario_recommend_v1",
                "map_layer_read_v1",
                "map_zone_score_v1",
                "map_signal_attach_v1",
                "map_recommendation_generate_v1",
                "visual_source_read_v1",
                "visual_snapshot_capture_v1",
                "visual_snapshot_analyze_v1",
                "visual_observation_sync_knowledge_v1",
                "calendar_read_v1",
                "calendar_create_event_v1",
                "calendar_update_event_v1",
                "calendar_cancel_event_v1",
                "calendar_daily_summary_v1",
                "action_plan_create_v1",
                "action_plan_reschedule_v1",
                "action_plan_status_v1",
                "action_plan_cancel_v1",
                "time_context_set_v1",
                "territorial_action_window_v1",
                "source_registry_refresh_v1",
                "osint_signal_prioritize_v1",
                "rumor_origin_trace_v1",
                "evidence_graph_build_v1",
                "situation_posture_score_v1",
                "maritime_snapshot_read_v1",
                "decision_option_rank_v1",
                "draft_response_email_v1",
                "voice_tandem_oracle_v1",
                "audit_log_v1",
            ],
            "variant": "government_mission_room",
        },
        {
            "name": "Briefing Quotidien Vice Premier Ministre",
            "objective": "Produire un briefing sourcé : priorites, risques, decisions attendues, actions et elements de langage.",
            "capability_slug": "ministerial_daily_briefing",
            "skill_slugs": [
                "ministerial_briefing_v1",
                "calendar_daily_summary_v1",
                "action_plan_status_v1",
                "llm_rag_answer_v1",
                "audit_log_v1",
            ],
            "variant": "ministerial_daily_briefing",
        },
        {
            "name": "Veille Presse & Signaux Faibles",
            "objective": "Agreger presse ivoirienne, CEDEAO, internationale et signaux publics de rumeurs pour detecter les sujets sensibles avant escalation.",
            "capability_slug": "open_intelligence_watch",
            "skill_slugs": [
                "intelligence_batch_v1",
                "news_signal_synthesis_v1",
                "source_registry_refresh_v1",
                "osint_signal_prioritize_v1",
                "rumor_origin_trace_v1",
                "audit_log_v1",
            ],
            "variant": "intelligence",
            "execution_mode": "continuous_monitoring",
        },
        {
            "name": "OSINT & Rumor Intelligence",
            "objective": "Qualifier les signaux OSINT, rumeurs publiques, origines, propagation et priorite geographique Cote d'Ivoire / CEDEAO / Afrique / Monde.",
            "capability_slug": "osint_rumor_intelligence",
            "skill_slugs": [
                "intelligence_batch_v1",
                "source_registry_refresh_v1",
                "osint_signal_prioritize_v1",
                "rumor_origin_trace_v1",
                "news_signal_synthesis_v1",
                "audit_log_v1",
            ],
            "variant": "osint_rumor_intelligence",
            "execution_mode": "continuous_monitoring",
        },
        {
            "name": "Evidence Graph",
            "objective": "Relier sources, entites, lieux, projets, rumeurs, agenda et actions pour les reponses sourcées d'AYA.",
            "capability_slug": "evidence_graph",
            "skill_slugs": [
                "evidence_graph_build_v1",
                "semantic_search_v1",
                "chain_mixed_hah_v1",
                "audit_log_v1",
            ],
            "variant": "evidence_graph",
        },
        {
            "name": "Maritime & Customs Watch",
            "objective": "Suivre Abidjan, San Pedro, douanes et routes Golfe de Guinee pour anticiper impacts economiques et projets.",
            "capability_slug": "maritime_customs_watch",
            "skill_slugs": [
                "maritime_snapshot_read_v1",
                "map_layer_read_v1",
                "osint_signal_prioritize_v1",
                "situation_posture_score_v1",
                "audit_log_v1",
            ],
            "variant": "maritime_customs_watch",
            "execution_mode": "continuous_monitoring",
        },
        {
            "name": "Scenario Fusion Monitor",
            "objective": "Fusionner webcams, presse, carte, agenda et actions pour maintenir le scenario Crise nationale et la posture strategique.",
            "capability_slug": "scenario_fusion_monitor",
            "skill_slugs": [
                "news_signal_synthesis_v1",
                "territorial_signal_map_v1",
                "map_layer_read_v1",
                "map_zone_score_v1",
                "visual_source_read_v1",
                "visual_snapshot_analyze_v1",
                "calendar_daily_summary_v1",
                "action_plan_status_v1",
                "scenario_generate_v1",
                "scenario_compare_v1",
                "scenario_recommend_v1",
                "situation_posture_score_v1",
                "decision_option_rank_v1",
                "chain_mixed_hah_v1",
                "voice_tandem_oracle_v1",
                "audit_log_v1",
            ],
            "variant": "scenario_fusion_monitor",
            "execution_mode": "continuous_monitoring",
        },
        {
            "name": "Strategic Forecasts",
            "objective": "Produire des previsions courtes et options comparees en cout, impact, confiance et fenetres de decision.",
            "capability_slug": "strategic_forecasts",
            "skill_slugs": [
                "situation_posture_score_v1",
                "scenario_generate_v1",
                "scenario_compare_v1",
                "scenario_recommend_v1",
                "decision_option_rank_v1",
                "audit_log_v1",
            ],
            "variant": "strategic_forecasts",
        },
        {
            "name": "Pilotage Projets Strategiques",
            "objective": "Expliquer les projets rouges, causes probables, risques et options d'arbitrage.",
            "capability_slug": "strategic_project_pilotage",
            "skill_slugs": [
                "project_risk_explainer_v1",
                "scenario_generate_v1",
                "scenario_compare_v1",
                "scenario_recommend_v1",
                "semantic_search_v1",
                "instruction_draft_v1",
                "action_plan_create_v1",
                "action_plan_status_v1",
                "audit_log_v1",
            ],
            "variant": "strategic_project_pilotage",
        },
        {
            "name": "Carte Strategique Executive",
            "objective": "Afficher les zones d'action preventive non militaire avec signaux, sources et recommandations.",
            "capability_slug": "territorial_action_map",
            "skill_slugs": [
                "territorial_signal_map_v1",
                "territorial_action_window_v1",
                "map_layer_read_v1",
                "map_zone_score_v1",
                "map_signal_attach_v1",
                "map_recommendation_generate_v1",
                "map_command_apply_v1",
                "situation_posture_score_v1",
                "maritime_snapshot_read_v1",
                "chain_mixed_hah_v1",
                "audit_log_v1",
            ],
            "variant": "territorial_action_map",
        },
        {
            "name": "Live Visual Monitor",
            "legacy_names": ["Situation Monitor Visuel"],
            "objective": "Lire des flux visuels habilites, produire des observations snapshot-only et les synchroniser dans la connaissance.",
            "capability_slug": "visual_situation_watch",
            "skill_slugs": [
                "visual_source_read_v1",
                "visual_snapshot_capture_v1",
                "visual_snapshot_analyze_v1",
                "visual_observation_sync_knowledge_v1",
                "territorial_signal_map_v1",
                "chain_mixed_hah_v1",
                "audit_log_v1",
            ],
            "variant": "visual_situation_watch",
            "execution_mode": "continuous_monitoring",
        },
        {
            "name": "Government Calendar Assist",
            "objective": "Lire l'agenda institutionnel, qualifier les conflits et proposer les fenetres d'arbitrage.",
            "capability_slug": "government_calendar_assist",
            "skill_slugs": [
                "calendar_read_v1",
                "calendar_daily_summary_v1",
                "calendar_create_event_v1",
                "calendar_update_event_v1",
                "calendar_cancel_event_v1",
                "action_plan_status_v1",
                "audit_log_v1",
            ],
            "variant": "government_calendar_assist",
        },
        {
            "name": "AYA Voice Command",
            "objective": "Piloter la Mission Control Room en voice-first : briefing, camera, carte regionale, rumeurs, agenda et instructions.",
            "capability_slug": "aya_voice_command",
            "skill_slugs": [
                "voice_tandem_oracle_v1",
                "voice_realtime_session_v1",
                "llm_rag_answer_v1",
                "audit_log_v1",
            ],
            "variant": "aya_voice_command",
        },
        {
            "name": "Decision Desk",
            "objective": "Classer les options, preparer brouillons email/actions et maintenir la validation humaine.",
            "capability_slug": "decision_desk",
            "skill_slugs": [
                "decision_option_rank_v1",
                "draft_response_email_v1",
                "instruction_draft_v1",
                "action_plan_create_v1",
                "action_plan_status_v1",
                "audit_log_v1",
            ],
            "variant": "decision_desk",
        },
        {
            "name": "Instructions Cabinet",
            "objective": "Rediger des brouillons d'instruction sources et soumis a validation humaine.",
            "capability_slug": "executive_instruction_drafting",
            "skill_slugs": [
                "instruction_draft_v1",
                "draft_response_email_v1",
                "decision_option_rank_v1",
                "claim_audit_v1",
                "audit_log_v1",
            ],
            "variant": "executive_instruction_drafting",
        },
    ]
    systems_created = 0
    for spec in system_specs:
        before = (
            db.query(System)
            .filter(System.workspace_id == workspace.id, System.name == spec["name"])
            .count()
        )
        _ensure_system(db, workspace, **spec)
        if before == 0:
            systems_created += 1
    map_system = (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.name == "Carte Strategique Executive")
        .first()
    )
    ensure_workspace_map_seed(db, workspace, system_id=map_system.id if map_system else None)
    visual_system = (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.name == "Live Visual Monitor")
        .first()
    )
    ensure_visual_intelligence_seed(
        db, workspace, system_id=visual_system.id if visual_system else None
    )

    db.commit()
    return {
        "workspace_slug": workspace.slug,
        "workspace_created": created,
        "members_added": members_added,
        "systems_created": systems_created,
        "demo_artifacts_cleaned": cleaned_demo_artifacts,
        "knowledge_guides_changed": knowledge_guides_changed,
    }


OCTOCITY_COLLECTIONS: tuple[tuple[str, str, str], ...] = (
    (
        "octocity-ministerial-briefs",
        "Octocity Mission Briefs",
        "Synthetic institutional briefings, agenda notes and validated language for OCTAVE.",
    ),
    (
        "octocity-open-intelligence",
        "Octocity Open Intelligence",
        "Demo-safe public signals, press syntheses and weak-signal monitoring for Octocity.",
    ),
    (
        "octocity-projects",
        "Octocity Strategic Projects",
        "Synthetic civic project records and decision-support risk explanations.",
    ),
    (
        "octocity-territorial-map",
        "Octocity Territorial Map",
        "Fictive regions, corridor signals and non-military action recommendations.",
    ),
    (
        "octocity-knowledge-capture",
        "Octocity Knowledge Capture Corpus",
        "Source inventory used by Knowledge Capture for synthetic expert interviews.",
    ),
    (
        "octocity-evidence-graph",
        "Octocity Evidence Graph",
        "Entities, sources, locations, decisions and risks connected for OCTAVE.",
    ),
)


def _octocity_collection_sources() -> dict[str, list[tuple[str, int]]]:
    return {
        "octocity-ministerial-briefs": [
            ("octocity-civic-brief-2026-05-25.md", 18),
            ("octocity-agenda-synthesis-2026-05-25.md", 12),
            ("octave-public-language-guide.md", 9),
        ],
        "octocity-open-intelligence": [
            ("aurora-public-signal-digest-2026-05-25.md", 16),
            ("meridian-social-pulse-snapshot.md", 11),
            ("northern-belt-rumor-trace-demo.md", 14),
        ],
        "octocity-projects": [
            ("liora-resilience-campus-project-note.md", 13),
            ("meridian-harbor-logistics-corridor.md", 15),
            ("solenne-infrastructure-risk-register.md", 10),
        ],
        "octocity-territorial-map": [
            ("asteria-territorial-map-legend.md", 10),
            ("auralis-zone-risk-reading.md", 12),
        ],
        "octocity-knowledge-capture": [
            ("octocity-expert-interview-seed.md", 8),
            ("octocity-decision-vocabulary.md", 6),
        ],
        "octocity-evidence-graph": [
            ("octocity-evidence-graph-nodes.json", 22),
            ("octocity-source-registry.json", 18),
        ],
    }


def _ensure_octocity_collection_sources(db: DBSession, workspace: Workspace) -> int:
    from app.services.knowledge_collections import upsert_collection_source

    written = 0
    for slug, source_specs in _octocity_collection_sources().items():
        collection = (
            db.query(KnowledgeCollection)
            .filter(
                KnowledgeCollection.workspace_id == workspace.id, KnowledgeCollection.slug == slug
            )
            .first()
        )
        if not collection:
            continue
        names: list[str] = []
        chunks = 0
        for filename, chunk_count in source_specs:
            names.append(filename)
            chunks += chunk_count
            upsert_collection_source(
                db,
                collection=collection,
                filename=filename,
                status="ready",
                origin="seed",
                chunk_count=chunk_count,
                source_metadata={
                    "demo": True,
                    "workspace_profile": OCTOCITY_MISSION_ROOM_PROFILE,
                    "source_profile": "synthetic_institutional_demo",
                },
                replace_source_metadata=True,
            )
            written += 1
        collection.status = "ready"
        collection.document_names = names
        collection.document_count = len(names)
        collection.chunk_count = chunks
    return written


def _octocity_guide_specs(workspace: Workspace) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for guide in SENTINEL_KNOWLEDGE_GUIDES:
        spec = present_payload_for_workspace(workspace, _clone(guide))
        if spec.get("target_type") == "scope" and spec.get("target_ref") == "vigie":
            spec["target_ref"] = "octocity_vigie"
        if isinstance(spec.get("guide_key"), str):
            spec["guide_key"] = spec["guide_key"].replace("vigie", "octocity-vigie")
        specs.append(spec)
    specs.append(
        {
            "guide_key": "octocity-knowledge-capture-v1",
            "target_type": "collection",
            "target_ref": "octocity-knowledge-capture",
            "title": "Guide OCTAVE - Knowledge Capture",
            "markdown": """# Guide OCTAVE - Knowledge Capture

OCTAVE conduit les entretiens de capture de connaissance dans un univers fictif. Les questions doivent rester concretes, institutionnelles et sourcees par les documents Octocity.

Regles :
- Reformuler chaque reponse en fait reutilisable, avec source ou incertitude explicite.
- Distinguer decision, signal, hypothese, action proposee et preuve.
- Ne jamais reintroduire de pays, ville, institution ou filiere reelle issue du workspace d'origine.
- Produire des propositions advisory only, relues par un humain avant publication.
""",
        }
    )
    return specs


def _ensure_octocity_knowledge_guides(db: DBSession, workspace: Workspace) -> int:
    changed = 0
    now = datetime.utcnow()
    for spec in _octocity_guide_specs(workspace):
        current = (
            db.query(KnowledgeGuide)
            .filter(
                KnowledgeGuide.workspace_id == workspace.id,
                KnowledgeGuide.guide_key == spec["guide_key"],
                KnowledgeGuide.is_current.is_(True),
            )
            .first()
        )
        if (
            current
            and current.target_type == spec["target_type"]
            and current.target_ref == spec["target_ref"]
            and current.title == spec["title"]
            and current.markdown == spec["markdown"]
            and current.status == "published"
        ):
            continue
        version = 1
        supersedes_id = None
        if current:
            current.is_current = False
            db.add(current)
            version = int(current.version or 1) + 1
            supersedes_id = current.id
        db.add(
            KnowledgeGuide(
                id=str(uuid4()),
                guide_key=spec["guide_key"],
                workspace_id=workspace.id,
                target_type=spec["target_type"],
                target_ref=spec["target_ref"],
                title=spec["title"],
                markdown=spec["markdown"],
                status="published",
                version=version,
                is_current=True,
                supersedes_id=supersedes_id,
                created_by_user_id=None,
                created_at=now,
                published_at=now,
            )
        )
        changed += 1
    return changed


def _ensure_octocity_filter(db: DBSession, workspace: Workspace) -> None:
    name = "Octocity demo safety"
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
                "Allow fictional institutional briefings, demo-safe public-signal summaries and advisory recommendations."
            ),
            severity="flag",
            active=True,
        )
    )


def _ensure_octocity_rag_preset(db: DBSession, workspace: Workspace) -> None:
    name = "Octocity C-HAH briefing preset"
    config = {
        "mode": "chah",
        "ragPipelineMode": "chah",
        "rag_pipeline_mode": "chah",
        "ragVectorDBType": "qdrant",
        "ragCollectionName": "octocity-open-intelligence",
        "topK": 6,
        "ragTopK": 6,
        "promptType": "executive_briefing",
        "asyncRetrieval": True,
        "sourcePolicy": "sources_required",
        "experience": {"demoSafeProviderLabels": True, "advisoryOnly": True},
    }
    existing_by_name = (
        db.query(RagPreset)
        .filter(RagPreset.workspace_id == workspace.id, RagPreset.name == name)
        .first()
    )
    existing_default = (
        db.query(RagPreset)
        .filter(
            RagPreset.workspace_id == workspace.id,
            RagPreset.scope == "workspace",
            RagPreset.scope_id == workspace.id,
            RagPreset.is_default.is_(True),
        )
        .first()
    )
    existing = existing_default or existing_by_name
    if existing:
        if existing_by_name and existing_by_name.id != existing.id:
            existing_by_name.is_default = False
        existing.name = name
        existing.config = config
        existing.scope = "workspace"
        existing.scope_id = workspace.id
        existing.workspace_id = workspace.id
        existing.is_default = True
        return
    db.add(
        RagPreset(
            workspace_id=workspace.id,
            name=name,
            scope="workspace",
            scope_id=workspace.id,
            config=config,
            is_default=True,
        )
    )


def _octocity_settings() -> dict[str, Any]:
    action_packs = ["global_voice_v1", "octave_mission_room_v1", "octave_security_v1"]
    return {
        "family": "generic",
        "demo_profile": "octocity_mission_room",
        # Octocity intentionally reuses only these four global government
        # Capabilities. Keep the exception slug-scoped so the workspace does
        # not inherit the complete Sentinel/government catalog.
        "catalog": {
            "enabled_capabilities": [
                "executive_instruction_drafting",
                "government_mission_room",
                "open_intelligence_watch",
                "territorial_action_map",
            ],
        },
        "default_route": MISSION_ROOM_ROUTE,
        "hide_provider_details": True,
        "workspace_app_shell": "immersive",
        "workspace_app_label": OCTOCITY_WORKSPACE_NAME,
        "workspace_app_default_view": "cockpit",
        "workspace_app_brand": {
            "label": OCTOCITY_WORKSPACE_NAME,
            "lines": ["AGENTIUM", "MISSION ROOM"],
            "emblem": "/assets/brand/agentium-mark.svg",
            "style": "agentium",
            "accent": "cyan",
        },
        "calendar": {
            "mode": "internal_shared",
            "connector_id": "institutional_calendar",
            "connector_label": "Agenda institutionnel",
            "write_policy": "direct",
            "timezone": "UTC",
        },
        "demo_time_context": demo_time_context_defaults(),
        "action_planner": {
            "write_policy": "direct",
            "default_owner": "Coordination",
            "advisory_only": True,
        },
        "actions": {
            "enabled_packs": action_packs,
            "confirmation_policy": "confirm_side_effects",
            "legacy_adapters": ["octave_action_plans"],
        },
        "voice_loop": {
            "default_mode": "session_loop",
            "enabled_default": False,
            "manual_start_required": True,
            "auto_send_final_transcript": True,
            "auto_endpoint": True,
            "auto_rearm_after_tts": True,
            "barge_in": True,
            "commands_enabled": True,
            "command_packs": action_packs,
            "trigger_word": OCTOCITY_ASSISTANT_NAME,
            "stop_phrases": ["stop", "pause", "on peut s'arreter la", "annule", "arrete"],
            "silence_ms": 1050,
            "min_speech_ms": 320,
            "max_turn_ms": 45000,
            "cooldown_ms": 450,
        },
        "voice_output": {
            "latency_profile": "fast",
            "voice": "nova",
            "flush_first_chars": 18,
            "flush_next_chars": 56,
            "flush_timeout_ms": 450,
            "interrupt_on_user_speech": True,
        },
        "document_intelligence": {
            "enabled": True,
            "default_profile": "octocity_institutional",
            "profiles": [
                {
                    "key": "octocity_institutional",
                    "label": "Octocity institutional documents",
                    "synonyms": {
                        "briefing": ["note coordination", "fiche", "brief", "elements de langage"],
                        "decision": ["arbitrage", "instruction", "validation", "deadline"],
                        "territory": ["zone", "region", "corridor", "port", "district"],
                    },
                    "max_candidate_facts": 1800,
                    "max_evidence_rows": 18,
                }
            ],
            "ocr": {
                "enabled": True,
                "provider_priority": ["tesseract_local", "ppocr_service"],
                "languages": ["fra", "eng"],
                "min_confidence": 0.45,
                "timeout_seconds": 20,
                "required": False,
                "openai_vision_enabled": False,
            },
            "citation_policy": "raw_source_first_page_section_paragraph",
        },
        "visual_intelligence": {
            "enabled": True,
            "capture_cadence_minutes": 60,
            "allowed_adapters": ["demo_static", "http_image", "browser_screenshot"],
            "storage_policy": "snapshot_only_no_continuous_recording",
            "analysis_policy": "no_identification_no_biometrics",
            "source_model": "live_webcam_embed_layer",
        },
        "feature_flag": {
            "security_live_osint": False,
        },
        "connectors": {
            "institutional_calendar": {
                "enabled": True,
                "status": "connected",
                "mode": "internal_shared",
                "label": "Agenda institutionnel",
            },
            "visual_streams": {
                "enabled": True,
                "status": "connected",
                "mode": "live_webcam_embed_layer",
                "label": "Flux visuels institutionnels",
            },
        },
        "assistant_profile_default": "octave_executive",
        "knowledge_scopes": [
            {
                "key": "octocity_vigie",
                "label": "Signals + Projects + Map",
                "description": "Synthetic institutional signals, civic projects and map data for the Octocity Mission Room.",
                "collection_slugs": [slug for slug, _, _ in OCTOCITY_COLLECTIONS],
                "default_mode": "chah",
                "top_k": 8,
                "is_default": True,
            },
            {
                "key": "octocity_capture",
                "label": "Knowledge Capture",
                "description": "Curated synthetic corpus for expert capture sessions.",
                "collection_slugs": ["octocity-knowledge-capture", "octocity-ministerial-briefs"],
                "default_mode": "chah",
                "top_k": 6,
                "is_default": False,
            },
        ],
        "assistant_profiles": [
            {
                "key": "octave_executive",
                "label": OCTOCITY_ASSISTANT_NAME,
                "subtitle": "Assistant strategique - donnees fictives",
                "default_knowledge_scope": "octocity_vigie",
                "executive_mode": True,
                "tone": "institutional",
                "grounding": {
                    "default_mode": "balanced",
                    "allowed_modes": ["strict", "balanced"],
                    "fallback_disclaimer": "Je n'ai pas de source workspace sur ce point ; analyse generale a valider :",
                    "strict_guard": "default",
                },
                "actions": {
                    "enabled_packs": action_packs,
                    "confirmation_policy": "confirm_side_effects",
                },
                "voice_loop": {
                    "default_mode": "session_loop",
                    "enabled_default": False,
                    "manual_start_required": True,
                    "auto_send_final_transcript": True,
                    "auto_endpoint": True,
                    "auto_rearm_after_tts": True,
                    "barge_in": True,
                    "commands_enabled": True,
                    "command_packs": action_packs,
                    "trigger_word": OCTOCITY_ASSISTANT_NAME,
                },
                "voice_output": {
                    "latency_profile": "fast",
                    "voice": "nova",
                    "flush_first_chars": 18,
                    "flush_next_chars": 56,
                    "flush_timeout_ms": 450,
                    "interrupt_on_user_speech": True,
                },
                "response_style": {
                    "address_as": "Madame la Directrice de Coordination",
                    "tone": "formel",
                    "format": "brief_institutionnel_court",
                    "max_bullets": 4,
                },
                "hidden_controls": [
                    "provider",
                    "model",
                    "system_picker",
                    "retrieval",
                    "reasoning",
                    "voice_runtime",
                ],
                "prompt_pack": [
                    {
                        "icon": "newspaper",
                        "label": "Synthese du jour",
                        "prompt": "Quels signaux necessitent une attention coordination aujourd'hui ?",
                    },
                    {
                        "icon": "shield-check",
                        "label": "Sources et confiance",
                        "prompt": "Quelles sources soutiennent cette alerte ?",
                    },
                    {
                        "icon": "check-circle",
                        "label": "Decision requise",
                        "prompt": "Quels arbitrages sont attendus cette semaine ?",
                    },
                    {
                        "icon": "message-square",
                        "label": "Langage public",
                        "prompt": "Prepare des elements de langage prudents et sources.",
                    },
                ],
            }
        ],
        "mission_room": {
            "enabled": True,
            "profile": OCTOCITY_MISSION_ROOM_PROFILE,
            "country": "Asteria",
            "country_code": "AS",
            "region_scope": ["Asteria", "Atlantic Arc", "Northern Belt", "Gulf of Meridian"],
            "news_source_policy": "Synthetic public fixtures first; external feeds disabled for this anonymized demo.",
            "label": OCTOCITY_ASSISTANT_NAME,
            "assistant_label": OCTOCITY_ASSISTANT_NAME,
            "brand": {
                "label": OCTOCITY_WORKSPACE_NAME,
                "lines": ["AGENTIUM", "MISSION ROOM"],
                "emblem": "/assets/brand/agentium-mark.svg",
                "style": "agentium",
            },
            "root_route": MISSION_ROOM_ROOT,
            "default_view": "cockpit",
            "navigation": [dict(item) for item in OCTOCITY_NAVIGATION_ITEMS],
        },
    }


def ensure_octocity_mission_room_workspace(db: DBSession) -> dict[str, int | str]:
    """Create/update the anonymized Agentium Mission Room video workspace."""
    workspace = db.query(Workspace).filter(Workspace.slug == OCTOCITY_WORKSPACE_SLUG).first()
    created = 0
    if not workspace:
        workspace = Workspace(
            id=str(uuid4()),
            name=OCTOCITY_WORKSPACE_NAME,
            slug=OCTOCITY_WORKSPACE_SLUG,
            mode="demo",
            settings={},
        )
        db.add(workspace)
        db.flush()
        created = 1
    else:
        workspace = lock_workspace_for_app_entitlement_mutation(db, workspace.id)

    workspace.name = OCTOCITY_WORKSPACE_NAME
    workspace.mode = "demo"
    settings = dict(workspace.settings or {})
    settings.update(_octocity_settings())
    workspace.settings = settings
    owner_emails = _octocity_owner_emails()
    if owner_emails:
        members_added = _ensure_workspace_members(
            db,
            workspace,
            owner_emails,
            role="owner",
            role_template="workspace_owner",
            custom_label="octocity:video-owner",
            grant_source="octocity_seed_owner",
        )
    else:
        members_added = 0
        logger.warning(
            "Octocity owner auto-provisioning skipped: "
            "OCTOCITY_OWNER_EMAILS is empty; existing memberships are preserved"
        )

    for slug, name, description in OCTOCITY_COLLECTIONS:
        _ensure_collection(db, workspace, slug, name, description)
    sources_seeded = _ensure_octocity_collection_sources(db, workspace)
    knowledge_guides_changed = _ensure_octocity_knowledge_guides(db, workspace)
    _ensure_octocity_filter(db, workspace)
    _ensure_octocity_rag_preset(db, workspace)
    ensure_calendar_seed(db, workspace)
    ensure_action_plan_seed(db, workspace)

    system_specs = [
        {
            "name": "OCTAVE Mission Room",
            "objective": "Consolider signaux, projets, carte, decisions et actions institutionnelles fictives sous controle humain.",
            "capability_slug": "government_mission_room",
            "skill_slugs": [
                "ministerial_briefing_v1",
                "news_signal_synthesis_v1",
                "project_risk_explainer_v1",
                "territorial_signal_map_v1",
                "instruction_draft_v1",
                "calendar_daily_summary_v1",
                "action_plan_status_v1",
                "maritime_snapshot_read_v1",
                "voice_tandem_oracle_v1",
                "audit_log_v1",
            ],
            "variant": "octocity_mission_room",
        },
        {
            "name": "OCTAVE Territorial Map",
            "objective": "Relier les zones, signaux et projets fictifs pour la coordination territoriale Octocity.",
            "capability_slug": "territorial_action_map",
            "skill_slugs": [
                "territorial_signal_map_v1",
                "territorial_action_window_v1",
                "map_layer_read_v1",
                "map_zone_score_v1",
                "map_command_apply_v1",
                "audit_log_v1",
            ],
            "variant": "octocity_territorial_map",
        },
        {
            "name": "OCTAVE Open Intelligence",
            "objective": "Qualifier les signaux publics synthetiques et leur niveau de confiance pour Octocity.",
            "capability_slug": "open_intelligence_watch",
            "skill_slugs": [
                "intelligence_batch_v1",
                "news_signal_synthesis_v1",
                "source_registry_refresh_v1",
                "osint_signal_prioritize_v1",
                "audit_log_v1",
            ],
            "variant": "octocity_intelligence",
            "execution_mode": "continuous_monitoring",
        },
        {
            "name": "OCTAVE Decision Desk",
            "objective": "Preparer des arbitrages fictifs sources et soumis a validation humaine dans Octocity.",
            "capability_slug": "executive_instruction_drafting",
            "skill_slugs": [
                "instruction_draft_v1",
                "draft_response_email_v1",
                "decision_option_rank_v1",
                "claim_audit_v1",
                "audit_log_v1",
            ],
            "variant": "octocity_decision_desk",
        },
    ]
    systems_created = 0
    for spec in system_specs:
        before = (
            db.query(System)
            .filter(System.workspace_id == workspace.id, System.name == spec["name"])
            .count()
        )
        system = _ensure_system(
            db,
            workspace,
            **spec,
            template_prefix="octocity",
            created_by="system:octocity_seed",
        )
        if before == 0 and system:
            systems_created += 1

    # Test and bootstrap sessions disable autoflush.  Flush the newly-created
    # systems before resolving the map owner so an upgrade can rebind an
    # existing WorkspaceMap to OCTAVE Territorial Map in the same seed run.
    db.flush()
    map_system = (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.name == "OCTAVE Territorial Map")
        .first()
    )
    ensure_workspace_map_seed(db, workspace, system_id=map_system.id if map_system else None)

    from app.services.systems.bootstrap import (
        ensure_expert_capture_system_default,
        ensure_workspace_chat_system_default,
    )

    chat_before = (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.name == "Workspace Chat")
        .count()
    )
    chat_system = ensure_workspace_chat_system_default(db, workspace.id)
    if chat_system:
        chat_system.name = "Workspace Chat"
        chat_system.objective = "Provide OCTAVE workspace chat over the synthetic Octocity corpus and Mission Room actions."
        systems_created += 1 if chat_before == 0 else 0

    capture_before = (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.name == "Knowledge Capture")
        .count()
    )
    capture_system = ensure_expert_capture_system_default(db, workspace.id)
    if capture_system:
        capture_system.name = "Knowledge Capture"
        capture_system.objective = (
            "Run guided expert interviews connected to the Octocity synthetic corpus."
        )
        systems_created += 1 if capture_before == 0 else 0

    db.commit()
    return {
        "workspace_slug": workspace.slug,
        "workspace_created": created,
        "members_added": members_added,
        "systems_created": systems_created,
        "knowledge_guides_changed": knowledge_guides_changed,
        "collection_sources_seeded": sources_seeded,
    }
