"""Lot 8: dual-run Experiences for Andritz, Sentinel, Octocity, Mission Control.

Revision ID: 090_xp_dual_run
Revises: 089_publish_nawa_recon

Data only. Idempotent. Experiences are inventory pointers
(``theme.live_href``). Bindings are created only when a published Flow
version is already present.
"""
from __future__ import annotations

from alembic import op

from app.services.experience.dual_run_seeds import (
    seed_dual_run_experiences,
    unseed_dual_run_experiences,
)

revision = "090_xp_dual_run"
down_revision = "089_publish_nawa_recon"
branch_labels = None
depends_on = None


def upgrade() -> None:
    seed_dual_run_experiences(op.get_bind())


def downgrade() -> None:
    unseed_dual_run_experiences(op.get_bind())
