"""Application configuration"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """Application settings"""
    
    # Application
    app_name: str = "Omnirag A*"
    app_version: str = "0.1.0"
    debug: bool = False
    
    # API
    api_v1_prefix: str = "/api/v1"
    
    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    # Default to high-context model with rope scaling support
    # Options: qwen3:8b (128K), llama3-gradient:8b (128K), gemma3:9b (128K), phi-4:14b (128K)
    # For 1M+ context: Use models with rope scaling (rope_freq_base, rope_alpha)
    ollama_default_model: str = "qwen3:8b"  # High context (128K), fast, good balance - supports rope scaling
    # Default context window size - optimized for speed (32K is a good balance)
    # Can be increased to 64K or 128K if needed, but will be slower
    ollama_default_num_ctx: int = 32768  # 32K tokens - good balance of speed and context
    # Rope scaling for extended context (optional, model-dependent)
    ollama_rope_scale: Optional[float] = None  # Set if model supports rope scaling
    ollama_rope_alpha: Optional[float] = None  # Set if model supports rope alpha
    
    # Database
    database_url: str = "sqlite:///./omnirag.db"
    
    # Redis
    redis_url: str = "redis://localhost:6379/0"
    
    # Vector Store
    chroma_persist_directory: str = "./chroma_db"
    faiss_persist_directory: str = "./faiss_db"
    default_vector_db_type: str = "faiss"  # Options: "faiss", "chroma"
    
    # Logging
    log_level: str = "INFO"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False
    )


settings = Settings()

