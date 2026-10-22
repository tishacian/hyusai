"""Validated business parameters for evidence-backed claim resolution.

These settings do not grant authority to pay, skip evidence or bypass approval.
Existing workspaces retain their original policy until an administrator changes
it explicitly. The effective contract is fingerprinted in every new proposal.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

from app.services.connectors.generic.postgresql_claims import digest


class ResolutionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    document_key: StrictStr = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
    document_version: StrictStr = Field(min_length=1, max_length=64)
    document_sha256: StrictStr = Field(pattern=r"^[a-f0-9]{64}$")
    currency: StrictStr = Field(pattern=r"^[A-Z]{3}$")
    manager_approval_above: StrictStr = Field(pattern=r"^(0|[1-9][0-9]{0,8})(\.[0-9]{1,2})?$")

    @field_validator("document_version")
    @classmethod
    def clean_version(cls, value):
        if value != value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("Invalid document version")
        return value

    @field_validator("manager_approval_above")
    @classmethod
    def canonical_amount(cls, value):
        return format(Decimal(value), ".2f")

    @property
    def sha256(self):
        return digest(self.model_dump())


def legacy_policy(config) -> ResolutionPolicy:
    """Compatibility contract; no write or implicit migration on reads."""
    return ResolutionPolicy(
        document_key="refund-policy-v2",  # gitleaks:allow -- public document identifier, not a credential
        document_version="2",
        document_sha256=config.get("policy_sha256", ""),
        currency="EUR",
        manager_approval_above="300.00",
    )


def resolve_policy(config) -> ResolutionPolicy:
    try:
        if "resolution_policy" in config:
            return ResolutionPolicy.model_validate(config["resolution_policy"])
        return legacy_policy(config)
    except (TypeError, ValueError) as exc:
        raise ValueError("CLAIM_RESOLUTION_POLICY_INVALID") from exc


def is_legacy_policy(config) -> bool:
    try:
        return resolve_policy(config).sha256 == legacy_policy(config).sha256
    except (TypeError, ValueError):
        return False


def policy_evidence(policy: ResolutionPolicy):
    return {"sha256": policy.sha256, **policy.model_dump()}


def same_proposal(recorded, proposed, config) -> bool:
    """An in-flight legacy proposal survives only unchanged legacy rules.

    A new contract may not silently inherit an approval obtained under another
    contract, even when the resulting amount happens to be identical.
    """
    if not isinstance(recorded, dict):
        return False
    keys = proposed.keys()
    if "resolution_policy" not in recorded:
        if not is_legacy_policy(config):
            return False
        keys = [key for key in keys if key != "resolution_policy"]
    return all(recorded.get(key) == proposed.get(key) for key in keys)
