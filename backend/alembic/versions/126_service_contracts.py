"""Governed asset versions and service delivery windows.

Revision ID: 126_service_contracts
Revises: 125_retrieval_bench_runs
"""

import sqlalchemy as sa

from alembic import op

revision = "126_service_contracts"
down_revision = "125_retrieval_bench_runs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "asset_versions",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("logical_key", sa.String(length=200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("manifest_key", sa.String(length=500), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("parents_json", sa.JSON(), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('dataset','model','document_set','reference')", name="ck_asset_versions_kind"
        ),
        sa.CheckConstraint("version > 0", name="ck_asset_versions_revision"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "workspace_id", "kind", "logical_key", "digest", name="uq_asset_versions_content"
        ),
        sa.UniqueConstraint(
            "workspace_id", "kind", "logical_key", "version", name="uq_asset_versions_revision"
        ),
        sa.UniqueConstraint("workspace_id", "id", name="uq_asset_versions_tenant_id"),
    )
    op.create_index("ix_asset_versions_workspace_id", "asset_versions", ["workspace_id"])

    op.create_table(
        "asset_qualifications",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("asset_digest", sa.String(length=64), nullable=False),
        sa.Column("policy_digest", sa.String(length=64), nullable=False),
        sa.Column("evidence_digest", sa.String(length=64), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("policy_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_asset_qualification_confidence",
        ),
        sa.CheckConstraint(
            "status IN ('qualified','rejected','review_required','needs_requalification')",
            name="ck_asset_qualification_status",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "asset_id"],
            ["asset_versions.workspace_id", "asset_versions.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "workspace_id", "asset_id", "version", name="uq_asset_qualification_revision"
        ),
        sa.UniqueConstraint("workspace_id", "id", name="uq_asset_qualification_tenant_id"),
    )
    op.create_index("ix_asset_qualifications_asset_id", "asset_qualifications", ["asset_id"])
    op.create_index(
        "ix_asset_qualifications_workspace_id", "asset_qualifications", ["workspace_id"]
    )

    op.create_table(
        "service_contracts",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("system_id", sa.String(length=36), nullable=False),
        sa.Column("logical_key", sa.String(length=200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("definition_json", sa.JSON(), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id", "system_id"],
            ["systems.workspace_id", "systems.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "workspace_id",
            "system_id",
            "logical_key",
            "version",
            name="uq_service_contract_revision",
        ),
        sa.UniqueConstraint("workspace_id", "id", name="uq_service_contract_tenant_id"),
    )
    op.create_index("ix_service_contracts_published_at", "service_contracts", ["published_at"])
    op.create_index("ix_service_contracts_system_id", "service_contracts", ["system_id"])
    op.create_index("ix_service_contracts_workspace_id", "service_contracts", ["workspace_id"])

    op.create_table(
        "service_windows",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("contract_id", sa.String(length=36), nullable=False),
        sa.Column("system_id", sa.String(length=36), nullable=False),
        sa.Column("logical_key", sa.String(length=200), nullable=False),
        sa.Column("period_start", sa.DateTime(), nullable=False),
        sa.Column("period_end", sa.DateTime(), nullable=False),
        sa.Column("deadline_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("fence", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.String(length=64), nullable=True),
        sa.Column("lease_owner", sa.String(length=160), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("cost_used", sa.Float(), nullable=False),
        sa.Column("tokens_used", sa.Integer(), nullable=False),
        sa.Column("seconds_used", sa.Float(), nullable=False),
        sa.Column("candidate_ref", sa.JSON(), nullable=True),
        sa.Column("input_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "attempts >= 0 AND cost_used >= 0 AND tokens_used >= 0 AND seconds_used >= 0",
            name="ck_service_window_budget",
        ),
        sa.CheckConstraint(
            "period_end > period_start AND deadline_at >= period_start",
            name="ck_service_window_period",
        ),
        sa.CheckConstraint(
            "status IN ('pending','running','awaiting_review','failed','missed','delivered')",
            name="ck_service_window_status",
        ),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "contract_id"],
            ["service_contracts.workspace_id", "service_contracts.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "system_id",
            "logical_key",
            "period_start",
            name="uq_service_window_period",
        ),
        sa.UniqueConstraint("workspace_id", "id", name="uq_service_window_tenant_id"),
    )
    op.create_index("ix_service_windows_contract_id", "service_windows", ["contract_id"])
    op.create_index("ix_service_windows_deadline_at", "service_windows", ["deadline_at"])
    op.create_index("ix_service_windows_status", "service_windows", ["status"])
    op.create_index("ix_service_windows_workspace_id", "service_windows", ["workspace_id"])

    op.create_table(
        "service_attempts",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("window_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("fence", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reserved_cost", sa.Float(), nullable=False),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False),
        sa.Column("reserved_seconds", sa.Float(), nullable=False),
        sa.Column("actual_cost", sa.Float(), nullable=True),
        sa.Column("actual_tokens", sa.Integer(), nullable=True),
        sa.Column("actual_seconds", sa.Float(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id", "window_id"],
            ["service_windows.workspace_id", "service_windows.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("window_id", "fence", name="uq_service_attempt_fence"),
    )
    op.create_index("ix_service_attempts_window_id", "service_attempts", ["window_id"])
    op.create_index("ix_service_attempts_workspace_id", "service_attempts", ["workspace_id"])

    op.create_table(
        "delivery_receipts",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("window_id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("asset_digest", sa.String(length=64), nullable=False),
        sa.Column("qualification_id", sa.String(length=36), nullable=False),
        sa.Column("qualification_digest", sa.String(length=64), nullable=False),
        sa.Column("destination", sa.String(length=160), nullable=False),
        sa.Column("decision_id", sa.String(length=36), nullable=False),
        sa.Column("binding_digest", sa.String(length=64), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["decision_id"], ["decisions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "asset_id"],
            ["asset_versions.workspace_id", "asset_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "qualification_id"],
            ["asset_qualifications.workspace_id", "asset_qualifications.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "window_id"],
            ["service_windows.workspace_id", "service_windows.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "window_id", "asset_digest", "destination", name="uq_delivery_receipt_destination"
        ),
    )
    op.create_index("ix_delivery_receipts_published_at", "delivery_receipts", ["published_at"])
    op.create_index("ix_delivery_receipts_window_id", "delivery_receipts", ["window_id"])
    op.create_index("ix_delivery_receipts_workspace_id", "delivery_receipts", ["workspace_id"])

    op.create_table(
        "service_incidents",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("window_id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id", "window_id"],
            ["service_windows.workspace_id", "service_windows.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("window_id", "code", name="uq_service_incident_code"),
    )
    op.create_index("ix_service_incidents_window_id", "service_incidents", ["window_id"])
    op.create_index("ix_service_incidents_workspace_id", "service_incidents", ["workspace_id"])


def downgrade():
    op.drop_table("service_incidents")
    op.drop_table("delivery_receipts")
    op.drop_table("service_attempts")
    op.drop_table("service_windows")
    op.drop_table("service_contracts")
    op.drop_table("asset_qualifications")
    op.drop_table("asset_versions")
