import os
from enum import Enum, StrEnum
from pathlib import Path

from configuration import get_backend_config, get_vlm_config

# %% Directory

REPO_PATH = Path(__file__).parent.parent
DATA_PATH = REPO_PATH / "data"
IMG_PATH = REPO_PATH / "image"
VECTOR_STORE_PATH = REPO_PATH / "vector_store"
EMBEDDING_CACHE_STORE = ".cache/"

# -- Check if paths exist otherwise, create one
if not os.path.exists(DATA_PATH):
    os.makedirs(DATA_PATH)

if not os.path.exists(IMG_PATH):
    os.makedirs(IMG_PATH)

if not os.path.exists(VECTOR_STORE_PATH):
    os.makedirs(VECTOR_STORE_PATH)
# %%
# -- Helper for suggestions
HELP = {  # help suggestions..
    "HuggingFace": (
        "You can get the HuggingFace token from settings of your "
        "Huggingface account"
    ),
    "LLM_Model": (
        "An instruction LLM model well (distilled or not) necessary to provide "
        "the right answer"
        + "\n"
        "toward the particular context"
    ),
    "Instruction_Embedding": (
        "An instruction LLM Embedding well suited to provide the right "
        "answer"
        + "\n"
        + "toward the particular context"
    ),
    "Vector_store": (
        "A list vector embedding created using the instruction embedding"
    ),
    "Temperature": (
        "Apply a larger temperature when sampling for challenging tokens, allowing LLMs to explore"
        + "\n"
        + "diverse choices. A smaller temperature for confident tokens avoiding the influence "
        + "\n"
        + "of tail randomness noises"
    ),
    "Max_character": (
        "The maximum number of characters to generated. This can be similar to the maximum token"
        + "\n"
        + " size of the embedding space. The default is set to 500."
    ),
    "index_type": "Select desired vector types",
    "pipeline": (
        "Select the desired pipeline. Default is without Chain of Thought (COT)"
    ),
    "template": (
        "Select a template style of choice. Default is a simple template."
    ),
    "reranker": (
        "Reranker algorithm selects between two different response types. The first is Reciprocal Rank Fusion,"
        + "\n"
        + "The other is the Flash reranker, which uses a Cross-Encoder for reranking."
    ),
    "new_vector_store": (
        "If choose <New> in the dropdown / multiselect box, name the new vector store. Otherwise, "
        + "\n"
        + "fill in the existing vector store to merge."
    ),
}

# -- Template for LLM prompting -->
TEMPLATE = ["Default", "Custom"]

# -- Summplementary models for Embedding
SUPPLEMENT = [
    "Alibaba-NLP/gte-large-en-v1.5",
    "sentence-transformers/all-mpnet-base-v2",
    "mixedbread-ai/mxbai-embed-large-v1",
    "WhereIsAI/UAE-Large-V1",
    "avsolatorio/GIST-large-Embedding-v0",
    "w601sxs/b1ade-embed",
    "Labib11/MUG-B-1.6",
    "WhereIsAI/UAE-Large-V1",
]

# -- Embedding name
EMBEDDING_NAME = (
    "sentence-transformers/all-mpnet-base-v2"  # all-mpnet-base-v2 is best; "sentence-transformers/all-MiniLM-L6-v2" (competitive)
)

SINGLE_FILE = 1  # single files
RANDOM_SEED = 42
MAX_MODEL_LEN: int = (
    None  # <-- switch maximum model length here. 64 -> Llama3-70; 128 -> Llama3-8b
)

# -- LLM configuration (LLM-as-a-service)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "").strip()
LLM_MODEL_NAME = (
    os.getenv("LLM_MODEL_NAME")
    or ""
).strip()
LLM_BASE_URL = (
    os.getenv("LLM_BASE_URL")
    or ""
).strip()


# %% reasoning types


class ReasoningType(StrEnum):
    """Defines different types of reasoning for the LLM"""

    FACTUAL = "factual"
    ANALYTICAL = "analytical"
    COMPARATIVE = "comparative"
    CAUSAL = "causal"
    HYPOTHETICAL = "hypothetical"


# %% StrEnums


class Reranker(StrEnum):
    RRF = "RRF"
    FLASHRERANKER = "FlashReranker"


class Models(StrEnum):
    LLAMA31_8B = "neuralmagic/Meta-Llama-3.1-8B-Instruct-quantized.w4a16"
    LLAMA31_70B = "neuralmagic/Meta-Llama-3.1-70B-Instruct-quantized.w4a16"
    LLAMA31_405B = "neuralmagic/Meta-Llama-3.1-405B-Instruct-quantized.w4a16"
    LLAMA3_8B = "neuralmagic/Meta-Llama-3-8B-Instruct-quantized.w4a16"
    LLAMA3_70B = "neuralmagic/Meta-Llama-3-70B-Instruct-quantized.w4a16"
    LLAMA2_7B = "neuralmagic/Llama-2-7b-chat-quantized.w4a16"
    LLAMA2_13B = "TheBloke/Llama-2-13B-chat-GPTQ"
    MISTRAL_LARGE = "neuralmagic/Mistral-7B-Instruct-v0.3-quantized.w4a16"
    MISTRAL_SMALL = "neuralmagic/Mistral-Nemo-Instruct-2407-quantized.w4a16"
    GEMMA2 = "neuralmagic/gemma-2-9b-it-quantized.w4a16"
    TINYLLAMA = "neuralmagic/TinyLlama-1.1B-Chat-v1.0-marlin"
    LAMINIGPT = "MBZUAI/LaMini-GPT-774M"
    LAMININEO = "MBZUAI/LaMini-Neo-125M"
    LAMINICEREBRAS = "MBZUAI/LaMini-Cerebras-590M"
    LAMNINIFLAN = "MBZUAI/LaMini-Flan-T5-783M"


class GPUModels(StrEnum):
    LLAMA31_8B = "neuralmagic/Meta-Llama-3.1-8B-Instruct-quantized.w4a16"
    LLAMA31_70B = "neuralmagic/Meta-Llama-3.1-70B-Instruct-quantized.w4a16"
    LLAMA31_405B = "neuralmagic/Meta-Llama-3.1-405B-Instruct-quantized.w4a16"
    LLAMA3_8B = "neuralmagic/Meta-Llama-3-8B-Instruct-quantized.w4a16"
    LLAMA3_70B = "neuralmagic/Meta-Llama-3-70B-Instruct-quantized.w4a16"
    LLAMA2_7B = "neuralmagic/Llama-2-7b-chat-quantized.w4a16"
    LLAMA2_13B = "TheBloke/Llama-2-13B-chat-GPTQ"
    MISTRAL_LARGE = "neuralmagic/Mistral-7B-Instruct-v0.3-quantized.w4a16"
    MISTRAL_SMALL = "neuralmagic/Mistral-Nemo-Instruct-2407-quantized.w4a16"
    GEMMA2 = "neuralmagic/gemma-2-9b-it-quantized.w4a16"
    TINYLLAMA = "neuralmagic/TinyLlama-1.1B-Chat-v1.0-marlin"


class CPUModels(StrEnum):
    LLAMA32_3B_INSTRUCT = "patrickzj/Llama-3.2-3B-Instruct-Q2_K-GGUF"


class CPUTokenizer(StrEnum):
    LLAMA32_3B_INSTRUCT_TOK = (
        "fbaldassarri/meta-llama_Llama-3.2-3B-Instruct-auto_awq-int4-gs128-sym"
    )


# VLM Models
class VLMModels(StrEnum):
    # vLLM versions (preferred for speed, but cannot be used if vLLM instance is already running)
    VLLM_SMOLVLM_256M = "vllm-smolvlm-256m"
    VLLM_SMOLVLM_500M = "vllm-smolvlm-500m"
    VLLM_SMOLVLM_2_2B = "vllm-smolvlm-2.2b"
    VLLM_MOONDREAM = "vllm-moondream"
    VLLM_QWEN = "vllm-qwen"
    # classical versions (can be used if vLLM instance is already running)
    SMOLVLM_256M = "smolvlm-256m"
    SMOLVLM_500M = "smolvlm-500m"
    SMOLVLM_2_2B = "smolvlm-2.2b"
    MOONDREAM = "moondream"
    QWEN = "qwen"


GPU_MODEL_SET = {model for model in GPUModels}
CPU_MODEL_SET = {model for model in CPUModels}

DEFAULT_CPU_MODEL = CPUModels.LLAMA32_3B_INSTRUCT
DEFAULT_CPU_TOKENIZER = CPUTokenizer.LLAMA32_3B_INSTRUCT_TOK
LARGE_MODELS = [
    Models.LLAMA31_8B,
    Models.LLAMA31_70B,
    Models.LLAMA31_405B,
    Models.LLAMA3_70B,
    Models.MISTRAL_LARGE,
]


class ChunkingMethod(StrEnum):
    RECURSIVE_CHARACTER = "recursive_character"
    FIXED = "fixed"
    SEMANTIC = "semantic"
    TOKEN_BASED = "token_based"
    HIERARCHICAL = "hierarchical"
    MODEL_BASED = "model_based"


class IndexType(StrEnum):
    FAISS = "faiss"
    CHROMA = "chroma"
    WEAVIATE = "weaviate"


class OptimalMethod(StrEnum):
    ELBOW = "elbow"
    SILHOUETTE = "silhouette"
    GAP = "gap"


class PipelineType(StrEnum):
    HAHCOMPOSITE = "C-HAH RAG"
    HAH = "HAH RAG"
    NAIVE = "Naive RAG"


class OCRConfig(Enum):
    USE_OCR = not get_backend_config().disable_ocr_for_pdf
    OCR_DPI = 150
    FORCE_OCR = get_backend_config().force_ocr_on_all_pdf
    LANGS = os.getenv("LANGS", "eng fra deu spa ita por kor ara").split(" ")


class GPUMemoryStatus(Enum):
    AVAILABLE = "available"
    INSUFFICIENT = "insufficient"
    UNAVAILABLE = "unavailable"


# -- GPU memory requirements (in GiB)
GPU_MEMORY_REQUIREMENTS = {
    "neuralmagic/Meta-Llama-3.1-8B-Instruct-quantized.w4a16": 16,
    "neuralmagic/Meta-Llama-3.1-70B-Instruct-quantized.w4a16": 70,
    "neuralmagic/Meta-Llama-3.1-405B-Instruct-quantized.w4a16": 200,
    "neuralmagic/Meta-Llama-3-8B-Instruct-quantized.w4a16": 16,
    "neuralmagic/Meta-Llama-3-70B-Instruct-quantized.w4a16": 70,
    "neuralmagic/Llama-2-7b-chat-quantized.w4a16": 14,
    "TheBloke/Llama-2-13B-chat-GPTQ": 26,
    "neuralmagic/Mistral-7B-Instruct-v0.3-quantized.w4a16": 14,
    "neuralmagic/Mistral-Nemo-Instruct-2407-quantized.w4a16": 8,
    "neuralmagic/gemma-2-9b-it-quantized.w4a16": 18,
    "neuralmagic/TinyLlama-1.1B-Chat-v1.0-marlin": 2,
    "MBZUAI/LaMini-GPT-774M": 8,
    "MBZUAI/LaMini-Neo-125M": 4,
    "MBZUAI/LaMini-Cerebras-590M": 8,
    "MBZUAI/LaMini-Flan-T5-783M": 8,
}

# -- Default requirement (78% of RTX5090 memory ~25 GiB)
DEFAULT_GPU_MEMORY_REQUIREMENT = 25

# Safety margin memory (reserved memory, also in GiB)
GPU_MEMORY_SAFETY_MARGIN = 2

# Maximum trivial message length
TRIVIAL_LEN: int = 100


class PDFProcessingConfig(Enum):
    # PDF Processing method: "markdown_converter" or "ocr"
    PDF_PROCESSING_METHOD = "markdown_converter"

    # "ocr" fallback when markdown fails
    ENABLE_FALLBACK = True
    FALLBACK_METHOD = "ocr"

    # OCR-specific settings (when using OCR method)
    OCR_DPI = 150
    OCR_FORCE_OCR = True

    # Markdown converter settings (when using markdown method)
    ENABLE_VLM = False
    VLM_MODEL = "smolvlm-256m"
    EXTRACT_IMAGES = True
    EXTRACT_TABLES = True

    # File saving settings
    DISABLE_FILE_SAVING = get_backend_config().disable_file_saving

    # Performance settings
    MAX_WORKERS = 4
    TIMEOUT_SECONDS = 300


class VLMConfig(Enum):
    ENABLE_VLM = get_vlm_config().enable_vlm
    VLM_MODEL = get_vlm_config().vlm_model
    VLM_WORKERS = get_vlm_config().vlm_workers
    MAX_WORKERS = get_vlm_config().max_workers
    SKIP_LARGE_IMAGES = get_vlm_config().skip_large_images
    MAX_MODEL_LEN = get_vlm_config().max_model_len
    GPU_MEMORY_UTILIZATION = get_vlm_config().gpu_memory_utilization
    TEMPERATURE = get_vlm_config().temperature
    MAX_TOKENS = get_vlm_config().max_tokens
    TOP_P = get_vlm_config().top_p
    FREQUENCY_PENALTY = get_vlm_config().frequency_penalty
    PRESENCE_PENALTY = get_vlm_config().presence_penalty
    REPETITION_PENALTY = get_vlm_config().repetition_penalty
    MAX_IMAGE_SIZE = get_vlm_config().max_image_size
    MIN_IMAGE_SIZE = get_vlm_config().min_image_size
    MAX_TOKENS_LIMIT = get_vlm_config().max_tokens_limit
    JPEG_QUALITY_LEVELS = get_vlm_config().jpeg_quality_levels
    DEVICE = get_vlm_config().device
    USE_FLASH_ATTENTION = get_vlm_config().use_flash_attention
    TORCH_DTYPE = get_vlm_config().torch_dtype
