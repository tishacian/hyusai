"""Fail-closed recovery for a rejected completed notice wave.

The ingestion worker already rolls back failures raised while it owns the
wave.  This module covers the narrower case where the worker completed but a
runner postflight gate subsequently rejects the wave.  Recovery is allowed
only when the immutable ``wave_id`` deletion is confirmed and the Qdrant
collection returns to its exact pre-wave cardinality.  Otherwise the
collection remains quarantined in ``error`` for snapshot-based recovery.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from app.core.settings_manager import get_resolved_settings
from app.models.knowledge_collection import (
    KnowledgeCollection,
    KnowledgeCollectionSource,
    WorkerJob,
)
from app.models.knowledge_document_fact import KnowledgeDocumentFact
from app.models.knowledge_table_fact import KnowledgeTableFact
from app.models.secure_deposit import DepositFile
from app.models.workspace import Workspace
from app.services.audit_logger import emit_audit_event
from app.services.knowledge_collections import update_job
from app.services.notice_campaign_guard import (
    _assert_project_filter_isolation,
    _qdrant_collection_status,
    verify_notice_collection_gate,
)
from app.services.object_store import get_object_store
from app.services.rag.bm25_store import bm25_artifact_key
from app.services.rag.document_service import DocumentService
from app.services.rag.vector_store_config import resolve_vector_db_type


def quarantine_notice_collection(
    db: DBSession,
    *,
    workspace: Workspace,
    collection: KnowledgeCollection,
    wave_id: str,
    reason: str,
    actor: str,
) -> dict[str, Any]:
    """Quarantine a collection when a no-op wave proves ledger corruption."""

    message = f"notice campaign gate rejected wave={wave_id}: {reason}"
    collection.status = "error"
    collection.last_error = message
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="notice.collection.quarantined",
        actor=actor,
        severity="warning",
        details={
            "collection_slug": collection.slug,
            "wave_id": wave_id,
            "reason": reason,
        },
    )
    db.commit()
    return {"status": "quarantined", "wave_id": wave_id, "reason": reason}


def _quarantine(
    db: DBSession,
    *,
    workspace: Workspace,
    collection: KnowledgeCollection,
    job: WorkerJob,
    wave_id: str,
    reason: str,
    actor: str,
) -> None:
    message = f"notice campaign postflight rejected wave={wave_id}: {reason}"
    collection.status = "error"
    collection.last_error = message
    update_job(
        db,
        job.id,
        status="failed",
        progress=100,
        error=message,
        result={
            **dict(job.result or {}),
            "postflight_recovery": {
                "status": "quarantined",
                "wave_id": wave_id,
                "reason": reason,
            },
        },
        stage="postflight_rejected",
    )
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="notice.wave.postflight_rejected",
        actor=actor,
        severity="warning",
        details={
            "collection_slug": collection.slug,
            "job_id": job.id,
            "wave_id": wave_id,
            "reason": reason,
        },
    )
    db.commit()


def _delete_wave_facts(
    db: DBSession,
    *,
    workspace_id: str,
    collection_id: str,
    document_ids: set[str],
    document_names: set[str],
) -> None:
    for model in (KnowledgeTableFact, KnowledgeDocumentFact):
        predicates = []
        if document_ids:
            predicates.append(model.document_id.in_(sorted(document_ids)))
        if document_names:
            predicates.append(model.document_filename.in_(sorted(document_names)))
        if not predicates:
            continue
        (
            db.query(model)
            .filter(
                model.workspace_id == workspace_id,
                model.collection_id == collection_id,
                or_(*predicates),
            )
            .delete(synchronize_session=False)
        )


def _reset_wave_ledger(
    db: DBSession,
    *,
    workspace: Workspace,
    collection: KnowledgeCollection,
    job: WorkerJob,
    document_names: set[str],
    wave_id: str,
    reason: str,
    baseline_document_names: list[str],
    baseline_document_count: int,
    baseline_chunk_count: int,
) -> None:
    rows = (
        db.query(KnowledgeCollectionSource)
        .filter(
            KnowledgeCollectionSource.collection_id == collection.id,
            KnowledgeCollectionSource.normalized_name.in_(sorted(document_names)),
        )
        .all()
        if document_names
        else []
    )
    document_ids: set[str] = set()
    deposit_ids: set[str] = set()
    reset_names: set[str] = set()
    for row in rows:
        metadata = dict(row.source_metadata or {})
        if str(metadata.get("wave_id") or "") != wave_id:
            continue
        document_id = str(metadata.get("document_id") or "").strip()
        deposit_id = str(metadata.get("source_deposit_file_id") or "").strip()
        if document_id:
            document_ids.add(document_id)
        if deposit_id:
            deposit_ids.add(deposit_id)
        reset_names.add(row.normalized_name)
        row.status = "error"
        row.chunk_count = 0
        row.indexed_at = None
        row.last_error = f"postflight rollback: {reason}"
        row.source_metadata = {
            **metadata,
            "postflight_rollback": {
                "wave_id": wave_id,
                "reason": reason,
                "rolled_back_at": datetime.utcnow().isoformat(),
            },
        }

    if reset_names != document_names:
        missing = sorted(document_names - reset_names)
        raise RuntimeError(
            "postflight_wave_ledger_scope_mismatch:" + ",".join(missing[:10])
        )
    missing_deposit_ids = sorted(
        row.normalized_name
        for row in rows
        if not str((row.source_metadata or {}).get("source_deposit_file_id") or "").strip()
    )
    if missing_deposit_ids:
        raise RuntimeError(
            "postflight_wave_deposit_id_missing:"
            + ",".join(missing_deposit_ids[:10])
        )

    _delete_wave_facts(
        db,
        workspace_id=workspace.id,
        collection_id=collection.id,
        document_ids=document_ids,
        document_names=reset_names,
    )

    if deposit_ids:
        deposits = (
            db.query(DepositFile)
            .filter(
                DepositFile.workspace_id == workspace.id,
                DepositFile.id.in_(sorted(deposit_ids)),
            )
            .all()
        )
        deposits_by_id = {str(deposit.id): deposit for deposit in deposits}
        missing_deposits = sorted(deposit_ids - set(deposits_by_id))
        if missing_deposits:
            raise RuntimeError(
                "postflight_wave_deposit_missing:"
                + ",".join(missing_deposits[:10])
            )
        wrong_job = sorted(
            deposit_id
            for deposit_id, deposit in deposits_by_id.items()
            if str(deposit.worker_job_id or "") != str(job.id)
        )
        if wrong_job:
            raise RuntimeError(
                "postflight_wave_deposit_job_mismatch:"
                + ",".join(wrong_job[:10])
            )
        for deposit in deposits:
            promotion = dict(deposit.promotion_result or {})
            promotion.update(
                {
                    "status": "received",
                    "indexing_status": "failed",
                    "postflight_rollback": {
                        "worker_job_id": job.id,
                        "wave_id": wave_id,
                        "reason": reason,
                        "rolled_back_at": datetime.utcnow().isoformat(),
                    },
                }
            )
            deposit.status = "received"
            deposit.promoted_at = None
            deposit.promoted_by_user_id = None
            deposit.promoted_collection_slug = None
            deposit.promotion_result = promotion

    collection.document_names = [str(name) for name in baseline_document_names]
    collection.document_count = int(baseline_document_count)
    collection.chunk_count = int(baseline_chunk_count)


async def rollback_rejected_notice_wave(
    db: DBSession,
    *,
    workspace: Workspace,
    collection: KnowledgeCollection,
    job: WorkerJob,
    document_names: list[str],
    wave_id: str,
    reason: str,
    actor: str,
    baseline_document_names: list[str],
    baseline_document_count: int,
    baseline_chunk_count: int,
    baseline_validation_names: list[str] | None = None,
    snapshot_ref: str | None = None,
) -> dict[str, Any]:
    """Rollback one just-completed wave or quarantine the collection.

    The initial quarantine transaction is committed before touching Qdrant so
    that a process crash can never leave a rejected collection advertised as
    ready.  A successful cleanup explicitly restores ``ready`` afterwards.
    """

    names = {str(name) for name in document_names if str(name or "").strip()}
    if not wave_id:
        raise ValueError("postflight recovery requires wave_id")
    if job.collection_id != collection.id or job.workspace_id != workspace.id:
        raise ValueError("postflight recovery job scope mismatch")
    if job.status != "completed":
        raise ValueError("postflight recovery only accepts a completed worker job")

    job_options = dict((job.result or {}).get("ingest_options") or {})
    job_wave_id = str(job_options.get("wave_id") or "")
    job_names = {
        str(name)
        for name in (job_options.get("document_names") or [])
        if str(name or "").strip()
    }
    ledger_rows = (
        db.query(KnowledgeCollectionSource)
        .filter(KnowledgeCollectionSource.collection_id == collection.id)
        .all()
    )
    scoped_rows = [
        row
        for row in ledger_rows
        if str((row.source_metadata or {}).get("wave_id") or "") == wave_id
    ]
    ledger_names = {row.normalized_name for row in scoped_rows}
    scope_errors: list[str] = []
    if job_wave_id != wave_id:
        scope_errors.append(f"job_wave_id:{job_wave_id or 'missing'}")
    if job.kind != "document_ingest_index":
        scope_errors.append(f"job_kind:{job.kind or 'missing'}")
    if str(job_options.get("mode") or "") != "incremental":
        scope_errors.append("job_mode_not_incremental")
    if str(job_options.get("source_profile") or "") != "needlepunch":
        scope_errors.append("job_source_profile_not_needlepunch")
    if names != job_names:
        scope_errors.append("caller_job_document_names_mismatch")
    if job_names != ledger_names:
        scope_errors.append("job_ledger_document_names_mismatch")
    if not names:
        scope_errors.append("document_names_missing")
    if scope_errors:
        _quarantine(
            db,
            workspace=workspace,
            collection=collection,
            job=job,
            wave_id=wave_id,
            reason=f"{reason}; " + "; ".join(scope_errors),
            actor=actor,
        )
        return {
            "status": "quarantined",
            "wave_id": wave_id,
            "job_id": job.id,
            "error": "postflight_recovery_scope_mismatch",
        }

    project_codes = {
        str((row.source_metadata or {}).get("project_code") or "").strip().upper()
        for row in scoped_rows
        if str((row.source_metadata or {}).get("project_code") or "").strip()
    }
    dependent_names = {
        str((row.source_metadata or {}).get("duplicate_of") or "").strip()
        for row in scoped_rows
        if row.status == "deduplicated"
        and str((row.source_metadata or {}).get("duplicate_of") or "").strip()
    } - ledger_names
    external_dependents = [
        row.normalized_name
        for row in ledger_rows
        if row.normalized_name not in ledger_names
        and row.status == "deduplicated"
        and str((row.source_metadata or {}).get("duplicate_of") or "").strip()
        in ledger_names
    ]
    if external_dependents:
        _quarantine(
            db,
            workspace=workspace,
            collection=collection,
            job=job,
            wave_id=wave_id,
            reason=(
                f"{reason}; rollback_has_external_dedup_dependents:"
                + ",".join(sorted(external_dependents)[:10])
            ),
            actor=actor,
        )
        return {
            "status": "quarantined",
            "wave_id": wave_id,
            "job_id": job.id,
            "error": "postflight_recovery_has_external_dedup_dependents",
        }

    _quarantine(
        db,
        workspace=workspace,
        collection=collection,
        job=job,
        wave_id=wave_id,
        reason=reason,
        actor=actor,
    )

    report: dict[str, Any] = {
        "status": "quarantined",
        "wave_id": wave_id,
        "job_id": job.id,
        "baseline_chunk_count": int(baseline_chunk_count),
    }
    try:
        app_settings = get_resolved_settings(workspace_id=workspace.id)
        db_type = resolve_vector_db_type(app_settings)
        if str(db_type).strip().lower() != "qdrant":
            raise RuntimeError(f"authoritative_collection_not_qdrant:{db_type}")
        service = DocumentService(
            collection_name=collection.slug,
            vector_db_type=db_type,
            workspace_slug=workspace.slug,
        )
        deletion_confirmed = await service.delete_by_metadata({"wave_id": wave_id})
        remaining_chunks = int(await service.get_document_count())
        qdrant_status = _qdrant_collection_status(service.vector_db)
        report.update(
            {
                "wave_delete_confirmed": bool(deletion_confirmed),
                "qdrant_chunk_count_after": remaining_chunks,
                "qdrant_status_after": qdrant_status,
            }
        )
        if not deletion_confirmed:
            raise RuntimeError("wave_vector_delete_unconfirmed")
        if remaining_chunks != int(baseline_chunk_count):
            raise RuntimeError(
                "postflight_rollback_chunk_drift:"
                f"{remaining_chunks}!={int(baseline_chunk_count)}"
            )
        isolation_counts = await _assert_project_filter_isolation(
            service.vector_db,
            project_codes=sorted(project_codes),
        )

        _reset_wave_ledger(
            db,
            workspace=workspace,
            collection=collection,
            job=job,
            document_names=names,
            wave_id=wave_id,
            reason=reason,
            baseline_document_names=baseline_document_names,
            baseline_document_count=baseline_document_count,
            baseline_chunk_count=baseline_chunk_count,
        )
        # A BM25 sidecar built by the completed worker may contain rejected
        # wave chunks.  Removing it is safer than serving stale sparse hits;
        # normal operation can rebuild it from authoritative Qdrant later.
        store = get_object_store()
        store.delete_prefix(bm25_artifact_key(collection, store=store))

        collection.status = "ready"
        collection.last_error = None
        db.flush()
        validation_names = {
            str(name)
            for name in (baseline_validation_names or [])
            if str(name or "").strip()
        }
        validation_names.update(dependent_names)
        baseline_verification = await verify_notice_collection_gate(
            db,
            workspace=workspace,
            collection=collection,
            document_names=sorted(validation_names),
        )
        recovery = {
            "status": "rolled_back",
            "wave_id": wave_id,
            "reason": reason,
            "qdrant_chunk_count_after": remaining_chunks,
            "qdrant_status_after": qdrant_status,
            "project_filter_counts_after": isolation_counts,
            "baseline_verification": baseline_verification,
        }
        update_job(
            db,
            job.id,
            status="failed",
            progress=100,
            error=f"postflight rejected and rolled back: {reason}",
            result={**dict(job.result or {}), "postflight_recovery": recovery},
            stage="postflight_rolled_back",
        )
        emit_audit_event(
            db=db,
            workspace_id=workspace.id,
            event_type="notice.wave.postflight_rolled_back",
            actor=actor,
            severity="warning",
            details={
                "collection_slug": collection.slug,
                "job_id": job.id,
                "wave_id": wave_id,
                "reason": reason,
                "baseline_chunk_count": int(baseline_chunk_count),
                "snapshot_ref": snapshot_ref,
            },
        )
        db.commit()
        return {**report, **recovery}
    except Exception as exc:  # noqa: BLE001 - quarantine is the safe fallback.
        db.rollback()
        fresh_collection = (
            db.query(KnowledgeCollection)
            .filter(KnowledgeCollection.id == collection.id)
            .first()
        )
        if fresh_collection is not None:
            fresh_collection.status = "error"
            fresh_collection.last_error = (
                f"postflight rollback unconfirmed wave={wave_id}: {exc}"
            )
        fresh_job = db.query(WorkerJob).filter(WorkerJob.id == job.id).first()
        if fresh_job is not None:
            update_job(
                db,
                fresh_job.id,
                status="failed",
                progress=100,
                error=f"postflight rollback unconfirmed: {exc}",
                result={
                    **dict(fresh_job.result or {}),
                    "postflight_recovery": {
                        **report,
                        "status": "quarantined",
                        "error": str(exc),
                    },
                },
                stage="postflight_rollback_unconfirmed",
            )
        db.commit()
        return {**report, "status": "quarantined", "error": str(exc)}


__all__ = ["quarantine_notice_collection", "rollback_rejected_notice_wave"]
