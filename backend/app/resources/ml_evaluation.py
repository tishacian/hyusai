"""Portable evaluation provenance, stored in Hyusai's existing artifact plane."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import math
import numbers
from collections import Counter
from datetime import date, datetime
from pathlib import Path

SCHEMA = 1
FILENAME = "evaluation.json.gz"
MAX_BYTES = 128 * 1024 * 1024
MAX_JSON_BYTES = 192 * 1024 * 1024


def _cell(value):
    import pandas as pd

    if value is None or value is pd.NA or value is pd.NaT:
        return ["null"]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, numbers.Integral):
        return ["number", str(int(value))]
    if isinstance(value, numbers.Real):
        value = float(value)
        if math.isnan(value):
            return ["null"]
        if value.is_integer():
            return ["number", str(int(value))]
        return ["number", value.hex()]
    if isinstance(value, (datetime, date)):
        return ["date", value.isoformat()]
    if isinstance(value, str):
        return ["text", value]
    raise ValueError(f"Unsupported provenance cell type: {type(value).__name__}")


def row_ids(frame, columns: list[str]) -> list[str]:
    """Identify contents independently of pandas indices and physical row order."""
    prefix = json.dumps(columns, ensure_ascii=False, separators=(",", ":"))
    return [
        hashlib.sha256(
            (
                prefix
                + json.dumps(
                    [_cell(value) for value in row], ensure_ascii=False, separators=(",", ":")
                )
            ).encode("utf-8")
        ).hexdigest()
        for row in frame[columns].itertuples(index=False, name=None)
    ]


def fingerprint(ids: list[str]) -> str:
    """Fingerprint a multiset, retaining duplicate counts but ignoring ordering."""
    digest = hashlib.sha256()
    for key, count in sorted(Counter(ids).items()):
        digest.update(f"{key}:{count}\n".encode("ascii"))
    return digest.hexdigest()


def prepare(
    frame,
    *,
    columns,
    train_indices,
    test_indices,
    dataset,
    target,
    seed,
    test_size,
    positive_class=None,
):
    """Describe exactly the usable rows and the recorded train/final-test split."""
    columns = sorted(set(columns))
    ids = row_ids(frame, columns)
    by_index = dict(zip(frame.index, ids, strict=True))
    if len(by_index) != len(frame):
        raise ValueError("Provenance needs a unique physical index")
    train = [by_index[index] for index in train_indices]
    test = [by_index[index] for index in test_indices]
    if len(train) + len(test) != len(ids) or set(train_indices) & set(test_indices):
        raise ValueError("Invalid evaluation partition")
    metadata = {
        "schema": SCHEMA,
        "identity": "sha256-typed-cells-v1",
        "dataset": dict(dataset or {}),
        "columns": columns,
        "target": target,
        "fingerprint": fingerprint(ids),
        "random_state": seed,
        "test_size": test_size,
        "strategy": "random_holdout",
        "rows": {"total": len(ids), "train": len(train), "test": len(test)},
        "positive_class": positive_class,
        "role": "final_test",
        "duplicate_overlap": len(set(train) & set(test)),
    }
    return {**metadata, "train_ids": train, "test_ids": test}


def write_partition(payload, path):
    """Write a bounded temporary artifact; the worker transfers its existing key."""
    encoded = gzip.compress(
        json.dumps(payload, separators=(",", ":"), allow_nan=False).encode(), mtime=0
    )
    if len(encoded) > MAX_BYTES:
        raise ValueError("Evaluation partition exceeds its byte ceiling")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".partial")
    temporary.write_bytes(encoded)
    temporary.replace(target)
    return {
        key: value for key, value in payload.items() if key not in {"train_ids", "test_ids"}
    } | {
        "status": "recorded",
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "bytes": len(encoded),
    }


def read_partition(encoded: bytes, *, sha256: str):
    """Read JSON evidence with size/digest/schema validation, never pickle."""
    if len(encoded) > MAX_BYTES or hashlib.sha256(encoded).hexdigest() != sha256:
        raise ValueError("Evaluation artifact digest/size mismatch")
    with gzip.GzipFile(fileobj=io.BytesIO(encoded)) as stream:
        raw = stream.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError("Evaluation artifact expands beyond its byte ceiling")
    payload = json.loads(raw)
    if payload.get("schema") != SCHEMA or payload.get("identity") != "sha256-typed-cells-v1":
        raise ValueError("Unsupported evaluation schema")
    ids = payload.get("train_ids", []) + payload.get("test_ids", [])
    if not ids or any(not isinstance(key, str) or len(key) != 64 for key in ids):
        raise ValueError("Invalid evaluation row identifiers")
    if fingerprint(ids) != payload.get("fingerprint"):
        raise ValueError("Evaluation partition fingerprint mismatch")
    return payload


def shared_holdout(frame, partitions):
    """Return a deterministic intersection excluding every model's training rows."""
    candidates = set(range(len(frame)))
    order = None
    for partition in partitions:
        ids = row_ids(frame, partition["columns"])
        if fingerprint(ids) != partition["fingerprint"]:
            raise ValueError("Dataset contents changed since evaluation")
        trained = set(partition["train_ids"])
        tested = set(partition["test_ids"]) - trained
        candidates &= {index for index, key in enumerate(ids) if key in tested}
        if order is None:
            order = ids
    if not candidates:
        raise ValueError("No provably unseen rows shared by these models")
    # Equivalent duplicates are ordered by content; their multiplicity is retained.
    selected = sorted(candidates, key=lambda index: order[index])
    return frame.iloc[selected].copy()
