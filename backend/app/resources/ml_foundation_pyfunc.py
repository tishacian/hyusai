"""Portable foundation forecast: JSON context plus bundled safetensors weights.

No application imports, hub downloads, pickle, training or custom remote code.
MLflow exports carry the exact model snapshot used for their backtest.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import mlflow.pyfunc
import pandas as pd
from mlflow.models import set_model


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_forecaster(model_path, *, context_length=512):
    # Both the path and offline flags are deliberate: a cache miss must never
    # turn an inference request into a network download.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import torch
    from chronos import BaseChronosPipeline
    from skforecast.foundation import ForecasterFoundation, FoundationModel

    torch.set_num_threads(max(1, min(4, int(os.environ.get("OMP_NUM_THREADS", "2")))))
    forecaster = ForecasterFoundation(FoundationModel(
        "autogluon/chronos-2-small", context_length=context_length, device_map="cpu",
    ))
    # ForecasterFoundation clones its estimator and discards a constructor's
    # preloaded pipeline. Attach the locally loaded pipeline AFTER this clone.
    forecaster.estimator.adapter._pipeline = BaseChronosPipeline.from_pretrained(
        str(model_path), local_files_only=True, device_map="cpu", torch_dtype=torch.float32,
    )
    return forecaster


class AgentiumFoundationForecaster(mlflow.pyfunc.PythonModel):
    def load_context(self, context):
        self.meta = json.loads(Path(context.artifacts["meta"]).read_text())
        snapshot = Path(context.artifacts["foundation"])
        for name, expected in self.meta["foundation"]["files"].items():
            path = snapshot / name
            if not path.is_file() or not path.resolve().is_relative_to(snapshot.resolve()) or sha256(path) != expected:
                raise ValueError("The bundled foundation model failed its fingerprint check.")
        stored = json.loads(Path(context.artifacts["forecaster"]).read_text())
        series = {}
        for name, rows in stored["series"].items():
            index = pd.DatetimeIndex(rows["timestamps"], freq=self.meta["frequency"])
            series[name] = pd.Series(rows["values"], index=index, name=name, dtype=float)
        self.forecaster = build_forecaster(snapshot, context_length=self.meta["context_length"])
        self.forecaster.fit(series=series)

    def predict(self, context, model_input, params=None):
        params = params or {}
        raw_horizon = params.get("horizon", self.meta["horizon"])
        if isinstance(raw_horizon, bool) or int(raw_horizon) != raw_horizon:
            raise ValueError("horizon must be a whole number")
        horizon = int(raw_horizon)
        if not 1 <= horizon <= self.meta["max_steps"]:
            raise ValueError(f"horizon must be between 1 and {self.meta['max_steps']}")
        level = float(params.get("interval_level", self.meta["interval_level"]))
        if not 0.5 <= level <= 0.98:
            raise ValueError("interval_level must be between 0.5 and 0.98")
        levels = list(self.meta["levels"])
        if model_input is not None and not model_input.empty:
            if "series" not in model_input:
                raise ValueError("Only a series selection is supported; this model takes no covariates.")
            requested = [str(value) for value in model_input["series"].dropna().unique()]
            if set(requested) - set(levels):
                raise ValueError("The request selects a series absent from this model.")
            levels = requested or levels
        frame = self.forecaster.predict_interval(
            steps=horizon, levels=levels, interval=[(1 - level) / 2, (1 + level) / 2],
        )
        frame = frame.rename_axis("timestamp").reset_index().rename(columns={"level": "series"})
        frame["timestamp"] = frame["timestamp"].astype(str)
        return frame[["series", "timestamp", "pred", "lower_bound", "upper_bound"]]


set_model(AgentiumFoundationForecaster())
