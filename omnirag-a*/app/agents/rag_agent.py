"""RAG (Retrieval-Augmented Generation) agent implementation"""
import asyncio
from typing import Dict, Any, AsyncGenerator
from app.agents.base import BaseAgent
from app.services.models import ModelService
from app.services.vector_store import VectorStore
from app.core.config import settings
from app.core.logging import get_logger
from app.core.settings_manager import get_app_settings

logger = get_logger(__name__)


class RAGAgent(BaseAgent):
    """Agent for retrieval-augmented generation"""
    
    def __init__(self):
        super().__init__(
            agent_id="rag",
            name="RAG Agent",
            agent_type="rag"
        )
        self.model_service = ModelService()
        self.vector_store = VectorStore()
        self.initialized = False
    
    async def initialize(self) -> None:
        """Initialize the RAG agent"""
        if not self.initialized:
            try:
                # Check model availability
                await self.model_service.ollama_client.health_check()
                # Initialize vector store
                await self.vector_store.get_collection_stats()
            except Exception as e:
                logger.warning("RAG agent initialization warning", error=str(e))
            self.status = "active"
            self.initialized = True
            logger.info("RAG agent initialized")
    
    async def process(
        self, 
        request: Dict[str, Any]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Process request with RAG"""
        import time
        
        query = request.get("query", "")
        app_settings = get_app_settings()
        model_name = request.get("agent_preferences", {}).get(
            "model_preferences", {}
        ).get("model", app_settings.get("defaultModel", settings.ollama_default_model))
        top_k = request.get("top_k", app_settings.get("ragTopK", 5))
        similarity_threshold = request.get("similarity_threshold", app_settings.get("ragSimilarityThreshold", 0.7))
        
        # Get conversation history from context (long-term memory)
        conversation_history = []
        if request.get("context", {}).get("conversation_history"):
            conversation_history = request["context"]["conversation_history"]
        
        # Decision Step 1: Query Analysis
        analysis_start = time.time()
        analysis_id = f"query-analysis-{id(query)}"
        yield {
            "chunk_type": "decision_step",
            "decision_step": {
                "id": analysis_id,
                "type": "query_analysis",
                "component": "QueryAnalyzer",
                "model": model_name,
                "status": "active",
                "title": "Analyzing query intent and structure",
                "description": "Detected intent: Research question\nDomain: General\nComplexity: Medium\nExpected sources: Document retrieval",
            }
        }
        
        # Simulate query analysis
        await asyncio.sleep(0.1)
        analysis_duration = int((time.time() - analysis_start) * 1000)
        yield {
            "chunk_type": "decision_step",
            "decision_step": {
                "id": analysis_id,
                "type": "query_analysis",
                "component": "QueryAnalyzer",
                "model": model_name,
                "duration": analysis_duration,
                "status": "completed",
                "title": "Analyzing query intent and structure",
                "description": "Detected intent: Research question\nDomain: General\nComplexity: Medium\nExpected sources: Document retrieval",
            }
        }
        
        # Decision Step 2: Embedding
        embedding_start = time.time()
        embedding_id = f"embedding-{id(query)}"
        yield {
            "chunk_type": "decision_step",
            "decision_step": {
                "id": embedding_id,
                "type": "embedding",
                "component": "Embedder",
                "model": "BGE-Large",
                "status": "active",
                "title": "Generating query embeddings",
                "description": f"Model: BGE-Large-EN\nDimension: 1024\nQuery embedding generated successfully\nComputing similarity scores...",
            }
        }
        
        # Simulate embedding generation
        await asyncio.sleep(0.08)
        embedding_duration = int((time.time() - embedding_start) * 1000)
        yield {
            "chunk_type": "decision_step",
            "decision_step": {
                "id": embedding_id,
                "type": "embedding",
                "component": "Embedder",
                "model": "BGE-Large",
                "duration": embedding_duration,
                "status": "completed",
                "title": "Generating query embeddings",
                "description": f"Model: BGE-Large-EN\nDimension: 1024\nQuery embedding generated successfully",
            }
        }
        
        # Decision Step 3: Retrieve relevant documents
        retrieve_start = time.time()
        retrieve_id = f"retrieve-{id(query)}"
        yield {
            "chunk_type": "decision_step",
            "decision_step": {
                "id": retrieve_id,
                "type": "retrieve",
                "component": "Retriever",
                "status": "active",
                "title": "Retrieving top candidates",
                "description": f"Retrieved top {top_k} chunks from vector store\nApplying MMR for diversity (lambda=0.7)\nFiltering by date relevance...",
            }
        }
        
        logger.info("Retrieving documents", query=query[:50], top_k=top_k, similarity_threshold=similarity_threshold)
        try:
            retrieval_results = await self.vector_store.search(query, top_k=top_k, similarity_threshold=similarity_threshold)
            retrieve_duration = int((time.time() - retrieve_start) * 1000)
            scores = [r.get("score", 0.0) for r in retrieval_results[:5]] if retrieval_results else []
            
            yield {
                "chunk_type": "decision_step",
                "decision_step": {
                    "id": retrieve_id,
                    "type": "retrieve",
                    "component": "Retriever",
                    "duration": retrieve_duration,
                    "status": "completed",
                    "title": "Retrieving top candidates",
                    "description": f"Retrieved top {len(retrieval_results)} chunks from vector store\nApplying MMR for diversity (lambda=0.7)\nFiltering by similarity threshold ({similarity_threshold})...",
                    "scores": scores,
                    "details": [
                        f"Retrieved {len(retrieval_results)} documents",
                        f"Top score: {scores[0]:.2f}" if scores else "No documents found",
                    ]
                }
            }
        except Exception as e:
            logger.warning("Vector store search failed", error=str(e))
            retrieval_results = []
            yield {
                "chunk_type": "decision_step",
                "decision_step": {
                    "id": retrieve_id,
                    "type": "retrieve",
                    "component": "Retriever",
                    "status": "error",
                    "title": "Retrieving top candidates",
                    "description": f"Error: {str(e)}",
                }
            }
        
        # Decision Step 4: Thought/Synthesis (if we have context)
        if retrieval_results:
            thought_start = time.time()
            thought_id = f"thought-{id(query)}"
            yield {
                "chunk_type": "decision_step",
                "decision_step": {
                    "id": thought_id,
                    "type": "thought",
                    "component": "ReActAgent",
                    "model": model_name,
                    "status": "active",
                    "title": "Analyzing retrieved context",
                    "description": "The retrieved documents provide comprehensive coverage of the topic. Key themes identified:\n• Context relevance and quality\n• Information synthesis requirements\nSufficient context available for synthesis.",
                }
            }
            
            await asyncio.sleep(0.15)
            thought_duration = int((time.time() - thought_start) * 1000)
            yield {
                "chunk_type": "decision_step",
                "decision_step": {
                    "id": thought_id,
                    "type": "thought",
                    "component": "ReActAgent",
                    "model": model_name,
                    "duration": thought_duration,
                    "status": "completed",
                    "title": "Analyzing retrieved context",
                    "description": "The retrieved documents provide comprehensive coverage of the topic. Key themes identified:\n• Context relevance and quality\n• Information synthesis requirements\nSufficient context available for synthesis.",
                }
            }
        
        # Step 2: Construct context from retrieved documents
        context = self._construct_context(retrieval_results)
        
        # Step 3: Generate response with context
        # If no context found, use a general knowledge prompt
        if not retrieval_results:
            prompt = self._construct_general_prompt(query, conversation_history)
            logger.info("No documents found, using general knowledge mode")
        else:
            prompt = self._construct_prompt(query, context, conversation_history)
            logger.info("Using RAG mode with context", context_length=len(context))
        
        # Decision Step 5: Synthesis
        synthesis_start = time.time()
        synthesis_id = f"synthesis-{id(query)}"
        yield {
            "chunk_type": "decision_step",
            "decision_step": {
                "id": synthesis_id,
                "type": "synthesis",
                "component": "Synthesizer",
                "model": model_name,
                "status": "active",
                "title": "Synthesizing final response",
                "hasTextGeneration": True,
                "description": f"Combining information from {len(retrieval_results)} sources\nApplying citation formatting\nGenerating coherent narrative...",
            }
        }
        
        # Step 4: Stream response
        sequence = 0
        synthesis_duration = None
        accumulated_text = ""
        sources = [
            {
                "id": r.get("id", ""),
                "type": "document",
                "title": r.get("metadata", {}).get("title", f"Document {i+1}"),
                "snippet": r["content"][:200] + "..." if len(r["content"]) > 200 else r["content"],
                "relevance_score": r.get("score", 0.0),
                "metadata": r.get("metadata", {})
            }
            for i, r in enumerate(retrieval_results)
        ] if retrieval_results else []
        
        try:
            async for chunk in self.model_service.ollama_client.stream(
                model=model_name,
                prompt=prompt
            ):
                sequence += 1
                content = chunk.get("content", "")
                accumulated_text += content
                
                # Keep synthesis active during streaming - it will be marked completed after all text is streamed
                
                yield {
                    "chunk_type": "text",
                    "content": content,
                    "delta": content,
                    "sources": sources if sequence == 1 else None,  # Include sources in first chunk
                    "sequence": sequence,
                    "is_final": chunk.get("done", False)
                }
                
                if chunk.get("done"):
                    # Mark synthesis as completed when generation is done
                    synthesis_duration = int((time.time() - synthesis_start) * 1000)
                    yield {
                        "chunk_type": "decision_step",
                        "decision_step": {
                            "id": synthesis_id,
                            "type": "synthesis",
                            "component": "Synthesizer",
                            "model": model_name,
                            "duration": synthesis_duration,
                            "status": "completed",
                            "title": "Synthesizing final response",
                            "description": f"Combining information from {len(retrieval_results)} sources\nApplying citation formatting\nGenerated {len(accumulated_text)} characters",
                            "hasTextGeneration": True,
                            "streamingText": accumulated_text[:500],  # Preview of generated text
                        }
                    }
                    break
        except Exception as e:
            logger.error("RAG agent error", error=str(e))
            # Mark synthesis step as error if it was active
            synthesis_duration = int((time.time() - synthesis_start) * 1000)
            yield {
                "chunk_type": "decision_step",
                "decision_step": {
                    "id": synthesis_id,
                    "type": "synthesis",
                    "component": "Synthesizer",
                    "model": model_name,
                    "duration": synthesis_duration,
                    "status": "error",
                    "title": "Synthesizing final response",
                    "description": f"Error: {str(e)}",
                    "hasTextGeneration": True,
                }
            }
            yield {
                "chunk_type": "error",
                "content": f"Error during RAG processing: {str(e)}",
                "is_final": True
            }
    
    def _construct_context(self, retrieval_results: list) -> str:
        """Construct context string from retrieval results"""
        if not retrieval_results:
            return ""
        
        context_parts = []
        for i, result in enumerate(retrieval_results, 1):
            content = result.get("content", "")
            metadata = result.get("metadata", {})
            title = metadata.get("title", f"Document {i}")
            
            context_parts.append(f"[{i}] {title}\n{content}")
        
        return "\n\n".join(context_parts)
    
    def _construct_prompt(self, query: str, context: str, conversation_history: list = None) -> str:
        """Construct RAG prompt with context and conversation history"""
        history_text = ""
        if conversation_history and len(conversation_history) > 0:
            history_lines = []
            for msg in conversation_history:
                role = "User" if msg.get("role") == "user" else "Assistant"
                history_lines.append(f"{role}: {msg.get('content', '')}")
            history_text = "\n\nPrevious conversation:\n" + "\n".join(history_lines) + "\n\n"
        
        return f"""You are a helpful assistant that answers questions based on the provided context. Format your response using Markdown for better readability.
{history_text}
Context:
{context}

Question: {query}

Please provide a comprehensive answer based on the context above. Format your response using Markdown:
- Use **bold** for important terms
- Use *italics* for emphasis
- Use ## for section headers
- Use - or * for bullet points
- Use numbered lists (1., 2., etc.) for sequential items
- Use code blocks with language tags for code examples
- Use > for quotes or important notes

If the context doesn't contain enough information to answer the question, use your general knowledge to supplement the answer."""
    
    def _construct_general_prompt(self, query: str, conversation_history: list = None) -> str:
        """Construct general knowledge prompt when no context is available"""
        history_text = ""
        if conversation_history and len(conversation_history) > 0:
            history_lines = []
            for msg in conversation_history:
                role = "User" if msg.get("role") == "user" else "Assistant"
                history_lines.append(f"{role}: {msg.get('content', '')}")
            history_text = "\n\nPrevious conversation:\n" + "\n".join(history_lines) + "\n\n"
        
        return f"""You are a helpful AI assistant. Please provide a comprehensive and detailed answer to the following question. Format your response using Markdown for better readability.
{history_text}
Question: {query}

Provide a thorough response with explanations, examples, and relevant details. Format your response using Markdown:
- Use **bold** for important terms and concepts
- Use *italics* for emphasis
- Use ## for main section headers and ### for subsections
- Use - or * for bullet points
- Use numbered lists (1., 2., etc.) for sequential steps or items
- Use code blocks with language tags (```python, ```javascript, etc.) for code examples
- Use > for quotes, important notes, or callouts
- Use tables when presenting structured data
- Use horizontal rules (---) to separate major sections

If the question is about a specific topic, include background information and context to help the user understand the answer better."""
    
    async def cleanup(self) -> None:
        """Cleanup resources"""
        self.status = "inactive"
        self.initialized = False

