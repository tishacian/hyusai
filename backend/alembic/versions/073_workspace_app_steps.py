"""Persist ordered Workspace App lifecycle step receipts.

Revision ID: 073_workspace_app_steps
Revises: 072_value_measurement_eval

The migration is additive. Existing lifecycle operations are labelled
``legacy_unorchestrated`` honestly; no migration or backfill execution is
reconstructed after the fact.
"""
from __future__ import annotations

import hashlib
import json

import sqlalchemy as sa

from alembic import op

revision = "073_workspace_app_steps"
down_revision = "072_value_measurement_eval"
branch_labels = None
depends_on = None


def _enum_check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _sha256(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def upgrade() -> None:
    op.add_column(
        "workspace_app_operations",
        sa.Column("lifecycle_phase", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "workspace_app_operations",
        sa.Column("steps_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "workspace_app_operations",
        sa.Column("compensation", sa.JSON(), nullable=True),
    )
    operations = sa.table(
        "workspace_app_operations",
        sa.column("lifecycle_phase", sa.String(length=32)),
        sa.column("steps_sha256", sa.String(length=64)),
        sa.column("compensation", sa.JSON()),
    )
    op.get_bind().execute(
        operations.update().values(
            lifecycle_phase="legacy_unorchestrated",
            steps_sha256=_sha256({"steps": []}),
            compensation={
                "failure": "database_transaction_rollback",
                "post_commit": "legacy_unorchestrated",
            },
        )
    )
    with op.batch_alter_table("workspace_app_operations") as batch:
        batch.alter_column(
            "lifecycle_phase",
            existing_type=sa.String(length=32),
            nullable=False,
        )
        batch.alter_column(
            "steps_sha256",
            existing_type=sa.String(length=64),
            nullable=False,
        )
        batch.alter_column(
            "compensation",
            existing_type=sa.JSON(),
            nullable=False,
        )
        batch.create_unique_constraint(
            "uq_workspace_app_operations_id_workspace",
            ["id", "workspace_id"],
        )
        batch.create_check_constraint(
            "ck_workspace_app_operations_lifecycle_phase",
            _enum_check(
                "lifecycle_phase",
                ("normal", "legacy_adoption", "legacy_unorchestrated"),
            ),
        )

    op.create_table(
        "workspace_app_lifecycle_step_receipts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("installation_id", sa.String(length=36), nullable=False),
        sa.Column("app_id", sa.String(length=120), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("manifest_role", sa.String(length=16), nullable=False),
        sa.Column("manifest_digest", sa.String(length=64), nullable=False),
        sa.Column("step_id", sa.String(length=160), nullable=False),
        sa.Column("step_sha256", sa.String(length=64), nullable=False),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column("executor", sa.String(length=80), nullable=False),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("reversibility", sa.String(length=80), nullable=False),
        sa.Column("compensation", sa.JSON(), nullable=False),
        sa.Column("evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "position >= 0",
            name="ck_workspace_app_step_receipts_position",
        ),
        sa.CheckConstraint(
            _enum_check("manifest_role", ("source", "target")),
            name="ck_workspace_app_step_receipts_manifest_role",
        ),
        sa.CheckConstraint(
            _enum_check("outcome", ("verified", "executed", "compensated")),
            name="ck_workspace_app_step_receipts_outcome",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id", "workspace_id"],
            ["workspace_app_operations.id", "workspace_app_operations.workspace_id"],
            name="fk_workspace_app_step_receipts_operation_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["installation_id", "workspace_id"],
            ["workspace_app_installations.id", "workspace_app_installations.workspace_id"],
            name="fk_workspace_app_step_receipts_installation_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "operation_id",
            "position",
            name="uq_workspace_app_step_receipts_operation_position",
        ),
    )
    for column in (
        "workspace_id",
        "operation_id",
        "installation_id",
        "app_id",
        "created_at",
    ):
        op.create_index(
            f"ix_workspace_app_lifecycle_step_receipts_{column}",
            "workspace_app_lifecycle_step_receipts",
            [column],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    receipts = sa.Table(
        "workspace_app_lifecycle_step_receipts",
        metadata,
        autoload_with=bind,
    )
    count = int(
        bind.execute(sa.select(sa.func.count()).select_from(receipts)).scalar_one()
    )
    if count:
        raise RuntimeError(
            "Refusing to downgrade Workspace App lifecycle step receipts "
            f"containing {count} rows"
        )
    op.drop_table("workspace_app_lifecycle_step_receipts")
    with op.batch_alter_table("workspace_app_operations") as batch:
        batch.drop_constraint(
            "ck_workspace_app_operations_lifecycle_phase",
            type_="check",
        )
        batch.drop_constraint(
            "uq_workspace_app_operations_id_workspace",
            type_="unique",
        )
        batch.drop_column("compensation")
        batch.drop_column("steps_sha256")
        batch.drop_column("lifecycle_phase")
