"""Authoritative review contract for authorization-v2 shadow mismatches.

Raw shadow reports are observations, not approval artefacts.  An intentional
policy difference can become promotion evidence only after an authenticated
workspace policy administrator records a review in the server-owned audit
ledger.  The review is content-addressed and binds the exact source manifest,
observation ids, actions, reasons and reviewer identity.

This module is deliberately independent from the rollout scripts so the HTTP
review boundary, collector and promoter all validate the same representation.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.models.audit import AuditLog

SHADOW_EVENT_TYPE = "iam.shadow.evaluation"
MISMATCH_REVIEW_EVENT_TYPE = "iam.shadow.mismatch_reviewed"
MISMATCH_REVIEW_KIND = "authorization_v2_shadow_mismatch_review"
SCHEMA_VERSION = 1

SHADOW_COUNTERS = (
    "legacy_allowed",
    "legacy_denied",
    "candidate_allowed",
    "candidate_denied",
    "matches",
    "mismatches",
)

_ACTION_RE = re.compile(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_.]*")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_REASON_CODE_RE = re.compile(r"[a-z][a-z0-9_]{2,63}")
_SOURCE_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "workspace_id",
        "actions",
        "window_started_at",
        "window_ended_at",
        "event_type",
        "runtime_revision",
        "candidate_config_sha256",
        "candidate_config_version",
        "rows",
    }
)
_SOURCE_ROW_KEYS = frozenset(
    {
        "id",
        "timestamp",
        "action",
        "evaluation_count",
        "runtime_revision",
        "candidate_config_sha256",
        "candidate_config_version",
        *SHADOW_COUNTERS,
        "sha256",
    }
)
_REVIEW_DOCUMENT_KEYS = frozenset(
    {"schema_version", "kind", "subject", "reviewed_by", "reviewed_at", "entries"}
)
_REVIEW_SUBJECT_KEYS = frozenset(
    {
        "workspace_id",
        "actions",
        "revision",
        "source_ref",
        "candidate_config_sha256",
        "candidate_config_version",
    }
)
_REVIEWER_KEYS = frozenset({"user_id", "identity"})
_REVIEW_ENTRY_KEYS = frozenset({"action", "observation_ids", "reason_code", "reason"})


class ShadowReviewError(ValueError):
    """Raised when shadow evidence or its approval is not authoritative."""


@dataclass(frozen=True)
class ValidatedSourceManifest:
    document: dict[str, Any]
    source_ref: str
    rows_by_id: dict[str, dict[str, Any]]
    summaries: dict[str, dict[str, int]]
    window_started_at: datetime
    window_ended_at: datetime


@dataclass(frozen=True)
class ValidatedMismatchReview:
    envelope: dict[str, Any]
    explained_by_action: dict[str, int]
    reviewed_observation_ids: tuple[str, ...]


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sha256_ref(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _timestamp(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ShadowReviewError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ShadowReviewError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ShadowReviewError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _counter(value: Any, *, field: str, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ShadowReviewError(f"{field} must be an integer")
    if value < (1 if positive else 0):
        raise ShadowReviewError(f"{field} is below its minimum")
    return value


def _exact_keys(value: Mapping[str, Any], expected: frozenset[str], *, field: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        raise ShadowReviewError(
            f"{field} fields differ from the contract"
            + (f"; missing={missing}" if missing else "")
            + (f"; extra={extra}" if extra else "")
        )


def build_source_manifest_row(
    *,
    row_id: str,
    timestamp: datetime,
    action: str,
    evaluation_count: int,
    runtime_revision: str,
    candidate_config_sha256: str,
    candidate_config_version: int,
    counters: Mapping[str, int],
) -> dict[str, Any]:
    """Build the complete non-sensitive row that the promoter can revalidate."""

    document = {
        "id": str(row_id),
        "timestamp": timestamp.astimezone(UTC).isoformat(),
        "action": action,
        "evaluation_count": evaluation_count,
        "runtime_revision": runtime_revision,
        "candidate_config_sha256": candidate_config_sha256,
        "candidate_config_version": candidate_config_version,
        **{name: counters[name] for name in SHADOW_COUNTERS},
    }
    return {
        **document,
        "sha256": hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest(),
    }


def validate_source_manifest(
    manifest: Any,
    *,
    source_ref: str,
    workspace_id: str,
    actions: Sequence[str],
    revision: str,
    candidate_config_sha256: str,
    candidate_config_version: int,
    window_started_at: datetime,
    window_ended_at: datetime,
) -> ValidatedSourceManifest:
    """Recompute every source row and aggregate instead of trusting summaries."""

    if not isinstance(manifest, Mapping):
        raise ShadowReviewError("shadow source manifest must be an object")
    document = dict(manifest)
    _exact_keys(document, _SOURCE_MANIFEST_KEYS, field="shadow source manifest")
    selected = tuple(sorted(actions))
    expected = {
        "schema_version": SCHEMA_VERSION,
        "workspace_id": workspace_id,
        "actions": list(selected),
        "window_started_at": window_started_at.astimezone(UTC).isoformat(),
        "window_ended_at": window_ended_at.astimezone(UTC).isoformat(),
        "event_type": SHADOW_EVENT_TYPE,
        "runtime_revision": revision,
        "candidate_config_sha256": candidate_config_sha256,
        "candidate_config_version": candidate_config_version,
    }
    for field, expected_value in expected.items():
        if document.get(field) != expected_value:
            raise ShadowReviewError(f"shadow source manifest does not bind {field}")
    if source_ref != sha256_ref(document):
        raise ShadowReviewError("shadow_observation.source_ref does not match source_manifest")

    raw_rows = document.get("rows")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ShadowReviewError("shadow source manifest rows are missing")
    summaries = {
        action: {
            "evaluations": 0,
            **{name: 0 for name in SHADOW_COUNTERS},
            "explained_mismatches": 0,
            "unexplained_mismatches": 0,
        }
        for action in selected
    }
    rows_by_id: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(raw_rows):
        if not isinstance(raw, Mapping):
            raise ShadowReviewError(f"shadow source row {index} must be an object")
        row = dict(raw)
        _exact_keys(row, _SOURCE_ROW_KEYS, field=f"shadow source row {index}")
        row_id = str(row.get("id") or "").strip()
        if not row_id or row_id in rows_by_id:
            raise ShadowReviewError("shadow source manifest row ids must be non-empty and unique")
        action = row.get("action")
        if action not in summaries:
            raise ShadowReviewError("shadow source manifest contains an unexpected action")
        if row.get("runtime_revision") != revision:
            raise ShadowReviewError(f"shadow source row {row_id} revision drift")
        if row.get("candidate_config_sha256") != candidate_config_sha256:
            raise ShadowReviewError(f"shadow source row {row_id} candidate config drift")
        if row.get("candidate_config_version") != candidate_config_version:
            raise ShadowReviewError(f"shadow source row {row_id} candidate version drift")
        observed_at = _timestamp(
            row.get("timestamp"), field=f"shadow source row {row_id}.timestamp"
        )
        if observed_at < window_started_at.astimezone(
            UTC
        ) or observed_at > window_ended_at.astimezone(UTC):
            raise ShadowReviewError(f"shadow source row {row_id} is outside the observation window")
        evaluations = _counter(
            row.get("evaluation_count"),
            field=f"shadow source row {row_id}.evaluation_count",
            positive=True,
        )
        counters = {
            name: _counter(row.get(name), field=f"shadow source row {row_id}.{name}")
            for name in SHADOW_COUNTERS
        }
        if counters["legacy_allowed"] + counters["legacy_denied"] != evaluations:
            raise ShadowReviewError(f"shadow source row {row_id} legacy counters do not balance")
        if counters["candidate_allowed"] + counters["candidate_denied"] != evaluations:
            raise ShadowReviewError(f"shadow source row {row_id} candidate counters do not balance")
        if counters["matches"] + counters["mismatches"] != evaluations:
            raise ShadowReviewError(
                f"shadow source row {row_id} comparison counters do not balance"
            )
        digest = str(row.get("sha256") or "")
        unsigned = {key: value for key, value in row.items() if key != "sha256"}
        expected_digest = hashlib.sha256(canonical_json(unsigned).encode("utf-8")).hexdigest()
        if _SHA256_RE.fullmatch(digest) is None or digest != expected_digest:
            raise ShadowReviewError(
                f"shadow source row {row_id} digest does not match its counters"
            )
        summary = summaries[str(action)]
        summary["evaluations"] += evaluations
        for name, value in counters.items():
            summary[name] += value
        rows_by_id[row_id] = row

    for summary in summaries.values():
        summary["unexplained_mismatches"] = summary["mismatches"]
    return ValidatedSourceManifest(
        document=document,
        source_ref=source_ref,
        rows_by_id=rows_by_id,
        summaries=summaries,
        window_started_at=window_started_at.astimezone(UTC),
        window_ended_at=window_ended_at.astimezone(UTC),
    )


def _normalized_entries(entries: Any) -> list[dict[str, Any]]:
    if not isinstance(entries, list) or not entries:
        raise ShadowReviewError("mismatch review entries must be a non-empty array")
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(entries):
        if not isinstance(raw, Mapping):
            raise ShadowReviewError(f"mismatch review entry {index} must be an object")
        entry = dict(raw)
        _exact_keys(entry, _REVIEW_ENTRY_KEYS, field=f"mismatch review entry {index}")
        action = str(entry.get("action") or "").strip()
        if _ACTION_RE.fullmatch(action) is None:
            raise ShadowReviewError(f"mismatch review entry {index} action is invalid")
        raw_ids = entry.get("observation_ids")
        if not isinstance(raw_ids, list) or not raw_ids:
            raise ShadowReviewError(
                f"mismatch review entry {index} observation_ids must be non-empty"
            )
        observation_ids = sorted(str(value or "").strip() for value in raw_ids)
        if any(not value for value in observation_ids) or len(observation_ids) != len(
            set(observation_ids)
        ):
            raise ShadowReviewError(f"mismatch review entry {index} observation_ids must be unique")
        reason_code = str(entry.get("reason_code") or "").strip().lower()
        reason = " ".join(str(entry.get("reason") or "").split())
        if _REASON_CODE_RE.fullmatch(reason_code) is None:
            raise ShadowReviewError(f"mismatch review entry {index} reason_code is invalid")
        if len(reason) < 12 or len(reason) > 1000:
            raise ShadowReviewError(
                f"mismatch review entry {index} reason must contain 12 to 1000 characters"
            )
        normalized.append(
            {
                "action": action,
                "observation_ids": observation_ids,
                "reason_code": reason_code,
                "reason": reason,
            }
        )
    return sorted(
        normalized,
        key=lambda row: (row["action"], row["observation_ids"], row["reason_code"]),
    )


def build_review_document(
    *,
    source: ValidatedSourceManifest,
    reviewer_user_id: str,
    reviewer_identity: str,
    reviewed_at: datetime,
    entries: Any,
) -> dict[str, Any]:
    identity = " ".join(str(reviewer_identity or "").split())
    user_id = str(reviewer_user_id or "").strip()
    if not user_id or not identity:
        raise ShadowReviewError("mismatch review requires an authenticated reviewer identity")
    document = {
        "schema_version": SCHEMA_VERSION,
        "kind": MISMATCH_REVIEW_KIND,
        "subject": {
            "workspace_id": source.document["workspace_id"],
            "actions": list(source.document["actions"]),
            "revision": source.document["runtime_revision"],
            "source_ref": source.source_ref,
            "candidate_config_sha256": source.document["candidate_config_sha256"],
            "candidate_config_version": source.document["candidate_config_version"],
        },
        "reviewed_by": {"user_id": user_id, "identity": identity},
        "reviewed_at": reviewed_at.astimezone(UTC).isoformat(),
        "entries": _normalized_entries(entries),
    }
    # Validate coverage now so the audit ledger never records a decorative or
    # partial approval for this exact source manifest.
    _validate_review_document(document, source=source, validated_at=None)
    return document


def _validate_review_document(
    document: Any,
    *,
    source: ValidatedSourceManifest,
    validated_at: datetime | None,
) -> tuple[dict[str, Any], dict[str, int], tuple[str, ...]]:
    if not isinstance(document, Mapping):
        raise ShadowReviewError("mismatch review document must be an object")
    normalized = dict(document)
    _exact_keys(normalized, _REVIEW_DOCUMENT_KEYS, field="mismatch review document")
    if normalized.get("schema_version") != SCHEMA_VERSION:
        raise ShadowReviewError("mismatch review schema_version must be 1")
    if normalized.get("kind") != MISMATCH_REVIEW_KIND:
        raise ShadowReviewError("mismatch review kind is invalid")
    subject = normalized.get("subject")
    if not isinstance(subject, Mapping):
        raise ShadowReviewError("mismatch review subject must be an object")
    subject = dict(subject)
    _exact_keys(subject, _REVIEW_SUBJECT_KEYS, field="mismatch review subject")
    expected_subject = {
        "workspace_id": source.document["workspace_id"],
        "actions": list(source.document["actions"]),
        "revision": source.document["runtime_revision"],
        "source_ref": source.source_ref,
        "candidate_config_sha256": source.document["candidate_config_sha256"],
        "candidate_config_version": source.document["candidate_config_version"],
    }
    if subject != expected_subject:
        raise ShadowReviewError("mismatch review subject does not match the source manifest")
    reviewer = normalized.get("reviewed_by")
    if not isinstance(reviewer, Mapping):
        raise ShadowReviewError("mismatch review reviewed_by must be an object")
    reviewer = dict(reviewer)
    _exact_keys(reviewer, _REVIEWER_KEYS, field="mismatch review reviewed_by")
    if (
        not str(reviewer.get("user_id") or "").strip()
        or not str(reviewer.get("identity") or "").strip()
    ):
        raise ShadowReviewError("mismatch review reviewer identity is incomplete")
    reviewed_at = _timestamp(normalized.get("reviewed_at"), field="mismatch review reviewed_at")
    if reviewed_at < source.window_ended_at:
        raise ShadowReviewError("mismatch review predates the observation window")
    if validated_at is not None and reviewed_at > validated_at.astimezone(UTC):
        raise ShadowReviewError("mismatch review postdates evidence validation")
    entries = _normalized_entries(normalized.get("entries"))
    if entries != normalized.get("entries"):
        raise ShadowReviewError("mismatch review entries are not in canonical order")

    mismatch_ids = {
        row_id for row_id, row in source.rows_by_id.items() if int(row["mismatches"]) > 0
    }
    if not mismatch_ids:
        raise ShadowReviewError("mismatch review cannot approve a source with no mismatches")
    seen: set[str] = set()
    explained = {action: 0 for action in source.summaries}
    for index, entry in enumerate(entries):
        action = entry["action"]
        if action not in explained:
            raise ShadowReviewError(f"mismatch review entry {index} action is outside the subject")
        for row_id in entry["observation_ids"]:
            if row_id in seen:
                raise ShadowReviewError(f"mismatch observation {row_id} is reviewed more than once")
            row = source.rows_by_id.get(row_id)
            if row is None:
                raise ShadowReviewError(f"mismatch review references unknown observation {row_id}")
            if row["action"] != action:
                raise ShadowReviewError(f"mismatch review action differs for observation {row_id}")
            if int(row["mismatches"]) <= 0:
                raise ShadowReviewError(f"mismatch review references matching observation {row_id}")
            explained[action] += int(row["mismatches"])
            seen.add(row_id)
    missing = sorted(mismatch_ids - seen)
    if missing:
        raise ShadowReviewError(
            "mismatch review does not cover every mismatching observation: " + ", ".join(missing)
        )
    return normalized, explained, tuple(sorted(seen))


def validate_review_envelope(
    envelope: Any,
    *,
    source: ValidatedSourceManifest,
    validated_at: datetime | None,
) -> ValidatedMismatchReview:
    if not isinstance(envelope, Mapping):
        raise ShadowReviewError("mismatch review envelope must be an object")
    payload = dict(envelope)
    if set(payload) != {"audit_id", "artifact_ref", "document"}:
        raise ShadowReviewError("mismatch review envelope fields differ from the contract")
    audit_id = str(payload.get("audit_id") or "").strip()
    artifact_ref = str(payload.get("artifact_ref") or "")
    if not audit_id:
        raise ShadowReviewError("mismatch review audit_id is required")
    if artifact_ref != sha256_ref(payload.get("document")):
        raise ShadowReviewError("mismatch review artifact_ref does not match its document")
    document, explained, reviewed_ids = _validate_review_document(
        payload.get("document"),
        source=source,
        validated_at=validated_at,
    )
    return ValidatedMismatchReview(
        envelope={"audit_id": audit_id, "artifact_ref": artifact_ref, "document": document},
        explained_by_action=explained,
        reviewed_observation_ids=reviewed_ids,
    )


def apply_review_to_summaries(
    source: ValidatedSourceManifest,
    review: ValidatedMismatchReview | None,
) -> dict[str, dict[str, int]]:
    summaries = {action: dict(values) for action, values in source.summaries.items()}
    if review is not None:
        for action, explained in review.explained_by_action.items():
            summaries[action]["explained_mismatches"] = explained
            summaries[action]["unexplained_mismatches"] = (
                summaries[action]["mismatches"] - explained
            )
    return summaries


def expected_blockers(summaries: Mapping[str, Mapping[str, int]]) -> list[dict[str, Any]]:
    missing = sorted(
        action for action, summary in summaries.items() if summary.get("evaluations") == 0
    )
    unexplained = sorted(
        action
        for action, summary in summaries.items()
        if int(summary.get("unexplained_mismatches") or 0) > 0
    )
    blockers: list[dict[str, Any]] = []
    if missing:
        blockers.append({"code": "missing_observations", "actions": missing})
    if unexplained:
        blockers.append({"code": "unexplained_mismatches", "actions": unexplained})
    return blockers


def assert_source_manifest_matches_audit(
    db: DBSession,
    source: ValidatedSourceManifest,
) -> None:
    """Verify the content-addressed rows against the server-owned audit ledger."""

    row_ids = sorted(source.rows_by_id)
    # Query the complete bounded source, not only caller-supplied ids. Otherwise
    # a reviewer could be shown a self-consistent subset that silently omitted
    # the very mismatch the approval is meant to govern.
    rows = (
        db.query(AuditLog)
        .filter(
            AuditLog.workspace_id == source.document["workspace_id"],
            AuditLog.event_type == SHADOW_EVENT_TYPE,
            AuditLog.timestamp >= source.window_started_at.astimezone(UTC).replace(tzinfo=None),
            AuditLog.timestamp <= source.window_ended_at.astimezone(UTC).replace(tzinfo=None),
        )
        .order_by(AuditLog.timestamp.asc(), AuditLog.id.asc())
        .all()
    )
    selected_actions = set(source.document["actions"])
    relevant: list[AuditLog] = []
    for row in rows:
        if not isinstance(row.details, Mapping):
            raise ShadowReviewError(f"audit observation {row.id} has no details object")
        if row.details.get("action") in selected_actions:
            relevant.append(row)
    by_id = {row.id: row for row in relevant}
    if set(by_id) != set(row_ids):
        missing_from_manifest = sorted(set(by_id) - set(row_ids))
        missing_from_ledger = sorted(set(row_ids) - set(by_id))
        raise ShadowReviewError(
            "shadow source manifest is not exhaustive for its action/window"
            + (
                "; omitted audit observations=" + ", ".join(missing_from_manifest)
                if missing_from_manifest
                else ""
            )
            + (
                "; unknown manifest observations=" + ", ".join(missing_from_ledger)
                if missing_from_ledger
                else ""
            )
        )
    for row_id in row_ids:
        row = by_id[row_id]
        details = row.details if isinstance(row.details, Mapping) else {}
        if (
            details.get("origin") != "server"
            or details.get("policy_version") != 2
            or details.get("configured_mode") != "shadow"
        ):
            raise ShadowReviewError(f"audit observation {row_id} is not canonical shadow evidence")
        counters = {name: details.get(name) for name in SHADOW_COUNTERS}
        timestamp = row.timestamp
        timestamp = (
            timestamp.replace(tzinfo=UTC) if timestamp.tzinfo is None else timestamp.astimezone(UTC)
        )
        rebuilt = build_source_manifest_row(
            row_id=row.id,
            timestamp=timestamp,
            action=str(details.get("action") or ""),
            evaluation_count=details.get("evaluation_count"),
            runtime_revision=str(details.get("runtime_revision") or ""),
            candidate_config_sha256=str(details.get("candidate_config_sha256") or ""),
            candidate_config_version=details.get("candidate_config_version"),
            counters=counters,
        )
        if rebuilt != source.rows_by_id[row_id]:
            raise ShadowReviewError(f"audit observation {row_id} differs from source_manifest")


def record_mismatch_review(
    db: DBSession,
    *,
    source: ValidatedSourceManifest,
    reviewer_user_id: str,
    reviewer_identity: str,
    reviewed_at: datetime,
    entries: Any,
) -> dict[str, Any]:
    """Persist one authoritative, content-addressed mismatch approval."""

    missing_actions = sorted(
        action for action, summary in source.summaries.items() if summary["evaluations"] == 0
    )
    if missing_actions:
        raise ShadowReviewError(
            "mismatch review requires observations for every action: " + ", ".join(missing_actions)
        )
    assert_source_manifest_matches_audit(db, source)
    document = build_review_document(
        source=source,
        reviewer_user_id=reviewer_user_id,
        reviewer_identity=reviewer_identity,
        reviewed_at=reviewed_at,
        entries=entries,
    )
    envelope = {
        "audit_id": str(uuid4()),
        "artifact_ref": sha256_ref(document),
        "document": document,
    }
    db.add(
        AuditLog(
            id=envelope["audit_id"],
            workspace_id=source.document["workspace_id"],
            timestamp=reviewed_at.astimezone(UTC).replace(tzinfo=None),
            event_type=MISMATCH_REVIEW_EVENT_TYPE,
            actor=reviewer_identity,
            details={
                "artifact_ref": envelope["artifact_ref"],
                "document": document,
            },
            severity="warning",
        )
    )
    db.flush()
    return envelope


def load_persisted_review(
    db: DBSession,
    *,
    workspace_id: str,
    audit_id: str,
) -> dict[str, Any]:
    row = (
        db.query(AuditLog)
        .filter(
            AuditLog.id == audit_id,
            AuditLog.workspace_id == workspace_id,
            AuditLog.event_type == MISMATCH_REVIEW_EVENT_TYPE,
        )
        .one_or_none()
    )
    if row is None or not isinstance(row.details, Mapping):
        raise ShadowReviewError("mismatch review is not present in the authoritative audit ledger")
    details = dict(row.details)
    envelope = {
        "audit_id": row.id,
        "artifact_ref": details.get("artifact_ref"),
        "document": details.get("document"),
    }
    reviewed_by = (
        envelope["document"].get("reviewed_by")
        if isinstance(envelope.get("document"), Mapping)
        else None
    )
    if not isinstance(reviewed_by, Mapping) or row.actor != reviewed_by.get("identity"):
        raise ShadowReviewError("mismatch review actor differs from its reviewer identity")
    return envelope
