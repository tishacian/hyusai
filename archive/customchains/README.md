# Archived custom chains (legacy Streamlit)

These three modules used to power the legacy Streamlit prototype:

| Legacy module                  | Purpose                                    | Replacement in new backend                                                                                     |
| ------------------------------ | ------------------------------------------ | -------------------------------------------------------------------------------------------------------------- |
| `customchain_naive.py`         | Single-pass vector RAG                     | `backend/app/services/rag/chains/naive.py` + canonical skill `chain_naive_v1`                                  |
| `customchain.py`               | Two-pass hybrid (BM25 + dense) HAH RAG     | `backend/app/services/rag/chains/hybrid.py` + canonical skill `chain_hybrid_v1` (uses `retrieve_hah_like`)      |
| `customchainmixedhah.py`       | Parallel multi-strategy composite HAH RAG  | `backend/app/services/rag/chains/mixed_hah.py` + canonical skill `chain_mixed_hah_v1` (uses `retrieve_chah_like`)|

The new chains delegate through `app.services.rag.rag_service.answer()`
which aggregates the orchestrator's streamed response into a single
payload. They no longer depend on `langchain`, `weaviate`, `vllm`,
`faiss-cpu` or `torch`, so they work in any environment where the new
backend runs.

These files are kept for historical reference only. Do **not** import
from this directory — production code must use the canonical skill
registry (`app.services.skills_registry`) instead.
