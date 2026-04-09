"""Add chunking settings to app_settings

Revision ID: add_chunking_settings
Revises: c82434c93376
Create Date: 2025-01-XX XX:XX:XX.XXXXXX

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_chunking_settings'
down_revision = '5de68fb3b313'  # After ollama context settings
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add chunking settings columns
    op.add_column('app_settings', sa.Column('rag_chunking_method', sa.String(), nullable=True, server_default='recursive_character'))
    op.add_column('app_settings', sa.Column('rag_chunk_size', sa.Integer(), nullable=True, server_default='1000'))
    op.add_column('app_settings', sa.Column('rag_chunk_overlap', sa.Integer(), nullable=True, server_default='200'))
    
    # Update existing rows with default values
    op.execute("UPDATE app_settings SET rag_chunking_method = 'recursive_character' WHERE rag_chunking_method IS NULL")
    op.execute("UPDATE app_settings SET rag_chunk_size = 1000 WHERE rag_chunk_size IS NULL")
    op.execute("UPDATE app_settings SET rag_chunk_overlap = 200 WHERE rag_chunk_overlap IS NULL")


def downgrade() -> None:
    op.drop_column('app_settings', 'rag_chunk_overlap')
    op.drop_column('app_settings', 'rag_chunk_size')
    op.drop_column('app_settings', 'rag_chunking_method')

