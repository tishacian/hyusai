from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import auth


def keycloak(monkeypatch, *, users=None, lookup_status=200, send_status=204, network_error=False):
    calls = []

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, url, **kwargs):
            if network_error:
                raise httpx.ConnectError("unavailable")
            calls.append(("get", url))
            return SimpleNamespace(status_code=lookup_status, json=lambda: users or [])

        async def put(self, url, **kwargs):
            calls.append(("put", url))
            return SimpleNamespace(status_code=send_status)

    async def token():
        return "local-test-token"

    monkeypatch.setattr(auth, "_get_admin_token", token)
    monkeypatch.setattr(auth.httpx, "AsyncClient", Client)
    return calls


@pytest.mark.asyncio
async def test_reset_unknown_and_known_accounts_have_identical_neutral_success(monkeypatch):
    request = auth.PasswordResetRequest(email="reader@example.com")
    keycloak(monkeypatch)
    unknown = await auth.password_reset(request)
    calls = keycloak(monkeypatch, users=[{"id": "user-1", "email": request.email, "enabled": True}])
    known = await auth.password_reset(request)
    assert known == unknown
    assert len([method for method, _ in calls if method == "put"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "options", [{"lookup_status": 500}, {"send_status": 500}, {"network_error": True}]
)
async def test_reset_failure_never_claims_email_was_sent(monkeypatch, options):
    keycloak(
        monkeypatch,
        users=[{"id": "user-1", "email": "reader@example.com", "enabled": True}],
        **options,
    )
    with pytest.raises(HTTPException) as failed:
        await auth.password_reset(auth.PasswordResetRequest(email="reader@example.com"))
    assert failed.value.status_code == 502
    assert failed.value.detail["code"] == "password_reset_unavailable"
    assert "reader@example.com" not in str(failed.value.detail)


@pytest.mark.asyncio
async def test_sessions_failure_is_not_an_empty_list(monkeypatch):
    keycloak(monkeypatch, lookup_status=500)
    with pytest.raises(HTTPException) as failed:
        await auth.list_sessions(SimpleNamespace(keycloak_sub="user-1"))
    assert failed.value.status_code == 502
    assert failed.value.detail["code"] == "sessions_unavailable"
