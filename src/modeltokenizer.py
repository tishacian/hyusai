import glob
import logging
import os
import sys
from functools import lru_cache, wraps
from typing import Optional

import torch
from transformers import AutoTokenizer

from configuration import get_standalone_interface_config
from globalvariables import (
    CPU_MODEL_SET,
    DEFAULT_CPU_MODEL,
    DEFAULT_CPU_TOKENIZER,
    GPU_MODEL_SET,
    LARGE_MODELS,
    MAX_MODEL_LEN,
)
from utils import get_max_model_len, gpu_arc_type

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
os.environ["VLLM_ALLOW_LONG_MAX_MODEL_LEN"] = "1"
gpu_available = True if torch.cuda.is_available() else False
if not gpu_available:
    from huggingface_hub import hf_hub_download, list_repo_files
    from llama_cpp import Llama
else:
    import psutil
    from vllm import LLM


class LlamaCppServer:
    _instances = {}

    def __init__(
        self,
        model_path: str,
        n_ctx: int = 2048,
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
                f"Selected CPU model {selected_model} but GPU is available. Using default GPU model {get_standalone_interface_config().default_gpu_model}"
            )
            return get_standalone_interface_config().default_gpu_model
        else:
            logging.warning(
                f"Unknown model {selected_model}. Using default GPU model {get_standalone_interface_config().default_gpu_model}"
            )
            return get_standalone_interface_config().default_gpu_model
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
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model_name = model_name
        self.is_large_model = self.model_name in LARGE_MODELS
        self.max_model_len = get_max_model_len(self.model_name, MAX_MODEL_LEN)
        self.gpu_type = gpu_arc_type(self.device)

    def _load_gpu_model(self):
        """!IMPORTANT
        Load model for GPU inference with optimizations for A100, H100 and L40S GPUs

        On RoPE scaling
        ---------------
        RoPE (Rotary Position Embedding) is a SOTA method for extending context length.
        While different methods exits today to implement this technique, not all are efficient and scale for transformers.

        Formular: RoPE(x_i, x_j) = (x_i * cos θ_i - x_j * sin θ_j, x_i * sin θ_i + x_j * cos θ_i)
                where θ_i  = 10000 ^(-2 * (i - 1) / d)

        Types: "linear", "yarn", "dynamic", "ntk", "hybrid", "llama3". "dynamic" and "llama3" are best suited for most applications.

        NOTE:
            For "dynamic": Maximum concurrency for 131072 tokens per request: 2.21x on A100;
            For "llama3": Maximum concurrency for 131072 tokens per request: 2.23x (faster) on A100; >=4x faster for both on H100
        """
        if self.model_name not in self._model_instances:
            logging.info(f"Loading GPU model: {self.model_name}")
            try:
                mem = psutil.virtual_memory()
                available_ram_gb = (
                    mem.available * 0.10 / (1024**3)
                )  # using 10% RAM resource for swap
                swap_space = max(1, int(available_ram_gb))

                if self.is_large_model:
                    if self.gpu_type == "H100":
                        gpu_utilization = 0.98
                        tensor_parallel = min(torch.cuda.device_count(), 8)
                    elif self.gpu_type == "A100":
                        gpu_utilization = 0.95
                        tensor_parallel = min(torch.cuda.device_count(), 8)
                    elif self.gpu_type == "L40S":
                        gpu_utilization = 0.95
                        tensor_parallel = min(torch.cuda.device_count(), 8)
                    else:
                        gpu_utilization = 0.75
                        tensor_parallel = torch.cuda.device_count()

                else:
                    if self.gpu_type == "H100":
                        gpu_utilization = 0.95
                        tensor_parallel = min(torch.cuda.device_count(), 8)
                    elif self.gpu_type == "A100":
                        gpu_utilization = 0.90
                        tensor_parallel = min(torch.cuda.device_count(), 8)
                    elif self.gpu_type == "L40S":
                        gpu_utilization = 0.80
                        tensor_parallel = min(torch.cuda.device_count(), 4)
                    else:
                        gpu_utilization = 0.80
                        tensor_parallel = torch.cuda.device_count()

                kwargs = {
                    "model": self.model_name,
                    "tensor_parallel_size": tensor_parallel,
                    "max_model_len": self.max_model_len,
                    "trust_remote_code": True,
                    "gpu_memory_utilization": gpu_utilization,  # <-- Too high values may cause "Cache issues", OOM Error. Lowers values are preferred.
                    "enforce_eager": False,
                    "swap_space": swap_space,
                }

                # --> Optimal KV caching
                if self.is_large_model:
                    kwargs.update(
                        {
                            "rope_scaling": {
                                "rope_type": "llama3",
                                "type": "resonance_yarn",
                                "factor": 8.0,
                                "low_freq_factor": 1.0,
                                "high_freq_factor": 4.0,
                                "original_max_position_embeddings": 8192,
                            },
                            "dtype": "float16",
                        }
                    )
                model = LLM(**kwargs)
                self._model_instances[self.model_name] = model

                if self.is_large_model:
                    logging.info(
                        f"Performing warmup for large model: {self.model_name}"
                    )
                    model.generate("Hello, world")

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


@lru_cache(maxsize=None)
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
