"""Read existing references only; no implicit submit, retry or publication."""

from .contracts import ExecutionScope, NativeReference, NativeState


def observe_native(db, scope: ExecutionScope, reference: NativeReference) -> NativeState:
    from app.models.compute_run import ComputeRun
    from app.models.recipe import RecipeExecution
    from app.models.run import Run
    from app.models.tabular import MLModel
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.services.activity_observability.queries import require_membership
    from app.services.huggingface.access import is_workspace_admin
    from app.services.run_access import readable_runs

    if (
        not isinstance(scope.flow_digest, str)
        or len(scope.flow_digest) != 64
        or any(character not in "0123456789abcdef" for character in scope.flow_digest)
        or not isinstance(scope.version_id, str)
        or not scope.version_id
    ):
        raise ValueError("NATIVE_FROZEN_CONTRACT_REQUIRED")
    if (reference.workspace_id, reference.run_id) != (scope.workspace_id, scope.run_id):
        raise ValueError("NATIVE_REFERENCE_SCOPE_MISMATCH")
    workspace = db.get(Workspace, scope.workspace_id, populate_existing=True)
    user = db.get(User, scope.actor_id, populate_existing=True)
    require_membership(db, workspace, user)
    parent = (
        db.query(Run)
        .filter_by(id=scope.run_id, workspace_id=scope.workspace_id)
        .populate_existing()
        .first()
    )
    if not parent or not readable_runs(db, runs=[parent], user=user, workspace=workspace):
        raise ValueError("NATIVE_REFERENCE_UNAUTHORIZED")
    if (
        parent.flow_sha256 != scope.flow_digest
        or parent.published_flow_version_id != scope.version_id
    ):
        raise ValueError("NATIVE_CONTRACT_MISMATCH")
    model = {
        "run": Run,
        "recipe_execution": RecipeExecution,
        "compute_run": ComputeRun,
        "ml_training": MLModel,
    }.get(reference.kind)
    if model is None:
        raise ValueError("NATIVE_REFERENCE_KIND_UNSUPPORTED")
    row = (
        db.query(model)
        .filter_by(id=reference.id, workspace_id=scope.workspace_id)
        .populate_existing()
        .first()
    )
    if not row:
        raise ValueError("NATIVE_REFERENCE_NOT_FOUND")
    if reference.kind == "run":
        if row.id != parent.id and not (row.parent_run_id == parent.id and row.delegation_key):
            raise ValueError("NATIVE_REFERENCE_PARENT_MISMATCH")
        if not readable_runs(db, runs=[row], user=user, workspace=workspace):
            raise ValueError("NATIVE_REFERENCE_UNAUTHORIZED")
    elif row.run_id != parent.id:
        raise ValueError("NATIVE_REFERENCE_PARENT_MISMATCH")
    if (
        reference.kind == "compute_run"
        and row.user_id != user.id
        and not is_workspace_admin(db, user, workspace)
    ):
        raise ValueError("NATIVE_REFERENCE_UNAUTHORIZED")
    states = {
        "pending": "pending",
        "queued": "pending",
        "created": "pending",
        "running": "running",
        "training": "running",
        "env_building": "running",
        "admitted": "running",
        "launching": "running",
        "committing": "running",
        "waiting_subflows": "waiting",
        "hitl_pending": "waiting",
        "debug_pending": "waiting",
        "completed": "succeeded",
        "ready": "succeeded",
        "succeeded": "succeeded",
        "failed": "failed",
        "cancelled": "cancelled",
        "timed_out": "timed_out",
        "lost": "lost",
    }
    if row.status not in states:
        raise ValueError("NATIVE_STATUS_UNSUPPORTED")
    return NativeState(status=states[row.status], reference=reference)
