"""API surface for /python-envs and /recipe-executions."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import recipes
from app.core.config import settings
from app.models.recipe import PythonEnv, RecipeExecution
from app.models.user import User
from app.models.workspace import Workspace


@pytest.fixture()
def workspace(db_session) -> Workspace:
    ws = Workspace(
        id=str(uuid4()),
        name="Recipes API",
        slug=f"recipes-api-{uuid4().hex[:8]}",
        settings={},
    )
    db_session.add(ws)
    db_session.commit()
    return ws


@pytest.fixture()
def user(db_session) -> User:
    token = uuid4().hex[:8]
    row = User(
        id=str(uuid4()),
        username=f"recipes-{token}",
        email=f"recipes-{token}@example.invalid",
        role="user",
    )
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture()
def client(db_session, workspace, user) -> TestClient:
    app = FastAPI()
    app.include_router(recipes.envs_router, prefix="/python-envs")
    app.include_router(recipes.executions_router, prefix="/recipe-executions")
    app.dependency_overrides[recipes.get_current_workspace] = lambda: workspace
    app.dependency_overrides[recipes.get_current_user] = lambda: user
    app.dependency_overrides[recipes.get_db] = lambda: db_session
    return TestClient(app)


@pytest.fixture()
def envs_root(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "recipe_envs_path", str(tmp_path / "envs"))
    return tmp_path / "envs"


def _seed_env(db_session, workspace, *, status: str = "pending") -> PythonEnv:
    env = PythonEnv(
        id=str(uuid4()),
        workspace_id=workspace.id,
        fingerprint=uuid4().hex + uuid4().hex[:32],
        python_version="3.12",
        requirements_text="pandas==2.2.0",
        status=status,
    )
    db_session.add(env)
    db_session.commit()
    return env


def _seed_execution(db_session, workspace, *, status: str = "queued") -> RecipeExecution:
    execution = RecipeExecution(
        id=str(uuid4()),
        workspace_id=workspace.id,
        status=status,
        input_json={"n": 1},
    )
    db_session.add(execution)
    db_session.commit()
    return execution


# ---------------------------------------------------------------------------
# /python-envs
# ---------------------------------------------------------------------------


def test_resolve_creates_pending_env_and_is_idempotent(client):
    body = {"requirements_text": "pandas==2.2.0\nnumpy>=1.26"}
    first = client.post("/python-envs/resolve", json=body)
    assert first.status_code == 200
    env = first.json()["env"]
    assert env["status"] == "pending"
    assert env["requirements_text"] == "numpy>=1.26\npandas==2.2.0"
    assert "enabled" in first.json()["feature"]

    # Same spec in a different order → the same content-addressed row.
    second = client.post(
        "/python-envs/resolve",
        json={"requirements_text": "numpy>=1.26\npandas==2.2.0"},
    )
    assert second.json()["env"]["id"] == env["id"]


def test_resolve_rejects_option_lines_with_code_payload(client):
    response = client.post(
        "/python-envs/resolve",
        json={"requirements_text": "-r other.txt"},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "RECIPE_REQUIREMENT_OPTION_FORBIDDEN"
    assert detail["message"]


def test_resolve_rejects_bad_registry(client):
    response = client.post(
        "/python-envs/resolve",
        json={"requirements_text": "", "index_url": "ftp://nope"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "RECIPE_REGISTRY_INVALID"


def test_list_and_get_envs_are_workspace_scoped(client, db_session, workspace):
    mine = _seed_env(db_session, workspace)
    other_ws = Workspace(
        id=str(uuid4()), name="Other", slug=f"other-{uuid4().hex[:8]}", settings={}
    )
    db_session.add(other_ws)
    db_session.commit()
    foreign = _seed_env(db_session, other_ws)

    listed = client.get("/python-envs")
    assert listed.status_code == 200
    ids = {row["id"] for row in listed.json()["envs"]}
    assert mine.id in ids
    assert foreign.id not in ids

    assert client.get(f"/python-envs/{mine.id}").status_code == 200
    missing = client.get(f"/python-envs/{foreign.id}")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "RECIPE_ENV_NOT_FOUND"


def test_build_endpoint_fails_closed_when_disabled(client, db_session, workspace, monkeypatch):
    monkeypatch.setattr(settings, "recipe_execution_enabled", False)
    env = _seed_env(db_session, workspace)
    response = client.post(f"/python-envs/{env.id}/build")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RECIPE_EXECUTION_DISABLED"


def test_build_endpoint_eager_builds_inline(
    client, db_session, workspace, envs_root, monkeypatch
):
    monkeypatch.setattr(settings, "recipe_execution_enabled", True)
    monkeypatch.setattr(settings, "worker_eager_mode", True)
    # Empty requirements → venv creation only, no network.
    resolved = client.post("/python-envs/resolve", json={"requirements_text": ""})
    env_id = resolved.json()["env"]["id"]
    response = client.post(f"/python-envs/{env_id}/build")
    assert response.status_code == 200
    assert response.json()["dispatched"] is True
    assert response.json()["env"]["status"] == "ready"

    # Already ready → no rebuild dispatched.
    again = client.post(f"/python-envs/{env_id}/build")
    assert again.json()["dispatched"] is False


def test_evict_endpoint_conflicts(client, db_session, workspace, envs_root):
    env = _seed_env(db_session, workspace, status="ready")
    db_session.add(
        RecipeExecution(
            id=str(uuid4()),
            workspace_id=workspace.id,
            env_id=env.id,
            status="running",
        )
    )
    db_session.commit()
    busy = client.delete(f"/python-envs/{env.id}")
    assert busy.status_code == 409
    assert busy.json()["detail"]["code"] == "RECIPE_ENV_IN_USE"

    building = _seed_env(db_session, workspace, status="building")
    blocked = client.delete(f"/python-envs/{building.id}")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "RECIPE_ENV_BUILDING"


def test_evict_endpoint_frees_ready_env(client, db_session, workspace, envs_root):
    env = _seed_env(db_session, workspace, status="ready")
    response = client.delete(f"/python-envs/{env.id}")
    assert response.status_code == 200
    assert response.json()["env"]["status"] == "evicted"


# ---------------------------------------------------------------------------
# /recipe-executions
# ---------------------------------------------------------------------------


def test_list_executions_filters(client, db_session, workspace):
    run_id = str(uuid4())
    match = RecipeExecution(
        id=str(uuid4()),
        workspace_id=workspace.id,
        run_id=run_id,
        node_id="recipe.node",
        status="succeeded",
    )
    other = _seed_execution(db_session, workspace)
    db_session.add(match)
    db_session.commit()

    unfiltered = client.get("/recipe-executions")
    assert unfiltered.status_code == 200
    assert {row["id"] for row in unfiltered.json()["executions"]} >= {match.id, other.id}

    filtered = client.get(
        "/recipe-executions", params={"run_id": run_id, "node_id": "recipe.node"}
    )
    rows = filtered.json()["executions"]
    assert [row["id"] for row in rows] == [match.id]


def test_get_execution_scoped_404(client, db_session):
    other_ws = Workspace(
        id=str(uuid4()), name="Other", slug=f"other-{uuid4().hex[:8]}", settings={}
    )
    db_session.add(other_ws)
    db_session.commit()
    foreign = _seed_execution(db_session, other_ws)
    response = client.get(f"/recipe-executions/{foreign.id}")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "RECIPE_EXECUTION_NOT_FOUND"


def test_cancel_queued_execution(client, db_session, workspace):
    execution = _seed_execution(db_session, workspace, status="queued")
    response = client.post(f"/recipe-executions/{execution.id}/cancel")
    assert response.status_code == 200
    payload = response.json()["execution"]
    assert payload["status"] == "cancelled"
    assert payload["cancel_requested"] is True


def test_cancel_running_execution_sets_flag_only(client, db_session, workspace):
    execution = _seed_execution(db_session, workspace, status="running")
    response = client.post(f"/recipe-executions/{execution.id}/cancel")
    payload = response.json()["execution"]
    assert payload["status"] == "running"
    assert payload["cancel_requested"] is True


def test_cancel_terminal_execution_is_noop(client, db_session, workspace):
    execution = _seed_execution(db_session, workspace, status="succeeded")
    response = client.post(f"/recipe-executions/{execution.id}/cancel")
    payload = response.json()["execution"]
    assert payload["status"] == "succeeded"
    assert payload["cancel_requested"] is False
