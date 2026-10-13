"""Regression gates for ports, previews, worker loss and delivery authority."""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import service_contracts as api
from app.core.config import settings
from app.models.recipe import RecipeExecution
from app.models.tabular import TabularDataset
from app.services import governed_assets as assets
from app.services.dataops.preparation import compile_inputs, preview_preparation, submit_preparation
from app.services.dataops.preview import infer_schema
from app.services.dataops.storage import (
    materialize_files,
    settle_files,
    write_batches,
)
from app.services.dataops.watchdog import sweep
from app.services.outcome.derive import _extract_confidence
from app.services.recipe_executions import request_cancel
from app.services.run_engine.dag import (
    DagGraph,
    WalkerState,
    _apply_graph_owned_config,
    _merge_predecessor_outputs,
)
from app.services.secrets import registry
from app.services.service_engine import freeze_inputs
from app.tests.services.test_dataops_preparation import plane as plane_fixture
from app.tests.services.test_dataops_preparation import spec
from app.tests.services.test_service_contracts import (
    asset,
    candidate,
    window,
)
from app.tests.services.test_service_contracts import (
    setup as setup_fixture,
)


@pytest.fixture
def plane(db_session, monkeypatch, tmp_path):
    return plane_fixture.__wrapped__(db_session, monkeypatch, tmp_path)


@pytest.fixture
def setup(db_session, tmp_path, monkeypatch):
    return setup_fixture.__wrapped__(db_session, tmp_path, monkeypatch)


@pytest.mark.parametrize("mode", ["strict", "overlay"])
def test_split_ports_are_selected_for_every_consumer(mode):
    graph = DagGraph.from_flow_definition(
        {
            "io_mode": mode,
            "nodes": [
                {"id": "split", "kind": "task", "config": {"skill_slug": "data_prep_v1"}},
                {"id": "score", "kind": "task", "config": {"skill_slug": "ml_batch_score_v1"}},
            ],
            "edges": [{"from": "split", "to": "score", "kind": "data", "from_port": "test"}],
        }
    )
    state = WalkerState(
        node_outputs={
            "split": {
                "dataset_id": "train",
                "outputs": {"train": {"dataset_id": "train"}, "test": {"dataset_id": "test"}},
            }
        }
    )
    assert _merge_predecessor_outputs(graph, state, "score") == {"dataset_id": "test"}
    graph.in_edges["score"][0].from_port = None
    with pytest.raises(ValueError, match="PORT_REQUIRED"):
        _merge_predecessor_outputs(graph, state, "score")


def test_conflicting_graph_config_is_rejected():
    graph = DagGraph.from_flow_definition(
        {
            "nodes": [
                {
                    "id": "prep",
                    "kind": "task",
                    "config": {
                        "skill_slug": "data_prep_v1",
                        "data_prep": {"spec": 1},
                        "params": {"data_prep": {"spec": 2}},
                    },
                }
            ]
        }
    )
    with pytest.raises(ValueError, match="GRAPH_CONFIG_CONFLICT"):
        _apply_graph_owned_config(
            graph.nodes["prep"],
            {},
            key="_data_prep",
            slugs=frozenset({"data_prep_v1"}),
            param_keys=("data_prep",),
        )


def test_cancel_queued_retires_reserved_outputs(db_session, plane, monkeypatch):
    ws, data = plane
    monkeypatch.setattr(settings, "worker_eager_mode", False)
    from app.workers.celery_app import celery_app

    monkeypatch.setattr(celery_app, "send_task", lambda *a, **k: SimpleNamespace(id="queued-probe"))
    monkeypatch.setattr(celery_app.control, "revoke", lambda *a, **k: None)
    row = submit_preparation(
        db_session, workspace_id=ws.id, spec=spec(), inputs={"in": {"dataset_id": data.id}}
    )
    request_cancel(db_session, row)
    assert row.status == "cancelled"
    assert all(
        db_session.get(TabularDataset, i).status == "failed"
        for i in row.input_json["outputs"].values()
    )


def test_watchdog_cannot_be_starved_by_other_recipe_types(db_session, plane):
    ws, _ = plane
    now = datetime.utcnow()
    old = now - timedelta(hours=2)
    unrelated = RecipeExecution(
        id=str(uuid4()),
        workspace_id=ws.id,
        status="queued",
        created_at=old,
        input_json={"kind": "python_recipe"},
        timeout_s=1,
    )
    lost = RecipeExecution(
        id=str(uuid4()),
        workspace_id=ws.id,
        status="running",
        created_at=old,
        started_at=old,
        input_json={"kind": "data_prep", "outputs": {}},
        timeout_s=1,
    )
    db_session.add_all([unrelated, lost])
    db_session.commit()
    assert sweep(db_session, now=now, workspace_id=ws.id, limit=1) == [lost.id]
    assert lost.status == "failed" and lost.cancel_requested and unrelated.status == "queued"


def test_compile_and_preview_never_materialize_source_dataset(db_session, plane, monkeypatch):
    ws, data = plane
    import app.services.dataops.storage as storage

    monkeypatch.setattr(
        storage, "materialize_files", lambda *a, **k: pytest.fail("full dataset fetched by preview")
    )
    compiled, inputs = compile_inputs(db_session, ws.id, spec(), {"in": {"dataset_id": data.id}})
    schema = infer_schema(compiled, inputs, spec())
    assert {f["name"] for f in schema} == {"id", "value", "group"}
    preview = preview_preparation(
        db_session, workspace_id=ws.id, spec=spec(), inputs={"in": {"dataset_id": data.id}}
    )
    assert preview["sample"] and preview["sample_metadata"]["inputs"]["in"]["rows"] == 20


def test_zero_row_delta_output_remains_a_valid_immutable_version(db_session, plane, tmp_path):
    ws, _ = plane
    from app.services.tabular_datasets import reserve_frame

    target = reserve_frame(
        db_session,
        workspace_id=ws.id,
        name="Empty partition",
        source="transform",
        produced_by="data_prep_v1",
        commit=False,
    )
    schema = pa.schema([("id", pa.int64())])
    root = tmp_path / "empty-delta"
    files = write_batches(root, [], schema=schema, delta=True)
    settle_files(db_session, target, files, delta_root=root)
    paths = materialize_files(target, tmp_path / "restore")
    assert (
        target.status == "ready"
        and target.row_count == 0
        and pq.read_table(paths[0]).schema == schema
    )


def test_hash_uses_only_dedicated_versioned_salt_without_persisting_value(
    db_session, plane, monkeypatch
):
    ws, data = plane
    monkeypatch.setattr(settings, "secret_registry_fernet_key", Fernet.generate_key().decode())
    meta = registry.create(
        db_session,
        scope="workspace",
        workspace_id=ws.id,
        name="hash-salt",
        value="a" * 32,
        actor="test",
        metadata={"purpose": "dataops_hash_salt"},
    )
    salt = meta["ref"] + "#1"
    config = spec(
        steps=[
            {
                "action": "hash",
                "params": {"columns": ["id"], "output": "anonymous_id", "salt_secret_ref": salt},
            }
        ]
    )
    row = submit_preparation(
        db_session, workspace_id=ws.id, spec=config, inputs={"in": {"dataset_id": data.id}}
    )
    assert row.status == "succeeded", row.error
    assert "a" * 32 not in json.dumps(row.input_json) and "a" * 32 not in json.dumps(
        row.output_json
    )
    bad = registry.create(
        db_session,
        scope="workspace",
        workspace_id=ws.id,
        name="password",
        kind="password",
        value="b" * 32,
        actor="test",
    )
    from app.services.dataops.secrets import hash_parameters

    config.steps[0].params["salt_secret_ref"] = bad["ref"] + "#1"
    with pytest.raises(ValueError, match="SALT_PURPOSE"):
        hash_parameters(config, db_session, workspace_id=ws.id)


def test_invalidated_input_is_refused_even_after_snapshot_frozen(setup):
    s = setup
    source = asset(s, name="reference")
    assets.record_qualification(
        s.db, s.workspace.id, assets.asset_ref(source), status="qualified", policy={}, evidence={}
    )
    c, w = window(
        s,
        inputs=[
            {
                "payload_key": "reference",
                "kind": source.kind,
                "logical_key": source.logical_key,
                "max_age_seconds": 86400,
            }
        ],
    )
    freeze_inputs(s.db, w, c, source.created_at + timedelta(seconds=1))
    assets.mark_for_requalification(
        s.db, s.workspace.id, assets.asset_ref(source), actor=s.owner.id, reason="changed reference"
    )
    with pytest.raises(assets.GovernanceError, match="QUALIFICATION_CHANGED"):
        freeze_inputs(s.db, w, c, source.created_at + timedelta(seconds=2))


def test_typed_judge_unknown_confidence_dominates_other_outputs():
    invocations = [
        SimpleNamespace(skill_slug="llm", output_ref={"confidence": 0.99}),
        SimpleNamespace(
            skill_slug="evaluate_v2",
            output_ref={
                "schema_version": 2,
                "confidence": None,
                "answers": {"score": {"value": 100}},
            },
        ),
    ]
    assert _extract_confidence(invocations) is None


def test_candidate_files_are_bound_to_the_reviewed_revision(setup):
    s = setup
    _, w, a, _, _ = candidate(s)
    s.db.commit()
    app = FastAPI()
    app.include_router(api.router, prefix="/service-contracts")
    app.dependency_overrides[api.get_db] = lambda: s.db
    app.dependency_overrides[api.get_current_workspace] = lambda: s.workspace
    app.dependency_overrides[api.get_current_user] = lambda: s.owner
    client = TestClient(app)
    path = f"/service-contracts/windows/{w.id}/objects/0"
    assert client.get(path).status_code == 422
    assert (
        client.get(
            path, params={"expected_asset_digest": "0" * 64, "expected_fence": w.fence}
        ).status_code
        == 409
    )
    response = client.get(
        path, params={"expected_asset_digest": a.digest, "expected_fence": w.fence}
    )
    assert response.status_code == 200 and response.content == b"verified evidence"
    assert response.headers["x-asset-digest"] == a.digest
    assert (
        client.post(
            "/service-contracts/assets",
            json={
                "kind": "reference",
                "logical_key": "forged",
                "manifest": {"type": "typed_calibration_annotation"},
            },
        ).status_code
        == 422
    )


@pytest.mark.parametrize("status", [None, "review_required", "rejected"])
def test_optional_qualification_is_preserved_on_retry(setup, status):
    s = setup
    source = asset(s, name="optional-source")
    if status:
        assets.record_qualification(
            s.db, s.workspace.id, assets.asset_ref(source),
            status=status, policy={}, evidence={},
        )
    c, w = window(s, inputs=[{
        "payload_key": "source", "kind": source.kind,
        "logical_key": source.logical_key, "require_qualified": False,
    }])
    moment = source.created_at + timedelta(seconds=1)
    frozen = freeze_inputs(s.db, w, c, moment)
    assert freeze_inputs(s.db, w, c, moment + timedelta(seconds=1)) == frozen
    assets.mark_for_requalification(
        s.db, s.workspace.id, assets.asset_ref(source),
        actor=s.owner.id, reason="source changed after freezing",
    )
    with pytest.raises(assets.GovernanceError, match="QUALIFICATION_CHANGED"):
        freeze_inputs(s.db, w, c, moment + timedelta(seconds=2))


def test_invalidated_source_cannot_become_a_new_candidate(setup):
    from app.services.service_engine import _dataset_asset

    s = setup
    source = asset(s, name="source-before-run")
    assets.record_qualification(
        s.db, s.workspace.id, assets.asset_ref(source),
        status="qualified", policy={}, evidence={},
    )
    c, w = window(s, inputs=[{
        "payload_key": "source", "kind": source.kind, "logical_key": source.logical_key,
    }])
    freeze_inputs(s.db, w, c, source.created_at + timedelta(seconds=1))
    assets.mark_for_requalification(
        s.db, s.workspace.id, assets.asset_ref(source),
        actor=s.owner.id, reason="source changed before candidate creation",
    )
    before = s.db.query(assets.AssetVersion).count()
    with pytest.raises(assets.GovernanceError, match="QUALIFICATION_CHANGED"):
        _dataset_asset(s.db, w, SimpleNamespace(output_ref={}))
    assert s.db.query(assets.AssetVersion).count() == before


def test_source_change_blocks_human_qualification_and_publication(setup):
    from app.services import service_promises as promises
    from app.tests.services.test_service_contracts import NOW, review_snapshot

    s = setup
    source = asset(s, name="input-to-revoke")
    assets.record_qualification(
        s.db, s.workspace.id, assets.asset_ref(source),
        status="qualified", policy={}, evidence={},
    )
    c, w, result, q, attempt = candidate(s, inputs=[{
        "payload_key": "source", "kind": source.kind, "logical_key": source.logical_key,
    }])
    freeze_inputs(s.db, w, c, source.created_at + timedelta(seconds=1))
    inspected = review_snapshot(s, w)
    assets.mark_for_requalification(
        s.db, s.workspace.id, assets.asset_ref(source),
        actor=s.owner.id, reason="source changed during Run",
    )
    # No dependency existed when invalidation ran: checking only the new
    # candidate's status would incorrectly allow human qualification.
    assert assets.current_qualification(s.db, s.workspace.id, result.id).id == q.id
    with pytest.raises(assets.GovernanceError, match="QUALIFICATION_CHANGED"):
        promises.review_delivery(
            s.db, s.workspace.id, w.id, reviewer_user_id=s.owner.id,
            accept=True, qualify_candidate=True, note="reviewed bytes",
            **inspected, now=NOW + timedelta(seconds=5),
        )
    assert assets.current_qualification(s.db, s.workspace.id, result.id).id == q.id
    with pytest.raises(assets.GovernanceError, match="QUALIFICATION_CHANGED"):
        promises.publish_delivery(
            s.db, s.workspace.id, w.id, decision_id="irrelevant",
            fence=attempt.fence, lease_token=attempt.lease_token,
            now=NOW + timedelta(seconds=6),
        )


@pytest.mark.parametrize("status", [None, "review_required", "rejected", "needs_requalification"])
def test_human_can_refuse_an_unqualified_candidate(setup, status):
    from app.models.service_contract import DeliveryReceipt, ServiceIncident
    from app.services import service_promises as promises
    from app.tests.services.test_service_contracts import NOW, review_snapshot

    s = setup
    _, w, result, _, _ = candidate(s, qualification=False)
    if status:
        assets.record_qualification(
            s.db, s.workspace.id, assets.asset_ref(result),
            status=status, policy={}, evidence={},
        )
    previous = assets.current_qualification(s.db, s.workspace.id, result.id)
    decision = promises.review_delivery(
        s.db, s.workspace.id, w.id, reviewer_user_id=s.owner.id,
        accept=False, note="Reject this result", **review_snapshot(s, w),
        now=NOW + timedelta(seconds=3),
    )
    assert decision.status == "rejected" and decision.human_confirmed_by == s.owner.id
    assert w.status == "failed"
    assert assets.current_qualification(s.db, s.workspace.id, result.id) == previous
    assert s.db.query(DeliveryReceipt).count() == 0
    assert s.db.query(ServiceIncident).filter_by(code="SERVICE_REVIEW_REJECTED").count() == 1


def test_terminal_run_with_invalidated_inputs_fails_its_attempt(setup):
    from app.models.run import Run
    from app.models.service_contract import ServiceIncident
    from app.services import service_promises as promises
    from app.services.service_engine import reconcile_runs
    from app.tests.services.test_service_contracts import NOW

    s = setup
    source = asset(s, name="source-during-execution")
    assets.record_qualification(
        s.db, s.workspace.id, assets.asset_ref(source),
        status="qualified", policy={}, evidence={},
    )
    c, w = window(s, inputs=[{
        "payload_key": "source", "kind": source.kind, "logical_key": source.logical_key,
    }])
    freeze_inputs(s.db, w, c, source.created_at + timedelta(seconds=1))
    run = Run(
        workspace_id=s.workspace.id, system_id=s.system.id,
        status="completed", started_at=NOW, duration_ms=1000, output_ref={},
    )
    s.db.add(run)
    s.db.flush()
    attempt = promises.claim_window(
        s.db, s.workspace.id, w.id, worker_id="run-worker", run_id=run.id, now=NOW,
    )
    assets.mark_for_requalification(
        s.db, s.workspace.id, assets.asset_ref(source), actor=s.owner.id,
        reason="source changed before run completion",
    )
    reconcile_runs(s.db, s.workspace, now=NOW + timedelta(seconds=2))
    assert w.status == "failed" and w.candidate_ref is None
    assert attempt.status == "failed"
    assert attempt.error_code == "SERVICE_INPUT_QUALIFICATION_CHANGED"
    assert s.db.query(ServiceIncident).filter_by(code=attempt.error_code).count() == 1
