"""Index SENTINEL-CI mission-room fixtures into canonical RAG collections."""
from __future__ import annotations

import re
import tempfile
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.settings_manager import get_resolved_settings
from app.models.knowledge_collection import KnowledgeCollection
from app.models.workspace import Workspace
from app.models.workspace_visual import WorkspaceVisualObservation
from app.services import mission_room
from app.services.knowledge_collections import (
    create_or_get_collection,
    ingested_key,
    original_key,
    update_collection_status,
)
from app.services.object_store import get_object_store
from app.services.rag.bm25_store import rebuild_bm25_artifact
from app.services.rag.document_service import DocumentService
from app.services.rag.vector_store_config import resolve_vector_db_type
from app.services.visual_intelligence import VISUAL_COLLECTION_SLUG, _observation_markdown

logger = get_logger(__name__)


COLLECTION_DEFS: dict[str, dict[str, str]] = {
    "sentinel-ci-ministerial-briefs": {
        "name": "SENTINEL-CI Ministerial Briefs",
        "description": "Briefings, agenda syntheses and validated talking points for AYA.",
    },
    "sentinel-ci-projects": {
        "name": "SENTINEL-CI Strategic Projects",
        "description": "Strategic project records and decision-support risk explanations.",
    },
    "sentinel-ci-territorial-map": {
        "name": "SENTINEL-CI Territorial Map",
        "description": "Territorial zones, signals and non-military action recommendations.",
    },
    "sentinel-ci-territorial-intelligence": {
        "name": "SENTINEL-CI Territorial Intelligence",
        "description": "Fused territorial scores from news, projects, agenda, visual observations and action windows.",
    },
    VISUAL_COLLECTION_SLUG: {
        "name": "SENTINEL-CI Visual Intelligence",
        "description": "Visual snapshots and observations from authorized workspace streams.",
    },
    mission_room.SENTINEL_MARITIME_INTELLIGENCE_COLLECTION: {
        "name": "SENTINEL-CI Maritime Intelligence",
        "description": "Port, customs and Gulf of Guinea signals used by AYA for executive briefings.",
    },
    mission_room.SENTINEL_EVIDENCE_GRAPH_COLLECTION: {
        "name": "SENTINEL-CI Evidence Graph",
        "description": "Entities, rumors, sources, locations, projects and decisions connected for AYA.",
    },
}

HEAVY_PAYLOAD_KEYS = {
    "admin_boundaries",
    "basemap_options",
    "camera_presets",
    "cities",
    "default_map_state",
    "geojson_sources",
    "layer_catalog",
    "layers",
    "renderer_config",
    "visual_effects",
}
MAX_INLINE_VALUE_CHARS = 1600
SYNC_INGEST_MAX_CONCURRENCY = 4


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return str(value)


def _safe_filename(value: str, fallback: str = "document") -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", (value or "").strip().lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-_.")
    return (slug or fallback)[:120]


def _local_sync_dir(workspace: Workspace, collection_slug: str) -> Path:
    return (
        Path(tempfile.gettempdir())
        / "agentium-mission-room-rag"
        / _safe_filename(workspace.slug)
        / _safe_filename(collection_slug)
    )


def _document_id_for_path(path: Path) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, str(path)))


async def _delete_existing_chunks(doc_service: DocumentService, paths: list[Path]) -> int:
    deleted = 0
    vector_db = doc_service.vector_db
    if not hasattr(vector_db, "get_by_document_id") or not hasattr(vector_db, "delete"):
        return deleted
    for path in paths:
        document_id = _document_id_for_path(path)
        try:
            chunk_ids = await vector_db.get_by_document_id(document_id)
            if chunk_ids:
                await vector_db.delete(chunk_ids)
                deleted += len(chunk_ids)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "mission_room.knowledge_sync.delete_existing_chunks_failed",
                document_id=document_id,
                collection=doc_service.collection_name,
                error=str(exc),
            )
    return deleted


def _line(label: str, value: Any) -> str:
    if value in (None, "", [], {}):
        return f"- {label}: n/a"
    if isinstance(value, (list, tuple, set)):
        return f"- {label}: {_truncate_inline(', '.join(_display_value(v) for v in value))}"
    if isinstance(value, dict):
        return f"- {label}: {_display_value(value)}"
    return f"- {label}: {value}"


def _truncate_inline(value: str, *, limit: int = MAX_INLINE_VALUE_CHARS) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit].rstrip()}... [truncated]"


def _compact_payload(value: Any, *, depth: int = 0) -> Any:
    """Keep indexed fixture docs useful without embedding full map GeoJSON blobs."""
    if depth > 3:
        return "[nested payload omitted]"
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for key, item in value.items():
            if key in HEAVY_PAYLOAD_KEYS:
                if isinstance(item, dict):
                    compact[key] = {
                        "omitted": True,
                        "keys": list(item.keys())[:12],
                        "reason": "large cartographic payload; use map API for raw GeoJSON",
                    }
                elif isinstance(item, list):
                    compact[key] = {
                        "omitted": True,
                        "items": len(item),
                        "reason": "large cartographic payload; use map API for raw GeoJSON",
                    }
                else:
                    compact[key] = "[large cartographic payload omitted]"
                continue
            compact[str(key)] = _compact_payload(item, depth=depth + 1)
        return compact
    if isinstance(value, list):
        max_items = 20 if depth <= 1 else 8
        compact_items = [_compact_payload(item, depth=depth + 1) for item in value[:max_items]]
        if len(value) > max_items:
            compact_items.append(f"[{len(value) - max_items} additional items omitted]")
        return compact_items
    if isinstance(value, str):
        return _truncate_inline(value, limit=2400 if depth <= 1 else 900)
    return _jsonable(value)


def _display_value(value: Any) -> str:
    return _truncate_inline(str(_compact_payload(value)))


def _payload_markdown(title: str, payload: dict[str, Any]) -> str:
    lines = [f"# {title}", ""]
    for key, value in _compact_payload(payload).items():
        if key == "workspace":
            continue
        lines.append(f"## {key.replace('_', ' ').title()}")
        if isinstance(value, list):
            if not value:
                lines.append("- n/a")
            for item in value:
                if isinstance(item, dict):
                    label = item.get("title") or item.get("name") or item.get("label") or item.get("id") or "Item"
                    lines.append(f"### {label}")
                    for sub_key, sub_value in item.items():
                        lines.append(_line(sub_key, sub_value))
                else:
                    lines.append(f"- {item}")
        elif isinstance(value, dict):
            for sub_key, sub_value in value.items():
                lines.append(_line(sub_key, sub_value))
        else:
            lines.append(str(value))
        lines.append("")
    return "\n".join(lines)


def _source_markdown() -> str:
    lines = ["# SENTINEL-CI source index", ""]
    for source in mission_room.source_index():
        lines.append(f"## {source.get('title') or source.get('id')}")
        for key, value in source.items():
            lines.append(_line(key, value))
        lines.append("")
    return "\n".join(lines)


def _fixture_documents(db: DBSession, workspace: Workspace) -> dict[str, dict[str, str]]:
    briefing = mission_room.briefing_payload(workspace)
    projects = mission_room.projects_payload(workspace, db=db)
    map_payload = mission_room.map_payload(workspace, db=db)
    monitor = mission_room.monitor_payload(workspace, db=db)
    timeline = mission_room.timeline_payload(workspace, db=db)
    decisions = mission_room.decisions_payload(workspace, db=db)
    library = mission_room.library_payload(workspace)
    cockpit = mission_room.cockpit_payload(workspace, db=db)
    evidence_graph = mission_room.evidence_graph_payload(workspace, db=db)
    news = mission_room.news_payload(workspace, db=db)
    map_system = map_payload.get("map_system") or {}
    maritime_snapshot = map_system.get("maritime_snapshot") or {}
    maritime_intelligence = news.get("maritime_intelligence") or {}

    project_docs = {
        f"project-{_safe_filename(project.get('id') or project.get('name'))}.md": _payload_markdown(
            f"Projet strategic - {project.get('name')}",
            project,
        )
        for project in projects.get("projects", [])
    }
    zone_docs = {
        f"zone-{_safe_filename(zone.get('id') or zone.get('name'))}.md": _payload_markdown(
            f"Zone territoriale - {zone.get('name')}",
            zone,
        )
        for zone in map_payload.get("zones", [])
    }

    return {
        "sentinel-ci-ministerial-briefs": {
            "briefing-quotidien.md": _payload_markdown("Briefing quotidien vice-presidence", briefing),
            "agenda-et-echeances.md": _payload_markdown("Agenda ministeriel et echeances", timeline),
            "decisions-cabinet.md": _payload_markdown("Decisions et actions cabinet", decisions),
            "sources-qualifiees.md": _source_markdown(),
        },
        "sentinel-ci-projects": {
            "synthese-projets.md": _payload_markdown("Synthese des projets strategiques", projects),
            **project_docs,
        },
        "sentinel-ci-territorial-map": {
            "carte-strategique.md": _payload_markdown("Carte strategique executive", map_payload),
            **zone_docs,
        },
        "sentinel-ci-territorial-intelligence": {
            "cockpit-executif.md": _payload_markdown("Cockpit executif SENTINEL-CI", cockpit),
            "situation-monitor.md": _payload_markdown("Situation Monitor", monitor),
            "bibliotheque-sources.md": _payload_markdown("Bibliotheque institutionnelle", library),
        },
        mission_room.SENTINEL_MARITIME_INTELLIGENCE_COLLECTION: {
            "maritime-et-douanes.md": _payload_markdown(
                "Maritime et douanes - lecture executive",
                {
                    "maritime_intelligence": maritime_intelligence,
                    "map_snapshot": maritime_snapshot,
                    "source_health": map_system.get("source_health") or [],
                    "layer_registry": [
                        layer
                        for layer in map_system.get("layer_registry") or []
                        if layer.get("key") == "maritime-traffic"
                    ],
                },
            ),
            "port-abidjan.md": _payload_markdown(
                "Port d'Abidjan - vigilance cabinet",
                {
                    "port": "Abidjan",
                    "active_evidence": maritime_intelligence.get("active_evidence") or {},
                    "latest_observation": maritime_intelligence.get("latest_observation") or {},
                    "density_zones": maritime_snapshot.get("density_zones") or [],
                    "disruptions": maritime_snapshot.get("disruptions") or [],
                },
            ),
        },
        mission_room.SENTINEL_EVIDENCE_GRAPH_COLLECTION: {
            "evidence-graph.md": _payload_markdown("Evidence Graph AYA", evidence_graph),
            "evidence-graph-summary.md": _payload_markdown(
                "Graphe de preuves - synthese",
                {
                    "summary": evidence_graph.get("summary") or {},
                    "clusters": evidence_graph.get("clusters") or [],
                    "source_freshness": evidence_graph.get("source_freshness") or {},
                    "suggested_questions": evidence_graph.get("suggested_questions") or [],
                },
            ),
        },
    }


async def sync_markdown_documents_to_collection(
    db: DBSession,
    workspace: Workspace,
    *,
    collection_slug: str,
    documents: dict[str, str],
) -> dict[str, Any]:
    definition = COLLECTION_DEFS.get(collection_slug) or {
        "name": collection_slug,
        "description": "Workspace knowledge collection.",
    }
    collection = create_or_get_collection(
        db,
        workspace=workspace,
        slug=collection_slug,
        name=definition["name"],
        description=definition["description"],
    )
    db.flush()

    local_dir = _local_sync_dir(workspace, collection.slug)
    local_dir.mkdir(parents=True, exist_ok=True)
    store = get_object_store()
    local_paths: list[Path] = []
    for filename, content in documents.items():
        safe_name = _safe_filename(filename, fallback="document.md")
        if not safe_name.endswith(".md"):
            safe_name = f"{safe_name}.md"
        store.write_text(original_key(collection, safe_name), content)
        store.write_text(ingested_key(collection, safe_name), content)
        path = local_dir / safe_name
        path.write_text(content, encoding="utf-8")
        local_paths.append(path)

    app_settings = get_resolved_settings(workspace_id=workspace.id)
    vector_db_type = resolve_vector_db_type(app_settings)
    doc_service = DocumentService(
        collection_name=collection.slug,
        vector_db_type=vector_db_type,
        workspace_slug=workspace.slug,
    )
    deleted_chunks = await _delete_existing_chunks(doc_service, local_paths)
    ingest_result = await doc_service.ingest_documents_batch(
        [str(path) for path in local_paths],
        max_concurrency=SYNC_INGEST_MAX_CONCURRENCY,
    )
    document_count = len(await doc_service.list_documents())
    chunk_count = await doc_service.get_document_count()
    bm25 = await rebuild_bm25_artifact(collection=collection, vector_db=doc_service.vector_db, store=store)

    collection.name = definition["name"]
    collection.description = definition["description"]
    collection.embedding_model = settings.embedding_model
    collection.chunking_method = app_settings.get("ragChunkingMethod", "recursive_character")
    collection.chunking_params = {
        "chunk_size": app_settings.get("ragChunkSize", 1000),
        "chunk_overlap": app_settings.get("ragChunkOverlap", 200),
        "sync_source": "mission_room.fixtures",
    }
    update_collection_status(
        db,
        collection.id,
        status="ready",
        last_error=None,
        document_names=[path.name for path in local_paths],
        document_count=document_count,
        chunk_count=chunk_count,
    )
    db.commit()
    return {
        "status": "ready",
        "collection_slug": collection.slug,
        "collection_id": collection.id,
        "vector_db_type": vector_db_type,
        "documents_written": len(local_paths),
        "deleted_chunks": deleted_chunks,
        "document_count": document_count,
        "chunk_count": chunk_count,
        "ingest": _jsonable(ingest_result),
        "bm25": _jsonable(bm25),
    }


async def sync_mission_room_fixtures_to_knowledge(db: DBSession, workspace: Workspace) -> dict[str, Any]:
    """Index the structured SENTINEL-CI demo corpus used by AYA."""
    docs_by_collection = _fixture_documents(db, workspace)
    results: dict[str, Any] = {}
    for collection_slug, documents in docs_by_collection.items():
        results[collection_slug] = await sync_markdown_documents_to_collection(
            db,
            workspace,
            collection_slug=collection_slug,
            documents=documents,
        )
    logger.info(
        "mission_room.knowledge_sync.completed",
        workspace_slug=workspace.slug,
        collections=list(results),
    )
    return {"status": "ready", "collections": results}


async def sync_visual_observations_to_knowledge(
    db: DBSession,
    workspace: Workspace,
    *,
    limit: int = 50,
) -> dict[str, Any]:
    observations = (
        db.query(WorkspaceVisualObservation)
        .filter(WorkspaceVisualObservation.workspace_id == workspace.id)
        .order_by(WorkspaceVisualObservation.created_at.desc())
        .limit(max(1, min(limit, 200)))
        .all()
    )
    docs = {
        f"visual-observation-{observation.id}.md": _observation_markdown(observation)
        for observation in observations
    }
    if not docs:
        docs = {
            "visual-observations-empty.md": (
                "# Observations visuelles\n\n"
                "Aucune observation visuelle indexable n'est disponible pour ce workspace.\n"
            )
        }
    return await sync_markdown_documents_to_collection(
        db,
        workspace,
        collection_slug=VISUAL_COLLECTION_SLUG,
        documents=docs,
    )
