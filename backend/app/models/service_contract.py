"""Immutable asset evidence and durable service delivery windows."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    event,
    inspect,
)

from app.db.base import Base


def _id():
    return str(uuid4())


class AssetVersion(Base):
    __tablename__ = "asset_versions"
    id = Column(String(36), primary_key=True, default=_id)
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind = Column(String(24), nullable=False)
    logical_key = Column(String(200), nullable=False)
    version = Column(Integer, nullable=False)
    digest = Column(String(64), nullable=False)
    manifest_key = Column(String(500), nullable=False)
    manifest_json = Column(JSON, nullable=False)
    parents_json = Column(JSON, nullable=False, default=list)
    run_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_asset_versions_tenant_id"),
        UniqueConstraint(
            "workspace_id", "kind", "logical_key", "version", name="uq_asset_versions_revision"
        ),
        UniqueConstraint(
            "workspace_id", "kind", "logical_key", "digest", name="uq_asset_versions_content"
        ),
        CheckConstraint(
            "kind IN ('dataset','model','document_set','reference')", name="ck_asset_versions_kind"
        ),
        CheckConstraint("version > 0", name="ck_asset_versions_revision"),
    )


class AssetQualification(Base):
    __tablename__ = "asset_qualifications"
    id = Column(String(36), primary_key=True, default=_id)
    workspace_id = Column(String(36), nullable=False, index=True)
    asset_id = Column(String(36), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    asset_digest = Column(String(64), nullable=False)
    policy_digest = Column(String(64), nullable=False)
    evidence_digest = Column(String(64), nullable=False)
    digest = Column(String(64), nullable=False)
    status = Column(String(24), nullable=False)
    policy_json = Column(JSON, nullable=False)
    evidence_json = Column(JSON, nullable=False)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "asset_id"],
            ["asset_versions.workspace_id", "asset_versions.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workspace_id", "asset_id", "version", name="uq_asset_qualification_revision"
        ),
        UniqueConstraint("workspace_id", "id", name="uq_asset_qualification_tenant_id"),
        CheckConstraint(
            "status IN ('qualified','rejected','review_required','needs_requalification')",
            name="ck_asset_qualification_status",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_asset_qualification_confidence",
        ),
    )


class ServiceContract(Base):
    __tablename__ = "service_contracts"
    id = Column(String(36), primary_key=True, default=_id)
    workspace_id = Column(String(36), nullable=False, index=True)
    system_id = Column(String(36), nullable=False, index=True)
    logical_key = Column(String(200), nullable=False, default="default")
    version = Column(Integer, nullable=False)
    owner_user_id = Column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    definition_json = Column(JSON, nullable=False)
    digest = Column(String(64), nullable=False)
    created_by = Column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    published_at = Column(DateTime, nullable=True, index=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "system_id"],
            ["systems.workspace_id", "systems.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_service_contract_tenant_id"),
        UniqueConstraint(
            "workspace_id",
            "system_id",
            "logical_key",
            "version",
            name="uq_service_contract_revision",
        ),
    )


class ServiceWindow(Base):
    __tablename__ = "service_windows"
    id = Column(String(36), primary_key=True, default=_id)
    workspace_id = Column(String(36), nullable=False, index=True)
    contract_id = Column(String(36), nullable=False, index=True)
    system_id = Column(String(36), ForeignKey("systems.id", ondelete="CASCADE"), nullable=False)
    logical_key = Column(String(200), nullable=False)
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    deadline_at = Column(DateTime, nullable=False, index=True)
    status = Column(String(24), nullable=False, default="pending", index=True)
    fence = Column(Integer, nullable=False, default=0)
    lease_token = Column(String(64), nullable=True)
    lease_owner = Column(String(160), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    cost_used = Column(Float, nullable=False, default=0)
    tokens_used = Column(Integer, nullable=False, default=0)
    seconds_used = Column(Float, nullable=False, default=0)
    candidate_ref = Column(JSON, nullable=True)
    input_snapshot_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "contract_id"],
            ["service_contracts.workspace_id", "service_contracts.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_service_window_tenant_id"),
        UniqueConstraint(
            "workspace_id",
            "system_id",
            "logical_key",
            "period_start",
            name="uq_service_window_period",
        ),
        CheckConstraint(
            "status IN ('pending','running','awaiting_review','failed','missed','delivered')",
            name="ck_service_window_status",
        ),
        CheckConstraint(
            "attempts >= 0 AND cost_used >= 0 AND tokens_used >= 0 AND seconds_used >= 0",
            name="ck_service_window_budget",
        ),
        CheckConstraint(
            "period_end > period_start AND deadline_at >= period_start",
            name="ck_service_window_period",
        ),
    )


class ServiceAttempt(Base):
    __tablename__ = "service_attempts"
    id = Column(String(36), primary_key=True, default=_id)
    workspace_id = Column(String(36), nullable=False, index=True)
    window_id = Column(String(36), nullable=False, index=True)
    run_id = Column(String(36), nullable=True)
    fence = Column(Integer, nullable=False)
    lease_token = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="running")
    reserved_cost = Column(Float, nullable=False, default=0)
    reserved_tokens = Column(Integer, nullable=False, default=0)
    reserved_seconds = Column(Float, nullable=False, default=0)
    actual_cost = Column(Float, nullable=True)
    actual_tokens = Column(Integer, nullable=True)
    actual_seconds = Column(Float, nullable=True)
    error_code = Column(String(80), nullable=True)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "window_id"],
            ["service_windows.workspace_id", "service_windows.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("window_id", "fence", name="uq_service_attempt_fence"),
    )


class DeliveryReceipt(Base):
    __tablename__ = "delivery_receipts"
    id = Column(String(36), primary_key=True, default=_id)
    workspace_id = Column(String(36), nullable=False, index=True)
    window_id = Column(String(36), nullable=False, index=True)
    asset_id = Column(String(36), nullable=False)
    asset_digest = Column(String(64), nullable=False)
    qualification_id = Column(String(36), nullable=False)
    qualification_digest = Column(String(64), nullable=False)
    destination = Column(String(160), nullable=False)
    decision_id = Column(
        String(36), ForeignKey("decisions.id", ondelete="RESTRICT"), nullable=False
    )
    binding_digest = Column(String(64), nullable=False)
    published_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "window_id"],
            ["service_windows.workspace_id", "service_windows.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "asset_id"],
            ["asset_versions.workspace_id", "asset_versions.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "qualification_id"],
            ["asset_qualifications.workspace_id", "asset_qualifications.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "window_id", "asset_digest", "destination", name="uq_delivery_receipt_destination"
        ),
    )


class ServiceIncident(Base):
    __tablename__ = "service_incidents"
    id = Column(String(36), primary_key=True, default=_id)
    workspace_id = Column(String(36), nullable=False, index=True)
    window_id = Column(String(36), nullable=False, index=True)
    owner_user_id = Column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    code = Column(String(80), nullable=False)
    resolved = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "window_id"],
            ["service_windows.workspace_id", "service_windows.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("window_id", "code", name="uq_service_incident_code"),
    )


@event.listens_for(AssetVersion, "before_update")
@event.listens_for(AssetQualification, "before_update")
@event.listens_for(DeliveryReceipt, "before_update")
def _immutable_record(mapper, connection, target):
    if any(attribute.history.has_changes() for attribute in inspect(target).attrs):
        raise ValueError("IMMUTABLE_GOVERNED_RECORD")


@event.listens_for(ServiceContract, "before_update")
def _immutable_contract(mapper, connection, target):
    changed = {
        attribute.key for attribute in inspect(target).attrs if attribute.history.has_changes()
    }
    if changed - {"published_at"} or (
        "published_at" in changed
        and inspect(target).attrs.published_at.history.deleted
        and inspect(target).attrs.published_at.history.deleted[0] is not None
    ):
        raise ValueError("IMMUTABLE_SERVICE_CONTRACT")
