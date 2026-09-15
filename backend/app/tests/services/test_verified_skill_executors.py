"""What a workspace-defined Skill is allowed to execute, and how it fails.

Before this tranche there was no parameterisable runtime at all: ``_REGISTRY``
is a hardcoded dict and ``resolve()`` handed back a callable that only raised
once awaited, so an unbound Skill looked like a node the walker had already
committed to running. Both halves are pinned here: the closed executor set that
replaces "bring your own code", and resolution that refuses rather than
degrades.
"""
from __future__ import annotations

import pytest

from app.models.skill import Skill
from app.services.skills_registry import wrappers
from app.services.skills_registry.binding import SkillBindingError
from app.services.skills_registry.executors import (
    VERIFIED_EXECUTORS,
    bind_executor,
    validate_executor_binding,
    verified_executor_catalog,
)
from app.services.skills_registry.workspace_skills import workspace_skill_callable


@pytest.fixture
def recorded(monkeypatch) -> list[dict]:
    """Replace one seeded wrapper so binding is observable without a provider."""

    calls: list[dict] = []

    async def _capture(payload, ctx=None):
        calls.append(dict(payload))
        return {"ok": True}

    for slug in ("audit_log_v1", "ollama_llm_v1"):
        entry = wrappers._REGISTRY[slug]
        monkeypatch.setitem(wrappers._REGISTRY, slug, (_capture, entry[1], entry[2]))
    return calls


def _authored(db, *, executor, slug="ws.ws-exec.custom_op", workspace_id="ws-exec"):
    row = Skill(
        id=f"skill-{slug}",
        workspace_id=workspace_id,
        slug=slug,
        name="Custom op",
        type="generic",
        executor=executor,
        is_seeded="N",
    )
    db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------------------
# resolve() is fail-closed
# ---------------------------------------------------------------------------
def test_an_unbound_seeded_slug_fails_at_resolution_not_at_invocation():
    with pytest.raises(NotImplementedError):
        wrappers.resolve("no_such_skill_v1")


def test_a_workspace_slug_reaching_the_seeded_resolver_is_a_loud_failure():
    """It must not read as "nothing declared".

    An authored Skill's runtime lives on its row. A caller that skipped executor
    resolution has a dispatch bug, and ``NotImplementedError`` would have the
    walker record a *skipped* node -- the quiet outcome this tranche removes.
    """

    with pytest.raises(SkillBindingError) as refused:
        wrappers.resolve("ws.ws-exec.custom_op")

    assert refused.value.code == "workspace_skill_requires_executor"
    assert not isinstance(refused.value, NotImplementedError)


def test_no_executor_returns_a_degraded_stand_in():
    """Every rejection path raises; none yields a callable that fakes a result."""

    for binding in (
        None,
        {},
        "registry_call",
        {"kind": "exec_shell"},
        {"kind": "registry_call"},
        {"kind": "registry_call", "params": {"skill_slug": "no_such_skill_v1"}},
        {"kind": "prompt_template", "params": {"provider": "ollama"}},
    ):
        with pytest.raises(SkillBindingError):
            bind_executor(binding)


def test_a_kind_is_a_key_and_never_an_import_path():
    """The property that keeps authoring out of code execution."""

    for kind in (
        "app.services.skills_registry.wrappers._stub",
        "os.system",
        "builtins.eval",
        "../wrappers",
    ):
        with pytest.raises(SkillBindingError) as refused:
            validate_executor_binding({"kind": kind, "params": {}})
        assert refused.value.code == "executor_kind_unknown"


def test_every_verified_executor_closes_its_parameter_object():
    """A closed params_schema is what makes the binding safe to serialise.

    ``/skills`` returns the binding to every member. With
    ``additionalProperties`` open, an admin could park arbitrary content -- a
    token, a URL -- in a field nobody reviewed, and the catalog would publish it.
    """

    for executor in VERIFIED_EXECUTORS.values():
        assert executor.params_schema["additionalProperties"] is False, executor.kind
        assert executor.params_schema["type"] == "object", executor.kind

    assert [item["kind"] for item in verified_executor_catalog()] == sorted(
        VERIFIED_EXECUTORS
    )


# ---------------------------------------------------------------------------
# registry_call
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_pinned_parameters_win_over_the_run(recorded):
    """Frozen means frozen: a run cannot substitute its own value for one the
    workspace pinned, or the parameters would be a default rather than policy."""

    call = bind_executor(
        {
            "kind": "registry_call",
            "params": {
                "skill_slug": "audit_log_v1",
                "frozen_input": {"event_type": "pinned", "severity": "warning"},
            },
        }
    )

    await call({"event_type": "attacker_supplied", "details": {"a": 1}}, {})

    assert recorded == [
        {"event_type": "pinned", "severity": "warning", "details": {"a": 1}}
    ]


def test_an_authored_skill_cannot_chain_onto_another_authored_skill():
    """Otherwise a workspace composes a call graph the verified set never saw,
    and can close a cycle the resolver would follow."""

    with pytest.raises(SkillBindingError) as refused:
        bind_executor(
            {
                "kind": "registry_call",
                "params": {"skill_slug": "ws.ws-exec.other_op"},
            }
        )
    assert refused.value.code == "executor_target_not_seeded"


# ---------------------------------------------------------------------------
# prompt_template
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_template_is_filled_from_the_run(recorded):
    call = bind_executor(
        {
            "kind": "prompt_template",
            "params": {
                "provider": "ollama",
                "template": "Summarise {ticket} for {audience}.",
            },
        }
    )

    await call({"ticket": "INC-1", "audience": "the duty manager"}, {})

    assert recorded == [{"prompt": "Summarise INC-1 for the duty manager."}]


@pytest.mark.asyncio
async def test_a_placeholder_cannot_walk_the_object_graph(recorded):
    """``str.format`` would resolve ``{x.__class__}`` and friends.

    The template is admin-authored but the *values* arrive from upstream node
    output, so the substitution is attacker-reachable. Anything that is not a
    flat declared name stays literal text.
    """

    call = bind_executor(
        {
            "kind": "prompt_template",
            "params": {
                "provider": "ollama",
                "template": "{ticket.__class__.__init__.__globals__} {0} {ticket[0]}",
            },
        }
    )

    await call({"ticket": "INC-1"}, {})

    assert recorded == [
        {"prompt": "{ticket.__class__.__init__.__globals__} {0} {ticket[0]}"}
    ]


@pytest.mark.asyncio
async def test_a_missing_placeholder_fails_rather_than_sending_a_hole(recorded):
    call = bind_executor(
        {
            "kind": "prompt_template",
            "params": {"provider": "ollama", "template": "Summarise {ticket}."},
        }
    )

    with pytest.raises(SkillBindingError) as refused:
        await call({"unrelated": 1}, {})

    assert refused.value.code == "prompt_input_missing"
    assert recorded == []


@pytest.mark.asyncio
async def test_an_input_model_overrides_the_executor_pin(recorded):
    """The engine resolves both values before checking the effective model."""

    assert "model" in VERIFIED_EXECUTORS["prompt_template"].params_schema["properties"]

    call = bind_executor(
        {
            "kind": "prompt_template",
            "params": {"provider": "ollama", "model": "qwen3:8b", "template": "Hi {name}."},
        }
    )
    await call({"name": "Sam", "model": "mistral:7b"}, {})

    assert recorded == [{"prompt": "Hi Sam.", "model": "mistral:7b"}]


# ---------------------------------------------------------------------------
# Slug-directed dispatch
# ---------------------------------------------------------------------------
def test_a_seeded_slug_needs_no_row_lookup(db_session):
    """The namespace is a routing decision, so the seeded catalog pays nothing.

    ``workspace_skill_callable`` returning ``None`` on a string test is what
    keeps this tranche off the run engine's hot path.
    """

    assert (
        workspace_skill_callable(db_session, workspace_id="ws-exec", slug="audit_log_v1")
        is None
    )


def test_an_authored_slug_resolves_to_its_binding(db_session, recorded):
    _authored(
        db_session,
        executor={"kind": "registry_call", "params": {"skill_slug": "audit_log_v1"}},
    )

    resolved = workspace_skill_callable(
        db_session,
        workspace_id="ws-exec",
        slug="ws.ws-exec.custom_op",
    )

    assert callable(resolved)


@pytest.mark.parametrize(
    ("workspace_id", "slug", "code"),
    [
        ("ws-exec", "ws.ws-exec.absent_op", "skill_not_found"),
        ("ws-other", "ws.ws-exec.custom_op", "skill_slug_foreign_workspace"),
        (None, "ws.ws-exec.custom_op", "skill_slug_foreign_workspace"),
        ("ws-exec", "ws.ws-exec.NOPE", "skill_slug_malformed"),
    ],
)
def test_dispatch_never_falls_back_to_the_global_catalog(
    db_session, workspace_id, slug, code
):
    """A deleted, foreign or malformed authored slug must not be answered by
    whatever the seeded registry happens to hold under a similar name."""

    _authored(
        db_session,
        executor={"kind": "registry_call", "params": {"skill_slug": "audit_log_v1"}},
    )

    with pytest.raises(SkillBindingError) as refused:
        workspace_skill_callable(db_session, workspace_id=workspace_id, slug=slug)
    assert refused.value.code == code


def test_a_row_whose_binding_stopped_being_verifiable_fails_at_resolution(db_session):
    """The binding is re-verified on every resolution, not trusted because it
    was accepted once: the executor set can retire a kind, and a row written
    before that must stop resolving rather than resolve to something else."""

    _authored(db_session, executor={"kind": "retired_kind", "params": {}})

    with pytest.raises(SkillBindingError) as refused:
        workspace_skill_callable(
            db_session,
            workspace_id="ws-exec",
            slug="ws.ws-exec.custom_op",
        )
    assert refused.value.code == "executor_kind_unknown"
