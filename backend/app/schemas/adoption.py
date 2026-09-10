"""Personal experience state, never an authorization or quality verdict."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Step = Literal["example", "question", "source", "result"]


class ExperienceProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    persona: Literal["builder", "operator", "executive"] = "operator"
    journey: Literal["northforge_sources"] = "northforge_sources"
    completed_steps: list[Step] = Field(default_factory=list, max_length=4)
    dismissed: bool = False
    session_id: str | None = Field(default=None, max_length=64)
    run_id: str | None = Field(default=None, max_length=64)


class ExperienceProgressUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona: Literal["builder", "operator", "executive"] | None = None
    completed_step: Step | None = None
    dismissed: bool | None = None
    session_id: str | None = Field(default=None, max_length=64)
    run_id: str | None = Field(default=None, max_length=64)


def update_progress(current: dict, patch: ExperienceProgressUpdate) -> ExperienceProgress:
    progress = ExperienceProgress.model_validate(current or {})
    if patch.persona is not None:
        progress.persona = patch.persona
    if patch.dismissed is not None:
        progress.dismissed = patch.dismissed
    if patch.completed_step and patch.completed_step not in progress.completed_steps:
        progress.completed_steps.append(patch.completed_step)
    if patch.session_id is not None:
        progress.session_id = patch.session_id
    if patch.run_id is not None:
        progress.run_id = patch.run_id
    return progress
