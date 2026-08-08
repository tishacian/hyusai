"""Skill identity shared by the seeded registry and workspace-defined rows.

A slug is the runtime dispatch key: published Flows carry it in
``config.skill_slug`` and ``resolve()`` turns it into a callable. A workspace
that could mint a seeded slug would do more than collide with the catalog --
:func:`seed_skills_and_capabilities` upserts on ``slug`` alone, so the next
boot would adopt the workspace row, stamp ``is_seeded='Y'`` on it and overwrite
its contract while leaving ``workspace_id`` set. The namespace below removes
that reachability by construction rather than by validation: every seeded slug
is ``[a-z0-9_]+``, so reserving ``.`` makes the two vocabularies disjoint
alphabets instead of two lists someone has to keep comparing.

The workspace segment is the workspace **id**, not its slug, because a
workspace rename must not invalidate the dispatch key already frozen into a
published Flow.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

SkillCallable = Callable[[dict[str, Any], Optional[dict[str, Any]]], Awaitable[dict[str, Any]]]

WORKSPACE_NAMESPACE = "ws"
NAMESPACE_SEPARATOR = "."
WORKSPACE_SLUG_PREFIX = f"{WORKSPACE_NAMESPACE}{NAMESPACE_SEPARATOR}"

# The authored half of a namespaced slug. Deliberately the same alphabet as a
# seeded slug so a workspace name reads like the rest of the catalog; it is the
# prefix, not the local name, that keeps the two apart.
LOCAL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
# Owner ids are ``String(36)`` uuid4 by default, but fixtures and older rows use
# readable identifiers. Anything carrying the separator would make the slug
# ambiguous to parse, so it is refused rather than escaped.
_OWNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,35}$")
_WORKSPACE_SLUG_RE = re.compile(
    rf"^{WORKSPACE_NAMESPACE}\{NAMESPACE_SEPARATOR}"
    r"(?P<owner>[A-Za-z0-9][A-Za-z0-9_-]{0,35})"
    rf"\{NAMESPACE_SEPARATOR}"
    r"(?P<local>[a-z][a-z0-9_]{2,63})$"
)


# Not frozen: exception propagation assigns ``__traceback__``.
@dataclass(slots=True)
class SkillBindingError(ValueError):
    """A Skill identity or runtime binding that must not become executable."""

    code: str
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class WorkspaceSkillSlug:
    workspace_id: str
    local_name: str

    @property
    def slug(self) -> str:
        return NAMESPACE_SEPARATOR.join(
            (WORKSPACE_NAMESPACE, self.workspace_id, self.local_name)
        )


def is_workspace_skill_slug(slug: Any) -> bool:
    """Whether a slug belongs to the workspace namespace, cheaply.

    Called on the run engine's hot path to decide whether a slug can possibly
    need a database lookup, so it must stay a string test.
    """

    return isinstance(slug, str) and slug.startswith(WORKSPACE_SLUG_PREFIX)


def parse_workspace_skill_slug(slug: Any) -> WorkspaceSkillSlug | None:
    """Split a well-formed namespaced slug, or return ``None``."""

    if not isinstance(slug, str):
        return None
    match = _WORKSPACE_SLUG_RE.match(slug)
    if match is None:
        return None
    return WorkspaceSkillSlug(
        workspace_id=match.group("owner"),
        local_name=match.group("local"),
    )


def workspace_skill_slug(*, workspace_id: Any, local_name: Any) -> WorkspaceSkillSlug:
    """Mint the only slug a workspace is allowed to own.

    The owner segment is supplied by the server, never by the request, so an
    admin of one workspace cannot author into another workspace's namespace.
    """

    owner = str(workspace_id or "").strip()
    if not _OWNER_RE.match(owner):
        raise SkillBindingError(
            code="skill_namespace_unavailable",
            message="This workspace has no namespace-safe identifier to author under.",
        )
    local = str(local_name or "").strip().lower()
    if not LOCAL_NAME_RE.match(local):
        raise SkillBindingError(
            code="skill_local_name_invalid",
            message=(
                "A Skill name must be 3 to 64 characters of lowercase letters, "
                "digits and underscores, starting with a letter."
            ),
        )
    return WorkspaceSkillSlug(workspace_id=owner, local_name=local)


__all__ = [
    "LOCAL_NAME_RE",
    "NAMESPACE_SEPARATOR",
    "SkillBindingError",
    "SkillCallable",
    "WORKSPACE_NAMESPACE",
    "WORKSPACE_SLUG_PREFIX",
    "WorkspaceSkillSlug",
    "is_workspace_skill_slug",
    "parse_workspace_skill_slug",
    "workspace_skill_slug",
]
