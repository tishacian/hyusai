"""Actual DataOps/ML + canonical AgentLoop campaign; only remote evidence/LLM are test doubles."""

import copy
import json
from pathlib import Path

import pytest

from app.core.config import settings
from app.models.claim_action import ClaimAction
from app.models.evaluation_campaign import EvaluationSuite
from app.models.recipe import RecipeExecution
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system_flow_draft import SystemFlowDraft
from app.models.tabular import MLPrediction, TabularDataset
from app.services.ecommerce import composition
from app.services.evaluation import campaigns
from app.services.run_engine import dag, engine
from app.services.run_engine.execution_contract import canonical_flow_sha256
from app.tests.services.test_ecommerce_composition import (  # noqa: F401
    activate,
    create_run,
    environment,
    luma_artifact,
)


@pytest.mark.parametrize(
    "streaming,early_human,retain_inputs",
    [(False, False, True), (True, False, True), (False, True, True), (True, False, False)],
)
@pytest.mark.asyncio
async def test_qualification_executes_the_hybrid_prefix_and_preserves_business_artifacts(
    db_session, environment, monkeypatch, streaming, early_human, retain_inputs
):
    ws, actor, main, _, model, _, reader = environment
    monkeypatch.setattr(settings, "dataops_enabled", True)
    monkeypatch.setattr(settings, "dataops_write_delta_enabled", False)
    activate(db_session, environment)
    ws.settings = {
        **(ws.settings or {}),
        "ml": {"store_inputs": retain_inputs},
        "features": {
            **((ws.settings or {}).get("features") or {}),
            "ml_score_streaming_enabled": streaming,
            "flow_workbench_v1": True,
            "flow_publication_v1": True,
            "flow_v3_dag_authoritative": True,
        },
    }
    db_session.commit()
    baseline = create_run(db_session, environment, composition.CASE_INGRESS)
    flow = copy.deepcopy(baseline.flow_snapshot)
    fixture = json.loads(
        (
            Path(__file__).resolve().parents[4]
            / "docs/demo-runs/showcase-ecommerce/fixtures/agentic_controls/reviewed_plan.json"
        ).read_text()
    )["publication_candidate"]
    prep = next(n for n in fixture["nodes"] if n["id"] == "sav.prepare")
    original = next(n for n in flow["nodes"] if n["id"] == "sav.prepare")
    original["config"] = copy.deepcopy(prep["config"])
    original["config"].pop("inputs_map", None)
    for slug in ("data_prep_v1", "evaluate_v2"):
        row = db_session.query(Skill).filter_by(slug=slug).first()
        if row is None:
            row = Skill(
                slug=slug,
                version="1",
                name=slug,
                provider="internal",
                input_schema={},
                output_schema={},
                execution={"mode": "async"},
            )
            db_session.add(row)
            db_session.flush()
        main.skill_ids = [*main.skill_ids, row.id]
    loop = next(n for n in flow["nodes"] if n["id"] == "loop.investigate")
    loop["config"]["skill_allowlist"] = ["ecommerce_resolution_propose_v1"]
    loop["config"]["goal"]["done_when"] = ["ecommerce_resolution_propose_v1"]
    # This fixture exercises the runtime boundary, not a provider's judgement quality.
    flow["nodes"].append(
        {
            "id": "quality.review",
            "kind": "task",
            "config": {
                "skill_slug": "evaluate_v2",
                "typed_evaluation": {
                    "questions": [
                        {"key": "grounded", "question": "Is this grounded?", "type": "boolean"}
                    ]
                },
            },
        }
    )
    for edge in flow["edges"]:
        if edge.get("to") == "hitl.review":
            edge["to"] = "quality.review"
    flow["edges"].append({"from": "quality.review", "to": "hitl.review"})
    from app.services.flow_contracts import compile_execution_contract

    contract = compile_execution_contract(
        db_session,
        workspace_id=ws.id,
        runtime_mode="dag_overlay",
        allowed_skill_ids=main.skill_ids,
        flow=flow,
    )
    baseline.flow_snapshot = copy.deepcopy(flow)
    baseline.execution_contract = copy.deepcopy(contract)
    baseline.flow_sha256 = canonical_flow_sha256(flow)
    baseline.status = "completed"
    draft = db_session.get(SystemFlowDraft, main.id)
    draft.flow_definition = copy.deepcopy(flow)
    draft.flow_sha256 = baseline.flow_sha256
    suite = EvaluationSuite(
        workspace_id=ws.id,
        system_id=main.id,
        name="Hybrid prefix",
        revision=1,
        cases=[
            {
                "id": "case",
                "input_ref": {"claim_id": "RC-1042"},
                "expected_termination": "human_gate",
                "output_selector": {"skill_slug": "ecommerce_resolution_propose_v1", "path": []},
                "trajectory_assertions": [
                    {"id": "ml", "operator": "tool_required", "skill_slug": "ml_batch_score_v1"},
                    {"id": "agent", "operator": "tool_required", "skill_slug": "decide_next_v1"},
                    {"id": "judge", "operator": "tool_required", "skill_slug": "evaluate_v2"},
                    {
                        "id": "no-action",
                        "operator": "tool_forbidden",
                        "skill_slug": "ecommerce_resolution_simulate_v1",
                    },
                ],
            }
        ],
        corpus_manifest=[],
        provenance={"reviewed_by": actor.id},
        created_by_user_id=actor.id,
    )
    from app.models.knowledge_collection import KnowledgeCollection

    references = {
        n["config"]["collection_slug"]
        for n in flow["nodes"]
        if (n.get("config") or {}).get("collection_slug")
    }
    for slug in references:
        db_session.add(
            KnowledgeCollection(
                id=slug,
                workspace_id=ws.id,
                slug=slug,
                name=slug,
                vector_collection_name=slug,
                artifact_prefix=slug,
                status="ready",
                document_names=["rules.pdf"],
            )
        )
    db_session.flush()
    suite.corpus_manifest = campaigns.corpus_manifest(db_session, ws.id, list(references))
    if early_human:
        proposal = json.loads(
            (
                Path(__file__).resolve().parents[4]
                / "docs/demo-runs/showcase-ecommerce/fixtures/observability/qa-plan.proposal.json"
            ).read_text()
        )
        suite.cases = [
            next(
                case
                for case in proposal["suite_draft"]["cases"]
                if case["case_family"] == "missing_evidence"
            )
        ]
        loop["config"]["goal"]["done_when"] = ["resolution_ready"]
        baseline.flow_snapshot = copy.deepcopy(flow)
        baseline.flow_sha256 = canonical_flow_sha256(flow)
        baseline.execution_contract = compile_execution_contract(
            db_session,
            workspace_id=ws.id,
            runtime_mode="dag_overlay",
            allowed_skill_ids=main.skill_ids,
            flow=flow,
        )
        draft.flow_definition = copy.deepcopy(flow)
        draft.flow_sha256 = baseline.flow_sha256
    db_session.add(suite)
    db_session.commit()
    resolve = engine.resolve_skill

    async def decide(payload, ctx):
        if early_human:
            return {
                "next_skill": None,
                "done": False,
                "needs_human": True,
                "exit": "ask_human",
                "human_prompt": "Missing carrier proof",
            }
        return {
            "next_skill": "ecommerce_resolution_propose_v1",
            "confidence": 0.9,
            "done": False,
            "needs_human": False,
        }

    async def propose(payload, ctx):
        return {
            "claim_id": "RC-1042",
            "summary": "Review carrier evidence",
            "action": "carrier_investigation",
        }

    async def judge(payload, ctx):
        return {
            "schema_version": 2,
            "evaluation_id": "test-provider-failure",
            "disposition": "review",
            "confidence": None,
            "answers": {
                "grounded": {
                    "status": "invalid",
                    "value": None,
                    "reason": "TEST_PROVIDER_UNAVAILABLE",
                    "explanation": "Provider test double unavailable",
                    "evidence": [],
                    "confidence": None,
                }
            },
            "coverage": {},
            "quality_status": "unassessed",
            "status": "failed",
            "reason": "TEST_PROVIDER_UNAVAILABLE",
        }

    overrides = {
        "decide_next_v1": decide,
        "ecommerce_resolution_propose_v1": propose,
        "evaluate_v2": judge,
    }
    monkeypatch.setattr(engine, "resolve_skill", lambda slug: overrides.get(slug) or resolve(slug))
    monkeypatch.setattr("app.services.evaluation.auto_eval.schedule_eval", lambda _id: None)
    body = {
        "expected_draft_revision": draft.revision,
        "request_key": "hybrid-prefix",
        "execution_mode": "qualified_prefix",
        "repeat_count": 1,
        "ingress_id": composition.CASE_INGRESS,
        "kind": "manual",
    }
    preview, _, _ = campaigns.preflight_campaign(
        db_session, suite=suite, baseline=baseline, workspace=ws, body=body
    )
    assert preview["eligible"], preview["issues"]
    body["preflight_sha256"] = preview["preflight_sha256"]
    campaign = campaigns.create_campaign(
        db_session, suite=suite, baseline=baseline, workspace=ws, user=actor, body=body
    )
    db_session.commit()
    draft_before = copy.deepcopy(draft.flow_definition)
    count_before = model.predict_count
    business_slugs = {
        d.slug for d in db_session.query(TabularDataset).filter_by(evaluation_campaign_id=None)
    }
    for side in ("baseline", "candidate"):
        run_id = campaign.results[0][side]["run_id"]
        outcome = await dag.execute_run_dag(run_id)
        db_session.expire_all()
        run = db_session.get(Run, run_id)
        assert outcome["status"] == "cancelled", (
            outcome,
            run.error,
            [(i.skill_slug, i.error) for i in run.invocations],
        )
        assert run.error == "EVALUATION_STOPPED_AT_HUMAN_GATE"
        assert run.duration_ms > 0
        datasets = db_session.query(TabularDataset).filter_by(run_id=run_id).all()
        assert len(datasets) == 3
        assert all(
            d.evaluation_campaign_id == campaign.id and d.slug not in business_slugs
            for d in datasets
        )
        assert all(d.status == "ready" for d in datasets)
    db_session.refresh(model)
    assert model.predict_count == count_before
    assert db_session.query(ClaimAction).count() == 0
    assert db_session.query(MLPrediction).filter_by(evaluation_campaign_id=campaign.id).count() == 2
    assert db_session.query(MLPrediction).filter_by(evaluation_campaign_id=None).count() == 0
    if not retain_inputs:
        predictions = (
            db_session.query(MLPrediction).filter_by(evaluation_campaign_id=campaign.id).all()
        )
        assert all(
            prediction.dataset_id is None and not prediction.payload_json
            for prediction in predictions
        )
    assert (
        db_session.query(RecipeExecution).filter_by(evaluation_campaign_id=campaign.id).count() >= 2
    )
    assert db_session.get(SystemFlowDraft, main.id).flow_definition == draft_before
    campaigns.refresh_campaign(db_session, campaign)
    assert campaign.status == "completed"
    assert all(
        campaign.results[0][side]["verdict"] == "passed" for side in ("baseline", "candidate")
    )
    assert all(
        campaign.results[0][side]["quality_status"]
        == ("not_applicable" if early_human else "unassessed")
        for side in ("baseline", "candidate")
    )
    assert campaigns.suite_run_result(run)["termination"] == "human_gate"
    assert "output_ref" not in campaigns.suite_run_result(run)
    if early_human:
        assert (
            not db_session.query(SkillInvocation)
            .filter(
                SkillInvocation.run_id == run.id,
                SkillInvocation.skill_slug == "ecommerce_resolution_propose_v1",
            )
            .count()
        )
        assert campaign.results[0]["candidate"]["output_ref"]["exit"] == "ask_human"
