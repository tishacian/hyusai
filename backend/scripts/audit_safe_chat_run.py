"""Read-only, content-free audit of the controlled Andritz deployment Chat."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.db.base import SessionLocal
from app.models.capability import Capability
from app.models.knowledge_collection import KnowledgeCollection
from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.models.workspace import Workspace
from app.services.chat_execution_policy import (
    AGENTIC_SYSTEM_TYPE,
    AGENTIC_VARIANT,
    ANDRITZ_RETRIEVAL_CONTRACT,
    migration_059_system_id,
)
from app.services.object_store import get_object_store

FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DEPLOYMENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{5,95}$")
READ_GENERATION_SKILLS = frozenset(
    {
        "semantic_search_v1",
        "multi_hop_retrieve_v1",
        "chat_agentic_plan_v1",
        "llm_rag_answer_v1",
        "response_eval_v1",
        "chat_self_correct_v1",
    }
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class SafeChatAuditError(ValueError):
    """Raised when a CLI identity is malformed."""


def controlled_chat_marker(deployment_id: str, candidate_sha: str) -> str:
    if DEPLOYMENT_ID_RE.fullmatch(deployment_id) is None:
        raise SafeChatAuditError("deployment-id is invalid")
    if FULL_SHA_RE.fullmatch(candidate_sha) is None:
        raise SafeChatAuditError("candidate SHA is invalid")
    return f"agentium_safe_chat::{deployment_id}::{candidate_sha[:12]}"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_sha256(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return _sha256(canonical)


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _canonical_uuid(value: str, *, label: str) -> str:
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise SafeChatAuditError(f"{label} is invalid") from exc
    if str(parsed) != value:
        raise SafeChatAuditError(f"{label} must be a canonical UUID")
    return value


def _flow_skill_slugs(value: object) -> set[str]:
    result: set[str] = set()

    def visit(item: object) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if key in {"skill_slug", "skill_ref"} and isinstance(child, str) and child:
                    result.add(child)
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return result


def audit_safe_chat_run(
    db,
    *,
    run_id: str,
    workspace_id: str,
    deployment_id: str,
    candidate_sha: str,
    object_store=None,
) -> dict[str, Any]:
    """Verify one Run and emit no query, answer, citation, source, or trace."""

    expected_run_id = _canonical_uuid(run_id, label="run-id")
    expected_workspace_id = _canonical_uuid(workspace_id, label="workspace-id")
    marker = controlled_chat_marker(deployment_id, candidate_sha)
    run = db.query(Run).filter(Run.id == expected_run_id).one_or_none()
    workspace = (
        db.query(Workspace).filter(Workspace.id == expected_workspace_id).one_or_none()
    )
    system = (
        db.query(System).filter(System.id == run.system_id).one_or_none()
        if run is not None and run.system_id
        else None
    )
    capability = (
        db.query(Capability).filter(Capability.id == system.capability_id).one_or_none()
        if system is not None and system.capability_id
        else None
    )
    invocations = (
        db.query(SkillInvocation)
        .filter(SkillInvocation.run_id == expected_run_id)
        .order_by(SkillInvocation.started_at.asc(), SkillInvocation.id.asc())
        .all()
        if run is not None
        else []
    )

    input_ref = _mapping(run.input_ref if run is not None else None)
    chat_execution = _mapping(input_ref.get("chat_execution"))
    run_retrieval_contract = _mapping(input_ref.get("retrieval_contract"))
    workspace_settings = _mapping(workspace.settings if workspace is not None else None)
    system_settings = _mapping(system.settings if system is not None else None)
    system_flow = _mapping(system.flow_definition if system is not None else None)
    run_flow = _mapping(run.flow_snapshot if run is not None else None)
    system_retrieval_contract = _mapping(system_settings.get("retrieval_contract"))
    expected_collection_slug = ANDRITZ_RETRIEVAL_CONTRACT["collection"]
    collection = (
        db.query(KnowledgeCollection)
        .filter(
            KnowledgeCollection.workspace_id == workspace.id,
            KnowledgeCollection.slug == expected_collection_slug,
        )
        .one_or_none()
        if workspace is not None
        else None
    )
    query = input_ref.get("query") if isinstance(input_ref.get("query"), str) else ""
    statuses = Counter(str(row.status or "unset") for row in invocations)
    skill_sequence = [str(row.skill_slug or "") for row in invocations]
    invoked_skills = set(skill_sequence)
    flow_skills = _flow_skill_slugs(run.flow_snapshot if run is not None else None)
    unexpected_skills = invoked_skills - READ_GENERATION_SKILLS
    artifacts: list[dict[str, Any]] = []
    for invocation in invocations:
        trace = invocation.trace if isinstance(invocation.trace, dict) else {}
        direct = trace.get("membrane_provenance")
        if isinstance(direct, dict):
            artifacts.append(direct)
        membrane = trace.get("membrane") if isinstance(trace.get("membrane"), dict) else {}
        nested = membrane.get("artifact")
        if isinstance(nested, dict):
            artifacts.append(nested)

    store = object_store or get_object_store()
    backend = str(getattr(store, "backend", "")).strip().lower()
    artifact = artifacts[0] if len(artifacts) == 1 else {}
    artifact_key = str(artifact.get("key") or "")
    artifact_uri = str(artifact.get("uri") or "")
    declared_sha256 = str(artifact.get("sha256") or "").strip().lower()
    declared_size = artifact.get("size_bytes")
    metadata_valid = bool(
        artifact_key
        and artifact_uri == f"object://{artifact_key}"
        and SHA256_RE.fullmatch(declared_sha256)
        and isinstance(declared_size, int)
        and not isinstance(declared_size, bool)
        and declared_size >= 0
        and backend in {"local", "s3"}
    )
    persisted = b""
    artifact_readable = False
    if metadata_valid:
        try:
            persisted = store.read_bytes(artifact_key)
            artifact_readable = isinstance(persisted, bytes)
        except Exception:  # noqa: BLE001 - a failed proof stays content-free.
            artifact_readable = False
    observed_sha256 = hashlib.sha256(persisted).hexdigest() if artifact_readable else None
    observed_size = len(persisted) if artifact_readable else None
    checks = {
        "workspace_exists": workspace is not None,
        "run_exists": run is not None,
        "workspace_is_andritz": bool(
            workspace is not None and run is not None and run.workspace_id == workspace.id
        ),
        "workspace_family_is_andritz": workspace_settings.get("family") == "andritz",
        "run_completed": bool(run is not None and run.status == "completed"),
        "trigger_is_strict_agentic_chat": bool(run is not None and run.trigger == "chat_agentic"),
        "input_marker_present": marker in query,
        "system_exists": system is not None,
        "system_is_active_andritz_system": bool(
            workspace is not None
            and system is not None
            and system.workspace_id == workspace.id
            and system.status == "active"
        ),
        "system_type_is_agentic_chat": bool(
            system is not None and system_settings.get("system_type") == AGENTIC_SYSTEM_TYPE
        ),
        "system_flow_variant_is_agentic_chat": bool(
            system is not None and system_flow.get("variant") == AGENTIC_VARIANT
        ),
        "run_flow_variant_matches_system": bool(
            run is not None
            and system is not None
            and run_flow.get("variant") == AGENTIC_VARIANT
            and run_flow.get("variant") == system_flow.get("variant")
        ),
        "migration_marker_targets_system": bool(
            workspace is not None
            and system is not None
            and migration_059_system_id(workspace) == system.id
        ),
        "run_capability_matches_system": bool(
            run is not None
            and system is not None
            and isinstance(system.capability_id, str)
            and bool(system.capability_id)
            and run.capability_id == system.capability_id
        ),
        "capability_exists": capability is not None,
        "capability_is_visible_to_andritz": bool(
            workspace is not None
            and capability is not None
            and capability.workspace_id in {None, workspace.id}
        ),
        "chat_execution_routes_agentic": chat_execution.get("route") == "agentic",
        "chat_execution_targets_system": bool(
            system is not None and chat_execution.get("executor_system_id") == system.id
        ),
        "chat_execution_variant_is_agentic_chat": (
            chat_execution.get("executor_variant") == AGENTIC_VARIANT
        ),
        "system_retrieval_contract_is_andritz": (
            system_retrieval_contract == ANDRITZ_RETRIEVAL_CONTRACT
        ),
        "run_retrieval_contract_is_andritz": (run_retrieval_contract == ANDRITZ_RETRIEVAL_CONTRACT),
        "knowledge_collection_exists": collection is not None,
        "knowledge_collection_is_ready": bool(
            collection is not None and collection.status == "ready"
        ),
        "knowledge_collection_has_chunks": bool(
            collection is not None
            and isinstance(collection.chunk_count, int)
            and not isinstance(collection.chunk_count, bool)
            and collection.chunk_count > 0
        ),
        "skill_invocation_ledger_present": bool(invocations),
        "skill_invocation_ledger_completed": bool(invocations)
        and all(row.status == "completed" for row in invocations),
        "flow_skill_contract_present": bool(flow_skills),
        "skill_invocations_declared_by_flow": bool(invocations)
        and invoked_skills.issubset(flow_skills),
        "skill_invocations_read_generation_only": bool(invocations) and not unexpected_skills,
        "single_membrane_provenance_artifact": len(artifacts) == 1,
        "membrane_provenance_metadata_valid": metadata_valid,
        "membrane_provenance_artifact_readable": artifact_readable,
        "membrane_provenance_sha256_matches": bool(
            artifact_readable and observed_sha256 == declared_sha256
        ),
        "membrane_provenance_size_matches": bool(
            artifact_readable and observed_size == declared_size
        ),
    }
    passed = all(checks.values())
    return {
        "schema_version": 2,
        "kind": "safe_controlled_chat_ledger",
        "commit_sha": candidate_sha,
        "deployment_id": deployment_id,
        "outcome": "passed" if passed else "failed",
        "run_id": expected_run_id,
        "workspace_id": workspace.id if workspace is not None else None,
        "system_id": system.id if system is not None else None,
        "capability_id": capability.id if capability is not None else None,
        "knowledge_collection_id": collection.id if collection is not None else None,
        "input_marker_sha256": _sha256(marker),
        "input_query_sha256": _sha256(query) if query else None,
        "run_trigger_sha256": _sha256(str(run.trigger)) if run is not None else None,
        "system_type_sha256": (
            _sha256(str(system_settings.get("system_type"))) if system is not None else None
        ),
        "flow_variant_sha256": (
            _sha256(str(system_flow.get("variant"))) if system is not None else None
        ),
        "retrieval_contract_sha256": _json_sha256(ANDRITZ_RETRIEVAL_CONTRACT),
        "knowledge_collection_slug_sha256": _sha256(expected_collection_slug),
        "knowledge_collection_chunk_count": (
            collection.chunk_count if collection is not None else None
        ),
        "run_status_counts": {str(run.status): 1} if run is not None else {},
        "invocation_count": len(invocations),
        "invocation_ids": [str(row.id) for row in invocations],
        "invocation_status_counts": dict(sorted(statuses.items())),
        "skill_sequence_sha256": _sha256("\0".join(skill_sequence)),
        "flow_skill_contract_sha256": _sha256("\0".join(sorted(flow_skills))),
        "read_generation_allowlist_sha256": _sha256("\0".join(sorted(READ_GENERATION_SKILLS))),
        "unexpected_skill_count": len(unexpected_skills),
        "artifact_count": len(artifacts),
        "provenance_artifact": {
            "backend": backend if backend in {"local", "s3"} else None,
            "key_sha256": _sha256(artifact_key) if artifact_key else None,
            "content_sha256": observed_sha256,
            "size": observed_size,
        },
        "checks": {name: {"passed": value} for name, value in checks.items()},
    }


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--sha", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        with SessionLocal() as db:
            report = audit_safe_chat_run(
                db,
                run_id=args.run_id,
                workspace_id=args.workspace_id,
                deployment_id=args.deployment_id,
                candidate_sha=args.sha,
            )
            db.rollback()
    except SafeChatAuditError as exc:
        print(f"controlled Chat audit failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["outcome"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
