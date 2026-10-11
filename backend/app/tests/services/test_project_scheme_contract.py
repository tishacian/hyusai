"""The contract ADR 0002 rests on, stated as tests rather than as prose.

Two properties matter and neither is about the parser being correct when it is
called correctly. The first is that a third tenant never gets an Andritz
identifier. The second is that a call site which forgets to bind a scheme is
reported, because failing closed is silent and it degrades Andritz, not the
tenant it protects.
"""

from __future__ import annotations

import pytest

from app.services.rag import project_references as pr
from app.services.rag.project_references import (
    bind_project_reference_scheme,
    derive_project_reference,
    extract_query_project_codes,
    project_reference_scheme,
    using_workspace_project_scheme,
)


class _Workspace:
    def __init__(self, slug: str, settings: dict | None):
        self.id = f"ws-{slug}"
        self.slug = slug
        self.name = slug
        self.settings = settings


# ADR 0002 D6: these must not produce a project code for a third tenant.
OUT_OF_SCOPE = [
    ("line position", "la toile du convoyeur J1 et la station C1"),
    ("machine brands", "la pompe Uraca du Jetlace"),
    ("generic technical pattern", "reference AVA200 du schema"),
    ("part number", "piece ABC1234 du catalogue"),
    ("norm reference", "conforme a la norme ISO9001"),
    ("french prose with a count", "a remplacer tous les 16 000 heures"),
]


@pytest.mark.parametrize("label,text", OUT_OF_SCOPE, ids=[c[0] for c in OUT_OF_SCOPE])
def test_no_third_tenant_ever_gets_a_project_code(label, text):
    del label
    for family in ("generic", "industrial", "sentinel_ci"):
        workspace = _Workspace("acme", {"family": family})
        with using_workspace_project_scheme(workspace):
            assert (derive_project_reference(text) or {}).get("project_code") is None
            assert extract_query_project_codes(text) == []


def test_an_andritz_token_is_inert_outside_andritz():
    """The witness case: the grammar itself, on a tenant that is not Andritz."""

    workspace = _Workspace("acme", {"family": "industrial"})
    with using_workspace_project_scheme(workspace):
        assert (derive_project_reference("Manual_BBA120.zip") or {}).get("project_code") is None
        assert extract_query_project_codes("resume le projet 61038") == []


def test_the_same_token_still_parses_inside_andritz():
    """And the customer who pays for it keeps exactly what it had."""

    workspace = _Workspace("andritz", {"family": "andritz"})
    with using_workspace_project_scheme(workspace):
        parsed = derive_project_reference("Manual_BBA120.zip") or {}
        assert parsed.get("project_code") == "BBA120"
        assert parsed.get("project_reference_kind") == "andritz_project"


def test_the_slug_alone_never_arms_the_grammar():
    """Only the stamp counts; a slug is mutable and must not carry meaning."""

    assert project_reference_scheme(_Workspace("andritz", {})) == ""
    assert project_reference_scheme(_Workspace("andritz", None)) == ""
    assert project_reference_scheme(_Workspace("andritz-nonwovens", {"family": "industrial"})) == ""
    assert project_reference_scheme(_Workspace("whatever", {"family": "andritz"})) == "andritz"


def test_a_call_site_that_forgets_to_bind_is_counted():
    """Failing closed is right, and silent. The count is what makes it alertable."""

    pr.reset_project_reference_unbound_calls()
    assert pr.project_reference_unbound_calls() == 0

    # No bind anywhere: this is the bug shape, not a legitimate third tenant.
    assert (derive_project_reference("Manual_BBA120.zip") or {}).get("project_code") is None
    assert pr.project_reference_unbound_calls() == 1


def test_a_bound_non_andritz_tenant_is_not_reported():
    """The normal case must stay quiet, or the signal is worthless."""

    pr.reset_project_reference_unbound_calls()
    with using_workspace_project_scheme(_Workspace("acme", {"family": "generic"})):
        derive_project_reference("Manual_BBA120.zip")
        extract_query_project_codes("projet 61038")
    assert pr.project_reference_unbound_calls() == 0

    pr.reset_project_reference_unbound_calls()
    with bind_project_reference_scheme(""):
        derive_project_reference("Manual_BBA120.zip")
    assert pr.project_reference_unbound_calls() == 0


def test_an_explicit_scheme_argument_is_never_reported():
    pr.reset_project_reference_unbound_calls()
    derive_project_reference("Manual_BBA120.zip", scheme="")
    derive_project_reference("Manual_BBA120.zip", scheme="andritz")
    assert pr.project_reference_unbound_calls() == 0


def test_the_chat_router_binds_in_a_form_that_actually_reaches_the_endpoint():
    """The bind must be an async generator, and this is not a style rule.

    FastAPI runs a sync generator dependency through a threadpool: the
    ContextVar is set in one worker thread and reset in another, so the
    endpoint never observes it and the teardown raises "Token was created in a
    different Context". The bind silently does nothing, which turns the Andritz
    grammar off across the whole chat surface while every test that calls the
    parser directly keeps passing.
    """

    import inspect

    from app.api.v1.endpoints.chat import _bind_workspace_project_scheme

    assert inspect.isasyncgenfunction(_bind_workspace_project_scheme), (
        "a sync generator dependency binds the ContextVar in a worker thread "
        "and the endpoint never sees it"
    )


def test_a_sync_generator_dependency_really_does_lose_the_bind():
    """Pin the platform behaviour the test above defends against."""

    from contextvars import ContextVar

    from fastapi import APIRouter, Depends, FastAPI
    from fastapi.testclient import TestClient

    probe: ContextVar[str] = ContextVar("probe", default="UNBOUND")

    def sync_bind():
        token = probe.set("BOUND")
        try:
            yield
        finally:
            probe.reset(token)

    async def async_bind():
        token = probe.set("BOUND")
        try:
            yield
        finally:
            probe.reset(token)

    def seen_by_endpoint(dependency) -> str:
        app = FastAPI()
        router = APIRouter(dependencies=[Depends(dependency)])

        @router.get("/probe")
        async def _probe():
            return {"seen": probe.get()}

        app.include_router(router)
        client = TestClient(app, raise_server_exceptions=False)
        return client.get("/probe").json()["seen"]

    assert seen_by_endpoint(sync_bind) == "UNBOUND"
    assert seen_by_endpoint(async_bind) == "BOUND"
