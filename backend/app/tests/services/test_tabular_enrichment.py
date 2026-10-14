"""Exercise the actual SQL engine, versioned datasets and Flow boundary."""

from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings
from app.models.tabular import TabularDataset
from app.models.workspace import Workspace
from app.services.tabular_datasets import (
    TabularError,
    read_frame,
    register_frame,
    serialize_dataset,
)
from app.services.tabular_enrichment import preview_enrichment, run_enrichment_transform

pl = pytest.importorskip("polars")
pytest.importorskip("duckdb")


@pytest.fixture()
def sample(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    ws = Workspace(id=str(uuid4()), name="Enrichment", slug=uuid4().hex, settings={})
    db_session.add(ws)
    db_session.commit()
    base = register_frame(
        db_session,
        workspace_id=ws.id,
        name="Orders",
        frame=pl.DataFrame(
            {
                "order_id": [3, 1, 2, 4],
                "customer_id": ["C1", "C1", "C2", "C3"],
                "ordered_at": ["2026-03-01", "2026-02-01", "2026-02-01", "2026-02-01"],
                "basket": [50.0, 40.0, 30.0, 20.0],
                "late": [1, 0, 1, 0],
                "future_status": [1, 2, 3, 4],
            }
        ),
    )
    history = register_frame(
        db_session,
        workspace_id=ws.id,
        name="Payments",
        frame=pl.DataFrame(
            {
                "event_id": [1, 2, 3, 4, 5, 6],
                "customer_id": ["C1", "C1", "C1", "C1", "C2", "C2"],
                "available_at": [
                    "2026-01-01",
                    "2026-01-01",
                    "2026-02-01",
                    "2026-04-01",
                    "2026-01-01",
                    "2026-03-01",
                ],
                "amount": [10.0, 20.0, 30.0, 999.0, 50.0, 999.0],
                "late": [1, 0, 1, 0, 1, 1],
            }
        ),
    )
    db_session.commit()
    spec = {
        "base": {"dataset_id": base.id, "version": base.version},
        "history": {"dataset_id": history.id, "version": history.version},
        "base_row_id": "order_id",
        "history_row_id": "event_id",
        "base_key": "customer_id",
        "history_key": "customer_id",
        "decision_time": "ordered_at",
        "available_time": "available_at",
        "base_features": ["basket"],
        "target_columns": ["late"],
        "unavailable_columns": ["future_status"],
        "aggregates": [
            {"operation": "count", "output": "prior_events"},
            {"operation": "sum", "column": "amount", "output": "prior_amount"},
            {"operation": "mean", "column": "amount", "output": "prior_mean"},
            {"operation": "min", "column": "amount", "output": "prior_min"},
            {"operation": "max", "column": "amount", "output": "prior_max"},
        ],
    }
    return ws, base, history, spec


def test_actual_temporal_aggregates_exclude_equal_and_future_events(db_session, sample):
    ws, _, _, spec = sample
    result = preview_enrichment(db_session, workspace_id=ws.id, spec=spec)
    rows = result["preview"]
    assert [r["order_id"] for r in rows] == [1, 2, 3, 4]
    assert [r["prior_events"] for r in rows] == [2, 1, 3, 0]
    assert [r["prior_amount"] for r in rows] == [30.0, 50.0, 60.0, None]
    assert [r["prior_mean"] for r in rows] == [15.0, 50.0, 20.0, None]
    assert [r["prior_max"] for r in rows] == [20.0, 50.0, 30.0, None]
    assert [r["prior_min"] for r in rows] == [10.0, 50.0, 10.0, None]
    assert all("future_status" not in r for r in rows)
    assert result["enrichment"]["unmatched_fraction"] == 0.25
    assert db_session.query(TabularDataset).count() == 2


def test_persisted_lineage_and_reload_are_reproducible(db_session, sample):
    ws, base, history, spec = sample
    first = run_enrichment_transform(
        db_session, workspace_id=ws.id, spec=spec, output_name="Features", node_id="history"
    )
    second = run_enrichment_transform(
        db_session, workspace_id=ws.id, spec=spec, output_name="Features"
    )
    row = db_session.get(TabularDataset, first["dataset_id"])
    assert row.parent_ids == [base.id, history.id]
    assert row.node_id == "history"
    assert second["version"] == first["version"] + 1
    assert read_frame(row).equals(read_frame(db_session.get(TabularDataset, second["dataset_id"])))
    evidence = serialize_dataset(row, include_preview=True)["lineage"]["enrichment"]
    assert evidence["contract"] == second["enrichment"]["contract"]
    assert evidence["contract_sha256"] == second["enrichment"]["contract_sha256"]
    assert evidence["sources"][0]["dataset_id"] == base.id
    assert evidence["sources"][0]["version"] == base.version
    assert len(evidence["sources"][0]["sha256"]) == 64
    assert evidence["row_lineage"]["history_identity"] == "event_id"
    assert evidence["comparison_independence"] == "not_established_by_enrichment"


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"base": {"version": 99}}, "ENRICHMENT_VERSION_MISMATCH"),
        ({"max_base_rows": 3}, "ENRICHMENT_INPUT_TOO_LARGE"),
        ({"max_history_rows": 5}, "ENRICHMENT_INPUT_TOO_LARGE"),
        ({"max_input_bytes": 1}, "ENRICHMENT_INPUT_TOO_LARGE"),
        ({"max_unmatched_fraction": 0.2}, "ENRICHMENT_UNMATCHED"),
        ({"base_features": ["future_status"]}, "ENRICHMENT_SPEC_INVALID"),
        ({"base_features": ["late"]}, "ENRICHMENT_SPEC_INVALID"),
        ({"base_key": "late"}, "ENRICHMENT_SPEC_INVALID"),
        ({"cardinality": "many_to_many"}, "ENRICHMENT_SPEC_INVALID"),
        ({"base_key": "missing"}, "ENRICHMENT_COLUMN_MISSING"),
        (
            {"aggregates": [{"operation": "mean", "column": "late", "output": "label_mean"}]},
            "ENRICHMENT_SPEC_INVALID",
        ),
        (
            {"aggregates": [{"operation": "sum", "column": "customer_id", "output": "key_sum"}]},
            "ENRICHMENT_AGGREGATE_TYPE",
        ),
        ({"aggregates": [{"operation": "count", "output": "event_id"}]}, "ENRICHMENT_SPEC_INVALID"),
    ],
)
def test_invalid_contract_refuses_without_dataset_creation(db_session, sample, change, code):
    ws, _, _, spec = sample
    spec = deepcopy(spec)
    for key, value in change.items():
        if key in {"base", "history"}:
            spec[key].update(value)
        else:
            spec[key] = value
    with pytest.raises(TabularError) as caught:
        run_enrichment_transform(db_session, workspace_id=ws.id, spec=spec)
    assert caught.value.code == code
    assert db_session.query(TabularDataset).count() == 2


def test_cross_workspace_is_refused_before_materialization(db_session, sample, monkeypatch):
    ws, base, _, spec = sample
    other = Workspace(id=str(uuid4()), name="Other", slug=uuid4().hex, settings={})
    db_session.add(other)
    db_session.commit()
    base.workspace_id = other.id
    db_session.commit()
    monkeypatch.setattr(
        "app.services.tabular_transforms.materialize_dataset",
        lambda *args, **kwargs: pytest.fail("No bytes should be read"),
    )
    with pytest.raises(TabularError) as caught:
        preview_enrichment(db_session, workspace_id=ws.id, spec=spec)
    assert caught.value.code == "DATASET_NOT_FOUND"


@pytest.mark.parametrize(
    ("column", "values", "code"),
    [
        ("event_id", [1, 1, 3, 4, 5, 6], "ENRICHMENT_KEY_INVALID"),
        ("customer_id", [None, "C1", "C1", "C1", "C2", "C2"], "ENRICHMENT_KEY_INVALID"),
        (
            "available_at",
            ["bad", "2026-01-01", "2026-02-01", "2026-04-01", "2026-01-01", "2026-03-01"],
            "ENRICHMENT_TIME_INVALID",
        ),
        ("amount", [float("inf"), 2.0, 3.0, 4.0, 5.0, 6.0], "ENRICHMENT_AGGREGATE_TYPE"),
    ],
)
def test_bad_source_values_refuse(db_session, sample, column, values, code):
    ws, _, history, spec = sample
    frame = read_frame(history).with_columns(pl.Series(column, values))
    changed = register_frame(db_session, workspace_id=ws.id, name="Bad history", frame=frame)
    db_session.commit()
    spec["history"] = {"dataset_id": changed.id, "version": changed.version}
    with pytest.raises(TabularError) as caught:
        preview_enrichment(db_session, workspace_id=ws.id, spec=spec)
    assert caught.value.code == code


def test_preview_validates_all_rows_and_never_uses_latest_reference(db_session, sample):
    ws, _, history, spec = sample
    register_frame(
        db_session,
        workspace_id=ws.id,
        name=history.name,
        frame=read_frame(history).with_columns(pl.lit(999.0).alias("amount")),
    )
    db_session.commit()
    preview = preview_enrichment(db_session, workspace_id=ws.id, spec=spec, row_limit=1)
    assert preview["row_count"] == 4
    assert len(preview["preview"]) == 1
    assert preview["preview"][0]["prior_amount"] == 30.0
    spec["max_unmatched_fraction"] = 0.1
    with pytest.raises(TabularError, match="fraction"):
        preview_enrichment(db_session, workspace_id=ws.id, spec=spec, row_limit=1)


def test_preview_api_has_same_workspace_and_typed_contract(db_session, sample):
    from app.api.v1.endpoints import datasets as api

    ws, _, _, spec = sample
    app = FastAPI()
    app.include_router(api.router, prefix="/datasets")
    app.dependency_overrides[api.get_current_workspace] = lambda: ws
    app.dependency_overrides[api.get_current_user] = lambda: object()
    app.dependency_overrides[api.get_db] = lambda: db_session
    client = TestClient(app)
    response = client.post("/datasets/enrichment-preview", json={"enrichment": spec})
    assert response.status_code == 200, response.text
    assert response.json()["row_count"] == 4
    assert db_session.query(TabularDataset).count() == 2
    bad = deepcopy(spec)
    bad["history"]["dataset_id"] = str(uuid4())
    assert client.post("/datasets/enrichment-preview", json={"enrichment": bad}).status_code == 404
    bad["workspace_id"] = "forged"
    assert client.post("/datasets/enrichment-preview", json={"enrichment": bad}).status_code == 422


def test_flow_contract_owns_enrichment_not_trigger_payload(sample):
    from app.services.run_engine.dag import DagNode, _apply_transform_node_config

    _, _, _, spec = sample
    node = DagNode(
        id="enrich",
        type="task",
        kind="task",
        label="Historical features",
        config={"skill_slug": "sql_transform_v1", "params": {"enrichment": spec}},
        skill_slug="sql_transform_v1",
        data={},
    )
    payload = {
        "_transform": {"enrichment": {"history": {"dataset_id": "evil"}}},
        "enrichment": {"history": {"dataset_id": "evil"}},
    }
    _apply_transform_node_config(node, payload)
    assert payload["_transform"]["enrichment"] == spec


@pytest.mark.asyncio
async def test_flow_wrapper_runs_the_real_enrichment(db_session, sample):
    from app.services.skills_registry.wrappers import _sql_transform_v1

    ws, _, _, spec = sample
    result = await _sql_transform_v1(
        {"_transform": {"enrichment": spec, "node_id": "enrich", "output_name": "Flow features"}},
        {"workspace_id": ws.id},
    )
    row = db_session.get(TabularDataset, result["dataset_id"])
    assert row.node_id == "enrich"
    assert row.produced_by == "sql_transform_v1"
    assert row.parent_ids == [spec["base"]["dataset_id"], spec["history"]["dataset_id"]]
    assert read_frame(row)["prior_events"].to_list() == [2, 1, 3, 0]


def test_actual_bytes_are_bounded_even_with_understated_metadata(db_session, sample):
    ws, base, _, spec = sample
    base.size_bytes = 1
    db_session.commit()
    spec["max_input_bytes"] = 20
    db_session.get(TabularDataset, spec["history"]["dataset_id"]).size_bytes = 1
    db_session.commit()
    with pytest.raises(TabularError) as caught:
        preview_enrichment(db_session, workspace_id=ws.id, spec=spec)
    assert caught.value.code == "ENRICHMENT_INPUT_TOO_LARGE"


def test_declared_deadline_interrupts_sql_work(db_session, sample, monkeypatch):
    import threading

    import app.services.tabular_transforms as transforms

    ws, _, _, spec = sample
    real_timer = threading.Timer
    monkeypatch.setattr(
        transforms.threading, "Timer", lambda interval, callback: real_timer(0.0001, callback)
    )
    with pytest.raises(TabularError) as caught:
        preview_enrichment(db_session, workspace_id=ws.id, spec=spec)
    assert caught.value.code == "ENRICHMENT_TIMEOUT"


def test_synthetic_before_after_value_with_frozen_group_disjoint_protocol(db_session, sample):
    """Technical planted-signal fixture, NOT business evidence.

    Frozen protocol: seed 47, one decision/customer, 300 shuffled identities
    train / 100 test, same depth-2 tree, balanced accuracy; accept gain >= .20
    and enriched accuracy >= .85. The history also includes future distractors.
    """
    import numpy as np
    from sklearn.metrics import balanced_accuracy_score
    from sklearn.tree import DecisionTreeClassifier

    ws, _, _, _ = sample
    rng = np.random.default_rng(47)
    signal = rng.integers(0, 2, 400)
    base = register_frame(
        db_session,
        workspace_id=ws.id,
        name="Synthetic decisions",
        frame=pl.DataFrame(
            {
                "decision_id": list(range(400)),
                "customer_id": list(range(400)),
                "decision_time": ["2026-02-01"] * 400,
                "basket": rng.random(400),
                "late": signal,
            }
        ),
    )
    history = register_frame(
        db_session,
        workspace_id=ws.id,
        name="Synthetic history",
        frame=pl.DataFrame(
            {
                "event_id": list(range(800)),
                "customer_id": list(range(400)) * 2,
                "available_time": ["2026-01-01"] * 400 + ["2026-03-01"] * 400,
                "amount": list(signal * 10 + rng.random(400)) + [999.0] * 400,
            }
        ),
    )
    db_session.commit()
    spec = {
        "base": {"dataset_id": base.id, "version": base.version},
        "history": {"dataset_id": history.id, "version": history.version},
        "base_row_id": "decision_id",
        "history_row_id": "event_id",
        "base_key": "customer_id",
        "history_key": "customer_id",
        "decision_time": "decision_time",
        "available_time": "available_time",
        "base_features": ["basket"],
        "target_columns": ["late"],
        "max_unmatched_fraction": 0.0,
        "aggregates": [{"operation": "mean", "column": "amount", "output": "past_amount"}],
    }
    result = run_enrichment_transform(db_session, workspace_id=ws.id, spec=spec)
    frame = read_frame(db_session.get(TabularDataset, result["dataset_id"]))
    order = rng.permutation(400)
    train, test = order[:300], order[300:]
    scores = []
    for features in (["basket"], ["basket", "past_amount"]):
        X = frame.select(features).to_numpy()
        estimator = DecisionTreeClassifier(max_depth=2, random_state=47).fit(
            X[train], signal[train]
        )
        scores.append(balanced_accuracy_score(signal[test], estimator.predict(X[test])))
    print(
        {
            "evidence_level": "synthetic_technical_fixture",
            "baseline_balanced_accuracy": scores[0],
            "enriched_balanced_accuracy": scores[1],
            "gain": scores[1] - scores[0],
            "transform_ms": result["duration_ms"],
            "business_value": "not_measured",
        }
    )
    assert scores[1] >= 0.85
    assert scores[1] - scores[0] >= 0.20


def test_qualified_source_digest_is_checked_and_preserved(db_session, sample):
    ws, _, _, spec = sample
    qualified = preview_enrichment(db_session, workspace_id=ws.id, spec=spec)["enrichment"][
        "contract"
    ]
    replay = preview_enrichment(db_session, workspace_id=ws.id, spec=qualified)
    assert replay["enrichment"]["contract"] == qualified
    qualified["history"]["sha256"] = "0" * 64
    with pytest.raises(TabularError) as caught:
        run_enrichment_transform(db_session, workspace_id=ws.id, spec=qualified)
    assert caught.value.code == "ENRICHMENT_SOURCE_CHANGED"
    assert db_session.query(TabularDataset).count() == 2


def test_empty_history_preserves_rows_and_marks_unmatched(db_session, sample):
    ws, _, history, spec = sample
    empty = register_frame(
        db_session, workspace_id=ws.id, name="Empty history", frame=read_frame(history).head(0)
    )
    db_session.commit()
    spec["history"] = {"dataset_id": empty.id, "version": empty.version}
    preview = preview_enrichment(db_session, workspace_id=ws.id, spec=spec)
    assert preview["row_count"] == 4
    assert preview["enrichment"]["unmatched_fraction"] == 1.0
    assert all(row["prior_events"] == 0 and row["prior_mean"] is None for row in preview["preview"])
