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
    # Default to DeepSeek-R1:14B - 128K context window, very fast generation
    # Alternative options: qwen2.5:72b (128K), llama3.1:70b (128K)
    ollama_default_model: str = "deepseek-r1:14b"
    
    # Database
    database_url: str = "sqlite:///./omnirag.db"
    
    # Redis
    redis_url: str = "redis://localhost:6379/0"
    
    # Vector Store
    chroma_persist_directory: str = "./chroma_db"
    
    # Logging
    log_level: str = "INFO"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False
    )


settings = Settings()

