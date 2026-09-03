"""The workspace template is the Andritz artifact, generalised — not a fork."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

from app.services.chat_agentic_contract import (
    EXPECTED_FLOW_CONTRACT_SHA256,
    TEMPLATE_FLOW_REVISION,
    agentic_flow_contract_digest,
    expected_contract_digest,
    is_expected_agentic_flow,
)
from app.services.systems import agentic_chat_template as tpl


def _fixture_flow() -> dict:
    with tpl.ARTIFACT_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)["flow_definition"]


def _strip_model_tier(flow: dict) -> dict:
    """Undo exactly the model-tier wiring the template adds (nothing else)."""
    flow = copy.deepcopy(flow)
    for node in flow["nodes"]:
        config = node.get("config") or {}
        inputs_map = config.get("inputs_map")
        if isinstance(inputs_map, dict):
            inputs_map.pop("model_tier", None)
        node["inputs"] = [i for i in node.get("inputs") or [] if i.get("name") != "model_tier"]
        node["outputs"] = [o for o in node.get("outputs") or [] if o.get("name") != "model_tier"]
    return flow


def test_the_fixture_is_still_the_migration_pinned_artifact():
    # Migrations 059/078 raise if this drifts; the template must never edit it.
    assert agentic_flow_contract_digest(_fixture_flow()) == EXPECTED_FLOW_CONTRACT_SHA256


def test_andritz_profile_renders_the_fixture_plus_model_tier_wiring_only():
    fixture = _fixture_flow()
    rendered = tpl.build_flow_definition(tpl.andritz_profile())

    assert [n["id"] for n in rendered["nodes"]] == [n["id"] for n in fixture["nodes"]]
    assert rendered["edges"] == fixture["edges"]
    # Node configs are identical once the tier wiring is removed (skills,
    # decision conditions, HITL prompt, collection binding all unchanged).
    assert agentic_flow_contract_digest(_strip_model_tier(rendered)) == EXPECTED_FLOW_CONTRACT_SHA256
    assert rendered["template_revision"] == TEMPLATE_FLOW_REVISION
    assert rendered["chat_profile_key"] == "andritz"

    by_id = {n["id"]: n for n in rendered["nodes"]}
    for node_id in ("task.generate", "task.self_correct"):
        assert by_id[node_id]["config"]["inputs_map"]["model_tier"] == {
            "node_id": "plan.thinking",
            "path": ["model_tier"],
        }
        # The System pin stays wired: priority 2 in the resolver.
        assert by_id[node_id]["config"]["inputs_map"]["model"] == {"node_id": "system", "path": ["default_model"]}
    assert {"name": "model_tier", "schema": "string"} in by_id["plan.thinking"]["outputs"]


def test_a_generic_profile_has_no_andritz_left_in_the_graph_or_the_membrane():
    profile = tpl.generic_profile(slug="acme", domain_label="ACME Corp")
    rendered = tpl.render(profile)
    text = json.dumps(rendered.flow_definition, ensure_ascii=False).lower()
    # Documentary descriptions in the artifact keep their history; the
    # executable configuration must not name the pilot tenant.
    for node in rendered.flow_definition["nodes"]:
        assert "andritz" not in json.dumps(node.get("config") or {}).lower(), node["id"]
    assert "andritz-notices" not in text
    by_id = {n["id"]: n for n in rendered.flow_definition["nodes"]}
    assert by_id["asset.collection"]["config"] == {"collection_slug": None, "workspace_scoped": True}
    assert "un expert du workspace" in by_id["hitl.expert_review"]["config"]["prompt"]
    assert rendered.membrane_spec["inbound"]["industrial_grounding"] is False
    assert rendered.membrane_spec["inbound"]["collection_allowlist"] == []
    assert rendered.membrane_spec["provenance"]["object_store_prefix"] == "membrane/acme/chat-agentic/"
    assert rendered.retrieval_contract == {"asset_binding": "workspace", "allow_workspace_fallback": True}
    assert rendered.contract_sha256 != EXPECTED_FLOW_CONTRACT_SHA256
    assert set(rendered.skill_slugs) >= {"chat_agentic_plan_v1", "llm_rag_answer_v1", "chat_self_correct_v1"}


def test_an_industrial_profile_with_one_collection_binds_it_authoritatively():
    profile = tpl.generic_profile(slug="mill", family="industrial", domain_label="Mill", collection_slug="mill-docs")
    rendered = tpl.render(profile)
    by_id = {n["id"]: n for n in rendered.flow_definition["nodes"]}
    assert by_id["asset.collection"]["config"]["collection_slug"] == "mill-docs"
    assert rendered.membrane_spec["inbound"]["industrial_grounding"] is True
    assert rendered.membrane_spec["inbound"]["collection_allowlist"] == ["mill-docs"]
    assert rendered.retrieval_contract["collection"] == "mill-docs"
    assert profile.project_code_gates is True and profile.industrial is True


def test_profile_round_trips_through_system_settings():
    profile = tpl.andritz_profile()
    again = tpl.AgenticChatProfile.from_dict(json.loads(json.dumps(profile.to_dict())))
    assert again == profile
    assert tpl.AgenticChatProfile.from_dict({"slug": "x", "unknown": 1}).slug == "x"


def test_contract_accepts_both_the_migration_pin_and_the_template_revision():
    fixture = _fixture_flow()
    legacy_settings = {"system_type": "chat_agentic", "flow_revision": "078_andritz_decision_contract"}
    assert is_expected_agentic_flow(legacy_settings, fixture)

    profile = tpl.generic_profile(slug="acme", domain_label="ACME")
    rendered = tpl.build_flow_definition(profile)
    template_settings = {
        "system_type": "chat_agentic",
        "flow_revision": TEMPLATE_FLOW_REVISION,
        "chat_profile": profile.to_dict(),
    }
    assert expected_contract_digest(template_settings) == tpl.contract_digest(profile)
    assert is_expected_agentic_flow(template_settings, rendered)
    # Another workspace's profile is another contract.
    other = dict(template_settings, chat_profile=tpl.generic_profile(slug="other", domain_label="Other").to_dict())
    assert not is_expected_agentic_flow(other, rendered)
    # No profile recorded => unknown digest => fail closed.
    assert not is_expected_agentic_flow({"system_type": "chat_agentic", "flow_revision": TEMPLATE_FLOW_REVISION}, rendered)
    assert not is_expected_agentic_flow({"system_type": "chat_agentic", "flow_revision": "nope"}, rendered)


def test_workspace_profile_derivation(monkeypatch):
    andritz = SimpleNamespace(slug="andritz", name="Andritz", settings={"family": "andritz"})
    assert tpl.workspace_agentic_chat_profile(andritz) == tpl.andritz_profile()

    generic = SimpleNamespace(slug="acme", name="ACME Corp", settings={})
    profile = tpl.workspace_agentic_chat_profile(generic)
    assert (profile.slug, profile.domain_label, profile.industrial, profile.collection_slug) == (
        "acme", "ACME Corp", False, None,
    )
