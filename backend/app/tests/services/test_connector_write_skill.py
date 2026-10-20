"""Agents can request human review, never bypass it or impersonate a System owner."""

import asyncio
from uuid import uuid4

import jsonschema
import pytest

from app.core.config import settings
from app.models.compute_run import ComputeRun
from app.models.connector_write import ConnectorWrite
from app.models.run import Run
from app.models.system import System
from app.models.system_version import SystemVersion
from app.services.connectors import writes
from app.services.skills_registry.seed import SEED_SKILLS
from app.services.skills_registry.wrappers import _connector_write_request_v1
from app.tests.services import test_connector_writes as fixtures


@pytest.fixture()
def call(db_session, monkeypatch):
    seeded = fixtures.seeded.__wrapped__(db_session, monkeypatch)
    monkeypatch.setattr(settings, "connector_framework_enabled", True)
    ws, admin, _, connection, dataset = seeded
    context = {"db": db_session, "workspace_id": ws.id, "user_id": admin.id}
    payload = {
        "connection_id": connection.id,
        "operation": "write_append",
        "dataset_id": dataset.id,
        "request_key": "delivery-1",
        "parameters": {"schema": "public", "table": "scores"},
    }

    def invoke(values=None, **ctx):
        return asyncio.run(_connector_write_request_v1(payload | (values or {}), context | ctx))

    return seeded, invoke


def test_write_request_only_queues_readonly_preflight_and_keeps_contract_idempotent(
    db_session, call
):
    _, invoke = call
    result = invoke()
    entry = next(s for s in SEED_SKILLS if s["slug"] == "connector_write_request_v1")
    jsonschema.validate(result, entry["output_schema"])
    assert result["approval_required"] is True and result["state"] == "prepared"
    assert invoke()["write_operation_id"] == result["write_operation_id"]
    intent = db_session.get(ConnectorWrite, result["write_operation_id"])
    assert intent.approved_by is None and intent.compute_run_id is None
    assert {row.operation for row in db_session.query(ComputeRun).all()} == {"write_preview"}
    with pytest.raises(ValueError, match="CONNECTOR_IDEMPOTENCY_CONFLICT"):
        invoke({"parameters": {"schema": "public", "table": "other"}})


def test_nonadmin_context_and_payload_impersonation_cannot_prepare(db_session, call):
    seeded, invoke = call
    with pytest.raises(ValueError, match="WORKSPACE_PERMISSION_DENIED"):
        invoke(user_id=seeded[2].id)
    with pytest.raises(ValueError, match="CONNECTOR_PARAMETERS_INVALID"):
        invoke({"user_id": seeded[1].id}, user_id=seeded[2].id)
    with pytest.raises(ValueError, match="CONNECTOR_PARAMETERS_INVALID"):
        invoke({"operation": "approve"})
    assert db_session.query(ConnectorWrite).count() == 0


def test_persisted_run_actor_is_required_and_no_system_write_delegation(db_session, call):
    seeded, invoke = call
    run = Run(id=str(uuid4()), workspace_id=seeded[0].id, initiated_by_user_id=None)
    db_session.add(run)
    db_session.commit()
    with pytest.raises(ValueError, match="CONNECTOR_ACTOR_FORBIDDEN"):
        invoke(run_id=run.id)
    with pytest.raises(ValueError, match="CONNECTOR_ACTOR_FORBIDDEN"):
        invoke(run_id=run.id, user_id=None)
    assert db_session.query(ConnectorWrite).count() == 0


def test_framework_disabled_cannot_prepare(db_session, call, monkeypatch):
    monkeypatch.setattr(settings, "connector_framework_enabled", False)
    with pytest.raises(ValueError, match="CONNECTOR_FRAMEWORK_DISABLED"):
        call[1]()
    assert db_session.query(ConnectorWrite).count() == 0


def test_flow_origin_survives_human_approval_into_delivery_and_reconciliation(db_session, call):
    seeded, invoke = call
    ws, admin = seeded[:2]
    system = System(id=str(uuid4()), workspace_id=ws.id, name="Scoring delivery")
    db_session.add(system)
    db_session.flush()
    version = SystemVersion(
        id=str(uuid4()),
        system_id=system.id,
        workspace_id=ws.id,
        version_number=1,
        release_kind="publish",
        flow_definition={},
    )
    db_session.add(version)
    db_session.flush()
    system.published_flow_version_id = version.id
    flow = Run(
        id=str(uuid4()),
        workspace_id=ws.id,
        system_id=system.id,
        initiated_by_user_id=admin.id,
        published_flow_version_id=version.id,
        flow_snapshot={"nodes": [{"id": "task.request"}]},
    )
    db_session.add(flow)
    db_session.commit()
    with pytest.raises(ValueError, match="CONNECTOR_ORIGIN_INVALID"):
        invoke(run_id=flow.id, _skill_node_id="forged-node")
    result = invoke(run_id=flow.id, _skill_node_id="task.request")
    expected = {
        "run_id": flow.id,
        "node_id": "task.request",
        "system_id": system.id,
        "system_version_id": version.id,
    }
    assert result["contract"]["origin"] == expected
    preview = db_session.get(ComputeRun, result["preview_compute_run_id"])
    assert {key: getattr(preview, key) for key in expected} == expected
    preview.status = "succeeded"
    preview.output_json = {
        "dry_run": True,
        "applied": False,
        "write_operation": "write_append",
        "operation_id": result["write_operation_id"],
        "contract_digest": result["contract_digest"],
    }
    db_session.commit()
    intent = writes.approve(
        db_session,
        workspace_id=ws.id,
        user=admin,
        operation_id=result["write_operation_id"],
        contract_digest=result["contract_digest"],
    )
    writes.dispatch(db_session, workspace_id=ws.id, user=admin, operation_id=intent.id)
    delivery = db_session.get(ComputeRun, intent.compute_run_id)
    assert {key: getattr(delivery, key) for key in expected} == expected
    intent.state = "unknown"
    db_session.commit()
    reconciled = writes.dispatch_reconciliation(
        db_session, workspace_id=ws.id, user=admin, operation_id=intent.id
    )
    reconcile = db_session.get(ComputeRun, reconciled["id"])
    assert {key: getattr(reconcile, key) for key in expected} == expected
