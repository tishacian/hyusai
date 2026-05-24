"""Workspace-scoped maritime / AIS endpoints for SENTINEL-CI.

These endpoints expose vessel positions to the cockpit map layer (`maritime
vessels`) and to AYA's vessel-evidence action. They are *advisory-only* and
backed by a provider-neutral service (``maritime_tracking``) that defaults to
a demo-safe baseline snapshot so the cockpit always renders, even without an
upstream AIS subscription.

All payloads are workspace-scoped and audit-logged. Cross-workspace access is
prevented by the regular ``get_current_workspace`` dependency; the maritime
data itself is global (port of Abidjan is a public location) but the audit
trail remains tenant-bounded.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.services.audit_logger import emit_audit_event
from app.services.maritime_tracking import (
    BBox,
    fetch_snapshot,
    fetch_vessels_in_bbox,
    find_vessel_by_mmsi,
    serialize_snapshot,
    serialize_vessel,
)
from app.services.webcam_proxy import (
    get_spec as get_webcam_spec,
    recommended_webcam_for_vessel,
    webcam_cycle_for_vessel,
)


router = APIRouter()


def _actor(user: User) -> str:
    return user.email or user.username or user.id


def _audit(
    *,
    db: DBSession,
    workspace: Workspace,
    user: User,
    event_type: str,
    details: dict,
) -> None:
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type=event_type,
        actor=_actor(user),
        details=details,
    )


def _parse_bbox(raw: Optional[str]) -> Optional[BBox]:
    """Parse ``?bbox=west,south,east,north`` into a validated ``BBox``."""
    if not raw:
        return None
    parts = [token.strip() for token in raw.split(",") if token.strip()]
    if len(parts) != 4:
        raise HTTPException(status_code=400, detail="bbox_must_have_4_values_west_south_east_north")
    try:
        west, south, east, north = (float(value) for value in parts)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="bbox_values_must_be_numeric") from exc
    if west > east or south > north:
        raise HTTPException(status_code=400, detail="bbox_west_south_must_be_lower_than_east_north")
    try:
        return BBox(west=west, south=south, east=east, north=north)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"bbox_invalid:{exc}") from exc


@router.get("/vessels")
def list_vessels(
    bbox: Optional[str] = Query(default=None, description="west,south,east,north"),
    limit: int = Query(default=50, ge=1, le=500),
    vessel_types: Optional[str] = Query(
        default=None,
        description="Comma-separated list of vessel types (cargo, container, tanker, roro, fishing, tug, passenger, other)",
        max_length=160,
    ),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    parsed_bbox = _parse_bbox(bbox)
    types = [item.strip() for item in (vessel_types or "").split(",") if item.strip()] or None
    snapshot = fetch_snapshot(parsed_bbox)
    vessels = fetch_vessels_in_bbox(parsed_bbox, limit=limit, vessel_types=types)
    payload = serialize_snapshot(snapshot)
    serialized: list[dict] = []
    for vessel in vessels:
        item = serialize_vessel(vessel)
        webcam_source_id = recommended_webcam_for_vessel(
            mmsi=vessel.mmsi,
            cargo_id=vessel.linked_cargo_id,
        )
        if webcam_source_id:
            item["recommended_webcam_source_id"] = webcam_source_id
        serialized.append(item)
    payload["vessels"] = serialized
    payload["count"] = len(vessels)
    payload["workspace"] = {"id": workspace.id, "slug": workspace.slug}
    payload["filters"] = {
        "bbox": payload.get("bbox"),
        "vessel_types": types or [],
        "limit": limit,
    }
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="maritime.vessels.listed",
        details={
            "provider": snapshot.provider,
            "source": snapshot.source,
            "count": len(vessels),
            "bbox": payload.get("bbox"),
            "vessel_types": types or [],
        },
    )
    return payload


@router.get("/vessels/{mmsi}")
def vessel_detail(
    mmsi: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    if not mmsi or not mmsi.strip().isdigit():
        raise HTTPException(status_code=400, detail="mmsi_must_be_numeric")
    vessel = find_vessel_by_mmsi(mmsi)
    if vessel is None:
        raise HTTPException(status_code=404, detail="vessel_not_found")
    snapshot = fetch_snapshot()
    vessel_payload = serialize_vessel(vessel)
    recommended_id = recommended_webcam_for_vessel(
        mmsi=vessel.mmsi,
        cargo_id=vessel.linked_cargo_id,
    )
    if recommended_id:
        vessel_payload["recommended_webcam_source_id"] = recommended_id
    payload = {
        "vessel": vessel_payload,
        "snapshot": {
            "provider": snapshot.provider,
            "source": snapshot.source,
            "fetched_at": snapshot.fetched_at,
            "ttl_seconds": snapshot.ttl_seconds,
            "embed_url": snapshot.embed_url,
            "attribution": snapshot.attribution,
        },
        "workspace": {"id": workspace.id, "slug": workspace.slug},
        "policy": "advisory_only",
    }
    if recommended_id:
        spec = get_webcam_spec(recommended_id)
        cycle_ids = webcam_cycle_for_vessel(mmsi=vessel.mmsi, cargo_id=vessel.linked_cargo_id)
        payload["recommended_webcam"] = {
            "source_id": recommended_id,
            "label": spec.label if spec else None,
            "attribution": spec.attribution if spec else None,
            "label_disclaimer": spec.label_disclaimer if spec else None,
            "proxy_url": f"/api/v1/mission-room/webcams/proxy?source_id={recommended_id}",
            "cycle": [
                {
                    "source_id": candidate,
                    "label": get_webcam_spec(candidate).label if get_webcam_spec(candidate) else None,
                    "proxy_url": f"/api/v1/mission-room/webcams/proxy?source_id={candidate}",
                }
                for candidate in cycle_ids
            ],
        }
    if vessel.linked_cargo_id:
        payload["linked_cargo"] = {
            "id": vessel.linked_cargo_id,
            "project_ref": vessel.linked_project_ref,
            "narrative_role": vessel.demo_role,
        }
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="maritime.vessel.viewed",
        details={
            "mmsi": vessel.mmsi,
            "imo": vessel.imo,
            "provider": snapshot.provider,
            "source": snapshot.source,
            "linked_cargo": vessel.linked_cargo_id,
            "recommended_webcam_source_id": recommended_id,
        },
    )
    return payload


@router.get("/snapshot")
def snapshot_metadata(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Return only the provider envelope (no vessels) for sanity checks / UI footer."""
    snapshot = fetch_snapshot()
    payload = {
        "provider": snapshot.provider,
        "source": snapshot.source,
        "fetched_at": snapshot.fetched_at,
        "ttl_seconds": snapshot.ttl_seconds,
        "bbox": snapshot.bbox.model_dump() if snapshot.bbox else None,
        "embed_url": snapshot.embed_url,
        "attribution": snapshot.attribution,
        "limitations": list(snapshot.limitations or []),
        "policy": "advisory_only",
        "workspace": {"id": workspace.id, "slug": workspace.slug},
    }
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="maritime.snapshot.viewed",
        details={"provider": snapshot.provider, "source": snapshot.source},
    )
    return payload
