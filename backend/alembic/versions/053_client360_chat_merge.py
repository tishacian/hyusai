"""Merge the Client360 campaigns and Andritz chat agentic heads.

Phase 2 of the Client360 PDR post-MVP backlog added
``052_client360_campaigns`` on top of ``051_client360_pdr_merge``, while the
Andritz chat roadmap added ``051_andritz_chat_latency_mh`` (also descending from
``051_client360_pdr_merge``). That left two divergent heads. This is a no-op
merge revision so the Alembic graph has a single head again.

Revision ID: 053_client360_chat_merge
Revises: 051_andritz_chat_latency_mh, 052_client360_campaigns
Create Date: 2026-07-09
"""
from __future__ import annotations


revision = "053_client360_chat_merge"
down_revision = ("051_andritz_chat_latency_mh", "052_client360_campaigns")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
