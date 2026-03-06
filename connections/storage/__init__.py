import papai_unified_storage

from configurations import Config

storage_config = Config.get().storage

fs: papai_unified_storage.storage.Storage = papai_unified_storage.filesystem(
    protocol=storage_config.name, **storage_config.options.model_dump()
)

# TODO: make this configurable for papai
WORKSPACE_UUID = "a0000000-0000-0000-0000-000000000001"
BUCKET_FOLDER = "buckets"
KNOWLEDGE_BASE_FOLDER = "knowledge-bases"
KB_ORIGINAL_FOLDER = "original"
KB_INGESTED_FOLDER = "ingested"
KB_VECTOR_STORE_FOLDER = "vector-store"

__all__ = [
    "fs",
    "WORKSPACE_UUID",
    "BUCKET_FOLDER",
    "KNOWLEDGE_BASE_FOLDER",
    "KB_ORIGINAL_FOLDER",
    "KB_INGESTED_FOLDER",
    "KB_VECTOR_STORE_FOLDER",
]
