from typing import cast

from celery import Task
from fastapi import APIRouter, status

from connections.celery.tasks import ingest_documents
from connections.payload_models.flow_operations import (
    IngestDocumentsPayload,
)
from connections.payload_models.flow_operations.base import BaseTaskResponse

router = APIRouter()

ingest_documents = cast(Task, ingest_documents)


@router.post(
    "/flow_operations/ingest_documents",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=BaseTaskResponse,
)
def ingest_documents_route(payload: IngestDocumentsPayload):
    task = ingest_documents.apply_async(args=(payload.model_dump(),), queue="cpu")
    return {"task_id": task.id}
