from app.services.rag.decision_trace import (
    build_retrieval_decision_trace,
    build_trivial_retrieval_decision_trace,
)


def test_trivial_bypass_trace_is_explicit():
    trace = build_trivial_retrieval_decision_trace(reason="greeting", query="bonjour")

    assert trace["query_type"] == "trivial"
    assert trace["selected_route"] == "trivial_bypass"
    assert trace["trace_source"] == "runtime"
    assert "Skipped retrieval" in trace["tradeoff"]


def test_chah_trace_preserves_quality_controls_and_sources():
    trace = build_retrieval_decision_trace(
        request={"latency_profile": "balanced"},
        metrics={
            "pipeline": "chah_backend",
            "retrieval_profile": "chat",
            "retrieval_scope": {"intent": "exact_reference", "collections": ["andritz-notices"]},
            "retrieval_plan": {
                "layers": {
                    "dense": {"enabled": True, "status": "applied", "top_k": 12},
                    "sparse": {"enabled": True, "status": "applied", "top_k": 20},
                }
            },
            "sparse_status": "applied",
            "cross_encoder_status": "applied",
            "cross_encoder_ms": 18,
            "selected_sources": [{"label": "AKK200 manual", "score": 0.91}],
            "stage_timings": {"retrieval_ms": 112},
        },
    )

    assert trace["selected_route"] == "chah_backend"
    assert trace["query_type"] == "exact_reference"
    assert trace["quality_controls"]["sparse_status"] == "applied"
    assert trace["quality_controls"]["cross_encoder_status"] == "applied"
    assert trace["selected_sources"][0]["label"] == "AKK200 manual"


def test_sparse_timeout_trace_records_fallback():
    trace = build_retrieval_decision_trace(
        metrics={
            "pipeline": "dense_vector",
            "sparse_status": "timeout",
            "sparse_fallback_reason": "bm25_timeout",
            "dense_only": True,
            "deep_retrieval_recommended": True,
        },
    )

    assert trace["quality_controls"]["sparse_status"] == "timeout"
    assert any(item["kind"] == "sparse_fallback_reason" for item in trace["fallbacks"])
    assert trace["deep_search"]["recommended"] is True
