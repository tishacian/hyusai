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


class _ChunkSink:
    """Forward-only Arrow sink drained after each bounded record batch."""

    def __init__(self, max_bytes):
        self.position = 0
        self.chunks = []
        self.closed = False
        self.max_bytes = max_bytes

    def writable(self):
        return True

    def tell(self):
        return self.position

    def write(self, data):
        self.position += len(data)
        if self.position > self.max_bytes:
            raise ValueError("DATASET_EXPORT_BUDGET_EXCEEDED")
        # Copy Arrow-owned buffers before the producer can reuse them.
        self.chunks.append(bytes(data))
        return len(data)

    def flush(self):
        pass

    def close(self):
        self.closed = True

    def drain(self):
        chunks, self.chunks = self.chunks, []
        yield from chunks


def stream_dataset(dataset, *, format: str, arrow=None):
    """Generate CSV or one portable Parquet without a consolidated scratch file.

    The Parquet writer is forward-only. The HTTP response yields between batches,
    so consumer backpressure also bounds reading and encoding of the next batch.
    """
    import pyarrow.csv as csv
    import pyarrow.parquet as pq

    from app.services.dataops.storage import open_dataset_arrow

    if format not in {"csv", "parquet"}:
        raise ValueError("DATASET_EXPORT_FORMAT_INVALID")
    arrow = arrow if arrow is not None else open_dataset_arrow(dataset)
    sink = _ChunkSink(settings.dataops_max_output_mb * 1024**2)
    writer = (
        pq.ParquetWriter(sink, arrow.schema, compression="zstd")
        if format == "parquet"
        else csv.CSVWriter(sink, arrow.schema)
    )
    try:
        yield from sink.drain()
        scanner = arrow.scanner(
            batch_size=min(settings.dataops_batch_rows, 1024),
            use_threads=False,
            batch_readahead=0,
            fragment_readahead=0,
        )
        for batch in scanner.to_batches():
            writer.write_batch(batch)
            yield from sink.drain()
        writer.close()
        yield from sink.drain()
    finally:
        writer.close()
        sink.close()
