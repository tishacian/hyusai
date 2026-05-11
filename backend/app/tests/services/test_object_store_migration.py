"""Tests for ObjectStore migration manifest helpers."""
from __future__ import annotations

from pathlib import Path

from app.services.object_store_migration import (
    ObjectStoreEntry,
    compare_manifests,
    local_object_manifest,
)


def test_local_manifest_keeps_hierarchical_keys_and_hashes(tmp_path: Path):
    (tmp_path / "workspaces" / "andritz" / "original").mkdir(parents=True)
    (tmp_path / "workspaces" / "andritz" / "original" / "a.txt").write_text("alpha")
    (tmp_path / "workspaces" / "andritz" / "original" / "b.txt").write_text("bravo")

    manifest = local_object_manifest(tmp_path)

    assert [entry.key for entry in manifest] == [
        "workspaces/andritz/original/a.txt",
        "workspaces/andritz/original/b.txt",
    ]
    assert {entry.size for entry in manifest} == {5}
    assert all(len(entry.sha256) == 64 for entry in manifest)


def test_compare_manifests_reports_missing_extra_and_mismatch():
    source = [
        ObjectStoreEntry("a.txt", 5, "hash-a"),
        ObjectStoreEntry("b.txt", 5, "hash-b"),
        ObjectStoreEntry("c.txt", 7, "hash-c"),
    ]
    target = [
        ObjectStoreEntry("b.txt", 5, "hash-b"),
        ObjectStoreEntry("c.txt", 8, "hash-c"),
        ObjectStoreEntry("d.txt", 9, "hash-d"),
    ]

    diff = compare_manifests(source, target)

    assert not diff.strict_match
    assert diff.missing_target == ["a.txt"]
    assert diff.extra_target == ["d.txt"]
    assert diff.mismatched == ["c.txt"]
