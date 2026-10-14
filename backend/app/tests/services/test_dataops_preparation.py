"""DataOps correctness across SQL compilation, real workers and Delta readers."""

from uuid import uuid4

import polars as pl
import pyarrow as pa
import pytest

from app.core.config import settings
from app.models.tabular import TabularDataset
from app.models.workspace import Workspace
from app.schemas.data_prep import DataPrepSpec
from app.services.dataops.compiler import expression
from app.services.dataops.preparation import preview_preparation, submit_preparation
from app.services.dataops.storage import (
    dataset_digest,
    materialize_files,
    settle_files,
    write_batches,
)
from app.services.object_store import get_object_store
from app.services.tabular_datasets import read_frame, register_frame, reserve_frame


@pytest.fixture
def plane(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "dataops_enabled", True)
    monkeypatch.setattr(settings, "worker_eager_mode", True)
    monkeypatch.setattr(settings, "dataops_write_delta_enabled", False)
    workspace = Workspace(id=str(uuid4()), slug="prep", name="Preparation", settings={})
    db_session.add(workspace)
    db_session.commit()
    dataset = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Input",
        frame=pl.DataFrame(
            {
                "id": list(range(20)),
                "value": [float(i) for i in range(20)],
                "group": ["n", "s"] * 10,
            }
        ),
    )
    db_session.commit()
    return workspace, dataset


def spec(operation="prepare", params=None, steps=None, outputs=None):
    return DataPrepSpec(
        operation=operation,
        params=params or {},
        steps=steps or [],
        outputs=outputs or [{"name": "Result", "port": "out"}],
    )


@pytest.mark.parametrize(
    "operation,params,expected",
    [
        ("prepare", {}, 20),
        (
            "aggregate",
            {
                "group_by": ["group"],
                "aggregates": [{"column": "value", "function": "sum", "name": "total"}],
            },
            2,
        ),
        (
            "pivot",
            {"group_by": [], "column": "group", "values": ["n", "s"], "value_column": "value"},
            1,
        ),
        ("unpivot", {"columns": ["id", "value"]}, 40),
        ("sample", {"keys": ["id"], "rows": 5}, 5),
    ],
)
def test_real_worker_operations(db_session, plane, operation, params, expected):
    workspace, dataset = plane
    row = submit_preparation(
        db_session,
        workspace_id=workspace.id,
        spec=spec(operation, params),
        inputs={"in": {"dataset_id": dataset.id}},
    )
    assert row.status == "succeeded", row.error
    result = db_session.get(TabularDataset, row.output_json["dataset_id"])
    assert result.row_count == expected
    assert read_frame(result).height == expected


def test_join_and_union_use_named_authorized_ports(db_session, plane):
    workspace, dataset = plane
    right = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="References",
        frame=pl.DataFrame({"id": [1, 2], "label": ["one", "two"]}),
    )
    db_session.commit()
    row = submit_preparation(
        db_session,
        workspace_id=workspace.id,
        spec=spec("join", {"keys": [{"left": "id", "right": "id"}]}),
        inputs={"left": {"dataset_id": dataset.id}, "right": {"dataset_id": right.id}},
    )
    assert row.status == "succeeded", row.error
    result = read_frame(db_session.get(TabularDataset, row.output_json["dataset_id"]))
    assert result.filter(pl.col("id") == 1)["label"].item() == "one"
    row = submit_preparation(
        db_session,
        workspace_id=workspace.id,
        spec=spec("union", outputs=[{"name": "Combined"}]),
        inputs={"a": {"dataset_id": dataset.id}, "b": {"dataset_id": dataset.id}},
    )
    assert row.status == "succeeded", row.error
    assert row.output_json["rows"] == 40


def test_split_is_complete_disjoint_and_reproducible(db_session, plane):
    workspace, dataset = plane
    config = spec(
        "split",
        {"keys": ["id"], "ratios": [0.7, 0.3], "stratify": ["group"]},
        outputs=[{"name": "Train", "port": "train"}, {"name": "Test", "port": "test"}],
    )
    row = submit_preparation(
        db_session,
        workspace_id=workspace.id,
        spec=config,
        inputs={"in": {"dataset_id": dataset.id}},
    )
    assert row.status == "succeeded", row.error
    outputs = row.output_json["outputs"]
    train = read_frame(db_session.get(TabularDataset, outputs["train"]["dataset_id"]))
    test = read_frame(db_session.get(TabularDataset, outputs["test"]["dataset_id"]))
    assert train.height + test.height == 20
    assert set(train["id"]).isdisjoint(set(test["id"]))
    assert train.height == 14


def test_steps_are_typed_and_do_not_allow_sql_escape(db_session, plane):
    workspace, dataset = plane
    config = spec(
        steps=[
            {"action": "derive", "params": {"name": "twice", "expression": "value*2"}},
            {"action": "filter", "params": {"expression": "twice>=20"}},
            {"action": "cast", "params": {"column": "twice", "type": "BIGINT"}},
        ]
    )
    row = submit_preparation(
        db_session,
        workspace_id=workspace.id,
        spec=config,
        inputs={"in": {"dataset_id": dataset.id}},
    )
    assert row.status == "succeeded", row.error
    frame = read_frame(db_session.get(TabularDataset, row.output_json["dataset_id"]))
    assert frame.height == 10 and frame["twice"].dtype == pl.Int64
    for source in ["(SELECT 1)", "read_csv('/etc/passwd')", "id; SELECT 2", "missing+1"]:
        with pytest.raises(ValueError):
            expression(source, ["id"])


def test_cross_workspace_and_slug_takeover_are_refused(db_session, plane):
    workspace, dataset = plane
    with pytest.raises(Exception):
        submit_preparation(
            db_session, workspace_id="other", spec=spec(), inputs={"in": {"dataset_id": dataset.id}}
        )
    with pytest.raises(ValueError, match="SLUG_TAKEN"):
        submit_preparation(
            db_session,
            workspace_id=workspace.id,
            spec=spec(outputs=[{"name": "Input"}]),
            inputs={"in": {"dataset_id": dataset.id}},
        )


def test_preview_declares_sample_and_does_not_create_outputs(db_session, plane):
    workspace, dataset = plane
    before = db_session.query(TabularDataset).count()
    result = preview_preparation(
        db_session,
        workspace_id=workspace.id,
        spec=spec(),
        inputs={"in": {"dataset_id": dataset.id}},
    )
    assert result["sample"] is True and result["sample_metadata"]["method"] == "persisted"
    assert db_session.query(TabularDataset).count() == before


def test_delta_commit_controls_parts_and_detects_corruption(db_session, plane, tmp_path):
    workspace, _ = plane
    target = reserve_frame(db_session, workspace_id=workspace.id, name="Delta", commit=False)
    table = pa.table({"id": [1, 2], "value": [1.5, None]})
    paths = write_batches(tmp_path / "delta", table.to_batches(), schema=table.schema, delta=True)
    settle_files(db_session, target, paths, delta_root=tmp_path / "delta")
    db_session.commit()
    assert read_frame(target).height == 2
    digest = dataset_digest(target)
    store = get_object_store()
    store.write_bytes(f"{target.storage_key}/uncommitted.parquet", b"orphan")
    assert dataset_digest(target) == digest
    materialized = materialize_files(target, tmp_path / "materialized")
    assert len(materialized) == len(paths)
    part = next(iter(target.lineage_json["storage"]["parts"]))
    store.write_bytes(f"{target.storage_key}/{part}", b"broken")
    with pytest.raises(ValueError, match="INTEGRITY|budget"):
        materialize_files(target, tmp_path / "broken")


def test_delta_legacy_reader_and_atomic_split(db_session, plane, monkeypatch):
    workspace, dataset = plane
    monkeypatch.setattr(settings, "dataops_write_delta_enabled", True)
    config = spec(
        "split",
        {"keys": ["id"], "ratios": [0.5, 0.5]},
        outputs=[{"name": "A", "port": "a"}, {"name": "B", "port": "b"}],
    )
    row = submit_preparation(
        db_session,
        workspace_id=workspace.id,
        spec=config,
        inputs={"in": {"dataset_id": dataset.id}},
    )
    assert row.status == "succeeded", row.error
    assert (
        sum(
            read_frame(db_session.get(TabularDataset, ref["dataset_id"])).height
            for ref in row.output_json["outputs"].values()
        )
        == 20
    )


def test_delta_settlement_accepts_a_symlinked_temporary_directory(db_session, plane, tmp_path):
    workspace, _ = plane
    physical = tmp_path / "physical"
    physical.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(physical, target_is_directory=True)
    delta_root = linked / "delta"
    target = reserve_frame(db_session, workspace_id=workspace.id, name="Linked Delta", commit=False)
    table = pa.table({"id": [1, 2], "value": [1.5, None]})
    paths = write_batches(delta_root, table.to_batches(), schema=table.schema, delta=True)

    # Delta's Rust reader returns canonical paths even when its input uses an alias.
    assert delta_root != delta_root.resolve()
    assert all(path.is_relative_to(delta_root.resolve()) for path in paths)
    settle_files(db_session, target, paths, delta_root=delta_root)
    db_session.commit()

    assert target.status == "ready"
    assert read_frame(target).to_dicts() == table.to_pylist()
    assert all(
        not key.startswith("/") and ".." not in key.split("/")
        for key in target.lineage_json["storage"]["parts"]
    )


def test_delta_settlement_refuses_a_file_symlink_outside_its_commit(db_session, plane, tmp_path):
    workspace, _ = plane
    table = pa.table({"id": [1, 2]})
    external = write_batches(tmp_path / "external", table.to_batches(), schema=table.schema)[0]
    delta_root = tmp_path / "delta"
    write_batches(delta_root, table.to_batches(), schema=table.schema, delta=True)
    escape = delta_root / "outside.parquet"
    escape.symlink_to(external)
    target = reserve_frame(db_session, workspace_id=workspace.id, name="Escape", commit=False)

    with pytest.raises(ValueError, match="not in the subpath"):
        settle_files(db_session, target, [escape], delta_root=delta_root)

    assert target.status == "ingesting"
    assert not get_object_store().list_keys(
        f"workspaces/{workspace.id}/tabular/datasets/{target.id}"
    )


def test_failed_split_publishes_no_ready_output(db_session, plane, monkeypatch):
    from app.services.dataops import preparation

    workspace, dataset = plane
    original = preparation.settle_files
    count = 0

    def fail_second(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise ValueError("simulated writer failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(preparation, "settle_files", fail_second)
    row = submit_preparation(
        db_session,
        workspace_id=workspace.id,
        spec=spec(
            "split",
            {"keys": ["id"], "ratios": [0.5, 0.5]},
            outputs=[{"name": "A", "port": "a"}, {"name": "B", "port": "b"}],
        ),
        inputs={"in": {"dataset_id": dataset.id}},
    )
    assert row.status == "failed"
    assert all(
        db_session.get(TabularDataset, identifier).status == "failed"
        for identifier in row.input_json["outputs"].values()
    )
