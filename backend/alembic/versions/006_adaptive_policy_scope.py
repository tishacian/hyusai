"""Add scope + target_id columns to adaptive_policies.

Revision ID: 006_adaptive_policy_scope
Revises: 005_system_defaults
Create Date: 2026-04-16

Wave E of the audit plan: the Steering cockpit filters adaptive policies
by scope (portfolio / capability / system) and target_id. The model already
carries triggers/constraints but lacked a first-class scope binding, which
forced the UI to smuggle that info into JSON blobs. We normalise it here.
"""
from alembic import op
import sqlalchemy as sa


revision = "006_adaptive_policy_scope"
down_revision = "005_system_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("adaptive_policies") as batch:
        batch.add_column(sa.Column("scope", sa.String(length=20), nullable=True))
        batch.add_column(sa.Column("target_id", sa.String(length=36), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("adaptive_policies") as batch:
        batch.drop_column("target_id")
        batch.drop_column("scope")
