from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm.attributes import flag_modified

from app.api.v1.endpoints import audit
from app.models.audit import AuditLog
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember


def _subject(db, *, suffix: str, role_template: str):
    workspace = Workspace(
        id=f"workspace-audit-{suffix}",
        slug=f"audit-{suffix}",
        name=f"Audit {suffix}",
    )
    user = User(id=f"user-audit-{suffix}", username=f"audit-{suffix}")
    membership = WorkspaceMember(
        user_id=user.id,
        workspace_id=workspace.id,
        role="member",
        role_template=role_template,
    )
    log = AuditLog(
        id=f"log-audit-{suffix}",
        workspace_id=workspace.id,
        timestamp=datetime.utcnow(),
        event_type="system.updated",
        actor="server-actor",
        details={"system_id": "system-secret"},
        trace_id="run-secret",
        severity="info",
    )
    db.add_all([workspace, user, membership, log])
    db.commit()
    return workspace, user


def _client(db, workspace, user) -> TestClient:
    app = FastAPI()
    app.include_router(audit.router, prefix="/api/v1/audit")
    app.dependency_overrides[audit.get_current_workspace] = lambda: workspace
    app.dependency_overrides[audit.get_current_user] = lambda: user
    app.dependency_overrides[audit.get_db] = lambda: db
    return TestClient(app)


def test_contributor_cannot_read_audit_list_or_summary_in_compat(db_session):
    workspace, user = _subject(
        db_session,
        suffix="contributor",
        role_template="workspace_contributor",
    )
    client = _client(db_session, workspace, user)

    for path in ("/api/v1/audit", "/api/v1/audit/summary"):
        response = client.get(path)
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "WORKSPACE_PERMISSION_DENIED"
        assert "system-secret" not in response.text
        assert "run-secret" not in response.text


def test_reviewer_reads_only_the_active_workspace_audit(db_session):
    workspace, user = _subject(
        db_session,
        suffix="reviewer",
        role_template="workspace_reviewer",
    )
    foreign, _foreign_user = _subject(
        db_session,
        suffix="foreign",
        role_template="workspace_reviewer",
    )
    client = _client(db_session, workspace, user)

    listed = client.get("/api/v1/audit")
    summary = client.get("/api/v1/audit/summary")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["logs"]] == ["log-audit-reviewer"]
    assert summary.status_code == 200
    assert summary.json()["total_events"] == 1
    assert foreign.id != workspace.id


def test_audit_list_filters_by_event_type_prefix(db_session):
    workspace, user = _subject(
        db_session,
        suffix="prefix",
        role_template="workspace_reviewer",
    )
    extra = AuditLog(
        id="log-audit-prefix-experience",
        workspace_id=workspace.id,
        timestamp=datetime.utcnow(),
        event_type="experience.released",
        actor="server-actor",
        details={"experience_id": "exp-1"},
        severity="info",
    )
    db_session.add(extra)
    db_session.commit()
    client = _client(db_session, workspace, user)

    prefixed = client.get("/api/v1/audit", params={"event_type_prefix": "experience."})
    exact = client.get("/api/v1/audit", params={"event_type": "system.updated"})

    assert prefixed.status_code == 200
    assert [item["id"] for item in prefixed.json()["logs"]] == ["log-audit-prefix-experience"]
    assert [item["id"] for item in exact.json()["logs"]] == ["log-audit-prefix"]


def test_exact_enforcement_and_invalid_attestation_are_fail_closed(
    db_session,
    attest_authorization_v2,
):
    workspace, user = _subject(
        db_session,
        suffix="enforced",
        role_template="workspace_reviewer",
    )
    config = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        version=1,
        role_flags={},
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "modes": {"audit_log.read": "enforce"},
            }
        },
    )
    db_session.add(config)
    db_session.flush()
    attest_authorization_v2(config, ["audit_log.read"])
    db_session.commit()
    client = _client(db_session, workspace, user)

    assert client.get("/api/v1/audit").status_code == 200

    config.capability_overrides["authorization_v2"]["enforcement_attestations"][
        "audit_log.read"
    ]["trusted_runner"]["commit_sha"] = "b" * 40
    flag_modified(config, "capability_overrides")
    db_session.commit()
    db_session.expire_all()

    invalid = client.get("/api/v1/audit/summary")
    assert invalid.status_code == 503
    assert invalid.json()["detail"]["code"] == "AUTHORIZATION_ENFORCEMENT_INVALID"
