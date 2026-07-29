"""API tests for the per-System event-trigger piloting endpoints.

Covers ``GET /systems/{id}/event-trigger`` (read-only state) and
``PATCH /systems/{id}/event-trigger`` (mode flip + circuit-breaker re-arm),
which merge into ``System.settings['event_trigger']`` — the same JSON blob the
run engine reads through ``triggers.trigger_mode`` (Flow Builder sources DAG,
Phase 3). No migration: the state lives entirely in ``settings``.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import systems
from app.models.audit import AuditLog
from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(systems.router, prefix="/systems")
    app.dependency_overrides[systems.get_current_workspace] = lambda: workspace
    app.dependency_overrides[systems.get_current_user] = lambda: user
    app.dependency_overrides[systems.get_db] = lambda: db_session
    return TestClient(app)


def _seed(db_session, *, settings_blob: dict | None = None) -> tuple[Workspace, User, System]:
    user = User(id="user-et", username="et@datategy.test", email="et@datategy.test")
    workspace = Workspace(id="ws-et", name="Event Trigger", slug="event-trigger")
    system = System(
        id="sys-et",
        workspace_id=workspace.id,
        name="Trigger pilot",
        status="active",
        settings=settings_blob or {},
        flow_definition={
            "schema_version": 3,
            "nodes": [
                {"id": "src.sftp", "kind": "source", "type": "source.sftp_arrival"},
            ],
            "edges": [],
        },
    )
    db_session.add_all([user, workspace, system])
    db_session.commit()
    return workspace, user, system


def _set_v2_mode(
    db_session,
    workspace: Workspace,
    user: User,
    key: str,
    mode: str,
) -> WorkspaceIAMConfig:
    config = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        version=1,
        role_flags={},
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "modes": {key: mode},
            }
        },
        updated_by_user_id=user.id,
    )
    db_session.add(config)
    db_session.commit()
    return config


def test_get_event_trigger_defaults_to_dry_run(db_session, monkeypatch):
    workspace, user, _system = _seed(db_session)
    monkeypatch.setattr(systems.settings, "enable_event_triggers", True)
    client = _client(db_session, workspace, user)

    res = client.get("/systems/sys-et/event-trigger")
    assert res.status_code == 200
    body = res.json()
    assert body["system_id"] == "sys-et"
    assert body["master_enabled"] is True
    assert body["mode"] == "dry_run"
    assert body["disabled"] is False
    assert body["disabled_reason"] is None


def test_patch_mode_to_live_persists_and_reads_back(db_session):
    workspace, user, system = _seed(db_session)
    client = _client(db_session, workspace, user)

    res = client.patch("/systems/sys-et/event-trigger", json={"mode": "live"})
    assert res.status_code == 200
    assert res.json()["mode"] == "live"

    db_session.refresh(system)
    assert system.settings["event_trigger"]["mode"] == "live"

    # The read endpoint reflects the persisted mode.
    assert client.get("/systems/sys-et/event-trigger").json()["mode"] == "live"


def test_patch_rearm_clears_circuit_breaker_provenance(db_session):
    # Pre-trip the breaker exactly as ``triggers._trip_circuit_breaker`` does.
    workspace, user, system = _seed(
        db_session,
        settings_blob={
            "event_trigger": {
                "mode": "live",
                "disabled": True,
                "disabled_reason": "circuit_breaker",
                "disabled_at": "2026-07-10T00:00:00",
            }
        },
    )
    client = _client(db_session, workspace, user)

    before = client.get("/systems/sys-et/event-trigger").json()
    assert before["disabled"] is True
    assert before["disabled_reason"] == "circuit_breaker"

    res = client.patch("/systems/sys-et/event-trigger", json={"disabled": False})
    assert res.status_code == 200
    body = res.json()
    assert body["disabled"] is False
    assert body["disabled_reason"] is None
    assert body["disabled_at"] is None
    # Mode is preserved when only re-arming.
    assert body["mode"] == "live"

    db_session.refresh(system)
    et = system.settings["event_trigger"]
    assert et["disabled"] is False
    assert et["rearmed_at"] is not None


def test_patch_rejects_invalid_mode(db_session):
    workspace, user, _system = _seed(db_session)
    client = _client(db_session, workspace, user)

    res = client.patch("/systems/sys-et/event-trigger", json={"mode": "turbo"})
    assert res.status_code == 400


def test_patch_rejects_empty_body(db_session):
    workspace, user, _system = _seed(db_session)
    client = _client(db_session, workspace, user)

    res = client.patch("/systems/sys-et/event-trigger", json={})
    assert res.status_code == 400


def test_event_trigger_404_for_unknown_system(db_session):
    workspace, user, _system = _seed(db_session)
    client = _client(db_session, workspace, user)

    assert client.get("/systems/nope/event-trigger").status_code == 404
    assert client.patch("/systems/nope/event-trigger", json={"mode": "live"}).status_code == 404


def test_event_trigger_admin_shadow_preserves_legacy_then_enforce_blocks(
    db_session,
    attest_authorization_v2,
):
    workspace, user, system = _seed(db_session)
    _set_v2_mode(db_session, workspace, user, "system.admin", "shadow")
    client = _client(db_session, workspace, user)

    shadow = client.patch("/systems/sys-et/event-trigger", json={"mode": "live"})
    assert shadow.status_code == 200
    diff = db_session.query(AuditLog).filter_by(
        workspace_id=workspace.id,
        event_type="iam.shadow.diff",
    ).one()
    assert diff.details["resource"] == {
        "kind": "system",
        "system_id": system.id,
    }
    assert diff.details["action"] == "system.admin"
    assert diff.details["legacy_allowed"] is True
    assert diff.details["candidate_allowed"] is False

    config = db_session.query(WorkspaceIAMConfig).filter_by(
        workspace_id=workspace.id
    ).one()
    config.capability_overrides = {
        "authorization_v2": {
            "policy_version": 2,
            "default_mode": "compat",
            "modes": {"system.admin": "enforce"},
        }
    }
    attest_authorization_v2(config, ["system.admin"])
    db_session.commit()

    denied = client.patch("/systems/sys-et/event-trigger", json={"mode": "dry_run"})
    assert denied.status_code == 403
    assert denied.json()["detail"]["mode"] == "enforce"
    db_session.refresh(system)
    assert system.settings["event_trigger"]["mode"] == "live"


def test_system_admin_enforce_covers_secondary_mutation_surfaces(
    db_session,
    attest_authorization_v2,
):
    workspace, user, system = _seed(db_session)
    config = _set_v2_mode(db_session, workspace, user, "system.admin", "enforce")
    attest_authorization_v2(config, ["system.admin"])
    db_session.commit()
    client = _client(db_session, workspace, user)

    requests = [
        ("patch", "/systems/sys-et", {}),
        ("delete", "/systems/sys-et", None),
        ("post", "/systems/sys-et/versions/1/rollback", {}),
        ("post", "/systems/import", {"envelope": {}}),
        ("post", "/systems/sys-et/schedules", {"cron_expr": "0 9 * * *"}),
        ("patch", "/systems/sys-et/schedules/missing", {"enabled": False}),
        ("delete", "/systems/sys-et/schedules/missing", None),
        ("post", "/systems/sys-et/hooks", {}),
        ("patch", "/systems/sys-et/hooks/missing", {"rotate_secret": True}),
        ("delete", "/systems/sys-et/hooks/missing", None),
    ]
    for method, path, body in requests:
        response = client.request(method.upper(), path, json=body)
        assert response.status_code == 403, (method, path, response.text)
        assert response.json()["detail"]["mode"] == "enforce"

    db_session.refresh(system)
    assert system.settings == {}


def test_system_read_enforce_covers_configuration_surfaces(
    db_session,
    attest_authorization_v2,
):
    workspace, user, _system = _seed(db_session)
    config = _set_v2_mode(db_session, workspace, user, "system.read", "enforce")
    attest_authorization_v2(config, ["system.read"])
    db_session.commit()
    client = _client(db_session, workspace, user)

    paths = [
        "/systems/sys-et",
        "/systems/sys-et/flow-manifest",
        "/systems/sys-et/event-trigger",
        "/systems/sys-et/versions",
        "/systems/sys-et/versions/1",
        "/systems/sys-et/export",
        "/systems/sys-et/runs",
        "/systems/sys-et/schedules",
        "/systems/sys-et/hooks",
    ]
    for path in paths:
        response = client.get(path)
        assert response.status_code == 403, (path, response.text)
        assert response.json()["detail"]["mode"] == "enforce"


def test_system_run_collection_applies_per_run_read_authorization(
    db_session,
    attest_authorization_v2,
):
    workspace, user, system = _seed(db_session)
    db_session.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role="member",
            role_template="workspace_contributor",
        )
    )
    db_session.add_all(
        [
            Run(
                id="run-owned",
                workspace_id=workspace.id,
                system_id=system.id,
                initiated_by_user_id=user.id,
                status="completed",
            ),
            Run(
                id="run-private",
                workspace_id=workspace.id,
                system_id=system.id,
                initiated_by_user_id="another-user",
                status="completed",
            ),
        ]
    )
    config = _set_v2_mode(db_session, workspace, user, "run.read", "enforce")
    attest_authorization_v2(config, ["run.read"])
    db_session.commit()

    response = _client(db_session, workspace, user).get("/systems/sys-et/runs")

    assert response.status_code == 200
    assert [row["id"] for row in response.json()["runs"]] == ["run-owned"]
