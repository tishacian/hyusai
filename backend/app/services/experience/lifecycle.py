"""Workspace-scoped Experience draft / release / deploy. Publish ≠ activate."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import desc, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.models.experience import (
    DEFAULT_RENDERER_VERSION,
    DEPLOYMENT_CHANNELS,
    EXPERIENCE_PATTERNS,
    Experience,
    ExperienceDeployment,
    ExperienceDraftRevision,
    ExperienceRelease,
)
from app.services.audit_logger import emit_audit_event
from app.services.experience import bindings as binding_service

SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{0,119}$")
COMPONENT_TYPES = frozenset(
    {
        "page",
        "section",
        "header",
        "form",
        "action_button",
        "result",
        "table",
        "queue",
        "approval_card",
        "runtime_status",
        "evidence",
        "history",
        "kpi",
        "callout",
        "map_panel",
        "agenda_panel",
        "intelligence_feed",
        "decision_queue",
    }
)
ABSOLUTE_POSITION_KEYS = frozenset(
    {
        "x",
        "y",
        "left",
        "top",
        "right",
        "bottom",
        "absoluteX",
        "absoluteY",
        "absolute_x",
        "absolute_y",
    }
)
EMPTY_STATE_PATTERNS = frozenset({"queue", "approval"})
EMPTY_PAGES = {"pages": []}


@dataclass(slots=True)
class ExperienceError(Exception):
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


def _canonical_sha256(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def content_sha256(pages: Mapping[str, Any], binding_keys: list[str]) -> str:
    return _canonical_sha256({"binding_keys": binding_keys, "pages": pages})


def serialize_experience(
    row: Experience,
    deployments: list[ExperienceDeployment] | None = None,
) -> dict[str, Any]:
    payload = {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "name": row.name,
        "slug": row.slug,
        "pattern": row.pattern,
        "languages": copy.deepcopy(row.languages or []),
        "theme": copy.deepcopy(row.theme or {}),
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
    if deployments is not None:
        payload["deployments"] = [serialize_deployment(item) for item in deployments]
    return payload


def serialize_draft(row: ExperienceDraftRevision) -> dict[str, Any]:
    return {
        "experience_id": row.experience_id,
        "revision": row.revision,
        "pages": copy.deepcopy(row.pages or EMPTY_PAGES),
        "binding_keys": list(row.binding_keys or []),
        "content_sha256": row.content_sha256,
        "updated_by": row.updated_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def serialize_release(row: ExperienceRelease) -> dict[str, Any]:
    return {
        "id": row.id,
        "experience_id": row.experience_id,
        "release_number": row.release_number,
        "content_sha256": row.content_sha256,
        "pages": copy.deepcopy(row.pages),
        "bindings_snapshot": copy.deepcopy(row.bindings_snapshot or []),
        "access_snapshot": copy.deepcopy(row.access_snapshot or {}),
        "languages": copy.deepcopy(row.languages or []),
        "theme": copy.deepcopy(row.theme or {}),
        "renderer_version": row.renderer_version,
        "notes": row.notes,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def serialize_deployment(row: ExperienceDeployment) -> dict[str, Any]:
    return {
        "id": row.id,
        "experience_id": row.experience_id,
        "channel": row.channel,
        "release_id": row.release_id,
        "previous_release_id": row.previous_release_id,
        "audience": copy.deepcopy(row.audience or {}),
        "updated_by": row.updated_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def serialize_detail(
    row: Experience,
    draft: ExperienceDraftRevision | None,
    deployments: list[ExperienceDeployment],
) -> dict[str, Any]:
    payload = serialize_experience(row)
    payload["draft"] = serialize_draft(draft) if draft is not None else None
    payload["deployments"] = [serialize_deployment(item) for item in deployments]
    return payload


def _validate_slug(slug: str) -> str:
    value = (slug or "").strip()
    if not SLUG_RE.fullmatch(value):
        raise ExperienceError(
            code="EXPERIENCE_SLUG_INVALID",
            message="slug must be a lowercase URL identifier.",
            status_code=422,
        )
    return value


def _validate_pattern(pattern: str) -> str:
    if pattern not in EXPERIENCE_PATTERNS:
        raise ExperienceError(
            code="EXPERIENCE_PATTERN_INVALID",
            message=f"pattern must be one of {', '.join(EXPERIENCE_PATTERNS)}.",
            status_code=422,
        )
    return pattern


def _validate_languages(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ExperienceError(
            code="EXPERIENCE_LANGUAGES_INVALID",
            message="languages must be an array of non-empty strings.",
            status_code=422,
        )
    return [item.strip() for item in value]


def _validate_theme(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ExperienceError(
            code="EXPERIENCE_THEME_INVALID",
            message="theme must be an object.",
            status_code=422,
        )
    return copy.deepcopy(value)


def _validate_audience(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ExperienceError(
            code="EXPERIENCE_AUDIENCE_INVALID",
            message="audience must be an object.",
            status_code=422,
        )
    return copy.deepcopy(value)


def _reject_absolute_positioning(node: Mapping[str, Any], *, path: str) -> None:
    extras = ABSOLUTE_POSITION_KEYS.intersection(node)
    if extras:
        raise ExperienceError(
            code="DRAFT_ABSOLUTE_POSITIONING",
            message="Absolute positioning fields are not allowed.",
            status_code=422,
            details={"path": path, "fields": sorted(extras)},
        )
    if node.get("position") == "absolute":
        raise ExperienceError(
            code="DRAFT_ABSOLUTE_POSITIONING",
            message="Absolute positioning fields are not allowed.",
            status_code=422,
            details={"path": path, "fields": ["position"]},
        )


def validate_pages_document(pages: Any) -> dict[str, Any]:
    if not isinstance(pages, dict):
        raise ExperienceError(
            code="DRAFT_PAGES_INVALID",
            message="pages JSON must be an object.",
            status_code=422,
        )
    raw_pages = pages.get("pages")
    if not isinstance(raw_pages, list):
        raise ExperienceError(
            code="DRAFT_PAGES_INVALID",
            message="pages JSON must contain a pages array.",
            status_code=422,
        )
    _reject_absolute_positioning(pages, path="pages")
    cleaned_pages: list[dict[str, Any]] = []
    for index, page in enumerate(raw_pages):
        path = f"pages[{index}]"
        if not isinstance(page, dict):
            raise ExperienceError(
                code="DRAFT_PAGES_INVALID",
                message="Each page must be an object.",
                status_code=422,
                details={"path": path},
            )
        if not isinstance(page.get("id"), str) or not page["id"].strip():
            raise ExperienceError(
                code="DRAFT_PAGES_INVALID",
                message="Each page must have an id.",
                status_code=422,
                details={"path": path},
            )
        if not isinstance(page.get("title"), str) or not page["title"].strip():
            raise ExperienceError(
                code="DRAFT_PAGES_INVALID",
                message="Each page must have a title.",
                status_code=422,
                details={"path": path},
            )
        components = page.get("components")
        if not isinstance(components, list):
            raise ExperienceError(
                code="DRAFT_PAGES_INVALID",
                message="Each page must have a components array.",
                status_code=422,
                details={"path": path},
            )
        _reject_absolute_positioning(page, path=path)
        cleaned_components: list[dict[str, Any]] = []
        for c_index, component in enumerate(components):
            c_path = f"{path}.components[{c_index}]"
            if not isinstance(component, dict):
                raise ExperienceError(
                    code="DRAFT_PAGES_INVALID",
                    message="Each component must be an object.",
                    status_code=422,
                    details={"path": c_path},
                )
            component_type = component.get("type")
            if component_type not in COMPONENT_TYPES:
                raise ExperienceError(
                    code="DRAFT_COMPONENT_TYPE_INVALID",
                    message="Unknown component type.",
                    status_code=422,
                    details={"path": c_path, "type": component_type},
                )
            _reject_absolute_positioning(component, path=c_path)
            cleaned_components.append(copy.deepcopy(component))
        cleaned = copy.deepcopy(page)
        cleaned["components"] = cleaned_components
        cleaned_pages.append(cleaned)
    document = copy.deepcopy(pages)
    document["pages"] = cleaned_pages
    return document


def _validate_binding_keys(keys: Any) -> list[str]:
    if keys is None:
        return []
    if not isinstance(keys, list) or any(not isinstance(item, str) for item in keys):
        raise ExperienceError(
            code="DRAFT_BINDING_KEYS_INVALID",
            message="binding_keys must be an array of strings.",
            status_code=422,
        )
    seen: set[str] = set()
    ordered: list[str] = []
    for item in keys:
        key = item.strip()
        if not binding_service.BINDING_KEY_RE.fullmatch(key):
            raise ExperienceError(
                code="BINDING_KEY_INVALID",
                message="binding_key must be a lowercase dotted identifier.",
                status_code=422,
            )
        if key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return ordered


def _owned(
    db: DBSession,
    *,
    workspace_id: str,
    experience_id: str,
    lock: bool = False,
) -> Experience:
    query = db.query(Experience).filter(
        Experience.id == experience_id,
        Experience.workspace_id == workspace_id,
    )
    if lock:
        query = query.populate_existing().with_for_update(of=Experience)
    row = query.one_or_none()
    if row is None:
        raise ExperienceError(
            code="EXPERIENCE_NOT_FOUND",
            message="Experience not found.",
            status_code=404,
        )
    return row


def _draft_for(db: DBSession, experience: Experience) -> ExperienceDraftRevision:
    draft = (
        db.query(ExperienceDraftRevision)
        .filter(
            ExperienceDraftRevision.experience_id == experience.id,
            ExperienceDraftRevision.workspace_id == experience.workspace_id,
        )
        .one_or_none()
    )
    if draft is None:
        raise ExperienceError(
            code="EXPERIENCE_DRAFT_MISSING",
            message="The experience has no draft revision.",
            status_code=409,
        )
    return draft


def _deployments_for(
    db: DBSession, *, workspace_id: str, experience_id: str
) -> list[ExperienceDeployment]:
    return (
        db.query(ExperienceDeployment)
        .filter(
            ExperienceDeployment.experience_id == experience_id,
            ExperienceDeployment.workspace_id == workspace_id,
        )
        .order_by(ExperienceDeployment.channel.asc())
        .all()
    )


def _owned_release(
    db: DBSession,
    *,
    experience: Experience,
    release_id: str,
) -> ExperienceRelease:
    row = (
        db.query(ExperienceRelease)
        .filter(
            ExperienceRelease.id == release_id,
            ExperienceRelease.experience_id == experience.id,
            ExperienceRelease.workspace_id == experience.workspace_id,
        )
        .one_or_none()
    )
    if row is None:
        raise ExperienceError(
            code="EXPERIENCE_RELEASE_NOT_FOUND",
            message="Release not found for this experience.",
            status_code=404,
        )
    return row


def list_experiences(db: DBSession, *, workspace_id: str) -> list[Experience]:
    return (
        db.query(Experience)
        .filter(Experience.workspace_id == workspace_id)
        .order_by(Experience.slug.asc())
        .all()
    )


def list_deployments_for_workspace(
    db: DBSession, *, workspace_id: str
) -> list[ExperienceDeployment]:
    return (
        db.query(ExperienceDeployment)
        .filter(ExperienceDeployment.workspace_id == workspace_id)
        .order_by(
            ExperienceDeployment.experience_id.asc(),
            ExperienceDeployment.channel.asc(),
        )
        .all()
    )


def inventory_index(db: DBSession, *, workspace_id: str) -> dict[str, dict[str, Any]]:
    """Draft keys + latest release number, keyed by experience id."""
    drafts = (
        db.query(ExperienceDraftRevision)
        .filter(ExperienceDraftRevision.workspace_id == workspace_id)
        .all()
    )
    latest_rows = (
        db.query(
            ExperienceRelease.experience_id,
            func.max(ExperienceRelease.release_number),
        )
        .filter(ExperienceRelease.workspace_id == workspace_id)
        .group_by(ExperienceRelease.experience_id)
        .all()
    )
    latest = {experience_id: number for experience_id, number in latest_rows}
    index: dict[str, dict[str, Any]] = {}
    for draft in drafts:
        index[draft.experience_id] = {
            "binding_keys": list(draft.binding_keys or []),
            "draft_revision": draft.revision,
            "latest_release_number": latest.get(draft.experience_id),
        }
    return index


def audience_allows(audience: Any, role: str) -> bool:
    """Pilot visibility: empty audience (or empty roles) is open; otherwise match role.

    Accepted shapes: ``{"roles": [...]}`` or ``{"role_templates": [...]}``.
    """
    if not isinstance(audience, dict):
        return True
    raw = audience.get("roles")
    if raw is None:
        raw = audience.get("role_templates")
    if not isinstance(raw, list) or not raw:
        return True
    allowed = [item.strip() for item in raw if isinstance(item, str) and item.strip()]
    if not allowed:
        return True
    return role in allowed


def pick_work_channel(
    deployments: list[ExperienceDeployment], *, role: str
) -> ExperienceDeployment | None:
    """Prefer live (anyone with view). Else entitled pilot."""
    live = next((item for item in deployments if item.channel == "live"), None)
    if live is not None:
        return live
    pilot = next((item for item in deployments if item.channel == "pilot"), None)
    if pilot is not None and audience_allows(pilot.audience, role):
        return pilot
    return None


def resolve_work(
    db: DBSession, *, workspace_id: str, slug: str, role: str
) -> tuple[Experience, ExperienceDeployment, ExperienceRelease]:
    row = (
        db.query(Experience)
        .filter(Experience.workspace_id == workspace_id, Experience.slug == slug)
        .one_or_none()
    )
    if row is None:
        raise ExperienceError(
            code="EXPERIENCE_NOT_FOUND",
            message="Experience not found.",
            status_code=404,
        )
    chosen = pick_work_channel(
        _deployments_for(db, workspace_id=workspace_id, experience_id=row.id),
        role=role,
    )
    if chosen is None:
        raise ExperienceError(
            code="EXPERIENCE_NOT_FOUND",
            message="Experience not found.",
            status_code=404,
        )
    return row, chosen, _owned_release(db, experience=row, release_id=chosen.release_id)


def serialize_work(
    experience: Experience,
    deployment: ExperienceDeployment,
    release: ExperienceRelease,
) -> dict[str, Any]:
    return {
        "experience": serialize_experience(experience),
        "channel": deployment.channel,
        "release": {
            "id": release.id,
            "pages": copy.deepcopy(release.pages),
            "bindings_snapshot": copy.deepcopy(release.bindings_snapshot or []),
            "languages": copy.deepcopy(release.languages or []),
            "theme": copy.deepcopy(release.theme or {}),
            "renderer_version": release.renderer_version,
        },
    }


def get_experience(
    db: DBSession, *, workspace_id: str, experience_id: str
) -> tuple[Experience, ExperienceDraftRevision, list[ExperienceDeployment]]:
    row = _owned(db, workspace_id=workspace_id, experience_id=experience_id)
    return row, _draft_for(db, row), _deployments_for(
        db, workspace_id=workspace_id, experience_id=experience_id
    )


def create_experience(
    db: DBSession,
    *,
    workspace: Any,
    actor: str | None,
    name: str,
    slug: str,
    pattern: str,
    languages: Any,
    theme: Any,
) -> tuple[Experience, ExperienceDraftRevision]:
    cleaned_name = (name or "").strip()
    if not cleaned_name:
        raise ExperienceError(
            code="EXPERIENCE_NAME_INVALID",
            message="name is required.",
            status_code=422,
        )
    cleaned_slug = _validate_slug(slug)
    cleaned_pattern = _validate_pattern(pattern)
    cleaned_languages = _validate_languages(languages)
    cleaned_theme = _validate_theme(theme)
    existing = (
        db.query(Experience)
        .filter(Experience.workspace_id == workspace.id, Experience.slug == cleaned_slug)
        .one_or_none()
    )
    if existing is not None:
        raise ExperienceError(
            code="EXPERIENCE_SLUG_EXISTS",
            message="An experience with this slug already exists in the workspace.",
            status_code=409,
            details={"slug": cleaned_slug},
        )
    now = datetime.utcnow()
    row = Experience(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name=cleaned_name,
        slug=cleaned_slug,
        pattern=cleaned_pattern,
        languages=cleaned_languages,
        theme=cleaned_theme,
        created_by=actor,
        created_at=now,
        updated_at=now,
    )
    pages = copy.deepcopy(EMPTY_PAGES)
    keys: list[str] = []
    draft = ExperienceDraftRevision(
        experience_id=row.id,
        workspace_id=workspace.id,
        revision=1,
        pages=pages,
        binding_keys=keys,
        content_sha256=content_sha256(pages, keys),
        updated_by=actor,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.add(draft)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ExperienceError(
            code="EXPERIENCE_SLUG_EXISTS",
            message="An experience with this slug already exists in the workspace.",
            status_code=409,
            details={"slug": cleaned_slug},
        ) from exc
    emit_audit_event(
        workspace_id=workspace.id,
        event_type="experience.created",
        actor=actor or "unknown",
        agent_id=row.id,
        details={"experience_id": row.id, "slug": row.slug, "pattern": row.pattern},
        db=db,
    )
    return row, draft


def update_experience(
    db: DBSession,
    *,
    workspace_id: str,
    experience_id: str,
    name: str | None = None,
    slug: str | None = None,
    pattern: str | None = None,
    languages: Any = None,
    theme: Any = None,
) -> Experience:
    row = _owned(db, workspace_id=workspace_id, experience_id=experience_id, lock=True)
    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise ExperienceError(
                code="EXPERIENCE_NAME_INVALID",
                message="name is required.",
                status_code=422,
            )
        row.name = cleaned
    if slug is not None:
        cleaned_slug = _validate_slug(slug)
        clash = (
            db.query(Experience)
            .filter(
                Experience.workspace_id == workspace_id,
                Experience.slug == cleaned_slug,
                Experience.id != row.id,
            )
            .one_or_none()
        )
        if clash is not None:
            raise ExperienceError(
                code="EXPERIENCE_SLUG_EXISTS",
                message="An experience with this slug already exists in the workspace.",
                status_code=409,
                details={"slug": cleaned_slug},
            )
        row.slug = cleaned_slug
    if pattern is not None:
        row.pattern = _validate_pattern(pattern)
    if languages is not None:
        row.languages = _validate_languages(languages)
    if theme is not None:
        row.theme = _validate_theme(theme)
    row.updated_at = datetime.utcnow()
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ExperienceError(
            code="EXPERIENCE_SLUG_EXISTS",
            message="An experience with this slug already exists in the workspace.",
            status_code=409,
        ) from exc
    return row


def save_draft(
    db: DBSession,
    *,
    workspace_id: str,
    experience_id: str,
    pages: Any,
    binding_keys: Any,
    actor: str | None,
) -> ExperienceDraftRevision:
    experience = _owned(db, workspace_id=workspace_id, experience_id=experience_id, lock=True)
    document = validate_pages_document(pages)
    keys = _validate_binding_keys(binding_keys)
    digest = content_sha256(document, keys)
    draft = _draft_for(db, experience)
    if draft.content_sha256 == digest and draft.pages == document and list(draft.binding_keys or []) == keys:
        return draft
    draft.pages = document
    draft.binding_keys = keys
    draft.content_sha256 = digest
    draft.revision = int(draft.revision) + 1
    draft.updated_by = actor
    draft.updated_at = datetime.utcnow()
    db.flush()
    emit_audit_event(
        workspace_id=workspace_id,
        event_type="experience.draft_saved",
        actor=actor or "unknown",
        agent_id=experience.id,
        details={
            "experience_id": experience.id,
            "revision": draft.revision,
            "content_sha256": draft.content_sha256,
        },
        db=db,
    )
    return draft


def _binding_issue(key: str, resolved: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if resolved is None:
        return {
            "code": "BINDING_MISSING",
            "message": "Referenced binding_key does not exist.",
            "binding_key": key,
        }
    if resolved.get("status") != "ok":
        return {
            "code": "BINDING_NOT_OK",
            "message": "Referenced binding is not currently ok.",
            "binding_key": key,
            "status": resolved.get("status"),
            "reasons": list(resolved.get("reasons") or []),
        }
    return None


def _resolve_referenced(
    db: DBSession, *, workspace: Any, key: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    try:
        resolved = binding_service.resolve_binding(db, workspace=workspace, binding_key=key)
    except binding_service.BindingError as exc:
        if exc.code == "BINDING_NOT_FOUND":
            return None, _binding_issue(key, None)
        raise ExperienceError(
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            details=copy.deepcopy(exc.details),
        ) from exc
    return resolved, _binding_issue(key, resolved)


def _has_empty_state(pages: Mapping[str, Any]) -> bool:
    if pages.get("empty_state"):
        return True
    for page in pages.get("pages") or []:
        if not isinstance(page, Mapping):
            continue
        if page.get("empty_state"):
            return True
        for component in page.get("components") or []:
            if isinstance(component, Mapping) and component.get("empty_state"):
                return True
    return False


def ready_check(
    db: DBSession,
    *,
    workspace: Any,
    experience_id: str,
) -> dict[str, Any]:
    experience, draft, _deployments = get_experience(
        db, workspace_id=workspace.id, experience_id=experience_id
    )
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    pages = draft.pages if isinstance(draft.pages, dict) else {}
    raw_pages = pages.get("pages") if isinstance(pages.get("pages"), list) else []
    if not raw_pages:
        blockers.append({"code": "NO_PAGES", "message": "The draft has no pages."})
    for key in list(draft.binding_keys or []):
        _resolved, issue = _resolve_referenced(db, workspace=workspace, key=key)
        if issue is not None:
            blockers.append(issue)
    if experience.pattern in EMPTY_STATE_PATTERNS and not _has_empty_state(pages):
        warnings.append(
            {
                "code": "MISSING_EMPTY_STATE",
                "message": "Queue and approval patterns should declare an empty-state.",
            }
        )
    languages = experience.languages or []
    i18n = pages.get("i18n")
    if languages and not (isinstance(i18n, dict) and i18n):
        warnings.append(
            {
                "code": "MISSING_I18N",
                "message": "Languages are declared but the draft has no i18n map.",
            }
        )
    return {
        "ready": not blockers,
        "blockers": blockers,
        "warnings": warnings,
    }


def _bindings_snapshot(
    db: DBSession, *, workspace: Any, keys: list[str]
) -> list[dict[str, Any]]:
    snapshot: list[dict[str, Any]] = []
    for key in keys:
        resolved, issue = _resolve_referenced(db, workspace=workspace, key=key)
        if issue is not None or resolved is None:
            raise ExperienceError(
                code="EXPERIENCE_NOT_READY",
                message="The draft has ready-check blockers.",
                status_code=409,
                details={"blockers": [issue] if issue else []},
            )
        binding = resolved["binding"]
        snapshot.append(
            {
                "binding_key": binding["binding_key"],
                "system_id": binding["system_id"],
                "published_flow_version_id": binding["published_flow_version_id"],
                "flow_sha256": binding["flow_sha256"],
                "ingress_id": binding["ingress_id"],
                "input_schema_sha256": binding["input_schema_sha256"],
                "output_schema_sha256": binding["output_schema_sha256"],
                "confirmation_policy": binding["confirmation_policy"],
                "on_unavailable": binding["on_unavailable"],
            }
        )
    return snapshot


def create_release(
    db: DBSession,
    *,
    workspace: Any,
    experience_id: str,
    notes: str,
    actor: str | None,
) -> ExperienceRelease:
    cleaned_notes = (notes or "").strip()
    if not cleaned_notes:
        raise ExperienceError(
            code="EXPERIENCE_RELEASE_NOTES_REQUIRED",
            message="notes are required to create a release.",
            status_code=422,
        )
    experience = _owned(db, workspace_id=workspace.id, experience_id=experience_id, lock=True)
    draft = _draft_for(db, experience)
    check = ready_check(db, workspace=workspace, experience_id=experience.id)
    if check["blockers"]:
        raise ExperienceError(
            code="EXPERIENCE_NOT_READY",
            message="The draft has ready-check blockers.",
            status_code=409,
            details={"blockers": check["blockers"], "warnings": check["warnings"]},
        )
    latest = (
        db.query(ExperienceRelease)
        .filter(ExperienceRelease.experience_id == experience.id)
        .order_by(desc(ExperienceRelease.release_number))
        .first()
    )
    row = ExperienceRelease(
        id=str(uuid4()),
        experience_id=experience.id,
        workspace_id=experience.workspace_id,
        release_number=(latest.release_number if latest else 0) + 1,
        content_sha256=draft.content_sha256,
        pages=copy.deepcopy(draft.pages),
        bindings_snapshot=_bindings_snapshot(
            db, workspace=workspace, keys=list(draft.binding_keys or [])
        ),
        access_snapshot={},
        languages=copy.deepcopy(experience.languages or []),
        theme=copy.deepcopy(experience.theme or {}),
        renderer_version=DEFAULT_RENDERER_VERSION,
        notes=cleaned_notes,
        created_by=actor,
        created_at=datetime.utcnow(),
    )
    db.add(row)
    db.flush()
    emit_audit_event(
        workspace_id=workspace.id,
        event_type="experience.released",
        actor=actor or "unknown",
        agent_id=experience.id,
        details={
            "experience_id": experience.id,
            "release_id": row.id,
            "release_number": row.release_number,
            "content_sha256": row.content_sha256,
        },
        db=db,
    )
    return row


def list_releases(
    db: DBSession, *, workspace_id: str, experience_id: str
) -> list[ExperienceRelease]:
    _owned(db, workspace_id=workspace_id, experience_id=experience_id)
    return (
        db.query(ExperienceRelease)
        .filter(
            ExperienceRelease.experience_id == experience_id,
            ExperienceRelease.workspace_id == workspace_id,
        )
        .order_by(ExperienceRelease.release_number.desc())
        .all()
    )


def _channel(value: str) -> str:
    if value not in DEPLOYMENT_CHANNELS:
        raise ExperienceError(
            code="EXPERIENCE_CHANNEL_INVALID",
            message="channel must be pilot or live.",
            status_code=422,
        )
    return value


def deploy(
    db: DBSession,
    *,
    workspace: Any,
    experience_id: str,
    channel: str,
    release_id: str,
    audience: Any,
    actor: str | None,
) -> ExperienceDeployment:
    cleaned_channel = _channel(channel)
    experience = _owned(db, workspace_id=workspace.id, experience_id=experience_id, lock=True)
    release = _owned_release(db, experience=experience, release_id=release_id)
    cleaned_audience = _validate_audience(audience)
    now = datetime.utcnow()
    row = (
        db.query(ExperienceDeployment)
        .filter(
            ExperienceDeployment.experience_id == experience.id,
            ExperienceDeployment.channel == cleaned_channel,
        )
        .populate_existing()
        .with_for_update(of=ExperienceDeployment)
        .one_or_none()
    )
    if row is None:
        row = ExperienceDeployment(
            id=str(uuid4()),
            experience_id=experience.id,
            workspace_id=experience.workspace_id,
            channel=cleaned_channel,
            release_id=release.id,
            previous_release_id=None,
            audience=cleaned_audience,
            updated_by=actor,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        if row.release_id != release.id:
            row.previous_release_id = row.release_id
            row.release_id = release.id
        row.audience = cleaned_audience
        row.updated_by = actor
        row.updated_at = now
    db.flush()
    emit_audit_event(
        workspace_id=workspace.id,
        event_type="experience.deployed",
        actor=actor or "unknown",
        agent_id=experience.id,
        details={
            "experience_id": experience.id,
            "channel": cleaned_channel,
            "release_id": release.id,
            "release_number": release.release_number,
        },
        db=db,
    )
    return row


def rollback_deployment(
    db: DBSession,
    *,
    workspace: Any,
    experience_id: str,
    channel: str,
    release_id: str | None,
    actor: str | None,
) -> ExperienceDeployment:
    cleaned_channel = _channel(channel)
    experience = _owned(db, workspace_id=workspace.id, experience_id=experience_id, lock=True)
    row = (
        db.query(ExperienceDeployment)
        .filter(
            ExperienceDeployment.experience_id == experience.id,
            ExperienceDeployment.workspace_id == experience.workspace_id,
            ExperienceDeployment.channel == cleaned_channel,
        )
        .populate_existing()
        .with_for_update(of=ExperienceDeployment)
        .one_or_none()
    )
    if row is None:
        raise ExperienceError(
            code="EXPERIENCE_DEPLOYMENT_NOT_FOUND",
            message="No deployment exists for this channel.",
            status_code=404,
        )
    target_id = (release_id or "").strip() or row.previous_release_id
    if not target_id:
        raise ExperienceError(
            code="EXPERIENCE_NO_PREVIOUS_RELEASE",
            message="No previous release is recorded for this channel.",
            status_code=409,
        )
    if target_id == row.release_id:
        return row
    release = _owned_release(db, experience=experience, release_id=target_id)
    row.previous_release_id = row.release_id
    row.release_id = release.id
    row.updated_by = actor
    row.updated_at = datetime.utcnow()
    db.flush()
    emit_audit_event(
        workspace_id=workspace.id,
        event_type="experience.rolled_back",
        actor=actor or "unknown",
        agent_id=experience.id,
        details={
            "experience_id": experience.id,
            "channel": cleaned_channel,
            "release_id": release.id,
            "from_release_id": row.previous_release_id,
        },
        db=db,
    )
    return row


def delete_experience(
    db: DBSession, *, workspace_id: str, experience_id: str, actor: str | None = None
) -> None:
    row = _owned(db, workspace_id=workspace_id, experience_id=experience_id, lock=True)
    live = (
        db.query(ExperienceDeployment)
        .filter(
            ExperienceDeployment.experience_id == row.id,
            ExperienceDeployment.channel == "live",
        )
        .one_or_none()
    )
    if live is not None:
        raise ExperienceError(
            code="EXPERIENCE_LIVE_DEPLOYED",
            message="An experience with a live deployment cannot be deleted.",
            status_code=409,
            details={"release_id": live.release_id},
        )
    emit_audit_event(
        workspace_id=workspace_id,
        event_type="experience.deleted",
        actor=actor or "unknown",
        agent_id=row.id,
        details={"experience_id": row.id, "slug": row.slug},
        db=db,
    )
    db.delete(row)
    db.flush()
