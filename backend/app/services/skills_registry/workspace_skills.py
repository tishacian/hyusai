"""Resolve the runtime of a workspace-defined Skill from its slug.

Dispatch stays a single string test on the hot path. Because the namespace is
part of the slug, the walker can tell a seeded slug from an authored one without
touching the database, so the seeded catalog keeps paying exactly the queries it
paid before this tranche.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
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


def workspace_skill_purposes(
    db: DBSession, *, workspace_id: str | None, slugs: Iterable[str]
) -> dict[str, str]:
    """What each authored slug in ``slugs`` is for, in its own catalog words.

    An agent choosing between skills is given a slug and a purpose. Seeded slugs
    have their purpose written into the loop's static table, but an authored one
    is named after the thing it wraps — ``ws.<id>.predict_churn_radar`` — and a
    slug repeated back as its own description tells a planner nothing about when
    to reach for it. The row already carries the sentence the catalog card shows
    a human; this hands the same sentence to the model.

    Foreign or missing slugs are simply absent from the result: this feeds a
    prompt, and the authority over what may actually run is the mandate view,
    which is computed separately and does not consult this.
    """

    wanted = {
        slug
        for slug in (str(item or "").strip() for item in slugs)
        if slug and is_workspace_skill_slug(slug)
    }
    if not wanted or not workspace_id:
        return {}
    rows = (
        db.query(Skill.slug, Skill.name, Skill.description)
        .filter(Skill.slug.in_(sorted(wanted)), Skill.workspace_id == str(workspace_id))
        .all()
    )
    described: dict[str, str] = {}
    for slug, name, description in rows:
        # Name first: a description opens with what the model does, and the
        # planner also needs to know which model, which is what the name says.
        sentence = " — ".join(part for part in (name, description) if part)
        if sentence.strip():
            described[str(slug)] = sentence.strip()
    return described


__all__ = ["workspace_skill_callable", "workspace_skill_purposes"]
