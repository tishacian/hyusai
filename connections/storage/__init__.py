import papai_unified_storage

from configurations import back_conf

storage_config = back_conf().storage

fs: papai_unified_storage.storage.Storage = papai_unified_storage.filesystem(
    protocol=storage_config.name, **storage_config.options.model_dump()
)
