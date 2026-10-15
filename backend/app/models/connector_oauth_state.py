"""One-use OAuth requests. State and PKCE material are never stored in plaintext."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Column, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String

from app.db.base import Base


class ConnectorOAuthState(Base):
    __tablename__ = "connector_oauth_states"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["connections.workspace_id", "connections.id"],
            ondelete="CASCADE",
        ),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    state_sha256 = Column(String(64), nullable=False, unique=True)
    workspace_id = Column(String(36), nullable=False, index=True)
    connection_id = Column(String(36), nullable=False)
    connection_revision = Column(Integer, nullable=False)
    owner_user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    verifier_ref = Column(String(240), nullable=False)
    redirect_uri = Column(String(2048), nullable=False)
    scopes = Column(JSON, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    consumed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
