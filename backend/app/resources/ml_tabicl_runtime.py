"""Pinned TabICL adapter: safe tensors and declarative context, never estimator pickle.

The private loader override is qualified against exactly TabICL 2.2.0. Provisioning
is separate from serving; this module has no network acquisition path.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from importlib.metadata import version
from pathlib import Path

TABICL_VERSION = "2.2.0"
REVISION = "4dcd344ece2c00be9e831fdd35bed57b5ad83e19"
CHECKPOINTS = {
    "classification": (
        "tabicl-classifier-v2-20260212.ckpt",
        "bdc7dbd5e4ff21f8f0456fcf90c6b7cdf72dbea960f2d05b19bec19f9b3d4ed0",
    ),
    "regression": (
        "tabicl-regressor-v2-20260212.ckpt",
        "0db9cb538f114e79026bf08f45f41ad8dd7ad2de2aaca9a5ca8cd3bd9748ae7a",
    ),
}
CONFIG = {
    "activation": "gelu",
    "bias_free_ln": False,
    "col_affine": False,
    "col_feature_group": "same",
    "col_feature_group_size": 3,
    "col_nhead": 8,
    "col_num_blocks": 3,
    "col_num_inds": 128,
    "col_ssmax": "qassmax-mlp-elementwise",
    "col_target_aware": True,
    "dropout": 0.0,
    "embed_dim": 128,
    "ff_factor": 2,
    "icl_nhead": 8,
    "icl_num_blocks": 12,
    "icl_ssmax": "qassmax-mlp-elementwise",
    "max_classes": 10,
    "norm_first": True,
    "num_quantiles": 999,
    "recompute": False,
    "row_nhead": 8,
    "row_num_blocks": 3,
    "row_num_cls": 4,
    "row_rope_base": 100000,
    "row_rope_interleaved": False,
}
MAX_ROWS = 10_000
MAX_FEATURES = 100
MAX_CONTEXT_BYTES = 64 * 1024 * 1024
MAX_WEIGHT_BYTES = 128 * 1024 * 1024


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_config(task):
    if task not in CHECKPOINTS:
        raise ValueError("Unsupported TabICL task")
    return {**CONFIG, **({"bias_free_ln": True, "max_classes": 0} if task == "regression" else {})}


def read_json(path, limit=MAX_CONTEXT_BYTES):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("TabICL JSON file missing or exceeds its limit")
    return json.loads(
        path.read_text(), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value))
    )


def validate_weights(directory, task=None):
    root = Path(directory)
    metadata = read_json(root / "config.json", 64 * 1024)
    task = task or metadata.get("task")
    if (
        metadata.get("schema") != 1
        or metadata.get("tabicl") != TABICL_VERSION
        or metadata.get("architectures") != ["HyusaiTabICLv2"]
        or metadata.get("task") != task
        or metadata.get("config") != expected_config(task)
        or metadata.get("revision") != REVISION
        or metadata.get("source_sha256") != CHECKPOINTS[task][1]
    ):
        raise ValueError("Unqualified TabICL checkpoint configuration")
    weights = root / "model.safetensors"
    if (
        weights.is_symlink()
        or not weights.is_file()
        or weights.stat().st_size > MAX_WEIGHT_BYTES
        or sha256(weights) != metadata.get("weights_sha256")
    ):
        raise ValueError("TabICL weight integrity check failed")
    return metadata


def convert_checkpoint(source, destination, *, task):
    """Explicit offline conversion of the exact audited official tensor checkpoint."""
    import torch
    from safetensors.torch import save_file

    source, destination = Path(source), Path(destination)
    if (
        source.is_symlink()
        or source.stat().st_size > MAX_WEIGHT_BYTES
        or sha256(source) != CHECKPOINTS[task][1]
    ):
        raise ValueError("Checkpoint differs from the pinned official weights")
    checkpoint = torch.load(source, map_location="cpu", weights_only=True)
    if set(checkpoint) != {"state_dict", "config"} or checkpoint["config"] != expected_config(task):
        raise ValueError("Checkpoint configuration is not qualified")
    state = checkpoint["state_dict"]
    if (
        not isinstance(state, dict)
        or len(state) > 500
        or any(not isinstance(value, torch.Tensor) for value in state.values())
    ):
        raise ValueError("Checkpoint must contain only tensors")
    destination.mkdir(parents=True, exist_ok=False)
    save_file(
        {name: value.contiguous() for name, value in state.items()},
        destination / "model.safetensors",
    )
    metadata = {
        "schema": 1,
        "architectures": ["HyusaiTabICLv2"],
        "tabicl": TABICL_VERSION,
        "task": task,
        "config": checkpoint["config"],
        "revision": REVISION,
        "source_sha256": CHECKPOINTS[task][1],
        "weights_sha256": sha256(destination / "model.safetensors"),
    }
    (destination / "config.json").write_text(json.dumps(metadata, sort_keys=True, allow_nan=False))
    return metadata


def execution_threads(requested):
    """A stored profile cannot exceed the current worker CPU envelope."""
    try:
        ceiling = max(1, int(os.environ.get("OMP_NUM_THREADS", "1")))
    except ValueError as exc:
        raise ValueError("OMP_NUM_THREADS must be an integer") from exc
    return min(requested, ceiling, 4)


def build_estimator(task, weights_dir, *, n_estimators=1, seed=42, n_jobs=4, kv_cache=False):
    """Return an unfitted CPU estimator; only two bounded pilot profiles are allowed."""
    if version("tabicl") != TABICL_VERSION:
        raise ValueError("TabICL runtime must be exactly 2.2.0")
    if n_estimators != 1 or type(kv_cache) is not bool or not 1 <= n_jobs <= 4:
        raise ValueError("Unqualified TabICL pilot profile")
    n_jobs = execution_threads(n_jobs)
    metadata = validate_weights(weights_dir, task)
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    import torch
    from safetensors.torch import load_file
    from tabicl import TabICLClassifier, TabICLRegressor
    from tabicl._model.tabicl import TabICL

    torch.set_num_threads(n_jobs)
    base = TabICLClassifier if task == "classification" else TabICLRegressor

    class OfflineEstimator(base):
        def _load_model(self):
            validate_weights(self.model_path, task)
            self.model_path_ = Path(self.model_path)
            self.model_config_ = metadata["config"]
            self.model_ = TabICL(**self.model_config_)
            self.model_.load_state_dict(
                load_file(str(self.model_path_ / "model.safetensors"), device="cpu"), strict=True
            )
            self.model_.eval()

    estimator = OfflineEstimator(
        n_estimators=1,
        model_path=str(Path(weights_dir).resolve()),
        allow_auto_download=False,
        device="cpu",
        kv_cache=kv_cache,
        random_state=seed,
        n_jobs=n_jobs,
        batch_size=1,
        use_amp=False,
        use_fa3=False,
        offload_mode=False,
        checkpoint_version=CHECKPOINTS[task][0],
    )
    return estimator


def normalize_frame(frame):
    """Stable, train-independent scalar normalization for numeric/categorical inputs."""
    import numpy as np
    import pandas as pd

    frame = pd.DataFrame(frame).copy()
    if not 1 <= len(frame.columns) <= MAX_FEATURES or len(frame) > MAX_ROWS:
        raise ValueError("TabICL pilot supports at most 100 features and 10000 rows")
    if any(not isinstance(name, str) for name in frame.columns) or frame.columns.duplicated().any():
        raise ValueError("TabICL feature names must be unique strings")
    for name in frame:
        if pd.api.types.is_numeric_dtype(frame[name]):
            frame[name] = pd.to_numeric(frame[name], errors="raise").astype(float)
            if np.isinf(frame[name].to_numpy()).any():
                raise ValueError("TabICL numeric inputs must not contain infinity")
        else:
            if pd.api.types.is_datetime64_any_dtype(frame[name]):
                raise ValueError("TabICL pilot accepts numeric and categorical columns only")
            frame[name] = (
                frame[name].map(lambda item: None if pd.isna(item) else str(item)).astype(object)
            )
    return frame


def export_state(estimator, X_train, y_train, directory, *, foundation=None):
    import pandas as pd

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    X_train = normalize_frame(X_train)
    if len(X_train) != len(y_train) or len(X_train) < 2:
        raise ValueError("Invalid TabICL context dimensions")
    task = "classification" if hasattr(estimator, "classes_") else "regression"
    # Store raw bounded context, not internal sklearn objects or a tensor cache.
    frame = X_train.astype(object).where(pd.notna(X_train), None)
    state = {
        "schema": 1,
        "serialization": "json+safetensors",
        "task": task,
        "features": list(X_train.columns),
        "numeric": [name for name in X_train if pd.api.types.is_numeric_dtype(X_train[name])],
        "rows": frame.values.tolist(),
        "target": pd.Series(y_train).tolist(),
        "classes": estimator.classes_.tolist() if task == "classification" else [],
        "parameters": {
            "n_estimators": 1,
            "seed": estimator.random_state,
            "n_jobs": estimator.n_jobs,
            "kv_cache": estimator.kv_cache,
        },
        "foundation": dict(foundation or {}),
        "versions": {
            name: version(name)
            for name in ("tabicl", "torch", "numpy", "pandas", "scikit-learn", "safetensors")
        },
    }
    encoded = json.dumps(state, allow_nan=False, separators=(",", ":"))
    if len(encoded.encode()) > MAX_CONTEXT_BYTES:
        raise ValueError("TabICL context exceeds its byte ceiling")
    (directory / "context.json").write_text(encoded)
    shutil.copytree(estimator.model_path, directory / "foundation")
    validate_weights(directory / "foundation", task)
    return {
        "context_sha256": sha256(directory / "context.json"),
        "rows": len(X_train),
        "sensitive_context": True,
    }


class ReloadedEstimator:
    def __init__(self, estimator, features, numeric):
        self.estimator = estimator
        self.feature_names_in_ = features
        self.numeric = numeric
        if hasattr(estimator, "classes_"):
            self.classes_ = estimator.classes_

    def _frame(self, rows):
        frame = normalize_frame(rows)
        if set(frame.columns) != set(self.feature_names_in_):
            raise ValueError("TabICL features differ from the trained context")
        return frame[self.feature_names_in_]

    def predict(self, rows):
        return self.estimator.predict(self._frame(rows))

    def predict_proba(self, rows):
        return self.estimator.predict_proba(self._frame(rows))


def load_state(directory):
    import pandas as pd

    root = Path(directory)
    state = read_json(root / "context.json")
    if state.get("schema") != 1 or state.get("serialization") != "json+safetensors":
        raise ValueError("Unsupported TabICL context")
    if state.get("versions") != {
        name: version(name)
        for name in ("tabicl", "torch", "numpy", "pandas", "scikit-learn", "safetensors")
    }:
        raise ValueError("TabICL context runtime versions are not qualified")
    rows, features, target = state["rows"], state["features"], state["target"]
    if (
        not 2 <= len(rows) <= MAX_ROWS
        or len(target) != len(rows)
        or not 1 <= len(features) <= MAX_FEATURES
    ):
        raise ValueError("Invalid TabICL context dimensions")
    frame = pd.DataFrame(rows, columns=features)
    for name in state["numeric"]:
        frame[name] = pd.to_numeric(frame[name], errors="raise").astype(float)
    estimator = build_estimator(state["task"], root / "foundation", **state["parameters"])
    estimator.fit(normalize_frame(frame), target)
    if state["task"] == "classification" and estimator.classes_.tolist() != state["classes"]:
        raise ValueError("TabICL class order differs after reconstruction")
    return ReloadedEstimator(estimator, features, state["numeric"])
