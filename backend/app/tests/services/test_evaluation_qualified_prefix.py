"""Campaign boundaries use real ledgers and isolated artifacts, never caller dry-run flags."""

import copy
import importlib.util
import json
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

from app.core.config import settings
from app.models.decision import Decision
from app.models.evaluation_campaign import EvaluationCampaign
from app.models.run import Run, SkillInvocation
from app.models.tabular import TabularDataset
from app.services.evaluation import campaigns, qualification
from app.services.tabular_datasets import register_frame
from app.tests.api.test_evaluation_campaigns import setup_campaign


def qualified_campaign(db, monkeypatch, *, repetitions=1):
    http, body, reference, workspace, user, system = setup_campaign(db, monkeypatch)
    body.update(execution_mode="qualified_prefix", repeat_count=repetitions)
    preview = http.post("/evaluation/campaigns/preflight", json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()["eligible"]
    body["preflight_sha256"] = preview.json()["preflight_sha256"]
    response = http.post("/evaluation/campaigns", json=body)
    assert response.status_code == 201, response.text
    return http, body, db.get(EvaluationCampaign, response.json()["id"]), workspace


def test_preflight_is_read_only_and_two_repetitions_keep_all_runs(db_session, monkeypatch):
    http, body, baseline, workspace, user, system = setup_campaign(db_session, monkeypatch)
    from app.models.evaluation_campaign import EvaluationSuite
    from app.models.system_flow_draft import SystemFlowDraft

    suite = db_session.get(EvaluationSuite, body["suite_id"])
    suite.cases = [
        {"id": str(i), "input_ref": {"case": str(i)}, "assertions": []} for i in range(12)
    ]
    db_session.commit()
    draft = db_session.get(SystemFlowDraft, system.id)
    original = copy.deepcopy(draft.flow_definition)
    body.update(execution_mode="qualified_prefix", repeat_count=2)
    plan = http.post("/evaluation/campaigns/preflight", json=body).json()
    assert plan["planned_runs"] == 48
    assert db_session.query(Run).count() == 1
    body["preflight_sha256"] = plan["preflight_sha256"]
    result = http.post("/evaluation/campaigns", json=body)
    assert result.status_code == 201, result.text
    assert len(result.json()["results"]) == 24
    assert db_session.query(Run).count() == 49
    assert draft.flow_definition == original
    assert http.post("/evaluation/campaigns", json=body).json()["id"] == result.json()["id"]
    assert db_session.query(Run).count() == 49


def test_unreviewed_or_changed_preflight_cannot_dispatch(db_session, monkeypatch):
    http, body, *_ = setup_campaign(db_session, monkeypatch)
    body.update(execution_mode="qualified_prefix", preflight_sha256="0" * 64)
    assert http.post("/evaluation/campaigns", json=body).status_code == 409
    assert db_session.query(Run).count() == 1


def test_luma_prefix_includes_real_dataops_ml_and_stops_before_receipt():
    path = (
        Path(__file__).resolve().parents[4]
        / "docs/demo-runs/showcase-ecommerce/fixtures/agentic_controls/reviewed_plan.json"
    )
    flow = json.loads(path.read_text())["publication_candidate"]
    contract = {"nodes": {}}
    for node in flow["nodes"]:
        config = node.get("config") or {}
        binding = {"skill_slug": config.get("skill_slug")}
        if node["kind"] == "agent_loop":
            binding["tool_contract"] = {
                "nodes": {slug: {"skill_slug": slug} for slug in config["skill_allowlist"]}
            }
        contract["nodes"][node["id"]] = binding
    result = qualification.profile(flow, contract, {"source_node_id": "source.request"})
    assert result["eligible"], result["issues"]
    by_id = {node["node_id"]: node for node in result["nodes"]}
    for key in ("sav.features", "sav.prepare", "sav.score", "quality.review"):
        assert by_id[key]["execution_mode"] == "isolated_compute"
    assert by_id["hitl.review"]["execution_mode"] == "human_boundary"
    assert "task.simulate" not in by_id
    assert "forecast.predict" not in by_id
    assert "flow.mv95zi21.1" not in by_id


def test_authored_alias_cannot_disguise_a_write_or_delegate():
    flow = {
        "nodes": [
            {"id": "source", "kind": "source"},
            {
                "id": "agent",
                "kind": "agent_loop",
                "config": {"skill_slug": "decide_next_v1", "skill_allowlist": ["ws.hidden"]},
            },
        ],
        "edges": [{"from": "source", "to": "agent"}],
    }
    contract = {
        "nodes": {
            "agent": {
                "skill_slug": "decide_next_v1",
                "tool_contract": {
                    "nodes": {
                        "ws.hidden": {
                            "executor": {
                                "kind": "registry_call",
                                "params": {"skill_slug": "ecommerce_resolution_simulate_v1"},
                            }
                        }
                    }
                },
            }
        }
    }
    result = qualification.profile(flow, contract)
    assert result["issues"][0]["code"] == "EVALUATION_AGENT_TOOL_UNQUALIFIED"
    flow["nodes"][1]["kind"] = "subflow"
    assert not qualification.profile(flow, contract)["eligible"]


def test_runtime_guard_rejects_forged_binding_and_unqualified_tool(db_session, monkeypatch):
    _, _, campaign, _ = qualified_campaign(db_session, monkeypatch)
    run = db_session.get(Run, campaign.results[0]["candidate"]["run_id"])
    run.status = "running"
    with pytest.raises(ValueError, match="INVOCATION_NOT_QUALIFIED"):
        qualification.authorize_invocation(
            db_session, run, node_id="result", skill_slug="ecommerce_resolution_simulate_v1"
        )
    run.evaluation_binding = {**run.evaluation_binding, "side": "baseline"}
    with pytest.raises(ValueError, match="BINDING_INVALID"):
        qualification.bound_profile(db_session, run)


def test_human_boundary_preserves_output_proof_without_approving(db_session, monkeypatch):
    _, _, campaign, workspace = qualified_campaign(db_session, monkeypatch)
    run = db_session.get(Run, campaign.results[0]["candidate"]["run_id"])
    flow = copy.deepcopy(run.flow_snapshot)
    flow["nodes"].append({"id": "review", "kind": "hitl"})
    flow["edges"].append({"from": "result", "to": "review"})
    run.flow_snapshot = flow
    frozen = qualification.profile(flow, run.execution_contract)
    campaign.snapshot = {
        **campaign.snapshot,
        "execution_profiles": {**campaign.snapshot["execution_profiles"], "candidate": frozen},
    }
    run.evaluation_binding = {
        **run.evaluation_binding,
        "profile_sha256": qualification.digest(frozen),
    }
    decision = Decision(
        workspace_id=workspace.id,
        target_id=run.id,
        scope="run",
        kind="hitl_approval",
        title="Review",
    )
    db_session.add(decision)
    db_session.flush()
    run.status = "hitl_pending"
    run.checkpoints = [{"kind": "hitl_pause", "node_id": "review", "decision_id": decision.id}]
    proof = SkillInvocation(
        run_id=run.id,
        skill_slug="ecommerce_resolution_propose_v1",
        status="completed",
        output_ref={"summary": "Ask the carrier"},
        started_at=datetime.utcnow(),
    )
    db_session.add(proof)
    db_session.commit()
    outcome = qualification.finish_at_human_gate(db_session, run)
    assert outcome["status"] == "cancelled"
    assert decision.status == "rejected"
    assert decision.human_confirmed_by is None and decision.approved_by is None
    case = {
        "expected_termination": "human_gate",
        "output_selector": {"skill_slug": proof.skill_slug, "path": ["summary"]},
        "assertions": [{"id": "text", "operator": "contains", "path": [], "value": "carrier"}],
        "trajectory_assertions": [{"id": "human", "operator": "human_gate"}],
    }
    result = campaigns.case_result(run, case, qualified=True)
    assert result["verdict"] == "passed"
    assert result["termination"] == "human_gate"
    assert result["output_invocation_id"] == proof.id
    assert result["output_ref"] == "Ask the carrier"


def test_dataset_namespaces_cannot_advance_the_business_version(db_session, monkeypatch, tmp_path):
    _, _, campaign, workspace = qualified_campaign(db_session, monkeypatch, repetitions=2)
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "dataops_write_delta_enabled", False)
    business = register_frame(
        db_session, workspace_id=workspace.id, name="Same name", frame=pl.DataFrame({"n": [1]})
    )
    qa = []
    for result in campaign.results:
        for side in ("baseline", "candidate"):
            run = db_session.get(Run, result[side]["run_id"])
            qa.append(
                register_frame(
                    db_session,
                    workspace_id=workspace.id,
                    name="Same name",
                    frame=pl.DataFrame({"n": [1]}),
                    run_id=run.id,
                    node_id="facts",
                )
            )
    assert len({row.slug for row in qa}) == 4
    assert all(
        row.evaluation_campaign_id == campaign.id and row.name == business.name for row in qa
    )
    assert all(row.slug != business.slug and row.version == 1 for row in qa)
    assert (
        db_session.query(TabularDataset)
        .filter(TabularDataset.evaluation_campaign_id.is_(None))
        .count()
        == 1
    )


def test_membrane_held_output_cannot_be_copied_into_evaluation(db_session, monkeypatch):
    _, _, campaign, _ = qualified_campaign(db_session, monkeypatch)
    run = db_session.get(Run, campaign.results[0]["candidate"]["run_id"])
    run.status, run.output_ref = "cancelled", {"restricted": "held"}
    run.checkpoints = [
        {"kind": "hitl_pause", "membrane_egress": True},
        {"kind": "evaluation_boundary", "boundary": "policy_gate"},
    ]
    assert qualification.selected_output(run, {}) == (None, None)
    result = campaigns.case_result(run, {"expected_termination": "human_gate"}, qualified=True)
    assert result["termination"] == "policy_gate" and result["verdict"] == "unevaluated"
    assert not qualification.trajectory_results(run, [{"id": "human", "operator": "human_gate"}])[
        0
    ]["passed"]


def test_cross_campaign_input_and_business_settlement_are_refused(
    db_session, monkeypatch, tmp_path
):
    from app.services.evaluation.isolation import validate_inputs
    from app.services.tabular_datasets import TabularError, reserve_frame

    _, _, campaign, workspace = qualified_campaign(db_session, monkeypatch)
    run = db_session.get(Run, campaign.results[0]["candidate"]["run_id"])
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    business = reserve_frame(db_session, workspace_id=workspace.id, name="Business")
    with pytest.raises(TabularError, match="does not belong"):
        register_frame(
            db_session,
            workspace_id=workspace.id,
            name="Business",
            into=business,
            frame=pl.DataFrame({"value": [1]}),
            run_id=run.id,
        )
    qa = reserve_frame(db_session, workspace_id=workspace.id, name="QA", run_id=run.id)
    with pytest.raises(ValueError, match="INPUT_SCOPE_INVALID"):
        validate_inputs(db_session, run_id=None, workspace_id=workspace.id, datasets=[qa])


def test_completed_campaign_without_authored_checks_stays_unevaluated(db_session, monkeypatch):
    _, _, campaign, _ = qualified_campaign(db_session, monkeypatch)
    run = db_session.get(Run, campaign.results[0]["candidate"]["run_id"])
    run.status = "completed"
    assert campaigns.case_result(run, {}, qualified=True)["verdict"] == "unevaluated"


@pytest.mark.parametrize("answer_format", ["text", "json"])
def test_giskard_uses_all_retained_human_boundary_outputs_and_unique_admission_keys(
    db_session, monkeypatch, answer_format
):
    from types import SimpleNamespace

    from app.models.evaluation_campaign import EvaluationSuite
    from app.models.knowledge_collection import KnowledgeCollection
    from app.models.workspace_job import WorkspaceJob
    from app.services.evaluation import giskard_adapter
    from app.services.rag.index.factory import VectorDBFactory

    http, body, _, workspace, _, system = setup_campaign(db_session, monkeypatch)
    collection = KnowledgeCollection(
        id="qa-corpus",
        workspace_id=workspace.id,
        slug="qa-corpus",
        name="QA",
        vector_collection_name="qa-corpus",
        artifact_prefix="qa",
        status="ready",
    )
    db_session.add(collection)
    db_session.flush()
    suite = db_session.get(EvaluationSuite, body["suite_id"])
    suite.corpus_manifest = campaigns.corpus_manifest(db_session, workspace.id, [collection.id])
    suite.cases = [
        {
            **suite.cases[0],
            "question": "What action?",
            "reference_answer": "Ask the carrier",
            "expected_termination": "human_gate",
            "answer_format": answer_format,
            "output_selector": {
                "skill_slug": "ecommerce_resolution_propose_v1",
                "path": ["summary"] if answer_format == "text" else [],
            },
            "trajectory_assertions": [{"id": "human", "operator": "human_gate"}],
        }
    ]
    db_session.commit()
    body.update(execution_mode="qualified_prefix", repeat_count=2)
    body["preflight_sha256"] = http.post("/evaluation/campaigns/preflight", json=body).json()[
        "preflight_sha256"
    ]
    campaign = http.post("/evaluation/campaigns", json=body).json()
    for pair in campaign["results"]:
        for side in ("baseline", "candidate"):
            run = db_session.get(Run, pair[side]["run_id"])
            run.status, run.output_ref = (
                "cancelled",
                {"wrong": "Whole-run output must not be evaluated"},
            )
            run.checkpoints = [{"kind": "evaluation_boundary", "boundary": "human_gate"}]
            db_session.add(
                SkillInvocation(
                    run_id=run.id,
                    skill_slug="ecommerce_resolution_propose_v1",
                    status="completed",
                    output_ref={"summary": f"{side} attempt {pair['repetition_index']}"},
                )
            )
    db_session.commit()
    monkeypatch.setattr(
        "app.services.model_plane.execution.resolve_model_execution",
        lambda *a, **k: SimpleNamespace(
            provider="openai", model="gpt-4o-mini", _api_key="test-private"
        ),
    )
    created = http.post(
        f"/evaluation/campaigns/{campaign['id']}/raget", json={"request_key": "retained"}
    )
    assert created.status_code == 201, created.text

    class Vectors:
        async def list_payloads(self, **kwargs):
            return [{"content": f"Source chunk {i}"} for i in range(8)]

    monkeypatch.setattr(VectorDBFactory, "get_db", lambda *a, **k: Vectors())
    monkeypatch.setattr("app.db.base.SessionLocal", lambda: db_session)
    attempts = []

    def evaluate(**kwargs):
        attempts.append(kwargs)
        return {"cases": kwargs["evaluation_cases"], "method": "test_evaluator"}

    monkeypatch.setattr(giskard_adapter, "generate_isolated", evaluate)
    outcome = campaigns.run_generation_job(created.json()["id"])
    assert outcome["status"] == "completed"
    assert len(attempts) == 4
    expected = {
        f"{side} attempt {index}" for side in ("baseline", "candidate") for index in range(2)
    }
    if answer_format == "json":
        expected = {json.dumps({"summary": text}, sort_keys=True) for text in expected}
    assert {attempt["evaluation_cases"][0]["agent_answer"] for attempt in attempts} == expected
    assert len({attempt["usage_context"]["request_key"] for attempt in attempts}) == 4
    assert all(attempt["evaluation_cases"][0]["metadata"]["invocation_id"] for attempt in attempts)
    job = db_session.get(WorkspaceJob, created.json()["id"])
    assert all(
        len(job.result["sides"][side]["repetitions"]) == 2 for side in ("baseline", "candidate")
    )


def test_luma_proposal_is_unreviewed_has_twelve_distinct_inputs_and_valid_cases():
    from pydantic import ValidationError

    from app.api.v1.endpoints.evaluation_campaigns import CaseBody, SuiteBody

    path = (
        Path(__file__).resolve().parents[4]
        / "docs/demo-runs/showcase-ecommerce/fixtures/observability/qa-plan.proposal.json"
    )
    proposal = json.loads(path.read_text())
    spec = importlib.util.spec_from_file_location(
        "build_luma_qa_plan", path.with_name("build_qa_plan.py")
    )
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    assert generator.build("SELECT_LUMA_SYSTEM", []) == proposal
    cases = proposal["suite_draft"]["cases"]
    assert len(cases) == len({case["input_ref"]["claim_id"] for case in cases}) == 12
    assert len({case["case_family"] for case in cases}) == 6
    assert len(cases) * proposal["campaign_template"]["repeat_count"] * 2 == 48
    assert (
        "reviewed" not in proposal["suite_draft"] and proposal["provenance"]["human_review"] is None
    )
    assert all("reference_answer" not in case for case in cases)
    assert all(CaseBody.model_validate(case) for case in cases)
    proposals = [case for case in cases if case["case_family"] != "missing_evidence"]
    assert len(proposals) == 10
    for case in proposals:
        checks = {check["id"]: check for check in case["assertions"]}
        assert checks["expected-amount"]["value"] == (
            "49.90" if checks["expected-action"]["value"] == "refund" else "0"
        )
        assert checks["expected-currency"]["value"] == "EUR"
        assert checks["matching-claim"]["value"] == case["input_ref"]["claim_id"]
        assert checks["current-policy-version"]["value"] == "2"
    for case in cases:
        if case["case_family"] == "missing_evidence":
            assert {check["id"] for check in case["assertions"]} == {"ask-human", "not-completed"}
    with pytest.raises(ValidationError):
        SuiteBody.model_validate(proposal["suite_draft"])


@pytest.mark.parametrize(
    "path,incorrect_value,failed_check",
    [
        (["amount"], "50.00", "expected-amount"),
        (["amount"], 49.9, "expected-amount"),
        (["currency"], "USD", "expected-currency"),
        (["claim_id"], "RC-5004", "matching-claim"),
        (["order_id"], "LM-5004", "matching-order"),
        (["requires_human"], False, "human-required"),
        (["financial_execution"], "real", "simulated-financial-execution"),
        (["missing_references"], ["missing_loss_confirmation"], "no-missing-references"),
        (["resolution_policy", "document_key"], "refund-policy-v1", "current-policy-document"),
        (["resolution_policy", "document_version"], "1", "current-policy-version"),
        (["resolution_policy", "document_sha256"], "0" * 64, "current-policy-digest"),
    ],
)
def test_luma_proposal_rejects_financial_or_provenance_drift(path, incorrect_value, failed_check):
    from app.services.ecommerce.claims import propose
    from app.tests.services.test_ecommerce_claims import case

    proposal = json.loads(
        (
            Path(__file__).resolve().parents[4]
            / "docs/demo-runs/showcase-ecommerce/fixtures/observability/qa-plan.proposal.json"
        ).read_text()
    )
    checks = next(
        item["assertions"]
        for item in proposal["suite_draft"]["cases"]
        if item["input_ref"]["claim_id"] == "RC-5003"
    )
    # Use the real proposal contract for the same confirmed-loss scenario;
    # bind its output to this cohort's identity before evaluating generic checks.
    output = propose(*case(1043))
    output.update(claim_id="RC-5003", order_id="LM-5003")
    assert campaigns.assertion_results(output, checks)["verdict"] == "passed"
    target = output
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = incorrect_value
    result = campaigns.assertion_results(output, checks)
    assert result["verdict"] == "failed"
    assert failed_check in {item["id"] for item in result["assertions"] if item["passed"] is False}
