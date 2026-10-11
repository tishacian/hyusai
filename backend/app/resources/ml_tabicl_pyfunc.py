"""Trusted MLflow model-from-code facade for the offline TabICL context format."""

import importlib.util
from pathlib import Path

import mlflow.pyfunc
from mlflow.models import set_model


class AgentiumTabICL(mlflow.pyfunc.PythonModel):
    def load_context(self, context):
        path = Path(context.artifacts["runtime"])
        spec = importlib.util.spec_from_file_location("hyusai_tabicl_runtime", path)
        runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runtime)
        self.estimator = runtime.load_state(context.artifacts["state"])

    def get_raw_model(self):
        return self.estimator

    def predict(self, context, model_input, params=None):
        if params:
            raise ValueError("TabICL pilot takes no serving parameters")
        return self.estimator.predict(model_input)


set_model(AgentiumTabICL())
