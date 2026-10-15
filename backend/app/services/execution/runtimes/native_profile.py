"""Closed, published-Flow profiles for the native Temporal candidate (no SDK)."""

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

COMPOSITIONS = {
    "agent_data_agent": ("agent_plan", "data_prepare", "agent_explain", "review", "delivery"),
    "data_agent_delivery": ("data_prepare", "agent_explain", "judge", "review", "delivery"),
}


class NativeProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal[1] = 1
    composition: Literal["agent_data_agent", "data_agent_delivery"]
    role_nodes: dict[str, str]
    output_role: str = "data_prepare"
    output_port: str | None = Field(default=None, min_length=1, max_length=128)
    # Delivery authority is an existing ServiceWindow, never an arbitrary URL.
    delivery: Literal["service_receipt"] = "service_receipt"
    review: Literal["service_delivery"] = "service_delivery"
    max_runtime_s: int = Field(default=3600, ge=1, le=86400)
    poll_interval_s: int = Field(default=10, ge=1, le=60)


def profile_digest(profile):
    return hashlib.sha256(
        json.dumps(profile, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def freeze_profile(run, raw_profile) -> dict:
    """Reject unrepresented execution rather than silently flattening a DAG."""
    from app.services.flow_contracts import validate_execution_contract
    from app.services.run_engine.dag import DagGraph
    from app.services.systems.flow_publication import canonical_flow_sha256

    profile = NativeProfile.model_validate(raw_profile)
    if not run.published_flow_version_id or not run.flow_sha256 or not run.execution_contract:
        raise ValueError("NATIVE_PUBLISHED_FLOW_REQUIRED")
    if canonical_flow_sha256(run.flow_snapshot) != run.flow_sha256:
        raise ValueError("NATIVE_FLOW_DIGEST_MISMATCH")
    validate_execution_contract(run.execution_contract)
    roles = COMPOSITIONS[profile.composition]
    if set(profile.role_nodes) != set(roles) or len(set(profile.role_nodes.values())) != len(roles):
        raise ValueError("NATIVE_ROLE_BINDINGS_INVALID")
    if profile.output_role not in roles[:-2]:
        raise ValueError("NATIVE_OUTPUT_ROLE_INVALID")
    graph = DagGraph.from_flow_definition(run.flow_snapshot)
    bound = set(profile.role_nodes.values())
    if not bound.issubset(graph.nodes):
        raise ValueError("NATIVE_NODE_MISSING")
    output_node = graph.nodes[profile.role_nodes[profile.output_role]]
    if output_node.skill_slug == "data_prep_v1":
        from app.schemas.data_prep import bind_spec
        from app.services.dataops.flow import _prep_config

        prep = _prep_config({"config": output_node.config})
        ports = {output.port for output in bind_spec(prep.get("spec"), prep.get("outputs")).outputs}
        if profile.output_port is not None and profile.output_port not in ports:
            raise ValueError("NATIVE_OUTPUT_PORT_UNKNOWN")
        if len(ports) > 1 and profile.output_port is None:
            raise ValueError("NATIVE_OUTPUT_PORT_REQUIRED")
    elif profile.output_port is not None:
        raise ValueError("NATIVE_OUTPUT_PORT_UNSUPPORTED")
    for role in roles:
        node = graph.nodes[profile.role_nodes[role]]
        expected = "hitl" if role == "review" else "sink" if role == "delivery" else "task"
        if node.kind != expected:
            raise ValueError("NATIVE_NODE_KIND_UNSUPPORTED")
        if role == "review" and (
            node.config.get("approvers")
            or node.config.get("prompt_kind") not in {None, "approve_write"}
            or any(
                node.config.get(key)
                for key in ("ttl_seconds", "ttl_s", "expiry_action", "inputs_map", "outputs_map")
            )
        ):
            raise ValueError("NATIVE_REVIEW_POLICY_UNSUPPORTED")
        if role == "delivery" and any(
            node.config.get(key) for key in ("inputs_map", "outputs_map", "passthrough_inputs")
        ):
            raise ValueError("NATIVE_DELIVERY_MAPPING_UNSUPPORTED")
        if expected == "task":
            contract = run.execution_contract.get("nodes", {}).get(node.id, {})
            if not node.skill_slug or contract.get("skill_slug") != node.skill_slug:
                raise ValueError("NATIVE_FROZEN_EXECUTOR_REQUIRED")
            if role == "data_prepare" and node.skill_slug not in {
                "data_prep_v1",
                "ml_batch_score_v1",
            }:
                raise ValueError("NATIVE_COMPUTE_SUBMISSION_UNSUPPORTED")
            if role == "judge" and node.skill_slug != "evaluate_v2":
                raise ValueError("NATIVE_TYPED_JUDGE_REQUIRED")
    # Only ingress sources may sit outside this fixed linear composition.
    # Loops, subflows, retries and parallel branches need their own qualified port.
    if any(
        node.kind not in {"source", "secret"}
        for key, node in graph.nodes.items()
        if key not in bound
    ):
        raise ValueError("NATIVE_UNBOUND_EXECUTION")
    ordered = [profile.role_nodes[role] for role in roles]
    expected_edges = set(zip(ordered, ordered[1:]))
    actual = {(e.source, e.target) for e in graph.edges if e.source in bound}
    if actual != expected_edges or any(e.kind == "branch" for e in graph.edges):
        raise ValueError("NATIVE_COMPOSITION_EDGES_INVALID")
    if any(
        e.source not in bound and e.target != ordered[0] and graph.nodes[e.source].kind != "secret"
        for e in graph.edges
    ):
        raise ValueError("NATIVE_SOURCE_BINDING_UNSUPPORTED")
    if any(
        graph.nodes[e.source].kind == "secret" and graph.nodes[e.target].kind != "task"
        for e in graph.edges
    ):
        raise ValueError("NATIVE_SECRET_BINDING_INVALID")
    return profile.model_dump(mode="json")


def workflow_id(run_id):
    return f"agentium-native:{run_id}"


def request_for_run(db, run):
    from app.services.execution.contracts import ExecutionPolicy

    policy = ExecutionPolicy.model_validate(run.execution_policy)
    profile = freeze_profile(run, policy.native_profile)
    if policy.engine != "temporal" or profile_digest(profile) != policy.native_profile_digest:
        raise ValueError("NATIVE_PROFILE_MISMATCH")
    return {
        "workspace_id": run.workspace_id,
        "run_id": run.id,
        "profile_digest": policy.native_profile_digest,
        "runtime_revision": policy.runtime_revision,
    }
