#!/usr/bin/env python3
"""Two-phase, attested rollout owner for Workspace App runtime authority.

The lifecycle and its backfill never toggle runtime authority.  A protected
preflight proof may stage a short probation for one structurally marked
canary Workspace.  During that lease the authoritative runtime is available
only for the post-activation canary.  ``finalize`` binds that second proof to
the exact Workspace, deployed SHA, canonical installation/configuration set
and probation.  Expiry fails closed; ``abort`` and ``deactivate`` are the only
ways back to the legacy runtime.

Dry-run is the default for every mutating operation.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ElementTree
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.db.base import SessionLocal  # noqa: E402
from app.models.audit import AuditLog  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.services.workspace_app_runtime import (  # noqa: E402
    WORKSPACE_APP_PLATFORM_FEATURE,
    WORKSPACE_APP_POSTACTIVATION_CHECK_COUNT,
    WORKSPACE_APP_PREFLIGHT_CHECK_COUNT,
    WORKSPACE_APP_PROBATION_MAX_AGE,
    WORKSPACE_APP_ROLLOUT_STATE_KEY,
    WorkspaceAppRuntime,
    WorkspaceAppRuntimeError,
    _probation_digest,
    inspect_authoritative_workspace_app_runtime,
    resolve_workspace_app_runtime,
    validate_workspace_app_inactive_rollout_history,
    workspace_app_installation_subject,
    workspace_app_installations_sha256,
)
from scripts.rollout_authorization_v2 import (  # noqa: E402
    AuthorizationPromotionError,
    _trusted_runner_from_ci,
    _trusted_runner_metadata,
)

ROLLOUT_SCHEMA_VERSION = 1
ROLLOUT_STATE_KEY = WORKSPACE_APP_ROLLOUT_STATE_KEY
CANARY_MARKER = "workspace_app_platform_canary"
CANARY_MARKER_VALUE = "v1"
EVIDENCE_SCHEMA_VERSION = 2
PREFLIGHT_EVIDENCE_KIND = "lot9_workspace_app_preflight"
POSTACTIVATION_EVIDENCE_KIND = "lot9_workspace_app_postactivation"
PREFLIGHT_EVIDENCE_SUITE = "lot9-workspace-app-preflight"
POSTACTIVATION_EVIDENCE_SUITE = "lot9-workspace-app-postactivation"
PREFLIGHT_CHECKS = (
    "lifecycle_idempotency",
    "upgrade_rollback_uninstall",
    "legacy_gate_off",
)
POSTACTIVATION_CHECKS = (
    "runtime_bootstrap",
    "entry_gate",
    "action_pack_isolation",
    "workspace_epoch_purge",
)
REQUIRED_CHECKS = PREFLIGHT_CHECKS + POSTACTIVATION_CHECKS
EVIDENCE_MAX_AGE = timedelta(hours=24)
EVIDENCE_FUTURE_TOLERANCE = timedelta(minutes=5)
EVIDENCE_ARTIFACT_MAX_BYTES = 512 * 1024
DEFAULT_PROBATION_SECONDS = 15 * 60
MIN_PROBATION_SECONDS = 60
MAX_PROBATION_SECONDS = int(WORKSPACE_APP_PROBATION_MAX_AGE.total_seconds())
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")


class WorkspaceAppRolloutError(ValueError):
    """A Lot-9 stage, finalize or rollback precondition is not satisfied."""


def _record(value: Any) -> dict[str, Any]:
    return copy.deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_utc(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise WorkspaceAppRolloutError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkspaceAppRolloutError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise WorkspaceAppRolloutError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _runtime_revision() -> str:
    revision = str(settings.agentium_image_revision or "").strip().lower()
    if _REVISION_RE.fullmatch(revision) is None:
        raise WorkspaceAppRolloutError(
            "the deployed runtime must expose its exact 40-character Git SHA"
        )
    return revision


def _workspace(db: DBSession, workspace_id: str, *, lock: bool) -> Workspace:
    scoped_id = str(workspace_id or "").strip()
    if not scoped_id:
        raise WorkspaceAppRolloutError("workspace_id is required")
    query = db.query(Workspace).populate_existing().filter(
        Workspace.id == scoped_id,
        Workspace.is_active.is_(True),
        Workspace.deleted_at.is_(None),
    )
    if lock:
        query = query.with_for_update(of=Workspace)
    workspace = query.one_or_none()
    if workspace is None:
        raise WorkspaceAppRolloutError("the target Workspace is missing or inactive")
    return workspace


def _feature_enabled(workspace: Workspace) -> bool:
    settings_payload = workspace.settings if isinstance(workspace.settings, Mapping) else {}
    features = settings_payload.get("features")
    return (
        isinstance(features, Mapping)
        and features.get(WORKSPACE_APP_PLATFORM_FEATURE) is True
    )


def _set_feature(workspace: Workspace, enabled: bool) -> None:
    workspace_settings = _record(workspace.settings)
    raw_features = workspace_settings.get("features")
    if raw_features is not None and not isinstance(raw_features, Mapping):
        raise WorkspaceAppRolloutError("workspace settings.features must be an object")
    features = _record(raw_features)
    features[WORKSPACE_APP_PLATFORM_FEATURE] = bool(enabled)
    workspace_settings["features"] = features
    workspace.settings = workspace_settings


def _is_canary(workspace: Workspace) -> bool:
    workspace_settings = workspace.settings if isinstance(workspace.settings, Mapping) else {}
    experience = workspace_settings.get("experience")
    return (
        isinstance(experience, Mapping)
        and experience.get(CANARY_MARKER) == CANARY_MARKER_VALUE
    )


def _require_unique_canary(db: DBSession, workspace: Workspace) -> None:
    if not _is_canary(workspace):
        raise WorkspaceAppRolloutError(
            f"target Workspace must declare settings.experience.{CANARY_MARKER}="
            f"{CANARY_MARKER_VALUE!r}"
        )
    marked = [row.id for row in db.query(Workspace).filter(
        Workspace.is_active.is_(True),
        Workspace.deleted_at.is_(None),
    ).all() if _is_canary(row)]
    if marked != [workspace.id]:
        raise WorkspaceAppRolloutError(
            "exactly one active Workspace must carry the Workspace App canary marker"
        )


def _state(workspace: Workspace) -> dict[str, Any]:
    settings_payload = _record(workspace.settings)
    state = _record(settings_payload.get(ROLLOUT_STATE_KEY))
    if not state:
        return {
            "schema_version": ROLLOUT_SCHEMA_VERSION,
            "activations": [],
            "deactivations": [],
            "probation": None,
            "probation_aborts": [],
        }
    if state.get("schema_version") != ROLLOUT_SCHEMA_VERSION:
        raise WorkspaceAppRolloutError("unsupported Workspace App rollout state")
    for field in ("activations", "deactivations", "probation_aborts"):
        rows = state.get(field, [])
        if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
            raise WorkspaceAppRolloutError(f"invalid Workspace App rollout {field}")
        state[field] = [dict(row) for row in rows]
    probation = state.get("probation")
    if probation is not None and not isinstance(probation, Mapping):
        raise WorkspaceAppRolloutError("invalid Workspace App rollout probation")
    state["probation"] = dict(probation) if isinstance(probation, Mapping) else None
    return state


def _save_state(workspace: Workspace, state: Mapping[str, Any]) -> None:
    workspace_settings = _record(workspace.settings)
    workspace_settings[ROLLOUT_STATE_KEY] = copy.deepcopy(dict(state))
    workspace.settings = workspace_settings


def _installation_subject(runtime: WorkspaceAppRuntime) -> list[dict[str, str]]:
    return workspace_app_installation_subject(runtime)


def _exact_keys(value: Mapping[str, Any], expected: set[str], *, field: str) -> None:
    actual = set(value)
    if actual != expected:
        raise WorkspaceAppRolloutError(
            f"{field} fields differ from the contract; "
            f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
        )


def _validated_trusted_runner(
    value: Mapping[str, Any] | None,
    *,
    revision: str,
) -> dict[str, Any]:
    try:
        return _trusted_runner_metadata(value, revision=revision)
    except AuthorizationPromotionError as exc:
        raise WorkspaceAppRolloutError(f"untrusted Workspace App runner: {exc}") from exc


def _current_trusted_runner(*, token_env: str, audience: str | None) -> dict[str, Any]:
    try:
        return _trusted_runner_from_ci(token_env=token_env, audience=audience)
    except AuthorizationPromotionError as exc:
        raise WorkspaceAppRolloutError(str(exc)) from exc


def _require_same_trusted_runner(
    producer: Mapping[str, Any],
    current: Mapping[str, Any] | None,
    *,
    revision: str,
) -> dict[str, Any]:
    current_runner = _validated_trusted_runner(current, revision=revision)
    if current_runner != dict(producer):
        raise WorkspaceAppRolloutError(
            "--apply must run in the same protected GitLab job that produced the evidence"
        )
    return current_runner


def _source_junit(payload: Mapping[str, Any]) -> dict[str, str]:
    raw = payload.get("source_junit")
    source = _record(raw)
    _exact_keys(
        source,
        {"media_type", "sha256", "artifact_ref"},
        field="source_junit",
    )
    digest = str(source.get("sha256") or "").strip().lower()
    artifact_ref = str(source.get("artifact_ref") or "").strip().lower()
    if (
        source.get("media_type") != "application/junit+xml"
        or _SHA256_RE.fullmatch(digest) is None
        or artifact_ref != f"sha256:{digest}"
    ):
        raise WorkspaceAppRolloutError(
            "source_junit must be a content-addressed JUnit artifact"
        )
    return {
        "media_type": "application/junit+xml",
        "sha256": digest,
        "artifact_ref": artifact_ref,
    }


def _validate_junit_artifact(
    artifact: Any,
    *,
    revision: str,
    workspace_id: str,
    installations_sha256: str,
    suite_name: str,
    checks: Sequence[str],
    probation_ref: str | None,
    observation_ref: str,
    source_junit_ref: str,
) -> dict[str, str | int]:
    if not isinstance(artifact, Mapping):
        raise WorkspaceAppRolloutError("runner_artifact must be an object")
    if artifact.get("media_type") != "application/junit+xml":
        raise WorkspaceAppRolloutError("runner artifact media type is invalid")
    digest = str(artifact.get("sha256") or "").strip().lower()
    artifact_ref = str(artifact.get("artifact_ref") or "").strip().lower()
    content = artifact.get("content_base64")
    if _SHA256_RE.fullmatch(digest) is None or artifact_ref != f"sha256:{digest}":
        raise WorkspaceAppRolloutError("runner artifact is not content-addressed")
    if not isinstance(content, str) or not content:
        raise WorkspaceAppRolloutError("runner artifact content is required")
    try:
        raw = base64.b64decode(content, validate=True)
    except (ValueError, TypeError) as exc:
        raise WorkspaceAppRolloutError("runner artifact is not valid base64") from exc
    if not raw or len(raw) > EVIDENCE_ARTIFACT_MAX_BYTES:
        raise WorkspaceAppRolloutError("runner artifact size is invalid")
    if hashlib.sha256(raw).hexdigest() != digest:
        raise WorkspaceAppRolloutError("runner artifact digest mismatch")
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        raise WorkspaceAppRolloutError("runner artifact must be JUnit XML") from exc
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    named = [suite for suite in suites if suite.attrib.get("name") == suite_name]
    if len(named) != 1:
        raise WorkspaceAppRolloutError("runner artifact suite identity is invalid")
    suite = named[0]
    try:
        counters = {
            key: int(suite.attrib.get(key, "0"))
            for key in ("tests", "failures", "errors", "skipped")
        }
    except ValueError as exc:
        raise WorkspaceAppRolloutError("runner artifact counters must be integers") from exc
    testcases = suite.findall("./testcase")
    testcase_names = [str(node.attrib.get("name") or "").strip() for node in testcases]
    if (
        counters["tests"] != len(checks)
        or len(testcases) != len(checks)
        or len(testcase_names) != len(set(testcase_names))
        or set(testcase_names) != set(checks)
        or any(counters[key] for key in ("failures", "errors", "skipped"))
        or any(
            node.find("failure") is not None
            or node.find("error") is not None
            or node.find("skipped") is not None
            for node in testcases
        )
    ):
        raise WorkspaceAppRolloutError("runner artifact does not prove its complete passing suite")
    property_nodes = suite.findall("./properties/property")
    property_names = [str(node.attrib.get("name") or "") for node in property_nodes]
    if "" in property_names or len(property_names) != len(set(property_names)):
        raise WorkspaceAppRolloutError("runner artifact has duplicate properties")
    properties = {
        name: str(node.attrib.get("value") or "")
        for name, node in zip(property_names, property_nodes, strict=True)
    }
    expected = {
        "revision": revision,
        "workspace_id": workspace_id,
        "installations_sha256": installations_sha256,
        "observation_ref": observation_ref,
        "source_junit_ref": source_junit_ref,
    }
    if probation_ref is not None:
        expected["probation_ref"] = probation_ref
    if properties != expected:
        raise WorkspaceAppRolloutError("runner artifact subject differs from rollout subject")
    return {
        "artifact_ref": artifact_ref,
        "sha256": digest,
        "tests": counters["tests"],
    }


def _validate_evidence(
    evidence: Any,
    *,
    workspace: Workspace,
    runtime: WorkspaceAppRuntime,
    kind: str,
    suite_name: str,
    checks: Sequence[str],
    probation_ref: str | None = None,
    probation_window: tuple[datetime, datetime] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not isinstance(evidence, Mapping):
        raise WorkspaceAppRolloutError("evidence must be an object")
    payload = copy.deepcopy(dict(evidence))
    _exact_keys(
        payload,
        {
            "schema_version",
            "kind",
            "activation_grade",
            "generated_at",
            "revision",
            "validated_by",
            "observation_ref",
            "trusted_runner",
            "source_junit",
            "subject",
            "checks",
            "runner_artifact",
        },
        field="evidence",
    )
    if payload.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        raise WorkspaceAppRolloutError("unsupported evidence schema")
    if payload.get("kind") != kind:
        raise WorkspaceAppRolloutError("unexpected evidence kind")
    if payload.get("activation_grade") is not True:
        raise WorkspaceAppRolloutError("evidence is not activation-grade")
    current_revision = _runtime_revision()
    revision = str(payload.get("revision") or "").strip().lower()
    if revision != current_revision:
        raise WorkspaceAppRolloutError("evidence revision differs from deployed runtime")
    producer = _validated_trusted_runner(
        payload.get("trusted_runner"),
        revision=revision,
    )
    source_junit = _source_junit(payload)
    validated_by = str(payload.get("validated_by") or "").strip()
    if not validated_by:
        raise WorkspaceAppRolloutError("evidence validated_by is required")
    observation_ref = str(payload.get("observation_ref") or "").strip().lower()
    if not observation_ref.startswith("sha256:") or _SHA256_RE.fullmatch(
        observation_ref.removeprefix("sha256:")
    ) is None:
        raise WorkspaceAppRolloutError("evidence observation_ref must be content-addressed")
    generated_at = _parse_utc(payload.get("generated_at"), field="generated_at")
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    if generated_at > current_time + EVIDENCE_FUTURE_TOLERANCE:
        raise WorkspaceAppRolloutError("evidence timestamp is in the future")
    if current_time - generated_at > EVIDENCE_MAX_AGE:
        raise WorkspaceAppRolloutError("evidence is stale")
    if probation_window is not None:
        staged_at, expires_at = probation_window
        if generated_at < staged_at or generated_at > expires_at:
            raise WorkspaceAppRolloutError("post-activation evidence is outside its probation")
    subject = payload.get("subject")
    if not isinstance(subject, Mapping) or subject.get("workspace_id") != workspace.id:
        raise WorkspaceAppRolloutError("evidence subject differs from the target Workspace")
    installed = _installation_subject(runtime)
    if not installed:
        raise WorkspaceAppRolloutError("at least one trusted Workspace App must be installed")
    installation_sha = workspace_app_installations_sha256(runtime)
    if subject.get("installations") != installed:
        raise WorkspaceAppRolloutError("evidence installation set differs from the database")
    if subject.get("installations_sha256") != installation_sha:
        raise WorkspaceAppRolloutError("evidence installation digest differs from the database")
    if probation_ref is not None and subject.get("probation_ref") != probation_ref:
        raise WorkspaceAppRolloutError("evidence belongs to a different probation")
    evidence_checks = payload.get("checks")
    if (
        not isinstance(evidence_checks, Mapping)
        or set(evidence_checks) != set(checks)
        or any(evidence_checks.get(key) is not True for key in checks)
    ):
        raise WorkspaceAppRolloutError("evidence does not contain the exact required checks")
    artifact = _validate_junit_artifact(
        payload.get("runner_artifact"),
        revision=revision,
        workspace_id=workspace.id,
        installations_sha256=installation_sha,
        suite_name=suite_name,
        checks=checks,
        probation_ref=probation_ref,
        observation_ref=observation_ref,
        source_junit_ref=source_junit["artifact_ref"],
    )
    evidence_sha = _sha256(payload)
    return {
        "evidence_sha256": evidence_sha,
        "evidence_ref": f"sha256:{evidence_sha}",
        "generated_at": _utc_text(generated_at),
        "revision": revision,
        "installations_sha256": installation_sha,
        "installation_count": len(installed),
        "artifact_ref": artifact["artifact_ref"],
        "artifact_sha256": artifact["sha256"],
        "artifact_tests": artifact["tests"],
        "observation_ref": observation_ref,
        "trusted_runner": producer,
        "source_junit_ref": source_junit["artifact_ref"],
        "validated_by": validated_by,
    }


def _required_actor(actor: str) -> str:
    value = str(actor or "").strip()
    if not value:
        raise WorkspaceAppRolloutError("--apply requires a non-empty actor")
    return value


def _required_reason(reason: str, *, operation: str) -> str:
    value = str(reason or "").strip()
    if not value:
        raise WorkspaceAppRolloutError(f"--apply {operation} requires a reason")
    return value


def _mandatory_audit(
    db: DBSession,
    *,
    workspace: Workspace,
    event_type: str,
    actor: str,
    details: Mapping[str, Any],
) -> None:
    db.add(
        AuditLog(
            id=str(uuid4()),
            workspace_id=workspace.id,
            timestamp=datetime.now(UTC).replace(tzinfo=None),
            event_type=event_type,
            actor=actor,
            severity="info",
            details=copy.deepcopy(dict(details)),
        )
    )
    db.flush()


def _authoritative_runtime(
    workspace: Workspace,
    db: DBSession,
) -> WorkspaceAppRuntime:
    try:
        return inspect_authoritative_workspace_app_runtime(workspace, db=db)
    except WorkspaceAppRuntimeError as exc:
        raise WorkspaceAppRolloutError(
            f"authoritative runtime is invalid: {exc.code}"
        ) from exc


def status(db: DBSession, *, workspace_id: str) -> dict[str, Any]:
    workspace = _workspace(db, workspace_id, lock=False)
    state = _state(workspace)
    runtime: WorkspaceAppRuntime | None = None
    blocker: str | None = None
    phase = "disabled"
    try:
        if _feature_enabled(workspace):
            runtime = resolve_workspace_app_runtime(workspace, db=db)
            phase = runtime.rollout_phase
        else:
            validate_workspace_app_inactive_rollout_history(workspace)
            runtime = inspect_authoritative_workspace_app_runtime(workspace, db=db)
    except WorkspaceAppRuntimeError as exc:
        blocker = exc.code
        phase = "invalid"
        try:
            runtime = inspect_authoritative_workspace_app_runtime(workspace, db=db)
        except WorkspaceAppRuntimeError:
            runtime = None
    installations = _installation_subject(runtime) if runtime is not None else []
    if not installations and blocker is None:
        blocker = "no_installed_apps"
    probation = state.get("probation")
    return {
        "schema_version": ROLLOUT_SCHEMA_VERSION,
        "workspace_id": workspace.id,
        "feature": WORKSPACE_APP_PLATFORM_FEATURE,
        "enabled": _feature_enabled(workspace),
        "canary_marked": _is_canary(workspace),
        "phase": phase,
        "ready": bool(installations) and blocker is None,
        "blocker": blocker,
        "installations": installations,
        "installations_sha256": (
            workspace_app_installations_sha256(runtime) if runtime is not None else _sha256([])
        ),
        "probation_ref": (
            str(probation.get("probation_ref")) if isinstance(probation, Mapping) else None
        ),
        "probation_expires_at": (
            str(probation.get("expires_at")) if isinstance(probation, Mapping) else None
        ),
        "activation_count": len(state["activations"]),
        "deactivation_count": len(state["deactivations"]),
        "probation_abort_count": len(state["probation_aborts"]),
    }


def bootstrap(
    db: DBSession,
    *,
    workspace_id: str,
    apply: bool,
    actor: str,
) -> dict[str, Any]:
    """Mark exactly one inactive, installed Workspace as the structural canary.

    Bootstrap is deliberately separate from staging. It holds every active
    Workspace row in deterministic order while applying, so two concurrent
    operators cannot both observe an empty marker set and create two canaries.
    It never enables runtime authority or changes an installation.
    """

    scoped_id = str(workspace_id or "").strip()
    if not scoped_id:
        raise WorkspaceAppRolloutError("workspace_id is required")
    query = (
        db.query(Workspace)
        .populate_existing()
        .filter(
            Workspace.is_active.is_(True),
            Workspace.deleted_at.is_(None),
        )
        .order_by(Workspace.id.asc())
    )
    if apply:
        query = query.with_for_update(of=Workspace)
    active_workspaces = query.all()
    workspace = next((row for row in active_workspaces if row.id == scoped_id), None)
    if workspace is None:
        raise WorkspaceAppRolloutError("the target Workspace is missing or inactive")
    marked_ids = sorted(row.id for row in active_workspaces if _is_canary(row))
    foreign_markers = [item for item in marked_ids if item != workspace.id]
    if foreign_markers:
        raise WorkspaceAppRolloutError(
            "another active Workspace already carries the Workspace App canary marker"
        )
    if _feature_enabled(workspace):
        raise WorkspaceAppRolloutError(
            "runtime authority must be disabled before canary bootstrap"
        )
    try:
        validate_workspace_app_inactive_rollout_history(workspace)
    except WorkspaceAppRuntimeError as exc:
        raise WorkspaceAppRolloutError(f"rollout history is invalid: {exc.code}") from exc
    runtime = _authoritative_runtime(workspace, db)
    installations = _installation_subject(runtime)
    if not installations:
        raise WorkspaceAppRolloutError(
            "at least one trusted Workspace App must be installed before bootstrap"
        )
    changed = not _is_canary(workspace)
    result = {
        "workspace_id": workspace.id,
        "operation": "bootstrap",
        "apply": apply,
        "changed": changed,
        "marker": f"settings.experience.{CANARY_MARKER}",
        "marker_value": CANARY_MARKER_VALUE,
        "installation_count": len(installations),
        "installations_sha256": workspace_app_installations_sha256(runtime),
        "runtime_authority_enabled": False,
    }
    if not apply or not changed:
        return result
    actor_key = _required_actor(actor)
    workspace_settings = _record(workspace.settings)
    raw_experience = workspace_settings.get("experience")
    if raw_experience is not None and not isinstance(raw_experience, Mapping):
        raise WorkspaceAppRolloutError("workspace settings.experience must be an object")
    experience = _record(raw_experience)
    experience[CANARY_MARKER] = CANARY_MARKER_VALUE
    workspace_settings["experience"] = experience
    workspace.settings = workspace_settings
    try:
        _mandatory_audit(
            db,
            workspace=workspace,
            event_type="lot9.workspace_app_platform.canary_bootstrapped",
            actor=actor_key,
            details={
                "marker": CANARY_MARKER,
                "marker_value": CANARY_MARKER_VALUE,
                "installations_sha256": result["installations_sha256"],
                "installation_count": result["installation_count"],
                "runtime_authority_enabled": False,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


def stage(
    db: DBSession,
    *,
    workspace_id: str,
    evidence: Mapping[str, Any],
    apply: bool,
    actor: str,
    probation_seconds: int = DEFAULT_PROBATION_SECONDS,
    now: datetime | None = None,
    trusted_runner: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not MIN_PROBATION_SECONDS <= probation_seconds <= MAX_PROBATION_SECONDS:
        raise WorkspaceAppRolloutError(
            f"probation must last between {MIN_PROBATION_SECONDS} and "
            f"{MAX_PROBATION_SECONDS} seconds"
        )
    workspace = _workspace(db, workspace_id, lock=apply)
    _require_unique_canary(db, workspace)
    if _feature_enabled(workspace):
        raise WorkspaceAppRolloutError("runtime authority is already enabled; abort first")
    try:
        validate_workspace_app_inactive_rollout_history(workspace)
    except WorkspaceAppRuntimeError as exc:
        raise WorkspaceAppRolloutError(f"rollout history is invalid: {exc.code}") from exc
    state = _state(workspace)
    runtime = _authoritative_runtime(workspace, db)
    validation = _validate_evidence(
        evidence,
        workspace=workspace,
        runtime=runtime,
        kind=PREFLIGHT_EVIDENCE_KIND,
        suite_name=PREFLIGHT_EVIDENCE_SUITE,
        checks=PREFLIGHT_CHECKS,
        now=now,
    )
    if apply:
        _require_same_trusted_runner(
            validation["trusted_runner"],
            trusted_runner,
            revision=validation["revision"],
        )
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    probation: dict[str, Any] = {
        "workspace_id": workspace.id,
        "revision": validation["revision"],
        "installations_sha256": validation["installations_sha256"],
        "installation_count": validation["installation_count"],
        "preflight_evidence_sha256": validation["evidence_sha256"],
        "preflight_evidence_ref": validation["evidence_ref"],
        "preflight_artifact_sha256": validation["artifact_sha256"],
        "preflight_artifact_ref": validation["artifact_ref"],
        "preflight_artifact_tests": WORKSPACE_APP_PREFLIGHT_CHECK_COUNT,
        "preflight_source_junit_ref": validation["source_junit_ref"],
        "trusted_runner": validation["trusted_runner"],
        "staged_at": _utc_text(current_time),
        "expires_at": _utc_text(current_time + timedelta(seconds=probation_seconds)),
        "staged_by": str(actor or "").strip() or None,
    }
    probation_sha = _probation_digest(probation)
    probation["probation_sha256"] = probation_sha
    probation["probation_ref"] = f"sha256:{probation_sha}"
    result = {
        "workspace_id": workspace.id,
        "operation": "stage",
        "apply": apply,
        "changed": True,
        "probation_ref": probation["probation_ref"],
        "probation_expires_at": probation["expires_at"],
        "validation": validation,
    }
    if not apply:
        return result
    actor_key = _required_actor(actor)
    probation["staged_by"] = actor_key
    # staged_by is part of the content address, so finalize the digest after
    # actor validation rather than accepting an anonymous preview digest.
    probation_sha = _probation_digest(probation)
    probation["probation_sha256"] = probation_sha
    probation["probation_ref"] = f"sha256:{probation_sha}"
    result["probation_ref"] = probation["probation_ref"]
    try:
        state["probation"] = probation
        _save_state(workspace, state)
        _set_feature(workspace, True)
        _mandatory_audit(
            db,
            workspace=workspace,
            event_type="lot9.workspace_app_platform.staged",
            actor=actor_key,
            details={
                "revision": validation["revision"],
                "probation_ref": probation["probation_ref"],
                "expires_at": probation["expires_at"],
                "preflight_evidence_ref": validation["evidence_ref"],
                "preflight_artifact_ref": validation["artifact_ref"],
                "preflight_source_junit_ref": validation["source_junit_ref"],
                "pipeline_id": validation["trusted_runner"]["pipeline_id"],
                "job_id": validation["trusted_runner"]["job_id"],
                "installations_sha256": validation["installations_sha256"],
                "installation_count": validation["installation_count"],
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


def finalize(
    db: DBSession,
    *,
    workspace_id: str,
    evidence: Mapping[str, Any],
    apply: bool,
    actor: str,
    now: datetime | None = None,
    trusted_runner: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    workspace = _workspace(db, workspace_id, lock=apply)
    _require_unique_canary(db, workspace)
    if not _feature_enabled(workspace):
        raise WorkspaceAppRolloutError("runtime authority is not in probation")
    try:
        runtime = resolve_workspace_app_runtime(workspace, db=db)
    except WorkspaceAppRuntimeError as exc:
        raise WorkspaceAppRolloutError(f"probation is invalid: {exc.code}") from exc
    if runtime.rollout_phase != "probation" or runtime.rollout_ref is None:
        raise WorkspaceAppRolloutError("runtime authority is not in probation")
    state = _state(workspace)
    probation = state.get("probation")
    if not isinstance(probation, Mapping):
        raise WorkspaceAppRolloutError("probation state is missing")
    staged_at = _parse_utc(probation.get("staged_at"), field="staged_at")
    expires_at = _parse_utc(probation.get("expires_at"), field="expires_at")
    validation = _validate_evidence(
        evidence,
        workspace=workspace,
        runtime=runtime,
        kind=POSTACTIVATION_EVIDENCE_KIND,
        suite_name=POSTACTIVATION_EVIDENCE_SUITE,
        checks=POSTACTIVATION_CHECKS,
        probation_ref=runtime.rollout_ref,
        probation_window=(staged_at, expires_at),
        now=now,
    )
    if apply:
        current_runner = _require_same_trusted_runner(
            validation["trusted_runner"],
            trusted_runner,
            revision=validation["revision"],
        )
        if _validated_trusted_runner(
            probation.get("trusted_runner"),
            revision=validation["revision"],
        ) != current_runner:
            raise WorkspaceAppRolloutError(
                "finalize must run in the same protected GitLab job as preflight staging"
            )
    result = {
        "workspace_id": workspace.id,
        "operation": "finalize",
        "apply": apply,
        "changed": True,
        "probation_ref": runtime.rollout_ref,
        "validation": validation,
    }
    if not apply:
        return result
    actor_key = _required_actor(actor)
    activation = {
        "workspace_id": workspace.id,
        "revision": validation["revision"],
        "installations_sha256": validation["installations_sha256"],
        "installation_count": validation["installation_count"],
        "preflight_evidence_sha256": probation["preflight_evidence_sha256"],
        "preflight_evidence_ref": probation["preflight_evidence_ref"],
        "preflight_artifact_sha256": probation["preflight_artifact_sha256"],
        "preflight_artifact_ref": probation["preflight_artifact_ref"],
        "preflight_artifact_tests": WORKSPACE_APP_PREFLIGHT_CHECK_COUNT,
        "preflight_source_junit_ref": probation["preflight_source_junit_ref"],
        "evidence_sha256": validation["evidence_sha256"],
        "evidence_ref": validation["evidence_ref"],
        "artifact_sha256": validation["artifact_sha256"],
        "artifact_ref": validation["artifact_ref"],
        "postactivation_artifact_tests": WORKSPACE_APP_POSTACTIVATION_CHECK_COUNT,
        "artifact_tests": len(REQUIRED_CHECKS),
        "source_junit_ref": validation["source_junit_ref"],
        "trusted_runner": validation["trusted_runner"],
        "probation_ref": runtime.rollout_ref,
        "activated_at": _utc_text((now or datetime.now(UTC)).astimezone(UTC)),
        "actor": actor_key,
    }
    try:
        state["probation"] = None
        state["activations"].append(activation)
        _save_state(workspace, state)
        _set_feature(workspace, True)
        _mandatory_audit(
            db,
            workspace=workspace,
            event_type="lot9.workspace_app_platform.activated",
            actor=actor_key,
            details={
                "revision": validation["revision"],
                "probation_ref": runtime.rollout_ref,
                "preflight_evidence_ref": probation["preflight_evidence_ref"],
                "evidence_ref": validation["evidence_ref"],
                "artifact_ref": validation["artifact_ref"],
                "source_junit_ref": validation["source_junit_ref"],
                "pipeline_id": validation["trusted_runner"]["pipeline_id"],
                "job_id": validation["trusted_runner"]["job_id"],
                "installations_sha256": validation["installations_sha256"],
                "installation_count": validation["installation_count"],
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


def abort(
    db: DBSession,
    *,
    workspace_id: str,
    apply: bool,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    workspace = _workspace(db, workspace_id, lock=apply)
    state = _state(workspace)
    probation = state.get("probation")
    changed = _feature_enabled(workspace) or isinstance(probation, Mapping)
    result = {
        "workspace_id": workspace.id,
        "operation": "abort",
        "apply": apply,
        "changed": changed,
        "probation_ref": (
            str(probation.get("probation_ref")) if isinstance(probation, Mapping) else None
        ),
    }
    if not apply or not changed:
        return result
    actor_key = _required_actor(actor)
    reason_key = _required_reason(reason, operation="abort")
    event = {
        "workspace_id": workspace.id,
        "aborted_at": _utc_text(datetime.now(UTC)),
        "actor": actor_key,
        "reason": reason_key,
        "probation_ref": result["probation_ref"],
    }
    try:
        _set_feature(workspace, False)
        state["probation"] = None
        state["probation_aborts"].append(event)
        _save_state(workspace, state)
        _mandatory_audit(
            db,
            workspace=workspace,
            event_type="lot9.workspace_app_platform.probation_aborted",
            actor=actor_key,
            details={
                "reason": reason_key,
                "probation_ref": result["probation_ref"],
                "additive_state_preserved": True,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


def deactivate(
    db: DBSession,
    *,
    workspace_id: str,
    apply: bool,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    workspace = _workspace(db, workspace_id, lock=apply)
    state = _state(workspace)
    if isinstance(state.get("probation"), Mapping):
        return abort(
            db,
            workspace_id=workspace_id,
            apply=apply,
            actor=actor,
            reason=reason,
        )
    changed = _feature_enabled(workspace)
    result = {
        "workspace_id": workspace.id,
        "operation": "deactivate",
        "apply": apply,
        "changed": changed,
    }
    if not apply or not changed:
        return result
    actor_key = _required_actor(actor)
    reason_key = _required_reason(reason, operation="deactivate")
    latest = state["activations"][-1] if state["activations"] else {}
    previous_ref = latest.get("evidence_ref") if isinstance(latest, Mapping) else None
    event = {
        "workspace_id": workspace.id,
        "deactivated_at": _utc_text(datetime.now(UTC)),
        "actor": actor_key,
        "reason": reason_key,
        "previous_activation_ref": previous_ref,
    }
    try:
        _set_feature(workspace, False)
        state["deactivations"].append(event)
        _save_state(workspace, state)
        _mandatory_audit(
            db,
            workspace=workspace,
            event_type="lot9.workspace_app_platform.deactivated",
            actor=actor_key,
            details={
                "reason": reason_key,
                "previous_activation_ref": previous_ref,
                "additive_state_preserved": True,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


def activate(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    """Reject the unsafe one-step API retained only as an explicit boundary."""

    raise WorkspaceAppRolloutError(
        "direct activation is disabled; use preflight, stage, post-canary and finalize"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=("status", "bootstrap", "stage", "finalize", "abort", "deactivate"),
    )
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--probation-seconds", type=int, default=DEFAULT_PROBATION_SECONDS)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--actor", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument(
        "--oidc-token-env",
        default="AGENTIUM_ATTESTATION_ID_TOKEN",
    )
    parser.add_argument("--oidc-audience")
    return parser


def main() -> int:
    args = _parser().parse_args()
    with SessionLocal() as db:
        try:
            if args.operation == "status":
                result = status(db, workspace_id=args.workspace_id)
            elif args.operation == "bootstrap":
                result = bootstrap(
                    db,
                    workspace_id=args.workspace_id,
                    apply=args.apply,
                    actor=args.actor,
                )
            elif args.operation in {"stage", "finalize"}:
                if args.evidence is None:
                    raise WorkspaceAppRolloutError(
                        f"{args.operation} requires --evidence"
                    )
                evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
                trusted_runner = (
                    _current_trusted_runner(
                        token_env=args.oidc_token_env,
                        audience=args.oidc_audience,
                    )
                    if args.apply
                    else None
                )
                if args.operation == "stage":
                    result = stage(
                        db,
                        workspace_id=args.workspace_id,
                        evidence=evidence,
                        apply=args.apply,
                        actor=args.actor,
                        probation_seconds=args.probation_seconds,
                        trusted_runner=trusted_runner,
                    )
                else:
                    result = finalize(
                        db,
                        workspace_id=args.workspace_id,
                        evidence=evidence,
                        apply=args.apply,
                        actor=args.actor,
                        trusted_runner=trusted_runner,
                    )
            elif args.operation == "abort":
                result = abort(
                    db,
                    workspace_id=args.workspace_id,
                    apply=args.apply,
                    actor=args.actor,
                    reason=args.reason,
                )
            else:
                result = deactivate(
                    db,
                    workspace_id=args.workspace_id,
                    apply=args.apply,
                    actor=args.actor,
                    reason=args.reason,
                )
        except (
            WorkspaceAppRolloutError,
            WorkspaceAppRuntimeError,
            json.JSONDecodeError,
            OSError,
        ) as exc:
            db.rollback()
            print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
            return 2
    print(json.dumps({"ok": True, **result}, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
