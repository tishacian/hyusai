"""Fail closed for voice LLM routes outside the qualified attempt transport."""

from app.db.base import SessionLocal
from app.models.model_usage import UsageBudgetPolicy
from app.models.workspace import Workspace

MESSAGE = "Real-time LLM voice is unavailable while model usage budgets are active. Use the metered assistant."


def unqualified_voice_blocked(workspace_id=None, *, workspace_slug=None):
    if not workspace_id and not workspace_slug:
        return False
    with SessionLocal() as db:
        if not workspace_id:
            workspace_id = db.query(Workspace.id).filter_by(slug=workspace_slug).scalar()
        # A voice session cannot declare itself outside a capped application.
        # Any active application or workspace policy requires qualified routing.
        return bool(
            workspace_id
            and db.query(UsageBudgetPolicy.id)
            .filter_by(workspace_id=workspace_id, enabled=True)
            .first()
        )
