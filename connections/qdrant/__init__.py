from qdrant_client import QdrantClient

from configurations import BackendConfig

_qdrant_cfg = BackendConfig.get().qdrant

qdrant_client: QdrantClient = QdrantClient(
    host=_qdrant_cfg.host,
    port=_qdrant_cfg.port,
    api_key=_qdrant_cfg.api_key or None,
    https=_qdrant_cfg.https,
)

__all__ = ["qdrant_client"]
