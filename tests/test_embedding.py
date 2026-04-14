"""Unit tests for the embedding module.

Covers:
- EmbeddingVectors initialization: device selection, dimension, new interface attrs (5 tests)
- create_embeddings(): output shape and empty-input handling (2 tests)
- _calculate_dynamic_batch_size(): positive int, upper cap (2 tests)

Total: 9 unit tests
"""

from unittest.mock import MagicMock, patch

import numpy as np

from src.embedding import EmbeddingVectors


class TestEmbeddingVectorsInitialization:
    """Test EmbeddingVectors initialization."""

    @patch("src.embedding.EmbeddingModelLoader")
    def test_initialization_basic(self, mock_loader):
        """Test basic initialization of EmbeddingVectors."""
        mock_loader.load_embedding_model.return_value = MagicMock()
        mock_loader.get_embedding_dimension.return_value = 768

        tokenizer = MagicMock()
        model = MagicMock()

        emb_vec = EmbeddingVectors(
            tokenizer=tokenizer,
            model=model,
            target_collection="test_vs",
            kb_uuid="00000000-0000-0000-0000-000000000001",
        )

        assert emb_vec.tokenizer == tokenizer
        assert emb_vec.model == model
        assert emb_vec.target_collection == "test_vs"
        assert emb_vec.source_collection is None

    @patch("src.embedding.EmbeddingModelLoader")
    def test_initialization_device_selection(self, mock_loader):
        """Test device selection during initialization."""
        mock_loader.load_embedding_model.return_value = MagicMock()
        mock_loader.get_embedding_dimension.return_value = 768

        emb_vec = EmbeddingVectors(
            tokenizer=MagicMock(),
            model=MagicMock(),
            target_collection="test_vs",
            kb_uuid="00000000-0000-0000-0000-000000000001",
        )

        assert emb_vec.device.type in ["cuda", "cpu"]

    @patch("src.embedding.EmbeddingModelLoader")
    def test_initialization_embedding_dimension(self, mock_loader):
        """Test embedding dimension is properly set."""
        expected_dim = 768
        mock_loader.load_embedding_model.return_value = MagicMock()
        mock_loader.get_embedding_dimension.return_value = expected_dim

        emb_vec = EmbeddingVectors(
            tokenizer=MagicMock(),
            model=MagicMock(),
            target_collection="test_vs",
            kb_uuid="00000000-0000-0000-0000-000000000001",
        )

        assert emb_vec.embedding_dimension == expected_dim


class TestEmbeddingVectorsAttributes:
    """Test that interface attributes are stored correctly."""

    @patch("src.embedding.EmbeddingModelLoader")
    def test_source_collection_stored(self, mock_loader):
        mock_loader.load_embedding_model.return_value = MagicMock()
        mock_loader.get_embedding_dimension.return_value = 768

        emb_vec = EmbeddingVectors(
            tokenizer=MagicMock(),
            model=MagicMock(),
            target_collection="my_col",
            kb_uuid="abc-123",
            source_collection="other_col",
        )

        assert emb_vec.source_collection == "other_col"
        assert emb_vec.target_collection == "my_col"
        assert emb_vec.kb_uuid == "abc-123"

    @patch("src.embedding.EmbeddingModelLoader")
    def test_source_collection_defaults_to_none(self, mock_loader):
        mock_loader.load_embedding_model.return_value = MagicMock()
        mock_loader.get_embedding_dimension.return_value = 768

        emb_vec = EmbeddingVectors(
            tokenizer=MagicMock(),
            model=MagicMock(),
            target_collection="my_col",
            kb_uuid="abc-123",
        )

        assert emb_vec.source_collection is None


class TestCreateEmbeddings:
    """Test create_embeddings() output shape and empty-input handling."""

    @patch("src.embedding.EmbeddingModelLoader")
    def test_output_shape_matches_dimension(self, mock_loader):
        fake_model = MagicMock()
        fake_tensor = MagicMock()
        fake_tensor.to.return_value.cpu.return_value.numpy.return_value = np.zeros(
            (2, 768), dtype=np.float32
        )
        fake_model.encode.return_value = fake_tensor
        mock_loader.load_embedding_model.return_value = fake_model
        mock_loader.get_embedding_dimension.return_value = 768

        emb_vec = EmbeddingVectors(
            tokenizer=MagicMock(),
            model=MagicMock(),
            target_collection="test_vs",
            kb_uuid="abc-123",
        )
        result = emb_vec.create_embeddings(
            ["text one", "text two"], use_dynamic_batching=False
        )
        assert result.shape == (2, 768)

    @patch("src.embedding.EmbeddingModelLoader")
    def test_empty_texts_returns_empty_array(self, mock_loader):
        mock_loader.load_embedding_model.return_value = MagicMock()
        mock_loader.get_embedding_dimension.return_value = 768

        emb_vec = EmbeddingVectors(
            tokenizer=MagicMock(),
            model=MagicMock(),
            target_collection="test_vs",
            kb_uuid="abc-123",
        )
        result = emb_vec.create_embeddings([])
        assert result.shape == (0, 768)


class TestDynamicBatchSize:
    """Test _calculate_dynamic_batch_size() returns sensible values."""

    @patch("src.embedding.EmbeddingModelLoader")
    def test_returns_positive_integer(self, mock_loader):
        mock_loader.load_embedding_model.return_value = MagicMock()
        mock_loader.get_embedding_dimension.return_value = 768

        emb_vec = EmbeddingVectors(
            tokenizer=MagicMock(),
            model=MagicMock(),
            target_collection="test_vs",
            kb_uuid="abc-123",
        )
        batch_size = emb_vec._calculate_dynamic_batch_size(["hello"] * 50)
        assert isinstance(batch_size, int)
        assert 1 <= batch_size <= 128

    @patch("src.embedding.EmbeddingModelLoader")
    def test_respects_upper_cap(self, mock_loader):
        mock_loader.load_embedding_model.return_value = MagicMock()
        mock_loader.get_embedding_dimension.return_value = 768

        emb_vec = EmbeddingVectors(
            tokenizer=MagicMock(),
            model=MagicMock(),
            target_collection="test_vs",
            kb_uuid="abc-123",
        )
        # 10-item list → cap is min(128, 10) = 10
        batch_size = emb_vec._calculate_dynamic_batch_size(["x"] * 10)
        assert batch_size <= 10
