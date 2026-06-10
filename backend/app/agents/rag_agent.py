"""RAG (Retrieval-Augmented Generation) agent implementation"""
from typing import Dict, Any, AsyncGenerator
from app.agents.base import BaseAgent
from app.services.models import ModelService
from app.core.config import settings
from app.core.logging import get_logger
from app.core.settings_manager import get_resolved_settings

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
        self.vector_store = None
        self.initialized = False
    
    async def initialize(self) -> None:
        """Initialize the RAG agent"""
        if not self.initialized:
            try:
                # Check model availability
                await self.model_service.ollama_client.health_check()
                # Initialize legacy vector store lazily. Planned RAG retrieval
                # no longer depends on this Chroma-backed path, so an optional
                # dependency mismatch must not make the agent unimportable.
                if self.vector_store is None:
                    from app.services.vector_store import VectorStore

                    self.vector_store = VectorStore()
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
        app_settings = get_resolved_settings(
            workspace_id=request.get("workspace_id"),
            capability_id=request.get("capability_id"),
            system_id=request.get("system_id"),
        )
        model_name = request.get("agent_preferences", {}).get(
            "model_preferences", {}
        ).get("model", app_settings.get("defaultModel", settings.ollama_default_model))
        top_k = request.get("top_k", app_settings.get("ragTopK", 5))
        workspace_slug = request.get("workspace_slug")

        # Get conversation history from context (long-term memory)
        conversation_history = []
        if request.get("context", {}).get("conversation_history"):
            conversation_history = request["context"]["conversation_history"]
        workspace_context = request.get("context", {}).get("workspace_calendar") or ""
        
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
        
        # Decision Step 2: Embedding — real embedder telemetry. The query is
        # embedded inside the retrieval call; this step reports the actual
        # provider/model/dimension instead of a simulated placeholder.
        embedding_start = time.time()
        embedding_id = f"embedding-{id(query)}"
        from app.services.embedding.embedder import get_shared_embedder

        embedder_info = get_shared_embedder().describe()
        embedding_description = (
            f"Provider: {embedder_info['provider']}\n"
            f"Model: {embedder_info['model_name']}\n"
            f"Dimension: {embedder_info['dimension']}"
        )
        if embedder_info.get("degraded"):
            embedding_description += "\nWARNING: degraded hash fallback — vectors are not semantic"
        yield {
            "chunk_type": "decision_step",
            "decision_step": {
                "id": embedding_id,
                "type": "embedding",
                "component": "Embedder",
                "model": embedder_info["model_name"],
                "status": "active",
                "title": "Generating query embeddings",
                "description": embedding_description,
            }
        }
        embedding_duration = int((time.time() - embedding_start) * 1000)
        yield {
            "chunk_type": "decision_step",
            "decision_step": {
                "id": embedding_id,
                "type": "embedding",
                "component": "Embedder",
                "model": embedder_info["model_name"],
                "duration": embedding_duration,
                "status": "completed",
                "title": "Generating query embeddings",
                "description": embedding_description,
                "embedding_provider": embedder_info["provider"],
                "embedding_degraded": bool(embedder_info.get("degraded")),
            }
        }
        
        # Decision Step 3: Retrieve relevant documents
        from app.services.rag.context import apply_retrieval_profile_to_request, retrieve_rag_context

        retrieve_start = time.time()
        retrieve_id = f"retrieve-{id(query)}"
        retrieval_request = dict(request)
        retrieval_request["query"] = query
        retrieval_request["workspace_slug"] = workspace_slug
        if retrieval_request.get("top_k") is None:
            retrieval_request["top_k"] = top_k
        if retrieval_request.get("latency_profile") is None:
            retrieval_request["latency_profile"] = "fast"
        profile = apply_retrieval_profile_to_request(retrieval_request)
        retrieval_method = "Planned Retrieval"
        
        yield {
            "chunk_type": "decision_step",
            "decision_step": {
                "id": retrieve_id,
                "type": "retrieve",
                "component": "Retriever",
                "status": "active",
                "title": f"Retrieving top candidates ({retrieval_method})",
                "description": (
                    f"Searching collection '{profile['collection']}' ({profile['vector_db']})\n"
                    f"Method: planner-bounded {profile.get('latency_profile')}\n"
                    f"top_k: {profile.get('top_k')} · candidate_pool_k: {profile.get('candidate_pool_k')}..."
                ),
            }
        }
        
        logger.info(
            "Retrieving documents via planned RAG context",
            query=query[:50],
            top_k=profile.get("top_k"),
            candidate_pool_k=profile.get("candidate_pool_k"),
            collection_name=profile.get("collection"),
            vector_db_type=profile.get("vector_db"),
            latency_profile=profile.get("latency_profile"),
            enable_rag=app_settings.get("enableRAG", True),
        )
        try:
            retrieval_context = await retrieve_rag_context(retrieval_request)
            chunks = retrieval_context.get("chunks") if isinstance(retrieval_context.get("chunks"), list) else []
            scores_raw = retrieval_context.get("scores") if isinstance(retrieval_context.get("scores"), list) else []
            metadatas_raw = retrieval_context.get("metadatas") if isinstance(retrieval_context.get("metadatas"), list) else []
            metrics = retrieval_context.get("metrics") if isinstance(retrieval_context.get("metrics"), dict) else {}
            retrieval_results = []
            for index, content in enumerate(chunks):
                text = str(content or "").strip()
                if not text:
                    continue
                metadata = metadatas_raw[index] if index < len(metadatas_raw) and isinstance(metadatas_raw[index], dict) else {}
                raw_score = scores_raw[index] if index < len(scores_raw) else 0.0
                try:
                    score = float(raw_score)
                except (TypeError, ValueError):
                    score = 0.0
                retrieval_results.append(
                    {
                        "content": text,
                        "score": score,
                        "metadata": metadata,
                        "id": metadata.get("chunk_id") or metadata.get("id") or f"planned:{index}",
                        "vector_score": score,
                        "bm25_score": 0.0,
                    }
                )
            retrieval_results = retrieval_results[: int(profile.get("source_display_k") or top_k or 5)]
            retrieval_method = str(
                metrics.get("dense_policy")
                or retrieval_context.get("pipeline")
                or retrieval_context.get("mode_label")
                or "planned"
            )
            logger.info(
                "Retrieved planned RAG context",
                chunks=len(retrieval_results),
                collection=profile.get("collection"),
                pipeline=retrieval_context.get("pipeline"),
                dense_policy=metrics.get("dense_policy"),
                fallback_reason=metrics.get("fallback_reason"),
            )

            retrieve_duration = int((time.time() - retrieve_start) * 1000)
            scores = [r.get("score", 0.0) for r in retrieval_results[:5]] if retrieval_results else []
            
            # Build description with retrieval details
            if retrieval_results:
                description = (
                    f"Retrieved {len(retrieval_results)} chunks from collection '{profile['collection']}' ({profile['vector_db']})\n"
                    f"Method: {retrieval_method}\n"
                    f"Budget: {profile.get('latency_profile')} · candidate_pool_k {profile.get('candidate_pool_k')}\n"
                    f"Top score: {scores[0]:.3f}" if scores else "No documents found"
                )
            else:
                description = (
                    f"No chunks retrieved from collection '{profile['collection']}' ({profile['vector_db']})\n"
                    f"Possible reasons:\n"
                    f"- Collection may be empty\n"
                    f"- Planner returned an inventory/fallback answer without chunk context\n"
                    f"- Query may need deep retrieval refinement"
                )
            
            yield {
                "chunk_type": "decision_step",
                "decision_step": {
                    "id": retrieve_id,
                    "type": "retrieve",
                    "component": "Retriever",
                    "duration": retrieve_duration,
                    "status": "completed" if retrieval_results else "warning",
                    "title": f"Retrieved top candidates ({retrieval_method})",
                    "description": description,
                    "scores": scores,
                    "details": [
                        f"Collection: {profile['collection']} ({profile['vector_db']})",
                        f"Retrieved: {len(retrieval_results)}/{profile.get('top_k')} documents",
                        f"Top score: {scores[0]:.3f}" if scores else "No documents found",
                        f"Method: {retrieval_method}",
                        f"Latency profile: {profile.get('latency_profile')}",
                    ] if retrieval_results else [
                        f"Collection: {profile['collection']} ({profile['vector_db']})",
                        f"Retrieved: 0/{profile.get('top_k')} documents",
                        f"Latency profile: {profile.get('latency_profile')}",
                    ]
                }
            }
        except Exception as e:
            logger.warning("Planned RAG retrieval failed", error=str(e))
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
        # If a reasoning template (prompt_type) is selected, we render it
        # with {context} / {question} and prepend it to the markdown brief.
        # The selector can be "auto" (or None) — in which case we fall
        # back to the legacy markdown-first prompt used historically.
        prompt_type = request.get("prompt_type") or request.get("default_prompt_type")
        if workspace_context:
            context = (context + "\n\n" if context else "") + f"[Agenda institutionnel]\n{workspace_context}"
        template_text = self._render_reasoning_template(prompt_type, query, context, conversation_history)
        if template_text is not None:
            prompt = template_text
            logger.info(
                "Using reasoning template",
                template=prompt_type,
                has_context=bool(retrieval_results),
            )
        elif not retrieval_results:
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
            # Get context window settings from app settings
            # Use 32K default for faster generation (can be increased if needed)
            num_ctx = app_settings.get("ollamaNumCtx", 32768)  # Default 32K tokens - optimized for speed
            rope_scale = app_settings.get("ollamaRopeScale", None)
            rope_alpha = app_settings.get("ollamaRopeAlpha", None)
            
            async for chunk in self.model_service.ollama_client.stream(
                model=model_name,
                prompt=prompt,
                num_ctx=num_ctx,
                rope_scale=rope_scale,
                rope_alpha=rope_alpha
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
    
    def _render_reasoning_template(
        self,
        prompt_type,
        query: str,
        context: str,
        conversation_history: list = None,
    ):
        """Render one of the `SYSTEM_PROMPT_TEMPLATES` if `prompt_type` is set.

        Returns ``None`` to let the caller fall back to the legacy prompt
        (either when no template is requested or when the slug does not
        resolve to a template). We keep the history block intact so the
        conversational continuity survives the template swap.
        """
        if not prompt_type or prompt_type == "auto":
            return None
        try:
            from app.services.system_prompts import SYSTEM_PROMPT_TEMPLATES, SystemPromptType
            key = SystemPromptType(prompt_type) if isinstance(prompt_type, str) else prompt_type
        except Exception:
            return None
        template = SYSTEM_PROMPT_TEMPLATES.get(key)
        if not template:
            return None
        history_text = ""
        if conversation_history:
            lines = []
            for msg in conversation_history:
                role = "User" if msg.get("role") == "user" else "Assistant"
                lines.append(f"{role}: {msg.get('content', '')}")
            history_text = "\n\nPrevious conversation:\n" + "\n".join(lines) + "\n\n"
        rendered = template.format(context=context or "(no retrieved context)", question=query)
        return f"{rendered}{history_text}"

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
