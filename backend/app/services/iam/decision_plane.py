"""Authorization decision plane v2 with granular compat/shadow/enforce rollout.

The existing IAM engine remains the candidate policy evaluator.  This module
owns rollout semantics: a caller supplies the pre-existing (legacy) decision,
and the plane compares it with the candidate without changing behaviour in
``compat`` or ``shadow``.  Only an explicit workspace + resource/action
``enforce`` entry makes the candidate authoritative.

Configuration lives in the already versioned
``WorkspaceIAMConfig.capability_overrides`` document under
``authorization_v2`` so this additive tranche needs no schema migration::

    {
      "authorization_v2": {
        "policy_version": 2,
        "default_mode": "compat",
        "modes": {
          "mail_draft.mail.send": "shadow",
          "decision.*": "shadow"
        }
      }
    }

Exact keys win over ``resource.*``, then ``*.action``, then ``*.*`` and the
default.  Unknown or malformed values fail safe to ``compat``.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import Enum
from functools import lru_cache
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm import object_session

from app.core.config import settings
from app.core.iam.dependencies import evaluate_permission
from app.models.audit import AuditLog


# Protected runners and the API host may differ slightly in wall-clock time.
# Promotion accepts the same bounded skew as the evidence validator; larger
# causal inversions still fail closed.
PROMOTION_VALIDATION_CLOCK_SKEW = timedelta(minutes=5)
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember
from app.services.audit_logger import emit_audit_event
from app.services.iam.config_service import effective_role_flags, load_iam_config
from app.services.iam.evidence_contracts import junit_count_errors
from app.services.iam.manifest import MANIFESTS, get_manifest
from app.services.iam.shadow_review import (
    MISMATCH_REVIEW_KIND,
    ShadowReviewError,
    apply_review_to_summaries,
    assert_source_manifest_matches_audit,
    load_persisted_review,
    sha256_ref,
    validate_review_envelope,
    validate_source_manifest,
)


class AuthorizationMode(str, Enum):
    COMPAT = "compat"
    SHADOW = "shadow"
    ENFORCE = "enforce"
    INVALID_ENFORCE = "invalid_enforce"


GIT_SHA_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
ACTION_KEY_RE = re.compile(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_.]*")
ATTESTATIONS_KEY = "enforcement_attestations"
PROMOTION_EVENT_TYPE = "lot7.authorization.enforce_promoted"
PROMOTION_RECEIPT_KIND = "authorization_v2_enforcement_promotion"
PROMOTION_RECEIPT_KEY = "promotion_receipt"


def build_promotion_receipt_document(
    *,
    workspace_id: str,
    promotion: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the canonical server-side receipt before its audit id exists."""

    promoted = copy.deepcopy(dict(promotion))
    promoted.pop(PROMOTION_RECEIPT_KEY, None)
    source = copy.deepcopy(dict(source_manifest))
    source_ref = str(
        (promoted.get("shadow_observation") or {}).get("source_ref")
        if isinstance(promoted.get("shadow_observation"), Mapping)
        else ""
    )
    return {
        "schema_version": 1,
        "kind": PROMOTION_RECEIPT_KIND,
        "workspace_id": str(workspace_id),
        "actions": copy.deepcopy(promoted.get("actions")),
        "promotion": promoted,
        "shadow_source": {
            "artifact_ref": source_ref,
            "document": source,
        },
    }


def candidate_config_sha256(config: Optional[WorkspaceIAMConfig]) -> str:
    """Fingerprint the policy inputs that can change a candidate decision.

    Rollout modes are deliberately excluded: promotion changes ``shadow`` to
    ``enforce`` but must not change the candidate evaluator being attested.
    Exact action modes are bound separately by the shadow event and promotion
    gate.  The deployed Git SHA binds the executable evaluator; serialising the
    manifests here also makes policy drift explicit in local/status tooling.
    """

    policy = authorization_v2_config(config)
    # The digest is a pure function of the three values below plus the static
    # manifest registry, but serialising every manifest is far from free.  An
    # aggregate resolves thousands of resources against one config, so key the
    # cache on the complete input set: the digest stays byte-identical while
    # the canonical serialisation runs once per distinct policy.
    return _candidate_config_sha256(
        json.dumps(
            {
                "policy_version": policy.get("policy_version"),
                "default_mode": policy.get("default_mode", AuthorizationMode.COMPAT.value),
                "role_flags": effective_role_flags(config),
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    )


@lru_cache(maxsize=256)
def _candidate_config_sha256(inputs: str) -> str:
    payload = json.loads(inputs)
    manifests = []
    for manifest_id, manifest in sorted(MANIFESTS.items()):
        manifests.append(
            {
                "id": manifest_id,
                "permissions": [
                    {
                        "resource_kind": rule.resource_kind,
                        "action": rule.action,
                        "roles": list(rule.roles),
                        "conditions": list(rule.conditions),
                        "policy_id": rule.policy_id,
                    }
                    for rule in manifest.permissions
                ],
            }
        )
    document = {
        "schema_version": 1,
        "authorization_v2": {
            "policy_version": payload["policy_version"],
            "default_mode": payload["default_mode"],
        },
        "role_flags": payload["role_flags"],
        "manifests": manifests,
    }
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ActionResolution:
    resource_kind: str
    action: str
    mode: str
    effective_allowed: bool
    legacy_allowed: bool
    candidate_allowed: bool
    mismatch: bool
    reason: str
    policy_id: str
    runtime_revision: str = ""
    candidate_config_sha256: str = ""
    candidate_config_version: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def authorization_v2_config(config: Optional[WorkspaceIAMConfig]) -> dict[str, Any]:
    overrides = (
        config.capability_overrides
        if config and isinstance(config.capability_overrides, Mapping)
        else {}
    )
    raw = overrides.get("authorization_v2") if isinstance(overrides, Mapping) else None
    return dict(raw) if isinstance(raw, Mapping) else {}


# Cache for one request's enforce-attestation lookups.  ``resolve_mode`` is
# called once per candidate resource (every Run / SkillInvocation in an
# aggregate), yet its DB-backed receipt validation depends only on
# ``(action, config.version)`` — not on the resource.  Keying the resolved
# mode by that pair lets a batch of thousands reuse a single audit-ledger
# read instead of one per row.
ModeResolutionCache = dict[tuple[str, Optional[int]], "AuthorizationMode"]


def resolve_mode(
    config: Optional[WorkspaceIAMConfig],
    *,
    resource_kind: str,
    action: str,
    db: Optional[DBSession] = None,
    mode_cache: Optional[ModeResolutionCache] = None,
) -> AuthorizationMode:
    payload = authorization_v2_config(config)
    modes = payload.get("modes")
    modes = modes if isinstance(modes, Mapping) else {}
    exact_key = f"{resource_kind}.{action}"
    raw = None
    source_key: Optional[str] = None
    for key in (
        exact_key,
        f"{resource_kind}.*",
        f"*.{action}",
        "*.*",
    ):
        if key in modes:
            raw = modes[key]
            source_key = key
            break
    if raw is None:
        raw = payload.get("default_mode", AuthorizationMode.COMPAT.value)
    try:
        configured = AuthorizationMode(str(raw).strip().lower())
    except ValueError:
        return AuthorizationMode.COMPAT
    if configured is not AuthorizationMode.ENFORCE:
        return configured

    # Enforce is never inherited.  A wildcard/default entry is useful while
    # preparing a rollout document, but cannot become an authorization bypass.
    # Runtime authority requires the exact action promoted by the rollout gate.
    if source_key != exact_key:
        return AuthorizationMode.SHADOW

    cache_key: Optional[tuple[str, Optional[int]]] = None
    if mode_cache is not None:
        version = getattr(config, "version", None)
        cache_key = (exact_key, int(version) if isinstance(version, int) else None)
        if cache_key in mode_cache:
            return mode_cache[cache_key]

    if enforcement_attestation_errors(
        config=config,
        action=exact_key,
        require_runtime_revision=True,
        db=db,
        require_server_receipt=True,
    ):
        # An exact enforce declaration is an authorization boundary.  Drift
        # must fail closed; silently falling back to legacy/shadow would reopen
        # actions precisely when the attestation is no longer trustworthy.
        resolved = AuthorizationMode.INVALID_ENFORCE
    else:
        resolved = AuthorizationMode.ENFORCE
    if mode_cache is not None and cache_key is not None:
        mode_cache[cache_key] = resolved
    return resolved


def _aware_timestamp(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _valid_counter(value: Any, *, positive: bool = False) -> bool:
    return (
        not isinstance(value, bool) and isinstance(value, int) and value >= (1 if positive else 0)
    )


def _enforcement_attestation_errors(
    *,
    config: Optional[WorkspaceIAMConfig],
    policy: Mapping[str, Any],
    action: str,
    require_runtime_revision: bool,
) -> list[str]:
    """Validate one persisted promotion group without trusting config alone."""

    errors: list[str] = []
    if policy.get("policy_version") != 2:
        errors.append("authorization policy version is not 2")
    modes = policy.get("modes")
    if not isinstance(modes, Mapping):
        return [*errors, "authorization modes are missing"]
    attestations = policy.get(ATTESTATIONS_KEY)
    if not isinstance(attestations, Mapping):
        return [*errors, "enforcement attestations are missing"]
    raw = attestations.get(action)
    if not isinstance(raw, Mapping):
        return [*errors, "exact enforce action has no attestation"]
    attestation = dict(raw)
    workspace_id = str(getattr(config, "workspace_id", "") or "")
    if attestation.get("schema_version") != 1:
        errors.append("invalid attestation schema version")
    if require_runtime_revision and not workspace_id:
        errors.append("attestation workspace drift")
    elif workspace_id and attestation.get("workspace_id") != workspace_id:
        errors.append("attestation workspace drift")

    revision = str(attestation.get("revision") or "")
    if GIT_SHA_RE.fullmatch(revision) is None:
        errors.append("attestation revision is not an exact Git SHA")
    if require_runtime_revision:
        runtime_revision = str(settings.agentium_image_revision or "").strip()
        if GIT_SHA_RE.fullmatch(runtime_revision) is None or revision != runtime_revision:
            errors.append("attestation revision differs from the running image")
    digest = str(attestation.get("evidence_sha256") or "")
    if SHA256_RE.fullmatch(digest) is None:
        errors.append("invalid attestation evidence digest")
    trusted_runner = attestation.get("trusted_runner")
    if not isinstance(trusted_runner, Mapping):
        errors.append("trusted runner attestation is missing")
    else:
        if trusted_runner.get("commit_sha") != revision:
            errors.append("trusted runner commit differs from attested revision")
        for field in ("ref", "project_id", "pipeline_id", "job_id", "issuer"):
            if not str(trusted_runner.get(field) or "").strip():
                errors.append(f"trusted runner {field} is missing")
        trusted_issuer = str(settings.authorization_v2_trusted_oidc_issuer or "").rstrip("/")
        runner_issuer = str(trusted_runner.get("issuer") or "").rstrip("/")
        if not trusted_issuer.startswith("https://") or runner_issuer != trusted_issuer:
            errors.append("trusted runner issuer is not the configured trust anchor")
        trusted_project_id = str(settings.authorization_v2_trusted_project_id or "").strip()
        if (
            not trusted_project_id
            or str(trusted_runner.get("project_id") or "") != trusted_project_id
        ):
            errors.append("trusted runner project is not the configured trust anchor")
        trusted_ref = str(settings.authorization_v2_trusted_ref or "").strip()
        if not trusted_ref or str(trusted_runner.get("ref") or "") != trusted_ref:
            errors.append("trusted runner ref is not the configured trust anchor")
        if trusted_runner.get("ref_protected") is not True:
            errors.append("trusted runner ref is not protected")
    for field in ("validated_by", "environment", "promoted_by"):
        if not str(attestation.get(field) or "").strip():
            errors.append(f"attestation {field} is missing")
    validated_at = _aware_timestamp(attestation.get("validated_at"))
    promoted_at = _aware_timestamp(attestation.get("promoted_at"))
    if validated_at is None:
        errors.append("invalid attestation validated_at")
    if promoted_at is None:
        errors.append("invalid attestation promoted_at")
    elif (
        validated_at is not None
        and promoted_at + PROMOTION_VALIDATION_CLOCK_SKEW < validated_at
    ):
        errors.append("attestation promotion predates validation")

    group = attestation.get("actions")
    if (
        not isinstance(group, list)
        or not group
        or any(not isinstance(peer, str) or ACTION_KEY_RE.fullmatch(peer) is None for peer in group)
        or group != sorted(set(group))
        or action not in group
    ):
        errors.append("invalid attestation action group")
        return errors
    explained_total = 0
    for peer in group:
        if modes.get(peer) != AuthorizationMode.ENFORCE.value:
            errors.append(f"attested peer {peer} is not exact enforce")
        if attestations.get(peer) != raw:
            errors.append(f"attestation group drift for {peer}")

    contracts = attestation.get("contracts")
    if not isinstance(contracts, Mapping):
        errors.append("attestation contract summary is missing")
    else:
        for contract_name in ("legacy", "candidate"):
            contract = contracts.get(contract_name)
            if not isinstance(contract, Mapping):
                errors.append(f"attestation {contract_name} contract is missing")
                continue
            if contract.get("format") != "junit":
                errors.append(f"attestation {contract_name} contract is not JUnit")
            artifact_ref = str(contract.get("artifact_ref") or "")
            if (
                not artifact_ref.startswith("sha256:")
                or SHA256_RE.fullmatch(artifact_ref[7:]) is None
            ):
                errors.append(
                    f"attestation {contract_name} contract artifact is not content-addressed"
                )
            errors.extend(
                f"attestation {contract_name} {error}" for error in junit_count_errors(contract)
            )
            producer = contract.get("producer")
            if not isinstance(producer, Mapping):
                errors.append(f"attestation {contract_name} producer is missing")
                continue
            if producer.get("commit_sha") != revision:
                errors.append(f"attestation {contract_name} producer revision drift")
            for field in ("issuer", "project_id", "pipeline_id", "job_id", "ref"):
                if not str(producer.get(field) or "").strip():
                    errors.append(f"attestation {contract_name} producer {field} is missing")
            if str(producer.get("issuer") or "").rstrip("/") != str(
                settings.authorization_v2_trusted_oidc_issuer or ""
            ).rstrip("/"):
                errors.append(f"attestation {contract_name} producer issuer drift")
            if str(producer.get("project_id") or "") != str(
                settings.authorization_v2_trusted_project_id or ""
            ):
                errors.append(f"attestation {contract_name} producer project drift")
            if str(producer.get("ref") or "") != str(settings.authorization_v2_trusted_ref or ""):
                errors.append(f"attestation {contract_name} producer ref drift")
            if producer.get("ref_protected") is not True:
                errors.append(f"attestation {contract_name} producer ref is not protected")

    candidate_digest = str(attestation.get("candidate_config_sha256") or "")
    if SHA256_RE.fullmatch(candidate_digest) is None:
        errors.append("invalid attestation candidate config digest")
    elif config is not None and candidate_digest != candidate_config_sha256(config):
        errors.append("attestation candidate config differs from runtime policy")
    if not _valid_counter(attestation.get("candidate_config_version"), positive=True):
        errors.append("invalid attestation candidate config version")

    shadow = attestation.get("shadow_observation")
    if not isinstance(shadow, Mapping):
        errors.append("attestation shadow observation is missing")
        return errors
    source = str(shadow.get("source") or "").strip()
    source_ref = str(shadow.get("source_ref") or "").strip()
    if not source:
        errors.append("attestation shadow source is missing")
    if not source_ref.startswith("sha256:") or SHA256_RE.fullmatch(source_ref[7:]) is None:
        errors.append("attestation shadow source is mutable")
    if shadow.get("runtime_revision") != revision:
        errors.append("attestation shadow revision drift")
    if shadow.get("candidate_config_sha256") != candidate_digest:
        errors.append("attestation shadow candidate config drift")
    if shadow.get("candidate_config_version") != attestation.get("candidate_config_version"):
        errors.append("attestation shadow candidate config version drift")
    started_at = _aware_timestamp(shadow.get("window_started_at"))
    ended_at = _aware_timestamp(shadow.get("window_ended_at"))
    if started_at is None or ended_at is None:
        errors.append("invalid attestation shadow window")
    elif ended_at < started_at:
        errors.append("attestation shadow window is inverted")
    elif validated_at is not None and validated_at < ended_at:
        errors.append("attestation validation predates shadow window")

    summaries = shadow.get("actions")
    if not isinstance(summaries, Mapping) or set(summaries) != set(group):
        errors.append("attestation shadow action group drift")
        return errors
    counter_names = (
        "legacy_allowed",
        "legacy_denied",
        "candidate_allowed",
        "candidate_denied",
        "matches",
        "mismatches",
        "explained_mismatches",
        "unexplained_mismatches",
    )
    for peer in group:
        counters = summaries.get(peer)
        if not isinstance(counters, Mapping):
            errors.append(f"attestation counters missing for {peer}")
            continue
        evaluations = counters.get("evaluations")
        if not _valid_counter(evaluations, positive=True):
            errors.append(f"attestation evaluations invalid for {peer}")
            continue
        if any(not _valid_counter(counters.get(name)) for name in counter_names):
            errors.append(f"attestation counters invalid for {peer}")
            continue
        if counters["legacy_allowed"] + counters["legacy_denied"] != evaluations:
            errors.append(f"legacy counters do not balance for {peer}")
        if counters["candidate_allowed"] + counters["candidate_denied"] != evaluations:
            errors.append(f"candidate counters do not balance for {peer}")
        if counters["matches"] + counters["mismatches"] != evaluations:
            errors.append(f"comparison counters do not balance for {peer}")
        if (
            counters["explained_mismatches"] + counters["unexplained_mismatches"]
            != counters["mismatches"]
        ):
            errors.append(f"mismatch counters do not balance for {peer}")
        if counters["unexplained_mismatches"] != 0:
            errors.append(f"unexplained mismatches remain for {peer}")
        explained_total += counters["explained_mismatches"]

    review = shadow.get("mismatch_review")
    if explained_total == 0:
        if review is not None:
            errors.append("attestation carries a mismatch review without explained mismatches")
        return errors
    if not isinstance(review, Mapping):
        errors.append("explained mismatches have no authoritative review")
        return errors
    if set(review) != {"audit_id", "artifact_ref", "document"}:
        errors.append("mismatch review envelope fields are invalid")
        return errors
    document = review.get("document")
    if not str(review.get("audit_id") or "").strip() or not isinstance(document, Mapping):
        errors.append("mismatch review envelope is incomplete")
        return errors
    if review.get("artifact_ref") != sha256_ref(document):
        errors.append("mismatch review content digest drift")
    if document.get("schema_version") != 1 or document.get("kind") != MISMATCH_REVIEW_KIND:
        errors.append("mismatch review document contract is invalid")
    subject = document.get("subject")
    if not isinstance(subject, Mapping):
        errors.append("mismatch review subject is missing")
    else:
        expected_review_subject = {
            "workspace_id": workspace_id,
            "actions": list(group),
            "revision": revision,
            "source_ref": source_ref,
            "candidate_config_sha256": candidate_digest,
            "candidate_config_version": attestation.get("candidate_config_version"),
        }
        if dict(subject) != expected_review_subject:
            errors.append("mismatch review subject drift")
    reviewer = document.get("reviewed_by")
    if (
        not isinstance(reviewer, Mapping)
        or not str(reviewer.get("user_id") or "").strip()
        or not str(reviewer.get("identity") or "").strip()
    ):
        errors.append("mismatch review reviewer identity is missing")
    reviewed_at = _aware_timestamp(document.get("reviewed_at"))
    if reviewed_at is None:
        errors.append("mismatch review timestamp is invalid")
    elif validated_at is not None and reviewed_at > validated_at:
        errors.append("mismatch review postdates evidence validation")
    entries = document.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append("mismatch review entries are missing")
    return errors


def _promotion_receipt_errors(
    *,
    db: Optional[DBSession],
    config: Optional[WorkspaceIAMConfig],
    action: str,
) -> list[str]:
    """Reload the canonical promotion and all of its server-owned evidence.

    The JSON policy is only a cache of the rollout decision.  Authority comes
    from an exact, content-addressed promotion row in ``AuditLog`` which, in
    turn, embeds the immutable shadow-source manifest.  Runtime validation
    rebuilds that manifest from the original shadow audit rows and reloads the
    mismatch review when one was required.
    """

    errors: list[str] = []
    policy = authorization_v2_config(config)
    attestations = policy.get(ATTESTATIONS_KEY)
    raw_attestation = attestations.get(action) if isinstance(attestations, Mapping) else None
    if not isinstance(raw_attestation, Mapping):
        return ["promotion receipt has no attestation to bind"]
    attestation = dict(raw_attestation)
    workspace_id = str(getattr(config, "workspace_id", "") or "")
    receipt = attestation.get(PROMOTION_RECEIPT_KEY)
    if not isinstance(receipt, Mapping) or set(receipt) != {"audit_id", "artifact_ref"}:
        return ["canonical promotion receipt is missing or malformed"]
    audit_id = str(receipt.get("audit_id") or "").strip()
    artifact_ref = str(receipt.get("artifact_ref") or "").strip()
    if not audit_id:
        errors.append("canonical promotion audit id is missing")
    if not artifact_ref.startswith("sha256:") or SHA256_RE.fullmatch(artifact_ref[7:]) is None:
        errors.append("canonical promotion receipt is not content-addressed")

    session = db or (object_session(config) if config is not None else None)
    if session is None:
        return [*errors, "canonical promotion ledger is unavailable"]
    if errors:
        return errors
    row = (
        session.query(AuditLog)
        .filter(
            AuditLog.id == audit_id,
            AuditLog.workspace_id == workspace_id,
            AuditLog.event_type == PROMOTION_EVENT_TYPE,
        )
        .one_or_none()
    )
    if row is None or not isinstance(row.details, Mapping):
        return ["canonical promotion is absent from the server audit ledger"]
    if row.actor != attestation.get("promoted_by"):
        errors.append("canonical promotion actor differs from the attestation")
    details = dict(row.details)
    if set(details) != {"artifact_ref", "document"}:
        return [*errors, "canonical promotion audit fields are invalid"]
    document = details.get("document")
    if not isinstance(document, Mapping):
        return [*errors, "canonical promotion document is missing"]
    document = dict(document)
    if details.get("artifact_ref") != artifact_ref or sha256_ref(document) != artifact_ref:
        errors.append("canonical promotion content digest drift")
    if set(document) != {
        "schema_version",
        "kind",
        "workspace_id",
        "actions",
        "promotion",
        "shadow_source",
    }:
        return [*errors, "canonical promotion document fields are invalid"]
    if document.get("schema_version") != 1 or document.get("kind") != PROMOTION_RECEIPT_KIND:
        errors.append("canonical promotion document contract is invalid")
    if document.get("workspace_id") != workspace_id:
        errors.append("canonical promotion workspace drift")
    if document.get("actions") != attestation.get("actions"):
        errors.append("canonical promotion action group drift")
    expected_promotion = {
        key: value for key, value in attestation.items() if key != PROMOTION_RECEIPT_KEY
    }
    if document.get("promotion") != expected_promotion:
        errors.append("canonical promotion differs from the configured attestation")

    shadow = attestation.get("shadow_observation")
    source_envelope = document.get("shadow_source")
    if not isinstance(shadow, Mapping) or not isinstance(source_envelope, Mapping):
        return [*errors, "canonical shadow source is missing"]
    if set(source_envelope) != {"artifact_ref", "document"}:
        return [*errors, "canonical shadow source envelope fields are invalid"]
    source_ref = str(shadow.get("source_ref") or "")
    source_document = source_envelope.get("document")
    if source_envelope.get("artifact_ref") != source_ref:
        errors.append("canonical shadow source reference drift")
    started_at = _aware_timestamp(shadow.get("window_started_at"))
    ended_at = _aware_timestamp(shadow.get("window_ended_at"))
    group = attestation.get("actions")
    version = attestation.get("candidate_config_version")
    if (
        started_at is None
        or ended_at is None
        or not isinstance(group, list)
        or not isinstance(version, int)
        or isinstance(version, bool)
    ):
        return [*errors, "canonical shadow source binding is incomplete"]
    try:
        source = validate_source_manifest(
            source_document,
            source_ref=source_ref,
            workspace_id=workspace_id,
            actions=group,
            revision=str(attestation.get("revision") or ""),
            candidate_config_sha256=str(attestation.get("candidate_config_sha256") or ""),
            candidate_config_version=version,
            window_started_at=started_at,
            window_ended_at=ended_at,
        )
        assert_source_manifest_matches_audit(session, source)
    except (ShadowReviewError, TypeError, ValueError) as exc:
        errors.append(f"canonical shadow source is invalid: {exc}")
        return errors

    review = shadow.get("mismatch_review")
    expected_summaries = source.summaries
    if review is not None:
        if not isinstance(review, Mapping):
            errors.append("canonical mismatch review envelope is invalid")
        else:
            try:
                validated_at = _aware_timestamp(attestation.get("validated_at"))
                if validated_at is None:
                    raise ShadowReviewError("promotion validation timestamp is invalid")
                validated_review = validate_review_envelope(
                    review,
                    source=source,
                    validated_at=validated_at,
                )
                persisted_review = load_persisted_review(
                    session,
                    workspace_id=workspace_id,
                    audit_id=str(review.get("audit_id") or ""),
                )
            except ShadowReviewError as exc:
                errors.append(f"canonical mismatch review is unavailable: {exc}")
            else:
                if persisted_review != dict(review):
                    errors.append("canonical mismatch review differs from the audit ledger")
                expected_summaries = apply_review_to_summaries(source, validated_review)
    if shadow.get("actions") != expected_summaries:
        errors.append("canonical shadow summaries differ from the authoritative source")
    return errors


def enforcement_attestation_errors(
    *,
    config: Optional[WorkspaceIAMConfig],
    action: str,
    require_runtime_revision: bool = True,
    db: Optional[DBSession] = None,
    require_server_receipt: bool = True,
) -> list[str]:
    """Expose the runtime's exact enforce-coherence check to rollout tooling."""

    errors = _enforcement_attestation_errors(
        config=config,
        policy=authorization_v2_config(config),
        action=action,
        require_runtime_revision=require_runtime_revision,
    )
    if require_server_receipt:
        errors.extend(
            _promotion_receipt_errors(
                db=db,
                config=config,
                action=action,
            )
        )
    return errors


def resolve_action(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
    resource_kind: str,
    action: str,
    legacy_allowed: bool,
    resource_attrs: Optional[dict[str, Any]] = None,
    membership: Optional[WorkspaceMember] = None,
    config: Optional[WorkspaceIAMConfig] = None,
    mode_cache: Optional[ModeResolutionCache] = None,
    audit_shadow_diff: bool = True,
    audit_shadow_evidence: bool = True,
) -> ActionResolution:
    """Compare the legacy and candidate decisions and select the effective one."""

    return resolve_candidate_permission(
        db,
        user=user,
        workspace=workspace,
        resource_kind=resource_kind,
        action=action,
        legacy_allowed=legacy_allowed,
        candidate_manifest="agentium_object_actions",
        resource_attrs=resource_attrs,
        membership=membership,
        config=config,
        mode_cache=mode_cache,
        audit_shadow_diff=audit_shadow_diff,
        audit_shadow_evidence=audit_shadow_evidence,
    )


def resolve_candidate_permission(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
    resource_kind: str,
    action: str,
    legacy_allowed: bool,
    candidate_manifest: str,
    resource_attrs: Optional[dict[str, Any]] = None,
    membership: Optional[WorkspaceMember] = None,
    config: Optional[WorkspaceIAMConfig] = None,
    mode_cache: Optional[ModeResolutionCache] = None,
    audit_shadow_diff: bool = True,
    audit_shadow_evidence: bool = True,
) -> ActionResolution:
    """Compare one manifest-declared candidate without widening ObjectAction."""

    manifest = get_manifest(candidate_manifest, strict=True)
    if not any(
        rule.resource_kind == resource_kind and rule.action == action
        for rule in manifest.permissions
    ):
        raise ValueError(
            f"Unknown candidate permission {candidate_manifest}:{resource_kind}.{action}"
        )
    attrs = dict(resource_attrs or {})
    attrs["iam_manifest"] = candidate_manifest
    candidate = evaluate_permission(
        db,
        user=user,
        workspace=workspace,
        membership=membership,
        config=config,
        resource_kind=resource_kind,
        action=action,
        resource_attrs=attrs,
        audit_denials=False,
    )
    if config is None:
        config = load_iam_config(db, workspace.id, create=False)
    mode = resolve_mode(
        config,
        resource_kind=resource_kind,
        action=action,
        db=db,
        mode_cache=mode_cache,
    )
    mismatch = bool(legacy_allowed) != candidate.allowed
    effective_allowed = (
        candidate.allowed
        if mode is AuthorizationMode.ENFORCE
        else False
        if mode is AuthorizationMode.INVALID_ENFORCE
        else bool(legacy_allowed)
    )
    resolution = ActionResolution(
        resource_kind=resource_kind,
        action=action,
        mode=mode.value,
        effective_allowed=effective_allowed,
        legacy_allowed=bool(legacy_allowed),
        candidate_allowed=candidate.allowed,
        mismatch=mismatch,
        reason=(
            "authorization_enforcement_attestation_invalid"
            if mode is AuthorizationMode.INVALID_ENFORCE
            else candidate.reason
        ),
        policy_id=candidate.policy_id,
        runtime_revision=str(settings.agentium_image_revision or "").strip().lower(),
        candidate_config_sha256=candidate_config_sha256(config),
        candidate_config_version=(int(config.version) if config is not None else None),
    )
    if mode is AuthorizationMode.SHADOW:
        if audit_shadow_evidence:
            _emit_shadow_evaluation(workspace, user, resolution, attrs)
        if mismatch and audit_shadow_diff:
            _emit_shadow_diff(db, workspace, user, resolution, attrs)
    return resolution


def enforce_action(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
    resource_kind: str,
    action: str,
    legacy_allowed: bool,
    resource_attrs: Optional[dict[str, Any]] = None,
    membership: Optional[WorkspaceMember] = None,
) -> ActionResolution:
    resolution = resolve_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind=resource_kind,
        action=action,
        legacy_allowed=legacy_allowed,
        resource_attrs=resource_attrs,
        membership=membership,
    )
    return _enforce_resolution(resolution)


def enforce_candidate_permission(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
    resource_kind: str,
    action: str,
    legacy_allowed: bool,
    candidate_manifest: str,
    resource_attrs: Optional[dict[str, Any]] = None,
    membership: Optional[WorkspaceMember] = None,
) -> ActionResolution:
    resolution = resolve_candidate_permission(
        db,
        user=user,
        workspace=workspace,
        resource_kind=resource_kind,
        action=action,
        legacy_allowed=legacy_allowed,
        candidate_manifest=candidate_manifest,
        resource_attrs=resource_attrs,
        membership=membership,
    )
    return _enforce_resolution(resolution)


def _enforce_resolution(resolution: ActionResolution) -> ActionResolution:
    if resolution.mode == AuthorizationMode.INVALID_ENFORCE.value:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "AUTHORIZATION_ENFORCEMENT_INVALID",
                "message": "Authorization enforcement is unavailable until its attestation is repaired",
                "mode": resolution.mode,
            },
        )
    if not resolution.effective_allowed:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "WORKSPACE_PERMISSION_DENIED",
                "message": "Workspace permission denied",
                "reason": resolution.reason,
                "policy_id": resolution.policy_id,
                "mode": resolution.mode,
            },
        )
    return resolution


def resolve_manifest_permission(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
    required_permission: str,
    legacy_allowed: bool,
    capability_manifest: Optional[str],
    action_id: str,
    membership: Optional[WorkspaceMember] = None,
    resource_attrs: Optional[dict[str, Any]] = None,
) -> ActionResolution:
    """Resolve one ActionManifest's concrete ``resource.action`` contract.

    Rollout is governed by ``action.execute`` while the candidate decision is
    evaluated against the manifest's declared permission.  This makes the
    previously decorative field effective without globally enabling every
    endpoint that happens to use the same low-level permission.
    """

    if "." not in required_permission:
        raise ValueError("ActionManifest.required_permission must be resource.action")
    resource_kind, action = required_permission.split(".", 1)
    manifest_id = capability_manifest or "agentium_actions"
    manifest = get_manifest(manifest_id, strict=True)
    if not any(
        rule.resource_kind == resource_kind and rule.action == action
        for rule in manifest.permissions
    ):
        raise ValueError(f"Unknown action permission {manifest_id}:{required_permission}")
    attrs = dict(resource_attrs or {})
    attrs.update(
        {
            "iam_manifest": manifest_id,
            "action_id": action_id,
        }
    )
    # Ownership is resource evidence, never a property that this boundary may
    # infer from the caller. Owner-scoped rules therefore fail closed when the
    # caller did not load and pass an owner from the persisted resource.
    candidate = evaluate_permission(
        db,
        user=user,
        workspace=workspace,
        membership=membership,
        resource_kind=resource_kind,
        action=action,
        resource_attrs=attrs,
        audit_denials=False,
    )
    config = load_iam_config(db, workspace.id, create=False)
    mode = resolve_mode(config, resource_kind="action", action="execute", db=db)
    mismatch = bool(legacy_allowed) != candidate.allowed
    resolution = ActionResolution(
        resource_kind="action",
        action="execute",
        mode=mode.value,
        effective_allowed=(
            candidate.allowed
            if mode is AuthorizationMode.ENFORCE
            else False
            if mode is AuthorizationMode.INVALID_ENFORCE
            else bool(legacy_allowed)
        ),
        legacy_allowed=bool(legacy_allowed),
        candidate_allowed=candidate.allowed,
        mismatch=mismatch,
        reason=(
            "authorization_enforcement_attestation_invalid"
            if mode is AuthorizationMode.INVALID_ENFORCE
            else candidate.reason
        ),
        policy_id=candidate.policy_id,
        runtime_revision=str(settings.agentium_image_revision or "").strip().lower(),
        candidate_config_sha256=candidate_config_sha256(config),
        candidate_config_version=(int(config.version) if config is not None else None),
    )
    if mode is AuthorizationMode.SHADOW:
        _emit_shadow_evaluation(
            workspace,
            user,
            resolution,
            attrs,
        )
        if mismatch:
            _emit_shadow_diff(
                db,
                workspace,
                user,
                resolution,
                attrs,
            )
    return resolution


def build_authorization_v2_backfill(
    *,
    mode: str = AuthorizationMode.SHADOW.value,
    policy_version: int = 2,
) -> dict[str, Any]:
    """Return the canonical, idempotent rollout document.

    Callers merge this document under ``capability_overrides``.  It covers
    mutation boundaries first and keeps read paths in compat until their
    object projector has been validated.
    """

    parsed_mode = AuthorizationMode(mode)
    return {
        "policy_version": policy_version,
        "default_mode": AuthorizationMode.COMPAT.value,
        "modes": {
            "capture_session.create": parsed_mode.value,
            "capture_session.read": parsed_mode.value,
            "capture_session.update": parsed_mode.value,
            "capture_session.execute": parsed_mode.value,
            "knowledge_proposal.read": parsed_mode.value,
            "knowledge_proposal.submit_review": parsed_mode.value,
            "knowledge_proposal.review_decide": parsed_mode.value,
            "knowledge_proposal.chat_correct": parsed_mode.value,
            "knowledge_proposal.trigger_ingestion": parsed_mode.value,
            "capability.read": parsed_mode.value,
            "system.read": parsed_mode.value,
            "run.read": parsed_mode.value,
            "run.approve": parsed_mode.value,
            "run.admin": parsed_mode.value,
            "skill_invocation.read": parsed_mode.value,
            # The Skill catalog, distinct from a recorded invocation of it.
            # Governing these here is what lets them ever leave ``compat``: the
            # manifest rule alone only makes the candidate evaluable, and the
            # rollout script refuses to promote an action the document does not
            # own. Adding them cannot move ``candidate_config_sha256`` because
            # that digest excludes ``modes`` by construction, so stored
            # enforcement attestations stay valid.
            "skill.read": parsed_mode.value,
            "skill.admin": parsed_mode.value,
            "system.engine.run": parsed_mode.value,
            "mail_draft.mail.send": parsed_mode.value,
            "decision.read": parsed_mode.value,
            "decision.approve": parsed_mode.value,
            "decision.admin": parsed_mode.value,
            "value_scenario.read": parsed_mode.value,
            "value_scenario.create": parsed_mode.value,
            "value_scenario.simulate": parsed_mode.value,
            "value_scenario.approve": parsed_mode.value,
            "value_scenario.act": parsed_mode.value,
            "value_scenario.measure": parsed_mode.value,
            "knowledge_proposal.publish": parsed_mode.value,
            "capability.admin": parsed_mode.value,
            "system.admin": parsed_mode.value,
            "audit_log.read": parsed_mode.value,
            "control_policy.read": parsed_mode.value,
            "control_policy.admin": parsed_mode.value,
            "adaptive_policy.read": parsed_mode.value,
            "adaptive_policy.admin": parsed_mode.value,
            "action.read": parsed_mode.value,
            "action.execute": parsed_mode.value,
            "binding.view": parsed_mode.value,
            "binding.manage": parsed_mode.value,
            "experience.view": parsed_mode.value,
            "experience.consume": parsed_mode.value,
            "experience.edit": parsed_mode.value,
            "experience.release": parsed_mode.value,
            "experience.deploy": parsed_mode.value,
        },
    }


def merge_authorization_v2_backfill(
    current: Any,
    *,
    mode: str = AuthorizationMode.SHADOW.value,
) -> tuple[dict[str, Any], bool]:
    """Merge the v2 rollout without deleting workspace-specific policy.

    The backfill owns only the canonical keys returned by
    :func:`build_authorization_v2_backfill`. Existing entries for other
    resources, plus future metadata, must survive an idempotent re-run.
    """

    payload = dict(current) if isinstance(current, Mapping) else {}
    desired = build_authorization_v2_backfill(mode=mode)
    existing_raw = payload.get("authorization_v2")
    existing = dict(existing_raw) if isinstance(existing_raw, Mapping) else {}
    existing_modes_raw = existing.get("modes")
    existing_modes = dict(existing_modes_raw) if isinstance(existing_modes_raw, Mapping) else {}
    existing_attestations = existing.get(ATTESTATIONS_KEY, {})
    if not isinstance(existing_attestations, Mapping):
        raise ValueError("authorization_v2.enforcement_attestations must be an object")

    canonical_keys = set(desired["modes"])
    for key in canonical_keys:
        current_mode = existing_modes.get(key)
        if current_mode not in {
            None,
            AuthorizationMode.COMPAT.value,
            AuthorizationMode.SHADOW.value,
            AuthorizationMode.ENFORCE.value,
        }:
            raise ValueError(f"authorization_v2 has an invalid mode for {key}")
        if current_mode == AuthorizationMode.ENFORCE.value:
            errors = _enforcement_attestation_errors(
                config=None,
                policy={**existing, "modes": existing_modes},
                action=key,
                require_runtime_revision=False,
            )
            if errors:
                raise ValueError(
                    f"authorization_v2 enforce state is incoherent for {key}: " + "; ".join(errors)
                )

    for key, raw in existing_attestations.items():
        if key in canonical_keys and existing_modes.get(key) != AuthorizationMode.ENFORCE.value:
            raise ValueError(f"authorization_v2 attestation exists while {key} is not enforce")

    # Backfill advances missing/compat canonical actions into the requested
    # mode.  It never demotes an already-shadowed or attested enforce action.
    for key, desired_mode in desired["modes"].items():
        if existing_modes.get(key) not in {
            AuthorizationMode.SHADOW.value,
            AuthorizationMode.ENFORCE.value,
        }:
            existing_modes[key] = desired_mode
    merged = {
        **existing,
        "policy_version": desired["policy_version"],
        "default_mode": existing.get("default_mode", desired["default_mode"]),
        "modes": existing_modes,
    }
    changed = existing_raw != merged
    payload["authorization_v2"] = merged
    return payload, changed


def _emit_shadow_diff(
    db: DBSession,
    workspace: Workspace,
    user: User,
    resolution: ActionResolution,
    attrs: Mapping[str, Any],
) -> None:
    safe_attrs = _safe_shadow_attrs(attrs)
    emit_audit_event(
        # GET/list requests do not commit their request-scoped session. A
        # dedicated audit session makes the shadow evidence survive request
        # teardown and also records denials that intentionally abort the unit
        # of work.
        db=None,
        workspace_id=workspace.id,
        event_type="iam.shadow.diff",
        actor=user.email or user.username or user.id,
        severity="warning",
        details={
            "origin": "server",
            "resource": {"kind": resolution.resource_kind, **safe_attrs},
            "action": _canonical_action_key(
                resolution.resource_kind,
                resolution.action,
            ),
            "legacy_allowed": resolution.legacy_allowed,
            "candidate_allowed": resolution.candidate_allowed,
            "policy_id": resolution.policy_id,
            "reason": resolution.reason,
            "policy_version": 2,
        },
    )


def _safe_shadow_attrs(attrs: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in attrs.items()
        if key
        in {
            "capability_id",
            "system_id",
            "run_id",
            "skill_invocation_id",
            "decision_id",
            "draft_id",
            "owner_user_id",
            "action_id",
        }
        and value is not None
    }


def _canonical_action_key(resource_kind: str, action: str) -> str:
    """Return the collector/promotion key emitted at every API boundary.

    The decision engine deliberately reasons about a leaf action (``read``,
    ``approve`` or ``engine.run``).  Persisted shadow evidence is a public
    contract shared with the collector and therefore always carries the
    unambiguous ``resource_kind.action`` key.
    """

    prefix = f"{resource_kind}."
    return action if action.startswith(prefix) else f"{prefix}{action}"


def _shadow_counters(resolutions: Iterable[ActionResolution]) -> dict[str, int]:
    rows = list(resolutions)
    return {
        "evaluation_count": len(rows),
        "legacy_allowed": sum(row.legacy_allowed for row in rows),
        "legacy_denied": sum(not row.legacy_allowed for row in rows),
        "candidate_allowed": sum(row.candidate_allowed for row in rows),
        "candidate_denied": sum(not row.candidate_allowed for row in rows),
        "matches": sum(not row.mismatch for row in rows),
        "mismatches": sum(row.mismatch for row in rows),
    }


def _shadow_binding(resolution: ActionResolution) -> dict[str, Any]:
    return {
        "runtime_revision": resolution.runtime_revision,
        "candidate_config_sha256": resolution.candidate_config_sha256,
        "candidate_config_version": resolution.candidate_config_version,
        "configured_mode": resolution.mode,
    }


def _emit_shadow_evaluation(
    workspace: Workspace,
    user: User,
    resolution: ActionResolution,
    attrs: Mapping[str, Any],
) -> None:
    emit_audit_event(
        db=None,
        workspace_id=workspace.id,
        event_type="iam.shadow.evaluation",
        actor=user.email or user.username or user.id,
        details={
            "origin": "server",
            "resource": {
                "kind": resolution.resource_kind,
                **_safe_shadow_attrs(attrs),
            },
            "action": _canonical_action_key(
                resolution.resource_kind,
                resolution.action,
            ),
            **_shadow_counters([resolution]),
            **_shadow_binding(resolution),
            "policy_id": resolution.policy_id,
            "policy_version": 2,
        },
    )


def emit_shadow_diff_summary(
    *,
    workspace: Workspace,
    user: User,
    resource_kind: str,
    action: str,
    resolutions: Iterable[tuple[str, ActionResolution]],
) -> None:
    """Persist one safe observation and, when needed, one diff per collection."""

    shadow = [
        (resource_id, resolution)
        for resource_id, resolution in resolutions
        if resolution.mode == AuthorizationMode.SHADOW.value
    ]
    if not shadow:
        return
    first = shadow[0][1]
    emit_audit_event(
        db=None,
        workspace_id=workspace.id,
        event_type="iam.shadow.evaluation",
        actor=user.email or user.username or user.id,
        details={
            "origin": "server",
            "resource": {
                "kind": resource_kind,
                "sample_ids": [resource_id for resource_id, _ in shadow[:10]],
            },
            "action": _canonical_action_key(resource_kind, action),
            "summary": True,
            **_shadow_counters(resolution for _, resolution in shadow),
            **_shadow_binding(first),
            "policy_id": first.policy_id,
            "policy_version": 2,
        },
    )
    mismatches = [row for row in shadow if row[1].mismatch]
    if not mismatches:
        return
    emit_audit_event(
        db=None,
        workspace_id=workspace.id,
        event_type="iam.shadow.diff",
        actor=user.email or user.username or user.id,
        severity="warning",
        details={
            "origin": "server",
            "resource": {
                "kind": resource_kind,
                "sample_ids": [resource_id for resource_id, _ in mismatches[:10]],
            },
            "action": _canonical_action_key(resource_kind, action),
            "summary": True,
            "mismatch_count": len(mismatches),
            "legacy_allowed_count": sum(
                1 for _, resolution in mismatches if resolution.legacy_allowed
            ),
            "candidate_allowed_count": sum(
                1 for _, resolution in mismatches if resolution.candidate_allowed
            ),
            "policy_id": first.policy_id,
            "policy_version": 2,
        },
    )
