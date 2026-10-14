"""Typed agent/Flow calls use persisted authority and the actual compute registry."""

import asyncio
from datetime import datetime, timedelta
from uuid import uuid4

import jsonschema
import pytest

from app.core.config import settings
from app.models.compute_run import ComputeRun
from app.models.run import Run
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.workspace import WorkspaceMember
from app.services import compute_runs
from app.services.connectors import connections
from app.services.skills_registry.seed import SEED_SKILLS
from app.services.skills_registry.wrappers import _connector_read_v1, resolve
from app.tests.services import test_connection_registry as fixtures

create, personal = fixtures.create, fixtures.personal


@pytest.fixture()
def setup(db_session, monkeypatch):
    yield from fixtures.setup.__wrapped__(db_session, monkeypatch)


@pytest.fixture()
def call(db_session, setup, monkeypatch):
    connection = create(db_session, setup)
    monkeypatch.setattr(compute_runs, "dispatch_run", lambda db, row: "queued-in-test")
    ctx = {"db": db_session, "workspace_id": setup[0].id, "user_id": setup[2][1].id}

    def invoke(payload=None, **context):
        return asyncio.run(
            _connector_read_v1(
                {
                    "connection_id": connection.id,
                    "operation": "preview",
                    "parameters": {"schema": "public", "table": "sales"},
                    **(payload or {}),
                },
                {**ctx, **context},
            )
        )

    return connection, ctx, invoke


def test_typed_seed_returns_registry_handle_and_later_real_result(db_session, call):
    connection, _, invoke = call
    result = invoke()
    entry = next(s for s in SEED_SKILLS if s["slug"] == "connector_read_v1")
    assert resolve("connector_read_v1") is not None
    jsonschema.validate(result, entry["output_schema"])
    assert result["status"] == "queued" and result["result"] is None
    row = db_session.get(ComputeRun, result["compute_run_id"])
    assert row.connection_id == connection.id and row.input_json["table"] == "sales"
    row.status, row.output_json = "succeeded", {"rows": [{"amount": 1}], "source": "real"}
    db_session.commit()
    result = invoke({"operation": "status", "compute_run_id": row.id, "parameters": {}})
    assert result["result"]["rows"] == [{"amount": 1}]
    jsonschema.validate(result, entry["output_schema"])


@pytest.mark.parametrize(
    "payload",
    [
        {"operation": "write_append"},
        {"workspace_id": "forged"},
        {"user_id": "forged"},
        {"parameters": {"sql": "DELETE FROM sales"}},
        {"parameters": {"limit": True}},
        {"parameters": {"password": "never-echo"}},
        {"operation": "status"},
    ],
)
def test_schema_refuses_identity_sql_source_writes_and_secret_payloads(db_session, call, payload):
    with pytest.raises(ValueError, match="CONNECTOR_PARAMETERS_INVALID"):
        call[2](payload)
    assert db_session.query(ComputeRun).count() == 0


def test_flag_scope_membership_and_import_role_are_checked_before_dispatch(
    db_session, setup, call, monkeypatch
):
    _, _, invoke = call
    monkeypatch.setattr(settings, "connector_framework_enabled", False)
    with pytest.raises(ValueError, match="CONNECTOR_FRAMEWORK_DISABLED"):
        invoke()
    monkeypatch.setattr(settings, "connector_framework_enabled", True)
    with pytest.raises(ValueError, match="CONNECTOR_NOT_FOUND"):
        invoke(workspace_id=setup[1].id)
    member = (
        db_session.query(WorkspaceMember)
        .filter_by(workspace_id=setup[0].id, user_id=setup[2][1].id)
        .one()
    )
    member.role_template = "workspace_viewer"
    db_session.commit()
    with pytest.raises(ValueError, match="CONNECTOR_ACTOR_FORBIDDEN"):
        invoke({"operation": "import"})
    db_session.query(WorkspaceMember).filter_by(
        workspace_id=setup[0].id, user_id=setup[2][1].id
    ).delete()
    db_session.commit()
    with pytest.raises(ValueError):
        invoke()
    assert db_session.query(ComputeRun).count() == 0


def test_run_identity_cannot_be_forged_and_status_is_not_shared(db_session, setup, call):
    _, _, invoke = call
    result = invoke()
    with pytest.raises(ValueError, match="CONNECTOR_RUN_NOT_FOUND"):
        invoke(
            {"operation": "status", "parameters": {}, "compute_run_id": result["compute_run_id"]},
            user_id=setup[2][2].id,
        )
    run = Run(id=str(uuid4()), workspace_id=setup[0].id, initiated_by_user_id=setup[2][1].id)
    db_session.add(run)
    db_session.commit()
    with pytest.raises(ValueError, match="CONNECTOR_ACTOR_FORBIDDEN"):
        invoke(run_id=run.id, user_id=setup[2][0].id)
    result = invoke(run_id=run.id)
    row = db_session.get(ComputeRun, result["compute_run_id"])
    assert row.run_id == run.id and row.node_id is None


def test_system_personal_read_requires_approved_current_delegation(db_session, setup, call):
    connection, _, invoke = call
    grant, _ = personal(db_session, setup, connection)
    system = System(id=str(uuid4()), workspace_id=setup[0].id, name="Reader")
    db_session.add(system)
    db_session.flush()
    version = SystemVersion(
        id=str(uuid4()),
        system_id=system.id,
        workspace_id=setup[0].id,
        version_number=1,
        release_kind="publish",
        flow_definition={},
    )
    db_session.add(version)
    db_session.flush()
    system.published_flow_version_id = version.id
    run = Run(
        id=str(uuid4()),
        workspace_id=setup[0].id,
        system_id=system.id,
        published_flow_version_id=version.id,
        initiated_by_user_id=None,
    )
    db_session.add(run)
    delegation = connections.create_delegation(
        db_session,
        grant,
        actor=setup[2][1].id,
        system_version_id=version.id,
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    db_session.commit()
    context = {"user_id": None, "run_id": run.id, "system_id": system.id}
    with pytest.raises(ValueError, match="CONNECTOR_GRANT_REQUIRED"):
        invoke({"delegation_id": delegation.id}, **context)
    connections.approve_delegation(db_session, delegation, actor=setup[2][0])
    db_session.commit()
    result = invoke({"delegation_id": delegation.id}, **context)
    row = db_session.get(ComputeRun, result["compute_run_id"])
    assert row.user_id is None and row.delegation_id == delegation.id
    delegation.revoked_at = datetime.utcnow()
    db_session.commit()
    with pytest.raises(ValueError, match="CONNECTOR_GRANT_REQUIRED"):
        invoke(
            {
                "operation": "status",
                "parameters": {},
                "compute_run_id": row.id,
                "delegation_id": delegation.id,
            },
            **context,
        )


def test_personal_user_never_borrows_grant(db_session, setup, call):
    connection, _, invoke = call
    personal(db_session, setup, connection, user_index=1)
    with pytest.raises(ValueError, match="CONNECTOR_OAUTH_CONSENT_REQUIRED"):
        invoke(user_id=setup[2][0].id)
    assert db_session.query(ComputeRun).count() == 0


def _flow_context(db, setup):
    run = Run(id=str(uuid4()), workspace_id=setup[0].id, initiated_by_user_id=setup[2][1].id)
    db.add(run)
    db.commit()
    return {"run_id": run.id, "_skill_node_id": "task.connection"}


def test_flow_waits_for_publication_with_no_session_held_during_await(
    db_session, setup, call, monkeypatch, tmp_path
):
    import hashlib

    import pyarrow as pa
    import pyarrow.parquet as pq

    from app.db import base
    from app.models.tabular import TabularDataset
    from app.workers.tasks_connectors import _publish_stream

    context = _flow_context(db_session, setup)
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "dataops_write_delta_enabled", False)
    path = tmp_path / "data.parquet"
    pq.write_table(pa.table({"id": [1, 2]}), path)
    output = {
        "artifact": "data.parquet",
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "row_count": 2,
        "consistency": "snapshot",
    }
    original = base.SessionLocal
    opened = []
    active = []

    class ShortSession:
        def __enter__(self):
            self.db = original()
            active.append(self.db)
            opened.append(self.db)
            return self.db

        def __exit__(self, *args):
            self.db.close()
            active.remove(self.db)

    monkeypatch.setattr(base, "SessionLocal", ShortSession)

    async def complete(_seconds):
        assert not active, "a database session crossed the await"
        row = db_session.query(ComputeRun).filter_by(run_id=context["run_id"]).one()
        assert row.status == "queued" and row.node_id == context["_skill_node_id"]
        row.status = "succeeded"
        row.output_json = _publish_stream(db_session, row, output, tmp_path)
        db_session.commit()

    monkeypatch.setattr(asyncio, "sleep", complete)
    result = call[2]({"operation": "import"}, **context)
    dataset = db_session.query(TabularDataset).filter_by(workspace_id=setup[0].id).one()
    assert result["status"] == "succeeded"
    assert result["result"]["dataset"]["dataset_id"] == dataset.id
    assert result["result"]["dataset"]["rows"] == 2 and dataset.status == "ready"
    assert dataset.lineage_json["compute_run_id"] == result["compute_run_id"]
    assert len(opened) == 2 and not active
    assert db_session.query(ComputeRun).count() == 1
    entry = next(s for s in SEED_SKILLS if s["slug"] == "connector_read_v1")
    jsonschema.validate(result, entry["output_schema"])


def test_flow_cancellation_requests_registry_cancellation(db_session, setup, call, monkeypatch):
    context = _flow_context(db_session, setup)

    async def cancelled(_seconds):
        raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", cancelled)
    with pytest.raises(asyncio.CancelledError):
        call[2](**context)
    row = db_session.query(ComputeRun).populate_existing().one()
    assert row.cancel_requested and row.status == "cancelled"


@pytest.mark.parametrize(
    "change", ["membership", "connection_revision", "run_cancelled", "import_role"]
)
def test_flow_revalidates_current_authority_and_cancels_on_loss(
    db_session, setup, call, monkeypatch, change
):
    context = _flow_context(db_session, setup)

    async def revoke(_seconds):
        if change == "membership":
            db_session.query(WorkspaceMember).filter_by(
                workspace_id=setup[0].id, user_id=setup[2][1].id
            ).delete()
        elif change == "connection_revision":
            call[0].revision += 1
        elif change == "run_cancelled":
            db_session.get(Run, context["run_id"]).status = "cancelled"
        else:
            db_session.query(WorkspaceMember).filter_by(
                workspace_id=setup[0].id, user_id=setup[2][1].id
            ).one().role_template = "workspace_viewer"
        db_session.commit()

    monkeypatch.setattr(asyncio, "sleep", revoke)
    with pytest.raises(ValueError, match="CONNECTOR_|SECRET_SCOPE_VIOLATION"):
        call[2]({"operation": "import"}, **context)
    row = db_session.query(ComputeRun).populate_existing().one()
    assert row.cancel_requested and row.status == "cancelled"


def test_expired_flow_deadline_does_not_dispatch_work(db_session, setup, call):
    import time

    context = _flow_context(db_session, setup)
    with pytest.raises(ValueError, match="CONNECTOR_TIMEOUT"):
        call[2](**context, _run_deadline_monotonic=time.monotonic() - 1)
    assert db_session.query(ComputeRun).count() == 0


def test_flow_obeys_compute_deadline_even_with_longer_flow_budget(
    db_session, setup, call, monkeypatch
):
    context = _flow_context(db_session, setup)

    async def expire(_seconds):
        row = db_session.query(ComputeRun).one()
        row.deadline_at = datetime.utcnow() - timedelta(seconds=1)
        db_session.commit()

    monkeypatch.setattr(asyncio, "sleep", expire)
    with pytest.raises(ValueError, match="CONNECTOR_"):
        call[2](**context)
    assert db_session.query(ComputeRun).populate_existing().one().status == "timed_out"


def test_flow_status_cannot_claim_another_node_result(db_session, setup, call):
    context = _flow_context(db_session, setup)
    handle = call[2](run_id=context["run_id"])
    with pytest.raises(ValueError, match="CONNECTOR_RUN_NOT_FOUND"):
        call[2](
            {"operation": "status", "parameters": {}, "compute_run_id": handle["compute_run_id"]},
            **context,
        )
    assert db_session.query(ComputeRun).one().status == "queued"


def test_flow_terminal_failure_never_passes_null_to_downstream(
    db_session, setup, call, monkeypatch
):
    async def fail(_seconds):
        row = db_session.query(ComputeRun).one()
        row.status, row.error_code = "failed", "CONNECTOR_REMOTE_FAILED"
        db_session.commit()

    monkeypatch.setattr(asyncio, "sleep", fail)
    with pytest.raises(ValueError, match="CONNECTOR_REMOTE_FAILED"):
        call[2](**_flow_context(db_session, setup))


def test_flow_deadline_is_persisted_before_dispatch(db_session, setup, call, monkeypatch):
    import time

    context = _flow_context(db_session, setup)
    before = datetime.utcnow()

    async def cancel_after_observation(_seconds):
        row = db_session.query(ComputeRun).one()
        assert timedelta(seconds=3) < row.deadline_at - before < timedelta(seconds=6)
        raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", cancel_after_observation)
    with pytest.raises(asyncio.CancelledError):
        call[2]({"operation": "import"}, **context, _run_deadline_monotonic=time.monotonic() + 5)
    row = db_session.query(ComputeRun).populate_existing().one()
    assert row.cancel_requested and row.status == "cancelled"
