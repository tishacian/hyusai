"""A workspace that is not industrial must not answer like one.

The industrial answer policy (project summaries, cross-project inventories,
equipment detail) was reachable from every workspace in two ways: chat and the
policy helpers fell back to it when no contract said otherwise, and the intent
classifier returned industrial profiles whatever policy it was given. The
second was the sharper one: a domain-neutral workspace asking about "projects"
was classified as a cross-project inventory and forced into exhaustive deep
retrieval, even with the neutral policy correctly seeded.
"""

from __future__ import annotations

import pytest

from app.api.v1.endpoints.chat import ChatRequest, _apply_workspace_chat_flow_defaults
from app.models.workspace import Workspace
from app.services.industrial_answer_profile import (
    answer_policy_for_family,
    answer_policy_prompt,
    default_answer_policy,
    industrial_answer_policy,
    resolve_answer_profile,
)
from app.services.skills_registry.seed import seed_skills_and_capabilities
from app.services.systems.bootstrap import ensure_workspace_chat_system_default

NEUTRAL = default_answer_policy()
INDUSTRIAL = industrial_answer_policy()


@pytest.mark.parametrize(
    "family,key",
    [
        ("andritz", "industrial_answer_profile_v1"),
        ("industrial", "industrial_answer_profile_v1"),
        ("generic", "default_answer_profile_v1"),
        ("sentinel_ci", "default_answer_profile_v1"),
        (None, "default_answer_profile_v1"),
    ],
)
def test_one_rule_decides_the_default_policy(family, key):
    assert answer_policy_for_family(family)["key"] == key


@pytest.mark.parametrize(
    "query",
    [
        "Quels projets utilisent une pompe Uraca ?",
        "inventaire de tous les projets avec un cabinet pneumatique",
    ],
)
def test_a_neutral_policy_is_never_pushed_into_exhaustive_retrieval(query):
    decision = resolve_answer_profile(query, NEUTRAL)
    assert decision.requires_exhaustive_retrieval is False
    assert decision.profile in NEUTRAL["profiles"]


def test_a_neutral_policy_only_ever_returns_profiles_it_offers():
    offered = set(NEUTRAL["profiles"])
    for query in [
        "résume le dossier Martin",
        "compare les deux offres",
        "quelle est la référence de la pièce KD724 ?",
        "Quels projets utilisent une pompe Uraca ?",
        "bonjour",
    ]:
        assert resolve_answer_profile(query, NEUTRAL, include_agentic_profiles=True).profile in offered


def test_a_summary_request_is_a_summary_in_any_workspace():
    assert resolve_answer_profile("résume le dossier Martin", NEUTRAL).profile == "summary"


def test_the_industrial_policy_is_unchanged():
    """The customer that opted in keeps exactly what it had."""

    decision = resolve_answer_profile("Quels projets utilisent une pompe Uraca ?", INDUSTRIAL)
    assert decision.profile == "transversal_inventory"
    assert decision.requires_exhaustive_retrieval is True


def test_the_policy_helpers_default_to_neutral():
    prompt = answer_policy_prompt(
        answer_policy=None, profile_decision={"profile": "precise_fact"}
    )
    neutral = answer_policy_prompt(
        answer_policy=NEUTRAL, profile_decision={"profile": "precise_fact"}
    )
    assert prompt == neutral


def test_a_seeded_generic_workspace_is_not_forced_into_deep_retrieval(db_session):
    """The realistic path, not a unit of it.

    Bootstrap seeded the neutral policy correctly for this workspace, and it
    still went deep, because the classifier ignored the policy it was given.
    """

    workspace = Workspace(
        id="ws-generic-neutral",
        name="Cabinet Juridique",
        slug="cabinet-juridique",
        settings={"family": "generic"},
    )
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)
    ensure_workspace_chat_system_default(db_session, workspace.id)

    request = ChatRequest(query="Quels projets utilisent une pompe Uraca ?")
    _apply_workspace_chat_flow_defaults(db_session, workspace=workspace, request=request)

    assert request.answer_policy["key"] == "default_answer_profile_v1"
    assert request.answer_profile != "transversal_inventory"
    assert request.deep_retrieval is not True
    assert request.latency_profile != "deep"
