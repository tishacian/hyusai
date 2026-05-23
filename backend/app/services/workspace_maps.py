"""Workspace map system and risk scoring service."""
from __future__ import annotations

import copy
import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
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
GEO_DATA_DIR = Path(__file__).resolve().parents[1] / "resources" / "geo" / "civ"

IVORY_COAST_BOUNDS = {
    "west": -8.65,
    "south": 4.20,
    "east": -2.45,
    "north": 10.75,
}

REGIONAL_CONTEXT_BOUNDS = {
    "west": -13.80,
    "south": 3.80,
    "east": 1.75,
    "north": 13.20,
}

SENTINEL_ZONE_GEOGRAPHY = {
    "zone-nord": {
        "centroid": [-5.65, 9.15],
        "admin1": ["Savanes", "Denguele", "Woroba"],
    },
    "zone-ouest": {
        "centroid": [-7.25, 6.9],
        "admin1": ["Montagnes", "Sassandra-Marahoue"],
    },
    "zone-centre": {
        "centroid": [-5.1, 7.25],
        "admin1": ["Valle Du Bandama", "Lacs", "District Autonome De Yamoussoukro"],
    },
    "zone-sud": {
        "centroid": [-5.25, 5.35],
        "admin1": ["Bas-Sassandra", "Goh-Djiboua", "Lagunes", "District Autonome D'Abidjan"],
    },
    "zone-est": {
        "centroid": [-3.25, 7.25],
        "admin1": ["Zanzan", "Comoe"],
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
    {"name": "Accra", "kind": "voisin CEDEAO · Ghana", "coordinates": [-0.1869, 5.6037], "weight": 70, "scope": "regional"},
    {"name": "Monrovia", "kind": "voisin CEDEAO · Liberia", "coordinates": [-10.7969, 6.3156], "weight": 58, "scope": "regional"},
    {"name": "Conakry", "kind": "voisin CEDEAO · Guinee", "coordinates": [-13.5784, 9.6412], "weight": 60, "scope": "regional"},
    {"name": "Bamako", "kind": "Sahel · Mali", "coordinates": [-8.0029, 12.6392], "weight": 72, "scope": "regional"},
    {"name": "Ouagadougou", "kind": "Sahel · Burkina Faso", "coordinates": [-1.5197, 12.3714], "weight": 74, "scope": "regional"},
    {"name": "Lome", "kind": "Golfe de Guinee · Togo", "coordinates": [1.2314, 6.1319], "weight": 54, "scope": "regional"},
]

SENTINEL_CONTEXT_LINES = [
    {"name": "Axe cabinet nord", "path": [[-4.0244, 5.3453], [-5.2767, 6.8276], [-5.0303, 7.6906], [-5.6294, 9.4580]], "tone": "watch"},
    {"name": "Axe ouest coordination", "path": [[-4.0244, 5.3453], [-6.4500, 6.8833], [-7.5538, 7.4125]], "tone": "stable"},
    {"name": "Axe est diplomatie locale", "path": [[-4.0244, 5.3453], [-3.8850, 6.7300], [-2.8000, 8.0500]], "tone": "watch"},
    {"name": "Arc CEDEAO ouest", "path": [[-4.0244, 5.3453], [-10.7969, 6.3156], [-13.5784, 9.6412]], "tone": "regional"},
    {"name": "Arc Sahel", "path": [[-4.0244, 5.3453], [-5.6294, 9.4580], [-8.0029, 12.6392], [-1.5197, 12.3714]], "tone": "watch"},
    {"name": "Arc Golfe de Guinee", "path": [[-4.0244, 5.3453], [-0.1869, 5.6037], [1.2314, 6.1319]], "tone": "stable"},
]

MAP_COMMAND_INTENTS = {
    "focus_zone",
    "focus_port",
    "set_layers",
    "set_basemap",
    "set_time_range",
    "reset_view",
    "show_sources",
    "show_vessel_snapshot",
    "show_disruption",
    "highlight_marker",
    "draw_area",
    "show_action_window",
    "open_source_panel",
    "open_layer_search",
    "compare_before_after",
}

MAP_TIME_RANGES = [
    {"key": "24h", "label": "24h", "description": "Signaux recents utiles au briefing du jour."},
    {"key": "7d", "label": "7 jours", "description": "Tendance ministerielle hebdomadaire."},
    {"key": "30d", "label": "30 jours", "description": "Lecture de fond et recurrents territoriaux."},
]

DEFAULT_RENDERER_LAYERS = [
    {
        "key": "territorial-risk",
        "label": "Zones de vigilance",
        "short_label": "Zones",
        "deck_group": "territory",
        "tone": "cyan",
        "kind": "zone_score",
        "visible": True,
        "payload": {"scoring": "signals+projects+agenda+visual"},
        "sort_order": 10,
    },
    {
        "key": "open-intelligence",
        "label": "Presse CI / international",
        "short_label": "Presse",
        "deck_group": "press",
        "tone": "blue",
        "kind": "signal",
        "visible": True,
        "payload": {"sources": ["rss_press", "cabinet_note", "project_record"]},
        "sort_order": 20,
    },
    {
        "key": "regional-context",
        "label": "Contexte CEDEAO / Golfe de Guinee",
        "short_label": "Region",
        "deck_group": "region",
        "tone": "orange",
        "kind": "regional_context",
        "visible": False,
        "payload": {"sources": ["rss_press_regional", "diplomatic_context", "social_listening"]},
        "sort_order": 25,
    },
    {
        "key": "strategic-projects",
        "label": "Projets publics",
        "short_label": "Projets",
        "deck_group": "projects",
        "tone": "green",
        "kind": "project",
        "visible": True,
        "payload": {"sources": ["project_record", "action_plan"]},
        "sort_order": 30,
    },
    {
        "key": "agenda-windows",
        "label": "Fenetres agenda",
        "short_label": "Agenda",
        "deck_group": "agenda",
        "tone": "amber",
        "kind": "agenda_window",
        "visible": False,
        "payload": {"sources": ["workspace_calendar"]},
        "sort_order": 40,
    },
    {
        "key": "visual-streams",
        "label": "Flux visuels habilites",
        "short_label": "Visuel",
        "deck_group": "visual",
        "tone": "violet",
        "kind": "visual_observation",
        "visible": True,
        "payload": {"sources": ["visual_streams"]},
        "sort_order": 50,
    },
    {
        "key": "maritime-traffic",
        "label": "Maritime / douanes",
        "short_label": "Maritime",
        "deck_group": "maritime",
        "tone": "blue",
        "kind": "maritime_snapshot",
        "visible": False,
        "payload": {"sources": ["port_snapshot", "rss_maritime", "ais_provider_optional"]},
        "sort_order": 55,
    },
    {
        "key": "preventive-actions",
        "label": "Actions preventives",
        "short_label": "Actions",
        "deck_group": "actions",
        "tone": "red",
        "kind": "action",
        "visible": False,
        "payload": {"sources": ["action_plans", "scenario_engine"]},
        "sort_order": 60,
    },
]

MARITIME_PORTS = [
    {
        "id": "port-abidjan",
        "name": "Port d'Abidjan",
        "location": "Abidjan / Vridi",
        "longitude": -4.0083,
        "latitude": 5.2512,
        "score": 71,
        "tone": "watch",
        "status": "active",
        "role": "Hub portuaire et douanier critique pour flux economiques nationaux.",
    },
    {
        "id": "port-san-pedro",
        "name": "Port de San Pedro",
        "location": "San Pedro",
        "longitude": -6.6368,
        "latitude": 4.7446,
        "score": 48,
        "tone": "stable",
        "status": "monitoring",
        "role": "Port secondaire a surveiller pour corridors export et approvisionnement.",
    },
]

MARITIME_EVENTS = [
    {
        "id": "cargo-abidjan-supply-001",
        "title": "Cargo composants drones Napié — attente dedouanement Abidjan",
        "location": "Port d'Abidjan / Vridi",
        "longitude": -4.02,
        "latitude": 5.24,
        "score": 74,
        "severity": "watch",
        "domain": "customs",
        "status": "awaiting_customs",
        "vessel_name": "MV Atlantic Trader",
        "vessel_id": "mv-atlantic-trader",
        "imo": "9876543",
        "mmsi": "627012345",
        "cargo": (
            "Composants drones AerostarDynamics — hangars formation, "
            "terrains apprentissage, labos cartographie (Centre Napié)"
        ),
        "origin": "USA East Coast",
        "destination": "Napié via Port autonome d'Abidjan",
        "project_ref": "proj-drone-centre-napie",
        "project_ref_aliases": ["proj-public-north-supply"],
        "customs_record_ref": "customs-record-non-conformite-2026-05",
        "summary": (
            "Cargaison de composants drones Aerostar Dynamics destinée au Centre "
            "International de Formation aux Métiers des Drones de Napié bloquée à "
            "Vridi par effet collatéral du PV douanes du 18 mai."
        ),
        "recommended_action": "Preparer courrier de derogation chef des douanes pour distinguer le cargo drones Napié du lot non conforme.",
        "decision_deadline": "12:00",
        "source_refs": [
            "src-maritime-paa-001",
            "src-marinetraffic-context-001",
            "src-cabinet-brief-001",
            "src-abidjan-net-drone-napie-2025-07-16",
        ],
    },
    {
        "id": "vessel-density-abidjan",
        "title": "Densite navires · Abidjan",
        "location": "Rade d'Abidjan",
        "longitude": -4.12,
        "latitude": 5.18,
        "score": 68,
        "severity": "watch",
        "domain": "port_flow",
        "status": "anchored",
        "speed_knots": 0.3,
        "summary": "Concentration de navires a rapprocher des flux douaniers et du calendrier economique.",
        "recommended_action": "Verifier douanes + port avant toute communication economique.",
        "decision_deadline": "12:00",
        "source_refs": ["src-maritime-paa-001", "src-marinetraffic-context-001"],
    },
    {
        "id": "vessel-underway-gulf",
        "title": "Corridor Golfe de Guinee",
        "location": "Golfe de Guinee",
        "longitude": -3.62,
        "latitude": 4.92,
        "score": 52,
        "severity": "monitoring",
        "domain": "gulf_corridor",
        "status": "underway",
        "speed_knots": 12.4,
        "summary": "Transit nominal mais pertinent pour une lecture douanes / commerce exterieur.",
        "recommended_action": "Maintenir veille portuaire et economique.",
        "decision_deadline": "aujourd'hui",
        "source_refs": ["src-maritime-marinelink-001"],
    },
    {
        "id": "customs-watch-san-pedro",
        "title": "San Pedro · corridor export",
        "location": "San Pedro",
        "longitude": -6.72,
        "latitude": 4.70,
        "score": 43,
        "severity": "stable",
        "domain": "customs",
        "status": "unknown",
        "speed_knots": None,
        "summary": "Point de controle demo-safe pour relier ports, douanes et chantiers industriels.",
        "recommended_action": "Conserver en veille hebdomadaire.",
        "decision_deadline": "semaine",
        "source_refs": ["src-port-san-pedro-context-001"],
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
        if existing.projection != "geojson_admin_boundaries_v1":
            existing.projection = "geojson_admin_boundaries_v1"
            existing.settings = {
                **(existing.settings or {}),
                "policy": "advisory_only",
                "scope": "government_mission_room",
                "version": 2,
                "renderer_source": "geoBoundaries.ADM1.ADM2",
                "legacy_polygon_mode": "compatibility_only",
            }
            existing.updated_at = datetime.utcnow()
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
        projection="geojson_admin_boundaries_v1",
        view_box="200 40 470 480",
        center={"x": 430, "y": 270},
        settings={
            "policy": "advisory_only",
            "scope": "government_mission_room",
            "version": 2,
            "renderer_source": "geoBoundaries.ADM1.ADM2",
            "legacy_polygon_mode": "compatibility_only",
        },
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


def _basemap_style(source_id: str, tiles: list[str], paint: dict[str, Any], background: str = "#05080d") -> dict[str, Any]:
    return {
        "version": 8,
        "sources": {
            source_id: {
                "type": "raster",
                "tiles": tiles,
                "tileSize": 256,
                "attribution": "OpenStreetMap contributors / CARTO",
            }
        },
        "layers": [
            {"id": "agentium-background", "type": "background", "paint": {"background-color": background}},
            {"id": f"{source_id}-base", "type": "raster", "source": source_id, "paint": paint},
        ],
    }


def _map_basemap_options() -> list[dict[str, Any]]:
    carto_dark = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"
    carto_voyager = "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json"
    carto_positron = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"
    carto_dark_tiles = [
        "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        "https://d.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
    ]
    return [
        {
            "key": "command",
            "label": "Commandement",
            "description": "Fond commandement sombre a contraste stable pour distinguer mer, terre, frontieres et points de situation.",
            "provider": "carto_raster",
            "theme": "dark_all_command",
            "style": _basemap_style(
                "carto-command-dark",
                carto_dark_tiles,
                {
                    "raster-opacity": 0.98,
                    "raster-brightness-min": 0.0,
                    "raster-brightness-max": 0.84,
                    "raster-saturation": -0.16,
                    "raster-contrast": 0.18,
                },
                background="#0b0d0f",
            ),
        },
        {
            "key": "administrative",
            "label": "Administratif",
            "description": "Fond administratif contraste, labels et frontieres visibles pour briefing executif.",
            "provider": "carto_vector",
            "theme": "voyager",
            "style": carto_voyager,
        },
        {
            "key": "dark",
            "label": "Sombre",
            "description": "Fond cockpit sombre avec relief visuel et labels discrets.",
            "provider": "carto_vector",
            "theme": "dark-matter",
            "style": carto_dark,
        },
        {
            "key": "contours",
            "label": "Contours",
            "description": "Fond clair desature pour briefing imprime, projection ou capture de sources.",
            "provider": "carto_vector",
            "theme": "positron",
            "style": carto_positron,
        },
    ]


def _layer_catalog(source_counts: dict[str, int]) -> list[dict[str, Any]]:
    return [
        {
            "key": layer["key"],
            "label": layer["label"],
            "short_label": layer["short_label"],
            "deck_group": layer["deck_group"],
            "tone": layer["tone"],
            "visible": layer["visible"],
            "kind": layer["kind"],
            "count": source_counts.get(layer["key"], 0),
            "confidence": _layer_confidence(layer["key"]),
        }
        for layer in DEFAULT_RENDERER_LAYERS
    ]


def _layer_registry(source_counts: dict[str, int]) -> list[dict[str, Any]]:
    freshness = _layer_freshness()
    updated_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    groups = {
        "territorial-risk": "Territoire",
        "open-intelligence": "Presse / rumeurs",
        "regional-context": "CEDEAO",
        "strategic-projects": "Projets",
        "agenda-windows": "Agenda",
        "visual-streams": "Visuel",
        "maritime-traffic": "Maritime / douanes",
        "preventive-actions": "Actions",
    }
    icons = {
        "territorial-risk": "target",
        "open-intelligence": "rss",
        "regional-context": "globe",
        "strategic-projects": "network",
        "agenda-windows": "calendar",
        "visual-streams": "camera",
        "maritime-traffic": "ship",
        "preventive-actions": "check",
    }
    registry = []
    for item in _layer_catalog(source_counts):
        count = int(item.get("count") or 0)
        status = "ready" if count else "empty"
        registry.append(
            {
                **item,
                "group": groups.get(item["key"], "Sources"),
                "icon": icons.get(item["key"], "layer"),
                "status": status,
                "state_label": "pret" if status == "ready" else "vide",
                "freshness": freshness.get(item["key"], "a jour"),
                "freshness_at": updated_at,
                "failure_reason": None,
                "default_visible": bool(item.get("visible")),
                "source_kind": _layer_source_kind(item["key"]),
                "source_count": count,
                "renderer_support": ["maplibre", "deck.gl", "svg-fallback"],
                "tooltip": _layer_tooltip(item["key"]),
            }
        )
    return registry


def _layer_tooltip(key: str) -> dict[str, str]:
    return {
        "territorial-risk": {
            "title": "Zones de vigilance",
            "body": "Scores territoriaux calcules depuis presse, projets, agenda et observations.",
        },
        "open-intelligence": {
            "title": "Presse et rumeurs",
            "body": "Signaux qualifies par origine, zone, impact institutionnel et confiance.",
        },
        "regional-context": {
            "title": "Contexte CEDEAO",
            "body": "Pays voisins, axes regionaux et signaux susceptibles d'affecter la Cote d'Ivoire.",
        },
        "strategic-projects": {
            "title": "Projets publics",
            "body": "Chantiers et dossiers sensibles relies aux zones et aux arbitrages cabinet.",
        },
        "agenda-windows": {
            "title": "Fenetres agenda",
            "body": "Creneaux utiles pour arbitrage, communication ou mission terrain.",
        },
        "visual-streams": {
            "title": "Flux visuels",
            "body": "Captures publiques ou habilitees, analysees sans biometrie ni suivi individuel.",
        },
        "maritime-traffic": {
            "title": "Maritime et douanes",
            "body": "Ports, corridors et densites demo-safe, avec provider AIS optionnel.",
        },
        "preventive-actions": {
            "title": "Actions preventives",
            "body": "Options advisory-only, a valider par le VP ou le cabinet.",
        },
    }.get(key, {"title": "Couche", "body": "Donnees workspace scopees."})


def _layer_confidence(key: str) -> int:
    return {
        "territorial-risk": 78,
        "open-intelligence": 72,
        "regional-context": 74,
        "strategic-projects": 69,
        "agenda-windows": 81,
        "visual-streams": 62,
        "maritime-traffic": 66,
        "preventive-actions": 74,
    }.get(key, 65)


def _layer_freshness() -> dict[str, str]:
    return {
        "territorial-risk": "scoring actif",
        "open-intelligence": "dernier run veille",
        "regional-context": "contexte stable",
        "strategic-projects": "mise a jour projet",
        "agenda-windows": "agenda du jour",
        "visual-streams": "snapshot recent",
        "maritime-traffic": "snapshot demo-safe",
        "preventive-actions": "validation requise",
    }


def _layer_source_kind(key: str) -> str:
    return {
        "territorial-risk": "workspace_map_score",
        "open-intelligence": "news_lab",
        "regional-context": "regional_context",
        "strategic-projects": "project_record",
        "agenda-windows": "workspace_calendar",
        "visual-streams": "visual_intelligence",
        "maritime-traffic": "maritime_snapshot",
        "preventive-actions": "action_planner",
    }.get(key, "workspace")


def _source_counts(zones: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "territorial-risk": len(zones),
        "open-intelligence": sum(len(zone.get("drivers") or zone.get("signals") or []) for zone in zones),
        "regional-context": sum(1 for marker in SENTINEL_CONTEXT_MARKERS if marker.get("scope") == "regional"),
        "strategic-projects": sum(1 for zone in zones if zone.get("scenario_options")),
        "agenda-windows": sum(len(zone.get("recommended_windows") or []) for zone in zones),
        "visual-streams": 1,
        "maritime-traffic": len(MARITIME_PORTS) + len(MARITIME_EVENTS),
        "preventive-actions": sum(len(zone.get("recommendations") or []) for zone in zones),
    }


@lru_cache(maxsize=8)
def _load_geo_asset(filename: str) -> dict[str, Any]:
    path = GEO_DATA_DIR / filename
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _normalize_geo_collection(filename: str, *, level: str, kind: str) -> dict[str, Any]:
    source = _load_geo_asset(filename)
    features = []
    for feature in source.get("features") or []:
        copied = copy.deepcopy(feature)
        properties = copied.setdefault("properties", {})
        shape_name = properties.get("shapeName") or properties.get("name") or ""
        copied["id"] = properties.get("shapeID") or _slugify(shape_name)
        properties.update(
            {
                "name": shape_name,
                "kind": kind,
                "admin_level": level,
                "source": "geoBoundaries",
                "license": "CC BY 4.0",
            }
        )
        features.append(copied)
    return {"type": "FeatureCollection", "features": features}


def _geo_metadata() -> dict[str, Any]:
    try:
        return _load_geo_asset("metadata.json")
    except FileNotFoundError:
        return {
            "source": "geoBoundaries",
            "license": "CC BY 4.0",
            "notes": "Metadata file missing; geospatial assets remain versioned in the repository.",
        }


def _country_boundary_geojson() -> dict[str, Any]:
    return _normalize_geo_collection("geoboundaries-civ-adm0.geojson", level="ADM0", kind="country")


def _admin_boundaries_geojson() -> dict[str, Any]:
    return _normalize_geo_collection("geoboundaries-civ-adm2.geojson", level="ADM2", kind="region")


def _district_boundaries_geojson() -> dict[str, Any]:
    return _normalize_geo_collection("geoboundaries-civ-adm1.geojson", level="ADM1", kind="district")


def _zone_geojson_features(zone: dict[str, Any]) -> list[dict[str, Any]]:
    definition = SENTINEL_ZONE_GEOGRAPHY.get(str(zone.get("id") or ""))
    if not definition:
        return []
    requested = set(definition.get("admin1") or [])
    districts = _district_boundaries_geojson()
    features = []
    for feature in districts.get("features") or []:
        admin_name = feature.get("properties", {}).get("name")
        if admin_name not in requested:
            continue
        copied = copy.deepcopy(feature)
        copied["id"] = f"{zone.get('id')}-{_slugify(admin_name)}"
        copied.setdefault("properties", {}).update(
            {
                "id": zone.get("id"),
                "zone_id": zone.get("id"),
                "zone_name": zone.get("name"),
                "name": zone.get("name"),
                "admin_name": admin_name,
                "level": zone.get("level"),
                "tone": zone.get("tone"),
                "signals": zone.get("signals") or [],
                "recommendations": zone.get("recommendations") or [],
                "source": "geoBoundaries ADM1 + Agentium scoring",
            }
        )
        features.append(copied)
    return features


def _cities_geojson() -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": f"city-{marker['name'].lower().replace(' ', '-')}",
                "geometry": {"type": "Point", "coordinates": marker["coordinates"]},
                "properties": {
                    "name": marker["name"],
                    "kind": marker["kind"],
                    "weight": marker["weight"],
                    "scope": marker.get("scope", "ci"),
                    "source": "sentinel-ci-territorial-reference",
                },
            }
            for marker in SENTINEL_CONTEXT_MARKERS
        ],
    }


def _event_points_geojson(zones: list[dict[str, Any]]) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    for zone in zones:
        centroid = SENTINEL_ZONE_GEOGRAPHY.get(str(zone.get("id") or ""), {}).get("centroid")
        if not centroid:
            continue
        zone_name = str(zone.get("name") or "Zone")
        score = int(zone.get("level") or zone.get("score", {}).get("score") or 0)
        events = [
            {
                "suffix": "press",
                "layer_key": "open-intelligence",
                "source_kind": "news_lab",
                "title": f"Signal presse · {zone_name}",
                "summary": (zone.get("drivers") or zone.get("signals") or [f"Signal prioritaire {zone_name}"])[0],
                "offset": [-0.10, 0.08],
                "confidence": 0.72,
            },
            {
                "suffix": "project",
                "layer_key": "strategic-projects",
                "source_kind": "project_record",
                "title": f"Projet sensible · {zone_name}",
                "summary": "Point d'avancement a relier aux arbitrages cabinet.",
                "offset": [0.12, -0.05],
                "confidence": 0.69,
            },
        ]
        if score >= 45:
            events.append(
                {
                    "suffix": "action",
                    "layer_key": "preventive-actions",
                    "source_kind": "action_planner",
                    "title": f"Action recommandee · {zone_name}",
                    "summary": (zone.get("recommendations") or ["Action preventive a qualifier"])[0],
                    "offset": [0.02, 0.16],
                    "confidence": 0.74,
                }
            )
        for event in events:
            lon = round(float(centroid[0]) + event["offset"][0], 5)
            lat = round(float(centroid[1]) + event["offset"][1], 5)
            features.append(
                {
                    "type": "Feature",
                    "id": f"{zone.get('id')}-{event['suffix']}",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": {
                        "zone_id": zone.get("id"),
                        "zone_name": zone_name,
                        "layer_key": event["layer_key"],
                        "source_kind": event["source_kind"],
                        "title": event["title"],
                        "summary": event["summary"],
                        "score": score,
                        "tone": zone.get("tone"),
                        "confidence": event["confidence"],
                        "freshness": "7d",
                        "source_label": "SENTINEL-CI · source qualifiee",
                    },
                }
            )
    return {"type": "FeatureCollection", "features": features}


def _maritime_geojson_sources() -> dict[str, dict[str, Any]]:
    point_features = []
    density_features = []
    operating_area = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "maritime-gulf-of-guinea-operating-area",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-9.35, 3.95],
                            [-1.05, 3.95],
                            [-1.05, 4.98],
                            [-2.95, 5.02],
                            [-4.10, 5.03],
                            [-6.58, 4.67],
                            [-9.35, 4.60],
                            [-9.35, 3.95],
                        ]
                    ],
                },
                "properties": {
                    "name": "Zone maritime suivie · Golfe de Guinee",
                    "layer_key": "maritime-traffic",
                    "source_kind": "maritime_operating_area",
                    "visual_role": "operating_area",
                    "render_tone": "maritime_area",
                    "status": "monitoring",
                    "confidence": 0.66,
                    "source": "zone maritime demo-safe",
                },
            }
        ],
    }
    for port in MARITIME_PORTS:
        point_features.append(
            {
                "type": "Feature",
                "id": port["id"],
                "geometry": {"type": "Point", "coordinates": [port["longitude"], port["latitude"]]},
                "properties": {
                    "kind": "port",
                    "layer_key": "maritime-traffic",
                    "source_kind": "port_snapshot",
                    "visual_role": "port",
                    "render_tone": "port_primary" if port["id"] == "port-abidjan" else "port_secondary",
                    **port,
                },
            }
        )
    for event in MARITIME_EVENTS:
        feature = {
            "type": "Feature",
            "id": event["id"],
            "geometry": {"type": "Point", "coordinates": [event["longitude"], event["latitude"]]},
            "properties": {
                "kind": "vessel_snapshot",
                "layer_key": "maritime-traffic",
                "source_kind": "maritime_snapshot",
                "visual_role": "vessel",
                "render_tone": "vessel_snapshot",
                **event,
            },
        }
        point_features.append(feature)
        density_features.append(feature)
    for zone in _maritime_density_zones():
        density_features.append(
            {
                "type": "Feature",
                "id": zone["id"],
                "geometry": {"type": "Point", "coordinates": zone["coordinates"]},
                "properties": {
                    **zone,
                    "kind": "density_zone",
                    "layer_key": "maritime-traffic",
                    "source_kind": "maritime_snapshot",
                    "visual_role": "density",
                    "render_tone": "density_elevated" if zone.get("status") == "elevated" else "density_monitoring",
                    "source": "snapshot maritime demo-safe",
                },
            }
        )
    for disruption in _maritime_disruptions():
        point_features.append(
            {
                "type": "Feature",
                "id": disruption["id"],
                "geometry": {"type": "Point", "coordinates": disruption["coordinates"]},
                "properties": {
                    **disruption,
                    "kind": "disruption",
                    "layer_key": "maritime-traffic",
                    "source_kind": "port_customs_watch",
                    "visual_role": "disruption",
                    "render_tone": "customs_disruption" if disruption.get("severity") == "elevated" else "customs_watch",
                    "source": "port + douanes + veille economique",
                },
            }
        )
    route_features = [
        {
            "type": "Feature",
            "id": "route-gulf-abidjan",
            "geometry": {
                "type": "LineString",
                "coordinates": [[-1.2, 4.85], [-2.7, 4.78], [-4.05, 4.92], [-6.66, 4.52], [-9.1, 4.55]],
            },
            "properties": {
                "name": "Corridor Golfe de Guinee",
                "layer_key": "maritime-traffic",
                "visual_role": "corridor",
                "render_tone": "maritime_corridor",
                "status": "monitoring",
                "confidence": 0.66,
                "source": "demo-safe maritime corridor",
            },
        },
        {
            "type": "Feature",
            "id": "route-approche-abidjan-vridi",
            "geometry": {
                "type": "LineString",
                "coordinates": [[-4.45, 4.82], [-4.22, 4.96], [-4.08, 5.12], [-4.0083, 5.2512]],
            },
            "properties": {
                "name": "Approche portuaire Abidjan / Vridi",
                "layer_key": "maritime-traffic",
                "visual_role": "port_approach",
                "render_tone": "port_approach",
                "status": "watch",
                "confidence": 0.62,
                "source": "port + douanes + economie",
            },
        },
        {
            "type": "Feature",
            "id": "route-approche-san-pedro",
            "geometry": {
                "type": "LineString",
                "coordinates": [[-7.15, 4.56], [-6.91, 4.62], [-6.72, 4.70], [-6.6368, 4.7446]],
            },
            "properties": {
                "name": "Approche portuaire San Pedro",
                "layer_key": "maritime-traffic",
                "visual_role": "port_approach",
                "render_tone": "port_approach",
                "status": "stable",
                "confidence": 0.58,
                "source": "port + export + economie",
            },
        },
    ]
    return {
        "maritime_area": operating_area,
        "maritime_points": {"type": "FeatureCollection", "features": point_features},
        "maritime_routes": {"type": "FeatureCollection", "features": route_features},
        "maritime_density": {"type": "FeatureCollection", "features": density_features},
    }


def _maritime_snapshot_payload() -> dict[str, Any]:
    density_zones = _maritime_density_zones()
    disruptions = _maritime_disruptions()
    return {
        "mode": "snapshot_demo_safe",
        "provider": "demo-safe / AIS optional",
        "provider_configured": False,
        "ports": MARITIME_PORTS,
        "events": MARITIME_EVENTS,
        "bbox": {"west": -9.35, "south": 3.95, "east": -1.05, "north": 5.25},
        "density_zones": density_zones,
        "disruptions": disruptions,
        "freshness": {
            "status": "ready",
            "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "ttl_seconds": 300,
            "cache_policy": "bbox_quantized_snapshot",
        },
        "summary": "Lecture portuaire demo-safe : Abidjan et San Pedro, corridors Golfe de Guinee, densite indicative et liens douanes/projets.",
        "limitations": [
            "Pas de promesse de live AIS sans provider active.",
            "Les points navires sont un snapshot demonstratif et non un suivi individuel.",
        ],
    }


def _maritime_density_zones() -> list[dict[str, Any]]:
    return [
        {
            "id": "density-abidjan-vridi",
            "name": "Densite Abidjan / Vridi",
            "coordinates": [-4.055, 5.205],
            "radius_km": 22,
            "intensity": 0.72,
            "vessel_count": 18,
            "delta_pct": 12,
            "status": "elevated",
            "score": 72,
            "confidence": 0.66,
            "summary": "Densite indicative autour du port d'Abidjan, utile pour lecture douanes, approvisionnement et projets BTP.",
            "recommended_action": "Croiser douanes, agenda economique et communication gouvernementale avant 14h.",
        },
        {
            "id": "density-san-pedro",
            "name": "Densite San Pedro",
            "coordinates": [-6.67, 4.72],
            "radius_km": 18,
            "intensity": 0.42,
            "vessel_count": 7,
            "delta_pct": -3,
            "status": "monitoring",
            "score": 48,
            "confidence": 0.61,
            "summary": "Flux export a surveiller, sans signal critique dans le scenario courant.",
            "recommended_action": "Maintenir veille hebdomadaire.",
        },
    ]


def _maritime_disruptions() -> list[dict[str, Any]]:
    return [
        {
            "id": "disruption-abidjan-customs-window",
            "title": "Fenetre douanes / Port d'Abidjan",
            "coordinates": [-4.0244, 5.3453],
            "severity": "elevated",
            "score": 69,
            "confidence": 0.64,
            "status": "watch",
            "summary": "Signal economique reliant port d'Abidjan, dossier BTP et calendrier cabinet.",
            "recommended_action": "Preparer une note courte avant arbitrage budgetaire.",
            "decision_deadline": "14:00",
        },
        {
            "id": "disruption-gulf-route-watch",
            "title": "Corridor Golfe de Guinee sous surveillance",
            "coordinates": [-3.35, 4.82],
            "severity": "monitoring",
            "score": 54,
            "confidence": 0.58,
            "status": "monitoring",
            "summary": "Transit regional nominal mais a relier aux signaux presse CEDEAO.",
            "recommended_action": "Aucun arbitrage immediat, conserver veille.",
            "decision_deadline": "24-48h",
        },
    ]


def _region_scores(zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "zone_id": zone.get("id"),
            "name": zone.get("name"),
            "score": int(zone.get("level") or zone.get("score", {}).get("score") or 0),
            "tone": zone.get("tone"),
            "admin1_refs": zone.get("admin1_refs") or [],
            "drivers": zone.get("drivers") or zone.get("signals") or [],
            "sources": zone.get("sources") or [],
        }
        for zone in zones
    ]


def _source_health(source_counts: dict[str, int]) -> dict[str, Any]:
    layers = []
    for item in _layer_registry(source_counts):
        layers.append(
            {
                "layer_key": item["key"],
                "label": item["label"],
                "status": item["status"],
                "count": item["count"],
                "freshness": item["freshness"],
                "freshness_at": item["freshness_at"],
                "failure_reason": item["failure_reason"],
                "confidence": item["confidence"],
                "source_kind": item["source_kind"],
            }
        )
    return {
        "status": "ready",
        "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "layers": layers,
        "notes": "Toutes les couches sont workspace-scopees et restent advisory-only.",
    }


def _tooltip_templates() -> dict[str, dict[str, str]]:
    return {
        "zone_score": {
            "title": "{name} · {level}/100",
            "body": "{summary}",
            "footer": "Sources : presse, projets, agenda, visuel",
        },
        "signal": {
            "title": "{title}",
            "body": "{summary}",
            "footer": "Confiance {confidence}",
        },
        "project": {
            "title": "{title}",
            "body": "{summary}",
            "footer": "Projet sensible · advisory-only",
        },
        "agenda_window": {
            "title": "{label}",
            "body": "{why}",
            "footer": "{start}-{end}",
        },
        "visual_observation": {
            "title": "{title}",
            "body": "{summary}",
            "footer": "Pas de biometrie · validation humaine",
        },
        "maritime_snapshot": {
            "title": "{title}",
            "body": "{summary}",
            "footer": "Snapshot demo-safe · AIS optionnel",
        },
        "action": {
            "title": "{title}",
            "body": "{recommended_action}",
            "footer": "Validation requise",
        },
    }


def _default_layer_groups() -> dict[str, list[str]]:
    return {
        "explorer": ["territorial-risk", "open-intelligence", "strategic-projects", "visual-streams"],
        "comprendre": ["territorial-risk", "open-intelligence", "regional-context", "visual-streams", "maritime-traffic"],
        "decider": ["territorial-risk", "agenda-windows", "preventive-actions", "strategic-projects", "maritime-traffic"],
        "maritime": ["maritime-traffic", "open-intelligence", "strategic-projects", "preventive-actions"],
    }


def _scenario_modes_payload() -> list[dict[str, Any]]:
    return [
        {
            "key": "explorer",
            "label": "Explorer",
            "goal": "Surveiller posture, couches, signaux et fraîcheur des sources.",
            "active_layers": ["territorial-risk", "open-intelligence", "regional-context"],
            "default_question": "Que se passe-t-il et où regarder en priorité ?",
        },
        {
            "key": "comprendre",
            "label": "Comprendre",
            "goal": "Relier zones, rumeurs, projets, agenda, visuel et sources.",
            "active_layers": ["territorial-risk", "open-intelligence", "strategic-projects", "visual-streams"],
            "default_question": "Pourquoi cette zone mérite-t-elle l'attention du cabinet ?",
        },
        {
            "key": "decider",
            "label": "Décider",
            "goal": "Comparer options, échéances, impact, coût et confiance.",
            "active_layers": ["territorial-risk", "agenda-windows", "preventive-actions", "maritime-traffic"],
            "default_question": "Quelle action recommander et avant quelle fenêtre ?",
        },
    ]


def _forecast_signals_payload(zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    signals = []
    for zone in zones[:5]:
        score = int(zone.get("level") or (zone.get("score") or {}).get("score") or 0)
        if score < 25:
            continue
        label = zone.get("name") or zone.get("id")
        signals.append(
            {
                "id": f"forecast-{zone.get('id')}",
                "zone_id": zone.get("id"),
                "title": f"{label} · trajectoire { _tone_for(score) }",
                "horizon": "24-48h" if score >= 45 else "7j",
                "score": score,
                "confidence": min(86, max(54, int(zone.get("confidence") or score + 8))),
                "drivers": zone.get("drivers") or zone.get("signals") or [],
                "recommended_action": (zone.get("recommendations") or ["Maintenir la veille qualifiée"])[0],
                "source_refs": zone.get("sources") or [],
            }
        )
    signals.extend(
        [
            {
                "id": "forecast-port-abidjan",
                "zone_id": "port-abidjan",
                "title": "Port d'Abidjan · vigilance douanes",
                "horizon": "24h",
                "score": 58,
                "confidence": 66,
                "drivers": ["congestion indicative", "fenêtre arbitrage import", "presse économique"],
                "recommended_action": "Qualifier l'impact sur les projets sensibles avant midi.",
                "source_refs": ["src-maritime-paa-001", "src-maritime-marinelink-001"],
            }
        ]
    )
    return signals


def _slugify(value: str) -> str:
    normalized = (value or "").lower().replace("'", "").replace("/", " ")
    return "-".join(part for part in normalized.replace("_", " ").split() if part)


def serialize_zone(zone: WorkspaceMapZone, score: Optional[WorkspaceMapScore] = None) -> dict[str, Any]:
    zone_definition = SENTINEL_ZONE_GEOGRAPHY.get(zone.zone_key) or {}
    payload = {
        "id": zone.zone_key,
        "zone_id": zone.id,
        "name": zone.name,
        "level": score.score if score else zone.level,
        "tone": _tone_for(score.score if score else zone.level),
        "centroid": zone.centroid or {},
        "polygon": zone.polygon,
        "geometry_kind": "geoBoundaries.ADM1_group",
        "admin1_refs": list(zone_definition.get("admin1") or []),
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
            "accuracy": "geojson_admin_boundaries_v1",
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
    basemap: Optional[str] = None,
    time_range: Optional[str] = None,
    camera: Optional[dict[str, Any]] = None,
    annotation: Optional[dict[str, Any]] = None,
    user: Optional[User] = None,
) -> dict[str, Any]:
    """Build a provider-neutral map command scoped to the current workspace."""
    map_row = get_workspace_map(db, workspace, map_id_or_slug)
    payload = mission_room_map_payload(db, workspace)
    map_system = payload["map_system"]
    normalized_intent = "show_sources" if intent == "open_source_panel" else intent
    normalized_intent = normalized_intent if normalized_intent in MAP_COMMAND_INTENTS else "focus_zone"
    zones = payload.get("zones") or []
    selected_port = None if normalized_intent == "reset_view" else _find_port_payload(target)
    selected = None if normalized_intent in {"reset_view", "focus_port", "show_vessel_snapshot", "show_disruption"} else _find_zone_payload(zones, target)
    if normalized_intent != "reset_view" and not selected_port:
        selected = selected or payload.get("score_summary", {}).get("top_zone")
    selected_key = selected.get("id") if selected else None
    presets = map_system.get("camera_presets") or {}
    port_key = selected_port.get("id") if selected_port else None
    selected_camera = (
        camera
        or (presets.get("country") if normalized_intent == "reset_view" else presets.get(port_key or selected_key))
        or presets.get("country")
    )
    default_state = map_system.get("default_map_state") or {}
    layer_catalog = map_system.get("layer_catalog") or []
    allowed_layers = {layer.get("key") for layer in layer_catalog}
    requested_layers = [layer for layer in (layers or []) if not allowed_layers or layer in allowed_layers]
    default_active_layers = list(
        default_state.get("active_layers")
        or [layer["key"] for layer in DEFAULT_RENDERER_LAYERS if layer.get("visible")]
    )
    if requested_layers:
        active_layers = requested_layers
    elif normalized_intent in {"focus_port", "show_vessel_snapshot", "show_disruption"}:
        active_layers = ["territorial-risk", "open-intelligence", "maritime-traffic", "preventive-actions"]
    elif normalized_intent in {"set_layers", "reset_view"}:
        active_layers = default_active_layers
    else:
        active_layers = default_active_layers
    basemap_options = {option.get("key") for option in map_system.get("basemap_options") or []}
    selected_basemap = basemap if basemap in basemap_options else default_state.get("basemap") or "command"
    selected_time_range = time_range if time_range in {item["key"] for item in MAP_TIME_RANGES} else default_state.get("time_range") or "7d"
    explanation = _command_explanation(normalized_intent, selected, selected_basemap, selected_port=selected_port, time_range=selected_time_range)
    sources = _port_sources(selected_port) if selected_port else _zone_sources(selected)
    target_key = port_key or selected_key
    target_label = selected_port.get("name") if selected_port else (selected.get("name") if selected else None)
    command = {
        "command_id": str(uuid4()),
        "map_id": map_row.id,
        "map_slug": map_row.slug,
        "intent": normalized_intent,
        "target": target_key,
        "target_label": target_label,
        "map_state": {
            "renderer": map_system.get("renderer_config", {}).get("renderer", "maplibre"),
            "selected_zone": selected_key,
            "selected_port": port_key,
            "active_layers": active_layers,
            "basemap": selected_basemap,
            "time_range": selected_time_range,
            "camera": selected_camera,
            "focus_marker": {
                "longitude": selected_port.get("longitude"),
                "latitude": selected_port.get("latitude"),
                "label": selected_port.get("name"),
                "tone": "maritime",
            }
            if selected_port
            else None,
            "annotation": annotation
            or {
                "label": target_label or "Cote d'Ivoire",
                "summary": explanation,
                "tone": (selected_port.get("tone") if selected_port else selected.get("tone")) if (selected_port or selected) else "monitoring",
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
            "target": target_key,
            "layers": active_layers,
            "basemap": selected_basemap,
            "time_range": selected_time_range,
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
    """Small deterministic executive assistant action for map-centric questions.

    The heavy RAG path remains available for open questions. This branch is
    deliberately narrow: it emits a structured map command when the user asks
    the assistant to show/focus/highlight territorial zones.
    """
    if assistant_profile != "vigie_executive":
        return None
    normalized = (query or "").lower()
    explicit_map_terms = (
        "carte",
        "zoom",
        "montre",
        "affiche",
        "visualise",
        "focalise",
        "ouvre",
        "couche",
        "couches",
        "layer",
        "fond",
        "basemap",
        "réinitialise",
        "reinitialise",
    )
    port_target = _extract_port_target(normalized)
    explicit_port_map = bool(port_target) and any(
        term in normalized
        for term in (
            "montre",
            "affiche",
            "visualise",
            "carte",
            "zoom",
            "focalise",
            "couche maritime",
            "couches maritime",
        )
    )
    if not any(term in normalized for term in explicit_map_terms) and not explicit_port_map:
        return None
    intent = "focus_zone"
    basemap = None
    layers = None
    target = _extract_zone_target(normalized)
    if port_target:
        intent = "focus_port"
        target = port_target
        layers = ["territorial-risk", "open-intelligence", "maritime-traffic", "preventive-actions"]
        if "navire" in normalized or "bateau" in normalized:
            intent = "show_vessel_snapshot"
        if "risque" in normalized or "douane" in normalized or "douanes" in normalized:
            intent = "show_disruption"
    if "source" in normalized:
        intent = "show_sources"
    if "fenetre" in normalized or "créneau" in normalized or "creneau" in normalized:
        intent = "show_action_window"
    if "compare" in normalized or "changé" in normalized or "change" in normalized:
        intent = "compare_before_after"
    if "réinitialise" in normalized or "reinitialise" in normalized or "côte d'ivoire" in normalized or "cote d'ivoire" in normalized:
        intent = "reset_view"
    if "fond" in normalized or "basemap" in normalized:
        intent = "set_basemap"
        if "contour" in normalized:
            basemap = "contours"
        elif "sombre" in normalized:
            basemap = "dark"
        elif "commandement" in normalized or "worldmonitor" in normalized:
            basemap = "command"
        else:
            basemap = "administrative"
    command = build_map_command(
        db,
        workspace,
        intent=intent,
        target=target,
        layers=layers,
        basemap=basemap,
        user=user,
    )
    label = command.get("target_label") or "les zones prioritaires"
    if intent in {"focus_port", "show_vessel_snapshot", "show_disruption"}:
        content = (
            f"J'affiche {label} avec les couches maritime, douanes, presse et actions. "
            "Lecture demo-safe : ports, corridor Golfe de Guinee, densite indicative et options cabinet."
        )
    else:
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
    source_counts = _source_counts(zones)
    basemap_options = _map_basemap_options()
    default_layers = [layer["key"] for layer in DEFAULT_RENDERER_LAYERS if layer["visible"]]
    zone_features = []
    marker_features = []
    context_features = []
    line_features = []
    arc_links = []
    abidjan = [-4.0244, 5.3453]
    for zone in zones:
        centroid = _zone_lonlat_centroid(zone, view_box)
        zone_features.extend(_zone_geojson_features(zone))
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
                    "scope": marker.get("scope", "ci"),
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
    event_points = _event_points_geojson(zones)
    maritime_sources = _maritime_geojson_sources()
    default_basemap = "command"
    return {
        "map_version": "situation_map_v3",
        "rendering_profile": "executive_command_v1",
        "time_range": "7d",
        "available_time_ranges": MAP_TIME_RANGES,
        "renderer_config": {
            "renderer": "maplibre",
            "rendering_profile": "executive_command_v1",
            "fallback_renderer": "svg",
            "basemap_policy": "public_osm_carto_with_self_hosted_ready",
            "default_basemap": default_basemap,
            "style": basemap_options[0]["style"],
            "initial_view_state": camera_presets["country"],
            "bounds": [[IVORY_COAST_BOUNDS["west"], IVORY_COAST_BOUNDS["south"]], [IVORY_COAST_BOUNDS["east"], IVORY_COAST_BOUNDS["north"]]],
            "regional_bounds": [[REGIONAL_CONTEXT_BOUNDS["west"], REGIONAL_CONTEXT_BOUNDS["south"]], [REGIONAL_CONTEXT_BOUNDS["east"], REGIONAL_CONTEXT_BOUNDS["north"]]],
            "attribution": "Fond OSM/CARTO · frontières geoBoundaries CC BY 4.0 · contexte CEDEAO Agentium workspace",
            "interaction_contract": {
                "commands": sorted(MAP_COMMAND_INTENTS),
                "scenario_modes": [mode["key"] for mode in _scenario_modes_payload()],
                "selection": "zone",
                "events": ["zone_selected", "map_state_updated", "source_panel_requested"],
            },
        },
        "basemap_options": basemap_options,
        "layer_catalog": _layer_catalog(source_counts),
        "layer_registry": _layer_registry(source_counts),
        "default_map_state": {
            "basemap": default_basemap,
            "active_layers": default_layers,
            "selected_zone": zones[0]["id"] if zones else None,
            "camera": camera_presets["country"],
            "time_range": "7d",
            "mode": "explorer",
        },
        "geodata_metadata": _geo_metadata(),
        "country_boundary": _country_boundary_geojson(),
        "district_boundaries": _district_boundaries_geojson(),
        "admin_boundaries": _admin_boundaries_geojson(),
        "cities": _cities_geojson(),
        "region_scores": _region_scores(zones),
        "event_points": event_points,
        "maritime_snapshot": _maritime_snapshot_payload(),
        "source_health": _source_health(source_counts),
        "forecast_signals": _forecast_signals_payload(zones),
        "scenario_modes": _scenario_modes_payload(),
        "default_layer_groups": _default_layer_groups(),
        "tooltip_templates": _tooltip_templates(),
        "source_counts": source_counts,
        "geojson_sources": {
            "zones": {"type": "FeatureCollection", "features": zone_features},
            "markers": {"type": "FeatureCollection", "features": marker_features},
            "context_markers": {"type": "FeatureCollection", "features": context_features},
            "context_lines": {"type": "FeatureCollection", "features": line_features},
            "event_points": event_points,
            **maritime_sources,
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
    return _polygon_to_lonlat(zone.get("polygon") or "", view_box)


def _zone_lonlat_centroid(zone: dict[str, Any], view_box: tuple[float, float, float, float]) -> Optional[list[float]]:
    seeded = SENTINEL_ZONE_GEOGRAPHY.get(str(zone.get("id") or ""))
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
            "longitude": -5.75,
            "latitude": 7.95,
            "zoom": 5.85,
            "pitch": 0,
            "bearing": 0,
            "duration_ms": 900,
        },
        "regional": {
            "longitude": -5.95,
            "latitude": 8.20,
            "zoom": 4.85,
            "pitch": 0,
            "bearing": 0,
            "duration_ms": 900,
        }
    }
    for port in MARITIME_PORTS:
        presets[port["id"]] = {
            "longitude": port["longitude"],
            "latitude": port["latitude"],
            "zoom": 8.65 if port["id"] == "port-abidjan" else 8.35,
            "pitch": 0,
            "bearing": 0,
            "duration_ms": 850,
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
            "pitch": 0,
            "bearing": 0,
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


def _find_port_payload(target: Optional[str]) -> Optional[dict[str, Any]]:
    if not target:
        return None
    normalized = target.lower().strip()
    aliases = {
        "abidjan": "port-abidjan",
        "port-abidjan": "port-abidjan",
        "vridi": "port-abidjan",
        "san pedro": "port-san-pedro",
        "san-pedro": "port-san-pedro",
        "port-san-pedro": "port-san-pedro",
    }
    canonical = aliases.get(normalized, normalized)
    for port in MARITIME_PORTS:
        if canonical in {str(port.get("id", "")).lower(), str(port.get("name", "")).lower()}:
            return port
        if canonical and canonical in str(port.get("name", "")).lower():
            return port
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


def _extract_port_target(query: str) -> Optional[str]:
    if any(label in query for label in ("san pedro", "san-pedro")):
        return "port-san-pedro"
    if any(label in query for label in ("port", "abidjan", "vridi", "douane", "douanes", "maritime", "navire", "bateau")):
        return "port-abidjan"
    return None


def _command_explanation(
    intent: str,
    selected: Optional[dict[str, Any]],
    basemap: Optional[str] = None,
    *,
    selected_port: Optional[dict[str, Any]] = None,
    time_range: Optional[str] = None,
) -> str:
    if intent == "reset_view":
        return "Vue Côte d'Ivoire réinitialisée avec les couches ministérielles par défaut."
    if intent == "set_basemap":
        return f"Fond cartographique basculé sur {basemap or 'le fond par défaut'}."
    if intent == "set_time_range":
        return f"Fenêtre temporelle basculée sur {time_range or 'la tendance active'}."
    if intent == "set_layers":
        return "Couches ministérielles ajustées pour la lecture territoriale demandée."
    if intent in {"focus_port", "show_vessel_snapshot", "show_disruption"} and selected_port:
        return (
            f"Focus portuaire sur {selected_port.get('name')} : couche maritime, douanes, presse et actions "
            "préventives activées pour une lecture économique et gouvernementale."
        )
    if not selected:
        return "Vue consolidee de la posture territoriale et des signaux qualifiés."
    name = selected.get("name")
    if intent == "show_action_window":
        return f"Fenêtres recommandées pour une action préventive sur la zone {name}."
    if intent == "show_sources":
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


def _port_sources(selected_port: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    if not selected_port:
        return [{"title": "Maritime / douanes", "kind": "maritime_snapshot", "source_label": "Couche maritime"}]
    return [
        {
            "title": selected_port.get("name"),
            "kind": "port_snapshot",
            "source_label": "Flux maritime demo-safe",
            "port": selected_port.get("id"),
        },
        {
            "title": "Corridor Golfe de Guinee",
            "kind": "maritime_route",
            "source_label": "Route maritime indicative",
            "port": selected_port.get("id"),
        },
        {
            "title": "Douanes / economie",
            "kind": "cabinet_context",
            "source_label": "Contexte ministeriel",
            "port": selected_port.get("id"),
        },
    ]
