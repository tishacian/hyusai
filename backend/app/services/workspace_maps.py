"""Workspace map system and risk scoring service."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.models.workspace_map import WorkspaceMap, WorkspaceMapLayer, WorkspaceMapScore, WorkspaceMapSignal, WorkspaceMapZone
from app.services.audit_logger import emit_audit_event
from app.services.scenario_engine import generate_scenarios
from app.services.workspace_jobs import transition_job


SENTINEL_MAP_SLUG = "sentinel-ci-strategic-map"
TERRITORIAL_INTELLIGENCE_COLLECTION = "sentinel-ci-territorial-intelligence"

IVORY_COAST_BOUNDS = {
    "west": -8.65,
    "south": 4.20,
    "east": -2.45,
    "north": 10.75,
}

SENTINEL_GEO_ZONES = {
    "zone-nord": {
        "centroid": [-5.63, 9.45],
        "coordinates": [[
            [-8.18, 9.42],
            [-7.62, 10.30],
            [-6.45, 10.53],
            [-5.25, 10.37],
            [-3.72, 9.72],
            [-3.64, 8.62],
            [-4.58, 8.08],
            [-5.82, 8.16],
            [-7.24, 8.34],
            [-8.18, 9.42],
        ]],
    },
    "zone-ouest": {
        "centroid": [-7.47, 7.25],
        "coordinates": [[
            [-8.54, 8.66],
            [-7.34, 8.36],
            [-6.70, 7.26],
            [-6.92, 6.18],
            [-7.64, 5.30],
            [-8.20, 5.72],
            [-8.42, 7.14],
            [-8.54, 8.66],
        ]],
    },
    "zone-centre": {
        "centroid": [-5.35, 7.23],
        "coordinates": [[
            [-6.76, 8.14],
            [-5.54, 8.26],
            [-4.56, 7.84],
            [-4.38, 6.62],
            [-5.12, 5.96],
            [-6.35, 6.16],
            [-6.96, 7.10],
            [-6.76, 8.14],
        ]],
    },
    "zone-sud": {
        "centroid": [-5.18, 5.18],
        "coordinates": [[
            [-7.78, 5.32],
            [-6.48, 5.80],
            [-5.10, 5.90],
            [-3.34, 5.58],
            [-2.88, 5.04],
            [-3.68, 4.64],
            [-5.32, 4.54],
            [-7.28, 4.46],
            [-7.78, 5.32],
        ]],
    },
    "zone-est": {
        "centroid": [-3.38, 7.24],
        "coordinates": [[
            [-4.42, 8.78],
            [-3.18, 8.58],
            [-2.72, 7.74],
            [-2.82, 6.48],
            [-3.55, 5.78],
            [-4.42, 6.24],
            [-4.70, 7.52],
            [-4.42, 8.78],
        ]],
    },
}

SENTINEL_CONTEXT_MARKERS = [
    {"name": "Abidjan", "kind": "capitale economique", "coordinates": [-4.0244, 5.3453], "weight": 98},
    {"name": "Yamoussoukro", "kind": "capitale politique", "coordinates": [-5.2767, 6.8276], "weight": 82},
    {"name": "Bouake", "kind": "centre logistique", "coordinates": [-5.0303, 7.6906], "weight": 75},
    {"name": "Korhogo", "kind": "ancrage nord", "coordinates": [-5.6294, 9.4580], "weight": 88},
    {"name": "Man", "kind": "ancrage ouest", "coordinates": [-7.5538, 7.4125], "weight": 62},
    {"name": "San Pedro", "kind": "port", "coordinates": [-6.6363, 4.7485], "weight": 58},
    {"name": "Daloa", "kind": "centre-ouest", "coordinates": [-6.4500, 6.8833], "weight": 55},
    {"name": "Bondoukou", "kind": "frontiere est", "coordinates": [-2.8000, 8.0500], "weight": 60},
]

SENTINEL_CONTEXT_LINES = [
    {"name": "Axe cabinet nord", "path": [[-4.0244, 5.3453], [-5.2767, 6.8276], [-5.0303, 7.6906], [-5.6294, 9.4580]], "tone": "watch"},
    {"name": "Axe ouest coordination", "path": [[-4.0244, 5.3453], [-6.4500, 6.8833], [-7.5538, 7.4125]], "tone": "stable"},
    {"name": "Axe est diplomatie locale", "path": [[-4.0244, 5.3453], [-3.8850, 6.7300], [-2.8000, 8.0500]], "tone": "watch"},
]

MAP_COMMAND_INTENTS = {
    "focus_zone",
    "set_layers",
    "highlight_marker",
    "draw_area",
    "show_action_window",
    "open_source_panel",
    "compare_before_after",
}

DEFAULT_RENDERER_LAYERS = [
    {
        "key": "territorial-risk",
        "label": "Zones de vigilance",
        "kind": "zone_score",
        "visible": True,
        "payload": {"scoring": "signals+projects+agenda+visual"},
        "sort_order": 10,
    },
    {
        "key": "open-intelligence",
        "label": "Presse et signaux faibles",
        "kind": "signal",
        "visible": True,
        "payload": {"sources": ["rss_press", "cabinet_note", "project_record"]},
        "sort_order": 20,
    },
    {
        "key": "strategic-projects",
        "label": "Projets publics",
        "kind": "project",
        "visible": True,
        "payload": {"sources": ["project_record", "action_plan"]},
        "sort_order": 30,
    },
    {
        "key": "agenda-windows",
        "label": "Fenetres agenda",
        "kind": "agenda_window",
        "visible": True,
        "payload": {"sources": ["workspace_calendar"]},
        "sort_order": 40,
    },
    {
        "key": "visual-streams",
        "label": "Flux visuels habilites",
        "kind": "visual_observation",
        "visible": True,
        "payload": {"sources": ["visual_streams"]},
        "sort_order": 50,
    },
    {
        "key": "preventive-actions",
        "label": "Actions preventives",
        "kind": "action",
        "visible": True,
        "payload": {"sources": ["action_plans", "scenario_engine"]},
        "sort_order": 60,
    },
]


SENTINEL_ZONE_SEED = [
    {
        "key": "zone-nord",
        "name": "Nord",
        "level": 85,
        "tone": "critical",
        "centroid": {"x": 410, "y": 98},
        "polygon": "374,62 455,74 489,130 444,168 366,152 342,105",
        "signals": ["Projet social en retard", "Rumeurs recurrentes", "Faible presence institutionnelle"],
        "recommendations": ["Rencontre autorites locales", "Communication ciblee", "Mission terrain non militaire"],
        "sources": ["src-cabinet-brief-001", "src-project-sante-042", "src-press-rfi-017"],
    },
    {
        "key": "zone-ouest",
        "name": "Ouest",
        "level": 45,
        "tone": "watch",
        "centroid": {"x": 300, "y": 220},
        "polygon": "263,158 347,171 369,260 315,319 244,282 229,205",
        "signals": ["Flux transfrontaliers", "Besoin de couverture institutionnelle"],
        "recommendations": ["Brief prefectoral", "Suivi logistique", "Coordination regionale"],
        "sources": ["src-cabinet-brief-001"],
    },
    {
        "key": "zone-centre",
        "name": "Centre",
        "level": 25,
        "tone": "stable",
        "centroid": {"x": 430, "y": 272},
        "polygon": "371,176 470,169 511,248 476,334 382,327 342,258",
        "signals": ["Situation stable", "Projet prioritaire dans les temps"],
        "recommendations": ["Maintien veille", "Capitaliser sur communication positive"],
        "sources": ["src-project-sante-042"],
    },
    {
        "key": "zone-sud",
        "name": "Sud",
        "level": 15,
        "tone": "stable",
        "centroid": {"x": 420, "y": 410},
        "polygon": "340,335 492,344 536,438 463,499 334,473 296,390",
        "signals": ["Couverture institutionnelle forte"],
        "recommendations": ["Aucune action urgente", "Veille presse standard"],
        "sources": ["src-agenda-jour-015"],
    },
    {
        "key": "zone-est",
        "name": "Est",
        "level": 55,
        "tone": "watch",
        "centroid": {"x": 558, "y": 257},
        "polygon": "493,143 596,166 629,263 581,356 497,327 520,238",
        "signals": ["Tension transfrontaliere moderee", "Couverture presse regionale"],
        "recommendations": ["Veille diplomatique", "Point coordination regionale"],
        "sources": ["src-press-rfi-017"],
    },
]


def ensure_workspace_map_seed(db: DBSession, workspace: Workspace, *, system_id: Optional[str] = None) -> WorkspaceMap:
    existing = (
        db.query(WorkspaceMap)
        .filter(WorkspaceMap.workspace_id == workspace.id, WorkspaceMap.slug == SENTINEL_MAP_SLUG)
        .first()
    )
    if existing:
        _ensure_map_layers(db, existing)
        return existing
    now = datetime.utcnow()
    map_row = WorkspaceMap(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system_id,
        slug=SENTINEL_MAP_SLUG,
        name="Carte strategique executive",
        description="Carte decisionnelle Cote d'Ivoire, zones, signaux et actions preventives non militaires.",
        country="Cote d'Ivoire",
        projection="illustrative_exec_demo",
        view_box="200 40 470 480",
        center={"x": 430, "y": 270},
        settings={"policy": "advisory_only", "scope": "government_mission_room", "version": 1},
        created_at=now,
        updated_at=now,
    )
    db.add(map_row)
    db.flush()
    _ensure_map_layers(db, map_row)
    db.flush()
    zone_rows: list[WorkspaceMapZone] = []
    for item in SENTINEL_ZONE_SEED:
        zone = WorkspaceMapZone(
            id=str(uuid4()),
            map_id=map_row.id,
            zone_key=item["key"],
            name=item["name"],
            level=item["level"],
            tone=item["tone"],
            polygon=item["polygon"],
            centroid=item["centroid"],
            meta_data={"signals": item["signals"], "recommendations": item["recommendations"]},
            source_refs=item["sources"],
        )
        db.add(zone)
        zone_rows.append(zone)
    db.flush()
    for zone, item in zip(zone_rows, SENTINEL_ZONE_SEED):
        for idx, signal in enumerate(item["signals"]):
            db.add(
                WorkspaceMapSignal(
                    id=str(uuid4()),
                    map_id=map_row.id,
                    zone_id=zone.id,
                    source_kind="mission_room",
                    source_id=f"{zone.zone_key}-signal-{idx + 1}",
                    title=signal,
                    summary=signal,
                    weight=max(8, min(30, int(item["level"] / 4))),
                    confidence=0.72 if item["level"] >= 50 else 0.62,
                    occurred_at=now,
                    meta_data={"seed": "sentinel-ci"},
                )
            )
    db.flush()
    score_map_zones(db, workspace, map_row)
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="map.system.seeded",
        actor="system",
        details={"map_id": map_row.id, "slug": map_row.slug, "zones": len(zone_rows)},
    )
    return map_row


def list_workspace_maps(db: DBSession, workspace: Workspace) -> list[WorkspaceMap]:
    return db.query(WorkspaceMap).filter(WorkspaceMap.workspace_id == workspace.id).order_by(WorkspaceMap.created_at.asc()).all()


def get_workspace_map(db: DBSession, workspace: Workspace, map_id_or_slug: str) -> WorkspaceMap:
    row = (
        db.query(WorkspaceMap)
        .filter(WorkspaceMap.workspace_id == workspace.id)
        .filter((WorkspaceMap.id == map_id_or_slug) | (WorkspaceMap.slug == map_id_or_slug))
        .first()
    )
    if not row:
        raise LookupError("workspace_map_not_found")
    return row


def score_map_zones(
    db: DBSession,
    workspace: Workspace,
    map_row: WorkspaceMap,
    *,
    job: Optional[WorkspaceJob] = None,
    user: Optional[User] = None,
) -> dict[str, Any]:
    if job:
        transition_job(db, workspace, job, "running", progress=35, stage="collect_signals", user=user)
    zones = db.query(WorkspaceMapZone).filter(WorkspaceMapZone.map_id == map_row.id).order_by(WorkspaceMapZone.level.desc()).all()
    db.query(WorkspaceMapScore).filter(WorkspaceMapScore.map_id == map_row.id).delete(synchronize_session=False)
    results = []
    for zone in zones:
        signals = db.query(WorkspaceMapSignal).filter(WorkspaceMapSignal.zone_id == zone.id).all()
        signal_score = sum(min(35, max(0, signal.weight)) * signal.confidence for signal in signals)
        score = max(0, min(100, int(round(zone.level * 0.68 + signal_score * 0.32))))
        label = _level_label(score)
        recommendations = generate_scenarios(
            target_kind="zone",
            target_id=zone.zone_key,
            risk_level=label,
            source_refs=zone.source_refs or [],
            signal_strength=score,
        )[:3]
        windows = _recommended_windows(zone.zone_key, score)
        score_row = WorkspaceMapScore(
            id=str(uuid4()),
            map_id=map_row.id,
            zone_id=zone.id,
            job_id=job.id if job else None,
            score=score,
            level_label=label,
            drivers=[signal.title for signal in signals] or list((zone.meta_data or {}).get("signals") or []),
            recommendations=recommendations,
            recommended_windows=windows,
            computed_at=datetime.utcnow(),
        )
        db.add(score_row)
        results.append(score_row)
    db.flush()
    if job:
        transition_job(
            db,
            workspace,
            job,
            "completed",
            progress=100,
            stage="scored",
            result={"zones_scored": len(results), "map_id": map_row.id},
            user=user,
        )
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="map.zones.scored",
        actor=_actor(user),
        details={"map_id": map_row.id, "zones": len(results), "job_id": job.id if job else None},
    )
    return {"map_id": map_row.id, "zones_scored": len(results), "scores": [serialize_score(score) for score in results]}


def serialize_map(map_row: WorkspaceMap, db: Optional[DBSession] = None) -> dict[str, Any]:
    payload = {
        "id": map_row.id,
        "slug": map_row.slug,
        "name": map_row.name,
        "description": map_row.description,
        "country": map_row.country,
        "projection": map_row.projection,
        "view_box": map_row.view_box,
        "center": map_row.center or {},
        "settings": map_row.settings or {},
    }
    if db:
        layers = db.query(WorkspaceMapLayer).filter(WorkspaceMapLayer.map_id == map_row.id).order_by(WorkspaceMapLayer.sort_order.asc()).all()
        payload["layers"] = [serialize_layer(layer) for layer in layers]
        zones = db.query(WorkspaceMapZone).filter(WorkspaceMapZone.map_id == map_row.id).order_by(WorkspaceMapZone.level.desc()).all()
        scores = {
            score.zone_id: score
            for score in db.query(WorkspaceMapScore)
            .filter(WorkspaceMapScore.map_id == map_row.id)
            .order_by(WorkspaceMapScore.computed_at.desc())
            .all()
        }
        zone_payloads = [serialize_zone(zone, scores.get(zone.id)) for zone in zones]
        renderer_payload = workspace_map_renderer_payload(map_row, zone_payloads)
        payload.update(renderer_payload)
    return payload


def serialize_layer(layer: WorkspaceMapLayer) -> dict[str, Any]:
    return {
        "id": layer.id,
        "key": layer.key,
        "label": layer.label,
        "kind": layer.kind,
        "visible": layer.visible,
        "payload": layer.payload or {},
        "sort_order": layer.sort_order,
    }


def serialize_zone(zone: WorkspaceMapZone, score: Optional[WorkspaceMapScore] = None) -> dict[str, Any]:
    payload = {
        "id": zone.zone_key,
        "zone_id": zone.id,
        "name": zone.name,
        "level": score.score if score else zone.level,
        "tone": _tone_for(score.score if score else zone.level),
        "centroid": zone.centroid or {},
        "polygon": zone.polygon,
        "signals": list((zone.meta_data or {}).get("signals") or []),
        "recommendations": list((zone.meta_data or {}).get("recommendations") or []),
        "sources": zone.source_refs or [],
    }
    if score:
        payload.update(
            {
                "score": serialize_score(score),
                "drivers": score.drivers or [],
                "scenario_options": score.recommendations or [],
                "recommended_windows": score.recommended_windows or [],
            }
        )
    return payload


def serialize_score(score: WorkspaceMapScore) -> dict[str, Any]:
    return {
        "id": score.id,
        "zone_id": score.zone_id,
        "job_id": score.job_id,
        "score": score.score,
        "level_label": score.level_label,
        "drivers": score.drivers or [],
        "recommendations": score.recommendations or [],
        "recommended_windows": score.recommended_windows or [],
        "computed_at": score.computed_at.isoformat() if score.computed_at else None,
    }


def mission_room_map_payload(db: DBSession, workspace: Workspace) -> dict[str, Any]:
    map_row = ensure_workspace_map_seed(db, workspace)
    zones = db.query(WorkspaceMapZone).filter(WorkspaceMapZone.map_id == map_row.id).order_by(WorkspaceMapZone.level.desc()).all()
    scores = {
        score.zone_id: score
        for score in db.query(WorkspaceMapScore).filter(WorkspaceMapScore.map_id == map_row.id).order_by(WorkspaceMapScore.computed_at.desc()).all()
    }
    zone_payloads = [serialize_zone(zone, scores.get(zone.id)) for zone in zones]
    return {
        "map_system": serialize_map(map_row, db),
        "map": {
            "country": map_row.country,
            "view_box": map_row.view_box,
            "projection": map_row.projection,
            "accuracy": "strategic_demo_not_geospatial_reference",
        },
        "zones": zone_payloads,
        "recommended_windows": [
            {"zone": zone["name"], "target_id": zone["id"], **(zone.get("recommended_windows") or [{}])[0]}
            for zone in zone_payloads
            if zone.get("recommended_windows")
        ],
        "score_summary": {
            "critical": sum(1 for zone in zone_payloads if zone.get("tone") == "critical"),
            "watch": sum(1 for zone in zone_payloads if zone.get("tone") == "watch"),
            "stable": sum(1 for zone in zone_payloads if zone.get("tone") == "stable"),
            "top_zone": zone_payloads[0] if zone_payloads else None,
        },
    }


def build_map_command(
    db: DBSession,
    workspace: Workspace,
    *,
    map_id_or_slug: str = SENTINEL_MAP_SLUG,
    intent: str,
    target: Optional[str] = None,
    layers: Optional[list[str]] = None,
    camera: Optional[dict[str, Any]] = None,
    annotation: Optional[dict[str, Any]] = None,
    user: Optional[User] = None,
) -> dict[str, Any]:
    """Build a provider-neutral map command scoped to the current workspace."""
    map_row = get_workspace_map(db, workspace, map_id_or_slug)
    payload = mission_room_map_payload(db, workspace)
    map_system = payload["map_system"]
    normalized_intent = intent if intent in MAP_COMMAND_INTENTS else "focus_zone"
    zones = payload.get("zones") or []
    selected = _find_zone_payload(zones, target) or payload.get("score_summary", {}).get("top_zone")
    selected_key = selected.get("id") if selected else None
    presets = map_system.get("camera_presets") or {}
    selected_camera = camera or presets.get(selected_key) or presets.get("country")
    active_layers = layers or [
        "territorial-risk",
        "open-intelligence",
        "strategic-projects",
        "visual-streams",
        "preventive-actions",
    ]
    explanation = _command_explanation(normalized_intent, selected)
    sources = _zone_sources(selected)
    command = {
        "command_id": str(uuid4()),
        "map_id": map_row.id,
        "map_slug": map_row.slug,
        "intent": normalized_intent,
        "target": selected_key,
        "target_label": selected.get("name") if selected else None,
        "map_state": {
            "renderer": map_system.get("renderer_config", {}).get("renderer", "maplibre"),
            "selected_zone": selected_key,
            "active_layers": active_layers,
            "camera": selected_camera,
            "annotation": annotation
            or {
                "label": selected.get("name") if selected else "Cote d'Ivoire",
                "summary": explanation,
                "tone": selected.get("tone") if selected else "monitoring",
            },
        },
        "explanation": explanation,
        "sources": sources,
    }
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="map.command.created",
        actor=_actor(user),
        details={
            "map_id": map_row.id,
            "intent": normalized_intent,
            "target": selected_key,
            "layers": active_layers,
            "source_count": len(sources),
        },
    )
    return command


def handle_map_chat_query(
    db: DBSession,
    workspace: Workspace,
    user: Optional[User],
    *,
    query: str,
    assistant_profile: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Small deterministic VIGIE action for map-centric questions.

    The heavy RAG path remains available for open questions. This branch is
    deliberately narrow: it emits a structured map command when the user asks
    VIGIE to show/focus/highlight territorial zones.
    """
    if assistant_profile != "vigie_executive":
        return None
    normalized = (query or "").lower()
    map_terms = ("carte", "zone", "zones", "nord", "ouest", "centre", "sud", "est", "zoom", "montre", "affiche")
    if not any(term in normalized for term in map_terms):
        return None
    intent = "focus_zone"
    if "source" in normalized:
        intent = "open_source_panel"
    if "fenetre" in normalized or "créneau" in normalized or "creneau" in normalized:
        intent = "show_action_window"
    if "compare" in normalized or "changé" in normalized or "change" in normalized:
        intent = "compare_before_after"
    target = _extract_zone_target(normalized)
    command = build_map_command(
        db,
        workspace,
        intent=intent,
        target=target,
        user=user,
    )
    label = command.get("target_label") or "les zones prioritaires"
    content = (
        f"J'affiche {label} sur la carte stratégique. La vue active les couches vigilance, "
        "presse, projets, flux visuels et actions préventives pour garder une lecture sourcée "
        "et exploitable par le cabinet."
    )
    return {
        "action": "map_command",
        "applied": True,
        "content": content,
        "command": command,
        "sources": command.get("sources") or [],
    }


def workspace_map_renderer_payload(map_row: WorkspaceMap, zones: list[dict[str, Any]]) -> dict[str, Any]:
    view_box = _parse_view_box(map_row.view_box)
    zone_features = []
    marker_features = []
    context_features = []
    line_features = []
    arc_links = []
    abidjan = [-4.0244, 5.3453]
    for zone in zones:
        coords = _zone_lonlat_polygon(zone, view_box)
        centroid = _zone_lonlat_centroid(zone, view_box)
        if coords:
            zone_features.append(
                {
                    "type": "Feature",
                    "id": zone.get("id"),
                    "geometry": {"type": "Polygon", "coordinates": [coords]},
                    "properties": {
                        "id": zone.get("id"),
                        "name": zone.get("name"),
                        "level": zone.get("level"),
                        "tone": zone.get("tone"),
                        "signals": zone.get("signals") or [],
                        "recommendations": zone.get("recommendations") or [],
                    },
                }
            )
        if centroid:
            marker_features.append(
                {
                    "type": "Feature",
                    "id": f"{zone.get('id')}-marker",
                    "geometry": {"type": "Point", "coordinates": centroid},
                    "properties": {
                        "zone_id": zone.get("id"),
                        "name": zone.get("name"),
                        "level": zone.get("level"),
                        "tone": zone.get("tone"),
                    },
                }
            )
            if (zone.get("level") or 0) >= 45:
                arc_links.append(
                    {
                        "source": abidjan,
                        "target": centroid,
                        "tone": zone.get("tone"),
                        "level": zone.get("level"),
                        "label": f"Coordination {zone.get('name')}",
                    }
                )
    for marker in SENTINEL_CONTEXT_MARKERS:
        context_features.append(
            {
                "type": "Feature",
                "id": f"context-{marker['name'].lower().replace(' ', '-')}",
                "geometry": {"type": "Point", "coordinates": marker["coordinates"]},
                "properties": {
                    "name": marker["name"],
                    "kind": marker["kind"],
                    "weight": marker["weight"],
                    "source": "sentinel-ci-territorial-context",
                },
            }
        )
    for line in SENTINEL_CONTEXT_LINES:
        line_features.append(
            {
                "type": "Feature",
                "id": f"line-{line['name'].lower().replace(' ', '-')}",
                "geometry": {"type": "LineString", "coordinates": line["path"]},
                "properties": {"name": line["name"], "tone": line["tone"]},
            }
        )
    camera_presets = _camera_presets(zones, view_box)
    return {
        "renderer_config": {
            "renderer": "maplibre",
            "fallback_renderer": "svg",
            "basemap_policy": "public_osm_muted",
            "style": {
                "version": 8,
                "sources": {
                    "carto-voyager": {
                        "type": "raster",
                        "tiles": [
                            "https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
                            "https://b.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
                            "https://c.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
                        ],
                        "tileSize": 256,
                        "attribution": "OpenStreetMap contributors / CARTO",
                    }
                },
                "layers": [
                    {
                        "id": "agentium-background",
                        "type": "background",
                        "paint": {"background-color": "#05080d"},
                    },
                    {
                        "id": "carto-voyager-muted",
                        "type": "raster",
                        "source": "carto-voyager",
                        "paint": {
                            "raster-opacity": 0.54,
                            "raster-brightness-min": 0.03,
                            "raster-brightness-max": 0.70,
                            "raster-saturation": -0.68,
                            "raster-contrast": -0.08,
                        },
                    }
                ],
            },
            "initial_view_state": camera_presets["country"],
            "bounds": [[IVORY_COAST_BOUNDS["west"], IVORY_COAST_BOUNDS["south"]], [IVORY_COAST_BOUNDS["east"], IVORY_COAST_BOUNDS["north"]]],
            "attribution": "Fond cartographique OSM/CARTO · couches Agentium workspace",
            "interaction_contract": {
                "commands": sorted(MAP_COMMAND_INTENTS),
                "selection": "zone",
                "events": ["zone_selected", "map_state_updated", "source_panel_requested"],
            },
        },
        "geojson_sources": {
            "zones": {"type": "FeatureCollection", "features": zone_features},
            "markers": {"type": "FeatureCollection", "features": marker_features},
            "context_markers": {"type": "FeatureCollection", "features": context_features},
            "context_lines": {"type": "FeatureCollection", "features": line_features},
        },
        "camera_presets": camera_presets,
        "visual_effects": {
            "zone_halo": True,
            "marker_pulse": True,
            "arc_links": arc_links,
            "performance_policy": "disable_effects_on_low_power_device",
        },
    }


def _zone_lonlat_polygon(zone: dict[str, Any], view_box: tuple[float, float, float, float]) -> list[list[float]]:
    seeded = SENTINEL_GEO_ZONES.get(str(zone.get("id") or ""))
    if seeded:
        return seeded["coordinates"][0]
    return _polygon_to_lonlat(zone.get("polygon") or "", view_box)


def _zone_lonlat_centroid(zone: dict[str, Any], view_box: tuple[float, float, float, float]) -> Optional[list[float]]:
    seeded = SENTINEL_GEO_ZONES.get(str(zone.get("id") or ""))
    if seeded:
        return seeded["centroid"]
    return _point_to_lonlat(zone.get("centroid") or {}, view_box)


def _ensure_map_layers(db: DBSession, map_row: WorkspaceMap) -> None:
    existing = {
        layer.key
        for layer in db.query(WorkspaceMapLayer.key).filter(WorkspaceMapLayer.map_id == map_row.id).all()
    }
    for layer in DEFAULT_RENDERER_LAYERS:
        if layer["key"] in existing:
            continue
        db.add(
            WorkspaceMapLayer(
                id=str(uuid4()),
                map_id=map_row.id,
                key=layer["key"],
                label=layer["label"],
                kind=layer["kind"],
                visible=layer["visible"],
                payload=layer["payload"],
                sort_order=layer["sort_order"],
            )
        )
    db.flush()


def _recommended_windows(zone_key: str, score: int) -> list[dict[str, Any]]:
    if "nord" in zone_key or score >= 75:
        return [
            {
                "label": "Avant point presse",
                "start": "10:00",
                "end": "10:45",
                "why": "Dernier creneau avant expression publique et amplification potentielle.",
            },
            {
                "label": "Apres revue operations",
                "start": "16:10",
                "end": "16:45",
                "why": "Fenetre utile pour arbitrage cabinet avant sequence parlementaire.",
            },
        ]
    if score >= 45:
        return [
            {
                "label": "Creneau coordination",
                "start": "12:00",
                "end": "12:25",
                "why": "Fenetre courte pour cadrer une action preventive.",
            }
        ]
    return [
        {
            "label": "Veille standard",
            "start": "17:00",
            "end": "17:20",
            "why": "Point rapide suffisant en l'absence de signal prioritaire.",
        }
    ]


def _level_label(score: int) -> str:
    if score >= 75:
        return "critical"
    if score >= 45:
        return "high"
    if score >= 25:
        return "medium"
    return "low"


def _tone_for(score: int) -> str:
    if score >= 75:
        return "critical"
    if score >= 45:
        return "watch"
    return "stable"


def _actor(user: Optional[User]) -> str:
    if not user:
        return "system"
    return user.email or user.username or user.id


def _parse_view_box(view_box: Optional[str]) -> tuple[float, float, float, float]:
    try:
        parts = [float(part) for part in (view_box or "").split()]
        if len(parts) == 4 and parts[2] > 0 and parts[3] > 0:
            return parts[0], parts[1], parts[2], parts[3]
    except ValueError:
        pass
    return 200.0, 40.0, 470.0, 480.0


def _point_to_lonlat(point: dict[str, Any], view_box: tuple[float, float, float, float]) -> Optional[list[float]]:
    try:
        x = float(point.get("x"))
        y = float(point.get("y"))
    except (TypeError, ValueError):
        return None
    min_x, min_y, width, height = view_box
    x_ratio = max(0.0, min(1.0, (x - min_x) / width))
    y_ratio = max(0.0, min(1.0, (y - min_y) / height))
    lon = IVORY_COAST_BOUNDS["west"] + x_ratio * (IVORY_COAST_BOUNDS["east"] - IVORY_COAST_BOUNDS["west"])
    lat = IVORY_COAST_BOUNDS["north"] - y_ratio * (IVORY_COAST_BOUNDS["north"] - IVORY_COAST_BOUNDS["south"])
    return [round(lon, 5), round(lat, 5)]


def _polygon_to_lonlat(polygon: str, view_box: tuple[float, float, float, float]) -> list[list[float]]:
    coords: list[list[float]] = []
    for token in polygon.split():
        if "," not in token:
            continue
        try:
            x_raw, y_raw = token.split(",", 1)
            point = _point_to_lonlat({"x": float(x_raw), "y": float(y_raw)}, view_box)
        except ValueError:
            point = None
        if point:
            coords.append(point)
    if coords and coords[0] != coords[-1]:
        coords.append(coords[0])
    return coords


def _camera_presets(zones: list[dict[str, Any]], view_box: tuple[float, float, float, float]) -> dict[str, dict[str, Any]]:
    presets: dict[str, dict[str, Any]] = {
        "country": {
            "longitude": -5.45,
            "latitude": 7.52,
            "zoom": 6.0,
            "pitch": 34,
            "bearing": -7,
            "duration_ms": 900,
        }
    }
    for zone in zones:
        point = _zone_lonlat_centroid(zone, view_box)
        if not point:
            continue
        zoom = 7.35 if (zone.get("level") or 0) >= 75 else 6.95
        presets[zone.get("id") or zone.get("name")] = {
            "longitude": point[0],
            "latitude": point[1],
            "zoom": zoom,
            "pitch": 44,
            "bearing": -10,
            "duration_ms": 850,
        }
    return presets


def _find_zone_payload(zones: list[dict[str, Any]], target: Optional[str]) -> Optional[dict[str, Any]]:
    if not target:
        return None
    normalized = target.lower().strip()
    for zone in zones:
        if normalized in {str(zone.get("id", "")).lower(), str(zone.get("name", "")).lower()}:
            return zone
        if normalized and normalized in str(zone.get("name", "")).lower():
            return zone
    return None


def _extract_zone_target(query: str) -> Optional[str]:
    for key, labels in {
        "zone-nord": ("nord", "korhogo", "frontaliere nord"),
        "zone-ouest": ("ouest", "man", "liberia", "guinee"),
        "zone-centre": ("centre", "yamoussoukro"),
        "zone-sud": ("sud", "abidjan", "littoral"),
        "zone-est": ("est", "ghana", "bondoukou"),
    }.items():
        if any(label in query for label in labels):
            return key
    return None


def _command_explanation(intent: str, selected: Optional[dict[str, Any]]) -> str:
    if not selected:
        return "Vue consolidee de la posture territoriale et des signaux qualifiés."
    name = selected.get("name")
    if intent == "show_action_window":
        return f"Fenêtres recommandées pour une action préventive sur la zone {name}."
    if intent == "open_source_panel":
        return f"Ouverture des sources qualifiées soutenant l'analyse de la zone {name}."
    if intent == "compare_before_after":
        return f"Comparaison de la posture de la zone {name} depuis le dernier briefing."
    return f"Focus sur la zone {name}, niveau {selected.get('level')}%, avec couches de vigilance et actions."


def _zone_sources(selected: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    if not selected:
        return [{"title": "Carte stratégique", "kind": "workspace_map", "source_label": "Carte stratégique"}]
    return [
        {
            "title": source,
            "kind": "map_source",
            "source_label": f"Source zone {selected.get('name')}",
            "zone": selected.get("id"),
        }
        for source in (selected.get("sources") or ["Carte stratégique"])
    ]
