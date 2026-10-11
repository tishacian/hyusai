from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import auth
from app.models.user import User


def _client(db_session) -> TestClient:
    app = FastAPI()
    app.include_router(auth.router, prefix="/auth")
    app.dependency_overrides[auth.get_db] = lambda: db_session
    return TestClient(app)


def test_signup_triggers_keycloak_verify_email(db_session, monkeypatch):
    requests: list[dict] = []

    class FakeResponse:
        def __init__(self, status_code: int, *, headers: dict | None = None, text: str = ""):
            self.status_code = status_code
            self.headers = headers or {}
            self.text = text

        def json(self) -> dict:
            return {}

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, json=None, headers=None, timeout=None, **kwargs):
            requests.append({"method": "POST", "url": url, "json": json, "headers": headers})
            return FakeResponse(
                201,
                headers={"Location": "http://kc/admin/realms/papai-org/users/kc-user-1"},
            )

        async def put(self, url, *, json=None, headers=None, timeout=None, **kwargs):
            requests.append({"method": "PUT", "url": url, "json": json, "headers": headers})
            return FakeResponse(204)

    async def fake_admin_token():
        return "admin-token"

    monkeypatch.setattr(auth, "_get_admin_token", fake_admin_token)
    monkeypatch.setattr(auth, "_get_admin_url", lambda: "http://kc/admin/realms/papai-org")
    monkeypatch.setattr(auth.httpx, "AsyncClient", FakeAsyncClient)

    response = _client(db_session).post(
        "/auth/signup",
        json={
            "first_name": "Eric",
            "last_name": "Oneill",
            "email": "eric.oneill@datategy.net",
            "password": "Str0ng!Pass",
        },
    )

    assert response.status_code == 200
    assert response.json()["verification_email_sent"] is True
    assert db_session.query(User).filter(User.email == "eric.oneill@datategy.net").one()
    assert requests[0]["method"] == "POST"
    assert requests[0]["json"]["emailVerified"] is False
    assert requests[1] == {
        "method": "PUT",
        "url": "http://kc/admin/realms/papai-org/users/kc-user-1/execute-actions-email",
        "json": ["VERIFY_EMAIL"],
        "headers": {
            "Authorization": "Bearer admin-token",
            "Content-Type": "application/json",
        },
    }
