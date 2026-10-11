"""Contract tests for the authorization-v2 shadow evidence collector."""
from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import runs, systems
from app.models.audit import AuditLog
from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember
from app.services.iam.decision_plane import candidate_config_sha256
from app.services.iam.shadow_review import (
    record_mismatch_review,
    sha256_ref,
    validate_source_manifest,
)
from scripts import collect_authorization_v2_shadow as collector
from scripts import rollout_authorization_v2 as promoter

REVISION = "a" * 40
PRODUCER = {
    "issuer": "https://gitlab.example.test",
    "project_id": "42",
    "pipeline_id": "314",
    "job_id": "159",
    "commit_sha": REVISION,
    "ref": "demo/agentic",
    "ref_protected": True,
}


@pytest.fixture(autouse=True)
def _trusted_runner_settings(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(
        settings,
        "authorization_v2_trusted_oidc_issuer",
        PRODUCER["issuer"],
    )
    monkeypatch.setattr(settings, "authorization_v2_trusted_project_id", "42")
    monkeypatch.setattr(settings, "authorization_v2_trusted_ref", "demo/agentic")
    monkeypatch.setattr(settings, "agentium_image_revision", REVISION)


def _seed_workspace(db):
    workspace = Workspace(
        id=str(uuid4()),
        name="Opaque workspace",
        slug=f"opaque-{uuid4()}",
        settings={"family": "generic"},
    )
    config = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        version=3,
        role_flags={},
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "modes": {"system.read": "shadow", "run.read": "shadow"},
            }
        },
    )
    db.add_all([workspace, config])
    db.commit()
    return workspace


def _event(workspace, *, action="system.read", mismatch=False, timestamp=None):
    return AuditLog(
        id=str(uuid4()),
        workspace_id=workspace.id,
        timestamp=(timestamp or datetime.now(UTC)).replace(tzinfo=None),
        event_type=collector.EVENT_TYPE,
        actor="opaque-user",
        details={
            "origin": "server",
            "resource": {"kind": action.split(".", maxsplit=1)[0]},
            "action": action,
            "evaluation_count": 1,
            "legacy_allowed": 1,
            "legacy_denied": 0,
            "candidate_allowed": 0 if mismatch else 1,
            "candidate_denied": 1 if mismatch else 0,
            "matches": 0 if mismatch else 1,
            "mismatches": 1 if mismatch else 0,
            "policy_id": "policy-v2",
            "policy_version": 2,
            "configured_mode": "shadow",
            "runtime_revision": REVISION,
            "candidate_config_sha256": candidate_config_sha256(workspace.iam_config),
            "candidate_config_version": workspace.iam_config.version,
        },
    )


def _junit(tmp_path, name, *, failed=False, skipped=False):
    failure = '<failure message="boom" />' if failed else ""
    skipped_node = "<skipped />" if skipped else ""
    path = tmp_path / f"{name}.xml"
    path.write_text(
        (
            '<testsuite tests="1"><properties>'
            f'<property name="agentium.git_revision" value="{REVISION}" />'
            f'<property name="agentium.ci_issuer" value="{PRODUCER["issuer"]}" />'
            f'<property name="agentium.ci_project_id" value="{PRODUCER["project_id"]}" />'
            f'<property name="agentium.ci_pipeline_id" value="{PRODUCER["pipeline_id"]}" />'
            f'<property name="agentium.ci_job_id" value="{PRODUCER["job_id"]}" />'
            f'<property name="agentium.ci_ref" value="{PRODUCER["ref"]}" />'
            '<property name="agentium.ci_ref_protected" value="true" />'
            '</properties>'
            f'<testcase classname="gate" name="{name}">{failure}{skipped_node}</testcase></testsuite>'
        ),
        encoding="utf-8",
    )
    return path


def _collect(db, workspace_id, start, end, tmp_path, *, mismatch_review_id=None):
    return collector.collect(
        db,
        workspace_id=workspace_id,
        actions=["system.read", "run.read"],
        revision=REVISION,
        window_started_at=start,
        window_ended_at=end,
        validated_at=end + timedelta(minutes=1),
        validated_by="protected-gate",
        environment="test",
        legacy_junit=_junit(tmp_path, "legacy"),
        candidate_junit=_junit(tmp_path, "candidate"),
        trusted_runner=PRODUCER,
        mismatch_review_id=mismatch_review_id,
    )


def test_collector_builds_content_addressed_balanced_evidence(db_session, tmp_path):
    workspace = _seed_workspace(db_session)
    end = datetime.now(UTC)
    start = end - timedelta(hours=1)
    db_session.add_all(
        [
            _event(workspace, action="system.read", timestamp=start + timedelta(minutes=1)),
            _event(workspace, action="run.read", timestamp=start + timedelta(minutes=2)),
            _event(
                workspace,
                action="capability.read",
                timestamp=start + timedelta(minutes=3),
            ),
        ]
    )
    db_session.commit()

    report = _collect(db_session, workspace.id, start, end, tmp_path)
    assert report["result"] == "passed"
    assert report["blockers"] == []
    assert report["subject"] == {
        "workspace_id": workspace.id,
        "actions": ["run.read", "system.read"],
        "revision": REVISION,
    }
    observation = report["shadow_observation"]
    assert observation["source_ref"].startswith("sha256:")
    assert len(observation["source_ref"]) == 71
    assert len(observation["source_manifest"]["rows"]) == 2
    assert observation["runtime_revision"] == REVISION
    assert observation["candidate_config_sha256"] == candidate_config_sha256(workspace.iam_config)
    assert report["contracts"]["legacy"]["artifact_ref"].startswith("sha256:")
    assert report["contracts"]["legacy"]["test_count"] == 1
    assert all(
        row["evaluations"] == 1 and row["unexplained_mismatches"] == 0
        for row in observation["actions"].values()
    )


def test_real_boundary_events_flow_through_collector_and_atomic_promotion(
    db_session,
    tmp_path,
):
    """Prove the canonical action key from decision boundary to enforcement."""

    workspace = _seed_workspace(db_session)
    user = User(
        id=str(uuid4()),
        username=f"boundary-{uuid4()}@example.test",
        email=f"boundary-{uuid4()}@example.test",
        role="user",
    )
    membership = WorkspaceMember(
        user_id=user.id,
        workspace_id=workspace.id,
        role="admin",
        role_template="workspace_admin",
    )
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Boundary System",
        objective="Exercise a real HTTP authorization boundary.",
        status="active",
    )
    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        initiated_by_user_id=user.id,
        status="completed",
    )
    db_session.add_all([user, membership, system, run])
    db_session.commit()

    started_at = datetime.now(UTC) - timedelta(seconds=1)
    app = FastAPI()
    app.include_router(systems.router, prefix="/systems")
    app.include_router(runs.router, prefix="/runs")
    for dependency in {
        systems.get_current_workspace,
        runs.get_current_workspace,
    }:
        app.dependency_overrides[dependency] = lambda: workspace
    for dependency in {systems.get_current_user, runs.get_current_user}:
        app.dependency_overrides[dependency] = lambda: user
    for dependency in {systems.get_db, runs.get_db}:
        app.dependency_overrides[dependency] = lambda: db_session
    client = TestClient(app)
    assert client.get("/systems").status_code == 200
    assert client.get(f"/runs/{run.id}").status_code == 200
    ended_at = datetime.now(UTC) + timedelta(seconds=1)
    db_session.expire_all()

    report = _collect(
        db_session,
        workspace.id,
        started_at,
        ended_at,
        tmp_path,
    )
    assert report["result"] == "passed"
    source_rows = report["shadow_observation"]["source_manifest"]["rows"]
    assert {row["action"] for row in source_rows} == {"system.read", "run.read"}
    assert all(
        report["shadow_observation"]["actions"][action]["evaluations"] == 1
        for action in ("system.read", "run.read")
    )

    result = promoter.promote(
        db_session,
        workspace_id=workspace.id,
        actions=["system.read", "run.read"],
        revision=REVISION,
        evidence=report,
        apply=True,
        actor="protected-gate@example.test",
        trusted_runner=PRODUCER,
    )
    assert result["changed"] is True
    db_session.refresh(workspace.iam_config)
    policy = workspace.iam_config.capability_overrides["authorization_v2"]
    assert policy["modes"] == {"system.read": "enforce", "run.read": "enforce"}
    assert set(policy["enforcement_attestations"]) == {"system.read", "run.read"}


def test_collector_blocks_missing_or_mismatched_observations(db_session, tmp_path):
    workspace = _seed_workspace(db_session)
    end = datetime.now(UTC)
    start = end - timedelta(hours=1)
    db_session.add(
        _event(
            workspace,
            action="system.read",
            mismatch=True,
            timestamp=start + timedelta(minutes=1),
        )
    )
    db_session.commit()

    report = _collect(db_session, workspace.id, start, end, tmp_path)
    assert report["result"] == "blocked"
    assert {blocker["code"] for blocker in report["blockers"]} == {
        "missing_observations",
        "unexplained_mismatches",
    }
    assert report["shadow_observation"]["actions"]["system.read"] == {
        "evaluations": 1,
        "legacy_allowed": 1,
        "legacy_denied": 0,
        "candidate_allowed": 0,
        "candidate_denied": 1,
        "matches": 0,
        "mismatches": 1,
        "explained_mismatches": 0,
        "unexplained_mismatches": 1,
    }


def test_authenticated_persisted_review_explains_exact_mismatch_rows(
    db_session,
    tmp_path,
):
    workspace = _seed_workspace(db_session)
    end = datetime.now(UTC)
    start = end - timedelta(hours=1)
    mismatch = _event(
        workspace,
        action="system.read",
        mismatch=True,
        timestamp=start + timedelta(minutes=1),
    )
    db_session.add_all(
        [
            mismatch,
            _event(
                workspace,
                action="run.read",
                timestamp=start + timedelta(minutes=2),
            ),
        ]
    )
    db_session.commit()

    raw = _collect(db_session, workspace.id, start, end, tmp_path)
    assert raw["result"] == "blocked"
    observation = raw["shadow_observation"]
    source = validate_source_manifest(
        observation["source_manifest"],
        source_ref=observation["source_ref"],
        workspace_id=workspace.id,
        actions=["run.read", "system.read"],
        revision=REVISION,
        candidate_config_sha256=candidate_config_sha256(workspace.iam_config),
        candidate_config_version=workspace.iam_config.version,
        window_started_at=start,
        window_ended_at=end,
    )
    review = record_mismatch_review(
        db_session,
        source=source,
        reviewer_user_id="security-reviewer-id",
        reviewer_identity="security-reviewer@example.net",
        reviewed_at=end + timedelta(seconds=30),
        entries=[
            {
                "action": "system.read",
                "observation_ids": [mismatch.id],
                "reason_code": "reviewer_role_separation",
                "reason": "Reviewer execution rights are intentionally removed in policy v2.",
            }
        ],
    )
    db_session.commit()

    reviewed = _collect(
        db_session,
        workspace.id,
        start,
        end,
        tmp_path,
        mismatch_review_id=review["audit_id"],
    )
    assert reviewed["result"] == "passed"
    assert reviewed["blockers"] == []
    summary = reviewed["shadow_observation"]["actions"]["system.read"]
    assert summary["explained_mismatches"] == 1
    assert summary["unexplained_mismatches"] == 0
    assert reviewed["shadow_observation"]["mismatch_review"] == review


def test_review_rejects_a_self_consistent_manifest_that_omits_an_audit_row(
    db_session,
    tmp_path,
):
    workspace = _seed_workspace(db_session)
    end = datetime.now(UTC)
    start = end - timedelta(hours=1)
    included = _event(
        workspace,
        action="system.read",
        mismatch=True,
        timestamp=start + timedelta(minutes=1),
    )
    omitted = _event(
        workspace,
        action="system.read",
        mismatch=True,
        timestamp=start + timedelta(minutes=2),
    )
    db_session.add_all(
        [
            included,
            omitted,
            _event(workspace, action="run.read", timestamp=start + timedelta(minutes=3)),
        ]
    )
    db_session.commit()

    raw = _collect(db_session, workspace.id, start, end, tmp_path)
    source_document = copy.deepcopy(raw["shadow_observation"]["source_manifest"])
    source_document["rows"] = [row for row in source_document["rows"] if row["id"] != omitted.id]
    source_ref = sha256_ref(source_document)
    source = validate_source_manifest(
        source_document,
        source_ref=source_ref,
        workspace_id=workspace.id,
        actions=["run.read", "system.read"],
        revision=REVISION,
        candidate_config_sha256=candidate_config_sha256(workspace.iam_config),
        candidate_config_version=workspace.iam_config.version,
        window_started_at=start,
        window_ended_at=end,
    )

    with pytest.raises(ValueError, match="not exhaustive"):
        record_mismatch_review(
            db_session,
            source=source,
            reviewer_user_id="security-reviewer-id",
            reviewer_identity="security-reviewer@example.net",
            reviewed_at=end + timedelta(seconds=30),
            entries=[
                {
                    "action": "system.read",
                    "observation_ids": [included.id],
                    "reason_code": "reviewer_role_separation",
                    "reason": "Reviewer execution rights are intentionally removed in policy v2.",
                }
            ],
        )


def test_raw_mismatch_report_cannot_self_promote_by_editing_counters(
    db_session,
    tmp_path,
):
    workspace = _seed_workspace(db_session)
    end = datetime.now(UTC)
    start = end - timedelta(hours=1)
    db_session.add_all(
        [
            _event(
                workspace,
                action="system.read",
                mismatch=True,
                timestamp=start + timedelta(minutes=1),
            ),
            _event(workspace, action="run.read", timestamp=start + timedelta(minutes=2)),
        ]
    )
    db_session.commit()

    raw = _collect(db_session, workspace.id, start, end, tmp_path)
    edited = copy.deepcopy(raw)
    edited["result"] = "passed"
    edited["blockers"] = []
    summary = edited["shadow_observation"]["actions"]["system.read"]
    summary["explained_mismatches"] = summary["mismatches"]
    summary["unexplained_mismatches"] = 0

    from scripts import rollout_authorization_v2 as rollout

    with pytest.raises(rollout.AuthorizationPromotionError, match="summaries differ"):
        rollout.validate_evidence(
            edited,
            workspace_id=workspace.id,
            actions=["run.read", "system.read"],
            revision=REVISION,
            now=end + timedelta(minutes=2),
        )


def test_collector_fails_closed_on_malformed_counters(db_session, tmp_path):
    workspace = _seed_workspace(db_session)
    end = datetime.now(UTC)
    start = end - timedelta(hours=1)
    event = _event(workspace, timestamp=start + timedelta(minutes=1))
    details = copy.deepcopy(event.details)
    details["legacy_allowed"] = 2
    event.details = details
    db_session.add(event)
    db_session.commit()

    with pytest.raises(collector.ShadowCollectionError, match="do not balance"):
        collector.collect(
            db_session,
            workspace_id=workspace.id,
            actions=["system.read"],
            revision=REVISION,
            window_started_at=start,
            window_ended_at=end,
            validated_at=end,
            validated_by="protected-gate",
            environment="test",
            legacy_junit=_junit(tmp_path, "legacy"),
            candidate_junit=_junit(tmp_path, "candidate"),
            trusted_runner=PRODUCER,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("runtime_revision", "b" * 40, "revision differs"),
        ("candidate_config_sha256", "c" * 64, "candidate config differs"),
        ("candidate_config_version", 99, "config version differs"),
        ("configured_mode", "compat", "not evaluated in shadow"),
    ],
)
def test_collector_rejects_rows_from_another_runtime_or_policy(
    db_session,
    tmp_path,
    field,
    value,
    message,
):
    workspace = _seed_workspace(db_session)
    end = datetime.now(UTC)
    start = end - timedelta(hours=1)
    event = _event(workspace, timestamp=start + timedelta(minutes=1))
    details = copy.deepcopy(event.details)
    details[field] = value
    event.details = details
    db_session.add(event)
    db_session.commit()

    with pytest.raises(collector.ShadowCollectionError, match=message):
        collector.collect(
            db_session,
            workspace_id=workspace.id,
            actions=["system.read"],
            revision=REVISION,
            window_started_at=start,
            window_ended_at=end,
            validated_at=end,
            validated_by="protected-gate",
            environment="test",
            legacy_junit=_junit(tmp_path, "legacy"),
            candidate_junit=_junit(tmp_path, "candidate"),
            trusted_runner=PRODUCER,
        )


def test_collector_derives_contract_result_from_junit_bytes(db_session, tmp_path):
    workspace = _seed_workspace(db_session)
    end = datetime.now(UTC)
    start = end - timedelta(hours=1)
    db_session.add(_event(workspace, timestamp=start + timedelta(minutes=1)))
    db_session.commit()

    with pytest.raises(collector.ShadowCollectionError, match="not green"):
        collector.collect(
            db_session,
            workspace_id=workspace.id,
            actions=["system.read"],
            revision=REVISION,
            window_started_at=start,
            window_ended_at=end,
            validated_at=end,
            validated_by="protected-gate",
            environment="test",
            legacy_junit=_junit(tmp_path, "legacy", failed=True),
            candidate_junit=_junit(tmp_path, "candidate"),
            trusted_runner=PRODUCER,
        )

    with pytest.raises(collector.ShadowCollectionError, match="no executed test cases"):
        collector.collect(
            db_session,
            workspace_id=workspace.id,
            actions=["system.read"],
            revision=REVISION,
            window_started_at=start,
            window_ended_at=end,
            validated_at=end,
            validated_by="protected-gate",
            environment="test",
            legacy_junit=_junit(tmp_path, "legacy-skipped", skipped=True),
            candidate_junit=_junit(tmp_path, "candidate"),
            trusted_runner=PRODUCER,
        )
