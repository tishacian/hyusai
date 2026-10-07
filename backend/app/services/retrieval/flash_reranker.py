"""Fast reranker using cross-encoder models"""
import torch
import numpy as np
from typing import List, Dict, Optional, Tuple, Union, Any
from transformers import AutoModelForSequenceClassification, AutoTokenizer
from app.core.logging import get_logger
from app.services.retrieval.reranker_config import RerankerConfig, RerankerMode

__all__ = ["FlashReranker", "RerankerConfig", "RerankerMode"]

logger = get_logger(__name__)


class FlashReranker:
    """Fast and efficient reranker with memory management"""
    
    _model_cache: Dict[str, Any] = {}
    _tokenizer_cache: Dict[str, Any] = {}
    
    def __init__(self, config: Optional[RerankerConfig] = None):
        """Initialize flash reranker"""
        self.config = config or RerankerConfig()
        
        # Determine device
        if self.config.device is None:
            if torch.cuda.is_available():
                self.device = "cuda"
            elif torch.backends.mps.is_available():
                self.device = "mps"
            else:
                self.device = "cpu"
        else:
            self.device = self.config.device
        
        # Load model and tokenizer
        self.model, self.tokenizer = self._load_model()
    
    def _load_model(self) -> Tuple[Any, Any]:
        """Load reranker model with caching"""
        if self.config.model_name in FlashReranker._model_cache:
            logger.info(f"Using cached reranker model: {self.config.model_name}")
            model = FlashReranker._model_cache[self.config.model_name]
            tokenizer = FlashReranker._tokenizer_cache[self.config.model_name]
            
            # Move to device if needed
            if next(model.parameters()).device.type != self.device:
                try:
                    model = model.to(self.device)
                    FlashReranker._model_cache[self.config.model_name] = model
                except RuntimeError as e:
                    logger.warning(f"Failed to move model to {self.device}, using CPU: {e}")
                    self.device = "cpu"
                    model = model.to("cpu")
                    FlashReranker._model_cache[self.config.model_name] = model
            
            return model, tokenizer
        
        # Load new model
        try:
            logger.info(f"Loading reranker model: {self.config.model_name}")
            model = AutoModelForSequenceClassification.from_pretrained(self.config.model_name)
            tokenizer = AutoTokenizer.from_pretrained(self.config.model_name)
            
            model = model.to(self.device)
            model.eval()
            
            # Cache model
            FlashReranker._model_cache[self.config.model_name] = model
            FlashReranker._tokenizer_cache[self.config.model_name] = tokenizer
            
            logger.info(f"Successfully loaded reranker model: {self.config.model_name}")
            return model, tokenizer
            
        except Exception as e:
            logger.error(f"Error loading reranker model: {e}")
            raise
    
    def _batch_tokenize(self, query: str, passages: List[str]) -> Dict[str, torch.Tensor]:
        """Tokenize query-passage pairs with memory-efficient batching"""
        try:
            pairs = [(query, passage) for passage in passages]
            inputs = self.tokenizer(
                pairs,
                padding=True,
                truncation=True,
                max_length=self.config.max_length,
                return_tensors="pt",
            )
            
            if self.device != "cpu":
                try:
                    inputs = {k: v.to(self.device) for k, v in inputs.items()}
                except RuntimeError:
                    logger.warning("CUDA memory insufficient, processing on CPU")
                    self.device = "cpu"
                    torch.cuda.empty_cache()
            
            return inputs
            
        except Exception as e:
            logger.error(f"Error in batch tokenization: {e}")
            # Return empty inputs as fallback
            return self.tokenizer(
                [(query, "")],
                padding=True,
                truncation=True,
                max_length=self.config.max_length,
                return_tensors="pt",
            )
    
    def _compute_relevance_scores(self, inputs: Dict[str, torch.Tensor]) -> torch.Tensor:
        """Compute relevance scores"""
        try:
            with torch.no_grad():
                if self.device == "cuda":
                    try:
                        with torch.inference_mode():
                            outputs = self.model(**inputs)
                    except RuntimeError:
                        logger.warning("CUDA error in scoring, falling back to CPU")
                        self.device = "cpu"
                        torch.cuda.empty_cache()
                        inputs = {k: v.cpu() for k, v in inputs.items()}
                        outputs = self.model(**inputs)
                else:
                    with torch.inference_mode():
                        outputs = self.model(**inputs)
                
                scores = torch.sigmoid(outputs.logits)
                if scores.dim() == 0:
                    scores = scores.unsqueeze(0)
                return scores.squeeze()
                
        except Exception as e:
            logger.error(f"Error computing relevance scores: {e}")
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
                
                all_scores.extend(scores.tolist() if isinstance(scores, np.ndarray) else [float(scores)])
                
                if self.device == "cuda":
                    torch.cuda.empty_cache()
                    
            except Exception as e:
                logger.error(f"Error processing batch: {e}")
                all_scores.extend([0.0] * len(batch))
        
        return all_scores
    
    def score(self, query: str, passages: List[str]) -> List[float]:
        """Relevance scores aligned to the input passage order (no sorting).

        Sigmoid scores in [0, 1]; callers that need to keep passages aligned
        with external metadata should use this instead of ``rerank``.
        """
        if not passages:
            return []
        batch_size = (
            self.config.batch_size
            if self.device == "cuda"
            else max(1, self.config.batch_size // 4)
        )
        return self._batch_process(query, passages, batch_size)

    def rerank(
        self, query: str, passages: List[str], return_scores: bool = False
    ) -> Union[List[str], Tuple[List[str], List[float]]]:
        """Memory-efficient reranking"""
        try:
            batch_size = (
                self.config.batch_size
                if self.device == "cuda"
                else max(1, self.config.batch_size // 4)
            )
            
            # Compute scores
            scores = self._batch_process(query, passages, batch_size)
            
            # Sort by score
            scored_passages = list(zip(passages, scores))
            scored_passages.sort(key=lambda x: x[1], reverse=True)
            
            # Filter by threshold
            filtered = [
                (p, s) for p, s in scored_passages if s >= self.config.threshold
            ]
            if not filtered:
                filtered = scored_passages
            
            reranked_passages, final_scores = zip(*filtered) if filtered else ([], [])
            
            return (
                (list(reranked_passages), list(final_scores))
                if return_scores
                else list(reranked_passages)
            )
            
        except Exception as e:
            logger.error(f"Error during reranking: {e}")
            if return_scores:
                return passages, [0.0] * len(passages)
            return passages
    
    def __call__(
        self, query: str, passages: List[str], return_scores: bool = False
    ) -> Union[List[str], Tuple[List[str], List[float]]]:
        """Convenience method to rerank"""
        return self.rerank(query, passages, return_scores)

