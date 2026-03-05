from typing import cast

from celery import Task
from fastapi import APIRouter, status

from connections.celery.tasks import ingest_documents
from connections.models.flow_operations import (
    IngestDocumentsPayload,
    IngestDocumentsResponse,
)

router = APIRouter()

ingest_documents = cast(Task, ingest_documents)


@router.post(
    "/flow_operations/ingest_documents",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=IngestDocumentsResponse,
)
def ingest_documents_route(payload: IngestDocumentsPayload):
    task = ingest_documents.apply_async(args=(payload.model_dump(),), queue="cpu")
    return {"task_id": task.id}
