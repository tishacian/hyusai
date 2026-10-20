"""Keep the application creation wizard's progress on the server.

A new table only: no existing row is read, changed or backfilled. Unfinished
wizards from before this revision simply have no saved step.
"""

import sqlalchemy as sa

from alembic import op

revision = "142_experience_wizard_state"
down_revision = "141_event_execution_principal"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "experience_wizard_states",
        sa.Column(
            "experience_id",
            sa.String(36),
            sa.ForeignKey("experiences.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("step >= 1 AND step <= 3", name="ck_experience_wizard_states_step"),
    )
    op.create_index(
        "ix_experience_wizard_states_workspace_id",
        "experience_wizard_states",
        ["workspace_id"],
    )


def downgrade():
    op.drop_index("ix_experience_wizard_states_workspace_id", table_name="experience_wizard_states")
    op.drop_table("experience_wizard_states")
