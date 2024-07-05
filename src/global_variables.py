from enum import Enum, StrEnum
from pathlib import Path

REPO_PATH = Path(__file__).parent.parent
DATA_PATH = REPO_PATH / "data"
IMG_PATH = REPO_PATH / "image"
VECTOR_STORE_PATH = REPO_PATH / "vector_store"

# %% Default variables


class PipelineTypes(StrEnum):
    DEFAULT = "default"
    COT = "cot"
    AsynCOT = "asyncot"


class Reranker(StrEnum):
    RRF = "rrf"
    FLASHRERANKER = "flashreranker"


class DefaultValues(Enum):
    SINGLE_FILE = 1
    DEFAULT = "default"
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
    EMBEDDING_NAME = "sentence-transformers/all-mpnet-base-v2"
    VECTOR_TYPES = ["FAISS", "Chroma", "Weaviate", "PGVector"]
    TEMPLATES = ["Default", "Custom"]
    DEFAULT_PIPELINE = "default"
    COT_PIPELINE = "cot"
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
    # --
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
        "vector_type": "Slect desired vector types",
        "pipeline": "Select the desired pipeline. Default is without Chain of Thought (COT)",
        "template": "Select a template style of choice. Default is a simple template.",
        "reranker": "Reranker algorithm selects between two different response types. The first is Reciprocal Rank Fusion,"
        + "\n"
        + "The other is the Flash reranker, which uses a Cross-Encoder for reranking.",
    }
