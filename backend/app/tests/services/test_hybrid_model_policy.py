"""A model allowlist governs real LLM calls, not deterministic hybrid steps."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.policy import ControlPolicy
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.services.membrane.enforcement import evaluate_capability
from app.services.membrane.spec import MembraneSpec
from app.services.model_plane.execution import ModelExecution
from app.services.model_plane.skill_capabilities import (
    VERIFIED_NON_TEXT_SKILLS,
    is_verified_non_text_skill,
)
from app.services.run_engine import engine
from app.services.run_engine.agent_loop import compile_mandate_view


def _policy(slug):
    return ControlPolicy(
        id=str(uuid4()),
        name="Hybrid scope",
        scope="system",
        extra={
            "membrane_spec": {
                "version": 2,
                "enforcement_mode": "enforce",
                "capabilities": {
                    "allowed_skills": [slug],
                    "allowed_models": ["openai:gpt-allowed"],
                },
            }
        },
    )


def _run(db, slug, *, executor=None):
    skill = Skill(
        id=str(uuid4()),
        slug=slug,
        name=slug,
        version="v1",
        input_schema={},
        output_schema={},
        execution={"mode": "sync"},
        executor=executor,
        pricing={},
    )
    run = Run(
        id=str(uuid4()),
        status="running",
        input_ref={},
        execution_contract={
            "nodes": {"work": {"skill_slug": slug, **({"executor": executor} if executor else {})}}
        },
    )
    db.add_all([skill, run])
    db.commit()
    return skill, run


def test_missing_model_is_denied_unless_server_explicitly_scopes_out_text_models():
    spec = MembraneSpec.from_dict(
        {
            "version": 2,
            "enforcement_mode": "enforce",
            "capabilities": {"allowed_models": ["openai:gpt-allowed"]},
        },
        authoritative=True,
    )
    assert not evaluate_capability(spec, skill="unknown_native").allowed
    assert evaluate_capability(spec, skill="data_prep_v1", model_required=False).allowed
    assert not evaluate_capability(spec, model="openai:gpt-denied", model_required=False).allowed


def test_reviewed_classification_uses_executable_not_authored_metadata():
    assert is_verified_non_text_skill("data_prep_v1", None)
    assert not is_verified_non_text_skill("unknown_native", None)
    assert not is_verified_non_text_skill("polars_transform_v1", None)
    assert not is_verified_non_text_skill("connector_read_v1", None)
    assert not is_verified_non_text_skill("connector_write_request_v1", None)
    assert not is_verified_non_text_skill("ws.any.data_prep_v1", None)
    assert not is_verified_non_text_skill("data_prep_v1", {"kind": "prompt_template", "params": {}})
    assert is_verified_non_text_skill(
        "ws.any.read", {"kind": "registry_call", "params": {"skill_slug": "semantic_search_v1"}}
    )
    assert not is_verified_non_text_skill(
        "ws.any.read",
        {
            "kind": "registry_call",
            "params": {"skill_slug": "unknown_native", "model_required": False},
        },
    )
    from app.services.skills_registry.wrappers import resolve

    assert all(callable(resolve(slug)) for slug in VERIFIED_NON_TEXT_SKILLS)


def test_agent_catalog_does_not_mistake_projection_for_a_model_call():
    control = _policy("semantic_search_v1")
    view = compile_mandate_view(
        ["semantic_search_v1", "azure_llm_v1"], control=control, privilege_tier="recommend"
    )
    assert view.slugs() == {"semantic_search_v1"}
    assert "skill_not_allowed:azure_llm_v1" in view.membrane_blocked


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "slug",
    ["data_prep_v1", "ml_batch_score_v1", "postgresql_claim_snapshot_v1", "semantic_search_v1"],
)
async def test_non_text_steps_execute_under_a_text_model_allowlist(db_session, monkeypatch, slug):
    _, run = _run(db_session, slug)
    calls = []

    async def operation(payload, ctx):
        calls.append(payload)
        return {"rows": 23}

    monkeypatch.setattr(engine, "resolve_skill", lambda _: operation)
    invocation = await engine._execute_task_node(
        db_session,
        run,
        {"default_model": "unrelated-default"},
        slug,
        control=_policy(slug),
        last_output={},
        node_id="work",
        resolved_input={"model": {"model_id": "classical-ml", "version": 5}},
    )
    assert invocation.status == "completed" and len(calls) == 1
    assert invocation.trace["effective_model"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("claimed_model", [None, "openai:gpt-allowed"])
async def test_unknown_native_cannot_claim_non_text_in_input(
    db_session, monkeypatch, claimed_model
):
    slug = "unknown_native"
    _, run = _run(db_session, slug)
    monkeypatch.setattr(
        engine, "resolve_skill", lambda _: pytest.fail("Unknown model identity must block")
    )
    invocation = await engine._execute_task_node(
        db_session,
        run,
        {"default_model": claimed_model},
        slug,
        control=_policy(slug),
        last_output={},
        node_id="work",
        resolved_input={"model_required": False, "provider": "internal", "model": claimed_model},
    )
    assert invocation is None
    assert "model_not_allowed:missing" in run.error
    assert db_session.query(SkillInvocation).filter_by(run_id=run.id).count() == 0


@pytest.mark.asyncio
async def test_even_reviewed_non_text_step_cannot_dispatch_a_forbidden_nested_model(
    db_session, monkeypatch
):
    slug = "semantic_search_v1"
    _, run = _run(db_session, slug)
    dispatched = []

    async def operation(payload, ctx):
        ctx["_model_policy_check"](ModelExecution("openai", "gpt-denied", "test", "test"))
        dispatched.append(True)
        return {"answer": "must not execute"}

    monkeypatch.setattr(engine, "resolve_skill", lambda _: operation)
    invocation = await engine._execute_task_node(
        db_session,
        run,
        {},
        slug,
        control=_policy(slug),
        last_output={},
        node_id="work",
        resolved_input={},
    )
    assert invocation.status == "failed" and dispatched == []
    assert "model_not_allowed:openai:gpt-denied" in invocation.error


@pytest.mark.asyncio
async def test_frozen_alias_identity_wins_over_changed_live_executor(db_session, monkeypatch):
    slug = "ws.reviewed.operation"
    frozen = {"kind": "registry_call", "params": {"skill_slug": "semantic_search_v1"}}
    skill, run = _run(db_session, slug, executor=frozen)
    skill.executor = {
        "kind": "prompt_template",
        "params": {"provider": "openai", "model": "gpt-denied", "template": "changed"},
    }
    db_session.commit()

    async def operation(payload, ctx):
        return {"results": []}

    def bind(*args, frozen_executor, **kwargs):
        assert frozen_executor == frozen
        return operation

    monkeypatch.setattr(engine, "workspace_skill_callable", bind)
    invocation = await engine._execute_task_node(
        db_session,
        run,
        {},
        slug,
        control=_policy(slug),
        last_output={},
        node_id="work",
        resolved_input={},
    )
    assert invocation.status == "completed"


def test_hybrid_run_entry_defers_to_each_checked_runtime(db_session):
    flow = {
        "nodes": [
            {"id": "source", "kind": "source"},
            {"id": "prepare", "kind": "task", "config": {"skill_slug": "data_prep_v1"}},
            {
                "id": "loop",
                "kind": "agent_loop",
                "config": {"skill_allowlist": ["semantic_search_v1"]},
            },
            {"id": "judge", "kind": "task", "config": {"skill_slug": "evaluate_v2"}},
            {"id": "sink", "kind": "sink"},
        ]
    }
    system = System(default_model="openai:gpt-allowed", flow_definition=flow)
    run = SimpleNamespace(flow_snapshot=flow, execution_contract={}, workspace_id=None)
    assert engine._evaluate_run_capability(
        _policy("decide_next_v1"), system, db=db_session, run=run
    ).allowed
    flow["nodes"][1]["config"]["skill_slug"] = "unknown_native"
    denied = engine._evaluate_run_capability(
        _policy("decide_next_v1"), system, db=db_session, run=run
    )
    assert not denied.allowed and "model_not_allowed:missing" in denied.violations


@pytest.mark.parametrize("kind", ["subflow", "unknown_runtime"])
def test_unknown_flow_runtime_cannot_use_approved_default_as_model_proof(db_session, kind):
    flow = {"nodes": [{"id": "runtime", "kind": kind}]}
    system = System(default_model="openai:gpt-allowed", flow_definition=flow)
    run = SimpleNamespace(flow_snapshot=flow, execution_contract={}, workspace_id=None)
    denied = engine._evaluate_run_capability(
        _policy("unknown_native"), system, db=db_session, run=run
    )
    assert not denied.allowed and "model_not_allowed:missing" in denied.violations


@pytest.mark.asyncio
async def test_unknown_authored_alias_cannot_borrow_input_model_identity(db_session, monkeypatch):
    slug = "ws.custom.composite"
    executor = {
        "kind": "registry_call",
        "params": {"skill_slug": "unknown_native", "frozen_input": {"model": "openai:gpt-allowed"}},
    }
    _, run = _run(db_session, slug, executor=executor)
    monkeypatch.setattr(
        engine,
        "workspace_skill_callable",
        lambda *a, **kw: pytest.fail("Must block before binding"),
    )
    invocation = await engine._execute_task_node(
        db_session,
        run,
        {"default_model": "openai:gpt-allowed"},
        slug,
        control=_policy(slug),
        last_output={},
        node_id="work",
        resolved_input={"model": "openai:gpt-allowed"},
    )
    assert invocation is None and "model_not_allowed:missing" in run.error


def test_frozen_missing_tool_contract_is_not_replaced_by_live_binding(db_session):
    flow = {
        "nodes": [
            {
                "id": "loop",
                "kind": "agent_loop",
                "config": {"skill_allowlist": ["semantic_search_v1"]},
            }
        ]
    }
    contract = {"nodes": {"loop": {"skill_slug": "decide_next_v1", "tool_contract": {"nodes": {}}}}}
    run = SimpleNamespace(flow_snapshot=flow, execution_contract=contract, workspace_id=None)
    system = System(default_model="openai:gpt-allowed", flow_definition=flow)
    denied = engine._evaluate_run_capability(
        _policy("semantic_search_v1"), system, db=db_session, run=run
    )
    assert not denied.allowed
