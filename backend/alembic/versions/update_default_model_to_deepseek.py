"""Update default model to DeepSeek-R1:14B

Revision ID: a1b2c3d4e5f6
Revises: 7f64035c0cbd
Create Date: 2024-12-19

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '7f64035c0cbd'
branch_labels = None
depends_on = None


def upgrade():
    # Update default_model for existing settings to deepseek-r1:14b
    # This model has 128K context window and very fast generation
    # Note: 128K is currently the largest context window commonly available in Ollama
    # For 1M context, specialized models may be needed (not yet widely available)
    op.execute("""
        UPDATE app_settings 
        SET default_model = 'deepseek-r1:14b',
            max_tokens = 8000
        WHERE default_model = 'llama3.1:8b' OR default_model IS NULL OR max_tokens < 8000
    """)


def downgrade():
    # Revert to llama3.1:8b
    op.execute("""
        UPDATE app_settings 
        SET default_model = 'llama3.1:8b',
            max_tokens = 2000
        WHERE default_model = 'deepseek-r1:14b'
    """)

