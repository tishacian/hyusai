"""Add the verified runtime binding column workspace-defined Skills need.

Revision ID: 083_workspace_skill_executor
Revises: 082_skill_category

Seeded Skills dispatch through the hardcoded ``_REGISTRY`` in
``skills_registry/wrappers.py``, which a workspace cannot extend. A
workspace-defined Skill instead names one entry of the verified executor table
plus frozen parameters, and that binding has to live on the row.

The column is deliberately left null everywhere on upgrade: a null binding is
not executable, so a pre-existing row cannot become runnable by acquiring the
column. Only the authoring surface writes it, and only after
``validate_executor_binding`` has accepted it.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "083_workspace_skill_executor"
down_revision = "082_skill_category"
branch_labels = None
depends_on = None

COLUMN = "executor"


def upgrade() -> None:
    op.add_column("skills", sa.Column(COLUMN, sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("skills", COLUMN)
