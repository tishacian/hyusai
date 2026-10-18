"""Isolated reference prediction for runtime requalification.

Invoked only with a server-created manifest, by ``ml_requalification``. One
code path for both modes, so the two sets of outputs being compared were
produced exactly the same way, through the serving plane's own coercion,
frame building and prediction:

* ``capture`` — the strict serving gate: the reader must still be the
  producer runtime. The outputs become the model's reference predictions.
* ``requalify`` — every serving check except producer-runtime equality
  (hashes, sizes, trust profile, skops allowlist, MLmodel loader). Nothing is
  served from here; the parent compares the outputs and decides.
* ``import`` (M4.3) — the strict gate over a bundle whose contract the parent
  just built for this reader; the outputs are compared with the importer's
  expected outputs, and the measured costs against the serving budgets.

Every mode reports the load time, the single-row latency and the peak memory
the model added, because an accepted model is loaded in the API process.

The child receives the bundle the parent already downloaded, the reference
rows (never the reference outputs), and no database, object store or provider
credential. It reports its own reader runtime, because the process that loads
is the reader being attested.
"""

import json
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace

_CODE = re.compile(r"ML_[A-Z0-9_]{2,60}")


def _write(destination, payload):
    Path(destination).write_text(json.dumps(payload, allow_nan=False), encoding="utf-8")


def _finite_list(values):
    import math

    result = []
    for value in values:
        number = float(value)
        result.append(number if math.isfinite(number) else None)
    return result


def _peak_mb() -> float:
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Bytes on macOS, kilobytes on Linux.
    return peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024


def run(data):
    from app.core.config import settings
    from app.resources.ml_artifact_contract import runtime_versions
    from app.services.ml.artifacts import (
        verify_model_bundle,
        verify_requalification_candidate,
    )
    from app.services.tabular_predict import (
        _label,
        _load_mlflow_model,
        _predict_frame,
        _rows_from,
        build_frame,
        coerce_rows,
        contract_fields,
    )

    model = SimpleNamespace(**data["model"])
    artifact = (model.metrics_json or {}).get("artifact") or {}
    bundle = Path(data["bundle"])
    limit = int(data["max_artifact_bytes"])
    if data["mode"] in {"capture", "import"}:
        verify_model_bundle(bundle, artifact, family=model.family, max_bytes=limit)
    elif data["mode"] == "requalify":
        verify_requalification_candidate(bundle, artifact, family=model.family, max_bytes=limit)
    else:
        raise ValueError("unknown mode")
    reader = runtime_versions(model.family, artifact.get("serialization"))
    # Imports are done; what the peak gains from here on is the model's.
    baseline_mb = _peak_mb()
    started = time.monotonic()
    pipeline = _load_mlflow_model(bundle)
    load_ms = (time.monotonic() - started) * 1000
    fields = contract_fields(model)
    rows = list(data["rows"])
    # The serving contract caps one inline call; the reference set is bounded
    # by its own setting, so coercion follows the serving ceiling in chunks.
    ceiling = max(1, int(settings.ml_predict_max_rows))
    coerced = []
    for offset in range(0, len(rows), ceiling):
        coerced.extend(coerce_rows(model, rows[offset : offset + ceiling]))
    frame = build_frame(fields, coerced)
    started = time.monotonic()
    entry = SimpleNamespace(pipeline=pipeline)
    predicted, probabilities = _predict_frame(entry, model, frame)
    predict_ms = (time.monotonic() - started) * 1000
    # One interactive call, the shape /predict serves most.
    started = time.monotonic()
    _predict_frame(entry, model, frame.iloc[:1])
    single_row_ms = (time.monotonic() - started) * 1000
    # Probability columns follow the estimator's own classes_ order; the stored
    # vocabulary is the fallback for an estimator that does not expose it.
    raw_classes = getattr(pipeline, "classes_", None)
    classes = (
        [_label(value) for value in list(raw_classes)]
        if raw_classes is not None
        else [str(value) for value in (model.classes_json or [])]
    )
    answers = _rows_from(model, classes, None, predicted, None)
    outputs = {"labels": [answer["prediction"] for answer in answers]}
    if model.task == "classification":
        outputs["classes"] = classes
        outputs["probabilities"] = (
            [_finite_list(row) for row in probabilities] if probabilities is not None else None
        )
    elif model.task == "regression":
        outputs = {"values": [answer["prediction"] for answer in answers]}
    final = pipeline.steps[-1][1] if hasattr(pipeline, "steps") and pipeline.steps else pipeline
    return {
        "reader_runtime": reader,
        "estimator": type(final).__name__[:80],
        "outputs": outputs,
        "rows": len(rows),
        "load_ms": round(load_ms, 2),
        "predict_ms": round(predict_ms, 2),
        "single_row_ms": round(single_row_ms, 2),
        "model_memory_mb": round(max(0.0, _peak_mb() - baseline_mb), 1),
    }


def main(source, destination):
    data = json.loads(Path(source).read_text(encoding="utf-8"))
    # The supervisor owns the wall-clock deadline. If its worker is killed,
    # don't leave a detached native load alive beyond the job lease.
    if sys.platform == "linux":
        import ctypes
        import os
        import signal

        if ctypes.CDLL(None).prctl(1, signal.SIGKILL) != 0 or os.getppid() != data["parent_pid"]:
            raise RuntimeError("requalification supervisor unavailable")
    try:
        result = run(data)
    except Exception as exc:  # noqa: BLE001 - the parent records a code, never a trace
        code = getattr(exc, "code", None)
        if not isinstance(code, str) or not _CODE.fullmatch(code):
            code = "ML_ARTIFACT_UNLOADABLE"
        _write(destination, {"error": {"code": code}})
        return 3
    _write(destination, result)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
