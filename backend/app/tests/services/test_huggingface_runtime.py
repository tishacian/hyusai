"""Runtime/cache contracts use temporary snapshots and real local ONNX execution."""

from __future__ import annotations

import hashlib
import io
import json

import pytest

from app.services.huggingface import adapters
from app.services.huggingface.cache import ArtifactCache, ArtifactError, verify_snapshot


def manifest_for(files, *, artifact_id="artifact-one", format="safetensors"):
    return {
        "version": 2,
        "artifact_id": artifact_id,
        "kind": "model",
        "repo_id": "org/model",
        "revision": "a" * 40,
        "format": format,
        "files": {
            name: {"sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}
            for name, data in files.items()
        },
        "total_bytes": sum(map(len, files.values())),
    }


def provision(tmp_path, files, **kwargs):
    cache = ArtifactCache(tmp_path, max_bytes=1_000_000, min_free_bytes=0)
    manifest = manifest_for(files, **kwargs)
    snapshot = cache.materialize(manifest, lambda name, entry: io.BytesIO(files[name]))
    return cache, snapshot


def test_cache_streams_once_and_verifies_every_load(tmp_path):
    files = {"config.json": b"{}", "model.safetensors": b"some bytes"}
    cache, snapshot = provision(tmp_path, files)
    assert snapshot.path.name == "artifact-one"
    assert (
        cache.materialize(
            snapshot.manifest, lambda *args: pytest.fail("must reuse exact snapshot")
        ).fingerprint
        == snapshot.fingerprint
    )
    with cache.lease("artifact-one", snapshot.manifest) as leased:
        assert leased.fingerprint == snapshot.fingerprint
    (snapshot.path / "model.safetensors").chmod(0o644)
    (snapshot.path / "model.safetensors").write_bytes(b"bad bytes!")
    with pytest.raises(ArtifactError, match="verification"):
        with cache.lease("artifact-one", snapshot.manifest):
            pass


def test_failed_transfer_never_publishes_or_keeps_temporary_files(tmp_path):
    files = {"model.safetensors": b"safe weights"}
    manifest = manifest_for(files)
    cache = ArtifactCache(tmp_path, min_free_bytes=0)
    with pytest.raises(ArtifactError):
        cache.materialize(manifest, lambda *args: io.BytesIO(b"wrong weights"))
    assert not (tmp_path / "artifact-one").exists()
    assert not list(tmp_path.glob(".staging-*"))
    assert cache.materialize(manifest, lambda *args: io.BytesIO(files["model.safetensors"]))


def test_active_leases_prevent_eviction(tmp_path):
    files = {"model.safetensors": b"weights" * 10}
    cache, one = provision(tmp_path, files)
    two = manifest_for(files, artifact_id="artifact-two")
    cache.max_bytes = cache._usage() + 10
    with cache.lease("artifact-one"):
        with pytest.raises(ArtifactError) as caught:
            cache.materialize(two, lambda name, entry: io.BytesIO(files[name]))
        assert caught.value.code == "HF_CACHE_FULL"
        assert one.path.exists()
    cache.materialize(two, lambda name, entry: io.BytesIO(files[name]))
    assert not one.path.exists()


@pytest.mark.parametrize(
    "path", ["../outside", "/absolute", "a/../b", "a//b", "a\\b", "manifest.json"]
)
def test_cache_rejects_path_escape_and_reserved_manifest(tmp_path, path):
    with pytest.raises(ArtifactError):
        provision(tmp_path, {path: b"bad"})


def test_cache_rejects_unlisted_files_and_symlinks(tmp_path):
    cache, snapshot = provision(tmp_path, {"model.safetensors": b"weights"})
    extra = snapshot.path / "extra.py"
    extra.write_text("not imported")
    with pytest.raises(ArtifactError):
        verify_snapshot(snapshot.path)
    extra.unlink()
    file = snapshot.path / "model.safetensors"
    file.unlink()
    outside = tmp_path / "outside"
    outside.write_bytes(b"weights")
    file.symlink_to(outside)
    with pytest.raises(ArtifactError, match="Symlinks"):
        verify_snapshot(snapshot.path)


def test_sharded_chronos_layout_requires_all_declared_shards(tmp_path):
    files = {
        "config.json": b'{"architectures":["Chronos2Model"]}',
        "model.safetensors.index.json": b'{"weight_map":{"layer1":"model-01.safetensors","layer2":"model-02.safetensors"}}',
        "model-01.safetensors": b"first",
        "model-02.safetensors": b"second",
    }
    _, snapshot = provision(tmp_path, files)
    assert adapters.validate_layout(snapshot, "forecasting")["engine"] == "forecasting"
    files.pop("model-02.safetensors")
    _, incomplete = provision(tmp_path, files, artifact_id="incomplete")
    with pytest.raises(ArtifactError, match="Every safetensors shard"):
        adapters.validate_layout(incomplete, "forecasting")


def test_custom_remote_code_and_unknown_modules_are_refused(tmp_path):
    config = {"architectures": ["BertModel"], "auto_map": {"AutoModel": "custom.Model"}}
    files = {"config.json": json.dumps(config).encode(), "model.safetensors": b"weights"}
    _, snapshot = provision(tmp_path, files)
    with pytest.raises(ArtifactError, match="custom remote code"):
        adapters.validate_layout(snapshot, "embedding")
    files["config.json"] = b'{"architectures":["BertModel"]}'
    files["modules.json"] = b'[{"type":"remote.Custom","path":""}]'
    _, snapshot = provision(tmp_path, files, artifact_id="modules")
    with pytest.raises(ArtifactError):
        adapters.validate_layout(snapshot, "embedding")


def test_missing_runtime_is_not_reported_as_compatible(monkeypatch):
    def missing(name):
        raise adapters.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(adapters.metadata, "version", missing)
    with pytest.raises(ArtifactError) as caught:
        adapters.runtime_versions("forecasting")
    assert caught.value.code == "HF_RUNTIME_MISSING"


def tiny_onnx_files():
    pytest.importorskip("onnx")
    from onnx import TensorProto, helper
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace

    # A real, deterministic network with the adapter's exact input/output ABI.
    # Equal mean token IDs produce equal logits; no external pretrained download.
    graph = helper.make_graph(
        [
            helper.make_node("Cast", ["input_ids"], ["ids"], to=TensorProto.FLOAT),
            helper.make_node("ReduceMean", ["ids"], ["logits"], axes=[1], keepdims=1),
        ],
        "tiny-reranker",
        [helper.make_tensor_value_info("input_ids", TensorProto.INT64, [None, None])],
        [helper.make_tensor_value_info("logits", TensorProto.FLOAT, [None, 1])],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 9
    tokenizer = Tokenizer(
        WordLevel({"[UNK]": 0, "[PAD]": 1, "activation": 2, "probe": 3}, unk_token="[UNK]")
    )
    tokenizer.pre_tokenizer = Whitespace()
    tokenizer.enable_padding(pad_id=1, pad_token="[PAD]")
    return {
        "config.json": b'{"architectures":["BertForSequenceClassification"],"num_labels":1}',
        "onnx/model.onnx": model.SerializeToString(),
        "tokenizer.json": tokenizer.to_str().encode(),
    }


def test_real_offline_onnx_activation_scores_and_rechecks_revocation(tmp_path, monkeypatch):
    files = tiny_onnx_files()
    cache, snapshot = provision(tmp_path, files, format="onnx")
    monkeypatch.setattr(adapters, "configured_cache", lambda: cache)
    revoked = False
    checks = []

    def authorize(workspace_id, artifact_id, **kwargs):
        checks.append((workspace_id, artifact_id))
        if revoked:
            raise ArtifactError("HF_GRANT_REVOKED", "Workspace grant revoked")
        return snapshot.manifest

    monkeypatch.setattr(adapters, "authorized_manifest", authorize)
    reranker = adapters.ArtifactReranker(workspace_id="workspace-a", artifact_id="artifact-one")
    scores = reranker.score("activation", ["probe", "other"])
    assert len(scores) == 2 and all(0 <= score <= 1 for score in scores)
    assert len(checks) == 2
    revoked = True
    with pytest.raises(ArtifactError, match="revoked"):
        reranker.score("query", ["passage"])
    reranker.close()


def test_real_onnx_probe_refuses_corrupt_weights(tmp_path, monkeypatch):
    files = tiny_onnx_files()
    files["onnx/model.onnx"] = b"not a graph"
    cache, snapshot = provision(tmp_path, files, format="onnx")
    monkeypatch.setattr(adapters, "configured_cache", lambda: cache)
    monkeypatch.setattr(adapters, "authorized_manifest", lambda *args, **kwargs: snapshot.manifest)
    # SHA verification alone is not activation: the real runtime must load it.
    with pytest.raises(ArtifactError) as caught:
        adapters.ArtifactReranker(workspace_id="workspace-a", artifact_id="artifact-one")
    assert caught.value.code == "HF_ADAPTER_LOAD_FAILED"


def tiny_sentence_transformer_files(tmp_path):
    pytest.importorskip("sentence_transformers")
    from sentence_transformers import SentenceTransformer, models
    from transformers import BertConfig, BertModel, BertTokenizerFast

    source = tmp_path / "source"
    source.mkdir()
    vocab = source / "vocab.txt"
    vocab.write_text("[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\nhello\nworld\nagentium\n")
    tokenizer = BertTokenizerFast(vocab_file=str(vocab))
    tokenizer.save_pretrained(source)
    BertModel(
        BertConfig(
            vocab_size=8,
            hidden_size=8,
            num_hidden_layers=1,
            num_attention_heads=2,
            intermediate_size=16,
        )
    ).save_pretrained(source, safe_serialization=True)
    transformer = models.Transformer(
        str(source),
        model_args={"local_files_only": True},
        tokenizer_args={"local_files_only": True},
    )
    model = SentenceTransformer(modules=[transformer, models.Pooling(8)])
    exported = tmp_path / "exported"
    model.save(str(exported), safe_serialization=True, create_model_card=False)
    files = {
        path.relative_to(exported).as_posix(): path.read_bytes()
        for path in exported.rglob("*")
        if path.is_file()
    }
    return files


def test_real_sentence_transformer_offline_probe_and_no_fallback(tmp_path, monkeypatch):
    pytest.importorskip("sentence_transformers")
    import socket

    import numpy as np

    from app.services.ml.local_models import resolve_artifact_model

    files = tiny_sentence_transformer_files(tmp_path)
    cache, snapshot = provision(tmp_path / "cache", files)
    monkeypatch.setattr(adapters, "configured_cache", lambda: cache)
    blocked = False

    def authorize(*args, **kwargs):
        if blocked:
            raise ArtifactError("HF_GRANT_REVOKED", "Workspace grant revoked")
        return snapshot.manifest

    monkeypatch.setattr(adapters, "authorized_manifest", authorize)
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *args, **kwargs: pytest.fail("model runtime attempted network access"),
    )
    embedder = adapters.ArtifactEmbedder(
        workspace_id="workspace-a",
        artifact_id="artifact-one",
        parameters={"normalize_embeddings": True},
        expected_dimension=8,
    )
    try:
        import asyncio

        vectors = asyncio.run(embedder.embed_batch(["hello world", "agentium"]))
        assert vectors.shape == (2, 8)
        assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)
        assert embedder.describe()["artifact_id"] == "artifact-one"
        local = resolve_artifact_model(
            "artifact-one", kind="embedding", cache_dir=cache.root, manifest=snapshot.manifest
        )
        assert local.public()["artifact_id"] == "artifact-one"
        assert local.runtime["sentence-transformers"]
        assert local.files.keys() == files.keys()
        blocked = True
        with pytest.raises(ArtifactError, match="revoked"):
            asyncio.run(embedder.embed_batch(["hello"]))
    finally:
        embedder.close()


def test_cache_purge_waits_for_lease(tmp_path):
    cache, snapshot = provision(tmp_path, {"model.safetensors": b"safe"})
    with cache.lease("artifact-one"):
        assert cache.remove("artifact-one") is False
        assert snapshot.path.exists()
    assert cache.remove("artifact-one") is True
    assert not snapshot.path.exists()
    assert (tmp_path / ".leases" / "artifact-one").exists()


def test_abandoned_staging_releases_admission_budget(tmp_path):
    cache = ArtifactCache(tmp_path, max_bytes=1000, min_free_bytes=0)
    abandoned = tmp_path / ".staging-dead"
    abandoned.mkdir()
    (abandoned / "large").write_bytes(b"a" * 5000)
    files = {"model.safetensors": b"safe"}
    cache.materialize(manifest_for(files), lambda name, entry: io.BytesIO(files[name]))
    assert not abandoned.exists()


def test_onnx_external_weights_cannot_escape_verified_snapshot(tmp_path, monkeypatch):
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper

    files = tiny_onnx_files()
    model = onnx.load_model_from_string(files["onnx/model.onnx"])
    tensor = helper.make_tensor("external", TensorProto.FLOAT, [1], [1.0])
    tensor.ClearField("float_data")
    tensor.data_location = TensorProto.EXTERNAL
    tensor.external_data.add(key="location", value="../../outside")
    model.graph.initializer.append(tensor)
    # External tensor participates in the output so it cannot be pruned.
    model.graph.node[-1].output[0] = "mean"
    model.graph.node.append(helper.make_node("Add", ["mean", "external"], ["logits"]))
    files["onnx/model.onnx"] = model.SerializeToString()
    cache, snapshot = provision(tmp_path, files, format="onnx")
    monkeypatch.setattr(adapters, "configured_cache", lambda: cache)
    monkeypatch.setattr(adapters, "authorized_manifest", lambda *args, **kwargs: snapshot.manifest)
    with pytest.raises(ArtifactError) as caught:
        adapters.ArtifactReranker(workspace_id="workspace-a", artifact_id="artifact-one")
    assert caught.value.code == "HF_ADAPTER_LOAD_FAILED"


def test_cache_lru_respects_active_usage_without_open_reader(tmp_path):
    files = {"model.safetensors": b"weights" * 100}
    cache = ArtifactCache(
        tmp_path,
        max_bytes=100_000,
        min_free_bytes=0,
        retained=lambda artifact_id: artifact_id == "artifact-2",
        last_used=lambda artifact_id: {"artifact-1": 30, "artifact-2": 10, "artifact-3": 20}[
            artifact_id
        ],
    )
    for name in ("artifact-1", "artifact-2", "artifact-3"):
        cache.materialize(
            manifest_for(files, artifact_id=name), lambda path, entry: io.BytesIO(files[path])
        )
    cache.max_bytes = cache._usage() + 5
    cache.materialize(
        manifest_for(files, artifact_id="artifact-4"), lambda path, entry: io.BytesIO(files[path])
    )
    # 2 was oldest but pinned by a collection; 3 is the oldest evictable entry.
    assert (tmp_path / "artifact-1").exists()
    assert (tmp_path / "artifact-2").exists()
    assert not (tmp_path / "artifact-3").exists()
    assert cache._usage() <= cache.max_bytes
