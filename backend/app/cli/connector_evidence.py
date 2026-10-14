"""Assemble complete, bounded certification reports; never execute or invent tests.

Run in the exact connector image that ran the kit. The resulting JSON must be
accepted by a platform operator; integrity alone is not producer authentication.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

from app.services.connectors.certification import (
    ComponentIdentity,
    EvidenceBundle,
    EvidencePayload,
    SuiteResult,
    evidence_digest,
    required_suites,
)
from app.services.connectors.evidence_store import ProofReport, report_digest
from app.services.connectors.kit_identity import kit_identity
from app.services.connectors.profiles import get_profile


def read_json(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 1024 * 1024:
        raise ValueError("CONNECTOR_EVIDENCE_INPUT_INVALID")
    return json.loads(path.read_text())


def assemble(*, identity, reports, revision, environment, environment_id, kind, completed_at):
    if isinstance(identity, dict) and "identity" in identity:
        if identity.get("source") != "real":
            raise ValueError("CONNECTOR_EVIDENCE_SOURCE_INVALID")
        identity = identity["identity"]
    identity = ComponentIdentity.model_validate(identity)
    profile = get_profile(identity.profile_key)
    kit = kit_identity()
    if (
        identity.profile_sha256 != profile.digest
        or identity.capabilities != profile.capabilities
        or identity.kit_version != kit["version"]
        or identity.kit_sha256 != kit["sha256"]
    ):
        raise ValueError("CONNECTOR_EVIDENCE_COMPONENT_CHANGED")
    for driver in identity.drivers:
        if metadata.version(driver.package) != driver.version:
            raise ValueError("CONNECTOR_EVIDENCE_DRIVER_CHANGED")
    reports = [ProofReport.model_validate(report) for report in reports]
    expected = (
        required_suites(profile.capabilities) if kind == "suite" else {"canary", "revocation"}
    )
    if len(reports) != len(expected) or {r.suite for r in reports} != expected:
        raise ValueError("CONNECTOR_EVIDENCE_SUITES_INCOMPLETE")
    if completed_at > datetime.now(UTC):
        raise ValueError("CONNECTOR_EVIDENCE_FROM_FUTURE")
    payload = EvidencePayload(
        kind=kind,
        identity=identity,
        source_revision=revision,
        environment=environment,
        environment_id=environment_id,
        source="real",
        completed_at=completed_at,
        results=tuple(
            SuiteResult(suite=r.suite, status=r.status, evidence_sha256=report_digest(r))
            for r in sorted(reports, key=lambda r: r.suite)
        ),
    )
    bundle = EvidenceBundle(payload=payload, sha256=evidence_digest(payload))
    return {
        "bundle": bundle.model_dump(mode="json"),
        "reports": [r.model_dump(mode="json") for r in reports],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan", help="Print required suite names for a profile; does not produce evidence"
    )
    parser.add_argument("--identity-file")
    parser.add_argument("--reports-dir")
    parser.add_argument("--revision")
    parser.add_argument("--environment", choices=["container", "test_account", "deployed"])
    parser.add_argument("--environment-id")
    parser.add_argument("--kind", choices=["suite", "canary"], default="suite")
    parser.add_argument("--completed-at")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    if args.plan:
        print(
            json.dumps(
                {
                    "profile": args.plan,
                    "required_suites": sorted(required_suites(get_profile(args.plan).capabilities)),
                    "kit": kit_identity(),
                },
                indent=2,
            )
        )
        return 0
    required = (
        args.identity_file,
        args.reports_dir,
        args.revision,
        args.environment,
        args.environment_id,
        args.completed_at,
        args.output,
    )
    if not all(required):
        parser.error(
            "identity, reports, revision, environment, environment-id, completed-at and output are required"
        )
    try:
        root = Path(args.reports_dir)
        paths = sorted(root.glob("*.json"))
        if not root.is_dir() or len(paths) > 100:
            raise ValueError("CONNECTOR_EVIDENCE_INPUT_INVALID")
        result = assemble(
            identity=read_json(args.identity_file),
            reports=[read_json(p) for p in paths],
            revision=args.revision,
            environment=args.environment,
            environment_id=args.environment_id,
            kind=args.kind,
            completed_at=datetime.fromisoformat(args.completed_at),
        )
        fd = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(result, handle, sort_keys=True, indent=2)
        passed = all(row["status"] == "passed" for row in result["reports"])
        print(
            json.dumps(
                {
                    "sha256": result["bundle"]["sha256"],
                    "all_suites_passed": passed,
                    "operator_acceptance_required": True,
                }
            )
        )
        return 0 if passed else 2
    except Exception as exc:
        code = str(exc)
        if not re.fullmatch("CONNECTOR_[A-Z_]+", code):
            code = "CONNECTOR_EVIDENCE_ASSEMBLY_FAILED"
        print(json.dumps({"error_code": code}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
