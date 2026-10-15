"""Ground truth belongs to one persisted serving sample, never an implicit batch."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint

from app.db.base import Base


class MLPredictionFeedback(Base):
    __tablename__ = "ml_prediction_feedback"

    sample_id = Column(String(64), primary_key=True)
    prediction_id = Column(
        String(36), ForeignKey("ml_predictions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sample_index = Column(Integer, nullable=False)
    label = Column(String(200), nullable=False)
    labeled_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    labeled_by = Column(String(36), nullable=True)
    __table_args__ = (
        UniqueConstraint("prediction_id", "sample_index", name="uq_ml_feedback_prediction_sample"),
    )
