"""Cockpit/decisions bindings + certified Sentinel/Octocity widgets.

Revision ID: 091_xp_sentinel_certified
Revises: 090_xp_dual_run

Data only. Idempotent. Re-runs the dual-run seeder so workspaces that
already applied 090 pick up cockpit/decisions bindings and certified
mission pages. Fresh 090 installs already have both.
"""
from __future__ import annotations

from alembic import op

from app.services.experience.dual_run_seeds import upgrade_dual_run_experiences

revision = "091_xp_sentinel_certified"
down_revision = "090_xp_dual_run"
branch_labels = None
depends_on = None


def upgrade() -> None:
    upgrade_dual_run_experiences(op.get_bind())


def downgrade() -> None:
    return
