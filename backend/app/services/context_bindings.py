"""Tenant-safe Context/System binding resolution.

Object identifiers are never sufficient authority on their own.  Every
binding written by an API or Blueprint and every Context loaded by the Run
engine must resolve through the same workspace-qualified contract.
"""

from __future__ import annotations

from sqlalchemy.orm import Session as DBSession

from app.models.context import Context
from app.models.system import System


class ContextBindingError(ValueError):
    """A requested Context/System binding is absent from the tenant."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def context_in_workspace(
    db: DBSession,
    *,
    workspace_id: str | None,
    context_id: str,
) -> Context:
    row = (
        db.query(Context)
        .filter(
            Context.id == context_id,
            Context.workspace_id == workspace_id,
        )
        .first()
    )
    if row is None:
        raise ContextBindingError(
            "Context must belong to the current workspace",
            code="context_workspace_mismatch",
        )
    return row


def system_in_workspace(
    db: DBSession,
    *,
    workspace_id: str | None,
    system_id: str,
) -> System:
    row = (
        db.query(System)
        .filter(
            System.id == system_id,
            System.workspace_id == workspace_id,
        )
        .first()
    )
    if row is None:
        raise ContextBindingError(
            "System must belong to the current workspace",
            code="system_workspace_mismatch",
        )
    return row


def validate_context_id(
    db: DBSession,
    *,
    workspace_id: str | None,
    context_id: str | None,
) -> Context | None:
    if context_id is None:
        return None
    return context_in_workspace(
        db,
        workspace_id=workspace_id,
        context_id=context_id,
    )


def validate_system_id(
    db: DBSession,
    *,
    workspace_id: str | None,
    system_id: str | None,
) -> System | None:
    if system_id is None:
        return None
    return system_in_workspace(
        db,
        workspace_id=workspace_id,
        system_id=system_id,
    )


__all__ = [
    "ContextBindingError",
    "context_in_workspace",
    "system_in_workspace",
    "validate_context_id",
    "validate_system_id",
]
