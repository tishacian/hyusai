"""Prove the candidate's exact difference from the captured publication."""

import copy
import json
import unittest
from pathlib import Path

from prepare import SYSTEM_ID, sha
from prepare_main_flow import (
    INPUT_ISOLATION,
    JEV_NODE_ID,
    JUDGE_NODE_ID,
    SHIFTED_NODE_IDS,
    build,
    candidate_flow,
)

PLAN = json.loads((Path(__file__).parent / "main-flow-plan.json").read_text())
CANDIDATE = PLAN["review_request"]["body"]["flow_definition"]


def published_source():
    """Undo only the reviewed additions; its hash must equal the captured v10."""
    flow = copy.deepcopy(CANDIDATE)
    flow["nodes"] = [node for node in flow["nodes"] if node["id"] != JEV_NODE_ID]
    nodes = {node["id"]: node for node in flow["nodes"]}
    for node_id in SHIFTED_NODE_IDS:
        nodes[node_id]["position"]["x"] -= 320
    config = nodes[JUDGE_NODE_ID]["config"]
    del config["input_mode"]
    del config["passthrough_inputs"]
    flow["edges"] = [edge for edge in flow["edges"] if edge.get("from") != JEV_NODE_ID]
    next(edge for edge in flow["edges"] if edge.get("to") == JEV_NODE_ID)["to"] = (
        JUDGE_NODE_ID
    )
    return flow


def source_state():
    graph = published_source()
    draft = copy.deepcopy(graph)
    draft["nodes"].append(
        {
            "id": "flow.mv95zi21.1",
            "kind": "task",
            "label": "Unfinished user preparation",
            "config": {},
        }
    )
    return {
        "system_id": SYSTEM_ID,
        "draft": {"revision": 38, "flow_definition": draft, "flow_sha256": sha(draft)},
        "published": {
            "version_id": PLAN["preserved_flow"]["published_version_id"],
            "version_number": 10,
            "flow_definition": graph,
            "flow_sha256": PLAN["preserved_flow"]["published_flow_sha256"],
        },
    }


class MainFlowCandidateTests(unittest.TestCase):
    def test_exact_original_publication_is_recoverable_without_other_changes(self):
        original = published_source()
        self.assertEqual(sha(original), PLAN["preserved_flow"]["published_flow_sha256"])
        self.assertEqual(candidate_flow(original), CANDIDATE)
        self.assertEqual(sha(CANDIDATE), PLAN["candidate_flow_sha256"])

    def test_preparation_does_not_publish_or_mutate_user_draft(self):
        source = source_state()
        before = copy.deepcopy(source)
        plan = build(source)
        self.assertEqual(source, before)
        self.assertFalse(plan["applied"])
        self.assertFalse(plan["qualified_live"])
        body = plan["review_request"]["body"]
        self.assertEqual(body["expected_draft_revision"], 38)
        self.assertEqual(
            body["expected_draft_flow_sha256"], source["draft"]["flow_sha256"]
        )
        self.assertNotIn(
            "flow.mv95zi21.1", {node["id"] for node in body["flow_definition"]["nodes"]}
        )
        self.assertNotIn("expected_execution_contract_sha256", body)
        self.assertEqual(
            plan["publish_after_review"]["required_from_review"],
            {
                "expected_review_sha256": "candidate.review_sha256",
                "expected_execution_contract_sha256": "candidate.execution_contract_sha256",
            },
        )

    def test_both_judges_capture_the_original_sources_independently(self):
        nodes = {node["id"]: node for node in CANDIDATE["nodes"]}
        original = next(
            node for node in published_source()["nodes"] if node["id"] == JUDGE_NODE_ID
        )
        gpt = nodes[JUDGE_NODE_ID]["config"]
        jev = nodes[JEV_NODE_ID]["config"]
        self.assertEqual(
            gpt["typed_evaluation"], original["config"]["typed_evaluation"]
        )
        self.assertEqual(
            jev["typed_evaluation"]["run_evidence"],
            gpt["typed_evaluation"]["run_evidence"],
        )
        for config in (gpt, jev):
            self.assertEqual(
                {key: config[key] for key in INPUT_ISOLATION}, INPUT_ISOLATION
            )
        for question in jev["typed_evaluation"]["questions"]:
            self.assertFalse(question["requires_evidence"])
            self.assertNotIn("acceptable_values", question)
            self.assertNotIn("accept_minimum", question)
        self.assertFalse(PLAN["rubric_human_reviewed"])

    def test_full_candidate_can_be_qualified_before_publication_without_draft_swap(
        self,
    ):
        preview = build(source_state())["qualification_before_publication"]
        self.assertTrue(preview["path"].endswith("/flow-workbench/preview-runs"))
        self.assertEqual(
            preview["copy_from_review_body"],
            ["flow_definition", "expected_flow_sha256"],
        )
        self.assertEqual(preview["body"]["ingress_id"], "source.request")
        self.assertEqual(preview["body"]["input_ref"], {"claim_id": "RC-1042"})
        self.assertTrue(preview["body"]["acknowledge_real_side_effects"])
        self.assertEqual(preview["execution_surface"], "builder_preview")
        self.assertNotIn("flow_version_id", preview["body"])

    def test_only_ready_branch_receives_second_opinion_and_human_gate_remains(self):
        edges = CANDIDATE["edges"]

        def targets(node):
            return {edge["to"] for edge in edges if edge["from"] == node}

        self.assertEqual(targets(JEV_NODE_ID), {JUDGE_NODE_ID})
        self.assertEqual(targets(JUDGE_NODE_ID), {"hitl.review"})
        self.assertEqual(targets("hitl.review"), {"task.simulate"})
        ready = next(
            edge
            for edge in edges
            if edge.get("from") == "decision.ready"
            and edge.get("branch_label") == "ready"
        )
        self.assertEqual(ready["to"], JEV_NODE_ID)
        blocked = next(
            edge
            for edge in edges
            if edge.get("from") == "decision.ready"
            and edge.get("branch_label") == "blocked"
        )
        self.assertEqual(blocked["to"], "sink.blocked")
        self.assertEqual(targets("sink.blocked"), set())

    def test_source_port_and_edge_identity_survive_insertion(self):
        flow = published_source()
        ready = next(edge for edge in flow["edges"] if edge.get("to") == JUDGE_NODE_ID)
        ready.update(id="reviewed-edge", from_port="ready")
        candidate = candidate_flow(flow)
        edge = next(
            edge for edge in candidate["edges"] if edge.get("to") == JEV_NODE_ID
        )
        self.assertEqual(edge, {**ready, "to": JEV_NODE_ID})

    def test_changed_paths_or_inputs_require_a_new_review(self):
        def change_incoming(flow):
            flow["edges"].append({"from": "source.request", "to": JUDGE_NODE_ID})

        def change_input(flow):
            next(node for node in flow["nodes"] if node["id"] == JUDGE_NODE_ID)[
                "config"
            ]["inputs_map"] = {"subject_ref": "run.injected"}

        def change_port(flow):
            next(edge for edge in flow["edges"] if edge.get("to") == JUDGE_NODE_ID)[
                "to_port"
            ] = "subject"

        for mutate in (change_incoming, change_input, change_port):
            with self.subTest(mutate=mutate.__name__):
                flow = published_source()
                mutate(flow)
                with self.assertRaises(ValueError):
                    candidate_flow(flow)


if __name__ == "__main__":
    unittest.main()
