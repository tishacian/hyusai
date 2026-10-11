"""Evidence-backed proposals with explicit, atomic application to a draft only."""
from copy import deepcopy
from datetime import datetime
import difflib

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

class CorrectionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(min_length=1, max_length=36)
    node_id: str = Field(min_length=1, max_length=160)
    evaluation_id: str = Field(min_length=1, max_length=36)
    expected_draft_revision: int = Field(ge=1)
    replacement_template: str = Field(min_length=1, max_length=8000)
    rationale: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=100)


from app.models.evaluation import EvaluationScore
from app.models.evaluation_correction import EvaluationCorrection
from app.models.run import Run
from app.models.skill import Skill
from app.models.system import System
from app.models.system_flow_draft import SystemFlowDraft
from app.services.chat_execution_policy import migration_059_system_id
from app.services.flow_contracts import canonical_sha256
from app.services.flow_node_overrides import override_executor
from app.services.iam.decision_plane import enforce_action
from app.services.iam.legacy_authority import legacy_object_action_allowed
from app.services.run_access import run_is_visible, run_read_attrs, has_private_chat_admin_access
from app.services.systems import flow_publication


def authorize(db, *, user, workspace, run_id, write=False):
    run = db.query(Run).filter_by(id=run_id, workspace_id=workspace.id).one_or_none()
    if run is None or not run_is_visible(db, run=run, user=user, workspace=workspace):
        raise HTTPException(404, "Run not found")
    enforce_action(db, user=user, workspace=workspace, resource_kind="run", action="read", legacy_allowed=True, resource_attrs=run_read_attrs(run))
    system = db.query(System).filter_by(id=run.system_id, workspace_id=workspace.id).one_or_none()
    if system is None:
        raise HTTPException(422, "The Run has no editable System")
    managed = migration_059_system_id(workspace) == system.id
    if write and managed and not has_private_chat_admin_access(db, user=user, workspace=workspace):
        raise HTTPException(403, "Admin access required for the managed System")
    action = "admin" if write else "read"
    enforce_action(db, user=user, workspace=workspace, resource_kind="system", action=action,
        legacy_allowed=legacy_object_action_allowed(db, user=user, workspace=workspace, resource_kind="system", action=action, resource_attrs={"managed_system": managed}),
        resource_attrs={"system_id": system.id, "capability_id": system.capability_id, "mutation": "flow_draft_save"} if write else {"system_id": system.id})
    return run, system


def correction_context(db, *, user, workspace, run_id, node_id, evaluation_id):
    run, system = authorize(db, user=user, workspace=workspace, run_id=run_id, write=True)
    evaluation = db.query(EvaluationScore).filter_by(id=evaluation_id, run_id=run.id, workspace_id=workspace.id).one_or_none()
    if evaluation is None:
        raise HTTPException(404, "Evaluation not found for this Run")
    draft = db.query(SystemFlowDraft).filter_by(system_id=system.id, workspace_id=workspace.id).one_or_none()
    if draft is None:
        raise HTTPException(409, "Open a server draft before proposing a correction")
    executed = ((run.execution_contract or {}).get("nodes") or {}).get(node_id)
    if not executed or not executed.get("executor"):
        raise HTTPException(422, "This historical or seeded executor cannot receive a template correction")
    contract = flow_publication.compile_execution_contract(db, draft.flow_definition, workspace, system=system)
    current = contract.get("nodes", {}).get(node_id)
    if not current or (current.get("executor") or {}).get("kind") != "prompt_template":
        raise HTTPException(422, "This node does not support a prompt template correction")
    # A changed catalog/draft must be run and evaluated before diagnosing it.
    if current != executed:
        raise HTTPException(409, "The draft node differs from the executed node; test the draft first")
    return run, system, draft, current, evaluation


def context_payload(db, **kwargs):
    run, system, draft, node, evaluation = correction_context(db, **kwargs)
    from app.services.evaluation.lifecycle import public_evaluation_snapshot
    public = public_evaluation_snapshot(db, {"metadata": deepcopy(evaluation.metadata_ or {})},
        user=kwargs["user"], workspace=kwargs["workspace"], run=run)["metadata"]
    return {
        "examined_response": public.get("response_examined"),
        "examined_excerpts": public.get("excerpts", []),
        "coverage": {"response_truncated": public.get("response_truncated"), "context_truncated": public.get("context_truncated")},
        "run_id": run.id, "system_id": system.id, "node_id": kwargs["node_id"],
        "evaluation_id": evaluation.id, "expected_draft_revision": draft.revision,
        "base_flow_sha256": draft.flow_sha256, "executor_sha256": canonical_sha256(node["executor"]),
        "template": node["executor"]["params"]["template"],
        "input_schema": node["input_schema"], "output_schema": node["output_schema"],
        "claim_audit": deepcopy(evaluation.claim_audit or {}),
        "scores": deepcopy(evaluation.scores or {}),
        "method": (evaluation.metadata_ or {}).get("method"),
        "next_action": "Propose a template preserving all placeholders. The author must review its diff before applying it to this draft.",
    }


def serialize(row):
    return {"id": row.id, "status": row.status, "proposal_sha256": row.proposal_sha256,
            "proposal": deepcopy(row.proposal), "applied_revision": row.applied_revision,
            "created_at": row.created_at.isoformat() if row.created_at else None}


def create_proposal(db, *, user, workspace, run_id, node_id, evaluation_id,
                    expected_draft_revision, replacement_template, rationale, idempotency_key):
    try:
        CorrectionBody(run_id=run_id, node_id=node_id, evaluation_id=evaluation_id,
            expected_draft_revision=expected_draft_revision, replacement_template=replacement_template,
            rationale=rationale, idempotency_key=idempotency_key)
    except ValidationError as exc:
        raise HTTPException(422, "Invalid correction fields") from exc
    request = {"run_id": run_id, "node_id": node_id, "evaluation_id": evaluation_id,
               "expected_draft_revision": expected_draft_revision,
               "replacement_template": replacement_template, "rationale": rationale}
    digest = canonical_sha256(request)
    authorize(db, user=user, workspace=workspace, run_id=run_id, write=True)
    previous = db.query(EvaluationCorrection).filter_by(workspace_id=workspace.id, created_by_user_id=user.id, idempotency_key=idempotency_key).one_or_none()
    if previous:
        if previous.request_sha256 != digest:
            raise HTTPException(409, "Idempotency key already used for another proposal")
        return previous
    run, system, draft, node, evaluation = correction_context(db, user=user, workspace=workspace, run_id=run_id, node_id=node_id, evaluation_id=evaluation_id)
    if draft.revision != expected_draft_revision:
        raise HTTPException(409, "The draft changed; reload before proposing a correction")
    try:
        replacement = override_executor(node["executor"], {"prompt_template_override": replacement_template})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    original = node["executor"]["params"]["template"]
    if replacement_template == original:
        raise HTTPException(422, "The proposal does not change the template")
    proposal = {**request, "system_id": system.id, "base_flow_sha256": draft.flow_sha256,
        "executed_node_sha256": canonical_sha256(node), "executor_sha256": canonical_sha256(node["executor"]),
        "replacement_executor_sha256": canonical_sha256(replacement),
        "original_template": original,
        "diff": "\n".join(difflib.unified_diff(original.splitlines(), replacement_template.splitlines(), fromfile="reference", tofile="draft", lineterm="")),
        "evidence": {"run_id": run.id, "evaluation_id": evaluation.id, "claim_audit_sha256": canonical_sha256(evaluation.claim_audit or {})},
        "scope": "draft_node_only", "requires_explicit_review": True}
    row = EvaluationCorrection(workspace_id=workspace.id, system_id=system.id, run_id=run.id,
        created_by_user_id=user.id, idempotency_key=idempotency_key, request_sha256=digest,
        proposal_sha256=canonical_sha256(proposal), proposal=proposal)
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        previous = db.query(EvaluationCorrection).filter_by(workspace_id=workspace.id, created_by_user_id=user.id, idempotency_key=idempotency_key).one()
        if previous.request_sha256 != digest:
            raise HTTPException(409, "Idempotency key already used for another proposal")
        return previous
    return row


def list_proposals(db, *, user, workspace, run_id):
    run, system = authorize(db, user=user, workspace=workspace, run_id=run_id, write=True)
    return db.query(EvaluationCorrection).filter_by(
        workspace_id=workspace.id, system_id=system.id, run_id=run.id,
    ).order_by(EvaluationCorrection.created_at.desc(), EvaluationCorrection.id.desc()).limit(100).all()


def get_proposal(db, *, user, workspace, proposal_id, lock=False):
    query = db.query(EvaluationCorrection).filter_by(id=proposal_id, workspace_id=workspace.id)
    row = (query.with_for_update() if lock else query).one_or_none()
    if row is None:
        raise HTTPException(404, "Correction not found")
    authorize(db, user=user, workspace=workspace, run_id=row.run_id, write=True)
    return row


def apply_proposal(db, *, user, workspace, proposal_id, expected_draft_revision, reviewed_proposal_sha256):
    row = get_proposal(db, user=user, workspace=workspace, proposal_id=proposal_id, lock=True)
    if row.proposal_sha256 != reviewed_proposal_sha256:
        raise HTTPException(409, "Review the current proposal before applying it")
    if expected_draft_revision != row.proposal["expected_draft_revision"]:
        raise HTTPException(409, "The reviewed draft revision does not match")
    if row.status == "applied":
        return row
    p = row.proposal
    # Use publication's lock ordering and refresh identity-map state before CAS.
    system = flow_publication._lock_system(db, system_id=row.system_id, workspace_id=workspace.id)
    flow_publication._locked_draft(db, system)
    run_node = ((db.get(Run, row.run_id).execution_contract or {}).get("nodes") or {}).get(p["node_id"], {})
    db.query(Skill).filter(Skill.id == run_node.get("skill_id")).populate_existing().with_for_update().one_or_none()
    run, system, draft, node, evaluation = correction_context(db, user=user, workspace=workspace,
        run_id=row.run_id, node_id=p["node_id"], evaluation_id=p["evaluation_id"])
    if draft.revision != expected_draft_revision or draft.flow_sha256 != p["base_flow_sha256"] or canonical_sha256(node) != p["executed_node_sha256"]:
        raise HTTPException(409, "The draft or executor changed; prepare and review a new proposal")
    flow = deepcopy(draft.flow_definition)
    target = next(n for n in flow["nodes"] if n.get("id") == p["node_id"])
    target.setdefault("config", {})["prompt_template_override"] = p["replacement_template"]
    flow_publication.compile_execution_contract(db, flow, workspace, system=system)
    draft, _ = flow_publication.save_draft(db, system_id=system.id, workspace=workspace,
        flow_definition=flow, expected_revision=expected_draft_revision, actor=user.id)
    row.status = "applied"
    row.applied_revision = draft.revision
    row.applied_by_user_id = user.id
    row.applied_at = datetime.utcnow()
    db.flush()
    return row
