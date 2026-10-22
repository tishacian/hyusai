"""P1 DAG-walker integration tests for the typed VariablePool.

Verifies that ``inputs_map`` / ``outputs_map`` are actually *read* by the
walker end to end (a producer node writes a namespaced slice that a downstream
consumer node selects), that reserved namespaces are seeded from the run input,
and that a flow with no maps is byte-identical to the legacy flat-merge path.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable, Optional

import pytest

from app.models.context import Context
from app.models.run import Run
from app.models.skill import Skill
from app.models.system import System
from app.models.workspace import Workspace
from app.services.run_engine import engine as engine_module
from app.services.run_engine.dag import _seed_pool, execute_run_dag
from app.services.run_engine.variable_pool import VariablePool, apply_inputs_map

SkillFn = Callable[[dict[str, Any], dict[str, Any]], "Any"]


def _install_fake_registry(monkeypatch, skills: dict[str, SkillFn]) -> None:
    def _resolve(slug: str) -> SkillFn:
        fn = skills.get(slug)
        if fn is None:
            raise NotImplementedError(f"fake registry has no {slug!r}")
        return fn

    monkeypatch.setattr(engine_module, "resolve_skill", _resolve)


def _mk_skill(db, slug: str) -> Skill:
    row = Skill(
        id=str(uuid.uuid4()),
        slug=slug,
        version="v1",
        name=slug,
        description=f"test skill {slug}",
        input_schema={},
        output_schema={},
        pricing={"unit_price": 0.0},
        execution={"mode": "sync", "timeout_ms": 1000, "retryable": True, "idempotent": True},
        certification_level="basic",
    )
    db.add(row)
    db.commit()
    return row


def _mk_system(db, *, flow: dict[str, Any]) -> System:
    skill_slugs = [
        str((node.get("config") or {}).get("skill_slug"))
        for node in (flow.get("nodes") or [])
        if node.get("kind") in {"task", "retry", "loop"}
        and (node.get("config") or {}).get("skill_slug")
    ]
    skill_ids = (
        [row.id for row in db.query(Skill).filter(Skill.slug.in_(skill_slugs)).all()]
        if skill_slugs
        else []
    )
    sys_row = System(
        id=str(uuid.uuid4()),
        name="vp system",
        objective="test",
        skill_ids=skill_ids,
        flow_definition=flow,
    )
    db.add(sys_row)
    db.commit()
    return sys_row


def _mk_run(db, system: System, *, input_ref: Optional[dict[str, Any]] = None) -> Run:
    run = Run(
        id=str(uuid.uuid4()),
        system_id=system.id,
        input_ref=input_ref or {},
        status="pending",
    )
    db.add(run)
    db.commit()
    return run


async def test_outputs_map_then_inputs_map_round_trip(db_session, monkeypatch):
    """Producer writes ``producer.payload`` via outputs_map; consumer reads it
    via inputs_map. The consumer skill must receive the mapped value."""
    seen: dict[str, Any] = {}

    async def producer(inp, ctx):
        return {"payload": {"k": "v"}, "noise": 1}

    async def consumer(inp, ctx):
        seen["input"] = dict(inp)
        return {"done": True}

    _install_fake_registry(monkeypatch, {"producer_v1": producer, "consumer_v1": consumer})
    _mk_skill(db_session, "producer_v1")
    _mk_skill(db_session, "consumer_v1")

    flow = {
        "schema_version": 3,
        "nodes": [
            {"id": "src", "kind": "source"},
            {
                "id": "p",
                "kind": "task",
                "config": {
                    "skill_slug": "producer_v1",
                    "outputs_map": {"payload": "shared.payload"},
                },
            },
            {
                "id": "c",
                "kind": "task",
                "config": {
                    "skill_slug": "consumer_v1",
                    "inputs_map": {"data": "shared.payload"},
                },
            },
            # A control node so the flow is unambiguously DAG-shaped.
            {"id": "jn", "kind": "join", "config": {"strategy": "all"}},
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "src", "to": "p"},
            {"from": "p", "to": "c"},
            {"from": "c", "to": "jn"},
            {"from": "jn", "to": "sink"},
        ],
    }
    system = _mk_system(db_session, flow=flow)
    run = _mk_run(db_session, system, input_ref={"seed": True})

    summary = await execute_run_dag(run.id)
    assert summary["status"] == "completed"
    # The consumer received the value the producer published into the pool.
    assert seen["input"].get("data") == {"k": "v"}


async def test_inputs_map_reads_reserved_run_namespace(db_session, monkeypatch):
    """A ``run.<field>`` selector resolves from the seeded run namespace."""
    seen: dict[str, Any] = {}

    async def consumer(inp, ctx):
        seen["input"] = dict(inp)
        return {"ok": True}

    _install_fake_registry(monkeypatch, {"consumer_v1": consumer})
    _mk_skill(db_session, "consumer_v1")

    flow = {
        "schema_version": 3,
        "nodes": [
            {"id": "src", "kind": "source"},
            {
                "id": "c",
                "kind": "task",
                "config": {
                    "skill_slug": "consumer_v1",
                    "inputs_map": {"q": "run.query"},
                },
            },
            {"id": "jn", "kind": "join", "config": {"strategy": "all"}},
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "src", "to": "c"},
            {"from": "c", "to": "jn"},
            {"from": "jn", "to": "sink"},
        ],
    }
    system = _mk_system(db_session, flow=flow)
    run = _mk_run(db_session, system, input_ref={"query": "hello world"})

    summary = await execute_run_dag(run.id)
    assert summary["status"] == "completed"
    assert seen["input"].get("q") == "hello world"


def test_context_namespace_reads_bound_context_environment_state(db_session):
    context = Context(
        id=str(uuid.uuid4()),
        name="bound context",
        environment_state={"audit_event_type": "system.test.audited"},
    )
    system = System(
        id=str(uuid.uuid4()),
        name="context namespace system",
        objective="test",
        context_id=context.id,
        flow_definition={},
    )
    run = Run(
        id=str(uuid.uuid4()),
        system_id=system.id,
        input_ref={},
        status="pending",
    )
    db_session.add_all([context, system, run])
    db_session.commit()

    pool = VariablePool()
    _seed_pool(db_session, pool, run, system)

    assert pool.get("context.environment_state.audit_event_type") == "system.test.audited"
    assert apply_inputs_map(
        {
            "inputs_map": {
                "event_type": {
                    "node_id": "context",
                    "path": ["environment_state", "audit_event_type"],
                }
            }
        },
        pool,
        {},
        io_mode="strict",
    ) == {"event_type": "system.test.audited"}


def test_context_namespace_rejects_cross_workspace_binding(db_session):
    owner = Workspace(
        id=str(uuid.uuid4()),
        name="Context owner",
        slug=f"context-owner-{uuid.uuid4().hex[:8]}",
    )
    other = Workspace(
        id=str(uuid.uuid4()),
        name="Context other",
        slug=f"context-other-{uuid.uuid4().hex[:8]}",
    )
    foreign_context = Context(
        id=str(uuid.uuid4()),
        workspace_id=other.id,
        name="Foreign context",
        business_constraints={"sensitive_business_rule": "never expose"},
    )
    system = System(
        id=str(uuid.uuid4()),
        workspace_id=owner.id,
        name="Local System",
        objective="test",
        context_id=foreign_context.id,
        flow_definition={},
    )
    run = Run(
        id=str(uuid.uuid4()),
        workspace_id=owner.id,
        system_id=system.id,
        input_ref={},
        status="pending",
    )
    db_session.add_all([owner, other, foreign_context, system, run])
    db_session.commit()

    with pytest.raises(RuntimeError, match="system_context_binding_invalid"):
        _seed_pool(db_session, VariablePool(), run, system)


async def test_no_maps_is_byte_identical_to_flat_merge(db_session, monkeypatch):
    """With no inputs_map, the skill input must be the legacy
    ``{**run_input, **upstream}`` shape (no pool overlay)."""
    seen: dict[str, Any] = {}

    async def first(inp, ctx):
        return {"a": 1}

    async def second(inp, ctx):
        seen["input"] = dict(inp)
        return {"b": 2}

    _install_fake_registry(monkeypatch, {"first_v1": first, "second_v1": second})
    _mk_skill(db_session, "first_v1")
    _mk_skill(db_session, "second_v1")

    flow = {
        "schema_version": 3,
        "nodes": [
            {"id": "src", "kind": "source"},
            {"id": "n1", "kind": "task", "config": {"skill_slug": "first_v1"}},
            {"id": "n2", "kind": "task", "config": {"skill_slug": "second_v1"}},
            {"id": "jn", "kind": "join", "config": {"strategy": "all"}},
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "src", "to": "n1"},
            {"from": "n1", "to": "n2"},
            {"from": "n2", "to": "jn"},
            {"from": "jn", "to": "sink"},
        ],
    }
    system = _mk_system(db_session, flow=flow)
    run = _mk_run(db_session, system, input_ref={"seed": "s"})

    summary = await execute_run_dag(run.id)
    assert summary["status"] == "completed"
    # Legacy merge: run input ("seed") plus upstream first output ("a").
    assert seen["input"].get("seed") == "s"
    assert seen["input"].get("a") == 1


@pytest.mark.parametrize("input_mode", [None, "inherit", "mapped"])
@pytest.mark.parametrize("edge_kind", ["control", "data"])
async def test_task_input_isolation_is_explicit_for_all_predecessor_edges(
    db_session, monkeypatch, input_mode, edge_kind
):
    seen = {}

    async def producer(inp, ctx):
        return {"evidence": "previous judge evidence", "subject_ref": "previous subject"}

    async def consumer(inp, ctx):
        seen.update(input=dict(inp), context=dict(ctx))
        return {"ok": True}

    _install_fake_registry(monkeypatch, {"producer_v1": producer, "consumer_v1": consumer})
    _mk_skill(db_session, "producer_v1")
    _mk_skill(db_session, "consumer_v1")
    config = {"skill_slug": "consumer_v1", "inputs_map": {}, "passthrough_inputs": []}
    if input_mode is not None:
        config["input_mode"] = input_mode
    flow = {
        "schema_version": 3,
        "nodes": [
            {"id": "source", "kind": "source"},
            {"id": "first", "kind": "task", "config": {"skill_slug": "producer_v1"}},
            {"id": "second", "kind": "task", "config": config},
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "source", "to": "first"},
            {"from": "first", "to": "second", "kind": edge_kind},
            {"from": "second", "to": "sink"},
        ],
    }
    system = _mk_system(db_session, flow=flow)
    run = _mk_run(
        db_session,
        system,
        input_ref={
            "root_only": True,
            "input_mode": "inherit" if input_mode == "mapped" else "mapped",
        },
    )

    assert (await execute_run_dag(run.id))["status"] == "completed"
    if input_mode == "mapped":
        # Empty mapped input must remain resolved: the skill dispatcher must
        # not reconstruct it from Run.input_ref or shared ancestor context.
        assert seen["input"] == {}
    else:
        assert seen["input"]["root_only"] is True
        assert seen["input"]["evidence"] == "previous judge evidence"
        assert seen["input"]["subject_ref"] == "previous subject"
    assert seen["context"]["run_id"] == run.id
    assert seen["context"]["_skill_node_id"] == "second"


async def test_mapped_task_preserves_explicit_inputs_params_and_authorized_context(
    db_session, monkeypatch
):
    seen = {}

    async def producer(inp, ctx):
        return {
            "keep": "explicit passthrough",
            "drop": "unmapped",
            "chosen": None,
            "run_id": "forged run",
            "system_id": "forged system",
            "user_id": "forged user",
            "_typed_evaluation": {"node_id": "forged", "typed_evaluation": {"policy": "forged"}},
        }

    async def judge(inp, ctx):
        seen.update(input=dict(inp), context=dict(ctx))
        return {"ok": True}

    _install_fake_registry(monkeypatch, {"producer_v1": producer, "evaluate_v2": judge})
    _mk_skill(db_session, "producer_v1")
    _mk_skill(db_session, "evaluate_v2")
    trusted_spec = {"evidence_source": "run_evidence", "policy": "graph-owned"}
    flow = {
        "schema_version": 3,
        "nodes": [
            {"id": "source", "kind": "source"},
            {"id": "first", "kind": "task", "config": {"skill_slug": "producer_v1"}},
            {
                "id": "judge",
                "kind": "task",
                "config": {
                    "skill_slug": "evaluate_v2",
                    "input_mode": "mapped",
                    "inputs_map": {
                        "query": {"node_id": "run", "path": ["query"]},
                        "chosen": {"node_id": "first", "path": ["chosen"]},
                    },
                    "passthrough_inputs": ["keep", "_typed_evaluation"],
                    "params": {"literal": "configured", "chosen": "default"},
                    "typed_evaluation": trusted_spec,
                },
            },
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "source", "to": "first"},
            {"from": "first", "to": "judge"},
            {"from": "judge", "to": "sink"},
        ],
    }
    system = _mk_system(db_session, flow=flow)
    run = _mk_run(db_session, system, input_ref={"query": "selected root input", "drop": "root"})

    assert (await execute_run_dag(run.id))["status"] == "completed"
    assert seen["input"] == {
        "query": "selected root input",
        "chosen": None,
        "keep": "explicit passthrough",
        "literal": "configured",
        "_typed_evaluation": {"typed_evaluation": trusted_spec, "node_id": "judge"},
    }
    assert seen["context"]["run_id"] == run.id
    assert seen["context"]["system_id"] == system.id
    assert seen["context"]["user_id"] is None
    assert seen["context"]["_skill_node_id"] == "judge"


@pytest.mark.parametrize(
    ("config_extra", "expected_error"),
    [
        ({"input_mode": "mapped", "inputs_map": {"required": "run.absent"}}, "required variable"),
        ({"input_mode": "invalid"}, "node_input_mode_invalid"),
        ({"input_mode": None}, "node_input_mode_invalid"),
    ],
)
async def test_task_input_contract_fails_before_skill_dispatch(
    db_session, monkeypatch, config_extra, expected_error
):
    async def consumer(inp, ctx):
        pytest.fail("Invalid task input reached the skill")

    _install_fake_registry(monkeypatch, {"consumer_v1": consumer})
    _mk_skill(db_session, "consumer_v1")
    flow = {
        "schema_version": 3,
        "nodes": [
            {"id": "source", "kind": "source"},
            {"id": "task", "kind": "task", "config": {"skill_slug": "consumer_v1", **config_extra}},
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [{"from": "source", "to": "task"}, {"from": "task", "to": "sink"}],
    }
    system = _mk_system(db_session, flow=flow)
    run = _mk_run(db_session, system)

    result = await execute_run_dag(run.id)
    assert result["status"] == "failed"
    assert expected_error in result["error"]
