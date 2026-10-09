"""Scheduled model monitoring and human-authorized retraining.

Protected jobs hold execution authority. Flow/HITL supplies the human decision;
generic Hypervisor decision JSON can never stage or dispatch a model.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import tempfile
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from app.core.config import settings
from app.models.decision import Decision
from app.models.run import Run
from app.models.run_schedule import RunSchedule
from app.models.skill import Skill
from app.models.system import System
from app.models.tabular import MLModel, TabularDataset
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services.mlops_jobs import can_configure_mlops, operational_job_id
from app.services.tabular_datasets import TabularError, materialize, register_frame

MONITOR_SKILL = "ml_monitor_model_v1"
RETRAIN_SKILL = "ml_retrain_model_v1"
PROMPT_KIND = "approve_model_retraining"
SNAPSHOT_KIND = "ml_monitoring"
PROPOSAL_KIND = "ml_retraining"
HISTORY_LIMIT = 100


class MonitoringPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool = False
    propose_retraining: bool = False
    interval_minutes: int = 60


def refuse(code, message, status=409):
    raise TabularError(code=code, message=message, status_code=status)


def policy_for(model):
    return dict(((model.params_json or {}).get("mlops") or {}).get("monitoring") or {})


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _flow(model_id):
    def ports(*names):
        return [{"name": name, "schema": "boolean" if name == "proposed" else "string"} for name in names]

    def wire(node, *names):
        return {name: {"node_id": node, "path": [name], "required": True} for name in names}

    return {"schema_version": 3, "io_mode": "strict", "nodes": [
        {"id": "schedule", "type": "source.schedule", "kind": "source", "label": "Schedule"},
        {"id": "monitor", "kind": "task", "label": "Monitor model", "outputs": ports("proposed", "proposal_id"),
         "config": {"skill_slug": MONITOR_SKILL, "params": {"model_id": model_id}}},
        {"id": "route", "kind": "decision", "inputs": ports("proposed"),
         "config": {"inputs_map": wire("monitor", "proposed"), "branches": [
             {"label": "review", "condition": "proposed == True"},
             {"label": "done", "condition": "proposed == False"}]}},
        {"id": "review", "kind": "hitl", "label": "Approve retraining", "inputs": ports("proposal_id"),
         "config": {"prompt_kind": PROMPT_KIND, "inputs_map": wire("monitor", "proposal_id"),
                    "expires_in_days": 2, "expiry_action": "reject"}},
        {"id": "retrain", "kind": "task", "label": "Train challenger", "inputs": ports("proposal_id", "decision_id"),
         "outputs": ports("model_id"), "config": {"skill_slug": RETRAIN_SKILL,
             "inputs_map": wire("review", "proposal_id", "decision_id")}},
        {"id": "sink", "kind": "sink"},
    ], "edges": [{"from": "schedule", "to": "monitor"}, {"from": "monitor", "to": "route"},
                 {"from": "route", "to": "review", "kind": "branch", "branch_label": "review"},
                 {"from": "route", "to": "sink", "kind": "branch", "branch_label": "done"},
                 {"from": "review", "to": "retrain"}, {"from": "retrain", "to": "sink"}]}


def configure(db, *, model, workspace, user, body: MonitoringPolicy):
    from app.services.run_engine.scheduler import validate_cron_expr
    from app.services.systems.flow_publication import initialize_new_system_publication_if_enabled
    from app.services.run_engine.execution_contract import canonical_flow_sha256

    if not can_configure_mlops(db, workspace=workspace, user=user, admin_only=True):
        refuse("ML_MONITORING_FORBIDDEN", "Workspace administration is required to schedule retraining proposals.", 403)
    if body.enabled and (model.status != "ready" or model.task not in {"classification", "regression"}):
        refuse("ML_MONITORING_UNSUPPORTED", "Select a ready tabular classification or regression model.")
    if body.interval_minutes not in {60, 360, 1440}:
        refuse("ML_MONITORING_INTERVAL_INVALID", "Choose an hourly, six-hourly or daily schedule.", 422)
    db.query(MLModel).filter_by(id=model.id, workspace_id=workspace.id).populate_existing().with_for_update().one()
    current = policy_for(model)
    if not body.enabled:
        schedule = db.get(RunSchedule, current.get("schedule_id")) if current.get("schedule_id") else None
        if schedule and schedule.workspace_id == workspace.id:
            schedule.enabled = False
            schedule.next_fire_at = None
        updated = {**current, **body.model_dump()}
    else:
        skills = db.query(Skill).filter(Skill.slug.in_([MONITOR_SKILL, RETRAIN_SKILL]),
                                        Skill.workspace_id.is_(None)).all()
        if {skill.slug for skill in skills} != {MONITOR_SKILL, RETRAIN_SKILL}:
            refuse("ML_MONITORING_CATALOG_REQUIRED", "Publish the model monitoring Skills in the catalog first.")
        system = db.get(System, current.get("system_id")) if current.get("system_id") else None
        if system is None:
            system = System(id=str(uuid4()), workspace_id=workspace.id,
                name=f"Monitor · {model.name[:150]} · v{model.version}", objective="Monitor model drift and review retraining",
                status="active", execution_mode="human_augmented", created_by=user.id,
                flow_definition=_flow(model.id), skill_ids=[skill.id for skill in skills],
                settings={"ml_monitoring_model_id": model.id})
            db.add(system)
            db.flush()
            initialize_new_system_publication_if_enabled(db, system=system, workspace=workspace, actor=user.id)
        if system.workspace_id != workspace.id or (system.settings or {}).get("ml_monitoring_model_id") != model.id:
            refuse("ML_MONITORING_BINDING_INVALID", "The monitoring Flow does not belong to this model.")
        flow_hash = canonical_flow_sha256(_flow(model.id))
        if canonical_flow_sha256(system.flow_definition) != flow_hash:
            refuse("ML_MONITORING_FLOW_CHANGED", "Restore the generated monitoring Flow before enabling its schedule.")
        schedule = db.get(RunSchedule, current.get("schedule_id")) if current.get("schedule_id") else None
        if schedule is None:
            schedule = RunSchedule(id=str(uuid4()), workspace_id=workspace.id, system_id=system.id,
                                   name=f"Monitor v{model.version}", input_payload={})
            db.add(schedule)
        if schedule.workspace_id != workspace.id or schedule.system_id != system.id:
            refuse("ML_MONITORING_BINDING_INVALID", "The monitoring schedule does not belong to this model.")
        schedule.cron_expr = {60: "0 * * * *", 360: "0 */6 * * *", 1440: "0 0 * * *"}[body.interval_minutes]
        schedule.timezone = "UTC"
        schedule.enabled = True
        schedule.next_fire_at = validate_cron_expr(schedule.cron_expr, "UTC")
        updated = {**body.model_dump(), "system_id": system.id, "schedule_id": schedule.id,
                   "flow_sha256": flow_hash, "configured_by": user.id}
    model.params_json = {**(model.params_json or {}), "mlops": {
        **((model.params_json or {}).get("mlops") or {}), "monitoring": updated}}
    db.commit()
    return monitoring_view(db, model)


def stop_model_schedules(db, model):
    """Retire future ticks with the deleted model, retaining its Flow history.

    Do not commit: scheduling and model deletion must settle atomically. Only
    the dedicated, workspace-owned monitoring System may be affected.
    """
    # Serialize with configure() and refresh a policy enabled since the caller
    # loaded the model. Both paths acquire the model before its schedules.
    model = db.query(MLModel).filter_by(id=model.id, workspace_id=model.workspace_id).populate_existing().with_for_update().first()
    if model is None:
        return
    policy = policy_for(model)
    system = db.get(System, policy.get("system_id")) if policy.get("system_id") else None
    if (system is None or system.workspace_id != model.workspace_id
            or (system.settings or {}).get("ml_monitoring_model_id") != model.id):
        return
    db.query(RunSchedule).filter_by(workspace_id=model.workspace_id, system_id=system.id).update(
        {"enabled": False, "next_fire_at": None}, synchronize_session="fetch")


def _active(db, model, run):
    from app.services.run_engine.execution_contract import canonical_flow_sha256

    policy = policy_for(model)
    workspace = db.get(Workspace, model.workspace_id)
    author = db.get(User, policy.get("configured_by")) if policy.get("configured_by") else None
    if (not policy.get("enabled") or not workspace or not author
            or not can_configure_mlops(db, workspace=workspace, user=author, admin_only=True)):
        refuse("ML_MONITORING_DISABLED", "The monitoring policy is no longer authorized or enabled.")
    if (model.status != "ready" or not run or run.workspace_id != model.workspace_id
            or run.system_id != policy.get("system_id")
            or canonical_flow_sha256(run.flow_snapshot or {}) != policy.get("flow_sha256")):
        refuse("ML_MONITORING_BINDING_INVALID", "The run does not match the authorized monitoring Flow.")
    return policy


def _file_hash(dataset):
    if dataset.status != "ready" or (dataset.size_bytes or 0) > 32 * 1024 * 1024:
        refuse("ML_RETRAIN_SOURCE_UNAVAILABLE", "The reviewed feedback dataset is unavailable or too large.")
    with tempfile.TemporaryDirectory(prefix="retrain-source-") as folder:
        try:
            path = materialize(dataset, Path(folder) / "data.parquet")
        except FileNotFoundError:
            refuse("ML_RETRAIN_SOURCE_UNAVAILABLE", "The reviewed feedback dataset is unavailable.")
        if path.stat().st_size > 32 * 1024 * 1024:
            refuse("ML_RETRAIN_SOURCE_UNAVAILABLE", "The reviewed feedback dataset exceeds 32 MiB.")
        return hashlib.sha256(path.read_bytes()).hexdigest()


def _training_options(model):
    from app.services.tabular_predict import contract_fields

    params = model.params_json or {}
    spec = {key: value for key, value in (model.spec_json or {}).items()
            if key != "distillation_inference_cost_per_1000"}
    return {"task": model.task, "target": model.target, "features": [field["name"] for field in contract_fields(model)], "algo": model.algo,
            "knobs": params.get("knobs") or {}, "spec": spec, "test_size": model.test_size,
            "cross_validation": model.cross_validation, "name": model.slug}


def _feedback_dataset(db, model, rows):
    import polars as pl
    from app.services.tabular_monitoring import _feedback_number

    features = _training_options(model)["features"]
    records, ids = [], []
    for row in rows:
        if row.label is None or not isinstance(row.payload_json, list) or not row.payload_json:
            continue
        payload = row.payload_json[0]
        if not isinstance(payload, dict) or not all(name in payload for name in features):
            continue
        label = _feedback_number(row.label) if model.task == "regression" else row.label
        if label is None or label == "":
            continue
        records.append({**{name: payload[name] for name in features}, model.target: label})
        ids.append(row.id)
    required = max(40, settings.ml_train_min_rows)
    if len(records) < required:
        refuse("ML_RETRAIN_FEEDBACK_INSUFFICIENT", f"At least {required} labeled calls with all model inputs are required.")
    dataset = register_frame(db, workspace_id=model.workspace_id, name=f"{model.name[:150]} · reviewed feedback",
        frame=pl.DataFrame(records), source="generated", produced_by="ml_feedback",
        parent_ids=[model.dataset_id] if model.dataset_id else [],
        lineage={"kind": "feedback", "model": {"model_id": model.id, "version": model.version},
                 "labeled": len(records), "prediction_ids": ids})
    return dataset, ids


def monitor_cycle(db, *, model_id, run_id):
    from app.services.tabular_monitoring import report, _recent
    from app.services.tabular_ml import validate_training

    model = db.query(MLModel).filter_by(id=model_id).populate_existing().with_for_update().first()
    run = db.get(Run, run_id)
    if model is None:
        refuse("ML_MODEL_NOT_FOUND", "The monitored model is unavailable.", 404)
    policy = _active(db, model, run)
    rows = _recent(db, model)
    window_hash = digest([(row.id, row.label, row.labeled_at) for row in rows])
    snapshot_id = operational_job_id(SNAPSHOT_KIND, model.id, window_hash)
    snapshot = db.get(WorkspaceJob, snapshot_id)
    measured = {key: value for key, value in report(db, model=model).items()
                if key in {"badge", "window", "data_drift", "score_drift", "concept_drift"}}
    if snapshot is None:
        snapshot = WorkspaceJob(id=snapshot_id, workspace_id=model.workspace_id, system_id=run.system_id,
            run_id=run.id, kind=SNAPSHOT_KIND, title=f"Monitor {model.name[:200]}", status="completed", stage="measured",
            progress=100, completed_at=datetime.utcnow(), input_ref={"model_id": model.id, "version": model.version,
                "window_sha256": window_hash}, result={"report": measured})
        db.add(snapshot)
        db.flush()
    result = {"proposed": False, "proposal_id": "", "snapshot_id": snapshot.id, "badge": measured["badge"]}
    proposal_id = operational_job_id(PROPOSAL_KIND, model.id, window_hash)
    existing = db.get(WorkspaceJob, proposal_id)
    pending = db.query(WorkspaceJob).filter_by(workspace_id=model.workspace_id, system_id=run.system_id, kind=PROPOSAL_KIND).filter(
        WorkspaceJob.status.in_(["created", "queued", "running"])).all()
    active = next((job for job in pending if (job.input_ref or {}).get("model_id") == model.id), None)
    if (policy.get("propose_retraining") and measured["badge"] == "alert" and model.is_champion
            and existing is None and active is None):
        try:
            with db.begin_nested():
                dataset, ids = _feedback_dataset(db, model, rows)
                options = _training_options(model)
                validate_training(dataset, db=db, **options)
                binding = {"model_id": model.id, "model_version": model.version, "model_name": model.name,
                           "dataset_id": dataset.id, "dataset_version": dataset.version, "dataset_sha256": _file_hash(dataset),
                           "labeled_rows": len(ids), "prediction_ids": ids, "training": options,
                           "snapshot_id": snapshot.id, "window_sha256": window_hash, "evidence": measured}
                job = WorkspaceJob(id=proposal_id, workspace_id=model.workspace_id, system_id=run.system_id,
                    run_id=run.id, kind=PROPOSAL_KIND, title=f"Retrain {model.name[:200]}", status="created", stage="proposed",
                    input_ref=binding, result={"binding_sha256": digest(binding)}, created_by_user_id=policy["configured_by"])
                db.add(job)
                db.flush()
                result.update(proposed=True, proposal_id=job.id)
        except TabularError as exc:
            result["reason"] = exc.code
    elif existing or active:
        result["reason"] = "ML_RETRAIN_PROPOSAL_EXISTS"
    elif not model.is_champion:
        result["reason"] = "ML_RETRAIN_CHAMPION_REQUIRED"
    snapshot.result = {**snapshot.result, "last_result": result}
    run.checkpoints = [*(run.checkpoints or []), {"kind": "ml_monitoring_snapshot", "snapshot_id": snapshot.id,
        "model_id": model.id, "model_name": model.name, "version": model.version, "badge": measured["badge"],
        "t": datetime.utcnow().isoformat()}]
    # Keep a bounded measurement history; proposals retain their own evidence.
    history = db.query(WorkspaceJob).filter_by(workspace_id=model.workspace_id, kind=SNAPSHOT_KIND,
        system_id=run.system_id).order_by(WorkspaceJob.created_at.desc()).offset(HISTORY_LIMIT).all()
    for old in history:
        db.delete(old)
    db.commit()
    return result


def proposal_for(db, proposal_id, *, workspace_id, run_id):
    job = db.query(WorkspaceJob).filter_by(id=proposal_id, workspace_id=workspace_id, run_id=run_id,
                                          kind=PROPOSAL_KIND).populate_existing().with_for_update().first()
    if job is None or digest(job.input_ref) != (job.result or {}).get("binding_sha256"):
        refuse("ML_RETRAIN_PROPOSAL_INVALID", "The retraining proposal has no matching server-owned snapshot.")
    model = db.get(MLModel, job.input_ref["model_id"])
    if model is None or model.workspace_id != workspace_id:
        refuse("ML_RETRAIN_PROPOSAL_INVALID", "The source model is unavailable.")
    policy = _active(db, model, db.get(Run, run_id))
    if not policy.get("propose_retraining") or not model.is_champion or model.version != job.input_ref["model_version"]:
        refuse("ML_RETRAIN_PROPOSAL_CHANGED", "The serving model or retraining policy changed after the proposal.")
    if _training_options(model) != job.input_ref["training"]:
        refuse("ML_RETRAIN_PROPOSAL_CHANGED", "The training configuration changed after the proposal.")
    dataset = db.get(TabularDataset, job.input_ref["dataset_id"])
    if (dataset is None or dataset.workspace_id != workspace_id
            or dataset.version != job.input_ref["dataset_version"] or _file_hash(dataset) != job.input_ref["dataset_sha256"]):
        refuse("ML_RETRAIN_SOURCE_CHANGED", "The feedback dataset changed after the proposal.")
    return job, model, dataset


def make_binding(db, *, proposal_id, run):
    job, _, _ = proposal_for(db, proposal_id, workspace_id=run.workspace_id, run_id=run.id)
    if job.status != "created" or job.result.get("decision_id"):
        refuse("ML_RETRAIN_ALREADY_BOUND", "This proposal already has a human decision.")
    return {"proposal_id": job.id, **{key: value for key, value in job.input_ref.items() if key != "prediction_ids"}}


def bind_decision(db, decision, binding):
    job = db.get(WorkspaceJob, binding["proposal_id"])
    job.result = {**job.result, "decision_id": decision.id}
    job.status, job.stage = "queued", "awaiting_approval"
    db.flush()


def approved_proposal(db, *, proposal_id, decision_id, run):
    if run is None:
        refuse("ML_RETRAIN_PROPOSAL_INVALID", "The approving run is unavailable.")
    job, model, dataset = proposal_for(db, proposal_id, workspace_id=run.workspace_id, run_id=run.id)
    decision = db.query(Decision).filter_by(id=decision_id, workspace_id=run.workspace_id,
        target_id=run.id, scope="run", kind="hitl_approval").first()
    if (decision is None or job.result.get("decision_id") != decision.id
            or decision.status not in {"accepted", "applied"} or not decision.human_confirmed_by
            or decision.human_confirmed_at is None
            or ((decision.rationale or {}).get("model_retraining") or {}).get("proposal_id") != job.id):
        refuse("ML_RETRAIN_HUMAN_REQUIRED", "Confirm the retraining proposal through its human Flow gate.")
    return job, model, dataset, decision


def settle_gate(db, decision):
    binding = (decision.rationale or {}).get("model_retraining") or {}
    if decision.status == "rejected":
        job = db.get(WorkspaceJob, binding.get("proposal_id"))
        if job and job.kind == PROPOSAL_KIND and job.result.get("decision_id") == decision.id:
            job.status, job.stage = "cancelled", "rejected"
            db.flush()
        refuse("ML_RETRAIN_REJECTED", "Retraining was rejected.")
    run = db.get(Run, decision.target_id)
    approved_proposal(db, proposal_id=binding.get("proposal_id"), decision_id=decision.id, run=run)
    return {"proposal_id": binding["proposal_id"]}


def stage_retraining(db, *, proposal_id, decision_id, run_id):
    from app.services.tabular_ml import create_model, validate_training

    run = db.get(Run, run_id)
    if run is None:
        refuse("ML_RETRAIN_PROPOSAL_INVALID", "The approving run is unavailable.")
    job, source, dataset, decision = approved_proposal(db, proposal_id=proposal_id, decision_id=decision_id, run=run)
    if job.result.get("model_id"):
        return job.result["model_id"]
    if job.status != "queued":
        refuse("ML_RETRAIN_PROPOSAL_INVALID", "This proposal is no longer awaiting retraining.")
    spec = validate_training(dataset, db=db, **job.input_ref["training"])
    model = create_model(db, workspace_id=source.workspace_id, spec=spec, created_by=decision.human_confirmed_by,
                         run_id=run.id, node_id="retrain")
    model.name = source.name
    model.params_json = {**model.params_json, "retraining_proposal": job.id}
    job.result = {**job.result, "model_id": model.id}
    job.status, job.stage = "running", "training_pending"
    db.commit()  # Pending model and proposal link are one recoverable intent.
    return model.id


def verify_training(db, model):
    proposal_id = (model.params_json or {}).get("retraining_proposal")
    if not proposal_id:
        return
    job = db.get(WorkspaceJob, proposal_id)
    if (job is None or job.kind != PROPOSAL_KIND or job.workspace_id != model.workspace_id
            or job.result.get("model_id") != model.id or model.dataset_id != job.input_ref.get("dataset_id")):
        refuse("ML_RETRAIN_PROPOSAL_INVALID", "The staged model does not belong to its proposal.")
    if retraining_cancel_requested(db, model):
        refuse("ML_RETRAIN_CANCELLED", "The approving run or proposal was cancelled.")
    approved_proposal(db, proposal_id=job.id, decision_id=job.result.get("decision_id"), run=db.get(Run, job.run_id))


def retraining_cancel_requested(db, model):
    """Cheap polling guard; never reread a Parquet file on the supervisor tick."""
    proposal_id = (model.params_json or {}).get("retraining_proposal")
    if not proposal_id:
        return False
    job = db.query(WorkspaceJob).filter_by(id=proposal_id, kind=PROPOSAL_KIND,
        workspace_id=model.workspace_id).populate_existing().first()
    if job is None or job.status in {"cancelled", "failed"}:
        return True
    run = db.query(Run).filter_by(id=job.run_id, workspace_id=job.workspace_id).populate_existing().first()
    decision = db.query(Decision).filter_by(id=job.result.get("decision_id"),
        workspace_id=job.workspace_id, target_id=job.run_id).populate_existing().first()
    return (run is None or run.status in {"cancelled", "failed"}
            or decision is None or decision.status not in {"accepted", "applied"}
            or not decision.human_confirmed_by or decision.human_confirmed_at is None)


def claim_training(db, model):
    """One worker may ever enter the fit for an approved retraining intent.

    Called before the ordinary training redelivery guard. Ambiguous broker ACKs
    may duplicate messages; an active duplicate must never fail the first fit.
    """
    proposal_id = (model.params_json or {}).get("retraining_proposal")
    if not proposal_id:
        return True
    job = db.query(WorkspaceJob).filter_by(id=proposal_id, kind=PROPOSAL_KIND,
        workspace_id=model.workspace_id).populate_existing().first()
    if job is None or job.result.get("model_id") != model.id:
        refuse("ML_RETRAIN_PROPOSAL_INVALID", "The model has no matching retraining intent.")
    if job.status != "running" or job.stage not in {"training_pending", "dispatching", "dispatched"}:
        return False
    verify_training(db, model)
    # Approval validation refreshes/locks the proposal. Another worker may
    # have acquired it while this one was waiting for that lock.
    if job.status != "running" or job.stage not in {"training_pending", "dispatching", "dispatched"}:
        db.rollback()
        return False
    stamp, stage = job.updated_at, job.stage
    now = datetime.utcnow()
    result = {**job.result, "worker_claimed_at": now.isoformat()}
    changed = db.query(WorkspaceJob).filter_by(id=job.id, status="running", stage=stage,
        updated_at=stamp).update({"stage": "training", "result": result, "updated_at": now}, synchronize_session=False)
    db.commit()
    return bool(changed)


def _publish_retraining(model_id, family, task_id):
    from app.services.ml.families import get_family
    from app.services.tabular_ml import run_training
    if settings.worker_eager_mode:
        return run_training(model_id)
    from app.workers.celery_app import celery_app
    return celery_app.send_task("agentium.ml_train", args=[model_id], task_id=task_id,
        queue=get_family(family).train_queue(), retry=False)


def _close_proposal(db, job, *, status, error=None, model=None):
    job.status, job.stage, job.error = status, status, error
    job.completed_at = job.updated_at = datetime.utcnow()
    if model is not None and model.status in {"pending", "training"}:
        model.cancel_requested = True
        # An active supervisor will see the flag. A lost one must not leave a
        # permanently pending/training version or permit another fit.
        model.status = "cancelled" if status == "cancelled" else "failed"
        model.status_detail, model.error = None, error
    db.commit()


def recover_retraining(*, limit=25):
    from app.db.base import SessionLocal
    from app.services.tabular_ml import clamp_timeout

    count = 0
    with SessionLocal() as db:
        jobs = db.query(WorkspaceJob).filter(WorkspaceJob.kind == PROPOSAL_KIND,
            WorkspaceJob.status.in_(["created", "queued", "running"])).order_by(
            WorkspaceJob.updated_at.asc()).limit(max(1, min(limit, 100))).all()
        for job in jobs:
            # A previous dispatch may have committed through another Session.
            db.refresh(job)
            if job.status not in {"created", "queued", "running"}:
                continue
            run = db.get(Run, job.run_id, populate_existing=True)
            decision = db.get(Decision, job.result.get("decision_id"), populate_existing=True) if job.result.get("decision_id") else None
            model = db.get(MLModel, job.result.get("model_id"), populate_existing=True) if job.result.get("model_id") else None
            if job.status in {"created", "queued"}:
                if (run is None or run.status in {"completed", "cancelled", "failed"}
                        or (decision is not None and decision.status == "rejected")):
                    _close_proposal(db, job, status="cancelled", error="ML_RETRAIN_RUN_TERMINAL")
                else:
                    # Rotate waiting gates so they cannot starve pending fits.
                    job.updated_at = datetime.utcnow()
                    db.commit()
                continue
            if model is None:
                _close_proposal(db, job, status="failed", error="ML_MODEL_NOT_FOUND")
                continue
            if model.status in {"ready", "failed", "cancelled"}:
                job.status = "completed" if model.status == "ready" else model.status
                job.stage, job.error, job.completed_at = model.status, model.error, datetime.utcnow()
                db.commit()
                continue
            if retraining_cancel_requested(db, model):
                _close_proposal(db, job, status="cancelled", error="ML_RETRAIN_CANCELLED", model=model)
                continue
            if job.stage == "training":
                claimed_at = job.result.get("worker_claimed_at")
                try:
                    claimed_at = datetime.fromisoformat(claimed_at)
                except (TypeError, ValueError):
                    claimed_at = job.updated_at
                if datetime.utcnow() >= claimed_at + timedelta(seconds=clamp_timeout(settings.ml_train_timeout_s) + 120):
                    _close_proposal(db, job, status="failed", error="ML_RETRAIN_WORKER_LOST", model=model)
                else:
                    # The immutable claim timestamp owns the deadline; this
                    # sweep timestamp rotates active fits behind pending work.
                    job.updated_at = datetime.utcnow()
                    db.commit()
                continue
            if job.stage not in {"training_pending", "dispatching", "dispatched"} or model.status != "pending":
                continue
            now = datetime.utcnow()
            if job.stage != "training_pending" and job.updated_at > now - timedelta(seconds=60):
                continue
            try:
                verify_training(db, model)
            except TabularError as exc:
                db.rollback()
                db.refresh(job)
                _close_proposal(db, job, status="failed", error=exc.code, model=model)
                continue
            except Exception:
                db.rollback()
                continue  # a transient artifact-store outage is not approval
            if (job.status != "running" or job.stage not in {"training_pending", "dispatching", "dispatched"}
                    or (job.stage != "training_pending" and job.updated_at > now - timedelta(seconds=60))):
                db.rollback()
                continue
            stamp, stage = job.updated_at, job.stage
            task_id = operational_job_id("ml_train", model.workspace_id, model.id)
            result = {**job.result, "dispatch_attempts": int(job.result.get("dispatch_attempts", 0)) + 1,
                      "task_id": task_id}
            changed = db.query(WorkspaceJob).filter_by(id=job.id, status="running", stage=stage,
                updated_at=stamp).update({"stage": "dispatching", "result": result, "updated_at": now}, synchronize_session=False)
            if not changed:
                db.rollback()
                continue
            model.celery_task_id = task_id
            model_id, family = model.id, model.family
            db.commit()  # Broker ACK may be lost; worker CAS remains authority.
            try:
                _publish_retraining(model_id, family, task_id)
                count += 1
                db.query(WorkspaceJob).filter_by(id=job.id, status="running", stage="dispatching",
                    updated_at=now).update({"stage": "dispatched", "updated_at": now}, synchronize_session=False)
                db.commit()
            except Exception:
                # Do not clear the task id or worker claim after an ambiguous
                # ACK. An expired dispatch lease republishes the same identity.
                db.rollback()
    return {"dispatched": count}


def monitoring_view(db, model):
    policy = policy_for(model)
    jobs = db.query(WorkspaceJob).filter_by(workspace_id=model.workspace_id, system_id=policy.get("system_id")).filter(
        WorkspaceJob.kind.in_([SNAPSHOT_KIND, PROPOSAL_KIND])).order_by(WorkspaceJob.created_at.desc()).limit(40).all() if policy.get("system_id") else []
    history, proposals = [], []
    for job in jobs:
        if job.kind == SNAPSHOT_KIND:
            measured = (job.result or {}).get("report") or {}
            history.append({"id": job.id, "created_at": job.created_at.isoformat(), "badge": measured.get("badge"),
                            "window": measured.get("window"), "reason": (job.result.get("last_result") or {}).get("reason")})
        else:
            binding = job.input_ref
            proposals.append({"id": job.id, "status": job.status, "stage": job.stage, "error": job.error,
                "created_at": job.created_at.isoformat(), "run_id": job.run_id, "decision_id": job.result.get("decision_id"),
                "model_id": job.result.get("model_id"), "source_model_id": model.id, "source_model_name": binding["model_name"],
                "source_version": binding["model_version"],
                "dataset_id": binding["dataset_id"], "dataset_version": binding["dataset_version"],
                "dataset_sha256": binding["dataset_sha256"], "labeled_rows": binding["labeled_rows"], "training": binding["training"], "evidence": binding.get("evidence")})
    return {"supported": (model.family or "tabular") == "tabular" and model.task in {"classification", "regression"},
            "policy": {"enabled": False, "propose_retraining": False, "interval_minutes": 60, **policy},
            "history": history[:20], "proposals": proposals[:20]}
