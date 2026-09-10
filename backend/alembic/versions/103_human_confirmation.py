"""Record explicit authenticated human decisions without relabelling history."""
from alembic import op
import sqlalchemy as sa

revision = "103_human_confirmation"
down_revision = "102_assistant_requests"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("decisions", sa.Column("human_confirmed_by", sa.String(36), nullable=True))
    op.add_column("decisions", sa.Column("human_confirmed_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("decisions", "human_confirmed_at")
    op.drop_column("decisions", "human_confirmed_by")
