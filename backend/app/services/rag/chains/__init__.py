"""Canonical RAG chains (naive, hybrid, mixed-HAH).

Thin wrappers that describe which retrieval pipeline to use + delegate
to `rag_service.answer()`. This is the modern replacement for the
legacy `src/customchain*.py` Streamlit modules which depended on a full
langchain / FAISS / vLLM stack that is not shipped with the new
backend. The canonical skills `chain_naive_v1`, `chain_hybrid_v1` and
`chain_mixed_hah_v1` bind to the helpers exported here.
"""
from .naive import answer_naive
from .hybrid import answer_hybrid
from .mixed_hah import answer_mixed_hah

__all__ = ["answer_naive", "answer_hybrid", "answer_mixed_hah"]
