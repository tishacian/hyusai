#!/usr/bin/env python3
"""Attested, marker-discovered rollout for the Lot 7 object projectors.

The target is discovered exclusively from the existing System 360 marker.
No mutable workspace/System name or slug and no fixed database id is part of
the selection contract.  Commands are dry-run by default; every activation
requires an explicit ``--apply`` *and* a validation evidence document.

Example::

    python -m scripts.rollout_lot7_projections status \
        --workspace-id "$WORKSPACE_ID"
    python -m scripts.rollout_lot7_projections stage capability \
        --workspace-id "$WORKSPACE_ID" --apply --actor operator@example.net
    # Run the authenticated canary during the returned 30-minute lease, then:
    python -m scripts.rollout_lot7_projections finalize capability \
        --workspace-id "$WORKSPACE_ID" --evidence /path/to/capability-proof.json \
        --pilot-observation /path/to/capability-pilot.json \
        --apply --actor operator@example.net
    python -m scripts.rollout_lot7_projections deactivate capability \
        --workspace-id "$WORKSPACE_ID" --apply --actor operator@example.net

The order is fail-closed: Capability, then Run, then SkillInvocation.  Only a
hash and the non-sensitive validation metadata are persisted, never the raw
evidence document.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import re
import sys
import uuid
import xml.etree.ElementTree as ElementTree
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.db.base import SessionLocal  # noqa: E402
from app.models.audit import AuditLog  # noqa: E402
from app.models.capability import Capability  # noqa: E402
from app.models.run import Run, SkillInvocation  # noqa: E402
from app.models.skill import Skill  # noqa: E402
from app.models.system import System  # noqa: E402
from app.models.system_version import SystemVersion  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.services.audit_logger import emit_audit_event  # noqa: E402
from app.services.projection_gate import (  # noqa: E402
    FEATURE_BY_PROJECTION,
    PROBATION_MAX_LEASE,
    PROJECTION_FINALIZATION_AUDIT_EVENT,
    PROJECTION_ORDER,
    SYSTEM_CANARY_MARKER,
    SYSTEM_ROLLOUT_STATE_KEY,
    WORKSPACE_GATE_KEY,
    ProjectionGateError,
    authoritative_projection_enabled,
    projection_activation_audit_details,
    projection_activation_sha256,
    validated_gate_rows,
    with_projection_activation,
    with_projection_probation,
    without_projection_activation,
)
from scripts.rollout_authorization_v2 import (  # noqa: E402
    AuthorizationPromotionError,
    _trusted_runner_from_ci,
    _trusted_runner_metadata,
)

CANARY_MARKER = SYSTEM_CANARY_MARKER
ROLLOUT_STATE_KEY = SYSTEM_ROLLOUT_STATE_KEY
ROLLOUT_SCHEMA_VERSION = 1
EVIDENCE_SCHEMA_VERSION = 2
EVIDENCE_SOURCE_SCHEMA_VERSION = 1
EVIDENCE_SOURCE_KIND = "lot7_projection_behavior_source"
EVIDENCE_SUITE = "frontend-ng/e2e/tests/12-lot7-object-graph-canary.spec.ts"
EVIDENCE_LENSES = ("build", "operate", "steer", "govern")
EVIDENCE_JUNIT_SUITE = "lot7-object-graph-canary"
EVIDENCE_ARTIFACT_MAX_BYTES = 128 * 1024
EVIDENCE_MAX_AGE = timedelta(hours=24)
EVIDENCE_FUTURE_TOLERANCE = timedelta(minutes=5)
PILOT_OBSERVATION_SCHEMA_VERSION = 1
PILOT_OBSERVATION_KIND = "lot7_projection_pilot_observation"
PILOT_OBSERVATION_AUDIT_EVENT = "lot7.projection.pilot_observation_attested"
PILOT_PROFILES = frozenset(
    {"builder", "operator", "decision_owner", "governor", "transverse"}
)
PILOT_QUESTION_LENSES = EVIDENCE_LENSES
PILOT_MAX_QUESTION_SECONDS = 60.0
LOT6_PREREQUISITE_FLAGS = (
    "cockpit_router_axes_v4",
    "system_360_projection_v1",
)


class ProjectionRolloutError(ValueError):
    """Raised before an ambiguous, unauthenticated or out-of-order write."""


def _record(value: Any) -> dict[str, Any]:
    return copy.deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _experience(system: System) -> dict[str, Any]:
    return _record(_record(system.settings).get("experience"))


def _features(workspace: Workspace) -> tuple[dict[str, Any], dict[str, Any]]:
    settings = _record(workspace.settings)
    raw = settings.get("features")
    if raw is not None and not isinstance(raw, Mapping):
        raise ProjectionRolloutError("workspace settings.features must be an object")
    return settings, _record(raw)


def _feature(workspace: Workspace, projection: str) -> bool:
    _, features = _features(workspace)
    return bool(features.get(FEATURE_BY_PROJECTION[projection], False))


def _workspace_gate_rows(workspace: Workspace) -> dict[str, dict[str, Any]]:
    settings, _ = _features(workspace)
    gate = settings.get(WORKSPACE_GATE_KEY)
    if gate is None:
        return {}
    if not isinstance(gate, Mapping):
        raise ProjectionRolloutError("Lot 7 Workspace gate must be an object")
    try:
        return validated_gate_rows(gate)
    except ProjectionGateError as exc:
        raise ProjectionRolloutError(str(exc)) from exc


def _state(system: System) -> dict[str, Any]:
    state = _record(_record(system.settings).get(ROLLOUT_STATE_KEY))
    if not state:
        return {
            "schema_version": ROLLOUT_SCHEMA_VERSION,
            "activations": [],
            "probations": [],
            "deactivations": [],
        }
    if state.get("schema_version") != ROLLOUT_SCHEMA_VERSION:
        raise ProjectionRolloutError("unsupported Lot 7 projector rollout state")
    activations = state.get("activations")
    if not isinstance(activations, list) or any(
        not isinstance(item, Mapping) for item in activations
    ):
        raise ProjectionRolloutError("invalid Lot 7 projector activation history")
    state["activations"] = [dict(item) for item in activations]
    probations = state.get("probations", [])
    if not isinstance(probations, list) or any(
        not isinstance(item, Mapping) for item in probations
    ):
        raise ProjectionRolloutError("invalid Lot 7 projector probation history")
    if len(probations) > 1:
        raise ProjectionRolloutError("only one Lot 7 projector probation may be active")
    state["probations"] = [dict(item) for item in probations]
    deactivations = state.get("deactivations", [])
    if not isinstance(deactivations, list) or any(
        not isinstance(item, Mapping) for item in deactivations
    ):
        raise ProjectionRolloutError("invalid Lot 7 projector deactivation history")
    state["deactivations"] = [dict(item) for item in deactivations]
    return state


def _save_state(system: System, state: Mapping[str, Any]) -> None:
    settings = _record(system.settings)
    settings[ROLLOUT_STATE_KEY] = copy.deepcopy(dict(state))
    system.settings = settings


def discover_target(
    db: DBSession,
    *,
    workspace_id: str,
    lock: bool = False,
) -> tuple[Workspace, Capability, System]:
    """Resolve one marked canary inside one explicit Workspace boundary."""

    scoped_workspace_id = str(workspace_id or "").strip()
    if not scoped_workspace_id:
        raise ProjectionRolloutError("workspace_id is required")
    workspace_query = db.query(Workspace).filter(
        Workspace.id == scoped_workspace_id,
        Workspace.is_active.is_(True),
        Workspace.deleted_at.is_(None),
    )
    workspace = workspace_query.one_or_none()
    if workspace is None:
        raise ProjectionRolloutError("the target Workspace is missing or inactive")

    system_query = db.query(System).filter(
        System.workspace_id == workspace.id,
        System.status == "active",
    )
    marked = [
        system
        for system in system_query.all()
        if _experience(system).get("system_360_canary") == CANARY_MARKER
    ]
    if len(marked) != 1:
        raise ProjectionRolloutError(
            "expected exactly one active System 360 marker in Workspace "
            f"{workspace.id}, found {len(marked)}"
        )
    system = marked[0]
    if lock:
        # Discovery is read-only over the small candidate set; only the exact
        # subject is locked.  Locking every active Workspace/System would make
        # an unrelated rollout or request wait behind this transaction.
        workspace = (
            db.query(Workspace)
            .filter(
                Workspace.id == workspace.id,
                Workspace.is_active.is_(True),
                Workspace.deleted_at.is_(None),
            )
            .with_for_update(of=Workspace)
            .one_or_none()
        )
        if workspace is None:
            raise ProjectionRolloutError("the discovered Workspace changed while acquiring locks")
        system = (
            db.query(System)
            .filter(
                System.id == system.id,
                System.workspace_id == workspace.id,
                System.status == "active",
            )
            .with_for_update(of=System)
            .one_or_none()
        )
        if (
            system is None
            or _experience(system).get("system_360_canary") != CANARY_MARKER
        ):
            raise ProjectionRolloutError("the discovered canary changed while acquiring locks")
        # Recheck uniqueness after acquiring the subject locks.  This does not
        # broaden the lock footprint and fails closed on concurrent marker drift.
        current_markers = [
            candidate
            for candidate in db.query(System).filter(
                System.workspace_id == workspace.id,
                System.status == "active",
            ).all()
            if _experience(candidate).get("system_360_canary") == CANARY_MARKER
        ]
        if len(current_markers) != 1 or current_markers[0].id != system.id:
            raise ProjectionRolloutError("the canary marker set changed while acquiring locks")
    if not system.capability_id:
        raise ProjectionRolloutError("the marked System has no Capability")
    capability_query = db.query(Capability).filter(
        Capability.id == system.capability_id,
        or_(
            Capability.workspace_id == workspace.id,
            Capability.workspace_id.is_(None),
        ),
    )
    if lock:
        capability_query = capability_query.with_for_update(of=Capability)
    capabilities = capability_query.all()
    if len(capabilities) != 1:
        raise ProjectionRolloutError(
            "the marked System Capability is missing or crosses workspace scope"
        )
    return workspace, capabilities[0], system


def _activation_prefix(workspace: Workspace) -> int:
    values = [_feature(workspace, projection) for projection in PROJECTION_ORDER]
    seen_false = False
    for projection, enabled in zip(PROJECTION_ORDER, values, strict=True):
        if not enabled:
            seen_false = True
        elif seen_false:
            raise ProjectionRolloutError(
                "Lot 7 projector flags are not a contiguous Capability→Run→"
                f"SkillInvocation prefix (unexpected {projection}=true)"
            )
    return sum(values)


def _missing_lot6_prerequisites(workspace: Workspace) -> list[str]:
    _, features = _features(workspace)
    return [key for key in LOT6_PREREQUISITE_FLAGS if features.get(key) is not True]


def _parse_validated_at(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ProjectionRolloutError("validation evidence requires validated_at")
    value = raw.strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProjectionRolloutError("validated_at must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ProjectionRolloutError("validated_at must include a timezone")
    now = datetime.now(UTC)
    normalized = parsed.astimezone(UTC)
    if normalized > now + EVIDENCE_FUTURE_TOLERANCE:
        raise ProjectionRolloutError("validation evidence is dated in the future")
    if now - normalized > EVIDENCE_MAX_AGE:
        raise ProjectionRolloutError("validation evidence is older than 24 hours")
    return parsed.isoformat()


def _canonical_sha256(value: Any) -> str:
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _exact_keys(value: Mapping[str, Any], expected: set[str], *, field: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ProjectionRolloutError(
            f"{field} fields differ from the contract"
            + (f"; missing={missing}" if missing else "")
            + (f"; extra={extra}" if extra else "")
        )


def validate_pilot_observation(
    observation: Mapping[str, Any],
    *,
    projection: str,
    workspace: Workspace,
    capability: Capability,
    system: System,
    probation: Mapping[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate one uncoached, lease-bound four-question pilot observation.

    The raw human notes are never copied into rollout state.  Only their
    canonical content address and the non-sensitive threshold summary are
    persisted, so a later status can prove which exact observation opened the
    projection without turning System settings into a research notebook.
    """

    payload = _record(observation)
    _exact_keys(
        payload,
        {
            "schema_version",
            "kind",
            "subject",
            "observed_at",
            "participant",
            "uncoached",
            "questions",
        },
        field="pilot observation",
    )
    if payload.get("schema_version") != PILOT_OBSERVATION_SCHEMA_VERSION:
        raise ProjectionRolloutError("pilot observation schema_version must be 1")
    if payload.get("kind") != PILOT_OBSERVATION_KIND:
        raise ProjectionRolloutError(
            f"pilot observation kind must be {PILOT_OBSERVATION_KIND}"
        )

    subject = _record(payload.get("subject"))
    expected_subject = {
        "workspace_id": workspace.id,
        "system_id": system.id,
        "capability_id": capability.id,
        "projection": projection,
        "revision": probation.get("revision"),
        "lease_id": probation.get("lease_id"),
    }
    _exact_keys(subject, set(expected_subject), field="pilot observation subject")
    if subject != expected_subject:
        raise ProjectionRolloutError(
            "pilot observation subject must exactly match the active probation"
        )

    participant = _record(payload.get("participant"))
    _exact_keys(
        participant,
        {"id", "profile"},
        field="pilot observation participant",
    )
    participant_id = str(participant.get("id") or "").strip()
    if not 8 <= len(participant_id) <= 255:
        raise ProjectionRolloutError(
            "pilot observation participant.id must be an opaque stable identifier"
        )
    profile = str(participant.get("profile") or "").strip()
    if profile not in PILOT_PROFILES:
        raise ProjectionRolloutError(
            "pilot observation participant.profile must be a canonical profile"
        )
    if payload.get("uncoached") is not True:
        raise ProjectionRolloutError("pilot observation must be explicitly uncoached")

    observed_at = _parse_utc(
        payload.get("observed_at"),
        field="pilot observation observed_at",
    )
    staged_at = _parse_utc(probation.get("staged_at"), field="probation.staged_at")
    expires_at = _parse_utc(probation.get("expires_at"), field="probation.expires_at")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    if not staged_at <= observed_at < expires_at:
        raise ProjectionRolloutError(
            "pilot observation must be collected inside the active probation lease"
        )
    if observed_at > current:
        raise ProjectionRolloutError("pilot observation cannot be dated in the future")

    questions = payload.get("questions")
    if not isinstance(questions, list) or len(questions) != len(PILOT_QUESTION_LENSES):
        raise ProjectionRolloutError(
            "pilot observation must contain exactly four question results"
        )
    normalized: dict[str, dict[str, float | bool | str]] = {}
    for index, raw in enumerate(questions):
        if not isinstance(raw, Mapping):
            raise ProjectionRolloutError(
                f"pilot observation question {index} must be an object"
            )
        question = dict(raw)
        _exact_keys(
            question,
            {
                "lens",
                "success",
                "duration_seconds",
                "confidence",
                "critical_confusion",
            },
            field=f"pilot observation question {index}",
        )
        lens = str(question.get("lens") or "").strip()
        if lens not in PILOT_QUESTION_LENSES or lens in normalized:
            raise ProjectionRolloutError(
                "pilot observation questions must cover each canonical lens exactly once"
            )
        duration = question.get("duration_seconds")
        confidence = question.get("confidence")
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not 0 < float(duration) <= PILOT_MAX_QUESTION_SECONDS
        ):
            raise ProjectionRolloutError(
                f"pilot observation {lens} duration_seconds must be within (0, 60]"
            )
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 4 <= float(confidence) <= 5
        ):
            raise ProjectionRolloutError(
                f"pilot observation {lens} confidence must be within [4, 5]"
            )
        if question.get("success") is not True:
            raise ProjectionRolloutError(
                f"pilot observation {lens} did not answer the product question"
            )
        if question.get("critical_confusion") is not False:
            raise ProjectionRolloutError(
                f"pilot observation {lens} contains a critical confusion"
            )
        normalized[lens] = {
            "lens": lens,
            "success": True,
            "duration_seconds": float(duration),
            "confidence": float(confidence),
            "critical_confusion": False,
        }
    if set(normalized) != set(PILOT_QUESTION_LENSES):
        raise ProjectionRolloutError(
            "pilot observation questions must cover Build, Operate, Steer and Govern"
        )

    durations = [float(row["duration_seconds"]) for row in normalized.values()]
    confidences = [float(row["confidence"]) for row in normalized.values()]
    return {
        "observation_ref": f"sha256:{_canonical_sha256(payload)}",
        "participant_ref": f"sha256:{hashlib.sha256(participant_id.encode('utf-8')).hexdigest()}",
        "schema_version": PILOT_OBSERVATION_SCHEMA_VERSION,
        "kind": PILOT_OBSERVATION_KIND,
        "subject": expected_subject,
        "profile": profile,
        "observed_at": observed_at.isoformat(),
        "question_count": len(normalized),
        "uncoached": True,
        "success_count": len(normalized),
        "confidence_mean": sum(confidences) / len(confidences),
        "max_duration_seconds": max(durations),
        "critical_confusion_count": 0,
    }


def _required_sha256(value: Any, *, field: str) -> str:
    normalized = str(value or "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", normalized) is None:
        raise ProjectionRolloutError(f"{field} must be a SHA-256 digest")
    return normalized


def _database_utc(value: Any, *, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise ProjectionRolloutError(f"{field} is missing")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _runner_artifact_metadata(
    payload: Mapping[str, Any],
    source: Mapping[str, Any],
    *,
    revision: str,
    workspace: Workspace,
    capability: Capability,
    system: System,
    projection: str,
    probation: Mapping[str, Any],
    trusted_runner: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Decode, hash and parse the strict JUnit evidence produced by Playwright."""

    artifact = _record(payload.get("runner_artifact"))
    if artifact.get("format") != "junit_xml":
        raise ProjectionRolloutError("runner_artifact.format must be junit_xml")
    encoded = artifact.get("content_base64")
    if not isinstance(encoded, str) or not encoded:
        raise ProjectionRolloutError("runner_artifact.content_base64 is required")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ProjectionRolloutError(
            "runner_artifact.content_base64 is invalid"
        ) from exc
    if not content or len(content) > EVIDENCE_ARTIFACT_MAX_BYTES:
        raise ProjectionRolloutError("runner_artifact has an invalid size")
    artifact_ref = f"sha256:{hashlib.sha256(content).hexdigest()}"
    if artifact.get("artifact_ref") != artifact_ref:
        raise ProjectionRolloutError(
            "runner_artifact.artifact_ref differs from the supplied bytes"
        )
    if source.get("runner_artifact_ref") != artifact_ref:
        raise ProjectionRolloutError(
            "source_manifest.runner_artifact_ref differs from the JUnit artifact"
        )
    if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise ProjectionRolloutError("runner_artifact XML declarations are forbidden")
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise ProjectionRolloutError("runner_artifact is not valid XML") from exc
    if root.tag != "testsuite" or root.get("name") != EVIDENCE_JUNIT_SUITE:
        raise ProjectionRolloutError(
            f"runner_artifact must contain the {EVIDENCE_JUNIT_SUITE} testsuite"
        )
    counts: dict[str, int] = {}
    for field in ("tests", "failures", "errors", "skipped"):
        try:
            counts[field] = int(root.get(field, ""))
        except ValueError as exc:
            raise ProjectionRolloutError(
                f"runner_artifact testsuite.{field} must be an integer"
            ) from exc
    if (
        counts["tests"] < 1
        or counts["failures"] != 0
        or counts["errors"] != 0
        or counts["skipped"] != 0
    ):
        raise ProjectionRolloutError(
            "runner_artifact must contain tests with zero failures/errors/skips"
        )
    testcases = root.findall("./testcase")
    if len(testcases) != counts["tests"] or any(
        testcase.find("failure") is not None
        or testcase.find("error") is not None
        or testcase.find("skipped") is not None
        for testcase in testcases
    ):
        raise ProjectionRolloutError(
            "runner_artifact testcase results differ from its counters"
        )
    properties_node = root.find("./properties")
    property_nodes = (
        [] if properties_node is None else properties_node.findall("property")
    )
    property_names = [str(item.get("name") or "") for item in property_nodes]
    if "" in property_names or len(property_names) != len(set(property_names)):
        raise ProjectionRolloutError(
            "runner_artifact contains missing or duplicate property names"
        )
    properties = {
        name: str(item.get("value") or "")
        for name, item in zip(property_names, property_nodes, strict=True)
    }
    expected_properties = {
        "revision": revision,
        "workspace_id": workspace.id,
        "system_id": system.id,
        "capability_id": capability.id,
        "projection": projection,
        "lease_id": str(probation.get("lease_id") or ""),
    }
    if trusted_runner is not None:
        expected_properties.update(
            {
                "runner_project_id": str(trusted_runner.get("project_id") or ""),
                "runner_pipeline_id": str(trusted_runner.get("pipeline_id") or ""),
                "runner_job_id": str(trusted_runner.get("job_id") or ""),
            }
        )
    for key, expected in expected_properties.items():
        if properties.get(key) != expected:
            raise ProjectionRolloutError(
                f"runner_artifact property {key} differs from the rollout lease"
            )
    return {
        "runner_artifact_ref": artifact_ref,
        "runner_test_count": counts["tests"],
    }


def _runtime_source_metadata(
    db: DBSession,
    source: Mapping[str, Any],
    *,
    projection: str,
    workspace: Workspace,
    capability: Capability,
    system: System,
    revision: str,
    staged_at: datetime,
    validated_at: datetime,
    lock: bool,
) -> dict[str, Any]:
    """Revalidate the canary's content addresses against authoritative rows."""

    runtime = _record(source.get("runtime"))
    run_id = str(runtime.get("run_id") or "").strip()
    if not run_id:
        raise ProjectionRolloutError("source_manifest.runtime.run_id is required")
    run_query = db.query(Run).filter(
        Run.id == run_id,
        Run.workspace_id == workspace.id,
        Run.system_id == system.id,
        Run.capability_id == capability.id,
    )
    if lock:
        run_query = run_query.with_for_update(of=Run)
    run = run_query.one_or_none()
    if run is None:
        raise ProjectionRolloutError(
            "source_manifest.runtime.run_id does not resolve inside the rollout target"
        )
    if run.status != "completed" or run.error:
        raise ProjectionRolloutError("the attested Run must be successful")
    if runtime.get("status") != "completed":
        raise ProjectionRolloutError("source_manifest.runtime.status must be completed")

    run_started_at = _database_utc(run.started_at, field="Run.started_at")
    completed_at = _database_utc(run.completed_at, field="Run.completed_at")
    execution = _record(_record(run.input_ref).get("execution"))
    if execution.get("runtime_revision") != revision:
        raise ProjectionRolloutError(
            "the attested Run was not snapshotted by the evidence runtime SHA"
        )
    if runtime.get("runtime_revision") != revision:
        raise ProjectionRolloutError(
            "source_manifest.runtime.runtime_revision differs from the evidence SHA"
        )
    execution_snapshot_at = _parse_utc(
        execution.get("snapshot_at"),
        field="Run.input_ref.execution.snapshot_at",
    )
    if execution_snapshot_at < staged_at:
        raise ProjectionRolloutError("the attested Run predates the probation staged_at")
    if not run_started_at <= execution_snapshot_at <= completed_at <= validated_at:
        raise ProjectionRolloutError(
            "the attested Run completion is outside its execution/evidence window"
        )
    source_started_at = _parse_utc(
        runtime.get("started_at"),
        field="source_manifest.runtime.started_at",
    )
    source_completed_at = _parse_utc(
        runtime.get("completed_at"),
        field="source_manifest.runtime.completed_at",
    )
    source_execution_snapshot_at = _parse_utc(
        runtime.get("execution_snapshot_at"),
        field="source_manifest.runtime.execution_snapshot_at",
    )
    if source_started_at != run_started_at or source_completed_at != completed_at:
        raise ProjectionRolloutError(
            "source_manifest runtime timestamps differ from the persisted Run"
        )
    if source_execution_snapshot_at != execution_snapshot_at:
        raise ProjectionRolloutError(
            "source_manifest execution_snapshot_at differs from the persisted Run"
        )

    if not isinstance(run.flow_snapshot, Mapping) or not run.flow_snapshot:
        raise ProjectionRolloutError("the attested Run has no persisted flow_snapshot")
    flow_snapshot_sha256 = _canonical_sha256(run.flow_snapshot)
    if _required_sha256(
        runtime.get("flow_snapshot_sha256"),
        field="source_manifest.runtime.flow_snapshot_sha256",
    ) != flow_snapshot_sha256:
        raise ProjectionRolloutError(
            "source_manifest flow_snapshot digest differs from the persisted Run"
        )
    flow_version_id = str(runtime.get("flow_version_id") or "").strip()
    if not flow_version_id or run.flow_version_id != flow_version_id:
        raise ProjectionRolloutError(
            "source_manifest flow_version_id differs from the persisted Run"
        )
    version_query = db.query(SystemVersion).filter(
        SystemVersion.id == flow_version_id,
        SystemVersion.system_id == system.id,
        SystemVersion.workspace_id == workspace.id,
    )
    if lock:
        version_query = version_query.with_for_update(of=SystemVersion)
    version = version_query.one_or_none()
    if version is None:
        raise ProjectionRolloutError(
            "the attested Run flow_version_id is not exact for its System/Workspace"
        )
    if version.flow_definition != run.flow_snapshot:
        raise ProjectionRolloutError(
            "the attested SystemVersion does not equal the Run flow_snapshot"
        )
    if _database_utc(
        version.created_at,
        field="SystemVersion.created_at",
    ) > execution_snapshot_at:
        raise ProjectionRolloutError(
            "the attested SystemVersion was created after the execution snapshot"
        )

    invocation_query = db.query(SkillInvocation).filter(
        SkillInvocation.run_id == run.id,
    )
    if lock:
        invocation_query = invocation_query.with_for_update(of=SkillInvocation)
    invocations = invocation_query.order_by(
        SkillInvocation.started_at.asc(),
        SkillInvocation.id.asc(),
    ).all()
    source_invocations = runtime.get("invocations")
    if not isinstance(source_invocations, list) or not source_invocations:
        raise ProjectionRolloutError(
            "source_manifest.runtime.invocations must contain the full invocation ledger"
        )
    if any(not isinstance(item, Mapping) for item in source_invocations):
        raise ProjectionRolloutError(
            "source_manifest.runtime.invocations must contain only objects"
        )
    source_by_id = {
        str(item.get("id") or "").strip(): dict(item)
        for item in source_invocations
    }
    if "" in source_by_id or len(source_by_id) != len(source_invocations):
        raise ProjectionRolloutError(
            "source_manifest.runtime.invocations contains missing or duplicate ids"
        )
    if set(source_by_id) != {item.id for item in invocations} or not invocations:
        raise ProjectionRolloutError(
            "source_manifest.runtime.invocations is not the exact persisted ledger"
        )
    for invocation in invocations:
        item = source_by_id[invocation.id]
        if invocation.status != "completed" or invocation.error:
            raise ProjectionRolloutError(
                f"SkillInvocation {invocation.id} is not successful"
            )
        snapshot = invocation.execution_snapshot
        if not isinstance(snapshot, Mapping) or snapshot.get("resolution") != "resolved":
            raise ProjectionRolloutError(
                f"SkillInvocation {invocation.id} has no resolved execution_snapshot"
            )
        if item.get("status") != "completed" or item.get("resolution") != "resolved":
            raise ProjectionRolloutError(
                f"source_manifest SkillInvocation {invocation.id} is not resolved/completed"
            )
        if _required_sha256(
            item.get("execution_snapshot_sha256"),
            field=(
                "source_manifest.runtime.invocations."
                f"{invocation.id}.execution_snapshot_sha256"
            ),
        ) != _canonical_sha256(snapshot):
            raise ProjectionRolloutError(
                f"source_manifest SkillInvocation {invocation.id} digest differs from storage"
            )

    primary_invocation_id = str(runtime.get("primary_invocation_id") or "").strip()
    if primary_invocation_id not in source_by_id:
        raise ProjectionRolloutError(
            "source_manifest.runtime.primary_invocation_id is not in the ledger"
        )
    primary = next(item for item in invocations if item.id == primary_invocation_id)
    primary_snapshot = _record(primary.execution_snapshot)
    snapshot_skill = _record(primary_snapshot.get("skill"))
    catalog_skill_id = str(runtime.get("catalog_skill_id") or "").strip()
    if not catalog_skill_id or snapshot_skill.get("id") != catalog_skill_id:
        raise ProjectionRolloutError(
            "source_manifest catalog Skill does not match the immutable invocation snapshot"
        )
    if catalog_skill_id == primary.id:
        raise ProjectionRolloutError("catalog Skill and SkillInvocation identities collapsed")
    visible_skill = (
        db.query(Skill)
        .filter(
            Skill.id == catalog_skill_id,
            or_(Skill.workspace_id == workspace.id, Skill.workspace_id.is_(None)),
        )
        .one_or_none()
    )
    if visible_skill is None:
        raise ProjectionRolloutError(
            "source_manifest catalog Skill is not visible in the target Workspace"
        )

    return {
        "run_id": run.id,
        "flow_version_id": version.id,
        "flow_snapshot_sha256": flow_snapshot_sha256,
        "primary_invocation_id": primary.id,
        "invocation_count": len(invocations),
    }


def validate_evidence(
    db: DBSession,
    evidence: Mapping[str, Any],
    *,
    projection: str,
    workspace: Workspace,
    capability: Capability,
    system: System,
    probation: Mapping[str, Any],
    trusted_runner: Mapping[str, Any] | None = None,
    lock_runtime: bool = False,
) -> dict[str, Any]:
    """Revalidate a content-addressed behavioural proof against live storage."""

    payload = _record(evidence)
    if payload.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        raise ProjectionRolloutError(
            f"validation evidence schema_version must be {EVIDENCE_SCHEMA_VERSION}"
        )
    if payload.get("result") != "passed":
        raise ProjectionRolloutError("validation evidence result must be passed")
    subject = _record(payload.get("subject"))
    expected_subject = {
        "workspace_id": workspace.id,
        "system_id": system.id,
        "capability_id": capability.id,
        "projection": projection,
    }
    for key, expected in expected_subject.items():
        if subject.get(key) != expected:
            raise ProjectionRolloutError(
                f"validation evidence subject.{key} does not match discovered target"
            )
    validated_by = str(payload.get("validated_by") or "").strip()
    if not validated_by:
        raise ProjectionRolloutError("validation evidence requires validated_by")
    validated_at = _parse_validated_at(payload.get("validated_at"))
    revision = str(payload.get("revision") or "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise ProjectionRolloutError(
            "validation evidence revision must be the exact 40-character Git SHA"
        )
    environment = str(payload.get("environment") or "").strip()
    if not environment:
        raise ProjectionRolloutError("validation evidence requires environment")

    source = _record(payload.get("source_manifest"))
    if source.get("schema_version") != EVIDENCE_SOURCE_SCHEMA_VERSION:
        raise ProjectionRolloutError("source_manifest.schema_version must be 1")
    if source.get("kind") != EVIDENCE_SOURCE_KIND:
        raise ProjectionRolloutError(
            f"source_manifest.kind must be {EVIDENCE_SOURCE_KIND}"
        )
    if _record(source.get("subject")) != expected_subject:
        raise ProjectionRolloutError(
            "source_manifest.subject must exactly match the rollout subject"
        )
    source_ref = str(payload.get("source_ref") or "").strip().lower()
    expected_source_ref = f"sha256:{_canonical_sha256(source)}"
    if source_ref != expected_source_ref:
        raise ProjectionRolloutError(
            "source_ref does not match the canonical source_manifest"
        )

    build_info = _record(source.get("build_info"))
    for service in ("backend", "frontend"):
        row = _record(build_info.get(service))
        if row != {
            "revision": revision,
            "service": service,
            "revision_verified": True,
        }:
            raise ProjectionRolloutError(
                f"source_manifest.build_info.{service} does not attest the target SHA"
            )
    projection_hashes = _record(source.get("projection_sha256"))
    if set(projection_hashes) != set(EVIDENCE_LENSES):
        raise ProjectionRolloutError(
            "source_manifest.projection_sha256 must contain exactly four lenses"
        )
    normalized_projection_hashes = {
        lens: _required_sha256(
            projection_hashes.get(lens),
            field=f"source_manifest.projection_sha256.{lens}",
        )
        for lens in EVIDENCE_LENSES
    }
    if len(set(normalized_projection_hashes.values())) != len(EVIDENCE_LENSES):
        raise ProjectionRolloutError("the four projection sources are not distinct")
    rendered_fact_sources = _record(source.get("rendered_fact_sources"))
    if set(rendered_fact_sources) != set(EVIDENCE_LENSES):
        raise ProjectionRolloutError(
            "source_manifest.rendered_fact_sources must contain exactly four lenses"
        )
    normalized_fact_hashes: dict[str, dict[str, str]] = {}
    allowed_fact_states = {
        "available",
        "not_measured",
        "not_configured",
        "restricted",
        "unavailable",
    }
    for lens in EVIDENCE_LENSES:
        fact = _record(rendered_fact_sources.get(lens))
        for field in ("block_id", "fact_key", "fact_label"):
            if not str(fact.get(field) or "").strip():
                raise ProjectionRolloutError(
                    f"source_manifest.rendered_fact_sources.{lens}.{field} is required"
                )
        if fact.get("fact_state") not in allowed_fact_states:
            raise ProjectionRolloutError(
                f"source_manifest.rendered_fact_sources.{lens}.fact_state is invalid"
            )
        normalized_fact_hashes[lens] = {
            "api_fact_sha256": _required_sha256(
                fact.get("api_fact_sha256"),
                field=(
                    "source_manifest.rendered_fact_sources."
                    f"{lens}.api_fact_sha256"
                ),
            ),
            "rendered_text_sha256": _required_sha256(
                fact.get("rendered_text_sha256"),
                field=(
                    "source_manifest.rendered_fact_sources."
                    f"{lens}.rendered_text_sha256"
                ),
            ),
        }
    invariant_chrome_sha256 = _required_sha256(
        source.get("invariant_chrome_sha256"),
        field="source_manifest.invariant_chrome_sha256",
    )
    if source.get("suite") != EVIDENCE_SUITE:
        raise ProjectionRolloutError("source_manifest.suite is not the protected canary")

    gate_off_workspace_id = str(source.get("gate_off_workspace_id") or "").strip()
    if not gate_off_workspace_id or gate_off_workspace_id == workspace.id:
        raise ProjectionRolloutError(
            "source_manifest requires a distinct gate-off Workspace"
        )
    gate_off_workspace = (
        db.query(Workspace)
        .filter(
            Workspace.id == gate_off_workspace_id,
            Workspace.is_active.is_(True),
            Workspace.deleted_at.is_(None),
        )
        .one_or_none()
    )
    if gate_off_workspace is None or _feature(gate_off_workspace, projection):
        raise ProjectionRolloutError(
            "source_manifest gate-off Workspace is missing or has the projection enabled"
        )

    validated_at_dt = _parse_utc(validated_at, field="validated_at")
    staged_at = _parse_utc(probation.get("staged_at"), field="probation.staged_at")
    runtime_metadata = _runtime_source_metadata(
        db,
        source,
        projection=projection,
        workspace=workspace,
        capability=capability,
        system=system,
        revision=revision,
        staged_at=staged_at,
        validated_at=validated_at_dt,
        lock=lock_runtime,
    )
    artifact_metadata = _runner_artifact_metadata(
        payload,
        source,
        revision=revision,
        workspace=workspace,
        capability=capability,
        system=system,
        projection=projection,
        probation=probation,
        trusted_runner=trusted_runner,
    )

    metadata = {
        "evidence_sha256": _canonical_sha256(payload),
        "source_ref": source_ref,
        "validated_by": validated_by,
        "validated_at": validated_at,
        "revision": revision,
        "environment": environment,
        "projection_sha256": normalized_projection_hashes,
        "rendered_fact_sha256": normalized_fact_hashes,
        "invariant_chrome_sha256": invariant_chrome_sha256,
        **runtime_metadata,
        **artifact_metadata,
        "verification_state": "operator_validated",
    }
    if trusted_runner is not None:
        try:
            metadata["trusted_runner"] = _trusted_runner_metadata(
                trusted_runner,
                revision=revision,
            )
        except AuthorizationPromotionError as exc:
            raise ProjectionRolloutError(f"untrusted projection runner: {exc}") from exc
        metadata["verification_state"] = "runner_verified"
    return metadata


def _persisted_activation(state: Mapping[str, Any], projection: str) -> dict[str, Any] | None:
    matches = [
        dict(item)
        for item in state.get("activations", [])
        if isinstance(item, Mapping) and item.get("projection") == projection
    ]
    if len(matches) > 1:
        raise ProjectionRolloutError(f"duplicate persisted evidence for {projection}")
    return matches[0] if matches else None


def _persisted_probation(state: Mapping[str, Any], projection: str) -> dict[str, Any] | None:
    matches = [
        dict(item)
        for item in state.get("probations", [])
        if isinstance(item, Mapping) and item.get("projection") == projection
    ]
    if len(matches) > 1:
        raise ProjectionRolloutError(f"duplicate persisted probation for {projection}")
    return matches[0] if matches else None


def _persisted_pilot_is_valid(
    value: Any,
    *,
    db: DBSession,
    workspace_id: str,
    expected_subject: Mapping[str, Any],
    expected_runner: Mapping[str, Any],
) -> bool:
    pilot = _record(value)
    try:
        confidence = float(pilot.get("confidence_mean"))
        duration = float(pilot.get("max_duration_seconds"))
        _parse_utc(pilot.get("observed_at"), field="pilot observation observed_at")
    except (ProjectionRolloutError, TypeError, ValueError):
        return False
    structurally_valid = bool(
        re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            str(pilot.get("observation_ref") or ""),
        )
        and re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            str(pilot.get("participant_ref") or ""),
        )
        and str(pilot.get("audit_id") or "").strip()
        and pilot.get("schema_version") == PILOT_OBSERVATION_SCHEMA_VERSION
        and pilot.get("kind") == PILOT_OBSERVATION_KIND
        and pilot.get("subject") == dict(expected_subject)
        and pilot.get("profile") in PILOT_PROFILES
        and pilot.get("question_count") == 4
        and pilot.get("success_count") == 4
        and pilot.get("uncoached") is True
        and 4 <= confidence <= 5
        and 0 < duration <= PILOT_MAX_QUESTION_SECONDS
        and pilot.get("critical_confusion_count") == 0
    )
    if not structurally_valid:
        return False
    audit = (
        db.query(AuditLog)
        .filter(
            AuditLog.id == pilot.get("audit_id"),
            AuditLog.workspace_id == workspace_id,
            AuditLog.event_type == PILOT_OBSERVATION_AUDIT_EVENT,
        )
        .one_or_none()
    )
    if audit is None or audit.agent_id != expected_subject.get("system_id"):
        return False
    details = _record(audit.details)
    return details == {
        "schema_version": PILOT_OBSERVATION_SCHEMA_VERSION,
        "subject": dict(expected_subject),
        "observation_ref": pilot.get("observation_ref"),
        "participant_ref": pilot.get("participant_ref"),
        "profile": pilot.get("profile"),
        "trusted_runner": dict(expected_runner),
    }


def _validate_workspace_gate_alignment(
    workspace: Workspace,
    state: Mapping[str, Any],
    *,
    capability: Capability,
    system: System,
) -> None:
    gate_rows = _workspace_gate_rows(workspace)
    for projection in PROJECTION_ORDER:
        evidence = _persisted_activation(state, projection)
        probation = _persisted_probation(state, projection)
        enabled = _feature(workspace, projection)
        gate = gate_rows.get(projection)
        if evidence is not None and probation is not None:
            raise ProjectionRolloutError(
                f"{projection} cannot be both probationary and verified"
            )
        persisted = evidence or probation
        if not (enabled == (persisted is not None) == (gate is not None)):
            raise ProjectionRolloutError(
                f"{projection} feature/evidence/Workspace-gate state diverged"
            )
        if persisted is None or gate is None:
            continue
        if probation is not None:
            expected = {
                "projection": projection,
                "feature": FEATURE_BY_PROJECTION[projection],
                "phase": "probation",
                "revision": probation.get("revision"),
                "system_id": system.id,
                "capability_id": capability.id,
                "staged_at": probation.get("staged_at"),
                "expires_at": probation.get("expires_at"),
                "lease_id": probation.get("lease_id"),
            }
        else:
            expected = {
                "projection": projection,
                "feature": FEATURE_BY_PROJECTION[projection],
                "phase": "verified",
                "evidence_sha256": evidence.get("evidence_sha256"),
                "revision": evidence.get("revision"),
                "system_id": system.id,
                "capability_id": capability.id,
            }
        legacy_expected = dict(expected)
        legacy_expected.pop("phase", None)
        if gate != expected and not (
            evidence is not None and gate == legacy_expected
        ):
            raise ProjectionRolloutError(
                f"{projection} Workspace gate differs from persisted validation evidence"
            )


def _runtime_revision() -> str:
    revision = str(settings.agentium_image_revision or "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise ProjectionRolloutError(
            "the deployed runtime must expose its exact 40-character Git SHA"
        )
    return revision


def _parse_utc(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ProjectionRolloutError(f"{field} is missing")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProjectionRolloutError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ProjectionRolloutError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def stage(
    db: DBSession,
    *,
    workspace_id: str,
    projection: str,
    apply: bool,
    actor: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Open exactly one short probation window for the deployed SHA."""

    if projection not in PROJECTION_ORDER:
        raise ProjectionRolloutError(f"unknown projection: {projection}")
    workspace, capability, system = discover_target(
        db,
        workspace_id=workspace_id,
        lock=apply,
    )
    missing_prerequisites = _missing_lot6_prerequisites(workspace)
    if missing_prerequisites:
        raise ProjectionRolloutError(
            "Lot 6 prerequisites are not active: " + ", ".join(missing_prerequisites)
        )
    state = _state(system)
    _validate_workspace_gate_alignment(
        workspace,
        state,
        capability=capability,
        system=system,
    )
    revision = _runtime_revision()
    prefix = _activation_prefix(workspace)
    target_index = PROJECTION_ORDER.index(projection)
    activation = _persisted_activation(state, projection)
    probation = _persisted_probation(state, projection)
    current = (now or datetime.now(UTC)).astimezone(UTC)
    report: dict[str, Any] = {
        "schema_version": 1,
        "operation": "apply" if apply else "dry_run",
        "direction": "stage",
        "projection": projection,
        "feature": FEATURE_BY_PROJECTION[projection],
        "workspace_id": workspace.id,
        "capability_id": capability.id,
        "system_id": system.id,
        "revision": revision,
        "lease_seconds": int(PROBATION_MAX_LEASE.total_seconds()),
        "changed": activation is None and probation is None,
    }
    if activation is not None:
        report.update({"changed": False, "already_verified": True})
        return report
    if probation is not None:
        expires_at = _parse_utc(probation.get("expires_at"), field="probation.expires_at")
        if probation.get("revision") != revision:
            raise ProjectionRolloutError(
                "the existing probation belongs to a different runtime SHA; abort it first"
            )
        if current >= expires_at:
            raise ProjectionRolloutError("the existing probation expired; abort it first")
        report.update({"changed": False, "already_staged": True, "probation": probation})
        return report
    if target_index != prefix:
        expected = PROJECTION_ORDER[prefix] if prefix < len(PROJECTION_ORDER) else "none"
        raise ProjectionRolloutError(f"out-of-order staging: next projection must be {expected}")
    staged_at = current
    expires_at = current + PROBATION_MAX_LEASE
    lease_id = str(uuid.uuid4())
    probation = {
        "projection": projection,
        "feature": FEATURE_BY_PROJECTION[projection],
        "phase": "probation",
        "revision": revision,
        "system_id": system.id,
        "capability_id": capability.id,
        "staged_by": str(actor or "").strip(),
        "staged_at": staged_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "lease_id": lease_id,
    }
    report["probation"] = probation
    if not apply:
        return report
    if not probation["staged_by"]:
        raise ProjectionRolloutError("--apply requires a non-empty actor")
    try:
        workspace.settings = with_projection_probation(
            workspace.settings,
            projection=projection,
            revision=revision,
            system_id=system.id,
            capability_id=capability.id,
            staged_at=staged_at,
            expires_at=expires_at,
            lease_id=lease_id,
        )
    except ProjectionGateError as exc:
        raise ProjectionRolloutError(str(exc)) from exc
    state["probations"].append(probation)
    _save_state(system, state)
    audit_id = emit_audit_event(
        workspace_id=workspace.id,
        event_type="lot7.projection.probation_staged",
        actor=probation["staged_by"],
        agent_id=system.id,
        details={
            "system_id": system.id,
            "capability_id": capability.id,
            "projection": projection,
            "feature": FEATURE_BY_PROJECTION[projection],
            "revision": revision,
            "expires_at": expires_at.isoformat(),
            "lease_id": lease_id,
        },
        db=db,
    )
    if audit_id is None:
        raise ProjectionRolloutError("the probation audit event could not be persisted")
    db.commit()
    return report


def activate(
    db: DBSession,
    *,
    workspace_id: str,
    projection: str,
    evidence: Mapping[str, Any] | None,
    apply: bool,
    actor: str,
    pilot_observation: Mapping[str, Any] | None = None,
    trusted_runner: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Finalize a live probation using its authenticated canary evidence."""

    if projection not in PROJECTION_ORDER:
        raise ProjectionRolloutError(f"unknown projection: {projection}")
    workspace, capability, system = discover_target(
        db,
        workspace_id=workspace_id,
        lock=apply,
    )
    missing_prerequisites = _missing_lot6_prerequisites(workspace)
    if missing_prerequisites:
        raise ProjectionRolloutError(
            "Lot 6 prerequisites are not active: "
            + ", ".join(missing_prerequisites)
        )
    prefix = _activation_prefix(workspace)
    target_index = PROJECTION_ORDER.index(projection)
    state = _state(system)
    _validate_workspace_gate_alignment(
        workspace,
        state,
        capability=capability,
        system=system,
    )
    persisted = _persisted_activation(state, projection)
    probation = _persisted_probation(state, projection)
    enabled = _feature(workspace, projection)
    report: dict[str, Any] = {
        "schema_version": 1,
        "operation": "apply" if apply else "dry_run",
        "projection": projection,
        "feature": FEATURE_BY_PROJECTION[projection],
        "workspace_id": workspace.id,
        "capability_id": capability.id,
        "system_id": system.id,
        "changed": probation is not None,
        "validation_required": evidence is None and probation is not None,
        "pilot_observation_required": (
            pilot_observation is None and probation is not None
        ),
    }

    if persisted is not None:
        if not enabled:
            raise ProjectionRolloutError(f"{projection} is verified but disabled")
        report.update({"changed": False, "already_active": True, "validation": persisted})
        return report
    if probation is None or not enabled:
        raise ProjectionRolloutError(
            f"{projection} must be staged before validation can be finalized"
        )
    if target_index != prefix - 1:
        expected = PROJECTION_ORDER[prefix - 1] if prefix else "none"
        raise ProjectionRolloutError(
            f"out-of-order finalization: probation tail must be {expected}"
        )
    now = datetime.now(UTC)
    expires_at = _parse_utc(probation.get("expires_at"), field="probation.expires_at")
    if now >= expires_at:
        raise ProjectionRolloutError("the probation expired before validation finalized")
    runtime_revision = _runtime_revision()
    if probation.get("revision") != runtime_revision:
        raise ProjectionRolloutError("the probation belongs to a different runtime SHA")

    metadata = None
    pilot_metadata = None
    if evidence is not None:
        metadata = validate_evidence(
            db,
            evidence,
            projection=projection,
            workspace=workspace,
            capability=capability,
            system=system,
            probation=probation,
            trusted_runner=trusted_runner,
            lock_runtime=apply,
        )
        if metadata.get("revision") != probation.get("revision"):
            raise ProjectionRolloutError(
                "validation evidence revision differs from the probation runtime SHA"
            )
        gate_evidence = _record(
            _record(evidence.get("source_manifest")).get("gate")
        )
        if gate_evidence.get("phase") != "probation":
            raise ProjectionRolloutError(
                "validation evidence must attest the probation gate phase"
            )
        if gate_evidence.get("lease_id") != probation.get("lease_id"):
            raise ProjectionRolloutError(
                "validation evidence lease_id differs from the active probation"
            )
        if gate_evidence.get("revision") != probation.get("revision"):
            raise ProjectionRolloutError(
                "validation evidence gate revision differs from the active probation"
            )
        for field in ("staged_at", "expires_at"):
            if gate_evidence.get(field) != probation.get(field):
                raise ProjectionRolloutError(
                    f"validation evidence gate {field} differs from the active probation"
                )
        validated_at = _parse_utc(metadata.get("validated_at"), field="validated_at")
        staged_at = _parse_utc(probation.get("staged_at"), field="probation.staged_at")
        if not staged_at <= validated_at < expires_at:
            raise ProjectionRolloutError(
                "validation evidence was not produced inside the probation lease"
            )
        report["validation"] = metadata
        report["validation_required"] = False
    if pilot_observation is not None:
        pilot_metadata = validate_pilot_observation(
            pilot_observation,
            projection=projection,
            workspace=workspace,
            capability=capability,
            system=system,
            probation=probation,
        )
        report["pilot_observation"] = pilot_metadata
        report["pilot_observation_required"] = False
    if not apply:
        return report
    if metadata is None:
        raise ProjectionRolloutError(f"--apply for {projection} requires validation evidence")
    if pilot_metadata is None:
        raise ProjectionRolloutError(
            f"--apply for {projection} requires a valid pilot observation"
        )
    actor_value = str(actor or "").strip()
    if not actor_value:
        raise ProjectionRolloutError("--apply requires a non-empty actor")
    runner_metadata = _record(metadata.get("trusted_runner"))
    if not runner_metadata:
        raise ProjectionRolloutError(
            "--apply finalization requires a protected GitLab OIDC runner"
        )

    try:
        pilot_audit_id = emit_audit_event(
            workspace_id=workspace.id,
            event_type=PILOT_OBSERVATION_AUDIT_EVENT,
            actor=actor_value,
            agent_id=system.id,
            details={
                "schema_version": PILOT_OBSERVATION_SCHEMA_VERSION,
                "subject": pilot_metadata["subject"],
                "observation_ref": pilot_metadata["observation_ref"],
                "participant_ref": pilot_metadata["participant_ref"],
                "profile": pilot_metadata["profile"],
                "trusted_runner": runner_metadata,
            },
            db=db,
        )
        if pilot_audit_id is None:
            raise ProjectionRolloutError(
                "the authenticated pilot observation could not be persisted"
            )
        pilot_metadata = {**pilot_metadata, "audit_id": pilot_audit_id}
        report["pilot_observation"] = pilot_metadata

        activation = {
            "projection": projection,
            "feature": FEATURE_BY_PROJECTION[projection],
            "system_id": system.id,
            "capability_id": capability.id,
            **metadata,
            "pilot_observation": pilot_metadata,
            "activated_by": actor_value,
            "activated_at": datetime.now(UTC).isoformat(),
            "probation_lease_id": probation.get("lease_id"),
        }
        activation["activation_sha256"] = projection_activation_sha256(activation)
        next_workspace_settings = with_projection_activation(
            workspace.settings,
            projection=projection,
            evidence_sha256=metadata["evidence_sha256"],
            revision=metadata["revision"],
            system_id=system.id,
            capability_id=capability.id,
        )
        audit_id = emit_audit_event(
            workspace_id=workspace.id,
            event_type=PROJECTION_FINALIZATION_AUDIT_EVENT,
            actor=actor_value,
            agent_id=system.id,
            details=projection_activation_audit_details(activation),
            db=db,
        )
        if audit_id is None:
            raise ProjectionRolloutError(
                "the activation audit event could not be persisted"
            )
        activation["audit_id"] = audit_id
        workspace.settings = next_workspace_settings
        state["probations"] = [
            item
            for item in state["probations"]
            if item.get("projection") != projection
        ]
        state["activations"].append(activation)
        _save_state(system, state)
        db.commit()
        report["validation"] = activation
        return report
    except ProjectionGateError as exc:
        db.rollback()
        raise ProjectionRolloutError(str(exc)) from exc
    except Exception:
        db.rollback()
        raise


def deactivate(
    db: DBSession,
    *,
    workspace_id: str,
    projection: str,
    apply: bool,
    actor: str,
) -> dict[str, Any]:
    """Disable exactly the active tail projection, preserving audit history."""

    if projection not in PROJECTION_ORDER:
        raise ProjectionRolloutError(f"unknown projection: {projection}")
    workspace, capability, system = discover_target(
        db,
        workspace_id=workspace_id,
        lock=apply,
    )
    prefix = _activation_prefix(workspace)
    target_index = PROJECTION_ORDER.index(projection)
    state = _state(system)
    _validate_workspace_gate_alignment(
        workspace,
        state,
        capability=capability,
        system=system,
    )
    persisted = _persisted_activation(state, projection)
    probation = _persisted_probation(state, projection)
    enabled = _feature(workspace, projection)
    report: dict[str, Any] = {
        "schema_version": 1,
        "operation": "apply" if apply else "dry_run",
        "direction": "deactivate",
        "projection": projection,
        "feature": FEATURE_BY_PROJECTION[projection],
        "workspace_id": workspace.id,
        "capability_id": capability.id,
        "system_id": system.id,
        "changed": enabled,
    }
    if not enabled:
        if persisted is not None or probation is not None:
            raise ProjectionRolloutError(
                f"{projection} is disabled but still has rollout state"
            )
        report["already_inactive"] = True
        return report
    if persisted is None and probation is None:
        raise ProjectionRolloutError(
            f"{projection} is active without persisted rollout state"
        )
    if target_index != prefix - 1:
        expected = PROJECTION_ORDER[prefix - 1] if prefix else "none"
        raise ProjectionRolloutError(
            f"out-of-order deactivation: next projection must be {expected}"
        )
    if not apply:
        return report
    actor_value = str(actor or "").strip()
    if not actor_value:
        raise ProjectionRolloutError("--apply requires a non-empty actor")

    try:
        workspace.settings = without_projection_activation(
            workspace.settings,
            projection=projection,
        )
    except ProjectionGateError as exc:
        raise ProjectionRolloutError(str(exc)) from exc
    state["activations"] = [
        item
        for item in state["activations"]
        if item.get("projection") != projection
    ]
    state["probations"] = [
        item
        for item in state["probations"]
        if item.get("projection") != projection
    ]
    deactivation = {
        "projection": projection,
        "feature": FEATURE_BY_PROJECTION[projection],
        "deactivated_by": actor_value,
        "deactivated_at": datetime.now(UTC).isoformat(),
        "phase": "verified" if persisted is not None else "probation",
        "activation_evidence_sha256": (
            persisted.get("evidence_sha256") if persisted is not None else None
        ),
        "activation_revision": (
            persisted.get("revision") if persisted is not None else probation.get("revision")
        ),
        "probation_lease_id": probation.get("lease_id") if probation is not None else None,
    }
    state["deactivations"].append(deactivation)
    _save_state(system, state)
    audit_id = emit_audit_event(
        workspace_id=workspace.id,
        event_type=(
            "lot7.projection.deactivated"
            if persisted is not None
            else "lot7.projection.probation_aborted"
        ),
        actor=actor_value,
        agent_id=system.id,
        details={
            "system_id": system.id,
            "capability_id": capability.id,
            "projection": projection,
            "feature": FEATURE_BY_PROJECTION[projection],
            "activation_evidence_sha256": (
                persisted.get("evidence_sha256") if persisted is not None else None
            ),
            "activation_revision": (
                persisted.get("revision")
                if persisted is not None
                else probation.get("revision")
            ),
            "probation_lease_id": (
                probation.get("lease_id") if probation is not None else None
            ),
        },
        db=db,
    )
    if audit_id is None:
        raise ProjectionRolloutError("the deactivation audit event could not be persisted")
    db.commit()
    report["deactivation"] = deactivation
    return report


def status(db: DBSession, *, workspace_id: str) -> dict[str, Any]:
    workspace, capability, system = discover_target(
        db,
        workspace_id=workspace_id,
    )
    prefix = _activation_prefix(workspace)
    state = _state(system)
    _validate_workspace_gate_alignment(
        workspace,
        state,
        capability=capability,
        system=system,
    )
    rows = []
    runtime_revision = str(settings.agentium_image_revision or "").strip().lower()
    runtime_revision_valid = re.fullmatch(r"[0-9a-f]{40}", runtime_revision) is not None
    for projection in PROJECTION_ORDER:
        evidence = _persisted_activation(state, projection)
        probation = _persisted_probation(state, projection)
        enabled = _feature(workspace, projection)
        runner_verified = False
        pilot_observation = _record(
            evidence.get("pilot_observation") if evidence else None
        )
        pilot_observed = _persisted_pilot_is_valid(
            pilot_observation,
            db=db,
            workspace_id=workspace.id,
            expected_subject={
                "workspace_id": workspace.id,
                "system_id": system.id,
                "capability_id": capability.id,
                "projection": projection,
                "revision": evidence.get("revision") if evidence else None,
                "lease_id": (
                    evidence.get("probation_lease_id") if evidence else None
                ),
            },
            expected_runner=_record(evidence.get("trusted_runner") if evidence else None),
        )
        if evidence and evidence.get("trusted_runner") is not None:
            try:
                _trusted_runner_metadata(
                    evidence.get("trusted_runner"),
                    revision=str(evidence.get("revision") or ""),
                )
            except AuthorizationPromotionError:
                runner_verified = False
            else:
                runner_verified = True
        revision_matches_runtime = bool(
            (evidence or probation)
            and runtime_revision_valid
            and (evidence or probation).get("revision") == runtime_revision
        )
        effective = bool(
            runtime_revision_valid
            and authoritative_projection_enabled(
                db,
                workspace,
                projection,
                runtime_revision=runtime_revision,
            )
        )
        rows.append(
            {
                "projection": projection,
                "feature": FEATURE_BY_PROJECTION[projection],
                "enabled": enabled,
                "effective": effective,
                "phase": "verified" if evidence is not None else (
                    "probation" if probation is not None else "inactive"
                ),
                "attested": evidence is not None,
                "evidence_sha256": evidence.get("evidence_sha256") if evidence else None,
                "runner_verified": runner_verified,
                "pilot_observed": pilot_observed,
                "pilot_observation": pilot_observation or None,
                "revision_matches_runtime": revision_matches_runtime,
                "lease_id": probation.get("lease_id") if probation else None,
                "expires_at": probation.get("expires_at") if probation else None,
                "behavior_verified": bool(
                    enabled
                    and runner_verified
                    and revision_matches_runtime
                    and pilot_observed
                    and effective
                ),
            }
        )
    verified_prefix = 0
    for projection in PROJECTION_ORDER:
        if _persisted_activation(state, projection) is None:
            break
        verified_prefix += 1
    active_complete = verified_prefix == len(PROJECTION_ORDER)
    behavior_verified = active_complete and all(
        row["behavior_verified"] for row in rows
    )
    return {
        "schema_version": 1,
        "activation_order": list(PROJECTION_ORDER),
        "workspace_id": workspace.id,
        "capability_id": capability.id,
        "system_id": system.id,
        "active_prefix": list(PROJECTION_ORDER[:verified_prefix]),
        "enabled_prefix": list(PROJECTION_ORDER[:prefix]),
        "active_complete": active_complete,
        # Formal completion is deliberately stronger than feature activation.
        "complete": behavior_verified,
        "behavior_verified": behavior_verified,
        "runtime_revision": runtime_revision if runtime_revision_valid else None,
        "lot6_prerequisites": {
            key: key not in _missing_lot6_prerequisites(workspace)
            for key in LOT6_PREREQUISITE_FLAGS
        },
        "deactivation_count": len(state.get("deactivations", [])),
        "projections": rows,
    }


def _load_evidence(path: str | None) -> Mapping[str, Any] | None:
    if not path:
        return None
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectionRolloutError(f"cannot read validation evidence: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ProjectionRolloutError("validation evidence root must be an object")
    return payload


def _load_pilot_observation(path: str | None) -> Mapping[str, Any] | None:
    if not path:
        return None
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectionRolloutError(f"cannot read pilot observation: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ProjectionRolloutError("pilot observation root must be an object")
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    status_parser = commands.add_parser("status")
    status_parser.add_argument("--workspace-id", required=True)
    stage_parser = commands.add_parser("stage")
    stage_parser.add_argument("projection", choices=PROJECTION_ORDER)
    stage_parser.add_argument("--workspace-id", required=True)
    stage_parser.add_argument("--actor")
    stage_parser.add_argument("--apply", action="store_true")
    for command in ("finalize", "activate"):
        activate_parser = commands.add_parser(command)
        activate_parser.add_argument("projection", choices=PROJECTION_ORDER)
        activate_parser.add_argument("--workspace-id", required=True)
        activate_parser.add_argument("--evidence")
        activate_parser.add_argument("--pilot-observation")
        activate_parser.add_argument("--actor")
        activate_parser.add_argument("--apply", action="store_true")
        activate_parser.add_argument("--oidc-token-env")
        activate_parser.add_argument("--oidc-audience")
    deactivate_parser = commands.add_parser("deactivate")
    deactivate_parser.add_argument("projection", choices=PROJECTION_ORDER)
    deactivate_parser.add_argument("--workspace-id", required=True)
    deactivate_parser.add_argument("--actor")
    deactivate_parser.add_argument("--apply", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    db = SessionLocal()
    try:
        if args.command == "status":
            report = status(db, workspace_id=args.workspace_id)
        elif args.command == "stage":
            report = stage(
                db,
                workspace_id=args.workspace_id,
                projection=args.projection,
                apply=args.apply,
                actor=args.actor or "",
            )
        elif args.command in {"activate", "finalize"}:
            trusted_runner = (
                _trusted_runner_from_ci(
                    token_env=args.oidc_token_env,
                    audience=args.oidc_audience,
                )
                if args.oidc_token_env
                else None
            )
            report = activate(
                db,
                workspace_id=args.workspace_id,
                projection=args.projection,
                evidence=_load_evidence(args.evidence),
                pilot_observation=_load_pilot_observation(args.pilot_observation),
                apply=args.apply,
                actor=args.actor or "",
                trusted_runner=trusted_runner,
            )
        else:
            report = deactivate(
                db,
                workspace_id=args.workspace_id,
                projection=args.projection,
                apply=args.apply,
                actor=args.actor or "",
            )
    except (AuthorizationPromotionError, ProjectionRolloutError) as exc:
        db.rollback()
        print(json.dumps({"error": str(exc)}, sort_keys=True))
        return 2
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
