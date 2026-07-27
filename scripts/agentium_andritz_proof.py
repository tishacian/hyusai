#!/usr/bin/env python3
"""Build the content-free Andritz deployment proof bundle.

The bundle cryptographically binds the independent UX JUnit, SPL probe, one
controlled Chat delivery, its database ledger, and the all-workspace runtime
binding audit.  It never copies a query, answer, citation, source, or filename
from customer data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import UUID


FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
MAX_AGE_SECONDS = 60 * 60
MAX_BYTES = 32 * 1024 * 1024
MAX_STORAGE_BYTES = 96 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
STABLE_MOUNT_FIELDS = (
    "source",
    "normalized_source",
    "expected_source",
    "source_matches_expected",
    "target",
    "fstype",
    "device_id",
)
OBJECT_STORE_ENTRY_FIELDS = ("path_sha256", "size", "content_sha256")
MINIO_ENTRY_FIELDS = (
    "object_id_sha256",
    "version_id_sha256",
    "size",
    "etag_sha256",
    "last_modified",
    "is_latest",
    "delete_marker",
)
OBJECT_STORE_MODIFICATION_FIELDS = (
    "path_sha256",
    "before_entry_sha256",
    "after_entry_sha256",
)
MINIO_MODIFICATION_FIELDS = (
    "object_id_sha256",
    "version_id_sha256",
    "before_entry_sha256",
    "after_entry_sha256",
)
EXPECTED_STORAGE_ADDITIONS_CHECKS = frozenset(
    {
        "secure_deposit.aggregate",
        "object_store_bindings",
        "qdrant.inventory",
        "container_mounts",
        "object_store.algorithm",
        "object_store.entry_fields",
        "object_store.preexisting_entries_preserved",
        "minio.bucket_id_sha256",
        "minio.versioning_status",
        "minio.algorithm",
        "minio.entry_fields",
        "minio.preexisting_entries_preserved",
        "minio.preexisting_object_keys_not_reversioned",
        "minio.no_delete_marker_additions",
        "minio.delete_markers_unchanged",
    }
) | frozenset(
    f"mounts.{mount}.{field}"
    for mount in ("data", "secure_deposit")
    for field in STABLE_MOUNT_FIELDS
)
INPUTS = {
    "workspace_junit": "andritz.xml",
    "spl_probe": "spl-probe.json",
    "chat_delivery": "controlled-chat-state.json",
    "chat_ledger": "chat-ledger.json",
    "runtime_bindings": "runtime-bindings.json",
    "storage_canary_comparison": "../storage-canary-comparison.json",
}
EXPECTED_ANDRITZ_TEST_TITLES = frozenset(
    {
        "Andritz business preview exposes the three-app shell",
        "the three Andritz surfaces survive deep links, history and reload",
        "a forced access-token expiry retries inside the selected workspace",
        "business preview redirects advanced routes while admin mode keeps the full cockpit",
        "deployed Andritz profile, entitlements and active Systems match the Lot 4 contract",
        "resolved navigation is persisted with canonical routes and no user identity",
    }
)
FORBIDDEN_CONTENT_KEYS = frozenset(
    {
        "query",
        "answer",
        "response",
        "citation",
        "citations",
        "source",
        "sources",
        "content",
        "text",
    }
)
REQUIRED_CHAT_LINEAGE_CHECKS = frozenset(
    {
        "workspace_exists",
        "workspace_is_andritz",
        "workspace_family_is_andritz",
        "run_exists",
        "run_completed",
        "trigger_is_strict_agentic_chat",
        "input_marker_present",
        "system_exists",
        "system_is_active_andritz_system",
        "system_type_is_agentic_chat",
        "system_flow_variant_is_agentic_chat",
        "run_flow_variant_matches_system",
        "migration_marker_targets_system",
        "run_capability_matches_system",
        "capability_exists",
        "capability_is_visible_to_andritz",
        "chat_execution_routes_agentic",
        "chat_execution_targets_system",
        "chat_execution_variant_is_agentic_chat",
        "system_retrieval_contract_is_andritz",
        "run_retrieval_contract_is_andritz",
        "knowledge_collection_exists",
        "knowledge_collection_is_ready",
        "knowledge_collection_has_chunks",
    }
)


class AndritzProofError(ValueError):
    """Raised when an Andritz proof input is missing or inconsistent."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _private_input(
    path: Path,
    proofs: Path,
    *,
    label: str,
    max_bytes: int = MAX_BYTES,
) -> Path:
    try:
        if path.is_symlink():
            raise AndritzProofError(f"{label} cannot be a symlink")
        resolved = path.resolve(strict=True)
        resolved.relative_to(proofs)
        details = resolved.stat()
    except (OSError, ValueError) as exc:
        raise AndritzProofError(f"{label} is unavailable or escaped proofs") from exc
    if not resolved.is_file() or details.st_size <= 0 or details.st_size > max_bytes:
        raise AndritzProofError(f"{label} is not a bounded regular file")
    if details.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise AndritzProofError(f"{label} is group/world writable")
    age = time.time() - details.st_mtime
    if age < -300 or age > MAX_AGE_SECONDS:
        raise AndritzProofError(f"{label} is stale or future-dated")
    return resolved


def _json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AndritzProofError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise AndritzProofError(f"{label} must be a JSON object")
    return value


def _uuid(value: object, *, label: str) -> str:
    raw = str(value or "")
    try:
        parsed = UUID(raw)
    except ValueError as exc:
        raise AndritzProofError(f"{label} is not a run UUID") from exc
    if str(parsed) != raw:
        raise AndritzProofError(f"{label} is not canonical")
    return raw


def _all_checks_pass(payload: Mapping[str, Any], *, label: str) -> None:
    checks = payload.get("checks")
    if not isinstance(checks, dict) or not checks:
        raise AndritzProofError(f"{label} checks are missing")
    if any(
        value is not True
        and not (isinstance(value, dict) and value.get("passed") is True)
        for value in checks.values()
    ):
        raise AndritzProofError(f"{label} contains a failing check")


def _marker_sha256(deployment_id: str, candidate_sha: str) -> str:
    marker = f"agentium_safe_chat::{deployment_id}::{candidate_sha[:12]}"
    return hashlib.sha256(marker.encode("utf-8")).hexdigest()


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _assert_content_free(value: object, *, label: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).strip().lower() in FORBIDDEN_CONTENT_KEYS:
                raise AndritzProofError(f"{label} contains persisted content")
            _assert_content_free(child, label=label)
    elif isinstance(value, list):
        for child in value:
            _assert_content_free(child, label=label)


def _storage_addition_matches_artifact(
    comparison: Mapping[str, Any],
    artifact: Mapping[str, Any],
) -> bool:
    backend = artifact.get("backend")
    key_sha256 = artifact.get("key_sha256")
    content_sha256 = artifact.get("content_sha256")
    size = artifact.get("size")
    if (
        backend not in {"local", "s3"}
        or not isinstance(key_sha256, str)
        or SHA256_RE.fullmatch(key_sha256) is None
        or not isinstance(content_sha256, str)
        or SHA256_RE.fullmatch(content_sha256) is None
        or not isinstance(size, int)
        or isinstance(size, bool)
        or size <= 0
    ):
        return False
    if (
        comparison.get("profile") != "agentium-storage-object-additions-v1"
        or comparison.get("assurance") != "cryptographic_entry_inclusion"
        or comparison.get("result") != "passed"
        or comparison.get("failed_checks") != []
    ):
        return False
    checks = comparison.get("checks")
    check_names = (
        [row.get("name") if isinstance(row, dict) else None for row in checks]
        if isinstance(checks, list)
        else []
    )
    if (
        not isinstance(checks, list)
        or not checks
        or any(
            not isinstance(row, dict) or row.get("passed") is not True for row in checks
        )
        or len(check_names) != len(set(check_names))
        or set(check_names) != EXPECTED_STORAGE_ADDITIONS_CHECKS
    ):
        return False
    additions = comparison.get("additions")
    deletions = comparison.get("deletions")
    modifications = comparison.get("modifications")
    if not all(
        isinstance(value, dict) for value in (additions, deletions, modifications)
    ):
        return False
    empty_digest = _canonical_sha256([])
    if set(deletions) != {"object_store", "minio"} or set(modifications) != {
        "object_store",
        "minio",
    }:
        return False
    for key, fields in (
        ("object_store", OBJECT_STORE_ENTRY_FIELDS),
        ("minio", MINIO_ENTRY_FIELDS),
    ):
        summary = deletions.get(key)
        if (
            not isinstance(summary, dict)
            or set(summary) != {"count", "bytes", "entry_fields", "entries", "digest"}
            or summary.get("count") != 0
            or summary.get("bytes") != 0
            or summary.get("entry_fields") != list(fields)
            or summary.get("entries") != []
            or summary.get("digest") != empty_digest
        ):
            return False
    for key, fields in (
        ("object_store", OBJECT_STORE_MODIFICATION_FIELDS),
        ("minio", MINIO_MODIFICATION_FIELDS),
    ):
        summary = modifications.get(key)
        if (
            not isinstance(summary, dict)
            or set(summary) != {"count", "entry_fields", "entries", "digest"}
            or summary.get("count") != 0
            or summary.get("entry_fields") != list(fields)
            or summary.get("entries") != []
            or summary.get("digest") != empty_digest
        ):
            return False
    if set(additions) != {"object_store", "minio"}:
        return False
    selected = "object_store" if backend == "local" else "minio"
    other = "minio" if backend == "local" else "object_store"
    selected_summary = additions.get(selected)
    other_summary = additions.get(other)
    if (
        not isinstance(selected_summary, dict)
        or set(selected_summary)
        != {"count", "bytes", "entry_fields", "entries", "digest"}
        or selected_summary.get("count") != 1
        or selected_summary.get("bytes") != size
        or not isinstance(selected_summary.get("entries"), list)
        or len(selected_summary["entries"]) != 1
        or selected_summary.get("digest")
        != _canonical_sha256(selected_summary["entries"])
        or not isinstance(other_summary, dict)
        or set(other_summary) != {"count", "bytes", "entry_fields", "entries", "digest"}
        or other_summary.get("count") != 0
        or other_summary.get("bytes") != 0
        or other_summary.get("entries") != []
        or other_summary.get("digest") != empty_digest
    ):
        return False
    entry = selected_summary["entries"][0]
    fields = selected_summary.get("entry_fields")
    if backend == "local":
        return bool(
            isinstance(entry, dict)
            and set(entry) == set(OBJECT_STORE_ENTRY_FIELDS)
            and fields == list(OBJECT_STORE_ENTRY_FIELDS)
            and other_summary.get("entry_fields") == list(MINIO_ENTRY_FIELDS)
            and entry.get("path_sha256") == key_sha256
            and entry.get("content_sha256") == content_sha256
            and entry.get("size") == size
        )
    if (
        not isinstance(entry, list)
        or fields != list(MINIO_ENTRY_FIELDS)
        or other_summary.get("entry_fields") != list(OBJECT_STORE_ENTRY_FIELDS)
        or len(entry) != len(fields)
    ):
        return False
    row = dict(zip(fields, entry, strict=True))
    return bool(
        row.get("object_id_sha256") == key_sha256
        and row.get("size") == size
        and row.get("delete_marker") is False
    )


def _assert_testcase_sha_bindings(
    root: ET.Element,
    cases: list[ET.Element],
    *,
    candidate_sha: str,
) -> None:
    sha_property_names = {
        "commit_sha",
        "candidate_sha",
        "ci_commit_sha",
        "git_sha",
    }
    all_sha_properties = [
        node
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1] == "property"
        and str(node.attrib.get("name", "")).strip().lower() in sha_property_names
    ]
    if len(all_sha_properties) != len(cases):
        raise AndritzProofError(
            "workspace JUnit must bind the candidate SHA inside every testcase"
        )
    for case in cases:
        bindings = [
            node
            for node in case.iter()
            if node.tag.rsplit("}", 1)[-1] == "property"
            and str(node.attrib.get("name", "")).strip().lower() in sha_property_names
        ]
        if len(bindings) != 1:
            raise AndritzProofError(
                "workspace JUnit must bind the candidate SHA inside every testcase"
            )
        binding = bindings[0]
        value = str(binding.attrib.get("value", binding.text or "")).strip()
        if binding.attrib.get("name") != "commit_sha" or value != candidate_sha:
            raise AndritzProofError(
                "workspace JUnit testcase commit SHA does not match the candidate"
            )


def _green_junit(path: Path, *, candidate_sha: str) -> int:
    raw = path.read_bytes()
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise AndritzProofError("workspace JUnit contains forbidden declarations")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise AndritzProofError("workspace JUnit is invalid") from exc
    if any(
        "".join(node.itertext()).strip()
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1] in {"system-out", "system-err"}
    ):
        raise AndritzProofError("workspace JUnit contains retained console output")
    cases = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "testcase"]
    case_titles = [node.attrib.get("name", "") for node in cases]
    if (
        len(case_titles) != len(EXPECTED_ANDRITZ_TEST_TITLES)
        or len(case_titles) != len(set(case_titles))
        or set(case_titles) != EXPECTED_ANDRITZ_TEST_TITLES
    ):
        raise AndritzProofError(
            "workspace JUnit does not contain exactly the six expected Andritz canaries"
        )
    if any(
        node.tag.rsplit("}", 1)[-1] in {"failure", "error", "skipped"}
        for node in root.iter()
    ):
        raise AndritzProofError("workspace JUnit is not fully green")
    _assert_testcase_sha_bindings(root, cases, candidate_sha=candidate_sha)
    for suite in root.iter():
        if suite.tag.rsplit("}", 1)[-1] not in {"testsuite", "testsuites"}:
            continue
        for key in ("failures", "errors", "skipped", "disabled"):
            try:
                if int(suite.attrib.get(key, "0")) != 0:
                    raise AndritzProofError("workspace JUnit is not fully green")
            except ValueError as exc:
                raise AndritzProofError("workspace JUnit count is invalid") from exc
    return len(cases)


def build_andritz_proof(
    *,
    candidate_sha: str,
    deployment_dir: Path,
) -> dict[str, Any]:
    if FULL_SHA_RE.fullmatch(candidate_sha) is None:
        raise AndritzProofError("candidate SHA is invalid")
    if deployment_dir.is_symlink():
        raise AndritzProofError("deployment-dir cannot be a symlink")
    deployment = deployment_dir.resolve(strict=True)
    proofs_candidate = deployment / "proofs"
    if proofs_candidate.is_symlink():
        raise AndritzProofError("proofs directory is invalid")
    proofs = proofs_candidate.resolve(strict=True)
    if proofs.parent != deployment:
        raise AndritzProofError("proofs directory is invalid")

    paths = {
        label: _private_input(
            proofs / name,
            deployment,
            label=label,
            max_bytes=(
                MAX_STORAGE_BYTES if label == "storage_canary_comparison" else MAX_BYTES
            ),
        )
        for label, name in INPUTS.items()
    }
    test_count = _green_junit(
        paths["workspace_junit"],
        candidate_sha=candidate_sha,
    )
    spl = _json(paths["spl_probe"], label="spl_probe")
    delivery = _json(paths["chat_delivery"], label="chat_delivery")
    ledger = _json(paths["chat_ledger"], label="chat_ledger")
    bindings = _json(paths["runtime_bindings"], label="runtime_bindings")
    storage_comparison = _json(
        paths["storage_canary_comparison"],
        label="storage_canary_comparison",
    )
    for label, evidence in (
        ("spl_probe", spl),
        ("chat_delivery", delivery),
        ("chat_ledger", ledger),
    ):
        _assert_content_free(evidence, label=label)

    expected_deployment_id = deployment.name
    expected_marker_sha256 = _marker_sha256(expected_deployment_id, candidate_sha)

    for label, payload in (("spl_probe", spl), ("chat_ledger", ledger)):
        if (
            payload.get("outcome") != "passed"
            or payload.get("commit_sha") != candidate_sha
            or payload.get("deployment_id") != expected_deployment_id
            or payload.get("input_marker_sha256") != expected_marker_sha256
        ):
            raise AndritzProofError(f"{label} did not pass for the candidate")
        _all_checks_pass(payload, label=label)
    if (
        spl.get("kind") != "andritz_spl_controlled_probe"
        or ledger.get("kind") != "safe_controlled_chat_ledger"
        or delivery.get("kind") != "controlled_chat_delivery"
        or delivery.get("status") != "completed"
        or delivery.get("commit_sha") != candidate_sha
        or delivery.get("deployment_id") != expected_deployment_id
        or delivery.get("input_marker_sha256") != expected_marker_sha256
        or delivery.get("attempt_ceiling") != 1
    ):
        raise AndritzProofError("controlled Chat delivery is incomplete")
    if (
        spl.get("actual_chat_requests") != 1
        or delivery.get("actual_chat_requests") != 1
    ):
        raise AndritzProofError("controlled Chat count is not exactly one")
    spl_run_id = _uuid(spl.get("run_id"), label="spl_probe run_id")
    if _uuid(delivery.get("run_id"), label="chat_delivery run_id") != spl_run_id:
        raise AndritzProofError("controlled Chat delivery run does not match SPL")
    if _uuid(ledger.get("run_id"), label="chat_ledger run_id") != spl_run_id:
        raise AndritzProofError("controlled Chat ledger run does not match SPL")
    ledger_checks = ledger.get("checks")
    if (
        ledger.get("schema_version") != 2
        or not isinstance(ledger_checks, dict)
        or not REQUIRED_CHAT_LINEAGE_CHECKS.issubset(ledger_checks)
    ):
        raise AndritzProofError("controlled Chat lineage contract is incomplete")
    workspace_id = _uuid(ledger.get("workspace_id"), label="workspace id")
    system_id = _uuid(ledger.get("system_id"), label="System id")
    capability_id = _uuid(ledger.get("capability_id"), label="Capability id")
    knowledge_collection_id = _uuid(
        ledger.get("knowledge_collection_id"),
        label="KnowledgeCollection id",
    )
    knowledge_collection_chunk_count = ledger.get("knowledge_collection_chunk_count")
    lineage_hash_fields = (
        "system_type_sha256",
        "flow_variant_sha256",
        "retrieval_contract_sha256",
        "knowledge_collection_slug_sha256",
    )
    if (
        not isinstance(knowledge_collection_chunk_count, int)
        or isinstance(knowledge_collection_chunk_count, bool)
        or knowledge_collection_chunk_count <= 0
        or any(
            SHA256_RE.fullmatch(str(ledger.get(field) or "")) is None
            for field in lineage_hash_fields
        )
    ):
        raise AndritzProofError("controlled Chat lineage contract is inconsistent")
    invocation_count = ledger.get("invocation_count")
    if not isinstance(invocation_count, int) or invocation_count <= 0:
        raise AndritzProofError("controlled Chat has no SkillInvocation ledger")
    invocation_ids = ledger.get("invocation_ids")
    if (
        not isinstance(invocation_ids, list)
        or len(invocation_ids) != invocation_count
        or any(not isinstance(value, str) for value in invocation_ids)
        or len(set(invocation_ids)) != invocation_count
        or any(
            _uuid(value, label="SkillInvocation id") != value
            for value in invocation_ids
        )
        or ledger.get("invocation_status_counts") != {"completed": invocation_count}
        or ledger.get("run_status_counts") != {"completed": 1}
        or SHA256_RE.fullmatch(str(ledger.get("input_query_sha256") or "")) is None
        or SHA256_RE.fullmatch(str(ledger.get("run_trigger_sha256") or "")) is None
        or SHA256_RE.fullmatch(str(ledger.get("skill_sequence_sha256") or "")) is None
        or SHA256_RE.fullmatch(str(ledger.get("flow_skill_contract_sha256") or ""))
        is None
        or SHA256_RE.fullmatch(
            str(ledger.get("read_generation_allowlist_sha256") or "")
        )
        is None
        or ledger.get("unexpected_skill_count") != 0
    ):
        raise AndritzProofError("controlled Chat ledger is internally inconsistent")
    artifact = ledger.get("provenance_artifact")
    if (
        ledger.get("artifact_count") != 1
        or not isinstance(artifact, dict)
        or not _storage_addition_matches_artifact(storage_comparison, artifact)
    ):
        raise AndritzProofError(
            "controlled Chat provenance artifact does not match the sole storage addition"
        )
    if (
        bindings.get("result") != "passed"
        or bindings.get("requested_workspace_slugs") != []
        or bindings.get("missing_workspace_slugs") != []
        or not isinstance(bindings.get("workspace_count"), int)
        or bindings["workspace_count"] < 3
    ):
        raise AndritzProofError("runtime binding audit did not pass")

    checks = {
        "andritz_workspace_junit_green": True,
        "spl_probe_passed": True,
        "exactly_one_controlled_chat": True,
        "controlled_chat_ledger_passed": True,
        "skill_invocation_ledger_present": True,
        "single_provenance_artifact_storage_addition": True,
        "all_workspace_runtime_bindings_passed": True,
    }
    return {
        "schema_version": 2,
        "kind": "andritz_safe_deployment_bundle",
        "commit_sha": candidate_sha,
        "deployment_id": deployment.name,
        "outcome": "passed",
        "actual_chat_requests": 1,
        "chat_run_id": spl_run_id,
        "input_marker_sha256": expected_marker_sha256,
        "artifact_backend": artifact["backend"],
        "artifact_key_sha256": artifact["key_sha256"],
        "artifact_content_sha256": artifact["content_sha256"],
        "artifact_size": artifact["size"],
        "workspace_id": workspace_id,
        "system_id": system_id,
        "capability_id": capability_id,
        "knowledge_collection_id": knowledge_collection_id,
        "knowledge_collection_chunk_count": knowledge_collection_chunk_count,
        **{field: ledger[field] for field in lineage_hash_fields},
        "invocation_count": invocation_count,
        "workspace_test_count": test_count,
        "checks": {name: {"passed": passed} for name, passed in checks.items()},
        "evidence": {
            label: {
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
            for label, path in paths.items()
        },
    }


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists() and path.is_symlink():
        raise AndritzProofError("Andritz output cannot be a symlink")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".andritz.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--deployment-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        payload = build_andritz_proof(
            candidate_sha=args.sha,
            deployment_dir=args.deployment_dir,
        )
        output = args.deployment_dir.resolve(strict=True) / "proofs" / "andritz.json"
        _write(output, payload)
    except (AndritzProofError, OSError) as exc:
        print(f"Andritz proof failed: {exc}", file=sys.stderr)
        return 1
    print("Andritz proof bundle passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
