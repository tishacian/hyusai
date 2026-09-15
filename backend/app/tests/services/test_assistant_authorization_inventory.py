"""Structural guarantee: no assistant tool reaches the run engine unguarded.

A model that can start or resume an execution is an escalation surface. The
guarantee we need is not "the current code calls the boundary" but "code that
forgets the boundary cannot ship". So this suite reads the tool module as an AST
and follows intra-module calls: if a tool can reach a run engine entrypoint
through any private helper, its own body must call
``enforce_system_engine_run`` first.

The checker itself is exercised against a deliberately violating source, so a
future refactor that neuters the analysis fails here too. And because the
analysis matches call names against a list, the list is itself recomputed from
what ``app/services/run_engine`` actually exports: an entrypoint added there
later cannot stay invisible here just because nobody remembered to write it
down.
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import textwrap

import app.services.run_engine as run_engine_package
from app.services.assistant import tools as assistant_tools

# Every function that starts, resumes or continues a real execution, plus the
# Decision transitions that release a paused one. Names outside the run engine
# package are listed because they are the boundary's other side: the Flow
# ingress that commits a Run, the agentic chat run factory, and the two Decision
# transitions. Everything else is cross-checked against the package below.
RUN_ENGINE_ENTRYPOINTS = frozenset(
    {
        "accept_decision",
        "create_agentic_chat_run",
        "create_published_ingress_run",
        "enqueue_dispatch",
        "execute_run",
        "execute_run_dag",
        "reject_decision",
        "resume_parent_for_child",
        "resume_parent_for_child_sync",
        "resume_run_dag",
        "resume_run_dag_debug",
        "resume_subflow_parent",
        "resume_subflow_parent_sync",
        "run_subflow_child",
        "schedule_run",
        "schedule_run_hitl_resume",
        "schedule_subflow_hitl_resume",
        "schedule_subflow_parent_resume",
        "schedule_subflow_run",
    }
)

# What an execution entrypoint of the run engine is called. Deliberately a
# naming rule and not a hand-kept list: the rule is applied to the package's
# real exports, so a new ``schedule_*`` / ``resume_*`` / ``execute_*`` lands in
# the inventory above or fails the cross-check.
ENTRYPOINT_VERBS = (
    "dispatch_",
    "enqueue_",
    "execute_",
    "launch_",
    "resume_",
    "run_",
    "schedule_",
    "start_",
)

# Exports the naming rule catches that reach no execution. Short on purpose: a
# real entrypoint belongs in the inventory above, never here. Each line says
# what the function does instead.
NON_ENTRYPOINT_EXPORTS = frozenset(
    {
        "dispatch_trigger_ingresses",  # maps event kinds to trigger node ids
        "run_correlation_key",  # builds an idempotency key for an inbox event
        "run_has_agent_loop",  # reads a run's snapshot for a loop node, runs nothing
    }
)

AUTHORIZATION_GUARD = "enforce_system_engine_run"


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _module_functions(tree: ast.Module) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _calls(node: ast.AST) -> list[tuple[str, int]]:
    return [
        (name, child.lineno)
        for child in ast.walk(node)
        if isinstance(child, ast.Call) and (name := _call_name(child)) is not None
    ]


def _reachable_functions(
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    entry: str,
) -> set[str]:
    """Transitive closure of intra-module calls, so a helper is not a bypass."""
    seen: set[str] = set()
    frontier = [entry]
    while frontier:
        current = frontier.pop()
        if current in seen or current not in functions:
            continue
        seen.add(current)
        frontier.extend(name for name, _ in _calls(functions[current]))
    return seen


def unguarded_run_engine_tools(source: str, handler_names: dict[str, str]) -> dict[str, str]:
    """Return ``{tool_name: reason}`` for every tool missing the boundary.

    ``handler_names`` maps a public tool name to the module-level function that
    implements it.
    """
    tree = ast.parse(textwrap.dedent(source))
    functions = _module_functions(tree)
    violations: dict[str, str] = {}
    for tool_name, handler_name in handler_names.items():
        handler = functions.get(handler_name)
        if handler is None:
            violations[tool_name] = f"handler {handler_name!r} is not a module-level function"
            continue
        reached = {
            call
            for name in _reachable_functions(functions, handler_name)
            for call, _lineno in _calls(functions[name])
        }
        if not reached & RUN_ENGINE_ENTRYPOINTS:
            continue
        own_calls = _calls(handler)
        guard_lines = [line for name, line in own_calls if name == AUTHORIZATION_GUARD]
        if not guard_lines:
            violations[tool_name] = (
                f"reaches {sorted(reached & RUN_ENGINE_ENTRYPOINTS)} without calling "
                f"{AUTHORIZATION_GUARD}"
            )
            continue
        engine_lines = [line for name, line in own_calls if name in RUN_ENGINE_ENTRYPOINTS]
        if engine_lines and min(guard_lines) > min(engine_lines):
            violations[tool_name] = f"{AUTHORIZATION_GUARD} is called after the run engine"
    return violations


def _handler_names() -> dict[str, str]:
    return {name: tool.handler.__name__ for name, tool in assistant_tools.TOOLS.items()}


def _tool_source() -> str:
    return inspect.getsource(assistant_tools)


def run_engine_exports() -> dict[str, str]:
    """Return ``{public function name: module file}`` for the run engine package.

    Read as source rather than imported: the package's modules pull Celery, the
    scheduler and the trigger registry along with them, and this check only
    needs the names they define.
    """
    root = pathlib.Path(run_engine_package.__file__).parent
    exports: dict[str, str] = {}
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and not node.name.startswith(
                "_"
            ):
                exports.setdefault(node.name, path.name)
    return exports


def uncovered_entrypoints(exports: dict[str, str]) -> dict[str, str]:
    """Return the exports that look like an entrypoint and are classified nowhere."""
    return {
        name: module
        for name, module in exports.items()
        if name.startswith(ENTRYPOINT_VERBS)
        and name not in RUN_ENGINE_ENTRYPOINTS
        and name not in NON_ENTRYPOINT_EXPORTS
    }


def test_no_assistant_tool_reaches_the_run_engine_without_the_execution_boundary() -> None:
    assert unguarded_run_engine_tools(_tool_source(), _handler_names()) == {}


def test_the_entrypoint_inventory_covers_every_run_engine_export() -> None:
    """The list the analysis matches on is recomputed, not trusted.

    The checker recognises an entrypoint by its call name, so an entrypoint the
    inventory never heard of is an entrypoint a tool could reach unguarded
    without this suite noticing. Adding one to ``app/services/run_engine``
    therefore has to be a decision taken here.
    """
    exports = run_engine_exports()
    assert "schedule_run" in exports, "the run engine package was not read at all"

    assert uncovered_entrypoints(exports) == {}, (
        "a run engine export looks like an execution entrypoint and is classified "
        "nowhere: add it to RUN_ENGINE_ENTRYPOINTS, or to NON_ENTRYPOINT_EXPORTS "
        "with the reason it reaches no execution."
    )


def test_the_inventory_check_reports_an_unclassified_entrypoint() -> None:
    """Negative control: the cross-check must not pass on an unknown entrypoint."""
    assert uncovered_entrypoints({"schedule_ghost_run": "engine.py"}) == {
        "schedule_ghost_run": "engine.py"
    }
    # A helper whose name carries no execution verb is not the subject here.
    assert uncovered_entrypoints({"delegation_key": "dag.py"}) == {}


def test_every_inventoried_run_engine_name_still_exists() -> None:
    """A renamed entrypoint leaves a name in the inventory that matches nothing.

    The names below live outside the package on purpose (the Flow ingress and the
    two Decision transitions); everything else must still be found, or the
    analysis is silently guarding against a function that is gone.
    """
    outside_the_package = {
        "accept_decision",
        "create_agentic_chat_run",
        "create_published_ingress_run",
        "reject_decision",
    }
    missing = sorted(
        (RUN_ENGINE_ENTRYPOINTS - outside_the_package) - set(run_engine_exports())
    )
    assert missing == []


def test_the_checker_rejects_a_tool_that_skips_the_execution_boundary() -> None:
    """Negative control: the analysis must fail on an unguarded tool."""
    bad_source = """
        def _dispatch(run_id):
            schedule_run(run_id)

        async def _rogue_start_run(ctx, args):
            system = ctx.db.query(System).first()
            _dispatch(system.id)
            return {"ok": True}
        """
    violations = unguarded_run_engine_tools(bad_source, {"rogue": "_rogue_start_run"})
    assert "rogue" in violations
    assert AUTHORIZATION_GUARD in violations["rogue"]


def test_the_checker_rejects_a_boundary_crossed_after_the_run_engine() -> None:
    bad_source = """
        async def _late_guard(ctx, args):
            run = create_published_ingress_run(ctx.db)
            enforce_system_engine_run(ctx.db, system=run.system)
            return {"ok": True}
        """
    violations = unguarded_run_engine_tools(bad_source, {"late": "_late_guard"})
    assert violations["late"].endswith("after the run engine")


def test_mutating_flag_matches_the_tools_that_actually_reach_the_run_engine() -> None:
    """``mutating`` is documentation the registry must not be allowed to lie about."""
    tree = ast.parse(textwrap.dedent(_tool_source()))
    functions = _module_functions(tree)
    for name, tool in assistant_tools.TOOLS.items():
        reached = {
            call
            for reachable in _reachable_functions(functions, tool.handler.__name__)
            for call, _lineno in _calls(functions[reachable])
        }
        # Proposals persist a reviewable artifact but cannot reach execution.
        persisted_artifact = bool(reached & {"create_proposal"})
        assert bool(reached & RUN_ENGINE_ENTRYPOINTS or persisted_artifact) is tool.mutating, name
        if persisted_artifact:
            assert not reached & RUN_ENGINE_ENTRYPOINTS, name
            assert "apply_proposal" not in reached, name


def test_the_tool_module_never_delegates_to_the_http_layer() -> None:
    """Calling an endpoint would move the boundary out of this analysis' reach."""
    tree = ast.parse(textwrap.dedent(_tool_source()))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    assert [module for module in imported if module.startswith("app.api")] == []


def test_every_registered_tool_declares_its_authorization_boundary() -> None:
    for name, tool in assistant_tools.TOOLS.items():
        assert tool.authorization, name
        assert tool.name == name
        assert tool.parameters.get("type") == "object", name
