from app.services.rag.context import _history_augmented_query
from app.services.rag.conversation_anchors import (
    anchor_terms,
    extract_salient_entities,
    has_reference,
)


def test_extract_salient_entities_finds_references_and_documents():
    entities = extract_salient_entities(
        "Quelle est la procédure de maintenance pour AKK200 ?",
        "Voir spare part list ACO150.pdf, machine BBA 120.",
    )
    assert "AKK200" in entities["references"]
    assert "ACO150" in entities["references"]
    assert "BBA120" in entities["references"]
    assert any("ACO150.pdf" in doc for doc in entities["documents"])


def test_extract_salient_entities_finds_contextual_needlepunch_reference():
    entities = extract_salient_entities("Résume le projet 61038")

    assert entities["references"] == ["61038"]


def test_extract_salient_entities_rejects_french_article_measurement():
    entities = extract_salient_entities(
        "Résume le projet 61035",
        "Le remplacement est recommandé tous les 16 000 heures [1].",
        "TTN17829J.pdf",
    )

    assert entities == {
        "references": ["61035"],
        "documents": ["TTN17829J.pdf"],
    }


def test_extract_salient_entities_preserves_real_legacy_reference():
    entities = extract_salient_entities("Résume BAO100", "Voir TTN17829J.pdf")

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
    assert has_reference("voir ACO150 svp")
    assert has_reference("résume 61038")
    assert not has_reference("vitesse 10000 rpm")
    assert not has_reference("et pour cette machine ?")
