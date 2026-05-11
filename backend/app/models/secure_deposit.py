"""Secure external deposit links and staged files."""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from app.db.base import Base


class DepositAccessLink(Base):
    __tablename__ = "deposit_access_links"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    label = Column(String(255), nullable=False, default="External deposit")
    access_id = Column(String(80), nullable=False, unique=True, index=True)
    password_hash = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, default="active")
    expires_at = Column(DateTime, nullable=True)
    max_file_size_mb = Column(Integer, nullable=False, default=100)
    allowed_extensions = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    files = relationship("DepositFile", back_populates="access_link", cascade="all, delete-orphan")


class DepositFile(Base):
    __tablename__ = "deposit_files"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    access_link_id = Column(String(36), ForeignKey("deposit_access_links.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    content_type = Column(String(255), nullable=True)
    object_key = Column(Text, nullable=False)
    size_bytes = Column(BigInteger, nullable=False, default=0)
    sha256 = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default="received")
    uploaded_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    promoted_at = Column(DateTime, nullable=True)
    promoted_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    promoted_collection_slug = Column(String(120), nullable=True)
    worker_job_id = Column(String(36), nullable=True)
    promotion_result = Column(JSON, nullable=True)
    rejection_reason = Column(Text, nullable=True)

    access_link = relationship("DepositAccessLink", back_populates="files")
