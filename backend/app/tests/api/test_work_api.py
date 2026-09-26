"""GET /work/{slug} — live preferred, entitled pilot, flag-gated."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import work as endpoint
from app.models.run import Run
from app.models.run_dispatch_outbox import RunDispatchOutbox
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.experience import bindings as binding_service
from app.services.run_engine.execution_contract import canonical_flow_sha256
from app.services.systems import flow_publication


def _seed(db_session, *, enabled: bool = True, role_template: str = "workspace_admin"):
    workspace = Workspace(
        id="ws-work-api",
        slug="work-api",
        name="Work API",
        settings={
            "features": {
                "experience_v1": enabled,
                "flow_publication_v1": True,
            }
        },
    )
    user = User(
        id="user-work-admin",
        username="work-admin@example.invalid",
        email="work-admin@example.invalid",
        role="admin" if role_template == "workspace_admin" else "member",
    )
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="admin" if role_template == "workspace_admin" else "member",
        role_template=role_template,
    )
    db_session.add_all([workspace, user, member])
    db_session.commit()
    return workspace, user


def _client(db_session, workspace: Workspace, user: User, monkeypatch=None) -> TestClient:
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/work")
    app.dependency_overrides[endpoint.get_current_workspace] = lambda: workspace
    app.dependency_overrides[endpoint.get_current_user] = lambda: user
    app.dependency_overrides[endpoint.get_db] = lambda: db_session
    if monkeypatch is not None:
        monkeypatch.setattr(endpoint, "reconcile_dispatch_outbox", lambda: None)
    return TestClient(app)


def _experiences_client(db_session, workspace: Workspace, user: User) -> TestClient:
    from app.api.v1.endpoints import experiences as experiences_endpoint

    app = FastAPI()
    app.include_router(experiences_endpoint.router, prefix="/experiences")
    app.dependency_overrides[experiences_endpoint.get_current_workspace] = lambda: workspace
    app.dependency_overrides[experiences_endpoint.get_current_user] = lambda: user
    app.dependency_overrides[experiences_endpoint.get_db] = lambda: db_session
    return TestClient(app)


def _pages(binding_key: str | None = None) -> dict:
    component = {"type": "header", "id": "header", "props": {"title": "Reset"}}
    if binding_key:
        component = {
            "type": "form",
            "id": "reset-form",
            "props": {"bindingKey": binding_key, "schema": _input_schema()},
        }
    return {
        "pages": [
            {
                "id": "home",
                "title": "Home",
                "components": [component],
            }
        ]
    }


def _release_body(client: TestClient, experience_id: str, notes: str) -> dict[str, Any]:
    detail = client.get(f"/experiences/{experience_id}").json()
    ready = client.get(f"/experiences/{experience_id}/ready-check").json()
    return {
        "notes": notes,
        "expected_draft_revision": detail["draft"]["revision"],
        "expected_content_sha256": detail["draft"]["content_sha256"],
        "expected_experience_updated_at": detail["updated_at"],
        "expected_bindings_sha256": ready["bindings_sha256"],
    }


def _publish(
    client: TestClient,
    *,
    audience: dict | None = None,
    channel: str = "live",
    binding_key: str | None = None,
):
    create_body: dict[str, Any] = {
        "name": "Password reset",
        "slug": "password-reset",
        "pattern": "form_result",
        "languages": ["en"],
        "access_policy": {"roles": []},
    }
    if channel == "live" and audience is not None:
        create_body["access_policy"] = audience
    created = client.post(
        "/experiences",
        json=create_body,
    )
    assert created.status_code == 201, created.text
    experience_id = created.json()["id"]
    saved = client.put(
        f"/experiences/{experience_id}/draft",
        json={
            "pages": _pages(binding_key),
            "binding_keys": [binding_key] if binding_key else [],
            "expected_revision": 1,
        },
    )
    assert saved.status_code == 200, saved.text
    released = client.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(client, experience_id, "r1"),
    )
    assert released.status_code == 201, released.text
    body: dict = {
        "channel": channel,
        "release_id": released.json()["id"],
        "expected_current_release_id": None,
        "expected_deployment_updated_at": None,
    }
    if audience is not None:
        body["audience"] = audience
    deployed = client.post(f"/experiences/{experience_id}/deployments", json=body)
    assert deployed.status_code == 201, deployed.text
    return experience_id, released.json()["id"]


def _input_schema(*, ticket: bool = False) -> dict[str, Any]:
    properties: dict[str, Any] = {"query": {"type": "string"}}
    required = ["query"]
    if ticket:
        properties["ticket"] = {"type": "string"}
        required.append("ticket")
    return {
        "type": "object",
        "required": required,
        "properties": properties,
        "additionalProperties": False,
    }


def _flow(*, ticket: bool = False) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "io_mode": "strict",
        "nodes": [
            {
                "id": "manual.input",
                "kind": "source",
                "config": {
                    "ingress_kind": "manual",
                    "input_schema": _input_schema(ticket=ticket),
                },
            },
            {"id": "result", "kind": "sink"},
        ],
        "edges": [{"from": "manual.input", "to": "result", "kind": "data"}],
    }


def _seed_binding(db_session, workspace: Workspace, user: User):
    flow = _flow()
    system = System(
        id="work-bound-system",
        workspace_id=workspace.id,
        name="Work bound system",
        objective="test",
        status="active",
        flow_definition=flow,
    )
    db_session.add(system)
    db_session.flush()
    version = SystemVersion(
        id="work-bound-v1",
        workspace_id=workspace.id,
        system_id=system.id,
        version_number=1,
        flow_definition=flow,
        flow_sha256=canonical_flow_sha256(flow),
        release_kind="publish",
        draft_revision=1,
        execution_contract=flow_publication.compile_execution_contract(
            db_session, flow, workspace
        ),
        message="v1",
        created_by=user.email,
    )
    db_session.add(version)
    db_session.flush()
    system.published_flow_version_id = version.id
    system.published_by = user.email
    system.published_at = datetime.utcnow()
    binding = binding_service.create_binding(
        db_session,
        workspace=workspace,
        actor=user.email,
        binding_key="work.reset",
        system_id=system.id,
        published_flow_version_id=version.id,
        ingress_id="manual.input",
        confirmation_policy="direct-safe",
        on_unavailable="unavailable",
    )
    db_session.commit()
    return system, version, binding


def test_work_is_feature_gated(db_session) -> None:
    workspace, user = _seed(db_session, enabled=False)
    client = _client(db_session, workspace, user)

    response = client.get("/work/password-reset")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "EXPERIENCE_V1_DISABLED"


def test_work_remains_enabled_when_only_studio_is_disabled(db_session) -> None:
    workspace, user = _seed(db_session)
    workspace.settings = {
        "features": {"experience_v1": True, "experience_studio_v1": False}
    }
    db_session.add(workspace)
    db_session.commit()
    client = _client(db_session, workspace, user)

    response = client.get("/work/missing-app")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "EXPERIENCE_NOT_FOUND"


def test_work_unknown_slug_is_not_found(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    response = client.get("/work/missing-app")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "EXPERIENCE_NOT_FOUND"


def test_work_prefers_entitled_pilot_over_live_and_returns_frozen_pages(db_session) -> None:
    workspace, user = _seed(db_session)
    studio = _experiences_client(db_session, workspace, user)
    experience_id, release_id = _publish(studio, channel="pilot")
    listed = studio.get("/experiences")
    assert studio.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "live",
            "release_id": release_id,
            "expected_current_release_id": None,
            "expected_deployment_updated_at": None,
        },
    ).status_code == 201

    work = _client(db_session, workspace, user).get("/work/password-reset")

    assert work.status_code == 200, work.text
    body = work.json()
    assert body["channel"] == "pilot"
    assert body["experience"]["slug"] == "password-reset"
    assert body["release"]["pages"]["pages"][0]["id"] == "home"
    assert body["release"]["bindings_snapshot"] == []
    assert body["release"]["renderer_version"] == "certified-components-0.2.0"
    assert listed.json()["experiences"][0]["deployments"]


def test_work_preserves_historical_renderer_pin(db_session) -> None:
    from app.models.experience import ExperienceRelease

    workspace, user = _seed(db_session)
    studio = _experiences_client(db_session, workspace, user)
    _publish(studio, channel="live")
    release = db_session.query(ExperienceRelease).one()
    release.renderer_version = "certified-components-0.1.0"
    db_session.commit()

    work = _client(db_session, workspace, user).get("/work/password-reset")

    assert work.status_code == 200, work.text
    body = work.json()
    assert body["release"]["pages"]["pages"][0]["id"] == "home"
    assert body["release"]["renderer_version"] == "certified-components-0.1.0"


def test_work_pilot_empty_audience_is_open(db_session) -> None:
    workspace, admin = _seed(db_session)
    studio = _experiences_client(db_session, workspace, admin)
    _publish(studio, channel="pilot", audience={})

    viewer = User(
        id="user-work-viewer",
        username="work-viewer@example.invalid",
        email="work-viewer@example.invalid",
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

    work = _client(db_session, workspace, viewer).get("/work/password-reset")

    assert work.status_code == 200, work.text
    assert work.json()["channel"] == "pilot"


def test_work_pilot_hides_unentitled_audience(db_session) -> None:
    workspace, admin = _seed(db_session)
    studio = _experiences_client(db_session, workspace, admin)
    _publish(studio, channel="pilot", audience={"roles": ["workspace_admin"]})

    viewer = User(
        id="user-work-viewer-closed",
        username="work-viewer-closed@example.invalid",
        email="work-viewer-closed@example.invalid",
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

    hidden = _client(db_session, workspace, viewer).get("/work/password-reset")
    visible = _client(db_session, workspace, admin).get("/work/password-reset")

    assert hidden.status_code == 404
    assert visible.status_code == 200
    assert visible.json()["channel"] == "pilot"


def test_workspace_owner_can_use_an_admin_audience(db_session) -> None:
    workspace, owner = _seed(db_session, role_template="workspace_owner")
    studio = _experiences_client(db_session, workspace, owner)
    _publish(
        studio,
        channel="live",
        audience={"roles": ["workspace_admin"]},
    )

    response = _client(db_session, workspace, owner).get("/work/password-reset")

    assert response.status_code == 200, response.text


def test_work_catalog_and_channel_are_filtered_server_side(db_session) -> None:
    workspace, admin = _seed(db_session)
    studio = _experiences_client(db_session, workspace, admin)
    experience_id, release_id = _publish(
        studio,
        channel="live",
        audience={"roles": ["workspace_viewer", "workspace_admin"]},
    )
    assert studio.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "pilot",
            "release_id": release_id,
            "expected_current_release_id": None,
            "expected_deployment_updated_at": None,
            "audience": {"roles": ["workspace_admin"]},
        },
    ).status_code == 201
    viewer = User(
        id="user-work-catalog-viewer",
        username="catalog-viewer@example.invalid",
        email="catalog-viewer@example.invalid",
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

    viewer_catalog = _client(db_session, workspace, viewer).get("/work")
    admin_catalog = _client(db_session, workspace, admin).get("/work")

    assert viewer_catalog.status_code == 200
    assert viewer_catalog.json()["experiences"][0]["channel"] == "live"
    assert "pages" not in viewer_catalog.json()["experiences"][0]["release"]
    assert admin_catalog.json()["experiences"][0]["channel"] == "pilot"


def test_work_audience_is_strict_and_malformed_persisted_data_closes(db_session) -> None:
    from app.models.experience import ExperienceDeployment

    workspace, admin = _seed(db_session)
    studio = _experiences_client(db_session, workspace, admin)
    experience_id, _release_id = _publish(studio, channel="live")
    invalid = studio.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "live",
            "release_id": db_session.query(ExperienceDeployment).one().release_id,
            "expected_current_release_id": db_session.query(ExperienceDeployment).one().release_id,
            "expected_deployment_updated_at": db_session.query(ExperienceDeployment).one().updated_at.isoformat(),
            "audience": {"roles": "workspace_admin"},
        },
    )
    assert invalid.status_code == 422
    deployment = db_session.query(ExperienceDeployment).one()
    deployment.audience = {"unknown": ["workspace_admin"]}
    db_session.commit()

    hidden = _client(db_session, workspace, admin)
    assert hidden.get("/work/password-reset").status_code == 404
    assert hidden.get("/work").json()["experiences"] == []


def test_deployed_run_uses_release_snapshot_after_binding_retarget_and_delete(
    db_session, monkeypatch
) -> None:
    workspace, admin = _seed(db_session)
    system, version_v1, _binding = _seed_binding(db_session, workspace, admin)
    studio = _experiences_client(db_session, workspace, admin)
    _publish(studio, binding_key="work.reset", channel="live")

    flow_v2 = _flow(ticket=True)
    version_v2 = SystemVersion(
        id="work-bound-v2",
        workspace_id=workspace.id,
        system_id=system.id,
        version_number=2,
        flow_definition=flow_v2,
        flow_sha256=canonical_flow_sha256(flow_v2),
        release_kind="publish",
        draft_revision=2,
        execution_contract=flow_publication.compile_execution_contract(
            db_session, flow_v2, workspace
        ),
        message="v2",
        created_by=admin.email,
    )
    db_session.add(version_v2)
    db_session.flush()
    system.flow_definition = flow_v2
    system.published_flow_version_id = version_v2.id
    binding_service.update_binding(
        db_session,
        workspace=workspace,
        binding_key="work.reset",
        published_flow_version_id=version_v2.id,
    )
    binding_service.delete_binding(
        db_session, workspace_id=workspace.id, binding_key="work.reset"
    )
    db_session.commit()

    work = _client(db_session, workspace, admin, monkeypatch)
    resolved = work.get("/work/password-reset/bindings/work.reset/resolve")
    request = {
        "payload": {"query": "reset"},
        "page_id": "home",
        "component_id": "reset-form",
    }
    headers = {"Idempotency-Key": "work-reset-request-0001"}
    invoked = work.post(
        "/work/password-reset/bindings/work.reset/runs",
        json=request,
        headers=headers,
    )
    replayed = work.post(
        "/work/password-reset/bindings/work.reset/runs",
        json=request,
        headers=headers,
    )
    reused_for_other_payload = work.post(
        "/work/password-reset/bindings/work.reset/runs",
        json={**request, "payload": {"query": "other"}},
        headers=headers,
    )

    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "ok"
    assert "published_flow_version_id" not in resolved.json()["binding"]
    assert "system_id" not in resolved.json()["binding"]
    assert invoked.status_code == 201, invoked.text
    assert invoked.json()["idempotent_replay"] is False
    assert replayed.status_code == 201, replayed.text
    assert replayed.json()["id"] == invoked.json()["id"]
    assert replayed.json()["idempotent_replay"] is True
    assert reused_for_other_payload.status_code == 409
    assert (
        reused_for_other_payload.json()["detail"]["code"]
        == "WORK_IDEMPOTENCY_KEY_REUSED"
    )
    assert "published_flow_version_id" not in invoked.json()
    assert "system_id" not in invoked.json()
    assert invoked.json()["origin"] == "experience:password-reset"
    run = db_session.get(Run, invoked.json()["id"])
    assert run.published_flow_version_id == version_v1.id
    adapter = run.input_ref["_ingress"]["adapter"]
    assert adapter["experience_release_id"] == invoked.json()["experience_release_id"]
    assert adapter["experience_deployment_id"] == invoked.json()["experience_deployment_id"]
    assert adapter["binding_key"] == "work.reset"
    assert adapter["page_id"] == "home"
    assert adapter["component_id"] == "reset-form"


def test_work_idempotency_replays_the_original_run_after_redeployment(
    db_session, monkeypatch
) -> None:
    workspace, admin = _seed(db_session)
    _system, _version, _binding = _seed_binding(db_session, workspace, admin)
    studio = _experiences_client(db_session, workspace, admin)
    experience_id, first_release_id = _publish(
        studio, binding_key="work.reset", channel="live"
    )
    work = _client(db_session, workspace, admin, monkeypatch)
    request = {
        "payload": {"query": "reset"},
        "page_id": "home",
        "component_id": "reset-form",
    }
    headers = {"Idempotency-Key": "work-across-release-0001"}

    invoked = work.post(
        "/work/password-reset/bindings/work.reset/runs",
        json=request,
        headers=headers,
    )
    detail = studio.get(f"/experiences/{experience_id}").json()
    saved = studio.put(
        f"/experiences/{experience_id}/draft",
        json={
            "pages": _pages("work.reset"),
            "binding_keys": ["work.reset"],
            "expected_revision": detail["draft"]["revision"],
        },
    )
    assert saved.status_code == 200, saved.text
    second = studio.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(studio, experience_id, "r2"),
    )
    assert second.status_code == 201, second.text
    live = next(
        row for row in studio.get(f"/experiences/{experience_id}").json()["deployments"]
        if row["channel"] == "live"
    )
    moved = studio.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "live",
            "release_id": second.json()["id"],
            "expected_current_release_id": first_release_id,
            "expected_deployment_updated_at": live["updated_at"],
        },
    )
    replayed = work.post(
        "/work/password-reset/bindings/work.reset/runs",
        json=request,
        headers=headers,
    )

    assert invoked.status_code == 201, invoked.text
    assert moved.status_code == 201, moved.text
    assert replayed.status_code == 201, replayed.text
    assert replayed.json()["id"] == invoked.json()["id"]
    assert replayed.json()["experience_release_id"] == first_release_id
    assert replayed.json()["idempotent_replay"] is True
    assert db_session.query(Run).count() == 1


def test_pending_idempotent_replay_keeps_one_durable_dispatch(
    db_session, monkeypatch
) -> None:
    workspace, admin = _seed(db_session)
    _seed_binding(db_session, workspace, admin)
    _publish(
        _experiences_client(db_session, workspace, admin),
        binding_key="work.reset",
        channel="live",
    )
    work = _client(db_session, workspace, admin, monkeypatch)
    reconciled: list[bool] = []
    monkeypatch.setattr(endpoint, "reconcile_dispatch_outbox", lambda: reconciled.append(True))
    request = {
        "payload": {"query": "reset"},
        "page_id": "home",
        "component_id": "reset-form",
    }
    headers = {"Idempotency-Key": "work-recovery-replay-0001"}

    first = work.post(
        "/work/password-reset/bindings/work.reset/runs",
        json=request,
        headers=headers,
    )
    reconciled.clear()
    replayed = work.post(
        "/work/password-reset/bindings/work.reset/runs",
        json=request,
        headers=headers,
    )

    assert first.status_code == 201, first.text
    assert replayed.status_code == 201, replayed.text
    assert replayed.json()["idempotent_replay"] is True
    assert reconciled == [True]
    dispatch = db_session.query(RunDispatchOutbox).one()
    assert dispatch.run_id == first.json()["id"]
    assert dispatch.event_type == "trigger_run"


def test_idempotent_replay_rechecks_current_audience_before_rescheduling(
    db_session, monkeypatch
) -> None:
    workspace, admin = _seed(db_session)
    _seed_binding(db_session, workspace, admin)
    studio = _experiences_client(db_session, workspace, admin)
    experience_id, first_release_id = _publish(
        studio,
        binding_key="work.reset",
        channel="live",
    )
    work = _client(db_session, workspace, admin, monkeypatch)
    reconciled: list[bool] = []
    monkeypatch.setattr(endpoint, "reconcile_dispatch_outbox", lambda: reconciled.append(True))
    request = {
        "payload": {"query": "reset"},
        "page_id": "home",
        "component_id": "reset-form",
    }
    headers = {"Idempotency-Key": "work-revoked-replay-0001"}
    first = work.post(
        "/work/password-reset/bindings/work.reset/runs",
        json=request,
        headers=headers,
    )
    assert first.status_code == 201, first.text
    reconciled.clear()

    detail = studio.get(f"/experiences/{experience_id}").json()
    changed = studio.patch(
        f"/experiences/{experience_id}",
        json={
            "access_policy": {"roles": ["workspace_viewer"]},
            "expected_updated_at": detail["updated_at"],
        },
    )
    assert changed.status_code == 200, changed.text
    second = studio.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(studio, experience_id, "withdraw admin audience"),
    )
    assert second.status_code == 201, second.text
    live = next(
        deployment
        for deployment in studio.get(f"/experiences/{experience_id}").json()[
            "deployments"
        ]
        if deployment["channel"] == "live"
    )
    moved = studio.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "live",
            "release_id": second.json()["id"],
            "expected_current_release_id": first_release_id,
            "expected_deployment_updated_at": live["updated_at"],
        },
    )
    assert moved.status_code == 201, moved.text

    replayed = work.post(
        "/work/password-reset/bindings/work.reset/runs",
        json=request,
        headers=headers,
    )

    assert replayed.status_code == 404
    assert replayed.json()["detail"]["code"] == "EXPERIENCE_NOT_FOUND"
    assert reconciled == []
    assert db_session.query(Run).count() == 1


def test_work_validations_only_project_runs_the_user_can_approve(db_session) -> None:
    workspace, admin = _seed(db_session)
    system, _version, _binding = _seed_binding(db_session, workspace, admin)
    _publish(
        _experiences_client(db_session, workspace, admin),
        binding_key="work.reset",
        channel="live",
    )
    viewer = User(
        id="user-work-validator",
        username="work-validator@example.invalid",
        email="work-validator@example.invalid",
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
    origin = {"_ingress": {"adapter": {"origin": "experience:password-reset"}}}
    own = Run(
        id="work-own-hitl",
        workspace_id=workspace.id,
        system_id=system.id,
        initiated_by_user_id=viewer.id,
        status="hitl_pending",
        input_ref=origin,
        checkpoints=[{"kind": "hitl_pause", "prompt": "Own decision"}],
    )
    foreign = Run(
        id="work-foreign-hitl",
        workspace_id=workspace.id,
        system_id=system.id,
        initiated_by_user_id=admin.id,
        status="hitl_pending",
        input_ref=origin,
        checkpoints=[{"kind": "hitl_pause", "prompt": "Private decision"}],
    )
    db_session.add_all([own, foreign])
    db_session.commit()

    viewer_rows = _client(db_session, workspace, viewer).get(
        "/work/password-reset/validations"
    )
    admin_rows = _client(db_session, workspace, admin).get(
        "/work/password-reset/validations"
    )

    assert viewer_rows.status_code == 200, viewer_rows.text
    assert [row["id"] for row in viewer_rows.json()["runs"]] == [own.id]
    assert viewer_rows.json()["runs"][0]["hitl"]["prompt"] == "Own decision"
    assert {row["id"] for row in admin_rows.json()["runs"]} == {own.id, foreign.id}


def test_work_validations_include_a_bound_system_pause_and_skip_the_scheduler(db_session) -> None:
    workspace, admin = _seed(db_session)
    system, _version, _binding = _seed_binding(db_session, workspace, admin)
    _publish(
        _experiences_client(db_session, workspace, admin),
        binding_key="work.reset",
        channel="live",
    )
    paused = Run(
        id="work-bound-pause",
        workspace_id=workspace.id,
        system_id=system.id,
        initiated_by_user_id=admin.id,
        status="hitl_pending",
        trigger="manual",
        input_ref={},
        checkpoints=[{"kind": "hitl_pause", "prompt": "Approve the purchase order", "decision_id": "dec-1"}],
    )
    scheduled = Run(
        id="work-scheduled-pause",
        workspace_id=workspace.id,
        system_id=system.id,
        initiated_by_user_id=admin.id,
        status="hitl_pending",
        trigger="scheduler",
        input_ref={},
        checkpoints=[{"kind": "hitl_pause", "prompt": "Nightly tick"}],
    )
    db_session.add_all([paused, scheduled])
    db_session.commit()

    rows = _client(db_session, workspace, admin).get("/work/password-reset/validations")

    assert rows.status_code == 200, rows.text
    assert [row["id"] for row in rows.json()["runs"]] == [paused.id]


def test_work_validations_limits_after_approval_authority(db_session) -> None:
    workspace, admin = _seed(db_session)
    system, _version, _binding = _seed_binding(db_session, workspace, admin)
    _publish(
        _experiences_client(db_session, workspace, admin),
        binding_key="work.reset",
        channel="live",
    )
    viewer = User(
        id="user-work-validator",
        username="work-validator@example.invalid",
        email="work-validator@example.invalid",
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
    origin = {"_ingress": {"adapter": {"origin": "experience:password-reset"}}}
    oldest = datetime(2026, 1, 1)
    own = Run(
        id="work-own-old-hitl",
        workspace_id=workspace.id,
        system_id=system.id,
        initiated_by_user_id=viewer.id,
        status="hitl_pending",
        started_at=oldest,
        input_ref=origin,
        checkpoints=[{"kind": "hitl_pause", "prompt": "Own old decision"}],
    )
    foreign = [
        Run(
            id=f"work-foreign-{index:03d}",
            workspace_id=workspace.id,
            system_id=system.id,
            initiated_by_user_id=admin.id,
            status="hitl_pending",
            started_at=oldest + timedelta(minutes=index + 1),
            input_ref=origin,
            checkpoints=[{"kind": "hitl_pause", "prompt": "Foreign decision"}],
        )
        for index in range(101)
    ]
    db_session.add_all([own, *foreign])
    db_session.commit()

    response = _client(db_session, workspace, viewer).get(
        "/work/password-reset/validations"
    )

    assert response.status_code == 200, response.text
    assert [row["id"] for row in response.json()["runs"]] == [own.id]


def test_work_catalog_pending_decisions_match_validations_for_same_reader(db_session) -> None:
    """L17 — GET /work counter equals /{slug}/validations for the same reader."""
    workspace, admin = _seed(db_session)
    system, _version, _binding = _seed_binding(db_session, workspace, admin)
    _publish(
        _experiences_client(db_session, workspace, admin),
        binding_key="work.reset",
        channel="live",
    )
    viewer = User(
        id="user-work-pending-viewer",
        username="work-pending-viewer@example.invalid",
        email="work-pending-viewer@example.invalid",
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
    origin = {"_ingress": {"adapter": {"origin": "experience:password-reset"}}}
    older = Run(
        id="work-pending-old",
        workspace_id=workspace.id,
        system_id=system.id,
        initiated_by_user_id=viewer.id,
        status="hitl_pending",
        started_at=datetime(2026, 3, 1, 10, 0, 0),
        input_ref=origin,
        checkpoints=[{"kind": "hitl_pause", "prompt": "Older"}],
    )
    newer = Run(
        id="work-pending-new",
        workspace_id=workspace.id,
        system_id=system.id,
        initiated_by_user_id=viewer.id,
        status="hitl_pending",
        started_at=datetime(2026, 3, 2, 10, 0, 0),
        input_ref=origin,
        checkpoints=[{"kind": "hitl_pause", "prompt": "Newer"}],
    )
    foreign = Run(
        id="work-pending-foreign",
        workspace_id=workspace.id,
        system_id=system.id,
        initiated_by_user_id=admin.id,
        status="hitl_pending",
        started_at=datetime(2026, 2, 1, 10, 0, 0),
        input_ref=origin,
        checkpoints=[{"kind": "hitl_pause", "prompt": "Admin only"}],
    )
    db_session.add_all([older, newer, foreign])
    db_session.commit()

    client = _client(db_session, workspace, viewer)
    catalog = client.get("/work")
    validations = client.get("/work/password-reset/validations")

    assert catalog.status_code == 200, catalog.text
    assert validations.status_code == 200, validations.text
    item = next(
        row
        for row in catalog.json()["experiences"]
        if row["experience"]["slug"] == "password-reset"
    )
    pending = item["pending_decisions"]
    runs = validations.json()["runs"]
    assert pending["count"] == len(runs) == 2
    assert {row["id"] for row in runs} == {older.id, newer.id}
    assert pending["oldest_at"] == older.started_at.isoformat()

    admin_catalog = _client(db_session, workspace, admin).get("/work")
    admin_item = next(
        row
        for row in admin_catalog.json()["experiences"]
        if row["experience"]["slug"] == "password-reset"
    )
    assert admin_item["pending_decisions"]["count"] == 3


def test_work_rejects_component_context_that_does_not_own_binding(
    db_session, monkeypatch
) -> None:
    workspace, admin = _seed(db_session)
    _seed_binding(db_session, workspace, admin)
    _publish(
        _experiences_client(db_session, workspace, admin),
        binding_key="work.reset",
        channel="live",
    )

    response = _client(db_session, workspace, admin, monkeypatch).post(
        "/work/password-reset/bindings/work.reset/runs",
        json={
            "payload": {"query": "reset"},
            "page_id": "home",
            "component_id": "other",
        },
        headers={"Idempotency-Key": "work-invalid-context-0001"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "EXPERIENCE_BINDING_CONTEXT_INVALID"


def test_work_uses_frozen_release_identity_and_minimal_public_projection(db_session) -> None:
    workspace, admin = _seed(db_session)
    studio = _experiences_client(db_session, workspace, admin)
    created = studio.post(
        "/experiences",
        json={
            "name": "Frozen name",
            "description": "Operator cockpit",
            "emblem": "🧭",
            "slug": "frozen-app",
            "pattern": "form_result",
            "languages": ["en"],
            "access_policy": {"roles": []},
        },
    )
    experience_id = created.json()["id"]
    saved = studio.put(
        f"/experiences/{experience_id}/draft",
        json={"pages": _pages(), "binding_keys": [], "expected_revision": 1},
    )
    released = studio.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(studio, experience_id, "identity"),
    )
    assert studio.patch(
        f"/experiences/{experience_id}",
        json={
            "name": "Future name",
            "description": "Future description",
            "emblem": "future",
            "pattern": "approval",
        },
    ).status_code == 200
    assert studio.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "live",
            "release_id": released.json()["id"],
            "expected_current_release_id": None,
            "expected_deployment_updated_at": None,
        },
    ).status_code == 201

    work = _client(db_session, workspace, admin)
    detail = work.get("/work/frozen-app")
    catalog = work.get("/work")

    assert detail.status_code == 200, detail.text
    assert detail.json()["experience"] == {
        "id": experience_id,
        "name": "Frozen name",
        "description": "Operator cockpit",
        "emblem": "🧭",
        "slug": "frozen-app",
        "pattern": "form_result",
    }
    assert set(detail.json()["release"]) == {
        "id",
        "pages",
        "bindings_snapshot",
        "languages",
        "theme",
        "renderer_version",
    }
    item = catalog.json()["experiences"][0]
    assert item["experience"]["name"] == "Frozen name"
    assert item["experience"]["description"] == "Operator cockpit"
    assert item["experience"]["emblem"] == "🧭"
    assert "workspace_id" not in item["experience"]
    assert "access_policy" not in item["experience"]


def test_release_access_snapshot_cannot_be_widened_by_deployment(db_session) -> None:
    workspace, admin = _seed(db_session)
    studio = _experiences_client(db_session, workspace, admin)
    created = studio.post(
        "/experiences",
        json={
            "name": "Restricted",
            "slug": "restricted-app",
            "pattern": "form_result",
            "languages": ["en"],
            "access_policy": {"roles": ["workspace_admin"]},
        },
    )
    experience_id = created.json()["id"]
    saved = studio.put(
        f"/experiences/{experience_id}/draft",
        json={"pages": _pages(), "binding_keys": [], "expected_revision": 1},
    )
    released = studio.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(studio, experience_id, "restricted"),
    )
    release_id = released.json()["id"]
    widened_live = studio.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "live",
            "release_id": release_id,
            "expected_current_release_id": None,
            "expected_deployment_updated_at": None,
            "audience": {"roles": ["workspace_viewer"]},
        },
    )
    assert widened_live.status_code == 409
    assert widened_live.json()["detail"]["code"] == "EXPERIENCE_LIVE_AUDIENCE_IMMUTABLE"
    widened_pilot = studio.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "pilot",
            "release_id": release_id,
            "expected_current_release_id": None,
            "expected_deployment_updated_at": None,
            "audience": {"roles": ["workspace_admin", "workspace_viewer"]},
        },
    )
    assert widened_pilot.status_code == 409
    assert (
        widened_pilot.json()["detail"]["code"]
        == "EXPERIENCE_DEPLOYMENT_AUDIENCE_WIDENS_RELEASE"
    )
    widened_group = studio.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "pilot",
            "release_id": release_id,
            "expected_current_release_id": None,
            "expected_deployment_updated_at": None,
            "audience": {"groups": ["pilot-a"]},
        },
    )
    assert widened_group.status_code == 409
    assert (
        widened_group.json()["detail"]["code"]
        == "EXPERIENCE_DEPLOYMENT_AUDIENCE_WIDENS_RELEASE"
    )
    assert studio.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "pilot",
            "release_id": release_id,
            "expected_current_release_id": None,
            "expected_deployment_updated_at": None,
            "audience": {"roles": ["workspace_admin"]},
        },
    ).status_code == 201

    viewer = User(
        id="user-release-bound-viewer",
        username="release-bound-viewer@example.invalid",
        email="release-bound-viewer@example.invalid",
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

    viewer_work = _client(db_session, workspace, viewer)
    assert viewer_work.get("/work/restricted-app").status_code == 404
    assert viewer_work.get("/work").json()["experiences"] == []
    assert _client(db_session, workspace, admin).get("/work/restricted-app").status_code == 200


def test_group_audience_is_enforced_server_side(db_session) -> None:
    workspace, admin = _seed(db_session)
    studio = _experiences_client(db_session, workspace, admin)
    _publish(studio, channel="pilot", audience={"groups": ["pilot-a"]})
    viewer = User(
        id="user-work-group",
        username="work-group@example.invalid",
        email="work-group@example.invalid",
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
                custom_labels=["pilot-a"],
            ),
        ]
    )
    db_session.commit()

    assert _client(db_session, workspace, viewer).get("/work/password-reset").status_code == 200


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("confirmation_policy", "anything"),
        ("on_unavailable", "fallback-anywhere"),
        ("flow_sha256", "z" * 64),
        ("input_schema_sha256", "short"),
    ],
)
def test_work_binding_snapshot_corruption_fails_closed(
    db_session, field: str, value: str
) -> None:
    from app.models.experience import ExperienceRelease

    workspace, admin = _seed(db_session)
    _seed_binding(db_session, workspace, admin)
    _publish(
        _experiences_client(db_session, workspace, admin),
        binding_key="work.reset",
        channel="live",
    )
    release = db_session.query(ExperienceRelease).one()
    snapshot = [dict(item) for item in release.bindings_snapshot]
    snapshot[0][field] = value
    release.bindings_snapshot = snapshot
    db_session.commit()

    response = _client(db_session, workspace, admin).get(
        "/work/password-reset/bindings/work.reset/resolve"
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RELEASE_BINDING_SNAPSHOT_INVALID"


def test_system_linked_work_apps_are_filtered_by_reader_rights(db_session) -> None:
    """L14 — GET /work/systems/{id}/apps returns only apps the reader can open."""
    workspace, admin = _seed(db_session)
    system, _version, _binding = _seed_binding(db_session, workspace, admin)
    studio = _experiences_client(db_session, workspace, admin)
    experience_id, _release_id = _publish(
        studio,
        binding_key="work.reset",
        channel="live",
        audience={"roles": ["workspace_admin"]},
    )
    other = System(
        id="work-unrelated-system",
        workspace_id=workspace.id,
        name="Unrelated",
        objective="test",
        status="active",
        flow_definition=_flow(),
    )
    db_session.add(other)
    db_session.commit()

    viewer = User(
        id="user-work-linked-viewer",
        username="linked-viewer@example.invalid",
        email="linked-viewer@example.invalid",
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

    admin_client = _client(db_session, workspace, admin)
    catalog = admin_client.get("/work")
    assert catalog.status_code == 200, catalog.text
    item = catalog.json()["experiences"][0]
    assert item["binding_system_ids"] == [system.id]

    linked = admin_client.get(f"/work/systems/{system.id}/apps")
    assert linked.status_code == 200, linked.text
    apps = linked.json()["apps"]
    assert len(apps) == 1
    assert apps[0]["id"] == experience_id
    assert apps[0]["href"] == "/work/password-reset"
    assert apps[0]["type"] == "form_result"
    assert apps[0]["channel"] == "live"
    assert apps[0]["kind"] == "experience"

    empty = admin_client.get(f"/work/systems/{other.id}/apps")
    assert empty.status_code == 200
    assert empty.json()["apps"] == []

    missing = admin_client.get("/work/systems/missing-system/apps")
    assert missing.status_code == 404

    viewer_client = _client(db_session, workspace, viewer)
    denied = viewer_client.get(f"/work/systems/{system.id}/apps")
    assert denied.status_code == 200
    assert denied.json()["apps"] == []
    assert viewer_client.get("/work").json()["experiences"] == []
