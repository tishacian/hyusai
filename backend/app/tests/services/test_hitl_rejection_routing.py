"""A refused approval never implicitly authorizes its normal continuation."""

from copy import deepcopy

import pytest

from app.models.decision import Decision
from app.services.run_engine.dag import DagGraph, WalkerState, execute_run_dag, resume_run_dag
from app.services.run_engine.hitl_routing import has_explicit_rejection_route
from app.tests.services.test_run_engine_dag_e2e import (
    _install_fake_registry,
    _mk_run,
    _mk_skill,
    _mk_system,
)


def routed_flow():
    return {
        "schema_version": 2,
        "nodes": [
            {"id": "source", "kind": "source"},
            {"id": "review", "kind": "hitl"},
            {
                "id": "route",
                "kind": "decision",
                "config": {
                    "inputs_map": {"verdict": {"node_id": "review", "path": ["approved"]}},
                    "branches": [
                        {"label": "accepted", "condition": "verdict == True"},
                        {"label": "rejected", "condition": "verdict == False"},
                    ],
                },
            },
            {"id": "apply", "kind": "task", "config": {"skill_slug": "apply_v1"}},
            {"id": "discard", "kind": "task", "config": {"skill_slug": "discard_v1"}},
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "source", "to": "review"},
            {"from": "review", "to": "route", "kind": "control"},
            {"from": "route", "to": "apply", "kind": "branch", "branch_label": "accepted"},
            {"from": "route", "to": "discard", "kind": "branch", "branch_label": "rejected"},
            {"from": "apply", "to": "sink"},
            {"from": "discard", "to": "sink"},
        ],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["accepted", "applied", "rejected"])
async def test_authored_verdict_routes_execute_only_the_selected_tail(
    db_session, monkeypatch, status
):
    calls = []

    async def apply(inp, ctx):
        calls.append("apply")
        return {"action": "apply"}

    async def discard(inp, ctx):
        calls.append("discard")
        return {"action": "discard"}

    _install_fake_registry(monkeypatch, {"apply_v1": apply, "discard_v1": discard})
    for slug in ("apply_v1", "discard_v1"):
        _mk_skill(db_session, slug)
    system = _mk_system(db_session, flow=routed_flow())
    run = _mk_run(db_session, system)
    paused = await execute_run_dag(run.id)
    assert paused["status"] == "hitl_pending"
    decision = db_session.get(Decision, paused["awaiting_decision"])
    decision.status = status
    db_session.commit()
    resumed = await resume_run_dag(run.id, decision_id=decision.id)
    assert resumed["status"] == "completed", resumed
    expected = "discard" if status == "rejected" else "apply"
    assert calls == [expected]
    db_session.refresh(run)
    assert run.output_ref == {"action": expected}


@pytest.mark.asyncio
async def test_terminal_collector_can_retain_a_rejected_verdict(db_session):
    flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "source", "kind": "source"},
            {"id": "review", "kind": "hitl"},
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [{"from": "source", "to": "review"}, {"from": "review", "to": "sink"}],
    }
    run = _mk_run(db_session, _mk_system(db_session, flow=flow))
    paused = await execute_run_dag(run.id)
    decision = db_session.get(Decision, paused["awaiting_decision"])
    decision.status = "rejected"
    db_session.commit()
    assert (await resume_run_dag(run.id, decision_id=decision.id))["status"] == "completed"
    db_session.refresh(run)
    assert run.output_ref["decision_status"] == "rejected"


@pytest.mark.parametrize(
    "variant",
    [
        "valid",
        "legacy",
        "strict",
        "ctx_alias",
        "foreign_selector",
        "foreign_condition",
        "wrong_gate_port",
        "unconditional",
        "default",
        "unroutable",
        "same_target",
        "parallel_bypass",
        "second_predecessor",
        "unsafe_expression",
        "strict_unmapped",
        "overwritten_gate_verdict",
    ],
)
def test_rejection_route_requires_this_gate_and_distinct_valid_branches(variant):
    flow = deepcopy(routed_flow())
    config = flow["nodes"][2]["config"]
    if variant == "legacy":
        config.pop("inputs_map")
        for branch in config["branches"]:
            branch["condition"] = branch["condition"].replace("verdict", "hitl_approved")
    elif variant == "ctx_alias":
        for branch in config["branches"]:
            branch["condition"] = branch["condition"].replace("verdict", "ctx.verdict")
    elif variant == "foreign_selector":
        config["inputs_map"]["verdict"]["node_id"] = "source"
    elif variant == "foreign_condition":
        config["branches"][1]["condition"] = "request_permits_write"
    elif variant == "wrong_gate_port":
        flow["edges"][1]["from_port"] = "invented_verdict"
    elif variant == "unconditional":
        config["branches"][1]["condition"] = "True"
    elif variant == "default":
        config["branches"][1]["condition"] = "False"
        config["default_branch"] = "rejected"
    elif variant == "unroutable":
        flow["edges"][3]["branch_label"] = "unknown"
    elif variant == "same_target":
        flow["edges"][3]["to"] = "apply"
    elif variant == "parallel_bypass":
        flow["edges"].append({"from": "review", "to": "apply"})
    elif variant == "second_predecessor":
        flow["edges"].append({"from": "source", "to": "route"})
    elif variant == "unsafe_expression":
        config["branches"][1]["condition"] = "False and exec('unsafe')"
    elif variant == "strict_unmapped":
        config.pop("inputs_map")
    elif variant == "overwritten_gate_verdict":
        flow["nodes"][1]["config"] = {"outputs_map": {"rejected": "review.approved"}}
    graph = DagGraph.from_flow_definition(flow)
    graph.strict_authoritative = variant in {"strict", "strict_unmapped"}
    assert has_explicit_rejection_route(graph, WalkerState(), "review") is (
        variant in {"valid", "legacy", "strict", "ctx_alias"}
    )


def test_canonical_sap_refusal_route_remains_available():
    from app.services.connectors.mcp.flow import pr_to_po_flow

    graph = DagGraph.from_flow_definition(pr_to_po_flow())
    graph.strict_authoritative = True
    assert has_explicit_rejection_route(graph, WalkerState(), "hitl.approve_po")


@pytest.mark.asyncio
async def test_unrelated_ttl_proof_does_not_call_a_human_refusal_expired(db_session, monkeypatch):
    flow = routed_flow()
    flow["nodes"] = [node for node in flow["nodes"] if node["id"] not in {"route", "discard"}]
    flow["edges"] = [
        edge
        for edge in flow["edges"]
        if edge["from"] in {"source", "apply"} and edge["to"] != "route"
    ]
    flow["edges"].append({"from": "review", "to": "apply"})
    for slug in ("apply_v1", "discard_v1"):
        _mk_skill(db_session, slug)
    # No task callable is installed: a mistaken continuation must fail the test.
    _install_fake_registry(monkeypatch, {})
    run = _mk_run(db_session, _mk_system(db_session, flow=flow))
    paused = await execute_run_dag(run.id)
    decision = db_session.get(Decision, paused["awaiting_decision"])
    decision.status = "rejected"
    decision.approved_by = "system:gate_ttl"
    db_session.refresh(run)
    run.checkpoints = [
        *(run.checkpoints or []),
        {
            "kind": "gate_ttl_expired",
            "decision_id": "another-decision",
            "expiry_action": "reject",
        },
    ]
    db_session.commit()
    resumed = await resume_run_dag(run.id, decision_id=decision.id)
    assert resumed["status"] == "cancelled"
    assert resumed["error"] == "hitl_approval_rejected"
    db_session.refresh(run)
    assert not any(cp.get("skill_slug") == "apply_v1" for cp in run.checkpoints)
