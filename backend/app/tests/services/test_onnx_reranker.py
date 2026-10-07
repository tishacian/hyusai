"""ONNX cross-encoder engine: FlashReranker's contract on onnxruntime + tokenizers."""
import math
import os
import sys
import types
from importlib.util import find_spec
from pathlib import Path

import numpy as np
import pytest

from app.services.retrieval import onnx_reranker
from app.services.retrieval.onnx_reranker import OnnxReranker, has_model_files
from app.services.retrieval.reranker_config import RerankerConfig

MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class _Encoding:
    def __init__(self, ids):
        self.ids = ids
        self.attention_mask = [1] * len(ids)
        self.type_ids = [0] * len(ids)


class _Tokenizer:
    truncation = None
    padding = None

    def __init__(self):
        self.truncated_at = None

    @classmethod
    def from_file(cls, path):
        tokenizer = cls()
        tokenizer.path = path
        return tokenizer

    def enable_truncation(self, max_length, stride=0, strategy="longest_first"):
        self.truncated_at = (max_length, stride, strategy)

    def enable_padding(self):
        self.padding = {"strategy": "BatchLongest"}

    def encode_batch(self, pairs):
        width = max(len(passage) for _, passage in pairs)
        # One id per character, padded to the batch's longest passage.
        return [_Encoding([len(passage)] * width) for _, passage in pairs]


class _Session:
    calls = []

    def __init__(self, path, sess_options=None, providers=None):
        self.path, self.providers = path, providers
        self.threads = sess_options.intra_op_num_threads

    def get_inputs(self):
        return [types.SimpleNamespace(name="input_ids"), types.SimpleNamespace(name="attention_mask")]

    def run(self, outputs, feeds):
        _Session.calls.append(sorted(feeds))
        if (feeds["input_ids"] == 666).any():
            raise RuntimeError("bad batch")
        # Logit = passage length - 5: longer passages score higher.
        return [feeds["input_ids"][:, :1].astype(np.float32) - 5.0]


@pytest.fixture
def fake_runtime(monkeypatch, tmp_path):
    onnxruntime = types.ModuleType("onnxruntime")
    onnxruntime.SessionOptions = lambda: types.SimpleNamespace(intra_op_num_threads=0)
    onnxruntime.InferenceSession = _Session
    tokenizers = types.ModuleType("tokenizers")
    tokenizers.Tokenizer = _Tokenizer
    monkeypatch.setitem(sys.modules, "onnxruntime", onnxruntime)
    monkeypatch.setitem(sys.modules, "tokenizers", tokenizers)
    monkeypatch.setattr(OnnxReranker, "_sessions", {})
    _Session.calls = []
    directory = tmp_path / MODEL
    (directory / "onnx").mkdir(parents=True)
    (directory / "onnx" / "model.onnx").write_bytes(b"")
    (directory / "tokenizer.json").write_text("{}")
    return tmp_path


def test_scores_are_the_sigmoid_of_the_logit_in_input_order(fake_runtime):
    reranker = OnnxReranker(RerankerConfig(model_name=MODEL, batch_size=8), models_dir=fake_runtime)
    passages = ["abcdefg", "abc", "abcdefghij"]
    scores = reranker.score("q", passages)
    expected = [1 / (1 + math.exp(-(len(p) - 5))) for p in passages]
    assert scores == pytest.approx(expected)


def test_only_the_inputs_the_graph_declares_are_fed(fake_runtime):
    OnnxReranker(RerankerConfig(model_name=MODEL), models_dir=fake_runtime).score("q", ["a"])
    assert _Session.calls == [["attention_mask", "input_ids"]]


def test_batches_follow_flash_reranker_cpu_size_and_a_failed_batch_scores_zero(fake_runtime):
    reranker = OnnxReranker(RerankerConfig(model_name=MODEL, batch_size=8), models_dir=fake_runtime)
    passages = ["a" * 6] * 2 + ["x" * 666] + ["a" * 6] * 3
    scores = reranker.score("q", passages)
    assert len(_Session.calls) == 3  # batch of 8 // 4 = 2 per run
    assert scores[2:4] == [0.0, 0.0]
    assert scores[0] == pytest.approx(1 / (1 + math.exp(-1)))


def test_rerank_sorts_applies_the_threshold_and_keeps_all_when_none_pass(fake_runtime):
    reranker = OnnxReranker(RerankerConfig(model_name=MODEL, threshold=0.5), models_dir=fake_runtime)
    ranked, scores = reranker.rerank("q", ["abc", "abcdefgh", "abcdef"], return_scores=True)
    assert ranked == ["abcdefgh", "abcdef"]
    assert scores == sorted(scores, reverse=True)
    assert reranker("q", ["a", "ab"]) == ["ab", "a"]  # nothing passes: all, sorted


def test_truncation_uses_the_reranker_max_length_and_sessions_are_shared(fake_runtime):
    config = RerankerConfig(model_name=MODEL, max_length=256, num_threads=3)
    first = OnnxReranker(config, models_dir=fake_runtime)
    second = OnnxReranker(config, models_dir=fake_runtime)
    assert first.tokenizer.truncated_at == (256, 0, "longest_first")
    assert first.session is second.session
    assert first.session.threads == 3 and first.session.providers == ["CPUExecutionProvider"]
    other = OnnxReranker(RerankerConfig(model_name=MODEL, max_length=512), models_dir=fake_runtime)
    assert other.tokenizer is not first.tokenizer


def test_missing_files_refuse_to_load(fake_runtime, tmp_path):
    assert has_model_files(fake_runtime, MODEL)
    assert not has_model_files(tmp_path / "elsewhere", MODEL)
    with pytest.raises(FileNotFoundError):
        OnnxReranker(RerankerConfig(model_name=MODEL), models_dir=tmp_path / "elsewhere")


REAL_MODELS = Path(os.environ.get("AGENTIUM_RAG_MODELS_DIR", "/opt/agentium-models"))
CARD = {
    "cross-encoder/ms-marco-MiniLM-L-6-v2": (8.607138, -4.320078),
    "cross-encoder/ms-marco-MiniLM-L-12-v2": (9.218911, -4.0780287),
}


@pytest.mark.parametrize("model", sorted(CARD))
def test_real_model_reproduces_the_model_card_logits(model):
    """The baked ONNX export scores like the published PyTorch model."""
    if find_spec("onnxruntime") is None or find_spec("tokenizers") is None:
        pytest.skip("onnxruntime/tokenizers not installed")
    if not has_model_files(REAL_MODELS, model):
        pytest.skip(f"model files not under {REAL_MODELS}")
    reranker = OnnxReranker(RerankerConfig(model_name=model), models_dir=REAL_MODELS)
    probabilities = reranker.score(
        "How many people live in Berlin?",
        [
            "Berlin had a population of 3,520,031 registered inhabitants in an area of 891.82 square kilometers.",
            "Berlin is well known for its museums.",
        ],
    )
    logits = [math.log(p / (1 - p)) for p in probabilities]
    assert logits == pytest.approx(CARD[model], abs=1e-3)


def test_module_imports_neither_torch_nor_transformers():
    import ast

    tree = ast.parse(Path(onnx_reranker.__file__).read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    } | {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert not imported & {"torch", "torchvision", "transformers"}
