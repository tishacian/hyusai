"""Model debugging in production: aggregated reports over labelled samples (M5).

One row is one analysis of one model version on the production samples it
served and that were later labelled. The report is aggregated by design — the
error tree's rules and node counts, per-group fairness metrics, the counts of
samples used and excluded — and never carries a production row.
"""

from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String

from app.db.base import Base

TRIGGERS = ("manual", "scheduled")
STATUSES = ("queued", "running", "completed", "insufficient_data", "failed")


class MLProductionExplanation(Base):
    __tablename__ = "ml_production_explanations"

    # Deterministic for a scheduled analysis (model and labelled-sample
    # watermark), so a replayed monitoring cycle cannot stage it twice.
    id = Column(String(64), primary_key=True)
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    model_id = Column(String(36), ForeignKey("ml_models.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    trigger = Column(String(16), nullable=False)
    status = Column(String(24), nullable=False)
    window_from = Column(DateTime, nullable=True)
    window_until = Column(DateTime, nullable=True)
    labeled_count = Column(Integer, nullable=False, default=0)
    used_count = Column(Integer, nullable=False, default=0)
    excluded_json = Column(JSON, nullable=False, default=dict)
    metrics_json = Column(JSON, nullable=False, default=dict)
    report_json = Column(JSON, nullable=False, default=dict)
    fairness_badge = Column(String(16), nullable=True)
    source_digest = Column(String(64), nullable=True)
    error_code = Column(String(64), nullable=True)
    created_by = Column(String(36), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_ml_production_explanations_model_created", "model_id", "created_at"),
        Index("ix_ml_production_explanations_workspace", "workspace_id"),
    )
