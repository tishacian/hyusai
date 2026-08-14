"""SystemBinding table and optional NAWA password-reset seed.

Revision ID: 086_system_bindings
Revises: 085_nawa_brand_light_emblem

Additive. The table is empty unless a workspace already has the NAWA
Password Reset System with a published Flow version; that seed is skipped
when either is missing so a fresh install without the demo tenant is fine.
"""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "086_system_bindings"
down_revision = "085_nawa_brand_light_emblem"
branch_labels = None
depends_on = None

NAWA_SLUG = "nawa"
SYSTEM_NAME = "Password Reset"
SEED_ORIGIN_065 = "065_nawa_itsd"
BINDING_KEY = "nawa.password_reset"
SEED_ORIGIN = "086_system_bindings"


def _enum_check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return deepcopy(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def upgrade() -> None:
    op.create_table(
        "system_bindings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("binding_key", sa.String(length=120), nullable=False),
        sa.Column("system_id", sa.String(length=36), nullable=False),
        sa.Column("published_flow_version_id", sa.String(length=36), nullable=False),
        sa.Column("flow_sha256", sa.String(length=64), nullable=False),
        sa.Column("ingress_id", sa.String(length=160), nullable=False),
        sa.Column("input_schema_sha256", sa.String(length=64), nullable=False),
        sa.Column("output_schema_sha256", sa.String(length=64), nullable=True),
        sa.Column("confirmation_policy", sa.String(length=32), nullable=False),
        sa.Column("on_unavailable", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            _enum_check("confirmation_policy", ("direct-safe", "confirm", "hitl")),
            name="ck_system_bindings_confirmation_policy",
        ),
        sa.CheckConstraint(
            _enum_check("on_unavailable", ("empty", "unavailable", "admin-repair")),
            name="ck_system_bindings_on_unavailable",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "binding_key",
            name="uq_system_bindings_workspace_key",
        ),
    )
    op.create_index(
        "ix_system_bindings_workspace_id",
        "system_bindings",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_system_bindings_system_id",
        "system_bindings",
        ["system_id"],
        unique=False,
    )
    _seed_nawa_password_reset()


def _seed_nawa_password_reset() -> None:
    """Lock ``nawa.password_reset`` if 065's System still has a published version."""

    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    needed = {"workspaces", "systems", "system_versions", "system_bindings"}
    if not needed.issubset(tables):
        return

    workspaces = sa.table(
        "workspaces",
        sa.column("id"),
        sa.column("slug"),
    )
    systems = sa.table(
        "systems",
        sa.column("id"),
        sa.column("workspace_id"),
        sa.column("name"),
        sa.column("settings", sa.JSON()),
        sa.column("published_flow_version_id"),
    )
    versions = sa.table(
        "system_versions",
        sa.column("id"),
        sa.column("system_id"),
        sa.column("workspace_id"),
        sa.column("flow_sha256"),
        sa.column("execution_contract", sa.JSON()),
    )
    bindings = sa.table(
        "system_bindings",
        sa.column("id"),
        sa.column("workspace_id"),
        sa.column("binding_key"),
        sa.column("system_id"),
        sa.column("published_flow_version_id"),
        sa.column("flow_sha256"),
        sa.column("ingress_id"),
        sa.column("input_schema_sha256"),
        sa.column("output_schema_sha256"),
        sa.column("confirmation_policy"),
        sa.column("on_unavailable"),
        sa.column("created_by"),
        sa.column("created_at"),
        sa.column("updated_at"),
    )

    ws_rows = bind.execute(
        sa.select(workspaces.c.id).where(workspaces.c.slug == NAWA_SLUG)
    ).all()
    now = datetime.utcnow()
    for ws in ws_rows:
        workspace_id = ws._mapping["id"]
        already = bind.execute(
            sa.select(bindings.c.id).where(
                bindings.c.workspace_id == workspace_id,
                bindings.c.binding_key == BINDING_KEY,
            )
        ).first()
        if already:
            continue
        ours = None
        for existing in bind.execute(
            sa.select(
                systems.c.id,
                systems.c.settings,
                systems.c.published_flow_version_id,
            ).where(
                systems.c.workspace_id == workspace_id,
                systems.c.name == SYSTEM_NAME,
            )
        ).all():
            if _as_dict(existing._mapping["settings"]).get("seed_origin") == SEED_ORIGIN_065:
                ours = existing._mapping
                break
        if ours is None or not ours["published_flow_version_id"]:
            continue
        version = bind.execute(
            sa.select(
                versions.c.id,
                versions.c.flow_sha256,
                versions.c.execution_contract,
            ).where(
                versions.c.id == ours["published_flow_version_id"],
                versions.c.system_id == ours["id"],
                versions.c.workspace_id == workspace_id,
            )
        ).first()
        if version is None:
            continue
        mapping = version._mapping
        flow_sha256 = mapping["flow_sha256"]
        if not isinstance(flow_sha256, str) or len(flow_sha256) != 64:
            continue
        contract = _as_dict(mapping["execution_contract"])
        ingresses = _as_list(contract.get("ingresses"))
        ingress = next(
            (
                item
                for item in ingresses
                if isinstance(item, dict) and item.get("ingress_id") == "source.request"
            ),
            next((item for item in ingresses if isinstance(item, dict)), None),
        )
        if not isinstance(ingress, dict):
            continue
        ingress_id = ingress.get("ingress_id")
        input_sha = ingress.get("input_schema_sha256")
        if not isinstance(ingress_id, str) or not ingress_id:
            continue
        if not isinstance(input_sha, str) or len(input_sha) != 64:
            continue
        outputs = _as_list(contract.get("outputs"))
        output_sha = None
        if len(outputs) == 1 and isinstance(outputs[0], dict):
            digest = outputs[0].get("schema_sha256")
            if isinstance(digest, str) and len(digest) == 64:
                output_sha = digest
        bind.execute(
            sa.insert(bindings).values(
                id=str(uuid4()),
                workspace_id=workspace_id,
                binding_key=BINDING_KEY,
                system_id=ours["id"],
                published_flow_version_id=mapping["id"],
                flow_sha256=flow_sha256,
                ingress_id=ingress_id,
                input_schema_sha256=input_sha,
                output_schema_sha256=output_sha,
                confirmation_policy="hitl",
                on_unavailable="unavailable",
                created_by=f"system:{SEED_ORIGIN}",
                created_at=now,
                updated_at=now,
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "system_bindings" in tables:
        bindings = sa.table(
            "system_bindings",
            sa.column("binding_key"),
            sa.column("created_by"),
        )
        bind.execute(
            sa.delete(bindings).where(
                bindings.c.binding_key == BINDING_KEY,
                bindings.c.created_by == f"system:{SEED_ORIGIN}",
            )
        )
        op.drop_index("ix_system_bindings_system_id", table_name="system_bindings")
        op.drop_index("ix_system_bindings_workspace_id", table_name="system_bindings")
        op.drop_table("system_bindings")
