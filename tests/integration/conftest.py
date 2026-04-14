"""Integration-test configuration.

Patches the module-level qdrant_client singletons so every integration test
connects to the real Qdrant instance with the configured API key rather than
the unauthenticated mock built from the unit-test config.
"""

import os
from unittest.mock import patch

import pytest
from qdrant_client import QdrantClient

QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
QDRANT_API_KEY = os.environ.get("QDRANT__SERVICE__API_KEY", "changeme")


@pytest.fixture(autouse=True, scope="session")
def qdrant_authenticated_client():
    """Session-scoped fixture that:
    1. Builds a QdrantClient with the test API key and https=False.
    2. Patches both the connections singleton and the src.embedding reference
       so all integration tests go through an authenticated client.
    """
    real_client = QdrantClient(
        host=QDRANT_HOST,
        port=QDRANT_PORT,
        api_key=QDRANT_API_KEY,
        https=False,
    )
    with (
        patch("connections.qdrant.qdrant_client", real_client),
        patch("src.embedding.qdrant_client", real_client),
    ):
        yield real_client
