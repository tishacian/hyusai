"""Execute the frozen, offline Probabl pilot without another experiment store.

Examples (from the repository root, using the qualified ML interpreter):
  python backend/scripts/qualify_probabl_pilot.py --output /tmp/probabl-development
  python backend/scripts/qualify_probabl_pilot.py --output /tmp/probabl-final \
    --stage final --development /tmp/probabl-development \
    --weights-classification /provisioned/classification \
    --weights-regression /provisioned/regression

The final reserve is unlocked only for tasks with a complete development
comparison. Output directories are exclusive: a campaign cannot silently resume
or overwrite final evidence. Keep evidence in the existing artifact workflow.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import platform
import resource
import sys
import tempfile
import time
from pathlib import Path

RESOURCES = Path(__file__).resolve().parents[1] / "app" / "resources"
sys.path.insert(0, str(RESOURCES))
from probabl_pilot import (  # noqa: E402
    balanced_schedule,
    block_network,
    dataset,
    digest,
    exclusion_reason,
    partitions,
    project_full_cycle_cpu,
    run_bounded,
    runtime_versions,
    score,
    select_candidates,
    summarize,
    validate_contract,
    write_json,
)


def clock():
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return time.monotonic(), own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime


def elapsed(started):
    wall, cpu = clock()
    return {"wall_seconds": wall - started[0], "cpu_seconds": max(0, cpu - started[1])}


def harness():
    spec = importlib.util.spec_from_file_location(
        "ml_train_harness", RESOURCES / "ml_train_harness.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def estimator(case, task, contract, x, y, weights):
    candidate = case["candidate"]
    classification = task["kind"] == "classification"
    seed = contract["model_seed"]
    if candidate == "dummy":
        from sklearn.dummy import DummyClassifier, DummyRegressor

        return (
            DummyClassifier(strategy="prior") if classification else DummyRegressor(strategy="mean")
        ), None
    if candidate.startswith("tabicl_"):
        from ml_tabicl_runtime import build_estimator

        return build_estimator(
            task["kind"],
            weights,
            seed=seed,
            n_jobs=contract["budgets"]["threads"],
            n_estimators=1,
            kv_cache=candidate == "tabicl_cache",
        ), None
    module = harness()
    if candidate == "sklearn_linear":
        path = (
            "sklearn.linear_model.LogisticRegression"
            if classification
            else "sklearn.linear_model.Ridge"
        )
        params = {"max_iter": 300, "random_state": seed} if classification else {"alpha": 1.0}
        return module._make_pipeline(path, params, seed=seed), None
    path = (
        "sklearn.ensemble.HistGradientBoostingClassifier"
        if classification
        else "sklearn.ensemble.HistGradientBoostingRegressor"
    )
    params = {"max_iter": 100, "max_leaf_nodes": 31, "random_state": seed}
    tuning = None
    if candidate == "sklearn_tuned":
        definition = {
            "algo": "gradient_boosting",
            "task": task["kind"],
            "estimator": path,
            "random_state": seed,
            "spec": {},
            "tuning": {
                "metric": "balanced_accuracy" if classification else "neg_mean_absolute_error",
                "direction": "max",
                "trials": contract["search"]["trials"],
                "folds": contract["search"]["folds"],
                "budget_s": contract["search"]["seconds"],
                "forest_leaves": 64,
                "start": {"max_iter": 100, "max_leaf_nodes": 31, "learning_rate": 0.1},
                "space": [
                    {"key": "max_iter", "kind": "categorical", "choices": [50, 100]},
                    {"key": "max_leaf_nodes", "kind": "categorical", "choices": [15, 31]},
                    {"key": "learning_rate", "kind": "categorical", "choices": [0.05, 0.1]},
                ],
            },
        }
        params, tuning = module._tune(definition, x, y)
    return module._make_pipeline(
        path, params, seed=seed, tuning=candidate == "sklearn_tuned"
    ), tuning


def export_reload(model, x, y, path, candidate):
    if candidate.startswith("tabicl_"):
        from ml_tabicl_runtime import export_state, load_state

        export_state(model, x, y, path, foundation={"pilot": True})
        return lambda: load_state(path)
    import skops.io as sio

    path.mkdir(parents=True, exist_ok=True)
    trusted = harness()._trusted_types(model)
    sio.dump(model, path / "model.skops")
    return lambda: sio.load(path / "model.skops", trusted=trusted)


def worker(job_path, result_path):
    job = json.loads(Path(job_path).read_text())
    case, contract = job["case"], job["contract"]
    task = next(t for t in contract["tasks"] if t["id"] == case["task"])
    egress = block_network()
    import numpy as np
    from threadpoolctl import threadpool_limits

    started = clock()
    x, y = dataset(task)
    split = partitions(task, contract, y)[case["split"]]
    train, validation = split["train"], split["validation"]
    x_train, y_train = x.iloc[train].copy(), y.iloc[train].copy()
    x_test, y_test = x.iloc[validation].copy(), y.iloc[validation].copy()
    if case["candidate"].startswith("tabicl_"):
        from ml_tabicl_runtime import normalize_frame

        x_train, x_test = normalize_frame(x_train), normalize_frame(x_test)
    timings = {"data_preparation": elapsed(started)}
    with threadpool_limits(limits=contract["budgets"]["threads"]):
        started = clock()
        model, tuning = estimator(case, task, contract, x_train, y_train, job.get("weights"))
        model.fit(x_train, y_train)
        timings["selection_and_fit"] = elapsed(started)
        started = clock()
        predictions = np.asarray(model.predict(x_test))
        timings["first_prediction"] = elapsed(started)
        serving = {}
        for size in contract["serving"]["request_rows"]:
            # Repeated held-out rows are latency fixtures, never extra score units.
            batch = x_test.iloc[np.arange(size) % len(x_test)]
            repetitions = []
            for _ in range(contract["serving"]["repetitions"]):
                started = clock()
                model.predict(batch)
                repetitions.append(elapsed(started))
            serving[str(size)] = repetitions
        started = clock()
        reload_model = export_reload(
            model, x_train, y_train, Path(job["scratch"]) / "model", case["candidate"]
        )
        timings["export"] = elapsed(started)
        artifact_bytes = sum(
            p.stat().st_size for p in (Path(job["scratch"]) / "model").rglob("*") if p.is_file()
        )
        if artifact_bytes > contract["budgets"]["artifact_bytes"]:
            raise RuntimeError("case_artifact_budget")
        # Eviction is explicit; the reload must use only its autonomous bundle.
        started = clock()
        del model
        import gc

        gc.collect()
        timings["eviction"] = elapsed(started)
        started = clock()
        restored = reload_model()
        timings["reload"] = elapsed(started)
        started = clock()
        restored_predictions = np.asarray(restored.predict(x_test))
        timings["reload_first_prediction"] = elapsed(started)
        if task["kind"] == "classification":
            parity = bool(np.array_equal(predictions, restored_predictions))
        else:
            parity = bool(
                np.allclose(
                    predictions,
                    restored_predictions,
                    atol=contract["decision"]["reload_atol"],
                    rtol=contract["decision"]["reload_rtol"],
                )
            )
        if not parity:
            raise RuntimeError("Export/reload prediction parity failed")
    result = {
        **case,
        "status": "evaluated",
        "metric": task["metric"],
        "metric_value": score(task["kind"], y_test, predictions),
        "timings": timings,
        "serving": serving,
        "artifact_bytes": artifact_bytes,
        "offline_enforcement": egress,
        "reload_parity": parity,
        "train_rows": len(train),
        "validation_rows": len(validation),
        "split_sha256": digest(split),
        "versions": runtime_versions(),
        "tuning": tuning,
    }
    if case["split"] == "final":
        result.update(
            {
                "truth": y_test.tolist(),
                "predictions": predictions.tolist(),
                "agent_input_allowed": False,
            }
        )
        if task["kind"] == "classification":
            from sklearn.metrics import recall_score

            labels = np.unique(y_test)
            recalls = recall_score(
                y_test, predictions, labels=labels, average=None, zero_division=0
            )
            result["class_recall"] = {
                str(label): float(value) for label, value in zip(labels, recalls, strict=True)
            }
    write_json(result_path, result)


def code_hash():
    files = [
        Path(__file__),
        RESOURCES / "probabl_pilot.py",
        RESOURCES / "ml_train_harness.py",
        RESOURCES / "ml_tuning_harness.py",
        RESOURCES / "ml_knob_translation.py",
    ]
    optional = RESOURCES / "ml_tabicl_runtime.py"
    if optional.exists():
        files.append(optional)
    return digest({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files})


def weight_identity(paths):
    result = {}
    for task, path in paths.items():
        if path is not None:
            from ml_tabicl_runtime import validate_weights

            result[task] = validate_weights(path, task)
    return result


def main(argv=None):
    cpu_at_start = resource.getrusage(resource.RUSAGE_SELF)
    parent_cpu_start = cpu_at_start.ru_utime + cpu_at_start.ru_stime
    parent_cpu_accounted = 0.0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "config/ml/probabl-pilot.v2.json",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--stage", choices=("development", "final"), default="development")
    parser.add_argument("--development", type=Path)
    parser.add_argument("--weights-classification", type=Path)
    parser.add_argument("--weights-regression", type=Path)
    parser.add_argument(
        "--reserve-cpu-seconds",
        type=float,
        default=0,
        help="Conservatively reserve budget for earlier interrupted qualification; not a measured cost",
    )
    parser.add_argument("--worker", nargs=2, metavar=("JOB", "RESULT"))
    args = parser.parse_args(argv)
    if args.worker:
        worker(*args.worker)
        return
    if not args.output:
        parser.error("--output is required")
    contract = validate_contract(json.loads(args.contract.read_text()))
    contract_hash = digest(contract)
    runner_hash = code_hash()
    versions = runtime_versions()
    for package, expected in contract["runtime"].items():
        actual = versions.get(package)
        if actual is not None and actual != expected:
            parser.error(f"Runtime {package}={actual} differs from frozen {expected}")
    weights = {"classification": args.weights_classification, "regression": args.weights_regression}
    identities = weight_identity(weights)
    selection = None
    prior_cpu = 0
    reserved_cpu = args.reserve_cpu_seconds
    if (
        not math.isfinite(reserved_cpu)
        or not 0 <= reserved_cpu < contract["budgets"]["campaign_cpu_seconds"]
    ):
        parser.error("CPU reserve must be finite, nonnegative and below the campaign budget")
    if args.stage == "final":
        if not args.development:
            parser.error("--final requires --development with complete paired results")
        development = json.loads((args.development / "results.json").read_text())
        if (
            development["contract_sha256"] != contract_hash
            or development["code_sha256"] != runner_hash
        ):
            parser.error(
                "Contract or implementation changed after development; use a new protocol/reserve"
            )
        if development["versions"] != runtime_versions():
            parser.error("Runtime changed after development")
        if development["weights"] != identities:
            parser.error("Weights changed after development")
        selection = select_candidates(contract, development["results"])
        if not any(selection.values()):
            parser.error(
                "No complete paired development comparison; final reserve remains unopened"
            )
        prior_cpu = development["total_cpu_seconds"]
        reserved_cpu = max(reserved_cpu, development.get("reserved_cpu_seconds", 0))
        # An exclusive marker binds one final evaluation to this development run.
        write_json(
            args.development / "final-reserve-opened.json",
            {"selection": selection, "contract_sha256": contract_hash, "code_sha256": runner_hash},
            exclusive=True,
        )
    args.output.mkdir(parents=True, exist_ok=False)
    frozen = {
        "contract": contract,
        "contract_sha256": contract_hash,
        "code_sha256": runner_hash,
        "versions": versions,
        "weights": identities,
        "selection": selection,
        "stage": args.stage,
        "reserved_cpu_seconds": reserved_cpu,
        "final_test_agent_input_allowed": False,
        "thread_wait_policy": {"OMP_WAIT_POLICY": "PASSIVE", "KMP_BLOCKTIME": "0"},
        "hardware": {
            "co_tenant_workload_controlled": False,
            "interactive_sla_qualified": False,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "logical_cpu_count": os.cpu_count(),
            "cpu_model": next(
                (
                    line.split(":", 1)[1].strip()
                    for line in Path("/proc/cpuinfo").read_text().splitlines()
                    if line.startswith("model name")
                ),
                "unknown",
            ),
        },
    }
    # Freeze before any worker is started or final label is evaluated.
    write_json(args.output / "frozen-protocol.json", frozen, exclusive=True)
    results = []
    total_cpu = prior_cpu
    schedule = balanced_schedule(contract, args.stage, selection)
    env = {
        **os.environ,
        **{
            key: str(contract["budgets"]["threads"])
            for key in (
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS",
            )
        },
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "DO_NOT_TRACK": "1",
        # Avoid busy waiting between OpenMP tasks on a quota-shared CPU worker.
        # Identical policy for every candidate, frozen with the campaign.
        "OMP_WAIT_POLICY": "PASSIVE",
        "KMP_BLOCKTIME": "0",
        "POLARS_MAX_THREADS": str(contract["budgets"]["threads"]),
    }
    for case_index, case in enumerate(schedule):
        own = resource.getrusage(resource.RUSAGE_SELF)
        parent_cpu = own.ru_utime + own.ru_stime - parent_cpu_start
        total_cpu += parent_cpu - parent_cpu_accounted
        parent_cpu_accounted = parent_cpu
        task = next(t for t in contract["tasks"] if t["id"] == case["task"])
        remaining = contract["budgets"]["campaign_cpu_seconds"] - total_cpu - reserved_cpu
        excluded = exclusion_reason(contract, case["task"], case["candidate"])
        reason = None
        if remaining <= 0:
            reason = "campaign_cpu_budget_exhausted"
        elif case["candidate"].startswith("tabicl_") and (
            weights[task["kind"]] is None
            or not weights[task["kind"]].is_dir()
            or runtime_versions()["tabicl"] is None
        ):
            reason = "qualified_local_weights_or_runtime_unavailable"
        if excluded:
            result = {**case, "status": "not_qualified", "reason": excluded, "executed": False}
        elif reason:
            result = {**case, "status": "not_evaluated", "reason": reason}
        else:
            with tempfile.TemporaryDirectory(prefix="probabl-pilot-") as scratch:
                job_path, result_path = Path(scratch) / "job.json", Path(scratch) / "result.json"
                write_json(
                    job_path,
                    {
                        "case": case,
                        "contract": contract,
                        "weights": str(weights[task["kind"]]) if weights[task["kind"]] else None,
                        "scratch": scratch,
                    },
                )
                resources = run_bounded(
                    [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--worker",
                        str(job_path),
                        str(result_path),
                    ],
                    env=env,
                    wall_seconds=contract["budgets"]["case_wall_seconds"],
                    cpu_seconds=remaining,
                    memory_bytes=contract["budgets"]["memory_bytes"],
                )
                total_cpu += resources["cpu_seconds"]
                if resources["exit_code"] == 0 and result_path.exists():
                    result = json.loads(result_path.read_text())
                    projection = project_full_cycle_cpu(
                        resources["cpu_seconds"], result["timings"], result["serving"], contract
                    )
                    result["cost_projection"] = projection
                    result["projected_cpu_seconds"] = projection["projected_cpu_seconds"]
                else:
                    result = {
                        **case,
                        "status": "failed",
                        "reason": resources["stopped_by"] or "worker_failure",
                    }
                result["resources"] = resources
        results.append(result)
        summary = (
            summarize(contract, results)
            if case_index == len(schedule) - 1
            else {"status": "campaign_in_progress", "adoption": "experimental"}
        )
        own = resource.getrusage(resource.RUSAGE_SELF)
        parent_cpu = own.ru_utime + own.ru_stime - parent_cpu_start
        total_cpu += parent_cpu - parent_cpu_accounted
        parent_cpu_accounted = parent_cpu
        evidence = {
            "schema": "agentium.probabl-pilot-results.v1",
            "stage": args.stage,
            "contract_sha256": contract_hash,
            "code_sha256": runner_hash,
            "versions": versions,
            "weights": identities,
            "results": results,
            "total_cpu_seconds": total_cpu,
            "reserved_cpu_seconds": reserved_cpu,
            "planned_cases": len(schedule),
            "completed_cases": len(results),
            "summary": summary,
        }
        write_json(args.output / "results.json", evidence)
        print(f"{case['task']}/{case['split']}/{case['candidate']}: {result['status']}", flush=True)
    write_json(
        args.output / "selection.json",
        {
            "contract_sha256": contract_hash,
            "selected_on_development_only": select_candidates(contract, results)
            if args.stage == "development"
            else selection,
        },
    )


if __name__ == "__main__":
    main()
