"""Add the SAP write intents table: one row per PR item turned into a PO.

Two approvals of the same purchase-requisition item used to send two
BAPI_PO_CREATE1 calls: the scheduler opens a new gate every tick while an
earlier one is still pending, and nothing linked them. This table is the
idempotency record the write claims before it calls SAP. Its unique key is
the business object (workspace, PR, item), so a second approval meets the
first one's row and is refused unless the first one is a known failure.

Creation only: no existing row is touched, and the downgrade drops the table.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "112_sap_write_intents"
down_revision = "111_freeze_ws_slug_fallbacks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sap_write_intents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("pr_id", sa.String(20), nullable=False),
        sa.Column("pr_item", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("server_id", sa.String(64), nullable=True),
        sa.Column("tool", sa.String(64), nullable=True),
        sa.Column("run_id", sa.String(36), nullable=True),
        sa.Column("decision_id", sa.String(36), nullable=True),
        sa.Column("decided_by", sa.String(255), nullable=True),
        sa.Column("reference", sa.String(10), nullable=True),
        sa.Column("po_number", sa.String(20), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("resolved_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("workspace_id", "pr_id", "pr_item", name="uq_sap_write_intent_pr_item"),
    )
    op.create_index("ix_sap_write_intents_workspace_id", "sap_write_intents", ["workspace_id"])
    op.create_index("ix_sap_write_intents_run_id", "sap_write_intents", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_sap_write_intents_run_id", table_name="sap_write_intents")
    op.drop_index("ix_sap_write_intents_workspace_id", table_name="sap_write_intents")
    op.drop_table("sap_write_intents")
