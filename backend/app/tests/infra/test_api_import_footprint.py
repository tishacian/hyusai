"""Importing the RAG path must not reach for torch.

Until this guard, ``app.services.retrieval`` imported ``flash_reranker`` at
package import, which imports torch and transformers at module scope; through
the documents router that ran in every uvicorn worker and every Celery worker
at start-up. Now the engine is chosen when a rerank is first asked for.

The check records every attempt to import a forbidden package, through a meta
path finder placed first, so it holds whether or not torch is installed where
the test runs: a guarded ``try: import torch`` counts as much as a bare one.
"""
import json
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3]
FORBIDDEN = ("torch", "torchvision", "transformers")
MODULES = (
    "app.services.retrieval",
    "app.services.retrieval.contextual_compression",
    "app.services.retrieval.rerankers",
    "app.services.retrieval.onnx_reranker",
    "app.services.rag.cross_encoder_stage",
    "app.services.rag.document_service",
)

PROBE = f"""
import importlib, json, sys
forbidden = {FORBIDDEN!r}
attempts = []

class Recorder:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in forbidden:
            attempts.append(name)
        return None

sys.meta_path.insert(0, Recorder())
for module in {MODULES!r}:
    importlib.import_module(module)
print("FOOTPRINT " + json.dumps(sorted(set(attempts))))
"""


def test_rag_import_path_never_attempts_torch():
    result = subprocess.run(
        [sys.executable, "-c", PROBE], cwd=BACKEND, capture_output=True, text=True, timeout=600
    )
    lines = [line for line in result.stdout.splitlines() if line.startswith("FOOTPRINT ")]
    assert result.returncode == 0 and lines, result.stderr[-2000:]
    assert json.loads(lines[-1].removeprefix("FOOTPRINT ")) == []


def test_flash_reranker_stays_reachable_from_the_package():
    """The lazy export keeps ``from app.services.retrieval import FlashReranker``."""
    import app.services.retrieval as retrieval

    assert "FlashReranker" in retrieval.__all__
    engine = retrieval.FlashReranker  # None where torch is not installed
    assert engine is None or engine.__name__ == "FlashReranker"


def test_application_import_never_attempts_optuna():
    probe = PROBE.replace(repr(FORBIDDEN), repr(("optuna",))).replace(repr(MODULES), repr(("app.main",)))
    result = subprocess.run([sys.executable, "-c", probe], cwd=BACKEND, capture_output=True, text=True, timeout=120)
    lines = [line for line in result.stdout.splitlines() if line.startswith("FOOTPRINT ")]
    assert result.returncode == 0 and lines, result.stderr[-2000:]
    assert json.loads(lines[-1].removeprefix("FOOTPRINT ")) == []


def test_deep_runtime_metadata_and_api_never_attempt_provider_imports():
    modules = ("app.main", "app.services.ml.local_models", "app.services.ml.runtime", "app.workers.celery_ml")
    forbidden = ("torch", "torchvision", "transformers", "chronos", "sentence_transformers")
    probe = PROBE.replace(repr(FORBIDDEN), repr(forbidden)).replace(repr(MODULES), repr(modules))
    result = subprocess.run([sys.executable, "-c", probe], cwd=BACKEND, capture_output=True, text=True, timeout=120)
    lines = [line for line in result.stdout.splitlines() if line.startswith("FOOTPRINT ")]
    assert result.returncode == 0 and lines, result.stderr[-2000:]
    assert json.loads(lines[-1].removeprefix("FOOTPRINT ")) == []
