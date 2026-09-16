"""Reviewed, versioned evaluation cases and canonical Run comparisons."""
from typing import Any, Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1.endpoints.flow_workbench import _authorize, _raise_workbench
from app.api.v1.endpoints.runs import _visible_run_or_404
from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.evaluation_campaign import EvaluationCampaign, EvaluationSuite
from app.models.user import User
from app.models.workspace import Workspace
from app.services.evaluation import campaigns as service
from app.services.systems.flow_workbench import FlowWorkbenchError
from app.services.workspace_jobs import dispatch_workspace_job
from app.models.workspace_job import WorkspaceJob

router = APIRouter()


def dispatch_job(db, workspace, job):
    task_id = dispatch_workspace_job(db, workspace, job, allow_inline_fallback=False)
    if task_id is None and job.status in {"created", "queued"}:
        job.status, job.stage = "failed", "dispatch_unavailable"
        job.error = "The evaluation worker is unavailable. No evaluation was performed."
    db.commit()


class AssertionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    path: list[str] = Field(default_factory=list, max_length=12)
    operator: Literal["equals", "contains", "not_contains", "exists", "quotes_in_source"]
    value: Any = None

    @model_validator(mode="after")
    def validate_value(self):
        if self.operator != "exists" and "value" not in self.model_fields_set:
            raise ValueError("An assertion value is required")
        if self.operator in {"contains", "not_contains", "quotes_in_source"} and (not isinstance(self.value, str) or not self.value):
            raise ValueError("Text assertions require non-empty text")
        return self


class CaseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    input_ref: dict[str, Any]
    assertions: list[AssertionBody] = Field(default_factory=list, max_length=30)
    reference_run_id: str | None = None
    question: str | None = Field(default=None, max_length=8000)
    reference_answer: str | None = Field(default=None, max_length=16000)
    reference_context: str | None = Field(default=None, max_length=32000)
    answer_path: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def unique_assertions(self):
        if len({assertion.id for assertion in self.assertions}) != len(self.assertions):
            raise ValueError("Assertion ids must be unique within a case")
        return self


class SuiteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    system_id: str
    name: str = Field(min_length=1, max_length=160)
    cases: list[CaseBody] = Field(min_length=1, max_length=20)
    collection_ids: list[str] = Field(default_factory=list, max_length=20)
    reviewed: Literal[True]
    generation_job_id: str | None = None

    @field_validator("reviewed", mode="before")
    @classmethod
    def explicit_review(cls, value):
        if value is not True:
            raise ValueError("Explicit review is required")
        return value

    @model_validator(mode="after")
    def unique_cases(self):
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("Case ids must be unique")
        return self


class CampaignBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suite_id: str
    baseline_run_id: str
    expected_draft_revision: int = Field(ge=1)
    request_key: str = Field(min_length=1, max_length=160)
    ingress_id: str | None = None
    kind: Literal["manual", "chat", "http", "schedule", "event"] | None = None


def authorize_suite(db, suite, workspace, user):
    if not suite or suite.workspace_id != workspace.id:
        raise HTTPException(404, "Suite not found")
    _authorize(db, system_id=suite.system_id, workspace=workspace, user=user)
    for case in suite.cases:
        if case.get("reference_run_id"):
            _visible_run_or_404(db, run_id=case["reference_run_id"], workspace=workspace, user=user)
    # Recheck collection membership on every read; withdrawn documents are not
    # silently exposed through a copied suite.
    service.corpus_manifest(db, workspace.id, [item["id"] for item in suite.corpus_manifest])
    return suite


@router.post("/suites", status_code=201)
def create_suite(body: SuiteBody, workspace: Workspace = Depends(get_current_workspace),
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    suite = _create_suite_record(body, workspace=workspace, user=user, db=db)
    db.commit()
    return service.serialize_suite(suite)


def _create_suite_record(body: SuiteBody, *, workspace, user, db):
    _authorize(db, system_id=body.system_id, workspace=workspace, user=user)
    cases = [case.model_dump(exclude_none=True) for case in body.cases]
    from app.services.systems.flow_workbench import validate_golden_cases, _json_size
    try:
        _json_size(cases, code="EVALUATION_SUITE_TOO_LARGE", limit=1024 * 1024)
        validate_golden_cases(cases)
    except FlowWorkbenchError as exc:
        _raise_workbench(db, exc)
    for case in cases:
        if case.get("reference_run_id"):
            run = _visible_run_or_404(db, run_id=case["reference_run_id"], workspace=workspace, user=user)
            if run.system_id != body.system_id:
                raise HTTPException(422, "Reference Run belongs to another System")
    revision = (db.query(func.max(EvaluationSuite.revision)).filter_by(workspace_id=workspace.id, system_id=body.system_id, name=body.name).scalar() or 0) + 1
    manifest = service.corpus_manifest(db, workspace.id, body.collection_ids)
    provenance = {"method": "human_authored", "reviewed_by": user.id}
    if body.generation_job_id:
        job = db.get(WorkspaceJob, body.generation_job_id)
        if not job or job.workspace_id != workspace.id or job.system_id != body.system_id or job.kind != "evaluation_generation" or job.status != "completed":
            raise HTTPException(404, "Completed generation not found")
        if job.created_by_user_id != user.id:
            raise HTTPException(404, "Generation not found")
        if (job.result or {}).get("corpus_manifest") != manifest:
            raise HTTPException(409, "Generation corpus changed; regenerate before review")
        provenance = {"method": "giskard_raget_generated_human_reviewed", "generation_job_id": job.id,
            "reviewed_by": user.id, "version": job.result.get("version"), "usage": job.result.get("usage"),
            "models": job.result.get("models"), "corpus_sha256": job.result.get("corpus_sha256")}
    suite = EvaluationSuite(workspace_id=workspace.id, system_id=body.system_id, name=body.name, revision=revision,
        cases=cases, corpus_manifest=manifest, provenance=provenance, created_by_user_id=user.id)
    db.add(suite)
    db.flush()
    return suite


@router.get("/suites")
def list_suites(system_id: str, workspace: Workspace = Depends(get_current_workspace),
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _authorize(db, system_id=system_id, workspace=workspace, user=user)
    rows = db.query(EvaluationSuite).filter_by(workspace_id=workspace.id, system_id=system_id).order_by(EvaluationSuite.created_at.desc()).limit(100).all()
    visible = []
    for row in rows:
        try:
            authorize_suite(db, row, workspace, user)
        except HTTPException:
            continue
        visible.append(service.serialize_suite(row))
    return visible


class GenerationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    system_id: str
    collection_ids: list[str] = Field(min_length=1, max_length=5)
    num_questions: int = Field(default=3, ge=1, le=20)
    language: Literal["fr", "en"] = "fr"
    max_calls: int = Field(default=40, ge=1, le=100)
    max_tokens: int = Field(default=100_000, ge=1, le=200_000)
    request_key: str = Field(min_length=1, max_length=160)


@router.post("/generations", status_code=201)
def generate_cases(body: GenerationBody, workspace: Workspace = Depends(get_current_workspace),
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _authorize(db, system_id=body.system_id, workspace=workspace, user=user)
    from app.core.config import settings
    from app.services.model_plane.execution import resolve_model_execution
    from app.services.workspace_jobs import create_workspace_job, serialize_job
    from app.models.system import System
    db.query(System).filter_by(id=body.system_id, workspace_id=workspace.id).with_for_update(of=System).one()
    request_sha = service.digest(body.model_dump())
    existing = db.query(WorkspaceJob).filter(WorkspaceJob.workspace_id == workspace.id,
        WorkspaceJob.created_by_user_id == user.id, WorkspaceJob.kind == "evaluation_generation",
        WorkspaceJob.input_ref["request_key"].as_string() == body.request_key).first()
    if existing:
        if existing.input_ref.get("request_sha256") != request_sha:
            raise HTTPException(409, "Generation request key already used")
        service.validate_generation_policy(db, system_id=existing.system_id, workspace_id=workspace.id, inputs=existing.input_ref)
        return serialize_job(existing)
    execution = resolve_model_execution(workspace, provider="workspace")
    if execution.provider != "openai" or not execution._api_key:
        raise HTTPException(409, "Giskard generation requires the configured OpenAI provider")
    inputs = body.model_dump()
    inputs["request_sha256"] = request_sha
    inputs["corpus_manifest"] = service.corpus_manifest(db, workspace.id, body.collection_ids)
    service.freeze_generation_models(db, workspace, body.system_id, inputs)
    job = create_workspace_job(db, workspace, user, kind="evaluation_generation", title="Giskard testset",
                               system_id=body.system_id, input_ref=inputs, status="queued")
    db.commit()
    dispatch_job(db, workspace, job)
    return serialize_job(job)


@router.get("/generations/{job_id}")
def get_generation(job_id: str, workspace: Workspace = Depends(get_current_workspace),
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.workspace_jobs import serialize_job
    job = db.get(WorkspaceJob, job_id)
    if not job or job.workspace_id != workspace.id or job.created_by_user_id != user.id or job.kind not in {"evaluation_generation", "evaluation_raget"}:
        raise HTTPException(404, "Generation not found")
    _authorize(db, system_id=job.system_id, workspace=workspace, user=user)
    if job.kind == "evaluation_raget":
        authorize_campaign(db, db.get(EvaluationCampaign, job.input_ref["campaign_id"]), workspace, user)
    service.validate_generation_policy(db, system_id=job.system_id, workspace_id=workspace.id, inputs=job.input_ref)
    from datetime import datetime
    last_update = job.updated_at or job.created_at
    if job.status in {"queued", "running"} and last_update and (datetime.utcnow() - last_update).total_seconds() > 1200:
        job.status, job.stage = "failed", "worker_interrupted"
        job.error = "The offline evaluation worker stopped reporting progress. Start a new attempt; no result is certified."
        job.completed_at = datetime.utcnow()
        db.commit()
    return serialize_job(job)


class RagetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=160)


@router.post("/campaigns/{campaign_id}/raget", status_code=201)
def evaluate_raget(campaign_id: str, body: RagetBody, workspace: Workspace = Depends(get_current_workspace),
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.workspace_jobs import create_workspace_job, serialize_job
    campaign = authorize_campaign(db, db.query(EvaluationCampaign).filter_by(id=campaign_id, workspace_id=workspace.id).with_for_update().one_or_none(), workspace, user)
    existing = db.query(WorkspaceJob).filter(WorkspaceJob.workspace_id == workspace.id,
        WorkspaceJob.created_by_user_id == user.id, WorkspaceJob.kind == "evaluation_raget",
        WorkspaceJob.input_ref["request_key"].as_string() == body.request_key).first()
    if existing:
        if existing.input_ref.get("campaign_id") != campaign_id:
            raise HTTPException(409, "RAGET request key already used for another campaign")
        service.validate_generation_policy(db, system_id=campaign.system_id, workspace_id=workspace.id, inputs=existing.input_ref)
        return serialize_job(existing)
    service.refresh_campaign(db, campaign)
    if campaign.status != "completed" or campaign.snapshot["comparability"] == "not_comparable":
        raise HTTPException(409, "Complete a comparable campaign before RAGET evaluation")
    cases = campaign.snapshot["cases"]
    if any(not case.get("question") or not case.get("reference_answer") for case in cases):
        raise HTTPException(422, "Review a question and reference answer for every RAGET case")
    if len({case["question"] for case in cases}) != len(cases):
        raise HTTPException(422, "RAGET questions must be unique")
    manifest = campaign.snapshot["corpus_manifest"]
    if not manifest:
        raise HTTPException(422, "RAGET requires the reviewed corpus")
    inputs = {"campaign_id": campaign.id, "request_key": body.request_key,
        "collection_ids": [item["id"] for item in manifest], "corpus_manifest": manifest,
        "num_questions": len(cases), "language": "en", "max_calls": 80, "max_tokens": 200_000}
    service.freeze_generation_models(db, workspace, campaign.system_id, inputs)
    job = create_workspace_job(db, workspace, user, kind="evaluation_raget", title="Giskard RAGET report",
        system_id=campaign.system_id, status="queued", input_ref=inputs)
    snapshot = dict(campaign.snapshot)
    snapshot["raget_job_id"] = job.id
    campaign.snapshot = snapshot
    db.commit()
    dispatch_job(db, workspace, job)
    return serialize_job(job)


@router.post("/campaigns", status_code=201)
def create_campaign(body: CampaignBody, workspace: Workspace = Depends(get_current_workspace),
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    suite = authorize_suite(db, db.get(EvaluationSuite, body.suite_id), workspace, user)
    baseline = _visible_run_or_404(db, run_id=body.baseline_run_id, workspace=workspace, user=user)
    try:
        campaign = service.create_campaign(db, suite=suite, baseline=baseline, workspace=workspace, user=user, body=body.model_dump())
        db.commit()
    except FlowWorkbenchError as exc:
        _raise_workbench(db, exc)
    job = db.get(WorkspaceJob, campaign.job_id)
    if job and job.status == "queued" and not (job.input_ref or {}).get("task_id"):
        dispatch_job(db, workspace, job)
    if job and job.status == "failed":
        campaign.status = "failed"
        service.cancel_pending_cases(db, campaign, "Evaluation worker dispatch unavailable; this case was not executed.")
        db.commit()
    return service.serialize_campaign(campaign)


def authorize_campaign(db, row, workspace, user):
    if not row or row.workspace_id != workspace.id:
        raise HTTPException(404, "Campaign not found")
    authorize_suite(db, db.get(EvaluationSuite, row.suite_id), workspace, user)
    _visible_run_or_404(db, run_id=row.baseline_run_id, workspace=workspace, user=user)
    for case in row.results:
        for side in ("baseline", "candidate"):
            _visible_run_or_404(db, run_id=case[side]["run_id"], workspace=workspace, user=user)
    return row


@router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: str, workspace: Workspace = Depends(get_current_workspace),
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    campaign = authorize_campaign(db, db.get(EvaluationCampaign, campaign_id), workspace, user)
    service.refresh_campaign(db, campaign)
    db.commit()
    return service.serialize_campaign(campaign)


@router.get("/campaigns")
def list_campaigns(system_id: str, workspace: Workspace = Depends(get_current_workspace),
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _authorize(db, system_id=system_id, workspace=workspace, user=user)
    rows = db.query(EvaluationCampaign).filter_by(workspace_id=workspace.id, system_id=system_id).order_by(EvaluationCampaign.created_at.desc()).limit(100).all()
    visible = []
    for row in rows:
        try:
            authorize_campaign(db, row, workspace, user)
        except HTTPException:
            continue
        service.refresh_campaign(db, row)
        visible.append(service.serialize_campaign(row))
    db.commit()
    return visible
