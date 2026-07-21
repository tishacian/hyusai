"""Durable parent/child coordination for Celery delegated Runs.

This module deliberately owns only persisted coordination.  Celery messages
carry a child Run id; all mutable inputs, join state and lineage are reloaded
under database locks.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.db.base import SessionLocal
from app.models.capability import Capability
from app.models.run import Run
from app.models.system import System
from app.models.workspace import Workspace

TERMINAL = {"completed", "failed", "cancelled"}


def validate_contract(payload: Any, contract: dict[str, Any]) -> bool:
    """Validate the JSON-schema subset used by delegation ACLs.

    Supported keywords are ``type``, ``required``, ``properties`` and nested
    objects/arrays. A compact ``{field: type}`` map is accepted as shorthand.
    Unknown schema keywords are ignored, keeping validation deterministic and
    dependency-free inside workers.
    """
    if not contract:
        return True
    if not any(key in contract for key in ("type", "required", "properties", "items")):
        contract = {
            "type": "object",
            "required": list(contract),
            "properties": {
                str(key): value if isinstance(value, dict) else {"type": str(value)}
                for key, value in contract.items()
            },
        }
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
            if key in payload and isinstance(child_contract, dict):
                if not validate_contract(payload[key], child_contract):
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


def resolve_waiting(waiting: dict[str, Any]) -> tuple[bool, str | None]:
    """Resolve all/any/race deterministically from persisted child states."""
    entries = [v for k, v in waiting.items() if k != "_meta" and isinstance(v, dict)]
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


def _refresh_entries(db: DBSession, waiting: dict[str, Any]) -> dict[str, Any]:
    result = {k: dict(v) if isinstance(v, dict) else v for k, v in waiting.items()}
    for key, entry in list(result.items()):
        if key == "_meta" or not isinstance(entry, dict):
            continue
        child_id = entry.get("child_run_id")
        child = db.query(Run).filter(Run.id == child_id).first() if child_id else None
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
    waiting: dict[str, Any],
    winner_id: str,
    *,
    reason: str = "subflow_race_lost",
) -> list[str]:
    """Persist cancellation before best-effort broker revoke for race losers."""
    task_ids = []
    for key, entry in waiting.items():
        if key == "_meta" or not isinstance(entry, dict):
            continue
        child_id = str(entry.get("child_run_id") or "")
        if not child_id or child_id == winner_id:
            continue
        child = db.query(Run).filter(Run.id == child_id).with_for_update().first()
        if child is None or child.status in TERMINAL:
            continue
        child.status = "cancelled"
        child.completed_at = datetime.utcnow()
        child.error = child.error or reason
        entry.update({"status": "cancelled", "completed_at": child.completed_at.isoformat()})
        if child.celery_task_id:
            task_ids.append(child.celery_task_id)
    # Caller commits this together with the parent's claimed state while the
    # parent row lock is still held; otherwise two child callbacks could both
    # observe an unclaimed parent between cancellation and claim.
    return task_ids


async def resume_parent_for_child(child_run_id: str) -> dict[str, Any]:
    """Atomically claim and resume a ready parent after a child transition."""
    from .dag import (
        DagGraph,
        WalkerState,
        _load_adaptive_policy,
        _load_control_policy,
        _walk,
        _workspace_strict_dag_enabled,
    )

    db: DBSession = SessionLocal()
    try:
        child = db.query(Run).filter(Run.id == child_run_id).first()
        if child is None or not child.parent_run_id:
            return {"status": "no_parent"}
        parent = (
            db.query(Run)
            .filter(Run.id == child.parent_run_id, Run.workspace_id == child.workspace_id)
            .with_for_update()
            .first()
        )
        if parent is None:
            return {"status": "parent_missing"}

        waiting = _refresh_entries(db, dict(parent.waiting_subflows or {}))
        parent.waiting_subflows = waiting
        # HITL is propagated as durable child state; only the child Decision
        # may unblock it, and redelivery continues to reference this same Run.
        if child.status == "hitl_pending":
            db.commit()
            return {"status": "waiting_hitl", "parent_run_id": parent.id, "child_run_id": child.id}

        ready, winner_id = resolve_waiting(waiting)
        if not ready:
            db.commit()
            return {"status": "waiting", "parent_run_id": parent.id}
        checkpoints = list(parent.checkpoints or [])
        pause_cp = next((cp for cp in reversed(checkpoints) if cp.get("kind") == "subflow_wait"), None)
        if parent.status != "waiting_subflows":
            meta_state = str((waiting.get("_meta") or {}).get("state") or "waiting")
            if parent.status == "running" and meta_state == "waiting" and pause_cp is None:
                db.commit()
                return {"status": "checkpoint_pending", "parent_run_id": parent.id}
            db.commit()
            return {"status": "already_claimed", "parent_run_id": parent.id}
        if pause_cp is None:
            db.commit()
            return {"status": "checkpoint_pending", "parent_run_id": parent.id}

        strategy = str((waiting.get("_meta") or {}).get("strategy") or "all")
        revoke_ids: list[str] = []
        if strategy in {"any", "race"} and winner_id:
            reason = "subflow_race_lost" if strategy == "race" else "subflow_any_join_satisfied"
            revoke_ids = _cancel_losers(db, waiting, winner_id, reason=reason)
            waiting = _refresh_entries(db, waiting)

        child_entries = [
            value for key, value in waiting.items() if key != "_meta" and isinstance(value, dict)
        ]
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
            meta = dict(waiting.get("_meta") or {})
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

        meta = dict(waiting.get("_meta") or {})
        claimed_at = datetime.utcnow().isoformat()
        meta.update({"state": "claimed", "winner_child_id": winner_id, "claimed_at": claimed_at})
        waiting["_meta"] = meta
        parent.waiting_subflows = waiting
        parent.status = "running"
        parent.checkpoints = [
            *(parent.checkpoints or []),
            {
                "kind": "subflow_resume",
                "t": claimed_at,
                "strategy": strategy,
                "winner_child_id": winner_id,
            },
        ]
        db.commit()  # releases the row lock; duplicate callbacks now observe claimed
        _revoke_tasks(revoke_ids)

        system = db.query(System).filter(System.id == parent.system_id).first()
        if system is None:
            parent.status = "failed"
            parent.error = "system_not_found"
            db.commit()
            return {"id": parent.id, "status": "failed", "error": parent.error}
        workspace = (
            db.query(Workspace).filter(Workspace.id == (system.workspace_id or parent.workspace_id)).first()
            if (system.workspace_id or parent.workspace_id)
            else None
        )
        graph = DagGraph.from_flow_definition(parent.flow_snapshot or system.flow_definition or {})
        graph.strict_authoritative = graph.io_mode == "strict" and _workspace_strict_dag_enabled(workspace)
        state = WalkerState.from_payload(pause_cp.get("state") or {})
        state.start_monotonic = asyncio.get_running_loop().time()
        capability = (
            db.query(Capability).filter(Capability.id == system.capability_id).first()
            if system.capability_id
            else None
        )
        return await _walk(
            db,
            parent,
            graph,
            state,
            system=system,
            capability=capability,
            control=_load_control_policy(db, system),
            adaptive=_load_adaptive_policy(db, system),
        )
    finally:
        db.close()


def resume_parent_for_child_sync(child_run_id: str) -> dict[str, Any]:
    return asyncio.run(resume_parent_for_child(child_run_id))


def cancel_waiting_children(parent_run_id: str, *, reason: str = "parent_cancelled") -> int:
    """Propagate parent cancellation without creating or redispatching children."""
    db: DBSession = SessionLocal()
    try:
        parent = db.query(Run).filter(Run.id == parent_run_id).with_for_update().first()
        if parent is None:
            return 0
        waiting = dict(parent.waiting_subflows or {})
        count = 0
        task_ids: list[str] = []
        for key, entry in waiting.items():
            if key == "_meta" or not isinstance(entry, dict):
                continue
            child = db.query(Run).filter(Run.id == entry.get("child_run_id")).with_for_update().first()
            if child is not None and child.status not in TERMINAL:
                child.status = "cancelled"
                child.completed_at = datetime.utcnow()
                child.error = child.error or reason
                entry["status"] = "cancelled"
                if child.celery_task_id:
                    task_ids.append(child.celery_task_id)
                count += 1
        parent.waiting_subflows = waiting
        db.commit()
        _revoke_tasks(task_ids)
        return count
    finally:
        db.close()


def retry_ambiguous_dispatches(parent_run_id: str) -> dict[str, str]:
    """Retry broker-ambiguous dispatches without changing logical identity."""
    from .engine import schedule_subflow_run

    db: DBSession = SessionLocal()
    results: dict[str, str] = {}
    try:
        parent = db.query(Run).filter(Run.id == parent_run_id).with_for_update().first()
        if parent is None:
            return results
        waiting = dict(parent.waiting_subflows or {})
        for key, entry in waiting.items():
            if key == "_meta" or not isinstance(entry, dict):
                continue
            if entry.get("dispatch_state") != "ambiguous":
                continue
            child = db.query(Run).filter(Run.id == entry.get("child_run_id")).first()
            if child is None or child.status in TERMINAL:
                continue
            try:
                task_id = schedule_subflow_run(child.id)
            except RuntimeError:
                results[key] = "ambiguous"
                continue
            child.celery_task_id = task_id
            entry.update({"celery_task_id": task_id, "dispatch_state": "dispatched"})
            results[key] = "dispatched"
        parent.waiting_subflows = waiting
        db.commit()
        return results
    finally:
        db.close()
