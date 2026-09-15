"""Durable evaluation commands; the Run remains the evidence/access anchor."""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime

from fastapi import HTTPException

from app.db.base import SessionLocal
from app.models.run import Run
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services.run_access import readable_runs
from app.services.workspace_jobs import create_workspace_job, dispatch_workspace_job, transition_job
from app.services.evaluation_preset_service import get_evaluation_preset_service


def require_readable_run(db, run, user, workspace):
    if run is None or run.workspace_id != workspace.id or not readable_runs(db, runs=[run], user=user, workspace=workspace):
        raise HTTPException(404, "Run not found")
    return run


def visible_evaluation_query(db, query, user, workspace):
    runs = db.query(Run).filter(Run.workspace_id == workspace.id).all()
    ids = [r.id for r in readable_runs(db, runs=runs, user=user, workspace=workspace)]
    # Detached historic/manual text has no verifiable Run visibility. Keep it
    # out of cross-user feeds; it remains returned to its submitting caller.
    from app.models.evaluation import EvaluationScore
    from app.models.run import SkillInvocation
    from app.services.run_access import readable_skill_invocations_for_runs
    from sqlalchemy import or_
    invocations = db.query(SkillInvocation).filter(SkillInvocation.run_id.in_(ids)).all()
    allowed = readable_skill_invocations_for_runs(db, invocations=invocations, runs=[r for r in runs if r.id in ids], user=user, workspace=workspace)
    target = EvaluationScore.metadata_["invocation_id"].as_string()
    return query.filter(EvaluationScore.run_id.in_(ids), or_(target.is_(None), target.in_([i.id for i in allowed])))


def enqueue_run_evaluation(db, run, *, user, idempotency_key, invocation_id=None):
    run = db.query(Run).filter(Run.id == run.id).with_for_update().one()
    if run.status != "completed":
        raise HTTPException(409, "Only a completed Run can be evaluated")
    actor = str(user.id) if user else "system"
    identity = hashlib.sha256(f"{actor}:{run.id}:{invocation_id or ''}:{idempotency_key}".encode()).hexdigest()
    existing = db.query(WorkspaceJob).filter(WorkspaceJob.run_id == run.id, WorkspaceJob.kind == "run_evaluation").all()
    for job in existing:
        if (job.input_ref or {}).get("request_key") == identity:
            return job
    if any(job.status in {"created", "queued", "running"} for job in existing):
        raise HTTPException(409, "An evaluation is already active for this Run")
    workspace = db.query(Workspace).filter(Workspace.id == run.workspace_id).one()
    preset = get_evaluation_preset_service().resolve(db, workspace_id=run.workspace_id, capability_id=run.capability_id, system_id=run.system_id)
    if user:
        preset = {**preset, "enabled": True, "sample_rate": 1.0}
    job = create_workspace_job(db, workspace, user, kind="run_evaluation", title="Evaluate Run", run_id=run.id, system_id=run.system_id, status="queued", input_ref={"request_key": identity, "preset": preset, "invocation_id": invocation_id})
    run.evaluation_scores = {"status": "queued", "job_id": job.id, "preset": preset}
    db.commit()
    task_id = dispatch_workspace_job(db, workspace, job, allow_inline_fallback=False)
    if not task_id:
        transition_job(db, workspace, job, "failed", error="dispatch_unavailable")
        run.evaluation_scores = {"status": "failed", "reason": "dispatch_unavailable", "job_id": job.id}
    db.commit()
    return job


def run_evaluation_job(job_id):
    from app.services.evaluation.auto_eval import evaluate_run_async
    db = SessionLocal()
    try:
        # Serialize deliveries for this job. A worker crash releases the lock;
        # late acknowledgement lets the broker redeliver the persisted command.
        job = db.query(WorkspaceJob).filter(WorkspaceJob.id == job_id).with_for_update().one()
        if job.status in {"completed", "failed", "cancelled"}:
            return job.result or {}
        workspace = db.query(Workspace).filter(Workspace.id == job.workspace_id).one()
        transition_job(db, workspace, job, "running", stage="judge", audit=False)
        run = db.query(Run).filter(Run.id == job.run_id).one()
        actor_id = job.created_by_user_id or run.initiated_by_user_id
        if actor_id:
            from app.models.user import User
            from app.models.run import SkillInvocation
            from app.services.evaluation.auto_eval import _context_evidence
            actor = db.query(User).filter(User.id == actor_id).first()
            try:
                if actor is None:
                    raise HTTPException(404, "Actor unavailable")
                require_readable_run(db, run, actor, workspace)
                evidence = _context_evidence(run, db.query(SkillInvocation).filter(SkillInvocation.run_id == run.id).all())
                checked = public_evaluation_snapshot(db, {"metadata": {"invocation_id": (job.input_ref or {}).get("invocation_id"), "excerpts": [{**row, "id": str(index)} for index, row in enumerate(evidence, 1)]}}, workspace=workspace, user=actor, run=run)
                if any(row.get("availability") == "source_unavailable" for row in checked["metadata"]["excerpts"]):
                    raise HTTPException(404, "Source unavailable")
            except HTTPException:
                result = {"status": "failed", "reason": "evidence_access_unavailable", "job_id": job.id}
                run.evaluation_scores = result
                transition_job(db, workspace, job, "failed", result=result)
                db.commit()
                return result
        existing = run.evaluation_scores or {}
        if existing.get("job_id") == job.id and existing.get("status") in {"completed", "partial", "skipped"}:
            result = existing
        else:
            async def evaluate_bounded():
                return await asyncio.wait_for(evaluate_run_async(job.run_id, preset_override=(job.input_ref or {}).get("preset"), invocation_id=(job.input_ref or {}).get("invocation_id"), job_id=job.id), timeout=120)
            try:
                result = asyncio.run(evaluate_bounded())
            except TimeoutError:
                result = {"status": "failed", "reason": "evaluation_timeout"}
            result = result or {"status": "failed", "reason": "evaluation_failed"}
        db.refresh(run)
        run.evaluation_scores = {**result, "job_id": job.id}
        transition_job(db, workspace, job, "failed" if result.get("status") == "failed" else "completed", result={k: result[k] for k in ("status", "reason", "evaluation_id") if k in result})
        db.commit()
        return result
    finally:
        db.close()


def public_evaluation_snapshot(db, snapshot, *, workspace, user, run):
    """Recheck concrete source/invocation references before exposing excerpts."""
    from app.models.knowledge_collection import KnowledgeCollection, KnowledgeCollectionSource
    from app.models.run import SkillInvocation
    from app.services.run_access import readable_skill_invocations
    from app.models.system import System
    from app.services.run_engine.engine import _load_control_policy, _safe_membrane
    from app.services.membrane.enforcement import enforce_inbound_collections
    system = db.query(System).filter(System.id == run.system_id, System.workspace_id == workspace.id).first()
    spec = _safe_membrane(_load_control_policy(db, system) if system else None)
    metadata = dict(snapshot.get("metadata") or {})
    invocations = db.query(SkillInvocation).filter(SkillInvocation.run_id == run.id).all()
    allowed_invocations = {i.id for i in readable_skill_invocations(db, invocations=invocations, run=run, user=user, workspace=workspace)}
    selected_invocation = metadata.get("invocation_id")
    if selected_invocation and selected_invocation not in allowed_invocations:
        raise HTTPException(404, "Evaluation evidence not found")
    public = []
    for original in metadata.get("excerpts") or []:
        item = dict(original)
        available = not item.get("invocation_id") or item["invocation_id"] in allowed_invocations
        collection_ref = item.get("collection_id") or item.get("collection")
        source_ref = item.get("source_id") or item.get("document_id") or item.get("filename") or item.get("document_ref")
        if isinstance(source_ref, dict):
            source_ref = source_ref.get("source_id") or source_ref.get("document_id") or source_ref.get("filename")
        collection = None
        if collection_ref:
            collection = db.query(KnowledgeCollection).filter(KnowledgeCollection.workspace_id == workspace.id,
                (KnowledgeCollection.id == collection_ref) | (KnowledgeCollection.slug == collection_ref) | (KnowledgeCollection.vector_collection_name == collection_ref)).first()
            available = available and collection is not None
            if collection is not None:
                decision = enforce_inbound_collections(spec, [collection.slug, collection.vector_collection_name, collection.id])
                available = available and not decision.blocked
        if source_ref:
            query = db.query(KnowledgeCollectionSource).filter(KnowledgeCollectionSource.workspace_id == workspace.id,
                (KnowledgeCollectionSource.id == str(source_ref)) | (KnowledgeCollectionSource.filename == str(source_ref)))
            if collection:
                query = query.filter(KnowledgeCollectionSource.collection_id == collection.id)
            source = query.first()
            available = available and source is not None and source.status != "deleted"
        if not available:
            item = {"id": item.get("id"), "availability": "source_unavailable", "text": None}
        else:
            item["availability"] = "available" if source_ref else "run_evidence_only"
        public.append(item)
    metadata["excerpts"] = public
    # A duplicate formatted context would bypass source revalidation.
    metadata.pop("context_examined", None)
    return {**snapshot, "metadata": metadata}


def evaluation_model_context(db, run, system, invocations):
    """Apply current model permissions/valves without changing the finished Run."""
    from dataclasses import replace
    from app.services.run_engine.engine import _load_control_policy, _safe_membrane
    from app.services.membrane.enforcement import evaluate_capability, evaluate_valves, collect_valve_usage, MembraneEnforcementError, MeasurementCoverage
    from app.services.evaluation.judge import provider_usage_evidence
    spec = _safe_membrane(_load_control_policy(db, system) if system else None)
    base = collect_valve_usage(invocations, duration_ms=run.duration_ms)
    ctx = {}
    def check(execution):
        model = execution.policy_model(spec.capabilities.allowed_models)
        if not evaluate_capability(spec, model=model).allowed:
            raise MembraneEnforcementError("evaluation_model_not_allowed")
        usage = base
        provider = ctx.get("_provider_usage_v1") or {}
        if provider.get("calls"):
            measured = provider_usage_evidence(provider).get("usage") or {}
            usage = replace(base, tokens=base.tokens + int(measured.get("total_tokens") or 0),
                token_coverage=base.token_coverage if measured else MeasurementCoverage.UNAVAILABLE,
                cost_coverage=MeasurementCoverage.UNAVAILABLE)
        if not evaluate_valves(spec, usage).allowed:
            raise MembraneEnforcementError("evaluation_budget_unavailable_or_exhausted")
    ctx["_model_policy_check"] = check
    return ctx
