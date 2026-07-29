"""Read-authorization contracts for Hypervisor Decisions and Balance Sheet."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import hypervisor
from app.models.audit import AuditLog
from app.models.capability import Capability
from app.models.decision import Decision
from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember


def _seed(db_session):
    workspace = Workspace(
        id="ws-hypervisor-read-authz",
        slug="hypervisor-read-authz",
        name="Hypervisor read authorization",
        settings={},
    )
    foreign_workspace = Workspace(
        id="ws-hypervisor-read-authz-foreign",
        slug="hypervisor-read-authz-foreign",
        name="Foreign Hypervisor",
        settings={},
    )
    contributor = User(
        id="user-hypervisor-contributor",
        username="hypervisor-contributor",
        email="hypervisor-contributor@example.test",
    )
    other = User(
        id="user-hypervisor-other",
        username="hypervisor-other",
        email="hypervisor-other@example.test",
    )
    reviewer = User(
        id="user-hypervisor-reviewer",
        username="hypervisor-reviewer",
        email="hypervisor-reviewer@example.test",
    )
    admin = User(
        id="user-hypervisor-admin",
        username="hypervisor-admin",
        email="hypervisor-admin@example.test",
    )
    members = [
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=contributor.id,
            role="member",
            role_template="workspace_contributor",
        ),
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=reviewer.id,
            role="reviewer",
            role_template="workspace_reviewer",
        ),
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=admin.id,
            role="admin",
            role_template="workspace_admin",
        ),
    ]
    capability = Capability(
        id="cap-hypervisor-read-authz",
        workspace_id=workspace.id,
        slug="hypervisor_read_authz",
        name="Hypervisor Read",
        tier="system",
    )
    system = System(
        id="system-hypervisor-read-authz",
        workspace_id=workspace.id,
        capability_id=capability.id,
        name="Hypervisor read System",
        status="active",
    )
    own_run = Run(
        id="run-hypervisor-own-private",
        workspace_id=workspace.id,
        initiated_by_user_id=contributor.id,
        system_id=system.id,
        capability_id=capability.id,
        trigger="chat_agentic",
        status="completed",
        started_at=datetime.utcnow() - timedelta(minutes=3),
        completed_at=datetime.utcnow() - timedelta(minutes=2),
        cost_internal=1.0,
        value_estimated=4.0,
        value_source="auto",
    )
    other_run = Run(
        id="run-hypervisor-other-manual",
        workspace_id=workspace.id,
        initiated_by_user_id=other.id,
        system_id=system.id,
        capability_id=capability.id,
        trigger="manual",
        status="completed",
        started_at=datetime.utcnow() - timedelta(minutes=2),
        completed_at=datetime.utcnow() - timedelta(minutes=1),
        cost_internal=100.0,
        value_estimated=500.0,
        value_source="auto",
    )
    private_run = Run(
        id="run-hypervisor-other-private",
        workspace_id=workspace.id,
        initiated_by_user_id=other.id,
        system_id=system.id,
        capability_id=capability.id,
        trigger="chat_agentic",
        status="completed",
        started_at=datetime.utcnow() - timedelta(minutes=1),
        completed_at=datetime.utcnow(),
        cost_internal=1_000.0,
        value_estimated=5_000.0,
        value_source="auto",
        error="PRIVATE RUN ERROR",
    )
    own_decision = Decision(
        id="decision-hypervisor-own",
        workspace_id=workspace.id,
        scope="run",
        target_id=own_run.id,
        title="Own Decision",
        status="proposed",
    )
    other_decision = Decision(
        id="decision-hypervisor-other",
        workspace_id=workspace.id,
        scope="run",
        target_id=other_run.id,
        title="Other Decision",
        status="proposed",
    )
    ownerless = Decision(
        id="decision-hypervisor-ownerless",
        workspace_id=workspace.id,
        scope="system",
        target_id=system.id,
        title="Ownerless Decision",
        status="proposed",
    )
    foreign = Decision(
        id="decision-hypervisor-foreign",
        workspace_id=foreign_workspace.id,
        scope="system",
        target_id=system.id,
        title="FOREIGN DECISION SECRET",
        status="proposed",
    )
    db_session.add_all(
        [
            workspace,
            foreign_workspace,
            contributor,
            other,
            reviewer,
            admin,
            *members,
            capability,
            system,
            own_run,
            other_run,
            private_run,
            own_decision,
            other_decision,
            ownerless,
            foreign,
        ]
    )
    db_session.commit()
    return {
        "workspace": workspace,
        "contributor": contributor,
        "reviewer": reviewer,
        "admin": admin,
        "own_run": own_run,
        "other_run": other_run,
        "private_run": private_run,
        "own_decision": own_decision,
        "other_decision": other_decision,
        "ownerless": ownerless,
    }


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(hypervisor.router, prefix="/hypervisor")
    app.dependency_overrides[hypervisor.get_current_workspace] = lambda: workspace
    app.dependency_overrides[hypervisor.get_current_user] = lambda: user
    app.dependency_overrides[hypervisor.get_db] = lambda: db_session
    return TestClient(app)


def _config(
    db_session,
    *,
    workspace: Workspace,
    user: User,
    modes: dict[str, str],
) -> WorkspaceIAMConfig:
    row = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        version=1,
        role_flags={},
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "modes": modes,
            }
        },
        updated_by_user_id=user.id,
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_decision_list_detail_pagination_and_roles_are_authorization_scoped(
    db_session,
    attest_authorization_v2,
):
    seeded = _seed(db_session)
    workspace = seeded["workspace"]
    config = _config(
        db_session,
        workspace=workspace,
        user=seeded["admin"],
        modes={"decision.read": "enforce"},
    )
    attest_authorization_v2(config, ["decision.read"])
    db_session.commit()

    contributor = _client(db_session, workspace, seeded["contributor"])
    page = contributor.get("/hypervisor/decisions", params={"limit": 1, "offset": 0})
    assert page.status_code == 200
    assert page.json()["total"] == 1
    assert [item["id"] for item in page.json()["items"]] == [
        seeded["own_decision"].id
    ]
    recommendations = contributor.get("/hypervisor/recommendations")
    assert recommendations.status_code == 200
    assert [item["id"] for item in recommendations.json()["items"]] == [
        seeded["own_decision"].id
    ]
    denied = contributor.get(
        f"/hypervisor/decisions/{seeded['ownerless'].id}"
    )
    missing = contributor.get("/hypervisor/decisions/missing-decision")
    assert denied.status_code == missing.status_code == 404
    assert denied.json() == missing.json() == {"detail": "Decision not found"}

    expected = {
        seeded["own_decision"].id,
        seeded["other_decision"].id,
        seeded["ownerless"].id,
    }
    for actor in (seeded["reviewer"], seeded["admin"]):
        response = _client(db_session, workspace, actor).get(
            "/hypervisor/decisions",
            params={"limit": 1, "offset": 1},
        )
        assert response.status_code == 200
        assert response.json()["total"] == 3
        assert len(response.json()["items"]) == 1
        all_rows = _client(db_session, workspace, actor).get(
            "/hypervisor/decisions",
            params={"limit": 10},
        )
        assert {item["id"] for item in all_rows.json()["items"]} == expected
        assert "FOREIGN DECISION SECRET" not in all_rows.text


def test_decision_shadow_preserves_legacy_and_invalid_enforce_fails_closed(
    db_session,
):
    seeded = _seed(db_session)
    workspace = seeded["workspace"]
    config = _config(
        db_session,
        workspace=workspace,
        user=seeded["admin"],
        modes={"decision.read": "shadow"},
    )
    client = _client(db_session, workspace, seeded["contributor"])

    shadow = client.get("/hypervisor/decisions", params={"limit": 10})

    assert shadow.status_code == 200
    assert shadow.json()["total"] == 3
    evidence = [
        row
        for row in db_session.query(AuditLog)
        .filter_by(
            workspace_id=workspace.id,
            event_type="iam.shadow.evaluation",
        )
        .all()
        if row.details.get("action") == "decision.read"
    ]
    assert len(evidence) == 1
    assert evidence[0].details["summary"] is True
    assert evidence[0].details["mismatches"] == 2

    payload = dict(config.capability_overrides)
    policy = dict(payload["authorization_v2"])
    policy["modes"] = {"decision.read": "enforce"}
    payload["authorization_v2"] = policy
    config.capability_overrides = payload
    config.version += 1
    db_session.commit()

    invalid = client.get("/hypervisor/decisions", params={"limit": 10})
    detail = client.get(f"/hypervisor/decisions/{seeded['own_decision'].id}")
    assert invalid.status_code == 200
    assert invalid.json()["total"] == 0
    assert invalid.json()["items"] == []
    assert detail.status_code == 404
    assert seeded["own_decision"].title not in invalid.text


def test_balance_sheet_aggregates_and_signals_only_readable_runs(
    db_session,
    attest_authorization_v2,
):
    seeded = _seed(db_session)
    workspace = seeded["workspace"]
    config = _config(
        db_session,
        workspace=workspace,
        user=seeded["admin"],
        modes={"run.read": "enforce"},
    )
    attest_authorization_v2(config, ["run.read"])
    db_session.commit()

    contributor = _client(db_session, workspace, seeded["contributor"]).get(
        "/hypervisor/balance-sheet",
        params={"period": "rolling_30d"},
    )
    assert contributor.status_code == 200
    assert contributor.json()["portfolio"]["runs_count"] == 1
    assert contributor.json()["portfolio"]["total_cost"] == 1.0
    assert {row["id"] for row in contributor.json()["signals"]} == {
        seeded["own_run"].id
    }
    assert contributor.json()["authorization_scope"] == {
        "resource": "run",
        "action": "read",
        "aggregation": "post_authorization_filter",
        "counts_include_only_readable_runs": True,
    }
    assert seeded["private_run"].id not in contributor.text
    assert "PRIVATE RUN ERROR" not in contributor.text

    reviewer = _client(db_session, workspace, seeded["reviewer"]).get(
        "/hypervisor/balance-sheet",
        params={"period": "rolling_30d"},
    )
    assert reviewer.status_code == 200
    assert reviewer.json()["portfolio"]["runs_count"] == 3
    assert reviewer.json()["portfolio"]["total_cost"] == 1_101.0
    assert {row["id"] for row in reviewer.json()["signals"]} == {
        seeded["own_run"].id,
        seeded["other_run"].id,
        seeded["private_run"].id,
    }


def test_recommendation_generation_compat_uses_server_actor(
    db_session,
    monkeypatch,
):
    seeded = _seed(db_session)
    captured = {}

    def _generate(_db, **kwargs):
        captured.update(kwargs)
        return {"created": [], "skipped": [], "preview": []}

    monkeypatch.setattr(hypervisor, "generate_proactive_recommendations", _generate)
    response = _client(
        db_session,
        seeded["workspace"],
        seeded["contributor"],
    ).post(
        "/hypervisor/recommendations/generate",
        json={"dry_run": True, "actor": "attacker@example.test"},
    )

    assert response.status_code == 200
    assert captured["actor"] == seeded["contributor"].email
    assert captured["actor"] != "attacker@example.test"
    assert captured["dry_run"] is True


def test_recommendation_generation_exact_enforce_denies_non_admin(
    db_session,
    attest_authorization_v2,
    monkeypatch,
):
    seeded = _seed(db_session)
    config = _config(
        db_session,
        workspace=seeded["workspace"],
        user=seeded["admin"],
        modes={"decision.admin": "enforce"},
    )
    attest_authorization_v2(config, ["decision.admin"])
    db_session.commit()
    called = False

    def _generate(_db, **_kwargs):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(hypervisor, "generate_proactive_recommendations", _generate)
    response = _client(
        db_session,
        seeded["workspace"],
        seeded["contributor"],
    ).post("/hypervisor/recommendations/generate", json={"dry_run": True})

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "WORKSPACE_PERMISSION_DENIED"
    assert called is False
