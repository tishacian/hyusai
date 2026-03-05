from uuid import UUID

from connections.celery.custom_task_class import CustomTask
from connections.database.knowledge_bases import KnowledgeBases
from connections.models.flow_operations import IngestDocumentsPayload
from connections.storage import (
    BUCKET_FOLDER,
    KB_EXTRACTED_ASSETS_FOLDER,
    KB_ORIGINAL_FOLDER,
    KNOWLEDGE_BASE_FOLDER,
    WORKSPACE_UUID,
    fs,
)
from src.docloader import ThreadMultiDocLoader


class IngestDocumentsService:
    def __init__(self, celery_task: CustomTask | None = None):
        self.celery_task = celery_task

    def call(self, payload: IngestDocumentsPayload) -> UUID:
        # save original files in knowledge base and create instance in db table
        input_folder_path = fs.joinpath(
            WORKSPACE_UUID, BUCKET_FOLDER, str(payload.input_documents_bucket)
        )
        document_relative_paths = fs.list_files(
            input_folder_path, recursive=True, remove_root_folder=True
        )
        kb = KnowledgeBases.add(
            name=payload.knowledge_base_name,
            created_by=payload.knowledge_base_creator,
            document_names=document_relative_paths,
            description=payload.knowledge_base_description,
        )
        original_folder_path = fs.joinpath(
            WORKSPACE_UUID, KNOWLEDGE_BASE_FOLDER, kb.uuid, KB_ORIGINAL_FOLDER
        )
        fs.put(input_folder_path, original_folder_path, recursive=True)
        # ingest documents
        file_paths = fs.joinpaths(original_folder_path, document_relative_paths)
        extracted_assets_folder_path = fs.joinpath(
            WORKSPACE_UUID, KNOWLEDGE_BASE_FOLDER, kb.uuid, KB_EXTRACTED_ASSETS_FOLDER
        )
        ThreadMultiDocLoader(
            file_paths=file_paths, target_dir=extracted_assets_folder_path
        )
        return kb.uuid
