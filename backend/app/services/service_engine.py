"""Bridge service obligations to published Runs and their existing dispatch outbox."""

from __future__ import annotations

from datetime import datetime

from app.core.config import settings
from app.models.run import Run
from app.models.service_contract import AssetVersion, ServiceAttempt, ServiceWindow
from app.models.tabular import TabularDataset
from app.models.workspace import Workspace
from app.services import service_promises as promises
from app.services.governed_assets import (
    GovernanceError,
    asset_ref,
    record_qualification,
    register_asset,
    resolve_asset_ref,
)


def enabled(workspace):
    return (
        settings.service_contracts_enabled
        or (workspace.settings or {}).get("features", {}).get("service_contracts") is True
    )


def window_for_run(db, run_id, workspace_id):
    attempt = (
        db.query(ServiceAttempt)
        .filter_by(run_id=run_id, workspace_id=workspace_id)
        .order_by(ServiceAttempt.fence.desc())
        .first()
    )
    return db.get(ServiceWindow, attempt.window_id) if attempt else None


def validate_frozen_inputs(db, window):
    """The source qualification observed at launch must still authorize delivery."""
    from app.services.governed_assets import _workspace, current_qualification

    _workspace(db, window.workspace_id)
    snapshot = window.input_snapshot_json or {}
    pinned = snapshot.get("qualifications", {})
    required = snapshot.get("qualification_requirements", {})
    for ref in snapshot.get("refs", []):
        resolve_asset_ref(db, window.workspace_id, ref)
        current = current_qualification(db, window.workspace_id, ref["asset_id"])
        actual = current.digest if current else None
        if (
            actual != pinned.get(ref["asset_id"])
            or required.get(ref["asset_id"], False)
            and (current is None or current.status != "qualified")
            or current is not None
            and current.status == "needs_requalification"
        ):
            raise GovernanceError("SERVICE_INPUT_QUALIFICATION_CHANGED")


def freeze_inputs(db, window, contract, now):
    """Freeze fresh versions once, retaining each binding's qualification policy."""
    from app.services.governed_assets import _workspace, current_qualification

    _workspace(db, window.workspace_id)
    if window.input_snapshot_json is not None:
        validate_frozen_inputs(db, window)
        return window.input_snapshot_json["payload"]
    payload = dict(contract.definition_json.get("input_payload", {}))
    refs, qualifications, qualification_requirements = [], {}, {}
    for binding in contract.definition_json.get("inputs", []):
        asset = (
            db.query(AssetVersion)
            .filter_by(
                workspace_id=window.workspace_id,
                kind=binding["kind"],
                logical_key=binding["logical_key"],
            )
            .order_by(AssetVersion.version.desc())
            .first()
        )
        if asset is None:
            raise GovernanceError("SERVICE_INPUT_MISSING")
        age = (now - asset.created_at).total_seconds()
        if age < 0 or age > binding["max_age_seconds"]:
            raise GovernanceError("SERVICE_INPUT_STALE")
        qualification = current_qualification(db, window.workspace_id, asset.id)
        if (
            qualification is not None and qualification.status == "needs_requalification"
            or binding.get("require_qualified", True)
            and (qualification is None or qualification.status != "qualified")
        ):
            raise GovernanceError("SERVICE_INPUT_NOT_QUALIFIED")
        if binding.get("qualification_policy_digest") and (
            qualification is None
            or qualification.policy_digest != binding["qualification_policy_digest"]
        ):
            raise GovernanceError("SERVICE_INPUT_POLICY_CHANGED")
        ref = asset_ref(asset)
        resolve_asset_ref(db, window.workspace_id, ref)
        if binding.get("representation", "asset_ref") == "native_id":
            native = [
                entry
                for entry in asset.manifest_json.get("native_refs", [])
                if entry.get("kind") == binding["kind"]
            ]
            if len(native) != 1:
                raise GovernanceError("SERVICE_INPUT_NATIVE_ID_REQUIRED")
            payload[binding["payload_key"]] = native[0]["id"]
        else:
            payload[binding["payload_key"]] = ref
        refs.append(ref)
        qualifications[asset.id] = qualification.digest if qualification else None
        qualification_requirements[asset.id] = (
            qualification_requirements.get(asset.id, False)
            or binding.get("require_qualified", True)
        )
    window.input_snapshot_json = {
        "payload": payload,
        "refs": refs,
        "qualifications": qualifications,
        "qualification_requirements": qualification_requirements,
        "frozen_at": now.isoformat(),
    }
    db.flush()
    return payload


def _dataset_asset(db, window, run):
    validate_frozen_inputs(db, window)
    output = run.output_ref or {}
    reference = output.get("asset_ref")
    if reference:
        candidate = resolve_asset_ref(db, window.workspace_id, reference)
        if candidate.run_id != run.id:
            raise GovernanceError("SERVICE_OUTPUT_PRODUCER_MISMATCH")
        extra_refs = (window.input_snapshot_json or {}).get("refs", [])
        known = {ref["asset_id"] for ref in candidate.parents_json or []}
        missing = [ref for ref in extra_refs if ref["asset_id"] not in known]
        if missing:
            candidate = register_asset(
                db,
                window.workspace_id,
                candidate.kind,
                f"service:{window.system_id}:{window.logical_key}",
                candidate.manifest_json,
                parents=[asset_ref(candidate), *missing],
                run_id=run.id,
            )
        return candidate
    identifier = output.get("dataset_id")
    row = (
        db.query(TabularDataset)
        .filter_by(id=identifier, workspace_id=window.workspace_id, status="ready", run_id=run.id)
        .first()
    )
    if row is None:
        raise GovernanceError("SERVICE_OUTPUT_DATASET_REQUIRED")
    from app.services.dataops.asset_lineage import dataset_manifest, ensure_dataset_asset

    parent_refs = list((window.input_snapshot_json or {}).get("refs", []))
    parent_refs.append(asset_ref(ensure_dataset_asset(db, window.workspace_id, row.id)))
    native_manifest = dataset_manifest(row)
    count = int(row.row_count or 0)
    if "scored_rows" in output and output["scored_rows"] + output.get("excluded_rows", 0) != count:
        raise GovernanceError("SERVICE_OUTPUT_CARDINALITY_FAILED")
    manifest = {
        **native_manifest,
        "output": {
            **output,
            "technical_status": "completed",
            "coverage": {"expected": count, "processed": count, "failed": 0},
        },
        "producer": {
            "run_id": run.id,
            "flow_sha256": run.flow_sha256,
            "flow_version_id": run.published_flow_version_id,
        },
    }
    return register_asset(
        db,
        window.workspace_id,
        "dataset",
        f"service:{window.system_id}:{window.logical_key}",
        manifest,
        parents=parent_refs,
        run_id=run.id,
    )


def reconcile_runs(db, workspace, *, now=None, limit=50):
    now = now or datetime.utcnow()
    attempts = (
        db.query(ServiceAttempt)
        .filter(
            ServiceAttempt.workspace_id == workspace.id,
            ServiceAttempt.run_id.isnot(None),
            ServiceAttempt.completed_at.is_(None),
        )
        .limit(limit)
        .all()
    )
    completed = 0
    for attempt in attempts:
        window = db.get(ServiceWindow, attempt.window_id)
        if window is None or window.fence != attempt.fence or window.status != "running":
            continue
        run = db.query(Run).filter_by(id=attempt.run_id, workspace_id=workspace.id).first()
        if run is None:
            continue
        if run.status not in {"completed", "failed", "cancelled"}:
            if (
                now < window.deadline_at
                and (now - run.started_at).total_seconds()
                <= promises.get_contract(db, workspace.id, window.contract_id).definition_json[
                    "budget"
                ]["max_seconds"]
            ):
                promises.renew_lease(
                    db,
                    workspace.id,
                    window.id,
                    fence=window.fence,
                    lease_token=window.lease_token,
                    lease_seconds=120,
                    now=now,
                )
            continue
        run_budget = None
        try:
            from app.services.window_budget import summary as budget_summary

            total_budget = budget_summary(db, workspace.id, window.id)
            run_budget = budget_summary(db, workspace.id, window.id, run_id=run.id)
            if total_budget and (
                total_budget["over_budget"] or total_budget.get("measurement_conflict")
            ):
                raise GovernanceError("SERVICE_BUDGET_EXCEEDED")
            if run.status != "completed":
                promises.complete_attempt(
                    db,
                    workspace.id,
                    window.id,
                    fence=attempt.fence,
                    lease_token=attempt.lease_token,
                    error_code="SERVICE_RUN_FAILED",
                    cost=run_budget["measured_cost"] if run_budget else run.provider_cost_usd,
                    tokens=run_budget["measured_tokens"] if run_budget else None,
                    seconds=float(run.duration_ms or 0) / 1000,
                    now=now,
                )
            else:
                candidate = _dataset_asset(db, window, run)
                from app.services.governed_assets import current_qualification

                if current_qualification(db, workspace.id, candidate.id) is None:
                    record_qualification(
                        db,
                        workspace.id,
                        asset_ref(candidate),
                        status="review_required",
                        policy={
                            "authority": "service_producer",
                            "contract_digest": promises.get_contract(
                                db, workspace.id, window.contract_id
                            ).digest,
                        },
                        evidence={
                            "run_id": run.id,
                            "technical_status": "completed",
                            "human_required": True,
                        },
                        confidence=None,
                    )
                promises.complete_attempt(
                    db,
                    workspace.id,
                    window.id,
                    fence=attempt.fence,
                    lease_token=attempt.lease_token,
                    candidate_ref=asset_ref(candidate),
                    cost=run_budget["measured_cost"] if run_budget else run.provider_cost_usd,
                    tokens=run_budget["measured_tokens"] if run_budget else None,
                    seconds=float(run.duration_ms or 0) / 1000,
                    now=now,
                )
            completed += 1
        except GovernanceError as exc:
            # A terminal Run with invalidated inputs or an invalid output is a
            # failed attempt, rather than a perpetually running obligation.
            try:
                promises.complete_attempt(
                    db,
                    workspace.id,
                    window.id,
                    fence=attempt.fence,
                    lease_token=attempt.lease_token,
                    error_code=exc.code,
                    cost=run_budget["measured_cost"] if run_budget else run.provider_cost_usd,
                    tokens=run_budget["measured_tokens"] if run_budget else None,
                    seconds=float(run.duration_ms or 0) / 1000,
                    now=now,
                )
            except GovernanceError:
                # An expired/replaced lease is authoritative; the watchdog
                # owns its state transition and this worker records evidence.
                promises._incident(db, window, exc.code, now)
    return completed


def service_tick(*, limit=50, now=None):
    from fastapi import HTTPException

    from app.db.base import SessionLocal
    from app.models.system import System
    from app.services.execution.submission import stage_run
    from app.services.run_engine.dispatch_outbox import TRIGGER_RUN, enqueue_dispatch
    from app.services.systems.flow_ingress import FlowIngressError, create_published_ingress_run

    now = now or datetime.utcnow()
    created, fired, completed, incidents = 0, 0, 0, 0
    with SessionLocal() as db:
        workspaces = db.query(Workspace).filter_by(is_active=True).all()
        for workspace in workspaces:
            if not enabled(workspace):
                continue
            with db.begin_nested():
                from app.services.dataops.watchdog import sweep

                sweep(db, workspace_id=workspace.id, now=now, limit=limit)
                created += len(promises.tick(db, now, workspace_id=workspace.id, limit=limit))
                completed += reconcile_runs(db, workspace, now=now, limit=limit)
                windows = (
                    db.query(ServiceWindow)
                    .filter_by(workspace_id=workspace.id, status="pending")
                    .order_by(ServiceWindow.period_start)
                    .limit(limit)
                    .all()
                )
                for window in windows:
                    if now >= window.deadline_at:
                        continue
                    try:
                        with db.begin_nested():
                            contract = promises.get_contract(db, workspace.id, window.contract_id)
                            run = create_published_ingress_run(
                                db,
                                system_id=window.system_id,
                                workspace=workspace,
                                ingress_id=None,
                                kind="schedule",
                                payload=freeze_inputs(db, window, contract, now),
                                initiated_by_user_id=contract.owner_user_id,
                                adapter_evidence={
                                    "service_window_id": window.id,
                                    "contract_digest": contract.digest,
                                    "period_start": window.period_start.isoformat(),
                                },
                                trigger="scheduler",
                                trigger_dedup_key=f"service:{window.id}:attempt:{window.attempts + 1}",
                            )
                            promises.claim_window(
                                db,
                                workspace.id,
                                window.id,
                                worker_id=f"run:{run.id}",
                                run_id=run.id,
                                lease_seconds=120,
                                reserve_cost=0,
                                reserve_tokens=0,
                                reserve_seconds=0,
                                now=now,
                            )
                            system = db.get(System, run.system_id)
                            execution_profile = system.execution_profile or {}
                            if execution_profile.get("orchestration") is not None:
                                # Claim, frozen Run and candidate intent commit
                                # together. Never dispatch two engines for one Run.
                                stage_run(db, run, system, business_deadline=window.deadline_at)
                            else:
                                enqueue_dispatch(
                                    db,
                                    event_type=TRIGGER_RUN,
                                    workspace_id=workspace.id,
                                    run_id=run.id,
                                    source_id=window.id,
                                    dedupe_key=f"service:{window.id}:{window.fence}",
                                )
                        fired += 1
                    except (GovernanceError, FlowIngressError, HTTPException) as exc:
                        promises._incident(
                            db, window, getattr(exc, "code", "SERVICE_RUN_REFUSED"), now
                        )
                incidents += len(promises.watchdog(db, now, workspace_id=workspace.id, limit=limit))
            db.commit()
    return {
        "created": created,
        "fired": fired,
        "completed": completed,
        "incidents": incidents,
        "checked_at": now.isoformat(),
    }
