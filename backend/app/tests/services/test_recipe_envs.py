"""Recipe env service: spec normalization, fingerprints, build cycle, sweep."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.recipe import PythonEnv, RecipeExecution
from app.models.workspace import Workspace
from app.services import recipe_envs
from app.services.recipe_envs import (
    EnvSpec,
    RecipeError,
    build_env,
    build_env_spec,
    normalize_requirements,
    reclaim_stale_builds,
    resolve_env,
    sweep_envs,
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
def envs_root(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "recipe_envs_path", str(tmp_path / "envs"))
    return tmp_path / "envs"


# ---------------------------------------------------------------------------
# normalize_requirements
# ---------------------------------------------------------------------------


def test_normalize_requirements_sorts_dedups_and_strips_comments():
    text = """
    # data stack
    pandas==2.2.0   # pinned
    numpy>=1.26

    pandas==2.2.0
    Requests
    """
    assert normalize_requirements(text) == (
        "numpy>=1.26",
        "pandas==2.2.0",
        "Requests",
    )


def test_normalize_requirements_empty_and_none():
    assert normalize_requirements(None) == ()
    assert normalize_requirements("") == ()
    assert normalize_requirements("   \n  # only a comment\n") == ()


def test_normalize_requirements_rejects_pip_option_lines():
    for line in ("-r other.txt", "--index-url https://x", "-e .", "./local-pkg"):
        with pytest.raises(RecipeError) as exc:
            normalize_requirements(line)
        assert exc.value.code == "RECIPE_REQUIREMENT_OPTION_FORBIDDEN"


def test_normalize_requirements_rejects_non_string():
    with pytest.raises(RecipeError) as exc:
        normalize_requirements(["pandas"])
    assert exc.value.code == "RECIPE_REQUIREMENTS_INVALID"


def test_normalize_requirements_line_and_count_limits():
    with pytest.raises(RecipeError) as exc:
        normalize_requirements("a" * 301)
    assert exc.value.code == "RECIPE_REQUIREMENT_LINE_TOO_LONG"
    many = "\n".join(f"pkg{i}" for i in range(201))
    with pytest.raises(RecipeError) as exc:
        normalize_requirements(many)
    assert exc.value.code == "RECIPE_REQUIREMENTS_TOO_MANY"


# ---------------------------------------------------------------------------
# build_env_spec + fingerprint
# ---------------------------------------------------------------------------


def test_build_env_spec_normalizes_registries():
    spec = build_env_spec(
        requirements_text="b\na",
        index_url=" https://mirror.example/simple ",
        extra_index_urls=["https://extra.example/simple", "https://extra.example/simple"],
    )
    assert spec.requirements == ("a", "b")
    assert spec.index_url == "https://mirror.example/simple"
    assert spec.extra_index_urls == ("https://extra.example/simple",)


def test_build_env_spec_rejects_bad_registry():
    with pytest.raises(RecipeError) as exc:
        build_env_spec(index_url="ftp://nope")
    assert exc.value.code == "RECIPE_REGISTRY_INVALID"
    with pytest.raises(RecipeError):
        build_env_spec(extra_index_urls="not-a-list")
    with pytest.raises(RecipeError):
        build_env_spec(extra_index_urls=[f"https://r{i}.example" for i in range(5)])


def test_build_env_spec_applies_default_registry(monkeypatch):
    monkeypatch.setattr(
        settings, "recipe_pip_default_index_url", "https://corp.example/simple"
    )
    assert build_env_spec().index_url == "https://corp.example/simple"
    # An explicit registry wins over the deployment default.
    spec = build_env_spec(index_url="https://other.example/simple")
    assert spec.index_url == "https://other.example/simple"


def test_fingerprint_is_order_insensitive_and_registry_sensitive():
    a = build_env_spec(requirements_text="pandas==2.2.0\nnumpy>=1.26")
    b = build_env_spec(requirements_text="numpy>=1.26\npandas==2.2.0")
    assert a.fingerprint() == b.fingerprint()
    c = build_env_spec(
        requirements_text="numpy>=1.26\npandas==2.2.0",
        index_url="https://mirror.example/simple",
    )
    assert c.fingerprint() != a.fingerprint()
    d = build_env_spec(requirements_text="numpy>=1.27\npandas==2.2.0")
    assert d.fingerprint() != a.fingerprint()


# ---------------------------------------------------------------------------
# resolve_env
# ---------------------------------------------------------------------------


def test_resolve_env_is_get_or_create(db_session, workspace):
    spec = build_env_spec(requirements_text="left-pad==1.0")
    first = resolve_env(db_session, workspace_id=workspace.id, spec=spec)
    db_session.commit()
    second = resolve_env(db_session, workspace_id=workspace.id, spec=spec)
    assert first.id == second.id
    assert first.status == "pending"
    assert first.fingerprint == spec.fingerprint()

    other_ws = Workspace(
        id=str(uuid4()), name="Other", slug=f"other-{uuid4().hex[:8]}", settings={}
    )
    db_session.add(other_ws)
    db_session.commit()
    third = resolve_env(db_session, workspace_id=other_ws.id, spec=spec)
    assert third.id != first.id


# ---------------------------------------------------------------------------
# build cycle (real `python -m venv`, no pip install → no network)
# ---------------------------------------------------------------------------


def test_build_env_creates_ready_venv_and_lock(db_session, workspace, envs_root):
    spec = build_env_spec()  # empty requirements: venv only, no pip install
    env = resolve_env(db_session, workspace_id=workspace.id, spec=spec)
    db_session.commit()

    built = build_env(db_session, env.id)
    assert built.status == "ready"
    assert built.size_bytes > 0
    assert built.built_at is not None
    assert built.lock_text is not None  # pip freeze captured (may be empty text)
    python_bin = recipe_envs.env_python(workspace.id, built.fingerprint)
    assert python_bin.exists()


def test_build_env_failure_is_recorded(db_session, workspace, envs_root, monkeypatch):
    spec = build_env_spec(requirements_text="definitely-not-a-package")
    env = resolve_env(db_session, workspace_id=workspace.id, spec=spec)
    db_session.commit()

    def boom(args, *, log_parts, deadline):
        log_parts.append("simulated pip failure\n")
        raise RuntimeError("step failed with exit code 1: pip install")

    monkeypatch.setattr(recipe_envs, "_run_build_step", boom)
    built = build_env(db_session, env.id)
    assert built.status == "failed"
    assert "exit code 1" in (built.build_error or "")
    assert "simulated pip failure" in (built.build_log_tail or "")
    assert built.size_bytes == 0


def test_evict_then_rebuild_reuses_lock(db_session, workspace, envs_root, monkeypatch):
    spec = build_env_spec()
    env = resolve_env(db_session, workspace_id=workspace.id, spec=spec)
    db_session.commit()
    built = build_env(db_session, env.id)
    assert built.status == "ready"
    built.lock_text = "leftpad==1.0.0\n"  # simulate a captured resolution
    db_session.commit()

    recipe_envs.evict_env(db_session, built, reason="test")
    assert built.status == "evicted"
    assert built.size_bytes == 0
    assert not recipe_envs.env_dir(workspace.id, built.fingerprint).exists()
    # The row and its lock survive eviction — that is the rebuild contract.
    assert built.lock_text == "leftpad==1.0.0\n"

    captured: list[list[str]] = []
    real_step = recipe_envs._run_build_step

    def spy(args, *, log_parts, deadline):
        captured.append(list(args))
        if args[1:3] == ["-m", "venv"]:
            return real_step(args, log_parts=log_parts, deadline=deadline)
        # Assert the rebuild installs from the requirements file that now
        # carries the lock, then skip the real network call.
        req_file = recipe_envs.env_dir(workspace.id, built.fingerprint) / "requirements.txt"
        assert req_file.read_text(encoding="utf-8") == "leftpad==1.0.0\n"
        log_parts.append("installed from lock\n")

    monkeypatch.setattr(recipe_envs, "_run_build_step", spy)
    rebuilt = build_env(db_session, built.id)
    assert rebuilt.status == "ready"
    assert any("pip" in " ".join(args) for args in captured)
    # The lock is not overwritten by the rebuild.
    assert rebuilt.lock_text == "leftpad==1.0.0\n"


def test_build_env_concurrent_claim_waits(db_session, workspace, envs_root, monkeypatch):
    spec = build_env_spec()
    env = resolve_env(db_session, workspace_id=workspace.id, spec=spec)
    env.status = "building"
    db_session.commit()

    monkeypatch.setattr(settings, "recipe_env_build_timeout_s", 1.0)
    with pytest.raises(RecipeError) as exc:
        build_env(db_session, env.id)
    assert exc.value.code == "RECIPE_ENV_BUILD_TIMEOUT"


def test_reclaim_stale_builds(db_session, workspace):
    spec = build_env_spec()
    env = resolve_env(db_session, workspace_id=workspace.id, spec=spec)
    env.status = "building"
    db_session.commit()
    # Fresh building row is left alone.
    assert reclaim_stale_builds(db_session) == 0
    env.updated_at = datetime.utcnow() - timedelta(hours=2)
    db_session.commit()
    assert reclaim_stale_builds(db_session) == 1
    assert env.status == "pending"


# ---------------------------------------------------------------------------
# sweep — storage governor
# ---------------------------------------------------------------------------


def _ready_env(
    db_session,
    workspace,
    *,
    size: int,
    last_used_days_ago: float,
    fingerprint: str | None = None,
) -> PythonEnv:
    env = PythonEnv(
        id=str(uuid4()),
        workspace_id=workspace.id,
        fingerprint=fingerprint or uuid4().hex + uuid4().hex[:32],
        python_version="3.12",
        requirements_text="",
        status="ready",
        size_bytes=size,
        built_at=datetime.utcnow() - timedelta(days=last_used_days_ago),
        last_used_at=datetime.utcnow() - timedelta(days=last_used_days_ago),
    )
    db_session.add(env)
    db_session.commit()
    return env


def test_sweep_evicts_idle_envs_past_ttl(db_session, workspace, envs_root, monkeypatch):
    monkeypatch.setattr(settings, "recipe_envs_idle_ttl_days", 14)
    monkeypatch.setattr(settings, "recipe_envs_max_total_bytes", 0)  # quota off
    old = _ready_env(db_session, workspace, size=10, last_used_days_ago=30)
    fresh = _ready_env(db_session, workspace, size=10, last_used_days_ago=1)

    report = sweep_envs(db_session)
    assert report["evicted_ttl"] == 1
    assert old.status == "evicted"
    assert fresh.status == "ready"


def test_sweep_evicts_lru_down_to_watermark(db_session, workspace, envs_root, monkeypatch):
    monkeypatch.setattr(settings, "recipe_envs_idle_ttl_days", 365)
    monkeypatch.setattr(settings, "recipe_envs_max_total_bytes", 250)
    monkeypatch.setattr(settings, "recipe_envs_low_watermark_bytes", 150)
    monkeypatch.setattr(settings, "recipe_envs_min_idle_minutes", 0)
    oldest = _ready_env(db_session, workspace, size=100, last_used_days_ago=9)
    middle = _ready_env(db_session, workspace, size=100, last_used_days_ago=5)
    newest = _ready_env(db_session, workspace, size=100, last_used_days_ago=1)

    report = sweep_envs(db_session)
    # 300 > 250 → evict LRU until ≤ 150: oldest then middle go, newest stays.
    assert report["evicted_lru"] == 2
    assert oldest.status == "evicted"
    assert middle.status == "evicted"
    assert newest.status == "ready"
    assert report["ready_bytes"] == 100


def test_sweep_protects_envs_with_active_executions(
    db_session, workspace, envs_root, monkeypatch
):
    monkeypatch.setattr(settings, "recipe_envs_idle_ttl_days", 14)
    monkeypatch.setattr(settings, "recipe_envs_max_total_bytes", 0)
    protected = _ready_env(db_session, workspace, size=10, last_used_days_ago=30)
    db_session.add(
        RecipeExecution(
            id=str(uuid4()),
            workspace_id=workspace.id,
            env_id=protected.id,
            status="running",
        )
    )
    db_session.commit()

    report = sweep_envs(db_session)
    assert report["evicted_ttl"] == 0
    assert protected.status == "ready"


def test_sweep_respects_min_idle_grace(db_session, workspace, envs_root, monkeypatch):
    monkeypatch.setattr(settings, "recipe_envs_idle_ttl_days", 365)
    monkeypatch.setattr(settings, "recipe_envs_max_total_bytes", 50)
    monkeypatch.setattr(settings, "recipe_envs_low_watermark_bytes", 10)
    monkeypatch.setattr(settings, "recipe_envs_min_idle_minutes", 60)
    hot = _ready_env(db_session, workspace, size=100, last_used_days_ago=0.001)

    report = sweep_envs(db_session)
    # Over quota but the only candidate was used a minute ago: never evicted.
    assert report["evicted_lru"] == 0
    assert hot.status == "ready"


def test_cap_pip_cache_deletes_oldest_first(envs_root, monkeypatch):
    cache = recipe_envs.pip_cache_dir()
    cache.mkdir(parents=True)
    import os
    import time

    old_file = cache / "old.whl"
    new_file = cache / "new.whl"
    old_file.write_bytes(b"x" * 60)
    new_file.write_bytes(b"y" * 60)
    stamp = time.time()
    os.utime(old_file, (stamp - 1000, stamp - 1000))
    os.utime(new_file, (stamp, stamp))

    freed = recipe_envs._cap_pip_cache(80)
    assert freed == 60
    assert not old_file.exists()
    assert new_file.exists()


def test_serialize_env_shape(db_session, workspace):
    spec = EnvSpec(python_version="3.12", requirements=("pandas==2.2.0",))
    env = resolve_env(db_session, workspace_id=workspace.id, spec=spec)
    db_session.commit()
    payload = recipe_envs.serialize_env(env)
    assert payload["id"] == env.id
    assert payload["status"] == "pending"
    assert payload["fingerprint"] == spec.fingerprint()
    assert payload["requirements_text"] == "pandas==2.2.0"
    assert payload["has_lock"] is False
    assert payload["use_count"] == 0
