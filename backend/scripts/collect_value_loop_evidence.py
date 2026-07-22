#!/usr/bin/env python3
"""Collect redacted Lot 8 observations into activation-grade evidence.

The Playwright canary publishes only SHA-256 references.  This collector runs
next to the authoritative database, resolves those references back to one
tenant-scoped measured lifecycle, validates the original Playwright JUnit,
and emits the strict evidence contract consumed by ``rollout_value_loop``.

``local`` mode is deliberately non-promotable and never emits database ids.
``protected`` mode emits a 0600 evidence file containing the ids required for
transactional activation and is accepted by the CLI only in a protected CI
job testing the exact deployed revision.
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
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session as DBSession

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.base import SessionLocal  # noqa: E402
from app.models.decision import Decision  # noqa: E402
from app.models.run import Run  # noqa: E402
from app.models.value_loop import (  # noqa: E402
    ValueActionExecution,
    ValueMeasurement,
    ValueScenario,
    ValueSimulation,
)
from app.services.control_policy_snapshot import (  # noqa: E402
    validated_control_policy_execution_contract,
)
from app.services.run_outcome_provenance import (  # noqa: E402
    is_canary_authored_operator_outcome,
    run_measurement_provenance,
)
from scripts import rollout_value_loop as rollout  # noqa: E402

OBSERVATION_SCHEMA_VERSION = 2
OBSERVATION_KIND = "lot8_value_loop_observation"
OBSERVATION_CLAIM = "LOT8-AUTHORITATIVE-VALUE-LOOP"
CANARY_TEST_NAME = (
    "discovers one marked System and proves persisted simulate-to-measure semantics"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


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
        raise rollout.ValueLoopRolloutError(
            f"{field} fields differ from the contract; "
            f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
        )


def _sha(value: Any, *, field: str, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    normalized = str(value or "").strip().lower()
    if not SHA256_RE.fullmatch(normalized):
        raise rollout.ValueLoopRolloutError(f"{field} must be a lowercase SHA-256")
    return normalized


def _validate_observation(
    observation: Mapping[str, Any],
    *,
    revision: str,
) -> dict[str, Any]:
    payload = _record(observation)
    _exact_keys(
        payload,
        {
            "schema_version",
            "kind",
            "claim",
            "status",
            "promotion_eligible",
            "non_promotable_reason",
            "tested_revision",
            "runner",
            "contract_sha256",
            "target",
            "operations",
            "checks",
            "diagnostics",
            "generated_at",
        },
        field="observation",
    )
    if payload.get("schema_version") != OBSERVATION_SCHEMA_VERSION:
        raise rollout.ValueLoopRolloutError("observation schema_version must be 2")
    if payload.get("kind") != OBSERVATION_KIND or payload.get("claim") != OBSERVATION_CLAIM:
        raise rollout.ValueLoopRolloutError("observation identity differs from Lot 8")
    if payload.get("tested_revision") != revision:
        raise rollout.ValueLoopRolloutError(
            "observation revision differs from the deployed runtime revision"
        )
    generated_at = rollout._parse_utc(payload.get("generated_at"), field="generated_at")
    now = datetime.now(UTC)
    if generated_at > now + rollout.EVIDENCE_FUTURE_TOLERANCE:
        raise rollout.ValueLoopRolloutError("observation is dated in the future")
    if now - generated_at > rollout.EVIDENCE_MAX_AGE:
        raise rollout.ValueLoopRolloutError("observation is older than 24 hours")

    runner = _record(payload.get("runner"))
    _exact_keys(runner, {"protected_ci", "pipeline_id", "job_id"}, field="runner")
    target = _record(payload.get("target"))
    _exact_keys(
        target,
        {"workspace_sha256", "system_sha256", "baseline_run_sha256"},
        field="target",
    )
    operations = _record(payload.get("operations"))
    _exact_keys(
        operations,
        {
            "scenario_sha256",
            "decision_sha256",
            "simulation_sha256",
            "action_sha256",
            "measurement_sha256",
            "observed_run_sha256",
            "measurement_status",
        },
        field="operations",
    )
    for key, value in target.items():
        target[key] = _sha(value, field=f"target.{key}")
    for key in (
        "scenario_sha256",
        "decision_sha256",
        "simulation_sha256",
        "action_sha256",
        "measurement_sha256",
    ):
        operations[key] = _sha(operations.get(key), field=f"operations.{key}")
    operations["observed_run_sha256"] = _sha(
        operations.get("observed_run_sha256"),
        field="operations.observed_run_sha256",
        nullable=True,
    )
    checks = _record(payload.get("checks"))
    _exact_keys(checks, set(rollout.REQUIRED_CHECKS), field="checks")
    _sha(payload.get("contract_sha256"), field="contract_sha256")
    if not isinstance(payload.get("diagnostics"), Mapping):
        raise rollout.ValueLoopRolloutError("diagnostics must be an object")
    return {
        **payload,
        "runner": runner,
        "target": target,
        "operations": operations,
        "checks": checks,
        "generated_at": generated_at.isoformat(),
    }


def _validate_playwright_junit(content: bytes) -> None:
    if not content or len(content) > rollout.EVIDENCE_ARTIFACT_MAX_BYTES:
        raise rollout.ValueLoopRolloutError("Playwright JUnit has an invalid size")
    upper = content.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise rollout.ValueLoopRolloutError("Playwright JUnit XML declarations are forbidden")
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise rollout.ValueLoopRolloutError("Playwright JUnit is not valid XML") from exc
    if root.tag not in {"testsuite", "testsuites"}:
        raise rollout.ValueLoopRolloutError("Playwright JUnit root must be testsuite(s)")
    for suite in root.iter("testsuite"):
        try:
            failures = int(suite.get("failures", "0"))
            errors = int(suite.get("errors", "0"))
            skipped = int(suite.get("skipped", "0"))
        except ValueError as exc:
            raise rollout.ValueLoopRolloutError(
                "Playwright JUnit counters must be integers"
            ) from exc
        if failures or errors or skipped:
            raise rollout.ValueLoopRolloutError(
                "Playwright JUnit contains failed, errored or skipped tests"
            )
    cases = list(root.iter("testcase"))
    matching = [
        case
        for case in cases
        if CANARY_TEST_NAME in str(case.get("name") or "")
        or "13-lot8-value-loop-canary" in str(case.get("classname") or "")
    ]
    if len(matching) != 1:
        raise rollout.ValueLoopRolloutError(
            "Playwright JUnit must contain exactly one Lot 8 canary testcase"
        )
    case = matching[0]
    if any(case.find(name) is not None for name in ("failure", "error", "skipped")):
        raise rollout.ValueLoopRolloutError("the Lot 8 Playwright testcase did not pass")


def _find_by_hash(
    rows: Iterable[Any],
    expected_sha256: str,
    *,
    field: str,
) -> Any:
    matches = [row for row in rows if _id_sha256(row.id) == expected_sha256]
    if len(matches) != 1:
        raise rollout.ValueLoopRolloutError(
            f"server-side resolution for {field} expected one record, found {len(matches)}"
        )
    return matches[0]


def _resolve_records(
    db: DBSession,
    *,
    workspace_id: str,
    system_id: str,
    operations: Mapping[str, Any],
) -> tuple[dict[str, str], str | None]:
    scenario = _find_by_hash(
        db.query(ValueScenario).filter(
            ValueScenario.workspace_id == workspace_id,
            ValueScenario.system_id == system_id,
        ),
        str(operations["scenario_sha256"]),
        field="scenario",
    )
    decision = _find_by_hash(
        db.query(Decision).filter(
            Decision.workspace_id == workspace_id,
            Decision.scenario_id == scenario.id,
        ),
        str(operations["decision_sha256"]),
        field="decision",
    )
    simulation = _find_by_hash(
        db.query(ValueSimulation).filter(
            ValueSimulation.workspace_id == workspace_id,
            ValueSimulation.scenario_id == scenario.id,
        ),
        str(operations["simulation_sha256"]),
        field="simulation",
    )
    action = _find_by_hash(
        db.query(ValueActionExecution).filter(
            ValueActionExecution.workspace_id == workspace_id,
            ValueActionExecution.scenario_id == scenario.id,
        ),
        str(operations["action_sha256"]),
        field="action",
    )
    measurement = _find_by_hash(
        db.query(ValueMeasurement).filter(
            ValueMeasurement.workspace_id == workspace_id,
            ValueMeasurement.scenario_id == scenario.id,
        ),
        str(operations["measurement_sha256"]),
        field="measurement",
    )
    action_policy = validated_control_policy_execution_contract(
        (action.after_state or {}).get("_control_policy")
        if isinstance(action.after_state, Mapping)
        else None,
        policy_id=action.control_policy_id,
    )
    if action_policy is None:
        raise rollout.ValueLoopRolloutError(
            "action has no valid post-actuation ControlPolicy identity"
        )
    patch = action.patch if isinstance(action.patch, Mapping) else {}
    before_state = action.before_state if isinstance(action.before_state, Mapping) else {}
    after_state = action.after_state if isinstance(action.after_state, Mapping) else {}
    if not patch or not any(
        before_state.get(field) != after_state.get(field) == value
        for field, value in patch.items()
    ):
        raise rollout.ValueLoopRolloutError(
            "action evidence does not prove a changing ControlPolicy patch"
        )
    if measurement.action_execution_id != action.id:
        raise rollout.ValueLoopRolloutError(
            "measurement is not bound to the observed action execution"
        )
    if measurement.simulation_id != simulation.id:
        raise rollout.ValueLoopRolloutError(
            "measurement is not bound to the approved simulation"
        )
    evaluation = (
        measurement.assumption_evaluation
        if isinstance(measurement.assumption_evaluation, Mapping)
        else {}
    )
    if (
        measurement.assumption_verdict
        not in {
            "confirmed",
            "partially_confirmed",
            "not_confirmed",
            "not_evaluable",
        }
        or evaluation.get("verdict") != measurement.assumption_verdict
        or evaluation.get("causality") != "not_established"
    ):
        raise rollout.ValueLoopRolloutError(
            "measurement has no authoritative forecast assumption evaluation"
        )
    observed_sha = operations.get("observed_run_sha256")
    if measurement.source_run_id:
        observed = db.query(Run).filter(
            Run.id == measurement.source_run_id,
            Run.workspace_id == workspace_id,
            Run.system_id == system_id,
        ).one_or_none()
        if observed is None or _id_sha256(observed.id) != observed_sha:
            raise rollout.ValueLoopRolloutError(
                "server-side observed Run differs from the redacted observation"
            )
        execution = (
            observed.input_ref.get("execution")
            if isinstance(observed.input_ref, Mapping)
            else None
        )
        run_policy = validated_control_policy_execution_contract(
            execution.get("control_policy") if isinstance(execution, Mapping) else None
        )
        observed_outcome = (
            measurement.observed_outcome
            if isinstance(measurement.observed_outcome, Mapping)
            else {}
        )
        measured_policy = validated_control_policy_execution_contract(
            observed_outcome.get("control_policy")
        )
        if run_policy != action_policy or measured_policy != action_policy:
            raise rollout.ValueLoopRolloutError(
                "measured Run did not execute the post-actuation ControlPolicy"
            )
        if measurement.status == "measured":
            if not isinstance(measurement.forecast_delta, Mapping):
                raise rollout.ValueLoopRolloutError(
                    "measured outcome has no persisted forecast comparison"
                )
            if is_canary_authored_operator_outcome(observed):
                raise rollout.ValueLoopRolloutError(
                    "canary-authored operator outcome is not independent measurement evidence"
                )
            expected_provenance = run_measurement_provenance(observed)
            measured_provenance = observed_outcome.get("measurement_provenance")
            if expected_provenance is None or measured_provenance != expected_provenance:
                raise rollout.ValueLoopRolloutError(
                    "measured Run has no exact server-verifiable outcome provenance"
                )
    elif observed_sha is not None:
        raise rollout.ValueLoopRolloutError(
            "redacted observation references an absent measured Run"
        )
    return (
        {
            "scenario_id": scenario.id,
            "decision_id": decision.id,
            "simulation_id": simulation.id,
            "action_execution_id": action.id,
            "measurement_id": measurement.id,
        },
        measurement.status,
    )


def _canonical_runner_artifact(
    *,
    revision: str,
    workspace_id: str,
    system_id: str,
    observation_ref: str,
    source_junit_ref: str,
) -> dict[str, str]:
    root = ElementTree.Element(
        "testsuite",
        {
            "name": rollout.EVIDENCE_SUITE,
            "tests": str(len(rollout.REQUIRED_CHECKS)),
            "failures": "0",
            "errors": "0",
            "skipped": "0",
        },
    )
    properties = ElementTree.SubElement(root, "properties")
    for name, value in (
        ("revision", revision),
        ("workspace_id", workspace_id),
        ("system_id", system_id),
        ("observation_ref", observation_ref),
        ("source_junit_ref", source_junit_ref),
    ):
        ElementTree.SubElement(properties, "property", {"name": name, "value": value})
    for name in rollout.REQUIRED_CHECKS:
        ElementTree.SubElement(root, "testcase", {"classname": "lot8", "name": name})
    content = ElementTree.tostring(root, encoding="utf-8", xml_declaration=False)
    return {
        "format": "junit_xml",
        "content_base64": base64.b64encode(content).decode("ascii"),
        "artifact_ref": f"sha256:{hashlib.sha256(content).hexdigest()}",
    }


def collect_evidence(
    db: DBSession,
    *,
    workspace_id: str,
    observation: Mapping[str, Any],
    playwright_junit: bytes,
    mode: str,
    validated_by: str,
    trusted_runner: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if mode not in {"local", "protected"}:
        raise rollout.ValueLoopRolloutError("collector mode must be local or protected")
    revision = rollout._runtime_revision()
    payload = _validate_observation(observation, revision=revision)
    _validate_playwright_junit(playwright_junit)
    source_junit_sha256 = hashlib.sha256(playwright_junit).hexdigest()
    source_junit = {
        "media_type": "application/junit+xml",
        "sha256": source_junit_sha256,
        "artifact_ref": f"sha256:{source_junit_sha256}",
    }
    workspace, system, _derived = rollout.discover_target(
        db,
        workspace_id=workspace_id,
        allow_system360_fallback=False,
    )
    proof_window = None
    if mode == "protected":
        proof_window = rollout._active_proof_window(
            rollout._state(system),
            system_id=system.id,
            revision=revision,
        )
        if proof_window is None:
            raise rollout.ValueLoopRolloutError(
                "protected collection requires an active SHA-bound canary window"
            )
        generated_at = rollout._parse_utc(
            payload["generated_at"],
            field="generated_at",
        )
        opened_at = rollout._parse_utc(
            proof_window["opened_at"],
            field="proof_window.opened_at",
        )
        expires_at = rollout._parse_utc(
            proof_window["expires_at"],
            field="proof_window.expires_at",
        )
        if not opened_at <= generated_at < expires_at:
            raise rollout.ValueLoopRolloutError(
                "protected observation was not generated inside the canary window"
            )
    if (
        payload["target"]["workspace_sha256"] != _id_sha256(workspace.id)
        or payload["target"]["system_sha256"] != _id_sha256(system.id)
    ):
        raise rollout.ValueLoopRolloutError(
            "redacted observation target differs from the rollout target"
        )
    records, measurement_status = _resolve_records(
        db,
        workspace_id=workspace.id,
        system_id=system.id,
        operations=payload["operations"],
    )
    scenario = db.query(ValueScenario).filter_by(id=records["scenario_id"]).one()
    if _id_sha256(scenario.source_run_id) != payload["target"]["baseline_run_sha256"]:
        raise rollout.ValueLoopRolloutError(
            "server-side baseline Run differs from the redacted observation"
        )
    if proof_window is not None:
        opened_at = rollout._parse_utc(
            proof_window["opened_at"],
            field="proof_window.opened_at",
        )
        scenario_created_at = scenario.created_at
        if scenario_created_at is None:
            raise rollout.ValueLoopRolloutError("evidence scenario has no creation time")
        if scenario_created_at.tzinfo is None:
            scenario_created_at = scenario_created_at.replace(tzinfo=UTC)
        else:
            scenario_created_at = scenario_created_at.astimezone(UTC)
        if scenario_created_at < opened_at:
            raise rollout.ValueLoopRolloutError(
                "evidence scenario predates the active canary window"
            )
    observation_ref = f"sha256:{_canonical_sha256(payload)}"

    promotable = bool(
        mode == "protected"
        and payload.get("status") == "behavior_observed"
        and payload.get("promotion_eligible") is True
        and payload.get("non_promotable_reason") is None
        and payload["runner"].get("protected_ci") is True
        and payload["runner"].get("pipeline_id")
        and payload["runner"].get("job_id")
        and payload["operations"].get("measurement_status") == "measured"
        and measurement_status == "measured"
        and all(payload["checks"].get(name) is True for name in rollout.REQUIRED_CHECKS)
    )
    if not promotable:
        return {
            "schema_version": 1,
            "kind": "lot8_value_loop_local_collection",
            "status": "non_promotable",
            "revision": revision,
            "observation_ref": observation_ref,
            "measurement_status": measurement_status,
            "reason": str(
                payload.get("non_promotable_reason")
                or "protected measured behaviour evidence is required"
            ),
        }

    actor = str(validated_by or "").strip()
    if not actor:
        raise rollout.ValueLoopRolloutError("protected collection requires validated_by")
    producer = rollout._validated_trusted_runner(trusted_runner, revision=revision)
    if (
        producer["pipeline_id"] != str(payload["runner"]["pipeline_id"])
        or producer["job_id"] != str(payload["runner"]["job_id"])
    ):
        raise rollout.ValueLoopRolloutError(
            "protected observation and OIDC producer identify different GitLab jobs"
        )
    normalized = rollout._validated_records(
        db,
        workspace=workspace,
        system=system,
        records=records,
        lock=False,
    )
    return {
        "schema_version": rollout.EVIDENCE_SCHEMA_VERSION,
        "kind": rollout.EVIDENCE_KIND,
        "revision": revision,
        "validated_at": datetime.now(UTC).isoformat(),
        "validated_by": actor,
        "observation_ref": observation_ref,
        "subject": {"workspace_id": workspace.id, "system_id": system.id},
        "records": normalized,
        "checks": {name: True for name in rollout.REQUIRED_CHECKS},
        "trusted_runner": producer,
        "source_junit": source_junit,
        "runner_artifact": _canonical_runner_artifact(
            revision=revision,
            workspace_id=workspace.id,
            system_id=system.id,
            observation_ref=observation_ref,
            source_junit_ref=source_junit["artifact_ref"],
        ),
    }


def _load_json(path: str) -> Mapping[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise rollout.ValueLoopRolloutError(f"cannot load observation: {exc}") from exc
    if not isinstance(value, Mapping):
        raise rollout.ValueLoopRolloutError("observation root must be an object")
    return value


def _protected_environment(
    revision: str,
    observation: Mapping[str, Any],
) -> None:
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
        raise rollout.ValueLoopRolloutError(
            "protected collection requires a protected CI job on the exact runtime revision"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
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
                workspace_id=args.workspace_id,
                observation=observation,
                playwright_junit=junit,
                mode=args.mode,
                validated_by=args.validated_by,
                trusted_runner=trusted_runner,
            )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        output.chmod(0o600)
        print(
            json.dumps(
                {
                    "status": result["status"] if "status" in result else "collected",
                    "observation_ref": result["observation_ref"],
                    "output": str(output),
                },
                sort_keys=True,
            )
        )
        return 0
    except (OSError, rollout.ValueLoopRolloutError) as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - CLI boundary
    raise SystemExit(main())
