"""P1 server-draft and atomic publication HTTP contract."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.v1.endpoints import flow_publication as endpoint
from app.api.v1.endpoints import runs as runs_endpoint
from app.api.v1.endpoints import systems
from app.models.capability import Capability
from app.models.run import Run
from app.models.skill import Skill
from app.models.system import System
from app.models.system_flow_draft import SystemFlowDraft
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.workspace import Workspace
from app.services import flow_contracts
from app.services.run_engine.execution_contract import canonical_flow_sha256
from app.services.systems import flow_publication


def _flow(label: str) -> dict[str, Any]:
    # Minimal executable Flow: publication tests also exercise the normalized
    # manual ingress used by the canonical System Run endpoint.
    return {
        "schema_version": 3,
        "io_mode": "overlay",
        "label": label,
        "nodes": [
            {
                "id": "manual",
                "kind": "source",
                "config": {
                    "input_schema": {
                        "type": "object",
                        "properties": {"case": {"type": "string"}},
                        "required": ["case"],
                        "additionalProperties": False,
                    }
                },
            },
            {"id": "result", "kind": "sink"},
        ],
        "edges": [{"from": "manual", "to": "result", "kind": "data"}],
    }


def _multi_ingress_flow(label: str) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "io_mode": "overlay",
        "label": label,
        "nodes": [
            {
                "id": "manual",
                "kind": "source",
                "config": {"ingress_kind": "manual"},
            },
            {
                "id": "webhook",
                "type": "source.webhook",
                "kind": "source",
                "config": {"ingress_kind": "http"},
            },
            {"id": "result", "kind": "sink"},
        ],
        "edges": [
            {"from": "manual", "to": "result", "kind": "data"},
            {"from": "webhook", "to": "result", "kind": "data"},
        ],
    }


def _seed(db_session, *, enabled: bool = True, status: str = "active"):
    workspace = Workspace(
        id="ws-publication",
        slug="flow-publication",
        name="Flow publication",
        settings={"features": {"flow_publication_v1": enabled}},
    )
    user = User(
        id="user-publication",
        username="publisher@example.invalid",
        email="publisher@example.invalid",
        role="admin",
    )
    system = System(
        id="system-publication",
        workspace_id=workspace.id,
        name="Published System",
        objective="test",
        status=status,
        settings={},
        skill_ids=[],
        flow_definition=_flow("published-v1"),
        created_by=user.email,
    )
    db_session.add_all([workspace, user, system])
    db_session.commit()
    if enabled:
        flow_publication.initialize_publication_state(
            db_session,
            system=system,
            workspace=workspace,
            actor=user.email,
        )
        db_session.commit()
        db_session.refresh(system)
    return workspace, user, system


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/systems")
    app.dependency_overrides[endpoint.get_current_workspace] = lambda: workspace
    app.dependency_overrides[endpoint.get_current_user] = lambda: user
    app.dependency_overrides[endpoint.get_db] = lambda: db_session
    return TestClient(app)


def _systems_client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(systems.router, prefix="/systems")
    app.dependency_overrides[systems.get_current_workspace] = lambda: workspace
    app.dependency_overrides[systems.get_current_user] = lambda: user
    app.dependency_overrides[systems.get_db] = lambda: db_session
    return TestClient(app)


def test_feature_on_envelope_import_initializes_published_flow_authority(
    db_session,
) -> None:
    workspace, user, _ = _seed(db_session)
    response = _systems_client(db_session, workspace, user).post(
        "/systems/import",
        json={
            "envelope": {
                "kind": "agentium.system.export",
                "schema_version": 1,
                "exported_at": "2026-08-06T12:00:00Z",
                "exported_by": "source@example.invalid",
                "source": {"workspace_id": "source", "system_id": "source-system"},
                "system": {
                    "name": "Imported published System",
                    "objective": "Prove post-migration initialization",
                    "flow_definition": _flow("imported-v1"),
                    "skill_slugs": [],
                    "execution_mode": "real_time_decision",
                    "execution_profile": {},
                    "coordination_pattern": "single_agent",
                },
            }
        },
    )

    assert response.status_code == 200, response.text
    imported = (
        db_session.query(System)
        .filter_by(workspace_id=workspace.id, name="Imported published System")
        .one()
    )
    draft = db_session.query(SystemFlowDraft).filter_by(system_id=imported.id).one()
    version = (
        db_session.query(SystemVersion)
        .filter_by(system_id=imported.id, id=imported.published_flow_version_id)
        .one()
    )
    assert draft.base_published_version_id == version.id
    assert draft.flow_sha256 == version.flow_sha256
    assert version.release_kind == "migration"
    assert version.execution_contract is not None
    assert db_session.query(SystemVersion).filter_by(system_id=imported.id).count() == 1


def test_contract_allowlist_uses_bound_capability_skills_when_system_list_is_empty(
    db_session,
) -> None:
    workspace, _, system = _seed(db_session)
    skill = Skill(
        id="skill-capability-publication",
        workspace_id=workspace.id,
        slug="capability-publication-skill",
        version="1",
        name="Capability publication Skill",
        input_schema={},
        output_schema={},
        execution={},
        executor={
            "kind": "registry_call",
            "params": {"skill_slug": "audit_log_v1"},
        },
    )
    capability = Capability(
        id="capability-publication",
        workspace_id=workspace.id,
        slug="capability-publication",
        name="Capability publication",
        tier="client",
        skill_ids=[skill.id],
    )
    db_session.add_all([skill, capability])
    system.capability_id = capability.id
    system.skill_ids = []
    db_session.commit()

    contract = flow_publication.compile_execution_contract(
        db_session,
        {
            "schema_version": 3,
            "io_mode": "strict",
            "nodes": [
                {
                    "id": "task",
                    "kind": "task",
                    "data": {"bound_skill_slug": skill.slug},
                },
                {"id": "result", "kind": "sink"},
            ],
            "edges": [{"from": "task", "to": "result"}],
        },
        workspace,
        system=system,
    )

    assert contract["nodes"]["task"]["skill_id"] == skill.id


def test_owned_reconciler_publishes_atomically_without_direct_mirror_drift(
    db_session,
) -> None:
    workspace, user, system = _seed(db_session)
    initial_pointer = system.published_flow_version_id
    desired = _flow("seed-reconciled-v2")

    result = flow_publication.reconcile_system_flow(
        db_session,
        system=system,
        workspace=workspace,
        flow_definition=desired,
        actor=user.email,
        publish_if_owned=True,
        ownership_prefix=user.email,
        message="Owned seed reconciliation",
    )
    db_session.commit()
    db_session.refresh(system)
    draft = db_session.query(SystemFlowDraft).filter_by(system_id=system.id).one()
    published = db_session.get(SystemVersion, system.published_flow_version_id)

    assert result.status == "published"
    assert system.published_flow_version_id != initial_pointer
    assert system.flow_definition == desired
    assert published is not None
    assert published.flow_definition == desired
    assert draft.base_published_version_id == published.id
    assert draft.flow_sha256 == published.flow_sha256


def test_unowned_reconciler_stages_only_a_clean_server_draft(db_session) -> None:
    workspace, _, system = _seed(db_session)
    initial_pointer = system.published_flow_version_id
    published_flow = copy.deepcopy(system.flow_definition)
    desired = _flow("unowned-seed-proposal")

    result = flow_publication.reconcile_system_flow(
        db_session,
        system=system,
        workspace=workspace,
        flow_definition=desired,
        actor="system:foreign-seed",
        publish_if_owned=True,
        ownership_prefix="system:foreign-seed",
    )
    db_session.commit()
    db_session.refresh(system)
    draft = db_session.query(SystemFlowDraft).filter_by(system_id=system.id).one()

    assert result.status == "draft_updated"
    assert system.published_flow_version_id == initial_pointer
    assert system.flow_definition == published_flow
    assert draft.flow_definition == desired
    assert draft.base_published_version_id == initial_pointer


def test_owned_reconciler_preserves_an_operator_dirty_draft(db_session) -> None:
    workspace, user, system = _seed(db_session)
    initial_pointer = system.published_flow_version_id
    published_flow = copy.deepcopy(system.flow_definition)
    operator_flow = _flow("operator-draft")
    draft, _ = flow_publication.save_draft(
        db_session,
        system_id=system.id,
        workspace=workspace,
        flow_definition=operator_flow,
        expected_revision=1,
        actor="operator@example.invalid",
    )

    result = flow_publication.reconcile_system_flow(
        db_session,
        system=system,
        workspace=workspace,
        flow_definition=_flow("seed-wants-another-flow"),
        actor=user.email,
        publish_if_owned=True,
        ownership_prefix=user.email,
    )
    db_session.commit()
    db_session.refresh(system)
    db_session.refresh(draft)

    assert result.status == "operator_draft_preserved"
    assert system.published_flow_version_id == initial_pointer
    assert system.flow_definition == published_flow
    assert draft.flow_definition == operator_flow
    assert draft.updated_by == "operator@example.invalid"


def test_draft_save_is_revisioned_and_never_mutates_published_mirror(db_session) -> None:
    workspace, user, system = _seed(db_session)
    client = _client(db_session, workspace, user)
    original = copy.deepcopy(system.flow_definition)

    response = client.put(
        f"/systems/{system.id}/flow-draft",
        json={"expected_revision": 1, "flow_definition": _flow("draft-v2")},
    )

    assert response.status_code == 200
    assert response.json()["revision"] == 2
    db_session.refresh(system)
    assert system.flow_definition == original
    assert canonical_flow_sha256(system.flow_definition) != response.json()["flow_sha256"]

    stale = client.put(
        f"/systems/{system.id}/flow-draft",
        json={"expected_revision": 1, "flow_definition": _flow("lost-update")},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "FLOW_DRAFT_REVISION_MISMATCH"
    db_session.expire_all()
    draft = db_session.get(SystemFlowDraft, system.id)
    assert draft is not None and draft.flow_definition == _flow("draft-v2")


def test_draft_save_rejects_malformed_graph_shape_without_mutation(db_session) -> None:
    workspace, user, system = _seed(db_session)
    client = _client(db_session, workspace, user)
    pointer = system.published_flow_version_id
    before = db_session.get(SystemFlowDraft, system.id)
    assert before is not None
    before_flow = copy.deepcopy(before.flow_definition)
    before_hash = before.flow_sha256

    response = client.put(
        f"/systems/{system.id}/flow-draft",
        json={
            "expected_revision": before.revision,
            "flow_definition": {"nodes": [None], "edges": [None]},
        },
    )

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "FLOW_DRAFT_SHAPE_INVALID"
    assert [issue["code"] for issue in detail["issues"]] == [
        "node_invalid",
        "edge_invalid",
    ]
    db_session.expire_all()
    persisted = db_session.get(SystemFlowDraft, system.id)
    persisted_system = db_session.get(System, system.id)
    assert persisted is not None and persisted.revision == 1
    assert persisted.flow_sha256 == before_hash
    assert persisted.flow_definition == before_flow
    assert persisted_system is not None
    assert persisted_system.published_flow_version_id == pointer


def test_publish_rejects_preexisting_malformed_draft_without_pointer_drift(
    db_session,
) -> None:
    workspace, user, system = _seed(db_session)
    pointer = system.published_flow_version_id
    version_count = db_session.query(SystemVersion).filter_by(system_id=system.id).count()
    draft = db_session.get(SystemFlowDraft, system.id)
    assert draft is not None
    malformed = {"nodes": [None], "edges": [None]}
    draft.flow_definition = malformed
    draft.flow_sha256 = canonical_flow_sha256(malformed)
    draft.revision += 1
    db_session.commit()

    response = _client(db_session, workspace, user).post(
        f"/systems/{system.id}/flow/publish",
        json={
            "expected_draft_revision": draft.revision,
            "expected_published_version_id": pointer,
            "message": "Must fail closed before publication",
            "breaking_change_intent": "acknowledged",
        },
    )

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "FLOW_PUBLISH_VALIDATION_FAILED"
    assert [issue["code"] for issue in detail["issues"]] == [
        "node_invalid",
        "edge_invalid",
    ]
    db_session.expire_all()
    persisted_system = db_session.get(System, system.id)
    assert persisted_system is not None
    assert persisted_system.published_flow_version_id == pointer
    assert db_session.query(SystemVersion).filter_by(system_id=system.id).count() == version_count


def test_publish_rejects_non_object_persisted_draft_before_hashing(db_session) -> None:
    workspace, user, system = _seed(db_session)
    pointer = system.published_flow_version_id
    version_count = db_session.query(SystemVersion).filter_by(system_id=system.id).count()
    draft = db_session.get(SystemFlowDraft, system.id)
    assert draft is not None
    draft.flow_definition = []
    draft.flow_sha256 = "0" * 64
    draft.revision += 1
    db_session.commit()

    response = _client(db_session, workspace, user).post(
        f"/systems/{system.id}/flow/publish",
        json={
            "expected_draft_revision": draft.revision,
            "expected_published_version_id": pointer,
            "message": "Reject top-level corruption",
            "breaking_change_intent": "acknowledged",
        },
    )

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "FLOW_PUBLISH_VALIDATION_FAILED"
    assert [issue["code"] for issue in detail["issues"]] == ["flow_invalid"]
    db_session.expire_all()
    persisted_system = db_session.get(System, system.id)
    assert persisted_system is not None
    assert persisted_system.published_flow_version_id == pointer
    assert db_session.query(SystemVersion).filter_by(system_id=system.id).count() == version_count


def test_equivalent_draft_save_is_a_noop_without_revision_churn(db_session) -> None:
    workspace, user, system = _seed(db_session)
    client = _client(db_session, workspace, user)

    state = client.get(f"/systems/{system.id}/flow-state").json()
    response = client.put(
        f"/systems/{system.id}/flow-draft",
        json={
            "expected_revision": state["draft"]["revision"],
            "flow_definition": state["draft"]["flow_definition"],
        },
    )

    assert response.status_code == 200
    assert response.json()["no_op"] is True
    assert response.json()["revision"] == 1


@pytest.mark.asyncio
async def test_migration_baseline_requires_contract_only_publish_before_run(
    db_session,
) -> None:
    workspace, user, system = _seed(db_session)
    initial_pointer = system.published_flow_version_id
    version = db_session.get(SystemVersion, initial_pointer)
    assert version is not None
    version.execution_contract = None
    db_session.commit()
    before_runs = db_session.query(Run).count()

    with pytest.raises(HTTPException) as rejected:
        await systems.trigger_run(
            system.id,
            systems.RunCreate(
                input_ref={"case": "blocked"},
                expected_flow_sha256=canonical_flow_sha256(system.flow_definition),
            ),
            BackgroundTasks(),
            workspace,
            user,
            db_session,
        )

    assert rejected.value.status_code == 409
    assert rejected.value.detail["code"] == "PUBLISHED_EXECUTION_CONTRACT_MISSING"
    assert db_session.query(Run).count() == before_runs

    published = _client(db_session, workspace, user).post(
        f"/systems/{system.id}/flow/publish",
        json={
            "expected_draft_revision": 1,
            "expected_published_version_id": initial_pointer,
            "message": "Freeze the migration baseline contract",
            "breaking_change_intent": None,
        },
    )

    assert published.status_code == 200, published.text
    assert published.json()["no_op"] is False
    assert published.json()["published"]["version_id"] != initial_pointer
    assert published.json()["published"]["execution_contract"]["contract_sha256"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "invalid_value", "rehash"),
    [
        ("ingresses", "not-an-array", True),
        ("nodes", [], True),
        ("outputs", {}, True),
        ("contract_sha256", "0" * 64, False),
    ],
)
async def test_published_run_rejects_corrupted_frozen_contract_before_insert(
    db_session,
    field: str,
    invalid_value,
    rehash: bool,
) -> None:
    workspace, user, system = _seed(db_session)
    version = db_session.get(SystemVersion, system.published_flow_version_id)
    assert version is not None
    contract = copy.deepcopy(version.execution_contract)
    contract[field] = invalid_value
    if rehash:
        body = {key: value for key, value in contract.items() if key != "contract_sha256"}
        contract["contract_sha256"] = flow_contracts.canonical_sha256(body)
    version.execution_contract = contract
    db_session.commit()
    before_runs = db_session.query(Run).count()

    with pytest.raises(HTTPException) as rejected:
        await systems.trigger_run(
            system.id,
            systems.RunCreate(
                input_ref={"case": "blocked"},
                expected_flow_sha256=canonical_flow_sha256(system.flow_definition),
            ),
            BackgroundTasks(),
            workspace,
            user,
            db_session,
        )

    assert rejected.value.status_code == 409
    assert rejected.value.detail["code"] == "PUBLISHED_EXECUTION_CONTRACT_MISSING"
    assert db_session.query(Run).count() == before_runs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("corruption", "expected_code"),
    [
        ("shape", "PUBLISHED_FLOW_SHAPE_INVALID"),
        ("digest", "PUBLISHED_FLOW_VERSION_HASH_DRIFT"),
    ],
)
async def test_published_run_rejects_corrupted_immutable_flow_before_insert(
    db_session,
    corruption: str,
    expected_code: str,
) -> None:
    workspace, user, system = _seed(db_session)
    version = db_session.get(SystemVersion, system.published_flow_version_id)
    assert version is not None
    expected_flow_sha256 = version.flow_sha256
    assert expected_flow_sha256 is not None
    if corruption == "shape":
        system.flow_definition = []
        version.flow_definition = []
    else:
        changed = _flow("illegally-rewritten-version")
        system.flow_definition = copy.deepcopy(changed)
        version.flow_definition = copy.deepcopy(changed)
    db_session.commit()
    before_runs = db_session.query(Run).count()

    with pytest.raises(HTTPException) as rejected:
        await systems.trigger_run(
            system.id,
            systems.RunCreate(
                input_ref={"case": "blocked"},
                expected_flow_sha256=expected_flow_sha256,
            ),
            BackgroundTasks(),
            workspace,
            user,
            db_session,
        )

    assert rejected.value.status_code == 409
    assert rejected.value.detail["code"] == expected_code
    assert db_session.query(Run).count() == before_runs


def test_publish_rejects_whitespace_only_release_message(db_session) -> None:
    workspace, user, system = _seed(db_session)
    response = _client(db_session, workspace, user).post(
        f"/systems/{system.id}/flow/publish",
        json={
            "expected_draft_revision": 1,
            "expected_published_version_id": system.published_flow_version_id,
            "message": "   \n\t  ",
            "breaking_change_intent": None,
        },
    )

    assert response.status_code == 422


def test_same_graph_republishes_changed_skill_schema_as_breaking_contract(
    db_session,
) -> None:
    workspace, user, system = _seed(db_session, enabled=False)
    skill = Skill(
        id="mutable-contract-skill",
        workspace_id=workspace.id,
        slug="mutable-contract-skill",
        version="1",
        name="Mutable contract Skill",
        input_schema={"type": "object"},
        output_schema={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "additionalProperties": False,
        },
        execution={},
        executor={
            "kind": "registry_call",
            "params": {"skill_slug": "audit_log_v1"},
        },
    )
    flow = _flow("skill-contract-v1")
    flow["nodes"].insert(
        1,
        {
            "id": "mutable.task",
            "kind": "task",
            "config": {"skill_slug": skill.slug},
        },
    )
    flow["edges"] = [
        {"from": "manual", "to": "mutable.task", "kind": "data"},
        {"from": "mutable.task", "to": "result", "kind": "data"},
    ]
    db_session.add(skill)
    system.skill_ids = [skill.id]
    system.flow_definition = flow
    settings = dict(workspace.settings or {})
    features = dict(settings.get("features") or {})
    features["flow_publication_v1"] = True
    settings["features"] = features
    workspace.settings = settings
    db_session.commit()
    flow_publication.initialize_publication_state(
        db_session,
        system=system,
        workspace=workspace,
        actor=user.email,
    )
    db_session.commit()
    db_session.refresh(system)
    initial_version_id = system.published_flow_version_id
    initial_contract = db_session.get(SystemVersion, initial_version_id).execution_contract

    skill.output_schema = {
        "type": "object",
        "properties": {"approved": {"type": "boolean"}},
        "required": ["approved"],
        "additionalProperties": False,
    }
    db_session.commit()
    request = {
        "expected_draft_revision": 1,
        "expected_published_version_id": initial_version_id,
        "message": "Freeze the reviewed Skill schema",
        "breaking_change_intent": None,
    }
    client = _client(db_session, workspace, user)

    rejected = client.post(f"/systems/{system.id}/flow/publish", json=request)
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["detail"]["code"] == "FLOW_BREAKING_CHANGE_INTENT_REQUIRED"

    request["breaking_change_intent"] = "acknowledged"
    published = client.post(f"/systems/{system.id}/flow/publish", json=request)
    assert published.status_code == 200, published.text
    payload = published.json()
    assert payload["no_op"] is False
    assert payload["published"]["flow_sha256"] == canonical_flow_sha256(flow)
    assert payload["published"]["version_id"] != initial_version_id
    assert (
        payload["published"]["execution_contract"]["contract_sha256"]
        != initial_contract["contract_sha256"]
    )


def test_publish_is_atomic_append_only_and_does_not_activate(db_session) -> None:
    workspace, user, system = _seed(db_session, status="paused")
    client = _client(db_session, workspace, user)
    initial_pointer = system.published_flow_version_id
    initial_versions = db_session.query(SystemVersion).filter_by(system_id=system.id).count()

    saved = client.put(
        f"/systems/{system.id}/flow-draft",
        json={"expected_revision": 1, "flow_definition": _flow("published-v2")},
    ).json()
    response = client.post(
        f"/systems/{system.id}/flow/publish",
        json={
            "expected_draft_revision": saved["revision"],
            "expected_published_version_id": initial_pointer,
            "message": "Publish the reviewed draft",
            "breaking_change_intent": None,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["no_op"] is False
    assert payload["status"] == "paused"
    assert payload["published"]["version_id"] != initial_pointer
    assert payload["published"]["flow_sha256"] == saved["flow_sha256"]
    assert payload["published"]["execution_contract"]["contract_sha256"]
    db_session.refresh(system)
    assert system.status == "paused"
    assert system.flow_definition == _flow("published-v2")
    assert (
        db_session.query(SystemVersion).filter_by(system_id=system.id).count()
        == initial_versions + 1
    )


def test_publish_preconditions_allow_exactly_one_competing_request(db_session) -> None:
    workspace, user, system = _seed(db_session)
    client = _client(db_session, workspace, user)
    pointer = system.published_flow_version_id
    saved = client.put(
        f"/systems/{system.id}/flow-draft",
        json={"expected_revision": 1, "flow_definition": _flow("candidate")},
    ).json()
    request = {
        "expected_draft_revision": saved["revision"],
        "expected_published_version_id": pointer,
        "message": "Concurrent candidate",
        "breaking_change_intent": None,
    }

    winner = client.post(f"/systems/{system.id}/flow/publish", json=request)
    loser = client.post(f"/systems/{system.id}/flow/publish", json=request)

    assert winner.status_code == 200
    assert loser.status_code == 409
    assert loser.json()["detail"]["code"] == "PUBLISHED_FLOW_VERSION_MISMATCH"
    assert db_session.query(SystemVersion).filter_by(system_id=system.id).count() == 2


def test_active_system_publish_requires_explicit_breaking_change_intent(
    db_session,
) -> None:
    workspace, user, system = _seed(db_session, status="active")
    client = _client(db_session, workspace, user)
    pointer = system.published_flow_version_id
    candidate = _flow("strict-v2")
    candidate["io_mode"] = "strict"
    saved = client.put(
        f"/systems/{system.id}/flow-draft",
        json={"expected_revision": 1, "flow_definition": candidate},
    ).json()
    request = {
        "expected_draft_revision": saved["revision"],
        "expected_published_version_id": pointer,
        "message": "Intentional strict contract",
        "breaking_change_intent": None,
    }

    rejected = client.post(f"/systems/{system.id}/flow/publish", json=request)

    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["detail"]["code"] == "FLOW_BREAKING_CHANGE_INTENT_REQUIRED"
    assert rejected.json()["detail"]["required_intent"] == "acknowledged"
    assert "io_mode" in rejected.json()["detail"]["breaking_changes"]
    db_session.expire_all()
    system = db_session.get(System, system.id)
    assert system is not None and system.published_flow_version_id == pointer
    assert db_session.query(SystemVersion).filter_by(system_id=system.id).count() == 1

    request["breaking_change_intent"] = "acknowledged"
    published = client.post(f"/systems/{system.id}/flow/publish", json=request)

    assert published.status_code == 200, published.text
    assert published.json()["published"]["version_id"] != pointer
    assert published.json()["status"] == "active"


def test_active_system_output_contract_change_requires_breaking_intent(
    db_session,
) -> None:
    workspace, user, system = _seed(db_session, status="active")
    client = _client(db_session, workspace, user)
    pointer = system.published_flow_version_id
    candidate = _flow("output-contract-v2")
    candidate["output_contract"] = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    saved = client.put(
        f"/systems/{system.id}/flow-draft",
        json={"expected_revision": 1, "flow_definition": candidate},
    ).json()
    request = {
        "expected_draft_revision": saved["revision"],
        "expected_published_version_id": pointer,
        "message": "Change the public output contract",
        "breaking_change_intent": None,
    }

    rejected = client.post(f"/systems/{system.id}/flow/publish", json=request)

    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["detail"]["code"] == "FLOW_BREAKING_CHANGE_INTENT_REQUIRED"
    assert "output_contract" in rejected.json()["detail"]["breaking_changes"]

    request["breaking_change_intent"] = "acknowledged"
    published = client.post(f"/systems/{system.id}/flow/publish", json=request)
    assert published.status_code == 200, published.text
    assert published.json()["published"]["version_id"] != pointer


def test_variant_and_executable_reordering_require_breaking_intent(db_session) -> None:
    workspace, user, system = _seed(db_session, status="active")
    client = _client(db_session, workspace, user)
    pointer = system.published_flow_version_id
    candidate = _flow("runtime-change")
    candidate["variant"] = "chat_agentic_thinking_v1"
    candidate["nodes"] = list(reversed(candidate["nodes"]))
    saved = client.put(
        f"/systems/{system.id}/flow-draft",
        json={"expected_revision": 1, "flow_definition": candidate},
    ).json()

    rejected = client.post(
        f"/systems/{system.id}/flow/publish",
        json={
            "expected_draft_revision": saved["revision"],
            "expected_published_version_id": pointer,
            "message": "Change runtime identity and order",
            "breaking_change_intent": None,
        },
    )

    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "FLOW_BREAKING_CHANGE_INTENT_REQUIRED"
    assert {"variant", "nodes/order"} <= set(rejected.json()["detail"]["breaking_changes"])


def test_restore_changes_only_draft_and_draft_test_run_freezes_snapshot(
    db_session,
    monkeypatch,
) -> None:
    workspace, user, system = _seed(db_session)
    client = _client(db_session, workspace, user)
    initial_pointer = system.published_flow_version_id
    saved = client.put(
        f"/systems/{system.id}/flow-draft",
        json={"expected_revision": 1, "flow_definition": _flow("candidate")},
    ).json()

    monkeypatch.setattr(endpoint, "schedule_run", lambda _run_id: None)
    test_run = client.post(
        f"/systems/{system.id}/flow-draft/test-runs",
        json={
            "expected_draft_revision": saved["revision"],
            "expected_flow_sha256": saved["flow_sha256"],
            "input_ref": {"case": "A"},
        },
    )
    assert test_run.status_code == 201, test_run.text
    run = db_session.get(Run, test_run.json()["id"])
    assert run is not None
    assert run.execution_surface == "draft_test"
    assert run.published_flow_version_id is None
    assert run.flow_snapshot == _flow("candidate")
    assert run.flow_sha256 == saved["flow_sha256"]

    restored = client.post(
        f"/systems/{system.id}/flow-draft/restore/{initial_pointer}",
        json={"expected_revision": saved["revision"]},
    )
    assert restored.status_code == 200
    assert restored.json()["flow_definition"] == _flow("published-v1")
    db_session.refresh(system)
    assert system.published_flow_version_id == initial_pointer
    assert system.flow_definition == _flow("published-v1")


def test_draft_test_run_requires_and_freezes_explicit_multi_ingress_selection(
    db_session,
    monkeypatch,
) -> None:
    workspace, user, system = _seed(db_session)
    client = _client(db_session, workspace, user)
    saved = client.put(
        f"/systems/{system.id}/flow-draft",
        json={
            "expected_revision": 1,
            "flow_definition": _multi_ingress_flow("candidate"),
        },
    ).json()
    monkeypatch.setattr(endpoint, "schedule_run", lambda _run_id: None)
    request = {
        "expected_draft_revision": saved["revision"],
        "expected_flow_sha256": saved["flow_sha256"],
        "input_ref": {"case": "A"},
    }

    ambiguous = client.post(
        f"/systems/{system.id}/flow-draft/test-runs",
        json=request,
    )
    assert ambiguous.status_code == 422
    assert ambiguous.json()["detail"]["code"] == "FLOW_DRAFT_TEST_INGRESS_AMBIGUOUS"

    selected = client.post(
        f"/systems/{system.id}/flow-draft/test-runs",
        json={**request, "ingress_id": "webhook", "kind": "http"},
    )
    assert selected.status_code == 201, selected.text
    run = db_session.get(Run, selected.json()["id"])
    assert run is not None
    assert run.execution_surface == "draft_test"
    assert run.input_ref["_ingress"] == {
        "ingress_id": "webhook",
        "source_node_id": "webhook",
        "kind": "http",
        "adapter": {"surface": "draft_test"},
    }
    assert run.input_ref["execution"]["ingress_id"] == "webhook"


def test_activation_checks_the_reviewed_published_version_without_mutating_a_newer_one(db_session):
    from app.models.audit import AuditLog

    workspace, user, system = _seed(db_session, status="draft")
    reviewed = system.published_flow_version_id
    client = _client(db_session, workspace, user)
    saved = client.put(f"/systems/{system.id}/flow-draft", json={
        "expected_revision": 1, "flow_definition": _flow("published-v2"),
    }).json()
    published = client.post(f"/systems/{system.id}/flow/publish", json={
        "expected_draft_revision": saved["revision"],
        "expected_published_version_id": reviewed,
        "message": "New publication before activation", "breaking_change_intent": "acknowledged",
    })
    assert published.status_code == 200, published.text
    db_session.refresh(system)
    current = system.published_flow_version_id
    assert current != reviewed and system.status == "draft"
    audits = db_session.query(AuditLog).count()
    versions = db_session.query(SystemVersion).count()
    api = _systems_client(db_session, workspace, user)
    rejected = api.patch(f"/systems/{system.id}", params={"expected_published_version_id": reviewed},
                         json={"status": "active"})
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["detail"]["code"] == "SYSTEM_PUBLISHED_VERSION_MISMATCH"
    db_session.refresh(system)
    assert system.status == "draft" and system.published_flow_version_id == current
    assert db_session.query(AuditLog).count() == audits
    assert db_session.query(SystemVersion).count() == versions
    for _ in range(2):
        accepted = api.patch(f"/systems/{system.id}", params={"expected_published_version_id": current},
                             json={"status": "active"})
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["status"] == "active"
        assert accepted.json()["published_flow_version_id"] == current
    assert db_session.query(SystemVersion).count() == versions
    assert db_session.query(AuditLog).count() == audits + 1


def test_feature_off_hides_publication_endpoints(db_session) -> None:
    workspace, user, system = _seed(db_session, enabled=False)
    client = _client(db_session, workspace, user)

    response = client.get(f"/systems/{system.id}/flow-state")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "FLOW_PUBLICATION_DISABLED"


@pytest.mark.asyncio
async def test_feature_on_rejects_direct_legacy_flow_patch(db_session) -> None:
    workspace, user, system = _seed(db_session)
    published = copy.deepcopy(system.flow_definition)

    with pytest.raises(HTTPException) as rejected:
        await systems.update_system(
            system.id,
            systems.SystemUpdate(flow_definition=_flow("bypass")),
            systems.SystemUpdateOptions(),
            workspace,
            user,
            db_session,
        )

    assert rejected.value.status_code == 409
    assert rejected.value.detail["code"] == "FLOW_DRAFT_ENDPOINT_REQUIRED"
    db_session.rollback()
    db_session.refresh(system)
    assert system.flow_definition == published


@pytest.mark.asyncio
async def test_normal_run_freezes_published_pointer_contract_and_flow_at_insert(
    db_session,
) -> None:
    workspace, user, system = _seed(db_session)
    version_id = system.published_flow_version_id
    digest = canonical_flow_sha256(system.flow_definition)

    result = await systems.trigger_run(
        system.id,
        systems.RunCreate(input_ref={"case": "published"}, expected_flow_sha256=digest),
        BackgroundTasks(),
        workspace,
        user,
        db_session,
    )

    run = db_session.get(Run, result["id"])
    assert run is not None
    assert run.flow_snapshot == _flow("published-v1")
    assert run.flow_sha256 == digest
    assert run.published_flow_version_id == version_id
    assert run.flow_version_id == version_id
    assert run.execution_surface == "published_manual"
    assert run.execution_contract["contract_sha256"]

    system.flow_definition = _flow("illegal-later-mutation")
    db_session.commit()
    db_session.refresh(run)
    assert run.flow_snapshot == _flow("published-v1")
    assert run.flow_sha256 == digest


@pytest.mark.asyncio
async def test_rerun_preserves_all_immutable_published_execution_evidence(
    db_session,
) -> None:
    workspace, user, system = _seed(db_session)
    digest = canonical_flow_sha256(system.flow_definition)
    created = await systems.trigger_run(
        system.id,
        systems.RunCreate(
            input_ref={"case": "published"},
            expected_flow_sha256=digest,
        ),
        BackgroundTasks(),
        workspace,
        user,
        db_session,
    )
    parent = db_session.get(Run, created["id"])

    result = await runs_endpoint.rerun_run(
        parent.id,
        BackgroundTasks(),
        workspace,
        user,
        db_session,
    )

    rerun = db_session.get(Run, result["id"])
    assert rerun.parent_run_id == parent.id
    assert rerun.flow_snapshot == parent.flow_snapshot
    assert rerun.flow_version_id == parent.flow_version_id
    assert rerun.published_flow_version_id == parent.published_flow_version_id
    assert rerun.flow_sha256 == parent.flow_sha256
    assert rerun.execution_contract == parent.execution_contract
    assert rerun.execution_surface == parent.execution_surface
    assert rerun.input_ref == parent.input_ref
    assert rerun.input_ref is not parent.input_ref


@pytest.mark.asyncio
async def test_normalized_manual_ingress_rejects_invalid_input_before_run_insert(
    db_session,
) -> None:
    workspace, user, system = _seed(db_session)
    before = db_session.query(Run).count()

    with pytest.raises(HTTPException) as rejected:
        await systems.trigger_run(
            system.id,
            systems.RunCreate(
                input_ref={"case": 42},
                expected_flow_sha256=canonical_flow_sha256(system.flow_definition),
            ),
            BackgroundTasks(),
            workspace,
            user,
            db_session,
        )

    assert rejected.value.status_code == 422
    assert rejected.value.detail["code"] == "INGRESS_PAYLOAD_INVALID"
    assert db_session.query(Run).count() == before


@pytest.mark.asyncio
async def test_new_system_is_initialized_with_draft_and_published_pointer(
    db_session,
) -> None:
    workspace = Workspace(
        id="ws-publication-create",
        slug="flow-publication-create",
        name="Flow publication create",
        settings={"features": {"flow_publication_v1": True}},
    )
    user = User(
        id="user-publication-create",
        username="publisher-create@example.invalid",
        email="publisher-create@example.invalid",
        role="admin",
    )
    db_session.add_all([workspace, user])
    db_session.commit()

    payload = await systems.create_system(
        systems.SystemCreate(
            name="New publication System",
            flow_definition=_flow("initial"),
        ),
        workspace,
        user,
        db_session,
        systems.SystemCreateOptions(),
    )

    system = db_session.get(System, payload["id"])
    assert system is not None and system.published_flow_version_id
    draft = db_session.get(SystemFlowDraft, system.id)
    assert draft is not None
    assert draft.flow_definition == system.flow_definition == _flow("initial")
    assert draft.base_published_version_id == system.published_flow_version_id
