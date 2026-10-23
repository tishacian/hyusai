"""Mark Work record attempts linked by a historical backfill.

Additive only: one nullable column and its index. Rows written when a Run
starts keep NULL; a backfill stamps the rows it creates with its batch id so
that exactly those rows can be removed again.
"""

import sqlalchemy as sa

from alembic import op

revision = "148_work_record_backfill"
down_revision = "147_work_record_runs"
branch_labels = depends_on = None


def upgrade():
    op.add_column("work_record_runs", sa.Column("backfill_batch_id", sa.String(36), nullable=True))
    op.create_index("ix_work_record_runs_backfill_batch", "work_record_runs", ["backfill_batch_id"])


def downgrade():
    op.drop_index("ix_work_record_runs_backfill_batch", table_name="work_record_runs")
    op.drop_column("work_record_runs", "backfill_batch_id")
