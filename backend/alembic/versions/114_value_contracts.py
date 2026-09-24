"""Add the value contracts table: the governed value terms of an automation.

ADR 0003 lot 3. An automation's value contract names its owner, indicator,
unit, target, period, convention and source, and becomes visible once the
owner approves it. Each proposal is a new revision; approving one supersedes
the revision it replaces, so the history stays readable.

Creation only: no existing row is touched, and the downgrade drops the table.
The operational objective and the capability value basis stay where they are.

Revision ID: 114_value_contracts
Revises: 113_nawa_studio_appearance
Create Date: 2026-09-24
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "114_value_contracts"
down_revision = "113_nawa_studio_appearance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "value_contracts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("system_id", sa.String(36), sa.ForeignKey("systems.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("indicator", sa.String(40), nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("target", sa.Float(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("convention", sa.JSON(), nullable=False),
        sa.Column("source", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("proposed_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("proposed_at", sa.DateTime(), nullable=False),
        sa.Column("decided_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.UniqueConstraint("system_id", "revision", name="uq_value_contract_revision"),
    )
    op.create_index("ix_value_contracts_workspace_id", "value_contracts", ["workspace_id"])
    op.create_index("ix_value_contracts_system_id", "value_contracts", ["system_id"])


def downgrade() -> None:
    op.drop_index("ix_value_contracts_system_id", table_name="value_contracts")
    op.drop_index("ix_value_contracts_workspace_id", table_name="value_contracts")
    op.drop_table("value_contracts")
