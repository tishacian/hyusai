"""Origin-bound, DNS-pinned HTTP transport; never follows redirects or proxies."""

from __future__ import annotations

import httpx

from app.services.connectors.network_policy import (
    ConnectorNetworkError,
    Destination,
    canonical_host,
    resolve_destination,
)


def origin(url: httpx.URL) -> tuple[str, str, int]:
    if url.scheme not in {"http", "https"} or url.username or url.password or url.fragment:
        raise ConnectorNetworkError("CONNECTOR_URL_INVALID")
    return url.scheme, canonical_host(url.host), url.port or (443 if url.scheme == "https" else 80)


def destination_for_url(url: str, *, require_https: bool = False) -> tuple[httpx.URL, Destination]:
    try:
        parsed = httpx.URL(url)
        scheme, host, port = origin(parsed)
    except (httpx.InvalidURL, ValueError):
        raise ConnectorNetworkError("CONNECTOR_URL_INVALID") from None
    if require_https and scheme != "https":
        raise ConnectorNetworkError("CONNECTOR_TLS_REQUIRED", 403)
    return parsed, resolve_destination(host, port)


class PinnedHTTPTransport(httpx.BaseTransport):
    def __init__(self, url: httpx.URL, destination: Destination):
        self._origin = origin(url)
        if (destination.host, destination.port) != self._origin[1:]:
            raise ConnectorNetworkError("CONNECTOR_ORIGIN_DENIED", 403)
        self._destination = destination
        self._inner = httpx.HTTPTransport(verify=True, trust_env=False, retries=0)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if origin(request.url) != self._origin:
            raise ConnectorNetworkError("CONNECTOR_ORIGIN_DENIED", 403)
        # HTTP Host and TLS SNI/certificate verification retain the declared
        # hostname, while TCP sees only the address that passed the policy.
        headers = request.headers.copy()
        headers["Host"] = request.url.netloc.decode("ascii")
        extensions = {**request.extensions, "sni_hostname": self._destination.host}
        pinned = httpx.Request(
            request.method,
            request.url.copy_with(host=self._destination.address),
            headers=headers,
            stream=request.stream,
            extensions=extensions,
        )
        return self._inner.handle_request(pinned)

    def close(self) -> None:
        self._inner.close()


def pinned_client(url: httpx.URL, destination: Destination, *, timeout: float) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        transport=PinnedHTTPTransport(url, destination),
        follow_redirects=False,
        trust_env=False,
    )
