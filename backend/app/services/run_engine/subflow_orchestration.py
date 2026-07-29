"""Durable parent/child coordination for Celery delegated Runs.

This module deliberately owns only persisted coordination.  Celery messages
carry a child Run id; all mutable inputs, join state and lineage are reloaded
under database locks.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

from app.db.base import SessionLocal
from app.db.base import engine as db_engine
from app.models.run import Run
from app.models.system import System
from app.models.workspace import Workspace
from app.services.system_catalog_bindings import (
    SystemCatalogBindingError,
    resolve_run_system_catalog_bindings,
)

TERMINAL = {"completed", "failed", "cancelled"}


def _wave_ids_equal(left: Any, right: Any) -> bool:
    """Compare canonical non-negative integer wave ids without coercion."""

    if left is None or right is None:
        return left is None and right is None
    return (
        type(left) is int
        and type(right) is int
        and left >= 0
        and right >= 0
        and left == right
    )


def _parent_lock_key(parent_run_id: str) -> int:
    """Map a Run id to PostgreSQL's signed 64-bit advisory-lock space."""

    return int.from_bytes(
        hashlib.sha256(f"agentium:subflow-parent:{parent_run_id}".encode()).digest()[:8],
        byteorder="big",
        signed=True,
    )


@contextmanager
def postgres_coordination_lease(scope: str, run_id: str):
    """Yield whether this process owns a crash-released session lease."""

    connection = db_engine.connect()
    lock_key = int.from_bytes(
        hashlib.sha256(f"agentium:{scope}:{run_id}".encode()).digest()[:8],
        byteorder="big",
        signed=True,
    )
    acquired = False
    try:
        if connection.dialect.name != "postgresql":
            yield False
            return
        acquired = bool(
            connection.execute(
                text("SELECT pg_try_advisory_lock(:lock_key)"),
                {"lock_key": lock_key},
            ).scalar()
        )
        connection.commit()
        yield acquired
    finally:
        if acquired:
            try:
                if connection.in_transaction():
                    connection.rollback()
                released = bool(
                    connection.execute(
                        text("SELECT pg_advisory_unlock(:lock_key)"),
                        {"lock_key": lock_key},
                    ).scalar()
                )
                connection.commit()
                if not released:
                    connection.invalidate()
            except Exception:
                # Never return a connection whose session lock state is
                # uncertain to the pool.
                connection.invalidate()
        connection.close()


def _maybe_crash_after_claim(parent: Run, *, resume_owner: str) -> None:
    """Integration-only crash point for the real parent resume path."""

    if os.getenv("RUN_RABBITMQ_INTEGRATION") != "1":
        return
    marker_token = (
        (parent.input_ref or {}).get("_p4_crash_after_parent_claim")
        if isinstance(parent.input_ref, dict)
        else None
    )
    if not marker_token:
        return
    safe_token = str(UUID(str(marker_token)))
    root = Path(os.getenv("SUBFLOW_CRASH_PROBE_DIR", "/tmp"))
    marker = root / f"agentium-p4-parent-claim-{safe_token}.first"
    if marker.exists():
        return
    marker.write_text(resume_owner, encoding="utf-8")
    os._exit(92)  # dedicated P4 worker process; PostgreSQL releases the lease


def validate_contract(payload: Any, contract: dict[str, Any]) -> bool:
    """Validate the JSON-schema subset used by delegation ACLs.

    Supported keywords are ``type``, ``required``, ``properties`` and nested
    objects/arrays. A compact ``{field: type}`` map is accepted as shorthand.
    Unknown keywords and malformed nested schemas fail closed so a typo in an
    enforce ACL can never broaden delegation.
    """
    if not contract:
        return True
    schema_keywords = {"type", "required", "properties", "items"}
    if not any(key in contract for key in schema_keywords):
        contract = {
            "type": "object",
            "required": list(contract),
            "properties": {
                str(key): value if isinstance(value, dict) else {"type": str(value)}
                for key, value in contract.items()
            },
        }
    elif any(key not in schema_keywords for key in contract):
        return False
    expected = contract.get("type")
    types = {
        "object": dict,
        "array": list,
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
        "null": type(None),
    }
    if expected is not None and expected not in types:
        return False
    required_value = contract.get("required", [])
    if not isinstance(required_value, list | tuple) or any(
        not isinstance(item, str) or not item for item in required_value
    ):
        return False
    properties_value = contract.get("properties", {})
    if not isinstance(properties_value, dict):
        return False
    if contract.get("items") is not None and not isinstance(contract.get("items"), dict):
        return False
    if expected in types:
        if expected in {"number", "integer"} and isinstance(payload, bool):
            return False
        if not isinstance(payload, types[expected]):
            return False
    if isinstance(payload, dict):
        required = required_value
        if any(str(key) not in payload for key in required):
            return False
        properties = properties_value
        for key, child_contract in properties.items():
            if not isinstance(child_contract, dict):
                if isinstance(child_contract, str):
                    child_contract = {"type": child_contract}
                else:
                    return False
            if key in payload and not validate_contract(payload[key], child_contract):
                return False
    if isinstance(payload, list) and isinstance(contract.get("items"), dict):
        return all(validate_contract(item, contract["items"]) for item in payload)
    return True


def delegation_acl_result(
    spec: Any,
    *,
    target_system_id: str,
    branch: str,
    input_payload: dict[str, Any],
) -> tuple[bool, str | None, dict[str, Any] | None, bool]:
    """Return allowed, reason, output contract and whether denial is enforced."""
    if not getattr(spec, "authoritative", False) or getattr(spec, "version", 1) < 2:
        return True, None, None, False
    mode = str(getattr(getattr(spec, "effective_mode", None), "value", "compat"))
    if mode == "compat":
        return True, None, None, False
    rules = list(getattr(getattr(spec, "capabilities", None), "allowed_delegations", []) or [])
    rule = next(
        (
            item
            for item in rules
            if isinstance(item, dict) and str(item.get("system_id") or "") == target_system_id
        ),
        None,
    )
    reason = None
    if rule is None:
        reason = "target_not_allowed"
    elif rule.get("branches") and branch not in {str(v) for v in rule["branches"]}:
        reason = "branch_not_allowed"
    elif rule.get("input_contract") and not validate_contract(input_payload, rule["input_contract"]):
        reason = "input_contract_mismatch"
    output_contract = dict(rule.get("output_contract") or {}) if rule else None
    enforced = mode == "enforce"
    return reason is None or not enforced, reason, output_contract, enforced


def _active_waiting_items(
    waiting: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    """Return the logical delegation key and entry for the active wave only.

    Pre-wave rows remain readable for compatibility, but as soon as the
    parent declares a ``wave_id`` an entry without that exact id is historical
    and must never be refreshed, cancelled or redispatched.
    """

    meta = waiting.get("_meta") if isinstance(waiting.get("_meta"), dict) else {}
    active_wave = meta.get("wave_id")
    return [
        (str(key), value)
        for key, value in waiting.items()
        if key != "_meta"
        and isinstance(value, dict)
        and (
            active_wave is None
            or _wave_ids_equal(value.get("wave_id"), active_wave)
        )
    ]


def _active_waiting_entries(waiting: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only entries belonging to the current durable fan-out wave."""

    return [entry for _key, entry in _active_waiting_items(waiting)]


def _scoped_child_query(
    db: DBSession,
    *,
    parent: Run,
    delegation_key: str,
    child_run_id: str,
):
    """Build the only permitted lookup for a persisted delegation child."""

    return db.query(Run).filter(
        Run.id == child_run_id,
        Run.workspace_id == parent.workspace_id,
        Run.parent_run_id == parent.id,
        Run.delegation_key == delegation_key,
    )


def delegated_parent_claim_context(
    db: DBSession,
    *,
    child: Run,
    workspace_id: str | None,
) -> tuple[Run, dict[str, Any]] | None:
    """Return the active parent claim for this exact child and workspace.

    This deliberately does not trust the child ``input_ref``.  It is the
    recovery-grade half of the contract used when a malformed child must be
    failed and its otherwise valid parent woken.  Normal execution must still
    use :func:`delegated_celery_context`, which validates both durable sides.
    """

    if (
        child.workspace_id != workspace_id
        or not child.parent_run_id
        or not child.delegation_key
    ):
        return None
    parent = (
        db.query(Run)
        .filter(
            Run.id == child.parent_run_id,
            Run.workspace_id == workspace_id,
        )
        .first()
    )
    if parent is None:
        return None
    if (
        _scoped_child_query(
            db,
            parent=parent,
            delegation_key=child.delegation_key,
            child_run_id=child.id,
        ).first()
        is None
    ):
        return None
    waiting = dict(parent.waiting_subflows or {})
    meta = waiting.get("_meta") if isinstance(waiting.get("_meta"), dict) else {}
    if str(meta.get("execution_plane") or "") != "celery":
        return None
    active = dict(_active_waiting_items(waiting))
    entry = active.get(child.delegation_key)
    if not isinstance(entry, dict) or str(entry.get("child_run_id") or "") != child.id:
        return None
    return parent, entry


def delegated_celery_context(
    db: DBSession,
    *,
    child: Run,
    workspace_id: str | None,
) -> tuple[Run, dict[str, Any]] | None:
    """Verify the persisted parent/child envelope for a Celery delegation.

    A broker task id is delivery metadata, not proof of which execution plane
    owns a paused child.  The durable proof is the agreement between the child
    columns, its immutable delegation envelope, and the active parent waiting
    entry in the same workspace.
    """

    delegation = (
        ((child.input_ref or {}).get("_delegation") or {})
        if isinstance(child.input_ref, dict)
        else {}
    )
    if (
        not isinstance(delegation, dict)
        or str(delegation.get("parent_run_id") or "") != child.parent_run_id
        or str(delegation.get("execution_plane") or "") != "celery"
    ):
        return None
    parent_context = delegated_parent_claim_context(
        db,
        child=child,
        workspace_id=workspace_id,
    )
    if parent_context is None:
        return None
    parent, entry = parent_context
    if str(entry.get("node_id") or "") != str(child.delegation_node_id or ""):
        return None
    if str(entry.get("branch") or "") != str(child.delegation_branch or ""):
        return None
    return parent, entry


def delegated_celery_claimed(
    db: DBSession,
    *,
    child: Run,
    workspace_id: str | None,
) -> bool:
    """Return whether either durable side claims Celery owns this child.

    This is intentionally broader than :func:`delegated_celery_context`: a
    malformed or historical Celery envelope must fail closed at the API rather
    than silently falling back to an in-process continuation.
    """

    if (
        child.workspace_id != workspace_id
        or not child.parent_run_id
        or not child.delegation_key
    ):
        return False
    delegation = (
        ((child.input_ref or {}).get("_delegation") or {})
        if isinstance(child.input_ref, dict)
        else {}
    )
    if isinstance(delegation, dict) and delegation.get("execution_plane") == "celery":
        return True
    parent = (
        db.query(Run)
        .filter(
            Run.id == child.parent_run_id,
            Run.workspace_id == workspace_id,
        )
        .first()
    )
    if parent is None:
        return False
    waiting = dict(parent.waiting_subflows or {})
    meta = waiting.get("_meta") if isinstance(waiting.get("_meta"), dict) else {}
    entry = waiting.get(child.delegation_key)
    return bool(
        meta.get("execution_plane") == "celery"
        and isinstance(entry, dict)
        and str(entry.get("child_run_id") or "") == child.id
    )


def resolve_waiting(waiting: dict[str, Any]) -> tuple[bool, str | None]:
    """Resolve all/any/race deterministically from the active fan-out wave."""
    entries = _active_waiting_entries(waiting)
    if not entries:
        return False, None
    strategy = str((waiting.get("_meta") or {}).get("strategy") or "all")
    terminal = [v for v in entries if v.get("status") in TERMINAL]
    successful = [v for v in terminal if v.get("status") == "completed"]
    def order(value: dict[str, Any]) -> tuple[str, str]:
        return (
            str(value.get("completed_at") or "9999"),
            str(value.get("child_run_id") or ""),
        )
    if strategy == "all":
        return len(terminal) == len(entries), None
    if strategy == "any":
        winner = min(successful, key=order) if successful else None
        return bool(winner or len(terminal) == len(entries)), winner and str(winner["child_run_id"])
    if strategy == "race":
        winner = min(terminal, key=order) if terminal else None
        return bool(winner), winner and str(winner["child_run_id"])
    raise ValueError(f"unsupported subflow join strategy: {strategy}")


def _refresh_entries(
    db: DBSession,
    parent: Run,
    waiting: dict[str, Any],
) -> dict[str, Any]:
    result = {k: dict(v) if isinstance(v, dict) else v for k, v in waiting.items()}
    for key, entry in _active_waiting_items(result):
        child_id = entry.get("child_run_id")
        child = (
            _scoped_child_query(
                db,
                parent=parent,
                delegation_key=key,
                child_run_id=str(child_id),
            ).first()
            if child_id
            else None
        )
        if child is None:
            entry.update({"status": "failed", "error": "delegated_child_missing"})
        else:
            delegation = (
                ((child.input_ref or {}).get("_delegation") or {})
                if isinstance(child.input_ref, dict)
                else {}
            )
            if child.status == "completed" and isinstance(delegation, dict):
                contracts = [
                    value
                    for value in (
                        delegation.get("output_contract"),
                        delegation.get("target_output_contract"),
                    )
                    if isinstance(value, dict) and value
                ]
                if (
                    contracts
                    and not all(validate_contract(child.output_ref or {}, contract) for contract in contracts)
                    and delegation.get("contract_enforced")
                ):
                    child.status = "failed"
                    child.error = child.error or "delegation_output_contract_mismatch"
                    child.output_ref = {}
            entry.update(
                {
                    "status": child.status,
                    "completed_at": child.completed_at.isoformat() if child.completed_at else None,
                    "celery_task_id": child.celery_task_id,
                    "error": child.error,
                }
            )
        result[key] = entry
    return result


def _revoke_tasks(task_ids: list[str]) -> None:
    if not task_ids:
        return
    try:
        from app.workers.celery_app import celery_app

        for task_id in task_ids:
            celery_app.control.revoke(task_id, terminate=True)
    except Exception:
        # Persisted Run state is authoritative; revoke only shortens work.
        pass


def _cancel_losers(
    db: DBSession,
    parent: Run,
    waiting: dict[str, Any],
    winner_id: str,
    *,
    reason: str = "subflow_race_lost",
) -> list[str]:
    """Persist cancellation before best-effort broker revoke for race losers."""
    task_ids = []
    for key, entry in _active_waiting_items(waiting):
        child_id = str(entry.get("child_run_id") or "")
        if not child_id or child_id == winner_id:
            continue
        child = (
            _scoped_child_query(
                db,
                parent=parent,
                delegation_key=key,
                child_run_id=child_id,
            )
            .populate_existing()
            .with_for_update()
            .first()
        )
        if child is None or child.status in TERMINAL:
            continue
        completed_at = datetime.utcnow()
        celery_task_id = child.celery_task_id
        # SessionLocal has autoflush disabled. Use an immediate guarded UPDATE
        # instead of a deferred attribute mutation so the cancellation cannot
        # be lost behind a concurrent HITL transition or an identity-map
        # refresh before the caller commits the parent claim.
        updated = (
            _scoped_child_query(
                db,
                parent=parent,
                delegation_key=key,
                child_run_id=child_id,
            )
            .filter(~Run.status.in_(TERMINAL))
            .update(
                {
                    Run.status: "cancelled",
                    Run.completed_at: completed_at,
                    Run.error: child.error or reason,
                },
                synchronize_session=False,
            )
        )
        if not updated:
            continue
        db.expire(child)
        entry.update({"status": "cancelled", "completed_at": completed_at.isoformat()})
        if celery_task_id:
            task_ids.append(celery_task_id)
    # Caller commits this together with the parent's claimed state while the
    # parent row lock is still held; otherwise two child callbacks could both
    # observe an unclaimed parent between cancellation and claim.
    return task_ids


async def resume_subflow_parent(
    parent_run_id: str,
    *,
    resume_owner: str | None = None,
    redelivered: bool = False,
) -> dict[str, Any]:
    """Claim and resume a parent under a crash-released PostgreSQL lease.

    A session-level advisory lock remains held by an explicitly pinned
    connection across every commit performed by ``_walk``.  If the worker is
    killed, PostgreSQL releases that lock with the connection; an acks-late
    redelivery can then recover a persisted ``running/claimed`` parent without
    allowing two live walkers to execute concurrently.
    """
    from .dag import (
        DagGraph,
        WalkerState,
        _load_control_policy,
        _settle_node,
        _settle_subflow_output,
        _walk,
        _workspace_strict_dag_enabled,
        validate_graph_skill_bindings,
    )

    owner = str(resume_owner or f"inline:{parent_run_id}")
    connection = db_engine.connect()
    db: DBSession = SessionLocal(bind=connection)
    lock_key = _parent_lock_key(parent_run_id)
    postgres_lease = connection.dialect.name == "postgresql"
    lease_acquired = False
    try:
        if postgres_lease:
            lease_acquired = bool(
                db.execute(
                    text("SELECT pg_try_advisory_lock(:lock_key)"),
                    {"lock_key": lock_key},
                ).scalar()
            )
            if not lease_acquired:
                db.rollback()
                return {"status": "resume_busy", "parent_run_id": parent_run_id}

        parent = (
            db.query(Run)
            .filter(Run.id == parent_run_id)
            .with_for_update()
            .first()
        )
        if parent is None:
            return {"status": "parent_missing"}
        if parent.status in TERMINAL:
            db.commit()
            return {"status": parent.status, "parent_run_id": parent.id}

        waiting = _refresh_entries(db, parent, dict(parent.waiting_subflows or {}))
        parent.waiting_subflows = waiting
        # HITL is propagated as durable child state; only the child Decision
        # may unblock it, and redelivery continues to reference this same Run.
        active_entries = _active_waiting_entries(waiting)
        hitl_entry = next(
            (
                entry
                for entry in active_entries
                if entry.get("status") == "hitl_pending"
            ),
            None,
        )
        ready, winner_id = resolve_waiting(waiting)
        if not ready:
            db.commit()
            if hitl_entry is not None:
                return {
                    "status": "waiting_hitl",
                    "parent_run_id": parent.id,
                    "child_run_id": hitl_entry.get("child_run_id"),
                }
            return {"status": "waiting", "parent_run_id": parent.id}
        checkpoints = list(parent.checkpoints or [])
        pause_cp = next((cp for cp in reversed(checkpoints) if cp.get("kind") == "subflow_wait"), None)
        meta = dict(waiting.get("_meta") or {})
        meta_state = str(meta.get("state") or "waiting")
        recovering_claim = bool(
            postgres_lease
            and lease_acquired
            and parent.status == "running"
            and meta_state == "claimed"
            and pause_cp is not None
        )
        if parent.status != "waiting_subflows":
            if parent.status == "running" and meta_state == "waiting" and pause_cp is None:
                db.commit()
                return {"status": "checkpoint_pending", "parent_run_id": parent.id}
            if not recovering_claim:
                db.commit()
                return {"status": "already_claimed", "parent_run_id": parent.id}
        if pause_cp is None:
            db.commit()
            return {"status": "checkpoint_pending", "parent_run_id": parent.id}

        strategy = str((waiting.get("_meta") or {}).get("strategy") or "all")
        revoke_ids: list[str] = []
        if strategy in {"any", "race"} and winner_id:
            reason = "subflow_race_lost" if strategy == "race" else "subflow_any_join_satisfied"
            revoke_ids = _cancel_losers(db, parent, waiting, winner_id, reason=reason)
            waiting = _refresh_entries(db, parent, waiting)

        child_entries = _active_waiting_entries(waiting)
        winner = next(
            (value for value in child_entries if str(value.get("child_run_id")) == winner_id),
            None,
        )
        propagated_failure = (
            strategy == "all" and any(value.get("status") != "completed" for value in child_entries)
        ) or (
            strategy == "any" and winner_id is None
        ) or (
            strategy == "race" and (winner is None or winner.get("status") != "completed")
        )
        if propagated_failure:
            now = datetime.utcnow()
            meta.update({"state": "failed", "winner_child_id": winner_id, "claimed_at": now.isoformat()})
            waiting["_meta"] = meta
            parent.waiting_subflows = waiting
            parent.status = "failed"
            parent.error = "delegated_subflow_failed"
            parent.completed_at = now
            parent.output_ref = {
                "subflows": {
                    str(value.get("node_id") or value.get("child_run_id")): {
                        "child_run_id": value.get("child_run_id"),
                        "status": value.get("status"),
                        "error": value.get("error"),
                    }
                    for value in child_entries
                }
            }
            parent.checkpoints = [
                *(parent.checkpoints or []),
                {
                    "kind": "run_end",
                    "t": now.isoformat(),
                    "status": "failed",
                    "error": parent.error,
                    "subflow_strategy": strategy,
                },
            ]
            db.commit()
            _revoke_tasks(revoke_ids)
            return {"id": parent.id, "status": "failed", "error": parent.error}

        # A successful join is about to re-enter executable graph code. Prove
        # its immutable task/retry/loop slugs before claiming the parent or
        # invoking any Skill. Pure terminal failure propagation above remains
        # available even for legacy orphaned parent fixtures.
        system = (
            db.query(System)
            .filter(
                System.id == parent.system_id,
                System.workspace_id == parent.workspace_id,
            )
            .first()
        )
        if system is None:
            parent.status = "failed"
            parent.error = "system_not_found"
            db.commit()
            return {"id": parent.id, "status": "failed", "error": parent.error}
        workspace = (
            db.query(Workspace)
            .filter(Workspace.id == (system.workspace_id or parent.workspace_id))
            .first()
            if (system.workspace_id or parent.workspace_id)
            else None
        )
        graph = DagGraph.from_flow_definition(
            parent.flow_snapshot or system.flow_definition or {}
        )
        graph.strict_authoritative = (
            graph.io_mode == "strict" and _workspace_strict_dag_enabled(workspace)
        )
        try:
            catalog_bindings = resolve_run_system_catalog_bindings(
                db,
                workspace=workspace,
                system=system,
                run=parent,
            )
            validate_graph_skill_bindings(graph, catalog_bindings)
        except SystemCatalogBindingError as exc:
            now = datetime.utcnow()
            parent.status = "failed"
            parent.error = f"system_catalog_binding_invalid:{exc.code}"
            parent.completed_at = now
            parent.checkpoints = [
                *(parent.checkpoints or []),
                {
                    "kind": "run_end",
                    "t": now.isoformat(),
                    "status": "failed",
                    "error": parent.error,
                    "resume_owner": owner,
                },
            ]
            db.commit()
            return {"id": parent.id, "status": "failed", "error": parent.error}

        claimed_at = datetime.utcnow().isoformat()
        generation = int(meta.get("resume_generation") or 0) + 1
        meta.update(
            {
                "state": "claimed",
                "winner_child_id": winner_id,
                "claimed_at": claimed_at,
                "resume_owner": owner,
                "resume_generation": generation,
                "last_delivery_redelivered": bool(redelivered),
            }
        )
        waiting["_meta"] = meta
        parent.waiting_subflows = waiting
        parent.status = "running"
        parent.checkpoints = [
            *(parent.checkpoints or []),
            {
                "kind": "subflow_resume_recovered" if recovering_claim else "subflow_resume",
                "t": claimed_at,
                "strategy": strategy,
                "winner_child_id": winner_id,
                "resume_owner": owner,
                "resume_generation": generation,
                "redelivered": bool(redelivered),
            },
        ]
        db.commit()  # row lock releases; advisory lease remains on this connection
        _revoke_tasks(revoke_ids)
        _maybe_crash_after_claim(parent, resume_owner=owner)

        state = WalkerState.from_payload(pause_cp.get("state") or {})
        state.start_monotonic = asyncio.get_running_loop().time()
        # The coordinator has already resolved this fan-out wave under the
        # parent lease. Materialise that durable result directly into the
        # checkpointed walker instead of asking every subflow node to inspect
        # its child again. In particular, a cancelled any/race loser must
        # never surface a concurrently-created HITL Decision on the parent.
        for _key, entry in _active_waiting_items(waiting):
            node_id = str(entry.get("node_id") or "")
            child_id = str(entry.get("child_run_id") or "")
            node = graph.nodes.get(node_id)
            if (
                not child_id
                or node is None
                or node.kind != "subflow"
                or node_id in state.done
            ):
                continue
            if strategy in {"any", "race"} and child_id != winner_id:
                outcome = {"output": {}}
            else:
                target_id = str((node.config or {}).get("system_id") or "")
                outcome = _settle_subflow_output(
                    db,
                    state,
                    child_id,
                    target_id,
                )
            _settle_node(graph, state, node_id, outcome)
        return await _walk(
            db,
            parent,
            graph,
            state,
            system=system,
            capability=catalog_bindings.capability,
            control=_load_control_policy(db, system),
            adaptive=catalog_bindings.adaptive_policy,
        )
    finally:
        try:
            db.close()
        finally:
            if lease_acquired:
                try:
                    if connection.in_transaction():
                        connection.rollback()
                    released = bool(
                        connection.execute(
                            text("SELECT pg_advisory_unlock(:lock_key)"),
                            {"lock_key": lock_key},
                        ).scalar()
                    )
                    connection.commit()
                    if not released:
                        connection.invalidate()
                except Exception:
                    # Closing the pinned connection is the final fail-safe and
                    # always releases a session advisory lock. Invalidate first
                    # so an uncertain session can never re-enter the pool.
                    connection.invalidate()
            connection.close()


async def resume_parent_for_child(
    child_run_id: str,
    *,
    resume_owner: str | None = None,
    redelivered: bool = False,
) -> dict[str, Any]:
    """Resolve a child's parent and delegate to the durable coordinator."""

    with SessionLocal() as lookup:
        child = lookup.query(Run).filter(Run.id == child_run_id).first()
        if (
            child is None
            or not child.parent_run_id
            or not child.delegation_key
        ):
            return {"status": "no_parent"}
        parent = (
            lookup.query(Run)
            .filter(
                Run.id == child.parent_run_id,
                Run.workspace_id == child.workspace_id,
            )
            .first()
        )
        if parent is None:
            return {"status": "invalid_delegation_context"}
        scoped_child = _scoped_child_query(
            lookup,
            parent=parent,
            delegation_key=child.delegation_key,
            child_run_id=child.id,
        ).first()
        if scoped_child is None:
            return {"status": "invalid_delegation_context"}
        delegation = (
            ((child.input_ref or {}).get("_delegation") or {})
            if isinstance(child.input_ref, dict)
            else {}
        )
        if (
            isinstance(delegation, dict)
            and delegation.get("execution_plane") == "celery"
            and delegated_celery_context(
                lookup,
                child=child,
                workspace_id=child.workspace_id,
            )
            is None
        ):
            return {"status": "invalid_delegation_context"}
        parent_run_id = parent.id
    return await resume_subflow_parent(
        parent_run_id,
        resume_owner=resume_owner,
        redelivered=redelivered,
    )


def resume_parent_for_child_sync(
    child_run_id: str,
    *,
    resume_owner: str | None = None,
    redelivered: bool = False,
) -> dict[str, Any]:
    return asyncio.run(
        resume_parent_for_child(
            child_run_id,
            resume_owner=resume_owner,
            redelivered=redelivered,
        )
    )


def resume_subflow_parent_sync(
    parent_run_id: str,
    *,
    resume_owner: str | None = None,
    redelivered: bool = False,
) -> dict[str, Any]:
    return asyncio.run(
        resume_subflow_parent(
            parent_run_id,
            resume_owner=resume_owner,
            redelivered=redelivered,
        )
    )


def _cancel_waiting_descendants(
    db: DBSession,
    parent: Run,
    *,
    reason: str,
    visited: set[str],
) -> tuple[int, list[str]]:
    """Cancel the active delegated subtree using one locked transaction."""

    if parent.id in visited:
        return 0, []
    visited.add(parent.id)
    waiting = deepcopy(parent.waiting_subflows or {})
    count = 0
    task_ids: list[str] = []
    for key, entry in _active_waiting_items(waiting):
        child_id = str(entry.get("child_run_id") or "")
        child = (
            _scoped_child_query(
                db,
                parent=parent,
                delegation_key=key,
                child_run_id=child_id,
            )
            .with_for_update()
            .first()
            if child_id
            else None
        )
        if child is None:
            continue
        if child.status not in TERMINAL:
            child.status = "cancelled"
            child.completed_at = datetime.utcnow()
            child.error = child.error or reason
            entry.update(
                {
                    "status": "cancelled",
                    "completed_at": child.completed_at.isoformat(),
                }
            )
            if child.celery_task_id:
                task_ids.append(child.celery_task_id)
            count += 1
        descendant_count, descendant_tasks = _cancel_waiting_descendants(
            db,
            child,
            reason=reason,
            visited=visited,
        )
        count += descendant_count
        task_ids.extend(descendant_tasks)
    parent.waiting_subflows = waiting
    return count, task_ids


def cancel_waiting_children(parent_run_id: str, *, reason: str = "parent_cancelled") -> int:
    """Recursively cancel the active delegated subtree without redispatch."""
    db: DBSession = SessionLocal()
    try:
        parent = db.query(Run).filter(Run.id == parent_run_id).with_for_update().first()
        if parent is None:
            return 0
        count, task_ids = _cancel_waiting_descendants(
            db,
            parent,
            reason=reason,
            visited=set(),
        )
        db.commit()
        _revoke_tasks(task_ids)
        return count
    finally:
        db.close()


def retry_ambiguous_dispatches(parent_run_id: str) -> dict[str, str]:
    """Migrate legacy ambiguous entries onto the transactional outbox.

    This compatibility hook is intentionally not a second broker publisher:
    it persists the same logical dispatch and lets the reconciler remain the
    single owner of RabbitMQ publication.
    """
    from app.models.run_dispatch_outbox import RunDispatchOutbox

    from .dispatch_outbox import SUBFLOW_RUN, enqueue_dispatch, reconcile_dispatch_outbox

    db: DBSession = SessionLocal()
    results: dict[str, str] = {}
    event_ids: dict[str, str] = {}
    try:
        parent = db.query(Run).filter(Run.id == parent_run_id).with_for_update().first()
        if parent is None:
            return results
        waiting = dict(parent.waiting_subflows or {})
        for key, entry in _active_waiting_items(waiting):
            if entry.get("dispatch_state") != "ambiguous":
                continue
            child_id = str(entry.get("child_run_id") or "")
            child = (
                _scoped_child_query(
                    db,
                    parent=parent,
                    delegation_key=key,
                    child_run_id=child_id,
                ).first()
                if child_id
                else None
            )
            if child is None or child.status in TERMINAL:
                continue
            event = enqueue_dispatch(
                db,
                event_type=SUBFLOW_RUN,
                workspace_id=str(parent.workspace_id),
                run_id=child.id,
                source_id=child.delegation_key,
                wave_id=entry.get("wave_id"),
            )
            event_ids[key] = event.id
            entry.update(
                {
                    "celery_task_id": event.task_id,
                    "dispatch_state": "outbox_pending",
                }
            )
            results[key] = "outbox_pending"
        parent.waiting_subflows = waiting
        db.commit()
    finally:
        db.close()
    if not event_ids:
        return results
    try:
        reconcile_dispatch_outbox(batch_size=max(50, len(event_ids)), lease_seconds=60)
    except Exception:
        return results
    with SessionLocal() as settled_db:
        states = {
            row.id: row.state
            for row in settled_db.query(RunDispatchOutbox)
            .filter(RunDispatchOutbox.id.in_(event_ids.values()))
            .all()
        }
    for key, event_id in event_ids.items():
        state = states.get(event_id, "missing")
        results[key] = "dispatched" if state == "published" else state
    return results
