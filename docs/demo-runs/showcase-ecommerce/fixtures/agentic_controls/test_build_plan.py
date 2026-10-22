"""Offline configuration tests; no HTTP, DB or credentials."""

import json
import unittest
from copy import deepcopy
from pathlib import Path

from build_plan import (
    CONTEXT_KEYS,
    SYSTEM,
    build_plan,
    configured_flow,
    contract_skills,
    preserve_draft,
    sha,
)


def snapshots():
    graph = {
        "schema_version": 3,
        "nodes": [
            {
                "id": "loop.investigate",
                "kind": "agent_loop",
                "position": {"x": 10, "y": 20},
                "config": {
                    "skill_slug": "decide_next_v1",
                    "skill_allowlist": ["read_case"],
                    "privilege_tier": "recommend",
                    "on_budget": "exit",
                    "goal": {
                        "objective": "Review the request",
                        "done_when": ["reviewed"],
                    },
                    "budget": {"max_turns": 12},
                    "inputs_map": {
                        key: {"node_id": "context", "path": [key]}
                        for key in CONTEXT_KEYS
                    },
                },
            },
            {
                "id": "sav.score",
                "kind": "task",
                "config": {
                    "skill_slug": "ml_batch_score_v1",
                    "params": {
                        "model_id": "ml-id",
                        "model_slug": "risk",
                        "pinned_version": 5,
                    },
                },
            },
            {"id": "sink.queue", "kind": "sink", "position": {"x": 40, "y": 20}},
            {
                "id": "quality.review",
                "kind": "task",
                "config": {
                    "skill_slug": "evaluate_v2",
                    "typed_evaluation": {
                        "tariff": {"provider": "openai", "model": "gpt-5"}
                    },
                },
            },
            {
                "id": "docs",
                "kind": "asset",
                "type": "source.collection",
                "config": {"collection_slug": "published-policy"},
            },
        ],
        "edges": [{"from": "sav.score", "to": "sink.queue"}],
    }
    contract = {
        "nodes": {
            "loop.investigate": {
                "skill_slug": "decide_next_v1",
                "tool_contract": {"nodes": {"tool": {"skill_slug": "read_case"}}},
            },
            "sav.score": {"skill_slug": "ml_batch_score_v1"},
            "quality.review": {"skill_slug": "evaluate_v2"},
        }
    }
    draft = deepcopy(graph)
    draft["nodes"][0]["position"] = {"x": 999, "y": 200}
    draft["nodes"].append(
        {
            "id": "unfinished-user-preparation",
            "kind": "task",
            "config": {"params": {"sql": "-- keep my work"}},
        }
    )
    draft["edges"].append(
        {"from": "unfinished-user-preparation", "to": "sink.queue", "id": "user-edge"}
    )
    state = {
        "system_id": SYSTEM,
        "published": {
            "version_id": "v10",
            "version_number": 10,
            "flow_definition": graph,
            "flow_sha256": sha(graph),
            "execution_contract": contract,
        },
        "draft": {
            "revision": 38,
            "base_published_version_id": "v10",
            "flow_definition": draft,
            "flow_sha256": sha(draft),
            "control_policy_snapshot_sha256": "b" * 64,
        },
    }
    spec = {
        "version": 2,
        "enforcement_mode": "shadow",
        "inbound": {"collection_allowlist": []},
        "capabilities": {
            "allowed_skills": [],
            "allowed_models": [],
            "allowed_actions": [],
            "allowed_delegations": [],
        },
        "outbound": {},
        "provenance": {},
        "valves": {
            "max_cost_per_decision": None,
            "max_latency_ms": None,
            "token_budget": None,
            "hard_abort": False,
        },
    }
    mandate = {
        "system_id": SYSTEM,
        "draft": {
            "revision": 38,
            "flow_sha256": sha(draft),
            "snapshot_sha256": "b" * 64,
            "spec_is_seed": True,
            "spec": spec,
        },
        "published": {"spec": None},
        "options": {
            "skills": [{"id": slug} for slug in contract_skills(contract)],
            "collections": [{"id": "published-policy"}],
            "models": [{"id": "gpt-5"}],
        },
    }
    app = {
        "id": "app",
        "slug": "team-app",
        "updated_at": "2026-10-22T00:00:00",
        "deployments": [{"channel": "pilot", "release_id": "release-1"}],
        "draft": {
            "revision": 4,
            "content_sha256": "c" * 64,
            "pages": {"pages": []},
            "binding_keys": ["showcase.claims.refresh_queue"],
        },
    }
    return state, mandate, app


class PlanTests(unittest.TestCase):
    def test_published_candidate_excludes_draft_only_work_and_restore_preserves_it(
        self,
    ):
        args = snapshots()
        before = deepcopy(args)
        plan = build_plan(*args)
        self.assertEqual(args, before)
        self.assertNotIn(
            "unfinished-user-preparation",
            [n["id"] for n in plan["publication_candidate"]["nodes"]],
        )
        saved = plan["preserved_draft_candidate"]
        self.assertEqual(
            saved["nodes"][-1], before[0]["draft"]["flow_definition"]["nodes"][-1]
        )
        self.assertEqual(saved["edges"], before[0]["draft"]["flow_definition"]["edges"])
        self.assertEqual(saved["nodes"][0]["position"], {"x": 999, "y": 200})
        self.assertEqual(
            saved["nodes"][0]["config"]["goal"],
            before[0]["draft"]["flow_definition"]["nodes"][0]["config"]["goal"],
        )
        self.assertEqual(
            plan["request_templates"]["save_flow_candidate"]["expected_revision"], 38
        )
        self.assertFalse(plan["activation_ready"])

    def test_conflicting_user_control_edits_require_review(self):
        state, _, _ = snapshots()
        state["draft"]["flow_definition"]["nodes"][0]["config"]["budget"][
            "max_turns"
        ] = 4
        with self.assertRaisesRegex(ValueError, "USER_DRAFT_CONFLICT"):
            preserve_draft(
                state["published"]["flow_definition"], state["draft"]["flow_definition"]
            )

    def test_scope_covers_nested_tools_and_keeps_ml_pins_out_of_llm_models(self):
        plan = build_plan(*snapshots())
        policy = plan["shadow_mandate_candidate"]
        self.assertEqual(
            policy["capabilities"]["allowed_skills"],
            ["decide_next_v1", "evaluate_v2", "ml_batch_score_v1", "read_case"],
        )
        self.assertEqual(
            policy["inbound"]["collection_allowlist"], ["published-policy"]
        )
        self.assertEqual(policy["capabilities"]["allowed_actions"], [])
        self.assertEqual(policy["capabilities"]["allowed_delegations"], [])
        self.assertNotIn("ml-id", policy["capabilities"]["allowed_models"])
        self.assertEqual(plan["unchanged_ml_registry_pins"][0]["version"], 5)
        self.assertIsNone(policy["valves"]["token_budget"])
        self.assertTrue(plan["work_cutover"]["blocked_until_fresh_reads"])

    def test_unknown_catalogue_reference_and_stale_revision_fail_closed(self):
        for change, message in [
            (
                lambda s, m, a: m["options"].update(skills=[]),
                "REFERENCE_NOT_AUTHORIZED",
            ),
            (lambda s, m, a: m["draft"].update(revision=37), "REVISION_MISMATCH"),
            (
                lambda s, m, a: s["published"].update(flow_sha256="0" * 64),
                "HASH_MISMATCH",
            ),
        ]:
            args = snapshots()
            change(*args)
            with self.assertRaisesRegex(ValueError, message):
                build_plan(*args)

    def test_sink_unknown_exclusion_is_not_fabricated_as_zero(self):
        graph = configured_flow(snapshots()[0]["published"]["flow_definition"])
        sink = next(n for n in graph["nodes"] if n["id"] == "sink.queue")["config"]
        ref = sink["inputs_map"]["excluded_count"]
        self.assertFalse(ref["required"])
        self.assertNotIn("default", ref)
        self.assertNotIn("excluded_count", sink["output_schema"]["required"])
        self.assertEqual(
            sink["inputs_map"]["model_version"]["path"], ["model", "version"]
        )

    def test_checked_in_plan_is_not_activation_and_has_real_backup_hashes(self):
        plan = json.loads((Path(__file__).parent / "reviewed_plan.json").read_text())
        self.assertFalse(plan["applied"])
        self.assertFalse(plan["activation_ready"])
        self.assertEqual(
            sha(plan["backup"]["flow_definition"]),
            plan["preconditions"]["draft_flow_sha256"],
        )
        self.assertEqual(sha(plan["publication_candidate"]), plan["target_flow_sha256"])
        self.assertEqual(
            len(plan["shadow_mandate_candidate"]["capabilities"]["allowed_skills"]), 14
        )
        self.assertEqual(
            len(plan["shadow_mandate_candidate"]["inbound"]["collection_allowlist"]), 5
        )


if __name__ == "__main__":
    unittest.main()
