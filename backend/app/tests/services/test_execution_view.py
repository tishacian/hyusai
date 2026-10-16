import asyncio
import json
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import update

from app.core.config import settings
from app.models.activity import Activity, ActivityEvent
from app.models.compute_run import ComputeRun
from app.models.run import Run, SkillInvocation
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.activity_observability import queries
from app.services.activity_observability.projection import activity_id
from app.services.execution_view import execution_view


@pytest.fixture
def context(db_session, monkeypatch):
    workspace = Workspace(id="view-ws", slug="view-ws", name="Execution view")
    user = User(id="view-user", username="view-user", role="admin", is_active=True)
    db_session.add_all([workspace, user])
    db_session.commit()
    monkeypatch.setattr(settings, "execution_view_enabled", True)
    monkeypatch.setattr(settings, "activity_observability_enabled", True)
    return db_session, workspace, user


def seed(context, **kwargs):
    db, workspace, _ = context
    row = Run(
        id=kwargs.pop("id", "view-run"),
        workspace_id=workspace.id,
        status=kwargs.pop("status", "running"),
        **kwargs,
    )
    db.add(row)
    db.commit()
    return row


def view(context, run, **kwargs):
    return execution_view(*context, run.id, **kwargs)


def member(context):
    db, workspace, _ = context
    row = User(id="ordinary-view", username="ordinary-view", role="user", is_active=True)
    db.add_all([row, WorkspaceMember(workspace_id=workspace.id, user_id=row.id, role="member")])
    db.commit()
    return row


def test_safe_frozen_topology_and_legacy_absence(context):
    snapshot = {
        "nodes": [
            {"id": "a", "kind": "task", "label": "Public", "config": {"prompt": "SECRET"}},
            {"id": "b", "kind": "sink", "data": {"title": "Done", "prompt": "SECRET"}},
            {"id": "c", "label": "<script>SECRET</script>"},
        ],
        "edges": [{"source": "a", "target": "b", "conditions": {"secret": "SECRET"}}],
    }
    run = seed(context, flow_snapshot=snapshot, input_ref={"secret": "SECRET"})
    result = view(context, run)
    assert "SECRET" not in json.dumps(result)
    assert result["graph"]["nodes"][0] == {"id": "a", "kind": "task", "label": "Public"}
    assert result["nodes"][0]["status"] == "not_started"
    assert run.flow_snapshot == snapshot and not context[0].dirty
    legacy = seed(context, id="legacy")
    assert view(context, legacy)["graph"] == {"available": False, "nodes": [], "edges": []}


def test_retries_loops_and_page_independent_totals(context):
    db, _, _ = context
    run = seed(context, flow_snapshot={"nodes": [{"id": "n", "kind": "retry"}]})
    for index, kind in enumerate(["task", "retry", "loop", "agent_loop_act"], 1):
        db.add(
            SkillInvocation(
                id=f"i-{index}",
                run_id=run.id,
                status="failed" if index == 1 else "completed",
                trace={
                    "node_id": "n",
                    "passage_id": "p",
                    "membrane_attempt_kind": kind,
                    "membrane_attempt_index": index,
                },
                provider_cost_usd=0.0,
                cost_measured=True,
                metrics={"cost_evidence": {"state": "calculated", "currency": "USD"}},
            )
        )
    db.commit()
    first, second = view(context, run, limit=2), view(context, run, limit=2, offset=2)
    assert first["total"] == second["total"] == 4
    assert first["nodes"] == second["nodes"]
    assert first["read_version"] == second["read_version"]
    assert first["nodes"][0]["counts"]["failed"] == 1
    assert first["nodes"][0]["passages_total"] == 1
    assert first["items"][1]["attempt_index"] == 2
    assert second["items"][0]["iteration"] == 3 and second["items"][0]["attempt_index"] is None
    assert second["items"][1]["iteration"] == 4
    assert second["items"][0]["measurements"]["cost_known"] is True


def test_checkpoint_transition_atomic_dedup_and_metadata_only(context):
    db, workspace, user = context
    run = seed(context, flow_snapshot={"nodes": [{"id": "gate", "kind": "hitl"}]})
    cursor = view(context, run)["snapshot_cursor"]
    cp = {
        "kind": "node_start",
        "node_id": "gate",
        "transition_id": "t1",
        "passage_id": "p",
        "t": "2026-10-16T10:00:00",
        "secret": "SECRET",
    }
    db.execute(update(Run).where(Run.id == run.id).values(checkpoints=[cp]))
    assert len(queries.event_page(db, workspace, user, cursor=cursor, run_id=run.id)["items"]) == 1
    db.rollback()
    assert not queries.event_page(db, workspace, user, cursor=cursor, run_id=run.id)["items"]
    run.checkpoints = [cp]
    db.commit()
    before = queries.highwater(db, workspace.id)
    run.checkpoints = [cp, cp]
    db.commit()
    assert queries.highwater(db, workspace.id) == before
    run.checkpoints = [
        cp,
        {
            "kind": "hitl_pause",
            "node_id": "gate",
            "transition_id": "t2",
            "passage_id": "p",
            "t": "2026-10-16T10:01:00",
            "state": {"password": "SECRET"},
        },
    ]
    db.commit()
    result = view(context, run)
    assert result["nodes"][0]["status"] == "waiting"
    assert result["nodes"][0]["waiting_reason"] == "human"
    assert result["items"][0]["started_at"] == "2026-10-16T10:00:00Z"
    assert "SECRET" not in json.dumps(result)
    assert "SECRET" not in json.dumps([row.snapshot for row in db.query(Activity).all()])
    assert "SECRET" not in json.dumps([row.payload for row in db.query(ActivityEvent).all()])


def test_skipped_control_node_is_not_queued(context):
    run = seed(
        context,
        flow_snapshot={"nodes": [{"id": "off", "kind": "task"}]},
        checkpoints=[
            {
                "kind": "node_start",
                "node_id": "off",
                "passage_id": "p",
                "transition_id": "a",
                "t": "2026-10-16T10:00:00",
            },
            {
                "kind": "node_end",
                "node_id": "off",
                "passage_id": "p",
                "transition_id": "b",
                "status": "skipped",
                "skipped_reason": "all_inputs_dead",
                "t": "2026-10-16T10:00:01",
            },
        ],
    )
    node = view(context, run)["nodes"][0]
    assert node["status"] == "not_executed" and node["skipped_reason"] == "all_inputs_dead"
    assert node["counts"].get("pending", 0) == 0


def test_child_created_after_snapshot_uses_same_subtree_cursor(context):
    db, workspace, user = context
    root = seed(context)
    cursor = view(context, root)["snapshot_cursor"]
    child = seed(
        context,
        id="late-child",
        parent_run_id=root.id,
        delegation_key="key",
        delegation_node_id="fork",
        delegation_branch="east",
    )
    page = queries.event_page(db, workspace, user, cursor=cursor, run_id=root.id, subtree=True)
    assert [item["activity_id"] for item in page["items"]] == [activity_id("run", child.id)]
    assert queries.event_page(db, workspace, user, cursor=cursor, run_id=root.id)["items"] == []
    assert view(context, root)["items"][0]["relation"] == "delegation"
    assert (
        queries.event_page(
            db, workspace, user, cursor=page["next_cursor"], run_id=root.id, subtree=True
        )["items"]
        == []
    )


def test_private_children_not_exposed_in_totals_or_stream(context):
    db, workspace, admin = context
    root = seed(context)
    user = member(context)
    child = seed(
        context,
        id="private-child",
        parent_run_id=root.id,
        trigger="chat_agentic",
        initiated_by_user_id=admin.id,
    )
    assert execution_view(db, workspace, user, root.id)["total"] == 0
    assert activity_id("run", child.id) not in {
        item["activity_id"]
        for item in queries.event_page(db, workspace, user, run_id=root.id, subtree=True)["items"]
    }
    with pytest.raises(HTTPException):
        execution_view(db, workspace, user, child.id)
    with pytest.raises(HTTPException):
        queries.event_page(db, workspace, user, run_id=child.id, subtree=True)


def test_compute_owner_and_outcome_unknown(context):
    db, workspace, admin = context
    run = seed(context)
    user = member(context)
    db.add(
        ComputeRun(
            id="secret-compute",
            workspace_id=workspace.id,
            user_id=admin.id,
            run_id=run.id,
            node_id="n",
            kind="read",
            operation="read",
            deadline_at=datetime.utcnow() + timedelta(hours=1),
            outcome_unknown=True,
        )
    )
    db.commit()
    assert execution_view(db, workspace, user, run.id)["total"] == 0
    assert view(context, run)["items"][0]["status"] == "unknown"


def test_invocation_policy_applies_before_counts_and_events(context, monkeypatch):
    from app.services import execution_view as service
    from app.services import run_access

    db, workspace, user = context
    run = seed(context)
    db.add(
        SkillInvocation(
            id="denied-inv",
            run_id=run.id,
            status="failed",
            trace={"node_id": "n", "passage_id": "p"},
        )
    )
    db.commit()
    monkeypatch.setattr(
        run_access, "readable_skill_invocations_for_runs", lambda *args, **kwargs: []
    )
    monkeypatch.setattr(service, "readable_skill_invocations_for_runs", lambda *args, **kwargs: [])
    assert view(context, run)["total"] == 0
    assert activity_id("skill_invocation", "denied-inv") not in {
        item["activity_id"]
        for item in queries.event_page(db, workspace, user, run_id=run.id)["items"]
    }


def test_flag_revoked_user_and_foreign_selection(context, monkeypatch):
    db, _, user = context
    run = seed(context)
    monkeypatch.setattr(settings, "execution_view_enabled", False)
    with pytest.raises(HTTPException, match="EXECUTION_VIEW_DISABLED"):
        view(context, run)
    monkeypatch.setattr(settings, "execution_view_enabled", True)
    with pytest.raises(HTTPException, match="EXECUTION_NODE_NOT_FOUND"):
        view(context, run, node_id="fake")
    other = seed(context, id="unrelated")
    with pytest.raises(HTTPException, match="ACTIVITY_NOT_FOUND"):
        view(context, run, activity_id_filter=activity_id("run", other.id))
    user.is_active = False
    db.commit()
    with pytest.raises(HTTPException, match="ACTIVITY_ACCESS_DENIED"):
        view(context, run)


def test_expired_cursor_demands_resync(context):
    db, workspace, user = context
    run = seed(context)
    run.status = "completed"
    db.commit()
    db.query(ActivityEvent).filter(
        ActivityEvent.sequence == 1, ActivityEvent.workspace_id == workspace.id
    ).delete()
    db.commit()
    with pytest.raises(HTTPException, match="ACTIVITY_CURSOR_EXPIRED"):
        queries.event_page(
            db, workspace, user, cursor=queries.encode_cursor(workspace.id, 0), run_id=run.id
        )


def test_task_local_passage_isolated_for_parallel_branches():
    from app.services.run_engine.execution_correlation import current_passage, passage_context

    async def branch(name):
        reset = passage_context.set({"run_id": "run", "node_id": name, "passage_id": name + "-p"})
        try:
            await asyncio.sleep(0)
            assert current_passage("run", name) == {"passage_id": name + "-p"}
            assert current_passage("run", "other") == {}
        finally:
            passage_context.reset(reset)

    async def execute():
        await asyncio.gather(branch("a"), branch("b"))

    asyncio.run(execute())
    assert passage_context.get() is None


@pytest.mark.asyncio
async def test_real_dag_retry_produces_one_passage_and_distinct_native_attempts(
    context, monkeypatch
):
    from app.services.run_engine.dag import execute_run_dag
    from app.tests.services.test_run_engine_dag_e2e import (
        _install_fake_registry,
        _mk_skill,
        _mk_system,
    )

    db, workspace, _ = context
    calls = []

    async def flaky(payload, ctx):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("test first attempt")
        return {"ok": True}

    _install_fake_registry(monkeypatch, {"observe_retry_v1": flaky})
    _mk_skill(db, "observe_retry_v1")
    flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "src", "kind": "source"},
            {
                "id": "retry",
                "kind": "retry",
                "config": {"skill_slug": "observe_retry_v1", "max_attempts": 2, "backoff_ms": 0},
            },
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [{"from": "src", "to": "retry"}, {"from": "retry", "to": "sink"}],
    }
    system = _mk_system(db, flow=flow)
    system.workspace_id = workspace.id
    db.commit()
    run = seed(context, system_id=system.id, status="pending")
    outcome = await execute_run_dag(run.id)
    assert outcome["status"] == "completed"
    db.expire_all()
    result = view(context, run)
    native = [item for item in result["items"] if item["source"] == "skill_invocation"]
    assert len(native) == 2 and len({item["passage_id"] for item in native}) == 1
    assert [item["attempt_index"] for item in native] == [1, 2]
    assert [item["status"] for item in native] == ["failed", "succeeded"]
    assert all(item["coverage"] == "exact" for item in native)
    cps = [
        item
        for item in run.checkpoints
        if item.get("node_id") == "retry" and item["kind"] in {"node_start", "node_end"}
    ]
    assert len(cps) == 2 and cps[0]["passage_id"] == native[0]["passage_id"] == cps[1]["passage_id"]
    assert cps[0]["transition_id"] != cps[1]["transition_id"]
    assert (
        next(item for item in result["nodes"] if item["node_id"] == "sink")["status"] == "succeeded"
    )


@pytest.mark.asyncio
async def test_live_token_stream_revokes_under_continuous_traffic(context, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from app.api.v1.endpoints import runs as api

    db, workspace, user = context
    run = seed(context)

    class Request:
        headers = {}

        async def is_disconnected(self):
            return False

    class Subscriber:
        count = 0

        async def next_event(self):
            self.count += 1
            return {"kind": "token_delta", "text": "token", "t": str(self.count)}

        async def aclose(self):
            pass

    monkeypatch.setattr(api, "SessionLocal", sessionmaker(bind=db.get_bind()))
    monkeypatch.setattr(api.event_bus, "subscribe", lambda _: Subscriber())
    stream = api._run_event_stream(run.id, Request(), workspace.id, user.id)
    assert "event: snapshot" in await anext(stream)
    assert "event: token_delta" in await anext(stream)
    user.is_active = False
    db.commit()
    await asyncio.sleep(1.05)
    frame = await anext(stream)
    assert "access_unavailable" in frame and "token_delta" not in frame
    async for _ in stream:
        pass


def test_historical_uncorrelated_work_does_not_pretend_nodes_never_started(context):
    db, _, _ = context
    run = seed(context, flow_snapshot={"nodes": [{"id": "n", "kind": "task"}]})
    db.add(SkillInvocation(id="legacy-inv", run_id=run.id, status="completed", trace={}))
    db.commit()
    node = view(context, run)["nodes"][0]
    assert node["status"] == "unknown" and node["coverage"] == "absent"


def test_wait_intervals_preserve_human_pause_and_recovery(context):
    run = seed(
        context,
        flow_snapshot={"nodes": [{"id": "n", "kind": "hitl"}]},
        checkpoints=[
            {
                "kind": kind,
                "node_id": "n",
                "passage_id": "p",
                "transition_id": f"t-{index}",
                "t": f"2026-10-16T10:0{index}:00",
                **({"status": "completed"} if kind == "node_end" else {}),
            }
            for index, kind in enumerate(["node_start", "hitl_pause", "hitl_resume", "node_end"])
        ],
    )
    item = view(context, run)["items"][0]
    assert item["status"] == "succeeded"
    assert [segment["phase"] for segment in item["intervals"]] == [
        "execution",
        "human",
        "execution",
    ]
    assert item["intervals"][1]["started_at"] == "2026-10-16T10:01:00Z"
    assert item["intervals"][1]["finished_at"] == "2026-10-16T10:02:00Z"


def test_resource_measurements_do_not_expose_policy_or_lease(context):
    from app.models.execution_control import ExecutionReservation

    db, workspace, _ = context
    run = seed(context)
    db.add(
        SkillInvocation(
            id="resource-inv", run_id=run.id, status="completed", trace={"node_id": "n"}
        )
    )
    db.add(
        ExecutionReservation(
            workspace_id=workspace.id,
            entity_kind="skill_invocation",
            entity_id="resource-inv",
            lane="batch",
            cpu_cores=2,
            memory_mb=512,
            reserved_core_hours=0.5,
            policy={"secret": "DO_NOT_RETURN"},
            lease_token="DO_NOT_RETURN",
            deadline_at=datetime.utcnow() + timedelta(hours=1),
            cpu_seconds=0.0,
            peak_rss_bytes=None,
        )
    )
    db.commit()
    result = view(context, run)
    item = result["items"][0]
    assert item["measurements"]["cpu_seconds"] == 0.0
    assert item["measurements"]["peak_memory_bytes"] is None
    assert item["resource_coverage"] == "measured"
    assert "DO_NOT_RETURN" not in json.dumps(result)


def test_root_activity_deep_link_is_accepted_without_hiding_work(context):
    run = seed(context)
    result = view(context, run, activity_id_filter=activity_id("run", run.id))
    assert result["run"]["id"] == run.id


@pytest.mark.parametrize(
    ("state", "currency", "amount", "basis", "usd"),
    [
        (None, None, None, "unknown", None),
        ("calculated", "EUR", 2.0, "catalogue_calculated", None),
        ("calculated", "USD", 2.0, "catalogue_calculated", None),
        ("measured", "USD", 3.0, "provider_measured", 3.0),
    ],
)
def test_cost_basis_requires_evidence_and_keeps_currency(
    context, state, currency, amount, basis, usd
):
    db, _, _ = context
    run = seed(context)
    db.add(
        SkillInvocation(
            id="cost-inv",
            run_id=run.id,
            status="completed",
            cost_measured=True,
            cost=2.0,
            provider_cost_usd=3.0,
            metrics={
                "cost_evidence": {"state": state, "currency": currency, "secret": "DO_NOT_RETURN"}
            },
            trace={"node_id": "n"},
        )
    )
    db.commit()
    result = view(context, run)
    values = result["items"][0]["measurements"]
    assert values["cost_amount"] == amount
    assert values["provider_cost_usd"] == usd
    assert values["cost_basis"] == basis
    assert values["currency"] == currency
    assert "DO_NOT_RETURN" not in json.dumps(result)


def test_catalogue_cost_settlement_emits_metadata_invalidation_without_status_change(context):
    db, workspace, user = context
    run = seed(context)
    invocation = SkillInvocation(
        id="settled-cost",
        run_id=run.id,
        status="completed",
        cost_measured=True,
        cost=1.0,
        metrics={"cost_evidence": {"state": "calculated", "currency": "EUR"}},
    )
    db.add(invocation)
    db.commit()
    cursor = view(context, run)["snapshot_cursor"]
    invocation.cost = 2.0
    invocation.metrics = {
        "cost_evidence": {"state": "calculated", "currency": "EUR", "secret": "DO_NOT_RETURN"}
    }
    db.commit()
    page = queries.event_page(db, workspace, user, cursor=cursor, run_id=run.id)
    assert len(page["items"]) == 1
    projection = db.query(Activity).filter_by(native_id=invocation.id).one()
    assert projection.snapshot["measurements"]["cost_amount"] == 2.0
    assert projection.snapshot["measurements"]["cost_basis"] == "catalogue_calculated"
    assert "DO_NOT_RETURN" not in json.dumps(projection.snapshot)
    cursor = page["next_cursor"]
    invocation.metrics = {**invocation.metrics, "token_count": 4}
    db.commit()
    assert queries.event_page(db, workspace, user, cursor=cursor, run_id=run.id)["items"] == []


@pytest.mark.asyncio
async def test_hitl_resume_recovers_passage_with_empty_process_context(context, monkeypatch):
    from app.models.decision import Decision
    from app.services.run_engine.dag import execute_run_dag, resume_run_dag
    from app.services.run_engine.execution_correlation import passage_context
    from app.tests.services.test_run_engine_dag_e2e import (
        _install_fake_registry,
        _mk_skill,
        _mk_system,
    )

    db, workspace, _ = context

    async def tail(payload, ctx):
        return {"ok": True}

    _install_fake_registry(monkeypatch, {"observed_tail_v1": tail})
    _mk_skill(db, "observed_tail_v1")
    flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "source", "kind": "source"},
            {"id": "human", "kind": "hitl", "config": {"prompt": "Approve?"}},
            {"id": "tail", "kind": "task", "config": {"skill_slug": "observed_tail_v1"}},
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "source", "to": "human"},
            {"from": "human", "to": "tail"},
            {"from": "tail", "to": "sink"},
        ],
    }
    system = _mk_system(db, flow=flow)
    system.workspace_id = workspace.id
    db.commit()
    run = seed(context, system_id=system.id, status="pending")
    paused = await execute_run_dag(run.id)
    assert paused["status"] == "hitl_pending" and passage_context.get() is None
    db.expire_all()
    before = view(context, run)
    human = next(item for item in before["items"] if item["node_id"] == "human")
    assert human["status"] == "waiting" and human["coverage"] == "exact"
    decision = db.get(Decision, paused["awaiting_decision"])
    decision.status = "accepted"
    db.commit()
    resumed = await resume_run_dag(run.id, decision_id=decision.id)
    assert resumed["status"] == "completed" and passage_context.get() is None
    db.expire_all()
    after = view(context, run)
    settled = next(item for item in after["items"] if item["node_id"] == "human")
    assert settled["status"] == "succeeded" and settled["passage_id"] == human["passage_id"]
    assert any(part["phase"] == "human" and part["finished_at"] for part in settled["intervals"])


@pytest.mark.asyncio
async def test_agent_data_ml_agent_composite_native_jobs_are_visible(context, monkeypatch):
    """Real DAG and ledger writes; deterministic skills, no external ML/provider claim."""
    from app.models.recipe import RecipeExecution
    from app.models.tabular import MLModel
    from app.models.workspace_job import WorkspaceJob
    from app.services.run_engine.dag import execute_run_dag
    from app.tests.services.test_run_engine_dag_e2e import (
        _install_fake_registry,
        _mk_skill,
        _mk_system,
    )

    db, workspace, user = context
    run = None

    async def identity(payload, ctx):
        return {"ok": True}

    async def prepare(payload, ctx):
        invocation = (
            db.query(SkillInvocation)
            .filter_by(run_id=run.id, status="running")
            .filter(SkillInvocation.skill_slug == "composite_prepare_v1")
            .one()
        )
        now = datetime.utcnow()
        db.add(
            RecipeExecution(
                id="composite-recipe",
                workspace_id=workspace.id,
                run_id=run.id,
                node_id="prepare",
                invocation_id=invocation.id,
                status="succeeded",
                started_at=now,
                finished_at=now,
            )
        )
        db.flush()
        db.add(
            ComputeRun(
                id="composite-compute",
                workspace_id=workspace.id,
                user_id=user.id,
                run_id=run.id,
                node_id="prepare",
                recipe_execution_id="composite-recipe",
                kind="dataops",
                operation="prepare",
                status="succeeded",
                deadline_at=now + timedelta(hours=1),
                started_at=now,
                finished_at=now,
            )
        )
        db.add(
            MLModel(
                id="composite-model",
                workspace_id=workspace.id,
                run_id=run.id,
                node_id="prepare",
                slug="composite",
                name="Composite",
                version=1,
                task="classification",
                algo="test",
                target="y",
                status="ready",
                trained_at=now,
            )
        )
        db.add(
            WorkspaceJob(
                id="composite-job",
                workspace_id=workspace.id,
                run_id=run.id,
                created_by_user_id=user.id,
                kind="briefing",
                status="completed",
                completed_at=now,
            )
        )
        db.commit()
        return {"ok": True}

    skills = {
        "composite_agent_before_v1": identity,
        "composite_prepare_v1": prepare,
        "composite_agent_after_v1": identity,
    }
    _install_fake_registry(monkeypatch, skills)
    for slug in skills:
        _mk_skill(db, slug)
    flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "source", "kind": "source"},
            *[
                {"id": node, "kind": "task", "config": {"skill_slug": slug}}
                for node, slug in zip(["agent-before", "prepare", "agent-after"], skills)
            ],
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": left, "to": right}
            for left, right in zip(
                ["source", "agent-before", "prepare", "agent-after"],
                ["agent-before", "prepare", "agent-after", "sink"],
            )
        ],
    }
    system = _mk_system(db, flow=flow)
    system.workspace_id = workspace.id
    db.commit()
    run = seed(context, system_id=system.id, status="pending")
    outcome = await execute_run_dag(run.id)
    assert outcome["status"] == "completed"
    db.expire_all()
    result = view(context, run)
    kinds = {item["source"] for item in result["items"]}
    assert {
        "skill_invocation",
        "recipe_execution",
        "compute_run",
        "ml_training",
        "workspace_job",
    } <= kinds
    prepare_items = [item for item in result["items"] if item["node_id"] == "prepare"]
    assert len(prepare_items) == 4
    assert (
        next(item for item in prepare_items if item["source"] == "recipe_execution")["passage_id"]
        == next(item for item in prepare_items if item["source"] == "skill_invocation")[
            "passage_id"
        ]
    )
    assert (
        next(item for item in result["items"] if item["source"] == "workspace_job")["node_id"]
        is None
    )


@pytest.mark.asyncio
async def test_data_judge_delivery_composite_keeps_native_receipt_and_stream_lineage(
    context, monkeypatch, tmp_path
):
    """Deterministic judge/skills; real governed assets, review and receipt publication."""
    from types import SimpleNamespace

    from app.services import governed_assets as assets
    from app.services import service_promises as services
    from app.services.run_engine.dag import execute_run_dag
    from app.tests.services.test_run_engine_dag_e2e import (
        _install_fake_registry,
        _mk_skill,
        _mk_system,
    )
    from app.tests.services.test_service_contracts import NOW, asset, review_snapshot, window

    db, workspace, user = context
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path))
    workspace.settings = {"features": {"service_contracts": True}}
    db.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role="owner",
            role_template="workspace_owner",
        )
    )
    db.commit()
    state = {}

    async def data(payload, ctx):
        state["asset"] = asset(scope, text="Deterministic public evidence", run_id=run.id)
        db.commit()
        return {"ok": True}

    async def judge(payload, ctx):
        state["qualification"] = assets.record_qualification(
            db,
            workspace.id,
            assets.asset_ref(state["asset"]),
            status="qualified",
            policy={"rubric": "deterministic-test"},
            evidence={"classification": "accepted", "test_provider": True},
            confidence=1.0,
        )
        db.commit()
        return {"accepted": True}

    async def deliver(payload, ctx):
        attempt = services.claim_window(
            db,
            workspace.id,
            service_window.id,
            worker_id="deterministic-test",
            run_id=run.id,
            now=NOW,
        )
        services.complete_attempt(
            db,
            workspace.id,
            service_window.id,
            fence=attempt.fence,
            lease_token=attempt.lease_token,
            candidate_ref=assets.asset_ref(state["asset"]),
            now=NOW + timedelta(seconds=1),
        )
        decision = services.review_delivery(
            db,
            workspace.id,
            service_window.id,
            **review_snapshot(scope, service_window),
            reviewer_user_id=user.id,
            accept=True,
            now=NOW + timedelta(seconds=2),
        )
        state["receipt"] = services.publish_delivery(
            db,
            workspace.id,
            service_window.id,
            decision_id=decision.id,
            fence=attempt.fence,
            lease_token=attempt.lease_token,
            now=NOW + timedelta(seconds=3),
        )
        db.commit()
        return {"delivered": True}

    skills = {"observed_data_v1": data, "observed_judge_v1": judge, "observed_delivery_v1": deliver}
    _install_fake_registry(monkeypatch, skills)
    for slug in skills:
        _mk_skill(db, slug)
    flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "source", "kind": "source"},
            *[
                {"id": node, "kind": "task", "config": {"skill_slug": slug}}
                for node, slug in zip(["data", "judge", "deliver"], skills)
            ],
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": left, "to": right}
            for left, right in zip(
                ["source", "data", "judge", "deliver"], ["data", "judge", "deliver", "sink"]
            )
        ],
    }
    system = _mk_system(db, flow=flow)
    system.workspace_id = workspace.id
    db.commit()
    run = seed(context, system_id=system.id, status="pending")
    scope = SimpleNamespace(db=db, workspace=workspace, owner=user, system=system)
    _, service_window = window(scope)
    db.commit()
    cursor = view(context, run)["snapshot_cursor"]
    outcome = await execute_run_dag(run.id)
    assert outcome["status"] == "completed"
    db.expire_all()
    result = view(context, run)
    receipts = [item for item in result["items"] if item["source"] == "delivery_receipt"]
    assert len(receipts) == 1 and receipts[0]["native_id"] == state["receipt"].id
    assert receipts[0]["node_id"] is None  # No native node correlation exists for a receipt.
    assert receipts[0]["native_status"] == "published"
    page = queries.event_page(
        db, workspace, user, cursor=cursor, run_id=run.id, subtree=True, limit=500
    )
    assert activity_id("delivery_receipt", state["receipt"].id) in {
        event["activity_id"] for event in page["items"]
    }
    assert {"data", "judge", "deliver"} <= {
        item["node_id"] for item in result["items"] if item["source"] == "skill_invocation"
    }
