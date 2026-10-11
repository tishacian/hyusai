"""Tenant-safe catalog lookup helpers for idempotent seed scripts."""
from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy.orm import Session as DBSession

from app.models.capability import Capability
from app.models.workspace import Workspace
from app.services.catalog_visibility import capability_is_visible, workspace_catalog_policy


class SeedCatalogCollisionError(RuntimeError):
    """A globally unique slug already belongs to a different catalog owner."""


class SeedWorkspaceBoundaryError(RuntimeError):
    """A demo seed was pointed at a workspace it does not already own."""


def require_showcase_workspace_for_seed(workspace: Workspace) -> None:
    """Require the server-owned structural marker before mutating an existing tenant.

    Display names and slugs are intentionally irrelevant: a CLI override must
    never turn Andritz or another workspace into Showcase by coincidence.
    """

    settings = workspace.settings if isinstance(workspace.settings, Mapping) else {}
    if settings.get("showcase_seed") is not True:
        raise SeedWorkspaceBoundaryError(
            "target workspace is not structurally owned by the Showcase seed"
        )


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
    "SeedWorkspaceBoundaryError",
    "owned_capability_for_seed",
    "require_showcase_workspace_for_seed",
    "visible_capability_for_seed",
]
