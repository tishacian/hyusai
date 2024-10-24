import os
import torch
import logging
from functools import wraps, lru_cache
from langchain_community.embeddings import HuggingFaceInstructEmbeddings
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    AutoConfig,
)
from vllm import LLM
from globalvariables import Models
from concurrent.futures import ThreadPoolExecutor

def model_and_tokenizer_cache(func):
    """
    Decorator to cache the model and tokenizer loading.
    """

    @wraps(func)
    def wrapper(model_name: str, *args, **kwargs):
        try:
            return func(model_name, *args, **kwargs)
        except Exception as e:
            logging.error(f"🚩 Error loading model and tokenizer: {e}")
            return None, None

    return wrapper


@lru_cache(maxsize=512)
@model_and_tokenizer_cache
def load_model_and_tokenizer(model_name: str, abs_path: str):
    """
    Helper function to load and cache the model and tokenizer.

    Parameters
    - model_name (str): The name or path of the pre-trained model to load.
    - abs_path (str): The absolute path for model storage.

    Returns:
    - model: The loaded LLM model.
    - tokenizer: The loaded tokenizer associated with the model.
    """
    try:
        if torch.cuda.is_available():
            cached_llm = CachedLLM(model_name)
            model, tokenizer = cached_llm.get_model_and_tokenizer()
        else:
            tokenizer = TokenizerLoader(model_name).from_pretrained()
            model = CustomLLMLoader(model_name, abs_path).from_pretrained()
        return model, tokenizer
    except Exception as e:
        logging.error(
            f"Failed to load model or tokenizer for {model_name}: {e}"
        )
        return None, None


class TokenizerLoader:
    def __init__(self, model_name):
        """
        Tokenizer Loader

        Parameters
        ---------
        - model_name (str): Model card (name).
        - cache_dir (str), optional : cache directory. The default is None.

        Returns
        - GPT2TokenizerFast(..)

        """
        self.model_name = model_name

    def from_pretrained(self):
        """
        Load tokenizer
        """
        if self.model_name:
            try:
                self.tokenizer = AutoTokenizer.from_pretrained(
                    self.model_name,
                )
            except (OSError, ValueError, RuntimeError, KeyError) as e:
                logging.error(f"🚩 Unexpected error loading tokenizer: {e}")
                self.tokenizer = None
        return self.tokenizer


class InstructionEmbeddingLoader:
    def __init__(
        self,
        embedding_model_name="sentence-transformers/all-mpnet-base-v2",
    ):
        """
        Load the instruction Embedding model required by Chroma

        Parameters
        ---------
        - embedding_model_name (str): Name of the embedding model.

        Returns
        None.

        """
        self.embedding_model_name = embedding_model_name
        self.device = torch.device(
            "cuda:0" if torch.cuda.is_available() else "cpu"
        )
        self.model_kwargs = {"device": self.device.type}
        self.encode_kwargs = {"normalize_embeddings": True}

    def from_pretrained(self):
        """
        Load Instruction Embedding
        """
        if self.embedding_model_name:
            try:
                self.embedding_model = HuggingFaceInstructEmbeddings(
                    model_name=self.embedding_model_name,
                    model_kwargs=self.model_kwargs,
                    encode_kwargs=self.encode_kwargs,
                )
            except (OSError, ValueError, RuntimeError, KeyError) as e:
                logging.error(
                    f"🚩 Error loading instruction embedding model: {e}"
                )
                self.embedding_model = None
        return self.embedding_model


class CachedLLM:
    def __init__(self, model_name: str):
        self.model_name = model_name
        self.max_model_len = self.max_model_len()

    def max_model_len(self):
        if self.model_name in [Models.LLAMA3, Models.MISTRAL]:
            return 8192
        elif self.model_name == Models.TINYLLAMA:
            return 2048
        elif self.model_name == Models.GEMMA2:
            return 4096
        else:
            raise ValueError(f"Error: Unknown model name {self.model_name}")

    @lru_cache(maxsize=None)
    def load_model(self):
        tensor_parallel_size = torch.cuda.device_count()
        return LLM(
            model=self.model_name,
            tensor_parallel_size=tensor_parallel_size,
            max_model_len=self.max_model_len,
            trust_remote_code=True,
        )

    @lru_cache(maxsize=None)
    def load_tokenizer(self):
        return AutoTokenizer.from_pretrained(
            self.model_name, trust_remote_code=True
        )

    def get_model_and_tokenizer(self):
        return self.load_model(), self.load_tokenizer()


class CustomLLMLoader:
    def __init__(
        self, model_name, abs_path, precision="bfloat16", cache_dir=None
    ):
        """LLM Loader
        Parameters
        ----------
        model_name (str): Model card (name).
        abs_path (str): absolute working path.
        precision (str), optional. Model precision type. The default is "bfloat16".
        cache_dir (str), optional.
            cache directory. The default is None.

        Raises
        ------
        NotImplementedError
            int8 precision error.
        ValueError
            Unsupported precision.

        Returns
        -------
            GPT2LMHeadModel(...)

        """
        self.model_name = model_name
        self.abs_path = abs_path
        self.precision = precision
        self.cache_dir = cache_dir
        self.device = torch.device(
            "cuda:0" if torch.cuda.is_available() else "cpu"
        )
        self.model_path = os.path.join(
            self.abs_path, self.model_name.split("/")[-1]
        )

        # Set the torch_dtype based on the precision
        if torch.cuda.is_available():
            self.torch_dtype = {
                "float16": torch.float16,
                "float32": torch.float32,
                "bfloat16": torch.bfloat16,
            }.get(
                self.precision, torch.float32
            )  # Default to float32 if not specified
        else:
            self.torch_dtype = (
                torch.float32
            )  # Use float32 for better CPU performance

        if self.precision == "int8":
            raise NotImplementedError(
                "🚩 int8 precision is not supported for direct dtype conversion."
            )
        elif self.torch_dtype is None:
            raise ValueError(f"🚩 Unsupported precision: {self.precision}")

        # Ensure the model directory exists
        os.makedirs(self.model_path, exist_ok=True)

        self.model = self._load_model()

    def _load_model(self):
        """
        Load or download the model.
        """
        if not os.path.exists(self.model_path) or not os.listdir(
            self.model_path
        ):
            try:
                # Load the model with optimized settings
                model = AutoModelForCausalLM.from_pretrained(
                    self.model_name,
                    torch_dtype=self.torch_dtype,
                    low_cpu_mem_usage=True,  # Minimize CPU memory usage during loading
                )
                model = model.module if hasattr(model, "module") else model
                model.save_pretrained(self.model_path)
            except (OSError, ValueError, RuntimeError, KeyError) as e:
                logging.error(f"🚩 Error loading model: {e}")
                model = None
        else:
            try:
                model = AutoModelForCausalLM.from_pretrained(
                    pretrained_model_name_or_path=self.model_name,
                    torch_dtype=self.torch_dtype,
                    cache_dir=self.cache_dir if self.cache_dir else None,
                    low_cpu_mem_usage=True,  # Minimize CPU memory usage during loading
                )
            except (OSError, ValueError, RuntimeError, KeyError) as e:
                logging.error(f"🚩 Error loading model: {e}")
                model = None
        return model

    def from_pretrained(self):
        """
        Prepare the model for inference.
        """
        if torch.cuda.is_available():
            config = AutoConfig.from_pretrained(self.model_name)

            if hasattr(config, "attn_implementation"):
                config.attn_implementation = (
                    "flash_attention_2"  # Enable flash attention if supported
                )

            self.model.config = config

            # Use a distributed approach to load the model onto the GPU
            self._distributed_gpu_transfer()

        else:
            # Disable GPU-specific settings for CPU
            if hasattr(self.model.config, "attn_implementation"):
                self.model.config.attn_implementation = None

            self._distributed_cpu_transfer()

        return self.model

    def available_device_count(self, device):
        """
        Get the number of available devices (GPUs or CPU cores).
        """
        if device.type == "cuda" and torch.cuda.is_available():
            return torch.cuda.device_count()
        else:
            return torch.get_num_threads()

    def _distributed_gpu_transfer(self):
        """
        Move the model to GPU in parallel using multiple CUDA streams to maximize GPU usage.
        """
        try:
            # -- Number of streams (you can adjust based on your GPU's capabilities)
            num_streams = self.available_device_count(self.device)
            streams = [torch.cuda.Stream(device=i) for i in range(num_streams)]

            # -- Divide parameters into chunks
            params = list(self.model.parameters())
            chunk_size = len(params) // 10
            chunks = [
                params[i * chunk_size : (i + 1) * chunk_size]
                for i in range(num_streams)
            ]
            # -- Use CUDA streams to transfer chunks in parallel
            for stream, chunk in zip(streams, chunks):
                with torch.cuda.stream(stream):
                    for param in chunk:
                        param.data = param.data.to(
                            self.device, non_blocking=True
                        )

            # -- Synchronize all streams to ensure completion
            for stream in streams:
                stream.synchronize()
            # --
            with torch.cuda.amp.autocast(enabled=True):
                self.model.to(self.device)

        except Exception as e:
            logging.error(f"🚩 Error during GPU transfer: {e}")

    def _distributed_cpu_transfer(self):
        """
        Move the model to CPU in parallel
        """
        try:
            num_cores = self.available_device_count(self.device)
            params = list(self.model.parameters())
            chunk_size = max(1, len(params) // num_cores)
            param_chunks = [
                params[i * chunk_size : (i + 1) * chunk_size]
                for i in range(num_cores)
            ]

            # -- chunk and load buffers into CPU
            buffers = list(self.model.buffers())
            buffer_chunk_size = max(1, len(buffers) // num_cores)
            buffer_chunks = [
                buffers[i * buffer_chunk_size : (i + 1) * buffer_chunk_size]
                for i in range(num_cores)
            ]

            def transfer_to_cpu(chunk):
                """
                Transfer tensor data to cpu
                """
                for tensor in chunk:
                    tensor.data = tensor.data.to("cpu", non_blocking=True)

            def transfer_tensors():
                """
                model transfer
                """
                self.model.to("cpu")

            # --
            with ThreadPoolExecutor(max_workers=num_cores) as executor:
                executor.map(transfer_to_cpu, param_chunks)
                executor.map(transfer_to_cpu, buffer_chunks)
                executor.submit(transfer_tensors).result()

        except Exception as e:
            logging.error(f"🚩 Error during CPU transfer: {e}")


# %% initialize model and cache..time saving upon calling
if torch.cuda.is_available():
    abs_path = "/workspace/FixLoCL/customLLM"
    model_name = Models.LLAMA3
else:
    abs_path = "/Users/kennethezukwoke/Documents/Datategy/Kenneth/RAGGER/src/LLMCustomChain"
    model_name = Models.LAMINIGPT

model, tokenizer = load_model_and_tokenizer(model_name, abs_path)
