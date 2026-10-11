from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import build_info
from app.core.config import settings


def test_build_info_exposes_exact_full_revision(monkeypatch) -> None:
    revision = "a" * 40
    monkeypatch.setattr(settings, "agentium_image_revision", revision)
    app = FastAPI()
    app.include_router(build_info.router, prefix="/api/v1/build-info")

    response = TestClient(app).get("/api/v1/build-info")

    assert response.status_code == 200
    assert response.json() == {
        "service": "backend",
        "revision": revision,
        "revision_verified": True,
        "version": settings.app_version,
    }


def test_build_info_marks_local_revision_unverified(monkeypatch) -> None:
    monkeypatch.setattr(settings, "agentium_image_revision", "development")
    app = FastAPI()
    app.include_router(build_info.router, prefix="/api/v1/build-info")

    assert TestClient(app).get("/api/v1/build-info").json()["revision_verified"] is False
