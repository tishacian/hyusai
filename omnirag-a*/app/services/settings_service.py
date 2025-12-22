"""Settings service for managing application settings"""
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.models.settings import AppSettings
from app.core.logging import get_logger
from app.core.config import settings as app_config

logger = get_logger(__name__)


class SettingsService:
    """Service for managing application settings"""
    
    @staticmethod
    def get_settings(db: Session) -> Dict[str, Any]:
        """Get current application settings from database"""
        db_settings = db.query(AppSettings).filter(AppSettings.id == "default").first()
        
        if not db_settings:
            # Create default settings if none exist
            db_settings = AppSettings(id="default")
            db.add(db_settings)
            db.commit()
            db.refresh(db_settings)
            logger.info("Created default settings")
        
        return SettingsService._settings_to_dict(db_settings)
    
    @staticmethod
    def update_settings(db: Session, settings_update: Dict[str, Any]) -> Dict[str, Any]:
        """Update application settings in database"""
        try:
            db_settings = db.query(AppSettings).filter(AppSettings.id == "default").first()
            
            if not db_settings:
                db_settings = AppSettings(id="default")
                db.add(db_settings)
            
            # Track successful updates
            successful_updates = []
            failed_updates = []
            
            # Update settings fields
            for key, value in settings_update.items():
                # Map frontend keys to database column names
                db_key = SettingsService._map_setting_key(key)
                if hasattr(db_settings, db_key):
                    try:
                        setattr(db_settings, db_key, value)
                        successful_updates.append(key)
                        logger.debug("Updated setting", key=db_key, value=value)
                    except Exception as e:
                        failed_updates.append((key, str(e)))
                        logger.warning(f"Failed to set {db_key}: {e}")
                        # Skip invalid fields instead of failing
                        continue
                else:
                    failed_updates.append((key, f"Column {db_key} not found in model"))
                    logger.warning(f"Setting key {key} (mapped to {db_key}) not found in AppSettings model")
            
            # Update timestamp
            from datetime import datetime
            db_settings.updated_at = datetime.utcnow()
            
            db.commit()
            db.refresh(db_settings)
            
            if failed_updates and not successful_updates:
                # If all updates failed, raise an error
                error_msg = f"Failed to update all settings: {failed_updates}"
                logger.error(error_msg)
                raise ValueError(error_msg)
            elif failed_updates:
                logger.warning(f"Some settings failed to update: {failed_updates}")
            
            logger.info("Settings updated", updated_keys=successful_updates)
            return SettingsService._settings_to_dict(db_settings)
        except Exception as e:
            db.rollback()
            logger.error("Failed to update settings", error=str(e), exc_info=True)
            raise
    
    @staticmethod
    def _settings_to_dict(db_settings: AppSettings) -> Dict[str, Any]:
        """Convert database settings to dictionary"""
        return {
            "defaultModel": db_settings.default_model,
            "defaultProvider": db_settings.default_provider,
            "temperature": db_settings.temperature,
            "maxTokens": db_settings.max_tokens,
            "topK": db_settings.top_k,
            "preferredAgents": db_settings.preferred_agents or [],
            "enableRAG": db_settings.enable_rag,
            "enableReasoning": db_settings.enable_reasoning,
            "enableSearch": db_settings.enable_search,
            "ragTopK": db_settings.rag_top_k,
            "ragSimilarityThreshold": db_settings.rag_similarity_threshold,
            "enableStreaming": db_settings.enable_streaming,
            "streamingSpeed": db_settings.streaming_speed,
            "theme": db_settings.theme,
            "fontSize": db_settings.font_size,
            "showReasoningTraces": db_settings.show_reasoning_traces,
            "showSources": db_settings.show_sources,
            "autoExpandReasoning": db_settings.auto_expand_reasoning,
            "apiUrl": getattr(db_settings, 'api_url', None) or 'http://localhost:8000/api/v1',
            "apiTimeout": db_settings.api_timeout,
            "enableCaching": db_settings.enable_caching,
            "cacheTTL": db_settings.cache_ttl,
            "enableRateLimiting": db_settings.enable_rate_limiting,
            "rateLimitPerMinute": db_settings.rate_limit_per_minute,
            "ollamaBaseUrl": db_settings.ollama_base_url,
        }
    
    @staticmethod
    def _map_setting_key(key: str) -> str:
        """Map frontend setting key to database column name"""
        mapping = {
            "defaultModel": "default_model",
            "defaultProvider": "default_provider",
            "temperature": "temperature",
            "maxTokens": "max_tokens",
            "topK": "top_k",
            "preferredAgents": "preferred_agents",
            "enableRAG": "enable_rag",
            "enableReasoning": "enable_reasoning",
            "enableSearch": "enable_search",
            "ragTopK": "rag_top_k",
            "ragSimilarityThreshold": "rag_similarity_threshold",
            "enableStreaming": "enable_streaming",
            "streamingSpeed": "streaming_speed",
            "theme": "theme",
            "fontSize": "font_size",
            "showReasoningTraces": "show_reasoning_traces",
            "showSources": "show_sources",
            "autoExpandReasoning": "auto_expand_reasoning",
            "apiUrl": "api_url",
            "apiTimeout": "api_timeout",
            "enableCaching": "enable_caching",
            "cacheTTL": "cache_ttl",
            "enableRateLimiting": "enable_rate_limiting",
            "rateLimitPerMinute": "rate_limit_per_minute",
            "ollamaBaseUrl": "ollama_base_url",
        }
        return mapping.get(key, key)

