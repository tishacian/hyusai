"""Worker-owned document ingestion and indexing workflows."""
from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from pathlib import Path
from datetime import datetime

from app.core.config import settings
from app.core.logging import get_logger
from app.core.settings_manager import get_resolved_settings
from app.db.base import SessionLocal
from app.models.knowledge_collection import (
    KnowledgeCollection,
    KnowledgeCollectionSource,
    WorkerJob,
)
from app.models.secure_deposit import DepositFile
from app.models.workspace import Workspace
from app.services.document_parser.factory import DocumentParserFactory
from app.services.knowledge_collections import (
    create_worker_job,
    document_manifest_key,
    ingested_key,
    original_key,
    resolve_original_key,
    update_collection_status,
    update_job,
    upsert_collection_source,
)
from app.services.object_store import get_object_store
from app.services.rag.bm25_store import rebuild_bm25_artifact
from app.services.rag.document_service import DocumentService
from app.services.rag.vector_store_config import resolve_vector_db_type
from app.services.table_intelligence import clear_collection_table_facts
from app.services.document_intelligence import clear_collection_document_facts
from app.services.ocr import resolve_ocr_config_for_workspace

logger = get_logger(__name__)


def _load_document_metadata_manifest(
    collection: KnowledgeCollection,
) -> dict[str, dict]:
    store = get_object_store()
    key = document_manifest_key(collection)
    if not store.exists(key):
        return {}
    try:
        payload = json.loads(store.read_bytes(key).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "document ingest worker could not read document metadata manifest",
            collection_id=collection.id,
            error=str(exc),
        )
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(name): dict(metadata)
        for name, metadata in payload.items()
        if isinstance(metadata, dict)
    }


def _source_result_status(item: dict) -> str:
    return "ready" if item.get("status") == "success" else "error"


def _verification_status(
    *, document_count: int, indexed_count: int, error_count: int, chunk_count: int
) -> str:
    if document_count <= 0:
        return "unknown"
    if error_count > 0 and indexed_count > 0:
        return "partial"
    if error_count > 0:
        return "failed"
    if indexed_count == document_count:
        return "indexed" if chunk_count > 0 else "indexed_empty"
    if indexed_count > 0:
        return "partial"
    return "failed"


def _merge_promotion_result(row: DepositFile, payload: dict) -> None:
    base = dict(row.promotion_result or {})
    base.update(payload)
    row.promotion_result = base


def _finalize_linked_deposit_files(
    db,
    *,
    job: WorkerJob,
    collection: KnowledgeCollection,
    file_names: list[str],
    document_metadata_by_name: dict[str, dict],
    source_results_by_name: dict[str, dict],
    ingest_result: dict,
) -> list[dict]:
    """Attach worker completion proof to Secure Deposit files linked to a job.

    ``deposit_files.status`` has only a coarse ``promoted`` value, so the
    detailed truth lives in ``promotion_result.indexing_status``. A file is only
    considered verified when the worker produced ready source rows for the
    documents that came from that deposit path.
    """

    rows = (
        db.query(DepositFile)
        .filter(
            DepositFile.worker_job_id == job.id,
            DepositFile.workspace_id == job.workspace_id,
        )
        .all()
    )
    if not rows:
        return []

    source_rows = {
        row.normalized_name: row
        for row in db.query(KnowledgeCollectionSource)
        .filter(KnowledgeCollectionSource.collection_id == collection.id)
        .all()
    }
    all_names = list(file_names)
    summaries: list[dict] = []
    for row in rows:
        document_names = [
            name
            for name in all_names
            if str(
                (document_metadata_by_name.get(name) or {}).get("source_deposit_path")
                or ""
            )
            == str(row.filename or "")
        ]
        if not document_names and len(rows) == 1:
            document_names = all_names

        documents: list[dict] = []
        indexed_count = 0
        error_count = 0
        chunk_count = 0
        for name in document_names:
            source_row = source_rows.get(name)
            item = source_results_by_name.get(name) or {}
            status = source_row.status if source_row else _source_result_status(item)
            chunks = int(
                (source_row.chunk_count if source_row else item.get("chunks_processed"))
                or 0
            )
            if status in {"ready", "indexed"}:
                indexed_count += 1
            elif status == "error":
                error_count += 1
            chunk_count += chunks
            documents.append(
                {
                    "document_name": name,
                    "status": status,
                    "chunk_count": chunks,
                    "error": (
                        source_row.last_error if source_row else item.get("error")
                    )
                    or None,
                }
            )

        indexing_status = _verification_status(
            document_count=len(document_names),
            indexed_count=indexed_count,
            error_count=error_count,
            chunk_count=chunk_count,
        )
        verification = {
            "worker_job_id": job.id,
            "job_status": "completed",
            "collection_slug": collection.slug,
            "document_count": len(document_names),
            "indexed_document_count": indexed_count,
            "error_document_count": error_count,
            "chunk_count": chunk_count,
            "ingest_failed_count": int(ingest_result.get("failed") or 0),
            "completed_at": datetime.utcnow().isoformat(),
            "documents": documents[:100],
            "truncated_documents": max(0, len(documents) - 100),
        }
        _merge_promotion_result(
            row,
            {
                "indexing_status": indexing_status,
                "indexing_verification": verification,
            },
        )
        summaries.append(
            {
                "file_id": row.id,
                "filename": row.filename,
                "indexing_status": indexing_status,
                "document_count": len(document_names),
                "chunk_count": chunk_count,
            }
        )
    return summaries


def _mark_linked_deposit_files_failed(
    db, *, job_id: str, workspace_id: str, error: str
) -> None:
    rows = (
        db.query(DepositFile)
        .filter(
            DepositFile.worker_job_id == job_id,
            DepositFile.workspace_id == workspace_id,
        )
        .all()
    )
    for row in rows:
        row.status = "received"
        _merge_promotion_result(
            row,
            {
                "indexing_status": "failed",
                "indexing_verification": {
                    "worker_job_id": job_id,
                    "job_status": "failed",
                    "error": error,
                    "completed_at": datetime.utcnow().isoformat(),
                },
            },
        )


def _record_wave_ledger_if_verified(
    db,
    *,
    workspace: Workspace,
    ingest_options: dict,
    deposit_summaries: list[dict],
) -> dict | None:
    wave_ledger = ingest_options.get("wave_ledger")
    if not isinstance(wave_ledger, dict):
        return None
    statuses = {str(item.get("indexing_status") or "") for item in deposit_summaries}
    verified_statuses = {"indexed"}
    if not deposit_summaries or not statuses <= verified_statuses:
        return {
            "status": "not_recorded",
            "reason": "deposit_indexing_not_fully_verified",
            "deposit_statuses": sorted(statuses),
        }
    from app.services.spl_wave_importer import record_wave_ledger

    filenames = [
        str(name) for name in wave_ledger.get("filenames") or [] if str(name).strip()
    ]
    collection_slug = str(wave_ledger.get("collection_slug") or "")
    wave_id = str(wave_ledger.get("wave_id") or ingest_options.get("wave_id") or "")
    if not filenames or not collection_slug or not wave_id:
        return {"status": "not_recorded", "reason": "wave_ledger_payload_incomplete"}
    record_wave_ledger(
        db,
        workspace=workspace,
        collection_slug=collection_slug,
        wave_id=wave_id,
        filenames=filenames,
        job_id=str(wave_ledger.get("job_id") or ""),
        new_document_count=int(wave_ledger.get("new_document_count") or 0),
    )
    return {
        "status": "recorded",
        "wave_id": wave_id,
        "collection_slug": collection_slug,
        "filenames": filenames,
    }


async def _materialize_ingested_text(
    *,
    collection: KnowledgeCollection,
    local_path: Path,
    workspace_id: str | None = None,
    ocr_overrides: dict | None = None,
):
    parser = DocumentParserFactory.get_parser(str(local_path))
    ocr_config = resolve_ocr_config_for_workspace(workspace_id, overrides=ocr_overrides)
    try:
        parsed = await parser.parse(str(local_path), ocr_config=ocr_config)
    except TypeError:
        parsed = await parser.parse(str(local_path))
    text = "\n\n".join(
        str(chunk.get("content", "")) for chunk in parsed.chunks if chunk.get("content")
    )
    get_object_store().write_text(ingested_key(collection, local_path.name), text)
    parsed.raw_content = ""
    return parsed


async def _run_document_ingest_index_async(job_id: str) -> dict:
    db = SessionLocal()
    temp_dir = Path(tempfile.mkdtemp(prefix="agentium-ingest-"))
    try:
        existing_job = db.query(WorkerJob).filter(WorkerJob.id == job_id).first()
        if existing_job and existing_job.status in ("completed", "failed", "cancelled"):
            return {
                "status": "skipped",
                "reason": "worker_job_already_terminal",
                "job_id": job_id,
                "job_status": existing_job.status,
            }
        job = update_job(
            db, job_id, status="running", progress=5, stage="copy_originals"
        )
        if not job or not job.collection_id:
            db.commit()
            raise ValueError(
                f"Worker job {job_id!r} not found or not linked to a collection"
            )

        ingest_options = dict((job.result or {}).get("ingest_options") or {})
        ingest_mode = str(ingest_options.get("mode") or "full")
        incremental_names = [
            str(name)
            for name in (ingest_options.get("document_names") or [])
            if str(name).strip()
        ]
        ocr_overrides = (
            ingest_options.get("document_ocr")
            if isinstance(ingest_options.get("document_ocr"), dict)
            else None
        )

        collection = (
            db.query(KnowledgeCollection)
            .filter(KnowledgeCollection.id == job.collection_id)
            .first()
        )
        if not collection:
            db.commit()
            raise ValueError(f"Collection for worker job {job_id!r} not found")

        workspace = db.query(Workspace).filter(Workspace.id == job.workspace_id).first()
        if not workspace:
            db.commit()
            raise ValueError(f"Workspace for worker job {job_id!r} not found")

        update_collection_status(db, collection.id, status="ingesting")
        db.commit()

        store = get_object_store()
        file_names = list(collection.document_names or [])
        if incremental_names:
            file_names = [
                name
                for name in incremental_names
                if name in set(collection.document_names or [])
            ]
        elif ingest_mode == "incremental" and collection.document_names:
            file_names = list(collection.document_names or [])
        document_metadata_by_name = _load_document_metadata_manifest(collection)
        if not file_names:
            prefix = store.key(collection.artifact_prefix, "original")
            file_names = [Path(k).name for k in store.list_keys(prefix)]
        if not file_names:
            raise ValueError(
                f"No original documents found for collection {collection.id}"
            )

        local_paths: list[str] = []
        for name in file_names:
            upsert_collection_source(
                db,
                collection=collection,
                filename=name,
                status="ingesting",
                origin=(document_metadata_by_name.get(name) or {}).get("origin")
                or "upload",
            )
            dest = temp_dir / Path(name).name
            legacy_name = (document_metadata_by_name.get(name) or {}).get(
                "legacy_document_name"
            )
            store.copy_to_local(
                resolve_original_key(
                    collection, name, legacy_name=legacy_name, store=store
                ),
                dest,
            )
            local_paths.append(str(dest))

        update_job(db, job_id, progress=20, stage="parsing")
        db.commit()

        parsed_documents_by_path: dict[str, object] = {}
        total_paths = max(1, len(local_paths))
        for index, path in enumerate(local_paths, start=1):
            try:
                parsed_documents_by_path[path] = await _materialize_ingested_text(
                    collection=collection,
                    local_path=Path(path),
                    workspace_id=workspace.id,
                    ocr_overrides=ocr_overrides,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "document ingest worker could not materialize ingested text",
                    filename=file_names[index - 1]
                    if index - 1 < len(file_names)
                    else Path(path).name,
                    error=str(exc),
                )
            if index == len(local_paths) or index % 25 == 0:
                parse_progress = 20 + int(20 * index / total_paths)
                update_job(
                    db,
                    job_id,
                    progress=min(40, parse_progress),
                    stage=f"parsing {index}/{total_paths}",
                )
                db.commit()

        app_settings = get_resolved_settings(workspace_id=workspace.id)
        collection.embedding_model = settings.embedding_model
        collection.chunking_method = app_settings.get(
            "ragChunkingMethod", "recursive_character"
        )
        collection.chunking_params = {
            "chunk_size": app_settings.get("ragChunkSize", 1000),
            "chunk_overlap": app_settings.get("ragChunkOverlap", 200),
        }
        update_collection_status(db, collection.id, status="embedding")
        update_job(db, job_id, progress=45, stage="embedding")
        db.commit()

        db_type = resolve_vector_db_type(app_settings)
        doc_service = DocumentService(
            collection_name=collection.slug,
            vector_db_type=db_type,
            workspace_slug=workspace.slug,
        )
        if ingest_mode != "incremental":
            # Worker jobs ingest the full collection snapshot. Clear stale vectors
            # first so a reindex cannot accumulate duplicate chunks with fresh temp
            # file-derived IDs.
            await doc_service.clear_all_documents()
            clear_collection_table_facts(
                db, workspace_id=workspace.id, collection_id=collection.id
            )
            clear_collection_document_facts(
                db, workspace_id=workspace.id, collection_id=collection.id
            )
            db.commit()
        update_job(db, job_id, progress=60, stage="indexing")
        db.commit()
        try:
            ingest_max_concurrency = int(
                getattr(settings, "document_ingest_max_concurrency", 8) or 8
            )
        except (TypeError, ValueError):
            ingest_max_concurrency = 8
        ingest_result = await doc_service.ingest_documents_batch(
            local_paths,
            workspace_id=workspace.id,
            collection_id=collection.id,
            collection_slug=collection.slug,
            document_metadata_by_name=document_metadata_by_name,
            parsed_documents_by_path=parsed_documents_by_path,
            document_ocr=ocr_overrides,
            max_concurrency=max(1, ingest_max_concurrency),
        )
        source_results_by_name: dict[str, dict] = {}
        for index, item in enumerate(ingest_result.get("results") or []):
            if not isinstance(item, dict):
                continue
            filename = (
                file_names[index] if index < len(file_names) else item.get("filename")
            )
            filename = filename or Path(str(item.get("document_id") or "")).name
            if not filename:
                continue
            status = "ready" if item.get("status") == "success" else "error"
            source_results_by_name[str(filename)] = item
            manifest_metadata = dict(document_metadata_by_name.get(str(filename)) or {})
            upsert_collection_source(
                db,
                collection=collection,
                filename=str(filename),
                status=status,
                origin=manifest_metadata.get("origin") or "upload",
                chunk_count=int(item.get("chunks_processed") or 0),
                source_metadata={
                    **manifest_metadata,
                    "document_id": item.get("document_id"),
                    "table_facts_processed": item.get("table_facts_processed"),
                    "document_facts_processed": item.get("document_facts_processed"),
                },
                last_error=item.get("error"),
            )
        db.flush()
        chunk_count = await doc_service.get_document_count()
        documents = await doc_service.list_documents()
        update_job(db, job_id, progress=85, stage="bm25")
        db.commit()
        bm25 = await rebuild_bm25_artifact(
            collection=collection,
            vector_db=doc_service.vector_db,
            store=store,
        )
        if bm25.get("status") == "deferred":
            bm25_job = create_worker_job(
                db,
                workspace_id=workspace.id,
                collection_id=collection.id,
                kind="bm25_rebuild",
            )
            db.commit()
            try:
                from app.services.worker_dispatch import dispatch_worker_job

                task_id = dispatch_worker_job(db, bm25_job)
                bm25 = {
                    **bm25,
                    "status": "queued",
                    "deferred": True,
                    "worker_job_id": bm25_job.id,
                    "celery_task_id": task_id,
                }
            except Exception as exc:
                update_job(
                    db,
                    bm25_job.id,
                    status="failed",
                    progress=100,
                    error=str(exc),
                    stage="bm25_dispatch_failed",
                )
                bm25 = {
                    **bm25,
                    "status": "failed",
                    "deferred": True,
                    "worker_job_id": bm25_job.id,
                    "error": str(exc),
                }
            db.commit()

        deposit_summaries = _finalize_linked_deposit_files(
            db,
            job=job,
            collection=collection,
            file_names=file_names,
            document_metadata_by_name=document_metadata_by_name,
            source_results_by_name=source_results_by_name,
            ingest_result=ingest_result,
        )
        wave_ledger_result = _record_wave_ledger_if_verified(
            db,
            workspace=workspace,
            ingest_options=ingest_options,
            deposit_summaries=deposit_summaries,
        )

        source_document_count = len(
            collection.document_names or file_names or documents
        )

        result = {
            "ingest": ingest_result,
            "bm25": bm25,
            "vector_db_type": db_type,
            "collection_slug": collection.slug,
            "chunk_count": chunk_count,
            "document_count": source_document_count,
            "indexed_document_count": len(documents),
            "deposit_files": deposit_summaries,
        }
        if wave_ledger_result:
            result["wave_ledger"] = wave_ledger_result
        update_collection_status(
            db,
            collection.id,
            status="ready",
            document_count=source_document_count,
            chunk_count=chunk_count,
            document_names=list(collection.document_names or file_names),
        )
        update_job(
            db, job_id, status="completed", progress=100, result=result, stage="ready"
        )
        db.commit()
        return result
    except Exception as exc:
        logger.exception("document ingest worker failed", job_id=job_id, error=str(exc))
        db.rollback()
        job = db.query(WorkerJob).filter(WorkerJob.id == job_id).first()
        if job and job.collection_id:
            update_collection_status(
                db, job.collection_id, status="error", last_error=str(exc)
            )
            _mark_linked_deposit_files_failed(
                db, job_id=job.id, workspace_id=job.workspace_id, error=str(exc)
            )
        update_job(db, job_id, status="failed", progress=100, error=str(exc))
        db.commit()
        raise
    finally:
        db.close()
        shutil.rmtree(temp_dir, ignore_errors=True)


def run_document_ingest_index(job_id: str) -> dict:
    """Synchronous entrypoint used by Celery and eager-mode tests."""
    return asyncio.run(_run_document_ingest_index_async(job_id))
