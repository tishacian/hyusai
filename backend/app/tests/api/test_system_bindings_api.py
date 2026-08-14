"""SystemBinding CRUD, resolve, invoke, and IAM — gated by experience_v1."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import system_bindings as endpoint
from app.models.audit import AuditLog
from app.models.run import Run
from app.models.system import System
from app.models.system_binding import SystemBinding
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.iam.manifest import CONTRIBUTOR_OR_ADMIN, ALL_CAPTURE_ROLES, get_manifest
from app.services.run_engine.execution_contract import canonical_flow_sha256
from app.services.systems import flow_publication


def _flow(*, extra_required: str | None = None) -> dict[str, Any]:
    required = ["query"]
    properties = {"query": {"type": "string"}}
    if extra_required:
        required.append(extra_required)
        properties[extra_required] = {"type": "string"}
    schema = {
        "type": "object",
        "required": required,
        "properties": properties,
        "additionalProperties": False,
    }
    return {
        "schema_version": 3,
        "io_mode": "strict",
        "nodes": [
            {
                "id": "manual.input",
                "kind": "source",
                "config": {"ingress_kind": "manual", "input_schema": schema},
            },
            {"id": "result", "kind": "sink"},
        ],
        "edges": [{"from": "manual.input", "to": "result", "kind": "data"}],
    }


def _seed(db_session, *, enabled: bool = True, role_template: str = "workspace_admin"):
    workspace = Workspace(
        id="ws-binding-api",
        slug="binding-api",
        name="Binding API",
        settings={
            "features": {
                "experience_v1": enabled,
                "flow_publication_v1": True,
            }
        },
    )
    user = User(
        id="user-binding-admin",
        username="binding-admin@example.invalid",
        email="binding-admin@example.invalid",
        role="admin" if role_template == "workspace_admin" else "member",
    )
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="admin" if role_template == "workspace_admin" else "member",
        role_template=role_template,
    )
    flow = _flow()
    system = System(
        id="system-binding-api",
        workspace_id=workspace.id,
        name="Bound system",
        objective="test",
        status="active",
        flow_definition=flow,
    )
    db_session.add_all([workspace, user, member, system])
    db_session.flush()
    contract = flow_publication.compile_execution_contract(db_session, flow, workspace)
    version = SystemVersion(
        id="version-binding-api",
        workspace_id=workspace.id,
        system_id=system.id,
        version_number=1,
        flow_definition=flow,
        flow_sha256=canonical_flow_sha256(flow),
        release_kind="publish",
        draft_revision=1,
        execution_contract=contract,
        message="published",
        created_by=user.email,
    )
    db_session.add(version)
    db_session.flush()
    system.published_flow_version_id = version.id
    system.published_by = user.email
    system.published_at = datetime.utcnow()
    db_session.commit()
    return workspace, user, system, version


def _client(db_session, workspace: Workspace, user: User, monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/system-bindings")
    app.dependency_overrides[endpoint.get_current_workspace] = lambda: workspace
    app.dependency_overrides[endpoint.get_current_user] = lambda: user
    app.dependency_overrides[endpoint.get_db] = lambda: db_session
    monkeypatch.setattr(endpoint, "schedule_run", lambda _run_id: None)
    return TestClient(app)


def _create_body(version: SystemVersion, *, key: str = "expenses.submit") -> dict[str, Any]:
    return {
        "binding_key": key,
        "system_id": version.system_id,
        "published_flow_version_id": version.id,
        "ingress_id": "manual.input",
        "confirmation_policy": "direct-safe",
        "on_unavailable": "unavailable",
    }


def test_binding_actions_are_declared_on_the_object_actions_manifest() -> None:
    rules = {
        (rule.resource_kind, rule.action): rule
        for rule in get_manifest("agentium_object_actions", strict=True).permissions
    }
    assert rules[("binding", "view")].roles == ALL_CAPTURE_ROLES
    assert rules[("binding", "manage")].roles == CONTRIBUTOR_OR_ADMIN


def test_bindings_are_feature_gated(db_session, monkeypatch) -> None:
    workspace, user, _system, version = _seed(db_session, enabled=False)
    client = _client(db_session, workspace, user, monkeypatch)

    listed = client.get("/system-bindings")
    created = client.post("/system-bindings", json=_create_body(version))

    assert listed.status_code == 404
    assert listed.json()["detail"]["code"] == "EXPERIENCE_V1_DISABLED"
    assert created.status_code == 404
    assert db_session.query(SystemBinding).count() == 0


def test_create_and_list_bindings(db_session, monkeypatch) -> None:
    workspace, user, system, version = _seed(db_session)
    client = _client(db_session, workspace, user, monkeypatch)

    created = client.post("/system-bindings", json=_create_body(version))
    listed = client.get("/system-bindings")
    fetched = client.get("/system-bindings/expenses.submit")

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["binding_key"] == "expenses.submit"
    assert body["system_id"] == system.id
    assert body["ingress_id"] == "manual.input"
    assert body["flow_sha256"] == version.flow_sha256
    assert listed.status_code == 200
    assert [item["binding_key"] for item in listed.json()["bindings"]] == ["expenses.submit"]
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]


def test_binding_key_is_unique_per_workspace(db_session, monkeypatch) -> None:
    workspace, user, _system, version = _seed(db_session)
    client = _client(db_session, workspace, user, monkeypatch)

    first = client.post("/system-bindings", json=_create_body(version))
    second = client.post("/system-bindings", json=_create_body(version))

    assert first.status_code == 201, first.text
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "BINDING_KEY_EXISTS"
    assert db_session.query(SystemBinding).count() == 1


def test_resolve_ok_unavailable_and_drift(db_session, monkeypatch) -> None:
    workspace, user, system, version = _seed(db_session)
    client = _client(db_session, workspace, user, monkeypatch)
    assert client.post("/system-bindings", json=_create_body(version)).status_code == 201

    ok = client.get("/system-bindings/expenses.submit/resolve")
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "ok"
    assert ok.json()["reasons"] == []

    system.published_flow_version_id = None
    db_session.commit()
    unavailable = client.get("/system-bindings/expenses.submit/resolve")
    assert unavailable.status_code == 200
    assert unavailable.json()["status"] == "unavailable"
    assert "published_evidence_unavailable" in unavailable.json()["reasons"]

    system.published_flow_version_id = version.id
    db_session.commit()
    drifted_flow = _flow(extra_required="ticket")
    drifted_contract = flow_publication.compile_execution_contract(
        db_session, drifted_flow, workspace
    )
    drifted = SystemVersion(
        id="version-binding-drift",
        workspace_id=workspace.id,
        system_id=system.id,
        version_number=2,
        flow_definition=drifted_flow,
        flow_sha256=canonical_flow_sha256(drifted_flow),
        release_kind="publish",
        draft_revision=2,
        execution_contract=drifted_contract,
        message="breaking republish",
        created_by=user.email,
    )
    db_session.add(drifted)
    db_session.flush()
    system.flow_definition = drifted_flow
    system.published_flow_version_id = drifted.id
    db_session.commit()

    drift = client.get("/system-bindings/expenses.submit/resolve")
    assert drift.status_code == 200, drift.text
    assert drift.json()["status"] == "drift"
    assert "flow_sha256_mismatch" in drift.json()["reasons"]
    assert "input_schema_sha256_mismatch" in drift.json()["reasons"]


def test_drift_list_and_retarget_snapshots_current_publish(db_session, monkeypatch) -> None:
    workspace, user, system, version = _seed(db_session)
    client = _client(db_session, workspace, user, monkeypatch)
    assert client.post("/system-bindings", json=_create_body(version)).status_code == 201

    drifted_flow = _flow(extra_required="ticket")
    drifted_contract = flow_publication.compile_execution_contract(
        db_session, drifted_flow, workspace
    )
    drifted = SystemVersion(
        id="version-binding-retarget",
        workspace_id=workspace.id,
        system_id=system.id,
        version_number=2,
        flow_definition=drifted_flow,
        flow_sha256=canonical_flow_sha256(drifted_flow),
        release_kind="publish",
        draft_revision=2,
        execution_contract=drifted_contract,
        message="breaking republish",
        created_by=user.email,
    )
    db_session.add(drifted)
    db_session.flush()
    system.flow_definition = drifted_flow
    system.published_flow_version_id = drifted.id
    db_session.commit()

    listed = client.get("/system-bindings/drift")
    retargeted = client.post("/system-bindings/expenses.submit/retarget")
    after = client.get("/system-bindings/drift")
    resolved = client.get("/system-bindings/expenses.submit/resolve")

    assert listed.status_code == 200, listed.text
    assert [item["binding"]["binding_key"] for item in listed.json()["bindings"]] == [
        "expenses.submit"
    ]
    assert listed.json()["bindings"][0]["status"] == "drift"
    assert retargeted.status_code == 200, retargeted.text
    assert retargeted.json()["published_flow_version_id"] == drifted.id
    assert retargeted.json()["flow_sha256"] == drifted.flow_sha256
    assert after.status_code == 200
    assert after.json()["bindings"] == []
    assert resolved.json()["status"] == "ok"
    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "experience.binding.retargeted")
        .one()
    )
    assert audit.details["binding_key"] == "expenses.submit"
    assert audit.details["to"]["published_flow_version_id"] == drifted.id


def test_invoke_delegates_to_published_ingress_and_tags_origin(
    db_session, monkeypatch
) -> None:
    workspace, user, system, version = _seed(db_session)
    client = _client(db_session, workspace, user, monkeypatch)
    created = client.post("/system-bindings", json=_create_body(version))
    assert created.status_code == 201, created.text

    invoked = client.post(
        "/system-bindings/expenses.submit/runs",
        json={"payload": {"query": "reset"}},
    )

    assert invoked.status_code == 201, invoked.text
    run = db_session.get(Run, invoked.json()["id"])
    assert run is not None
    assert run.system_id == system.id
    assert run.published_flow_version_id == version.id
    adapter = (run.input_ref or {}).get("_ingress", {}).get("adapter") or {}
    assert adapter["origin"] == "experience:expenses.submit"
    assert invoked.json()["origin"] == "experience:expenses.submit"
    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "experience.binding.invoked")
        .one()
    )
    assert audit.details["binding_key"] == "expenses.submit"
    assert audit.details["run_id"] == run.id


def test_invoke_conflict_when_binding_has_drifted(db_session, monkeypatch) -> None:
    workspace, user, system, version = _seed(db_session)
    client = _client(db_session, workspace, user, monkeypatch)
    assert client.post("/system-bindings", json=_create_body(version)).status_code == 201

    drifted_flow = _flow(extra_required="ticket")
    drifted_contract = flow_publication.compile_execution_contract(
        db_session, drifted_flow, workspace
    )
    drifted = SystemVersion(
        id="version-binding-invoke-drift",
        workspace_id=workspace.id,
        system_id=system.id,
        version_number=2,
        flow_definition=drifted_flow,
        flow_sha256=canonical_flow_sha256(drifted_flow),
        release_kind="publish",
        draft_revision=2,
        execution_contract=drifted_contract,
        message="breaking",
        created_by=user.email,
    )
    db_session.add(drifted)
    db_session.flush()
    system.flow_definition = drifted_flow
    system.published_flow_version_id = drifted.id
    db_session.commit()

    response = client.post(
        "/system-bindings/expenses.submit/runs",
        json={"payload": {"query": "reset"}},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["status"] == "drift"
    assert db_session.query(Run).count() == 0


def test_confirm_policy_requires_confirmed_flag(db_session, monkeypatch) -> None:
    workspace, user, _system, version = _seed(db_session)
    client = _client(db_session, workspace, user, monkeypatch)
    body = _create_body(version)
    body["confirmation_policy"] = "confirm"
    assert client.post("/system-bindings", json=body).status_code == 201

    denied = client.post(
        "/system-bindings/expenses.submit/runs",
        json={"payload": {"query": "reset"}},
    )
    accepted = client.post(
        "/system-bindings/expenses.submit/runs",
        json={"payload": {"query": "reset"}, "confirmed": True},
    )

    assert denied.status_code == 409
    assert denied.json()["detail"]["code"] == "BINDING_CONFIRMATION_REQUIRED"
    assert accepted.status_code == 201, accepted.text
    assert db_session.query(Run).count() == 1


def test_viewer_cannot_manage_bindings(db_session, monkeypatch) -> None:
    workspace, _admin, _system, version = _seed(db_session)
    viewer = User(
        id="user-binding-viewer",
        username="binding-viewer@example.invalid",
        email="binding-viewer@example.invalid",
        role="member",
    )
    db_session.add_all(
        [
            viewer,
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=viewer.id,
                role="member",
                role_template="workspace_viewer",
            ),
        ]
    )
    db_session.commit()
    client = _client(db_session, workspace, viewer, monkeypatch)

    created = client.post("/system-bindings", json=_create_body(version))
    listed = client.get("/system-bindings")

    assert created.status_code == 403
    assert created.json()["detail"]["code"] == "WORKSPACE_PERMISSION_DENIED"
    assert listed.status_code == 200
    assert listed.json()["bindings"] == []
    assert db_session.query(SystemBinding).count() == 0


def test_nawa_password_reset_key_resolves_when_present(db_session, monkeypatch) -> None:
    workspace, user, system, version = _seed(db_session)
    client = _client(db_session, workspace, user, monkeypatch)

    created = client.post(
        "/system-bindings",
        json=_create_body(version, key="nawa.password_reset"),
    )
    resolved = client.get("/system-bindings/nawa.password_reset/resolve")

    assert created.status_code == 201, created.text
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert body["status"] == "ok"
    assert body["binding"]["binding_key"] == "nawa.password_reset"
    assert body["binding"]["system_id"] == system.id


def test_first_real_publish_retargets_seed_stub_bindings_only(db_session) -> None:
    from app.services.experience import bindings as binding_service

    workspace, user, system, compiled = _seed(db_session)
    stub_flow = _flow()
    stub = SystemVersion(
        id="version-seed-stub",
        workspace_id=workspace.id,
        system_id=system.id,
        version_number=0,
        flow_definition=stub_flow,
        flow_sha256="c" * 64,
        release_kind="migration",
        draft_revision=1,
        execution_contract={
            "ingresses": [
                {
                    "ingress_id": "manual.input",
                    "input_schema_sha256": "d" * 64,
                }
            ]
        },
        message="089 stub",
        created_by="system:089_publish_nawa_recon",
    )
    db_session.add(stub)
    db_session.flush()
    seed_row = SystemBinding(
        workspace_id=workspace.id,
        binding_key="nawa.password_reset",
        system_id=system.id,
        published_flow_version_id=stub.id,
        flow_sha256=stub.flow_sha256,
        ingress_id="manual.input",
        input_schema_sha256="d" * 64,
        confirmation_policy="hitl",
        on_unavailable="unavailable",
        created_by="system:089_publish_nawa_recon",
    )
    author_row = SystemBinding(
        workspace_id=workspace.id,
        binding_key="expenses.submit",
        system_id=system.id,
        published_flow_version_id=stub.id,
        flow_sha256=stub.flow_sha256,
        ingress_id="manual.input",
        input_schema_sha256="d" * 64,
        confirmation_policy="confirm",
        on_unavailable="unavailable",
        created_by=user.email,
    )
    db_session.add_all([seed_row, author_row])
    db_session.commit()

    updated = binding_service.retarget_seed_stub_bindings(
        db_session,
        workspace=workspace,
        system=system,
        actor="system:test",
    )
    db_session.commit()

    assert [row.binding_key for row in updated] == ["nawa.password_reset"]
    db_session.refresh(seed_row)
    db_session.refresh(author_row)
    assert seed_row.published_flow_version_id == compiled.id
    assert seed_row.flow_sha256 == compiled.flow_sha256
    assert author_row.published_flow_version_id == stub.id
