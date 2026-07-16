"""Focused tests for the migration-059 Agentic rollout command."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm.attributes import flag_modified

from app.models.audit import AuditLog
from app.models.knowledge_collection import KnowledgeCollection
from app.models.policy import ControlPolicy
from app.models.system import System
from app.models.workspace import Workspace
from app.services import andritz_agentic_rollout as rollout
from app.services.chat_agentic_contract import is_expected_agentic_flow
from scripts import set_andritz_agentic_rollout as rollout_cli


def _load_migration_059():
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "059_andritz_agentic_default.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace(get_bind=lambda: None)
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("rollout_migration_059", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if saved is not None:
            sys.modules["alembic"] = saved
        else:
            sys.modules.pop("alembic", None)
    return module


MIGRATION_059 = _load_migration_059()


@pytest.fixture(autouse=True)
def _enable_agentic_chat(monkeypatch):
    monkeypatch.setattr(rollout.app_settings, "enable_agentic_chat", True)


def _valid_flow() -> dict:
    return deepcopy(
        json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "resources"
                / "flows"
                / "andritz_chat_agentic_v3.json"
            ).read_text(encoding="utf-8")
        )["flow_definition"]
    )


def test_runtime_flow_contract_pins_quality_hitl_and_egress_spine():
    settings = {
        "system_type": rollout.AGENTIC_SYSTEM_TYPE,
        "flow_revision": rollout.EXPECTED_FLOW_REVISION,
    }
    flow = _valid_flow()
    for node in flow["nodes"]:
        if node.get("kind") == "task":
            node.setdefault("config", {})["skill_id"] = f"installation-{node['id']}"
    assert is_expected_agentic_flow(settings, flow) is True

    permuted = deepcopy(flow)
    draft_index = next(
        index
        for index, edge in enumerate(permuted["edges"])
        if edge.get("from") == "task.generate" and edge.get("to") == "join.answer"
    )
    corrected_index = next(
        index
        for index, edge in enumerate(permuted["edges"])
        if edge.get("from") == "task.self_correct" and edge.get("to") == "join.answer"
    )
    permuted["edges"][draft_index], permuted["edges"][corrected_index] = (
        permuted["edges"][corrected_index],
        permuted["edges"][draft_index],
    )
    assert is_expected_agentic_flow(settings, permuted) is False

    removed = {
        "task.response_eval",
        "join.eval",
        "decision.verdict",
        "task.self_correct",
        "join.answer",
        "decision.egress_gate",
        "hitl.expert_review",
        "decision.deliver",
        "sink.ask_user",
        "sink.oos",
        "sink.final_answer",
    }
    flow["nodes"] = [node for node in flow["nodes"] if node.get("id") not in removed]
    flow["edges"] = [
        edge
        for edge in flow["edges"]
        if edge.get("from") not in removed and edge.get("to") not in removed
    ]

    assert is_expected_agentic_flow(settings, flow) is False


def test_system_lock_targets_only_the_non_nullable_system_table(db_session):
    sql = str(
        rollout._locked_system_query(db_session).statement.compile(
            dialect=postgresql.dialect(),
        )
    )

    assert "LEFT OUTER JOIN capabilities" in sql
    assert sql.rstrip().endswith("FOR UPDATE OF systems")


def _marker(*, system_id: str, policy_id: str) -> dict:
    return {
        "revision": rollout.MIGRATION_REVISION,
        "schema": rollout.MIGRATION_MARKER_SCHEMA,
        "system_id": system_id,
        "workspace": {"chat_execution": {"state": "absent"}},
        "system": {
            "retrieval_contract": {"state": "absent"},
            "execution_profile": {
                "container": "mapping",
                "max_runtime_s": {"state": "present", "value": 55},
            },
        },
        "control_policy": {
            "id": policy_id,
            "inbound_container": "mapping",
            "collection_allowlist": {"state": "present", "value": []},
        },
        "applied": {
            "chat_execution": deepcopy(rollout._IMMUTABLE_CHAT_EXECUTION),
            "retrieval_contract": deepcopy(rollout.STRICT_RETRIEVAL_CONTRACT),
            "execution_profile_max_runtime_s": 40,
            "collection_allowlist": [rollout.NOTICES_COLLECTION],
            "flow_revision": rollout.EXPECTED_FLOW_REVISION,
        },
    }


def _seed_contract(
    db_session,
    *,
    slug: str | None = None,
    percentage: int | float = 0,
) -> tuple[Workspace, System, ControlPolicy]:
    token = uuid4().hex
    workspace_id = f"ws-{token}"
    system_id = f"sys-{token}"
    policy_id = f"policy-{token}"
    chat_execution = deepcopy(rollout._IMMUTABLE_CHAT_EXECUTION)
    chat_execution["rollout"]["percentage"] = percentage
    workspace = Workspace(
        id=workspace_id,
        name="Andritz rollout test",
        slug=slug or f"andritz-{token}",
        settings={
            "family": "andritz",
            "branding": {"name": "ANDRITZ"},
            "chat_execution": chat_execution,
            rollout.MIGRATION_MARKER_KEY: _marker(
                system_id=system_id,
                policy_id=policy_id,
            ),
        },
    )
    policy = ControlPolicy(
        id=policy_id,
        workspace_id=workspace_id,
        name="Andritz Agentic membrane",
        scope="system",
        target_id=system_id,
        extra={
            "membrane_spec": {
                "inbound": {
                    "collection_allowlist": [rollout.NOTICES_COLLECTION],
                    "reject_cross_project_sources": True,
                },
                "outbound": {"expert_review_required": False},
            },
            "unrelated": "preserved",
        },
    )
    system = System(
        id=system_id,
        workspace_id=workspace_id,
        name="Andritz Chat Agentic",
        objective="Grounded Agentic chat",
        status="active",
        settings={
            "system_type": rollout.AGENTIC_SYSTEM_TYPE,
            "flow_revision": rollout.EXPECTED_FLOW_REVISION,
            "retrieval_contract": deepcopy(rollout.STRICT_RETRIEVAL_CONTRACT),
            "unrelated": "preserved",
        },
        flow_definition=_valid_flow(),
        execution_profile={"max_runtime_s": 40, "latency_target_ms": 2500},
        control_policy_id=policy_id,
    )
    collection = KnowledgeCollection(
        id=f"collection-{token}",
        workspace_id=workspace_id,
        slug=rollout.NOTICES_COLLECTION,
        name="Andritz SPL notices",
        description="test",
        status="ready",
        vector_collection_name=f"{workspace.slug}__{rollout.NOTICES_COLLECTION}",
        artifact_prefix=f"workspaces/{workspace_id}/collections/{rollout.NOTICES_COLLECTION}",
        document_count=8,
        chunk_count=128,
    )
    db_session.add_all([workspace, policy, system, collection])
    db_session.flush()
    return workspace, system, policy


def _replace_settings(entity, settings: dict) -> None:
    entity.settings = deepcopy(settings)
    flag_modified(entity, "settings")


def test_rollout_updates_only_percentage_and_writes_atomic_audit(db_session):
    workspace, system, policy = _seed_contract(db_session, percentage=0)
    before = deepcopy(workspace.settings)

    result = rollout.set_andritz_agentic_rollout(
        db_session,
        percentage=25,
        actor="operator@datategy.net",
    )

    assert result.as_dict()["workspace_count"] == 1
    assert result.workspaces[0].changed is True
    expected = deepcopy(before)
    expected["chat_execution"]["rollout"]["percentage"] = 25
    assert workspace.settings == expected
    assert system.settings["retrieval_contract"] == rollout.STRICT_RETRIEVAL_CONTRACT
    assert policy.extra["membrane_spec"]["inbound"]["collection_allowlist"] == [
        rollout.NOTICES_COLLECTION
    ]

    audit = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.workspace_id == workspace.id,
            AuditLog.event_type == rollout.AUDIT_EVENT_TYPE,
        )
        .one()
    )
    assert audit.actor == "operator@datategy.net"
    assert audit.agent_id == system.id
    assert audit.details == {
        "migration_revision": rollout.MIGRATION_REVISION,
        "policy_version": 1,
        "target": {
            "system_type": rollout.AGENTIC_SYSTEM_TYPE,
            "variant": rollout.AGENTIC_VARIANT,
            "system_id": system.id,
        },
        "previous_percentage": 0,
        "percentage": 25,
        "changed": True,
        "retrieval_collection": rollout.NOTICES_COLLECTION,
        "collection_status": "ready",
        "collection_chunk_count": 128,
        "flow_revision": rollout.EXPECTED_FLOW_REVISION,
        "agentic_kill_switch_enabled": True,
        "control_policy_id": policy.id,
    }
    assert result.workspaces[0].audit_event_id == audit.id


def test_rollout_accepts_the_marker_envelope_emitted_by_migration_059(db_session):
    workspace, system, policy = _seed_contract(db_session, percentage=0)
    marker = MIGRATION_059._new_marker(
        {"family": "andritz"},
        system_id=system.id,
        system_settings={
            "system_type": rollout.AGENTIC_SYSTEM_TYPE,
            "flow_revision": rollout.EXPECTED_FLOW_REVISION,
        },
        execution_profile={"max_runtime_s": 55},
        control_policy_id=policy.id,
        control_policy_extra={
            "membrane_spec": {
                "inbound": {"collection_allowlist": []},
            }
        },
    )
    settings = deepcopy(workspace.settings)
    settings[rollout.MIGRATION_MARKER_KEY] = marker
    _replace_settings(workspace, settings)

    result = rollout.set_andritz_agentic_rollout(
        db_session,
        percentage=5,
        actor="operator@datategy.net",
    )

    assert result.workspaces[0].percentage == 5
    assert workspace.settings["chat_execution"]["rollout"]["percentage"] == 5


def test_dry_run_validates_but_never_mutates_or_audits(db_session):
    workspace, _, _ = _seed_contract(db_session, percentage=5)
    before = deepcopy(workspace.settings)

    result = rollout.set_andritz_agentic_rollout(
        db_session,
        percentage=50,
        actor="operator@datategy.net",
        dry_run=True,
    )

    assert result.dry_run is True
    assert result.workspaces[0].previous_percentage == 5
    assert result.workspaces[0].percentage == 50
    assert result.workspaces[0].audit_event_id is None
    assert workspace.settings == before
    assert db_session.query(AuditLog).filter(AuditLog.workspace_id == workspace.id).count() == 0


@pytest.mark.parametrize(
    ("drift", "message"),
    [
        ("chat_policy", "immutable drift"),
        ("retrieval", "strict Andritz notices"),
        ("runtime", "max_runtime_s"),
        ("membrane", "membrane allowlist"),
        ("binding", "ControlPolicy binding"),
        ("flow_revision", "exactly one active canonical"),
        ("flow_topology", "exactly one active canonical"),
    ],
)
def test_rollout_fails_closed_on_owned_contract_drift(db_session, drift, message):
    workspace, system, policy = _seed_contract(db_session)
    if drift == "chat_policy":
        settings = deepcopy(workspace.settings)
        settings["chat_execution"]["fallback"] = "workspace"
        _replace_settings(workspace, settings)
    elif drift == "retrieval":
        settings = deepcopy(system.settings)
        settings["retrieval_contract"]["allow_workspace_fallback"] = True
        _replace_settings(system, settings)
    elif drift == "runtime":
        system.execution_profile = {"max_runtime_s": 41}
        flag_modified(system, "execution_profile")
    elif drift == "membrane":
        extra = deepcopy(policy.extra)
        extra["membrane_spec"]["inbound"]["collection_allowlist"] = []
        policy.extra = extra
        flag_modified(policy, "extra")
    elif drift == "flow_revision":
        settings = deepcopy(system.settings)
        settings["flow_revision"] = "stale-flow"
        _replace_settings(system, settings)
    elif drift == "flow_topology":
        system.flow_definition = {
            "variant": rollout.AGENTIC_VARIANT,
            "nodes": [],
            "edges": [],
        }
        flag_modified(system, "flow_definition")
    else:
        system.control_policy_id = None
    before = deepcopy(workspace.settings)

    with pytest.raises(rollout.RolloutInvariantError, match=message):
        rollout.set_andritz_agentic_rollout(
            db_session,
            percentage=10,
            actor="operator@datategy.net",
        )

    assert workspace.settings == before
    assert db_session.query(AuditLog).filter(AuditLog.workspace_id == workspace.id).count() == 0


@pytest.mark.parametrize(
    ("drift", "audit_fragment"),
    [
        ("disabled", "status is 'retired'"),
        ("chat_policy", "immutable drift"),
        ("flow_topology", "canonical Agentic chat flow"),
        ("retrieval", "strict Andritz notices"),
        ("runtime", "max_runtime_s"),
        ("membrane", "membrane allowlist"),
        ("binding", "ControlPolicy binding"),
    ],
)
def test_zero_percentage_is_audited_risk_reduction_despite_runtime_drift(
    db_session,
    drift,
    audit_fragment,
):
    workspace, system, policy = _seed_contract(db_session, percentage=50)
    if drift == "disabled":
        system.status = "retired"
    elif drift == "chat_policy":
        settings = deepcopy(workspace.settings)
        settings["chat_execution"]["fallback"] = "workspace"
        _replace_settings(workspace, settings)
    elif drift == "flow_topology":
        system.flow_definition = {
            "variant": rollout.AGENTIC_VARIANT,
            "nodes": [],
            "edges": [],
        }
        flag_modified(system, "flow_definition")
    elif drift == "retrieval":
        settings = deepcopy(system.settings)
        settings["retrieval_contract"]["allow_workspace_fallback"] = True
        _replace_settings(system, settings)
    elif drift == "runtime":
        system.execution_profile = {"max_runtime_s": 41}
        flag_modified(system, "execution_profile")
    elif drift == "membrane":
        extra = deepcopy(policy.extra)
        extra["membrane_spec"]["inbound"]["collection_allowlist"] = []
        policy.extra = extra
        flag_modified(policy, "extra")
    else:
        system.control_policy_id = None
    db_session.flush()

    result = rollout.set_andritz_agentic_rollout(
        db_session,
        percentage=0,
        actor="rollback@datategy.net",
    )

    assert workspace.settings["chat_execution"]["rollout"]["percentage"] == 0
    assert result.workspaces[0].previous_percentage == 50
    assert result.workspaces[0].changed is True
    assert any(
        audit_fragment in invariant for invariant in result.workspaces[0].degraded_invariants
    )
    audit = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.workspace_id == workspace.id,
            AuditLog.event_type == rollout.AUDIT_EVENT_TYPE,
        )
        .one()
    )
    assert audit.severity == "warning"
    assert audit.details["validation_mode"] == "risk_reduction_rollback"
    assert audit.details["previous_percentage"] == 50
    assert audit.details["percentage"] == 0
    assert any(audit_fragment in invariant for invariant in audit.details["degraded_invariants"])


def test_zero_percentage_still_requires_a_valid_migration_marker(db_session):
    workspace, _, _ = _seed_contract(db_session, percentage=50)
    settings = deepcopy(workspace.settings)
    settings[rollout.MIGRATION_MARKER_KEY]["revision"] = "058_stale"
    _replace_settings(workspace, settings)

    with pytest.raises(rollout.RolloutInvariantError, match="invalid migration 059 marker"):
        rollout.set_andritz_agentic_rollout(
            db_session,
            percentage=0,
            actor="rollback@datategy.net",
        )

    assert workspace.settings["chat_execution"]["rollout"]["percentage"] == 50
    assert db_session.query(AuditLog).filter(AuditLog.workspace_id == workspace.id).count() == 0


@pytest.mark.parametrize("marker_drift", ["applied", "snapshot"])
def test_zero_percentage_audits_non_identity_marker_drift_instead_of_blocking(
    db_session,
    marker_drift,
):
    workspace, _, _ = _seed_contract(db_session, percentage=50)
    settings = deepcopy(workspace.settings)
    marker = settings[rollout.MIGRATION_MARKER_KEY]
    if marker_drift == "applied":
        marker["applied"]["flow_revision"] = "stale-flow"
    else:
        marker["workspace"]["chat_execution"] = {"state": "corrupt"}
    _replace_settings(workspace, settings)

    result = rollout.set_andritz_agentic_rollout(
        db_session,
        percentage=0,
        actor="rollback@datategy.net",
    )

    assert workspace.settings["chat_execution"]["rollout"]["percentage"] == 0
    degraded = result.workspaces[0].degraded_invariants
    assert any("migration marker contract drift" in item for item in degraded)
    audit = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.workspace_id == workspace.id,
            AuditLog.event_type == rollout.AUDIT_EVENT_TYPE,
        )
        .one()
    )
    assert audit.severity == "warning"
    assert any(
        "migration marker contract drift" in item for item in audit.details["degraded_invariants"]
    )


def test_positive_rollout_remains_fail_closed_on_non_identity_marker_drift(db_session):
    workspace, _, _ = _seed_contract(db_session, percentage=0)
    settings = deepcopy(workspace.settings)
    settings[rollout.MIGRATION_MARKER_KEY]["applied"]["flow_revision"] = "stale-flow"
    _replace_settings(workspace, settings)

    with pytest.raises(rollout.RolloutInvariantError, match="invalid migration 059 marker"):
        rollout.set_andritz_agentic_rollout(
            db_session,
            percentage=5,
            actor="operator@datategy.net",
        )

    assert workspace.settings["chat_execution"]["rollout"]["percentage"] == 0


def test_zero_percentage_audits_all_concurrent_runtime_degradations(db_session):
    workspace, system, policy = _seed_contract(db_session, percentage=80)
    system.status = "paused"
    system.flow_definition = {"variant": rollout.AGENTIC_VARIANT, "nodes": [], "edges": []}
    system_settings = deepcopy(system.settings)
    system_settings["retrieval_contract"]["allow_workspace_fallback"] = True
    _replace_settings(system, system_settings)
    system.execution_profile = {"max_runtime_s": 99}
    flag_modified(system, "execution_profile")
    system.control_policy_id = None
    policy_extra = deepcopy(policy.extra)
    policy_extra["membrane_spec"]["inbound"]["collection_allowlist"] = []
    policy.extra = policy_extra
    flag_modified(policy, "extra")
    collection = (
        db_session.query(KnowledgeCollection)
        .filter(KnowledgeCollection.workspace_id == workspace.id)
        .one()
    )
    collection.status = "embedding"
    collection.chunk_count = 0
    db_session.flush()

    result = rollout.set_andritz_agentic_rollout(
        db_session,
        percentage=0,
        actor="rollback@datategy.net",
    )

    degraded = "\n".join(result.workspaces[0].degraded_invariants)
    for fragment in (
        "status is 'paused'",
        "canonical Agentic chat flow",
        "strict Andritz notices retrieval contract",
        "max_runtime_s",
        "ControlPolicy binding",
        "membrane allowlist",
        "is not ready",
        "has no indexed chunks",
    ):
        assert fragment in degraded
    assert workspace.settings["chat_execution"]["rollout"]["percentage"] == 0


def test_zero_percentage_requires_an_identifiable_current_percentage(db_session):
    workspace, system, _ = _seed_contract(db_session, percentage=50)
    settings = deepcopy(workspace.settings)
    settings["chat_execution"]["rollout"].pop("percentage")
    _replace_settings(workspace, settings)
    before = deepcopy(workspace.settings)

    with pytest.raises(rollout.RolloutInvariantError, match="invalid current rollout percentage"):
        rollout.set_andritz_agentic_rollout(
            db_session,
            percentage=0,
            actor="rollback@datategy.net",
        )

    assert workspace.settings == before
    assert system.status == "active"
    assert db_session.query(AuditLog).filter(AuditLog.workspace_id == workspace.id).count() == 0


def test_zero_percentage_survives_family_drift_and_audits_it(db_session):
    workspace, _, _ = _seed_contract(db_session, percentage=75)
    settings = deepcopy(workspace.settings)
    settings["family"] = "generic"
    _replace_settings(workspace, settings)

    result = rollout.set_andritz_agentic_rollout(
        db_session,
        percentage=0,
        actor="rollback@datategy.net",
    )

    assert workspace.settings["chat_execution"]["rollout"]["percentage"] == 0
    assert any("family drift" in item for item in result.workspaces[0].degraded_invariants)
    audit = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.workspace_id == workspace.id,
            AuditLog.event_type == rollout.AUDIT_EVENT_TYPE,
        )
        .one()
    )
    assert any("family drift" in item for item in audit.details["degraded_invariants"])


def test_zero_percentage_validates_the_fleet_before_staging_any_write(db_session):
    first, _, _ = _seed_contract(db_session, percentage=50)
    second, _, _ = _seed_contract(db_session, percentage=75)
    second_settings = deepcopy(second.settings)
    second_settings["chat_execution"]["rollout"]["percentage"] = "unknown"
    _replace_settings(second, second_settings)

    with pytest.raises(rollout.RolloutInvariantError, match="invalid current rollout percentage"):
        rollout.set_andritz_agentic_rollout(
            db_session,
            percentage=0,
            actor="rollback@datategy.net",
        )

    assert first.settings["chat_execution"]["rollout"]["percentage"] == 50
    assert second.settings["chat_execution"]["rollout"]["percentage"] == "unknown"
    assert (
        db_session.query(AuditLog).filter(AuditLog.workspace_id.in_([first.id, second.id])).count()
        == 0
    )


def test_exactly_one_active_target_is_required(db_session):
    workspace, system, _ = _seed_contract(db_session)
    duplicate = System(
        id=f"duplicate-{uuid4().hex}",
        workspace_id=workspace.id,
        name="Duplicate active target",
        objective="invalid",
        status="active",
        settings={
            "system_type": rollout.AGENTIC_SYSTEM_TYPE,
            "flow_revision": rollout.EXPECTED_FLOW_REVISION,
        },
        flow_definition=_valid_flow(),
    )
    db_session.add(duplicate)
    db_session.flush()

    with pytest.raises(rollout.RolloutInvariantError, match="exactly one"):
        rollout.set_andritz_agentic_rollout(
            db_session,
            percentage=5,
            actor="operator@datategy.net",
        )
    assert workspace.settings["chat_execution"]["rollout"]["percentage"] == 0
    assert system.status == "active"


@pytest.mark.parametrize(
    ("status", "chunk_count", "message"),
    [
        ("embedding", 128, "is not ready"),
        ("ready", 0, "has no indexed chunks"),
    ],
)
def test_positive_rollout_requires_ready_nonempty_collection(
    db_session,
    status,
    chunk_count,
    message,
):
    workspace, _, _ = _seed_contract(db_session)
    collection = (
        db_session.query(KnowledgeCollection)
        .filter(KnowledgeCollection.workspace_id == workspace.id)
        .one()
    )
    collection.status = status
    collection.chunk_count = chunk_count
    db_session.flush()

    with pytest.raises(rollout.RolloutInvariantError, match=message):
        rollout.set_andritz_agentic_rollout(
            db_session,
            percentage=5,
            actor="operator@datategy.net",
        )

    assert workspace.settings["chat_execution"]["rollout"]["percentage"] == 0


def test_positive_rollout_refuses_unmarked_andritz_workspace(db_session):
    marked, _, _ = _seed_contract(db_session)
    unmarked = Workspace(
        id=str(uuid4()),
        name="Unprovisioned Andritz",
        slug=f"andritz-unmarked-{uuid4().hex[:8]}",
        settings={"family": "andritz"},
    )
    db_session.add(unmarked)
    db_session.flush()

    with pytest.raises(rollout.RolloutInvariantError, match="missing migration 059 marker"):
        rollout.set_andritz_agentic_rollout(
            db_session,
            percentage=5,
            actor="operator@datategy.net",
        )

    assert marked.settings["chat_execution"]["rollout"]["percentage"] == 0


def test_positive_rollout_refuses_disabled_master_switch(db_session, monkeypatch):
    workspace, _, _ = _seed_contract(db_session)
    monkeypatch.setattr(rollout.app_settings, "enable_agentic_chat", False)

    with pytest.raises(rollout.RolloutInvariantError, match="ENABLE_AGENTIC_CHAT is disabled"):
        rollout.set_andritz_agentic_rollout(
            db_session,
            percentage=5,
            actor="operator@datategy.net",
        )

    assert workspace.settings["chat_execution"]["rollout"]["percentage"] == 0


def test_fleet_is_validated_before_any_workspace_is_changed(db_session):
    first, _, _ = _seed_contract(db_session, percentage=0)
    second, second_system, _ = _seed_contract(db_session, percentage=0)
    second_system.execution_profile = {"max_runtime_s": 39}
    flag_modified(second_system, "execution_profile")

    with pytest.raises(rollout.RolloutInvariantError, match="max_runtime_s"):
        rollout.set_andritz_agentic_rollout(
            db_session,
            percentage=25,
            actor="operator@datategy.net",
        )

    assert first.settings["chat_execution"]["rollout"]["percentage"] == 0
    assert second.settings["chat_execution"]["rollout"]["percentage"] == 0
    assert (
        db_session.query(AuditLog).filter(AuditLog.workspace_id.in_([first.id, second.id])).count()
        == 0
    )


@pytest.mark.parametrize("value", [-1, 101, "nan", "inf", True, "not-a-number"])
def test_percentage_validation_is_fail_closed(value):
    with pytest.raises(ValueError, match="between 0 and 100"):
        rollout.normalize_percentage(value)


def test_cli_commits_success_and_emits_machine_readable_report(db_session, capsys):
    workspace, _, _ = _seed_contract(db_session, percentage=0)
    db_session.commit()

    exit_code = rollout_cli.main(
        [
            "--percentage",
            "5",
            "--actor",
            "operator@datategy.net",
        ]
    )

    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["percentage"] == 5
    assert report["workspace_count"] == 1
    db_session.expire_all()
    refreshed = db_session.get(Workspace, workspace.id)
    assert refreshed.settings["chat_execution"]["rollout"]["percentage"] == 5
    assert (
        db_session.query(AuditLog)
        .filter(
            AuditLog.workspace_id == workspace.id,
            AuditLog.event_type == rollout.AUDIT_EVENT_TYPE,
        )
        .count()
        == 1
    )


def test_cli_returns_nonzero_and_rolls_back_on_invariant_failure(db_session, capsys):
    workspace, system, _ = _seed_contract(db_session, percentage=0)
    system.execution_profile = {"max_runtime_s": 99}
    flag_modified(system, "execution_profile")
    db_session.commit()

    exit_code = rollout_cli.main(
        [
            "--percentage",
            "5",
            "--actor",
            "operator@datategy.net",
        ]
    )

    assert exit_code == 2
    assert "refused" in capsys.readouterr().err
    db_session.expire_all()
    refreshed = db_session.get(Workspace, workspace.id)
    assert refreshed.settings["chat_execution"]["rollout"]["percentage"] == 0
    assert db_session.query(AuditLog).filter(AuditLog.workspace_id == workspace.id).count() == 0
