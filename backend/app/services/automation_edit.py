"""Closed catalog for an automation edit. No model call.

A patch may only add, update, or remove blocks the automation palette
already runs. Any other type is a refusal. A write is accepted only against
the draft hash just read, and the saved graph must match that patch.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.services.run_engine.execution_contract import canonical_flow, canonical_flow_sha256


class AutomationEditRefusal(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class AutomationBlock:
    type: str
    skill_slug: str | None
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]


CATALOG: tuple[AutomationBlock, ...] = (
    AutomationBlock("trigger", None, (), ("transcript",)),
    AutomationBlock("agent", "workspace_llm_v1", ("transcript", "instruction"), ("completion",)),
    AutomationBlock("decision", None, ("value",), ("yes", "no")),
    AutomationBlock("approval", None, ("in",), ("approved", "decision_id", "decided_by")),
    AutomationBlock("retrieve", "semantic_search_v1", ("query",), ("passage", "source")),
    AutomationBlock("sap_write", "sap_create_po_v1", ("pr_id", "decided_by"), ("sealed", "po_number", "rolled_back")),
    AutomationBlock("output", None, ("result",), ()),
)

_BY_TYPE = {block.type: block for block in CATALOG}


def catalog() -> tuple[AutomationBlock, ...]:
    return CATALOG


def edit_generation_options(provider: str, model: str) -> dict[str, Any]:
    """One completion. A thinking model must keep tokens for the JSON plan.

    gpt-5 spends ``max_completion_tokens`` on reasoning. The chat path already
    pins ``openai_reasoning_effort``; this turn uses the same pin, or the
    visible plan comes back empty.
    """

    from app.core.config import settings
    from app.llm.providers.openai_provider import OpenAIProvider

    options: dict[str, Any] = {"max_tokens": 2000}
    if provider in {"openai", "azure_openai"}:
        options["response_format"] = {"type": "json_object"}
    thinking = any(
        model == item or model.startswith(f"{item}-")
        for item in OpenAIProvider.THINKING_MODELS
    )
    if thinking:
        options["reasoning_effort"] = settings.openai_reasoning_effort or "minimal"
    return options


def edit_prompt(message: str, snapshot: Mapping[str, Any]) -> str:
    """Ask the workspace model for one catalog patch. The catalog check still refuses the reply."""

    lines = [
        f"{block.type} skill={block.skill_slug or '-'} in={','.join(block.inputs) or '-'} out={','.join(block.outputs) or '-'}"
        for block in CATALOG
    ]
    return (
        "You edit one automation draft. Reply with one JSON object and nothing else. "
        "Keys are intent and patch. intent is explain, clarify, edit, run, or edit_and_run. "
        "patch may contain add, update, remove, and edges. "
        "edges is an array of objects, each with from, to, from_port and to_port. "
        "Each added or updated block has id and type, and type is only one of: "
        + "; ".join(lines)
        + ". When the patch adds sap_write and approval, include an edge whose from_port and to_port are decided_by. "
        "There is no publish tool and no approve tool. "
        "Current draft: "
        + json.dumps(dict(snapshot), sort_keys=True, separators=(",", ":"))
        + "\nRequest: "
        + message
    )


def required_skill_slugs(flow: Mapping[str, Any]) -> list[str]:
    nodes = flow.get("nodes") if isinstance(flow.get("nodes"), list) else []
    slugs: list[str] = []
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        config = node.get("config") if isinstance(node.get("config"), Mapping) else {}
        slug = config.get("skill_slug")
        if isinstance(slug, str) and slug and slug not in slugs:
            slugs.append(slug)
    return slugs


def _items(patch: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    raw = patch.get(key) or []
    if isinstance(raw, Mapping):
        raw = [raw]
    if not isinstance(raw, list) or any(not isinstance(item, Mapping) for item in raw):
        raise AutomationEditRefusal("patch_invalid", f"{key} must be a list of objects")
    return list(raw)


def _block(node: Mapping[str, Any]) -> AutomationBlock:
    block_type = node.get("type")
    block = _BY_TYPE.get(block_type) if isinstance(block_type, str) else None
    if block is None:
        raise AutomationEditRefusal(
            "block_refused",
            f"Block type {block_type!r} is not in the automation catalog",
        )
    slug = node.get("skill_slug")
    if slug is not None and slug != block.skill_slug:
        raise AutomationEditRefusal(
            "block_refused",
            f"Block type {block.type!r} cannot use skill {slug!r}",
        )
    return block


def _node_type(node: Mapping[str, Any]) -> str | None:
    marked = node.get("config")
    if isinstance(marked, Mapping) and marked.get("automation_block") in _BY_TYPE:
        return str(marked["automation_block"])
    kind = node.get("kind")
    config = node.get("config") if isinstance(node.get("config"), Mapping) else {}
    slug = config.get("skill_slug")
    if slug == "workspace_llm_v1":
        return "agent"
    if slug == "semantic_search_v1":
        return "retrieve"
    if slug == "sap_create_po_v1":
        return "sap_write"
    if kind == "hitl":
        return "approval"
    if kind == "decision":
        return "decision"
    if kind == "source":
        return "trigger"
    if kind == "sink":
        return "output"
    return None


def _edge_key(edge: Mapping[str, Any]) -> tuple[Any, Any, Any, Any]:
    return (edge.get("from"), edge.get("to"), edge.get("from_port"), edge.get("to_port"))


def _require_decided_by(nodes: list[Mapping[str, Any]], edges: list[Mapping[str, Any]]) -> None:
    approvals = [node for node in nodes if _node_type(node) == "approval"]
    writes = [node for node in nodes if _node_type(node) == "sap_write"]
    if not approvals or not writes:
        return
    linked = {
        edge.get("to")
        for edge in edges
        if edge.get("from_port") == "decided_by"
        and edge.get("to_port") == "decided_by"
        and any(node.get("id") == edge.get("from") for node in approvals)
    }
    if any(node.get("id") not in linked for node in writes):
        raise AutomationEditRefusal(
            "decided_by_required",
            "Approval must link decided_by to SAP write",
        )


def _project(node_id: str, block: AutomationBlock) -> dict[str, Any]:
    """Project a catalog block into the graph the existing draft runner executes."""

    config: dict[str, Any] = {"automation_block": block.type}
    if block.skill_slug:
        config["skill_slug"] = block.skill_slug
    if block.type == "trigger":
        return {
            "id": node_id,
            "type": "source",
            "kind": "source",
            "label": "Trigger",
            "outputs": [{"name": "transcript", "schema": "string", "required": True}],
            "config": {
                **config,
                "ingress_kind": "manual",
                "input_schema": {
                    "type": "object",
                    "required": ["transcript"],
                    "properties": {"transcript": {"type": "string"}},
                },
            },
        }
    if block.type == "agent":
        config["inputs_map"] = {
            "transcript": "run.transcript",
            "instruction": "node.config.params.instruction",
        }
        config["outputs_map"] = {}
        return {
            "id": node_id,
            "type": "skill",
            "kind": "task",
            "label": "Agent",
            "inputs": [{"name": "transcript", "schema": "string"}],
            "outputs": [{"name": "completion", "schema": "string"}],
            "config": config,
        }
    if block.type == "decision":
        config.update({
            "passthrough_inputs": ["value"],
            "branches": [
                {"label": "yes", "condition": "value == True"},
                {"label": "no", "condition": "value == False"},
            ],
            "default_branch": "no",
        })
        return {
            "id": node_id,
            "type": "decision",
            "kind": "decision",
            "label": "Decision",
            "inputs": [{"name": "value", "schema": "any"}],
            "outputs": [
                {"name": "yes", "schema": "object"},
                {"name": "no", "schema": "object"},
            ],
            "config": config,
        }
    if block.type == "approval":
        config.update({"prompt": "Approve this step?", "prompt_kind": "approve_write"})
        return {
            "id": node_id,
            "type": "hitl",
            "kind": "hitl",
            "label": "Approval",
            "inputs": [{"name": "in", "schema": "string"}],
            "outputs": [
                {"name": "approved", "schema": "boolean"},
                {"name": "decision_id", "schema": "string"},
                {"name": "decided_by", "schema": "string"},
            ],
            "config": config,
        }
    if block.type == "retrieve":
        config["inputs_map"] = {"query": "run.transcript"}
        config["outputs_map"] = {}
        return {
            "id": node_id,
            "type": "skill",
            "kind": "task",
            "label": "Retrieve",
            "inputs": [{"name": "query", "schema": "string"}],
            "outputs": [
                {"name": "passage", "schema": "string"},
                {"name": "source", "schema": "string"},
            ],
            "config": config,
        }
    if block.type == "sap_write":
        config["inputs_map"] = {}
        config["outputs_map"] = {}
        return {
            "id": node_id,
            "type": "skill",
            "kind": "task",
            "label": "SAP write",
            "inputs": [
                {"name": "pr_id", "schema": "string"},
                {"name": "decided_by", "schema": "string"},
            ],
            "outputs": [
                {"name": "sealed", "schema": "boolean"},
                {"name": "po_number", "schema": "string"},
                {"name": "rolled_back", "schema": "boolean"},
            ],
            "config": config,
        }
    return {
        "id": node_id,
        "type": "sink",
        "kind": "sink",
        "label": "Output",
        "inputs": [{"name": "result", "schema": "object"}],
        "config": config,
    }


def _foreign_type(node: Mapping[str, Any]) -> str:
    """How a block the palette does not run is named when a person reads it."""

    config = node.get("config") if isinstance(node.get("config"), Mapping) else {}
    slug = config.get("skill_slug")
    if isinstance(slug, str) and slug.strip("@"):
        return slug.strip("@")
    for key in ("type", "kind"):
        value = node.get(key)
        if isinstance(value, str) and value:
            return value
    return "block"


def read_graph(flow: Mapping[str, Any]) -> dict[str, Any]:
    """Every node, the draft hash, and which blocks an edit may change. Nothing is saved.

    Reading is not editing: a reservation rereads any System's draft, including
    blocks the palette does not run (a BRD extraction, say). ``editable`` names
    the blocks an automation turn may patch; :func:`read_draft` refuses a draft
    with any other block before a write.
    """

    graph = canonical_flow(flow)
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
    read = []
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        block_type = _node_type(node)
        read.append(
            {
                "id": node.get("id"),
                "type": block_type or _foreign_type(node),
                "editable": block_type is not None,
            }
        )
    return {
        "nodes": read,
        "edges": [_edge_key(edge) for edge in edges if isinstance(edge, Mapping)],
        "hash": canonical_flow_sha256(graph),
    }


def read_draft(flow: Mapping[str, Any]) -> dict[str, Any]:
    """Nodes, edges, and the hash a later write must repeat. Nothing is saved."""

    seen = read_graph(flow)
    unknown = [node["id"] for node in seen["nodes"] if not node["editable"]]
    if unknown:
        raise AutomationEditRefusal(
            "block_refused",
            f"Draft contains a block outside the automation catalog: {unknown[0]!r}",
        )
    return {
        "nodes": [{"id": node["id"], "type": node["type"]} for node in seen["nodes"]],
        "edges": seen["edges"],
        "hash": seen["hash"],
    }


def apply_patch(flow: Mapping[str, Any], patch: Mapping[str, Any], *, expected_hash: str) -> dict[str, Any]:
    """Return the next draft. Refuse when the draft moved since it was read."""

    current = read_draft(flow)
    if current["hash"] != expected_hash:
        raise AutomationEditRefusal(
            "stale_draft",
            "The draft changed after it was read; read it again before writing",
        )
    validate_patch(patch)
    graph = copy.deepcopy(canonical_flow(flow))
    nodes = [node for node in graph.get("nodes") or [] if isinstance(node, Mapping)]
    edges = [edge for edge in graph.get("edges") or [] if isinstance(edge, Mapping)]
    by_id = {node.get("id"): node for node in nodes}

    for node_id in (item.get("id") for item in _items(patch, "remove")):
        by_id.pop(node_id, None)
        edges = [edge for edge in edges if edge.get("from") != node_id and edge.get("to") != node_id]
    for update in _items(patch, "update"):
        node_id = update.get("id")
        if node_id not in by_id:
            raise AutomationEditRefusal("patch_invalid", f"Cannot update unknown node {node_id!r}")
        by_id[node_id] = _project(str(node_id), _block(update))
    for added in _items(patch, "add"):
        node_id = added.get("id")
        if not isinstance(node_id, str) or not node_id:
            raise AutomationEditRefusal("patch_invalid", "An added block needs an id")
        if node_id in by_id:
            raise AutomationEditRefusal("patch_invalid", f"Node {node_id!r} already exists")
        by_id[node_id] = _project(node_id, _block(added))
    for edge in _items(patch, "edges"):
        if edge.get("from") not in by_id or edge.get("to") not in by_id:
            raise AutomationEditRefusal("patch_invalid", "An edge must join two blocks in the draft")
        edges.append(dict(edge))

    drafted = list(by_id.values())
    _require_decided_by(drafted, edges)
    graph["nodes"] = drafted
    graph["edges"] = edges
    return graph


_TOOLS: dict[str, frozenset[str]] = {
    "explain": frozenset({"read"}),
    "clarify": frozenset({"read"}),
    "edit": frozenset({"read", "patch"}),
    "run": frozenset({"read", "test"}),
    "edit_and_run": frozenset({"read", "patch", "test"}),
}


def allow_tool(intent: str, tool: str) -> None:
    """Gate a tool by the classified intention. Publish and approve do not exist."""

    if tool in {"publish", "approve"}:
        raise AutomationEditRefusal("tool_refused", f"There is no {tool} tool on an automation edit")
    granted = _TOOLS.get(intent)
    if granted is None:
        raise AutomationEditRefusal("intent_refused", f"Intention {intent!r} is not an automation turn")
    if tool not in granted:
        raise AutomationEditRefusal(
            "tool_refused",
            f"Intention {intent!r} cannot call {tool}",
        )


def read_back(saved: Mapping[str, Any], proposed: Mapping[str, Any]) -> None:
    """Fail when the saved draft is not the patch that was applied."""

    if read_draft(saved)["nodes"] != read_draft(proposed)["nodes"] or read_draft(saved)["edges"] != read_draft(proposed)["edges"]:
        raise AutomationEditRefusal(
            "save_mismatch",
            "The saved draft is not the patch that was applied",
        )


def plan_from_completion(text: str) -> dict[str, Any]:
    """Read one model completion. A non-catalog block is a refusal, not a guess."""

    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1]
        if stripped.endswith("```"):
            stripped = stripped[:-3].strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise AutomationEditRefusal("plan_invalid", "The edit plan is not JSON") from exc
    if not isinstance(parsed, Mapping):
        raise AutomationEditRefusal("plan_invalid", "The edit plan is not an object")
    intent = parsed.get("intent")
    if not isinstance(intent, str):
        raise AutomationEditRefusal("intent_refused", "The edit plan has no intention")
    patch = parsed.get("patch") if isinstance(parsed.get("patch"), Mapping) else {}
    if intent in {"edit", "edit_and_run"}:
        allow_tool(intent, "patch")
        validate_patch(patch)
    elif patch:
        allow_tool(intent, "patch")
    else:
        allow_tool(intent, "read")
    return {"intent": intent, "patch": dict(patch)}


def summarize_draft_result(run: Mapping[str, Any]) -> dict[str, Any]:
    """The run the loop may show: a citation, a sealed write, or an Approval pause."""

    checkpoints = run.get("checkpoints") if isinstance(run.get("checkpoints"), list) else []
    pause = next(
        (
            item
            for item in reversed(checkpoints)
            if isinstance(item, Mapping) and item.get("kind") == "hitl_pause"
        ),
        None,
    )
    if run.get("status") == "hitl_pending" and pause is not None:
        return {
            "kind": "approval_pause",
            "prompt": pause.get("prompt"),
            "decision_id": pause.get("decision_id"),
        }
    invocations = run.get("invocations") if isinstance(run.get("invocations"), list) else []
    for invocation in reversed(invocations):
        if not isinstance(invocation, Mapping):
            continue
        output = invocation.get("output_ref") if isinstance(invocation.get("output_ref"), Mapping) else {}
        if invocation.get("skill_slug") == "semantic_search_v1":
            passage = output.get("passage") if isinstance(output.get("passage"), str) else ""
            source = output.get("source") if isinstance(output.get("source"), str) else ""
            if passage.strip():
                return {"kind": "retrieve", "passage": passage, "source": source}
            return {"kind": "retrieve", "passage": None, "source": None}
        if invocation.get("skill_slug") == "sap_create_po_v1":
            return {
                "kind": "sap_write",
                "sealed": output.get("sealed") is True,
                "called": output.get("called") is True,
            }
    return {"kind": "none"}


def execute_turn(
    flow: Mapping[str, Any],
    *,
    intent: str,
    patch: Mapping[str, Any] | None,
    save,
    start_test,
) -> dict[str, Any]:
    """Read, optionally write the verified patch, optionally start the existing draft test."""

    seen = read_draft(flow)
    proposed = flow
    verified = False
    if patch:
        allow_tool(intent, "patch")
        proposed = apply_patch(flow, patch, expected_hash=seen["hash"])
        saved = save(proposed)
        read_back(saved, proposed)
        proposed = saved
        verified = True
    else:
        allow_tool(intent, "read")
    started = None
    if intent in {"run", "edit_and_run"}:
        allow_tool(intent, "test")
        started = start_test(read_draft(proposed))
    return {"read": read_draft(proposed), "verified": verified, "run": started}


def validate_patch(patch: Mapping[str, Any]) -> dict[str, Any]:
    """Accept a patch of catalog blocks, or refuse it.

    When the patch places both Approval and SAP write, Approval must feed
    ``decided_by`` into the write. The function does not save anything.
    """

    if not isinstance(patch, Mapping):
        raise AutomationEditRefusal("patch_invalid", "patch must be an object")
    nodes = [*_items(patch, "add"), *_items(patch, "update")]
    for node in nodes:
        _block(node)
    placed = [node for node in _items(patch, "add")]
    approvals = [node for node in placed if node.get("type") == "approval"]
    writes = [node for node in placed if node.get("type") == "sap_write"]
    edges = _items(patch, "edges")
    if approvals and writes:
        linked = {
            edge.get("to")
            for edge in edges
            if edge.get("from_port") == "decided_by"
            and edge.get("to_port") == "decided_by"
            and any(node.get("id") == edge.get("from") for node in approvals)
        }
        missing = [node.get("id") for node in writes if node.get("id") not in linked]
        if missing:
            raise AutomationEditRefusal(
                "decided_by_required",
                "Approval must link decided_by to SAP write",
            )
    return {
        "nodes": [
            {"id": node.get("id"), "type": node.get("type"), "skill_slug": _block(node).skill_slug}
            for node in placed
        ],
        "edges": [dict(edge) for edge in edges],
    }
