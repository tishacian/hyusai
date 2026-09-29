"""Access decisions for workspace knowledge collections."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session as DBSession

from app.core.iam.roles import WORKSPACE_VIEWER, is_admin_template, normalize_role_template
from app.models.knowledge_collection import KnowledgeCollection
from app.models.workspace import Workspace, WorkspaceMember

_ACTION_FIELDS = ("read", "write")
_PRINCIPAL_PREFIXES = ("role:", "group:", "user:")


def normalize_collection_access(value: Any) -> dict[str, list[str]] | None:
    """Return a canonical ACL, or ``None`` for the legacy open collection."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Collection access must be an object")

    normalized: dict[str, list[str]] = {}
    for action in _ACTION_FIELDS:
        if action not in value:
            continue
        raw = value.get(action)
        if raw is None:
            raw = []
        if not isinstance(raw, (list, tuple, set)):
            raise ValueError(f"Collection {action} access must be a list")
        principals: list[str] = []
        for item in raw:
            principal = str(item or "").strip()
            if not principal or not principal.startswith(_PRINCIPAL_PREFIXES):
                raise ValueError(f"Invalid collection principal: {item!r}")
            if len(principal.split(":", 1)[1]) == 0:
                raise ValueError(f"Invalid collection principal: {item!r}")
            if principal not in principals:
                principals.append(principal)
        normalized[action] = principals
    return normalized


def _member_principals(member: WorkspaceMember | None) -> set[str]:
    if member is None:
        return set()
    role = normalize_role_template(member.role_template, member.role)
    principals = {f"role:{role}", f"role:{member.role or ''}"}
    labels = member.custom_labels if isinstance(member.custom_labels, list) else []
    principals.update(f"group:{label}" for label in labels if str(label or "").strip())
    if member.user_id:
        principals.add(f"user:{member.user_id}")
    return {item for item in principals if item.rstrip(":")}


def _is_admin(member: WorkspaceMember | None) -> bool:
    return bool(member and is_admin_template(member.role_template, member.role))


def can_read_collection(member: WorkspaceMember | None, collection: KnowledgeCollection) -> bool:
    if _is_admin(member):
        return True
    access = normalize_collection_access(collection.access)
    if access is None:
        return member is not None
    if member is None:
        return False
    principals = _member_principals(member)
    return any(item in principals for item in access.get("read", []))


def can_write_collection(member: WorkspaceMember | None, collection: KnowledgeCollection) -> bool:
    if _is_admin(member):
        return True
    access = normalize_collection_access(collection.access)
    if access is None:
        return member is not None and normalize_role_template(
            member.role_template, member.role
        ) != WORKSPACE_VIEWER
    if member is None:
        return False
    role = normalize_role_template(member.role_template, member.role)
    if role == WORKSPACE_VIEWER:
        return False
    principals = _member_principals(member)
    return any(item in principals for item in access.get("write", []))


def get_membership(
    db: DBSession, *, workspace: Workspace, user_id: str | None
) -> WorkspaceMember | None:
    if not user_id:
        return None
    return (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.workspace_id == workspace.id,
        )
        .first()
    )


def require_read_collection(
    db: DBSession, *, workspace: Workspace, user_id: str | None, collection: KnowledgeCollection
) -> None:
    if can_read_collection(get_membership(db, workspace=workspace, user_id=user_id), collection):
        return
    raise HTTPException(status_code=403, detail={"code": "COLLECTION_READ_DENIED"})


def require_write_collection(
    db: DBSession, *, workspace: Workspace, user_id: str | None, collection: KnowledgeCollection
) -> None:
    if can_write_collection(get_membership(db, workspace=workspace, user_id=user_id), collection):
        return
    raise HTTPException(status_code=403, detail={"code": "COLLECTION_WRITE_DENIED"})


def require_named_collection_read(
    db: DBSession, *, workspace: Workspace, user_id: str | None, collection_ref: str
) -> KnowledgeCollection | None:
    row = (
        db.query(KnowledgeCollection)
        .filter(
            KnowledgeCollection.workspace_id == workspace.id,
            (KnowledgeCollection.slug == collection_ref)
            | (KnowledgeCollection.id == collection_ref),
        )
        .first()
    )
    if row is not None:
        require_read_collection(db, workspace=workspace, user_id=user_id, collection=row)
    return row


def require_named_collection_write(
    db: DBSession, *, workspace: Workspace, user_id: str | None, collection_ref: str
) -> KnowledgeCollection | None:
    member = get_membership(db, workspace=workspace, user_id=user_id)
    role = normalize_role_template(member.role_template, member.role) if member else None
    if member and role == WORKSPACE_VIEWER:
        raise HTTPException(status_code=403, detail={"code": "COLLECTION_WRITE_DENIED"})
    row = (
        db.query(KnowledgeCollection)
        .filter(
            KnowledgeCollection.workspace_id == workspace.id,
            (KnowledgeCollection.slug == collection_ref)
            | (KnowledgeCollection.id == collection_ref),
        )
        .first()
    )
    if row is not None and not can_write_collection(member, row):
        raise HTTPException(status_code=403, detail={"code": "COLLECTION_WRITE_DENIED"})
    return row


def collection_permissions(
    db: DBSession, *, workspace: Workspace, user_id: str | None, collection: KnowledgeCollection
) -> dict[str, bool]:
    member = get_membership(db, workspace=workspace, user_id=user_id)
    return collection_permissions_for_member(member, collection)


def collection_permissions_for_member(
    member: WorkspaceMember | None, collection: KnowledgeCollection
) -> dict[str, bool]:
    return {
        "can_read": can_read_collection(member, collection),
        "can_write": can_write_collection(member, collection),
        "can_manage": _is_admin(member),
    }
