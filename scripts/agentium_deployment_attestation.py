#!/usr/bin/env python3
"""Collect a SHA-bound Agentium VM deployment attestation.

The collector is intentionally read-only.  It probes the checked-out ref and
running containers over SSH, then compares both public build-info resources
with the exact GitLab commit.  It emits JSON, JUnit and HTML only after every
identity check has been evaluated; a mismatch makes the command fail.

No password, private key, access token or application credential is accepted
as an argument, stored in an artifact or printed by this process.  SSH
authentication remains the responsibility of the CI runner's protected SSH
configuration.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SAFE_HOST_RE = re.compile(r"^(?:[A-Za-z0-9._-]+@)?[A-Za-z0-9.-]+$")
SAFE_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
SAFE_REMOTE_PATH_RE = re.compile(r"^/[A-Za-z0-9._/-]+$")
SAFE_SERVICE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
SAFE_CLAIM_RE = re.compile(r"^LOT6-[A-Z0-9][A-Z0-9-]*$")
IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
DB_REVISION_RE = re.compile(r"^[A-Za-z0-9_]+$")

DEFAULT_SERVICES = (
    "agentium-backend",
    "agentium-frontend",
    "agentium-worker-cpu",
)
DEFAULT_CLAIM = "LOT6-SYSTEM360-PERSPECTIVES"


class AttestationError(ValueError):
    """Raised when the deployment cannot be proven safely."""


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    expected: str
    observed: str


REMOTE_PROBE = r'''from __future__ import annotations
import json
import re
import subprocess
import sys
from pathlib import Path

repo = Path(sys.argv[1])
expected_branch = sys.argv[2]
services = sys.argv[3:]

def run(argv):
    completed = subprocess.run(
        argv,
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()

head = run(["git", "rev-parse", "HEAD"]).lower()
branch = run(["git", "branch", "--show-current"])
dirty = run(["git", "status", "--porcelain=v1", "--untracked-files=all"])
rows = []
for service in services:
    state_and_image = run([
        "docker", "inspect", "--format", "{{.State.Running}}|{{.Image}}", service,
    ])
    running, image_id = state_and_image.split("|", 1)
    revision = run([
        "docker", "image", "inspect", "--format",
        '{{ index .Config.Labels "org.opencontainers.image.revision" }}', image_id,
    ]).lower()
    rows.append({
        "service": service,
        "running": running == "true",
        "image_id": image_id,
        "revision": revision,
    })

alembic = run(["docker", "exec", "agentium-backend", "alembic", "current"])
heads = sorted(set(re.findall(r"([A-Za-z0-9_]+)\s+\(head\)", alembic)))
rollout_raw = run([
    "docker", "exec", "-w", "/app/backend", "agentium-backend",
    "python", "-m", "scripts.rollout_system360_canary", "status",
])
rollout = json.loads(rollout_raw)
print(json.dumps({
    "repo_head": head,
    "branch": branch,
    "clean": not bool(dirty),
    "dirty_entry_count": len(dirty.splitlines()) if dirty else 0,
    "services": rows,
    "database_heads": heads,
    "rollout": rollout,
}, sort_keys=True))
'''


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_full_sha(value: str, *, field: str) -> str:
    normalized = value.strip().lower()
    if not FULL_SHA_RE.fullmatch(normalized):
        raise AttestationError(f"{field} must be a full 40-character lowercase SHA")
    return normalized


def _require_safe(value: str, pattern: re.Pattern[str], *, field: str) -> str:
    if not value or not pattern.fullmatch(value):
        raise AttestationError(f"{field} contains unsupported characters")
    return value


def protected_ci_identity(env: Mapping[str, str] = os.environ) -> dict[str, str]:
    """Return the non-secret GitLab identity bound to a protected job."""

    required = (
        "CI_SERVER_URL",
        "CI_PROJECT_ID",
        "CI_PIPELINE_ID",
        "CI_JOB_ID",
        "CI_JOB_URL",
        "CI_COMMIT_SHA",
        "CI_COMMIT_REF_NAME",
    )
    missing = [key for key in required if not env.get(key, "").strip()]
    if missing:
        raise AttestationError(
            "protected GitLab metadata is incomplete: " + ", ".join(missing)
        )
    if env.get("CI_COMMIT_REF_PROTECTED", "").lower() != "true":
        raise AttestationError("the attestation job must run from a protected GitLab ref")
    sha = _require_full_sha(env["CI_COMMIT_SHA"], field="CI_COMMIT_SHA")
    return {
        "server_url": env["CI_SERVER_URL"].rstrip("/"),
        "project_id": env["CI_PROJECT_ID"],
        "pipeline_id": env["CI_PIPELINE_ID"],
        "job_id": env["CI_JOB_ID"],
        "job_url": env["CI_JOB_URL"],
        "commit_sha": sha,
        "ref": env["CI_COMMIT_REF_NAME"],
        "ref_protected": "true",
    }


def collect_remote_snapshot(
    *,
    host: str,
    repo_dir: str,
    branch: str,
    services: Sequence[str],
    ssh_bin: str = "ssh",
) -> dict[str, Any]:
    """Read deployment identity from the VM without changing it."""

    _require_safe(host, SAFE_HOST_RE, field="--host")
    _require_safe(repo_dir, SAFE_REMOTE_PATH_RE, field="--repo-dir")
    _require_safe(branch, SAFE_BRANCH_RE, field="--branch")
    if ".." in Path(repo_dir).parts:
        raise AttestationError("--repo-dir cannot contain parent traversal")
    if not services:
        raise AttestationError("at least one container service is required")
    for service in services:
        _require_safe(service, SAFE_SERVICE_RE, field="--service")

    command = [
        ssh_bin,
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        host,
        "python3",
        "-",
        repo_dir,
        branch,
        *services,
    ]
    try:
        completed = subprocess.run(
            command,
            input=REMOTE_PROBE,
            check=True,
            capture_output=True,
            text=True,
            timeout=90,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        stderr = getattr(exc, "stderr", "") or ""
        safe_detail = " ".join(stderr.strip().split())[:300]
        suffix = f": {safe_detail}" if safe_detail else ""
        raise AttestationError(f"read-only VM probe failed{suffix}") from exc
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AttestationError("VM probe did not return valid JSON") from exc
    if not isinstance(value, dict):
        raise AttestationError("VM probe returned a non-object payload")
    return value


def fetch_build_info(
    base_url: str,
    path: str,
    *,
    timeout: float = 15.0,
    insecure: bool = False,
) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise AttestationError("--base-url must be an absolute HTTP(S) URL")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise AttestationError("remote build-info must be queried over HTTPS")
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    context = ssl._create_unverified_context() if insecure else None
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "agentium-attestor/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            payload = response.read(65_537)
            if len(payload) > 65_536:
                raise AttestationError(f"build-info response is too large: {path}")
            if response.status != 200:
                raise AttestationError(f"build-info returned HTTP {response.status}: {path}")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise AttestationError(f"cannot read build-info resource: {path}") from exc
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise AttestationError(f"build-info is not JSON: {path}") from exc
    if not isinstance(value, dict):
        raise AttestationError(f"build-info must be an object: {path}")
    return value


def evaluate_deployment(
    *,
    expected_sha: str,
    expected_branch: str,
    expected_services: Sequence[str],
    snapshot: Mapping[str, Any],
    backend_build: Mapping[str, Any],
    frontend_build: Mapping[str, Any],
) -> list[Check]:
    """Return every independent deployment identity check."""

    expected_sha = _require_full_sha(expected_sha, field="expected SHA")
    checks = [
        Check("vm.repo_head", snapshot.get("repo_head") == expected_sha, expected_sha, str(snapshot.get("repo_head"))),
        Check("vm.branch", snapshot.get("branch") == expected_branch, expected_branch, str(snapshot.get("branch"))),
        Check("vm.checkout_clean", snapshot.get("clean") is True, "true", str(snapshot.get("clean")).lower()),
        Check("database.single_head", len(snapshot.get("database_heads", [])) == 1, "one Alembic head", json.dumps(snapshot.get("database_heads"))),
        Check("backend.build_info.service", backend_build.get("service") == "backend", "backend", str(backend_build.get("service"))),
        Check("backend.build_info.revision", backend_build.get("revision") == expected_sha, expected_sha, str(backend_build.get("revision"))),
        Check("backend.build_info.revision_verified", backend_build.get("revision_verified") is True, "true", str(backend_build.get("revision_verified")).lower()),
        Check("frontend.build_info.service", frontend_build.get("service") == "frontend", "frontend", str(frontend_build.get("service"))),
        Check("frontend.build_info.revision", frontend_build.get("revision") == expected_sha, expected_sha, str(frontend_build.get("revision"))),
        Check("frontend.build_info.revision_verified", frontend_build.get("revision_verified") is True, "true", str(frontend_build.get("revision_verified")).lower()),
    ]
    rows = snapshot.get("services")
    by_service = {
        row.get("service"): row
        for row in rows
        if isinstance(row, Mapping) and isinstance(row.get("service"), str)
    } if isinstance(rows, list) else {}
    checks.append(
        Check(
            "oci.service_set",
            set(by_service) == set(expected_services),
            ",".join(sorted(expected_services)),
            ",".join(sorted(str(item) for item in by_service)),
        )
    )
    for service in expected_services:
        row = by_service.get(service, {})
        checks.extend(
            [
                Check(f"oci.{service}.running", row.get("running") is True, "true", str(row.get("running")).lower()),
                Check(f"oci.{service}.image_id", bool(IMAGE_ID_RE.fullmatch(str(row.get("image_id", "")))), "sha256:<64 hex>", str(row.get("image_id"))),
                Check(f"oci.{service}.revision", row.get("revision") == expected_sha, expected_sha, str(row.get("revision"))),
            ]
        )
    rollout = snapshot.get("rollout")
    rollout = rollout if isinstance(rollout, Mapping) else {}
    features = rollout.get("features")
    features = features if isinstance(features, Mapping) else {}
    exercise = rollout.get("exercise")
    exercise = exercise if isinstance(exercise, Mapping) else {}
    checks.extend(
        [
            Check("rollout.phase", rollout.get("phase") == "projection_active", "projection_active", str(rollout.get("phase"))),
            Check("rollout.ready", rollout.get("ready") is True, "true", str(rollout.get("ready")).lower()),
            Check("rollout.marker_count", rollout.get("marker_count") == 1, "1", str(rollout.get("marker_count"))),
            Check("rollout.marker_on_target", rollout.get("marker_on_target") is True, "true", str(rollout.get("marker_on_target")).lower()),
            Check("rollout.strict_flow", rollout.get("strict_flow") is True, "true", str(rollout.get("strict_flow")).lower()),
            Check("rollout.flow_feature", features.get("flow_v3_dag_authoritative") is True, "true", str(features.get("flow_v3_dag_authoritative")).lower()),
            Check("rollout.axes_feature", features.get("cockpit_router_axes_v4") is True, "true", str(features.get("cockpit_router_axes_v4")).lower()),
            Check("rollout.projection_feature", features.get("system_360_projection_v1") is True, "true", str(features.get("system_360_projection_v1")).lower()),
            Check("rollout.membrane", rollout.get("membrane_mode") == "enforce", "enforce", str(rollout.get("membrane_mode"))),
            Check("rollout.exercise_status", exercise.get("status") == "completed", "completed", str(exercise.get("status"))),
            Check("rollout.exercise_skills", exercise.get("required_skills_observed") is True, "true", str(exercise.get("required_skills_observed")).lower()),
            Check("rollout.exercise_grounded", exercise.get("grounded_output_verified") is True, "true", str(exercise.get("grounded_output_verified")).lower()),
            Check("rollout.exercise_provenance", exercise.get("canonical_provenance_verified") is True, "true", str(exercise.get("canonical_provenance_verified")).lower()),
        ]
    )
    return checks


def build_attestation(
    *,
    sha: str,
    environment: str,
    branch: str,
    host: str,
    claims: Sequence[str],
    ci: Mapping[str, str],
    snapshot: Mapping[str, Any],
    backend_build: Mapping[str, Any],
    frontend_build: Mapping[str, Any],
    checks: Sequence[Check],
) -> dict[str, Any]:
    passed = all(check.passed for check in checks)
    return {
        "schema_version": 1,
        "kind": "deployment",
        "commit_sha": sha,
        "environment": environment,
        "outcome": "passed" if passed else "failed",
        "claims": {claim: "deployed" if passed else "failed" for claim in claims},
        "collected_at": _utc_now(),
        "ci": dict(ci),
        "vm": {
            "host": host,
            "repo_head": snapshot.get("repo_head"),
            "branch": snapshot.get("branch"),
            "clean": snapshot.get("clean"),
            "dirty_entry_count": snapshot.get("dirty_entry_count"),
        },
        "database_heads": snapshot.get("database_heads", []),
        "rollout": snapshot.get("rollout", {}),
        "services": snapshot.get("services", []),
        "build_info": {
            "backend": dict(backend_build),
            "frontend": dict(frontend_build),
        },
        "checks": {
            check.name: {
                "passed": check.passed,
                "expected": check.expected,
                "observed": check.observed,
            }
            for check in checks
        },
    }


def write_reports(
    attestation: Mapping[str, Any],
    *,
    output: Path,
    junit: Path,
    html_output: Path,
    checksum: Path,
) -> None:
    for path in (output, junit, html_output, checksum):
        path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(attestation, indent=2, sort_keys=True) + "\n"
    output.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    checksum.write_text(f"{digest}  {output.name}\n", encoding="utf-8")

    check_rows = attestation.get("checks", {})
    suite = ET.Element(
        "testsuite",
        name="agentium-lot6-deployment-preflight",
        tests=str(len(check_rows)),
        failures=str(sum(not bool(row.get("passed")) for row in check_rows.values())),
    )
    for name, row in check_rows.items():
        case = ET.SubElement(suite, "testcase", classname="deployment.identity", name=name)
        if not row.get("passed"):
            failure = ET.SubElement(case, "failure", message="deployment identity mismatch")
            failure.text = f"expected={row.get('expected')} observed={row.get('observed')}"
    ET.ElementTree(suite).write(junit, encoding="utf-8", xml_declaration=True)

    rows = "\n".join(
        "<tr><td>{}</td><td>{}</td><td><code>{}</code></td><td><code>{}</code></td></tr>".format(
            html.escape(name),
            "PASS" if row.get("passed") else "FAIL",
            html.escape(str(row.get("expected"))),
            html.escape(str(row.get("observed"))),
        )
        for name, row in check_rows.items()
    )
    html_output.write_text(
        "<!doctype html><meta charset=utf-8><title>Agentium Lot 6 deployment proof</title>"
        "<style>body{font:14px system-ui;margin:2rem;color:#18202a}table{border-collapse:collapse}"
        "th,td{border:1px solid #ccd3da;padding:.5rem;text-align:left}code{font-size:12px}</style>"
        f"<h1>Agentium Lot 6 deployment proof</h1><p>SHA <code>{html.escape(str(attestation.get('commit_sha')))}</code>"
        f" · outcome <strong>{html.escape(str(attestation.get('outcome')))}</strong></p>"
        "<table><thead><tr><th>Check</th><th>Result</th><th>Expected</th><th>Observed</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>",
        encoding="utf-8",
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--repo-dir", default="/home/ubuntu/omnirag")
    parser.add_argument("--branch", default="demo/agentic")
    parser.add_argument("--environment", default="production")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--service", action="append", dest="services")
    parser.add_argument("--claim", action="append", dest="claims")
    parser.add_argument("--insecure", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--html", type=Path, required=True)
    parser.add_argument("--checksum", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        sha = _require_full_sha(args.sha, field="--sha")
        branch = _require_safe(args.branch, SAFE_BRANCH_RE, field="--branch")
        services = tuple(args.services or DEFAULT_SERVICES)
        claims = tuple(args.claims or (DEFAULT_CLAIM,))
        for claim in claims:
            _require_safe(claim, SAFE_CLAIM_RE, field="--claim")
        ci = protected_ci_identity()
        if ci["commit_sha"] != sha:
            raise AttestationError("--sha does not match CI_COMMIT_SHA")
        if ci["ref"] != branch:
            raise AttestationError("--branch does not match CI_COMMIT_REF_NAME")
        snapshot = collect_remote_snapshot(
            host=args.host,
            repo_dir=args.repo_dir,
            branch=branch,
            services=services,
        )
        backend_build = fetch_build_info(
            args.base_url, "/api/v1/build-info", insecure=args.insecure
        )
        frontend_build = fetch_build_info(
            args.base_url, "/build-info.json", insecure=args.insecure
        )
        checks = evaluate_deployment(
            expected_sha=sha,
            expected_branch=branch,
            expected_services=services,
            snapshot=snapshot,
            backend_build=backend_build,
            frontend_build=frontend_build,
        )
        attestation = build_attestation(
            sha=sha,
            environment=args.environment,
            branch=branch,
            host=args.host,
            claims=claims,
            ci=ci,
            snapshot=snapshot,
            backend_build=backend_build,
            frontend_build=frontend_build,
            checks=checks,
        )
        write_reports(
            attestation,
            output=args.output,
            junit=args.junit,
            html_output=args.html,
            checksum=args.checksum,
        )
        if attestation["outcome"] != "passed":
            failed = [check.name for check in checks if not check.passed]
            raise AttestationError("deployment identity mismatch: " + ", ".join(failed))
        print(f"Deployment attestation passed for {sha[:12]} ({len(checks)} checks)")
        return 0
    except AttestationError as exc:
        print(f"Deployment attestation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
