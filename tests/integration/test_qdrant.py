"""Integration tests for the Qdrant vector store service.

Covers the four core operations from the Qdrant quickstart:
  1. Create a collection
  2. Upsert points
  3. Search (nearest-neighbour query)
  4. Filtered search

Requires a running Qdrant instance on localhost:6333 (e.g. via docker compose).
"""

import uuid

import pytest
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

QDRANT_HOST = "localhost"
QDRANT_PORT = 6333

# Mirrors the quickstart: 4-dim vectors, dot-product distance
VECTOR_SIZE = 4
DISTANCE = Distance.DOT

POINTS = [
    PointStruct(id=1, vector=[0.05, 0.61, 0.76, 0.74], payload={"city": "Berlin"}),
    PointStruct(id=2, vector=[0.19, 0.81, 0.75, 0.11], payload={"city": "London"}),
    PointStruct(id=3, vector=[0.36, 0.55, 0.47, 0.94], payload={"city": "Moscow"}),
    PointStruct(id=4, vector=[0.18, 0.01, 0.85, 0.80], payload={"city": "New York"}),
    PointStruct(id=5, vector=[0.24, 0.18, 0.22, 0.44], payload={"city": "Beijing"}),
    PointStruct(id=6, vector=[0.35, 0.08, 0.11, 0.44], payload={"city": "Mumbai"}),
]

QUERY_VECTOR = [0.2, 0.1, 0.9, 0.7]


@pytest.fixture(scope="module")
def client(qdrant_authenticated_client):
    """Reuse the session-scoped authenticated client from conftest."""
    return qdrant_authenticated_client


@pytest.fixture
def collection_name():
    """Unique collection per test so tests are isolated."""
    return f"test_{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def cleanup(client, collection_name):
    yield
    if client.collection_exists(collection_name):
        client.delete_collection(collection_name)


@pytest.mark.integration
class TestQdrantQuickstart:
    def test_create_collection(self, client, collection_name):
        """Operation 1 — create a collection."""
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=DISTANCE),
        )
        assert client.collection_exists(collection_name)

    def test_upsert_points(self, client, collection_name):
        """Operation 2 — upsert points with payload."""
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=DISTANCE),
        )
        operation_info = client.upsert(
            collection_name=collection_name,
            wait=True,
            points=POINTS,
        )
        assert operation_info.status.name == "COMPLETED"

        count = client.count(collection_name=collection_name)
        assert count.count == len(POINTS)

    def test_search(self, client, collection_name):
        """Operation 3 — nearest-neighbour query."""
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=DISTANCE),
        )
        client.upsert(collection_name=collection_name, wait=True, points=POINTS)

        results = client.query_points(
            collection_name=collection_name,
            query=QUERY_VECTOR,
            limit=3,
        ).points

        assert len(results) == 3
        # scores must be in descending order
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_filtered_search(self, client, collection_name):
        """Operation 4 — nearest-neighbour query with a payload filter."""
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=DISTANCE),
        )
        client.upsert(collection_name=collection_name, wait=True, points=POINTS)

        results = client.query_points(
            collection_name=collection_name,
            query=QUERY_VECTOR,
            query_filter=Filter(
                must=[FieldCondition(key="city", match=MatchValue(value="London"))]
            ),
            limit=3,
        ).points

        assert len(results) == 1
        assert results[0].payload["city"] == "London"
