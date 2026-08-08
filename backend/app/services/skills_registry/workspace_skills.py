"""Resolve the runtime of a workspace-defined Skill from its slug.

Dispatch stays a single string test on the hot path. Because the namespace is
part of the slug, the walker can tell a seeded slug from an authored one without
touching the database, so the seeded catalog keeps paying exactly the queries it
paid before this tranche.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.models.skill import Skill
from app.services.skills_registry.binding import (
    SkillBindingError,
    SkillCallable,
    is_workspace_skill_slug,
    parse_workspace_skill_slug,
)
from app.services.skills_registry.executors import bind_executor


def workspace_skill_callable(
    db: DBSession,
    *,
    workspace_id: str | None,
    slug: str,
    frozen_executor: Mapping[str, Any] | None = None,
) -> SkillCallable | None:
    """Return the verified callable for an authored slug, or ``None``.

    ``None`` means "not an authored slug, use the seeded registry". Every other
    outcome raises: an authored slug that resolves to no row, to another
    workspace's row, or to a binding the verified set rejects must fail here.
    Falling back to the seeded registry would let a deleted or foreign Skill be
    answered by whatever the global catalog happens to hold.

    ``frozen_executor`` is the binding a published execution contract pinned for
    this node. It wins over the live row, and the row is not read at all: the
    point of publishing is that a later catalog edit cannot change what an
    already-published Flow does. The ownership check still runs, because a slug
    naming another workspace is a graph defect regardless of what was frozen.
    """

    if not is_workspace_skill_slug(slug):
        return None
    identity = parse_workspace_skill_slug(slug)
    if identity is None:
        raise SkillBindingError(
            code="skill_slug_malformed",
            message=f"{slug} is not a well-formed workspace Skill slug.",
        )
    if not workspace_id or identity.workspace_id != str(workspace_id):
        raise SkillBindingError(
            code="skill_slug_foreign_workspace",
            message=f"{slug} is not owned by the workspace running it.",
        )
    if frozen_executor is not None:
        return bind_executor(frozen_executor)
    row = (
        db.query(Skill)
        .filter(Skill.slug == slug, Skill.workspace_id == identity.workspace_id)
        .first()
    )
    if row is None:
        raise SkillBindingError(
            code="skill_not_found",
            message=f"{slug} no longer exists in this workspace.",
        )
    return bind_executor(row.executor)


__all__ = ["workspace_skill_callable"]
