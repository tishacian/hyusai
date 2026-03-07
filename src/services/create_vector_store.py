from connections.celery.custom_task_class import CustomTask
from connections.celery.task_response import TaskResponse
from connections.models.flow_operations import CreateVectorStorePayload
from connections.storage import (
    KB_INGESTED_FOLDER,
    KNOWLEDGE_BASE_FOLDER,
    WORKSPACE_UUID,
    fs,
)
from src.chunker import TextChunker
from src.embedding import EmbeddingVectors


class CreateVectorStoreService:
    def __init__(self, celery_task: CustomTask | None = None):
        self.celery_task = celery_task

    def call(self, payload: CreateVectorStorePayload) -> TaskResponse:
        # step 1: read all ingested documents and combine them into a single text
        ingested_folder_path = fs.joinpath(
            WORKSPACE_UUID,
            KNOWLEDGE_BASE_FOLDER,
            payload.knowledge_base_uuid,
            KB_INGESTED_FOLDER,
        )
        files = fs.list_files(ingested_folder_path)
        if not files:
            raise ValueError("No ingested documents found.")
        documents = []
        for file_path in files:
            with fs.open(file_path, "r") as f:
                documents.append(f.read())
        documents = "\n".join(documents)  # TODO: consider batching instead
        # step 2: split the text into chunks
        text_chunker = TextChunker()
        chunking_params = payload.chunking_params.model_dump(exclude_none=True)
        chunks = text_chunker.chunker(documents, **chunking_params)
        if not chunks:
            raise ValueError("No chunks created from the documents.")
        # step 3: embed the chunks and index them into the vector store
        embedding_params = payload.embedding_params
        embedder = EmbeddingVectors(
            create_new_vs=True,
            existing_vector_store=embedding_params.old_vector_store_uuid,
            new_vs_name=embedding_params.new_vector_store_name,
            embedding_model_name=embedding_params.embedding_model_name,
            normalization_strategy=embedding_params.normalization_strategy,
            embedding_type=embedding_params.vector_store_type,
            log_normalization_stats=False,
        )
        embedder.create_and_save_index(chunks)
