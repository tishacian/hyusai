"""Separate access policy and freeze the release's public identity.

Revision ID: 092_experience_access_policy
Revises: 091_xp_sentinel_certified
"""
from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

from app.services.experience.dual_run_seeds import repair_mutated_091_releases

revision = "092_experience_access_policy"
down_revision = "091_xp_sentinel_certified"
branch_labels = None
depends_on = None
_FAIL_CLOSED_POLICY = {"roles": ["__invalid_migrated_audience__"]}


def _dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return dict(parsed) if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _policy(value: Any) -> dict[str, list[str]]:
    raw = _dict(value)
    if not raw and value not in ({}, None):
        return dict(_FAIL_CLOSED_POLICY)
    if set(raw) - {"roles", "role_templates", "groups"} or (
        "roles" in raw and "role_templates" in raw
    ):
        return dict(_FAIL_CLOSED_POLICY)
    result: dict[str, list[str]] = {}
    roles = raw.get("roles", raw.get("role_templates"))
    groups = raw.get("groups")
    if roles is not None:
        if not isinstance(roles, list) or any(
            not isinstance(item, str) or not item.strip() for item in roles
        ):
            return dict(_FAIL_CLOSED_POLICY)
        result["roles"] = list(dict.fromkeys(item.strip() for item in roles))
    if groups is not None:
        if not isinstance(groups, list) or any(
            not isinstance(item, str) or not item.strip() for item in groups
        ):
            return dict(_FAIL_CLOSED_POLICY)
        result["groups"] = list(dict.fromkeys(item.strip() for item in groups))
    return result


def upgrade() -> None:
    op.add_column(
        "experience_releases",
        sa.Column(
            "identity_snapshot",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "experiences",
        sa.Column(
            "access_policy",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    bind = op.get_bind()
    experiences = sa.table(
        "experiences",
        sa.column("id"),
        sa.column("name"),
        sa.column("slug"),
        sa.column("pattern"),
        sa.column("theme", sa.JSON()),
        sa.column("access_policy", sa.JSON()),
    )
    policies: dict[str, dict[str, list[str]]] = {}
    for row in bind.execute(sa.select(experiences.c.id, experiences.c.theme)).all():
        theme = _dict(row._mapping["theme"])
        policy = _policy(theme.pop("audience")) if "audience" in theme else {}
        policies[str(row._mapping["id"])] = policy
        bind.execute(
            experiences.update()
            .where(experiences.c.id == row._mapping["id"])
            .values(theme=theme, access_policy=policy)
        )
    repair_mutated_091_releases(bind)

    # Run this after the 091 repair: it may append an immutable successor
    # release, which must receive the same complete identity evidence.
    releases = sa.table(
        "experience_releases",
        sa.column("id"),
        sa.column("experience_id"),
        sa.column("access_snapshot", sa.JSON()),
        sa.column("identity_snapshot", sa.JSON()),
    )
    deployments = sa.table(
        "experience_deployments",
        sa.column("experience_id"),
        sa.column("channel"),
        sa.column("audience", sa.JSON()),
    )
    rows = bind.execute(
        sa.select(
            releases.c.id,
            releases.c.experience_id,
            experiences.c.name,
            experiences.c.slug,
            experiences.c.pattern,
        ).join(experiences, experiences.c.id == releases.c.experience_id)
    ).all()
    for row in rows:
        mapping = row._mapping
        bind.execute(
            releases.update()
            .where(releases.c.id == mapping["id"])
            .values(
                access_snapshot=policies.get(str(mapping["experience_id"]), {}),
                identity_snapshot={
                    "name": mapping["name"],
                    "slug": mapping["slug"],
                    "pattern": mapping["pattern"],
                }
            )
        )
    for experience_id, policy in policies.items():
        bind.execute(
            deployments.update()
            .where(
                deployments.c.experience_id == experience_id,
                deployments.c.channel == "live",
            )
            .values(audience=policy)
        )


def downgrade() -> None:
    op.drop_column("experience_releases", "identity_snapshot")
    op.drop_column("experiences", "access_policy")
