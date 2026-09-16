"""L0 — decide_next_v1 coerce, allowlist prompt, overlay Password Reset."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.chains.dag_validator import validate_flow
from app.services.run_engine.agent_loop import coerce_decide_output
from app.services.run_engine.dag import should_use_dag
from app.services.skills_registry import wrappers
from app.services.skills_registry.seed import SEED_SKILLS, SKILL_CATEGORIES
from app.models.system import System

ARTIFACT = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "resources"
        / "flows"
        / "nawa_password_reset_agent_loop_v1.json"
    ).read_text(encoding="utf-8")
)

VISIBLE = [
    {
        "slug": "azure_llm_v1",
        "purpose": "Classify ITSD intent",
        "side_effect_class": "read",
        "privilege_tier": "recommend",
    },
    {
        "slug": "audit_log_v1",
        "purpose": "Write audit ledger",
        "side_effect_class": "write",
        "privilege_tier": "act_with_approval",
    },
]


def test_seed_and_wrapper_are_registered():
    by_slug = {entry["slug"]: entry for entry in SEED_SKILLS}
    assert "decide_next_v1" in by_slug
    assert SKILL_CATEGORIES["decide_next_v1"] == "Decision Support"
    assert wrappers.runtime_status("decide_next_v1") == "bound"


def test_coerce_rejects_slug_outside_allowlist():
    out = coerce_decide_output(
        {
            "next_skill": "rpa_dispatch_v1",
            "rationale": "reset now",
            "confidence": 0.9,
        },
        VISIBLE,
    )
    assert out["exit"] == "policy_block"
    assert out["next_skill"] is None
    assert out["done"] is False


def test_coerce_unreadable_json_blocks():
    out = coerce_decide_output("not-json", VISIBLE)
    assert out["next_skill"] is None
    assert out["confidence"] == 0
    assert out["needs_human"] is True
    assert out["exit"] == "ask_human"


def test_coerce_low_confidence_forces_human():
    out = coerce_decide_output(
        {
            "next_skill": "azure_llm_v1",
            "rationale": "maybe classify",
            "confidence": 0.2,
        },
        VISIBLE,
        confidence_floor=0.55,
    )
    assert out["needs_human"] is True
    assert out["exit"] == "ask_human"
    assert out["human_prompt"]


@pytest.mark.asyncio
async def test_wrapper_prompt_contains_only_allowlisted_slugs(monkeypatch):
    recorded: dict = {}

    async def fake_complete(prompt, model, ctx, **kwargs):
        recorded["prompt"] = prompt
        return json.dumps(
            {
                "next_skill": "azure_llm_v1",
                "rationale": "classify first",
                "confidence": 0.8,
                "needs_human": False,
                "exit": None,
                "done": False,
            }
        )

    monkeypatch.setattr(wrappers, "_route_llm_complete", fake_complete)
    out = await wrappers._decide_next_v1(
        {
            "goal": {"objective": "reset password", "done_when": ["audit_log_v1"]},
            "observations": [],
            "visible_skills": VISIBLE,
            "budget": {"turns_left": 4},
        },
        {},
    )
    prompt = recorded["prompt"]
    assert "azure_llm_v1" in prompt
    assert "audit_log_v1" in prompt
    assert "rpa_dispatch_v1" not in prompt
    assert "exec" not in prompt
    assert out["next_skill"] == "azure_llm_v1"


@pytest.mark.asyncio
async def test_wrapper_garbage_completion_blocks(monkeypatch):
    async def fake_complete(prompt, model, ctx, **kwargs):
        return "sorry I cannot"

    monkeypatch.setattr(wrappers, "_route_llm_complete", fake_complete)
    out = await wrappers._decide_next_v1({"visible_skills": VISIBLE}, {})
    assert out["next_skill"] is None
    assert out["needs_human"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(("raw", "reasons", "expected_exit", "expected_human"), [
    ({"next_skill": "azure_llm_v1", "confidence": 0.54, "needs_human": False,
      "exit": None, "done": False}, ["confidence_below_floor"], "ask_human", True),
    ({"next_skill": "azure_llm_v1", "confidence": 0.54, "needs_human": True,
      "exit": None, "done": False}, ["model_requested_human"], "ask_human", True),
    ({"next_skill": "rpa_dispatch_v1", "confidence": 0.9, "needs_human": False,
      "exit": None, "done": False}, ["skill_outside_allowlist"], "policy_block", False),
    ({"next_skill": "azure_llm_v1", "confidence": 0.55, "needs_human": False,
      "exit": None, "done": False}, [], None, False),
])
async def test_wrapper_records_decision_provenance_without_changing_output(
    monkeypatch, raw, reasons, expected_exit, expected_human,
):
    async def fake_complete(prompt, model, ctx, **kwargs):
        return json.dumps({**raw, "rationale": "private model rationale", "human_prompt": "private question"})

    monkeypatch.setattr(wrappers, "_route_llm_complete", fake_complete)
    ctx = {}
    out = await wrappers._decide_next_v1({"visible_skills": VISIBLE}, ctx)

    evidence = ctx["_agent_loop_decision_evidence"]
    expected_raw = dict(raw)
    if raw["next_skill"] == "rpa_dispatch_v1":
        expected_raw["next_skill"] = {"omitted_type": "string", "reason": "not_visible_skill"}
    assert evidence["raw"] == expected_raw
    assert evidence["confidence_floor"] == 0.55
    assert evidence["normalization_reasons"] == reasons
    assert evidence["effective"] == {key: out[key] for key in raw}
    assert out["exit"] == expected_exit
    assert out["needs_human"] is expected_human
    assert set(out) == {"next_skill", "rationale", "confidence", "needs_human", "human_prompt", "exit", "done"}
    assert "private" not in json.dumps(evidence)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["json_parse_failure", "llm_failure"])
async def test_wrapper_records_failure_origin_without_completion_or_error_text(monkeypatch, failure):
    async def fake_complete(prompt, model, ctx, **kwargs):
        if failure == "llm_failure":
            raise RuntimeError("private provider failure")
        return "private invalid completion"

    monkeypatch.setattr(wrappers, "_route_llm_complete", fake_complete)
    ctx = {}
    out = await wrappers._decide_next_v1({"visible_skills": VISIBLE}, ctx)

    evidence = ctx["_agent_loop_decision_evidence"]
    assert evidence["raw"] == {}
    assert evidence["normalization_reasons"] == [failure, "confidence_normalized", "confidence_below_floor"]
    assert evidence["effective"]["needs_human"] is True
    assert out == coerce_decide_output({}, VISIBLE)
    assert "private" not in json.dumps(evidence)


def test_decision_provenance_bounds_invalid_values_and_remains_json_serializable():
    evidence = {}
    coerce_decide_output({"next_skill": "x" * 1000, "confidence": float("nan"),
                         "needs_human": {"private": "nested content"}, "done": ["private"],
                         "exit": "unsupported", "rationale": "private rationale"},
                        VISIBLE, evidence=evidence)
    assert evidence["raw"]["next_skill"] == {"omitted_type": "string", "reason": "not_visible_skill"}
    assert evidence["raw"]["confidence"] == {"omitted_type": "number", "reason": "invalid_number"}
    assert evidence["raw"]["needs_human"] == {"omitted_type": "object", "reason": "invalid_type"}
    assert evidence["raw"]["done"] == {"omitted_type": "array", "reason": "invalid_type"}
    assert "private" not in json.dumps(evidence, allow_nan=False)


@pytest.mark.parametrize("field", ["next_skill", "confidence", "needs_human", "exit", "done"])
def test_decision_provenance_omits_prose_even_in_scalar_fields(field):
    raw = {"next_skill": "azure_llm_v1", "confidence": 0.9,
           "needs_human": False, "exit": None, "done": False}
    raw[field] = "private_provider_content"
    evidence = {}
    original = coerce_decide_output(raw, VISIBLE)
    assert coerce_decide_output(raw, VISIBLE, evidence=evidence) == original
    assert evidence["raw"][field]["omitted_type"] == "string"
    assert "private_provider_content" not in json.dumps(evidence, allow_nan=False)


def test_overlay_has_no_validator_errors():
    errors = [
        issue.to_dict()
        for issue in validate_flow(ARTIFACT["overlay_decide"])
        if issue.level == "error"
    ]
    assert errors == [], errors
    assert should_use_dag(System(flow_definition=ARTIFACT["overlay_decide"])) is True


def test_overlay_does_not_rewrite_password_reset_seed():
    production = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "resources"
            / "flows"
            / "nawa_password_reset_v1.json"
        ).read_text(encoding="utf-8")
    )
    assert production["artifact"] == "nawa_password_reset_v1"
    assert "decide_next_v1" not in json.dumps(production["flow_definition"])
