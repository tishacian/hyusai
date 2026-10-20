"""A real local Delta history is read using only captured objects and identities."""

import hashlib
import shutil
from datetime import UTC, datetime, timedelta

import pyarrow as pa
import pytest
from deltalake import write_deltalake

from app.services.connectors.adapters.delta_reader import _action, stage_delta
from app.services.connectors.adapters.sql import AdapterError


def test_delta_history_uses_active_parts_and_partition_values(tmp_path):
    source = tmp_path / "source"
    write_deltalake(
        str(source), pa.table({"group": ["A", "B"], "value": [1, 2]}), partition_by=["group"]
    )
    write_deltalake(
        str(source),
        pa.table({"group": ["A", "C"], "value": [3, 4]}),
        mode="overwrite",
        partition_by=["group"],
    )
    items = []
    for path in source.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            items.append(
                {
                    "key": "root/" + path.relative_to(source).as_posix(),
                    "size": len(data),
                    "etag": hashlib.sha256(data).hexdigest(),
                }
            )
    copied = []

    class Client:
        def download(self, item, path, max_bytes):
            src = source / item["key"].removeprefix("root/")
            assert hashlib.sha256(src.read_bytes()).hexdigest() == item["etag"]
            shutil.copyfile(src, path)
            copied.append(item["key"])
            return {}, src.stat().st_size, item["etag"]

    out = tmp_path / "out"
    out.mkdir()
    result = stage_delta(
        Client(),
        items,
        out,
        operation="import",
        max_rows=10,
        max_bytes=1024**2,
        deadline=(datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
        preview_limit=100,
    )
    assert result["row_count"] == 2 and result["delta_version"] == 1
    assert result["consistency"] == "snapshot"
    assert len([key for key in copied if key.endswith(".parquet")]) == 2
    import json

    values = [
        dict(zip(result["columns"], json.loads(row)))
        for row in (out / "rows.jsonl").read_text().splitlines()
    ]
    assert sorted(values, key=lambda r: r["value"]) == [
        {"group": "A", "value": 3},
        {"group": "C", "value": 4},
    ]


@pytest.mark.parametrize(
    "path",
    ["../outside", "%2e%2e/outside", "https://metadata.test/file", "/etc/passwd", "a/../../escape"],
)
def test_delta_actions_cannot_reference_outside_captured_table(path):
    with pytest.raises(AdapterError):
        _action({"add": {"path": path}})


def test_delta_deletion_vectors_are_not_silently_ignored():
    with pytest.raises(AdapterError, match="CONNECTOR_DELTA_FEATURE_UNSUPPORTED"):
        _action({"add": {"path": "data.parquet", "deletionVector": {"pathOrInlineDv": "v"}}})


@pytest.mark.parametrize(
    "action",
    [
        {"sidecar": {"path": "../outside.parquet"}},
        {"checkpointMetadata": {"version": 4}},
        {"metaData": {"configuration": {"delta.columnMapping.mode": "name"}}},
    ],
)
def test_unsupported_visibility_and_checkpoint_features_fail_closed(action):
    with pytest.raises(AdapterError, match="CONNECTOR_DELTA_FEATURE_UNSUPPORTED"):
        _action(action)
