from pathlib import Path
from typing import cast

from celery import Task
from fastapi import APIRouter, status

from connections.celery.tasks import ingest_documents
from connections.database.knowledge_bases import KnowledgeBases
from connections.models.flow_operations import (
    IngestDocumentsPayload,
    IngestDocumentsResponse,
)
from connections.storage import BUCKET_FOLDER, WORKSPACE_UUID, fs

router = APIRouter()

ingest_documents = cast(Task, ingest_documents)


@router.post(
    "/flow_operations/ingest_documents",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=IngestDocumentsResponse,
)
def ingest_documents_route(payload: IngestDocumentsPayload):
    # create instance in db table at fastapi level to return kb uuid to user immediately
    input_folder_path = fs.joinpath(
        WORKSPACE_UUID, BUCKET_FOLDER, str(payload.input_documents_bucket)
    )
    document_paths = fs.list_files(input_folder_path, recursive=True)
    document_filenames = [Path(path).name for path in document_paths]
    kb = KnowledgeBases.add(
        name=payload.knowledge_base_name,
        created_by=payload.knowledge_base_creator,
        document_names=document_filenames,
        description=payload.knowledge_base_description,
    )
    task = ingest_documents.apply_async(
        args=(payload.model_dump(), kb.uuid), queue="cpu"
    )
    return {"task_id": task.id, "knowledge_base_uuid": kb.uuid}
