from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import client360
from app.core.iam.roles import WORKSPACE_CONTRIBUTOR, WORKSPACE_OWNER
from app.models.capability import Capability
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.client360_contract import (
    CLIENT360_CAPABILITY_SLUG,
    CLIENT360_SYSTEM_VARIANT,
)


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(client360.router, prefix="/api/v1/client360")
    app.dependency_overrides[client360.get_db] = lambda: db_session
    app.dependency_overrides[client360.get_current_workspace] = lambda: workspace
    app.dependency_overrides[client360.get_current_user] = lambda: user
    return TestClient(app)


def _seed(db_session):
    workspace = Workspace(
        id="workspace-client360-mail-api",
        name="Client360 Mail API",
        slug="client360-mail-api",
        settings={"family": "andritz"},
    )
    owner = User(
        id="user-client360-mail-owner",
        username="client360-mail-owner",
        email="client360-mail-owner@example.test",
        role="user",
    )
    contributor = User(
        id="user-client360-mail-contributor",
        username="client360-mail-contributor",
        email="client360-mail-contributor@example.test",
        role="user",
    )
    capability = Capability(
        id="capability-client360-mail-api",
        workspace_id=workspace.id,
        slug=CLIENT360_CAPABILITY_SLUG,
        name="Client360 Opportunity Engine",
        tier="client",
    )
    system = System(
        id="system-client360-mail-api",
        workspace_id=workspace.id,
        name="Client360 mail authority",
        objective="Exercise workspace-scoped SMTP configuration.",
        capability_id=capability.id,
        status="active",
        settings={"system_type": CLIENT360_SYSTEM_VARIANT},
        flow_definition={"variant": CLIENT360_SYSTEM_VARIANT},
    )
    db_session.add_all(
        [
            workspace,
            owner,
            contributor,
            capability,
            system,
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=owner.id,
                role="owner",
                role_template=WORKSPACE_OWNER,
            ),
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=contributor.id,
                role="member",
                role_template=WORKSPACE_CONTRIBUTOR,
            ),
        ]
    )
    db_session.commit()
    return workspace, owner, contributor


def test_client360_mail_settings_require_admin_even_with_application_access(
    db_session,
) -> None:
    workspace, _owner, contributor = _seed(db_session)

    response = _client(db_session, workspace, contributor).patch(
        "/api/v1/client360/mail-settings",
        json={"host": "smtp.example.test"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "WORKSPACE_PERMISSION_DENIED"
    db_session.refresh(workspace)
    assert "client360_pdr_mail" not in workspace.settings


def test_client360_mail_settings_admin_patch_is_persisted_under_workspace_lock(
    db_session,
) -> None:
    workspace, owner, _contributor = _seed(db_session)

    response = _client(db_session, workspace, owner).patch(
        "/api/v1/client360/mail-settings",
        json={"host": "smtp.example.test", "enabled": True},
    )

    assert response.status_code == 200, response.text
    db_session.refresh(workspace)
    smtp = workspace.settings["client360_pdr_mail"]["smtp"]
    assert smtp["host"] == "smtp.example.test"
    assert smtp["enabled"] is True


def test_client360_mail_settings_encrypt_password_and_refuse_encrypted_write(
    db_session, monkeypatch
) -> None:
    from cryptography.fernet import Fernet

    from app.services.client360_pdr import (
        CLIENT360_SMTP_ENV_MASTER_KEY,
        CLIENT360_SMTP_ENV_MASTER_KEY_FALLBACK,
        _decrypt_smtp_password,
        client360_mail_settings_payload,
    )

    monkeypatch.delenv(CLIENT360_SMTP_ENV_MASTER_KEY, raising=False)
    monkeypatch.setenv(CLIENT360_SMTP_ENV_MASTER_KEY_FALLBACK, Fernet.generate_key().decode())
    workspace, owner, _contributor = _seed(db_session)
    secret = "smtp-password-never-echoed"
    admin = _client(db_session, workspace, owner)

    written = admin.patch(
        "/api/v1/client360/mail-settings",
        json={"host": "smtp.example.test", "username": "bot", "password": secret},
    )
    assert written.status_code == 200, written.text
    assert "password" not in written.json()["mail_settings"]
    assert written.json()["mail_settings"]["password_configured"] is True
    assert secret not in written.text

    listed = admin.get("/api/v1/client360/mail-settings")
    assert listed.status_code == 200
    assert "password" not in listed.json()["mail_settings"]
    assert secret not in listed.text
    assert "password" not in client360_mail_settings_payload(workspace)

    db_session.refresh(workspace)
    smtp = workspace.settings["client360_pdr_mail"]["smtp"]
    assert "password" not in smtp
    assert "ciphertext" in smtp["password_encrypted"]
    assert secret not in smtp["password_encrypted"]
    assert _decrypt_smtp_password(smtp["password_encrypted"]) == secret

    forged = admin.patch(
        "/api/v1/client360/mail-settings",
        json={"password_encrypted": "forged-envelope"},
    )
    assert forged.status_code == 422
    assert forged.json()["detail"]["code"] == "WORKSPACE_SECRET_WRITE_ONLY"

    omitted = admin.patch("/api/v1/client360/mail-settings", json={"from_name": "Desk"})
    assert omitted.status_code == 200
    db_session.refresh(workspace)
    assert (
        _decrypt_smtp_password(
            workspace.settings["client360_pdr_mail"]["smtp"]["password_encrypted"]
        )
        == secret
    )
