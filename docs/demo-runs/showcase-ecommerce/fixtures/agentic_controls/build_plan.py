"""Build a reviewable Luma configuration from reads. Never applies or calls HTTP.

This is demo configuration, not product behavior. No token, environment
credential, database connection or installation command is read by this file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path

SYSTEM = "f3ea83de-df89-45ec-8a85-c00d676b2713"
CONTEXT_KEYS = ["claim_id", "sla_prediction", "sla_model", "sav_facts", "data_quality"]
MODEL_ROUTE = "openai:gpt-5"
WORK_BINDINGS = [
    "showcase.claims.investigate",
    "showcase.claims.refresh_queue",
    "showcase.claims.forecast",
]


def sha(value):
    # Same serialization as canonical_flow_sha256; JSON array ordering matters.
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def body(path):
    payload = json.loads(Path(path).read_text())
    if payload.get("status") != 200:
        raise ValueError("SUCCESSFUL_SNAPSHOT_REQUIRED")
    return payload.get("data", payload.get("body"))


def by_id(flow, node_id):
    matches = [node for node in flow["nodes"] if node["id"] == node_id]
    if len(matches) != 1:
        raise ValueError("UNIQUE_REVIEWED_NODE_REQUIRED:" + node_id)
    return matches[0]


def contract_skills(contract):
    result = set()
    for node in contract.get("nodes", {}).values():
        if node.get("skill_slug"):
            result.add(node["skill_slug"])
        result.update(contract_skills(node.get("tool_contract") or {}))
    return result


def configured_flow(flow):
    result = deepcopy(flow)
    loop = by_id(result, "loop.investigate")["config"]
    if set(loop.get("inputs_map", {})) != set(CONTEXT_KEYS):
        raise ValueError("REVIEWED_CONTEXT_MAPPING_CHANGED")
    if loop.get("privilege_tier") != "recommend" or loop.get("on_budget") != "exit":
        raise ValueError("REVIEWED_LOOP_AUTONOMY_CHANGED")
    loop["model"] = MODEL_ROUTE
    loop["decision_context"] = {"keys": CONTEXT_KEYS[:], "max_bytes": 16384}
    loop["budget"] = {"max_turns": 12, "deadline_ms": 120000}
    sink = by_id(result, "sink.queue")
    config = deepcopy(sink.get("config") or {})
    config["inputs_map"] = {
        "case_count": {
            "node_id": "sav.score",
            "path": ["scored_rows"],
            "required": True,
        },
        "excluded_count": {
            "node_id": "sav.score",
            "path": ["excluded_rows"],
            "required": False,
        },
        "dataset_id": {
            "node_id": "sav.score",
            "path": ["dataset_id"],
            "required": True,
        },
        "model_name": {
            "node_id": "sav.score",
            "path": ["model", "name"],
            "required": True,
        },
        "model_version": {
            "node_id": "sav.score",
            "path": ["model", "version"],
            "required": True,
        },
    }
    config["output_schema"] = {
        "type": "object",
        "required": ["case_count", "dataset_id", "model_name", "model_version"],
        "properties": {
            "case_count": {
                "type": "integer",
                "minimum": 0,
                "title": "Dossiers priorisés",
            },
            "excluded_count": {
                "type": ["integer", "null"],
                "minimum": 0,
                "title": "Dossiers exclus",
                "description": "Absent si le moteur ne mesure pas les exclusions ; ne pas afficher zéro.",
            },
            "dataset_id": {"type": "string", "title": "Dataset produit"},
            "model_name": {"type": "string", "title": "Modèle utilisé"},
            "model_version": {
                "type": "integer",
                "minimum": 1,
                "title": "Version du modèle",
            },
        },
        # Legacy overlay keeps predecessor fields. This change does not claim
        # to have switched the entire published Flow to strict I/O.
        "additionalProperties": True,
    }
    sink["config"] = config
    return result


def preserve_draft(published, draft):
    """Rebase only reviewed fields; refuse to overwrite conflicting edits."""
    for node_id, fields in {
        "loop.investigate": [
            "model",
            "decision_context",
            "budget",
            "inputs_map",
            "privilege_tier",
            "on_budget",
        ],
        "sink.queue": ["inputs_map", "output_schema"],
    }.items():
        old = by_id(published, node_id).get("config") or {}
        authored = by_id(draft, node_id).get("config") or {}
        for field in fields:
            if old.get(field) != authored.get(field):
                raise ValueError(f"USER_DRAFT_CONFLICT:{node_id}.{field}")
    # Starting from the whole draft preserves extra nodes, typed ports, edges,
    # user positions, top-level properties and unfinished preparations.
    return configured_flow(draft)


def build_plan(state, mandate, app):
    state, mandate, app = deepcopy(state), deepcopy(mandate), deepcopy(app)
    if state["system_id"] != SYSTEM or mandate["system_id"] != SYSTEM:
        raise ValueError("UNEXPECTED_SYSTEM")
    published, draft = state["published"], state["draft"]
    if published["version_number"] != 10:
        raise ValueError("REVIEW_PUBLISHED_VERSION_AGAIN")
    if draft["base_published_version_id"] != published["version_id"]:
        raise ValueError("DRAFT_BASE_CHANGED")
    for revision in (published, draft):
        if sha(revision["flow_definition"]) != revision["flow_sha256"]:
            raise ValueError("FLOW_SNAPSHOT_HASH_MISMATCH")
    md = mandate["draft"]
    if md["revision"] != draft["revision"] or md["flow_sha256"] != draft["flow_sha256"]:
        raise ValueError("FLOW_MANDATE_REVISION_MISMATCH")
    if md["snapshot_sha256"] != draft["control_policy_snapshot_sha256"]:
        raise ValueError("MANDATE_SNAPSHOT_MISMATCH")
    if not md.get("spec_is_seed") or mandate["published"].get("spec") is not None:
        raise ValueError("AUTHORED_MANDATE_REQUIRES_NEW_REVIEW")
    judge_route = by_id(published["flow_definition"], "quality.review")["config"][
        "typed_evaluation"
    ]["tariff"]
    if judge_route.get("provider") != "openai" or judge_route.get("model") != "gpt-5":
        raise ValueError("JUDGE_MODEL_ROUTE_REQUIRES_NEW_REVIEW")
    candidate = configured_flow(published["flow_definition"])
    preserved = preserve_draft(published["flow_definition"], draft["flow_definition"])
    skills = contract_skills(published["execution_contract"])
    expected = {
        n["config"]["skill_slug"]
        for n in candidate["nodes"]
        if (n.get("config") or {}).get("skill_slug")
    }
    expected.update(by_id(candidate, "loop.investigate")["config"]["skill_allowlist"])
    if skills != expected:
        raise ValueError("EXECUTION_CONTRACT_SKILL_SCOPE_DRIFT")
    collections = sorted(
        {
            n["config"]["collection_slug"]
            for n in candidate["nodes"]
            if n.get("type") == "source.collection"
        }
    )
    options = mandate["options"]
    for refs, category in ((skills, "skills"), (collections, "collections")):
        if not set(refs) <= {item["id"] for item in options[category]}:
            raise ValueError("MANDATE_REFERENCE_NOT_AUTHORIZED:" + category)
    if "gpt-5" not in {item["id"] for item in options["models"]}:
        raise ValueError("REVIEWED_MODEL_NOT_CONFIGURED")
    policy = deepcopy(md["spec"])
    policy["enforcement_mode"] = "shadow"
    policy["inbound"]["collection_allowlist"] = collections
    policy["capabilities"]["allowed_skills"] = sorted(skills)
    policy["capabilities"]["allowed_models"] = ["gpt-5", MODEL_ROUTE]
    # No action or delegation grant is synthesized; all other facets survive.
    if any(
        value is not None and value is not False for value in policy["valves"].values()
    ):
        raise ValueError("AUTHORED_VALVES_REQUIRE_NEW_REVIEW")
    strict_candidate = {**deepcopy(policy), "enforcement_mode": "enforce"}
    ml_pins = []
    for node in candidate["nodes"]:
        params = (node.get("config") or {}).get("params") or {}
        if params.get("model_id"):
            ml_pins.append(
                {
                    "node_id": node["id"],
                    "model_id": params["model_id"],
                    "model_slug": params.get("model_slug"),
                    "version": params.get("pinned_version"),
                }
            )
    return {
        "format": "reviewed-agentic-controls-v1",
        "applied": False,
        "activation_ready": False,
        "status": "awaiting_deployment_and_fresh_read_review",
        "system_id": SYSTEM,
        "preconditions": {
            "published_version_id": published["version_id"],
            "published_flow_sha256": published["flow_sha256"],
            "draft_revision": draft["revision"],
            "draft_flow_sha256": draft["flow_sha256"],
            "mandate_snapshot_sha256": md["snapshot_sha256"],
            "team_app": {
                **{key: deepcopy(app[key]) for key in ("id", "slug", "updated_at")},
                "deployments": [
                    {
                        key: deepcopy(item[key])
                        for key in (
                            "id",
                            "channel",
                            "release_id",
                            "previous_release_id",
                            "audience",
                            "updated_at",
                        )
                        if key in item
                    }
                    for item in app["deployments"]
                ],
            },
            "team_app_draft_revision": app["draft"]["revision"],
            "team_app_content_sha256": app["draft"]["content_sha256"],
        },
        "backup": {
            "flow_definition": draft["flow_definition"],
            "mandate_spec": md["spec"],
            "team_app_draft": {
                key: deepcopy(app["draft"][key])
                for key in ("revision", "content_sha256", "pages", "binding_keys")
            },
        },
        "publication_candidate": candidate,
        "target_flow_sha256": sha(candidate),
        "preserved_draft_candidate": preserved,
        "preserved_draft_sha256": sha(preserved),
        "shadow_mandate_candidate": policy,
        "enforce_mandate_candidate_not_activated": strict_candidate,
        "llm_routes": [
            {
                "node_id": "loop.investigate",
                "provider": "openai",
                "model": "gpt-5",
                "qualified_model": MODEL_ROUTE,
            },
            {
                "node_id": "quality.review",
                "provider": "openai",
                "model": "gpt-5",
                "source": "existing typed_evaluation.tariff",
            },
        ],
        "unchanged_ml_registry_pins": ml_pins,
        "required_fresh_reads_before_writes": [
            "flow-state and mandate/draft (compare every CAS precondition)",
            "provider model catalogue and mandate options after saving candidate: openai:gpt-5 must be authorized",
            "three Work bindings, claims triage settings, all affected app releases and deployments (including reclamations and pilotage-sav-equipe)",
            "trigger delegates and schedules: remain paused; compare reviewed execution pins",
        ],
        "qualification_gates": [
            "Deployed API and workers support decision_context, explicit planner route, corrected provenance and sink result validation.",
            "Model allowlist applies to LLM operations only when server classification proves that; unknown LLM identity still fails closed. Qualify this before enforce.",
            "Shadow: manual case, queue, forecast, missing evidence and prior refund; inspect all would_block events and actual model provenance.",
            "Offline and isolated enforce: reject a forbidden Skill, foreign collection and wrong model; retain DataOps and ML calls without inventing model identities.",
            "No financial cap claim: cost/token valves remain unset. Loop has 12 turns and a 120-second between-calls deadline.",
            "A result without excluded_rows keeps excluded_count absent/unknown. Queue dataset and served model must resolve in this workspace.",
            "Human review and Judge remain separate; no automated payment or fabricated human benchmark.",
            "If editable resolution policy thresholds change, review and version Judge rubric question 5 and the human-review prompt together; their current 300 EUR wording must stay consistent with the supplied policy.",
        ],
        "work_cutover": {
            "binding_keys": WORK_BINDINGS,
            "target_version": "$response.flow_publish.published.version_id",
            "target_flow_sha256": sha(candidate),
            "triage_fields": ["scoring_version_id", "scoring_flow_sha256"],
            "unchanged_triage_fields": [
                "model_id",
                "model_version",
                "prediction_contract",
            ],
            "release_rule": "Retarget all three bindings, update triage, ready-check each consuming app and create an immutable release from its reviewed pages and fresh bindings; deploy by CAS before traffic resumes.",
            "blocked_until_fresh_reads": True,
        },
        "request_templates": {
            "save_flow_candidate": {
                "flow_definition": candidate,
                "expected_revision": draft["revision"],
            },
            "save_shadow_mandate": {
                "spec": policy,
                "expected_revision": "$response.save_flow_candidate.revision",
                "expected_snapshot_sha256": md["snapshot_sha256"],
            },
            "validate_mandate": {
                "expected_revision": "$response.save_shadow_mandate.draft.revision",
                "expected_snapshot_sha256": "$response.save_shadow_mandate.draft.snapshot_sha256",
            },
            "flow_publish": {
                "expected_draft_revision": "$response.save_shadow_mandate.draft.revision",
                "expected_published_version_id": published["version_id"],
                "expected_execution_contract_sha256": "$response.flow_diff.target.execution_contract_sha256",
                "breaking_change_intent": "acknowledged",
                "message": "Contexte explicite et modèle de décision, résultat métier de la file, mandat observé ; brouillon utilisateur préservé.",
            },
            "restore_user_draft_with_reviewed_additions": {
                "flow_definition": preserved,
                "expected_revision": "$response.flow_publish.draft.revision",
            },
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    plan = build_plan(
        body(args.snapshot_dir / "before-1.json"),
        body(args.snapshot_dir / "mandate-draft.json"),
        body(args.snapshot_dir / "team-app-published.json"),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "applied": False,
                "activation_ready": False,
                "target_flow_sha256": plan["target_flow_sha256"],
                "output": str(args.out),
            }
        )
    )


if __name__ == "__main__":
    main()
