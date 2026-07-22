"""Tenant-safe catalog lookup helpers for idempotent seed scripts."""
from __future__ import annotations

from sqlalchemy.orm import Session as DBSession

from app.models.capability import Capability
from app.models.workspace import Workspace
from app.services.catalog_visibility import capability_is_visible, workspace_catalog_policy


class SeedCatalogCollisionError(RuntimeError):
    """A globally unique slug already belongs to a different catalog owner."""


def owned_capability_for_seed(
    db: DBSession,
    *,
    workspace: Workspace,
    slug: str,
) -> Capability | None:
    """Return an exactly-owned row; never adopt a global or foreign row."""

    capability = db.query(Capability).filter(Capability.slug == slug).one_or_none()
    if capability is None:
        return None
    if capability.workspace_id != workspace.id:
        owner = "global" if capability.workspace_id is None else "foreign_workspace"
        raise SeedCatalogCollisionError(
            f"Capability slug {slug!r} is already owned by {owner}; seed refused"
        )
    return capability


def visible_capability_for_seed(
    db: DBSession,
    *,
    workspace: Workspace,
    slug: str,
) -> Capability | None:
    """Resolve a reusable binding through the real workspace catalog policy."""

    capability = db.query(Capability).filter(Capability.slug == slug).one_or_none()
    if capability is None:
        return None
    if not capability_is_visible(
        capability,
        workspace,
        workspace_catalog_policy(workspace),
    ):
        raise SeedCatalogCollisionError(
            f"Capability slug {slug!r} is not visible in the target workspace; seed refused"
        )
    return capability


__all__ = [
    "SeedCatalogCollisionError",
    "owned_capability_for_seed",
    "visible_capability_for_seed",
]
