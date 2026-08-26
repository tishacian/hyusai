"""Print every figure a manual rebuild of the Nawa data/ML use case must land on.

The companion to ``docs/demo-runs/2026-08-25-nawa-data-ml/PAPAI-MIRROR.md``, which
describes how to rebuild the churn and radio pipelines by hand on another
platform. That note quotes row counts, band counts and metrics; an operator
rebuilding the case needs to *check* them, and a figure copied into prose is a
figure that goes stale on the first change to the generator.

So the numbers come from here, computed by importing the same generator, the same
cleaning statement, the same feature script and the same dbt models the demo
runs. Nothing is duplicated: this script owns no SQL and no feature logic of its
own.

It needs polars, duckdb and — for ``--with-fits`` — scikit-learn, skrub and
pandas. It does **not** need a database, an object store or a running Agentium:
the point is that the specification can be arbitrated from the bytes alone.

Usage:
    cd backend
    python -m scripts.papai_mirror_facts                 # counts, seconds
    python -m scripts.papai_mirror_facts --with-fits     # + the three ROC AUCs
    python -m scripts.papai_mirror_facts --json          # machine-readable
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.gen_nawa_telecom_data import (
    CHURN_FEATURE_COLUMNS,
    CHURN_TARGET,
    churn_raw_frame,
    clean_churn_frame,
    network_cell_frame,
)
from scripts.seed_nawa_data_demo import ENGINEERED_COLUMNS, FEATURE_CODE, RADIO_MODELS

#: The train/test split of every fit in the demo, and the seed under it. Stated
#: here because a rebuild that changes either lands on different metrics while
#: every row count still matches — the one discrepancy that is hard to find by
#: looking at tables.
TEST_SIZE = 0.25
RANDOM_STATE = 42


def feature_frame(cleaned: Any) -> Any:
    """Apply the demo's Polars feature script to the cleaned base.

    ``exec`` of the node's own source rather than a re-implementation: the whole
    value of this script is that it cannot disagree with what the pipeline runs.
    """

    namespace: dict[str, Any] = {}
    exec(FEATURE_CODE, namespace)  # noqa: S102 - our own literal, versioned beside it
    return namespace["transform"]({"input": cleaned})


def watchlist_frame(network: Any) -> Any:
    """Run the two dbt models over the KPI table, with the refs resolved by hand.

    dbt itself is not needed to obtain the mart: ``ref`` and ``source`` are the
    only templating the project uses, so substituting them leaves plain duckdb
    SQL. That is also what makes the models portable to a platform whose SQL step
    has no dbt in it.
    """

    import duckdb

    connection = duckdb.connect()
    try:
        connection.register("input", network.to_arrow())
        staging = RADIO_MODELS[0]["sql"].replace(
            "{{ source('inputs', 'input') }}", "input"
        )
        connection.execute(f"create view stg_cell_hourly as {staging}")
        mart = RADIO_MODELS[1]["sql"].replace(
            "{{ ref('stg_cell_hourly') }}", "stg_cell_hourly"
        )
        return connection.execute(mart).pl()
    finally:
        connection.close()


def _counts(series: Any) -> dict[str, int]:
    return {
        str(row[series.name]): int(row["count"])
        for row in series.value_counts().sort(series.name).to_dicts()
    }


def fits(cleaned: Any, features: Any) -> dict[str, float]:
    """The three ROC AUCs the demo's registry holds, refitted from the frames.

    Assembled with ``skrub.tabular_pipeline`` — the same call the training
    harness makes — so the preprocessing is the estimator's own requirement
    rather than a choice made here. The numbers will not match the demo's to six
    decimals on a different scikit-learn; the *ordering* is the claim.
    """

    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import train_test_split
    from skrub import tabular_pipeline

    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression

    def auc(frame: Any, columns: list[str], estimator: Any) -> float:
        table = frame.to_pandas()
        x = table[columns].copy()
        for column in x.columns:
            if str(x[column].dtype).startswith(("int", "Int")):
                x[column] = x[column].astype("float64")
        y = table[CHURN_TARGET]
        x_train, x_test, y_train, y_test = train_test_split(
            x, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y
        )
        pipeline = tabular_pipeline(estimator)
        imputer = pipeline.named_steps.get("simpleimputer")
        if imputer is not None:
            imputer.set_params(strategy="median")
        pipeline.fit(x_train, y_train)
        return round(
            float(roc_auc_score(y_test, pipeline.predict_proba(x_test)[:, 1])), 6
        )

    base = list(CHURN_FEATURE_COLUMNS)
    engineered = [*CHURN_FEATURE_COLUMNS, *ENGINEERED_COLUMNS]
    return {
        "v1_linear_20_columns": auc(
            cleaned, base, LogisticRegression(max_iter=1000, random_state=RANDOM_STATE)
        ),
        "v2_gradient_boosting_20_columns": auc(
            cleaned,
            base,
            HistGradientBoostingClassifier(
                max_iter=220, learning_rate=0.08, random_state=RANDOM_STATE
            ),
        ),
        "v3_gradient_boosting_29_columns": auc(
            features,
            engineered,
            HistGradientBoostingClassifier(
                max_iter=220, learning_rate=0.08, random_state=RANDOM_STATE
            ),
        ),
    }


def facts(*, seed: int = 20260825, with_fits: bool = False) -> dict[str, Any]:
    """Every acceptance figure of the specification, computed from the bytes."""

    raw = churn_raw_frame(seed=seed)
    cleaned = clean_churn_frame(raw)
    features = feature_frame(cleaned)
    network = network_cell_frame(seed=seed)
    watchlist = watchlist_frame(network)

    body: dict[str, Any] = {
        "seed": seed,
        "raw_export": {
            "rows": raw.height,
            "columns": raw.width,
            "distinct_subscribers": int(raw["msisdn"].n_unique()),
            "duplicate_rows": raw.height - int(raw["msisdn"].n_unique()),
            "region_spellings": int(raw["region"].n_unique()),
            "plan_spellings": int(raw["plan"].n_unique()),
            "suspended_rows": int((raw["line_status"] == "suspended").sum()),
            "arpu_null_rows": int(raw["arpu_mad"].null_count()),
            "arpu_sentinel_rows": int((raw["arpu_mad"] == -1.0).sum()),
            "nps_null_rows": int(raw["nps"].null_count()),
            "churn_rate": round(float(raw[CHURN_TARGET].mean()), 4),
        },
        "cleaned_base": {
            "rows": cleaned.height,
            "columns": cleaned.width,
            "regions": int(cleaned["region"].n_unique()),
            "plans": int(cleaned["plan"].n_unique()),
            "churn_rate": round(float(cleaned[CHURN_TARGET].mean()), 4),
            "churn_positives": int(cleaned[CHURN_TARGET].sum()),
            "nps_null_rows": int(cleaned["nps"].null_count()),
        },
        "feature_table": {
            "rows": features.height,
            "columns": features.width,
            "added": list(ENGINEERED_COLUMNS),
            "tenure_bands": _counts(features["tenure_band"]),
            "training_columns": len(CHURN_FEATURE_COLUMNS) + len(ENGINEERED_COLUMNS),
        },
        "radio_kpis": {
            "rows": network.height,
            "columns": network.width,
            "cells": int(network["cell_id"].n_unique()),
            "first_hour": str(network["ts"].min()),
            "last_hour": str(network["ts"].max()),
            "prb_max": round(float(network["prb_utilization_pct"].max()), 2),
            "hours_at_the_ceiling": int((network["prb_utilization_pct"] >= 100.0).sum()),
        },
        "watchlist": {
            "rows": watchlist.height,
            "columns": watchlist.width,
            "bands": _counts(watchlist["risk_band"]),
            "climbers_above_20_points": int(
                (watchlist["prb_pct_delta"] > 20.0).sum()
            ),
            "fallers_below_minus_10_points": int(
                (watchlist["prb_pct_delta"] < -10.0).sum()
            ),
        },
        "split": {"test_size": TEST_SIZE, "random_state": RANDOM_STATE},
    }
    if with_fits:
        body["roc_auc"] = fits(cleaned, features)
    return body


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20260825)
    parser.add_argument(
        "--with-fits",
        action="store_true",
        help="Also refit the three models and report their ROC AUC (slow).",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON, not a report.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    body = facts(seed=args.seed, with_fits=args.with_fits)
    if args.json:
        print(json.dumps(body, indent=2, default=str))
        return 0
    for section, values in body.items():
        if not isinstance(values, dict):
            print(f"{section}: {values}")
            continue
        print(f"\n[{section}]")
        for key, value in values.items():
            print(f"  {key} = {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
