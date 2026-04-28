import papai_unified_storage
from pydantic import SecretStr

from configurations import BackendConfig

storage_config = BackendConfig.get().storage

# FsspecStorageConfig.options may contain SecretStr values — unwrap before passing
# to papai_unified_storage which expects plain strings.
_options = {
    k: v.get_secret_value() if isinstance(v, SecretStr) else v
    for k, v in storage_config.options.model_dump().items()
}

fs: papai_unified_storage.storage.Storage = papai_unified_storage.filesystem(
    protocol=storage_config.name, **_options
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
