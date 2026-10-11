"""Offline, pre-registered pilot primitives; never imported by the agent runtime.

Results are qualification evidence, not another experiment store. Only the
explicit CLI may evaluate the reserved final test. No generated data proves ROI.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import errno
import hashlib
import importlib.metadata
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def write_json(path, value, *, exclusive=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    destination = path if exclusive else path.with_suffix(path.suffix + ".partial")
    with destination.open("x" if exclusive else "w") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    if not exclusive:
        destination.replace(path)


def runtime_versions():
    packages = (
        "numpy",
        "pandas",
        "scikit-learn",
        "skrub",
        "skops",
        "optuna",
        "tabicl",
        "torch",
        "safetensors",
    )
    result = {}
    for package in packages:
        try:
            result[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            result[package] = None
    return result


def dataset(task):
    """Only bundled UCI tables and our fixed, explicitly synthetic generators."""
    import numpy as np
    import pandas as pd
    from sklearn.datasets import load_breast_cancer, load_iris, make_friedman1, make_regression

    source = task["source"]
    if source in {"iris", "breast_cancer"}:
        bundled = (load_iris if source == "iris" else load_breast_cancer)(as_frame=True)
        return bundled.data, bundled.target
    seed = task["generator_seed"]
    n = task["rows"]
    if source == "linear_synthetic":
        x, y = make_regression(
            n_samples=n, n_features=12, n_informative=7, noise=8, random_state=seed
        )
        return pd.DataFrame(x, columns=[f"x{i}" for i in range(x.shape[1])]), pd.Series(
            y, name="target"
        )
    if source == "friedman_synthetic":
        x, y = make_friedman1(n_samples=n, n_features=10, noise=1, random_state=seed)
        frame = pd.DataFrame(x, columns=[f"x{i}" for i in range(x.shape[1])])
        frame["region"] = np.array(["north", "south", "east", "west"])[np.arange(n) % 4]
        return frame, pd.Series(y, name="target")
    if source in {"delivery_late_synthetic", "delivery_cost_synthetic"}:
        rng = np.random.default_rng(seed)
        distance = rng.uniform(10, 1200, n)
        weight = rng.lognormal(1, 0.8, n)
        rural = rng.choice(["urban", "rural"], n, p=[0.75, 0.25])
        carrier = rng.choice(["carrier_a", "carrier_b", "carrier_c"], n)
        x = pd.DataFrame(
            {"distance_km": distance, "weight_kg": weight, "destination": rural, "carrier": carrier}
        )
        if source == "delivery_late_synthetic":
            logit = (
                -4.2 + distance / 600 + (rural == "rural") * 0.8 + (carrier == "carrier_c") * 0.6
            )
            target = rng.binomial(1, 1 / (1 + np.exp(-logit)))
        else:
            target = (
                5
                + distance * 0.025
                + weight * 1.8
                + (rural == "rural") * 5
                + (carrier == "carrier_c") * 2
                + rng.normal(0, 2, n)
            )
        return x, pd.Series(target, name="target")
    raise ValueError(f"Unsupported offline dataset: {source}")


def frame_digest(x, y):
    # JSON is independent of parquet engines and records feature order/dtypes.
    return digest(
        {
            "columns": list(x.columns),
            "dtypes": [str(t) for t in x.dtypes],
            "data": json.loads(x.to_json(orient="values", double_precision=15)),
            "target": json.loads(y.to_json(orient="values", double_precision=15)),
        }
    )


def partitions(task, contract, y):
    import numpy as np
    from sklearn.model_selection import train_test_split

    if contract["partition"]["strategy"] != "iid":
        raise ValueError(
            "Groups and time splits require a separate qualified protocol; no random fallback"
        )
    indices = np.arange(len(y))
    stratify = y if task["kind"] == "classification" else None
    development, final = train_test_split(
        indices,
        test_size=contract["partition"]["final_fraction"],
        random_state=contract["partition"]["final_seed"],
        stratify=stratify,
    )
    result = {}
    for index, seed in enumerate(contract["partition"]["development_seeds"]):
        train, validation = train_test_split(
            development,
            test_size=contract["partition"]["validation_fraction"],
            random_state=seed,
            stratify=y.iloc[development] if stratify is not None else None,
        )
        result[f"dev-{index}"] = {"train": train.tolist(), "validation": validation.tolist()}
    result["final"] = {"train": development.tolist(), "validation": final.tolist()}
    return result


def validate_contract(contract):
    if contract.get("schema") not in {"omnirag.probabl-pilot.v1", "omnirag.probabl-pilot.v2"}:
        raise ValueError("Unknown pilot schema")
    tasks = contract["tasks"]
    exclusions = contract.get("exclusions", [])
    if contract["schema"] == "omnirag.probabl-pilot.v2":
        expected = {(task["id"], "tabicl_plain") for task in tasks if task["kind"] == "regression"}
        actual = {(item["task"], item["candidate"]) for item in exclusions}
        if (
            len(exclusions) != 3
            or actual != expected
            or any(not item["reason"] for item in exclusions)
        ):
            raise ValueError(
                "Revision 2 must exclude every unqualified uncached regression profile"
            )
    elif exclusions:
        raise ValueError("Revision 1 did not pre-register exclusions")
    if contract["candidates"] != [
        "dummy",
        "sklearn_linear",
        "sklearn_hist",
        "sklearn_tuned",
        "tabicl_plain",
        "tabicl_cache",
    ]:
        raise ValueError("Candidate set and balanced scheduling order must be pre-registered")
    if len(tasks) != 6 or len({t["id"] for t in tasks}) != 6:
        raise ValueError("Six unique pre-registered tasks required")
    if (
        sum(t["kind"] == "classification" for t in tasks) != 3
        or sum(t["kind"] == "regression" for t in tasks) != 3
    ):
        raise ValueError("Three classification and three regression tasks required")
    limits = contract["budgets"]
    if (
        not 0 < limits["threads"] <= 4
        or not 0 < limits["case_wall_seconds"] <= 600
        or not 0 < limits["campaign_cpu_seconds"] <= 43200
    ):
        raise ValueError("Pilot exceeds pre-registered CPU/wall limits")
    if (
        contract["partition"]["strategy"] != "iid"
        or len(contract["partition"]["development_seeds"]) != 3
    ):
        raise ValueError("Only the explicit three-split IID pilot is qualified")
    if contract["decision"]["business_value_status"] != "not_evaluated":
        raise ValueError("Public/synthetic pilot cannot establish business value")
    for task in tasks:
        metric, direction = (
            ("f1_macro", "max") if task["kind"] == "classification" else ("mae", "min")
        )
        if (task["metric"], task["direction"]) != (metric, direction):
            raise ValueError("Unsupported primary metric or direction")
        if task["rows"] > 10000 or not task["license"] or not task["reference"]:
            raise ValueError("Dataset needs an admissible size, license and provenance")
        x, y = dataset(task)
        if len(y) != task["rows"] or x.shape[1] > 100:
            raise ValueError("Dataset shape differs from contract")
        if frame_digest(x, y) != task["sha256"]:
            raise ValueError(f"Dataset fingerprint changed: {task['id']}")
        actual = {key: digest(value) for key, value in partitions(task, contract, y).items()}
        if actual != task["partition_sha256"]:
            raise ValueError(f"Partition fingerprint changed: {task['id']}")
    return contract


def exclusion_reason(contract, task, candidate):
    """Exclusions are protocol decisions, never inferred from a lucky rerun."""
    return next(
        (
            item["reason"]
            for item in contract.get("exclusions", [])
            if item["task"] == task and item["candidate"] == candidate
        ),
        None,
    )


def balanced_schedule(contract, stage="development", selection=None):
    """Rotate first candidate, and visit every dataset before another split."""
    candidates = contract["candidates"]
    splits = [f"dev-{n}" for n in range(3)] if stage == "development" else ["final"]
    result = []
    for split_number, split in enumerate(splits):
        for task_number, task in enumerate(contract["tasks"]):
            allowed = selection[task["id"]] if selection is not None else candidates
            if not allowed:
                continue
            rotation = (split_number + task_number) % len(allowed)
            ordered = allowed[rotation:] + allowed[:rotation]
            for candidate in ordered:
                result.append({"task": task["id"], "split": split, "candidate": candidate})
    return result


def block_network():
    """Kernel-enforced syscall filter, inherited by descendants; fail closed.

    No Python monkeypatch masquerading as a native-model egress boundary.
    UNIX socketpairs used by local runtimes remain available.
    """
    if sys.platform != "linux":
        raise RuntimeError("Offline qualification requires Linux seccomp")
    library = ctypes.util.find_library("seccomp")
    if not library:
        raise RuntimeError("Offline qualification requires libseccomp")
    seccomp = ctypes.CDLL(library, use_errno=True)
    seccomp.seccomp_init.argtypes = [ctypes.c_uint32]
    seccomp.seccomp_init.restype = ctypes.c_void_p
    seccomp.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    seccomp.seccomp_syscall_resolve_name.restype = ctypes.c_int
    seccomp.seccomp_rule_add.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    seccomp.seccomp_rule_add.restype = ctypes.c_int
    seccomp.seccomp_load.argtypes = [ctypes.c_void_p]
    seccomp.seccomp_load.restype = ctypes.c_int
    seccomp.seccomp_release.argtypes = [ctypes.c_void_p]
    context = seccomp.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW
    if not context:
        raise RuntimeError("Cannot create seccomp context")
    try:
        for syscall in ("connect", "sendto", "sendmsg", "sendmmsg"):
            number = seccomp.seccomp_syscall_resolve_name(syscall.encode())
            if (
                number >= 0
                and seccomp.seccomp_rule_add(context, 0x00050000 | errno.EPERM, number, 0) != 0
            ):
                raise RuntimeError("Cannot restrict network syscalls")
        if seccomp.seccomp_load(context) != 0:
            raise RuntimeError("Cannot install egress restriction")
    finally:
        seccomp.seccomp_release(context)
    return "linux_seccomp_connect_send_denied"


def process_group_usage(group):
    """Sum live process CPU plus their already-reaped children, and live RSS."""
    ticks = os.sysconf("SC_CLK_TCK")
    pages = os.sysconf("SC_PAGE_SIZE")
    cpu = rss = 0
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            if int(fields[2]) != group:  # field 5 = process group
                continue
            cpu += sum(int(fields[index]) for index in (11, 12, 13, 14)) / ticks
            rss += int(fields[21]) * pages
        except (OSError, ValueError, IndexError):
            continue
    return cpu, rss


def run_bounded(command, *, env, wall_seconds, cpu_seconds, memory_bytes):
    import resource

    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.monotonic()
    reason = None
    peak = consumed = 0
    # Logs are bounded by a temporary file read from its tail, not a full pipe.
    import tempfile

    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(command, stdout=log, stderr=log, env=env, start_new_session=True)
        try:
            while process.poll() is None:
                cpu, rss = process_group_usage(process.pid)
                consumed, peak = max(consumed, cpu), max(peak, rss)
                if time.monotonic() - started >= wall_seconds:
                    reason = "case_wall_budget"
                elif cpu >= cpu_seconds:
                    reason = "campaign_cpu_budget"
                elif rss > memory_bytes:
                    reason = "case_memory_budget"
                if reason:
                    os.killpg(process.pid, signal.SIGKILL)
                    break
                time.sleep(0.05)
            process.wait()
        finally:
            # Also kill orphaned descendants if the top-level worker exited early.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        consumed = max(
            consumed, after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime
        )
        log.seek(0, 2)
        log.seek(max(0, log.tell() - 4000))
        tail = log.read().decode(errors="replace")
    return {
        "exit_code": process.returncode,
        "stopped_by": reason,
        "cpu_seconds": consumed,
        "peak_group_rss_bytes": peak,
        "wall_seconds": time.monotonic() - started,
        "log_tail": tail if process.returncode else None,
    }


def score(kind, y, predicted):
    from sklearn.metrics import f1_score, mean_absolute_error

    if kind == "classification":
        return float(f1_score(y, predicted, average="macro", zero_division=0))
    return float(mean_absolute_error(y, predicted))


def project_full_cycle_cpu(measured_cpu_seconds, timings, serving, contract):
    """Replace only latency probes by the declared service volume.

    The supervisor total includes process startup, imports and tuning children.
    Phase timers explain this total; do not add them to it a second time.
    """
    measured_phases = sum(item["cpu_seconds"] for item in timings.values())
    warm_probes = sum(item["cpu_seconds"] for batch in serving.values() for item in batch)
    warm = serving[str(contract["serving"]["projected_request_rows"])]
    projected_service = (
        contract["serving"]["projected_requests"]
        * sum(item["cpu_seconds"] for item in warm)
        / len(warm)
    )
    overhead = max(0.0, measured_cpu_seconds - measured_phases - warm_probes)
    return {
        "projected_cpu_seconds": measured_phases + overhead + projected_service,
        "measured_full_cycle_cpu_seconds": measured_cpu_seconds,
        "startup_imports_and_unattributed_cpu_seconds": overhead,
        "excluded_latency_probe_cpu_seconds": warm_probes,
        "projected_service_cpu_seconds": projected_service,
        "projected_requests": contract["serving"]["projected_requests"],
        "projected_request_rows": contract["serving"]["projected_request_rows"],
    }


def paired_interval(kind, y, baseline, challenger, *, seed, repetitions=2000):
    """IID row paired bootstrap; positive difference means challenger improves.

    Classification resamples within class to avoid degenerate rare-class samples.
    The contract explicitly excludes repeated entities/time-series observations.
    """
    import numpy as np

    y, baseline, challenger = (np.asarray(a) for a in (y, baseline, challenger))
    if len(y) < 30 or baseline.shape != y.shape or challenger.shape != y.shape:
        return {"status": "insufficient_independent_units"}
    rng = np.random.default_rng(seed)
    groups = (
        [np.flatnonzero(y == value) for value in np.unique(y)]
        if kind == "classification"
        else [np.arange(len(y))]
    )
    if min(map(len, groups)) < 10:
        return {"status": "insufficient_independent_units"}

    def improvement(indices):
        left, right = (
            score(kind, y[indices], baseline[indices]),
            score(kind, y[indices], challenger[indices]),
        )
        return right - left if kind == "classification" else (left - right) / max(abs(left), 1e-12)

    samples = [
        improvement(
            np.concatenate([rng.choice(group, len(group), replace=True) for group in groups])
        )
        for _ in range(repetitions)
    ]
    low, high = np.quantile(samples, [0.025, 0.975])
    return {
        "status": "evaluated",
        "method": "paired_stratified_iid_percentile_bootstrap"
        if kind == "classification"
        else "paired_iid_percentile_bootstrap",
        "confidence": 0.95,
        "repetitions": repetitions,
        "gain": improvement(np.arange(len(y))),
        "lower": float(low),
        "upper": float(high),
        "unit": "absolute_f1_macro" if kind == "classification" else "relative_mae_reduction",
    }


def select_candidates(contract, results):
    selected = {}
    for task in contract["tasks"]:
        values = {}
        for candidate in contract["candidates"]:
            if exclusion_reason(contract, task["id"], candidate):
                continue
            rows = [
                r
                for r in results
                if r["task"] == task["id"]
                and r["candidate"] == candidate
                and r["status"] == "evaluated"
                and r.get("split_sha256") == task["partition_sha256"].get(r["split"])
            ]
            if len(rows) == 3 and {r["split"] for r in rows} == {"dev-0", "dev-1", "dev-2"}:
                metric = sum(r["metric_value"] for r in rows) / 3
                values[candidate] = (
                    metric if task["direction"] == "min" else -metric,
                    sum(r["resources"]["cpu_seconds"] for r in rows),
                )
        classical = [c for c in values if c.startswith("sklearn_")]
        foundation = [c for c in values if c.startswith("tabicl_")]
        # Do not unlock a final test if there is no complete paired challenger.
        selected[task["id"]] = (
            ["dummy", min(classical, key=values.get), min(foundation, key=values.get)]
            if classical and foundation and "dummy" in values
            else []
        )
    return selected


def summarize(contract, results):
    summary = {
        "business_value": "not_evaluated",
        "energy": "not_measured",
        "carbon": "not_measured",
        "money": "not_measured",
        "adoption": "experimental",
        "aggregate_metric": None,
        "tasks": [],
    }
    for task in contract["tasks"]:
        rows = [
            r
            for r in results
            if r["task"] == task["id"]
            and r["split"] == "final"
            and r["status"] == "evaluated"
            and not exclusion_reason(contract, task["id"], r["candidate"])
        ]
        baseline = next((r for r in rows if r["candidate"].startswith("sklearn_")), None)
        challenger = next((r for r in rows if r["candidate"].startswith("tabicl_")), None)
        item = {
            "task": task["id"],
            "status": "not_evaluated",
            "reason": "complete_paired_final_required",
        }
        if (
            baseline
            and challenger
            and baseline.get("split_sha256")
            == challenger.get("split_sha256")
            == task["partition_sha256"]["final"]
            and baseline.get("truth") == challenger.get("truth")
        ):
            interval = paired_interval(
                task["kind"],
                baseline["truth"],
                baseline["predictions"],
                challenger["predictions"],
                seed=contract["decision"]["bootstrap_seed"],
                repetitions=contract["decision"]["bootstrap_repetitions"],
            )
            bcost, ccost = baseline["projected_cpu_seconds"], challenger["projected_cpu_seconds"]
            ratio = ccost / bcost if bcost > 0 else None
            target = (
                contract["decision"]["classification_gain"]
                if task["kind"] == "classification"
                else contract["decision"]["regression_relative_gain"]
            )
            margin = (
                contract["decision"]["classification_noninferiority"]
                if task["kind"] == "classification"
                else contract["decision"]["regression_relative_noninferiority"]
            )
            storage_ok = challenger["artifact_bytes"] <= baseline["artifact_bytes"]
            recall_ok = all(
                challenger.get("class_recall", {}).get(label, -1) >= value - 0.02
                for label, value in baseline.get("class_recall", {}).items()
            )
            quality = (
                interval.get("gain", -1) >= target
                and interval.get("lower", -1) > 0
                and ratio is not None
                and ratio <= contract["decision"]["quality_max_cost_ratio"]
                and recall_ok
            )
            frugal = (
                interval.get("lower", -1) >= -margin
                and ratio is not None
                and ratio <= contract["decision"]["frugal_max_cost_ratio"]
                and storage_ok
            )
            item = {
                "task": task["id"],
                "status": "evaluated",
                "interval": interval,
                "full_cycle_cpu_ratio": ratio,
                "storage_nonincreasing": storage_ok,
                "class_recall_guard_met": recall_ok,
                "statistical_quality_threshold_met": quality,
                "compute_frugality_threshold_met": frugal and recall_ok,
                "adoption": "experimental_pending_authorized_business_case_and_target_hardware",
            }
        summary["tasks"].append(item)
    return summary
