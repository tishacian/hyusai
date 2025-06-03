#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Feb 14 16:58:25 2025

@author: kennethezukwoke
"""

import re
import sys
import logging
import numpy as np
from configuration import get_backend_config
from globalvariables import ReasoningType
from src.reasonning_instructions import ALL_REASONING_PATTERNS

# --
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


class ReasoningMetrics:
    def __init__(self, embedding_model):
        """
        Parameters
            embedding_model (model): embedding model

        Returns
            None.
        """
        self.embedding_model = embedding_model
        self.raw_reasoning_patterns = ALL_REASONING_PATTERNS[get_backend_config().language]
        self.reasoning_patterns = self._precompile_patterns(self.raw_reasoning_patterns)
        self.reasoning_weights = {
            ReasoningType.FACTUAL: 1.4,
            ReasoningType.ANALYTICAL: 1.25,
            ReasoningType.COMPARATIVE: 1.0,
            ReasoningType.CAUSAL: 1.2,
            ReasoningType.HYPOTHETICAL: 0.8,
        }

        self.entropy_thresholds = {
            ReasoningType.FACTUAL: 0.25,
            ReasoningType.ANALYTICAL: 0.35,
            ReasoningType.COMPARATIVE: 0.45,
            ReasoningType.CAUSAL: 0.3,
            ReasoningType.HYPOTHETICAL: 0.5,
        }

        self.quality_multipliers = {
            "coherence": {
                ReasoningType.FACTUAL: 1.3,
                ReasoningType.ANALYTICAL: 1.25,
                ReasoningType.COMPARATIVE: 1.1,
                ReasoningType.CAUSAL: 1.2,
                ReasoningType.HYPOTHETICAL: 1.0,
            },
            "factuality": {
                ReasoningType.FACTUAL: 1.4,
                ReasoningType.ANALYTICAL: 1.2,
                ReasoningType.COMPARATIVE: 1.1,
                ReasoningType.CAUSAL: 1.15,
                ReasoningType.HYPOTHETICAL: 0.9,
            },
            "relevance": {
                ReasoningType.FACTUAL: 1.25,
                ReasoningType.ANALYTICAL: 1.2,
                ReasoningType.COMPARATIVE: 1.15,
                ReasoningType.CAUSAL: 1.1,
                ReasoningType.HYPOTHETICAL: 1.0,
            },
        }

        # -- vectorize weights
        self.type_feature_weights = {
            ReasoningType.FACTUAL: np.array([0.4, 0.4, 0.2]),
            ReasoningType.ANALYTICAL: np.array([0.3, 0.4, 0.3]),
            ReasoningType.COMPARATIVE: np.array([0.2, 0.4, 0.4]),
            ReasoningType.CAUSAL: np.array([0.3, 0.3, 0.4]),
            ReasoningType.HYPOTHETICAL: np.array([0.2, 0.5, 0.3]),
        }
        # -- shared caches
        self._embedding_cache = {}
        self._pattern_matches_cache = {}
        self._reasoning_type_cache = {}
        self._entropy_cache = {}

        # -- precompute reasoning embeddings
        self._reasoning_type_embeddings = (
            self._precompute_reasoning_embeddings()
        )
        self.pattern_token_sets = self._create_pattern_token_sets()

    def _precompile_patterns(self, patterns_dict):
        """Precompile regex patterns

        Parameters
        ----------
        patterns_dict : dict
            pattern dictionary.

        Returns
        -------
        compiled_patterns : dict
            compiled patterns.

        """
        compiled_patterns = {}
        for rtype, patterns in patterns_dict.items():
            compiled_patterns[rtype] = [
                re.compile(r"\b" + pattern + r"\b", re.IGNORECASE)
                for pattern in patterns
            ]
        return compiled_patterns

    def _precompute_reasoning_embeddings(self):
        """Precompute and cache embeddings for reasoning types

        Returns
        -------
        embeddings_dict : embedding_dit
            Embedding dictionary.

        """
        embeddings_dict = {}
        reasoning_texts = [str(rtype.value) for rtype in ReasoningType]

        try:
            embeddings = self.embedding_model.encode(reasoning_texts)
            for i, rtype in enumerate(ReasoningType):
                embeddings_dict[rtype] = embeddings[i]
                self._embedding_cache[hash(str(rtype.value))] = embeddings[i]
        except Exception as e:
            logging.error(f"Error precomputing reasoning embeddings: {e}")

        return embeddings_dict

    def _create_pattern_token_sets(self):
        """Pattern tokens

        Returns
        -------
        token_sets : set
            pattern tokens for each reasoning type for faster initial filtering.

        """
        token_sets = {}
        for rtype, patterns in self.raw_reasoning_patterns.items():
            token_set = set()
            for pattern in patterns:
                tokens = pattern.lower().split()
                token_set.update(tokens)
            token_sets[rtype] = token_set
        return token_sets

    def compute_cosine_similarity(self, vec1_hash, vec2_hash) -> float:
        """Compute cosine similarity using cached vectors

        Parameters
        ----------
        vec1_hash : int
            Hash key for the first vector in cache
        vec2_hash : int
            Hash key for the second vector in cache

        Returns
        -------
        float
            Cosine similarity
        """
        vec1 = self._embedding_cache.get(vec1_hash)
        vec2 = self._embedding_cache.get(vec2_hash)

        if vec1 is None or vec2 is None:
            return 0.0

        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        return dot_product / (norm1 * norm2) if norm1 * norm2 != 0 else 0.0

    def compute_pattern_entropy(
        self, text: str, pattern_type: ReasoningType
    ) -> float:
        """Compute entropy of reasoning patterns in text using Shannon entropy

        Parameters
        ----------
        text : str
            Input text
        pattern_type : ReasoningType
            Reasoning pattern type

        Returns
        -------
        float
            Entropy score
        """
        cache_key = (hash(text), pattern_type)
        if cache_key in self._entropy_cache:
            return self._entropy_cache[cache_key]

        # Get cached pattern matches or find them
        matches_dict = self._find_pattern_matches(text)
        matched_patterns = matches_dict.get(pattern_type, [])

        if not matched_patterns:
            self._entropy_cache[cache_key] = 0.0
            return 0.0

        # Count pattern occurrences
        pattern_counts = {}
        for pattern in matched_patterns:
            pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1

        total_patterns = sum(pattern_counts.values())

        # Compute entropy
        probabilities = (
            np.array(list(pattern_counts.values())) / total_patterns
        )
        entropy = -np.sum(probabilities * np.log2(probabilities))

        self._entropy_cache[cache_key] = entropy
        return entropy

    def get_text_embedding(self, text: str) -> np.ndarray:
        """Get text embedding with caching

        Parameters
        ----------
        text : str
            Input text

        Returns
        -------
        np.ndarray
            Text embedding
        """
        text_hash = hash(text)
        if text_hash in self._embedding_cache:
            return self._embedding_cache[text_hash]

        try:
            embedding = self.embedding_model.encode([text])[0]
            self._embedding_cache[text_hash] = embedding
            return embedding
        except Exception as e:
            logging.error(f"Error getting text embedding: {e}")
            return np.zeros(
                self.embedding_model.get_sentence_embedding_dimension()
            )

    async def get_text_embedding_async(self, text: str) -> np.ndarray:
        """Asynchronous version of get_text_embedding for compatibility

        Parameters
        ----------
        text : str
            Input text

        Returns
        -------
        np.ndarray
            Text embedding
        """
        return self.get_text_embedding(text)

    def _find_pattern_matches(self, text: str):
        """Find all pattern matches in text for all reasoning types

        Parameters
        ----------
        text : str
            Input text

        Returns
        -------
        Dict[ReasoningType, List[str]]
            Dictionary mapping reasoning types to lists of matched patterns
        """
        text_hash = hash(text)
        if text_hash in self._pattern_matches_cache:
            return self._pattern_matches_cache[text_hash]

        text_lower = text.lower()
        matches = {}
        candidate_types = []
        text_tokens = set(text_lower.split())
        for rtype, token_set in self.pattern_token_sets.items():
            if text_tokens.intersection(token_set):
                candidate_types.append(rtype)

        # -- regex matching on candidate types
        for rtype in candidate_types:
            pattern_matches = []
            for pattern in self.reasoning_patterns[rtype]:
                if pattern.search(text_lower):
                    pattern_matches.append(pattern.pattern[2:-2])
            matches[rtype] = pattern_matches

        # -- empty lists for types without matches
        for rtype in ReasoningType:
            if rtype not in matches:
                matches[rtype] = []

        self._pattern_matches_cache[text_hash] = matches
        return matches

    def compute_pattern_entropy(
        self, text: str, pattern_type: ReasoningType
    ) -> float:
        """Compute entropy of reasoning patterns in text using Shannon entropy

        Parameters
        ----------
        text : str
            Input text
        pattern_type : ReasoningType
            Reasoning pattern type

        Returns
        -------
        float
            Entropy score
        """
        cache_key = (hash(text), pattern_type)
        if cache_key in self._entropy_cache:
            return self._entropy_cache[cache_key]

        # -- get cached pattern matches or find them
        matches_dict = self._find_pattern_matches(text)
        matched_patterns = matches_dict.get(pattern_type, [])

        if not matched_patterns:
            self._entropy_cache[cache_key] = 0.0
            return 0.0

        # -- count pattern occurrences
        pattern_counts = {}
        for pattern in matched_patterns:
            pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1

        total_patterns = sum(pattern_counts.values())

        # -- compute entropy
        probabilities = (
            np.array(list(pattern_counts.values())) / total_patterns
        )
        entropy = -np.sum(probabilities * np.log2(probabilities))

        self._entropy_cache[cache_key] = entropy
        return entropy

    def compute_semantic_coherence(
        self, text: str, reasoning_type: ReasoningType
    ) -> float:
        """Compute semantic coherence score using embedding similarity

        Parameters
        ----------
        text : str
            Input text
        reasoning_type : ReasoningType
            reasoning type.

        Returns
        -------
        float
            Coherence score.
        """
        text_hash = hash(text)
        if text_hash not in self._embedding_cache:
            self._embedding_cache[text_hash] = self.get_text_embedding(text)

        # -- compute type embedding
        type_text = str(reasoning_type.value)
        type_hash = hash(type_text)
        if type_hash not in self._embedding_cache:
            self._embedding_cache[type_hash] = self.embedding_model.encode(
                [type_text]
            )[0]
            self._reasoning_type_embeddings[reasoning_type] = (
                self._embedding_cache[type_hash]
            )

        return self.compute_cosine_similarity(text_hash, type_hash)

    def _compute_feature_vector(self, text: str, question: str = None):
        """One pass compute feature vectors for all reasoning types

        Parameters
        ----------
        text : str
            Input text
        question : str, optional
            Question text for combined analysis

        Returns
        -------
        Dict[ReasoningType, np.ndarray]
            Dictionary mapping reasoning types to feature vectors
        """
        combined_text = question + " " + text if question else text
        combined_hash = hash(combined_text)

        # -- compute text embedding
        if combined_hash not in self._embedding_cache:
            self._embedding_cache[combined_hash] = self.get_text_embedding(
                combined_text
            )

        pattern_matches = self._find_pattern_matches(text)
        # -- compute features for all reasoning types
        feature_vectors = {}
        for rtype in ReasoningType:
            entropy = self.compute_pattern_entropy(text, rtype)
            entropy_score = (
                1.0 if entropy >= self.entropy_thresholds[rtype] else 0.5
            )

            type_text = str(rtype.value)
            type_hash = hash(type_text)
            coherence_score = self.compute_cosine_similarity(
                combined_hash, type_hash
            )
            matches = pattern_matches.get(rtype, [])
            total_patterns = len(ReasoningPatterns[rtype])
            coverage = (
                len(matches) / total_patterns if total_patterns > 0 else 0
            )
            feature_vectors[rtype] = np.array(
                [entropy_score, coherence_score, coverage]
            )

        return feature_vectors

    def bayesian_reasoning_detection(self, question: str):
        """Bayesian reasoning detection

        Parameters
        ----------
        question : str
            Input question

        Returns
        -------
        Tuple[ReasoningType, float]
            reasoning type w/ confidence score
        """
        question_hash = hash(question)
        if question_hash in self._reasoning_type_cache:
            return self._reasoning_type_cache[question_hash]

        # -- compute all features in one pass
        feature_vectors = self._compute_feature_vector(question)
        evidence = {}
        for rtype in ReasoningType:
            weighted_score = np.dot(
                feature_vectors[rtype], self.type_feature_weights[rtype]
            )
            evidence[rtype] = weighted_score * self.reasoning_weights[rtype]

        # -- uniform priors
        priors = {rtype: 1.0 / len(ReasoningType) for rtype in ReasoningType}
        # -- compute posterior probabilities
        total_evidence = sum(evidence.values())
        if total_evidence == 0:
            result = (ReasoningType.ANALYTICAL, 0.5)
            self._reasoning_type_cache[question_hash] = result
            return result

        posteriors = {
            rtype: (evidence[rtype] / total_evidence) * priors[rtype]
            for rtype in ReasoningType
        }

        rzn_type = max(posteriors.items(), key=lambda x: x[1])
        result = (rzn_type[0], rzn_type[1])
        self._reasoning_type_cache[question_hash] = result
        return result

    async def compute_reasoning_score_async(
        self, question: str, context: str, reasoning_type: ReasoningType
    ) -> float:
        """Compute reasoning score during search phase asynchronously

        Parameters
        ----------
        question (str): Input question
        context (str): Context
        reasoning_type : ReasoningType
            Reasoning type.

        Returns
        -------
        float
            Reasoning score.
        """
        return self.compute_reasoning_score(question, context, reasoning_type)

    async def bayesian_reasoning_detection_async(self, question: str):
        """Async bayesian_reasoning_detection

        Parameters
        ----------
        question (str): Input prompt

        Returns
        -------
        Tuple[ReasoningType, float]
            reasoning type and confidence score
        """
        return self.bayesian_reasoning_detection(question)

    def compute_reasoning_score(
        self, question: str, context: str, reasoning_type: ReasoningType
    ) -> float:
        """Compute reasoning score for a given context

        Parameters
        ----------
        question : str
            Input question
        context : str
            Context text
        reasoning_type : ReasoningType
            Reasoning type

        Returns
        -------
        float
            Reasoning score
        """
        feature_vector = self._compute_feature_vector(context, question)[
            reasoning_type
        ]
        score = np.dot(
            feature_vector, self.type_feature_weights[reasoning_type]
        )

        return score
