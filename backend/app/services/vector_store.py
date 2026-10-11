"""Vector store service for document storage and retrieval"""
from typing import List, Dict, Any, Optional
import chromadb
from chromadb.config import Settings
from app.core.logging import get_logger
from app.core.config import settings
from app.services.embeddings import EmbeddingService

logger = get_logger(__name__)


class VectorStore:
    """Vector store for document embeddings"""
    
    def __init__(self, collection_name: str = "documents"):
        self.collection_name = collection_name
        self.client = None
        self.collection = None
        self.embedding_service = EmbeddingService()
        self.logger = get_logger(__name__)
    
    def _initialize(self):
        """Initialize ChromaDB client and collection"""
        if self.client is None:
            self.logger.info("Initializing ChromaDB", persist_dir=settings.chroma_persist_directory)
            self.client = chromadb.PersistentClient(
                path=settings.chroma_persist_directory,
                settings=Settings(anonymized_telemetry=False)
            )
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"}
            )
            self.logger.info("ChromaDB initialized")
    
    async def add_documents(
        self, 
        documents: List[Dict[str, Any]],
        batch_size: int = 100
    ) -> List[str]:
        """Add documents to vector store"""
        self._initialize()
        
        ids = []
        texts = []
        embeddings = []
        metadatas = []
        
        for doc in documents:
            doc_id = doc.get("id")
            content = doc.get("content", "")
            metadata = doc.get("metadata", {})
            
            if not doc_id or not content:
                continue
            
            # Generate embedding
            embedding = self.embedding_service.embed(content)
            
            ids.append(doc_id)
            texts.append(content)
            embeddings.append(embedding)
            metadatas.append(metadata)
        
        # Add in batches
        for i in range(0, len(ids), batch_size):
            batch_ids = ids[i:i + batch_size]
            batch_texts = texts[i:i + batch_size]
            batch_embeddings = embeddings[i:i + batch_size]
            batch_metadatas = metadatas[i:i + batch_size]
            
            self.collection.add(
                ids=batch_ids,
                documents=batch_texts,
                embeddings=batch_embeddings,
                metadatas=batch_metadatas
            )
        
        self.logger.info("Documents added to vector store", count=len(ids))
        return ids
    
    async def search(
        self, 
        query: str, 
        top_k: int = 5,
        similarity_threshold: float = 0.7,
        filter_metadata: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Search for similar documents"""
        self._initialize()
        
        # Generate query embedding
        query_embedding = self.embedding_service.embed(query)
        
        # Search with more results to filter by threshold
        # We request more results than top_k to allow filtering by similarity threshold
        search_top_k = max(top_k * 2, 20) if similarity_threshold > 0 else top_k
        
        # Search
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=search_top_k,
            where=filter_metadata
        )
        
        # Format results and filter by similarity threshold
        formatted_results = []
        if results["ids"] and len(results["ids"][0]) > 0:
            for i in range(len(results["ids"][0])):
                distance = results["distances"][0][i] if results.get("distances") else 1.0
                score = 1 - distance  # Convert distance to similarity score
                
                # Filter by similarity threshold
                if score >= similarity_threshold:
                    formatted_results.append({
                        "id": results["ids"][0][i],
                        "content": results["documents"][0][i],
                        "score": score,
                        "metadata": results["metadatas"][0][i] if results.get("metadatas") else {}
                    })
                
                # Stop once we have enough results that meet the threshold
                if len(formatted_results) >= top_k:
                    break
        
        return formatted_results
        
        return formatted_results
    
    async def delete_document(self, document_id: str) -> bool:
        """Delete a document from vector store"""
        self._initialize()
        try:
            self.collection.delete(ids=[document_id])
            self.logger.info("Document deleted", document_id=document_id)
            return True
        except Exception as e:
            self.logger.error("Failed to delete document", document_id=document_id, error=str(e))
            return False
    
    async def get_collection_stats(self) -> Dict[str, Any]:
        """Get collection statistics"""
        self._initialize()
        count = self.collection.count()
        return {
            "collection_name": self.collection_name,
            "document_count": count
        }

