import logging

from connections.celery.custom_task_class import CustomTask
from connections.celery.task_response import TaskResponse
from connections.database.collections import Collection
from connections.models.flow_operations import IndexCollectionPayload
from connections.storage import (
    KB_INGESTED_FOLDER,
    KNOWLEDGE_BASE_FOLDER,
    WORKSPACE_UUID,
    fs,
)
from src.embedding import EmbeddingVectors

logger = logging.getLogger(__name__)

# Maps payload field names to TextChunker method parameter names.
_CHUNKING_PARAM_MAP = {
    "max_chunk_length": "chunk_size",
    "overlap_size": "overlap",
    "max_tokens_per_chunk": "max_tokens",
    "max_paragraph_length": "paragraph_chunk_size",
    "max_sentence_length": "sentence_chunk_size",
    "cluster_selection_method": "method",
    "boundary_confidence_threshold": "threshold",
}


class CreateVectorStoreService:
    def __init__(self, celery_task: CustomTask | None = None):
        self.celery_task = celery_task

    def call(self, payload: IndexCollectionPayload) -> TaskResponse:
        # Import here to avoid loading heavy ML deps at module import time
        from src.chunker import SimpleTokenizer, TextChunker
        from src.embeddingloader import EmbeddingModelLoader

        kb_uuid = str(payload.collection_uuid)

        # 1. Read all ingested documents from storage
        ingested_folder = fs.joinpath(
            WORKSPACE_UUID, KNOWLEDGE_BASE_FOLDER, kb_uuid, KB_INGESTED_FOLDER
        )
        file_paths = fs.list_files(ingested_folder, recursive=True)
        if not file_paths:
            raise ValueError(f"No ingested documents found for collection {kb_uuid!r}")

        documents = []
        for path in file_paths:
            with fs.open_for_reading(path, text=True) as f:
                documents.append(f.read())

        if not documents:
            raise ValueError(
                f"All ingested documents are empty for collection {kb_uuid!r}"
            )

        # 2. Derive chunk-size ceiling from the embedding model's tokenizer.
        # The embedding model (SentenceTransformer) is already loaded/cached by EmbeddingModelLoader.
        # TODO: once TEI (Text Embeddings Inference) is wired up as the embedding service,
        #       query the tokenizer context length from the TEI /tokenize endpoint instead.
        _DEFAULT_MAX_LENGTH = 512
        try:
            _st_model = EmbeddingModelLoader.load_embedding_model(
                payload.embedding.model_name
            )
            _model_max_length = (
                _st_model.tokenizer.model_max_length
                if _st_model is not None and hasattr(_st_model, "tokenizer")
                else _DEFAULT_MAX_LENGTH
            )
        except Exception:
            _model_max_length = _DEFAULT_MAX_LENGTH

        # 3. Chunk each document and collect all chunks
        chunker = TextChunker(SimpleTokenizer(_model_max_length), None)
        chunking_method = payload.chunking.method
        chunking_kwargs_raw = payload.chunking.model_dump(
            exclude={"method"},
            exclude_none=True,
        )
        chunking_kwargs = {
            _CHUNKING_PARAM_MAP.get(k, k): v for k, v in chunking_kwargs_raw.items()
        }

        all_chunks: list[str] = []
        for doc_text in documents:
            chunks = chunker.chunker(
                doc_text, method=chunking_method, **chunking_kwargs
            )
            if chunks:
                all_chunks.extend(chunks)

        if not all_chunks:
            raise ValueError(f"No chunks produced for collection {kb_uuid!r}")

        logger.info("Produced %d chunks for collection %s", len(all_chunks), kb_uuid)

        # 4. Embed and index into Qdrant
        embedder = EmbeddingVectors(
            tokenizer=None,
            model=None,
            target_collection=kb_uuid,
            kb_uuid=kb_uuid,
            source_collection=payload.embedding.source_collection,
            embedding_model_name=payload.embedding.model_name,
            distance_metric=payload.embedding.distance_metric,
        )
        embedder.create_and_save_index(
            all_chunks,
            batch_size=payload.embedding.batch_size,
            use_dynamic_batching=(payload.embedding.batch_size is None),
        )

        # 5. Mark collection as ready in the database
        Collection.update(kb_uuid, status="ready")
        logger.info("Collection %s is now ready", kb_uuid)

        return {"status": "success"}
