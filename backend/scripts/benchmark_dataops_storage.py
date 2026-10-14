#!/usr/bin/env python3
"""Opt-in synthetic multipart storage qualification against a local MinIO fixture.

No production credentials, dataset rows or manifests are synthesized. This probes
physical Delta writing/streaming, independently of a registered dataset profile.
The caller may additionally request real bounded production profiling.
"""

from __future__ import annotations

import argparse
import json
import resource
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--gib", type=float, default=3.01)
    parser.add_argument("--profile", action="store_true")
    args = parser.parse_args()
    import numpy as np
    import pyarrow as pa

    from app.core.config import settings
    from app.resources.dataops_storage import PartWriter
    from app.services.dataops.storage import (
        dataset_digest,
        file_digest,
        materialize_files,
        open_dataset_arrow,
        persist_sample,
        profile_files,
    )
    from app.services.object_store import get_object_store

    cfg = json.loads((args.fixture_dir / "container.json").read_text())
    secret = json.loads((args.fixture_dir / "credentials.json").read_text())
    settings.object_store_backend = "s3"
    settings.object_store_s3_endpoint_url = cfg["endpoint"]
    settings.object_store_s3_bucket = "d3-qualification"
    settings.object_store_s3_access_key = secret["app_user"]
    settings.object_store_s3_secret_key = secret["app_secret"]
    settings.dataops_max_input_mb = max(settings.dataops_max_input_mb, 4096)
    settings.dataops_sql_timeout_s = 900
    # These are explicit benchmark budgets, recorded in the report.
    target = int(args.gib * 1024**3)
    report = {
        "synthetic": True,
        "minio_release": "RELEASE.2025-04-22T22-12-26Z",
        "target_bytes": target,
        "profile_requested": args.profile,
        "budgets": {
            "rss_mb": 4096,
            "duckdb_memory_mb": settings.dataops_duckdb_memory_mb,
            "spill_mb": settings.dataops_spill_max_mb,
            "profile_timeout_s": 900,
            "profile_threads": 1,
        },
    }

    def checkpoint(phase):
        report["phase"] = phase
        report["elapsed_seconds"] = round(time.monotonic() - start, 3)
        report["cgroup"] = {
            name: path.read_text().strip()
            for name in ("memory.max", "memory.peak", "memory.events", "cpu.max")
            if (path := Path("/sys/fs/cgroup") / name).is_file()
        }
        temporary = args.report.with_suffix(".pending.json")
        temporary.write_text(json.dumps(report, indent=2))
        temporary.replace(args.report)

    start = time.monotonic()
    report["status"] = "running"
    checkpoint("writing")
    with tempfile.TemporaryDirectory(prefix="d3-volume-") as scratch:
        root = Path(scratch)
        schema = pa.schema([("id", pa.int64()), ("payload", pa.binary(4096))])
        writer = PartWriter(root / "delta", schema, target_bytes=128 * 1024**2)
        rng = np.random.default_rng(20261013)
        count = 0
        while writer.size_bytes < target:
            size = 4096
            payload = rng.bytes(size * 4096)
            values = pa.Array.from_buffers(pa.binary(4096), size, [None, pa.py_buffer(payload)])
            batch = pa.record_batch(
                [pa.array(np.arange(count, count + size)), values], schema=schema
            )
            writer.write_batch(batch)
            count += size
        writer.close()
        report.update(
            rows=count,
            parts=len(writer.paths),
            actual_bytes=writer.size_bytes,
            write_seconds=round(time.monotonic() - start, 3),
        )
        checkpoint("uploading")
        identifier = str(uuid4())
        prefix = f"workspaces/d3-volume/tabular/datasets/{identifier}"
        dataset = SimpleNamespace(
            id=identifier, workspace_id="d3-volume", storage_key=prefix + "/delta", lineage_json={}
        )
        store = get_object_store()
        hashes = {}
        stage = time.monotonic()
        for path in writer.paths:
            hashes[path.name] = file_digest(path)
            store.write_file(f"{dataset.storage_key}/{path.name}", path)
        log = writer.directory / "_delta_log/00000000000000000000.json"
        actions = [json.loads(line) for line in log.read_text().splitlines()]
        commit = next(action["commitInfo"] for action in actions if "commitInfo" in action)
        assert commit["operation"] == "CONVERT"
        assert commit["engineInfo"].startswith("delta-rs:")
        report["writer"] = {
            "operation": commit["operation"],
            "engine_info": commit["engineInfo"],
            "client_version": commit["clientVersion"],
            "commit_versions": [path.name for path in log.parent.glob("*.json")],
            "log_bytes": log.stat().st_size,
            "parts_reencoded_during_commit": False,
        }
        store.write_once(
            f"{dataset.storage_key}/_delta_log/00000000000000000000.json", log.read_bytes()
        )
        dataset.lineage_json = {"storage": {"parts": hashes, "log_sha256": file_digest(log)}}
        sample_started = time.monotonic()
        persist_sample(dataset, writer.paths)
        report["sample_seconds"] = round(time.monotonic() - sample_started, 3)
        sample = dataset.lineage_json["sample"]
        report["sample"] = {
            key: sample[key] for key in ("method", "seed", "rows", "size_bytes", "sha256")
        }
        report["upload_seconds"] = round(time.monotonic() - stage, 3)
        report["commit_digest"] = dataset_digest(dataset)
        checkpoint("reading")
        store.write_bytes(f"{dataset.storage_key}/orphan.parquet", b"uncommitted")
        stage = time.monotonic()
        arrow = open_dataset_arrow(dataset)
        rows = 0
        for batch in arrow.scanner(
            columns=["id"],
            batch_size=65536,
            use_threads=False,
            batch_readahead=0,
            fragment_readahead=0,
        ).to_batches():
            rows += batch.num_rows
        assert rows == count
        report["projected_read_seconds"] = round(time.monotonic() - stage, 3)
        checkpoint("downloading")
        stage = time.monotonic()
        copies = materialize_files(dataset, root / "download", max_bytes=4 * 1024**3)
        assert len(copies) == len(writer.paths)
        assert all(file_digest(path) == hashes[path.name] for path in copies)
        report["verified_download_seconds"] = round(time.monotonic() - stage, 3)
        report["download_sha256_verified"] = True
        report["orphan_ignored"] = True
        report["sample_bytes"] = dataset.lineage_json["sample"]["size_bytes"]
        checkpoint("profiling" if args.profile else "completed")
        if args.profile:
            stage = time.monotonic()
            try:
                profile = profile_files(writer.paths)
                assert profile["row_count"] == count
                report["profile"] = {
                    "status": "passed",
                    "rows": profile["row_count"],
                    "columns": profile["column_count"],
                }
            except Exception as exc:
                report["profile"] = {
                    "status": "refused",
                    "code": str(exc) if isinstance(exc, ValueError) else type(exc).__name__,
                }
            report["profile_seconds"] = round(time.monotonic() - stage, 3)
        report["status"] = (
            "passed"
            if not args.profile or report["profile"]["status"] == "passed"
            else "profile_refused"
        )
    report["total_seconds"] = round(time.monotonic() - start, 3)
    report["self_peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 3)
    report["children_peak_rss_mb"] = round(
        resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024, 3
    )
    checkpoint("completed")
    print(json.dumps(report))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
