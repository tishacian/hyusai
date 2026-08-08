"""A workspace-defined Skill running in a DAG, and failing closed when it cannot.

The walker dispatches on the slug. The namespace is what lets it decide, without
a query, whether the runtime comes from the hardcoded registry or from the Skill
row's verified executor binding.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.capability import Capability
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.models.workspace import Workspace
from app.services.run_engine import engine as engine_module
from app.services.run_engine.dag import execute_run_dag
from app.services.skills_registry import wrappers
from app.services.skills_registry.binding import workspace_skill_slug

AUTHORED_LOCAL_NAME = "record_reset"


def _authored_run(db, *, executor, local_name: str = AUTHORED_LOCAL_NAME):
    workspace = Workspace(
        id=f"ws-{uuid4().hex[:8]}",
        slug=f"authored-{uuid4().hex[:8]}",
        name="Authored dispatch",
        settings={},
    )
    db.add(workspace)
    db.flush()
    slug = workspace_skill_slug(
        workspace_id=workspace.id,
        local_name=local_name,
    ).slug
    skill = Skill(
        id=str(uuid4()),
        workspace_id=workspace.id,
        slug=slug,
        version="1",
        name="Record reset",
        input_schema={},
        output_schema={},
        execution={"mode": "sync"},
        pricing={"unit_price": 0.0},
        executor=executor,
        is_seeded="N",
    )
    db.add(skill)
    db.flush()
    capability = Capability(
        id=str(uuid4()),
        workspace_id=workspace.id,
        slug=f"authored-cap-{uuid4().hex[:8]}",
        name="Authored capability",
        tier="client",
        skill_ids=[skill.id],
    )
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Authored dispatch",
        capability_id=capability.id,
        skill_ids=[skill.id],
        flow_definition={
            "schema_version": 3,
            "nodes": [
                {"id": "source", "kind": "source"},
                {"id": "work", "kind": "task", "config": {"skill_slug": slug}},
                {"id": "sink", "kind": "sink"},
            ],
            "edges": [
                {"from": "source", "to": "work"},
                {"from": "work", "to": "sink"},
            ],
        },
    )
    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        capability_id=capability.id,
        status="pending",
        input_ref={"event_type": "run_supplied", "details": {"ticket": "INC-1"}},
    )
    db.add_all([capability, system, run])
    db.commit()
    return run, slug


@pytest.mark.asyncio
async def test_an_authored_skill_runs_through_its_verified_executor(
    db_session,
    monkeypatch,
):
    seen: list[dict] = []

    async def _capture(payload, ctx=None):
        seen.append(dict(payload))
        return {"status": "recorded"}

    entry = wrappers._REGISTRY["audit_log_v1"]
    monkeypatch.setitem(wrappers._REGISTRY, "audit_log_v1", (_capture, entry[1], entry[2]))
    run, slug = _authored_run(
        db_session,
        executor={
            "kind": "registry_call",
            "params": {
                "skill_slug": "audit_log_v1",
                "frozen_input": {"event_type": "ticket.reset"},
            },
        },
    )

    result = await execute_run_dag(run.id)

    assert result["status"] == "completed"
    invocation = (
        db_session.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run.id, SkillInvocation.skill_slug == slug)
        .one()
    )
    assert invocation.status == "completed"
    assert invocation.output_ref == {"status": "recorded"}
    # The pinned parameter beat the run's own value, and the rest came through
    # alongside the context the walker adds for every Skill.
    assert len(seen) == 1
    assert seen[0]["event_type"] == "ticket.reset"
    assert seen[0]["details"] == {"ticket": "INC-1"}


@pytest.mark.asyncio
async def test_an_unresolvable_authored_skill_fails_the_node_rather_than_skipping_it(
    db_session,
):
    """The distinction this tranche exists for.

    An unbound *seeded* slug is a node nobody declared a runtime for, which the
    walker records as skipped. An authored Skill whose executor no longer
    verifies has a runtime that the platform refuses to honour, and recording
    that as skipped would leave a Flow that reports having run.
    """

    run, slug = _authored_run(
        db_session,
        executor={"kind": "retired_kind", "params": {}},
    )

    await execute_run_dag(run.id)

    invocation = (
        db_session.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run.id, SkillInvocation.skill_slug == slug)
        .one()
    )
    assert invocation.status == "failed"
    assert invocation.error
    assert "executor" in invocation.error
    assert invocation.output_ref in (None, {})


@pytest.mark.asyncio
async def test_the_seeded_path_still_dispatches_through_the_registry(
    db_session,
    monkeypatch,
):
    """Guard against the namespace check swallowing the seeded catalog."""

    resolved: list[str] = []

    async def _execute(payload, ctx=None):
        return {"allowed": True}

    def _resolve(slug):
        resolved.append(slug)
        return _execute

    monkeypatch.setattr(engine_module, "resolve_skill", _resolve)
    workspace = Workspace(
        id=f"ws-{uuid4().hex[:8]}",
        slug=f"seeded-{uuid4().hex[:8]}",
        name="Seeded dispatch",
        settings={},
    )
    skill = Skill(
        id=str(uuid4()),
        workspace_id=None,
        slug=f"seeded_op_{uuid4().hex[:8]}",
        version="1",
        name="Seeded op",
        input_schema={},
        output_schema={},
        execution={"mode": "sync"},
        pricing={"unit_price": 0.0},
        is_seeded="Y",
    )
    db_session.add_all([workspace, skill])
    db_session.flush()
    capability = Capability(
        id=str(uuid4()),
        workspace_id=workspace.id,
        slug=f"seeded-cap-{uuid4().hex[:8]}",
        name="Seeded capability",
        tier="client",
        skill_ids=[skill.id],
    )
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Seeded dispatch",
        capability_id=capability.id,
        skill_ids=[skill.id],
        flow_definition={
            "schema_version": 3,
            "nodes": [
                {"id": "source", "kind": "source"},
                {"id": "work", "kind": "task", "config": {"skill_slug": skill.slug}},
                {"id": "sink", "kind": "sink"},
            ],
            "edges": [
                {"from": "source", "to": "work"},
                {"from": "work", "to": "sink"},
            ],
        },
    )
    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        capability_id=capability.id,
        status="pending",
        input_ref={},
    )
    db_session.add_all([capability, system, run])
    db_session.commit()

    assert (await execute_run_dag(run.id))["status"] == "completed"
    assert resolved == [skill.slug]
