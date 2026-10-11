"""Secret registry rows. Values never live here in clear: ``db`` versions hold
Fernet ciphertext, ``openbao`` versions hold a KV v2 path/version reference."""

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

SECRET_SCOPES = ("platform", "workspace", "system")
SECRET_KINDS = ("api_key", "token", "password", "oauth_client", "generic")
SECRET_BACKENDS = ("db", "openbao")


def _id():
    return str(uuid4())


class Secret(Base):
    __tablename__ = "secrets"
    __table_args__ = (
        # owner_key is "platform", the workspace id or the system id: NULL
        # owners would make the uniqueness constraint toothless.
        UniqueConstraint("scope", "owner_key", "name", name="uq_secrets_scope_owner_name"),
        CheckConstraint("scope IN ('platform','workspace','system')", name="ck_secrets_scope"),
        CheckConstraint(
            "kind IN ('api_key','token','password','oauth_client','generic')",
            name="ck_secrets_kind",
        ),
        CheckConstraint("backend IN ('db','openbao')", name="ck_secrets_backend"),
    )

    id = Column(String(36), primary_key=True, default=_id)
    scope = Column(String(16), nullable=False)
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True
    )
    system_id = Column(
        String(36), ForeignKey("systems.id", ondelete="CASCADE"), nullable=True, index=True
    )
    owner_key = Column(String(36), nullable=False)
    name = Column(String(120), nullable=False)
    kind = Column(String(24), nullable=False, default="generic")
    backend = Column(String(16), nullable=False, default="db")
    current_version = Column(Integer, nullable=False, default=1)
    description = Column(Text, nullable=True)
    meta = Column("metadata", JSON, nullable=False, default=dict)
    expires_at = Column(DateTime, nullable=True)
    rotated_at = Column(DateTime, nullable=True)
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    disabled_at = Column(DateTime, nullable=True)


class SecretVersion(Base):
    __tablename__ = "secret_versions"
    __table_args__ = (
        UniqueConstraint("secret_id", "version", name="uq_secret_versions_secret_ver"),
    )

    id = Column(String(36), primary_key=True, default=_id)
    secret_id = Column(
        String(36), ForeignKey("secrets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version = Column(Integer, nullable=False)
    ciphertext = Column(Text, nullable=True)
    backend_ref = Column(String(500), nullable=True)
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    destroyed_at = Column(DateTime, nullable=True)
