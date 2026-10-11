from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace

import pytest

from app.models.capability import Capability
from app.models.context import Context
from app.models.evaluation_preset import EvaluationPreset
from app.models.knowledge_collection import KnowledgeCollection
from app.models.rag_preset import RagPreset
from app.models.skill import Skill
from app.models.system import System
from app.models.system_flow_draft import SystemFlowDraft
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.workspace import (
    Workspace,
    WorkspaceMember,
    WorkspaceMemberAppEntitlement,
)
from app.models.workspace_app import WorkspaceAppInstallation, WorkspaceAppOperation
from app.services import workspace_blueprints
from app.services.iam.app_entitlements import (
    APP_ENTITLEMENTS_FEATURE,
    BUSINESS_APP_KEYS,
    WORKSPACE_EXPERIENCE_FEATURE,
)
from app.services.iam.config_service import load_iam_config, patch_iam_config
from app.services.workspace_app_lifecycle import (
    apply_workspace_app_lifecycle,
    plan_workspace_app_lifecycle,
)
from app.services.workspace_app_manifests import BUILTIN_WORKSPACE_APP_MANIFESTS


def _workspace(
    db_session,
    *,
    id_: str,
    slug: str,
    mode: str = "executive",
    settings: dict | None = None,
) -> Workspace:
    workspace = Workspace(
        id=id_,
        name=slug.title(),
        slug=slug,
        mode=mode,
        settings=settings or {},
    )
    db_session.add(workspace)
    db_session.flush()
    return workspace


def _user(db_session) -> User:
    user = User(id="user-1", username="builder", email="builder@example.test")
    db_session.add(user)
    db_session.flush()
    return user


def _reference_workspace(db_session) -> tuple[Workspace, User]:
    workspace = _workspace(
        db_session,
        id_="ws-source",
        slug="andritz",
        settings={"family": "andritz"},
    )
    user = _user(db_session)
    skill = Skill(
        id="skill-rag",
        slug="llm_rag_answer_v1",
        name="RAG answer",
        workspace_id=None,
    )
    capability = Capability(
        id="cap-capture",
        workspace_id=workspace.id,
        slug="expert_knowledge_capture",
        name="Expert Knowledge Capture",
        description="Capture tacit expert knowledge.",
        skill_ids=[skill.id],
        pricing={"unit": "session", "unit_price": 0},
    )
    context = Context(
        id="ctx-andritz",
        workspace_id=workspace.id,
        name="Andritz MVP Knowledge Context",
        data_refs=["collection:andritz-secure-deposit"],
        environment_state={"site": "pilot"},
        ephemeral=False,
    )
    system = System(
        id="sys-capture",
        workspace_id=workspace.id,
        name="Expert Knowledge Capture",
        objective="Capture troubleshooting decisions from senior experts.",
        capability_id=capability.id,
        context_id=context.id,
        skill_ids=[skill.id],
        flow_definition={
            "nodes": [
                {
                    "id": "n1",
                    "kind": "task",
                    "config": {"skill_id": skill.id, "skill_slug": skill.slug},
                }
            ],
            "edges": [],
        },
        execution_mode="human_augmented",
        execution_profile={"voice_sla_ms": 1500},
        status="active",
    )
    collection = KnowledgeCollection(
        id="col-secure",
        workspace_id=workspace.id,
        slug="andritz-secure-deposit",
        name="Andritz Secure Deposit",
        description="Staged supplier files.",
        status="ready",
        document_names=["manual.pdf"],
        vector_collection_name="andritz_andritz-secure-deposit",
        artifact_prefix="workspaces/ws-source/collections/col-secure",
        document_count=1,
        chunk_count=12,
    )
    preset = RagPreset(
        id="preset-rag",
        workspace_id=workspace.id,
        name="Andritz default RAG",
        scope="workspace",
        config={"mode": "hybrid", "topK": 5},
        is_default=True,
    )
    db_session.add_all([skill, capability, context, system, collection, preset])
    db_session.flush()
    return workspace, user


def _validate_then_apply(
    db_session,
    *,
    target: Workspace,
    blueprint: dict,
    actor: User,
    experience_policy: str = "preserve_target",
    entitlement_policy: str = "preserve_target",
    activate_systems: bool = False,
) -> tuple[dict, dict]:
    dry_run = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=actor,
        dry_run=True,
        activate_systems=activate_systems,
        experience_policy=experience_policy,
        entitlement_policy=entitlement_policy,
    )
    applied = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=actor,
        dry_run=False,
        activate_systems=activate_systems,
        experience_policy=experience_policy,
        entitlement_policy=entitlement_policy,
        expected_plan_token=dry_run["plan_token"],
    )
    return dry_run, applied


def _add_member(
    db_session,
    *,
    workspace: Workspace,
    user_id: str,
    username: str,
) -> WorkspaceMember:
    user = User(id=user_id, username=username, email=f"{username}@example.test")
    membership = WorkspaceMember(
        user_id=user.id,
        workspace_id=workspace.id,
        role="member",
        role_template="business_user",
    )
    db_session.add_all([user, membership])
    db_session.flush()
    return membership


def _install_builtin_app(
    db_session,
    *,
    workspace: Workspace,
    app_id: str,
    version: str,
) -> WorkspaceAppInstallation:
    manifest = BUILTIN_WORKSPACE_APP_MANIFESTS[(app_id, version)]
    plan = plan_workspace_app_lifecycle(
        db_session,
        workspace_id=workspace.id,
        operation="install",
        app_id=app_id,
        target_version=version,
        expected_manifest_digest=manifest.digest,
    )
    result = apply_workspace_app_lifecycle(
        db_session,
        workspace_id=workspace.id,
        operation="install",
        app_id=app_id,
        target_version=version,
        expected_manifest_digest=manifest.digest,
        expected_plan_sha256=plan.plan_sha256,
        actor="blueprint-test",
        idempotency_key=f"blueprint-test-{workspace.id}-{app_id}-{version}",
        commit=False,
    )
    return result.installation


def test_export_workspace_blueprint_excludes_sensitive_data(db_session):
    workspace, user = _reference_workspace(db_session)

    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=workspace,
        exported_by=user,
    )

    assert blueprint["kind"] == workspace_blueprints.BLUEPRINT_KIND
    assert blueprint["workspace"]["slug"] == "andritz"
    assert blueprint["systems"][0]["name"] == "Expert Knowledge Capture"
    assert blueprint["systems"][0]["capability_slug"] == "expert_knowledge_capture"
    assert blueprint["capabilities"][0]["skill_slugs"] == ["llm_rag_answer_v1"]
    assert blueprint["knowledge"]["collections"][0]["slug"] == "andritz-secure-deposit"
    assert blueprint["knowledge"]["exports_raw_documents"] is False
    assert blueprint["connectors"]["secure_deposit"]["exports_passwords"] is False
    assert blueprint["data_policy"]["workspace_members"] == "excluded"


def test_dry_run_reports_actions_without_writing(db_session):
    source, user = _reference_workspace(db_session)
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    target = _workspace(db_session, id_="ws-target", slug="target")

    report = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=user,
        dry_run=True,
    )

    assert report["dry_run"] is True
    assert report["created"]["systems"] == 1
    assert db_session.query(System).filter(System.workspace_id == target.id).count() == 0


def test_apply_workspace_blueprint_creates_draft_system_and_metadata(db_session):
    source, user = _reference_workspace(db_session)
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    target = _workspace(db_session, id_="ws-target", slug="target")

    _dry_run, report = _validate_then_apply(
        db_session,
        target=target,
        blueprint=blueprint,
        actor=user,
    )
    db_session.flush()

    imported = (
        db_session.query(System)
        .filter(System.workspace_id == target.id, System.name == "Expert Knowledge Capture")
        .one()
    )
    collection = (
        db_session.query(KnowledgeCollection)
        .filter(
            KnowledgeCollection.workspace_id == target.id,
            KnowledgeCollection.slug == "andritz-secure-deposit",
        )
        .one()
    )

    assert report["created"]["systems"] == 1
    assert report["created"]["capabilities"] == 1
    assert imported.status == "draft"
    assert imported.execution_mode == "human_augmented"
    assert imported.capability_id is not None
    assert collection.document_count == 0
    assert collection.status == "created"


def test_feature_on_blueprint_system_initializes_published_flow_authority(db_session):
    source, user = _reference_workspace(db_session)
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    target = _workspace(
        db_session,
        id_="ws-publication-target",
        slug="publication-target",
        settings={"features": {"flow_publication_v1": True}},
    )

    _validate_then_apply(
        db_session,
        target=target,
        blueprint=blueprint,
        actor=user,
    )
    imported = (
        db_session.query(System)
        .filter_by(workspace_id=target.id, name="Expert Knowledge Capture")
        .one()
    )
    draft = db_session.query(SystemFlowDraft).filter_by(system_id=imported.id).one()
    published = (
        db_session.query(SystemVersion)
        .filter_by(system_id=imported.id, id=imported.published_flow_version_id)
        .one()
    )

    assert draft.base_published_version_id == published.id
    assert draft.flow_sha256 == published.flow_sha256
    assert published.execution_contract is not None
    assert db_session.query(SystemVersion).filter_by(system_id=imported.id).count() == 1


def test_export_uses_positive_allowlists_and_removes_credential_shaped_config(db_session):
    workspace, user = _reference_workspace(db_session)
    workspace.settings = {
        "family": "andritz",
        "features": {WORKSPACE_EXPERIENCE_FEATURE: True},
        "smtp_password": "root-secret-value",
        "connectors": {"erp": {"api_key": "settings-secret-value"}},
    }
    capability = db_session.query(Capability).filter_by(id="cap-capture").one()
    capability.pricing = {
        "unit": "session",
        "vendor_secret": "pricing-secret-value",
        "token": "bare-token-value",
        "warehouse_dsn": "postgresql://warehouse:dsn-value@example.test/data",
        "endpoint": "https://embedded-user:embedded-value@example.test/api",
        "header": "Bearer bearer-value",
        "env": [
            {"name": "OPENAI_API_KEY", "value": "indirected-secret-value"},
            {"name": "REGION", "value": "eu-west-1"},
        ],
        "secretariat_label": "Executive office",
        "authorization_endpoint": "https://login.example.test/oauth/authorize",
        "passwordless_enabled": True,
        "public": {"currency": "EUR"},
    }
    context = db_session.query(Context).filter_by(id="ctx-andritz").one()
    context.environment_state = {
        "site": "pilot",
        "credentials": {"username": "operator", "password": "context-secret-value"},
    }
    system = db_session.query(System).filter_by(id="sys-capture").one()
    system.flow_definition = {
        "nodes": [
            {
                "id": "n1",
                "kind": "task",
                "config": {
                    "skill_id": "skill-rag",
                    "skill_slug": "llm_rag_answer_v1",
                    "api_key": "flow-secret-value",
                },
            }
        ],
        "edges": [],
    }
    system.execution_profile = {
        "latency_target_ms": 1500,
        "refresh_token": "execution-secret-value",
    }
    collection = db_session.query(KnowledgeCollection).filter_by(id="col-secure").one()
    collection.chunking_params = {
        "chunk_size": 800,
        "access_token": "collection-secret-value",
    }
    preset = db_session.query(RagPreset).filter_by(id="preset-rag").one()
    preset.config = {"mode": "hybrid", "provider_api_key": "preset-secret-value"}
    db_session.flush()

    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=workspace,
        exported_by=user,
    )
    encoded = json.dumps(blueprint, sort_keys=True)

    for secret in (
        "root-secret-value",
        "settings-secret-value",
        "pricing-secret-value",
        "context-secret-value",
        "flow-secret-value",
        "execution-secret-value",
        "collection-secret-value",
        "preset-secret-value",
        "bare-token-value",
        "dsn-value",
        "embedded-value",
        "bearer-value",
        "indirected-secret-value",
    ):
        assert secret not in encoded
    assert "settings" not in blueprint["workspace"]
    assert blueprint["experience"]["profile"] == {"family": "andritz"}
    assert blueprint["capabilities"][0]["pricing"] == {
        "unit": "session",
        "env": [{"name": "REGION", "value": "eu-west-1"}],
        "secretariat_label": "Executive office",
        "authorization_endpoint": "https://login.example.test/oauth/authorize",
        "passwordless_enabled": True,
        "public": {"currency": "EUR"},
    }
    assert blueprint["contexts"][0]["environment_state"] == {"site": "pilot"}
    assert blueprint["systems"][0]["execution_profile"] == {"latency_target_ms": 1500}
    assert blueprint["presets"]["rag"][0]["config"] == {"mode": "hybrid"}


def test_v1_import_explicitly_ignores_workspace_mode_and_settings(db_session):
    user = _user(db_session)
    target = _workspace(
        db_session,
        id_="ws-target",
        slug="target",
        settings={"family": "target-family"},
    )
    blueprint = {
        "kind": workspace_blueprints.BLUEPRINT_KIND,
        "schema_version": 1,
        "workspace": {
            "name": "Legacy",
            "slug": "legacy",
            "mode": "demo",
            "settings": {
                "family": "legacy-family",
                "password": "must-not-be-consumed",
            },
        },
        "capabilities": [],
        "contexts": [],
        "systems": [],
        "knowledge": {"collections": []},
        "presets": {"rag": [], "evaluation": []},
        "iam": {},
    }

    dry_run = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=user,
        dry_run=True,
        experience_policy="replace_portable",
    )
    report = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=user,
        dry_run=False,
        experience_policy="replace_portable",
        expected_plan_token=dry_run["plan_token"],
    )

    assert dry_run["experience"]["legacy_ignored"] == [
        "/workspace/mode",
        "/workspace/settings",
    ]
    assert report["experience"]["legacy_ignored"] == dry_run["experience"]["legacy_ignored"]
    assert target.mode == "executive"
    assert target.settings == {"family": "target-family"}


def test_v1_realistic_structural_export_round_trips_only_after_dry_run_token(
    db_session,
):
    source, user = _reference_workspace(db_session)
    db_session.add(
        EvaluationPreset(
            id="preset-evaluation",
            workspace_id=source.id,
            name="Legacy evaluation",
            scope="workspace",
            config={"judge": "grounded"},
            is_default=True,
        )
    )
    patch_iam_config(
        db_session,
        workspace_id=source.id,
        role_flags={"workspace_contributor": {"can_publish": False}},
        capability_overrides={"expert_knowledge_capture": {"can_publish": False}},
        updated_by_user_id=user.id,
    )
    db_session.flush()
    legacy = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    legacy["schema_version"] = 1
    legacy["workspace"]["settings"] = {
        "family": "must-remain-ignored",
        "password": "must-not-be-consumed",
    }
    legacy.pop("experience")
    target = _workspace(
        db_session,
        id_="ws-target",
        slug="target",
        settings={"family": "generic", "target_only": True},
    )

    dry_run = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=legacy,
        actor=user,
        dry_run=True,
    )
    assert dry_run["created"] == {
        "capabilities": 1,
        "contexts": 1,
        "collections": 1,
        "systems": 1,
        "presets": 2,
    }
    with pytest.raises(
        workspace_blueprints.WorkspaceBlueprintConflictError,
        match="plan_token",
    ):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=legacy,
            actor=user,
            dry_run=False,
        )

    report = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=legacy,
        actor=user,
        dry_run=False,
        expected_plan_token=dry_run["plan_token"],
    )

    assert report["created"] == dry_run["created"]
    assert target.settings == {"family": "generic", "target_only": True}
    assert db_session.query(System).filter(System.workspace_id == target.id).count() == 1
    assert (
        db_session.query(KnowledgeCollection)
        .filter(KnowledgeCollection.workspace_id == target.id)
        .count()
        == 1
    )
    assert (
        db_session.query(EvaluationPreset)
        .filter(EvaluationPreset.workspace_id == target.id)
        .count()
        == 1
    )
    target_iam = load_iam_config(db_session, target.id, create=False)
    assert target_iam is not None
    assert target_iam.capability_overrides == {"expert_knowledge_capture": {"can_publish": False}}


def test_experience_contract_v1_remains_readable_and_preserves_app_installations(
    db_session,
):
    source, user = _reference_workspace(db_session)
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    blueprint["experience"]["contract_version"] = 1
    blueprint["experience"].pop("workspace_apps")
    target = _workspace(
        db_session,
        id_="ws-contract-v1-target",
        slug="contract-v1-target",
        settings={"family": "andritz"},
    )
    installation = _install_builtin_app(
        db_session,
        workspace=target,
        app_id="andritz.chat",
        version="1.0.0",
    )

    dry_run, report = _validate_then_apply(
        db_session,
        target=target,
        blueprint=blueprint,
        actor=user,
    )

    assert dry_run["experience"]["workspace_apps"]["mode"] == "preserve_target"
    assert report["experience"]["workspace_apps"]["operations"] == []
    db_session.refresh(installation)
    assert installation.state == "installed"
    assert installation.version == "1.0.0"


def test_contract_v2_workspace_apps_round_trip_exact_manifests_and_configuration(
    db_session,
):
    source, user = _reference_workspace(db_session)
    _install_builtin_app(
        db_session,
        workspace=source,
        app_id="andritz.chat",
        version="1.0.0",
    )
    _install_builtin_app(
        db_session,
        workspace=source,
        app_id="andritz.knowledge-capture",
        version="1.0.0",
    )
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    target = _workspace(
        db_session,
        id_="ws-app-roundtrip-target",
        slug="app-roundtrip-target",
        settings={"family": "andritz"},
    )

    dry_run = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=user,
        dry_run=True,
    )

    assert blueprint["experience"]["contract_version"] == 2
    assert [
        item["app_id"] for item in blueprint["experience"]["workspace_apps"]["installations"]
    ] == ["andritz.chat", "andritz.knowledge-capture"]
    assert set(blueprint["experience"]["workspace_apps"]["installations"][0]) == {
        "app_id",
        "version",
        "manifest_digest",
        "config",
    }
    assert "settings" not in blueprint["experience"]["workspace_apps"]
    assert [item["action"] for item in dry_run["experience"]["workspace_apps"]["operations"]] == [
        "install",
        "install",
    ]
    assert (
        db_session.query(WorkspaceAppInstallation)
        .filter(WorkspaceAppInstallation.workspace_id == target.id)
        .count()
        == 0
    )
    assert (
        db_session.query(WorkspaceAppOperation)
        .filter(WorkspaceAppOperation.workspace_id == target.id)
        .count()
        == 0
    )

    report = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=user,
        dry_run=False,
        expected_plan_token=dry_run["plan_token"],
    )
    installed = (
        db_session.query(WorkspaceAppInstallation)
        .filter(
            WorkspaceAppInstallation.workspace_id == target.id,
            WorkspaceAppInstallation.state == "installed",
        )
        .order_by(WorkspaceAppInstallation.app_id.asc())
        .all()
    )
    assert [row.app_id for row in installed] == [
        "andritz.chat",
        "andritz.knowledge-capture",
    ]
    assert [row.version for row in installed] == ["1.0.0", "1.0.0"]
    assert installed[1].configuration == {
        "api_contract": "andritz.knowledge-capture.v1",
    }
    assert len(report["experience"]["workspace_apps"]["applied"]) == 2


def test_contract_v2_replace_portable_plans_apps_against_prospective_family(
    db_session,
):
    source, user = _reference_workspace(db_session)
    source.settings = {
        "family": "andritz",
        "features": {APP_ENTITLEMENTS_FEATURE: True},
    }
    _install_builtin_app(
        db_session,
        workspace=source,
        app_id="andritz.chat",
        version="1.0.0",
    )
    _install_builtin_app(
        db_session,
        workspace=source,
        app_id="andritz.knowledge-capture",
        version="1.0.0",
    )
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    target = _workspace(
        db_session,
        id_="ws-prospective-andritz-target",
        slug="prospective-andritz-target",
        settings={"family": "generic", "runtime_state": {"keep": True}},
    )
    membership = _add_member(
        db_session,
        workspace=target,
        user_id="user-2",
        username="prospective-member",
    )
    original_settings = deepcopy(target.settings)

    dry_run = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=user,
        dry_run=True,
        experience_policy="replace_portable",
        entitlement_policy="grant_all_existing_members",
    )

    assert dry_run["can_apply"] is True
    assert dry_run["experience"]["workspace_apps"]["conflicts"] == []
    assert [item["action"] for item in dry_run["experience"]["workspace_apps"]["operations"]] == [
        "install",
        "install",
    ]
    assert target.settings == original_settings
    assert db_session.is_modified(target, include_collections=True) is False
    assert (
        db_session.query(WorkspaceAppInstallation)
        .filter(WorkspaceAppInstallation.workspace_id == target.id)
        .count()
        == 0
    )

    report = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=user,
        dry_run=False,
        experience_policy="replace_portable",
        entitlement_policy="grant_all_existing_members",
        expected_plan_token=dry_run["plan_token"],
    )

    db_session.refresh(target)
    assert target.settings["family"] == "andritz"
    assert target.settings["runtime_state"] == {"keep": True}
    assert [
        row.app_id
        for row in (
            db_session.query(WorkspaceAppInstallation)
            .filter(
                WorkspaceAppInstallation.workspace_id == target.id,
                WorkspaceAppInstallation.state == "installed",
            )
            .order_by(WorkspaceAppInstallation.app_id.asc())
            .all()
        )
    ] == ["andritz.chat", "andritz.knowledge-capture"]
    assert len(report["experience"]["workspace_apps"]["applied"]) == 2
    assert dry_run["experience"]["app_access"]["required_apps"] == [
        "chat",
        "knowledge-capture",
        "fse-reports",
    ]
    assert report["experience"]["app_access"]["grants_created"] == 3
    assert {
        row.app_key
        for row in db_session.query(WorkspaceMemberAppEntitlement)
        .filter(WorkspaceMemberAppEntitlement.workspace_member_id == membership.id)
        .all()
    } == {"chat", "knowledge-capture", "fse-reports"}


def test_contract_v2_reused_app_cannot_end_in_incompatible_experience(db_session):
    source, user = _reference_workspace(db_session)
    _install_builtin_app(
        db_session,
        workspace=source,
        app_id="andritz.chat",
        version="1.0.0",
    )
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    blueprint["experience"]["profile"]["family"] = "generic"
    target = _workspace(
        db_session,
        id_="ws-incompatible-final-target",
        slug="incompatible-final-target",
        settings={"family": "andritz"},
    )
    installed = _install_builtin_app(
        db_session,
        workspace=target,
        app_id="andritz.chat",
        version="1.0.0",
    )

    dry_run = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=user,
        dry_run=True,
        experience_policy="replace_portable",
    )

    assert dry_run["can_apply"] is False
    assert any(
        item.get("reason") == "workspace_family_incompatible"
        and item.get("path") == "/experience/workspace_apps/installations/andritz.chat"
        for item in dry_run["experience"]["workspace_apps"]["conflicts"]
    )
    with pytest.raises(
        workspace_blueprints.WorkspaceBlueprintConflictError,
        match="experience conflicts",
    ):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=blueprint,
            actor=user,
            dry_run=False,
            experience_policy="replace_portable",
            expected_plan_token=dry_run["plan_token"],
        )

    db_session.refresh(target)
    db_session.refresh(installed)
    assert target.settings["family"] == "andritz"
    assert installed.state == "installed"


def test_contract_v2_rejects_entitlement_for_absent_app_without_dormant_grant(
    db_session,
):
    source = _workspace(
        db_session,
        id_="ws-absent-entitlement-source",
        slug="absent-entitlement-source",
        settings={
            "family": "andritz",
            "features": {APP_ENTITLEMENTS_FEATURE: True},
        },
    )
    user = _user(db_session)
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    blueprint["experience"]["app_access"]["required_apps"] = ["chat"]
    target = _workspace(
        db_session,
        id_="ws-absent-entitlement-target",
        slug="absent-entitlement-target",
        settings={"family": "andritz"},
    )
    membership = _add_member(
        db_session,
        workspace=target,
        user_id="user-2",
        username="absent-entitlement-member",
    )

    with pytest.raises(
        workspace_blueprints.WorkspaceBlueprintError,
        match="exactly match the entitlement_keys",
    ):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=blueprint,
            actor=user,
            dry_run=True,
            entitlement_policy="grant_all_existing_members",
        )

    assert (
        db_session.query(WorkspaceMemberAppEntitlement)
        .filter(WorkspaceMemberAppEntitlement.workspace_member_id == membership.id)
        .count()
        == 0
    )
    # A later lifecycle install cannot wake a grant that the invalid
    # Blueprint was never allowed to persist.
    _install_builtin_app(
        db_session,
        workspace=target,
        app_id="andritz.chat",
        version="1.0.0",
    )
    assert (
        db_session.query(WorkspaceMemberAppEntitlement)
        .filter(WorkspaceMemberAppEntitlement.workspace_member_id == membership.id)
        .count()
        == 0
    )


def test_contract_v2_installed_app_grants_exact_manifest_entitlements(db_session):
    source = _workspace(
        db_session,
        id_="ws-exact-entitlement-source",
        slug="exact-entitlement-source",
        settings={
            "family": "andritz",
            "features": {APP_ENTITLEMENTS_FEATURE: True},
        },
    )
    user = _user(db_session)
    _install_builtin_app(
        db_session,
        workspace=source,
        app_id="andritz.knowledge-capture",
        version="1.0.0",
    )
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    target = _workspace(
        db_session,
        id_="ws-exact-entitlement-target",
        slug="exact-entitlement-target",
        settings={"family": "andritz"},
    )
    membership = _add_member(
        db_session,
        workspace=target,
        user_id="user-2",
        username="exact-entitlement-member",
    )

    dry_run, report = _validate_then_apply(
        db_session,
        target=target,
        blueprint=blueprint,
        actor=user,
        entitlement_policy="grant_all_existing_members",
    )

    assert dry_run["experience"]["app_access"]["required_apps"] == [
        "knowledge-capture",
        "fse-reports",
    ]
    assert dry_run["experience"]["app_access"]["installed_entitlement_keys"] == [
        "knowledge-capture",
        "fse-reports",
    ]
    assert report["experience"]["app_access"]["grants_created"] == 2
    assert [
        row.app_key
        for row in db_session.query(WorkspaceMemberAppEntitlement)
        .filter(WorkspaceMemberAppEntitlement.workspace_member_id == membership.id)
        .order_by(WorkspaceMemberAppEntitlement.app_key.asc())
        .all()
    ] == ["fse-reports", "knowledge-capture"]


def test_contract_v2_locked_entitlement_revalidation_rolls_back_global_apply(
    db_session,
    monkeypatch,
):
    source = _workspace(
        db_session,
        id_="ws-locked-entitlement-source",
        slug="locked-entitlement-source",
        settings={
            "family": "andritz",
            "features": {APP_ENTITLEMENTS_FEATURE: True},
        },
    )
    user = _user(db_session)
    _install_builtin_app(
        db_session,
        workspace=source,
        app_id="andritz.chat",
        version="1.0.0",
    )
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    target = _workspace(
        db_session,
        id_="ws-locked-entitlement-target",
        slug="locked-entitlement-target",
        settings={"family": "generic", "runtime_state": {"keep": True}},
    )
    membership = _add_member(
        db_session,
        workspace=target,
        user_id="user-2",
        username="locked-entitlement-member",
    )
    db_session.commit()
    dry_run = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=user,
        dry_run=True,
        experience_policy="replace_portable",
        entitlement_policy="grant_all_existing_members",
    )

    # Simulate lifecycle drift after the valid locked plan: app access must
    # inspect installed digests again and abort the entire composition.
    monkeypatch.setattr(
        workspace_blueprints,
        "_apply_workspace_apps_plan",
        lambda **_kwargs: None,
    )
    with pytest.raises(
        workspace_blueprints.WorkspaceBlueprintConflictError,
        match="changed after",
    ):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=blueprint,
            actor=user,
            dry_run=False,
            experience_policy="replace_portable",
            entitlement_policy="grant_all_existing_members",
            expected_plan_token=dry_run["plan_token"],
        )

    db_session.expire_all()
    restored = db_session.query(Workspace).filter(Workspace.id == target.id).one()
    assert restored.settings == {"family": "generic", "runtime_state": {"keep": True}}
    assert (
        db_session.query(WorkspaceAppInstallation)
        .filter(WorkspaceAppInstallation.workspace_id == target.id)
        .count()
        == 0
    )
    assert (
        db_session.query(WorkspaceMemberAppEntitlement)
        .filter(WorkspaceMemberAppEntitlement.workspace_member_id == membership.id)
        .count()
        == 0
    )


def test_contract_v2_second_app_failure_rolls_back_experience_and_first_app(
    db_session,
    monkeypatch,
):
    # Keep this fixture intentionally structural: its committed precondition
    # must survive the deliberate transaction rollback without leaving the
    # fixed graph IDs used by the rest of this module in the test database.
    source = _workspace(
        db_session,
        id_="ws-atomic-app-failure-source",
        slug="atomic-app-failure-source",
        settings={"family": "andritz"},
    )
    user = _user(db_session)
    _install_builtin_app(
        db_session,
        workspace=source,
        app_id="andritz.chat",
        version="1.0.0",
    )
    _install_builtin_app(
        db_session,
        workspace=source,
        app_id="andritz.knowledge-capture",
        version="1.0.0",
    )
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    target = _workspace(
        db_session,
        id_="ws-atomic-app-failure-target",
        slug="atomic-app-failure-target",
        settings={"family": "generic", "runtime_state": {"keep": True}},
    )
    # Preserve the source and target fixtures across the deliberate lifecycle
    # rollback, just as they would already exist before an API transaction.
    db_session.commit()
    dry_run = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=user,
        dry_run=True,
        experience_policy="replace_portable",
    )
    original_planner = workspace_blueprints.plan_workspace_app_lifecycle

    def _tamper_second_plan(*args, **kwargs):
        plan = original_planner(*args, **kwargs)
        if kwargs.get("app_id") == "andritz.knowledge-capture":
            return replace(plan, plan_sha256="f" * 64)
        return plan

    monkeypatch.setattr(
        workspace_blueprints,
        "plan_workspace_app_lifecycle",
        _tamper_second_plan,
    )

    with pytest.raises(
        workspace_blueprints.WorkspaceBlueprintConflictError,
        match="changed after dry-run",
    ):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=blueprint,
            actor=user,
            dry_run=False,
            experience_policy="replace_portable",
            expected_plan_token=dry_run["plan_token"],
        )

    db_session.expire_all()
    restored = db_session.query(Workspace).filter(Workspace.id == target.id).one()
    assert restored.settings == {"family": "generic", "runtime_state": {"keep": True}}
    assert (
        db_session.query(WorkspaceAppInstallation)
        .filter(WorkspaceAppInstallation.workspace_id == target.id)
        .count()
        == 0
    )
    assert (
        db_session.query(WorkspaceAppOperation)
        .filter(WorkspaceAppOperation.workspace_id == target.id)
        .count()
        == 0
    )


def test_contract_v2_authoritative_dry_run_plans_removal_without_mutation(db_session):
    source, user = _reference_workspace(db_session)
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    target = _workspace(
        db_session,
        id_="ws-authoritative-removal",
        slug="authoritative-removal",
        settings={"family": "andritz"},
    )
    installation = _install_builtin_app(
        db_session,
        workspace=target,
        app_id="andritz.chat",
        version="1.0.0",
    )

    dry_run = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=user,
        dry_run=True,
    )

    assert [item["action"] for item in dry_run["experience"]["workspace_apps"]["operations"]] == [
        "uninstall"
    ]
    db_session.refresh(installation)
    assert installation.state == "installed"

    workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=user,
        dry_run=False,
        expected_plan_token=dry_run["plan_token"],
    )
    db_session.refresh(installation)
    assert installation.state == "uninstalled"


def test_contract_v2_cross_workspace_restore_converges_to_older_manifest(db_session):
    source = _workspace(
        db_session,
        id_="ws-blueprint-restore-source",
        slug="blueprint-restore-source",
        settings={"family": "generic"},
    )
    target = _workspace(
        db_session,
        id_="ws-blueprint-restore-target",
        slug="blueprint-restore-target",
        settings={"family": "generic"},
    )
    user = _user(db_session)
    _install_builtin_app(
        db_session,
        workspace=source,
        app_id="mission-room.extension",
        version="1.0.0",
    )
    target_installation = _install_builtin_app(
        db_session,
        workspace=target,
        app_id="mission-room.extension",
        version="1.1.0",
    )
    db_session.commit()

    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    dry_run = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=user,
        dry_run=True,
    )

    [operation] = dry_run["experience"]["workspace_apps"]["operations"]
    assert operation["action"] == "rollback"
    assert operation["request"]["allow_unrecorded_rollback"] is True

    workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=user,
        dry_run=False,
        expected_plan_token=dry_run["plan_token"],
    )

    db_session.refresh(target_installation)
    assert target_installation.version == "1.0.0"
    assert target_installation.configuration == {
        "assistant_profile": "default",
        "profile": "generic",
    }
    restore = (
        db_session.query(WorkspaceAppOperation)
        .filter(
            WorkspaceAppOperation.workspace_id == target.id,
            WorkspaceAppOperation.operation == "rollback",
        )
        .one()
    )
    assert restore.lifecycle_phase == "normal"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("version", "9.9.9", "unknown built-in"),
        ("manifest_digest", "0" * 64, "digest mismatch"),
    ],
)
def test_contract_v2_unknown_workspace_app_version_or_digest_fails_closed(
    db_session,
    field,
    value,
    message,
):
    source, user = _reference_workspace(db_session)
    _install_builtin_app(
        db_session,
        workspace=source,
        app_id="andritz.chat",
        version="1.0.0",
    )
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    blueprint["experience"]["workspace_apps"]["installations"][0][field] = value
    target = _workspace(
        db_session,
        id_=f"ws-invalid-app-{field}",
        slug=f"invalid-app-{field}",
        settings={"family": "andritz"},
    )

    with pytest.raises(workspace_blueprints.WorkspaceBlueprintError, match=message):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=blueprint,
            actor=user,
            dry_run=True,
        )

    assert (
        db_session.query(WorkspaceAppInstallation)
        .filter(WorkspaceAppInstallation.workspace_id == target.id)
        .count()
        == 0
    )


def test_blueprint_never_transports_authorization_enforce_authority_cross_workspace(
    db_session,
):
    source, user = _reference_workspace(db_session)
    source_attestation = {
        "workspace_id": source.id,
        "revision": "a" * 40,
        "evidence_sha256": "b" * 64,
    }
    patch_iam_config(
        db_session,
        workspace_id=source.id,
        capability_overrides={
            "portable_override": {"enabled": True},
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "enforce",
                "modes": {
                    "system.read": "enforce",
                    "run.read": "shadow",
                },
                "enforcement_attestations": {"system.read": source_attestation},
                "enforcement_history": [{"operation": "promote", "actor": "source"}],
            },
        },
        updated_by_user_id=user.id,
    )
    db_session.flush()

    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )

    exported_policy = blueprint["iam"]["capability_overrides"]["authorization_v2"]
    assert exported_policy["default_mode"] == "shadow"
    assert exported_policy["modes"] == {
        "system.read": "shadow",
        "run.read": "shadow",
    }
    assert "enforcement_attestations" not in exported_policy
    assert "enforcement_history" not in exported_policy
    assert source.id not in json.dumps(blueprint["iam"], sort_keys=True)

    # A hand-crafted payload cannot bypass the export-side downgrade.
    exported_policy["policy_version"] = 1
    exported_policy["modes"]["run.read"] = "enforce"
    exported_policy["enforcement_attestations"] = {
        "run.read": source_attestation,
    }
    exported_policy["enforcement_history"] = [{"operation": "promote", "actor": "forged-source"}]

    target = _workspace(db_session, id_="ws-blueprint-auth-target", slug="auth-target")
    target_attestation = {
        "workspace_id": target.id,
        "revision": "c" * 40,
        "evidence_sha256": "d" * 64,
    }
    patch_iam_config(
        db_session,
        workspace_id=target.id,
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "modes": {"system.admin": "enforce"},
                "enforcement_attestations": {"system.admin": target_attestation},
                "enforcement_history": [{"operation": "promote", "actor": "target"}],
            }
        },
        updated_by_user_id=user.id,
    )
    db_session.flush()

    _validate_then_apply(
        db_session,
        target=target,
        blueprint=blueprint,
        actor=user,
    )

    target_config = load_iam_config(db_session, target.id, create=False)
    assert target_config is not None
    applied = target_config.capability_overrides
    assert applied["portable_override"] == {"enabled": True}
    applied_policy = applied["authorization_v2"]
    assert applied_policy["policy_version"] == 2
    assert applied_policy["default_mode"] == "shadow"
    assert applied_policy["modes"] == {
        "system.read": "shadow",
        "run.read": "shadow",
        "system.admin": "enforce",
    }
    assert applied_policy["enforcement_attestations"] == {"system.admin": target_attestation}
    assert applied_policy["enforcement_history"] == [{"operation": "promote", "actor": "target"}]
    encoded = json.dumps(applied, sort_keys=True)
    assert source.id not in encoded
    assert "forged-source" not in encoded


def test_andritz_round_trip_backfills_all_members_before_entitlement_activation(db_session):
    source, user = _reference_workspace(db_session)
    source.mode = "operator"
    source.settings = {
        "family": "andritz",
        "hide_provider_details": True,
        "features": {
            WORKSPACE_EXPERIENCE_FEATURE: True,
            APP_ENTITLEMENTS_FEATURE: True,
            "unportable_feature": True,
        },
        "navigation_profile": {
            "key": "business_end_user",
            "default_route": "/client360-pdr",
            "primary_surfaces": list(BUSINESS_APP_KEYS),
            "advanced_access": "admin_only",
        },
        "default_route": "/client360-pdr",
        "workspace_app_shell": "standard",
        "workspace_app_label": "ANDRITZ",
        "workspace_app_default_view": "client360-pdr",
        "actions": {
            "enabled_packs": ["global_voice_v1", "andritz_industrial_v1"],
            "confirmation_policy": "confirm_side_effects",
            "runtime_history": ["not-portable"],
        },
        "assistant_profile_default": "andritz_operator",
        "assistant_profiles": [
            {
                "key": "andritz_operator",
                "label": "Industrial Assistant",
                "tone": "operational",
                "grounding": {
                    "default_mode": "strict",
                    "allowed_modes": ["strict", "balanced"],
                    "strict_guard": "default",
                },
                "actions": {
                    "enabled_packs": [
                        "global_voice_v1",
                        "andritz_industrial_v1",
                    ],
                    "confirmation_policy": "confirm_side_effects",
                },
            }
        ],
    }
    for app_id in (
        "andritz.chat",
        "andritz.client360-pdr",
        "andritz.knowledge-capture",
    ):
        _install_builtin_app(
            db_session,
            workspace=source,
            app_id=app_id,
            version="1.0.0",
        )
    db_session.flush()
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    target = _workspace(
        db_session,
        id_="ws-target",
        slug="andritz-target",
        settings={
            "family": "old-family",
            "features": {APP_ENTITLEMENTS_FEATURE: False},
            "runtime_cache": {"opaque": True},
        },
    )
    _add_member(
        db_session,
        workspace=target,
        user_id="user-2",
        username="member-two",
    )
    _add_member(
        db_session,
        workspace=target,
        user_id="user-3",
        username="member-three",
    )

    dry_run, report = _validate_then_apply(
        db_session,
        target=target,
        blueprint=blueprint,
        actor=user,
        experience_policy="replace_portable",
        entitlement_policy="grant_all_existing_members",
    )
    db_session.flush()

    # Lot 9 scopes app_access to the entitlement keys of the workspace's own
    # installations: the andritz reference ships four surfaces (chat,
    # client360-pdr, knowledge-capture, fse-reports) — not nawa-itsd, which
    # belongs to the nawa workspace.  The pre-lot-9 blanket BUSINESS_APP_KEYS
    # expectation would over-grant.
    required_apps = blueprint["experience"]["app_access"]["required_apps"]
    assert sorted(required_apps) == [
        "chat",
        "client360-pdr",
        "fse-reports",
        "knowledge-capture",
    ]
    expected_grants = 2 * len(required_apps)
    assert dry_run["experience"]["app_access"]["grants_planned"] == expected_grants
    assert report["experience"]["app_access"]["grants_created"] == expected_grants
    assert target.settings["features"][APP_ENTITLEMENTS_FEATURE] is True
    assert target.settings["runtime_cache"] == {"opaque": True}
    assert db_session.query(WorkspaceMemberAppEntitlement).join(
        WorkspaceMember,
        WorkspaceMember.id == WorkspaceMemberAppEntitlement.workspace_member_id,
    ).filter(WorkspaceMember.workspace_id == target.id).count() == expected_grants
    assert workspace_blueprints._serialize_workspace_experience(target) == blueprint["experience"]


def _mission_room_settings(kind: str) -> dict:
    sentinel = kind == "sentinel"
    profile = "sentinel_government_v1" if sentinel else "octocity_institutional_v1"
    demo_profile = "government_mission_room" if sentinel else "octocity_mission_room"
    assistant = "AYA" if sentinel else "OCTAVE"
    label = "SENTINEL-CI" if sentinel else "Octocity Mission Room"
    packs = [
        "global_voice_v1",
        "sentinel_ci_aya_v1" if sentinel else "octave_mission_room_v1",
        "sentinel_ci_aya_security_v1" if sentinel else "octave_security_v1",
    ]
    variant = "government_mission_room" if sentinel else "octocity_mission_room"
    navigation = [
        {
            "key": "cockpit",
            "label": "Cockpit",
            "glyph": "ledger",
            "variant": variant,
            "object": "Workbench",
        }
    ]
    brand = {
        "label": label,
        "lines": [label, "MISSION ROOM"],
        "emblem": "/assets/brand/sentinel-ci-emblem.png"
        if sentinel
        else "/assets/brand/agentium-mark.svg",
        "style": "sentinel" if sentinel else "agentium",
    }
    document_profile = "sentinel_ci_ministerial" if sentinel else "octocity_institutional"
    return {
        "family": "generic",
        "demo_profile": demo_profile,
        "hide_provider_details": True,
        "features": {WORKSPACE_EXPERIENCE_FEATURE: True},
        "default_route": "/hypervisor/mission-room/cockpit",
        "workspace_app_shell": "immersive",
        "workspace_app_label": label,
        "workspace_app_default_view": "cockpit",
        "workspace_app_brand": brand,
        "actions": {
            "enabled_packs": packs,
            "confirmation_policy": "confirm_side_effects",
        },
        "voice_loop": {
            "default_mode": "session_loop",
            "commands_enabled": True,
            "command_packs": packs,
            "trigger_word": assistant,
        },
        "calendar": {
            "mode": "internal_shared",
            "connector_id": "institutional_calendar",
            "connector_label": "Agenda institutionnel",
            "write_policy": "direct",
            "timezone": "Africa/Abidjan" if sentinel else "UTC",
            "api_key": "source-calendar-secret-must-not-export",
        },
        "action_planner": {
            "write_policy": "direct",
            "default_owner": "Cabinet" if sentinel else "Coordination",
            "advisory_only": True,
        },
        "document_intelligence": {
            "enabled": True,
            "default_profile": document_profile,
            "profiles": [
                {
                    "key": document_profile,
                    "label": f"{label} institutional documents",
                    "synonyms": {"briefing": ["brief", "note"]},
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
            "allowed_adapters": ["demo_static", "http_image"],
            "storage_policy": "snapshot_only_no_continuous_recording",
            "analysis_policy": "no_identification_no_biometrics",
            "source_model": "live_webcam_embed_layer",
        },
        "feature_flag": {"security_live_osint": False, "runtime_only": True},
        "connectors": {
            "institutional_calendar": {
                "enabled": True,
                "status": "connected",
                "mode": "internal_shared",
                "label": "Agenda institutionnel",
                "access_token": "source-connector-secret-must-not-export",
            },
            "visual_streams": {
                "enabled": True,
                "status": "connected",
                "mode": "live_webcam_embed_layer",
                "label": "Flux visuels institutionnels",
            },
        },
        "mission_room": {
            "enabled": True,
            "profile": profile,
            "country": "Cote d'Ivoire" if sentinel else "Asteria",
            "country_code": "CI" if sentinel else "AS",
            "region_scope": ["West Africa"] if sentinel else ["Atlantic Arc"],
            "label": assistant,
            "assistant_label": assistant,
            "brand": brand,
            "root_route": "/hypervisor/mission-room",
            "default_view": "cockpit",
            "navigation": navigation,
        },
    }


@pytest.mark.parametrize(
    ("kind", "forbidden_terms"),
    [
        ("sentinel", ("octocity", "octave")),
        ("octocity", ("sentinel",)),
    ],
)
def test_mission_room_round_trip_keeps_brand_and_action_pack_namespaces_isolated(
    db_session,
    kind,
    forbidden_terms,
):
    user = _user(db_session)
    source = _workspace(
        db_session,
        id_="ws-source",
        slug=f"{kind}-source",
        mode="demo",
        settings=_mission_room_settings(kind),
    )
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    experience_text = json.dumps(blueprint["experience"], sort_keys=True).lower()
    assert "source-calendar-secret-must-not-export" not in experience_text
    assert "source-connector-secret-must-not-export" not in experience_text
    for term in forbidden_terms:
        assert term not in experience_text

    target = _workspace(
        db_session,
        id_="ws-target",
        slug=f"{kind}-target",
        settings={
            "family": "legacy",
            "runtime_state": {"keep": True},
            "calendar": {"runtime_cursor": "keep"},
            "connectors": {
                "private_runtime_connector": {"api_key": "target-runtime-secret-must-remain"},
                "institutional_calendar": {"runtime_session": "keep"},
            },
        },
    )
    _dry_run, report = _validate_then_apply(
        db_session,
        target=target,
        blueprint=blueprint,
        actor=user,
        experience_policy="replace_portable",
    )

    assert report["experience"]["conflicts"] == []
    assert target.mode == "demo"
    assert target.settings["runtime_state"] == {"keep": True}
    assert target.settings["calendar"]["runtime_cursor"] == "keep"
    assert target.settings["connectors"]["private_runtime_connector"] == {
        "api_key": "target-runtime-secret-must-remain"
    }
    assert target.settings["connectors"]["institutional_calendar"]["runtime_session"] == "keep"
    dependencies = blueprint["experience"]["extensions"]["mission-room"]["dependencies"]
    assert set(dependencies) == {
        "calendar",
        "action_planner",
        "document_intelligence",
        "visual_intelligence",
        "feature_flags",
        "connectors",
    }
    assert dependencies["feature_flags"] == {"security_live_osint": False}
    assert workspace_blueprints._serialize_workspace_experience(target) == blueprint["experience"]


def test_merge_conflict_replace_idempotence_and_stale_plan_detection(db_session):
    user = _user(db_session)
    source = _workspace(
        db_session,
        id_="ws-source",
        slug="source",
        settings={
            "family": "generic",
            "features": {WORKSPACE_EXPERIENCE_FEATURE: True},
        },
    )
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    target = _workspace(
        db_session,
        id_="ws-target",
        slug="target",
        settings={"family": "sentinel_ci"},
    )

    conflict_plan = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=user,
        dry_run=True,
        experience_policy="merge_missing",
    )
    assert conflict_plan["can_apply"] is False
    assert any(
        item["path"] == "/workspace/settings/family"
        for item in conflict_plan["experience"]["conflicts"]
    )
    with pytest.raises(workspace_blueprints.WorkspaceBlueprintConflictError):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=blueprint,
            actor=user,
            dry_run=False,
            experience_policy="merge_missing",
            expected_plan_token=conflict_plan["plan_token"],
        )
    assert target.settings == {"family": "sentinel_ci"}

    first_plan, _first_apply = _validate_then_apply(
        db_session,
        target=target,
        blueprint=blueprint,
        actor=user,
        experience_policy="replace_portable",
    )
    assert first_plan["experience"]["applied"]
    second_plan = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=user,
        dry_run=True,
        experience_policy="replace_portable",
    )
    assert second_plan["experience"]["applied"] == []
    assert second_plan["experience"]["conflicts"] == []

    target.settings = {**target.settings, "family": "andritz"}
    db_session.flush()
    with pytest.raises(workspace_blueprints.WorkspaceBlueprintConflictError):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=blueprint,
            actor=user,
            dry_run=False,
            experience_policy="replace_portable",
            expected_plan_token=second_plan["plan_token"],
        )


def test_system_status_and_execution_mode_are_canonicalized_before_activation(db_session):
    source, user = _reference_workspace(db_session)
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    blueprint["systems"][0]["execution_mode"] = " human_augmented "
    blueprint["systems"][0]["source_status"] = " active "
    target = _workspace(db_session, id_="ws-target", slug="target")

    _dry_run, _report = _validate_then_apply(
        db_session,
        target=target,
        blueprint=blueprint,
        actor=user,
        activate_systems=True,
    )
    imported = db_session.query(System).filter(System.workspace_id == target.id).one()
    assert imported.execution_mode == "human_augmented"
    assert imported.status == "active"

    invalid = {**blueprint, "systems": [dict(blueprint["systems"][0])]}
    invalid["systems"][0]["source_status"] = "running"
    with pytest.raises(workspace_blueprints.WorkspaceBlueprintError):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=invalid,
            actor=user,
            dry_run=True,
            activate_systems=True,
        )


def _as_legacy_object_identity_blueprint(blueprint: dict) -> dict:
    legacy = deepcopy(blueprint)
    for context in legacy.get("contexts") or []:
        context.pop("stable_key", None)
        context.pop("system_key", None)
    for system in legacy.get("systems") or []:
        system.pop("stable_key", None)
        system.pop("context_key", None)
    for kind in ("rag", "evaluation"):
        for preset in (legacy.get("presets") or {}).get(kind) or []:
            preset.pop("scope_key", None)
    return legacy


def test_blueprint_keys_are_generated_while_display_names_remain_non_unique(db_session):
    workspace = _workspace(db_session, id_="ws-generated-keys", slug="generated-keys")
    contexts = [
        Context(workspace_id=workspace.id, name="Homonym", ephemeral=False),
        Context(workspace_id=workspace.id, name="Homonym", ephemeral=False),
    ]
    systems = [
        System(workspace_id=workspace.id, name="Homonym", objective="First"),
        System(workspace_id=workspace.id, name="Homonym", objective="Second"),
    ]
    db_session.add_all([*contexts, *systems])
    db_session.flush()

    assert all(row.blueprint_key for row in [*contexts, *systems])
    assert len({row.blueprint_key for row in contexts}) == 2
    assert len({row.blueprint_key for row in systems}) == 2


def test_blueprint_v2_round_trip_preserves_homonyms_bidirectional_edges_and_preset_scope(
    db_session,
):
    source, user = _reference_workspace(db_session)
    primary_context = db_session.query(Context).filter(Context.id == "ctx-andritz").one()
    primary_system = db_session.query(System).filter(System.id == "sys-capture").one()
    primary_context.system_id = primary_system.id

    second_context = Context(
        id="ctx-andritz-second",
        workspace_id=source.id,
        blueprint_key="context-stable-second",
        name=primary_context.name,
        data_refs=["collection:second"],
        ephemeral=False,
    )
    second_system = System(
        id="sys-capture-second",
        workspace_id=source.id,
        blueprint_key="system-stable-second",
        name=primary_system.name,
        objective="A distinct System with the same display name.",
        capability_id=primary_system.capability_id,
        context_id=second_context.id,
        skill_ids=list(primary_system.skill_ids or []),
        flow_definition=deepcopy(primary_system.flow_definition),
        execution_mode=primary_system.execution_mode,
        execution_profile=deepcopy(primary_system.execution_profile),
        status="active",
    )
    second_context.system_id = second_system.id
    primary_preset = RagPreset(
        id="preset-system-primary",
        workspace_id=source.id,
        name="System scoped primary",
        scope="system",
        scope_id=primary_system.id,
        config={"topK": 3},
    )
    second_preset = RagPreset(
        id="preset-system-second",
        workspace_id=source.id,
        name="System scoped second",
        scope="system",
        scope_id=second_system.id,
        config={"topK": 7},
    )
    db_session.add_all([second_context, second_system, primary_preset, second_preset])
    db_session.flush()

    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    contexts_by_key = {item["stable_key"]: item for item in blueprint["contexts"]}
    systems_by_key = {item["stable_key"]: item for item in blueprint["systems"]}
    assert len(contexts_by_key) == 2
    assert len(systems_by_key) == 2
    assert contexts_by_key[primary_context.blueprint_key]["system_key"] == (
        primary_system.blueprint_key
    )
    assert contexts_by_key[second_context.blueprint_key]["system_key"] == (
        second_system.blueprint_key
    )
    assert systems_by_key[primary_system.blueprint_key]["context_key"] == (
        primary_context.blueprint_key
    )
    assert systems_by_key[second_system.blueprint_key]["context_key"] == (
        second_context.blueprint_key
    )
    assert {
        item["name"]: item["scope_key"]
        for item in blueprint["presets"]["rag"]
        if item["scope"] == "system"
    } == {
        "System scoped primary": primary_system.blueprint_key,
        "System scoped second": second_system.blueprint_key,
    }

    target = _workspace(db_session, id_="ws-keyed-roundtrip", slug="keyed-roundtrip")
    _validate_then_apply(
        db_session,
        target=target,
        blueprint=blueprint,
        actor=user,
    )
    target_contexts = {
        row.blueprint_key: row
        for row in db_session.query(Context).filter(Context.workspace_id == target.id).all()
    }
    target_systems = {
        row.blueprint_key: row
        for row in db_session.query(System).filter(System.workspace_id == target.id).all()
    }
    assert [row.name for row in target_contexts.values()] == [
        primary_context.name,
        primary_context.name,
    ]
    assert [row.name for row in target_systems.values()] == [
        primary_system.name,
        primary_system.name,
    ]
    for source_context in (primary_context, second_context):
        imported = target_contexts[source_context.blueprint_key]
        source_system = primary_system if source_context is primary_context else second_system
        assert imported.system_id == target_systems[source_system.blueprint_key].id
    for source_system in (primary_system, second_system):
        imported = target_systems[source_system.blueprint_key]
        source_context = primary_context if source_system is primary_system else second_context
        assert imported.context_id == target_contexts[source_context.blueprint_key].id

    scoped_presets = (
        db_session.query(RagPreset)
        .filter(RagPreset.workspace_id == target.id, RagPreset.scope == "system")
        .all()
    )
    assert {row.name: row.scope_id for row in scoped_presets} == {
        "System scoped primary": target_systems[primary_system.blueprint_key].id,
        "System scoped second": target_systems[second_system.blueprint_key].id,
    }


def test_keyed_blueprint_creates_legitimate_homonym_instead_of_adopting_by_name(
    db_session,
):
    source, user = _reference_workspace(db_session)
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    target = _workspace(db_session, id_="ws-keyed-homonym", slug="keyed-homonym")
    existing_context = Context(
        id="target-context-homonym",
        workspace_id=target.id,
        blueprint_key="target-context-key",
        name=blueprint["contexts"][0]["name"],
        ephemeral=False,
    )
    existing_system = System(
        id="target-system-homonym",
        workspace_id=target.id,
        blueprint_key="target-system-key",
        name=blueprint["systems"][0]["name"],
        objective="Existing unrelated homonym",
    )
    db_session.add_all([existing_context, existing_system])
    db_session.flush()

    _dry_run, report = _validate_then_apply(
        db_session,
        target=target,
        blueprint=blueprint,
        actor=user,
    )

    assert report["created"]["contexts"] == 1
    assert report["created"]["systems"] == 1
    assert report["reused"]["contexts"] == 0
    assert report["reused"]["systems"] == 0
    assert db_session.query(Context).filter(Context.workspace_id == target.id).count() == 2
    assert db_session.query(System).filter(System.workspace_id == target.id).count() == 2


def test_legacy_unkeyed_blueprint_creates_deterministic_keys_and_is_idempotent(
    db_session,
):
    source, user = _reference_workspace(db_session)
    blueprint = _as_legacy_object_identity_blueprint(
        workspace_blueprints.export_workspace_blueprint(
            db=db_session,
            workspace=source,
            exported_by=user,
        )
    )
    target = _workspace(db_session, id_="ws-legacy-new", slug="legacy-new")

    _validate_then_apply(
        db_session,
        target=target,
        blueprint=blueprint,
        actor=user,
    )
    context = db_session.query(Context).filter(Context.workspace_id == target.id).one()
    system = db_session.query(System).filter(System.workspace_id == target.id).one()
    assert context.blueprint_key == workspace_blueprints._legacy_blueprint_key(
        "context",
        context.name,
    )
    assert system.blueprint_key == workspace_blueprints._legacy_blueprint_key(
        "system",
        system.name,
    )

    _dry_run, second = _validate_then_apply(
        db_session,
        target=target,
        blueprint=blueprint,
        actor=user,
    )
    assert second["created"]["contexts"] == 0
    assert second["created"]["systems"] == 0
    assert second["reused"]["contexts"] == 1
    assert second["reused"]["systems"] == 1


def test_legacy_unkeyed_blueprint_adopts_exactly_one_named_target_object(db_session):
    source, user = _reference_workspace(db_session)
    blueprint = _as_legacy_object_identity_blueprint(
        workspace_blueprints.export_workspace_blueprint(
            db=db_session,
            workspace=source,
            exported_by=user,
        )
    )
    target = _workspace(db_session, id_="ws-legacy-adopt", slug="legacy-adopt")
    context = Context(
        id="legacy-adopt-context",
        workspace_id=target.id,
        name=blueprint["contexts"][0]["name"],
        ephemeral=False,
    )
    system = System(
        id="legacy-adopt-system",
        workspace_id=target.id,
        name=blueprint["systems"][0]["name"],
        objective="Pre-existing legacy target",
    )
    db_session.add_all([context, system])
    db_session.flush()
    original_context_key = context.blueprint_key
    original_system_key = system.blueprint_key

    _dry_run, report = _validate_then_apply(
        db_session,
        target=target,
        blueprint=blueprint,
        actor=user,
    )

    assert report["reused"]["contexts"] == 1
    assert report["reused"]["systems"] == 1
    assert context.blueprint_key == original_context_key
    assert system.blueprint_key == original_system_key


def test_legacy_unkeyed_blueprint_rejects_ambiguous_target_homonyms(db_session):
    source, user = _reference_workspace(db_session)
    blueprint = _as_legacy_object_identity_blueprint(
        workspace_blueprints.export_workspace_blueprint(
            db=db_session,
            workspace=source,
            exported_by=user,
        )
    )
    target = _workspace(db_session, id_="ws-legacy-ambiguous", slug="legacy-ambiguous")
    name = blueprint["contexts"][0]["name"]
    db_session.add_all(
        [
            Context(id="legacy-ambiguous-1", workspace_id=target.id, name=name, ephemeral=False),
            Context(id="legacy-ambiguous-2", workspace_id=target.id, name=name, ephemeral=False),
        ]
    )
    db_session.flush()

    with pytest.raises(
        workspace_blueprints.WorkspaceBlueprintConflictError,
        match="matches more than one target object",
    ):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=blueprint,
            actor=user,
            dry_run=True,
        )


def test_legacy_unkeyed_blueprint_rejects_ambiguous_payload_entries(db_session):
    source, user = _reference_workspace(db_session)
    blueprint = _as_legacy_object_identity_blueprint(
        workspace_blueprints.export_workspace_blueprint(
            db=db_session,
            workspace=source,
            exported_by=user,
        )
    )
    blueprint["contexts"].append(deepcopy(blueprint["contexts"][0]))
    target = _workspace(db_session, id_="ws-legacy-payload", slug="legacy-payload")

    with pytest.raises(
        workspace_blueprints.WorkspaceBlueprintConflictError,
        match="ambiguous inside the Blueprint",
    ):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=blueprint,
            actor=user,
            dry_run=True,
        )


def test_keyed_blueprint_refuses_to_reuse_system_with_hidden_catalog_binding(db_session):
    source, user = _reference_workspace(db_session)
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    target = _workspace(
        db_session,
        id_="ws-hidden-catalog-binding",
        slug="hidden-catalog-binding",
        settings={"family": "generic"},
    )
    hidden = Capability(
        id="cap-hidden-government",
        workspace_id=None,
        slug="hidden_government_capability",
        name="Hidden government capability",
        tier="industry",
        industry="government",
        skill_ids=["skill-rag"],
    )
    existing = System(
        id="system-hidden-catalog-binding",
        workspace_id=target.id,
        name="Existing keyed System",
        objective="Must not be adopted through an invisible catalog binding.",
        capability_id=hidden.id,
        skill_ids=["skill-rag"],
        flow_definition={"nodes": [], "edges": []},
        status="draft",
    )
    db_session.add_all([hidden, existing])
    db_session.flush()
    blueprint["systems"][0]["stable_key"] = existing.blueprint_key

    with pytest.raises(
        workspace_blueprints.WorkspaceBlueprintConflictError,
        match="invalid catalog binding: capability_not_visible",
    ):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=blueprint,
            actor=user,
            dry_run=True,
        )


def test_key_reference_cannot_bind_to_object_outside_blueprint(db_session):
    source, user = _reference_workspace(db_session)
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    context_key = blueprint["contexts"][0]["stable_key"]
    blueprint["contexts"] = []
    target = _workspace(db_session, id_="ws-key-ref-scope", slug="key-ref-scope")
    db_session.add(
        Context(
            id="same-key-but-not-imported",
            workspace_id=target.id,
            blueprint_key=context_key,
            name="Existing same key",
            ephemeral=False,
        )
    )
    db_session.flush()

    with pytest.raises(
        workspace_blueprints.WorkspaceBlueprintError,
        match="does not resolve inside this Blueprint",
    ):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=blueprint,
            actor=user,
            dry_run=True,
        )


def test_import_rejects_credential_shaped_fields_in_arbitrary_configs(db_session):
    source, user = _reference_workspace(db_session)
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    target = _workspace(db_session, id_="ws-target", slug="target")
    mutations = (
        {"api_key": "do-not-import"},
        {"token": "bare-secret-token"},
        {"warehouse_dsn": "postgresql://user:password@example.test/data"},
        {"header": "Bearer opaque-secret"},
        {"endpoint": "https://user:password@example.test/api"},
        {"endpoint": "https://example.test/api?access_token=opaque-secret"},
        {"env": [{"name": "OPENAI_API_KEY", "value": "opaque-secret"}]},
    )

    for mutation in mutations:
        candidate = deepcopy(blueprint)
        candidate["systems"][0]["execution_profile"].update(mutation)
        with pytest.raises(
            workspace_blueprints.WorkspaceBlueprintError,
            match="Credential-shaped (field|value|indirection)",
        ):
            workspace_blueprints.apply_workspace_blueprint(
                db=db_session,
                workspace=target,
                blueprint=candidate,
                actor=user,
                dry_run=True,
            )

    benign = deepcopy(blueprint)
    benign["systems"][0]["execution_profile"].update(
        {
            "secretariat_label": "Executive office",
            "authorization_endpoint": "https://login.example.test/oauth/authorize",
            "passwordless_enabled": True,
        }
    )
    workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=benign,
        actor=user,
        dry_run=True,
    )


def test_mission_dependencies_reject_credentials_and_v2_rejects_raw_settings(db_session):
    user = _user(db_session)
    source = _workspace(
        db_session,
        id_="ws-source",
        slug="sentinel-source",
        mode="demo",
        settings=_mission_room_settings("sentinel"),
    )
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    target = _workspace(db_session, id_="ws-target", slug="target")

    for invalid_version in (True, 1.0, 2.0, "2"):
        invalid_schema = deepcopy(blueprint)
        invalid_schema["schema_version"] = invalid_version
        with pytest.raises(
            workspace_blueprints.WorkspaceBlueprintError,
            match="Unsupported schema_version",
        ):
            workspace_blueprints.apply_workspace_blueprint(
                db=db_session,
                workspace=target,
                blueprint=invalid_schema,
                actor=user,
                dry_run=True,
            )

    invalid_contract = deepcopy(blueprint)
    invalid_contract["experience"]["contract_version"] = True
    with pytest.raises(
        workspace_blueprints.WorkspaceBlueprintError,
        match="experience.contract_version",
    ):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=invalid_contract,
            actor=user,
            dry_run=True,
        )

    raw_settings = deepcopy(blueprint)
    raw_settings["workspace"]["settings"] = {"family": "decorative-only"}
    with pytest.raises(
        workspace_blueprints.WorkspaceBlueprintError,
        match="Unknown fields at /workspace: settings",
    ):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=raw_settings,
            actor=user,
            dry_run=True,
        )

    unknown_family = deepcopy(blueprint)
    unknown_family["experience"]["profile"]["family"] = "decorative-only"
    with pytest.raises(
        workspace_blueprints.WorkspaceBlueprintError,
        match="canonical workspace family",
    ):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=unknown_family,
            actor=user,
            dry_run=True,
        )

    noncanonical_pack = deepcopy(blueprint)
    noncanonical_pack["experience"]["actions"]["enabled_packs"] = [" global_voice_v1 "]
    with pytest.raises(
        workspace_blueprints.WorkspaceBlueprintError,
        match="must be trimmed and unique",
    ):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=noncanonical_pack,
            actor=user,
            dry_run=True,
        )

    credential = deepcopy(blueprint)
    dependencies = credential["experience"]["extensions"]["mission-room"]["dependencies"]
    dependencies["connectors"]["institutional_calendar"]["api_key"] = "forbidden"
    with pytest.raises(
        workspace_blueprints.WorkspaceBlueprintError,
        match="Credential-shaped field",
    ):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=credential,
            actor=user,
            dry_run=True,
        )


def test_mutating_apply_reauthorizes_immediately_after_workspace_lock(
    db_session,
    monkeypatch,
):
    source, user = _reference_workspace(db_session)
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    target = _workspace(db_session, id_="ws-target", slug="target")
    dry_run = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=user,
        dry_run=True,
    )
    events: list[str] = []
    original_lock = workspace_blueprints._lock_workspace

    def _recording_lock(db, workspace):
        events.append("lock")
        return original_lock(db, workspace)

    class _AuthorityLostError(RuntimeError):
        pass

    def _deny_after_lock(locked_workspace):
        events.append("reauthorize")
        assert locked_workspace.id == target.id
        raise _AuthorityLostError("caller was demoted while waiting")

    monkeypatch.setattr(workspace_blueprints, "_lock_workspace", _recording_lock)

    with pytest.raises(_AuthorityLostError, match="demoted"):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=blueprint,
            actor=user,
            dry_run=False,
            expected_plan_token=dry_run["plan_token"],
            locked_workspace_guard=_deny_after_lock,
        )

    assert events == ["lock", "reauthorize"]
    assert db_session.query(System).filter(System.workspace_id == target.id).count() == 0


def test_replace_portable_blocks_before_erasing_private_state_in_object_lists(
    db_session,
):
    navigation_source = {
        "key": "cockpit",
        "label": "Source cockpit",
        "glyph": "radar",
        "variant": "primary",
        "object": "mission",
    }
    navigation_target = {
        **navigation_source,
        "label": "Target cockpit",
        "runtime_cursor": "private-navigation-state",
    }
    source = _workspace(
        db_session,
        id_="ws-source",
        slug="source",
        settings={
            "family": "generic",
            "assistant_profiles": [{"key": "guide", "label": "Source guide"}],
            "knowledge_scopes": [
                {
                    "key": "primary",
                    "label": "Source scope",
                    "collection_slugs": ["source-collection"],
                }
            ],
            "mission_room": {"enabled": True, "navigation": [navigation_source]},
            "document_intelligence": {
                "enabled": True,
                "profiles": [{"key": "brief", "label": "Source brief"}],
            },
        },
    )
    user = _user(db_session)
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    target_settings = {
        "family": "generic",
        "assistant_profiles": [
            {
                "key": "guide",
                "label": "Target guide",
                "runtime_session": "private-assistant-state",
            }
        ],
        "knowledge_scopes": [
            {
                "key": "primary",
                "label": "Target scope",
                "collection_slugs": ["target-collection"],
                "runtime_cache": "private-scope-state",
            }
        ],
        "mission_room": {"enabled": True, "navigation": [navigation_target]},
        "document_intelligence": {
            "enabled": True,
            "profiles": [
                {
                    "key": "brief",
                    "label": "Target brief",
                    "runtime_model": "private-document-state",
                }
            ],
        },
    }
    target = _workspace(
        db_session,
        id_="ws-target",
        slug="target",
        settings=deepcopy(target_settings),
    )

    report = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=user,
        dry_run=True,
        experience_policy="replace_portable",
    )

    conflict_paths = {
        item["path"]
        for item in report["experience"]["conflicts"]
        if item.get("reason") == "target_contains_nonportable_list_state"
    }
    assert conflict_paths == {
        "/workspace/settings/assistant_profiles",
        "/workspace/settings/knowledge_scopes",
        "/workspace/settings/mission_room/navigation",
        "/workspace/settings/document_intelligence/profiles",
    }
    encoded_report = json.dumps(report, sort_keys=True)
    assert "private-assistant-state" not in encoded_report
    assert "private-scope-state" not in encoded_report
    assert "private-navigation-state" not in encoded_report
    assert "private-document-state" not in encoded_report

    with pytest.raises(
        workspace_blueprints.WorkspaceBlueprintConflictError,
        match="experience conflicts",
    ):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=blueprint,
            actor=user,
            dry_run=False,
            experience_policy="replace_portable",
            expected_plan_token=report["plan_token"],
        )
    assert target.settings == target_settings
