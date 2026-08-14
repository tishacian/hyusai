"""Experience releases retain their exact System dependencies."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import systems as systems_endpoint
from app.models.experience import Experience, ExperienceRelease
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.chains import version_service
from app.services.run_engine.execution_contract import canonical_flow_sha256


def _seed(db_session):
    workspace = Workspace(id="ws-xp-retention", slug="xp-retention", name="XP retention")
    user = User(
        id="user-xp-retention",
        username="xp-retention@example.invalid",
        email="xp-retention@example.invalid",
        role="admin",
    )
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="admin",
        role_template="workspace_admin",
    )
    flow = {"nodes": [], "edges": []}
    system = System(
        id="system-xp-retention",
        workspace_id=workspace.id,
        name="Retained",
        objective="test",
        status="active",
        flow_definition=flow,
    )
    experience = Experience(
        id="experience-xp-retention",
        workspace_id=workspace.id,
        name="Retained app",
        slug="retained-app",
        pattern="dashboard",
        languages=[],
        theme={},
        access_policy={},
    )
    db_session.add_all([workspace, user, member, system, experience])
    db_session.flush()
    versions = [
        SystemVersion(
            id=f"system-xp-retention-v{number}",
            system_id=system.id,
            workspace_id=workspace.id,
            version_number=number,
            flow_definition=flow,
            flow_sha256=canonical_flow_sha256(flow),
            execution_contract={},
            created_by=user.email,
        )
        for number in (1, 2)
    ]
    db_session.add_all(versions)
    db_session.flush()
    system.published_flow_version_id = versions[1].id
    release = ExperienceRelease(
        id="experience-xp-retention-r1",
        experience_id=experience.id,
        workspace_id=workspace.id,
        release_number=1,
        content_sha256="a" * 64,
        pages={"pages": []},
        bindings_snapshot=[
            {
                "binding_key": "retained.read",
                "system_id": system.id,
                "published_flow_version_id": versions[0].id,
            }
        ],
        access_snapshot={},
        languages=[],
        theme={},
        renderer_version="certified-components-0.1.0",
        notes="retention",
        created_by=user.email,
    )
    db_session.add(release)
    db_session.commit()
    return workspace, user, system, versions


def test_undeployed_release_blocks_system_delete(db_session) -> None:
    workspace, user, system, _versions = _seed(db_session)
    app = FastAPI()
    app.include_router(systems_endpoint.router, prefix="/systems")
    app.dependency_overrides[systems_endpoint.get_current_workspace] = lambda: workspace
    app.dependency_overrides[systems_endpoint.get_current_user] = lambda: user
    app.dependency_overrides[systems_endpoint.get_db] = lambda: db_session

    response = TestClient(app).delete(f"/systems/{system.id}")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SYSTEM_REFERENCED_BY_EXPERIENCE_RELEASE"
    assert response.json()["detail"]["references"][0]["active"] is False
    assert db_session.get(System, system.id) is not None


def test_release_version_is_protected_from_fifo_trimming(db_session, monkeypatch) -> None:
    _workspace, _user, system, versions = _seed(db_session)
    monkeypatch.setattr(version_service.settings, "custom_chain_version_window", 1)

    purged = version_service.purge_version_window(db=db_session, system_id=system.id)

    assert purged == []
    assert db_session.get(SystemVersion, versions[0].id) is not None
    assert db_session.get(SystemVersion, versions[1].id) is not None
