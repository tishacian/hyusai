"""Test helpers for the two Flow authority modes.

``flow_publication_v1`` defaults on, so the dispatch authority resolves runs
through the immutable published pointer and its pinned execution contract. A
fixture that adds a ``System`` row directly skips the creation paths that seed
that pointer, and would be refused with ``PUBLISHED_FLOW_VERSION_INVALID``.

Two remedies, picked by what the test is actually about:

``baseline_flow_publication``
    Seed the production-shaped baseline. Requires every Skill the graph binds to
    exist, because the contract is compiled, not stubbed.

``LEGACY_FLOW_AUTHORITY``
    Workspace settings that opt out. For suites whose subject is the legacy
    mirror contract, or whose fixture graphs reference Skills they never seed.
"""

from __future__ import annotations

from typing import Any

from app.models.system import System
from app.models.workspace import Workspace
from app.services.systems import flow_publication

ACTOR = "test:publication-baseline"

#: Pins a fixture workspace to the pre-publication authority.
LEGACY_FLOW_AUTHORITY: dict[str, Any] = {"features": {flow_publication.FEATURE_KEY: False}}


def baseline_flow_publication(db: Any, system: System) -> System:
    """Seed the draft and published pointer, compiling a real contract.

    A no-op when the System's workspace opts out, so a fixture helper can call
    it unconditionally.
    """

    workspace = db.query(Workspace).filter(Workspace.id == system.workspace_id).one()
    if not flow_publication.flow_publication_enabled(workspace):
        return system
    flow_publication.initialize_publication_state(
        db,
        system=system,
        workspace=workspace,
        actor=ACTOR,
    )
    db.commit()
    return system
