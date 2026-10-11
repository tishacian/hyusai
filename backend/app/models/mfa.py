"""MFA challenge model — stores email OTP codes for pending login sessions."""
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Integer, Text, ForeignKey
from app.db.base import Base


class MfaChallenge(Base):
    """A 2FA challenge pending verification.

    When a user completes password auth but MFA is required, we create a challenge
    row with a 6-digit code and the Keycloak token response. Once the user submits
    the correct code within the TTL, we return the stored tokens.
    """

    __tablename__ = "mfa_challenges"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    code = Column(String(6), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    attempts = Column(Integer, default=0)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Stored KC token response (JSON-encoded) — released on successful MFA
    kc_payload = Column(Text, nullable=False)
