"""Stream OCI archives; never extract or load their layers into Docker.

The graphdriver comparison follows Moby 28.4.0's UnpackLayer hdr.Size sum,
ApplyDiff result, and cumulative roLayer.Size. It is an estimate of that
specific accounting algorithm from real layer bytes, not a daemon inspect.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import tarfile
import time
from pathlib import Path
from typing import BinaryIO

MIB = 1024**2
JSON_LIMIT = 8 * MIB
BUDGETS_MIB = {"backend": 1400, "worker": 1760}
MANIFEST_TYPES = {
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
}
INDEX_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}


class CountedReader:
    def __init__(self, source: BinaryIO) -> None:
        self.source = source
        self.digest = hashlib.sha256()
        self.count = 0

    def read(self, size: int = -1) -> bytes:
        # Bound even a caller requesting all remaining bytes.
        data = self.source.read(MIB if size < 0 else min(size, MIB))
        self.digest.update(data)
        self.count += len(data)
        return data

    def drain(self) -> None:
        while self.read(MIB):
            pass

    def hexdigest(self) -> str:
        return "sha256:" + self.digest.hexdigest()


def _blob_path(digest: str) -> str:
    algorithm, value = digest.split(":", 1)
    if algorithm != "sha256" or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("unsupported or malformed OCI digest")
    return f"blobs/sha256/{value}"


def _open_blob(archive: tarfile.TarFile, descriptor: dict) -> BinaryIO:
    member = archive.getmember(_blob_path(descriptor["digest"]))
    if not member.isfile() or member.size != descriptor["size"]:
        raise ValueError("OCI blob file type or size mismatch")
    result = archive.extractfile(member)
    if result is None:
        raise ValueError("missing OCI blob")
    return result


def _json_blob(archive: tarfile.TarFile, descriptor: dict) -> dict:
    if descriptor["size"] > JSON_LIMIT:
        raise ValueError("OCI JSON exceeds inspection limit")
    with _open_blob(archive, descriptor) as source:
        data = source.read(JSON_LIMIT + 1)
    if len(data) != descriptor["size"] or "sha256:" + hashlib.sha256(data).hexdigest() != descriptor["digest"]:
        raise ValueError("OCI JSON digest mismatch")
    result = json.loads(data)
    if not isinstance(result, dict):
        raise ValueError("OCI JSON object required")
    return result


def _manifests(archive: tarfile.TarFile, descriptor: dict, depth: int = 0) -> list[tuple[dict, dict]]:
    if depth > 3:
        raise ValueError("OCI index nesting limit exceeded")
    if descriptor.get("annotations", {}).get("vnd.docker.reference.type") == "attestation-manifest":
        return []
    data = _json_blob(archive, descriptor)
    media_type = descriptor.get("mediaType", data.get("mediaType"))
    if media_type in INDEX_TYPES:
        return [item for child in data["manifests"] for item in _manifests(archive, child, depth + 1)]
    if media_type not in MANIFEST_TYPES:
        raise ValueError("unsupported OCI manifest type")
    return [(descriptor, data)]


def _layer(archive: tarfile.TarFile, descriptor: dict, expected_diff_id: str) -> dict:
    with _open_blob(archive, descriptor) as source:
        compressed = CountedReader(source)
        media_type = descriptor["mediaType"]
        decoder = None
        if media_type.endswith("+gzip") or media_type.endswith(".gzip"):
            decoder = gzip.GzipFile(fileobj=compressed, mode="rb")
        elif media_type.endswith("+zstd"):
            import zstandard

            decoder = zstandard.ZstdDecompressor().stream_reader(compressed, closefd=False)
        elif media_type.endswith(".tar"):
            decoder = compressed
        else:
            raise ValueError("unsupported OCI layer compression")
        unpacked = CountedReader(decoder)
        entry_count = payload_bytes = 0
        with tarfile.open(fileobj=unpacked, mode="r|") as layer_tar:
            for member in layer_tar:
                if member.issparse():
                    raise ValueError("sparse layer requires dedicated Docker accounting validation")
                entry_count += 1
                payload_bytes += member.size
        # Include tar padding/end markers in diff_id, as Docker does.
        unpacked.drain()
        if decoder is not compressed:
            decoder.close()
        compressed.drain()
        if compressed.count != descriptor["size"] or compressed.hexdigest() != descriptor["digest"]:
            raise ValueError("OCI layer compressed digest mismatch")
        if unpacked.hexdigest() != expected_diff_id:
            raise ValueError("OCI layer uncompressed diff_id mismatch")
        return {
            "digest": descriptor["digest"],
            "diff_id": expected_diff_id,
            "compressed_bytes": compressed.count,
            "uncompressed_tar_bytes": unpacked.count,
            "tar_entry_payload_bytes": payload_bytes,
            "tar_entries": entry_count,
            "media_type": media_type,
            "integrity": "verified",
        }


def measure(name: str, path: Path) -> dict:
    started = time.monotonic()
    with tarfile.open(path, mode="r:") as archive:
        index_member = archive.getmember("index.json")
        if not index_member.isfile() or index_member.size > JSON_LIMIT:
            raise ValueError("invalid OCI index")
        with archive.extractfile(index_member) as source:
            index = json.load(source)
        candidates = []
        for descriptor in index["manifests"]:
            for manifest_descriptor, manifest in _manifests(archive, descriptor):
                config = _json_blob(archive, manifest["config"])
                if (config.get("os"), config.get("architecture")) == ("linux", "amd64"):
                    candidates.append((manifest_descriptor, manifest, config))
        if len(candidates) != 1:
            raise ValueError("exactly one linux/amd64 image required")
        descriptor, manifest, config = candidates[0]
        diff_ids = config["rootfs"]["diff_ids"]
        if len(diff_ids) != len(manifest["layers"]):
            raise ValueError("OCI layer and diff_id counts disagree")
        layers = [_layer(archive, layer, diff_id) for layer, diff_id in zip(manifest["layers"], diff_ids, strict=True)]
    comparable_bytes = sum(layer["tar_entry_payload_bytes"] for layer in layers)
    budget = BUDGETS_MIB[name]
    return {
        "image": name,
        "archive_path": str(path.resolve()),
        "oci_archive_bytes": path.stat().st_size,
        "manifest_digest": descriptor["digest"],
        "config_digest": manifest["config"]["digest"],
        "revision": config.get("config", {}).get("Labels", {}).get("org.opencontainers.image.revision"),
        "platform": "linux/amd64",
        "compressed_layer_bytes": sum(layer["compressed_bytes"] for layer in layers),
        "uncompressed_layer_tar_bytes": sum(layer["uncompressed_tar_bytes"] for layer in layers),
        "docker_graphdriver_comparable_size_bytes": comparable_bytes,
        "docker_graphdriver_comparable_size_mib_floor": comparable_bytes // MIB,
        "budget_mib": budget,
        "budget_verdict_for_graphdriver_comparable_size": "OVER" if comparable_bytes // MIB > budget else "ok",
        "seconds": round(time.monotonic() - started, 3),
        "layers": layers,
    }


def write_report(path: Path, report: dict) -> None:
    staging = path.with_suffix(path.suffix + ".tmp")
    staging.write_text(json.dumps(report, indent=2) + "\n")
    staging.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", action="append", required=True, help="backend=/absolute/image.oci.tar or worker=...")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = {
        "status": "running",
        "measurement": "streamed OCI layer bytes; no docker load or extraction",
        "budget_source": "scripts/agentium-vm-build.sh defaults; scripts/agentium-image-budget.sh integer MiB floor",
        "size_accounting": "Moby 28.4.0 classic graphdriver: sum hdr.Size per tar layer, then sum all layers",
        "size_accounting_sources": [
            "https://github.com/moby/moby/blob/v28.4.0/vendor/github.com/moby/go-archive/diff.go",
            "https://github.com/moby/moby/blob/v28.4.0/daemon/graphdriver/fsdiff.go",
            "https://github.com/moby/moby/blob/v28.4.0/layer/layer_store.go",
            "https://github.com/moby/moby/blob/v28.4.0/layer/ro_layer.go",
        ],
        "limits": [
            "Not an actual docker image inspect on the deployment VM; its image-store accounting may differ.",
            "Compressed archive size alone is never a budget verdict.",
            "No runtime, frontend, optional image, VM, or deployment qualification is implied.",
            "No overall release budget verdict: only the images explicitly listed here are inspected.",
        ],
        "images": [],
    }
    write_report(args.report, report)
    try:
        seen = set()
        for item in args.image:
            name, image_path = item.split("=", 1)
            if name not in BUDGETS_MIB or name in seen:
                raise ValueError("invalid or duplicate image name")
            seen.add(name)
            report["images"].append(measure(name, Path(image_path)))
            write_report(args.report, report)
        if seen == {"backend", "worker"}:
            by_name = {image["image"]: image for image in report["images"]}
            a = by_name["backend"]["layers"]
            b = by_name["worker"]["layers"]
            shared = {layer["diff_id"] for layer in a} & {layer["diff_id"] for layer in b}
            prefix = 0
            for left, right in zip(a, b):
                if left["diff_id"] != right["diff_id"]:
                    break
                prefix += 1
            report["shared_layers"] = {
                "diff_ids": sorted(shared),
                "count": len(shared),
                "common_prefix_count": prefix,
                "required_minimum": 5,
                "verdict": "ok" if len(shared) >= 5 else "insufficient",
            }
        report["status"] = "measured"
    except Exception as exc:
        report["status"] = "failed"
        report["error_type"] = type(exc).__name__
        report["error"] = str(exc)
        write_report(args.report, report)
        raise
    write_report(args.report, report)
    print(json.dumps({"status": report["status"], "report": str(args.report), "images": [
        {key: image[key] for key in ("image", "compressed_layer_bytes", "uncompressed_layer_tar_bytes", "docker_graphdriver_comparable_size_bytes", "budget_mib", "budget_verdict_for_graphdriver_comparable_size")}
        for image in report["images"]
    ]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
