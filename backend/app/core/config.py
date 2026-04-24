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

    # Embeddings
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"

    # RAG: HAH/C-HAH backend pipelines (multi-pass on DocumentService; see pipeline_retrieval.py)
    rag_hah_chah_enabled: bool = True

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

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
    )


settings = Settings()
