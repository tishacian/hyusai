"""Experience lifecycle: identity, mutable draft, immutable release, channel pointer.

Publish a release does not deploy it. Deployment is a separate pointer per
channel (``pilot`` | ``live``). Rollback repoints that pointer.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.db.base import Base


EXPERIENCE_PATTERNS = (
    "assistant",
    "form_result",
    "queue",
    "approval",
    "dashboard",
    "mission_cockpit",
)
DEPLOYMENT_CHANNELS = ("pilot", "live")
DEFAULT_RENDERER_VERSION = "certified-components-0.2.0"


def _enum_check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class Experience(Base):
    __tablename__ = "experiences"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    description = Column(String(500), nullable=True)
    emblem = Column(String(32), nullable=True)
    slug = Column(String(120), nullable=False)
    pattern = Column(String(32), nullable=False)
    languages = Column(JSON, nullable=False, default=list)
    theme = Column(JSON, nullable=False, default=dict)
    access_policy = Column(JSON, nullable=False, default=dict)
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_experiences_workspace_slug"),
        CheckConstraint(
            _enum_check("pattern", EXPERIENCE_PATTERNS),
            name="ck_experiences_pattern",
        ),
    )


class ExperienceDraftRevision(Base):
    """Exactly one mutable draft document per Experience."""

    __tablename__ = "experience_draft_revisions"

    experience_id = Column(
        String(36),
        ForeignKey("experiences.id", ondelete="CASCADE"),
        primary_key=True,
    )
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision = Column(Integer, nullable=False, default=1)
    pages = Column(JSON, nullable=False, default=dict)
    binding_keys = Column(JSON, nullable=False, default=list)
    content_sha256 = Column(String(64), nullable=False)
    updated_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "revision >= 1",
            name="ck_experience_draft_revisions_revision_positive",
        ),
    )


class ExperienceDraftHistory(Base):
    """Append-only snapshots behind draft history and CAS restore."""

    __tablename__ = "experience_draft_history"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    experience_id = Column(
        String(36),
        ForeignKey("experiences.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision = Column(Integer, nullable=False)
    pages = Column(JSON, nullable=False)
    binding_keys = Column(JSON, nullable=False)
    content_sha256 = Column(String(64), nullable=False)
    saved_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "experience_id",
            "revision",
            name="uq_experience_draft_history_experience_revision",
        ),
        CheckConstraint(
            "revision >= 1",
            name="ck_experience_draft_history_revision_positive",
        ),
    )


class ExperienceRelease(Base):
    """Immutable snapshot. Creating one never moves a deployment pointer."""

    __tablename__ = "experience_releases"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    experience_id = Column(
        String(36),
        ForeignKey("experiences.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    release_number = Column(Integer, nullable=False)
    creation_request_sha256 = Column(String(64), nullable=True)
    content_sha256 = Column(String(64), nullable=False)
    pages = Column(JSON, nullable=False)
    bindings_snapshot = Column(JSON, nullable=False)
    access_snapshot = Column(JSON, nullable=False, default=dict)
    identity_snapshot = Column(JSON, nullable=False, default=dict)
    languages = Column(JSON, nullable=False)
    theme = Column(JSON, nullable=False)
    renderer_version = Column(
        String(80),
        nullable=False,
        default=DEFAULT_RENDERER_VERSION,
    )
    notes = Column(Text, nullable=False)
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "experience_id",
            "release_number",
            name="uq_experience_releases_experience_number",
        ),
        UniqueConstraint(
            "experience_id",
            "creation_request_sha256",
            name="uq_experience_releases_creation_request",
        ),
        CheckConstraint(
            "release_number >= 1",
            name="ck_experience_releases_number_positive",
        ),
    )


class ExperienceDeployment(Base):
    """One pointer per channel. Rollback = atomic repoint."""

    __tablename__ = "experience_deployments"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    experience_id = Column(
        String(36),
        ForeignKey("experiences.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel = Column(String(16), nullable=False)
    release_id = Column(
        String(36),
        ForeignKey("experience_releases.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    previous_release_id = Column(
        String(36),
        ForeignKey("experience_releases.id", ondelete="SET NULL"),
        nullable=True,
    )
    previous_audience = Column(JSON, nullable=True)
    audience = Column(JSON, nullable=False, default=dict)
    last_mutation_sha256 = Column(String(64), nullable=True)
    updated_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "experience_id",
            "channel",
            name="uq_experience_deployments_experience_channel",
        ),
        CheckConstraint(
            _enum_check("channel", DEPLOYMENT_CHANNELS),
            name="ck_experience_deployments_channel",
        ),
    )
