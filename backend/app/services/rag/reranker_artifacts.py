"""Explicit per-collection reranker activation and request-time selection."""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException

from app.db.base import SessionLocal
from app.models.knowledge_collection import KnowledgeCollection, WorkerJob
from app.models.workspace import Workspace


def selected_reranker(collection_ref: str, workspace_slug: str | None) -> tuple[str, str] | None:
    if not workspace_slug:
        return None
    with SessionLocal() as db:
        row = (
            db.query(KnowledgeCollection)
            .join(Workspace, Workspace.id == KnowledgeCollection.workspace_id)
            .filter(
                Workspace.slug == workspace_slug,
                (KnowledgeCollection.slug == collection_ref)
                | (KnowledgeCollection.id == collection_ref),
            )
            .first()
        )
        if row and row.reranker_artifact_id:
            return row.workspace_id, row.reranker_artifact_id
    return None


def queue_reranker_activation(db, *, collection, artifact_id: str | None):
    from app.services.huggingface.registry import require_artifact
    from app.services.knowledge_collections import create_worker_job

    row = (
        db.query(KnowledgeCollection)
        .filter(KnowledgeCollection.id == collection.id)
        .with_for_update()
        .populate_existing()
        .one()
    )
    if (
        db.query(WorkerJob.id)
        .filter(
            WorkerJob.collection_id == row.id,
            WorkerJob.kind == "rag_reranker_activate",
            WorkerJob.status.in_(["queued", "running"]),
        )
        .first()
    ):
        raise HTTPException(409, detail={"code": "RAG_RERANKER_ACTIVATION_PENDING"})
    if artifact_id is None:
        from app.models.huggingface import HubArtifactUsage

        db.query(HubArtifactUsage).filter_by(
            workspace_id=row.workspace_id, kind="reranker", target_id=row.id
        ).update({"status": "released"})
        row.reranker_artifact_id = None
        return None
    require_artifact(db, row.workspace_id, artifact_id, usage="reranker")
    job = create_worker_job(
        db, workspace_id=row.workspace_id, collection_id=row.id, kind="rag_reranker_activate"
    )
    job.result = {
        "activation": {
            "artifact_id": artifact_id,
            "previous_artifact_id": row.reranker_artifact_id,
        },
        "stage": "queued",
    }
    return job


def run_reranker_activation(job_id: str) -> dict:
    from app.services.huggingface.adapters import ArtifactReranker
    from app.services.huggingface.registry import register_usage, require_artifact

    runtime = None
    with SessionLocal() as db:
        claimed = (
            db.query(WorkerJob)
            .filter(
                WorkerJob.id == job_id,
                WorkerJob.kind == "rag_reranker_activate",
                WorkerJob.status == "queued",
            )
            .update(
                {WorkerJob.status: "running", WorkerJob.started_at: datetime.utcnow()},
                synchronize_session=False,
            )
        )
        db.commit()
        if claimed != 1:
            return {"status": "skipped"}
        job = db.query(WorkerJob).filter(WorkerJob.id == job_id).one()
        activation = job.result["activation"]
        try:
            runtime = ArtifactReranker(
                workspace_id=job.workspace_id, artifact_id=activation["artifact_id"], db=db
            )
            # Constructor performs the real load/inference probe.
            row = (
                db.query(KnowledgeCollection)
                .filter(KnowledgeCollection.id == job.collection_id)
                .with_for_update()
                .populate_existing()
                .one()
            )
            db.refresh(job)
            if (
                job.status != "running"
                or row.reranker_artifact_id != activation["previous_artifact_id"]
            ):
                raise RuntimeError("RAG_RERANKER_SELECTION_CHANGED")
            require_artifact(db, job.workspace_id, activation["artifact_id"], usage="reranker")
            row.reranker_artifact_id = activation["artifact_id"]
            register_usage(db, job.workspace_id, activation["artifact_id"], "reranker", row.id)
            job.status, job.progress = "completed", 100
            job.completed_at = datetime.utcnow()
            result = {"activation": activation, "stage": "ready"}
            job.result = result
            db.commit()
            return result
        except Exception as exc:
            db.rollback()
            db.refresh(job)
            if job.status != "cancelled":
                job.status = "failed"
            job.error = str(exc)
            job.completed_at = datetime.utcnow()
            db.commit()
            raise
        finally:
            if runtime is not None:
                runtime.close()


def score_collection_passages(
    query,
    passages,
    metadatas,
    *,
    workspace_slug,
    collection_ref,
    model_name,
    max_length,
    models=None,
):
    """Score each collection with its explicitly selected artifact, or default.

    One failed selected model aborts this stage and is traced by the caller;
    it must never cause that collection to use a different reranker.
    """
    from app.services.huggingface.adapters import ArtifactReranker
    from app.services.rag.cross_encoder_stage import _score_passages
    from app.services.retrieval.reranker_config import RerankerConfig

    groups = {}
    for index, metadata in enumerate(metadatas):
        ref = str(
            collection_ref or metadata.get("collection") or metadata.get("collection_name") or ""
        )
        groups.setdefault(ref, []).append(index)
    scores = [0.0] * len(passages)
    provenance = models if models is not None else {}
    for ref, indices in groups.items():
        selected = selected_reranker(ref, workspace_slug)
        texts = [passages[i] for i in indices]
        if selected:
            workspace_id, artifact_id = selected
            provenance[ref] = artifact_id
            runtime = ArtifactReranker(
                workspace_id=workspace_id,
                artifact_id=artifact_id,
                config=RerankerConfig(max_length=max_length),
            )
            try:
                values = runtime.score(query, texts)
            finally:
                runtime.close()
        else:
            provenance[ref] = model_name
            values = _score_passages(query, texts, model_name=model_name, max_length=max_length)
        if len(values) != len(indices):
            raise RuntimeError("RAG_RERANKER_SCORE_ALIGNMENT")
        for index, score in zip(indices, values):
            scores[index] = float(score)
    return scores, provenance
