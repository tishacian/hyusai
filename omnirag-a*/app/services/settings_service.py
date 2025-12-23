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
    def get_settings(db: Session, ignore_missing_columns: bool = False) -> Dict[str, Any]:
        """Get current application settings from database"""
        try:
            db_settings = db.query(AppSettings).filter(AppSettings.id == "default").first()
            
            if not db_settings:
                # Create default settings if none exist
                db_settings = AppSettings(id="default")
                db.add(db_settings)
                db.commit()
                db.refresh(db_settings)
                logger.info("Created default settings")
            
            return SettingsService._settings_to_dict(db_settings, ignore_missing_columns=ignore_missing_columns)
        except Exception as e:
            error_str = str(e)
            # Check if it's a missing column error (migration not run yet)
            if "no such column" in error_str.lower() or "rag_vector_db_type" in error_str:
                if ignore_missing_columns:
                    # Return empty dict so defaults can be merged
                    logger.debug("Ignoring missing column error", error=error_str)
                    return {}
                else:
                    # Re-raise to be handled by caller
                    raise
            else:
                # Some other error, re-raise
                raise
    
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
    def _settings_to_dict(db_settings: AppSettings, ignore_missing_columns: bool = False) -> Dict[str, Any]:
        """Convert database settings to dictionary"""
        # Use getattr with defaults for columns that might not exist yet (before migration)
        result = {
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
        }
        
        # Add optional columns that might not exist yet
        try:
            result["ragCollectionName"] = getattr(db_settings, 'rag_collection_name', None) or 'documents'
        except (AttributeError, Exception):
            result["ragCollectionName"] = 'documents'
        
        try:
            result["ragUseHybridSearch"] = getattr(db_settings, 'rag_use_hybrid_search', True)
        except (AttributeError, Exception):
            result["ragUseHybridSearch"] = True
        
        try:
            result["ragVectorWeight"] = getattr(db_settings, 'rag_vector_weight', 0.7)
        except (AttributeError, Exception):
            result["ragVectorWeight"] = 0.7
        
        try:
            result["ragBM25Weight"] = getattr(db_settings, 'rag_bm25_weight', 0.3)
        except (AttributeError, Exception):
            result["ragBM25Weight"] = 0.3
        
        try:
            result["ragVectorDBType"] = getattr(db_settings, 'rag_vector_db_type', 'faiss')
        except (AttributeError, Exception):
            result["ragVectorDBType"] = 'faiss'
        
        try:
            result["ragChunkingMethod"] = getattr(db_settings, 'rag_chunking_method', 'recursive_character')
        except (AttributeError, Exception):
            result["ragChunkingMethod"] = 'recursive_character'
        
        try:
            result["ragChunkSize"] = getattr(db_settings, 'rag_chunk_size', 1000)
        except (AttributeError, Exception):
            result["ragChunkSize"] = 1000
        
        try:
            result["ragChunkOverlap"] = getattr(db_settings, 'rag_chunk_overlap', 200)
        except (AttributeError, Exception):
            result["ragChunkOverlap"] = 200
        
        result.update({
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
            "ollamaNumCtx": getattr(db_settings, 'ollama_num_ctx', 32768),
            "ollamaRopeScale": getattr(db_settings, 'ollama_rope_scale', None),
            "ollamaRopeAlpha": getattr(db_settings, 'ollama_rope_alpha', None),
        })
        
        return result
    
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
            "ragCollectionName": "rag_collection_name",
            "ragUseHybridSearch": "rag_use_hybrid_search",
            "ragVectorWeight": "rag_vector_weight",
            "ragBM25Weight": "rag_bm25_weight",
            "ragVectorDBType": "rag_vector_db_type",
            "ragChunkingMethod": "rag_chunking_method",
            "ragChunkSize": "rag_chunk_size",
            "ragChunkOverlap": "rag_chunk_overlap",
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
            "ollamaNumCtx": "ollama_num_ctx",
            "ollamaRopeScale": "ollama_rope_scale",
            "ollamaRopeAlpha": "ollama_rope_alpha",
        }
        return mapping.get(key, key)

