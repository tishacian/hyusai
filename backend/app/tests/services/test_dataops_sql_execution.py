"""SQL transforms on the worker plane: the DuckDB runner and the row it settles.

The runner is a standalone program, so most of its contract is pinned by
running it the way the worker does — as a subprocess, from a manifest.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.config import Settings, settings
from app.models.recipe import RecipeExecution
from app.models.tabular import TabularDataset
from app.models.workspace import Workspace
from app.services.dataops import sql_execution
from app.services.dataops.sql_execution import runner_path, submit_sql_run
from app.services.tabular_datasets import TabularError, register_frame

pl = pytest.importorskip("polars")
pytest.importorskip("duckdb")
pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

REPO = Path(__file__).resolve().parents[4]


def _run(tmp_path: Path, manifest: dict) -> tuple[int, str, dict | None]:
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    done = subprocess.run(  # noqa: S603 - the interpreter running the tests
        [
            sys.executable,
            str(runner_path()),
            str(tmp_path / "manifest.json"),
            str(tmp_path / "result.json"),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    result = tmp_path / "result.json"
    summary = json.loads(result.read_text()) if result.exists() else None
    return done.returncode, done.stderr, summary


def _manifest(tmp_path: Path, sql: str, **overrides) -> dict:
    manifest = {
        "views": [{"name": "orders", "path": str(tmp_path / "orders.parquet")}],
        "aliases": {"input": "orders", "input_1": "orders"},
        "sql": sql,
        "output_path": str(tmp_path / "out.parquet"),
        "row_limit": 1_000_000,
        "max_output_bytes": 64 * 1024**2,
        "duckdb": {
            "memory_mb": 256,
            "threads": 1,
            "temp_directory": str(tmp_path / "spill"),
            "max_temp_mb": 512,
        },
    }
    manifest.update(overrides)
    return manifest


@pytest.fixture()
def orders(tmp_path: Path) -> Path:
    path = tmp_path / "orders.parquet"
    pq.write_table(
        pa.table(
            {
                "id": list(range(1000)),
                "amount": [i * 1.5 for i in range(1000)],
                "region": ["n", "s"] * 500,
            }
        ),
        path,
    )
    return path


def test_the_runner_streams_a_statement_over_its_views_and_aliases(tmp_path, orders):
    code, stderr, summary = _run(
        tmp_path,
        _manifest(
            tmp_path,
            "SELECT region, count(*) AS n, sum(amount) AS total FROM input_1 GROUP BY 1 ORDER BY 1",
        ),
    )

    assert code == 0, stderr
    assert summary["rows"] == 2 and summary["bytes"] > 0
    out = pl.read_parquet(tmp_path / "out.parquet")
    assert out.columns == ["region", "n", "total"]
    assert out["n"].to_list() == [500, 500]


def test_an_answer_past_the_row_limit_is_refused_before_it_is_computed_in_full(tmp_path, orders):
    code, stderr, summary = _run(tmp_path, _manifest(tmp_path, "SELECT * FROM input", row_limit=10))

    assert code == 2 and summary is None
    assert "SQL_RESULT_TOO_LARGE" in stderr


def test_a_sort_larger_than_memory_spills_instead_of_failing(tmp_path):
    rows = 2_000_000
    pq.write_table(
        pa.table(
            {
                "k": [(i * 7919) % rows for i in range(rows)],
                "s": [f"row-{i % 5000}" for i in range(rows)],
            }
        ),
        tmp_path / "orders.parquet",
    )
    manifest = _manifest(
        tmp_path,
        "SELECT k, s FROM input ORDER BY k",
        row_limit=rows,
        max_output_bytes=512 * 1024**2,
        duckdb={
            "memory_mb": 32,
            "threads": 1,
            "temp_directory": str(tmp_path / "spill"),
            "max_temp_mb": 1024,
        },
    )

    code, stderr, summary = _run(tmp_path, manifest)

    assert code == 0, stderr
    assert summary["rows"] == rows
    head = pl.read_parquet(tmp_path / "out.parquet", n_rows=3)["k"].to_list()
    assert head == [0, 1, 2]


def test_without_a_spill_budget_running_out_of_memory_is_an_error(tmp_path):
    rows = 2_000_000
    pq.write_table(
        pa.table(
            {
                "k": [(i * 7919) % rows for i in range(rows)],
                "s": [f"row-{i % 5000}" for i in range(rows)],
            }
        ),
        tmp_path / "orders.parquet",
    )
    manifest = _manifest(
        tmp_path,
        "SELECT k, s FROM input ORDER BY k",
        row_limit=rows,
        duckdb={"memory_mb": 32, "threads": 1, "temp_directory": "", "max_temp_mb": 0},
    )

    code, stderr, _ = _run(tmp_path, manifest)

    assert code == 1 and "SQL_EXECUTION_FAILED" in stderr


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT * FROM read_parquet('{path}')",
        "SELECT * FROM '{path}'",
        "SELECT * FROM glob('*')",
    ],
)
def test_the_sealed_engine_reads_no_path_the_statement_names(tmp_path, orders, statement):
    """Validation refuses these upstream; the seal is the second wall."""

    code, stderr, _ = _run(tmp_path, _manifest(tmp_path, statement.format(path=orders)))

    assert code == 1
    assert "disabled by configuration" in stderr


# ---------------------------------------------------------------------------
# The row the worker settles
# ---------------------------------------------------------------------------


@pytest.fixture()
def workspace(db_session) -> Workspace:
    ws = Workspace(id=str(uuid4()), name="Dataops", slug=f"dataops-{uuid4().hex[:8]}", settings={})
    db_session.add(ws)
    db_session.commit()
    return ws


@pytest.fixture()
def eager(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "worker_eager_mode", True)


@pytest.fixture()
def customers(db_session, workspace, eager) -> TabularDataset:
    dataset = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Customers",
        frame=pl.DataFrame({"customer_id": ["C1", "C2", "C3"], "churn": [1, 0, 1]}),
        source="upload",
    )
    db_session.commit()
    return dataset


def test_a_run_settles_its_row_and_registers_the_streamed_result(db_session, workspace, customers):
    execution = submit_sql_run(
        db_session,
        workspace_id=workspace.id,
        sql="SELECT churn, count(*) AS n FROM customers GROUP BY 1 ORDER BY 1",
        output_name="Churn split",
        declared=[{"dataset_id": customers.id}],
        run_id="run-1",
        node_id="node-sql",
    )

    db_session.expire_all()
    row = db_session.get(RecipeExecution, execution.id)
    assert row.status == "succeeded", row.error
    assert row.env_id is None and row.input_json["kind"] == "sql_transform"
    dataset = db_session.get(TabularDataset, row.output_json["dataset_id"])
    assert dataset.row_count == 2 and dataset.parent_ids == [customers.id]
    assert dataset.lineage_json["engine"] == "duckdb"
    assert dataset.lineage_json["placement"] == "local"
    assert dataset.lineage_json["runner"]["rows"] == 2


def test_an_engine_error_fails_the_row_with_the_coded_reason(db_session, workspace, customers):
    execution = submit_sql_run(
        db_session,
        workspace_id=workspace.id,
        sql="SELECT nope FROM input",
        output_name="Broken",
        declared=[{"dataset_id": customers.id}],
    )

    db_session.expire_all()
    row = db_session.get(RecipeExecution, execution.id)
    assert row.status == "failed"
    assert row.error.startswith("SQL_EXECUTION_FAILED: ")
    assert "nope" in row.error
    assert db_session.query(TabularDataset).filter_by(slug="broken").count() == 0


def test_a_forbidden_statement_is_refused_before_anything_is_queued(
    db_session, workspace, customers
):
    with pytest.raises(TabularError) as refused:
        submit_sql_run(
            db_session,
            workspace_id=workspace.id,
            sql="COPY input TO 'x.csv'",
            output_name="x",
            declared=[{"dataset_id": customers.id}],
        )

    assert refused.value.code == "SQL_FORBIDDEN_KEYWORD"
    assert db_session.query(RecipeExecution).filter_by(workspace_id=workspace.id).count() == 0


def test_a_row_found_running_was_claimed_by_a_dead_worker_and_fails_closed(
    db_session, workspace, customers, monkeypatch
):
    monkeypatch.setattr(sql_execution, "dispatch_sql_execution", lambda db, execution: "queued")
    execution = submit_sql_run(
        db_session,
        workspace_id=workspace.id,
        sql="SELECT 1 AS one",
        output_name="x",
        declared=[{"dataset_id": customers.id}],
    )
    execution.status = "running"
    db_session.commit()

    assert sql_execution.run_sql_execution(execution.id)["status"] == "failed"
    db_session.expire_all()
    assert db_session.get(RecipeExecution, execution.id).error == "sql_worker_lost_after_claim"


def test_a_cancel_requested_before_the_claim_settles_the_row_without_running(
    db_session, workspace, customers, monkeypatch
):
    monkeypatch.setattr(sql_execution, "dispatch_sql_execution", lambda db, execution: "queued")
    execution = submit_sql_run(
        db_session,
        workspace_id=workspace.id,
        sql="SELECT 1 AS one",
        output_name="x",
        declared=[{"dataset_id": customers.id}],
    )
    execution.cancel_requested = True
    db_session.commit()

    assert sql_execution.run_sql_execution(execution.id)["status"] == "cancelled"


def test_transforms_are_dispatched_to_the_dataops_queue(
    monkeypatch, db_session, workspace, customers
):
    """SQL, Polars and dbt runs all leave the CPU pool their walkers wait in."""

    from app.services import tabular_dbt, tabular_polars
    from app.workers import celery_app as celery_module

    sent: list[tuple[str, str]] = []

    class _Result:
        id = "task-1"

    def _send(name, args=(), queue=None, **_):
        sent.append((name, queue))
        return _Result()

    monkeypatch.setattr(settings, "worker_eager_mode", False)
    monkeypatch.setattr(celery_module.celery_app, "send_task", _send)

    submit_sql_run(
        db_session,
        workspace_id=workspace.id,
        sql="SELECT 1 AS one",
        output_name="x",
        declared=[{"dataset_id": customers.id}],
    )
    row = RecipeExecution(
        id=str(uuid4()), workspace_id=workspace.id, status="queued", input_json={}
    )
    db_session.add(row)
    db_session.commit()
    tabular_polars.dispatch_polars_execution(db_session, row, code="x")
    tabular_dbt.dispatch_dbt_execution(db_session, row)

    assert [queue for _, queue in sent] == ["dataops"] * 3
    assert sent[0][0] == "agentium.dataops_sql_execute"


def test_the_workshop_mirrors_the_backend_statement_ceiling():
    source = (
        REPO / "frontend-ng/src/app/features/orchestration/flow/flow-transform.vm.ts"
    ).read_text()
    mirrored = re.search(r"export const SQL_MAX_CHARS = ([\d_]+);", source)

    assert mirrored is not None
    assert (
        int(mirrored.group(1).replace("_", ""))
        == Settings.model_fields["tabular_sql_max_chars"].default
    )
