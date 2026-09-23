"""One customer's nomenclature must not decide how strict another tenant is.

Workspace-fact detection matches by substring, and the Andritz list carried
three-letter series codes. For every tenant, "caractère" matched "ara" and
"avancement" matched "ava"; paired with an evidence or state term, the turn
was forced into strict source-bound grounding.
"""

from __future__ import annotations

import pytest

from app.models.workspace import Workspace
from app.services.chat_grounding import resolve_grounding_policy

BALANCED = {"chat": {"grounding": {"default_mode": "balanced", "allowed_modes": ["strict", "balanced"]}}}

FALSE_TRIGGERS = [
    "selon nos documents, quel est le caractère de cette clause ?",
    "quel est le statut actuel de l'avancement du dossier ?",
]


def _workspace(family: str) -> Workspace:
    return Workspace(
        id=f"ws-grounding-{family}",
        name=family,
        slug=f"grounding-{family}",
        settings={"family": family, **BALANCED},
    )


@pytest.mark.parametrize("query", FALSE_TRIGGERS)
@pytest.mark.parametrize("family", ["generic", "industrial", "sentinel_ci"])
def test_ordinary_words_no_longer_force_a_third_tenant_into_strict(family, query):
    policy = resolve_grounding_policy(query=query, workspace=_workspace(family))
    assert policy["mode"] == "balanced"


@pytest.mark.parametrize("query", FALSE_TRIGGERS)
def test_the_andritz_tenant_keeps_its_behaviour(query):
    """Unchanged for the customer whose list it is, false positives included:
    fixing those is that tenant's question, not this one."""

    policy = resolve_grounding_policy(query=query, workspace=_workspace("andritz"))
    assert policy["mode"] == "strict"


def test_an_andritz_series_code_is_meaningless_elsewhere():
    query = "selon nos documents, statut de la série BBA120"
    assert resolve_grounding_policy(query=query, workspace=_workspace("generic"))["mode"] == "balanced"
    assert resolve_grounding_policy(query=query, workspace=_workspace("andritz"))["mode"] == "strict"


REPORT_QUERY = "selon nos documents, que dit le rapport actuel ?"


@pytest.mark.parametrize("family", ["generic", "industrial"])
def test_the_sentinel_domain_no_longer_decides_for_other_tenants(family):
    """"port" is a Sentinel term, and it sits inside "rapport"."""

    assert resolve_grounding_policy(query=REPORT_QUERY, workspace=_workspace(family))["mode"] == "balanced"


@pytest.mark.parametrize("family", ["sentinel_ci", "andritz"])
def test_the_tenants_that_had_the_sentinel_list_keep_it(family):
    assert resolve_grounding_policy(query=REPORT_QUERY, workspace=_workspace(family))["mode"] == "strict"


def test_platform_vocabulary_still_grounds_every_tenant():
    query = "selon nos documents, quelle est la décision actuelle ?"
    for family in ("generic", "industrial", "sentinel_ci", "andritz"):
        assert resolve_grounding_policy(query=query, workspace=_workspace(family))["mode"] == "strict", family
