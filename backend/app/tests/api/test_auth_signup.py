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


def _fake_keycloak(monkeypatch, users: list[dict], *, put_status: int = 204) -> list[dict]:
    requests: list[dict] = []

    class FakeResponse:
        def __init__(self, status_code: int, payload=None):
            self.status_code = status_code
            self.headers = {}
            self.text = ""
            self._payload = payload

        def json(self):
            return self._payload

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, *, params=None, headers=None, timeout=None, **kwargs):
            requests.append({"method": "GET", "url": url, "params": params})
            return FakeResponse(200, users)

        async def put(self, url, *, json=None, headers=None, timeout=None, **kwargs):
            requests.append({"method": "PUT", "url": url, "json": json})
            return FakeResponse(put_status)

    async def fake_admin_token():
        return "admin-token"

    monkeypatch.setattr(auth, "_get_admin_token", fake_admin_token)
    monkeypatch.setattr(auth, "_get_admin_url", lambda: "http://kc/admin/realms/papai-org")
    monkeypatch.setattr(auth.httpx, "AsyncClient", FakeAsyncClient)
    return requests


def test_resend_verification_sends_to_unverified_account(db_session, monkeypatch):
    requests = _fake_keycloak(
        monkeypatch,
        [{"id": "kc-user-1", "email": "ada@example.com", "enabled": True, "emailVerified": False}],
    )

    response = _client(db_session).post(
        "/auth/signup/resend-verification", json={"email": "Ada@example.com"}
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "verification_email_sent": True}
    assert requests[-1] == {
        "method": "PUT",
        "url": "http://kc/admin/realms/papai-org/users/kc-user-1/execute-actions-email",
        "json": ["VERIFY_EMAIL"],
    }


def test_resend_verification_skips_verified_or_unknown_accounts(db_session, monkeypatch):
    requests = _fake_keycloak(
        monkeypatch,
        [{"id": "kc-user-1", "email": "ada@example.com", "enabled": True, "emailVerified": True}],
    )

    response = _client(db_session).post(
        "/auth/signup/resend-verification", json={"email": "ada@example.com"}
    )

    assert response.status_code == 200
    assert response.json()["verification_email_sent"] is False
    assert all(request["method"] == "GET" for request in requests)


def test_resend_verification_reports_a_failed_send(db_session, monkeypatch):
    _fake_keycloak(
        monkeypatch,
        [{"id": "kc-user-1", "email": "ada@example.com", "enabled": True, "emailVerified": False}],
        put_status=500,
    )

    response = _client(db_session).post(
        "/auth/signup/resend-verification", json={"email": "ada@example.com"}
    )

    assert response.json()["verification_email_sent"] is False
