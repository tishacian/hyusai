"""Canonical Skill binding resolution for authored Flow nodes.

Historical Flow shapes can carry the Skill slug in several locations.  Every
acceptance and execution path must interpret those locations identically;
otherwise a node can be published without a frozen Skill contract and still
execute a mutable registry binding at runtime.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class FlowSkillBinding:
    skill_id: str | None
    skill_slug: str | None


# Not frozen: exception propagation assigns ``__traceback__``.
@dataclass(slots=True)
class FlowSkillBindingError(ValueError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def _identity(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalised = value.strip()
    return normalised or None


def resolve_flow_skill_binding(node: Mapping[str, Any]) -> FlowSkillBinding:
    """Return one canonical Skill id/slug pair or fail closed.

    Supported slug locations are ``config.skill_slug``,
    ``config.skill.slug``, ``data.bound_skill_slug`` and
    ``data.skill_slug``.  Multiple representations are allowed only when they
    name the same slug. AgentLoop also accepts ``config.decide_skill`` and
    defaults to ``decide_next_v1``, matching its runtime. A Skill id is never
    executable by itself because the runtime dispatch key is the slug.
    """

    raw_config = node.get("config")
    config = raw_config if isinstance(raw_config, Mapping) else {}
    raw_data = node.get("data")
    data = raw_data if isinstance(raw_data, Mapping) else {}
    raw_nested_skill = config.get("skill")
    nested_skill = raw_nested_skill if isinstance(raw_nested_skill, Mapping) else {}

    is_agent_loop = node.get("kind") == "agent_loop"
    skill_id = _identity(config.get("skill_id"))
    slug_candidates = {
        slug
        for slug in (
            _identity(config.get("skill_slug")),
            _identity(config.get("decide_skill")) if is_agent_loop else None,
            _identity(nested_skill.get("slug")),
            _identity(data.get("bound_skill_slug")),
            _identity(data.get("skill_slug")),
        )
        if slug is not None
    }
    if len(slug_candidates) > 1:
        raise FlowSkillBindingError(
            code="skill_binding_conflict",
            message="Skill slug representations disagree for this Flow node.",
        )

    skill_slug = next(iter(slug_candidates), "decide_next_v1" if is_agent_loop else None)
    if skill_id is not None and skill_slug is None:
        raise FlowSkillBindingError(
            code="skill_slug_required",
            message="A Flow Skill binding with skill_id must also declare its skill_slug.",
        )
    return FlowSkillBinding(skill_id=skill_id, skill_slug=skill_slug)


__all__ = [
    "FlowSkillBinding",
    "FlowSkillBindingError",
    "resolve_flow_skill_binding",
]
