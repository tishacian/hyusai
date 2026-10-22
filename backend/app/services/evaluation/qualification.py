"""Qualified campaign execution on the canonical runtime, with a terminal human boundary.

These permissions come from reviewed server code and frozen executors. A node's
``effect`` label, an authored alias or an input flag cannot grant them.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime

READ_SKILLS = frozenset(
    {
        "decide_next_v1",
        "skill_search_v1",
        "semantic_search_v1",
        "llm_rag_answer_v1",
        "claim_audit_v1",
        "azure_llm_v1",
        "openai_llm_v1",
        "workspace_llm_v1",
        "azure_openai_llm_v1",
        "postgresql_claim_snapshot_v1",
        "ecommerce_policy_evidence_v1",
        "ecommerce_delivery_evidence_v1",
        "ecommerce_refund_evidence_v1",
        "ecommerce_resolution_propose_v1",
        "ecommerce_sav_context_v1",
    }
)
ISOLATED_SKILLS = frozenset(
    {"ecommerce_sav_dataset_v1", "data_prep_v1", "ml_batch_score_v1", "evaluate_v2"}
)
STRUCTURAL_KINDS = frozenset({"source", "sink", "asset", "decision", "condition", "join", "fork"})


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def executor_mode(slug, contract):
    executor = contract.get("executor") or {}
    if executor:
        if executor.get("kind") == "prompt_template":
            return "read"
        if executor.get("kind") != "registry_call":
            return None
        slug = (executor.get("params") or {}).get("skill_slug")
        # Aliases cannot introduce graph-owned DataOps/evaluation configuration.
        return "read" if slug in READ_SKILLS else None
    return (
        "read" if slug in READ_SKILLS else "isolated_compute" if slug in ISOLATED_SKILLS else None
    )


def profile(flow, contract, ingress=None):
    nodes = {n["id"]: n for n in flow.get("nodes", [])}
    start = (ingress or {}).get("source_node_id")
    if start is None:
        sources = [n["id"] for n in nodes.values() if n.get("kind") == "source"]
        start = sources[0] if len(sources) == 1 else None
    issues, found, pending = [], {}, [start] if start else []
    if not start:
        issues.append(
            {"code": "EVALUATION_INGRESS_REQUIRED", "message": "Select one execution ingress."}
        )
    while pending:
        key = pending.pop()
        if key in found:
            continue
        node = nodes.get(key)
        if node is None:
            issues.append(
                {
                    "code": "EVALUATION_NODE_MISSING",
                    "node_id": key,
                    "message": "Referenced node is unavailable.",
                }
            )
            continue
        kind = node.get("kind") or node.get("type")
        cfg = node.get("config") or {}
        frozen = (contract.get("nodes") or {}).get(key) or {}
        slug = frozen.get("skill_slug") or cfg.get("skill_slug") or node.get("skill_slug")
        row = {"node_id": key, "kind": kind, "skills": {}}
        found[key] = row
        if kind == "hitl":
            row["execution_mode"] = "human_boundary"
            if cfg.get("prompt_kind") in {"review_dataset_labels", "approve_model_retraining"}:
                issues.append(
                    {
                        "code": "EVALUATION_GATE_UNQUALIFIED",
                        "node_id": key,
                        "message": "This gate performs domain-specific binding and is not qualified.",
                    }
                )
            continue  # No action beyond this boundary is ever qualified.
        if kind in STRUCTURAL_KINDS:
            row["execution_mode"] = "read"
        elif kind in {"task", "skill", "retry", "loop", "agent_loop"}:
            mode = executor_mode(slug, frozen)
            row["execution_mode"] = mode
            if mode is None:
                issues.append(
                    {
                        "code": "EVALUATION_EXECUTOR_UNQUALIFIED",
                        "node_id": key,
                        "skill_slug": slug,
                        "message": "This executor has no qualified campaign adapter.",
                    }
                )
            else:
                row["skills"][slug] = {"mode": mode, "contract_sha256": digest(frozen)}
            if slug == "ml_batch_score_v1":
                params = cfg.get("params") or {}
                if not params.get("model_id") or type(params.get("pinned_version")) is not int:
                    issues.append(
                        {
                            "code": "EVALUATION_MODEL_PIN_REQUIRED",
                            "node_id": key,
                            "message": "Select an exact model and version before comparing.",
                        }
                    )
            if kind == "agent_loop":
                tools = (frozen.get("tool_contract") or {}).get("nodes") or {}
                for tool in cfg.get("skill_allowlist", []):
                    binding = tools.get(tool)
                    tool_mode = executor_mode(tool, binding) if binding is not None else None
                    if tool_mode != "read":
                        issues.append(
                            {
                                "code": "EVALUATION_AGENT_TOOL_UNQUALIFIED",
                                "node_id": key,
                                "skill_slug": tool,
                                "message": "Agent tools must have a frozen qualified read executor.",
                            }
                        )
                    else:
                        row["skills"][tool] = {
                            "mode": tool_mode,
                            "contract_sha256": digest(binding),
                        }
        else:
            issues.append(
                {
                    "code": "EVALUATION_NODE_UNQUALIFIED",
                    "node_id": key,
                    "message": "Delegation, arbitrary computation or this node kind is not qualified.",
                }
            )
        for edge in flow.get("edges", []):
            source, target = (
                edge.get("from", edge.get("source")),
                edge.get("to", edge.get("target")),
            )
            if source == key:
                pending.append(target)
    return {
        "schema_version": 1,
        "eligible": not issues,
        "issues": issues,
        "ingress_id": start,
        "stop_at_human": True,
        "flow_sha256": digest(flow),
        "contract_sha256": digest(contract),
        "nodes": [found[key] for key in sorted(found)],
    }


def bound_profile(db, run):
    campaign_id = getattr(run, "evaluation_campaign_id", None)
    if campaign_id is None:
        return None
    from app.models.evaluation_campaign import EvaluationCampaign

    campaign = db.get(EvaluationCampaign, campaign_id)
    binding = run.evaluation_binding or {}
    side = binding.get("side")
    frozen = (
        ((campaign.snapshot or {}).get("execution_profiles") or {}).get(side) if campaign else None
    )
    matches = (
        [
            item
            for item in (campaign.results or [])
            if item.get("case_id") == binding.get("case_id")
            and item.get("repetition_index", 0) == binding.get("repetition_index", 0)
            and (item.get(side) or {}).get("run_id") == run.id
        ]
        if campaign and side in {"baseline", "candidate"}
        else []
    )
    if (
        not campaign
        or campaign.workspace_id != run.workspace_id
        or campaign.system_id != run.system_id
        or not frozen
        or not frozen.get("eligible")
        or len(matches) != 1
        or binding.get("profile_sha256") != digest(frozen)
        or frozen.get("flow_sha256") != digest(run.flow_snapshot)
        or frozen.get("contract_sha256") != digest(run.execution_contract)
    ):
        raise ValueError("EVALUATION_BINDING_INVALID")
    from app.models.tabular import MLModel

    for identity in (campaign.snapshot or {}).get("model_manifest", []):
        if identity["side"] != side:
            continue
        model = db.get(MLModel, identity["model_id"])
        if (
            model is None
            or model.workspace_id != run.workspace_id
            or model.status != "ready"
            or model.version != identity["version"]
            or model.model_uri != identity["artifact"]
            or digest(model.signature_json) != identity["signature_sha256"]
            or digest((model.metrics_json or {}).get("artifact"))
            != identity["artifact_metadata_sha256"]
        ):
            raise ValueError("EVALUATION_MODEL_CHANGED")
    return frozen


def authorize_invocation(db, run, *, node_id, skill_slug):
    frozen = bound_profile(db, run)
    if frozen is None:
        return
    if run.status in {"completed", "cancelled", "failed"} or run.cancel_requested:
        raise ValueError("EVALUATION_EXECUTION_TERMINAL")
    node = next((n for n in frozen["nodes"] if n["node_id"] == node_id), None)
    if node is None or skill_slug not in node["skills"]:
        raise ValueError("EVALUATION_INVOCATION_NOT_QUALIFIED")


def finish_at_human_gate(db, run):
    frozen = bound_profile(db, run)
    if frozen is None:
        return None
    from app.models.decision import Decision

    pause = next(
        (cp for cp in reversed(run.checkpoints or []) if cp.get("kind") == "hitl_pause"), None
    )
    if run.status != "hitl_pending" or not pause:
        raise ValueError("EVALUATION_HUMAN_BOUNDARY_MISSING")
    gate = next((node for node in frozen["nodes"] if node["node_id"] == pause.get("node_id")), None)
    if not gate:
        raise ValueError("EVALUATION_HUMAN_BOUNDARY_INVALID")
    decision = db.get(Decision, pause.get("decision_id")) if pause.get("decision_id") else None
    if decision and (decision.workspace_id != run.workspace_id or decision.target_id != run.id):
        raise ValueError("EVALUATION_HUMAN_BOUNDARY_INVALID")
    if decision:
        # System rejection closes the test, never impersonates a reviewer.
        decision.status = "rejected"
        decision.expires_at = None
        decision.rationale = {
            **(decision.rationale or {}),
            "evaluation_boundary": True,
            "evaluation_campaign_id": run.evaluation_campaign_id,
        }
    boundary = "policy_gate" if pause.get("membrane_egress") else "human_gate"
    run.checkpoints = [
        *(run.checkpoints or []),
        {
            "kind": "evaluation_boundary",
            "boundary": boundary,
            "node_id": pause.get("node_id"),
            "decision_id": pause.get("decision_id"),
            "at": datetime.utcnow().isoformat(),
        },
    ]
    elapsed = (pause.get("state") or {}).get("accumulated_ms")
    if type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0:
        run.duration_ms = round(elapsed, 2)
    run.status, run.completed_at = "cancelled", datetime.utcnow()
    run.error = "EVALUATION_STOPPED_AT_HUMAN_GATE"
    db.commit()
    return {
        "id": run.id,
        "status": run.status,
        "evaluation_termination": boundary,
        "awaiting_decision": None,
    }


def selected_output(run, case):
    # A membrane-held result must never be copied into an evaluator's prompt.
    if any(
        cp.get("kind") == "hitl_pause" and cp.get("membrane_egress") for cp in run.checkpoints or []
    ):
        return None, None
    selector = case.get("output_selector")
    if not selector:
        return run.output_ref, None
    candidates = [
        i
        for i in run.invocations
        if i.run_id == run.id
        and i.status == "completed"
        and not i.error
        and i.skill_slug == selector["skill_slug"]
        and (not selector.get("node_id") or (i.trace or {}).get("node_id") == selector["node_id"])
    ]
    # Selection is the last executed attempt, not the best evaluated answer.
    if not candidates:
        return None, None
    invocation = sorted(candidates, key=lambda i: (i.started_at or datetime.min, i.id))[-1]
    value = invocation.output_ref
    for key in selector.get("path", []):
        if not isinstance(value, dict) or key not in value:
            return None, invocation.id
        value = value[key]
    return value, invocation.id


def trajectory_results(run, assertions):
    invocations = [i for i in run.invocations if i.run_id == run.id]
    good = [i for i in invocations if i.status == "completed" and not i.error]
    good.sort(key=lambda i: (i.started_at or datetime.min, i.id))
    boundary = any(
        cp.get("kind") == "evaluation_boundary" and cp.get("boundary") == "human_gate"
        for cp in run.checkpoints or []
    )
    results = []
    for check in assertions:
        op, slug = check["operator"], check.get("skill_slug")
        ids = [i.id for i in good if i.skill_slug == slug]
        if op == "tool_required":
            passed = bool(ids)
        elif op == "tool_forbidden":
            passed = not any(i.skill_slug == slug for i in invocations)
        elif op == "max_calls":
            passed = len(invocations) <= check["limit"]
        elif op == "human_gate":
            passed = boundary
        elif op == "no_business_effects":
            passed = bool(getattr(run, "evaluation_campaign_id", None)) and all(
                i.skill_slug in READ_SKILLS | ISOLATED_SKILLS or i.skill_slug.startswith("ws.")
                for i in invocations
            )
        elif op == "before":
            before = [n for n, i in enumerate(good) if i.skill_slug == check["before_skill"]]
            after = [n for n, i in enumerate(good) if i.skill_slug == check["after_skill"]]
            passed = bool(before and after and min(before) < min(after))
        else:
            raise ValueError("EVALUATION_ASSERTION_UNKNOWN")
        results.append(
            {
                "id": check["id"],
                "passed": passed,
                "severity": check.get("severity", "normal"),
                "evidence_basis": "canonical_invocation_ledger",
                "invocation_ids": ids,
            }
        )
    return results
