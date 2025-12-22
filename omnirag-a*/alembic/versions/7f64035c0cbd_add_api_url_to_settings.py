"""add_api_url_to_settings

Revision ID: 7f64035c0cbd
Revises: 70e2ecf77346
Create Date: 2025-12-11 23:47:25.180499

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7f64035c0cbd'
down_revision = '70e2ecf77346'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add api_url column to app_settings table
    op.add_column('app_settings', sa.Column('api_url', sa.String(), nullable=True, server_default='http://localhost:8000/api/v1'))


def downgrade() -> None:
    # Remove api_url column from app_settings table
    op.drop_column('app_settings', 'api_url')

