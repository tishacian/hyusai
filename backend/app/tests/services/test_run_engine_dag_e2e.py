"""End-to-end tests for the DAG walker (`execute_run_dag`) — Vague D / D6.

The sibling ``test_run_engine_dag_graph.py`` only covers graph parsing,
and the smoke performed at C11 validated HTTP routes + 401. These tests
finally exercise the *runtime* behaviour the frontend relies on:

* Sequential ``task → task → task`` parity with ``execute_run``.
* ``fork → [task, task] → join`` both branches execute before the join.
* ``decision`` selects the matching branch; the others are recorded as
  inactive and downstream nodes fed only by dead edges are short-circuited.
* ``retry`` retries a failing skill until it succeeds and persists one
  ``SkillInvocation`` per attempt.
* ``loop`` iterates over a context list, producing N invocations.
* ``hitl`` pauses the run; ``resume_run_dag`` with an *accepted* /
  *rejected* Decision resumes cleanly with the right outcome.
* ``subflow`` inlines the target System's skill sequence in the parent
  run.

The tests stub the skills registry with deterministic callables so the
walker's control-flow is exercised without hitting LLMs or Qdrant. Every
assertion targets observable state (Run row, SkillInvocation ledger,
checkpoints) — the same surfaces the cockpit consumes.
"""
from __future__ import annotations

import uuid
from typing import Any, Callable, Dict, List, Optional

import pytest

from app.api.v1.endpoints.flow_runner import _run_row as _runner_run_row
from app.models.decision import Decision
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.workspace import Workspace
from app.services.flow_contracts import compile_execution_contract
from app.services.run_engine import engine as engine_module
from app.services.run_engine.dag import execute_run_dag, resume_run_dag
from app.services.run_engine.execution_contract import canonical_flow_sha256
from app.services.systems import flow_ingress, flow_publication

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
SkillFn = Callable[[Dict[str, Any], Dict[str, Any]], "Any"]


def _install_fake_registry(monkeypatch: pytest.MonkeyPatch, skills: Dict[str, SkillFn]) -> None:
    """Patch ``resolve_skill`` so the walker calls our deterministic stubs.

    The walker imports ``resolve_skill`` by name at the top of
    ``engine.py``; we patch the re-bound reference there, which is the
    one actually invoked inside ``_execute_task_node``.
    """

    def _resolve(slug: str) -> SkillFn:
        fn = skills.get(slug)
        if fn is None:
            raise NotImplementedError(f"fake registry has no {slug!r}")
        return fn

    monkeypatch.setattr(engine_module, "resolve_skill", _resolve)


def _mk_skill(db, slug: str, *, unit_price: float = 0.0) -> Skill:
    """Create a Skill row so the walker can price invocations."""
    row = Skill(
        id=str(uuid.uuid4()),
        slug=slug,
        version="v1",
        name=slug,
        description=f"test skill {slug}",
        input_schema={},
        output_schema={},
        pricing={"unit_price": unit_price},
        execution={"mode": "sync", "timeout_ms": 1000, "retryable": True, "idempotent": True},
        certification_level="basic",
    )
    db.add(row)
    db.commit()
    return row


def _mk_system(
    db,
    *,
    flow: Dict[str, Any],
    skill_slugs: Optional[List[str]] = None,
) -> System:
    """Create a System row with the given v2 flow and optional skill ids."""
    if skill_slugs is None:
        # Executable flow slugs are part of the authoritative System binding.
        # Keep fixtures honest by deriving the explicit binding from the graph
        # they exercise; production never performs this implicit backfill.
        skill_slugs = [
            str((node.get("config") or {}).get("skill_slug"))
            for node in (flow.get("nodes") or [])
            if node.get("kind") in {"task", "retry", "loop"}
            and (node.get("config") or {}).get("skill_slug")
        ]
    skill_ids: List[str] = []
    if skill_slugs:
        rows = db.query(Skill).filter(Skill.slug.in_(skill_slugs)).all()
        skill_ids = [r.id for r in rows]
    sys_row = System(
        id=str(uuid.uuid4()),
        name="test system",
        objective="test",
        skill_ids=skill_ids,
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


def _checkpoint_kinds(run: Run) -> List[str]:
    return [cp.get("kind") for cp in (run.checkpoints or [])]


# ---------------------------------------------------------------------------
# 1 — Sequential task → task → task
# ---------------------------------------------------------------------------
async def test_sequential_tasks_thread_outputs(db_session, monkeypatch):
    """Three task nodes chained linearly: each skill receives the prior
    output, and the final Run.output_ref reflects the last task."""

    async def first(inp, ctx):
        return {"stage": "one", "n": 1}

    async def second(inp, ctx):
        return {"stage": "two", "n": (inp.get("n") or 0) + 1}

    async def third(inp, ctx):
        return {"stage": "three", "n": (inp.get("n") or 0) + 1}

    _install_fake_registry(monkeypatch, {"one_v1": first, "two_v1": second, "three_v1": third})

    for slug in ("one_v1", "two_v1", "three_v1"):
        _mk_skill(db_session, slug)

    # We call `execute_run_dag` directly so we don't need a control
    # node to trick `should_use_dag` into picking the DAG walker.
    flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "src", "kind": "source"},
            {"id": "n1", "kind": "task", "config": {"skill_slug": "one_v1"}},
            {"id": "n2", "kind": "task", "config": {"skill_slug": "two_v1"}},
            {"id": "n3", "kind": "task", "config": {"skill_slug": "three_v1"}},
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "src", "to": "n1"},
            {"from": "n1", "to": "n2"},
            {"from": "n2", "to": "n3"},
            {"from": "n3", "to": "sink"},
        ],
    }
    system = _mk_system(db_session, flow=flow)
    run = _mk_run(db_session, system, input_ref={"seed": True})

    summary = await execute_run_dag(run.id)
    assert summary["status"] == "completed"

    db_session.expire_all()
    run = db_session.query(Run).filter(Run.id == run.id).first()
    assert run.status == "completed"
    # Last task wrote {"stage": "three", "n": 3}; sink collects it.
    assert run.output_ref.get("stage") == "three"
    assert run.output_ref.get("n") == 3

    invocations = (
        db_session.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run.id)
        .order_by(SkillInvocation.started_at.asc())
        .all()
    )
    assert [i.skill_slug for i in invocations] == ["one_v1", "two_v1", "three_v1"]
    assert all(i.status == "completed" for i in invocations)

    assert "run_start" in _checkpoint_kinds(run)
    assert "run_end" in _checkpoint_kinds(run)


@pytest.mark.parametrize(
    ("value", "schema"),
    [
        (False, {"type": "boolean"}),
        (0, {"type": "integer"}),
        ("", {"type": "string"}),
    ],
)
async def test_falsy_scalar_output_survives_runtime_persistence_and_runner_projection(
    db_session,
    monkeypatch,
    value,
    schema,
):
    async def scalar(_inp, _ctx):
        return value

    _install_fake_registry(monkeypatch, {"scalar_v1": scalar})
    _mk_skill(db_session, "scalar_v1")
    flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "src", "kind": "source"},
            {"id": "scalar", "kind": "task", "config": {"skill_slug": "scalar_v1"}},
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "src", "to": "scalar"},
            {"from": "scalar", "to": "sink"},
        ],
    }
    system = _mk_system(db_session, flow=flow)
    run = _mk_run(db_session, system, input_ref={"query": "scalar"})
    run.flow_snapshot = flow
    run.execution_contract = {
        "validation_mode": "enforce",
        "nodes": {"scalar": {"output_schema": schema}},
        "outputs": [{"node_id": "sink", "schema": schema}],
    }
    db_session.commit()

    summary = await execute_run_dag(run.id)
    assert summary["status"] == "completed"
    db_session.expire_all()
    persisted = db_session.query(Run).filter(Run.id == run.id).one()
    invocation = (
        db_session.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run.id)
        .one()
    )
    assert type(invocation.output_ref) is type(value)
    assert invocation.output_ref == value
    assert type(persisted.output_ref) is type(value)
    assert persisted.output_ref == value
    projected = _runner_run_row(persisted)["output_ref"]
    assert type(projected) is type(value)
    assert projected == value


@pytest.mark.parametrize(
    ("execution_surface", "selected_source", "selected_kind", "expected_call"),
    [
        ("published_manual", "manual.input", "manual", "manual"),
        ("draft_test", "http.input", "http", "http"),
        ("builder_preview", "manual.input", "manual", "manual"),
        ("node_preview", "http.input", "http", "http"),
        ("golden_preview", "manual.input", "manual", "manual"),
    ],
)
async def test_normalized_ingress_executes_only_its_frozen_source_branch(
    db_session,
    monkeypatch,
    execution_surface,
    selected_source,
    selected_kind,
    expected_call,
):
    calls: list[str] = []

    async def manual(_inp, _ctx):
        calls.append("manual")
        return {"adapter": "manual"}

    async def webhook(_inp, _ctx):
        calls.append("http")
        return {"adapter": "http"}

    _install_fake_registry(
        monkeypatch,
        {"manual_v1": manual, "webhook_v1": webhook},
    )
    _mk_skill(db_session, "manual_v1")
    _mk_skill(db_session, "webhook_v1")
    flow = {
        "schema_version": 2,
        "nodes": [
            {
                "id": "manual.input",
                "kind": "source",
                "config": {"ingress_kind": "manual"},
            },
            {
                "id": "http.input",
                "kind": "source",
                "config": {"ingress_kind": "http"},
            },
            {
                "id": "manual.task",
                "kind": "task",
                "config": {"skill_slug": "manual_v1"},
            },
            {
                "id": "http.task",
                "kind": "task",
                "config": {"skill_slug": "webhook_v1"},
            },
            {"id": "manual.sink", "kind": "sink"},
            {"id": "http.sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "manual.input", "to": "manual.task"},
            {"from": "manual.task", "to": "manual.sink"},
            {"from": "http.input", "to": "http.task"},
            {"from": "http.task", "to": "http.sink"},
        ],
    }
    system = _mk_system(db_session, flow=flow)
    run = _mk_run(db_session, system, input_ref={"query": "selected"})
    run.flow_snapshot = flow
    run.execution_surface = execution_surface
    run.input_ref = {
        "query": "selected",
        "execution": {
            "execution_surface": execution_surface,
            "published_flow_version_id": None,
            "ingress_id": selected_source,
            "ingress_selection_version": 1,
        },
        "_ingress": {
            "ingress_id": selected_source,
            "source_node_id": selected_source,
            "kind": selected_kind,
            "adapter": {"surface": "test"},
        },
    }
    run.execution_contract = {
        "validation_mode": "observe",
        "ingresses": [
            {
                "ingress_id": "manual.input",
                "source_node_id": "manual.input",
                "kind": "manual",
            },
            {
                "ingress_id": "http.input",
                "source_node_id": "http.input",
                "kind": "http",
            },
        ],
        "nodes": {},
        "outputs": [],
    }
    db_session.commit()

    summary = await execute_run_dag(run.id)
    assert summary["status"] == "completed"
    assert calls == [expected_call]
    db_session.expire_all()
    persisted = db_session.query(Run).filter(Run.id == run.id).one()
    assert persisted.output_ref == {"adapter": expected_call}
    if execution_surface.endswith("_preview"):
        assert persisted.flow_version_id is None
        assert persisted.published_flow_version_id is None
    start = next(
        checkpoint
        for checkpoint in persisted.checkpoints
        if checkpoint.get("kind") == "run_start"
    )
    assert start["ingress_source_node_id"] == selected_source
    assert start["inactive_ingress_source_node_ids"] == [
        "http.input" if selected_source == "manual.input" else "manual.input"
    ]


@pytest.mark.parametrize(
    ("validation_mode", "expected_status", "expected_disposition"),
    [
        ("enforce", "failed", "failed"),
        ("observe", "completed", "observed"),
    ],
)
async def test_frozen_output_schema_is_enforced_or_observed_by_runtime(
    db_session,
    monkeypatch,
    validation_mode,
    expected_status,
    expected_disposition,
):
    async def invalid_output(_inp, _ctx):
        return {"answer": 42}

    _install_fake_registry(monkeypatch, {"typed_v1": invalid_output})
    _mk_skill(db_session, "typed_v1")
    flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "src", "kind": "source"},
            {"id": "typed", "kind": "task", "config": {"skill_slug": "typed_v1"}},
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "src", "to": "typed"},
            {"from": "typed", "to": "sink"},
        ],
    }
    system = _mk_system(db_session, flow=flow)
    run = _mk_run(db_session, system, input_ref={"query": "hello"})
    run.flow_snapshot = flow
    run.execution_contract = {
        "validation_mode": validation_mode,
        "nodes": {
            "typed": {
                "output_schema": {
                    "type": "object",
                    "required": ["answer"],
                    "properties": {"answer": {"type": "string"}},
                }
            }
        },
        "outputs": [],
    }
    db_session.commit()

    summary = await execute_run_dag(run.id)
    assert summary["status"] == expected_status
    db_session.expire_all()
    persisted = db_session.query(Run).filter(Run.id == run.id).one()
    assert persisted.status == expected_status
    violation = next(
        cp
        for cp in persisted.checkpoints
        if cp.get("kind") == "execution_contract_violation"
    )
    assert violation["code"] == "node_output_invalid"
    assert violation["node_id"] == "typed"
    assert violation["disposition"] == expected_disposition
    assert "42" not in violation["message"]
    assert not ({"payload", "value", "instance"} & set(violation))
    if validation_mode == "enforce":
        assert persisted.output_ref == {}


# ---------------------------------------------------------------------------
# 2 — fork → [task, task] → join
# ---------------------------------------------------------------------------
async def test_fork_join_executes_both_branches(db_session, monkeypatch):
    """Fork fans the data out; join waits for both branches and merges."""

    async def left(inp, ctx):
        return {"left": "L"}

    async def right(inp, ctx):
        return {"right": "R"}

    _install_fake_registry(monkeypatch, {"left_v1": left, "right_v1": right})
    _mk_skill(db_session, "left_v1")
    _mk_skill(db_session, "right_v1")

    flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "src", "kind": "source"},
            {"id": "fk", "kind": "fork"},
            {"id": "nl", "kind": "task", "config": {"skill_slug": "left_v1"}},
            {"id": "nr", "kind": "task", "config": {"skill_slug": "right_v1"}},
            {"id": "jn", "kind": "join", "config": {"strategy": "all"}},
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "src", "to": "fk"},
            {"from": "fk", "to": "nl"},
            {"from": "fk", "to": "nr"},
            {"from": "nl", "to": "jn"},
            {"from": "nr", "to": "jn"},
            {"from": "jn", "to": "sink"},
        ],
    }
    system = _mk_system(db_session, flow=flow)
    run = _mk_run(db_session, system)

    summary = await execute_run_dag(run.id)
    assert summary["status"] == "completed"

    db_session.expire_all()
    run = db_session.query(Run).filter(Run.id == run.id).first()
    # Both branch outputs merged by the join, forwarded to the sink.
    assert run.output_ref.get("left") == "L"
    assert run.output_ref.get("right") == "R"

    invocations = db_session.query(SkillInvocation).filter(SkillInvocation.run_id == run.id).all()
    assert {i.skill_slug for i in invocations} == {"left_v1", "right_v1"}
    assert all(i.status == "completed" for i in invocations)


# ---------------------------------------------------------------------------
# 3 — decision branch selection
# ---------------------------------------------------------------------------
async def test_decision_activates_matching_branch_only(db_session, monkeypatch):
    """Decision picks the true branch; the false branch's task never
    runs and the inactive branch is recorded on the node_end checkpoint.
    """
    calls: List[str] = []

    async def high(inp, ctx):
        calls.append("high")
        return {"path": "high"}

    async def low(inp, ctx):
        calls.append("low")
        return {"path": "low"}

    _install_fake_registry(monkeypatch, {"high_v1": high, "low_v1": low})
    _mk_skill(db_session, "high_v1")
    _mk_skill(db_session, "low_v1")

    flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "src", "kind": "source"},
            {
                "id": "dec",
                "kind": "decision",
                "config": {
                    "branches": [
                        {"label": "hi", "condition": "score > 0.5"},
                        {"label": "lo", "condition": "score <= 0.5"},
                    ]
                },
            },
            {"id": "th", "kind": "task", "config": {"skill_slug": "high_v1"}},
            {"id": "tl", "kind": "task", "config": {"skill_slug": "low_v1"}},
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "src", "to": "dec"},
            {"from": "dec", "to": "th", "kind": "branch", "branch_label": "hi"},
            {"from": "dec", "to": "tl", "kind": "branch", "branch_label": "lo"},
            {"from": "th", "to": "sink"},
            {"from": "tl", "to": "sink"},
        ],
    }
    system = _mk_system(db_session, flow=flow)
    run = _mk_run(db_session, system, input_ref={"score": 0.9})

    summary = await execute_run_dag(run.id)
    assert summary["status"] == "completed"

    # Only the hi branch's skill actually fired.
    assert calls == ["high"]

    db_session.expire_all()
    run = db_session.query(Run).filter(Run.id == run.id).first()
    assert run.output_ref.get("path") == "high"

    invocations = db_session.query(SkillInvocation).filter(SkillInvocation.run_id == run.id).all()
    assert {i.skill_slug for i in invocations} == {"high_v1"}

    # Decision's node_end records the chosen branch.
    decisions_cp = [
        cp
        for cp in (run.checkpoints or [])
        if cp.get("kind") == "node_end" and cp.get("node_id") == "dec"
    ]
    assert decisions_cp, "decision node_end checkpoint missing"
    assert decisions_cp[0].get("chosen_branch") == "hi"


async def test_decision_uses_explicit_default_and_records_resolution(db_session):
    flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "src", "kind": "source"},
            {
                "id": "dec",
                "kind": "decision",
                "config": {
                    "branches": [
                        {"label": "yes", "condition": "score > 0.8"},
                        {"label": "no", "condition": "score < 0"},
                    ],
                    "default_branch": "no",
                },
            },
            {"id": "yes_sink", "kind": "sink"},
            {"id": "no_sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "src", "to": "dec"},
            {"from": "dec", "to": "yes_sink", "kind": "branch", "branch_label": "yes"},
            {"from": "dec", "to": "no_sink", "kind": "branch", "branch_label": "no"},
        ],
    }
    system = _mk_system(db_session, flow=flow)
    run = _mk_run(db_session, system, input_ref={"score": 0.4})

    summary = await execute_run_dag(run.id)

    assert summary["status"] == "completed"
    db_session.expire_all()
    persisted = db_session.query(Run).filter(Run.id == run.id).one()
    resolution = next(
        cp for cp in persisted.checkpoints if cp.get("kind") == "decision_resolution"
    )
    assert resolution["resolution"] == "defaulted"
    assert resolution["chosen_branch"] == "no"
    assert resolution["matching_routes"] == 1


@pytest.mark.parametrize(
    ("branches", "default_branch", "edge_label", "expected_error", "expected_resolution"),
    [
        (
            [{"label": "yes", "condition": "score > 0.8"}],
            None,
            "yes",
            "decision_no_match:dec",
            "no_match",
        ),
        (
            [{"label": "yes", "condition": "True"}],
            None,
            "no",
            "decision_branch_unroutable:dec",
            "unroutable",
        ),
    ],
)
async def test_decision_fails_closed_without_a_routable_choice(
    db_session,
    branches,
    default_branch,
    edge_label,
    expected_error,
    expected_resolution,
):
    config: Dict[str, Any] = {"branches": branches}
    if default_branch is not None:
        config["default_branch"] = default_branch
    flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "src", "kind": "source"},
            {"id": "dec", "kind": "decision", "config": config},
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "src", "to": "dec"},
            {
                "from": "dec",
                "to": "sink",
                "kind": "branch",
                "branch_label": edge_label,
            },
        ],
    }
    system = _mk_system(db_session, flow=flow)
    run = _mk_run(db_session, system, input_ref={"score": 0.4})

    summary = await execute_run_dag(run.id)

    assert summary == {"id": run.id, "status": "failed", "error": expected_error}
    db_session.expire_all()
    persisted = db_session.query(Run).filter(Run.id == run.id).one()
    assert persisted.status == "failed"
    assert persisted.error == expected_error
    assert persisted.output_ref == {}
    resolution = next(
        cp for cp in persisted.checkpoints if cp.get("kind") == "decision_resolution"
    )
    assert resolution["resolution"] == expected_resolution
    assert resolution["error"] == expected_error


async def test_decision_validates_every_condition_before_first_match(db_session):
    flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "src", "kind": "source"},
            {
                "id": "dec",
                "kind": "decision",
                "config": {
                    "branches": [
                        {"label": "yes", "condition": "True"},
                        {"label": "unsafe", "condition": "len(secret) > 0"},
                    ]
                },
            },
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "src", "to": "dec"},
            {"from": "dec", "to": "sink", "kind": "branch", "branch_label": "yes"},
        ],
    }
    system = _mk_system(db_session, flow=flow)
    run = _mk_run(db_session, system, input_ref={"secret": "must-not-leak"})

    summary = await execute_run_dag(run.id)

    assert summary["status"] == "failed"
    assert summary["error"] == "decision_condition_error:dec"
    db_session.expire_all()
    persisted = db_session.query(Run).filter(Run.id == run.id).one()
    resolution = next(
        cp for cp in persisted.checkpoints if cp.get("kind") == "decision_resolution"
    )
    assert resolution["resolution"] == "error"
    assert resolution["condition_error"] == {
        "code": "condition_unsupported",
        "message": "unsupported expression node Call",
        "branch_index": 1,
        "branch_label": "unsafe",
    }
    assert "must-not-leak" not in str(resolution)


async def test_dead_decision_lane_stays_dead_through_multiple_nodes(db_session, monkeypatch):
    calls: List[str] = []

    async def active(inp, ctx):
        calls.append("active")
        return {"path": "active"}

    async def dead_one(inp, ctx):
        calls.append("dead_one")
        return {"path": "dead_one"}

    async def dead_two(inp, ctx):
        calls.append("dead_two")
        return {"path": "dead_two"}

    skills = {
        "active_v1": active,
        "dead_one_v1": dead_one,
        "dead_two_v1": dead_two,
    }
    _install_fake_registry(monkeypatch, skills)
    for slug in skills:
        _mk_skill(db_session, slug)

    flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "src", "kind": "source"},
            {
                "id": "dec",
                "kind": "decision",
                "config": {
                    "branches": [
                        {"label": "live", "condition": "True"},
                        {"label": "dead", "condition": "False"},
                    ]
                },
            },
            {"id": "live", "kind": "task", "config": {"skill_slug": "active_v1"}},
            {"id": "dead1", "kind": "task", "config": {"skill_slug": "dead_one_v1"}},
            {"id": "dead2", "kind": "task", "config": {"skill_slug": "dead_two_v1"}},
            {"id": "join", "kind": "join", "config": {"strategy": "all"}},
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "src", "to": "dec"},
            {"from": "dec", "to": "live", "kind": "branch", "branch_label": "live"},
            {"from": "dec", "to": "dead1", "kind": "branch", "branch_label": "dead"},
            {"from": "dead1", "to": "dead2"},
            {"from": "dead2", "to": "join"},
            {"from": "live", "to": "join"},
            {"from": "join", "to": "sink"},
        ],
    }
    system = _mk_system(db_session, flow=flow)
    run = _mk_run(db_session, system)

    summary = await execute_run_dag(run.id)

    assert summary["status"] == "completed"
    assert calls == ["active"]
    db_session.expire_all()
    persisted = db_session.query(Run).filter(Run.id == run.id).one()
    assert persisted.output_ref.get("path") == "active"
    skipped = {
        cp.get("node_id")
        for cp in persisted.checkpoints
        if cp.get("kind") == "node_end" and cp.get("skipped_reason") == "all_inputs_dead"
    }
    assert skipped == {"dead1", "dead2"}


# ---------------------------------------------------------------------------
# 4 — retry: two failures then success
# ---------------------------------------------------------------------------
async def test_retry_persists_one_invocation_per_attempt(db_session, monkeypatch):
    """A skill that fails twice then succeeds should produce 3
    SkillInvocation rows and a completed run."""
    attempts = {"n": 0}

    async def flaky(inp, ctx):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError(f"attempt {attempts['n']} failed")
        return {"ok": True, "attempts": attempts["n"]}

    _install_fake_registry(monkeypatch, {"flaky_v1": flaky})
    _mk_skill(db_session, "flaky_v1")

    flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "src", "kind": "source"},
            {
                "id": "r",
                "kind": "retry",
                "config": {
                    "skill_slug": "flaky_v1",
                    "max_attempts": 3,
                    "backoff_ms": 0,
                },
            },
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "src", "to": "r"},
            {"from": "r", "to": "sink"},
        ],
    }
    system = _mk_system(db_session, flow=flow)
    run = _mk_run(db_session, system)

    summary = await execute_run_dag(run.id)
    assert summary["status"] == "completed"

    db_session.expire_all()
    invocations = (
        db_session.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run.id)
        .order_by(SkillInvocation.started_at.asc())
        .all()
    )
    assert len(invocations) == 3, "retry must persist one invocation per attempt"
    assert [i.status for i in invocations] == ["failed", "failed", "completed"]


# ---------------------------------------------------------------------------
# 5 — loop over a context list
# ---------------------------------------------------------------------------
async def test_loop_produces_one_invocation_per_item(db_session, monkeypatch):
    """Three items in ctx.items → three invocations of the bound skill."""

    async def per_item(inp, ctx):
        idx = ctx.get("_loop_index")
        item = ctx.get("_loop_item")
        return {"idx": idx, "upper": str(item).upper() if item is not None else None}

    _install_fake_registry(monkeypatch, {"item_v1": per_item})
    _mk_skill(db_session, "item_v1")

    flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "src", "kind": "source"},
            {
                "id": "lp",
                "kind": "loop",
                "config": {
                    "skill_slug": "item_v1",
                    "iterator": "items",
                    "max_iterations": 10,
                },
            },
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "src", "to": "lp"},
            {"from": "lp", "to": "sink"},
        ],
    }
    system = _mk_system(db_session, flow=flow)
    run = _mk_run(db_session, system, input_ref={"items": ["a", "b", "c"]})

    summary = await execute_run_dag(run.id)
    assert summary["status"] == "completed"

    db_session.expire_all()
    invocations = (
        db_session.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run.id)
        .order_by(SkillInvocation.started_at.asc())
        .all()
    )
    assert len(invocations) == 3
    assert [i.status for i in invocations] == ["completed"] * 3

    run = db_session.query(Run).filter(Run.id == run.id).first()
    assert run.output_ref.get("count") == 3


async def test_retry_strict_contract_validates_raw_output_before_adapting(
    db_session,
    monkeypatch,
):
    async def typed_retry(_inp, _ctx):
        return {"ok": True}

    _install_fake_registry(monkeypatch, {"typed_retry_v1": typed_retry})
    skill = _mk_skill(db_session, "typed_retry_v1")
    skill.output_schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    db_session.commit()
    flow = {
        "schema_version": 3,
        "io_mode": "strict",
        "nodes": [
            {"id": "src", "kind": "source"},
            {
                "id": "retry",
                "kind": "retry",
                "config": {
                    "skill_slug": skill.slug,
                    "max_attempts": 2,
                    "backoff_ms": 0,
                },
            },
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "src", "to": "retry"},
            {"from": "retry", "to": "sink"},
        ],
    }
    system = _mk_system(db_session, flow=flow)
    run = _mk_run(db_session, system)
    run.flow_snapshot = flow
    run.execution_contract = compile_execution_contract(
        db_session,
        flow=flow,
        workspace_id=None,
        runtime_mode="dag_strict",
        allowed_skill_ids={skill.id},
    )
    db_session.commit()

    summary = await execute_run_dag(run.id)

    assert summary["status"] == "completed"
    db_session.expire_all()
    persisted = db_session.query(Run).filter(Run.id == run.id).one()
    assert persisted.output_ref == {
        "ok": True,
        "_retry_attempts": 1,
        "_status": "completed",
    }
    assert persisted.execution_contract["nodes"]["retry"]["output_adapter"] == "retry.v1"
    assert not any(
        checkpoint.get("kind") == "execution_contract_violation"
        for checkpoint in persisted.checkpoints
    )


async def test_loop_strict_contract_validates_raw_outputs_and_public_envelope(
    db_session,
    monkeypatch,
):
    async def typed_loop(_inp, ctx):
        return {"index": ctx["_loop_index"]}

    _install_fake_registry(monkeypatch, {"typed_loop_v1": typed_loop})
    skill = _mk_skill(db_session, "typed_loop_v1")
    skill.output_schema = {
        "type": "object",
        "properties": {"index": {"type": "integer"}},
        "required": ["index"],
        "additionalProperties": False,
    }
    db_session.commit()
    flow = {
        "schema_version": 3,
        "io_mode": "strict",
        "nodes": [
            {"id": "src", "kind": "source"},
            {
                "id": "loop",
                "kind": "loop",
                "config": {
                    "skill_slug": skill.slug,
                    "iterator": "items",
                    "max_iterations": 2,
                },
            },
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "src", "to": "loop"},
            {"from": "loop", "to": "sink"},
        ],
    }
    system = _mk_system(db_session, flow=flow)
    run = _mk_run(db_session, system, input_ref={"items": ["a", "b"]})
    run.flow_snapshot = flow
    run.execution_contract = compile_execution_contract(
        db_session,
        flow=flow,
        workspace_id=None,
        runtime_mode="dag_strict",
        allowed_skill_ids={skill.id},
    )
    db_session.commit()

    summary = await execute_run_dag(run.id)

    assert summary["status"] == "completed"
    db_session.expire_all()
    persisted = db_session.query(Run).filter(Run.id == run.id).one()
    assert persisted.output_ref == {
        "iterations": [
            {"index": 0, "status": "completed", "output": {"index": 0}},
            {"index": 1, "status": "completed", "output": {"index": 1}},
        ],
        "count": 2,
    }
    assert persisted.execution_contract["nodes"]["loop"]["output_adapter"] == "loop.v1"
    assert not any(
        checkpoint.get("kind") == "execution_contract_violation"
        for checkpoint in persisted.checkpoints
    )


@pytest.mark.parametrize("kind", ["retry", "loop"])
async def test_strict_control_node_rejects_invalid_raw_skill_output(
    db_session,
    monkeypatch,
    kind,
):
    async def invalid_typed_output(_inp, _ctx):
        return {"ok": "not-a-boolean"}

    slug = f"invalid_{kind}_v1"
    _install_fake_registry(monkeypatch, {slug: invalid_typed_output})
    skill = _mk_skill(db_session, slug)
    skill.output_schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    db_session.commit()
    config = {"skill_slug": slug}
    if kind == "retry":
        config.update({"max_attempts": 1, "backoff_ms": 0})
    else:
        config.update({"max_iterations": 1})
    flow = {
        "schema_version": 3,
        "io_mode": "strict",
        "nodes": [
            {"id": "src", "kind": "source"},
            {"id": "control", "kind": kind, "config": config},
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "src", "to": "control"},
            {"from": "control", "to": "sink"},
        ],
    }
    system = _mk_system(db_session, flow=flow)
    run = _mk_run(db_session, system)
    run.flow_snapshot = flow
    run.execution_contract = compile_execution_contract(
        db_session,
        flow=flow,
        workspace_id=None,
        runtime_mode="dag_strict",
        allowed_skill_ids={skill.id},
    )
    db_session.commit()

    summary = await execute_run_dag(run.id)

    assert summary == {
        "id": run.id,
        "status": "failed",
        "error": "execution_contract:node_invocation_output_invalid:control",
    }
    db_session.expire_all()
    persisted = db_session.query(Run).filter(Run.id == run.id).one()
    violations = [
        checkpoint
        for checkpoint in persisted.checkpoints
        if checkpoint.get("kind") == "execution_contract_violation"
    ]
    assert len(violations) == 1
    assert violations[0]["code"] == "node_invocation_output_invalid"
    assert violations[0]["node_id"] == "control"
    assert violations[0]["disposition"] == "failed"
    assert "not-a-boolean" not in str(violations[0])


# ---------------------------------------------------------------------------
# 6a — HITL: pause then resume with an accepted Decision
# ---------------------------------------------------------------------------
async def test_hitl_accept_resumes_to_completion(db_session, monkeypatch):
    """HITL node pauses the run; once we flip the Decision to
    ``accepted``, ``resume_run_dag`` walks the DAG to completion with
    ``hitl_approved`` in the ctx."""

    async def tail(inp, ctx):
        return {"approved": ctx.get("hitl_approved"), "done": True}

    _install_fake_registry(monkeypatch, {"tail_v1": tail})
    _mk_skill(db_session, "tail_v1")

    flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "src", "kind": "source"},
            {"id": "h", "kind": "hitl", "config": {"prompt": "approve?"}},
            {"id": "t", "kind": "task", "config": {"skill_slug": "tail_v1"}},
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "src", "to": "h"},
            {"from": "h", "to": "t"},
            {"from": "t", "to": "sink"},
        ],
    }
    system = _mk_system(db_session, flow=flow)
    run = _mk_run(db_session, system)

    # First pass: walker should pause at the HITL node.
    summary = await execute_run_dag(run.id)
    assert summary["status"] == "hitl_pending"
    assert summary.get("awaiting_decision")

    db_session.expire_all()
    run = db_session.query(Run).filter(Run.id == run.id).first()
    assert run.status == "hitl_pending"
    assert "hitl_pause" in _checkpoint_kinds(run)

    # Flip the Decision to accepted (frontend does this via
    # `/decisions/:id/accept`; here we bypass the endpoint to stay at
    # the engine level).
    decision_id = summary.get("awaiting_decision")
    dec = db_session.query(Decision).filter(Decision.id == decision_id).first()
    assert dec is not None
    dec.status = "accepted"
    db_session.commit()

    resumed = await resume_run_dag(run.id, decision_id=decision_id)
    assert resumed["status"] == "completed"

    db_session.expire_all()
    run = db_session.query(Run).filter(Run.id == run.id).first()
    assert run.status == "completed"
    assert run.output_ref.get("approved") is True
    assert run.output_ref.get("done") is True
    assert "hitl_resume" in _checkpoint_kinds(run)


async def test_hitl_resume_executes_immutable_flow_snapshot(db_session, monkeypatch):
    """Publishing a new System graph while paused must not change this Run."""

    async def original_tail(inp, ctx):
        return {"implementation": "snapshotted"}

    async def replacement_tail(inp, ctx):
        return {"implementation": "mutated"}

    _install_fake_registry(
        monkeypatch,
        {"original_tail_v1": original_tail, "replacement_tail_v1": replacement_tail},
    )
    _mk_skill(db_session, "original_tail_v1")
    _mk_skill(db_session, "replacement_tail_v1")
    flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "src", "kind": "source"},
            {"id": "h", "kind": "hitl", "config": {"prompt": "approve?"}},
            {
                "id": "t",
                "kind": "task",
                "config": {"skill_slug": "original_tail_v1"},
            },
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "src", "to": "h"},
            {"from": "h", "to": "t"},
            {"from": "t", "to": "sink"},
        ],
    }
    system = _mk_system(db_session, flow=flow)
    run = _mk_run(db_session, system)

    paused = await execute_run_dag(run.id)
    assert paused["status"] == "hitl_pending"
    db_session.expire_all()
    run = db_session.query(Run).filter(Run.id == run.id).one()
    assert run.flow_snapshot == flow
    flow_hash = run.input_ref["execution"]["flow_sha256"]

    replacement = {
        **flow,
        "nodes": [
            {
                **node,
                "config": {"skill_slug": "replacement_tail_v1"},
            }
            if node["id"] == "t"
            else node
            for node in flow["nodes"]
        ],
    }
    system = db_session.query(System).filter(System.id == system.id).one()
    system.flow_definition = replacement
    decision = db_session.query(Decision).filter(Decision.id == paused["awaiting_decision"]).one()
    decision.status = "accepted"
    db_session.commit()

    resumed = await resume_run_dag(run.id, decision_id=decision.id)
    assert resumed["status"] == "completed"
    db_session.expire_all()
    run = db_session.query(Run).filter(Run.id == run.id).one()
    assert run.output_ref["implementation"] == "snapshotted"
    assert run.flow_snapshot == flow
    assert run.input_ref["execution"]["flow_sha256"] == flow_hash
    invocations = db_session.query(SkillInvocation).filter(SkillInvocation.run_id == run.id).all()
    assert [item.skill_slug for item in invocations] == ["original_tail_v1"]


# ---------------------------------------------------------------------------
# 6b — HITL: pause then resume with a rejected Decision
# ---------------------------------------------------------------------------
async def test_hitl_reject_propagates_to_tail(db_session, monkeypatch):
    """A rejected HITL decision still resumes the walker (no hard stop)
    but the ``hitl_approved`` flag in ctx is False, so downstream tasks
    can branch on it."""

    async def tail(inp, ctx):
        return {"approved": bool(ctx.get("hitl_approved"))}

    _install_fake_registry(monkeypatch, {"tail_v1": tail})
    _mk_skill(db_session, "tail_v1")

    flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "src", "kind": "source"},
            {"id": "h", "kind": "hitl", "config": {"prompt": "approve?"}},
            {"id": "t", "kind": "task", "config": {"skill_slug": "tail_v1"}},
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "src", "to": "h"},
            {"from": "h", "to": "t"},
            {"from": "t", "to": "sink"},
        ],
    }
    system = _mk_system(db_session, flow=flow)
    run = _mk_run(db_session, system)

    summary = await execute_run_dag(run.id)
    assert summary["status"] == "hitl_pending"
    decision_id = summary["awaiting_decision"]

    dec = db_session.query(Decision).filter(Decision.id == decision_id).first()
    dec.status = "rejected"
    db_session.commit()

    resumed = await resume_run_dag(run.id, decision_id=decision_id)
    assert resumed["status"] == "completed"

    db_session.expire_all()
    run = db_session.query(Run).filter(Run.id == run.id).first()
    assert run.output_ref.get("approved") is False


# ---------------------------------------------------------------------------
# 7 — Subflow delegates to a real child Run (P4)
# ---------------------------------------------------------------------------
async def test_subflow_creates_child_run(db_session, monkeypatch):
    """A ``subflow`` node now creates a child ``Run(parent_run_id=parent)`` for
    the target System, executes it as its own walker (the child owns the
    SkillInvocation ledger), and merges the child output back at the subflow
    node. Provenance (parent_run_id + delegation_node_id) is preserved."""

    async def inner_a(inp, ctx):
        return {"a": "A"}

    async def inner_b(inp, ctx):
        return {"b": "B"}

    _install_fake_registry(monkeypatch, {"inner_a_v1": inner_a, "inner_b_v1": inner_b})
    _mk_skill(db_session, "inner_a_v1")
    _mk_skill(db_session, "inner_b_v1")

    # Target System — sequential skill list, no custom flow needed.
    target = _mk_system(db_session, flow={}, skill_slugs=["inner_a_v1", "inner_b_v1"])

    flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "src", "kind": "source"},
            {
                "id": "sf",
                "kind": "subflow",
                "config": {"system_id": target.id},
            },
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "src", "to": "sf"},
            {"from": "sf", "to": "sink"},
        ],
    }
    parent = _mk_system(db_session, flow=flow)
    run = _mk_run(db_session, parent)

    summary = await execute_run_dag(run.id)
    assert summary["status"] == "completed"

    db_session.expire_all()
    # The parent run carries NO target skills — they live on the child.
    parent_invocations = (
        db_session.query(SkillInvocation).filter(SkillInvocation.run_id == run.id).all()
    )
    assert [i.skill_slug for i in parent_invocations] == []

    # A child run was created, linked to the parent and the target System.
    child = (
        db_session.query(Run)
        .filter(Run.parent_run_id == run.id, Run.system_id == target.id)
        .first()
    )
    assert child is not None
    assert child.input_ref.get("_delegation", {}).get("delegation_node_id") == "sf"

    child_invocations = (
        db_session.query(SkillInvocation)
        .filter(SkillInvocation.run_id == child.id)
        .order_by(SkillInvocation.started_at.asc())
        .all()
    )
    assert [i.skill_slug for i in child_invocations] == ["inner_a_v1", "inner_b_v1"]
    assert all(i.status == "completed" for i in child_invocations)

    run = db_session.query(Run).filter(Run.id == run.id).first()
    # The subflow node stamps target id + child run id and merges child output.
    assert run.output_ref.get("subflow_system_id") == target.id
    assert run.output_ref.get("child_run_id") == child.id
    assert run.output_ref.get("b") == "B"


async def test_feature_on_subflow_child_freezes_target_publication_boundary(
    db_session,
    monkeypatch,
):
    async def inner(_inp, _ctx):
        return {"frozen": True}

    _install_fake_registry(monkeypatch, {"published_inner_v1": inner})
    skill = _mk_skill(db_session, "published_inner_v1")
    workspace = Workspace(
        id=str(uuid.uuid4()),
        slug=f"subflow-publication-{uuid.uuid4().hex[:8]}",
        name="Subflow publication",
        settings={"features": {"flow_publication_v1": True}},
    )
    target_flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "manual", "kind": "source"},
            {
                "id": "work",
                "kind": "task",
                "config": {"skill_slug": skill.slug},
            },
            {"id": "result", "kind": "sink"},
        ],
        "edges": [
            {"from": "manual", "to": "work"},
            {"from": "work", "to": "result"},
        ],
    }
    target = System(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name="Published child",
        objective="child",
        status="active",
        skill_ids=[skill.id],
        flow_definition=target_flow,
    )
    parent_flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "manual", "kind": "source"},
            {
                "id": "delegate",
                "kind": "subflow",
                "config": {
                    "system_id": target.id,
                    "subflow_ingress_kind": "manual",
                },
            },
            {"id": "result", "kind": "sink"},
        ],
        "edges": [
            {"from": "manual", "to": "delegate"},
            {"from": "delegate", "to": "result"},
        ],
    }
    parent = System(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name="Published parent",
        objective="parent",
        status="active",
        skill_ids=[],
        flow_definition=parent_flow,
    )
    db_session.add_all([workspace, target, parent])
    db_session.commit()
    for system in (target, parent):
        flow_publication.initialize_publication_state(
            db_session,
            system=system,
            workspace=workspace,
            actor="test",
        )
    db_session.commit()
    target_version_id = target.published_flow_version_id
    target_contract = db_session.get(SystemVersion, target_version_id).execution_contract
    parent_run = flow_ingress.create_published_ingress_run(
        db_session,
        system_id=parent.id,
        workspace=workspace,
        ingress_id="manual",
        kind="manual",
        payload={"query": "frozen"},
        expected_published_version_id=parent.published_flow_version_id,
        expected_flow_sha256=canonical_flow_sha256(parent_flow),
        adapter_evidence={"surface": "test"},
    )
    db_session.commit()

    summary = await execute_run_dag(parent_run.id)
    assert summary["status"] == "completed"
    db_session.expire_all()
    child = (
        db_session.query(Run)
        .filter(Run.parent_run_id == parent_run.id, Run.system_id == target.id)
        .one()
    )
    assert child.status == "completed"
    assert child.flow_snapshot == target_flow
    assert child.flow_version_id == target_version_id
    assert child.published_flow_version_id == target_version_id
    assert child.flow_sha256 == canonical_flow_sha256(target_flow)
    assert child.execution_contract == target_contract
    assert child.execution_surface == "published_manual"
    assert child.input_ref["_ingress"]["source_node_id"] == "manual"


# ---------------------------------------------------------------------------
# 8 — Subflow whose child contains a HITL is resume-aware (P4 follow-up)
# ---------------------------------------------------------------------------
async def test_subflow_child_hitl_resumes_without_duplicate_child(db_session, monkeypatch):
    """A subflow whose *child* run pauses for HITL must, on parent resume,
    drive that SAME child to completion — never spawn a second child Run.

    This pins the P4 follow-up: the child run id is recorded in the parent
    ``WalkerState`` and survives the pause, so ``_run_subflow`` reuses it on
    re-entry instead of re-delegating from scratch.
    """

    async def child_tail(inp, ctx):
        return {"child_done": True, "approved": ctx.get("hitl_approved")}

    _install_fake_registry(monkeypatch, {"child_tail_v1": child_tail})
    _mk_skill(db_session, "child_tail_v1")

    # Child System owns a HITL gate before its tail task. The ``hitl`` control
    # node routes the child to the DAG walker (so it can pause/resume).
    child_flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "csrc", "kind": "source"},
            {"id": "ch", "kind": "hitl", "config": {"prompt": "child approve?"}},
            {"id": "ct", "kind": "task", "config": {"skill_slug": "child_tail_v1"}},
            {"id": "csink", "kind": "sink"},
        ],
        "edges": [
            {"from": "csrc", "to": "ch"},
            {"from": "ch", "to": "ct"},
            {"from": "ct", "to": "csink"},
        ],
    }
    target = _mk_system(db_session, flow=child_flow)

    parent_flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "src", "kind": "source"},
            {"id": "sf", "kind": "subflow", "config": {"system_id": target.id}},
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "src", "to": "sf"},
            {"from": "sf", "to": "sink"},
        ],
    }
    parent = _mk_system(db_session, flow=parent_flow)
    run = _mk_run(db_session, parent)

    # First pass: child pauses at its HITL → the parent pause is surfaced.
    summary = await execute_run_dag(run.id)
    assert summary["status"] == "hitl_pending"
    child_decision_id = summary.get("awaiting_decision")
    assert child_decision_id

    db_session.expire_all()
    children = db_session.query(Run).filter(Run.parent_run_id == run.id).all()
    assert len(children) == 1, "exactly one child run should exist after the pause"
    child = children[0]
    child_id = child.id
    assert child.status == "hitl_pending"

    # The pending decision belongs to the CHILD run (its own HITL gate).
    dec = db_session.query(Decision).filter(Decision.id == child_decision_id).first()
    assert dec is not None
    assert dec.target_id == child_id
    dec.status = "accepted"
    db_session.commit()

    # Parent resume: must drive the SAME child to completion, no new child.
    resumed = await resume_run_dag(run.id, decision_id=child_decision_id)
    assert resumed["status"] == "completed"

    db_session.expire_all()
    children_after = db_session.query(Run).filter(Run.parent_run_id == run.id).all()
    assert len(children_after) == 1, "parent resume must NOT spawn a duplicate child"
    assert children_after[0].id == child_id
    assert children_after[0].status == "completed"

    run = db_session.query(Run).filter(Run.id == run.id).first()
    assert run.status == "completed"
    # Parent settles with the child's merged output (post-HITL tail), keyed to
    # the original child run id.
    assert run.output_ref.get("child_run_id") == child_id
    assert run.output_ref.get("child_done") is True
    assert run.output_ref.get("approved") is True

    # The child ran its tail skill exactly once (no re-delegation / replay).
    child_invocations = (
        db_session.query(SkillInvocation).filter(SkillInvocation.run_id == child_id).all()
    )
    assert [i.skill_slug for i in child_invocations] == ["child_tail_v1"]
    assert all(i.status == "completed" for i in child_invocations)


async def test_nested_subflow_hitl_resumes_entire_lineage_once(db_session, monkeypatch):
    """A → B → C propagates one HITL Decision and resumes without replay.

    Each delegating run persists the same child identity and the same Decision
    in its pause checkpoint. Resuming only the root recursively drives the
    existing lineage to completion; no level may create a replacement child or
    append more than one resume checkpoint.
    """

    async def child_tail(inp, ctx):
        return {"leaf_done": True, "approved": ctx.get("hitl_approved")}

    _install_fake_registry(monkeypatch, {"nested_child_tail_v1": child_tail})
    _mk_skill(db_session, "nested_child_tail_v1")

    leaf_flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "csrc", "kind": "source"},
            {"id": "ch", "kind": "hitl", "config": {"prompt": "leaf approve?"}},
            {
                "id": "ct",
                "kind": "task",
                "config": {"skill_slug": "nested_child_tail_v1"},
            },
            {"id": "csink", "kind": "sink"},
        ],
        "edges": [
            {"from": "csrc", "to": "ch"},
            {"from": "ch", "to": "ct"},
            {"from": "ct", "to": "csink"},
        ],
    }
    system_c = _mk_system(db_session, flow=leaf_flow)

    def _subflow_flow(node_id: str, target_id: str) -> Dict[str, Any]:
        return {
            "schema_version": 2,
            "nodes": [
                {"id": f"{node_id}_src", "kind": "source"},
                {
                    "id": node_id,
                    "kind": "subflow",
                    "config": {"system_id": target_id},
                },
                {"id": f"{node_id}_sink", "kind": "sink"},
            ],
            "edges": [
                {"from": f"{node_id}_src", "to": node_id},
                {"from": node_id, "to": f"{node_id}_sink"},
            ],
        }

    system_b = _mk_system(db_session, flow=_subflow_flow("b_to_c", system_c.id))
    system_a = _mk_system(db_session, flow=_subflow_flow("a_to_b", system_b.id))
    run_a = _mk_run(db_session, system_a)

    paused = await execute_run_dag(run_a.id)
    assert paused["status"] == "hitl_pending"
    decision_id = paused.get("awaiting_decision")
    assert decision_id

    db_session.expire_all()
    run_a = db_session.query(Run).filter(Run.id == run_a.id).one()
    runs_b = db_session.query(Run).filter(Run.parent_run_id == run_a.id).all()
    assert len(runs_b) == 1, "A must persist exactly one B child"
    run_b = runs_b[0]
    runs_c = db_session.query(Run).filter(Run.parent_run_id == run_b.id).all()
    assert len(runs_c) == 1, "B must persist exactly one C child"
    run_c = runs_c[0]

    for lineage_run in (run_a, run_b, run_c):
        assert lineage_run.status == "hitl_pending"
        pauses = [
            cp
            for cp in (lineage_run.checkpoints or [])
            if cp.get("kind") == "hitl_pause"
        ]
        assert len(pauses) == 1
        assert pauses[0].get("decision_id") == decision_id

    decision = db_session.query(Decision).filter(Decision.id == decision_id).one()
    assert decision.target_id == run_c.id
    decision.status = "accepted"
    db_session.commit()

    resumed = await resume_run_dag(run_a.id, decision_id=decision_id)
    assert resumed["status"] == "completed"

    db_session.expire_all()
    run_a = db_session.query(Run).filter(Run.id == run_a.id).one()
    run_b = db_session.query(Run).filter(Run.id == run_b.id).one()
    run_c = db_session.query(Run).filter(Run.id == run_c.id).one()
    assert [run_a.status, run_b.status, run_c.status] == ["completed"] * 3
    assert run_a.output_ref.get("leaf_done") is True
    assert run_b.output_ref.get("leaf_done") is True
    assert run_c.output_ref.get("leaf_done") is True
    assert run_c.output_ref.get("approved") is True

    assert db_session.query(Run).filter(Run.parent_run_id == run_a.id).count() == 1
    assert db_session.query(Run).filter(Run.parent_run_id == run_b.id).count() == 1
    assert db_session.query(Run).filter(Run.parent_run_id == run_c.id).count() == 0

    for lineage_run in (run_a, run_b, run_c):
        assert _checkpoint_kinds(lineage_run).count("hitl_resume") == 1

    leaf_invocations = (
        db_session.query(SkillInvocation).filter(SkillInvocation.run_id == run_c.id).all()
    )
    assert [item.skill_slug for item in leaf_invocations] == ["nested_child_tail_v1"]


def _unbound_decision_flow() -> dict:
    return {
        "schema_version": 2,
        "nodes": [
            {"id": "src", "kind": "source"},
            {
                "id": "route",
                "kind": "decision",
                "config": {
                    "branches": [
                        {
                            "label": "approved",
                            "condition": "line_manager_approved == True",
                        },
                        {"label": "refused", "condition": "True"},
                    ],
                },
            },
            {"id": "yes", "kind": "sink"},
            {"id": "no", "kind": "sink"},
        ],
        "edges": [
            {"from": "src", "to": "route"},
            {"from": "route", "to": "yes", "kind": "branch", "branch_label": "approved"},
            {"from": "route", "to": "no", "kind": "branch", "branch_label": "refused"},
        ],
    }


@pytest.mark.parametrize(
    ("validation_mode", "expected_status", "expected_disposition"),
    [
        ("enforce", "failed", "failed"),
        ("observe", "completed", "observed"),
    ],
)
async def test_a_decision_reading_an_unbound_name_is_enforced_or_observed(
    db_session,
    validation_mode,
    expected_status,
    expected_disposition,
):
    """The silent routing bug, made loud.

    ``line_manager_approved`` is bound nowhere, so the predicate compares None
    against True and the run quietly takes the fallback branch. Enforcing
    contracts refuse to route on that; observing ones record it and keep the
    historical behaviour.
    """

    flow = _unbound_decision_flow()
    system = _mk_system(db_session, flow=flow)
    run = _mk_run(db_session, system, input_ref={"query": "hello"})
    run.flow_snapshot = flow
    run.execution_contract = {
        "validation_mode": validation_mode,
        "nodes": {},
        "outputs": [],
    }
    db_session.commit()

    summary = await execute_run_dag(run.id)

    assert summary["status"] == expected_status
    db_session.expire_all()
    persisted = db_session.query(Run).filter(Run.id == run.id).one()
    reported = next(
        cp for cp in persisted.checkpoints if cp.get("kind") == "decision_input_unbound"
    )
    assert reported["names"] == ["line_manager_approved"]
    assert reported["node_id"] == "route"
    assert reported["disposition"] == expected_disposition


async def test_a_decision_whose_names_are_all_bound_routes_untouched(db_session):
    flow = _unbound_decision_flow()
    system = _mk_system(db_session, flow=flow)
    run = _mk_run(db_session, system, input_ref={"line_manager_approved": True})
    run.flow_snapshot = flow
    run.execution_contract = {
        "validation_mode": "enforce",
        "nodes": {},
        "outputs": [],
    }
    db_session.commit()

    summary = await execute_run_dag(run.id)

    assert summary["status"] == "completed"
    db_session.expire_all()
    persisted = db_session.query(Run).filter(Run.id == run.id).one()
    assert not [
        cp for cp in persisted.checkpoints if cp.get("kind") == "decision_input_unbound"
    ]
