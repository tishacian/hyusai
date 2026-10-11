"""Retain immutable BRD-to-System proposals before application."""
from alembic import op
import sqlalchemy as sa

revision = "107_brd_proposals"
down_revision = "106_brd_documents"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("brd_proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("brd_documents.id"), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_key", sa.String(100), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("proposal", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("system_id", sa.String(36), sa.ForeignKey("systems.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("workspace_id", "created_by_user_id", "request_key", name="uq_brd_proposal_request"))


def downgrade():
    op.drop_table("brd_proposals")
