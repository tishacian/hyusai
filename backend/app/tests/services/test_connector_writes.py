"""Approvals bind one exact target/version; uncertain writes are never replayed."""

from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.models.connector_connection import ConnectorConnection
from app.models.tabular import TabularDataset
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.connectors import writes
from app.services.connectors.profiles import get_profile


@pytest.fixture()
def seeded(db_session, monkeypatch):
    ws = Workspace(id=str(uuid4()), name="Writes", slug="write-tests")
    admin = User(id=str(uuid4()), username="writeadmin", email="wa@example.test")
    member = User(id=str(uuid4()), username="writemember", email="wm@example.test")
    db_session.add_all([ws, admin, member])
    db_session.flush()
    db_session.add_all(
        [
            WorkspaceMember(workspace_id=ws.id, user_id=admin.id, role="owner"),
            WorkspaceMember(workspace_id=ws.id, user_id=member.id, role="member"),
        ]
    )
    conn = ConnectorConnection(
        id=str(uuid4()),
        workspace_id=ws.id,
        name="db",
        profile_key="postgresql",
        profile_version=1,
        values={},
        secret_refs={},
        access="read_write",
        created_by=admin.id,
    )
    dataset = TabularDataset(
        id=str(uuid4()),
        workspace_id=ws.id,
        name="input",
        slug="input",
        status="ready",
        storage_key="immutable/key.parquet",
        version=1,
        schema_json=[{"name": "id", "type": "int64"}],
        row_count=1,
        size_bytes=100,
        lineage_json={"storage": {"format": "parquet", "sha256": "a" * 64}},
    )
    db_session.add_all([conn, dataset])
    db_session.commit()
    profile = get_profile("postgresql")
    profile = profile.model_copy(
        update={
            "capabilities": profile.capabilities.model_copy(
                update={"write_append": True, "write_upsert": True}
            )
        }
    )
    monkeypatch.setattr(writes, "get_profile", lambda key: profile)
    monkeypatch.setattr(writes.compute_runs, "dispatch_run", Mock(return_value="fixture-task"))
    return ws, admin, member, conn, dataset


def prepare(db, s, key="request-1", **changes):
    ws, admin, _, conn, dataset = s
    args = dict(
        workspace_id=ws.id,
        user=admin,
        connection_id=conn.id,
        request_key=key,
        operation="write_append",
        dataset_id=dataset.id,
        parameters={"schema": "public", "table": "scores"},
    )
    return writes.prepare(db, **(args | changes))


def test_exact_contract_and_idempotency_conflict(db_session, seeded):
    ws, admin, _, _, _ = seeded
    row = prepare(db_session, seeded)
    assert prepare(db_session, seeded).id == row.id
    with pytest.raises(writes.WriteError, match="CONNECTOR_IDEMPOTENCY_CONFLICT"):
        prepare(db_session, seeded, parameters={"schema": "public", "table": "other"})
    with pytest.raises(writes.WriteError, match="CONNECTOR_APPROVAL_MISMATCH"):
        writes.approve(
            db_session,
            workspace_id=ws.id,
            user=admin,
            operation_id=row.id,
            contract_digest="a" * 64,
        )
    assert row.state == "prepared"


def test_members_and_readonly_connections_cannot_prepare(db_session, seeded):
    with pytest.raises(writes.WriteError, match="WORKSPACE_PERMISSION_DENIED"):
        prepare(db_session, seeded, user=seeded[2])
    seeded[3].access = "read"
    db_session.flush()
    with pytest.raises(writes.WriteError, match="CONNECTOR_READ_ONLY"):
        prepare(db_session, seeded)


def test_changed_connection_or_dataset_invalidates_approval(db_session, seeded):
    ws, admin, _, conn, dataset = seeded
    row = prepare(db_session, seeded)
    dataset.version = 2
    db_session.flush()
    with pytest.raises(writes.WriteError, match="CONNECTOR_WRITE_CONTRACT_CHANGED"):
        writes.approve(
            db_session,
            workspace_id=ws.id,
            user=admin,
            operation_id=row.id,
            contract_digest=row.contract_digest,
        )
    dataset.version = 1
    conn.revision += 1
    db_session.flush()
    with pytest.raises(writes.WriteError, match="CONNECTOR_CONNECTION_CHANGED"):
        writes.approve(
            db_session,
            workspace_id=ws.id,
            user=admin,
            operation_id=row.id,
            contract_digest=row.contract_digest,
        )


def approved(db, s, key="request-1"):
    row = prepare(db, s, key)
    successful_preview(db, s, row)
    return writes.approve(
        db,
        workspace_id=s[0].id,
        user=s[1],
        operation_id=row.id,
        contract_digest=row.contract_digest,
    )


def successful_preview(db, s, row):
    run = writes.compute_runs.create_run(
        db,
        workspace_id=s[0].id,
        user_id=s[1].id,
        connection_id=s[3].id,
        operation="write_preview",
        parameters={"write_operation_id": row.id},
    )
    run.status = "succeeded"
    run.output_json = {
        "operation_id": row.id,
        "contract_digest": row.contract_digest,
        "dry_run": True,
        "applied": False,
        "write_operation": row.operation,
    }
    db.flush()
    return run


def test_approval_requires_successful_preview_of_the_exact_contract(db_session, seeded):
    row = prepare(db_session, seeded)
    args = dict(
        workspace_id=seeded[0].id,
        user=seeded[1],
        operation_id=row.id,
        contract_digest=row.contract_digest,
    )
    with pytest.raises(writes.WriteError, match="CONNECTOR_WRITE_PREVIEW_REQUIRED"):
        writes.approve(db_session, **args)
    preview = successful_preview(db_session, seeded, row)
    preview.output_json = preview.output_json | {"contract_digest": "f" * 64}
    db_session.flush()
    with pytest.raises(writes.WriteError, match="CONNECTOR_WRITE_PREVIEW_REQUIRED"):
        writes.approve(db_session, **args)
    preview.output_json = preview.output_json | {"contract_digest": row.contract_digest}
    preview.status = "failed"
    db_session.flush()
    with pytest.raises(writes.WriteError, match="CONNECTOR_WRITE_PREVIEW_REQUIRED"):
        writes.approve(db_session, **args)
    preview.status = "succeeded"
    db_session.flush()
    assert writes.approve(db_session, **args).state == "approved"


def test_dispatch_queues_one_identity_and_reserves_target(db_session, seeded):
    ws, admin, _, _, _ = seeded
    row = approved(db_session, seeded)
    writes.dispatch(db_session, workspace_id=ws.id, user=admin, operation_id=row.id)
    run_id = row.compute_run_id
    writes.dispatch(db_session, workspace_id=ws.id, user=admin, operation_id=row.id)
    assert row.compute_run_id == run_id
    assert writes.compute_runs.dispatch_run.call_count == 1
    other = approved(db_session, seeded, "request-2")
    with pytest.raises(writes.WriteError, match="CONNECTOR_TARGET_BUSY"):
        writes.dispatch(db_session, workspace_id=ws.id, user=admin, operation_id=other.id)


def test_lost_write_stays_unknown_and_is_not_reissued(db_session, seeded):
    ws, admin, _, _, _ = seeded
    row = approved(db_session, seeded)
    writes.dispatch(db_session, workspace_id=ws.id, user=admin, operation_id=row.id)
    run = writes.compute_runs.get_run(db_session, ws.id, row.compute_run_id)
    writes.start_execution(db_session, run)
    run.status = "failed"
    run.outcome_unknown = True
    run.error_code = "CONNECTOR_TIMEOUT"
    db_session.commit()
    writes.settle(db_session, run)
    assert row.state == "unknown"
    writes.dispatch(db_session, workspace_id=ws.id, user=admin, operation_id=row.id)
    assert writes.compute_runs.dispatch_run.call_count == 1
    with pytest.raises(writes.WriteError, match="CONNECTOR_APPROVAL_REQUIRED"):
        writes.start_execution(db_session, run)


def test_success_requires_receipt_bound_to_operation(db_session, seeded):
    ws, admin, _, _, _ = seeded
    row = approved(db_session, seeded)
    writes.dispatch(db_session, workspace_id=ws.id, user=admin, operation_id=row.id)
    run = writes.compute_runs.get_run(db_session, ws.id, row.compute_run_id)
    writes.start_execution(db_session, run)
    run.status = "succeeded"
    db_session.commit()
    writes.settle(db_session, run, {"operation_id": "other", "applied": True})
    assert row.state == "unknown"
    writes.settle(
        db_session,
        run,
        {
            "operation_id": row.id,
            "applied": True,
            "contract_digest": row.contract_digest,
            "rows": 1,
        },
    )
    assert row.state == "applied" and row.receipt["rows"] == 1
    from app.models.decision import Decision

    assert db_session.get(Decision, writes._review_id(row.id)).status == "applied"


def test_unknown_review_is_durable_and_abandon_never_replays(db_session, seeded):
    from app.models.decision import Decision

    ws, admin, member, _, _ = seeded
    row = approved(db_session, seeded)
    writes.dispatch(db_session, workspace_id=ws.id, user=admin, operation_id=row.id)
    run = writes.compute_runs.get_run(db_session, ws.id, row.compute_run_id)
    writes.start_execution(db_session, run)
    run.status, run.outcome_unknown = "failed", True
    db_session.commit()
    writes.settle(db_session, run)
    writes.settle(db_session, run)
    db_session.commit()
    review = db_session.get(Decision, writes.view(row)["review_decision_id"])
    assert review.rationale["owner_user_id"] == admin.id
    assert review.rationale["automatic_retry"] is False
    assert review.expires_at is None
    assert db_session.query(Decision).filter_by(id=review.id).count() == 1
    args = dict(
        workspace_id=ws.id,
        user=admin,
        operation_id=row.id,
        contract_digest=row.contract_digest,
        reason="Outcome inspected outside the platform",
        acknowledge_possible_application=True,
    )
    with pytest.raises(writes.WriteError, match="WORKSPACE_PERMISSION_DENIED"):
        writes.abandon_unknown(db_session, **(args | {"user": member}))
    with pytest.raises(writes.WriteError, match="CONNECTOR_UNKNOWN_REVIEW_REQUIRED"):
        writes.abandon_unknown(db_session, **(args | {"acknowledge_possible_application": False}))
    writes.abandon_unknown(db_session, **args)
    assert row.state == "abandoned" and row.receipt["applied"] is None
    assert review.status == "accepted"
    writes.dispatch(db_session, workspace_id=ws.id, user=admin, operation_id=row.id)
    assert writes.compute_runs.dispatch_run.call_count == 1
    # Releasing the target requires an independently prepared and approved intent.
    other = approved(db_session, seeded, "reviewed-new-intent")
    writes.dispatch(db_session, workspace_id=ws.id, user=admin, operation_id=other.id)
    assert writes.compute_runs.dispatch_run.call_count == 2


@pytest.mark.parametrize("snapshot", [None, 2**63 - 1, str(2**63 - 1)])
def test_iceberg_approval_keeps_exact_snapshot_identity(seeded, snapshot):
    conn = seeded[3]
    conn.profile_key = "iceberg_rest"
    params = {
        "schema": "public",
        "table": "scores",
        "expected_snapshot_id": snapshot,
        "expected_schema_id": 0,
        "expected_table_uuid": str(uuid4()),
    }
    assert writes._target(conn, "write_append", params) == {"schema": "public", "table": "scores"}
    assert params["expected_snapshot_id"] == snapshot
    with pytest.raises(writes.WriteError, match="CONNECTOR_TABLE_IDENTITY_REQUIRED"):
        writes._target(conn, "write_append", params | {"expected_schema_id": True})


@pytest.mark.parametrize("snapshot", [True, 0, -1, 2**63, "01", "+1", "1e2", str(2**63)])
def test_iceberg_approval_rejects_ambiguous_snapshot_identity(seeded, snapshot):
    conn = seeded[3]
    conn.profile_key = "iceberg_rest"
    with pytest.raises(writes.WriteError, match="CONNECTOR_TABLE_IDENTITY_REQUIRED"):
        writes._target(
            conn,
            "write_append",
            {
                "schema": "public",
                "table": "scores",
                "expected_snapshot_id": snapshot,
                "expected_schema_id": 0,
                "expected_table_uuid": str(uuid4()),
            },
        )
