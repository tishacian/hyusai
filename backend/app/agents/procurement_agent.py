"""RAG Agent -- Generic RAG pipeline

Full execution streaming pipeline with real-time SSE decision_step events.
"""

import asyncio
import time
from typing import Any, AsyncGenerator

from app.agents.base import BaseAgent
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are an intelligent assistant with access to a curated knowledge base.

Answer questions accurately and concisely using the retrieved context.
When the context contains relevant information, cite it specifically.
If no relevant context is available, say so clearly rather than guessing.

Be professional, precise, and helpful."""


class OmniRAGAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            agent_id="rag",
            name="RAG Agent",
            agent_type="rag",
        )
        self._llm = None
        # Cache DocumentService instances by (workspace_slug, collection, vector_db_type)
        # so we don't rebuild the reranker + BM25 on every request, but still keep
        # each tenant's index isolated. A single shared instance (the pre-D8
        # behaviour) routed every workspace to the same unscoped collection and
        # never honored the per-workspace `ragVectorDBType` preset — drop-and-ask
        # uploads went to FAISS while this agent read from Qdrant.
        self._document_services: dict[tuple[str | None, str, str], Any] = {}

    async def initialize(self) -> None:
        self.status = "active"
        logger.info("Procurement agent initialized")

    def _get_llm(self):
        if self._llm is None:
            from app.llm.llm import LLM

            self._llm = LLM(
                provider=settings.default_provider,
                api_key=settings.openai_api_key,
            )
        return self._llm

    def _get_document_service(self, request: dict[str, Any] | None = None):
        """Return a DocumentService scoped to the request's workspace.

        Resolution order for ``vector_db_type`` / ``collection_name``:
          1. The workspace's resolved RAG preset (`get_resolved_settings`).
          2. Static defaults (`faiss` / `documents`) — matches
             ``_get_default_settings`` and keeps upload and retrieval
             symmetric.

        ``workspace_slug`` is taken verbatim from the request so that the
        FAISS/Qdrant/Chroma factory can prefix the collection with
        ``<slug>__``, giving the same isolation the dropzone upload path
        already uses.
        """
        from app.core.settings_manager import get_resolved_settings
        from app.services.rag.document_service import DocumentService

        request = request or {}
        workspace_slug = request.get("workspace_slug")
        app_settings = get_resolved_settings(
            workspace_id=request.get("workspace_id"),
            capability_id=request.get("capability_id"),
            system_id=request.get("system_id"),
        )
        collection_name = app_settings.get("ragCollectionName", "documents")
        vector_db_type = app_settings.get("ragVectorDBType", "faiss")

        cache_key = (workspace_slug, collection_name, vector_db_type)
        svc = self._document_services.get(cache_key)
        if svc is not None:
            return svc

        try:
            svc = DocumentService(
                collection_name=collection_name,
                vector_db_type=vector_db_type,
                workspace_slug=workspace_slug,
            )
            self._document_services[cache_key] = svc
            logger.info(
                "rag_agent: DocumentService ready",
                workspace_slug=workspace_slug,
                collection=collection_name,
                vector_db=vector_db_type,
            )
            return svc
        except Exception as e:
            logger.warning(
                "Document service init failed, RAG disabled",
                error=str(e),
                workspace_slug=workspace_slug,
            )
            return None

    async def process(self, request: dict[str, Any]) -> AsyncGenerator[dict[str, Any], None]:
        query = request.get("query", "")
        rewritten = request.get("rewritten_query", query)
        prefs = request.get("agent_preferences", {}).get("model_preferences", {})
        model_name = prefs.get("model", settings.default_model)
        temperature = request.get("temperature", 0.3)
        custom_system_prompt = request.get("system_prompt")
        system_prompt = custom_system_prompt or SYSTEM_PROMPT
        pipeline_start = time.time()

        uid = id(query)

        # ── Step 1: Query Received ──
        step_start = time.time()
        sid = f"query-received-{uid}"
        yield self._step(
            sid,
            "active",
            "query_received",
            "QueryReceiver",
            model_name,
            "Receiving and parsing query",
            f'Input: "{query[:120]}"',
        )
        await asyncio.sleep(0.03)
        is_question = any(query.strip().endswith(c) for c in ["?", "？"]) or any(
            query.lower().startswith(w)
            for w in [
                "what ",
                "which ",
                "how ",
                "who ",
                "when ",
                "where ",
                "why ",
                "is ",
                "are ",
                "can ",
                "do ",
                "does ",
            ]
        )
        intent = "Q&A / Question" if is_question else "Document / Data Processing"
        yield self._step(
            sid,
            "completed",
            "query_received",
            "QueryReceiver",
            model_name,
            "Query received",
            f"Intent: {intent} · Length: {len(query)} chars",
            duration=self._ms_since(step_start),
        )

        # ── Step 2: Query Rewrite ──
        step_start = time.time()
        sid = f"query-rewrite-{uid}"
        yield self._step(
            sid,
            "active",
            "query_rewrite",
            "QueryRewriter",
            "gpt-4o-mini",
            "Rewriting query for optimal retrieval",
            f'Original: "{query[:80]}…"',
        )

        has_rewrite = rewritten != query
        await asyncio.sleep(0.02)
        yield self._step(
            sid,
            "completed",
            "query_rewrite",
            "QueryRewriter",
            "gpt-4o-mini",
            "Query rewritten" if has_rewrite else "Query kept as-is",
            f'Rewritten: "{rewritten[:100]}"'
            if has_rewrite
            else "No rewrite needed — query already well-formed",
            duration=self._ms_since(step_start),
        )

        # ── Step 3: Embedding Generation ──
        step_start = time.time()
        sid = f"embedding-{uid}"
        yield self._step(
            sid,
            "active",
            "embedding",
            "Embedder",
            "text-embedding-3-small",
            "Generating query embeddings",
            "Dimension: 1536 · Model: text-embedding-3-small",
        )
        await asyncio.sleep(0.04)
        yield self._step(
            sid,
            "completed",
            "embedding",
            "Embedder",
            "text-embedding-3-small",
            "Query embedded",
            "Vector generated — ready for similarity search",
            duration=self._ms_since(step_start),
        )

        # ── Step 4: Knowledge Retrieval (naive / hybrid / HAH-like / C-HAH-like on DocumentService) ──
        from app.services.rag.mode_selector import resolve_retrieval_mode
        from app.services.rag.pipeline_retrieval import retrieve_for_mode

        rag_mode = request.get("rag_pipeline_mode") or (
            request.get("agent_preferences") or {}
        ).get("rag_pipeline_mode")
        doc_svc = self._get_document_service(request)
        use_hybrid, mode_label, mode_reason = await resolve_retrieval_mode(
            doc_svc, rewritten, rag_mode
        )
        retriever_name = "HybridRetriever" if use_hybrid else "VectorRetriever"
        retriever_title = (
            "FAISS + BM25 (RRF)" if use_hybrid else "FAISS dense (naive)"
        )
        method_line = (
            "Method: Reciprocal Rank Fusion · top_k: 5"
            if use_hybrid
            else "Method: dense vector similarity · top_k: 5"
        )
        if mode_label == "hah_backend":
            retriever_name = "HAHBackendRetriever"
            retriever_title = "Two-pass hybrid + RRF (HAH-like)"
            method_line = "Method: pass1 hybrid → pseudo-document → pass2 hybrid → RRF merge · top_k: 5"
        elif mode_label == "chah_backend":
            retriever_name = "CHAHBackendRetriever"
            retriever_title = "Parallel hybrid + RRF (C-HAH-like)"
            method_line = "Method: parallel hybrid over query variants → RRF merge · top_k: 5"

        step_start = time.time()
        sid = f"kb-retrieval-{uid}"
        yield self._step(
            sid,
            "active",
            "retrieve",
            retriever_name,
            retriever_title,
            "Searching knowledge base",
            f"{mode_label} — {mode_reason}\n{method_line}\nQuery: \"{rewritten[:80]}…\"",
        )

        pr = await retrieve_for_mode(
            doc_svc,
            rewritten,
            rag_mode,
            top_k=5,
            use_hybrid=use_hybrid,
            hah_chah_enabled=settings.rag_hah_chah_enabled,
        )
        retrieval_context = {
            "chunks": pr.chunks,
            "scores": pr.scores,
            "metadatas": pr.metadatas,
        }
        n_chunks = len(retrieval_context["chunks"])
        scores = retrieval_context.get("scores", [])
        top_score = f"{scores[0]:.3f}" if scores else "—"
        if pr.pipeline == "hah_backend":
            done_method = "HAH-like two-pass + RRF"
        elif pr.pipeline == "chah_backend":
            done_method = "C-HAH-like parallel + RRF"
        else:
            done_method = (
                "RRF (Vector + BM25)" if use_hybrid else "Dense cosine similarity"
            )

        done_detail = (
            f"Top score: {top_score} · {done_method}"
            if n_chunks
            else "No documents in knowledge base — using built-in rules"
        )
        if n_chunks and pr.detail:
            done_detail = f"{done_detail}\n{pr.detail}"

        yield self._step(
            sid,
            "completed",
            "retrieve",
            retriever_name,
            retriever_title,
            f"Retrieved {n_chunks} chunks",
            done_detail,
            duration=self._ms_since(step_start),
            scores=scores[:5],
        )

        # ── Step 5: Context Filtering & Reranking ──
        step_start = time.time()
        sid = f"context-filter-{uid}"
        yield self._step(
            sid,
            "active",
            "context_filtering",
            "ContextFilter",
            "text-embedding-3-small",
            "Filtering and reranking contexts",
            f"Evaluating {n_chunks} chunks for relevance…",
        )

        filtered_chunks = retrieval_context["chunks"]
        filtered_scores = scores
        filtered_metadatas = retrieval_context.get("metadatas", []) or []
        # Make sure we always have a metadata entry per chunk even if the
        # retrieval pipeline is an older build that never populated it —
        # sources/prompt paths below rely on index alignment.
        if len(filtered_metadatas) < len(filtered_chunks):
            filtered_metadatas = filtered_metadatas + [{}] * (
                len(filtered_chunks) - len(filtered_metadatas)
            )
        if n_chunks > 0 and scores:
            threshold = 0.1
            before = n_chunks
            triples = list(zip(retrieval_context["chunks"], scores, filtered_metadatas))
            triples = [(c, s, m) for c, s, m in triples if s >= threshold]
            triples.sort(key=lambda x: x[1], reverse=True)
            if triples:
                filtered_chunks = [c for c, _, _ in triples]
                filtered_scores = [s for _, s, _ in triples]
                filtered_metadatas = [m for _, _, m in triples]
            else:
                filtered_chunks = retrieval_context["chunks"]
                filtered_scores = scores
                filtered_metadatas = retrieval_context.get("metadatas", []) or [
                    {} for _ in filtered_chunks
                ]
            after = len(filtered_chunks)
        else:
            before = after = 0

        await asyncio.sleep(0.02)
        yield self._step(
            sid,
            "completed",
            "context_filtering",
            "ContextFilter",
            "text-embedding-3-small",
            "Context filtered",
            f"Kept {after}/{before} chunks · Threshold: 0.1 · Sorted by relevance",
            duration=self._ms_since(step_start),
        )

        # ── Step 6: Knowledge Synthesis ──
        step_start = time.time()
        sid = f"synthesis-prep-{uid}"
        yield self._step(
            sid,
            "active",
            "validation",
            "KnowledgeSynthesizer",
            model_name,
            "Preparing knowledge context",
            f"Assembling {after} chunks for synthesis…",
        )

        # Build a citation-friendly context block: each chunk is prefixed with
        # its document title (docmeta-sourced when available, filename
        # otherwise). This helps the LLM attribute quotes back to the right
        # source and lets follow-up questions reference by name.
        def _display_title(meta: dict[str, Any]) -> str:
            title = (meta.get("document_title") or "").strip()
            if title:
                return title
            filename = (meta.get("document_filename") or "").strip()
            return filename or "Untitled document"

        if filtered_chunks:
            context_blocks: list[str] = []
            for idx, chunk in enumerate(filtered_chunks):
                meta = filtered_metadatas[idx] if idx < len(filtered_metadatas) else {}
                title = _display_title(meta)
                page = meta.get("page")
                header = f"[{idx + 1}] {title}"
                if page is not None:
                    header = f"{header} (p. {page})"
                context_blocks.append(f"{header}\n{chunk}")
            context_text = "\n\n".join(context_blocks)
        else:
            context_text = "No documents found in the knowledge base."

        # Aggregate docmeta TF-IDF keywords across the top chunks so the LLM
        # can anchor on document topics even when the user's query is fuzzy
        # ("c'est quoi ce doc ?"). We keep it short (top 10 unique) so it
        # adds zero cost to the prompt in normal cases and degrades
        # gracefully when docmeta didn't run (empty list).
        keyword_seen: set[str] = set()
        aggregated_keywords: list[str] = []
        for meta in filtered_metadatas[:5]:
            for kw in meta.get("document_extracted_keywords") or []:
                if not isinstance(kw, str):
                    continue
                normalised = kw.strip().lower()
                if not normalised or normalised in keyword_seen:
                    continue
                keyword_seen.add(normalised)
                aggregated_keywords.append(kw.strip())
                if len(aggregated_keywords) >= 10:
                    break
            if len(aggregated_keywords) >= 10:
                break

        keyword_hint = (
            f"\n\nDocument keywords (from TF-IDF over retrieved chunks): "
            f"{', '.join(aggregated_keywords)}"
            if aggregated_keywords
            else ""
        )

        user_prompt = f"""User message:
{query}

Knowledge base context:
{context_text}{keyword_hint}

Answer the user's question using the context above. Cite sources by their
[number] when relevant. If the context is not relevant, say so clearly."""

        await asyncio.sleep(0.03)
        yield self._step(
            sid,
            "completed",
            "validation",
            "KnowledgeSynthesizer",
            model_name,
            "Context ready",
            f"{after} chunks · {len(context_text)} chars",
            duration=self._ms_since(step_start),
        )

        # ── Step 7: Response Generation (LLM synthesis, streamed) ──
        step_start = time.time()
        sid = f"synthesis-{uid}"
        yield self._step(
            sid,
            "active",
            "synthesis",
            "Synthesizer",
            model_name,
            "Generating response",
            f"Model: {model_name} · Temperature: {temperature} · Streaming…",
            has_text=True,
        )

        # Build real citations from the chunk metadata we now keep in lockstep
        # with ``filtered_chunks``. Prefer docmeta-sourced ``document_title``
        # (e.g. the PDF's embedded title), fall back to the filename, and
        # surface page numbers + docmeta keywords when available so the UI
        # source panel can render something useful instead of the legacy
        # "Policy chunk N" placeholder.
        sources: list[dict[str, Any]] = []
        for i, c in enumerate(filtered_chunks[:5]):
            meta = filtered_metadatas[i] if i < len(filtered_metadatas) else {}
            source_entry: dict[str, Any] = {
                "id": f"chunk-{i}",
                "type": "document",
                "title": _display_title(meta),
                "snippet": c[:200],
                "relevance_score": filtered_scores[i] if i < len(filtered_scores) else 0.0,
            }
            document_id = meta.get("document_id")
            if document_id:
                source_entry["document_id"] = document_id
            filename = meta.get("document_filename")
            if filename:
                source_entry["filename"] = filename
            page = meta.get("page")
            if page is not None:
                source_entry["page"] = page
            keywords = meta.get("document_extracted_keywords")
            if keywords:
                source_entry["keywords"] = list(keywords)[:5]
            author = meta.get("document_author")
            if author:
                source_entry["author"] = author
            num_pages = meta.get("document_num_pages")
            if num_pages is not None:
                source_entry["num_pages"] = num_pages
            sources.append(source_entry)

        sequence = 0
        accumulated = ""
        try:
            llm = self._get_llm()
            async for chunk_text in llm.stream_complete(
                prompt=user_prompt,
                model=model_name,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=2000,
            ):
                sequence += 1
                accumulated += chunk_text
                yield {
                    "chunk_type": "text",
                    "content": chunk_text,
                    "delta": chunk_text,
                    "sources": sources if sequence == 1 else None,
                    "sequence": sequence,
                    "is_final": False,
                }
        except Exception as e:
            logger.error("LLM generation failed", error=str(e))
            yield {"chunk_type": "error", "content": f"LLM generation error: {e}", "is_final": True}
            yield self._step(
                sid,
                "error",
                "synthesis",
                "Synthesizer",
                model_name,
                "Generation failed",
                str(e),
                duration=self._ms_since(step_start),
                has_text=True,
            )
            return

        yield {"chunk_type": "text", "content": "", "is_final": True, "sequence": sequence + 1}

        llm_duration_ms = self._ms_since(step_start)
        yield self._step(
            sid,
            "completed",
            "synthesis",
            "Synthesizer",
            model_name,
            "Response generated",
            f"{len(accumulated)} chars · {len(sources)} citations · {sequence} tokens streamed",
            duration=llm_duration_ms,
            has_text=True,
        )

        # ── Step 8: Quality Metrics ──
        step_start = time.time()
        sid = f"quality-metrics-{uid}"
        yield self._step(
            sid,
            "active",
            "evaluation",
            "ResponseEvaluator",
            "text-embedding-3-small",
            "Evaluating response quality",
            "Computing factuality, relevance, coherence, HHEM & latency…",
        )

        try:
            from app.services.metrics.evaluator import ResponseEvaluator

            evaluator = ResponseEvaluator()
            metrics = await evaluator.evaluate(
                query=query,
                response=accumulated,
                source_chunks=filtered_chunks[:5],
            )
        except Exception as e:
            logger.warning("Metrics evaluation failed", error=str(e))
            metrics = {
                "relevance": 0.0,
                "factuality": 0.0,
                "coherence": 0.0,
                "hhem": 0.0,
                "adv_hhem": 0.0,
            }

        eval_duration_ms = self._ms_since(step_start)
        pipeline_total_ms = self._ms_since(pipeline_start)
        metrics["llm_latency"] = llm_duration_ms
        metrics["total_latency"] = pipeline_total_ms

        yield self._metrics_step(sid, metrics, eval_duration_ms)

    # ── Helpers ──

    async def _retrieve_context(
        self,
        query: str,
        use_hybrid: bool = True,
        request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        doc_svc = self._get_document_service(request)
        if doc_svc is None:
            return {"chunks": [], "scores": [], "metadatas": []}
        try:
            results = await doc_svc.search(query, top_k=5, use_hybrid=use_hybrid)
            chunks, scores, metadatas = [], [], []
            for r in results:
                metadata = r.get("metadata", {}) or {}
                content = r.get("content") or metadata.get("content", "")
                if content:
                    chunks.append(content)
                    scores.append(r.get("combined_score") or r.get("score", 0.0))
                    # Keep the full chunk metadata alongside the text so the
                    # caller can build real citations (document_title, page,
                    # docmeta-sourced keywords) instead of "Policy chunk N".
                    metadatas.append(metadata)
            return {"chunks": chunks, "scores": scores, "metadatas": metadatas}
        except Exception as e:
            logger.warning("Retrieval failed", error=str(e))
            return {"chunks": [], "scores": [], "metadatas": []}

    @staticmethod
    def _step(
        step_id: str,
        status: str,
        step_type: str,
        component: str,
        model: str,
        title: str,
        description: str,
        duration: int = None,
        scores: list = None,
        has_text: bool = False,
    ) -> dict[str, Any]:
        step = {
            "id": step_id,
            "type": step_type,
            "component": component,
            "model": model,
            "status": status,
            "title": title,
            "description": description,
        }
        if duration is not None:
            step["duration"] = duration
        if scores:
            step["scores"] = scores
        if has_text:
            step["hasTextGeneration"] = True
        return {"chunk_type": "decision_step", "decision_step": step}

    @staticmethod
    def _metrics_step(step_id: str, metrics: dict[str, float], duration: int) -> dict[str, Any]:
        return {
            "chunk_type": "decision_step",
            "decision_step": {
                "id": step_id,
                "type": "evaluation",
                "component": "ResponseEvaluator",
                "model": "text-embedding-3-small",
                "status": "completed",
                "title": "Response quality evaluation",
                "description": " · ".join(f"{k}: {v:.2f}" for k, v in metrics.items()),
                "duration": duration,
                "metrics": metrics,
            },
        }

    @staticmethod
    def _ms_since(start: float) -> int:
        return int((time.time() - start) * 1000)

    async def cleanup(self) -> None:
        self.status = "inactive"
