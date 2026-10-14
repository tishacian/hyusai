"""Single-use OAuth PKCE requests; token values remain in the scoped secret registry."""

import sqlalchemy as sa

from alembic import op

revision = "130_connector_oauth_states"
down_revision = "129_connector_governance"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "connector_oauth_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("state_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("connection_id", sa.String(36), nullable=False),
        sa.Column("connection_revision", sa.Integer(), nullable=False),
        sa.Column(
            "owner_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("verifier_ref", sa.String(240), nullable=False),
        sa.Column("redirect_uri", sa.String(2048), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["connections.workspace_id", "connections.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_connector_oauth_states_workspace_id", "connector_oauth_states", ["workspace_id"]
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM connector_oauth_states LIMIT 1")).first():
        raise RuntimeError("Downgrade refused: OAuth authorization records exist")
    op.drop_table("connector_oauth_states")
