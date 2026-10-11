"""Add private, workspace-scoped adoption preferences to memberships."""
from alembic import op
import sqlalchemy as sa

revision = "101_member_experience"
down_revision = "100_capability_value_basis"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("workspace_members", sa.Column("experience_progress", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("workspace_members", "experience_progress")
