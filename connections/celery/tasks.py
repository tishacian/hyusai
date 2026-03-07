from connections.celery.app import app
from connections.celery.custom_task_class import CustomTask
from connections.celery.task_response import TaskResponse
from connections.models.flow_operations import IngestDocumentsPayload
from connections.models.flow_operations.create_vector_store.payload import (
    CreateVectorStorePayload,
)


@app.task(name="ingest_documents", bind=True)
def ingest_documents(self: CustomTask, payload: dict, kb_uuid: str) -> TaskResponse:
    from src.services.ingest_documents import IngestDocumentsService

    validated_payload = IngestDocumentsPayload.model_validate(payload)
    IngestDocumentsService(celery_task=self).call(validated_payload, kb_uuid)
    return {"status": "success"}


@app.task(name="create_vector_store", bind=True)
def create_vector_store(self: CustomTask, payload: dict) -> TaskResponse:
    from src.services.create_vector_store import CreateVectorStoreService

    validated_payload = CreateVectorStorePayload.model_validate(payload)
    CreateVectorStoreService(celery_task=self).call(validated_payload)
    return {"status": "success"}


@app.task(name="query_llm_pipeline", bind=True)
def query_llm_pipeline(self: CustomTask, payload: dict) -> TaskResponse:
    from src.services.query_llm_pipeline import QueryLLMPipelineService

    validated_payload = CreateVectorStorePayload.model_validate(payload)
    QueryLLMPipelineService(celery_task=self).call(validated_payload)
    return {"status": "success"}
