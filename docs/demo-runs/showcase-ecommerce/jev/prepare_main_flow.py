"""Prepare Jev in the published Luma graph, without writing its user draft.

This script is deliberately offline. Deployment, reviewed publication and Work
release are separate operations; an artifact produced here is not activation.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from prepare import MODEL, SYSTEM_ID, flow_identity, question_config, sha

JEV_NODE_ID = "quality.second_opinion_jev"
JUDGE_NODE_ID = "quality.review"
SHIFTED_NODE_IDS = (JUDGE_NODE_ID, "hitl.review", "task.simulate", "sink.receipt")
INPUT_ISOLATION = {"input_mode": "mapped", "inputs_map": {}, "passthrough_inputs": []}


def require(condition, code):
    if not condition:
        raise ValueError(code)


def candidate_flow(published):
    """Add one independent opinion, retaining GPT's reviewed question contract."""
    flow = copy.deepcopy(published)
    nodes = {node["id"]: node for node in flow["nodes"]}
    require(len(nodes) == len(flow["nodes"]), "DUPLICATE_NODE_ID")
    require(JEV_NODE_ID not in nodes, "JEV_ALREADY_PRESENT")
    require(
        all(node_id in nodes for node_id in SHIFTED_NODE_IDS),
        "LUMA_REVIEW_PATH_REQUIRED",
    )
    judge = nodes[JUDGE_NODE_ID]
    config = judge.get("config", {})
    typed = config.get("typed_evaluation", {})
    require(config.get("skill_slug") == "evaluate_v2", "EXISTING_JUDGE_REQUIRED")
    require(typed.get("tariff", {}).get("model") == "gpt-5", "EXISTING_GPT5_REQUIRED")
    require(bool(typed.get("run_evidence", {}).get("sources")), "RUN_EVIDENCE_REQUIRED")
    require(
        not config.get("inputs_map") and not config.get("passthrough_inputs"),
        "JUDGE_INPUT_CONTRACT_CHANGED",
    )
    require(
        config.get("input_mode") in (None, "mapped"), "JUDGE_INPUT_CONTRACT_CHANGED"
    )
    require(nodes["hitl.review"].get("kind") == "hitl", "HUMAN_REVIEW_REQUIRED")
    require(
        nodes["task.simulate"].get("config", {}).get("skill_slug")
        == "ecommerce_resolution_simulate_v1",
        "SIMULATED_ACTION_REQUIRED",
    )
    for source, target in [
        (JUDGE_NODE_ID, "hitl.review"),
        ("hitl.review", "task.simulate"),
        ("task.simulate", "sink.receipt"),
    ]:
        require(
            any(
                edge.get("from") == source and edge.get("to") == target
                for edge in flow["edges"]
            ),
            "LUMA_REVIEW_PATH_REQUIRED",
        )
    incoming = [edge for edge in flow["edges"] if edge.get("to") == JUDGE_NODE_ID]
    require(len(incoming) == 1, "JUDGE_INCOMING_PATH_CHANGED")
    ready = incoming[0]
    require(
        ready.get("from") == "decision.ready"
        and ready.get("kind") == "branch"
        and ready.get("branch_label") == "ready",
        "READY_BRANCH_REQUIRED",
    )
    # A reviewed source edge with explicit destination ports needs a different
    # candidate; never silently transfer a GPT input port onto Jev.
    require(not ready.get("to_port"), "JUDGE_DESTINATION_PORT_REVIEW_REQUIRED")

    jev_config = question_config()
    jev_config["run_evidence"] = copy.deepcopy(typed["run_evidence"])
    jev_node = {
        "id": JEV_NODE_ID,
        "type": "skill",
        "kind": "task",
        "label": "Second avis SAV · Jev",
        "position": copy.deepcopy(judge["position"]),
        "config": {
            "skill_slug": "evaluate_v2",
            "typed_evaluation": jev_config,
            "on_error": "fail",
            **copy.deepcopy(INPUT_ISOLATION),
        },
    }
    config.update(copy.deepcopy(INPUT_ISOLATION))
    for node_id in SHIFTED_NODE_IDS:
        nodes[node_id]["position"]["x"] += 320
    # Preserve ordering, edge identity, source port and branch metadata.
    ready["to"] = JEV_NODE_ID
    flow["edges"].append({"from": JEV_NODE_ID, "to": JUDGE_NODE_ID, "kind": "data"})
    flow["nodes"].insert(flow["nodes"].index(judge), jev_node)
    return flow


def build(state):
    identity = flow_identity(state)
    if state.get("status") == 200:
        state = state.get("data", state.get("body"))
    published = state["published"]["flow_definition"]
    candidate = candidate_flow(published)
    common = {
        "flow_definition": candidate,
        "expected_flow_sha256": sha(candidate),
        "expected_draft_revision": identity["draft_revision"],
        "expected_draft_flow_sha256": identity["draft_flow_sha256"],
        "expected_published_version_id": identity["published_version_id"],
    }
    return {
        "format": "luma-jev-main-flow-candidate-v1",
        "applied": False,
        "qualified_live": False,
        "preserved_flow": identity,
        "candidate_flow_sha256": sha(candidate),
        "added_node_id": JEV_NODE_ID,
        "model": MODEL,
        "rubric_human_reviewed": False,
        "runtime_requirements": [
            "task_config_input_mode_mapped",
            "typed_judge_batch_scope_per_engine_node",
            "reviewed_candidate_publication_preserves_user_draft",
        ],
        "qualification_before_publication": {
            "method": "POST",
            "path": f"/api/v1/systems/{SYSTEM_ID}/flow-workbench/preview-runs",
            "copy_from_review_body": ["flow_definition", "expected_flow_sha256"],
            "body": {
                "acknowledge_real_side_effects": True,
                "ingress_id": "source.request",
                "kind": "manual",
                "input_ref": {"claim_id": "RC-1042"},
            },
            "stop_at": "hitl.review; do not approve the simulated action during qualification",
            "execution_surface": "builder_preview",
            "mandate_precondition": {
                "draft_policy_sha256": identity["draft_policy_sha256"],
                "published_policy_sha256": identity["published_policy_sha256"],
                "must_match": True,
                "reason": "Full previews inherit the draft mandate; candidate publication inherits the published mandate.",
            },
        },
        "review_request": {
            "method": "POST",
            "path": f"/api/v1/systems/{SYSTEM_ID}/flow/review-candidate",
            "body": common,
        },
        "publish_after_review": {
            "method": "POST",
            "path": f"/api/v1/systems/{SYSTEM_ID}/flow/publish-candidate",
            "additional_fields": {
                "message": "Ajouter un second avis Jev avant la revue GPT-5 citée et la validation humaine ; préserver le brouillon utilisateur.",
            },
            "required_from_review": {
                "expected_review_sha256": "candidate.review_sha256",
                "expected_execution_contract_sha256": "candidate.execution_contract_sha256",
            },
        },
        "work_activation": "Publish alone does not retarget Work: review bindings, triage composition and a coherent application release separately.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flow-state", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    plan = build(json.loads(args.flow_state.read_text()))
    # Exclusive create: do not overwrite a previously reviewed candidate.
    with args.out.open("x") as stream:
        json.dump(plan, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {
                "applied": False,
                "candidate_flow_sha256": plan["candidate_flow_sha256"],
                "added_node_id": JEV_NODE_ID,
            }
        )
    )


if __name__ == "__main__":
    main()
