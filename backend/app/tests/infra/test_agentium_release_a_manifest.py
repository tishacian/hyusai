"""Fail-closed tests for the content-free Release A Git diff manifest."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[4]
HELPER = ROOT / "scripts" / "agentium_release_a_manifest.py"
FIXED_BASE_SHA = "154fd98822439747846cd941dce1bf8191f379b2"
NOW = datetime(2026, 7, 22, 19, 0, tzinfo=UTC)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("agentium_release_a_manifest_test", HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def module() -> ModuleType:
    return _load()


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repository), *arguments],
        text=True,
    ).strip()


def _commit(repository: Path, message: str) -> str:
    subprocess.run(["git", "-C", str(repository), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "user.name=Release A Test",
            "-c",
            "user.email=release-a-test@example.invalid",
            "commit",
            "-qm",
            message,
        ],
        check=True,
    )
    return _git(repository, "rev-parse", "HEAD")


def _write(repository: Path, relative: str, content: str = "test\n") -> Path:
    target = repository / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "-C", str(repository), "init", "-q"], check=True)
    _write(repository, "README.md", "base\n")
    base_sha = _commit(repository, "base")
    return repository, base_sha


def _release(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    path: str = "scripts/agentium_release_a_manifest.py",
) -> tuple[Path, str]:
    repository, base_sha = _repository(tmp_path)
    monkeypatch.setattr(module, "LIVE_BASE_SHA", base_sha)
    _write(repository, path)
    return repository, _commit(repository, "release a")


def _resign(module: ModuleType, payload: dict[str, object]) -> None:
    body = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    payload["manifest_sha256"] = module._sha256(module._canonical_json(body))


def _review_policy(
    module: ModuleType,
    repository: Path,
    release_sha: str,
    *,
    now: datetime = NOW,
) -> dict[str, object]:
    inventory = module._diff_inventory(repository, release_sha)
    files = []
    for row in inventory:
        path = row["path"]
        app_controls = module._APP_HARDENING_CONTROLS.get(path)
        files.append(
            {
                **row,
                "classification": (
                    "runtime_safety_hardening" if app_controls is not None else "verification_test"
                ),
                "hardening_controls": (
                    sorted(app_controls)
                    if app_controls is not None
                    else ["reviewed_exact_patch"]
                ),
            }
        )
    policy: dict[str, object] = {
        "profile": module.REVIEW_PROFILE,
        "base_sha": module.LIVE_BASE_SHA,
        "release_a_sha": release_sha,
        "approval": "approved",
        "reviewer": "release-a-independent-reviewer",
        "review_ticket": "OPS-RELEASE-A-TEST",
        "reviewed_at": module._utc_text(now),
        "files": files,
    }
    policy["review_sha256"] = module._review_policy_digest(policy)
    return policy


def test_valid_manifest_binds_fixed_range_policy_and_content_free_inventory(
    module,
    monkeypatch,
    tmp_path,
) -> None:
    repository, release_sha = _release(module, monkeypatch, tmp_path)
    review = _review_policy(module, repository, release_sha)

    manifest = module.build_manifest(repository, release_sha, review, now=NOW)
    receipt = module.verify_manifest(manifest, repository, release_sha, review, now=NOW)

    assert set(manifest) == {
        "profile",
        "base_sha",
        "release_a_sha",
        "files",
        "diff_inventory_sha256",
        "file_count",
        "policy_sha256",
        "review_policy_sha256",
        "generated_at",
        "manifest_sha256",
    }
    assert manifest["profile"] == "agentium-release-a-diff-manifest-v7"
    assert manifest["base_sha"] == module.LIVE_BASE_SHA
    assert manifest["release_a_sha"] == release_sha
    assert manifest["file_count"] == 1
    assert manifest["policy_sha256"] == module.POLICY_SHA256
    assert receipt == {
        "profile": "agentium-release-a-diff-verification-v7",
        "result": "passed",
        "base_sha": module.LIVE_BASE_SHA,
        "release_a_sha": release_sha,
        "manifest_sha256": manifest["manifest_sha256"],
        "review_policy_sha256": review["review_sha256"],
        "verified_at": "2026-07-22T19:00:00Z",
    }
    rendered = json.dumps(manifest, sort_keys=True)
    assert manifest["files"] == [
        {
            "path": "scripts/agentium_release_a_manifest.py",
            "status": "A",
            "base_mode": None,
            "release_mode": "100644",
            "base_blob": None,
            "release_blob": _git(
                repository,
                "rev-parse",
                f"{release_sha}:scripts/agentium_release_a_manifest.py",
            ),
            "patch_sha256": manifest["files"][0]["patch_sha256"],
        }
    ]
    assert len(manifest["files"][0]["patch_sha256"]) == 64
    assert "test\n" not in rendered


def test_v7_allowlist_is_bound_to_an_immutable_profile_digest(module) -> None:
    assert module.PROFILE == "agentium-release-a-diff-manifest-v7"
    assert module.VERIFICATION_PROFILE == "agentium-release-a-diff-verification-v7"
    assert module._ALLOWLIST_SHA256_BY_PROFILE == {
        "agentium-release-a-diff-manifest-v2": (
            "a0df2377efc1d79d141a3cb9fddd61d278b363ad3a4172023c97aaa89f3ea91a"
        ),
        "agentium-release-a-diff-manifest-v3": (
            "8cff57a64e05b9b0c776a777c8e35de4c96ef69a902e3eb694635a56f45f0364"
        ),
        "agentium-release-a-diff-manifest-v4": (
            "84194570157cc1204c255909e53fe4d592548df82e4166dd561b62d40177b3d9"
        ),
        "agentium-release-a-diff-manifest-v5": (
            "f6a182b5e47e20c7a89dbe7399fcffa41b25a8048e1a078b5b738fcd89ec80fb"
        ),
        "agentium-release-a-diff-manifest-v6": (
            "aa94442c20ab0dc07ee8e0ec118b2e64d96b2a99aff0e1ee891ef7d56f6ed027"
        ),
        "agentium-release-a-diff-manifest-v7": (
            "2253c4eacf762b8cf7a9667a4504f335d42e90fb29031cfdaa33933115be7b48"
        ),
    }
    assert module.ALLOWED_PATHS_SHA256 == (
        "2253c4eacf762b8cf7a9667a4504f335d42e90fb29031cfdaa33933115be7b48"
    )
    assert module._assert_allowlist_profile_contract() == module.ALLOWED_PATHS_SHA256

    silently_extended = module._ALLOWED_PATHS | {"scripts/unreviewed-release-a-helper.py"}
    with pytest.raises(module.ReleaseAManifestError, match="without an explicit profile bump"):
        module._assert_allowlist_profile_contract(allowed_paths=silently_extended)
    with pytest.raises(module.ReleaseAManifestError, match="profile bump is required"):
        module._assert_allowlist_profile_contract(
            profile="agentium-release-a-diff-manifest-v8",
            allowed_paths=silently_extended,
        )


def test_policy_fingerprint_includes_regex_flags(module) -> None:
    payload = module._policy_payload()
    env_contract = payload["forbidden_non_app_additions"][
        "docker/env/agentium.env.example"
    ][0]

    assert env_contract == {
        "pattern": r"\bAUTHORIZATION_V2_[A-Z0-9_]+\b",
        "flags": module.re.IGNORECASE | module.re.UNICODE,
    }
    assert all(
        set(contract) == {"pattern", "flags"}
        for contract in payload["forbidden_app_structures"]
    )


@pytest.mark.parametrize(
    "path",
    [
        "backend/app/tests/infra/test_agentium_terminal_gate_authorization.py",
        "backend/app/tests/infra/test_agentium_release_a_sftp_identity_invalidation.py",
        "backend/app/tests/infra/test_agentium_compliance_contract.py",
        "backend/app/tests/infra/test_image_provenance_contract.py",
    ],
)
def test_v7_explicitly_allows_release_a_safety_proofs(
    module,
    monkeypatch,
    tmp_path,
    path,
) -> None:
    repository, release_sha = _release(module, monkeypatch, tmp_path, path=path)
    review = _review_policy(module, repository, release_sha)

    manifest = module.build_manifest(repository, release_sha, review, now=NOW)

    assert manifest["files"][0]["path"] == path
    assert review["files"][0]["classification"] == "verification_test"
    assert review["files"][0]["hardening_controls"] == ["reviewed_exact_patch"]


@pytest.mark.parametrize(
    "variable",
    [
        "AUTHORIZATION_V2_TRUSTED_REF",
        "authorization_v2_trusted_ref",
        "Authorization_V2_Trusted_Ref",
    ],
)
def test_shared_env_rejects_release_b_authorization_variables_in_any_case(
    module,
    monkeypatch,
    tmp_path,
    variable,
) -> None:
    repository, base_sha = _repository(tmp_path)
    monkeypatch.setattr(module, "LIVE_BASE_SHA", base_sha)
    _write(
        repository,
        "docker/env/agentium.env.example",
        f"AGENTIUM_POSTGRES_DB=agentium\n{variable}=demo/agentic\n",
    )
    release_sha = _commit(repository, "mixed release env")

    with pytest.raises(module.ReleaseAManifestError, match="Release B addition"):
        module.build_manifest(repository, release_sha, {}, now=NOW)


def _release_a_e2e_source() -> str:
    return """\
const expectedSha = process.env['E2E_EXPECTED_SHA'];
const safeContentFree = process.env['E2E_SAFE_CONTENT_FREE'] === '1';
type WorkspaceTarget = { id: string; slug: string };
async function client360DryRunProjection() { return true; }
async function crossTenantSystemIsolationProjection() { return true; }
await expect(links).toHaveCount(3);
const baseline = { primary_surfaces: ['chat', 'client360-pdr', 'knowledge-capture'] };
expect(baseline.activeSystems).toHaveLength(5);
"""


def test_shared_e2e_accepts_only_the_three_surface_release_a_contract(
    module,
    monkeypatch,
    tmp_path,
) -> None:
    repository, base_sha = _repository(tmp_path)
    monkeypatch.setattr(module, "LIVE_BASE_SHA", base_sha)
    path = "frontend-ng/e2e/tests/09-live-workspace-contract.spec.ts"
    _write(repository, path, _release_a_e2e_source())
    release_sha = _commit(repository, "release a e2e safety contract")
    review = _review_policy(module, repository, release_sha)

    manifest = module.build_manifest(repository, release_sha, review, now=NOW)

    assert manifest["files"][0]["path"] == path


@pytest.mark.parametrize(
    "release_b_line",
    [
        "fetch('/api/v1/governance/workspace-apps/installations');",
        "await page.goto('/knowledge/interventions');",
        "const fseSystem = true;",
        "const installedAppIds = [];",
        "const app = 'andritz.chat';",
        "await expect(links).toHaveCount(4);",
        "expect(baseline.activeSystems).toHaveLength(6);",
    ],
)
def test_shared_e2e_rejects_release_b_product_contracts(
    module,
    monkeypatch,
    tmp_path,
    release_b_line,
) -> None:
    repository, base_sha = _repository(tmp_path)
    monkeypatch.setattr(module, "LIVE_BASE_SHA", base_sha)
    path = "frontend-ng/e2e/tests/09-live-workspace-contract.spec.ts"
    _write(repository, path, _release_a_e2e_source() + release_b_line + "\n")
    release_sha = _commit(repository, "mixed release e2e")

    with pytest.raises(module.ReleaseAManifestError, match="Release B addition"):
        module.build_manifest(repository, release_sha, {}, now=NOW)


def test_shared_e2e_requires_all_release_a_safety_markers(
    module,
    monkeypatch,
    tmp_path,
) -> None:
    repository, base_sha = _repository(tmp_path)
    monkeypatch.setattr(module, "LIVE_BASE_SHA", base_sha)
    path = "frontend-ng/e2e/tests/09-live-workspace-contract.spec.ts"
    source = _release_a_e2e_source().replace(
        "async function crossTenantSystemIsolationProjection() { return true; }\n",
        "",
    )
    _write(repository, path, source)
    release_sha = _commit(repository, "incomplete release a e2e")

    with pytest.raises(module.ReleaseAManifestError, match="safety invariant"):
        module.build_manifest(repository, release_sha, {}, now=NOW)


def _compliance_document(module, claim=None) -> dict[str, object]:
    return {
        "schema_version": 1,
        "claims": [
            {"label": "Unrelated safety claim", "path": "README.md", "contains": []},
            copy.deepcopy(claim or module._BASE_ROLLBACK_CLAIM),
        ],
    }


def _compliance_release(
    module,
    monkeypatch,
    tmp_path,
    candidate: dict[str, object],
) -> tuple[Path, str]:
    repository, _initial_base = _repository(tmp_path)
    path = module._PRODUCT_COMPLIANCE_PATH
    _write(repository, path, json.dumps(_compliance_document(module)))
    base_sha = _commit(repository, "base compliance contract")
    monkeypatch.setattr(module, "LIVE_BASE_SHA", base_sha)
    _write(repository, path, json.dumps(candidate))
    return repository, _commit(repository, "release a compliance contract")


def test_product_compliance_allows_only_exact_rollback_claim_replacement(
    module,
    monkeypatch,
    tmp_path,
) -> None:
    candidate = _compliance_document(module, module._RELEASE_A_ROLLBACK_CLAIM)
    repository, release_sha = _compliance_release(
        module,
        monkeypatch,
        tmp_path,
        candidate,
    )
    review = _review_policy(module, repository, release_sha)

    manifest = module.build_manifest(repository, release_sha, review, now=NOW)

    assert manifest["files"][0]["path"] == module._PRODUCT_COMPLIANCE_PATH


def test_product_compliance_rejects_any_unrelated_claim_change(
    module,
    monkeypatch,
    tmp_path,
) -> None:
    candidate = _compliance_document(module, module._RELEASE_A_ROLLBACK_CLAIM)
    candidate["claims"].append(
        {"label": "Lot 9 app platform", "path": "product.py", "contains": []}
    )
    repository, release_sha = _compliance_release(
        module,
        monkeypatch,
        tmp_path,
        candidate,
    )

    with pytest.raises(module.ReleaseAManifestError, match="only the exact"):
        module.build_manifest(repository, release_sha, {}, now=NOW)


@pytest.mark.parametrize("equivalent_version", [True, 1.0])
def test_product_compliance_rejects_python_equal_but_json_distinct_types(
    module,
    monkeypatch,
    tmp_path,
    equivalent_version,
) -> None:
    candidate = _compliance_document(module, module._RELEASE_A_ROLLBACK_CLAIM)
    candidate["schema_version"] = equivalent_version
    repository, release_sha = _compliance_release(
        module,
        monkeypatch,
        tmp_path,
        candidate,
    )

    with pytest.raises(module.ReleaseAManifestError, match="only the exact"):
        module.build_manifest(repository, release_sha, {}, now=NOW)


@pytest.mark.parametrize("mode", ["wrong", "duplicate"])
def test_product_compliance_rejects_wrong_or_duplicate_rollback_claim(
    module,
    monkeypatch,
    tmp_path,
    mode,
) -> None:
    wrong = copy.deepcopy(module._RELEASE_A_ROLLBACK_CLAIM)
    wrong["contains"][0] = "printf 'format\\t4\\n'"
    candidate = _compliance_document(
        module,
        wrong if mode == "wrong" else module._RELEASE_A_ROLLBACK_CLAIM,
    )
    if mode == "duplicate":
        candidate["claims"].append(copy.deepcopy(module._RELEASE_A_ROLLBACK_CLAIM))
    repository, release_sha = _compliance_release(
        module,
        monkeypatch,
        tmp_path,
        candidate,
    )

    with pytest.raises(module.ReleaseAManifestError, match="exactly one"):
        module.build_manifest(repository, release_sha, {}, now=NOW)


@pytest.mark.parametrize(
    "path",
    [
        "backend/app/api/v1/endpoints/secure_deposit.py",
        "backend/app/services/secure_deposit.py",
        "backend/app/services/secure_deposit_sftp.py",
        "backend/app/tests/api/test_secure_deposit_api.py",
        "backend/app/tests/services/test_secure_deposit.py",
    ],
)
def test_v3_explicitly_allows_sftp_retry_safety_hardening(
    module,
    monkeypatch,
    tmp_path,
    path,
) -> None:
    repository, release_sha = _release(module, monkeypatch, tmp_path, path=path)
    review = _review_policy(module, repository, release_sha)

    manifest = module.build_manifest(repository, release_sha, review, now=NOW)

    assert manifest["files"][0]["path"] == path
    if path in module._APP_HARDENING_CONTROLS:
        assert review["files"][0]["classification"] == "runtime_safety_hardening"
        assert review["files"][0]["hardening_controls"] == [
            "sftp_canary_retry_safe_audit"
        ]


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("backend/alembic/versions/999_business.py", "denied business"),
        ("scripts/backfill_customer_vectors.py", "backfill"),
        ("scripts/seed_andritz.py", "seed"),
        ("scripts/bootstrap_workspace.py", "bootstrap"),
        (
            "backend/app/services/system_catalog_bindings.py",
            "explicitly denied business service",
        ),
        ("backend/app/services/workspace_blueprints.py", "explicitly denied business service"),
        ("frontend-ng/src/app/features/chat/chat.component.ts", "denied business"),
        ("docs/demo-runs/proof.md", "denied business"),
        ("docker/env/agentium.env", "runtime environment"),
        ("deploy/operator-private.key", "secret, archive"),
        ("backend/app/services/some_new_service.py", "outside the exact"),
        ("docs/ops/nested/runbook.md", "outside the exact"),
    ],
)
def test_forbidden_or_unknown_paths_fail_closed(
    module,
    monkeypatch,
    tmp_path,
    path,
    message,
) -> None:
    repository, base_sha = _repository(tmp_path)
    monkeypatch.setattr(module, "LIVE_BASE_SHA", base_sha)
    _write(repository, path)
    release_sha = _commit(repository, "forbidden")

    with pytest.raises(module.ReleaseAManifestError, match=message):
        module.build_manifest(repository, release_sha, {}, now=NOW)


def test_one_level_ops_markdown_is_the_only_bounded_documentation_rule(
    module,
    monkeypatch,
    tmp_path,
) -> None:
    repository, release_sha = _release(
        module,
        monkeypatch,
        tmp_path,
        path="docs/ops/release-a-operator-window.md",
    )
    review = _review_policy(module, repository, release_sha)
    manifest = module.build_manifest(repository, release_sha, review, now=NOW)
    assert manifest["file_count"] == 1


@pytest.mark.parametrize("field", ["diff_inventory_sha256", "policy_sha256", "generated_at"])
def test_manifest_tamper_breaks_self_checksum(
    module,
    monkeypatch,
    tmp_path,
    field,
) -> None:
    repository, release_sha = _release(module, monkeypatch, tmp_path)
    review = _review_policy(module, repository, release_sha)
    manifest = module.build_manifest(repository, release_sha, review, now=NOW)
    if field == "generated_at":
        manifest[field] = "2026-07-22T18:59:59Z"
    else:
        manifest[field] = "f" * 64

    with pytest.raises(module.ReleaseAManifestError, match="self-checksum|policy fingerprint"):
        module.verify_manifest(manifest, repository, release_sha, review, now=NOW)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("profile", "agentium-release-a-diff-manifest-v8", "profile"),
        ("base_sha", "b" * 40, "fixed live base"),
        ("release_a_sha", "c" * 40, "expected SHA"),
        ("file_count", True, "integer"),
        ("file_count", 0, "positive"),
        ("manifest_sha256", "not-a-digest", "SHA-256"),
    ],
)
def test_manifest_schema_and_identity_mutations_fail_closed(
    module,
    monkeypatch,
    tmp_path,
    field,
    value,
    message,
) -> None:
    repository, release_sha = _release(module, monkeypatch, tmp_path)
    review = _review_policy(module, repository, release_sha)
    manifest = module.build_manifest(repository, release_sha, review, now=NOW)
    manifest[field] = value

    with pytest.raises(module.ReleaseAManifestError, match=message):
        module.verify_manifest(manifest, repository, release_sha, review, now=NOW)


def test_recomputed_manifest_cannot_lie_about_committed_inventory(
    module,
    monkeypatch,
    tmp_path,
) -> None:
    repository, release_sha = _release(module, monkeypatch, tmp_path)
    review = _review_policy(module, repository, release_sha)
    manifest = module.build_manifest(repository, release_sha, review, now=NOW)
    manifest["diff_inventory_sha256"] = "d" * 64
    _resign(module, manifest)

    with pytest.raises(module.ReleaseAManifestError, match="committed Git range"):
        module.verify_manifest(manifest, repository, release_sha, review, now=NOW)


def test_extra_or_missing_fields_fail_closed(module, monkeypatch, tmp_path) -> None:
    repository, release_sha = _release(module, monkeypatch, tmp_path)
    review = _review_policy(module, repository, release_sha)
    manifest = module.build_manifest(repository, release_sha, review, now=NOW)
    missing = copy.deepcopy(manifest)
    missing.pop("file_count")
    extra = copy.deepcopy(manifest)
    extra["paths"] = ["must-never-be-emitted"]

    for candidate in (missing, extra):
        with pytest.raises(module.ReleaseAManifestError, match="invalid field set"):
            module.verify_manifest(candidate, repository, release_sha, review, now=NOW)


def test_deletion_is_forbidden(module, monkeypatch, tmp_path) -> None:
    repository, base_sha = _repository(tmp_path)
    allowed = _write(repository, "deploy/agentium-backend.service")
    base_sha = _commit(repository, "base with runtime file")
    monkeypatch.setattr(module, "LIVE_BASE_SHA", base_sha)
    allowed.unlink()
    release_sha = _commit(repository, "delete runtime file")

    with pytest.raises(module.ReleaseAManifestError, match="status 'D' is forbidden"):
        module.build_manifest(repository, release_sha, {}, now=NOW)


def test_rename_is_forbidden_even_between_two_allowed_paths(module, monkeypatch, tmp_path) -> None:
    repository, _initial_base = _repository(tmp_path)
    source = _write(repository, "scripts/deploy-vm.sh")
    base_sha = _commit(repository, "base with deploy helper")
    monkeypatch.setattr(module, "LIVE_BASE_SHA", base_sha)
    destination = repository / "scripts" / "deploy-agentium-safe.sh"
    source.rename(destination)
    release_sha = _commit(repository, "rename")

    with pytest.raises(module.ReleaseAManifestError, match="renames and copies are forbidden"):
        module.build_manifest(repository, release_sha, {}, now=NOW)


def test_symlinks_are_forbidden(module, monkeypatch, tmp_path) -> None:
    repository, base_sha = _repository(tmp_path)
    monkeypatch.setattr(module, "LIVE_BASE_SHA", base_sha)
    target = repository / "scripts" / "deploy-agentium-safe.sh"
    target.parent.mkdir(parents=True)
    target.symlink_to("../README.md")
    release_sha = _commit(repository, "symlink")

    with pytest.raises(module.ReleaseAManifestError, match="only regular committed files"):
        module.build_manifest(repository, release_sha, {}, now=NOW)


def test_release_must_be_a_nonempty_descendant(module, monkeypatch, tmp_path) -> None:
    repository, base_sha = _repository(tmp_path)
    monkeypatch.setattr(module, "LIVE_BASE_SHA", base_sha)
    with pytest.raises(module.ReleaseAManifestError, match="must differ"):
        module.build_manifest(repository, base_sha, {}, now=NOW)

    subprocess.run(["git", "-C", str(repository), "checkout", "--orphan", "other"], check=True)
    subprocess.run(["git", "-C", str(repository), "rm", "-qrf", "."], check=True)
    _write(repository, "scripts/deploy-agentium-safe.sh")
    unrelated_sha = _commit(repository, "unrelated")
    with pytest.raises(module.ReleaseAManifestError, match="must descend"):
        module.build_manifest(repository, unrelated_sha, {}, now=NOW)


def test_manifest_generated_in_future_is_rejected(module, monkeypatch, tmp_path) -> None:
    repository, release_sha = _release(module, monkeypatch, tmp_path)
    review = _review_policy(module, repository, release_sha)
    manifest = module.build_manifest(
        repository,
        release_sha,
        review,
        now=NOW + timedelta(minutes=6),
    )
    with pytest.raises(module.ReleaseAManifestError, match="future"):
        module.verify_manifest(manifest, repository, release_sha, review, now=NOW)


@pytest.mark.parametrize(
    ("path", "content", "message"),
    [
        (
            "backend/app/core/config.py",
            'authorization_v2_trusted_project_id = "123"\n',
            "product token",
        ),
        (
            "backend/app/main.py",
            "system_catalog = {}\n",
            "product token",
        ),
        (
            "backend/app/services/settings_service.py",
            "workspace_app_platform = object()\n",
            "product token",
        ),
        (
            "backend/app/services/rag_preset_service.py",
            "decision_scenario = {}\n",
            "product token",
        ),
        (
            "backend/app/api/v1/endpoints/settings.py",
            '@router.get("/new-product-surface")\ndef product_surface():\n    return {}\n',
            "product route or persistence structure",
        ),
        (
            "backend/app/api/v1/endpoints/settings.py",
            'from app.core.config import settings\n\n@router.get("/new-product-surface")\ndef product_surface():\n    return {}\n',
            "product route or persistence structure",
        ),
        (
            "backend/app/api/v1/endpoints/settings.py",
            'from app.core.config import settings\n\n@internal_router.post("/new-product-surface")\ndef product_surface():\n    return {}\n',
            "product route or persistence structure",
        ),
        (
            "backend/app/api/v1/endpoints/settings.py",
            'from app.core.config import settings\n\n@router . get("/new-product-surface")\ndef product_surface():\n    return {}\n',
            "product route or persistence structure",
        ),
        (
            "backend/app/api/v1/endpoints/settings.py",
            'from app.core.config import settings\n\n@api.v1.internal_router.post("/new-product-surface")\ndef product_surface():\n    return {}\n',
            "product route or persistence structure",
        ),
        (
            "backend/app/api/v1/endpoints/settings.py",
            'from app.core.config import settings\nfrom app.routes import get\n\n@get("/new-product-surface")\ndef product_surface():\n    return {}\n',
            "product route or persistence structure",
        ),
        (
            "backend/app/api/v1/endpoints/settings.py",
            'from app.core.config import settings\nroute = internal_router.post\n\n@route("/new-product-surface")\ndef product_surface():\n    return {}\n',
            "product route or persistence structure",
        ),
        (
            "backend/app/services/livekit_service.py",
            'class ProductModel:\n    __tablename__ = "product"\n',
            "product route or persistence structure",
        ),
    ],
)
def test_allowed_application_paths_reject_product_semantics(
    module,
    monkeypatch,
    tmp_path,
    path,
    content,
    message,
) -> None:
    repository, base_sha = _repository(tmp_path)
    monkeypatch.setattr(module, "LIVE_BASE_SHA", base_sha)
    _write(repository, path, content)
    release_sha = _commit(repository, "product work disguised as release a")

    with pytest.raises(module.ReleaseAManifestError, match=message):
        module.build_manifest(repository, release_sha, {}, now=NOW)


def test_application_patch_requires_exact_external_hardening_review(
    module,
    monkeypatch,
    tmp_path,
) -> None:
    repository, base_sha = _repository(tmp_path)
    monkeypatch.setattr(module, "LIVE_BASE_SHA", base_sha)
    _write(
        repository,
        "backend/app/core/config.py",
        'startup_reconciliation = "disabled"\n',
    )
    release_sha = _commit(repository, "startup mutation barrier")
    review = _review_policy(module, repository, release_sha)

    manifest = module.build_manifest(repository, release_sha, review, now=NOW)
    assert manifest["review_policy_sha256"] == review["review_sha256"]

    wrong_control = copy.deepcopy(review)
    wrong_control["files"][0]["hardening_controls"] = ["product_enablement"]
    wrong_control["review_sha256"] = module._review_policy_digest(wrong_control)
    with pytest.raises(module.ReleaseAManifestError, match="unauthorized hardening control"):
        module.build_manifest(repository, release_sha, wrong_control, now=NOW)

    wrong_classification = copy.deepcopy(review)
    wrong_classification["files"][0]["classification"] = "verification_test"
    wrong_classification["review_sha256"] = module._review_policy_digest(wrong_classification)
    with pytest.raises(module.ReleaseAManifestError, match="runtime safety hardening"):
        module.build_manifest(repository, release_sha, wrong_classification, now=NOW)

    incomplete_controls = copy.deepcopy(review)
    incomplete_controls["files"][0]["hardening_controls"] = [
        "immutable_runtime_environment"
    ]
    incomplete_controls["review_sha256"] = module._review_policy_digest(
        incomplete_controls
    )
    with pytest.raises(module.ReleaseAManifestError, match="every required"):
        module.build_manifest(
            repository,
            release_sha,
            incomplete_controls,
            now=NOW,
        )


@pytest.mark.parametrize(
    "path",
    [
        "backend/app/api/v1/endpoints/secure_deposit.py",
        "backend/app/api/v1/endpoints/settings.py",
        "backend/app/core/config.py",
        "backend/app/core/settings_manager.py",
        "backend/app/main.py",
        "backend/app/services/livekit_service.py",
        "backend/app/services/rag_preset_service.py",
        "backend/app/services/secure_deposit.py",
        "backend/app/services/secure_deposit_sftp.py",
        "backend/app/services/settings_service.py",
    ],
)
def test_every_application_path_requires_its_exact_control_set(
    module,
    monkeypatch,
    tmp_path,
    path,
) -> None:
    repository, release_sha = _release(module, monkeypatch, tmp_path, path=path)
    review = _review_policy(module, repository, release_sha)
    required = sorted(module._APP_HARDENING_CONTROLS[path])

    assert review["files"][0]["classification"] == "runtime_safety_hardening"
    assert review["files"][0]["hardening_controls"] == required
    module.build_manifest(repository, release_sha, review, now=NOW)

    tampered = copy.deepcopy(review)
    if len(required) > 1:
        tampered["files"][0]["hardening_controls"] = required[:-1]
        message = "every required"
    else:
        tampered["files"][0]["hardening_controls"] = sorted(
            [*required, "unreviewed_product_control"]
        )
        message = "unauthorized hardening control"
    tampered["review_sha256"] = module._review_policy_digest(tampered)

    with pytest.raises(module.ReleaseAManifestError, match=message):
        module.build_manifest(repository, release_sha, tampered, now=NOW)


def test_review_policy_must_bind_every_exact_blob_and_patch(
    module,
    monkeypatch,
    tmp_path,
) -> None:
    repository, release_sha = _release(module, monkeypatch, tmp_path)
    review = _review_policy(module, repository, release_sha)
    review["files"][0]["release_blob"] = "f" * 40
    review["review_sha256"] = module._review_policy_digest(review)

    with pytest.raises(module.ReleaseAManifestError, match="exact Git inventory"):
        module.build_manifest(repository, release_sha, review, now=NOW)


def test_review_policy_cannot_be_omitted_pending_or_self_resigned_after_tamper(
    module,
    monkeypatch,
    tmp_path,
) -> None:
    repository, release_sha = _release(module, monkeypatch, tmp_path)
    with pytest.raises(module.ReleaseAManifestError, match="invalid field set"):
        module.build_manifest(repository, release_sha, {}, now=NOW)

    review = _review_policy(module, repository, release_sha)
    review["approval"] = "pending"
    review["review_sha256"] = module._review_policy_digest(review)
    with pytest.raises(module.ReleaseAManifestError, match="approval must be explicit"):
        module.build_manifest(repository, release_sha, review, now=NOW)


def test_review_template_is_unusable_until_explicitly_edited_and_sealed(
    module,
    monkeypatch,
    tmp_path,
) -> None:
    repository, release_sha = _release(module, monkeypatch, tmp_path)
    draft = module.build_review_template(repository, release_sha, now=NOW)
    assert draft["approval"] == "pending"
    assert draft["files"][0]["classification"] == "PENDING_REVIEW"
    with pytest.raises(module.ReleaseAManifestError, match="approval must be explicit"):
        module.build_manifest(repository, release_sha, draft, now=NOW)

    draft["approval"] = "approved"
    draft["reviewer"] = "independent-release-reviewer"
    draft["review_ticket"] = "OPS-RELEASE-A-42"
    draft["files"][0]["classification"] = "deployment_orchestration"
    sealed = module.seal_review_policy(draft, repository, release_sha, now=NOW)
    manifest = module.build_manifest(repository, release_sha, sealed, now=NOW)
    assert manifest["review_policy_sha256"] == sealed["review_sha256"]


def test_manifest_exposes_only_content_free_exact_inventory_and_revalidates_it(
    module,
    monkeypatch,
    tmp_path,
) -> None:
    repository, release_sha = _release(module, monkeypatch, tmp_path)
    review = _review_policy(module, repository, release_sha)
    manifest = module.build_manifest(repository, release_sha, review, now=NOW)
    assert set(manifest["files"][0]) == module._INVENTORY_KEYS
    assert "test\n" not in json.dumps(manifest)

    manifest["files"][0]["patch_sha256"] = "e" * 64
    manifest["diff_inventory_sha256"] = module._sha256(module._canonical_json(manifest["files"]))
    _resign(module, manifest)
    with pytest.raises(module.ReleaseAManifestError, match="committed Git range"):
        module.verify_manifest(manifest, repository, release_sha, review, now=NOW)


def test_private_manifest_loader_rejects_public_symlink_and_hardlink(
    module,
    tmp_path,
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    manifest.chmod(0o644)
    with pytest.raises(module.ReleaseAManifestError, match="private owner-only"):
        module._load_private_manifest(manifest)

    manifest.chmod(0o600)
    alias = tmp_path / "manifest-hardlink.json"
    os.link(manifest, alias)
    with pytest.raises(module.ReleaseAManifestError, match="private owner-only"):
        module._load_private_manifest(manifest)
    alias.unlink()

    symlink = tmp_path / "manifest-symlink.json"
    symlink.symlink_to(manifest)
    with pytest.raises(module.ReleaseAManifestError, match="private owner-only"):
        module._load_private_manifest(symlink)


def test_review_and_manifest_artifacts_must_live_outside_candidate_worktree(
    module,
    tmp_path,
) -> None:
    repository, _base_sha = _repository(tmp_path)
    with pytest.raises(module.ReleaseAManifestError, match="outside the candidate"):
        module._assert_external_artifact(
            repository,
            repository / ".private" / "review.json",
            label="semantic review policy",
        )
    module._assert_external_artifact(
        repository,
        tmp_path / "review.json",
        label="semantic review policy",
    )


def test_cli_create_and_verify_against_the_fixed_live_base(tmp_path) -> None:
    assert _git(ROOT, "cat-file", "-t", FIXED_BASE_SHA) == "commit"
    repository = tmp_path / "release-a"
    subprocess.run(
        ["git", "clone", "-q", "--shared", "--no-checkout", str(ROOT), str(repository)],
        check=True,
    )
    subprocess.run(["git", "-C", str(repository), "checkout", "-q", FIXED_BASE_SHA], check=True)
    runtime = repository / "deploy" / "agentium-backend.service"
    runtime.write_text(
        runtime.read_text(encoding="utf-8") + "\n# release-a-test\n", encoding="utf-8"
    )
    release_sha = _commit(repository, "release a")
    manifest = tmp_path / "private-release-a-manifest.json"
    draft_path = tmp_path / "private-release-a-review-draft.json"
    review_path = tmp_path / "private-release-a-review.json"

    drafted = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "review-template",
            "--repository",
            str(repository),
            "--release-a-sha",
            release_sha,
            "--output",
            str(draft_path),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    assert json.loads(drafted.stdout)["result"] == "pending_review"
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    draft["approval"] = "approved"
    draft["reviewer"] = "independent-release-reviewer"
    draft["review_ticket"] = "OPS-RELEASE-A-CLI"
    draft["files"][0]["classification"] = "runtime_configuration"
    draft_path.write_text(json.dumps(draft), encoding="utf-8")
    draft_path.chmod(0o600)
    sealed = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "seal-review",
            "--repository",
            str(repository),
            "--release-a-sha",
            release_sha,
            "--draft",
            str(draft_path),
            "--output",
            str(review_path),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    assert json.loads(sealed.stdout)["result"] == "approved"

    created = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "create",
            "--repository",
            str(repository),
            "--release-a-sha",
            release_sha,
            "--review-policy",
            str(review_path),
            "--output",
            str(manifest),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    creation = json.loads(created.stdout)
    assert creation["result"] == "created"
    assert creation["base_sha"] == FIXED_BASE_SHA
    assert manifest.stat().st_mode & 0o777 == 0o600

    verified = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "verify",
            "--repository",
            str(repository),
            "--release-a-sha",
            release_sha,
            "--review-policy",
            str(review_path),
            "--manifest",
            str(manifest),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    assert json.loads(verified.stdout)["result"] == "passed"

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["file_count"] += 1
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    manifest.chmod(0o600)
    rejected = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "verify",
            "--repository",
            str(repository),
            "--release-a-sha",
            release_sha,
            "--review-policy",
            str(review_path),
            "--manifest",
            str(manifest),
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert rejected.returncode == 2
    assert "self-checksum mismatch" in rejected.stderr
