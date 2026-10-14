"""Operator acceptance of bounded proof bundles, with report-byte verification.

Only a platform operator can attest a producer. Hashes establish integrity, not
trust: accepting evidence is an audited privileged operation, never a workspace
upload that can promote its own connector.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.connector_governance import ConnectorEvidence
from app.services.audit_logger import emit_audit_event
from app.services.connectors.certification import EvidenceBundle, Identifier
from app.services.huggingface.access import is_platform_admin


class EvidenceError(RuntimeError):
    def __init__(self, code, status_code=400):
        self.code, self.status_code = code, status_code
        super().__init__(code)


class ProofReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    suite: Identifier
    status: str = Field(pattern="^(passed|failed|skipped)$")
    code: Identifier
    elapsed_ms: int = Field(ge=0, le=604800000)
    rows: int | None = Field(default=None, ge=0)
    peak_rss_bytes: int | None = Field(default=None, ge=0)
    result_digest: str | None = Field(default=None, pattern="^[a-f0-9]{64}$")


def report_digest(report):
    return hashlib.sha256(
        json.dumps(report.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def accept_evidence(db, *, user, producer, bundle: EvidenceBundle, reports: list[ProofReport]):
    if not is_platform_admin(user):
        raise EvidenceError("PLATFORM_PERMISSION_DENIED", 403)
    if not isinstance(producer, str) or not producer.strip() or len(producer) > 160:
        raise EvidenceError("CONNECTOR_EVIDENCE_PRODUCER_REQUIRED")
    if bundle.payload.completed_at > datetime.now(UTC):
        raise EvidenceError("CONNECTOR_EVIDENCE_FROM_FUTURE")
    supplied = {report_digest(report): report for report in reports}
    expected = {row.evidence_sha256: row for row in bundle.payload.results}
    if (
        len(supplied) != len(reports)
        or supplied.keys() != expected.keys()
        or any(
            report.suite != expected[digest].suite or report.status != expected[digest].status
            for digest, report in supplied.items()
        )
    ):
        raise EvidenceError("CONNECTOR_EVIDENCE_REPORT_MISMATCH")
    existing = db.get(ConnectorEvidence, bundle.sha256)
    if existing:
        if existing.revoked_at:
            raise EvidenceError("CONNECTOR_EVIDENCE_REVOKED", 409)
        return existing
    row = ConnectorEvidence(
        digest=bundle.sha256,
        profile_key=bundle.payload.identity.profile_key,
        identity_digest=bundle.payload.identity.sha256,
        payload=bundle.model_dump(mode="json"),
        reports=[report.model_dump(mode="json") for report in reports],
        accepted_by=user.id,
        producer=producer.strip(),
    )
    db.add(row)
    db.flush()
    if (
        emit_audit_event(
            db=db,
            event_type="connector.evidence_accepted",
            workspace_id=None,
            actor=user.id,
            details={
                "digest": row.digest,
                "profile_key": row.profile_key,
                "producer": row.producer,
            },
        )
        is None
    ):
        db.rollback()
        raise EvidenceError("CONNECTOR_AUDIT_REQUIRED", 503)
    db.commit()
    return row


def revoke_evidence(db, *, user, digest):
    if not is_platform_admin(user):
        raise EvidenceError("PLATFORM_PERMISSION_DENIED", 403)
    row = db.get(ConnectorEvidence, digest)
    if row is None:
        raise EvidenceError("CONNECTOR_EVIDENCE_NOT_FOUND", 404)
    if row.revoked_at is None:
        row.revoked_at, row.revoked_by = datetime.now(UTC).replace(tzinfo=None), user.id
        if (
            emit_audit_event(
                db=db,
                event_type="connector.evidence_revoked",
                workspace_id=None,
                actor=user.id,
                details={"digest": row.digest},
            )
            is None
        ):
            db.rollback()
            raise EvidenceError("CONNECTOR_AUDIT_REQUIRED", 503)
        db.commit()
    return row


def trusted_bundles(db, profile_key):
    return tuple(
        EvidenceBundle.model_validate(row.payload)
        for row in db.query(ConnectorEvidence)
        .filter_by(profile_key=profile_key, revoked_at=None)
        .order_by(ConnectorEvidence.accepted_at.desc())
        .limit(1000)
        .all()
    )
