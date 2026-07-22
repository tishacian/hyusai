#!/usr/bin/env python3
"""Collect Lot-9 Playwright observations into rollout-grade evidence.

The browser never chooses a raw Workspace id: it discovers the unique
structurally marked canary and emits only hashes.  This server-side collector
binds that observation to the authoritative database, exact deployment SHA,
canonical installation/configuration set and (for post-activation evidence)
the live probation lease.  Local collections are useful diagnostics but are
deliberately non-promotable.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import xml.etree.ElementTree as ElementTree
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session as DBSession

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.base import SessionLocal  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.services.workspace_app_runtime import (  # noqa: E402
    WorkspaceAppRuntimeError,
    inspect_authoritative_workspace_app_runtime,
    resolve_workspace_app_runtime,
    workspace_app_installation_subject,
    workspace_app_installations_sha256,
)
from scripts import rollout_workspace_app_platform as rollout  # noqa: E402

OBSERVATION_SCHEMA_VERSION = 1
PREFLIGHT_OBSERVATION_KIND = "lot9_workspace_app_preflight_observation"
POSTACTIVATION_OBSERVATION_KIND = "lot9_workspace_app_postactivation_observation"
PREFLIGHT_CANARY_TEST_NAME = (
    "discovers the dedicated target and leaves a proven nonempty installation set"
)
POSTACTIVATION_CANARY_TEST_NAME = (
    "proves the staged runtime on the same workspace and installation set"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _canonical_sha256(value: Any) -> str:
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _id_sha256(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _exact_keys(value: Mapping[str, Any], expected: set[str], *, field: str) -> None:
    actual = set(value)
    if actual != expected:
        raise rollout.WorkspaceAppRolloutError(
            f"{field} fields differ from the contract; "
            f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
        )


def _sha256(value: Any, *, field: str) -> str:
    normalized = str(value or "").strip().lower()
    if _SHA256_RE.fullmatch(normalized) is None:
        raise rollout.WorkspaceAppRolloutError(f"{field} must be a lowercase SHA-256")
    return normalized


def _phase_contract(
    phase: str,
) -> tuple[str, str, tuple[str, ...], str, str]:
    if phase == "preflight":
        return (
            PREFLIGHT_OBSERVATION_KIND,
            PREFLIGHT_CANARY_TEST_NAME,
            rollout.PREFLIGHT_CHECKS,
            rollout.PREFLIGHT_EVIDENCE_KIND,
            rollout.PREFLIGHT_EVIDENCE_SUITE,
        )
    if phase == "postactivation":
        return (
            POSTACTIVATION_OBSERVATION_KIND,
            POSTACTIVATION_CANARY_TEST_NAME,
            rollout.POSTACTIVATION_CHECKS,
            rollout.POSTACTIVATION_EVIDENCE_KIND,
            rollout.POSTACTIVATION_EVIDENCE_SUITE,
        )
    raise rollout.WorkspaceAppRolloutError(
        "collector phase must be preflight or postactivation"
    )


def _validate_observation(
    observation: Mapping[str, Any],
    *,
    phase: str,
    revision: str,
) -> dict[str, Any]:
    observation_kind, _test_name, checks, _evidence_kind, _suite = _phase_contract(phase)
    payload = _record(observation)
    _exact_keys(
        payload,
        {
            "schema_version",
            "kind",
            "tested_revision",
            "generated_at",
            "runner",
            "target",
            "checks",
            "diagnostics",
        },
        field="observation",
    )
    if payload.get("schema_version") != OBSERVATION_SCHEMA_VERSION:
        raise rollout.WorkspaceAppRolloutError("observation schema_version must be 1")
    if payload.get("kind") != observation_kind:
        raise rollout.WorkspaceAppRolloutError("observation kind differs from collector phase")
    if payload.get("tested_revision") != revision:
        raise rollout.WorkspaceAppRolloutError(
            "observation revision differs from the deployed runtime revision"
        )
    generated_at = rollout._parse_utc(payload.get("generated_at"), field="generated_at")
    now = datetime.now(UTC)
    if generated_at > now + rollout.EVIDENCE_FUTURE_TOLERANCE:
        raise rollout.WorkspaceAppRolloutError("observation is dated in the future")
    if now - generated_at > rollout.EVIDENCE_MAX_AGE:
        raise rollout.WorkspaceAppRolloutError("observation is older than 24 hours")
    runner = _record(payload.get("runner"))
    _exact_keys(runner, {"protected_ci", "pipeline_id", "job_id"}, field="runner")
    target = _record(payload.get("target"))
    expected_target = {"workspace_sha256", "installations_sha256"}
    if phase == "postactivation":
        expected_target.add("probation_ref")
    _exact_keys(target, expected_target, field="target")
    target["workspace_sha256"] = _sha256(
        target.get("workspace_sha256"), field="target.workspace_sha256"
    )
    target["installations_sha256"] = _sha256(
        target.get("installations_sha256"), field="target.installations_sha256"
    )
    if phase == "postactivation":
        probation_ref = str(target.get("probation_ref") or "").strip().lower()
        if not probation_ref.startswith("sha256:") or _SHA256_RE.fullmatch(
            probation_ref.removeprefix("sha256:")
        ) is None:
            raise rollout.WorkspaceAppRolloutError(
                "target.probation_ref must be content-addressed"
            )
        target["probation_ref"] = probation_ref
    observed_checks = _record(payload.get("checks"))
    _exact_keys(observed_checks, set(checks), field="checks")
    if any(observed_checks.get(name) is not True for name in checks):
        raise rollout.WorkspaceAppRolloutError("every phase check must pass")
    if not isinstance(payload.get("diagnostics"), Mapping):
        raise rollout.WorkspaceAppRolloutError("diagnostics must be an object")
    diagnostics = _record(payload.get("diagnostics"))
    if phase == "postactivation":
        declared_count = diagnostics.get("declared_entitlement_count")
        if (
            isinstance(declared_count, bool)
            or not isinstance(declared_count, int)
            or declared_count <= 0
            or diagnostics.get("entitlement_gate") is not True
        ):
            raise rollout.WorkspaceAppRolloutError(
                "post-activation entry_gate requires a declared and exercised entitlement"
            )
    return {
        **payload,
        "runner": runner,
        "target": target,
        "checks": observed_checks,
        "diagnostics": diagnostics,
        "generated_at": generated_at,
    }


def _validate_playwright_junit(content: bytes, *, phase: str) -> None:
    _kind, test_name, _checks, _evidence_kind, _suite = _phase_contract(phase)
    if not content or len(content) > rollout.EVIDENCE_ARTIFACT_MAX_BYTES:
        raise rollout.WorkspaceAppRolloutError("Playwright JUnit has an invalid size")
    upper = content.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise rollout.WorkspaceAppRolloutError("Playwright JUnit XML declarations are forbidden")
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise rollout.WorkspaceAppRolloutError("Playwright JUnit is not valid XML") from exc
    if root.tag not in {"testsuite", "testsuites"}:
        raise rollout.WorkspaceAppRolloutError("Playwright JUnit root must be testsuite(s)")
    for suite in root.iter("testsuite"):
        try:
            failed = sum(
                int(suite.get(name, "0")) for name in ("failures", "errors", "skipped")
            )
        except ValueError as exc:
            raise rollout.WorkspaceAppRolloutError(
                "Playwright JUnit counters must be integers"
            ) from exc
        if failed:
            raise rollout.WorkspaceAppRolloutError(
                "Playwright JUnit contains failed, errored or skipped tests"
            )
    matches = [
        case
        for case in root.iter("testcase")
        if test_name in str(case.get("name") or "")
    ]
    if len(matches) != 1:
        raise rollout.WorkspaceAppRolloutError(
            "Playwright JUnit must contain exactly one phase-specific Lot 9 testcase"
        )
    if any(matches[0].find(name) is not None for name in ("failure", "error", "skipped")):
        raise rollout.WorkspaceAppRolloutError("the Lot 9 Playwright testcase did not pass")


def _canonical_runner_artifact(
    *,
    revision: str,
    workspace_id: str,
    installations_sha256: str,
    checks: Sequence[str],
    suite_name: str,
    observation_ref: str,
    probation_ref: str | None,
    source_junit_ref: str,
) -> dict[str, str]:
    root = ElementTree.Element(
        "testsuite",
        {
            "name": suite_name,
            "tests": str(len(checks)),
            "failures": "0",
            "errors": "0",
            "skipped": "0",
        },
    )
    properties = ElementTree.SubElement(root, "properties")
    values = [
        ("revision", revision),
        ("workspace_id", workspace_id),
        ("installations_sha256", installations_sha256),
        ("observation_ref", observation_ref),
        ("source_junit_ref", source_junit_ref),
    ]
    if probation_ref is not None:
        values.append(("probation_ref", probation_ref))
    for name, value in values:
        ElementTree.SubElement(properties, "property", {"name": name, "value": value})
    for name in checks:
        ElementTree.SubElement(root, "testcase", {"classname": "lot9", "name": name})
    content = ElementTree.tostring(root, encoding="utf-8", xml_declaration=False)
    digest = hashlib.sha256(content).hexdigest()
    return {
        "media_type": "application/junit+xml",
        "content_base64": base64.b64encode(content).decode("ascii"),
        "sha256": digest,
        "artifact_ref": f"sha256:{digest}",
    }


def _unique_canary(db: DBSession, workspace_id: str) -> Workspace:
    target = db.query(Workspace).filter(
        Workspace.id == workspace_id,
        Workspace.is_active.is_(True),
        Workspace.deleted_at.is_(None),
    ).one_or_none()
    if target is None:
        raise rollout.WorkspaceAppRolloutError("collector target is missing or inactive")
    marked = [
        workspace
        for workspace in db.query(Workspace).filter(
            Workspace.is_active.is_(True),
            Workspace.deleted_at.is_(None),
        ).all()
        if rollout._is_canary(workspace)
    ]
    if len(marked) != 1 or marked[0].id != target.id:
        raise rollout.WorkspaceAppRolloutError(
            "collector target must be the unique structurally marked Workspace"
        )
    return target


def collect_evidence(
    db: DBSession,
    *,
    phase: str,
    workspace_id: str,
    observation: Mapping[str, Any],
    playwright_junit: bytes,
    mode: str,
    validated_by: str,
    trusted_runner: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if mode not in {"local", "protected"}:
        raise rollout.WorkspaceAppRolloutError("collector mode must be local or protected")
    observation_kind, _test_name, checks, evidence_kind, suite_name = _phase_contract(phase)
    del observation_kind
    revision = rollout._runtime_revision()
    payload = _validate_observation(observation, phase=phase, revision=revision)
    _validate_playwright_junit(playwright_junit, phase=phase)
    source_junit_sha256 = hashlib.sha256(playwright_junit).hexdigest()
    source_junit = {
        "media_type": "application/junit+xml",
        "sha256": source_junit_sha256,
        "artifact_ref": f"sha256:{source_junit_sha256}",
    }
    workspace = _unique_canary(db, workspace_id)
    try:
        if phase == "preflight":
            if rollout._feature_enabled(workspace):
                raise rollout.WorkspaceAppRolloutError(
                    "preflight collection requires runtime authority to be disabled"
                )
            runtime = inspect_authoritative_workspace_app_runtime(workspace, db=db)
            probation_ref = None
        else:
            runtime = resolve_workspace_app_runtime(workspace, db=db)
            if runtime.rollout_phase != "probation" or runtime.rollout_ref is None:
                raise rollout.WorkspaceAppRolloutError(
                    "post-activation collection requires a live probation"
                )
            probation_ref = runtime.rollout_ref
    except WorkspaceAppRuntimeError as exc:
        raise rollout.WorkspaceAppRolloutError(
            f"Workspace App runtime cannot be collected: {exc.code}"
        ) from exc
    installations = workspace_app_installation_subject(runtime)
    installations_sha = workspace_app_installations_sha256(runtime)
    if not installations:
        raise rollout.WorkspaceAppRolloutError(
            "collector requires a nonempty installed application set"
        )
    if (
        payload["target"]["workspace_sha256"] != _id_sha256(workspace.id)
        or payload["target"]["installations_sha256"] != installations_sha
    ):
        raise rollout.WorkspaceAppRolloutError(
            "redacted observation target differs from the authoritative runtime"
        )
    if phase == "postactivation":
        if payload["target"].get("probation_ref") != probation_ref:
            raise rollout.WorkspaceAppRolloutError(
                "redacted observation belongs to a different probation"
            )
        state = rollout._state(workspace)
        probation = _record(state.get("probation"))
        generated_at = payload["generated_at"]
        if not (
            rollout._parse_utc(probation.get("staged_at"), field="staged_at")
            <= generated_at
            <= rollout._parse_utc(probation.get("expires_at"), field="expires_at")
        ):
            raise rollout.WorkspaceAppRolloutError(
                "post-activation observation is outside its probation"
            )
    observation_for_hash = {**payload, "generated_at": payload["generated_at"].isoformat()}
    observation_ref = f"sha256:{_canonical_sha256(observation_for_hash)}"
    runner = payload["runner"]
    promotable = bool(
        mode == "protected"
        and runner.get("protected_ci") is True
        and str(runner.get("pipeline_id") or "").strip()
        and str(runner.get("job_id") or "").strip()
        and all(payload["checks"].get(name) is True for name in checks)
    )
    if not promotable:
        return {
            "schema_version": 1,
            "kind": f"lot9_workspace_app_{phase}_local_collection",
            "status": "non_promotable",
            "revision": revision,
            "observation_ref": observation_ref,
            "workspace_sha256": _id_sha256(workspace.id),
            "installations_sha256": installations_sha,
            "reason": "protected phase-specific behaviour evidence is required",
        }
    actor = str(validated_by or "").strip()
    if not actor:
        raise rollout.WorkspaceAppRolloutError(
            "protected collection requires validated_by"
        )
    producer = rollout._validated_trusted_runner(trusted_runner, revision=revision)
    if (
        producer["pipeline_id"] != str(runner["pipeline_id"])
        or producer["job_id"] != str(runner["job_id"])
    ):
        raise rollout.WorkspaceAppRolloutError(
            "protected observation and OIDC producer identify different GitLab jobs"
        )
    subject: dict[str, Any] = {
        "workspace_id": workspace.id,
        "installations": installations,
        "installations_sha256": installations_sha,
    }
    if probation_ref is not None:
        subject["probation_ref"] = probation_ref
    return {
        "schema_version": rollout.EVIDENCE_SCHEMA_VERSION,
        "kind": evidence_kind,
        "activation_grade": True,
        "revision": revision,
        "generated_at": payload["generated_at"].isoformat(),
        "validated_by": actor,
        "observation_ref": observation_ref,
        "trusted_runner": producer,
        "source_junit": source_junit,
        "subject": subject,
        "checks": {name: True for name in checks},
        "runner_artifact": _canonical_runner_artifact(
            revision=revision,
            workspace_id=workspace.id,
            installations_sha256=installations_sha,
            checks=checks,
            suite_name=suite_name,
            observation_ref=observation_ref,
            probation_ref=probation_ref,
            source_junit_ref=source_junit["artifact_ref"],
        ),
    }


def _load_json(path: str) -> Mapping[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise rollout.WorkspaceAppRolloutError(f"cannot load observation: {exc}") from exc
    if not isinstance(value, Mapping):
        raise rollout.WorkspaceAppRolloutError("observation root must be an object")
    return value


def _protected_environment(revision: str, observation: Mapping[str, Any]) -> None:
    runner = _record(observation.get("runner"))
    if (
        os.getenv("CI") != "true"
        or os.getenv("CI_COMMIT_REF_PROTECTED") != "true"
        or str(os.getenv("CI_COMMIT_SHA") or "").lower() != revision
        or not os.getenv("CI_PIPELINE_ID")
        or not os.getenv("CI_JOB_ID")
        or runner.get("protected_ci") is not True
        or str(runner.get("pipeline_id") or "") != os.getenv("CI_PIPELINE_ID")
        or str(runner.get("job_id") or "") != os.getenv("CI_JOB_ID")
    ):
        raise rollout.WorkspaceAppRolloutError(
            "protected collection requires a protected CI job on the exact runtime revision"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("preflight", "postactivation"), required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--observation", required=True)
    parser.add_argument("--junit", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--mode", choices=("local", "protected"), default="local")
    parser.add_argument("--validated-by", default="")
    parser.add_argument(
        "--oidc-token-env",
        default="AGENTIUM_ATTESTATION_ID_TOKEN",
    )
    parser.add_argument("--oidc-audience")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        observation = _load_json(args.observation)
        junit = Path(args.junit).read_bytes()
        with SessionLocal() as db:
            trusted_runner = None
            if args.mode == "protected":
                _protected_environment(rollout._runtime_revision(), observation)
                trusted_runner = rollout._current_trusted_runner(
                    token_env=args.oidc_token_env,
                    audience=args.oidc_audience,
                )
            result = collect_evidence(
                db,
                phase=args.phase,
                workspace_id=args.workspace_id,
                observation=observation,
                playwright_junit=junit,
                mode=args.mode,
                validated_by=args.validated_by,
                trusted_runner=trusted_runner,
            )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        output.chmod(0o600)
        print(
            json.dumps(
                {
                    "status": result.get("status", "collected"),
                    "observation_ref": result["observation_ref"],
                    "output": str(output),
                },
                sort_keys=True,
            )
        )
        return 0
    except (OSError, rollout.WorkspaceAppRolloutError) as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - CLI boundary
    raise SystemExit(main())
