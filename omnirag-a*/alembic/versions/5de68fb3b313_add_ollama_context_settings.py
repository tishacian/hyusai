"""add_ollama_context_settings

Revision ID: 5de68fb3b313
Revises: c82434c93376
Create Date: 2025-12-22 22:11:15.865181

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5de68fb3b313'
down_revision = 'c82434c93376'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add Ollama high-context settings columns
    # Using 32K default for faster generation (can be increased to 64K/128K if needed)
    op.add_column('app_settings', sa.Column('ollama_num_ctx', sa.Integer(), nullable=True, server_default='32768'))
    op.add_column('app_settings', sa.Column('ollama_rope_scale', sa.Float(), nullable=True))
    op.add_column('app_settings', sa.Column('ollama_rope_alpha', sa.Float(), nullable=True))
    
    # Update existing rows with default values (32K for speed optimization)
    op.execute("UPDATE app_settings SET ollama_num_ctx = 32768 WHERE ollama_num_ctx IS NULL OR ollama_num_ctx > 65536")


def downgrade() -> None:
    op.drop_column('app_settings', 'ollama_rope_alpha')
    op.drop_column('app_settings', 'ollama_rope_scale')
    op.drop_column('app_settings', 'ollama_num_ctx')

