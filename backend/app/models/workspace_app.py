"""Authoritative Workspace App installation and operation receipts."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)

from app.db.base import Base


def _enum_check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class WorkspaceAppInstallation(Base):
    """Current lifecycle state for one app identity in one workspace."""

    __tablename__ = "workspace_app_installations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    app_id = Column(String(120), nullable=False, index=True)
    version = Column(String(40), nullable=True)
    manifest_digest = Column(String(64), nullable=True)
    state = Column(String(24), nullable=False, default="uninstalled", index=True)
    configuration = Column(JSON, nullable=False, default=dict)
    revision = Column(Integer, nullable=False, default=0)
    installed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    updated_by = Column(String(255), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "app_id",
            name="uq_workspace_app_installations_workspace_app",
        ),
        UniqueConstraint(
            "id",
            "workspace_id",
            name="uq_workspace_app_installations_id_workspace",
        ),
        CheckConstraint(
            _enum_check("state", ("installed", "uninstalled")),
            name="ck_workspace_app_installations_state",
        ),
        CheckConstraint(
            "(state = 'installed' AND version IS NOT NULL "
            "AND manifest_digest IS NOT NULL) OR "
            "(state = 'uninstalled' AND version IS NULL "
            "AND manifest_digest IS NULL)",
            name="ck_workspace_app_installations_materialized_state",
        ),
        CheckConstraint(
            "revision >= 0",
            name="ck_workspace_app_installations_revision",
        ),
    )


class WorkspaceAppOperation(Base):
    """Immutable, workspace-scoped idempotency receipt for a lifecycle change."""

    __tablename__ = "workspace_app_operations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    installation_id = Column(String(36), nullable=False, index=True)
    app_id = Column(String(120), nullable=False, index=True)
    idempotency_key = Column(String(160), nullable=False)
    request_sha256 = Column(String(64), nullable=False)
    operation = Column(String(24), nullable=False, index=True)
    from_version = Column(String(40), nullable=True)
    to_version = Column(String(40), nullable=True)
    manifest_digest = Column(String(64), nullable=False)
    plan_sha256 = Column(String(64), nullable=False)
    lifecycle_phase = Column(String(32), nullable=False, default="normal")
    steps_sha256 = Column(String(64), nullable=False)
    compensation = Column(JSON, nullable=False, default=dict)
    before_state = Column(JSON, nullable=False)
    after_state = Column(JSON, nullable=False)
    actor = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["installation_id", "workspace_id"],
            ["workspace_app_installations.id", "workspace_app_installations.workspace_id"],
            name="fk_workspace_app_operations_installation_tenant",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_workspace_app_operations_workspace_key",
        ),
        UniqueConstraint(
            "id",
            "workspace_id",
            name="uq_workspace_app_operations_id_workspace",
        ),
        CheckConstraint(
            _enum_check("operation", ("install", "upgrade", "rollback", "uninstall")),
            name="ck_workspace_app_operations_operation",
        ),
        CheckConstraint(
            _enum_check(
                "lifecycle_phase",
                ("normal", "legacy_adoption", "legacy_unorchestrated"),
            ),
            name="ck_workspace_app_operations_lifecycle_phase",
        ),
    )


class WorkspaceAppLifecycleStepReceipt(Base):
    """Immutable proof that one closed lifecycle executor handled one step."""

    __tablename__ = "workspace_app_lifecycle_step_receipts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    operation_id = Column(String(36), nullable=False, index=True)
    installation_id = Column(String(36), nullable=False, index=True)
    app_id = Column(String(120), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    manifest_role = Column(String(16), nullable=False)
    manifest_digest = Column(String(64), nullable=False)
    step_id = Column(String(160), nullable=False)
    step_sha256 = Column(String(64), nullable=False)
    phase = Column(String(32), nullable=False)
    executor = Column(String(80), nullable=False)
    outcome = Column(String(24), nullable=False)
    reversibility = Column(String(80), nullable=False)
    compensation = Column(JSON, nullable=False, default=dict)
    evidence_sha256 = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["operation_id", "workspace_id"],
            ["workspace_app_operations.id", "workspace_app_operations.workspace_id"],
            name="fk_workspace_app_step_receipts_operation_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["installation_id", "workspace_id"],
            ["workspace_app_installations.id", "workspace_app_installations.workspace_id"],
            name="fk_workspace_app_step_receipts_installation_tenant",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "operation_id",
            "position",
            name="uq_workspace_app_step_receipts_operation_position",
        ),
        CheckConstraint("position >= 0", name="ck_workspace_app_step_receipts_position"),
        CheckConstraint(
            _enum_check("manifest_role", ("source", "target")),
            name="ck_workspace_app_step_receipts_manifest_role",
        ),
        CheckConstraint(
            _enum_check("outcome", ("verified", "executed", "compensated")),
            name="ck_workspace_app_step_receipts_outcome",
        ),
    )
