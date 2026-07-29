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
    
    def __new__(cls, *, create_if_missing: bool = True):
        # ``create_if_missing`` is consumed by ``__init__``.  Keeping it in the
        # explicit ``__new__`` signature matters because this class is a
        # singleton: Python forwards constructor keyword arguments to both
        # methods.
        del create_if_missing
        if cls._instance is None:
            cls._instance = super(SettingsManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, *, create_if_missing: bool = True):
        if not self._initialized:
            self._load_settings(create_if_missing=create_if_missing)
            self._create_if_missing = create_if_missing
            SettingsManager._initialized = True
        elif not create_if_missing and getattr(self, "_create_if_missing", True):
            # A process advertised as non-mutative must never silently reuse a
            # singleton that was initialized through the legacy create path.
            # Failing startup is safer than claiming a read-only proof after a
            # possibly mutating initialization.
            raise RuntimeError(
                "SettingsManager was already initialized with create_if_missing=True"
            )
    
    def _load_settings(self, *, create_if_missing: bool = True):
        """Load settings from database.

        Preferred source of truth is the workspace-default ``rag_presets`` row;
        if none exists yet (e.g. pre-migration or mid-bootstrap) we fall back
        to the legacy ``app_settings`` singleton. This keeps the process-wide
        singleton aligned with the new multi-scope preset model without
        breaking any caller that still uses ``get_app_settings()``.
        """
        try:
            db = SessionLocal()
            try:
                loaded_from_preset = False
                try:
                    from app.services.rag_preset_service import RagPresetService
                    from app.models.rag_preset import RagPreset
                    default = (
                        db.query(RagPreset)
                        .filter(
                            RagPreset.scope == "workspace",
                            RagPreset.workspace_id.is_(None),
                            RagPreset.scope_id.is_(None),
                            RagPreset.is_default.is_(True),
                        )
                        .order_by(RagPreset.created_at.asc())
                        .first()
                    )
                    if default and default.config:
                        merged = self._get_default_settings()
                        merged.update(dict(default.config))
                        self._settings = merged
                        loaded_from_preset = True
                        logger.info(
                            "Settings loaded from rag_presets",
                            preset_id=default.id,
                        )
                except Exception as preset_error:  # pragma: no cover - defensive
                    logger.debug(
                        "rag_presets lookup skipped — falling back to app_settings",
                        error=str(preset_error),
                    )

                if loaded_from_preset:
                    return

                loaded = SettingsService.get_settings(
                    db, create_if_missing=create_if_missing
                )
                self._settings = {**self._get_default_settings(), **loaded}
                logger.info("Settings loaded from app_settings table")
            except Exception as db_error:
                # Check if it's a missing column error (migration not run yet)
                error_str = str(db_error)
                if "no such column" in error_str.lower() or "rag_vector_db_type" in error_str:
                    logger.warning("Database migration may not be complete. Using defaults for new columns.", error=error_str)
                    # Try to get partial settings and merge with defaults
                    try:
                        partial_settings = SettingsService.get_settings(
                            db,
                            ignore_missing_columns=True,
                            create_if_missing=create_if_missing,
                        )
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
        self._load_settings(create_if_missing=self._create_if_missing)
    
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
            "ragCandidatePoolK": 48,
            "ragSynthesisK": 12,
            "ragSourceDisplayK": 8,
                "ragSimilarityThreshold": 0.2,  # Lowered from 0.7 - cosine similarity scores are typically 0.2-0.5 range
            "ragCollectionName": "documents",
            "ragUseHybridSearch": True,
            "ragVectorWeight": 0.7,
            "ragBM25Weight": 0.3,
            "ragVectorDBType": app_config.default_vector_db_type,
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


def get_settings_manager(*, create_if_missing: bool = True) -> SettingsManager:
    """Get global settings manager instance"""
    global _settings_manager
    if _settings_manager is None:
        _settings_manager = SettingsManager(create_if_missing=create_if_missing)
    elif not create_if_missing and getattr(
        _settings_manager, "_create_if_missing", True
    ):
        raise RuntimeError(
            "SettingsManager was already initialized with create_if_missing=True"
        )
    return _settings_manager


def get_app_settings() -> Dict[str, Any]:
    """Get current application settings (process-wide singleton).

    Kept for backward compatibility with callers that don't know their
    workspace / capability / system context. Prefer
    :func:`get_resolved_settings` when the context is available so the
    most specific preset gets picked.
    """
    return get_settings_manager().get_settings()


def get_resolved_settings(
    workspace_id: Optional[str] = None,
    capability_id: Optional[str] = None,
    system_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve the preset config for a given run context.

    Falls back to the process-wide singleton (``get_app_settings``) if the
    database is unavailable or the preset service hasn't been migrated yet,
    so this helper is always safe to call from agent code.
    """
    if not any([workspace_id, capability_id, system_id]):
        return get_app_settings()
    try:
        from app.services.rag_preset_service import RagPresetService
        db = SessionLocal()
        try:
            merged = get_settings_manager()._get_default_settings()
            resolved = RagPresetService.resolve_for(
                db,
                workspace_id=workspace_id,
                capability_id=capability_id,
                system_id=system_id,
            )
            merged.update(resolved or {})
            return merged
        finally:
            db.close()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug(
            "get_resolved_settings fallback",
            error=str(exc),
        )
        return get_app_settings()


def reload_app_settings():
    """Reload application settings from database"""
    get_settings_manager().reload_settings()
