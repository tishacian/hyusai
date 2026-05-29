from __future__ import annotations

from app.agents.orchestrator import _rewrite_preserves_query_terms


def test_query_rewrite_rejects_domain_term_corruption():
    original = "Peux-tu retrouver la liste de garniture de la carde numero 1 du projet COL100 ?"
    rewritten = "Retrouver la liste de garniture de la carte numero 1 du projet COL100"

    assert _rewrite_preserves_query_terms(original, rewritten) is False


def test_query_rewrite_accepts_when_domain_terms_are_preserved():
    original = "Peux-tu retrouver la liste de garniture de la carde numero 1 du projet COL100 ?"
    rewritten = "Liste de garniture de la carde numero 1 pour le projet COL100"

    assert _rewrite_preserves_query_terms(original, rewritten) is True
