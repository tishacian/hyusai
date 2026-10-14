"""Pinned transport for Python SQL drivers, scoped to one isolated child.

Unlike a global application DNS monkeypatch, this context exists only while one
runner subprocess owns a single connector. Routing/failover to any other origin
is refused before authentication, including SQL Server routing tokens.
"""

from __future__ import annotations

import socket
from contextlib import contextmanager

from app.services.connectors.network_policy import (
    ConnectorNetworkError,
    canonical_host,
    resolve_destination,
)


@contextmanager
def pinned_sql_destination(host: str, port: int):
    destination = resolve_destination(host, port)
    original = socket.getaddrinfo

    def pinned(name, requested_port, family=0, type=0, proto=0, flags=0):
        if isinstance(name, bytes):
            name = name.decode("ascii")
        if canonical_host(name) != destination.host or int(requested_port) != port:
            raise ConnectorNetworkError("CONNECTOR_REDIRECT_DENIED", 403)
        # Numeric host prevents a second hostname lookup/rebinding. Drivers keep
        # the configured name for SNI and certificate identity verification.
        return original(
            destination.address, port, family, type, proto, flags | socket.AI_NUMERICHOST
        )

    socket.getaddrinfo = pinned
    try:
        yield destination
    finally:
        socket.getaddrinfo = original
