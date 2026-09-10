"""Deduplicate assistant HTTP requests across retries and workers."""
from alembic import op
import sqlalchemy as sa

revision = "102_assistant_requests"
down_revision = "101_member_experience"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "assistant_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("response", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "workspace_id", "user_id", "request_id", name="uq_assistant_request_caller"
        ),
    )


def downgrade():
    op.drop_table("assistant_requests")
