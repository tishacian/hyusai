#!/usr/bin/env python3
"""Collect immutable authorization-v2 shadow observations from the audit log.

The collector never changes authorization policy.  It aggregates only the
canonical ``iam.shadow.evaluation`` events for one immutable workspace id,
exact action keys and a bounded UTC window. Any malformed row or missing action
makes the report blocked. Candidate/legacy mismatches remain blocked until an
authenticated policy administrator records a review through
``POST /api/v1/iam/authorization-v2/mismatch-reviews``; rerun this collector
with ``--mismatch-review-id`` to attach that immutable approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from sqlalchemy.orm import Session as DBSession

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.base import SessionLocal  # noqa: E402
from app.models.audit import AuditLog  # noqa: E402
from app.models.workspace import Workspace, WorkspaceIAMConfig  # noqa: E402
from app.services.iam.decision_plane import (  # noqa: E402
    build_authorization_v2_backfill,
    candidate_config_sha256,
)
from app.services.iam.evidence_contracts import junit_count_errors  # noqa: E402
from app.services.iam.shadow_review import (  # noqa: E402
    SHADOW_COUNTERS,
    SHADOW_EVENT_TYPE,
    ShadowReviewError,
    apply_review_to_summaries,
    build_source_manifest_row,
    expected_blockers,
    load_persisted_review,
    validate_review_envelope,
    validate_source_manifest,
)
from scripts.rollout_authorization_v2 import (  # noqa: E402
    AuthorizationPromotionError,
    _trusted_runner_from_ci,
    _trusted_runner_metadata,
)

SCHEMA_VERSION = 1
EVENT_TYPE = SHADOW_EVENT_TYPE
ACTION_RE = re.compile(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_.]*")
SHA_RE = re.compile(r"[0-9a-f]{40}")
COUNTERS = SHADOW_COUNTERS


class ShadowCollectionError(ValueError):
    """Raised when an observation window cannot produce trustworthy evidence."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _timestamp(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise ShadowCollectionError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ShadowCollectionError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _actions(values: Iterable[str]) -> tuple[str, ...]:
    selected = tuple(sorted(str(value or "").strip() for value in values))
    if not selected or any(ACTION_RE.fullmatch(value) is None for value in selected):
        raise ShadowCollectionError("explicit resource.action keys are required")
    if len(selected) != len(set(selected)):
        raise ShadowCollectionError("duplicate actions are not allowed")
    governed = set(build_authorization_v2_backfill()["modes"])
    unknown = sorted(set(selected) - governed)
    if unknown:
        raise ShadowCollectionError(
            "actions are outside the authorization-v2 contract: " + ", ".join(unknown)
        )
    return selected


def _counter(value: Any, *, field: str, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ShadowCollectionError(f"{field} must be an integer")
    if value < (1 if positive else 0):
        raise ShadowCollectionError(f"{field} is below its minimum")
    return value


def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


def _junit_contract(
    path: Path,
    *,
    name: str,
    revision: str,
    producer: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ShadowCollectionError(f"cannot read {name} JUnit artifact: {exc}") from exc
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise ShadowCollectionError(f"{name} JUnit artifact is invalid XML") from exc

    def _tag(element: ElementTree.Element) -> str:
        return element.tag.rsplit("}", 1)[-1]

    cases = [element for element in root.iter() if _tag(element) == "testcase"]
    failures = sum(1 for case in cases if any(_tag(child) == "failure" for child in list(case)))
    errors = sum(1 for case in cases if any(_tag(child) == "error" for child in list(case)))
    skipped = sum(1 for case in cases if any(_tag(child) == "skipped" for child in list(case)))
    if not cases:
        raise ShadowCollectionError(f"{name} JUnit artifact has no test cases")
    if failures or errors:
        raise ShadowCollectionError(
            f"{name} JUnit artifact is not green: {failures} failures, {errors} errors"
        )
    if len(cases) - skipped <= 0:
        raise ShadowCollectionError(f"{name} JUnit artifact has no executed test cases")
    properties = {
        str(element.attrib.get("name") or ""): str(element.attrib.get("value") or "")
        for element in root.iter()
        if _tag(element) == "property" and element.attrib.get("name")
    }
    expected_properties = {
        "agentium.git_revision": revision,
        "agentium.ci_issuer": str(producer["issuer"]),
        "agentium.ci_project_id": str(producer["project_id"]),
        "agentium.ci_pipeline_id": str(producer["pipeline_id"]),
        "agentium.ci_job_id": str(producer["job_id"]),
        "agentium.ci_ref": str(producer["ref"]),
        "agentium.ci_ref_protected": "true",
    }
    for key, expected in expected_properties.items():
        if properties.get(key) != expected:
            raise ShadowCollectionError(
                f"{name} JUnit artifact does not bind trusted producer property {key}"
            )
    summary = {
        "result": "passed",
        "format": "junit",
        "artifact_ref": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "test_count": len(cases),
        "failure_count": failures,
        "error_count": errors,
        "skipped_count": skipped,
        "producer": dict(producer),
    }
    errors = junit_count_errors(summary)
    if errors:
        raise ShadowCollectionError(f"{name} JUnit counters are invalid: {'; '.join(errors)}")
    return summary


def collect(
    db: DBSession,
    *,
    workspace_id: str,
    actions: Iterable[str],
    revision: str,
    window_started_at: datetime,
    window_ended_at: datetime,
    validated_at: datetime,
    validated_by: str,
    environment: str,
    legacy_junit: Path,
    candidate_junit: Path,
    trusted_runner: Mapping[str, Any],
    mismatch_review_id: str | None = None,
) -> dict[str, Any]:
    selected = _actions(actions)
    revision_value = str(revision or "").strip().lower()
    if SHA_RE.fullmatch(revision_value) is None:
        raise ShadowCollectionError("revision must be an exact 40-character Git SHA")
    try:
        producer = _trusted_runner_metadata(trusted_runner, revision=revision_value)
    except AuthorizationPromotionError as exc:
        raise ShadowCollectionError(f"untrusted JUnit producer: {exc}") from exc
    workspace_value = str(workspace_id or "").strip()
    workspace = (
        db.query(Workspace)
        .filter(
            Workspace.id == workspace_value,
            Workspace.is_active.is_(True),
            Workspace.deleted_at.is_(None),
        )
        .one_or_none()
    )
    if workspace is None:
        raise ShadowCollectionError("workspace_id does not identify an active workspace")
    config = (
        db.query(WorkspaceIAMConfig)
        .filter(WorkspaceIAMConfig.workspace_id == workspace.id)
        .one_or_none()
    )
    if config is None:
        raise ShadowCollectionError("workspace has no authorization-v2 configuration")
    config_digest = candidate_config_sha256(config)
    config_version = int(config.version or 0)
    if config_version <= 0:
        raise ShadowCollectionError("workspace IAM config version must be positive")
    if any(value.tzinfo is None for value in (window_started_at, window_ended_at, validated_at)):
        raise ShadowCollectionError("observation timestamps must include a timezone")
    start = window_started_at.astimezone(UTC)
    end = window_ended_at.astimezone(UTC)
    validation_time = validated_at.astimezone(UTC)
    if end < start:
        raise ShadowCollectionError("shadow observation window is inverted")
    if validation_time < end:
        raise ShadowCollectionError("validated_at precedes the observation window")
    validator = str(validated_by or "").strip()
    environment_value = str(environment or "").strip()
    if not validator or not environment_value:
        raise ShadowCollectionError("validated_by and environment are required")
    contracts = {
        "legacy": _junit_contract(
            legacy_junit,
            name="legacy",
            revision=revision_value,
            producer=producer,
        ),
        "candidate": _junit_contract(
            candidate_junit,
            name="candidate",
            revision=revision_value,
            producer=producer,
        ),
    }

    rows = (
        db.query(AuditLog)
        .filter(
            AuditLog.workspace_id == workspace.id,
            AuditLog.event_type == EVENT_TYPE,
            AuditLog.timestamp >= _naive_utc(start),
            AuditLog.timestamp <= _naive_utc(end),
        )
        .order_by(AuditLog.timestamp.asc(), AuditLog.id.asc())
        .all()
    )
    summaries = {
        action: {
            "evaluations": 0,
            **{counter: 0 for counter in COUNTERS},
            "explained_mismatches": 0,
            "unexplained_mismatches": 0,
        }
        for action in selected
    }
    manifest_rows: list[dict[str, Any]] = []
    for row in rows:
        details = row.details
        if not isinstance(details, Mapping):
            raise ShadowCollectionError(f"audit row {row.id} has no details object")
        action = details.get("action")
        if action not in summaries:
            continue
        if details.get("policy_version") != 2:
            raise ShadowCollectionError(f"audit row {row.id} is not policy_version 2")
        if details.get("origin") != "server":
            raise ShadowCollectionError(f"audit row {row.id} is not server-originated")
        if details.get("configured_mode") != "shadow":
            raise ShadowCollectionError(f"audit row {row.id} was not evaluated in shadow mode")
        if details.get("runtime_revision") != revision_value:
            raise ShadowCollectionError(f"audit row {row.id} revision differs from target")
        if details.get("candidate_config_sha256") != config_digest:
            raise ShadowCollectionError(f"audit row {row.id} candidate config differs from target")
        if details.get("candidate_config_version") != config_version:
            raise ShadowCollectionError(
                f"audit row {row.id} candidate config version differs from target"
            )
        evaluations = _counter(
            details.get("evaluation_count"),
            field=f"audit[{row.id}].evaluation_count",
            positive=True,
        )
        counters = {
            name: _counter(
                details.get(name),
                field=f"audit[{row.id}].{name}",
            )
            for name in COUNTERS
        }
        if counters["legacy_allowed"] + counters["legacy_denied"] != evaluations:
            raise ShadowCollectionError(f"audit row {row.id} legacy counters do not balance")
        if counters["candidate_allowed"] + counters["candidate_denied"] != evaluations:
            raise ShadowCollectionError(f"audit row {row.id} candidate counters do not balance")
        if counters["matches"] + counters["mismatches"] != evaluations:
            raise ShadowCollectionError(f"audit row {row.id} comparison counters do not balance")
        summary = summaries[action]
        summary["evaluations"] += evaluations
        for name, value in counters.items():
            summary[name] += value
        # Mismatches are never self-explained by the collector.  A protected
        # promotion therefore remains blocked until the candidate agrees.
        summary["unexplained_mismatches"] += counters["mismatches"]
        row_timestamp = row.timestamp
        row_timestamp = (
            row_timestamp.replace(tzinfo=UTC)
            if row_timestamp.tzinfo is None
            else row_timestamp.astimezone(UTC)
        )
        manifest_rows.append(
            build_source_manifest_row(
                row_id=row.id,
                timestamp=row_timestamp,
                action=action,
                evaluation_count=evaluations,
                runtime_revision=revision_value,
                candidate_config_sha256=config_digest,
                candidate_config_version=config_version,
                counters=counters,
            )
        )

    source_manifest = {
        "schema_version": SCHEMA_VERSION,
        "workspace_id": workspace.id,
        "actions": list(selected),
        "window_started_at": start.isoformat(),
        "window_ended_at": end.isoformat(),
        "event_type": EVENT_TYPE,
        "runtime_revision": revision_value,
        "candidate_config_sha256": config_digest,
        "candidate_config_version": config_version,
        "rows": manifest_rows,
    }
    source_digest = hashlib.sha256(_canonical_json(source_manifest).encode("utf-8")).hexdigest()
    source_ref = f"sha256:{source_digest}"
    try:
        source = validate_source_manifest(
            source_manifest,
            source_ref=source_ref,
            workspace_id=workspace.id,
            actions=selected,
            revision=revision_value,
            candidate_config_sha256=config_digest,
            candidate_config_version=config_version,
            window_started_at=start,
            window_ended_at=end,
        )
        review = None
        if mismatch_review_id is not None:
            persisted = load_persisted_review(
                db,
                workspace_id=workspace.id,
                audit_id=str(mismatch_review_id).strip(),
            )
            review = validate_review_envelope(
                persisted,
                source=source,
                validated_at=validation_time,
            )
        summaries = apply_review_to_summaries(source, review)
        blockers = expected_blockers(summaries)
    except ShadowReviewError as exc:
        raise ShadowCollectionError(str(exc)) from exc
    return {
        "schema_version": SCHEMA_VERSION,
        "result": "passed" if not blockers else "blocked",
        "subject": {
            "workspace_id": workspace.id,
            "actions": list(selected),
            "revision": revision_value,
        },
        "validated_by": validator,
        "validated_at": validation_time.isoformat(),
        "environment": environment_value,
        "contracts": contracts,
        "shadow_observation": {
            "source": f"audit_logs:{EVENT_TYPE}",
            "source_ref": source_ref,
            "window_started_at": start.isoformat(),
            "window_ended_at": end.isoformat(),
            "runtime_revision": revision_value,
            "candidate_config_sha256": config_digest,
            "candidate_config_version": config_version,
            "actions": summaries,
            "source_manifest": source_manifest,
            **({"mismatch_review": review.envelope} if review is not None else {}),
        },
        "blockers": blockers,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--action", action="append", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--window-started-at", required=True)
    parser.add_argument("--window-ended-at", required=True)
    parser.add_argument("--validated-at")
    parser.add_argument("--validated-by", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--legacy-junit", type=Path, required=True)
    parser.add_argument("--candidate-junit", type=Path, required=True)
    parser.add_argument(
        "--mismatch-review-id",
        help=(
            "Audit id returned by POST /api/v1/iam/authorization-v2/mismatch-reviews; "
            "use only for an intentional, explicitly reviewed shadow difference"
        ),
    )
    parser.add_argument(
        "--oidc-token-env",
        default="AGENTIUM_GITLAB_ID_TOKEN",
    )
    parser.add_argument("--oidc-audience")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    db = SessionLocal()
    try:
        trusted_runner = _trusted_runner_from_ci(
            token_env=args.oidc_token_env,
            audience=args.oidc_audience,
        )
        report = collect(
            db,
            workspace_id=args.workspace_id,
            actions=args.action,
            revision=args.revision,
            window_started_at=_timestamp(
                args.window_started_at,
                field="window_started_at",
            ),
            window_ended_at=_timestamp(args.window_ended_at, field="window_ended_at"),
            validated_at=(
                _timestamp(args.validated_at, field="validated_at")
                if args.validated_at
                else datetime.now(UTC)
            ),
            validated_by=args.validated_by,
            environment=args.environment,
            legacy_junit=args.legacy_junit,
            candidate_junit=args.candidate_junit,
            trusted_runner=trusted_runner,
            mismatch_review_id=args.mismatch_review_id,
        )
    except (AuthorizationPromotionError, ShadowCollectionError) as exc:
        report = {"schema_version": SCHEMA_VERSION, "result": "error", "error": str(exc)}
        exit_code = 2
    else:
        exit_code = 0 if report["result"] == "passed" else 3
    finally:
        db.close()
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
