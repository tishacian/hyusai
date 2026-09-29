"""Personal experience state, never an authorization or quality verdict."""
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Step = Literal["example", "question", "source", "result", "documents", "decision"]
Journey = Literal["northforge_sources", "client_sources"]
# Each journey owns its steps. ``northforge_sources`` walks the fictional
# NorthForge corpus of the Showcase; ``client_sources`` walks the workspace's
# own collections and ends on a human decision about agent work.
JOURNEY_STEPS: dict[str, tuple[str, ...]] = {
    "northforge_sources": ("example", "question", "source", "result"),
    "client_sources": ("source", "documents", "question", "decision"),
}
SHOWCASE_WORKSPACE_SLUG = "agentium-showcase"
# How the Cockpit rail shows its zone names. ``auto`` shows them during the
# member's first two weeks in the workspace (from ``first_seen_at``), then
# hides them; ``shown`` and ``hidden`` are the member's explicit choice.
RailLabels = Literal["auto", "shown", "hidden"]


class ExperienceProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    persona: Literal["builder", "operator", "executive"] = "operator"
    journey: Journey = "northforge_sources"
    completed_steps: list[Step] = Field(default_factory=list, max_length=4)
    dismissed: bool = False
    session_id: str | None = Field(default=None, max_length=64)
    run_id: str | None = Field(default=None, max_length=64)
    # ``client_sources`` only: the collection the member chose, so the
    # journey resumes on it. Checked against the workspace on every write.
    collection_id: str | None = Field(default=None, max_length=64)
    rail_labels: RailLabels = "auto"
    # Server-owned: set on the member's first read, never overwritten, never
    # accepted from a client (``ExperienceProgressUpdate`` forbids it).
    first_seen_at: datetime | None = None


class ExperienceProgressUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona: Literal["builder", "operator", "executive"] | None = None
    completed_step: Step | None = None
    dismissed: bool | None = None
    session_id: str | None = Field(default=None, max_length=64)
    run_id: str | None = Field(default=None, max_length=64)
    collection_id: str | None = Field(default=None, max_length=64)
    rail_labels: RailLabels | None = None


def journey_for_workspace(slug: str | None) -> Journey:
    """The journey a workspace offers: the fictional example only in Showcase."""
    return "northforge_sources" if slug == SHOWCASE_WORKSPACE_SLUG else "client_sources"


def step_allowed(journey: str, step: str | None) -> bool:
    return step is None or step in JOURNEY_STEPS.get(journey, ())


def for_journey(current: dict, journey: Journey) -> ExperienceProgress:
    """Return the progress as seen by ``journey``.

    A record written for another journey (for instance NorthForge steps kept
    from before a workspace offered its own sources) says nothing about this
    one: its steps, its dismissal and its conversation are dropped, while the
    member's preferences (persona, rail labels, first sighting) stay.
    """
    progress = ExperienceProgress.model_validate(current or {})
    if progress.journey == journey:
        return progress
    return progress.model_copy(
        update={
            "journey": journey,
            "completed_steps": [],
            "dismissed": False,
            "session_id": None,
            "run_id": None,
            "collection_id": None,
        }
    )


def update_progress(
    current: dict,
    patch: ExperienceProgressUpdate,
    journey: Journey | None = None,
) -> ExperienceProgress:
    progress = (
        for_journey(current, journey) if journey else ExperienceProgress.model_validate(current or {})
    )
    if not step_allowed(progress.journey, patch.completed_step):
        raise ValueError(f"step {patch.completed_step!r} is not part of {progress.journey}")
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
    if patch.collection_id is not None:
        progress.collection_id = patch.collection_id
    if patch.rail_labels is not None:
        progress.rail_labels = patch.rail_labels
    return progress


def with_first_seen(
    current: dict,
    now: datetime | None = None,
    joined_at: datetime | None = None,
) -> tuple[ExperienceProgress, bool]:
    """Return the progress with ``first_seen_at`` set, and whether it was just set.

    An existing value is kept as is: the first sighting is a fact, not a
    preference, so no later read can move it. It starts when the member joined
    the workspace when the membership records it, so long-standing members do
    not restart a newcomer period at their first read after a deploy.
    """
    progress = ExperienceProgress.model_validate(current or {})
    if progress.first_seen_at is not None:
        return progress, False
    if joined_at is not None:
        # ``joined_at`` is stored naive, in UTC.
        progress.first_seen_at = joined_at if joined_at.tzinfo else joined_at.replace(tzinfo=timezone.utc)
    else:
        progress.first_seen_at = now or datetime.now(timezone.utc)
    return progress, True
