"""Provider attempts and shared admission budgets, separate from Skill prices."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)

from app.db.base import Base


class ModelTariff(Base):
    __tablename__ = "model_usage_tariffs"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False, index=True)
    provider = Column(String(80), nullable=False)
    model = Column(String(200), nullable=False)
    revision = Column(Integer, nullable=False)
    currency = Column(String(3), nullable=False)
    rates = Column(JSON, nullable=False)
    created_by_user_id = Column(String(36), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "provider", "model", "revision", name="uq_model_tariff_revision"
        ),
    )


class ModelUsageCall(Base):
    __tablename__ = "model_usage_calls"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False, index=True)
    request_key = Column(String(200), nullable=False)
    request_sha256 = Column(String(64), nullable=False)
    system_id = Column(String(36), nullable=True, index=True)
    root_system_id = Column(String(36), nullable=True, index=True)
    run_id = Column(String(36), nullable=True, index=True)
    root_run_id = Column(String(36), nullable=True, index=True)
    invocation_id = Column(String(36), nullable=True, index=True)
    job_id = Column(String(36), nullable=True, index=True)
    worker_job_id = Column(String(36), nullable=True, index=True)
    campaign_id = Column(String(36), nullable=True, index=True)
    evaluation_id = Column(String(36), nullable=True, index=True)
    actor_user_id = Column(String(36), nullable=True)
    purpose = Column(String(40), nullable=False)
    traffic = Column(String(20), nullable=False)
    provider = Column(String(80), nullable=False)
    model = Column(String(200), nullable=False)
    returned_model = Column(String(200), nullable=True)
    operation = Column(String(40), nullable=False)
    provider_request_id = Column(String(200), nullable=True)
    status = Column(String(20), nullable=False, default="prepared")
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    dispatched_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    input_tokens = Column(BigInteger, nullable=True)
    output_tokens = Column(BigInteger, nullable=True)
    total_tokens = Column(BigInteger, nullable=True)
    cached_input_tokens = Column(BigInteger, nullable=True)
    cache_write_tokens = Column(BigInteger, nullable=True)
    reasoning_tokens = Column(BigInteger, nullable=True)
    usage_coverage = Column(String(20), nullable=False, default="unavailable")
    reserved_tokens = Column(BigInteger, nullable=True)
    reserved_amount = Column(Numeric(24, 12), nullable=True)
    amount = Column(Numeric(24, 12), nullable=True)
    currency = Column(String(3), nullable=True)
    tariff_id = Column(String(36), ForeignKey("model_usage_tariffs.id"), nullable=True)
    tariff_snapshot = Column(JSON, nullable=True)
    diagnostic = Column(String(160), nullable=True)
    details = Column(JSON, nullable=False, default=dict)
    __table_args__ = (
        UniqueConstraint("workspace_id", "request_key", name="uq_model_usage_request"),
        Index("ix_model_usage_workspace_started", "workspace_id", "started_at", "id"),
    )


class UsageBudgetPolicy(Base):
    __tablename__ = "model_usage_budget_policies"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False, index=True)
    scope_key = Column(String(80), nullable=False)
    system_id = Column(String(36), nullable=True, index=True)
    revision = Column(Integer, nullable=False, default=1)
    enabled = Column(Boolean, nullable=False, default=False)
    timezone = Column(String(80), nullable=False, default="UTC")
    max_tokens = Column(BigInteger, nullable=True)
    reconciliation_required = Column(Boolean, nullable=False, default=False)
    currency_limits = Column(JSON, nullable=False, default=dict)
    activated_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    history = Column(JSON, nullable=False, default=list)
    __table_args__ = (UniqueConstraint("workspace_id", "scope_key", name="uq_model_budget_scope"),)


class UsageBudgetBucket(Base):
    __tablename__ = "model_usage_budget_buckets"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    policy_id = Column(
        String(36), ForeignKey("model_usage_budget_policies.id"), nullable=False, index=True
    )
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    consumed_tokens = Column(BigInteger, nullable=False, default=0)
    reserved_tokens = Column(BigInteger, nullable=False, default=0)
    # Decimal strings, by currency. The workspace row serialises modifications.
    consumed_amounts = Column(JSON, nullable=False, default=dict)
    reserved_amounts = Column(JSON, nullable=False, default=dict)
    __table_args__ = (UniqueConstraint("policy_id", "period_start", name="uq_model_budget_period"),)


class UsageReservation(Base):
    __tablename__ = "model_usage_reservations"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    call_id = Column(String(36), ForeignKey("model_usage_calls.id"), nullable=False, index=True)
    bucket_id = Column(
        String(36), ForeignKey("model_usage_budget_buckets.id"), nullable=False, index=True
    )
    reserved_tokens = Column(BigInteger, nullable=False, default=0)
    reserved_amount = Column(Numeric(24, 12), nullable=False, default=0)
    currency = Column(String(3), nullable=True)
    # Independently settled dimensions: partial usage cannot release money.
    settled_tokens = Column(BigInteger, nullable=True)
    settled_amount = Column(Numeric(24, 12), nullable=True)
    released = Column(Boolean, nullable=False, default=False)
    __table_args__ = (UniqueConstraint("call_id", "bucket_id", name="uq_model_usage_allocation"),)
