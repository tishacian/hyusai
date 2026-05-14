"""Sync RSS intelligence outputs into canonical Knowledge/RAG collections."""
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
from app.models.intelligence import FeedArticle, FeedSource
from app.models.workspace import Workspace
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

logger = get_logger(__name__)

INTELLIGENCE_COLLECTION_SLUG = "sentinel-ci-open-intelligence"
INTELLIGENCE_COLLECTION_NAME = "SENTINEL-CI Open Intelligence"
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


def _local_sync_dir(workspace: Workspace) -> Path:
    return Path(tempfile.gettempdir()) / "agentium-intelligence-rag" / _safe_filename(workspace.slug)


def _document_id_for_path(path: Path) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, str(path)))


def _line(label: str, value: Any) -> str:
    if value in (None, "", [], {}):
        return f"- {label}: n/a"
    if isinstance(value, (list, tuple, set)):
        return f"- {label}: {', '.join(str(v) for v in value)}"
    return f"- {label}: {value}"


def _article_markdown(article: FeedArticle, source: FeedSource) -> str:
    analysis = article.analysis or {}
    raw_content = article.content or article.summary or ""
    summary = article.summary or "; ".join(analysis.get("key_findings") or []) or raw_content[:800]
    key_findings = analysis.get("key_findings") or []
    entities = analysis.get("entities") or []
    published_at = article.published_at.isoformat() if article.published_at else "n/a"
    fetched_at = article.fetched_at.isoformat() if article.fetched_at else "n/a"

    findings_md = "\n".join(f"- {item}" for item in key_findings) or "- n/a"
    return "\n".join(
        [
            f"# {article.title}",
            "",
            "## Source",
            _line("Feed", source.name),
            _line("Category", source.category),
            _line("URL", article.url),
            _line("Published at", published_at),
            _line("Fetched at", fetched_at),
            "",
            "## Analysis metadata",
            _line("Relevance score", round(float(article.relevance_score or 0.0), 3)),
            _line("Risk level", analysis.get("risk_level")),
            _line("Sentiment", analysis.get("sentiment")),
            _line("Safety flag", article.safety_flag),
            _line("Entities", entities),
            "",
            "## Analyzed summary",
            summary or "n/a",
            "",
            "## Key findings",
            findings_md,
            "",
            "## Raw scraped content",
            raw_content or "n/a",
            "",
        ]
    )


def _synthesis_markdown(dashboard_payload: dict[str, Any] | None) -> str:
    dashboard_payload = dashboard_payload or {}
    synthesis = dashboard_payload.get("synthesis") or {}
    kpis = dashboard_payload.get("kpis") or {}
    risk = dashboard_payload.get("risk") or {}
    sentiment = dashboard_payload.get("sentiment") or {}
    articles = dashboard_payload.get("articles") or []

    findings = "\n".join(f"- {item}" for item in synthesis.get("key_findings") or []) or "- n/a"
    actions = "\n".join(f"- {item}" for item in synthesis.get("recommended_actions") or []) or "- n/a"
    sources = "\n".join(
        f"- {item.get('title', 'Untitled')} ({item.get('risk_level', 'n/a')}) - {item.get('url', 'n/a')}"
        for item in synthesis.get("source_articles") or []
    ) or "- n/a"
    live_articles = "\n".join(
        f"- {item.get('title', 'Untitled')} | risk={item.get('risk_level', 'n/a')} | score={item.get('relevance_score', 'n/a')}"
        for item in articles[:30]
    ) or "- n/a"

    return "\n".join(
        [
            "# Synthese consolidee News Lab",
            "",
            "## Executive summary",
            synthesis.get("summary") or "No consolidated synthesis available yet.",
            "",
            "## KPIs",
            _line("Active feeds", kpis.get("active_feeds")),
            _line("Articles collected", kpis.get("total_articles")),
            _line("Articles analyzed", kpis.get("analyzed")),
            _line("High risk signals", kpis.get("high_risk")),
            "",
            "## Risk distribution",
            _line("Risk", _jsonable(risk)),
            "",
            "## Sentiment distribution",
            _line("Sentiment", _jsonable(sentiment)),
            "",
            "## Key findings",
            findings,
            "",
            "## Recommended actions",
            actions,
            "",
            "## Source articles",
            sources,
            "",
            "## Recent analyzed articles",
            live_articles,
            "",
        ]
    )


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
                "intelligence.knowledge_sync.delete_existing_chunks_failed",
                document_id=document_id,
                error=str(exc),
            )
    return deleted


async def sync_intelligence_to_knowledge(
    db: DBSession,
    workspace: Workspace,
    *,
    dashboard_payload: dict[str, Any] | None = None,
    max_articles: int = 250,
) -> dict[str, Any]:
    """Make News Lab analysis and raw RSS rows queryable through canonical RAG."""
    collection = create_or_get_collection(
        db,
        workspace=workspace,
        slug=INTELLIGENCE_COLLECTION_SLUG,
        name=INTELLIGENCE_COLLECTION_NAME,
        description=(
            "Open intelligence RSS sources, raw scraped article content, and consolidated "
            "News Lab analysis for AYA interactions."
        ),
    )
    db.flush()

    rows = (
        db.query(FeedArticle, FeedSource)
        .join(FeedSource, FeedSource.id == FeedArticle.source_id)
        .filter(FeedSource.workspace_id == workspace.id)
        .order_by(FeedArticle.fetched_at.desc())
        .limit(max(1, max_articles))
        .all()
    )

    docs: dict[str, str] = {
        "news-lab-consolidated-latest.md": _synthesis_markdown(dashboard_payload),
    }
    for article, source in rows:
        docs[f"rss-article-{_safe_filename(article.id)}.md"] = _article_markdown(article, source)

    local_dir = _local_sync_dir(workspace)
    local_dir.mkdir(parents=True, exist_ok=True)
    store = get_object_store()
    local_paths: list[Path] = []
    for filename, content in docs.items():
        store.write_text(original_key(collection, filename), content)
        store.write_text(ingested_key(collection, filename), content)
        path = local_dir / filename
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

    collection.name = INTELLIGENCE_COLLECTION_NAME
    collection.description = (
        "Open intelligence RSS sources, raw scraped article content, and consolidated "
        "News Lab analysis for AYA interactions."
    )
    collection.embedding_model = settings.embedding_model
    collection.chunking_method = app_settings.get("ragChunkingMethod", "recursive_character")
    collection.chunking_params = {
        "chunk_size": app_settings.get("ragChunkSize", 1000),
        "chunk_overlap": app_settings.get("ragChunkOverlap", 200),
        "sync_source": "intelligence.news_lab",
    }
    update_collection_status(
        db,
        collection.id,
        status="ready",
        last_error=None,
        document_names=list(docs.keys()),
        document_count=document_count,
        chunk_count=chunk_count,
    )
    db.commit()

    result = {
        "status": "ready",
        "collection_slug": collection.slug,
        "collection_id": collection.id,
        "vector_db_type": vector_db_type,
        "documents_written": len(docs),
        "articles_synced": len(rows),
        "deleted_chunks": deleted_chunks,
        "document_count": document_count,
        "chunk_count": chunk_count,
        "ingest": _jsonable(ingest_result),
        "bm25": _jsonable(bm25),
    }
    logger.info("intelligence.knowledge_sync.completed", **result)
    return result
