import os
from enum import Enum, StrEnum
from pathlib import Path
from typing import Set

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


class ReasoningType(Enum):
    """Defines different types of reasoning for the LLM"""

    FACTUAL = "factual"
    ANALYTICAL = "analytical"
    COMPARATIVE = "comparative"
    CAUSAL = "causal"
    HYPOTHETICAL = "hypothetical"
    TRIVIAL = "trivial"


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


# -----------------------------
# Trivial-input detection vocabulary
# -----------------------------


TRIVIAL_LEN: int = 100

TRIVIAL_ENGLISH_VOCABULARY: Set[str] = {
    "hello",
    "hi",
    "hey",
    "yo",
    "sup",
    "good morning",
    "good afternoon",
    "good evening",
    "howdy",
    "greetings",
    "how are you",
    "how are ya",
    "thanks",
    "thank you",
    "thx",
    "ty",
    "merci",
    "gracias",
    "cool, thanks",
    "ok, thanks",
    "great, thanks",
    "morning",
    "evening",
    "good noon",
    "good eve",
    "gm",
    "gn",
    "thank u",
    "thanx",
    "thnx",
    "thanks a lot",
    "thank you so much",
    "appreciate it",
    "much obliged",
    "cheers",
    "cheers mate",
    "ta",
    "hiya",
    "wassup",
    "thanks a ton",
    "how are you doing today",
    "good night",
    "night",
    "nite",
    "sleep well",
    "sweet dreams",
    "see ya",
    "see you",
    "bye",
    "goodbye",
    "farewell",
    "catch ya later",
    "later",
    "peace",
    "peace out",
    "take care",
    "have a good one",
    "until next time",
    "ttyl",
    "brb",
    "is",
    "it",
    "you",
    "your",
    "you're",
    "you've",
    "you'll",
    "you'd",
    "in",
    "at",
    "to",
    "of",
    "and",
    "or",
    "but",
    "if",
    "be right back",
    "one sec",
    "hold on",
    "wait up",
    "just a minute",
    "give me a sec",
    "hang tight",
    "bear with me",
    "sorry",
    "my bad",
    "oops",
    "whoops",
    "my apologies",
    "excuse me",
    "pardon",
    "forgive me",
    "apologies",
    "no worries",
    "no problem",
    "dont mention it",
    "you're welcome",
    "anytime",
    "my pleasure",
    "glad to help",
    "happy to help",
    "sure thing",
    "of course",
    "absolutely",
    "definitely",
    "for sure",
    "yep",
    "yeah",
    "yes",
    "yup",
    "uh huh",
    "right on",
    "sounds good",
    "okay",
    "ok",
    "alright",
    "fine",
    "not bad",
    "decent",
    "fair enough",
    "i see",
    "got it",
    "understood",
    "makes sense",
    "right",
    "bingo",
    "that's it",
    "you got it",
    "spot on",
    "on point",
    "nailed it",
    "well done",
    "good job",
    "nice work",
    "keep it up",
    "way to go",
    "congrats",
    "congratulations",
    "well played",
    "impressive",
    "goodnight",
    "adios",
    "ciao",
    "au revoir",
    "sayonara",
    "cheerio",
    "toodles",
    "so long",
    "talk soon",
    "solid",
    "tight",
    "clean",
    "smooth",
    "slick",
    "fresh",
    "crisp",
    "sharp",
    "on fleek",
    "tell me about it",
    "you said it",
    "couldnt agree more",
    "totally",
    "completely",
    "entirely",
    "wholly",
    "utterly",
    "fully",
    "100%",
    "all the way",
    "through and through",
    "to the core",
    "without a doubt",
    "no question",
    "hands down",
    "by far",
    "thats for sure",
    "you bet",
    "you betcha",
    "quite so",
    "quite",
    "somewhat",
    "kind of",
    "sort of",
    "more or less",
    "roughly",
    "approximately",
    "about",
    "around",
    "nearly",
    "almost",
    "close to",
    "just about",
    "not bad at all",
    "never",
    "not ever",
    "at no time",
    "under no circumstances",
    "by no means",
    "not at all",
    "not in the least",
    "not one bit",
    "not a chance",
    "no way",
    "forget it",
    "dream on",
    "in your dreams",
    "fat chance",
    "when pigs fly",
    "over my dead body",
    "not if i can help it",
    "not on my watch",
    "not happening",
    "aint gonna happen",
    "nope",
    "nah",
    "negative",
    "nada",
    "zilch",
    "nothing",
    "none",
    "neither",
    "nor",
    "however",
    "nevertheless",
    "nonetheless",
    "still",
    "yet",
    "though",
    "although",
    "even though",
    "despite",
    "in spite of",
    "regardless",
    "anyway",
    "anyhow",
    "in any case",
    "at any rate",
    "either way",
    "one way or another",
    "somehow",
    "someway",
    "whatever",
    "whenever",
    "wherever",
    "whoever",
    "whomever",
    "whichever",
    "why not",
    "sure why not",
    "why not indeed",
    "indeed why not",
    "what the heck",
    "what the hell",
    "why the hell not",
    "might as well",
    "could be worse",
    "better than nothing",
    "something is better than nothing",
    "half a loaf is better than none",
    "beggars cant be choosers",
    "take what you can get",
    "it is what it is",
    "such is life",
    "thats life",
    "life goes on",
    "cest la vie",
    "what can you do",
    "what are you gonna do",
    "whatcha gonna do",
    "whaddya gonna do",
    "what else is new",
    "same old same old",
    "nothing new under the sun",
    "been there done that",
    "story of my life",
    "tell me something i dont know",
    "no kidding",
    "you dont say",
    "are you serious",
    "are you kidding me",
    "youve got to be kidding",
    "you must be joking",
    "pull the other one",
    "get out of here",
    "get outta here",
    "no way jose",
    "come on",
    "come off it",
    "give me a break",
    "cut it out",
    "knock it off",
    "stop it",
    "quit it",
    "enough",
    "thats enough",
    "im done",
    "im out",
    "i gotta go",
    "anyone",
    "someone",
    "somebody",
    "i",
    'a',
    'b',
    'c',
    'd',
    'e',
    'f',
    'g',
    'h',
    'j',
    'k',
    'l',
    'm',
    'n',
    'o',
    'p',
    'q',
    'r',
    's',
    't',
    'u',
    'v',
    'w',
    'x',
    'y',
    'z',
    "I'm",
    "I've",
    "I'll",
    "I'd",
    "re",
    "im",
    "ive",
    "ill",
    "id",
    "youre",
    "youve",
    "gotta run",
    "thank you very much",
    "hey there how are you doing today",
    "hello there good sir hope everything is okay",
    "thank you very much that was very helpful",
    "don",
    "dont",
    "didnt",
    "couldn",
    "couldnt",
    "shouldnt",
    "wont",
    "for",
    "from",
    "as",
    "by",
    "that",
    "this",
    "these",
    "those",
    "them",
    "their",
    "theirs",
    "not",
    "no",
    "got",
    "be",
    "me",
    "out",
    "outta",
    "outta here",
    "outta there",
    "our",
    "ours",
    "yours",
    "anybody",
    "anybody there",
    "anybody there?",
    "my",
    "anywhere",
    "somewhere",
    "everywhere",
    "have",
    "has",
    "had",
    "off",
    "with",
    "we",
    "we're",
    "we've",
    "we'll",
    "we'd",
    "went",
    "without",
    "on",
    "need",
    "should",
    "would",
    "could",
    "might",
    "may",
    "can",
    "must",
    "mustn't",
    "mustn",
    "mustnt",
    "ought",
    "oughtn't",
    "oughtnt",
    "gotta",
    "gotta go",
    "anything",
    "something",
    "ve",
    "was",
    "were",
    "sometime",
    "sometimes",
    "time to go",
}
