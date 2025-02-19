import os
import sys
import glob
import torch
import logging
from typing import Optional
from functools import wraps, lru_cache
from transformers import AutoTokenizer
from vllm import LLM
from llama_cpp import Llama
from huggingface_hub import hf_hub_download, list_repo_files
from globalvariables import (
    Models,
    GPU_MODEL_SET,
    CPU_MODEL_SET,
    DEFAULT_GPU_MODEL,
    DEFAULT_CPU_MODEL,
    DEFAULT_CPU_TOKENIZER,
)

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


class LlamaCppServer:
    _instances = {}

    def __init__(
        self,
        model_path: str,
        n_ctx: int = 1024,
        n_threads: Optional[int] = None,
        n_gpu_layers: int = 0,
        verbose: bool = True,
    ):
        """Initialize the Llama.cpp w/ model config

        Parameters
        ----------
        model_path (str): Model name
        n_ctx : int, optional
            context size. The default is 2048.
        n_threads : Optional[int], optional
            number of thread -> CPU. The default is None.
        n_gpu_layers : int, optional
            number of gpu layers. The default is 0.
        verbose : bool, optional
            verbosity. The default is True.

        Raises
        ------
        Exception
            Model loading failed error.

        Returns
        -------
        None.

        """
        if model_path not in LlamaCppServer._instances:
            try:
                if "/" in model_path and not os.path.exists(model_path):
                    model_path = self._download_model(model_path)

                self.model = Llama(
                    model_path=model_path,
                    n_ctx=n_ctx,
                    n_threads=n_threads or os.cpu_count(),
                    n_gpu_layers=n_gpu_layers,
                    verbose=verbose,
                )
                LlamaCppServer._instances[model_path] = self.model
                logging.info(
                    f"Model loaded successfully with {n_gpu_layers} GPU layers!"
                )
            except Exception as e:
                raise Exception(f"Failed to load model: {str(e)}")
        else:
            self.model = LlamaCppServer._instances[model_path]
            logging.info("Using cached model instance")

    def _download_model(self, repo_id: str) -> str:
        """


        Parameters
        ----------
        repo_id (str): Repo ID

        Raises
        ------
        Exception
            Failed to load model from repo.

        Returns
        -------
        str
            DESCRIPTION.

        """
        try:
            model_name = repo_id.split("/")[-1]
            model_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "models",
                model_name,
            )
            os.makedirs(model_dir, exist_ok=True)

            existing_models = glob.glob(os.path.join(model_dir, "*.gguf"))
            if existing_models:
                logging.info(f"Found existing model: {existing_models[0]}")
                return existing_models[0]

            logging.info(f"Downloading model from {repo_id}...")
            files = list_repo_files(repo_id)
            gguf_files = [f for f in files if f.endswith(".gguf")]

            if not gguf_files:
                raise Exception("No GGUF files found in the repository")

            preferred_files = [
                "model.q4_K_M.gguf",
                "q4_K_M.gguf",
                "model.q2_K.gguf",
                "q2_K.gguf",
            ]

            chosen_file = None
            for pref in preferred_files:
                matches = [f for f in gguf_files if pref in f]
                if matches:
                    chosen_file = matches[0]
                    break

            if not chosen_file:
                chosen_file = gguf_files[0]

            logging.info(f"Downloading {chosen_file}...")
            model_file = hf_hub_download(
                repo_id=repo_id, filename=chosen_file, local_dir=model_dir
            )

            logging.info(f"Model downloaded successfully to: {model_file}")
            return model_file

        except Exception as e:
            raise Exception(f"Failed to download model: {str(e)}")


class GPUModel:
    def __init__(self, model_name: str, max_model_len: int):
        """GPU Model and tokenizer loader

        Parameters
        ----------
        model_name (str): Model name
        max_model_len (int): maximum model length

        Returns
        -------
        None.
        """
        self.model = LLM(
            model=model_name,
            tensor_parallel_size=torch.cuda.device_count(),
            max_model_len=max_model_len,
            trust_remote_code=True,
        )
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_name, trust_remote_code=True
        )


class CPUModel:
    def __init__(self, model_name: str, max_model_len: int):
        """CPU Model and tokenizer loader

        Parameters
        ----------
        model_name (str): Model name
        max_model_len (int): maximum model length

        Returns
        -------
        None.
        """
        llama_server = LlamaCppServer(
            model_path=model_name, n_ctx=max_model_len, verbose=False
        )
        self.model = llama_server.model
        self.tokenizer = AutoTokenizer.from_pretrained(
            DEFAULT_CPU_TOKENIZER, trust_remote_code=True
        )
        if not hasattr(self.tokenizer, "model_max_length"):
            self.tokenizer.model_max_length = max_model_len


def validate_model_name(selected_model: str) -> str:
    """Validate the selected model and return appropriate model name based on hardware.


    Parameters
    ----------
    selected_model (str): Selected model

    Returns
    -------
    str
        validated model name.
    """
    has_gpu = torch.cuda.is_available()

    if has_gpu:
        if selected_model in GPU_MODEL_SET:
            return selected_model
        elif selected_model in CPU_MODEL_SET:
            logging.warning(
                f"Selected CPU model {selected_model} but GPU is available. Using default GPU model {DEFAULT_GPU_MODEL}"
            )
            return DEFAULT_GPU_MODEL
        else:
            logging.warning(
                f"Unknown model {selected_model}. Using default GPU model {DEFAULT_GPU_MODEL}"
            )
            return DEFAULT_GPU_MODEL
    else:
        if selected_model in CPU_MODEL_SET:
            return selected_model
        elif selected_model in GPU_MODEL_SET:
            logging.warning(
                f"Selected GPU model {selected_model} but no GPU available. Using default CPU model {DEFAULT_CPU_MODEL}"
            )
            return DEFAULT_CPU_MODEL
        else:
            logging.warning(
                f"Unknown model {selected_model}. Using default CPU model {DEFAULT_CPU_MODEL}"
            )
            return DEFAULT_CPU_MODEL


def model_and_tokenizer_cache(func):
    """
    Decorator to cache the model and tokenizer.
    """

    @wraps(func)
    def wrapper(model_name: str, *args, **kwargs):
        try:
            return func(model_name, *args, **kwargs)
        except Exception as e:
            logging.error(f"🚩 Error loading model and tokenizer: {e}")
            return None, None

    return wrapper


class CachedLLM:
    _model_instances = {}
    _tokenizer_instances = {}

    def __init__(self, model_name: str):
        """CachedLLM


        Parameters
        ----------
        model_name (str): Model name

        Returns
        -------
        None.

        """
        self.model_name = model_name
        self.max_model_len = self._get_max_model_len()
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

    def _get_max_model_len(self) -> int:
        """Get maximum model length based on model type."""
        if self.model_name in GPU_MODEL_SET:
            if self.model_name in [Models.LLAMA3, Models.MISTRAL]:
                return 8192
            elif self.model_name == Models.TINYLLAMA:
                return 2048
            elif self.model_name == Models.GEMMA2:
                return 4096
        elif self.model_name in CPU_MODEL_SET:
            return 1024
        else:
            raise ValueError(f"Error: Unknown model name {self.model_name}")

    def _load_gpu_model(self):
        """
        Load model for GPU inference
        """
        if self.model_name not in self._model_instances:
            logging.info(f"Loading GPU model: {self.model_name}")
            try:
                model = LLM(
                    model=self.model_name,
                    tensor_parallel_size=torch.cuda.device_count(),
                    max_model_len=self.max_model_len,
                    trust_remote_code=True,
                )
                self._model_instances[self.model_name] = model
            except Exception as e:
                logging.error(f"Error loading GPU model: {e}")
                return None
        return self._model_instances[self.model_name]

    def _load_cpu_model(self):
        """
        Load model for CPU inference
        """
        if self.model_name not in self._model_instances:
            logging.info(f"Loading CPU model: {self.model_name}")
            try:
                llama_server = LlamaCppServer(
                    model_path=self.model_name,
                    n_ctx=self.max_model_len,
                    verbose=False,
                )
                self._model_instances[self.model_name] = llama_server.model
            except Exception as e:
                logging.error(f"Error loading CPU model: {e}")
                return None
        return self._model_instances[self.model_name]

    def _load_tokenizer(self):
        """Load and cache tokenizer."""
        if self.model_name not in self._tokenizer_instances:
            logging.info(f"Loading tokenizer for: {self.model_name}")
            try:
                if self.device == "cuda":
                    tokenizer = AutoTokenizer.from_pretrained(
                        self.model_name, trust_remote_code=True
                    )
                else:
                    # For CPU/GGUF models, use base tokenizer
                    tokenizer = AutoTokenizer.from_pretrained(
                        DEFAULT_CPU_TOKENIZER,
                        trust_remote_code=True,
                    )

                if not hasattr(tokenizer, "model_max_length"):
                    tokenizer.model_max_length = self.max_model_len

                self._tokenizer_instances[self.model_name] = tokenizer
            except Exception as e:
                logging.error(f"Error loading tokenizer: {e}")
                return None
        return self._tokenizer_instances[self.model_name]

    def get_model_and_tokenizer(self):
        """Cached model and tokenizer instances."""
        try:
            # Load model based on device
            model = (
                self._load_gpu_model()
                if self.device == "cuda"
                else self._load_cpu_model()
            )
            tokenizer = self._load_tokenizer()

            if model is None or tokenizer is None:
                raise ValueError("Failed to load model or tokenizer")

            return model, tokenizer

        except Exception as e:
            logging.error(f"Error in get_model_and_tokenizer: {e}")
            return None, None

    @classmethod
    def clear_cache(cls):
        """Clear all cached models and tokenizers."""
        cls._model_instances.clear()
        cls._tokenizer_instances.clear()
        logging.info("Cleared model and tokenizer cache")

    @classmethod
    def get_cache_info(cls):
        """Information about cached models and tokenizers."""
        return {
            "cached_models": list(cls._model_instances.keys()),
            "cached_tokenizers": list(cls._tokenizer_instances.keys()),
            "total_cached_items": len(cls._model_instances)
            + len(cls._tokenizer_instances),
        }


@lru_cache(maxsize=512)
@model_and_tokenizer_cache
def load_model_and_tokenizer(model_name: str, abs_path: str):
    """
    Load and cache the model (GPu or CPu) and tokenizer.

    Parameters
        model_name (str): The name or path of the pre-trained model to load.
        abs_path (str): The absolute path for model storage.

    Returns:
        model: The loaded LLM model.
        tokenizer: The loaded tokenizer associated with the model.
    """
    try:
        validated_model_name = validate_model_name(model_name)
        cached_llm = CachedLLM(validated_model_name)
        model, tokenizer = cached_llm.get_model_and_tokenizer()

        if model is None or tokenizer is None:
            raise ValueError("Failed to load model or tokenizer")

        return model, tokenizer
    except Exception as e:
        logging.error(
            f"Failed to load model or tokenizer for {model_name}: {e}"
        )
        return None, None
