"""Document ingestion and indexing service"""
import asyncio
import numpy as np
from typing import List, Dict, Optional, Callable
from app.services.document_parser.factory import DocumentParserFactory
from app.services.embedding.embedder import Embedder
from app.services.vector_db.factory import VectorDBFactory
from app.services.retrieval.bm25_retriever import BM25Retriever
from app.services.retrieval.ensemble_retriever import EnsembleRetriever, EnsembleConfig
try:
    from app.services.retrieval.flash_reranker import FlashReranker, RerankerConfig
except ImportError:
    FlashReranker = None  # type: ignore
    RerankerConfig = None  # type: ignore

try:
    from app.services.retrieval.contextual_compression import ContextualCompressionRetriever, ContextualConfig
except ImportError:
    ContextualCompressionRetriever = None  # type: ignore
    ContextualConfig = None  # type: ignore
from app.services.retrieval.fusion_method import FusionMethod
from app.services.tracing.rag_tracer import get_tracer, TraceStepType
from app.services.rag.cache import get_cache
from app.core.logging import get_logger
from app.core.settings_manager import get_resolved_settings

logger = get_logger(__name__)


class DocumentService:
    """Service for ingesting and indexing documents"""
    
    def __init__(
        self, 
        collection_name: str = "documents", 
        use_hybrid: bool = True, 
        use_cache: bool = True, 
        vector_db_type: str = "faiss",
        fusion_method: FusionMethod = FusionMethod.SCORE_ADAPTIVE,
        use_reranker: bool = True,
        workspace_slug: Optional[str] = None,
    ):
        self.collection_name = collection_name
        self.vector_db_type = vector_db_type
        self.workspace_slug = workspace_slug
        self.embedder = Embedder()
        self.vector_db = VectorDBFactory.get_db(
            collection_name, db_type=vector_db_type, workspace_slug=workspace_slug
        )
        self.embedding_dimension = self.embedder.get_dimension()
        self.use_hybrid = use_hybrid
        self.use_reranker = use_reranker
        self.use_cache = use_cache
        self.cache = get_cache() if use_cache else None
        
        # Initialize BM25 retriever
        self.bm25_retriever = BM25Retriever()
        self._documents_cache: List[str] = []  # Cache for BM25
        
        # Initialize ensemble retriever (will be set up when documents are loaded)
        self.ensemble_retriever: Optional[EnsembleRetriever] = None
        self.contextual_retriever: Optional[ContextualCompressionRetriever] = None
        
        # Initialize reranker if enabled
        if use_reranker:
            try:
                self.reranker = FlashReranker(RerankerConfig())
            except Exception as e:
                logger.warning(f"Could not initialize reranker: {e}. Continuing without reranking.")
                self.reranker = None
                self.use_reranker = False
        else:
            self.reranker = None
    
    async def ingest_document(self, file_path: str, **kwargs) -> Dict:
        """Ingest a single document"""
        tracer = get_tracer()
        trace = tracer.start_trace("ingest", {"file_path": file_path})
        
        try:
            # Get chunking settings from app settings if not provided
            from app.services.document_parser.chunker import ChunkingMethod
            # DocumentService doesn't have direct workspace_id — fall back to
            # the process-wide singleton. Callers that do have a workspace
            # context should pass chunking_method / chunk_size / chunk_overlap
            # explicitly via kwargs (see documents.py endpoints).
            app_settings = get_resolved_settings()
            
            if 'chunking_method' not in kwargs:
                chunking_method_str = app_settings.get("ragChunkingMethod", "recursive_character")
                try:
                    kwargs['chunking_method'] = ChunkingMethod(chunking_method_str)
                except ValueError:
                    kwargs['chunking_method'] = ChunkingMethod.RECURSIVE_CHARACTER
            
            if 'chunk_size' not in kwargs:
                kwargs['chunk_size'] = app_settings.get("ragChunkSize", 1000)
            
            if 'chunk_overlap' not in kwargs:
                kwargs['chunk_overlap'] = app_settings.get("ragChunkOverlap", 200)
            
            # Step 1: Parse document
            parse_step = tracer.add_step(trace.id, TraceStepType.DOCUMENT_PARSE)
            parser = DocumentParserFactory.get_parser(file_path)
            parsed_doc = await parser.parse(file_path, **kwargs)
            parse_step.complete({
                "filename": parsed_doc.filename,
                "document_type": parsed_doc.document_type.value,
                "chunks_count": len(parsed_doc.chunks),
            })
            
            logger.info(f"Parsed document: {parsed_doc.filename} ({len(parsed_doc.chunks)} chunks)")
            
            # Generate embeddings for chunks
            chunk_texts = [chunk["content"] for chunk in parsed_doc.chunks]
            
            if not chunk_texts:
                logger.warning(f"No chunks extracted from {file_path}")
                trace.complete({"status": "success", "chunks_processed": 0})
                return {
                    "document_id": parsed_doc.id,
                    "status": "success",
                    "chunks_processed": 0,
                    "message": "No chunks to index",
                    "trace_id": trace.id,
                }
            
            # Step 2: Generate embeddings
            embedding_step = tracer.add_step(trace.id, TraceStepType.EMBEDDING, {
                "chunk_count": len(chunk_texts),
            })
            embeddings = await self.embedder.embed_batch(chunk_texts)
            import numpy as np
            embedding_dim = embeddings.shape[1] if isinstance(embeddings, np.ndarray) and len(embeddings) > 0 else 0
            embedding_step.complete({
                "embedding_dimension": embedding_dim,
            })
            
            # Step 3: Prepare metadata
            chunking_step = tracer.add_step(trace.id, TraceStepType.CHUNKING)
            chunk_metadatas = []
            chunk_ids = []
            
            for i, chunk in enumerate(parsed_doc.chunks):
                chunk_metadatas.append({
                    "document_id": parsed_doc.id,
                    "document_filename": parsed_doc.filename,
                    "chunk_index": i,
                    "content": chunk["content"],
                    "start_char": chunk.get("start_char", 0),
                    "end_char": chunk.get("end_char", len(chunk["content"])),
                    "page": chunk.get("page"),
                    "document_type": parsed_doc.document_type.value,
                    **{k: v for k, v in parsed_doc.metadata.items() if v is not None},
                })
                chunk_ids.append(f"{parsed_doc.id}_chunk_{i}")
            
            chunking_step.complete({"chunks_prepared": len(chunk_ids)})
            
            # Step 4: Index in vector database
            indexing_step = tracer.add_step(trace.id, TraceStepType.INDEXING)
            import numpy as np
            embeddings_array = np.array(embeddings)
            
            await self.vector_db.create_index(self.embedding_dimension)
            await self.vector_db.add_vectors(embeddings_array, chunk_metadatas, chunk_ids)
            indexing_step.complete({"vectors_indexed": len(chunk_ids)})
            
            # Update BM25 cache if using hybrid retrieval
            if self.use_hybrid:
                self._documents_cache.extend(chunk_texts)
                # Fit BM25 with documents (IDs and metadatas optional for single document)
                self.bm25_retriever.fit(self._documents_cache)
                # Reset ensemble retriever to rebuild with new documents
                self.ensemble_retriever = None
                self.contextual_retriever = None
            
            logger.info(f"Indexed {len(chunk_ids)} chunks from {parsed_doc.filename}")
            
            trace.complete({
                "status": "success",
                "chunks_processed": len(parsed_doc.chunks),
                "document_id": parsed_doc.id,
            })
            
            return {
                "document_id": parsed_doc.id,
                "status": "success",
                "chunks_processed": len(parsed_doc.chunks),
                "filename": parsed_doc.filename,
                "trace_id": trace.id,
            }
        
        except Exception as e:
            logger.error(f"Error ingesting document {file_path}: {e}", exc_info=True)
            trace.complete({"status": "error", "error": str(e)})
            return {
                "document_id": file_path,
                "status": "error",
                "error": str(e),
                "trace_id": trace.id,
            }
    
    async def ingest_documents_batch(self, file_paths: List[str], **kwargs) -> Dict:
        """
        Ingest multiple documents in parallel.
        Each document is processed asynchronously: parse -> chunk -> embed -> index
        """
        async def process_single_document(file_path: str) -> Dict:
            """Process a single document through the full pipeline"""
            try:
                # Step 1: Parse document (async)
                parser = DocumentParserFactory.get_parser(file_path)
                parsed_doc = await parser.parse(file_path, **kwargs)
                
                if not parsed_doc.chunks:
                    return {
                        "document_id": parsed_doc.id,
                        "status": "success",
                        "chunks_processed": 0,
                        "filename": parsed_doc.filename,
                        "message": "No chunks to index",
                    }
                
                # Step 2: Generate embeddings for chunks (async batch)
                chunk_texts = [chunk["content"] for chunk in parsed_doc.chunks]
                embeddings = await self.embedder.embed_batch(chunk_texts)
                
                # Step 3: Prepare metadata
                chunk_metadatas = []
                chunk_ids = []
                for i, chunk in enumerate(parsed_doc.chunks):
                    chunk_metadatas.append({
                        "document_id": parsed_doc.id,
                        "document_filename": parsed_doc.filename,
                        "chunk_index": i,
                        "content": chunk["content"],
                        "start_char": chunk.get("start_char", 0),
                        "end_char": chunk.get("end_char", len(chunk["content"])),
                        "page": chunk.get("page"),
                        "document_type": parsed_doc.document_type.value,
                        **{k: v for k, v in parsed_doc.metadata.items() if v is not None},
                    })
                    chunk_ids.append(f"{parsed_doc.id}_chunk_{i}")
                
                # Step 4: Index in vector database (async)
                import numpy as np
                embeddings_array = np.array(embeddings)
                await self.vector_db.create_index(self.embedding_dimension)
                await self.vector_db.add_vectors(embeddings_array, chunk_metadatas, chunk_ids)
                
                # Update BM25 cache (will be rebuilt after all documents are processed)
                if self.use_hybrid:
                    self._documents_cache.extend(chunk_texts)
                    # Store document IDs and metadatas for BM25 fitting
                    if not hasattr(self, '_document_ids_cache'):
                        self._document_ids_cache = []
                    if not hasattr(self, '_document_metadatas_cache'):
                        self._document_metadatas_cache = []
                    self._document_ids_cache.extend(chunk_ids)
                    self._document_metadatas_cache.extend(chunk_metadatas)
                
                logger.info(f"Indexed {len(chunk_ids)} chunks from {parsed_doc.filename}")
                
                return {
                    "document_id": parsed_doc.id,
                    "status": "success",
                    "chunks_processed": len(parsed_doc.chunks),
                    "filename": parsed_doc.filename,
                }
            except Exception as e:
                logger.error(f"Error processing document {file_path}: {e}", exc_info=True)
                return {
                    "document_id": file_path,
                    "status": "error",
                    "error": str(e),
                }
        
        # Process all documents in parallel
        tasks = [process_single_document(path) for path in file_paths]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle exceptions
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Exception processing {file_paths[i]}: {result}", exc_info=True)
                processed_results.append({
                    "document_id": file_paths[i],
                    "status": "error",
                    "error": str(result),
                })
            else:
                processed_results.append(result)
        
        # Rebuild BM25 index after all documents are processed
        if self.use_hybrid and self._documents_cache:
            try:
                document_ids = getattr(self, '_document_ids_cache', [f"doc_{i}" for i in range(len(self._documents_cache))])
                document_metadatas = getattr(self, '_document_metadatas_cache', [{}] * len(self._documents_cache))
                # Ensure lists are same length
                min_len = min(len(self._documents_cache), len(document_ids), len(document_metadatas))
                self.bm25_retriever.fit(
                    self._documents_cache[:min_len],
                    document_ids[:min_len],
                    document_metadatas[:min_len]
                )
                # Reset ensemble retriever to rebuild with new documents
                self.ensemble_retriever = None
                self.contextual_retriever = None
                logger.info(f"Rebuilt BM25 index with {min_len} document chunks")
            except Exception as e:
                logger.warning(f"Could not rebuild BM25 index: {e}")
        
        successful = sum(1 for r in processed_results if isinstance(r, dict) and r.get("status") == "success")
        failed = len(processed_results) - successful
        
        return {
            "total": len(file_paths),
            "successful": successful,
            "failed": failed,
            "results": processed_results,
        }
    
    async def search(self, query: str, top_k: int = 10, filters: Optional[Dict] = None, use_hybrid: Optional[bool] = None, use_cache: Optional[bool] = None) -> List[Dict]:
        """Search documents by query"""
        use_hybrid = use_hybrid if use_hybrid is not None else self.use_hybrid
        use_cache = use_cache if use_cache is not None else self.use_cache
        
        # Check cache first
        if use_cache and self.cache:
            cached_results = self.cache.get(query, top_k, filters, use_hybrid)
            if cached_results is not None:
                logger.debug("Returning cached search results")
                return cached_results
        
        tracer = get_tracer()
        trace = tracer.start_trace("search", {"query": query[:100], "top_k": top_k, "hybrid": use_hybrid})
        
        try:
            # Step 1: Generate query embedding
            query_embedding_step = tracer.add_step(trace.id, TraceStepType.QUERY_EMBEDDING)
            query_embedding = await self.embedder.embed(query)
            import numpy as np
            embedding_dim = len(query_embedding) if isinstance(query_embedding, np.ndarray) else query_embedding.shape[0] if hasattr(query_embedding, 'shape') else 0
            query_embedding_step.complete({"embedding_dimension": embedding_dim})
            
            # Step 2: Perform search using advanced ensemble retrieval
            search_step = tracer.add_step(trace.id, TraceStepType.VECTOR_SEARCH, {"top_k": top_k, "hybrid": use_hybrid})
            
            if use_hybrid:
                # Load documents for BM25 if cache is empty
                if not self._documents_cache:
                    try:
                        # Get all documents from collection to build BM25 index
                        all_ids = await self.vector_db.get_all_ids()
                        if all_ids:
                            loop = asyncio.get_event_loop()
                            
                            def _get_all():
                                # Handle ChromaDB, FAISS, and Qdrant
                                if hasattr(self.vector_db, 'collection'):
                                    # ChromaDB
                                    return self.vector_db.collection.get(ids=all_ids[:1000], include=['metadatas'])
                                elif hasattr(self.vector_db, 'metadatas'):
                                    # FAISS - get metadatas directly
                                    metadatas = []
                                    for vec_id in all_ids[:1000]:
                                        if vec_id in self.vector_db.metadatas:
                                            metadatas.append(self.vector_db.metadatas[vec_id])
                                    return {'metadatas': metadatas}
                                elif hasattr(self.vector_db, 'get_metadatas_for_chunk_ids'):
                                    metadatas = self.vector_db.get_metadatas_for_chunk_ids(all_ids[:1000])
                                    return {'metadatas': metadatas}
                                return None
                            
                            all_data = await loop.run_in_executor(None, _get_all)
                            if all_data and 'metadatas' in all_data:
                                self._documents_cache = [m.get("content", "") for m in all_data['metadatas'] if m.get("content")]
                                if self._documents_cache:
                                    # Fit BM25 retriever (IDs and metadatas optional when loading from DB)
                                    document_ids = all_ids[:len(self._documents_cache)]
                                    document_metadatas = all_data['metadatas'][:len(self._documents_cache)]
                                    self.bm25_retriever.fit(self._documents_cache, document_ids, document_metadatas)
                                    
                                    # Create dense search function wrapper
                                    async def dense_search_fn(query_embedding: np.ndarray, k: int) -> List[Dict]:
                                        """Dense search function for ensemble retriever"""
                                        # query_embedding is already a numpy array
                                        if len(query_embedding.shape) == 2:
                                            query_embedding = query_embedding[0]  # Take first row if 2D
                                        return await self.vector_db.search(query_embedding, k, filters)
                                    
                                    ensemble_config = EnsembleConfig(
                                        k=20,
                                        bm25_weight=0.4,
                                        dense_weight=0.6,
                                        fusion_method=FusionMethod.RRF,  # Use RRF as default
                                        rrf_k=60,
                                    )
                                    
                                    self.ensemble_retriever = EnsembleRetriever(
                                        bm25_retriever=self.bm25_retriever,
                                        dense_retriever_fn=dense_search_fn,
                                        embedding_model=self.embedder,
                                        texts=self._documents_cache,
                                        config=ensemble_config,
                                    )
                                    
                                    # Initialize contextual compression retriever if reranker is available
                                    if self.use_reranker and self.reranker:
                                        contextual_config = ContextualConfig(
                                            k=10,
                                            compression_ratio=0.7,
                                        )
                                        self.contextual_retriever = ContextualCompressionRetriever(
                                            base_retriever=self.ensemble_retriever,
                                            reranker=self.reranker,
                                            config=contextual_config,
                                        )
                                    
                                    logger.info(f"Loaded {len(self._documents_cache)} documents for advanced hybrid indexing (BM25 + Dense + Reranking) from collection '{self.collection_name}' ({self.vector_db_type})")
                            elif all_ids:
                                logger.warning(f"Could not extract content from {len(all_ids)} documents for BM25 indexing")
                    except Exception as e:
                        logger.warning(f"Could not load documents for BM25 from collection '{self.collection_name}' ({self.vector_db_type}): {e}", exc_info=True)
                
                # Use advanced retrieval if available
                if self.ensemble_retriever:
                    # First, get dense vector results with full metadata
                    dense_results = await self.vector_db.search(query_embedding, top_k * 2, filters)
                    
                    # Create a mapping from content to vector DB results for metadata preservation
                    content_to_vector_result = {}
                    for r in dense_results:
                        content = r.get("content") or r.get("metadata", {}).get("content", "")
                        if content:
                            content_to_vector_result[content] = r
                    
                    # Use ensemble retriever to get fused results
                    if self.contextual_retriever:
                        # Use contextual compression retriever (ensemble + reranking)
                        passages, scores = await self.contextual_retriever.retrieve_and_compress(query, top_k)
                    else:
                        # Use ensemble retriever (BM25 + Dense fusion)
                        passages, scores = await self.ensemble_retriever.retrieve(query, top_k)
                    
                    # Match ensemble results back to original vector DB results to preserve metadata
                    formatted_results = []
                    for passage, score in zip(passages, scores):
                        # Filter out low-quality content (garbage/binary data)
                        if not passage or len(passage.strip()) < 10:
                            continue
                        
                        # Check for high ratio of non-printable characters
                        printable_chars = sum(1 for c in passage if c.isprintable() or c.isspace())
                        if len(passage) > 0 and printable_chars / len(passage) < 0.7:
                            logger.debug(f"Filtering out low-quality content: {passage[:50]}...")
                            continue
                        
                        # Try to find matching vector DB result by content (fuzzy match)
                        vector_result = None
                        # First try exact match
                        if passage in content_to_vector_result:
                            vector_result = content_to_vector_result[passage]
                        else:
                            # Try to find by substring match (for cleaned content)
                            for content, result in content_to_vector_result.items():
                                if passage in content or content in passage:
                                    vector_result = result
                                    break
                        
                        if vector_result:
                            # Use original content from vector DB result (not cleaned passage)
                            original_content = vector_result.get("content") or vector_result.get("metadata", {}).get("content", "")
                            # Use original content if available, otherwise use passage
                            final_content = original_content if original_content else passage
                            
                            # Use metadata from vector DB result
                            metadata = vector_result.get("metadata", {})
                            formatted_results.append({
                                "id": vector_result.get("id", f"retrieved_{len(formatted_results)}"),
                                "content": final_content,
                                "score": float(score),
                                "metadata": metadata,
                                "vector_score": vector_result.get("score", 0.0),
                                "bm25_score": 0.0,  # Will be updated if available
                                "combined_score": float(score),
                            })
                        else:
                            # Fallback: create result from passage only (if it's good quality)
                            formatted_results.append({
                                "id": f"retrieved_{len(formatted_results)}",
                                "content": passage,
                                "score": float(score),
                                "metadata": {},
                                "vector_score": float(score),
                                "bm25_score": 0.0,
                                "combined_score": float(score),
                            })
                    
                    # If we have ensemble retriever, try to get individual scores
                    if hasattr(self.ensemble_retriever, '_get_bm25_scores') and hasattr(self.ensemble_retriever, '_get_dense_scores'):
                        try:
                            # Get BM25 and dense scores separately to preserve individual scores
                            candidate_k = top_k * 2
                            bm25_task = asyncio.create_task(self.ensemble_retriever._get_bm25_scores(query, candidate_k))
                            dense_task = asyncio.create_task(self.ensemble_retriever._get_dense_scores(query, candidate_k))
                            
                            (bm25_passages, bm25_scores_dict, _), (dense_passages, dense_scores_dict, _) = await asyncio.gather(
                                bm25_task, dense_task
                            )
                            
                            # Update formatted results with individual scores
                            for result in formatted_results:
                                content = result["content"]
                                if content in bm25_scores_dict:
                                    result["bm25_score"] = float(bm25_scores_dict[content])
                                if content in dense_scores_dict:
                                    result["vector_score"] = float(dense_scores_dict[content])
                        except Exception as e:
                            logger.warning(f"Could not extract individual scores: {e}")
                    
                    results = formatted_results
                else:
                    # Fallback to vector search if advanced retrieval not available
                    logger.warning(f"Advanced retrieval not available for collection '{self.collection_name}' ({self.vector_db_type}), falling back to vector-only search")
                    results = await self.vector_db.search(query_embedding, top_k, filters)
            else:
                # Vector search only
                results = await self.vector_db.search(query_embedding, top_k, filters)
            
            # Format results to include content from metadata (if not already formatted)
            formatted_results = []
            for r in results:
                metadata = r.get("metadata", {})
                # Extract content - check both direct content and metadata
                content = r.get("content") or metadata.get("content", "")
                
                formatted_results.append({
                    "id": r.get("id", ""),
                    "score": r.get("score", 0.0),
                    "content": content,  # Add content directly to result
                    "metadata": metadata,
                    # Preserve any additional scores if present
                    "vector_score": r.get("vector_score", r.get("score", 0.0)),
                    "bm25_score": r.get("bm25_score", 0.0),
                    "combined_score": r.get("combined_score", r.get("score", 0.0)),
                })
            
            search_step.complete({"results_count": len(formatted_results)})
            
            # Cache results
            if use_cache and self.cache:
                self.cache.set(query, top_k, formatted_results, filters, use_hybrid)
            
            trace.complete({"status": "success", "results_count": len(formatted_results)})
            
            return formatted_results
        
        except Exception as e:
            logger.error(f"Error searching documents: {e}", exc_info=True)
            trace.complete({"status": "error", "error": str(e)})
            raise
    
    async def get_document_count(self) -> int:
        """Get total number of indexed documents"""
        return await self.vector_db.get_count()
    
    async def list_documents(self) -> List[Dict]:
        """List all documents in the collection"""
        return await self.vector_db.list_documents()
    
    async def delete_document(self, document_id: str) -> bool:
        """Delete a document and all its chunks"""
        try:
            chunk_ids = await self.vector_db.get_by_document_id(document_id)
            if chunk_ids:
                await self.vector_db.delete(chunk_ids)
            # Clear cache
            if self.cache:
                self.cache.clear()
            return True
        except Exception as e:
            logger.error(f"Error deleting document {document_id}: {e}")
            return False
    
    async def clear_all_documents(self) -> bool:
        """Clear all documents from the collection"""
        try:
            await self.vector_db.clear_collection()
            # Clear cache
            if self.cache:
                self.cache.clear()
            return True
        except Exception as e:
            logger.error(f"Error clearing documents: {e}")
            return False

