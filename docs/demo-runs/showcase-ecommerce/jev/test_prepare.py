"""Guard fixture provenance, isolated execution and budget preconditions offline."""

import copy
import hashlib
import json
import unittest
from pathlib import Path

from prepare import (
    MODEL,
    NODE_ID,
    SYSTEM_ID,
    TRANSPORT,
    WORKSPACE_ID,
    build,
    cases,
    flow_identity,
    sha,
)
from run_preview import check_preflight


def state():
    # Small local stand-in; real preserved identifiers are in prepared-plan.json.
    graph = {"nodes": [], "edges": []}
    return {
        "system_id": SYSTEM_ID,
        "draft": {
            "revision": 38,
            "flow_definition": graph,
            "flow_sha256": sha(graph),
            "control_policy_snapshot_sha256": "a" * 64,
        },
        "published": {
            "version_id": "v10-id",
            "version_number": 10,
            "flow_definition": graph,
            "flow_sha256": sha(graph),
            "control_policy_snapshot_sha256": "b" * 64,
        },
    }


class PreviewPreparationTests(unittest.TestCase):
    def test_four_existing_scenarios_keep_expected_answers_out_of_provider_input(self):
        plan = build(state())
        self.assertEqual(
            [case["case_id"] for case in plan["cases"]],
            ["RC-1042", "RC-1043", "RC-1044", "RC-5007"],
        )
        self.assertFalse(plan["rubric_human_reviewed"])
        for case in plan["cases"]:
            request = case["request"]
            self.assertEqual(request["method"], "POST")
            self.assertEqual(
                request["path"], f"/api/v1/systems/{SYSTEM_ID}/flow-workbench/node-runs"
            )
            self.assertNotIn("expected_business_direction", json.dumps(request))
            self.assertIsNone(case["observed_result"])
            self.assertIsNone(case["human_annotation"])
            body = request["body"]
            self.assertEqual(body["expected_flow_sha256"], sha(body["flow_definition"]))
            self.assertEqual(len(body["flow_definition"]["nodes"]), 1)
            node = body["flow_definition"]["nodes"][0]
            self.assertEqual(node["id"], NODE_ID)
            self.assertEqual(node["config"]["skill_slug"], "evaluate_v2")
            typed = node["config"]["typed_evaluation"]
            self.assertNotIn("run_evidence", typed)
            self.assertEqual(typed["tariff"]["model"], MODEL)
            for question in typed["questions"]:
                self.assertFalse(question["requires_evidence"])
                self.assertNotIn("acceptable_values", question)
                self.assertNotIn("accept_minimum", question)

    def test_every_text_and_source_file_hash_matches(self):
        root = Path(__file__).resolve().parent.parent
        for case in cases():
            for evidence in case["input_ref"]["evidence"]:
                self.assertEqual(
                    evidence["sha256"],
                    hashlib.sha256(evidence["text"].encode()).hexdigest(),
                )
            for source in case["sources"]:
                self.assertEqual(
                    source["sha256"],
                    hashlib.sha256((root / source["path"]).read_bytes()).hexdigest(),
                )

    def test_missing_piece_is_absent_and_refund_fixture_keeps_original_amount(self):
        by_id = {case["case_id"]: case for case in cases()}
        missing = by_id["RC-5007"]["input_ref"]["evidence"]
        self.assertNotIn("delivery-lm5007", [evidence["id"] for evidence in missing])
        facts = json.loads(missing[0]["text"])
        self.assertEqual(facts["missing_case_documents"], ["delivery-lm5007"])
        self.assertEqual(facts["tables"]["orders"][0]["order_id"], "LM-5007")
        loss = json.loads(by_id["RC-1043"]["input_ref"]["evidence"][0]["text"])
        self.assertEqual(loss["tables"]["orders"][0]["paid_amount"], "49.90")

    def test_corrupt_or_other_system_snapshot_is_rejected(self):
        original = state()
        for key, value in [
            ("system_id", "another-system"),
            ("draft", {**original["draft"], "flow_sha256": "0" * 64}),
        ]:
            with self.assertRaises(ValueError):
                flow_identity({**original, key: value})


class PreviewPreflightTests(unittest.TestCase):
    def setUp(self):
        self.inputs = {
            "plan": build(state()),
            "live_flow": state(),
            "workspace": {
                "id": WORKSPACE_ID,
                "settings": {"features": {"flow_workbench_v1": True}},
            },
            "readiness": {
                "ready": True,
                "revision": "c" * 40,
                "qualified_transports": [TRANSPORT],
            },
            "budgets": {
                "can_manage": True,
                "items": [
                    {
                        "scope": "workspace",
                        "revision": 2,
                        "enabled": True,
                        "max_tokens": None,
                        "currency_limits": {"EUR": "2000"},
                        "reconciliation_required": False,
                        "current_period": {
                            "amounts": [
                                {
                                    "currency": "EUR",
                                    "limit": "2000",
                                    "consumed": "3",
                                    "reserved": "0.12",
                                }
                            ]
                        },
                    }
                ],
            },
            "providers": {
                "providers": [
                    {
                        "key": "typesafe",
                        "configured": True,
                        "status": "active",
                        "typed_decisions_available": True,
                        "models": ["jev-latest", "jev-preview"],
                    }
                ]
            },
            "tariffs": {
                "items": [
                    {
                        "provider": "typesafe",
                        "model": MODEL,
                        "currency": "EUR",
                        "id": "tariff-id",
                        "revision": 1,
                        "rates": {
                            "input_per_million": "0.037386505252",
                            "output_per_million": "0",
                        },
                    }
                ]
            },
        }

    def test_active_qualified_money_budget_accepts_documented_pin_despite_alias_discovery(
        self,
    ):
        result = check_preflight(**self.inputs)
        self.assertEqual(result["tariff_id"], "tariff-id")
        self.assertEqual(result["budget_revision"], 2)
        self.assertEqual(result["conservative_reservation_eur"], "0.002450162009")

    def test_latest_tariff_revision_is_selected_across_currencies(self):
        newer = {**self.inputs["tariffs"]["items"][0], "revision": 2, "currency": "USD"}
        self.inputs["tariffs"]["items"].append(newer)
        with self.assertRaisesRegex(ValueError, "LATEST_TARIFF_NOT_EUR"):
            check_preflight(**self.inputs)

    def test_cache_rates_use_the_highest_input_price_for_reservation(self):
        self.inputs["tariffs"]["items"][0]["rates"].update(
            cached_input_per_million="0.01", cache_write_per_million="0.1"
        )
        result = check_preflight(**self.inputs)
        self.assertEqual(result["conservative_reservation_eur"], "0.006553600000")

    def test_applicable_system_budget_must_include_tariff_currency(self):
        system_cap = copy.deepcopy(self.inputs["budgets"]["items"][0])
        system_cap.update(
            scope="system", system_id=SYSTEM_ID, currency_limits={"USD": "2000"}
        )
        self.inputs["budgets"]["items"].append(system_cap)
        with self.assertRaisesRegex(ValueError, "CURRENCY_NOT_BUDGETED"):
            check_preflight(**self.inputs)

    def test_old_rollout_or_missing_transport_cannot_dispatch(self):
        for changes in [{"ready": False}, {"qualified_transports": []}]:
            values = copy.deepcopy(self.inputs)
            values["readiness"].update(changes)
            with self.assertRaises(ValueError):
                check_preflight(**values)

    def test_token_cap_unknown_usage_or_not_enough_money_cannot_dispatch(self):
        for changes in [
            {"max_tokens": 10000},
            {"reconciliation_required": True},
            {
                "current_period": {
                    "amounts": [
                        {
                            "currency": "EUR",
                            "limit": "2000",
                            "consumed": "1999.9999",
                            "reserved": "0",
                        }
                    ]
                }
            },
        ]:
            values = copy.deepcopy(self.inputs)
            values["budgets"]["items"][0].update(changes)
            with self.assertRaises(ValueError):
                check_preflight(**values)

    def test_stale_draft_or_changed_cap_or_paid_output_is_rejected(self):
        values = copy.deepcopy(self.inputs)
        values["live_flow"]["draft"]["revision"] += 1
        with self.assertRaisesRegex(ValueError, "LUMA_FLOW_CHANGED"):
            check_preflight(**values)
        values = copy.deepcopy(self.inputs)
        values["budgets"]["items"][0]["currency_limits"]["EUR"] = "3000"
        with self.assertRaisesRegex(ValueError, "SHOWCASE_BUDGET_CHANGED"):
            check_preflight(**values)
        values = copy.deepcopy(self.inputs)
        values["tariffs"]["items"][0]["rates"]["output_per_million"] = "1"
        with self.assertRaisesRegex(ValueError, "TARIFF_CONTRACT_MISMATCH"):
            check_preflight(**values)


if __name__ == "__main__":
    unittest.main()
