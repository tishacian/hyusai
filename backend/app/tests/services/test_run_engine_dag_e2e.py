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

from app.models.capability import Capability
from app.models.decision import Decision
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.services.run_engine import dag as dag_module
from app.services.run_engine import engine as engine_module
from app.services.run_engine.dag import execute_run_dag, resume_run_dag


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
SkillFn = Callable[[Dict[str, Any], Dict[str, Any]], "Any"]


def _install_fake_registry(
    monkeypatch: pytest.MonkeyPatch, skills: Dict[str, SkillFn]
) -> None:
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

    _install_fake_registry(
        monkeypatch, {"one_v1": first, "two_v1": second, "three_v1": third}
    )

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

    invocations = (
        db_session.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run.id)
        .all()
    )
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

    invocations = (
        db_session.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run.id)
        .all()
    )
    assert {i.skill_slug for i in invocations} == {"high_v1"}

    # Decision's node_end records the chosen branch.
    decisions_cp = [
        cp
        for cp in (run.checkpoints or [])
        if cp.get("kind") == "node_end" and cp.get("node_id") == "dec"
    ]
    assert decisions_cp, "decision node_end checkpoint missing"
    assert decisions_cp[0].get("chosen_branch") == "hi"


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
# 7 — Subflow inlined
# ---------------------------------------------------------------------------
async def test_subflow_inlines_target_system_skills(db_session, monkeypatch):
    """A ``subflow`` node resolves the target System and executes its
    bound skills inside the parent run, persisting their invocations on
    the parent run_id."""
    async def inner_a(inp, ctx):
        return {"a": "A"}

    async def inner_b(inp, ctx):
        return {"b": "B"}

    _install_fake_registry(monkeypatch, {"inner_a_v1": inner_a, "inner_b_v1": inner_b})
    _mk_skill(db_session, "inner_a_v1")
    _mk_skill(db_session, "inner_b_v1")

    # Target System — sequential skill list, no custom flow needed.
    target = _mk_system(
        db_session, flow={}, skill_slugs=["inner_a_v1", "inner_b_v1"]
    )

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
    invocations = (
        db_session.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run.id)
        .order_by(SkillInvocation.started_at.asc())
        .all()
    )
    # Subflow inlined both target skills into the parent run's ledger.
    assert [i.skill_slug for i in invocations] == ["inner_a_v1", "inner_b_v1"]
    assert all(i.status == "completed" for i in invocations)

    run = db_session.query(Run).filter(Run.id == run.id).first()
    # The subflow wrapper stamps the target system id into its output.
    assert run.output_ref.get("subflow_system_id") == target.id
