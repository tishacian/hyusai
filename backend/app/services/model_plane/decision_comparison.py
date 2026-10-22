"""Compare model decisions on retained observations, never dispatch their tools.

The only executable node in a comparison is the native decide_next_v1 Skill.
Inputs come from one authorized, settled invocation, not from client-authored
tool lists or claims about evidence. Workbench Runs retain canonical policy,
model resolution, usage and dispatch evidence.
"""

from __future__ import annotations

import copy
from datetime import timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.services.flow_contracts import canonical_sha256
from app.services.run_access import readable_runs, readable_skill_invocations_for_runs
from app.services.run_engine.dispatch_outbox import TRIGGER_RUN, enqueue_dispatch
from app.services.run_engine.execution_contract import canonical_flow_sha256
from app.services.systems import flow_publication, flow_workbench

DECISION_SKILL = "decide_next_v1"
INPUT_FIELDS = frozenset(
    {
        "goal",
        "observations",
        "visible_skills",
        "budget",
        "confidence_floor",
        "agent_loop_node_id",
        "context",
        "context_evidence",
    }
)


def decision_input(invocation: SkillInvocation) -> dict[str, Any]:
    from app.services.run_engine.agent_loop import verify_decision_context_payload

    value = invocation.input_ref
    if (
        invocation.skill_slug != DECISION_SKILL
        or invocation.status != "completed"
        or not isinstance(value, dict)
    ):
        raise HTTPException(
            409,
            detail={
                "code": "DECISION_SAMPLE_UNAVAILABLE",
                "message": "Choose a completed agent decision.",
            },
        )
    if not isinstance(value.get("goal"), dict) or not isinstance(value.get("visible_skills"), list):
        raise HTTPException(
            409,
            detail={
                "code": "DECISION_SAMPLE_INCOMPLETE",
                "message": "This decision did not retain its instructions and allowed tools.",
            },
        )
    # Provider selection is the only variable. Do not replay engine controls or
    # a client's former provider/model overrides from the invocation envelope.
    result = {key: copy.deepcopy(item) for key, item in value.items() if key in INPUT_FIELDS}
    try:
        verify_decision_context_payload(result)
    except ValueError as exc:
        raise HTTPException(
            409,
            detail={
                "code": "DECISION_CONTEXT_INCOMPATIBLE",
                "message": "This decision did not retain verifiable context. Choose a newer decision.",
            },
        ) from exc
    flow_workbench._json_size(result, code="DECISION_SAMPLE_TOO_LARGE", limit=128 * 1024)
    return result


def sample(db, *, invocation_id: str, workspace, user):
    row = (
        db.query(SkillInvocation, Run, System)
        .join(Run, Run.id == SkillInvocation.run_id)
        .join(
            System,
            System.id == Run.system_id,
        )
        .filter(
            SkillInvocation.id == invocation_id,
            Run.workspace_id == workspace.id,
            System.workspace_id == workspace.id,
        )
        .first()
    )
    if row is None or not readable_runs(db, runs=[row[1]], user=user, workspace=workspace):
        raise HTTPException(
            404, detail={"code": "DECISION_SAMPLE_NOT_FOUND", "message": "Decision not found."}
        )
    invocation, run, system = row
    if not readable_skill_invocations_for_runs(
        db, invocations=[invocation], runs=[run], user=user, workspace=workspace
    ):
        raise HTTPException(
            404, detail={"code": "DECISION_SAMPLE_NOT_FOUND", "message": "Decision not found."}
        )
    inputs = decision_input(invocation)
    return invocation, run, system, inputs


def public_sample(invocation, run, system, inputs):
    trace = invocation.trace if isinstance(invocation.trace, dict) else {}
    model = trace.get("model_execution") if isinstance(trace.get("model_execution"), dict) else {}
    output = invocation.output_ref if isinstance(invocation.output_ref, dict) else {}
    started_at = invocation.started_at
    if started_at is not None and started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return {
        "invocation_id": invocation.id,
        "run_id": run.id,
        "system_id": system.id,
        "system_name": system.name,
        "node_id": inputs.get("agent_loop_node_id"),
        "started_at": started_at.isoformat() if started_at else None,
        "objective": str(inputs["goal"].get("objective") or "")[:2400],
        "observations_count": len(inputs.get("observations") or []),
        "next_skill": output.get("next_skill"),
        "input_sha256": canonical_sha256(inputs),
        "instruction_sha256": canonical_sha256(inputs["goal"]),
        "model": {
            key: model[key] for key in ("provider", "model", "returned_model") if key in model
        },
    }


def list_samples(db, *, workspace, user):
    rows = (
        db.query(SkillInvocation, Run, System)
        .join(Run, Run.id == SkillInvocation.run_id)
        .join(
            System,
            System.id == Run.system_id,
        )
        .filter(
            Run.workspace_id == workspace.id,
            System.workspace_id == workspace.id,
            SkillInvocation.skill_slug == DECISION_SKILL,
            SkillInvocation.status == "completed",
        )
        .order_by(SkillInvocation.started_at.desc(), SkillInvocation.id)
        .limit(100)
        .all()
    )
    readable = readable_runs(
        db, runs=list({row[1].id: row[1] for row in rows}.values()), user=user, workspace=workspace
    )
    allowed = {run.id for run in readable}
    visible_invocations = {
        inv.id
        for inv in readable_skill_invocations_for_runs(
            db, invocations=[row[0] for row in rows], runs=readable, user=user, workspace=workspace
        )
    }
    result = []
    for invocation, run, system in rows:
        if run.id not in allowed or invocation.id not in visible_invocations:
            continue
        # Comparisons are observations, not new business cases to sample again.
        execution = (run.input_ref or {}).get("execution")
        if isinstance(execution, dict) and execution.get("decision_comparison"):
            continue
        try:
            result.append(public_sample(invocation, run, system, decision_input(invocation)))
        except (HTTPException, flow_workbench.FlowWorkbenchError):
            continue
        if len(result) == 30:
            break
    return result


def create_comparison(db, *, workspace, user, body, authorize):
    invocation, source_run, system, inputs = sample(
        db, invocation_id=body.invocation_id, workspace=workspace, user=user
    )
    authorize(db, system_id=system.id, workspace=workspace, user=user)
    input_digest = canonical_sha256(inputs)
    if input_digest != body.expected_input_sha256:
        raise HTTPException(
            409,
            detail={
                "code": "DECISION_SAMPLE_CHANGED",
                "message": "Reload the retained decision before comparing.",
            },
        )
    request_digest = canonical_sha256(body.model_dump(mode="json"))
    # Serialize retries without holding a workspace lock across audit writes.
    system = (
        db.query(System)
        .filter_by(id=system.id, workspace_id=workspace.id)
        .populate_existing()
        .with_for_update(key_share=True)
        .one()
    )
    authorize(db, system_id=system.id, workspace=workspace, user=user)
    previous = (
        db.query(Run)
        .filter(
            Run.workspace_id == workspace.id,
            Run.system_id == system.id,
            Run.initiated_by_user_id == user.id,
            Run.input_ref["execution"]["decision_comparison"]["request_key"].as_string()
            == str(body.request_key),
        )
        .all()
    )
    if previous:
        if any(
            (run.input_ref["execution"]["decision_comparison"]).get("request_sha256")
            != request_digest
            for run in previous
        ):
            raise HTTPException(
                409,
                detail={
                    "code": "DECISION_COMPARISON_REQUEST_CONFLICT",
                    "message": "This request key belongs to another comparison.",
                },
            )
        db.commit()
        return sorted(
            previous,
            key=lambda run: run.input_ref["execution"]["decision_comparison"]["candidate_index"],
        )
    batch_id = str(uuid4())
    # An unpublished, more permissive mandate must not change which providers
    # may receive retained observations. Use the effective published mandate.
    try:
        policy = flow_publication.resolved_control_policy_snapshot(
            db, system=system, use_draft=False
        )
    except flow_publication.FlowPublicationError as exc:
        raise flow_workbench._translate_publication(exc) from exc
    runs = []
    for index, candidate in enumerate(body.candidates):
        qualified = f"{candidate.provider}:{candidate.model}"
        candidate_input = {**copy.deepcopy(inputs), "model": qualified}
        node_id = "decision.compare"
        flow = {
            "schema_version": 3,
            "source": "flow",
            "extended": True,
            "nodes": [
                {
                    "id": node_id,
                    "kind": "task",
                    "type": "skill",
                    "label": "Compare retained decision",
                    "config": {
                        "skill_slug": DECISION_SKILL,
                        "params": {"model": qualified},
                        "on_error": "fail",
                    },
                }
            ],
            "edges": [],
        }
        prepared = flow_workbench.prepare_node_preview(
            db,
            system_id=system.id,
            workspace=workspace,
            flow_definition=flow,
            expected_flow_sha256=canonical_flow_sha256(flow),
            node_id=node_id,
            input_ref=candidate_input,
            control_policy_snapshot=policy,
        )
        metadata = {
            "batch_id": batch_id,
            "request_key": str(body.request_key),
            "request_sha256": request_digest,
            "candidate_index": index,
            "provider": candidate.provider,
            "model": candidate.model,
            "source_run_id": source_run.id,
            "source_invocation_id": invocation.id,
            "input_sha256": input_digest,
            "instruction_sha256": canonical_sha256(inputs["goal"]),
            "generation_only": True,
            "quality_qualified": False,
        }
        run = flow_workbench.create_run(
            db,
            prepared=prepared,
            workspace=workspace,
            user_id=user.id,
            surface="node_preview",
            input_ref=candidate_input,
            metadata={
                "decision_comparison": metadata,
                "initial_dispatch_plane": "celery",
                "real_side_effects_acknowledged": True,
            },
        )
        run.trigger_dedup_key = f"decision-comparison:{batch_id}:{index}"
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
    return runs
