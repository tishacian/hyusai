"""Service windows freeze fresh inputs and dispatch actual published Runs."""

from datetime import timedelta

import pytest

from app.models.run import Run
from app.models.run_dispatch_outbox import RunDispatchOutbox
from app.models.service_contract import ServiceAttempt
from app.models.system_version import SystemVersion
from app.services import governed_assets as assets
from app.services import service_promises as promises
from app.services.run_engine.execution_contract import canonical_flow_sha256
from app.services.service_engine import freeze_inputs, service_tick
from app.services.systems.flow_publication import compile_execution_contract
from app.tests.services.test_service_contracts import NOW, asset, contract
from app.tests.services.test_service_contracts import setup as service_setup


@pytest.fixture
def setup(db_session, tmp_path, monkeypatch):
    return service_setup.__wrapped__(db_session, tmp_path, monkeypatch)


def test_fresh_inputs_are_frozen_and_stale_unqualified_inputs_refused(setup):
    s = setup
    source = asset(s, name="source")
    moment = source.created_at + timedelta(minutes=2)
    assets.record_qualification(
        s.db,
        s.workspace.id,
        assets.asset_ref(source),
        status="qualified",
        policy={"source": "reviewed"},
        evidence={"actual": "observed"},
    )
    c = contract(
        s,
        inputs=[
            {
                "payload_key": "asset_ref",
                "kind": source.kind,
                "logical_key": source.logical_key,
                "max_age_seconds": 300,
            }
        ],
    )
    w = promises.tick(s.db, NOW, workspace_id=s.workspace.id)[0]
    result = freeze_inputs(s.db, w, c, moment)
    assert result["asset_ref"] == assets.asset_ref(source)
    next_source = asset(s, name="source", text="new source")
    assert next_source.id != source.id
    assert freeze_inputs(s.db, w, c, moment + timedelta(minutes=8)) == result
    w.input_snapshot_json = None
    with pytest.raises(assets.GovernanceError, match="NOT_QUALIFIED"):
        freeze_inputs(s.db, w, c, moment)
    assets.record_qualification(
        s.db,
        s.workspace.id,
        assets.asset_ref(next_source),
        status="qualified",
        policy={},
        evidence={},
    )
    with pytest.raises(assets.GovernanceError, match="STALE"):
        freeze_inputs(s.db, w, c, moment + timedelta(days=1))


def test_service_tick_reuses_publication_and_dispatch_outbox_idempotently(setup):
    s = setup
    s.workspace.settings = {
        "features": {
            "service_contracts": True,
            "flow_publication_v1": True,
            "flow_v3_dag_authoritative": True,
        }
    }
    flow = {
        "schema_version": 3,
        "io_mode": "strict",
        "nodes": [
            {
                "id": "daily",
                "kind": "source",
                "config": {
                    "ingress_kind": "schedule",
                    "input_schema": {"type": "object", "additionalProperties": True},
                },
            },
            {"id": "result", "kind": "sink"},
        ],
        "edges": [{"from": "daily", "to": "result", "kind": "data"}],
    }
    s.system.flow_definition = flow
    s.db.flush()
    compiled = compile_execution_contract(s.db, flow, s.workspace)
    v = SystemVersion(
        workspace_id=s.workspace.id,
        system_id=s.system.id,
        version_number=1,
        flow_definition=flow,
        flow_sha256=canonical_flow_sha256(flow),
        execution_contract=compiled,
        release_kind="publish",
        draft_revision=1,
        created_by=s.owner.id,
    )
    s.db.add(v)
    s.db.flush()
    s.system.published_flow_version_id = v.id
    s.system.published_at = NOW
    s.system.published_by = s.owner.id
    contract(s, input_payload={"query": "score today"})
    s.db.commit()
    stats = service_tick(now=NOW)
    assert stats["fired"] == 1
    s.db.expire_all()
    attempt = s.db.query(ServiceAttempt).one()
    run = s.db.get(Run, attempt.run_id)
    assert run.published_flow_version_id == v.id and run.flow_snapshot == flow
    assert run.input_ref["query"] == "score today"
    assert s.db.query(RunDispatchOutbox).filter_by(run_id=run.id).count() == 1
    assert service_tick(now=NOW)["fired"] == 0
    assert s.db.query(Run).count() == 1


def test_requalification_cascades_without_changing_existing_assets(setup):
    s = setup
    a = asset(s)
    child = assets.register_asset(
        s.db,
        s.workspace.id,
        "reference",
        "child",
        {"output": {"value": "derived"}},
        parents=[assets.asset_ref(a)],
    )
    assets.record_qualification(
        s.db, s.workspace.id, assets.asset_ref(child), status="qualified", policy={}, evidence={}
    )
    original_digest = child.digest
    assert (
        assets.mark_for_requalification(
            s.db, s.workspace.id, assets.asset_ref(a), actor=s.owner.id, reason="reference changed"
        )
        == 2
    )
    assert child.digest == original_digest
    assert (
        assets.current_qualification(s.db, s.workspace.id, child.id).status
        == "needs_requalification"
    )
