#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Feb 7 15:48:53 2025

@author: kennethezukwoke
"""
import torch
import numpy as np

# --
import warnings

warnings.simplefilter(action="ignore", category=FutureWarning)

# --
import sys
import logging
from enum import Enum

# --
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple, Union
from transformers import AutoModelForSequenceClassification, AutoTokenizer

# --
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# %% Flash Reranker


class RerankerMode(Enum):
    """Defines reranking modes for FlashReranker"""

    PAIRWISE = "pairwise"  # Compare pairs of documents
    POINTWISE = "pointwise"  # Score documents individually
    LISTWISE = "listwise"  # Evaluate entire list at once


@dataclass
class RerankerConfig:
    """Configuration for FlashReranker"""

    batch_size: int = 32
    max_length: int = 512
    mode: RerankerMode = RerankerMode.POINTWISE
    num_threads: int = 4
    threshold: float = 0.5
    device: Optional[str] = None


class FlashReranker:
    """Fast and efficient reranking with memory management"""

    def __init__(self, config: Optional[RerankerConfig] = None):
        self.config = config or RerankerConfig()
        try:
            # Try CUDA first
            if torch.cuda.is_available():
                torch.cuda.empty_cache()  # Clear CUDA cache
                self.device = "cuda"
            else:
                self.device = "cpu"
        except Exception:
            self.device = "cpu"

        logging.info(f"Using device: {self.device}")

        try:
            # Initialize model and tokenizer on CPU first
            self.model = AutoModelForSequenceClassification.from_pretrained(
                "cross-encoder/ms-marco-MiniLM-L-12-v2"
            )
            self.tokenizer = AutoTokenizer.from_pretrained(
                "cross-encoder/ms-marco-MiniLM-L-12-v2"
            )

            # Move model to device only if CUDA is available and has enough memory
            if self.device == "cuda":
                try:
                    self.model = self.model.to(self.device)
                except RuntimeError:
                    logging.warning(
                        "CUDA memory insufficient, falling back to CPU"
                    )
                    self.device = "cpu"
                    torch.cuda.empty_cache()

            self.model.eval()

        except Exception as e:
            logging.error(f"Error initializing model/tokenizer: {e}")
            raise

    def _batch_tokenize(
        self, query: str, passages: List[str]
    ) -> Dict[str, torch.Tensor]:
        """Tokenize with memory-efficient batching"""
        try:
            pairs = [(query, passage) for passage in passages]
            inputs = self.tokenizer(
                pairs,
                padding=True,
                truncation=True,
                max_length=self.config.max_length,
                return_tensors="pt",
            )

            # Move to device in a memory-efficient way
            if self.device == "cuda":
                try:
                    inputs = {k: v.to(self.device) for k, v in inputs.items()}
                except RuntimeError:
                    logging.warning(
                        "CUDA memory insufficient for batch, processing on CPU"
                    )
                    self.device = "cpu"
                    torch.cuda.empty_cache()

            return inputs

        except Exception as e:
            logging.error(f"Error in batch tokenization: {e}")
            return self.tokenizer(
                [(query, "")],  # Fallback with empty passage
                padding=True,
                truncation=True,
                max_length=self.config.max_length,
                return_tensors="pt",
            )

    def _compute_relevance_scores(
        self, inputs: Dict[str, torch.Tensor]
    ) -> torch.Tensor:
        """Compute scores with memory management"""
        try:
            with torch.no_grad():
                if self.device == "cuda":
                    try:
                        outputs = self.model(**inputs)
                    except RuntimeError:
                        # If CUDA fails, fall back to CPU
                        logging.warning(
                            "CUDA error in scoring, falling back to CPU"
                        )
                        self.device = "cpu"
                        torch.cuda.empty_cache()
                        inputs = {k: v.cpu() for k, v in inputs.items()}
                        self.model = self.model.cpu()
                        outputs = self.model(**inputs)
                else:
                    outputs = self.model(**inputs)

                scores = torch.sigmoid(outputs.logits)
                if scores.dim() == 0:
                    scores = scores.unsqueeze(0)
                return scores.squeeze()

        except Exception as e:
            logging.error(f"Error computing relevance scores: {e}")
            return torch.zeros(1)

    def _batch_process(
        self, query: str, passages: List[str], batch_size: int
    ) -> List[float]:
        """Process passages in memory-efficient batches"""
        all_scores = []
        for i in range(0, len(passages), batch_size):
            try:
                batch = passages[i : i + batch_size]
                inputs = self._batch_tokenize(query, batch)
                scores = self._compute_relevance_scores(inputs)

                if isinstance(scores, torch.Tensor):
                    if scores.dim() == 0:
                        scores = scores.unsqueeze(0)
                    scores = scores.cpu().numpy()
                    if isinstance(scores, np.ndarray) and scores.ndim == 0:
                        scores = np.array([float(scores)])

                all_scores.extend(scores)

                # Clear memory after each batch
                if self.device == "cuda":
                    torch.cuda.empty_cache()

            except Exception as e:
                logging.error(f"Error processing batch: {e}")
                all_scores.extend([0.0] * len(batch))

        return all_scores

    def rerank(
        self, query: str, passages: List[str], return_scores: bool = False
    ) -> Union[List[str], Tuple[List[str], List[float]]]:
        """Memory-efficient reranking"""
        try:
            # Reduce batch size if on CPU
            batch_size = (
                self.config.batch_size
                if self.device == "cuda"
                else max(1, self.config.batch_size // 4)
            )

            # Compute scores
            scores = self._batch_process(query, passages, batch_size)

            # Sort and filter
            scored_passages = list(zip(passages, scores))
            scored_passages.sort(key=lambda x: x[1], reverse=True)

            filtered = [
                (p, s)
                for p, s in scored_passages
                if s >= self.config.threshold
            ]
            if not filtered:
                filtered = scored_passages

            reranked_passages, final_scores = zip(*filtered)

            return (
                (list(reranked_passages), list(final_scores))
                if return_scores
                else list(reranked_passages)
            )

        except Exception as e:
            logging.error(f"Error during reranking: {e}")
            if return_scores:
                return passages, [0.0] * len(passages)
            return passages

    def evaluate(
        self,
        queries: List[str],
        passages: List[List[str]],
        relevance_labels: List[List[int]],
    ) -> Dict[str, float]:
        """Evaluate reranker performance

        Args:
            queries: List of queries
            passages: List of passage lists for each query
            relevance_labels: Ground truth relevance labels

        Returns:
            Dictionary of evaluation metrics
        """
        metrics = {
            "mrr": [],  # Mean Reciprocal Rank
            "precision@1": [],
            "ndcg@10": [],  # Normalized Discounted Cumulative Gain
        }

        for query, query_passages, labels in zip(
            queries, passages, relevance_labels
        ):
            try:
                reranked_passages, scores = self.rerank(
                    query, query_passages, return_scores=True
                )

                # Compute ranking metrics
                ranked_labels = [
                    labels[query_passages.index(p)] for p in reranked_passages
                ]

                # MRR
                for i, label in enumerate(ranked_labels, 1):
                    if label > 0:
                        metrics["mrr"].append(1.0 / i)
                        break
                else:
                    metrics["mrr"].append(0.0)

                # P@1
                metrics["precision@1"].append(
                    1.0 if ranked_labels[0] > 0 else 0.0
                )

                # NDCG@10
                dcg = sum(
                    (2**label - 1) / np.log2(i + 2)
                    for i, label in enumerate(ranked_labels[:10])
                )
                ideal_labels = sorted(labels, reverse=True)[:10]
                idcg = sum(
                    (2**label - 1) / np.log2(i + 2)
                    for i, label in enumerate(ideal_labels)
                )
                metrics["ndcg@10"].append(dcg / idcg if idcg > 0 else 0.0)

            except Exception as e:
                logging.error(f"Error evaluating query: {e}")
                continue

        # Average metrics
        return {metric: np.mean(values) for metric, values in metrics.items()}

    def __call__(
        self, query: str, passages: List[str], return_scores: bool = False
    ) -> Union[List[str], Tuple[List[str], List[float]]]:
        """Convenience method to rerank passages

        Args:
            query: Search query
            passages: List of passages to rerank
            return_scores: Whether to return relevance scores

        Returns:
            Reranked passages and optionally their scores
        """
        return self.rerank(query, passages, return_scores)
