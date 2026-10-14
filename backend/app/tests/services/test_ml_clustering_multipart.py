"""Physical row limits cover the whole clustering input, before materialization."""

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.resources import ml_clustering_harness as harness


@pytest.fixture
def parts(tmp_path):
    paths = []
    for index, values in enumerate(([1.0, 2.0, 3.0], [4.0, 5.0, 6.0])):
        path = tmp_path / f"part-{index}.parquet"
        pq.write_table(
            pa.table(
                {
                    "load": values,
                    "energy": [value * 10 for value in values],
                    "unused": ["ignored"] * 3,
                }
            ),
            path,
        )
        paths.append(str(path))
    return paths


def test_clustering_reads_all_parts_and_checks_the_combined_minimum(parts):
    frame = harness.read_frame(parts, ["energy", "load"], min_rows=5, clusters=2)
    assert list(frame.columns) == ["energy", "load"]
    assert frame["load"].tolist() == [1, 2, 3, 4, 5, 6]
    assert frame["energy"].tolist() == [10, 20, 30, 40, 50, 60]
    assert all(dtype == "float64" for dtype in frame.dtypes)


def test_clustering_refuses_the_total_limit_before_reading_any_values(parts, monkeypatch):
    monkeypatch.setattr(harness, "MAX_ROWS", 5)

    def forbidden(*args, **kwargs):
        pytest.fail("Over-budget multipart clustering input was materialized")

    monkeypatch.setattr(pd, "read_parquet", forbidden)
    with pytest.raises(ValueError, match="clustering row count"):
        harness.read_frame(parts, ["load"], min_rows=2, clusters=2)


@pytest.mark.parametrize("as_list", [False, True])
def test_clustering_preserves_legacy_file_and_single_part_manifest(tmp_path, as_list):
    path = tmp_path / "single.parquet"
    pq.write_table(pa.table({"load": [1.0, 2.0, 3.0, 4.0]}), path)
    source = [str(path)] if as_list else str(path)
    assert harness.read_frame(source, ["load"], min_rows=2, clusters=2)["load"].tolist() == [
        1,
        2,
        3,
        4,
    ]


def test_clustering_validates_values_in_later_parts(parts):
    pq.write_table(pa.table({"load": [float("inf"), 5.0, 6.0]}), parts[1])
    with pytest.raises(ValueError, match="infinite values"):
        harness.read_frame(parts, ["load"], min_rows=5, clusters=2)
