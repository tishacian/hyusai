"""Exercise the checked-in plan against pure product validators; never apply."""

import argparse
import json
from pathlib import Path

from app.services.chains.dag_validator import validate_flow
from app.services.membrane.enforcement import (
    ValveUsage,
    enforce_inbound_collections,
    evaluate_capability,
    evaluate_valves,
)
from app.services.membrane.spec import MembraneSpec
from app.services.model_plane.skill_capabilities import is_verified_non_text_skill
from app.services.run_engine.agent_loop import build_decision_context
from app.services.run_engine.execution_contract import canonical_flow_sha256
from app.services.run_engine.variable_pool import VariablePool, apply_inputs_map


def qualify(plan):
    candidate = plan["publication_candidate"]
    checks = []

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    issues = validate_flow(candidate)
    check(
        "published_candidate_has_no_validation_errors",
        not any(issue.level == "error" for issue in issues),
    )
    check(
        "canonical_flow_hash_matches",
        canonical_flow_sha256(candidate) == plan["target_flow_sha256"],
    )
    loop = next(n for n in candidate["nodes"] if n["id"] == "loop.investigate")[
        "config"
    ]
    context, evidence = build_decision_context(
        loop,
        {
            **{key: {"source": key} for key in loop["decision_context"]["keys"]},
            "unselected": "must not reach the planner",
        },
    )
    check(
        "only_explicit_context_keys_reach_model",
        list(context) == loop["decision_context"]["keys"]
        and "unselected" not in context,
    )
    check(
        "context_has_complete_coverage_and_digest",
        not evidence["missing_keys"] and len(evidence["sha256"]) == 64,
    )

    shadow = MembraneSpec.from_dict(plan["shadow_mandate_candidate"])
    enforced = MembraneSpec.from_dict(plan["enforce_mandate_candidate_not_activated"])
    classifications = {}
    for slug in enforced.capabilities.allowed_skills:
        non_text = is_verified_non_text_skill(slug, None)
        classifications[slug] = (
            "server_verified_non_text" if non_text else "model_identity_required"
        )
        result = evaluate_capability(
            enforced,
            skill=slug,
            model=None if non_text else "openai:gpt-5",
            model_required=not non_text,
        )
        check("scope_accepts_" + slug, result.allowed)
    check(
        "forbidden_skill_is_blocked",
        not evaluate_capability(
            enforced, skill="unlisted_tool", model="openai:gpt-5"
        ).allowed,
    )
    check(
        "wrong_model_is_blocked",
        not evaluate_capability(
            enforced, skill="decide_next_v1", model="openai:unlisted-model"
        ).allowed,
    )
    check(
        "missing_model_identity_is_blocked",
        not evaluate_capability(enforced, skill="decide_next_v1").allowed,
    )
    denied = enforce_inbound_collections(enforced, ["outside-the-reviewed-scope"])
    observed = enforce_inbound_collections(shadow, ["outside-the-reviewed-scope"])
    check("foreign_collection_is_blocked_in_enforce", denied.blocked)
    check(
        "shadow_observes_without_claiming_enforcement",
        not observed.blocked and observed.would_block,
    )
    check(
        "unset_numeric_valves_do_not_invent_coverage",
        evaluate_valves(enforced, ValveUsage()).allowed,
    )

    sink = next(n for n in candidate["nodes"] if n["id"] == "sink.queue")["config"]
    pool = VariablePool()
    pool.set_namespace(
        "sav.score",
        {
            "dataset_id": "scored-dataset",
            "scored_rows": 23,
            "model": {"name": "SLA classifier", "version": 5},
        },
    )
    output = apply_inputs_map(sink, pool, {"chosen_branch": "queue"})
    check(
        "sink_exposes_business_result",
        output.get("case_count") == 23
        and output.get("model_version") == 5
        and output.get("dataset_id") == "scored-dataset",
    )
    check("missing_exclusion_measurement_stays_unknown", "excluded_count" not in output)
    return {
        "qualification": "offline_product_contracts_only",
        "applied": False,
        "live_qualified": False,
        "target_flow_sha256": plan["target_flow_sha256"],
        "checks_passed": checks,
        "runtime_classification": classifications,
        "warnings": [
            {"level": issue.level, "code": issue.code, "node_id": issue.node_id}
            for issue in issues
        ],
        "remaining": [
            "Fresh read CAS and model catalogue options",
            "Deployed worker revision verification",
            "Real shadow runs on all three business entries",
            "Negative boundary tests through the deployed dispatcher",
            "Coordinated Work bindings, triage and immutable releases",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = qualify(json.loads(args.plan.read_text()))
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "checks_passed": len(result["checks_passed"]),
                "live_qualified": False,
                "applied": False,
            }
        )
    )
