"""The Polars transform node: harness contract, worker lifecycle, DAG contract.

The venv is faked, never built: a real `polars` install in a throwaway venv
would put a network fetch in the unit suite. Pointing `env_python` at the test
interpreter — which already has polars — exercises the SAME supervised
subprocess path with the same harness, which is the part worth testing.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.recipe import PythonEnv, RecipeExecution
from app.models.tabular import TabularDataset
from app.models.workspace import Workspace
from app.services import recipe_executions, tabular_polars
from app.services.tabular_polars import (
    clamp_timeout,
    effective_requirements,
    env_spec_for,
    harness_path,
    run_polars_execution,
    submit_polars_run,
    validate_code,
)

pl = pytest.importorskip("polars")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def workspace(db_session) -> Workspace:
    ws = Workspace(
        id=str(uuid4()),
        name="Polars node",
        slug=f"polars-node-{uuid4().hex[:8]}",
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
    # The harness runs on THIS interpreter, which already carries polars.
    interpreter = Path(sys.executable)
    monkeypatch.setattr(
        tabular_polars, "env_python", lambda workspace_id, fingerprint: interpreter
    )
    monkeypatch.setattr(
        recipe_executions, "env_python", lambda workspace_id, fingerprint: interpreter
    )


@pytest.fixture()
def ready_env(db_session, workspace, enabled) -> PythonEnv:
    """The node's env row, flipped ready without paying for a real build."""

    env = tabular_polars.resolve_polars_env(db_session, workspace_id=workspace.id)
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
# Environment identity
# ---------------------------------------------------------------------------


def test_the_engine_pin_leads_the_requirements_and_drives_the_fingerprint(monkeypatch):
    monkeypatch.setattr(settings, "tabular_polars_requirement", "polars==1.44.0")
    assert effective_requirements(None) == "polars==1.44.0"
    assert effective_requirements("scikit-learn==1.5.0\n\n") == (
        "polars==1.44.0\nscikit-learn==1.5.0"
    )

    baseline = env_spec_for().fingerprint
    # A platform upgrade of the engine must produce a NEW env, or the author's
    # code would run against a frame format it was never tested on.
    monkeypatch.setattr(settings, "tabular_polars_requirement", "polars==1.45.0")
    assert env_spec_for().fingerprint != baseline
    # An extra author library is a new env too; nodes that declare none share one.
    assert env_spec_for(requirements_text="httpx").fingerprint != env_spec_for().fingerprint


def test_validate_code_and_timeout_refusals(monkeypatch):
    from app.services.tabular_datasets import TabularError

    with pytest.raises(TabularError) as exc:
        validate_code("   ")
    assert exc.value.code == "POLARS_CODE_REQUIRED"
    monkeypatch.setattr(settings, "recipe_execution_max_code_bytes", 8)
    with pytest.raises(TabularError) as exc:
        validate_code("x" * 9)
    assert exc.value.code == "POLARS_CODE_TOO_LARGE"

    monkeypatch.setattr(settings, "tabular_polars_default_timeout_s", 180.0)
    monkeypatch.setattr(settings, "recipe_execution_max_timeout_s", 600.0)
    assert clamp_timeout(None) == 180.0
    assert clamp_timeout("nope") == 180.0
    assert clamp_timeout(0) == 180.0
    assert clamp_timeout(30) == 30.0
    assert clamp_timeout(10_000) == 600.0


# ---------------------------------------------------------------------------
# Harness contract (direct subprocess, no venv needed)
# ---------------------------------------------------------------------------


def _run_harness(tmp_path: Path, code: str, *, row_limit: int | None = None):
    frame = pl.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    source = tmp_path / "in.parquet"
    frame.write_parquet(source)
    script = tmp_path / "transform.py"
    script.write_text(code, encoding="utf-8")
    manifest: dict = {
        "inputs": {"input": str(source), "subscribers": str(source)},
        "output_path": str(tmp_path / "out.parquet"),
    }
    if row_limit:
        manifest["row_limit"] = row_limit
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(harness_path()),
            str(script),
            str(tmp_path / "manifest.json"),
            str(tmp_path / "result.json"),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return completed


def test_harness_roundtrip_writes_the_result_frame_and_its_summary(tmp_path):
    result = _run_harness(
        tmp_path,
        "def transform(inputs):\n"
        "    return inputs['input'].select('a').with_columns(double=2 * __import__('polars').col('a'))\n",
    )
    assert result.returncode == 0, result.stderr
    frame = pl.read_parquet(tmp_path / "out.parquet")
    assert frame.columns == ["a", "double"]
    summary = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert summary == {"rows": 3, "columns": 2, "names": ["a", "double"]}


def test_harness_names_every_source_the_author_can_address(tmp_path):
    result = _run_harness(
        tmp_path,
        "def transform(inputs):\n"
        "    assert set(inputs) == {'input', 'subscribers'}\n"
        "    return inputs['subscribers']\n",
    )
    assert result.returncode == 0, result.stderr


def test_harness_accepts_the_natural_return_shapes(tmp_path):
    for code in (
        "def transform(inputs):\n    return inputs['input'].lazy().select('a')\n",
        "def transform(inputs):\n    return {'a': [1, 2]}\n",
        "def transform(inputs):\n    return [{'a': 1}, {'a': 2}]\n",
        "import polars as pl\ndef transform(inputs):\n    return pl.Series('a', [1])\n",
    ):
        assert _run_harness(tmp_path, code).returncode == 0, code


def test_harness_exit_codes_name_the_author_mistake(tmp_path):
    raised = _run_harness(
        tmp_path, "def transform(inputs):\n    raise ValueError('boom')\n"
    )
    assert raised.returncode == 1
    assert "ValueError: boom" in raised.stderr

    missing = _run_harness(tmp_path, "x = 1\n")
    assert missing.returncode == 3
    assert "polars_transform_missing" in missing.stderr

    not_tabular = _run_harness(tmp_path, "def transform(inputs):\n    return 42\n")
    assert not_tabular.returncode == 4
    assert "polars_result_not_tabular" in not_tabular.stderr

    import_error = _run_harness(tmp_path, "import nope_not_installed\n")
    assert import_error.returncode == 1


def test_harness_truncates_a_preview_to_the_requested_row_budget(tmp_path):
    result = _run_harness(
        tmp_path, "def transform(inputs):\n    return inputs['input']\n", row_limit=2
    )
    assert result.returncode == 0, result.stderr
    assert pl.read_parquet(tmp_path / "out.parquet").height == 2


# ---------------------------------------------------------------------------
# Worker lifecycle
# ---------------------------------------------------------------------------


def test_a_preview_run_profiles_the_frame_without_persisting_a_dataset(
    db_session, workspace, ready_env, upstream
):
    execution, sources = submit_polars_run(
        db_session,
        workspace_id=workspace.id,
        code=(
            "import polars as pl\n"
            "def transform(inputs):\n"
            "    return inputs['input'].filter(pl.col('churn') == 1)\n"
        ),
        declared=[{"view": "input", "dataset_id": upstream.id}],
        persist=False,
        row_limit=50,
    )
    assert [source.view for source in sources] == ["input"]

    db_session.expire_all()
    row = db_session.query(RecipeExecution).filter_by(id=execution.id).one()
    assert row.status == "succeeded", row.error
    assert row.output_json["kind"] == "polars_preview"
    assert row.output_json["row_count"] == 2
    assert [column["name"] for column in row.output_json["schema"]] == [
        "msisdn",
        "arpu",
        "churn",
    ]
    assert row.output_json["preview"][0]["churn"] == 1
    # A preview is a dry run: the only dataset in the workspace is the input.
    assert (
        db_session.query(TabularDataset)
        .filter(TabularDataset.workspace_id == workspace.id)
        .count()
        == 1
    )


def test_a_persisted_run_registers_a_new_version_with_its_lineage(
    db_session, workspace, ready_env, upstream
):
    execution, _ = submit_polars_run(
        db_session,
        workspace_id=workspace.id,
        code=(
            "import polars as pl\n"
            "def transform(inputs):\n"
            "    frame = inputs['input']\n"
            "    return frame.with_columns(high_value=pl.col('arpu') > 20)\n"
        ),
        declared=[{"view": "input", "dataset_id": upstream.id}],
        output_name="Churn features",
        persist=True,
        run_id="run-42",
        node_id="polars.1",
    )

    db_session.expire_all()
    row = db_session.query(RecipeExecution).filter_by(id=execution.id).one()
    assert row.status == "succeeded", row.error
    assert row.output_json["kind"] == "polars_transform"
    assert row.output_json["rows"] == 4 and row.output_json["columns"] == 4

    dataset = (
        db_session.query(TabularDataset)
        .filter_by(id=row.output_json["dataset_id"])
        .one()
    )
    assert dataset.slug == "churn-features"
    assert dataset.status == "ready"
    assert dataset.parent_ids == [upstream.id]
    assert dataset.run_id == "run-42" and dataset.node_id == "polars.1"
    assert dataset.lineage_json["engine"] == "polars"
    assert dataset.produced_by == "polars_transform_v1"


def test_a_script_that_raises_fails_the_row_with_a_coded_reason(
    db_session, workspace, ready_env, upstream
):
    execution, _ = submit_polars_run(
        db_session,
        workspace_id=workspace.id,
        code="def transform(inputs):\n    raise RuntimeError('no such column')\n",
        declared=[{"dataset_id": upstream.id}],
        persist=False,
    )

    db_session.expire_all()
    row = db_session.query(RecipeExecution).filter_by(id=execution.id).one()
    assert row.status == "failed"
    assert row.error.startswith("POLARS_SCRIPT_RAISED")
    assert "no such column" in row.error
    assert "RuntimeError" in (row.stderr_tail or "")


def test_a_missing_transform_function_is_named_as_such(
    db_session, workspace, ready_env, upstream
):
    execution, _ = submit_polars_run(
        db_session,
        workspace_id=workspace.id,
        code="frame = 1\n",
        declared=[{"dataset_id": upstream.id}],
        persist=False,
    )
    db_session.expire_all()
    row = db_session.query(RecipeExecution).filter_by(id=execution.id).one()
    assert row.status == "failed"
    assert row.error.startswith("POLARS_TRANSFORM_MISSING")


def test_the_engine_gets_a_wider_address_space_and_a_bounded_thread_count(
    db_session, workspace, ready_env, upstream, monkeypatch
):
    """RLIMIT_AS caps VIRTUAL memory: at the plain-script budget polars cannot
    even spawn its allocator's background threads, so the engine needs its own
    ceiling — and a thread cap, so one node cannot take the worker's cores."""

    monkeypatch.setattr(settings, "tabular_polars_memory_limit_mb", 3072)
    monkeypatch.setattr(settings, "tabular_polars_max_threads", 2)
    seen: dict = {}
    original = tabular_polars.supervise_harness

    def capture(argv, **kwargs):
        seen.update(kwargs)
        return original(argv, **kwargs)

    monkeypatch.setattr(tabular_polars, "supervise_harness", capture)
    execution, _ = submit_polars_run(
        db_session,
        workspace_id=workspace.id,
        code="def transform(inputs):\n    return inputs['input']\n",
        declared=[{"dataset_id": upstream.id}],
        persist=False,
    )

    assert seen["memory_limit_mb"] == 3072
    assert seen["extra_env"]["POLARS_MAX_THREADS"] == "2"
    db_session.expire_all()
    row = db_session.query(RecipeExecution).filter_by(id=execution.id).one()
    assert row.status == "succeeded", row.error


def test_an_unwired_node_refuses_synchronously_rather_than_queueing(
    db_session, workspace, ready_env
):
    from app.services.tabular_datasets import TabularError

    with pytest.raises(TabularError) as exc:
        submit_polars_run(
            db_session,
            workspace_id=workspace.id,
            code="def transform(inputs):\n    return inputs['input']\n",
            persist=False,
        )
    assert exc.value.code == "TRANSFORM_NO_INPUT"


def test_the_plane_fails_closed_while_managed_environments_are_disabled(
    db_session, workspace, ready_env, upstream, monkeypatch
):
    from app.services.tabular_datasets import TabularError

    monkeypatch.setattr(settings, "recipe_execution_enabled", False)
    with pytest.raises(TabularError) as exc:
        submit_polars_run(
            db_session,
            workspace_id=workspace.id,
            code="def transform(inputs):\n    return inputs['input']\n",
            declared=[{"dataset_id": upstream.id}],
            persist=False,
        )
    assert exc.value.code == "POLARS_EXECUTION_DISABLED"


def test_a_redelivered_task_that_finds_the_row_running_fails_closed(
    db_session, workspace, ready_env, upstream
):
    from app.services.tabular_polars import create_polars_execution
    from app.services.tabular_transforms import resolve_sources

    sources = resolve_sources(
        db_session, workspace_id=workspace.id, declared=[{"dataset_id": upstream.id}]
    )
    execution = create_polars_execution(
        db_session,
        workspace_id=workspace.id,
        code="def transform(inputs):\n    return inputs['input']\n",
        sources=sources,
        persist=False,
    )
    execution.status = "running"
    db_session.commit()

    assert run_polars_execution(execution.id, "def transform(i):\n    return i")[
        "status"
    ] == "failed"
    db_session.expire_all()
    row = db_session.query(RecipeExecution).filter_by(id=execution.id).one()
    assert row.error == "polars_worker_lost_after_claim"


# ---------------------------------------------------------------------------
# Node wrapper + DAG contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_wrapper_refuses_a_payload_without_graph_configuration():
    from app.services.skills_registry.wrappers import _polars_transform_v1

    with pytest.raises(ValueError, match="transform_config_missing"):
        await _polars_transform_v1({"dataset_id": "x"}, {"workspace_id": "w"})


@pytest.mark.asyncio
async def test_the_wrapper_requires_a_workspace_scope():
    from app.services.skills_registry.wrappers import _polars_transform_v1

    with pytest.raises(ValueError, match="transform_workspace_required"):
        await _polars_transform_v1({"_transform": {"code": "x"}}, {})


@pytest.mark.asyncio
async def test_the_wrapper_settles_a_transform_and_returns_a_dataset_envelope(
    db_session, workspace, ready_env, upstream
):
    from app.services.skills_registry.wrappers import _polars_transform_v1

    result = await _polars_transform_v1(
        {
            "_transform": {
                "code": (
                    "import polars as pl\n"
                    "def transform(inputs):\n"
                    "    return inputs['input'].group_by('churn').len()\n"
                ),
                "output_name": "Churn split",
                "sources": [{"view": "input", "dataset_id": upstream.id}],
                "node_id": "polars.node",
            }
        },
        {"workspace_id": workspace.id, "run_id": "run-9"},
    )

    assert result["rows"] == 2 and result["columns"] == 2
    assert result["slug"] == "churn-split"
    # The envelope is a reference, not the data: downstream nodes resolve the id.
    assert "preview" not in result
    dataset = (
        db_session.query(TabularDataset).filter_by(id=result["dataset_id"]).one()
    )
    assert dataset.run_id == "run-9" and dataset.node_id == "polars.node"


@pytest.mark.asyncio
async def test_a_failing_script_fails_the_node_with_the_authors_own_message(
    db_session, workspace, ready_env, upstream
):
    from app.services.skills_registry.wrappers import _polars_transform_v1

    with pytest.raises(RuntimeError, match="POLARS_SCRIPT_RAISED"):
        await _polars_transform_v1(
            {
                "_transform": {
                    "code": "def transform(inputs):\n    raise KeyError('arpu_v2')\n",
                    "output_name": "boom",
                    "sources": [{"dataset_id": upstream.id}],
                }
            },
            {"workspace_id": workspace.id},
        )


def test_the_dag_projects_the_script_and_its_environment_as_graph_configuration():
    from app.services.run_engine.dag import DagNode, _apply_transform_node_config

    node = DagNode(
        id="polars.1",
        type="task",
        kind="task",
        label="Polars",
        config={
            "skill_slug": "polars_transform_v1",
            "params": {
                "code": "def transform(inputs):\n    return inputs['input']\n",
                "requirements_text": "scikit-learn==1.5.0",
                "timeout_s": 45,
                "output_name": "Features",
            },
        },
        skill_slug="polars_transform_v1",
        data={},
    )
    node_input = {
        "dataset_id": "abc",
        # A hostile payload trying to swap the script and its libraries.
        "code": "def transform(i):\n    return {'hacked': [1]}\n",
        "requirements_text": "evil",
        "_transform": {"code": "evil"},
    }

    _apply_transform_node_config(node, node_input)

    transform = node_input["_transform"]
    assert transform["code"].startswith("def transform(inputs):")
    assert transform["requirements_text"] == "scikit-learn==1.5.0"
    assert transform["timeout_s"] == 45
    assert transform["output_name"] == "Features"
    assert transform["node_id"] == "polars.1"
    assert "code" not in node_input and "requirements_text" not in node_input
    assert node_input["dataset_id"] == "abc"


def test_the_skill_is_registered_bound_and_claimed_by_a_universal_capability():
    from app.services.skills_registry import wrappers
    from app.services.skills_registry.seed import SEED_CAPABILITIES, SEED_SKILLS

    assert wrappers.runtime_status("polars_transform_v1") == "bound"
    assert any(entry["slug"] == "polars_transform_v1" for entry in SEED_SKILLS)
    carriers = [
        entry
        for entry in SEED_CAPABILITIES
        if "polars_transform_v1" in entry.get("skill_slugs", ())
    ]
    assert any(entry.get("tier") == "universal" for entry in carriers), (
        "an unclaimed skill is filtered from every workspace catalog, which "
        "would grey the palette row and block System binding"
    )
