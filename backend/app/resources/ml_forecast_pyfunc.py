"""The MLflow model a forecast is saved as ("models from code").

This file is copied into every forecasting model directory and runs when the
model is loaded, so it imports nothing from the application: a model must be
loadable by ``mlflow.pyfunc.load_model`` in any environment that has
skforecast. Its sha256 is recorded at training time and checked before load.

``predict(model_input, params)``:

* ``params`` — ``horizon`` (steps ahead, at most the one the model was built
  for when its strategy is direct) and ``interval_level`` (0.5–0.99);
* ``model_input`` — one row per future step for the covariates known in the
  future (``timestamp``, optionally ``series``, then one column per
  covariate), or no rows when the model has none. A ``series`` column on its
  own selects which series of a panel to forecast.

It answers in long form: ``series``, ``timestamp``, ``pred``, ``lower_bound``,
``upper_bound``.
"""

from __future__ import annotations

import json

import mlflow.pyfunc
import pandas as pd
from mlflow.models import set_model


class AgentiumForecaster(mlflow.pyfunc.PythonModel):
    def load_context(self, context):
        from skforecast.utils import load_forecaster

        self.meta = json.loads(open(context.artifacts["meta"], encoding="utf-8").read())
        backend = self.meta["serialization"]
        kwargs = {"trusted": self.meta.get("trusted") or []} if backend == "skops" else {}
        self.forecaster = load_forecaster(context.artifacts["forecaster"], backend=backend, verbose=False, **kwargs)

    def _future_index(self, horizon: int) -> pd.DatetimeIndex:
        last = pd.Timestamp(self.meta["last_timestamp"])
        offset = pd.tseries.frequencies.to_offset(self.meta["frequency"])
        return pd.date_range(last + offset, periods=horizon, freq=offset)

    def _exog(self, model_input: pd.DataFrame, horizon: int, levels: list[str]):
        future = list(self.meta.get("exog_future") or [])
        static = list(self.meta.get("exog_static") or [])
        if not future and not static:
            return None
        index = self._future_index(horizon)
        frame = None
        if future:
            if model_input is None or model_input.empty or "timestamp" not in model_input:
                raise ValueError(f"this model needs future values of {future} for each of the {horizon} steps")
            frame = model_input.copy()
            frame["timestamp"] = pd.to_datetime(frame["timestamp"])

        def rows_for(level: str | None) -> pd.DataFrame:
            if frame is None:
                block = pd.DataFrame(index=index)
            else:
                rows = frame[frame["series"].astype(str) == level] if level is not None and "series" in frame else frame
                block = rows.set_index("timestamp").reindex(index)[future].astype(float)
                missing = int(block.isna().any(axis=1).sum())
                if missing:
                    where = f" for series '{level}'" if level is not None else ""
                    raise ValueError(f"{missing} of the {horizon} steps lack a value of {future}{where}")
            # A static covariate is the series' own attribute: the model knows it.
            for column in static:
                block[column] = (self.meta.get("static_values") or {}).get(level, {}).get(column)
            return block.astype(float)

        if self.meta["shape"] == "panel":
            return {level: rows_for(level) for level in levels}
        return rows_for(None)

    def predict(self, context, model_input: pd.DataFrame, params=None):
        params = params or {}
        horizon = int(params.get("horizon") or self.meta["horizon"])
        if horizon < 1:
            raise ValueError("horizon must be at least 1")
        if self.meta.get("max_steps") and horizon > int(self.meta["max_steps"]):
            raise ValueError(f"this model forecasts at most {self.meta['max_steps']} steps")
        level = float(params.get("interval_level") or self.meta["interval_level"])
        if not 0.5 <= level <= 0.99:
            raise ValueError("interval_level must be between 0.5 and 0.99")
        kind = self.meta["kind"]
        levels = list(self.meta.get("levels") or [])
        if self.meta["shape"] == "panel" and model_input is not None and "series" in model_input:
            asked = [str(value) for value in model_input["series"].dropna().unique()]
            unknown = sorted(set(asked) - set(levels))
            if unknown:
                raise ValueError(f"unknown series {unknown[:5]}: this model was trained on {len(levels)} series")
            levels = [name for name in levels if name in asked] or levels
        exog = self._exog(model_input, horizon, levels)
        # Out-of-sample residuals are the backtest's errors, the ones the card's
        # coverage was measured with; in-sample ones would flatter the model.
        conformal = {
            "method": "conformal",
            "interval": level,
            "use_in_sample_residuals": self.meta.get("residuals") != "out_sample",
            "use_binned_residuals": False,
        }
        if kind == "stats":
            frame = self.forecaster.predict_interval(steps=horizon, exog=exog, interval=[(1 - level) / 2, (1 + level) / 2])
        elif kind == "naive":
            frame = self.forecaster.predict_interval(steps=horizon, **conformal)
        elif self.meta["shape"] == "panel":
            frame = self.forecaster.predict_interval(steps=horizon, levels=levels, exog=exog, **conformal)
        else:
            frame = self.forecaster.predict_interval(steps=horizon, exog=exog, **conformal)
        frame = frame.copy()
        lower = next(column for column in frame.columns if "lower" in column)
        upper = next(column for column in frame.columns if "upper" in column)
        frame = frame.rename(columns={lower: "lower_bound", upper: "upper_bound"})
        if "level" not in frame.columns:
            frame["level"] = self.meta["target"]
        frame = frame.rename_axis("timestamp").reset_index()
        frame["timestamp"] = frame["timestamp"].astype(str)
        frame = frame.rename(columns={"level": "series"})
        return frame[["series", "timestamp", "pred", "lower_bound", "upper_bound"]]


set_model(AgentiumForecaster())
