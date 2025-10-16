from connections.celery.custom_task_class import CustomTask
from connections.payload_models.flow_operations.ingest_documents import (
    IngestDocumentsPayload,
)
from connections.storage import fs
from src.docloader import ThreadMultiDocLoader


class IngestDocumentsService:
    def __init__(self, celery_task: CustomTask | None = None):
        self.celery_task = celery_task

    def call(self, payload: IngestDocumentsPayload):
        uploaded_folder = fs.joinpath(
            "knowledge-bases", str(payload.knowledge_base_uuid), "uploaded"
        )
        file_paths = fs.list_files(uploaded_folder, recursive=True)
        ThreadMultiDocLoader(file_paths)
