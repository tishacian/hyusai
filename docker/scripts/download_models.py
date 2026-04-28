from huggingface_hub import snapshot_download

from src.flashreranker import RerankerConfig
from src.globalvariables import EMBEDDING_NAME

# Formats not needed for inference — skip to minimise download size.
_IGNORE_FORMATS = [
    "*.msgpack",
    "*.h5",
    "flax_model*",
    "tf_model*",
    "rust_model.ot",
    "onnx/*",
    "openvino/*",
]

# Embedding model ships both pytorch_model.bin and model.safetensors;
# transformers/sentence-transformers prefers SafeTensors, so skip the legacy bin.
_IGNORE_EMBEDDING = _IGNORE_FORMATS + ["pytorch_model.bin"]

# Reranker repo may only have pytorch_model.bin — keep both weight formats.
_IGNORE_RERANKER = _IGNORE_FORMATS

_RERANKER_MODEL = RerankerConfig().model_name

if __name__ == "__main__":
    print(f"Downloading embedding model: {EMBEDDING_NAME} ...")
    snapshot_download(repo_id=EMBEDDING_NAME, ignore_patterns=_IGNORE_EMBEDDING)
    print(f"Embedding model {EMBEDDING_NAME!r} ready.")

    print(f"Downloading reranker model: {_RERANKER_MODEL} ...")
    snapshot_download(repo_id=_RERANKER_MODEL, ignore_patterns=_IGNORE_RERANKER)
    print(f"Reranker model {_RERANKER_MODEL!r} ready.")
