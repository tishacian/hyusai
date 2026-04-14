"""Integration tests for EmbeddingVectors.save_index() against a real Qdrant instance.

Tests the new interface contract:
  target=<new_name>, source=None          → create brand-new collection
  target=<new_name>, source=<existing>    → create new collection seeded from existing
  target=<existing>, source=None          → append docs to existing collection
  target=<existing>, source=<different>   → ValueError (guard)

Requires a running Qdrant instance on localhost:6333.
Run with: pytest -m integration tests/integration/test_embedding.py
"""

import uuid
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

DIM = 8  # tiny fixed dimension — keeps tests fast
TEXTS = ["chunk alpha", "chunk beta", "chunk gamma"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client(qdrant_authenticated_client):
    """Reuse the session-scoped authenticated client from conftest."""
    return qdrant_authenticated_client


@pytest.fixture
def col():
    """Unique target collection name per test."""
    return f"test_target_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def src_col(client):
    """Pre-seeded source collection available for copy tests."""
    name = f"test_source_{uuid.uuid4().hex[:8]}"
    yield name
    if client.collection_exists(name):
        client.delete_collection(name)


@pytest.fixture(autouse=True)
def cleanup(client, col):
    yield
    if client.collection_exists(col):
        client.delete_collection(col)


def _build_ev(target_collection, kb_uuid, source_collection=None):
    """
    Construct an EmbeddingVectors instance with:
    - mocked EmbeddingModelLoader (no real model download)
    - real QdrantClient with API key (applied via conftest session fixture)
    - mocked fs (BM25 pickle write is a no-op)

    Returns (ev, mock_fs) so callers can assert on fs calls if needed.
    """
    mock_sentence_model = MagicMock()
    mock_sentence_model.encode.return_value = np.random.rand(len(TEXTS), DIM).astype(
        np.float32
    )

    mock_fs = MagicMock()
    mock_fs.joinpath.side_effect = lambda *parts: "/".join(str(p) for p in parts)
    mock_fs.write_to_file.return_value = None

    with (
        patch("src.embedding.EmbeddingModelLoader") as MockLoader,
        patch("src.embedding.fs", mock_fs),
    ):
        MockLoader.load_embedding_model.return_value = mock_sentence_model
        MockLoader.get_embedding_dimension.return_value = DIM

        from src.embedding import EmbeddingVectors

        ev = EmbeddingVectors(
            MagicMock(),  # tokenizer — unique object → cache miss each call
            MagicMock(),  # model
            target_collection,
            kb_uuid,
            source_collection=source_collection,
        )
        ev.embedding_dimension = DIM
        ev.last_embeddings_to_save = np.random.rand(len(TEXTS), DIM).astype(np.float32)

    return ev, mock_fs


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSaveIndexContract:
    def test_create_new_collection(self, client, col):
        """target=<new>, source=None → collection is created with correct point count."""
        kb = str(uuid.uuid4())
        ev, mock_fs = _build_ev(col, kb)

        with patch("src.embedding.fs", mock_fs):
            ev.save_index(TEXTS)

        assert client.collection_exists(col)
        assert client.count(col).count == len(TEXTS)

    def test_new_collection_payload_has_bm25_path(self, client, col):
        """Every point in a new collection must carry a bm25_path payload key."""
        kb = str(uuid.uuid4())
        ev, mock_fs = _build_ev(col, kb)

        with patch("src.embedding.fs", mock_fs):
            ev.save_index(TEXTS)

        results, _ = client.scroll(col, with_payload=True, limit=100)
        assert all("bm25_path" in p.payload for p in results)
        assert all("text" in p.payload for p in results)

    def test_append_to_existing_collection(self, client, col):
        """target=<existing>, source=None → new points appended, total grows."""
        kb = str(uuid.uuid4())
        ev1, mock_fs1 = _build_ev(col, kb)
        with patch("src.embedding.fs", mock_fs1):
            ev1.save_index(TEXTS)

        initial_count = client.count(col).count
        assert initial_count == len(TEXTS)

        extra_texts = ["chunk delta", "chunk epsilon"]
        ev2, mock_fs2 = _build_ev(col, kb)
        ev2.last_embeddings_to_save = np.random.rand(len(extra_texts), DIM).astype(
            np.float32
        )
        with patch("src.embedding.fs", mock_fs2):
            ev2.save_index(extra_texts)

        assert client.count(col).count == initial_count + len(extra_texts)

    def test_append_reuses_existing_kb_uuid(self, client, col):
        """When appending, kb_uuid is taken from the collection payload, not the caller."""
        original_kb = str(uuid.uuid4())
        ev1, mock_fs1 = _build_ev(col, original_kb)
        with patch("src.embedding.fs", mock_fs1):
            ev1.save_index(TEXTS)

        # Build a second instance with a DIFFERENT kb_uuid; save_index should override
        # self.kb_uuid to the existing one found in the payload.
        different_kb = str(uuid.uuid4())
        ev2, mock_fs2 = _build_ev(col, different_kb)
        with patch("src.embedding.fs", mock_fs2):
            ev2.save_index(["chunk new"])

        # The bm25_path for new points should use the ORIGINAL kb_uuid
        results, _ = client.scroll(col, with_payload=True, limit=100)
        for p in results:
            assert original_kb in p.payload["bm25_path"], (
                f"Expected original kb_uuid {original_kb} in bm25_path, "
                f"got {p.payload['bm25_path']}"
            )

    def test_guard_rejects_merge_into_existing(self, client, col, src_col):
        """target=<existing>, source=<different> → ValueError before any write."""
        # Create target first
        kb = str(uuid.uuid4())
        ev0, mock_fs0 = _build_ev(col, kb)
        with patch("src.embedding.fs", mock_fs0):
            ev0.save_index(TEXTS)

        initial_count = client.count(col).count

        # Now try to "merge" src_col into the already-existing col
        ev_bad, mock_fs_bad = _build_ev(col, kb, source_collection=src_col)
        with patch("src.embedding.fs", mock_fs_bad):
            with pytest.raises(ValueError, match="Cannot merge"):
                ev_bad.save_index(["should not be written"])

        # Collection must be untouched
        assert client.count(col).count == initial_count

    def test_source_copy_creates_seeded_collection(self, client, col, src_col):
        """target=<new>, source=<existing> → new collection has source + new points."""
        src_kb = str(uuid.uuid4())

        # Seed source collection directly via client
        from qdrant_client.models import Distance, PointStruct, VectorParams

        client.create_collection(
            src_col,
            vectors_config=VectorParams(size=DIM, distance=Distance.COSINE),
        )
        src_points = [
            PointStruct(
                id=i,
                vector=np.random.rand(DIM).tolist(),
                payload={
                    "text": f"src text {i}",
                    "bm25_path": f"knowledge-bases/{src_kb}/retrieval/bm25_retriever.pkl",
                },
            )
            for i in range(3)
        ]
        client.upsert(src_col, wait=True, points=src_points)

        # Build EmbeddingVectors with source_collection=src_col
        new_kb = str(uuid.uuid4())
        ev, mock_fs = _build_ev(col, new_kb, source_collection=src_col)
        with patch("src.embedding.fs", mock_fs):
            ev.save_index(TEXTS)

        total = client.count(col).count
        assert total == len(src_points) + len(TEXTS), (
            f"Expected {len(src_points) + len(TEXTS)} points, got {total}"
        )

    def test_bm25_covers_source_and_new_texts_on_seed(self, client, col, src_col):
        """BM25 retriever built after seeding must cover source texts + new texts."""
        import pickle

        from qdrant_client.models import Distance, PointStruct, VectorParams

        src_kb = str(uuid.uuid4())
        src_texts = ["source alpha", "source beta", "source gamma"]
        new_texts = ["new doc one", "new doc two"]

        client.create_collection(
            src_col, vectors_config=VectorParams(size=DIM, distance=Distance.COSINE)
        )
        client.upsert(
            src_col,
            wait=True,
            points=[
                PointStruct(
                    id=i,
                    vector=np.random.rand(DIM).tolist(),
                    payload={
                        "text": src_texts[i],
                        "bm25_path": f"knowledge-bases/{src_kb}/retrieval/bm25_retriever.pkl",
                    },
                )
                for i in range(len(src_texts))
            ],
        )

        new_kb = str(uuid.uuid4())
        ev, mock_fs = _build_ev(col, new_kb, source_collection=src_col)
        ev.last_embeddings_to_save = np.random.rand(len(new_texts), DIM).astype(
            np.float32
        )
        with patch("src.embedding.fs", mock_fs):
            ev.save_index(new_texts)

        _, bm25_buf = mock_fs.write_to_file.call_args[0]
        bm25_buf.seek(0)
        bm25_retriever = pickle.load(bm25_buf)

        assert set(bm25_retriever.documents) == set(src_texts + new_texts), (
            f"BM25 corpus mismatch: {bm25_retriever.documents}"
        )

    def test_bm25_covers_existing_and_new_texts_on_append(self, client, col):
        """BM25 retriever rebuilt on append must cover all previous + new texts."""
        import pickle

        kb = str(uuid.uuid4())
        initial_texts = list(TEXTS)
        extra_texts = ["appended doc one", "appended doc two"]

        ev1, mock_fs1 = _build_ev(col, kb)
        with patch("src.embedding.fs", mock_fs1):
            ev1.save_index(initial_texts)

        ev2, mock_fs2 = _build_ev(col, kb)
        ev2.last_embeddings_to_save = np.random.rand(len(extra_texts), DIM).astype(
            np.float32
        )
        with patch("src.embedding.fs", mock_fs2):
            ev2.save_index(extra_texts)

        _, bm25_buf = mock_fs2.write_to_file.call_args[0]
        bm25_buf.seek(0)
        bm25_retriever = pickle.load(bm25_buf)

        assert set(bm25_retriever.documents) == set(initial_texts + extra_texts), (
            f"BM25 corpus mismatch: {bm25_retriever.documents}"
        )
