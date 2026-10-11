"""Bounded Skore checks on development rows, using no final-test input or store."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from importlib.metadata import version
from pathlib import Path

SCHEMA = 1
DEFAULT_CHECKS = ("SKD001", "SKD002", "SKD004", "SKD008", "SKD009", "SKD012", "SKD013", "SKD016")
SECTIONS = {"issue", "tip", "passed", "not_applicable", "skipped", "ignored", "error", "pending"}


def _save(result, path):
    path = Path(path)
    temporary = path.with_suffix(".partial")
    temporary.write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def collect(report, *, selected=DEFAULT_CHECKS, checkpoint=None):
    """Isolate each public check so an exception cannot erase other findings."""
    codes = [entry.split(" - ", 1)[0] for entry in report.checks.available()]
    rows = report.checks.summarize(ignore=codes, fast_mode=True).frame().to_dict("records")
    for row in rows:
        if row["code"] in selected and row["section"] == "ignored":
            row["section"] = "pending"
    if checkpoint:
        checkpoint(rows)
    for row in rows:
        if row["section"] != "pending":
            continue
        code = row["code"]
        try:
            summary = report.checks.summarize(
                ignore=[other for other in codes if other != code], fast_mode=True
            )
            result = summary.frame().loc[lambda frame: frame.code == code].to_dict("records")
            if len(result) != 1 or result[0]["section"] not in SECTIONS - {"pending"}:
                raise ValueError("Unexpected Skore check result")
            row.update(result[0])
            # Evidence is plain text, never Skore's HTML representation.
            for key, limit in (("title", 240), ("explanation", 3000), ("documentation_url", 500)):
                row[key] = str(row[key])[:limit] if row.get(key) is not None else None
        except Exception as exc:
            row.update(section="error", explanation=f"{type(exc).__name__}: {exc}"[:240])
        if checkpoint:
            checkpoint(rows)
    return rows


def run(pipeline, x_train, y_train, *, config, seed, task, positive_class, scratch):
    """Optional child fit/checks; inherits the supervisor's cancellation group."""
    evidence = {
        "schema": SCHEMA,
        "engine": "skore",
        "version": version("skore"),
        "scope": "development_base_estimator",
        "role": "development",
        "served_model": False,
        "checks": [],
    }
    if not config.get("enabled"):
        return {**evidence, "status": "disabled"}
    import joblib
    from sklearn.model_selection import train_test_split

    started = time.monotonic()
    budget = min(120.0, max(1.0, float(config.get("budget_s", 30))))
    ceiling = min(50_000, max(100, int(config.get("max_rows", 2000))))
    source = Path(scratch) / "diagnostics-input.joblib"
    result = Path(scratch) / "diagnostics-result.json"
    try:
        if len(x_train) > ceiling:
            x_train, _, y_train, _ = train_test_split(
                x_train,
                y_train,
                train_size=ceiling,
                random_state=seed,
                stratify=y_train if task == "classification" else None,
            )
        joblib.dump((pipeline, x_train, y_train, seed, task, positive_class), source)
        remaining = budget - (time.monotonic() - started)
        if remaining <= 0:
            raise subprocess.TimeoutExpired("diagnostics", budget)
        subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), str(source), str(result)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=remaining,
            check=True,
        )
        if result.stat().st_size > 512_000:
            raise ValueError("Diagnostics summary exceeds its byte ceiling")
        evidence.update(json.loads(result.read_text(encoding="utf-8")))
    except subprocess.TimeoutExpired:
        if result.exists() and result.stat().st_size <= 512_000:
            evidence.update(json.loads(result.read_text(encoding="utf-8")))
        for row in evidence["checks"]:
            if row["section"] == "pending":
                row.update(section="skipped", explanation="Diagnostic budget exhausted")
        evidence.update(status="timed_out", reason="budget_exhausted")
    except Exception as exc:
        evidence.update(status="error", reason=f"{type(exc).__name__}: {exc}"[:240])
    finally:
        source.unlink(missing_ok=True)
        result.unlink(missing_ok=True)
    return {
        **evidence,
        "budget_s": budget,
        "max_rows": ceiling,
        "elapsed_s": round(time.monotonic() - started, 3),
    }


def main(argv):
    import joblib
    from sklearn.model_selection import train_test_split
    from skore import EstimatorReport

    # Only the parent-created transient input enters this process.
    pipeline, x, y, seed, task, positive = joblib.load(argv[1])
    train_x, valid_x, train_y, valid_y = train_test_split(
        x,
        y,
        test_size=0.25,
        random_state=seed,
        stratify=y if task == "classification" else None,
    )
    report = EstimatorReport(
        pipeline,
        X_train=train_x,
        y_train=train_y,
        X_test=valid_x,
        y_test=valid_y,
        **({"pos_label": positive} if positive is not None else {}),
    )
    evidence = {"status": "running", "rows": {"train": len(train_x), "validation": len(valid_x)}}

    def checkpoint(rows):
        _save({**evidence, "checks": rows}, argv[2])

    rows = collect(report, checkpoint=checkpoint)
    _save({**evidence, "status": "completed", "checks": rows}, argv[2])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
