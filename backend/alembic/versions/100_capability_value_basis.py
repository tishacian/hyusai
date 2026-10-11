"""Governed value basis on Capability for the Hypervisor denominator.

Hours and declared value live on the Capability so live series can convert
native outcomes without inventing a second economics source. ``value_per_outcome``
stays the column ``outcome/derive.py`` already reads; writers keep them mirrored.

Revision ID: 100_capability_value_basis
Revises: 099_data_plane_attached
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "100_capability_value_basis"
down_revision = "099_data_plane_attached"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("capabilities", sa.Column("value_basis", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("capabilities", "value_basis")
