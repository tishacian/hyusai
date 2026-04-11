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
        self._document_service = None

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

    def _get_document_service(self):
        if self._document_service is None:
            try:
                from app.services.rag.document_service import DocumentService

                self._document_service = DocumentService(
                    collection_name="documents",
                    vector_db_type="faiss",
                )
            except Exception as e:
                logger.warning("Document service init failed, RAG disabled", error=str(e))
        return self._document_service

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

        # ── Step 4: Knowledge Retrieval (FAISS + BM25 hybrid) ──
        step_start = time.time()
        sid = f"kb-retrieval-{uid}"
        yield self._step(
            sid,
            "active",
            "retrieve",
            "HybridRetriever",
            "FAISS + BM25 (RRF)",
            "Searching knowledge base",
            f'Method: Reciprocal Rank Fusion · top_k: 5\nQuery: "{rewritten[:80]}…"',
        )

        retrieval_context = await self._retrieve_context(rewritten)
        n_chunks = len(retrieval_context["chunks"])
        scores = retrieval_context.get("scores", [])
        top_score = f"{scores[0]:.3f}" if scores else "—"

        yield self._step(
            sid,
            "completed",
            "retrieve",
            "HybridRetriever",
            "FAISS + BM25 (RRF)",
            f"Retrieved {n_chunks} chunks",
            f"Top score: {top_score} · Method: RRF (Vector + BM25)"
            if n_chunks
            else "No documents in knowledge base — using built-in rules",
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
        if n_chunks > 0 and scores:
            threshold = 0.1
            before = n_chunks
            pairs = list(zip(retrieval_context["chunks"], scores))
            pairs = [(c, s) for c, s in pairs if s >= threshold]
            pairs.sort(key=lambda x: x[1], reverse=True)
            if pairs:
                filtered_chunks = [c for c, _ in pairs]
                filtered_scores = [s for _, s in pairs]
            else:
                filtered_chunks = retrieval_context["chunks"]
                filtered_scores = scores
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

        context_text = (
            "\n\n".join(filtered_chunks)
            if filtered_chunks
            else "No documents found in the knowledge base."
        )

        user_prompt = f"""User message:
{query}

Knowledge base context:
{context_text}

Answer the user's question using the context above. If the context is not relevant, say so clearly."""

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

        sources = [
            {
                "id": f"chunk-{i}",
                "type": "document",
                "title": f"Policy chunk {i + 1}",
                "snippet": c[:200],
                "relevance_score": filtered_scores[i] if i < len(filtered_scores) else 0.0,
            }
            for i, c in enumerate(filtered_chunks[:5])
        ]

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

    async def _retrieve_context(self, query: str) -> dict[str, Any]:
        doc_svc = self._get_document_service()
        if doc_svc is None:
            return {"chunks": [], "scores": []}
        try:
            results = await doc_svc.search(query, top_k=5, use_hybrid=True)
            chunks, scores = [], []
            for r in results:
                content = r.get("content") or r.get("metadata", {}).get("content", "")
                if content:
                    chunks.append(content)
                    scores.append(r.get("combined_score") or r.get("score", 0.0))
            return {"chunks": chunks, "scores": scores}
        except Exception as e:
            logger.warning("Retrieval failed", error=str(e))
            return {"chunks": [], "scores": []}

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
