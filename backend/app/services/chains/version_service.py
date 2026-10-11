"""Rolling window version store for System flow and configuration evidence.

Keep the table simple, keep the semantics boring:

- Every ``PATCH /systems/{id}`` that mutates ``flow_definition`` lands
  a new row here via :func:`record_new_version`. ``version_number``
  auto-increments per system so the editor can display v1, v2, v3…
  without guessing.
- When the row count for a system exceeds
  ``settings.custom_chain_version_window`` (default 500, decision
  2026-04-24), the oldest ``version_number`` is purged FIFO.
- Rollback (:func:`rollback_to_version`) never rewrites history: it
  creates a *new* version whose ``flow_definition`` equals the target
  one. The editor renders "v42 — rolled back to v17" via
  ``rolled_back_from_id``.
- A caller may explicitly attach a small, positive-allowlisted
  ``configuration_snapshot``.  This lets configuration-only rollouts append
  honest evidence while all legacy flow-only callers retain their exact no-op
  behaviour when the DAG is unchanged.

Every mutation emits an audit event (``chain.version.created``,
``chain.version.purged``, ``chain.rollback``) with workspace/system/
version context but *not* the full ``flow_definition`` (too big for
the audit log, and the version row already holds it).

All public functions are pure with respect to HTTP: they take a
``Session`` and the minimum context they need, so the same service
is reusable from a BackgroundTask, a CLI, or a future Celery worker
without touching FastAPI internals.
"""
from __future__ import annotations

import copy
import json
import logging
from collections.abc import Mapping
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import desc
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.models.run import Run
from app.models.experience import ExperienceDeployment, ExperienceRelease
from app.models.system import System
from app.models.system_binding import SystemBinding
from app.models.system_flow_draft import SystemFlowDraft
from app.models.system_version import SystemVersion
from app.services.audit_logger import emit_audit_event

logger = logging.getLogger(__name__)

CONFIGURATION_SNAPSHOT_SCHEMA_VERSION = 1
_CONFIGURATION_SNAPSHOT_KEYS = frozenset({"schema_version", "bindings", "transition"})
_CONFIGURATION_BINDING_KEYS = frozenset(
    {"control_policy_id", "adaptive_policy_id", "context_id"}
)
_CONFIGURATION_TRANSITION_KEYS = frozenset(
    {
        "kind",
        "previous_control_policy_id",
        "enforcement_mode",
        "source_contract_sha256",
        "target_contract_sha256",
    }
)
_CONFIGURATION_TRANSITION_KINDS = frozenset(
    {"control_policy_rebind", "showcase_seed_reconcile"}
)
_MEMBRANE_ENFORCEMENT_MODES = frozenset({"compat", "shadow", "enforce"})


def _canonical_flow_sha256(flow_definition: Mapping[str, Any]) -> str:
    """Resolve the shared hash lazily to avoid a run-engine import cycle."""

    from app.services.run_engine.execution_contract import canonical_flow_sha256

    return canonical_flow_sha256(flow_definition)


class ChainVersionError(Exception):
    """Raised when a rollback / lookup cannot be satisfied."""


class ConfigurationSnapshotError(ValueError):
    """Raised when configuration evidence exceeds its positive allowlist."""


def experience_release_references(
    db: DBSession,
    *,
    system_id: str,
    version_id: str | None = None,
) -> list[dict[str, Any]]:
    """Release references that make a SystemVersion retention authority."""
    rows = (
        db.query(ExperienceRelease, ExperienceDeployment)
        .outerjoin(
            ExperienceDeployment,
            ExperienceDeployment.release_id == ExperienceRelease.id,
        )
        .all()
    )
    references: list[dict[str, Any]] = []
    for release, deployment in rows:
        for snapshot in release.bindings_snapshot or []:
            if not isinstance(snapshot, Mapping) or snapshot.get("system_id") != system_id:
                continue
            referenced_version_id = snapshot.get("published_flow_version_id")
            if version_id is not None and referenced_version_id != version_id:
                continue
            references.append(
                {
                    "experience_id": release.experience_id,
                    "release_id": release.id,
                    "deployment_id": deployment.id if deployment is not None else None,
                    "channel": deployment.channel if deployment is not None else None,
                    "active": deployment is not None,
                    "binding_key": str(snapshot.get("binding_key") or ""),
                    "version_id": str(referenced_version_id or ""),
                }
            )
    return references


def _lock_system_for_versioning(db: DBSession, system_id: str) -> System:
    """Serialize version allocation on the stable parent row.

    Locking the latest ``SystemVersion`` cannot protect the first insert, and
    locking every existing version would still leave an empty-history race.
    The parent ``System`` exists for the complete lifetime of its history, so
    it is the single lock target for both the no-op comparison and allocation
    of ``max(version_number) + 1``.

    ``of=System`` is important on PostgreSQL because ``System.capability`` is
    joined eagerly: a bare ``FOR UPDATE`` would attempt to lock the nullable
    side of that outer join as well.
    """

    locked = (
        db.query(System)
        .filter(System.id == system_id)
        .populate_existing()
        .with_for_update(of=System)
        .one_or_none()
    )
    if locked is None:
        raise ChainVersionError(
            f"System {system_id!r} no longer exists; cannot append a version."
        )
    return locked


def _flow_definitions_equal(a: Any, b: Any) -> bool:
    """Conservative structural equality on JSON-ish trees.

    We compare after ``json.dumps(sort_keys=True)`` so key ordering
    on nested dicts doesn't create false positives. Non-JSON-safe
    inputs fall back to ``repr`` equality which is looser but safe.
    """
    if a is b:
        return True
    try:
        return json.dumps(a, sort_keys=True, default=str) == json.dumps(
            b, sort_keys=True, default=str
        )
    except (TypeError, ValueError):  # pragma: no cover — defensive
        return repr(a) == repr(b)


def _configuration_reference(value: Any, *, field: str, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise ConfigurationSnapshotError(
            f"configuration_snapshot.{field} must be a canonical UUID reference"
        )
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ConfigurationSnapshotError(
            f"configuration_snapshot.{field} must be a canonical UUID reference"
        ) from exc
    if str(parsed) != value:
        raise ConfigurationSnapshotError(
            f"configuration_snapshot.{field} must be a canonical UUID reference"
        )
    return str(parsed)


def _contract_sha256(value: Any, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or value.lower() != value
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ConfigurationSnapshotError(
            f"configuration_snapshot.{field} must be a lowercase SHA-256 digest"
        )
    return value


def normalize_configuration_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and detach safe configuration evidence.

    This is deliberately not a generic settings snapshot.  Only immutable
    binding references, the transition kind/mode, and contract digests can
    cross this boundary.  Unknown keys fail closed instead of being copied and
    potentially persisting a secret-bearing policy body.
    """

    if not isinstance(snapshot, Mapping):
        raise ConfigurationSnapshotError("configuration_snapshot must be an object")
    raw = dict(snapshot)
    unknown = sorted(
        repr(key)
        for key in raw
        if not isinstance(key, str) or key not in _CONFIGURATION_SNAPSHOT_KEYS
    )
    if unknown:
        raise ConfigurationSnapshotError(
            "unsupported configuration_snapshot fields: " + ", ".join(unknown)
        )
    if raw.get("schema_version") != CONFIGURATION_SNAPSHOT_SCHEMA_VERSION:
        raise ConfigurationSnapshotError(
            "configuration_snapshot.schema_version must be "
            f"{CONFIGURATION_SNAPSHOT_SCHEMA_VERSION}"
        )

    raw_bindings = raw.get("bindings")
    if not isinstance(raw_bindings, Mapping) or not raw_bindings:
        raise ConfigurationSnapshotError(
            "configuration_snapshot.bindings must be a non-empty object"
        )
    unknown_bindings = sorted(
        repr(key)
        for key in raw_bindings
        if not isinstance(key, str) or key not in _CONFIGURATION_BINDING_KEYS
    )
    if unknown_bindings:
        raise ConfigurationSnapshotError(
            "unsupported configuration_snapshot.bindings fields: "
            + ", ".join(unknown_bindings)
        )
    bindings = {
        key: _configuration_reference(
            value,
            field=f"bindings.{key}",
            nullable=True,
        )
        for key, value in raw_bindings.items()
    }

    normalized: dict[str, Any] = {
        "schema_version": CONFIGURATION_SNAPSHOT_SCHEMA_VERSION,
        "bindings": bindings,
    }
    raw_transition = raw.get("transition")
    if raw_transition is not None:
        if not isinstance(raw_transition, Mapping):
            raise ConfigurationSnapshotError(
                "configuration_snapshot.transition must be an object"
            )
        unknown_transition = sorted(
            repr(key)
            for key in raw_transition
            if not isinstance(key, str) or key not in _CONFIGURATION_TRANSITION_KEYS
        )
        if unknown_transition:
            raise ConfigurationSnapshotError(
                "unsupported configuration_snapshot.transition fields: "
                + ", ".join(unknown_transition)
            )
        if raw_transition.get("kind") not in _CONFIGURATION_TRANSITION_KINDS:
            raise ConfigurationSnapshotError(
                "configuration_snapshot.transition.kind is unsupported"
            )
        if raw_transition.get("enforcement_mode") not in _MEMBRANE_ENFORCEMENT_MODES:
            raise ConfigurationSnapshotError(
                "configuration_snapshot.transition.enforcement_mode is unsupported"
            )
        transition = {
            "kind": raw_transition["kind"],
            "previous_control_policy_id": _configuration_reference(
                raw_transition.get("previous_control_policy_id"),
                field="transition.previous_control_policy_id",
                nullable=True,
            ),
            "enforcement_mode": raw_transition["enforcement_mode"],
            "source_contract_sha256": _contract_sha256(
                raw_transition.get("source_contract_sha256"),
                field="transition.source_contract_sha256",
            ),
            "target_contract_sha256": _contract_sha256(
                raw_transition.get("target_contract_sha256"),
                field="transition.target_contract_sha256",
            ),
        }
        normalized["transition"] = transition
    return copy.deepcopy(normalized)


def record_new_version(
    *,
    db: DBSession,
    system: System,
    flow_definition: Mapping[str, Any],
    created_by: str,
    message: str | None = None,
    rolled_back_from_id: str | None = None,
    audit_actor: str | None = None,
    purge: bool = True,
    configuration_snapshot: Mapping[str, Any] | None = None,
    force: bool = False,
    release_kind: str = "legacy_snapshot",
    draft_revision: int | None = None,
    execution_contract: Mapping[str, Any] | None = None,
) -> SystemVersion | None:
    """Persist a new ``SystemVersion`` for this system and trim the
    rolling window. Commits on the caller's session (we only flush —
    the caller decides when to commit so we stay inside their
    transaction when embedded in a larger write).

    Returns the new version, or ``None`` if the authoritative inputs are
    identical to the latest row.  When ``configuration_snapshot`` is omitted,
    only the flow participates in that comparison, preserving the historical
    contract for every legacy caller.  When supplied explicitly, the validated
    snapshot participates too and can therefore prove a configuration-only
    transition.
    """

    normalized_configuration = (
        normalize_configuration_snapshot(configuration_snapshot)
        if configuration_snapshot is not None
        else None
    )

    # The parent lock must be acquired before either reading the latest row or
    # deriving its successor.  Every cooperating writer therefore allocates a
    # version number inside one serialized critical section.  The database
    # uniqueness constraint remains the final guard for non-cooperating writes.
    locked_system = _lock_system_for_versioning(db, system.id)
    latest = (
        db.query(SystemVersion)
        .filter(SystemVersion.system_id == locked_system.id)
        .order_by(desc(SystemVersion.version_number))
        .first()
    )

    if not force and latest is not None and _flow_definitions_equal(
        latest.flow_definition, flow_definition
    ):
        if configuration_snapshot is None or _flow_definitions_equal(
            latest.configuration_snapshot,
            normalized_configuration,
        ):
            return None

    version = SystemVersion(
        id=str(uuid4()),
        system_id=locked_system.id,
        workspace_id=locked_system.workspace_id,
        version_number=(latest.version_number if latest is not None else 0) + 1,
        flow_definition=copy.deepcopy(dict(flow_definition)),
        configuration_snapshot=normalized_configuration,
        flow_sha256=_canonical_flow_sha256(flow_definition),
        release_kind=release_kind,
        draft_revision=draft_revision,
        execution_contract=(
            copy.deepcopy(dict(execution_contract))
            if execution_contract is not None
            else None
        ),
        message=message,
        rolled_back_from_id=rolled_back_from_id,
        created_by=created_by or "demo-user",
    )
    db.add(version)
    db.flush()

    # Product/runtime edits retain the bounded rolling window.  Migration and
    # rollout callers can opt out explicitly: those operations promise never
    # to delete a historical SystemVersion while establishing a new contract.
    purged_ids = _purge_window(db=db, system_id=locked_system.id) if purge else []

    emit_audit_event(
        workspace_id=locked_system.workspace_id,
        event_type="chain.version.created",
        actor=audit_actor or created_by or "demo-user",
        details={
            "system_id": locked_system.id,
            "version_id": version.id,
            "version_number": version.version_number,
            "rolled_back_from_id": rolled_back_from_id,
            "message_len": len(message) if message else 0,
            "has_configuration_snapshot": normalized_configuration is not None,
            "configuration_snapshot_schema_version": (
                normalized_configuration.get("schema_version")
                if normalized_configuration is not None
                else None
            ),
        },
        # Reuse the caller's session so we stay inside their unit of
        # work (same transaction, same connection). Production doesn't
        # care (Postgres handles multi-session concurrency fine) but
        # SQLite serialises writes — opening a second SessionLocal
        # against the test DB while the caller still holds the write
        # lock produces "database is locked". ``emit_audit_event``
        # handles the reused-session path (flush-only, no commit).
        db=db,
    )

    if purged_ids:
        emit_audit_event(
            workspace_id=locked_system.workspace_id,
            event_type="chain.version.purged",
            actor=audit_actor or "system",
            details={
                "system_id": locked_system.id,
                "purged_count": len(purged_ids),
                "purged_ids": purged_ids,
                "window": settings.custom_chain_version_window,
            },
            db=db,
        )

    return version


def _purge_window(*, db: DBSession, system_id: str) -> list[str]:
    """Trim the oldest versions so the system stays within
    ``settings.custom_chain_version_window``. Return the ids of purged
    rows.
    """

    window = max(1, int(settings.custom_chain_version_window))
    total = (
        db.query(SystemVersion)
        .filter(SystemVersion.system_id == system_id)
        .count()
    )
    if total <= window:
        return []

    overflow = total - window
    # Publication pointers and Run evidence are retention authorities. The
    # rolling window may remain above its target when all old rows are
    # protected; losing replay/publication truth is never an acceptable way to
    # meet a row-count preference.
    protected_ids = {
        value
        for (value,) in (
            db.query(System.published_flow_version_id)
            .filter(
                System.id == system_id,
                System.published_flow_version_id.isnot(None),
            )
            .union_all(
                db.query(SystemFlowDraft.base_published_version_id).filter(
                    SystemFlowDraft.system_id == system_id,
                    SystemFlowDraft.base_published_version_id.isnot(None),
                )
            )
            .union_all(
                db.query(Run.published_flow_version_id).filter(
                    Run.system_id == system_id,
                    Run.published_flow_version_id.isnot(None),
                )
            )
            .union_all(
                db.query(Run.flow_version_id).filter(
                    Run.system_id == system_id,
                    Run.flow_version_id.isnot(None),
                )
            )
            .union_all(
                db.query(SystemBinding.published_flow_version_id).filter(
                    SystemBinding.system_id == system_id,
                    SystemBinding.published_flow_version_id.isnot(None),
                )
            )
            .all()
        )
        if value is not None
    }
    protected_ids.update(
        item["version_id"]
        for item in experience_release_references(db, system_id=system_id)
        if item["version_id"]
    )
    to_purge = (
        db.query(SystemVersion)
        .filter(SystemVersion.system_id == system_id)
        .filter(~SystemVersion.id.in_(protected_ids) if protected_ids else True)
        .order_by(SystemVersion.version_number.asc())
        .limit(overflow)
        .all()
    )
    purged_ids = [v.id for v in to_purge]
    for v in to_purge:
        db.delete(v)
    db.flush()
    logger.info(
        "Purged %d SystemVersion rows for system %s (window=%d)",
        len(purged_ids),
        system_id,
        window,
    )
    return purged_ids


def purge_version_window(*, db: DBSession, system_id: str) -> list[str]:
    """Public retention entrypoint used after an atomic publication."""

    return _purge_window(db=db, system_id=system_id)


def list_versions(
    *,
    db: DBSession,
    system_id: str,
    workspace_id: str | None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[SystemVersion], int]:
    """Return ``(rows, total)`` for the given system, workspace-scoped.

    ``limit`` is hard-capped at 500 (the rolling window size) to make
    pagination trivial — callers that need more should implement their
    own pagination on top.
    """

    q = db.query(SystemVersion).filter(SystemVersion.system_id == system_id)
    if workspace_id is not None:
        q = q.filter(SystemVersion.workspace_id == workspace_id)
    total = q.count()
    rows = (
        q.order_by(desc(SystemVersion.version_number))
        .offset(max(0, int(offset)))
        .limit(max(1, min(500, int(limit))))
        .all()
    )
    return rows, total


def get_version(
    *,
    db: DBSession,
    system_id: str,
    workspace_id: str | None,
    version_number: int,
) -> SystemVersion | None:
    q = db.query(SystemVersion).filter(
        SystemVersion.system_id == system_id,
        SystemVersion.version_number == int(version_number),
    )
    if workspace_id is not None:
        q = q.filter(SystemVersion.workspace_id == workspace_id)
    return q.first()


def rollback_to_version(
    *,
    db: DBSession,
    system: System,
    version_number: int,
    created_by: str,
    message: str | None = None,
    audit_actor: str | None = None,
    purge: bool = True,
    flow_write_audit: Mapping[str, Any] | None = None,
) -> SystemVersion:
    """Roll the system back to ``version_number`` by creating a new
    version whose ``flow_definition`` equals that target. Also updates
    ``System.flow_definition`` in place so the run engine sees the
    rollback on its next read.

    Returns the newly created version row. Raises
    :class:`ChainVersionError` if the target doesn't exist (e.g. it
    was purged out of the rolling window, or it belongs to another
    workspace).
    """

    # HTTP routes normally redirect feature-on restores to the server draft,
    # but services and scripts can call this primitive directly. Guard here as
    # the final authority so no legacy caller can rewrite the published mirror
    # behind its immutable pointer.
    if system.workspace_id is not None:
        from app.models.workspace import Workspace
        from app.services.systems.flow_publication import flow_publication_enabled

        workspace = db.query(Workspace).filter(Workspace.id == system.workspace_id).one_or_none()
        if workspace is not None and flow_publication_enabled(workspace):
            raise ChainVersionError(
                "Legacy rollback is disabled while Flow publication is enabled; "
                "restore the immutable version into the server draft instead."
            )

    target = get_version(
        db=db,
        system_id=system.id,
        workspace_id=system.workspace_id,
        version_number=version_number,
    )
    if target is None:
        raise ChainVersionError(
            f"Version {version_number} not found for system {system.id!r} "
            "(possibly purged by the rolling window)."
        )

    rollback_audit = (
        {"flow_write": copy.deepcopy(dict(flow_write_audit))}
        if flow_write_audit is not None
        else {}
    )

    # No-op is defined against the authoritative System row, not the latest
    # history row. The two can legitimately diverge after legacy/direct writes.
    if _flow_definitions_equal(system.flow_definition, target.flow_definition):
        emit_audit_event(
            workspace_id=system.workspace_id,
            event_type="chain.rollback",
            actor=audit_actor or created_by or "demo-user",
            details={
                "system_id": system.id,
                "target_version_number": target.version_number,
                "target_version_id": target.id,
                "no_op": True,
                **rollback_audit,
            },
            db=db,
        )
        return target

    new_version = record_new_version(
        db=db,
        system=system,
        flow_definition=target.flow_definition,
        created_by=created_by,
        message=message or f"Rolled back to v{target.version_number}",
        rolled_back_from_id=target.id,
        audit_actor=audit_actor,
        purge=purge,
        # A duplicate latest history row must not suppress repair of a drifted
        # authoritative System. Rollback intent always appends in that case.
        force=True,
        release_kind="rollback",
    )
    assert new_version is not None  # force=True forbids duplicate suppression

    # Keep System.flow_definition in sync so run engine sees the rollback.
    system.flow_definition = copy.deepcopy(dict(target.flow_definition))
    db.add(system)
    db.flush()

    emit_audit_event(
        workspace_id=system.workspace_id,
        event_type="chain.rollback",
        actor=audit_actor or created_by or "demo-user",
        details={
            "system_id": system.id,
            "target_version_number": target.version_number,
            "target_version_id": target.id,
            "new_version_number": new_version.version_number,
            "new_version_id": new_version.id,
            "no_op": False,
            **rollback_audit,
        },
        db=db,
    )

    return new_version


def serialize_version(version: SystemVersion) -> dict[str, Any]:
    """Shape for API responses."""
    return {
        "id": version.id,
        "system_id": version.system_id,
        "workspace_id": version.workspace_id,
        "version_number": version.version_number,
        "flow_definition": version.flow_definition,
        "configuration_snapshot": version.configuration_snapshot,
        "flow_sha256": version.flow_sha256
        or _canonical_flow_sha256(version.flow_definition),
        "release_kind": version.release_kind or "legacy_snapshot",
        "draft_revision": version.draft_revision,
        "execution_contract": version.execution_contract,
        "message": version.message,
        "rolled_back_from_id": version.rolled_back_from_id,
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "created_by": version.created_by,
    }


def serialize_version_summary(version: SystemVersion) -> dict[str, Any]:
    """Listing shape — drops the heavyweight ``flow_definition`` so the
    versions panel can stay snappy even with 500 rows.
    """
    flow = version.flow_definition or {}
    nodes = flow.get("nodes") if isinstance(flow, Mapping) else None
    edges = flow.get("edges") if isinstance(flow, Mapping) else None
    return {
        "id": version.id,
        "system_id": version.system_id,
        "version_number": version.version_number,
        "message": version.message,
        "rolled_back_from_id": version.rolled_back_from_id,
        "flow_sha256": version.flow_sha256
        or _canonical_flow_sha256(version.flow_definition),
        "release_kind": version.release_kind or "legacy_snapshot",
        "draft_revision": version.draft_revision,
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "created_by": version.created_by,
        "node_count": len(nodes) if isinstance(nodes, list) else 0,
        "edge_count": len(edges) if isinstance(edges, list) else 0,
    }
