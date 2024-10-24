import os
from enum import StrEnum
from pathlib import Path

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
HELP = {  # help suggestions...
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

# -- LLM Models
LLM_NAMES = [
    "MBZUAI/LaMini-GPT-774M",
    "MBZUAI/LaMini-GPT-1.5B",
    "MBZUAI/LaMini-Neo-125M",
    "MBZUAI/LaMini-Neo-1.3B",
    "MBZUAI/LaMini-Cerebras-590M",
    "MBZUAI/LaMini-Cerebras-1.3B",
    "MBZUAI/LaMini-Flan-T5-783M",
    "TheBloke/Mistral-7B-Instruct-v0.1-GPTQ",
]

# -- Embedding name
EMBEDDING_NAME = "sentence-transformers/all-mpnet-base-v2"

SINGLE_FILE = 1  # single files
RANDOM_SEED = 42


# %% StrEnums


class PipelineTypes(StrEnum):
    DEFAULT = "Default"
    COT = "COT"
    AsynCOT = "AsynCot"


class Reranker(StrEnum):
    RRF = "RRF"
    FLASHRERANKER = "FlashReranker"


class Models(StrEnum):
    LLAMA3 = "neuralmagic/Meta-Llama-3.1-8B-Instruct-quantized.w4a16"
    MISTRAL = "TheBloke/Mistral-7B-v0.1-AWQ"
    TINYLLAMA = "TheBloke/TinyLlama-1.1B-Chat-v0.3-AWQ"
    GEMMA2 = "neuralmagic/gemma-2-9b-it-quantized.w4a16"
    LAMINIGPT = "MBZUAI/LaMini-GPT-774M"


class ChunkingMethod(StrEnum):
    FIXED = "fixed"
    RECURSIVE_CHARACTER = "recursive_character"
    SEMANTIC = "semantic"
    TOKEN_BASED = "token_based"
    HIERARCHICAL = "hierarchical"
    MODEL_BASED = "model_based"


class IndexType(StrEnum):
    FAISS = "faiss"
    CHROMA = "chroma"
    WEAVIATE = "weaviate"
    # HNSW = "hnsw" # uses faiss also


class OptimalMethod(StrEnum):
    ELBOW = "elbow"
    SILHOUETTE = "silhouette"
    GAP = "gap"
