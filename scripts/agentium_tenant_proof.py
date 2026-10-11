#!/usr/bin/env python3
"""Build a SHA-bound Sentinel or Octocity deployment proof bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, Sequence


FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
TENANTS = {"sentinel": "sentinel.xml", "octocity": "octocity.xml"}
EXPECTED_TEST_TITLES = {
    "sentinel": "Sentinel workspace keeps its immersive Mission Room shell",
    "octocity": "Octocity workspace keeps its immersive Mission Room shell",
}
MAX_AGE_SECONDS = 60 * 60
MAX_BYTES = 32 * 1024 * 1024


class TenantProofError(ValueError):
    """Raised when tenant evidence is incomplete or unsafe."""


def _input(path: Path, proofs: Path, *, label: str) -> Path:
    try:
        if path.is_symlink():
            raise TenantProofError(f"{label} cannot be a symlink")
        resolved = path.resolve(strict=True)
        resolved.relative_to(proofs)
        details = resolved.stat()
    except (OSError, ValueError) as exc:
        raise TenantProofError(f"{label} is unavailable or escaped proofs") from exc
    if not resolved.is_file() or details.st_size <= 0 or details.st_size > MAX_BYTES:
        raise TenantProofError(f"{label} is not a bounded regular file")
    if details.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise TenantProofError(f"{label} is group/world writable")
    age = time.time() - details.st_mtime
    if age < -300 or age > MAX_AGE_SECONDS:
        raise TenantProofError(f"{label} is stale or future-dated")
    return resolved


def _digest(path: Path) -> dict[str, int | str]:
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
    }


def _assert_testcase_sha_binding(
    root: ET.Element,
    testcase: ET.Element,
    *,
    candidate_sha: str,
) -> None:
    sha_property_names = {
        "commit_sha",
        "candidate_sha",
        "ci_commit_sha",
        "git_sha",
    }
    all_sha_properties = [
        node
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1] == "property"
        and str(node.attrib.get("name", "")).strip().lower() in sha_property_names
    ]
    bindings = [
        node
        for node in testcase.iter()
        if node.tag.rsplit("}", 1)[-1] == "property"
        and str(node.attrib.get("name", "")).strip().lower() in sha_property_names
    ]
    if len(all_sha_properties) != 1 or len(bindings) != 1:
        raise TenantProofError(
            "workspace JUnit must bind the candidate SHA inside its testcase"
        )
    binding = bindings[0]
    value = str(binding.attrib.get("value", binding.text or "")).strip()
    if binding.attrib.get("name") != "commit_sha" or value != candidate_sha:
        raise TenantProofError(
            "workspace JUnit testcase commit SHA does not match the candidate"
        )


def _green_junit(
    path: Path,
    *,
    expected_title: str,
    candidate_sha: str,
) -> int:
    raw = path.read_bytes()
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise TenantProofError("workspace JUnit contains forbidden declarations")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise TenantProofError("workspace JUnit is invalid") from exc
    if any(
        "".join(node.itertext()).strip()
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1] in {"system-out", "system-err"}
    ):
        raise TenantProofError("workspace JUnit contains retained console output")
    cases = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "testcase"]
    if len(cases) != 1 or any(
        node.tag.rsplit("}", 1)[-1] in {"failure", "error", "skipped"}
        for node in root.iter()
    ):
        raise TenantProofError("workspace JUnit is not fully green")
    testcase_identity = " ".join(
        str(cases[0].attrib.get(key, "")).strip() for key in ("classname", "name")
    ).strip()
    if expected_title not in testcase_identity:
        raise TenantProofError(
            "workspace JUnit does not prove the expected tenant canary"
        )
    _assert_testcase_sha_binding(root, cases[0], candidate_sha=candidate_sha)
    for suite in root.iter():
        if suite.tag.rsplit("}", 1)[-1] not in {"testsuite", "testsuites"}:
            continue
        for key in ("failures", "errors", "skipped", "disabled"):
            try:
                if int(suite.attrib.get(key, "0")) != 0:
                    raise TenantProofError("workspace JUnit is not fully green")
            except ValueError as exc:
                raise TenantProofError("workspace JUnit count is invalid") from exc
    return len(cases)


def build_tenant_proof(
    *,
    tenant_key: str,
    candidate_sha: str,
    deployment_dir: Path,
) -> dict[str, Any]:
    if tenant_key not in TENANTS:
        raise TenantProofError("unsupported tenant proof key")
    if FULL_SHA_RE.fullmatch(candidate_sha) is None:
        raise TenantProofError("candidate SHA is invalid")
    if deployment_dir.is_symlink():
        raise TenantProofError("deployment-dir cannot be a symlink")
    deployment = deployment_dir.resolve(strict=True)
    proofs_candidate = deployment / "proofs"
    if proofs_candidate.is_symlink():
        raise TenantProofError("proofs directory is invalid")
    proofs = proofs_candidate.resolve(strict=True)
    if proofs.parent != deployment:
        raise TenantProofError("proofs directory is invalid")
    junit = _input(proofs / TENANTS[tenant_key], proofs, label="workspace_junit")
    bindings_path = _input(
        proofs / "runtime-bindings.json", proofs, label="runtime_bindings"
    )
    try:
        bindings = json.loads(bindings_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TenantProofError("runtime binding audit is invalid") from exc
    if (
        not isinstance(bindings, dict)
        or bindings.get("result") != "passed"
        or bindings.get("requested_workspace_slugs") != []
        or bindings.get("missing_workspace_slugs") != []
        or not isinstance(bindings.get("workspace_count"), int)
        or bindings["workspace_count"] < 3
    ):
        raise TenantProofError("runtime binding audit did not pass")
    test_count = _green_junit(
        junit,
        expected_title=EXPECTED_TEST_TITLES[tenant_key],
        candidate_sha=candidate_sha,
    )
    return {
        "schema_version": 1,
        "kind": "tenant_safe_deployment_bundle",
        "tenant_key": tenant_key,
        "commit_sha": candidate_sha,
        "deployment_id": deployment.name,
        "outcome": "passed",
        "workspace_test_count": test_count,
        "checks": {
            "workspace_junit_green": {"passed": True},
            "all_workspace_runtime_bindings_passed": {"passed": True},
        },
        "evidence": {
            "workspace_junit": _digest(junit),
            "runtime_bindings": _digest(bindings_path),
        },
    }


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists() and path.is_symlink():
        raise TenantProofError("tenant output cannot be a symlink")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", choices=sorted(TENANTS), required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--deployment-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        payload = build_tenant_proof(
            tenant_key=args.tenant,
            candidate_sha=args.sha,
            deployment_dir=args.deployment_dir,
        )
        output = (
            args.deployment_dir.resolve(strict=True) / "proofs" / f"{args.tenant}.json"
        )
        _write(output, payload)
    except (TenantProofError, OSError) as exc:
        print(f"tenant proof failed: {exc}", file=sys.stderr)
        return 1
    print(f"{args.tenant} proof bundle passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
