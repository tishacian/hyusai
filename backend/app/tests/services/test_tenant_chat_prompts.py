"""The grounded-answer and agentic-chat prompts speak for the workspace's own family.

``llm_rag_answer_v1`` is a shared skill: any Flow that wires retrieved context
into it used to get an Andritz technical-assistant persona and an Andritz
notion of "out of scope". The fragments now come from ``app.tenants.andritz``
for that family only. The Andritz prompts must not move by a single byte:
the fixture was captured from the code before the change.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.models.workspace import Workspace
from app.services.skills_registry import wrappers as w

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "tenant_prompts" / "andritz_chat_prompts.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES["grounded"], ids=lambda c: c["args"][0][:24])
def test_andritz_grounded_prompt_is_unchanged(case):
    assert w._build_grounded_answer_prompt(*case["args"], family="andritz") == case["expected"]


@pytest.mark.parametrize("case", CASES["plan"], ids=lambda c: c["args"][0][:24])
def test_andritz_plan_prompt_is_unchanged(case):
    assert w._build_plan_prompt(*case["args"], family="andritz") == case["expected"]


@pytest.mark.parametrize("case", CASES["self_correct"], ids=lambda c: c["args"][2])
def test_andritz_self_correct_prompt_is_unchanged(case):
    assert w._build_self_correct_prompt(*case["args"], family="andritz") == case["expected"]


def test_andritz_out_of_scope_reason_is_unchanged():
    (case,) = CASES["coerce_oos"]
    plan = w._coerce_plan(*case["args"], has_history=False, known_project_codes=[], family="andritz")
    assert plan == case["expected"]


@pytest.mark.parametrize("family", ["generic", "industrial", "sentinel_ci"])
def test_other_families_get_no_andritz_wording(family):
    grounded = CASES["grounded"][0]["args"]
    plan = CASES["plan"][1]["args"]
    prompts = [
        w._build_grounded_answer_prompt(*grounded, family=family),
        w._build_plan_prompt(*plan, family=family),
        *(
            w._build_self_correct_prompt(*case["args"], family=family)
            for case in CASES["self_correct"]
        ),
    ]
    for prompt in prompts:
        # The framing only: the context and history sections quote the inputs.
        framing = prompt.split("Contexte:")[0].split("Historique:")[0]
        assert "Andritz" not in framing
        assert "URACA" not in framing and "Arbeitsbreite" not in framing
    oos = w._coerce_plan({"action": "reject_oos"}, "x", family=family)["oos_reason"]
    assert oos == "Hors du perimetre de ce workspace."


def test_the_rules_are_shared_only_the_framing_differs():
    args = CASES["grounded"][0]["args"]
    andritz = w._build_grounded_answer_prompt(*args, family="andritz")
    generic = w._build_grounded_answer_prompt(*args, family="generic")
    rules = andritz[andritz.index("Cite chaque fait"):]
    assert generic.endswith(rules)


def test_the_family_comes_from_ctx_or_from_the_workspace_row(db_session):
    assert w._ctx_workspace_family({"workspace_family": "andritz"}) == "andritz"
    assert w._ctx_workspace_family({}) == "generic"
    assert w._ctx_workspace_family(None) == "generic"

    workspace = Workspace(
        id=str(uuid4()), name="Stamped", slug=f"stamped-{uuid4().hex[:6]}", settings={"family": "andritz"}
    )
    db_session.add(workspace)
    db_session.commit()
    ctx = {"workspace_id": workspace.id, "db": db_session}
    assert w._ctx_workspace_family(ctx) == "andritz"
    assert ctx["workspace_family"] == "andritz"  # cached for the next skill
