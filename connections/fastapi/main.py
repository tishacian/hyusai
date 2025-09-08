from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from logging_utils.asgi import LoggingMiddleware
from pydantic import ValidationError

from connections.fastapi.api.api import api_router
from connections.fastapi.utils import get_traceback

app = FastAPI()
# CorrelationIdMiddleware must come after LoggingMiddleware so that all logs
# (and particularly the ones before processing the request) have a correlation id
# The reason there is a type error is because LoggingMiddleware is using asgiref
# for typing (as recommended in Starlette docs).
app.add_middleware(LoggingMiddleware)  # type: ignore[arg-type]
app.add_middleware(CorrelationIdMiddleware)

app.include_router(api_router)


@app.exception_handler(Exception)
async def general_exception_handler(request, exc: Exception):
    if isinstance(exc, ValidationError):
        return PlainTextResponse(f"Validation error: {exc.errors()}", status_code=422)

    traceback = get_traceback(exc=exc)

    if hasattr(exc, "status_code"):
        return PlainTextResponse(traceback, status_code=getattr(exc, "status_code"))

    return PlainTextResponse(traceback, status_code=500)
