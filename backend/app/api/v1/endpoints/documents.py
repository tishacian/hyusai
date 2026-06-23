"""Document management endpoints"""

import asyncio
import mimetypes
import os
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any, Literal, Optional
from urllib.parse import quote

import numpy as np

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.core.iam.roles import is_admin_template
from app.core.logging import get_logger
from app.core.settings_manager import get_resolved_settings
from app.db.base import get_db
from app.models.knowledge_collection import KnowledgeCollection, WorkerJob
from app.models.knowledge_document_fact import KnowledgeDocumentFact
from app.models.knowledge_table_fact import KnowledgeTableFact
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.knowledge_collections import (
    collection_inventory,
    collection_source_rows,
    create_or_get_collection,
    create_collection as create_knowledge_collection,
    create_worker_job,
    get_collection_or_404,
    normalize_source_name,
    original_key,
    resolve_original_key,
    serialize_collection,
    serialize_job,
    update_collection_status,
    upsert_collection_source,
)
from app.services.object_store import get_object_store
from app.services.rag.document_service import DocumentService
from app.services.rag.vector_store_config import resolve_vector_db_type
from app.services.secure_deposit import build_file_preview, preview_needs_file_bytes
from app.services.worker_dispatch import dispatch_worker_job
from app.services.worker_offline_retrieval_artifacts import SUPPORTED_KINDS as SUPPORTED_RETRIEVAL_ARTIFACT_KINDS
from app.services.workspace_features import chat_document_upload_enabled

logger = get_logger(__name__)
router = APIRouter()
_GRAPH_CACHE_TTL_SECONDS = 120
_GRAPH_CACHE: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
_GRAPH_DENSE_SAMPLE_CAP = 500

UPLOADS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))),
    "uploads",
)
os.makedirs(UPLOADS_DIR, exist_ok=True)


def _require_workspace_admin(db: DBSession, user: User, workspace: Workspace) -> None:
    membership = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == workspace.id)
        .first()
    )
    if not membership or not is_admin_template(getattr(membership, "role_template", None), membership.role):
        raise HTTPException(status_code=403, detail={"code": "WORKSPACE_PERMISSION_DENIED"})


class DocumentSearchRequest(BaseModel):
    """Document search request"""

    query: str
    top_k: int = 10
    filters: Optional[dict] = None
    collection_name: str = "documents"
    use_hybrid: bool = True
    latency_profile: Literal["fast", "balanced", "deep"] = "fast"


class DocumentSearchResponse(BaseModel):
    """Document search response"""

    results: list[dict]
    total: int
    retrieval_plan: Optional[dict] = None
    retrieval_scope: Optional[dict] = None
    dense_policy: Optional[str] = None
    fallback_reason: Optional[str] = None
    latency_budget: Optional[dict] = None
    total_available: Optional[int] = None
    total_is_dense: bool = False


class CollectionCreateRequest(BaseModel):
    name: str
    description: str = ""
    slug: str | None = None


class CollectionPatchRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class RetrievalArtifactJobRequest(BaseModel):
    kind: Literal["summary_index_rebuild", "sparse_index_rebuild", "qdrant_sparse_reindex"]
    dry_run: bool = False


def _resolve_document_vector_db_type(
    workspace: Workspace,
    requested_type: Optional[str] = None,
) -> str:
    app_settings = get_resolved_settings(workspace_id=workspace.id)
    return (requested_type or "").strip().lower() or resolve_vector_db_type(app_settings)


def _attach_collection_job_diagnostics(payload: dict, jobs: list[WorkerJob]) -> dict:
    serialized_jobs = [serialize_job(job) for job in jobs]
    payload["jobs"] = serialized_jobs
    payload["latest_job"] = serialized_jobs[0] if serialized_jobs else None
    latest_bm25 = next((job for job in jobs if job.kind == "bm25_rebuild"), None)
    if latest_bm25:
        bm25_payload = payload.setdefault("bm25", {})
        bm25_payload["job"] = serialize_job(latest_bm25)
        if latest_bm25.status in ("queued", "running"):
            bm25_payload["status"] = latest_bm25.status
        elif latest_bm25.status == "failed":
            bm25_payload["status"] = "error"
        elif latest_bm25.status == "completed":
            result_status = ((latest_bm25.result or {}).get("bm25") or {}).get("status")
            bm25_payload["status"] = result_status or bm25_payload.get("status") or "ready"
    payload["job_summary"] = {
        "total": len(jobs),
        "running": sum(1 for job in jobs if job.status == "running"),
        "queued": sum(1 for job in jobs if job.status == "queued"),
        "failed": sum(1 for job in jobs if job.status == "failed"),
    }
    return payload


def _source_row_to_document(row: Any) -> dict[str, Any]:
    metadata = dict(row.source_metadata or {})
    document_id = metadata.get("document_id") or row.normalized_name or row.filename or row.id
    return {
        "document_id": str(document_id),
        "filename": row.filename,
        "chunk_count": int(row.chunk_count or 0),
        "chunks_count": int(row.chunk_count or 0),
        "document_type": row.source_kind,
        "mime_type": row.mime_type,
        "uploaded_at": row.indexed_at.isoformat() if row.indexed_at else None,
        "size": row.size_bytes,
        "status": row.status,
        "source_id": row.id,
    }


def _source_row_document_id(row: Any) -> str:
    metadata = dict(getattr(row, "source_metadata", None) or {})
    document_id = metadata.get("document_id") or row.normalized_name or row.filename or row.id
    return str(document_id)


def _ledger_document_for_id(
    db: DBSession,
    workspace: Workspace,
    collection_name: str,
    document_id: str,
) -> Optional[dict[str, Any]]:
    try:
        collection = get_collection_or_404(
            db,
            workspace_id=workspace.id,
            collection_ref=collection_name,
        )
    except HTTPException:
        return None
    target = str(document_id)
    for row in collection_source_rows(db, collection=collection):
        if _source_row_document_id(row) == target:
            return _source_row_to_document(row)
    return None


async def _queue_collection_ingest(
    *,
    db: DBSession,
    workspace: Workspace,
    collection: KnowledgeCollection,
    files: list[UploadFile],
) -> dict:
    if not files:
        raise HTTPException(status_code=422, detail="At least one file is required")

    store = get_object_store()
    existing = list(collection.document_names or [])
    uploaded_names: list[str] = []
    source_updates: dict[str, dict[str, Any]] = {}
    for file in files:
        safe_name = (file.filename or "upload").replace("/", "_").replace("\\", "_")
        content = await file.read()
        store.write_bytes(original_key(collection, safe_name), content)
        source_updates[normalize_source_name(safe_name)] = {
            "filename": safe_name,
            "mime_type": file.content_type,
            "size_bytes": len(content),
        }
        if safe_name not in existing:
            existing.append(safe_name)
        uploaded_names.append(safe_name)

    for update in source_updates.values():
        upsert_collection_source(
            db,
            collection=collection,
            filename=update["filename"],
            status="queued",
            mime_type=update["mime_type"],
            origin="upload",
            size_bytes=update["size_bytes"],
        )

    update_collection_status(
        db,
        collection.id,
        status="queued",
        document_names=existing,
        document_count=len(existing),
    )
    job = create_worker_job(
        db,
        workspace_id=workspace.id,
        collection_id=collection.id,
        kind="document_ingest_index",
    )
    db.commit()
    db.refresh(job)
    db.refresh(collection)

    dispatch_worker_job(db, job)
    db.commit()

    db.refresh(job)
    db.refresh(collection)
    return {
        "collection_id": collection.id,
        "collection_slug": collection.slug,
        "job_id": job.id,
        "celery_task_id": job.celery_task_id,
        "status": job.status,
        "collection_status": collection.status,
        "files": uploaded_names,
    }


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    collection_name: str = Form("documents"),
    vector_db_type: Optional[str] = Form(None),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Upload and index a document"""
    try:
        if settings.document_ingest_async_enabled:
            collection = create_or_get_collection(
                db,
                workspace=workspace,
                name=collection_name,
                created_by_user_id=user.id,
                slug=collection_name,
            )
            queued = await _queue_collection_ingest(
                db=db,
                workspace=workspace,
                collection=collection,
                files=[file],
            )
            return {
                "status": queued["status"],
                "collection_id": queued["collection_id"],
                "collection_name": queued["collection_slug"],
                "job_id": queued["job_id"],
                "filename": file.filename,
                "chunks_processed": 0,
            }

        db_type = _resolve_document_vector_db_type(workspace, vector_db_type)

        safe_name = file.filename.replace("/", "_").replace("\\", "_")
        tmp_dir = tempfile.mkdtemp()
        tmp_path = os.path.join(tmp_dir, safe_name)
        try:
            with open(tmp_path, "wb") as f:
                shutil.copyfileobj(file.file, f)

            doc_service = DocumentService(
                collection_name=collection_name,
                vector_db_type=db_type,
                workspace_slug=workspace.slug,
            )
            result = await doc_service.ingest_document(tmp_path)
            doc_id = result.get("document_id", "")

            # Persist original file for preview
            if doc_id:
                persist_path = os.path.join(UPLOADS_DIR, f"{doc_id}_{safe_name}")
                shutil.copy2(tmp_path, persist_path)

            return {
                "status": "success",
                "document_id": doc_id,
                "chunks_processed": result.get("chunks_processed", 0),
                "filename": file.filename,
            }
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    except Exception as e:
        logger.error(f"Error uploading document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload-batch")
async def upload_documents_batch(
    files: list[UploadFile] = File(...),
    collection_name: str = Form("documents"),
    vector_db_type: Optional[str] = Form(None),
    source: Optional[str] = Form(None),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Upload and index multiple documents"""
    if source == "chat_drop_and_ask" and not chat_document_upload_enabled(workspace):
        raise HTTPException(
            status_code=403,
            detail="Document upload in chat is disabled for this workspace",
        )
    if settings.document_ingest_async_enabled:
        collection = create_or_get_collection(
            db,
            workspace=workspace,
            name=collection_name,
            created_by_user_id=user.id,
            slug=collection_name,
        )
        queued = await _queue_collection_ingest(
            db=db,
            workspace=workspace,
            collection=collection,
            files=files,
        )
        return {
            "status": queued["status"],
            "collection_id": queued["collection_id"],
            "collection_name": queued["collection_slug"],
            "job_id": queued["job_id"],
            "total": len(files),
            "successful": 0,
            "failed": 0,
            "documents": [
                {
                    "document_id": None,
                    "filename": filename,
                    "status": "queued",
                    "chunks_processed": 0,
                }
                for filename in queued["files"]
            ],
        }

    db_type = _resolve_document_vector_db_type(workspace, vector_db_type)

    # We write each upload into a fresh tmpdir using its *original* filename so
    # downstream parsers surface `slides_admin_cockpit.pdf` in chunk metadata
    # rather than `tmp73klgow9.pdf`. The drop-and-ask flow relies on this for
    # filename-based questions ("what is slides_admin_cockpit.pdf about?").
    temp_dirs: list[str] = []
    try:
        file_paths = []
        for file in files:
            safe_name = (file.filename or "upload").replace("/", "_").replace("\\", "_")
            tmp_dir = tempfile.mkdtemp()
            temp_dirs.append(tmp_dir)
            tmp_path = os.path.join(tmp_dir, safe_name)
            with open(tmp_path, "wb") as out:
                shutil.copyfileobj(file.file, out)
            file_paths.append(tmp_path)

        doc_service = DocumentService(
            collection_name=collection_name,
            vector_db_type=db_type,
            workspace_slug=workspace.slug,
        )
        result = await doc_service.ingest_documents_batch(file_paths)

        # Surface per-document ids + filenames so the UI can request
        # docmeta for each (Doc-facts panel) without re-uploading or
        # re-listing the whole collection.
        documents = [
            {
                "document_id": r.get("document_id"),
                "filename": r.get("filename"),
                "status": r.get("status"),
                "chunks_processed": r.get("chunks_processed"),
            }
            for r in (result.get("results") or [])
        ]

        return {
            "status": "success",
            "total": result["total"],
            "successful": result["successful"],
            "failed": result["failed"],
            "documents": documents,
        }

    except Exception as e:
        logger.error(f"Error uploading documents batch: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        for tmp_dir in temp_dirs:
            shutil.rmtree(tmp_dir, ignore_errors=True)


@router.post("/search")
async def search_documents(
    request: DocumentSearchRequest,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Search documents with the same dense-corpus guardrails as chat retrieval."""
    try:
        db_type = _resolve_document_vector_db_type(workspace)
        raw_filters = dict(request.filters or {})
        system_scope = raw_filters.get("collection_slug") or raw_filters.get("collection")
        collection_name = str(system_scope or request.collection_name or "documents").strip() or "documents"
        payload_filters = {
            key: value
            for key, value in raw_filters.items()
            if key not in {"collection", "collection_slug"}
        }
        requested_top_k = max(1, int(request.top_k or 10))
        retrieval_request = {
            "query": request.query,
            "workspace_id": workspace.id,
            "workspace_slug": workspace.slug,
            "latency_profile": request.latency_profile,
            "rag_pipeline_mode": "hybrid" if request.use_hybrid else "naive",
            "top_k": requested_top_k,
            "candidate_pool_k": requested_top_k,
            "retrieval_filters": {"collection_slug": collection_name, **payload_filters},
        }
        from app.services.rag.context import get_retrieval_profile
        from app.services.rag.corpus_planner import plan_corpus

        profile = get_retrieval_profile(retrieval_request)
        planner_request = dict(retrieval_request)
        planner_request["retrieval_filters"] = dict(profile.get("retrieval_filters") or {})
        plan = plan_corpus(
            db=db,
            profile=profile,
            query=str(profile.get("query") or request.query),
            request=planner_request,
        )

        doc_service = DocumentService(
            collection_name=str(profile.get("collection") or collection_name),
            vector_db_type=db_type,
            use_hybrid=bool(request.use_hybrid and plan.allow_legacy_hybrid and (plan.use_hybrid is not False)),
            workspace_slug=workspace.slug,
        )
        vector_count: int | None = None
        try:
            vector_count = int(await doc_service.get_document_count())
        except Exception as exc:  # noqa: BLE001 - search can still run bounded.
            logger.warning("Could not compute document search vector count", error=str(exc), collection=collection_name)

        dense_from_vectors = bool(
            vector_count is not None
            and vector_count > int(getattr(settings, "rag_dense_chunk_threshold", 100_000) or 100_000)
        )
        effective_filters = dict(plan.filters or {})
        dense_unscoped = bool((plan.dense or dense_from_vectors) and not effective_filters)
        if plan.intent == "catalogue" or dense_unscoped:
            fallback_reason = (
                "catalogue_query_inventory_preferred"
                if plan.intent == "catalogue"
                else plan.fallback_reason or "dense_unscoped_search_skipped"
            )
            return DocumentSearchResponse(
                results=[],
                total=0,
                retrieval_plan=plan.retrieval_plan,
                retrieval_scope=plan.retrieval_scope,
                dense_policy=plan.dense_policy if plan.dense else "fast_scoped_dense_auto",
                fallback_reason=fallback_reason,
                latency_budget={
                    "profile": plan.latency_profile,
                    "deadline_seconds": plan.deadline_seconds,
                    "top_k": plan.top_k,
                    "candidate_pool_k": plan.candidate_pool_k,
                },
                total_available=vector_count,
                total_is_dense=bool(plan.dense or dense_from_vectors),
            )

        effective_top_k = max(1, min(requested_top_k, plan.candidate_pool_k))
        effective_use_hybrid = bool(
            request.use_hybrid
            and plan.use_hybrid is not False
            and plan.allow_legacy_hybrid
            and not (plan.dense or dense_from_vectors)
        )
        try:
            results = await asyncio.wait_for(
                doc_service.search(
                    query=request.query,
                    top_k=effective_top_k,
                    filters=effective_filters or None,
                    use_hybrid=effective_use_hybrid,
                ),
                timeout=max(0.001, float(plan.deadline_seconds or settings.rag_fast_retrieval_deadline_seconds)),
            )
        except TimeoutError:
            return DocumentSearchResponse(
                results=[],
                total=0,
                retrieval_plan=plan.retrieval_plan,
                retrieval_scope=plan.retrieval_scope,
                dense_policy=plan.dense_policy,
                fallback_reason="retrieval_deadline_exceeded",
                latency_budget={
                    "profile": plan.latency_profile,
                    "deadline_seconds": plan.deadline_seconds,
                    "top_k": plan.top_k,
                    "candidate_pool_k": plan.candidate_pool_k,
                },
                total_available=vector_count,
                total_is_dense=bool(plan.dense or dense_from_vectors),
            )

        return DocumentSearchResponse(
            results=results,
            total=len(results),
            retrieval_plan=plan.retrieval_plan,
            retrieval_scope=plan.retrieval_scope,
            dense_policy=plan.dense_policy,
            fallback_reason=plan.fallback_reason,
            latency_budget={
                "profile": plan.latency_profile,
                "deadline_seconds": plan.deadline_seconds,
                "top_k": plan.top_k,
                "candidate_pool_k": plan.candidate_pool_k,
            },
            total_available=vector_count,
            total_is_dense=bool(plan.dense or dense_from_vectors),
        )

    except Exception as e:
        logger.error(f"Error searching documents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/table-facts")
async def list_table_facts(
    collection_name: str = Query("documents"),
    semantic_type: Optional[str] = Query(None),
    sheet_name: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    vector_db_type: Optional[str] = Query(None),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """List spreadsheet facts/chunks for Knowledge diagnostics."""
    try:
        db_type = _resolve_document_vector_db_type(workspace, vector_db_type)
        base_query = db.query(KnowledgeTableFact).filter(
            KnowledgeTableFact.workspace_id == workspace.id,
            KnowledgeTableFact.collection_slug == collection_name,
        )
        if sheet_name:
            base_query = base_query.filter(KnowledgeTableFact.sheet_name == sheet_name)
        if q:
            like = f"%{q}%"
            base_query = base_query.filter(
                KnowledgeTableFact.content.ilike(like)
                | KnowledgeTableFact.document_filename.ilike(like)
                | KnowledgeTableFact.sheet_name.ilike(like)
                | KnowledgeTableFact.cell_ref.ilike(like)
                | KnowledgeTableFact.cell_range.ilike(like)
                | KnowledgeTableFact.row_label.ilike(like)
                | KnowledgeTableFact.column_header.ilike(like)
                | KnowledgeTableFact.subject.ilike(like)
                | KnowledgeTableFact.measure.ilike(like)
                | KnowledgeTableFact.value_raw.ilike(like)
            )
        by_type = {
            str(kind): int(count)
            for kind, count in (
                base_query.with_entities(KnowledgeTableFact.semantic_type, func.count())
                .group_by(KnowledgeTableFact.semantic_type)
                .all()
            )
        }
        query = base_query
        if semantic_type:
            query = query.filter(KnowledgeTableFact.semantic_type == semantic_type)
        total = query.count()
        if total:
            rows = (
                query.order_by(
                    KnowledgeTableFact.document_filename,
                    KnowledgeTableFact.sheet_name,
                    KnowledgeTableFact.row_index,
                    KnowledgeTableFact.column_index,
                )
                .offset(offset)
                .limit(limit)
                .all()
            )
            items = [
                {
                    "content": row.content,
                    "semantic_type": row.semantic_type,
                    "document_id": row.document_id,
                    "document_filename": row.document_filename,
                    "sheet_name": row.sheet_name,
                    "cell_ref": row.cell_ref,
                    "cell_range": row.cell_range,
                    "row_start": row.row_index,
                    "row_end": row.row_index,
                    "row_label": row.row_label,
                    "column_header": row.column_header,
                    "unit": row.unit,
                    "table_region_id": row.table_region_id,
                    "interpretation_note": None,
                    "chunk_index": None,
                    "subject": row.subject,
                    "measure": row.measure,
                    "value_raw": row.value_raw,
                    "value_numeric": row.value_numeric,
                }
                for row in rows
            ]
            return {
                "collection_name": collection_name,
                "vector_db_type": db_type,
                "items": items,
                "total_returned": len(items),
                "total": total,
                "has_more": offset + len(items) < total,
                "by_type": by_type,
                "limit": limit,
                "offset": offset,
                "total_is_exact": True,
                "source": "ledger",
            }

        doc_service = DocumentService(
            collection_name=collection_name,
            vector_db_type=db_type,
            workspace_slug=workspace.slug,
        )
        rows = await doc_service.list_table_facts(
            semantic_type=semantic_type,
            sheet_name=sheet_name,
            query=q,
            limit=limit,
            offset=offset,
        )
        items = [
            {
                "content": row.get("content"),
                "semantic_type": row.get("semantic_type"),
                "document_id": row.get("document_id"),
                "document_filename": row.get("document_filename"),
                "sheet_name": row.get("sheet_name"),
                "cell_ref": row.get("cell_ref"),
                "cell_range": row.get("cell_range"),
                "row_start": row.get("row_start"),
                "row_end": row.get("row_end"),
                "row_label": row.get("row_label"),
                "column_header": row.get("column_header"),
                "unit": row.get("unit"),
                "table_region_id": row.get("table_region_id"),
                "interpretation_note": row.get("interpretation_note"),
                "chunk_index": row.get("chunk_index"),
            }
            for row in rows
        ]
        fallback_by_type = dict(sorted(Counter(str(item.get("semantic_type") or "spreadsheet") for item in items).items()))
        return {
            "collection_name": collection_name,
            "vector_db_type": db_type,
            "items": items,
            "total_returned": len(items),
            "total": len(items),
            "has_more": len(items) >= limit,
            "by_type": fallback_by_type,
            "limit": limit,
            "offset": offset,
            "total_is_exact": False,
            "source": "vector",
        }
    except Exception as e:
        logger.error(f"Error listing table facts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/document-facts")
def list_document_facts(
    collection_name: str = Query("documents"),
    semantic_type: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """List structured document facts for Knowledge diagnostics."""
    base_query = db.query(KnowledgeDocumentFact).filter(
        KnowledgeDocumentFact.workspace_id == workspace.id,
        KnowledgeDocumentFact.collection_slug == collection_name,
    )
    if q:
        like = f"%{q}%"
        base_query = base_query.filter(
            KnowledgeDocumentFact.content.ilike(like)
            | KnowledgeDocumentFact.document_filename.ilike(like)
            | KnowledgeDocumentFact.subject.ilike(like)
            | KnowledgeDocumentFact.value_raw.ilike(like)
            | KnowledgeDocumentFact.section_path.ilike(like)
        )
    by_type = {
        str(kind): int(count)
        for kind, count in (
            base_query.with_entities(KnowledgeDocumentFact.semantic_type, func.count())
            .group_by(KnowledgeDocumentFact.semantic_type)
            .all()
        )
    }
    query = base_query
    if semantic_type:
        query = query.filter(KnowledgeDocumentFact.semantic_type == semantic_type)
    total = query.count()
    rows = (
        query.order_by(KnowledgeDocumentFact.document_filename, KnowledgeDocumentFact.page, KnowledgeDocumentFact.paragraph_index)
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "collection_name": collection_name,
        "items": [
            {
                "id": row.id,
                "content": row.content,
                "semantic_type": row.semantic_type,
                "document_id": row.document_id,
                "document_filename": row.document_filename,
                "document_type": row.document_type,
                "subject": row.subject,
                "predicate": row.predicate,
                "value_raw": row.value_raw,
                "value_numeric": row.value_numeric,
                "unit": row.unit,
                "page": row.page,
                "section_path": row.section_path,
                "paragraph_index": row.paragraph_index,
                "table_index": row.table_index,
                "evidence_locator": row.evidence_locator or {},
                "confidence": row.confidence,
            }
            for row in rows
        ],
        "total_returned": len(rows),
        "total": total,
        "has_more": offset + len(rows) < total,
        "by_type": by_type,
        "limit": limit,
        "offset": offset,
    }


def _find_original_file(document_id: str, filename: str) -> Optional[str]:
    """Find the original file in uploads/ or sample_data/."""
    # 1) Check uploads/ (persisted uploaded files)
    for entry in os.listdir(UPLOADS_DIR):
        if entry.startswith(document_id):
            candidate = os.path.join(UPLOADS_DIR, entry)
            if os.path.isfile(candidate):
                return candidate

    # 2) Check sample_data/ (pre-loaded seed docs)
    sample_dir = os.path.join(
        os.path.dirname(
            os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            )
        ),
        "sample_data",
    )
    candidate = os.path.join(sample_dir, filename)
    if os.path.isfile(candidate):
        return candidate

    return None


def _resolve_original_bytes(
    db: DBSession,
    workspace: Workspace,
    collection_name: str,
    document_id: str,
    filename: str,
) -> Optional[bytes]:
    """Return the original source bytes for an indexed document.

    Knowledge collections (web drop / SFTP / SPL wave promotions) keep
    originals in the object store under ``original_key``; legacy uploads land
    in ``uploads/`` or ``sample_data/``. Try the object store first, then the
    local filesystem.
    """
    try:
        collection = get_collection_or_404(
            db, workspace_id=workspace.id, collection_ref=collection_name
        )
        store = get_object_store()
        key = resolve_original_key(collection, filename, store=store)
        if store.exists(key):
            return store.read_bytes(key)
    except HTTPException:
        pass
    except Exception as exc:  # noqa: BLE001 - object store is best-effort here.
        logger.warning(f"Object store lookup failed for {document_id}: {exc}")

    local_path = _find_original_file(document_id, filename)
    if local_path:
        return Path(local_path).read_bytes()
    return None


def _resolve_original_meta(
    db: DBSession,
    workspace: Workspace,
    collection_name: str,
    document_id: str,
    filename: str,
) -> tuple[bool, int]:
    """Cheaply resolve ``(exists, size_bytes)`` without downloading the file.

    Lets the preview endpoint build PDF/image envelopes without pulling the
    full original out of object storage.
    """
    try:
        collection = get_collection_or_404(
            db, workspace_id=workspace.id, collection_ref=collection_name
        )
        store = get_object_store()
        key = resolve_original_key(collection, filename, store=store)
        if store.exists(key):
            return True, int(store.size(key) or 0)
    except HTTPException:
        pass
    except Exception as exc:  # noqa: BLE001 - object store is best-effort here.
        logger.warning(f"Object store meta lookup failed for {document_id}: {exc}")

    local_path = _find_original_file(document_id, filename)
    if local_path:
        try:
            return True, int(os.path.getsize(local_path))
        except OSError:
            return True, 0
    return False, 0


async def _document_filename_for_id(
    db: DBSession,
    workspace: Workspace,
    collection_name: str,
    document_id: str,
    doc_service: Optional[DocumentService] = None,
) -> Optional[str]:
    ledger_doc = _ledger_document_for_id(db, workspace, collection_name, document_id)
    if ledger_doc:
        return ledger_doc.get("filename") or ledger_doc.get("document_filename") or ""
    if doc_service is None:
        db_type = _resolve_document_vector_db_type(workspace)
        doc_service = DocumentService(
            collection_name=collection_name,
            vector_db_type=db_type,
            workspace_slug=workspace.slug,
        )
    documents = await doc_service.list_documents()
    doc = next((d for d in documents if d.get("document_id") == document_id), None)
    if not doc:
        return None
    return doc.get("filename") or doc.get("document_filename") or ""


_OFFICE_PREVIEW_EXTENSIONS = {".doc", ".docx", ".pptx"}


def _office_preview_pdf_bytes(original: bytes, filename: str) -> bytes:
    suffix = Path(filename).suffix.lower() or ".pptx"
    with tempfile.TemporaryDirectory() as tmp_dir:
        source_path = Path(tmp_dir) / Path(filename).name
        source_path.write_bytes(original)
        cmd = [
            "soffice",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            tmp_dir,
            str(source_path),
        ]
        completed = subprocess.run(cmd, capture_output=True, timeout=45, check=False)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or b"").decode("utf-8", errors="ignore")[:300]
            raise RuntimeError(f"office_preview_conversion_failed:{detail}")
        pdf_path = source_path.with_suffix(".pdf")
        if not pdf_path.exists():
            candidates = list(Path(tmp_dir).glob("*.pdf"))
            pdf_path = candidates[0] if candidates else pdf_path
        if not pdf_path.exists():
            raise RuntimeError(f"office_preview_conversion_missing:{suffix}")
        return pdf_path.read_bytes()


@router.get("/{document_id}/metadata")
async def get_document_metadata(
    document_id: str,
    collection_name: str = Query("documents"),
    workspace: Workspace = Depends(get_current_workspace),
):
    """Return docmeta-enriched metadata for a single document.

    Surfaces the ``document_*`` fields persisted at ingestion time (title,
    author, num_pages, token_count, TF-IDF keywords, language, ...). The
    UI's "Doc facts" panel calls this endpoint for every document it
    renders in the sources list; callers that only need the filename stay
    on the cheaper ``GET /documents`` listing.
    """
    try:
        db_type = _resolve_document_vector_db_type(workspace)
        doc_service = DocumentService(
            collection_name=collection_name,
            vector_db_type=db_type,
            workspace_slug=workspace.slug,
        )
        metadata = await doc_service.get_document_metadata(document_id)
        if not metadata:
            raise HTTPException(status_code=404, detail="Document not found")
        return {
            "document_id": document_id,
            "metadata": metadata,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching document metadata: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/preview/{document_id}")
async def preview_document(
    document_id: str,
    collection_name: str = Query("documents"),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Return raw content of a document for preview (text) or redirect info for binary files."""
    try:
        db_type = _resolve_document_vector_db_type(workspace)
        doc = _ledger_document_for_id(db, workspace, collection_name, document_id)
        if doc is None:
            doc_service = DocumentService(
                collection_name=collection_name,
                vector_db_type=db_type,
                workspace_slug=workspace.slug,
            )
            documents = await doc_service.list_documents()
            doc = next((d for d in documents if d.get("document_id") == document_id), None)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        filename = doc.get("filename", "")
        filepath = _find_original_file(document_id, filename)
        if not filepath:
            raise HTTPException(status_code=404, detail="Source file not found")

        ext = os.path.splitext(filepath)[1].lower()

        if ext == ".pdf":
            return {
                "document_id": document_id,
                "filename": filename,
                "content_type": "application/pdf",
                "download_url": f"/api/v1/documents/file/{document_id}",
                "size": os.path.getsize(filepath),
            }

        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        return {
            "document_id": document_id,
            "filename": filename,
            "content": content,
            "content_type": "text/plain",
            "size": len(content),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error previewing document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/file/{document_id}")
async def serve_document_file(
    document_id: str,
    collection_name: str = Query("documents"),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Serve the original uploaded file (PDF, DOCX, etc.) for in-browser viewing."""
    try:
        db_type = _resolve_document_vector_db_type(workspace)
        doc = _ledger_document_for_id(db, workspace, collection_name, document_id)
        if doc is None:
            doc_service = DocumentService(
                collection_name=collection_name,
                vector_db_type=db_type,
                workspace_slug=workspace.slug,
            )
            documents = await doc_service.list_documents()
            doc = next((d for d in documents if d.get("document_id") == document_id), None)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        filename = doc.get("filename", "")
        filepath = _find_original_file(document_id, filename)
        if not filepath:
            raise HTTPException(status_code=404, detail="Source file not found")

        ext = os.path.splitext(filepath)[1].lower()
        media_types = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".txt": "text/plain",
            ".md": "text/markdown",
        }
        media_type = media_types.get(ext, "application/octet-stream")

        return FileResponse(
            filepath,
            media_type=media_type,
            filename=filename,
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error serving file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{document_id}/rich-preview")
async def rich_preview_document(
    document_id: str,
    collection_name: str = Query("documents"),
    filename: Optional[str] = Query(
        None, description="Filename hint; skips the collection scan when provided."
    ),
    db: DBSession = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
):
    """Return an inline preview for an indexed source document.

    Mirrors the Secure Deposit preview contract (``kind`` text / spreadsheet /
    image / pdf / binary) so the Knowledge Sources browser can reuse the same
    viewer. Originals are read from the object store (or local uploads).

    PDF/image previews only need size + media type, so the original bytes are
    NOT downloaded here; the viewer streams them lazily from ``download_url``.
    """
    try:
        resolved_name = filename
        if not resolved_name:
            resolved_name = await _document_filename_for_id(
                db,
                workspace,
                collection_name,
                document_id,
            )
        if not resolved_name:
            raise HTTPException(status_code=404, detail="Document not found")

        media_type = mimetypes.guess_type(resolved_name)[0] or "application/octet-stream"
        download_url = (
            f"/api/v1/documents/{quote(document_id)}/raw"
            f"?collection_name={quote(collection_name)}&filename={quote(resolved_name)}"
        )
        ext = Path(resolved_name).suffix.lower()

        exists, size = _resolve_original_meta(
            db, workspace, collection_name, document_id, resolved_name
        )
        if not exists:
            raise HTTPException(status_code=404, detail="Source file not found")

        if ext in _OFFICE_PREVIEW_EXTENSIONS:
            converted_url = (
                f"/api/v1/documents/{quote(document_id)}/converted-preview"
                f"?collection_name={quote(collection_name)}&filename={quote(resolved_name)}"
            )
            return {
                "kind": "pdf",
                "filename": f"{Path(resolved_name).stem}.pdf",
                "content_type": "application/pdf",
                "size_bytes": size,
                "download_url": converted_url,
                "source_filename": resolved_name,
            }

        if not preview_needs_file_bytes(resolved_name, media_type, size):
            # PDF / image / binary: only size + media type are needed.
            return build_file_preview(
                Path(resolved_name),
                filename=resolved_name,
                media_type=media_type,
                size_bytes=size,
                download_url=download_url,
            )

        data = _resolve_original_bytes(db, workspace, collection_name, document_id, resolved_name)
        if data is None:
            raise HTTPException(status_code=404, detail="Source file not found")
        suffix = os.path.splitext(resolved_name)[1] or ""
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        try:
            return build_file_preview(
                Path(tmp_path),
                filename=resolved_name,
                media_type=media_type,
                size_bytes=len(data),
                download_url=download_url,
            )
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error building rich preview: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{document_id}/raw")
async def serve_document_raw(
    document_id: str,
    collection_name: str = Query("documents"),
    disposition: str = Query("inline"),
    filename: Optional[str] = Query(
        None, description="Filename hint; skips the collection scan when provided."
    ),
    db: DBSession = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
):
    """Serve the original source bytes (object store or local) for inline view."""
    try:
        resolved_name = filename
        if not resolved_name:
            resolved_name = await _document_filename_for_id(
                db,
                workspace,
                collection_name,
                document_id,
            )
        if not resolved_name:
            raise HTTPException(status_code=404, detail="Document not found")

        data = _resolve_original_bytes(db, workspace, collection_name, document_id, resolved_name)
        if data is None:
            raise HTTPException(status_code=404, detail="Source file not found")

        media_type = mimetypes.guess_type(resolved_name)[0] or "application/octet-stream"
        safe_disposition = "attachment" if disposition == "attachment" else "inline"
        name = os.path.basename(resolved_name) or "document"
        return Response(
            content=data,
            media_type=media_type,
            headers={
                "Content-Disposition": f'{safe_disposition}; filename="{name}"',
                "Cache-Control": "private, max-age=3600",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error serving raw document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{document_id}/converted-preview")
async def converted_preview_document(
    document_id: str,
    collection_name: str = Query("documents"),
    disposition: str = Query("inline"),
    filename: Optional[str] = Query(
        None, description="Filename hint; skips the collection scan when provided."
    ),
    db: DBSession = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
):
    try:
        resolved_name = filename
        if not resolved_name:
            resolved_name = await _document_filename_for_id(
                db,
                workspace,
                collection_name,
                document_id,
            )
        if not resolved_name:
            raise HTTPException(status_code=404, detail="Document not found")
        if Path(resolved_name).suffix.lower() not in _OFFICE_PREVIEW_EXTENSIONS:
            raise HTTPException(status_code=415, detail="Converted preview is not available for this file type")
        data = _resolve_original_bytes(db, workspace, collection_name, document_id, resolved_name)
        if data is None:
            raise HTTPException(status_code=404, detail="Source file not found")
        pdf = _office_preview_pdf_bytes(data, resolved_name)
        safe_disposition = "attachment" if disposition == "attachment" else "inline"
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'{safe_disposition}; filename="{Path(resolved_name).stem}.pdf"',
                "Cache-Control": "private, max-age=300",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error converting document preview: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chunks")
async def list_document_chunks(
    collection_name: str = Query("documents"),
    document_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    max_chars: int = Query(800, ge=80, le=8000),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Browse indexed chunks (vector payloads) for a collection or document.

    Powers the Knowledge "Chunks" tab: returns the chunk body (truncated to
    ``max_chars``) plus retrieval locators (chunk index, section path, page)
    so operators can inspect what was actually embedded.
    """
    try:
        db_type = _resolve_document_vector_db_type(workspace)
        doc_service = DocumentService(
            collection_name=collection_name,
            vector_db_type=db_type,
            workspace_slug=workspace.slug,
        )
        filters = {"document_id": document_id} if document_id else None
        total: int | None = None
        total_is_exact = False
        try:
            if document_id:
                collection = get_collection_or_404(
                    db,
                    workspace_id=workspace.id,
                    collection_ref=collection_name,
                )
                for row in collection_source_rows(db, collection=collection):
                    metadata = dict(row.source_metadata or {})
                    row_doc_id = metadata.get("document_id") or row.normalized_name or row.filename or row.id
                    if str(row_doc_id) == str(document_id):
                        total = int(row.chunk_count or 0)
                        total_is_exact = True
                        break
            if total is None:
                total = await doc_service.vector_db.count_payloads(filters=filters)
                total_is_exact = total is not None
            if total is None and not document_id:
                total = await doc_service.get_document_count()
                total_is_exact = True
        except Exception as exc:  # noqa: BLE001 - diagnostics only.
            logger.warning("Could not compute chunk total", error=str(exc), collection=collection_name)
        payloads = await doc_service.vector_db.list_payloads(
            filters=filters, limit=limit, offset=offset
        )
        chunks: list[dict] = []
        for pl in payloads:
            content = str(pl.get("content") or pl.get("text") or "")
            chunks.append(
                {
                    "point_id": pl.get("point_id"),
                    "chunk_id": pl.get("chunk_id"),
                    "document_id": pl.get("document_id"),
                    "document_filename": pl.get("document_filename"),
                    "chunk_index": pl.get("chunk_index"),
                    "section_path": pl.get("section_path"),
                    "page": pl.get("page") or pl.get("page_number"),
                    "semantic_type": pl.get("semantic_type"),
                    "content_length": len(content),
                    "content": content[:max_chars],
                    "truncated": len(content) > max_chars,
                }
            )
        return {
            "collection_name": collection_name,
            "document_id": document_id,
            "limit": limit,
            "offset": offset,
            "count": len(chunks),
            "total": total if total is not None else len(chunks),
            "total_is_exact": total_is_exact,
            "has_more": (offset + len(chunks) < total) if total is not None else len(chunks) >= limit,
            "navigation_note": (
                "Global chunk browsing is paginated over a dense vector collection; use document filters for audit-grade navigation."
                if not document_id
                else ""
            ),
            "chunks": chunks,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing chunks: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _project_2d(matrix: np.ndarray) -> tuple[np.ndarray, str]:
    """Reduce embeddings to 2D. Prefer UMAP (clusters), fall back to PCA."""
    n = matrix.shape[0]
    if n < 3:
        return np.zeros((n, 2), dtype=float), "trivial"
    try:
        import umap  # type: ignore

        reducer = umap.UMAP(
            n_components=2,
            n_neighbors=min(15, n - 1),
            metric="cosine",
            random_state=42,
        )
        coords = np.asarray(reducer.fit_transform(matrix), dtype=float)
        return coords, "umap"
    except Exception:  # noqa: BLE001 - UMAP optional; PCA always works.
        centered = matrix - matrix.mean(axis=0, keepdims=True)
        try:
            _, _, vt = np.linalg.svd(centered, full_matrices=False)
            coords = centered @ vt[:2].T
        except Exception:  # noqa: BLE001
            coords = centered[:, :2]
        return np.asarray(coords, dtype=float), "pca"


def _scale_unit(coords: np.ndarray) -> np.ndarray:
    """Min-max scale each axis into [0, 1] for stable frontend rendering."""
    if coords.size == 0:
        return coords
    scaled = coords.astype(float).copy()
    for axis in range(scaled.shape[1]):
        col = scaled[:, axis]
        lo, hi = float(col.min()), float(col.max())
        scaled[:, axis] = (col - lo) / (hi - lo) if hi > lo else 0.5
    return scaled


def _build_embedding_graph(
    rows: list[dict],
    *,
    neighbors: int,
    min_score: float,
) -> dict:
    """Build nodes (with 2D coords) + similarity edges from sampled vectors."""
    vectors = np.asarray([r["vector"] for r in rows], dtype=float)
    if len(rows):
        raw_coords, projection = _project_2d(vectors)
        coords = _scale_unit(raw_coords)
    else:
        coords, projection = np.zeros((0, 2)), "trivial"

    nodes: list[dict] = []
    for idx, row in enumerate(rows):
        pl = row.get("payload", {})
        content = str(pl.get("content") or pl.get("text") or "")
        nodes.append(
            {
                "id": idx,
                "point_id": row.get("id"),
                "document_id": pl.get("document_id"),
                "document_filename": pl.get("document_filename"),
                "chunk_index": pl.get("chunk_index"),
                "section_path": pl.get("section_path"),
                "page": pl.get("page") or pl.get("page_number"),
                "snippet": content[:180],
                "source_kind": pl.get("source_kind") or pl.get("document_type"),
                "project_code": pl.get("project_code"),
                "archive_name": pl.get("archive_name"),
                "x": float(coords[idx][0]) if len(coords) else 0.5,
                "y": float(coords[idx][1]) if len(coords) else 0.5,
            }
        )

    edges: list[dict] = []
    if len(rows) >= 2:
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        normed = vectors / np.where(norms == 0, 1.0, norms)
        sim = normed @ normed.T
        np.fill_diagonal(sim, -1.0)
        k = max(1, min(int(neighbors), len(rows) - 1))
        seen: set[tuple[int, int]] = set()
        for i in range(len(rows)):
            top = np.argpartition(sim[i], -k)[-k:]
            for j in top:
                j = int(j)
                weight = float(sim[i][j])
                if weight < min_score:
                    continue
                pair = (i, j) if i < j else (j, i)
                if pair in seen:
                    continue
                seen.add(pair)
                edges.append({"source": pair[0], "target": pair[1], "weight": round(weight, 4)})

    return {"nodes": nodes, "edges": edges, "projection": projection}


def _is_dense_graph_request(
    *,
    collection: KnowledgeCollection | None,
    total_chunks: int,
) -> bool:
    chunk_threshold = int(getattr(settings, "rag_dense_chunk_threshold", 100_000) or 100_000)
    source_threshold = int(getattr(settings, "rag_dense_source_threshold", 5_000) or 5_000)
    ledger_chunks = int(getattr(collection, "chunk_count", 0) or 0) if collection else 0
    ledger_sources = int(getattr(collection, "document_count", 0) or 0) if collection else 0
    return max(int(total_chunks or 0), ledger_chunks) > chunk_threshold or ledger_sources > source_threshold


@router.get("/graph")
async def embedding_graph(
    collection_name: str = Query("documents"),
    document_id: Optional[str] = Query(None),
    sample: int = Query(200, ge=10, le=1000),
    neighbors: int = Query(4, ge=1, le=15),
    min_score: float = Query(0.55, ge=0.0, le=1.0),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Embedding map: 2D projection of sampled chunks + similarity edges.

    Inspired by the Qdrant graph/visualize tools. Sampled chunk vectors are
    reduced to 2D (UMAP when available, otherwise PCA) and connected to their
    nearest neighbours, letting operators inspect clusters and outliers and
    jump from any node to the source document preview.
    """
    try:
        db_type = _resolve_document_vector_db_type(workspace)
        collection = None
        try:
            collection = get_collection_or_404(
                db,
                workspace_id=workspace.id,
                collection_ref=collection_name,
            )
        except HTTPException:
            collection = None
        doc_service = DocumentService(
            collection_name=collection_name,
            vector_db_type=db_type,
            workspace_slug=workspace.slug,
        )
        total_chunks = await doc_service.get_document_count()
        is_dense = _is_dense_graph_request(collection=collection, total_chunks=total_chunks)
        sample_cap = _GRAPH_DENSE_SAMPLE_CAP if is_dense else 1000
        requested_sample = int(sample)
        effective_sample = max(10, min(requested_sample, sample_cap))
        sample_capped = effective_sample < requested_sample
        cache_key = (
            workspace.id,
            collection_name,
            document_id or "",
            requested_sample,
            effective_sample,
            int(neighbors),
            round(float(min_score), 4),
            collection.updated_at.isoformat() if collection and collection.updated_at else "",
            int(total_chunks or 0),
        )
        cached = _GRAPH_CACHE.get(cache_key)
        if cached and time.time() - cached[0] < _GRAPH_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["cached"] = True
            return payload

        filters = {"document_id": document_id} if document_id else None
        warnings: list[str] = []
        if is_dense:
            warnings.append("Dense collection: this map is sampled and not exhaustive.")
        if sample_capped:
            warnings.append(f"Sample capped to {effective_sample} nodes for interactive latency.")
        try:
            rows = await asyncio.wait_for(
                doc_service.vector_db.sample_chunk_vectors(limit=effective_sample, filters=filters),
                timeout=8,
            )
        except asyncio.TimeoutError:
            rows = []
        if not rows:
            return {
                "collection_name": collection_name,
                "document_id": document_id,
                "sample": 0,
                "sample_requested": requested_sample,
                "sample_cap": sample_cap,
                "sample_capped": sample_capped,
                "total_chunks": total_chunks,
                "total_is_dense": is_dense,
                "neighbors": neighbors,
                "min_score": min_score,
                "vector_dim": None,
                "projection": "none",
                "nodes": [],
                "edges": [],
                "supported": db_type == "qdrant" or db_type == "faiss",
                "cached": False,
                "warnings": ["No sampled vectors were returned before the graph timeout."] + warnings,
            }
        try:
            graph = await asyncio.wait_for(
                asyncio.to_thread(_build_embedding_graph, rows, neighbors=neighbors, min_score=min_score),
                timeout=8,
            )
        except asyncio.TimeoutError:
            graph = {
                "nodes": [
                    {
                        "id": idx,
                        "point_id": row.get("id"),
                        "document_id": (row.get("payload") or {}).get("document_id"),
                        "document_filename": (row.get("payload") or {}).get("document_filename"),
                        "chunk_index": (row.get("payload") or {}).get("chunk_index"),
                        "section_path": (row.get("payload") or {}).get("section_path"),
                        "page": (row.get("payload") or {}).get("page") or (row.get("payload") or {}).get("page_number"),
                        "snippet": str((row.get("payload") or {}).get("content") or "")[:180],
                        "source_kind": (row.get("payload") or {}).get("source_kind") or (row.get("payload") or {}).get("document_type"),
                        "project_code": (row.get("payload") or {}).get("project_code"),
                        "archive_name": (row.get("payload") or {}).get("archive_name"),
                        "x": 0.5,
                        "y": 0.5,
                    }
                    for idx, row in enumerate(rows)
                ],
                "edges": [],
                "projection": "timeout",
            }
            warnings.append("Projection timed out; showing sampled nodes without cluster layout.")
        payload = {
            "collection_name": collection_name,
            "document_id": document_id,
            "sample": len(rows),
            "sample_requested": requested_sample,
            "sample_cap": sample_cap,
            "sample_capped": sample_capped,
            "total_chunks": total_chunks,
            "total_is_dense": is_dense,
            "neighbors": neighbors,
            "min_score": min_score,
            "vector_dim": len(rows[0].get("vector") or []),
            "projection": graph["projection"],
            "nodes": graph["nodes"],
            "edges": graph["edges"],
            "supported": True,
            "cached": False,
            "warnings": warnings,
        }
        _GRAPH_CACHE[cache_key] = (time.time(), payload)
        return payload
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error building embedding graph: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_document_stats(
    collection_name: str = "documents",
    workspace: Workspace = Depends(get_current_workspace),
):
    """Get document statistics"""
    try:
        db_type = _resolve_document_vector_db_type(workspace)
        doc_service = DocumentService(
            collection_name=collection_name,
            vector_db_type=db_type,
            workspace_slug=workspace.slug,
        )
        count = await doc_service.get_document_count()

        # Get cache stats if available
        cache_stats = None
        if doc_service.cache:
            cache_stats = doc_service.cache.get_stats()

        vector_dim = getattr(doc_service.vector_db, "dimension", None)

        return {
            "collection_name": collection_name,
            "vector_db_type": db_type,
            "total_chunks": count,
            "vector_dim": vector_dim,
            "cache_stats": cache_stats,
        }

    except Exception as e:
        logger.error(f"Error getting stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/clear")
async def clear_all_documents(
    collection_name: str = Query("documents"),
    vector_db_type: Optional[str] = Query(None),
    confirm: bool = Query(False, description="Must be true to acknowledge the destructive clear."),
    confirm_collection_name: Optional[str] = Query(
        None,
        description="Must exactly match collection_name to prevent accidental broad clears.",
    ),
    clear_uploads: bool = Query(
        False,
        description="Also clear the legacy uploads directory. Disabled by default to avoid cross-collection file loss.",
    ),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Clear all documents from a collection"""
    try:
        _require_workspace_admin(db, user, workspace)
        if not confirm:
            raise HTTPException(
                status_code=400,
                detail="Pass ?confirm=true to acknowledge the destructive document clear.",
            )
        if confirm_collection_name != collection_name:
            raise HTTPException(
                status_code=400,
                detail="confirm_collection_name must exactly match collection_name.",
            )
        db_type = _resolve_document_vector_db_type(workspace, vector_db_type)

        doc_service = DocumentService(
            collection_name=collection_name, vector_db_type=db_type, workspace_slug=workspace.slug
        )
        success = await doc_service.clear_all_documents()

        if success:
            deleted_upload_files = 0
            if clear_uploads:
                for entry in os.listdir(UPLOADS_DIR):
                    try:
                        os.unlink(os.path.join(UPLOADS_DIR, entry))
                        deleted_upload_files += 1
                    except OSError:
                        pass
            return {
                "status": "success",
                "message": f"All documents cleared from collection '{collection_name}'",
                "vector_db_type": db_type,
                "deleted_upload_files": deleted_upload_files,
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to clear documents")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error clearing documents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    collection_name: str = Query("documents"),
    vector_db_type: Optional[str] = Query(None),
    workspace: Workspace = Depends(get_current_workspace),
):
    """Delete a document and its chunks"""
    try:
        db_type = _resolve_document_vector_db_type(workspace, vector_db_type)

        doc_service = DocumentService(
            collection_name=collection_name, vector_db_type=db_type, workspace_slug=workspace.slug
        )

        success = await doc_service.delete_document(document_id)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete document")

        # Clean up persisted upload file
        for entry in os.listdir(UPLOADS_DIR):
            if entry.startswith(document_id):
                try:
                    os.unlink(os.path.join(UPLOADS_DIR, entry))
                except OSError:
                    pass

        return {
            "status": "success",
            "message": f"Document {document_id} deleted",
            "vector_db_type": db_type,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/collections")
async def list_collections(
    vector_db_type: Optional[str] = Query(None),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """List canonical collections for the current workspace.

    The legacy ``collections`` string list is kept for existing UI consumers;
    richer Agentium metadata is returned under ``items``.
    """
    try:
        from app.services.vector_db.factory import VectorDBFactory

        db_type = _resolve_document_vector_db_type(workspace, vector_db_type)

        rows = (
            db.query(KnowledgeCollection)
            .filter(KnowledgeCollection.workspace_id == workspace.id)
            .order_by(KnowledgeCollection.created_at.desc())
            .all()
        )
        items = [
            await serialize_collection(
                row,
                vector_db_type=db_type,
                workspace_slug=workspace.slug,
                include_metrics=False,
                include_document_names=False,
            )
            for row in rows
        ]

        legacy_names = VectorDBFactory.list_collections_for_workspace(
            db_type=db_type, workspace_slug=workspace.slug
        )
        ledger_slugs = {row.slug for row in rows}
        legacy_names = [
            name for name in legacy_names if not name.startswith("_") and name not in ledger_slugs
        ]
        collection_names = [item["slug"] for item in items] + legacy_names

        return {
            "collections": collection_names,
            "items": items,
            "legacy_collections": legacy_names,
            "default": collection_names[0] if collection_names else None,
            "vector_db_type": db_type,
        }

    except Exception as e:
        logger.error(f"Error listing collections: {e}", exc_info=True)
        # Return empty list on error, let frontend handle it
        return {
            "collections": [],
            "items": [],
            "legacy_collections": [],
            "default": None,
            "vector_db_type": vector_db_type or settings.default_vector_db_type,
        }


@router.post("/collections")
async def create_collection(
    payload: CollectionCreateRequest | None = Body(None),
    collection_name: Optional[str] = Query(None),
    vector_db_type: Optional[str] = Query(None),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Create a workspace-scoped collection ledger row and vector collection."""
    try:
        from app.services.vector_db.factory import VectorDBFactory

        db_type = _resolve_document_vector_db_type(workspace, vector_db_type)
        requested_name = (payload.name if payload else collection_name) or ""
        if not requested_name.strip():
            raise HTTPException(status_code=422, detail="Collection name is required")

        if payload is None and collection_name:
            row = create_or_get_collection(
                db,
                workspace=workspace,
                name=requested_name,
                created_by_user_id=user.id,
                slug=collection_name,
            )
        else:
            row = create_knowledge_collection(
                db,
                workspace=workspace,
                name=requested_name,
                description=payload.description if payload else "",
                created_by_user_id=user.id,
                slug=payload.slug if payload else collection_name,
            )
        vector_db = VectorDBFactory.get_db(row.slug, db_type=db_type, workspace_slug=workspace.slug)

        # For FAISS, ensure the index is created and saved so it shows up in listings
        if db_type == "faiss":
            # Create index with default dimension (384 for all-MiniLM-L6-v2)
            await vector_db.create_index(384)
            # Save to disk immediately so it appears in listings
            if hasattr(vector_db, "_save"):
                vector_db._save()
        elif db_type == "qdrant":
            from app.services.embedding.embedder import Embedder

            dim = Embedder().get_dimension()
            await vector_db.create_index(dim)

        count = await vector_db.get_count()
        row.chunk_count = count
        db.commit()
        db.refresh(row)

        updated_collections = VectorDBFactory.list_collections_for_workspace(
            db_type=db_type, workspace_slug=workspace.slug
        )
        if row.slug not in updated_collections:
            logger.warning(f"Collection '{row.slug}' created but not found in listings")

        item = await serialize_collection(
            row,
            vector_db_type=db_type,
            workspace_slug=workspace.slug,
            include_metrics=True,
            include_document_names=False,
        )
        return {
            "status": "success",
            "collection_id": row.id,
            "collection_name": row.slug,
            "item": item,
            "vector_db_type": db_type,
            "total_chunks": count,
            "collections": updated_collections,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating collection: {e}", exc_info=True)
        error_msg = str(e)
        # Provide more helpful error messages
        if "already exists" in error_msg.lower() or "different settings" in error_msg.lower():
            raise HTTPException(
                status_code=409,
                detail="Collection already exists or there is a vector-store conflict. Please try a different name.",
            )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/collections/{collection_id}")
async def get_collection_detail(
    collection_id: str,
    vector_db_type: Optional[str] = Query(None),
    source_limit: int = Query(50, ge=0, le=500),
    source_offset: int = Query(0, ge=0),
    q: Optional[str] = Query(None),
    source_kind: Optional[str] = Query(None),
    extension: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    project_code: Optional[str] = Query(None),
    archive_name: Optional[str] = Query(None),
    language: Optional[str] = Query(None),
    sort: str = Query("filename"),
    sort_dir: str = Query("asc"),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Return collection metadata enriched with storage/vector metrics."""
    db_type = _resolve_document_vector_db_type(workspace, vector_db_type)
    row = get_collection_or_404(
        db,
        workspace_id=workspace.id,
        collection_ref=collection_id,
    )
    jobs = (
        db.query(WorkerJob)
        .filter(WorkerJob.collection_id == row.id)
        .order_by(WorkerJob.created_at.desc())
        .limit(10)
        .all()
    )
    payload = await serialize_collection(
        row,
        vector_db_type=db_type,
        workspace_slug=workspace.slug,
        include_metrics=True,
        include_document_names=False,
    )
    payload["inventory"] = collection_inventory(
        db,
        collection=row,
        include_sources=True,
        source_limit=source_limit,
        source_offset=source_offset,
        q=q,
        source_kind=source_kind,
        extension=extension,
        status=status,
        project_code=project_code,
        archive_name=archive_name,
        language=language,
        sort=sort,
        sort_dir=sort_dir,
    )
    return _attach_collection_job_diagnostics(payload, jobs)


@router.get("/collections/{collection_id}/inventory")
async def get_collection_inventory(
    collection_id: str,
    source_limit: int | None = Query(default=None, ge=0, le=1000),
    source_offset: int = Query(0, ge=0),
    q: Optional[str] = Query(None),
    source_kind: Optional[str] = Query(None),
    extension: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    project_code: Optional[str] = Query(None),
    archive_name: Optional[str] = Query(None),
    language: Optional[str] = Query(None),
    sort: str = Query("filename"),
    sort_dir: str = Query("asc"),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Return authoritative source cardinality and typology for a collection."""
    row = get_collection_or_404(
        db,
        workspace_id=workspace.id,
        collection_ref=collection_id,
    )
    return collection_inventory(
        db,
        collection=row,
        include_sources=True,
        source_limit=source_limit,
        source_offset=source_offset,
        q=q,
        source_kind=source_kind,
        extension=extension,
        status=status,
        project_code=project_code,
        archive_name=archive_name,
        language=language,
        sort=sort,
        sort_dir=sort_dir,
    )


@router.get("/collections/{collection_id}/diagnostics")
async def get_collection_diagnostics(
    collection_id: str,
    vector_db_type: Optional[str] = Query(None),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Return corpus quality and scalability diagnostics for a collection."""
    row = get_collection_or_404(
        db,
        workspace_id=workspace.id,
        collection_ref=collection_id,
    )
    db_type = _resolve_document_vector_db_type(workspace, vector_db_type)
    inventory = collection_inventory(db, collection=row, include_sources=False)
    vector_points: int | None = None
    vector_dim = None
    supported_graph = db_type in {"qdrant", "faiss"}
    try:
        doc_service = DocumentService(
            collection_name=row.slug,
            vector_db_type=db_type,
            workspace_slug=workspace.slug,
        )
        vector_points = await doc_service.get_document_count()
        vector_dim = getattr(doc_service.vector_db, "dimension", None)
    except Exception as exc:  # noqa: BLE001 - diagnostics must not block the page.
        logger.warning("Could not compute vector diagnostics", error=str(exc), collection=row.slug)

    document_fact_counts = {
        str(kind): int(count)
        for kind, count in (
            db.query(KnowledgeDocumentFact.semantic_type, func.count())
            .filter(
                KnowledgeDocumentFact.workspace_id == workspace.id,
                KnowledgeDocumentFact.collection_id == row.id,
            )
            .group_by(KnowledgeDocumentFact.semantic_type)
            .all()
        )
    }
    document_fact_doc_types = {
        str(kind or "unknown"): int(count)
        for kind, count in (
            db.query(KnowledgeDocumentFact.document_type, func.count(func.distinct(KnowledgeDocumentFact.document_id)))
            .filter(
                KnowledgeDocumentFact.workspace_id == workspace.id,
                KnowledgeDocumentFact.collection_id == row.id,
            )
            .group_by(KnowledgeDocumentFact.document_type)
            .all()
        )
    }
    table_fact_counts = {
        str(kind): int(count)
        for kind, count in (
            db.query(KnowledgeTableFact.semantic_type, func.count())
            .filter(
                KnowledgeTableFact.workspace_id == workspace.id,
                KnowledgeTableFact.collection_id == row.id,
            )
            .group_by(KnowledgeTableFact.semantic_type)
            .all()
        )
    }
    ledger_chunks = int(inventory.get("chunk_count") or 0)
    drift = None if vector_points is None else int(vector_points - ledger_chunks)
    drift_abs = abs(drift or 0)
    drift_status = "unknown"
    if drift is not None:
        drift_status = "ok" if drift_abs == 0 else ("warning" if drift_abs <= 5000 else "drift")
    dense = bool((vector_points or ledger_chunks) > 100_000 or int(inventory.get("source_count") or 0) > 5_000)
    offline_sample = 5_000 if dense else min(max(vector_points or ledger_chunks or 0, 0), 500)
    offline_artifact_key = get_object_store().key(
        row.artifact_prefix,
        "derived",
        "embedding-clusters",
        "latest.json",
    )
    offline_clustering = {
        "state": "recommended" if dense and supported_graph and (vector_points or ledger_chunks) else "not_needed",
        "reason": (
            "Use a manually launched offline artifact if the live sampled graph becomes slow or unstable."
            if dense
            else "Live sampled graph is sufficient at the current corpus size."
        ),
        "launch_policy": "manual_only",
        "auto_run": False,
        "worker_kind": "embedding_cluster_artifact",
        "worker_configured": False,
        "artifact_key": offline_artifact_key,
        "default_sample": offline_sample,
        "max_live_sample": 500,
        "stratification": ["source_kind", "project_code", "source", "chunk_count_bucket"],
        "stores_vectors": False,
    }
    feature_status = {
        "graph": {
            "state": "available" if supported_graph and (vector_points or 0) > 0 else "disabled",
            "reason": "Sampled only for dense collections." if supported_graph else "Vector store does not expose graph sampling.",
        },
        "offline_clustering": {
            "state": offline_clustering["state"],
            "reason": offline_clustering["reason"],
        },
        "document_facts": {
            "state": "available" if sum(document_fact_counts.values()) > 0 else "empty",
            "reason": "Structured document facts are present." if document_fact_counts else "No document facts are indexed.",
        },
        "ocr": {
            "state": "available"
            if any(key in document_fact_counts for key in ("document_ocr_text", "visual_text_block", "visual_parameter", "visual_warning"))
            else "empty",
            "reason": "No OCR/visual fact layer exists for this collection.",
        },
        "table_facts": {
            "state": "available" if sum(table_fact_counts.values()) > 0 else "empty",
            "reason": "No structured table facts are indexed for this collection.",
        },
    }
    return {
        "collection_id": row.id,
        "collection_slug": row.slug,
        "collection_name": row.name,
        "status": row.status,
        "vector_db_type": db_type,
        "vector_points": vector_points,
        "vector_dim": vector_dim,
        "ledger_source_count": inventory.get("source_count", 0),
        "ledger_document_count": row.document_count or 0,
        "ledger_chunk_sum": ledger_chunks,
        "document_names_count": len(row.document_names or []),
        "drift": drift,
        "drift_status": drift_status,
        "dense": dense,
        "dense_thresholds": {"chunks": 100_000, "sources": 5_000},
        "chunk_buckets": inventory.get("chunk_buckets", {}),
        "chunk_percentiles": inventory.get("chunk_percentiles", {}),
        "top_sources": inventory.get("top_sources", []),
        "zero_chunk_sources": inventory.get("zero_chunk_sources", 0),
        "error_sources": inventory.get("error_sources", 0),
        "heavy_sources": inventory.get("heavy_sources", 0),
        "by_kind": inventory.get("by_kind", {}),
        "by_extension": inventory.get("by_extension", {}),
        "by_status": inventory.get("by_status", {}),
        "document_facts": {
            "total": sum(document_fact_counts.values()),
            "by_type": document_fact_counts,
            "docs_by_document_type": document_fact_doc_types,
        },
        "table_facts": {
            "total": sum(table_fact_counts.values()),
            "by_type": table_fact_counts,
        },
        "offline_clustering": offline_clustering,
        "feature_status": feature_status,
    }


@router.post("/collections/{collection_id}/retrieval-artifact-jobs")
async def create_retrieval_artifact_job(
    collection_id: str,
    payload: RetrievalArtifactJobRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Queue a manual offline retrieval artifact job for a collection."""
    row = get_collection_or_404(
        db,
        workspace_id=workspace.id,
        collection_ref=collection_id,
    )
    if payload.kind not in SUPPORTED_RETRIEVAL_ARTIFACT_KINDS:
        raise HTTPException(status_code=422, detail="Unsupported retrieval artifact job kind")
    base_result = {
        "stage": "dry_run" if payload.dry_run else "queued",
        "launch_policy": "manual_only",
        "requested_by": getattr(user, "id", None),
        "collection_slug": row.slug,
        "collection_id": row.id,
        "kind": payload.kind,
        "auto_run": False,
        "dry_run": bool(payload.dry_run),
    }
    if payload.dry_run:
        return {
            **base_result,
            "status": "dry_run",
            "supported_kinds": sorted(SUPPORTED_RETRIEVAL_ARTIFACT_KINDS),
            "would_create_job": True,
            "would_dispatch": True,
            "poll_url": None,
        }

    job = create_worker_job(
        db,
        workspace_id=workspace.id,
        collection_id=row.id,
        kind=payload.kind,
    )
    job.result = base_result
    db.commit()
    task_id = dispatch_worker_job(db, job, allow_inline_fallback=False)
    db.commit()
    refreshed = db.query(WorkerJob).filter(WorkerJob.id == job.id).first() or job
    result = serialize_job(refreshed)
    result["poll_url"] = f"/documents/jobs/{refreshed.id}"
    result["task_id"] = task_id
    return result


@router.patch("/collections/{collection_id}")
async def patch_collection(
    collection_id: str,
    payload: CollectionPatchRequest,
    vector_db_type: Optional[str] = Query(None),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Patch mutable collection presentation fields."""
    _require_workspace_admin(db, user, workspace)
    row = get_collection_or_404(
        db,
        workspace_id=workspace.id,
        collection_ref=collection_id,
    )
    if payload.name is not None:
        row.name = payload.name
    if payload.description is not None:
        row.description = payload.description
    db.commit()
    db.refresh(row)
    db_type = _resolve_document_vector_db_type(workspace, vector_db_type)
    return await serialize_collection(
        row,
        vector_db_type=db_type,
        workspace_slug=workspace.slug,
        include_metrics=True,
        include_document_names=False,
    )


@router.post("/collections/{collection_id}/documents")
async def upload_collection_documents(
    collection_id: str,
    files: list[UploadFile] = File(...),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Store originals and queue worker-owned parse/chunk/embed/index work."""
    row = get_collection_or_404(
        db,
        workspace_id=workspace.id,
        collection_ref=collection_id,
    )
    return await _queue_collection_ingest(
        db=db,
        workspace=workspace,
        collection=row,
        files=files,
    )


@router.get("/jobs")
async def list_worker_jobs(
    kind: str | None = Query(None, description="Optional WorkerJob kind filter."),
    status: str | None = Query(None, description="Comma-separated status filter."),
    collection_id: str | None = Query(None, description="Optional collection id or slug filter."),
    limit: int = Query(20, ge=1, le=100),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """List recent worker jobs in the current workspace.

    Deep Retrieval jobs are server-side state. This endpoint lets the UI recover
    running/recent jobs after a browser reload or closed session.
    """
    query = db.query(WorkerJob).filter(WorkerJob.workspace_id == workspace.id)
    if kind:
        query = query.filter(WorkerJob.kind == kind.strip())
    statuses = [item.strip() for item in str(status or "").split(",") if item.strip()]
    if statuses:
        query = query.filter(WorkerJob.status.in_(statuses))
    if collection_id:
        collection = (
            db.query(KnowledgeCollection)
            .filter(
                KnowledgeCollection.workspace_id == workspace.id,
                (
                    (KnowledgeCollection.id == collection_id)
                    | (KnowledgeCollection.slug == collection_id)
                    | (KnowledgeCollection.name == collection_id)
                ),
            )
            .first()
        )
        if not collection:
            return {"items": [], "total_returned": 0, "limit": limit}
        query = query.filter(WorkerJob.collection_id == collection.id)
    jobs = (
        query.order_by(WorkerJob.updated_at.desc(), WorkerJob.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "items": [serialize_job(job) for job in jobs],
        "total_returned": len(jobs),
        "limit": limit,
    }


@router.get("/jobs/{job_id}")
async def get_worker_job(
    job_id: str,
    include_context: bool = Query(False, description="Include heavy deep retrieval context when explicitly requested."),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    job = (
        db.query(WorkerJob)
        .filter(WorkerJob.id == job_id, WorkerJob.workspace_id == workspace.id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Worker job not found")
    return serialize_job(job, include_retrieval_context=include_context)


@router.delete("/collections/{collection_name}")
async def delete_collection(
    collection_name: str,
    vector_db_type: Optional[str] = Query(None),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Delete a collection in the current workspace."""
    try:
        from urllib.parse import unquote

        from app.services.vector_db.factory import VectorDBFactory

        collection_name = unquote(collection_name)

        db_type = _resolve_document_vector_db_type(workspace, vector_db_type)
        row = (
            db.query(KnowledgeCollection)
            .filter(
                KnowledgeCollection.workspace_id == workspace.id,
                (KnowledgeCollection.id == collection_name)
                | (KnowledgeCollection.slug == collection_name),
            )
            .first()
        )
        logical_collection_name = row.slug if row else collection_name

        scoped_coll = VectorDBFactory.scoped_name(logical_collection_name, workspace.slug)
        collections = VectorDBFactory.list_collections(db_type=db_type)
        collection_exists = scoped_coll in collections

        if not collection_exists and row is None:
            raise HTTPException(
                status_code=404, detail=f"Collection '{collection_name}' not found in {db_type}"
            )

        try:
            vector_db = VectorDBFactory.get_db(
                logical_collection_name, db_type=db_type, workspace_slug=workspace.slug
            )
            await vector_db.clear_collection()
        except Exception as e:
            logger.warning(f"Error clearing collection before deletion: {e}")

        try:
            VectorDBFactory.clear_instance(
                logical_collection_name, db_type=db_type, workspace_slug=workspace.slug
            )
        except Exception as cache_error:
            logger.warning(f"Could not clear cached instance: {cache_error}")

        try:
            if db_type == "chroma":
                import chromadb

                client = chromadb.PersistentClient(path=settings.chroma_persist_directory)
                client.delete_collection(name=scoped_coll)
            elif db_type == "faiss":
                persist_dir = getattr(settings, "faiss_persist_directory", "./faiss_db")
                index_path = os.path.join(persist_dir, f"{scoped_coll}.index")
                metadata_path = os.path.join(persist_dir, f"{scoped_coll}.metadata.pkl")
                if os.path.exists(index_path):
                    os.remove(index_path)
                if os.path.exists(metadata_path):
                    os.remove(metadata_path)
            elif db_type == "qdrant":
                # Collection already removed by clear_collection on QdrantVectorDB
                pass

            if row is not None:
                row_id = row.id
                get_object_store().delete_prefix(row.artifact_prefix)
                db.delete(row)
                db.commit()
            else:
                row_id = None

            logger.info(f"Successfully deleted collection: {logical_collection_name} (type: {db_type})")
            return {
                "status": "success",
                "message": f"Collection '{logical_collection_name}' deleted successfully",
                "collection_id": row_id,
                "collection_name": logical_collection_name,
                "vector_db_type": db_type,
            }
        except ValueError as e:
            # Collection doesn't exist or already deleted
            error_msg = str(e)
            if "not found" in error_msg.lower() or "does not exist" in error_msg.lower():
                raise HTTPException(
                    status_code=404, detail=f"Collection '{collection_name}' not found"
                )
            else:
                logger.error(f"ValueError when deleting collection: {e}", exc_info=True)
                raise HTTPException(
                    status_code=500, detail=f"Failed to delete collection: {error_msg}"
                )
        except Exception as delete_error:
            logger.error(
                f"Error deleting collection '{collection_name}': {delete_error}", exc_info=True
            )
            raise HTTPException(
                status_code=500, detail=f"Failed to delete collection: {str(delete_error)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error deleting collection '{collection_name}': {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail=f"Failed to delete collection: {str(e)}")


@router.get("/list")
async def list_documents(
    collection_name: str = Query("documents"),
    vector_db_type: Optional[str] = Query(None),
    limit: int | None = Query(default=None, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """List documents in a collection (scoped to current workspace).

    Ledger-backed collections can be served from SQL, avoiding a full vector
    scroll on very large Qdrant collections. Legacy vector-only collections
    still fall back to the historical vector listing.
    """
    try:
        db_type = _resolve_document_vector_db_type(workspace, vector_db_type)
        safe_offset = max(0, int(offset or 0))

        try:
            collection = get_collection_or_404(
                db,
                workspace_id=workspace.id,
                collection_ref=collection_name,
            )
            source_rows = collection_source_rows(db, collection=collection)
        except HTTPException:
            collection = None
            source_rows = []

        if collection is not None and source_rows:
            source_rows = [
                row
                for row in source_rows
                if not str(row.filename or "").startswith(".")
                and not str(row.filename or "").endswith(".tmp")
            ]
            total = len(source_rows)
            page_rows = source_rows[safe_offset:]
            if limit is not None:
                page_rows = page_rows[: int(limit)]
            documents = [_source_row_to_document(row) for row in page_rows]
            return {
                "collection_name": collection_name,
                "vector_db_type": db_type,
                "documents": documents,
                "total": total,
                "limit": limit,
                "offset": safe_offset,
                "has_more": safe_offset + len(documents) < total,
                "source": "ledger",
            }

        doc_service = DocumentService(
            collection_name=collection_name, vector_db_type=db_type, workspace_slug=workspace.slug
        )
        documents = await doc_service.list_documents()

        # Filter out temporary files and system files
        filtered_documents = [
            doc
            for doc in documents
            if not doc.get("filename", "").startswith(".")  # Exclude hidden files
            and not doc.get("filename", "").endswith(".tmp")  # Exclude temp files
            and doc.get("document_id")  # Ensure document_id exists
        ]

        total = len(filtered_documents)
        page_documents = filtered_documents[safe_offset:]
        if limit is not None:
            page_documents = page_documents[: int(limit)]

        return {
            "collection_name": collection_name,
            "vector_db_type": db_type,
            "documents": page_documents,
            "total": total,
            "limit": limit,
            "offset": safe_offset,
            "has_more": safe_offset + len(page_documents) < total,
            "source": "vector",
        }

    except Exception as e:
        logger.error(f"Error listing documents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
