"""Resolve an immutable export only through its committed pointer and manifest."""

import hashlib
import json
from uuid import UUID

from app.services.connectors.adapters.object_clients import object_key
from app.services.connectors.adapters.sql import AdapterError


def published_objects(client, prefix, objects):
    pointer_key = prefix.rstrip("/") + "/_LATEST.json"
    listing = {item["key"]: item for item in objects}
    if pointer_key not in listing:
        return None
    raw, _ = client.read_small(pointer_key)
    try:
        pointer = json.loads(raw)
        operation_id = str(UUID(pointer["operation_id"]))
        manifest_key = f"{prefix.rstrip('/')}/v={operation_id}/manifest.json"
        if pointer["manifest"] != manifest_key:
            raise ValueError("manifest")
        body, _ = client.read_small(manifest_key)
        if hashlib.sha256(body).hexdigest() != pointer["sha256"]:
            raise ValueError("hash")
        manifest = json.loads(body)
        if manifest["operation_id"] != operation_id or len(manifest["parts"]) > 10000:
            raise ValueError("operation")
        result = []
        seen = set()
        for part in manifest["parts"]:
            key = object_key(part["key"], f"{prefix.rstrip('/')}/v={operation_id}")
            if not key.endswith(".parquet") or key in seen:
                raise ValueError("part")
            seen.add(key)
            item = listing.get(key)
            if item is None or item["size"] != part["bytes"]:
                raise AdapterError("CONNECTOR_SOURCE_CHANGED")
            result.append({**item, "expected_sha256": part["sha256"]})
        if not result:
            raise ValueError("empty")
        return result
    except (ValueError, KeyError, TypeError):
        raise AdapterError("CONNECTOR_MANIFEST_INVALID") from None
