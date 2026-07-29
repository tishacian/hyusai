"""Shared legacy visibility and granular read authorization for Runs.

Run payloads are exposed by several canonical surfaces (Run detail/list/SSE,
System run lists and the object projectors).  Keeping the private-chat and
migration-managed HITL boundary here prevents a projection from becoming an
authorization bypass while ``run.read`` rolls out independently.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from app.core.iam.roles import WORKSPACE_REVIEWER, is_admin_template, normalize_role_template
from app.models.decision import Decision
from app.models.run import Run, SkillInvocation
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.chat_execution_policy import migration_059_system_id
from app.services.iam.decision_plane import (
    ActionResolution,
    emit_shadow_diff_summary,
    resolve_action,
)

PRIVATE_CHAT_TRIGGER = "chat_agentic"


def has_private_chat_admin_access(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
) -> bool:
    if getattr(user, "role", None) == "admin":
        return True
    membership = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.workspace_id == workspace.id,
        )
        .first()
    )
    return bool(
        membership
        and is_admin_template(membership.role_template, membership.role)
    )


def can_view_private_chat_runs(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
) -> bool:
    """Reviewers and workspace/org admins may inspect all Agentic chat Runs."""

    if has_private_chat_admin_access(db, user=user, workspace=workspace):
        return True
    membership = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.workspace_id == workspace.id,
        )
        .first()
    )
    return bool(
        membership
        and normalize_role_template(membership.role_template, membership.role)
        == WORKSPACE_REVIEWER
    )


def managed_agentic_run_requires_admin(
    db: DBSession,
    *,
    run: Run,
    workspace: Workspace,
) -> bool:
    """Return whether migration-059 keeps this Run admin-only."""

    managed_system_id = migration_059_system_id(workspace)
    if managed_system_id is None:
        return False
    managed = run.system_id == managed_system_id

    # A parent subflow can surface a Decision owned by a managed child Run.
    # Preserve the same boundary for that parent without trusting checkpoint
    # payload beyond the server-persisted Decision -> Run relationship.
    if not managed:
        decision_ids = [
            checkpoint.get("decision_id")
            for checkpoint in list(run.checkpoints or [])
            if isinstance(checkpoint, dict)
            and checkpoint.get("kind") == "hitl_pause"
        ]
        decision_ids = [decision_id for decision_id in decision_ids if decision_id]
        if decision_ids:
            managed = (
                db.query(Run.id)
                .join(Decision, Decision.target_id == Run.id)
                .filter(
                    Decision.id.in_(decision_ids),
                    Decision.scope == "run",
                    or_(
                        Decision.workspace_id == workspace.id,
                        Decision.workspace_id.is_(None),
                    ),
                    Run.workspace_id == workspace.id,
                    Run.system_id == managed_system_id,
                )
                .first()
                is not None
            )
    if not managed:
        return False
    if run.status not in {"completed", "failed", "cancelled"}:
        return True

    output = run.output_ref if isinstance(run.output_ref, dict) else {}
    if str(output.get("hitl_decision") or "").strip().lower() == "rejected":
        return True
    return any(
        isinstance(checkpoint, dict)
        and checkpoint.get("kind") == "hitl_resume"
        and str(checkpoint.get("decision_status") or "").strip().lower()
        == "rejected"
        for checkpoint in list(run.checkpoints or [])
    )


def run_is_visible(
    db: DBSession,
    *,
    run: Run,
    user: User,
    workspace: Workspace,
    allow_managed_hitl_for_resolution: bool = False,
) -> bool:
    """Apply the complete pre-v2 Run visibility boundary."""

    requires_admin = managed_agentic_run_requires_admin(
        db,
        run=run,
        workspace=workspace,
    )
    resolution_may_authorize = (
        allow_managed_hitl_for_resolution and run.status == "hitl_pending"
    )
    if requires_admin and not resolution_may_authorize:
        return has_private_chat_admin_access(
            db,
            user=user,
            workspace=workspace,
        )
    if run.trigger != PRIVATE_CHAT_TRIGGER:
        return True
    if run.initiated_by_user_id == user.id:
        return True
    return can_view_private_chat_runs(db, user=user, workspace=workspace)


def run_read_attrs(run: Run) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "system_id": run.system_id,
        "capability_id": run.capability_id,
        "owner_user_id": run.initiated_by_user_id,
    }


def resolve_run_read(
    db: DBSession,
    *,
    run: Run,
    user: User,
    workspace: Workspace,
    legacy_allowed: bool = True,
    audit_shadow_diff: bool = True,
    audit_shadow_evidence: bool = True,
) -> ActionResolution:
    return resolve_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="run",
        action="read",
        legacy_allowed=legacy_allowed,
        resource_attrs=run_read_attrs(run),
        audit_shadow_diff=audit_shadow_diff,
        audit_shadow_evidence=audit_shadow_evidence,
    )


def readable_runs(
    db: DBSession,
    *,
    runs: list[Run],
    user: User,
    workspace: Workspace,
) -> list[Run]:
    """Filter a collection through legacy visibility then granular read."""

    visible: list[Run] = []
    resolutions: list[tuple[str, ActionResolution]] = []
    for run in runs:
        if not run_is_visible(db, run=run, user=user, workspace=workspace):
            continue
        resolution = resolve_run_read(
            db,
            run=run,
            user=user,
            workspace=workspace,
            audit_shadow_diff=False,
            audit_shadow_evidence=False,
        )
        resolutions.append((run.id, resolution))
        if resolution.effective_allowed:
            visible.append(run)
    emit_shadow_diff_summary(
        workspace=workspace,
        user=user,
        resource_kind="run",
        action="read",
        resolutions=resolutions,
    )
    return visible


def readable_run_page(
    db: DBSession,
    *,
    query: Any,
    limit: int,
    user: User,
    workspace: Workspace,
) -> list[Run]:
    """Fill a page after authorization without letting hidden rows consume it.

    The caller supplies its fully scoped and ordered query.  Iterating in
    bounded batches preserves that order while ensuring recent denied Runs do
    not hide an older authorized Run behind a pre-authorization SQL LIMIT.
    """

    target = max(0, int(limit))
    if target == 0:
        return []
    batch_size = min(500, max(50, target * 2))
    page: list[Run] = []
    batch: list[Run] = []
    for run in query.execution_options(stream_results=True).yield_per(batch_size):
        batch.append(run)
        if len(batch) < batch_size:
            continue
        page.extend(
            readable_runs(
                db,
                runs=batch,
                user=user,
                workspace=workspace,
            )
        )
        if len(page) >= target:
            return page[:target]
        batch = []
    if batch:
        page.extend(
            readable_runs(
                db,
                runs=batch,
                user=user,
                workspace=workspace,
            )
        )
    return page[:target]


def skill_invocation_read_attrs(
    invocation: SkillInvocation,
    run: Run,
) -> dict[str, Any]:
    return {
        "skill_invocation_id": invocation.id,
        "run_id": run.id,
        "system_id": run.system_id,
        "capability_id": run.capability_id,
        "owner_user_id": run.initiated_by_user_id,
    }


def resolve_skill_invocation_read(
    db: DBSession,
    *,
    invocation: SkillInvocation,
    run: Run,
    user: User,
    workspace: Workspace,
    legacy_allowed: bool = True,
    audit_shadow_diff: bool = True,
    audit_shadow_evidence: bool = True,
) -> ActionResolution:
    return resolve_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="skill_invocation",
        action="read",
        legacy_allowed=legacy_allowed,
        resource_attrs=skill_invocation_read_attrs(invocation, run),
        audit_shadow_diff=audit_shadow_diff,
        audit_shadow_evidence=audit_shadow_evidence,
    )


def readable_skill_invocations(
    db: DBSession,
    *,
    invocations: list[SkillInvocation],
    run: Run,
    user: User,
    workspace: Workspace,
) -> list[SkillInvocation]:
    """Keep invocation rollout independent from the parent ``run.read``."""

    visible: list[SkillInvocation] = []
    resolutions: list[tuple[str, ActionResolution]] = []
    for invocation in invocations:
        resolution = resolve_skill_invocation_read(
            db,
            invocation=invocation,
            run=run,
            user=user,
            workspace=workspace,
            audit_shadow_diff=False,
            audit_shadow_evidence=False,
        )
        resolutions.append((invocation.id, resolution))
        if resolution.effective_allowed:
            visible.append(invocation)
    emit_shadow_diff_summary(
        workspace=workspace,
        user=user,
        resource_kind="skill_invocation",
        action="read",
        resolutions=resolutions,
    )
    return visible


def readable_skill_invocations_for_runs(
    db: DBSession,
    *,
    invocations: list[SkillInvocation],
    runs: list[Run],
    user: User,
    workspace: Workspace,
) -> list[SkillInvocation]:
    """Filter a multi-Run ledger with one aggregate shadow event at most."""

    runs_by_id = {run.id: run for run in runs}
    visible: list[SkillInvocation] = []
    resolutions: list[tuple[str, ActionResolution]] = []
    for invocation in invocations:
        run = runs_by_id.get(invocation.run_id)
        if run is None:
            continue
        resolution = resolve_skill_invocation_read(
            db,
            invocation=invocation,
            run=run,
            user=user,
            workspace=workspace,
            audit_shadow_diff=False,
            audit_shadow_evidence=False,
        )
        resolutions.append((invocation.id, resolution))
        if resolution.effective_allowed:
            visible.append(invocation)
    emit_shadow_diff_summary(
        workspace=workspace,
        user=user,
        resource_kind="skill_invocation",
        action="read",
        resolutions=resolutions,
    )
    return visible
