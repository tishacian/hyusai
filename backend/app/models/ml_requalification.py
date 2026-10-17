"""Runtime requalification attempts: one row per replay of reference predictions.

A qualified, unrevoked row lets exactly one reader runtime load exactly one
artifact whose producer runtime differs. Failed attempts are kept as evidence
and grant nothing. Rows hold package versions and measured gaps, never rows,
predictions or storage locations.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)

from app.db.base import Base

ACTIVE = "verdict = 'qualified' AND revoked_at IS NULL"


class MLRuntimeAttestation(Base):
    __tablename__ = "ml_runtime_attestations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    model_id = Column(String(36), ForeignKey("ml_models.id", ondelete="CASCADE"), nullable=False)
    artifact_fingerprint = Column(String(64), nullable=False)
    producer_runtime = Column(JSON, nullable=False)
    # Exactly ``runtime_versions(family, serialization)`` of the process that
    # loaded and predicted; its digest is what the uniqueness rule indexes.
    reader_runtime = Column(JSON, nullable=False)
    reader_digest = Column(String(64), nullable=False)
    reference_sha256 = Column(String(64), nullable=False)
    rows_compared = Column(Integer, nullable=False, default=0)
    metrics = Column(JSON, nullable=False, default=dict)
    tolerances = Column(JSON, nullable=False, default=dict)
    verdict = Column(String(16), nullable=False)
    error_code = Column(String(64), nullable=True)
    job_id = Column(String(36), nullable=True)
    actor = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    revoked_by = Column(String(64), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "verdict IN ('qualified', 'failed')", name="ck_ml_runtime_attestation_verdict"
        ),
        Index("ix_ml_runtime_attestations_model", "model_id", "created_at"),
        Index("ix_ml_runtime_attestations_workspace", "workspace_id"),
        # At most one active qualified attestation per artifact and reader.
        Index(
            "uq_ml_runtime_attestation_active",
            "model_id",
            "artifact_fingerprint",
            "reader_digest",
            unique=True,
            postgresql_where=text(ACTIVE),
            sqlite_where=text(ACTIVE),
        ),
    )
