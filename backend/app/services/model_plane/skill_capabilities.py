"""Server-reviewed text-model requirements of native Skill runtimes.

Absence from this table is not evidence of absence of a model. In particular,
``provider=internal``, a workspace-authored name, input metadata or a missing
model request cannot exempt an unknown/native composite from model policy.
Tabular/forecast artifact permissions and retrieval embedding configuration are
separate from the selectable text-generation models governed by this gate.
"""

from collections.abc import Mapping
from typing import Any

VERIFIED_NON_TEXT_SKILLS = frozenset(
    {
        # Deterministic storage/data operations; no arbitrary Python recipe runtime.
        "audit_log_v1",
        "sql_transform_v1",
        "data_prep_v1",
        # Artifact-scoped classical inference/forecasting, with their own ML grants.
        "ml_predict_v1",
        "ml_batch_score_v1",
        "ml_forecast_v1",
        # Retrieval returns evidence; it does not synthesize or rewrite with an LLM.
        "semantic_search_v1",
        "skill_search_v1",
        # Reviewed native business primitives: PostgreSQL, retrieval and rules only.
        "postgresql_claim_snapshot_v1",
        "ecommerce_sav_dataset_v1",
        "ecommerce_sav_context_v1",
        "ecommerce_policy_evidence_v1",
        "ecommerce_delivery_evidence_v1",
        "ecommerce_refund_evidence_v1",
        "ecommerce_resolution_propose_v1",
        "ecommerce_resolution_simulate_v1",
    }
)


def is_verified_non_text_skill(slug: str, executor: Mapping[str, Any] | None) -> bool:
    """Classify the executable binding, using the published executor if present."""
    if executor is not None:
        if not isinstance(executor, Mapping) or executor.get("kind") != "registry_call":
            return False
        params = executor.get("params")
        if not isinstance(params, Mapping):
            return False
        target = params.get("skill_slug")
        return isinstance(target, str) and target in VERIFIED_NON_TEXT_SKILLS
    return slug in VERIFIED_NON_TEXT_SKILLS


def frozen_skill_executor(
    contract: Any, node_id: str | None, slug: str | None = None
) -> dict[str, Any] | None:
    """Read an authored binding from the accepted node/tool contract only."""
    if not node_id:
        return None
    nodes = contract.get("nodes") if isinstance(contract, dict) else None
    node = nodes.get(node_id) if isinstance(nodes, dict) else None
    if isinstance(node, dict) and slug is not None and node.get("skill_slug") != slug:
        tools = node.get("tool_contract")
        if isinstance(tools, dict):
            tool_nodes = tools.get("nodes")
            node = tool_nodes.get(slug) if isinstance(tool_nodes, dict) else None
            if not isinstance(node, dict):
                raise ValueError("execution_contract:agent_loop_tool_not_frozen")
        else:
            return None  # Historical AgentLoops had no frozen tool bindings.
    executor = node.get("executor") if isinstance(node, dict) else None
    return executor if isinstance(executor, dict) else None


def flow_model_gate(flow: Any, contract: Any, *, db, workspace_id: str | None) -> str:
    """Return guarded/unknown/no_calls, using exactly the accepted Flow.

    A guarded Flow may defer model enforcement until each canonical invocation
    resolves its real connection. An unknown runtime cannot use a declared
    System default as evidence of the model it will actually call.
    """
    from app.models.skill import Skill
    from app.services.flow_skill_binding import resolve_flow_skill_binding
    from app.services.model_plane.execution import skill_model_request

    if not isinstance(flow, dict) or not isinstance(flow.get("nodes"), list):
        return "unknown"
    calls = []
    for node in flow["nodes"]:
        if not isinstance(node, dict):
            return "unknown"
        kind = node.get("kind")
        if kind in {"source", "sink", "asset", "secret", "decision", "hitl", "fork", "join"}:
            continue
        if kind not in {"task", "retry", "agent_loop"}:
            return "unknown"
        try:
            binding = resolve_flow_skill_binding(node)
        except (ValueError, TypeError, AttributeError):
            return "unknown"
        calls.append((node.get("id"), binding.skill_slug))
        if kind == "agent_loop":
            config = node.get("config")
            if not isinstance(config, dict) or not isinstance(config.get("skill_allowlist"), list):
                return "unknown"
            calls.extend((node.get("id"), slug) for slug in config["skill_allowlist"])
    if not calls:
        return "no_calls"
    for node_id, slug in calls:
        if not isinstance(slug, str) or not slug:
            return "unknown"
        try:
            executor = frozen_skill_executor(contract, node_id, slug)
        except ValueError:
            return "unknown"
        if executor is None and slug.startswith("ws."):
            row = (
                db.query(Skill)
                .filter(Skill.workspace_id == workspace_id, Skill.slug == slug)
                .first()
            )
            executor = row.executor if row is not None else None
        if (
            not is_verified_non_text_skill(slug, executor)
            and skill_model_request(slug, executor, {}, None) is None
        ):
            return "unknown"
    return "guarded"


def evaluate_flow_model_capability(spec, *, system_model, flow, contract, db, workspace_id):
    """Share the admission/runtime policy boundary without granting any model."""
    from app.services.membrane.enforcement import evaluate_capability

    if spec.capabilities.allowed_models and flow is not None:
        gate = flow_model_gate(flow, contract, db=db, workspace_id=workspace_id)
        if gate == "guarded":
            return evaluate_capability(spec, action="system.engine.run", model_required=False)
        if gate == "unknown":
            return evaluate_capability(spec, action="system.engine.run")
    # Preserve historical non-Flow/control-only admission. Any later Skill
    # still has to prove its executable identity at the invocation boundary.
    return evaluate_capability(spec, model=system_model, action="system.engine.run")
