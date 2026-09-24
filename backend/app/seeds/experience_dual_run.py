"""Lot 8 dual-run Experience + binding seeds (Andritz, Sentinel, Octocity, Mission Control).

Data only. Idempotent: skip an Experience when the slug exists; skip a binding
when the key exists. Bindings are created only for a published Flow version.

090/091 call ``seed_dual_run_experiences``. Mission Experiences keep
``theme.live_href`` (immersive shell) and seed certified map/agenda/intel/
decision widgets for Studio and ``/work`` preview.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

import sqlalchemy as sa

from app.services.experience.keys import (
    ANDRITZ_CAPTURE_KEY,
    ANDRITZ_CLIENT360_KEY,
    ANDRITZ_FSE_KEY,
    ANDRITZ_RECHERCHE_KEY,
    ANDRITZ_SLUG,
    CAPTURE_EXPERIENCE_SLUG,
    CLIENT360_EXPERIENCE_SLUG,
    FSE_EXPERIENCE_SLUG,
    MISSION_AGENDA_KEY,
    MISSION_CONTROL_EXPERIENCE_SLUG,
    MISSION_COCKPIT_KEY,
    MISSION_DECISIONS_KEY,
    MISSION_INTELLIGENCE_KEY,
    MISSION_MAP_KEY,
    OCTOCITY_AGENDA_KEY,
    OCTOCITY_COCKPIT_KEY,
    OCTOCITY_DECISIONS_KEY,
    OCTOCITY_EXPERIENCE_SLUG,
    OCTOCITY_INTELLIGENCE_KEY,
    OCTOCITY_MAP_KEY,
    OCTOCITY_PROFILES,
    OCTOCITY_SLUG,
    RECHERCHE_EXPERIENCE_SLUG,
    SENTINEL_AGENDA_KEY,
    SENTINEL_COCKPIT_KEY,
    SENTINEL_DECISIONS_KEY,
    SENTINEL_EXPERIENCE_SLUG,
    SENTINEL_INTELLIGENCE_KEY,
    SENTINEL_MAP_KEY,
    SENTINEL_PROFILES,
    SENTINEL_SLUG,
)

SEED_ORIGIN = "090_xp_dual_run"
RENDERER_VERSION = "certified-components-0.2.0"
FSE_TEMPLATE_ID = "fse_intervention_v1"
CHAT_VARIANT = "chat_transverse_v1"

ANDRITZ_CHAT_NAMES = frozenset({"Andritz Workspace Chat", "Agentium Workspace Chat"})
CLIENT360_NAMES = frozenset({"Client360 PDR"})
CAPTURE_NAMES = frozenset({"Expert Knowledge Capture"})
FSE_NAMES = frozenset({"Rapport d'intervention FSE"})


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return deepcopy(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _content_sha256(pages: dict[str, Any], binding_keys: list[str]) -> str:
    canonical = json.dumps(
        {"binding_keys": binding_keys, "pages": pages},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _tables():
    workspaces = sa.table(
        "workspaces",
        sa.column("id"),
        sa.column("slug"),
        sa.column("settings", sa.JSON()),
    )
    systems = sa.table(
        "systems",
        sa.column("id"),
        sa.column("workspace_id"),
        sa.column("name"),
        sa.column("settings", sa.JSON()),
        sa.column("flow_definition", sa.JSON()),
        sa.column("published_flow_version_id"),
    )
    versions = sa.table(
        "system_versions",
        sa.column("id"),
        sa.column("system_id"),
        sa.column("workspace_id"),
        sa.column("flow_sha256"),
        sa.column("execution_contract", sa.JSON()),
    )
    bindings = sa.table(
        "system_bindings",
        sa.column("id"),
        sa.column("workspace_id"),
        sa.column("binding_key"),
        sa.column("system_id"),
        sa.column("published_flow_version_id"),
        sa.column("flow_sha256"),
        sa.column("ingress_id"),
        sa.column("input_schema_sha256"),
        sa.column("output_schema_sha256"),
        sa.column("confirmation_policy"),
        sa.column("on_unavailable"),
        sa.column("created_by"),
        sa.column("created_at"),
        sa.column("updated_at"),
    )
    experiences = sa.table(
        "experiences",
        sa.column("id"),
        sa.column("workspace_id"),
        sa.column("name"),
        sa.column("slug"),
        sa.column("pattern"),
        sa.column("languages", sa.JSON()),
        sa.column("theme", sa.JSON()),
        sa.column("created_by"),
        sa.column("created_at"),
        sa.column("updated_at"),
    )
    drafts = sa.table(
        "experience_draft_revisions",
        sa.column("experience_id"),
        sa.column("workspace_id"),
        sa.column("revision"),
        sa.column("pages", sa.JSON()),
        sa.column("binding_keys", sa.JSON()),
        sa.column("content_sha256"),
        sa.column("updated_by"),
        sa.column("created_at"),
        sa.column("updated_at"),
    )
    releases = sa.table(
        "experience_releases",
        sa.column("id"),
        sa.column("experience_id"),
        sa.column("workspace_id"),
        sa.column("release_number"),
        sa.column("content_sha256"),
        sa.column("pages", sa.JSON()),
        sa.column("bindings_snapshot", sa.JSON()),
        sa.column("access_snapshot", sa.JSON()),
        sa.column("languages", sa.JSON()),
        sa.column("theme", sa.JSON()),
        sa.column("renderer_version"),
        sa.column("notes"),
        sa.column("created_by"),
        sa.column("created_at"),
    )
    deployments = sa.table(
        "experience_deployments",
        sa.column("id"),
        sa.column("experience_id"),
        sa.column("workspace_id"),
        sa.column("channel"),
        sa.column("release_id"),
        sa.column("previous_release_id"),
        sa.column("audience", sa.JSON()),
        sa.column("updated_by"),
        sa.column("created_at"),
        sa.column("updated_at"),
    )
    return workspaces, systems, versions, bindings, experiences, drafts, releases, deployments


def _pick_ingress(contract: dict[str, Any]) -> dict[str, Any] | None:
    ingresses = [item for item in _as_list(contract.get("ingresses")) if isinstance(item, dict)]
    named = next((item for item in ingresses if item.get("ingress_id") == "source.request"), None)
    if named is not None:
        return named
    return next((item for item in ingresses if item.get("ingress_id")), None)


def _binding_values(
    *,
    workspace_id: str,
    binding_key: str,
    system_id: str,
    version: Any,
    ingress: dict[str, Any],
    now: datetime,
) -> dict[str, Any] | None:
    mapping = version._mapping
    flow_sha256 = mapping["flow_sha256"]
    ingress_id = ingress.get("ingress_id")
    input_sha = ingress.get("input_schema_sha256")
    if not isinstance(flow_sha256, str) or len(flow_sha256) != 64:
        return None
    if not isinstance(ingress_id, str) or not ingress_id:
        return None
    if not isinstance(input_sha, str) or len(input_sha) != 64:
        return None
    outputs = _as_list(_as_dict(mapping["execution_contract"]).get("outputs"))
    output_sha = None
    if len(outputs) == 1 and isinstance(outputs[0], dict):
        digest = outputs[0].get("schema_sha256")
        if isinstance(digest, str) and len(digest) == 64:
            output_sha = digest
    return {
        "id": str(uuid4()),
        "workspace_id": workspace_id,
        "binding_key": binding_key,
        "system_id": system_id,
        "published_flow_version_id": mapping["id"],
        "flow_sha256": flow_sha256,
        "ingress_id": ingress_id,
        "input_schema_sha256": input_sha,
        "output_schema_sha256": output_sha,
        "confirmation_policy": "confirm",
        "on_unavailable": "unavailable",
        "created_by": f"system:{SEED_ORIGIN}",
        "created_at": now,
        "updated_at": now,
    }


def _existing_binding(bind, bindings, *, workspace_id: str, binding_key: str):
    return bind.execute(
        sa.select(
            bindings.c.id,
            bindings.c.system_id,
            bindings.c.published_flow_version_id,
            bindings.c.flow_sha256,
            bindings.c.ingress_id,
            bindings.c.input_schema_sha256,
            bindings.c.output_schema_sha256,
            bindings.c.confirmation_policy,
            bindings.c.on_unavailable,
            bindings.c.binding_key,
        ).where(
            bindings.c.workspace_id == workspace_id,
            bindings.c.binding_key == binding_key,
        )
    ).first()


def _snapshot_from_row(row: Any) -> dict[str, Any]:
    mapping = row._mapping
    return {
        "binding_key": mapping["binding_key"],
        "system_id": mapping["system_id"],
        "published_flow_version_id": mapping["published_flow_version_id"],
        "flow_sha256": mapping["flow_sha256"],
        "ingress_id": mapping["ingress_id"],
        "input_schema_sha256": mapping["input_schema_sha256"],
        "output_schema_sha256": mapping["output_schema_sha256"],
        "confirmation_policy": mapping["confirmation_policy"],
        "on_unavailable": mapping["on_unavailable"],
    }


def _insert_binding_if_missing(
    bind,
    bindings,
    versions,
    *,
    workspace_id: str,
    binding_key: str,
    system: Any,
    now: datetime,
) -> Any:
    already = _existing_binding(bind, bindings, workspace_id=workspace_id, binding_key=binding_key)
    if already:
        return already
    version_id = system["published_flow_version_id"]
    if not version_id:
        return None
    version = bind.execute(
        sa.select(
            versions.c.id,
            versions.c.flow_sha256,
            versions.c.execution_contract,
        ).where(
            versions.c.id == version_id,
            versions.c.system_id == system["id"],
            versions.c.workspace_id == workspace_id,
        )
    ).first()
    if version is None:
        return None
    ingress = _pick_ingress(_as_dict(version._mapping["execution_contract"]))
    if ingress is None:
        return None
    values = _binding_values(
        workspace_id=workspace_id,
        binding_key=binding_key,
        system_id=system["id"],
        version=version,
        ingress=ingress,
        now=now,
    )
    if values is None:
        return None
    bind.execute(sa.insert(bindings).values(**values))
    return _existing_binding(bind, bindings, workspace_id=workspace_id, binding_key=binding_key)


def _slug_exists(bind, experiences, *, workspace_id: str, slug: str) -> bool:
    return (
        bind.execute(
            sa.select(experiences.c.id).where(
                experiences.c.workspace_id == workspace_id,
                experiences.c.slug == slug,
            )
        ).first()
        is not None
    )


def _set_release_identity_if_supported(
    bind,
    *,
    release_id: str,
    name: str,
    slug: str,
    pattern: str,
) -> None:
    """090 has no identity column; 092+ seed calls still write complete evidence."""
    columns = {
        item["name"]
        for item in sa.inspect(bind).get_columns("experience_releases")
    }
    if "identity_snapshot" not in columns:
        return
    releases = sa.table(
        "experience_releases",
        sa.column("id"),
        sa.column("identity_snapshot", sa.JSON()),
    )
    bind.execute(
        releases.update()
        .where(releases.c.id == release_id)
        .values(identity_snapshot={"name": name, "slug": slug, "pattern": pattern})
    )


def _pointer_pages(*, title: str, body: str, href: str) -> dict[str, Any]:
    return {
        "pages": [
            {
                "id": "home",
                "title": title,
                "components": [
                    {
                        "type": "header",
                        "id": "dual-run-head",
                        "props": {"title": title, "subtitle": "Live surface stays on the existing route."},
                    },
                    {
                        "type": "callout",
                        "id": "dual-run-live",
                        "props": {"body": body, "href": href},
                    },
                ],
            }
        ]
    }


def _mission_view_href(href: str, view: str) -> str:
    base = href.rstrip("/")
    if base.endswith("/cockpit"):
        base = base[: -len("/cockpit")]
    if not base:
        return href
    return f"{base}/{view}"


def _certified_mission_pages(
    *,
    title: str,
    body: str,
    href: str,
    map_key: str | None,
    agenda_key: str | None,
    intel_key: str | None,
    decisions_key: str | None,
) -> dict[str, Any]:
    components: list[dict[str, Any]] = [
        {
            "type": "header",
            "id": "mission-head",
            "props": {"title": title, "subtitle": "Certified projection — the immersive shell stays live."},
        },
        {
            "type": "map_panel",
            "id": "mission-map",
            "props": {
                "bindingKey": map_key or "",
                "href": _mission_view_href(href, "strategie"),
            },
        },
        {
            "type": "agenda_panel",
            "id": "mission-agenda",
            "props": {
                "bindingKey": agenda_key or "",
                "href": _mission_view_href(href, "agenda"),
            },
        },
        {
            "type": "intelligence_feed",
            "id": "mission-intel",
            "props": {
                "bindingKey": intel_key or "",
                "href": _mission_view_href(href, "presse"),
            },
        },
        {
            "type": "decision_queue",
            "id": "mission-decisions",
            "props": {
                "bindingKey": decisions_key or "",
                "href": _mission_view_href(href, "decisions"),
            },
        },
        {
            "type": "callout",
            "id": "mission-aya",
            "props": {"body": body, "href": href},
        },
    ]
    return {"pages": [{"id": "cockpit", "title": title, "components": components}]}


def _pages_have_certified_widgets(pages: Any) -> bool:
    for page in _as_list(_as_dict(pages).get("pages")):
        for component in _as_list(_as_dict(page).get("components")):
            if _as_dict(component).get("type") in {
                "map_panel",
                "agenda_panel",
                "intelligence_feed",
                "decision_queue",
            }:
                return True
    return False


def _insert_experience(
    bind,
    experiences,
    drafts,
    releases,
    deployments,
    *,
    workspace_id: str,
    name: str,
    slug: str,
    pattern: str,
    theme: dict[str, Any],
    pages: dict[str, Any],
    binding_keys: list[str],
    bindings_snapshot: list[dict[str, Any]],
    notes: str,
    now: datetime,
) -> None:
    if _slug_exists(bind, experiences, workspace_id=workspace_id, slug=slug):
        return
    experience_id = str(uuid4())
    release_id = str(uuid4())
    digest = _content_sha256(pages, binding_keys)
    actor = f"system:{SEED_ORIGIN}"
    languages = ["fr", "en"]
    bind.execute(
        sa.insert(experiences).values(
            id=experience_id,
            workspace_id=workspace_id,
            name=name,
            slug=slug,
            pattern=pattern,
            languages=languages,
            theme=theme,
            created_by=actor,
            created_at=now,
            updated_at=now,
        )
    )
    bind.execute(
        sa.insert(drafts).values(
            experience_id=experience_id,
            workspace_id=workspace_id,
            revision=1,
            pages=pages,
            binding_keys=binding_keys,
            content_sha256=digest,
            updated_by=actor,
            created_at=now,
            updated_at=now,
        )
    )
    bind.execute(
        sa.insert(releases).values(
            id=release_id,
            experience_id=experience_id,
            workspace_id=workspace_id,
            release_number=1,
            content_sha256=digest,
            pages=pages,
            bindings_snapshot=bindings_snapshot,
            access_snapshot={},
            languages=languages,
            theme=theme,
            renderer_version=RENDERER_VERSION,
            notes=notes,
            created_by=actor,
            created_at=now,
        )
    )
    _set_release_identity_if_supported(
        bind,
        release_id=release_id,
        name=name,
        slug=slug,
        pattern=pattern,
    )
    bind.execute(
        sa.insert(deployments).values(
            id=str(uuid4()),
            experience_id=experience_id,
            workspace_id=workspace_id,
            channel="live",
            release_id=release_id,
            previous_release_id=None,
            audience={},
            updated_by=actor,
            created_at=now,
            updated_at=now,
        )
    )


def _flow_of(row: Any) -> dict[str, Any]:
    return _as_dict(row["flow_definition"])


def _settings_of(row: Any) -> dict[str, Any]:
    return _as_dict(row["settings"])


def _variant(row: Any) -> str:
    return str(_flow_of(row).get("variant") or "")


def _template_id(row: Any) -> str:
    flow = _flow_of(row)
    capture = _as_dict(_settings_of(row).get("capture"))
    return str(flow.get("template_id") or capture.get("template_id") or "")


def _published_systems(bind, systems, workspace_id: str) -> list[Any]:
    return [
        row._mapping
        for row in bind.execute(
            sa.select(
                systems.c.id,
                systems.c.name,
                systems.c.settings,
                systems.c.flow_definition,
                systems.c.published_flow_version_id,
            ).where(systems.c.workspace_id == workspace_id)
        ).all()
        if row._mapping["published_flow_version_id"]
    ]


def _first(rows: list[Any], predicate) -> Any | None:
    return next((row for row in rows if predicate(row)), None)


def _bind_and_keys(bind, bindings, versions, *, workspace_id: str, pairs: list[tuple[str, Any]], now: datetime):
    keys: list[str] = []
    snapshot: list[dict[str, Any]] = []
    for binding_key, system in pairs:
        if system is None:
            continue
        row = _insert_binding_if_missing(
            bind,
            bindings,
            versions,
            workspace_id=workspace_id,
            binding_key=binding_key,
            system=system,
            now=now,
        )
        if row is None:
            continue
        keys.append(binding_key)
        snapshot.append(_snapshot_from_row(row))
    return keys, snapshot


def _seed_pointer(
    bind,
    tables,
    *,
    workspace_id: str,
    name: str,
    slug: str,
    pattern: str,
    href: str,
    body: str,
    pairs: list[tuple[str, Any]],
    notes: str,
    now: datetime,
    pages: dict[str, Any] | None = None,
) -> None:
    _workspaces, _systems, versions, bindings, experiences, drafts, releases, deployments = tables
    keys, snapshot = _bind_and_keys(
        bind, bindings, versions, workspace_id=workspace_id, pairs=pairs, now=now
    )
    _insert_experience(
        bind,
        experiences,
        drafts,
        releases,
        deployments,
        workspace_id=workspace_id,
        name=name,
        slug=slug,
        pattern=pattern,
        theme={"live_href": href, "origin": "existing"},
        pages=pages or _pointer_pages(title=name, body=body, href=href),
        binding_keys=keys,
        bindings_snapshot=snapshot,
        notes=notes,
        now=now,
    )


def _is_andritz_chat(row: Any) -> bool:
    if (row["name"] or "") in ANDRITZ_CHAT_NAMES:
        return True
    if _settings_of(row).get("system_type") == "workspace_chat":
        return True
    return _variant(row) == CHAT_VARIANT


def _is_capture(row: Any) -> bool:
    name = row["name"] or ""
    if name in FSE_NAMES or _template_id(row) == FSE_TEMPLATE_ID:
        return False
    return name in CAPTURE_NAMES or name == "Knowledge Capture"


def _is_fse(row: Any) -> bool:
    if (row["name"] or "") in FSE_NAMES:
        return True
    return _template_id(row) == FSE_TEMPLATE_ID


def _seed_andritz(bind, tables, now: datetime) -> None:
    workspaces, systems, *_rest = tables
    for ws in bind.execute(
        sa.select(workspaces.c.id).where(workspaces.c.slug == ANDRITZ_SLUG)
    ).all():
        workspace_id = ws._mapping["id"]
        published = _published_systems(bind, systems, workspace_id)
        chat = _first(published, _is_andritz_chat)
        client360 = _first(published, lambda row: (row["name"] or "") in CLIENT360_NAMES)
        capture = _first(published, _is_capture)
        fse = _first(published, _is_fse)
        _seed_pointer(
            bind,
            tables,
            workspace_id=workspace_id,
            name="Recherche",
            slug=RECHERCHE_EXPERIENCE_SLUG,
            pattern="assistant",
            href="/chat",
            body="Open search on /chat — this inventory entry does not replace the business shell.",
            pairs=[(ANDRITZ_RECHERCHE_KEY, chat)],
            notes="Lot 8 dual-run: inventory pointer to /chat.",
            now=now,
        )
        _seed_pointer(
            bind,
            tables,
            workspace_id=workspace_id,
            name="Client360 PDR",
            slug=CLIENT360_EXPERIENCE_SLUG,
            pattern="dashboard",
            href="/client360",
            body="Open Client360 PDR on /client360 — this inventory entry does not replace the live UI.",
            pairs=[(ANDRITZ_CLIENT360_KEY, client360)],
            notes="Lot 8 dual-run: inventory pointer to /client360.",
            now=now,
        )
        _seed_pointer(
            bind,
            tables,
            workspace_id=workspace_id,
            name="Capture",
            slug=CAPTURE_EXPERIENCE_SLUG,
            pattern="form_result",
            href="/knowledge/capture",
            body="Open Knowledge Capture on /knowledge/capture — this inventory entry does not replace Le Fil.",
            pairs=[(ANDRITZ_CAPTURE_KEY, capture)],
            notes="Lot 8 dual-run: inventory pointer to /knowledge/capture.",
            now=now,
        )
        _seed_pointer(
            bind,
            tables,
            workspace_id=workspace_id,
            name="Rapport d'intervention FSE",
            slug=FSE_EXPERIENCE_SLUG,
            pattern="form_result",
            href="/knowledge/interventions",
            body="Open FSE reports on /knowledge/interventions — this inventory entry does not replace the capture shell.",
            pairs=[(ANDRITZ_FSE_KEY, fse)],
            notes="Lot 8 dual-run: inventory pointer to /knowledge/interventions.",
            now=now,
        )


def _is_sentinel_cockpit(row: Any) -> bool:
    return _variant(row) == "government_mission_room"


def _is_sentinel_map(row: Any) -> bool:
    return _variant(row) == "territorial_action_map" or (row["name"] or "") == "Carte Strategique Executive"


def _is_sentinel_agenda(row: Any) -> bool:
    return _variant(row) == "government_calendar_assist" or (row["name"] or "") == "Government Calendar Assist"


def _is_sentinel_intelligence(row: Any) -> bool:
    if _template_id(row) == "sentinel-ci-intelligence":
        return True
    return _variant(row) == "intelligence" and "veille" in (row["name"] or "").lower()


def _is_sentinel_decisions(row: Any) -> bool:
    return _variant(row) == "executive_instruction_drafting"


def _seed_sentinel(bind, tables, now: datetime) -> None:
    workspaces, systems, *_rest = tables
    for ws in bind.execute(
        sa.select(workspaces.c.id).where(workspaces.c.slug == SENTINEL_SLUG)
    ).all():
        workspace_id = ws._mapping["id"]
        published = _published_systems(bind, systems, workspace_id)
        map_sys = _first(published, _is_sentinel_map)
        agenda_sys = _first(published, _is_sentinel_agenda)
        intel_sys = _first(published, _is_sentinel_intelligence)
        decisions_sys = _first(published, _is_sentinel_decisions)
        href = "/hypervisor/mission-room/cockpit"
        body = "Open SENTINEL-CI on /hypervisor/mission-room/cockpit — AYA and the immersive shell stay on that route."
        _seed_pointer(
            bind,
            tables,
            workspace_id=workspace_id,
            name="SENTINEL-CI",
            slug=SENTINEL_EXPERIENCE_SLUG,
            pattern="mission_cockpit",
            href=href,
            body=body,
            pairs=[
                (SENTINEL_COCKPIT_KEY, _first(published, _is_sentinel_cockpit)),
                (SENTINEL_MAP_KEY, map_sys),
                (SENTINEL_AGENDA_KEY, agenda_sys),
                (SENTINEL_INTELLIGENCE_KEY, intel_sys),
                (SENTINEL_DECISIONS_KEY, decisions_sys),
            ],
            notes="Lot 8 dual-run: certified Mission widgets; live_href keeps the immersive shell.",
            now=now,
            pages=_certified_mission_pages(
                title="SENTINEL-CI",
                body=body,
                href=href,
                map_key=SENTINEL_MAP_KEY if map_sys else None,
                agenda_key=SENTINEL_AGENDA_KEY if agenda_sys else None,
                intel_key=SENTINEL_INTELLIGENCE_KEY if intel_sys else None,
                decisions_key=SENTINEL_DECISIONS_KEY if decisions_sys else None,
            ),
        )


def _is_octocity_cockpit(row: Any) -> bool:
    return _variant(row) == "octocity_mission_room"


def _is_octocity_map(row: Any) -> bool:
    return _variant(row) == "octocity_territorial_map"


def _is_octocity_agenda(row: Any) -> bool:
    return _variant(row) == "octocity_mission_room"


def _is_octocity_intelligence(row: Any) -> bool:
    return _variant(row) == "octocity_intelligence"


def _is_octocity_decisions(row: Any) -> bool:
    return _variant(row) == "octocity_decision_desk"


def _seed_octocity(bind, tables, now: datetime) -> None:
    workspaces, systems, *_rest = tables
    for ws in bind.execute(
        sa.select(workspaces.c.id).where(workspaces.c.slug == OCTOCITY_SLUG)
    ).all():
        workspace_id = ws._mapping["id"]
        published = _published_systems(bind, systems, workspace_id)
        map_sys = _first(published, _is_octocity_map)
        agenda_sys = _first(published, _is_octocity_agenda)
        intel_sys = _first(published, _is_octocity_intelligence)
        decisions_sys = _first(published, _is_octocity_decisions)
        href = "/hypervisor/mission-room/cockpit"
        body = "Open Octocity on /hypervisor/mission-room/cockpit — same certified widgets as SENTINEL, different branding."
        _seed_pointer(
            bind,
            tables,
            workspace_id=workspace_id,
            name="Octocity",
            slug=OCTOCITY_EXPERIENCE_SLUG,
            pattern="mission_cockpit",
            href=href,
            body=body,
            pairs=[
                (OCTOCITY_COCKPIT_KEY, _first(published, _is_octocity_cockpit)),
                (OCTOCITY_MAP_KEY, map_sys),
                (OCTOCITY_AGENDA_KEY, agenda_sys),
                (OCTOCITY_INTELLIGENCE_KEY, intel_sys),
                (OCTOCITY_DECISIONS_KEY, decisions_sys),
            ],
            notes="Lot 8 dual-run: Octocity uses the same certified widgets as SENTINEL.",
            now=now,
            pages=_certified_mission_pages(
                title="Octocity",
                body=body,
                href=href,
                map_key=OCTOCITY_MAP_KEY if map_sys else None,
                agenda_key=OCTOCITY_AGENDA_KEY if agenda_sys else None,
                intel_key=OCTOCITY_INTELLIGENCE_KEY if intel_sys else None,
                decisions_key=OCTOCITY_DECISIONS_KEY if decisions_sys else None,
            ),
        )


def _mission_profile(settings: dict[str, Any]) -> str:
    mission = _as_dict(settings.get("mission_room"))
    return str(mission.get("profile") or "")


def _is_generic_mission_workspace(settings: dict[str, Any]) -> bool:
    mission = _as_dict(settings.get("mission_room"))
    if mission.get("enabled") is not True:
        return False
    profile = _mission_profile(settings)
    if profile in SENTINEL_PROFILES or profile in OCTOCITY_PROFILES:
        return False
    if profile.startswith("octocity") or profile.startswith("sentinel"):
        return False
    demo = str(settings.get("demo_profile") or "")
    if demo in {"government_mission_room", "octocity_mission_room"}:
        return False
    return True


def _is_generic_cockpit(row: Any) -> bool:
    return _variant(row) == "government_mission_room"


def _is_generic_map(row: Any) -> bool:
    return _variant(row) == "territorial_action_map"


def _is_generic_agenda(row: Any) -> bool:
    return _variant(row) == "government_calendar_assist"


def _is_generic_intelligence(row: Any) -> bool:
    return _variant(row) == "intelligence"


def _is_generic_decisions(row: Any) -> bool:
    return _variant(row) in {"executive_instruction_drafting", "decision_desk"}


def _seed_mission_control(bind, tables, now: datetime) -> None:
    workspaces, systems, *_rest = tables
    for ws in bind.execute(sa.select(workspaces.c.id, workspaces.c.slug, workspaces.c.settings)).all():
        mapping = ws._mapping
        slug = mapping["slug"]
        if slug in {SENTINEL_SLUG, OCTOCITY_SLUG, ANDRITZ_SLUG}:
            continue
        if not _is_generic_mission_workspace(_as_dict(mapping["settings"])):
            continue
        workspace_id = mapping["id"]
        published = _published_systems(bind, systems, workspace_id)
        map_sys = _first(published, _is_generic_map)
        agenda_sys = _first(published, _is_generic_agenda)
        intel_sys = _first(published, _is_generic_intelligence)
        decisions_sys = _first(published, _is_generic_decisions)
        href = "/hypervisor/mission-room"
        body = "Open Mission Control on /hypervisor/mission-room — the immersive shell stays on that route."
        _seed_pointer(
            bind,
            tables,
            workspace_id=workspace_id,
            name="Mission Control",
            slug=MISSION_CONTROL_EXPERIENCE_SLUG,
            pattern="mission_cockpit",
            href=href,
            body=body,
            pairs=[
                (MISSION_COCKPIT_KEY, _first(published, _is_generic_cockpit)),
                (MISSION_MAP_KEY, map_sys),
                (MISSION_AGENDA_KEY, agenda_sys),
                (MISSION_INTELLIGENCE_KEY, intel_sys),
                (MISSION_DECISIONS_KEY, decisions_sys),
            ],
            notes="Lot 8 dual-run: certified Mission widgets; live_href keeps the generic Mission Room.",
            now=now,
            pages=_certified_mission_pages(
                title="Mission Control",
                body=body,
                href=href,
                map_key=MISSION_MAP_KEY if map_sys else None,
                agenda_key=MISSION_AGENDA_KEY if agenda_sys else None,
                intel_key=MISSION_INTELLIGENCE_KEY if intel_sys else None,
                decisions_key=MISSION_DECISIONS_KEY if decisions_sys else None,
            ),
        )


def _upgrade_seed_mission_pages(bind) -> None:
    tables_present = set(sa.inspect(bind).get_table_names())
    if not {
        "experiences",
        "experience_draft_revisions",
        "experience_releases",
        "experience_deployments",
        "system_bindings",
    }.issubset(tables_present):
        return
    _workspaces, _systems, _versions, bindings, experiences, drafts, releases, deployments = _tables()
    actor = f"system:{SEED_ORIGIN}"
    mission_slugs = {
        SENTINEL_EXPERIENCE_SLUG,
        OCTOCITY_EXPERIENCE_SLUG,
        MISSION_CONTROL_EXPERIENCE_SLUG,
    }
    rows = bind.execute(
        sa.select(
            experiences.c.id,
            experiences.c.workspace_id,
            experiences.c.slug,
            experiences.c.name,
            experiences.c.languages,
            experiences.c.theme,
            experiences.c.created_by,
        ).where(
            experiences.c.created_by == actor,
            experiences.c.slug.in_(list(mission_slugs)),
        )
    ).all()
    for row in rows:
        mapping = row._mapping
        draft = bind.execute(
            sa.select(
                drafts.c.pages,
                drafts.c.binding_keys,
                drafts.c.revision,
                drafts.c.updated_by,
            ).where(
                drafts.c.experience_id == mapping["id"]
            )
        ).first()
        if (
            draft is None
            or draft._mapping["updated_by"] != actor
            or _pages_have_certified_widgets(draft._mapping["pages"])
        ):
            continue
        theme = _as_dict(mapping["theme"])
        href = str(theme.get("live_href") or "/hypervisor/mission-room")
        family = (
            "sentinel"
            if mapping["slug"] == SENTINEL_EXPERIENCE_SLUG
            else "octocity"
            if mapping["slug"] == OCTOCITY_EXPERIENCE_SLUG
            else "mission"
        )
        prefix = {"sentinel": "sentinel", "octocity": "octocity", "mission": "mission"}[family]
        desired = [
            f"{prefix}.cockpit",
            f"{prefix}.map",
            f"{prefix}.agenda",
            f"{prefix}.intelligence",
            f"{prefix}.decisions",
        ]
        binding_rows = bind.execute(
            sa.select(
                bindings.c.binding_key,
                bindings.c.system_id,
                bindings.c.published_flow_version_id,
                bindings.c.flow_sha256,
                bindings.c.ingress_id,
                bindings.c.input_schema_sha256,
                bindings.c.output_schema_sha256,
                bindings.c.confirmation_policy,
                bindings.c.on_unavailable,
            ).where(
                bindings.c.workspace_id == mapping["workspace_id"],
                bindings.c.binding_key.in_(desired),
            )
        ).all()
        by_key = {item._mapping["binding_key"]: item for item in binding_rows}
        keys = [key for key in desired if key in by_key]
        key_set = set(keys)
        pages = _certified_mission_pages(
            title=mapping["name"],
            body=f"Open {mapping['name']} on {href} — the immersive shell stays on that route.",
            href=href,
            map_key=f"{prefix}.map" if f"{prefix}.map" in key_set else None,
            agenda_key=f"{prefix}.agenda" if f"{prefix}.agenda" in key_set else None,
            intel_key=f"{prefix}.intelligence" if f"{prefix}.intelligence" in key_set else None,
            decisions_key=f"{prefix}.decisions" if f"{prefix}.decisions" in key_set else None,
        )
        digest = _content_sha256(pages, keys)
        latest = bind.execute(
            sa.select(
                releases.c.id,
                releases.c.release_number,
                releases.c.access_snapshot,
            )
            .where(releases.c.experience_id == mapping["id"])
            .order_by(releases.c.release_number.desc())
        ).first()
        if latest is None:
            continue
        now = datetime.utcnow()
        release_id = str(uuid4())
        bind.execute(
            drafts.update()
            .where(drafts.c.experience_id == mapping["id"])
            .values(
                pages=pages,
                binding_keys=keys,
                content_sha256=digest,
                revision=int(draft._mapping["revision"] or 1) + 1,
                updated_by=actor,
                updated_at=now,
            )
        )
        bind.execute(
            sa.insert(releases).values(
                id=release_id,
                experience_id=mapping["id"],
                workspace_id=mapping["workspace_id"],
                release_number=int(latest._mapping["release_number"]) + 1,
                content_sha256=digest,
                pages=pages,
                bindings_snapshot=[_snapshot_from_row(by_key[key]) for key in keys],
                access_snapshot=_as_dict(latest._mapping["access_snapshot"]),
                languages=_as_list(mapping["languages"]),
                theme=theme,
                renderer_version=RENDERER_VERSION,
                notes="Lot 8 migration: certified Mission widgets (immutable successor release).",
                created_by=actor,
                created_at=now,
            )
        )
        _set_release_identity_if_supported(
            bind,
            release_id=release_id,
            name=mapping["name"],
            slug=mapping["slug"],
            pattern="mission_cockpit",
        )
        bind.execute(
            deployments.update()
            .where(
                deployments.c.experience_id == mapping["id"],
                deployments.c.updated_by == actor,
            )
            .values(
                previous_release_id=deployments.c.release_id,
                release_id=release_id,
                updated_by=actor,
                updated_at=now,
            )
        )


def repair_mutated_091_releases(bind) -> None:
    """Restore the 090 release bytes, then publish the certified page as r2.

    Early 091 installations rewrote seed release #1 in place. The original
    pointer page is deterministic. The certified bytes are copied to a new
    release before #1 is restored, so an operator-authored draft is untouched.
    """
    tables_present = set(sa.inspect(bind).get_table_names())
    if not {
        "experiences",
        "experience_draft_revisions",
        "experience_releases",
        "experience_deployments",
        "system_bindings",
    }.issubset(tables_present):
        return
    _workspaces, _systems, _versions, _bindings, experiences, _drafts, releases, deployments = _tables()
    actor = f"system:{SEED_ORIGIN}"
    rows = bind.execute(
        sa.select(
            experiences.c.id,
            experiences.c.workspace_id,
            experiences.c.slug,
            experiences.c.name,
            experiences.c.pattern,
            experiences.c.theme,
            releases.c.id.label("release_id"),
            releases.c.pages.label("release_pages"),
            releases.c.bindings_snapshot,
            releases.c.access_snapshot,
            releases.c.languages,
            releases.c.theme.label("release_theme"),
            releases.c.renderer_version,
        )
        .join(releases, releases.c.experience_id == experiences.c.id)
        .where(
            experiences.c.created_by == actor,
            releases.c.created_by == actor,
            releases.c.release_number == 1,
            experiences.c.slug.in_(
                [
                    SENTINEL_EXPERIENCE_SLUG,
                    OCTOCITY_EXPERIENCE_SLUG,
                    MISSION_CONTROL_EXPERIENCE_SLUG,
                ]
            ),
        )
    ).all()
    for row in rows:
        mapping = row._mapping
        release_pages = mapping["release_pages"]
        if not _pages_have_certified_widgets(release_pages):
            continue
        theme = _as_dict(mapping["theme"])
        href = str(theme.get("live_href") or "/hypervisor/mission-room")
        body = (
            f"Open SENTINEL-CI on {href} — AYA and the immersive shell stay on that route."
            if mapping["slug"] == SENTINEL_EXPERIENCE_SLUG
            else f"Open Octocity on {href} — same certified widgets as SENTINEL, different branding."
            if mapping["slug"] == OCTOCITY_EXPERIENCE_SLUG
            else f"Open Mission Control on {href} — the immersive shell stays on that route."
        )
        pointer = _pointer_pages(title=mapping["name"], body=body, href=href)
        snapshot = [
            item
            for item in _as_list(mapping["bindings_snapshot"])
            if isinstance(item, dict) and isinstance(item.get("binding_key"), str)
        ]
        keys = [item["binding_key"] for item in snapshot]
        # A seed-owned release #1 containing certified widgets can only have
        # been produced by the old 091 in-place UPDATE. The fixed migration
        # always keeps #1 as the pointer page and appends #2, regardless of
        # whether the set of bindings happened to change.
        certified_digest = _content_sha256(release_pages, keys)
        successor = bind.execute(
            sa.select(releases.c.id, releases.c.release_number).where(
                releases.c.experience_id == mapping["id"],
                releases.c.release_number > 1,
                releases.c.created_by == actor,
                releases.c.content_sha256 == certified_digest,
            )
        ).first()
        if successor is None:
            latest_number = bind.execute(
                sa.select(sa.func.max(releases.c.release_number)).where(
                    releases.c.experience_id == mapping["id"]
                )
            ).scalar_one()
            successor_id = str(uuid4())
            bind.execute(
                sa.insert(releases).values(
                    id=successor_id,
                    experience_id=mapping["id"],
                    workspace_id=mapping["workspace_id"],
                    release_number=int(latest_number or 1) + 1,
                    content_sha256=certified_digest,
                    pages=release_pages,
                    bindings_snapshot=snapshot,
                    access_snapshot=_as_dict(mapping["access_snapshot"]),
                    languages=_as_list(mapping["languages"]),
                    theme=_as_dict(mapping["release_theme"]),
                    renderer_version=mapping["renderer_version"],
                    notes="Lot 8 repair: certified Mission widgets copied from mutated 091 release #1.",
                    created_by=actor,
                    created_at=datetime.utcnow(),
                )
            )
            _set_release_identity_if_supported(
                bind,
                release_id=successor_id,
                name=mapping["name"],
                slug=mapping["slug"],
                pattern=mapping["pattern"],
            )
        else:
            successor_id = successor._mapping["id"]
        bind.execute(
            deployments.update()
            .where(
                deployments.c.experience_id == mapping["id"],
                deployments.c.release_id == mapping["release_id"],
                deployments.c.updated_by == actor,
            )
            .values(
                previous_release_id=mapping["release_id"],
                release_id=successor_id,
                updated_at=datetime.utcnow(),
            )
        )
        pointer_digest = _content_sha256(pointer, keys)
        bind.execute(
            releases.update()
            .where(releases.c.id == mapping["release_id"])
            .values(pages=pointer, content_sha256=pointer_digest)
        )


def seed_dual_run_experiences(bind) -> None:
    tables_present = set(sa.inspect(bind).get_table_names())
    needed = {
        "workspaces",
        "systems",
        "system_versions",
        "system_bindings",
        "experiences",
        "experience_draft_revisions",
        "experience_releases",
        "experience_deployments",
    }
    if not needed.issubset(tables_present):
        return
    now = datetime.utcnow()
    tables = _tables()
    _seed_andritz(bind, tables, now)
    _seed_sentinel(bind, tables, now)
    _seed_octocity(bind, tables, now)
    _seed_mission_control(bind, tables, now)
    _upgrade_seed_mission_pages(bind)


def upgrade_dual_run_experiences(bind) -> None:
    seed_dual_run_experiences(bind)


def unseed_dual_run_experiences(bind) -> None:
    tables = set(sa.inspect(bind).get_table_names())
    actor = f"system:{SEED_ORIGIN}"
    keys = (
        ANDRITZ_RECHERCHE_KEY,
        ANDRITZ_CLIENT360_KEY,
        ANDRITZ_CAPTURE_KEY,
        ANDRITZ_FSE_KEY,
        SENTINEL_COCKPIT_KEY,
        SENTINEL_MAP_KEY,
        SENTINEL_AGENDA_KEY,
        SENTINEL_INTELLIGENCE_KEY,
        SENTINEL_DECISIONS_KEY,
        OCTOCITY_COCKPIT_KEY,
        OCTOCITY_MAP_KEY,
        OCTOCITY_AGENDA_KEY,
        OCTOCITY_INTELLIGENCE_KEY,
        OCTOCITY_DECISIONS_KEY,
        MISSION_COCKPIT_KEY,
        MISSION_MAP_KEY,
        MISSION_AGENDA_KEY,
        MISSION_INTELLIGENCE_KEY,
        MISSION_DECISIONS_KEY,
    )
    if "experience_deployments" in tables:
        deployments = sa.table("experience_deployments", sa.column("updated_by"))
        bind.execute(sa.delete(deployments).where(deployments.c.updated_by == actor))
    if "experience_releases" in tables:
        releases = sa.table("experience_releases", sa.column("created_by"))
        bind.execute(sa.delete(releases).where(releases.c.created_by == actor))
    if "experience_draft_revisions" in tables:
        drafts = sa.table("experience_draft_revisions", sa.column("updated_by"))
        bind.execute(sa.delete(drafts).where(drafts.c.updated_by == actor))
    if "experiences" in tables:
        experiences = sa.table("experiences", sa.column("created_by"))
        bind.execute(sa.delete(experiences).where(experiences.c.created_by == actor))
    if "system_bindings" in tables:
        bindings = sa.table(
            "system_bindings",
            sa.column("created_by"),
            sa.column("binding_key"),
        )
        bind.execute(
            sa.delete(bindings).where(
                bindings.c.created_by == actor,
                bindings.c.binding_key.in_(keys),
            )
        )
