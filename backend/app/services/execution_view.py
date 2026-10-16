"""Versioned, payload-free reading of a Run's frozen graph and native work.

This service never dispatches, validates a draft, backfills or commits. Native
read policies are applied before totals, node summaries and page selection.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from urllib.parse import quote

from fastapi import HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.orm import load_only

from app.core.config import settings
from app.models.activity import Activity
from app.models.compute_run import ComputeRun
from app.models.execution_control import ExecutionReservation
from app.models.recipe import RecipeExecution
from app.models.run import Run, SkillInvocation
from app.models.service_contract import AssetVersion, DeliveryReceipt, ServiceAttempt, ServiceWindow
from app.models.tabular import MLModel
from app.models.workspace_job import WorkspaceJob
from app.services.activity_observability import queries
from app.services.activity_observability.execution_metadata import (
    correlation,
    invocation_cost,
    label,
    receipt_metadata_visible,
    token,
    transitions,
)
from app.services.activity_observability.projection import STATUS_MAP, activity_id, iso, number
from app.services.flow_node_kind import flow_node_kind
from app.services.huggingface.access import is_workspace_admin
from app.services.run_access import readable_runs, readable_skill_invocations_for_runs


def safe_graph(snapshot):
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("nodes"), list):
        return {"available": False, "nodes": [], "edges": []}
    nodes, edges, seen = [], [], set()
    for raw in snapshot["nodes"]:
        if (
            not isinstance(raw, dict)
            or not (identifier := token(raw.get("id")))
            or identifier in seen
        ):
            continue
        seen.add(identifier)
        data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
        nodes.append(
            {
                "id": identifier,
                "kind": token(flow_node_kind(raw)) or "unknown",
                "label": label(raw.get("label")) or label(data.get("title")) or identifier,
            }
        )
    for index, raw in enumerate(
        snapshot.get("edges", []) if isinstance(snapshot.get("edges"), list) else []
    ):
        if not isinstance(raw, dict):
            continue
        source, target = (
            token(raw.get("from") or raw.get("source")),
            token(raw.get("to") or raw.get("target")),
        )
        if source not in seen or target not in seen:
            continue
        edges.append(
            {
                "id": token(raw.get("id")) or f"edge:{index}",
                "source": source,
                "target": target,
                "kind": token(raw.get("kind")) or "data",
                "label": label(raw.get("branch_label")) or label(raw.get("label")),
            }
        )
    return {"available": True, "nodes": nodes, "edges": edges}


def _base(source, native_id, node_id, *, passage_id=None):
    return {
        "id": f"{source}:{native_id}",
        "source": source,
        "native_id": native_id,
        "node_id": node_id,
        "passage_id": passage_id or f"{source}:{native_id}",
        "activity_id": None,
        "status": "unknown",
        "native_status": "unknown",
        "relation": None,
        "attempt_index": None,
        "iteration": None,
        "branch": None,
        "started_at": None,
        "finished_at": None,
        "duration_ms": None,
        "waiting_reason": None,
        "measurements": {"provider_cost_usd": None, "cost_known": False},
        "coverage": "partial",
        "links": [],
        "runtime": None,
        "placement": None,
        "intervals": [],
    }


def _native(item, row, *, start="started_at", finish="finished_at", duration="duration_ms"):
    native_status = row.status if row.status in STATUS_MAP else "unknown"
    item.update(
        status=STATUS_MAP.get(native_status, "unknown"),
        native_status=native_status,
        started_at=iso(getattr(row, start, None)),
        finished_at=iso(getattr(row, finish, None)),
        duration_ms=number(getattr(row, duration, None)),
    )
    if row.status in {"queued", "pending"}:
        item["waiting_reason"] = "queue"  # Proven native admission state.
    elif row.status in {"hitl_pending", "debug_pending"}:
        item["waiting_reason"] = "human"
    elif row.status == "waiting_subflows":
        item["waiting_reason"] = "external"
    if item["started_at"]:
        item["intervals"] = [
            {
                "id": item["id"],
                "phase": "execution",
                "started_at": item["started_at"],
                "finished_at": item["finished_at"],
                "coverage": "native_timestamps",
            }
        ]
    return item


def _checkpoint_passages(run):
    """Explicit passage linkage for new rows; labelled partial on legacy order."""
    passages, current = {}, {}
    for event in transitions(run.checkpoints, run.id):
        node_id = event["node_id"]
        identifier = event["passage_id"]
        if identifier is None:
            if event["kind"] == "node_start":
                identifier = event["id"]
            else:
                identifier = current.get(node_id) or event["id"]
        current[node_id] = identifier
        if identifier not in passages:
            passages[identifier] = _base("checkpoint", event["id"], node_id, passage_id=identifier)
        passage = passages[identifier]
        passage["coverage"] = (
            "exact" if event["coverage"] == "exact" and passage.get("_exact", True) else "partial"
        )
        passage["_exact"] = passage["coverage"] == "exact"
        when = iso(event["t"])
        if event["kind"] == "node_start":
            passage["status"], passage["native_status"] = "running", "running"
            # Retransmission/pings cannot move an observed start.
            passage["started_at"] = passage["started_at"] or when
        elif event["kind"] in {"hitl_pause", "debug_pause", "subflow_wait"} or event["pause"]:
            passage["status"], passage["native_status"] = "waiting", event["kind"]
            passage["waiting_reason"] = (
                "external"
                if event["kind"] == "subflow_wait"
                else "human"
                if event["kind"] in {"hitl_pause", "debug_pause"}
                else "unavailable"
            )
        elif event["kind"] in {"hitl_resume", "debug_resume", "subflow_resume"}:
            passage["status"], passage["native_status"] = "running", event["kind"]
            passage["waiting_reason"] = None
        elif event["kind"] in {"node_end", "node_skipped"}:
            passage["native_status"] = event["native_status"] or "unknown"
            passage["status"] = (
                "not_executed"
                if event["native_status"] == "skipped" or event["kind"] == "node_skipped"
                else STATUS_MAP.get(event["native_status"], "unknown")
            )
            passage["finished_at"] = when
            passage["waiting_reason"] = None
            passage["skipped_reason"] = event["skipped_reason"]
        # Preserve the measured phases, not just a final status. Null ends
        # remain open/unknown, never a zero-duration segment.
        phase = (
            "human"
            if passage["waiting_reason"] == "human"
            else "external"
            if passage["waiting_reason"] == "external"
            else "waiting"
            if passage["status"] == "waiting"
            else "execution"
            if passage["status"] == "running"
            else None
        )
        intervals = passage["intervals"]
        if (
            intervals
            and intervals[-1]["finished_at"] is None
            and (phase != intervals[-1]["phase"] or phase is None)
        ):
            intervals[-1]["finished_at"] = when
        if phase and (
            not intervals
            or intervals[-1]["phase"] != phase
            or intervals[-1]["finished_at"] is not None
        ):
            intervals.append(
                {
                    "id": event["id"],
                    "phase": phase,
                    "started_at": when,
                    "finished_at": None,
                    "coverage": event["coverage"],
                }
            )
        passage["last_transition_id"] = event["id"]
    for passage in passages.values():
        passage.pop("_exact", None)
    return list(passages.values())


def _invocations(db, run, workspace, user):
    items = []
    columns = (
        SkillInvocation.id,
        SkillInvocation.run_id,
        SkillInvocation.skill_id,
        SkillInvocation.skill_slug,
        SkillInvocation.trace,
        SkillInvocation.status,
        SkillInvocation.started_at,
        SkillInvocation.completed_at,
        SkillInvocation.latency_ms,
        SkillInvocation.provider_cost_usd,
        SkillInvocation.cost_measured,
        SkillInvocation.cost,
        SkillInvocation.metrics,
    )
    query = (
        db.query(SkillInvocation)
        .options(load_only(*columns))
        .filter(SkillInvocation.run_id == run.id)
    )
    last = None
    while True:
        batch = (
            (query.filter(SkillInvocation.id > last) if last else query)
            .order_by(SkillInvocation.id)
            .limit(250)
            .all()
        )
        if not batch:
            break
        allowed = readable_skill_invocations_for_runs(
            db, invocations=batch, runs=[run], user=user, workspace=workspace
        )
        # DeferredNativeExecution currently supports only recipes. A generic
        # waiting status alone is not evidence of an external dependency.
        references = {}
        for row in allowed:
            trace = row.trace if isinstance(row.trace, dict) else {}
            reference = trace.get("native_reference")
            if (
                row.status == "waiting"
                and isinstance(reference, dict)
                and reference.get("kind") == "recipe_execution"
                and token(reference.get("id"))
            ):
                references[row.id] = reference["id"]
        deferred_nodes = (
            dict(
                db.query(RecipeExecution.id, RecipeExecution.node_id)
                .filter(
                    RecipeExecution.workspace_id == workspace.id,
                    RecipeExecution.run_id == run.id,
                    RecipeExecution.id.in_(set(references.values())),
                )
                .all()
            )
            if references
            else {}
        )
        for row in allowed:
            corr = correlation(row.trace)
            item = _native(
                _base("skill_invocation", row.id, corr["node_id"], passage_id=corr["passage_id"]),
                row,
                finish="completed_at",
                duration="latency_ms",
            )
            item.update({key: corr[key] for key in ("attempt_index", "iteration", "attempt_kind")})
            if corr["node_id"] and deferred_nodes.get(references.get(row.id)) == corr["node_id"]:
                item["waiting_reason"] = "external"
            item["coverage"] = "exact" if corr["node_id"] and corr["passage_id"] else "partial"
            item["measurements"] = invocation_cost(
                cost=row.cost,
                provider_cost_usd=row.provider_cost_usd,
                cost_measured=row.cost_measured,
                metrics=row.metrics,
            )
            item["links"] = [
                {
                    "rel": "invocation",
                    "href": f"/runs/{quote(run.id, safe='')}/invocations/{quote(row.id, safe='')}",
                }
            ]
            items.append(item)
        last = batch[-1].id
    return items


def _other_work(db, run, workspace, user, invocation_items):
    items = []
    # A Recipe's invocation is explicit evidence, but may be less readable than its Run.
    inv_by_id = {item["native_id"]: item for item in invocation_items}
    recipes = (
        db.query(RecipeExecution)
        .options(
            load_only(
                RecipeExecution.id,
                RecipeExecution.workspace_id,
                RecipeExecution.run_id,
                RecipeExecution.node_id,
                RecipeExecution.invocation_id,
                RecipeExecution.status,
                RecipeExecution.started_at,
                RecipeExecution.finished_at,
                RecipeExecution.duration_ms,
            )
        )
        .filter(RecipeExecution.workspace_id == workspace.id, RecipeExecution.run_id == run.id)
    )
    for row in recipes.yield_per(250):
        if row.invocation_id and row.invocation_id not in inv_by_id:
            continue
        invocation = inv_by_id.get(row.invocation_id)
        item = _native(
            _base(
                "recipe_execution",
                row.id,
                token(row.node_id) or (invocation or {}).get("node_id"),
                passage_id=(invocation or {}).get("passage_id"),
            ),
            row,
        )
        item["runtime"] = "recipes"
        item["coverage"] = (
            "exact" if invocation and invocation["coverage"] == "exact" else "partial"
        )
        items.append(item)
    recipes_by_id = {item["native_id"]: item for item in items}
    computes = (
        db.query(ComputeRun)
        .options(
            load_only(
                ComputeRun.id,
                ComputeRun.workspace_id,
                ComputeRun.user_id,
                ComputeRun.run_id,
                ComputeRun.node_id,
                ComputeRun.attempt,
                ComputeRun.recipe_execution_id,
                ComputeRun.placement,
                ComputeRun.status,
                ComputeRun.started_at,
                ComputeRun.finished_at,
                ComputeRun.cost_usd,
                ComputeRun.core_hours,
                ComputeRun.cpu_cores,
                ComputeRun.memory_mb,
                ComputeRun.outcome_unknown,
            )
        )
        .filter(ComputeRun.workspace_id == workspace.id, ComputeRun.run_id == run.id)
    )
    if not is_workspace_admin(db, user, workspace):
        computes = computes.filter(ComputeRun.user_id == user.id)
    for row in computes.yield_per(250):
        recipe = recipes_by_id.get(row.recipe_execution_id)
        if row.recipe_execution_id and not recipe:
            continue
        item = _native(
            _base(
                "compute_run",
                row.id,
                token(row.node_id) or (recipe or {}).get("node_id"),
                passage_id=(recipe or {}).get("passage_id"),
            ),
            row,
        )
        item.update(
            attempt_index=row.attempt,
            placement=row.placement,
            runtime=None,
            outcome_unknown=row.outcome_unknown,
        )
        if row.outcome_unknown:
            item["status"] = "unknown"  # Native explicit external-effect uncertainty.
        item["measurements"] = {
            "provider_cost_usd": None,
            "cost_known": number(row.cost_usd) is not None,
            "cost_amount": number(row.cost_usd),
            "currency": "USD" if number(row.cost_usd) is not None else None,
            "infrastructure_cost_usd": number(row.cost_usd),
            "core_hours": number(row.core_hours),
            "allocated_core_hours": number(row.core_hours),
            "resource_basis": "requested_resources_x_wall_time",
            "cpu_cores": number(row.cpu_cores),
            "memory_mb": number(row.memory_mb),
            "cost_basis": "infrastructure_allocation",
        }
        item["coverage"] = "exact" if token(row.node_id) else "partial"
        items.append(item)
    children = (
        db.query(Run)
        .filter(Run.workspace_id == workspace.id, Run.parent_run_id == run.id)
        .order_by(Run.id)
    )
    for child in children.yield_per(250):
        if not readable_runs(db, runs=[child], user=user, workspace=workspace):
            continue
        item = _native(
            _base("run", child.id, token(child.delegation_node_id)), child, finish="completed_at"
        )
        item["relation"] = (
            "delegation"
            if child.delegation_key
            else "replay"
            if child.trigger in {"replay", "rerun"}
            else None
        )
        item["branch"] = label(child.delegation_branch)
        item["coverage"] = "exact" if item["relation"] else "partial"
        item["links"] = [{"rel": "run", "href": f"/runs/{quote(child.id, safe='')}?view=flow"}]
        items.append(item)
    return items


def _attached_work(db, run, workspace, user):
    """Only persisted lineage; a model/job never inherits a node from its slug."""
    from app.api.v1.endpoints.workspace_jobs import _can_access_job

    items = []
    models = (
        db.query(MLModel)
        .options(
            load_only(
                MLModel.id,
                MLModel.run_id,
                MLModel.node_id,
                MLModel.status,
                MLModel.created_at,
                MLModel.trained_at,
                MLModel.train_duration_ms,
            )
        )
        .filter(MLModel.workspace_id == workspace.id, MLModel.run_id == run.id)
    )
    for row in models.yield_per(250):
        item = _native(
            _base("ml_training", row.id, token(row.node_id)),
            row,
            start="created_at",
            finish="trained_at",
            duration="train_duration_ms",
        )
        # created_at is admission, not proof of when training actually started.
        item["created_at"] = item["started_at"]
        item["started_at"], item["intervals"] = None, []
        item["coverage"] = "exact" if item["node_id"] else "partial"
        item["links"] = [{"rel": "model", "href": f"/models/{quote(row.id, safe='')}"}]
        items.append(item)
    for row in (
        db.query(WorkspaceJob)
        .filter(WorkspaceJob.workspace_id == workspace.id, WorkspaceJob.run_id == run.id)
        .yield_per(250)
    ):
        if not _can_access_job(db, row, user, workspace):
            continue
        items.append(_native(_base("workspace_job", row.id, None), row, finish="completed_at"))
    window_ids = db.query(ServiceAttempt.window_id).filter_by(
        workspace_id=workspace.id, run_id=run.id
    )
    windows = db.query(ServiceWindow).filter(
        ServiceWindow.workspace_id == workspace.id, ServiceWindow.id.in_(window_ids)
    )
    for row in windows.yield_per(250):
        projected = (
            db.query(Activity)
            .filter_by(workspace_id=workspace.id, kind="service_window", native_id=row.id)
            .first()
        )
        if not projected or not queries.filter_visible(db, [projected], workspace, user):
            continue
        item = _native(_base("service_window", row.id, None), row)
        item["relation"] = "service_delivery"
        item["links"] = [{"rel": "service", "href": "/work/services"}]
        items.append(item)
    # The asset carries its producing Run; no relation is inferred from a date
    # or from a shared System. Receipt evidence keeps its independent guard.
    receipts = (
        db.query(DeliveryReceipt)
        .join(
            AssetVersion,
            and_(
                AssetVersion.id == DeliveryReceipt.asset_id,
                AssetVersion.workspace_id == DeliveryReceipt.workspace_id,
            ),
        )
        .filter(DeliveryReceipt.workspace_id == workspace.id, AssetVersion.run_id == run.id)
    )
    for row in receipts.yield_per(250):
        if not receipt_metadata_visible(db, workspace, user, row.id):
            continue
        item = _base("delivery_receipt", row.id, None)
        item.update(
            status="succeeded",
            native_status="published",
            finished_at=iso(row.published_at),
            relation="service_delivery",
        )
        item["links"] = [{"rel": "service", "href": "/work/services"}]
        items.append(item)
    return items


def _resource_measurements(db, workspace, items):
    """Read only already-authorized native identities; never policy or lease data."""
    for start in range(0, len(items), 250):
        batch = items[start : start + 250]
        by_native = {(item["source"], item["native_id"]): item for item in batch}
        clauses = [
            and_(
                ExecutionReservation.entity_kind == kind,
                ExecutionReservation.entity_id.in_(
                    [identifier for candidate, identifier in by_native if candidate == kind]
                ),
            )
            for kind in {key[0] for key in by_native}
        ]
        rows = (
            db.query(ExecutionReservation)
            .options(
                load_only(
                    ExecutionReservation.entity_kind,
                    ExecutionReservation.entity_id,
                    ExecutionReservation.cpu_cores,
                    ExecutionReservation.memory_mb,
                    ExecutionReservation.allocated_core_hours,
                    ExecutionReservation.reserved_core_hours,
                    ExecutionReservation.cpu_seconds,
                    ExecutionReservation.peak_rss_bytes,
                    ExecutionReservation.deadline_at,
                    ExecutionReservation.released_at,
                    ExecutionReservation.lane,
                )
            )
            .filter(ExecutionReservation.workspace_id == workspace.id, or_(*clauses))
            .all()
        )
        for allocation in rows:
            item = by_native[(allocation.entity_kind, allocation.entity_id)]
            item["measurements"].update(
                {
                    "cpu_cores": number(allocation.cpu_cores),
                    "memory_mb": number(allocation.memory_mb),
                    "allocated_core_hours": number(allocation.allocated_core_hours),
                    "reserved_core_hours": number(allocation.reserved_core_hours),
                    "cpu_seconds": number(allocation.cpu_seconds),
                    "peak_memory_bytes": number(allocation.peak_rss_bytes),
                    "resource_basis": "requested_resources_x_wall_time",
                }
            )
            item["resource_coverage"] = (
                "measured" if allocation.cpu_seconds is not None else "allocation_only"
            )
            item["coordination"] = {
                "lane": allocation.lane,
                "deadline_at": iso(allocation.deadline_at),
                "released_at": iso(allocation.released_at),
            }


def execution_view(
    db, workspace, user, run_id, *, node_id=None, activity_id_filter=None, limit=50, offset=0
):
    if not getattr(settings, "execution_view_enabled", False):
        raise HTTPException(404, detail="EXECUTION_VIEW_DISABLED")
    if not 1 <= limit <= 100 or offset < 0:
        raise HTTPException(422, detail="EXECUTION_VIEW_PAGE_INVALID")
    queries.require_membership(db, workspace, user)
    # Read BEFORE native snapshots. Every concurrent committed transition after
    # this cursor is replayed, even if it was already included in this response.
    cursor = queries.encode_cursor(workspace.id, queries.highwater(db, workspace.id))
    run = queries.authorized_run(db, run_id, workspace, user)
    graph = safe_graph(run.flow_snapshot)
    checkpoint_items = _checkpoint_passages(run)
    invocations = _invocations(db, run, workspace, user)
    items = (
        invocations
        + _other_work(db, run, workspace, user, invocations)
        + _attached_work(db, run, workspace, user)
    )
    _resource_measurements(db, workspace, items)
    # Reference only actual readable projection rows. No fabricated Activities.
    native_ids = [activity_id(item["source"], item["native_id"]) for item in items]
    projections = []
    for start in range(0, len(native_ids), 250):
        projections.extend(
            queries.filter_visible(
                db,
                db.query(Activity)
                .filter(
                    Activity.workspace_id == workspace.id,
                    Activity.id.in_(native_ids[start : start + 250]),
                )
                .all(),
                workspace,
                user,
            )
        )
    by_native = {(row.kind, row.native_id): row for row in projections}
    for item in items:
        projected = by_native.get((item["source"], item["native_id"]))
        if projected:
            item["activity_id"] = projected.id
            item["links"].append(
                {
                    "rel": "activity",
                    "href": f"/observability?facet=activities&activityId={quote(projected.id, safe='')}",
                }
            )
    checkpoint_by_passage = {item["passage_id"]: item for item in checkpoint_items}
    for item in items:
        checkpoint = checkpoint_by_passage.get(item["passage_id"])
        if checkpoint:
            # Passage intervals describe the node envelope; native work keeps
            # its own timestamps so retries are never displayed as one call.
            item["passage_intervals"] = checkpoint["intervals"]
    concrete_passages = {item["passage_id"] for item in items}
    concrete_nodes = {item["node_id"] for item in items}
    # Avoid duplicating a job as its own checkpoint. Legacy relations remain
    # partial instead of guessing matches by time or by a shared Skill slug.
    items.extend(
        item
        for item in checkpoint_items
        if item["passage_id"] not in concrete_passages
        and (item["coverage"] == "exact" or item["node_id"] not in concrete_nodes)
    )
    grouped = defaultdict(list)
    for item in items:
        if item["node_id"]:
            grouped[item["node_id"]].append(item)
    last_checkpoint = {item["node_id"]: item for item in checkpoint_items}
    node_ids = [node["id"] for node in graph["nodes"]]
    node_ids.extend(sorted(set(grouped) - set(node_ids)))
    summaries = []
    has_uncorrelated_work = any(item["node_id"] is None for item in items)
    for identifier in node_ids:
        work = grouped[identifier]
        counts = Counter(item["status"] for item in work)
        checkpoint = last_checkpoint.get(identifier)
        status = "unknown" if has_uncorrelated_work else "not_started"
        waiting = "unavailable" if has_uncorrelated_work else None
        if work:
            # Latest observed work, not a synthetic aggregate sum of branch durations.
            latest = max(work, key=lambda item: (item["started_at"] or "", item["id"]))
            status, waiting = latest["status"], latest["waiting_reason"]
            for state in ("running", "waiting", "pending"):
                if counts[state]:
                    status = state
                    waiting = next(
                        (item["waiting_reason"] for item in work if item["status"] == state), None
                    )
                    break
        if checkpoint and checkpoint["status"] in {"waiting", "not_executed"}:
            status, waiting = checkpoint["status"], checkpoint["waiting_reason"]
        summary = {
            "node_id": identifier,
            "status": status,
            "waiting_reason": waiting,
            "counts": {"total": len(work), **dict(counts)},
            "passages_total": len({item["passage_id"] for item in work}),
            "coverage": "exact"
            if work and all(item["coverage"] == "exact" for item in work)
            else "partial"
            if work
            else "absent",
        }
        if checkpoint and checkpoint.get("skipped_reason"):
            summary["skipped_reason"] = checkpoint["skipped_reason"]
        summaries.append(summary)
    if node_id and node_id not in node_ids:
        raise HTTPException(404, detail="EXECUTION_NODE_NOT_FOUND")
    if activity_id_filter:
        # A readable activity from an unrelated Run cannot select/leak a node.
        selected = next((item for item in items if item["activity_id"] == activity_id_filter), None)
        root_selection = activity_id_filter == activity_id("run", run.id)
        if root_selection:
            queries.authorized_activity(db, activity_id_filter, workspace, user)
        if not root_selection and (not selected or (node_id and selected["node_id"] != node_id)):
            raise HTTPException(404, detail="ACTIVITY_NOT_FOUND")
    items.sort(key=lambda item: (item["started_at"] or "", item["id"]))
    payload = {
        "schema_version": 1,
        "run": {
            "id": run.id,
            "system_id": run.system_id,
            "status": STATUS_MAP.get(run.status, "unknown"),
            "native_status": run.status if run.status in STATUS_MAP else "unknown",
            "started_at": iso(run.started_at),
            "finished_at": iso(run.completed_at),
            "flow_version_id": run.flow_version_id,
            "flow_sha256": run.flow_sha256,
            "trigger": token(run.trigger),
        },
        "graph": graph,
        "nodes": summaries,
        "snapshot_cursor": cursor,
        "coverage": {
            "correlation": "exact"
            if items and all(item["coverage"] == "exact" for item in items)
            else "partial"
            if items
            else "absent",
            "graph": "snapshot" if graph["available"] else "unavailable",
            "timeline": "complete"
            if items and all(item["started_at"] and item["finished_at"] for item in items)
            else "partial",
        },
        "capabilities": {"read_only": True, "live": queries.enabled()},
    }
    # Content version excludes pagination and stream pings; reconnect is idempotent.
    revision = {key: value for key, value in payload.items() if key != "snapshot_cursor"}
    payload["read_version"] = hashlib.sha256(
        json.dumps({**revision, "items": items}, sort_keys=True).encode()
    ).hexdigest()
    selected_items = [item for item in items if not node_id or item["node_id"] == node_id]
    payload.update(
        total=len(selected_items),
        limit=limit,
        offset=offset,
        has_more=offset + limit < len(selected_items),
        items=selected_items[offset : offset + limit],
    )
    return payload
