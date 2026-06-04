"""One-off migration: mirror the local object store into the S3/MinIO bucket.

Context
-------
SPL wave imports (V1/V2/V3) were promoted from the host virtualenv, where the
object store is configured with ``OBJECT_STORE_BACKEND=local`` (files land under
``backend/data/object_store``). The live API runs in Docker with
``OBJECT_STORE_BACKEND=s3`` (MinIO). As a result the original source files exist
on local disk but were never uploaded to MinIO, so the document preview endpoints
return "Source file not found".

This script reads every file from the local object store and uploads it to the
S3 bucket using the *same* key, so the Docker backend can resolve originals.

It is idempotent: by default existing objects are skipped (use --overwrite to
force re-upload).

Usage (host venv, MinIO exposed on 127.0.0.1:9000)::

    OBJECT_STORE_S3_ENDPOINT_URL=http://127.0.0.1:9000 \
    OBJECT_STORE_S3_BUCKET=agentium-artifacts \
    OBJECT_STORE_S3_ACCESS_KEY=agentium \
    OBJECT_STORE_S3_SECRET_KEY=*** \
    python scripts/migrate_local_object_store_to_s3.py [--prefix workspaces/...] [--overwrite] [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from app.core.config import settings


def _require(name: str, fallback: str | None = None) -> str:
    value = os.getenv(name) or fallback
    if not value:
        sys.exit(f"Missing required environment variable: {name}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default="", help="Only migrate keys under this prefix")
    parser.add_argument("--overwrite", action="store_true", help="Re-upload even if the key exists")
    parser.add_argument("--dry-run", action="store_true", help="List actions without uploading")
    parser.add_argument("--batch-log", type=int, default=200, help="Log every N files")
    args = parser.parse_args()

    try:
        import fsspec  # type: ignore
    except ImportError:
        sys.exit("fsspec/s3fs is required. Install with: pip install s3fs")

    base = Path(settings.object_store_base_path).resolve()
    if not base.exists():
        sys.exit(f"Local object store base path does not exist: {base}")

    endpoint = _require("OBJECT_STORE_S3_ENDPOINT_URL", settings.object_store_s3_endpoint_url)
    bucket = _require("OBJECT_STORE_S3_BUCKET", settings.object_store_s3_bucket)
    access = _require("OBJECT_STORE_S3_ACCESS_KEY", settings.object_store_s3_access_key)
    secret = _require("OBJECT_STORE_S3_SECRET_KEY", settings.object_store_s3_secret_key)

    fs = fsspec.filesystem(
        "s3",
        key=access,
        secret=secret,
        client_kwargs={"endpoint_url": endpoint},
    )

    if not fs.exists(bucket):
        print(f"Creating bucket {bucket}")
        if not args.dry_run:
            fs.mkdir(bucket)

    prefix = args.prefix.strip("/")
    root = base / prefix if prefix else base
    files = [p for p in root.rglob("*") if p.is_file()]
    print(f"Scanning {root} -> {len(files)} files, target bucket s3://{bucket} @ {endpoint}")

    uploaded = skipped = failed = 0
    for idx, path in enumerate(files, start=1):
        key = path.relative_to(base).as_posix()
        remote = f"{bucket}/{key}"
        try:
            if not args.overwrite and fs.exists(remote):
                skipped += 1
            else:
                if not args.dry_run:
                    parent = remote.rsplit("/", 1)[0]
                    fs.makedirs(parent, exist_ok=True)
                    with path.open("rb") as src, fs.open(remote, "wb") as dst:
                        dst.write(src.read())
                uploaded += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAILED {key}: {exc}")
        if idx % args.batch_log == 0:
            print(f"  ...{idx}/{len(files)} (uploaded={uploaded} skipped={skipped} failed={failed})")

    print(
        f"Done. total={len(files)} uploaded={uploaded} skipped={skipped} failed={failed}"
        + (" [dry-run]" if args.dry_run else "")
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
