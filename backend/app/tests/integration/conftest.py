"""Shared gates for the integration tests: they need a live service.

A test that needs Qdrant asks for ``require_qdrant``. Without a reachable
Qdrant it is skipped with the address it tried, never failed: the unit suite
must stay readable on a machine without the vector store, and the tests still
run wherever Qdrant is up (``QDRANT_INTEGRATION=0`` forces the skip).
"""

from __future__ import annotations

import os
import socket

import pytest


def qdrant_address() -> tuple[str, int]:
    """The address the services use: settings, which read QDRANT_HOST / QDRANT_PORT."""

    from app.core.config import settings

    return (
        os.getenv("QDRANT_HOST") or settings.qdrant_host,
        int(os.getenv("QDRANT_PORT") or settings.qdrant_port),
    )


def qdrant_reachable() -> bool:
    if os.getenv("QDRANT_INTEGRATION") == "0":
        return False
    try:
        with socket.create_connection(qdrant_address(), timeout=0.75):
            return True
    except OSError:
        return False


@pytest.fixture
def require_qdrant():
    if not qdrant_reachable():
        host, port = qdrant_address()
        pytest.skip(
            f"Qdrant not reachable at {host}:{port} "
            "(start docker compose qdrant or set QDRANT_HOST / QDRANT_PORT)"
        )
