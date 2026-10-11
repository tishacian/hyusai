"""Immutable Hub selections and workspace-scoped access/lifecycle records."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)

from app.db.base import Base


def _id():
    return str(uuid4())


class HFPlatformConfig(Base):
    __tablename__ = "hf_platform_config"
    id = Column(String(36), primary_key=True, default="default")
    connection = Column(JSON, nullable=False, default=dict)
    policy = Column(JSON, nullable=False, default=dict)
    limits = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class HFLicenseAcceptance(Base):
    __tablename__ = "hf_license_acceptances"
    id = Column(String(36), primary_key=True, default=_id)
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    hub_endpoint = Column(String(500), nullable=False)
    kind = Column(String(16), nullable=False)
    repo_id = Column(String(255), nullable=False)
    revision = Column(String(40), nullable=False)
    license_digest = Column(String(64), nullable=False)
    policy_version = Column(String(64), nullable=False)
    license_text = Column(Text, nullable=False, default="")
    accepted_by = Column(String(36), nullable=False)
    accepted_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "hub_endpoint",
            "kind",
            "repo_id",
            "revision",
            "license_digest",
            "policy_version",
            name="uq_hf_license_acceptance",
        ),
    )


class HFLicenseException(Base):
    __tablename__ = "hf_license_exceptions"
    id = Column(String(36), primary_key=True, default=_id)
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    hub_endpoint = Column(String(500), nullable=False)
    kind = Column(String(16), nullable=False)
    repo_id = Column(String(255), nullable=False)
    revision = Column(String(40), nullable=False)
    license_digest = Column(String(64), nullable=False)
    policy_version = Column(String(64), nullable=False)
    license_text = Column(Text, nullable=False, default="")
    reason = Column(Text, nullable=False)
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)


class HubArtifact(Base):
    __tablename__ = "hub_artifacts"
    id = Column(String(36), primary_key=True, default=_id)
    identity_hash = Column(String(64), nullable=False, unique=True)
    hub_endpoint = Column(String(500), nullable=False)
    kind = Column(String(16), nullable=False)
    repo_id = Column(String(255), nullable=False)
    revision = Column(String(40), nullable=False)
    requested_ref = Column(String(255), nullable=False)
    format = Column(String(24), nullable=False)
    variant = Column(String(255), nullable=True)
    selection_digest = Column(String(64), nullable=False)
    files_json = Column(JSON, nullable=False, default=dict)
    selection_json = Column(JSON, nullable=False, default=dict)
    metadata_json = Column(JSON, nullable=False, default=dict)
    manifest_json = Column(JSON, nullable=False, default=dict)
    manifest_key = Column(String(500), nullable=True)
    total_bytes = Column(BigInteger, nullable=False, default=0)
    status = Column(String(24), nullable=False, default="pending", index=True)
    error_code = Column(String(80), nullable=True)
    in_catalogue = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    imported_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    revocation_reason = Column(Text, nullable=True)
    purged_at = Column(DateTime, nullable=True)
    __table_args__ = (
        CheckConstraint("kind IN ('model', 'dataset')", name="ck_hub_artifacts_kind"),
        CheckConstraint(
            "status IN ('pending', 'fetching', 'ready', 'failed', 'revoked')",
            name="ck_hub_artifacts_status",
        ),
        CheckConstraint("total_bytes >= 0", name="ck_hub_artifacts_bytes"),
    )


class HubArtifactGrant(Base):
    __tablename__ = "hub_artifact_grants"
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    artifact_id = Column(
        String(36), ForeignKey("hub_artifacts.id", ondelete="CASCADE"), primary_key=True
    )
    granted_by = Column(String(36), nullable=False)
    granted_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    revoked_at = Column(DateTime, nullable=True)
    revocation_reason = Column(Text, nullable=True)
    license_accepted_by = Column(String(36), nullable=True)
    license_accepted_at = Column(DateTime, nullable=True)
    license_digest = Column(String(64), nullable=False)
    policy_version = Column(String(64), nullable=False)


class HubArtifactUsage(Base):
    __tablename__ = "hub_artifact_usages"
    id = Column(String(36), primary_key=True, default=_id)
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artifact_id = Column(
        String(36), ForeignKey("hub_artifacts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    kind = Column(String(32), nullable=False)
    target_id = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False, default="active")
    details_json = Column(JSON, nullable=False, default=dict)
    lease_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("workspace_id", "kind", "target_id", name="uq_hub_artifact_usage_target"),
    )


class HubImportReservation(Base):
    __tablename__ = "hub_import_reservations"
    job_id = Column(
        String(36), ForeignKey("workspace_jobs.id", ondelete="CASCADE"), primary_key=True
    )
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artifact_id = Column(
        String(36), ForeignKey("hub_artifacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    temporary_bytes = Column(BigInteger, nullable=False, default=0)
    expires_at = Column(DateTime, nullable=False, index=True)
    lease_owner = Column(String(36), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class HubImportRequest(Base):
    """Durable idempotency key: queued input never contains a credential."""

    __tablename__ = "hub_import_requests"
    id = Column(String(36), primary_key=True, default=_id)
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    request_key = Column(String(128), nullable=False)
    request_digest = Column(String(64), nullable=False)
    job_id = Column(String(36), ForeignKey("workspace_jobs.id", ondelete="CASCADE"), nullable=False)
    __table_args__ = (
        UniqueConstraint("workspace_id", "request_key", name="uq_hub_import_request"),
    )
