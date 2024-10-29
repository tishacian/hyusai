import os
import sys
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
from globalvariables import (
    Models,
    GPU_MODEL_SET,
    CPU_MODEL_SET,
    DEFAULT_GPU_MODEL,
    DEFAULT_CPU_MODEL,
)
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def validate_model_name(selected_model: str) -> str:
    """
    Validate the selected model and return appropriate model name based on hardware.
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
    Load and cache the model (GPu or CPu) and tokenizer.

    Parameters
        model_name (str): The name or path of the pre-trained model to load.
        abs_path (str): The absolute path for model storage.

    Returns:
        model: The loaded LLM model.
        tokenizer: The loaded tokenizer associated with the model.
    """
    validated_model_name = validate_model_name(model_name)
    try:
        if torch.cuda.is_available():
            cached_llm = CachedLLM(validated_model_name)
            model, tokenizer = cached_llm.get_model_and_tokenizer()
        else:
            tokenizer = TokenizerLoader(validated_model_name).from_pretrained()
            model = CustomLLMLoader(
                validated_model_name, abs_path
            ).from_pretrained()
        return model, tokenizer
    except Exception as e:
        logging.error(
            f"Failed to load model or tokenizer for {validated_model_name}: {e}"
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
                    self.model_name, trust_remote_code=True
                )
                if not hasattr(self.tokenizer, "model_max_length"):
                    self.tokenizer.model_max_length = 512
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
            "cuda:0"
            if torch.cuda.is_available()
            else "mps" if torch.backends.mps.is_available() else "cpu"
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
        if self.model_name in GPU_MODEL_SET:
            if self.model_name in [Models.LLAMA3, Models.MISTRAL]:
                return 8192
            elif self.model_name == Models.TINYLLAMA:
                return 2048
            elif self.model_name == Models.GEMMA2:
                return 4096
        elif self.model_name in CPU_MODEL_SET:
            return 512
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
            "cuda:0"
            if torch.cuda.is_available()
            else "mps" if torch.backends.mps.is_available() else "cpu"
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
                    device_map="auto",
                    # low_cpu_mem_usage=True,  # Minimize CPU memory usage during loading
                    trust_remote_code=True,
                )
                model = model.module if hasattr(model, "module") else model
                model.save_pretrained(self.model_path)
            except (OSError, ValueError, RuntimeError, KeyError) as e:
                logging.error(f"🚩 Error loading model: {e}")
                model = None
        else:
            try:
                model = AutoModelForCausalLM.from_pretrained(
                    self.model_path,
                    torch_dtype=self.torch_dtype,
                    cache_dir=self.cache_dir if self.cache_dir else None,
                    device_map="auto",
                    # low_cpu_mem_usage=True,  # Minimize CPU memory usage during loading
                    trust_remote_code=True,
                )
            except (OSError, ValueError, RuntimeError, KeyError) as e:
                logging.error(f"🚩 Error loading model: {e}")
                model = None

        return model

    def from_pretrained(self):
        """
        Prepare the model for inference.
        """
        try:
            self.model = self._load_model()
            if self.model is None:
                return None

            # Handle device placement based on model state
            if hasattr(self.model, "is_meta") and self.model.is_meta:
                self.model = self.model.to_empty(device=self.device.type)

            # Configure model based on device
            if self.device.type == "cuda":
                config = AutoConfig.from_pretrained(self.model_name)
                if hasattr(config, "attn_implementation"):
                    config.attn_implementation = "flash_attention_2"
                self.model.config = config
                self._distributed_gpu_transfer()
            elif self.device.type == "mps":
                if hasattr(self.model.config, "attn_implementation"):
                    self.model.config.attn_implementation = None
                self.model = self.model.to(self.device.type)
            else:  # CPU
                if hasattr(self.model.config, "attn_implementation"):
                    self.model.config.attn_implementation = None
                self._distributed_cpu_transfer()

            return self.model

        except Exception as e:
            logging.error(f"🚩 Error during model initialization: {e}")
            return None

    def available_device_count(self, device):
        """
        Get number of available devices.
        """
        if device.type == "cuda":
            return torch.cuda.device_count()
        elif device.type == "mps":
            return 1
        else:
            return torch.get_num_threads()

    def _distributed_cpu_transfer(self):
        """
        Move model to CPU in parallel.
        """
        try:
            if hasattr(self.model, "is_meta") and self.model.is_meta:
                self.model = self.model.to_empty(device="cpu")
                return

            num_cores = self.available_device_count(self.device.type)
            params = list(self.model.parameters())
            chunk_size = max(1, len(params) // num_cores)
            param_chunks = [
                params[i * chunk_size : (i + 1) * chunk_size]
                for i in range(num_cores)
            ]

            buffers = list(self.model.buffers())
            buffer_chunk_size = max(1, len(buffers) // num_cores)
            buffer_chunks = [
                buffers[i * buffer_chunk_size : (i + 1) * buffer_chunk_size]
                for i in range(num_cores)
            ]

            def transfer_to_cpu(chunk):
                for tensor in chunk:
                    if not tensor.is_meta:
                        tensor.data = tensor.data.to("cpu", non_blocking=True)

            with ThreadPoolExecutor(max_workers=num_cores) as executor:
                executor.map(transfer_to_cpu, param_chunks)
                executor.map(transfer_to_cpu, buffer_chunks)
                self.model = self.model.to("cpu")

        except Exception as e:
            logging.error(f"🚩 Error during CPU transfer: {e}")

    def _distributed_gpu_transfer(self):
        """
        Move model to GPU using CUDA streams.
        """
        try:
            if hasattr(self.model, "is_meta") and self.model.is_meta:
                self.model = self.model.to_empty(device=self.device.type)
                return

            num_streams = self.available_device_count(self.device.type)
            streams = [torch.cuda.Stream(device=i) for i in range(num_streams)]

            params = list(self.model.parameters())
            chunk_size = len(params) // num_streams
            chunks = [
                params[i * chunk_size : (i + 1) * chunk_size]
                for i in range(num_streams)
            ]

            for stream, chunk in zip(streams, chunks):
                with torch.cuda.stream(stream):
                    for param in chunk:
                        if not param.is_meta:
                            param.data = param.data.to(
                                self.device.type, non_blocking=True
                            )

            for stream in streams:
                stream.synchronize()

            with torch.cuda.amp.autocast(enabled=True):
                self.model = self.model.to(self.device.type)

        except Exception as e:
            logging.error(f"🚩 Error during GPU transfer: {e}")
