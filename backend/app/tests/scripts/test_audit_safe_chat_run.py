from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import uuid4

import pytest

from app.models.capability import Capability
from app.models.knowledge_collection import KnowledgeCollection
from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.models.workspace import Workspace
from app.services.chat_execution_policy import (
    AGENTIC_VARIANT,
    ANDRITZ_MIGRATION_MARKER,
    ANDRITZ_MIGRATION_REVISION,
    ANDRITZ_RETRIEVAL_CONTRACT,
)
from scripts.audit_safe_chat_run import audit_safe_chat_run, controlled_chat_marker

SHA = "a" * 40
DEPLOYMENT_ID = "20260722T170000Z-aaaaaaaaaaaa"
ARTIFACT_KEY = "membrane/andritz/provenance.json"
ARTIFACT_BYTES = b'{"content":"never copied into the audit"}'


class FakeStore:
    backend = "local"

    def __init__(self, content: bytes = ARTIFACT_BYTES) -> None:
        self.content = content

    def read_bytes(self, key: str) -> bytes:
        assert key == ARTIFACT_KEY
        return self.content


@dataclass(frozen=True)
class SeededChat:
    workspace: Workspace
    capability: Capability
    system: System
    collection: KnowledgeCollection
    run: Run
    invocation: SkillInvocation


def _rows(
    db_session,
    *,
    marker: bool = True,
    capability_scope: str = "global",
) -> SeededChat:
    workspace_id = str(uuid4())
    system_id = str(uuid4())
    workspace = Workspace(
        id=workspace_id,
        name="Andritz",
        slug=f"opaque-{uuid4().hex}",
        settings={
            "family": "andritz",
            ANDRITZ_MIGRATION_MARKER: {
                "revision": ANDRITZ_MIGRATION_REVISION,
                "schema": 1,
                "system_id": system_id,
            },
        },
    )
    capability = Capability(
        id=str(uuid4()),
        workspace_id=workspace.id if capability_scope == "workspace" else None,
        slug=f"opaque-capability-{uuid4()}",
        name="Opaque controlled capability",
    )
    flow = {
        "schema_version": 3,
        "variant": AGENTIC_VARIANT,
        "nodes": [
            {
                "id": "retrieve",
                "kind": "task",
                "config": {"skill_slug": "semantic_search_v1"},
            }
        ],
        "edges": [],
    }
    system = System(
        id=system_id,
        workspace_id=workspace.id,
        capability_id=capability.id,
        name="Opaque controlled System",
        objective="Controlled execution",
        settings={
            "system_type": "chat_agentic",
            "retrieval_contract": dict(ANDRITZ_RETRIEVAL_CONTRACT),
        },
        flow_definition=flow,
        status="active",
    )
    collection = KnowledgeCollection(
        id=str(uuid4()),
        workspace_id=workspace.id,
        slug=ANDRITZ_RETRIEVAL_CONTRACT["collection"],
        name="Private source collection name",
        status="ready",
        vector_collection_name="private-vector-name",
        artifact_prefix="private/artifact/prefix",
        document_count=13,
        chunk_count=87,
    )
    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        capability_id=capability.id,
        status="completed",
        trigger="chat_agentic",
        input_ref={
            "query": "Controlled retrieval "
            + (controlled_chat_marker(DEPLOYMENT_ID, SHA) if marker else "missing"),
            "chat_execution": {
                "route": "agentic",
                "executor_system_id": system.id,
                "executor_variant": AGENTIC_VARIANT,
            },
            "retrieval_contract": dict(ANDRITZ_RETRIEVAL_CONTRACT),
        },
        output_ref={
            "response": "must never appear in proof",
            "sources": [{"title": "must never appear"}],
        },
        flow_snapshot=flow,
    )
    invocation = SkillInvocation(
        id=str(uuid4()),
        run_id=run.id,
        skill_slug="semantic_search_v1",
        status="completed",
        input_ref={"query": "must never appear"},
        output_ref={"answer": "must never appear"},
        trace={
            "membrane_provenance": {
                "uri": f"object://{ARTIFACT_KEY}",
                "key": ARTIFACT_KEY,
                "sha256": hashlib.sha256(ARTIFACT_BYTES).hexdigest(),
                "size_bytes": len(ARTIFACT_BYTES),
            }
        },
    )
    db_session.add_all([workspace, capability, system, collection, run, invocation])
    db_session.commit()
    return SeededChat(workspace, capability, system, collection, run, invocation)


@pytest.mark.parametrize("capability_scope", ["global", "workspace"])
def test_safe_chat_audit_binds_complete_andritz_graph_without_content(
    db_session,
    capability_scope: str,
) -> None:
    seeded = _rows(db_session, capability_scope=capability_scope)

    report = audit_safe_chat_run(
        db_session,
        run_id=seeded.run.id,
        workspace_id=seeded.workspace.id,
        deployment_id=DEPLOYMENT_ID,
        candidate_sha=SHA,
        object_store=FakeStore(),
    )
    serialized = json.dumps(report).lower()

    assert report["schema_version"] == 2
    assert report["outcome"] == "passed"
    assert report["run_id"] == seeded.run.id
    assert report["system_id"] == seeded.system.id
    assert report["capability_id"] == seeded.capability.id
    assert report["knowledge_collection_id"] == seeded.collection.id
    assert report["knowledge_collection_chunk_count"] == 87
    assert report["invocation_count"] == 1
    assert report["invocation_status_counts"] == {"completed": 1}
    assert report["unexpected_skill_count"] == 0
    assert report["artifact_count"] == 1
    assert report["provenance_artifact"] == {
        "backend": "local",
        "key_sha256": hashlib.sha256(ARTIFACT_KEY.encode()).hexdigest(),
        "content_sha256": hashlib.sha256(ARTIFACT_BYTES).hexdigest(),
        "size": len(ARTIFACT_BYTES),
    }
    assert all(check["passed"] is True for check in report["checks"].values())
    for forbidden in (
        "controlled retrieval",
        "must never appear",
        "response",
        "sources",
        ANDRITZ_RETRIEVAL_CONTRACT["collection"],
        "private source collection name",
        "private-vector-name",
        "private/artifact/prefix",
    ):
        assert forbidden not in serialized


def test_safe_chat_audit_fails_without_marker(db_session) -> None:
    seeded = _rows(db_session, marker=False)

    report = audit_safe_chat_run(
        db_session,
        run_id=seeded.run.id,
        workspace_id=seeded.workspace.id,
        deployment_id=DEPLOYMENT_ID,
        candidate_sha=SHA,
        object_store=FakeStore(),
    )

    assert report["outcome"] == "failed"
    assert report["checks"]["input_marker_present"]["passed"] is False


@pytest.mark.parametrize(
    ("case", "failed_check"),
    [
        ("foreign_run_workspace", "workspace_is_andritz"),
        ("wrong_workspace_family", "workspace_family_is_andritz"),
        ("legacy_trigger", "trigger_is_strict_agentic_chat"),
        ("missing_system", "system_exists"),
        ("foreign_system", "system_is_active_andritz_system"),
        ("inactive_system", "system_is_active_andritz_system"),
        ("wrong_system_type", "system_type_is_agentic_chat"),
        ("wrong_system_variant", "system_flow_variant_is_agentic_chat"),
        ("wrong_run_variant", "run_flow_variant_matches_system"),
        ("wrong_migration_target", "migration_marker_targets_system"),
        ("run_capability_drift", "run_capability_matches_system"),
        ("missing_capability_binding", "capability_exists"),
        ("foreign_capability", "capability_is_visible_to_andritz"),
        ("classic_route", "chat_execution_routes_agentic"),
        ("wrong_executor", "chat_execution_targets_system"),
        ("wrong_executor_variant", "chat_execution_variant_is_agentic_chat"),
        ("system_retrieval_drift", "system_retrieval_contract_is_andritz"),
        ("run_retrieval_drift", "run_retrieval_contract_is_andritz"),
        ("missing_collection", "knowledge_collection_exists"),
        ("foreign_collection", "knowledge_collection_exists"),
        ("collection_not_ready", "knowledge_collection_is_ready"),
        ("collection_empty", "knowledge_collection_has_chunks"),
    ],
)
def test_safe_chat_audit_fails_closed_on_each_graph_link(
    db_session,
    case: str,
    failed_check: str,
) -> None:
    seeded = _rows(db_session)
    foreign_workspace = Workspace(
        id=str(uuid4()),
        name="Foreign",
        slug=f"foreign-{uuid4()}",
        settings={},
    )
    db_session.add(foreign_workspace)
    db_session.flush()

    if case == "foreign_run_workspace":
        seeded.run.workspace_id = foreign_workspace.id
    elif case == "wrong_workspace_family":
        seeded.workspace.settings = {**seeded.workspace.settings, "family": "other"}
    elif case == "legacy_trigger":
        seeded.run.trigger = "chat"
    elif case == "missing_system":
        seeded.run.system_id = None
    elif case == "foreign_system":
        seeded.system.workspace_id = foreign_workspace.id
    elif case == "inactive_system":
        seeded.system.status = "paused"
    elif case == "wrong_system_type":
        seeded.system.settings = {**seeded.system.settings, "system_type": "workspace_chat"}
    elif case == "wrong_system_variant":
        seeded.system.flow_definition = {
            **seeded.system.flow_definition,
            "variant": "wrong_variant",
        }
    elif case == "wrong_run_variant":
        seeded.run.flow_snapshot = {**seeded.run.flow_snapshot, "variant": "wrong_variant"}
    elif case == "wrong_migration_target":
        marker = dict(seeded.workspace.settings[ANDRITZ_MIGRATION_MARKER])
        marker["system_id"] = str(uuid4())
        seeded.workspace.settings = {
            **seeded.workspace.settings,
            ANDRITZ_MIGRATION_MARKER: marker,
        }
    elif case == "run_capability_drift":
        seeded.run.capability_id = None
    elif case == "missing_capability_binding":
        seeded.run.capability_id = None
        seeded.system.capability_id = None
    elif case == "foreign_capability":
        seeded.capability.workspace_id = foreign_workspace.id
    elif case in {"classic_route", "wrong_executor", "wrong_executor_variant"}:
        execution = dict(seeded.run.input_ref["chat_execution"])
        if case == "classic_route":
            execution["route"] = "classic"
        elif case == "wrong_executor":
            execution["executor_system_id"] = str(uuid4())
        else:
            execution["executor_variant"] = "wrong_variant"
        seeded.run.input_ref = {**seeded.run.input_ref, "chat_execution": execution}
    elif case == "system_retrieval_drift":
        contract = dict(ANDRITZ_RETRIEVAL_CONTRACT)
        contract["allow_workspace_fallback"] = True
        seeded.system.settings = {
            **seeded.system.settings,
            "retrieval_contract": contract,
        }
    elif case == "run_retrieval_drift":
        contract = dict(ANDRITZ_RETRIEVAL_CONTRACT)
        contract["allow_workspace_fallback"] = True
        seeded.run.input_ref = {**seeded.run.input_ref, "retrieval_contract": contract}
    elif case == "missing_collection":
        seeded.collection.slug = "unrelated-private-collection"
    elif case == "foreign_collection":
        seeded.collection.workspace_id = foreign_workspace.id
    elif case == "collection_not_ready":
        seeded.collection.status = "embedding"
    elif case == "collection_empty":
        seeded.collection.chunk_count = 0
    else:  # pragma: no cover - parameter list and mutation switch are coupled.
        raise AssertionError(f"unhandled case: {case}")
    db_session.commit()

    report = audit_safe_chat_run(
        db_session,
        run_id=seeded.run.id,
        workspace_id=seeded.workspace.id,
        deployment_id=DEPLOYMENT_ID,
        candidate_sha=SHA,
        object_store=FakeStore(),
    )

    assert report["outcome"] == "failed"
    assert report["checks"][failed_check]["passed"] is False


def test_safe_chat_audit_rejects_failed_invocation(db_session) -> None:
    seeded = _rows(db_session)
    seeded.invocation.status = "failed"
    db_session.commit()

    report = audit_safe_chat_run(
        db_session,
        run_id=seeded.run.id,
        workspace_id=seeded.workspace.id,
        deployment_id=DEPLOYMENT_ID,
        candidate_sha=SHA,
        object_store=FakeStore(),
    )

    assert report["outcome"] == "failed"
    assert report["checks"]["skill_invocation_ledger_completed"]["passed"] is False


def test_safe_chat_audit_fails_on_duplicate_or_tampered_artifact(db_session) -> None:
    seeded = _rows(db_session)
    seeded.invocation.trace = {
        **seeded.invocation.trace,
        "membrane": {"artifact": seeded.invocation.trace["membrane_provenance"]},
    }
    db_session.commit()

    duplicate = audit_safe_chat_run(
        db_session,
        run_id=seeded.run.id,
        workspace_id=seeded.workspace.id,
        deployment_id=DEPLOYMENT_ID,
        candidate_sha=SHA,
        object_store=FakeStore(),
    )
    assert duplicate["outcome"] == "failed"
    assert duplicate["checks"]["single_membrane_provenance_artifact"]["passed"] is False

    seeded.invocation.trace = {
        "membrane_provenance": {
            **seeded.invocation.trace["membrane_provenance"],
            "sha256": "f" * 64,
        }
    }
    db_session.commit()
    tampered = audit_safe_chat_run(
        db_session,
        run_id=seeded.run.id,
        workspace_id=seeded.workspace.id,
        deployment_id=DEPLOYMENT_ID,
        candidate_sha=SHA,
        object_store=FakeStore(),
    )
    assert tampered["outcome"] == "failed"
    assert tampered["checks"]["membrane_provenance_sha256_matches"]["passed"] is False


def test_safe_chat_audit_rejects_external_effect_skill_even_if_flow_declares_it(
    db_session,
) -> None:
    seeded = _rows(db_session)
    seeded.invocation.skill_slug = "mail_send_v1"
    seeded.run.flow_snapshot = {
        "schema_version": 3,
        "variant": AGENTIC_VARIANT,
        "nodes": [
            {
                "id": "send",
                "kind": "task",
                "config": {"skill_slug": "mail_send_v1"},
            }
        ],
        "edges": [],
    }
    db_session.commit()

    report = audit_safe_chat_run(
        db_session,
        run_id=seeded.run.id,
        workspace_id=seeded.workspace.id,
        deployment_id=DEPLOYMENT_ID,
        candidate_sha=SHA,
        object_store=FakeStore(),
    )

    assert report["outcome"] == "failed"
    assert report["unexpected_skill_count"] == 1
    assert report["checks"]["skill_invocations_declared_by_flow"]["passed"] is True
    assert report["checks"]["skill_invocations_read_generation_only"]["passed"] is False
    assert "mail_send_v1" not in json.dumps(report)
