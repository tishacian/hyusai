"""
Created on Sat Mar  1 14:21:12 2025

@author: kennethezukwoke
"""

import asyncio
import logging
import sys
from functools import lru_cache, wraps
from typing import Any

import torch
from sentence_transformers import SentenceTransformer

from src.globalvariables import EMBEDDING_NAME

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


device = torch.device(
    "cuda"
    if torch.cuda.is_available()
    else "cpu"
    if torch.backends.mps.is_available()
    else "cpu"
)


def embedding_model_cache(func):
    """
    Decorator to cache the embedding model and handle exceptions.
    """

    @wraps(func)
    def wrapper(model_name: str, *args, **kwargs):
        try:
            return func(model_name, *args, **kwargs)
        except Exception as e:
            logging.error(f"🚩 Error loading embedding model: {e}")
            return None

    return wrapper


class EmbeddingModelLoader:
    """
    Class to load, initialize and cache embedding models.
    Uses both lru_cache and custom caching to optimize performance.
    """

    _model_cache: dict[str, Any] = {}
    _dimension_cache: dict[str, int] = {}

    @staticmethod
    @lru_cache(maxsize=None)
    @embedding_model_cache
    def load_embedding_model(model_name: str) -> Any:
        """
        Load and cache an embedding model by name.

        Parameters
        ----------
        model_name : str
            Name of the model to load

        Returns
        -------
        Any
            The loaded embedding model
        """
        logging.info(f"Loading embedding model {model_name} on {device.type}")

        if model_name in EmbeddingModelLoader._model_cache:
            logging.info(f"Using cached model for {model_name}")
            return EmbeddingModelLoader._model_cache[model_name]

        model = SentenceTransformer(model_name, device=device.type)
        sample_embedding = model.encode(
            "sample text for dimension detection",
            show_progress_bar=False,
            convert_to_tensor=True,
            device=device,
        )
        dimension = sample_embedding.shape[0]
        EmbeddingModelLoader._dimension_cache[model_name] = dimension
        logging.info(
            f"Model {model_name} produces embeddings with dimension {dimension}"
        )

        EmbeddingModelLoader._model_cache[model_name] = model
        return model

    @staticmethod
    def get_embedding_dimension(model_name: str) -> int:
        """
        Get the dimension of embeddings for a specific model.

        Parameters
        ----------
        model_name : str
            Name of the model

        Returns
        -------
        int
            The dimension of the embeddings
        """
        if model_name in EmbeddingModelLoader._dimension_cache:
            return EmbeddingModelLoader._dimension_cache[model_name]

        model = EmbeddingModelLoader.load_embedding_model(model_name)

        sample_embedding = model.encode(
            "sample text for dimension detection",
            show_progress_bar=False,
            convert_to_tensor=True,
            device=device,
        )
        dimension = sample_embedding.shape[0]
        EmbeddingModelLoader._dimension_cache[model_name] = dimension
        return dimension

    @staticmethod
    async def load_embedding_model_async(model_name: str) -> Any:
        """
        Asynchronously load an embedding model.

        Parameters
        ----------
        model_name : str
            Name of the model to load

        Returns
        -------
        Any
            The loaded embedding model
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            EmbeddingModelLoader.load_embedding_model,
            model_name,
        )

    @staticmethod
    async def load_multiple_models(model_names: list[str]) -> dict[str, Any]:
        """
        Load multiple embedding models in parallel.

        Parameters
        ----------
        model_names : list[str]
            List of model names to load

        Returns
        -------
        Dict[str, Any]
            Dictionary mapping model names to loaded models
        """
        tasks = [
            EmbeddingModelLoader.load_embedding_model_async(name)
            for name in model_names
        ]
        models = await asyncio.gather(*tasks)
        return dict(zip(model_names, models))

    @staticmethod
    def get_default_model() -> Any:
        """
        Get the default embedding model.

        Returns
        -------
        Any
            The default embedding model
        """
        return EmbeddingModelLoader.load_embedding_model(EMBEDDING_NAME)

    @staticmethod
    def clear_cache() -> None:
        """Clear the model cache to free memory."""
        EmbeddingModelLoader._model_cache.clear()
        EmbeddingModelLoader._dimension_cache.clear()
        EmbeddingModelLoader.load_embedding_model.cache_clear()
