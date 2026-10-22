"""Projection is a separate execution artifact, not an edit or validation bypass."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.evaluation_campaign import EvaluationCampaign
from app.models.run import Run
from app.models.system_flow_draft import SystemFlowDraft
from app.services import flow_contracts
from app.services.evaluation import projection, qualification
from app.services.run_engine.execution_contract import canonical_flow_sha256
from app.services.systems import flow_workbench
from app.tests.api.test_evaluation_campaigns import setup_campaign


def project(flow, **kwargs):
    return projection.project_flow(flow, expected_sha256=canonical_flow_sha256(flow), **kwargs)


def test_incomplete_draft_is_preserved_and_only_qualified_campaign_accepts_it(
    db_session, monkeypatch
):
    http, body, baseline, workspace, user, system = setup_campaign(
        db_session,
        monkeypatch,
        assertions=[{"id": "result", "path": ["result"], "operator": "equals", "value": "same"}],
    )
    draft = db_session.get(SystemFlowDraft, system.id)
    flow = copy.deepcopy(draft.flow_definition)
    flow["nodes"].append(
        {
            "id": "unfinished",
            "kind": "task",
            "config": {"skill_slug": "not_yet_created"},
        }
    )
    draft.flow_definition, draft.flow_sha256 = flow, canonical_flow_sha256(flow)
    db_session.commit()
    before = (copy.deepcopy(draft.flow_definition), draft.flow_sha256, draft.revision)
    assert http.post("/evaluation/campaigns/preflight", json=body).status_code == 422
    with pytest.raises(flow_workbench.FlowWorkbenchError, match="blocking diagnostics"):
        flow_workbench.prepare_preview(
            db_session,
            system_id=system.id,
            workspace=workspace,
            flow_definition=flow,
            expected_flow_sha256=draft.flow_sha256,
            ingress_id=None,
            ingress_kind=None,
        )
    body["execution_mode"] = "qualified_prefix"
    response = http.post("/evaluation/campaigns/preflight", json=body)
    assert response.status_code == 200, response.text
    plan = response.json()
    proof = plan["projections"]["candidate"]
    assert plan["eligible"] and proof["excluded_node_ids"] == ["unfinished"]
    assert proof["source_flow_sha256"] == draft.flow_sha256
    assert proof["projected_flow_sha256"] == baseline.flow_sha256
    assert proof["source_draft_revision"] == draft.revision
    assert db_session.query(Run).count() == 1
    body["preflight_sha256"] = plan["preflight_sha256"]
    response = http.post("/evaluation/campaigns", json=body)
    assert response.status_code == 201, response.text
    campaign = db_session.get(EvaluationCampaign, response.json()["id"])
    for side in ("baseline", "candidate"):
        run = db_session.get(Run, campaign.results[0][side]["run_id"])
        assert "unfinished" not in {n["id"] for n in run.flow_snapshot["nodes"]}
        assert run.flow_sha256 == baseline.flow_sha256
        if side == "candidate":
            assert run.input_ref["execution"]["source_flow_sha256"] == draft.flow_sha256
            assert run.input_ref["execution"]["source_draft_revision"] == draft.revision
        run.status, run.output_ref = "completed", {"result": "same"}
    db_session.commit()
    result = http.get(f"/evaluation/campaigns/{campaign.id}").json()["results"][0]
    assert result["change"] == "unchanged"
    assert result["baseline"]["verdict"] == result["candidate"]["verdict"] == "passed"
    db_session.refresh(draft)
    assert (draft.flow_definition, draft.flow_sha256, draft.revision) == before


def test_reachable_error_is_still_blocking_and_creates_no_runs(db_session, monkeypatch):
    http, body, baseline, workspace, user, system = setup_campaign(db_session, monkeypatch)
    draft = db_session.get(SystemFlowDraft, system.id)
    flow = copy.deepcopy(draft.flow_definition)
    flow["edges"].append(copy.deepcopy(flow["edges"][0]))
    draft.flow_definition, draft.flow_sha256 = flow, canonical_flow_sha256(flow)
    db_session.commit()
    response = http.post(
        "/evaluation/campaigns/preflight", json={**body, "execution_mode": "qualified_prefix"}
    )
    assert response.status_code == 422
    assert "edge_duplicate" in response.text
    assert db_session.query(Run).count() == 1


def test_preflight_hash_tracks_excluded_source_edits(db_session, monkeypatch):
    http, body, baseline, workspace, user, system = setup_campaign(db_session, monkeypatch)
    body["execution_mode"] = "qualified_prefix"
    initial = http.post("/evaluation/campaigns/preflight", json=body).json()
    draft = db_session.get(SystemFlowDraft, system.id)
    flow = copy.deepcopy(draft.flow_definition)
    flow["nodes"].append({"id": "unfinished", "kind": "task"})
    draft.flow_definition, draft.flow_sha256 = flow, canonical_flow_sha256(flow)
    db_session.commit()
    refreshed = http.post("/evaluation/campaigns/preflight", json=body).json()
    assert (
        initial["projections"]["candidate"]["projected_flow_sha256"]
        == refreshed["projections"]["candidate"]["projected_flow_sha256"]
    )
    assert initial["preflight_sha256"] != refreshed["preflight_sha256"]
    assert (
        http.post(
            "/evaluation/campaigns", json={**body, "preflight_sha256": initial["preflight_sha256"]}
        ).status_code
        == 409
    )
    assert db_session.query(Run).count() == 1


def luma_flow():
    path = (
        Path(__file__).resolve().parents[4]
        / "docs/demo-runs/showcase-ecommerce/fixtures/agentic_controls/reviewed_plan.json"
    )
    return json.loads(path.read_text())["backup"]["flow_definition"]


def test_luma_projection_retains_bound_sources_and_cuts_every_action_after_human():
    source = luma_flow()
    original = copy.deepcopy(source)
    flow, ingress, proof = project(source, ingress_id="source.request", ingress_kind="manual")
    assert source == original
    ids = {node["id"] for node in flow["nodes"]}
    assert {
        "sav.features",
        "sav.prepare",
        "sav.score",
        "loop.investigate",
        "quality.review",
        "hitl.review",
    } <= ids
    assert not {"task.simulate", "sink.receipt", "forecast.predict", "flow.mv95zi21.1"} & ids
    assert len(proof["asset_node_ids"]) == 6
    from app.services.flow_data_sources import bound_data_sources, data_source_issues

    assert not data_source_issues(flow)
    assert len(bound_data_sources(flow, "loop.investigate")) == 6
    assert all(item["node_id"] in ids for item in flow["runtime_contract"]["postgresql_consumers"])
    from app.services.ecommerce.composition import _ingress_operations

    assert _ingress_operations(flow) == {"source.request": "case"}
    assert "task.simulate" not in {
        node["node_id"] for node in qualification.profile(flow, {}, ingress)["nodes"]
    }


@pytest.mark.parametrize("dependency", ["edge", "selector", "legacy_selector"])
def test_executable_dependency_outside_prefix_is_refused(dependency):
    flow = {
        "nodes": [
            {"id": "in", "kind": "source"},
            {"id": "out", "kind": "sink"},
            {"id": "hidden", "kind": "task"},
        ],
        "edges": [{"from": "in", "to": "out"}],
    }
    if dependency == "edge":
        flow["edges"].append({"from": "hidden", "to": "out", "kind": "data"})
    elif dependency == "selector":
        flow["nodes"][1]["config"] = {"inputs_map": {"x": {"node_id": "hidden", "path": ["out"]}}}
    else:
        flow["nodes"][1]["config"] = {"inputs_map": {"x": "hidden.out"}}
    with pytest.raises(flow_workbench.FlowWorkbenchError) as error:
        project(flow)
    assert error.value.code == "EVALUATION_DEPENDENCY_OUTSIDE_PREFIX"


def test_strict_boundary_has_only_an_inert_output_and_retains_frozen_baseline(db_session):
    source = {
        "schema_version": 3,
        "io_mode": "strict",
        "nodes": [
            {"id": "in", "kind": "source"},
            {"id": "gate", "kind": "hitl"},
            {"id": "out", "kind": "sink"},
        ],
        "edges": [{"from": "in", "to": "gate"}, {"from": "gate", "to": "out"}],
    }
    contract = flow_contracts.compile_execution_contract(
        db_session, flow=source, workspace_id=None, runtime_mode="dag_strict"
    )
    baseline = SimpleNamespace(
        flow_snapshot=source, flow_sha256=canonical_flow_sha256(source), execution_contract=contract
    )
    before = copy.deepcopy(contract)
    prepared, proof = projection.prepare_baseline(
        baseline=baseline, system=None, ingress_id="in", ingress_kind="manual"
    )
    assert baseline.execution_contract == before
    assert proof["excluded_node_ids"] == ["out"]
    assert proof["synthetic_output_node_id"]
    assert prepared.contract["ingresses"] == contract["ingresses"]
    assert prepared.contract["nodes"] == contract["nodes"]
    assert prepared.contract["outputs"][0]["node_id"] == proof["synthetic_output_node_id"]
    assert flow_contracts.validate_execution_contract(prepared.contract) == prepared.contract
    profile = qualification.profile(prepared.flow, prepared.contract, prepared.ingress)
    assert profile["eligible"]
    assert proof["synthetic_output_node_id"] not in {n["node_id"] for n in profile["nodes"]}


def test_corrupt_historical_contract_cannot_be_repaired_by_projection(db_session, monkeypatch):
    http, body, baseline, *_ = setup_campaign(db_session, monkeypatch)
    baseline.execution_contract = {**baseline.execution_contract, "contract_sha256": "0" * 64}
    db_session.commit()
    response = http.post(
        "/evaluation/campaigns/preflight", json={**body, "execution_mode": "qualified_prefix"}
    )
    assert response.status_code == 422
    assert db_session.query(Run).count() == 1
