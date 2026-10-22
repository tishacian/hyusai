"""Append-only retries of one failed campaign Run, outside the initial comparison."""

from __future__ import annotations

import copy
from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException

from app.models.evaluation_campaign import EvaluationCampaign
from app.models.run import Run
from app.models.system import System
from app.models.workspace_job import WorkspaceJob
from app.services.evaluation.qualification import bound_profile, digest
from app.services.systems import flow_workbench
from app.services.workspace_jobs import create_workspace_job

ACTIVE = {"pending", "running", "hitl_pending"}
MAX_ATTEMPTS = 20


def lock_campaign(db, campaign_id, workspace_id):
    # Serializes the JSON append/refresh without conflicting with Run FK reads.
    row = (
        db.query(EvaluationCampaign)
        .filter_by(id=campaign_id, workspace_id=workspace_id)
        .populate_existing()
        .with_for_update(key_share=True)
        .first()
    )
    if row is None:
        raise HTTPException(404, "Campaign not found")
    return row


def attempts(campaign):
    for item in campaign.results or []:
        for side in ("baseline", "candidate"):
            for attempt in item[side].get("attempts", []):
                yield item, side, attempt


def retry_state(campaign, result):
    history = result.get("attempts", [])
    latest = history[-1] if history else result
    reason = None
    if campaign.snapshot.get("execution_mode") != "qualified_prefix":
        reason = "qualified_prefix_required"
    elif latest.get("status") in ACTIVE or latest.get("has_active_invocations"):
        reason = "attempt_active"
    elif latest.get("termination") == "human_gate":
        reason = "not_failed_terminal"
    elif latest.get("status") not in {"failed", "cancelled"} or latest.get("verdict") not in {
        "failed",
        "unevaluated",
    }:
        reason = "not_failed_terminal"
    elif len(history) >= MAX_ATTEMPTS:
        reason = "retry_limit_reached"
    return {
        "can_retry": reason is None,
        "retry_blocked_reason": reason,
        "retry_source_run_id": latest["run_id"],
    }


def create_retry(db, *, campaign, workspace, user, body):
    """Caller holds the campaign lock and has authorized every existing Run."""
    from app.services.evaluation import campaigns

    key = digest([user.id, body["request_key"]])
    fingerprint = digest(body)
    for _, _, previous in attempts(campaign):
        if previous["request_key_sha256"] == key:
            if previous["request_sha256"] != fingerprint:
                raise HTTPException(409, {"code": "EVALUATION_RETRY_REQUEST_CHANGED"})
            return db.get(WorkspaceJob, previous["job_id"])
    # Refresh only in the short admission transaction. Never hold this lock
    # during dispatch, provider work, or the original campaign's other Runs.
    campaigns.refresh_campaign(db, campaign, locked=True)
    results = copy.deepcopy(campaign.results)
    item = next((row for row in results if row["result_key"] == body["result_key"]), None)
    if item is None:
        raise HTTPException(404, "Campaign case not found")
    side = body["side"]
    initial = item[side]
    eligibility = retry_state(campaign, initial)
    if body["source_run_id"] != eligibility["retry_source_run_id"]:
        raise HTTPException(409, {"code": "EVALUATION_RETRY_SOURCE_CHANGED"})
    if not eligibility["can_retry"]:
        raise HTTPException(
            409,
            {
                "code": "EVALUATION_RETRY_NOT_ELIGIBLE",
                "reason": eligibility["retry_blocked_reason"],
            },
        )
    source = db.get(Run, body["source_run_id"])
    if source is None or source.workspace_id != workspace.id:
        raise HTTPException(404, "Run not found")
    if any(inv.status in {"pending", "running"} for inv in source.invocations):
        raise HTTPException(
            409, {"code": "EVALUATION_RETRY_NOT_ELIGIBLE", "reason": "attempt_active"}
        )
    try:
        profile = bound_profile(db, source)
    except ValueError as exc:
        raise HTTPException(409, {"code": "EVALUATION_RETRY_SOURCE_INVALID"}) from exc
    if not profile:
        raise HTTPException(409, {"code": "EVALUATION_RETRY_SOURCE_INVALID"})
    case = next(case for case in campaign.snapshot["cases"] if case["id"] == item["case_id"])
    current_corpus = campaigns.corpus_manifest(
        db, workspace.id, [c["id"] for c in campaign.snapshot["corpus_manifest"]]
    )
    if current_corpus != campaign.snapshot["corpus_manifest"]:
        raise HTTPException(409, {"code": "EVALUATION_RETRY_CORPUS_CHANGED"})
    attempt_id = str(uuid4())
    history = initial.setdefault("attempts", [])
    index = len(history) + 1
    execution = (source.input_ref or {}).get("execution", {})
    prepared = flow_workbench.PreparedPreview(
        system=db.get(System, campaign.system_id),
        flow=copy.deepcopy(source.flow_snapshot),
        flow_sha256=source.flow_sha256,
        source_flow_sha256=execution.get("source_flow_sha256", source.flow_sha256),
        contract=copy.deepcopy(source.execution_contract),
        runtime_reason=execution.get("runtime_mode_reason") or "evaluation_retry",
        ingress=copy.deepcopy((source.input_ref or {}).get("_ingress")),
    )
    run = flow_workbench.create_run(
        db,
        prepared=prepared,
        workspace=workspace,
        user_id=user.id,
        surface="golden_preview",
        input_ref=copy.deepcopy(case["input_ref"]),
        metadata={
            "evaluation_campaign_id": campaign.id,
            "golden_case_id": item["case_id"],
            "comparison_side": side,
            "evaluation_retry_id": attempt_id,
            "retry_source_run_id": source.id,
            "source_draft_revision": execution.get("source_draft_revision"),
        },
    )
    run.parent_run_id = source.id
    run.evaluation_campaign_id = campaign.id
    run.evaluation_binding = {
        **copy.deepcopy(source.evaluation_binding),
        "attempt_id": attempt_id,
        "attempt_index": index,
    }
    run.checkpoints = [
        {
            "kind": "evaluation_case_queued",
            "suite_id": campaign.suite_id,
            "suite_revision": campaign.snapshot["suite_revision"],
            "case": copy.deepcopy(case),
            "retry_id": attempt_id,
            "source_run_id": source.id,
        }
    ]
    job = create_workspace_job(
        db,
        workspace,
        user,
        kind="evaluation_campaign",
        title=f"Retry · {item['case_id']} · {side}",
        system_id=campaign.system_id,
        status="queued",
        input_ref={"campaign_id": campaign.id, "retry_run_id": run.id, "retry_id": attempt_id},
    )
    history.append(
        {
            "id": attempt_id,
            "attempt_index": index,
            "initial_run_id": initial["run_id"],
            "source_run_id": source.id,
            "run_id": run.id,
            "job_id": job.id,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "actor_user_id": user.id,
            "reason": body.get("reason") or None,
            "request_key_sha256": key,
            "request_sha256": fingerprint,
            "status": "pending",
            "verdict": "pending",
        }
    )
    campaign.results = results
    db.flush()
    # Validate the new registry membership before committing any runnable work.
    bound_profile(db, run)
    return job


def run_retry_job(job_id):
    """The existing evaluation worker dispatches this one immutable Run only."""
    from app.api.v1.endpoints.evaluation_campaigns import authorize_campaign
    from app.db.base import SessionLocal
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.services.evaluation import campaigns
    from app.services.run_engine import schedule_run

    with SessionLocal() as db:
        job = db.query(WorkspaceJob).filter_by(id=job_id).with_for_update(key_share=True).first()
        if job is None or job.status in {"completed", "failed", "cancelled"}:
            return (job.result or {}) if job else {"status": "unavailable"}
        if job.status == "running":
            return {"job_id": job_id, "status": "running"}
        try:
            campaign = authorize_campaign(
                db,
                db.get(EvaluationCampaign, job.input_ref["campaign_id"]),
                db.get(Workspace, job.workspace_id),
                db.get(User, job.created_by_user_id),
            )
            registered = next(
                (
                    a
                    for _, _, a in attempts(campaign)
                    if a["id"] == job.input_ref["retry_id"]
                    and a["job_id"] == job.id
                    and a["run_id"] == job.input_ref["retry_run_id"]
                ),
                None,
            )
            if registered is None:
                raise ValueError("EVALUATION_RETRY_BINDING_INVALID")
            run = db.get(Run, registered["run_id"])
            bound_profile(db, run)
            current_corpus = campaigns.corpus_manifest(
                db,
                campaign.workspace_id,
                [item["id"] for item in campaign.snapshot["corpus_manifest"]],
            )
            if current_corpus != campaign.snapshot["corpus_manifest"]:
                raise ValueError("EVALUATION_RETRY_CORPUS_CHANGED")
            run_id, should_dispatch = run.id, run.status == "pending"
            job.status, job.stage, job.started_at = "running", "canonical_retry", datetime.utcnow()
            db.commit()
            if should_dispatch:
                schedule_run(run_id)
            db.expire_all()
            campaigns.refresh_campaign(db, campaign)
            job.status, job.stage, job.progress = "completed", "retry_dispatched", 100
            job.completed_at = datetime.utcnow()
            job.result = {"campaign_id": campaign.id, "retry_run_id": run_id}
            db.commit()
            return job.result
        except Exception:
            db.rollback()
            job = db.get(WorkspaceJob, job_id)
            job.status, job.stage = "failed", "retry_unavailable"
            job.error = (
                "The selected retry could not continue; the initial comparison is unchanged."
            )
            job.completed_at = datetime.utcnow()
            run = db.get(Run, job.input_ref.get("retry_run_id"))
            if run and run.workspace_id == job.workspace_id and run.status == "pending":
                run.status, run.error, run.completed_at = "cancelled", job.error, datetime.utcnow()
            db.commit()
            return {"job_id": job_id, "status": "failed"}
