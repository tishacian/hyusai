"""Data integrity checks: leakage, date boundaries and reproducible exports."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from generate import DEFAULT_ANCHOR, FEATURES, build, validate, write_pack
from model_requests import plan_body, reviewed_text_requests, training_requests


class LearningPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = build()

    def test_outcomes_cutoffs_and_holdout_are_independent(self):
        result = validate(self.data, DEFAULT_ANCHOR)
        self.assertGreaterEqual(
            sum(result["calibration_conservative_minimum_by_class"].values()), 200
        )
        self.assertGreaterEqual(
            min(result["calibration_conservative_minimum_by_class"].values()), 20
        )
        self.assertGreater(result["unresolved_at_anchor"], 0)
        self.assertEqual(len(self.data["daily_volume.csv"]), 420)
        self.assertEqual(len(self.data["text_for_review.csv"]), 480)

    def test_validation_rejects_future_outcome(self):
        data = copy.deepcopy(self.data)
        data["outcomes.csv"][0]["resolved_at"] = "2026-10-10T00:00:00Z"
        with self.assertRaises(AssertionError):
            validate(data, DEFAULT_ANCHOR)

    def test_validation_rejects_volume_or_target_leakage(self):
        data = copy.deepcopy(self.data)
        data["daily_volume.csv"][0]["claim_count"] += 1
        with self.assertRaises(AssertionError):
            validate(data, DEFAULT_ANCHOR)
        data = copy.deepcopy(self.data)
        data["cases.csv"][0]["resolved_at"] = "2026-01-01T00:00:00Z"
        with self.assertRaises(AssertionError):
            validate(data, DEFAULT_ANCHOR)

    def test_same_seed_and_anchor_produce_identical_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            left, right = Path(tmp) / "left", Path(tmp) / "right"
            self.assertEqual(
                write_pack(left, DEFAULT_ANCHOR), write_pack(right, DEFAULT_ANCHOR)
            )
            for path in left.iterdir():
                self.assertEqual(path.read_bytes(), (right / path.name).read_bytes())

    def test_reference_manifest_matches_the_default_pack(self):
        reference = json.loads(
            (Path(__file__).parent / "manifest.reference.json").read_text()
        )
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(write_pack(Path(tmp), DEFAULT_ANCHOR), reference)

    def test_anchor_is_explicit_and_all_documents_follow_it(self):
        alternate = date(2027, 2, 15)
        data = build(alternate)
        validate(data, alternate)
        self.assertEqual(
            data["daily_volume.csv"][-1]["observed_at"][:10],
            (alternate - timedelta(days=1)).isoformat(),
        )
        with tempfile.TemporaryDirectory() as tmp:
            manifest = write_pack(Path(tmp), alternate)
            self.assertTrue(manifest["anchor_exclusive_utc"].startswith("2027-02-15"))
            self.assertIn("2027-02-15", (Path(tmp) / "campaign-plan.md").read_text())

    def test_training_requests_never_default_to_all_dataset_columns(self):
        requests = training_requests(
            sla_dataset_id="sla-id",
            volume_dataset_id="vol-id",
            regression_dataset_id="reg-id",
            segmentation_dataset_id="seg-id",
        )
        for key in ("sla_calibrated", "sla_challenger_tuned", "resolution_duration"):
            self.assertEqual(requests[key]["features"], FEATURES)
            self.assertNotIn(requests[key]["target"], requests[key]["features"])
        for key in ("volume_seasonal_naive", "volume_classical", "volume_chronos"):
            self.assertEqual(requests[key]["spec"]["horizon"], 28)
            self.assertEqual(requests[key]["features"], [])
        self.assertNotIn("calendar", requests["volume_chronos"]["spec"])
        self.assertNotIn("name", plan_body(requests["sla_calibrated"]))
        self.assertNotIn("cross_validation", plan_body(requests["sla_calibrated"]))
        for request in reviewed_text_requests("actual-reviewed-dataset-id").values():
            self.assertEqual(request["features"], ["initial_message"])
            self.assertEqual(request["cross_validation"], 0)


if __name__ == "__main__":
    unittest.main()
