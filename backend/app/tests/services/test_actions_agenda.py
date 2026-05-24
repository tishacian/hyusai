from __future__ import annotations

import asyncio

import pytest

from app.models.user import User
from app.models.workspace import Workspace
from app.services.actions.executor import _resolve_agenda_item_from_prompt, execute_flow_action
from app.services.actions.registry import effective_action_manifests, resolve_action
from app.services.workspace_calendar import ensure_calendar_seed


def _workspace(**kwargs) -> Workspace:
    defaults = {
        "id": "ws-sentinel",
        "slug": "sentinel-ci",
        "name": "SENTINEL-CI",
        "mode": "demo",
        "settings": {
            "actions": {"enabled_packs": ["global_voice_v1", "sentinel_ci_aya_v1"]},
            "assistant_profiles": [
                {"key": "vigie_executive", "actions": {"enabled_packs": ["global_voice_v1", "sentinel_ci_aya_v1"]}}
            ],
            "calendar": {"mode": "internal_shared", "write_policy": "direct"},
        },
    }
    defaults.update(kwargs)
    return Workspace(**defaults)


def test_resolver_explique_cargo_atlantic_trader_matches_vessel_evidence():
    workspace = _workspace()
    result = resolve_action(
        workspace,
        text="explique le cargo Atlantic Trader",
        surface="voice",
        assistant_profile="vigie_executive",
    )
    assert result.matched is True
    assert result.action_id == "aya.show_vessel_evidence"
    assert result.confidence >= 0.78


@pytest.mark.parametrize(
    ("prompt", "expected_title"),
    [
        (
            "mets a jour l odj : derogation douanes",
            "Derogation douanes — cargo MV Atlantic Trader / Centre Napie",
        ),
        (
            "mets a jour l ordre du jour",
            "Point cacao - diversification anacarde (proposition AYA)",
        ),
    ],
)
def test_resolve_agenda_item_from_prompt(prompt, expected_title):
    item = _resolve_agenda_item_from_prompt(prompt)
    assert item["title"] == expected_title


def test_update_meeting_agenda_stages_extracted_title(db_session):
    workspace = _workspace()
    user = User(id="u1", username="vp", email="vp@example.test", is_active=True)
    db_session.add_all([workspace, user])
    db_session.commit()
    ensure_calendar_seed(db_session, workspace)
    db_session.commit()

    manifest = next(
        m for m in effective_action_manifests(workspace, surface="chat") if m.action_id == "aya.update_meeting_agenda"
    )
    result = asyncio.run(
        execute_flow_action(
            db_session,
            workspace,
            user,
            manifest=manifest,
            text="mets a jour l odj : derogation douanes",
            session_id="sess-agenda",
        )
    )

    assert result["action"] == "aya.update_meeting_agenda"
    proposed = result.get("proposed_agenda_items") or []
    assert proposed
    assert proposed[0]["title"] == "Derogation douanes — cargo MV Atlantic Trader / Centre Napie"
    assert proposed[0]["title"] != "Point cacao - diversification anacarde (proposition AYA)"

    draft_effect = next(
        effect
        for effect in (result.get("action_effects") or [])
        if effect.get("effect") == "assistant-draft-open" and effect.get("target_type") == "calendar_agenda_patch"
    )
    draft_items = (draft_effect.get("draft_payload") or {}).get("metadata", {}).get("agenda_items") or []
    assert draft_items[0]["title"] == "Derogation douanes — cargo MV Atlantic Trader / Centre Napie"
