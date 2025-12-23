"""add_rag_collection_settings

Revision ID: c82434c93376
Revises: a1b2c3d4e5f6
Create Date: 2025-12-18 14:32:41.541672

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c82434c93376'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add RAG collection settings columns
    op.add_column('app_settings', sa.Column('rag_collection_name', sa.String(), server_default='documents', nullable=True))
    op.add_column('app_settings', sa.Column('rag_use_hybrid_search', sa.Boolean(), server_default='true', nullable=True))
    op.add_column('app_settings', sa.Column('rag_vector_weight', sa.Float(), server_default='0.7', nullable=True))
    op.add_column('app_settings', sa.Column('rag_bm25_weight', sa.Float(), server_default='0.3', nullable=True))
    op.add_column('app_settings', sa.Column('rag_vector_db_type', sa.String(), server_default='faiss', nullable=True))


def downgrade() -> None:
    # Remove RAG collection settings columns
    op.drop_column('app_settings', 'rag_vector_db_type')
    op.drop_column('app_settings', 'rag_bm25_weight')
    op.drop_column('app_settings', 'rag_vector_weight')
    op.drop_column('app_settings', 'rag_use_hybrid_search')
    op.drop_column('app_settings', 'rag_collection_name')

