"""Help content schema — persona-aware tooltips.

The cockpit ships a self-contained documentation layer: every actionable
UI surface can attach a ``<ck-help [id]="...">`` component that resolves
against this registry. Content is authored in a versioned YAML file so
product writers can iterate without touching Angular.

Personas:
- ``builder``   : assembles Capabilities, Skills, Systems.
- ``operator``  : tunes policies, approves decisions, monitors runs.
- ``executive`` : steers the portfolio (Hypervisor), sets priorities.
"""
from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


Persona = Literal["builder", "operator", "executive"]
Category = Literal["action", "metric", "control", "navigation", "status", "concept"]


class PersonaCopy(BaseModel):
    """Persona-tailored copy for a single help id."""

    summary: str = Field(..., max_length=160, description="<= 160 chars, one sentence.")
    user_story: str = Field(
        ...,
        description='"As a {persona}, I {verb} {object} in order to {outcome}."',
    )
    prerequisites: List[str] = Field(default_factory=list)
    related_actions: List[str] = Field(
        default_factory=list,
        description="help_ids of neighbouring actions the persona typically chains with.",
    )


class HelpContent(BaseModel):
    """One entry in the help registry — keyed by ``id``."""

    id: str = Field(..., description="Namespaced id, e.g. 'hypervisor.balance-sheet.scale-capability'.")
    title: str
    category: Category
    by_persona: Dict[Persona, PersonaCopy]
    learn_more: Optional[str] = Field(
        default=None,
        description="Anchor to docs/mental-model.md (e.g. '#s-23-steering').",
    )


class HelpContentIndex(BaseModel):
    """Index response for ``GET /help-content``."""

    version: str
    personas: List[Persona]
    items: List[HelpContent]
