from connections.celery.app import app
from connections.celery.custom_task_class import CustomTask
from connections.models.flow_operations import IngestDocumentsPayload


@app.task(name="ingest_documents", bind=True)
def ingest_documents(self: CustomTask, payload: dict) -> str:
    from src.services.ingest_documents import IngestDocumentsService

    validated_payload = IngestDocumentsPayload.model_validate(payload)
    kb_uuid = IngestDocumentsService(celery_task=self).call(validated_payload)
    return str(kb_uuid)
