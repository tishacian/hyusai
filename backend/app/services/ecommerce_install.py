"""Explicit, tenant-scoped demo installation using canonical publication services.

Never runs on startup, never changes another System or an existing Experience.
The operator supplies source receipts derived from Document Center inventory.
"""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

from app.core.iam.roles import WORKSPACE_ADMIN, WORKSPACE_OWNER, normalize_role_template
from app.models.experience import Experience
from app.models.skill import Skill
from app.models.system import System
from app.models.workspace import WorkspaceMember
from app.services import ecommerce_claims as claims
from app.services.connectors.generic import postgresql_claims as pg
from app.services.ecommerce_flow_sources import with_data_sources
from app.services.experience import bindings, lifecycle
from app.services.skills_registry.seed import SEED_SKILLS
from app.services.systems import flow_publication

RESOURCES = Path(__file__).resolve().parents[1] / "resources"
BLUEPRINT = "showcase-ecommerce-claims-v1"


def install(db, workspace, actor, *, policy_sha256, source_collections, benchmark, activate=False):
    member = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.user_id == actor.id)
        .one_or_none()
    )
    if not member or normalize_role_template(member.role_template, member.role) not in {
        WORKSPACE_OWNER,
        WORKSPACE_ADMIN,
    }:
        raise ValueError("CLAIMS_INSTALL_ADMIN_REQUIRED")
    existing = (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.blueprint_key == BLUEPRINT)
        .one_or_none()
    )
    app = (
        db.query(Experience)
        .filter(Experience.workspace_id == workspace.id, Experience.slug == "reclamations")
        .one_or_none()
    )
    if existing or app:
        raise ValueError("CLAIMS_INSTALL_ALREADY_EXISTS_REVIEW_REQUIRED")
    # Business data and real original-source mapping must precede publication.
    stage_ids = ["RC-1042", "RC-1043", "RC-1044"]
    cohort = [p[c + "_claim_id"] for p in benchmark["pairs"] for c in ("manual", "assisted")]
    config = {
        "allowed_claim_ids": stage_ids + cohort,
        "stage_claim_ids": stage_ids,
        "allowed_collection_slugs": source_collections,
        "policy_sha256": policy_sha256,
        "benchmark": copy.deepcopy(benchmark),
    }
    settings = copy.deepcopy(workspace.settings or {})
    settings.setdefault("features", {}).update(
        {"ecommerce_claims_v1": True, "experience_v1": True, "flow_publication_v1": True}
    )
    settings["ecommerce_claims"] = config
    workspace.settings = settings
    config["benchmark"]["snapshot_sha256"] = {}
    for claim_id in config["allowed_claim_ids"]:
        snap = pg.snapshot(workspace, claim_id)
        if claim_id in cohort:
            config["benchmark"]["snapshot_sha256"][claim_id] = snap["provenance"]["snapshot_sha256"]
        sources = claims._sources(
            db,
            workspace,
            SimpleNamespace(initiated_by_user_id=actor.id),
            snap,
            ("policy", "delivery", "refund"),
        )
        if any(
            r["knowledge_source_id"] not in {s.id for _, s, _ in sources}
            for r in snap["data"]["documents"]
        ):
            raise ValueError("CLAIMS_INSTALL_SOURCE_MAPPING_INCOMPLETE")
    workspace.settings = copy.deepcopy(settings)
    slugs = list(claims.SKILLS.values()) + ["decide_next_v1"]
    # Only add absent built-ins needed by this app; never reseed unrelated catalog rows.
    for definition in SEED_SKILLS:
        if (
            definition["slug"] in slugs
            and not db.query(Skill).filter(Skill.slug == definition["slug"]).first()
        ):
            db.add(Skill(**definition, is_seeded="Y", workspace_id=None))
    db.flush()
    skills = db.query(Skill).filter(Skill.slug.in_(slugs)).all()
    if len(skills) != len(slugs):
        raise ValueError("CLAIMS_INSTALL_SKILLS_MISSING")
    flow = with_data_sources(
        json.loads((RESOURCES / "flows/showcase_ecommerce_claims_v1.json").read_text()),
        source_collections,
    )
    system = System(
        workspace_id=workspace.id,
        blueprint_key=BLUEPRINT,
        name="Luma Maison — Réclamations",
        objective="Résoudre les réclamations avec des preuves documentaires et PostgreSQL, sous validation humaine.",
        execution_mode="human_augmented",
        status="draft",
        created_by=actor.email,
        skill_ids=[s.id for s in skills],
        flow_definition={"nodes": [], "edges": []},
        settings={"evidence_kind": "synthetic_demo", "production_baseline_eligible": False},
    )
    db.add(system)
    db.flush()
    flow_publication.initialize_new_system_publication_if_enabled(
        db, system=system, workspace=workspace, actor=actor.email
    )
    draft, _ = flow_publication.save_draft(
        db,
        system_id=system.id,
        workspace=workspace,
        flow_definition=flow,
        expected_revision=1,
        actor=actor.email,
    )
    version, _, _ = flow_publication.publish_draft(
        db,
        system_id=system.id,
        workspace=workspace,
        expected_draft_revision=draft.revision,
        expected_published_version_id=system.published_flow_version_id,
        message="Luma Maison v1: real reads, scoped evidence, native AgentLoop and human-approved simulated actions.",
        breaking_change_intent=None,
        actor=actor.email,
    )
    system.status = "active"
    db.flush()
    bindings.create_binding(
        db,
        workspace=workspace,
        actor=actor.email,
        binding_key="showcase.claims.investigate",
        system_id=system.id,
        published_flow_version_id=version.id,
        ingress_id="source.request",
        confirmation_policy="confirm",
        on_unavailable="unavailable",
    )
    experience, draft = lifecycle.create_experience(
        db,
        workspace=workspace,
        actor=actor.email,
        name="Réclamations",
        slug="reclamations",
        pattern="form_result",
        languages=["fr", "en"],
        theme={"live_href": "/work/reclamations/studio"},
        access_policy={"roles": []},
        emblem="◈",
        description="Luma Maison : commandes, justificatifs, enquête et décision SAV. Démonstration synthétique.",
    )
    pages = json.loads((RESOURCES / "experiences/showcase_ecommerce_claims_v1.json").read_text())
    draft = lifecycle.save_draft(
        db,
        workspace_id=workspace.id,
        experience_id=experience.id,
        pages=pages,
        binding_keys=["showcase.claims.investigate"],
        expected_revision=draft.revision,
        actor=actor.email,
    )
    check = lifecycle.ready_check(db, workspace=workspace, experience_id=experience.id)
    if check["blockers"]:
        raise ValueError("CLAIMS_INSTALL_NOT_READY: " + json.dumps(check["blockers"]))
    release = lifecycle.create_release(
        db,
        workspace=workspace,
        experience_id=experience.id,
        notes="Luma Maison v1",
        expected_draft_revision=draft.revision,
        expected_content_sha256=draft.content_sha256,
        expected_experience_updated_at=experience.updated_at,
        expected_bindings_sha256=check["bindings_sha256"],
        actor=actor.email,
    )
    deployment = lifecycle.deploy(
        db,
        workspace=workspace,
        experience_id=experience.id,
        channel="live" if activate else "pilot",
        release_id=release.id,
        expected_current_release_id=None,
        expected_deployment_updated_at=None,
        audience={"roles": []} if activate else {"roles": [WORKSPACE_OWNER, WORKSPACE_ADMIN]},
        actor=actor.email,
    )
    return {
        "workspace_id": workspace.id,
        "system_id": system.id,
        "published_flow_version_id": version.id,
        "experience_id": experience.id,
        "release_id": release.id,
        "deployment_id": deployment.id,
        "channel": deployment.channel,
    }
