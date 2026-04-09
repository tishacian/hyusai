"""Settings manager for loading and accessing application settings"""
from typing import Dict, Any, Optional
from app.services.settings_service import SettingsService
from app.db.base import SessionLocal
from app.core.logging import get_logger
from app.core.config import settings as app_config

logger = get_logger(__name__)


class SettingsManager:
    """Manages application settings loaded from database"""
    
    _instance: Optional['SettingsManager'] = None
    _settings: Dict[str, Any] = {}
    _initialized: bool = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SettingsManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._load_settings()
            SettingsManager._initialized = True
    
    def _load_settings(self):
        """Load settings from database"""
        try:
            db = SessionLocal()
            try:
                self._settings = SettingsService.get_settings(db)
                logger.info("Settings loaded from database")
            except Exception as db_error:
                # Check if it's a missing column error (migration not run yet)
                error_str = str(db_error)
                if "no such column" in error_str.lower() or "rag_vector_db_type" in error_str:
                    logger.warning("Database migration may not be complete. Using defaults for new columns.", error=error_str)
                    # Try to get partial settings and merge with defaults
                    try:
                        partial_settings = SettingsService.get_settings(db, ignore_missing_columns=True)
                        defaults = self._get_default_settings()
                        # Merge defaults with partial settings (defaults take precedence for missing columns)
                        self._settings = {**defaults, **partial_settings}
                    except Exception as fallback_error:
                        logger.warning("Failed to get partial settings, using full defaults", error=str(fallback_error))
                        # If that also fails, just use defaults
                        self._settings = self._get_default_settings()
                else:
                    # Some other error, use defaults
                    logger.warning("Failed to load settings from database, using defaults", error=error_str)
                    self._settings = self._get_default_settings()
            finally:
                db.close()
        except Exception as e:
            logger.warning("Failed to load settings from database, using defaults", error=str(e))
            self._settings = self._get_default_settings()
    
    def reload_settings(self):
        """Reload settings from database"""
        self._load_settings()
    
    def get_settings(self) -> Dict[str, Any]:
        """Get current settings"""
        return self._settings.copy()
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a specific setting value"""
        return self._settings.get(key, default)
    
    def _get_default_settings(self) -> Dict[str, Any]:
        """Get default settings"""
        return {
            "defaultModel": app_config.default_model,
            "defaultProvider": app_config.default_provider,
            "temperature": 0.3,
            "maxTokens": 4000,
            "topK": 5,
            "preferredAgents": [],
            "enableRAG": True,
            "enableReasoning": True,
            "enableSearch": False,
            "ragTopK": 5,
                "ragSimilarityThreshold": 0.2,  # Lowered from 0.7 - cosine similarity scores are typically 0.2-0.5 range
            "ragCollectionName": "documents",
            "ragUseHybridSearch": True,
            "ragVectorWeight": 0.7,
            "ragBM25Weight": 0.3,
            "ragVectorDBType": "faiss",
            "ragChunkingMethod": "recursive_character",  # Default: recursive_character (same as streaming-decision-process)
            "ragChunkSize": 1000,
            "ragChunkOverlap": 200,
            "enableStreaming": True,
            "streamingSpeed": "normal",
            "theme": "light",
            "fontSize": "medium",
            "showReasoningTraces": True,
            "showSources": True,
            "autoExpandReasoning": False,
            "apiUrl": "http://localhost:8000/api/v1",
            "apiTimeout": 30000,
            "enableCaching": True,
            "cacheTTL": 3600,
            "enableRateLimiting": True,
            "rateLimitPerMinute": 60,
            "ollamaBaseUrl": app_config.ollama_base_url,
            "ollamaNumCtx": getattr(app_config, 'ollama_default_num_ctx', 32768),
            "ollamaRopeScale": getattr(app_config, 'ollama_rope_scale', None),
            "ollamaRopeAlpha": getattr(app_config, 'ollama_rope_alpha', None),
        }


# Global settings manager instance
_settings_manager = None


def get_settings_manager() -> SettingsManager:
    """Get global settings manager instance"""
    global _settings_manager
    if _settings_manager is None:
        _settings_manager = SettingsManager()
    return _settings_manager


def get_app_settings() -> Dict[str, Any]:
    """Get current application settings"""
    return get_settings_manager().get_settings()


def reload_app_settings():
    """Reload application settings from database"""
    get_settings_manager().reload_settings()

