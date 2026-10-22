"""Exercise the prepared Luma Judge chain locally; provider replies are simulated."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from app.core.config import settings
from app.models.evaluation import EvaluationScore
from app.models.knowledge_collection import KnowledgeCollection
from app.models.run import Run, SkillInvocation
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.chains.dag_validator import validate_flow
from app.services.model_plane import execution, typesafe
from app.services.model_plane.execution import ModelExecution
from app.services.run_engine.dag import DagGraph
from app.services.run_engine.variable_pool import VariablePool, apply_inputs_map
from app.services.skills_registry.wrappers.skills import _evaluate_v2

ROOT = Path(__file__).resolve().parents[4]
PLAN = json.loads((ROOT / "docs/demo-runs/showcase-ecommerce/jev/main-flow-plan.json").read_text())
FLOW = PLAN["review_request"]["body"]["flow_definition"]
JEV, GPT = "quality.second_opinion_jev", "quality.review"


async def test_actual_candidate_captures_two_independent_evidence_snapshots_and_judgments(
    db_session, monkeypatch, tmp_path
):
    assert not [issue for issue in validate_flow(FLOW) if issue.level == "error"]
    graph = DagGraph.from_flow_definition(FLOW)
    assert graph.io_mode == "overlay" and not graph.strict_authoritative
    assert [edge.target for edge in graph.out_edges[JEV]] == [GPT]
    assert [edge.target for edge in graph.out_edges[GPT]] == ["hitl.review"]

    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path))
    workspace = Workspace(id=str(uuid4()), name="Candidate test", slug="candidate-" + uuid4().hex)
    user = User(id=str(uuid4()), username="candidate-" + uuid4().hex, is_active=True)
    db_session.add_all([workspace, user])
    db_session.flush()
    db_session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="member"))
    run = Run(
        id=str(uuid4()), workspace_id=workspace.id, initiated_by_user_id=user.id, status="running"
    )
    db_session.add(run)
    db_session.flush()
    selectors = graph.nodes[GPT].config["typed_evaluation"]["run_evidence"]
    for index, reference in enumerate(selectors["native_refs"]):
        db_session.add(
            KnowledgeCollection(
                id=reference["id"],
                workspace_id=workspace.id,
                slug=f"test-evidence-{index}",
                name=f"Test evidence {index}",
                status="ready",
                vector_collection_name=f"test-{index}",
                artifact_prefix=f"test-{index}",
                active_generation="local-fixture",
            )
        )
    outputs = {
        "proposal": {
            "claim_id": "RC-1042",
            "order_id": "LM-1042",
            "action": "carrier_investigation",
            "summary": "Local test: delivery contradiction",
            "reason": "Postal codes differ",
            "amount": "0",
            "currency": "EUR",
            "requires_human": True,
            "requires_sav_manager": False,
            "missing_references": [],
            "snapshot_sha256": "a" * 64,
            "citations": [],
            "evidence_kind": "synthetic_demo",
            "financial_execution": "not_executed",
            "unselected_secret": "must-not-reach-either-provider",
        },
        "policy": {"citations": [], "references": ["fixture-policy-v2"]},
        "order": {
            "data": {
                "context": {"postal_code": "75011"},
                "refunds": [],
                "shipments": [{"postal_code": "75012"}],
            }
        },
    }
    for source in selectors["sources"]:
        db_session.add(
            SkillInvocation(
                id=str(uuid4()),
                run_id=run.id,
                skill_slug=source["skill_slug"],
                status="completed",
                trace={"node_id": "loop.investigate"},
                output_ref=outputs[source["id"]],
            )
        )
    db_session.commit()

    calls = []

    async def native(**kwargs):
        calls.append(("typesafe", kwargs["state"]))
        answers = {}
        for key, question in kwargs["questions"].items():
            if question["type"] == "noul":
                answers[key] = {"type": "noul", "noul": 0.01}
            else:
                options = list(question["criteria"])
                answers[key] = {
                    "type": "choice",
                    "choice": options[0],
                    "confidence": 0.8,
                    "probabilities": {
                        option: 1.0 if i == 0 else 0.0 for i, option in enumerate(options)
                    },
                }
        return typesafe.normalize_response(
            {
                "model": kwargs["model"],
                "answers": answers,
                "usage": {"input_tokens": 120, "output_tokens": 20},
            },
            questions=kwargs["questions"],
        )

    class Provider:
        async def generate(self, *, model, prompt, **options):
            calls.append(("openai", prompt))
            # Deliberate abstentions keep the original citation contract valid;
            # this regression proves composition, not substantive model quality.
            return {
                "model": model,
                "content": json.dumps(
                    {
                        "answers": {
                            question["key"]: {
                                "status": "abstained",
                                "value": None,
                                "reason": "insufficient_evidence",
                                "explanation": "Local transport test; human review remains required.",
                                "evidence": [],
                            }
                            for question in graph.nodes[GPT].config["typed_evaluation"]["questions"]
                        }
                    }
                ),
                "usage": {"prompt_tokens": 200, "completion_tokens": 40, "total_tokens": 240},
            }

    monkeypatch.setattr(typesafe, "evaluate", native)
    monkeypatch.setattr(execution, "build_model_client", lambda *args, **kwargs: Provider())
    pool = VariablePool()
    results = []
    incoming = {
        "subject_ref": "must-not-use-incoming-subject",
        "evidence": [{"text": "must-not-use-incoming-proof"}],
    }
    for node_id in (JEV, GPT):
        config = graph.nodes[node_id].config
        payload = apply_inputs_map(config, pool, incoming, io_mode="overlay")
        assert payload == {}
        payload["_typed_evaluation"] = {
            "node_id": node_id,
            "typed_evaluation": config["typed_evaluation"],
        }
        tariff = config["typed_evaluation"]["tariff"]
        ctx = {
            "run_id": run.id,
            "workspace_id": workspace.id,
            "user_id": user.id,
            "_skill_node_id": node_id,
            "_model_policy_check": lambda candidate: None,
            "_model_execution": ModelExecution(
                tariff["provider"],
                tariff["model"],
                "workspace",
                "published_graph",
                _api_key="local-test-key",
            ),
        }
        result = await _evaluate_v2(payload, ctx)
        assert result["status"] in {"completed", "partial"}, result.get("reason")
        assert result["disposition"] == "review" and result["quality_status"] == "unassessed"
        assert {item["id"] for item in result["evidence"]} == {"proposal", "policy", "order"}
        # Replay the same node: cached, without a second provider call or budget.
        replay = await _evaluate_v2(payload, ctx)
        assert replay["cached"] and replay["evaluation_id"] == result["evaluation_id"]
        results.append(result)
        incoming = result

    assert [provider for provider, _ in calls] == ["typesafe", "openai"]
    assert all("must-not-" not in str(prompt) for _, prompt in calls)
    assert all("75011" in str(prompt) and "75012" in str(prompt) for _, prompt in calls)
    assert results[0]["evaluation_id"] != results[1]["evaluation_id"]
    assert results[0]["evidence"][0]["asset_ref"] != results[1]["evidence"][0]["asset_ref"]
    assert [(item["id"], item["sha256"]) for item in results[0]["evidence"]] == [
        (item["id"], item["sha256"]) for item in results[1]["evidence"]
    ]
    db_session.expire_all()
    assert db_session.query(EvaluationScore).filter_by(run_id=run.id).count() == 2
