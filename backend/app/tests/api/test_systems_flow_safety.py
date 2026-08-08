"""Fail-closed write contract for active System flows.

These tests exercise the HTTP boundary because ``SystemUpdate`` must preserve
the important distinction between an omitted PATCH field and an explicit JSON
``null``.  They also prove that rejected writes are atomic: no System change,
version, or mutation audit may survive a failed precondition/intent gate.

The subject is the legacy mirror write path, so the fixture workspace opts out
of ``flow_publication_v1``: with it on, the PATCH is refused before these gates
are ever reached and the draft endpoint owns the equivalent contract.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import systems
from app.models.audit import AuditLog
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.workspace import Workspace
from app.services.chains import version_service
from app.tests.publication_baseline import LEGACY_FLOW_AUTHORITY


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(systems.router, prefix="/systems")
    app.dependency_overrides[systems.get_current_workspace] = lambda: workspace
    app.dependency_overrides[systems.get_current_user] = lambda: user
    app.dependency_overrides[systems.get_db] = lambda: db_session
    return TestClient(app)


def _dag(prefix: str = "current", *, label: str = "Decision") -> dict[str, Any]:
    return {
        "schema_version": 3,
        "source": "flow",
        "variable_namespaces": ["case"],
        "nodes": [
            {
                "id": f"{prefix}.source",
                "kind": "source",
                "type": "input",
                "label": "Input",
            },
            {
                "id": f"{prefix}.decision",
                "kind": "decision",
                "label": label,
                "config": {
                    "branches": [
                        {"label": "yes", "condition": "True"},
                        {"label": "no", "condition": "False"},
                    ]
                },
            },
            {
                "id": f"{prefix}.sink",
                "kind": "sink",
                "type": "output",
                "label": "Output",
            },
        ],
        "edges": [
            {"from": f"{prefix}.source", "to": f"{prefix}.decision", "kind": "data"},
            {
                "from": f"{prefix}.decision",
                "to": f"{prefix}.sink",
                "kind": "branch",
                "branch_label": "yes",
            },
            {
                "from": f"{prefix}.decision",
                "to": f"{prefix}.sink",
                "kind": "branch",
                "branch_label": "no",
            },
        ],
    }


def _legacy_replacement() -> dict[str, Any]:
    """Structurally valid graph with overlap, but no DAG control primitive."""

    return {
        "schema_version": 3,
        "source": "flow",
        "nodes": [
            {"id": "current.source", "kind": "source", "type": "input"},
            {"id": "current.task", "kind": "task", "label": "Starter task"},
            {"id": "current.sink", "kind": "sink", "type": "output"},
        ],
        "edges": [
            {"from": "current.source", "to": "current.task", "kind": "data"},
            {"from": "current.task", "to": "current.sink", "kind": "data"},
        ],
    }


def _empty_flow() -> dict[str, Any]:
    return {
        "schema_version": 3,
        "source": "flow",
        "nodes": [],
        "edges": [],
    }


def _seed(
    db_session,
    *,
    status: str = "active",
    flow: dict[str, Any] | None = None,
) -> tuple[Workspace, User, System]:
    workspace = Workspace(
        id="ws-flow-safety",
        name="Flow safety",
        slug="flow-safety",
        settings={
            "features": {
                **LEGACY_FLOW_AUTHORITY["features"],
                "flow_v3_dag_authoritative": False,
            }
        },
    )
    user = User(
        id="user-flow-safety",
        username="flow-safety@example.invalid",
        email="flow-safety@example.invalid",
        role="admin",
    )
    system = System(
        id="system-flow-safety",
        workspace_id=workspace.id,
        name="Protected flow",
        objective="test",
        status=status,
        settings={},
        skill_ids=[],
        flow_definition=copy.deepcopy(flow if flow is not None else _dag()),
    )
    db_session.add_all([workspace, user, system])
    db_session.commit()
    return workspace, user, system


def _flow_hash(client: TestClient) -> str:
    response = client.get("/systems/system-flow-safety")
    assert response.status_code == 200
    digest = response.json()["flow_sha256"]
    assert len(digest) == 64
    return digest


def _assert_rejected_write_is_atomic(
    db_session,
    system: System,
    original_flow: dict[str, Any],
) -> None:
    # The production request-scoped session is closed (and therefore rolled
    # back) after an HTTP error. Tests override it with a shared Session, so
    # release the row-lock transaction explicitly before asserting persistence.
    db_session.rollback()
    db_session.refresh(system)
    assert system.flow_definition == original_flow
    assert db_session.query(SystemVersion).filter_by(system_id=system.id).count() == 0
    assert (
        db_session.query(AuditLog)
        .filter_by(agent_id=system.id, event_type="system.updated")
        .count()
        == 0
    )


def test_explicit_null_flow_is_rejected_by_request_schema(db_session) -> None:
    workspace, user, system = _seed(db_session)
    client = _client(db_session, workspace, user)
    original = copy.deepcopy(system.flow_definition)

    response = client.patch(
        "/systems/system-flow-safety",
        json={"flow_definition": None},
    )

    assert response.status_code == 422
    _assert_rejected_write_is_atomic(db_session, system, original)


def test_non_object_persisted_flow_fails_read_instead_of_hashing_as_empty(
    db_session,
) -> None:
    workspace, user, system = _seed(db_session)
    system.flow_definition = []  # type: ignore[assignment]
    db_session.commit()
    client = _client(db_session, workspace, user)

    response = client.get("/systems/system-flow-safety")

    assert response.status_code == 500
    assert response.json()["detail"]["error"] == "persisted_flow_invalid"


def test_patch_openapi_contract_does_not_advertise_nullable_flow() -> None:
    schema = systems.SystemUpdate.model_json_schema()
    flow_schema = schema["properties"]["flow_definition"]
    assert flow_schema.get("type") == "object"
    assert not any(
        branch.get("type") == "null" for branch in flow_schema.get("anyOf", [])
    )


@pytest.mark.parametrize(
    ("query", "expected_error"),
    [
        ("", "flow_precondition_missing"),
        (f"?expected_flow_sha256={'0' * 64}", "flow_precondition_stale"),
    ],
)
def test_active_flow_write_requires_current_hash_atomically(
    db_session,
    query: str,
    expected_error: str,
) -> None:
    workspace, user, system = _seed(db_session)
    client = _client(db_session, workspace, user)
    original = copy.deepcopy(system.flow_definition)
    edited = _dag(label="Edited safely")

    response = client.patch(
        f"/systems/system-flow-safety{query}",
        json={"flow_definition": edited},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == expected_error
    _assert_rejected_write_is_atomic(db_session, system, original)


def test_prospectively_active_flow_write_also_requires_hash(db_session) -> None:
    workspace, user, system = _seed(db_session, status="draft")
    client = _client(db_session, workspace, user)
    original = copy.deepcopy(system.flow_definition)

    response = client.patch(
        "/systems/system-flow-safety",
        json={"status": "active", "flow_definition": _dag(label="Activate")},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "flow_precondition_missing"
    _assert_rejected_write_is_atomic(db_session, system, original)


def test_status_only_activation_of_empty_flow_requires_hash_and_intent(
    db_session,
) -> None:
    workspace, user, system = _seed(
        db_session,
        status="draft",
        flow=_empty_flow(),
    )
    client = _client(db_session, workspace, user)
    digest = _flow_hash(client)

    missing = client.patch(
        "/systems/system-flow-safety",
        json={"status": "active"},
    )
    assert missing.status_code == 409
    assert missing.json()["detail"]["error"] == "flow_precondition_missing"
    db_session.rollback()

    no_intent = client.patch(
        f"/systems/system-flow-safety?expected_flow_sha256={digest}",
        json={"status": "active"},
    )
    assert no_intent.status_code == 409
    assert no_intent.json()["detail"]["error"] == "active_flow_replace_intent_required"
    db_session.rollback()

    accepted = client.patch(
        (
            "/systems/system-flow-safety"
            f"?expected_flow_sha256={digest}"
            "&flow_write_intent=replace_active_flow"
        ),
        json={"status": "active"},
    )
    assert accepted.status_code == 200
    db_session.refresh(system)
    assert system.status == "active"
    assert system.flow_definition == _empty_flow()


def test_create_active_empty_flow_requires_explicit_intent(db_session) -> None:
    workspace = Workspace(
        id="ws-flow-safety",
        name="Flow safety",
        slug="flow-safety",
        settings=dict(LEGACY_FLOW_AUTHORITY),
    )
    user = User(
        id="user-flow-safety",
        username="flow-safety@example.invalid",
        email="flow-safety@example.invalid",
        role="admin",
    )
    db_session.add_all([workspace, user])
    db_session.commit()
    client = _client(db_session, workspace, user)
    body = {
        "name": "Explicit empty active",
        "objective": "test",
        "status": "active",
        "flow_definition": _empty_flow(),
    }

    rejected = client.post("/systems", json=body)
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["error"] == "active_flow_replace_intent_required"
    assert db_session.query(System).count() == 0

    accepted = client.post(
        "/systems?flow_write_intent=replace_active_flow",
        json=body,
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "active"
    assert accepted.json()["flow_definition"] == _empty_flow()


@pytest.mark.parametrize(
    ("replacement_kind", "expected_reason", "extra_query"),
    [
        ("empty", "active_flow_empty", "&skip_validation=true"),
        ("legacy", "active_dag_runtime_downgrade", ""),
        ("disjoint", "active_flow_node_identity_replacement", ""),
    ],
)
def test_destructive_active_replacement_requires_exact_intent_atomically(
    db_session,
    replacement_kind: str,
    expected_reason: str,
    extra_query: str,
) -> None:
    workspace, user, system = _seed(db_session)
    client = _client(db_session, workspace, user)
    original = copy.deepcopy(system.flow_definition)
    digest = _flow_hash(client)
    replacements = {
        "empty": _empty_flow(),
        "legacy": _legacy_replacement(),
        "disjoint": _dag("replacement"),
    }

    response = client.patch(
        (
            "/systems/system-flow-safety"
            f"?expected_flow_sha256={digest}{extra_query}"
        ),
        json={"flow_definition": replacements[replacement_kind]},
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "active_flow_replace_intent_required"
    assert detail["required_intent"] == "replace_active_flow"
    assert expected_reason in detail["reasons"]
    assert "flow_definition" not in detail
    _assert_rejected_write_is_atomic(db_session, system, original)


def test_explicit_intent_persists_empty_flow_version_and_payload_free_audit(
    db_session,
) -> None:
    workspace, user, system = _seed(db_session)
    client = _client(db_session, workspace, user)
    before_hash = _flow_hash(client)
    replacement = _empty_flow()

    response = client.patch(
        (
            "/systems/system-flow-safety"
            f"?expected_flow_sha256={before_hash}"
            "&flow_write_intent=replace_active_flow"
            "&skip_validation=true"
        ),
        json={"flow_definition": replacement},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["flow_definition"] == replacement
    assert payload["flow_sha256"] == systems._flow_sha256(replacement)
    assert payload["new_version"]["version_number"] == 1

    db_session.refresh(system)
    assert system.flow_definition == replacement
    versions = db_session.query(SystemVersion).filter_by(system_id=system.id).all()
    assert len(versions) == 1
    assert versions[0].flow_definition == replacement

    event = (
        db_session.query(AuditLog)
        .filter_by(agent_id=system.id, event_type="system.updated")
        .one()
    )
    flow_write = event.details["flow_write"]
    assert flow_write == {
        "before_sha256": before_hash,
        "after_sha256": systems._flow_sha256(replacement),
        "before_node_count": 3,
        "after_node_count": 0,
        "before_edge_count": 3,
        "after_edge_count": 0,
        "intent": "replace_active_flow",
        "reasons": ["active_flow_empty", "active_dag_runtime_downgrade"],
        "active_boundary": True,
    }
    assert "flow_definition" not in event.details


def test_active_rollback_reuses_hash_and_explicit_replacement_gate(db_session) -> None:
    workspace, user, system = _seed(db_session)
    version_service.record_new_version(
        db=db_session,
        system=system,
        flow_definition=_empty_flow(),
        created_by="flow-safety@example.invalid",
        message="empty target",
    )
    db_session.commit()
    client = _client(db_session, workspace, user)
    digest = _flow_hash(client)

    missing = client.post(
        "/systems/system-flow-safety/versions/1/rollback",
        json={"message": "rollback empty"},
    )
    assert missing.status_code == 409
    assert missing.json()["detail"]["error"] == "flow_precondition_missing"
    db_session.rollback()

    no_intent = client.post(
        (
            "/systems/system-flow-safety/versions/1/rollback"
            f"?expected_flow_sha256={digest}"
        ),
        json={"message": "rollback empty"},
    )
    assert no_intent.status_code == 409
    assert no_intent.json()["detail"]["error"] == "active_flow_replace_intent_required"
    db_session.rollback()

    accepted = client.post(
        (
            "/systems/system-flow-safety/versions/1/rollback"
            f"?expected_flow_sha256={digest}"
            "&flow_write_intent=replace_active_flow"
        ),
        json={"message": "rollback empty"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["system"]["flow_definition"] == _empty_flow()
    assert accepted.json()["system"]["flow_sha256"] == systems._flow_sha256(
        _empty_flow()
    )
    db_session.refresh(system)
    assert system.flow_definition == _empty_flow()
    event = db_session.query(AuditLog).filter_by(event_type="chain.rollback").one()
    assert event.details["flow_write"]["intent"] == "replace_active_flow"
    assert "active_flow_empty" in event.details["flow_write"]["reasons"]


def test_non_destructive_active_dag_edit_needs_hash_but_not_replace_intent(
    db_session,
) -> None:
    workspace, user, system = _seed(db_session)
    client = _client(db_session, workspace, user)
    digest = _flow_hash(client)
    edited = _dag(label="Same graph, edited label")

    response = client.patch(
        f"/systems/system-flow-safety?expected_flow_sha256={digest}",
        json={"flow_definition": edited},
    )

    assert response.status_code == 200
    db_session.refresh(system)
    assert system.flow_definition == edited
    event = db_session.query(AuditLog).filter_by(
        agent_id=system.id,
        event_type="system.updated",
    ).one()
    assert event.details["flow_write"]["intent"] is None
    assert event.details["flow_write"]["reasons"] == []


def test_draft_flow_can_be_saved_empty_without_active_preconditions(db_session) -> None:
    workspace, user, system = _seed(db_session, status="draft")
    client = _client(db_session, workspace, user)
    replacement = _empty_flow()

    response = client.patch(
        "/systems/system-flow-safety",
        json={"flow_definition": replacement},
    )

    assert response.status_code == 200
    db_session.refresh(system)
    assert system.status == "draft"
    assert system.flow_definition == replacement
    assert db_session.query(SystemVersion).filter_by(system_id=system.id).count() == 1


def test_non_flow_update_of_active_legacy_empty_system_remains_compatible(
    db_session,
) -> None:
    legacy = {"variant": "chat_agentic_thinking_v1", "nodes": [], "edges": []}
    workspace, user, system = _seed(db_session, flow=legacy)
    client = _client(db_session, workspace, user)

    response = client.patch(
        "/systems/system-flow-safety",
        json={"objective": "metadata-only edit"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["flow_definition"] == legacy
    assert payload["flow_sha256"] == systems._flow_sha256(legacy)
    db_session.refresh(system)
    assert system.objective == "metadata-only edit"
    assert system.flow_definition == legacy
    assert db_session.query(SystemVersion).filter_by(system_id=system.id).count() == 0


def test_flow_hash_is_structural_for_object_keys_and_ordered_for_arrays() -> None:
    left = {
        "schema_version": 3,
        "nodes": [{"id": "a"}, {"id": "b"}],
        "edges": [],
    }
    reordered_keys = {
        "edges": [],
        "nodes": [{"id": "a"}, {"id": "b"}],
        "schema_version": 3,
    }
    reordered_nodes = {
        "schema_version": 3,
        "nodes": [{"id": "b"}, {"id": "a"}],
        "edges": [],
    }

    assert systems._flow_sha256(left) == systems._flow_sha256(reordered_keys)
    assert systems._flow_sha256(left) != systems._flow_sha256(reordered_nodes)
