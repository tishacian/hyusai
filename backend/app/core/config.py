"""Application configuration"""

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI Orchestration Platform"
    app_version: str = "1.0.0-demo"
    debug: bool = False

    api_v1_prefix: str = "/api/v1"

    # LLM -- OpenAI-first for demo, LLM SDK supports 20+ providers
    openai_api_key: str = ""
    default_provider: str = "openai"
    default_model: str = "gpt-5"

    # Ollama fallback
    ollama_base_url: str = "http://localhost:11434"
    ollama_default_model: str = "qwen3:8b"
    ollama_default_num_ctx: int = 32768
    ollama_rope_scale: Optional[float] = None
    ollama_rope_alpha: Optional[float] = None

    # Database (PostgreSQL recommended; SQLite fallback for dev-only)
    database_url: str = "postgresql://agentium:agentium@localhost:5432/agentium"

    # Vector Store
    faiss_persist_directory: str = "./faiss_db"
    chroma_persist_directory: str = "./chroma_db"
    default_vector_db_type: str = "faiss"

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
    worker_eager_mode: bool = False
    celery_broker_url: str = "amqp://guest:guest@localhost:5672//"
    celery_result_backend: Optional[str] = None
    celery_task_default_queue: str = "cpu"

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
    chat_stream_timeout_seconds: float = 180.0
    bm25_rebuild_inline_max_chunks: int = 50000

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

    # Voice2Voice runtime provider plane. OpenAI Realtime is an optional lane;
    # cascade_openai remains the production-safe default and local providers are
    # integrated through HTTP/WebSocket contracts rather than heavy in-process
    # model dependencies.
    voice_runtime_default_provider: str = "cascade_openai"
    voice_runtime_allowed_providers: str = "cascade_openai,openai_realtime,local_stt,local_tts,local_realtime,realtime_gpu"
    voice_runtime_fallback_providers: str = "cascade_openai"
    voice_realtime_default_transport: str = "backend_ws"
    voice_realtime_webrtc_enabled: bool = False
    openai_realtime_enabled: bool = False
    openai_realtime_enabled_workspace_slugs: str = "andritz"
    openai_realtime_model: str = "gpt-realtime-2"
    openai_realtime_transcribe_model: str = "gpt-realtime-whisper"
    openai_realtime_translate_model: str = "gpt-realtime-translate"
    openai_realtime_api_base: str = "https://api.openai.com/v1"
    openai_realtime_ephemeral_ttl_seconds: int = 600
    local_stt_endpoint_url: Optional[str] = None
    local_tts_endpoint_url: Optional[str] = None
    local_realtime_endpoint_url: Optional[str] = None

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

    # Transverse IAM engine rollout. Dry-run/evaluate is available everywhere;
    # enforcement is active when ``iam_generic_engine`` is true or when the
    # current workspace slug is listed here.
    iam_generic_engine: bool = False
    iam_enforced_workspace_slugs: str = "andritz"

    # Secure Deposit — public drop links backed by workspace membership.
    secure_deposit_enabled_workspace_slugs: str = "andritz"
    secure_deposit_public_base_url: Optional[str] = None
    secure_deposit_session_secret: str = ""
    secure_deposit_session_ttl_seconds: int = 7200
    secure_deposit_default_max_file_size_mb: int = 100
    secure_deposit_allowed_extensions: str = "pdf,doc,docx,xls,xlsx,ppt,pptx,txt,csv,md,png,jpg,jpeg,tif,tiff,webp"
    secure_deposit_storage_dir: str = "./data/secure_deposit"
    secure_deposit_archive_promotion_max_files: int = 50
    secure_deposit_sftp_host: str = "0.0.0.0"
    secure_deposit_sftp_port: int = 2222
    secure_deposit_sftp_host_key_path: str = "./data/secure_deposit/sftp_host_key"
    secure_deposit_sftp_temp_dir: str = "./data/secure_deposit/_sftp_uploads"

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
    )


settings = Settings()
