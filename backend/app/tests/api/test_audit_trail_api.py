from datetime import datetime, timedelta

import pytest

from app.models.audit import AuditLog
from app.models.decision import Decision
from app.models.run import Run, SkillInvocation
from app.tests.api.test_audit_read_authorization import _client, _subject


def _seed_audit(db):
    workspace, user = _subject(db, suffix="trail", role_template="workspace_reviewer")
    foreign, _ = _subject(db, suffix="other", role_template="workspace_reviewer")
    stamp = datetime(2026, 9, 30, 8)
    for i in range(7):
        db.add(
            AuditLog(
                id=f"trail-{i}",
                workspace_id=workspace.id,
                timestamp=stamp + timedelta(minutes=i // 2),
                event_type="navigation.transition" if i == 6 else "run.completed",
                actor="alice" if i % 2 else "bob",
                severity="warning" if i == 3 else "info",
                trace_id="own-run" if i == 3 else None,
                details={"run_id": "own-run"} if i == 1 else {},
            )
        )
    db.add_all(
        [
            Run(id="own-run", workspace_id=workspace.id),
            Run(id="foreign-run", workspace_id=foreign.id),
            SkillInvocation(id="inv-own", run_id="own-run"),
            Decision(
                id="dec-own",
                workspace_id=workspace.id,
                scope="run",
                target_id="own-run",
                title="Approve",
            ),
        ]
    )
    db.commit()
    return workspace, user, _client(db, workspace, user)


def test_cursor_has_no_gaps_even_with_equal_timestamps_and_new_events(db_session):
    workspace, _, client = _seed_audit(db_session)
    params = {"exclude_navigation": "true", "event_type": "run.completed", "limit": 2}
    expected = client.get("/api/v1/audit", params={**params, "limit": 500}).json()["logs"]
    seen = []
    while True:
        page = client.get("/api/v1/audit", params=params).json()
        seen.extend(row["id"] for row in page["logs"])
        if not page["has_more"]:
            break
        params["before"] = page["next_cursor"]
        if len(seen) == 2:
            db_session.add(
                AuditLog(
                    id="new-navigation",
                    workspace_id=workspace.id,
                    timestamp=datetime.utcnow(),
                    event_type="navigation.resolved",
                )
            )
            db_session.commit()
    assert seen == [row["id"] for row in expected]
    assert len(set(seen)) == 6
    assert page["total"] == 6


def test_filters_workspace_and_default_compatibility(db_session):
    _, _, client = _seed_audit(db_session)
    default = client.get("/api/v1/audit").json()
    assert len(default["logs"]) == 8
    assert all(row["id"] != "log-audit-other" for row in default["logs"])
    hidden = client.get("/api/v1/audit", params={"exclude_navigation": True}).json()
    assert not any(row["event_type"].startswith("navigation.") for row in hidden["logs"])
    filtered = client.get(
        "/api/v1/audit",
        params={
            "exclude_navigation": True,
            "actor": "alice",
            "event_type_prefix": "run.",
            "since": "2026-09-30T08:01:00Z",
            "until": "2026-09-30T08:01:00+00:00",
            "severity": "warning",
            "search": "completed",
        },
    ).json()
    assert [row["id"] for row in filtered["logs"]] == ["trail-3"]
    assert filtered["total"] == 1
    traced = client.get("/api/v1/audit", params={"trace_id": "own-run"}).json()
    assert {row["id"] for row in traced["logs"]} == {"trail-1", "trail-3"}


@pytest.mark.parametrize(
    "params",
    [
        {"before": "oops"},
        {"before": "2026-01-01,"},
        {"since": "oops"},
        {"limit": 0},
        {"since": "2026-02-01", "until": "2026-01-01"},
    ],
)
def test_invalid_filters_are_rejected(db_session, params):
    _, _, client = _seed_audit(db_session)
    assert client.get("/api/v1/audit", params=params).status_code == 422


def test_trace_resolution_never_links_foreign_or_missing_runs(db_session):
    workspace, _, client = _seed_audit(db_session)
    for key, trace, details in [
        ("direct", "own-run", {}),
        ("invocation", "inv-own", {}),
        ("details", None, {"run_id": "own-run"}),
        ("decision", None, {"decision_id": "dec-own"}),
        ("foreign", "foreign-run", {}),
        ("missing", "unknown", {}),
    ]:
        db_session.add(
            AuditLog(
                id=key,
                workspace_id=workspace.id,
                event_type="test.resolution",
                trace_id=trace,
                details=details,
            )
        )
    db_session.commit()
    rows = {
        row["id"]: row["run_id"]
        for row in client.get("/api/v1/audit", params={"event_type": "test.resolution"}).json()[
            "logs"
        ]
    }
    assert rows == {
        "direct": "own-run",
        "invocation": "own-run",
        "details": "own-run",
        "decision": "own-run",
        "foreign": None,
        "missing": None,
    }
    inverse = client.get(
        "/api/v1/audit", params={"trace_id": "own-run", "event_type": "test.resolution"}
    ).json()
    assert {row["id"] for row in inverse["logs"]} == {"direct", "invocation", "details", "decision"}


def test_unauthorized_reader_cannot_use_filters_or_resolution(db_session):
    workspace, user = _subject(
        db_session, suffix="denied-trail", role_template="workspace_contributor"
    )
    response = _client(db_session, workspace, user).get(
        "/api/v1/audit", params={"trace_id": "run-secret"}
    )
    assert response.status_code == 403
    assert "run-secret" not in response.text


@pytest.mark.parametrize(
    "surface,path",
    [
        ("work", "/work/pr-to-po"),
        ("conversations", "/conversations/private-id"),
        ("mcp", "/connectors/mcp"),
    ],
)
def test_new_surfaces_are_recorded_and_derived_from_the_route(db_session, surface, path):
    workspace, user = _subject(db_session, suffix="surface", role_template="workspace_reviewer")
    response = _client(db_session, workspace, user).post(
        "/api/v1/audit",
        json={
            "event_type": "navigation.resolved",
            "details": {
                "requested_route": path,
                "resolved_route": path,
                "effective_workspace": "client",
                "effective_surface": surface,
                "redirect_owner": "angular_router",
                "redirect_reason": "direct",
                "redirected": False,
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["details"]["effective_surface"] == surface
    assert "private-id" not in response.text


def test_private_run_and_malformed_details_never_produce_a_link(db_session):
    workspace, _, client = _seed_audit(db_session)
    db_session.add(
        Run(
            id="private-run",
            workspace_id=workspace.id,
            trigger="builder_preview",
            initiated_by_user_id="somebody-else",
        )
    )
    db_session.add_all(
        [
            AuditLog(
                id="private-ref",
                workspace_id=workspace.id,
                event_type="test.private",
                trace_id="private-run",
            ),
            AuditLog(
                id="malformed-ref",
                workspace_id=workspace.id,
                event_type="test.private",
                details={"decision_id": ["untrusted"], "run_id": {"bad": "value"}},
            ),
        ]
    )
    db_session.commit()
    response = client.get("/api/v1/audit", params={"event_type": "test.private"})
    assert response.status_code == 200
    assert all(row["run_id"] is None for row in response.json()["logs"])


def test_rule_and_proposal_references_never_resolve_another_workspace(db_session):
    from app.api.v1.endpoints.audit import _audit_references
    from app.models.policy import ControlPolicy

    workspace, user, client = _seed_audit(db_session)
    db_session.add_all(
        [
            ControlPolicy(
                id="own-rule",
                workspace_id=workspace.id,
                name="Spend cap",
                scope="portfolio",
                max_cost_per_decision=2,
            ),
            ControlPolicy(
                id="foreign-rule",
                workspace_id="workspace-audit-other",
                name="Hidden cap",
                max_cost_per_decision=7,
            ),
            AuditLog(
                id="rule-own",
                workspace_id=workspace.id,
                event_type="rule.test",
                details={"policy_id": "own-rule", "decision_id": "dec-own"},
            ),
            AuditLog(
                id="rule-foreign",
                workspace_id=workspace.id,
                event_type="rule.test",
                details={"policy_id": "foreign-rule"},
            ),
        ]
    )
    db_session.commit()
    rows = {
        row.id: {"references": _audit_references(db_session, row, workspace, user)}
        for row in db_session.query(AuditLog).filter_by(event_type="rule.test").all()
    }
    assert rows["rule-own"]["references"]["rule"]["values"]["max_cost_per_decision"] == 2
    assert rows["rule-own"]["references"]["proposal"]["id"] == "dec-own"
    assert rows["rule-foreign"]["references"] == {}


def test_audit_uses_frozen_execution_policy_instead_of_edited_current_values(db_session):
    from app.api.v1.endpoints.audit import _audit_references
    from app.models.policy import ControlPolicy
    from app.models.system import System
    from app.services.control_policy_snapshot import freeze_control_policy

    workspace, user, _ = _seed_audit(db_session)
    system = System(id="frozen-audit-system", workspace_id=workspace.id, name="Frozen")
    policy = ControlPolicy(
        id="frozen-audit-policy",
        workspace_id=workspace.id,
        name="Guard",
        scope="system",
        target_id=system.id,
        max_cost_per_decision=2,
    )
    db_session.add_all([system, policy])
    db_session.flush()
    snapshot = freeze_control_policy(policy, workspace_id=workspace.id, system_id=system.id)
    run = db_session.get(Run, "own-run")
    run.system_id = system.id
    run.execution_contract = {"control_policy_snapshot": snapshot}
    policy.max_cost_per_decision = 9
    event = AuditLog(
        id="frozen-ref",
        workspace_id=workspace.id,
        event_type="run.completed",
        details={"policy_id": policy.id},
    )
    db_session.add(event)
    db_session.commit()
    result = _audit_references(db_session, event, workspace, user, run.id)["rule"]
    assert result["source"] == "frozen_execution" and result["values"]["max_cost_per_decision"] == 2
    assert result["revision"] == snapshot["sha256"]
