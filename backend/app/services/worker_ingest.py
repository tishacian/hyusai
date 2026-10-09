"""Worker-owned document ingestion and indexing workflows."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger
from app.core.settings_manager import get_resolved_settings
from app.db.base import SessionLocal
from app.models.knowledge_collection import (
    KnowledgeCollection,
    KnowledgeCollectionSource,
    WorkerJob,
)
from app.models.knowledge_document_fact import KnowledgeDocumentFact
from app.models.knowledge_table_fact import KnowledgeTableFact
from app.models.secure_deposit import DepositFile
from app.models.workspace import Workspace
from app.services.collection_source_backing import (
    SourceBackingError,
    copy_or_materialize_collection_source,
    source_locator,
)
from app.services.document_intelligence import clear_collection_document_facts
from app.services.document_parser.factory import DocumentParserFactory
from app.services.knowledge_collections import (
    create_worker_job,
    document_manifest_key,
    ingested_key,
    normalize_source_name,
    resolve_original_key,
    update_collection_status,
    update_job,
    upsert_collection_source,
)
from app.services.notice_wave_state import (
    NoticeWaveBaselineError,
    notice_wave_baseline,
    restore_notice_wave_baseline,
)
from app.services.object_store import get_object_store
from app.services.ocr import resolve_ocr_config_for_workspace
from app.services.rag.bm25_store import rebuild_bm25_artifact
from app.services.rag.document_service import DocumentService
from app.services.rag.vector_store_config import resolve_vector_db_type
from app.services.table_intelligence import clear_collection_table_facts

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


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _existing_content_hashes(db, collection: KnowledgeCollection) -> dict[tuple[str, str], str]:
    """Map ``(content_sha256, project scope)`` to an indexed filename.

    Identical manuals are legitimately delivered in several industrial
    projects.  A collection-wide hash key erases every project after the first
    one and makes exact ``project_code`` filters incomplete.  Scoped documents
    therefore deduplicate inside their project only; unscoped documents keep
    the historical collection-wide behaviour.
    """
    hashes: dict[tuple[str, str], str] = {}
    rows = (
        db.query(KnowledgeCollectionSource)
        .filter(
            KnowledgeCollectionSource.collection_id == collection.id,
            KnowledgeCollectionSource.status == "ready",
        )
        .all()
    )
    for row in rows:
        metadata = row.source_metadata or {}
        content_hash = str(metadata.get("content_sha256") or "")
        project_scope = str(metadata.get("project_code") or "").strip().upper() or "__unscoped__"
        key = (content_hash, project_scope)
        if content_hash and key not in hashes:
            hashes[key] = row.filename
    return hashes


def _incremental_document_inventory(db, collection: KnowledgeCollection) -> tuple[list[str], int]:
    """Build the source inventory without scrolling the full vector corpus.

    Incremental jobs only need the durable source ledger after indexing their
    private wave.  Keep pre-ledger ``document_names`` in their historical
    order, except when every matching ledger row explicitly marks a name as
    deleted, then append live ledger-only names deterministically.  A source
    is counted as physically indexed only when the ledger says ``ready`` or
    ``indexed``; error, in-flight and deduplicated rows remain in the source
    inventory but do not claim their own vectors.
    """

    rows = (
        db.query(
            KnowledgeCollectionSource.filename,
            KnowledgeCollectionSource.normalized_name,
            KnowledgeCollectionSource.status,
        )
        .filter(KnowledgeCollectionSource.collection_id == collection.id)
        .order_by(
            KnowledgeCollectionSource.filename.asc(),
            KnowledgeCollectionSource.id.asc(),
        )
        .all()
    )

    statuses_by_name: dict[str, set[str]] = {}
    live_name_by_normalized: dict[str, str] = {}
    ledger_order: list[str] = []
    for filename, normalized_name, status in rows:
        normalized = normalize_source_name(normalized_name or filename)
        statuses_by_name.setdefault(normalized, set()).add(str(status or ""))
        if status == "deleted" or normalized in live_name_by_normalized:
            continue
        live_name_by_normalized[normalized] = str(filename or normalized_name)
        ledger_order.append(normalized)

    inventory: list[str] = []
    inventory_normalized: set[str] = set()
    for raw_name in collection.document_names or []:
        name = str(raw_name)
        normalized = normalize_source_name(name)
        known_statuses = statuses_by_name.get(normalized)
        if known_statuses and known_statuses == {"deleted"}:
            continue
        inventory.append(name)
        inventory_normalized.add(normalized)

    for normalized in ledger_order:
        if normalized in inventory_normalized:
            continue
        inventory.append(live_name_by_normalized[normalized])
        inventory_normalized.add(normalized)

    indexed_count = sum(
        1
        for normalized, statuses in statuses_by_name.items()
        if normalized in inventory_normalized and statuses.intersection({"ready", "indexed"})
    )
    return inventory, indexed_count


def _verification_status(
    *,
    document_count: int,
    indexed_count: int,
    deduplicated_count: int,
    error_count: int,
    chunk_count: int,
) -> str:
    if document_count <= 0:
        return "unknown"
    if error_count > 0 and indexed_count > 0:
        return "partial"
    if error_count > 0:
        return "failed"
    if deduplicated_count == document_count:
        return "deduplicated"
    if indexed_count + deduplicated_count == document_count:
        return "indexed" if chunk_count > 0 else "indexed_empty"
    if indexed_count > 0 or deduplicated_count > 0:
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
    defer_promotion: bool = False,
) -> list[dict]:
    """Attach worker completion proof to Secure Deposit files linked to a job.

    ``deposit_files.status`` has only a coarse ``promoted`` value, so the
    detailed truth lives in ``promotion_result.indexing_status``. A file is only
    considered worker-verified when the worker produced ready source rows for
    the documents that came from that deposit path.  Governed Needlepunch
    waves additionally require the campaign runner's postflight.  In that
    mode ``defer_promotion`` keeps the coarse deposit status at ``received``;
    the runner is the only owner of the final ``promoted`` transition.
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

    source_row_list = (
        db.query(KnowledgeCollectionSource)
        .filter(KnowledgeCollectionSource.collection_id == collection.id)
        .all()
    )
    source_rows = {row.normalized_name: row for row in source_row_list}
    all_names = list(file_names)
    summaries: list[dict] = []
    for row in rows:
        if defer_promotion:
            if str(row.status or "") not in {"received", "promoted"}:
                raise SourceBackingError("secure_deposit_source_status_invalid")
            assigned_collection = str(row.promoted_collection_slug or "").strip()
            if assigned_collection and assigned_collection != str(collection.slug):
                raise SourceBackingError("secure_deposit_source_collection_mismatch")
        document_names = [
            name
            for name in all_names
            if str((document_metadata_by_name.get(name) or {}).get("source_deposit_path") or "")
            == str(row.filename or "")
        ]
        if not document_names and len(rows) == 1:
            document_names = all_names

        documents: list[dict] = []
        indexed_count = 0
        deduplicated_count = 0
        error_count = 0
        chunk_count = 0
        for name in document_names:
            source_row = source_rows.get(name)
            item = source_results_by_name.get(name) or {}
            status = source_row.status if source_row else _source_result_status(item)
            chunks = int(
                (source_row.chunk_count if source_row else item.get("chunks_processed")) or 0
            )
            if status in {"ready", "indexed"}:
                indexed_count += 1
            elif status == "deduplicated":
                deduplicated_count += 1
            elif status == "error":
                error_count += 1
            chunk_count += chunks
            documents.append(
                {
                    "document_name": name,
                    "status": status,
                    "chunk_count": chunks,
                    "error": (source_row.last_error if source_row else item.get("error")) or None,
                }
            )

        indexing_status = _verification_status(
            document_count=len(document_names),
            indexed_count=indexed_count,
            deduplicated_count=deduplicated_count,
            error_count=error_count,
            chunk_count=chunk_count,
        )
        promotion_state = dict(row.promotion_result or {})
        expected_raw = promotion_state.get("deposit_expected_document_count")
        cumulative_verified_count = indexed_count + deduplicated_count
        expected_document_count = len(document_names)
        awaiting_document_count = 0
        if expected_raw not in (None, ""):
            try:
                expected_document_count = max(1, int(expected_raw))
            except (TypeError, ValueError):
                expected_document_count = len(document_names)
            matching_rows: list[KnowledgeCollectionSource] = []
            expected_sha = str(row.sha256 or "").strip().lower()
            for source_row in source_row_list:
                metadata = dict(source_row.source_metadata or {})
                if str(metadata.get("source_deposit_file_id") or "") != str(row.id):
                    continue
                locator = metadata.get("source_locator") or {}
                locator_sha = (
                    str(locator.get("sha256") or "").strip().lower()
                    if isinstance(locator, dict)
                    else ""
                )
                if expected_sha and locator_sha and locator_sha != expected_sha:
                    continue
                matching_rows.append(source_row)
            cumulative_verified_count = len(
                {
                    source_row.normalized_name
                    for source_row in matching_rows
                    if source_row.status in {"ready", "indexed", "deduplicated"}
                }
            )
            awaiting_document_count = max(0, expected_document_count - cumulative_verified_count)
            if indexing_status in {"indexed", "deduplicated"} and awaiting_document_count > 0:
                # A safe ZIP may span several operator-approved waves. The
                # current job succeeded, but its DepositFile remains received
                # until every eligible member for the immutable archive SHA is
                # terminal in the collection ledger.
                indexing_status = "partial"
        verification = {
            "worker_job_id": job.id,
            "job_status": "completed",
            "collection_slug": collection.slug,
            "document_count": len(document_names),
            "indexed_document_count": indexed_count,
            "deduplicated_document_count": deduplicated_count,
            "error_document_count": error_count,
            "chunk_count": chunk_count,
            "expected_document_count": expected_document_count,
            "cumulative_verified_document_count": cumulative_verified_count,
            "awaiting_document_count": awaiting_document_count,
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
                **(
                    {
                        "status": "worker_completed_pending_postflight",
                        "postflight_status": "pending",
                    }
                    if defer_promotion
                    else {}
                ),
            },
        )
        if defer_promotion:
            row.status = "received"
            row.promoted_at = None
            row.promoted_by_user_id = None
            row.promoted_collection_slug = None
        elif indexing_status in {"indexed", "deduplicated"}:
            row.status = "promoted"
            row.promoted_at = row.promoted_at or datetime.utcnow()
            row.promoted_collection_slug = collection.slug
        summaries.append(
            {
                "file_id": row.id,
                "filename": row.filename,
                "indexing_status": indexing_status,
                "document_count": len(document_names),
                "chunk_count": chunk_count,
                "expected_document_count": expected_document_count,
                "cumulative_verified_document_count": cumulative_verified_count,
                "awaiting_document_count": awaiting_document_count,
            }
        )
    return summaries


def _mark_linked_deposit_files_failed(db, *, job_id: str, workspace_id: str, error: str) -> None:
    rows = (
        db.query(DepositFile)
        .filter(
            DepositFile.worker_job_id == job_id,
            DepositFile.workspace_id == workspace_id,
        )
        .all()
    )
    for row in rows:
        # A concurrent reviewer rejection is authoritative.  Worker failure
        # handling must never revive it as a received/promotable deposit.
        if str(row.status or "") in {"received", "promoted"}:
            row.status = "received"
            row.promoted_at = None
            row.promoted_by_user_id = None
            row.promoted_collection_slug = None
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


def _mark_incremental_sources_failed(
    db,
    *,
    collection_id: str,
    file_names: list[str],
    error: str,
) -> None:
    """Keep failed wave sources in the ledger so the same wave can resume."""

    names = {str(name) for name in file_names if str(name).strip()}
    if not names:
        return
    rows = (
        db.query(KnowledgeCollectionSource)
        .filter(KnowledgeCollectionSource.collection_id == collection_id)
        .all()
    )
    for row in rows:
        if row.filename in names or row.normalized_name in names:
            row.status = "error"
            row.last_error = error


def _rollback_incremental_facts(
    db,
    *,
    workspace_id: str,
    collection_id: str,
    document_ids: list[str],
) -> None:
    ids = {str(value) for value in document_ids if str(value).strip()}
    if not ids:
        return
    for model in (KnowledgeTableFact, KnowledgeDocumentFact):
        (
            db.query(model)
            .filter(
                model.workspace_id == workspace_id,
                model.collection_id == collection_id,
                model.document_id.in_(ids),
            )
            .delete(synchronize_session=False)
        )


async def _rollback_incremental_vectors(
    doc_service: DocumentService | None,
    *,
    document_ids: list[str],
    wave_id: str,
    expected_chunk_count: int | None = None,
) -> bool:
    """Remove only documents successfully written by the current wave.

    Every Needlepunch logical filename is unique and its chunks also carry the
    immutable ``wave_id`` payload.  The worker records the returned document
    ids as it indexes, then deletes exactly those ids if a later step fails.
    This preserves the pre-existing collection even when Qdrant/BM25 fails
    after a partial upsert.
    """

    ids = list(dict.fromkeys(str(value) for value in document_ids if str(value).strip()))
    if doc_service is None:
        # No vector client was created, therefore the failure happened before
        # this worker could write any points.
        return not ids
    deletion_confirmed = False
    if wave_id and hasattr(doc_service, "delete_by_metadata"):
        try:
            if await doc_service.delete_by_metadata({"wave_id": wave_id}):
                deletion_confirmed = True
        except Exception as exc:  # noqa: BLE001 - point-id fallback remains.
            logger.warning(
                "incremental wave filtered rollback unavailable",
                wave_id=wave_id,
                error=str(exc),
            )
    if not deletion_confirmed:
        if not hasattr(doc_service, "delete_document"):
            return False
        if not ids:
            # A vector client existed but neither a filtered delete nor a
            # concrete document id can prove that a partially-written batch
            # was removed.
            return False
        deletion_confirmed = True
        for document_id in ids:
            try:
                deleted = await doc_service.delete_document(document_id)
                if deleted is False:
                    deletion_confirmed = False
                    logger.error(
                        "incremental wave vector rollback was not confirmed",
                        wave_id=wave_id,
                        document_id=document_id,
                    )
            except Exception as exc:  # noqa: BLE001 - retain the original failure.
                deletion_confirmed = False
                logger.exception(
                    "incremental wave vector rollback failed",
                    wave_id=wave_id,
                    document_id=document_id,
                    error=str(exc),
                )
    if not deletion_confirmed:
        return False
    if expected_chunk_count is None:
        return True
    if not hasattr(doc_service, "get_document_count"):
        logger.error(
            "incremental rollback cannot prove baseline cardinality",
            wave_id=wave_id,
            expected_chunk_count=expected_chunk_count,
        )
        return False
    try:
        current_chunk_count = int(await doc_service.get_document_count())
    except Exception as exc:  # noqa: BLE001 - rollback remains unconfirmed.
        logger.exception(
            "incremental rollback cardinality check failed",
            wave_id=wave_id,
            expected_chunk_count=expected_chunk_count,
            error=str(exc),
        )
        return False
    if current_chunk_count != int(expected_chunk_count):
        logger.error(
            "incremental rollback did not restore baseline cardinality",
            wave_id=wave_id,
            expected_chunk_count=expected_chunk_count,
            current_chunk_count=current_chunk_count,
        )
        return False
    return True


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
    verified_statuses = {"indexed", "deduplicated"}
    if not deposit_summaries or not statuses <= verified_statuses:
        return {
            "status": "not_recorded",
            "reason": "deposit_indexing_not_fully_verified",
            "deposit_statuses": sorted(statuses),
        }
    from app.services.spl_wave_importer import record_wave_ledger

    filenames = [str(name) for name in wave_ledger.get("filenames") or [] if str(name).strip()]
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
    ingest_options: dict = {}
    ingest_mode = "full"
    requested_file_names: list[str] = []
    indexed_document_ids: list[str] = []
    doc_service: DocumentService | None = None
    source_failure: dict | None = None
    try:
        existing_job = db.query(WorkerJob).filter(WorkerJob.id == job_id).first()
        if existing_job and existing_job.status in ("completed", "failed", "cancelled"):
            return {
                "status": "skipped",
                "reason": "worker_job_already_terminal",
                "job_id": job_id,
                "job_status": existing_job.status,
            }
        claim_time = datetime.utcnow()
        claimed = (
            db.query(WorkerJob)
            .filter(WorkerJob.id == job_id, WorkerJob.status == "queued")
            .update(
                {
                    WorkerJob.status: "running",
                    WorkerJob.progress: 5,
                    WorkerJob.started_at: claim_time,
                    WorkerJob.updated_at: claim_time,
                },
                synchronize_session=False,
            )
        )
        if claimed != 1:
            db.rollback()
            current = db.query(WorkerJob).filter(WorkerJob.id == job_id).first()
            return {
                "status": "skipped",
                "reason": "worker_job_not_claimable",
                "job_id": job_id,
                "job_status": current.status if current else "missing",
            }
        db.commit()
        job = update_job(db, job_id, progress=5, stage="copy_originals")
        if not job or not job.collection_id:
            db.commit()
            raise ValueError(f"Worker job {job_id!r} not found or not linked to a collection")

        ingest_options = dict((job.result or {}).get("ingest_options") or {})
        ingest_mode = str(ingest_options.get("mode") or "full")
        requires_notice_postflight = (
            ingest_mode == "incremental"
            and str(ingest_options.get("source_profile") or "") == "needlepunch"
        )
        incremental_names = [
            str(name) for name in (ingest_options.get("document_names") or []) if str(name).strip()
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

        from app.services.rag.embedding_generation import binding_for

        if collection.pending_generation:
            raise RuntimeError("RAG_REINDEX_IN_PROGRESS")
        embedding_binding = binding_for(collection)
        job.result = {**(job.result or {}), "embedding_binding": embedding_binding}

        workspace = db.query(Workspace).filter(Workspace.id == job.workspace_id).first()
        if not workspace:
            db.commit()
            raise ValueError(f"Workspace for worker job {job_id!r} not found")

        if ingest_mode == "incremental":
            if (
                str(ingest_options.get("source_profile") or "") == "needlepunch"
                and collection.status != "ready"
            ):
                raise RuntimeError("Needlepunch incremental ingestion requires a ready collection")
            # Incremental ingestion is additive: the existing Qdrant corpus is
            # still authoritative and must remain available to chat while this
            # job parses and embeds its private wave.
        else:
            update_collection_status(db, collection.id, status="ingesting")
        db.commit()

        store = get_object_store()
        file_names = list(collection.document_names or [])
        if incremental_names:
            file_names = [
                name for name in incremental_names if name in set(collection.document_names or [])
            ]
        elif ingest_mode == "incremental" and collection.document_names:
            file_names = list(collection.document_names or [])
        document_metadata_by_name = _load_document_metadata_manifest(collection)
        if not file_names:
            prefix = store.key(collection.artifact_prefix, "original")
            file_names = [Path(k).name for k in store.list_keys(prefix)]
        if not file_names:
            source_failure = {"code": "originals_missing"}
            raise ValueError(f"No original documents found for collection {collection.id}")

        requested_file_names = list(file_names)
        local_paths: list[str] = []
        for name in file_names:
            manifest_entry = document_metadata_by_name.get(name) or {}
            upsert_collection_source(
                db,
                collection=collection,
                filename=name,
                status="ingesting",
                origin=manifest_entry.get("origin") or "upload",
            )
            dest = temp_dir / Path(name).name
            legacy_name = manifest_entry.get("legacy_document_name")

            def copy_legacy_source(destination: Path) -> None:
                nonlocal source_failure
                key = resolve_original_key(collection, name, legacy_name=legacy_name, store=store)
                try:
                    store.copy_to_local(key, destination)
                except FileNotFoundError:
                    # A missing temporary destination must not be diagnosed as
                    # a missing original. A failed presence check is inconclusive.
                    try:
                        missing = not store.exists(key)
                    except Exception:
                        missing = False
                    if missing:
                        source_failure = {"code": "original_source_missing", "filename": name}
                    raise

            copy_or_materialize_collection_source(
                db,
                workspace_id=workspace.id,
                metadata=manifest_entry,
                destination=dest,
                copy_object_store_source=copy_legacy_source,
                expected_worker_job_id=job.id,
                expected_collection_slug=collection.slug,
                allowed_statuses={"received", "promoted"},
            )
            local_paths.append(str(dest))

        # Content-hash dedup: identical bytes under another name are not
        # re-parsed/re-embedded. The hash also rides the manifest, so every
        # chunk carries ``content_sha256`` for provenance.
        db.flush()  # sessions run autoflush=False; make the rows above queryable
        existing_hashes = (
            _existing_content_hashes(db, collection) if ingest_mode == "incremental" else {}
        )
        batch_hashes: dict[tuple[str, str], str] = {}
        kept_names: list[str] = []
        kept_paths: list[str] = []
        deduplicated_names: list[str] = []
        for name, path in zip(file_names, local_paths):
            try:
                content_hash = _sha256_file(Path(path))
            except OSError:
                kept_names.append(name)
                kept_paths.append(path)
                continue
            manifest_entry = document_metadata_by_name.setdefault(name, {})
            locator = source_locator(manifest_entry)
            locator_kind = str((locator or {}).get("kind") or "")
            expected_hash_key = (
                "member_sha256" if locator_kind == "secure_deposit_zip_member" else "sha256"
            )
            expected_hash = str((locator or {}).get(expected_hash_key) or "").strip().lower()
            if expected_hash and expected_hash != content_hash:
                raise SourceBackingError("secure_deposit_source_content_changed")
            manifest_entry["content_sha256"] = content_hash
            project_scope = (
                str(manifest_entry.get("project_code") or "").strip().upper() or "__unscoped__"
            )
            dedup_key = (content_hash, project_scope)
            canonical = batch_hashes.get(dedup_key) or existing_hashes.get(dedup_key)
            if canonical and canonical != name:
                logger.info(
                    "document ingest worker skipped duplicate content",
                    filename=name,
                    duplicate_of=canonical,
                    collection_id=collection.id,
                )
                try:
                    upsert_collection_source(
                        db,
                        collection=collection,
                        filename=name,
                        status="deduplicated",
                        origin=manifest_entry.get("origin") or "upload",
                        source_metadata={
                            **manifest_entry,
                            "content_sha256": content_hash,
                            "duplicate_of": canonical,
                        },
                    )
                except Exception as exc:  # noqa: BLE001
                    # Databases created before the 'deduplicated' status was
                    # added still enforce the old CHECK constraint. The dedup
                    # itself stands; only the ledger entry is skipped.
                    db.rollback()
                    logger.warning(
                        "could not record deduplicated source",
                        filename=name,
                        error=str(exc),
                    )
                deduplicated_names.append(name)
                continue
            batch_hashes[dedup_key] = name
            kept_names.append(name)
            kept_paths.append(path)
        file_names = kept_names
        local_paths = kept_paths
        if not local_paths:
            ingest_result = {
                "total": len(requested_file_names),
                "successful": 0,
                "failed": 0,
                "deduplicated": len(deduplicated_names),
                "results": [],
            }
            deposit_summaries = _finalize_linked_deposit_files(
                db,
                job=job,
                collection=collection,
                file_names=requested_file_names,
                document_metadata_by_name=document_metadata_by_name,
                source_results_by_name={},
                ingest_result=ingest_result,
                defer_promotion=requires_notice_postflight,
            )
            wave_ledger_result = _record_wave_ledger_if_verified(
                db,
                workspace=workspace,
                ingest_options=ingest_options,
                deposit_summaries=deposit_summaries,
            )
            result = {
                "ingest": ingest_result,
                "bm25": {"status": "skipped", "reason": "duplicate_only_wave"},
                "collection_slug": collection.slug,
                "chunk_count": int(collection.chunk_count or 0),
                "document_count": len(collection.document_names or []),
                "indexed_document_count": 0,
                "deposit_files": deposit_summaries,
                "ingest_options": ingest_options,
                "postflight_required": requires_notice_postflight,
                "postflight_status": ("pending" if requires_notice_postflight else "not_required"),
            }
            if wave_ledger_result:
                result["wave_ledger"] = wave_ledger_result
            update_collection_status(
                db,
                collection.id,
                status="ready",
                last_error=None,
                document_count=len(collection.document_names or []),
                chunk_count=int(collection.chunk_count or 0),
            )
            update_job(
                db,
                job_id,
                status="completed",
                progress=100,
                result=result,
                stage="ready_duplicate_only",
            )
            db.commit()
            return result

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
        collection.chunking_method = app_settings.get("ragChunkingMethod", "recursive_character")
        collection.chunking_params = {
            "chunk_size": app_settings.get("ragChunkSize", 1000),
            "chunk_overlap": app_settings.get("ragChunkOverlap", 200),
        }
        if ingest_mode != "incremental":
            update_collection_status(db, collection.id, status="embedding")
        update_job(db, job_id, progress=45, stage="embedding")
        db.commit()

        db_type = resolve_vector_db_type(app_settings)
        doc_service = DocumentService(
            collection_name=collection.slug,
            vector_db_type=db_type,
            workspace_slug=workspace.slug,
            embedding_binding=embedding_binding,
        )
        if ingest_mode != "incremental":
            # Worker jobs ingest the full collection snapshot. Clear stale vectors
            # first so a reindex cannot accumulate duplicate chunks with fresh temp
            # file-derived IDs.
            await doc_service.clear_all_documents()
            clear_collection_table_facts(db, workspace_id=workspace.id, collection_id=collection.id)
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
        indexed_document_ids = [
            str(item.get("document_id"))
            for item in (ingest_result.get("results") or [])
            if isinstance(item, dict) and item.get("document_id")
        ]
        if (
            ingest_mode == "incremental"
            and str(ingest_options.get("source_profile") or "") == "needlepunch"
        ):
            failed_count = int(ingest_result.get("failed") or 0)
            zero_chunk_names = [
                file_names[index]
                for index, item in enumerate(ingest_result.get("results") or [])
                if isinstance(item, dict)
                and item.get("status") == "success"
                and int(item.get("chunks_processed") or 0) <= 0
                and index < len(file_names)
            ]
            if failed_count or zero_chunk_names:
                reasons: list[str] = []
                if failed_count:
                    reasons.append(f"{failed_count} document(s) failed")
                if zero_chunk_names:
                    reasons.append("zero chunks for " + ", ".join(zero_chunk_names[:10]))
                raise RuntimeError(
                    "Needlepunch incremental wave verification failed: " + "; ".join(reasons)
                )
        source_results_by_name: dict[str, dict] = {}
        for index, item in enumerate(ingest_result.get("results") or []):
            if not isinstance(item, dict):
                continue
            filename = file_names[index] if index < len(file_names) else item.get("filename")
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
        if ingest_mode == "incremental":
            inventory_document_names, indexed_document_count = _incremental_document_inventory(
                db, collection
            )
        else:
            documents = await doc_service.list_documents()
            indexed_document_count = len(documents)
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
            file_names=requested_file_names,
            document_metadata_by_name=document_metadata_by_name,
            source_results_by_name=source_results_by_name,
            ingest_result=ingest_result,
            defer_promotion=requires_notice_postflight,
        )
        wave_ledger_result = _record_wave_ledger_if_verified(
            db,
            workspace=workspace,
            ingest_options=ingest_options,
            deposit_summaries=deposit_summaries,
        )

        if ingest_mode == "incremental":
            source_document_names = inventory_document_names
            source_document_count = len(source_document_names)
        else:
            source_document_names = list(collection.document_names or file_names)
            source_document_count = len(collection.document_names or file_names or documents)

        result = {
            "ingest": ingest_result,
            "bm25": bm25,
            "vector_db_type": db_type,
            "collection_slug": collection.slug,
            "chunk_count": chunk_count,
            "document_count": source_document_count,
            "indexed_document_count": indexed_document_count,
            "deposit_files": deposit_summaries,
            "ingest_options": ingest_options,
            "postflight_required": requires_notice_postflight,
            "postflight_status": ("pending" if requires_notice_postflight else "not_required"),
        }
        if wave_ledger_result:
            result["wave_ledger"] = wave_ledger_result
        update_collection_status(
            db,
            collection.id,
            status="ready",
            document_count=source_document_count,
            chunk_count=chunk_count,
            document_names=source_document_names,
        )
        update_job(db, job_id, status="completed", progress=100, result=result, stage="ready")
        db.commit()
        return result
    except Exception as exc:
        logger.exception("document ingest worker failed", job_id=job_id, error=str(exc))
        db.rollback()
        job = db.query(WorkerJob).filter(WorkerJob.id == job_id).first()
        if job and job.collection_id:
            failed_options = dict((job.result or {}).get("ingest_options") or {})
            if str(failed_options.get("mode") or "full") == "incremental":
                is_needlepunch = str(failed_options.get("source_profile") or "") == "needlepunch"
                baseline_error: NoticeWaveBaselineError | None = None
                expected_chunk_count: int | None = None
                if is_needlepunch:
                    try:
                        _names, _documents, expected_chunk_count = notice_wave_baseline(
                            failed_options
                        )
                    except NoticeWaveBaselineError as baseline_exc:
                        baseline_error = baseline_exc
                vector_cleanup_confirmed = await _rollback_incremental_vectors(
                    doc_service,
                    document_ids=indexed_document_ids,
                    wave_id=str(failed_options.get("wave_id") or ""),
                    expected_chunk_count=expected_chunk_count,
                )
                rollback_confirmed = vector_cleanup_confirmed and baseline_error is None
                if rollback_confirmed:
                    # The failed wave is gone; the pre-existing corpus remains
                    # byte-for-byte authoritative and can keep serving chat.
                    if not is_needlepunch:
                        update_collection_status(
                            db,
                            job.collection_id,
                            status="ready",
                            last_error=None,
                        )
                    else:
                        failed_collection = (
                            db.query(KnowledgeCollection)
                            .filter(KnowledgeCollection.id == job.collection_id)
                            .first()
                        )
                        try:
                            if failed_collection is None:
                                raise NoticeWaveBaselineError("notice_wave_collection_missing")
                            baseline_names, baseline_documents, baseline_chunks = (
                                restore_notice_wave_baseline(
                                    failed_collection,
                                    failed_options,
                                )
                            )
                        except NoticeWaveBaselineError as baseline_exc:
                            update_collection_status(
                                db,
                                job.collection_id,
                                status="error",
                                last_error=str(baseline_exc),
                            )
                        else:
                            update_collection_status(
                                db,
                                job.collection_id,
                                status="ready",
                                last_error=None,
                                document_names=baseline_names,
                                document_count=baseline_documents,
                                chunk_count=baseline_chunks,
                            )
                else:
                    # Never expose a collection that may still contain points
                    # from a rejected partial wave. Operator recovery now
                    # requires the snapshot/runbook path.
                    update_collection_status(
                        db,
                        job.collection_id,
                        status="error",
                        last_error=(
                            str(baseline_error)
                            if baseline_error is not None
                            else (
                                "incremental rollback was not confirmed; "
                                "baseline chunk cardinality was not restored; "
                                f"failed wave={failed_options.get('wave_id') or 'unknown'}"
                            )
                        ),
                    )
                _mark_incremental_sources_failed(
                    db,
                    collection_id=job.collection_id,
                    file_names=requested_file_names
                    or [str(name) for name in (failed_options.get("document_names") or [])],
                    error=str(exc),
                )
                _rollback_incremental_facts(
                    db,
                    workspace_id=job.workspace_id,
                    collection_id=job.collection_id,
                    document_ids=indexed_document_ids,
                )
            else:
                update_collection_status(db, job.collection_id, status="error", last_error=str(exc))
            _mark_linked_deposit_files_failed(
                db, job_id=job.id, workspace_id=job.workspace_id, error=str(exc)
            )
        failure_result = (
            {**(job.result or {}), "source_failure": source_failure}
            if job and source_failure
            else None
        )
        update_job(db, job_id, status="failed", progress=100, error=str(exc), result=failure_result)
        db.commit()
        raise
    finally:
        db.close()
        shutil.rmtree(temp_dir, ignore_errors=True)


def run_document_ingest_index(job_id: str) -> dict:
    """Synchronous entrypoint used by Celery and eager-mode tests."""
    return asyncio.run(_run_document_ingest_index_async(job_id))
