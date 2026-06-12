from app.services.rag.context import _compress_final_context


def _pool(ce_scores):
    chunks = [f"chunk-{i}" for i in range(len(ce_scores))]
    scores = [1.0 - i * 0.05 for i in range(len(ce_scores))]
    metadatas = [
        {"document_filename": f"d{i}.pdf", "cross_encoder_score": ce}
        if ce is not None
        else {"document_filename": f"d{i}.pdf"}
        for i, ce in enumerate(ce_scores)
    ]
    return chunks, scores, metadatas


def test_without_cross_encoder_falls_back_to_fixed_trim():
    chunks, scores, metadatas = _pool([None] * 8)
    out, _, _, diag = _compress_final_context(
        chunks, scores, metadatas, synthesis_k=4, cross_encoder_status="timeout"
    )
    assert out == chunks[:4]
    assert diag["compression_status"] == "fixed_trim"


def test_all_high_quality_keeps_synthesis_k():
    chunks, scores, metadatas = _pool([0.9] * 8)
    out, _, _, diag = _compress_final_context(
        chunks, scores, metadatas, synthesis_k=4, cross_encoder_status="applied"
    )
    assert out == chunks[:4]
    assert diag["compression_status"] == "proportional"
    assert diag["compression_kept"] == 4


def test_low_quality_tail_is_cut_to_ratio_floor():
    # Only 1 chunk above the floor, but the 0.7 ratio floor keeps ceil(4*0.7)=3.
    chunks, scores, metadatas = _pool([0.9, 0.1, 0.1, 0.1, 0.1, 0.1])
    out, _, _, diag = _compress_final_context(
        chunks, scores, metadatas, synthesis_k=4, cross_encoder_status="applied"
    )
    assert len(out) == 3
    assert diag["compression_status"] == "proportional"
    assert diag["compression_dropped"] == 3


def test_exempt_evidence_never_cut_and_not_counted():
    chunks, scores, metadatas = _pool([0.9, 0.1, 0.1, 0.1])
    metadatas.append({"source_type": "knowledge_guide"})
    chunks.append("guide")
    scores.append(1.0)
    out, _, out_metas, diag = _compress_final_context(
        chunks, scores, metadatas, synthesis_k=2, cross_encoder_status="applied"
    )
    assert "guide" in out
    assert diag["compression_status"] == "proportional"
    # ceil(2*0.7)=2 scored kept + the exempt guide.
    assert len(out) == 3
