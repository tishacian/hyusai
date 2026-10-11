"""Isolated challenger prediction, invoked only with a server-created manifest."""

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace


def main(source, destination):
    data = json.loads(Path(source).read_text(encoding="utf-8"))
    # The supervisor owns the wall-clock deadline. If its worker is killed,
    # don't leave a detached native fit/download alive beyond the job lease.
    if sys.platform == "linux":
        import ctypes
        import os
        import signal

        if ctypes.CDLL(None).prctl(1, signal.SIGKILL) != 0 or os.getppid() != data["parent_pid"]:
            raise RuntimeError("shadow supervisor unavailable")
    from app.services.ml.artifacts import validate_inventory, verify_model_bundle
    from app.services.tabular_ml import download_model_dir
    from app.services.tabular_predict import (
        _classes_of,
        _load_mlflow_model,
        _positive_label,
        _predict_frame,
        _rows_from,
        build_frame,
        coerce_rows,
        contract_fields,
    )

    model = SimpleNamespace(**data["model"])
    directory = Path(destination).parent / "artifact"
    load_started = time.monotonic()
    artifact = (model.metrics_json or {}).get("artifact") or {}
    limit = min(int(data["max_artifact_bytes"]), 256 * 1024 * 1024)
    # Bound the complete anchored inventory before any I/O. The shared
    # downloader then enforces each recorded size while streaming, and checks
    # the workspace/model namespace. Missing anchors are never synthesized.
    validate_inventory(artifact, max_bytes=limit)
    download_model_dir(model, directory)
    verify_model_bundle(directory, artifact, family=model.family, max_bytes=limit)
    pipeline = _load_mlflow_model(directory)
    classes = _classes_of(model, pipeline)
    fields = contract_fields(model)
    names = [field["name"] for field in fields]
    rows = coerce_rows(model, [{key: row[key] for key in names} for row in data["rows"]])
    frame = build_frame(fields, rows)
    load_ms = (time.monotonic() - load_started) * 1000
    start = time.monotonic()
    predicted, probabilities = _predict_frame(SimpleNamespace(pipeline=pipeline), model, frame)
    answers = _rows_from(model, classes, _positive_label(model, classes), predicted, probabilities)
    result = {
        "predictions": answers,
        "duration_ms": round((time.monotonic() - start) * 1000, 2),
        "load_ms": round(load_ms, 2),
    }
    Path(destination).write_text(json.dumps(result, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
