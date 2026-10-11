"""Auto-onboard workspace evaluation presets — E1.5.4.

Revision ID: 019_eval_default_onboard
Revises: 018_eval_component_analytics
Create Date: 2026-04-25
"""
from __future__ import annotations

import json
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision = "019_eval_default_onboard"
down_revision = "018_eval_component_analytics"
branch_labels = None
depends_on = None


ONBOARD_CONFIG = {
    "enabled": True,
    "composite_min": 70.0,
    "hallucination_max": 0.3,
    "dimension_min": {
        "safety": 80.0,
        "hallucination": 50.0,
    },
    "sample_rate": 1.0,
    "_seeded_by": revision,
}


def upgrade() -> None:
    bind = op.get_bind()
    workspace_ids = [
        row[0]
        for row in bind.execute(sa.text("SELECT id FROM workspaces")).all()
    ]
    if not workspace_ids:
        return

    existing_workspace_ids = {
        row[0]
        for row in bind.execute(
            sa.text(
                """
                SELECT workspace_id
                FROM evaluation_presets
                WHERE scope = 'workspace'
                  AND workspace_id IS NOT NULL
                """
            )
        ).all()
    }

    insert_stmt = sa.text(
        """
        INSERT INTO evaluation_presets
            (id, name, scope, scope_id, workspace_id, config, is_default, created_at, updated_at)
        VALUES
            (:id, :name, 'workspace', NULL, :workspace_id, CAST(:config AS JSON), TRUE, now(), now())
        """
    )
    for workspace_id in workspace_ids:
        if workspace_id in existing_workspace_ids:
            continue
        bind.execute(
            insert_stmt,
            {
                "id": str(uuid4()),
                "name": "Agentium default evaluation loop",
                "workspace_id": workspace_id,
                "config": json.dumps(ONBOARD_CONFIG),
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            DELETE FROM evaluation_presets
            WHERE scope = 'workspace'
              AND name = 'Agentium default evaluation loop'
              AND config ->> '_seeded_by' = :revision
            """
        ),
        {"revision": revision},
    )
