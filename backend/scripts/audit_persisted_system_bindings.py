#!/usr/bin/env python3
"""Read-only audit of the runtime catalogue authority of persisted Systems."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import func

from app.db.base import SessionLocal
from app.models.capability import Capability
from app.models.context import Context
from app.models.expert_capture import (
    ExpertCaptureEvent,
    ExpertCaptureSession,
    KnowledgeUpdateProposal,
)
from app.models.policy import AdaptivePolicy
from app.models.run import Run
from app.models.skill import Skill
from app.models.system import System
from app.models.workspace import Workspace
from app.services.catalog_visibility import workspace_catalog_policy


class _BindingAuditError(ValueError):
    """Content-free failure raised by the Release A standalone auditor."""

    def __init__(self, *, code: str, field: str) -> None:
        super().__init__(code)
        self.code = code
        self.field = field


def _is_disabled(*, row_id: str | None, slug: str | None, values: set[str]) -> bool:
    keys = {
        str(value).strip().lower()
        for value in (row_id, slug)
        if value is not None and str(value).strip()
    }
    return bool(keys & values)


def _audit_system_bindings(db, *, workspace: Workspace, system: System) -> tuple[int, bool]:
    """Validate persisted runtime bindings without depending on Release B code."""

    policy = workspace_catalog_policy(workspace)
    capability = None
    if system.capability_id:
        capability = (
            db.query(Capability)
            .filter(Capability.id == system.capability_id)
            .first()
        )
        if (
            capability is None
            or capability.workspace_id not in {None, workspace.id}
            or _is_disabled(
                row_id=getattr(capability, "id", None),
                slug=getattr(capability, "slug", None),
                values=policy.hidden_capabilities,
            )
        ):
            raise _BindingAuditError(
                code="capability_not_visible",
                field="capability_id",
            )

    explicit_skill_ids = tuple(str(value) for value in system.skill_ids or ())
    effective_skill_ids = explicit_skill_ids or tuple(
        str(value) for value in (capability.skill_ids if capability is not None else ())
    )
    if effective_skill_ids:
        skills = db.query(Skill).filter(Skill.id.in_(effective_skill_ids)).all()
        skills_by_id = {str(skill.id): skill for skill in skills}
        for skill_id in effective_skill_ids:
            skill = skills_by_id.get(skill_id)
            if (
                skill is None
                or skill.workspace_id not in {None, workspace.id}
                or _is_disabled(
                    row_id=getattr(skill, "id", None),
                    slug=getattr(skill, "slug", None),
                    values=policy.hidden_skills,
                )
            ):
                raise _BindingAuditError(
                    code="skill_not_visible",
                    field="skill_ids",
                )

    adaptive_policy = None
    if system.adaptive_policy_id:
        adaptive_policy = (
            db.query(AdaptivePolicy)
            .filter(
                AdaptivePolicy.id == system.adaptive_policy_id,
                AdaptivePolicy.workspace_id == workspace.id,
            )
            .first()
        )
        if adaptive_policy is None:
            raise _BindingAuditError(
                code="adaptive_policy_workspace_mismatch",
                field="adaptive_policy_id",
            )
        scope = str(adaptive_policy.scope or "").strip().lower()
        target_id = (
            str(adaptive_policy.target_id)
            if adaptive_policy.target_id is not None
            else None
        )
        scope_matches = (
            scope == ""
            or (scope == "system" and target_id == system.id)
            or (
                scope == "capability"
                and bool(system.capability_id)
                and target_id == system.capability_id
            )
            or (scope == "portfolio" and target_id in {None, workspace.id})
        )
        if not scope_matches:
            raise _BindingAuditError(
                code="adaptive_policy_scope_mismatch",
                field="adaptive_policy_id",
            )

    return len(effective_skill_ids), adaptive_policy is not None


def audit_persisted_system_bindings(
    db,
    *,
    workspace_slugs: Sequence[str] | None = None,
    include_inactive: bool = False,
) -> dict[str, Any]:
    requested = {
        slug.strip().lower() for slug in workspace_slugs or () if slug.strip()
    }
    workspaces_query = db.query(Workspace)
    if requested:
        workspaces_query = workspaces_query.filter(Workspace.slug.in_(requested))
    workspaces = workspaces_query.order_by(Workspace.slug.asc()).all()
    observed_slugs = {str(workspace.slug).lower() for workspace in workspaces}
    missing = sorted(requested - observed_slugs)
    mismatch_query = (
        db.query(ExpertCaptureSession, System)
        .join(System, ExpertCaptureSession.system_id == System.id)
        .filter(ExpertCaptureSession.workspace_id != System.workspace_id)
    )
    expert_capture_system_workspace_mismatch_count = int(mismatch_query.count())
    mismatch_detail_limit = 100
    expert_capture_system_workspace_mismatches: list[dict[str, Any]] = []
    for session, system in (
        mismatch_query.order_by(ExpertCaptureSession.id.asc())
        .limit(mismatch_detail_limit)
        .all()
    ):
        capability = (
            db.query(Capability)
            .filter(Capability.id == session.capability_id)
            .first()
            if session.capability_id
            else None
        )
        context = (
            db.query(Context).filter(Context.id == session.context_id).first()
            if session.context_id
            else None
        )
        run = (
            db.query(Run).filter(Run.id == session.run_id).first()
            if session.run_id
            else None
        )

        def workspace_relation(reference_id: str | None, row: Any) -> str:
            if not reference_id:
                return "not_bound"
            if row is None:
                return "missing"
            return (
                "same_workspace"
                if row.workspace_id == session.workspace_id
                else "different_workspace"
            )

        if run is None:
            run_system_relation = "not_bound" if not session.run_id else "missing_run"
        elif not run.system_id:
            run_system_relation = "run_not_system_bound"
        elif run.system_id == session.system_id:
            run_system_relation = "same_system"
        else:
            run_system_relation = "different_system"

        expert_capture_system_workspace_mismatches.append(
            {
                "session_id": session.id,
                "session_workspace_id": session.workspace_id,
                "system_id": system.id,
                "system_workspace_id": system.workspace_id,
                "status": session.status,
                "run_workspace_relation": workspace_relation(session.run_id, run),
                "run_system_relation": run_system_relation,
                "capability_workspace_relation": workspace_relation(
                    session.capability_id,
                    capability,
                ),
                "context_workspace_relation": workspace_relation(
                    session.context_id,
                    context,
                ),
                "event_count": int(
                    db.query(func.count(ExpertCaptureEvent.id))
                    .filter(ExpertCaptureEvent.session_id == session.id)
                    .scalar()
                    or 0
                ),
                "proposal_count": int(
                    db.query(func.count(KnowledgeUpdateProposal.id))
                    .filter(KnowledgeUpdateProposal.session_id == session.id)
                    .scalar()
                    or 0
                ),
            }
        )

    rows: list[dict[str, Any]] = []
    failed = 0
    for workspace in workspaces:
        systems_query = db.query(System).filter(System.workspace_id == workspace.id)
        if not include_inactive:
            systems_query = systems_query.filter(System.status == "active")
        for system in systems_query.order_by(System.id.asc()).all():
            row: dict[str, Any] = {
                "workspace_id": workspace.id,
                "workspace_slug": workspace.slug,
                "system_id": system.id,
                "status": system.status,
                "capability_id": system.capability_id,
            }
            try:
                effective_skill_count, adaptive_policy_bound = _audit_system_bindings(
                    db,
                    workspace=workspace,
                    system=system,
                )
            except _BindingAuditError as exc:
                failed += 1
                row.update(
                    {
                        "result": "failed",
                        "code": exc.code,
                        "field": exc.field,
                    }
                )
            else:
                row.update(
                    {
                        "result": "passed",
                        "effective_skill_count": effective_skill_count,
                        "adaptive_policy_bound": adaptive_policy_bound,
                    }
                )
            rows.append(row)

    return {
        "schema_version": 2,
        "kind": "persisted_system_catalog_runtime_audit",
        "result": (
            "passed"
            if not failed
            and not missing
            and expert_capture_system_workspace_mismatch_count == 0
            else "failed"
        ),
        "requested_workspace_slugs": sorted(requested),
        "missing_workspace_slugs": missing,
        "workspace_count": len(workspaces),
        "system_count": len(rows),
        "failed_system_count": failed,
        "expert_capture_system_workspace_mismatch_count": (
            expert_capture_system_workspace_mismatch_count
        ),
        "expert_capture_system_workspace_mismatch_detail_limit": (
            mismatch_detail_limit
        ),
        "expert_capture_system_workspace_mismatch_details_truncated": (
            expert_capture_system_workspace_mismatch_count
            > len(expert_capture_system_workspace_mismatches)
        ),
        "expert_capture_system_workspace_mismatches": (
            expert_capture_system_workspace_mismatches
        ),
        "systems": rows,
    }


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", action="append", dest="workspaces")
    parser.add_argument("--include-inactive", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    with SessionLocal() as db:
        report = audit_persisted_system_bindings(
            db,
            workspace_slugs=args.workspaces,
            include_inactive=args.include_inactive,
        )
        db.rollback()
    if args.output:
        _write_atomic(args.output, report)
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
