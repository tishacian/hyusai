"""Align legacy default model rows with GPT-5.

Revision ID: 038_default_model_gpt5
Revises: 037_chat_sessions_workspace_jobs
Create Date: 2026-06-03
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "038_default_model_gpt5"
down_revision = "037_chat_sessions_workspace_jobs"
branch_labels = None
depends_on = None


_LEGACY_DEFAULTS = ("", "gpt-4o", "gpt-4o-mini", "deepseek-r1:14b")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "app_settings" in tables:
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("app_settings") as batch:
                batch.alter_column(
                    "default_model",
                    existing_type=sa.String(length=100),
                    server_default="gpt-5",
                )
        else:
            op.alter_column(
                "app_settings",
                "default_model",
                existing_type=sa.String(length=100),
                server_default="gpt-5",
            )
        bind.execute(
            sa.text(
                """
                UPDATE app_settings
                   SET default_model = 'gpt-5'
                 WHERE default_model IS NULL
                    OR lower(trim(default_model)) IN :legacy_defaults
                """
            ).bindparams(sa.bindparam("legacy_defaults", expanding=True)),
            {"legacy_defaults": _LEGACY_DEFAULTS},
        )

    if "rag_presets" in tables:
        dialect = bind.dialect.name
        if dialect == "postgresql":
            bind.execute(
                sa.text(
                    """
                    UPDATE rag_presets
                       SET config = jsonb_set(
                            COALESCE(config::jsonb, '{}'::jsonb),
                            '{defaultModel}',
                            '"gpt-5"'::jsonb,
                            true
                       )::json
                     WHERE lower(trim(COALESCE(config::jsonb ->> 'defaultModel', ''))) IN :legacy_defaults
                    """
                ).bindparams(sa.bindparam("legacy_defaults", expanding=True)),
                {"legacy_defaults": _LEGACY_DEFAULTS},
            )
        elif dialect == "sqlite":
            bind.execute(
                sa.text(
                    """
                    UPDATE rag_presets
                       SET config = json_set(COALESCE(config, '{}'), '$.defaultModel', 'gpt-5')
                     WHERE lower(trim(COALESCE(json_extract(config, '$.defaultModel'), ''))) IN :legacy_defaults
                    """
                ).bindparams(sa.bindparam("legacy_defaults", expanding=True)),
                {"legacy_defaults": _LEGACY_DEFAULTS},
            )
        elif dialect in {"mysql", "mariadb"}:
            bind.execute(
                sa.text(
                    """
                    UPDATE rag_presets
                       SET config = JSON_SET(COALESCE(config, JSON_OBJECT()), '$.defaultModel', 'gpt-5')
                     WHERE lower(trim(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(config, '$.defaultModel')), ''))) IN :legacy_defaults
                    """
                ).bindparams(sa.bindparam("legacy_defaults", expanding=True)),
                {"legacy_defaults": _LEGACY_DEFAULTS},
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "app_settings" in set(inspector.get_table_names()):
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("app_settings") as batch:
                batch.alter_column(
                    "default_model",
                    existing_type=sa.String(length=100),
                    server_default="gpt-4o",
                )
        else:
            op.alter_column(
                "app_settings",
                "default_model",
                existing_type=sa.String(length=100),
                server_default="gpt-4o",
            )
