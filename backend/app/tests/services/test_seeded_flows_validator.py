"""Golden regression guard for the seeded Andritz flows vs the validator.

P0 (variable-membrane / ``schema_version`` 3) bumps the bootstrap
generators and adds two new validator codes (``port_type_mismatch`` /
``variable_unresolved``). This test pins the permanent invariant that the
flows Agentium re-derives at boot for an Andritz workspace — the always-on
``Workspace Chat`` twin and the ``Expert Knowledge Capture`` flow — stay
**error-free** under ``dag_validator.validate_flow`` and produce **zero
false positives** from the new v3 checks (their edges carry no typed
``from_port``/``to_port`` and their ``inputs_map`` are legacy dot-path
strings, which the new checks must leave alone).

Pure-logic: the flow generators are called directly with an empty skill
stub (skills are looked up only to stamp ``skill_id``, and the generators
tolerate a missing skill), so no DB / FastAPI is required.
"""
from __future__ import annotations

import pytest

from app.models.workspace import Workspace
from app.services.chains.dag_validator import validate_flow
from app.services.systems.bootstrap import (
    _expert_capture_flow_definition,
    _workspace_chat_flow_definition,
    _workspace_chat_profile,
)

# Mirrors the Andritz workspace settings exercised by
# ``test_workspace_chat_system.test_andritz_workspace_chat_inherits_industrial_profile``
# so the chat twin is generated through the real industrial profile path.
_ANDRITZ_SETTINGS = {
    "family": "andritz",
    "assistant_profile_default": "andritz_spl_advisor",
    "knowledge_scopes": [
        {
            "key": "andritz-spl-knowledge-experiment",
            "collection_slugs": [
                "andritz-secure-deposit",
                "andritz-notices-techniques-spl-pilot",
            ],
            "default_mode": "chah",
            "top_k": 6,
            "is_default": True,
        }
    ],
    "assistant_profiles": [
        {
            "key": "andritz_spl_advisor",
            "label": "Andritz SPL Advisor",
            "default_knowledge_scope": "andritz-spl-knowledge-experiment",
            "grounding": {
                "default_mode": "balanced",
                "allowed_modes": ["strict", "balanced"],
                "strict_guard": "business_interpretation",
            },
        }
    ],
}

# New v3 codes that must NOT fire on the legacy seeded graphs.
_V3_CODES = {"port_type_mismatch", "variable_unresolved"}


def _andritz_chat_flow():
    workspace = Workspace(id="ws-andritz-golden", name="Andritz", slug="andritz")
    workspace.settings = dict(_ANDRITZ_SETTINGS)
    profile = _workspace_chat_profile(workspace)
    # Empty skill stub: the generator stamps skill_id=None but keeps the
    # node/edge structure the validator reasons about.
    return _workspace_chat_flow_definition(profile, {})


def _capture_flow():
    return _expert_capture_flow_definition({})


def _seeded_flows():
    return {
        "andritz_workspace_chat": _andritz_chat_flow(),
        "expert_knowledge_capture": _capture_flow(),
    }


@pytest.mark.parametrize("name", ["andritz_workspace_chat", "expert_knowledge_capture"])
def test_seeded_flow_is_schema_version_3(name) -> None:
    flow = _seeded_flows()[name]
    assert flow["schema_version"] == 3


@pytest.mark.parametrize("name", ["andritz_workspace_chat", "expert_knowledge_capture"])
def test_seeded_flow_has_no_validator_errors(name) -> None:
    flow = _seeded_flows()[name]
    errors = [issue.to_dict() for issue in validate_flow(flow) if issue.level == "error"]
    assert errors == [], f"{name} produced error-level issues: {errors}"


@pytest.mark.parametrize("name", ["andritz_workspace_chat", "expert_knowledge_capture"])
def test_seeded_flow_no_v3_false_positives(name) -> None:
    """The legacy graphs use portless edges + dot-path inputs_map, so the
    new variable-membrane checks must stay silent (no false positives).
    """
    flow = _seeded_flows()[name]
    fired = {issue.code for issue in validate_flow(flow)} & _V3_CODES
    assert fired == set(), f"{name} unexpectedly fired v3 codes: {fired}"
