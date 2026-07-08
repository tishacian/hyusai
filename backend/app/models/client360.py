"""Client360 PDR pre-MVP data model.

The model deliberately stores explainable commercial potential and human
workflow evidence. It does not store supervised predictions or automated email
send state.
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
)

from app.db.base import Base


CLIENT360_SOURCE_TYPES = (
    "installed_base",
    "periodicity",
    "sap_sales_history",
    "contact_hub",
    "market_signal",
    "other",
)
CLIENT360_SOURCE_STATUSES = ("candidate", "mapped", "ready", "needs_review", "error", "archived")
CLIENT360_OPPORTUNITY_STATUSES = (
    "detected",
    "validated",
    "draft_generated",
    "sent",
    "responded",
    "quote_requested",
    "won",
    "lost",
    "dismissed",
)
CLIENT360_MAIL_STATUSES = (
    "draft_generated",
    "edited_by_sales",
    "approved",
    "sent",
    "cancelled",
)
CLIENT360_IMPACT_TYPES = ("response", "quote", "order", "lost", "no_response", "note")
CLIENT360_ATTRIBUTIONS = ("direct", "probable", "unknown", "none")
CLIENT360_MAPPING_STATUSES = ("candidate", "validated", "rejected", "needs_review")
CLIENT360_OUTCOME_REASONS = (
    "price",
    "competitor",
    "no_need",
    "wrong_contact",
    "timing",
    "hub",
    "technical_mismatch",
    "bad_data",
    "other",
    "unknown",
)


class Client360DataSource(Base):
    __tablename__ = "client360_data_sources"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)

    source_type = Column(String(40), nullable=False, default="other")
    label = Column(String(255), nullable=False)
    filename = Column(Text, nullable=True)
    collection_id = Column(String(36), ForeignKey("knowledge_collections.id", ondelete="SET NULL"), nullable=True, index=True)
    collection_slug = Column(String(120), nullable=True, index=True)
    knowledge_source_id = Column(String(36), ForeignKey("knowledge_collection_sources.id", ondelete="SET NULL"), nullable=True, index=True)
    deposit_file_id = Column(String(36), ForeignKey("deposit_files.id", ondelete="SET NULL"), nullable=True, index=True)

    status = Column(String(32), nullable=False, default="candidate")
    row_count = Column(Float, nullable=True)
    error = Column(Text, nullable=True)
    meta_data = Column("metadata", JSON, nullable=False, default=dict)
    evidence_refs = Column(JSON, nullable=False, default=list)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "source_type IN ('installed_base', 'periodicity', 'sap_sales_history', 'contact_hub', 'market_signal', 'other')",
            name="ck_client360_data_sources_type",
        ),
        CheckConstraint(
            "status IN ('candidate', 'mapped', 'ready', 'needs_review', 'error', 'archived')",
            name="ck_client360_data_sources_status",
        ),
        Index("ix_client360_data_sources_workspace_type", "workspace_id", "source_type"),
    )


class Client360Opportunity(Base):
    __tablename__ = "client360_opportunities"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)

    customer_key = Column(String(160), nullable=False, index=True)
    customer_name = Column(String(255), nullable=False)
    site_name = Column(String(255), nullable=True)
    country = Column(String(120), nullable=True, index=True)
    hub = Column(String(120), nullable=True, index=True)
    technology = Column(String(120), nullable=True, index=True)
    line_label = Column(String(255), nullable=True)
    machine_label = Column(String(255), nullable=True)

    part_family = Column(String(200), nullable=False, index=True)
    part_reference = Column(String(160), nullable=True, index=True)
    part_description = Column(Text, nullable=True)

    installed_quantity = Column(Float, nullable=True)
    recommended_quantity = Column(Float, nullable=True)
    periodicity_weeks = Column(Float, nullable=True)
    delivery_time_weeks = Column(Float, nullable=True)
    annual_theoretical_qty = Column(Float, nullable=True)
    potential_theoretical = Column(Float, nullable=True)
    potential_addressable = Column(Float, nullable=True)
    potential_unit = Column(String(40), nullable=False, default="quantity_per_year")
    currency = Column(String(12), nullable=True)

    sales_known_qty = Column(Float, nullable=True)
    sales_known_value = Column(Float, nullable=True)
    potential_gap_qty = Column(Float, nullable=True)
    potential_gap_value = Column(Float, nullable=True)
    next_due_at = Column(DateTime, nullable=True, index=True)

    confidence_score = Column(Float, nullable=True)
    confidence_label = Column(String(24), nullable=False, default="low")
    score_reasons = Column(JSON, nullable=False, default=list)
    recommended_action = Column(String(120), nullable=True)
    status = Column(String(32), nullable=False, default="detected", index=True)
    data_gaps = Column(JSON, nullable=False, default=list)
    evidence_refs = Column(JSON, nullable=False, default=list)
    source_ids = Column(JSON, nullable=False, default=list)
    meta_data = Column("metadata", JSON, nullable=False, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('detected', 'validated', 'draft_generated', 'sent', 'responded', 'quote_requested', 'won', 'lost', 'dismissed')",
            name="ck_client360_opportunities_status",
        ),
        Index("ix_client360_opportunities_workspace_customer", "workspace_id", "customer_key"),
        Index("ix_client360_opportunities_workspace_status", "workspace_id", "status"),
    )


class Client360MappingRule(Base):
    __tablename__ = "client360_mapping_rules"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)

    source_part_reference = Column(String(160), nullable=True, index=True)
    source_part_label = Column(String(255), nullable=True)
    source_part_family = Column(String(200), nullable=True, index=True)
    source_system = Column(String(80), nullable=False, default="sap")
    technology = Column(String(120), nullable=True, index=True)

    pdr_family = Column(String(200), nullable=False, index=True)
    normalized_key = Column(String(320), nullable=False, index=True)
    recommended_quantity = Column(Float, nullable=True)
    periodicity_weeks = Column(Float, nullable=True)
    delivery_time_weeks = Column(Float, nullable=True)

    status = Column(String(32), nullable=False, default="candidate", index=True)
    confidence = Column(Float, nullable=False, default=0.4)
    notes = Column(Text, nullable=False, default="")
    evidence_refs = Column(JSON, nullable=False, default=list)
    meta_data = Column("metadata", JSON, nullable=False, default=dict)

    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    updated_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('candidate', 'validated', 'rejected', 'needs_review')",
            name="ck_client360_mapping_rules_status",
        ),
        Index("ix_client360_mapping_rules_workspace_key", "workspace_id", "normalized_key"),
    )


class Client360MailDraft(Base):
    __tablename__ = "client360_mail_drafts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    opportunity_id = Column(String(36), ForeignKey("client360_opportunities.id", ondelete="CASCADE"), nullable=False, index=True)
    action_item_id = Column(String(36), ForeignKey("workspace_action_items.id", ondelete="SET NULL"), nullable=True, index=True)

    subject = Column(String(255), nullable=False)
    generated_body = Column(Text, nullable=False)
    sent_body = Column(Text, nullable=True)
    language = Column(String(16), nullable=False, default="fr")
    status = Column(String(32), nullable=False, default="draft_generated")
    meta_data = Column("metadata", JSON, nullable=False, default=dict)

    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    sent_at = Column(DateTime, nullable=True, index=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft_generated', 'edited_by_sales', 'approved', 'sent', 'cancelled')",
            name="ck_client360_mail_drafts_status",
        ),
        Index("ix_client360_mail_drafts_workspace_status", "workspace_id", "status"),
    )


class Client360ImpactEvent(Base):
    __tablename__ = "client360_impact_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    opportunity_id = Column(String(36), ForeignKey("client360_opportunities.id", ondelete="SET NULL"), nullable=True, index=True)
    action_item_id = Column(String(36), ForeignKey("workspace_action_items.id", ondelete="SET NULL"), nullable=True, index=True)
    mail_draft_id = Column(String(36), ForeignKey("client360_mail_drafts.id", ondelete="SET NULL"), nullable=True, index=True)

    impact_type = Column(String(32), nullable=False)
    attribution = Column(String(24), nullable=False, default="unknown")
    reason = Column(String(40), nullable=False, default="unknown")
    summary = Column(Text, nullable=False, default="")
    quote_value = Column(Float, nullable=True)
    order_value = Column(Float, nullable=True)
    currency = Column(String(12), nullable=True)
    occurred_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    meta_data = Column("metadata", JSON, nullable=False, default=dict)

    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "impact_type IN ('response', 'quote', 'order', 'lost', 'no_response', 'note')",
            name="ck_client360_impact_events_type",
        ),
        CheckConstraint(
            "attribution IN ('direct', 'probable', 'unknown', 'none')",
            name="ck_client360_impact_events_attribution",
        ),
        CheckConstraint(
            "reason IN ('price', 'competitor', 'no_need', 'wrong_contact', 'timing', 'hub', 'technical_mismatch', 'bad_data', 'other', 'unknown')",
            name="ck_client360_impact_events_reason",
        ),
        Index("ix_client360_impact_events_workspace_type", "workspace_id", "impact_type"),
    )
