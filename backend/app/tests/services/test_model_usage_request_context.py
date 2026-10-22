"""Real ASGI/threadpool propagation, with no provider or database calls."""

import asyncio
from types import SimpleNamespace

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException

from app.core.auth import _bind_workspace_usage
from app.core.model_usage_middleware import ModelUsageContextMiddleware
from app.services.model_usage import UsageContext
from app.services.model_usage_transport import current_scope, usage_scope


def test_authenticated_sync_dependency_binds_async_transport_without_cross_request_leak():
    app = FastAPI()
    app.add_middleware(ModelUsageContextMiddleware)

    def resolve_workspace(authorization: str = Header()):
        if authorization not in {"user-a", "user-b"}:
            raise HTTPException(403)
        _bind_workspace_usage(
            SimpleNamespace(id=authorization + "-workspace"), SimpleNamespace(id=authorization)
        )

    @app.get("/call", dependencies=[Depends(resolve_workspace)])
    async def call():
        await asyncio.sleep(0)
        scope = current_scope()
        assert scope is not None
        return {"workspace": scope.workspace_id, "actor": scope.actor_user_id}

    @app.get("/public")
    async def public():
        return {"unbound": current_scope() is None}

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            replies = await asyncio.gather(
                *(
                    client.get(
                        "/call",
                        headers={
                            "Authorization": principal,
                            "X-Workspace-Slug": "forged-workspace",
                        },
                    )
                    for principal in ("user-a", "user-b")
                )
            )
            assert [reply.json() for reply in replies] == [
                {"workspace": "user-a-workspace", "actor": "user-a"},
                {"workspace": "user-b-workspace", "actor": "user-b"},
            ]
            assert (
                await client.get("/call", headers={"Authorization": "invalid"})
            ).status_code == 403
            assert (await client.get("/public")).json() == {"unbound": True}
            assert current_scope() is None

    asyncio.run(check())


def test_run_scope_overrides_request_fallback_then_restores_it():
    from app.services.model_usage_transport import request_usage_scope

    with request_usage_scope():
        _bind_workspace_usage(SimpleNamespace(id="workspace"), SimpleNamespace(id="actor"))
        assert current_scope().actor_user_id == "actor"
        with usage_scope(UsageContext(workspace_id="workspace", run_id="run-1", purpose="judge")):
            assert current_scope().run_id == "run-1"
            assert current_scope().purpose == "judge"
        assert current_scope().run_id is None
        assert current_scope().actor_user_id == "actor"
    assert current_scope() is None
