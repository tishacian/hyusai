"""Adversarial tests for the external protected-runner orchestrator."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "agentium_protected_runner_orchestrator.py"
DEPLOYMENT_ID = "protected-runner-acceptance-20260723-v1"
SHA = "a" * 40
NOW = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
CAPTURED_AT = "2026-07-23T11:59:00Z"
PRINCIPAL = "operator_personal_admin"


def _load() -> ModuleType:
    name = "agentium_protected_runner_orchestrator_under_test"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def module() -> ModuleType:
    return _load()


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.write_bytes(
        (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    )
    path.chmod(0o600)


def _common_artifact(module: ModuleType, token: str) -> dict[str, Any]:
    checks = {name: True for name in module.REQUIRED_CHECKS[token]}
    if token in {"canary-sentinel", "canary-octocity"}:
        checks.update({"navigation_item_count": 7, "action_pack_count": 3})
    if token == "canary-andritz":
        checks.update({"configured_app_count": 3, "accessible_route_count": 3})
    return {
        "captured_at": CAPTURED_AT,
        "checks": checks,
        "deployment_id": DEPLOYMENT_ID,
        "evidence_class": "acceptance",
        "formal_release_eligible": False,
        "kind": "agentium-protected-runner-canary",
        "principal_class": PRINCIPAL,
        "profile": "agentium-protected-runner-canary-v1",
        "result": "passed",
        "schema_version": 1,
        "tested_sha": SHA,
        "token": token,
        "workspace_sha256": "b" * 64,
    }


def _sftp_artifact(module: ModuleType) -> dict[str, Any]:
    return {
        "access_id_sha256": "1" * 64,
        "captured_at": CAPTURED_AT,
        "checks": {
            name: True for name in module.REQUIRED_CHECKS["sftp-positive-auth"]
        },
        "claim": "sftp-positive-auth",
        "credential_fingerprint_sha256": "2" * 64,
        "deployment_id": DEPLOYMENT_ID,
        "environment": "production",
        "evidence_class": "acceptance",
        "formal_release_eligible": False,
        "hostname_sha256": "3" * 64,
        "kind": "sftp-positive-auth.artifact",
        "link_id_sha256": "4" * 64,
        "principal_class": PRINCIPAL,
        "principal_sha256": "5" * 64,
        "profile": "agentium-protected-runner-sftp-acceptance-v1",
        "result": "passed",
        "schema_version": 1,
        "sftp_host_key_sha256": "6" * 64,
        "tested_sha": SHA,
        "workspace_id_sha256": "7" * 64,
    }


def _evidence_set(module: ModuleType, root: Path) -> None:
    root.mkdir(mode=0o700)
    for token in module.TOKENS:
        payload = (
            _sftp_artifact(module)
            if token == "sftp-positive-auth"
            else _common_artifact(module, token)
        )
        _write(root / f"{token}.artifact", payload)


def test_closed_seven_artifact_set_is_accepted(
    module: ModuleType, tmp_path: Path
) -> None:
    output = tmp_path / "output"
    _evidence_set(module, output)

    result = module.validate_output_directory(
        output,
        deployment_id=DEPLOYMENT_ID,
        tested_sha=SHA,
        evidence_class="acceptance",
        principal_class=PRINCIPAL,
        formal_release_eligible=False,
        now=NOW,
    )

    assert tuple(result) == module.TOKENS
    assert all(len(row["artifact_sha256"]) == 64 for row in result.values())


def test_failed_or_missing_business_check_is_rejected(
    module: ModuleType, tmp_path: Path
) -> None:
    output = tmp_path / "output"
    _evidence_set(module, output)
    path = output / "canary-andritz.artifact"
    payload = json.loads(path.read_bytes())
    payload["checks"]["dry_run_confirmed"] = False
    _write(path, payload)

    with pytest.raises(module.OrchestratorError, match="did not pass"):
        module.validate_output_directory(
            output,
            deployment_id=DEPLOYMENT_ID,
            tested_sha=SHA,
            evidence_class="acceptance",
            principal_class=PRINCIPAL,
            formal_release_eligible=False,
            now=NOW,
        )


def test_raw_identity_in_artifact_is_rejected(
    module: ModuleType, tmp_path: Path
) -> None:
    output = tmp_path / "output"
    _evidence_set(module, output)
    path = output / "canary-livekit.artifact"
    payload = json.loads(path.read_bytes())
    payload["workspace_sha256"] = "619d0704-4bc7-4fe6-8400-a144f8c29046"
    _write(path, payload)

    with pytest.raises(module.OrchestratorError):
        module.validate_output_directory(
            output,
            deployment_id=DEPLOYMENT_ID,
            tested_sha=SHA,
            evidence_class="acceptance",
            principal_class=PRINCIPAL,
            formal_release_eligible=False,
            now=NOW,
        )


def test_release_mode_requires_distinct_sha_exact_source_and_automation(
    module: ModuleType,
) -> None:
    with pytest.raises(module.OrchestratorError, match="non-personal"):
        module.validate_mode(
            evidence_class="release",
            formal_release_eligible=True,
            principal_class=PRINCIPAL,
            live_sha="a" * 40,
            release_a_sha="b" * 40,
            tested_sha="b" * 40,
            source_sha="b" * 40,
        )
    with pytest.raises(module.OrchestratorError, match="distinct candidate"):
        module.validate_mode(
            evidence_class="release",
            formal_release_eligible=True,
            principal_class="automation_non_personal",
            live_sha="b" * 40,
            release_a_sha="b" * 40,
            tested_sha="b" * 40,
            source_sha="b" * 40,
        )
    with pytest.raises(module.OrchestratorError, match="source checkout"):
        module.validate_mode(
            evidence_class="release",
            formal_release_eligible=True,
            principal_class="automation_non_personal",
            live_sha="a" * 40,
            release_a_sha="b" * 40,
            tested_sha="b" * 40,
            source_sha="c" * 40,
        )


def test_acceptance_cannot_claim_formal_eligibility(module: ModuleType) -> None:
    with pytest.raises(module.OrchestratorError, match="cannot be formal"):
        module.validate_mode(
            evidence_class="acceptance",
            formal_release_eligible=True,
            principal_class=PRINCIPAL,
            live_sha=SHA,
            release_a_sha=SHA,
            tested_sha=SHA,
            source_sha="b" * 40,
        )


def test_showcase_derivation_removes_raw_object_ids(
    module: ModuleType, tmp_path: Path
) -> None:
    runner_path = tmp_path / "runner.json"
    behavior_path = tmp_path / "behavior.json"
    output_path = tmp_path / "canary-showcase.artifact"
    checks = {name: True for name in module.REQUIRED_CHECKS["canary-showcase"]}
    build_info = {
        service: {
            "revision": SHA,
            "service": service,
            "revision_verified": True,
        }
        for service in ("backend", "frontend")
    }
    common = {
        "schema_version": 1,
        "commit_sha": SHA,
        "outcome": "passed",
        "checks": checks,
        "build_info": build_info,
    }
    runner = {
        **common,
        "kind": "runner",
        "runner": "playwright",
        "suite": "frontend-ng/e2e/tests/11-system360-canary.spec.ts",
    }
    raw_workspace = "619d0704-4bc7-4fe6-8400-a144f8c29046"
    behavior = {
        **common,
        "kind": "behavior",
        "workspace": {"id": raw_workspace},
        "discovered": {"system_id": "private", "capability_id": "private"},
    }
    for path, payload in ((runner_path, runner), (behavior_path, behavior)):
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        path.chmod(0o600)

    module.derive_showcase_artifact(
        runner_path=runner_path,
        behavior_path=behavior_path,
        output_path=output_path,
        deployment_id=DEPLOYMENT_ID,
        tested_sha=SHA,
        evidence_class="acceptance",
        principal_class=PRINCIPAL,
        formal_release_eligible=False,
        now=NOW,
    )

    raw = output_path.read_bytes()
    payload = json.loads(raw)
    assert raw_workspace.encode() not in raw
    assert payload["workspace_sha256"] == module.hashlib.sha256(
        raw_workspace.encode()
    ).hexdigest()
    assert stat_mode(output_path) == 0o600


def stat_mode(path: Path) -> int:
    return os.stat(path, follow_symlinks=False).st_mode & 0o777
