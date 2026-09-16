"""Admin-only Flow Builder preview, isolated-node and golden-set endpoints."""

from __future__ import annotations

import copy
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session as DBSession

from app.api.v1.endpoints.systems import _enforce_system_admin
from app.core.auth import get_current_user, get_current_workspace
from app.core.iam.dependencies import current_membership
from app.core.iam.roles import is_admin_template
from app.db.base import get_db
from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services.run_engine import schedule_run
from app.services.run_engine.debug_contract import DebugContractError, normalize_input_debug
from app.services.run_engine.dispatch_outbox import (
    TRIGGER_RUN,
    enqueue_dispatch,
    reconcile_dispatch_outbox,
)
from app.services.systems import flow_workbench

router = APIRouter()


class WorkbenchFlowBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    acknowledge_real_side_effects: Literal[True]
    flow_definition: dict[str, Any]
    expected_flow_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_ref: dict[str, Any] = Field(default_factory=dict)
    ingress_id: str | None = Field(default=None, min_length=1, max_length=160)
    kind: Literal["manual", "chat", "http", "schedule", "event"] | None = None

    @field_validator("acknowledge_real_side_effects", mode="before")
    @classmethod
    def validate_real_side_effects_ack(cls, value: Any) -> Any:
        if value is not True:
            raise ValueError("acknowledge_real_side_effects must be the boolean true")
        return value

    @model_validator(mode="after")
    def validate_controls(self) -> WorkbenchFlowBody:
        if (self.ingress_id is None) != (self.kind is None):
            raise ValueError("ingress_id and kind must be provided together")
        try:
            self.input_ref = normalize_input_debug(self.input_ref)
        except DebugContractError as exc:
            raise ValueError(exc.message) from exc
        return self


class WorkbenchNodeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    acknowledge_real_side_effects: Literal[True]
    flow_definition: dict[str, Any]
    expected_flow_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    node_id: str = Field(min_length=1, max_length=160)
    input_ref: dict[str, Any] = Field(default_factory=dict)

    @field_validator("acknowledge_real_side_effects", mode="before")
    @classmethod
    def validate_real_side_effects_ack(cls, value: Any) -> Any:
        if value is not True:
            raise ValueError("acknowledge_real_side_effects must be the boolean true")
        return value

    @field_validator("node_id")
    @classmethod
    def validate_node_id(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("node_id must already be trimmed")
        return value

    @field_validator("input_ref")
    @classmethod
    def validate_input_ref(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            return normalize_input_debug(value)
        except DebugContractError as exc:
            raise ValueError(exc.message) from exc


class GoldenCaseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=160)
    input_ref: dict[str, Any] = Field(default_factory=dict)
    expected: Any = None

    @field_validator("id")
    @classmethod
    def validate_case_id(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("golden case id must already be trimmed")
        return value


class WorkbenchGoldenBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    acknowledge_real_side_effects: Literal[True]
    flow_definition: dict[str, Any]
    expected_flow_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ingress_id: str | None = Field(default=None, min_length=1, max_length=160)
    kind: Literal["manual", "chat", "http", "schedule", "event"] | None = None
    cases: list[GoldenCaseBody] | None = Field(default=None, min_length=1, max_length=20)
    suite_id: str | None = Field(default=None, min_length=1, max_length=36)
    request_key: str | None = Field(default=None, min_length=1, max_length=160)

    @field_validator("acknowledge_real_side_effects", mode="before")
    @classmethod
    def validate_real_side_effects_ack(cls, value: Any) -> Any:
        if value is not True:
            raise ValueError("acknowledge_real_side_effects must be the boolean true")
        return value

    @model_validator(mode="after")
    def validate_controls(self) -> WorkbenchGoldenBody:
        if (self.ingress_id is None) != (self.kind is None):
            raise ValueError("ingress_id and kind must be provided together")
        if (self.cases is None) == (self.suite_id is None):
            raise ValueError("Provide either cases or a reviewed suite_id")
        if self.suite_id and not self.request_key:
            raise ValueError("Suite execution requires a request_key")
        case_ids = [case.id for case in (self.cases or [])]
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("golden case ids must be unique")
        return self


def _system_or_404(
    db: DBSession,
    *,
    system_id: str,
    workspace_id: str,
) -> System:
    system = (
        db.query(System)
        .filter(System.id == system_id, System.workspace_id == workspace_id)
        .one_or_none()
    )
    if system is None:
        raise HTTPException(404, "System not found")
    return system


def _raise_workbench(db: DBSession, exc: flow_workbench.FlowWorkbenchError) -> None:
    db.rollback()
    raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


def _require_workbench_admin(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
) -> None:
    if user.role == "admin":
        return
    membership = current_membership(db, user, workspace)
    if membership is not None and is_admin_template(
        membership.role_template,
        membership.role,
    ):
        return
    raise HTTPException(
        status_code=403,
        detail={
            "code": "FLOW_WORKBENCH_ADMIN_REQUIRED",
            "message": "Admin or owner access is required for Flow Workbench execution.",
        },
    )


def _authorize(
    db: DBSession,
    *,
    system_id: str,
    workspace: Workspace,
    user: User,
) -> System:
    try:
        flow_workbench.require_flow_workbench(workspace)
    except flow_workbench.FlowWorkbenchError as exc:
        _raise_workbench(db, exc)
    system = _system_or_404(
        db,
        system_id=system_id,
        workspace_id=workspace.id,
    )
    _require_workbench_admin(db, workspace=workspace, user=user)
    _enforce_system_admin(
        db,
        user=user,
        workspace=workspace,
        system=system,
        mutation="flow_workbench_execute",
    )
    return system


def _run_payload(run: Run) -> dict[str, Any]:
    contract = run.execution_contract if isinstance(run.execution_contract, dict) else {}
    execution = (
        run.input_ref.get("execution")
        if isinstance(run.input_ref, dict) and isinstance(run.input_ref.get("execution"), dict)
        else {}
    )
    return {
        "id": run.id,
        "system_id": run.system_id,
        "status": run.status,
        "execution_surface": run.execution_surface,
        "flow_sha256": run.flow_sha256,
        "source_flow_sha256": execution.get("source_flow_sha256"),
        "runtime_mode": contract.get("runtime_mode"),
        "input_ref": copy.deepcopy(run.input_ref or {}),
        "output_ref": copy.deepcopy(run.output_ref or {}),
        "error": run.error,
        "checkpoints": copy.deepcopy(run.checkpoints or []),
    }


@router.post("/{system_id}/flow-workbench/preview-runs", status_code=201)
async def create_preview_run(
    system_id: str,
    body: WorkbenchFlowBody,
    background_tasks: BackgroundTasks,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _authorize(db, system_id=system_id, workspace=workspace, user=user)
    try:
        prepared = flow_workbench.prepare_preview(
            db,
            system_id=system_id,
            workspace=workspace,
            flow_definition=body.flow_definition,
            expected_flow_sha256=body.expected_flow_sha256,
            ingress_id=body.ingress_id,
            ingress_kind=body.kind,
        )
        run = flow_workbench.create_run(
            db,
            prepared=prepared,
            workspace=workspace,
            user_id=str(user.id) if getattr(user, "id", None) else None,
            surface="builder_preview",
            input_ref=body.input_ref,
            metadata={
                "real_side_effects_acknowledged": body.acknowledge_real_side_effects,
            },
        )
        db.commit()
        db.refresh(run)
    except flow_workbench.FlowWorkbenchError as exc:
        _raise_workbench(db, exc)
    background_tasks.add_task(schedule_run, run.id)
    return _run_payload(run)


@router.post("/{system_id}/flow-workbench/node-runs", status_code=201)
async def create_node_preview_run(
    system_id: str,
    body: WorkbenchNodeBody,
    background_tasks: BackgroundTasks,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _authorize(db, system_id=system_id, workspace=workspace, user=user)
    try:
        prepared = flow_workbench.prepare_node_preview(
            db,
            system_id=system_id,
            workspace=workspace,
            flow_definition=body.flow_definition,
            expected_flow_sha256=body.expected_flow_sha256,
            node_id=body.node_id,
            input_ref=body.input_ref,
        )
        run = flow_workbench.create_run(
            db,
            prepared=prepared,
            workspace=workspace,
            user_id=str(user.id) if getattr(user, "id", None) else None,
            surface="node_preview",
            input_ref=body.input_ref,
            metadata={
                "node_id": body.node_id,
                "real_side_effects_acknowledged": body.acknowledge_real_side_effects,
            },
        )
        db.commit()
        db.refresh(run)
    except flow_workbench.FlowWorkbenchError as exc:
        _raise_workbench(db, exc)
    background_tasks.add_task(schedule_run, run.id)
    return _run_payload(run)


@router.post("/{system_id}/flow-workbench/golden-runs", status_code=201)
async def create_golden_preview_runs(
    system_id: str,
    body: WorkbenchGoldenBody,
    background_tasks: BackgroundTasks,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _authorize(db, system_id=system_id, workspace=workspace, user=user)
    raw_cases: list[dict[str, Any]] = []
    for case in body.cases or []:
        raw_case: dict[str, Any] = {
            "id": case.id,
            "input_ref": copy.deepcopy(case.input_ref),
        }
        # An omitted oracle means "do not evaluate this case against an
        # expected value".  It is semantically different from an explicit
        # JSON null and must survive Pydantic's default value.
        if "expected" in case.model_fields_set:
            raw_case["expected"] = copy.deepcopy(case.expected)
        raw_cases.append(raw_case)
    suite = None
    if body.suite_id:
        from app.models.evaluation_campaign import EvaluationSuite
        from app.api.v1.endpoints.evaluation_campaigns import authorize_suite
        from app.services.evaluation.campaigns import corpus_manifest, validate_brd_corpus_bindings
        suite = authorize_suite(db, db.get(EvaluationSuite, body.suite_id), workspace, user)
        if suite.system_id != system_id:
            raise HTTPException(422, "The suite belongs to a different System")
        if corpus_manifest(db, workspace.id, [item["id"] for item in suite.corpus_manifest]) != suite.corpus_manifest:
            raise HTTPException(409, "Corpus changed; review a new suite revision")
        raw_cases = copy.deepcopy(suite.cases)
    from app.services.flow_contracts import canonical_sha256
    legacy_request_sha256 = canonical_sha256(body.model_dump())
    request_sha256 = canonical_sha256({
        **body.model_dump(),
        **({"cases": raw_cases} if body.cases is not None else {}),
    })
    try:
        if body.request_key:
            # Serialize submissions for this System using the existing row lock.
            flow_workbench._locked_system(db, system_id=system_id, workspace=workspace)
            previous = db.query(Run).filter(
                Run.workspace_id == workspace.id, Run.system_id == system_id,
                Run.initiated_by_user_id == user.id, Run.execution_surface == "golden_preview",
                Run.input_ref["execution"]["golden_request_key"].as_string() == body.request_key,
            ).order_by(Run.started_at, Run.id).all()
            if previous:
                for run in previous:
                    execution = run.input_ref["execution"]
                    expected_sha256 = (
                        request_sha256 if execution.get("initial_dispatch_plane") == "celery"
                        else legacy_request_sha256
                    )
                    if execution.get("golden_request_sha256") != expected_sha256:
                        raise HTTPException(409, "Request key already used for another test batch")
                execution = previous[0].input_ref["execution"]
                db.commit()  # Release the request's System lock before replying.
                background_tasks.add_task(reconcile_dispatch_outbox)
                return {"batch_id": execution["golden_batch_id"],
                    "flow_sha256": execution["source_flow_sha256"],
                    "runs": [_run_payload(run) for run in previous]}
        flow_workbench.validate_golden_cases(raw_cases)
        prepared = flow_workbench.prepare_preview(
            db,
            system_id=system_id,
            workspace=workspace,
            flow_definition=body.flow_definition,
            expected_flow_sha256=body.expected_flow_sha256,
            ingress_id=body.ingress_id,
            ingress_kind=body.kind,
        )
        corpus_limitations = validate_brd_corpus_bindings(
            db, workspace_id=workspace.id, suite=suite, contract=prepared.contract,
        ) if suite is not None else []
        batch_id = str(uuid4())
        runs: list[Run] = []
        for case in raw_cases:
            checkpoint: dict[str, Any] = {
                "kind": "golden_case_queued",
                "batch_id": batch_id,
                "case_id": case["id"],
            }
            if suite is not None:
                checkpoint["suite_id"] = suite.id
                checkpoint["suite_revision"] = suite.revision
                checkpoint["brd_proposal_id"] = (suite.provenance or {}).get("brd_proposal_id")
                checkpoint["brd_proposal_sha256"] = (suite.provenance or {}).get("brd_proposal_sha256")
                checkpoint["assertions"] = copy.deepcopy(case.get("assertions", []))
                if corpus_limitations:
                    checkpoint["corpus_limitations"] = corpus_limitations
            if "expected" in case:
                checkpoint["expected"] = copy.deepcopy(case["expected"])
            run = flow_workbench.create_run(
                db,
                prepared=prepared,
                workspace=workspace,
                user_id=str(user.id) if getattr(user, "id", None) else None,
                surface="golden_preview",
                input_ref=case["input_ref"],
                metadata={
                    "golden_batch_id": batch_id,
                    "golden_case_id": case["id"],
                    "initial_dispatch_plane": "celery",
                    "golden_request_sha256": request_sha256,
                    **({"golden_request_key": body.request_key} if body.request_key else {}),
                    "real_side_effects_acknowledged": (
                        body.acknowledge_real_side_effects
                    ),
                },
                checkpoints=[checkpoint],
            )
            # This server-owned claim opts only newly created Golden Runs into
            # worker recovery. Historical API-background Runs stay untouched.
            run.trigger_dedup_key = f"golden:{batch_id}:{run.id}"
            enqueue_dispatch(
                db,
                event_type=TRIGGER_RUN,
                workspace_id=workspace.id,
                run_id=run.id,
                source_id=run.trigger_dedup_key,
            )
            runs.append(run)
        db.commit()
        for run in runs:
            db.refresh(run)
    except flow_workbench.FlowWorkbenchError as exc:
        _raise_workbench(db, exc)
    except Exception:
        db.rollback()
        raise
    # This fast path only publishes identifier-only tasks; maintenance owns
    # retries if the API exits or the broker is temporarily unavailable.
    background_tasks.add_task(reconcile_dispatch_outbox)
    return {
        "batch_id": batch_id,
        "flow_sha256": prepared.source_flow_sha256,
        "runs": [_run_payload(run) for run in runs],
    }
