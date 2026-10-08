"""Isolated challenger prediction, invoked only with a server-created manifest."""
import json
from pathlib import Path
import sys
import time
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
    from app.services.tabular_predict import (
        _classes_of, _load_mlflow_model, _positive_label, _predict_frame,
        _rows_from, build_frame, coerce_rows, contract_fields,
    )
    from app.services.object_store import get_object_store

    model = SimpleNamespace(**data["model"])
    store = get_object_store()
    prefix = model.model_uri.rstrip("/") + "/"
    directory = Path(destination).parent / "artifact"
    directory.mkdir()
    total = 0
    load_started = time.monotonic()
    for key in store.list_keys(model.model_uri):
        if not key.startswith(prefix):
            raise ValueError("invalid artifact prefix")
        relative = Path(key[len(prefix):])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("invalid artifact path")
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        store.copy_to_local(key, target)
        total += target.stat().st_size
        if total > data["max_artifact_bytes"]:
            raise ValueError("artifact too large")
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
    result = {"predictions": answers, "duration_ms": round((time.monotonic() - start) * 1000, 2),
              "load_ms": round(load_ms, 2)}
    Path(destination).write_text(json.dumps(result, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
