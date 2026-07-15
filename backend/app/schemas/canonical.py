"""Canonical schemas — the single source of truth for shared contracts.

Every router that deals with Outcomes, Decisions, ControlPlane vectors or
runtime status MUST import from here rather than redeclaring fields. This
guarantees vocabulary consistency across `/systems`, `/runs`, `/hypervisor`,
`/control-plane`, `/steering`, `/skills`.

Mental model references:
- Outcome & DecisionUnit: §22.3, §24.1
- ControlPlaneVector: §23.8, §36.3
- PolicyScope: §21.4, §25.2
- ExecutionMode: §20.1–§20.5
- RuntimeStatus: `docs/skills-runtime.md`
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# Enums — exported as string-enums so FastAPI / SQLAlchemy serialize cleanly.
# ---------------------------------------------------------------------------
class DecisionState(str, Enum):
    """Canonical state machine for a Decision record.

    Transitions:
        proposed → accepted
        proposed → rejected
        accepted → applied
    All other transitions are invalid and must be rejected by the router.
    """

    proposed = "proposed"
    accepted = "accepted"
    rejected = "rejected"
    applied = "applied"


class PolicyScope(str, Enum):
    portfolio = "portfolio"
    capability = "capability"
    system = "system"


class ExecutionMode(str, Enum):
    real_time_decision = "real_time_decision"
    batch_processing = "batch_processing"
    event_driven_automation = "event_driven_automation"
    continuous_monitoring = "continuous_monitoring"
    human_augmented = "human_augmented"


class RuntimeStatus(str, Enum):
    bound = "bound"
    stub = "stub"
    unbound = "unbound"
    catalog_only = "catalog_only"


class ValueSource(str, Enum):
    auto = "auto"
    operator = "operator"
    unset = "unset"


# ---------------------------------------------------------------------------
# Outcome & DecisionUnit — the unit-of-value contract (§22.3).
# ---------------------------------------------------------------------------
class Outcome(BaseModel):
    """Canonical outcome produced by a Run.

    All four metrics are optional at the schema level so the UI can render
    partial outcomes while the run is in flight, but a completed Run MUST
    eventually carry the four of them (or `value_source='unset'` when no ROI
    model is declared on the Capability).
    """

    cost: Optional[float] = Field(
        default=None,
        description="Internal cost in the workspace's currency (cost_internal on Run).",
    )
    value: Optional[float] = Field(
        default=None,
        description="Estimated business value; see `value_source` for provenance.",
    )
    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Aggregated confidence score in [0, 1].",
    )
    efficiency: Optional[float] = Field(
        default=None,
        description="(value × confidence) / (cost × time). Higher is better.",
    )
    value_source: ValueSource = ValueSource.unset


class DecisionUnit(BaseModel):
    """Atomic unit exchanged between Run viewer, System viewer, Capability
    drill-down and Hypervisor. Mental model §24.1.
    """

    decision_id: str
    outcome: Outcome
    context: dict[str, Any] = Field(default_factory=dict)
    run_id: Optional[str] = None


# ---------------------------------------------------------------------------
# ControlPlaneVector — the canonical 4-lever pilot (§23.8).
# ---------------------------------------------------------------------------
class ControlPlaneVector(BaseModel):
    """The canonical cockpit vector.

    All four axes live in [0, 1]. Any legacy shortcut (cost_factor,
    value_factor, latency_factor) is accepted by routers for backward-compat
    but is NOT part of the canonical contract and MUST NOT be emitted by new
    frontend code.
    """

    resource: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    velocity: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    autonomy: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    risk_tolerance: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    def as_dict(self) -> dict[str, float]:
        return {k: v for k, v in self.model_dump().items() if v is not None}


# ---------------------------------------------------------------------------
# ExecutionProfile — the SLA + durability bundle attached to ExecutionMode.
# ---------------------------------------------------------------------------
class ExecutionProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latency_target_ms: Optional[int] = None
    max_runtime_s: Optional[int] = None
    checkpointing: bool = False
    replay_safe: bool = False
    retry_budget: Literal["none", "bounded", "unbounded"] = "bounded"
    pricing_unit: Optional[str] = None


# ---------------------------------------------------------------------------
# Policy targeting helper — enforces the invariant target_id=null ⇔ portfolio.
# ---------------------------------------------------------------------------
class PolicyTarget(BaseModel):
    scope: PolicyScope = PolicyScope.portfolio
    target_id: Optional[str] = None

    @model_validator(mode="after")
    def _target_required_for_non_portfolio(self) -> "PolicyTarget":
        if self.scope == PolicyScope.portfolio and self.target_id is not None:
            raise ValueError("target_id must be null for scope=portfolio")
        if self.scope != PolicyScope.portfolio and not self.target_id:
            raise ValueError(f"target_id required for scope={self.scope.value}")
        return self


# ---------------------------------------------------------------------------
# Runtime status listings — used by skills / apps / connectors.
# ---------------------------------------------------------------------------
class RuntimeStatusReport(BaseModel):
    """Uniform payload for any surface that advertises runtime-backed items."""

    id: str
    status: RuntimeStatus
    reason: Optional[str] = None
    version: Optional[str] = None
    dependencies: list[str] = Field(default_factory=list)
