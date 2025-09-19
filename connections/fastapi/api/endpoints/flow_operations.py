from typing import cast

from asgi_correlation_id.context import correlation_id
from celery import Task
from fastapi import APIRouter

from connections.celery.tasks import ingest_documents
from connections.payload_models.flow_operations import (
    IngestDocumentsPayload,
)

router = APIRouter()

ingest_documents = cast(Task, ingest_documents)


@router.post("/flow_operations/ingest_documents")
def ingest_documents_route(payload: IngestDocumentsPayload):
    ingest_documents.apply_async(
        args=(payload.model_dump(),),
        task_id=str(correlation_id.get()),
        queue="cpu",
    )
