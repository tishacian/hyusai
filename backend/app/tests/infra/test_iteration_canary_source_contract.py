"""Fail-closed source binding for the lightweight production canary gate."""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[4]
ORCHESTRATOR = ROOT / "scripts" / "agentium_protected_runner_orchestrator.py"
RUNNER = ROOT / "scripts" / "run-iteration-canaries.sh"


def _load() -> ModuleType:
    name = "agentium_iteration_canary_source_under_test"
    spec = importlib.util.spec_from_file_location(name, ORCHESTRATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _repository(module: ModuleType, root: Path) -> str:
    for relative_path in module.ITERATION_CANARY_SOURCE_PATHS:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"fixture for {relative_path}\n", encoding="utf-8")
    subprocess.run(["/usr/bin/git", "-C", str(root), "init", "--quiet"], check=True)
    subprocess.run(["/usr/bin/git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        [
            "/usr/bin/git",
            "-C",
            str(root),
            "-c",
            "user.name=Agentium test",
            "-c",
            "user.email=agentium@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        ],
        check=True,
    )
    sha = subprocess.run(
        ["/usr/bin/git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (root / ".agentium-source-sha").write_text(f"{sha}\n", encoding="ascii")
    return sha


def test_iteration_runner_uses_the_canonical_source_gate() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    assert "module._safe_iteration_source_root(source_root, tested_sha)" in source
    assert source.index("module._safe_iteration_source_root") < source.index(
        "module._playwright_runtime_attestation"
    )


def test_iteration_contract_freezes_experience_specs_and_dependency_lock() -> None:
    module = _load()
    assert {
        "frontend-ng/e2e/fixtures/accessibility-matrix.ts",
        "frontend-ng/e2e/fixtures/experience-canary.ts",
        "frontend-ng/e2e/tests/16-experience-work-canary.spec.ts",
        "frontend-ng/e2e/tests/17-experience-studio-canary.spec.ts",
    } <= set(module.ITERATION_CANARY_SOURCE_PATHS)
    assert hashlib.sha256((ROOT / "frontend-ng/package-lock.json").read_bytes()).hexdigest() == (
        module.PACKAGE_LOCK_SHA256
    )


def test_iteration_source_accepts_only_the_exact_clean_commit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load()
    sha = _repository(module, tmp_path)
    monkeypatch.setattr(module, "_safe_source_root", lambda root, _sha: root)

    assert module._safe_iteration_source_root(tmp_path, sha) == tmp_path
    with pytest.raises(module.OrchestratorError, match="SHA differs"):
        module._safe_iteration_source_root(tmp_path, "f" * 40)


@pytest.mark.parametrize("untracked", [False, True])
def test_iteration_source_rejects_tracked_or_untracked_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    untracked: bool,
) -> None:
    module = _load()
    sha = _repository(module, tmp_path)
    monkeypatch.setattr(module, "_safe_source_root", lambda root, _sha: root)
    if untracked:
        (tmp_path / "unexpected.txt").write_text("drift\n", encoding="utf-8")
    else:
        (tmp_path / module.ITERATION_CANARY_SOURCE_PATHS[0]).write_text(
            "modified\n", encoding="utf-8"
        )

    with pytest.raises(module.OrchestratorError, match="dirty"):
        module._safe_iteration_source_root(tmp_path, sha)
