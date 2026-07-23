#!/usr/bin/env python3
"""Create and verify the content-free Agentium Release A diff manifest.

Release A is the one-time safety adoption built directly on the production
commit.  This gate binds the exact commits, blob IDs and patch digests while
never copying source contents or business data into the manifest.

The allowlist is intentionally embedded and versioned.  Adding one path is a
policy change requiring review and a profile bump; an unknown path fails
closed.  Every exact patch must also be approved in a private review-policy
file supplied outside the candidate Git tree.  Application patches are parsed
and checked for known Lots 7--9 product structures before approval is accepted.
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

LIVE_BASE_SHA = "a8c790ade6b65859b53649b9bbf0c81a370d1856"
PROFILE = "agentium-release-a-diff-manifest-v7"
VERIFICATION_PROFILE = "agentium-release-a-diff-verification-v7"
REVIEW_PROFILE = "agentium-release-a-semantic-review-v1"
MAX_MANIFEST_BYTES = 128 * 1024
MAX_CLOCK_SKEW = timedelta(minutes=5)

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_UTC_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)
_SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9_.@+-]+(?:/[A-Za-z0-9_.@+-]+)*$")

_MANIFEST_KEYS = {
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

_REVIEW_KEYS = {
    "profile",
    "base_sha",
    "release_a_sha",
    "approval",
    "reviewer",
    "review_ticket",
    "reviewed_at",
    "files",
    "review_sha256",
}
_REVIEW_FILE_KEYS = {
    "path",
    "status",
    "base_mode",
    "release_mode",
    "base_blob",
    "release_blob",
    "patch_sha256",
    "classification",
    "hardening_controls",
}
_INVENTORY_KEYS = {
    "path",
    "status",
    "base_mode",
    "release_mode",
    "base_blob",
    "release_blob",
    "patch_sha256",
}

# Runtime and operator tooling permitted in the safety-only Release A.  This is
# an exact list, not a prefix rule: a new helper cannot enter A without changing
# this reviewed checker and its policy fingerprint.
_ALLOWED_PATHS = frozenset(
    {
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
        "backend/app/tests/api/test_secure_deposit_api.py",
        "backend/app/tests/infra/test_agentium_release_a_attestation.py",
        "backend/app/tests/infra/test_agentium_release_a_evidence_bundle.py",
        "backend/app/tests/infra/test_agentium_release_a_executor.py",
        "backend/app/tests/infra/test_agentium_release_a_manifest.py",
        "backend/app/tests/infra/test_agentium_release_a_preconditions.py",
        "backend/app/tests/infra/test_agentium_release_a_sftp_identity_invalidation.py",
        "backend/app/tests/infra/test_agentium_release_a_storage_contract.py",
        "backend/app/tests/infra/test_agentium_release_a_sftp_positive_canary.py",
        "backend/app/tests/infra/test_agentium_protected_runner_orchestrator.py",
        "backend/app/tests/infra/test_agentium_protected_runner_sftp_acceptance.py",
        "backend/app/tests/infra/test_agentium_compliance_contract.py",
        "backend/app/tests/infra/test_image_provenance_contract.py",
        "backend/app/tests/infra/test_agentium_runtime_env_bundle.py",
        "backend/app/tests/infra/test_agentium_safe_canaries.py",
        "backend/app/tests/infra/test_agentium_safe_validation.py",
        "backend/app/tests/infra/test_agentium_storage_attestation.py",
        "backend/app/tests/infra/test_agentium_terminal_gate_authorization.py",
        "backend/app/tests/infra/test_deploy_vm_env_isolation.py",
        "backend/app/tests/infra/test_nginx_security_contract.py",
        "backend/app/tests/infra/test_qdrant_safe_deploy_contract.py",
        "backend/app/tests/infra/test_safe_vm_deploy_contract.py",
        "backend/app/tests/infra/test_startup_reconciliation_guard.py",
        "backend/app/tests/infra/test_systemd_effective_environment_contract.py",
        "backend/app/tests/scripts/test_audit_livekit_quiescence.py",
        "backend/app/tests/scripts/test_audit_persisted_system_bindings.py",
        "backend/app/tests/scripts/test_audit_post_canary_database.py",
        "backend/app/tests/scripts/test_audit_qdrant_write_barrier.py",
        "backend/app/tests/scripts/test_audit_safe_chat_run.py",
        "backend/app/tests/scripts/test_audit_sftp_deploy_boundary.py",
        "backend/app/tests/services/test_secure_deposit.py",
        "backend/scripts/audit_livekit_quiescence.py",
        "backend/scripts/audit_persisted_system_bindings.py",
        "backend/scripts/audit_post_canary_database.py",
        "backend/scripts/audit_qdrant_write_barrier.py",
        "backend/scripts/audit_safe_chat_run.py",
        "backend/scripts/audit_sftp_deploy_boundary.py",
        "config/agentium/release-a-evidence-authorities.v1.json",
        "config/agentium/product-compliance.v1.json",
        "deploy/agentium-backend.service",
        "deploy/install-backend-service.sh",
        "deploy/nginx/agentium-container-backend.conf",
        "deploy/nginx/agentium-container-frontend.conf",
        "deploy/nginx/agentium-deploy-maintenance.conf",
        "deploy/nginx/agentium.conf",
        "docker/compose.agentium.opened.yml",
        "docker/compose.agentium.qdrant-barrier.yml",
        "docker/compose.agentium.audit-readonly.yml",
        "docker/compose.agentium.yml",
        "docker/env/agentium.env.example",
        "docker/env/qdrant.agentium.env.example",
        "docs/dev-deploy-policy.md",
        "docs/ops/agentium-release-a-b-git-plan-2026-07-22.md",
        "docs/ops/agentium-safe-vm-deployment.md",
        "frontend-ng/e2e/tests/09-live-workspace-contract.spec.ts",
        "frontend-ng/e2e/tests/11-system360-canary.spec.ts",
        "frontend-ng/e2e/tests/12-protected-runner-canaries.spec.ts",
        "frontend-ng/playwright.config.ts",
        "scripts/agentium-maintenance-gate.sh",
        "scripts/agentium_andritz_proof.py",
        "scripts/agentium_protected_runner_orchestrator.py",
        "scripts/agentium_protected_runner_sftp_acceptance.py",
        "scripts/agentium_release_a_attestation.py",
        "scripts/agentium_release_a_evidence_bundle.py",
        "scripts/agentium_release_a_manifest.py",
        "scripts/agentium_release_a_preconditions.py",
        "scripts/agentium_release_a_storage_contract.py",
        "scripts/agentium_release_a_sftp_positive_canary.py",
        "scripts/agentium_runtime_env_bundle.py",
        "scripts/agentium_safe_validation.py",
        "scripts/agentium_storage_attestation.py",
        "scripts/agentium_tenant_proof.py",
        "scripts/agentium_vm_fallback_attestation.py",
        "scripts/deploy-agentium-safe.sh",
        "scripts/deploy-agentium-release-a-safe.sh",
        "scripts/deploy-vm.sh",
        "scripts/run-agentium-safe-canaries.sh",
    }
)

# Existing entries are immutable policy history.  A changed allowlist must use
# a new manifest profile and add a new reviewed digest instead of rewriting an
# existing profile's meaning.
_ALLOWLIST_SHA256_BY_PROFILE = {
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

# Application files are exceptional in Release A.  They can only carry one of
# these narrowly reviewed hardening controls, and every exact blob/patch must
# be approved in an owner-only review file supplied independently of Git.
_APP_HARDENING_CONTROLS = {
    "backend/app/api/v1/endpoints/secure_deposit.py": frozenset(
        {"sftp_canary_retry_safe_audit"}
    ),
    "backend/app/api/v1/endpoints/settings.py": frozenset({"non_mutating_read_path"}),
    "backend/app/core/config.py": frozenset(
        {"immutable_runtime_environment", "startup_reconciliation_gate"}
    ),
    "backend/app/core/settings_manager.py": frozenset({"non_mutating_read_path"}),
    "backend/app/main.py": frozenset({"startup_reconciliation_gate"}),
    "backend/app/services/livekit_service.py": frozenset(
        {"authenticated_runtime_inventory"}
    ),
    "backend/app/services/rag_preset_service.py": frozenset({"non_mutating_read_path"}),
    "backend/app/services/secure_deposit.py": frozenset(
        {"sftp_canary_retry_safe_audit"}
    ),
    "backend/app/services/secure_deposit_sftp.py": frozenset(
        {"sftp_canary_retry_safe_audit"}
    ),
    "backend/app/services/settings_service.py": frozenset({"non_mutating_read_path"}),
}
_NON_APP_CLASSIFICATIONS = frozenset(
    {
        "deployment_orchestration",
        "operator_documentation",
        "runtime_configuration",
        "security_boundary",
        "verification_test",
    }
)
_FORBIDDEN_APP_PRODUCT_PATTERNS = (
    re.compile(r"authorization_v2_trusted_[A-Za-z0-9_]*", re.IGNORECASE),
    re.compile(r"authorization[_ -]?v2", re.IGNORECASE),
    re.compile(r"system[_ -]?catalog", re.IGNORECASE),
    re.compile(r"workspace[_ -]?apps?", re.IGNORECASE),
    re.compile(r"app[_ -]?platform", re.IGNORECASE),
    re.compile(r"decision[_ -]?scenarios?", re.IGNORECASE),
    re.compile(r"system[_ -]?360", re.IGNORECASE),
    re.compile(r"skill[_ -]?invocations?", re.IGNORECASE),
)
_FORBIDDEN_APP_STRUCTURES = (
    # The audited Release A application delta adds no decorators.  Rejecting
    # every added decorator line is deliberately stronger than recognizing a
    # set of router names: imports, aliases, dotted routers and whitespace
    # cannot turn a product route into an allowed spelling.
    re.compile(r"(?m)^\s*@"),
    re.compile(r"\b__tablename__\s*="),
    re.compile(r"\b(?:mapped_column|Column)\s*\("),
)

# These non-application files are shared with later product work in the local
# checkout.  Review of an exact patch remains mandatory, but the manifest also
# rejects the known cross-release structures so that a broad file copy cannot
# accidentally turn Release A into a product release.
_FORBIDDEN_NON_APP_ADDITIONS = {
    "docker/env/agentium.env.example": (
        re.compile(r"\bAUTHORIZATION_V2_[A-Z0-9_]+\b", re.IGNORECASE),
    ),
    "frontend-ng/e2e/tests/09-live-workspace-contract.spec.ts": (
        re.compile(r"/governance/workspace-apps/installations", re.IGNORECASE),
        re.compile(r"/knowledge/interventions", re.IGNORECASE),
        re.compile(r"\bfse(?:[-_A-Za-z0-9]*)?\b", re.IGNORECASE),
        re.compile(r"\binstalledAppIds\b"),
        re.compile(
            r"\bandritz\.(?:chat|client360-pdr|knowledge-capture)\b",
            re.IGNORECASE,
        ),
        re.compile(r"\b(?:four|4)[ -]surface", re.IGNORECASE),
        re.compile(r"\btoHaveCount\s*\(\s*4\s*\)"),
        re.compile(r"\btoHaveLength\s*\(\s*6\s*\)"),
    ),
}
_REQUIRED_NON_APP_SOURCE_PATTERNS = {
    "frontend-ng/e2e/tests/09-live-workspace-contract.spec.ts": (
        re.compile(r"\bE2E_EXPECTED_SHA\b"),
        re.compile(r"\bE2E_SAFE_CONTENT_FREE\b"),
        re.compile(r"\btype\s+WorkspaceTarget\b"),
        re.compile(r"\bclient360DryRunProjection\b"),
        re.compile(r"\bcrossTenantSystemIsolationProjection\b"),
        re.compile(r"\btoHaveCount\s*\(\s*3\s*\)"),
        re.compile(
            r"primary_surfaces\s*:\s*\[\s*['\"]chat['\"]\s*,\s*"
            r"['\"]client360-pdr['\"]\s*,\s*['\"]knowledge-capture['\"]\s*\]"
        ),
        re.compile(r"\bactiveSystems\)\.toHaveLength\s*\(\s*5\s*\)"),
    ),
}

_PRODUCT_COMPLIANCE_PATH = "config/agentium/product-compliance.v1.json"
_BASE_ROLLBACK_CLAIM = {
    "label": "Database-aware immutable image rollback",
    "path": "scripts/deploy-vm.sh",
    "contains": [
        "printf 'format\\t2\\n'",
        "printf 'database_revision\\t%s\\n'",
        'actual_database_revision="$(current_database_revision)"',
        "Rollback images refusé",
    ],
}
_RELEASE_A_ROLLBACK_CLAIM = {
    "label": "Database-aware immutable image rollback",
    "path": "scripts/deploy-vm.sh",
    "contains": [
        "printf 'format\\t3\\n'",
        "printf 'database_revision\\t%s\\n'",
        'actual_database_revision="$(current_database_revision)"',
        "Rollback images refusé",
        'ensure_rollback_image_override "$state_file"',
    ],
}

_DENIED_EXACT_PATHS = frozenset(
    {
        "backend/app/services/system_catalog_bindings.py",
        "backend/app/services/workspace_blueprints.py",
    }
)
_DENIED_PREFIXES = (
    "backend/alembic/versions/",
    "frontend-ng/src/app/",
    "docs/demo-runs/",
    "docs/pih/",
    "docs/render/",
)
_DENIED_NAME_TOKENS = frozenset({"backfill", "bootstrap", "seed"})
_DENIED_SUFFIXES = (
    ".db",
    ".dump",
    ".gz",
    ".key",
    ".p12",
    ".pem",
    ".pfx",
    ".sqlite",
    ".sql",
    ".tar",
    ".tgz",
    ".zip",
)


class ReleaseAManifestError(RuntimeError):
    """The Release A commit range or its manifest violates the safety policy."""


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReleaseAManifestError("value is not canonical JSON") from exc


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _assert_allowlist_profile_contract(
    *,
    profile: str | None = None,
    allowed_paths: frozenset[str] | None = None,
) -> str:
    """Bind one exact allowlist to one immutable, explicitly bumped profile."""

    selected_profile = PROFILE if profile is None else profile
    selected_paths = _ALLOWED_PATHS if allowed_paths is None else allowed_paths
    expected = _ALLOWLIST_SHA256_BY_PROFILE.get(selected_profile)
    if expected is None:
        raise ReleaseAManifestError(
            "Release A allowlist profile is unknown; an explicit profile bump is required"
        )
    actual = _sha256(_canonical_json(sorted(selected_paths)))
    if actual != expected:
        raise ReleaseAManifestError(
            "Release A allowlist changed without an explicit profile bump"
        )
    expected_verification_profile = selected_profile.replace(
        "-diff-manifest-", "-diff-verification-", 1
    )
    if selected_profile == PROFILE and VERIFICATION_PROFILE != expected_verification_profile:
        raise ReleaseAManifestError(
            "Release A verification profile must be bumped with the manifest profile"
        )
    return actual


ALLOWED_PATHS_SHA256 = _assert_allowlist_profile_contract()


def _utc_text(value: datetime) -> str:
    rendered = value.astimezone(UTC).replace(microsecond=0).isoformat()
    return rendered.replace("+00:00", "Z")


def _timestamp(value: Any, *, path: str) -> datetime:
    if not isinstance(value, str) or _UTC_TIMESTAMP_RE.fullmatch(value) is None:
        raise ReleaseAManifestError(
            f"{path} must be an ISO-8601 UTC timestamp ending in Z"
        )
    try:
        return datetime.fromisoformat(value.removesuffix("Z") + "+00:00").astimezone(
            UTC
        )
    except ValueError as exc:
        raise ReleaseAManifestError(f"{path} is not a valid timestamp") from exc


def _git_sha(value: Any, *, path: str) -> str:
    if not isinstance(value, str) or _GIT_SHA_RE.fullmatch(value) is None:
        raise ReleaseAManifestError(f"{path} must be a lowercase 40-character Git SHA")
    return value


def _digest(value: Any, *, path: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ReleaseAManifestError(f"{path} must be a lowercase SHA-256 digest")
    return value


def _policy_payload() -> dict[str, Any]:
    """Return the canonical, non-candidate-controlled policy description."""

    def regex_contract(pattern: re.Pattern[str]) -> dict[str, Any]:
        return {"pattern": pattern.pattern, "flags": pattern.flags}

    return {
        "profile": PROFILE,
        "allowed_paths": sorted(_ALLOWED_PATHS),
        "allowed_paths_sha256": ALLOWED_PATHS_SHA256,
        "docs_rule": "docs/ops/*.md (one level, regular file)",
        "denied_exact_paths": sorted(_DENIED_EXACT_PATHS),
        "denied_prefixes": list(_DENIED_PREFIXES),
        "denied_name_tokens": sorted(_DENIED_NAME_TOKENS),
        "denied_suffixes": list(_DENIED_SUFFIXES),
        "allowed_statuses": ["A", "M"],
        "allowed_modes": ["100644", "100755"],
        "semantic_review_required": True,
        "review_profile": REVIEW_PROFILE,
        "app_hardening_controls": {
            path: sorted(controls)
            for path, controls in sorted(_APP_HARDENING_CONTROLS.items())
        },
        "non_app_classifications": sorted(_NON_APP_CLASSIFICATIONS),
        "forbidden_app_product_patterns": [
            regex_contract(pattern) for pattern in _FORBIDDEN_APP_PRODUCT_PATTERNS
        ],
        "forbidden_app_structures": [
            regex_contract(pattern) for pattern in _FORBIDDEN_APP_STRUCTURES
        ],
        "forbidden_non_app_additions": {
            path: [regex_contract(pattern) for pattern in patterns]
            for path, patterns in sorted(_FORBIDDEN_NON_APP_ADDITIONS.items())
        },
        "required_non_app_source_patterns": {
            path: [regex_contract(pattern) for pattern in patterns]
            for path, patterns in sorted(_REQUIRED_NON_APP_SOURCE_PATTERNS.items())
        },
        "product_compliance_release_a_contract": {
            "path": _PRODUCT_COMPLIANCE_PATH,
            "base_claim": _BASE_ROLLBACK_CLAIM,
            "release_a_claim": _RELEASE_A_ROLLBACK_CLAIM,
        },
    }


POLICY_SHA256 = _sha256(_canonical_json(_policy_payload()))


def _run_git(repository: Path, arguments: Sequence[str]) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise ReleaseAManifestError("git is unavailable") from exc
    if completed.returncode != 0:
        error = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ReleaseAManifestError(f"git {' '.join(arguments[:2])} failed: {error}")
    return completed.stdout


def _repository(value: Path | str) -> Path:
    candidate = Path(value).expanduser().resolve()
    if not candidate.is_dir():
        raise ReleaseAManifestError("repository must be an existing directory")
    top_level = _run_git(candidate, ("rev-parse", "--show-toplevel"))
    try:
        resolved_top_level = Path(top_level.decode("utf-8").strip()).resolve()
    except UnicodeDecodeError as exc:
        raise ReleaseAManifestError("repository path is not valid UTF-8") from exc
    if resolved_top_level != candidate:
        raise ReleaseAManifestError("repository must be the exact Git worktree root")
    return candidate


def _resolve_commit(repository: Path, sha: str, *, path: str) -> str:
    expected = _git_sha(sha, path=path)
    resolved = _run_git(repository, ("rev-parse", "--verify", f"{expected}^{{commit}}"))
    actual = resolved.decode("ascii", errors="strict").strip()
    if actual != expected:
        raise ReleaseAManifestError(f"{path} did not resolve to the exact commit")
    return actual


def _assert_ancestry(repository: Path, release_a_sha: str) -> None:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "merge-base",
            "--is-ancestor",
            LIVE_BASE_SHA,
            release_a_sha,
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    if completed.returncode == 1:
        raise ReleaseAManifestError(
            "Release A must descend from the fixed live base SHA"
        )
    if completed.returncode != 0:
        error = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ReleaseAManifestError(f"Git ancestry check failed: {error}")
    if release_a_sha == LIVE_BASE_SHA:
        raise ReleaseAManifestError(
            "Release A must differ from the fixed live base SHA"
        )


def _safe_path(value: bytes) -> str:
    try:
        path = value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseAManifestError("changed paths must be valid UTF-8") from exc
    if (
        not path
        or path.startswith("/")
        or "\\" in path
        or PurePosixPath(path).is_absolute()
        or ".." in PurePosixPath(path).parts
        or _SAFE_PATH_RE.fullmatch(path) is None
    ):
        raise ReleaseAManifestError(
            "changed path is not a safe canonical repository path"
        )
    return path


def _path_policy_error(path: str) -> str | None:
    lower = path.lower()
    basename = PurePosixPath(lower).name
    if path in _DENIED_EXACT_PATHS:
        return "explicitly denied business service"
    if any(path.startswith(prefix) for prefix in _DENIED_PREFIXES):
        return "denied business, migration, asset or demo family"
    if any(token in lower for token in _DENIED_NAME_TOKENS):
        return "seed, backfill or bootstrap changes are forbidden"
    if (
        basename == ".env"
        or basename.endswith(".env")
        or (".env." in basename and not basename.endswith(".env.example"))
    ):
        return "runtime environment files are forbidden"
    if lower.endswith(_DENIED_SUFFIXES):
        return "secret, archive, dump or database artifact is forbidden"

    if path in _ALLOWED_PATHS:
        return None
    pure = PurePosixPath(path)
    if (
        len(pure.parts) == 3
        and pure.parts[:2] == ("docs", "ops")
        and pure.suffix == ".md"
    ):
        return None
    return "path is outside the exact Release A infrastructure allowlist"


def _tree_entry(
    repository: Path,
    commit_sha: str,
    path: str,
    *,
    required: bool,
) -> dict[str, str] | None:
    raw = _run_git(repository, ("ls-tree", "-z", commit_sha, "--", path))
    rows = [row for row in raw.split(b"\0") if row]
    if not rows and not required:
        return None
    if len(rows) != 1:
        raise ReleaseAManifestError(f"{path}: expected one committed tree entry")
    metadata, separator, encoded_path = rows[0].partition(b"\t")
    if not separator or _safe_path(encoded_path) != path:
        raise ReleaseAManifestError(f"{path}: malformed committed tree entry")
    parts = metadata.split(b" ")
    if len(parts) != 3:
        raise ReleaseAManifestError(f"{path}: malformed committed tree metadata")
    mode, object_type, object_id = parts
    if object_type != b"blob" or mode not in {b"100644", b"100755"}:
        raise ReleaseAManifestError(f"{path}: only regular committed files are allowed")
    blob = object_id.decode("ascii", errors="strict")
    if _GIT_SHA_RE.fullmatch(blob) is None:
        raise ReleaseAManifestError(f"{path}: committed blob ID is invalid")
    return {"mode": mode.decode("ascii"), "blob": blob}


def _patch(repository: Path, release_a_sha: str, path: str, *, unified: int) -> bytes:
    return _run_git(
        repository,
        (
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--full-index",
            "--binary",
            f"--unified={unified}",
            LIVE_BASE_SHA,
            release_a_sha,
            "--",
            path,
        ),
    )


def _assert_app_semantics(repository: Path, release_a_sha: str, path: str) -> None:
    """Reject known product work and product-shaped structures in app patches."""

    if path not in _APP_HARDENING_CONTROLS:
        return
    source = _run_git(repository, ("show", f"{release_a_sha}:{path}"))
    try:
        decoded_source = source.decode("utf-8")
        ast.parse(decoded_source, filename=path)
        patch_text = _patch(repository, release_a_sha, path, unified=0).decode("utf-8")
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise ReleaseAManifestError(
            f"{path}: reviewed application changes must be valid UTF-8 Python"
        ) from exc

    added_lines = "\n".join(
        line[1:]
        for line in patch_text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    for pattern in _FORBIDDEN_APP_PRODUCT_PATTERNS:
        if match := pattern.search(added_lines):
            raise ReleaseAManifestError(
                f"{path}: product token {match.group(0)!r} is forbidden in Release A"
            )
    for pattern in _FORBIDDEN_APP_STRUCTURES:
        if pattern.search(added_lines):
            raise ReleaseAManifestError(
                f"{path}: new product route or persistence structure is forbidden in Release A"
            )


def _assert_non_app_semantics(repository: Path, release_a_sha: str, path: str) -> None:
    """Reject known Release B structures in shared non-application files."""

    forbidden = _FORBIDDEN_NON_APP_ADDITIONS.get(path, ())
    required = _REQUIRED_NON_APP_SOURCE_PATTERNS.get(path, ())
    if not forbidden and not required:
        return
    try:
        source = _run_git(repository, ("show", f"{release_a_sha}:{path}")).decode(
            "utf-8"
        )
        patch_text = _patch(repository, release_a_sha, path, unified=0).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseAManifestError(
            f"{path}: reviewed shared-file changes must be valid UTF-8"
        ) from exc
    added_lines = "\n".join(
        line[1:]
        for line in patch_text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    for pattern in forbidden:
        if match := pattern.search(added_lines):
            raise ReleaseAManifestError(
                f"{path}: Release B addition {match.group(0)!r} is forbidden in Release A"
            )
    for pattern in required:
        if pattern.search(source) is None:
            raise ReleaseAManifestError(
                f"{path}: required Release A safety invariant {pattern.pattern!r} is absent"
            )


def _strict_json_document(raw: bytes, *, path: str) -> Any:
    """Decode committed JSON while rejecting duplicate object keys."""

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ReleaseAManifestError(
                    f"{path}: duplicate JSON object key is forbidden"
                )
            result[key] = value
        return result

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseAManifestError(
            f"{path}: committed compliance manifest must be valid UTF-8 JSON"
        ) from exc


def _matching_value_paths(
    value: Any,
    expected: Any,
    current: tuple[str | int, ...] = (),
) -> list[tuple[str | int, ...]]:
    matches = [current] if value == expected else []
    if isinstance(value, Mapping):
        for key, child in value.items():
            matches.extend(_matching_value_paths(child, expected, (*current, key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            matches.extend(_matching_value_paths(child, expected, (*current, index)))
    return matches


def _replace_value_at_path(
    document: Any,
    path: Sequence[str | int],
    replacement: Any,
) -> None:
    parent = document
    for component in path[:-1]:
        parent = parent[component]
    parent[path[-1]] = replacement


def _assert_product_compliance_semantics(
    repository: Path,
    release_a_sha: str,
    path: str,
) -> None:
    """Permit exactly the rollback format-2 to format-3 claim update in A."""

    if path != _PRODUCT_COMPLIANCE_PATH:
        return
    base = _strict_json_document(
        _run_git(repository, ("show", f"{LIVE_BASE_SHA}:{path}")),
        path=path,
    )
    candidate = _strict_json_document(
        _run_git(repository, ("show", f"{release_a_sha}:{path}")),
        path=path,
    )
    base_paths = _matching_value_paths(base, _BASE_ROLLBACK_CLAIM)
    candidate_paths = _matching_value_paths(candidate, _RELEASE_A_ROLLBACK_CLAIM)
    if len(base_paths) != 1:
        raise ReleaseAManifestError(
            f"{path}: fixed live base must contain exactly one rollback format-2 claim"
        )
    if len(candidate_paths) != 1 or candidate_paths[0] != base_paths[0]:
        raise ReleaseAManifestError(
            f"{path}: Release A must contain exactly one rollback format-3 claim at the original location"
        )
    expected_candidate = copy.deepcopy(base)
    _replace_value_at_path(
        expected_candidate,
        base_paths[0],
        copy.deepcopy(_RELEASE_A_ROLLBACK_CLAIM),
    )
    # Python considers ``True == 1 == 1.0``.  Canonical JSON comparison keeps
    # those JSON types distinct while intentionally ignoring whitespace and
    # object-key ordering.
    if _canonical_json(candidate) != _canonical_json(expected_candidate):
        raise ReleaseAManifestError(
            f"{path}: only the exact rollback format-3 claim replacement is allowed in Release A"
        )


def _diff_inventory(repository: Path, release_a_sha: str) -> list[dict[str, Any]]:
    raw = _run_git(
        repository,
        (
            "diff",
            "--name-status",
            "-z",
            "--find-renames=100%",
            LIVE_BASE_SHA,
            release_a_sha,
            "--",
        ),
    )
    tokens = raw.split(b"\0")
    if tokens and tokens[-1] == b"":
        tokens.pop()
    inventory: list[dict[str, Any]] = []
    index = 0
    while index < len(tokens):
        try:
            status = tokens[index].decode("ascii")
        except UnicodeDecodeError as exc:
            raise ReleaseAManifestError("Git diff status is not ASCII") from exc
        index += 1
        if index >= len(tokens):
            raise ReleaseAManifestError("Git diff name-status output is truncated")
        path = _safe_path(tokens[index])
        index += 1
        if status.startswith(("R", "C")):
            if index >= len(tokens):
                raise ReleaseAManifestError("Git rename/copy output is truncated")
            _safe_path(tokens[index])
            raise ReleaseAManifestError("renames and copies are forbidden in Release A")
        if status not in {"A", "M"}:
            raise ReleaseAManifestError(
                f"{path}: status {status!r} is forbidden; only additions and modifications are allowed"
            )
        error = _path_policy_error(path)
        if error is not None:
            raise ReleaseAManifestError(f"{path}: {error}")
        base_entry = _tree_entry(
            repository,
            LIVE_BASE_SHA,
            path,
            required=status == "M",
        )
        release_entry = _tree_entry(repository, release_a_sha, path, required=True)
        assert release_entry is not None
        _assert_app_semantics(repository, release_a_sha, path)
        _assert_non_app_semantics(repository, release_a_sha, path)
        _assert_product_compliance_semantics(repository, release_a_sha, path)
        inventory.append(
            {
                "status": status,
                "path": path,
                "base_mode": base_entry["mode"] if base_entry else None,
                "release_mode": release_entry["mode"],
                "base_blob": base_entry["blob"] if base_entry else None,
                "release_blob": release_entry["blob"],
                "patch_sha256": _sha256(
                    _patch(repository, release_a_sha, path, unified=3)
                ),
            }
        )
    if not inventory:
        raise ReleaseAManifestError("Release A has an empty diff")
    return sorted(inventory, key=lambda row: (row["path"], row["status"]))


def _review_policy_digest(payload: Mapping[str, Any]) -> str:
    body = {key: payload[key] for key in _REVIEW_KEYS if key != "review_sha256"}
    return _sha256(_canonical_json(body))


def _verify_review_policy(
    payload: Any,
    inventory: Sequence[Mapping[str, Any]],
    release_a_sha: str,
    *,
    now: datetime,
) -> str:
    """Validate an external, exact-blob semantic approval for the Git range."""

    if not isinstance(payload, Mapping) or set(payload) != _REVIEW_KEYS:
        raise ReleaseAManifestError("semantic review policy has an invalid field set")
    if payload["profile"] != REVIEW_PROFILE:
        raise ReleaseAManifestError("semantic review policy profile is invalid")
    if _git_sha(payload["base_sha"], path="review.base_sha") != LIVE_BASE_SHA:
        raise ReleaseAManifestError(
            "semantic review base differs from the fixed live base"
        )
    if _git_sha(payload["release_a_sha"], path="review.release_a_sha") != release_a_sha:
        raise ReleaseAManifestError("semantic review is not bound to the Release A SHA")
    if payload["approval"] != "approved":
        raise ReleaseAManifestError("semantic review approval must be explicit")
    reviewer = payload["reviewer"]
    if (
        not isinstance(reviewer, str)
        or not 3 <= len(reviewer) <= 160
        or reviewer.strip() != reviewer
        or not any(character.isalnum() for character in reviewer)
    ):
        raise ReleaseAManifestError("semantic review reviewer is invalid")
    ticket = payload["review_ticket"]
    if (
        not isinstance(ticket, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{2,159}", ticket) is None
    ):
        raise ReleaseAManifestError("semantic review ticket is invalid")
    reviewed_at = _timestamp(payload["reviewed_at"], path="review.reviewed_at")
    if reviewed_at > now.astimezone(UTC) + MAX_CLOCK_SKEW:
        raise ReleaseAManifestError(
            "semantic review timestamp is too far in the future"
        )

    review_files = payload["files"]
    if not isinstance(review_files, list) or len(review_files) != len(inventory):
        raise ReleaseAManifestError(
            "semantic review must cover every changed file exactly"
        )
    normalized: list[dict[str, Any]] = []
    for index, (reviewed, expected) in enumerate(
        zip(review_files, inventory, strict=True)
    ):
        if not isinstance(reviewed, Mapping) or set(reviewed) != _REVIEW_FILE_KEYS:
            raise ReleaseAManifestError(
                f"semantic review file {index} has an invalid field set"
            )
        for key in _INVENTORY_KEYS:
            if reviewed[key] != expected[key]:
                raise ReleaseAManifestError(
                    f"semantic review file {index}.{key} differs from the exact Git inventory"
                )
        path = expected["path"]
        classification = reviewed["classification"]
        controls = reviewed["hardening_controls"]
        if (
            not isinstance(controls, list)
            or not controls
            or not all(isinstance(control, str) for control in controls)
            or controls != sorted(set(controls))
        ):
            raise ReleaseAManifestError(
                f"semantic review for {path} must declare sorted unique hardening controls"
            )
        if path in _APP_HARDENING_CONTROLS:
            if classification != "runtime_safety_hardening":
                raise ReleaseAManifestError(
                    f"semantic review for {path} must classify application code as runtime safety hardening"
                )
            unknown = set(controls) - _APP_HARDENING_CONTROLS[path]
            if unknown:
                raise ReleaseAManifestError(
                    f"semantic review for {path} contains an unauthorized hardening control"
                )
            if set(controls) != _APP_HARDENING_CONTROLS[path]:
                raise ReleaseAManifestError(
                    f"semantic review for {path} must declare every required hardening control"
                )
        else:
            if classification not in _NON_APP_CLASSIFICATIONS:
                raise ReleaseAManifestError(
                    f"semantic review for {path} has an unauthorized classification"
                )
            if controls != ["reviewed_exact_patch"]:
                raise ReleaseAManifestError(
                    f"semantic review for {path} must bind the reviewed exact patch"
                )
        normalized.append(dict(reviewed))
    if normalized != review_files:
        raise ReleaseAManifestError(
            "semantic review files must use canonical JSON objects"
        )

    review_digest = _digest(payload["review_sha256"], path="review.review_sha256")
    if _review_policy_digest(payload) != review_digest:
        raise ReleaseAManifestError("semantic review self-checksum mismatch")
    return review_digest


def build_review_template(
    repository: Path | str,
    release_a_sha: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a deliberately non-approved, content-free semantic review draft."""

    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise ReleaseAManifestError("now must include a timezone")
    repo = _repository(repository)
    _resolve_commit(repo, LIVE_BASE_SHA, path="fixed live base SHA")
    release = _resolve_commit(repo, release_a_sha, path="Release A SHA")
    _assert_ancestry(repo, release)
    inventory = _diff_inventory(repo, release)
    files = []
    for row in inventory:
        is_app = row["path"] in _APP_HARDENING_CONTROLS
        files.append(
            {
                **row,
                "classification": (
                    "runtime_safety_hardening" if is_app else "PENDING_REVIEW"
                ),
                "hardening_controls": [] if is_app else ["reviewed_exact_patch"],
            }
        )
    draft: dict[str, Any] = {
        "profile": REVIEW_PROFILE,
        "base_sha": LIVE_BASE_SHA,
        "release_a_sha": release,
        "approval": "pending",
        "reviewer": "PENDING_REVIEW",
        "review_ticket": "PENDING_REVIEW",
        "reviewed_at": _utc_text(current),
        "files": files,
    }
    return {**draft, "review_sha256": _review_policy_digest(draft)}


def seal_review_policy(
    payload: Any,
    repository: Path | str,
    release_a_sha: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Seal an explicitly edited review draft against the exact committed range."""

    if not isinstance(payload, Mapping) or set(payload) != _REVIEW_KEYS:
        raise ReleaseAManifestError("semantic review draft has an invalid field set")
    candidate = dict(payload)
    candidate["review_sha256"] = _review_policy_digest(candidate)
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise ReleaseAManifestError("now must include a timezone")
    repo = _repository(repository)
    _resolve_commit(repo, LIVE_BASE_SHA, path="fixed live base SHA")
    release = _resolve_commit(repo, release_a_sha, path="Release A SHA")
    _assert_ancestry(repo, release)
    inventory = _diff_inventory(repo, release)
    _verify_review_policy(candidate, inventory, release, now=current)
    return candidate


def _manifest_body(
    repository: Path,
    release_a_sha: str,
    review_policy: Any,
    *,
    generated_at: datetime,
) -> dict[str, Any]:
    repo = _repository(repository)
    _resolve_commit(repo, LIVE_BASE_SHA, path="fixed live base SHA")
    release = _resolve_commit(repo, release_a_sha, path="Release A SHA")
    _assert_ancestry(repo, release)
    inventory = _diff_inventory(repo, release)
    review_policy_sha256 = _verify_review_policy(
        review_policy,
        inventory,
        release,
        now=generated_at,
    )
    return {
        "profile": PROFILE,
        "base_sha": LIVE_BASE_SHA,
        "release_a_sha": release,
        "files": inventory,
        "diff_inventory_sha256": _sha256(_canonical_json(inventory)),
        "file_count": len(inventory),
        "policy_sha256": POLICY_SHA256,
        "review_policy_sha256": review_policy_sha256,
        "generated_at": _utc_text(generated_at),
    }


def build_manifest(
    repository: Path | str,
    release_a_sha: str,
    review_policy: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a self-checksummed manifest for one committed Release A."""

    generated_at = now or datetime.now(UTC)
    if generated_at.tzinfo is None:
        raise ReleaseAManifestError("now must include a timezone")
    body = _manifest_body(
        Path(repository),
        release_a_sha,
        review_policy,
        generated_at=generated_at,
    )
    return {**body, "manifest_sha256": _sha256(_canonical_json(body))}


def verify_manifest(
    payload: Any,
    repository: Path | str,
    expected_release_a_sha: str,
    review_policy: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Verify schema, self-checksum, Git range and fail-closed path policy."""

    if not isinstance(payload, Mapping) or set(payload) != _MANIFEST_KEYS:
        raise ReleaseAManifestError("manifest has an invalid field set")
    if payload["profile"] != PROFILE:
        raise ReleaseAManifestError("manifest.profile is invalid")
    if _git_sha(payload["base_sha"], path="manifest.base_sha") != LIVE_BASE_SHA:
        raise ReleaseAManifestError(
            "manifest.base_sha differs from the fixed live base"
        )
    expected = _git_sha(expected_release_a_sha, path="expected Release A SHA")
    release = _git_sha(payload["release_a_sha"], path="manifest.release_a_sha")
    if release != expected:
        raise ReleaseAManifestError(
            "manifest.release_a_sha differs from the expected SHA"
        )
    if not isinstance(payload["files"], list):
        raise ReleaseAManifestError("manifest.files must be an exact inventory list")
    for index, row in enumerate(payload["files"]):
        if not isinstance(row, Mapping) or set(row) != _INVENTORY_KEYS:
            raise ReleaseAManifestError(
                f"manifest.files[{index}] has an invalid field set"
            )
    _digest(payload["diff_inventory_sha256"], path="manifest.diff_inventory_sha256")
    if isinstance(payload["file_count"], bool) or not isinstance(
        payload["file_count"], int
    ):
        raise ReleaseAManifestError("manifest.file_count must be an integer")
    if payload["file_count"] <= 0:
        raise ReleaseAManifestError("manifest.file_count must be positive")
    if (
        _digest(payload["policy_sha256"], path="manifest.policy_sha256")
        != POLICY_SHA256
    ):
        raise ReleaseAManifestError(
            "manifest policy fingerprint differs from this checker"
        )
    _digest(payload["review_policy_sha256"], path="manifest.review_policy_sha256")
    generated_at = _timestamp(payload["generated_at"], path="manifest.generated_at")
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise ReleaseAManifestError("now must include a timezone")
    if generated_at > current.astimezone(UTC) + MAX_CLOCK_SKEW:
        raise ReleaseAManifestError("manifest.generated_at is too far in the future")
    manifest_digest = _digest(
        payload["manifest_sha256"], path="manifest.manifest_sha256"
    )
    body = {key: payload[key] for key in _MANIFEST_KEYS if key != "manifest_sha256"}
    if _sha256(_canonical_json(body)) != manifest_digest:
        raise ReleaseAManifestError("manifest self-checksum mismatch")

    expected_body = _manifest_body(
        Path(repository),
        expected,
        review_policy,
        generated_at=generated_at,
    )
    for key in (
        "base_sha",
        "release_a_sha",
        "files",
        "diff_inventory_sha256",
        "file_count",
        "policy_sha256",
        "review_policy_sha256",
    ):
        if payload[key] != expected_body[key]:
            raise ReleaseAManifestError(
                f"manifest.{key} differs from the committed Git range"
            )

    return {
        "profile": VERIFICATION_PROFILE,
        "result": "passed",
        "base_sha": LIVE_BASE_SHA,
        "release_a_sha": expected,
        "manifest_sha256": manifest_digest,
        "review_policy_sha256": payload["review_policy_sha256"],
        "verified_at": _utc_text(current),
    }


def _load_private_manifest(path: Path) -> Any:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ReleaseAManifestError("manifest is not readable") from exc
    mode = stat.S_IMODE(metadata.st_mode)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
        or mode not in {0o400, 0o600}
        or metadata.st_size <= 0
        or metadata.st_size > MAX_MANIFEST_BYTES
    ):
        raise ReleaseAManifestError(
            "manifest must be a private owner-only regular file with one link"
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseAManifestError("manifest must contain valid UTF-8 JSON") from exc


def _assert_external_artifact(
    repository: Path | str,
    path: Path,
    *,
    label: str,
) -> None:
    repo = _repository(repository)
    candidate = path.expanduser().resolve()
    if candidate == repo or repo in candidate.parents:
        raise ReleaseAManifestError(
            f"{label} must live outside the candidate Git worktree"
        )


def _write_private_manifest(path: Path, payload: Mapping[str, Any]) -> None:
    destination = path.expanduser()
    if not destination.is_absolute():
        raise ReleaseAManifestError("output must be an absolute path")
    parent = destination.parent.resolve()
    if not parent.is_dir():
        raise ReleaseAManifestError("output parent must be an existing directory")
    if destination.exists() or destination.is_symlink():
        raise ReleaseAManifestError("output already exists")
    rendered = _canonical_json(payload) + b"\n"
    if len(rendered) > MAX_MANIFEST_BYTES:
        raise ReleaseAManifestError("manifest exceeds the size limit")
    temporary = parent / f".{destination.name}.{os.getpid()}.tmp"
    descriptor = -1
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = -1
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, destination, follow_symlinks=False)
        os.unlink(temporary)
        directory = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise ReleaseAManifestError("could not publish the private manifest") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    review_template = commands.add_parser(
        "review-template",
        help="create a private pending semantic-review draft for the exact Git range",
    )
    review_template.add_argument("--repository", type=Path, required=True)
    review_template.add_argument("--release-a-sha", required=True)
    review_template.add_argument("--output", type=Path, required=True)

    seal_review = commands.add_parser(
        "seal-review",
        help="validate and seal an explicitly approved semantic-review draft",
    )
    seal_review.add_argument("--repository", type=Path, required=True)
    seal_review.add_argument("--release-a-sha", required=True)
    seal_review.add_argument("--draft", type=Path, required=True)
    seal_review.add_argument("--output", type=Path, required=True)

    create = commands.add_parser(
        "create", help="create a private Release A diff manifest"
    )
    create.add_argument("--repository", type=Path, required=True)
    create.add_argument("--release-a-sha", required=True)
    create.add_argument("--review-policy", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)

    verify = commands.add_parser(
        "verify", help="verify a private Release A diff manifest"
    )
    verify.add_argument("--repository", type=Path, required=True)
    verify.add_argument("--release-a-sha", required=True)
    verify.add_argument("--review-policy", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "review-template":
            _assert_external_artifact(
                args.repository,
                args.output,
                label="semantic review draft",
            )
            review_template = build_review_template(
                args.repository,
                args.release_a_sha,
            )
            _write_private_manifest(args.output, review_template)
            result = {
                "profile": REVIEW_PROFILE,
                "result": "pending_review",
                "base_sha": LIVE_BASE_SHA,
                "release_a_sha": review_template["release_a_sha"],
                "review_sha256": review_template["review_sha256"],
                "file_count": len(review_template["files"]),
            }
        elif args.command == "seal-review":
            _assert_external_artifact(
                args.repository,
                args.draft,
                label="semantic review draft",
            )
            _assert_external_artifact(
                args.repository,
                args.output,
                label="sealed semantic review",
            )
            draft = _load_private_manifest(args.draft)
            review_policy = seal_review_policy(
                draft,
                args.repository,
                args.release_a_sha,
            )
            _write_private_manifest(args.output, review_policy)
            result = {
                "profile": REVIEW_PROFILE,
                "result": "approved",
                "base_sha": LIVE_BASE_SHA,
                "release_a_sha": review_policy["release_a_sha"],
                "review_sha256": review_policy["review_sha256"],
                "file_count": len(review_policy["files"]),
            }
        elif args.command == "create":
            _assert_external_artifact(
                args.repository,
                args.review_policy,
                label="semantic review policy",
            )
            _assert_external_artifact(
                args.repository,
                args.output,
                label="Release A manifest",
            )
            review_policy = _load_private_manifest(args.review_policy)
            manifest = build_manifest(
                args.repository,
                args.release_a_sha,
                review_policy,
            )
            _write_private_manifest(args.output, manifest)
            result = {
                "profile": PROFILE,
                "result": "created",
                "base_sha": LIVE_BASE_SHA,
                "release_a_sha": manifest["release_a_sha"],
                "manifest_sha256": manifest["manifest_sha256"],
                "review_policy_sha256": manifest["review_policy_sha256"],
                "file_count": manifest["file_count"],
            }
        else:
            _assert_external_artifact(
                args.repository,
                args.review_policy,
                label="semantic review policy",
            )
            _assert_external_artifact(
                args.repository,
                args.manifest,
                label="Release A manifest",
            )
            manifest = _load_private_manifest(args.manifest)
            review_policy = _load_private_manifest(args.review_policy)
            result = verify_manifest(
                manifest,
                args.repository,
                args.release_a_sha,
                review_policy,
            )
    except ReleaseAManifestError as exc:
        print(f"release-a-manifest: {exc}", file=sys.stderr)
        return 2
    print(_canonical_json(result).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
