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
    ExperienceDraftHistory,
    ExperienceDraftRevision,
    ExperienceRelease,
)
from app.models.system_binding import SystemBinding
from app.services.audit_logger import emit_audit_event
from app.services.experience import bindings as binding_service
from app.services.flow_contracts import (
    FlowContractError,
    validate_payload,
)
from app.services.flow_contracts import (
    canonical_sha256 as schema_sha256,
)

SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{0,119}$")
EMBLEM_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
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
DATA_LED_PATTERNS = frozenset({"queue", "approval", "dashboard", "mission_cockpit"})
DATA_BOUND_COMPONENT_TYPES = frozenset(
    {
        "result",
        "table",
        "queue",
        "approval_card",
        "runtime_status",
        "evidence",
        "history",
        "kpi",
        "map_panel",
        "agenda_panel",
        "intelligence_feed",
        "decision_queue",
    }
)
QUERY_BOUND_COMPONENT_TYPES = frozenset(
    {
        "table",
        "queue",
        "approval_card",
        "history",
        "kpi",
        "map_panel",
        "agenda_panel",
        "intelligence_feed",
        "decision_queue",
    }
)
IMPLICIT_ACTION_COMPONENT_TYPES = frozenset({"result", "runtime_status", "evidence"})
EMPTY_PAGES = {"pages": []}
AUDIENCE_KEYS = frozenset({"roles", "role_templates", "groups"})
VISIBLE_COPY_KEYS = frozenset(
    {
        "title",
        "subtitle",
        "description",
        "body",
        "label",
        "caption",
        "submitLabel",
        "emptyTitle",
        "emptyText",
        "ariaLabel",
        "keyboardHint",
        "prompt",
        "status",
    }
)


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
        "description": row.description,
        "emblem": row.emblem,
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


def serialize_draft_history(row: ExperienceDraftHistory) -> dict[str, Any]:
    return {
        "id": row.id,
        "experience_id": row.experience_id,
        "revision": row.revision,
        "pages": copy.deepcopy(row.pages or EMPTY_PAGES),
        "binding_keys": list(row.binding_keys or []),
        "content_sha256": row.content_sha256,
        "saved_by": row.saved_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
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
        "previous_audience": copy.deepcopy(row.previous_audience),
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


def _validate_description(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ExperienceError(
            code="EXPERIENCE_DESCRIPTION_INVALID",
            message="description must be text.",
            status_code=422,
        )
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > 500:
        raise ExperienceError(
            code="EXPERIENCE_DESCRIPTION_INVALID",
            message="description must contain at most 500 characters.",
            status_code=422,
        )
    return cleaned


def _validate_emblem(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ExperienceError(
            code="EXPERIENCE_EMBLEM_INVALID",
            message="emblem must be a safe identifier or short glyph.",
            status_code=422,
        )
    cleaned = value.strip()
    if not cleaned:
        return None
    is_identifier = bool(EMBLEM_ID_RE.fullmatch(cleaned))
    forbidden = set('<>/\\:\"\'&')
    is_glyph = (
        len(cleaned) <= 8
        and not forbidden.intersection(cleaned)
        and all(not character.isalnum() and not character.isspace() for character in cleaned)
    )
    if len(cleaned) > 32 or not (is_identifier or is_glyph):
        raise ExperienceError(
            code="EXPERIENCE_EMBLEM_INVALID",
            message="emblem must be a safe identifier or a glyph of at most 8 characters.",
            status_code=422,
        )
    return cleaned


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
    languages = [item.strip().lower() for item in value]
    if len(languages) != len(set(languages)) or any(item not in {"fr", "en"} for item in languages):
        raise ExperienceError(
            code="EXPERIENCE_LANGUAGES_INVALID",
            message="Experience Studio currently supports unique fr/en language codes only.",
            status_code=422,
        )
    return languages


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


def _audience_is_within(candidate: Mapping[str, Any], release: Mapping[str, Any]) -> bool:
    """Return whether a channel audience can only narrow the release audience."""
    release_roles = set(release.get("roles") or [])
    release_groups = set(release.get("groups") or [])
    if not release_roles and not release_groups:
        return True
    candidate_roles = set(candidate.get("roles") or [])
    candidate_groups = set(candidate.get("groups") or [])
    if not candidate_roles and not candidate_groups:
        return False
    return candidate_roles <= release_roles and candidate_groups <= release_groups


def _audience_intersection(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Return a representable audience intersection; ``None`` means deny-all."""
    left_roles = list(left.get("roles") or [])
    left_groups = list(left.get("groups") or [])
    right_roles = list(right.get("roles") or [])
    right_groups = list(right.get("groups") or [])
    if not left_roles and not left_groups:
        return copy.deepcopy(dict(right))
    if not right_roles and not right_groups:
        return copy.deepcopy(dict(left))
    right_role_set = set(right_roles)
    right_group_set = set(right_groups)
    roles = [item for item in left_roles if item in right_role_set]
    groups = [item for item in left_groups if item in right_group_set]
    if not roles and not groups:
        return None
    result: dict[str, Any] = {}
    if roles:
        result["roles"] = roles
    if groups:
        result["groups"] = groups
    return result


def _pilot_rollback_audience(
    row: ExperienceDeployment,
    *,
    target_release_id: str,
    target_release_audience: Mapping[str, Any],
) -> dict[str, Any]:
    current = _validate_audience(row.audience)
    desired: dict[str, Any] = copy.deepcopy(dict(target_release_audience))
    if row.previous_release_id == target_release_id and row.previous_audience is not None:
        try:
            desired = _validate_audience(row.previous_audience)
        except ExperienceError as exc:
            raise ExperienceError(
                code="EXPERIENCE_PREVIOUS_AUDIENCE_INVALID",
                message="The stored previous pilot audience is invalid.",
                status_code=409,
            ) from exc
    safe = _audience_intersection(current, desired)
    if safe is not None:
        safe = _audience_intersection(safe, target_release_audience)
    if safe is None:
        raise ExperienceError(
            code="EXPERIENCE_ROLLBACK_AUDIENCE_DISJOINT",
            message="Rollback cannot preserve a non-widening pilot audience.",
            status_code=409,
            details={"release_id": target_release_id},
        )
    return safe


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
    role_allowed = role in allowed_roles or (
        role == "workspace_owner" and "workspace_admin" in allowed_roles
    )
    return role_allowed or bool(allowed_groups.intersection(groups))


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


def release_identity(release: ExperienceRelease) -> dict[str, Any]:
    """Return the immutable public identity or fail closed on corrupt evidence."""
    raw = release.identity_snapshot
    if not isinstance(raw, Mapping):
        raw = {}
    name = raw.get("name")
    description = raw.get("description")
    emblem = raw.get("emblem")
    slug = raw.get("slug")
    pattern = raw.get("pattern")
    try:
        cleaned_description = _validate_description(description)
        cleaned_emblem = _validate_emblem(emblem)
    except ExperienceError:
        cleaned_description = cleaned_emblem = object()
    if (
        not isinstance(name, str)
        or not name.strip()
        or name != name.strip()
        or cleaned_description != description
        or cleaned_emblem != emblem
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
    return {
        "name": name,
        "description": cleaned_description,
        "emblem": cleaned_emblem,
        "slug": slug,
        "pattern": str(pattern),
    }


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
    description: Any = None,
    emblem: Any = None,
) -> tuple[Experience, ExperienceDraftRevision]:
    cleaned_name = (name or "").strip()
    if not cleaned_name:
        raise ExperienceError(
            code="EXPERIENCE_NAME_INVALID",
            message="name is required.",
            status_code=422,
        )
    cleaned_slug = _validate_slug(slug)
    cleaned_description = _validate_description(description)
    cleaned_emblem = _validate_emblem(emblem)
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
        description=cleaned_description,
        emblem=cleaned_emblem,
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
    history = ExperienceDraftHistory(
        id=str(uuid4()),
        experience_id=row.id,
        workspace_id=workspace.id,
        revision=1,
        pages=copy.deepcopy(pages),
        binding_keys=list(keys),
        content_sha256=draft.content_sha256,
        saved_by=actor,
        created_at=now,
    )
    db.add(row)
    db.add(draft)
    db.add(history)
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
    expected_updated_at: datetime | None = None,
    description: Any = None,
    emblem: Any = None,
    set_description: bool = False,
    set_emblem: bool = False,
    actor: str | None = None,
) -> Experience:
    row = _owned(db, workspace_id=workspace_id, experience_id=experience_id, lock=True)
    before = {
        "name": row.name,
        "description": row.description,
        "emblem": row.emblem,
        "slug": row.slug,
        "pattern": row.pattern,
        "languages": copy.deepcopy(row.languages or []),
        "theme": copy.deepcopy(row.theme or {}),
        "access_policy": copy.deepcopy(row.access_policy or {}),
    }
    if expected_updated_at is not None and row.updated_at != expected_updated_at:
        unchanged = (
            (name is None or row.name == name.strip())
            and (not set_description or row.description == _validate_description(description))
            and (not set_emblem or row.emblem == _validate_emblem(emblem))
            and (slug is None or row.slug == _validate_slug(slug))
            and (pattern is None or row.pattern == _validate_pattern(pattern))
            and (languages is None or row.languages == _validate_languages(languages))
            and (theme is None or row.theme == _validate_theme(theme))
            and (access_policy is None or row.access_policy == _validate_audience(access_policy))
        )
        if unchanged:
            return row
        raise ExperienceError(
            code="EXPERIENCE_METADATA_CONFLICT",
            message="The application access or presentation changed; reload before saving.",
            status_code=409,
            details={
                "expected_updated_at": expected_updated_at.isoformat(),
                "current_updated_at": row.updated_at.isoformat() if row.updated_at else None,
            },
        )
    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise ExperienceError(
                code="EXPERIENCE_NAME_INVALID",
                message="name is required.",
                status_code=422,
            )
        row.name = cleaned
    if set_description:
        row.description = _validate_description(description)
    if set_emblem:
        row.emblem = _validate_emblem(emblem)
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
    after = {
        "name": row.name,
        "description": row.description,
        "emblem": row.emblem,
        "slug": row.slug,
        "pattern": row.pattern,
        "languages": copy.deepcopy(row.languages or []),
        "theme": copy.deepcopy(row.theme or {}),
        "access_policy": copy.deepcopy(row.access_policy or {}),
    }
    changes = {
        field: {"from": before[field], "to": after[field]}
        for field in before
        if before[field] != after[field]
    }
    if not changes:
        return row
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
    audit_details: dict[str, Any] = {
        "experience_id": row.id,
        "changed_fields": sorted(changes),
    }
    if "access_policy" in changes:
        audit_details["access_policy"] = changes["access_policy"]
    emit_audit_event(
        workspace_id=workspace_id,
        event_type="experience.updated",
        actor=actor or "unknown",
        agent_id=row.id,
        details=audit_details,
        db=db,
    )
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
    referenced_binding_keys(document)
    digest = content_sha256(document, keys)
    draft = _draft_for(db, experience)
    if draft.content_sha256 == digest and draft.pages == document and list(draft.binding_keys or []) == keys:
        return draft
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
    draft.pages = document
    draft.binding_keys = keys
    draft.content_sha256 = digest
    draft.revision = int(draft.revision) + 1
    draft.updated_by = actor
    draft.updated_at = datetime.utcnow()
    db.add(
        ExperienceDraftHistory(
            id=str(uuid4()),
            experience_id=experience.id,
            workspace_id=workspace_id,
            revision=draft.revision,
            pages=copy.deepcopy(document),
            binding_keys=list(keys),
            content_sha256=digest,
            saved_by=actor,
            created_at=draft.updated_at,
        )
    )
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


def list_draft_history(
    db: DBSession,
    *,
    workspace_id: str,
    experience_id: str,
) -> list[ExperienceDraftHistory]:
    _owned(db, workspace_id=workspace_id, experience_id=experience_id)
    return (
        db.query(ExperienceDraftHistory)
        .filter(
            ExperienceDraftHistory.workspace_id == workspace_id,
            ExperienceDraftHistory.experience_id == experience_id,
        )
        .order_by(ExperienceDraftHistory.revision.desc())
        .all()
    )


def restore_draft_history(
    db: DBSession,
    *,
    workspace_id: str,
    experience_id: str,
    revision: int,
    expected_revision: int,
    actor: str | None,
) -> ExperienceDraftRevision:
    experience = _owned(
        db,
        workspace_id=workspace_id,
        experience_id=experience_id,
        lock=True,
    )
    draft = _draft_for(db, experience)
    target = (
        db.query(ExperienceDraftHistory)
        .filter(
            ExperienceDraftHistory.workspace_id == workspace_id,
            ExperienceDraftHistory.experience_id == experience_id,
            ExperienceDraftHistory.revision == revision,
        )
        .one_or_none()
    )
    if target is None:
        raise ExperienceError(
            code="EXPERIENCE_DRAFT_REVISION_NOT_FOUND",
            message="Draft revision not found.",
            status_code=404,
            details={"revision": revision},
        )
    if int(draft.revision) != expected_revision:
        raise ExperienceError(
            code="EXPERIENCE_DRAFT_REVISION_CONFLICT",
            message="The draft changed; reload it before restoring a revision.",
            status_code=409,
            details={
                "expected_revision": expected_revision,
                "current_revision": int(draft.revision),
            },
        )
    restored_from = int(target.revision)
    draft.revision = int(draft.revision) + 1
    draft.pages = copy.deepcopy(target.pages)
    draft.binding_keys = list(target.binding_keys or [])
    draft.content_sha256 = target.content_sha256
    draft.updated_by = actor
    draft.updated_at = datetime.utcnow()
    db.add(
        ExperienceDraftHistory(
            id=str(uuid4()),
            experience_id=experience.id,
            workspace_id=workspace_id,
            revision=draft.revision,
            pages=copy.deepcopy(draft.pages),
            binding_keys=list(draft.binding_keys or []),
            content_sha256=draft.content_sha256,
            saved_by=actor,
            created_at=draft.updated_at,
        )
    )
    db.flush()
    emit_audit_event(
        workspace_id=workspace_id,
        event_type="experience.draft_restored",
        actor=actor or "unknown",
        agent_id=experience.id,
        details={
            "experience_id": experience.id,
            "restored_from_revision": restored_from,
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


def referenced_binding_keys(pages: Mapping[str, Any]) -> list[str]:
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


def _form_copy_issues(pages: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Require explicit localized presentation for every visible form string."""
    missing: list[str] = []

    def option_key(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    def require_ref(value: Any, *, path: str) -> None:
        if (
            isinstance(value, Mapping)
            and isinstance(value.get("$i18n"), str)
            and bool(value["$i18n"].strip())
            and isinstance(value.get("fallback"), str)
            and bool(value["fallback"].strip())
        ):
            return
        missing.append(path)

    for page_index, page in enumerate(pages.get("pages") or []):
        if not isinstance(page, Mapping):
            continue
        for component_index, component in enumerate(page.get("components") or []):
            if not isinstance(component, Mapping) or component.get("type") != "form":
                continue
            props = component.get("props")
            if not isinstance(props, Mapping):
                continue
            schema = props.get("schema")
            properties = schema.get("properties") if isinstance(schema, Mapping) else None
            if not isinstance(properties, Mapping):
                continue
            presentation = props.get("fieldPresentation")
            presentation = presentation if isinstance(presentation, Mapping) else {}
            base_path = f"pages[{page_index}].components[{component_index}].props.fieldPresentation"
            for field, raw_schema in properties.items():
                if not isinstance(field, str) or not isinstance(raw_schema, Mapping):
                    continue
                field_copy = presentation.get(field)
                field_copy = field_copy if isinstance(field_copy, Mapping) else {}
                require_ref(
                    field_copy.get("label"),
                    path=f"{base_path}.{field}.label",
                )
                if (
                    isinstance(raw_schema.get("description"), str)
                    and bool(raw_schema["description"].strip())
                ) or "description" in field_copy:
                    require_ref(
                        field_copy.get("description"),
                        path=f"{base_path}.{field}.description",
                    )
                enum = raw_schema.get("enum")
                if not isinstance(enum, list):
                    continue
                options = field_copy.get("options")
                options = options if isinstance(options, Mapping) else {}
                for option in enum:
                    key = option_key(option)
                    require_ref(
                        options.get(key),
                        path=f"{base_path}.{field}.options.{key}",
                    )
    if not missing:
        return []
    return [
        {
            "code": "FORM_COPY_INCOMPLETE",
            "message": "Every visible form field needs localized presentation copy.",
            "paths": missing,
        }
    ]


def _visible_copy_issues(pages: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Reject raw authored UI copy when more than one language is declared."""
    paths: list[str] = []

    def inspect(value: Any, *, path: str) -> None:
        if isinstance(value, str) and value.strip():
            paths.append(path)

    for page_index, page in enumerate(pages.get("pages") or []):
        if not isinstance(page, Mapping):
            continue
        page_path = f"pages[{page_index}]"
        inspect(page.get("title"), path=f"{page_path}.title")
        page_props = page.get("props")
        if isinstance(page_props, Mapping):
            for key in VISIBLE_COPY_KEYS:
                inspect(page_props.get(key), path=f"{page_path}.props.{key}")
        for component_index, component in enumerate(page.get("components") or []):
            if not isinstance(component, Mapping):
                continue
            props = component.get("props")
            if not isinstance(props, Mapping):
                continue
            base = f"{page_path}.components[{component_index}].props"
            for key in VISIBLE_COPY_KEYS:
                inspect(props.get(key), path=f"{base}.{key}")
            a11y = props.get("a11y")
            if isinstance(a11y, Mapping):
                for key in ("ariaLabel", "emptyText", "keyboardHint"):
                    inspect(a11y.get(key), path=f"{base}.a11y.{key}")
            columns = props.get("columns")
            if isinstance(columns, list):
                for index, column in enumerate(columns):
                    if isinstance(column, Mapping):
                        inspect(
                            column.get("label"),
                            path=f"{base}.columns[{index}].label",
                        )
            items = props.get("items")
            if isinstance(items, list):
                for index, item in enumerate(items):
                    inspect(item, path=f"{base}.items[{index}]")
                    if not isinstance(item, Mapping):
                        continue
                    for key in ("title", "label", "name", "detail", "body"):
                        inspect(item.get(key), path=f"{base}.items[{index}].{key}")
    if not paths:
        return []
    return [
        {
            "code": "I18N_VISIBLE_TEXT_UNLOCALIZED",
            "message": "Visible authored copy must use $i18n references for every declared language.",
            "paths": paths,
        }
    ]


def _has_i18n_reference(value: Any) -> bool:
    if isinstance(value, list):
        return any(_has_i18n_reference(item) for item in value)
    if not isinstance(value, Mapping):
        return False
    if isinstance(value.get("$i18n"), str) and bool(value["$i18n"].strip()):
        return True
    return any(
        _has_i18n_reference(item)
        for name, item in value.items()
        if name != "i18n"
    )


def _selector_valid(value: Any) -> bool:
    if value in (None, ""):
        return True
    if not isinstance(value, str) or not SELECTOR_RE.fullmatch(value.strip()):
        return False
    return not {"__proto__", "prototype", "constructor"}.intersection(
        value.strip().split(".")
    )


def _query_binding_valid(component: Mapping[str, Any]) -> bool:
    props = component.get("props")
    query = props.get("queryBinding") if isinstance(props, Mapping) else None
    if not isinstance(query, Mapping):
        return False
    key = query.get("bindingKey")
    return (
        component.get("type") in QUERY_BOUND_COMPONENT_TYPES
        and not (set(query) - {"source", "bindingKey", "selector", "input"})
        and query.get("source") == "system-binding"
        and isinstance(key, str)
        and bool(binding_service.BINDING_KEY_RE.fullmatch(key.strip()))
        and isinstance(query.get("input"), Mapping)
        and _selector_valid(query.get("selector"))
    )


def _bound_action(component: Mapping[str, Any] | None) -> bool:
    if not isinstance(component, Mapping):
        return False
    props = component.get("props")
    if component.get("type") in {"form", "action_button"} and isinstance(props, Mapping):
        key = props.get("bindingKey")
        return isinstance(key, str) and bool(
            binding_service.BINDING_KEY_RE.fullmatch(key.strip())
        )
    return _query_binding_valid(component)


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
            if "queryBinding" in props and "dataBinding" in props:
                issues.append(
                    {
                        "code": "DATA_SOURCE_CONFLICT",
                        "message": "A component must use either queryBinding or dataBinding, not both.",
                        "component_id": component_id,
                    }
                )
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
                    if not _query_binding_valid(component):
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
                    if (
                        unknown
                        or component.get("type") not in DATA_BOUND_COMPONENT_TYPES
                        or data.get("source") != "run-output"
                        or not isinstance(source_id, str)
                        or not source_id.strip()
                        or not _bound_action(source)
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
                if not isinstance(source_id, str) or not source_id.strip() or not _bound_action(source):
                    issues.append(
                        {
                            "code": "SOURCE_COMPONENT_INVALID",
                            "message": "sourceComponentId must reference an actionable component on the same page.",
                            "component_id": component_id,
                        }
                    )
    return issues


def _implicit_action_issues(pages: Mapping[str, Any]) -> list[dict[str, Any]]:
    static_props = {"result": "value", "runtime_status": "status", "evidence": "citations"}
    issues: list[dict[str, Any]] = []
    reported_actions: set[str] = set()
    for page in pages.get("pages") or []:
        if not isinstance(page, Mapping):
            continue
        previous: Mapping[str, Any] | None = None
        for component in page.get("components") or []:
            if not isinstance(component, Mapping):
                continue
            if component.get("type") in {"form", "action_button"}:
                previous = component
                if not _bound_action(component):
                    action_id = str(component.get("id") or "")
                    if action_id not in reported_actions:
                        reported_actions.add(action_id)
                        issues.append(
                            {
                                "code": "ACTION_BINDING_MISSING",
                                "message": "A form or action has no executable binding.",
                                "component_id": component.get("id"),
                            }
                        )
                continue
            component_type = component.get("type")
            if component_type not in IMPLICIT_ACTION_COMPONENT_TYPES:
                continue
            props = component.get("props")
            props = props if isinstance(props, Mapping) else {}
            if (
                static_props[component_type] in props
                or "dataBinding" in props
                or "sourceComponentId" in props
            ):
                continue
            if previous is None:
                issues.append(
                    {
                        "code": "ACTION_SOURCE_MISSING",
                        "message": "A runtime output component has no action source.",
                        "component_id": component.get("id"),
                    }
                )
            elif not _bound_action(previous):
                action_id = str(previous.get("id") or "")
                if action_id in reported_actions:
                    continue
                reported_actions.add(action_id)
                issues.append(
                    {
                        "code": "ACTION_BINDING_MISSING",
                        "message": "A referenced form or action has no executable binding.",
                        "component_id": previous.get("id"),
                        "consumer_id": component.get("id"),
                    }
                )
    return issues


def _selected_schema(
    schema: Mapping[str, Any], selector: Any
) -> Mapping[str, Any] | None:
    if selector in (None, ""):
        return schema
    if not isinstance(selector, str) or not _selector_valid(selector):
        return None
    current: Mapping[str, Any] = schema
    for segment in selector.strip().split("."):
        properties = current.get("properties")
        if isinstance(properties, Mapping):
            child = properties.get(segment)
            if isinstance(child, Mapping):
                current = child
                continue
            additional = current.get("additionalProperties", True)
            if additional is False:
                return None
            if isinstance(additional, Mapping):
                current = additional
                continue
            return {}
        items = current.get("items")
        if isinstance(items, Mapping) and segment.isdigit():
            current = items
            continue
        if current.get("type") == "object":
            additional = current.get("additionalProperties", True)
            if additional is False:
                return None
            if isinstance(additional, Mapping):
                current = additional
                continue
            return {}
        # Polymorphic and deliberately open schemas cannot be proven invalid here.
        if not current or any(key in current for key in ("anyOf", "oneOf", "allOf", "$ref")):
            return {}
        return None
    return current


def _selector_matches_schema(schema: Mapping[str, Any], selector: Any) -> bool:
    return _selected_schema(schema, selector) is not None


def _selector_target_compatible(
    component_type: Any, schema: Mapping[str, Any], selector: Any
) -> bool:
    selected = _selected_schema(schema, selector)
    if selected is None or not selected:
        return True
    value_type = selected.get("type")
    if component_type == "approval_card":
        return value_type in (None, "object")
    if component_type == "evidence":
        return value_type in (None, "object", "array")
    if component_type != "table":
        return True
    if value_type is None:
        return True
    if value_type == "object":
        properties = selected.get("properties")
        if not isinstance(properties, Mapping):
            return True
        for key in ("items", "rows", "cases", "requests", "events", "results", "data"):
            candidate = properties.get(key)
            if not isinstance(candidate, Mapping) or candidate.get("type") != "array":
                continue
            items = candidate.get("items")
            return not isinstance(items, Mapping) or items.get("type") in (None, "object")
        return True
    if value_type != "array":
        return False
    items = selected.get("items")
    return not isinstance(items, Mapping) or items.get("type") in (None, "object")


def _form_schema_supported(schema: Mapping[str, Any]) -> bool:
    """Subset faithfully represented by the certified accessible form renderer."""
    supported_root = {
        "$schema", "type", "title", "description", "properties", "required",
        "additionalProperties",
    }
    if set(schema) - supported_root:
        return False
    unsupported_root = {
        "$ref", "oneOf", "anyOf", "allOf", "not", "if", "then", "else",
        "dependentRequired", "patternProperties", "unevaluatedProperties",
        "minProperties", "maxProperties",
    }
    if unsupported_root.intersection(schema):
        return False
    if schema.get("type", "object") != "object":
        return False
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if not isinstance(properties, Mapping) or not isinstance(required, list):
        return False
    if any(not isinstance(item, str) or item not in properties for item in required):
        return False
    unsupported_shape = {"$ref", "oneOf", "anyOf", "allOf", "items", "properties"}
    supported_field_keys = {
        "type", "title", "description", "default", "enum", "format",
        "contentMediaType", "x-file",
    }
    for raw in properties.values():
        if (
            not isinstance(raw, Mapping)
            or unsupported_shape.intersection(raw)
            or set(raw) - supported_field_keys
        ):
            return False
        value_type = raw.get("type", "string")
        if value_type not in {"string", "number", "integer", "boolean"}:
            return False
        field_format = raw.get("format")
        if field_format is not None and field_format not in {"date", "binary"}:
            return False
        if field_format in {"date", "binary"} and value_type != "string":
            return False
        if (
            "contentMediaType" in raw
            and field_format != "binary"
            and raw.get("x-file") is not True
        ):
            return False
        if "x-file" in raw and raw.get("x-file") is not True:
            return False
        enum = raw.get("enum")
        if (
            ("contentMediaType" in raw or raw.get("x-file") is True)
            and field_format not in {None, "binary"}
        ):
            return False
        if (
            (field_format == "binary" or "contentMediaType" in raw or raw.get("x-file") is True)
            and (value_type != "string" or enum is not None)
        ):
            return False
        if enum is not None:
            if not isinstance(enum, list) or not enum:
                return False
            if value_type == "string" and not all(isinstance(item, str) for item in enum):
                return False
            if value_type == "number" and not all(
                isinstance(item, int | float) and not isinstance(item, bool) for item in enum
            ):
                return False
            if value_type == "integer" and not all(
                isinstance(item, int) and not isinstance(item, bool) for item in enum
            ):
                return False
            if value_type == "boolean" and not all(isinstance(item, bool) for item in enum):
                return False
    return True


def _binding_contract_issues(
    pages: Mapping[str, Any], resolved_by_key: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Certify every authored invocation against its published ingress contract."""
    issues: list[dict[str, Any]] = []
    for page in pages.get("pages") or []:
        if not isinstance(page, Mapping):
            continue
        components = [item for item in page.get("components") or [] if isinstance(item, Mapping)]
        by_id = {item.get("id"): item for item in components}
        for component in components:
            props = component.get("props")
            if not isinstance(props, Mapping):
                continue
            component_type = component.get("type")
            key = props.get("bindingKey")
            resolved = resolved_by_key.get(key) if isinstance(key, str) else None
            input_schema = resolved.get("input_schema") if isinstance(resolved, Mapping) else None
            binding = resolved.get("binding") if isinstance(resolved, Mapping) else None
            expected = binding.get("input_schema_sha256") if isinstance(binding, Mapping) else None
            if component_type == "form" and isinstance(expected, str):
                schema = props.get("schema")
                if not isinstance(schema, Mapping) or schema_sha256(schema) != expected:
                    issues.append(
                        {
                            "code": "FORM_SCHEMA_MISMATCH",
                            "message": "The form fields do not match the published ingress contract.",
                            "component_id": component.get("id"),
                            "binding_key": key,
                        }
                    )
                elif not _form_schema_supported(schema):
                    issues.append(
                        {
                            "code": "FORM_SCHEMA_UNSUPPORTED",
                            "message": "The published schema uses fields the certified form renderer cannot represent.",
                            "component_id": component.get("id"),
                            "binding_key": key,
                        }
                    )
            if component_type == "action_button" and isinstance(input_schema, Mapping):
                try:
                    validate_payload(
                        props.get("input", {}),
                        input_schema,
                        code="action_input_schema_mismatch",
                        subject="Action input",
                    )
                except FlowContractError:
                    issues.append(
                        {
                            "code": "ACTION_INPUT_SCHEMA_MISMATCH",
                            "message": "The action input does not match the published ingress contract.",
                            "component_id": component.get("id"),
                            "binding_key": key,
                        }
                    )

            query = props.get("queryBinding")
            if isinstance(query, Mapping):
                query_key = query.get("bindingKey")
                query_resolved = (
                    resolved_by_key.get(query_key) if isinstance(query_key, str) else None
                )
                query_input_schema = (
                    query_resolved.get("input_schema")
                    if isinstance(query_resolved, Mapping)
                    else None
                )
                if isinstance(query_input_schema, Mapping):
                    try:
                        validate_payload(
                            query.get("input", {}),
                            query_input_schema,
                            code="query_input_schema_mismatch",
                            subject="Query input",
                        )
                    except FlowContractError:
                        issues.append(
                            {
                                "code": "QUERY_INPUT_SCHEMA_MISMATCH",
                                "message": "The query input does not match the published ingress contract.",
                                "component_id": component.get("id"),
                                "binding_key": query_key,
                            }
                        )
                output_schema = (
                    query_resolved.get("output_schema")
                    if isinstance(query_resolved, Mapping)
                    else None
                )
                if isinstance(output_schema, Mapping) and not _selector_matches_schema(
                    output_schema, query.get("selector")
                ):
                    issues.append(
                        {
                            "code": "SELECTOR_SCHEMA_MISMATCH",
                            "message": "The selected output path is absent from the published contract.",
                            "component_id": component.get("id"),
                            "binding_key": query_key,
                            "path": query.get("selector"),
                        }
                    )
                elif isinstance(output_schema, Mapping) and not _selector_target_compatible(
                    component_type, output_schema, query.get("selector")
                ):
                    issues.append(
                        {
                            "code": "SELECTOR_TARGET_TYPE_MISMATCH",
                            "message": "The selected output type cannot be rendered by this component.",
                            "component_id": component.get("id"),
                            "binding_key": query_key,
                            "path": query.get("selector"),
                        }
                    )

            data = props.get("dataBinding")
            if not isinstance(data, Mapping):
                continue
            source = by_id.get(data.get("componentId"))
            source_props = source.get("props") if isinstance(source, Mapping) else None
            source_key = source_props.get("bindingKey") if isinstance(source_props, Mapping) else None
            if not isinstance(source_key, str) and isinstance(source_props, Mapping):
                source_query = source_props.get("queryBinding")
                source_key = (
                    source_query.get("bindingKey") if isinstance(source_query, Mapping) else None
                )
            source_resolved = (
                resolved_by_key.get(source_key) if isinstance(source_key, str) else None
            )
            output_schema = (
                source_resolved.get("output_schema")
                if isinstance(source_resolved, Mapping)
                else None
            )
            if isinstance(output_schema, Mapping) and not _selector_matches_schema(
                output_schema, data.get("selector")
            ):
                issues.append(
                    {
                        "code": "SELECTOR_SCHEMA_MISMATCH",
                        "message": "The selected output path is absent from the published contract.",
                        "component_id": component.get("id"),
                        "binding_key": source_key,
                        "path": data.get("selector"),
                    }
                )
            elif isinstance(output_schema, Mapping) and not _selector_target_compatible(
                component_type, output_schema, data.get("selector")
            ):
                issues.append(
                    {
                        "code": "SELECTOR_TARGET_TYPE_MISMATCH",
                        "message": "The selected output type cannot be rendered by this component.",
                        "component_id": component.get("id"),
                        "binding_key": source_key,
                        "path": data.get("selector"),
                    }
                )
    return issues


def _has_template_data_source(pages: Mapping[str, Any]) -> bool:
    for page in pages.get("pages") or []:
        if not isinstance(page, Mapping):
            continue
        for component in page.get("components") or []:
            if not isinstance(component, Mapping) or component.get("type") not in DATA_BOUND_COMPONENT_TYPES:
                continue
            props = component.get("props")
            if isinstance(props, Mapping) and (
                isinstance(props.get("dataBinding"), Mapping)
                or isinstance(props.get("queryBinding"), Mapping)
            ):
                return True
    return False


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
    if not experience.languages:
        blockers.append(
            {
                "code": "LANGUAGES_REQUIRED",
                "message": "Choose at least one language before creating a release.",
            }
        )
    access_policy = experience.access_policy if isinstance(experience.access_policy, dict) else {}
    has_explicit_open_access = "roles" in access_policy or "role_templates" in access_policy
    has_restricted_access = bool(access_policy.get("roles") or access_policy.get("role_templates") or access_policy.get("groups"))
    if not has_explicit_open_access and not has_restricted_access:
        blockers.append(
            {
                "code": "ACCESS_POLICY_REQUIRED",
                "message": "Choose an explicit audience before creating a release.",
            }
        )
    referenced_keys = referenced_binding_keys(pages)
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
    resolved_by_key: dict[str, Mapping[str, Any]] = {}
    for key in dict.fromkeys(referenced_keys + declared_keys):
        resolved, issue = _resolve_referenced(db, workspace=workspace, key=key)
        if issue is not None:
            blockers.append(issue)
        elif isinstance(resolved, Mapping):
            resolved_by_key[key] = resolved
    for key in declared_keys:
        if key not in referenced_keys:
            warnings.append(
                {
                    "code": "BINDING_UNUSED",
                    "message": "A declared binding is not referenced by a component.",
                    "binding_key": key,
                }
            )
    languages = list(experience.languages or [])
    blockers.extend(_i18n_issues(pages, languages))
    if len(languages) > 1:
        blockers.extend(_form_copy_issues(pages))
        blockers.extend(_visible_copy_issues(pages))
    blockers.extend(_data_binding_issues(pages))
    blockers.extend(_implicit_action_issues(pages))
    blockers.extend(_binding_contract_issues(pages, resolved_by_key))
    if experience.pattern in DATA_LED_PATTERNS and not _has_template_data_source(pages):
        blockers.append(
            {
                "code": "TEMPLATE_DATA_SOURCE_MISSING",
                "message": "This application pattern needs a runnable data source.",
            }
        )
    blockers.extend(_after_success_issues(pages))
    accent_blockers, accent_warnings = _accent_issues(pages)
    blockers.extend(accent_blockers)
    warnings.extend(accent_warnings)
    if experience.pattern in EMPTY_STATE_PATTERNS and not _has_empty_state(pages):
        blockers.append(
            {
                "code": "MISSING_EMPTY_STATE",
                "message": "Queue and approval patterns must declare an empty-state.",
            }
        )
    i18n = pages.get("i18n")
    if len(languages) > 1 and (
        not (isinstance(i18n, dict) and i18n) or not _has_i18n_reference(pages)
    ):
        blockers.append(
            {
                "code": "MISSING_I18N",
                "message": "Languages are declared but the draft has no i18n map.",
            }
        )
    elif languages and not (isinstance(i18n, dict) and i18n):
        warnings.append(
            {
                "code": "MISSING_I18N",
                "message": "The declared language uses the document fallback copy.",
            }
        )
    binding_snapshot = [
        _binding_snapshot_item(resolved_by_key[key])
        for key in referenced_keys
        if key in resolved_by_key
    ]
    return {
        "ready": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "bindings": binding_snapshot,
        "bindings_sha256": _canonical_sha256(binding_snapshot),
    }


def _binding_snapshot_item(resolved: Mapping[str, Any]) -> dict[str, Any]:
    binding = resolved.get("binding")
    if not isinstance(binding, Mapping):
        raise ExperienceError(
            code="EXPERIENCE_BINDING_EVIDENCE_INVALID",
            message="Resolved binding evidence is invalid.",
            status_code=409,
        )
    return {
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
        snapshot.append(_binding_snapshot_item(resolved))
    return snapshot


def create_release(
    db: DBSession,
    *,
    workspace: Any,
    experience_id: str,
    notes: str,
    expected_draft_revision: int,
    expected_content_sha256: str,
    expected_experience_updated_at: datetime,
    expected_bindings_sha256: str,
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
    creation_request_sha256 = _canonical_sha256(
        {
            "experience_id": experience.id,
            "notes": cleaned_notes,
            "expected_draft_revision": expected_draft_revision,
            "expected_content_sha256": expected_content_sha256,
            "expected_experience_updated_at": expected_experience_updated_at.isoformat(),
            "expected_bindings_sha256": expected_bindings_sha256,
            "actor": actor,
        }
    )
    existing = (
        db.query(ExperienceRelease)
        .filter(
            ExperienceRelease.experience_id == experience.id,
            ExperienceRelease.creation_request_sha256 == creation_request_sha256,
        )
        .one_or_none()
    )
    if existing is not None:
        return existing
    if experience.updated_at != expected_experience_updated_at:
        raise ExperienceError(
            code="EXPERIENCE_METADATA_CONFLICT",
            message="Experience metadata changed; review it before releasing.",
            status_code=409,
            details={
                "expected_updated_at": expected_experience_updated_at.isoformat(),
                "current_updated_at": experience.updated_at.isoformat(),
            },
        )
    draft = _draft_for(db, experience)
    referenced_keys = referenced_binding_keys(
        draft.pages if isinstance(draft.pages, Mapping) else {}
    )
    if referenced_keys:
        # Ready-check and immutable snapshot must observe the same binding rows.
        # Stable ordering also prevents two concurrent releases deadlocking.
        (
            db.query(SystemBinding)
            .filter(
                SystemBinding.workspace_id == workspace.id,
                SystemBinding.binding_key.in_(sorted(referenced_keys)),
            )
            .order_by(SystemBinding.binding_key)
            .with_for_update()
            .all()
        )
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
    if check["bindings_sha256"] != expected_bindings_sha256:
        raise ExperienceError(
            code="EXPERIENCE_BINDINGS_CONFLICT",
            message="A referenced System binding changed; review it before releasing.",
            status_code=409,
            details={
                "expected_bindings_sha256": expected_bindings_sha256,
                "current_bindings_sha256": check["bindings_sha256"],
            },
        )
    binding_snapshot = _bindings_snapshot(
        db,
        workspace=workspace,
        keys=referenced_binding_keys(draft.pages or EMPTY_PAGES),
    )
    access_snapshot = copy.deepcopy(experience.access_policy or {})
    identity_snapshot = {
        "name": experience.name,
        "description": experience.description,
        "emblem": experience.emblem,
        "slug": experience.slug,
        "pattern": experience.pattern,
    }
    languages_snapshot = copy.deepcopy(experience.languages or [])
    theme_snapshot = copy.deepcopy(experience.theme or {})
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
        creation_request_sha256=creation_request_sha256,
        content_sha256=draft.content_sha256,
        pages=copy.deepcopy(draft.pages),
        bindings_snapshot=binding_snapshot,
        access_snapshot=access_snapshot,
        identity_snapshot=identity_snapshot,
        languages=languages_snapshot,
        theme=theme_snapshot,
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


def _deployment_mutation_sha256(
    *,
    operation: str,
    channel: str,
    release_id: str,
    audience: Mapping[str, Any],
    expected_current_release_id: str | None,
    expected_deployment_updated_at: datetime | None,
) -> str:
    return _canonical_sha256(
        {
            "operation": operation,
            "channel": channel,
            "release_id": release_id,
            "audience": audience,
            "expected_current_release_id": expected_current_release_id,
            "expected_deployment_updated_at": (
                expected_deployment_updated_at.isoformat()
                if expected_deployment_updated_at is not None
                else None
            ),
        }
    )


def deploy(
    db: DBSession,
    *,
    workspace: Any,
    experience_id: str,
    channel: str,
    release_id: str,
    expected_current_release_id: str | None,
    expected_deployment_updated_at: datetime | None,
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
        if not _audience_is_within(cleaned_audience, release_audience):
            raise ExperienceError(
                code="EXPERIENCE_DEPLOYMENT_AUDIENCE_WIDENS_RELEASE",
                message="Pilot audience must be contained by the release access snapshot.",
                status_code=409,
                details={
                    "release_id": release.id,
                    "release_audience": release_audience,
                    "requested_audience": cleaned_audience,
                },
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
    current_release_id = row.release_id if row is not None else None
    current_updated_at = row.updated_at if row is not None else None
    mutation_sha256 = _deployment_mutation_sha256(
        operation="deploy",
        channel=cleaned_channel,
        release_id=release.id,
        audience=cleaned_audience,
        expected_current_release_id=expected_current_release_id,
        expected_deployment_updated_at=expected_deployment_updated_at,
    )
    # Only a persisted receipt proves an exact lost-response retry. State alone
    # is insufficient because an ABA cycle can expose the same release again.
    if (
        row is not None
        and row.last_mutation_sha256 == mutation_sha256
        and row.release_id == release.id
        and row.audience == cleaned_audience
    ):
        return row
    if (
        current_release_id != expected_current_release_id
        or current_updated_at != expected_deployment_updated_at
    ):
        raise ExperienceError(
            code="EXPERIENCE_DEPLOYMENT_CONFLICT",
            message="The deployment changed; refresh before deploying.",
            status_code=409,
            details={
                "expected_current_release_id": expected_current_release_id,
                "current_release_id": current_release_id,
                "expected_deployment_updated_at": (
                    expected_deployment_updated_at.isoformat()
                    if expected_deployment_updated_at
                    else None
                ),
                "current_deployment_updated_at": (
                    current_updated_at.isoformat() if current_updated_at else None
                ),
            },
        )
    if row is None:
        row = ExperienceDeployment(
            id=str(uuid4()),
            experience_id=experience.id,
            workspace_id=experience.workspace_id,
            channel=cleaned_channel,
            release_id=release.id,
            previous_release_id=None,
            previous_audience=None,
            audience=cleaned_audience,
            last_mutation_sha256=mutation_sha256,
            updated_by=actor,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        if row.release_id != release.id:
            row.previous_release_id = row.release_id
            row.previous_audience = copy.deepcopy(row.audience or {})
            row.release_id = release.id
        row.audience = cleaned_audience
        row.last_mutation_sha256 = mutation_sha256
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
    release_id: str,
    expected_current_release_id: str,
    expected_deployment_updated_at: datetime,
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
    target_id = release_id.strip()
    expected_current_id = expected_current_release_id.strip()
    release = _owned_release(db, experience=experience, release_id=target_id)
    identity = release_identity(release)
    if identity["slug"] != experience.slug:
        raise ExperienceError(
            code="EXPERIENCE_RELEASE_IDENTITY_STALE",
            message="This release was created for a different URL slug.",
            status_code=409,
            details={"release_id": release.id},
        )
    release_audience = _validate_audience(release.access_snapshot)
    target_audience = (
        _pilot_rollback_audience(
            row,
            target_release_id=target_id,
            target_release_audience=release_audience,
        )
        if cleaned_channel == "pilot"
        else release_audience
    )
    mutation_sha256 = _deployment_mutation_sha256(
        operation="rollback",
        channel=cleaned_channel,
        release_id=target_id,
        audience=target_audience,
        expected_current_release_id=expected_current_id,
        expected_deployment_updated_at=expected_deployment_updated_at,
    )
    if (
        row.last_mutation_sha256 == mutation_sha256
        and row.release_id == target_id
        and row.audience == target_audience
    ):
        return row
    if (
        row.release_id != expected_current_id
        or row.updated_at != expected_deployment_updated_at
    ):
        raise ExperienceError(
            code="EXPERIENCE_DEPLOYMENT_CONFLICT",
            message="The deployment changed; refresh before rolling back.",
            status_code=409,
            details={
                "expected_current_release_id": expected_current_id,
                "current_release_id": row.release_id,
                "expected_deployment_updated_at": expected_deployment_updated_at.isoformat(),
                "current_deployment_updated_at": row.updated_at.isoformat(),
            },
        )
    previous_release_id = row.release_id
    previous_audience = copy.deepcopy(row.audience or {})
    row.previous_release_id = previous_release_id
    row.previous_audience = previous_audience
    row.release_id = release.id
    row.audience = target_audience
    row.last_mutation_sha256 = mutation_sha256
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
    release = (
        db.query(ExperienceRelease)
        .filter(
            ExperienceRelease.experience_id == row.id,
            ExperienceRelease.workspace_id == workspace_id,
        )
        .order_by(ExperienceRelease.release_number.desc())
        .first()
    )
    if release is not None:
        raise ExperienceError(
            code="EXPERIENCE_RELEASED",
            message="A released experience cannot be deleted.",
            status_code=409,
            details={
                "release_id": release.id,
                "release_number": release.release_number,
            },
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
