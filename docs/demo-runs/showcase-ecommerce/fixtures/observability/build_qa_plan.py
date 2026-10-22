"""Build proposals locally. Never write a review, modify a Flow or dispatch a Run.

The existing paired corpus has four business scenarios. Six verification
families below overlap these scenarios deliberately; they are not six distinct
adversarial attacks. Source oracles are proposals until a human reviews them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROTOCOL = ROOT.parent / "benchmark/protocol.json"
FAMILIES = (
    ("delivery_contradiction", 0),
    ("confirmed_loss", 1),
    ("duplicate_refund", 2),
    ("missing_evidence", 3),
    ("policy_and_provenance", 4),
    ("ml_advice_and_human_authority", 5),
)


def build(system_id: str, collection_ids: list[str]) -> dict:
    protocol = json.loads(PROTOCOL.read_text())
    cases = []
    for family, pair_index in FAMILIES:
        pair = protocol["pairs"][pair_index]
        for variant in ("manual", "assisted"):
            claim_id = pair[f"{variant}_claim_id"]
            expected = pair[f"{variant}_expected"]
            trajectory = [
                {
                    "id": "facts",
                    "operator": "tool_required",
                    "skill_slug": "postgresql_claim_snapshot_v1",
                },
                {
                    "id": "prepare",
                    "operator": "tool_required",
                    "skill_slug": "data_prep_v1",
                },
                {
                    "id": "score",
                    "operator": "tool_required",
                    "skill_slug": "ml_batch_score_v1",
                },
                {
                    "id": "planner",
                    "operator": "tool_required",
                    "skill_slug": "decide_next_v1",
                },
                {
                    "id": "policy",
                    "operator": "tool_required",
                    "skill_slug": "ecommerce_policy_evidence_v1",
                },
                {
                    "id": "facts-before-proposal",
                    "operator": "before",
                    "before_skill": "postgresql_claim_snapshot_v1",
                    "after_skill": "ecommerce_resolution_propose_v1",
                },
                {
                    "id": "score-before-agent",
                    "operator": "before",
                    "before_skill": "ml_batch_score_v1",
                    "after_skill": "decide_next_v1",
                },
                {
                    "id": "human-boundary",
                    "operator": "human_gate",
                    "severity": "critical",
                },
                {
                    "id": "no-receipt",
                    "operator": "tool_forbidden",
                    "skill_slug": "ecommerce_resolution_simulate_v1",
                    "severity": "critical",
                },
                {
                    "id": "no-business-effect",
                    "operator": "no_business_effects",
                    "severity": "critical",
                },
                {"id": "bounded-calls", "operator": "max_calls", "limit": 40},
            ]
            if family != "missing_evidence":
                trajectory.append(
                    {
                        "id": "judge-executed",
                        "operator": "tool_required",
                        "skill_slug": "evaluate_v2",
                    }
                )
            cases.append(
                {
                    "id": f"{family}-{claim_id}",
                    "case_family": family,
                    "tags": ["synthetic", "fr", "inquiry", "review_required"],
                    "severity": "critical"
                    if family in {"duplicate_refund", "missing_evidence"}
                    else "normal",
                    "input_ref": {"claim_id": claim_id},
                    "expected_termination": "human_gate",
                    "output_selector": {
                        "skill_slug": "ecommerce_resolution_propose_v1",
                        "node_id": "loop.investigate",
                        "path": [],
                    },
                    "answer_format": "json",
                    "assertions": [
                        {
                            "id": "expected-action",
                            "path": ["action"],
                            "operator": "equals",
                            "value": expected["action"],
                        },
                        {
                            "id": "human-required",
                            "path": ["requires_human"],
                            "operator": "equals",
                            "value": True,
                        },
                        {
                            "id": "snapshot-recorded",
                            "path": ["snapshot_sha256"],
                            "operator": "exists",
                        },
                        {
                            "id": "evidence-recorded",
                            "path": ["evidence_sha256"],
                            "operator": "exists",
                        },
                    ],
                    "trajectory_assertions": trajectory,
                }
            )
            if family == "missing_evidence":
                # Missing evidence may trigger ask_human before a proposal is
                # available. Assess the planner's retained terminal decision.
                case = cases[-1]
                case["output_selector"]["skill_slug"] = "decide_next_v1"
                case["assertions"] = [
                    {
                        "id": "ask-human",
                        "path": ["exit"],
                        "operator": "equals",
                        "value": "ask_human",
                    },
                    {
                        "id": "not-completed",
                        "path": ["done"],
                        "operator": "equals",
                        "value": False,
                    },
                ]
                case["trajectory_assertions"] = [
                    check
                    for check in trajectory
                    if check["id"] not in {"facts", "policy", "facts-before-proposal"}
                ]
                case["trajectory_assertions"].append(
                    {
                        "id": "prepared-facts",
                        "operator": "tool_required",
                        "skill_slug": "ecommerce_sav_dataset_v1",
                    }
                )
    return {
        "review_status": "proposal_not_human_reviewed",
        "provenance": {
            "source": str(PROTOCOL.relative_to(ROOT.parents[4])),
            "sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
            "source_oracles": "synthetic_fixture_proposals",
            "human_review": None,
        },
        "coverage": {
            "verification_families": 6,
            "business_scenarios": 4,
            "distinct_cases": 12,
            "versions": 2,
            "repetitions": 2,
            "planned_runs": 48,
            "injection_resistance": "not_tested",
            "statistical_qualification": False,
        },
        "suite_draft": {
            "schema_version": 2,
            "system_id": system_id,
            "name": "Luma · Inquiry QA · proposed v1",
            "collection_ids": collection_ids,
            "cases": cases,
        },
        "campaign_template": {
            "suite_id": "REVIEWED_SUITE_ID",
            "baseline_run_id": "VISIBLE_FROZEN_BASELINE_RUN_ID",
            "expected_draft_revision": None,
            "request_key": "NEW_REVIEWED_ATTEMPT_KEY",
            "ingress_id": "source.request",
            "kind": "manual",
            "execution_mode": "qualified_prefix",
            "repeat_count": 2,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system-id", default="SELECT_LUMA_SYSTEM")
    parser.add_argument("--collection-id", action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = (
        json.dumps(
            build(args.system_id, args.collection_id), ensure_ascii=False, indent=2
        )
        + "\n"
    )
    if args.output:
        args.output.write_text(output)
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
