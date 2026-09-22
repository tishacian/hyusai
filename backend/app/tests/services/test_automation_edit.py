import pytest

import json

from app.services.automation_edit import (
    AutomationEditRefusal,
    allow_tool,
    apply_patch,
    catalog,
    edit_generation_options,
    edit_prompt,
    execute_turn,
    plan_from_completion,
    read_back,
    read_draft,
    summarize_draft_result,
    validate_patch,
)


def test_catalog_is_the_seven_automation_blocks():
    assert [block.type for block in catalog()] == [
        "trigger",
        "agent",
        "decision",
        "approval",
        "retrieve",
        "sap_write",
        "output",
    ]
    by_type = {block.type: block for block in catalog()}
    assert by_type["agent"].skill_slug == "workspace_llm_v1"
    assert by_type["retrieve"].outputs == ("passage", "source")
    assert by_type["approval"].outputs[-1] == "decided_by"
    assert by_type["sap_write"].skill_slug == "sap_create_po_v1"


def test_patch_places_retrieve_approval_and_sap_write_with_decided_by():
    accepted = validate_patch(
        {
            "add": [
                {"id": "retrieve", "type": "retrieve"},
                {"id": "approval", "type": "approval"},
                {"id": "sap", "type": "sap_write"},
            ],
            "edges": [
                {
                    "from": "approval",
                    "to": "sap",
                    "from_port": "decided_by",
                    "to_port": "decided_by",
                }
            ],
        }
    )

    assert [node["type"] for node in accepted["nodes"]] == [
        "retrieve",
        "approval",
        "sap_write",
    ]
    assert accepted["edges"][0]["from_port"] == "decided_by"


def test_one_edge_object_is_read_as_a_single_edge():
    accepted = validate_patch(
        {
            "add": [
                {"id": "approval", "type": "approval"},
                {"id": "sap", "type": "sap_write"},
            ],
            "edges": {
                "from": "approval",
                "to": "sap",
                "from_port": "decided_by",
                "to_port": "decided_by",
            },
        }
    )
    assert accepted["edges"] == [
        {
            "from": "approval",
            "to": "sap",
            "from_port": "decided_by",
            "to_port": "decided_by",
        }
    ]


def test_eighth_block_type_is_refused():
    for block_type in ("function", "start_trigger", "condition", "response", "rpa_dispatch_v1"):
        with pytest.raises(AutomationEditRefusal) as refusal:
            validate_patch({"add": [{"id": "extra", "type": block_type}]})
        assert refusal.value.code == "block_refused"
        assert block_type in refusal.value.message


def test_approval_and_sap_write_without_decided_by_is_refused():
    with pytest.raises(AutomationEditRefusal) as refusal:
        validate_patch(
            {
                "add": [
                    {"id": "sap", "type": "sap_write"},
                    {"id": "approval", "type": "approval"},
                ]
            }
        )
    assert refusal.value.code == "decided_by_required"


def _draft() -> dict:
    return {
        "schema_version": 3,
        "variant": "automation_v1",
        "nodes": [
            {"id": "trigger", "kind": "source", "type": "source"},
            {"id": "output", "kind": "sink", "type": "sink"},
        ],
        "edges": [{"from": "trigger", "to": "output", "from_port": "transcript", "to_port": "result"}],
    }


def test_apply_patch_keeps_the_read_hash_and_read_back_matches():
    flow = _draft()
    seen = read_draft(flow)
    proposed = apply_patch(
        flow,
        {
            "add": [
                {"id": "retrieve", "type": "retrieve"},
                {"id": "approval", "type": "approval"},
                {"id": "sap", "type": "sap_write"},
            ],
            "edges": [{
                "from": "approval",
                "to": "sap",
                "from_port": "decided_by",
                "to_port": "decided_by",
            }],
        },
        expected_hash=seen["hash"],
    )

    read_back(proposed, proposed)
    reread = read_draft(proposed)
    assert [node["type"] for node in reread["nodes"]] == [
        "trigger",
        "output",
        "retrieve",
        "approval",
        "sap_write",
    ]
    assert ("approval", "sap", "decided_by", "decided_by") in reread["edges"]
    assert reread["hash"] != seen["hash"]


def test_stale_draft_is_not_written():
    flow = _draft()
    seen = read_draft(flow)
    with pytest.raises(AutomationEditRefusal) as refusal:
        apply_patch(flow, {"add": [{"id": "retrieve", "type": "retrieve"}]}, expected_hash="0" * 64)
    assert refusal.value.code == "stale_draft"
    assert read_draft(flow)["hash"] == seen["hash"]


def test_read_back_fails_when_the_save_drops_an_edge():
    flow = _draft()
    proposed = apply_patch(
        flow,
        {
            "add": [
                {"id": "approval", "type": "approval"},
                {"id": "sap", "type": "sap_write"},
            ],
            "edges": [{
                "from": "approval",
                "to": "sap",
                "from_port": "decided_by",
                "to_port": "decided_by",
            }],
        },
        expected_hash=read_draft(flow)["hash"],
    )
    saved = {
        **proposed,
        "edges": [edge for edge in proposed["edges"] if edge.get("from_port") != "decided_by"],
    }
    with pytest.raises(AutomationEditRefusal) as refusal:
        read_back(saved, proposed)
    assert refusal.value.code == "save_mismatch"


def test_intention_gates_the_tools():
    allow_tool("edit_and_run", "patch")
    allow_tool("edit_and_run", "test")
    allow_tool("explain", "read")
    with pytest.raises(AutomationEditRefusal) as refused_edit:
        allow_tool("explain", "patch")
    assert refused_edit.value.code == "tool_refused"
    with pytest.raises(AutomationEditRefusal) as refused_run:
        allow_tool("run", "patch")
    assert refused_run.value.code == "tool_refused"
    with pytest.raises(AutomationEditRefusal):
        allow_tool("edit", "publish")
    with pytest.raises(AutomationEditRefusal):
        allow_tool("edit_and_run", "approve")


def test_agent_cannot_swap_in_another_skill():
    with pytest.raises(AutomationEditRefusal) as refusal:
        validate_patch(
            {"add": [{"id": "agent", "type": "agent", "skill_slug": "llm_rag_answer_v1"}]}
        )
    assert refusal.value.code == "block_refused"


def test_model_completion_with_an_eighth_block_is_refused():
    text = json.dumps({"intent": "edit", "patch": {"add": [{"id": "fn", "type": "function"}]}})
    with pytest.raises(AutomationEditRefusal) as refusal:
        plan_from_completion(text)
    assert refusal.value.code == "block_refused"


def test_model_completion_can_plan_the_governed_patch():
    plan = plan_from_completion(json.dumps({
        "intent": "edit_and_run",
        "patch": {
            "add": [
                {"id": "retrieve", "type": "retrieve"},
                {"id": "approval", "type": "approval"},
                {"id": "sap", "type": "sap_write"},
            ],
            "edges": [{
                "from": "approval",
                "to": "sap",
                "from_port": "decided_by",
                "to_port": "decided_by",
            }],
        },
    }))
    assert plan["intent"] == "edit_and_run"
    assert [node["type"] for node in plan["patch"]["add"]] == ["retrieve", "approval", "sap_write"]


def test_explain_completion_cannot_carry_a_patch():
    text = json.dumps({"intent": "explain", "patch": {"add": [{"id": "out", "type": "output"}]}})
    with pytest.raises(AutomationEditRefusal) as refusal:
        plan_from_completion(text)
    assert refusal.value.code == "tool_refused"


def test_retrieve_summary_cites_or_says_there_is_no_passage():
    cited = summarize_draft_result({
        "status": "completed",
        "invocations": [{
            "skill_slug": "semantic_search_v1",
            "output_ref": {"passage": "The laptop request is approved.", "source": "doc-1"},
        }],
    })
    assert cited == {"kind": "retrieve", "passage": "The laptop request is approved.", "source": "doc-1"}
    empty = summarize_draft_result({
        "status": "completed",
        "invocations": [{"skill_slug": "semantic_search_v1", "output_ref": {"results": []}}],
    })
    assert empty == {"kind": "retrieve", "passage": None, "source": None}


def test_sap_write_without_approval_stays_sealed_in_the_summary():
    summary = summarize_draft_result({
        "status": "completed",
        "invocations": [{
            "skill_slug": "sap_create_po_v1",
            "output_ref": {"sealed": True, "called": False, "reason": "unattended"},
        }],
    })
    assert summary == {"kind": "sap_write", "sealed": True, "called": False}


def test_approval_pause_is_the_result_the_loop_shows():
    summary = summarize_draft_result({
        "status": "hitl_pending",
        "checkpoints": [{"kind": "hitl_pause", "prompt": "Approve this step?", "decision_id": "d1"}],
        "invocations": [{"skill_slug": "sap_create_po_v1", "output_ref": {"sealed": True, "called": False}}],
    })
    assert summary["kind"] == "approval_pause"
    assert summary["decision_id"] == "d1"


def test_execute_turn_saves_only_the_verified_patch_then_starts_the_draft_test():
    flow = {
        "schema_version": 3,
        "variant": "automation_v1",
        "nodes": [
            {"id": "trigger", "kind": "source", "type": "trigger", "config": {"automation_block": "trigger"}},
            {"id": "output", "kind": "sink", "type": "output", "config": {"automation_block": "output"}},
        ],
        "edges": [],
    }
    saved = {}

    def save(proposed):
        saved["flow"] = proposed
        return proposed

    started = {}

    def start_test(snapshot):
        started["hash"] = snapshot["hash"]
        return {"id": "run-1"}

    result = execute_turn(
        flow,
        intent="edit_and_run",
        patch={
            "add": [{"id": "retrieve", "type": "retrieve"}],
            "edges": [{"from": "trigger", "to": "retrieve", "from_port": "transcript", "to_port": "query"}],
        },
        save=save,
        start_test=start_test,
    )
    assert result["verified"] is True
    assert result["run"] == {"id": "run-1"}
    assert started["hash"] == result["read"]["hash"]
    assert any(node["type"] == "retrieve" for node in result["read"]["nodes"])
    retrieve = next(node for node in saved["flow"]["nodes"] if node["id"] == "retrieve")
    assert retrieve["config"]["skill_slug"] == "semantic_search_v1"
    assert retrieve["config"]["inputs_map"]["query"] == "run.transcript"


def test_fenced_model_completion_is_still_refused_outside_the_catalog():
    text = "```json\n" + json.dumps(
        {"intent": "edit", "patch": {"add": [{"id": "fn", "type": "function"}]}}
    ) + "\n```"
    with pytest.raises(AutomationEditRefusal) as refusal:
        plan_from_completion(text)
    assert refusal.value.code == "block_refused"


def test_a_thinking_model_keeps_tokens_for_the_json_plan():
    options = edit_generation_options("openai", "gpt-5")
    assert options["response_format"] == {"type": "json_object"}
    assert options["max_tokens"] == 2000
    assert options["reasoning_effort"]


def test_a_chat_model_does_not_receive_a_reasoning_pin():
    options = edit_generation_options("openai", "gpt-4o")
    assert "reasoning_effort" not in options
    assert options["response_format"] == {"type": "json_object"}


def test_a_local_model_is_not_forced_into_json_mode():
    options = edit_generation_options("ollama", "llama3")
    assert options == {"max_tokens": 2000}


def test_edit_prompt_names_the_catalog_and_not_a_publish_tool():
    prompt = edit_prompt("ajoute une recherche citée", {"nodes": [], "edges": [], "hash": "abc"})
    for block_type in ("trigger", "agent", "decision", "approval", "retrieve", "sap_write", "output"):
        assert block_type in prompt
    assert "publish" in prompt
    assert "function" not in prompt
