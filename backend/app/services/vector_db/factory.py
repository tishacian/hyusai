"""Vector database factory"""
from typing import Any, List, Optional, Tuple

from app.core.config import settings
from app.core.logging import get_logger
from app.services.vector_db.base import VectorDBBase
from app.services.vector_db.chroma_db import ChromaVectorDB
from app.services.vector_db.faiss_db import FAISSVectorDB
from app.services.vector_db.qdrant_db import QdrantVectorDB

logger = get_logger(__name__)


class VectorDBFactory:
    """Factory for creating vector database instances"""
    
    _instances = {}
    _chroma_clients = {}  # Cache ChromaDB clients by persist directory
    _qdrant_clients: dict[Tuple[str, int, bool, str], Any] = {}
    
    @staticmethod
    def scoped_name(collection_name: str, workspace_slug: Optional[str] = None) -> str:
        """Prefix collection name with workspace slug for isolation."""
        if workspace_slug:
            return f"{workspace_slug}__{collection_name}"
        return collection_name

    @classmethod
    def get_db(cls, collection_name: str = "documents", db_type: str = "qdrant", workspace_slug: Optional[str] = None) -> VectorDBBase:
        """Get vector database instance, scoped by workspace if provided."""
        collection_name = cls.scoped_name(collection_name, workspace_slug)
        cache_key = f"{db_type}_{collection_name}"
        
        if cache_key not in cls._instances:
            if db_type == "faiss":
                persist_dir = getattr(settings, 'faiss_persist_directory', './faiss_db')
                cls._instances[cache_key] = FAISSVectorDB(
                    persist_directory=persist_dir,
                    collection_name=collection_name
                )
            elif db_type == "chroma":
                persist_dir = getattr(settings, 'chroma_persist_directory', './chroma_db')
                # Use a shared ChromaDB client for the same persist directory to avoid conflicts
                if persist_dir not in cls._chroma_clients:
                    try:
                        import chromadb
                        cls._chroma_clients[persist_dir] = chromadb.PersistentClient(path=persist_dir)
                        logger.debug(f"Created new ChromaDB client for {persist_dir}")
                    except Exception as e:
                        error_str = str(e).lower()
                        if "already exists" in error_str or "different settings" in error_str:
                            # Try to get existing client - ChromaDB maintains singleton internally
                            logger.warning(f"ChromaDB client conflict detected, attempting to reuse: {e}")
                            # Create a new client - ChromaDB should handle singleton internally
                            cls._chroma_clients[persist_dir] = chromadb.PersistentClient(path=persist_dir)
                        else:
                            raise
                
                # Create ChromaVectorDB with shared client
                cls._instances[cache_key] = ChromaVectorDB(
                    persist_directory=persist_dir,
                    collection_name=collection_name,
                    client=cls._chroma_clients[persist_dir]  # Pass shared client
                )
            elif db_type == "qdrant":
                qkey = (
                    settings.qdrant_host,
                    settings.qdrant_port,
                    settings.qdrant_https,
                    settings.qdrant_api_key or "",
                )
                if qkey not in cls._qdrant_clients:
                    from qdrant_client import QdrantClient

                    cls._qdrant_clients[qkey] = QdrantClient(
                        host=settings.qdrant_host,
                        port=settings.qdrant_port,
                        api_key=settings.qdrant_api_key or None,
                        https=settings.qdrant_https,
                        timeout=settings.qdrant_timeout_seconds,
                    )
                    logger.debug(
                        "Created Qdrant client",
                        host=settings.qdrant_host,
                        port=settings.qdrant_port,
                    )
                cls._instances[cache_key] = QdrantVectorDB(
                    collection_name=collection_name,
                    client=cls._qdrant_clients[qkey],
                )
            else:
                raise ValueError(
                    f"Unknown vector DB type: {db_type}. Supported: 'faiss', 'chroma', 'qdrant'"
                )
        
        return cls._instances[cache_key]
    
    @classmethod
    def clear_instance(cls, collection_name: str, db_type: str = "qdrant", workspace_slug: Optional[str] = None):
        """Clear a cached instance (useful when deleting collections)"""
        collection_name = cls.scoped_name(collection_name, workspace_slug)
        cache_key = f"{db_type}_{collection_name}"
        if cache_key in cls._instances:
            del cls._instances[cache_key]
            logger.info(f"Cleared cached instance for collection: {collection_name} (type: {db_type})")
    
    @classmethod
    def list_collections(cls, db_type: str = "qdrant", workspace_slug: Optional[str] = None) -> List[str]:
        """List collections for a given vector DB type, filtered by workspace prefix."""
        import os
        from pathlib import Path
        
        if db_type == "faiss":
            persist_dir = getattr(settings, 'faiss_persist_directory', './faiss_db')
            collections = set()
            if os.path.exists(persist_dir):
                try:
                    for file in os.listdir(persist_dir):
                        # FAISS collections have both .index and .metadata.pkl files
                        # We check for .index files and verify .metadata.pkl exists
                        if file.endswith('.index') and not file.startswith('_'):
                            collection_name = file.replace('.index', '')
                            # Verify metadata file exists (indicates a valid collection)
                            metadata_file = os.path.join(persist_dir, f"{collection_name}.metadata.pkl")
                            if os.path.exists(metadata_file):
                                collections.add(collection_name)
                except Exception as e:
                    logger.warning(f"Error listing FAISS collections: {e}")
            return sorted(list(collections))
        elif db_type == "chroma":
            import chromadb
            persist_dir = getattr(settings, 'chroma_persist_directory', './chroma_db')
            try:
                client = chromadb.PersistentClient(path=persist_dir)
                collections = client.list_collections()
                # Filter out internal collections
                return [col.name for col in collections if not col.name.startswith('_')]
            except Exception as e:
                logger.error(f"Error listing ChromaDB collections: {e}")
                return []
        elif db_type == "qdrant":
            try:
                from qdrant_client import QdrantClient

                qkey = (
                    settings.qdrant_host,
                    settings.qdrant_port,
                    settings.qdrant_https,
                    settings.qdrant_api_key or "",
                )
                if qkey not in cls._qdrant_clients:
                    cls._qdrant_clients[qkey] = QdrantClient(
                        host=settings.qdrant_host,
                        port=settings.qdrant_port,
                        api_key=settings.qdrant_api_key or None,
                        https=settings.qdrant_https,
                        timeout=settings.qdrant_timeout_seconds,
                    )
                client = cls._qdrant_clients[qkey]
                cols = client.get_collections().collections
                return sorted([c.name for c in cols if not c.name.startswith("_")])
            except Exception as e:
                logger.error(f"Error listing Qdrant collections: {e}")
                return []
        else:
            return []

    @classmethod
    def list_collections_for_workspace(cls, db_type: str = "qdrant", workspace_slug: Optional[str] = None) -> List[str]:
        """List collections scoped to a workspace, stripping the prefix from names."""
        all_cols = cls.list_collections(db_type=db_type)
        if not workspace_slug:
            return all_cols
        prefix = f"{workspace_slug}__"
        return [c[len(prefix):] for c in all_cols if c.startswith(prefix)]
