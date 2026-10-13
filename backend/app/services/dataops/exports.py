"""Portable exports verify bytes and preserve immutable delivery evidence."""

import hashlib
import json
import zipfile
from pathlib import Path

from app.core.config import settings
from app.services.object_store import get_object_store


def receipt_bundle(asset, receipt, destination: Path):
    objects = asset.manifest_json.get("objects", [])
    ceiling = settings.dataops_max_output_mb * 1024**2
    if sum(o["size_bytes"] for o in objects) > ceiling:
        raise ValueError("DELIVERY_EXPORT_BUDGET_EXCEEDED")
    store = get_object_store()
    index = []
    with zipfile.ZipFile(
        destination, "x", compression=zipfile.ZIP_STORED, allowZip64=True
    ) as archive:
        for n, obj in enumerate(objects):
            name = f"objects/{n:06d}-{obj['sha256']}"
            source = (
                store._local_path(obj["key"]).open("rb")
                if store.backend == "local"
                else store._fsspec().open(store._remote_key(obj["key"]), "rb")
            )
            digest = hashlib.sha256()
            count = 0
            with source as handle, archive.open(name, "w", force_zip64=True) as target:
                while chunk := handle.read(1024**2):
                    count += len(chunk)
                    if count > obj["size_bytes"]:
                        raise ValueError("DELIVERY_EXPORT_OBJECT_CHANGED")
                    digest.update(chunk)
                    target.write(chunk)
            if count != obj["size_bytes"] or digest.hexdigest() != obj["sha256"]:
                raise ValueError("DELIVERY_EXPORT_OBJECT_CHANGED")
            index.append({**obj, "bundle_path": name})
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "asset_ref": {
                        "asset_id": asset.id,
                        "workspace_id": asset.workspace_id,
                        "kind": asset.kind,
                        "version": asset.version,
                        "digest": asset.digest,
                    },
                    "manifest": asset.manifest_json,
                    "parents": asset.parents_json,
                    "objects": index,
                    "receipt": receipt,
                },
                sort_keys=True,
                default=str,
            ),
        )
    return destination
