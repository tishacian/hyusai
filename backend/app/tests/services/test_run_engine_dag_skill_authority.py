"""Authoritative System catalog bindings at every DAG execution boundary."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.capability import Capability
from app.models.decision import Decision
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.models.workspace import Workspace
from app.services.run_engine import engine as engine_module
from app.services.run_engine.dag import execute_run_dag, resume_run_dag


def _skill(db, slug: str, *, workspace_id: str | None = None) -> Skill:
    row = Skill(
        id=str(uuid4()),
        workspace_id=workspace_id,
        slug=slug,
        version="1",
        name=slug,
        input_schema={},
        output_schema={},
        execution={"mode": "sync"},
        pricing={"unit_price": 0.0},
    )
    db.add(row)
    db.flush()
    return row


def _capability(
    db,
    slug: str,
    skill: Skill,
    *,
    workspace_id: str | None = None,
) -> Capability:
    row = Capability(
        id=str(uuid4()),
        workspace_id=workspace_id,
        slug=slug,
        name=slug,
        tier="client" if workspace_id else "universal",
        skill_ids=[skill.id],
    )
    db.add(row)
    db.flush()
    return row


def _flow(kind: str, slug: str | None) -> dict:
    config = {"skill_slug": slug} if slug is not None else {}
    if kind == "retry":
        config.update({"max_attempts": 3, "backoff_ms": 0})
    if kind == "loop":
        config.update({"max_iterations": 3})
    return {
        "schema_version": 3,
        "nodes": [
            {"id": "source", "kind": "source"},
            {"id": "work", "kind": kind, "config": config},
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "source", "to": "work"},
            {"from": "work", "to": "sink"},
        ],
    }


def _system_run(
    db,
    *,
    flow: dict,
    skills: list[Skill] | None = None,
    workspace: Workspace | None = None,
    capability: Capability | None = None,
) -> tuple[System, Run]:
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id if workspace else None,
        name="DAG skill authority",
        capability_id=capability.id if capability else None,
        skill_ids=[skill.id for skill in skills or []],
        flow_definition=flow,
    )
    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id if workspace else None,
        system_id=system.id,
        capability_id=capability.id if capability else None,
        status="pending",
        input_ref={"items": [1, 2]},
    )
    db.add_all([system, run])
    db.commit()
    return system, run


@pytest.mark.asyncio
async def test_bound_skill_executes_and_skillless_legacy_task_stays_passthrough(
    db_session,
    monkeypatch,
):
    skill = _skill(db_session, f"bound-{uuid4().hex}")
    calls: list[str] = []

    async def execute(payload, context):
        calls.append(skill.slug)
        return {"allowed": True}

    monkeypatch.setattr(engine_module, "resolve_skill", lambda slug: execute)
    _, run = _system_run(
        db_session,
        flow=_flow("task", skill.slug),
        skills=[skill],
    )
    assert (await execute_run_dag(run.id))["status"] == "completed"
    assert calls == [skill.slug]

    _, passthrough_run = _system_run(
        db_session,
        flow=_flow("task", None),
    )
    assert (await execute_run_dag(passthrough_run.id))["status"] == "completed"
    assert calls == [skill.slug]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["task", "retry", "loop"])
@pytest.mark.parametrize("rogue_kind", ["existing_unbound", "unresolved"])
async def test_task_retry_and_loop_reject_unbound_or_unresolved_slug_before_invocation(
    db_session,
    monkeypatch,
    kind,
    rogue_kind,
):
    bound = _skill(db_session, f"bound-{kind}-{rogue_kind}-{uuid4().hex}")
    rogue_slug = f"missing-{kind}-{uuid4().hex}"
    if rogue_kind == "existing_unbound":
        rogue_slug = _skill(db_session, f"unbound-{kind}-{uuid4().hex}").slug

    monkeypatch.setattr(
        engine_module,
        "resolve_skill",
        lambda slug: pytest.fail("registry invocation crossed the catalog authority gate"),
    )
    _, run = _system_run(
        db_session,
        flow=_flow(kind, rogue_slug),
        skills=[bound],
    )

    result = await execute_run_dag(run.id)

    assert result["status"] == "failed"
    assert result["error"] == "system_catalog_binding_invalid:flow_skill_not_bound"
    assert (
        db_session.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run.id)
        .count()
        == 0
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("visibility", ["foreign", "hidden_global"])
async def test_foreign_and_filtered_global_skill_bindings_fail_before_invocation(
    db_session,
    monkeypatch,
    visibility,
):
    owner = Workspace(
        id=str(uuid4()),
        name="Owner",
        slug=f"owner-{uuid4().hex}",
        settings={"catalog": {}},
    )
    other = Workspace(
        id=str(uuid4()),
        name="Other",
        slug=f"other-{uuid4().hex}",
        settings={},
    )
    db_session.add_all([owner, other])
    db_session.flush()

    if visibility == "foreign":
        skill = _skill(
            db_session,
            f"foreign-{uuid4().hex}",
            workspace_id=other.id,
        )
        capability = None
    else:
        skill = _skill(db_session, f"hidden-global-{uuid4().hex}")
        capability = _capability(db_session, f"global-{uuid4().hex}", skill)
        owner.settings = {"catalog": {"hidden_skills": [skill.slug]}}

    monkeypatch.setattr(
        engine_module,
        "resolve_skill",
        lambda slug: pytest.fail("invisible catalog skill was invoked"),
    )
    _, run = _system_run(
        db_session,
        flow=_flow("task", skill.slug),
        skills=[skill],
        workspace=owner,
        capability=capability,
    )

    result = await execute_run_dag(run.id)

    assert result["status"] == "failed"
    assert result["error"] == "system_catalog_binding_invalid:skill_not_visible"
    assert db_session.query(SkillInvocation).filter_by(run_id=run.id).count() == 0


@pytest.mark.asyncio
async def test_hitl_resume_revalidates_immutable_snapshot_before_tail_invocation(
    db_session,
    monkeypatch,
):
    allowed = _skill(db_session, f"allowed-resume-{uuid4().hex}")
    rogue = _skill(db_session, f"rogue-resume-{uuid4().hex}")
    flow = {
        "schema_version": 3,
        "nodes": [
            {"id": "source", "kind": "source"},
            {"id": "approval", "kind": "hitl", "config": {"prompt": "Approve"}},
            {
                "id": "tail",
                "kind": "task",
                "config": {"skill_slug": allowed.slug},
            },
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "source", "to": "approval"},
            {"from": "approval", "to": "tail"},
            {"from": "tail", "to": "sink"},
        ],
    }
    monkeypatch.setattr(
        engine_module,
        "resolve_skill",
        lambda slug: pytest.fail("resume invoked a skill outside its binding"),
    )
    _, run = _system_run(db_session, flow=flow, skills=[allowed])
    paused = await execute_run_dag(run.id)
    assert paused["status"] == "hitl_pending"

    db_session.expire_all()
    persisted = db_session.query(Run).filter_by(id=run.id).one()
    corrupted_snapshot = dict(persisted.flow_snapshot)
    corrupted_snapshot["nodes"] = [
        {
            **node,
            "config": {"skill_slug": rogue.slug},
        }
        if node.get("id") == "tail"
        else node
        for node in corrupted_snapshot["nodes"]
    ]
    persisted.flow_snapshot = corrupted_snapshot
    decision = db_session.query(Decision).filter_by(id=paused["awaiting_decision"]).one()
    decision.status = "accepted"
    db_session.commit()

    result = await resume_run_dag(run.id, decision_id=decision.id)

    assert result["status"] == "failed"
    assert result["error"] == "system_catalog_binding_invalid:flow_skill_not_bound"
    assert db_session.query(SkillInvocation).filter_by(run_id=run.id).count() == 0
