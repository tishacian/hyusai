from __future__ import annotations

from app.services.rag.offline_eval import RetrievalEvalCase, bge_m3_candidate, score_retrieval_cases


def test_bge_m3_candidate_is_isolated_from_global_embedding_settings():
    candidate = bge_m3_candidate()

    assert candidate.embedding_model == "bge-m3"
    assert candidate.collection_suffix == "__eval_bge_m3"
    assert candidate.mutates_global_settings is False


def test_score_retrieval_cases_reports_recall_provenance_and_sparse_rates():
    scores = score_retrieval_cases(
        [
            RetrievalEvalCase(
                query="SPL AKK200",
                expected_document_ids=("doc-a",),
                results=(
                    {"metadata": {"document_id": "doc-x", "status": "draft"}},
                    {"metadata": {"document_id": "doc-a", "status": "reviewed"}},
                ),
                metrics={"dense_only": False, "sparse_status": "ok"},
            ),
            RetrievalEvalCase(
                query="Non-Wovens table",
                expected_document_ids=("doc-b",),
                results=({"metadata": {"document_id": "doc-z", "status": "draft"}},),
                metrics={"dense_only": True, "sparse_status": "empty"},
            ),
        ],
        ks=(1, 2),
    )

    assert scores["cases"] == 2
    assert scores["recall_at_k"] == {"1": 0.0, "2": 0.5}
    assert scores["validated_provenance_rate"] == 0.5
    assert scores["dense_only_rate"] == 0.5
    assert scores["hybrid_ok_rate"] == 0.5
