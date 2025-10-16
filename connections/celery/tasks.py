from connections.celery.app import app
from connections.celery.custom_task_class import CustomTask
from connections.payload_models.flow_operations import (
    IngestDocumentsPayload,
)


@app.task(name="ingest_documents", bind=True)
def ingest_documents(self: CustomTask, payload: dict):
    from src.services.ingest_documents import IngestDocumentsService

    validated_payload = IngestDocumentsPayload.model_validate(payload)
    IngestDocumentsService(celery_task=self).call(validated_payload)
