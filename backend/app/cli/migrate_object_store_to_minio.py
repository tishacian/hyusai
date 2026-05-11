"""Mirror and verify the local ObjectStore against MinIO/S3."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.config import settings
from app.services.object_store_migration import (
    build_s3_filesystem,
    compare_manifests,
    ensure_s3_bucket,
    local_object_manifest,
    mirror_local_to_s3,
    s3_object_manifest,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Mirror local ObjectStore files to a MinIO/S3 bucket and verify strict parity.",
    )
    parser.add_argument("--source", default=settings.object_store_base_path)
    parser.add_argument("--bucket", default=settings.object_store_s3_bucket)
    parser.add_argument("--endpoint-url", default=settings.object_store_s3_endpoint_url)
    parser.add_argument("--access-key", default=settings.object_store_s3_access_key)
    parser.add_argument("--secret-key", default=settings.object_store_s3_secret_key)
    parser.add_argument("--prefix", default="")
    parser.add_argument("--create-bucket", action="store_true")
    parser.add_argument("--apply", action="store_true", help="Write missing or mismatched objects.")
    parser.add_argument(
        "--mode",
        choices=("report", "mirror", "verify"),
        default="report",
        help="report prints manifests, mirror copies local objects to S3, verify exits non-zero on drift.",
    )
    return parser


def _require_bucket(bucket: str | None) -> str:
    if not bucket:
        raise SystemExit("OBJECT_STORE_S3_BUCKET or --bucket is required")
    return bucket


def main() -> None:
    args = _parser().parse_args()
    source = Path(args.source)
    bucket = _require_bucket(args.bucket)
    fs = build_s3_filesystem(
        endpoint_url=args.endpoint_url,
        access_key=args.access_key,
        secret_key=args.secret_key,
    )
    if args.create_bucket:
        ensure_s3_bucket(fs, bucket)

    if args.mode == "mirror":
        report = mirror_local_to_s3(
            source_base_path=source,
            fs=fs,
            bucket=bucket,
            prefix=args.prefix,
            dry_run=not args.apply,
        )
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return

    source_manifest = local_object_manifest(source, prefix=args.prefix)
    target_manifest = s3_object_manifest(fs, bucket, prefix=args.prefix)
    diff = compare_manifests(source_manifest, target_manifest)
    payload = {
        "source_count": len(source_manifest),
        "source_bytes": sum(entry.size for entry in source_manifest),
        "target_count": len(target_manifest),
        "target_bytes": sum(entry.size for entry in target_manifest),
        "diff": {
            "missing_target": diff.missing_target,
            "extra_target": diff.extra_target,
            "mismatched": diff.mismatched,
        },
        "strict_match": diff.strict_match,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    if args.mode == "verify" and not diff.strict_match:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
