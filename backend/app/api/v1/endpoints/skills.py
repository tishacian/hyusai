"""Canonical /skills endpoints — Registry with certification + metrics.

The seeded registry is read-only from the UI: it comes from the in-process
`app.services.skills_registry` and metrics are aggregated from
`SkillInvocation` records. A workspace can additionally author its own Skills,
under `skill.admin` and inside its own slug namespace, binding them to the
verified executor set rather than to code of its own.
"""
from dataclasses import dataclass
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm import load_only

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.capability import Capability
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.user import User
from app.models.workspace import Workspace
from app.services.catalog_visibility import (
    SkillVisibility,
    WorkspaceCatalogPolicy,
    blocked_skill_levers,
    skill_capability_index,
    skill_visibility,
    visible_capabilities,
    visible_skill_ids_from_capabilities,
    workspace_catalog_policy,
)
from app.services.flow_contracts import FlowContractError, validate_schema_definition
from app.services.iam.decision_plane import enforce_action
from app.services.iam.legacy_authority import (
    legacy_object_action_allowed,
    legacy_workspace_admin,
)
from app.services.run_access import readable_runs, readable_skill_invocations_for_runs
from app.services.projection_integrity import invocation_cost_is_measured
from app.services.skills_registry.binding import SkillBindingError, workspace_skill_slug
from app.services.skills_registry.brd_import import (
    BrdUnreadableError,
    parse_business_requirements,
)
from app.services.skills_registry.executors import (
    validate_executor_binding,
    verified_executor_catalog,
)
from app.services.skills_registry.published_bindings import published_skill_bindings
from app.services.skills_registry.seed import SKILL_CATEGORIES
from app.services.tabular_predict import skill_provenance

router = APIRouter()

# A workspace picks from the taxonomy the seeder already established rather than
# inventing a tenth section: the palette groups by category, so a private
# category would fragment the very surface authoring is meant to populate.
AUTHORABLE_CATEGORIES = tuple(sorted(set(SKILL_CATEGORIES.values())))


def _known_category(value: Optional[str]) -> Optional[str]:
    if value is not None and value not in AUTHORABLE_CATEGORIES:
        raise ValueError("category must be one of: " + ", ".join(AUTHORABLE_CATEGORIES))
    return value


class SkillCreate(BaseModel):
    """A Skill definition, minus everything the workspace does not decide.

    ``slug`` is derived from ``local_name`` and the workspace id.
    ``certification_level``, ``is_seeded``, ``workspace_id``, ``version`` and
    ``metrics`` are the platform's or the runtime's, so accepting them here
    would let an authored row assert something no one measured or granted.
    """

    local_name: str
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    type: str = Field(default="generic", max_length=60)
    category: Optional[str] = None
    input_schema: Dict[str, Any] = {}
    output_schema: Dict[str, Any] = {}
    executor: Dict[str, Any]
    execution: Optional[Dict[str, Any]] = None
    pricing: Optional[Dict[str, Any]] = None
    # Optional: a Skill nobody claims is still catalogued, it simply sits in
    # the palette with no Capability behind it. Naming one at creation is what
    # spares the author a second trip through the Capability screen.
    capability_id: str | None = None

    _category = field_validator("category")(_known_category)


class SkillUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    type: Optional[str] = Field(default=None, max_length=60)
    category: Optional[str] = None
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    executor: Optional[Dict[str, Any]] = None
    execution: Optional[Dict[str, Any]] = None
    pricing: Optional[Dict[str, Any]] = None

    _category = field_validator("category")(_known_category)


def _runtime_status(s: Skill) -> str:
    """Resolve the canonical 4-state runtime status for one catalog row.

    Returns one of ``bound`` | ``stub`` | ``unbound`` | ``catalog_only``.
    ``catalog_only`` means the Skill row exists in the database but has
    no registered wrapper — useful to flag "declared-but-unimplemented"
    capabilities in the UI.

    A workspace-defined row is never ``catalog_only``: it is not waiting for
    someone to implement a wrapper, it either has a verified executor binding
    and will run, or it has none and its resolution fails closed.
    """
    from app.services.skills_registry import registry_snapshot

    if s.workspace_id is not None:
        return _authored_runtime_status(s.executor)
    entry = registry_snapshot().get(s.slug)
    if entry is None:
        return "catalog_only"
    return entry.get("status", "unbound")


def _authored_runtime_status(executor: Any) -> str:
    try:
        validate_executor_binding(executor)
    except SkillBindingError:
        return "unbound"
    return "bound"


def _serialize(
    s: Skill,
    metrics: Optional[Dict[str, Any]] = None,
    visibility: Optional[SkillVisibility] = None,
    provenance: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = {
        "id": s.id,
        "slug": s.slug,
        "version": s.version,
        "name": s.name,
        "description": s.description,
        "type": s.type,
        "category": s.category,
        "input_schema": s.input_schema or {},
        "output_schema": s.output_schema or {},
        "execution": s.execution or {},
        "pricing": s.pricing or {},
        "certification_level": s.certification_level,
        "is_seeded": s.is_seeded == "Y",
        "provider": s.provider,
        "metrics": metrics or s.metrics or {},
        "runtime_status": _runtime_status(s),
        "workspace_scope": "global" if s.workspace_id is None else "workspace",
        # Safe to serialise beside the schemas because no verified executor
        # declares a credential parameter and every params_schema is closed.
        "executor": s.executor or None,
    }
    if visibility is not None:
        payload["visibility"] = visibility.to_dict()
    # Only ever set for a Skill published from a model lineage, so a catalog
    # that trains nothing carries no extra field.
    if provenance is not None:
        payload["provenance"] = provenance
    return payload


@dataclass(frozen=True)
class _CatalogView:
    """One pass over the workspace catalog, with the filtering rule attached.

    A workspace routinely browses half of the global registry with no stated
    reason, which reads as arbitrary. Resolving every candidate row once —
    kept, filtered, and why — costs the same two queries as the old
    keep-only pass and lets the client explain the number it displays.
    """

    policy: WorkspaceCatalogPolicy
    visible: list[Skill]
    filtered: list[Skill]
    visibility_by_id: dict[str, SkillVisibility]

    def summary(self) -> Dict[str, Any]:
        reasons: Dict[str, int] = {}
        for skill in self.filtered:
            reason = self.visibility_by_id[str(skill.id)].reason
            reasons[reason] = reasons.get(reason, 0) + 1
        return {
            "total": len(self.visible) + len(self.filtered),
            "visible": len(self.visible),
            "filtered": len(self.filtered),
            "filtered_reasons": dict(sorted(reasons.items())),
            "policy": self.policy.to_dict(),
        }


def _catalog_view(db: DBSession, workspace: Workspace) -> _CatalogView:
    """Resolve the workspace catalog surface and the reason behind each row.

    The database registry is global, but the product surface is workspace
    filtered through visible capabilities plus explicit workspace overrides.
    """

    policy = workspace_catalog_policy(workspace)
    cap_rows = (
        db.query(Capability)
        .filter((Capability.workspace_id == workspace.id) | (Capability.workspace_id.is_(None)))
        .all()
    )
    visible_caps = visible_capabilities(cap_rows, workspace, policy)
    visible_skill_ids = visible_skill_ids_from_capabilities(visible_caps)
    capability_index = skill_capability_index(visible_caps)
    # Resolved from the capability rows already in hand: naming the lever
    # behind an exclusion costs no query beyond the two this pass makes.
    blocked_levers = blocked_skill_levers(cap_rows, workspace, policy)
    rows = (
        db.query(Skill)
        .filter((Skill.workspace_id == workspace.id) | (Skill.workspace_id.is_(None)))
        .all()
    )
    visible: list[Skill] = []
    filtered: list[Skill] = []
    visibility_by_id: dict[str, SkillVisibility] = {}
    for row in rows:
        decision = skill_visibility(
            row,
            workspace,
            visible_skill_ids,
            policy,
            capability_index=capability_index,
            blocked_levers=blocked_levers,
        )
        visibility_by_id[str(row.id)] = decision
        (visible if decision.visible else filtered).append(row)
    return _CatalogView(policy, visible, filtered, visibility_by_id)


def _visible_skill_rows(db: DBSession, workspace: Workspace) -> list[Skill]:
    return _catalog_view(db, workspace).visible


def _enforce_catalog_read(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
    resource_attrs: Optional[Dict[str, Any]] = None,
) -> None:
    """Resolve the catalog read boundary; `skill.read` is role-scoped."""

    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="skill",
        action="read",
        # Membership was already resolved by the workspace dependency, which is
        # the whole of the historical gate on browsing the catalog.
        legacy_allowed=True,
        resource_attrs=resource_attrs or {"scope": "collection"},
    )


def _enforce_catalog_admin(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
    resource_attrs: Optional[Dict[str, Any]] = None,
) -> None:
    """Resolve the authoring boundary.

    Authoring has no pre-v2 behaviour to preserve, so compat is given the
    candidate rule rather than the permissive default the older mutation routes
    inherited. Promotion out of compat must not be what makes this gate real.
    """

    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="skill",
        action="admin",
        legacy_allowed=legacy_workspace_admin(db, user=user, workspace=workspace),
        resource_attrs=resource_attrs or {"scope": "collection"},
    )


def _authored_skill(db: DBSession, workspace: Workspace, slug: str) -> Skill:
    """Load one editable row, or 404.

    Seeded rows are reachable through this path only to be refused: a workspace
    admin who could edit them would be editing every other workspace's catalog,
    and the next seeder run would silently revert the edit anyway.
    """

    row = (
        db.query(Skill)
        .filter(
            Skill.slug == slug,
            Skill.workspace_id == workspace.id,
            Skill.is_seeded == "N",
        )
        .first()
    )
    if row is None:
        raise HTTPException(404, "Skill not found (or not editable in this workspace)")
    return row


def _contract_error(exc: FlowContractError | SkillBindingError) -> HTTPException:
    detail = (
        exc.to_dict()
        if isinstance(exc, FlowContractError)
        else {"code": exc.code, "message": exc.message}
    )
    return HTTPException(400, detail)


def _validated_schemas(body: SkillCreate | SkillUpdate) -> Dict[str, Any]:
    """Compile both contracts with the executable-schema rules Flows enforce.

    Reusing ``validate_schema_definition`` rather than a bare ``check_schema``
    keeps one definition of "executable": remote ``$ref``, unbounded size and
    unbounded nesting are refused here exactly as they are at publication, so an
    author cannot save a Skill that only fails once a Flow is built on it.
    """

    fields = body.model_dump(exclude_unset=True)
    validated: Dict[str, Any] = {}
    for field in ("input_schema", "output_schema"):
        if fields.get(field) is None:
            continue
        try:
            validated[field] = validate_schema_definition(fields[field], field=field)
        except FlowContractError as exc:
            raise _contract_error(exc) from exc
    return validated


def _claim_capability(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    skill: Skill,
    capability_id: str,
) -> dict[str, Any]:
    """Ask one Capability of this workspace to carry a freshly authored Skill.

    Deliberately non-fatal. The Skill already exists and is already visible in
    the catalog; a refused claim is a missing link, not a reason to throw the
    definition away and make the author retype it. The verdict travels back in
    the response so the surface can say which of the two happened.

    Only a workspace-owned Capability is a candidate: the seeded catalog is
    shared by every workspace, and appending to it here would append to it for
    all of them.
    """

    row = (
        db.query(Capability)
        .filter(Capability.id == capability_id, Capability.workspace_id == workspace.id)
        .first()
    )
    if row is None:
        return {
            "attached": False,
            "capability_name": None,
            "reason": "no Capability of this workspace has that id",
        }
    try:
        enforce_action(
            db,
            user=user,
            workspace=workspace,
            resource_kind="capability",
            action="admin",
            legacy_allowed=legacy_object_action_allowed(
                db,
                user=user,
                workspace=workspace,
                resource_kind="capability",
                action="admin",
            ),
            resource_attrs={"capability_id": row.id},
        )
    except HTTPException as exc:
        return {
            "attached": False,
            "capability_name": row.name,
            "reason": _refusal_text(exc),
        }
    claimed = list(row.skill_ids or [])
    if skill.id not in claimed:
        claimed.append(skill.id)
        # Reassigned rather than mutated in place: a JSON column does not see
        # an append, and the claim would be lost at commit.
        row.skill_ids = claimed
        db.commit()
    return {"attached": True, "capability_name": row.name, "reason": None}


def _refusal_text(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("code") or detail)
    return str(detail)


@router.get("/runtime-health")
async def runtime_health(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Report the live runtime status of every registered skill wrapper.

    Canonical 4-state: ``bound`` (real implementation), ``stub`` (degraded
    stand-in), ``unbound`` (declared in the registry but no wrapper) or
    ``catalog_only`` (exists in the Skill catalog but has no registry
    entry at all).
    """
    from app.services.skills_registry import registry_snapshot

    _enforce_catalog_read(db, user=user, workspace=workspace)
    snapshot = registry_snapshot()
    visible_rows = _visible_skill_rows(db, workspace)
    visible_slugs = {s.slug for s in visible_rows}
    snapshot = {
        slug: entry
        for slug, entry in snapshot.items()
        if slug in visible_slugs
    }
    # An authored row has a runtime of its own, so reporting it as awaiting a
    # wrapper would misdirect the operator reading this surface.
    for row in visible_rows:
        if row.workspace_id is not None:
            snapshot[row.slug] = {
                "status": _authored_runtime_status(row.executor),
                "declared_status": "workspace_executor",
                "module": (row.executor or {}).get("kind"),
            }
    summary = {"bound": 0, "stub": 0, "unbound": 0, "catalog_only": 0}
    for entry in snapshot.values():
        summary[entry["status"]] = summary.get(entry["status"], 0) + 1

    catalog_slugs = visible_slugs
    catalog_only = catalog_slugs - set(snapshot.keys())
    summary["catalog_only"] = len(catalog_only)
    for slug in catalog_only:
        snapshot[slug] = {"status": "catalog_only", "declared_status": None, "module": None}
    return {"skills": snapshot, "summary": summary}


@router.get("")
async def list_skills(
    skill_type: Optional[str] = None,
    category: Optional[str] = None,
    certification: Optional[str] = None,
    include_filtered: bool = False,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """List the workspace catalog.

    ``include_filtered`` adds the registry rows this workspace does not see,
    each carrying the rule that excluded it, so a curation surface can offer
    them instead of pretending they do not exist. It is opt-in: the default
    payload and its size are unchanged.
    """
    _enforce_catalog_read(db, user=user, workspace=workspace)
    view = _catalog_view(db, workspace)
    rows: list[Skill] = list(view.visible)
    if include_filtered:
        rows += view.filtered
    if skill_type:
        rows = [row for row in rows if row.type == skill_type]
    if category:
        rows = [row for row in rows if row.category == category]
    if certification:
        rows = [row for row in rows if row.certification_level == certification]
    rows = sorted(rows, key=lambda row: (row.type or "", row.name or ""))

    # Metrics only exist for skills this workspace has actually run.
    metrics_by_slug = _aggregate_metrics(
        db,
        workspace=workspace,
        user=user,
        slugs=[row.slug for row in view.visible],
    )
    # The model behind a published Skill, resolved to the version that currently
    # serves its lineage. One query per distinct lineage, none for a catalog that
    # publishes no model.
    provenance_by_slug = skill_provenance(db, rows)
    return {
        "skills": [
            _serialize(
                s,
                metrics_by_slug.get(s.slug),
                view.visibility_by_id.get(str(s.id)),
                provenance_by_slug.get(s.slug),
            )
            for s in rows
        ],
        "catalog": view.summary(),
    }


@router.get("/executors")
async def list_verified_executors(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """The runtimes an authored Skill may bind to, and their parameter shapes.

    An authoring surface offers a choice from this list. There is no free-text
    path, module or URL to type, which is the whole point of the set.
    """

    _enforce_catalog_read(db, user=user, workspace=workspace)
    return {
        "executors": verified_executor_catalog(),
        "categories": list(AUTHORABLE_CATEGORIES),
        "editable": legacy_workspace_admin(db, user=user, workspace=workspace),
    }


@router.post("")
async def create_skill(
    body: SkillCreate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Define a Skill owned by this workspace.

    The caller names the Skill; the server derives the slug. That is what makes
    cross-namespace authoring unreachable rather than merely rejected.
    """

    _enforce_catalog_admin(db, user=user, workspace=workspace)
    try:
        identity = workspace_skill_slug(
            workspace_id=workspace.id,
            local_name=body.local_name,
        )
        executor = validate_executor_binding(body.executor)
    except SkillBindingError as exc:
        raise _contract_error(exc) from exc
    if db.query(Skill).filter(Skill.slug == identity.slug).first():
        raise HTTPException(409, "A Skill with this name already exists in this workspace")

    row = Skill(
        workspace_id=workspace.id,
        slug=identity.slug,
        name=body.name,
        description=body.description,
        type=body.type,
        category=body.category,
        executor=executor,
        # An authored Skill cannot claim a certification nobody granted it, and
        # ``is_seeded`` decides both editability and what the seeder owns.
        certification_level="basic",
        is_seeded="N",
        **_validated_schemas(body),
    )
    if body.execution is not None:
        row.execution = body.execution
    if body.pricing is not None:
        row.pricing = body.pricing
    db.add(row)
    db.commit()
    db.refresh(row)
    payload = _serialize(row)
    if body.capability_id:
        payload["capability_claim"] = _claim_capability(
            db,
            workspace=workspace,
            user=user,
            skill=row,
            capability_id=body.capability_id,
        )
    return payload


# A Business Requirements document is a few hundred kilobytes of tables. The
# ceiling is here so an accidental upload of something else is refused before
# it is parsed, not after.
_MAX_IMPORT_BYTES = 5 * 1024 * 1024


@router.post("/import/business-requirements")
async def import_business_requirements(
    file: UploadFile = File(...),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Read a BRD ``.docx`` into draft material. Nothing is created.

    Gated on ``skill.admin`` because the only thing this answer is good for is
    authoring a Skill, and offering the reading to someone who cannot author
    would be an invitation to a dead end.

    A document whose tables are missing or renamed still answers 200 with empty
    lists and a ``problems`` sentence: the wizard must open either way, blank
    if need be. Only a file that is not a Word document at all is refused.
    """

    _enforce_catalog_admin(db, user=user, workspace=workspace)
    data = await file.read()
    if len(data) > _MAX_IMPORT_BYTES:
        raise HTTPException(
            413,
            {
                "code": "brd_document_too_large",
                "message": "The document exceeds 5 MiB.",
            },
        )
    try:
        return parse_business_requirements(data)
    except BrdUnreadableError as exc:
        raise HTTPException(
            400,
            {"code": "brd_document_unreadable", "message": str(exc)},
        ) from exc


@router.get("/{slug}")
async def get_skill(
    slug: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _enforce_catalog_read(
        db,
        user=user,
        workspace=workspace,
        resource_attrs={"skill_slug": slug},
    )
    view = _catalog_view(db, workspace)
    s = next((row for row in view.visible if row.slug == slug), None)
    if not s:
        raise HTTPException(404, "Skill not found")
    metrics = _aggregate_metrics(
        db,
        workspace=workspace,
        user=user,
        slugs=[s.slug],
    ).get(s.slug)
    return _serialize(
        s,
        metrics,
        view.visibility_by_id.get(str(s.id)),
        skill_provenance(db, [s]).get(s.slug),
    )


@router.patch("/{slug}")
async def update_skill(
    slug: str,
    body: SkillUpdate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Edit a Skill this workspace owns.

    The slug is absent from the patch on purpose: it is the dispatch key already
    written into every Flow node bound to this Skill, so renaming it would break
    those bindings silently. The display name is the mutable identity.

    The edit is admitted even when a published Flow dispatches this Skill, since
    publication froze the contract and the runtime it accepted: the edit cannot
    change what that Flow does. Refusing instead would make a Skill uneditable
    for as long as anything published used it. What the response owes the author
    is therefore not a veto but the truth about reach, so ``published_bindings``
    names every published version that dispatches this Skill and which of them
    are now behind the definition just saved.
    """

    row = _authored_skill(db, workspace, slug)
    _enforce_catalog_admin(
        db,
        user=user,
        workspace=workspace,
        resource_attrs={"skill_id": row.id, "skill_slug": row.slug},
    )
    patch = body.model_dump(exclude_unset=True)
    if "executor" in patch:
        try:
            row.executor = validate_executor_binding(patch["executor"])
        except SkillBindingError as exc:
            raise _contract_error(exc) from exc
    for field, value in _validated_schemas(body).items():
        setattr(row, field, value)
    for field in ("name", "description", "type", "category", "execution", "pricing"):
        if field in patch:
            setattr(row, field, patch[field])
    db.commit()
    db.refresh(row)
    bindings = published_skill_bindings(db, workspace_id=workspace.id, skill=row)
    return {
        **_serialize(row),
        "published_bindings": [binding.to_dict() for binding in bindings],
    }


@router.delete("/{slug}")
async def delete_skill(
    slug: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Remove a Skill this workspace owns and nothing depends on.

    An invoked Skill is part of the run ledger's account of what happened, and a
    Capability that claims it would be left pointing at nothing. Both refuse the
    delete and name the dependency, so the answer is not "try again".

    A published Flow refuses too. Its frozen contract would keep the runs going,
    but the graph could no longer be validated or republished, so the System
    would be executable and uneditable at once -- and a version published before
    authored runtimes were frozen resolves the row live and would simply stop.
    """

    row = _authored_skill(db, workspace, slug)
    _enforce_catalog_admin(
        db,
        user=user,
        workspace=workspace,
        resource_attrs={"skill_id": row.id, "skill_slug": row.slug},
    )
    bindings = published_skill_bindings(db, workspace_id=workspace.id, skill=row)
    if bindings:
        raise HTTPException(
            409,
            {
                "code": "skill_bound_by_published_flow",
                "message": (
                    "This Skill is dispatched by the published Flow of "
                    + ", ".join(binding.system_name for binding in bindings)
                    + ". Publish a Flow that no longer uses it first."
                ),
                "published_bindings": [binding.to_dict() for binding in bindings],
            },
        )
    invoked = (
        db.query(SkillInvocation.id)
        .join(Run, Run.id == SkillInvocation.run_id)
        .filter(Run.workspace_id == workspace.id, SkillInvocation.skill_slug == row.slug)
        .first()
    )
    if invoked is not None:
        raise HTTPException(
            409,
            {
                "code": "skill_has_run_history",
                "message": "This Skill has been invoked and is part of the run ledger.",
            },
        )
    carriers = [
        cap.slug
        for cap in db.query(Capability)
        .filter(Capability.workspace_id == workspace.id)
        .all()
        if row.id in (cap.skill_ids or [])
    ]
    if carriers:
        raise HTTPException(
            409,
            {
                "code": "skill_claimed_by_capability",
                "message": "Remove this Skill from " + ", ".join(sorted(carriers)) + " first.",
            },
        )
    deleted = row.slug
    db.delete(row)
    db.commit()
    return {"deleted": deleted}


def _aggregate_metrics(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    slugs: list[str],
) -> Dict[str, Dict[str, Any]]:
    """Aggregate runtime metrics only from readable invocation objects."""
    if not slugs:
        return {}
    invocations = (
        db.query(SkillInvocation)
        .join(Run, Run.id == SkillInvocation.run_id)
        .filter(Run.workspace_id == workspace.id)
        .filter(SkillInvocation.skill_slug.in_(slugs))
        # This rollup and ``skill_invocation.read`` only read these scalars.
        # Selecting the whole entity also transfers and JSON-decodes every
        # payload column (``trace``, ``output_ref``, ``execution_snapshot``,
        # ...), which reaches hundreds of megabytes on a mature workspace and
        # dominated the endpoint's latency while contributing nothing.
        .options(
            load_only(
                SkillInvocation.run_id,
                SkillInvocation.skill_slug,
                SkillInvocation.status,
                SkillInvocation.latency_ms,
                SkillInvocation.cost,
                SkillInvocation.cost_measured,
            )
        )
        .all()
    )
    run_ids = {row.run_id for row in invocations}
    runs = (
        db.query(Run)
        .filter(Run.workspace_id == workspace.id, Run.id.in_(run_ids))
        .all()
        if run_ids
        else []
    )
    runs = readable_runs(
        db,
        runs=runs,
        user=user,
        workspace=workspace,
    )
    invocations = readable_skill_invocations_for_runs(
        db,
        invocations=invocations,
        runs=runs,
        user=user,
        workspace=workspace,
    )
    grouped: dict[str, list[SkillInvocation]] = {}
    for invocation in invocations:
        grouped.setdefault(invocation.skill_slug, []).append(invocation)

    out: Dict[str, Dict[str, Any]] = {}
    for slug, rows in grouped.items():
        count = len(rows)
        latencies = [float(row.latency_ms) for row in rows if row.latency_ms is not None]
        costs = [
            float(row.cost)
            for row in rows
            if row.cost is not None and invocation_cost_is_measured(row)
        ]
        ok = sum(1 for row in rows if row.status == "completed")
        out[slug] = {
            "calls": count,
            "avg_latency_ms": sum(latencies) / len(latencies) if latencies else None,
            "total_cost": sum(costs) if costs else None,
            "cost_state": "available" if costs else "not_measured",
            "cost_sample_count": len(costs),
            "success_rate": ok / count if count else None,
        }
    return out
