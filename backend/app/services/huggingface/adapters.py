"""Offline model adapters with explicit file, architecture and runtime contracts.

Hub metadata is only a compatibility hint. Activation loads the verified local
snapshot and exercises the actual runtime before exposing an embedding or score.
"""

from __future__ import annotations

import asyncio
import json
import weakref
from importlib import metadata
from pathlib import Path
from typing import Any

from app.services.huggingface.cache import ArtifactError, Snapshot, configured_cache, relative_name

# Deliberately bounded to architectures exercised by these adapters. Extending
# this matrix requires a load/inference recipe, not another repository allowlist.
ENCODERS = {"BertModel", "XLMRobertaModel", "RobertaModel", "DistilBertModel"}
CLASSIFIERS = {
    "BertForSequenceClassification",
    "XLMRobertaForSequenceClassification",
    "RobertaForSequenceClassification",
    "DistilBertForSequenceClassification",
}
MODULES = {
    "sentence_transformers.models.Transformer",
    "sentence_transformers.models.Pooling",
    "sentence_transformers.models.Normalize",
    "sentence_transformers.base.modules.transformer.Transformer",
    "sentence_transformers.sentence_transformer.modules.pooling.Pooling",
    "sentence_transformers.sentence_transformer.modules.normalize.Normalize",
}
REQUIREMENTS = {
    "embedding": {
        "sentence-transformers": ("3.0", "7"),
        "transformers": ("4.41", "6"),
        "torch": ("2.1", "3"),
    },
    "forecasting": {
        "chronos-forecasting": ("2.0", "3"),
        "transformers": ("4.41", "6"),
        "torch": ("2.1", "3"),
    },
    "reranker_onnx": {"onnxruntime": ("1.20", "2"), "tokenizers": ("0.20", "1")},
    "reranker_torch": {"transformers": ("4.41", "6"), "torch": ("2.1", "3")},
}


def _invalid(message: str) -> None:
    raise ArtifactError("HF_ADAPTER_INCOMPATIBLE", message)


def _json(snapshot: Snapshot, name: str):
    if name not in snapshot.manifest["files"]:
        _invalid(f"The adapter requires {name}.")
    path = snapshot.path / name
    if path.stat().st_size > 8 * 1024 * 1024:
        _invalid(f"Model configuration is too large: {name}.")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise ArtifactError(
            "HF_ADAPTER_INCOMPATIBLE", f"Invalid model configuration: {name}."
        ) from exc


def _weights(snapshot: Snapshot, prefix: str = "") -> None:
    files = snapshot.manifest["files"]
    if f"{prefix}model.safetensors" in files:
        return
    index = _json(snapshot, f"{prefix}model.safetensors.index.json")
    weights = index.get("weight_map") if isinstance(index, dict) else None
    if not isinstance(weights, dict) or not weights:
        _invalid("A sharded model must declare a nonempty weight_map.")
    if not all(isinstance(name, str) for name in weights.values()):
        _invalid("Safetensors shard paths must be strings.")
    for name in set(weights.values()):
        relative_name(name)
        if not name.endswith(".safetensors") or f"{prefix}{name}" not in files:
            _invalid("Every safetensors shard must be present in the artifact selection.")


def validate_layout(snapshot: Snapshot, usage: str) -> dict[str, Any]:
    files = snapshot.manifest["files"]
    for name in files:
        if Path(name).suffix.lower() in {".py", ".bin", ".pt", ".pth", ".pkl", ".ckpt"}:
            _invalid("Executable and pickle model files are not supported.")
        if name.endswith(".json") and "config" in Path(name).name:
            config = _json(snapshot, name)
            if isinstance(config, dict) and (
                config.get("auto_map") or config.get("trust_remote_code")
            ):
                _invalid("Models requiring custom remote code are not supported.")
    config = _json(snapshot, "config.json")
    if not isinstance(config, dict):
        _invalid("config.json must be an object.")
    architectures = config.get("architectures")
    if (
        not isinstance(architectures, list)
        or not architectures
        or not all(isinstance(a, str) for a in architectures)
    ):
        _invalid("The architecture must be explicitly declared.")
    if usage == "forecasting":
        if (
            set(architectures) != {"Chronos2Model"}
            or snapshot.manifest.get("format") != "safetensors"
        ):
            _invalid("Forecasting supports Chronos2Model safetensors only.")
        _weights(snapshot)
        engine = "forecasting"
    elif usage == "embedding":
        if not set(architectures) <= ENCODERS or snapshot.manifest.get("format") != "safetensors":
            _invalid("This sentence-transformer architecture or format is not supported.")
        _weights(snapshot)
        modules = _json(snapshot, "modules.json")
        if not isinstance(modules, list) or not modules:
            _invalid("A sentence-transformer requires its module inventory.")
        if not all(isinstance(module, dict) for module in modules):
            _invalid("Sentence-transformer modules must be objects.")
        if modules[0].get("type") not in {
            name for name in MODULES if name.endswith(".Transformer")
        } or modules[0].get("path") not in ("", "."):
            _invalid("The sentence-transformer must use root transformer weights.")
        for module in modules:
            if not isinstance(module, dict) or module.get("type") not in MODULES:
                _invalid("Custom sentence-transformer modules are not supported.")
            if module["type"].endswith("Pooling"):
                prefix = relative_name(module.get("path"))
                _json(snapshot, f"{prefix}/config.json")
        if not any(m["type"].endswith("Pooling") for m in modules):
            _invalid("A pooling module is required for sentence embeddings.")
        if "tokenizer.json" not in files and not (
            {"vocab.txt", "tokenizer_config.json"} <= files.keys()
        ):
            _invalid("Tokenizer files are required.")
        engine = "embedding"
    elif usage == "reranker":
        if (
            not set(architectures) <= CLASSIFIERS
            or int(config.get("num_labels", len(config.get("id2label", {})) or 1)) != 1
        ):
            _invalid("Reranking requires a recognized classifier with exactly one logit.")
        if "tokenizer.json" not in files:
            _invalid("The reranker requires tokenizer.json.")
        if snapshot.manifest.get("format") == "onnx":
            if "onnx/model.onnx" not in files:
                _invalid("The ONNX adapter requires onnx/model.onnx.")
            engine = "reranker_onnx"
        elif snapshot.manifest.get("format") == "safetensors":
            _weights(snapshot)
            engine = "reranker_torch"
        else:
            _invalid("Reranking supports ONNX or safetensors only.")
    else:
        _invalid("Unsupported adapter usage.")
    return {"usage": usage, "engine": engine, "architectures": architectures}


def runtime_versions(engine: str) -> dict[str, str]:
    from packaging.version import Version

    result = {}
    for package, (minimum, maximum) in REQUIREMENTS[engine].items():
        try:
            installed = metadata.version(package)
        except metadata.PackageNotFoundError as exc:
            raise ArtifactError("HF_RUNTIME_MISSING", f"The adapter requires {package}.") from exc
        if not Version(minimum) <= Version(installed) < Version(maximum):
            raise ArtifactError(
                "HF_RUNTIME_INCOMPATIBLE",
                f"{package} must be >= {minimum}, < {maximum}; found {installed}.",
            )
        result[package] = installed
    return result


def authorized_manifest(
    workspace_id: str, artifact_id: str, *, usage: str | None = None, db=None
) -> dict:
    from app.services.huggingface.registry import require_artifact

    if db is not None:
        return dict(require_artifact(db, workspace_id, artifact_id, usage=usage).manifest_json)
    from app.db.base import SessionLocal

    with SessionLocal() as session:
        manifest = dict(
            require_artifact(session, workspace_id, artifact_id, usage=usage).manifest_json
        )
        session.commit()  # This session owns only the access timestamp.
        return manifest


def _parameters(parameters: dict | None) -> dict:
    values = dict(parameters or {})
    if set(values) - {"normalize_embeddings", "batch_size"}:
        _invalid("Unsupported embedding parameters.")
    normalize = values.get("normalize_embeddings", False)
    batch = values.get("batch_size", 32)
    if (
        not isinstance(normalize, bool)
        or isinstance(batch, bool)
        or not isinstance(batch, int)
        or not 1 <= batch <= 256
    ):
        _invalid("Embedding normalization must be boolean and batch size between 1 and 256.")
    return {"normalize_embeddings": normalize, "batch_size": batch}


class ArtifactEmbedder:
    """A workspace-authorized sentence-transformer held under a cache lease."""

    provider = "huggingface_local"

    def __init__(
        self,
        *,
        workspace_id: str,
        artifact_id: str,
        parameters: dict | None = None,
        db=None,
        expected_dimension: int | None = None,
    ):
        import numpy as np

        self.workspace_id = workspace_id
        self.artifact_id = artifact_id
        self.model_name = artifact_id
        self.parameters = _parameters(parameters)
        manifest = authorized_manifest(workspace_id, artifact_id, usage="embedding", db=db)
        self._lease = configured_cache().lease(artifact_id, manifest)
        self.snapshot = self._lease.__enter__()
        self._finalizer = weakref.finalize(self, self._lease.__exit__, None, None, None)
        try:
            contract = validate_layout(self.snapshot, "embedding")
            self.runtime = runtime_versions(contract["engine"])
            from sentence_transformers import SentenceTransformer

            self.model = SentenceTransformer(
                str(self.snapshot.path),
                local_files_only=True,
                trust_remote_code=False,
                device="cpu",
                model_kwargs={"use_safetensors": True},
            )
            self._dimension = int(self.model.get_sentence_embedding_dimension())
            probe = self._encode(["Agentium embedding activation probe."])
            if (
                self._dimension <= 0
                or probe.shape != (1, self._dimension)
                or not np.isfinite(probe).all()
            ):
                _invalid("The embedding load/inference probe returned an invalid vector.")
            if expected_dimension is not None and self._dimension != expected_dimension:
                _invalid("The artifact's dimension differs from the active index generation.")
        except Exception as exc:
            self.close()
            if isinstance(exc, ArtifactError):
                raise
            raise ArtifactError(
                "HF_ADAPTER_LOAD_FAILED",
                "The selected model failed its offline load/inference probe.",
            ) from exc

    def close(self) -> None:
        self._finalizer()

    def _authorize(self) -> None:
        if not self._finalizer.alive:
            raise ArtifactError("HF_CACHE_MISSING", "The runtime lease has been released.")
        manifest = authorized_manifest(self.workspace_id, self.artifact_id, usage="embedding")
        if manifest != self.snapshot.manifest:
            raise ArtifactError(
                "HF_MANIFEST_INVALID", "The artifact manifest changed after activation."
            )

    def _encode(self, texts):
        import numpy as np

        return np.asarray(
            self.model.encode(
                texts, convert_to_numpy=True, show_progress_bar=False, **self.parameters
            ),
            dtype=np.float32,
        )

    async def embed_batch(self, texts: list[str]):
        import numpy as np

        self._authorize()
        if not texts:
            return np.empty((0, self._dimension), dtype=np.float32)
        try:
            vectors = await asyncio.to_thread(self._encode, texts)
        except Exception as exc:
            raise ArtifactError(
                "HF_ADAPTER_INFERENCE_FAILED",
                "The selected embedding model failed to produce vectors.",
            ) from exc
        if vectors.shape != (len(texts), self._dimension) or not np.isfinite(vectors).all():
            _invalid("Embedding inference returned an invalid vector batch.")
        return vectors

    async def embed(self, text: str):
        return (await self.embed_batch([text]))[0]

    embed_texts = embed_batch
    embed_query = embed

    def get_dimension(self) -> int:
        return self._dimension

    def is_degraded(self) -> bool:
        return False

    def describe(self) -> dict:
        return {
            "provider": self.provider,
            "model_name": self.model_name,
            "artifact_id": self.artifact_id,
            "revision": self.snapshot.manifest["revision"],
            "fingerprint": self.snapshot.fingerprint,
            "dimension": self._dimension,
            "parameters": dict(self.parameters),
            "runtime": dict(self.runtime),
            "degraded": False,
        }


class ArtifactReranker:
    """No implicit fallback: every score is produced by the selected artifact."""

    def __init__(self, *, workspace_id: str, artifact_id: str, config=None, db=None):
        import numpy as np

        from app.services.retrieval.reranker_config import RerankerConfig

        self.workspace_id, self.artifact_id = workspace_id, artifact_id
        self.config = config or RerankerConfig()
        manifest = authorized_manifest(workspace_id, artifact_id, usage="reranker", db=db)
        self._lease = configured_cache().lease(artifact_id, manifest)
        self.snapshot = self._lease.__enter__()
        self._finalizer = weakref.finalize(self, self._lease.__exit__, None, None, None)
        try:
            contract = validate_layout(self.snapshot, "reranker")
            self.runtime = runtime_versions(contract["engine"])
            self.engine = contract["engine"]
            if self.engine == "reranker_onnx":
                from dataclasses import replace

                from app.services.retrieval.onnx_reranker import OnnxReranker

                # Loading bytes gives ONNX Runtime no filesystem origin. Graphs
                # with external_data (including paths outside the selection)
                # fail before activation; only self-contained ONNX is supported.
                self.model = OnnxReranker(
                    replace(self.config, model_name=artifact_id),
                    models_dir=self.snapshot.path.parent,
                    model_bytes=(self.snapshot.path / "onnx/model.onnx").read_bytes(),
                )
                outputs = self.model.session.get_outputs()
                if (
                    len(outputs) != 1
                    or outputs[0].name != "logits"
                    or len(outputs[0].shape) != 2
                    or outputs[0].shape[-1] != 1
                ):
                    _invalid("The ONNX adapter requires one scalar logits output per pair.")
            else:
                from transformers import AutoModelForSequenceClassification, AutoTokenizer

                self.model = AutoModelForSequenceClassification.from_pretrained(
                    str(self.snapshot.path),
                    local_files_only=True,
                    trust_remote_code=False,
                    use_safetensors=True,
                ).eval()
                self.tokenizer = AutoTokenizer.from_pretrained(
                    str(self.snapshot.path), local_files_only=True, trust_remote_code=False
                )
            result = self._score("activation probe", ["A candidate passage."])
            if len(result) != 1 or not np.isfinite(result).all():
                _invalid("The reranker load/inference probe failed.")
        except Exception as exc:
            self.close()
            if isinstance(exc, ArtifactError):
                raise
            raise ArtifactError(
                "HF_ADAPTER_LOAD_FAILED",
                "The selected model failed its offline load/inference probe.",
            ) from exc

    def close(self):
        self._finalizer()

    def _score(self, query: str, passages: list[str]) -> list[float]:
        if self.engine == "reranker_onnx":
            # _batch_scores propagates failures; the legacy score() path fills
            # zeros on errors and therefore cannot validate artifact activation.
            return self.model._batch_scores(query, passages)
        import torch

        inputs = self.tokenizer(
            [(query, text) for text in passages],
            padding=True,
            truncation=True,
            max_length=self.config.max_length,
            return_tensors="pt",
        )
        with torch.inference_mode():
            logits = self.model(**inputs).logits
            if tuple(logits.shape) != (len(passages), 1):
                _invalid("The reranker must produce one logit per pair.")
            return torch.sigmoid(logits[:, 0]).cpu().tolist()

    def score(self, query: str, passages: list[str]) -> list[float]:
        import numpy as np

        if not self._finalizer.alive:
            raise ArtifactError("HF_CACHE_MISSING", "The runtime lease has been released.")
        authorized_manifest(self.workspace_id, self.artifact_id, usage="reranker")
        result = []
        for start in range(0, len(passages), max(1, int(self.config.batch_size))):
            result.extend(
                self._score(query, passages[start : start + max(1, int(self.config.batch_size))])
            )
        if not np.isfinite(result).all():
            _invalid("The reranker returned nonfinite scores.")
        return result

    def rerank(self, query, passages, return_scores=False):
        ranked = sorted(
            zip(passages, self.score(query, passages)), key=lambda item: item[1], reverse=True
        )
        kept = [item for item in ranked if item[1] >= self.config.threshold] or ranked
        texts, scores = [item[0] for item in kept], [item[1] for item in kept]
        return (texts, scores) if return_scores else texts

    __call__ = rerank


def require_model_foundation(model, db=None) -> None:
    """Derived ML exports and explicitly migrated v1 exports retain grant checks."""
    foundation = (getattr(model, "params_json", None) or {}).get("foundation") or {}
    artifact_id = foundation.get("artifact_id")
    if not artifact_id and foundation.get("model_id"):
        from app.services.huggingface.legacy_migration import migration_for

        if db is None:
            from app.db.base import SessionLocal

            with SessionLocal() as session:
                migration = migration_for(session, model)
                artifact_id = migration.artifact_id if migration else None
        else:
            migration = migration_for(db, model)
            artifact_id = migration.artifact_id if migration else None
    if artifact_id:
        from app.services.tabular_datasets import TabularError

        try:
            authorized_manifest(
                model.workspace_id,
                artifact_id,
                usage="forecasting" if model.family == "forecasting_deep" else "embedding",
                db=db,
            )
        except ValueError as exc:
            raise TabularError(
                code=getattr(exc, "code", "HF_ARTIFACT_UNAVAILABLE"),
                message=str(exc),
                status_code=409,
            ) from exc


def validate_local_artifact(workspace_id: str, artifact_id: str, usage: str, *, db=None) -> dict:
    """Run on a runtime worker after cache preparation; reports actual execution.

    This validation is never performed by a Hub download worker lacking the ML
    stack. The report can be stored on an artifact usage, not its immutable
    provenance manifest, and activation must keep the workspace authorization.
    """
    if usage == "embedding":
        model = ArtifactEmbedder(workspace_id=workspace_id, artifact_id=artifact_id, db=db)
        try:
            return {**model.describe(), "validation": "loaded_and_inferred", "usage": usage}
        finally:
            model.close()
    if usage == "reranker":
        model = ArtifactReranker(workspace_id=workspace_id, artifact_id=artifact_id, db=db)
        try:
            return {
                "artifact_id": artifact_id,
                "usage": usage,
                "validation": "loaded_and_inferred",
                "runtime": model.runtime,
                "engine": model.engine,
                "fingerprint": model.snapshot.fingerprint,
            }
        finally:
            model.close()
    if usage != "forecasting":
        _invalid("Unsupported adapter usage.")
    manifest = authorized_manifest(workspace_id, artifact_id, usage=usage, db=db)
    with configured_cache().lease(artifact_id, manifest) as snapshot:
        contract = validate_layout(snapshot, usage)
        runtime = runtime_versions(contract["engine"])
        try:
            import numpy as np
            import pandas as pd

            from app.resources.ml_foundation_pyfunc import build_forecaster

            forecaster = build_forecaster(snapshot.path)
            index = pd.date_range("2000-01-01", periods=64, freq="D")
            forecaster.fit(series={"probe": pd.Series(np.arange(64, dtype=float), index=index)})
            predicted = forecaster.predict_interval(steps=1, interval=[0.1, 0.9])
            if (
                len(predicted) != 1
                or not np.isfinite(
                    predicted[["pred", "lower_bound", "upper_bound"]].to_numpy()
                ).all()
            ):
                _invalid("The forecasting probe returned invalid predictions.")
        except ArtifactError:
            raise
        except Exception as exc:
            raise ArtifactError(
                "HF_ADAPTER_LOAD_FAILED",
                "The forecast model failed its offline load/inference probe.",
            ) from exc
        return {
            "artifact_id": artifact_id,
            "usage": usage,
            "validation": "loaded_and_inferred",
            "runtime": runtime,
            "fingerprint": snapshot.fingerprint,
        }
