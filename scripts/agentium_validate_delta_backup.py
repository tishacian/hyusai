#!/usr/bin/env python3
"""Verify copied Delta/A1 bytes offline, before backup readiness or after restore.

The JSONL registry is exported beside the SQL dump while writers are suspended.
This verifier uses only Python's standard library and never contacts a service.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath

SHA256 = re.compile(r"[0-9a-f]{64}\Z")
NATIVE_FIELDS = {
    "dataset": ("version", "storage_key", "schema_json", "row_count"),
    "model": ("version", "model_uri", "signature_json", "runtime_json"),
    "document_set": (
        "active_generation",
        "artifact_prefix",
        "document_names",
        "embedding_model",
    ),
}


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _sha(value):
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ValueError("invalid SHA-256")
    return value


def _path(root, key, workspace_id=None):
    if not isinstance(key, str) or not key or "\\" in key or "\x00" in key:
        raise ValueError("invalid object key")
    rel = PurePosixPath(key)
    if rel.is_absolute() or ".." in rel.parts or str(rel) != key or key == ".":
        raise ValueError("unsafe object key")
    if workspace_id is not None and not key.startswith(f"workspaces/{workspace_id}/"):
        raise ValueError("object outside workspace")
    path = Path(root)
    for component in rel.parts:
        path /= component
        if path.is_symlink():
            raise ValueError("symlink refused")
    if not path.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError("unsafe resolved path")
    return path


def _file(path, sha256=None, size=None):
    if path.is_symlink() or not path.is_file():
        raise ValueError("missing object")
    if size is not None and (
        type(size) is not int or size < 0 or path.stat().st_size != size
    ):
        raise ValueError("object size mismatch")
    if sha256 is not None:
        _sha(sha256)
        actual = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                actual.update(chunk)
        if actual.hexdigest() != sha256:
            raise ValueError("object hash mismatch")
    return path


def validate(directory, *, log_sha256=None, parts=None):
    """Validate one immutable Delta version; registry mode requires its hashes."""
    root = Path(directory)
    if root.is_symlink():
        raise ValueError("symlink refused")
    log = _path(root, "_delta_log/00000000000000000000.json")
    _file(log, log_sha256)
    if log.stat().st_size > 16 * 1024**2:
        raise ValueError("Delta log too large")
    if any(p.name != log.name for p in log.parent.glob("[0-9]*.json")):
        raise ValueError("additional Delta commits refused")
    metadata = 0
    seen = set()
    for line in log.read_text().splitlines():
        action = json.loads(line)
        if not isinstance(action, dict):
            raise TypeError("invalid Delta action")
        if "metaData" in action:
            metadata += 1
        if "remove" in action:
            raise ValueError("mutable version refused")
        if "protocol" in action and action["protocol"].get("minReaderVersion", 1) > 1:
            raise ValueError("unsupported Delta protocol")
        if "add" not in action:
            continue
        part = action["add"]
        key = part["path"]
        if key in seen:
            raise ValueError("duplicate Delta part")
        seen.add(key)
        if parts is not None and key not in parts:
            raise ValueError("Delta part hash missing")
        _file(_path(root, key), parts[key] if parts is not None else None, part["size"])
    if metadata != 1 or (parts is not None and set(parts) != seen):
        raise ValueError("Delta metadata or part inventory mismatch")
    return True


def _rows(registry):
    if Path(registry).stat().st_size > 256 * 1024**2:
        raise ValueError("registry exceeds offline verification budget")
    rows = {}
    with Path(registry).open() as source:
        for line in source:
            if len(line.encode()) > 4 * 1024**2:
                raise ValueError("registry row too large")
            record = json.loads(line)
            kind, row = record["type"], record["row"]
            if kind not in {"dataset", "model", "document_set", "asset"}:
                raise ValueError("unknown registry type")
            identity = (kind, row["workspace_id"], row["id"])
            if identity in rows:
                raise ValueError("duplicate registry identity")
            rows[identity] = row
    return rows


def _asset_ref(row):
    return {
        "asset_id": row["id"],
        "workspace_id": row["workspace_id"],
        "kind": row["kind"],
        "version": row["version"],
        "digest": row["digest"],
    }


def validate_registry(objects_root, registry):
    root = Path(objects_root)
    if root.is_symlink():
        raise ValueError("symlink root refused")
    rows = _rows(registry)
    report = {
        "schema_version": 1,
        "status": "verified",
        "datasets": 0,
        "delta_versions": 0,
        "legacy_datasets_without_recorded_hash": 0,
        "assets": 0,
        "asset_objects": 0,
        "native_references": 0,
        "parent_references": 0,
    }
    edges = {}
    for (kind, workspace_id, identifier), row in rows.items():
        if kind == "dataset":
            storage = (row.get("lineage_json") or {}).get("storage") or {}
            key = row.get("storage_key")
            if not key:
                raise ValueError("ready dataset has no object")
            path = _path(root, key, workspace_id)
            if key.endswith("/delta"):
                log_sha = _sha(storage.get("log_sha256"))
                parts = storage.get("parts")
                if not isinstance(parts, dict):
                    raise ValueError("Delta part inventory missing")
                validate(path, log_sha256=log_sha, parts=parts)
                report["delta_versions"] += 1
            else:
                _file(path, storage.get("sha256"), row.get("size_bytes"))
                if not storage.get("sha256"):
                    report["legacy_datasets_without_recorded_hash"] += 1
            sample = (row.get("lineage_json") or {}).get("sample")
            if sample:
                _file(
                    _path(root, sample["key"], workspace_id),
                    _sha(sample["sha256"]),
                    sample["size_bytes"],
                )
            report["datasets"] += 1
        elif kind == "asset":
            if (
                row["kind"] not in {"dataset", "model", "document_set", "reference"}
                or type(row["version"]) is not int
                or row["version"] < 1
            ):
                raise ValueError("invalid asset version")
            body = {
                "workspace_id": workspace_id,
                "kind": row["kind"],
                "logical_key": row["logical_key"],
                "manifest": row["manifest_json"],
                "parents": row["parents_json"],
                "run_id": row.get("run_id"),
            }
            sha = _sha(row["digest"])
            if digest(body) != sha:
                raise ValueError("asset SQL manifest hash mismatch")
            if (
                row["manifest_key"]
                != f"workspaces/{workspace_id}/governed-assets/manifests/{sha}.json"
            ):
                raise ValueError("asset manifest key mismatch")
            expected = canonical(body)
            path = _file(
                _path(root, row["manifest_key"], workspace_id), sha, len(expected)
            )
            if path.read_bytes() != expected:
                raise ValueError("asset manifest bytes mismatch")
            manifest = body["manifest"]
            objects = manifest.get("objects", [])
            if not isinstance(objects, list) or len(objects) > 10000:
                raise ValueError("invalid asset objects")
            seen = set()
            for obj in objects:
                if obj["key"] in seen:
                    raise ValueError("duplicate asset object")
                seen.add(obj["key"])
                _file(
                    _path(root, obj["key"], workspace_id),
                    _sha(obj["sha256"]),
                    obj["size_bytes"],
                )
                report["asset_objects"] += 1
            parents = body["parents"]
            if not isinstance(parents, list) or len(parents) > 256:
                raise ValueError("invalid parent inventory")
            edges[identifier] = []
            for ref in parents:
                parent = rows.get(("asset", workspace_id, ref["asset_id"]))
                if parent is None or _asset_ref(parent) != ref:
                    raise ValueError("asset parent missing or changed")
                edges[identifier].append(parent["id"])
                report["parent_references"] += 1
            native = manifest.get("native_refs", [])
            if not isinstance(native, list) or len(native) > 256:
                raise ValueError("invalid native inventory")
            for ref in native:
                target = rows.get((ref["kind"], workspace_id, ref["id"]))
                if (
                    ref["kind"] not in NATIVE_FIELDS
                    or target is None
                    or target.get("status") != "ready"
                ):
                    raise ValueError("native reference missing")
                if ref.get("version") is not None and ref["version"] != target.get(
                    "version"
                ):
                    raise ValueError("native version mismatch")
                actual = digest(
                    {field: target.get(field) for field in NATIVE_FIELDS[ref["kind"]]}
                )
                if ref.get("identity_digest") != actual:
                    raise ValueError("native identity mismatch")
                if ref["kind"] == "model":
                    _file(_path(root, target["model_uri"] + "/MLmodel", workspace_id))
                elif ref["kind"] == "document_set":
                    prefix = _path(root, target["artifact_prefix"], workspace_id)
                    if not prefix.is_dir() or not any(
                        p.is_file() for p in prefix.rglob("*")
                    ):
                        raise ValueError("native collection artifacts missing")
                report["native_references"] += 1
            report["assets"] += 1
    # Iterative DFS checks historical ancestry without recursion depth hazards.
    done, active = set(), set()
    for start in edges:
        stack = [(start, False)]
        while stack:
            current, exiting = stack.pop()
            if exiting:
                active.remove(current)
                done.add(current)
            elif current not in done:
                if current in active:
                    raise ValueError("asset parent cycle")
                active.add(current)
                stack.append((current, True))
                stack.extend((parent, False) for parent in edges[current])
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?")
    parser.add_argument("--objects-root", type=Path)
    parser.add_argument("--registry", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.registry and args.objects_root and not args.directory:
            print(
                json.dumps(
                    validate_registry(args.objects_root, args.registry), sort_keys=True
                )
            )
        elif args.directory and not args.registry and not args.objects_root:
            validate(args.directory)
        else:
            parser.error("provide a Delta directory, or --objects-root and --registry")
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError):
        print(
            "Backup verification failed: copied bytes or registry references are inconsistent",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
