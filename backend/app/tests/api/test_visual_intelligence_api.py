from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import visual_intelligence
from app.models.audit import AuditLog
from app.models.knowledge_collection import KnowledgeCollection
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_visual import (
    WorkspaceVisualCapture,
    WorkspaceVisualObservation,
    WorkspaceVisualSource,
)
from app.services import visual_intelligence as visual_service


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(visual_intelligence.router, prefix="/api/v1/visual-intelligence")
    app.dependency_overrides[visual_intelligence.get_current_workspace] = lambda: workspace
    app.dependency_overrides[visual_intelligence.get_current_user] = lambda: user
    app.dependency_overrides[visual_intelligence.get_db] = lambda: db_session
    return TestClient(app)


def test_visual_seed_gate_is_explicit_and_slug_independent(db_session):
    user = User(id="user-visual-contract", username="viewer", is_active=True)
    legacy_slug = Workspace(
        id="workspace-legacy-visual-slug",
        slug="sentinel-ci",
        name="Legacy name only",
        mode="demo",
        settings={},
    )
    configured = Workspace(
        id="workspace-configured-visual",
        slug="configured-visual",
        name="Configured visual workspace",
        mode="demo",
        settings={"visual_intelligence": {"enabled": True}},
    )
    malformed = Workspace(
        id="workspace-malformed-visual",
        slug="sentinel-ci-copy",
        name="Malformed visual workspace",
        mode="demo",
        settings={"visual_intelligence": {"enabled": "true"}},
    )
    db_session.add_all([user, legacy_slug, configured, malformed])
    db_session.commit()

    assert _client(db_session, legacy_slug, user).get(
        "/api/v1/visual-intelligence/sources"
    ).json() == {"sources": []}
    assert _client(db_session, malformed, user).get(
        "/api/v1/visual-intelligence/sources"
    ).json() == {"sources": []}
    configured_sources = _client(db_session, configured, user).get(
        "/api/v1/visual-intelligence/sources"
    )
    assert configured_sources.status_code == 200
    assert configured_sources.json()["sources"]


def test_visual_chat_gate_uses_declared_profile_and_action_pack() -> None:
    legacy_profile_name = Workspace(
        id="workspace-legacy-visual-profile",
        slug="sentinel-ci",
        name="Legacy visual profile",
        settings={"visual_intelligence": {"enabled": True}},
    )
    configured = Workspace(
        id="workspace-configured-visual-profile",
        slug="institutional-operations",
        name="Configured visual profile",
        settings={
            "visual_intelligence": {"enabled": True},
            "assistant_profiles": [
                {
                    "key": "operations_executive",
                    "actions": {"enabled_packs": ["sentinel_ci_aya_v1"]},
                }
            ],
        },
    )
    crossed = Workspace(
        id="workspace-crossed-visual-profile",
        slug="crossed-visual-profile",
        name="Crossed visual profile",
        settings={
            "visual_intelligence": {"enabled": True},
            "assistant_profiles": [
                {
                    "key": "crossed_executive",
                    "actions": {
                        "enabled_packs": [
                            "sentinel_ci_aya_v1",
                            "octave_mission_room_v1",
                        ]
                    },
                }
            ],
        },
    )

    assert not visual_service._visual_chat_profile_enabled(
        legacy_profile_name,
        "vigie_executive",
    )
    assert visual_service._visual_chat_profile_enabled(
        configured,
        "operations_executive",
    )
    assert not visual_service._visual_chat_profile_enabled(
        crossed,
        "crossed_executive",
    )


def test_visual_sources_seed_capture_dashboard_and_image_are_workspace_scoped(
    db_session, monkeypatch
):
    monkeypatch.setattr(
        visual_service,
        "_fetch_http_image",
        lambda _url: (b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", "image/svg+xml"),
    )
    monkeypatch.setattr(visual_service.settings, "worker_eager_mode", True)
    workspace = Workspace(
        id="workspace-sentinel",
        slug="sentinel-ci",
        name="SENTINEL-CI",
        mode="demo",
        settings={"visual_intelligence": {"enabled": True}},
    )
    user = User(id="user-1", username="minister", email="minister@example.test", is_active=True)
    db_session.add_all([workspace, user])
    db_session.commit()
    client = _client(db_session, workspace, user)

    sources = client.get("/api/v1/visual-intelligence/sources")

    assert sources.status_code == 200
    source = sources.json()["sources"][0]
    assert source["adapter"] == "http_image"
    assert source["source_type"] == "stream_embed"
    assert source["metadata"]["provider"] == "abidjan.net"
    assert source["metadata"]["layer_kind"] == "live_webcam_snapshot"
    assert source["metadata"]["preferred_render"] == "snapshot"
    assert source["metadata"]["embed_status"] == "unstable"
    assert source["metadata"]["embed_url"].startswith("https://video.nest.com/embedded/live/")
    assert source["metadata"]["preview_url"].startswith("https://media-files.abidjan.net/camera/")
    assert source["region"] == "Abidjan / Pont General-de-Gaulle"

    capture = client.post(f"/api/v1/visual-intelligence/sources/{source['id']}/capture")

    assert capture.status_code == 202
    capture_body = capture.json()
    assert capture_body["job"]["status"] == "completed"

    dashboard = client.get("/api/v1/visual-intelligence/dashboard")

    assert dashboard.status_code == 200
    assert dashboard.json()["source_health"]["captures"] == 1
    assert dashboard.json()["source_health"]["freshness_status"] == "fresh"
    latest = dashboard.json()["latest_observation"]
    assert latest["level_label"] in {"stable", "monitoring", "elevated", "critical"}

    image = client.get(f"/api/v1/visual-intelligence/captures/{latest['capture_id']}/image")

    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/svg+xml")
    assert b"<svg" in image.content

    collection = (
        db_session.query(KnowledgeCollection)
        .filter_by(slug="sentinel-ci-visual-intelligence")
        .one()
    )
    assert collection.workspace_id == workspace.id
    assert collection.document_count == 1
    assert db_session.query(WorkspaceVisualSource).filter_by(
        workspace_id=workspace.id
    ).count() == len(visual_service.ABIDJAN_NET_VISUAL_SOURCES)
    assert (
        db_session.query(WorkspaceVisualCapture).filter_by(workspace_id=workspace.id).count() == 1
    )
    assert (
        db_session.query(WorkspaceVisualObservation).filter_by(workspace_id=workspace.id).count()
        == 1
    )

    event_types = {row.event_type for row in db_session.query(AuditLog).all()}
    assert "visual.capture.completed" in event_types
    assert "visual.observation.synced_to_knowledge" in event_types


def test_visual_capture_image_cannot_cross_workspace(db_session, monkeypatch):
    monkeypatch.setattr(
        visual_service,
        "_fetch_http_image",
        lambda _url: (b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", "image/svg+xml"),
    )
    monkeypatch.setattr(visual_service.settings, "worker_eager_mode", True)
    sentinel = Workspace(
        id="workspace-sentinel",
        slug="sentinel-ci",
        name="SENTINEL-CI",
        mode="demo",
        settings={"visual_intelligence": {"enabled": True}},
    )
    other = Workspace(id="workspace-other", slug="andritz", name="Andritz", mode="builder")
    user = User(id="user-1", username="minister", email="minister@example.test", is_active=True)
    db_session.add_all([sentinel, other, user])
    db_session.commit()
    sentinel_client = _client(db_session, sentinel, user)
    other_client = _client(db_session, other, user)

    source = sentinel_client.get("/api/v1/visual-intelligence/sources").json()["sources"][0]
    sentinel_client.post(f"/api/v1/visual-intelligence/sources/{source['id']}/capture")
    capture = (
        db_session.query(WorkspaceVisualCapture)
        .filter_by(workspace_id=sentinel.id)
        .order_by(WorkspaceVisualCapture.captured_at.desc())
        .first()
    )

    response = other_client.get(f"/api/v1/visual-intelligence/captures/{capture.id}/image")

    assert response.status_code == 404


def test_visual_capture_uses_vlm_analysis_when_enabled(db_session, monkeypatch):
    monkeypatch.setattr(
        visual_service,
        "_fetch_http_image",
        lambda _url: (b"\xff\xd8\xff\xe0visual", "image/jpeg"),
    )
    monkeypatch.setattr(visual_service.settings, "worker_eager_mode", True)
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
    workspace = Workspace(
        id="workspace-sentinel",
        slug="sentinel-ci",
        name="SENTINEL-CI",
        mode="demo",
        settings={"visual_intelligence": {"enabled": True}},
    )
    user = User(id="user-1", username="minister", email="minister@example.test", is_active=True)
    db_session.add_all([workspace, user])
    db_session.commit()
    client = _client(db_session, workspace, user)

    source = client.get("/api/v1/visual-intelligence/sources").json()["sources"][0]
    capture = client.post(f"/api/v1/visual-intelligence/sources/{source['id']}/capture")

    assert capture.status_code == 202
    observation_row = (
        db_session.query(WorkspaceVisualObservation).filter_by(workspace_id=workspace.id).one()
    )
    observation = visual_service.serialize_observation(observation_row)
    assert observation["provider"] == "openai"
    assert observation["model"] == "gpt-4o-mini"
    assert observation["vigilance_score"] == 22
    assert "Image exploitable" in observation["summary"]
