import papai_unified_storage

from configurations import Config

storage_config = Config.get().storage

fs: papai_unified_storage.storage.Storage = papai_unified_storage.filesystem(
    protocol=storage_config.name, **storage_config.options.model_dump()
)
