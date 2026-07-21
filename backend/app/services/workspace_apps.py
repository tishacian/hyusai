"""Workspace Apps & Integrations toggles.

Persists enablement under ``workspace.settings["apps"]["enabled"]``. Wired apps
also sync into ``catalog.enabled_skills`` (and advertise their connector) so the
Flow Builder / skill registry see them. Catalog-only apps are intent flags only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Sequence

from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm.attributes import flag_modified

if TYPE_CHECKING:
    from app.models.workspace import Workspace

# Backend-known app definitions. Frontend may list additional catalog-only cards;
# enablement for unknown ids is still accepted and stored.
WIRED_APPS: dict[str, dict[str, Any]] = {
    "rpa_bridge": {
        "id": "rpa_bridge",
        "name": "RPA Bridge",
        "description": (
            "Dispatch jobs to an external RPA orchestrator via generic REST "
            "(UiPath, Power Automate, or custom runner)."
        ),
        "wiring": "wired",
        "status": "beta",
        "skills": ["rpa_dispatch_v1"],
        "connector": "rpa_bridge",
        "connector_route": "/connectors/rpa-bridge",
        "feature_flag": "rpa_bridge",
    },
}

CATALOG_APP_IDS: frozenset[str] = frozenset(
    {
        "web_search",
        "code_interpreter",
        "sql_query",
        "api_connector",
        "email_sender",
        "file_generator",
        "calendar_access",
        "memory",
    }
)


def _as_dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _string_list(value: object) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                continue
            key = item.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(key)
        return out
    return []


def _normalize_enabled(value: object) -> list[str]:
    """Accept list[str] or {id: bool} maps; return sorted unique enabled ids."""
    if isinstance(value, Mapping):
        enabled = [str(k).strip() for k, v in value.items() if v and str(k).strip()]
        return sorted(set(enabled))
    return sorted(set(_string_list(value)))


def read_enabled_app_ids(workspace: "Workspace") -> list[str]:
    settings = _as_dict(workspace.settings)
    apps = _as_dict(settings.get("apps"))
    return _normalize_enabled(apps.get("enabled"))


def app_wiring(app_id: str) -> str:
    return "wired" if app_id in WIRED_APPS else "catalog"


def _skills_for_apps(app_ids: Iterable[str]) -> list[str]:
    skills: list[str] = []
    seen: set[str] = set()
    for app_id in app_ids:
        meta = WIRED_APPS.get(app_id)
        if not meta:
            continue
        for slug in meta.get("skills") or []:
            if slug in seen:
                continue
            seen.add(slug)
            skills.append(slug)
    return skills


def _sync_catalog_skills(
    settings: dict[str, Any],
    *,
    previously_enabled: Sequence[str],
    newly_enabled: Sequence[str],
) -> None:
    """Add skills for newly enabled wired apps; drop skills only owned by disabled ones."""
    catalog = _as_dict(settings.get("catalog"))
    enabled_skills = _string_list(catalog.get("enabled_skills"))
    skill_set = set(enabled_skills)

    prev_skills = set(_skills_for_apps(previously_enabled))
    next_skills = set(_skills_for_apps(newly_enabled))

    for slug in next_skills - prev_skills:
        if slug not in skill_set:
            enabled_skills.append(slug)
            skill_set.add(slug)

    remove = prev_skills - next_skills
    if remove:
        enabled_skills = [s for s in enabled_skills if s not in remove]

    catalog["enabled_skills"] = enabled_skills
    settings["catalog"] = catalog


def describe_app(app_id: str, *, enabled: bool) -> dict[str, Any]:
    wired = WIRED_APPS.get(app_id)
    if wired:
        return {
            **wired,
            "enabled": enabled,
        }
    return {
        "id": app_id,
        "name": app_id.replace("_", " ").title(),
        "description": "",
        "wiring": "catalog",
        "status": "ready",
        "skills": [],
        "connector": None,
        "connector_route": None,
        "enabled": enabled,
    }


def list_workspace_apps(workspace: "Workspace") -> dict[str, Any]:
    enabled = read_enabled_app_ids(workspace)
    enabled_set = set(enabled)

    # Known catalog + wired ids first (stable order), then any extra enabled ids.
    known_ids = list(WIRED_APPS.keys()) + sorted(CATALOG_APP_IDS)
    extras = [app_id for app_id in enabled if app_id not in WIRED_APPS and app_id not in CATALOG_APP_IDS]
    ordered = known_ids + extras

    apps = [describe_app(app_id, enabled=app_id in enabled_set) for app_id in ordered]
    wired_enabled = sum(1 for a in apps if a["wiring"] == "wired" and a["enabled"])
    catalog_enabled = sum(1 for a in apps if a["wiring"] == "catalog" and a["enabled"])

    return {
        "enabled": enabled,
        "apps": apps,
        "wired_count": sum(1 for a in apps if a["wiring"] == "wired"),
        "wired_enabled_count": wired_enabled,
        "catalog_enabled_count": catalog_enabled,
        "has_wired_apps": any(a["wiring"] == "wired" for a in apps),
    }


def set_enabled_apps(
    db: DBSession,
    workspace: "Workspace",
    enabled: object,
) -> dict[str, Any]:
    previous = read_enabled_app_ids(workspace)
    next_enabled = _normalize_enabled(enabled)

    settings = _as_dict(workspace.settings)
    apps_blob = _as_dict(settings.get("apps"))
    apps_blob["enabled"] = next_enabled
    apps_blob["updated_at"] = datetime.now(timezone.utc).isoformat()
    settings["apps"] = apps_blob

    _sync_catalog_skills(
        settings,
        previously_enabled=previous,
        newly_enabled=next_enabled,
    )

    workspace.settings = settings
    flag_modified(workspace, "settings")
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return list_workspace_apps(workspace)
