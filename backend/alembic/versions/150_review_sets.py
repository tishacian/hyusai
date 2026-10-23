"""Review sets, items and decisions (Experience Lot 10).

Additive only: three new tables, nothing existing is rewritten.
"""

import sqlalchemy as sa

from alembic import op

revision = "150_review_sets"
down_revision = "149_remote_runners"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "review_sets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("namespace", sa.String(80), nullable=False),
        sa.Column("group_key", sa.String(200), nullable=False),
        sa.Column("group_labels", sa.JSON(), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("source", sa.JSON(), nullable=False),
        sa.Column("taxonomy", sa.JSON(), nullable=False),
        sa.Column("policy", sa.JSON(), nullable=False),
        sa.Column("reviewers", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("decided_count", sa.Integer(), nullable=False),
        sa.Column("deadline_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("event_emitted_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('open','closed')", name="ck_review_sets_status"),
    )
    op.create_index("ix_review_sets_workspace_id", "review_sets", ["workspace_id"])
    op.create_index("ix_review_sets_status", "review_sets", ["status"])
    op.create_table(
        "review_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "set_id",
            sa.String(36),
            sa.ForeignKey("review_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("item_ref", sa.String(200), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("tier", sa.String(40), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("subject", sa.JSON(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("claimed_by", sa.String(36), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("worst_severity", sa.String(40), nullable=True),
        sa.Column("categories", sa.JSON(), nullable=False),
        sa.Column("decided_by", sa.String(36), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.UniqueConstraint("set_id", "item_ref", name="uq_review_items_set_ref"),
        sa.CheckConstraint(
            "status IN ('pending','approve','correct','reject')", name="ck_review_items_status"
        ),
    )
    op.create_index("ix_review_items_set_id", "review_items", ["set_id"])
    op.create_index("ix_review_items_status", "review_items", ["status"])
    op.create_table(
        "review_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "item_id",
            sa.String(36),
            sa.ForeignKey("review_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("set_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("annotations", sa.JSON(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("decided_by", sa.String(36), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("item_id", "revision", name="uq_review_decisions_item_revision"),
        sa.CheckConstraint(
            "decision IN ('approve','correct','reject')", name="ck_review_decisions_decision"
        ),
    )
    op.create_index("ix_review_decisions_item_id", "review_decisions", ["item_id"])
    op.create_index("ix_review_decisions_set_id", "review_decisions", ["set_id"])


def downgrade():
    op.drop_index("ix_review_decisions_set_id", table_name="review_decisions")
    op.drop_index("ix_review_decisions_item_id", table_name="review_decisions")
    op.drop_table("review_decisions")
    op.drop_index("ix_review_items_status", table_name="review_items")
    op.drop_index("ix_review_items_set_id", table_name="review_items")
    op.drop_table("review_items")
    op.drop_index("ix_review_sets_status", table_name="review_sets")
    op.drop_index("ix_review_sets_workspace_id", table_name="review_sets")
    op.drop_table("review_sets")
