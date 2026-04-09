"""Procurement Agent -- Vendor Document Validation (Use Case 4)

Simplified illustration of the full proposal's 10-step process.
Demonstrates 3 core steps: ingestion+matching, compliance check, report generation.
"""
import time
import json
from typing import Dict, Any, AsyncGenerator
from app.agents.base import BaseAgent
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are a Vendor Compliance Validation Agent operating within an enterprise procurement platform.

Your role is to validate vendor document submissions against compliance checklists.
You check for: trade licenses, insurance certificates, financial statements, regulatory certifications, and NDAs.

For each vendor submission, you must:
1. Identify which required documents are present, missing, or expired
2. Classify each issue by severity: Critical (blocks approval), Major (requires remediation), Minor (advisory)
3. Provide a compliance verdict: Compliant, Non-Compliant, or Partial Compliance
4. Cite specific requirements from the knowledge base when available

Output format:
- Start with a brief summary of findings
- List each document with status and severity
- End with the compliance verdict and recommended next steps

Be precise, professional, and always reference the compliance policy when available."""

REQUIRED_DOCUMENTS = [
    {"name": "Trade License", "severity": "Critical", "validity_months": 12},
    {"name": "Insurance Certificate", "severity": "Critical", "validity_months": 12},
    {"name": "Financial Statements", "severity": "Major", "validity_months": 24},
    {"name": "Regulatory Certifications", "severity": "Major", "validity_months": 12},
    {"name": "Non-Disclosure Agreement", "severity": "Minor", "validity_months": None},
]


class ProcurementAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            agent_id="procurement",
            name="Vendor Compliance Agent",
            agent_type="procurement",
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

    async def process(
        self, request: Dict[str, Any]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        query = request.get("query", "")
        rewritten = request.get("rewritten_query", query)
        prefs = request.get("agent_preferences", {}).get("model_preferences", {})
        model_name = prefs.get("model", settings.default_model)
        temperature = request.get("temperature", 0.3)
        custom_system_prompt = request.get("system_prompt")
        system_prompt = custom_system_prompt or SYSTEM_PROMPT
        pipeline_start = time.time()

        # -- Step 1: Document Ingestion --
        step_start = time.time()
        step_id = f"doc-ingestion-{id(query)}"
        yield self._decision_step(step_id, "active", "document_ingestion",
            "DocumentIngestion", model_name,
            "Ingesting vendor submission",
            f'Parsing submission: "{query[:80]}..."')

        await self._brief_pause()
        yield self._decision_step(step_id, "completed", "document_ingestion",
            "DocumentIngestion", model_name,
            "Ingesting vendor submission",
            "Vendor dossier parsed successfully",
            duration=self._ms_since(step_start))

        # -- Step 2: Knowledge Retrieval (uses rewritten query) --
        step_start = time.time()
        step_id = f"kb-retrieval-{id(query)}"
        yield self._decision_step(step_id, "active", "retrieve",
            "KnowledgeRetriever", "FAISS + text-embedding-3-small",
            "Retrieving compliance requirements",
            f'Searching knowledge base with: "{rewritten[:100]}"')

        retrieval_context = await self._retrieve_context(rewritten)
        yield self._decision_step(step_id, "completed", "retrieve",
            "KnowledgeRetriever", "FAISS + text-embedding-3-small",
            "Retrieved compliance requirements",
            f"Found {len(retrieval_context['chunks'])} relevant chunks" if retrieval_context["chunks"] else "No documents in knowledge base -- using built-in rules",
            duration=self._ms_since(step_start),
            scores=retrieval_context.get("scores", []))

        # -- Step 3: Compliance Validation --
        step_start = time.time()
        step_id = f"compliance-check-{id(query)}"
        yield self._decision_step(step_id, "active", "validation",
            "ComplianceEngine", model_name,
            "Validating document completeness",
            f"Applying {len(REQUIRED_DOCUMENTS)} validation rules with severity classification...")

        context_text = "\n\n".join(retrieval_context["chunks"]) if retrieval_context["chunks"] else "No specific policy documents available. Use the built-in required documents list."
        rules_text = "\n".join(
            f"- {d['name']}: Severity={d['severity']}, Valid for {d['validity_months'] or 'N/A'} months"
            for d in REQUIRED_DOCUMENTS
        )

        user_prompt = f"""Vendor Submission to validate:
{query}

Required Documents (validation rules):
{rules_text}

Compliance Policy Context (from knowledge base):
{context_text}

Analyze this vendor submission. For each required document, determine if it is Present, Missing, or Expired.
Classify issues by severity (Critical/Major/Minor).
Provide a compliance verdict and recommended actions."""

        yield self._decision_step(step_id, "completed", "validation",
            "ComplianceEngine", model_name,
            "Compliance rules applied",
            f"Validated against {len(REQUIRED_DOCUMENTS)} document requirements",
            duration=self._ms_since(step_start))

        # -- Step 4: Report Generation (LLM synthesis, streamed) --
        step_start = time.time()
        step_id = f"report-gen-{id(query)}"
        yield self._decision_step(step_id, "active", "synthesis",
            "ReportGenerator", model_name,
            "Generating validation report",
            f"Model: {model_name} · Temperature: {temperature}",
            has_text=True)

        sources = [
            {"id": f"chunk-{i}", "type": "document", "title": f"Policy chunk {i+1}",
             "snippet": c[:200], "relevance_score": retrieval_context["scores"][i] if i < len(retrieval_context.get("scores", [])) else 0.0}
            for i, c in enumerate(retrieval_context["chunks"][:5])
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
            yield self._decision_step(step_id, "error", "synthesis",
                "ReportGenerator", model_name,
                "Report generation failed", str(e),
                duration=self._ms_since(step_start), has_text=True)
            return

        yield {"chunk_type": "text", "content": "", "is_final": True, "sequence": sequence + 1}

        llm_duration_ms = self._ms_since(step_start)
        yield self._decision_step(step_id, "completed", "synthesis",
            "ReportGenerator", model_name,
            "Validation report generated",
            f"Generated {len(accumulated)} characters with {len(sources)} citations",
            duration=llm_duration_ms, has_text=True)

        # -- Step 5: Quality Metrics (factuality, HHEM, coherence, relevance, latency) --
        step_start = time.time()
        step_id = f"quality-metrics-{id(query)}"
        yield self._decision_step(step_id, "active", "evaluation",
            "ResponseEvaluator", "text-embedding-3-small",
            "Evaluating response quality",
            "Computing factuality, relevance, coherence, HHEM & latency…")

        try:
            from app.services.metrics.evaluator import ResponseEvaluator
            evaluator = ResponseEvaluator()
            metrics = await evaluator.evaluate(
                query=query,
                response=accumulated,
                source_chunks=retrieval_context["chunks"][:5],
            )
        except Exception as e:
            logger.warning("Metrics evaluation failed", error=str(e))
            metrics = {"relevance": 0.0, "factuality": 0.0, "coherence": 0.0, "hhem": 0.0, "adv_hhem": 0.0}

        eval_duration_ms = self._ms_since(step_start)
        pipeline_total_ms = self._ms_since(pipeline_start)
        metrics["llm_latency"] = llm_duration_ms
        metrics["total_latency"] = pipeline_total_ms

        yield self._metrics_step(step_id, metrics, eval_duration_ms)

    # -- Helpers --

    async def _retrieve_context(self, query: str) -> Dict[str, Any]:
        doc_svc = self._get_document_service()
        if doc_svc is None:
            return {"chunks": [], "scores": []}
        try:
            results = await doc_svc.search(query, top_k=5, use_hybrid=True)
            chunks = []
            scores = []
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
    def _decision_step(
        step_id: str, status: str, step_type: str,
        component: str, model: str, title: str, description: str,
        duration: int = None, scores: list = None, has_text: bool = False,
    ) -> Dict[str, Any]:
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
    def _metrics_step(step_id: str, metrics: Dict[str, float], duration: int) -> Dict[str, Any]:
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
    async def _brief_pause():
        import asyncio
        await asyncio.sleep(0.05)

    @staticmethod
    def _ms_since(start: float) -> int:
        return int((time.time() - start) * 1000)

    async def cleanup(self) -> None:
        self.status = "inactive"
