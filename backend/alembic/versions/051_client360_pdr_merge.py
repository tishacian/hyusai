"""Merge Client360 PDR with the VM chat parity stamp.

Revision ID: 051_client360_pdr_merge
Revises: 048_client360_pdr, 050_andritz_chat_parity
Create Date: 2026-07-08
"""
from __future__ import annotations


revision = "051_client360_pdr_merge"
down_revision = ("048_client360_pdr", "050_andritz_chat_parity")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
