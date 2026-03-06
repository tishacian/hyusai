from connections.celery.app import app
from connections.celery.custom_task_class import CustomTask
from connections.celery.task_response import TaskResponse
from connections.models.flow_operations import IngestDocumentsPayload


@app.task(name="ingest_documents", bind=True)
def ingest_documents(self: CustomTask, payload: dict, kb_uuid: str) -> TaskResponse:
    from src.services.ingest_documents import IngestDocumentsService

    validated_payload = IngestDocumentsPayload.model_validate(payload)
    IngestDocumentsService(celery_task=self).call(validated_payload, kb_uuid)
    return {"status": "success"}
