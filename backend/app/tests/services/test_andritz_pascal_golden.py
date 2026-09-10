"""Golden pack for Pascal's Andritz session — no LLM, no network, no VM.

Pins plan §6: answer profile, hybrid/100% route (code decision, not live
prod settings), planner scope, teaching detection, and digit-first exact
refs. Reuses the identifier-scope ledger helpers and the hybrid-route
fixtures so this module does not invent a second planner fake.

Rows that need the live notices ledger or a generated answer are skipped
with a reason; do not treat a skip as a pass.
"""
from __future__ import annotations

import pytest

from app.services import chat_execution_policy as policy
from app.services.industrial_answer_profile import (
    industrial_answer_policy,
    resolve_answer_profile,
)
from app.services.knowledge_capture import is_teaching_utterance
from app.services.rag.corpus_planner import plan_corpus
from app.services.rag.lexical_retrieval import analyze_query
from app.services.rag.pipeline_retrieval import _query_exact_references
from app.tests.services.test_chat_execution_policy import (
    _policy,
    _resolve,
    _system,
    _workspace,
)
from app.tests.services.test_corpus_planner_identifier_scopes import (
    _ASY200_SPARE_PARTS,
    _AVA200_PRINTABLE,
    _BEX200_CONVEYOR,
    _CBX300_CONVEYOR,
    _pilot_collection,
    _pilot_profile,
)

QUERY_TOILE_J1 = "quelle est la réference de la toile du convoyeur j1"
QUERY_TOILE_J1_WITH_REF = f"{QUERY_TOILE_J1} 2310PW"
QUERY_TEACH_NOTER = (
    "Pour ta connaissance, merci de noter que sur un convoyeur J1, "
    "on installe une toile 2310 PW"
)
QUERY_TEACH_TOUJOURS = "Pour un J1 on instale toujours une toile 2310PW"
QUERY_STRIP = "quel strip mettre dans l'injecteur de prémouillage"
QUERY_DISTANCE_ISOJET = "quelle est la distance entre le j1 et le c1 en mode isojet"
QUERY_DISTANCE_C1_J1 = "quelle doit être la distance entre le C1 et le J1"
QUERY_COMPARE_J2S = "Compare les consignes J2S avec et sans Scorpio"
QUERY_C1_PLUS_RAPIDE = "C1 plus rapide que J1"
QUERY_SENS_C3 = "sens C3"
QUERY_VIDE_J2S = "vide J2S"
QUERY_TOILE_JP = "quelle toile sur un convoyeur jp"

# Same paths as test_corpus_planner_identifier_scopes (session-anchor case).
_TNX100_CARDING = (
    "T__TNX100__TNX100__files__section_IV__Carding unit__AAT__"
    "03 - SERVO X 91405971__TTN16697J.pdf"
)
_ACJ100_ISOJET = (
    "A__ACJ100__ACJ100__files__section_iv__hydroentanglement-unit__"
    "sub-section_5__V.1.Conveyor J1.pdf"
)
_MOG100_DRYER = (
    "M__MOG100__MOG100__files__section_V__Dryer__"
    "four-secheur-notice.pdf"
)

_ACJ100_SESSION_ANCHORS = {
    "references": ["ACJ100"],
    "positions": ["J1", "C1"],
    "documents": ["V.1.Conveyor J1.pdf"],
}

# Query → profile → hybrid/100% route. Teaching rows are not in this table:
# they must not reach retrieval (see test_pascal_teaching_is_not_a_retrieve).
_PASCAL_PROFILE_ROUTE = (
    (QUERY_TOILE_J1, "equipment_detail", "agentic"),
    (QUERY_STRIP, "precise_fact", "classic"),
    (QUERY_DISTANCE_ISOJET, "precise_fact", "classic"),
    (QUERY_DISTANCE_C1_J1, "precise_fact", "classic"),
    (QUERY_COMPARE_J2S, "comparison", "agentic"),
    (QUERY_TOILE_JP, "precise_fact", "classic"),
)


@pytest.fixture(autouse=True)
def _agentic_master_switch_on(monkeypatch):
    monkeypatch.setattr(policy.settings, "enable_agentic_chat", True)


def _hybrid_workspace(db_session, *, workspace_id: str = "ws-pascal-golden"):
    workspace = _workspace(
        db_session,
        workspace_id=workspace_id,
        settings={"chat_execution": _policy(policy.CHAT_EXECUTION_HYBRID, percentage=100)},
    )
    _system(db_session, workspace)
    return workspace


def _filenames(plan) -> str:
    return str(plan.filters.get("document_filename") or plan.filters)


@pytest.mark.parametrize(
    ("query", "expected_profile", "expected_route"),
    _PASCAL_PROFILE_ROUTE,
)
def test_pascal_profile_and_hybrid_route(
    db_session, query, expected_profile, expected_route
):
    workspace = _hybrid_workspace(db_session)
    decision = resolve_answer_profile(
        query,
        industrial_answer_policy(),
        include_agentic_profiles=True,
    )

    assert decision.profile == expected_profile
    assert (decision.profile in policy.AGENTIC_NICHE_PROFILES) is (expected_route == "agentic")

    route = _resolve(db_session, workspace, answer_profile=decision.profile)
    assert route.route == expected_route
    assert route.reason == (
        "policy_hybrid" if expected_route == "agentic" else "hybrid_profile_classic"
    )


@pytest.mark.parametrize("query", (QUERY_TEACH_NOTER, QUERY_TEACH_TOUJOURS))
def test_pascal_teaching_is_not_a_retrieve(query):
    assert is_teaching_utterance(query) is True
    decision = resolve_answer_profile(
        query,
        industrial_answer_policy(),
        include_agentic_profiles=True,
    )
    # Teaching is an assertion, not a question niche that would retrieve.
    assert decision.profile not in policy.AGENTIC_NICHE_PROFILES
    assert decision.reason != "part_reference_query"
    assert decision.reason != "precise_fact_query"


def test_pascal_2310pw_is_exact_technical_reference_when_present():
    for query in (QUERY_TOILE_J1_WITH_REF, QUERY_TEACH_TOUJOURS):
        assert "2310PW" in _query_exact_references(query), query
        assert "2310PW" in analyze_query(query).exact_terms, query


def test_pascal_toile_j1_does_not_hard_scope_bex200_conveyor(db_session):
    workspace, collection = _pilot_collection(
        db_session,
        workspace_id="ws-pascal-toile",
        name="Andritz notices SPL pilot",
        filenames=(
            _BEX200_CONVEYOR,
            _CBX300_CONVEYOR,
            _AVA200_PRINTABLE,
            _ASY200_SPARE_PARTS,
        ),
    )

    plan = plan_corpus(
        db=db_session,
        profile=_pilot_profile(workspace, collection),
        query=QUERY_TOILE_J1,
    )

    assert "document_filename" not in plan.filters
    assert "BEX200" not in str(plan.filters)


def test_pascal_distance_session_anchor_prefers_acj100_not_tnx100(db_session):
    workspace, collection = _pilot_collection(
        db_session,
        workspace_id="ws-pascal-isojet",
        name="Andritz notices SPL pilot anchors",
        filenames=(_TNX100_CARDING, _ACJ100_ISOJET, _MOG100_DRYER),
    )
    profile = _pilot_profile(workspace, collection)

    for query in (QUERY_DISTANCE_ISOJET, QUERY_DISTANCE_C1_J1):
        anchored = plan_corpus(
            db=db_session,
            profile=profile,
            query=query,
            request={"context": {"salient_entities": _ACJ100_SESSION_ANCHORS}},
        )
        assert anchored.filters == {"document_filename": [_ACJ100_ISOJET]}, query
        assert "TNX100" not in _filenames(anchored), query
        assert "MOG100" not in _filenames(anchored), query


def test_pascal_station_queries_do_not_lock_mog100_dryer_family(db_session):
    workspace, collection = _pilot_collection(
        db_session,
        workspace_id="ws-pascal-dryer",
        name="Andritz notices SPL pilot dryer",
        filenames=(
            _MOG100_DRYER,
            _TNX100_CARDING,
            _BEX200_CONVEYOR,
            _ACJ100_ISOJET,
        ),
    )
    profile = _pilot_profile(workspace, collection)

    for query in (QUERY_C1_PLUS_RAPIDE, QUERY_SENS_C3, QUERY_VIDE_J2S):
        plan = plan_corpus(db=db_session, profile=profile, query=query)
        assert "MOG100" not in _filenames(plan), query
        assert "Dryer" not in _filenames(plan) and "four-secheur" not in _filenames(plan), query


@pytest.mark.skip(
    reason="live Andritz ledger: 'quelle toile sur un convoyeur jp' / 'et sur un J1' pin the published expert fiche"
)
def test_pascal_toile_jp_and_j1_followup_use_expert_fiche_pin():
    raise AssertionError("unreachable: live-ledger pin")


@pytest.mark.skip(
    reason="live Andritz ledger: strip/prémouillage stays scoped to the AVA200 injector notice"
)
def test_pascal_strip_prewet_stays_on_ava200_notice():
    raise AssertionError("unreachable: live-ledger AVA200 scope")


@pytest.mark.skip(
    reason="prompt/fiche assertion, not a new judge: C1 plus rapide must not invent an unsourced inverse"
)
def test_pascal_c1_faster_than_j1_does_not_invent_inverse_claim():
    raise AssertionError("unreachable: generated-answer smoke")
