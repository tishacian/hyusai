"""Server-kept progress of the application creation wizard (plan lot 4).

The wizard creates the Experience and its draft at step 1. What it chose
after that, the bindings to create and the audience, used to live only in
the browser, so a reload or a detour to publish a System lost it. This row
keeps that progress until the draft is finalised.
"""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.models.experience import Experience, ExperienceWizardState
from app.services.experience.lifecycle import ExperienceError

MAX_STAGED_BINDINGS = 50
MAX_AUDIENCE_ITEMS = 100


def _owned_experience(db: DBSession, *, workspace_id: str, experience_id: str) -> Experience:
    row = (
        db.query(Experience)
        .filter(Experience.id == experience_id, Experience.workspace_id == workspace_id)
        .first()
    )
    if row is None:
        raise ExperienceError(
            code="EXPERIENCE_NOT_FOUND",
            message="Experience not found.",
            status_code=404,
        )
    return row


def _strings(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_AUDIENCE_ITEMS:
        raise ExperienceError(
            code="EXPERIENCE_WIZARD_STATE_INVALID",
            message=f"{field} must be a list of at most {MAX_AUDIENCE_ITEMS} names.",
            status_code=422,
        )
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item) > 120:
            raise ExperienceError(
                code="EXPERIENCE_WIZARD_STATE_INVALID",
                message=f"{field} holds an invalid name.",
                status_code=422,
            )
        if item.strip() not in out:
            out.append(item.strip())
    return out


def serialize(row: ExperienceWizardState | None) -> dict[str, Any] | None:
    if row is None:
        return None
    state = copy.deepcopy(row.state or {})
    return {
        "experience_id": row.experience_id,
        "step": row.step,
        "staged_bindings": state.get("staged_bindings", []),
        "audience": state.get(
            "audience", {"roles": [], "groups": [], "whole_workspace": False}
        ),
        "updated_by": row.updated_by,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def read(db: DBSession, *, workspace_id: str, experience_id: str) -> ExperienceWizardState | None:
    _owned_experience(db, workspace_id=workspace_id, experience_id=experience_id)
    return db.get(ExperienceWizardState, experience_id)


def save(
    db: DBSession,
    *,
    workspace_id: str,
    experience_id: str,
    step: int,
    staged_bindings: list[dict[str, Any]],
    audience: dict[str, Any],
    actor: str,
) -> ExperienceWizardState:
    _owned_experience(db, workspace_id=workspace_id, experience_id=experience_id)
    if step not in (1, 2, 3):
        raise ExperienceError(
            code="EXPERIENCE_WIZARD_STATE_INVALID",
            message="step must be 1, 2 or 3.",
            status_code=422,
        )
    if len(staged_bindings) > MAX_STAGED_BINDINGS:
        raise ExperienceError(
            code="EXPERIENCE_WIZARD_STATE_INVALID",
            message=f"At most {MAX_STAGED_BINDINGS} staged bindings.",
            status_code=422,
        )
    keys = [spec["binding_key"] for spec in staged_bindings]
    if len(set(keys)) != len(keys):
        raise ExperienceError(
            code="EXPERIENCE_WIZARD_STATE_INVALID",
            message="A staged binding key appears twice.",
            status_code=422,
        )
    state = {
        "staged_bindings": copy.deepcopy(staged_bindings),
        "audience": {
            "roles": _strings(audience.get("roles", []), field="audience.roles"),
            "groups": _strings(audience.get("groups", []), field="audience.groups"),
            "whole_workspace": audience.get("whole_workspace") is True,
        },
    }
    row = db.get(ExperienceWizardState, experience_id)
    if row is None:
        row = ExperienceWizardState(experience_id=experience_id, workspace_id=workspace_id)
        db.add(row)
    row.step = step
    row.state = state
    row.updated_by = actor
    db.flush()
    return row


def clear(db: DBSession, *, experience_id: str) -> None:
    row = db.get(ExperienceWizardState, experience_id)
    if row is not None:
        db.delete(row)
        db.flush()
