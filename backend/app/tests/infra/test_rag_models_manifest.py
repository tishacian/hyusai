"""The cross-encoder files baked into the images: pinned, verified, complete."""
import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.retrieval.onnx_reranker import MODEL_FILE, TOKENIZER_FILE

ROOT = Path(__file__).resolve().parents[4]
MANIFEST = ROOT / "backend" / "rag_models.lock.json"
sys.path.insert(0, str(ROOT / "backend" / "scripts"))
import fetch_rag_models  # noqa: E402


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_every_configured_cross_encoder_is_pinned():
    models = {model["name"]: model for model in _manifest()["models"]}
    for name in (settings.rag_cross_encoder_model_balanced, settings.rag_cross_encoder_model_deep):
        assert name in models, f"{name} is configured but not baked into the images"
    for model in models.values():
        assert re.fullmatch(r"[0-9a-f]{40}", model["revision"]), "pin a commit, not a branch"
        assert {MODEL_FILE.as_posix(), TOKENIZER_FILE} <= set(model["files"])
        for digest in model["files"].values():
            assert re.fullmatch(r"[0-9a-f]{64}", digest)


def test_images_bake_the_models_where_the_settings_read_them():
    for name in ("backend", "worker"):
        dockerfile = (ROOT / "docker" / f"Dockerfile.agentium-{name}").read_text(encoding="utf-8")
        assert f"--dest {settings.rag_models_dir}" in dockerfile


def _mirror(tmp_path: Path, files: dict[str, bytes]) -> tuple[Path, Path]:
    """A file:// mirror laid out like huggingface.co/<repo>/resolve/<rev>/<file>."""
    mirror, revision = tmp_path / "mirror", "a" * 40
    for relative, content in files.items():
        target = mirror / "org" / "repo" / "resolve" / revision / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    manifest = tmp_path / "lock.json"
    manifest.write_text(json.dumps({"models": [{
        "name": "org/model", "repo": "org/repo", "revision": revision,
        "files": {relative: hashlib.sha256(content).hexdigest() for relative, content in files.items()},
    }]}))
    return mirror, manifest


def test_fetch_downloads_verifies_and_is_idempotent(tmp_path, monkeypatch):
    mirror, manifest = _mirror(tmp_path, {"onnx/model.onnx": b"weights", "tokenizer.json": b"{}"})
    monkeypatch.setenv("RAG_MODELS_BASE_URL", mirror.as_uri())
    dest = tmp_path / "models"
    args = ["--manifest", str(manifest), "--dest", str(dest)]
    assert fetch_rag_models.main([*args, "--verify-only"]) == 1
    assert fetch_rag_models.main(args) == 0
    assert (dest / "org/model/onnx/model.onnx").read_bytes() == b"weights"
    # Fetched as root at build time, read by the non-root runtime user: a file
    # left at mkstemp's 0600 made onnxruntime fail with EACCES on the VM.
    for path in (dest / "org/model/onnx/model.onnx", dest / "org/model/tokenizer.json"):
        assert path.stat().st_mode & 0o044 == 0o044, oct(path.stat().st_mode)
    assert fetch_rag_models.main([*args, "--verify-only"]) == 0
    assert not list(dest.rglob(".partial-*"))
    # A warm layer does no I/O: an unreachable mirror is never contacted.
    monkeypatch.setenv("RAG_MODELS_BASE_URL", (tmp_path / "gone").as_uri())
    assert fetch_rag_models.main(args) == 0


def test_fetch_refuses_bytes_that_do_not_match_the_pin(tmp_path, monkeypatch):
    mirror, manifest = _mirror(tmp_path, {"tokenizer.json": b"{}"})
    lock = json.loads(manifest.read_text())
    lock["models"][0]["files"]["tokenizer.json"] = "0" * 64
    manifest.write_text(json.dumps(lock))
    monkeypatch.setenv("RAG_MODELS_BASE_URL", mirror.as_uri())
    with pytest.raises(SystemExit, match="sha256 mismatch"):
        fetch_rag_models.main(["--manifest", str(manifest), "--dest", str(tmp_path / "models")])
    assert not (tmp_path / "models" / "org/model/tokenizer.json").exists()
