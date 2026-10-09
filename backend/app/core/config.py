"""Application configuration"""

import os
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI Orchestration Platform"
    app_version: str = "1.0.0-demo"
    # Exact source revision baked into every deployable image. The protected
    # deployment job rejects non-SHA values outside local development.
    agentium_image_revision: str = "development"
    # Trust anchor for authorization-v2 promotion attestations.  A workspace
    # document cannot nominate its own issuer.
    authorization_v2_trusted_oidc_issuer: str = "https://gitlab.com"
    # Empty is intentionally fail-closed: enforcement cannot become effective
    # until deployment names the one protected GitLab project allowed to
    # attest promotions.  The ref is separately pinned as defence in depth.
    authorization_v2_trusted_project_id: str = ""
    authorization_v2_trusted_ref: str = "demo/agentic"
    debug: bool = False

    # Production startup normally reconciles idempotent demo/catalogue state.
    # Transactional VM deployments override this to ``disabled`` so merely
    # starting a candidate cannot mutate PostgreSQL, Qdrant or tenant Systems
    # before semantic before/after proofs have passed.
    startup_reconciliation: Literal["enabled", "disabled"] = "enabled"

    api_v1_prefix: str = "/api/v1"

    # LLM -- OpenAI-first for demo, LLM SDK supports 20+ providers
    openai_api_key: str = ""
    default_provider: str = "openai"
    default_model: str = "gpt-5"
    # Judge model override. Empty falls back to default_model (gpt-5) and is
    # routed provider-neutrally via ModelRouter (Ollama fallback on-prem).
    judge_model: str = ""

    # Route select niche intents (inventory/comparison/equipment/table/multi-hop)
    # through the agentic chat DAG instead of the classic orchestrator. Off by
    # default: no behavior change until explicitly enabled per deployment.
    enable_agentic_chat: bool = False

    # Flow Builder sources DAG, Phase 2. When ON, an ``asset`` node's collection
    # becomes the AUTHORITATIVE retrieval scope: retrieve nodes read it via an
    # ``inputs_map`` VariableRef and the membrane inbound allowlist is synced from
    # the graph on flow save. When OFF (default) asset-sourced VariableRefs are
    # skipped and asset data edges contribute nothing to the merge, so retrieval
    # keeps its implicit workspace resolution — byte-identical to Phase 1. Off by
    # default: no behavior change until explicitly enabled per deployment.
    flow_asset_binding_authoritative: bool = False

    # Flow Builder sources DAG, Phase 3. Global master switch for EXECUTABLE
    # event triggers (``source.sftp_arrival`` / ``deposit.promoted`` /
    # ``source.webhook``). When OFF (default) triggers stay inert UNLESS a
    # workspace opts in via ``settings.features.enable_event_triggers`` (or
    # ``settings.event_triggers.enabled``) — showcase seed does this without
    # flipping the deployment-wide switch. When enabled (global or workspace),
    # each System is still governed by ``settings.event_trigger.mode`` which
    # defaults to ``dry_run``; ``live`` is opt-in per System. The governance
    # invariant (docs/adr-flow-source-nodes.md §6) is enforced in code
    # regardless of this flag. Off by default: no behavior change on deploy.
    enable_event_triggers: bool = False

    # HITL / membrane HOLD gate TTL. Used when a hitl node (or membrane egress
    # HOLD) does not set ``config.expires_in_days`` / ``config.expiry_action``.
    # scheduler_tick sweeps expired ``proposed`` decisions and applies the action.
    hitl_gate_ttl_days: int = 3
    hitl_gate_default_expiry_action: str = "reject"  # reject | approve | escalate

    # Ollama fallback
    ollama_base_url: str = "http://localhost:11434"
    ollama_default_model: str = "qwen3:8b"
    ollama_default_num_ctx: int = 32768
    ollama_rope_scale: Optional[float] = None
    ollama_rope_alpha: Optional[float] = None

    # LLM serving nodes (omnirag-llm-portal). JSON list of
    # {"name","base_url","token"} objects. Empty = first-class zero-node
    # state (demo VM default). Never expose portal URLs to the browser —
    # the backend proxies lifecycle calls with the node token.
    llm_serving_nodes_json: str = ""

    # Database (PostgreSQL recommended; SQLite fallback for dev-only)
    database_url: str = "postgresql://agentium:agentium@localhost:5432/agentium"

    # Vector Store
    faiss_persist_directory: str = "./faiss_db"
    chroma_persist_directory: str = "./chroma_db"
    default_vector_db_type: str = "qdrant"

    # Qdrant (optional; used when rag_vector_db_type / default_vector_db_type is "qdrant")
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_api_key: Optional[str] = None
    qdrant_https: bool = False
    qdrant_timeout_seconds: float = 60.0
    qdrant_upsert_batch_size: int = 128

    # Async execution plane. Existing endpoints stay synchronous unless this
    # is explicitly enabled; the canonical collection upload endpoint always
    # creates a WorkerJob and dispatches through this plane.
    document_ingest_async_enabled: bool = False
    document_ingest_max_concurrency: int = 8
    worker_eager_mode: bool = False
    celery_broker_url: str = "amqp://guest:guest@localhost:5672//"
    celery_result_backend: Optional[str] = None
    celery_task_default_queue: str = "cpu"
    # Recipes are awaited by Flow workers: they must have an independent consumer.
    celery_recipe_queue: str = "recipes"
    # Training queue of the tabular model family. Empty => the default queue,
    # where the general worker already trains it. Other families name their own
    # queue setting (app.services.ml.families), consumed by their own image.
    celery_ml_tabular_queue: str = ""
    # Training queue of the forecasting family, consumed by the ml-ts image.
    celery_ml_ts_queue: str = "ml_ts"
    # Forecasts on demand: the API sends one task and waits for its answer, so
    # this queue is consumed by a threads-pool worker that keeps models loaded.
    celery_ml_ts_serve_queue: str = "ml_ts_rpc"
    # Optional torch runtime; neither queue is consumed by the CPU worker.
    celery_ml_deep_queue: str = "ml_deep"
    celery_ml_deep_serve_queue: str = "ml_deep_rpc"
    # Operator-provisioned, checksummed weights. Never a user-provided path.
    ml_deep_models_dir: str = "/data/models"

    # Object storage for original / ingested / derived RAG artifacts.
    # "local" is dependency-free for dev/tests; "s3" uses fsspec/s3fs when
    # configured for MinIO or compatible object stores.
    object_store_backend: str = "local"
    object_store_base_path: str = "./data/object_store"
    object_store_s3_bucket: Optional[str] = None
    object_store_s3_endpoint_url: Optional[str] = None
    object_store_s3_access_key: Optional[str] = None
    object_store_s3_secret_key: Optional[str] = None
    visual_capture_http_timeout_seconds: float = 15.0
    visual_capture_browser_enabled: bool = False
    visual_capture_windy_api_key: Optional[str] = None

    # ─── Maritime / AIS provider (advisory-only, demo-safe) ───
    # ``baseline`` reads ``backend/app/resources/maritime/abidjan-vessels-baseline.json``
    # (always works, ~15 vessels around Abidjan/Vridi).  ``aisstream`` and
    # ``aishub`` are optional live providers that require an API key/username
    # and degrade gracefully back to the baseline if the credential is missing
    # or the upstream call fails.  ``marinetraffic_embed`` keeps the baseline
    # JSON and exposes the public MarineTraffic iframe URL for the UI overlay.
    sentinel_ais_provider: str = "baseline"
    sentinel_aisstream_api_key: Optional[str] = None
    sentinel_aishub_username: Optional[str] = None
    sentinel_marinetraffic_embed_default_zoom: int = 11
    visual_analysis_enabled: bool = False
    visual_analysis_provider: str = "openai"
    visual_analysis_model: str = "gpt-4o-mini"
    visual_analysis_timeout_seconds: float = 20.0
    visual_analysis_endpoint_url: Optional[str] = None

    # OCR / Visual Document Intelligence. OCR providers are optional and
    # service-first: PP-OCR-compatible HTTP service in production, local
    # Tesseract only when available or explicitly installed.
    document_ocr_enabled: bool = True
    document_ocr_provider_priority: str = "ppocr_service,tesseract_local"
    document_ocr_ppocr_endpoint_url: Optional[str] = None
    document_ocr_languages: str = "eng,fra"
    document_ocr_scan_detection: bool = True
    document_ocr_force_ocr: bool = False
    document_ocr_min_text_chars_for_native_pdf: int = 80
    document_ocr_min_confidence: float = 0.0
    document_ocr_timeout_seconds: float = 30.0
    document_ocr_retries: int = 2
    document_ocr_retry_backoff_ms: int = 250
    document_ocr_required: bool = False
    document_ocr_openai_vision_enabled: bool = False
    document_ocr_openai_model: str = "gpt-4o-mini"
    document_ocr_openai_detail: str = "low"
    document_ocr_openai_max_image_bytes: int = 5_000_000
    document_ocr_openai_enrich_min_chars: int = 24
    document_ocr_openai_enrich_min_confidence: float = 0.45

    # Embeddings
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"

    # RAG: HAH/C-HAH backend pipelines (multi-pass on DocumentService; see pipeline_retrieval.py)
    rag_hah_chah_enabled: bool = True
    rag_retrieval_worker_enabled: bool = False
    rag_retrieval_worker_timeout_seconds: float = 120.0
    rag_fast_retrieval_deadline_seconds: float = 8.0
    rag_deep_retrieval_deadline_seconds: float = 120.0
    rag_auto_deep_retrieval_enabled: bool = True
    rag_auto_deep_retrieval_dense_unscoped: bool = True
    rag_auto_deep_retrieval_min_confidence: float = 0.45
    rag_context_cache_enabled: bool = True
    rag_context_cache_ttl_seconds: int = 90
    rag_context_cache_max_entries: int = 256
    rag_similarity_threshold: float = 0.2
    rag_dense_chunk_threshold: int = 100000
    rag_dense_source_threshold: int = 5000
    rag_sparse_backend: str = "auto"
    rag_opensearch_url: Optional[str] = None
    rag_opensearch_index_prefix: str = "agentium-rag"
    rag_qdrant_sparse_enabled: bool = False
    rag_qdrant_oracle_hnsw_ef: int = 32
    rag_qdrant_chat_hnsw_ef: int = 64
    rag_qdrant_deep_hnsw_ef: int = 128
    rag_qdrant_quantized_search_enabled: bool = True
    rag_qdrant_hybrid_fusion: str = "rrf"
    rag_allow_runtime_bm25: bool = False
    # Budgeted cross-encoder rerank applied after RRF/policy fusion. Off on
    # the fast profile; bounded by a hard time budget on balanced so the first
    # answer latency is protected; unbounded on the deep (async) path.
    rag_cross_encoder_enabled: bool = True
    rag_cross_encoder_model_balanced: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    rag_cross_encoder_model_deep: str = "cross-encoder/ms-marco-MiniLM-L-12-v2"
    rag_cross_encoder_budget_seconds: float = 0.5
    rag_cross_encoder_threshold: float = 0.2
    rag_cross_encoder_max_candidates: int = 24
    rag_cross_encoder_max_length_balanced: int = 256
    # Deep profile was previously unbounded (budget_seconds=None, pool=len(chunks),
    # max_length=512), so a large fused pool could blow the deep deadline. These
    # bound it: budget is a fraction of rag_deep_retrieval_deadline_seconds (120s),
    # the pool is capped, and on timeout the stage degrades to the policy order.
    rag_cross_encoder_budget_seconds_deep: float = 25.0
    rag_cross_encoder_max_candidates_deep: int = 64
    rag_cross_encoder_max_length_deep: int = 512
    rag_cross_encoder_max_concurrency: int = 2
    rag_cross_encoder_preload: bool = False
    # Which engine scores: "auto" runs ONNX Runtime on the model files baked
    # into rag_models_dir (backend/rag_models.lock.json) and falls back to torch
    # only where ONNX cannot run; "onnx" or "torch" forces one. The API image no
    # longer installs torch; the worker keeps it as the fallback engine.
    rag_reranker_backend: str = "auto"
    rag_models_dir: str = "/opt/agentium-models"
    # RAGGER/HAH-RAG paper refinements. Fusion/compression/generation are
    # near-zero-cost and ship enabled; MMR and the prompt classifier stay off
    # until the golden A/B comparison clears them (see offline_eval harness).
    rag_adaptive_fusion_enabled: bool = True
    rag_compression_enabled: bool = True
    rag_compression_ratio: float = 0.7
    rag_compression_score_floor: float = 0.35
    rag_generation_adaptive_enabled: bool = True
    rag_generation_frequency_penalty_enabled: bool = False
    rag_generation_max_output_cap_fast: int = 2048
    rag_generation_max_output_cap_balanced: int = 4096
    rag_generation_max_output_cap_deep: int = 8192
    rag_mmr_enabled: bool = False
    rag_mmr_lambda: float = 0.7
    rag_mmr_budget_seconds: float = 0.5
    rag_mmr_max_candidates: int = 24
    rag_prompt_classifier_enabled: bool = False
    rag_prompt_classifier_min_confidence: float = 0.15
    rag_prompt_classifier_budget_seconds: float = 0.15
    # Comparative query decomposition: an "A vs B" query is dominated by the
    # corpus-frequent entity, so the second entity under-recalls. When enabled
    # and two entities parse out, two entity-focused sub-queries run in parallel
    # and merge with the original, guaranteeing ≥1 chunk per entity in the
    # top-k. Master flag (deep): ON. Balanced is gated separately because the
    # extra sub-queries add latency — measured before flipping ON.
    rag_comparative_decompose_enabled: bool = True
    rag_comparative_decompose_balanced: bool = False
    rag_comparative_decompose_max_subqueries: int = 2
    # Workspace source_policy.reject_cross_project_sources rollout: log-only by
    # default (counts what would be dropped); flip to True once collections are
    # backfilled with project_code payloads, otherwise untagged corpora would
    # lose evidence.
    rag_reject_cross_project_enforce: bool = False
    # Expert fiche correction (chat -> pending_review -> validated fiche). Global
    # kill-switch defaults OFF; per-workspace activation rides on the chat
    # source_policy (expert_fiche_correction_enabled). The boost weight is the
    # strong-but-not-override ranking bump applied to source_type=expert_fiche
    # results, wired in Volet 3 (rerank/provenance), not here.
    rag_expert_fiche_boost_enabled: bool = False
    rag_expert_fiche_boost: int = 18
    # Hard pin (kill-switch) for validated expert fiches. When enabled, any
    # expert fiche present among the already-retrieved candidates is ordered
    # ahead of regular documents regardless of score (the additive
    # rag_expert_fiche_boost above stays a ranking signal; this is a sort key).
    # Default OFF keeps the retrieval path byte-for-byte identical.
    rag_expert_fiche_pin_enabled: bool = False
    # Global default for the per-workspace expert-review gate. When a workspace
    # chat/source policy does not override expert_review_required, this decides
    # whether expert corrections/captures stay pending_review (True) or are
    # auto-validated and published immediately (False). Per-workspace override
    # rides on source_policy.expert_review_required.
    kc_expert_review_required: bool = True
    # Conversation history sent to the LLM is token-budgeted (not a fixed
    # message count); older turns beyond the budget are condensed into a
    # one-line summary prefix.
    chat_history_token_budget: int = 3500
    chat_stream_timeout_seconds: float = 180.0
    bm25_rebuild_inline_max_chunks: int = 50000
    bm25_rebuild_max_chunks: int = 600000

    # OpenAI Responses API rollout. The chat-completions path remains the
    # default until explicitly enabled per environment.
    openai_responses_api_enabled: bool = False
    openai_responses_include_reasoning_encrypted_content: bool = True

    # Reasoning effort pinned for OpenAI "thinking" models (o-series, gpt-5
    # family). gpt-5 reasons by default, which adds thinking latency before the
    # first output token; pinning a low effort keeps the live chat + voice
    # cascade latency on par with the non-reasoning gpt-4o it replaces. Only
    # forwarded for thinking models (gpt-4o / gpt-4.1 never see it). Set empty
    # to let the model use its own default. Valid: minimal|low|medium|high.
    openai_reasoning_effort: str = "minimal"

    # Model used for the plan co-construction oracle (Knowledge Capture "Modifier
    # le plan" / Appliquer flow). Structuring the expert's own words into a JSON
    # outline is a low-difficulty task where a small model matches the default
    # gpt-5 quality at a fraction of the latency. Set empty to fall back to the
    # workspace default model.
    capture_plan_oracle_model: str = "gpt-4o-mini"

    # Model used for the FINAL end-of-capture pass (per-section exhaustive
    # reformulation, grounded open questions, thematic structuring). Faithful
    # restructuring of the expert's own statements is well within a small
    # model's reach, and the default workspace model may be a thinking model
    # (gpt-5: ~70s per section) — the dedicated model cuts the finalize wall
    # time dramatically. Set empty to fall back to the workspace default model.
    capture_finalize_model: str = "gpt-4o-mini"

    # Client360 PDR mail drafts. Enabled by default for the business surface:
    # the LLM writes the contextual draft, while deterministic templates remain
    # the safe fallback whenever the provider is unavailable.
    client360_mail_ai_enabled: bool = True
    client360_mail_model: str = "gpt-4o-mini"
    client360_mail_timeout_seconds: float = 20.0

    # Voice2Voice runtime provider plane. OpenAI Realtime is an optional lane;
    # cascade_openai remains the production-safe default and local providers are
    # integrated through HTTP/WebSocket contracts rather than heavy in-process
    # model dependencies.
    voice_runtime_default_provider: str = "cascade_openai"
    voice_runtime_allowed_providers: str = (
        "cascade_openai,openai_realtime,local_stt,local_tts,local_realtime,realtime_gpu"
    )
    voice_runtime_fallback_providers: str = "cascade_openai"
    voice_realtime_default_transport: str = "backend_ws"
    voice_realtime_webrtc_enabled: bool = False
    # Deployment switch. Which workspace may use it is the workspace's own
    # ``features.openai_realtime`` flag.
    openai_realtime_enabled: bool = False
    openai_realtime_model: str = "gpt-realtime-2"
    openai_realtime_transcribe_model: str = "gpt-realtime-whisper"
    openai_realtime_translate_model: str = "gpt-realtime-translate"
    openai_realtime_api_base: str = "https://api.openai.com/v1"
    openai_realtime_ephemeral_ttl_seconds: int = 600
    # Realtime streaming STT for Knowledge Capture via the LiveKit sidecar
    # (gpt-realtime-whisper on the LiveKit PCM track). Master switch separate
    # from the WebRTC speech-to-speech lane (openai_realtime_enabled). Once the
    # master switch is on every LiveKit-capable workspace gets it unless its
    # ``features.voice_realtime_stt`` is false; delay tunes the latency/accuracy
    # tradeoff (minimal|low|medium|high|xhigh).
    voice_realtime_stt_enabled: bool = False
    voice_realtime_stt_delay: str = "low"
    # gpt-realtime-whisper has no OpenAI turn_detection, so the sidecar detects
    # end-of-turn from the PCM and commits manually. These tune that silence VAD
    # (env-tunable so a restart suffices, no sidecar rebuild).
    # silence_ms = how long the PCM must stay below vad_threshold before a turn is
    # committed. 700 ms cut turns on natural mid-sentence pauses ("passage à la
    # ligne" too eager, keyword-sized utterances becoming their own turn); 1200 ms
    # keeps related speech in one turn so the oracle sees fuller context.
    voice_realtime_stt_silence_ms: int = 1200
    voice_realtime_stt_vad_threshold: int = 300
    voice_realtime_stt_max_turn_ms: int = 15000
    # Live "contexte retrouvé" hints run a CPU-bound retrieval (embeddings +
    # reranker) every few seconds WHILE the expert is still speaking. asyncio
    # threads do not release the GIL for that Python CPU work, so it starves the
    # realtime transcript relay (transcript freezes, then a big chunk lands right
    # after the oracle questions). Off by default: the per-turn grounded
    # questions (fired at silence, not during speech) carry the oracle value.
    voice_oracle_live_hints_enabled: bool = False
    # Per-turn live questions ground their gaps on a KB retrieval before the LLM
    # call. In-process that retrieval holds the GIL long enough to freeze the
    # NEXT turn's transcript relay. Re-enabled now that the retrieval runs in the
    # Celery worker process (separate GIL) via voice_oracle_retrieval_via_worker:
    # the backend loop only enqueues + awaits loop-free, so the relay is never
    # blocked. On worker timeout/empty the caller falls back to statement-grounded
    # questions, so questions always appear.
    voice_oracle_live_questions_retrieval_enabled: bool = True
    # Route the oracle's per-turn KB retrieval through the Celery worker (its own
    # GIL) instead of running it in-process on the realtime event loop.
    voice_oracle_retrieval_via_worker: bool = True
    # Short oracle-retrieval deadline (NOT rag_retrieval_worker_timeout_seconds,
    # which is the 120s chat budget). Past this the caller falls back.
    voice_oracle_retrieval_timeout_seconds: float = 2.5
    # Queue for oracle retrieval tasks. Empty => celery_task_default_queue (cpu);
    # set to a dedicated queue (e.g. "oracle") to avoid ingest/deep contention.
    voice_oracle_retrieval_queue: str = ""
    local_stt_endpoint_url: Optional[str] = None
    local_tts_endpoint_url: Optional[str] = None
    local_realtime_endpoint_url: Optional[str] = None

    # LiveKit transport lane. Disabled by default: backend_ws remains the
    # production-safe voice transport until the realtime Docker profile is
    # explicitly configured.
    livekit_enabled: bool = False
    livekit_url: Optional[str] = None
    livekit_internal_url: Optional[str] = None
    livekit_api_key: Optional[str] = None
    livekit_api_secret: Optional[str] = None
    livekit_webhook_api_key: Optional[str] = None
    livekit_webhook_api_secret: Optional[str] = None
    livekit_room_prefix: str = "agentium"
    livekit_default_room_ttl_seconds: int = 3600
    livekit_room_empty_timeout_seconds: int = 60
    livekit_room_departure_timeout_seconds: int = 20
    livekit_agent_identity_prefix: str = "agentium-agent"
    livekit_agent_dispatch_url: Optional[str] = None
    livekit_http_timeout_seconds: float = 5.0
    livekit_voice_gateway_ws_url: Optional[str] = None
    livekit_voice_bridge_token_ttl_seconds: int = 3600
    livekit_redis_address: Optional[str] = None
    livekit_turn_mode: str = "external_or_none"
    livekit_agents_mode: str = "sidecar_http_bridge"
    livekit_egress_enabled: bool = False

    # Domain-aware transcript rewrite on the capture voice loop's `improved`/`final`
    # stages. A hybrid glossary (workspace KB-derived + live plan topics + retrieved
    # chunks) drives a deterministic Tier-1 correction (fuzzy near-homophones,
    # acronym casing). The optional Tier-2 LLM pass stays OFF by default and is
    # timeout-bounded so it never delays the live cascade; `transcript.partial`
    # (raw) is never touched.
    voice_transcript_rewrite_enabled: bool = True
    voice_transcript_rewrite_llm_enabled: bool = True
    voice_transcript_rewrite_timeout_ms: int = 1200
    voice_transcript_glossary_max_terms: int = 120

    # Minimum delay between two server-side incremental transcriptions of the
    # growing audio buffer. The live preview re-transcribes the whole utterance
    # each tick (webm/opus clusters are not independently decodable, so true
    # delta/windowed STT is unsafe), so a larger interval directly reduces how
    # many times the live transcript is rewritten for a long answer (fewer,
    # more stable refreshes instead of 10+).
    # Tuned from runtime traces: actual STT runs ~0.5-1.0s on short/medium
    # buffers (gpt-4o-mini-transcribe) and an in-flight guard already prevents
    # overlapping calls, so the flat floor was the dominant latency term (4000ms
    # -> ~5s refresh; 2000ms -> ~3.2s). 1200ms keeps one call at a time while
    # letting short turns refresh at ~1.2-1.7s; long turns self-regulate at
    # their full-buffer STT cost.
    voice_partial_stt_min_interval_ms: int = 1200

    # Static domain framing injected into the FINAL (end-of-section / end-of-capture)
    # LLM reformulation only — never the live capture path. Domain-neutral default;
    # overridable per workspace via ``workspace.settings.voice.transcript_rewrite_context``.
    voice_transcript_rewrite_context: str = "Nous sommes dans un contexte industriel."

    # Minimum NORMALIZED per-chunk relevance score for KB sources attached to
    # capture FINAL reports. Interpreted against a [0, 1]-scale signal carried in
    # the chunk metadata — the cross-encoder sigmoid score when present, else the
    # per-chunk dense cosine (``dense_score``). It is NOT applied to the RRF
    # fusion score returned by retrieval (that score is rank-fusion weight whose
    # scale is path-dependent: ~0.005-0.02 on the client-weighted RRF path vs
    # ~3-22 on the Qdrant server-side RRF path, so a cosine threshold there drops
    # genuinely relevant evidence). Default 0.35: a dense cosine of ~0.35 keeps
    # both an abstract-but-on-topic chunk (observed ~0.367) and a strong match
    # (~0.626) while still discarding near-zero noise; cross-encoder scores for
    # relevant passages sit comfortably above this floor. Chunks with NO
    # normalized signal (e.g. sparse-only hits) are kept rather than dropped.
    capture_report_source_min_score: float = 0.35

    # Cascade TTS voice + steering. The steerable gpt-4o-mini-tts model accepts
    # an `instructions` field to control accent / persona / prosody; tts-1 and
    # tts-1-hd do NOT (instructions are dropped whenever the resolved model is
    # not a 4o-tts model, including the fast fallback). `sage` is a calm,
    # measured preset that is also available on tts-1, so the fallback path
    # keeps the same voice and only loses steering. Workspaces can override both
    # via voice_runtime settings ({"voice": ..., "instructions": ...}); these
    # are the global defaults. French-first persona for the Andritz workspace.
    openai_tts_voice: str = "sage"
    openai_tts_instructions: str = (
        "Parle en français de France, sans aucun accent anglo-américain. "
        "Adopte un ton d'expert industriel posé, professionnel et rassurant, "
        "avec une légère chaleur. Débit mesuré et régulier, articulation claire "
        "des nombres et des unités (mètres cubes par heure, bars, degrés Celsius)."
    )

    # Keycloak OIDC (papai-org realm, core-service client)
    # keycloak_url: public URL, used for "iss" validation and user-facing links
    # keycloak_url_internal: server-to-server URL (admin API, token, JWKS) — defaults to keycloak_url
    keycloak_url: str = "http://localhost:8080"
    keycloak_url_internal: Optional[str] = None
    keycloak_realm: str = "papai-org"
    keycloak_client_id: str = "core-service"
    keycloak_client_secret: Optional[str] = None
    keycloak_resource_server_id: str = "core-resource-server"
    # Public URL of the Agentium web app; used as the post-action redirect for
    # Keycloak action emails (invitation / signup). Must match one of the
    # core-service client's registered redirectUris.
    app_public_url: Optional[str] = None

    # Redis (optional, not required for demo)
    redis_url: str = "redis://localhost:6379/0"

    # SMTP (for MFA email codes and account notifications)
    smtp_host: Optional[str] = None
    smtp_port: int = 465
    smtp_ssl: bool = True
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None
    smtp_from_name: str = "Agentium"

    # MFA (email OTP)
    mfa_enabled_default: bool = False  # Can be overridden per user
    mfa_code_ttl_seconds: int = 300
    mfa_max_attempts: int = 5

    log_level: str = "INFO"
    intelligence_scheduler_enabled: bool = False
    intelligence_scheduler_interval_seconds: int = 43200
    intelligence_batch_max_articles: int = 20
    intelligence_batch_retry_skipped: bool = False
    intelligence_batch_safety_check_enabled: bool = False

    # SharePoint OTP connector
    # Persistence of captured sessions and MSAL token caches (encrypted at rest
    # when sharepoint_connector_fernet_key is set). Path is relative to the
    # process CWD, typically the repo root on the demo VM.
    sharepoint_session_dir: str = ".sharepoint_sessions"
    sharepoint_download_dir: str = "./downloads/sharepoint"
    sharepoint_connector_fernet_key: Optional[str] = None
    sharepoint_connector_require_encryption: bool = False

    # Custom chain (System.flow_definition) versioning — Vague E / E3.1.
    # Rolling window of SystemVersion rows kept per system. At each save
    # past this cap, the oldest version_number is purged (FIFO). 500 is
    # the default agreed on 2026-04-24 (profondeur large pour retrouver
    # un flow d'il y a plusieurs mois de modifs, plafond dur pour que
    # la table n'explose pas). Lower it for tests or raise it if a
    # client demands deeper history without re-migration.
    custom_chain_version_window: int = 500

    # Transverse IAM engine rollout. Dry-run/evaluate is available everywhere.
    # Enforcement is the workspace default (``features.iam_enforced``, absent
    # means enforced); true here enforces it even where a workspace opted out.
    iam_generic_engine: bool = False

    # P4 is double-gated: this global kill switch and an explicit per-System
    # settings.features.subflow_celery=true opt-in must both be present.
    enable_subflow_celery: bool = False

    # Durable Celery continuation for ordinary/in-process HITL is a separate
    # rollout from delegated P4.  It is enabled only when this deployment flag
    # and settings.features.run_hitl_celery=true are both present.  Keeping the
    # default off preserves the historical FastAPI BackgroundTask path.
    enable_run_hitl_celery: bool = False

    # Dedicated P4 repair loop.  It remains a process-level no-op until this
    # switch is explicitly enabled; the execution-plane flags above keep their
    # separate rollout semantics.  Each pass is bounded so a large backlog can
    # never monopolise the maintenance process.
    enable_p4_maintenance: bool = False
    p4_maintenance_interval_seconds: float = Field(default=5.0, ge=1.0, le=300.0)
    p4_maintenance_batch_size: int = Field(default=50, ge=1, le=1000)
    p4_maintenance_lease_seconds: int = Field(default=60, ge=5, le=3600)

    # Python recipe nodes — author-written scripts executed on the Celery
    # worker inside content-addressed virtual environments. Fail-closed by
    # default (same rollout posture as enable_p4_maintenance): the wrapper
    # refuses to dispatch and the worker refuses to execute until the
    # deployment explicitly enables the plane AND mounts the envs volume.
    recipe_execution_enabled: bool = False
    recipe_envs_path: str = "./data/recipe_envs"
    recipe_pip_default_index_url: str = ""  # empty = pip default (PyPI)
    recipe_execution_default_timeout_s: float = Field(default=120.0, ge=1.0)
    recipe_execution_max_timeout_s: float = Field(default=600.0, ge=1.0)
    recipe_execution_memory_limit_mb: int = Field(default=1024, ge=64)
    recipe_execution_cpu_limit_s: int = Field(default=300, ge=1)
    recipe_execution_output_max_bytes: int = Field(default=512 * 1024, ge=1024)
    recipe_execution_log_tail_chars: int = Field(default=4000, ge=200)
    recipe_execution_max_code_bytes: int = Field(default=200 * 1024, ge=1024)
    recipe_env_build_timeout_s: float = Field(default=600.0, ge=10.0)
    # Storage governor for the venv store: above the quota the sweep evicts
    # least-recently-used ready envs down to the low watermark; idle envs past
    # the TTL are evicted regardless. The shared pip cache keeps rebuild cost
    # near zero and is itself capped.
    recipe_envs_max_total_bytes: int = Field(default=10 * 1024**3, ge=0)
    recipe_envs_low_watermark_bytes: int = Field(default=8 * 1024**3, ge=0)
    recipe_envs_idle_ttl_days: int = Field(default=14, ge=1)
    recipe_envs_min_idle_minutes: int = Field(default=60, ge=0)
    # Never-built `pending` rows nothing references are deleted past this
    # window; resolve recreates them on demand, so only DB noise is at stake.
    recipe_envs_pending_purge_hours: int = Field(default=24, ge=1)
    recipe_pip_cache_max_bytes: int = Field(default=2 * 1024**3, ge=0)

    # Tabular data plane — datasets (Parquet in the ObjectStore), SQL/Polars
    # transform nodes and the sklearn training plane. Unlike recipe execution
    # this runs no author-written code by itself, so it ships enabled; the
    # transform/train nodes that DO run author code stay gated behind
    # ``recipe_execution_enabled``.
    # Hub transfer workers write this cache; inference workers mount it read-only.
    hf_cache_dir: str = "/data/hub-cache"
    hf_cache_max_bytes: int = Field(default=40 * 1024**3, ge=1024)
    hf_cache_min_free_bytes: int = Field(default=2 * 1024**3, ge=0)
    hf_disk_min_free_bytes: int = Field(default=10 * 1024**3, ge=0)
    hf_import_timeout_seconds: int = Field(default=7200, ge=60)
    hf_import_lease_seconds: int = Field(default=300, ge=30)
    hf_download_timeout_seconds: int = Field(default=60, ge=5, le=600)
    hf_max_files: int = Field(default=512, ge=1, le=10000)
    tabular_data_enabled: bool = True
    tabular_upload_max_bytes: int = Field(default=256 * 1024**2, ge=1024)
    tabular_preview_rows: int = Field(default=50, ge=1, le=500)
    # Ceiling on a page the preview route serves. The fifty rows cached on the
    # row answer the page load; this answers "show me more", and it is bounded
    # because the read happens in the web process — a caller asking for a
    # hundred thousand rows would be asking it to hold them.
    tabular_preview_page_max: int = Field(default=500, ge=1, le=5_000)
    tabular_max_columns: int = Field(default=512, ge=1)
    tabular_histogram_bins: int = Field(default=12, ge=2, le=64)
    tabular_top_values: int = Field(default=6, ge=1, le=50)
    # Guard for the in-worker duckdb SQL node: a statement is refused past this
    # size and a result past this row count is truncated rather than persisted.
    tabular_sql_max_chars: int = Field(default=40_000, ge=100)
    tabular_transform_max_rows: int = Field(default=5_000_000, ge=1)
    # Polars transform node. Author code runs on the venv interpreter, so the
    # engine itself has to be IN the venv: this pin is prepended to the node's
    # requirements and is therefore part of the env fingerprint. Keep it aligned
    # with the pin in requirements.txt so a frame written by the worker and a
    # frame written by the harness stay format-compatible.
    tabular_polars_requirement: str = "polars==1.44.0"
    tabular_polars_default_timeout_s: float = Field(default=180.0, ge=1.0)
    # A dataframe engine needs a wider ceiling than a plain script: RLIMIT_AS
    # caps VIRTUAL memory and polars' arena allocator reserves far more than it
    # commits (at 1 GiB it cannot even spawn its background threads). Thread
    # count is capped too so one node cannot monopolise the worker's cores.
    tabular_polars_memory_limit_mb: int = Field(default=3072, ge=512)
    tabular_polars_max_threads: int = Field(default=2, ge=1, le=32)
    # dbt transform node. Same posture as Polars — the engine lives in the venv
    # and is therefore part of the env fingerprint — with one addition: dbt is a
    # project, not a statement, so the node carries a small model tree and the
    # caps below bound how large that tree may get.
    # Both halves of the engine are pinned because the adapter only declares a
    # floor on the one underneath it (``dbt-core>=1.8.0``). Left transitive, the
    # core would resolve differently on two machines that built this env months
    # apart while the fingerprint — the hash of these very lines — stayed
    # identical, and a content-addressed cache that cannot tell two different
    # engines apart is worse than none.
    tabular_dbt_requirement: str = "dbt-duckdb==1.9.4\ndbt-core==1.12.3"
    tabular_dbt_default_timeout_s: float = Field(default=300.0, ge=1.0)
    tabular_dbt_memory_limit_mb: int = Field(default=3072, ge=512)
    tabular_dbt_max_threads: int = Field(default=2, ge=1, le=32)
    tabular_dbt_max_models: int = Field(default=12, ge=1, le=100)
    tabular_dbt_max_model_chars: int = Field(default=40_000, ge=100)
    # MLflow tracking/registry. Kept for a later phase: today the artifact is
    # written in the MLflow model FORMAT into the ObjectStore and the ml_models
    # table is the registry, so no tracking server has to be operated for facts
    # that table already holds.
    mlflow_tracking_uri: str = ""
    mlflow_artifact_root: str = ""
    mlflow_experiment_name: str = "agentium"
    # No-code training node. Unlike the transform engines this one runs NO
    # author-written code — the estimator comes from a curated catalog — so it
    # runs on the APPLICATION interpreter rather than a managed venv: the
    # serving path unpickles what training pickled, and a version skew between
    # two sklearn installs is a load failure with no useful error.
    ml_train_enabled: bool = True
    ml_train_max_rows: int = Field(default=2_000_000, ge=100)
    ml_train_min_rows: int = Field(default=40, ge=4)
    ml_train_max_features: int = Field(default=256, ge=1)
    ml_train_max_classes: int = Field(default=24, ge=2)
    ml_train_timeout_s: float = Field(default=900.0, ge=10.0)
    ml_train_memory_limit_mb: int = Field(default=6144, ge=1024)
    ml_train_cpu_limit_s: int = Field(default=1800, ge=30)
    # A fitted forest is megabytes, not kilobytes: the harness writes the model
    # directory itself, so its file-size ceiling has to fit an artifact.
    ml_train_artifact_limit_mb: int = Field(default=512, ge=16)
    # skore's report state is the evaluation itself — the split rows and the
    # cached predictions — so it is kept as an artifact and its size tracks the
    # dataset. Above this it is dropped rather than stored: a metric that can be
    # recomputed later is worth a few megabytes, not a few hundred. 0 to disable.
    ml_train_report_state_limit_mb: int = Field(default=64, ge=0)
    ml_train_importance_rows: int = Field(default=2_000, ge=100)
    # Points kept per curve. A ROC is drawn ~300px wide, so 500 samples is more
    # than one per pixel — the cap exists to bound the JSON a model card carries,
    # not to smooth the curve, and at 120 a steep early climb visibly stepped.
    ml_train_curve_points: int = Field(default=500, ge=10, le=2_000)
    ml_train_threads: int = Field(default=2, ge=1, le=64)
    # Fixed by default so retraining the same dataset with the same knobs is a
    # comparison and not a coin toss — the demo claim "v2 beats v1" has to mean
    # something.
    ml_train_random_state: int = Field(default=42, ge=0)
    # Which runtime this process is: "worker" for the general image, or the
    # name of a model family's image (ML_RUNTIME, set by that image). A worker
    # whose runtime is not "worker" announces itself in ml_runtime_heartbeats,
    # and a family trained there is only offered while one is fresh.
    ml_runtime: str = "worker"
    ml_runtime_heartbeat_s: float = Field(default=60.0, ge=5.0, le=3600.0)
    ml_runtime_heartbeat_ttl_s: float = Field(default=180.0, ge=15.0, le=86_400.0)
    # Forecasting bounds: what keeps a no-code forecast from asking for a year
    # of hourly steps, a thousand series or a lag the history cannot supply.
    ml_ts_max_horizon: int = Field(default=720, ge=1, le=10_000)
    ml_ts_max_series: int = Field(default=200, ge=1, le=5_000)
    ml_ts_max_lag: int = Field(default=744, ge=1, le=10_000)
    # A forecast answered in the request: how long the API waits for the ml-ts
    # worker, and how many rows of future covariates one call may carry.
    ml_forecast_timeout_s: float = Field(default=30.0, ge=1.0, le=300.0)
    ml_forecast_max_rows: int = Field(default=20_000, ge=1, le=500_000)
    # A Flow node's forecast: the whole panel written as a dataset, by the ml-ts
    # worker, while the node waits on the dataset row it reserved.
    ml_forecast_batch_timeout_s: float = Field(default=600.0, ge=10.0, le=7_200.0)
    # Serving. A loaded pyfunc is tens of megabytes of resident pipeline, so the
    # cache is small by design: it exists to make the second prediction of a
    # demo instant, not to hold a workspace's whole registry in memory.
    ml_predict_enabled: bool = True
    ml_predict_cache_size: int = Field(default=4, ge=1, le=64)
    # Inline predictions answer in the request, so the batch has to stay small
    # enough to be a request. Scoring a whole dataset is the Flow node's job and
    # is bounded by ``tabular_transform_max_rows`` instead.
    ml_predict_max_rows: int = Field(default=100, ge=1, le=10_000)
    ml_predict_timeout_s: float = Field(default=60.0, ge=1.0)
    # Scoring a dataset is a Flow node, so it may be large — but it is still one
    # in-process pass, which is why it stops well below the transform ceiling.
    ml_score_max_rows: int = Field(default=1_000_000, ge=1)
    # Keys are per model and minted from the model card, so the ceiling is about
    # keeping a card readable, not about capacity.
    ml_predict_max_keys: int = Field(default=8, ge=1, le=64)
    # MLflow tracking + Model Registry. There is no MLflow *server* to operate:
    # the client writes straight to a SQL backend store, which is the only store
    # that supports the registry at all (a bare ``mlruns/`` file store does not,
    # a documented trap). Empty means "derive a database named `mlflow` from
    # DATABASE_URL", so the registry lands in the same Postgres instance and the
    # same dump routine as everything else. The payoff is portability, and it is
    # checkable: `mlflow server --backend-store-uri <this>` serves the registry
    # read-only, and a stock MLflow client resolves a version's `source`
    # straight off MinIO.
    ml_registry_enabled: bool = True
    ml_registry_uri: str = ""

    # Secure Deposit — public drop links backed by workspace membership.
    secure_deposit_public_base_url: Optional[str] = None
    secure_deposit_session_secret: str = ""
    secure_deposit_session_ttl_seconds: int = 7200

    # Per-collection access (L35) — HMAC key that signs the member identity a
    # retrieval carries across processes (Celery deep retrieval). Shared by the
    # API and the workers; derived from ``database_url`` when left empty.
    collection_access_signing_key: str = ""
    collection_access_identity_ttl_seconds: int = 43200
    secure_deposit_default_max_file_size_mb: int = 100
    secure_deposit_allowed_extensions: str = (
        "pdf,doc,docx,xls,xlsx,ppt,pptx,txt,csv,md,png,jpg,jpeg,tif,tiff,webp"
    )
    # "local" keeps staged uploads on a filesystem, which only works where the
    # API and the SFTP transport share one. "object_store" puts them in the
    # artifact store, which is what lets them run as separate pods.
    secure_deposit_storage_backend: str = "local"
    secure_deposit_storage_dir: str = "./data/secure_deposit"
    secure_deposit_cache_ttl_seconds: int = 3600
    secure_deposit_archive_promotion_max_files: int = 50
    secure_deposit_sftp_host: str = "0.0.0.0"
    secure_deposit_sftp_port: int = 2222
    secure_deposit_sftp_host_key_path: str = "./data/secure_deposit/sftp_host_key"
    secure_deposit_sftp_temp_dir: str = "./data/secure_deposit/_sftp_uploads"

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
    )


def _settings_env_file() -> str | None:
    """Disable implicit dotenv reads for an attested production runtime.

    Docker and systemd inject the frozen environment explicitly.  Continuing
    to read ``backend/.env`` from the working directory would otherwise allow
    a later file edit to add configuration which isn't present in the
    deployment's immutable runtime-env bundle.
    """

    mode = os.environ.get("AGENTIUM_DISABLE_DOTENV", "0")
    if mode not in {"0", "1"}:
        raise RuntimeError("AGENTIUM_DISABLE_DOTENV must be 0 or 1")
    return None if mode == "1" else ".env"


settings = Settings(_env_file=_settings_env_file())
