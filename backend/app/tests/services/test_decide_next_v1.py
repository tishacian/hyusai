"""L0 — decide_next_v1 coerce, allowlist prompt, overlay Password Reset."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models.system import System
from app.services.chains.dag_validator import validate_flow
from app.services.run_engine.agent_loop import build_decision_context, coerce_decide_output
from app.services.run_engine.dag import should_use_dag
from app.services.skills_registry import wrappers
from app.services.skills_registry.seed import SEED_SKILLS, SKILL_CATEGORIES

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

    monkeypatch.setattr(wrappers.skills, "_route_llm_complete", fake_complete)
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

    monkeypatch.setattr(wrappers.skills, "_route_llm_complete", fake_complete)
    out = await wrappers._decide_next_v1({"visible_skills": VISIBLE}, {})
    assert out["next_skill"] is None
    assert out["needs_human"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw", "reasons", "expected_exit", "expected_human"),
    [
        (
            {
                "next_skill": "azure_llm_v1",
                "confidence": 0.54,
                "needs_human": False,
                "exit": None,
                "done": False,
            },
            ["confidence_below_floor"],
            "ask_human",
            True,
        ),
        (
            {
                "next_skill": "azure_llm_v1",
                "confidence": 0.54,
                "needs_human": True,
                "exit": None,
                "done": False,
            },
            ["model_requested_human"],
            "ask_human",
            True,
        ),
        (
            {
                "next_skill": "rpa_dispatch_v1",
                "confidence": 0.9,
                "needs_human": False,
                "exit": None,
                "done": False,
            },
            ["skill_outside_allowlist"],
            "policy_block",
            False,
        ),
        (
            {
                "next_skill": "azure_llm_v1",
                "confidence": 0.55,
                "needs_human": False,
                "exit": None,
                "done": False,
            },
            [],
            None,
            False,
        ),
    ],
)
async def test_wrapper_records_decision_provenance_without_changing_output(
    monkeypatch,
    raw,
    reasons,
    expected_exit,
    expected_human,
):
    async def fake_complete(prompt, model, ctx, **kwargs):
        return json.dumps(
            {**raw, "rationale": "private model rationale", "human_prompt": "private question"}
        )

    monkeypatch.setattr(wrappers.skills, "_route_llm_complete", fake_complete)
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
    assert set(out) == {
        "next_skill",
        "rationale",
        "confidence",
        "needs_human",
        "human_prompt",
        "exit",
        "done",
    }
    assert "private" not in json.dumps(evidence)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["json_parse_failure", "llm_failure"])
async def test_wrapper_records_failure_origin_without_completion_or_error_text(
    monkeypatch, failure
):
    async def fake_complete(prompt, model, ctx, **kwargs):
        if failure == "llm_failure":
            raise RuntimeError("private provider failure")
        return "private invalid completion"

    monkeypatch.setattr(wrappers.skills, "_route_llm_complete", fake_complete)
    ctx = {}
    out = await wrappers._decide_next_v1({"visible_skills": VISIBLE}, ctx)

    evidence = ctx["_agent_loop_decision_evidence"]
    assert evidence["raw"] == {}
    assert evidence["normalization_reasons"] == [
        failure,
        "confidence_normalized",
        "confidence_below_floor",
    ]
    assert evidence["effective"]["needs_human"] is True
    assert out == coerce_decide_output({}, VISIBLE)
    assert "private" not in json.dumps(evidence)


def test_decision_provenance_bounds_invalid_values_and_remains_json_serializable():
    evidence = {}
    coerce_decide_output(
        {
            "next_skill": "x" * 1000,
            "confidence": float("nan"),
            "needs_human": {"private": "nested content"},
            "done": ["private"],
            "exit": "unsupported",
            "rationale": "private rationale",
        },
        VISIBLE,
        evidence=evidence,
    )
    assert evidence["raw"]["next_skill"] == {
        "omitted_type": "string",
        "reason": "not_visible_skill",
    }
    assert evidence["raw"]["confidence"] == {"omitted_type": "number", "reason": "invalid_number"}
    assert evidence["raw"]["needs_human"] == {"omitted_type": "object", "reason": "invalid_type"}
    assert evidence["raw"]["done"] == {"omitted_type": "array", "reason": "invalid_type"}
    assert "private" not in json.dumps(evidence, allow_nan=False)


@pytest.mark.parametrize("field", ["next_skill", "confidence", "needs_human", "exit", "done"])
def test_decision_provenance_omits_prose_even_in_scalar_fields(field):
    raw = {
        "next_skill": "azure_llm_v1",
        "confidence": 0.9,
        "needs_human": False,
        "exit": None,
        "done": False,
    }
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


def test_context_selection_redacts_credentials_and_records_missing_inputs():
    from app.services.run_engine.secret_grants import forget, remember
    from app.services.secrets.values import SecretValue

    config = {
        "inputs_map": {"facts": "source.facts", "risk": "source.risk"},
        "decision_context": {"keys": ["facts", "risk"]},
    }
    remember("context-redaction-test", SecretValue("revealed-secret-value"))
    try:
        values, evidence = build_decision_context(
            config,
            {
                "facts": {
                    "status": "lost",
                    "connection_password": "unrevealed-password",
                    "nested": [
                        {"api_key": "unrevealed-api-key", "message": "revealed-secret-value"}
                    ],
                },
                "unselected": "customer-data-that-must-not-enter-the-prompt",
            },
        )
    finally:
        forget("context-redaction-test")
    assert values == {"facts": {"status": "lost", "nested": [{"message": "***"}]}}
    assert evidence["present_keys"] == ["facts"]
    assert evidence["missing_keys"] == ["risk"]
    assert evidence["sources"] == {
        "facts": {"reference": "source.facts"},
        "risk": {"reference": "source.risk"},
    }
    assert len(evidence["sha256"]) == 64
    assert "status" not in json.dumps(evidence)
    assert build_decision_context({}, {"facts": "private"}) is None


@pytest.mark.parametrize(
    "selection",
    [
        {"keys": ["missing"]},
        {"keys": ["facts", "facts"]},
        {"keys": ["model"]},
        {"keys": ["facts"], "max_bytes": 1},
        {"keys": ["facts"], "max_bytes": 32769},
        {"keys": ["facts"], "max_bytes": True},
        {"keys": ["facts"], "anything": "secret"},
    ],
)
def test_context_configuration_rejects_unmapped_or_unbounded_inputs(selection):
    with pytest.raises(ValueError):
        build_decision_context(
            {
                "inputs_map": {"facts": "source.facts", "model": "source.model"},
                "decision_context": selection,
            },
            {},
        )


def test_context_oversize_is_an_explicit_failure_not_silent_truncation():
    config = {
        "inputs_map": {"facts": "source.facts"},
        "decision_context": {"keys": ["facts"], "max_bytes": 256},
    }
    with pytest.raises(ValueError, match="AGENT_CONTEXT_TOO_LARGE"):
        build_decision_context(config, {"facts": "é" * 200})
    with pytest.raises(ValueError, match="AGENT_CONTEXT_NOT_JSON"):
        build_decision_context(config, {"facts": float("nan")})


def test_context_preserves_legacy_array_selector_provenance():
    from app.services.run_engine.agent_loop import verify_decision_context_payload

    values, evidence = build_decision_context(
        {
            "inputs_map": {"facts": ["input", "order"]},
            "decision_context": {"keys": ["facts"]},
        },
        {"facts": {"status": "delivered"}},
    )
    assert evidence["sources"] == {"facts": {"node_id": "input", "path": ["order"]}}
    assert verify_decision_context_payload({"context": values, "context_evidence": evidence}) == (
        values,
        evidence,
    )


@pytest.mark.asyncio
async def test_authorized_context_is_in_the_first_planner_prompt_and_trace(monkeypatch):
    seen = {}

    async def complete(prompt, model, ctx, **options):
        seen.update(prompt=prompt, model=model)
        return json.dumps({"next_skill": "azure_llm_v1", "confidence": 0.9})

    monkeypatch.setattr(wrappers.skills, "_route_llm_complete", complete)
    values, evidence = build_decision_context(
        {
            "inputs_map": {"risk": {"node_id": "prepared", "path": ["prediction"]}},
            "decision_context": {"keys": ["risk"]},
        },
        {"risk": {"probability": 0.82, "model_version": 5}, "unselected": "do not reveal"},
    )
    ctx = {}
    await wrappers._decide_next_v1(
        {
            "visible_skills": VISIBLE,
            "observations": [],
            "context": values,
            "context_evidence": evidence,
            "model": "openai:gpt-choice",
        },
        ctx,
    )
    assert "0.82" in seen["prompt"] and "model_version" in seen["prompt"]
    assert "untrusted evidence" in seen["prompt"]
    assert "do not reveal" not in seen["prompt"]
    assert seen["model"] == "openai:gpt-choice"
    assert ctx["_agent_loop_context_evidence"] == evidence
    assert "_use_prechecked_model" not in ctx


@pytest.mark.asyncio
async def test_native_planner_rejects_tampered_context_evidence_before_dispatch(monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("Invalid context must never reach the provider")

    monkeypatch.setattr(wrappers.skills, "_route_llm_complete", forbidden)
    values, evidence = build_decision_context(
        {
            "inputs_map": {"facts": "source.facts"},
            "decision_context": {"keys": ["facts"]},
        },
        {"facts": "the authorized fact"},
    )
    for mutated in ({**evidence, "private_extra": "sensitive"}, {**evidence, "sha256": "f" * 64}):
        with pytest.raises(ValueError, match="AGENT_CONTEXT_SNAPSHOT_INVALID"):
            await wrappers._decide_next_v1({"context": values, "context_evidence": mutated}, {})
    with pytest.raises(ValueError, match="AGENT_CONTEXT_SNAPSHOT_INVALID"):
        await wrappers._decide_next_v1(
            {"context": {"facts": "different evidence"}, "context_evidence": evidence}, {}
        )
