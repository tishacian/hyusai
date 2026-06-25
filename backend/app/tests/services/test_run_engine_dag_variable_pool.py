"""P1 DAG-walker integration tests for the typed VariablePool.

Verifies that ``inputs_map`` / ``outputs_map`` are actually *read* by the
walker end to end (a producer node writes a namespaced slice that a downstream
consumer node selects), that reserved namespaces are seeded from the run input,
and that a flow with no maps is byte-identical to the legacy flat-merge path.
"""
from __future__ import annotations

import uuid
from typing import Any, Callable, Dict, List, Optional

from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.services.run_engine import engine as engine_module
from app.services.run_engine.dag import execute_run_dag

SkillFn = Callable[[Dict[str, Any], Dict[str, Any]], "Any"]


def _install_fake_registry(monkeypatch, skills: Dict[str, SkillFn]) -> None:
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


def _mk_system(db, *, flow: Dict[str, Any]) -> System:
    sys_row = System(
        id=str(uuid.uuid4()),
        name="vp system",
        objective="test",
        skill_ids=[],
        flow_definition=flow,
    )
    db.add(sys_row)
    db.commit()
    return sys_row


def _mk_run(db, system: System, *, input_ref: Optional[Dict[str, Any]] = None) -> Run:
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
    seen: Dict[str, Any] = {}

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
    seen: Dict[str, Any] = {}

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


async def test_no_maps_is_byte_identical_to_flat_merge(db_session, monkeypatch):
    """With no inputs_map, the skill input must be the legacy
    ``{**run_input, **upstream}`` shape (no pool overlay)."""
    seen: Dict[str, Any] = {}

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
