from __future__ import annotations

import json

from app.services.rag.offline_eval import (
    RetrievalEvalCase,
    bge_m3_candidate,
    candidate_collection_name,
    embedding_candidate_eval_report,
    embedding_candidate_eval_report_from_exports,
    embedding_eval_candidate,
    load_retrieval_eval_cases,
    openai_text_embedding_3_large_candidate,
    score_retrieval_cases,
)


def test_bge_m3_candidate_is_isolated_from_global_embedding_settings():
    candidate = bge_m3_candidate()

    assert candidate.embedding_model == "bge-m3"
    assert candidate.embedding_provider == "openai_compatible_or_local"
    assert candidate.collection_suffix == "__eval_bge_m3"
    assert candidate.comparison_role == "exact_model_candidate"
    assert candidate.mutates_global_settings is False


def test_openai_large_candidate_is_dense_equivalent_not_exact_bge_m3():
    candidate = openai_text_embedding_3_large_candidate(dimensions=1536)

    assert candidate.embedding_provider == "openai"
    assert candidate.embedding_model == "text-embedding-3-large"
    assert candidate.embedding_dimensions == 1536
    assert candidate.collection_suffix == "__eval_openai_text_embedding_3_large_1536d"
    assert candidate.comparison_role == "dense_equivalent_candidate"
    assert candidate.mutates_global_settings is False
    assert candidate_collection_name("spl", candidate=candidate) == (
        "spl__eval_openai_text_embedding_3_large_1536d"
    )


def test_embedding_eval_candidate_registry_normalizes_names():
    assert embedding_eval_candidate("BAAI/bge-m3").collection_suffix == "__eval_bge_m3"
    assert embedding_eval_candidate("openai-large").embedding_model == "text-embedding-3-large"


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


def test_embedding_candidate_eval_report_compares_isolated_bge_m3_collection():
    baseline = [
        RetrievalEvalCase(
            query="SPL AKK200",
            expected_document_ids=("doc-a",),
            results=({"metadata": {"document_id": "doc-x", "status": "draft"}},),
            metrics={"dense_only": True, "sparse_status": "empty"},
        )
    ]
    candidate = [
        RetrievalEvalCase(
            query="SPL AKK200",
            expected_document_ids=("doc-a",),
            results=({"metadata": {"document_id": "doc-a", "status": "reviewed"}},),
            metrics={"dense_only": False, "sparse_status": "ok"},
        )
    ]

    report = embedding_candidate_eval_report(
        candidate=bge_m3_candidate(),
        baseline_cases=baseline,
        candidate_cases=candidate,
        ks=(1,),
    )

    assert report["isolated_candidate"] is True
    assert report["global_settings_mutation_allowed"] is False
    assert report["candidate"]["collection_suffix"] == "__eval_bge_m3"
    assert report["delta"]["recall_at_k"] == {"1": 1.0}
    assert report["delta"]["dense_only_rate"] == -1.0
    assert report["delta"]["hybrid_ok_rate"] == 1.0


def test_load_retrieval_eval_cases_accepts_json_and_jsonl_exports(tmp_path):
    json_path = tmp_path / "baseline.json"
    json_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "spl",
                        "query": "SPL AKK200",
                        "expected_document_ids": ["doc-a"],
                        "results": [{"metadata": {"document_id": "doc-x"}}],
                        "metrics": {"dense_only": True},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    jsonl_path = tmp_path / "candidate.jsonl"
    jsonl_path.write_text(
        json.dumps(
            {
                "id": "spl",
                "question": "SPL AKK200",
                "sources": [{"metadata": {"document_filename": "doc-a", "status": "reviewed"}}],
                "retrieval_trace": {"metrics": {"dense_only": False, "sparse_status": "ok"}},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    baseline = load_retrieval_eval_cases(json_path)
    candidate = load_retrieval_eval_cases(jsonl_path)

    assert baseline[0].case_id == "spl"
    assert baseline[0].expected_document_ids == ("doc-a",)
    assert candidate[0].query == "SPL AKK200"
    assert candidate[0].metrics["sparse_status"] == "ok"


def test_embedding_candidate_eval_report_from_exports_aligns_isolated_collection(tmp_path):
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.jsonl"
    baseline_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "spl",
                        "query": "SPL AKK200",
                        "expected_document_ids": ["doc-a"],
                        "results": [{"metadata": {"document_id": "doc-x", "status": "draft"}}],
                        "metrics": {"dense_only": True, "sparse_status": "empty"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    candidate_path.write_text(
        json.dumps(
            {
                "id": "spl",
                "query": "SPL AKK200",
                "sources": [{"metadata": {"document_filename": "doc-a", "status": "reviewed"}}],
                "metrics": {"dense_only": False, "sparse_status": "ok"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = embedding_candidate_eval_report_from_exports(
        candidate=bge_m3_candidate(),
        baseline_export=baseline_path,
        candidate_export=candidate_path,
        base_collection="andritz-spl",
        ks=(1,),
    )

    assert report["inputs"]["candidate_collection"] == "andritz-spl__eval_bge_m3"
    assert report["alignment"]["paired_cases"] == 1
    assert report["alignment"]["missing_candidate_cases"] == []
    assert report["candidate"]["comparison_role"] == "exact_model_candidate"
    assert report["delta"]["recall_at_k"] == {"1": 1.0}
    assert report["delta"]["dense_only_rate"] == -1.0
