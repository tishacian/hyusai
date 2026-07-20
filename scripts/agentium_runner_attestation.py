#!/usr/bin/env python3
"""Write a protected-job, SHA-bound runner attestation for trusted promotion.

This helper does not decide whether a test passed: it must be invoked only
after the runner exits successfully. The signed GitLab OIDC collector then
binds this JSON to the same protected job before it can promote any claim.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Mapping, Sequence

FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
CLAIM_RE = re.compile(r"^LOT[0-9]+-[A-Z0-9][A-Z0-9-]*$")
RUNNERS = {"pytest", "node", "playwright"}


class RunnerAttestationError(ValueError):
    """Raised when the running CI job cannot own formal runner evidence."""


def protected_ci_identity(env: Mapping[str, str]) -> dict[str, str]:
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
        raise RunnerAttestationError("missing CI metadata: " + ", ".join(missing))
    sha = env["CI_COMMIT_SHA"].strip().lower()
    if not FULL_SHA_RE.fullmatch(sha):
        raise RunnerAttestationError("CI_COMMIT_SHA must be a full lowercase SHA")
    if env.get("CI_COMMIT_REF_PROTECTED", "").lower() != "true":
        raise RunnerAttestationError("runner evidence requires a protected GitLab ref")
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


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner", required=True, choices=sorted(RUNNERS))
    parser.add_argument("--claim", action="append", required=True)
    parser.add_argument("--suite", required=True)
    parser.add_argument("--environment", default="ci")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        identity = protected_ci_identity(os.environ)
        invalid = [claim for claim in args.claim if not CLAIM_RE.fullmatch(claim)]
        if invalid:
            raise RunnerAttestationError("invalid claim ids: " + ", ".join(invalid))
        if not args.suite.strip() or "\x00" in args.suite:
            raise RunnerAttestationError("--suite must be a non-empty label")
        report = {
            "schema_version": 1,
            "kind": "runner",
            "commit_sha": identity["commit_sha"],
            "environment": args.environment,
            "outcome": "passed",
            "runner": args.runner,
            "suite": args.suite,
            "claims": {claim: "passed" for claim in args.claim},
            "ci": identity,
            "checks": {
                "runner_exit": True,
                "protected_ref": True,
                "sha_bound": True,
            },
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_name(args.output.name + ".tmp")
        temporary.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        temporary.replace(args.output)
        print(f"Runner attestation written for {identity['commit_sha'][:12]}")
        return 0
    except RunnerAttestationError as exc:
        print(f"Runner attestation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
