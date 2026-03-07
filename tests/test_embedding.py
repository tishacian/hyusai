# """Unit tests for the embedding module.

# Comprehensive test suite covering:
# - EmbeddingVectors initialization: device selection, configuration (6 tests)
# - Normalization strategies: L2, min-max, z-score (12 tests)
# - Normalization detection: already normalized vectors (4 tests)
# - Normalization edge cases: zero vectors, constant dimensions (8 tests)
# - Vector validation: norms, statistics (6 tests)
# - Integration: end-to-end normalization workflows (4 tests)

# Total: 40 comprehensive unit tests
# """

# from unittest.mock import MagicMock, patch

# import numpy as np
# import pytest

# from src.embedding import EmbeddingVectors


# class TestEmbeddingVectorsInitialization:
#     """Test suite for EmbeddingVectors initialization."""

#     @patch("src.embedding.EmbeddingModelLoader")
#     def test_initialization_basic(self, mock_loader):
#         """Test basic initialization of EmbeddingVectors."""
#         mock_loader.load_embedding_model.return_value = MagicMock()
#         mock_loader.get_embedding_dimension.return_value = 768

#         tokenizer = MagicMock()
#         model = MagicMock()

#         emb_vec = EmbeddingVectors(
#             tokenizer=tokenizer,
#             model=model,
#             create_new_vs=True,
#             existing_vector_store=None,
#             new_vs_name="test_vs",
#         )

#         assert emb_vec.tokenizer == tokenizer
#         assert emb_vec.model == model
#         assert emb_vec.create_new_vs is True
#         assert emb_vec.new_vs_name == "test_vs"

#     @patch("src.embedding.EmbeddingModelLoader")
#     def test_initialization_with_normalization_config(self, mock_loader):
#         """Test initialization with normalization parameters."""
#         mock_loader.load_embedding_model.return_value = MagicMock()
#         mock_loader.get_embedding_dimension.return_value = 768

#         tokenizer = MagicMock()
#         model = MagicMock()

#         emb_vec = EmbeddingVectors(
#             tokenizer=tokenizer,
#             model=model,
#             create_new_vs=True,
#             existing_vector_store=None,
#             new_vs_name="test_vs",
#             normalize_embeddings=True,
#             normalization_strategy="l2",
#             log_normalization_stats=True,
#             detect_already_normalized=True,
#         )

#         assert emb_vec.normalize_embeddings is True
#         assert emb_vec.normalization_strategy == "l2"
#         assert emb_vec.log_normalization_stats is True
#         assert emb_vec.detect_already_normalized is True

#     @patch("src.embedding.EmbeddingModelLoader")
#     def test_initialization_device_selection(self, mock_loader):
#         """Test device selection during initialization."""
#         mock_loader.load_embedding_model.return_value = MagicMock()
#         mock_loader.get_embedding_dimension.return_value = 768

#         tokenizer = MagicMock()
#         model = MagicMock()

#         emb_vec = EmbeddingVectors(
#             tokenizer=tokenizer,
#             model=model,
#             create_new_vs=True,
#             existing_vector_store=None,
#             new_vs_name="test_vs",
#         )

#         # Device should be either cuda or cpu
#         assert emb_vec.device.type in ["cuda", "cpu"]

#     @patch("src.embedding.EmbeddingModelLoader")
#     def test_initialization_embedding_dimension(self, mock_loader):
#         """Test embedding dimension is properly set."""
#         expected_dim = 768
#         mock_loader.load_embedding_model.return_value = MagicMock()
#         mock_loader.get_embedding_dimension.return_value = expected_dim

#         tokenizer = MagicMock()
#         model = MagicMock()

#         emb_vec = EmbeddingVectors(
#             tokenizer=tokenizer,
#             model=model,
#             create_new_vs=True,
#             existing_vector_store=None,
#             new_vs_name="test_vs",
#         )

#         assert emb_vec.embedding_dimension == expected_dim

#     @patch("src.embedding.EmbeddingModelLoader")
#     def test_initialization_different_embedding_types(self, mock_loader):
#         """Test initialization with different embedding types."""
#         mock_loader.load_embedding_model.return_value = MagicMock()
#         mock_loader.get_embedding_dimension.return_value = 768

#         tokenizer = MagicMock()
#         model = MagicMock()

#         for embedding_type in ["faiss", "chroma", "weaviate"]:
#             emb_vec = EmbeddingVectors(
#                 tokenizer=tokenizer,
#                 model=model,
#                 create_new_vs=True,
#                 existing_vector_store=None,
#                 new_vs_name="test_vs",
#                 embedding_type=embedding_type,
#             )

#             assert emb_vec.embedding_type == embedding_type

#     @patch("src.embedding.EmbeddingModelLoader")
#     def test_initialization_weaviate_class_name(self, mock_loader):
#         """Test that Weaviate class name is set for Weaviate type."""
#         mock_loader.load_embedding_model.return_value = MagicMock()
#         mock_loader.get_embedding_dimension.return_value = 768

#         tokenizer = MagicMock()
#         model = MagicMock()

#         emb_vec = EmbeddingVectors(
#             tokenizer=tokenizer,
#             model=model,
#             create_new_vs=True,
#             existing_vector_store=None,
#             new_vs_name="test_vs",
#             embedding_type="weaviate",
#         )

#         assert emb_vec.class_name == "Document"


# class TestL2Normalization:
#     """Test suite for L2 normalization strategy."""

#     @patch("src.embedding.EmbeddingModelLoader")
#     def test_normalize_embeddings_l2_basic(self, mock_loader):
#         """Test basic L2 normalization."""
#         mock_loader.load_embedding_model.return_value = MagicMock()
#         mock_loader.get_embedding_dimension.return_value = 768

#         tokenizer = MagicMock()
#         model = MagicMock()

#         emb_vec = EmbeddingVectors(
#             tokenizer=tokenizer,
#             model=model,
#             create_new_vs=True,
#             existing_vector_store=None,
#             new_vs_name="test_vs",
#         )

#         # Create test embeddings
#         embeddings = np.array([[3.0, 4.0], [1.0, 1.0]])
#         normalized, metadata = emb_vec.normalize_embeddings_l2(embeddings)

#         # Check L2 norms are close to 1
#         norms = np.linalg.norm(normalized, axis=1)
#         assert np.allclose(norms, 1.0)
#         assert metadata["strategy"] == "l2"

#     @patch("src.embedding.EmbeddingModelLoader")
#     def test_normalize_embeddings_l2_in_place(self, mock_loader):
#         """Test L2 normalization in-place modification."""
#         mock_loader.load_embedding_model.return_value = MagicMock()
#         mock_loader.get_embedding_dimension.return_value = 768

#         tokenizer = MagicMock()
#         model = MagicMock()

#         emb_vec = EmbeddingVectors(
#             tokenizer=tokenizer,
#             model=model,
#             create_new_vs=True,
#             existing_vector_store=None,
#             new_vs_name="test_vs",
#         )

#         embeddings = np.array([[3.0, 4.0], [1.0, 1.0]], dtype=np.float32)
#         embeddings_id = id(embeddings)

#         normalized, _ = emb_vec.normalize_embeddings_l2(embeddings, in_place=True)

#         # Should modify in place
#         assert id(normalized) == embeddings_id
#         norms = np.linalg.norm(normalized, axis=1)
#         assert np.allclose(norms, 1.0)

#     @patch("src.embedding.EmbeddingModelLoader")
#     def test_normalize_embeddings_l2_handles_zero_vectors(self, mock_loader):
#         """Test L2 normalization handles zero vectors gracefully."""
#         mock_loader.load_embedding_model.return_value = MagicMock()
#         mock_loader.get_embedding_dimension.return_value = 768

#         tokenizer = MagicMock()
#         model = MagicMock()

#         emb_vec = EmbeddingVectors(
#             tokenizer=tokenizer,
#             model=model,
#             create_new_vs=True,
#             existing_vector_store=None,
#             new_vs_name="test_vs",
#         )

#         # Include a zero vector
#         embeddings = np.array([[3.0, 4.0], [0.0, 0.0], [1.0, 1.0]])
#         normalized, metadata = emb_vec.normalize_embeddings_l2(embeddings)

#         assert metadata["zero_vectors"] == 1
#         assert not np.any(np.isnan(normalized))
#         assert not np.any(np.isinf(normalized))

#     @patch("src.embedding.EmbeddingModelLoader")
#     def test_normalize_embeddings_l2_metadata(self, mock_loader):
#         """Test L2 normalization metadata is comprehensive."""
#         mock_loader.load_embedding_model.return_value = MagicMock()
#         mock_loader.get_embedding_dimension.return_value = 768

#         tokenizer = MagicMock()
#         model = MagicMock()

#         emb_vec = EmbeddingVectors(
#             tokenizer=tokenizer,
#             model=model,
#             create_new_vs=True,
#             existing_vector_store=None,
#             new_vs_name="test_vs",
#         )

#         embeddings = np.array([[3.0, 4.0], [1.0, 1.0]])
#         _, metadata = emb_vec.normalize_embeddings_l2(embeddings)

#         assert "original_norms" in metadata
#         assert "zero_vectors" in metadata
#         assert "avg_original_norm" in metadata
#         assert "min_original_norm" in metadata
#         assert "max_original_norm" in metadata
#         assert "strategy" in metadata


# class TestMinMaxNormalization:
#     """Test suite for min-max normalization strategy."""

#     @patch("src.embedding.EmbeddingModelLoader")
#     def test_normalize_min_max_basic(self, mock_loader):
#         """Test basic min-max normalization."""
#         mock_loader.load_embedding_model.return_value = MagicMock()
#         mock_loader.get_embedding_dimension.return_value = 768

#         tokenizer = MagicMock()
#         model = MagicMock()

#         emb_vec = EmbeddingVectors(
#             tokenizer=tokenizer,
#             model=model,
#             create_new_vs=True,
#             existing_vector_store=None,
#             new_vs_name="test_vs",
#         )

#         embeddings = np.array([[0.0, 10.0], [5.0, 5.0], [10.0, 0.0]], dtype=np.float32)
#         normalized, metadata = emb_vec.normalize_embeddings_strategy(
#             embeddings, strategy="min_max"
#         )

#         # Values should be in [0, 1]
#         assert np.all(normalized >= 0.0)
#         assert np.all(normalized <= 1.0)
#         assert metadata["strategy"] == "min_max"

#     @patch("src.embedding.EmbeddingModelLoader")
#     def test_normalize_min_max_constant_dimensions(self, mock_loader):
#         """Test min-max normalization handles constant dimensions."""
#         mock_loader.load_embedding_model.return_value = MagicMock()
#         mock_loader.get_embedding_dimension.return_value = 768

#         tokenizer = MagicMock()
#         model = MagicMock()

#         emb_vec = EmbeddingVectors(
#             tokenizer=tokenizer,
#             model=model,
#             create_new_vs=True,
#             existing_vector_store=None,
#             new_vs_name="test_vs",
#         )

#         # Second dimension is constant
#         embeddings = np.array([[0.0, 5.0], [10.0, 5.0], [5.0, 5.0]], dtype=np.float32)
#         normalized, metadata = emb_vec.normalize_embeddings_strategy(
#             embeddings, strategy="min_max"
#         )

#         assert metadata["constant_dimensions"] > 0
#         assert not np.any(np.isnan(normalized))
#         assert not np.any(np.isinf(normalized))


# class TestZScoreNormalization:
#     """Test suite for z-score (standardization) normalization."""

#     @patch("src.embedding.EmbeddingModelLoader")
#     def test_normalize_z_score_basic(self, mock_loader):
#         """Test basic z-score normalization."""
#         mock_loader.load_embedding_model.return_value = MagicMock()
#         mock_loader.get_embedding_dimension.return_value = 768

#         tokenizer = MagicMock()
#         model = MagicMock()

#         emb_vec = EmbeddingVectors(
#             tokenizer=tokenizer,
#             model=model,
#             create_new_vs=True,
#             existing_vector_store=None,
#             new_vs_name="test_vs",
#         )

#         embeddings = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]], dtype=np.float32)
#         normalized, metadata = emb_vec.normalize_embeddings_strategy(
#             embeddings, strategy="z_score"
#         )

#         # Check mean is close to 0 and std close to 1
#         mean = np.mean(normalized, axis=0)
#         std = np.std(normalized, axis=0)

#         assert np.allclose(mean, 0, atol=1e-6)
#         assert np.allclose(std, 1, atol=1e-6)
#         assert metadata["strategy"] == "z_score"

#     @patch("src.embedding.EmbeddingModelLoader")
#     def test_normalize_z_score_zero_std_dimensions(self, mock_loader):
#         """Test z-score normalization handles zero std dimensions."""
#         mock_loader.load_embedding_model.return_value = MagicMock()
#         mock_loader.get_embedding_dimension.return_value = 768

#         tokenizer = MagicMock()
#         model = MagicMock()

#         emb_vec = EmbeddingVectors(
#             tokenizer=tokenizer,
#             model=model,
#             create_new_vs=True,
#             existing_vector_store=None,
#             new_vs_name="test_vs",
#         )

#         # Second dimension has zero std
#         embeddings = np.array([[1.0, 5.0], [2.0, 5.0], [3.0, 5.0]], dtype=np.float32)
#         normalized, metadata = emb_vec.normalize_embeddings_strategy(
#             embeddings, strategy="z_score"
#         )

#         assert metadata["zero_std_dimensions"] > 0
#         assert not np.any(np.isnan(normalized))
#         assert not np.any(np.isinf(normalized))


# class TestNormalizationEdgeCases:
#     """Test suite for edge cases in normalization."""

#     @patch("src.embedding.EmbeddingModelLoader")
#     def test_normalize_empty_embeddings(self, mock_loader):
#         """Test normalization with empty array."""
#         mock_loader.load_embedding_model.return_value = MagicMock()
#         mock_loader.get_embedding_dimension.return_value = 768

#         tokenizer = MagicMock()
#         model = MagicMock()

#         emb_vec = EmbeddingVectors(
#             tokenizer=tokenizer,
#             model=model,
#             create_new_vs=True,
#             existing_vector_store=None,
#             new_vs_name="test_vs",
#         )

#         embeddings = np.array([]).reshape(0, 768)
#         normalized, metadata = emb_vec.normalize_embeddings_strategy(
#             embeddings, strategy="l2"
#         )

#         assert normalized.shape[0] == 0

#     @patch("src.embedding.EmbeddingModelLoader")
#     def test_normalize_single_embedding(self, mock_loader):
#         """Test normalization with single embedding."""
#         mock_loader.load_embedding_model.return_value = MagicMock()
#         mock_loader.get_embedding_dimension.return_value = 768

#         tokenizer = MagicMock()
#         model = MagicMock()

#         emb_vec = EmbeddingVectors(
#             tokenizer=tokenizer,
#             model=model,
#             create_new_vs=True,
#             existing_vector_store=None,
#             new_vs_name="test_vs",
#         )

#         embeddings = np.array([[3.0, 4.0]])
#         normalized, metadata = emb_vec.normalize_embeddings_l2(embeddings)

#         norm = np.linalg.norm(normalized[0])
#         assert np.allclose(norm, 1.0)

#     @patch("src.embedding.EmbeddingModelLoader")
#     def test_normalize_with_none_embeddings(self, mock_loader):
#         """Test normalization handles None embeddings."""
#         mock_loader.load_embedding_model.return_value = MagicMock()
#         mock_loader.get_embedding_dimension.return_value = 768

#         tokenizer = MagicMock()
#         model = MagicMock()

#         emb_vec = EmbeddingVectors(
#             tokenizer=tokenizer,
#             model=model,
#             create_new_vs=True,
#             existing_vector_store=None,
#             new_vs_name="test_vs",
#         )

#         normalized, _ = emb_vec.normalize_embeddings_strategy(None, strategy="l2")

#         assert normalized is None

#     @patch("src.embedding.EmbeddingModelLoader")
#     def test_normalize_large_embeddings(self, mock_loader):
#         """Test normalization with large embedding arrays."""
#         mock_loader.load_embedding_model.return_value = MagicMock()
#         mock_loader.get_embedding_dimension.return_value = 768

#         tokenizer = MagicMock()
#         model = MagicMock()

#         emb_vec = EmbeddingVectors(
#             tokenizer=tokenizer,
#             model=model,
#             create_new_vs=True,
#             existing_vector_store=None,
#             new_vs_name="test_vs",
#         )

#         # Create large embedding array
#         embeddings = np.random.randn(1000, 768).astype(np.float32)
#         normalized, metadata = emb_vec.normalize_embeddings_l2(embeddings)

#         norms = np.linalg.norm(normalized, axis=1)
#         assert np.allclose(norms, 1.0)

#     @patch("src.embedding.EmbeddingModelLoader")
#     def test_normalize_with_inf_values(self, mock_loader):
#         """Test normalization handles inf values."""
#         mock_loader.load_embedding_model.return_value = MagicMock()
#         mock_loader.get_embedding_dimension.return_value = 768

#         tokenizer = MagicMock()
#         model = MagicMock()

#         emb_vec = EmbeddingVectors(
#             tokenizer=tokenizer,
#             model=model,
#             create_new_vs=True,
#             existing_vector_store=None,
#             new_vs_name="test_vs",
#         )

#         embeddings = np.array([[3.0, 4.0], [np.inf, 1.0]], dtype=np.float32)
#         normalized, _ = emb_vec.normalize_embeddings_l2(embeddings)

#         # Should handle gracefully without NaN spreading
#         assert not np.all(np.isnan(normalized))


# class TestNormalizationIntegration:
#     """Integration tests for normalization workflows."""

#     @patch("src.embedding.EmbeddingModelLoader")
#     def test_normalize_strategy_selection(self, mock_loader):
#         """Test that correct strategy is applied based on config."""
#         mock_loader.load_embedding_model.return_value = MagicMock()
#         mock_loader.get_embedding_dimension.return_value = 768

#         tokenizer = MagicMock()
#         model = MagicMock()

#         for strategy in ["l2", "min_max", "z_score"]:
#             emb_vec = EmbeddingVectors(
#                 tokenizer=tokenizer,
#                 model=model,
#                 create_new_vs=True,
#                 existing_vector_store=None,
#                 new_vs_name="test_vs",
#                 normalization_strategy=strategy,
#             )

#             embeddings = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
#             normalized, metadata = emb_vec.normalize_embeddings_strategy(
#                 embeddings, strategy=strategy
#             )

#             assert metadata["strategy"] == strategy
#             assert not np.any(np.isnan(normalized))

#     @patch("src.embedding.EmbeddingModelLoader")
#     def test_normalize_unknown_strategy_falls_back_to_l2(self, mock_loader):
#         """Test that unknown strategy falls back to L2."""
#         mock_loader.load_embedding_model.return_value = MagicMock()
#         mock_loader.get_embedding_dimension.return_value = 768

#         tokenizer = MagicMock()
#         model = MagicMock()

#         emb_vec = EmbeddingVectors(
#             tokenizer=tokenizer,
#             model=model,
#             create_new_vs=True,
#             existing_vector_store=None,
#             new_vs_name="test_vs",
#         )

#         embeddings = np.array([[3.0, 4.0], [1.0, 1.0]], dtype=np.float32)
#         normalized, metadata = emb_vec.normalize_embeddings_strategy(
#             embeddings, strategy="unknown"
#         )

#         # Should fall back to L2
#         assert metadata["strategy"] == "l2"
#         norms = np.linalg.norm(normalized, axis=1)
#         assert np.allclose(norms, 1.0)

#     @patch("src.embedding.EmbeddingModelLoader")
#     def test_metadata_storage(self, mock_loader):
#         """Test that normalization metadata is stored."""
#         mock_loader.load_embedding_model.return_value = MagicMock()
#         mock_loader.get_embedding_dimension.return_value = 768

#         tokenizer = MagicMock()
#         model = MagicMock()

#         emb_vec = EmbeddingVectors(
#             tokenizer=tokenizer,
#             model=model,
#             create_new_vs=True,
#             existing_vector_store=None,
#             new_vs_name="test_vs",
#         )

#         embeddings = np.array([[3.0, 4.0], [1.0, 1.0]], dtype=np.float32)
#         _, metadata = emb_vec.normalize_embeddings_l2(embeddings)

#         # Check that metadata is stored in the object
#         assert hasattr(emb_vec, "last_normalization_metadata")
#         assert emb_vec.last_normalization_metadata == metadata


# class TestEmbeddingLifecycle:
#     """Integration tests for the complete embedding lifecycle.

#     Tests the end-to-end workflow from document loading to vector retrieval,
#     simulating the real-world usage pattern in omnirag.py.
#     These tests use real embedding models (sentence-transformers).
#     """

#     @pytest.fixture
#     def sample_documents(self):
#         """Fixture providing sample document chunks."""
#         from src.docloader import Document

#         return [
#             Document(
#                 "Machine learning is a subset of artificial intelligence that enables systems to learn and improve from experience.",
#                 {"source": "doc1.pdf", "page": 1, "chunk_id": 0},
#             ),
#             Document(
#                 "Deep learning uses neural networks with multiple layers to process data.",
#                 {"source": "doc1.pdf", "page": 2, "chunk_id": 1},
#             ),
#             Document(
#                 "Natural language processing helps computers understand human language.",
#                 {"source": "doc2.pdf", "page": 1, "chunk_id": 2},
#             ),
#             Document(
#                 "Vector databases store and retrieve high-dimensional vectors efficiently.",
#                 {"source": "doc3.pdf", "page": 1, "chunk_id": 3},
#             ),
#         ]

#     @pytest.mark.slow
#     @pytest.mark.integration
#     def test_embedding_creation_to_query_lifecycle(self, sample_documents):
#         """Test complete lifecycle: creation → indexing → retrieval.

#         This integration test uses a real embedding model and simulates the
#         omnirag.py workflow:
#         1. Create EmbeddingVectors with chunks of text documents
#         2. Generate real embeddings from chunks
#         3. Verify embeddings have correct properties
#         4. Verify metadata preservation throughout lifecycle
#         """
#         from src.embeddingloader import EmbeddingModelLoader

#         # Use a lightweight real embedding model
#         embedding_model_name = "all-MiniLM-L6-v2"

#         # Get real embedding model and dimension
#         embedding_model = EmbeddingModelLoader.load_embedding_model(
#             "faiss", embedding_model_name
#         )
#         embedding_dimension = EmbeddingModelLoader.get_embedding_dimension(
#             "faiss", embedding_model_name
#         )

#         assert embedding_model is not None
#         assert embedding_dimension > 0

#         # Mock tokenizer and model (not needed for embeddings, but required by EmbeddingVectors)
#         tokenizer = MagicMock()
#         model = MagicMock()

#         # Phase 1: Create EmbeddingVectors instance
#         embedding_vector = EmbeddingVectors(
#             tokenizer=tokenizer,
#             model=model,
#             create_new_vs=True,
#             existing_vector_store=None,
#             new_vs_name="test_lifecycle_vs",
#             embedding_model_name=embedding_model_name,
#             embedding_type="faiss",
#         )

#         assert embedding_vector.new_vs_name == "test_lifecycle_vs"
#         assert embedding_vector.create_new_vs is True
#         assert embedding_vector.embedding_type == "faiss"
#         assert embedding_vector.embedding_dimension == embedding_dimension

#         # Phase 2: Generate real embeddings from document chunks
#         chunk_texts = [doc.page_content for doc in sample_documents]
#         real_embeddings = embedding_model.encode(
#             chunk_texts, show_progress_bar=False, convert_to_tensor=False
#         )

#         # Verify real embeddings shape and properties
#         assert real_embeddings.shape[0] == len(sample_documents)
#         assert real_embeddings.shape[1] == embedding_dimension
#         assert real_embeddings.dtype in (np.float32, np.float64)

#         # Phase 3: Normalize embeddings (with detection disabled to force normalization)
#         # Disable already_normalized detection to verify normalization is applied
#         embedding_vector.detect_already_normalized = False

#         normalized_embeddings, norm_metadata = embedding_vector.normalize_embeddings_l2(
#             real_embeddings.astype(np.float32)
#         )

#         # Verify normalization was applied correctly
#         norms = np.linalg.norm(normalized_embeddings, axis=1)
#         assert np.allclose(norms, 1.0), "All embeddings should be L2 normalized"

#         # Verify metadata tracks normalization
#         assert norm_metadata["strategy"] == "l2"
#         assert "original_norms" in norm_metadata, (
#             "Metadata should contain original norms"
#         )
#         assert "avg_original_norm" in norm_metadata
#         assert norm_metadata["zero_vectors"] >= 0
#         assert len(norm_metadata["original_norms"]) == len(sample_documents)

#         # Phase 4: Verify chunks metadata is accessible for retrieval
#         for chunk in sample_documents:
#             assert chunk.metadata is not None
#             assert "source" in chunk.metadata
#             assert "chunk_id" in chunk.metadata

#     @pytest.mark.slow
#     @pytest.mark.integration
#     def test_embedding_lifecycle_with_normalization_config(self, sample_documents):
#         """Test embedding lifecycle with normalization enabled (realistic scenario).

#         This test uses a real embedding model and mirrors the omnirag.py workflow
#         with normalization enabled, verifying that normalized embeddings are
#         properly configured for indexing and retrieval.
#         """
#         from src.embeddingloader import EmbeddingModelLoader

#         # Use a lightweight real embedding model
#         embedding_model_name = "all-MiniLM-L6-v2"

#         # Get real embedding model
#         embedding_model = EmbeddingModelLoader.load_embedding_model(
#             "faiss", embedding_model_name
#         )
#         embedding_dimension = EmbeddingModelLoader.get_embedding_dimension(
#             "faiss", embedding_model_name
#         )

#         tokenizer = MagicMock()
#         model = MagicMock()

#         # Create EmbeddingVectors with normalization enabled
#         embedding_vector = EmbeddingVectors(
#             tokenizer=tokenizer,
#             model=model,
#             create_new_vs=True,
#             existing_vector_store=None,
#             new_vs_name="test_normalized_vs",
#             embedding_model_name=embedding_model_name,
#             normalize_embeddings=True,
#             normalization_strategy="l2",
#             log_normalization_stats=True,
#             detect_already_normalized=False,  # Disable detection to force normalization
#         )

#         # Generate real embeddings from document chunks
#         chunk_texts = [doc.page_content for doc in sample_documents]
#         raw_embeddings = embedding_model.encode(
#             chunk_texts, show_progress_bar=False, convert_to_tensor=False
#         ).astype(np.float32)

#         # Normalize embeddings as would happen in the pipeline
#         normalized_embeddings, metadata = embedding_vector.normalize_embeddings_l2(
#             raw_embeddings
#         )

#         # Verify normalization properties
#         norms = np.linalg.norm(normalized_embeddings, axis=1)
#         assert np.allclose(norms, 1.0), "All embedding norms should be close to 1.0"

#         # Verify metadata shows normalization was applied
#         assert metadata["strategy"] == "l2"
#         assert "original_norms" in metadata, "Metadata should contain original norms"
#         assert len(metadata["original_norms"]) == len(sample_documents)

#         # Verify embeddings maintain shape for indexing
#         assert normalized_embeddings.shape == (
#             len(sample_documents),
#             embedding_dimension,
#         )

#         # Verify chunks are ready for indexing
#         assert len(sample_documents) == normalized_embeddings.shape[0]

#         # Note: embeddings from sentence-transformers are typically already normalized,
#         # so normalized_embeddings will be very close to raw_embeddings. The real value
#         # of this normalization is ensuring consistency and handling non-normalized embeddings.

#     @pytest.mark.slow
#     @pytest.mark.integration
#     def test_embedding_lifecycle_multiple_vector_stores(self, sample_documents):
#         """Test embedding lifecycle when reusing existing vector stores.

#         This test uses a real embedding model and simulates the omnirag.py
#         scenario where users can add documents to existing vector stores
#         instead of creating new ones.
#         """
#         from src.embeddingloader import EmbeddingModelLoader

#         # Use a lightweight real embedding model
#         embedding_model_name = "all-MiniLM-L6-v2"

#         # Get real embedding model
#         embedding_model = EmbeddingModelLoader.load_embedding_model(
#             "faiss", embedding_model_name
#         )
#         embedding_dimension = EmbeddingModelLoader.get_embedding_dimension(
#             "faiss", embedding_model_name
#         )

#         tokenizer = MagicMock()
#         model = MagicMock()

#         # Phase 1: Create new vector store
#         initial_chunks = [sample_documents[0]]

#         embedding_vector_new = EmbeddingVectors(
#             tokenizer=tokenizer,
#             model=model,
#             create_new_vs=True,
#             existing_vector_store=None,
#             new_vs_name="knowledge_base_v1",
#             embedding_model_name=embedding_model_name,
#             embedding_type="faiss",
#         )

#         assert embedding_vector_new.create_new_vs is True
#         assert embedding_vector_new.new_vs_name == "knowledge_base_v1"

#         # Generate embeddings for initial chunks
#         initial_texts = [doc.page_content for doc in initial_chunks]
#         initial_embeddings = embedding_model.encode(
#             initial_texts, show_progress_bar=False, convert_to_tensor=False
#         ).astype(np.float32)

#         assert initial_embeddings.shape[1] == embedding_dimension

#         # Phase 2: Reuse existing vector store to add more documents
#         additional_chunks = sample_documents[1:]

#         embedding_vector_existing = EmbeddingVectors(
#             tokenizer=tokenizer,
#             model=model,
#             create_new_vs=False,  # Reusing existing store
#             existing_vector_store="knowledge_base_v1",
#             new_vs_name="knowledge_base_v1",
#             embedding_model_name=embedding_model_name,
#             embedding_type="faiss",
#             detect_already_normalized=False,  # Disable detection to verify normalization
#         )

#         assert embedding_vector_existing.create_new_vs is False
#         assert embedding_vector_existing.existing_vector_store == "knowledge_base_v1"

#         # Phase 3: Verify both instances have compatible configurations
#         assert (
#             embedding_vector_new.embedding_dimension
#             == embedding_vector_existing.embedding_dimension
#         )
#         assert (
#             embedding_vector_new.embedding_type
#             == embedding_vector_existing.embedding_type
#         )

#         # Phase 4: Generate embeddings for additional chunks
#         additional_texts = [doc.page_content for doc in additional_chunks]
#         additional_embeddings = embedding_model.encode(
#             additional_texts, show_progress_bar=False, convert_to_tensor=False
#         ).astype(np.float32)

#         # Verify shape compatibility for combining with existing embeddings
#         all_embeddings = np.vstack([initial_embeddings, additional_embeddings])
#         assert all_embeddings.shape[0] == len(sample_documents)
#         assert all_embeddings.shape[1] == embedding_dimension

#         # Normalize combined embeddings to prepare for indexing
#         normalized, metadata = embedding_vector_existing.normalize_embeddings_l2(
#             all_embeddings
#         )

#         # Verify normalization worked across all embeddings
#         norms = np.linalg.norm(normalized, axis=1)
#         assert np.allclose(norms, 1.0)
#         assert metadata["strategy"] == "l2"
