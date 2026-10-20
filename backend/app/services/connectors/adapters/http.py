"""Bounded HTTPS requests for runner adapters, with pinned DNS and no redirects."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from pathlib import Path

import httpx

from app.services.connectors.adapters.sql import AdapterError, _remaining
from app.services.connectors.http_transport import destination_for_url, pinned_client


@contextmanager
def response(method, url, *, deadline_at, headers=None, content=None):
    # Signed URLs (SAS, lakehouse links) must never reach HTTP client logs.
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    logging.getLogger("httpcore").setLevel(logging.CRITICAL)
    checked, destination = destination_for_url(url, require_https=True)
    try:
        with pinned_client(
            checked, destination, timeout=min(30, _remaining(deadline_at))
        ) as client:
            with client.stream(method, checked, headers=headers, content=content) as reply:
                if 300 <= reply.status_code < 400:
                    raise AdapterError("CONNECTOR_REDIRECT_DENIED")
                if reply.status_code in (401, 403):
                    raise AdapterError("CONNECTOR_AUTH_DENIED")
                if reply.status_code in (409, 412):
                    raise AdapterError("CONNECTOR_SOURCE_CHANGED")
                if reply.status_code == 404:
                    raise AdapterError("CONNECTOR_SOURCE_NOT_FOUND")
                if reply.status_code == 429:
                    raise AdapterError("CONNECTOR_RATE_LIMITED")
                if reply.status_code >= 400:
                    raise AdapterError("CONNECTOR_HTTP_FAILED")
                yield reply
    except httpx.TimeoutException:
        raise AdapterError("CONNECTOR_TIMEOUT") from None
    except httpx.RequestError:
        raise AdapterError("CONNECTOR_NETWORK_UNREACHABLE") from None


def request(method, url, *, deadline_at, headers=None, content=None, max_bytes=4 * 1024 * 1024):
    with response(method, url, deadline_at=deadline_at, headers=headers, content=content) as reply:
        size, chunks = 0, []
        for chunk in reply.iter_bytes():
            _remaining(deadline_at)
            size += len(chunk)
            if size > max_bytes:
                raise AdapterError("CONNECTOR_RESPONSE_TOO_LARGE")
            chunks.append(chunk)
        return dict(reply.headers), b"".join(chunks)


def json_request(method, url, **kwargs):
    headers, payload = request(method, url, **kwargs)
    try:
        return headers, json.loads(payload)
    except (ValueError, UnicodeError):
        raise AdapterError("CONNECTOR_RESPONSE_INVALID") from None


def download(url, path: Path, *, deadline_at, headers=None, max_bytes):
    import hashlib

    size, digest = 0, hashlib.sha256()
    with response("GET", url, deadline_at=deadline_at, headers=headers) as reply:
        with path.open("xb") as handle:
            for chunk in reply.iter_bytes(chunk_size=65536):
                _remaining(deadline_at)
                size += len(chunk)
                if size > max_bytes:
                    raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
                handle.write(chunk)
                digest.update(chunk)
        return dict(reply.headers), size, digest.hexdigest()
