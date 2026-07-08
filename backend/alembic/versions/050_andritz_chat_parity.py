"""Reconcile Andritz chat parity Alembic stamp.

Revision ID: 050_andritz_chat_parity
Revises: 047_andritz_membrane
Create Date: 2026-07-08

The demo VM database is already stamped with this revision. The matching file
was missing from the deploy branch, which prevented later migrations from
running. Keep this as a no-op compatibility revision so the Alembic graph is
complete again without guessing historical production changes.
"""
from __future__ import annotations


revision = "050_andritz_chat_parity"
down_revision = "047_andritz_membrane"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
