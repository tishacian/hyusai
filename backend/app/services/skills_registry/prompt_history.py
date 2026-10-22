"""Instructions retained by immutable published Flow versions.

This deliberately is not an invented history of intermediate catalog edits.
Restoring a template edits the catalog; published contracts remain untouched.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import timezone

from fastapi import HTTPException

from app.models.system import System
from app.models.system_version import SystemVersion
from app.services.audit_logger import emit_audit_event
from app.services.flow_contracts import canonical_sha256
from app.services.skills_registry.executors import _render_template, validate_executor_binding


def template_of(executor):
    if not isinstance(executor, Mapping) or executor.get("kind") != "prompt_template":
        return None
    params = executor.get("params")
    template = params.get("template") if isinstance(params, Mapping) else None
    return template if isinstance(template, str) else None


def require_template(skill):
    template = template_of(skill.executor)
    if template is None:
        raise HTTPException(
            409,
            detail={
                "code": "PROMPT_HISTORY_UNAVAILABLE",
                "message": "This Skill does not use editable prompt instructions.",
            },
        )
    return template


def contract_entries(version, slug):
    contract = version.execution_contract
    nodes = contract.get("nodes") if isinstance(contract, Mapping) else None
    if not isinstance(nodes, Mapping):
        return
    for node_id, node in nodes.items():
        if not isinstance(node, Mapping):
            continue
        candidates = [node] if node.get("skill_slug") == slug else []
        tools = node.get("tool_contract")
        tool_nodes = tools.get("nodes") if isinstance(tools, Mapping) else None
        if isinstance(tool_nodes, Mapping) and isinstance(tool_nodes.get(slug), Mapping):
            candidates.append(tool_nodes[slug])
        for candidate in candidates:
            template = template_of(candidate.get("executor"))
            if template is not None:
                yield str(node_id), template, candidate["executor"]


def entries(db, *, workspace, user, skill, authorize_read):
    current = require_template(skill)
    rows = (
        db.query(SystemVersion, System)
        .join(System, System.id == SystemVersion.system_id)
        .filter(
            SystemVersion.workspace_id == workspace.id,
            System.workspace_id == workspace.id,
            SystemVersion.release_kind.in_(["publish", "rollback", "migration"]),
        )
        .order_by(SystemVersion.created_at.desc(), SystemVersion.id)
        .limit(500)
        .all()
    )
    permissions = {}
    result = []
    for version, system in rows:
        if system.id not in permissions:
            try:
                authorize_read(db, user=user, workspace=workspace, system=system)
                permissions[system.id] = True
            except HTTPException as exc:
                if exc.status_code not in (403, 404):
                    raise
                permissions[system.id] = False
        if not permissions[system.id]:
            continue
        for node_id, template, executor in contract_entries(version, skill.slug):
            params = executor["params"]
            created_at = version.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            result.append(
                {
                    "version_id": version.id,
                    "version_number": version.version_number,
                    "system_id": system.id,
                    "system_name": system.name,
                    "node_id": node_id,
                    "created_at": created_at.isoformat(),
                    "created_by": version.created_by,
                    "template": template,
                    "template_sha256": canonical_sha256(template),
                    "provider": params.get("provider"),
                    "model": params.get("model"),
                    "matches_current": template == current,
                }
            )
    return {
        "current_template": current,
        "current_sha256": canonical_sha256(current),
        "entries": result,
    }


def restore(db, *, workspace, user, skill, body, authorize_read):
    # Refresh under the same row lock used for optimistic concurrency. Checking
    # only the digest loaded before acquiring the lock would lose concurrent edits.
    db.refresh(skill, with_for_update=True)
    current = require_template(skill)
    row = (
        db.query(SystemVersion, System)
        .join(System, System.id == SystemVersion.system_id)
        .filter(
            SystemVersion.id == body.version_id,
            SystemVersion.workspace_id == workspace.id,
            System.workspace_id == workspace.id,
            SystemVersion.release_kind.in_(["publish", "rollback", "migration"]),
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            404,
            detail={
                "code": "PROMPT_VERSION_NOT_FOUND",
                "message": "Published instructions not found.",
            },
        )
    version, system = row
    authorize_read(db, user=user, workspace=workspace, system=system)
    selected = next(
        (
            template
            for node, template, _ in contract_entries(version, skill.slug)
            if node == body.node_id and canonical_sha256(template) == body.template_sha256
        ),
        None,
    )
    if selected is None:
        raise HTTPException(
            404,
            detail={
                "code": "PROMPT_VERSION_NOT_FOUND",
                "message": "Published instructions not found.",
            },
        )
    if selected == current:
        db.commit()
        return skill
    if canonical_sha256(current) != body.expected_current_sha256:
        raise HTTPException(
            409,
            detail={
                "code": "PROMPT_CHANGED",
                "message": "Instructions changed. Reload before restoring.",
            },
        )
    schema = skill.input_schema or {}
    # A historical placeholder absent from today's closed contract cannot be
    # satisfied by a caller. Fail before replacing the working catalog template.
    if schema.get("additionalProperties") is False:
        _render_template(selected, {key: "" for key in schema.get("properties", {})})
    executor = copy.deepcopy(skill.executor)
    executor["params"]["template"] = selected
    skill.executor = validate_executor_binding(executor)
    audit_id = emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        actor=user.id,
        event_type="skill.prompt.restored",
        details={
            "skill_id": skill.id,
            "source_version_id": version.id,
            "source_node_id": body.node_id,
            "before_sha256": canonical_sha256(current),
            "after_sha256": canonical_sha256(selected),
        },
    )
    if audit_id is None:
        raise HTTPException(
            503,
            detail={
                "code": "PROMPT_AUDIT_UNAVAILABLE",
                "message": "Instructions were not restored because their audit record could not be saved.",
            },
        )
    db.commit()
    db.refresh(skill)
    return skill
