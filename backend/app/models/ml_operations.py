"""Metadata-only serving accounting and durable alert deliveries."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String

from app.db.base import Base


def identity():
    return str(uuid4())


class MLInferenceUsage(Base):
    __tablename__ = "ml_inference_usage"
    id = Column(String(64), primary_key=True, default=identity)
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    model_id = Column(String(36), ForeignKey("ml_models.id", ondelete="CASCADE"), nullable=False)
    served_id = Column(String(36), nullable=False)
    version = Column(Integer, nullable=False)
    caller = Column(String(32), nullable=False)
    row_count = Column(Integer, nullable=False)
    duration_ms = Column(Float, nullable=True)
    error_code = Column(String(64), nullable=True)
    cpu_seconds = Column(Float, nullable=True)
    measured_cost_usd = Column(Float, nullable=True)
    tariff_cost_usd = Column(Float, nullable=True)
    tariff_evidence = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    rolled_up_at = Column(DateTime, nullable=True)
    __table_args__ = (Index("ix_ml_usage_pending", "rolled_up_at", "created_at"),)


class MLUsageRollup(Base):
    __tablename__ = "ml_usage_rollups"
    id = Column(String(64), primary_key=True)
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    model_id = Column(String(36), ForeignKey("ml_models.id", ondelete="CASCADE"), nullable=False)
    served_id = Column(String(36), nullable=False)
    version = Column(Integer, nullable=False)
    caller = Column(String(32), nullable=False)
    interval_start = Column(DateTime, nullable=False)
    requests = Column(Integer, nullable=False, default=0)
    rows = Column(Integer, nullable=False, default=0)
    errors = Column(Integer, nullable=False, default=0)
    latency_histogram = Column(JSON, nullable=False, default=dict)
    cpu_seconds = Column(Float, nullable=False, default=0)
    cpu_requests = Column(Integer, nullable=False, default=0)
    measured_cost_usd = Column(Float, nullable=False, default=0)
    measured_rows = Column(Integer, nullable=False, default=0)
    measured_requests = Column(Integer, nullable=False, default=0)
    tariff_cost_usd = Column(Float, nullable=False, default=0)
    tariff_requests = Column(Integer, nullable=False, default=0)
    tariff_rows = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (
        Index("ix_ml_rollups_scope_window", "workspace_id", "model_id", "interval_start"),
    )


class MLAlertChannel(Base):
    __tablename__ = "ml_alert_channels"
    id = Column(String(36), primary_key=True, default=identity)
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind = Column(String(16), nullable=False)
    name = Column(String(120), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    destination_email = Column(String(254), nullable=True)
    webhook_url_ref = Column(String(255), nullable=True)
    signing_key_ref = Column(String(255), nullable=True)
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class MLAlertState(Base):
    __tablename__ = "ml_alert_states"
    model_id = Column(String(36), ForeignKey("ml_models.id", ondelete="CASCADE"), primary_key=True)
    badge = Column(String(16), nullable=True)
    source_id = Column(String(64), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class MLAlert(Base):
    __tablename__ = "ml_alerts"
    id = Column(String(64), primary_key=True)
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    model_id = Column(String(36), ForeignKey("ml_models.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String(48), nullable=False)
    state = Column(String(64), nullable=False)
    source_id = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    acknowledged_at = Column(DateTime, nullable=True)
    acknowledged_by = Column(String(36), nullable=True)
    __table_args__ = (Index("ix_ml_alerts_workspace_created", "workspace_id", "created_at"),)


class MLAlertDelivery(Base):
    __tablename__ = "ml_alert_deliveries"
    id = Column(String(64), primary_key=True)
    alert_id = Column(String(64), ForeignKey("ml_alerts.id", ondelete="CASCADE"), nullable=False)
    channel_id = Column(
        String(36), ForeignKey("ml_alert_channels.id", ondelete="CASCADE"), nullable=False
    )
    status = Column(String(16), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    available_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    lease_token = Column(String(36), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    error_code = Column(String(64), nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    __table_args__ = (Index("ix_ml_alert_delivery_due", "status", "available_at"),)


class MLAlertSource(Base):
    __tablename__ = "ml_alert_sources"
    source_id = Column(String(64), nullable=False, index=True)
    event_type = Column(String(48), nullable=False)
    id = Column(String(64), primary_key=True)
    alert_id = Column(String(64), ForeignKey("ml_alerts.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
