from connections.celery.custom_task_class import CustomTask
from connections.payload_models.flow_operations.ingest_documents import (
    IngestDocumentsPayload,
)


class IngestDocumentsService:
    def __init__(self, celery_task: CustomTask):
        self.celery_task = celery_task

    def call(self, payload: IngestDocumentsPayload):
        pass
