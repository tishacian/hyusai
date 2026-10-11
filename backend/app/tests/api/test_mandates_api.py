from datetime import datetime, timedelta
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.v1.endpoints import mandates
from app.models.decision import Decision
from app.models.policy import ControlPolicy
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember


def seed(db):
    workspace = Workspace(id="mandate-ws", slug="mandate", name="Mandate")
    user = User(id="mandate-reader", username="mandate-reader", role="user")
    other = User(id="mandate-other", username="mandate-other", role="user")
    system = System(id="mandate-system", workspace_id=workspace.id, name="Example", status="active")
    db.add_all([workspace, user, other, system])
    db.flush()
    db.add(WorkspaceMember(user_id=user.id, workspace_id=workspace.id, role="member", role_template="workspace_contributor"))
    own = Run(id="mandate-run", system_id=system.id, workspace_id=workspace.id,
              initiated_by_user_id=user.id, trigger="chat_agentic", status="failed", error="membrane_valve_breach:cost",
              checkpoints=[{"kind": "membrane_valve_breach", "breaches": ["cost"]}])
    hidden = Run(id="mandate-private", system_id=system.id, workspace_id=workspace.id,
                 initiated_by_user_id=other.id, trigger="chat_agentic", status="completed",
                 checkpoints=[{"kind": "membrane_provenance", "sha256": "private-receipt"}])
    db.add_all([own, hidden])
    db.commit()
    return workspace, user, system, own, hidden


def client(db, workspace, user):
    app = FastAPI()
    app.include_router(mandates.router)
    app.dependency_overrides[mandates.get_current_workspace] = lambda: workspace
    app.dependency_overrides[mandates.get_current_user] = lambda: user
    app.dependency_overrides[mandates.get_db] = lambda: db
    return TestClient(app)


def test_private_runs_cannot_leak_via_evidence_or_coverage(db_session):
    workspace, user, system, own, hidden = seed(db_session)
    api = client(db_session, workspace, user)
    assert api.get(f"/runs/{hidden.id}/mandate").status_code == 404
    response = api.get(f"/systems/{system.id}/mandate")
    assert response.status_code == 200, response.text
    result = response.json()
    assert [item["run_id"] for item in result["recent_runs"]] == [own.id]
    assert result["recent_runs"][0]["facets"]["valves"]["breach_count"] == 1
    assert "private-receipt" not in response.text


def test_run_read_is_enforced_independently_of_system_read(db_session, monkeypatch):
    workspace, user, _, own, _ = seed(db_session)
    def deny(*args, **kwargs):
        assert kwargs["resource_kind"] == "run" and kwargs["action"] == "read"
        raise HTTPException(403, "Denied")
    monkeypatch.setattr(mandates, "enforce_action", deny)
    assert client(db_session, workspace, user).get(f"/runs/{own.id}/mandate").status_code == 403


def test_workspace_scope_applies_to_system_and_run(db_session):
    workspace, user, system, own, _ = seed(db_session)
    other = Workspace(id="other-ws", slug="other-mandate", name="Other")
    db_session.add(other)
    db_session.commit()
    api = client(db_session, other, user)
    assert api.get(f"/systems/{system.id}/mandate").status_code == 404
    assert api.get(f"/runs/{own.id}/mandate").status_code == 404


def test_denied_decision_and_invocation_dont_leak_into_run_counts(db_session, monkeypatch):
    workspace, user, system, own, _ = seed(db_session)
    own.checkpoints = []
    db_session.add_all([
        Decision(id="private-decision", workspace_id=workspace.id, target_id=own.id,
                 scope="run", kind="hitl_approval", title="Private", status="accepted",
                 human_confirmed_by=user.id, human_confirmed_at=datetime.utcnow()),
        SkillInvocation(id="private-inv", run_id=own.id, skill_slug="audit_log_v1",
                        trace={"membrane_provenance": {"sha256": "private-artifact"}}),
    ])
    db_session.commit()
    monkeypatch.setattr(mandates, "readable_decisions", lambda *a, **kw: [])
    monkeypatch.setattr(mandates, "readable_skill_invocations", lambda *a, **kw: [])
    result = client(db_session, workspace, user).get(f"/runs/{own.id}/mandate").json()
    assert result["events"] == []
    assert result["counts"]["recorded_events"] == 0


def test_policy_from_another_workspace_is_not_projected(db_session):
    workspace, user, system, _, _ = seed(db_session)
    policy = ControlPolicy(id="other-policy", workspace_id="other", target_id=system.id,
                           scope="system", allowed_models=["private-model"])
    db_session.add(policy)
    db_session.flush()
    system.control_policy_id = policy.id
    db_session.commit()
    response = client(db_session, workspace, user).get(f"/systems/{system.id}/mandate")
    assert response.status_code == 200
    assert response.json()["configuration"]["state"] == "not_configured"
    assert "private-model" not in response.text


def test_held_payloads_are_not_returned_in_read_projection(db_session):
    workspace, user, system, own, _ = seed(db_session)
    own.status = "hitl_pending"
    own.checkpoints = [{"kind": "hitl_pause", "membrane_egress": True, "decision_id": "gate",
                        "state": {"node_outputs": {"answer": "PRIVATE HELD RESULT"}}, "prompt": "PRIVATE PROMPT"}]
    db_session.add(Decision(id="gate", workspace_id=workspace.id, scope="run", target_id=own.id,
                            kind="hitl_approval", title="Review", status="proposed"))
    db_session.commit()
    response = client(db_session, workspace, user).get(f"/runs/{own.id}/mandate")
    assert response.status_code == 200, response.text
    assert response.json()["counts"]["awaiting_human"] == 1
    assert "PRIVATE" not in response.text


def delegated_gate(db, parent, workspace, *, trigger="subflow"):
    child = Run(id="delegated-child", workspace_id=workspace.id, system_id=parent.system_id,
                parent_run_id=parent.id, status="hitl_pending", trigger=trigger,
                initiated_by_user_id="mandate-other", delegation_key="d" * 64,
                delegation_node_id="delegate-analysis", delegation_branch="default")
    gate = Decision(id="delegated-gate", workspace_id=workspace.id, scope="run", target_id=child.id,
                    kind="hitl_approval", title="Review delegated result", status="proposed",
                    expires_at=datetime.utcnow() + timedelta(minutes=5))
    parent.status = "hitl_pending"
    parent.checkpoints = [{"kind": "hitl_pause", "decision_id": gate.id, "node_id": "delegate-analysis"}]
    child.checkpoints = [{"kind": "hitl_pause", "decision_id": gate.id, "node_id": "child-review"}]
    db.add_all([child, gate])
    db.commit()
    return child, gate


def test_authorized_delegation_has_child_proof_and_exact_forwarded_gate(db_session):
    workspace, user, _, parent, _ = seed(db_session)
    child, gate = delegated_gate(db_session, parent, workspace)
    api = client(db_session, workspace, user)
    response = api.get(f"/runs/{parent.id}/mandate")
    assert response.status_code == 200, response.text
    body = response.json()
    by_id = {item["id"]: item for item in body["events"]}
    assert by_id[f"delegation:{child.id}"]["child_run_id"] == child.id
    assert by_id[f"delegation:{child.id}"]["status"] == "recorded"
    assert by_id[f"decision:{gate.id}"]["status"] == "awaiting_human"
    assert by_id[f"decision:{gate.id}"]["child_run_id"] == child.id
    assert body["counts"]["awaiting_human"] == 1
    gate.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db_session.commit()
    assert api.get(f"/runs/{parent.id}/mandate").json()["counts"]["awaiting_human"] == 0


def test_parent_permission_does_not_inherit_private_child_or_decision_access(db_session):
    workspace, user, _, parent, _ = seed(db_session)
    child, gate = delegated_gate(db_session, parent, workspace, trigger="chat_agentic")
    response = client(db_session, workspace, user).get(f"/runs/{parent.id}/mandate")
    assert response.status_code == 200, response.text
    assert response.json()["counts"]["awaiting_human"] == 0
    assert child.id not in response.text
    assert gate.id not in response.text


def test_checkpoint_cannot_forward_an_unrelated_runs_decision(db_session):
    workspace, user, _, parent, _ = seed(db_session)
    child, gate = delegated_gate(db_session, parent, workspace)
    child.parent_run_id = None
    db_session.commit()
    response = client(db_session, workspace, user).get(f"/runs/{parent.id}/mandate")
    assert response.status_code == 200
    assert gate.id not in response.text
    assert child.id not in response.text


def test_optional_names_use_visible_catalog_and_independent_system_permissions(db_session, monkeypatch):
    workspace, user, system, _, _ = seed(db_session)
    other_workspace = Workspace(id="labels-other", slug="labels-other", name="Other")
    skill = Skill(id="label-skill", workspace_id=workspace.id, slug="local_read_v1", name="Read technical manuals")
    private_skill = Skill(id="private-label-skill", workspace_id=other_workspace.id,
                          slug="private_read_v1", name="SECRET SKILL NAME")
    child = System(id="label-child", workspace_id=workspace.id, name="Maintenance analysis")
    private_system = System(id="label-private-system", workspace_id=other_workspace.id, name="SECRET SYSTEM NAME")
    policy = ControlPolicy(id="label-policy", workspace_id=workspace.id, scope="system", target_id=system.id,
                           extra={"membrane_spec": {"version": 2, "enforcement_mode": "shadow",
                                  "capabilities": {"allowed_skills": [skill.slug, private_skill.slug],
                                                   "allowed_delegations": [{"system_id": child.id},
                                                                           {"system_id": private_system.id}]}}})
    db_session.add_all([other_workspace, skill, private_skill, child, private_system, policy])
    db_session.flush()
    system.control_policy_id = policy.id
    db_session.commit()
    api = client(db_session, workspace, user)
    response = api.get(f"/systems/{system.id}/mandate")
    assert response.status_code == 200, response.text
    assert response.json()["reference_labels"] == {
        "skills": {skill.slug: skill.name}, "delegations": {child.id: child.name},
    }
    assert "SECRET" not in response.text
    monkeypatch.setattr(mandates, "resolve_action", lambda *args, **kwargs: SimpleNamespace(effective_allowed=False))
    monkeypatch.setattr(mandates, "readable_systems", lambda *args, **kwargs: [])
    denied = api.get(f"/systems/{system.id}/mandate")
    assert denied.status_code == 200
    assert denied.json()["reference_labels"] == {"skills": {}, "delegations": {}}
