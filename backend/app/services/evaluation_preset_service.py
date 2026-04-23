"""Resolve + CRUD for :class:`~app.models.evaluation_preset.EvaluationPreset`.

Mirrors :mod:`app.services.rag_preset_service` intentionally — same scope
hierarchy (``system`` > ``capability`` > ``workspace`` > built-in
defaults), same "closest match wins" resolution, same
default_factory for new workspaces.

The threshold config is typed here (not in the model) so the UI can
stay dumb (it just GETs/PUTs a flat dict) and new knobs can be added
without an Alembic migration.
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.core.logging import get_logger
from app.models.evaluation_preset import EvaluationPreset

logger = get_logger(__name__)


# Canonical config defaults. Thresholds calibrated on the realistic
# score bands observed during D4→D7 smoke (see ``METRIC_REGISTRY`` in
# ``chat-panel.component.ts`` for the same philosophy on the client).
#
# composite_score is 0-100 (LLM-as-judge aggregate of 12 dimensions).
# hallucination_rate is 0-1 (fraction of unsupported claims).
DEFAULT_EVAL_CONFIG: Dict[str, Any] = {
    "enabled": False,  # opt-in per workspace/system
    "composite_min": 60.0,  # below = review_required
    "hallucination_max": 0.3,  # above = review_required
    "dimension_min": {
        # Floors that are cheap to tune per client without retraining
        # (safety + hallucination are the only genuinely universal hard
        # requirements; the others are softer guardrails).
        "safety": 80.0,
        "hallucination": 50.0,
    },
    "sample_rate": 1.0,  # 0.0 = no-op, 1.0 = all eligible runs
}


def _merge_with_defaults(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return ``config`` merged onto :data:`DEFAULT_EVAL_CONFIG`.

    Top-level keys on the input win; ``dimension_min`` merges one level
    deep so a client that only overrides ``safety`` doesn't lose the
    default ``hallucination`` floor.
    """
    base = {k: v for k, v in DEFAULT_EVAL_CONFIG.items()}
    base["dimension_min"] = dict(DEFAULT_EVAL_CONFIG["dimension_min"])
    if not config:
        return base
    for key, value in config.items():
        if key == "dimension_min" and isinstance(value, dict):
            base["dimension_min"].update(value)
        else:
            base[key] = value
    return base


class EvaluationPresetService:
    """Thin wrapper — DB-only, no side effects, no cache."""

    def resolve(
        self,
        db: DBSession,
        *,
        workspace_id: Optional[str] = None,
        capability_id: Optional[str] = None,
        system_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return the effective config for the given scope triplet.

        Precedence: system > capability > workspace > built-in defaults.
        Missing keys at the winning scope fall through to the next
        scope via :func:`_merge_with_defaults` called once at the end.
        """
        preset = self._closest_match(
            db,
            workspace_id=workspace_id,
            capability_id=capability_id,
            system_id=system_id,
        )
        config = preset.config if preset else {}
        return _merge_with_defaults(config)

    def _closest_match(
        self,
        db: DBSession,
        *,
        workspace_id: Optional[str],
        capability_id: Optional[str],
        system_id: Optional[str],
    ) -> Optional[EvaluationPreset]:
        if system_id:
            row = (
                db.query(EvaluationPreset)
                .filter(
                    EvaluationPreset.scope == "system",
                    EvaluationPreset.scope_id == system_id,
                )
                .first()
            )
            if row:
                return row
        if capability_id:
            row = (
                db.query(EvaluationPreset)
                .filter(
                    EvaluationPreset.scope == "capability",
                    EvaluationPreset.scope_id == capability_id,
                )
                .first()
            )
            if row:
                return row
        if workspace_id:
            row = (
                db.query(EvaluationPreset)
                .filter(
                    EvaluationPreset.scope == "workspace",
                    EvaluationPreset.workspace_id == workspace_id,
                )
                .first()
            )
            if row:
                return row
        return None

    def get_workspace_preset(
        self, db: DBSession, workspace_id: str
    ) -> Optional[EvaluationPreset]:
        return (
            db.query(EvaluationPreset)
            .filter(
                EvaluationPreset.scope == "workspace",
                EvaluationPreset.workspace_id == workspace_id,
            )
            .first()
        )

    def upsert_workspace_preset(
        self,
        db: DBSession,
        workspace_id: str,
        config: Dict[str, Any],
        *,
        name: str = "Workspace default",
    ) -> EvaluationPreset:
        """Create or update the workspace-scoped preset.

        ``config`` is stored verbatim; callers should pre-merge with
        :data:`DEFAULT_EVAL_CONFIG` if they want to persist a complete
        snapshot (the resolver merges on read anyway so partial configs
        are also safe, just harder to audit).
        """
        existing = self.get_workspace_preset(db, workspace_id)
        if existing:
            existing.config = config
            existing.name = name or existing.name
            db.commit()
            db.refresh(existing)
            return existing

        row = EvaluationPreset(
            id=str(uuid4()),
            name=name,
            scope="workspace",
            scope_id=None,
            workspace_id=workspace_id,
            config=config,
            is_default=True,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row


_service: Optional[EvaluationPresetService] = None


def get_evaluation_preset_service() -> EvaluationPresetService:
    global _service
    if _service is None:
        _service = EvaluationPresetService()
    return _service
