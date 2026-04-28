from pathlib import Path
from typing import cast

from celery import Task
from fastapi import APIRouter, status

from connections.celery.tasks import (
    create_vector_store,
    ingest_documents,
    query_llm_pipeline,
)
from connections.database.collections import Collection
from connections.models.flow_operations import (
    IngestDocumentsPayload,
    IngestDocumentsResponse,
)
from connections.models.flow_operations.base_response import BaseTaskResponse
from connections.models.flow_operations.create_vector_store.payload import (
    IndexCollectionPayload,
)
from connections.models.flow_operations.query_llm_pipeline.payload import (
    QueryPayload,
)
from connections.storage import BUCKET_FOLDER, WORKSPACE_UUID, fs

router = APIRouter()

ingest_documents = cast(Task, ingest_documents)
create_vector_store = cast(Task, create_vector_store)
query_llm_pipeline = cast(Task, query_llm_pipeline)


@router.post(
    "/flow_operations/ingest_documents",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=IngestDocumentsResponse,
)
async def ingest_documents_route(payload: IngestDocumentsPayload):
    # create collection record in db at fastapi level to return uuid to user immediately
    input_folder_path = fs.joinpath(
        WORKSPACE_UUID, BUCKET_FOLDER, str(payload.input_documents_bucket)
    )
    document_paths = fs.list_files(input_folder_path, recursive=True)
    document_filenames = [Path(path).name for path in document_paths]
    col = Collection.create(
        name=payload.collection_name,
        created_by=payload.created_by,
        document_names=document_filenames,
        description=payload.collection_description,
    )
    task = ingest_documents.apply_async(
        args=(payload.model_dump(), col.uuid), queue="cpu"
    )
    return {"task_id": task.id, "knowledge_base_uuid": col.uuid}


@router.post(
    "/flow_operations/create_vector_store",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=BaseTaskResponse,
)
async def create_vector_store_route(payload: IndexCollectionPayload):
    Collection.update(
        str(payload.collection_uuid),
        embedding_model_name=payload.embedding.model_name,
        chunking_method=payload.chunking.method,
        chunking_params=payload.chunking.model_dump(),
        status="embedding",
    )
    task = create_vector_store.apply_async(args=(payload.model_dump(),), queue="cpu")
    return {"task_id": task.id}


@router.post(
    "/flow_operations/query_llm_pipeline",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=BaseTaskResponse,
)
async def query_llm_pipeline_route(payload: QueryPayload):
    task = query_llm_pipeline.apply_async(args=(payload.model_dump(),), queue="cpu")
    return {"task_id": task.id}
