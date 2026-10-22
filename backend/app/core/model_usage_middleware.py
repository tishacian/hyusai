"""Request lifetime for usage attribution resolved by authenticated dependencies."""

from starlette.types import ASGIApp, Receive, Scope, Send


class ModelUsageContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        from app.services.model_usage_transport import request_usage_scope

        # The holder is created before sync dependencies enter a thread pool.
        # Only get_current_workspace binds it, after checking membership. No
        # workspace, principal or correlation id is trusted from the request.
        # Pure ASGI keeps it alive until streaming/background work completes.
        with request_usage_scope():
            await self.app(scope, receive, send)
