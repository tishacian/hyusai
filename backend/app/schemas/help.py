"""Help content schema — persona-aware, bilingual tooltips.

The cockpit ships a self-contained documentation layer: every actionable
UI surface can attach a ``<ck-help [id]="...">`` component that resolves
against this registry. Content is authored in a versioned YAML file so
product writers can iterate without touching Angular.

Personas:
- ``builder``   : assembles Capabilities, Skills, Systems.
- ``operator``  : tunes policies, approves decisions, monitors runs.
- ``executive`` : steers the portfolio (Hypervisor), sets priorities.

Languages:
- ``en`` : primary (the app is English-first).
- ``fr`` : secondary (preserved for francophone operators).

Textual fields (`summary`, `user_story`, each item in `prerequisites`)
are always a ``Dict[str, str]`` mapping language code → text. Strings
found in the YAML are transparently wrapped as ``{"en": value}`` by the
loader so legacy entries keep working.
"""
from __future__ import annotations

from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator


Persona = Literal["builder", "operator", "executive"]
Category = Literal["action", "metric", "control", "navigation", "status", "concept"]
Language = Literal["en", "fr"]

LocalizedText = Dict[str, str]


def _normalize_localized(value: Union[str, Dict[str, str]]) -> Dict[str, str]:
    """Accept plain strings (treated as English) or ``{en, fr, ...}`` dicts."""
    if isinstance(value, str):
        return {"en": value}
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    raise TypeError(f"localized text must be str or dict, got {type(value).__name__}")


class PersonaCopy(BaseModel):
    """Persona-tailored copy for a single help id.

    Every textual field is stored as a ``{lang: text}`` dict so the
    frontend can resolve against the active UI language with graceful
    fallback (``en`` first, then the first available locale).
    """

    summary: LocalizedText = Field(
        ...,
        description="<= 160 chars per locale, one sentence.",
    )
    user_story: LocalizedText = Field(
        ...,
        description='"As a {persona}, I {verb} {object} in order to {outcome}." per locale.',
    )
    prerequisites: List[LocalizedText] = Field(default_factory=list)
    related_actions: List[str] = Field(
        default_factory=list,
        description="help_ids of neighbouring actions the persona typically chains with.",
    )

    @field_validator("summary", "user_story", mode="before")
    @classmethod
    def _coerce_text(cls, value):  # noqa: ANN001
        return _normalize_localized(value)

    @field_validator("prerequisites", mode="before")
    @classmethod
    def _coerce_prereqs(cls, value):  # noqa: ANN001
        if not value:
            return []
        return [_normalize_localized(v) for v in value]


class HelpContent(BaseModel):
    """One entry in the help registry — keyed by ``id``."""

    id: str = Field(..., description="Namespaced id, e.g. 'hypervisor.balance-sheet.scale-capability'.")
    title: LocalizedText = Field(..., description="Per-locale display title.")
    category: Category
    by_persona: Dict[Persona, PersonaCopy]
    learn_more: Optional[str] = Field(
        default=None,
        description="Anchor to docs/mental-model.md (e.g. '#s-23-steering').",
    )

    @field_validator("title", mode="before")
    @classmethod
    def _coerce_title(cls, value):  # noqa: ANN001
        return _normalize_localized(value)


class HelpContentIndex(BaseModel):
    """Index response for ``GET /help-content``."""

    version: str
    personas: List[Persona]
    languages: List[Language] = Field(
        default_factory=lambda: ["en", "fr"],
        description="Locales for which copy is authored.",
    )
    items: List[HelpContent]
