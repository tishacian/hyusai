"""Which cross-encoder engine answers, by setting and by what the image has."""
import sys
import types

import pytest

from app.services.retrieval import rerankers
from app.services.retrieval.reranker_config import RerankerConfig

MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


@pytest.fixture
def host(monkeypatch):
    """A host whose installed engines and model files the test decides."""
    state = {"torch": True, "onnx": True}
    monkeypatch.setattr(rerankers, "_torch_installed", lambda: state["torch"])
    monkeypatch.setattr(rerankers, "_onnx_runnable", lambda model: state["onnx"])
    return state


@pytest.mark.parametrize(
    ("setting", "torch", "onnx", "expected"),
    [
        ("auto", True, True, "torch"),  # an image keeps the engine it was qualified with
        ("auto", False, True, "onnx"),  # an image without torch reranks on ONNX
        ("onnx", True, True, "onnx"),
        ("torch", True, False, "torch"),
        ("torch", False, False, "torch"),  # forced: FlashReranker's ImportError reports it
        ("AUTO ", False, True, "onnx"),
    ],
)
def test_backend_selection(host, monkeypatch, setting, torch, onnx, expected):
    host.update(torch=torch, onnx=onnx)
    monkeypatch.setattr(rerankers.settings, "rag_reranker_backend", setting)
    assert rerankers.reranker_backend(MODEL) == expected


@pytest.mark.parametrize("setting", ["auto", "onnx"])
def test_no_engine_is_an_import_error_callers_already_degrade_on(host, monkeypatch, setting):
    host.update(torch=False, onnx=False)
    monkeypatch.setattr(rerankers.settings, "rag_reranker_backend", setting)
    with pytest.raises(ImportError, match="No cross-encoder engine"):
        rerankers.reranker_backend(MODEL)


def test_unknown_setting_is_refused(host, monkeypatch):
    monkeypatch.setattr(rerankers.settings, "rag_reranker_backend", "gpu")
    with pytest.raises(ValueError):
        rerankers.reranker_backend(MODEL)


def test_make_reranker_builds_the_onnx_engine_from_the_models_dir(host, monkeypatch, tmp_path):
    host.update(torch=False, onnx=True)
    monkeypatch.setattr(rerankers.settings, "rag_reranker_backend", "auto")
    monkeypatch.setattr(rerankers.settings, "rag_models_dir", str(tmp_path))
    built = {}

    class FakeOnnx:
        def __init__(self, config, *, models_dir):
            built.update(config=config, models_dir=models_dir)

    module = types.ModuleType("app.services.retrieval.onnx_reranker")
    module.OnnxReranker = FakeOnnx
    module.has_model_files = lambda *args: True
    monkeypatch.setitem(sys.modules, "app.services.retrieval.onnx_reranker", module)
    config = RerankerConfig(model_name=MODEL, max_length=256)
    assert isinstance(rerankers.make_reranker(config), FakeOnnx)
    assert built == {"config": config, "models_dir": str(tmp_path)}


def test_make_reranker_builds_flash_reranker_when_torch_is_chosen(host, monkeypatch):
    monkeypatch.setattr(rerankers.settings, "rag_reranker_backend", "torch")

    class FakeFlash:
        def __init__(self, config):
            self.config = config

    module = types.ModuleType("app.services.retrieval.flash_reranker")
    module.FlashReranker = FakeFlash
    monkeypatch.setitem(sys.modules, "app.services.retrieval.flash_reranker", module)
    reranker = rerankers.make_reranker(RerankerConfig(model_name=MODEL))
    assert isinstance(reranker, FakeFlash) and reranker.config.model_name == MODEL


def test_cross_encoder_stage_scores_through_the_factory(monkeypatch):
    from app.services.rag import cross_encoder_stage

    seen = {}

    class Engine:
        def score(self, query, passages):
            return [0.5] * len(passages)

    def factory(config):
        seen["config"] = config
        return Engine()

    monkeypatch.setattr(rerankers, "make_reranker", factory)
    scores = cross_encoder_stage._score_passages("q", ["a", "b"], model_name=MODEL, max_length=128)
    assert scores == [0.5, 0.5]
    assert seen["config"].model_name == MODEL and seen["config"].max_length == 128
