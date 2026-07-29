"""RAG Preset service — CRUD + scope resolver.

Presets are the multi-scope successor to the global `AppSettings` singleton.
The resolver walks the hierarchy system > capability > workspace, and falls
back to the workspace default, then the process-wide defaults (stored in
`settings_manager`). This keeps the Run engine decoupled from authentication
so chat/document code paths that don't know the workspace can still get a
sane payload.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.core.logging import get_logger
from app.models.rag_preset import RagPreset

logger = get_logger(__name__)

VALID_SCOPES = ("workspace", "capability", "system")


def _serialize(preset: RagPreset) -> Dict[str, Any]:
    return {
        "id": preset.id,
        "name": preset.name,
        "scope": preset.scope,
        "scope_id": preset.scope_id,
        "workspace_id": preset.workspace_id,
        "config": dict(preset.config or {}),
        "is_default": bool(preset.is_default),
        "created_at": preset.created_at.isoformat() if preset.created_at else None,
        "updated_at": preset.updated_at.isoformat() if preset.updated_at else None,
    }


class RagPresetService:
    """CRUD + resolver over the `rag_presets` table."""

    # ---------------- CRUD ----------------
    @staticmethod
    def list_presets(
        db: DBSession,
        workspace_id: Optional[str] = None,
        scope: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        q = db.query(RagPreset)
        if workspace_id:
            q = q.filter(
                (RagPreset.workspace_id == workspace_id)
                | (RagPreset.workspace_id.is_(None))
            )
        if scope:
            q = q.filter(RagPreset.scope == scope)
        rows = q.order_by(
            RagPreset.scope.asc(),
            RagPreset.is_default.desc(),
            RagPreset.updated_at.desc(),
        ).all()
        return [_serialize(r) for r in rows]

    @staticmethod
    def get_preset(db: DBSession, preset_id: str) -> Optional[RagPreset]:
        return db.query(RagPreset).filter(RagPreset.id == preset_id).first()

    @staticmethod
    def create_preset(
        db: DBSession,
        *,
        name: str,
        scope: str,
        config: Dict[str, Any],
        scope_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        is_default: bool = False,
    ) -> Dict[str, Any]:
        if scope not in VALID_SCOPES:
            raise ValueError(f"Invalid preset scope '{scope}'")
        preset = RagPreset(
            id=str(uuid4()),
            name=name,
            scope=scope,
            scope_id=scope_id,
            workspace_id=workspace_id,
            config=config or {},
            is_default=False,
        )
        db.add(preset)
        db.flush()
        if is_default:
            RagPresetService._make_default(db, preset)
        db.commit()
        db.refresh(preset)
        logger.info(
            "preset.created",
            preset_id=preset.id,
            scope=scope,
            scope_id=scope_id,
            workspace_id=workspace_id,
        )
        return _serialize(preset)

    @staticmethod
    def update_preset(
        db: DBSession,
        preset_id: str,
        *,
        name: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        config_patch: Optional[Dict[str, Any]] = None,
        scope_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        preset = RagPresetService.get_preset(db, preset_id)
        if not preset:
            return None
        if name is not None:
            preset.name = name
        if scope_id is not None:
            preset.scope_id = scope_id
        if config is not None:
            preset.config = dict(config)
        elif config_patch:
            merged = dict(preset.config or {})
            merged.update(config_patch)
            preset.config = merged
        preset.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(preset)
        logger.info("preset.updated", preset_id=preset.id)
        return _serialize(preset)

    @staticmethod
    def delete_preset(db: DBSession, preset_id: str) -> bool:
        preset = RagPresetService.get_preset(db, preset_id)
        if not preset:
            return False
        if preset.is_default:
            raise ValueError("Cannot delete the default preset for this scope")
        db.delete(preset)
        db.commit()
        logger.info("preset.deleted", preset_id=preset_id)
        return True

    @staticmethod
    def set_default(db: DBSession, preset_id: str) -> Optional[Dict[str, Any]]:
        preset = RagPresetService.get_preset(db, preset_id)
        if not preset:
            return None
        RagPresetService._make_default(db, preset)
        db.commit()
        db.refresh(preset)
        logger.info("preset.set_default", preset_id=preset_id)
        return _serialize(preset)

    @staticmethod
    def _make_default(db: DBSession, preset: RagPreset) -> None:
        (
            db.query(RagPreset)
            .filter(
                RagPreset.id != preset.id,
                RagPreset.scope == preset.scope,
                RagPreset.scope_id == preset.scope_id,
                RagPreset.is_default.is_(True),
            )
            .update({"is_default": False}, synchronize_session=False)
        )
        preset.is_default = True

    # ---------------- Resolver ----------------
    @staticmethod
    def resolve_for(
        db: DBSession,
        workspace_id: Optional[str] = None,
        capability_id: Optional[str] = None,
        system_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Resolve the most specific default preset for a given run context.

        Order of precedence: system > capability > workspace default > first
        workspace default > process defaults. Always returns a camelCase
        config dict (never None).
        """
        candidates: List[RagPreset] = []

        if system_id:
            candidates += (
                db.query(RagPreset)
                .filter(
                    RagPreset.scope == "system",
                    RagPreset.scope_id == system_id,
                    RagPreset.is_default.is_(True),
                )
                .all()
            )
        if capability_id:
            candidates += (
                db.query(RagPreset)
                .filter(
                    RagPreset.scope == "capability",
                    RagPreset.scope_id == capability_id,
                    RagPreset.is_default.is_(True),
                )
                .all()
            )
        if workspace_id:
            candidates += (
                db.query(RagPreset)
                .filter(
                    RagPreset.scope == "workspace",
                    RagPreset.scope_id == workspace_id,
                    RagPreset.is_default.is_(True),
                )
                .all()
            )
            # Backward compatibility for pre-canonical workspace defaults
            # created with workspace_id set but scope_id left NULL.
            if not candidates:
                candidates += (
                    db.query(RagPreset)
                    .filter(
                        RagPreset.scope == "workspace",
                        RagPreset.workspace_id == workspace_id,
                        RagPreset.scope_id.is_(None),
                        RagPreset.is_default.is_(True),
                    )
                    .all()
                )

        # Fallback only to a global workspace default. Never borrow another
        # workspace's default preset: that would leak collection/provider
        # choices across tenants.
        if not candidates:
            row = (
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
            if row:
                candidates = [row]

        if candidates:
            return dict(candidates[0].config or {})

        # Ultimate fallback — process-wide defaults.
        from app.core.settings_manager import get_settings_manager

        # Resolution is a read path.  It must not manufacture the legacy
        # app_settings singleton when no preset exists.
        return get_settings_manager(create_if_missing=False)._get_default_settings()

    @staticmethod
    def get_or_create_workspace_default(
        db: DBSession, workspace_id: Optional[str]
    ) -> RagPreset:
        """Return the workspace-default preset, creating one from the current
        process defaults if missing. Used by the `/settings` compat proxy."""
        q = db.query(RagPreset).filter(
            RagPreset.scope == "workspace",
            RagPreset.is_default.is_(True),
        )
        if workspace_id is None:
            q = q.filter(RagPreset.scope_id.is_(None))
        else:
            q = q.filter(RagPreset.scope_id == workspace_id)
        preset = q.first()
        if preset:
            return preset

        from app.core.settings_manager import get_settings_manager
        defaults = get_settings_manager()._get_default_settings()
        preset = RagPreset(
            id=str(uuid4()),
            name="Default",
            scope="workspace",
            scope_id=workspace_id,
            workspace_id=workspace_id,
            config=defaults,
            is_default=True,
        )
        db.add(preset)
        db.commit()
        db.refresh(preset)
        logger.info(
            "preset.auto_created_workspace_default",
            preset_id=preset.id,
            workspace_id=workspace_id,
        )
        return preset
