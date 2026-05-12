"""Seed catalog of canonical Skills + universal Capabilities.

Each entry in `SEED_SKILLS` is a wrapper around an existing OmniRAG
endpoint. The actual `invoke()` callable is registered in
`backend/app/services/skills_registry/wrappers.py`; here we only declare
the typed contracts so the registry is queryable from `/skills` without
the runtime needing to be alive.
"""
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy.orm import Session as DBSession

from app.models.capability import Capability
from app.models.skill import Skill


# ---- Skills ----------------------------------------------------------------
# (slug, version, name, description, type, provider, certification, execution,
#  pricing, input_schema, output_schema)
SEED_SKILLS: List[Dict[str, Any]] = [
    {
        "slug": "llm_rag_answer_v1",
        "version": "1",
        "name": "RAG Answer",
        "description": "Streamed retrieval-augmented answer with citations and decision steps.",
        "type": "rag",
        "provider": "internal",
        "certification_level": "production",
        "execution": {"mode": "stream", "timeout_ms": 60_000, "retryable": True, "idempotent": False},
        "pricing": {"unit": "per_call", "unit_price": 0.012, "currency": "USD"},
        "input_schema": {"type": "object", "required": ["query"], "properties": {
            "query": {"type": "string"},
            "context_id": {"type": "string"},
        }},
        "output_schema": {"type": "object", "properties": {
            "answer": {"type": "string"},
            "citations": {"type": "array"},
            "decision_steps": {"type": "array"},
        }},
    },
    {
        "slug": "semantic_search_v1",
        "version": "1",
        "name": "Semantic Search",
        "description": "Vector + lexical hybrid search over the knowledge base.",
        "type": "retrieval",
        "provider": "internal",
        "certification_level": "production",
        "execution": {"mode": "sync", "timeout_ms": 8_000, "retryable": True, "idempotent": True},
        "pricing": {"unit": "per_call", "unit_price": 0.0008, "currency": "USD"},
        "input_schema": {"type": "object", "required": ["query"], "properties": {
            "query": {"type": "string"},
            "top_k": {"type": "integer", "default": 5},
        }},
        "output_schema": {"type": "object", "properties": {
            "results": {"type": "array"},
        }},
    },
    {
        "slug": "document_ingestion_v1",
        "version": "1",
        "name": "Document Ingestion",
        "description": "Parse and embed a document into the knowledge base.",
        "type": "ingestion",
        "provider": "internal",
        "certification_level": "production",
        "execution": {"mode": "async", "timeout_ms": 120_000, "retryable": True, "idempotent": True},
        "pricing": {"unit": "per_doc", "unit_price": 0.04, "currency": "USD"},
        "input_schema": {"type": "object", "required": ["filename"], "properties": {
            "filename": {"type": "string"},
            "collection": {"type": "string"},
        }},
        "output_schema": {"type": "object", "properties": {
            "doc_id": {"type": "string"},
            "chunks": {"type": "integer"},
        }},
    },
    {
        "slug": "eval_radar_v1",
        "version": "1",
        "name": "Evaluation Radar",
        "description": "Multi-axis evaluation (groundedness, relevance, recall, latency, safety).",
        "type": "analysis",
        "provider": "internal",
        "certification_level": "production",
        "execution": {"mode": "sync", "timeout_ms": 30_000, "retryable": False, "idempotent": True},
        "pricing": {"unit": "per_call", "unit_price": 0.02, "currency": "USD"},
        "input_schema": {"type": "object", "required": ["answer"], "properties": {
            "answer": {"type": "string"},
            "ground_truth": {"type": "string"},
        }},
        "output_schema": {"type": "object", "properties": {
            "axes": {"type": "object"},
            "overall": {"type": "number"},
        }},
    },
    {
        "slug": "claim_audit_v1",
        "version": "1",
        "name": "Claim Audit",
        "description": "Verifies factual claims in an answer against the citations.",
        "type": "analysis",
        "provider": "internal",
        "certification_level": "production",
        "execution": {"mode": "sync", "timeout_ms": 30_000, "retryable": False, "idempotent": True},
        "pricing": {"unit": "per_call", "unit_price": 0.025, "currency": "USD"},
        "input_schema": {"type": "object", "required": ["answer"], "properties": {
            "answer": {"type": "string"},
            "citations": {"type": "array"},
        }},
        "output_schema": {"type": "object", "properties": {
            "claims": {"type": "array"},
            "verdict": {"type": "string"},
        }},
    },
    {
        "slug": "intelligence_batch_v1",
        "version": "1",
        "name": "Intelligence Batch",
        "description": "Pulls feeds, deduplicates, scores and stores articles for a campaign.",
        "type": "ingestion",
        "provider": "internal",
        "certification_level": "production",
        "execution": {"mode": "async", "timeout_ms": 600_000, "retryable": True, "idempotent": False},
        "pricing": {"unit": "per_batch", "unit_price": 0.5, "currency": "USD"},
        "input_schema": {"type": "object", "properties": {
            "feed_ids": {"type": "array"},
        }},
        "output_schema": {"type": "object", "properties": {
            "ingested": {"type": "integer"},
            "errors": {"type": "integer"},
        }},
    },
    {
        "slug": "sharepoint_ingestion_v1",
        "version": "1",
        "name": "SharePoint Ingestion",
        "description": "Synchronizes a SharePoint library into a knowledge collection.",
        "type": "ingestion",
        "provider": "microsoft",
        "certification_level": "production",
        "execution": {"mode": "async", "timeout_ms": 1_800_000, "retryable": True, "idempotent": False},
        "pricing": {"unit": "per_file", "unit_price": 0.06, "currency": "USD"},
        "input_schema": {"type": "object", "required": ["site_url"], "properties": {
            "site_url": {"type": "string"},
            "library": {"type": "string"},
        }},
        "output_schema": {"type": "object", "properties": {
            "files": {"type": "integer"},
            "skipped": {"type": "integer"},
        }},
    },
    {
        "slug": "voice_transcribe_v1",
        "version": "1",
        "name": "Voice Transcribe",
        "description": "Phase 0 speech-to-text for recorded expert turns, backed by the active VoiceRuntimeProvider.",
        "type": "voice",
        "provider": "internal",
        "certification_level": "production",
        "execution": {"mode": "sync", "timeout_ms": 60_000, "retryable": True, "idempotent": False},
        "pricing": {"unit": "per_minute", "unit_price": 0.012, "currency": "USD"},
        "input_schema": {"type": "object", "required": ["audio_ref"], "properties": {
            "audio_ref": {"type": "string"},
            "audio_base64": {"type": "string"},
            "filename": {"type": "string"},
            "content_type": {"type": "string"},
        }},
        "output_schema": {"type": "object", "properties": {
            "transcript": {"type": "string"},
            "model": {"type": "string"},
        }},
    },
    {
        "slug": "voice_tts_v1",
        "version": "1",
        "name": "Voice TTS",
        "description": "Segmented text-to-speech with selectable voices for guided capture sessions.",
        "type": "voice",
        "provider": "internal",
        "certification_level": "production",
        "execution": {"mode": "stream", "timeout_ms": 30_000, "retryable": True, "idempotent": True},
        "pricing": {"unit": "per_char", "unit_price": 0.00002, "currency": "USD"},
        "input_schema": {"type": "object", "required": ["text"], "properties": {
            "text": {"type": "string"},
            "voice": {"type": "string"},
        }},
        "output_schema": {"type": "object", "properties": {
            "audio_url": {"type": "string"},
            "audio_base64": {"type": "string"},
            "content_type": {"type": "string"},
            "model": {"type": "string"},
        }},
    },
    {
        "slug": "voice_realtime_session_v1",
        "version": "1",
        "name": "Voice Realtime Session",
        "description": "Starts a provider-neutral realtime voice session with explicit provider, model, transport and fallback policy.",
        "type": "voice",
        "provider": "internal",
        "certification_level": "beta",
        "execution": {"mode": "stream", "timeout_ms": 30_000, "retryable": True, "idempotent": False},
        "pricing": {"unit": "per_session", "unit_price": 0.02, "currency": "USD"},
        "input_schema": {"type": "object", "properties": {
            "provider": {"type": "string"},
            "model": {"type": "string"},
            "transport": {"type": "string"},
            "language": {"type": "string"},
            "voice": {"type": "string"},
            "fallback_policy": {"type": "string"},
        }},
        "output_schema": {"type": "object", "properties": {
            "provider": {"type": "string"},
            "transport": {"type": "string"},
            "events": {"type": "array"},
            "capabilities": {"type": "object"},
        }},
    },
    {
        "slug": "voice_realtime_transcribe_v1",
        "version": "1",
        "name": "Voice Realtime Transcribe",
        "description": "Emits text.partial/text.final events from a realtime or cascade transcription provider.",
        "type": "voice",
        "provider": "internal",
        "certification_level": "beta",
        "execution": {"mode": "stream", "timeout_ms": 60_000, "retryable": True, "idempotent": False},
        "pricing": {"unit": "per_minute", "unit_price": 0.012, "currency": "USD"},
        "input_schema": {"type": "object", "properties": {
            "audio_ref": {"type": "string"},
            "audio_base64": {"type": "string"},
            "provider": {"type": "string"},
            "model": {"type": "string"},
            "language": {"type": "string"},
            "transport": {"type": "string"},
            "fallback_policy": {"type": "string"},
        }},
        "output_schema": {"type": "object", "properties": {
            "transcript": {"type": "string"},
            "text_events": {"type": "array"},
            "provider": {"type": "string"},
            "fallback": {"type": "boolean"},
        }},
    },
    {
        "slug": "voice_realtime_speak_v1",
        "version": "1",
        "name": "Voice Realtime Speak",
        "description": "Produces audio.out events from a realtime, local or cascade speech provider.",
        "type": "voice",
        "provider": "internal",
        "certification_level": "beta",
        "execution": {"mode": "stream", "timeout_ms": 30_000, "retryable": True, "idempotent": True},
        "pricing": {"unit": "per_char", "unit_price": 0.00002, "currency": "USD"},
        "input_schema": {"type": "object", "required": ["text"], "properties": {
            "text": {"type": "string"},
            "provider": {"type": "string"},
            "model": {"type": "string"},
            "transport": {"type": "string"},
            "language": {"type": "string"},
            "voice": {"type": "string"},
            "fallback_policy": {"type": "string"},
        }},
        "output_schema": {"type": "object", "properties": {
            "audio_base64": {"type": "string"},
            "content_type": {"type": "string"},
            "provider": {"type": "string"},
            "events": {"type": "array"},
        }},
    },
    {
        "slug": "voice_realtime_translate_v1",
        "version": "1",
        "name": "Voice Realtime Translate",
        "description": "Routes live translation events through an OpenAI Realtime or local translation-capable provider.",
        "type": "voice",
        "provider": "internal",
        "certification_level": "beta",
        "execution": {"mode": "stream", "timeout_ms": 60_000, "retryable": True, "idempotent": False},
        "pricing": {"unit": "per_minute", "unit_price": 0.02, "currency": "USD"},
        "input_schema": {"type": "object", "properties": {
            "text": {"type": "string"},
            "provider": {"type": "string"},
            "source_language": {"type": "string"},
            "target_language": {"type": "string"},
            "transport": {"type": "string"},
            "fallback_policy": {"type": "string"},
        }},
        "output_schema": {"type": "object", "properties": {
            "events": {"type": "array"},
            "translated_text": {"type": "string"},
            "provider": {"type": "string"},
        }},
    },
    {
        "slug": "voice_oracle_turn_v1",
        "version": "1",
        "name": "Voice Oracle Turn",
        "description": "Binds transcript, Knowledge context and evaluator output into the next voice action for a system.",
        "type": "voice",
        "provider": "internal",
        "certification_level": "production",
        "execution": {"mode": "sync", "timeout_ms": 15_000, "retryable": True, "idempotent": False},
        "pricing": {"unit": "per_turn", "unit_price": 0.01, "currency": "USD"},
        "input_schema": {"type": "object", "properties": {
            "answer": {"type": "string"},
            "question": {"type": "object"},
            "gap": {"type": "object"},
            "context": {"type": "object"},
        }},
        "output_schema": {"type": "object", "properties": {
            "action": {"type": "string"},
            "evaluation": {"type": "object"},
            "events": {"type": "array"},
        }},
    },
    {
        "slug": "voice_tandem_oracle_v1",
        "version": "1",
        "name": "Voice Tandem Oracle",
        "description": "Coordinates realtime voice micro-turns with a background Knowledge oracle using provider-neutral latest-wins events.",
        "type": "voice",
        "provider": "internal",
        "certification_level": "beta",
        "execution": {"mode": "stream", "timeout_ms": 15_000, "retryable": True, "idempotent": False},
        "pricing": {"unit": "per_turn", "unit_price": 0.012, "currency": "USD"},
        "input_schema": {"type": "object", "properties": {
            "partial_text": {"type": "string"},
            "final_text": {"type": "string"},
            "turn_id": {"type": "string"},
            "duration_ms": {"type": "integer"},
            "evaluation": {"type": "object"},
            "next_prompt": {"type": "string"},
            "sources": {"type": "array"},
            "provider": {"type": "string"},
            "transport": {"type": "string"},
            "fallback_policy": {"type": "string"},
        }},
        "output_schema": {"type": "object", "properties": {
            "events": {"type": "array"},
            "mode": {"type": "string"},
            "committed": {"type": "boolean"},
        }},
    },
    {
        "slug": "knowledge_gap_analysis_v1",
        "version": "1",
        "name": "Knowledge Gap Analysis",
        "description": "Identifies missing, weakly sourced or tacit knowledge to resolve with an expert.",
        "type": "analysis",
        "provider": "internal",
        "certification_level": "production",
        "execution": {"mode": "sync", "timeout_ms": 15_000, "retryable": True, "idempotent": True},
        "pricing": {"unit": "per_call", "unit_price": 0.015, "currency": "USD"},
        "input_schema": {"type": "object", "required": ["objective"], "properties": {
            "objective": {"type": "string"},
            "expert_profile": {"type": "string"},
            "context": {"type": "object"},
            "knowledge_refs": {"type": "array"},
        }},
        "output_schema": {"type": "object", "properties": {
            "gaps": {"type": "array"},
        }},
    },
    {
        "slug": "expert_interview_plan_v1",
        "version": "1",
        "name": "Expert Interview Plan",
        "description": "Builds a duration-bounded expert interview agenda from prioritized knowledge gaps.",
        "type": "planning",
        "provider": "internal",
        "certification_level": "production",
        "execution": {"mode": "sync", "timeout_ms": 15_000, "retryable": True, "idempotent": True},
        "pricing": {"unit": "per_plan", "unit_price": 0.03, "currency": "USD"},
        "input_schema": {"type": "object", "required": ["objective", "duration_minutes", "gaps"], "properties": {
            "objective": {"type": "string"},
            "expert_profile": {"type": "string"},
            "duration_minutes": {"type": "integer"},
            "gaps": {"type": "array"},
            "context": {"type": "object"},
        }},
        "output_schema": {"type": "object", "properties": {
            "plan": {"type": "object"},
        }},
    },
    {
        "slug": "expert_answer_evaluator_v1",
        "version": "1",
        "name": "Expert Answer Evaluator",
        "description": "Evaluates whether an expert answer is sufficient, partial, contradictory or needs a follow-up.",
        "type": "analysis",
        "provider": "internal",
        "certification_level": "production",
        "execution": {"mode": "sync", "timeout_ms": 8_000, "retryable": False, "idempotent": True},
        "pricing": {"unit": "per_answer", "unit_price": 0.01, "currency": "USD"},
        "input_schema": {"type": "object", "required": ["answer"], "properties": {
            "answer": {"type": "string"},
            "question": {"type": "object"},
            "gap": {"type": "object"},
        }},
        "output_schema": {"type": "object", "properties": {
            "verdict": {"type": "string"},
            "score": {"type": "number"},
            "follow_up": {"type": "string"},
            "signals": {"type": "object"},
        }},
    },
    {
        "slug": "capture_structuring_v1",
        "version": "1",
        "name": "Capture Structuring",
        "description": "Turns transcript and evaluated expert answers into a reviewable knowledge update proposal.",
        "type": "generation",
        "provider": "internal",
        "certification_level": "production",
        "execution": {"mode": "sync", "timeout_ms": 20_000, "retryable": True, "idempotent": True},
        "pricing": {"unit": "per_session", "unit_price": 0.04, "currency": "USD"},
        "input_schema": {"type": "object", "required": ["session"], "properties": {
            "session": {"type": "object"},
        }},
        "output_schema": {"type": "object", "properties": {
            "proposal": {"type": "object"},
        }},
    },
    {
        "slug": "audit_log_v1",
        "version": "1",
        "name": "Audit Log",
        "description": "Persists a typed audit event for compliance and replay.",
        "type": "compliance",
        "provider": "internal",
        "certification_level": "enterprise",
        "execution": {"mode": "sync", "timeout_ms": 5_000, "retryable": True, "idempotent": True},
        "pricing": {"unit": "per_call", "unit_price": 0.0001, "currency": "USD"},
        "input_schema": {"type": "object", "required": ["event_type"], "properties": {
            "event_type": {"type": "string"},
            "details": {"type": "object"},
        }},
        "output_schema": {"type": "object", "properties": {
            "id": {"type": "string"},
        }},
    },
    {
        "slug": "ollama_llm_v1",
        "version": "1",
        "name": "Ollama LLM",
        "description": "Generic LLM call routed through the Ollama provider.",
        "type": "llm",
        "provider": "ollama",
        "certification_level": "basic",
        "execution": {"mode": "stream", "timeout_ms": 120_000, "retryable": True, "idempotent": False},
        "pricing": {"unit": "per_1k_tokens", "unit_price": 0.0, "currency": "USD"},
        "input_schema": {"type": "object", "required": ["prompt"], "properties": {
            "prompt": {"type": "string"},
            "model": {"type": "string"},
        }},
        "output_schema": {"type": "object", "properties": {
            "completion": {"type": "string"},
        }},
    },
    {
        "slug": "chain_naive_v1",
        "version": "1",
        "name": "RAG Chain · Naive",
        "description": "Single-pass vector retrieval + LLM answer. Cheapest, fastest, lowest recall.",
        "type": "rag",
        "provider": "internal",
        "certification_level": "production",
        "execution": {"mode": "stream", "timeout_ms": 45_000, "retryable": True, "idempotent": False},
        "pricing": {"unit": "per_call", "unit_price": 0.006, "currency": "USD"},
        "input_schema": {"type": "object", "required": ["query"], "properties": {
            "query": {"type": "string"},
            "context_id": {"type": "string"},
            "top_k": {"type": "integer", "default": 5},
        }},
        "output_schema": {"type": "object", "properties": {
            "answer": {"type": "string"},
            "citations": {"type": "array"},
            "decision_steps": {"type": "array"},
        }},
    },
    {
        "slug": "chain_hybrid_v1",
        "version": "1",
        "name": "RAG Chain · Hybrid (HAH)",
        "description": "Two-pass hybrid retrieval (BM25 + dense) with RRF fusion before the LLM answer.",
        "type": "rag",
        "provider": "internal",
        "certification_level": "production",
        "execution": {"mode": "stream", "timeout_ms": 60_000, "retryable": True, "idempotent": False},
        "pricing": {"unit": "per_call", "unit_price": 0.014, "currency": "USD"},
        "input_schema": {"type": "object", "required": ["query"], "properties": {
            "query": {"type": "string"},
            "context_id": {"type": "string"},
            "top_k": {"type": "integer", "default": 5},
        }},
        "output_schema": {"type": "object", "properties": {
            "answer": {"type": "string"},
            "citations": {"type": "array"},
            "decision_steps": {"type": "array"},
        }},
    },
    {
        "slug": "chain_mixed_hah_v1",
        "version": "1",
        "name": "RAG Chain · Composite HAH (C-HAH)",
        "description": "Parallel multi-strategy retrieval: runs several query rephrasings concurrently and fuses via RRF before the LLM answer.",
        "type": "rag",
        "provider": "internal",
        "certification_level": "production",
        "execution": {"mode": "stream", "timeout_ms": 75_000, "retryable": True, "idempotent": False},
        "pricing": {"unit": "per_call", "unit_price": 0.022, "currency": "USD"},
        "input_schema": {"type": "object", "required": ["query"], "properties": {
            "query": {"type": "string"},
            "context_id": {"type": "string"},
            "top_k": {"type": "integer", "default": 5},
        }},
        "output_schema": {"type": "object", "properties": {
            "answer": {"type": "string"},
            "citations": {"type": "array"},
            "decision_steps": {"type": "array"},
        }},
    },
    {
        "slug": "azure_llm_v1",
        "version": "1",
        "name": "Azure OpenAI LLM",
        "description": "LLM call routed through Azure OpenAI.",
        "type": "llm",
        "provider": "azure",
        "certification_level": "production",
        "execution": {"mode": "stream", "timeout_ms": 60_000, "retryable": True, "idempotent": False},
        "pricing": {"unit": "per_1k_tokens", "unit_price": 0.01, "currency": "USD"},
        "input_schema": {"type": "object", "required": ["prompt"], "properties": {
            "prompt": {"type": "string"},
            "model": {"type": "string"},
        }},
        "output_schema": {"type": "object", "properties": {
            "completion": {"type": "string"},
        }},
    },
]


# ---- Universal Capabilities -------------------------------------------------
SEED_CAPABILITIES: List[Dict[str, Any]] = [
    {
        "slug": "intelligent_qa",
        "name": "Intelligent Q&A",
        "tier": "universal",
        "description": "Answers questions over your knowledge base with citations and a verifiable reasoning trail.",
        "input_unit": "question",
        "output_unit": "answer",
        "skill_slugs": ["llm_rag_answer_v1", "semantic_search_v1", "claim_audit_v1", "audit_log_v1"],
        "pricing": {"unit": "per_outcome", "unit_price": 0.05, "currency": "USD"},
        "value_per_outcome": 1.20,
        "confidence_threshold": 0.65,
        "sla": {"max_latency_ms": 8000, "uptime": 0.995},
        "roi_model": {"type": "value_minus_cost"},
    },
    {
        "slug": "knowledge_curation",
        "name": "Knowledge Curation",
        "tier": "universal",
        "description": "Continuously ingests, deduplicates and indexes documents from any source (uploads, SharePoint, web feeds).",
        "input_unit": "document",
        "output_unit": "indexed_chunk",
        "skill_slugs": ["document_ingestion_v1", "sharepoint_ingestion_v1", "intelligence_batch_v1"],
        "pricing": {"unit": "per_doc", "unit_price": 0.05, "currency": "USD"},
        "value_per_outcome": 0.40,
        "confidence_threshold": None,
        "sla": {"freshness_minutes": 60},
        "roi_model": {"type": "time_saved"},
    },
    {
        "slug": "voice2voice_interaction",
        "name": "Voice2Voice Interaction",
        "tier": "universal",
        "description": "Provider-neutral realtime voice loop for chat, capture and custom systems, with cascade fallback and auditable events.",
        "input_unit": "voice_session",
        "output_unit": "conversation_turn",
        "skill_slugs": [
            "voice_realtime_session_v1",
            "voice_realtime_transcribe_v1",
            "voice_oracle_turn_v1",
            "voice_tandem_oracle_v1",
            "voice_realtime_speak_v1",
            "voice_realtime_translate_v1",
            "voice_transcribe_v1",
            "voice_tts_v1",
            "audit_log_v1",
        ],
        "pricing": {"unit": "per_session", "unit_price": 0.12, "currency": "USD"},
        "value_per_outcome": 0.90,
        "confidence_threshold": 0.70,
        "sla": {"max_latency_ms": 4000},
        "roi_model": {"type": "value_minus_cost"},
    },
    {
        "slug": "voice_assistant",
        "name": "Voice Assistant",
        "tier": "universal",
        "description": "Transcribe a question, retrieve an answer, speak it back. End-to-end voice loop.",
        "input_unit": "audio_minute",
        "output_unit": "answer",
        "skill_slugs": [
            "voice_realtime_session_v1",
            "voice_realtime_transcribe_v1",
            "voice_tandem_oracle_v1",
            "llm_rag_answer_v1",
            "voice_realtime_speak_v1",
            "voice_transcribe_v1",
            "voice_tts_v1",
        ],
        "pricing": {"unit": "per_outcome", "unit_price": 0.10, "currency": "USD"},
        "value_per_outcome": 0.60,
        "confidence_threshold": 0.70,
        "sla": {"max_latency_ms": 4000},
        "roi_model": {"type": "value_minus_cost"},
    },
    {
        "slug": "expert_knowledge_capture",
        "name": "Expert Knowledge Capture",
        "tier": "universal",
        "description": "Prepares and runs guided expert interviews that resolve knowledge gaps and produce reviewable knowledge-base updates.",
        "input_unit": "capture_session",
        "output_unit": "knowledge_update_proposal",
        "skill_slugs": [
            "knowledge_gap_analysis_v1",
            "expert_interview_plan_v1",
            "voice_realtime_session_v1",
            "voice_realtime_transcribe_v1",
            "semantic_search_v1",
            "expert_answer_evaluator_v1",
            "voice_oracle_turn_v1",
            "voice_tandem_oracle_v1",
            "capture_structuring_v1",
            "voice_realtime_speak_v1",
            "voice_transcribe_v1",
            "voice_tts_v1",
            "audit_log_v1",
        ],
        "pricing": {"unit": "per_session", "unit_price": 0.35, "currency": "USD"},
        "value_per_outcome": 8.00,
        "confidence_threshold": 0.70,
        "sla": {"target_duration_minutes": 20, "max_plan_latency_ms": 15000},
        "roi_model": {"type": "time_saved_plus_knowledge_retention"},
    },
    {
        "slug": "answer_quality_audit",
        "name": "Answer Quality Audit",
        "tier": "universal",
        "description": "Continuously evaluates answer quality (groundedness, relevance, safety) and alerts on regressions.",
        "input_unit": "answer",
        "output_unit": "evaluation",
        "skill_slugs": ["eval_radar_v1", "claim_audit_v1"],
        "pricing": {"unit": "per_outcome", "unit_price": 0.04, "currency": "USD"},
        "value_per_outcome": 0.20,
        "confidence_threshold": None,
        "sla": {},
        "roi_model": {"type": "risk_avoided"},
    },
    {
        "slug": "market_signal_brief",
        "name": "Market Signal Brief",
        "tier": "industry",
        "industry": "finance",
        "description": "Aggregates intelligence feeds into a periodic decision-grade brief with semantic targets.",
        "input_unit": "feed_batch",
        "output_unit": "brief",
        "skill_slugs": ["intelligence_batch_v1", "llm_rag_answer_v1", "audit_log_v1"],
        "pricing": {"unit": "per_brief", "unit_price": 1.20, "currency": "USD"},
        "value_per_outcome": 8.00,
        "confidence_threshold": 0.65,
        "sla": {"freshness_minutes": 240},
        "roi_model": {"type": "value_minus_cost"},
    },
    {
        "slug": "compliance_assistant",
        "name": "Compliance Assistant",
        "tier": "industry",
        "industry": "legal",
        "description": "Answers compliance questions with full citation, audit log and HITL escalation when confidence is low.",
        "input_unit": "question",
        "output_unit": "answer",
        "skill_slugs": ["llm_rag_answer_v1", "claim_audit_v1", "audit_log_v1"],
        "pricing": {"unit": "per_outcome", "unit_price": 0.20, "currency": "USD"},
        "value_per_outcome": 4.00,
        "confidence_threshold": 0.80,
        "sla": {"max_latency_ms": 10_000, "uptime": 0.999},
        "roi_model": {"type": "value_minus_cost"},
    },
]


def seed_skills_and_capabilities(db: DBSession) -> Dict[str, int]:
    """Idempotent upsert of the seed registry. Safe to call on every boot.

    Returns a small report so the startup log can show what changed.
    """
    now = datetime.utcnow()
    skills_added = 0
    skills_updated = 0
    skill_id_by_slug: Dict[str, str] = {}

    # Skills first.
    for entry in SEED_SKILLS:
        existing = db.query(Skill).filter(Skill.slug == entry["slug"]).first()
        if existing:
            for key in ("name", "description", "type", "provider", "certification_level",
                        "execution", "pricing", "input_schema", "output_schema", "version"):
                if entry.get(key) is not None:
                    setattr(existing, key, entry[key])
            existing.is_seeded = "Y"
            existing.updated_at = now
            skill_id_by_slug[existing.slug] = existing.id
            skills_updated += 1
        else:
            sk = Skill(
                slug=entry["slug"],
                version=entry["version"],
                name=entry["name"],
                description=entry["description"],
                type=entry["type"],
                provider=entry["provider"],
                certification_level=entry["certification_level"],
                execution=entry["execution"],
                pricing=entry["pricing"],
                input_schema=entry["input_schema"],
                output_schema=entry["output_schema"],
                is_seeded="Y",
                workspace_id=None,
            )
            db.add(sk)
            db.flush()
            skill_id_by_slug[sk.slug] = sk.id
            skills_added += 1

    # Capabilities reference skill ids.
    caps_added = 0
    caps_updated = 0
    for entry in SEED_CAPABILITIES:
        skill_ids = [skill_id_by_slug[s] for s in entry["skill_slugs"] if s in skill_id_by_slug]
        existing = db.query(Capability).filter(Capability.slug == entry["slug"]).first()
        if existing:
            for key in ("name", "description", "tier", "industry", "input_unit", "output_unit",
                        "pricing", "value_per_outcome", "confidence_threshold", "sla", "roi_model"):
                if entry.get(key) is not None:
                    setattr(existing, key, entry[key])
            existing.skill_ids = skill_ids
            existing.is_seeded = "Y"
            existing.updated_at = now
            caps_updated += 1
        else:
            cap = Capability(
                slug=entry["slug"],
                name=entry["name"],
                description=entry["description"],
                tier=entry["tier"],
                industry=entry.get("industry"),
                input_unit=entry["input_unit"],
                output_unit=entry["output_unit"],
                skill_ids=skill_ids,
                pricing=entry["pricing"],
                value_per_outcome=entry["value_per_outcome"],
                confidence_threshold=entry["confidence_threshold"],
                sla=entry["sla"],
                roi_model=entry["roi_model"],
                is_seeded="Y",
                workspace_id=None,
            )
            db.add(cap)
            caps_added += 1

    db.commit()
    return {
        "skills_added": skills_added,
        "skills_updated": skills_updated,
        "capabilities_added": caps_added,
        "capabilities_updated": caps_updated,
    }
