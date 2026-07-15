"""Workspace and membership models"""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, String, DateTime, Boolean, JSON, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.db.base import Base


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
    settings = Column(JSON, default=dict)
    mode = Column(String(32), nullable=False, default="executive")

    members = relationship("WorkspaceMember", back_populates="workspace", cascade="all, delete-orphan")
    iam_config = relationship(
        "WorkspaceIAMConfig",
        back_populates="workspace",
        cascade="all, delete-orphan",
        uselist=False,
    )


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False)
    role = Column(String(50), default="member")
    role_template = Column(String(80), nullable=True, index=True)
    custom_labels = Column(JSON, default=list)
    joined_at = Column(DateTime, default=datetime.utcnow)

    workspace = relationship("Workspace", back_populates="members")
    user = relationship("User", back_populates="workspace_memberships")
    app_entitlements = relationship(
        "WorkspaceMemberAppEntitlement",
        back_populates="membership",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (UniqueConstraint("user_id", "workspace_id", name="uq_user_workspace"),)


class WorkspaceMemberAppEntitlement(Base):
    """Explicit access grant to a workspace application for one membership.

    Row existence is the grant.  Missing rows therefore remain fail-closed
    when the workspace entitlement feature is enabled, while deleting a
    membership removes every associated grant through the database cascade.
    """

    __tablename__ = "workspace_member_app_entitlements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_member_id = Column(
        Integer,
        ForeignKey("workspace_members.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    app_key = Column(String(80), nullable=False, index=True)
    granted_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    granted_by_user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    grant_source = Column(String(80), nullable=False, default="manual")

    membership = relationship("WorkspaceMember", back_populates="app_entitlements")

    __table_args__ = (
        UniqueConstraint(
            "workspace_member_id",
            "app_key",
            name="uq_workspace_member_app_entitlement",
        ),
    )


class WorkspaceIAMConfig(Base):
    __tablename__ = "workspace_iam_configs"

    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    version = Column(Integer, nullable=False, default=1)
    role_flags = Column(JSON, default=dict)
    capability_overrides = Column(JSON, default=dict)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    updated_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)

    workspace = relationship("Workspace", back_populates="iam_config")
