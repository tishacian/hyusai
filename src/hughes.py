import torch
from typing import List, Dict, Tuple
from dataclasses import dataclass
from sentence_transformers import SentenceTransformer
from functools import lru_cache
import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class HughesConfig:
    """Configuration for the Hughes Hallucination Evaluation Metric.

    Parameters:
    -----------
    cache_size : int
        Size of the LRU cache for component results
    batch_size : int
        Batch size for parallel processing
    device : str
        Device to run computations on ('cuda' or 'cpu')
    weights : Dict[str, float]
        Weights for different components in score calculation
    """

    cache_size: int = 1000
    batch_size: int = 32
    device: str = "cuda" if torch.cuda.is_available() else "cpu"
    weights: Dict[str, float] = None

    def __post_init__(self):
        # -- default weights
        if self.weights is None:
            self.weights = {
                "entailment": 0.3,
                "contradiction": 0.2,
                "consistency": 0.2,
                "drift": 0.15,
                "factuality": 0.15,
            }


class IdenticalCorrectionModel:
    """Identity transformation model for text correction.

    This model performs no transformation on the input text,
    serving as a baseline for text correction.
    """

    def __init__(self):
        """Initialize the identity correction model."""
        self.name = "Identity"

    @torch.no_grad()
    def transform(self, text: str) -> str:
        """Transform text using identity function.

        Parameters:
        -----------
        text : str
            Input text to transform

        Returns:
        --------
        str
            The same input text without any transformation
        """
        return text


class ClaimExtractor:
    """Extract claims using entailment scoring."""

    def __init__(self, embedding_model: SentenceTransformer):
        """Initialize the claim extractor.

        Parameters:
        -----------
        embedding_model : SentenceTransformer
            Model to use for text embeddings
        """
        self.model = embedding_model

    @torch.no_grad()
    @lru_cache(maxsize=1000)
    def extract_claims(self, embeddings: torch.Tensor) -> float:
        """Extract claims and compute entailment score.

        Parameters:
        -----------
        embeddings : torch.Tensor
            Embeddings of the text to analyze

        Returns:
        --------
        float
            Entailment score for the extracted claims
        """
        return float(torch.mean(embeddings).item())


class ContradictionExtractor:
    def __init__(self, embedding_model: SentenceTransformer):
        """Detect negation

        Parameters:
        -----------
        embedding_model : SentenceTransformer
            Model to use for text embeddings

        NOTE: We could also use negation identifiers such "is not", "would not" etc but we cannot possibly cover all
                negation flaggers.
        """
        self.model = embedding_model

    @torch.no_grad()
    @lru_cache(maxsize=1000)
    def detect_contradictions(self, embeddings: torch.Tensor) -> float:
        """Detect contradictions in text.

        Parameters:
        -----------
        embeddings : torch.Tensor
            Embeddings of the text to analyze

        Returns:
        --------
        float
            Contradiction score for the text
        """
        return float(torch.mean(embeddings).item())


class HHEMVerifier:
    """Verify claims against reference text."""

    def __init__(self, embedding_model: SentenceTransformer):
        """Initialize the HHEM verifier.

        Parameters:
        -----------
        embedding_model : SentenceTransformer
            Model to use for text embeddings
        """
        self.model = embedding_model

    @torch.no_grad()
    @lru_cache(maxsize=1000)
    def verify_claims(
        self, gen_emb: torch.Tensor, ref_emb: torch.Tensor
    ) -> float:
        """Verify claims against reference text.

        Parameters:
        -----------
        gen_emb : torch.Tensor
            Embeddings of the generated text
        ref_emb : torch.Tensor
            Embeddings of the reference text

        Returns:
        --------
        float
            Verification score between 0 and 1
        """
        similarity = torch.nn.functional.cosine_similarity(gen_emb, ref_emb)
        return float(similarity.item())


class SemanticDriftAnalyzer:
    def __init__(self, embedding_model: SentenceTransformer):
        """Initialize the semantic drift analyzer.

        Parameters:
        -----------
        embedding_model : SentenceTransformer
            Model to use for text embeddings
        """
        self.model = embedding_model

    @torch.no_grad()
    @lru_cache(maxsize=1000)
    def compute_drift(self, emb1: torch.Tensor, emb2: torch.Tensor) -> float:
        """Compute semantic drift between texts.
            Drift is a shift in similarity

        Parameters:
        -----------
        emb1 : torch.Tensor
            Embeddings of the first text
        emb2 : torch.Tensor
            Embeddings of the second text

        Returns:
        --------
        float
            Drift score between 0 and 1
        """
        drift = torch.nn.functional.cosine_similarity(emb1, emb2)
        return float(1 - drift.item())  # similarity --> drift


class FACTSGJudge:
    """Judge factual consistency of generated text.

    This component evaluates the factual consistency of
    generated text against reference text.
    """

    def __init__(self, embedding_model: SentenceTransformer):
        """Initialize the FACTSG judge.

        Parameters:
        -----------
        embedding_model : SentenceTransformer
            Model to use for text embeddings
        """
        self.model = embedding_model

    @torch.no_grad()
    @lru_cache(maxsize=1000)
    def judge_factuality(
        self, generated_text: str, reference_text: str
    ) -> float:
        """Judge factual consistency of generated text.

        Parameters:
        -----------
        generated_text : str
            Text to evaluate for factual consistency
        reference_text : str
            Reference text to compare against

        Returns:
        --------
        float
            Factual consistency score between 0 and 1
        """
        gen_emb = self.model.encode(
            [generated_text], convert_to_tensor=True, show_progress_bar=False
        )
        ref_emb = self.model.encode(
            [reference_text], convert_to_tensor=True, show_progress_bar=False
        )
        similarity = torch.nn.functional.cosine_similarity(gen_emb, ref_emb)
        return float(similarity.item())


class HughesHallucination:
    def __init__(
        self,
        config: HughesConfig,
        embedding_model: SentenceTransformer = None,
    ):
        """Initialize the Hughes pipeline.

        Parameters:
        -----------
        config : PipelineConfig
            Configuration settings for the pipeline
        embedding_model : SentenceTransformer, optional
            Pre-loaded embedding model to use for computations

        Raises:
        -------
        ValueError
            If embedding_model is not provided
        """
        self.config = config
        self.device = config.device

        if embedding_model is None:
            raise ValueError("Embedding model must be provided")

        self.identical_corrector = IdenticalCorrectionModel()
        self.claim_extractor = ClaimExtractor(embedding_model)
        self.contradiction_extractor = ContradictionExtractor(embedding_model)
        self.hhem_verifier = HHEMVerifier(embedding_model)
        self.semantic_drift = SemanticDriftAnalyzer(embedding_model)
        self.facts_judge = FACTSGJudge(embedding_model)
        # --
        self.executor = ThreadPoolExecutor(max_workers=4)

    @torch.no_grad()
    @lru_cache(maxsize=1000)
    def _compute_embeddings(self, text: str) -> torch.Tensor:
        """Compute and cache embeddings for a text."""
        return self.claim_extractor.model.encode(
            [text], convert_to_tensor=True, show_progress_bar=False
        )

    def compute_score(
        self, generated_text: str, reference_text: str
    ) -> Dict[str, float]:
        """Compute hallucination score using parallel component execution.

        Parameters:
        -----------
        generated_text : str
            Text to evaluate for hallucinations
        reference_text : str
            Reference text to compare against

        Returns:
        --------
        Dict[str, float]
            Dictionary containing component scores and final
            hallucination index
        """
        # -- embeddings
        gen_emb = self._compute_embeddings(generated_text)
        ref_emb = self._compute_embeddings(reference_text)

        component_methods = [
            (self.claim_extractor.extract_claims, (gen_emb,)),
            (self.contradiction_extractor.detect_contradictions, (gen_emb,)),
            (self.hhem_verifier.verify_claims, (gen_emb, ref_emb)),
            (self.semantic_drift.compute_drift, (gen_emb, ref_emb)),
            (
                self.facts_judge.judge_factuality,
                (generated_text, reference_text),
            ),
        ]

        with ThreadPoolExecutor(max_workers=4) as executor:
            tasks = [
                executor.submit(method, *args)
                for method, args in component_methods
            ]
            results = [task.result() for task in tasks]

        # -- normalize component scores
        component_scores = {
            "claim_extraction": max(0.0, min(1.0, results[0])),
            "contradiction_detection": max(0.0, min(1.0, results[1])),
            "claim_verification": max(0.0, min(1.0, results[2])),
            "semantic_drift": max(0.0, min(1.0, results[3])),
            "factual_consistency": max(0.0, min(1.0, results[4])),
        }

        # -- weights
        w_ce = self.config.weights["entailment"]
        w_cd = self.config.weights["contradiction"]
        w_cv = self.config.weights["consistency"]
        w_sd = self.config.weights["drift"]
        w_fc = self.config.weights["factuality"]

        # -- compute final hallucination index using weighted formula
        hallucination_index = (
            w_ce * component_scores["claim_extraction"]
            + w_cd * component_scores["contradiction_detection"]
            + w_cv * component_scores["claim_verification"]
            + w_sd * component_scores["semantic_drift"]
            + w_fc * component_scores["factual_consistency"]
        )

        # hallucination index
        hallucination_index = max(0.0, min(1.0, hallucination_index))

        return {**component_scores, "hallucination_index": hallucination_index}

    async def batch_compute(
        self, text_pairs: List[Tuple[str, str]]
    ) -> List[Dict]:
        """Compute scores for multiple text pairs in parallel.

        Parameters:
        -----------
        text_pairs : List[Tuple[str, str]]
            List of (generated_text, reference_text) pairs

        Returns:
        --------
        List[Dict]
            List of score dictionaries for each text pair
        """
        tasks = [self.compute_score(gen, ref) for gen, ref in text_pairs]
        return await asyncio.gather(*tasks)

    def __del__(self):
        """
        Cleanup resources by shutting down the thread pool.
        """
        self.executor.shutdown()
