"""Evolving workspace Skills against frozen published contracts.

Authoring made a Skill's contract and its runtime mutable while a published Flow
was already dispatching them. The schemas were already frozen at publication and
never re-read, so an edit to them could not reach a Run; the executor was not,
and was resolved from the row at every invocation. So the surface that could
silently change production was the one nobody flagged.

These tests fix the boundary: publication freezes the runtime as well, an edit is
admitted but cannot cross it, and the author is told which published versions the
edit did not reach.
"""

from __future__ import annotations

import copy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import skills
from app.models.run import Run
from app.models.skill import Skill
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.flow_contracts import (
    FlowContractError,
    canonical_sha256,
    compile_execution_contract,
    validate_execution_contract,
)
from app.services.run_engine.engine import _frozen_node_executor
from app.services.skills_registry.binding import SkillBindingError
from app.services.skills_registry.published_bindings import published_skill_bindings
from app.services.skills_registry.workspace_skills import workspace_skill_callable

WORKSPACE_ID = "ws-freeze"
AUTHORED_SLUG = f"ws.{WORKSPACE_ID}.draft_reply"
FROZEN_TEMPLATE = {
    "kind": "prompt_template",
    "params": {"provider": "ollama", "template": "Answer {ticket}."},
}
EDITED_TEMPLATE = {
    "kind": "prompt_template",
    "params": {"provider": "ollama", "template": "Answer {incident}."},
}


def _flow(slug: str) -> dict:
    return {
        "schema_version": 3,
        "nodes": [
            {"id": "entry", "kind": "source"},
            {"id": "draft", "kind": "task", "config": {"skill_slug": slug}},
            {"id": "result", "kind": "sink"},
        ],
        "edges": [
            {"from": "entry", "to": "draft"},
            {"from": "draft", "to": "result"},
        ],
    }


def _seed(db) -> tuple[Workspace, User, Skill]:
    workspace = Workspace(id=WORKSPACE_ID, slug="freeze", name="Freeze", settings={})
    user = User(id="freeze-user", username="freeze-user")
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="member",
        role_template="workspace_admin",
    )
    authored = Skill(
        id="skill-authored",
        workspace_id=workspace.id,
        slug=AUTHORED_SLUG,
        name="Draft a reply",
        type="generation",
        input_schema={"type": "object", "properties": {"ticket": {"type": "string"}}},
        output_schema={"type": "object"},
        executor=copy.deepcopy(FROZEN_TEMPLATE),
        is_seeded="N",
    )
    seeded = Skill(
        id="skill-seeded",
        slug="causal_drill_v1",
        name="Causal drill",
        type="analysis",
        is_seeded="Y",
    )
    db.add_all([workspace, user, member, authored, seeded])
    db.commit()
    return workspace, user, authored


def _compile(db, slug: str) -> dict:
    return compile_execution_contract(
        db,
        flow=_flow(slug),
        workspace_id=WORKSPACE_ID,
        runtime_mode="dag_overlay",
    )


def _publish(db, contract: dict, *, slug: str = AUTHORED_SLUG) -> System:
    """Point a System at a version carrying ``contract``, as Publish would."""

    system = System(
        id="system-freeze",
        workspace_id=WORKSPACE_ID,
        name="Reply desk",
        objective="test",
        flow_definition=_flow(slug),
        status="active",
    )
    version = SystemVersion(
        id="version-freeze",
        system_id=system.id,
        workspace_id=WORKSPACE_ID,
        version_number=1,
        flow_definition=_flow(slug),
        release_kind="publish",
        execution_contract=contract,
    )
    db.add_all([system, version])
    db.flush()
    system.published_flow_version_id = version.id
    db.commit()
    return system


def _client(db, workspace, user) -> TestClient:
    app = FastAPI()
    app.include_router(skills.router, prefix="/skills")
    app.dependency_overrides[skills.get_current_workspace] = lambda: workspace
    app.dependency_overrides[skills.get_current_user] = lambda: user
    app.dependency_overrides[skills.get_db] = lambda: db
    return TestClient(app)


def test_publication_freezes_the_authored_runtime_alongside_its_schemas(db_session):
    _seed(db_session)

    contract = _compile(db_session, AUTHORED_SLUG)

    node = contract["nodes"]["draft"]
    assert node["executor"] == FROZEN_TEMPLATE
    assert node["skill_definition_sha256"]
    # The frozen document must survive its own validator, or a Run could never
    # be created from the version that carries it.
    assert validate_execution_contract(contract) == contract


def test_a_seeded_contract_keeps_the_shape_its_digest_was_taken_over(db_session):
    """Every contract already published was digested without these keys.

    Adding them unconditionally would change ``contract_sha256`` for flows that
    did not change, which the publish path reads as a version to append.
    """

    _seed(db_session)

    contract = _compile(db_session, "causal_drill_v1")

    node = contract["nodes"]["draft"]
    assert "executor" not in node
    assert "skill_definition_sha256" not in node
    assert validate_execution_contract(contract) == contract


@pytest.mark.parametrize(
    ("mutate", "path"),
    [
        (lambda node: node.update({"executor": {"kind": "prompt_template"}}), "executor"),
        (lambda node: node.update({"executor": {"kind": "", "params": {}}}), "executor/kind"),
        (
            lambda node: node.update({"executor": {"kind": "x", "params": "nope"}}),
            "executor/params",
        ),
        (
            lambda node: node.update({"skill_definition_sha256": "short"}),
            "skill_definition_sha256",
        ),
        # The two keys are one fact, so half of it is a shape violation rather
        # than a node that froze a runtime and forgot to say which definition.
        (lambda node: node.pop("skill_definition_sha256"), ""),
        (lambda node: node.pop("executor"), ""),
    ],
)
def test_a_frozen_runtime_that_is_not_well_formed_is_refused(db_session, mutate, path):
    _seed(db_session)
    contract = _compile(db_session, AUTHORED_SLUG)
    mutate(contract["nodes"]["draft"])
    body = {key: value for key, value in contract.items() if key != "contract_sha256"}
    contract["contract_sha256"] = canonical_sha256(body)

    with pytest.raises(FlowContractError) as exc_info:
        validate_execution_contract(contract)

    assert exc_info.value.code == "execution_contract_invalid"
    assert exc_info.value.path == f"/nodes/draft/{path}".rstrip("/")


async def test_a_published_node_runs_the_binding_it_was_published_with(db_session):
    """The edit is invisible to the Run: the frozen template is what renders.

    Observed through the placeholder the template requires, because that is
    resolved before the provider is reached, so the assertion is about dispatch
    rather than about the model.
    """

    _, _, authored = _seed(db_session)
    contract = _compile(db_session, AUTHORED_SLUG)
    run = Run(
        id="run-freeze",
        workspace_id=WORKSPACE_ID,
        status="running",
        execution_contract=contract,
    )
    db_session.add(run)
    authored.executor = copy.deepcopy(EDITED_TEMPLATE)
    db_session.commit()

    frozen = workspace_skill_callable(
        db_session,
        workspace_id=WORKSPACE_ID,
        slug=AUTHORED_SLUG,
        frozen_executor=_frozen_node_executor(run, "draft"),
    )
    live = workspace_skill_callable(
        db_session,
        workspace_id=WORKSPACE_ID,
        slug=AUTHORED_SLUG,
    )

    with pytest.raises(SkillBindingError) as frozen_error:
        await frozen({"unrelated": "x"}, None)
    with pytest.raises(SkillBindingError) as live_error:
        await live({"unrelated": "x"}, None)

    assert "ticket" in frozen_error.value.message
    assert "incident" in live_error.value.message


def test_a_frozen_runtime_outlives_the_row_it_was_copied_from(db_session):
    """Publication is evidence, not a pointer, so the lookup is not attempted."""

    _, _, authored = _seed(db_session)
    contract = _compile(db_session, AUTHORED_SLUG)
    db_session.delete(authored)
    db_session.commit()

    assert workspace_skill_callable(
        db_session,
        workspace_id=WORKSPACE_ID,
        slug=AUTHORED_SLUG,
        frozen_executor=contract["nodes"]["draft"]["executor"],
    )
    with pytest.raises(SkillBindingError) as exc_info:
        workspace_skill_callable(
            db_session,
            workspace_id=WORKSPACE_ID,
            slug=AUTHORED_SLUG,
        )
    assert exc_info.value.code == "skill_not_found"


def test_a_frozen_runtime_is_still_re_verified_at_every_dispatch(db_session):
    """Freezing pins which verified parameters run, never that they still are."""

    _seed(db_session)

    with pytest.raises(SkillBindingError) as exc_info:
        workspace_skill_callable(
            db_session,
            workspace_id=WORKSPACE_ID,
            slug=AUTHORED_SLUG,
            frozen_executor={"kind": "withdrawn_kind", "params": {}},
        )

    assert exc_info.value.code == "executor_kind_unknown"


def test_a_published_binding_is_fresh_until_the_definition_moves(db_session):
    _, _, authored = _seed(db_session)
    _publish(db_session, _compile(db_session, AUTHORED_SLUG))

    fresh = published_skill_bindings(
        db_session, workspace_id=WORKSPACE_ID, skill=authored
    )
    authored.executor = copy.deepcopy(EDITED_TEMPLATE)
    db_session.commit()
    stale = published_skill_bindings(
        db_session, workspace_id=WORKSPACE_ID, skill=authored
    )

    assert [item.system_name for item in fresh] == ["Reply desk"]
    assert fresh[0].node_ids == ("draft",)
    assert fresh[0].stale is False
    assert stale[0].stale is True


def test_a_published_flow_that_does_not_dispatch_it_is_not_reported(db_session):
    _, _, authored = _seed(db_session)
    _publish(db_session, _compile(db_session, "causal_drill_v1"), slug="causal_drill_v1")

    assert published_skill_bindings(
        db_session, workspace_id=WORKSPACE_ID, skill=authored
    ) == []


def test_a_version_published_before_the_freeze_is_reported_as_behind(db_session):
    """It resolves its runtime live, so it cannot be said to hold a definition."""

    _, _, authored = _seed(db_session)
    contract = _compile(db_session, AUTHORED_SLUG)
    node = contract["nodes"]["draft"]
    del node["executor"]
    del node["skill_definition_sha256"]
    _publish(db_session, contract)

    bindings = published_skill_bindings(
        db_session, workspace_id=WORKSPACE_ID, skill=authored
    )

    assert [item.stale for item in bindings] == [True]


def test_an_edit_under_a_published_flow_is_admitted_and_reported(db_session):
    workspace, user, authored = _seed(db_session)
    _publish(db_session, _compile(db_session, AUTHORED_SLUG))
    client = _client(db_session, workspace, user)

    updated = client.patch(
        f"/skills/{AUTHORED_SLUG}",
        json={"executor": EDITED_TEMPLATE},
    )

    assert updated.status_code == 200
    payload = updated.json()
    assert payload["executor"] == EDITED_TEMPLATE
    assert payload["published_bindings"] == [
        {
            "system_id": "system-freeze",
            "system_name": "Reply desk",
            "version_id": "version-freeze",
            "version_number": 1,
            "node_ids": ["draft"],
            "stale": True,
        }
    ]


def test_a_delete_under_a_published_flow_names_the_system_and_refuses(db_session):
    workspace, user, _ = _seed(db_session)
    _publish(db_session, _compile(db_session, AUTHORED_SLUG))
    client = _client(db_session, workspace, user)

    refused = client.delete(f"/skills/{AUTHORED_SLUG}")

    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert detail["code"] == "skill_bound_by_published_flow"
    assert "Reply desk" in detail["message"]
    assert db_session.query(Skill).filter(Skill.slug == AUTHORED_SLUG).one()


async def test_agent_loop_tool_keeps_published_executor_after_catalog_edit(db_session):
    _, _, authored = _seed(db_session)
    flow = {"nodes": [{"id": "investigate", "kind": "agent_loop", "config": {
        "skill_slug": "causal_drill_v1", "skill_allowlist": [AUTHORED_SLUG],
    }}], "edges": []}
    contract = compile_execution_contract(db_session, flow=flow,
        workspace_id=WORKSPACE_ID, runtime_mode="dag_overlay")
    assert validate_execution_contract(contract) == contract
    _publish(db_session, contract)
    run = Run(id="loop-freeze", workspace_id=WORKSPACE_ID,
              status="running", execution_contract=contract)
    authored.executor = copy.deepcopy(EDITED_TEMPLATE)
    db_session.commit()
    frozen = _frozen_node_executor(run, "investigate", AUTHORED_SLUG)
    assert frozen == FROZEN_TEMPLATE
    assert _frozen_node_executor(run, "investigate", "causal_drill_v1") is None
    with pytest.raises(ValueError, match="agent_loop_tool_not_frozen"):
        _frozen_node_executor(run, "investigate", "unlisted")
    fn = workspace_skill_callable(db_session, workspace_id=WORKSPACE_ID,
                                 slug=AUTHORED_SLUG, frozen_executor=frozen)
    with pytest.raises(SkillBindingError) as error:
        await fn({"incident": "new catalog input"}, None)
    assert "ticket" in error.value.message
    bindings = published_skill_bindings(db_session, workspace_id=WORKSPACE_ID, skill=authored)
    assert bindings[0].node_ids == ("investigate",)
    assert bindings[0].stale is True
    # Even an outer digest recomputed by a caller cannot hide missing tools.
    contract["nodes"]["investigate"]["tool_contract"]["nodes"] = {}
    contract["contract_sha256"] = canonical_sha256({k: v for k, v in contract.items() if k != "contract_sha256"})
    with pytest.raises(FlowContractError):
        validate_execution_contract(contract)


async def test_agent_loop_dispatch_enforces_frozen_tool_input_and_output(db_session, monkeypatch):
    from app.services.run_engine import engine
    from app.services.model_plane import execution
    _, _, authored = _seed(db_session)
    authored.input_schema = {"type": "object", "required": ["ticket"],
                             "properties": {"ticket": {"type": "string"}}}
    authored.output_schema = {"type": "object", "required": ["answer"],
                              "properties": {"answer": {"type": "string"}}}
    db_session.commit()
    contract = compile_execution_contract(db_session, workspace_id=WORKSPACE_ID,
        runtime_mode="dag_overlay", flow={"nodes": [{"id": "investigate",
        "kind": "agent_loop", "config": {"skill_slug": "causal_drill_v1",
        "skill_allowlist": [AUTHORED_SLUG]}}], "edges": []})
    run = Run(id="loop-input-freeze", workspace_id=WORKSPACE_ID, status="running",
              execution_contract=contract, input_ref={})
    db_session.add(run)
    authored.input_schema = {"type": "object"}
    db_session.commit()
    called = []
    async def tool(payload, ctx):
        called.append(payload)
        return {"answer": "fixed"} if payload.get("ticket") == "original" else {}
    def bind(*args, **kwargs):
        assert kwargs["frozen_executor"] == FROZEN_TEMPLATE
        return tool
    monkeypatch.setattr(engine, "workspace_skill_callable", bind)
    monkeypatch.setattr(execution, "resolve_skill_model_execution", lambda *a, **kw: None)
    invocation = await engine._execute_task_node(db_session, run, {}, AUTHORED_SLUG,
        control=None, last_output={}, node_id="investigate", resolved_input={"incident": "new"})
    assert invocation.status == "failed"
    assert called == []
    valid = await engine._execute_task_node(db_session, run, {}, AUTHORED_SLUG,
        control=None, last_output={}, node_id="investigate", resolved_input={"ticket": "original"})
    assert valid.status == "completed"
    assert called == [{"ticket": "original"}]
    assert valid.trace["tool_contract_sha256"] == contract["nodes"]["investigate"]["tool_contract"]["contract_sha256"]
    invalid_output = await engine._execute_task_node(db_session, run, {}, AUTHORED_SLUG,
        control=None, last_output={}, node_id="investigate", resolved_input={"ticket": "bad output"})
    assert invalid_output.status == "failed"
