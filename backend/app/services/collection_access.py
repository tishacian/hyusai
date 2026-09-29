"""Per-collection access for workspace knowledge collections (L35).

The policy lives on ``KnowledgeCollection.access``:

* ``None`` keeps the collection open, as every collection was before L35:
  every workspace member reads it and every role except viewer adds documents.
* ``{"read": [...], "write": [...]}`` restricts an action to the listed
  principals. A missing (or ``None``) action keeps its open default; an empty
  list leaves it to workspace admins.

Principals are ``role:<workspace role template>``, ``group:<member label>``
(the admin-managed ``WorkspaceMember.custom_labels``), ``user:<user id>`` and
``system:<system id>`` (read only, for runs no user launched).

Rules applied everywhere:

* Workspace admins and owners read and write every collection. They administer
  the policy and could grant themselves any access, so hiding content from
  them would only slow down support and deletion, never protect anything.
* Writing requires reading, and viewers never write.
* Without a member (a scheduled automation, a retrieval that carries no
  identity) only open collections, and collections granted to the System that
  runs, are readable.
* A collection a member cannot read does not exist for them: 404.

Retrieval runs outside the request that authorised it (Celery deep retrieval,
skill runs), so the member travels as a signed identity in the retrieval
request (``collection_identity``). A request without a valid identity is
treated as a service: restricted collections are excluded, never "everything".
"""
from __future__ import annotations

import hashlib
import hmac
import re
import time
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session as DBSession

from app.core.iam.roles import (
    ADMIN_ROLE_TEMPLATES,
    CANONICAL_WORKSPACE_ROLES,
    WORKSPACE_VIEWER,
    normalize_role_template,
)
from app.models.knowledge_collection import KnowledgeCollection
from app.models.workspace import Workspace, WorkspaceMember

_ACTION_FIELDS = ("read", "write")
_PRINCIPAL_KINDS = ("role", "group", "user", "system")
_MAX_PRINCIPALS = 200

# Server-owned retrieval keys. Client bodies must never be able to set them.
RETRIEVAL_IDENTITY_KEY = "collection_identity"
_CLIENT_FORBIDDEN_RETRIEVAL_KEYS = (RETRIEVAL_IDENTITY_KEY, "accessible_collection_refs")
_EVIDENCE_COLLECTION_KEYS = ("collection", "collection_name", "collection_slug", "source_collection")

COLLECTION_NOT_FOUND = "Collection not found"


# ---------------------------------------------------------------- principals


@dataclass(frozen=True)
class CollectionPrincipal:
    """Who asks: a workspace member, or a service (no member)."""

    workspace_id: str | None = None
    user_id: str | None = None
    role: str | None = None  # canonical role template; None when not a member
    labels: frozenset[str] = field(default_factory=frozenset)
    system_id: str | None = None

    @property
    def is_member(self) -> bool:
        return self.role is not None

    @property
    def is_admin(self) -> bool:
        return self.role in ADMIN_ROLE_TEMPLATES

    @property
    def tokens(self) -> frozenset[str]:
        tokens: set[str] = set()
        if self.role:
            # Only the canonical template: the legacy ``role`` column maps a
            # viewer to ``member`` and must never grant anything.
            tokens.add(f"role:{self.role}")
        tokens.update(f"group:{label}" for label in self.labels)
        if self.user_id and self.is_member:
            tokens.add(f"user:{self.user_id}")
        if self.system_id:
            tokens.add(f"system:{self.system_id}")
        return frozenset(tokens)


SERVICE_PRINCIPAL = CollectionPrincipal()


def principal_for_member(
    member: WorkspaceMember | None,
    *,
    workspace_id: str | None = None,
    system_id: str | None = None,
) -> CollectionPrincipal:
    if member is None:
        return CollectionPrincipal(workspace_id=workspace_id, system_id=system_id)
    labels = member.custom_labels if isinstance(member.custom_labels, list) else []
    return CollectionPrincipal(
        workspace_id=member.workspace_id or workspace_id,
        user_id=member.user_id,
        role=normalize_role_template(member.role_template, member.role),
        labels=frozenset(str(label).strip() for label in labels if str(label or "").strip()),
        system_id=system_id,
    )


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


def load_principal(
    db: DBSession,
    *,
    workspace_id: str,
    user_id: str | None,
    system_id: str | None = None,
) -> CollectionPrincipal:
    """One query: the member's principal, or a service principal."""
    member = None
    if user_id:
        member = (
            db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.user_id == user_id,
                WorkspaceMember.workspace_id == workspace_id,
            )
            .first()
        )
    return principal_for_member(member, workspace_id=workspace_id, system_id=system_id)


def _principal(subject: Any) -> CollectionPrincipal:
    if isinstance(subject, CollectionPrincipal):
        return subject
    if isinstance(subject, WorkspaceMember):
        return principal_for_member(subject)
    return SERVICE_PRINCIPAL


# ------------------------------------------------------------------- policy


def normalize_collection_access(value: Any) -> dict[str, list[str]] | None:
    """Return a canonical policy, or ``None`` for an open collection.

    Raises ``ValueError`` for a malformed policy (the API answers 422).
    """
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("Collection access must be an object")
    unknown = set(value) - set(_ACTION_FIELDS)
    if unknown:
        raise ValueError(f"Unknown collection access keys: {sorted(unknown)}")

    normalized: dict[str, list[str]] = {}
    for action in _ACTION_FIELDS:
        raw = value.get(action)
        if raw is None:
            continue
        if not isinstance(raw, (list, tuple, set)):
            raise ValueError(f"Collection {action} access must be a list")
        if len(raw) > _MAX_PRINCIPALS:
            raise ValueError(f"Collection {action} access lists too many principals")
        principals: list[str] = []
        for item in raw:
            principal = str(item or "").strip()
            kind, _, ident = principal.partition(":")
            if kind not in _PRINCIPAL_KINDS or not ident.strip():
                raise ValueError(f"Invalid collection principal: {item!r}")
            if kind == "role" and ident not in CANONICAL_WORKSPACE_ROLES:
                raise ValueError(f"Unknown workspace role: {ident!r}")
            if kind == "system" and action == "write":
                raise ValueError("A System can only be granted read access")
            if principal not in principals:
                principals.append(principal)
        normalized[action] = principals
    return normalized or None


def _policy(collection: Any) -> dict[str, list[str]] | None:
    try:
        return normalize_collection_access(getattr(collection, "access", None))
    except ValueError:
        # A policy this code cannot read is treated as admin-only.
        return {"read": [], "write": []}


def can_read_collection(subject: Any, collection: Any) -> bool:
    principal = _principal(subject)
    if principal.is_admin:
        return True
    readers = (_policy(collection) or {}).get("read")
    if readers is None:
        return True
    return bool(principal.tokens.intersection(readers))


def can_write_collection(subject: Any, collection: Any) -> bool:
    principal = _principal(subject)
    if principal.is_admin:
        return True
    if not principal.is_member or principal.role == WORKSPACE_VIEWER:
        return False
    if not can_read_collection(principal, collection):
        return False
    writers = (_policy(collection) or {}).get("write")
    if writers is None:
        return True
    return bool(principal.tokens.intersection(writers))


def can_manage_collection(subject: Any) -> bool:
    return _principal(subject).is_admin


def collection_permissions_for_member(subject: Any, collection: Any) -> dict[str, bool]:
    principal = _principal(subject)
    return {
        "can_read": can_read_collection(principal, collection),
        "can_write": can_write_collection(principal, collection),
        "can_manage": can_manage_collection(principal),
    }


def collection_permissions(
    db: DBSession,
    *,
    workspace: Workspace,
    collection: KnowledgeCollection,
    user_id: str | None = None,
    member: Any = None,
) -> dict[str, bool]:
    principal = _resolve_subject(db, workspace=workspace, user_id=user_id, member=member)
    return collection_permissions_for_member(principal, collection)


def readable_collections(subject: Any, rows: Iterable[KnowledgeCollection]) -> list[KnowledgeCollection]:
    principal = _principal(subject)
    return [row for row in rows if can_read_collection(principal, row)]


def readable_collection_ids(db: DBSession, subject: Any, *, workspace_id: str) -> set[str]:
    """Ids of the workspace collections ``subject`` reads — one query."""
    principal = _principal(subject)
    rows = (
        db.query(KnowledgeCollection.id, KnowledgeCollection.access)
        .filter(KnowledgeCollection.workspace_id == workspace_id)
        .all()
    )
    return {row.id for row in rows if can_read_collection(principal, row)}


# ------------------------------------------------------------ HTTP guards


def _resolve_subject(
    db: DBSession,
    *,
    workspace: Workspace,
    user_id: str | None,
    member: Any,
) -> CollectionPrincipal:
    if isinstance(member, (CollectionPrincipal, WorkspaceMember)):
        return _principal(member)
    return principal_for_member(
        get_membership(db, workspace=workspace, user_id=user_id),
        workspace_id=workspace.id,
    )


def require_read_collection(
    db: DBSession,
    *,
    workspace: Workspace,
    collection: KnowledgeCollection,
    user_id: str | None = None,
    member: Any = None,
) -> CollectionPrincipal:
    """404 unless the member reads ``collection``; returns the principal."""
    principal = _resolve_subject(db, workspace=workspace, user_id=user_id, member=member)
    if collection.workspace_id != workspace.id or not can_read_collection(principal, collection):
        raise HTTPException(status_code=404, detail=COLLECTION_NOT_FOUND)
    return principal


def require_write_collection(
    db: DBSession,
    *,
    workspace: Workspace,
    collection: KnowledgeCollection,
    user_id: str | None = None,
    member: Any = None,
) -> CollectionPrincipal:
    """404 when unreadable, 403 when readable but not writable."""
    principal = require_read_collection(
        db, workspace=workspace, collection=collection, user_id=user_id, member=member
    )
    if not can_write_collection(principal, collection):
        raise HTTPException(status_code=403, detail={"code": "COLLECTION_WRITE_DENIED"})
    return principal


def find_collection(
    db: DBSession, *, workspace: Workspace, collection_ref: str | None
) -> KnowledgeCollection | None:
    ref = str(collection_ref or "").strip()
    if not ref:
        return None
    # ``create_or_get_collection`` slugifies names, so "Contrats RH" reaches
    # the ``contrats-rh`` row: resolve the same way before deciding.
    slug = re.sub(r"-{2,}", "-", re.sub(r"[^a-zA-Z0-9_-]+", "-", ref.lower())).strip("-_")[:100]
    return (
        db.query(KnowledgeCollection)
        .filter(
            KnowledgeCollection.workspace_id == workspace.id,
            (KnowledgeCollection.slug == ref)
            | (KnowledgeCollection.id == ref)
            | (KnowledgeCollection.vector_collection_name == ref)
            | (KnowledgeCollection.slug == (slug or ref)),
        )
        .order_by((KnowledgeCollection.slug == ref).desc(), (KnowledgeCollection.id == ref).desc())
        .first()
    )


def require_named_collection_read(
    db: DBSession,
    *,
    workspace: Workspace,
    collection_ref: str | None,
    user_id: str | None = None,
    member: Any = None,
) -> KnowledgeCollection | None:
    """The ledger row behind a name, 404 when unreadable.

    ``None`` means a legacy vector-only collection (no ledger row): it has no
    policy and stays open to every member.
    """
    row = find_collection(db, workspace=workspace, collection_ref=collection_ref)
    if row is not None:
        require_read_collection(db, workspace=workspace, collection=row, user_id=user_id, member=member)
    return row


def require_named_collection_write(
    db: DBSession,
    *,
    workspace: Workspace,
    collection_ref: str | None,
    user_id: str | None = None,
    member: Any = None,
) -> KnowledgeCollection | None:
    """Viewers never write; an existing row needs read (404) then write (403)."""
    principal = _resolve_subject(db, workspace=workspace, user_id=user_id, member=member)
    row = find_collection(db, workspace=workspace, collection_ref=collection_ref)
    if row is not None:
        require_write_collection(db, workspace=workspace, collection=row, member=principal)
        return row
    if not principal.is_admin and (not principal.is_member or principal.role == WORKSPACE_VIEWER):
        raise HTTPException(status_code=403, detail={"code": "COLLECTION_WRITE_DENIED"})
    return None


# ------------------------------------------------------- retrieval identity


def _signing_key() -> bytes:
    from app.core.config import settings

    explicit = str(getattr(settings, "collection_access_signing_key", "") or "").strip()
    material = explicit or f"agentium-collection-access::{settings.database_url}"
    return hashlib.sha256(material.encode("utf-8")).digest()


def _identity_message(workspace_id: str, user_id: str, system_id: str, issued_at: int) -> bytes:
    return f"v1|{workspace_id}|{user_id}|{system_id}|{issued_at}".encode("utf-8")


def sign_retrieval_identity(
    *,
    workspace_id: str,
    user_id: str | None = None,
    system_id: str | None = None,
    issued_at: int | None = None,
) -> dict[str, Any]:
    issued = int(issued_at if issued_at is not None else time.time())
    signature = hmac.new(
        _signing_key(),
        _identity_message(str(workspace_id), str(user_id or ""), str(system_id or ""), issued),
        hashlib.sha256,
    ).hexdigest()
    return {
        "v": 1,
        "workspace_id": str(workspace_id),
        "user_id": user_id or None,
        "system_id": system_id or None,
        "iat": issued,
        "sig": signature,
    }


def verify_retrieval_identity(value: Any, *, workspace_id: str | None) -> tuple[str | None, str | None] | None:
    """``(user_id, system_id)`` for a genuine, fresh identity of this workspace."""
    from app.core.config import settings

    if not isinstance(value, Mapping) or not workspace_id or value.get("v") != 1:
        return None
    if str(value.get("workspace_id") or "") != str(workspace_id):
        return None
    try:
        issued = int(value.get("iat"))
    except (TypeError, ValueError):
        return None
    ttl = int(getattr(settings, "collection_access_identity_ttl_seconds", 43200) or 43200)
    now = time.time()
    if issued > now + 60 or now - issued > ttl:
        return None
    user_id = str(value.get("user_id") or "")
    system_id = str(value.get("system_id") or "")
    expected = hmac.new(
        _signing_key(),
        _identity_message(str(workspace_id), user_id, system_id, issued),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, str(value.get("sig") or "")):
        return None
    return user_id or None, system_id or None


def strip_client_retrieval_keys(request: dict[str, Any]) -> dict[str, Any]:
    """Drop server-owned access keys a client body or payload may carry."""
    for key in _CLIENT_FORBIDDEN_RETRIEVAL_KEYS:
        request.pop(key, None)
    return request


def bind_retrieval_identity(
    request: dict[str, Any],
    *,
    workspace_id: str | None,
    user_id: str | None = None,
    system_id: str | None = None,
) -> dict[str, Any]:
    """Overwrite whatever the request carried with the server's identity."""
    strip_client_retrieval_keys(request)
    if workspace_id and (user_id or system_id):
        request[RETRIEVAL_IDENTITY_KEY] = sign_retrieval_identity(
            workspace_id=workspace_id, user_id=user_id, system_id=system_id
        )
    return request


# ------------------------------------------------------- retrieval filtering


@dataclass(frozen=True)
class RetrievalCollectionAccess:
    """Names (slug, id, vector name) of collections a retrieval must not touch."""

    denied: frozenset[str] = frozenset()

    def allows(self, ref: Any) -> bool:
        return str(ref or "").strip() not in self.denied

    def filter(self, refs: Iterable[Any] | None) -> list[str]:
        return [str(ref) for ref in (refs or []) if str(ref or "").strip() and self.allows(ref)]

    def evidence_allowed(self, metadata: Any) -> bool:
        if not self.denied or not isinstance(metadata, Mapping):
            return True
        return not any(
            str(metadata.get(key) or "").strip() in self.denied for key in _EVIDENCE_COLLECTION_KEYS
        )

    def filter_payload(self, payload: Any) -> Any:
        """Drop chunks whose metadata names a denied collection (final pass)."""
        if not self.denied or not isinstance(payload, dict):
            return payload
        chunks = list(payload.get("chunks") or [])
        metadatas = list(payload.get("metadatas") or [])
        scores = list(payload.get("scores") or [])
        if not metadatas:
            return payload
        keep = [index for index, meta in enumerate(metadatas) if self.evidence_allowed(meta)]
        if len(keep) == len(metadatas):
            return payload
        payload["chunks"] = [chunks[i] for i in keep if i < len(chunks)]
        payload["metadatas"] = [metadatas[i] for i in keep]
        payload["scores"] = [scores[i] for i in keep if i < len(scores)]
        metrics = payload.get("metrics")
        if isinstance(metrics, dict):
            metrics["collection_access_dropped_chunks"] = len(metadatas) - len(keep)
            metrics["chunks_retrieved"] = len(payload["chunks"])
        return payload


OPEN_RETRIEVAL = RetrievalCollectionAccess()

# The access resolved for the retrieval running in this task, so the profile,
# the planner and the lanes of one retrieval share a single decision (and a
# single query) instead of re-reading it at every stage.
_ACTIVE_RETRIEVAL: ContextVar[tuple[tuple[str, str], RetrievalCollectionAccess] | None] = ContextVar(
    "collection_access_active_retrieval", default=None
)


def _retrieval_key(request: Mapping[str, Any]) -> tuple[str, str]:
    identity = request.get(RETRIEVAL_IDENTITY_KEY)
    signature = str(identity.get("sig") or "") if isinstance(identity, Mapping) else ""
    return str(request.get("workspace_id") or request.get("workspace_slug") or ""), signature


@contextmanager
def scoped_retrieval_access(request: Mapping[str, Any], access: RetrievalCollectionAccess):
    token = _ACTIVE_RETRIEVAL.set((_retrieval_key(request), access))
    try:
        yield access
    finally:
        _ACTIVE_RETRIEVAL.reset(token)


def _workspace_id_for(db: DBSession, request: Mapping[str, Any]) -> str | None:
    workspace_id = str(request.get("workspace_id") or "").strip()
    if workspace_id:
        return workspace_id
    slug = str(request.get("workspace_slug") or "").strip()
    if not slug:
        return None
    return db.query(Workspace.id).filter(Workspace.slug == slug).scalar()


def retrieval_collection_access(
    request: Mapping[str, Any] | None,
    *,
    db: DBSession | None = None,
) -> RetrievalCollectionAccess:
    """What a retrieval request may not search, fail-closed.

    One query on the collections carrying a policy; one more for the member
    only when a restricted collection exists. Legacy vector-only collections
    have no row, hence no policy, and stay searchable.
    """
    if not isinstance(request, Mapping):
        return OPEN_RETRIEVAL
    active = _ACTIVE_RETRIEVAL.get()
    if active is not None and active[0] == _retrieval_key(request):
        return active[1]
    owns_session = db is None
    if owns_session:
        from app.db.base import SessionLocal

        db = SessionLocal()
    try:
        workspace_id = _workspace_id_for(db, request)
        if not workspace_id:
            return OPEN_RETRIEVAL
        rows = (
            db.query(
                KnowledgeCollection.id,
                KnowledgeCollection.slug,
                KnowledgeCollection.vector_collection_name,
                KnowledgeCollection.access,
            )
            .filter(
                KnowledgeCollection.workspace_id == workspace_id,
                KnowledgeCollection.access.isnot(None),
            )
            .all()
        )
        restricted = [row for row in rows if (_policy(row) or {}).get("read") is not None]
        if not restricted:
            return OPEN_RETRIEVAL
        identity = verify_retrieval_identity(request.get(RETRIEVAL_IDENTITY_KEY), workspace_id=workspace_id)
        user_id, system_id = identity if identity else (None, None)
        principal = load_principal(db, workspace_id=workspace_id, user_id=user_id, system_id=system_id)
        denied: set[str] = set()
        for row in restricted:
            if not can_read_collection(principal, row):
                denied.update(str(value) for value in (row.id, row.slug, row.vector_collection_name) if value)
        return RetrievalCollectionAccess(frozenset(denied))
    finally:
        if owns_session:
            db.close()


def request_identity_for_context(ctx: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Signed identity for a run: the launching user, else the running System."""
    if not isinstance(ctx, Mapping):
        return None
    workspace_id = str(ctx.get("workspace_id") or "").strip()
    user_id = str(ctx.get("user_id") or "").strip() or None
    system_id = str(ctx.get("system_id") or "").strip() or None
    if not workspace_id or not (user_id or system_id):
        return None
    # A user-launched run reads with the user's rights only; the System grant
    # applies to runs nobody launched (scheduled automations).
    return sign_retrieval_identity(
        workspace_id=workspace_id,
        user_id=user_id,
        system_id=None if user_id else system_id,
    )


__all__ = [
    "COLLECTION_NOT_FOUND",
    "CollectionPrincipal",
    "RETRIEVAL_IDENTITY_KEY",
    "RetrievalCollectionAccess",
    "bind_retrieval_identity",
    "can_manage_collection",
    "can_read_collection",
    "can_write_collection",
    "collection_permissions",
    "collection_permissions_for_member",
    "find_collection",
    "get_membership",
    "load_principal",
    "normalize_collection_access",
    "principal_for_member",
    "readable_collection_ids",
    "readable_collections",
    "request_identity_for_context",
    "require_named_collection_read",
    "require_named_collection_write",
    "require_read_collection",
    "require_write_collection",
    "retrieval_collection_access",
    "scoped_retrieval_access",
    "sign_retrieval_identity",
    "strip_client_retrieval_keys",
    "verify_retrieval_identity",
]
