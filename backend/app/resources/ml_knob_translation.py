"""Pure catalog translation, also loaded by path by the standalone harness."""
from __future__ import annotations


def translate(algo_key: str, task: str, knobs: dict, *, random_state: int, forest_leaves: int) -> dict:
    params = dict(knobs)
    if algo_key == "linear" and task == "classification" and "alpha" in params:
        strength = float(params.pop("alpha")) or 1.0
        params["C"] = round(1.0 / strength, 6)
    if algo_key in {"gradient_boosting", "random_forest", "linear"}:
        params.setdefault("random_state", random_state)
    if algo_key == "random_forest":
        params["n_jobs"] = 1
        if params.get("max_depth") is None:
            # Automatic depth is safe even for the untuned baseline trial.
            params.setdefault("max_leaf_nodes", forest_leaves)
    return params
