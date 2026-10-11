"""Action and target authorization for the canonical Control Plane."""
from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.v1.endpoints import control_plane
from app.models.policy import AdaptivePolicy, ControlPolicy
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember
from app.services.iam.decision_plane import ActionResolution


def _seed(db, attest_authorization_v2):
    suffix = uuid4().hex
    workspace = Workspace(
        id=f"workspace-control-plane-auth-{suffix}",
        slug=f"control-plane-auth-{suffix}",
        name="Control Plane auth",
    )
    foreign = Workspace(
        id=f"workspace-control-plane-foreign-{suffix}",
        slug=f"control-plane-foreign-{suffix}",
        name="Control Plane foreign",
    )
    contributor = User(
        id=f"control-plane-contributor-{suffix}",
        username=f"cp-contributor-{suffix}",
    )
    admin = User(id=f"control-plane-admin-{suffix}", username=f"cp-admin-{suffix}")
    visible = System(
        id=f"system-control-plane-visible-{suffix}",
        workspace_id=workspace.id,
        name="Visible System",
    )
    hidden = System(
        id=f"system-control-plane-hidden-{suffix}",
        workspace_id=workspace.id,
        name="Hidden System",
    )
    foreign_system = System(
        id=f"system-control-plane-foreign-{suffix}",
        workspace_id=foreign.id,
        name="Foreign System",
    )
    policies = [
        ControlPolicy(
            id=f"control-policy-visible-{suffix}",
            workspace_id=workspace.id,
            name="Visible policy",
            scope="system",
            target_id=visible.id,
            allowed_models=["visible-model"],
        ),
        ControlPolicy(
            id=f"control-policy-hidden-{suffix}",
            workspace_id=workspace.id,
            name="HIDDEN POLICY SECRET",
            scope="system",
            target_id=hidden.id,
            allowed_models=["hidden-model-secret"],
        ),
        AdaptivePolicy(
            id=f"adaptive-policy-visible-{suffix}",
            workspace_id=workspace.id,
            name="Visible adaptive",
            scope="system",
            target_id=visible.id,
            triggers={"visible": True},
        ),
        AdaptivePolicy(
            id=f"adaptive-policy-hidden-{suffix}",
            workspace_id=workspace.id,
            name="HIDDEN ADAPTIVE SECRET",
            scope="system",
            target_id=hidden.id,
            triggers={"secret": "never expose"},
        ),
    ]
    config = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        version=1,
        role_flags={},
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "modes": {
                    "control_policy.admin": "enforce",
                    "adaptive_policy.admin": "enforce",
                },
            }
        },
    )
    db.add_all(
        [
            workspace,
            foreign,
            contributor,
            admin,
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=contributor.id,
                role="member",
                role_template="workspace_contributor",
            ),
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=admin.id,
                role="admin",
                role_template="workspace_admin",
            ),
            visible,
            hidden,
            foreign_system,
            *policies,
            config,
        ]
    )
    db.flush()
    attest_authorization_v2(
        config,
        ["control_policy.admin", "adaptive_policy.admin"],
    )
    db.commit()
    return workspace, contributor, admin, visible, hidden, foreign_system


def _client(db, workspace, user) -> TestClient:
    app = FastAPI()
    app.include_router(control_plane.router, prefix="/control-plane")
    app.dependency_overrides[control_plane.get_current_workspace] = lambda: workspace
    app.dependency_overrides[control_plane.get_current_user] = lambda: user
    app.dependency_overrides[control_plane.get_db] = lambda: db
    return TestClient(app)


def test_policy_read_models_filter_every_parent_target(
    db_session,
    attest_authorization_v2,
    monkeypatch,
):
    workspace, contributor, _admin, visible, hidden, _foreign = _seed(
        db_session,
        attest_authorization_v2,
    )

    def _system_read(_db, *, system, **_kwargs):
        allowed = system.id == visible.id
        return ActionResolution(
            resource_kind="system",
            action="read",
            mode="enforce",
            effective_allowed=allowed,
            legacy_allowed=True,
            candidate_allowed=allowed,
            mismatch=not allowed,
            reason="candidate_allowed" if allowed else "role_denied",
            policy_id="test:system.read",
        )

    monkeypatch.setattr(control_plane, "resolve_system_read", _system_read)
    client = _client(db_session, workspace, contributor)

    controls = client.get("/control-plane/policies")
    adaptive = client.get("/control-plane/adaptive")

    assert controls.status_code == adaptive.status_code == 200
    assert [row["target_id"] for row in controls.json()["policies"]] == [visible.id]
    assert [row["target_id"] for row in adaptive.json()["policies"]] == [visible.id]
    assert hidden.id not in controls.text
    assert "HIDDEN" not in controls.text + adaptive.text
    assert "never expose" not in adaptive.text


def test_policy_read_is_resolved_per_row_with_target_attributes(
    db_session,
    attest_authorization_v2,
    monkeypatch,
):
    workspace, contributor, _admin, visible, hidden, _foreign = _seed(
        db_session,
        attest_authorization_v2,
    )
    observed: list[tuple[str, dict[str, str | None]]] = []

    def _policy_read(_db, *, resource_kind, action, resource_attrs, **_kwargs):
        observed.append((resource_kind, dict(resource_attrs)))
        allowed = resource_attrs["target_id"] == visible.id
        return ActionResolution(
            resource_kind=resource_kind,
            action=action,
            mode="enforce",
            effective_allowed=allowed,
            legacy_allowed=True,
            candidate_allowed=allowed,
            mismatch=not allowed,
            reason="candidate_allowed" if allowed else "role_denied",
            policy_id=f"test:{resource_kind}.{action}",
        )

    def _system_read(_db, *, system, **_kwargs):
        return ActionResolution(
            resource_kind="system",
            action="read",
            mode="enforce",
            effective_allowed=True,
            legacy_allowed=True,
            candidate_allowed=True,
            mismatch=False,
            reason="candidate_allowed",
            policy_id="test:system.read",
        )

    monkeypatch.setattr(control_plane, "resolve_action", _policy_read)
    monkeypatch.setattr(control_plane, "resolve_system_read", _system_read)
    client = _client(db_session, workspace, contributor)

    controls = client.get("/control-plane/policies")
    adaptive = client.get("/control-plane/adaptive")

    assert controls.status_code == adaptive.status_code == 200
    assert [row["target_id"] for row in controls.json()["policies"]] == [visible.id]
    assert [row["target_id"] for row in adaptive.json()["policies"]] == [visible.id]
    assert hidden.id not in controls.text + adaptive.text
    assert len(observed) == 4
    assert {attrs["policy_id"] for _, attrs in observed} == {
        row.id
        for row in db_session.query(ControlPolicy).filter_by(workspace_id=workspace.id)
    } | {
        row.id
        for row in db_session.query(AdaptivePolicy).filter_by(workspace_id=workspace.id)
    }
    assert all(attrs["scope"] == "system" for _, attrs in observed)
    assert all(attrs["system_id"] == attrs["target_id"] for _, attrs in observed)


def test_policy_mutations_require_exact_admin_and_tenant_valid_target(
    db_session,
    attest_authorization_v2,
):
    workspace, contributor, admin, visible, _hidden, foreign = _seed(
        db_session,
        attest_authorization_v2,
    )
    contributor_client = _client(db_session, workspace, contributor)
    admin_client = _client(db_session, workspace, admin)
    body = {
        "name": "New governed policy",
        "scope": "system",
        "target_id": visible.id,
    }

    assert contributor_client.post("/control-plane/policies", json=body).status_code == 403
    assert contributor_client.post("/control-plane/adaptive", json=body).status_code == 403
    assert admin_client.post("/control-plane/policies", json=body).status_code == 200
    assert admin_client.post("/control-plane/adaptive", json=body).status_code == 200

    cross_tenant = {**body, "target_id": foreign.id}
    assert admin_client.post("/control-plane/policies", json=cross_tenant).status_code == 404
    assert admin_client.post("/control-plane/adaptive", json=cross_tenant).status_code == 404


def test_policy_retarget_rechecks_admin_on_the_final_target(
    db_session,
    attest_authorization_v2,
    monkeypatch,
):
    workspace, _contributor, admin, visible, hidden, _foreign = _seed(
        db_session,
        attest_authorization_v2,
    )
    control = (
        db_session.query(ControlPolicy)
        .filter_by(workspace_id=workspace.id, target_id=visible.id)
        .one()
    )
    adaptive = (
        db_session.query(AdaptivePolicy)
        .filter_by(workspace_id=workspace.id, target_id=visible.id)
        .one()
    )
    observed: list[tuple[str, str | None]] = []

    def _target_admin(*_args, **kwargs):
        attrs = kwargs["resource_attrs"]
        observed.append((kwargs["resource_kind"], attrs["target_id"]))
        if attrs["target_id"] == hidden.id:
            raise HTTPException(status_code=403, detail="target admin denied")

    monkeypatch.setattr(control_plane, "enforce_action", _target_admin)
    client = _client(db_session, workspace, admin)
    patch = {"scope": "system", "target_id": hidden.id}

    control_response = client.patch(
        f"/control-plane/policies/{control.id}", json=patch
    )
    adaptive_response = client.patch(
        f"/control-plane/adaptive/{adaptive.id}", json=patch
    )

    assert control_response.status_code == adaptive_response.status_code == 403
    db_session.expire_all()
    assert db_session.get(ControlPolicy, control.id).target_id == visible.id
    assert db_session.get(AdaptivePolicy, adaptive.id).target_id == visible.id
    assert observed == [
        ("control_policy", visible.id),
        ("control_policy", hidden.id),
        ("adaptive_policy", visible.id),
        ("adaptive_policy", hidden.id),
    ]


def test_policy_contract_rejects_ambiguous_or_unknown_scopes():
    for body_type in (control_plane.ControlPolicyBody, control_plane.AdaptivePolicyBody):
        for payload in (
            {"scope": "system"},
            {"scope": "capability"},
            {"scope": "portfolio", "target_id": "unexpected"},
            {"scope": "unknown"},
        ):
            try:
                body_type(**payload)
            except ValidationError:
                continue
            raise AssertionError(f"payload unexpectedly accepted: {payload}")
