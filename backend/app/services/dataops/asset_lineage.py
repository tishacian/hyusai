"""Join native dataset/model lineage to the common governed asset graph."""

from __future__ import annotations

import hashlib

from app.models.tabular import MLModel, TabularDataset
from app.services.dataops.storage import delta_manifest, is_delta
from app.services.governed_assets import GovernanceError, asset_ref, register_asset
from app.services.object_store import get_object_store


def objects(keys):
    store = get_object_store()
    result = []
    for key in keys:
        source = (
            store._local_path(key).open("rb")
            if store.backend == "local"
            else store._fsspec().open(store._remote_key(key), "rb")
        )
        digest = hashlib.sha256()
        size = 0
        with source as handle:
            while chunk := handle.read(1024**2):
                digest.update(chunk)
                size += len(chunk)
        result.append({"key": key, "sha256": digest.hexdigest(), "size_bytes": size})
    return result


def dataset_manifest(row):
    keys = (
        [f"{row.storage_key}/{part['path']}" for part in delta_manifest(row)["files"]]
        if is_delta(row)
        else [row.storage_key]
    )
    if is_delta(row):
        keys.append(f"{row.storage_key}/_delta_log/00000000000000000000.json")
    sample = (row.lineage_json or {}).get("sample")
    if sample:
        keys.append(sample["key"])
    return {
        "objects": objects(keys),
        "native_refs": [{"kind": "dataset", "id": row.id}],
        "schema": row.schema_json,
    }


def ensure_dataset_asset(db, workspace_id, dataset_id, *, seen=None):
    seen = set() if seen is None else seen
    if dataset_id in seen or len(seen) > 128:
        raise GovernanceError("ASSET_NATIVE_LINEAGE_INVALID")
    seen.add(dataset_id)
    row = (
        db.query(TabularDataset)
        .filter_by(id=dataset_id, workspace_id=workspace_id, status="ready")
        .first()
    )
    if row is None:
        raise GovernanceError("ASSET_NATIVE_REF_UNAVAILABLE")
    parents = [
        asset_ref(ensure_dataset_asset(db, workspace_id, parent, seen=seen))
        for parent in row.parent_ids or []
    ]
    model_id = (row.lineage_json or {}).get("model", {}).get("model_id")
    if model_id:
        model = db.query(MLModel).filter_by(id=model_id, workspace_id=workspace_id).first()
        if model is None:
            raise GovernanceError("ASSET_NATIVE_REF_UNAVAILABLE")
        manifest = {
            "native_refs": [{"kind": "model", "id": model.id}],
            "output": {"model_id": model.id, "version": model.version},
        }
        if model.model_uri and model.model_uri.startswith(f"workspaces/{workspace_id}/"):
            manifest["objects"] = objects(get_object_store().list_keys(model.model_uri))
        parents.append(
            asset_ref(
                register_asset(db, workspace_id, "model", f"native:model:{model.id}", manifest)
            )
        )
    result = register_asset(
        db,
        workspace_id,
        "dataset",
        f"native:dataset:{row.id}",
        dataset_manifest(row),
        parents=parents,
        run_id=row.run_id,
    )
    seen.remove(dataset_id)
    return result
