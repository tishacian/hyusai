from fastapi import APIRouter

from connections.fastapi.utils import prepare_json_response
from connections.payload_models.flow_operations import (
    CreateVectorStorePayload,
    IngestDocumentsPayload,
    QueryLLMPipelinePayload,
)

router = APIRouter()


@router.post("/flow_operations/ingest_documents")
def ingest_documents(payload: IngestDocumentsPayload):
    return prepare_json_response(task_id="TODO")


@router.post("/flow_operations/create_vector_store")
def create_vector_store(payload: CreateVectorStorePayload):
    return prepare_json_response(task_id="TODO")


@router.post("/flow_operations/query_llm_pipeline")
def query_llm_pipeline(payload: QueryLLMPipelinePayload):
    return prepare_json_response(task_id="TODO")
