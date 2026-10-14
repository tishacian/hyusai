"""Revocation checks use live metadata, not repeated decryption or cached ORM state."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.db.base import SessionLocal
from app.models.connector_connection import ConnectorGrant
from app.models.secret import SecretVersion
from app.models.workspace import WorkspaceMember
from app.services import compute_runs as runs
from app.services import secrets as registry
from app.services.connectors import connections as service
from app.tests.services.test_compute_runs import registered as runs_fixture
from app.tests.services.test_compute_runs import submit
from app.tests.services.test_connection_registry import create, personal
from app.tests.services.test_connection_registry import setup as registry_setup
from app.workers import tasks_connectors as worker

setup = registry_setup
registered = runs_fixture


def test_child_policy_never_inherits_legacy_report_window(db_session, setup, monkeypatch):
    from app.core.config import settings

    connection = create(db_session, setup)
    monkeypatch.setattr(settings, "connector_network_policy_mode", "report")
    monkeypatch.setattr(settings, "hana_network_policy_mode", "report")
    row = runs.create_run(
        db_session,
        workspace_id=setup[0].id,
        user_id=setup[2][0].id,
        connection_id=connection.id,
        operation="test",
    )
    policy = worker._load_spec(db_session, row)["network_policy"]
    assert policy["connector_network_policy_mode"] == "enforce"
    assert policy["hana_network_policy_mode"] == "enforce"


def test_snapshot_never_decrypts_and_rotation_changes_unpinned_version(
    db_session, setup, monkeypatch
):
    row = create(db_session, setup)
    ws, _, users, metadata = setup
    first = service.authorization_snapshot(db_session, row, user_id=users[0].id)
    monkeypatch.setattr(
        registry, "resolve", lambda *a, **kw: pytest.fail("metadata must not decrypt")
    )
    assert service.authorization_snapshot(db_session, row, user_id=users[0].id) == first
    registry.rotate(db_session, metadata["id"], value="changed", actor=users[0].id)
    assert service.authorization_snapshot(db_session, row, user_id=users[0].id) != first


@pytest.mark.parametrize("change", ["membership", "destroyed", "disabled"])
def test_snapshot_observes_another_session_revocation(db_session, setup, change):
    row = create(db_session, setup)
    ws, _, users, metadata = setup
    service.authorization_snapshot(db_session, row, user_id=users[0].id)
    with SessionLocal() as admin:
        if change == "membership":
            admin.query(WorkspaceMember).filter_by(workspace_id=ws.id, user_id=users[0].id).delete()
        elif change == "destroyed":
            admin.query(SecretVersion).filter_by(secret_id=metadata["id"]).update(
                {"destroyed_at": runs.utcnow()}
            )
        else:
            other = admin.get(type(row), row.id)
            other.disabled_at = runs.utcnow()
        admin.commit()
    with pytest.raises(Exception):
        service.authorization_snapshot(db_session, row, user_id=users[0].id)


@pytest.mark.parametrize("change", ["revoke", "expire"])
def test_oauth_grant_cannot_outlive_revocation_or_expiry(db_session, setup, change):
    row = create(db_session, setup)
    grant, _ = personal(db_session, setup, row)
    user = setup[2][1]
    service.authorization_snapshot(db_session, row, user_id=user.id)
    with SessionLocal() as admin:
        other = admin.get(ConnectorGrant, grant.id)
        if change == "revoke":
            other.revoked_at = runs.utcnow()
        else:
            other.expires_at = runs.utcnow() - timedelta(seconds=1)
        admin.commit()
    with pytest.raises(service.ConnectionError, match="CONSENT_REQUIRED"):
        service.authorization_snapshot(db_session, row, user_id=user.id)


def test_runtime_revocation_stops_child_and_never_publishes(db_session, registered, monkeypatch):
    from app.services import recipe_executions

    row = submit(db_session, registered)
    monkeypatch.setattr(worker, "_load_spec", lambda *a: {"credentials": {}, "network_grants": []})
    state = ["original"]
    monkeypatch.setattr(worker, "_authorization_snapshot", lambda *a: tuple(state))
    monkeypatch.setattr(worker, "_grants_snapshot", lambda *a: [])

    def supervise(*args, **kwargs):
        state[0] = "revoked"
        assert kwargs["should_cancel"]()
        return SimpleNamespace(status="cancelled", error="cancelled", exit_code=None)

    monkeypatch.setattr(recipe_executions, "supervise_harness", supervise)
    result = worker.execute_run(row.id)
    assert result["status"] == "cancelled"
    assert result["error_code"] == "CONNECTOR_AUTHORIZATION_CHANGED"
    db_session.refresh(row)
    assert row.output_json is None


@pytest.mark.parametrize("revoked", ["authorization", "network_grants"])
@pytest.mark.parametrize("moment", ["staging", "running_commit"])
def test_revocation_before_launch_never_starts_child(
    db_session, registered, monkeypatch, revoked, moment
):
    from app.services import recipe_executions
    from app.services.connectors import writes

    row = runs.create_run(
        db_session,
        workspace_id=registered[0].id,
        connection_id=registered[1].id,
        user_id="fixture",
        operation="write_append",
    )
    db_session.commit()
    state = {"authorization": "original", "network_grants": ["approved"]}
    started = []
    monkeypatch.setattr(
        worker,
        "_load_spec",
        lambda *a: {"credentials": {}, "network_grants": ["approved"]},
    )
    monkeypatch.setattr(worker, "_authorization_snapshot", lambda *a: state["authorization"])
    monkeypatch.setattr(worker, "_grants_snapshot", lambda *a: state["network_grants"])

    def revoke():
        state[revoked] = "revoked" if revoked == "authorization" else []

    def stage(*args):
        if moment == "staging":
            revoke()
        return {}, {}

    monkeypatch.setattr(worker, "_stage_write", stage)
    monkeypatch.setattr(writes, "start_execution", lambda *args: started.append("sent"))
    advance = runs.advance_run

    def commit_running(db, identifier, token, status, **kwargs):
        result = advance(db, identifier, token, status, **kwargs)
        if moment == "running_commit" and status == "running":
            revoke()
        return result

    monkeypatch.setattr(runs, "advance_run", commit_running)
    monkeypatch.setattr(
        recipe_executions,
        "supervise_harness",
        lambda *a, **kw: pytest.fail("revoked credentials must never reach the child"),
    )
    result = worker.execute_run(row.id)
    db_session.refresh(row)
    assert row.output_json is None
    if moment == "staging":
        assert started == [] and row.write_started is False
        expected = (
            "CONNECTOR_AUTHORIZATION_CHANGED"
            if revoked == "authorization"
            else "CONNECTOR_NETWORK_GRANT_CHANGED"
        )
        assert result["status"] == "failed" and result["error_code"] == expected
    else:
        assert started == ["sent"] and row.outcome_unknown
        assert result["status"] == "lost"
        assert result["error_code"] == "CONNECTOR_WRITE_OUTCOME_UNKNOWN"


def test_revocation_during_upload_rolls_back_dataset_publication(
    db_session, registered, monkeypatch, tmp_path
):
    row = submit(db_session, registered)
    token = runs.claim_run(db_session, row.id)
    runs.advance_run(db_session, row.id, token, "launching")
    runs.advance_run(db_session, row.id, token, "running")
    current = ["original"]
    monkeypatch.setattr(worker, "_authorization_snapshot", lambda *a: tuple(current))

    def publish(*args):
        current[0] = "revoked"
        return {"dataset": "must-not-be-published"}

    monkeypatch.setattr(worker, "_publish_stream", publish)
    runs.finish_run(
        db_session,
        row.id,
        token,
        status="succeeded",
        publish=lambda: worker._publish_authorized(db_session, row, {}, tmp_path, ("original",)),
    )
    assert row.status == "failed"
    assert row.error_code == "CONNECTOR_AUTHORIZATION_CHANGED"
    assert row.output_json is None


@pytest.fixture()
def delegated(db_session, setup):
    from uuid import uuid4

    from app.models.run import Run
    from app.models.system import System
    from app.models.system_version import SystemVersion

    ws, _, users, _ = setup
    connection = create(db_session, setup)
    grant, _ = personal(db_session, setup, connection)
    system = System(id=str(uuid4()), workspace_id=ws.id, name="Delegated import")
    version = SystemVersion(
        id=str(uuid4()),
        system_id=system.id,
        workspace_id=ws.id,
        version_number=1,
        flow_definition={},
        release_kind="publish",
    )
    db_session.add_all([system, version])
    db_session.flush()
    system.published_flow_version_id = version.id
    db_session.commit()
    delegation = service.create_delegation(
        db_session,
        grant,
        actor=users[1].id,
        system_version_id=version.id,
        expires_at=runs.utcnow() + timedelta(hours=1),
    )
    service.approve_delegation(db_session, delegation, actor=users[0])
    run = Run(
        workspace_id=ws.id,
        system_id=system.id,
        published_flow_version_id=version.id,
        status="running",
    )
    db_session.add(run)
    db_session.commit()
    row = SimpleNamespace(
        workspace_id=ws.id,
        connection_id=connection.id,
        connection_revision=connection.revision,
        user_id=None,
        run_id=run.id,
        system_id=system.id,
        system_version_id=version.id,
        delegation_id=delegation.id,
        operation="preview",
    )
    return row, run, system, delegation, grant


def test_delegated_actor_keeps_personal_identity_and_can_finish_after_flow(
    db_session, setup, delegated
):
    row, run, _, _, _ = delegated
    assert worker._authorization_snapshot(db_session, row)
    run.status = "completed"
    db_session.commit()
    assert worker._authorization_snapshot(db_session, row)
    assert row.user_id is None


@pytest.mark.parametrize(
    "change",
    [
        "run_workspace",
        "run_version",
        "run_actor",
        "run_cancelled",
        "run_failed",
        "system_version",
        "delegation_revoked",
        "delegation_expired",
        "unapproved",
        "grant_revoked",
        "grant_expired",
        "grant_other_workspace",
        "owner_inactive",
        "owner_removed",
        "write",
        "service_credentials",
        "missing_run",
    ],
)
def test_delegation_revalidated_before_each_runtime_boundary(db_session, setup, delegated, change):
    row, run, system, delegation, grant = delegated
    worker._authorization_snapshot(db_session, row)
    # Simulate a different administrator session after the runner cached metadata.
    with SessionLocal() as admin:
        if change.startswith("run_"):
            other = admin.get(type(run), run.id)
            if change == "run_workspace":
                other.workspace_id = setup[1].id
            elif change == "run_version":
                other.published_flow_version_id = None
            elif change == "run_actor":
                other.initiated_by_user_id = setup[2][0].id
            else:
                other.status = change.removeprefix("run_")
        elif change == "system_version":
            admin.get(type(system), system.id).published_flow_version_id = None
        elif change in {"delegation_revoked", "delegation_expired", "unapproved"}:
            other = admin.get(type(delegation), delegation.id)
            if change == "delegation_revoked":
                other.revoked_at = runs.utcnow()
            elif change == "delegation_expired":
                other.expires_at = runs.utcnow() - timedelta(seconds=1)
            else:
                other.approved_at = None
        elif change.startswith("grant_"):
            other = admin.get(type(grant), grant.id)
            if change == "grant_revoked":
                other.revoked_at = runs.utcnow()
            elif change == "grant_expired":
                other.expires_at = runs.utcnow() - timedelta(seconds=1)
            else:
                other.workspace_id = setup[1].id
        elif change == "owner_inactive":
            owner = setup[2][1]
            admin.get(type(owner), owner.id).is_active = False
        elif change == "owner_removed":
            admin.query(WorkspaceMember).filter_by(
                workspace_id=row.workspace_id, user_id=grant.owner_user_id
            ).delete()
        elif change == "service_credentials":
            from app.models.connector_connection import ConnectorConnection

            connection = admin.get(ConnectorConnection, row.connection_id)
            connection.values = {k: v for k, v in connection.values.items() if k != "auth_mode"}
        elif change == "missing_run":
            row.run_id = None
        else:
            row.operation = "write_append"
        admin.commit()
    with pytest.raises(runs.ComputeRunError):
        worker._authorization_snapshot(db_session, row)


def test_delegated_import_uses_current_owner_permission(db_session, setup, delegated):
    row, _, _, _, grant = delegated
    row.operation = "import"
    member = (
        db_session.query(WorkspaceMember)
        .filter_by(
            workspace_id=row.workspace_id,
            user_id=grant.owner_user_id,
        )
        .one()
    )
    member.role_template = "workspace_contributor"
    db_session.commit()
    worker._check_actor(db_session, row)
    member.role_template = "workspace_viewer"
    db_session.commit()
    with pytest.raises(runs.ComputeRunError, match="CONNECTOR_ACTOR_FORBIDDEN"):
        worker._check_actor(db_session, row)
