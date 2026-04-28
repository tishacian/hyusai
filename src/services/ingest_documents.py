from uuid import UUID

from connections.celery.custom_task_class import CustomTask
from connections.database.collections import Collection
from connections.models.flow_operations import IngestDocumentsPayload
from connections.storage import (
    BUCKET_FOLDER,
    KB_INGESTED_FOLDER,
    KB_ORIGINAL_FOLDER,
    KNOWLEDGE_BASE_FOLDER,
    WORKSPACE_UUID,
    fs,
)
from src.docloader import ThreadMultiDocLoader


class IngestDocumentsService:
    def __init__(self, celery_task: CustomTask | None = None):
        self.celery_task = celery_task

    def call(self, payload: IngestDocumentsPayload, kb_uuid: str):
        Collection.update(kb_uuid, status="ingesting")

        # save original files in knowledge base
        input_folder_path = fs.joinpath(
            WORKSPACE_UUID, BUCKET_FOLDER, str(payload.input_documents_bucket)
        )
        original_folder_path = fs.joinpath(
            WORKSPACE_UUID, KNOWLEDGE_BASE_FOLDER, kb_uuid, KB_ORIGINAL_FOLDER
        )
        fs.filesystem.copy(input_folder_path, original_folder_path, recursive=True)
        # ingest documents
        document_filenames = Collection.get_by_uuid(UUID(kb_uuid)).document_names
        file_paths = fs.joinpaths(original_folder_path, document_filenames)
        ingested_folder_path = fs.joinpath(
            WORKSPACE_UUID, KNOWLEDGE_BASE_FOLDER, kb_uuid, KB_INGESTED_FOLDER
        )
        ThreadMultiDocLoader(file_paths=file_paths, target_dir=ingested_folder_path)

        Collection.update(kb_uuid, status="created")
