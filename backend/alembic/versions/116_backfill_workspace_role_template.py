"""Backfill workspace_members.role_template from legacy role.

Idempotent fill for rows where role_template is NULL. Rights stay the same:
member → workspace_contributor, admin → workspace_admin, owner → workspace_owner.

Revision ID: 116_backfill_workspace_role_template
Revises: 115_rpa_smtp_reencrypt
Create Date: 2026-09-28
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "116_backfill_workspace_role_template"
down_revision = "115_rpa_smtp_reencrypt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    null_before = bind.execute(
        sa.text("SELECT COUNT(*) FROM workspace_members WHERE role_template IS NULL")
    ).scalar_one()
    bind.execute(
        sa.text(
            """
            UPDATE workspace_members
            SET role_template = CASE role
                WHEN 'owner' THEN 'workspace_owner'
                WHEN 'admin' THEN 'workspace_admin'
                ELSE 'workspace_contributor'
            END
            WHERE role_template IS NULL
            """
        )
    )
    null_after = bind.execute(
        sa.text("SELECT COUNT(*) FROM workspace_members WHERE role_template IS NULL")
    ).scalar_one()
    if null_after != 0:
        raise RuntimeError(
            f"role_template backfill left {null_after} NULL rows (had {null_before})"
        )


def downgrade() -> None:
    # Keep filled templates; clearing them would drop IAM precision.
    pass
