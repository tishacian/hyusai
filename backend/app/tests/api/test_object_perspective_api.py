from __future__ import annotations

import json
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import capabilities, runs, systems
from app.core.config import settings
from app.models.audit import AuditLog
from app.models.capability import Capability
from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember
from app.services.projection_gate import (
    PROJECTION_FINALIZATION_AUDIT_EVENT,
    projection_activation_audit_details,
    projection_activation_sha256,
    with_projection_activation,
)
from app.services.run_outcome_provenance import RUN_OUTCOME_OVERRIDE_AUDIT_EVENT

TEST_TRUSTED_RUNNER = {
    "issuer": "https://gitlab.example.test",
    "project_id": "42",
    "pipeline_id": "314",
    "job_id": "159",
    "commit_sha": "a" * 40,
    "ref": "demo/agentic",
    "ref_protected": True,
}


@pytest.fixture(autouse=True)
def _deployed_projection_revision(monkeypatch):
    monkeypatch.setattr(settings, "agentium_image_revision", "a" * 40)
    monkeypatch.setattr(
        settings,
        "authorization_v2_trusted_oidc_issuer",
        TEST_TRUSTED_RUNNER["issuer"],
    )
    monkeypatch.setattr(
        settings,
        "authorization_v2_trusted_project_id",
        TEST_TRUSTED_RUNNER["project_id"],
    )
    monkeypatch.setattr(
        settings,
        "authorization_v2_trusted_ref",
        TEST_TRUSTED_RUNNER["ref"],
    )


def _projection_settings(*projections: str) -> dict:
    settings: dict = {"features": {}}
    for projection in projections:
        settings = with_projection_activation(
            settings,
            projection=projection,
            evidence_sha256="a" * 64,
            revision="a" * 40,
            system_id="system-object-api",
            capability_id="cap-object-api",
        )
    return settings


def _canary_settings(db_session, workspace_settings: dict, *, workspace_id: str) -> dict:
    rows = workspace_settings["_lot7_projection_gate_v1"]["activations"]
    activations = []
    for row in rows:
        activation = {
            **dict(row),
            "trusted_runner": dict(TEST_TRUSTED_RUNNER),
            "pilot_observation": {
                "audit_id": str(uuid4()),
                "observation_ref": f"sha256:{'b' * 64}",
                "participant_ref": f"sha256:{'c' * 64}",
                "profile": "operator",
            },
            "activated_by": "lot7-api-test-runner",
            "activated_at": "2026-01-01T00:00:00+00:00",
            "probation_lease_id": str(uuid4()),
        }
        activation["activation_sha256"] = projection_activation_sha256(activation)
        audit_id = str(uuid4())
        db_session.add(
            AuditLog(
                id=audit_id,
                workspace_id=workspace_id,
                event_type=PROJECTION_FINALIZATION_AUDIT_EVENT,
                actor=activation["activated_by"],
                agent_id=row["system_id"],
                details=projection_activation_audit_details(activation),
            )
        )
        activation["audit_id"] = audit_id
        activations.append(activation)
    return {
        "experience": {"system_360_canary": "v1"},
        "_lot7_projection_rollout_v1": {
            "schema_version": 1,
            "activations": activations,
            "probations": [],
            "deactivations": [],
        },
    }


def _seed(db_session):
    settings = _projection_settings("capability", "run", "skill_invocation")
    workspace = Workspace(
        id="ws-object-api",
        slug="object-api",
        name="Object API",
        settings=settings,
    )
    foreign_workspace = Workspace(
        id="ws-object-api-foreign",
        slug="object-api-foreign",
        name="Foreign",
        settings=settings,
    )
    user = User(id="user-object-api", username="object-api@test", email="object-api@test")
    member = WorkspaceMember(
        user_id=user.id,
        workspace_id=workspace.id,
        role="admin",
        role_template="workspace_admin",
    )
    capability = Capability(
        id="cap-object-api",
        workspace_id=workspace.id,
        slug="cap_object_api",
        name="Capability API",
    )
    system = System(
        id="system-object-api",
        workspace_id=workspace.id,
        name="System API",
        capability_id=capability.id,
        status="active",
        settings=_canary_settings(
            db_session,
            settings,
            workspace_id=workspace.id,
        ),
    )
    run = Run(
        id="run-object-api",
        workspace_id=workspace.id,
        initiated_by_user_id=user.id,
        system_id=system.id,
        capability_id=capability.id,
        status="completed",
    )
    invocation = SkillInvocation(
        id="inv-object-api",
        run_id=run.id,
        skill_slug="claim_audit_v1",
        status="completed",
        cost=0.0,
        cost_measured=True,
        execution_snapshot={
            "schema_version": 1,
            "resolution": "resolved",
            "skill": {"slug": "claim_audit_v1", "version": "1"},
            "digests": {"execution_sha256": "d" * 64},
        },
    )
    foreign_run = Run(
        id="run-object-api-foreign",
        workspace_id=foreign_workspace.id,
        status="completed",
    )
    db_session.add_all([
        workspace,
        foreign_workspace,
        user,
        member,
        capability,
        system,
        run,
        invocation,
        foreign_run,
    ])
    db_session.commit()
    return workspace, user, capability, run, invocation, foreign_run


def _client(db_session, workspace, user):
    app = FastAPI()
    app.include_router(capabilities.router, prefix="/capabilities")
    app.include_router(runs.router, prefix="/runs")
    app.include_router(systems.router, prefix="/systems")
    for module in (capabilities, runs, systems):
        app.dependency_overrides[module.get_current_workspace] = lambda: workspace
        app.dependency_overrides[module.get_current_user] = lambda: user
        app.dependency_overrides[module.get_db] = lambda: db_session
    return TestClient(app)


def test_capability_run_and_invocation_projection_routes(db_session):
    workspace, user, capability, run, invocation, _foreign = _seed(db_session)
    client = _client(db_session, workspace, user)

    capability_response = client.get(
        f"/capabilities/{capability.id}/perspective",
        params={"lens": "build"},
    )
    run_response = client.get(
        f"/runs/{run.id}/perspective",
        params={"lens": "operate"},
    )
    invocation_response = client.get(
        f"/runs/{run.id}/invocations/{invocation.id}/perspective",
        params={"lens": "govern"},
    )
    raw_invocation = client.get(f"/runs/{run.id}/invocations/{invocation.id}")

    assert capability_response.status_code == 200
    assert capability_response.json()["identity"]["capability_id"] == capability.id
    assert run_response.status_code == 200
    assert run_response.json()["identity"]["run_id"] == run.id
    assert invocation_response.status_code == 200
    assert invocation_response.json()["identity"]["skill_invocation_id"] == invocation.id
    assert raw_invocation.status_code == 200
    assert raw_invocation.json()["id"] == invocation.id
    assert raw_invocation.json()["run_id"] == run.id
    assert raw_invocation.json()["cost_measured"] is True
    assert raw_invocation.json()["execution_snapshot"]["skill"]["version"] == "1"


def test_object_projection_routes_fail_closed_by_workspace_and_flag(db_session):
    workspace, user, capability, run, invocation, foreign_run = _seed(db_session)
    client = _client(db_session, workspace, user)

    assert client.get(
        f"/runs/{foreign_run.id}/perspective",
        params={"lens": "operate"},
    ).status_code == 404
    assert client.get(
        f"/runs/{foreign_run.id}/invocations/{invocation.id}",
    ).status_code == 404

    workspace.settings = _projection_settings("capability")
    system = db_session.query(System).filter_by(id=run.system_id).one()
    system.settings = _canary_settings(
        db_session,
        workspace.settings,
        workspace_id=workspace.id,
    )
    db_session.commit()
    assert client.get(
        f"/capabilities/{capability.id}/perspective",
        params={"lens": "build"},
    ).status_code == 200
    assert client.get(
        f"/runs/{run.id}/perspective",
        params={"lens": "operate"},
    ).status_code == 410
    assert client.get(
        f"/runs/{run.id}/invocations/{invocation.id}/perspective",
        params={"lens": "govern"},
    ).status_code == 410
    assert client.get(
        f"/runs/{run.id}/invocations/{invocation.id}",
    ).status_code == 404
    historical_run = client.get(f"/runs/{run.id}")
    assert historical_run.status_code == 200
    historical_invocation = historical_run.json()["invocations"][0]
    assert "cost_measured" not in historical_invocation
    assert "execution_snapshot" not in historical_invocation


def test_object_projection_routes_validate_lens_and_window(db_session):
    workspace, user, capability, run, _invocation, _foreign = _seed(db_session)
    client = _client(db_session, workspace, user)
    assert client.get(
        f"/capabilities/{capability.id}/perspective",
        params={"lens": "hypervisor"},
    ).status_code == 422
    assert client.get(
        f"/runs/{run.id}/perspective",
        params={"lens": "build", "window": "365d"},
    ).status_code == 422


def test_all_projection_routes_compare_canonical_read_action(db_session, monkeypatch):
    workspace, user, capability, run, invocation, _foreign = _seed(db_session)
    calls: list[tuple[str, str, bool]] = []

    def _record(*args, **kwargs):  # noqa: ARG001
        calls.append(
            (
                kwargs["resource_kind"],
                kwargs["action"],
                kwargs["legacy_allowed"],
            )
        )

    monkeypatch.setattr(capabilities, "enforce_action", _record)
    monkeypatch.setattr(runs, "enforce_action", _record)
    monkeypatch.setattr(systems, "enforce_action", _record)
    client = _client(db_session, workspace, user)

    assert client.get(f"/capabilities/{capability.id}").status_code == 200
    assert client.get(
        f"/capabilities/{capability.id}/perspective",
        params={"lens": "build"},
    ).status_code == 200
    assert client.get("/systems/system-object-api").status_code == 200
    assert client.get(f"/runs/{run.id}").status_code == 200
    assert client.get(
        f"/runs/{run.id}/perspective",
        params={"lens": "operate"},
    ).status_code == 200
    assert client.get(
        f"/runs/{run.id}/invocations/{invocation.id}",
    ).status_code == 200
    assert client.get(
        f"/runs/{run.id}/invocations/{invocation.id}/perspective",
        params={"lens": "govern"},
    ).status_code == 200

    assert calls == [
        ("capability", "read", True),
        ("capability", "read", True),
        ("system", "read", True),
        ("run", "read", True),
        ("run", "read", True),
        ("run", "read", True),
        ("skill_invocation", "read", True),
        ("run", "read", True),
        ("skill_invocation", "read", True),
    ]


def test_projection_read_shadow_is_non_blocking_and_enforce_is_authoritative(
    db_session,
    attest_authorization_v2,
):
    workspace, user, _capability, run, invocation, _foreign = _seed(db_session)
    membership = db_session.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == workspace.id,
        WorkspaceMember.user_id == user.id,
    ).one()
    membership.role = "member"
    membership.role_template = "workspace_viewer"
    config = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        version=1,
        role_flags={},
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "modes": {
                    "run.read": "shadow",
                    "skill_invocation.read": "shadow",
                },
            }
        },
        updated_by_user_id=user.id,
    )
    db_session.add(config)
    db_session.commit()
    client = _client(db_session, workspace, user)

    assert client.get(f"/runs/{run.id}").status_code == 200
    assert client.get(
        f"/runs/{run.id}/perspective",
        params={"lens": "operate"},
    ).status_code == 200
    assert client.get(
        f"/runs/{run.id}/invocations/{invocation.id}",
    ).status_code == 200
    assert client.get(
        f"/runs/{run.id}/invocations/{invocation.id}/perspective",
        params={"lens": "govern"},
    ).status_code == 200
    shadow_resources = {
        (row.details or {}).get("resource", {}).get("kind")
        for row in db_session.query(AuditLog).filter(
            AuditLog.workspace_id == workspace.id,
            AuditLog.event_type == "iam.shadow.diff",
        )
    }
    assert shadow_resources == {"run", "skill_invocation"}

    config.capability_overrides = {
        "authorization_v2": {
            "policy_version": 2,
            "default_mode": "compat",
            "modes": {
                "run.read": "enforce",
                "skill_invocation.read": "enforce",
            },
        }
    }
    attest_authorization_v2(
        config,
        ["run.read", "skill_invocation.read"],
    )
    db_session.commit()

    run_denied = client.get(f"/runs/{run.id}")
    run_perspective_denied = client.get(
        f"/runs/{run.id}/perspective",
        params={"lens": "operate"},
    )
    invocation_denied = client.get(
        f"/runs/{run.id}/invocations/{invocation.id}/perspective",
        params={"lens": "govern"},
    )
    raw_invocation_denied = client.get(
        f"/runs/{run.id}/invocations/{invocation.id}",
    )
    assert run_denied.status_code == 403
    assert run_denied.json()["detail"]["mode"] == "enforce"
    assert run_perspective_denied.status_code == 403
    assert run_perspective_denied.json()["detail"]["mode"] == "enforce"
    assert invocation_denied.status_code == 403
    assert invocation_denied.json()["detail"]["mode"] == "enforce"
    assert raw_invocation_denied.status_code == 403
    assert raw_invocation_denied.json()["detail"]["mode"] == "enforce"


def test_skill_invocation_routes_never_bypass_private_parent_run_visibility(db_session):
    workspace, owner, _capability, run, invocation, _foreign = _seed(db_session)
    run.trigger = "chat_agentic"
    intruder = User(
        id="user-object-api-intruder",
        username="intruder-object-api",
        email="intruder-object-api@test",
    )
    intruder_member = WorkspaceMember(
        user_id=intruder.id,
        workspace_id=workspace.id,
        role="member",
        role_template="workspace_contributor",
    )
    db_session.add_all([intruder, intruder_member])
    db_session.commit()
    client = _client(db_session, workspace, intruder)

    assert owner.id == run.initiated_by_user_id
    assert client.get(
        f"/runs/{run.id}/invocations/{invocation.id}",
    ).status_code == 404
    assert client.get(
        f"/runs/{run.id}/invocations/{invocation.id}/perspective",
        params={"lens": "operate"},
    ).status_code == 404


def test_run_collection_stream_and_ledger_honor_independent_read_modes(
    db_session,
    attest_authorization_v2,
):
    workspace, user, capability, run, invocation, _foreign = _seed(db_session)
    membership = db_session.query(WorkspaceMember).filter_by(
        workspace_id=workspace.id,
        user_id=user.id,
    ).one()
    membership.role = "member"
    membership.role_template = "workspace_viewer"
    config = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        version=1,
        role_flags={},
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "modes": {"skill_invocation.read": "enforce"},
            }
        },
        updated_by_user_id=user.id,
    )
    db_session.add(config)
    attest_authorization_v2(config, ["skill_invocation.read"])
    db_session.commit()
    client = _client(db_session, workspace, user)

    detail = client.get(f"/runs/{run.id}")
    assert detail.status_code == 200
    assert detail.json()["invocations"] == []
    assert client.get(
        f"/runs/{run.id}/invocations/{invocation.id}",
    ).status_code == 403

    config.capability_overrides = {
        "authorization_v2": {
            "policy_version": 2,
            "default_mode": "compat",
            "modes": {
                "run.read": "enforce",
                "skill_invocation.read": "compat",
            },
        }
    }
    attest_authorization_v2(config, ["run.read"])
    db_session.commit()

    assert client.get("/runs").json() == {"runs": []}
    assert client.get(f"/runs/{run.id}/stream").status_code == 403
    assert client.get(f"/runs/{run.id}/replays").status_code == 403
    assert client.get(
        f"/runs/{run.id}/invocations/{invocation.id}",
    ).status_code == 403
    capability_payload = client.get(
        f"/capabilities/{capability.id}/perspective",
        params={"lens": "operate"},
    ).json()
    assert run.id not in str(capability_payload)

    config.capability_overrides = {
        "authorization_v2": {
            "policy_version": 2,
            "default_mode": "compat",
            "modes": {
                "run.admin": "enforce",
                "system.engine.run": "enforce",
            },
        }
    }
    attest_authorization_v2(
        config,
        ["run.admin", "system.engine.run"],
    )
    db_session.commit()
    assert client.patch(
        f"/runs/{run.id}/outcome",
        json={"value": 42, "note": "must not apply"},
    ).status_code == 403
    assert client.post(
        f"/runs/{run.id}/replay",
        json={"overrides": {}},
    ).status_code == 403
    assert client.post(f"/runs/{run.id}/rerun").status_code == 403
    run.status = "debug_pending"
    db_session.commit()
    assert client.post(
        f"/runs/{run.id}/step",
        json={"action": "continue"},
    ).status_code == 403


def test_run_outcome_override_persists_exact_redacted_server_receipt(db_session):
    workspace, user, _capability, run, _invocation, _foreign = _seed(db_session)
    client = _client(db_session, workspace, user)

    response = client.patch(
        f"/runs/{run.id}/outcome",
        json={"value": 42.75, "note": "board-only commercial note"},
    )

    assert response.status_code == 200
    db_session.expire_all()
    persisted = db_session.query(Run).filter(Run.id == run.id).one()
    audit = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.workspace_id == workspace.id,
            AuditLog.event_type == RUN_OUTCOME_OVERRIDE_AUDIT_EVENT,
        )
        .one()
    )
    receipt = persisted.output_ref["operator_value_overrides"][-1]
    assert receipt["audit_id"] == audit.id
    assert receipt["artifact_ref"] == audit.details["artifact_ref"]
    assert audit.actor == user.email
    assert audit.details["run_id"] == run.id
    assert set(audit.details) == {
        "schema_version",
        "receipt_schema_version",
        "source",
        "run_id",
        "previous_value_sha256",
        "value_sha256",
        "note_sha256",
        "artifact_ref",
    }
    serialized = json.dumps(audit.details, sort_keys=True)
    assert "board-only commercial note" not in serialized
    assert "42.75" not in serialized
    provenance = response.json()["outcome"]["measurement_provenance"]
    assert provenance["audit_id"] == audit.id
    assert provenance["actor"] == user.email
    assert provenance["artifact_ref"] == receipt["artifact_ref"]


def test_run_outcome_override_rolls_back_when_mandatory_audit_flush_fails(
    db_session,
    monkeypatch,
):
    workspace, user, _capability, run, _invocation, _foreign = _seed(db_session)
    client = _client(db_session, workspace, user)
    before = {
        "value": run.value_estimated,
        "source": run.value_source,
        "note": run.operator_value_note,
        "output_ref": run.output_ref,
    }
    real_flush = db_session.flush

    def fail_operator_audit(*args, **kwargs):
        if any(
            isinstance(row, AuditLog)
            and row.event_type == RUN_OUTCOME_OVERRIDE_AUDIT_EVENT
            for row in db_session.new
        ):
            raise RuntimeError("mandatory audit unavailable")
        return real_flush(*args, **kwargs)

    monkeypatch.setattr(db_session, "flush", fail_operator_audit)
    with pytest.raises(RuntimeError, match="mandatory audit unavailable"):
        client.patch(
            f"/runs/{run.id}/outcome",
            json={"value": 99.0, "note": "must roll back"},
        )

    db_session.expire_all()
    persisted = db_session.query(Run).filter(Run.id == run.id).one()
    assert persisted.value_estimated == before["value"]
    assert persisted.value_source == before["source"]
    assert persisted.operator_value_note == before["note"]
    assert persisted.output_ref == before["output_ref"]
    assert (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == RUN_OUTCOME_OVERRIDE_AUDIT_EVENT)
        .count()
        == 0
    )


def test_run_govern_resolves_real_legacy_approval_and_per_action_mode(
    db_session,
    attest_authorization_v2,
):
    workspace, user, _capability, run, _invocation, _foreign = _seed(db_session)
    membership = db_session.query(WorkspaceMember).filter_by(
        workspace_id=workspace.id,
        user_id=user.id,
    ).one()
    membership.role = "member"
    membership.role_template = "workspace_contributor"
    config = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        version=1,
        role_flags={},
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "modes": {"run.approve": "shadow"},
            }
        },
        updated_by_user_id=user.id,
    )
    db_session.add(config)
    db_session.commit()
    client = _client(db_session, workspace, user)

    payload = client.get(
        f"/runs/{run.id}/perspective",
        params={"lens": "govern"},
    ).json()
    actions = payload["facets"]["overview"]["blocks"][0]["facts"][0]["value"]
    assert actions["approve"]["mode"] == "shadow"
    assert actions["approve"]["legacy_allowed"] is True
    assert actions["approve"]["candidate_allowed"] is False
    assert actions["approve"]["effective_allowed"] is True
    assert "iam_mode" not in str(payload)

    config.capability_overrides = {
        "authorization_v2": {
            "policy_version": 2,
            "default_mode": "compat",
            "modes": {"run.approve": "enforce"},
        }
    }
    attest_authorization_v2(config, ["run.approve"])
    db_session.commit()
    enforced = client.get(
        f"/runs/{run.id}/perspective",
        params={"lens": "govern"},
    ).json()
    actions = enforced["facets"]["overview"]["blocks"][0]["facts"][0]["value"]
    assert actions["approve"]["mode"] == "enforce"
    assert actions["approve"]["effective_allowed"] is False


def test_capability_catalog_and_system_collections_share_read_rollout(
    db_session,
    attest_authorization_v2,
):
    workspace, _member_user, _capability, _run, _invocation, _foreign = _seed(db_session)
    outsider = User(
        id="user-object-api-outsider",
        username="object-api-outsider",
        email="object-api-outsider@test",
    )
    config = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        version=1,
        role_flags={},
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "modes": {
                    "capability.read": "shadow",
                    "system.read": "shadow",
                },
            }
        },
        updated_by_user_id=outsider.id,
    )
    db_session.add_all([outsider, config])
    db_session.commit()
    client = _client(db_session, workspace, outsider)

    assert client.get("/capabilities").status_code == 200
    assert client.get("/capabilities/catalog").status_code == 200
    assert client.get("/systems").status_code == 200

    config.capability_overrides = {
        "authorization_v2": {
            "policy_version": 2,
            "default_mode": "compat",
            "modes": {
                "capability.read": "enforce",
                "system.read": "enforce",
            },
        }
    }
    attest_authorization_v2(
        config,
        ["capability.read", "system.read"],
    )
    db_session.commit()

    for path in ("/capabilities", "/capabilities/catalog", "/systems"):
        response = client.get(path)
        assert response.status_code == 403
        assert response.json()["detail"]["mode"] == "enforce"
