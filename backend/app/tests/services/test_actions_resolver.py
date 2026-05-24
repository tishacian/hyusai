from __future__ import annotations

import asyncio

import pytest

from app.models.user import User
from app.models.workspace import Workspace
from app.services.actions.executor import (
    execute_flow_action,
    get_awaiting_state,
    resolve_action_with_awaiting,
    set_awaiting_state,
)
from app.services.actions.registry import effective_action_manifests, resolve_action


def _workspace(**kwargs) -> Workspace:
    defaults = {
        "id": "ws-sentinel",
        "slug": "sentinel-ci",
        "name": "SENTINEL-CI",
        "settings": {
            "actions": {"enabled_packs": ["global_voice_v1", "sentinel_ci_aya_v1"]},
            "assistant_profiles": [
                {"key": "vigie_executive", "actions": {"enabled_packs": ["global_voice_v1", "sentinel_ci_aya_v1"]}}
            ],
        },
    }
    defaults.update(kwargs)
    return Workspace(**defaults)


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("Aya, fais moi un résumé des sujets prioritaires", "aya.priority_summary"),
        ("Fais moi un zoom sur la région nord projet public composants importés", "aya.focus_zone_with_project"),
        ("Montre moi le trafic maritime à destination d'Abidjan", "aya.show_maritime_traffic"),
        ("OK Aya, quel est mon prochain RDV ?", "aya.open_next_meeting"),
        ("Quels ont été les derniers échanges ?", "aya.summarize_last_exchanges"),
        ("Aya, donne moi des préconisations sur le cacao", "aya.recommend_cacao"),
        ("Cale un RDV avec le ministre de l'Économie", "aya.schedule_meeting"),
        # Phase A — causal chain.
        ("Pourquoi cette cargaison est-elle bloquée ?", "aya.explain_why"),
        ("Explique moi pourquoi le projet public est en retard", "aya.explain_why"),
        ("Qu'est-ce qui cause la tension dans le Nord ?", "aya.explain_why"),
        # Phase C — vessel evidence.
        ("Montre le navire MV Atlantic Trader", "aya.show_vessel_evidence"),
        ("Voir flux entree port", "aya.show_vessel_evidence"),
        # Phase D — customs record PV.
        ("Montre le PV douanes", "aya.show_customs_record"),
        ("Ouvre le proces verbal douanes", "aya.show_customs_record"),
        # Phase H — agenda update.
        ("Ajoute le point cacao au meeting", "aya.update_meeting_agenda"),
        ("Mets a jour l'ordre du jour", "aya.update_meeting_agenda"),
        # Phase I — meeting live mode.
        ("Demarre la reunion", "aya.start_meeting"),
        ("Commence la reunion", "aya.start_meeting"),
        ("Valide l'option B", "aya.log_decision"),
        ("Decide option C", "aya.log_decision"),
        ("Qu'avons nous decide la derniere fois ?", "aya.recall_past_decisions"),
        ("Rappelle moi nos decisions", "aya.recall_past_decisions"),
        ("oui", "voice.confirm_yes"),
        ("non", "voice.confirm_no"),
        # AYA wake-word handling.
        ("AYA", "aya.acknowledge_presence"),
        ("AYA ?", "aya.acknowledge_presence"),
        ("AYA tu m'entends", "aya.acknowledge_presence"),
        ("AYA tu es là", "aya.acknowledge_presence"),
        ("AYA présente", "aya.acknowledge_presence"),
        ("AYA écoute", "aya.acknowledge_presence"),
        ("Hey AYA", "aya.acknowledge_presence"),
        # AYA prefix/suffix should not pollute the rest of the matching pipeline.
        ("AYA, donne moi le cockpit 60 secondes", "aya.priority_summary"),
        ("Donne moi le cockpit 60 secondes AYA", "aya.priority_summary"),
        ("pourquoi AYA situation au nord", "aya.explain_why"),
        ("AYA, ouvre le PV douanes", "aya.show_customs_record"),
        ("AYA, démarre la réunion", "aya.start_meeting"),
        # Top 5 résolveur — anglicismes critiques.
        ("morning briefing", "aya.priority_summary"),
        ("daily briefing", "aya.priority_summary"),
        ("give me the briefing", "aya.priority_summary"),
        ("next meeting", "aya.open_next_meeting"),
        ("what's my next meeting", "aya.open_next_meeting"),
        ("start meeting", "aya.start_meeting"),
        ("start the meeting", "aya.start_meeting"),
        ("show me the customs report", "aya.show_customs_record"),
        ("show the customs pv", "aya.show_customs_record"),
        ("draft a customs email", "aya.draft_customs_email"),
        ("customs clearance email", "aya.draft_customs_email"),
        ("why is the north tense", "aya.explain_why"),
        ("why north", "aya.explain_why"),
        # Top 5 résolveur — ultra-courts ≤ 4 mots.
        ("voir pv", "aya.show_customs_record"),
        ("pv douanes", "aya.show_customs_record"),
        ("quoi maintenant", "aya.open_next_meeting"),
        ("résume préfet", "aya.summarize_last_exchanges"),
        ("résume Préfet Nawa", "aya.summarize_last_exchanges"),
        ("résume Nawa", "aya.summarize_last_exchanges"),
        ("preco cacao", "aya.recommend_cacao"),
        ("préco cacao", "aya.recommend_cacao"),
        ("email dérogation", "aya.draft_customs_email"),
        ("email derogation", "aya.draft_customs_email"),
        # Top 5 résolveur — formes orales familières.
        ("c'est quoi qui cloche au Nord", "aya.explain_why"),
        ("on prépare un email aux douanes", "aya.propose_customs_email"),
        ("on commence le meeting", "aya.start_meeting"),
        # Top 5 résolveur — tie-breaker Atlantic Trader vs douanes.
        ("le PV du 18 mai sur Atlantic Trader", "aya.show_customs_record"),
        ("rédige un courrier de dédouanement pour Atlantic Trader", "aya.draft_customs_email"),
    ],
)
def test_resolver_matches_demo_scenario_phrases(phrase, expected):
    workspace = _workspace()
    result = resolve_action(workspace, text=phrase, surface="voice", assistant_profile="vigie_executive")
    assert result.matched is True
    assert result.action_id == expected


def test_awaiting_yes_routes_to_draft_customs_email(db_session):
    workspace = _workspace()
    db_session.add(workspace)
    db_session.commit()
    set_awaiting_state(
        db_session,
        workspace,
        {
            "key": "customs_email",
            "action_on_yes": "aya.draft_customs_email",
            "action_on_no": "voice.confirm_no",
        },
        session_id="sess-1",
    )
    db_session.commit()

    awaiting = get_awaiting_state(db_session, workspace, session_id="sess-1")
    resolution = resolve_action_with_awaiting(
        workspace,
        text="oui",
        surface="chat",
        assistant_profile="vigie_executive",
        awaiting=awaiting,
    )
    assert resolution.matched is True
    assert resolution.action_id == "aya.draft_customs_email"
    assert resolution.reason == "awaiting_yes"


def test_execute_maritime_sets_awaiting_and_propose_effect(db_session):
    workspace = _workspace()
    user = User(id="u1", username="vp", email="vp@example.test", is_active=True)
    db_session.add_all([workspace, user])
    db_session.commit()

    manifest = next(m for m in effective_action_manifests(workspace, surface="chat") if m.action_id == "aya.show_maritime_traffic")
    result = asyncio.run(
        execute_flow_action(
            db_session,
            workspace,
            user,
            manifest=manifest,
            text="trafic maritime abidjan",
            session_id="sess-maritime",
        )
    )
    assert result["action"] == "aya.show_maritime_traffic"
    effects = result.get("action_effects") or []
    assert any(item.get("effect") == "assistant-propose" for item in effects)
    awaiting = get_awaiting_state(db_session, workspace, session_id="sess-maritime")
    assert awaiting is not None
    assert awaiting["action_on_yes"] == "aya.draft_customs_email"
