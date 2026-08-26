"""Read what a System's last completed Run produced, without running it again.

Systems compose by pipeline today: a node hands its envelope to the next node
inside one graph. The other composition a workspace keeps asking for is across
graphs and across time — a surface that wants the brief last night's pipeline
wrote, not a fresh generation of it. The two are different claims. Re-running
the producer would give a *new* answer, and a page that shows a new answer while
saying "this is what the pipeline concluded" is quietly wrong.

So the read is separate from the execution, and deliberately narrow: the latest
completed Run of one System in this workspace, its ``output_ref``, and nothing
else. Nothing here writes, nothing here schedules, and a System that has never
finished a Run is reported as such rather than raised — the consumer is usually
a page, and "no result yet" is a state a page can render.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.models.run import Run
from app.models.system import System


class SystemRunReadError(Exception):
    """The System named cannot be read in this workspace."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _owned_system(
    db: DBSession,
    *,
    workspace_id: str,
    system_id: str | None,
    system_name: str | None,
) -> System:
    query = db.query(System).filter(System.workspace_id == workspace_id)
    if system_id:
        row = query.filter(System.id == str(system_id)).one_or_none()
    elif system_name:
        row = query.filter(System.name == str(system_name)).order_by(
            System.created_at.asc()
        ).first()
    else:
        raise SystemRunReadError(
            code="SYSTEM_RUN_REFERENCE_REQUIRED",
            message="Name the System to read, by id or by name.",
        )
    if row is None:
        raise SystemRunReadError(
            code="SYSTEM_NOT_FOUND",
            message="No System with that reference exists in this workspace.",
        )
    return row


def latest_completed_output(
    db: DBSession,
    *,
    workspace_id: str,
    system_id: str | None = None,
    system_name: str | None = None,
) -> dict[str, Any]:
    """The output of the newest completed Run of one System, or an absence.

    Ordered by ``completed_at`` rather than by ``started_at``: a long pipeline
    started before a short one can finish after it, and what a reader means by
    "the latest result" is the one that landed last.
    """

    system = _owned_system(
        db,
        workspace_id=workspace_id,
        system_id=system_id,
        system_name=system_name,
    )
    run = (
        db.query(Run)
        .filter(
            Run.workspace_id == workspace_id,
            Run.system_id == system.id,
            Run.status == "completed",
        )
        .order_by(Run.completed_at.desc(), Run.started_at.desc())
        .first()
    )
    if run is None:
        return {
            "system_id": system.id,
            "system_name": system.name,
            "run_id": None,
            "completed_at": None,
            "found": False,
            "output": {},
        }
    output = run.output_ref if isinstance(run.output_ref, dict) else {}
    return {
        "system_id": system.id,
        "system_name": system.name,
        "run_id": run.id,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "found": True,
        "output": output,
    }
