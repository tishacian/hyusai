#!/usr/bin/env python3
"""Evidence-gated authorization-v2 promotion from shadow to enforce.

The command deliberately accepts only an immutable workspace id and explicit
``resource.action`` keys.  It cannot create policy, infer a target from a
workspace slug, or jump an action from compat to enforce.  A promotion is
dry-run by default and a write requires an actor plus a SHA-bound JSON proof.

Example::

    python -m scripts.rollout_authorization_v2 status \
        --workspace-id 00000000-0000-0000-0000-000000000000
    python -m scripts.rollout_authorization_v2 promote \
        --workspace-id 00000000-0000-0000-0000-000000000000 \
        --action system.read --action run.read \
        --revision 0123456789abcdef0123456789abcdef01234567 \
        --evidence /path/to/authorization-proof.json \
        --actor operator@example.net --apply

Only reduced, non-sensitive attestation metadata is stored.  The original
proof stays an external CI/deployment artefact and is addressed by SHA-256.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session as DBSession

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TRUST_SCRIPTS = ROOT.parent / "scripts"
if str(TRUST_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(TRUST_SCRIPTS))

from agentium_trusted_compliance import (  # noqa: E402
    TrustedComplianceError,
    bound_ci_identity,
    verify_gitlab_oidc,
)

from app.core.config import settings  # noqa: E402
from app.db.base import SessionLocal  # noqa: E402
from app.models.workspace import Workspace, WorkspaceIAMConfig  # noqa: E402
from app.services.audit_logger import emit_audit_event  # noqa: E402
from app.services.iam.decision_plane import (  # noqa: E402
    build_authorization_v2_backfill,
    candidate_config_sha256,
    enforcement_attestation_errors,
    resolve_mode,
)
from app.services.iam.evidence_contracts import junit_count_errors  # noqa: E402
from app.services.iam.shadow_review import (  # noqa: E402
    ShadowReviewError,
    apply_review_to_summaries,
    assert_source_manifest_matches_audit,
    expected_blockers,
    load_persisted_review,
    validate_review_envelope,
    validate_source_manifest,
)

SCHEMA_VERSION = 1
POLICY_VERSION = 2
ATTESTATIONS_KEY = "enforcement_attestations"
HISTORY_KEY = "enforcement_history"
SHA_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
ACTION_RE = re.compile(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_.]*")
EVIDENCE_MAX_AGE = timedelta(hours=24)
EVIDENCE_FUTURE_TOLERANCE = timedelta(minutes=5)


class AuthorizationPromotionError(ValueError):
    """Raised before an ambiguous, unattested, or non-atomic promotion."""


def _record(value: Any) -> dict[str, Any]:
    return copy.deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _actions(values: Iterable[str]) -> tuple[str, ...]:
    raw = [str(value or "").strip() for value in values]
    if not raw or any(not value for value in raw):
        raise AuthorizationPromotionError("at least one explicit --action is required")
    if len(raw) != len(set(raw)):
        raise AuthorizationPromotionError("duplicate actions are not allowed")
    invalid = sorted(value for value in raw if ACTION_RE.fullmatch(value) is None)
    if invalid:
        raise AuthorizationPromotionError(
            "actions must be explicit resource.action keys: " + ", ".join(invalid)
        )
    return tuple(sorted(raw))


def _revision(value: str) -> str:
    revision = str(value or "").strip().lower()
    if SHA_RE.fullmatch(revision) is None:
        raise AuthorizationPromotionError("revision must be the exact 40-character Git SHA")
    return revision


def _trusted_runner_metadata(
    value: Mapping[str, Any] | None,
    *,
    revision: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AuthorizationPromotionError(
            "--apply promotion requires a protected GitLab OIDC runner"
        )
    runner = dict(value)
    required = ("issuer", "project_id", "pipeline_id", "job_id", "commit_sha", "ref")
    missing = [field for field in required if not str(runner.get(field) or "").strip()]
    if missing:
        raise AuthorizationPromotionError(
            "trusted runner metadata is incomplete: " + ", ".join(missing)
        )
    issuer = str(runner["issuer"]).rstrip("/")
    if not issuer.startswith("https://"):
        raise AuthorizationPromotionError("trusted runner issuer must use HTTPS")
    if str(runner["commit_sha"]).lower() != revision:
        raise AuthorizationPromotionError("trusted runner commit must match the promoted revision")
    protected = runner.get("ref_protected")
    if protected is not True and str(protected).lower() != "true":
        raise AuthorizationPromotionError("trusted runner ref must be protected")
    trusted_issuer = str(settings.authorization_v2_trusted_oidc_issuer or "").rstrip("/")
    if not trusted_issuer.startswith("https://") or issuer != trusted_issuer:
        raise AuthorizationPromotionError(
            "trusted runner issuer does not match the configured trust anchor"
        )
    trusted_project_id = str(settings.authorization_v2_trusted_project_id or "").strip()
    if not trusted_project_id or str(runner["project_id"]) != trusted_project_id:
        raise AuthorizationPromotionError(
            "trusted runner project does not match the configured trust anchor"
        )
    trusted_ref = str(settings.authorization_v2_trusted_ref or "").strip()
    if not trusted_ref or str(runner["ref"]) != trusted_ref:
        raise AuthorizationPromotionError(
            "trusted runner ref does not match the configured trust anchor"
        )
    return {
        "issuer": issuer,
        "project_id": str(runner["project_id"]),
        "pipeline_id": str(runner["pipeline_id"]),
        "job_id": str(runner["job_id"]),
        "commit_sha": revision,
        "ref": str(runner["ref"]),
        "ref_protected": True,
    }


def _trusted_runner_from_ci(*, token_env: str, audience: str | None) -> dict[str, Any]:
    server_url = os.environ.get("CI_SERVER_URL", "").rstrip("/")
    token = os.environ.get(token_env, "")
    if not token:
        raise AuthorizationPromotionError(f"signed GitLab ID token is missing from {token_env}")
    try:
        claims = verify_gitlab_oidc(
            token,
            server_url=server_url,
            audience=audience or server_url,
        )
        return _trusted_runner_metadata(
            bound_ci_identity(claims, os.environ),
            revision=os.environ.get("CI_COMMIT_SHA", ""),
        )
    except TrustedComplianceError as exc:
        raise AuthorizationPromotionError(f"untrusted GitLab runner: {exc}") from exc


def _governed_actions() -> frozenset[str]:
    return frozenset(build_authorization_v2_backfill()["modes"])


def _require_governed_actions(actions: Iterable[str]) -> tuple[str, ...]:
    selected = _actions(actions)
    unknown = sorted(set(selected) - _governed_actions())
    if unknown:
        raise AuthorizationPromotionError(
            "actions are not governed by the authorization-v2 rollout contract: "
            + ", ".join(unknown)
        )
    return selected


def _timestamp(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise AuthorizationPromotionError(f"evidence requires {field}")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuthorizationPromotionError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise AuthorizationPromotionError(f"{field} must include a timezone")
    return parsed


def _counter(value: Any, *, field: str, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AuthorizationPromotionError(f"{field} must be an integer")
    minimum = 1 if positive else 0
    if value < minimum:
        qualifier = "positive" if positive else "non-negative"
        raise AuthorizationPromotionError(f"{field} must be {qualifier}")
    return value


def _workspace_and_config(
    db: DBSession,
    *,
    workspace_id: str,
    lock: bool,
) -> tuple[Workspace, WorkspaceIAMConfig]:
    target = str(workspace_id or "").strip()
    if not target:
        raise AuthorizationPromotionError("workspace_id is required")
    workspace_query = db.query(Workspace).filter(
        Workspace.id == target,
        Workspace.is_active.is_(True),
        Workspace.deleted_at.is_(None),
    )
    if lock:
        workspace_query = workspace_query.with_for_update(of=Workspace)
    workspace = workspace_query.one_or_none()
    if workspace is None:
        raise AuthorizationPromotionError(f"unknown active workspace id: {target}")

    config_query = db.query(WorkspaceIAMConfig).filter(WorkspaceIAMConfig.workspace_id == target)
    if lock:
        config_query = config_query.with_for_update(of=WorkspaceIAMConfig)
    config = config_query.one_or_none()
    if config is None:
        raise AuthorizationPromotionError(
            "workspace has no authorization-v2 configuration; configure shadow first"
        )
    return workspace, config


def _documents(
    config: WorkspaceIAMConfig,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    raw_overrides = config.capability_overrides
    if raw_overrides is not None and not isinstance(raw_overrides, Mapping):
        raise AuthorizationPromotionError("capability_overrides must be an object")
    overrides = _record(raw_overrides)
    raw_policy = overrides.get("authorization_v2")
    if not isinstance(raw_policy, Mapping):
        raise AuthorizationPromotionError(
            "workspace has no authorization-v2 policy; configure shadow first"
        )
    policy = _record(raw_policy)
    if policy.get("policy_version") != POLICY_VERSION:
        raise AuthorizationPromotionError("authorization_v2.policy_version must be 2")
    raw_modes = policy.get("modes")
    if not isinstance(raw_modes, Mapping):
        raise AuthorizationPromotionError("authorization_v2.modes must be an object")
    modes = _record(raw_modes)
    raw_attestations = policy.get(ATTESTATIONS_KEY, {})
    if not isinstance(raw_attestations, Mapping):
        raise AuthorizationPromotionError(f"authorization_v2.{ATTESTATIONS_KEY} must be an object")
    attestations = _record(raw_attestations)
    return overrides, policy, modes, attestations


def validate_evidence(
    evidence: Mapping[str, Any],
    *,
    workspace_id: str,
    actions: Iterable[str],
    revision: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate a proof and reduce it to persistence-safe metadata."""

    requested_actions = _require_governed_actions(actions)
    requested_revision = _revision(revision)
    payload = _record(evidence)
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise AuthorizationPromotionError("evidence schema_version must be 1")
    if payload.get("result") != "passed":
        raise AuthorizationPromotionError("evidence result must be passed")

    expected_subject = {
        "workspace_id": workspace_id,
        "actions": list(requested_actions),
        "revision": requested_revision,
    }
    if payload.get("subject") != expected_subject:
        raise AuthorizationPromotionError(
            "evidence subject must exactly match workspace_id, sorted actions, and revision"
        )

    validated_by = str(payload.get("validated_by") or "").strip()
    environment = str(payload.get("environment") or "").strip()
    if not validated_by:
        raise AuthorizationPromotionError("evidence requires validated_by")
    if not environment:
        raise AuthorizationPromotionError("evidence requires environment")
    validated_at = _timestamp(payload.get("validated_at"), field="validated_at")
    checked_at = now or datetime.now(UTC)
    if checked_at.tzinfo is None:
        raise AuthorizationPromotionError("evidence validation clock must include a timezone")
    if validated_at > checked_at + EVIDENCE_FUTURE_TOLERANCE:
        raise AuthorizationPromotionError("evidence validated_at is in the future")
    if checked_at - validated_at > EVIDENCE_MAX_AGE:
        raise AuthorizationPromotionError("evidence is older than 24 hours")

    contracts = payload.get("contracts")
    if not isinstance(contracts, Mapping):
        raise AuthorizationPromotionError("evidence contracts must be an object")
    contract_summaries: dict[str, dict[str, Any]] = {}
    for contract_name in ("legacy", "candidate"):
        contract = contracts.get(contract_name)
        if not isinstance(contract, Mapping) or contract.get("result") != "passed":
            raise AuthorizationPromotionError(
                f"evidence {contract_name} contract must have result=passed"
            )
        if contract.get("format") != "junit":
            raise AuthorizationPromotionError(
                f"evidence {contract_name} contract must be derived from JUnit"
            )
        artifact_ref = str(contract.get("artifact_ref") or "")
        if not artifact_ref.startswith("sha256:") or SHA256_RE.fullmatch(artifact_ref[7:]) is None:
            raise AuthorizationPromotionError(
                f"evidence {contract_name} contract must be content-addressed"
            )
        test_count = _counter(
            contract.get("test_count"),
            field=f"contracts.{contract_name}.test_count",
            positive=True,
        )
        failure_count = _counter(
            contract.get("failure_count"),
            field=f"contracts.{contract_name}.failure_count",
        )
        error_count = _counter(
            contract.get("error_count"),
            field=f"contracts.{contract_name}.error_count",
        )
        skipped_count = _counter(
            contract.get("skipped_count"),
            field=f"contracts.{contract_name}.skipped_count",
        )
        count_errors = junit_count_errors(contract)
        if count_errors:
            raise AuthorizationPromotionError(
                f"evidence {contract_name} " + "; ".join(count_errors)
            )
        producer = _trusted_runner_metadata(
            contract.get("producer"),
            revision=requested_revision,
        )
        contract_summaries[contract_name] = {
            "result": "passed",
            "format": "junit",
            "artifact_ref": artifact_ref,
            "test_count": test_count,
            "failure_count": failure_count,
            "error_count": error_count,
            "skipped_count": skipped_count,
            "producer": producer,
        }

    observation = payload.get("shadow_observation")
    if not isinstance(observation, Mapping):
        raise AuthorizationPromotionError("evidence shadow_observation must be an object")
    source_name = str(observation.get("source") or "").strip()
    source_ref = str(observation.get("source_ref") or "").strip()
    if not source_name or not source_ref:
        raise AuthorizationPromotionError(
            "shadow_observation requires a source and immutable source_ref"
        )
    if not source_ref.startswith("sha256:") or SHA256_RE.fullmatch(source_ref[7:]) is None:
        raise AuthorizationPromotionError(
            "shadow_observation.source_ref must be sha256:<64 lowercase hex>"
        )
    started_at = _timestamp(
        observation.get("window_started_at"), field="shadow_observation.window_started_at"
    )
    ended_at = _timestamp(
        observation.get("window_ended_at"), field="shadow_observation.window_ended_at"
    )
    if ended_at < started_at:
        raise AuthorizationPromotionError("shadow observation window is inverted")
    if validated_at < ended_at:
        raise AuthorizationPromotionError(
            "validated_at cannot precede the shadow observation window"
        )
    if ended_at > checked_at + EVIDENCE_FUTURE_TOLERANCE:
        raise AuthorizationPromotionError("shadow observation window ends in the future")
    if checked_at - ended_at > EVIDENCE_MAX_AGE:
        raise AuthorizationPromotionError("shadow observation window ended more than 24 hours ago")
    candidate_digest = str(observation.get("candidate_config_sha256") or "")
    if SHA256_RE.fullmatch(candidate_digest) is None:
        raise AuthorizationPromotionError(
            "shadow_observation.candidate_config_sha256 must be a SHA-256"
        )
    candidate_version = _counter(
        observation.get("candidate_config_version"),
        field="shadow_observation.candidate_config_version",
        positive=True,
    )
    if observation.get("runtime_revision") != requested_revision:
        raise AuthorizationPromotionError("shadow observation revision differs from subject")
    try:
        validated_source = validate_source_manifest(
            observation.get("source_manifest"),
            source_ref=source_ref,
            workspace_id=workspace_id,
            actions=requested_actions,
            revision=requested_revision,
            candidate_config_sha256=candidate_digest,
            candidate_config_version=candidate_version,
            window_started_at=started_at,
            window_ended_at=ended_at,
        )
        review_payload = observation.get("mismatch_review")
        validated_review = (
            validate_review_envelope(
                review_payload,
                source=validated_source,
                validated_at=validated_at,
            )
            if review_payload is not None
            else None
        )
        summaries = apply_review_to_summaries(validated_source, validated_review)
        blockers = expected_blockers(summaries)
    except ShadowReviewError as exc:
        raise AuthorizationPromotionError(str(exc)) from exc

    observed = observation.get("actions")
    if not isinstance(observed, Mapping) or dict(observed) != summaries:
        raise AuthorizationPromotionError(
            "shadow observation action summaries differ from the source rows and review"
        )
    if payload.get("blockers") != blockers:
        raise AuthorizationPromotionError(
            "evidence blockers differ from the source rows and mismatch review"
        )
    if blockers:
        raise AuthorizationPromotionError("shadow evidence remains blocked")

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return {
        "schema_version": SCHEMA_VERSION,
        "workspace_id": workspace_id,
        "actions": list(requested_actions),
        "revision": requested_revision,
        "evidence_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "validated_by": validated_by,
        "validated_at": validated_at.isoformat(),
        "environment": environment,
        "contracts": contract_summaries,
        "candidate_config_sha256": candidate_digest,
        "candidate_config_version": candidate_version,
        "shadow_observation": {
            "source": source_name,
            "source_ref": source_ref,
            "window_started_at": started_at.isoformat(),
            "window_ended_at": ended_at.isoformat(),
            "runtime_revision": requested_revision,
            "candidate_config_sha256": candidate_digest,
            "candidate_config_version": candidate_version,
            "actions": summaries,
            **(
                {"mismatch_review": validated_review.envelope}
                if validated_review is not None
                else {}
            ),
        },
    }


def _require_persisted_mismatch_review(
    db: DBSession,
    *,
    workspace_id: str,
    metadata: Mapping[str, Any],
) -> None:
    observation = metadata.get("shadow_observation")
    review = observation.get("mismatch_review") if isinstance(observation, Mapping) else None
    if review is None:
        return
    if not isinstance(review, Mapping):
        raise AuthorizationPromotionError("mismatch review metadata is invalid")
    try:
        persisted = load_persisted_review(
            db,
            workspace_id=workspace_id,
            audit_id=str(review.get("audit_id") or ""),
        )
    except ShadowReviewError as exc:
        raise AuthorizationPromotionError(str(exc)) from exc
    if persisted != dict(review):
        raise AuthorizationPromotionError(
            "mismatch review differs from the authoritative audit ledger"
        )


def _require_authoritative_shadow_source(
    db: DBSession,
    *,
    workspace_id: str,
    evidence: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> None:
    """Rebuild every source row from AuditLog before any promotion preview.

    A SHA-256 makes a caller-provided manifest tamper-evident, but not
    authoritative: a caller can otherwise omit a mismatch and hash the
    resulting subset.  The bounded AuditLog query is therefore mandatory even
    when the evidence reports zero mismatches and carries no review.
    """

    raw_observation = evidence.get("shadow_observation")
    reduced_observation = metadata.get("shadow_observation")
    if not isinstance(raw_observation, Mapping) or not isinstance(reduced_observation, Mapping):
        raise AuthorizationPromotionError("shadow observation metadata is invalid")
    try:
        source = validate_source_manifest(
            raw_observation.get("source_manifest"),
            source_ref=str(reduced_observation.get("source_ref") or ""),
            workspace_id=workspace_id,
            actions=metadata.get("actions") if isinstance(metadata.get("actions"), list) else (),
            revision=str(metadata.get("revision") or ""),
            candidate_config_sha256=str(reduced_observation.get("candidate_config_sha256") or ""),
            candidate_config_version=int(reduced_observation.get("candidate_config_version") or 0),
            window_started_at=_timestamp(
                reduced_observation.get("window_started_at"),
                field="shadow_observation.window_started_at",
            ),
            window_ended_at=_timestamp(
                reduced_observation.get("window_ended_at"),
                field="shadow_observation.window_ended_at",
            ),
        )
        assert_source_manifest_matches_audit(db, source)
    except (ShadowReviewError, TypeError, ValueError) as exc:
        raise AuthorizationPromotionError(str(exc)) from exc


def _status_from_documents(
    *,
    config: WorkspaceIAMConfig,
    workspace_id: str,
    policy: Mapping[str, Any],
    modes: Mapping[str, Any],
    attestations: Mapping[str, Any],
    actions: Iterable[str] | None,
) -> dict[str, Any]:
    selected = (
        _actions(actions) if actions is not None else tuple(sorted(set(modes) | set(attestations)))
    )
    rows: list[dict[str, Any]] = []
    for action in selected:
        configured_mode = modes.get(action, policy.get("default_mode", "compat"))
        resource_kind, candidate_action = action.split(".", 1)
        effective_mode = resolve_mode(
            config,
            resource_kind=resource_kind,
            action=candidate_action,
        ).value
        raw_attestation = attestations.get(action)
        drift: list[str] = []
        if configured_mode not in {"compat", "shadow", "enforce"}:
            drift.append("invalid authorization mode")
        if configured_mode == "enforce":
            drift.extend(
                enforcement_attestation_errors(
                    config=config,
                    action=action,
                    require_runtime_revision=True,
                )
            )
        elif raw_attestation is not None:
            drift.append("attestation exists while action is not enforce")
        rows.append(
            {
                "action": action,
                "configured_mode": modes.get(action),
                "effective_mode": effective_mode,
                "attested": isinstance(raw_attestation, Mapping),
                "evidence_sha256": (
                    raw_attestation.get("evidence_sha256")
                    if isinstance(raw_attestation, Mapping)
                    else None
                ),
                "drift": sorted(set(drift)),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "operation": "status",
        "workspace_id": workspace_id,
        "policy_version": policy.get("policy_version"),
        "default_mode": policy.get("default_mode", "compat"),
        "healthy": all(not row["drift"] for row in rows),
        "enforce_count": sum(row["effective_mode"] == "enforce" for row in rows),
        "actions": rows,
    }


def status(
    db: DBSession,
    *,
    workspace_id: str,
    actions: Iterable[str] | None = None,
) -> dict[str, Any]:
    workspace, config = _workspace_and_config(db, workspace_id=workspace_id, lock=False)
    _, policy, modes, attestations = _documents(config)
    return _status_from_documents(
        config=config,
        workspace_id=workspace.id,
        policy=policy,
        modes=modes,
        attestations=attestations,
        actions=actions,
    )


def promote(
    db: DBSession,
    *,
    workspace_id: str,
    actions: Iterable[str],
    revision: str,
    evidence: Mapping[str, Any] | None,
    apply: bool,
    actor: str,
    trusted_runner: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Promote one exact action set, atomically, after its shadow proof."""

    selected = _require_governed_actions(actions)
    requested_revision = _revision(revision)
    actor_value = str(actor or "").strip()
    if apply and not actor_value:
        raise AuthorizationPromotionError("--apply requires a non-empty actor")
    runner_metadata = (
        _trusted_runner_metadata(trusted_runner, revision=requested_revision) if apply else None
    )

    workspace, config = _workspace_and_config(db, workspace_id=workspace_id, lock=apply)
    overrides, policy, modes, attestations = _documents(config)
    full_status = _status_from_documents(
        config=config,
        workspace_id=workspace.id,
        policy=policy,
        modes=modes,
        attestations=attestations,
        actions=None,
    )
    if not full_status["healthy"]:
        drifted = [row["action"] for row in full_status["actions"] if row["drift"]]
        raise AuthorizationPromotionError(
            "authorization enforce state is unattested or drifted: " + ", ".join(drifted)
        )

    current_modes = [modes.get(action, policy.get("default_mode", "compat")) for action in selected]
    compat = [
        action
        for action, mode in zip(selected, current_modes, strict=True)
        if mode == "compat" or action not in modes
    ]
    if compat:
        raise AuthorizationPromotionError(
            "cannot promote directly from compat; configure explicit shadow first: "
            + ", ".join(compat)
        )
    invalid = [
        action
        for action, mode in zip(selected, current_modes, strict=True)
        if mode not in {"shadow", "enforce"}
    ]
    if invalid:
        raise AuthorizationPromotionError(
            "actions have an invalid current mode: " + ", ".join(invalid)
        )
    if len(set(current_modes)) != 1:
        raise AuthorizationPromotionError(
            "requested actions must be promoted in one atomic shadow group"
        )

    metadata = None
    if evidence is not None:
        metadata = validate_evidence(
            evidence,
            workspace_id=workspace.id,
            actions=selected,
            revision=requested_revision,
        )
        if metadata["candidate_config_sha256"] != candidate_config_sha256(config):
            raise AuthorizationPromotionError(
                "shadow evidence candidate config differs from current workspace policy"
            )
        if current_modes[0] == "shadow" and metadata["candidate_config_version"] != int(
            config.version or 0
        ):
            raise AuthorizationPromotionError(
                "shadow evidence candidate config version differs from current workspace policy"
            )
        _require_authoritative_shadow_source(
            db,
            workspace_id=workspace.id,
            evidence=evidence,
            metadata=metadata,
        )
        _require_persisted_mismatch_review(
            db,
            workspace_id=workspace.id,
            metadata=metadata,
        )
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "operation": "apply" if apply else "dry_run",
        "workspace_id": workspace.id,
        "actions": list(selected),
        "revision": requested_revision,
        "changed": current_modes[0] == "shadow",
        "validation_required": metadata is None,
        "trusted_runner_required": runner_metadata is None,
    }

    if current_modes[0] == "enforce":
        existing = attestations[selected[0]]
        if any(attestations[action] != existing for action in selected):
            raise AuthorizationPromotionError("requested enforce attestations diverge")
        if existing.get("actions") != list(selected):
            raise AuthorizationPromotionError(
                "idempotent retry must use the original attested action set"
            )
        if existing.get("revision") != requested_revision:
            raise AuthorizationPromotionError(
                "idempotent retry revision differs from persisted attestation"
            )
        if metadata is not None and existing.get("evidence_sha256") != metadata["evidence_sha256"]:
            raise AuthorizationPromotionError(
                "idempotent retry evidence differs from persisted attestation"
            )
        report.update(
            {
                "changed": False,
                "already_enforced": True,
                "validation_required": False,
                "trusted_runner_required": False,
                "attestation": existing,
            }
        )
        return report

    if metadata is not None:
        report["attestation"] = metadata
        report["validation_required"] = False
    if not apply:
        return report
    if metadata is None:
        raise AuthorizationPromotionError("--apply requires matching validation evidence")

    promoted = {
        **metadata,
        "trusted_runner": runner_metadata,
        "promoted_by": actor_value,
        "promoted_at": datetime.now(UTC).isoformat(),
    }
    try:
        for action in selected:
            modes[action] = "enforce"
            attestations[action] = copy.deepcopy(promoted)
        policy["modes"] = modes
        policy[ATTESTATIONS_KEY] = attestations
        overrides["authorization_v2"] = policy
        config.capability_overrides = overrides
        config.version = int(config.version or 0) + 1

        audit_id = emit_audit_event(
            db=db,
            workspace_id=workspace.id,
            event_type="lot7.authorization.enforce_promoted",
            actor=actor_value,
            details={
                "policy_version": POLICY_VERSION,
                "actions": list(selected),
                "revision": requested_revision,
                "evidence_sha256": metadata["evidence_sha256"],
                "shadow_evaluation_count": sum(
                    row["evaluations"] for row in metadata["shadow_observation"]["actions"].values()
                ),
            },
        )
        if audit_id is None:
            raise AuthorizationPromotionError(
                "authorization promotion audit could not be persisted"
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    report["attestation"] = promoted
    return report


def demote(
    db: DBSession,
    *,
    workspace_id: str,
    actions: Iterable[str],
    revision: str,
    apply: bool,
    actor: str,
    reason: str,
    repair_drift: bool = False,
) -> dict[str, Any]:
    """Atomically return enforcement to shadow, including emergency repair."""

    selected = _require_governed_actions(actions)
    requested_revision = _revision(revision)
    actor_value = str(actor or "").strip()
    reason_value = str(reason or "").strip()
    if apply and not actor_value:
        raise AuthorizationPromotionError("--apply requires a non-empty actor")
    if apply and not reason_value:
        raise AuthorizationPromotionError("--apply requires a non-empty reason")

    workspace, config = _workspace_and_config(db, workspace_id=workspace_id, lock=apply)
    overrides, policy, modes, attestations = _documents(config)
    current_modes = [modes.get(action, policy.get("default_mode", "compat")) for action in selected]
    already_shadow = all(
        mode == "shadow" and action not in attestations
        for action, mode in zip(selected, current_modes, strict=True)
    )
    if already_shadow:
        return {
            "schema_version": SCHEMA_VERSION,
            "operation": "apply" if apply else "dry_run",
            "workspace_id": workspace.id,
            "actions": list(selected),
            "revision": requested_revision,
            "changed": False,
            "already_shadow": True,
        }
    if any(mode not in {"shadow", "enforce"} for mode in current_modes):
        raise AuthorizationPromotionError(
            "demotion requires requested actions to be shadow or enforce"
        )

    first = attestations.get(selected[0])
    coherent_group = bool(
        isinstance(first, Mapping)
        and all(attestations.get(action) == first for action in selected)
        and first.get("actions") == list(selected)
        and all(mode == "enforce" for mode in current_modes)
    )
    if not coherent_group and not repair_drift:
        raise AuthorizationPromotionError(
            "demotion must include the complete attested action group; "
            "use --repair-drift for an explicit restrictive repair"
        )
    previous = dict(first) if isinstance(first, Mapping) else {}

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "operation": "apply" if apply else "dry_run",
        "workspace_id": workspace.id,
        "actions": list(selected),
        "revision": requested_revision,
        "changed": True,
        "previous_evidence_sha256": previous.get("evidence_sha256"),
        "repair_drift": bool(repair_drift),
    }
    if not apply:
        return report

    raw_history = policy.get(HISTORY_KEY, [])
    if not isinstance(raw_history, list):
        raise AuthorizationPromotionError(f"authorization_v2.{HISTORY_KEY} must be an array")
    history = copy.deepcopy(raw_history)
    demoted_at = datetime.now(UTC).isoformat()
    history.append(
        {
            "operation": "repair_to_shadow" if repair_drift else "demote_to_shadow",
            "actions": list(selected),
            "revision": requested_revision,
            "previous_revision": previous.get("revision"),
            "evidence_sha256": previous.get("evidence_sha256"),
            "demoted_by": actor_value,
            "demoted_at": demoted_at,
            "reason": reason_value,
        }
    )
    try:
        for action in selected:
            modes[action] = "shadow"
            attestations.pop(action, None)
        policy["modes"] = modes
        policy[ATTESTATIONS_KEY] = attestations
        policy[HISTORY_KEY] = history
        overrides["authorization_v2"] = policy
        config.capability_overrides = overrides
        config.version = int(config.version or 0) + 1

        audit_id = emit_audit_event(
            db=db,
            workspace_id=workspace.id,
            event_type="lot7.authorization.enforce_demoted",
            actor=actor_value,
            severity="warning",
            details={
                "policy_version": POLICY_VERSION,
                "actions": list(selected),
                "revision": requested_revision,
                "previous_revision": previous.get("revision"),
                "evidence_sha256": previous.get("evidence_sha256"),
                "reason": reason_value,
                "repair_drift": bool(repair_drift),
            },
        )
        if audit_id is None:
            raise AuthorizationPromotionError("authorization demotion audit could not be persisted")
        db.commit()
    except Exception:
        db.rollback()
        raise
    report["demoted_at"] = demoted_at
    return report


def _load_evidence(path: str | None) -> Mapping[str, Any] | None:
    if not path:
        return None
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthorizationPromotionError(f"cannot read validation evidence: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise AuthorizationPromotionError("validation evidence root must be an object")
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    status_parser = commands.add_parser("status")
    status_parser.add_argument("--workspace-id", required=True)
    status_parser.add_argument("--action", action="append")

    promote_parser = commands.add_parser("promote")
    promote_parser.add_argument("--workspace-id", required=True)
    promote_parser.add_argument("--action", action="append", required=True)
    promote_parser.add_argument("--revision", required=True)
    promote_parser.add_argument("--evidence")
    promote_parser.add_argument("--actor")
    promote_parser.add_argument(
        "--oidc-token-env",
        default="AGENTIUM_ATTESTATION_ID_TOKEN",
    )
    promote_parser.add_argument("--oidc-audience")
    promote_parser.add_argument("--apply", action="store_true")

    demote_parser = commands.add_parser("demote")
    demote_parser.add_argument("--workspace-id", required=True)
    demote_parser.add_argument("--action", action="append", required=True)
    demote_parser.add_argument("--revision", required=True)
    demote_parser.add_argument("--actor")
    demote_parser.add_argument("--reason")
    demote_parser.add_argument("--repair-drift", action="store_true")
    demote_parser.add_argument("--apply", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    db = SessionLocal()
    exit_code = 0
    try:
        if args.command == "status":
            report = status(
                db,
                workspace_id=args.workspace_id,
                actions=args.action,
            )
            if not report["healthy"]:
                exit_code = 3
        elif args.command == "promote":
            trusted_runner = (
                _trusted_runner_from_ci(
                    token_env=args.oidc_token_env,
                    audience=args.oidc_audience,
                )
                if args.apply
                else None
            )
            report = promote(
                db,
                workspace_id=args.workspace_id,
                actions=args.action,
                revision=args.revision,
                evidence=_load_evidence(args.evidence),
                apply=args.apply,
                actor=args.actor or "",
                trusted_runner=trusted_runner,
            )
        else:
            report = demote(
                db,
                workspace_id=args.workspace_id,
                actions=args.action,
                revision=args.revision,
                apply=args.apply,
                actor=args.actor or "",
                reason=args.reason or "",
                repair_drift=args.repair_drift,
            )
    except AuthorizationPromotionError as exc:
        db.rollback()
        report = {"schema_version": SCHEMA_VERSION, "error": str(exc)}
        exit_code = 2
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    print(json.dumps(report, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
