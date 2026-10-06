"""Explicit CAS upgrade of one Luma Flow and its deployed Work binding."""

from __future__ import annotations

from app.core.iam.roles import WORKSPACE_ADMIN, WORKSPACE_OWNER, normalize_role_template
from app.models.experience import Experience, ExperienceRelease
from app.models.system import System
from app.models.workspace import WorkspaceMember
from app.services.connectors.generic import postgresql_claims as pg
from app.services.ecommerce_flow_sources import reviewed_source_base, with_data_sources
from app.services.ecommerce_install import BLUEPRINT
from app.services.experience import bindings, lifecycle
from app.services.run_engine.execution_contract import canonical_flow_sha256
from app.services.systems import flow_publication


def upgrade(
    db,
    workspace,
    actor,
    *,
    system_id,
    expected_flow_sha256,
    expected_release_id,
    channel="live",
    apply=False,
    expected_target_sha256=None,
    flow_transform=None,
    message="Luma: explicit live PostgreSQL and document source dependencies.",
):
    member = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.user_id == actor.id)
        .one_or_none()
    )
    if not member or normalize_role_template(member.role_template, member.role) not in {
        WORKSPACE_OWNER,
        WORKSPACE_ADMIN,
    }:
        raise ValueError("CLAIMS_SOURCE_UPGRADE_ADMIN_REQUIRED")
    system = (
        db.query(System)
        .filter(
            System.id == system_id,
            System.workspace_id == workspace.id,
            System.blueprint_key == BLUEPRINT,
        )
        .one_or_none()
    )
    if system is None:
        raise ValueError("CLAIMS_SOURCE_UPGRADE_SYSTEM_MISMATCH")
    state = flow_publication.flow_state(db, system=system, workspace=workspace)
    if state["published"]["flow_sha256"] != expected_flow_sha256:
        raise ValueError("CLAIMS_SOURCE_UPGRADE_FLOW_CHANGED")
    base = reviewed_source_base(
        state["published"]["flow_definition"], state["draft"]["flow_definition"]
    )
    experience = (
        db.query(Experience)
        .filter(Experience.workspace_id == workspace.id, Experience.slug == "reclamations")
        .one()
    )
    experience, app_draft, deployments = lifecycle.get_experience(
        db, workspace_id=workspace.id, experience_id=experience.id
    )
    deployment = next((row for row in deployments if row.channel == channel), None)
    if deployment is None or deployment.release_id != expected_release_id:
        raise ValueError("CLAIMS_SOURCE_UPGRADE_RELEASE_CHANGED")
    previous_release = db.get(ExperienceRelease, deployment.release_id)
    if app_draft.content_sha256 != previous_release.content_sha256:
        raise ValueError("CLAIMS_SOURCE_UPGRADE_UNPUBLISHED_APP_DRAFT")
    binding = bindings.get_binding(
        db, workspace_id=workspace.id, binding_key="showcase.claims.investigate"
    )
    if (
        binding.system_id != system.id
        or binding.published_flow_version_id != state["published"]["version_id"]
    ):
        raise ValueError("CLAIMS_SOURCE_UPGRADE_BINDING_CHANGED")
    config = (workspace.settings or {}).get("ecommerce_claims") or {}
    collections = config.get("allowed_collection_slugs") or []
    if not collections:
        raise ValueError("CLAIMS_SOURCE_UPGRADE_COLLECTIONS_MISSING")
    flow = with_data_sources(base, collections)
    if flow_transform is not None:
        flow = flow_transform(flow)
    target_hash = canonical_flow_sha256(flow)
    result = {
        "workspace_id": workspace.id,
        "system_id": system.id,
        "previous_flow_version_id": state["published"]["version_id"],
        "previous_release_id": deployment.release_id,
        "channel": channel,
        "flow_sha256": target_hash,
        "flow_definition": flow,
        "nodes": len(flow["nodes"]),
        "edges": len(flow["edges"]),
        "preserved_draft_revision": state["draft"]["revision"],
        "collections": collections,
        "postgresql_tables": pg.CLAIM_RESOURCES,
        "changed": target_hash != expected_flow_sha256,
        "applied": False,
    }
    if not apply or not result["changed"]:
        return result
    if expected_target_sha256 != target_hash:
        raise ValueError("CLAIMS_SOURCE_UPGRADE_TARGET_NOT_REVIEWED")
    # Read-only verification, no change to connector credentials or business data.
    for claim_id in config["stage_claim_ids"]:
        pg.snapshot(workspace, claim_id)
    draft, _ = flow_publication.save_draft(
        db,
        system_id=system.id,
        workspace=workspace,
        flow_definition=flow,
        expected_revision=state["draft"]["revision"],
        actor=actor.email,
    )
    version, _, _ = flow_publication.publish_draft(
        db,
        system_id=system.id,
        workspace=workspace,
        expected_draft_revision=draft.revision,
        expected_published_version_id=state["published"]["version_id"],
        message=message,
        breaking_change_intent="acknowledged",
        actor=actor.email,
    )
    bindings.update_binding(
        db,
        workspace=workspace,
        binding_key=binding.binding_key,
        published_flow_version_id=version.id,
        actor=actor.email,
    )
    check = lifecycle.ready_check(db, workspace=workspace, experience_id=experience.id)
    if check["blockers"]:
        raise ValueError("CLAIMS_SOURCE_UPGRADE_APP_NOT_READY")
    release = lifecycle.create_release(
        db,
        workspace=workspace,
        experience_id=experience.id,
        notes=message,
        expected_draft_revision=app_draft.revision,
        expected_content_sha256=app_draft.content_sha256,
        expected_experience_updated_at=experience.updated_at,
        expected_bindings_sha256=check["bindings_sha256"],
        actor=actor.email,
    )
    lifecycle.deploy(
        db,
        workspace=workspace,
        experience_id=experience.id,
        channel=channel,
        release_id=release.id,
        expected_current_release_id=expected_release_id,
        expected_deployment_updated_at=deployment.updated_at,
        audience=deployment.audience,
        actor=actor.email,
    )
    return {
        **result,
        "applied": True,
        "published_flow_version_id": version.id,
        "release_id": release.id,
    }
