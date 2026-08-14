"""Atomic server-draft and immutable Flow publication authority."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import desc
from sqlalchemy.orm import Session as DBSession

from app.models.run import Run
from app.models.system import System
from app.models.system_flow_draft import SystemFlowDraft
from app.models.system_version import SystemVersion
from app.services import flow_contracts, flow_diff
from app.services.audit_logger import emit_audit_event
from app.services.chains import dag_validator, version_service
from app.services.run_engine.debug_contract import (
    DebugContractError,
    normalize_input_debug,
)
from app.services.run_engine.execution_contract import (
    canonical_flow,
    canonical_flow_sha256,
    resolve_flow_execution,
)
from app.services.run_engine.run_contracts import (
    RuntimeContractError,
    validate_ingress_payload,
)
from app.services.system_catalog_bindings import (
    SystemCatalogBindingError,
    resolve_persisted_system_catalog_bindings,
)
from app.services.workspace_features import graduated_feature_enabled

FEATURE_KEY = "flow_publication_v1"


# Not frozen: a context manager's ``__exit__`` assigns ``__traceback__`` while
# the exception propagates, which a frozen dataclass refuses.
@dataclass
class FlowPublicationError(Exception):
    code: str
    message: str
    status_code: int = 409
    details: dict[str, Any] | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "error": self.code.lower(),
            "code": self.code,
            "message": self.message,
            **copy.deepcopy(self.details or {}),
        }


@dataclass(frozen=True, slots=True)
class FlowReconcileResult:
    """Outcome of a seed/reconciler Flow write across both authority modes."""

    status: str
    draft_revision: int | None = None
    published_version_id: str | None = None


def flow_publication_enabled(workspace: Any) -> bool:
    """Draft/publish separation, on unless the workspace explicitly opts out.

    Opting out restores the destructive posture where an editor write lands
    directly on the live executable graph, so it is only reachable by storing
    ``false``.
    """
    return graduated_feature_enabled(workspace, FEATURE_KEY)


def require_flow_publication(workspace: Any) -> None:
    if not flow_publication_enabled(workspace):
        raise FlowPublicationError(
            code="FLOW_PUBLICATION_DISABLED",
            message="Flow publication is not enabled for this workspace.",
            status_code=404,
        )


def compile_execution_contract(
    db: DBSession,
    flow: Any,
    workspace: Any,
    *,
    system: System | None = None,
) -> dict[str, Any]:
    """Bind publication identity around the shared executable compiler."""

    canonical = canonical_flow(flow)
    resolution = resolve_flow_execution(canonical, workspace)
    allowed_skill_ids: set[str] | None = None
    if system is not None:
        try:
            bindings = resolve_persisted_system_catalog_bindings(
                db,
                workspace=workspace,
                system=system,
            )
        except SystemCatalogBindingError as exc:
            raise FlowPublicationError(
                code=exc.code.upper(),
                message=str(exc),
                status_code=422,
                details={"field": exc.field},
            ) from exc
        allowed_skill_ids = set(bindings.effective_skill_ids)
    try:
        contract = flow_contracts.compile_execution_contract(
            db,
            flow=canonical,
            workspace_id=getattr(workspace, "id", None),
            runtime_mode=resolution.runtime_mode,
            allowed_skill_ids=allowed_skill_ids,
        )
    except flow_contracts.FlowContractError as exc:
        raise FlowPublicationError(
            code=exc.code.upper(),
            message=exc.message,
            status_code=422,
            details={"path": exc.path} if exc.path else None,
        ) from exc
    return copy.deepcopy(contract)


def _pinned_execution_contract(version: SystemVersion) -> dict[str, Any] | None:
    """Return a structurally valid immutable contract, never a live rebuild.

    Migration baselines intentionally carry ``NULL`` because Alembic cannot
    safely resolve mutable workspace Skills.  Those versions remain valid
    history, but they are not executable until an explicit Publish appends a
    version with a frozen contract.
    """

    try:
        return flow_contracts.validate_execution_contract(version.execution_contract)
    except flow_contracts.FlowContractError:
        return None


def _lock_system(
    db: DBSession,
    *,
    system_id: str,
    workspace_id: str | None,
) -> System:
    system = (
        db.query(System)
        .filter(System.id == system_id, System.workspace_id == workspace_id)
        .populate_existing()
        .with_for_update(of=System)
        .one_or_none()
    )
    if system is None:
        raise FlowPublicationError(
            code="SYSTEM_NOT_FOUND",
            message="System not found.",
            status_code=404,
        )
    return system


def _locked_draft(db: DBSession, system: System) -> SystemFlowDraft:
    draft = (
        db.query(SystemFlowDraft)
        .filter(
            SystemFlowDraft.system_id == system.id,
            SystemFlowDraft.workspace_id == system.workspace_id,
        )
        .populate_existing()
        .with_for_update(of=SystemFlowDraft)
        .one_or_none()
    )
    if draft is None:
        raise FlowPublicationError(
            code="FLOW_DRAFT_STATE_MISSING",
            message="The publication migration has not initialized this System draft.",
        )
    return draft


def _owned_version(
    db: DBSession,
    *,
    system: System,
    version_id: str | None,
) -> SystemVersion:
    version = (
        db.query(SystemVersion)
        .filter(
            SystemVersion.id == version_id,
            SystemVersion.system_id == system.id,
            SystemVersion.workspace_id == system.workspace_id,
        )
        .one_or_none()
    )
    if version is None:
        raise FlowPublicationError(
            code="PUBLISHED_FLOW_VERSION_INVALID",
            message="The published pointer does not reference an owned immutable version.",
        )
    return version


def _assert_published_mirror(system: System, version: SystemVersion) -> str:
    for subject, raw_flow in (
        ("System.flow_definition", system.flow_definition),
        ("SystemVersion.flow_definition", version.flow_definition),
    ):
        shape_issues = dag_validator.validate_flow_shape(raw_flow)
        if shape_issues:
            raise FlowPublicationError(
                code="PUBLISHED_FLOW_SHAPE_INVALID",
                message=f"{subject} has a malformed Flow graph shape.",
                details={"issues": dag_validator.issues_to_payload(shape_issues)},
            )
    mirror_hash = canonical_flow_sha256(system.flow_definition)
    version_hash = canonical_flow_sha256(version.flow_definition)
    if mirror_hash != version_hash:
        raise FlowPublicationError(
            code="PUBLISHED_FLOW_MIRROR_DRIFT",
            message="System.flow_definition no longer mirrors its published version.",
            details={
                "system_id": system.id,
                "published_flow_version_id": version.id,
                "mirror_flow_sha256": mirror_hash,
                "published_flow_sha256": version_hash,
            },
        )
    if version.flow_sha256 is not None and version.flow_sha256 != version_hash:
        raise FlowPublicationError(
            code="PUBLISHED_FLOW_VERSION_HASH_DRIFT",
            message="The published version hash no longer matches its immutable JSON payload.",
            details={
                "system_id": system.id,
                "published_flow_version_id": version.id,
                "stored_flow_sha256": version.flow_sha256,
                "published_flow_sha256": version_hash,
            },
        )
    return version_hash


def _assert_draft_precondition(
    draft: SystemFlowDraft,
    *,
    expected_revision: int,
    expected_flow_sha256: str | None = None,
) -> None:
    if draft.revision != expected_revision:
        raise FlowPublicationError(
            code="FLOW_DRAFT_REVISION_MISMATCH",
            message="Reload the server draft before writing or executing it.",
            details={
                "expected_revision": expected_revision,
                "current_revision": draft.revision,
                "current_flow_sha256": draft.flow_sha256,
            },
        )
    if expected_flow_sha256 is not None and draft.flow_sha256 != expected_flow_sha256:
        raise FlowPublicationError(
            code="FLOW_DRAFT_SHA256_MISMATCH",
            message="The submitted draft hash is stale.",
            details={
                "expected_flow_sha256": expected_flow_sha256,
                "current_flow_sha256": draft.flow_sha256,
                "current_revision": draft.revision,
            },
        )


def initialize_publication_state(
    db: DBSession,
    *,
    system: System,
    workspace: Any,
    actor: str,
) -> tuple[SystemFlowDraft, SystemVersion]:
    """Initialize a newly-created System while its transaction still owns it.

    Migration 077 handles every pre-existing row. This path exists solely for
    Systems created after a workspace has opted in and is idempotent for safe
    retries inside the same request.
    """

    require_flow_publication(workspace)
    locked = _lock_system(
        db,
        system_id=system.id,
        workspace_id=system.workspace_id,
    )
    existing_draft = db.query(SystemFlowDraft).filter_by(system_id=locked.id).one_or_none()
    if existing_draft is not None and locked.published_flow_version_id:
        return existing_draft, _owned_version(
            db,
            system=locked,
            version_id=locked.published_flow_version_id,
        )

    flow = copy.deepcopy(canonical_flow(locked.flow_definition))
    digest = canonical_flow_sha256(flow)
    exact = next(
        (
            row
            for row in db.query(SystemVersion)
            .filter(
                SystemVersion.system_id == locked.id,
                SystemVersion.workspace_id == locked.workspace_id,
            )
            .order_by(SystemVersion.version_number.desc())
            .all()
            if canonical_flow_sha256(row.flow_definition) == digest
        ),
        None,
    )
    if exact is not None and _pinned_execution_contract(exact) is None:
        # Reusing a migration/legacy snapshot here would make the newly
        # feature-enabled System depend on mutable Skill rows at run time.
        exact = None
    if exact is None:
        latest = (
            db.query(SystemVersion)
            .filter(SystemVersion.system_id == locked.id)
            .order_by(SystemVersion.version_number.desc())
            .first()
        )
        exact = SystemVersion(
            id=str(uuid4()),
            system_id=locked.id,
            workspace_id=locked.workspace_id,
            version_number=(latest.version_number if latest else 0) + 1,
            flow_definition=flow,
            message="Initial published Flow",
            created_by=actor,
            flow_sha256=digest,
            release_kind="migration",
            draft_revision=1,
            execution_contract=compile_execution_contract(
                db,
                flow,
                workspace,
                system=locked,
            ),
        )
        db.add(exact)
        db.flush()

    now = datetime.utcnow()
    locked.published_flow_version_id = exact.id
    locked.published_by = actor
    locked.published_at = now
    draft = existing_draft or SystemFlowDraft(system_id=locked.id)
    draft.workspace_id = locked.workspace_id
    draft.flow_definition = copy.deepcopy(flow)
    draft.revision = 1
    draft.flow_sha256 = digest
    draft.base_published_version_id = exact.id
    draft.updated_by = actor
    draft.updated_at = now
    db.add(draft)
    db.flush()
    return draft, exact


def initialize_new_system_publication_if_enabled(
    db: DBSession,
    *,
    system: System,
    workspace: Any,
    actor: str,
) -> tuple[SystemFlowDraft, SystemVersion] | None:
    """Initialize publication authority for a newly-created ``System``.

    Every production creation path uses this gate so enabling Flow publication
    cannot leave post-migration rows without a draft or immutable published
    pointer.  Feature-off behaviour is deliberately untouched: callers retain
    their historical versioning policy when this function returns ``None``.

    The flush is part of the feature-on path because ORM defaults (notably the
    System id) must exist before the parent row can be locked and its contract
    compiled.  Initialization remains in the caller's transaction.
    """

    if not flow_publication_enabled(workspace):
        return None
    db.flush()
    return initialize_publication_state(
        db,
        system=system,
        workspace=workspace,
        actor=actor,
    )


def reconcile_system_flow(
    db: DBSession,
    *,
    system: System,
    workspace: Any,
    flow_definition: Mapping[str, Any],
    actor: str,
    publish_if_owned: bool = False,
    ownership_prefix: str | None = None,
    message: str = "Seed-owned Flow reconciliation",
) -> FlowReconcileResult:
    """Reconcile generated Flow state without bypassing publication authority.

    Legacy workspaces retain their historical direct-mirror semantics.  Once
    publication is enabled, the immutable published mirror is never assigned
    directly: a clean draft is updated instead.  A reconciler may publish that
    draft only when the persisted ``created_by`` proves it owns the System.
    Dirty operator drafts are always preserved, including on seed-owned rows.
    """

    desired = copy.deepcopy(canonical_flow(flow_definition))
    desired_sha256 = canonical_flow_sha256(desired)
    if not flow_publication_enabled(workspace):
        if canonical_flow_sha256(system.flow_definition) == desired_sha256:
            return FlowReconcileResult(status="legacy_no_op")
        system.flow_definition = desired
        db.add(system)
        return FlowReconcileResult(status="legacy_mirror_updated")

    # Catalog bindings and other non-Flow seed fields may have been updated by
    # the caller immediately before reconciliation. Persist them before the
    # populate-existing lock reloads the parent row and compiles a contract.
    db.flush()
    # A System predating publication authority, or adopted from a workspace that
    # had it off, carries no draft. Initialize from its current mirror so the
    # reconciler starts from a coherent baseline instead of refusing.
    initialize_publication_state(db, system=system, workspace=workspace, actor=actor)
    locked = _lock_system(
        db,
        system_id=system.id,
        workspace_id=system.workspace_id,
    )
    draft = _locked_draft(db, locked)
    published = _owned_version(
        db,
        system=locked,
        version_id=locked.published_flow_version_id,
    )
    published_sha256 = _assert_published_mirror(locked, published)
    if canonical_flow_sha256(draft.flow_definition) != draft.flow_sha256:
        raise FlowPublicationError(
            code="FLOW_DRAFT_HASH_DRIFT",
            message="The stored draft hash does not match its JSON payload.",
        )
    if draft.base_published_version_id != published.id:
        raise FlowPublicationError(
            code="FLOW_DRAFT_BASE_DRIFT",
            message="The server draft no longer references the current published version.",
            details={
                "draft_base_published_version_id": draft.base_published_version_id,
                "published_flow_version_id": published.id,
            },
        )

    owner_prefix = ownership_prefix if ownership_prefix is not None else actor
    owns_system = bool(
        publish_if_owned
        and owner_prefix
        and str(locked.created_by or "").startswith(owner_prefix)
    )
    clean_draft = draft.flow_sha256 == published_sha256
    contract_missing = _pinned_execution_contract(published) is None

    if desired_sha256 != published_sha256:
        if not clean_draft:
            # A previous attempt by this same reconciler may have staged the
            # exact desired draft and failed before Publish. It alone may
            # resume; an operator-authored draft is never adopted or erased.
            can_resume_owned_draft = bool(
                owns_system
                and draft.flow_sha256 == desired_sha256
                and draft.updated_by == actor
            )
            if not can_resume_owned_draft:
                return FlowReconcileResult(
                    status="operator_draft_preserved",
                    draft_revision=draft.revision,
                    published_version_id=published.id,
                )
        else:
            draft, _ = save_draft(
                db,
                system_id=locked.id,
                workspace=workspace,
                flow_definition=desired,
                expected_revision=draft.revision,
                actor=actor,
            )
    elif not (owns_system and clean_draft and contract_missing):
        return FlowReconcileResult(
            status=("operator_draft_preserved" if not clean_draft else "published_no_op"),
            draft_revision=draft.revision,
            published_version_id=published.id,
        )

    if not owns_system:
        return FlowReconcileResult(
            status="draft_updated",
            draft_revision=draft.revision,
            published_version_id=published.id,
        )

    version, draft, no_op = publish_draft(
        db,
        system_id=locked.id,
        workspace=workspace,
        expected_draft_revision=draft.revision,
        expected_published_version_id=published.id,
        message=message,
        breaking_change_intent="acknowledged",
        actor=actor,
    )
    return FlowReconcileResult(
        status="published_no_op" if no_op else "published",
        draft_revision=draft.revision,
        published_version_id=version.id,
    )


def flow_state(
    db: DBSession,
    *,
    system: System,
    workspace: Any,
) -> dict[str, Any]:
    require_flow_publication(workspace)
    draft = (
        db.query(SystemFlowDraft)
        .filter(
            SystemFlowDraft.system_id == system.id,
            SystemFlowDraft.workspace_id == system.workspace_id,
        )
        .one_or_none()
    )
    if draft is None:
        raise FlowPublicationError(
            code="FLOW_DRAFT_STATE_MISSING",
            message="The publication migration has not initialized this System draft.",
        )
    published = _owned_version(
        db,
        system=system,
        version_id=system.published_flow_version_id,
    )
    published_hash = _assert_published_mirror(system, published)
    return {
        "system_id": system.id,
        "status": system.status,
        "draft": {
            "revision": draft.revision,
            "flow_sha256": draft.flow_sha256,
            "flow_definition": copy.deepcopy(draft.flow_definition),
            "base_published_version_id": draft.base_published_version_id,
            "updated_by": draft.updated_by,
            "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
        },
        "published": {
            "version_id": published.id,
            "version_number": published.version_number,
            "flow_sha256": published.flow_sha256 or published_hash,
            "flow_definition": copy.deepcopy(published.flow_definition),
            "release_kind": published.release_kind or "legacy_snapshot",
            "published_by": system.published_by,
            "published_at": system.published_at.isoformat() if system.published_at else None,
            "execution_contract": copy.deepcopy(published.execution_contract),
            "execution_contract_ready": _pinned_execution_contract(published) is not None,
        },
    }


def _assert_draft_flow_shape(flow: Mapping[str, Any]) -> None:
    """Reject JSON shapes that graph consumers would otherwise reinterpret."""

    issues = dag_validator.validate_flow_shape(flow)
    if issues:
        raise FlowPublicationError(
            code="FLOW_DRAFT_SHAPE_INVALID",
            message="The server draft has a malformed Flow graph shape.",
            status_code=422,
            details={"issues": dag_validator.issues_to_payload(issues)},
        )


def save_draft(
    db: DBSession,
    *,
    system_id: str,
    workspace: Any,
    flow_definition: Mapping[str, Any],
    expected_revision: int,
    actor: str,
) -> tuple[SystemFlowDraft, bool]:
    require_flow_publication(workspace)
    system = _lock_system(db, system_id=system_id, workspace_id=workspace.id)
    draft = _locked_draft(db, system)
    _assert_draft_precondition(draft, expected_revision=expected_revision)
    flow = copy.deepcopy(canonical_flow(flow_definition))
    _assert_draft_flow_shape(flow)
    digest = canonical_flow_sha256(flow)
    if digest == draft.flow_sha256:
        return draft, True
    draft.flow_definition = flow
    draft.flow_sha256 = digest
    draft.revision += 1
    draft.updated_by = actor
    draft.updated_at = datetime.utcnow()
    emit_audit_event(
        workspace_id=workspace.id,
        event_type="flow.draft.saved",
        actor=actor,
        agent_id=system.id,
        details={
            "system_id": system.id,
            "draft_revision": draft.revision,
            "flow_sha256": digest,
        },
        db=db,
    )
    db.flush()
    return draft, False


def restore_draft(
    db: DBSession,
    *,
    system_id: str,
    workspace: Any,
    version_id: str,
    expected_revision: int,
    actor: str,
) -> tuple[SystemFlowDraft, bool]:
    require_flow_publication(workspace)
    system = _lock_system(db, system_id=system_id, workspace_id=workspace.id)
    draft = _locked_draft(db, system)
    _assert_draft_precondition(draft, expected_revision=expected_revision)
    target = _owned_version(db, system=system, version_id=version_id)
    _assert_draft_flow_shape(target.flow_definition)
    digest = canonical_flow_sha256(target.flow_definition)
    if digest == draft.flow_sha256:
        return draft, True
    draft.flow_definition = copy.deepcopy(canonical_flow(target.flow_definition))
    draft.flow_sha256 = digest
    draft.revision += 1
    draft.updated_by = actor
    draft.updated_at = datetime.utcnow()
    # The diff base remains what is currently published, not the historical
    # source copied into the mutable draft.
    draft.base_published_version_id = system.published_flow_version_id
    emit_audit_event(
        workspace_id=workspace.id,
        event_type="flow.draft.restored",
        actor=actor,
        agent_id=system.id,
        details={
            "system_id": system.id,
            "source_version_id": target.id,
            "draft_revision": draft.revision,
            "flow_sha256": digest,
        },
        db=db,
    )
    db.flush()
    return draft, False


def publish_draft(
    db: DBSession,
    *,
    system_id: str,
    workspace: Any,
    expected_draft_revision: int,
    expected_published_version_id: str | None,
    message: str,
    breaking_change_intent: str | None,
    actor: str,
) -> tuple[SystemVersion, SystemFlowDraft, bool]:
    require_flow_publication(workspace)
    system = _lock_system(db, system_id=system_id, workspace_id=workspace.id)
    draft = _locked_draft(db, system)
    _assert_draft_precondition(draft, expected_revision=expected_draft_revision)
    if system.published_flow_version_id != expected_published_version_id:
        raise FlowPublicationError(
            code="PUBLISHED_FLOW_VERSION_MISMATCH",
            message="Reload the published Flow before publishing this draft.",
            details={
                "expected_published_version_id": expected_published_version_id,
                "current_published_version_id": system.published_flow_version_id,
            },
        )
    current = _owned_version(
        db,
        system=system,
        version_id=system.published_flow_version_id,
    )
    current_hash = _assert_published_mirror(system, current)
    raw_flow = copy.deepcopy(draft.flow_definition)
    shape_issues = dag_validator.validate_flow_shape(raw_flow)
    if shape_issues:
        raise FlowPublicationError(
            code="FLOW_PUBLISH_VALIDATION_FAILED",
            message="The draft has a malformed Flow graph shape.",
            status_code=422,
            details={"issues": dag_validator.issues_to_payload(shape_issues)},
        )
    flow = copy.deepcopy(canonical_flow(raw_flow))
    draft_hash = canonical_flow_sha256(flow)
    if draft_hash != draft.flow_sha256:
        raise FlowPublicationError(
            code="FLOW_DRAFT_HASH_DRIFT",
            message="The stored draft hash does not match its JSON payload.",
        )

    issues = dag_validator.validate_flow(flow)
    if dag_validator.has_errors(issues):
        raise FlowPublicationError(
            code="FLOW_PUBLISH_VALIDATION_FAILED",
            message="The draft has blocking Flow diagnostics.",
            status_code=422,
            details={"issues": dag_validator.issues_to_payload(issues)},
        )
    current_contract = _pinned_execution_contract(current)
    # Compile before deciding no-op.  Skill schemas are mutable catalog data;
    # an unchanged graph can therefore produce a new immutable execution
    # contract that must be published as its own append-only version.
    contract = compile_execution_contract(db, flow, workspace, system=system)
    if (
        draft_hash == current_hash
        and current_contract is not None
        and current_contract.get("contract_sha256") == contract.get("contract_sha256")
    ):
        draft.base_published_version_id = current.id
        return current, draft, True

    semantic_diff = flow_diff.semantic_flow_diff(
        canonical_flow(current.flow_definition),
        flow,
        base_identity=f"published:{current.version_number}",
        target_identity=f"draft:{draft.revision}",
        base_contract=current_contract,
        target_contract=contract,
    )
    breaking = [
        str(change.get("path") or change.get("subject") or "breaking_change")
        for change in semantic_diff["changes"]
        if change.get("impact") == "breaking"
    ]
    if system.status == "active" and breaking and breaking_change_intent != "acknowledged":
        raise FlowPublicationError(
            code="FLOW_BREAKING_CHANGE_INTENT_REQUIRED",
            message="Publishing this active System requires explicit breaking-change intent.",
            details={
                "required_intent": "acknowledged",
                "breaking_changes": breaking,
            },
        )

    latest = (
        db.query(SystemVersion)
        .filter(SystemVersion.system_id == system.id)
        .order_by(desc(SystemVersion.version_number))
        .first()
    )
    version = SystemVersion(
        id=str(uuid4()),
        system_id=system.id,
        workspace_id=system.workspace_id,
        version_number=(latest.version_number if latest else 0) + 1,
        flow_definition=flow,
        flow_sha256=draft_hash,
        release_kind="publish",
        draft_revision=draft.revision,
        execution_contract=contract,
        message=message.strip(),
        created_by=actor,
    )
    db.add(version)
    db.flush()

    published_at = datetime.utcnow()
    status_before = system.status
    system.flow_definition = copy.deepcopy(flow)
    system.published_flow_version_id = version.id
    system.published_by = actor
    system.published_at = published_at
    draft.base_published_version_id = version.id
    emit_audit_event(
        workspace_id=workspace.id,
        event_type="flow.published",
        actor=actor,
        agent_id=system.id,
        details={
            "system_id": system.id,
            "version_id": version.id,
            "version_number": version.version_number,
            "draft_revision": draft.revision,
            "flow_sha256": draft_hash,
            "status_unchanged": status_before,
            "breaking_change_count": len(breaking),
            "semantic_diff_summary": semantic_diff["summary"],
        },
        db=db,
    )
    db.flush()
    from app.services.experience.bindings import retarget_seed_stub_bindings

    retarget_seed_stub_bindings(db, workspace=workspace, system=system, actor=actor)
    version_service.purge_version_window(db=db, system_id=system.id)
    return version, draft, False


def create_draft_test_run(
    db: DBSession,
    *,
    system_id: str,
    workspace: Any,
    user_id: str | None,
    input_ref: Mapping[str, Any],
    expected_draft_revision: int,
    expected_flow_sha256: str,
    ingress_id: str | None = None,
    ingress_kind: str | None = None,
) -> Run:
    require_flow_publication(workspace)
    system = _lock_system(db, system_id=system_id, workspace_id=workspace.id)
    draft = _locked_draft(db, system)
    _assert_draft_precondition(
        draft,
        expected_revision=expected_draft_revision,
        expected_flow_sha256=expected_flow_sha256,
    )
    flow = copy.deepcopy(canonical_flow(draft.flow_definition))
    issues = dag_validator.validate_flow(flow)
    if dag_validator.has_errors(issues):
        raise FlowPublicationError(
            code="FLOW_DRAFT_TEST_VALIDATION_FAILED",
            message="The draft has blocking Flow diagnostics.",
            status_code=422,
            details={"issues": dag_validator.issues_to_payload(issues)},
        )
    contract = compile_execution_contract(db, flow, workspace, system=system)
    resolution = resolve_flow_execution(flow, workspace)
    try:
        accepted_input = normalize_input_debug(
            input_ref,
            runtime_mode=str(contract.get("runtime_mode") or ""),
        )
    except DebugContractError as exc:
        raise FlowPublicationError(
            code=exc.code,
            message=exc.message,
            status_code=422,
            details={"path": exc.path},
        ) from exc
    raw_ingresses = contract.get("ingresses")
    ingresses = (
        [item for item in raw_ingresses if isinstance(item, Mapping)]
        if isinstance(raw_ingresses, list)
        else []
    )
    if (ingress_id is None) != (ingress_kind is None):
        raise FlowPublicationError(
            code="FLOW_DRAFT_TEST_INGRESS_INCOMPLETE",
            message="Draft test ingress_id and kind must be supplied together.",
            status_code=422,
        )
    selected_ingress: Mapping[str, Any] | None = None
    if ingress_id is not None and ingress_kind is not None:
        matches = [
            item
            for item in ingresses
            if item.get("ingress_id") == ingress_id and item.get("kind") == ingress_kind
        ]
        if len(matches) != 1:
            raise FlowPublicationError(
                code="FLOW_DRAFT_TEST_INGRESS_NOT_FOUND",
                message="The requested ingress is not part of the saved draft contract.",
                status_code=422,
                details={"ingress_id": ingress_id, "kind": ingress_kind},
            )
        selected_ingress = matches[0]
    elif len(ingresses) == 1:
        selected_ingress = ingresses[0]
    elif len(ingresses) > 1:
        raise FlowPublicationError(
            code="FLOW_DRAFT_TEST_INGRESS_AMBIGUOUS",
            message="The draft test-run must name exactly one entry point.",
            status_code=422,
            details={
                "candidate_ingresses": sorted(
                    (
                        {
                            "ingress_id": str(item.get("ingress_id") or ""),
                            "kind": str(item.get("kind") or ""),
                        }
                        for item in ingresses
                    ),
                    key=lambda item: (item["kind"], item["ingress_id"]),
                )
            },
        )
    elif contract.get("runtime_mode") != "sequential_legacy":
        raise FlowPublicationError(
            code="FLOW_DRAFT_TEST_INGRESS_REQUIRED",
            message="An executable DAG draft must expose one ingress.",
            status_code=422,
        )
    if selected_ingress is not None:
        contract_payload = {
            key: value for key, value in accepted_input.items() if key != "_debug"
        }
        try:
            validate_ingress_payload(
                contract,
                ingress_id=str(selected_ingress["ingress_id"]),
                kind=str(selected_ingress["kind"]),
                payload=contract_payload,
            )
        except RuntimeContractError as exc:
            raise FlowPublicationError(
                code=exc.code.upper(),
                message=exc.message,
                status_code=422,
                details={"path": exc.path} if exc.path else None,
            ) from exc
    # Ingress selection is server-owned.  A caller cannot inject lookalike
    # evidence into the walker.
    accepted_input.pop("_ingress", None)
    execution = (
        dict(accepted_input.get("execution"))
        if isinstance(accepted_input.get("execution"), Mapping)
        else {}
    )
    for key in (
        "ingress_id",
        "ingress_selection_version",
        "published_flow_version_id",
        "execution_surface",
    ):
        execution.pop(key, None)
    execution.update(
        {
            "flow_sha256": draft.flow_sha256,
            "runtime_mode": contract["runtime_mode"],
            "runtime_mode_reason": resolution.reason,
            "execution_surface": "draft_test",
            "draft_revision": draft.revision,
            **(
                {
                    "ingress_id": selected_ingress["ingress_id"],
                    "ingress_selection_version": 1,
                }
                if selected_ingress is not None
                else {}
            ),
        }
    )
    accepted_input["execution"] = execution
    if selected_ingress is not None:
        accepted_input["_ingress"] = {
            "ingress_id": selected_ingress["ingress_id"],
            "source_node_id": selected_ingress["source_node_id"],
            "kind": selected_ingress["kind"],
            "adapter": {"surface": "draft_test"},
        }
    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        capability_id=system.capability_id,
        initiated_by_user_id=user_id,
        input_ref=accepted_input,
        flow_snapshot=flow,
        flow_version_id=None,
        published_flow_version_id=None,
        flow_sha256=draft.flow_sha256,
        execution_contract=contract,
        execution_surface="draft_test",
        status="pending",
        started_at=datetime.utcnow(),
        trigger="draft_test",
    )
    db.add(run)
    db.flush()
    return run


def published_run_evidence(
    db: DBSession,
    *,
    system: System,
    workspace: Any,
) -> tuple[SystemVersion | None, dict[str, Any], str, dict[str, Any]]:
    """Resolve immutable Run evidence while preserving flag-off compatibility."""

    if not flow_publication_enabled(workspace):
        shape_issues = dag_validator.validate_flow_shape(system.flow_definition)
        if shape_issues:
            raise FlowPublicationError(
                code="PERSISTED_FLOW_SHAPE_INVALID",
                message="System.flow_definition has a malformed Flow graph shape.",
                status_code=422,
                details={"issues": dag_validator.issues_to_payload(shape_issues)},
            )
        flow = copy.deepcopy(canonical_flow(system.flow_definition))
        digest = canonical_flow_sha256(flow)
        return None, flow, digest, compile_execution_contract(db, flow, workspace)
    version = _owned_version(
        db,
        system=system,
        version_id=system.published_flow_version_id,
    )
    version_digest = _assert_published_mirror(system, version)
    contract = _pinned_execution_contract(version)
    if contract is None:
        raise FlowPublicationError(
            code="PUBLISHED_EXECUTION_CONTRACT_MISSING",
            message=(
                "The published version has no valid immutable execution contract; "
                "publish the server draft before running it."
            ),
        )
    if version.flow_sha256 != version_digest:
        raise FlowPublicationError(
            code="PUBLISHED_FLOW_VERSION_HASH_MISSING",
            message=(
                "The published version has no exact immutable Flow digest; "
                "publish the server draft before running it."
            ),
        )
    return version, copy.deepcopy(version.flow_definition), version_digest, contract
