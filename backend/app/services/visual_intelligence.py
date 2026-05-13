"""Workspace visual intelligence for provider-neutral situation monitoring."""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.models.knowledge_collection import KnowledgeCollection
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_visual import (
    WorkspaceVisualCapture,
    WorkspaceVisualObservation,
    WorkspaceVisualSource,
)
from app.services.audit_logger import emit_audit_event
from app.services.object_store import get_object_store
from app.services.workspace_jobs import create_workspace_job, serialize_job, transition_job


VISUAL_COLLECTION_SLUG = "sentinel-ci-visual-intelligence"
DEFAULT_SOURCE_NAME = "Abidjan - couche webcam publique"
LEGACY_DEFAULT_SOURCE_NAME = "Abidjan Plateau - veille visuelle"
DEFAULT_SOURCE_URL = "https://images.pictimo.com/storage/live_thumbs/orig_45907.jpg"
DEFAULT_SOURCE_PAGE = "https://www.pictimo.com/ivory-coast/abidjan/45907/webcam-live-webcam-in-abidjan"


def ensure_visual_intelligence_seed(
    db: DBSession,
    workspace: Workspace,
    *,
    system_id: Optional[str] = None,
) -> dict[str, Any]:
    """Seed the visual connector and Knowledge target for demo workspaces."""
    collection = ensure_visual_collection(db, workspace)
    existing = (
        db.query(WorkspaceVisualSource)
        .filter(
            WorkspaceVisualSource.workspace_id == workspace.id,
            or_(WorkspaceVisualSource.name == DEFAULT_SOURCE_NAME, WorkspaceVisualSource.name == LEGACY_DEFAULT_SOURCE_NAME),
        )
        .first()
    )
    source_created = False
    default_policy = {
        "capture": "manual_or_scheduled_snapshot",
        "allowed_use": "situational_briefing",
        "pii_policy": "no_identification_no_biometrics",
        "human_validation_required": True,
        "recording": "no_continuous_recording",
    }
    default_metadata = _default_webcam_metadata()
    if not existing:
        existing = WorkspaceVisualSource(
            id=str(uuid4()),
            workspace_id=workspace.id,
            system_id=system_id,
            name=DEFAULT_SOURCE_NAME,
            description="Couche webcam publique pour snapshots horodates, analyse visuelle legere et posture de situation.",
            source_url=DEFAULT_SOURCE_URL,
            source_type="webcam",
            adapter="http_image",
            region="Abidjan / Le Plateau",
            status="active",
            enabled=True,
            capture_cadence_minutes=60,
            policy=default_policy,
            meta_data=default_metadata,
        )
        db.add(existing)
        db.flush()
        source_created = True
        emit_audit_event(
            db=db,
            workspace_id=workspace.id,
            event_type="visual.source.seeded",
            actor="system",
            details={"source_id": existing.id, "adapter": existing.adapter, "collection": collection.slug},
        )
    else:
        metadata = dict(existing.meta_data or {})
        metadata.update({
            key: value
            for key, value in default_metadata.items()
            if key not in metadata
            or key
            in {
                "provider",
                "layer_kind",
                "preview_url",
                "source_page",
                "analysis_mode",
                "attribution",
                "timelapse_policy",
            }
        })
        existing.name = DEFAULT_SOURCE_NAME
        existing.description = "Couche webcam publique pour snapshots horodates, analyse visuelle legere et posture de situation."
        existing.source_url = DEFAULT_SOURCE_URL
        existing.source_type = "webcam"
        existing.adapter = "http_image"
        existing.region = "Abidjan / Le Plateau"
        existing.enabled = True
        if existing.status not in {"active", "paused"}:
            existing.status = "active"
        existing.capture_cadence_minutes = existing.capture_cadence_minutes or 60
        existing.policy = {**default_policy, **(existing.policy or {})}
        existing.meta_data = metadata
        existing.system_id = existing.system_id or system_id
        existing.updated_at = datetime.utcnow()
        db.flush()
    return {"collection": collection.slug, "source_id": existing.id, "source_created": source_created}


def ensure_visual_collection(db: DBSession, workspace: Workspace) -> KnowledgeCollection:
    existing = (
        db.query(KnowledgeCollection)
        .filter(KnowledgeCollection.workspace_id == workspace.id, KnowledgeCollection.slug == VISUAL_COLLECTION_SLUG)
        .first()
    )
    if existing:
        existing.name = "SENTINEL-CI Visual Intelligence"
        existing.description = "Visual snapshots, observations and posture summaries from authorized workspace visual streams."
        return existing
    collection = KnowledgeCollection(
        id=str(uuid4()),
        workspace_id=workspace.id,
        slug=VISUAL_COLLECTION_SLUG,
        name="SENTINEL-CI Visual Intelligence",
        description="Visual snapshots, observations and posture summaries from authorized workspace visual streams.",
        status="ready",
        document_names=[],
        vector_collection_name=f"{workspace.slug}__{VISUAL_COLLECTION_SLUG}",
        artifact_prefix=f"workspaces/{workspace.id}/collections/{VISUAL_COLLECTION_SLUG}",
        embedding_model="text-embedding-3-small",
        chunking_method="semantic",
        chunking_params={"source": "visual_intelligence", "demo_safe": True},
    )
    db.add(collection)
    db.flush()
    return collection


def list_sources(db: DBSession, workspace: Workspace) -> list[WorkspaceVisualSource]:
    return (
        db.query(WorkspaceVisualSource)
        .filter(WorkspaceVisualSource.workspace_id == workspace.id)
        .order_by(WorkspaceVisualSource.created_at.asc())
        .all()
    )


def get_source(db: DBSession, workspace: Workspace, source_id: str) -> WorkspaceVisualSource:
    row = (
        db.query(WorkspaceVisualSource)
        .filter(WorkspaceVisualSource.id == source_id, WorkspaceVisualSource.workspace_id == workspace.id)
        .first()
    )
    if not row:
        raise LookupError("visual_source_not_found")
    return row


def create_source(
    db: DBSession,
    workspace: Workspace,
    user: Optional[User],
    *,
    name: str,
    source_url: str,
    description: str = "",
    source_type: str = "webcam",
    adapter: str = "http_image",
    region: str = "",
    capture_cadence_minutes: int = 60,
    enabled: bool = True,
    policy: Optional[dict[str, Any]] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> WorkspaceVisualSource:
    row = WorkspaceVisualSource(
        id=str(uuid4()),
        workspace_id=workspace.id,
        created_by_user_id=user.id if user else None,
        name=name,
        description=description,
        source_url=source_url,
        source_type=source_type,
        adapter=adapter,
        region=region,
        enabled=enabled,
        status="active" if enabled else "paused",
        capture_cadence_minutes=max(1, min(int(capture_cadence_minutes or 60), 1440)),
        policy=policy
        or {
            "capture": "manual_or_scheduled_snapshot",
            "allowed_use": "situational_briefing",
            "pii_policy": "no_identification_no_biometrics",
        },
        meta_data=metadata or {},
    )
    db.add(row)
    db.flush()
    _audit(db, workspace, user, "visual.source.created", {"source_id": row.id, "adapter": row.adapter})
    return row


def update_source(
    db: DBSession,
    workspace: Workspace,
    user: Optional[User],
    source_id: str,
    updates: dict[str, Any],
) -> WorkspaceVisualSource:
    row = get_source(db, workspace, source_id)
    allowed = {
        "name",
        "description",
        "source_url",
        "source_type",
        "adapter",
        "region",
        "status",
        "enabled",
        "capture_cadence_minutes",
        "policy",
        "metadata",
    }
    touched: list[str] = []
    for key, value in updates.items():
        if key not in allowed:
            continue
        attr = "meta_data" if key == "metadata" else key
        if key == "capture_cadence_minutes" and value is not None:
            value = max(1, min(int(value), 1440))
        setattr(row, attr, value)
        touched.append(key)
    row.updated_at = datetime.utcnow()
    db.flush()
    _audit(db, workspace, user, "visual.source.updated", {"source_id": row.id, "updates": sorted(touched)})
    return row


def capture_source(
    db: DBSession,
    workspace: Workspace,
    source: WorkspaceVisualSource,
    user: Optional[User] = None,
) -> dict[str, Any]:
    if source.workspace_id != workspace.id:
        raise LookupError("visual_source_not_found")
    if not source.enabled or source.status != "active":
        raise RuntimeError("visual_source_not_active")
    job = create_workspace_job(
        db,
        workspace,
        user,
        kind="visual_snapshot_capture",
        title=f"Capture visuelle · {source.name}",
        input_ref={"source_id": source.id, "adapter": source.adapter},
        status="queued",
    )
    transition_job(db, workspace, job, "running", progress=25, stage="capture_snapshot", user=user)
    capture_id = str(uuid4())
    try:
        content, mime_type, capture_meta = _capture_bytes(source)
        digest = hashlib.sha256(content).hexdigest()
        ext = _extension_for_mime(mime_type)
        store = get_object_store()
        object_key = store.key("workspaces", workspace.id, "visual-intelligence", source.id, f"{capture_id}.{ext}")
        store.write_bytes(object_key, content)
        capture = WorkspaceVisualCapture(
            id=capture_id,
            workspace_id=workspace.id,
            source_id=source.id,
            job_id=job.id,
            status="captured",
            object_key=object_key,
            mime_type=mime_type,
            size_bytes=len(content),
            sha256=digest,
            width=capture_meta.get("width"),
            height=capture_meta.get("height"),
            meta_data=capture_meta,
            captured_at=datetime.utcnow(),
        )
        db.add(capture)
        db.flush()
        transition_job(db, workspace, job, "running", progress=70, stage="analyze_snapshot", user=user)
        observation = _analyze_capture(db, workspace, source, capture, capture_meta)
        capture.status = "analyzed"
        source.last_captured_at = capture.captured_at
        source.status = "active"
        source.updated_at = datetime.utcnow()
        sync_key = sync_observation_to_knowledge(db, workspace, observation)
        transition_job(
            db,
            workspace,
            job,
            "completed",
            progress=100,
            stage="synced_to_knowledge",
            result={"capture_id": capture.id, "observation_id": observation.id, "knowledge_object_key": sync_key},
            user=user,
        )
        _audit(
            db,
            workspace,
            user,
            "visual.capture.completed",
            {
                "source_id": source.id,
                "capture_id": capture.id,
                "observation_id": observation.id,
                "object_key": capture.object_key,
                "vigilance_score": observation.vigilance_score,
            },
        )
        db.flush()
        return {
            "job": serialize_job(job),
            "source": serialize_source(source),
            "capture": serialize_capture(capture),
            "observation": serialize_observation(observation),
        }
    except Exception as exc:  # noqa: BLE001
        source.status = "error"
        transition_job(db, workspace, job, "failed", progress=100, stage="failed", error=str(exc), user=user)
        failed = WorkspaceVisualCapture(
            id=capture_id,
            workspace_id=workspace.id,
            source_id=source.id,
            job_id=job.id,
            status="failed",
            object_key="",
            mime_type="application/octet-stream",
            size_bytes=0,
            sha256="",
            error=str(exc),
            meta_data={"adapter": source.adapter},
            captured_at=datetime.utcnow(),
        )
        db.add(failed)
        _audit(db, workspace, user, "visual.capture.failed", {"source_id": source.id, "job_id": job.id, "error": str(exc)})
        db.flush()
        raise


def list_captures(db: DBSession, workspace: Workspace, source_id: str, *, limit: int = 50) -> list[WorkspaceVisualCapture]:
    return (
        db.query(WorkspaceVisualCapture)
        .filter(WorkspaceVisualCapture.workspace_id == workspace.id, WorkspaceVisualCapture.source_id == source_id)
        .order_by(WorkspaceVisualCapture.captured_at.desc())
        .limit(max(1, min(limit, 200)))
        .all()
    )


def get_capture(db: DBSession, workspace: Workspace, capture_id: str) -> WorkspaceVisualCapture:
    row = (
        db.query(WorkspaceVisualCapture)
        .filter(WorkspaceVisualCapture.id == capture_id, WorkspaceVisualCapture.workspace_id == workspace.id)
        .first()
    )
    if not row:
        raise LookupError("visual_capture_not_found")
    return row


def latest_observations(db: DBSession, workspace: Workspace, *, limit: int = 5) -> list[WorkspaceVisualObservation]:
    return (
        db.query(WorkspaceVisualObservation)
        .filter(WorkspaceVisualObservation.workspace_id == workspace.id)
        .order_by(WorkspaceVisualObservation.created_at.desc())
        .limit(max(1, min(limit, 20)))
        .all()
    )


def dashboard_payload(db: DBSession, workspace: Workspace) -> dict[str, Any]:
    sources = list_sources(db, workspace)
    captures = (
        db.query(WorkspaceVisualCapture)
        .filter(WorkspaceVisualCapture.workspace_id == workspace.id)
        .order_by(WorkspaceVisualCapture.captured_at.desc())
        .limit(25)
        .all()
    )
    observations = latest_observations(db, workspace, limit=8)
    active_sources = [source for source in sources if source.enabled and source.status == "active"]
    latest = observations[0] if observations else None
    posture = strategic_visual_posture(observations)
    return {
        "connector": {
            "id": "visual_streams",
            "label": "Flux visuels institutionnels",
            "status": "connected" if active_sources else "configured",
            "mode": "webcam_snapshot_layer",
            "policy": "no_identification_no_biometrics",
        },
        "source_health": {
            "active_sources": len(active_sources),
            "total_sources": len(sources),
            "captures": len(captures),
            "observations": len(observations),
            "last_capture_at": captures[0].captured_at.isoformat() if captures else None,
            "coverage_label": "Flux visuels habilites" if active_sources else "Aucune source active",
        },
        "posture": posture,
        "sources": [serialize_source(source) for source in sources],
        "captures": [serialize_capture(capture) for capture in captures[:10]],
        "observations": [serialize_observation(observation) for observation in observations],
        "latest_observation": serialize_observation(latest) if latest else None,
    }


def strategic_visual_posture(observations: list[WorkspaceVisualObservation]) -> dict[str, Any]:
    score = max((obs.vigilance_score for obs in observations), default=32)
    label = _level_label(score)
    return {
        "label": label,
        "score": score,
        "trend": "stable" if score < 55 else "a surveiller",
        "summary": _posture_summary(label, score),
    }


def visual_context_for_chat(db: DBSession, workspace: Workspace) -> str:
    observations = latest_observations(db, workspace, limit=4)
    if not observations:
        return "Aucune observation visuelle recente n'est disponible dans ce workspace."
    lines = ["Observations visuelles recentes:"]
    for obs in observations:
        lines.append(
            f"- {obs.created_at.isoformat()}: {obs.summary} "
            f"(vigilance {obs.vigilance_score}/100, confiance {round(obs.confidence * 100)}%, tags {', '.join(obs.tags or [])})"
        )
    return "\n".join(lines)


def handle_visual_chat_query(
    db: DBSession,
    workspace: Workspace,
    user: User,
    *,
    query: str,
    assistant_profile: Optional[str],
) -> Optional[dict[str, Any]]:
    if assistant_profile != "vigie_executive":
        return None
    lowered = (query or "").lower()
    triggers = ("visuel", "visuelle", "webcam", "camera", "caméra", "capture", "image", "flux", "observation")
    if not any(token in lowered for token in triggers):
        return None
    workspace_settings = dict((workspace.settings or {}).get("visual_intelligence") or {})
    if workspace.slug == "sentinel-ci" or workspace_settings.get("enabled"):
        ensure_visual_intelligence_seed(db, workspace)
    dashboard = dashboard_payload(db, workspace)
    observations = dashboard.get("observations") or []
    if not observations:
        content = (
            "Aucune observation visuelle recente n'est encore disponible. "
            "Je peux demander une capture d'un flux visuel habilite avant de consolider la synthese."
        )
    else:
        latest = observations[0]
        content = (
            "Derniere lecture visuelle disponible : "
            f"{latest.get('summary')} Niveau de vigilance {latest.get('vigilance_score')}/100, "
            f"confiance {round((latest.get('confidence') or 0) * 100)}%. "
            "Cette lecture reste indicative : elle soutient le briefing, mais ne remplace pas une validation humaine."
        )
    _audit(
        db,
        workspace,
        user,
        "visual.chat.context_used",
        {"observations": len(observations), "assistant_profile": assistant_profile},
    )
    return {
        "action": "visual_observation_read",
        "applied": False,
        "content": content,
        "dashboard": dashboard,
    }


def sync_observation_to_knowledge(
    db: DBSession,
    workspace: Workspace,
    observation: WorkspaceVisualObservation,
) -> str:
    collection = ensure_visual_collection(db, workspace)
    store = get_object_store()
    filename = f"visual-observation-{observation.id}.md"
    markdown = _observation_markdown(observation)
    original_key = store.key(collection.artifact_prefix, "original", filename)
    object_key = store.key(collection.artifact_prefix, "ingested", filename)
    store.write_text(original_key, markdown)
    store.write_text(object_key, markdown)
    docs = list(collection.document_names or [])
    if filename not in docs:
        docs.append(filename)
    collection.document_names = docs
    collection.document_count = len(docs)
    collection.chunk_count = max(collection.chunk_count or 0, len(docs))
    collection.status = "ready"
    collection.updated_at = datetime.utcnow()
    db.flush()
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="visual.observation.synced_to_knowledge",
        actor="system",
        details={
            "observation_id": observation.id,
            "collection": collection.slug,
            "object_key": object_key,
            "original_key": original_key,
        },
    )
    return object_key


def serialize_source(source: WorkspaceVisualSource) -> dict[str, Any]:
    return {
        "id": source.id,
        "name": source.name,
        "description": source.description,
        "source_url": source.source_url,
        "source_type": source.source_type,
        "adapter": source.adapter,
        "region": source.region,
        "status": source.status,
        "enabled": source.enabled,
        "capture_cadence_minutes": source.capture_cadence_minutes,
        "policy": source.policy or {},
        "metadata": source.meta_data or {},
        "last_captured_at": source.last_captured_at.isoformat() if source.last_captured_at else None,
        "created_at": source.created_at.isoformat() if source.created_at else None,
        "updated_at": source.updated_at.isoformat() if source.updated_at else None,
    }


def serialize_capture(capture: WorkspaceVisualCapture) -> dict[str, Any]:
    return {
        "id": capture.id,
        "source_id": capture.source_id,
        "job_id": capture.job_id,
        "status": capture.status,
        "object_key": capture.object_key,
        "mime_type": capture.mime_type,
        "size_bytes": capture.size_bytes,
        "sha256": capture.sha256,
        "width": capture.width,
        "height": capture.height,
        "error": capture.error,
        "metadata": capture.meta_data or {},
        "captured_at": capture.captured_at.isoformat() if capture.captured_at else None,
    }


def serialize_observation(observation: WorkspaceVisualObservation) -> dict[str, Any]:
    return {
        "id": observation.id,
        "source_id": observation.source_id,
        "capture_id": observation.capture_id,
        "summary": observation.summary,
        "tags": observation.tags or [],
        "confidence": observation.confidence,
        "vigilance_score": observation.vigilance_score,
        "level_label": observation.level_label,
        "source_refs": observation.source_refs or [],
        "provider": observation.provider,
        "model": observation.model,
        "metadata": observation.meta_data or {},
        "created_at": observation.created_at.isoformat() if observation.created_at else None,
    }


def _default_webcam_metadata() -> dict[str, Any]:
    return {
        "demo_fallback": True,
        "provider_neutral": True,
        "provider": "pictimo",
        "country": "Cote d'Ivoire",
        "default_vigilance_score": 38,
        "layer": "visual_streams",
        "layer_kind": "webcam_snapshot",
        "preview_url": DEFAULT_SOURCE_URL,
        "source_page": DEFAULT_SOURCE_PAGE,
        "refresh_seconds": 300,
        "analysis_mode": "snapshot_to_vlm_ready",
        "attribution": "Pictimo public webcam snapshot",
        "timelapse_policy": "latest_periodic_image_from_webcam_layer",
    }


def _capture_bytes(source: WorkspaceVisualSource) -> tuple[bytes, str, dict[str, Any]]:
    if source.adapter == "demo_static" or source.source_url.startswith("demo://"):
        return _demo_snapshot(source), "image/svg+xml", {"adapter": source.adapter, "width": 960, "height": 540, "demo_safe": True}
    if source.adapter == "http_image" and (source.meta_data or {}).get("provider") == "windy":
        try:
            return _capture_windy_webcam(source)
        except Exception:
            if (source.meta_data or {}).get("demo_fallback"):
                return _demo_snapshot(source), "image/svg+xml", {"adapter": source.adapter, "width": 960, "height": 540, "demo_safe": True, "fallback": "windy_unavailable"}
            raise
    if source.adapter == "browser_screenshot":
        if not settings.visual_capture_browser_enabled:
            raise RuntimeError("browser_screenshot_disabled")
        if not source.source_url.startswith(("http://", "https://")):
            raise RuntimeError("browser_screenshot_requires_http_url")
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("browser_screenshot_adapter_missing_playwright") from exc
        timeout_ms = int(settings.visual_capture_http_timeout_seconds * 1000)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=1)
                page.goto(source.source_url, wait_until="networkidle", timeout=timeout_ms)
                content = page.screenshot(type="png", full_page=False)
            finally:
                browser.close()
        return content, "image/png", {"adapter": source.adapter, "source_url": source.source_url, "width": 1280, "height": 720}
    if source.adapter != "http_image":
        raise RuntimeError(f"unsupported_visual_adapter:{source.adapter}")
    if not source.source_url.startswith(("http://", "https://")):
        raise RuntimeError("http_image_requires_http_url")
    try:
        content, mime_type = _fetch_http_image(source.source_url)
    except Exception:
        if (source.meta_data or {}).get("demo_fallback"):
            return _demo_snapshot(source), "image/svg+xml", {"adapter": source.adapter, "width": 960, "height": 540, "demo_safe": True, "fallback": "http_image_unavailable"}
        raise
    return content, mime_type, {"adapter": source.adapter, "source_url": source.source_url, "provider": (source.meta_data or {}).get("provider")}


def _fetch_http_image(url: str) -> tuple[bytes, str]:
    with httpx.Client(timeout=settings.visual_capture_http_timeout_seconds, follow_redirects=True) as client:
        response = client.get(url, headers={"User-Agent": "AgentiumVisualIntelligence/1.0"})
        response.raise_for_status()
    mime_type = response.headers.get("content-type", "application/octet-stream").split(";")[0].strip()
    if not mime_type.startswith("image/"):
        raise RuntimeError(f"visual_source_not_image:{mime_type}")
    return response.content, mime_type


def _capture_windy_webcam(source: WorkspaceVisualSource) -> tuple[bytes, str, dict[str, Any]]:
    metadata = source.meta_data or {}
    webcam_id = metadata.get("webcam_id")
    if not webcam_id:
        raise RuntimeError("windy_webcam_id_required")
    if not settings.visual_capture_windy_api_key:
        raise RuntimeError("windy_api_key_missing")
    url = f"https://api.windy.com/webcams/api/v3/webcams/{webcam_id}?include=images,urls"
    with httpx.Client(timeout=settings.visual_capture_http_timeout_seconds, follow_redirects=True) as client:
        response = client.get(url, headers={"x-windy-api-key": settings.visual_capture_windy_api_key})
        response.raise_for_status()
    payload = response.json()
    webcam = (payload.get("webcams") or [payload])[0]
    images = webcam.get("images") or webcam.get("image") or {}
    image_url = (
        ((images.get("current") or {}).get("preview"))
        or ((images.get("current") or {}).get("thumbnail"))
        or metadata.get("preview_url")
    )
    if not image_url:
        raise RuntimeError("windy_preview_unavailable")
    content, mime_type = _fetch_http_image(image_url)
    return content, mime_type, {
        "adapter": source.adapter,
        "provider": "windy",
        "webcam_id": webcam_id,
        "source_url": image_url,
        "player_url": (webcam.get("urls") or {}).get("player") or metadata.get("player_url"),
        "last_updated": webcam.get("lastUpdatedOn"),
    }


def _analyze_capture(
    db: DBSession,
    workspace: Workspace,
    source: WorkspaceVisualSource,
    capture: WorkspaceVisualCapture,
    capture_meta: dict[str, Any],
) -> WorkspaceVisualObservation:
    default_score = int((source.meta_data or {}).get("default_vigilance_score") or 35)
    source_name = source.name or "Source visuelle"
    region = source.region or "zone suivie"
    summary = (
        f"{source_name}: capture exploitable sur {region}. "
        "Activite visuelle compatible avec une surveillance institutionnelle nominale ; "
        "aucun signal critique automatise n'est retenu sans confirmation operateur."
    )
    tags = [
        "flux-visuel",
        "observation",
        "cote-ivoire",
        "validation-humaine",
    ]
    observation = WorkspaceVisualObservation(
        id=str(uuid4()),
        workspace_id=workspace.id,
        source_id=source.id,
        capture_id=capture.id,
        summary=summary,
        tags=tags,
        confidence=0.68 if capture_meta.get("demo_safe") else 0.62,
        vigilance_score=default_score,
        level_label=_level_label(default_score),
        source_refs=[f"visual:{source.id}", f"capture:{capture.id}"],
        provider="rule_based",
        model=None,
        meta_data={
            "adapter": source.adapter,
            "source_region": region,
            "no_biometrics": True,
            "advisory_only": True,
        },
        created_at=datetime.utcnow(),
    )
    db.add(observation)
    db.flush()
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="visual.observation.created",
        actor="system",
        details={"source_id": source.id, "capture_id": capture.id, "observation_id": observation.id},
    )
    return observation


def _demo_snapshot(source: WorkspaceVisualSource) -> bytes:
    region = (source.region or "Abidjan").replace("&", "&amp;")
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 540">
  <defs>
    <linearGradient id="sky" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0" stop-color="#061018"/>
      <stop offset="1" stop-color="#142334"/>
    </linearGradient>
    <linearGradient id="road" x1="0" x2="1">
      <stop offset="0" stop-color="#10202d"/>
      <stop offset="1" stop-color="#070c12"/>
    </linearGradient>
  </defs>
  <rect width="960" height="540" fill="url(#sky)"/>
  <circle cx="770" cy="108" r="46" fill="#8ed8ff" opacity="0.18"/>
  <path d="M0 360 C160 310 250 375 382 338 C532 295 615 362 960 302 L960 540 L0 540Z" fill="url(#road)"/>
  <g fill="#162c3a">
    <rect x="72" y="198" width="54" height="155"/>
    <rect x="148" y="150" width="82" height="207"/>
    <rect x="270" y="226" width="60" height="126"/>
    <rect x="690" y="185" width="88" height="165"/>
    <rect x="808" y="245" width="48" height="106"/>
  </g>
  <g fill="#7dd3fc" opacity="0.58">
    <circle cx="175" cy="314" r="5"/>
    <circle cx="610" cy="340" r="4"/>
    <circle cx="720" cy="296" r="5"/>
    <circle cx="835" cy="344" r="4"/>
  </g>
  <rect x="28" y="28" width="396" height="82" rx="10" fill="#071019" opacity="0.82" stroke="#244257"/>
  <text x="50" y="61" font-family="Inter,Arial" font-size="18" fill="#bdeaff" font-weight="700">{region}</text>
  <text x="50" y="88" font-family="Inter,Arial" font-size="13" fill="#7b8da3">{now} · snapshot demo-safe · no biometrics</text>
</svg>"""
    return svg.encode("utf-8")


def _observation_markdown(observation: WorkspaceVisualObservation) -> str:
    tags = ", ".join(observation.tags or [])
    return (
        f"# Observation visuelle {observation.id}\n\n"
        f"- Date: {observation.created_at.isoformat()}\n"
        f"- Niveau: {observation.level_label} ({observation.vigilance_score}/100)\n"
        f"- Confiance: {round(observation.confidence * 100)}%\n"
        f"- Tags: {tags}\n"
        f"- Sources: {', '.join(observation.source_refs or [])}\n\n"
        f"{observation.summary}\n\n"
        "Politique: observation indicative, sans reconnaissance faciale ni identification individuelle. "
        "Toute action reste advisory-only et soumise a validation humaine.\n"
    )


def _extension_for_mime(mime_type: str) -> str:
    if mime_type == "image/svg+xml":
        return "svg"
    if mime_type in {"image/jpeg", "image/jpg"}:
        return "jpg"
    if mime_type == "image/png":
        return "png"
    if mime_type == "image/webp":
        return "webp"
    return "bin"


def _level_label(score: int) -> str:
    if score >= 75:
        return "critical"
    if score >= 55:
        return "elevated"
    if score >= 35:
        return "monitoring"
    return "stable"


def _posture_summary(label: str, score: int) -> str:
    if label == "critical":
        return f"Posture critique ({score}/100) : confirmation operateur immediate recommandee."
    if label == "elevated":
        return f"Posture elevee ({score}/100) : observation a rapprocher des signaux presse et agenda."
    if label == "monitoring":
        return f"Posture en surveillance ({score}/100) : source exploitable, aucun signal visuel critique automatise."
    return f"Posture stable ({score}/100) : veille visuelle nominale."


def _audit(db: DBSession, workspace: Workspace, user: Optional[User], event_type: str, details: dict[str, Any]) -> None:
    actor = "system"
    if user:
        actor = user.email or user.username or user.id
    emit_audit_event(db=db, workspace_id=workspace.id, event_type=event_type, actor=actor, details=details)
