"""Recipe executions: harness contract, statuses, timeout, cancel, wrapper."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.recipe import RecipeExecution
from app.models.workspace import Workspace
from app.services import recipe_executions
from app.services.recipe_envs import RecipeError, build_env, build_env_spec, resolve_env
from app.services.recipe_executions import (
    clamp_timeout,
    create_execution,
    request_cancel,
    run_recipe_execution,
    serialize_execution,
    validate_code,
)


@pytest.fixture()
def workspace(db_session) -> Workspace:
    ws = Workspace(
        id=str(uuid4()),
        name="Recipes",
        slug=f"recipes-{uuid4().hex[:8]}",
        settings={},
    )
    db_session.add(ws)
    db_session.commit()
    return ws


@pytest.fixture()
def enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "recipe_execution_enabled", True)
    monkeypatch.setattr(settings, "recipe_envs_path", str(tmp_path / "envs"))


@pytest.fixture()
def ready_env(db_session, workspace, enabled):
    """One real, empty venv shared by the execution tests of this module."""

    env = resolve_env(db_session, workspace_id=workspace.id, spec=build_env_spec())
    db_session.commit()
    built = build_env(db_session, env.id)
    assert built.status == "ready"
    return built


def _execution(db_session, workspace, env, code: str, *, timeout_s: float = 30.0):
    execution = create_execution(
        db_session,
        workspace_id=workspace.id,
        env=env,
        code=code,
        inputs={"n": 21},
        timeout_s=timeout_s,
    )
    db_session.commit()
    return execution


# ---------------------------------------------------------------------------
# validation helpers
# ---------------------------------------------------------------------------


def test_clamp_timeout_defaults_and_caps(monkeypatch):
    monkeypatch.setattr(settings, "recipe_execution_default_timeout_s", 120.0)
    monkeypatch.setattr(settings, "recipe_execution_max_timeout_s", 600.0)
    assert clamp_timeout(None) == 120.0
    assert clamp_timeout("nope") == 120.0
    assert clamp_timeout(-5) == 120.0
    assert clamp_timeout(30) == 30.0
    assert clamp_timeout(10_000) == 600.0


def test_validate_code_rejects_empty_and_oversized(monkeypatch):
    with pytest.raises(RecipeError) as exc:
        validate_code("   ")
    assert exc.value.code == "RECIPE_CODE_REQUIRED"
    monkeypatch.setattr(settings, "recipe_execution_max_code_bytes", 10)
    with pytest.raises(RecipeError) as exc:
        validate_code("x" * 11)
    assert exc.value.code == "RECIPE_CODE_TOO_LARGE"


# ---------------------------------------------------------------------------
# harness contract (direct subprocess, no venv needed)
# ---------------------------------------------------------------------------


def _run_harness(tmp_path, code: str, inputs) -> subprocess.CompletedProcess:
    script = tmp_path / "recipe.py"
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    script.write_text(code, encoding="utf-8")
    input_path.write_text(json.dumps(inputs), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(recipe_executions.harness_path()),
            str(script),
            str(input_path),
            str(output_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_harness_success_roundtrip(tmp_path):
    result = _run_harness(
        tmp_path,
        "def main(inputs):\n    return {'double': inputs['n'] * 2}\n",
        {"n": 21},
    )
    assert result.returncode == 0
    output = json.loads((tmp_path / "output.json").read_text(encoding="utf-8"))
    assert output == {"double": 42}


def test_harness_exit_codes(tmp_path):
    # Script raises → 1 with the traceback on stderr.
    result = _run_harness(tmp_path, "def main(inputs):\n    raise ValueError('boom')\n", {})
    assert result.returncode == 1
    assert "ValueError: boom" in result.stderr
    # main() missing → 3.
    result = _run_harness(tmp_path, "x = 1\n", {})
    assert result.returncode == 3
    assert "recipe_main_missing" in result.stderr
    # Non-dict return → 4.
    result = _run_harness(tmp_path, "def main(inputs):\n    return [1]\n", {})
    assert result.returncode == 4
    # Unserializable return → 5.
    result = _run_harness(
        tmp_path, "def main(inputs):\n    return {'f': lambda: 1}\n", {}
    )
    assert result.returncode == 5
    # None counts as an empty object.
    result = _run_harness(tmp_path, "def main(inputs):\n    return None\n", {})
    assert result.returncode == 0
    assert json.loads((tmp_path / "output.json").read_text(encoding="utf-8")) == {}


# ---------------------------------------------------------------------------
# run_recipe_execution — end to end on a real (empty) venv
# ---------------------------------------------------------------------------


def test_run_recipe_execution_succeeds(db_session, workspace, ready_env):
    code = (
        "import sys\n"
        "def main(inputs):\n"
        "    print('working on', inputs['n'])\n"
        "    print('warned', file=sys.stderr)\n"
        "    return {'double': inputs['n'] * 2}\n"
    )
    execution = _execution(db_session, workspace, ready_env, code)
    result = run_recipe_execution(execution.id, code)
    assert result["status"] == "succeeded"

    db_session.expire_all()
    row = db_session.query(RecipeExecution).filter_by(id=execution.id).one()
    assert row.status == "succeeded"
    assert row.output_json == {"double": 42}
    assert row.exit_code == 0
    assert "working on 21" in (row.stdout_tail or "")
    assert "warned" in (row.stderr_tail or "")
    assert row.duration_ms is not None and row.duration_ms > 0
    assert row.started_at is not None and row.finished_at is not None
    # Usage accounting feeds the LRU governor.
    db_session.refresh(ready_env)
    assert ready_env.use_count == 1
    assert ready_env.last_used_at is not None


def test_run_recipe_execution_script_error(db_session, workspace, ready_env):
    code = "def main(inputs):\n    raise RuntimeError('bad input')\n"
    execution = _execution(db_session, workspace, ready_env, code)
    result = run_recipe_execution(execution.id, code)
    assert result["status"] == "failed"

    db_session.expire_all()
    row = db_session.query(RecipeExecution).filter_by(id=execution.id).one()
    assert row.status == "failed"
    assert row.exit_code == 1
    assert "RuntimeError: bad input" in (row.stderr_tail or "")
    assert (row.error or "").startswith("recipe_exit_1")


def test_run_recipe_execution_times_out(db_session, workspace, ready_env):
    code = "import time\ndef main(inputs):\n    time.sleep(30)\n    return {}\n"
    execution = _execution(db_session, workspace, ready_env, code, timeout_s=1.0)
    started = time.monotonic()
    result = run_recipe_execution(execution.id, code)
    elapsed = time.monotonic() - started
    assert result["status"] == "timed_out"
    assert elapsed < 15  # killed promptly, not after the script's 30 s sleep

    db_session.expire_all()
    row = db_session.query(RecipeExecution).filter_by(id=execution.id).one()
    assert row.status == "timed_out"
    assert (row.error or "").startswith("recipe_timeout_after_1")


def test_run_recipe_execution_cooperative_cancel(
    db_session, workspace, ready_env, monkeypatch
):
    """The supervision loop kills the process group once the flag flips."""

    calls = {"count": 0}

    def flag_flips_on_second_check(db, execution_id):
        calls["count"] += 1
        return calls["count"] >= 2

    monkeypatch.setattr(
        recipe_executions, "_cancel_requested", flag_flips_on_second_check
    )
    code = "import time\ndef main(inputs):\n    time.sleep(30)\n    return {}\n"
    execution = _execution(db_session, workspace, ready_env, code, timeout_s=60.0)
    started = time.monotonic()
    result = run_recipe_execution(execution.id, code)
    elapsed = time.monotonic() - started
    assert result["status"] == "cancelled"
    assert elapsed < 15

    db_session.expire_all()
    row = db_session.query(RecipeExecution).filter_by(id=execution.id).one()
    assert row.status == "cancelled"
    assert row.error == "cancel_requested"


def test_run_recipe_execution_pre_start_cancel(db_session, workspace, ready_env):
    code = "def main(inputs):\n    return {}\n"
    execution = _execution(db_session, workspace, ready_env, code)
    execution.cancel_requested = True
    db_session.commit()
    result = run_recipe_execution(execution.id, code)
    assert result["status"] == "cancelled"


def test_run_recipe_execution_disabled_flag_fails_closed(
    db_session, workspace, ready_env, monkeypatch
):
    code = "def main(inputs):\n    return {}\n"
    execution = _execution(db_session, workspace, ready_env, code)
    monkeypatch.setattr(settings, "recipe_execution_enabled", False)
    result = run_recipe_execution(execution.id, code)
    assert result["status"] == "failed"
    db_session.expire_all()
    row = db_session.query(RecipeExecution).filter_by(id=execution.id).one()
    assert row.error == "recipe_execution_disabled"


def test_run_recipe_execution_redelivery_guard(db_session, workspace, ready_env):
    """A redelivered task that finds the row `running` fails closed."""

    code = "def main(inputs):\n    return {}\n"
    execution = _execution(db_session, workspace, ready_env, code)
    execution.status = "running"
    db_session.commit()
    result = run_recipe_execution(execution.id, code)
    assert result["status"] == "failed"
    db_session.expire_all()
    row = db_session.query(RecipeExecution).filter_by(id=execution.id).one()
    assert row.error == "recipe_worker_lost_after_claim"


def test_run_recipe_execution_terminal_row_is_idempotent(
    db_session, workspace, ready_env
):
    code = "def main(inputs):\n    return {}\n"
    execution = _execution(db_session, workspace, ready_env, code)
    execution.status = "succeeded"
    execution.output_json = {"kept": True}
    db_session.commit()
    result = run_recipe_execution(execution.id, code)
    assert result["status"] == "succeeded"
    db_session.expire_all()
    row = db_session.query(RecipeExecution).filter_by(id=execution.id).one()
    assert row.output_json == {"kept": True}


def test_run_recipe_execution_output_too_large(db_session, workspace, ready_env, monkeypatch):
    monkeypatch.setattr(settings, "recipe_execution_output_max_bytes", 64)
    code = "def main(inputs):\n    return {'blob': 'x' * 10_000}\n"
    execution = _execution(db_session, workspace, ready_env, code)
    result = run_recipe_execution(execution.id, code)
    assert result["status"] == "failed"
    db_session.expire_all()
    row = db_session.query(RecipeExecution).filter_by(id=execution.id).one()
    assert row.error == "recipe_output_too_large"


def test_run_recipe_execution_builds_pending_env(db_session, workspace, enabled):
    """A pending env is built on first use (status walks through env_building)."""

    env = resolve_env(db_session, workspace_id=workspace.id, spec=build_env_spec())
    db_session.commit()
    assert env.status == "pending"
    code = "def main(inputs):\n    return {'ok': True}\n"
    execution = _execution(db_session, workspace, env, code)
    result = run_recipe_execution(execution.id, code)
    assert result["status"] == "succeeded"
    db_session.expire_all()
    db_session.refresh(env)
    assert env.status == "ready"


def test_request_cancel_queued_execution_settles_immediately(
    db_session, workspace, ready_env
):
    code = "def main(inputs):\n    return {}\n"
    execution = _execution(db_session, workspace, ready_env, code)
    assert execution.status == "queued"
    request_cancel(db_session, execution)
    assert execution.status == "cancelled"
    assert execution.cancel_requested is True
    # Terminal rows are left untouched by a second cancel.
    request_cancel(db_session, execution)
    assert execution.status == "cancelled"


def test_serialize_execution_shape(db_session, workspace, ready_env):
    code = "def main(inputs):\n    return {}\n"
    execution = _execution(db_session, workspace, ready_env, code)
    payload = serialize_execution(execution)
    assert payload["id"] == execution.id
    assert payload["status"] == "queued"
    assert payload["env_id"] == ready_env.id
    assert payload["env_fingerprint"] == ready_env.fingerprint
    assert payload["cancel_requested"] is False


# ---------------------------------------------------------------------------
# python_recipe_v1 wrapper — fail-closed shapes + happy path (eager dispatch)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wrapper_requires_recipe_block():
    from app.services.skills_registry import wrappers

    with pytest.raises(ValueError, match="recipe_config_missing"):
        await wrappers._python_recipe_v1({"n": 1}, {"workspace_id": "ws"})


@pytest.mark.asyncio
async def test_wrapper_fails_closed_when_disabled(monkeypatch):
    from app.services.skills_registry import wrappers

    monkeypatch.setattr(settings, "recipe_execution_enabled", False)
    with pytest.raises(ValueError, match="recipe_execution_disabled"):
        await wrappers._python_recipe_v1(
            {"_recipe": {"code": "def main(i):\n    return {}"}},
            {"workspace_id": "ws"},
        )


@pytest.mark.asyncio
async def test_wrapper_requires_workspace(monkeypatch):
    from app.services.skills_registry import wrappers

    monkeypatch.setattr(settings, "recipe_execution_enabled", True)
    with pytest.raises(ValueError, match="recipe_workspace_required"):
        await wrappers._python_recipe_v1(
            {"_recipe": {"code": "def main(i):\n    return {}"}}, {}
        )


@pytest.mark.asyncio
async def test_wrapper_rejects_invalid_code(monkeypatch):
    from app.services.skills_registry import wrappers

    monkeypatch.setattr(settings, "recipe_execution_enabled", True)
    with pytest.raises(ValueError, match="RECIPE_CODE_REQUIRED"):
        await wrappers._python_recipe_v1(
            {"_recipe": {"code": "   "}}, {"workspace_id": "ws"}
        )


@pytest.mark.asyncio
async def test_wrapper_happy_path_eager(db_session, workspace, ready_env, monkeypatch):
    """Eager dispatch runs inline; the wrapper's first poll finds it terminal."""

    from app.services.skills_registry import wrappers

    monkeypatch.setattr(settings, "worker_eager_mode", True)
    code = "def main(inputs):\n    return {'sum': inputs['a'] + inputs['b']}\n"
    result = await wrappers._python_recipe_v1(
        {"a": 2, "b": 3, "_recipe": {"code": code, "node_id": "recipe.node"}},
        {"workspace_id": workspace.id, "run_id": None},
    )
    assert result == {"sum": 5}

    row = (
        db_session.query(RecipeExecution)
        .filter(RecipeExecution.workspace_id == workspace.id)
        .order_by(RecipeExecution.created_at.desc())
        .first()
    )
    assert row is not None
    assert row.status == "succeeded"
    assert row.node_id == "recipe.node"
    # The reserved `_recipe` block never reaches the script inputs.
    assert row.input_json == {"a": 2, "b": 3}


@pytest.mark.asyncio
async def test_wrapper_surfaces_script_failure(db_session, workspace, ready_env, monkeypatch):
    from app.services.skills_registry import wrappers

    monkeypatch.setattr(settings, "worker_eager_mode", True)
    code = "def main(inputs):\n    raise ValueError('recipe blew up')\n"
    with pytest.raises(RuntimeError, match="recipe_execution_failed"):
        await wrappers._python_recipe_v1(
            {"_recipe": {"code": code}},
            {"workspace_id": workspace.id},
        )


def test_wrapper_is_registered_and_bound():
    from app.services.skills_registry import wrappers

    assert wrappers.runtime_status("python_recipe_v1") == "bound"


def test_recipe_skill_is_claimed_by_a_universal_capability():
    """An unclaimed skill is filtered from every workspace catalog, which
    blocks System binding (`skill_not_visible`) and greys the palette row.
    The recipe node is a universal Flow Builder primitive, so a universal
    capability must carry it."""

    from app.services.skills_registry.seed import SEED_CAPABILITIES, SEED_SKILLS

    assert any(
        entry["slug"] == "python_recipe_v1" for entry in SEED_SKILLS
    ), "the recipe skill must stay in the seeded registry"
    carriers = [
        entry
        for entry in SEED_CAPABILITIES
        if "python_recipe_v1" in entry.get("skill_slugs", ())
    ]
    assert carriers, "python_recipe_v1 must be claimed by a seeded capability"
    assert any(entry.get("tier") == "universal" for entry in carriers), (
        "at least one carrier must be universal so every workspace can bind "
        "the recipe node"
    )


# ---------------------------------------------------------------------------
# DAG projection of the graph-owned recipe config
# ---------------------------------------------------------------------------


def test_apply_recipe_node_config_injects_and_strips():
    from app.services.run_engine.dag import DagNode, _apply_recipe_node_config

    node = DagNode(
        id="recipe.1",
        type="skill",
        kind="task",
        label="Python Recipe",
        config={
            "skill_slug": "python_recipe_v1",
            "params": {
                "code": "def main(i):\n    return {}",
                "requirements_text": "pandas==2.2.0",
                "timeout_s": 45,
            },
        },
        skill_slug="python_recipe_v1",
        data={},
    )
    node_input = {
        "n": 1,
        # Palette-params merge may seed raw config keys as input defaults…
        "code": "def main(i):\n    return {'hacked': True}",
        "timeout_s": 45,
        # …and a caller may try to smuggle its own block.
        "_recipe": {"code": "evil"},
    }
    _apply_recipe_node_config(node, node_input)
    assert node_input["_recipe"]["code"] == "def main(i):\n    return {}"
    assert node_input["_recipe"]["requirements_text"] == "pandas==2.2.0"
    assert node_input["_recipe"]["timeout_s"] == 45
    assert node_input["_recipe"]["node_id"] == "recipe.1"
    assert "code" not in node_input
    assert "timeout_s" not in node_input
    assert node_input["n"] == 1


def test_apply_recipe_node_config_strips_reserved_key_on_other_nodes():
    from app.services.run_engine.dag import DagNode, _apply_recipe_node_config

    node = DagNode(
        id="other.1",
        type="skill",
        kind="task",
        label="LLM",
        config={"skill_slug": "azure_llm_v1"},
        skill_slug="azure_llm_v1",
        data={},
    )
    node_input = {"q": "hello", "_recipe": {"code": "evil"}}
    _apply_recipe_node_config(node, node_input)
    assert node_input == {"q": "hello"}
