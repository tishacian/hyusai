"""Attach the data plane to the concepts the platform is made of.

A dataset or a model produced by a Flow was only related to its run by an
unconstrained ``run_id``, and a published model named its Skill by slug. That
left ``tabular_datasets`` and ``ml_models`` as a plane beside the mental
model (System → Flow → Run → Skill) rather than inside it: nothing could join
a System to what its runs produced, and a Skill removed from the registry
left cards still claiming to be published.

Additive only. ``system_id`` is backfilled from the run that produced the
row; ``published_skill_id`` from the Skill whose slug the row carried. Rows
whose run or Skill is gone stay NULL — a NULL is the truth about them.

Revision ID: 099_data_plane_attached
Revises: 098_ml_predictions
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "099_data_plane_attached"
down_revision = "098_ml_predictions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tabular_datasets",
        sa.Column(
            "system_id",
            sa.String(36),
            sa.ForeignKey(
                "systems.id",
                ondelete="SET NULL",
                name="fk_tabular_datasets_system_id_systems",
            ),
            nullable=True,
        ),
    )
    op.create_index("ix_tabular_datasets_system_id", "tabular_datasets", ["system_id"])

    op.add_column(
        "ml_models",
        sa.Column(
            "system_id",
            sa.String(36),
            sa.ForeignKey(
                "systems.id",
                ondelete="SET NULL",
                name="fk_ml_models_system_id_systems",
            ),
            nullable=True,
        ),
    )
    op.create_index("ix_ml_models_system_id", "ml_models", ["system_id"])

    op.add_column(
        "ml_models",
        sa.Column(
            "published_skill_id",
            sa.String(36),
            sa.ForeignKey(
                "skills.id",
                ondelete="SET NULL",
                name="fk_ml_models_published_skill_id_skills",
            ),
            nullable=True,
        ),
    )
    op.create_index("ix_ml_models_published_skill_id", "ml_models", ["published_skill_id"])

    # Backfill from what the rows already said, through the run and the slug.
    op.execute(
        """
        UPDATE tabular_datasets AS d
        SET system_id = r.system_id
        FROM runs AS r
        WHERE d.run_id = r.id AND r.system_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE ml_models AS m
        SET system_id = r.system_id
        FROM runs AS r
        WHERE m.run_id = r.id AND r.system_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE ml_models AS m
        SET published_skill_id = s.id
        FROM skills AS s
        WHERE m.published_skill_slug IS NOT NULL
          AND s.slug = m.published_skill_slug
          AND (s.workspace_id IS NULL OR s.workspace_id = m.workspace_id)
        """
    )


def downgrade() -> None:
    op.drop_index("ix_ml_models_published_skill_id", table_name="ml_models")
    op.drop_constraint(
        "fk_ml_models_published_skill_id_skills", "ml_models", type_="foreignkey"
    )
    op.drop_column("ml_models", "published_skill_id")
    op.drop_index("ix_ml_models_system_id", table_name="ml_models")
    op.drop_constraint("fk_ml_models_system_id_systems", "ml_models", type_="foreignkey")
    op.drop_column("ml_models", "system_id")
    op.drop_index("ix_tabular_datasets_system_id", table_name="tabular_datasets")
    op.drop_constraint(
        "fk_tabular_datasets_system_id_systems", "tabular_datasets", type_="foreignkey"
    )
    op.drop_column("tabular_datasets", "system_id")
