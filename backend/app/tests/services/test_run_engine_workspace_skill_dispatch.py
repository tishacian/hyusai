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


def _model_policy(db, run, slug, allowed, system_model):
    from app.models.policy import ControlPolicy
    system = db.get(System, run.system_id)
    system.default_model = system_model
    policy = ControlPolicy(id=str(uuid4()), workspace_id=run.workspace_id, name="Effective model policy", scope="system", target_id=system.id, allowed_skills=[slug], extra={"membrane_spec": {
        "version": 2, "enforcement_mode": "enforce", "outbound": {"expert_review_required": False},
        "capabilities": {"allowed_skills": [slug], "allowed_models": allowed, "allowed_actions": ["system.engine.run"]},
        "provenance": {"require_citations": False},
    }})
    system.control_policy_id = policy.id
    db.add(policy); db.commit()
    return system


@pytest.mark.asyncio
@pytest.mark.parametrize("system_model,selected,expected", [
    ("gpt-denied", "gpt-allowed", "completed"),
    ("gpt-allowed", "gpt-denied", "failed"),
])
async def test_policy_uses_skill_model_instead_of_system_default(db_session, monkeypatch, system_model, selected, expected):
    from app.services.model_plane import execution
    calls = []
    class Client:
        async def generate(self, **kwargs):
            calls.append(kwargs)
            return {"content": "ok", "model": kwargs["model"], "usage": {"total_tokens": 3}}
    monkeypatch.setattr(execution, "build_model_client", lambda resolved: Client())
    run, slug = _authored_run(db_session, executor={"kind": "prompt_template", "params": {
        "provider": "openai", "model": selected, "template": "Explain {event_type}.",
    }})
    _model_policy(db_session, run, slug, ["openai:gpt-allowed"], system_model)
    result = await execute_run_dag(run.id)
    assert result["status"] == expected
    assert len(calls) == (1 if expected == "completed" else 0)
    if calls:
        invocation = db_session.query(SkillInvocation).filter(SkillInvocation.run_id == run.id).one()
        assert invocation.trace["effective_model"] == "openai:gpt-allowed"
        assert invocation.trace["model_execution"]["model_source"] == "executor"
        assert "model_execution" not in invocation.output_ref
        assert "model" not in invocation.input_ref  # pin is not a new user input


@pytest.mark.asyncio
async def test_provider_qualified_policy_blocks_same_model_on_azure(db_session, monkeypatch):
    from app.services.model_plane import execution
    monkeypatch.setattr(execution, "build_model_client", lambda resolved: (_ for _ in ()).throw(AssertionError("must not connect")))
    run, slug = _authored_run(db_session, executor={"kind": "prompt_template", "params": {
        "provider": "azure_openai", "model": "gpt-allowed", "template": "Explain {event_type}.",
    }})
    _model_policy(db_session, run, slug, ["openai:gpt-allowed"], "gpt-allowed")
    assert (await execute_run_dag(run.id))["status"] == "failed"
    assert db_session.query(SkillInvocation).filter(SkillInvocation.run_id == run.id).count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,output_fields", [("ollama", ["completion", "model"]), ("azure", ["completion", "model", "usage"])])
async def test_frozen_closed_output_preserves_legacy_shape_and_runtime(db_session, monkeypatch, provider, output_fields):
    from jsonschema import validate
    from app.models.system_version import SystemVersion
    from app.services.flow_contracts import compile_execution_contract
    from app.services.model_plane import execution
    seen = []
    class Client:
        async def generate(self, **kwargs):
            seen.append(kwargs)
            return {"content": "ok", "model": kwargs["model"], "usage": {"total_tokens": 3}}
    monkeypatch.setattr(execution, "build_model_client", lambda resolved: Client())
    run, slug = _authored_run(db_session, executor={"kind": "prompt_template", "params": {"provider": provider, "template": "Explain {event_type}."}})
    skill = db_session.query(Skill).filter(Skill.slug == slug).one()
    schema = {"type": "object", "additionalProperties": False, "required": output_fields, "properties": {key: {"type": "object" if key == "usage" else "string"} for key in output_fields}}
    skill.output_schema = schema
    system = db_session.get(System, run.system_id)
    system.default_model = "different-current-system-model"
    db_session.commit()
    contract = compile_execution_contract(db_session, flow=system.flow_definition, workspace_id=run.workspace_id, runtime_mode="dag_overlay")
    version = SystemVersion(id=str(uuid4()), system_id=system.id, workspace_id=run.workspace_id, version_number=1, flow_definition=system.flow_definition, release_kind="publish", execution_contract=contract)
    db_session.add(version); db_session.flush()
    system.published_flow_version_id = version.id
    run.execution_contract = contract
    run.flow_snapshot = system.flow_definition
    run.flow_version_id = version.id
    skill.executor = {"kind": "prompt_template", "params": {"provider": "openai", "model": "gpt-different", "template": "CHANGED {event_type}."}}
    db_session.commit()
    result = await execute_run_dag(run.id)
    assert result["status"] == "completed"
    invocation = db_session.query(SkillInvocation).filter(SkillInvocation.run_id == run.id).one()
    validate(invocation.output_ref, schema)
    assert set(invocation.output_ref) == set(output_fields)
    assert seen[0]["model"] == ("deepseek-r1:14b" if provider == "ollama" else "gpt-4o-mini")
    assert not seen[0]["prompt"].startswith("CHANGED")
    assert invocation.trace["model_execution"]["model_source"] in {"legacy_default", "published_legacy_default"}
    assert invocation.metrics["total_tokens"] == 3


@pytest.mark.asyncio
async def test_denied_fallback_fails_canonical_run_without_second_provider_call(db_session, monkeypatch):
    from app.services.model_plane import execution
    seen = []
    class Client:
        async def generate(self, **kwargs):
            seen.append(kwargs)
            raise TimeoutError()
    monkeypatch.setattr(execution, "build_model_client", lambda resolved: Client())
    monkeypatch.setattr(execution.settings, "ollama_default_model", "qwen3:8b")
    run, slug = _authored_run(db_session, executor={"kind": "prompt_template", "params": {"provider": "workspace", "template": "Explain {event_type}."}})
    workspace = db_session.get(Workspace, run.workspace_id)
    workspace.settings = {"llm_portal": {"routing": {"default_provider": "openai", "default_model": "gpt-allowed", "fallback_chain": ["openai", "ollama"]}}}
    db_session.commit()
    _model_policy(db_session, run, slug, ["openai:gpt-allowed"], None)
    result = await execute_run_dag(run.id)
    assert result["status"] == "failed"
    assert "model_not_allowed:ollama:qwen3:8b" in result["error"]
    assert len(seen) == 1
    invocation = db_session.query(SkillInvocation).filter(SkillInvocation.run_id == run.id).one()
    assert invocation.status == "failed"
    assert [item["status"] for item in invocation.trace["model_execution"]["attempts"]] == ["failed", "blocked"]
    assert invocation.metrics["token_evidence"]["measurement_coverage"] == "unavailable"
    assert invocation.trace["effective_model"] == "openai:gpt-allowed"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing_template_input", "missing_credential"])
async def test_resolution_is_not_execution_evidence_without_provider_dispatch(db_session, monkeypatch, failure):
    from app.services.model_plane import execution
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError("No provider client should be constructed")
    monkeypatch.setattr("app.services.model_clients.openai_client.OpenAIClient", forbidden)
    template = "Explain {missing}." if failure == "missing_template_input" else "Explain {event_type}."
    run, slug = _authored_run(db_session, executor={"kind": "prompt_template", "params": {"provider": "openai", "model": "gpt-test", "template": template}})
    await execute_run_dag(run.id)
    invocation = db_session.query(SkillInvocation).filter(SkillInvocation.run_id == run.id).one()
    assert invocation.status == "failed"
    assert invocation.trace["model_resolution"]["provider"] == "openai"
    assert "model_execution" not in invocation.trace
    assert "effective_model" not in invocation.trace
    assert "total_tokens" not in invocation.metrics
    assert "No provider client" not in invocation.error


@pytest.mark.asyncio
@pytest.mark.parametrize("valves,expected_breach", [
    ({"token_budget": 100}, "token_measurement_unavailable"),
    ({"max_latency_ms": 0.001}, "max_latency_ms"),
])
async def test_canonical_valves_block_fallback_before_a_second_dispatch(db_session, monkeypatch, valves, expected_breach):
    from app.models.policy import ControlPolicy
    from app.services.model_plane import execution
    seen = []
    class Client:
        async def generate(self, **kwargs):
            seen.append(kwargs)
            raise TimeoutError()
    monkeypatch.setattr(execution, "build_model_client", lambda resolved: Client())
    monkeypatch.setattr(execution.settings, "ollama_default_model", "qwen3:8b")
    run, slug = _authored_run(db_session, executor={"kind": "prompt_template", "params": {"provider": "workspace", "template": "Explain {event_type}."}})
    workspace = db_session.get(Workspace, run.workspace_id)
    workspace.settings = {"llm_portal": {"routing": {"default_provider": "openai", "default_model": "gpt-allowed", "fallback_chain": ["openai", "ollama"]}}}
    db_session.commit()
    system = _model_policy(db_session, run, slug, ["openai:gpt-allowed", "ollama:qwen3:8b"], None)
    policy = db_session.get(ControlPolicy, system.control_policy_id)
    policy.extra = {"membrane_spec": {**policy.extra["membrane_spec"], "valves": valves}}
    db_session.commit()
    result = await execute_run_dag(run.id)
    assert result["status"] == "failed"
    assert expected_breach in result["error"]
    assert len(seen) == 1
    invocation = db_session.query(SkillInvocation).filter(SkillInvocation.run_id == run.id).one()
    assert invocation.trace["model_execution"]["attempts"][-1]["dispatch_started"] is False
    assert invocation.trace["model_execution"]["attempts"][-1]["status"] == "blocked"
