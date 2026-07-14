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
from app.models.workspace_map import (
    WorkspaceMap,
    WorkspaceMapLayer,
    WorkspaceMapScore,
    WorkspaceMapSignal,
    WorkspaceMapZone,
)
from app.services.audit_logger import emit_audit_event
from app.services.maritime_tracking import (
    fetch_snapshot as fetch_maritime_snapshot,
)
from app.services.maritime_tracking import (
    fetch_vessels_in_bbox,
    serialize_vessel,
)
from app.services.scenario_engine import generate_scenarios
from app.services.workspace_jobs import transition_job

SENTINEL_MAP_SLUG = "sentinel-ci-strategic-map"
TERRITORIAL_INTELLIGENCE_COLLECTION = "sentinel-ci-territorial-intelligence"
GEO_DATA_DIR = Path(__file__).resolve().parents[1] / "resources" / "geo" / "civ"

OCTOCITY_WORKSPACE_SLUG = "octocity-mission-room"
OCTOCITY_MISSION_ROOM_PROFILE = "octocity_institutional_v1"
OCTOCITY_MAP_SLUG = "octocity-operating-map"
OCTOCITY_MAP_FIXTURE_PROFILE = "octocity_france_v1"
OCTOCITY_MAP_FIXTURE_VERSION = 1

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
    # S3 — Posture securitaire dual-axis layers. Off by default; turned on via
    # AYA actions aya.show_social_pulse / aya.show_troops_movement /
    # aya.trace_rumor_origin which emit ``map_command`` set_layers commands.
    {
        "key": "social-geo",
        "label": "Pulsation sociale Abidjan",
        "short_label": "Social",
        "deck_group": "social",
        "tone": "cyan",
        "kind": "social_signal",
        "visible": False,
        "payload": {"sources": ["social_snapshot_demo_safe"]},
        "sort_order": 70,
    },
    {
        "key": "military-air",
        "label": "ADS-B advisory Sahel",
        "short_label": "ADS-B",
        "deck_group": "security",
        "tone": "amber",
        "kind": "ads_b_advisory",
        "visible": False,
        "payload": {"sources": ["ads_b_advisory_snapshot"]},
        "sort_order": 72,
    },
    {
        "key": "border-tension",
        "label": "Tension frontiere Nord",
        "short_label": "Frontiere",
        "deck_group": "security",
        "tone": "orange",
        "kind": "border_tension",
        "visible": False,
        "payload": {"sources": ["rumor_dossier"]},
        "sort_order": 74,
    },
    {
        "key": "satellite-footprint",
        "label": "Empreintes satellite advisory",
        "short_label": "Satellite",
        "deck_group": "security",
        "tone": "amber",
        "kind": "satellite_scene",
        "visible": False,
        "payload": {"sources": ["satellite_baseline"]},
        "sort_order": 76,
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


# Octocity is a product showcase derived from the Mission Room foundation, not
# an alias of the Sentinel-CI tenant.  Its map fixture therefore has its own
# persisted identity and geography.  These coordinates mirror the Octocity
# frontend fallback and contain no Sentinel/Ivorian source data.
OCTOCITY_MAP_BOUNDS = {
    "west": -5.3,
    "south": 42.35,
    "east": 8.1,
    "north": 50.8,
}

OCTOCITY_ZONE_GEOGRAPHY = {
    "zone-nord": {
        "centroid": [2.8, 48.55],
        "polygon": [[1.0, 47.9], [4.5, 47.9], [4.8, 49.5], [1.3, 49.7], [1.0, 47.9]],
    },
    "zone-ouest": {
        "centroid": [-1.7, 46.3],
        "polygon": [[-4.8, 44.5], [-0.2, 44.7], [0.0, 48.2], [-4.2, 48.4], [-4.8, 44.5]],
    },
    "zone-centre": {
        "centroid": [3.25, 45.75],
        "polygon": [[1.0, 44.0], [5.3, 44.0], [5.5, 47.3], [1.2, 47.4], [1.0, 44.0]],
    },
    "zone-est": {
        "centroid": [6.5, 47.6],
        "polygon": [[4.9, 45.5], [8.0, 45.3], [8.0, 49.7], [5.1, 49.8], [4.9, 45.5]],
    },
    "zone-sud": {
        "centroid": [4.45, 43.35],
        "polygon": [[-1.0, 42.4], [7.5, 42.4], [7.8, 44.8], [-0.5, 45.0], [-1.0, 42.4]],
    },
}

OCTOCITY_ZONE_SEED = [
    {
        "key": "zone-nord",
        "name": "Northern Arc",
        "level": 72,
        "tone": "watch",
        "centroid": {"x": 338, "y": 146},
        "polygon": "265,62 383,72 444,140 410,222 312,212 235,158",
        "signals": ["Transport corridor variance", "Public-service backlog", "Regional signal cluster"],
        "recommendations": ["Prepare an executive review", "Confirm the operating window"],
        "sources": ["src-octocity-map-001", "src-octocity-news-014"],
    },
    {
        "key": "zone-ouest",
        "name": "Atlantic Corridor",
        "level": 61,
        "tone": "watch",
        "centroid": {"x": 280, "y": 245},
        "polygon": "205,155 330,145 370,250 310,345 190,305 165,215",
        "signals": ["Logistics capacity watch", "Field coordination request"],
        "recommendations": ["Validate the logistics brief", "Maintain weekly monitoring"],
        "sources": ["src-octocity-logistics-003"],
    },
    {
        "key": "zone-centre",
        "name": "Central Hub",
        "level": 68,
        "tone": "watch",
        "centroid": {"x": 425, "y": 270},
        "polygon": "340,175 475,165 525,275 470,360 350,345 315,255",
        "signals": ["Decision queue pressure", "Executive calendar constraint"],
        "recommendations": ["Schedule a coordination review", "Prioritize the human validation queue"],
        "sources": ["src-octocity-decision-007", "src-octocity-agenda-002"],
    },
    {
        "key": "zone-est",
        "name": "Rhine Interface",
        "level": 58,
        "tone": "stable",
        "centroid": {"x": 560, "y": 240},
        "polygon": "485,130 615,150 650,270 590,360 500,330 515,225",
        "signals": ["Cross-region coordination", "Industrial signal review"],
        "recommendations": ["Keep the interface brief current"],
        "sources": ["src-octocity-interface-005"],
    },
    {
        "key": "zone-sud",
        "name": "Mediterranean Gate",
        "level": 76,
        "tone": "critical",
        "centroid": {"x": 430, "y": 420},
        "polygon": "285,345 545,340 580,455 485,510 300,485 245,405",
        "signals": ["Port capacity watch", "Executive action window"],
        "recommendations": ["Confirm the operating plan", "Prepare a sourced decision brief"],
        "sources": ["src-octocity-port-011", "src-octocity-action-004"],
    },
]

OCTOCITY_CONTEXT_MARKERS = [
    {"name": "Paris", "kind": "coordination", "coordinates": [2.3522, 48.8566], "weight": 96},
    {"name": "Lille", "kind": "news_flow", "coordinates": [3.0573, 50.6292], "weight": 78},
    {"name": "Rennes", "kind": "field_ops", "coordinates": [-1.6778, 48.1173], "weight": 73},
    {"name": "Nantes", "kind": "logistics", "coordinates": [-1.5536, 47.2184], "weight": 82},
    {"name": "Bordeaux", "kind": "field_ops", "coordinates": [-0.5792, 44.8378], "weight": 77},
    {"name": "Toulouse", "kind": "industry", "coordinates": [1.4442, 43.6047], "weight": 74},
    {"name": "Lyon", "kind": "operations", "coordinates": [4.8357, 45.764], "weight": 86},
    {"name": "Marseille", "kind": "port", "coordinates": [5.3698, 43.2965], "weight": 88},
    {"name": "Nice", "kind": "field_ops", "coordinates": [7.262, 43.7102], "weight": 70},
    {"name": "Strasbourg", "kind": "coordination", "coordinates": [7.7521, 48.5734], "weight": 79},
]

OCTOCITY_PORTS = [
    {
        "id": "port-marseille",
        "name": "Marseille Logistics Gate",
        "location": "Marseille",
        "longitude": 5.3698,
        "latitude": 43.2965,
        "score": 64,
        "tone": "watch",
        "status": "monitoring",
        "role": "Synthetic logistics gateway used by the Octocity operating fixture.",
    },
    {
        "id": "port-nantes",
        "name": "Nantes Atlantic Gate",
        "location": "Nantes",
        "longitude": -1.5536,
        "latitude": 47.2184,
        "score": 52,
        "tone": "stable",
        "status": "monitoring",
        "role": "Synthetic Atlantic gateway used by the Octocity operating fixture.",
    },
]

OCTOCITY_CONTEXT_LINES = [
    {"name": "Paris-Lyon decision axis", "path": [[2.3522, 48.8566], [4.8357, 45.764]], "tone": "regional"},
    {"name": "Rhone corridor", "path": [[4.8357, 45.764], [5.3698, 43.2965]], "tone": "watch"},
    {"name": "Northern coordination link", "path": [[2.3522, 48.8566], [3.0573, 50.6292]], "tone": "regional"},
    {"name": "Eastern interface link", "path": [[2.3522, 48.8566], [7.7521, 48.5734]], "tone": "regional"},
    {"name": "Atlantic logistics link", "path": [[-1.5536, 47.2184], [2.3522, 48.8566]], "tone": "watch"},
]

OCTOCITY_RENDERER_LAYERS = [
    {
        "key": "territorial-risk",
        "label": "Decision heatmap",
        "short_label": "Heatmap",
        "deck_group": "territory",
        "tone": "cyan",
        "kind": "zone_score",
        "visible": True,
        "payload": {"sources": ["octocity_zone_scores"]},
        "sort_order": 10,
    },
    {
        "key": "open-intelligence",
        "label": "News signals",
        "short_label": "News",
        "deck_group": "press",
        "tone": "blue",
        "kind": "signal",
        "visible": True,
        "payload": {"sources": ["octocity_open_intelligence"]},
        "sort_order": 20,
    },
    {
        "key": "regional-context",
        "label": "Coordination points",
        "short_label": "Coordination",
        "deck_group": "region",
        "tone": "orange",
        "kind": "regional_context",
        "visible": True,
        "payload": {"sources": ["octocity_operating_context"]},
        "sort_order": 30,
    },
    {
        "key": "agenda-windows",
        "label": "Executive windows",
        "short_label": "Agenda",
        "deck_group": "agenda",
        "tone": "amber",
        "kind": "agenda_window",
        "visible": True,
        "payload": {"sources": ["institutional_calendar"]},
        "sort_order": 40,
    },
    {
        "key": "preventive-actions",
        "label": "Recommended actions",
        "short_label": "Actions",
        "deck_group": "actions",
        "tone": "red",
        "kind": "action",
        "visible": True,
        "payload": {"sources": ["octocity_action_planner"]},
        "sort_order": 50,
    },
]


def _is_octocity_workspace(workspace: Workspace) -> bool:
    settings = workspace.settings if isinstance(workspace.settings, dict) else {}
    mission_room = settings.get("mission_room") if isinstance(settings.get("mission_room"), dict) else {}
    return (
        workspace.slug == OCTOCITY_WORKSPACE_SLUG
        or mission_room.get("profile") == OCTOCITY_MISSION_ROOM_PROFILE
    )


def _is_octocity_map(map_row: WorkspaceMap) -> bool:
    settings = map_row.settings if isinstance(map_row.settings, dict) else {}
    return settings.get("fixture_profile") == OCTOCITY_MAP_FIXTURE_PROFILE


def _is_operator_map(map_row: WorkspaceMap) -> bool:
    return not _is_octocity_map(map_row) and map_row.slug != SENTINEL_MAP_SLUG


def _octocity_map_settings() -> dict[str, Any]:
    return {
        "policy": "advisory_only",
        "scope": "octocity_operating_room",
        "version": 1,
        "fixture_profile": OCTOCITY_MAP_FIXTURE_PROFILE,
        "fixture_version": OCTOCITY_MAP_FIXTURE_VERSION,
        "renderer_source": "octocity.synthetic.france",
        "legacy_polygon_mode": "compatibility_only",
    }


def _apply_octocity_map_identity(map_row: WorkspaceMap) -> None:
    map_row.slug = OCTOCITY_MAP_SLUG
    map_row.name = "Octocity Operating Map"
    map_row.description = "France operating map with synthetic Octocity signals and human-reviewed actions."
    map_row.country = "France"
    map_row.projection = "octocity_france_operating_v1"
    map_row.view_box = "160 40 500 480"
    map_row.center = {"x": 420, "y": 270}
    current_settings = map_row.settings if isinstance(map_row.settings, dict) else {}
    map_row.settings = {**current_settings, **_octocity_map_settings()}


def _octocity_fixture_is_current(db: DBSession, map_row: WorkspaceMap) -> bool:
    settings = map_row.settings if isinstance(map_row.settings, dict) else {}
    if (
        map_row.slug != OCTOCITY_MAP_SLUG
        or map_row.country != "France"
        or map_row.projection != "octocity_france_operating_v1"
        or settings.get("fixture_profile") != OCTOCITY_MAP_FIXTURE_PROFILE
        or settings.get("fixture_version") != OCTOCITY_MAP_FIXTURE_VERSION
    ):
        return False

    zone_rows = (
        db.query(WorkspaceMapZone)
        .filter(WorkspaceMapZone.map_id == map_row.id)
        .all()
    )
    zones_by_key = {row.zone_key: row for row in zone_rows}
    for item in OCTOCITY_ZONE_SEED:
        row = zones_by_key.get(item["key"])
        metadata = row.meta_data if row and isinstance(row.meta_data, dict) else {}
        if (
            not row
            or row.name != item["name"]
            or row.level != item["level"]
            or row.tone != item["tone"]
            or row.polygon != item["polygon"]
            or row.centroid != item["centroid"]
            or metadata.get("seed") != "octocity"
            or not set(item["signals"]).issubset(metadata.get("signals") or [])
            or not set(item["recommendations"]).issubset(metadata.get("recommendations") or [])
            or not set(item["sources"]).issubset(row.source_refs or [])
        ):
            return False

    layers_by_key = {
        row.key: row
        for row in db.query(WorkspaceMapLayer)
        .filter(WorkspaceMapLayer.map_id == map_row.id)
        .all()
    }
    for item in OCTOCITY_RENDERER_LAYERS:
        row = layers_by_key.get(item["key"])
        payload = row.payload if row and isinstance(row.payload, dict) else {}
        if (
            not row
            or row.label != item["label"]
            or row.kind != item["kind"]
            or row.visible != item["visible"]
            or row.sort_order != item["sort_order"]
            or payload.get("seed") != "octocity"
            or not set(item["payload"].get("sources") or []).issubset(payload.get("sources") or [])
        ):
            return False

    signals = (
        db.query(WorkspaceMapSignal)
        .filter(WorkspaceMapSignal.map_id == map_row.id)
        .all()
    )
    seeded_signals = {
        signal.source_id: signal
        for signal in signals
        if (signal.meta_data or {}).get("seed") == "octocity"
    }
    for item in OCTOCITY_ZONE_SEED:
        zone = zones_by_key[item["key"]]
        for index, title in enumerate(item["signals"], start=1):
            signal = seeded_signals.get(f"{item['key']}-signal-{index}")
            if not signal or signal.zone_id != zone.id or signal.title != title or signal.summary != title:
                return False

    scores = (
        db.query(WorkspaceMapScore)
        .filter(WorkspaceMapScore.map_id == map_row.id)
        .all()
    )
    scored_zone_ids = {score.zone_id for score in scores}
    return all(zones_by_key[item["key"]].id in scored_zone_ids for item in OCTOCITY_ZONE_SEED)


def _merge_seed_values(
    current: Any,
    required: list[str],
    *,
    superseded: Optional[list[str]] = None,
) -> list[str]:
    """Keep operator additions while replacing values owned by an older fixture."""
    superseded_values = set(superseded or [])
    preserved = [
        value
        for value in (current if isinstance(current, list) else [])
        if value not in superseded_values and value not in required
    ]
    return [*required, *preserved]


def _zone_score_values(db: DBSession, zone: WorkspaceMapZone) -> dict[str, Any]:
    signals = db.query(WorkspaceMapSignal).filter(WorkspaceMapSignal.zone_id == zone.id).all()
    signal_score = sum(min(35, max(0, signal.weight)) * signal.confidence for signal in signals)
    score = max(0, min(100, int(round(zone.level * 0.68 + signal_score * 0.32))))
    label = _level_label(score)
    return {
        "score": score,
        "level_label": label,
        "drivers": [signal.title for signal in signals] or list((zone.meta_data or {}).get("signals") or []),
        "recommendations": generate_scenarios(
            target_kind="zone",
            target_id=zone.zone_key,
            risk_level=label,
            source_refs=zone.source_refs or [],
            signal_strength=score,
        )[:3],
        "recommended_windows": _recommended_windows(zone.zone_key, score),
    }


def _repair_octocity_map_fixture_rows(
    db: DBSession,
    map_row: WorkspaceMap,
    *,
    legacy_fixture: bool,
) -> int:
    """Upsert Octocity-owned rows without deleting operator-owned map data."""
    legacy_zones = {item["key"]: item for item in SENTINEL_ZONE_SEED}
    zones_by_key = {
        row.zone_key: row
        for row in db.query(WorkspaceMapZone)
        .filter(WorkspaceMapZone.map_id == map_row.id)
        .all()
    }
    for item in OCTOCITY_ZONE_SEED:
        zone = zones_by_key.get(item["key"])
        if not zone:
            zone = WorkspaceMapZone(
                id=str(uuid4()),
                map_id=map_row.id,
                zone_key=item["key"],
                name=item["name"],
                level=item["level"],
                tone=item["tone"],
                polygon=item["polygon"],
                centroid=item["centroid"],
                meta_data={},
                source_refs=[],
            )
            db.add(zone)
            zones_by_key[item["key"]] = zone
        legacy = legacy_zones.get(item["key"]) or {}
        metadata = zone.meta_data if isinstance(zone.meta_data, dict) else {}
        zone.name = item["name"]
        zone.level = item["level"]
        zone.tone = item["tone"]
        zone.polygon = item["polygon"]
        zone.centroid = item["centroid"]
        zone.meta_data = {
            **metadata,
            "signals": _merge_seed_values(
                metadata.get("signals"),
                item["signals"],
                superseded=legacy.get("signals") if legacy_fixture else None,
            ),
            "recommendations": _merge_seed_values(
                metadata.get("recommendations"),
                item["recommendations"],
                superseded=legacy.get("recommendations") if legacy_fixture else None,
            ),
            "seed": "octocity",
        }
        zone.source_refs = _merge_seed_values(
            zone.source_refs,
            item["sources"],
            superseded=legacy.get("sources") if legacy_fixture else None,
        )

    legacy_layers = {item["key"]: item for item in DEFAULT_RENDERER_LAYERS}
    layers_by_key = {
        row.key: row
        for row in db.query(WorkspaceMapLayer)
        .filter(WorkspaceMapLayer.map_id == map_row.id)
        .all()
    }
    octocity_layer_keys = {item["key"] for item in OCTOCITY_RENDERER_LAYERS}
    if legacy_fixture:
        for key, layer in layers_by_key.items():
            legacy_spec = legacy_layers.get(key)
            if not legacy_spec or key in octocity_layer_keys:
                continue
            current_payload = layer.payload if isinstance(layer.payload, dict) else {}
            legacy_payload = legacy_spec.get("payload") or {}
            layer.label = "Retired compatibility layer"
            layer.visible = False
            layer.payload = {
                **current_payload,
                "sources": _merge_seed_values(
                    current_payload.get("sources"),
                    [],
                    superseded=legacy_payload.get("sources") or [],
                ),
                "seed": "octocity-retired",
                "retired": True,
            }
    for item in OCTOCITY_RENDERER_LAYERS:
        layer = layers_by_key.get(item["key"])
        if not layer:
            layer = WorkspaceMapLayer(id=str(uuid4()), map_id=map_row.id, key=item["key"])
            db.add(layer)
            layers_by_key[item["key"]] = layer
        current_payload = layer.payload if isinstance(layer.payload, dict) else {}
        legacy_payload = (legacy_layers.get(item["key"]) or {}).get("payload") or {}
        layer.label = item["label"]
        layer.kind = item["kind"]
        layer.visible = item["visible"]
        layer.sort_order = item["sort_order"]
        layer.payload = {
            **current_payload,
            **item["payload"],
            "sources": _merge_seed_values(
                current_payload.get("sources"),
                item["payload"].get("sources") or [],
                superseded=legacy_payload.get("sources") if legacy_fixture else None,
            ),
            "seed": "octocity",
        }

    db.flush()
    seed_signals_by_source: dict[str, WorkspaceMapSignal] = {}
    for signal in (
        db.query(WorkspaceMapSignal)
        .filter(WorkspaceMapSignal.map_id == map_row.id)
        .all()
    ):
        if (signal.meta_data or {}).get("seed") in {"sentinel-ci", "octocity"}:
            seed_signals_by_source.setdefault(signal.source_id, signal)
    now = datetime.utcnow()
    for item in OCTOCITY_ZONE_SEED:
        zone = zones_by_key[item["key"]]
        for index, title in enumerate(item["signals"], start=1):
            source_id = f"{item['key']}-signal-{index}"
            signal = seed_signals_by_source.get(source_id)
            if not signal:
                signal = WorkspaceMapSignal(
                    id=str(uuid4()),
                    map_id=map_row.id,
                    zone_id=zone.id,
                    source_kind="mission_room",
                    source_id=source_id,
                    title=title,
                    summary=title,
                    weight=max(8, min(30, int(item["level"] / 4))),
                    confidence=0.72 if item["level"] >= 50 else 0.62,
                    occurred_at=now,
                    meta_data={"seed": "octocity"},
                )
                db.add(signal)
                seed_signals_by_source[source_id] = signal
            else:
                signal.zone_id = zone.id
                signal.source_kind = "mission_room"
                signal.title = title
                signal.summary = title
                signal.weight = max(8, min(30, int(item["level"] / 4)))
                signal.confidence = 0.72 if item["level"] >= 50 else 0.62
                signal.meta_data = {**(signal.meta_data or {}), "seed": "octocity"}

    db.flush()
    scores_by_zone: dict[str, list[WorkspaceMapScore]] = {}
    for score in (
        db.query(WorkspaceMapScore)
        .filter(WorkspaceMapScore.map_id == map_row.id)
        .order_by(WorkspaceMapScore.computed_at.asc())
        .all()
    ):
        scores_by_zone.setdefault(score.zone_id, []).append(score)
    for item in OCTOCITY_ZONE_SEED:
        zone = zones_by_key[item["key"]]
        existing_scores = scores_by_zone.get(zone.id) or []
        score_row = existing_scores[0] if existing_scores else None
        if not score_row:
            score_row = WorkspaceMapScore(
                id=str(uuid4()),
                map_id=map_row.id,
                zone_id=zone.id,
                job_id=None,
                computed_at=now,
            )
            db.add(score_row)
        if legacy_fixture or not existing_scores:
            for key, value in _zone_score_values(db, zone).items():
                setattr(score_row, key, value)
            score_row.computed_at = now
    db.flush()
    return len(OCTOCITY_ZONE_SEED)


def _seed_map_fixture_rows(
    db: DBSession,
    workspace: Workspace,
    map_row: WorkspaceMap,
    *,
    zone_seed: list[dict[str, Any]],
    layer_specs: list[dict[str, Any]],
    seed_label: str,
) -> int:
    now = datetime.utcnow()
    _ensure_map_layers(db, map_row, layer_specs=layer_specs, seed_label=seed_label)
    db.flush()
    zone_rows: list[WorkspaceMapZone] = []
    for item in zone_seed:
        zone = WorkspaceMapZone(
            id=str(uuid4()),
            map_id=map_row.id,
            zone_key=item["key"],
            name=item["name"],
            level=item["level"],
            tone=item["tone"],
            polygon=item["polygon"],
            centroid=item["centroid"],
            meta_data={
                "signals": item["signals"],
                "recommendations": item["recommendations"],
                **({"seed": seed_label} if seed_label == "octocity" else {}),
            },
            source_refs=item["sources"],
        )
        db.add(zone)
        zone_rows.append(zone)
    db.flush()
    for zone, item in zip(zone_rows, zone_seed):
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
                    meta_data={"seed": seed_label},
                )
            )
    db.flush()
    score_map_zones(db, workspace, map_row)
    return len(zone_rows)


def ensure_workspace_map_seed(db: DBSession, workspace: Workspace, *, system_id: Optional[str] = None) -> WorkspaceMap:
    octocity = _is_octocity_workspace(workspace)
    target_slug = OCTOCITY_MAP_SLUG if octocity else SENTINEL_MAP_SLUG
    candidate_slugs = [target_slug]
    if octocity:
        candidate_slugs.append(SENTINEL_MAP_SLUG)
    candidates = (
        db.query(WorkspaceMap)
        .filter(
            WorkspaceMap.workspace_id == workspace.id,
            WorkspaceMap.slug.in_(candidate_slugs),
        )
        .all()
    )
    existing = next((row for row in candidates if row.slug == target_slug), None)
    existing = existing or next(iter(candidates), None)
    if existing:
        changed = False
        if system_id is not None and existing.system_id != system_id:
            existing.system_id = system_id
            changed = True
        if octocity:
            existing_settings = existing.settings if isinstance(existing.settings, dict) else {}
            legacy_fixture = existing_settings.get("fixture_profile") != OCTOCITY_MAP_FIXTURE_PROFILE
            fixture_current = _octocity_fixture_is_current(db, existing)
            _apply_octocity_map_identity(existing)
            if not fixture_current:
                zones = _repair_octocity_map_fixture_rows(
                    db,
                    existing,
                    legacy_fixture=legacy_fixture,
                )
                emit_audit_event(
                    db=db,
                    workspace_id=workspace.id,
                    event_type="map.system.upgraded",
                    actor="system",
                    details={"map_id": existing.id, "slug": existing.slug, "zones": zones},
                )
                changed = True
        else:
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
                changed = True
            _ensure_map_layers(db, existing)
        if changed:
            existing.updated_at = datetime.utcnow()
        return existing

    now = datetime.utcnow()
    map_row = WorkspaceMap(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system_id,
        slug=target_slug,
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
    if octocity:
        _apply_octocity_map_identity(map_row)
    db.add(map_row)
    db.flush()
    zones = _seed_map_fixture_rows(
        db,
        workspace,
        map_row,
        zone_seed=OCTOCITY_ZONE_SEED if octocity else SENTINEL_ZONE_SEED,
        layer_specs=OCTOCITY_RENDERER_LAYERS if octocity else DEFAULT_RENDERER_LAYERS,
        seed_label="octocity" if octocity else "sentinel-ci",
    )
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="map.system.seeded",
        actor="system",
        details={"map_id": map_row.id, "slug": map_row.slug, "zones": zones},
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


def serialize_map(
    map_row: WorkspaceMap,
    db: Optional[DBSession] = None,
    *,
    workspace: Optional[Workspace] = None,
) -> dict[str, Any]:
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
        octocity = _is_octocity_map(map_row)
        operator = _is_operator_map(map_row)
        zone_payloads = [
            serialize_zone(
                zone,
                scores.get(zone.id),
                octocity=octocity,
                operator=operator,
            )
            for zone in zones
        ]
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
        {
            "key": "satellite",
            "label": "Satellite",
            "description": "Imagerie ESRI World Imagery — fond contextuel indicatif.",
            "provider": "esri_world_imagery",
            "theme": "satellite",
            "style": _basemap_style(
                "esri-world-imagery",
                ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
                {
                    "raster-opacity": 0.88,
                    "raster-brightness-min": 0.0,
                    "raster-brightness-max": 0.92,
                    "raster-saturation": -0.08,
                    "raster-contrast": 0.08,
                },
                background="#0a0e12",
            ),
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
        "social-geo": "Securite / social",
        "military-air": "Securite / Sahel",
        "border-tension": "Securite / frontiere",
        "satellite-footprint": "Securite / satellite",
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
        "social-geo": "pulse",
        "military-air": "plane",
        "border-tension": "shield-alert",
        "satellite-footprint": "image",
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
            "body": "Options advisory-only, a valider par le Vice Premier Ministre ou le cabinet.",
        },
        "social-geo": {
            "title": "Pulsation sociale Abidjan",
            "body": "Tweets geolocalises Plateau / Cocody — snapshot demo-safe, handles pseudonymises.",
        },
        "military-air": {
            "title": "ADS-B advisory Sahel",
            "body": "Snapshot scenario sur axe Bamako / Ouaga / Niamey — advisory only, pas operationnel.",
        },
        "border-tension": {
            "title": "Tension frontiere Nord",
            "body": "Zones de rumeur OSINT — démentis officiels FANCI et Préfecture Nord references.",
        },
        "satellite-footprint": {
            "title": "Empreintes satellite",
            "body": "Scènes baseline indicatives — aucune détection automatique, advisory only.",
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
        "social-geo": 66,
        "military-air": 62,
        "border-tension": 74,
        "satellite-footprint": 68,
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
        "social-geo": "snapshot demo-safe",
        "military-air": "snapshot ADS-B advisory only",
        "border-tension": "dossier rumeur démenti officiel",
        "satellite-footprint": "baseline satellite demo",
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
        "social-geo": "social_snapshot",
        "military-air": "ads_b_advisory",
        "border-tension": "rumor_dossier",
        "satellite-footprint": "satellite_baseline",
    }.get(key, "workspace")


def _source_counts(zones: list[dict[str, Any]]) -> dict[str, int]:
    try:
        vessel_count = len(fetch_vessels_in_bbox(limit=500))
    except Exception:  # noqa: BLE001
        vessel_count = 0
    # Use lazy imports to avoid circular dependency mission_room -> workspace_maps.
    try:
        from app.services.mission_room import SOCIAL_SNAPSHOT, TROOPS_SAHEL  # noqa: PLC0415

        social_count = len((SOCIAL_SNAPSHOT or {}).get("tweets") or [])
        tracks_count = len((TROOPS_SAHEL or {}).get("tracks") or [])
        border_count = len([t for t in ((SOCIAL_SNAPSHOT or {}).get("tweets") or []) if t.get("kind") == "rumeur"])
    except Exception:  # noqa: BLE001
        social_count = 0
        tracks_count = 0
        border_count = 0
    return {
        "territorial-risk": len(zones),
        "open-intelligence": sum(len(zone.get("drivers") or zone.get("signals") or []) for zone in zones),
        "regional-context": sum(1 for marker in SENTINEL_CONTEXT_MARKERS if marker.get("scope") == "regional"),
        "strategic-projects": sum(1 for zone in zones if zone.get("scenario_options")),
        "agenda-windows": sum(len(zone.get("recommended_windows") or []) for zone in zones),
        "visual-streams": 1,
        "maritime-traffic": len(MARITIME_PORTS) + len(MARITIME_EVENTS) + vessel_count,
        "preventive-actions": sum(len(zone.get("recommendations") or []) for zone in zones),
        "social-geo": social_count,
        "military-air": tracks_count,
        "border-tension": border_count or 3,
        "satellite-footprint": 2,
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


def _s3_security_geojson_sources() -> dict[str, dict[str, Any]]:
    """Demo-safe GeoJSON sources backing the S3 ``social-geo``, ``military-air``
    and ``border-tension`` deck layers.

    All inputs come from the static SENTINEL-CI fixtures (no live feed). The
    helper is defensive against the structured fixtures being absent so the
    map keeps rendering the base layers if the import fails.
    """
    social_points: dict[str, Any] = {"type": "FeatureCollection", "features": []}
    military_points: dict[str, Any] = {"type": "FeatureCollection", "features": []}
    border_polygons: dict[str, Any] = {"type": "FeatureCollection", "features": []}
    satellite_footprints: dict[str, Any] = {"type": "FeatureCollection", "features": []}
    try:
        from app.services.intelligence.satellite_imagery import (
            load_satellite_baseline,  # noqa: PLC0415
        )
        from app.services.mission_room import SOCIAL_SNAPSHOT, TROOPS_SAHEL  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return {
            "social_geo": social_points,
            "military_air": military_points,
            "border_tension": border_polygons,
            "satellite_footprint": satellite_footprints,
        }

    for tweet in (SOCIAL_SNAPSHOT or {}).get("tweets") or []:
        geo = tweet.get("geo") or {}
        longitude = geo.get("longitude")
        latitude = geo.get("latitude")
        if longitude is None or latitude is None:
            continue
        social_points["features"].append(
            {
                "type": "Feature",
                "id": tweet.get("id"),
                "geometry": {"type": "Point", "coordinates": [float(longitude), float(latitude)]},
                "properties": {
                    "id": tweet.get("id"),
                    "kind": tweet.get("kind"),
                    "handle": tweet.get("handle"),
                    "sentiment": tweet.get("sentiment"),
                    "engagement": tweet.get("engagement"),
                    "label": geo.get("label"),
                    "text": tweet.get("text"),
                    "posted_at": tweet.get("posted_at"),
                },
            }
        )

    for track in (TROOPS_SAHEL or {}).get("tracks") or []:
        longitude = track.get("longitude")
        latitude = track.get("latitude")
        if longitude is None or latitude is None:
            continue
        military_points["features"].append(
            {
                "type": "Feature",
                "id": track.get("id"),
                "geometry": {"type": "Point", "coordinates": [float(longitude), float(latitude)]},
                "properties": {
                    "id": track.get("id"),
                    "callsign": track.get("callsign"),
                    "kind": track.get("kind"),
                    "operator": track.get("operator"),
                    "altitude_ft": track.get("altitude_ft"),
                    "heading": track.get("heading"),
                    "speed_kt": track.get("speed_kt"),
                    "tone": track.get("tone"),
                    "origin": track.get("origin"),
                    "destination": track.get("destination"),
                    "advisory_only": True,
                },
            }
        )

    # Border-tension polygons cover the Bouna / Kong / Korhogo arc where the
    # demo-safe rumor was geolocated. The polygons are intentionally coarse
    # since they only carry the « rumor under démenti » signal, not any
    # operational footprint.
    border_polygons["features"] = [
        {
            "type": "Feature",
            "id": "border-tension-bouna",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-3.45, 9.05],
                    [-2.55, 9.05],
                    [-2.55, 9.65],
                    [-3.45, 9.65],
                    [-3.45, 9.05],
                ]],
            },
            "properties": {
                "id": "border-tension-bouna",
                "label": "Zone Bouna — rumeur OSINT démentie",
                "tone": "watch",
                "source_id": "src-rumor-frontier-nord-2026-05-25",
                "advisory_only": True,
            },
        },
        {
            "type": "Feature",
            "id": "border-tension-kong",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-5.10, 9.05],
                    [-4.20, 9.05],
                    [-4.20, 9.55],
                    [-5.10, 9.55],
                    [-5.10, 9.05],
                ]],
            },
            "properties": {
                "id": "border-tension-kong",
                "label": "Zone Kong — rumeur OSINT démentie",
                "tone": "watch",
                "source_id": "src-rumor-frontier-nord-2026-05-25",
                "advisory_only": True,
            },
        },
        {
            "type": "Feature",
            "id": "border-tension-korhogo",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-6.10, 9.20],
                    [-5.15, 9.20],
                    [-5.15, 9.75],
                    [-6.10, 9.75],
                    [-6.10, 9.20],
                ]],
            },
            "properties": {
                "id": "border-tension-korhogo",
                "label": "Zone Korhogo — surveillance Préfecture Nord",
                "tone": "stable",
                "source_id": "src-rumor-frontier-nord-2026-05-25",
                "advisory_only": True,
            },
        },
    ]
    try:
        satellite_baseline = load_satellite_baseline()
        for scene in satellite_baseline.get("scenes") or []:
            bbox = scene.get("bbox") or []
            if len(bbox) != 4:
                continue
            west, south, east, north = [float(value) for value in bbox]
            satellite_footprints["features"].append(
                {
                    "type": "Feature",
                    "id": scene.get("id"),
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [west, south],
                            [east, south],
                            [east, north],
                            [west, north],
                            [west, south],
                        ]],
                    },
                    "properties": {
                        "id": scene.get("id"),
                        "label": scene.get("label"),
                        "axis": scene.get("axis"),
                        "tone": scene.get("tone") or "watch",
                        "narrative_status": scene.get("narrative_status"),
                        "advisory_only": True,
                    },
                }
            )
    except Exception:  # noqa: BLE001
        pass
    return {
        "social_geo": social_points,
        "military_air": military_points,
        "border_tension": border_polygons,
        "satellite_footprint": satellite_footprints,
    }


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
    vessel_features = _maritime_vessel_features()
    return {
        "maritime_area": operating_area,
        "maritime_points": {"type": "FeatureCollection", "features": point_features},
        "maritime_routes": {"type": "FeatureCollection", "features": route_features},
        "maritime_density": {"type": "FeatureCollection", "features": density_features},
        "maritime_vessels": {"type": "FeatureCollection", "features": vessel_features},
    }


def _maritime_vessel_features() -> list[dict[str, Any]]:
    """Return AIS-like vessel positions as GeoJSON Point features.

    Linked to the same MMSI/IMO as ``MARITIME_EVENTS['cargo-abidjan-supply-001']``
    so the cargo card and the vessel marker reference the same physical ship.
    """
    snapshot = fetch_maritime_snapshot()
    features: list[dict[str, Any]] = []
    for vessel in snapshot.vessels:
        properties = serialize_vessel(vessel)
        properties.update(
            {
                "kind": "vessel_position",
                "layer_key": "maritime-traffic",
                "source_kind": "maritime_vessels",
                "visual_role": "vessel_live",
                "render_tone": "vessel_highlight" if vessel.highlight else "vessel_position",
                "tooltip_title": vessel.name,
                "tooltip_subtitle": (
                    f"{(vessel.vessel_type or 'navire').upper()} · "
                    f"MMSI {vessel.mmsi}"
                    + (f" · IMO {vessel.imo}" if vessel.imo else "")
                ),
            }
        )
        features.append(
            {
                "type": "Feature",
                "id": f"vessel-{vessel.mmsi}",
                "geometry": {"type": "Point", "coordinates": [vessel.lon, vessel.lat]},
                "properties": properties,
            }
        )
    return features


def _maritime_snapshot_payload() -> dict[str, Any]:
    density_zones = _maritime_density_zones()
    disruptions = _maritime_disruptions()
    vessel_snapshot = fetch_maritime_snapshot()
    vessels = fetch_vessels_in_bbox(limit=50)
    limitations = [
        "Pas de promesse de live AIS sans provider active.",
        "Les points navires sont un snapshot demonstratif et non un suivi individuel.",
    ]
    limitations.extend(vessel_snapshot.limitations or [])
    return {
        "mode": "snapshot_demo_safe",
        "provider": f"demo-safe / AIS={vessel_snapshot.provider}",
        "provider_configured": vessel_snapshot.source != "baseline",
        "ports": MARITIME_PORTS,
        "events": MARITIME_EVENTS,
        "vessels": [serialize_vessel(vessel) for vessel in vessels],
        "vessels_provider": vessel_snapshot.provider,
        "vessels_source": vessel_snapshot.source,
        "vessels_embed_url": vessel_snapshot.embed_url,
        "vessels_attribution": vessel_snapshot.attribution,
        "vessels_fetched_at": vessel_snapshot.fetched_at,
        "bbox": {"west": -9.35, "south": 3.95, "east": -1.05, "north": 5.25},
        "density_zones": density_zones,
        "disruptions": disruptions,
        "freshness": {
            "status": "ready",
            "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "ttl_seconds": min(300, vessel_snapshot.ttl_seconds or 300),
            "cache_policy": "bbox_quantized_snapshot",
        },
        "summary": "Lecture portuaire demo-safe : Abidjan et San Pedro, corridors Golfe de Guinee, densite indicative et liens douanes/projets.",
        "limitations": list(dict.fromkeys(limitations)),
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


def serialize_zone(
    zone: WorkspaceMapZone,
    score: Optional[WorkspaceMapScore] = None,
    *,
    octocity: bool = False,
    operator: bool = False,
) -> dict[str, Any]:
    zone_definition = (
        {}
        if octocity or operator
        else SENTINEL_ZONE_GEOGRAPHY.get(zone.zone_key) or {}
    )
    geometry_kind = (
        "octocity.synthetic.operating_zone"
        if octocity
        else "workspace.operator_zone"
        if operator
        else "geoBoundaries.ADM1_group"
    )
    payload = {
        "id": zone.zone_key,
        "zone_id": zone.id,
        "name": zone.name,
        "level": score.score if score else zone.level,
        "tone": _tone_for(score.score if score else zone.level),
        "centroid": zone.centroid or {},
        "polygon": zone.polygon,
        "geometry_kind": geometry_kind,
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


def mission_room_map_payload(
    db: DBSession,
    workspace: Workspace,
    *,
    map_row: Optional[WorkspaceMap] = None,
) -> dict[str, Any]:
    map_row = map_row or ensure_workspace_map_seed(db, workspace)
    octocity = _is_octocity_map(map_row)
    operator = _is_operator_map(map_row)
    zones = db.query(WorkspaceMapZone).filter(WorkspaceMapZone.map_id == map_row.id).order_by(WorkspaceMapZone.level.desc()).all()
    scores = {
        score.zone_id: score
        for score in db.query(WorkspaceMapScore).filter(WorkspaceMapScore.map_id == map_row.id).order_by(WorkspaceMapScore.computed_at.desc()).all()
    }
    zone_payloads = [
        serialize_zone(
            zone,
            scores.get(zone.id),
            octocity=octocity,
            operator=operator,
        )
        for zone in zones
    ]
    return {
        "map_system": serialize_map(map_row, db, workspace=workspace),
        "map": {
            "country": map_row.country,
            "view_box": map_row.view_box,
            "projection": map_row.projection,
            "accuracy": (
                "octocity_synthetic_operating_fixture_v1"
                if octocity
                else "workspace_operator_geometry_v1"
                if operator
                else "geojson_admin_boundaries_v1"
            ),
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
    map_id_or_slug: Optional[str] = None,
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
    map_row = (
        get_workspace_map(db, workspace, map_id_or_slug)
        if map_id_or_slug
        else ensure_workspace_map_seed(db, workspace)
    )
    payload = mission_room_map_payload(db, workspace, map_row=map_row)
    map_system = payload["map_system"]
    octocity = _is_octocity_map(map_row) or _is_octocity_workspace(workspace)
    normalized_intent = "show_sources" if intent == "open_source_panel" else intent
    normalized_intent = normalized_intent if normalized_intent in MAP_COMMAND_INTENTS else "focus_zone"
    zones = payload.get("zones") or []
    selected_port = None if normalized_intent == "reset_view" else _find_port_payload(target, octocity=octocity)
    if octocity and normalized_intent in {"focus_port", "show_vessel_snapshot", "show_disruption"} and not selected_port:
        selected_port = _find_port_payload("port-marseille", octocity=True)
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
        if octocity:
            active_layers = [
                layer
                for layer in (
                    "territorial-risk",
                    "open-intelligence",
                    "regional-context",
                    "preventive-actions",
                )
                if layer in allowed_layers
            ]
        else:
            active_layers = ["territorial-risk", "open-intelligence", "maritime-traffic", "preventive-actions"]
    elif normalized_intent in {"set_layers", "reset_view"}:
        active_layers = default_active_layers
    else:
        active_layers = default_active_layers
    basemap_options = {option.get("key") for option in map_system.get("basemap_options") or []}
    selected_basemap = basemap if basemap in basemap_options else default_state.get("basemap") or "command"
    selected_time_range = time_range if time_range in {item["key"] for item in MAP_TIME_RANGES} else default_state.get("time_range") or "7d"
    explanation = _command_explanation(
        normalized_intent,
        selected,
        selected_basemap,
        selected_port=selected_port,
        time_range=selected_time_range,
        octocity=octocity,
    )
    sources = _port_sources(selected_port, octocity=octocity) if selected_port else _zone_sources(selected)
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
                "label": target_label or map_row.country or "Workspace map",
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
    if assistant_profile not in {"vigie_executive", "octave_executive"}:
        return None
    normalized = (query or "").lower()
    octocity = assistant_profile == "octave_executive" or _is_octocity_workspace(workspace)
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
    port_target = _extract_port_target(normalized, octocity=octocity)
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
    target = _extract_zone_target(normalized, octocity=octocity)
    if port_target:
        intent = "focus_port"
        target = port_target
        layers = (
            ["territorial-risk", "open-intelligence", "regional-context", "preventive-actions"]
            if octocity
            else ["territorial-risk", "open-intelligence", "maritime-traffic", "preventive-actions"]
        )
        if "navire" in normalized or "bateau" in normalized:
            intent = "show_vessel_snapshot"
        disruption_terms = ("risque", "perturbation", "incident") if octocity else ("risque", "douane", "douanes")
        if any(term in normalized for term in disruption_terms):
            intent = "show_disruption"
    if "source" in normalized:
        intent = "show_sources"
    if "fenetre" in normalized or "créneau" in normalized or "creneau" in normalized:
        intent = "show_action_window"
    if "compare" in normalized or "changé" in normalized or "change" in normalized:
        intent = "compare_before_after"
    reset_terms = (
        ("réinitialise", "reinitialise", "france", "octocity")
        if octocity
        else ("réinitialise", "reinitialise", "côte d'ivoire", "cote d'ivoire")
    )
    if any(term in normalized for term in reset_terms):
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
    if octocity and intent in {"focus_port", "show_vessel_snapshot", "show_disruption"}:
        content = (
            f"J'affiche {label} dans le contexte opérationnel France avec les signaux ouverts "
            "et les actions recommandées. Lecture synthétique Octocity, à valider humainement."
        )
    elif octocity:
        content = (
            f"J'affiche {label} sur la carte opérationnelle France. La vue Octocity relie les "
            "signaux ouverts, les fenêtres exécutives et les actions recommandées."
        )
    elif intent in {"focus_port", "show_vessel_snapshot", "show_disruption"}:
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


def _octocity_workspace_map_renderer_payload(
    map_row: WorkspaceMap,
    zones: list[dict[str, Any]],
) -> dict[str, Any]:
    empty_collection = {"type": "FeatureCollection", "features": []}
    zone_by_key = {str(zone.get("id") or ""): zone for zone in zones}
    zone_features = []
    marker_features = []
    event_features = []
    camera_presets: dict[str, dict[str, Any]] = {
        "country": {
            "longitude": 2.25,
            "latitude": 46.75,
            "zoom": 6.32,
            "pitch": 0,
            "bearing": 0,
            "duration_ms": 900,
        }
    }
    for port in OCTOCITY_PORTS:
        camera_presets[port["id"]] = {
            "longitude": port["longitude"],
            "latitude": port["latitude"],
            "zoom": 8.25,
            "pitch": 0,
            "bearing": 0,
            "duration_ms": 850,
        }
    for key, geography in OCTOCITY_ZONE_GEOGRAPHY.items():
        zone = zone_by_key.get(key) or {}
        name = str(zone.get("name") or key)
        level = int(zone.get("level") or 0)
        tone = str(zone.get("tone") or "stable")
        centroid = list(geography["centroid"])
        zone_features.append(
            {
                "type": "Feature",
                "id": key,
                "geometry": {"type": "Polygon", "coordinates": [geography["polygon"]]},
                "properties": {
                    "id": key,
                    "zone_id": key,
                    "name": name,
                    "level": level,
                    "tone": tone,
                    "synthetic": True,
                },
            }
        )
        marker_features.append(
            {
                "type": "Feature",
                "id": f"{key}-marker",
                "geometry": {"type": "Point", "coordinates": centroid},
                "properties": {
                    "zone_id": key,
                    "name": name,
                    "level": level,
                    "tone": tone,
                    "synthetic": True,
                },
            }
        )
        event_features.append(
            {
                "type": "Feature",
                "id": f"event-{key}",
                "geometry": {"type": "Point", "coordinates": centroid},
                "properties": {
                    "name": f"{name} operating signal",
                    "layer_key": "open-intelligence",
                    "score": level,
                    "source_kind": "octocity_synthetic_signal",
                },
            }
        )
        camera_presets[key] = {
            "longitude": centroid[0],
            "latitude": centroid[1],
            "zoom": 6.45,
            "pitch": 0,
            "bearing": 0,
            "duration_ms": 850,
        }

    context_features = [
        {
            "type": "Feature",
            "id": f"context-{marker['name'].lower().replace(' ', '-')}",
            "geometry": {"type": "Point", "coordinates": marker["coordinates"]},
            "properties": {
                "name": marker["name"],
                "kind": marker["kind"],
                "weight": marker["weight"],
                "scope": "octocity",
                "source": "octocity-operating-context",
            },
        }
        for marker in OCTOCITY_CONTEXT_MARKERS
    ]
    line_features = [
        {
            "type": "Feature",
            "id": f"line-{line['name'].lower().replace(' ', '-')}",
            "geometry": {"type": "LineString", "coordinates": line["path"]},
            "properties": {"name": line["name"], "tone": line["tone"], "synthetic": True},
        }
        for line in OCTOCITY_CONTEXT_LINES
    ]
    source_counts = {
        "territorial-risk": len(zones),
        "open-intelligence": sum(len(zone.get("drivers") or zone.get("signals") or []) for zone in zones),
        "regional-context": len(context_features),
        "agenda-windows": sum(len(zone.get("recommended_windows") or []) for zone in zones),
        "preventive-actions": sum(len(zone.get("recommendations") or []) for zone in zones),
    }
    layer_catalog = [
        {
            "key": layer["key"],
            "label": layer["label"],
            "short_label": layer["short_label"],
            "deck_group": layer["deck_group"],
            "tone": layer["tone"],
            "visible": layer["visible"],
            "kind": layer["kind"],
            "count": source_counts.get(layer["key"], 0),
            "confidence": 82 if layer["key"] == "territorial-risk" else 76,
        }
        for layer in OCTOCITY_RENDERER_LAYERS
    ]
    updated_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    layer_registry = [
        {
            **layer,
            "group": layer["deck_group"],
            "icon": "target" if layer["key"] == "territorial-risk" else "layer",
            "status": "ready" if layer["count"] else "empty",
            "state_label": "ready" if layer["count"] else "empty",
            "freshness": "synthetic fixture",
            "freshness_at": updated_at,
            "failure_reason": None,
            "default_visible": bool(layer["visible"]),
            "source_kind": "octocity_fixture",
            "source_count": layer["count"],
            "renderer_support": ["maplibre", "deck.gl", "svg-fallback"],
            "tooltip": {
                "title": layer["label"],
                "body": "Synthetic Octocity workspace data for human-reviewed operating decisions.",
            },
        }
        for layer in layer_catalog
    ]
    basemap_options = _map_basemap_options()
    administrative_basemap = next(
        option for option in basemap_options if option["key"] == "administrative"
    )
    active_layers = [layer["key"] for layer in OCTOCITY_RENDERER_LAYERS if layer["visible"]]
    event_points = {"type": "FeatureCollection", "features": event_features}
    top_zones = sorted(zones, key=lambda zone: int(zone.get("level") or 0), reverse=True)[:3]
    return {
        "map_version": "octocity_map_v1",
        "rendering_profile": "octocity_operating_v1",
        "time_range": "7d",
        "available_time_ranges": MAP_TIME_RANGES,
        "renderer_config": {
            "renderer": "maplibre",
            "rendering_profile": "octocity_operating_v1",
            "fallback_renderer": "svg",
            "basemap_policy": "public_osm_carto_with_synthetic_workspace_overlays",
            "default_basemap": "administrative",
            "style": administrative_basemap["style"],
            "initial_view_state": camera_presets["country"],
            "bounds": [
                [OCTOCITY_MAP_BOUNDS["west"], OCTOCITY_MAP_BOUNDS["south"]],
                [OCTOCITY_MAP_BOUNDS["east"], OCTOCITY_MAP_BOUNDS["north"]],
            ],
            "regional_bounds": [
                [OCTOCITY_MAP_BOUNDS["west"], OCTOCITY_MAP_BOUNDS["south"]],
                [OCTOCITY_MAP_BOUNDS["east"], OCTOCITY_MAP_BOUNDS["north"]],
            ],
            "attribution": "OSM/CARTO basemap · synthetic Octocity workspace signals",
            "interaction_contract": {
                "commands": sorted(MAP_COMMAND_INTENTS),
                "scenario_modes": ["explorer", "comprendre", "decider"],
                "selection": "zone",
                "events": ["zone_selected", "map_state_updated", "source_panel_requested"],
            },
        },
        "basemap_options": basemap_options,
        "layer_catalog": layer_catalog,
        "layer_registry": layer_registry,
        "default_map_state": {
            "basemap": "administrative",
            "active_layers": active_layers,
            "selected_zone": zones[0]["id"] if zones else None,
            "camera": camera_presets["country"],
            "time_range": "7d",
            "mode": "explorer",
        },
        "geodata_metadata": {
            "source": "Octocity synthetic operating fixture",
            "license": "demo-only",
            "synthetic": True,
            "admin_levels": [],
        },
        "country_boundary": copy.deepcopy(empty_collection),
        "district_boundaries": copy.deepcopy(empty_collection),
        "admin_boundaries": copy.deepcopy(empty_collection),
        "cities": {"type": "FeatureCollection", "features": context_features},
        "region_scores": _region_scores(zones),
        "event_points": event_points,
        "maritime_snapshot": {
            "mode": "disabled_for_octocity_fixture",
            "density_zones": [],
            "disruptions": [],
            "synthetic": True,
        },
        "source_health": {
            "status": "ready",
            "mode": "synthetic_fixture",
            "source_count": sum(source_counts.values()),
        },
        "forecast_signals": [
            {
                "id": f"forecast-{zone.get('id')}",
                "zone_id": zone.get("id"),
                "label": f"{zone.get('name')} operating outlook",
                "score": zone.get("level"),
                "synthetic": True,
            }
            for zone in top_zones
        ],
        "scenario_modes": [
            {"key": "explorer", "label": "Explore", "goal": "Inspect synthetic signals"},
            {"key": "comprendre", "label": "Understand", "goal": "Review sourced context"},
            {"key": "decider", "label": "Decide", "goal": "Prepare a human-reviewed action"},
        ],
        "default_layer_groups": {
            "situation": ["territorial-risk", "open-intelligence", "regional-context"],
            "decision": ["agenda-windows", "preventive-actions"],
        },
        "tooltip_templates": {
            layer["key"]: {
                "title": layer["label"],
                "body": "Synthetic Octocity workspace evidence.",
            }
            for layer in OCTOCITY_RENDERER_LAYERS
        },
        "source_counts": source_counts,
        "geojson_sources": {
            "zones": {"type": "FeatureCollection", "features": zone_features},
            "markers": {"type": "FeatureCollection", "features": marker_features},
            "context_markers": {"type": "FeatureCollection", "features": context_features},
            "context_lines": {"type": "FeatureCollection", "features": line_features},
            "event_points": event_points,
            "maritime_area": copy.deepcopy(empty_collection),
            "maritime_points": copy.deepcopy(empty_collection),
            "maritime_routes": copy.deepcopy(empty_collection),
            "maritime_density": copy.deepcopy(empty_collection),
            "social_geo": copy.deepcopy(empty_collection),
            "military_air": copy.deepcopy(empty_collection),
            "border_tension": copy.deepcopy(empty_collection),
            "satellite_footprint": copy.deepcopy(empty_collection),
        },
        "camera_presets": camera_presets,
        "visual_effects": {
            "zone_halo": True,
            "marker_pulse": True,
            "arc_links": [
                {
                    "source": [2.3522, 48.8566],
                    "target": geography["centroid"],
                    "tone": (zone_by_key.get(key) or {}).get("tone", "stable"),
                    "level": (zone_by_key.get(key) or {}).get("level", 0),
                    "label": f"Coordination {(zone_by_key.get(key) or {}).get('name', key)}",
                }
                for key, geography in OCTOCITY_ZONE_GEOGRAPHY.items()
                if int((zone_by_key.get(key) or {}).get("level") or 0) >= 60
            ],
            "performance_policy": "disable_effects_on_low_power_device",
        },
    }


def _coerce_map_bounds(value: Any) -> Optional[list[list[float]]]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        west, south = float(value[0][0]), float(value[0][1])
        east, north = float(value[1][0]), float(value[1][1])
    except (IndexError, TypeError, ValueError):
        return None
    if west >= east or south >= north:
        return None
    return [[west, south], [east, north]]


def _operator_map_bounds(map_row: WorkspaceMap) -> list[list[float]]:
    settings = map_row.settings if isinstance(map_row.settings, dict) else {}
    renderer = settings.get("renderer_config")
    renderer = renderer if isinstance(renderer, dict) else {}
    for candidate in (
        renderer.get("bounds"),
        settings.get("bounds"),
        settings.get("geo_bounds"),
    ):
        bounds = _coerce_map_bounds(candidate)
        if bounds:
            return bounds
    if str(map_row.country or "").strip().lower() == "france":
        return [
            [OCTOCITY_MAP_BOUNDS["west"], OCTOCITY_MAP_BOUNDS["south"]],
            [OCTOCITY_MAP_BOUNDS["east"], OCTOCITY_MAP_BOUNDS["north"]],
        ]
    return [[-180.0, -85.0], [180.0, 85.0]]


def _operator_zone_feature(
    zone: dict[str, Any],
    view_box: tuple[float, float, float, float],
    bounds: list[list[float]],
) -> Optional[dict[str, Any]]:
    polygon = str(zone.get("polygon") or "")
    coordinates = _polygon_to_lonlat(polygon, view_box, bounds=bounds)
    geometry: Optional[dict[str, Any]] = None
    if len(coordinates) >= 4:
        geometry = {"type": "Polygon", "coordinates": [coordinates]}
    else:
        centroid = _point_to_lonlat(zone.get("centroid") or {}, view_box, bounds=bounds)
        if centroid:
            geometry = {"type": "Point", "coordinates": centroid}
    if geometry is None:
        return None
    return {
        "type": "Feature",
        "id": str(zone.get("id") or zone.get("zone_id") or zone.get("name")),
        "geometry": geometry,
        "properties": {
            "id": zone.get("id"),
            "zone_id": zone.get("id"),
            "zone_name": zone.get("name"),
            "name": zone.get("name"),
            "level": zone.get("level"),
            "tone": zone.get("tone"),
            "signals": zone.get("signals") or [],
            "recommendations": zone.get("recommendations") or [],
            "source": "workspace_operator_map",
        },
    }


def _operator_workspace_map_renderer_payload(
    map_row: WorkspaceMap,
    zones: list[dict[str, Any]],
) -> dict[str, Any]:
    view_box = _parse_view_box(map_row.view_box)
    bounds = _operator_map_bounds(map_row)
    empty_collection: dict[str, Any] = {"type": "FeatureCollection", "features": []}
    zone_features = [
        feature
        for zone in zones
        if (feature := _operator_zone_feature(zone, view_box, bounds)) is not None
    ]
    marker_features = []
    camera_presets: dict[str, dict[str, Any]] = {}
    west, south = bounds[0]
    east, north = bounds[1]
    map_center = _point_to_lonlat(map_row.center or {}, view_box, bounds=bounds) or [
        round((west + east) / 2, 5),
        round((south + north) / 2, 5),
    ]
    camera_presets["country"] = {
        "longitude": map_center[0],
        "latitude": map_center[1],
        "zoom": 5.4,
        "pitch": 0,
        "bearing": 0,
        "duration_ms": 900,
    }
    for zone in zones:
        centroid = _point_to_lonlat(zone.get("centroid") or {}, view_box, bounds=bounds)
        if centroid is None:
            continue
        zone_key = str(zone.get("id") or zone.get("zone_id") or zone.get("name"))
        marker_features.append(
            {
                "type": "Feature",
                "id": f"{zone_key}-marker",
                "geometry": {"type": "Point", "coordinates": centroid},
                "properties": {
                    "zone_id": zone.get("id"),
                    "name": zone.get("name"),
                    "level": zone.get("level"),
                    "tone": zone.get("tone"),
                    "source": "workspace_operator_map",
                },
            }
        )
        camera_presets[zone_key] = {
            "longitude": centroid[0],
            "latitude": centroid[1],
            "zoom": 7.0,
            "pitch": 0,
            "bearing": 0,
            "duration_ms": 850,
        }

    source_counts = {
        "territorial-risk": len(zones),
        "open-intelligence": sum(
            len(zone.get("drivers") or zone.get("signals") or []) for zone in zones
        ),
        "agenda-windows": sum(
            len(zone.get("recommended_windows") or []) for zone in zones
        ),
        "preventive-actions": sum(
            len(zone.get("recommendations") or []) for zone in zones
        ),
    }
    layer_specs = (
        ("territorial-risk", "Workspace zones", "Zones", "zone_score"),
        ("open-intelligence", "Workspace signals", "Signals", "signal"),
        ("agenda-windows", "Action windows", "Windows", "agenda_window"),
        ("preventive-actions", "Reviewed actions", "Actions", "action"),
    )
    layer_catalog = [
        {
            "key": key,
            "label": label,
            "short_label": short_label,
            "deck_group": "workspace",
            "tone": "cyan" if key == "territorial-risk" else "blue",
            "visible": True,
            "kind": kind,
            "count": source_counts.get(key, 0),
            "confidence": 75,
        }
        for key, label, short_label, kind in layer_specs
    ]
    updated_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    layer_registry = [
        {
            **layer,
            "group": "Workspace",
            "icon": "target" if layer["key"] == "territorial-risk" else "layer",
            "status": "ready" if layer["count"] else "empty",
            "state_label": "ready" if layer["count"] else "empty",
            "freshness": "workspace data",
            "freshness_at": updated_at,
            "failure_reason": None,
            "default_visible": True,
            "source_kind": "workspace_operator_map",
            "source_count": layer["count"],
            "renderer_support": ["maplibre", "deck.gl", "svg-fallback"],
            "tooltip": {
                "title": layer["label"],
                "body": "Workspace-scoped operator data.",
            },
        }
        for layer in layer_catalog
    ]
    basemap_options = _map_basemap_options()
    default_basemap = "administrative"
    default_style = next(
        option["style"] for option in basemap_options if option["key"] == default_basemap
    )
    settings = map_row.settings if isinstance(map_row.settings, dict) else {}
    configured_renderer = settings.get("renderer_config")
    configured_renderer = configured_renderer if isinstance(configured_renderer, dict) else {}
    renderer_config = {
        "renderer": "maplibre",
        "rendering_profile": "workspace_operator_v1",
        "fallback_renderer": "svg",
        "basemap_policy": "workspace_operator_with_public_basemap",
        "default_basemap": default_basemap,
        "style": default_style,
        "initial_view_state": camera_presets["country"],
        "bounds": bounds,
        "regional_bounds": bounds,
        "attribution": "Workspace operator data · OpenStreetMap/CARTO basemap",
        "interaction_contract": {
            "commands": sorted(MAP_COMMAND_INTENTS),
            "scenario_modes": ["explorer", "comprendre", "decider"],
            "selection": "zone",
            "events": ["zone_selected", "map_state_updated", "source_panel_requested"],
        },
    }
    renderer_config.update(configured_renderer)
    renderer_config["bounds"] = bounds
    renderer_config["regional_bounds"] = bounds
    event_points = {"type": "FeatureCollection", "features": copy.deepcopy(marker_features)}
    active_layers = [layer["key"] for layer in layer_catalog]
    forecast_signals = [
        {
            "id": f"forecast-{zone.get('id')}",
            "zone_id": zone.get("id"),
            "title": f"{zone.get('name')} · {zone.get('tone') or 'monitoring'}",
            "horizon": "workspace-defined",
            "score": int(zone.get("level") or 0),
            "confidence": 70,
            "drivers": zone.get("drivers") or zone.get("signals") or [],
            "recommended_action": (zone.get("recommendations") or ["Review signal"])[0],
            "source_refs": zone.get("sources") or [],
        }
        for zone in zones
    ]
    return {
        "map_version": "workspace_map_v1",
        "rendering_profile": "workspace_operator_v1",
        "time_range": "7d",
        "available_time_ranges": MAP_TIME_RANGES,
        "renderer_config": renderer_config,
        "basemap_options": basemap_options,
        "layer_catalog": layer_catalog,
        "layer_registry": layer_registry,
        "default_map_state": {
            "basemap": renderer_config.get("default_basemap") or default_basemap,
            "active_layers": active_layers,
            "selected_zone": zones[0].get("id") if zones else None,
            "camera": camera_presets["country"],
            "time_range": "7d",
            "mode": "explorer",
        },
        "geodata_metadata": {
            "source": "Workspace operator map",
            "license": "workspace-defined",
            "synthetic": False,
            "admin_levels": [],
        },
        "country_boundary": copy.deepcopy(empty_collection),
        "district_boundaries": copy.deepcopy(empty_collection),
        "admin_boundaries": copy.deepcopy(empty_collection),
        "cities": copy.deepcopy(empty_collection),
        "region_scores": _region_scores(zones),
        "event_points": event_points,
        "maritime_snapshot": {
            "mode": "workspace_operator",
            "ports": [],
            "density_zones": [],
            "disruptions": [],
        },
        "source_health": {
            "status": "ready",
            "updated_at": updated_at,
            "layers": layer_registry,
            "notes": "Workspace-scoped operator sources.",
        },
        "forecast_signals": forecast_signals,
        "scenario_modes": _scenario_modes_payload(),
        "default_layer_groups": {
            "explorer": active_layers,
            "comprendre": active_layers,
            "decider": active_layers,
        },
        "tooltip_templates": _tooltip_templates(),
        "source_counts": source_counts,
        "geojson_sources": {
            "zones": {"type": "FeatureCollection", "features": zone_features},
            "markers": {"type": "FeatureCollection", "features": marker_features},
            "context_markers": copy.deepcopy(empty_collection),
            "context_lines": copy.deepcopy(empty_collection),
            "event_points": event_points,
            "maritime_area": copy.deepcopy(empty_collection),
            "maritime_points": copy.deepcopy(empty_collection),
            "maritime_routes": copy.deepcopy(empty_collection),
            "maritime_density": copy.deepcopy(empty_collection),
            "social_geo": copy.deepcopy(empty_collection),
            "military_air": copy.deepcopy(empty_collection),
            "border_tension": copy.deepcopy(empty_collection),
            "satellite_footprint": copy.deepcopy(empty_collection),
        },
        "camera_presets": camera_presets,
        "visual_effects": {
            "zone_halo": True,
            "marker_pulse": True,
            "arc_links": [
                {
                    "source": map_center,
                    "target": feature["geometry"]["coordinates"],
                    "tone": feature["properties"].get("tone"),
                    "level": feature["properties"].get("level"),
                    "label": f"Workspace {feature['properties'].get('name')}",
                }
                for feature in marker_features
            ],
            "performance_policy": "disable_effects_on_low_power_device",
        },
    }


def workspace_map_renderer_payload(
    map_row: WorkspaceMap,
    zones: list[dict[str, Any]],
) -> dict[str, Any]:
    if _is_octocity_map(map_row):
        return _octocity_workspace_map_renderer_payload(map_row, zones)
    if _is_operator_map(map_row):
        return _operator_workspace_map_renderer_payload(map_row, zones)
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
            **_s3_security_geojson_sources(),
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


def _ensure_map_layers(
    db: DBSession,
    map_row: WorkspaceMap,
    *,
    layer_specs: Optional[list[dict[str, Any]]] = None,
    seed_label: Optional[str] = None,
) -> None:
    existing = {
        layer.key
        for layer in db.query(WorkspaceMapLayer.key).filter(WorkspaceMapLayer.map_id == map_row.id).all()
    }
    for layer in layer_specs or DEFAULT_RENDERER_LAYERS:
        if layer["key"] in existing:
            continue
        payload = {
            **layer["payload"],
            **({"seed": seed_label} if seed_label == "octocity" else {}),
        }
        db.add(
            WorkspaceMapLayer(
                id=str(uuid4()),
                map_id=map_row.id,
                key=layer["key"],
                label=layer["label"],
                kind=layer["kind"],
                visible=layer["visible"],
                payload=payload,
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


def _point_to_lonlat(
    point: Any,
    view_box: tuple[float, float, float, float],
    *,
    bounds: Optional[list[list[float]]] = None,
) -> Optional[list[float]]:
    if isinstance(point, (list, tuple)) and len(point) >= 2:
        try:
            return [float(point[0]), float(point[1])]
        except (TypeError, ValueError):
            return None
    if not isinstance(point, dict):
        return None
    longitude = point.get("longitude", point.get("lon"))
    latitude = point.get("latitude", point.get("lat"))
    if longitude is not None and latitude is not None:
        try:
            return [float(longitude), float(latitude)]
        except (TypeError, ValueError):
            return None
    try:
        x = float(point.get("x"))
        y = float(point.get("y"))
    except (TypeError, ValueError):
        return None
    min_x, min_y, width, height = view_box
    x_ratio = max(0.0, min(1.0, (x - min_x) / width))
    y_ratio = max(0.0, min(1.0, (y - min_y) / height))
    active_bounds = bounds or [
        [IVORY_COAST_BOUNDS["west"], IVORY_COAST_BOUNDS["south"]],
        [IVORY_COAST_BOUNDS["east"], IVORY_COAST_BOUNDS["north"]],
    ]
    west, south = active_bounds[0]
    east, north = active_bounds[1]
    lon = west + x_ratio * (east - west)
    lat = north - y_ratio * (north - south)
    return [round(lon, 5), round(lat, 5)]


def _polygon_to_lonlat(
    polygon: str,
    view_box: tuple[float, float, float, float],
    *,
    bounds: Optional[list[list[float]]] = None,
) -> list[list[float]]:
    coords: list[list[float]] = []
    for token in polygon.split():
        if "," not in token:
            continue
        try:
            x_raw, y_raw = token.split(",", 1)
            point = _point_to_lonlat(
                {"x": float(x_raw), "y": float(y_raw)},
                view_box,
                bounds=bounds,
            )
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


def _find_port_payload(target: Optional[str], *, octocity: bool = False) -> Optional[dict[str, Any]]:
    if not target:
        return None
    normalized = target.lower().strip()
    if octocity:
        ports = OCTOCITY_PORTS
        aliases = {
            "marseille": "port-marseille",
            "port-marseille": "port-marseille",
            "nantes": "port-nantes",
            "port-nantes": "port-nantes",
        }
    else:
        ports = MARITIME_PORTS
        aliases = {
            "abidjan": "port-abidjan",
            "port-abidjan": "port-abidjan",
            "vridi": "port-abidjan",
            "san pedro": "port-san-pedro",
            "san-pedro": "port-san-pedro",
            "port-san-pedro": "port-san-pedro",
        }
    canonical = aliases.get(normalized, normalized)
    for port in ports:
        if canonical in {str(port.get("id", "")).lower(), str(port.get("name", "")).lower()}:
            return port
        if canonical and canonical in str(port.get("name", "")).lower():
            return port
    return None


def _extract_zone_target(query: str, *, octocity: bool = False) -> Optional[str]:
    labels_by_zone = (
        {
            "zone-nord": ("nord", "lille"),
            "zone-ouest": ("ouest", "rennes", "bordeaux"),
            "zone-centre": ("centre", "paris", "lyon"),
            "zone-sud": ("sud", "toulouse", "nice"),
            "zone-est": ("est", "strasbourg"),
        }
        if octocity
        else {
            "zone-nord": ("nord", "korhogo", "frontaliere nord"),
            "zone-ouest": ("ouest", "man", "liberia", "guinee"),
            "zone-centre": ("centre", "yamoussoukro"),
            "zone-sud": ("sud", "abidjan", "littoral"),
            "zone-est": ("est", "ghana", "bondoukou"),
        }
    )
    for key, labels in labels_by_zone.items():
        if any(label in query for label in labels):
            return key
    return None


def _extract_port_target(query: str, *, octocity: bool = False) -> Optional[str]:
    if octocity:
        if "nantes" in query:
            return "port-nantes"
        if "marseille" in query:
            return "port-marseille"
        if any(label in query for label in ("abidjan", "golfe de guin", "douane")):
            return None
        if any(label in query for label in ("port", "logistique", "maritime", "navire", "bateau")):
            return "port-marseille"
        return None
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
    octocity: bool = False,
) -> str:
    if intent == "reset_view":
        if octocity:
            return "Vue Octocity réinitialisée avec les couches opérationnelles par défaut."
        return "Vue Côte d'Ivoire réinitialisée avec les couches ministérielles par défaut."
    if intent == "set_basemap":
        return f"Fond cartographique basculé sur {basemap or 'le fond par défaut'}."
    if intent == "set_time_range":
        return f"Fenêtre temporelle basculée sur {time_range or 'la tendance active'}."
    if intent == "set_layers":
        return "Couches ministérielles ajustées pour la lecture territoriale demandée."
    if intent in {"focus_port", "show_vessel_snapshot", "show_disruption"} and selected_port:
        if octocity:
            return (
                f"Focus logistique sur {selected_port.get('name')} : signaux ouverts, contexte France et actions "
                "recommandées activés pour une lecture Octocity à validation humaine."
            )
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


def _port_sources(
    selected_port: Optional[dict[str, Any]],
    *,
    octocity: bool = False,
) -> list[dict[str, Any]]:
    if not selected_port:
        return [{"title": "Logistics snapshot", "kind": "logistics_snapshot", "source_label": "Octocity fixture"}]
    if octocity:
        return [
            {
                "title": selected_port.get("name"),
                "kind": "logistics_gateway",
                "source_label": "Octocity synthetic logistics fixture",
                "port": selected_port.get("id"),
            },
            {
                "title": "Synthetic operating corridor",
                "kind": "logistics_route",
                "source_label": "Octocity operating context",
                "port": selected_port.get("id"),
            },
        ]
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
