"""Retain BRD originals and their server-side extraction."""
from alembic import op
import sqlalchemy as sa

revision = "106_brd_documents"
down_revision = "105_evaluation_corrections"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "brd_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(1024), nullable=False),
        sa.Column("extraction", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("workspace_id", "created_by_user_id", "sha256", name="uq_brd_document_upload"),
    )


def downgrade():
    op.drop_table("brd_documents")
