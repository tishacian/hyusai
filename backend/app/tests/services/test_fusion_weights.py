from app.services.rag.fusion_weights import FusionWeights, resolve_fusion_weights
from app.services.rag.pipeline_retrieval import _merge_rrf


def _weights(query: str) -> FusionWeights:
    return resolve_fusion_weights(query, base_dense=0.6, base_sparse=0.4)


def test_exact_identifier_query_leans_sparse():
    w = _weights("Spare parts list ACO150")
    assert w.sparse > w.dense
    assert "exact_identifiers" in w.reason
    assert abs(w.dense + w.sparse - 1.0) < 1e-9


def test_interrogative_queries_lean_dense_trilingual():
    for query in (
        "Pourquoi la pompe perd-elle de la pression en fonctionnement ?",
        "Why does the pump lose pressure during operation?",
        "Warum verliert die Pumpe im Betrieb Druck?",
    ):
        w = _weights(query)
        assert w.dense > w.sparse, query
        assert "long_or_interrogative" in w.reason


def test_german_capitalisation_does_not_trigger_sparse():
    # Every German noun is capitalised; capitalisation must not read as
    # "technical term". Only identifier patterns may lean sparse.
    w = _weights("Die Maschine braucht eine neue Dichtung im Bereich der Filtration")
    assert "exact_identifiers" not in w.reason


def test_mixed_signals_cancel_out_to_base():
    # Identifier (+sparse) AND interrogative (+dense) → adjustments cancel.
    w = _weights("Pourquoi la référence ACO150 est-elle indisponible ?")
    base = resolve_fusion_weights("texte neutre sans signal", base_dense=0.6, base_sparse=0.4)
    assert abs(w.dense - base.dense) < 1e-9


def test_clamp_keeps_weights_in_bounds():
    w = resolve_fusion_weights("ACO150 AKK200 BBA120", base_dense=0.2, base_sparse=0.8)
    assert 0.2 / 1.0 <= w.sparse <= 0.8
    assert abs(w.dense + w.sparse - 1.0) < 1e-9


def _rows(*contents: str) -> list[dict]:
    return [{"content": c * 3, "score": 0.5, "metadata": {}} for c in contents]


def test_merge_rrf_without_weights_is_unchanged():
    dense = _rows("alpha-alpha", "beta-beta")
    sparse = _rows("beta-beta", "gamma-gamma")
    legacy = _merge_rrf([dense, sparse], top_k=3)
    explicit_uniform = _merge_rrf([dense, sparse], top_k=3, weights=[1.0, 1.0])
    assert [r["content"] for r in legacy] == [r["content"] for r in explicit_uniform]
    assert [r["rrf_score"] for r in legacy] == [r["rrf_score"] for r in explicit_uniform]


def test_merge_rrf_weights_reorder_results():
    dense = _rows("alpha-alpha")
    sparse = _rows("gamma-gamma")
    sparse_heavy = _merge_rrf([dense, sparse], top_k=2, weights=[0.2, 0.8])
    assert sparse_heavy[0]["content"].startswith("gamma")
    dense_heavy = _merge_rrf([dense, sparse], top_k=2, weights=[0.8, 0.2])
    assert dense_heavy[0]["content"].startswith("alpha")
