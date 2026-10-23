"""Let an application deployment be withdrawn from its channel without deletion.

Additive only: two nullable columns. A withdrawn deployment keeps its row,
release and audience; Work ignores it until it is deployed again. Downgrade
drops the columns (a withdrawn deployment would then read as deployed again).
"""

import sqlalchemy as sa

from alembic import op

revision = "149_experience_deployment_withdrawn"
down_revision = "148_work_record_backfill"
branch_labels = depends_on = None


def upgrade():
    op.add_column("experience_deployments", sa.Column("withdrawn_at", sa.DateTime(), nullable=True))
    op.add_column("experience_deployments", sa.Column("withdrawn_by", sa.String(255), nullable=True))


def downgrade():
    op.drop_column("experience_deployments", "withdrawn_by")
    op.drop_column("experience_deployments", "withdrawn_at")
