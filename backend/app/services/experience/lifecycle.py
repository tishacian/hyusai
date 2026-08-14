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
DOCUMENT_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,159}$")
SELECTOR_RE = re.compile(r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*$")
HEX_COLOR_RE = re.compile(r"^#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$")
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
AUDIENCE_KEYS = frozenset({"roles", "role_templates", "groups"})


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
        "access_policy": copy.deepcopy(row.access_policy or {}),
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
        "identity_snapshot": copy.deepcopy(row.identity_snapshot or {}),
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
    unknown = set(value) - AUDIENCE_KEYS
    if unknown or ("roles" in value and "role_templates" in value):
        raise ExperienceError(
            code="EXPERIENCE_AUDIENCE_INVALID",
            message="audience accepts roles (or role_templates) and groups only.",
            status_code=422,
            details={"fields": sorted(unknown)},
        )
    normalized: dict[str, list[str]] = {}
    for source, target in (("roles", "roles"), ("role_templates", "roles"), ("groups", "groups")):
        if source not in value:
            continue
        raw = value[source]
        if not isinstance(raw, list) or any(
            not isinstance(item, str) or not item.strip() for item in raw
        ):
            raise ExperienceError(
                code="EXPERIENCE_AUDIENCE_INVALID",
                message=f"audience.{source} must be an array of non-empty strings.",
                status_code=422,
                details={"field": source},
            )
        normalized[target] = list(dict.fromkeys(item.strip() for item in raw))
    return normalized


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


def _text_value(value: Any) -> bool:
    return bool(
        (isinstance(value, str) and value.strip())
        or (isinstance(value, Mapping) and "$i18n" in value)
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
    page_ids: set[str] = set()
    component_ids: set[str] = set()
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
        page_id = page["id"].strip()
        if not DOCUMENT_ID_RE.fullmatch(page_id):
            raise ExperienceError(
                code="DRAFT_PAGE_ID_INVALID",
                message="Page ids must be safe URL and DOM identifiers.",
                status_code=422,
                details={"path": path, "id": page_id},
            )
        if page_id in page_ids:
            raise ExperienceError(
                code="DRAFT_PAGE_ID_DUPLICATE",
                message="Page ids must be unique.",
                status_code=422,
                details={"path": path, "id": page_id},
            )
        page_ids.add(page_id)
        if not _text_value(page.get("title")):
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
            component_id = component.get("id")
            if not isinstance(component_id, str) or not component_id.strip():
                raise ExperienceError(
                    code="DRAFT_COMPONENT_ID_REQUIRED",
                    message="Each component must have a stable id.",
                    status_code=422,
                    details={"path": c_path},
                )
            component_id = component_id.strip()
            if not DOCUMENT_ID_RE.fullmatch(component_id):
                raise ExperienceError(
                    code="DRAFT_COMPONENT_ID_INVALID",
                    message="Component ids must be safe DOM identifiers.",
                    status_code=422,
                    details={"path": c_path, "id": component_id},
                )
            if component_id in component_ids:
                raise ExperienceError(
                    code="DRAFT_COMPONENT_ID_DUPLICATE",
                    message="Component ids must be unique across the document.",
                    status_code=422,
                    details={"path": c_path, "id": component_id},
                )
            component_ids.add(component_id)
            _reject_absolute_positioning(component, path=c_path)
            cleaned_component = copy.deepcopy(component)
            cleaned_component["id"] = component_id
            props = cleaned_component.get("props")
            if isinstance(props, dict):
                if isinstance(props.get("accent"), str):
                    props["accent"] = props["accent"].strip()
                if isinstance(props.get("bindingKey"), str):
                    props["bindingKey"] = props["bindingKey"].strip()
                query = props.get("queryBinding")
                if isinstance(query, dict):
                    if isinstance(query.get("bindingKey"), str):
                        query["bindingKey"] = query["bindingKey"].strip()
                    if isinstance(query.get("selector"), str):
                        query["selector"] = query["selector"].strip()
                data = props.get("dataBinding")
                if isinstance(data, dict):
                    if isinstance(data.get("componentId"), str):
                        data["componentId"] = data["componentId"].strip()
                    if isinstance(data.get("selector"), str):
                        data["selector"] = data["selector"].strip()
                if isinstance(props.get("sourceComponentId"), str):
                    props["sourceComponentId"] = props["sourceComponentId"].strip()
            cleaned_components.append(cleaned_component)
        cleaned = copy.deepcopy(page)
        cleaned["id"] = page_id
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


def audience_allows(
    audience: Any,
    role: str,
    groups: tuple[str, ...] | list[str] | set[str] = (),
) -> bool:
    """Return membership in a valid deployment audience; malformed data closes."""
    if not isinstance(audience, dict) or set(audience) - AUDIENCE_KEYS:
        return False
    if "roles" in audience and "role_templates" in audience:
        return False
    role_values = audience.get("roles", audience.get("role_templates", []))
    group_values = audience.get("groups", [])
    if not isinstance(role_values, list) or not isinstance(group_values, list):
        return False
    if any(
        not isinstance(item, str) or not item.strip() or item != item.strip()
        for item in role_values + group_values
    ):
        return False
    allowed_roles = {item.strip() for item in role_values}
    allowed_groups = {item.strip() for item in group_values}
    if not allowed_roles and not allowed_groups:
        return True
    return role in allowed_roles or bool(allowed_groups.intersection(groups))


def _pick_work_release(
    db: DBSession,
    *,
    experience: Experience,
    deployments: list[ExperienceDeployment],
    role: str,
    groups: tuple[str, ...] = (),
) -> tuple[ExperienceDeployment, ExperienceRelease] | None:
    """Pilot overrides Live only when both release and deployment allow it."""
    by_channel = {item.channel: item for item in deployments}
    for channel in ("pilot", "live"):
        deployment = by_channel.get(channel)
        if deployment is None or not audience_allows(deployment.audience, role, groups):
            continue
        release = _owned_release(db, experience=experience, release_id=deployment.release_id)
        if audience_allows(release.access_snapshot, role, groups):
            return deployment, release
    return None


def release_identity(release: ExperienceRelease) -> dict[str, str]:
    """Return the immutable public identity or fail closed on corrupt evidence."""
    raw = release.identity_snapshot
    if not isinstance(raw, Mapping):
        raw = {}
    name = raw.get("name")
    slug = raw.get("slug")
    pattern = raw.get("pattern")
    if (
        not isinstance(name, str)
        or not name.strip()
        or name != name.strip()
        or not isinstance(slug, str)
        or not SLUG_RE.fullmatch(slug)
        or pattern not in EXPERIENCE_PATTERNS
    ):
        raise ExperienceError(
            code="EXPERIENCE_RELEASE_IDENTITY_INVALID",
            message="The deployed release contains an invalid identity snapshot.",
            status_code=409,
            details={"release_id": release.id},
        )
    return {"name": name, "slug": slug, "pattern": str(pattern)}


def resolve_work(
    db: DBSession,
    *,
    workspace_id: str,
    slug: str,
    role: str,
    groups: tuple[str, ...] = (),
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
    selected = _pick_work_release(
        db,
        experience=row,
        deployments=_deployments_for(
            db, workspace_id=workspace_id, experience_id=row.id
        ),
        role=role,
        groups=groups,
    )
    if selected is None:
        raise ExperienceError(
            code="EXPERIENCE_NOT_FOUND",
            message="Experience not found.",
            status_code=404,
        )
    chosen, release = selected
    identity = release_identity(release)
    if identity["slug"] != slug or identity["slug"] != row.slug:
        raise ExperienceError(
            code="EXPERIENCE_NOT_FOUND",
            message="Experience not found.",
            status_code=404,
        )
    return row, chosen, release


def list_work(
    db: DBSession,
    *,
    workspace_id: str,
    role: str,
    groups: tuple[str, ...] = (),
) -> list[tuple[Experience, ExperienceDeployment, ExperienceRelease]]:
    """Return only deployments consumable by the caller."""
    result: list[tuple[Experience, ExperienceDeployment, ExperienceRelease]] = []
    deployments = list_deployments_for_workspace(db, workspace_id=workspace_id)
    by_experience: dict[str, list[ExperienceDeployment]] = {}
    for item in deployments:
        by_experience.setdefault(item.experience_id, []).append(item)
    for experience in list_experiences(db, workspace_id=workspace_id):
        selected = _pick_work_release(
            db,
            experience=experience,
            deployments=by_experience.get(experience.id, []),
            role=role,
            groups=groups,
        )
        if selected is None:
            continue
        chosen, release = selected
        try:
            identity = release_identity(release)
        except ExperienceError:
            continue
        if identity["slug"] != experience.slug:
            continue
        result.append((experience, chosen, release))
    return result


def serialize_work(
    experience: Experience,
    deployment: ExperienceDeployment,
    release: ExperienceRelease,
) -> dict[str, Any]:
    identity = release_identity(release)
    public_bindings = [
        {
            "binding_key": item.get("binding_key"),
            "confirmation_policy": item.get("confirmation_policy"),
            "on_unavailable": item.get("on_unavailable"),
        }
        for item in release.bindings_snapshot or []
        if isinstance(item, Mapping)
    ]
    return {
        "experience": {
            "id": experience.id,
            **identity,
        },
        "channel": deployment.channel,
        "release": {
            "id": release.id,
            "pages": copy.deepcopy(release.pages),
            "bindings_snapshot": public_bindings,
            "languages": copy.deepcopy(release.languages or []),
            "theme": copy.deepcopy(release.theme or {}),
            "renderer_version": release.renderer_version,
        },
    }


def serialize_public_binding_resolution(resolved: Mapping[str, Any]) -> dict[str, Any]:
    binding = resolved.get("binding") if isinstance(resolved.get("binding"), Mapping) else {}
    return {
        "status": resolved.get("status"),
        "reasons": list(resolved.get("reasons") or []),
        "binding": {
            "binding_key": binding.get("binding_key"),
            "confirmation_policy": binding.get("confirmation_policy"),
            "on_unavailable": binding.get("on_unavailable"),
        },
    }


def serialize_work_catalog_item(
    experience: Experience,
    deployment: ExperienceDeployment,
    release: ExperienceRelease,
) -> dict[str, Any]:
    """Safe launcher projection: no author draft or executable document."""
    identity = release_identity(release)
    return {
        "experience": {
            "id": experience.id,
            **identity,
            "languages": copy.deepcopy(release.languages or []),
            "theme": copy.deepcopy(release.theme or {}),
        },
        "channel": deployment.channel,
        "release": {
            "id": release.id,
            "release_number": release.release_number,
            "languages": copy.deepcopy(release.languages or []),
            "theme": copy.deepcopy(release.theme or {}),
            "renderer_version": release.renderer_version,
        },
    }


def work_binding_snapshot(release: ExperienceRelease, *, binding_key: str) -> dict[str, Any]:
    key = (binding_key or "").strip()
    if not binding_service.BINDING_KEY_RE.fullmatch(key):
        raise ExperienceError(
            code="BINDING_KEY_INVALID",
            message="binding_key must be a lowercase dotted identifier.",
            status_code=422,
        )
    for item in release.bindings_snapshot or []:
        if isinstance(item, Mapping) and item.get("binding_key") == key:
            return copy.deepcopy(dict(item))
    raise ExperienceError(
        code="EXPERIENCE_BINDING_NOT_RELEASED",
        message="The binding is not part of this deployed release.",
        status_code=404,
        details={"binding_key": key, "release_id": release.id},
    )


def work_binding_context(
    release: ExperienceRelease,
    *,
    binding_key: str,
    page_id: str | None,
    component_id: str | None,
) -> tuple[str, str]:
    matches: list[tuple[str, str]] = []
    pages = release.pages if isinstance(release.pages, Mapping) else {}
    for page in pages.get("pages") or []:
        if not isinstance(page, Mapping):
            continue
        current_page_id = page.get("id")
        for component in page.get("components") or []:
            if not isinstance(component, Mapping):
                continue
            props = component.get("props")
            if not isinstance(props, Mapping):
                continue
            query = props.get("queryBinding")
            references = props.get("bindingKey") == binding_key or (
                isinstance(query, Mapping) and query.get("bindingKey") == binding_key
            )
            if not references:
                continue
            current_component_id = component.get("id")
            if isinstance(current_page_id, str) and isinstance(current_component_id, str):
                matches.append((current_page_id, current_component_id))
    if page_id is not None or component_id is not None:
        candidate = (page_id or "", component_id or "")
        if candidate not in matches:
            raise ExperienceError(
                code="EXPERIENCE_BINDING_CONTEXT_INVALID",
                message="The component does not reference this released binding.",
                status_code=422,
                details={"binding_key": binding_key},
            )
        return candidate
    if len(matches) == 1:
        return matches[0]
    raise ExperienceError(
        code="EXPERIENCE_BINDING_CONTEXT_REQUIRED",
        message="page_id and component_id are required for this binding.",
        status_code=422,
        details={"binding_key": binding_key, "references": len(matches)},
    )


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
    access_policy: Any,
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
    cleaned_access_policy = _validate_audience(access_policy)
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
        access_policy=cleaned_access_policy,
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
    access_policy: Any = None,
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
        deployment = (
            db.query(ExperienceDeployment)
            .filter(
                ExperienceDeployment.experience_id == row.id,
                ExperienceDeployment.workspace_id == workspace_id,
            )
            .first()
        )
        if deployment is not None and cleaned_slug != row.slug:
            raise ExperienceError(
                code="EXPERIENCE_DEPLOYED_SLUG_IMMUTABLE",
                message="The URL slug cannot change while this experience is deployed.",
                status_code=409,
                details={
                    "slug": row.slug,
                    "channel": deployment.channel,
                    "release_id": deployment.release_id,
                },
            )
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
    if access_policy is not None:
        row.access_policy = _validate_audience(access_policy)
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
    expected_revision: int,
    actor: str | None,
) -> ExperienceDraftRevision:
    experience = _owned(db, workspace_id=workspace_id, experience_id=experience_id, lock=True)
    document = validate_pages_document(pages)
    keys = _validate_binding_keys(binding_keys)
    _component_binding_keys(document)
    digest = content_sha256(document, keys)
    draft = _draft_for(db, experience)
    if int(draft.revision) != expected_revision:
        raise ExperienceError(
            code="EXPERIENCE_DRAFT_REVISION_CONFLICT",
            message="The draft changed; reload it before saving.",
            status_code=409,
            details={
                "expected_revision": expected_revision,
                "current_revision": int(draft.revision),
            },
        )
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


def _component_binding_keys(pages: Mapping[str, Any]) -> list[str]:
    """Binding references in stable document order, without trusting the side list."""
    seen: set[str] = set()
    result: list[str] = []
    for page in pages.get("pages") or []:
        if not isinstance(page, Mapping):
            continue
        for component in page.get("components") or []:
            if not isinstance(component, Mapping):
                continue
            props = component.get("props")
            if not isinstance(props, Mapping):
                continue
            query = props.get("queryBinding")
            raw_values = [props.get("bindingKey")]
            if isinstance(query, Mapping):
                raw_values.append(query.get("bindingKey"))
            for raw in raw_values:
                if raw in (None, ""):
                    continue
                if not isinstance(raw, str) or not binding_service.BINDING_KEY_RE.fullmatch(raw.strip()):
                    raise ExperienceError(
                        code="COMPONENT_BINDING_KEY_INVALID",
                        message="A component bindingKey is invalid.",
                        status_code=422,
                        details={"component_id": component.get("id")},
                    )
                key = raw.strip()
                if key not in seen:
                    seen.add(key)
                    result.append(key)
    return result


def _i18n_issues(pages: Mapping[str, Any], languages: list[str]) -> list[dict[str, Any]]:
    dictionaries = pages.get("i18n") if isinstance(pages.get("i18n"), Mapping) else {}
    issues: list[dict[str, Any]] = []
    refs: list[tuple[str, str]] = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")
            return
        if not isinstance(value, Mapping):
            return
        if "$i18n" in value:
            key = value.get("$i18n")
            fallback = value.get("fallback")
            if not isinstance(key, str) or not key.strip() or not isinstance(fallback, str) or not fallback.strip():
                issues.append(
                    {
                        "code": "I18N_REFERENCE_INVALID",
                        "message": "Localized text requires non-empty $i18n and fallback.",
                        "path": path,
                    }
                )
                return
            refs.append((key.strip(), path))
            return
        for name, item in value.items():
            if name != "i18n":
                visit(item, f"{path}.{name}" if path else str(name))

    visit(pages, "")
    for key, path in refs:
        for language in languages:
            exact = dictionaries.get(language)
            base = dictionaries.get(language.lower().split("-", 1)[0])
            translated = (
                exact.get(key)
                if isinstance(exact, Mapping) and key in exact
                else base.get(key)
                if isinstance(base, Mapping)
                else None
            )
            if not isinstance(translated, str) or not translated.strip():
                issues.append(
                    {
                        "code": "I18N_TRANSLATION_MISSING",
                        "message": "A localized text is missing a declared-language translation.",
                        "path": path,
                        "key": key,
                        "language": language,
                    }
                )
    return issues


def _selector_valid(value: Any) -> bool:
    if value in (None, ""):
        return True
    if not isinstance(value, str) or not SELECTOR_RE.fullmatch(value.strip()):
        return False
    return not {"__proto__", "prototype", "constructor"}.intersection(
        value.strip().split(".")
    )


def _data_binding_issues(pages: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for page in pages.get("pages") or []:
        if not isinstance(page, Mapping):
            continue
        components = [item for item in page.get("components") or [] if isinstance(item, Mapping)]
        by_id = {item.get("id"): item for item in components}
        for component in components:
            component_id = component.get("id")
            props = component.get("props")
            if not isinstance(props, Mapping):
                continue
            query = props.get("queryBinding")
            if "queryBinding" in props:
                if not isinstance(query, Mapping):
                    issues.append(
                        {
                            "code": "QUERY_BINDING_INVALID",
                            "message": "queryBinding must be an object.",
                            "component_id": component_id,
                        }
                    )
                else:
                    unknown = set(query) - {"source", "bindingKey", "selector", "input"}
                    query_key = query.get("bindingKey")
                    if (
                        unknown
                        or query.get("source") != "system-binding"
                        or not isinstance(query_key, str)
                        or not binding_service.BINDING_KEY_RE.fullmatch(query_key.strip())
                        or not isinstance(query.get("input"), Mapping)
                        or not _selector_valid(query.get("selector"))
                    ):
                        issues.append(
                            {
                                "code": "QUERY_BINDING_INVALID",
                                "message": "queryBinding has an invalid closed contract.",
                                "component_id": component_id,
                                "fields": sorted(unknown),
                            }
                        )
            data = props.get("dataBinding")
            if "dataBinding" in props:
                if not isinstance(data, Mapping):
                    issues.append(
                        {
                            "code": "DATA_BINDING_INVALID",
                            "message": "dataBinding must be an object.",
                            "component_id": component_id,
                        }
                    )
                else:
                    unknown = set(data) - {"source", "componentId", "selector"}
                    source_id = data.get("componentId")
                    source = by_id.get(source_id) if isinstance(source_id, str) else None
                    source_props = source.get("props") if isinstance(source, Mapping) else None
                    actionable = isinstance(source, Mapping) and (
                        source.get("type") in {"form", "action_button"}
                        or (isinstance(source_props, Mapping) and isinstance(source_props.get("queryBinding"), Mapping))
                    )
                    if (
                        unknown
                        or data.get("source") != "run-output"
                        or not isinstance(source_id, str)
                        or not source_id.strip()
                        or not actionable
                        or not _selector_valid(data.get("selector"))
                    ):
                        issues.append(
                            {
                                "code": "DATA_BINDING_INVALID",
                                "message": "dataBinding must reference an actionable component on the same page.",
                                "component_id": component_id,
                                "fields": sorted(unknown),
                            }
                        )
            source_id = props.get("sourceComponentId")
            if source_id is not None:
                source = by_id.get(source_id) if isinstance(source_id, str) else None
                source_props = source.get("props") if isinstance(source, Mapping) else None
                actionable = isinstance(source, Mapping) and (
                    source.get("type") in {"form", "action_button"}
                    or (isinstance(source_props, Mapping) and isinstance(source_props.get("queryBinding"), Mapping))
                )
                if not isinstance(source_id, str) or not source_id.strip() or not actionable:
                    issues.append(
                        {
                            "code": "SOURCE_COMPONENT_INVALID",
                            "message": "sourceComponentId must reference an actionable component on the same page.",
                            "component_id": component_id,
                        }
                    )
    return issues


def _after_success_issues(pages: Mapping[str, Any]) -> list[dict[str, Any]]:
    page_ids = {
        page.get("id")
        for page in pages.get("pages") or []
        if isinstance(page, Mapping) and isinstance(page.get("id"), str)
    }
    issues: list[dict[str, Any]] = []
    for page in pages.get("pages") or []:
        if not isinstance(page, Mapping):
            continue
        for component in page.get("components") or []:
            if not isinstance(component, Mapping):
                continue
            props = component.get("props")
            if not isinstance(props, Mapping) or "afterSuccess" not in props:
                continue
            outcome = props.get("afterSuccess")
            if isinstance(outcome, str) and outcome in {"stay", "result", "reset"}:
                continue
            if isinstance(outcome, str) and outcome.startswith("page:"):
                target_page_id = outcome.removeprefix("page:")
                if not DOCUMENT_ID_RE.fullmatch(target_page_id):
                    issues.append(
                        {
                            "code": "AFTER_SUCCESS_INVALID",
                            "message": "afterSuccess page targets must use a safe page id.",
                            "component_id": component.get("id"),
                            "after_success": outcome,
                        }
                    )
                elif target_page_id not in page_ids:
                    issues.append(
                        {
                            "code": "AFTER_SUCCESS_PAGE_MISSING",
                            "message": "afterSuccess must target a page in the same release.",
                            "component_id": component.get("id"),
                            "target_page_id": target_page_id,
                        }
                    )
                continue
            issues.append(
                {
                    "code": "AFTER_SUCCESS_INVALID",
                    "message": "afterSuccess must be stay, result, reset, or page:<page-id>.",
                    "component_id": component.get("id"),
                }
            )
    return issues


def _hex_luminance(value: str) -> float:
    raw = value[1:]
    if len(raw) == 3:
        raw = "".join(character * 2 for character in raw)
    channels = [int(raw[index : index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [
        channel / 12.92
        if channel <= 0.03928
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(left: float, right: float) -> float:
    return (max(left, right) + 0.05) / (min(left, right) + 0.05)


def _accent_issues(
    pages: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    dark_luminance = _hex_luminance("#0c1014")
    light_luminance = _hex_luminance("#fafaf6")
    for page in pages.get("pages") or []:
        if not isinstance(page, Mapping):
            continue
        page_props = page.get("props")
        raw_theme = page_props.get("theme") if isinstance(page_props, Mapping) else None
        theme = raw_theme if raw_theme in {"light", "dark"} else "inherit"
        for component in page.get("components") or []:
            if not isinstance(component, Mapping):
                continue
            props = component.get("props")
            if not isinstance(props, Mapping) or "accent" not in props:
                continue
            accent = props.get("accent")
            if not isinstance(accent, str) or not HEX_COLOR_RE.fullmatch(accent):
                blockers.append(
                    {
                        "code": "ACCENT_COLOR_INVALID",
                        "message": "Component accent must be a 3- or 6-digit hex color.",
                        "page_id": page.get("id"),
                        "component_id": component.get("id"),
                    }
                )
                continue
            luminance = _hex_luminance(accent)
            weak_dark = _contrast(luminance, dark_luminance) < 3
            weak_light = _contrast(luminance, light_luminance) < 3
            if (
                (theme == "dark" and weak_dark)
                or (theme == "light" and weak_light)
                or (theme == "inherit" and (weak_dark or weak_light))
            ):
                warnings.append(
                    {
                        "code": "ACCENT_CONTRAST_LOW",
                        "message": "Component accent has less than 3:1 UI contrast.",
                        "page_id": page.get("id"),
                        "component_id": component.get("id"),
                        "accent": accent,
                        "theme": theme,
                    }
                )
    return blockers, warnings


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
    referenced_keys = _component_binding_keys(pages)
    declared_keys = list(draft.binding_keys or [])
    for key in referenced_keys:
        if key not in declared_keys:
            blockers.append(
                {
                    "code": "COMPONENT_BINDING_UNLISTED",
                    "message": "A component references a binding outside the draft binding list.",
                    "binding_key": key,
                }
            )
    for key in dict.fromkeys(referenced_keys + declared_keys):
        _resolved, issue = _resolve_referenced(db, workspace=workspace, key=key)
        if issue is not None:
            blockers.append(issue)
    for key in declared_keys:
        if key not in referenced_keys:
            warnings.append(
                {
                    "code": "BINDING_UNUSED",
                    "message": "A declared binding is not referenced by a component.",
                    "binding_key": key,
                }
            )
    blockers.extend(_i18n_issues(pages, list(experience.languages or [])))
    blockers.extend(_data_binding_issues(pages))
    blockers.extend(_after_success_issues(pages))
    accent_blockers, accent_warnings = _accent_issues(pages)
    blockers.extend(accent_blockers)
    warnings.extend(accent_warnings)
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
    expected_draft_revision: int,
    expected_content_sha256: str,
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
    if int(draft.revision) != expected_draft_revision:
        raise ExperienceError(
            code="EXPERIENCE_DRAFT_REVISION_CONFLICT",
            message="The draft changed; review it before releasing.",
            status_code=409,
            details={
                "expected_revision": expected_draft_revision,
                "current_revision": int(draft.revision),
            },
        )
    if draft.content_sha256 != expected_content_sha256:
        raise ExperienceError(
            code="EXPERIENCE_DRAFT_CONTENT_CONFLICT",
            message="The draft content changed; review it before releasing.",
            status_code=409,
            details={
                "expected_content_sha256": expected_content_sha256,
                "current_content_sha256": draft.content_sha256,
            },
        )
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
            db,
            workspace=workspace,
            keys=_component_binding_keys(draft.pages or EMPTY_PAGES),
        ),
        access_snapshot=copy.deepcopy(experience.access_policy or {}),
        identity_snapshot={
            "name": experience.name,
            "slug": experience.slug,
            "pattern": experience.pattern,
        },
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
    identity = release_identity(release)
    if identity["slug"] != experience.slug:
        raise ExperienceError(
            code="EXPERIENCE_RELEASE_IDENTITY_STALE",
            message="This release was created for a different URL slug.",
            status_code=409,
            details={
                "release_id": release.id,
                "release_slug": identity["slug"],
                "current_slug": experience.slug,
            },
        )
    release_audience = _validate_audience(release.access_snapshot)
    if cleaned_channel == "live":
        if audience is not None and _validate_audience(audience) != release_audience:
            raise ExperienceError(
                code="EXPERIENCE_LIVE_AUDIENCE_IMMUTABLE",
                message="Live audience is frozen by the release access snapshot.",
                status_code=409,
                details={"release_id": release.id},
            )
        cleaned_audience = release_audience
    else:
        cleaned_audience = _validate_audience(
            release.access_snapshot if audience is None else audience
        )
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
    identity = release_identity(release)
    if identity["slug"] != experience.slug:
        raise ExperienceError(
            code="EXPERIENCE_RELEASE_IDENTITY_STALE",
            message="This release was created for a different URL slug.",
            status_code=409,
            details={"release_id": release.id},
        )
    row.previous_release_id = row.release_id
    row.release_id = release.id
    if cleaned_channel == "live":
        row.audience = _validate_audience(release.access_snapshot)
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
    deployment = (
        db.query(ExperienceDeployment)
        .filter(
            ExperienceDeployment.experience_id == row.id,
            ExperienceDeployment.workspace_id == workspace_id,
        )
        .first()
    )
    if deployment is not None:
        raise ExperienceError(
            code="EXPERIENCE_DEPLOYED",
            message="A deployed experience cannot be deleted.",
            status_code=409,
            details={"channel": deployment.channel, "release_id": deployment.release_id},
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
