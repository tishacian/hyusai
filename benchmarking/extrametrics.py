"""
Created on Fri Dec  6 01:47:23 2024

@author: kennethezukwoke
"""

import nltk
import numpy as np
from rouge import Rouge
from sklearn.metrics.pairwise import cosine_similarity


class ExtraMetrics:
    def __init__(self):
        """Initialize RAG evaluation metrics calculator"""
        self.rouge = Rouge()
        try:
            nltk.download("punkt", quiet=True)
        except Exception as e:
            print(f"Error initializing NLTK: {e}")

    def compute_ndcg(
        self,
        retrieved_docs: list[str],
        relevant_docs: list[str],
        embeddings_model,
        k: int = None,
    ) -> float:
        """Compute Normalized Discounted Cumulative Gain"""
        if not retrieved_docs or not relevant_docs:
            return 0.0

        if k is not None:
            retrieved_docs = retrieved_docs[:k]

        def dcg_at_k(r, k):
            r = np.asfarray(r)[:k]
            if r.size:
                return np.sum(
                    np.subtract(np.power(2, r), 1) / np.log2(np.arange(2, r.size + 2))
                )
            return 0.0

        # Calculate relevance scores
        relevance_scores = []
        for doc in retrieved_docs:
            max_score = 0
            doc_embedding = embeddings_model.encode(doc, show_progress_bar=False)

            for rel_doc in relevant_docs:
                rel_embedding = embeddings_model.encode(
                    rel_doc, show_progress_bar=False
                )
                similarity = float(
                    cosine_similarity(
                        doc_embedding.reshape(1, -1),
                        rel_embedding.reshape(1, -1),
                    )[0][0]
                )
                max_score = max(max_score, similarity)

            relevance_scores.append(max_score)

        dcg = dcg_at_k(relevance_scores, len(retrieved_docs))
        idcg = dcg_at_k(sorted(relevance_scores, reverse=True), len(retrieved_docs))

        return dcg / idcg if idcg > 0 else 0.0

    def compute_rouge_scores(self, hypothesis: str, reference: str) -> dict[str, float]:
        """Compute ROUGE scores"""
        if not hypothesis or not reference:
            return {"rouge1": 0.0, "rouge2": 0.0, "rougeL": 0.0}

        try:
            hypothesis = str(hypothesis).strip()
            reference = str(reference).strip()

            if not hypothesis or not reference:
                return {"rouge1": 0.0, "rouge2": 0.0, "rougeL": 0.0}

            if len(hypothesis.split()) == 1 or len(reference.split()) == 1:
                exact_match = float(hypothesis.lower() == reference.lower())
                return {
                    "rouge1": exact_match,
                    "rouge2": 0.0,
                    "rougeL": exact_match,
                }

            scores = self.rouge.get_scores(hypothesis, reference)[0]
            return {
                "rouge1": float(scores["rouge-1"]["f"]),
                "rouge2": float(scores["rouge-2"]["f"]),
                "rougeL": float(scores["rouge-l"]["f"]),
            }

        except Exception as e:
            print(f"Error computing ROUGE scores: {e}")
            return {"rouge1": 0.0, "rouge2": 0.0, "rougeL": 0.0}

    def evaluate_rag(
        self,
        retrieved_docs: list[str],
        generated_answer: str,
        relevant_docs: list[str],
        ground_truth: str,
        embeddings_model,
        k: int = 12,
    ) -> dict[str, float]:
        """Comprehensive RAG evaluation with all metrics"""
        try:
            metrics = {}
            metrics["ndcg"] = self.compute_ndcg(
                retrieved_docs, relevant_docs, embeddings_model, k
            )
            rouge_scores = self.compute_rouge_scores(generated_answer, ground_truth)
            metrics.update(rouge_scores)
            return metrics

        except Exception as e:
            print(f"Error in evaluate_rag: {e}")
            return {
                "ndcg": 0.0,
                "rouge1": 0.0,
                "rouge2": 0.0,
                "rougeL": 0.0,
            }
