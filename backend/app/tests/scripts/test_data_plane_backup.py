"""Offline restore checks exercise real Delta files and A1 content hashes."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts/agentium_validate_delta_backup.py"
spec = importlib.util.spec_from_file_location("backup_verifier", SCRIPT)
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _registry(path, records):
    path.write_text("".join(json.dumps(row) + "\n" for row in records))


def _asset(root, workspace, identifier, manifest, parents=()):
    body = {
        "workspace_id": workspace,
        "kind": "document_set",
        "logical_key": identifier,
        "manifest": manifest,
        "parents": list(parents),
        "run_id": None,
    }
    sha = verify.digest(body)
    key = f"workspaces/{workspace}/governed-assets/manifests/{sha}.json"
    _write(root / key, verify.canonical(body))
    return {
        "id": identifier,
        "workspace_id": workspace,
        "kind": "document_set",
        "logical_key": identifier,
        "version": 1,
        "digest": sha,
        "manifest_key": key,
        "manifest_json": manifest,
        "parents_json": list(parents),
        "run_id": None,
    }


@pytest.fixture(scope="module")
def backup_source(tmp_path_factory):
    import numpy as np
    import pyarrow as pa
    from deltalake import DeltaTable, write_deltalake

    base = tmp_path_factory.mktemp("backup-source")
    objects = base / "objects"
    key = "workspaces/ws-1/tabular/datasets/ds-1/delta"
    table = pa.table({"row_id": np.arange(20000), "value": np.random.default_rng(42).random(20000)})
    write_deltalake(str(objects / key), table, target_file_size=64 * 1024)
    files = [Path(uri) for uri in DeltaTable(str(objects / key)).file_uris()]
    assert len(files) > 1

    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    dataset = {
        "id": "ds-1",
        "workspace_id": "ws-1",
        "version": 1,
        "status": "ready",
        "storage_key": key,
        "row_count": 20000,
        "schema_json": [{"name": "row_id"}, {"name": "value"}],
        "lineage_json": {
            "storage": {
                "format": "delta",
                "log_sha256": sha(objects / key / "_delta_log/00000000000000000000.json"),
                "parts": {path.name: sha(path) for path in files},
            }
        },
    }
    evidence_key = "workspaces/ws-1/evidence/source.txt"
    content = "preuve exacte : été".encode()
    _write(objects / evidence_key, content)
    parent = _asset(
        objects,
        "ws-1",
        "parent",
        {
            "objects": [
                {
                    "key": evidence_key,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                }
            ]
        },
    )
    native = {
        "kind": "dataset",
        "id": dataset["id"],
        "version": 1,
        "identity_digest": verify.digest(
            {field: dataset[field] for field in verify.NATIVE_FIELDS["dataset"]}
        ),
    }
    child = _asset(objects, "ws-1", "child", {"native_refs": [native]}, [verify._asset_ref(parent)])
    records = [
        {"type": "dataset", "row": dataset},
        {"type": "asset", "row": parent},
        {"type": "asset", "row": child},
    ]
    registry = base / "reference-registry.jsonl"
    _registry(registry, records)
    return objects, registry, records


@pytest.fixture()
def restored(tmp_path, backup_source):
    objects, registry, records = backup_source
    destination = tmp_path / "restored-objects"
    shutil.copytree(objects, destination)
    restored_registry = tmp_path / "reference-registry.jsonl"
    shutil.copy2(registry, restored_registry)
    return destination, restored_registry, copy.deepcopy(records)


def test_real_multipart_delta_and_a1_restore_verifies_copied_bytes(restored):
    objects, registry, _ = restored
    report = verify.validate_registry(objects, registry)
    assert report == {
        "schema_version": 1,
        "status": "verified",
        "datasets": 1,
        "delta_versions": 1,
        "legacy_datasets_without_recorded_hash": 0,
        "assets": 2,
        "asset_objects": 1,
        "native_references": 1,
        "parent_references": 1,
    }
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--objects-root", str(objects), "--registry", str(registry)],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == report


@pytest.mark.parametrize(
    "damage",
    [
        "part_same_size",
        "part_missing",
        "log_same_size",
        "additional_commit",
        "manifest_same_size",
        "object_same_size",
        "object_missing",
        "parent_missing",
        "parent_version",
        "native_version",
        "native_identity",
        "sql_manifest",
        "missing_part_hash",
    ],
)
def test_corruption_and_incomplete_restores_are_refused(restored, damage):
    objects, registry, records = restored
    dataset, parent, child = [entry["row"] for entry in records]
    delta = objects / dataset["storage_key"]
    if damage.startswith("part_"):
        path = delta / next(iter(dataset["lineage_json"]["storage"]["parts"]))
    elif damage == "log_same_size":
        path = delta / "_delta_log/00000000000000000000.json"
    elif damage == "manifest_same_size":
        path = objects / parent["manifest_key"]
    elif damage.startswith("object_"):
        path = objects / parent["manifest_json"]["objects"][0]["key"]
    else:
        path = None
    if path:
        if damage.endswith("missing"):
            path.unlink()
        else:
            content = path.read_bytes()
            path.write_bytes(bytes([content[0] ^ 1]) + content[1:])
    elif damage == "additional_commit":
        (delta / "_delta_log/00000000000000000001.json").write_text("{}\n")
    elif damage == "parent_missing":
        records.pop(1)
    elif damage == "parent_version":
        parent["version"] += 1
    elif damage == "native_version":
        dataset["version"] += 1
    elif damage == "native_identity":
        dataset["row_count"] += 1
    elif damage == "sql_manifest":
        parent["manifest_json"]["edited"] = True
    elif damage == "missing_part_hash":
        dataset["lineage_json"]["storage"]["parts"].pop(
            next(iter(dataset["lineage_json"]["storage"]["parts"]))
        )
    _registry(registry, records)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--objects-root", str(objects), "--registry", str(registry)],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 1 and not result.stdout
    assert "Backup verification failed" in result.stderr


@pytest.mark.parametrize(
    "key",
    [
        "../escape",
        "/tmp/escape",
        "workspaces/ws-2/evidence.txt",
        "workspaces/ws-1/../ws-2/evidence.txt",
        "workspaces/ws-1//evidence.txt",
        "workspaces/ws-1/evil\\name",
    ],
)
def test_manifest_cannot_escape_workspace_even_with_consistent_hash(restored, key):
    objects, registry, records = restored
    parent = records[1]["row"]
    manifest = copy.deepcopy(parent["manifest_json"])
    manifest["objects"][0]["key"] = key
    replacement = _asset(objects, "ws-1", "replacement", manifest)
    _registry(registry, [{"type": "asset", "row": replacement}])
    with pytest.raises(ValueError):
        verify.validate_registry(objects, registry)


def test_symlinked_restore_object_is_refused(restored, tmp_path):
    objects, registry, records = restored
    path = objects / records[1]["row"]["manifest_json"]["objects"][0]["key"]
    target = tmp_path / "outside"
    shutil.copy2(path, target)
    path.unlink()
    path.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        verify.validate_registry(objects, registry)


def test_actual_sqlite_and_object_store_backup_restoration(db_session, tmp_path, monkeypatch):
    """Round-trip actual application A1 rows through SQLite's backup API."""
    from app.core.config import settings
    from app.models.workspace import Workspace
    from app.services.governed_assets import register_asset
    from app.services.object_store import get_object_store

    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "live-store"))
    workspace = Workspace(id=str(uuid4()), name="Backup", slug="backup-" + uuid4().hex)
    db_session.add(workspace)
    db_session.commit()
    key = f"workspaces/{workspace.id}/source/facts.bin"
    payload = b"stored application evidence"
    get_object_store().write_once(key, payload)
    asset = register_asset(
        db_session,
        workspace.id,
        "document_set",
        "facts",
        {
            "objects": [
                {
                    "key": key,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "size_bytes": len(payload),
                }
            ]
        },
    )
    db_session.commit()
    backup_db, restored_db = tmp_path / "backup.sqlite", tmp_path / "restored.sqlite"
    connection = sqlite3.connect(db_session.bind.url.database)
    with sqlite3.connect(backup_db) as target:
        connection.backup(target)
    connection.close()
    with sqlite3.connect(backup_db) as source, sqlite3.connect(restored_db) as target:
        source.backup(target)
    with sqlite3.connect(restored_db) as restored_sql:
        restored_sql.row_factory = sqlite3.Row
        row = dict(
            restored_sql.execute("SELECT * FROM asset_versions WHERE id = ?", [asset.id]).fetchone()
        )
    for field in ("manifest_json", "parents_json"):
        row[field] = json.loads(row[field])
    restored_objects = tmp_path / "restored-store"
    shutil.copytree(tmp_path / "live-store", restored_objects)
    # Verification must not fall back to live bytes, so remove the source store.
    shutil.rmtree(tmp_path / "live-store")
    registry = tmp_path / "restored-registry.jsonl"
    _registry(registry, [{"type": "asset", "row": row}])
    assert verify.validate_registry(restored_objects, registry)["assets"] == 1
    (restored_objects / key).write_bytes(b"corrupt restoration")
    with pytest.raises(ValueError):
        verify.validate_registry(restored_objects, registry)


DOCKER_DOUBLE = r"""#!/usr/bin/env python3
# Transport double only: actual shell, copied bytes and readiness gate still run.
import json, os, pathlib, shutil, subprocess, sys
args = sys.argv[1:]
registry = pathlib.Path(os.environ['BACKUP_TEST_REGISTRY'])
bucket = pathlib.Path(os.environ['BACKUP_TEST_BUCKET'])
if args[0] == 'cp':
    source = pathlib.Path(args[1].split(':', 1)[-1])
    destination = pathlib.Path(args[2])
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)
    else:
        shutil.copy2(source, destination)
    sys.exit(0)
assert args[0] == 'exec', args
command = args[2:]
if command[0] == 'psql':
    sql = command[command.index('-c') + 1]
    if 'pg_database' in sql:
        pass
    elif 'information_schema.tables' in sql:
        print(2 if "table_name in ('tabular_datasets', 'ml_models')" in sql else int("table_name = 'asset_versions'" in sql))
    elif 'json_build_object' in sql:
        print(registry.read_text(), end='')
    elif 'null::text as workspace_id' in sql:
        print('ws-1')
    elif 'select storage_key from tabular_datasets' in sql:
        print(next(json.loads(line)['row']['storage_key'] for line in registry.read_text().splitlines() if json.loads(line)['type'] == 'dataset'))
    elif any(token in sql for token in ('select model_uri', "metrics_json->'report'", "metrics_json->'evaluation'")):
        pass
    else:
        raise RuntimeError('Unexpected SQL in transport double')
elif command[0] == 'pg_dump':
    pathlib.Path(command[command.index('-f') + 1]).write_bytes(b'transport-double-not-a-real-pg-dump')
elif command[0] == 'printenv':
    print('bucket')
elif command[0] == 'sh':
    mc = command[command.index('mc') + 1:]
    verb = mc[0]
    source = bucket / mc[2].removeprefix('dump/bucket/')
    if verb == 'du':
        print(json.dumps({'size': sum(p.stat().st_size for p in source.rglob('*') if p.is_file())}))
    elif verb == 'mirror':
        shutil.copytree(source, mc[3], dirs_exist_ok=True)
    else:
        raise RuntimeError('Unexpected mc operation')
else:
    assert command[0] in {'rm', 'mkdir'}, command
    subprocess.run(command, check=True)
"""


@pytest.mark.parametrize("corrupt", [False, True])
def test_actual_dump_shell_marks_ready_only_after_a1_byte_verification(restored, tmp_path, corrupt):
    import os

    bucket, registry, records = restored
    if corrupt:
        obj = bucket / records[1]["row"]["manifest_json"]["objects"][0]["key"]
        content = obj.read_bytes()
        obj.write_bytes(bytes([content[0] ^ 1]) + content[1:])
    data_root = tmp_path / "data-root"
    data_root.mkdir()
    script = tmp_path / "dump.sh"
    original = (ROOT / "scripts/agentium-data-plane-dump.sh").read_text()
    script.write_text(
        original.replace(
            "readonly DATA_ROOT=/srv/agentium-data", f"readonly DATA_ROOT={data_root}"
        ).replace(
            "readonly STAGE=/tmp/agentium-data-plane-dump",
            f"readonly STAGE={tmp_path / 'mirror-stage'}",
        )
    )
    shutil.copy2(SCRIPT, tmp_path)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    docker = binaries / "docker"
    docker.write_text(DOCKER_DOUBLE)
    docker.chmod(0o755)
    result = subprocess.run(
        ["bash", str(script), uuid4().hex[:12], "offline-test"],
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
            "BACKUP_TEST_REGISTRY": str(registry),
            "BACKUP_TEST_BUCKET": str(bucket),
        },
        timeout=30,
    )
    window = next((data_root / "offline-test-deployments").iterdir())
    manifest = json.loads((window / "MANIFEST.json").read_text())
    assert (window / ".ready").exists() is not corrupt
    assert manifest["governed_bytes_verified"] is not corrupt
    assert result.returncode == (1 if corrupt else 0), result.stderr
    if not corrupt:
        assert json.loads((window / "governed-verification.json").read_text())["assets"] == 2
        assert (window / "reference-registry.jsonl").read_bytes() == registry.read_bytes()
