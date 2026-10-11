"""Immutable, secret-free execution evidence for ``SkillInvocation`` rows.

The mutable Skill catalogue is useful for current configuration, but it cannot
truthfully describe a historical invocation after a Skill is edited.  This
module resolves the workspace-visible Skill at invocation creation and copies
only a strict identity allowlist plus SHA-256 digests of executable contracts.
Raw schemas, execution configuration, pricing, credentials, and arbitrary
metadata are never persisted in the snapshot.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from app.models.skill import Skill

SNAPSHOT_SCHEMA_VERSION = 1
_SAFE_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]*$")
_USAGE_PRICING_UNITS = frozenset(
    {
        "per_1k_tokens",
        "per_1000_source_words",
        "per_char",
        "per_day",
        "per_minute",
        "per_source_day",
    }
)


@dataclass(frozen=True)
class SkillExecutionEvidence:
    """Resolved persistence fields for one new invocation."""

    skill_id: str | None
    skill_slug: str | None
    execution_snapshot: dict[str, Any]


@dataclass(frozen=True)
class SkillInvocationCostEvidence:
    """Truthful cost value and its secret-free calculation evidence.

    ``cost_measured`` deliberately includes a cost calculated from an
    explicitly configured catalogue tariff.  Missing, malformed, synthetic or
    unresolved prices keep the database default value harmless by setting the
    flag to ``False``.
    """

    cost: float
    cost_measured: bool
    evidence: dict[str, Any]


def resolve_skill_invocation_cost(
    db: DBSession,
    *,
    workspace_id: str | None,
    skill_id: str | None,
    skill_slug: str | None,
    quantity: float | None = None,
) -> SkillInvocationCostEvidence:
    """Resolve one invocation cost from an identifiable catalogue tariff.

    Resolution is intentionally anchored to the immutable Skill binding
    captured for the invocation.  An unresolved snapshot (``skill_id=None``)
    is never rebound by slug here, and an incomplete tariff never becomes a
    measured zero.  Only a positive allowlist of non-secret pricing fields is
    emitted in ``evidence``; the mutable raw pricing object is never copied.
    """

    if not skill_id:
        return _unmeasured_cost("skill_unresolved")

    skill, reason = _resolve_visible_skill(
        db,
        workspace_id=workspace_id,
        skill_id=skill_id,
        skill_slug=skill_slug,
    )
    if skill is None:
        return _unmeasured_cost(reason)

    pricing = skill.pricing
    if not isinstance(pricing, dict):
        return _unmeasured_cost("pricing_not_configured")
    if "unit_price" not in pricing:
        return _unmeasured_cost("unit_price_not_configured")

    unit = _safe_identity(pricing.get("unit"), maximum=40)
    currency = _safe_identity(pricing.get("currency"), maximum=12)
    if unit is None or currency is None:
        return _unmeasured_cost("pricing_identity_incomplete")

    if quantity is None and unit in _USAGE_PRICING_UNITS:
        return _unmeasured_cost("pricing_quantity_not_measured")

    try:
        unit_price = float(pricing["unit_price"])
        normalized_quantity = 1.0 if quantity is None else float(quantity)
    except (TypeError, ValueError):
        return _unmeasured_cost("pricing_value_invalid")
    if (
        isinstance(pricing["unit_price"], bool)
        or isinstance(quantity, bool)
        or not math.isfinite(unit_price)
        or not math.isfinite(normalized_quantity)
        or unit_price < 0
        or normalized_quantity < 0
    ):
        return _unmeasured_cost("pricing_value_invalid")

    tariff = {
        "currency": currency.upper(),
        "unit": unit,
        "unit_price": unit_price,
    }
    return SkillInvocationCostEvidence(
        cost=round(unit_price * normalized_quantity, 6),
        cost_measured=True,
        evidence={
            "schema_version": 1,
            "state": "calculated",
            "method": "catalog_unit_price",
            "source": f"skill_catalog:{skill.id}:pricing",
            "pricing_sha256": _canonical_sha256(tariff),
            "currency": tariff["currency"],
            "unit": unit,
            "quantity": normalized_quantity,
        },
    )


def capture_skill_execution_evidence(
    db: DBSession,
    *,
    workspace_id: str | None,
    skill_id: str | None = None,
    skill_slug: str | None = None,
) -> SkillExecutionEvidence:
    """Resolve and snapshot a Skill without copying mutable contract bodies.

    An explicit id is authoritative.  If it is absent, slug resolution prefers
    a workspace row over a global row.  A stale id or an id/slug mismatch stays
    unresolved instead of silently rebinding the invocation to another Skill.
    """

    requested_id = _safe_identity(skill_id, maximum=36)
    requested_slug = _safe_identity(skill_slug, maximum=160)
    skill, reason = _resolve_visible_skill(
        db,
        workspace_id=workspace_id,
        skill_id=skill_id,
        skill_slug=skill_slug,
    )
    if skill is None:
        requested = {
            key: value
            for key, value in {
                "id": requested_id,
                "slug": requested_slug,
            }.items()
            if value is not None
        }
        snapshot: dict[str, Any] = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "resolution": "unresolved",
            "resolution_reason": reason,
        }
        if requested:
            snapshot["requested_skill"] = requested
        return SkillExecutionEvidence(
            # An unresolved request is evidence, not a canonical catalogue
            # binding.  Keep the requested id inside the immutable envelope so
            # readers cannot accidentally treat it as a resolved Skill FK.
            skill_id=None,
            skill_slug=requested_slug,
            execution_snapshot=snapshot,
        )

    identity = {
        "id": _required_identity(skill.id, maximum=36),
        "slug": _required_identity(skill.slug, maximum=160),
        "scope": "workspace" if skill.workspace_id is not None else "global",
    }
    version = _safe_identity(skill.version, maximum=20)
    provider = _safe_identity(skill.provider, maximum=80)
    certification = _safe_identity(skill.certification_level, maximum=20)
    if version is not None:
        identity["version"] = version
    if provider is not None:
        identity["provider"] = provider
    if certification is not None:
        identity["certification_level"] = certification

    return SkillExecutionEvidence(
        skill_id=skill.id,
        skill_slug=skill.slug,
        execution_snapshot={
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "resolution": "resolved",
            "skill": identity,
            "digests": {
                "input_contract_sha256": _canonical_sha256(skill.input_schema),
                "output_contract_sha256": _canonical_sha256(skill.output_schema),
                "execution_sha256": _canonical_sha256(skill.execution),
            },
        },
    )


def _resolve_visible_skill(
    db: DBSession,
    *,
    workspace_id: str | None,
    skill_id: str | None,
    skill_slug: str | None,
) -> tuple[Skill | None, str]:
    visibility = (
        Skill.workspace_id.is_(None)
        if workspace_id is None
        else or_(Skill.workspace_id == workspace_id, Skill.workspace_id.is_(None))
    )

    if skill_id:
        skill = (
            db.query(Skill)
            .filter(
                Skill.id == skill_id,
                visibility,
            )
            .first()
        )
        if skill is None:
            return None, "skill_id_not_visible"
        if skill_slug and skill.slug != skill_slug:
            return None, "skill_identity_mismatch"
        return skill, "resolved_by_id"

    if not skill_slug:
        return None, "skill_identity_missing"

    candidates = (
        db.query(Skill)
        .filter(
            Skill.slug == skill_slug,
            visibility,
        )
        .all()
    )
    if not candidates:
        return None, "skill_slug_not_visible"
    workspace_candidates = [
        item for item in candidates if workspace_id and item.workspace_id == workspace_id
    ]
    preferred = workspace_candidates or [
        item for item in candidates if item.workspace_id is None
    ]
    if len(preferred) != 1:
        return None, "skill_slug_ambiguous"
    return preferred[0], "resolved_by_slug"


def _canonical_sha256(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _unmeasured_cost(reason: str) -> SkillInvocationCostEvidence:
    return SkillInvocationCostEvidence(
        cost=0.0,
        cost_measured=False,
        evidence={
            "schema_version": 1,
            "state": "not_measured",
            "reason": reason,
        },
    )


def _safe_identity(value: Any, *, maximum: int) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized or len(normalized) > maximum or not _SAFE_IDENTITY.fullmatch(normalized):
        return None
    return normalized


def _required_identity(value: Any, *, maximum: int) -> str:
    normalized = _safe_identity(value, maximum=maximum)
    if normalized is None:
        # Database constraints already require these fields.  Refusing an
        # unsafe catalogue identity is safer than persisting it in evidence.
        raise ValueError("resolved Skill contains a non-canonical identity")
    return normalized
