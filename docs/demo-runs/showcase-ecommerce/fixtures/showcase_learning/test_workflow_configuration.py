"""Configuration contracts and a real DuckDB history/forecast union."""

from __future__ import annotations

import copy
import importlib.util
import unittest
from datetime import datetime, timedelta, timezone

from workflow_configuration import (
    FORECAST_BINDING,
    TIMELINE_SQL,
    build_configuration,
)


def base():
    flow = {
        "schema_version": 3,
        "nodes": [
            {
                "id": "source.request",
                "type": "source",
                "kind": "source",
                "config": {
                    "ingress_kind": "manual",
                    "input_schema": {"type": "object", "properties": {}},
                },
            },
            {
                "id": "source.queue",
                "type": "source",
                "kind": "source",
                "config": {
                    "ingress_kind": "manual",
                    "input_schema": {"type": "object", "properties": {}},
                },
            },
            {
                "id": "sav.score",
                "type": "skill",
                "kind": "task",
                "config": {
                    "skill_slug": "ml_batch_score_v1",
                    "params": {"model_id": "sla-model", "pinned_version": 2},
                },
            },
            {"id": "sink.case", "type": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "source.request", "to": "sav.score", "kind": "data"},
            {"from": "source.queue", "to": "sav.score", "kind": "data"},
            {"from": "sav.score", "to": "sink.case", "kind": "data"},
        ],
    }
    pages = {
        "pages": [
            {
                "id": "dossier",
                "title": "Dossier",
                "components": [
                    {
                        "id": "investigation",
                        "type": "form",
                        "props": {
                            "bindingKey": "showcase.claims.investigate",
                            "schema": {"type": "object", "properties": {}},
                        },
                    },
                    {
                        "id": "queue_refresh",
                        "type": "action_button",
                        "props": {
                            "bindingKey": "showcase.claims.refresh_queue",
                            "input": {},
                        },
                    },
                ],
            }
        ]
    }
    return flow, pages


def configured():
    return build_configuration(
        *base(),
        "forecast-model",
        "forecast-model",
        3,
        "history-dataset",
        {"model_id": "sla-model"},
    )


class ConfigurationTests(unittest.TestCase):
    def test_preserves_original_actions_and_only_adds_native_steps(self):
        flow, pages = base()
        frozen = copy.deepcopy((flow, pages))
        result = build_configuration(
            flow,
            pages,
            "forecast-model",
            "forecast-model",
            3,
            "history-dataset",
            {"model_id": "sla-model"},
        )
        self.assertEqual((flow, pages), frozen)
        self.assertEqual(result["flow_definition"]["nodes"][:4], flow["nodes"])
        self.assertEqual(
            result["pages"]["pages"][0]["components"][:2],
            pages["pages"][0]["components"],
        )
        self.assertEqual(
            result["bindings"],
            [{"binding_key": FORECAST_BINDING, "ingress_id": "source.forecast"}],
        )
        added = result["flow_definition"]["nodes"][4:]
        self.assertEqual(
            [node["config"]["skill_slug"] for node in added if node["kind"] == "task"],
            ["ml_forecast_v1", "sql_transform_v1"],
        )
        transform = added[2]["config"]
        self.assertEqual(
            transform["params"]["sources"],
            [{"view": "history", "dataset_id": "history-dataset"}],
        )
        self.assertEqual(
            transform["inputs_map"]["dataset_id"]["node_id"], "forecast.predict"
        )

    def test_chart_reads_only_authorised_dataset_from_action_run(self):
        result = configured()
        page = next(page for page in result["pages"]["pages"] if page["id"] == "charge")
        chart = next(
            node for node in page["components"] if node["id"] == "forecast_chart"
        )
        self.assertEqual(
            chart["props"]["datasetSource"],
            {
                "source": "run-output",
                "selector": "dataset_id",
                "componentId": "forecast_refresh",
            },
        )
        self.assertFalse(
            {"queryBinding", "dataBinding", "series"} & chart["props"].keys()
        )
        self.assertEqual(chart["props"]["kind"], "timeseries")
        self.assertEqual(
            set(result["pages"]["i18n"]["fr"]), set(result["pages"]["i18n"]["en"])
        )
        self.assertTrue(
            all(result["pages"]["i18n"][lang].values() for lang in ("fr", "en"))
        )

    def test_reapplying_refuses_to_duplicate_ingress_and_pages(self):
        result = configured()
        with self.assertRaisesRegex(ValueError, "ALREADY_INSTALLED"):
            build_configuration(
                result["flow_definition"],
                result["pages"],
                "forecast-model",
                "forecast-model",
                3,
                "history-dataset",
                {"model_id": "sla-model"},
            )

    @unittest.skipUnless(
        importlib.util.find_spec("app"),
        "Run with PYTHONPATH=backend and the backend venv for product validators",
    )
    def test_native_flow_and_pages_validators_accept_configuration(self):
        from app.services.chains.dag_validator import validate_flow
        from app.services.experience.lifecycle import validate_pages_document
        from app.services.tabular_transforms import validate_sql

        result = configured()
        issues = validate_flow(result["flow_definition"])
        self.assertEqual([issue for issue in issues if issue.level == "error"], [])
        self.assertEqual(len(validate_pages_document(result["pages"])["pages"]), 3)
        self.assertEqual(validate_sql(TIMELINE_SQL), TIMELINE_SQL.strip())

    @unittest.skipUnless(
        importlib.util.find_spec("duckdb"),
        "Run with the backend venv for real SQL execution",
    )
    def test_sql_keeps_42_actuals_and_28_forecasts_without_zero_fill(self):
        import duckdb

        db = duckdb.connect(":memory:")
        try:
            db.execute(
                "CREATE TABLE input_1(observed_at TIMESTAMPTZ, claim_count INTEGER)"
            )
            db.execute(
                "CREATE TABLE input_2(timestamp TIMESTAMPTZ, series VARCHAR, pred DOUBLE, lower_bound DOUBLE, upper_bound DOUBLE)"
            )
            start = datetime(2026, 8, 30, tzinfo=timezone.utc)
            db.executemany(
                "INSERT INTO input_1 VALUES (?, ?)",
                [(start + timedelta(days=i), i + 1) for i in range(50)],
            )
            db.executemany(
                "INSERT INTO input_2 VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        start + timedelta(days=50 + i),
                        "__single__",
                        20.0 + i,
                        15.0 + i,
                        25.0 + i,
                    )
                    for i in range(28)
                ],
            )
            # Fetch naive UTC only for Python's stdlib assertion: DuckDB's
            # native TIMESTAMPTZ Python adapter optionally depends on pytz.
            rows = db.execute(
                "SELECT cast(timestamp AS TIMESTAMP), series, actual, pred, lower_bound, upper_bound FROM ("
                + TIMELINE_SQL
                + ")"
            ).fetchall()
            self.assertEqual(len(rows), 70)
            self.assertEqual(
                rows[0][0], (start + timedelta(days=8)).replace(tzinfo=None)
            )
            self.assertEqual({row[1] for row in rows}, {"Luma SAV"})
            self.assertTrue(
                all(
                    row[2] is not None and row[3:] == (None, None, None)
                    for row in rows[:42]
                )
            )
            self.assertTrue(
                all(row[2] is None and row[4] <= row[3] <= row[5] for row in rows[42:])
            )
            self.assertEqual(len({row[0] for row in rows}), 70)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
