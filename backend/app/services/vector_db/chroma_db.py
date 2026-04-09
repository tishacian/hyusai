"""Chroma vector database implementation"""
from typing import List, Dict, Optional
import numpy as np
from app.services.vector_db.base import VectorDBBase
from app.core.logging import get_logger

logger = get_logger(__name__)


class ChromaVectorDB(VectorDBBase):
    """Chroma-based vector database"""
    
    def __init__(self, persist_directory: str = "./chroma_db", collection_name: str = "documents", client=None):
        self.persist_directory = persist_directory
        self.collection_name = collection_name
        self.client = client  # Allow passing a shared client
        self.collection = None
        self._initialize()
    
    def _initialize(self):
        """Initialize Chroma client"""
        try:
            import chromadb
            
            # Use shared client if provided, otherwise create new one
            if self.client is None:
                # Use new ChromaDB API (v0.4+)
                # ChromaDB client is a singleton per path, so we need to handle existing instances
                try:
                    self.client = chromadb.PersistentClient(
                        path=self.persist_directory,
                    )
                except Exception as client_error:
                    # If client already exists, try to get it
                    error_str = str(client_error).lower()
                    if "already exists" in error_str or "different settings" in error_str:
                        # Try to use existing client - ChromaDB should handle this
                        # Create a new client with same path (should reuse if possible)
                        try:
                            # Force create new client - ChromaDB will handle singleton internally
                            self.client = chromadb.PersistentClient(
                                path=self.persist_directory,
                            )
                        except Exception as e2:
                            logger.warning(f"ChromaDB client initialization issue, trying alternative: {e2}")
                            # Last resort: try to get existing collection directly
                            # This might fail, but we'll let it propagate
                            self.client = chromadb.PersistentClient(path=self.persist_directory)
                    else:
                        raise
            
            # Get or create collection
            try:
                self.collection = self.client.get_or_create_collection(
                    name=self.collection_name,
                    metadata={"hnsw:space": "cosine"}
                )
            except Exception as coll_error:
                # If collection creation fails, try to get existing one
                error_str = str(coll_error).lower()
                if "already exists" in error_str or "different" in error_str:
                    try:
                        self.collection = self.client.get_collection(name=self.collection_name)
                    except Exception as get_error:
                        logger.error(f"Failed to get existing collection: {get_error}")
                        raise
                else:
                    raise
            
            logger.info(f"Initialized ChromaDB at {self.persist_directory} for collection '{self.collection_name}'")
        except ImportError:
            logger.error("chromadb not installed. Install with: pip install chromadb")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize ChromaDB: {e}")
            raise
    
    async def create_index(self, dimension: int, index_type: str = "default"):
        """Create index (Chroma handles this automatically)"""
        # Chroma automatically creates index when collection is created
        # Metadata is set during collection creation, not after
        pass
    
    async def add_vectors(self, vectors: np.ndarray, metadatas: List[Dict], ids: List[str]):
        """Add vectors to Chroma"""
        import asyncio
        
        loop = asyncio.get_event_loop()
        
        def _add():
            # Convert numpy array to list of lists
            vectors_list = vectors.tolist()
            
            # Filter out None values from metadata (ChromaDB doesn't accept None)
            cleaned_metadatas = []
            for metadata in metadatas:
                cleaned_metadata = {k: v for k, v in metadata.items() if v is not None}
                cleaned_metadatas.append(cleaned_metadata)
            
            # Chroma expects metadatas as list of dicts
            self.collection.add(
                embeddings=vectors_list,
                metadatas=cleaned_metadatas,
                ids=ids,
            )
        
        await loop.run_in_executor(None, _add)
        logger.debug(f"Added {len(ids)} vectors to ChromaDB")
    
    async def search(self, query_vector: np.ndarray, top_k: int = 10, filters: Optional[Dict] = None) -> List[Dict]:
        """Search similar vectors"""
        import asyncio
        
        # ChromaDB requires at least 1 result
        if top_k <= 0:
            return []
        
        loop = asyncio.get_event_loop()
        
        def _search():
            query_list = query_vector.tolist()
            
            # Convert filters to Chroma format
            where = None
            if filters:
                where = filters
            
            results = self.collection.query(
                query_embeddings=[query_list],
                n_results=top_k,
                where=where,
            )
            
            # Format results
            formatted_results = []
            if results['ids'] and len(results['ids'][0]) > 0:
                for i, vec_id in enumerate(results['ids'][0]):
                    metadata = results['metadatas'][0][i] if results['metadatas'] and results['metadatas'][0] else {}
                    # Extract content from metadata for ChromaDB
                    content = metadata.get("content", "")
                    
                    formatted_results.append({
                        "id": vec_id,
                        "score": 1 - results['distances'][0][i] if 'distances' in results and results['distances'] else 0.0,
                        "metadata": metadata,
                        "content": content,  # Include content directly in result
                    })
            
            return formatted_results
        
        return await loop.run_in_executor(None, _search)
    
    async def delete(self, ids: List[str]):
        """Delete vectors by IDs"""
        import asyncio
        
        if not ids:
            return
        
        loop = asyncio.get_event_loop()
        
        def _delete():
            try:
                # Filter out None/empty IDs
                valid_ids = [id for id in ids if id]
                if valid_ids:
                    self.collection.delete(ids=valid_ids)
            except Exception as e:
                logger.warning(f"Error deleting some vectors: {e}")
        
        await loop.run_in_executor(None, _delete)
        logger.debug(f"Deleted {len(ids)} vectors from ChromaDB")
    
    async def update(self, ids: List[str], vectors: np.ndarray, metadatas: List[Dict]):
        """Update vectors"""
        await self.delete(ids)
        await self.add_vectors(vectors, metadatas, ids)
    
    async def get_count(self) -> int:
        """Get total number of vectors"""
        import asyncio
        
        loop = asyncio.get_event_loop()
        
        def _count():
            return self.collection.count()
        
        return await loop.run_in_executor(None, _count)
    
    async def get_all_ids(self) -> List[str]:
        """Get all vector IDs in the collection"""
        import asyncio
        
        loop = asyncio.get_event_loop()
        
        def _get_ids():
            # Get all documents from collection
            results = self.collection.get(include=[])  # Only need IDs
            return results['ids'] if results and 'ids' in results else []
        
        return await loop.run_in_executor(None, _get_ids)
    
    async def get_by_document_id(self, document_id: str) -> List[str]:
        """Get all chunk IDs for a specific document"""
        import asyncio
        
        loop = asyncio.get_event_loop()
        
        def _get_by_doc():
            # Query by document_id in metadata
            results = self.collection.get(
                where={"document_id": document_id}
            )
            return results['ids'] if results and 'ids' in results else []
        
        return await loop.run_in_executor(None, _get_by_doc)
    
    async def list_documents(self) -> List[Dict]:
        """List all unique documents in the collection"""
        import asyncio
        
        loop = asyncio.get_event_loop()
        
        def _list_docs():
            # Get all documents
            results = self.collection.get(include=['metadatas'])
            if not results or 'metadatas' not in results:
                return []
            
            # Extract unique document IDs
            seen_docs = {}
            for metadata in results['metadatas']:
                doc_id = metadata.get('document_id')
                filename = metadata.get('document_filename', 'Unknown')
                
                # Filter out temporary files and system files
                if filename.startswith('.') or filename.endswith('.tmp') or filename.startswith('tmp_'):
                    continue
                
                # Filter out documents without proper IDs
                if not doc_id or doc_id.startswith('temp_') or doc_id.startswith('tmp_'):
                    continue
                
                if doc_id not in seen_docs:
                    seen_docs[doc_id] = {
                        'document_id': doc_id,
                        'filename': filename,
                        'document_type': metadata.get('document_type', 'unknown'),
                    }
            
            return list(seen_docs.values())
        
        return await loop.run_in_executor(None, _list_docs)
    
    async def clear_collection(self):
        """Clear all vectors from the collection"""
        import asyncio
        
        loop = asyncio.get_event_loop()
        
        def _clear():
            # Get all IDs and delete them
            results = self.collection.get()
            if results and 'ids' in results and results['ids']:
                self.collection.delete(ids=results['ids'])
        
        await loop.run_in_executor(None, _clear)
        logger.info(f"Cleared all vectors from collection {self.collection_name}")

