"""Shared path-boundary rules for co-installed Workspace Apps.

Routes and API prefixes are hierarchical claims.  A claim owns its exact path
and descendants separated by ``/``; lexically similar sibling paths remain
independent (for example ``/chat`` and ``/chatbot``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.orm import Session as DBSession

WORKSPACE_APP_REQUIRED_UNIQUE_CONSTRAINTS = frozenset(
    {
        (
            "workspace_app_installations",
            "uq_workspace_app_installations_lineage",
            ("workspace_id", "app_id", "id"),
        ),
        (
            "workspace_app_operations",
            "uq_workspace_app_operations_lineage",
            ("workspace_id", "app_id", "installation_id", "id"),
        ),
    }
)
WORKSPACE_APP_REQUIRED_FOREIGN_KEYS = frozenset(
    {
        (
            "workspace_app_operations",
            "fk_workspace_app_operations_installation_lineage",
            ("workspace_id", "app_id", "installation_id"),
            "workspace_app_installations",
            ("workspace_id", "app_id", "id"),
        ),
        (
            "workspace_app_lifecycle_step_receipts",
            "fk_workspace_app_step_receipts_operation_lineage",
            ("workspace_id", "app_id", "installation_id", "operation_id"),
            "workspace_app_operations",
            ("workspace_id", "app_id", "installation_id", "id"),
        ),
    }
)


class WorkspaceAppBoundaryContractError(ValueError):
    """A trusted manifest does not expose a usable authority boundary."""


def workspace_app_relational_integrity_errors(db: DBSession) -> list[str]:
    """Return exact missing tenant-lineage constraints from migration 074."""

    inspector = inspect(db.get_bind())
    tables = {
        table
        for table, *_rest in (
            *WORKSPACE_APP_REQUIRED_UNIQUE_CONSTRAINTS,
            *WORKSPACE_APP_REQUIRED_FOREIGN_KEYS,
        )
    }
    observed_unique = {
        (table, str(row.get("name") or ""), tuple(row.get("column_names") or ()))
        for table in tables
        for row in inspector.get_unique_constraints(table)
    }
    observed_foreign = {
        (
            table,
            str(row.get("name") or ""),
            tuple(row.get("constrained_columns") or ()),
            str(row.get("referred_table") or ""),
            tuple(row.get("referred_columns") or ()),
        )
        for table in tables
        for row in inspector.get_foreign_keys(table)
    }
    return sorted(
        [
            f"unique:{table}.{name}"
            for table, name, columns in WORKSPACE_APP_REQUIRED_UNIQUE_CONSTRAINTS
            if (table, name, columns) not in observed_unique
        ]
        + [
            f"foreign_key:{table}.{name}"
            for table, name, columns, parent, parent_columns in WORKSPACE_APP_REQUIRED_FOREIGN_KEYS
            if (table, name, columns, parent, parent_columns) not in observed_foreign
        ]
    )


def slash_boundary_paths_overlap(left: str, right: str) -> bool:
    """Return whether two canonical paths overlap on a ``/`` boundary."""

    return left == right or left.startswith(f"{right}/") or right.startswith(f"{left}/")


def manifest_api_prefixes(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the complete, canonical API authority declared by a manifest.

    Older manifests derive this boundary from their surfaces.  Invalid or
    empty boundaries fail closed even though compiled manifests are normally
    validated before reaching the lifecycle/runtime services.
    """

    declared = payload.get("api_prefixes")
    if declared is None:
        surfaces = payload.get("surfaces")
        if (
            not isinstance(surfaces, Sequence)
            or isinstance(surfaces, str | bytes)
            or not surfaces
            or any(not isinstance(surface, Mapping) for surface in surfaces)
        ):
            raise WorkspaceAppBoundaryContractError(
                "manifest surfaces do not define an API authority boundary"
            )
        values = [surface.get("api_prefix") for surface in surfaces]
    else:
        if not isinstance(declared, Sequence) or isinstance(declared, str | bytes) or not declared:
            raise WorkspaceAppBoundaryContractError("manifest API authority boundary is invalid")
        values = list(declared)

    if any(
        not isinstance(prefix, str)
        or prefix != prefix.strip()
        or not prefix.startswith("/api/v1/")
        or prefix.endswith("/")
        for prefix in values
    ):
        raise WorkspaceAppBoundaryContractError("manifest API authority boundary is invalid")
    if declared is not None and len(values) != len(set(values)):
        raise WorkspaceAppBoundaryContractError(
            "manifest API authority boundary contains duplicates"
        )
    # Multiple surfaces of one application may intentionally share their
    # single inherited API prefix. They constitute one authority claim.
    return tuple(dict.fromkeys(values))
