"""Workspace and membership models"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import relationship
from sqlalchemy.sql.expression import ColumnElement

from app.db.base import Base
from app.schemas.canonical import WorkspaceFamily, WorkspaceMode


def _enum_check(column: str, values: list[str]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _default_workspace_settings() -> dict[str, str]:
    return {"family": WorkspaceFamily.generic.value}


def _app_key_common_check() -> str:
    """The portable half of the check: length, lower-cased, and no whitespace.

    "No whitespace" is spelled with ``replace`` rather than the ``NOT LIKE
    '% %'`` it reads as, because this string is embedded verbatim into DDL and
    psycopg2 interpolates ``%`` in any statement it is handed — so a LIKE
    wildcard here made ``create_all`` raise "immutabledict is not a sequence"
    against Postgres and took the whole schema bootstrap with it. ``replace`` is
    understood by every dialect this runs on and says the same thing.
    """

    return (
        "length(app_key) BETWEEN 1 AND 80 "
        "AND app_key = lower(trim(app_key)) "
        "AND app_key = replace(app_key, ' ', '')"
    )


class _AppKeyFormatCheck(ColumnElement):
    """One named CHECK whose charset operator follows the SQL dialect."""

    inherit_cache = True
    type = Boolean()


@compiles(_AppKeyFormatCheck)
def _compile_app_key_check_default(_element, _compiler, **_kw) -> str:
    return _app_key_common_check()


@compiles(_AppKeyFormatCheck, "postgresql")
def _compile_app_key_check_postgresql(_element, _compiler, **_kw) -> str:
    return _app_key_common_check() + " AND app_key ~ '^[a-z0-9][a-z0-9.-]{0,79}$'"


@compiles(_AppKeyFormatCheck, "sqlite")
def _compile_app_key_check_sqlite(_element, _compiler, **_kw) -> str:
    return (
        _app_key_common_check()
        + " AND app_key NOT GLOB '*[^a-z0-9.-]*'"
        + " AND substr(app_key, 1, 1) GLOB '[a-z0-9]'"
    )


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
    settings = Column(JSON, default=_default_workspace_settings)
    mode = Column(String(32), nullable=False, default="executive")

    members = relationship(
        "WorkspaceMember", back_populates="workspace", cascade="all, delete-orphan"
    )
    iam_config = relationship(
        "WorkspaceIAMConfig",
        back_populates="workspace",
        cascade="all, delete-orphan",
        uselist=False,
    )

    __table_args__ = (
        CheckConstraint(
            _enum_check("mode", [item.value for item in WorkspaceMode]),
            name="ck_workspaces_mode",
        ),
    )


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False)
    role = Column(String(50), default="member")
    role_template = Column(String(80), nullable=True, index=True)
    custom_labels = Column(JSON, default=list)
    experience_progress = Column(JSON, nullable=True)
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
        CheckConstraint(
            _AppKeyFormatCheck(),
            name="ck_workspace_member_app_entitlements_app_key",
        ),
    )


class WorkspaceIAMConfig(Base):
    __tablename__ = "workspace_iam_configs"

    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    version = Column(Integer, nullable=False, default=1)
    role_flags = Column(JSON, default=dict)
    capability_overrides = Column(JSON, default=dict)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    updated_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)

    workspace = relationship("Workspace", back_populates="iam_config")
