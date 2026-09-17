"""Add a policy snapshot to the existing versioned Flow draft."""
from alembic import op
import sqlalchemy as sa

revision = "108_flow_draft_control_policy"
down_revision = "107_brd_proposals"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("system_flow_drafts", sa.Column("control_policy_snapshot", sa.JSON(), nullable=True))


def downgrade():
    # Downgrade must not discard authored mandates. Roll back the application
    # to a compatible image while retaining this additive column.
    if op.get_bind().execute(sa.text(
        "SELECT 1 FROM system_flow_drafts WHERE control_policy_snapshot IS NOT NULL LIMIT 1"
    )).first():
        raise RuntimeError("Cannot drop authored mandate snapshots; keep the additive schema.")
    op.drop_column("system_flow_drafts", "control_policy_snapshot")
