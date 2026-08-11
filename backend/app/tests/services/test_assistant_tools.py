"""Tool behaviour: workspace scoping, refusals, and the execution boundary."""
from __future__ import annotations

import ast
import inspect
import textwrap

import pytest
from fastapi import HTTPException

from app.models.decision import Decision
from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember
from app.services.assistant import tools as assistant_tools
from app.services.assistant.config import resolve_assistant_config
from app.services.assistant.tools import (
    KNOWN_TOOLS,
    TOOLS,
    ToolContext,
    execute_tool,
    tools_for,
)


def _subject(db_session, *, allowed_tools: list[str], role_template: str = "workspace_admin"):
    workspace = Workspace(
        id="ws-tools",
        name="Tools",
        slug="tools",
        settings={
            "knowledge_scopes": [
                {"key": "itsd", "collection_slugs": ["itsd-knowledge"], "is_default": True}
            ],
            "assistant": {"knowledge_scope": "itsd", "allowed_tools": allowed_tools},
        },
    )
    user = User(id="user-tools", username="tools@datategy.test", email="tools@datategy.test")
    db_session.add_all(
        [
            workspace,
            user,
            WorkspaceMember(
                user_id=user.id,
                workspace_id=workspace.id,
                role="member",
                role_template=role_template,
            ),
        ]
    )
    db_session.commit()
    return workspace, user


def _ctx(db_session, workspace, user, *, session_context=None) -> ToolContext:
    return ToolContext(
        db=db_session,
        user=user,
        workspace=workspace,
        config=resolve_assistant_config(workspace, known_tools=KNOWN_TOOLS),
        session_id="session-tools",
        surface="text",
        session_context=session_context or {},
    )


async def test_search_knowledge_is_scoped_to_the_configured_workspace_scope(
    db_session, monkeypatch
):
    workspace, user = _subject(db_session, allowed_tools=["search_knowledge"])
    seen: dict = {}

    async def fake_retrieve(request):
        seen.update(request)
        return {
            "chunks": ["passage"],
            "scores": [0.5],
            "metadatas": [{"chunk_id": "c1", "document_filename": "doc.pdf"}],
        }

    monkeypatch.setattr("app.services.rag.context.retrieve_rag_context", fake_retrieve)

    result = await execute_tool(
        _ctx(db_session, workspace, user),
        "search_knowledge",
        {"query": "mot de passe"},
    )

    assert result["ok"] is True
    assert seen["workspace_id"] == workspace.id
    assert seen["workspace_slug"] == "tools"
    assert seen["knowledge_scope"] == "itsd"
    assert result["collections"] == ["itsd-knowledge"]
    assert result["citations"][0]["filename"] == "doc.pdf"


async def test_search_knowledge_without_a_query_refuses_readably(db_session):
    workspace, user = _subject(db_session, allowed_tools=["search_knowledge"])

    result = await execute_tool(_ctx(db_session, workspace, user), "search_knowledge", {})

    assert result == {
        "ok": False,
        "error": "query_required",
        "message": "search_knowledge needs a non-empty query.",
    }


async def test_list_systems_only_returns_systems_of_this_workspace(db_session):
    workspace, user = _subject(db_session, allowed_tools=["list_systems"])
    other = Workspace(id="ws-other-tools", name="Other", slug="other-tools", settings={})
    db_session.add_all(
        [
            other,
            System(id="sys-mine", workspace_id=workspace.id, name="Mine", objective="o"),
            System(id="sys-theirs", workspace_id=other.id, name="Theirs", objective="o"),
        ]
    )
    db_session.commit()

    result = await execute_tool(_ctx(db_session, workspace, user), "list_systems", {})

    assert [row["system_id"] for row in result["systems"]] == ["sys-mine"]
    # No published Flow version, so the model is told the system is not runnable
    # rather than being handed a digest it could not obtain.
    assert result["systems"][0]["runnable"] is False
    assert result["systems"][0]["flow_sha256"] is None


async def test_get_run_status_hides_a_run_from_another_workspace(db_session):
    workspace, user = _subject(db_session, allowed_tools=["get_run_status"])
    other = Workspace(id="ws-foreign-run", name="Foreign", slug="foreign-run", settings={})
    db_session.add_all(
        [other, Run(id="run-foreign", workspace_id=other.id, status="completed")]
    )
    db_session.commit()

    result = await execute_tool(
        _ctx(db_session, workspace, user),
        "get_run_status",
        {"run_id": "run-foreign"},
    )

    assert result["ok"] is False
    assert result["error"] == "run_not_found"


async def test_get_run_status_surfaces_a_pending_human_gate(db_session):
    workspace, user = _subject(db_session, allowed_tools=["get_run_status"])
    db_session.add(
        Run(
            id="run-paused",
            workspace_id=workspace.id,
            status="hitl_pending",
            trigger="assistant_tool",
            checkpoints=[
                {
                    "kind": "hitl_pause",
                    "node_id": "gate-1",
                    "prompt": "Confirmer la réinitialisation ?",
                    "decision_id": "decision-1",
                }
            ],
        )
    )
    db_session.commit()

    result = await execute_tool(
        _ctx(db_session, workspace, user),
        "get_run_status",
        {"run_id": "run-paused"},
    )

    assert result["ok"] is True
    assert result["awaiting_gate"] == {
        "node_id": "gate-1",
        "prompt": "Confirmer la réinitialisation ?",
        "decision_id": "decision-1",
    }


async def test_a_tool_absent_from_the_allowlist_is_never_executed(db_session, monkeypatch):
    workspace, user = _subject(db_session, allowed_tools=["search_knowledge"])

    def explode(*args, **kwargs):
        raise AssertionError("a disallowed tool must not reach its handler")

    monkeypatch.setattr(
        "app.services.assistant.tools.enforce_system_engine_run",
        explode,
    )

    result = await execute_tool(
        _ctx(db_session, workspace, user),
        "start_system_run",
        {"system_id": "sys-1"},
    )

    assert result["error"] == "tool_not_available"


async def test_start_system_run_crosses_the_execution_boundary_before_creating_a_run(
    db_session,
    monkeypatch,
):
    workspace, user = _subject(db_session, allowed_tools=["start_system_run"])
    db_session.add(
        System(id="sys-run", workspace_id=workspace.id, name="Password reset", objective="o")
    )
    db_session.commit()
    order: list[str] = []

    def spy_enforce(db, *, user, workspace, system, source):
        order.append(f"enforce:{source}")
        return None

    def fake_create(db, **kwargs):
        order.append("create_run")
        assert kwargs["trigger"] == "assistant_tool"
        assert kwargs["expected_flow_sha256"] == "a" * 64
        assert kwargs["adapter_evidence"]["surface"] == "assistant_engine"
        run = Run(id="run-new", workspace_id=workspace.id, system_id="sys-run", status="pending")
        db.add(run)
        return run

    monkeypatch.setattr(
        "app.services.assistant.tools.enforce_system_engine_run",
        spy_enforce,
    )
    monkeypatch.setattr(
        "app.services.systems.flow_ingress.create_published_ingress_run",
        fake_create,
    )
    monkeypatch.setattr(
        "app.services.assistant.tools._dispatch_run",
        lambda run_id: order.append(f"dispatch:{run_id}"),
    )

    result = await execute_tool(
        _ctx(db_session, workspace, user),
        "start_system_run",
        {"system_id": "sys-run", "expected_flow_sha256": "a" * 64, "input": {"ticket": "T-1"}},
    )

    assert result["ok"] is True
    assert result["run_id"] == "run-new"
    assert order == ["enforce:assistant_engine", "create_run", "dispatch:run-new"]


async def test_start_system_run_refuses_a_system_of_another_workspace(db_session, monkeypatch):
    workspace, user = _subject(db_session, allowed_tools=["start_system_run"])
    other = Workspace(id="ws-foreign-sys", name="Foreign", slug="foreign-sys", settings={})
    db_session.add_all(
        [other, System(id="sys-foreign", workspace_id=other.id, name="Foreign", objective="o")]
    )
    db_session.commit()

    def explode(*args, **kwargs):
        raise AssertionError("tenant scoping must precede the authorization call")

    monkeypatch.setattr("app.services.assistant.tools.enforce_system_engine_run", explode)

    result = await execute_tool(
        _ctx(db_session, workspace, user),
        "start_system_run",
        {"system_id": "sys-foreign"},
    )

    assert result["error"] == "system_not_found"


async def test_an_enforced_denial_stops_the_run_and_is_reported_to_the_model(
    db_session,
    monkeypatch,
    attest_authorization_v2,
):
    workspace, user = _subject(
        db_session,
        allowed_tools=["start_system_run"],
        role_template="workspace_viewer",
    )
    db_session.add(
        System(id="sys-denied", workspace_id=workspace.id, name="Denied", objective="o")
    )
    config = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        version=1,
        role_flags={},
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "modes": {"system.engine.run": "enforce"},
            }
        },
    )
    db_session.add(config)
    db_session.flush()
    attest_authorization_v2(config, ["system.engine.run"])
    db_session.commit()

    def explode(*args, **kwargs):
        raise AssertionError("a denied caller must never reach the run engine")

    monkeypatch.setattr(
        "app.services.systems.flow_ingress.create_published_ingress_run",
        explode,
    )
    monkeypatch.setattr("app.services.assistant.tools._dispatch_run", explode)

    result = await execute_tool(
        _ctx(db_session, workspace, user),
        "start_system_run",
        {"system_id": "sys-denied"},
    )

    assert result["ok"] is False
    assert result["error"] == "run_forbidden"
    assert result["status_code"] == 403


async def test_answer_hitl_gate_refuses_a_run_that_is_not_paused(db_session, monkeypatch):
    workspace, user = _subject(db_session, allowed_tools=["answer_hitl_gate"])
    db_session.add(Run(id="run-live", workspace_id=workspace.id, status="running"))
    db_session.commit()

    def explode(*args, **kwargs):
        raise AssertionError("no boundary crossing on a run that has no gate")

    monkeypatch.setattr("app.services.assistant.tools.enforce_system_engine_run", explode)

    result = await execute_tool(
        _ctx(db_session, workspace, user),
        "answer_hitl_gate",
        {"run_id": "run-live", "decision": "accept"},
    )

    assert result["error"] == "gate_not_pending"


def _paused_run_with_gate(db_session, workspace, *, decision_target: str | None = None):
    db_session.add(
        System(id="sys-gate", workspace_id=workspace.id, name="Gated", objective="o")
    )
    run = Run(
        id="run-gated",
        workspace_id=workspace.id,
        system_id="sys-gate",
        status="hitl_pending",
        checkpoints=[
            {"kind": "hitl_pause", "node_id": "gate-1", "decision_id": "decision-gate"}
        ],
    )
    decision = Decision(
        id="decision-gate",
        workspace_id=workspace.id,
        scope="run",
        target_id=decision_target or run.id,
        kind="hitl_approval",
        status="proposed",
        title="HITL approval — gate-1",
    )
    db_session.add_all([run, decision])
    db_session.commit()
    return run, decision


async def test_answer_hitl_gate_accepts_the_decision_and_resumes_the_execution(
    db_session,
    monkeypatch,
):
    workspace, user = _subject(db_session, allowed_tools=["answer_hitl_gate"])
    run, decision = _paused_run_with_gate(db_session, workspace)
    order: list[str] = []
    monkeypatch.setattr(
        "app.services.assistant.tools.enforce_system_engine_run",
        lambda db, **kwargs: order.append(f"enforce:{kwargs['source']}"),
    )
    monkeypatch.setattr(
        "app.services.assistant.tools._dispatch_gate_resume",
        lambda run_id, decision_id: order.append(f"resume:{run_id}:{decision_id}"),
    )

    result = await execute_tool(
        _ctx(db_session, workspace, user),
        "answer_hitl_gate",
        {"run_id": run.id, "decision": "accept", "note": "confirmé par l'utilisateur"},
    )

    assert result["ok"] is True
    assert result["decision_status"] == "accepted"
    assert result["applied"] == "accept"
    assert order == ["enforce:assistant_engine", f"resume:{run.id}:{decision.id}"]
    db_session.refresh(decision)
    assert decision.status == "accepted"
    assert decision.approved_by == "tools@datategy.test"


async def test_answer_hitl_gate_refuses_a_gate_owned_by_a_nested_run(db_session, monkeypatch):
    workspace, user = _subject(db_session, allowed_tools=["answer_hitl_gate"])
    run, _decision = _paused_run_with_gate(db_session, workspace, decision_target="run-child")
    monkeypatch.setattr(
        "app.services.assistant.tools._dispatch_gate_resume",
        lambda *args: (_ for _ in ()).throw(AssertionError("must not resume")),
    )

    result = await execute_tool(
        _ctx(db_session, workspace, user),
        "answer_hitl_gate",
        {"run_id": run.id, "decision": "accept"},
    )

    assert result["error"] == "gate_plane_unsupported"


async def test_answer_hitl_gate_rejects_an_invalid_decision_value(db_session):
    workspace, user = _subject(db_session, allowed_tools=["answer_hitl_gate"])

    result = await execute_tool(
        _ctx(db_session, workspace, user),
        "answer_hitl_gate",
        {"run_id": "run-x", "decision": "maybe"},
    )

    assert result["error"] == "decision_invalid"


async def test_service_catalogue_tools_read_the_session_context_only(db_session):
    workspace, user = _subject(db_session, allowed_tools=["list_services", "preview_service"])
    catalog = [
        {"slug": "password-reset", "title": "Password reset", "category": "identity"},
        {"slug": "vpn-access", "title": "VPN access", "category": "network"},
    ]
    ctx = _ctx(db_session, workspace, user, session_context={"service_catalog": catalog})

    listed = await execute_tool(ctx, "list_services", {"query": "vpn"})
    previewed = await execute_tool(ctx, "preview_service", {"slug": "password-reset"})
    missing = await execute_tool(ctx, "preview_service", {"slug": "nope"})

    assert [item["slug"] for item in listed["services"]] == ["vpn-access"]
    assert previewed["service"]["title"] == "Password reset"
    assert missing["error"] == "service_not_found"


async def test_a_tool_raising_an_http_exception_is_translated_not_propagated(
    db_session,
    monkeypatch,
):
    workspace, user = _subject(db_session, allowed_tools=["list_systems"])

    def deny(*args, **kwargs):
        raise HTTPException(status_code=403, detail="nope")

    monkeypatch.setattr("app.services.assistant.tools.enforce_action", deny)

    result = await execute_tool(_ctx(db_session, workspace, user), "list_systems", {})

    assert result["error"] == "tool_forbidden"
    assert result["status_code"] == 403


def test_tools_for_returns_only_allowed_tools_in_a_stable_order(db_session):
    workspace, _user = _subject(db_session, allowed_tools=["list_systems", "search_knowledge"])
    config = resolve_assistant_config(workspace, known_tools=KNOWN_TOOLS)

    assert [tool.name for tool in tools_for(config)] == ["list_systems", "search_knowledge"]


def test_every_tool_exposes_a_provider_ready_specification():
    for name, tool in TOOLS.items():
        spec = tool.as_openai_spec()
        assert spec["type"] == "function"
        assert spec["function"]["name"] == name
        assert spec["function"]["description"]
        assert spec["function"]["parameters"]["type"] == "object"


@pytest.mark.parametrize("tool_name", ["start_system_run", "answer_hitl_gate"])
def test_mutating_tools_are_never_enabled_by_default(db_session, tool_name):
    workspace = Workspace(id="ws-default", name="Default", slug="default", settings={})
    config = resolve_assistant_config(workspace, known_tools=KNOWN_TOOLS)

    assert config.allows(tool_name) is False


def test_a_mutating_tool_never_suspends() -> None:
    """A cancelled turn must not leave a Run created that nobody ordered.

    A turn is a cancellable task — a barge-in on the voice surface cancels it
    while the engine is mid-loop — and a coroutine only takes a cancellation at
    a suspension point. Both mutating tools commit a row and then hand it to the
    run engine, so the window between the two is kept closed by construction:
    they contain no ``await``, ``async with`` or ``async for`` at all. That is
    invisible in the code, which is why it is asserted here rather than trusted:
    the first ``await`` dropped into one of them reopens the window silently.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(assistant_tools)))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }

    for name, tool in TOOLS.items():
        if not tool.mutating:
            continue
        handler = functions[tool.handler.__name__]
        suspensions = sorted(
            child.lineno
            for child in ast.walk(handler)
            if isinstance(child, ast.Await | ast.AsyncWith | ast.AsyncFor)
        )
        assert suspensions == [], (
            f"{name} suspends at line(s) {suspensions} of its module: a cancellation "
            "can now land between the row it commits and the dispatch that orders it. "
            "Shield the commit/dispatch pair explicitly instead of reopening it."
        )
