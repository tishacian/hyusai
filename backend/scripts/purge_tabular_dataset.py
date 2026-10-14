#!/usr/bin/env python3
"""Run one authorized dataset purge with the dedicated tabular-purge identity.

Run outside API/worker common environment. Never accepts an arbitrary prefix.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def deletion_adapter():
    from app.core.config import settings
    from app.services.object_store import get_object_store

    if settings.object_store_backend == "local":
        store = get_object_store()

        def remove_local(prefix):
            root = store._local_path(prefix)
            count = sum(1 for p in root.rglob("*") if p.is_file()) if root.exists() else 0
            store.delete_prefix(prefix)
            return count

        return remove_local
    if settings.object_store_backend != "s3":
        raise ValueError("DATASET_PURGE_BACKEND_UNSUPPORTED")
    access = os.environ.get("HF_TABULAR_PURGE_ACCESS_KEY")
    secret = os.environ.get("HF_TABULAR_PURGE_SECRET_KEY")
    if not access or not secret or access == settings.object_store_s3_access_key:
        raise ValueError("DATASET_PURGE_DEDICATED_IDENTITY_REQUIRED")
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=settings.object_store_s3_endpoint_url,
        aws_access_key_id=access,
        aws_secret_access_key=secret,
    )
    bucket = settings.object_store_s3_bucket

    def remove_s3(prefix):
        count = 0
        # Versioned objects and delete markers both retain storage/history.
        # Iterate fixed-size pages; delete exact versions, including null versions.
        for page in client.get_paginator("list_object_versions").paginate(
            Bucket=bucket, Prefix=prefix
        ):
            entries = [*page.get("Versions", []), *page.get("DeleteMarkers", [])]
            for entry in entries:
                if not entry["Key"].startswith(prefix):
                    raise ValueError("DATASET_PURGE_SCOPE_VIOLATION")
                client.delete_object(Bucket=bucket, Key=entry["Key"], VersionId=entry["VersionId"])
                count += 1
        return count

    return remove_s3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    from app.db.base import SessionLocal
    from app.services.dataops.purge import purge_job

    with SessionLocal() as db:
        job = purge_job(db, args.job_id, delete_prefix=deletion_adapter())
        db.commit()
        print(json.dumps({"job_id": job.id, "status": job.status, "result": job.result}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # SDK exception strings can contain credential/endpoint data.
        print(
            json.dumps(
                {"code": getattr(exc, "code", "DATASET_PURGE_FAILED"), "type": type(exc).__name__}
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)
