from app.services.run_engine.dag import (
    DagEdge,
    DagGraph,
    DagNode,
    WalkerState,
    unattended_sap_writes,
)


def _node(node_id: str, skill_slug: str | None = None, kind: str = "task") -> DagNode:
    return DagNode(
        id=node_id,
        type=kind,
        kind=kind,
        label=node_id,
        config={},
        skill_slug=skill_slug,
        data={},
    )


def _graph() -> DagGraph:
    approval = _node("approval", kind="hitl")
    agent = _node("agent", "workspace_llm_v1")
    sap = _node("sap", "sap_create_po_v1")
    decided = DagEdge("approval", "sap", "data", None, "decided_by", "decided_by")
    pr = DagEdge("agent", "sap", "data", None, "completion", "pr_id")
    return DagGraph(
        nodes={"approval": approval, "agent": agent, "sap": sap},
        edges=[decided, pr],
        out_edges={"approval": [decided], "agent": [pr], "sap": []},
        in_edges={"approval": [], "agent": [], "sap": [decided, pr]},
    )


def test_a_write_waiting_only_on_the_open_gate_is_selected():
    state = WalkerState()
    state.done.add("agent")
    assert unattended_sap_writes(_graph(), state, "approval") == ["sap"]


def test_a_write_still_waiting_on_another_node_is_left_alone():
    assert unattended_sap_writes(_graph(), WalkerState(), "approval") == []
