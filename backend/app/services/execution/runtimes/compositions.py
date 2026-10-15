"""Qualification graphs with short native adapters and durable interrupts.

These graphs contain references, never a whole Flow inside one Activity. The
two fixed compositions are a qualification corpus, not a user graph compiler.
"""

from hashlib import sha256
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .contracts import ExecutionScope, native_port

COMPOSITIONS = {
    "agent_data_agent": ("agent_plan", "data_prepare", "agent_explain", "review", "delivery"),
    "data_agent_delivery": ("data_prepare", "agent_explain", "judge", "review", "delivery"),
}


class CompositionState(TypedDict):
    scope: dict
    references: dict


async def _execute_native(state: CompositionState, name):
    scope = ExecutionScope(**state["scope"])
    key = sha256(
        f"{scope.workspace_id}:{scope.run_id}:{scope.version_id}:{scope.flow_digest}:{name}".encode()
    ).hexdigest()
    port = native_port()
    await port.authorize(scope)
    reference = await port.submit(scope, name, key)
    observed = await port.observe(scope, reference)
    while observed.status in {"pending", "running", "waiting"}:
        # The resume value is deliberately ignored: the native Decision or
        # execution row, reauthorized below, is the only state authority.
        interrupt({"native_reference": reference.to_dict()})
        await port.authorize(scope)
        observed = await port.observe(scope, reference)
    if observed.status != "succeeded":
        raise RuntimeError(f"NATIVE_STEP_{observed.status.upper()}")
    return {"references": {**state.get("references", {}), name: reference.to_dict()}}


# Plugin 0.1.0 identifies Activities by module-qualified name and rejects
# closures/local functions. Stable module-level nodes also make replay naming
# explicit rather than depending on a graph factory's closure state.
async def agent_plan(state: CompositionState):
    return await _execute_native(state, "agent_plan")


async def data_prepare(state: CompositionState):
    return await _execute_native(state, "data_prepare")


async def agent_explain(state: CompositionState):
    return await _execute_native(state, "agent_explain")


async def judge(state: CompositionState):
    return await _execute_native(state, "judge")


async def review(state: CompositionState):
    return await _execute_native(state, "review")


async def delivery(state: CompositionState):
    return await _execute_native(state, "delivery")


NODES = {
    function.__name__: function
    for function in (agent_plan, data_prepare, agent_explain, judge, review, delivery)
}


def build_graph(name):
    if name not in COMPOSITIONS:
        raise ValueError("COMPOSITION_UNSUPPORTED")
    graph = StateGraph(CompositionState)
    previous = START
    for node in COMPOSITIONS[name]:
        graph.add_node(node, NODES[node], metadata={"execute_in": "activity"})
        graph.add_edge(previous, node)
        previous = node
    graph.add_edge(previous, END)
    return graph
