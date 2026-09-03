"""Ingest and profiling: the read model every tabular surface renders."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.tabular import TabularDataset
from app.models.workspace import Workspace
from app.services.tabular_datasets import (
    INGEST_STEPS,
    KIND_BOOLEAN,
    KIND_DATETIME,
    KIND_FLOAT,
    KIND_INTEGER,
    KIND_STRING,
    TabularError,
    create_upload,
    dataset_reference,
    detect_format,
    ingest_dataset,
    next_version,
    profile_frame,
    read_frame,
    register_frame,
    resolve_dataset_ref,
    serialize_dataset,
    slugify,
    soft_delete,
)

pl = pytest.importorskip("polars")


@pytest.fixture()
def workspace(db_session) -> Workspace:
    ws = Workspace(
        id=str(uuid4()),
        name="Tabular",
        slug=f"tabular-{uuid4().hex[:8]}",
        settings={},
    )
    db_session.add(ws)
    db_session.commit()
    return ws


@pytest.fixture()
def object_store_root(tmp_path, monkeypatch):
    """Point the ObjectStore facade at a scratch directory (local backend)."""

    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    return tmp_path / "store"


CSV = (
    "customer_id,tenure_months,monthly_charges,contract,churn,signed_at\n"
    "C1,12,45.5,monthly,true,2024-01-15\n"
    "C2,36,80.25,yearly,false,2023-02-20\n"
    "C3,3,,monthly,true,2024-06-01\n"
    "C4,24,60.0,yearly,false,2022-11-30\n"
)


def test_profile_frame_types_every_column_and_profiles_it():
    """The profile is the contract: canonical kinds, nulls, histograms, top values."""

    frame = pl.DataFrame(
        {
            "amount": [1.0, 2.0, 3.0, None],
            "count": [10, 20, 30, 40],
            "label": ["a", "b", "a", "a"],
            "flag": [True, False, True, True],
            "seen_at": [
                "2024-01-01",
                "2024-02-01",
                "2024-03-01",
                "2024-04-01",
            ],
        }
    ).with_columns(pl.col("seen_at").str.to_date())

    profile = profile_frame(frame)

    assert profile["row_count"] == 4
    assert profile["column_count"] == 5
    kinds = {col["name"]: col["kind"] for col in profile["schema"]}
    assert kinds == {
        "amount": KIND_FLOAT,
        "count": KIND_INTEGER,
        "label": KIND_STRING,
        "flag": KIND_BOOLEAN,
        "seen_at": KIND_DATETIME,
    }

    amount = profile["stats"]["amount"]
    assert amount["nulls"] == 1
    assert amount["min"] == 1.0 and amount["max"] == 3.0
    # Histograms are what the table header renders; numeric columns must carry one.
    assert amount["histogram"] and sum(b["count"] for b in amount["histogram"]) == 3

    label = profile["stats"]["label"]
    assert label["distinct"] == 2
    assert label["top_values"][0] == {"value": "a", "count": 3}

    # Dates reach the UI as ISO strings, and the whole profile must survive a
    # JSON round-trip: Postgres JSON columns reject NaN/Infinity and repr()s.
    assert profile["stats"]["seen_at"]["min"] == "2024-01-01"
    assert json.loads(json.dumps(profile)) == profile


def test_profile_drops_non_finite_floats_so_json_columns_accept_it():
    frame = pl.DataFrame({"ratio": [1.0, float("nan"), float("inf")]})

    profile = profile_frame(frame)

    assert json.loads(json.dumps(profile)) == profile
    assert profile["preview"][1]["ratio"] is None


def test_upload_then_ingest_writes_parquet_and_the_full_read_model(
    db_session, workspace, object_store_root
):
    dataset = create_upload(
        db_session,
        workspace_id=workspace.id,
        name="Churn export",
        filename="churn.csv",
        content_type="text/csv",
        payload=CSV.encode("utf-8"),
    )
    db_session.commit()
    assert dataset.status == "pending"
    # A step, never a mute spinner — and a code, because the page reading it is
    # French on one deployment and English on the next.
    assert dataset.status_detail == "queued"
    assert dataset.status_detail in INGEST_STEPS
    assert dataset.storage_key is None

    result = ingest_dataset(dataset.id)
    db_session.expire_all()
    dataset = db_session.query(TabularDataset).filter_by(id=dataset.id).one()

    assert result["status"] == "ready"
    assert dataset.status == "ready"
    assert dataset.status_detail is None
    assert dataset.row_count == 4 and dataset.column_count == 6
    assert dataset.storage_key.endswith("data.parquet")
    assert dataset.size_bytes and dataset.size_bytes > 0
    assert dataset.ingest_duration_ms is not None

    kinds = {col["name"]: col["kind"] for col in dataset.schema_json}
    assert kinds["tenure_months"] == KIND_INTEGER
    assert kinds["monthly_charges"] == KIND_FLOAT
    assert kinds["contract"] == KIND_STRING
    assert dataset.stats_json["monthly_charges"]["nulls"] == 1
    assert len(dataset.preview_json) == 4

    # The bytes are readable back through the same facade the workers use.
    frame = read_frame(dataset)
    assert frame.height == 4
    assert frame.get_column("contract").to_list()[0] == "monthly"


def test_ingest_walks_the_declared_steps_in_order(
    db_session, workspace, object_store_root, monkeypatch
):
    """The steps a surface renders as a check-list are the ones the worker walks,
    in the order it walks them — so `INGEST_STEPS` is a contract, not a label."""

    from app.services import tabular_datasets

    walked: list[str] = []
    written: list[str] = []
    real = tabular_datasets.mark_step

    def spy(db, dataset, step, *, rows=None):
        walked.append(step)
        real(db, dataset, step, rows=rows)
        written.append(dataset.status_detail)

    monkeypatch.setattr(tabular_datasets, "mark_step", spy)

    dataset = create_upload(
        db_session,
        workspace_id=workspace.id,
        name="Churn export",
        filename="churn.csv",
        content_type="text/csv",
        payload=CSV.encode("utf-8"),
    )
    db_session.commit()
    ingest_dataset(dataset.id)

    assert walked == ["reading", "profiling", "writing"]
    # Plus the queued one the API stamps before the worker exists, which is the
    # whole list.
    assert ["queued", *walked] == list(INGEST_STEPS)

    # Once the parse has a height, the step carries it. That is the difference
    # between a progress line and a fact: "profiling" is what a spinner says,
    # "3 rows" is what tells the reader their file arrived whole. A number and
    # not a sentence, because the thousands separator belongs to the locale and
    # two of them poll this same row.
    rows = CSV.strip().count("\n")
    assert written == ["reading", f"profiling:{rows}", f"writing:{rows}"]


def test_ingest_failure_records_a_reason_instead_of_hanging_in_progress(
    db_session, workspace, object_store_root
):
    dataset = create_upload(
        db_session,
        workspace_id=workspace.id,
        name="Broken",
        filename="broken.csv",
        content_type="text/csv",
        payload=b"a,b\n1,2\n3,4,5,6\n",
    )
    db_session.commit()

    ingest_dataset(dataset.id)
    db_session.expire_all()
    dataset = db_session.query(TabularDataset).filter_by(id=dataset.id).one()

    assert dataset.status == "failed"
    assert dataset.error
    assert dataset.status_detail is None


def test_upload_rejects_unsupported_formats_and_oversized_payloads(
    db_session, workspace, object_store_root, monkeypatch
):
    with pytest.raises(TabularError) as unsupported:
        create_upload(
            db_session,
            workspace_id=workspace.id,
            name="Photo",
            filename="holiday.png",
            content_type="image/png",
            payload=b"\x89PNG",
        )
    assert unsupported.value.code == "DATASET_FORMAT_UNSUPPORTED"

    monkeypatch.setattr(settings, "tabular_upload_max_bytes", 8)
    with pytest.raises(TabularError) as too_large:
        create_upload(
            db_session,
            workspace_id=workspace.id,
            name="Big",
            filename="big.csv",
            content_type="text/csv",
            payload=CSV.encode("utf-8"),
        )
    assert too_large.value.code == "DATASET_TOO_LARGE"

    with pytest.raises(TabularError) as empty:
        create_upload(
            db_session,
            workspace_id=workspace.id,
            name="Empty",
            filename="empty.csv",
            content_type="text/csv",
            payload=b"",
        )
    assert empty.value.code == "DATASET_EMPTY"


def test_register_frame_versions_the_slug_and_records_lineage(
    db_session, workspace, object_store_root
):
    first = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Clean customers",
        frame=pl.DataFrame({"id": [1, 2], "score": [0.4, 0.6]}),
        produced_by="sql_transform_v1",
        run_id="run-1",
        node_id="node-a",
    )
    db_session.commit()
    second = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Clean customers",
        frame=pl.DataFrame({"id": [1, 2, 3], "score": [0.4, 0.6, 0.9]}),
        produced_by="sql_transform_v1",
        parent_ids=[first.id],
    )
    db_session.commit()

    assert first.slug == second.slug == "clean-customers"
    assert (first.version, second.version) == (1, 2)
    assert second.parent_ids == [first.id]
    assert second.status == "ready" and second.row_count == 3
    assert next_version(db_session, workspace_id=workspace.id, slug=first.slug) == 3

    # Datasets travel through the DAG by reference, with the counts the canvas
    # badges read straight off the envelope.
    reference = dataset_reference(second)
    assert reference["dataset_id"] == second.id
    assert reference["rows"] == 3 and reference["columns"] == 2


def test_a_frame_produced_by_a_run_belongs_to_the_run_system(
    db_session, workspace, object_store_root
):
    """The producers know their run; the row must know its System, or the
    data plane stays beside the mental model instead of inside it."""
    from app.models.run import Run
    from app.models.system import System

    system = System(id=str(uuid4()), workspace_id=workspace.id, name="Scoring")
    run = Run(id=str(uuid4()), workspace_id=workspace.id, system_id=system.id)
    db_session.add_all([system, run])
    db_session.commit()

    scored = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Scored",
        frame=pl.DataFrame({"id": [1], "score": [0.7]}),
        produced_by="ml_score_v1",
        run_id=run.id,
        node_id="score",
    )
    adhoc = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Adhoc",
        frame=pl.DataFrame({"id": [1]}),
        produced_by="sql_transform_v1",
        run_id="run-that-was-purged",
    )
    db_session.commit()

    assert scored.system_id == system.id
    assert serialize_dataset(scored)["system_id"] == system.id
    assert adhoc.system_id is None


def test_resolve_ref_accepts_id_envelope_or_latest_ready_slug(
    db_session, workspace, object_store_root
):
    old = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Kpi cells",
        frame=pl.DataFrame({"cell": ["a"]}),
    )
    newer = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Kpi cells",
        frame=pl.DataFrame({"cell": ["a", "b"]}),
    )
    db_session.commit()

    assert resolve_dataset_ref(
        db_session, workspace_id=workspace.id, ref=old.id
    ).id == old.id
    assert resolve_dataset_ref(
        db_session, workspace_id=workspace.id, ref={"dataset_id": newer.id}
    ).id == newer.id
    # A slug resolves to the newest ready version — how flows pin "the" table.
    assert resolve_dataset_ref(
        db_session, workspace_id=workspace.id, ref={"slug": "kpi-cells"}
    ).id == newer.id

    with pytest.raises(TabularError) as missing:
        resolve_dataset_ref(
            db_session, workspace_id=workspace.id, ref={"slug": "nope"}
        )
    assert missing.value.code == "DATASET_NOT_FOUND"


def test_soft_delete_hides_the_row_and_survives_an_append_only_store(
    db_session, workspace, object_store_root
):
    dataset = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Scratch",
        frame=pl.DataFrame({"x": [1]}),
    )
    db_session.commit()

    soft_delete(db_session, dataset)

    assert dataset.status == "deleted"
    with pytest.raises(TabularError):
        resolve_dataset_ref(db_session, workspace_id=workspace.id, ref=dataset.id)


def test_slug_and_format_detection_cover_the_demo_inputs():
    assert slugify("Churn — Clients Été 2026") == "churn-clients-ete-2026"
    assert slugify("   ") == "dataset"
    assert detect_format("a.csv") == "csv"
    assert detect_format("a.tsv") == "tsv"
    assert detect_format("a.parquet") == "parquet"
    assert detect_format("a.xlsx") == "xlsx"
    assert detect_format("blob", "text/csv") == "csv"


def test_serialize_keeps_the_heavy_blocks_out_of_list_payloads(
    db_session, workspace, object_store_root
):
    dataset = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Wide",
        frame=pl.DataFrame({"a": [1, 2], "b": ["x", "y"]}),
    )
    db_session.commit()

    listed = serialize_dataset(dataset)
    detail = serialize_dataset(dataset, include_preview=True)

    assert "preview" not in listed and "stats" not in listed
    assert listed["schema"] and listed["row_count"] == 2
    assert detail["preview"] and detail["stats"]["b"]["top_values"]


def test_the_detail_payload_credits_the_model_that_scored_the_dataset(
    db_session, workspace, object_store_root
):
    """A column nobody uploaded must say where it came from.

    The lineage block is curated on the way out: the model and the columns it
    added are what the detail page badges, while the producer's own program is
    not republished on a dataset page.
    """

    dataset = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Base scored",
        frame=pl.DataFrame({"msisdn": ["a", "b"], "prediction": ["1", "0"]}),
        source="score",
        lineage={
            "engine": "sklearn",
            "model": {"model_id": "m1", "slug": "churn-risk", "version": 3},
            "added_columns": ["prediction"],
            "duration_ms": 412.0,
            "sql": "select * from secrets",
        },
    )
    db_session.commit()

    listed = serialize_dataset(dataset)
    detail = serialize_dataset(dataset, include_preview=True)

    assert "lineage" not in listed, "a list row does not carry provenance blocks"
    assert detail["lineage"]["model"] == {
        "model_id": "m1",
        "slug": "churn-risk",
        "version": 3,
    }
    assert detail["lineage"]["added_columns"] == ["prediction"]
    assert detail["lineage"]["engine"] == "sklearn"
    assert "sql" not in detail["lineage"]


def test_an_uploaded_dataset_has_an_empty_lineage_rather_than_none(
    db_session, workspace, object_store_root
):
    dataset = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Plain",
        frame=pl.DataFrame({"a": [1]}),
    )
    db_session.commit()

    assert serialize_dataset(dataset, include_preview=True)["lineage"] == {}
