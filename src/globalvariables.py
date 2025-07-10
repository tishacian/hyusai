import os
from enum import Enum, StrEnum
from pathlib import Path

from configuration import get_backend_config

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
    "HuggingFace": "You can get theHuggingFace token from settings of your Huggingface account",
    "LLM_Model": "An instruction LLM model well (distilled or not) necessary to provide the right anwser"
    + "\n"
    "toward the particular context",
    "Instruction_Embedding": "An instruction LLM Embedding well suited to provide the right anwser"
    + "\n"
    + "toward the particular context",
    "Vector_store": "A lsit vector embedding created using the instruction embedding",
    "Temperature": "Apply a larger temperature when sampling for challenging tokens, allowing LLMs to explore"
    + "\n"
    + "diverse choices. A smaller temperature for confident tokens avoiding the influence "
    + "\n"
    + "of tail randomness noises",
    "Max_characer": "The maximum number of characters to generated. This can be similar to the maximum token"
    + "\n"
    + " size of the embedding space. The default is set to 500.",
    "index_type": "Select desired vector types",
    "pipeline": "Select the desired pipeline. Default is without Chain of Thought (COT)",
    "template": "Select a template style of choice. Default is a simple template.",
    "reranker": "Reranker algorithm selects between two different response types. The first is Reciprocal Rank Fusion,"
    + "\n"
    + "The other is the Flash reranker, which uses a Cross-Encoder for reranking.",
    "new_vector_store": "If choose <New> in the dropdown / multiselect box, name the new vector store. Otherwise, "
    + "\n"
    + "fill in the existing vector store to merge.",
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
EMBEDDING_NAME = "sentence-transformers/all-mpnet-base-v2"  # all-mpnet-base-v2 is best;  "sentence-transformers/all-MiniLM-L6-v2" (competitive)

SINGLE_FILE = 1  # single files
RANDOM_SEED = 42
MAX_MODEL_LEN: int = (
    None  # <-- switch maximum model length here. 64 -> Llama3-70; 128 -> Llama3-8b
)

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


# --- Metadata storage mode ---------------------------------------------------
class MetadataStorageMode(StrEnum):
    """Controls how document metadata is stored with chunks.

    INPLACE    -> full metadata duplicated on every chunk (legacy behaviour)
    REFERENCE  -> only ``doc_id`` stored on each chunk, full metadata kept in
                  a separate pickle keyed by ``doc_id``.  
    """

    INPLACE = "inplace"
    REFERENCE = "reference"


# ── Configure how metadata is stored ─────────────────────────────────────────
# Change the value below to switch between legacy *INPLACE* mode (full metadata
# duplicated on every chunk) and the new *REFERENCE* mode (per‐doc collection).

METADATA_STORAGE_MODE: MetadataStorageMode = MetadataStorageMode.REFERENCE  # ← set mode here


# Optional helper for runtime switching (e.g. from a UI)
def set_metadata_storage_mode(mode: MetadataStorageMode | str):
    """Update the global ``METADATA_STORAGE_MODE`` at runtime.

    Accepts either a ``MetadataStorageMode`` enum value or its string name
    ("inplace" / "reference").
    """

    global METADATA_STORAGE_MODE
    if isinstance(mode, str):
        mode = MetadataStorageMode(mode.lower())
    METADATA_STORAGE_MODE = mode


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

# -- Default requirement (7/8 of H100 memory ~70 GiB)
DEFAULT_GPU_MEMORY_REQUIREMENT = 70

# Safety margin memory (reserved memory, also in GiB)
GPU_MEMORY_SAFETY_MARGIN = 2

# Maximum trivial message length
TRIVIAL_LEN: int = 100
