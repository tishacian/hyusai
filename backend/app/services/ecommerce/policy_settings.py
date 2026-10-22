"""Workspace-scoped claim policy settings with optimistic writes and audit."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.core.iam.roles import is_admin_template
from app.models.audit import AuditLog
from app.models.workspace import Workspace, WorkspaceMember
from app.services.connectors.generic import postgresql_claims as pg
from app.services.ecommerce import claims
from app.services.ecommerce.resolution_policy import ResolutionPolicy, resolve_policy


class PolicySettingsError(ValueError):
    def __init__(self, code, status=409):
        self.code, self.status = code, status
        super().__init__(code)


def can_configure(db, workspace, user):
    member = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace.id,
            WorkspaceMember.user_id == user.id,
        )
        .populate_existing()
        .one_or_none()
    )
    return bool(member and is_admin_template(member.role_template, member.role))


def read(db, workspace, user):
    config = claims._config(workspace)
    policy = resolve_policy(config)
    return {
        "policy": policy.model_dump(),
        "sha256": policy.sha256,
        "source": "workspace" if "resolution_policy" in config else "legacy_defaults",
        "revision": config.get("resolution_policy_revision", 0),
        "updated_at": config.get("resolution_policy_updated_at"),
        "can_configure": can_configure(db, workspace, user),
        "invariants": {
            "human_approval_required": True,
            "financial_execution": "simulated",
            "duplicate_action_guard": True,
            "live_evidence_recheck": True,
        },
    }


def _scope_sha(config):
    return pg.digest(
        {
            "policy": resolve_policy(config).model_dump(),
            "allowed_claim_ids": config["allowed_claim_ids"],
            "allowed_collection_slugs": config["allowed_collection_slugs"],
        }
    )


def update(db, workspace, user, policy: ResolutionPolicy, expected_sha256: str):
    if not can_configure(db, workspace, user):
        raise PolicySettingsError("CLAIM_POLICY_ADMIN_REQUIRED", 403)
    config = claims._config(workspace)
    previous = resolve_policy(config)
    if previous.sha256 != expected_sha256:
        raise PolicySettingsError("CLAIM_POLICY_CONFLICT")
    scope = _scope_sha(config)

    # Read and authorize the actual revision before acquiring the workspace
    # write lock: credential audit uses an independent transaction.
    claim_id = (config.get("stage_claim_ids") or config["allowed_claim_ids"])[0]
    snapshot = pg.snapshot(workspace, claim_id)
    references = [
        r
        for r in snapshot["data"]["documents"]
        if r.get("document_key") == policy.document_key
        and r.get("document_type") == "policy"
        and r.get("version") == policy.document_version
        and r.get("sha256") == policy.document_sha256
    ]
    if len(references) != 1:
        raise PolicySettingsError("CLAIM_POLICY_DOCUMENT_UNAVAILABLE")
    reader = SimpleNamespace(initiated_by_user_id=user.id)
    authorized = claims._sources(db, workspace, reader, snapshot, ("policy",))
    if not any(ref == references[0] for ref, _, _ in authorized):
        raise PolicySettingsError("CLAIM_POLICY_DOCUMENT_UNAVAILABLE")

    locked = (
        db.query(Workspace)
        .filter(Workspace.id == workspace.id)
        .populate_existing()
        .with_for_update(key_share=True)
        .one()
    )
    if not can_configure(db, locked, user):
        raise PolicySettingsError("CLAIM_POLICY_ADMIN_REQUIRED", 403)
    current = claims._config(locked)
    if _scope_sha(current) != scope or resolve_policy(current).sha256 != expected_sha256:
        raise PolicySettingsError("CLAIM_POLICY_CONFLICT")
    # Identical saves are a read-back, not an extra policy revision.
    if policy.sha256 == previous.sha256 and "resolution_policy" in current:
        return read(db, locked, user)
    settings = copy.deepcopy(locked.settings or {})
    updated = settings["ecommerce_claims"]
    updated["resolution_policy"] = policy.model_dump()
    updated["resolution_policy_revision"] = int(current.get("resolution_policy_revision", 0)) + 1
    updated["resolution_policy_updated_at"] = datetime.now(timezone.utc).isoformat()
    locked.settings = settings
    db.add(
        AuditLog(
            id=str(uuid4()),
            workspace_id=workspace.id,
            event_type="claims.resolution_policy.updated",
            actor=user.id,
            details={
                "before": previous.model_dump(),
                "after": policy.model_dump(),
                "before_sha256": previous.sha256,
                "after_sha256": policy.sha256,
                "revision": updated["resolution_policy_revision"],
            },
        )
    )
    db.flush()
    return read(db, locked, user)
