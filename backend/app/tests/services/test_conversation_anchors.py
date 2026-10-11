from app.services.rag.context import _history_augmented_query
from app.services.rag.conversation_anchors import (
    anchor_terms,
    extract_salient_entities,
    has_reference,
    line_position_terms,
    session_document_anchors,
)
from app.services.rag.project_references import ANDRITZ_PROJECT_SCHEME, bind_project_reference_scheme

ANDRITZ = ANDRITZ_PROJECT_SCHEME


def test_line_position_terms_separate_stations_from_machine_and_part_numbers():
    assert line_position_terms("quelle est la réference de la toile du convoyeur j1") == ("J1",)
    assert line_position_terms("quelle doit être la distance entre le C1 et le J1") == ("C1", "J1")
    assert line_position_terms("compare les consignes J2S et Scorpio") == ("J2S",)
    # Machine, drawing and part references keep their own grammar.
    for text in ("BEX200", "TTN16697J", "la pompe URACA KD724-G", "la toile 2310PW", "AVA100 RUS"):
        assert line_position_terms(text) == (), text


def test_extract_salient_entities_anchors_line_positions():
    entities = extract_salient_entities(
        "quelle est la réference de la toile du convoyeur J1 ?",
        "La toile du J1 est référencée dans la spare parts list ASY200.pdf.",
    )

    assert entities["positions"] == ["J1"]
    assert any("ASY200.pdf" in document for document in entities["documents"])


def test_extract_salient_entities_drops_documents_of_a_turn_that_found_nothing():
    """A refused turn describes the scope that already failed, not a good one."""
    entities = extract_salient_entities(
        "quelle est la réference de la toile du convoyeur J1 ?",
        "Je n'ai pas trouvé cette information dans les documents consultés.",
        "V.1.Conveyor BEX200.pdf",
    )

    assert entities["documents"] == []
    assert entities["positions"] == ["J1"]


def test_session_document_anchors_keep_the_station_document_only():
    entities = {
        "references": ["ACJ100"],
        "positions": ["J1", "C1"],
        "documents": ["V.1.Conveyor J1.pdf", "Chapter 01.pdf"],
    }

    assert session_document_anchors(
        entities,
        query="quelle doit être la distance entre le C1 et le J1",
    ) == ["V.1.Conveyor J1.pdf", "Chapter 01.pdf"]
    # Another station, another subject: nothing from the previous turn applies.
    assert session_document_anchors(
        {**entities, "positions": ["J1"]},
        query="quel est le poids de la machine",
    ) == []
    assert session_document_anchors(None, query="et pour le J1 ?") == []


def test_extract_salient_entities_finds_references_and_documents():
    entities = extract_salient_entities(
        "Quelle est la procédure de maintenance pour AKK200 ?",
        "Voir spare part list ACO150.pdf, machine BBA 120.",
        scheme=ANDRITZ,
    )
    assert "AKK200" in entities["references"]
    assert "ACO150" in entities["references"]
    assert "BBA120" in entities["references"]
    assert any("ACO150.pdf" in doc for doc in entities["documents"])


def test_extract_salient_entities_finds_contextual_needlepunch_reference():
    entities = extract_salient_entities("Résume le projet 61038", scheme=ANDRITZ)

    assert entities["references"] == ["61038"]


def test_extract_salient_entities_rejects_french_article_measurement():
    entities = extract_salient_entities(
        "Résume le projet 61035",
        "Le remplacement est recommandé tous les 16 000 heures [1].",
        "TTN17829J.pdf",
        scheme=ANDRITZ,
    )

    assert entities == {
        "references": ["61035"],
        "positions": [],
        "documents": ["TTN17829J.pdf"],
    }


def test_extract_salient_entities_preserves_real_legacy_reference():
    entities = extract_salient_entities("Résume BAO100", "Voir TTN17829J.pdf", scheme=ANDRITZ)

    assert entities["references"] == ["BAO100"]
    assert any("TTN17829J.pdf" in document for document in entities["documents"])


def test_anchor_terms_caps_and_prioritises_references():
    entities = {
        "references": ["AKK200", "ACO150", "BBA120"],
        "documents": ["manual.pdf"],
    }
    assert anchor_terms(entities) == ["AKK200", "ACO150"]
    assert anchor_terms(None) == []


def test_history_augmented_query_uses_precomputed_entities():
    request = {
        "query": "et pour cette machine, quelle vitesse ?",
        "context": {
            "conversation_history": [
                {"role": "user", "content": "Parle-moi du projet AKK200"},
                {"role": "assistant", "content": "AKK200 est une ligne SPL."},
            ],
            "salient_entities": {"references": ["AKK200"], "documents": []},
        },
    }
    augmented = _history_augmented_query(request)
    assert augmented.startswith("et pour cette machine")
    assert "AKK200" in augmented


def test_history_augmented_query_falls_back_to_history_scan():
    with bind_project_reference_scheme(ANDRITZ):
        _assert_history_augmented_query_falls_back_to_history_scan()


def _assert_history_augmented_query_falls_back_to_history_scan():
    request = {
        "query": "et pour celle-ci ?",
        "context": {
            "conversation_history": [
                {"role": "user", "content": "Donne la fiche de la machine BBA120"},
                {"role": "assistant", "content": "Voici la fiche."},
            ],
        },
    }
    augmented = _history_augmented_query(request)
    assert "BBA120" in augmented


def test_history_augmented_query_skips_when_query_has_own_reference():
    request = {
        "query": "et pour ACO150, même question ?",
        "context": {
            "conversation_history": [
                {"role": "user", "content": "Parle-moi du projet AKK200"},
            ],
            "salient_entities": {"references": ["AKK200"], "documents": []},
        },
    }
    with bind_project_reference_scheme(ANDRITZ):
        assert _history_augmented_query(request) == "et pour ACO150, même question ?"


def test_history_augmented_query_keeps_numeric_project_for_possessive_followup():
    request = {
        "query": "et ses pièces ?",
        "context": {
            "conversation_history": [
                {"role": "user", "content": "Résume le projet 61038"},
            ],
            "salient_entities": {"references": ["61038"], "documents": []},
        },
    }

    augmented = _history_augmented_query(request)
    assert augmented.startswith("et ses pièces ?")
    assert "61038" in augmented


def test_history_augmented_query_does_not_carry_measurement_as_reference():
    entities = extract_salient_entities(
        "Résume le projet 61035",
        "La périodicité indiquée est de tous les 16 000 heures [1].",
        scheme=ANDRITZ,
    )
    request = {
        "query": "Et ses pièces ?",
        "context": {
            "conversation_history": [
                {"role": "user", "content": "Résume le projet 61035"},
                {
                    "role": "assistant",
                    "content": "La périodicité indiquée est de tous les 16 000 heures [1].",
                },
            ],
            "salient_entities": entities,
        },
    }

    augmented = _history_augmented_query(request)
    assert augmented == "Et ses pièces ? | Previous user context: | 61035"
    assert "LES16" not in augmented


def test_history_augmented_query_untouched_without_followup_signal():
    request = {
        "query": "Quelle est la pression nominale de la pompe URACA KD716 ?",
        "context": {
            "conversation_history": [
                {"role": "user", "content": "Parle-moi du projet AKK200"},
            ],
        },
    }
    query = _history_augmented_query(request)
    assert not query.startswith("Quelle") or "Previous user context" not in query


def test_has_reference():
    assert has_reference("voir ACO150 svp", scheme=ANDRITZ)
    assert has_reference("résume 61038", scheme=ANDRITZ)
    assert not has_reference("vitesse 10000 rpm", scheme=ANDRITZ)
    assert not has_reference("et pour cette machine ?", scheme=ANDRITZ)


def test_andritz_references_are_not_anchors_without_scheme():
    entities = extract_salient_entities(
        "Quelle est la procédure de maintenance pour AKK200 ?",
        "Voir spare part list ACO150.pdf, machine BBA 120.",
    )
    assert entities["references"] == []
    assert not has_reference("voir ACO150 svp")
    assert not has_reference("résume le projet BBA120")
