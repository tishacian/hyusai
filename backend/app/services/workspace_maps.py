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
    db.add_all(
        [
            WorkspaceMapLayer(
                id=str(uuid4()),
                map_id=map_row.id,
                key="territorial-risk",
                label="Risque territorial",
                kind="zone_score",
                visible=True,
                payload={"scoring": "signals+projects+agenda"},
                sort_order=10,
            ),
            WorkspaceMapLayer(
                id=str(uuid4()),
                map_id=map_row.id,
                key="open-intelligence",
                label="Signaux faibles",
                kind="signal",
                visible=True,
                payload={"sources": ["rss_press", "cabinet_note", "project_record"]},
                sort_order=20,
            ),
        ]
    )
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
