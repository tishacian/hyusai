"""The dbt transform node: harness contract, worker lifecycle, DAG contract.

Two testing postures, on purpose.

The **harness contract** needs a real dbt, so a venv carrying the pinned adapter
is built once per session and cached across runs. It is the only way to prove
what actually matters about this node: that ``ref()`` links models, that
``source()`` reaches the node's inputs, and that a failing data test comes back
as a distinct verdict rather than a generic error. Without network the fixture
skips instead of failing — the rest of the file still runs.

The **worker lifecycle** is exercised with a stubbed harness that writes the
Parquet and the summary a real one would. That keeps the interesting assertions
— which row status, which lineage, whether a dataset gets published at all —
deterministic and dbt-free.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.recipe import PythonEnv, RecipeExecution
from app.models.tabular import TabularDataset
from app.models.workspace import Workspace
from app.services import recipe_executions, tabular_dbt
from app.services.recipe_executions import SupervisedRun
from app.services.tabular_dbt import (
    clamp_timeout,
    effective_requirements,
    env_spec_for,
    harness_path,
    resolve_output_model,
    run_dbt_execution,
    submit_dbt_run,
    validate_models,
)

pl = pytest.importorskip("polars")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def workspace(db_session) -> Workspace:
    ws = Workspace(
        id=str(uuid4()),
        name="dbt node",
        slug=f"dbt-node-{uuid4().hex[:8]}",
        settings={},
    )
    db_session.add(ws)
    db_session.commit()
    return ws


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    return tmp_path / "store"


@pytest.fixture()
def enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "recipe_execution_enabled", True)
    monkeypatch.setattr(settings, "recipe_envs_path", str(tmp_path / "envs"))
    monkeypatch.setattr(settings, "worker_eager_mode", True)
    interpreter = Path(sys.executable)
    monkeypatch.setattr(
        tabular_dbt, "env_python", lambda workspace_id, fingerprint: interpreter
    )
    monkeypatch.setattr(
        recipe_executions, "env_python", lambda workspace_id, fingerprint: interpreter
    )


@pytest.fixture()
def ready_env(db_session, workspace, enabled) -> PythonEnv:
    """The node's env row, flipped ready without paying for a real build."""

    env = tabular_dbt.resolve_dbt_env(db_session, workspace_id=workspace.id)
    env.status = "ready"
    db_session.commit()
    return env


@pytest.fixture()
def upstream(db_session, workspace, store) -> TabularDataset:
    from app.services.tabular_datasets import register_frame

    dataset = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Subscribers",
        frame=pl.DataFrame(
            {
                "msisdn": ["A", "B", "C", "D"],
                "arpu": [10.0, 22.5, 31.0, 8.0],
                "churn": [0, 1, 0, 1],
            }
        ),
        source="upload",
    )
    db_session.commit()
    return dataset


# ---------------------------------------------------------------------------
# Project validation
# ---------------------------------------------------------------------------


def test_the_adapter_pin_leads_the_requirements_and_drives_the_fingerprint(monkeypatch):
    monkeypatch.setattr(settings, "tabular_dbt_requirement", "dbt-duckdb==1.9.4")
    assert effective_requirements(None) == "dbt-duckdb==1.9.4"
    assert effective_requirements("dbt-utils\n\n") == "dbt-duckdb==1.9.4\ndbt-utils"

    baseline = env_spec_for().fingerprint
    monkeypatch.setattr(settings, "tabular_dbt_requirement", "dbt-duckdb==1.9.5")
    assert env_spec_for().fingerprint != baseline
    # The dbt env is its own family: it must never collide with a Polars env
    # that happens to declare no extra library.
    from app.services.tabular_polars import env_spec_for as polars_spec

    assert env_spec_for().fingerprint != polars_spec().fingerprint


def test_a_model_tree_is_validated_before_anything_is_queued(monkeypatch):
    from app.services.tabular_datasets import TabularError

    with pytest.raises(TabularError) as exc:
        validate_models([])
    assert exc.value.code == "DBT_MODELS_REQUIRED"

    with pytest.raises(TabularError) as exc:
        validate_models([{"name": "Stg Calls", "sql": "select 1"}])
    assert exc.value.code == "DBT_MODEL_NAME_INVALID"

    with pytest.raises(TabularError) as exc:
        validate_models(
            [{"name": "stg", "sql": "select 1"}, {"name": "stg", "sql": "select 2"}]
        )
    assert exc.value.code == "DBT_MODEL_NAME_DUPLICATE"

    with pytest.raises(TabularError) as exc:
        validate_models([{"name": "stg", "sql": "   "}])
    assert exc.value.code == "DBT_MODEL_EMPTY"

    monkeypatch.setattr(settings, "tabular_dbt_max_models", 1)
    with pytest.raises(TabularError) as exc:
        validate_models(
            [{"name": "a", "sql": "select 1"}, {"name": "b", "sql": "select 2"}]
        )
    assert exc.value.code == "DBT_TOO_MANY_MODELS"

    # A wholly blank row is what an empty editor tab looks like: dropped, not
    # refused, so adding a file then leaving it does not break the run.
    assert validate_models(
        [{"name": "keep", "sql": "select 1"}, {"name": "", "sql": ""}]
    ) == [{"name": "keep", "sql": "select 1"}]


def test_the_published_model_defaults_to_the_last_one_and_must_exist():
    from app.services.tabular_datasets import TabularError

    project = [{"name": "stg", "sql": "select 1"}, {"name": "mart", "sql": "select 2"}]
    assert resolve_output_model(project, None) == "mart"
    assert resolve_output_model(project, "  ") == "mart"
    assert resolve_output_model(project, "stg") == "stg"
    with pytest.raises(TabularError) as exc:
        resolve_output_model(project, "nope")
    assert exc.value.code == "DBT_OUTPUT_MODEL_MISSING"


def test_a_model_may_not_shadow_one_of_the_inputs(
    db_session, workspace, ready_env, upstream
):
    from app.services.tabular_datasets import TabularError

    with pytest.raises(TabularError) as exc:
        submit_dbt_run(
            db_session,
            workspace_id=workspace.id,
            models=[{"name": "input", "sql": "select 1 as a"}],
            declared=[{"view": "input", "dataset_id": upstream.id}],
            persist=False,
        )
    assert exc.value.code == "DBT_MODEL_SHADOWS_SOURCE"


def test_timeout_clamps_to_the_platform_window(monkeypatch):
    monkeypatch.setattr(settings, "tabular_dbt_default_timeout_s", 300.0)
    monkeypatch.setattr(settings, "recipe_execution_max_timeout_s", 600.0)
    assert clamp_timeout(None) == 300.0
    assert clamp_timeout("nope") == 300.0
    assert clamp_timeout(0) == 300.0
    assert clamp_timeout(45) == 45.0
    assert clamp_timeout(10_000) == 600.0


# ---------------------------------------------------------------------------
# Harness contract — needs a real dbt
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def dbt_interpreter() -> Path:
    """A cached venv carrying the pinned adapter, or a skip when offline.

    Cached by requirement digest under the system temp dir so the install is
    paid once per machine rather than once per session.
    """

    requirement = settings.tabular_dbt_requirement
    digest = hashlib.sha256(requirement.encode("utf-8")).hexdigest()[:12]
    root = Path(tempfile.gettempdir()) / f"agentium-dbt-test-venv-{digest}"
    interpreter = root / "bin" / "python"
    marker = root / ".ready"
    if not marker.exists():
        try:
            subprocess.run(
                [sys.executable, "-m", "venv", str(root)],
                check=True,
                capture_output=True,
                timeout=300,
            )
            subprocess.run(
                [str(interpreter), "-m", "pip", "install", "-q", requirement],
                check=True,
                capture_output=True,
                timeout=900,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            pytest.skip(f"no dbt interpreter available ({type(exc).__name__})")
        marker.write_text(requirement, encoding="utf-8")
    return interpreter


def _run_harness(
    interpreter: Path,
    tmp_path: Path,
    models: list[dict[str, str]],
    *,
    tests_yml: str = "",
    output_model: str | None = None,
    row_limit: int | None = None,
):
    tmp_path.mkdir(parents=True, exist_ok=True)
    frame = pl.DataFrame({"msisdn": ["A", "B"], "arpu": [10.0, 20.0]})
    source = tmp_path / "in.parquet"
    frame.write_parquet(source)
    manifest: dict = {
        "models": models,
        "tests_yml": tests_yml,
        "output_model": output_model or models[-1]["name"],
        "sources": {"input": str(source), "subscribers": str(source)},
        "output_path": str(tmp_path / "out.parquet"),
        "threads": 2,
    }
    if row_limit:
        manifest["row_limit"] = row_limit
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    completed = subprocess.run(
        [
            str(interpreter),
            str(harness_path()),
            str(tmp_path / "manifest.json"),
            str(tmp_path / "result.json"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
        env={
            "PATH": f"{interpreter.parent}:/usr/local/bin:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "TMPDIR": str(tmp_path),
            "LANG": "C.UTF-8",
            "PYTHONUNBUFFERED": "1",
            "DO_NOT_TRACK": "1",
        },
    )
    summary = None
    result_file = tmp_path / "result.json"
    if result_file.exists():
        summary = json.loads(result_file.read_text(encoding="utf-8"))
    return completed, summary


def test_the_harness_builds_a_ref_linked_project_and_publishes_one_model(
    dbt_interpreter, tmp_path
):
    completed, summary = _run_harness(
        dbt_interpreter,
        tmp_path,
        [
            {
                "name": "stg_subscribers",
                "sql": "select msisdn, arpu from {{ source('inputs', 'input') }}",
            },
            {
                "name": "mart_value",
                "sql": (
                    "select msisdn, arpu, arpu * 12 as annual "
                    "from {{ ref('stg_subscribers') }}"
                ),
            },
        ],
    )
    assert completed.returncode == 0, completed.stderr
    assert summary["models_total"] == 2
    assert summary["selected"] == "mart_value"
    assert summary["columns"] == ["msisdn", "arpu", "annual"]
    frame = pl.read_parquet(tmp_path / "out.parquet")
    assert frame.columns == ["msisdn", "arpu", "annual"]
    assert frame["annual"].to_list() == [120.0, 240.0]


def test_the_harness_reaches_the_inputs_by_source_and_by_bare_relation(
    dbt_interpreter, tmp_path
):
    """The single-statement node taught authors ``from input``; that habit has
    to keep working here, alongside the dbt-idiomatic ``source()``."""

    completed, summary = _run_harness(
        dbt_interpreter,
        tmp_path,
        [{"name": "both", "sql": "select (select count(*) from input) as bare, "
          "(select count(*) from {{ source('inputs', 'subscribers') }}) as declared"}],
    )
    assert completed.returncode == 0, completed.stderr
    frame = pl.read_parquet(tmp_path / "out.parquet")
    assert frame.row(0) == (2, 2)
    assert summary["tests_total"] == 0


def test_a_failing_data_test_is_its_own_verdict_not_a_generic_error(
    dbt_interpreter, tmp_path
):
    completed, summary = _run_harness(
        dbt_interpreter,
        tmp_path,
        [{"name": "dupes", "sql": "select 1 as k union all select 1 as k"}],
        tests_yml=(
            "version: 2\nmodels:\n  - name: dupes\n    columns:\n"
            "      - name: k\n        tests: [unique]\n"
        ),
    )
    # Exit 2 is what makes "the data is unfit" distinguishable from "the SQL is
    # broken" — the node maps it to DBT_TESTS_FAILED.
    assert completed.returncode == 2, completed.stderr
    assert summary["tests_total"] == 1 and summary["tests_failed"] == 1
    failing = [node for node in summary["nodes"] if node["kind"] == "test"]
    assert failing[0]["name"] == "unique_dupes_k"
    assert failing[0]["failures"] == 1
    # No Parquet: a result its own project declared unfit is never published.
    assert not (tmp_path / "out.parquet").exists()


def test_a_passing_data_test_is_reported_alongside_the_result(
    dbt_interpreter, tmp_path
):
    completed, summary = _run_harness(
        dbt_interpreter,
        tmp_path,
        [{"name": "clean", "sql": "select msisdn from {{ source('inputs', 'input') }}"}],
        tests_yml=(
            "version: 2\nmodels:\n  - name: clean\n    columns:\n"
            "      - name: msisdn\n        tests: [not_null, unique]\n"
        ),
    )
    assert completed.returncode == 0, completed.stderr
    assert summary["tests_total"] == 2 and summary["tests_failed"] == 0
    assert {node["status"] for node in summary["nodes"] if node["kind"] == "test"} == {
        "pass"
    }


def test_the_harness_exit_codes_name_the_author_mistake(dbt_interpreter, tmp_path):
    broken, summary = _run_harness(
        dbt_interpreter,
        tmp_path,
        [{"name": "broken", "sql": "select nope from {{ source('inputs', 'input') }}"}],
    )
    assert broken.returncode == 1
    # The structured node message is what names the column; the stderr tail of a
    # duckdb binder error is just a caret.
    assert "nope" in summary["nodes"][0]["message"]

    bad_ref, _ = _run_harness(
        dbt_interpreter,
        tmp_path / "ref",
        [{"name": "m", "sql": "select * from {{ ref('nowhere') }}"}],
    )
    assert bad_ref.returncode == 1
    assert "nowhere" in bad_ref.stderr

    wrong_output, _ = _run_harness(
        dbt_interpreter,
        tmp_path / "sel",
        [{"name": "m", "sql": "select 1 as a"}],
        output_model="not_a_model",
    )
    assert wrong_output.returncode == 3
    assert "dbt_output_model_missing" in wrong_output.stderr


def test_the_harness_truncates_a_preview_to_the_requested_row_budget(
    dbt_interpreter, tmp_path
):
    completed, summary = _run_harness(
        dbt_interpreter,
        tmp_path,
        [{"name": "m", "sql": "select * from {{ source('inputs', 'input') }}"}],
        row_limit=1,
    )
    assert completed.returncode == 0, completed.stderr
    assert pl.read_parquet(tmp_path / "out.parquet").height == 1
    # The summary still reports the model's real size, so "showing 1 of 2" is
    # sayable in the workshop.
    assert summary["rows"] == 2


# ---------------------------------------------------------------------------
# Worker lifecycle — stubbed harness, real row handling
# ---------------------------------------------------------------------------


def _stub_harness(monkeypatch, *, frame=None, summary=None, exit_code=0):
    """Stand in for the dbt subprocess: write what a real harness would."""

    def fake(argv, **kwargs):
        manifest_path = Path(argv[2])
        result_path = Path(argv[3])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload = {
            "nodes": [],
            "models_total": len(manifest["models"]),
            "tests_total": 0,
            "tests_failed": 0,
            "selected": manifest["output_model"],
            "rows": 0,
            "columns": [],
        }
        payload.update(summary or {})
        result_path.write_text(json.dumps(payload), encoding="utf-8")
        if exit_code == 0:
            (frame if frame is not None else pl.DataFrame({"a": [1]})).write_parquet(
                manifest["output_path"]
            )
        return SupervisedRun(
            status=None,
            error=None,
            exit_code=exit_code,
            stdout_tail="Done. PASS=1",
            stderr_tail="" if exit_code == 0 else "dbt said no",
        )

    monkeypatch.setattr(tabular_dbt, "supervise_harness", fake)


def test_a_preview_run_profiles_the_published_model_without_persisting(
    db_session, workspace, ready_env, upstream, monkeypatch
):
    _stub_harness(
        monkeypatch,
        frame=pl.DataFrame({"msisdn": ["A", "B"], "annual": [120.0, 270.0]}),
        summary={
            "tests_total": 2,
            "tests_failed": 0,
            "nodes": [
                {"kind": "model", "name": "mart", "status": "success", "failures": 0},
                {
                    "kind": "test",
                    "name": "unique_mart_msisdn",
                    "status": "pass",
                    "failures": 0,
                },
            ],
        },
    )
    execution, sources = submit_dbt_run(
        db_session,
        workspace_id=workspace.id,
        models=[{"name": "mart", "sql": "select * from {{ source('inputs','input') }}"}],
        declared=[{"view": "input", "dataset_id": upstream.id}],
        persist=False,
        row_limit=50,
    )
    assert [source.view for source in sources] == ["input"]

    db_session.expire_all()
    row = db_session.query(RecipeExecution).filter_by(id=execution.id).one()
    assert row.status == "succeeded", row.error
    assert row.output_json["kind"] == "dbt_preview"
    assert row.output_json["row_count"] == 2
    assert [column["name"] for column in row.output_json["schema"]] == [
        "msisdn",
        "annual",
    ]
    # The dbt verdict rides along, which is the whole point of the engine.
    assert row.output_json["dbt"]["tests_total"] == 2
    assert row.output_json["dbt"]["tests_failed"] == 0
    assert row.output_json["dbt"]["selected"] == "mart"
    assert (
        db_session.query(TabularDataset)
        .filter(TabularDataset.workspace_id == workspace.id)
        .count()
        == 1
    )


def test_a_persisted_run_registers_a_version_carrying_the_project_lineage(
    db_session, workspace, ready_env, upstream, monkeypatch
):
    _stub_harness(
        monkeypatch,
        frame=pl.DataFrame({"msisdn": ["A"], "score": [0.9]}),
        summary={
            "tests_total": 1,
            "tests_failed": 0,
            "selected": "mart_churn",
            "nodes": [
                {
                    "kind": "test",
                    "name": "not_null_mart_churn_msisdn",
                    "status": "pass",
                    "failures": 0,
                }
            ],
        },
    )
    execution, _ = submit_dbt_run(
        db_session,
        workspace_id=workspace.id,
        models=[
            {"name": "stg_subs", "sql": "select * from {{ source('inputs','input') }}"},
            {"name": "mart_churn", "sql": "select * from {{ ref('stg_subs') }}"},
        ],
        tests_yml="version: 2\n",
        declared=[{"view": "input", "dataset_id": upstream.id}],
        output_name="Churn mart",
        persist=True,
        run_id="run-77",
        node_id="dbt.1",
    )

    db_session.expire_all()
    row = db_session.query(RecipeExecution).filter_by(id=execution.id).one()
    assert row.status == "succeeded", row.error
    assert row.output_json["kind"] == "dbt_transform"

    dataset = (
        db_session.query(TabularDataset)
        .filter_by(id=row.output_json["dataset_id"])
        .one()
    )
    assert dataset.slug == "churn-mart"
    assert dataset.status == "ready"
    assert dataset.parent_ids == [upstream.id]
    assert dataset.run_id == "run-77" and dataset.node_id == "dbt.1"
    assert dataset.produced_by == "dbt_transform_v1"
    lineage = dataset.lineage_json
    assert lineage["engine"] == "dbt-duckdb"
    assert lineage["models"] == ["stg_subs", "mart_churn"]
    assert lineage["output_model"] == "mart_churn"
    assert lineage["tests_total"] == 1 and lineage["tests_failed"] == 0


def test_a_failing_data_test_refuses_to_publish_and_keeps_the_verdict(
    db_session, workspace, ready_env, upstream, monkeypatch
):
    _stub_harness(
        monkeypatch,
        exit_code=2,
        summary={
            "tests_total": 1,
            "tests_failed": 1,
            "selected": "mart",
            "nodes": [
                {
                    "kind": "test",
                    "name": "unique_mart_msisdn",
                    "status": "fail",
                    "failures": 3,
                    "message": "Got 3 results, configured to fail if != 0",
                }
            ],
        },
    )
    execution, _ = submit_dbt_run(
        db_session,
        workspace_id=workspace.id,
        models=[{"name": "mart", "sql": "select * from {{ source('inputs','input') }}"}],
        tests_yml="version: 2\n",
        declared=[{"dataset_id": upstream.id}],
        output_name="Should not exist",
        persist=True,
    )

    db_session.expire_all()
    row = db_session.query(RecipeExecution).filter_by(id=execution.id).one()
    assert row.status == "failed"
    assert row.error.startswith("DBT_TESTS_FAILED")
    assert "unique_mart_msisdn (3 rows)" in row.error
    # The verdict survives the failure: the workshop renders WHICH test refused.
    assert row.output_json["kind"] == "dbt_failed"
    assert row.output_json["dbt"]["tests_failed"] == 1
    # And nothing was published.
    assert (
        db_session.query(TabularDataset)
        .filter(TabularDataset.workspace_id == workspace.id)
        .count()
        == 1
    )


def test_a_build_error_reports_the_node_message_rather_than_the_stderr_tail(
    db_session, workspace, ready_env, upstream, monkeypatch
):
    _stub_harness(
        monkeypatch,
        exit_code=1,
        summary={
            "nodes": [
                {
                    "kind": "model",
                    "name": "broken",
                    "status": "error",
                    "failures": 0,
                    "message": 'Binder Error: Referenced column "nope" not found\n  ^',
                }
            ]
        },
    )
    execution, _ = submit_dbt_run(
        db_session,
        workspace_id=workspace.id,
        models=[{"name": "broken", "sql": "select nope from input"}],
        declared=[{"dataset_id": upstream.id}],
        persist=False,
    )

    db_session.expire_all()
    row = db_session.query(RecipeExecution).filter_by(id=execution.id).one()
    assert row.status == "failed"
    assert row.error.startswith("DBT_BUILD_FAILED")
    assert 'Referenced column "nope" not found' in row.error
    assert "dbt said no" not in row.error


def test_the_engine_gets_its_own_budget_and_no_telemetry(
    db_session, workspace, ready_env, upstream, monkeypatch
):
    monkeypatch.setattr(settings, "tabular_dbt_memory_limit_mb", 3072)
    seen: dict = {}
    _stub_harness(monkeypatch)
    stub = tabular_dbt.supervise_harness

    def capture(argv, **kwargs):
        seen.update(kwargs)
        return stub(argv, **kwargs)

    monkeypatch.setattr(tabular_dbt, "supervise_harness", capture)
    submit_dbt_run(
        db_session,
        workspace_id=workspace.id,
        models=[{"name": "m", "sql": "select 1 as a"}],
        declared=[{"dataset_id": upstream.id}],
        persist=False,
    )

    assert seen["memory_limit_mb"] == 3072
    # dbt phones home by default; a node running author SQL must not.
    assert seen["extra_env"]["DO_NOT_TRACK"] == "1"


def test_an_unwired_node_refuses_synchronously_rather_than_queueing(
    db_session, workspace, ready_env
):
    from app.services.tabular_datasets import TabularError

    with pytest.raises(TabularError) as exc:
        submit_dbt_run(
            db_session,
            workspace_id=workspace.id,
            models=[{"name": "m", "sql": "select 1 as a"}],
            persist=False,
        )
    assert exc.value.code == "TRANSFORM_NO_INPUT"


def test_the_plane_fails_closed_while_managed_environments_are_disabled(
    db_session, workspace, ready_env, upstream, monkeypatch
):
    from app.services.tabular_datasets import TabularError

    monkeypatch.setattr(settings, "recipe_execution_enabled", False)
    with pytest.raises(TabularError) as exc:
        submit_dbt_run(
            db_session,
            workspace_id=workspace.id,
            models=[{"name": "m", "sql": "select 1 as a"}],
            declared=[{"dataset_id": upstream.id}],
            persist=False,
        )
    assert exc.value.code == "DBT_EXECUTION_DISABLED"


def test_a_redelivered_task_that_finds_the_row_running_fails_closed(
    db_session, workspace, ready_env, upstream
):
    from app.services.tabular_dbt import create_dbt_execution
    from app.services.tabular_transforms import resolve_sources

    sources = resolve_sources(
        db_session, workspace_id=workspace.id, declared=[{"dataset_id": upstream.id}]
    )
    execution = create_dbt_execution(
        db_session,
        workspace_id=workspace.id,
        models=[{"name": "m", "sql": "select 1 as a"}],
        tests_yml="",
        output_model="m",
        sources=sources,
        persist=False,
    )
    execution.status = "running"
    db_session.commit()

    assert run_dbt_execution(execution.id)["status"] == "failed"
    db_session.expire_all()
    row = db_session.query(RecipeExecution).filter_by(id=execution.id).one()
    assert row.error == "dbt_worker_lost_after_claim"


# ---------------------------------------------------------------------------
# Node wrapper + DAG contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_wrapper_refuses_a_payload_without_graph_configuration():
    from app.services.skills_registry.wrappers import _dbt_transform_v1

    with pytest.raises(ValueError, match="transform_config_missing"):
        await _dbt_transform_v1({"dataset_id": "x"}, {"workspace_id": "w"})


@pytest.mark.asyncio
async def test_the_wrapper_requires_a_workspace_scope():
    from app.services.skills_registry.wrappers import _dbt_transform_v1

    with pytest.raises(ValueError, match="transform_workspace_required"):
        await _dbt_transform_v1({"_transform": {"models": []}}, {})


@pytest.mark.asyncio
async def test_the_wrapper_settles_a_build_and_returns_a_dataset_envelope(
    db_session, workspace, ready_env, upstream, monkeypatch
):
    from app.services.skills_registry.wrappers import _dbt_transform_v1

    _stub_harness(
        monkeypatch,
        frame=pl.DataFrame({"churn": [0, 1], "n": [2, 2]}),
        summary={"selected": "mart_churn", "tests_total": 1, "tests_failed": 0},
    )
    result = await _dbt_transform_v1(
        {
            "_transform": {
                "models": [
                    {
                        "name": "mart_churn",
                        "sql": "select churn, count(*) as n from input group by 1",
                    }
                ],
                "tests_yml": "version: 2\n",
                "output_model": "mart_churn",
                "output_name": "Churn split",
                "sources": [{"view": "input", "dataset_id": upstream.id}],
                "node_id": "dbt.node",
            }
        },
        {"workspace_id": workspace.id, "run_id": "run-9"},
    )

    assert result["rows"] == 2 and result["columns"] == 2
    assert result["slug"] == "churn-split"
    assert result["dbt"]["selected"] == "mart_churn"
    assert "preview" not in result
    dataset = db_session.query(TabularDataset).filter_by(id=result["dataset_id"]).one()
    assert dataset.run_id == "run-9" and dataset.node_id == "dbt.node"


@pytest.mark.asyncio
async def test_a_failed_data_test_fails_the_node_so_nothing_flows_downstream(
    db_session, workspace, ready_env, upstream, monkeypatch
):
    from app.services.skills_registry.wrappers import _dbt_transform_v1

    _stub_harness(
        monkeypatch,
        exit_code=2,
        summary={
            "tests_total": 1,
            "tests_failed": 1,
            "nodes": [
                {
                    "kind": "test",
                    "name": "not_null_mart_msisdn",
                    "status": "fail",
                    "failures": 7,
                }
            ],
        },
    )
    with pytest.raises(RuntimeError, match="DBT_TESTS_FAILED"):
        await _dbt_transform_v1(
            {
                "_transform": {
                    "models": [{"name": "mart", "sql": "select * from input"}],
                    "tests_yml": "version: 2\n",
                    "output_name": "unfit",
                    "sources": [{"dataset_id": upstream.id}],
                }
            },
            {"workspace_id": workspace.id},
        )


def test_the_dag_projects_the_project_and_its_tests_as_graph_configuration():
    from app.services.run_engine.dag import DagNode, _apply_transform_node_config

    node = DagNode(
        id="dbt.1",
        type="task",
        kind="task",
        label="dbt",
        config={
            "skill_slug": "dbt_transform_v1",
            "params": {
                "models": [{"name": "mart", "sql": "select 1 as a"}],
                "tests_yml": "version: 2\n",
                "output_model": "mart",
                "timeout_s": 120,
                "output_name": "Mart",
            },
        },
        skill_slug="dbt_transform_v1",
        data={},
    )
    node_input = {
        "dataset_id": "abc",
        # A hostile payload trying to swap the project and its gate.
        "models": [{"name": "evil", "sql": "select 'pwned'"}],
        "tests_yml": "",
        "output_model": "evil",
        "_transform": {"models": []},
    }

    _apply_transform_node_config(node, node_input)

    transform = node_input["_transform"]
    assert transform["models"] == [{"name": "mart", "sql": "select 1 as a"}]
    assert transform["tests_yml"] == "version: 2\n"
    assert transform["output_model"] == "mart"
    assert transform["timeout_s"] == 120
    assert transform["node_id"] == "dbt.1"
    assert "models" not in node_input and "tests_yml" not in node_input
    assert node_input["dataset_id"] == "abc"


def test_the_skill_is_registered_bound_and_claimed_by_a_universal_capability():
    from app.services.skills_registry import wrappers
    from app.services.skills_registry.seed import (
        SEED_CAPABILITIES,
        SEED_SKILLS,
        skill_category,
    )

    assert wrappers.runtime_status("dbt_transform_v1") == "bound"
    assert any(entry["slug"] == "dbt_transform_v1" for entry in SEED_SKILLS)
    assert skill_category("dbt_transform_v1") == "Analysis"
    carriers = [
        entry
        for entry in SEED_CAPABILITIES
        if "dbt_transform_v1" in entry.get("skill_slugs", ())
    ]
    assert any(entry.get("tier") == "universal" for entry in carriers), (
        "an unclaimed skill is filtered from every workspace catalog, which "
        "would grey the palette row and block System binding"
    )
