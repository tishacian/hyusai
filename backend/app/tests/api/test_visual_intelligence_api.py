from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import visual_intelligence
from app.models.audit import AuditLog
from app.models.knowledge_collection import KnowledgeCollection
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_visual import WorkspaceVisualCapture, WorkspaceVisualObservation, WorkspaceVisualSource
from app.services import visual_intelligence as visual_service


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(visual_intelligence.router, prefix="/api/v1/visual-intelligence")
    app.dependency_overrides[visual_intelligence.get_current_workspace] = lambda: workspace
    app.dependency_overrides[visual_intelligence.get_current_user] = lambda: user
    app.dependency_overrides[visual_intelligence.get_db] = lambda: db_session
    return TestClient(app)


def test_visual_sources_seed_capture_dashboard_and_image_are_workspace_scoped(db_session, monkeypatch):
    monkeypatch.setattr(
        visual_service,
        "_fetch_http_image",
        lambda _url: (b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", "image/svg+xml"),
    )
    workspace = Workspace(id="workspace-sentinel", slug="sentinel-ci", name="SENTINEL-CI", mode="demo")
    user = User(id="user-1", username="minister", email="minister@example.test", is_active=True)
    db_session.add_all([workspace, user])
    db_session.commit()
    client = _client(db_session, workspace, user)

    sources = client.get("/api/v1/visual-intelligence/sources")

    assert sources.status_code == 200
    source = sources.json()["sources"][0]
    assert source["adapter"] == "http_image"
    assert source["metadata"]["layer_kind"] == "webcam_snapshot"
    assert source["region"] == "Abidjan / Le Plateau"

    capture = client.post(f"/api/v1/visual-intelligence/sources/{source['id']}/capture")

    assert capture.status_code == 200
    capture_body = capture.json()
    assert capture_body["capture"]["status"] == "analyzed"
    assert capture_body["observation"]["level_label"] in {"stable", "monitoring", "elevated", "critical"}

    dashboard = client.get("/api/v1/visual-intelligence/dashboard")

    assert dashboard.status_code == 200
    assert dashboard.json()["source_health"]["captures"] == 1
    assert dashboard.json()["latest_observation"]["capture_id"] == capture_body["capture"]["id"]

    image = client.get(f"/api/v1/visual-intelligence/captures/{capture_body['capture']['id']}/image")

    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/svg+xml")
    assert b"<svg" in image.content

    collection = db_session.query(KnowledgeCollection).filter_by(slug="sentinel-ci-visual-intelligence").one()
    assert collection.workspace_id == workspace.id
    assert collection.document_count == 1
    assert db_session.query(WorkspaceVisualSource).filter_by(workspace_id=workspace.id).count() == 1
    assert db_session.query(WorkspaceVisualCapture).filter_by(workspace_id=workspace.id).count() == 1
    assert db_session.query(WorkspaceVisualObservation).filter_by(workspace_id=workspace.id).count() == 1

    event_types = {row.event_type for row in db_session.query(AuditLog).all()}
    assert "visual.capture.completed" in event_types
    assert "visual.observation.synced_to_knowledge" in event_types


def test_visual_capture_image_cannot_cross_workspace(db_session, monkeypatch):
    monkeypatch.setattr(
        visual_service,
        "_fetch_http_image",
        lambda _url: (b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", "image/svg+xml"),
    )
    sentinel = Workspace(id="workspace-sentinel", slug="sentinel-ci", name="SENTINEL-CI", mode="demo")
    other = Workspace(id="workspace-other", slug="andritz", name="Andritz", mode="standard")
    user = User(id="user-1", username="minister", email="minister@example.test", is_active=True)
    db_session.add_all([sentinel, other, user])
    db_session.commit()
    sentinel_client = _client(db_session, sentinel, user)
    other_client = _client(db_session, other, user)

    source = sentinel_client.get("/api/v1/visual-intelligence/sources").json()["sources"][0]
    capture = sentinel_client.post(f"/api/v1/visual-intelligence/sources/{source['id']}/capture").json()["capture"]

    response = other_client.get(f"/api/v1/visual-intelligence/captures/{capture['id']}/image")

    assert response.status_code == 404


def test_visual_capture_uses_vlm_analysis_when_enabled(db_session, monkeypatch):
    monkeypatch.setattr(
        visual_service,
        "_fetch_http_image",
        lambda _url: (b"\xff\xd8\xff\xe0visual", "image/jpeg"),
    )
    monkeypatch.setattr(visual_service.settings, "visual_analysis_enabled", True)
    monkeypatch.setattr(
        visual_service,
        "_run_visual_analysis",
        lambda *_args, **_kwargs: {
            "analysis": "vlm",
            "provider": "openai",
            "model": "gpt-4o-mini",
            "summary": "Image exploitable: flux calme, aucune anomalie visible.",
            "tags": ["flux-visuel", "abidjan", "calme"],
            "confidence": 0.74,
            "vigilance_score": 22,
            "level_label": "stable",
            "observations": ["couloir calme"],
            "recommended_next_step": "Maintenir la veille periodique.",
        },
    )
    workspace = Workspace(id="workspace-sentinel", slug="sentinel-ci", name="SENTINEL-CI", mode="demo")
    user = User(id="user-1", username="minister", email="minister@example.test", is_active=True)
    db_session.add_all([workspace, user])
    db_session.commit()
    client = _client(db_session, workspace, user)

    source = client.get("/api/v1/visual-intelligence/sources").json()["sources"][0]
    capture = client.post(f"/api/v1/visual-intelligence/sources/{source['id']}/capture")

    assert capture.status_code == 200
    observation = capture.json()["observation"]
    assert observation["provider"] == "openai"
    assert observation["model"] == "gpt-4o-mini"
    assert observation["vigilance_score"] == 22
    assert "Image exploitable" in observation["summary"]
