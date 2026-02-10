"""
Created on Sat Mar  1 14:21:12 2025

@author: kennethezukwoke
"""

import asyncio
import logging
import sys
from functools import lru_cache, wraps
from typing import Any, Dict

import torch
import weaviate
from sentence_transformers import SentenceTransformer

from src.globalvariables import EMBEDDING_NAME, IndexType

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
    def wrapper(embedding_type: str, model_name: str, *args, **kwargs):
        try:
            return func(embedding_type, model_name, *args, **kwargs)
        except Exception as e:
            logging.error(f"🚩 Error loading embedding model: {e}")
            return None

    return wrapper


class EmbeddingModelLoader:
    """
    Class to load, initialize and cache embedding models.
    Uses both lru_cache and custom caching to optimize performance.
    """

    _model_cache: Dict[str, Any] = {}
    _dimension_cache: Dict[str, int] = {}

    @staticmethod
    @lru_cache(maxsize=None)
    @embedding_model_cache
    def load_embedding_model(embedding_type: str, model_name: str) -> Any:
        """
        Load and cache an embedding model based on the embedding type and model name.

        Parameters
        ----------
        embedding_type : str
            Type of embedding ('faiss', 'chroma', or 'weaviate')
        model_name : str
            Name of the model to load

        Returns
        -------
        Any
            The loaded embedding model
        """
        logging.info(
            f"Loading embedding model {model_name} for {embedding_type} on {device.type}"
        )

        cache_key = f"{embedding_type}_{model_name}"
        if cache_key in EmbeddingModelLoader._model_cache:
            logging.info(f"Using cached model for {cache_key}")
            return EmbeddingModelLoader._model_cache[cache_key]

        if embedding_type == IndexType.FAISS or embedding_type == IndexType.CHROMA:
            model = SentenceTransformer(model_name, device=device.type)
            sample_embedding = model.encode(
                "sample text for dimension detection",
                show_progress_bar=False,
                convert_to_tensor=True,
                device=device,
            )
            dimension = sample_embedding.shape[0]
            EmbeddingModelLoader._dimension_cache[cache_key] = dimension
            logging.info(
                f"Model {model_name} produces embeddings with dimension {dimension}"
            )

        elif embedding_type == IndexType.WEAVIATE:
            model = weaviate.Client("http://localhost:8080")
            class_name = "Document"
            if not model.schema.contains(class_name):
                model.schema.create_class(
                    {
                        "class": class_name,
                        "vectorizer": "none",
                    }
                )
        else:
            raise ValueError(
                "🚩 Unsupported embedding type. Choose 'faiss', 'chroma', or 'weaviate'."
            )

        # Store in class-level cache and return
        EmbeddingModelLoader._model_cache[cache_key] = model
        return model

    @staticmethod
    def get_embedding_dimension(embedding_type: str, model_name: str) -> int:
        """
        Get the dimension of embeddings for a specific model.

        Parameters
        ----------
        embedding_type : str
            Type of embedding ('faiss', 'chroma', or 'weaviate')
        model_name : str
            Name of the model

        Returns
        -------
        int
            The dimension of the embeddings
        """
        cache_key = f"{embedding_type}_{model_name}"
        if cache_key in EmbeddingModelLoader._dimension_cache:
            return EmbeddingModelLoader._dimension_cache[cache_key]

        # -- reload to get dimension
        model = EmbeddingModelLoader.load_embedding_model(embedding_type, model_name)

        if embedding_type in [IndexType.FAISS, IndexType.CHROMA]:
            sample_embedding = model.encode(
                "sample text for dimension detection",
                show_progress_bar=False,
                convert_to_tensor=True,
                device=device,
            )
            dimension = sample_embedding.shape[0]
            EmbeddingModelLoader._dimension_cache[cache_key] = dimension
            return dimension
        else:
            return 384

    @staticmethod
    async def load_embedding_model_async(embedding_type: str, model_name: str) -> Any:
        """
        Asynchronously load an embedding model.

        Parameters
        ----------
        embedding_type : str
            Type of embedding ('faiss', 'chroma', or 'weaviate')
        model_name : str
            Name of the model to load

        Returns
        -------
        Any
            The loaded embedding model
        """
        # Use run_in_executor to run the synchronous method in a thread pool
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            EmbeddingModelLoader.load_embedding_model,
            embedding_type,
            model_name,
        )

    @staticmethod
    async def load_multiple_models(model_configs: list) -> Dict[str, Any]:
        """
        Load multiple embedding models in parallel.

        Parameters
        ----------
        model_configs : list
            List of tuples containing (embedding_type, model_name)

        Returns
        -------
        Dict[str, Any]
            Dictionary mapping model keys to loaded models
        """
        tasks = []
        for config in model_configs:
            embedding_type, model_name = config
            tasks.append(
                EmbeddingModelLoader.load_embedding_model_async(
                    embedding_type, model_name
                )
            )

        models = await asyncio.gather(*tasks)
        return {
            f"{config[0]}_{config[1]}": model
            for config, model in zip(model_configs, models)
        }

    @staticmethod
    def get_default_model(embedding_type: str) -> Any:
        """
        Get the default embedding model for a specific embedding type.

        Parameters
        ----------
        embedding_type : str
            Type of embedding ('faiss', 'chroma', or 'weaviate')

        Returns
        -------
        Any
            The default embedding model for the specified type
        """
        embedding_model_name = EMBEDDING_NAME
        if embedding_type in [IndexType.FAISS, IndexType.CHROMA]:
            return EmbeddingModelLoader.load_embedding_model(
                embedding_type, embedding_model_name
            )
        elif embedding_type == IndexType.WEAVIATE:
            return EmbeddingModelLoader.load_embedding_model(embedding_type, "default")
        else:
            raise ValueError("🚩 Unsupported embedding type")

    @staticmethod
    def clear_cache() -> None:
        """Clear the model cache to free memory.

        Returns
        -------
        None
            clear cache.

        """
        EmbeddingModelLoader._model_cache.clear()
        EmbeddingModelLoader._dimension_cache.clear()
        EmbeddingModelLoader.load_embedding_model.cache_clear()
