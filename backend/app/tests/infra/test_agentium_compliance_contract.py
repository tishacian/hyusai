"""Static governance tests for the Agentium product compliance contract."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "agentium_compliance.py"
MANIFEST = ROOT / "config" / "agentium" / "product-compliance.v1.json"


def _load_compliance_module():
    spec = importlib.util.spec_from_file_location("agentium_compliance_contract", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_agentium_compliance_contract_is_current() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_manifest_cannot_author_a_delivery_status() -> None:
    compliance = _load_compliance_module()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    tampered = deepcopy(manifest)
    tampered["claims"][0]["status"] = "shipped"

    with pytest.raises(compliance.ComplianceError, match="forbidden key"):
        compliance.validate_manifest(tampered, ROOT)


def test_manifest_schema_forbids_unknown_root_generated_and_claim_keys() -> None:
    compliance = _load_compliance_module()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    mutations = (
        lambda value: value.__setitem__("extra", True),
        lambda value: value["generated"].__setitem__("extra", True),
        lambda value: value["claims"][0].__setitem__("extra", True),
    )

    for mutate in mutations:
        tampered = deepcopy(manifest)
        mutate(tampered)
        with pytest.raises(compliance.ComplianceError, match="unknown keys"):
            compliance.validate_manifest(tampered, ROOT)


def test_static_proofs_without_runner_attestations_are_not_shipped() -> None:
    compliance = _load_compliance_module()
    result = compliance.ClaimResult(
        claim={"id": "LOT5-EXAMPLE"},
        required_families=("implementation", "tests"),
        required_runners=("node", "pytest"),
        proofs=(),
        computed_state="static_verified",
    )

    claim = compliance.build_report(
        [result],
        commit_sha="a" * 40,
        runner_attestations=[],
        deployment_attestations=[],
    )["claims"][0]

    assert claim["computed_state"] == "static_verified"
    assert claim["runner_evidence_complete"] is False
    assert claim["runner_verified"] is False
    assert claim["shipped"] is False
    assert claim["deployed"] is False


def test_sha_attestations_cannot_upgrade_a_partial_repository_claim() -> None:
    compliance = _load_compliance_module()
    result = compliance.ClaimResult(
        claim={"id": "LOT5-EXAMPLE"},
        required_families=("implementation", "tests"),
        required_runners=("pytest",),
        proofs=(),
        computed_state="partial",
    )
    sha = "a" * 40
    report = compliance.build_report(
        [result],
        commit_sha=sha,
        runner_attestations=[
            {
                "schema_version": 1,
                "kind": "runner",
                "commit_sha": sha,
                "runner": "pytest",
                "claims": {"LOT5-EXAMPLE": "passed"},
            }
        ],
        deployment_attestations=[
            {
                "schema_version": 1,
                "kind": "deployment",
                "commit_sha": sha,
                "environment": "production",
                "claims": {"LOT5-EXAMPLE": "deployed"},
            }
        ],
    )

    claim = report["claims"][0]
    assert claim["computed_state"] == "partial"
    assert claim["runner_evidence_complete"] is False
    assert claim["runner_verified"] is False
    assert claim["shipped"] is False
    assert claim["deployed"] is False
    assert claim["deployment_environments"] == []


def test_every_required_runner_must_be_attested_before_shipping() -> None:
    compliance = _load_compliance_module()
    result = compliance.ClaimResult(
        claim={"id": "LOT5-EXAMPLE"},
        required_families=("implementation", "api", "frontend", "tests"),
        required_runners=("node", "playwright", "pytest"),
        proofs=(),
        computed_state="static_verified",
    )
    sha = "a" * 40
    pytest_only = {
        "schema_version": 1,
        "kind": "runner",
        "commit_sha": sha,
        "runner": "pytest",
        "claims": {"LOT5-EXAMPLE": "passed"},
    }

    partial = compliance.build_report(
        [result],
        commit_sha=sha,
        runner_attestations=[pytest_only],
        deployment_attestations=[],
    )["claims"][0]

    assert partial["runner_attestations"] == ["pytest"]
    assert partial["runner_evidence_complete"] is False
    assert partial["runner_verified"] is False
    assert partial["shipped"] is False


def test_complete_local_attestations_cannot_self_promote_formal_delivery() -> None:
    compliance = _load_compliance_module()
    result = compliance.ClaimResult(
        claim={"id": "LOT5-EXAMPLE"},
        required_families=("implementation", "tests"),
        required_runners=("pytest",),
        proofs=(),
        computed_state="static_verified",
    )
    sha = "a" * 40

    report = compliance.build_report(
        [result],
        commit_sha=sha,
        runner_attestations=[
            {
                "schema_version": 1,
                "kind": "runner",
                "commit_sha": sha,
                "runner": "pytest",
                "claims": {"LOT5-EXAMPLE": "passed"},
            }
        ],
        deployment_attestations=[
            {
                "schema_version": 1,
                "kind": "deployment",
                "commit_sha": sha,
                "environment": "production",
                "claims": {"LOT5-EXAMPLE": "deployed"},
            }
        ],
    )

    claim = report["claims"][0]
    assert report["formal_promotion"] == ("disabled_without_authenticated_ci_collector")
    assert claim["runner_evidence_complete"] is True
    assert claim["runner_verified"] is False
    assert claim["attestation_trust"] == "untrusted_external"
    assert claim["deployment_evidence_environments"] == ["production"]
    assert claim["shipped"] is False
    assert claim["deployed"] is False
    assert claim["deployment_environments"] == []


def test_runner_attestation_for_another_sha_is_rejected(tmp_path: Path) -> None:
    compliance = _load_compliance_module()
    attestation = tmp_path / "runner.json"
    attestation.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "runner",
                "commit_sha": "b" * 40,
                "runner": "pytest",
                "claims": {"LOT5-EXAMPLE": "passed"},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(compliance.ComplianceError, match="does not match requested SHA"):
        compliance._load_attestations(
            [attestation],
            expected_kind="runner",
            expected_sha="a" * 40,
            claim_ids={"LOT5-EXAMPLE"},
        )


def test_requested_report_sha_must_match_the_current_ref() -> None:
    compliance = _load_compliance_module()
    current = compliance._current_git_sha(ROOT)
    assert current is not None
    other = "b" * 40 if current != "b" * 40 else "a" * 40

    with pytest.raises(compliance.ComplianceError, match="current checkout HEAD"):
        compliance.validate_requested_sha(other, ROOT)


def _clean_git_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "compliance@example.test"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Compliance Test"],
        cwd=repo,
        check=True,
    )
    (repo / "proof.txt").write_text("committed\n", encoding="utf-8")
    subprocess.run(["git", "add", "proof.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "proof"], cwd=repo, check=True)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return repo, sha


def test_sha_bound_report_rejects_dirty_or_untracked_proof_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    compliance = _load_compliance_module()
    repo, sha = _clean_git_repo(tmp_path)
    monkeypatch.delenv("CI_COMMIT_SHA", raising=False)
    assert compliance.validate_requested_sha(sha, repo) == sha

    (repo / "untracked-proof.txt").write_text("decorative\n", encoding="utf-8")
    with pytest.raises(compliance.ComplianceError, match="completely clean checkout"):
        compliance.validate_requested_sha(sha, repo)


def test_sha_bound_report_rejects_ci_metadata_that_differs_from_git_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    compliance = _load_compliance_module()
    repo, sha = _clean_git_repo(tmp_path)
    monkeypatch.setenv("CI_COMMIT_SHA", "b" * 40)

    with pytest.raises(compliance.ComplianceError, match="CI_COMMIT_SHA must match"):
        compliance.validate_requested_sha(sha, repo)


def test_sha_bound_report_rejects_ignored_or_untracked_proof_inputs(
    tmp_path: Path,
) -> None:
    compliance = _load_compliance_module()
    repo, _sha = _clean_git_repo(tmp_path)
    (repo / "config").mkdir()
    (repo / "docs").mkdir()
    (repo / "scan").mkdir()
    (repo / "config" / "manifest.json").write_text("{}\n", encoding="utf-8")
    (repo / "docs" / "matrix.md").write_text("generated\n", encoding="utf-8")
    (repo / "docs" / "mental.md").write_text("generated\n", encoding="utf-8")
    (repo / "scan" / "runtime.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "governed inputs"], cwd=repo, check=True)

    manifest = {
        "generated": {
            "matrix_path": "docs/matrix.md",
            "mental_model_path": "docs/mental.md",
        },
        "governed_docs": ["docs/mental.md"],
        "workspace_slug_branch_inventory": {
            "scan_roots": ["scan"],
            "exclude_paths": [],
            "exclude_suffixes": [],
        },
        "claims": [
            {
                "proofs": {
                    "implementation": [{"path": "proof.txt"}],
                    "api": [],
                    "frontend": [],
                    "tests": [],
                }
            }
        ],
    }
    compliance.validate_sha_bound_repository_content(
        manifest,
        repo / "config" / "manifest.json",
        repo,
    )

    (repo / "ignored").mkdir()
    (repo / "ignored" / "proof.py").write_text("DECORATIVE = True\n", encoding="utf-8")
    manifest["claims"][0]["proofs"]["implementation"] = [{"path": "ignored/proof.py"}]
    with pytest.raises(compliance.ComplianceError, match="must be tracked at HEAD"):
        compliance.validate_sha_bound_repository_content(
            manifest,
            repo / "config" / "manifest.json",
            repo,
        )


def test_vm_image_rollback_is_bound_to_the_recorded_database_revision() -> None:
    script = (ROOT / "scripts" / "deploy-vm.sh").read_text(encoding="utf-8")
    rollback = script.split("rollback_from_state() {", 1)[1].split(
        '\n}\n\nif [[ -n "$ROLLBACK_STATE" ]]', 1
    )[0]

    assert "printf 'format\\t2\\n'" in script
    assert "printf 'database_revision\\t%s\\n'" in script
    assert 'actual_database_revision="$(current_database_revision)"' in rollback
    assert '[[ "$actual_database_revision" == "$expected_database_revision" ]]' in rollback
    assert rollback.index('actual_database_revision="$(current_database_revision)"') < (
        rollback.index('docker tag "$rollback_ref" "$image_ref"')
    )


def test_generated_block_replacement_requires_unique_markers() -> None:
    compliance = _load_compliance_module()
    begin = "<!-- BEGIN GENERATED -->"
    end = "<!-- END GENERATED -->"

    assert (
        compliance.replace_generated_block(
            f"before\n{begin}\nstale\n{end}\nafter\n",
            begin,
            end,
            f"{begin}\nfresh\n{end}",
        )
        == f"before\n{begin}\nfresh\n{end}\nafter\n"
    )
    with pytest.raises(compliance.ComplianceError, match="exactly once"):
        compliance.replace_generated_block("no markers", begin, end, "replacement")


def test_plain_shipped_claims_are_forbidden_outside_generated_zone(
    tmp_path: Path,
) -> None:
    compliance = _load_compliance_module()
    document = tmp_path / "docs" / "mental-model.md"
    document.parent.mkdir(parents=True)
    begin = "<!-- BEGIN GENERATED -->"
    end = "<!-- END GENERATED -->"
    document.write_text(
        f"{begin}\nShipped from attested report only\n{end}\n"
        "This decorative mechanism is shipped.\n",
        encoding="utf-8",
    )
    manifest = {
        "generated": {
            "mental_model_path": "docs/mental-model.md",
            "mental_model_begin": begin,
            "mental_model_end": end,
        },
        "governed_docs": ["docs/mental-model.md"],
    }

    violations = compliance.lint_manual_shipped_claims(manifest, tmp_path)

    assert len(violations) == 1
    assert "docs/mental-model.md:4" in violations[0]


def _slug_inventory_fixture(tmp_path: Path) -> tuple[dict, Path]:
    source = tmp_path / "backend" / "app" / "tenant_dispatch.py"
    source.parent.mkdir(parents=True)
    (tmp_path / "frontend-ng" / "src" / "app").mkdir(parents=True)
    source.write_text(
        'def dispatch(workspace):\n    return workspace.slug == "new-tenant"\n',
        encoding="utf-8",
    )
    return (
        {
            "schema_version": 1,
            "identity_literals": ["andritz"],
            "scan_roots": ["backend/app", "frontend-ng/src/app"],
            "exclude_paths": [],
            "exclude_suffixes": [".spec.ts"],
            "entries": [],
        },
        source,
    )


def test_new_workspace_slug_branch_requires_versioned_debt_entry(
    tmp_path: Path,
) -> None:
    compliance = _load_compliance_module()
    inventory, _source = _slug_inventory_fixture(tmp_path)

    with pytest.raises(compliance.ComplianceError, match="inventory drift"):
        compliance.validate_workspace_slug_branch_inventory(inventory, tmp_path)

    inventory["entries"] = [
        {
            "path": "backend/app/tenant_dispatch.py",
            "expression": 'workspace.slug == "new-tenant"',
            "occurrences": 1,
            "category": "runtime_legacy",
            "reason": "Explicitly reviewed compatibility debt.",
        }
    ]
    compliance.validate_workspace_slug_branch_inventory(inventory, tmp_path)

    frontend_source = tmp_path / "frontend-ng" / "src" / "app" / "tenant-dispatch.ts"
    frontend_source.write_text(
        "return input.workspace.slug === 'another-new-tenant';\n",
        encoding="utf-8",
    )
    with pytest.raises(compliance.ComplianceError, match="inventory drift"):
        compliance.validate_workspace_slug_branch_inventory(inventory, tmp_path)

    inventory["entries"].append(
        {
            "path": "frontend-ng/src/app/tenant-dispatch.ts",
            "expression": "return input.workspace.slug === 'another-new-tenant';",
            "occurrences": 1,
            "category": "resolver_contract",
            "reason": "Explicitly reviewed resolver debt.",
        }
    )
    compliance.validate_workspace_slug_branch_inventory(inventory, tmp_path)


def test_stale_workspace_slug_branch_inventory_entry_fails(
    tmp_path: Path,
) -> None:
    compliance = _load_compliance_module()
    inventory, source = _slug_inventory_fixture(tmp_path)
    inventory["entries"] = [
        {
            "path": "backend/app/tenant_dispatch.py",
            "expression": 'workspace.slug == "new-tenant"',
            "occurrences": 1,
            "category": "runtime_legacy",
            "reason": "Explicitly reviewed compatibility debt.",
        }
    ]
    source.write_text("def dispatch(workspace):\n    return None\n", encoding="utf-8")

    with pytest.raises(compliance.ComplianceError, match="discovered=0, declared=1"):
        compliance.validate_workspace_slug_branch_inventory(inventory, tmp_path)
