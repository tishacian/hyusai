"""
Created on Sat Mar  1 14:20:06 2025

@author: kennethezukwoke
"""

import asyncio
import logging
import sys
import warnings
from functools import lru_cache, wraps
from typing import Any

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
warnings.simplefilter(action="ignore", category=FutureWarning)


device = torch.device(
    "cuda"
    if torch.cuda.is_available()
    else "cpu"
    if torch.backends.mps.is_available()
    else "cpu"
)


def reranker_model_cache(func):
    """
    Decorator to cache the reranker model and handle exceptions.
    """

    @wraps(func)
    def wrapper(model_name: str, *args, **kwargs):
        try:
            return func(model_name, *args, **kwargs)
        except Exception as e:
            logging.error(f"🚩 Error loading reranker model: {e}")
            return None, None

    return wrapper


class RerankerModelLoader:
    """
    Class to load, initialize and cache reranker models.
    """

    _model_cache: dict[str, Any] = {}
    _tokenizer_cache: dict[str, Any] = {}

    @staticmethod
    @lru_cache(maxsize=None)
    @reranker_model_cache
    def load_reranker_model(
        model_name: str, device: str | None = None
    ) -> tuple[Any, Any]:
        """
        Load and cache a reranker model and tokenizer based on the model name.

        Parameters
        ----------
        model_name : str
            Name of the model to load
        device : Optional[str]
            Device to load the model on ('cuda' or 'cpu')

        Returns
        -------
        Tuple[Any, Any]
            The loaded model and tokenizer
        """
        if model_name in RerankerModelLoader._model_cache:
            logging.info(f"Using cached model for {model_name}")
            model = RerankerModelLoader._model_cache[model_name]
            tokenizer = RerankerModelLoader._tokenizer_cache[model_name]

            if device != "cpu" and next(model.parameters()).device.type != device:
                try:
                    model = model.to(device)
                except RuntimeError as e:
                    logging.warning(f"Failed to move model to {device}, using CPU: {e}")
                    model = model.to("cpu")
                    device = "cpu"

            return model, tokenizer

        # -- Initialize the model and tokenizer
        model = AutoModelForSequenceClassification.from_pretrained(model_name)
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        RerankerModelLoader._model_cache[model_name] = model
        RerankerModelLoader._tokenizer_cache[model_name] = tokenizer
        # -- model :: tokenizer
        return model, tokenizer

    @staticmethod
    async def load_model_async(
        model_name: str, device: str | None = None
    ) -> tuple[Any, Any]:
        """
        Asynchronously load a reranker model.

        Parameters
        ----------
        model_name : str
            Name of the model to load
        device : Optional[str]
            Device to load the model on ('cuda' or 'cpu')

        Returns
        -------
        Tuple[Any, Any]
            The loaded model and tokenizer
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            RerankerModelLoader.load_reranker_model,
            model_name,
            device,
        )

    @staticmethod
    def clear_cache() -> None:
        """Clear the model and tokenizer caches to free memory."""
        RerankerModelLoader._model_cache.clear()
        RerankerModelLoader._tokenizer_cache.clear()
        RerankerModelLoader.load_reranker_model.cache_clear()

    @staticmethod
    def get_model_device(model_name: str) -> str:
        """
        Get the device that a cached model is on.

        Parameters
        ----------
        model_name : str
            Name of the model

        Returns
        -------
        str
            The device the model is on ('cuda' or 'cpu')
        """
        if model_name in RerankerModelLoader._model_cache:
            model = RerankerModelLoader._model_cache[model_name]
            return next(model.parameters()).device.type
        return "none"

    @staticmethod
    def move_model_to_device(model_name: str, device: str) -> bool:
        """
        Move a cached model to the specified device.

        Parameters
        ----------
        model_name : str
            Name of the model
        device : str
            Target device ('cuda' or 'cpu')

        Returns
        -------
        bool
            True if successful, False otherwise
        """
        if model_name not in RerankerModelLoader._model_cache:
            logging.error(f"Model {model_name} not found in cache")
            return False

        model = RerankerModelLoader._model_cache[model_name]
        current_device = next(model.parameters()).device.type

        if current_device == device:
            return True

        try:
            model = model.to(device)
            RerankerModelLoader._model_cache[model_name] = model
            logging.info(f"Moved model {model_name} from {current_device} to {device}")
            return True
        except Exception as e:
            logging.error(f"Failed to move model to {device}: {e}")
            return False
