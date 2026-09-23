"""Scripted demo skills answer for their own family only.

``draft_email_v1``, ``generate_recommendations_v1`` and
``summarize_long_document_v1`` read as generic catalogue entries, but they
returned the Sentinel CI scenario (customs letters for the Vice Prime
Minister, cocoa options, the Nawa prefect report) to whichever workspace
called them.
"""

from __future__ import annotations

import pytest

from app.services.skills_registry import wrappers as w

SKILLS = [
    (w._draft_email_v1, {"template_kind": "customs_priority"}),
    (w._generate_recommendations_v1, {"topic": "cacao_diversification"}),
    (w._summarize_long_document_v1, {"document_id": "doc-1"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("skill,payload", SKILLS, ids=lambda v: getattr(v, "__name__", ""))
@pytest.mark.parametrize("family", ["generic", "industrial", "andritz"])
async def test_other_families_are_told_the_skill_is_unavailable(skill, payload, family):
    result = await skill(payload, {"workspace_family": family})
    assert result["status"] == "unavailable"
    assert result["error"] == "demo_skill_outside_its_family"


@pytest.mark.asyncio
async def test_the_sentinel_ci_family_keeps_its_scenario():
    ctx = {"workspace_family": "sentinel_ci"}
    email = await w._draft_email_v1({"template_kind": "customs_priority"}, ctx)
    assert email["status"] == "draft"
    assert email["subject"].startswith("Priorisation dedouanement")

    options = await w._generate_recommendations_v1({"topic": "cacao_diversification"}, ctx)
    assert options["status"] == "ready" and len(options["options"]) == 3

    summary = await w._summarize_long_document_v1({}, ctx)
    assert summary["citations"][0]["document_id"] == "report-prefet-nawa-2026-05-10"


@pytest.mark.asyncio
async def test_a_call_without_any_workspace_is_refused_rather_than_guessed():
    result = await w._draft_email_v1({"template_kind": "customs_priority"}, None)
    assert result["status"] == "unavailable"
