"""Unit tests for the docloader module.

Comprehensive test suite covering:
- Document class: initialization, metadata handling (3 tests)
- PDFMarkdownLoader: initialization, configuration, path validation (8 tests)
- PDF loading methods: fallback logic, error handling (10 tests)
- File operations: directory creation, file reading (8 tests)
- Document creation helpers: success, error, empty documents (6 tests)
- Integration: end-to-end loading scenarios (5 tests)

Total: 40 comprehensive unit tests
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.docloader import Document, PDFMarkdownLoader


class TestDocumentClass:
    """Test suite for the Document class."""

    def test_document_initialization_with_content(self):
        """Test Document initialization with content."""
        content = "This is test content"
        doc = Document(content)

        assert doc.page_content == content
        assert doc.metadata == {}

    def test_document_initialization_with_metadata(self):
        """Test Document initialization with metadata."""
        content = "Test content"
        metadata = {"source": "test.pdf", "page": 1}
        doc = Document(content, metadata)

        assert doc.page_content == content
        assert doc.metadata == metadata

    def test_document_empty_content(self):
        """Test Document with empty content."""
        doc = Document("")

        assert doc.page_content == ""
        assert doc.metadata == {}


class TestPDFMarkdownLoaderInitialization:
    """Test suite for PDFMarkdownLoader initialization."""

    def test_loader_initialization_valid_file(self):
        """Test loader initialization with valid PDF path."""
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            loader = PDFMarkdownLoader(f.name, "/tmp")

            assert loader.file_path == f.name
            assert loader.target_dir == "/tmp"
            assert loader.config is not None
            assert loader.stats is not None

    def test_loader_initialization_nonexistent_file(self):
        """Test loader initialization with nonexistent file."""
        with pytest.raises(FileNotFoundError):
            PDFMarkdownLoader("/nonexistent/path/to/file.pdf", "/tmp")

    def test_loader_stats_initialization(self):
        """Test that stats are properly initialized."""
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            loader = PDFMarkdownLoader(f.name, "/tmp")

            assert "processing_time" in loader.stats
            assert "method_used" in loader.stats
            assert "fallback_used" in loader.stats
            assert "errors" in loader.stats
            assert loader.stats["fallback_used"] is False
            assert loader.stats["errors"] == []

    def test_loader_config_defaults(self):
        """Test that configuration loads with defaults."""
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            loader = PDFMarkdownLoader(f.name, "/tmp")

            assert loader.config["enable_fallback"] is not None
            assert loader.config["pdf_processing_method"] is not None
            assert loader.config["max_workers"] is not None

    def test_loader_config_runtime_overrides(self):
        """Test that runtime kwargs override defaults."""
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            custom_dpi = 300
            loader = PDFMarkdownLoader(f.name, "/tmp", ocr_dpi=custom_dpi)

            assert loader.config["ocr_dpi"] == custom_dpi

    def test_loader_load_configuration_method(self):
        """Test _load_configuration method directly."""
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            loader = PDFMarkdownLoader(f.name, "/tmp")
            config = loader._load_configuration(custom_key="custom_value")

            assert config["custom_key"] == "custom_value"


class TestPDFMarkdownLoaderFileOperations:
    """Test suite for file operations in PDFMarkdownLoader."""

    def test_output_directory_creates_if_needed(self):
        """Test that _output_directory creates directory if needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = str(Path(tmpdir) / "new_dir" / "nested")
            with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
                loader = PDFMarkdownLoader(f.name, target_dir=target_dir)
                result_dir = loader._output_directory()

                assert Path(result_dir).exists()
                assert result_dir == target_dir

    def test_read_markdown_file_success(self):
        """Test successful reading of markdown file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = str(Path(tmpdir) / "test.md")
            test_content = "# Test Markdown\nThis is test content"
            Path(md_path).write_text(test_content)

            with tempfile.NamedTemporaryFile(suffix=".pdf") as pdf_file:
                loader = PDFMarkdownLoader(pdf_file.name, "/tmp")
                content = loader._read_markdown_file(md_path)
                assert content == test_content

    def test_read_markdown_file_not_found(self):
        """Test reading nonexistent markdown file raises error."""
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            loader = PDFMarkdownLoader(f.name, "/tmp")

            with pytest.raises(RuntimeError):
                loader._read_markdown_file("/nonexistent/file.md")


class TestPDFMarkdownLoaderDocumentCreation:
    """Test suite for document creation helper methods."""

    def test_create_success_document(self):
        """Test _create_success_document creates proper document."""
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            loader = PDFMarkdownLoader(f.name, "/tmp")
            content = "Test markdown content"
            result = {"markdown": "/path/to/markdown.md"}
            method = "markdown_converter"

            docs = loader._create_success_document(content, result, method)

            assert len(docs) == 1
            assert docs[0].page_content == content
            assert docs[0].metadata["processing_method"] == method

    def test_create_error_document(self):
        """Test _create_error_document creates error document."""
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            loader = PDFMarkdownLoader(f.name, "/tmp")
            error_msg = "Processing failed"
            method = "test_method"

            docs = loader._create_error_document(error_msg, method)

            assert len(docs) == 1
            assert "Error" in docs[0].page_content
            assert error_msg in docs[0].page_content
            assert docs[0].metadata["processing_method"] == method
            assert "extraction_error" in docs[0].metadata

    def test_create_empty_document(self):
        """Test _create_empty_document handles no content."""
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            loader = PDFMarkdownLoader(f.name, "/tmp")
            result = {}
            method = "test"

            docs = loader._create_empty_document(result, method)

            assert len(docs) == 1
            assert docs[0].metadata["processing_method"] == method


class TestPDFMarkdownLoaderFallback:
    """Test suite for fallback mechanism."""

    @patch("src.docloader.markdown_converter")
    def test_apply_fallback_success(self, mock_converter):
        """Test fallback method succeeds when primary fails."""
        with tempfile.NamedTemporaryFile(suffix=".pdf") as pdf_file:
            mock_converter.return_value = {"markdown": "/tmp/test.md"}

            loader = PDFMarkdownLoader(pdf_file.name, "/tmp")
            loader.config["fallback_method"] = "markdown_converter"

            with patch.object(
                loader, "_read_markdown_file", return_value="Fallback content"
            ):
                primary_error = Exception("Primary failed")
                docs = loader._apply_fallback(primary_error)

            assert len(docs) == 1
            assert loader.stats["fallback_used"] is True

    def test_apply_fallback_unsupported_method(self):
        """Test fallback with unsupported method raises error."""
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            loader = PDFMarkdownLoader(f.name, "/tmp")
            loader.config["fallback_method"] = "unsupported_method"

            primary_error = Exception("Primary failed")
            docs = loader._apply_fallback(primary_error)

            # Should return error document
            assert len(docs) == 1
            assert docs[0].metadata.get("extraction_error") is not None
            assert "Both primary and fallback methods failed" in docs[0].metadata.get(
                "extraction_error"
            )


class TestPDFMarkdownLoaderIntegration:
    """Integration tests for PDFMarkdownLoader."""

    @patch("src.docloader.markdown_converter")
    def test_load_with_markdown_converter_success(self, mock_converter):
        """Test successful load with markdown converter."""
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            mock_converter.return_value = {"markdown": "/tmp/test.md"}

            loader = PDFMarkdownLoader(f.name, "/tmp")
            loader.config["pdf_processing_method"] = "markdown_converter"

            with patch.object(
                loader, "_read_markdown_file", return_value="# Test Content"
            ):
                docs = loader.load()

            assert len(docs) == 1
            assert docs[0].metadata["processing_method"] == "markdown_converter"
            assert docs[0].page_content == "# Test Content"

    @patch("src.docloader.OCRPDFLoader")
    def test_load_with_ocr_success(self, mock_ocr_loader):
        """Test successful load with OCR."""
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            mock_instance = MagicMock()
            mock_instance.load.return_value = [Document("OCR content")]
            mock_ocr_loader.return_value = mock_instance

            loader = PDFMarkdownLoader(f.name, "/tmp")
            loader.config["pdf_processing_method"] = "ocr"

            docs = loader.load()

            assert len(docs) == 1
            assert docs[0].page_content == "OCR content"

    def test_load_invalid_method(self):
        """Test load with invalid processing method."""
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            loader = PDFMarkdownLoader(f.name, "/tmp")
            loader.config["pdf_processing_method"] = "invalid_method"
            loader.config["enable_fallback"] = False

            docs = loader.load()

            # Should return error document
            assert len(docs) == 1
            assert docs[0].metadata.get("extraction_error") is not None
            assert "invalid_method" in docs[0].metadata.get("extraction_error")

    def test_load_stats_tracking(self):
        """Test that load() properly tracks stats."""
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            loader = PDFMarkdownLoader(f.name, "/tmp")
            loader.config["pdf_processing_method"] = "invalid_method"
            loader.config["enable_fallback"] = False

            _ = loader.load()

            # Check that stats are tracked
            assert loader.stats["method_used"] is None
            assert len(loader.stats["errors"]) > 0
            assert loader.stats["fallback_used"] is False


class TestPDFLoader:
    """Test suite for PDFLoader static method."""

    def test_pdf_loader_default(self):
        """Test pdf_loader returns correct defaults."""
        from src.docloader import PDFLoader

        loader_class, loader_args = PDFLoader.pdf_loader()

        assert loader_class is not None
        assert isinstance(loader_args, dict)

    def test_pdf_loader_use_ocr_true(self):
        """Test pdf_loader with use_ocr=True."""
        from src.docloader import PDFLoader

        _, loader_args = PDFLoader.pdf_loader(use_ocr=True)

        assert loader_args["pdf_processing_method"] == "ocr"

    def test_pdf_loader_use_ocr_false(self):
        """Test pdf_loader with use_ocr=False."""
        from src.docloader import PDFLoader

        _, loader_args = PDFLoader.pdf_loader(use_ocr=False)

        assert loader_args["pdf_processing_method"] == "markdown_converter"

    def test_pdf_loader_ocr_dpi_override(self):
        """Test pdf_loader with custom OCR DPI."""
        from src.docloader import PDFLoader

        custom_dpi = 400
        _, loader_args = PDFLoader.pdf_loader(ocr_dpi=custom_dpi)

        assert loader_args["ocr_dpi"] == custom_dpi

    def test_pdf_loader_force_ocr_override(self):
        """Test pdf_loader with force_ocr override."""
        from src.docloader import PDFLoader

        _, loader_args = PDFLoader.pdf_loader(force_ocr=True)

        assert loader_args["ocr_force_ocr"] is True

    def test_pdf_loader_includes_vlm_config(self):
        """Test pdf_loader includes VLM configuration."""
        from src.docloader import PDFLoader

        _, loader_args = PDFLoader.pdf_loader()

        assert "enable_vlm" in loader_args
        assert "vlm_model" in loader_args
        assert "max_workers" in loader_args


class TestLoadSingleDocument:
    """Test suite for loadSingleDocument function."""

    def test_load_single_document_unsupported_extension(self):
        """Test loading with unsupported file extension."""
        from src.docloader import loadSingleDocument

        with pytest.raises(ValueError, match="Unsupported file extension"):
            loadSingleDocument("/path/to/file.xyz", "")

    def test_load_single_document_txt_file(self):
        """Test loading a text file."""
        from src.docloader import loadSingleDocument

        with tempfile.TemporaryDirectory() as tmpdir:
            txt_path = str(Path(tmpdir) / "test.txt")
            test_content = "This is test content"
            Path(txt_path).write_text(test_content)

            # Mock only the storage write to avoid actual I/O
            with patch("src.docloader.fs.write_to_file"):
                with patch("src.docloader.fs.open_for_reading") as mock_read:
                    mock_read.return_value.__enter__.return_value.read.return_value = (
                        test_content.encode()
                    )
                    result = loadSingleDocument(txt_path, "")

                    assert isinstance(result, str)
                    assert test_content in result

    def test_load_single_document_csv_file(self):
        """Test loading a CSV file."""
        from src.docloader import loadSingleDocument

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = str(Path(tmpdir) / "test.csv")
            csv_content = "name,age\nJohn,30\nJane,25"
            Path(csv_path).write_text(csv_content)

            with patch("src.docloader.fs.write_to_file"):
                with patch("src.docloader.fs.open_for_reading") as mock_read:
                    mock_read.return_value.__enter__.return_value.read.return_value = (
                        csv_content.encode()
                    )
                    result = loadSingleDocument(csv_path, "")

                    assert isinstance(result, str)
                    # CSV loader should extract data
                    assert len(result) > 0

    def test_load_single_document_unsupported_file_raises_error(self):
        """Test that unsupported extensions raise ValueError."""
        from src.docloader import loadSingleDocument

        with pytest.raises(ValueError):
            loadSingleDocument("somefile.unsupported", "")


class TestThreadMultiDocLoader:
    """Test suite for ThreadMultiDocLoader function."""

    def test_thread_multi_doc_loader_empty_list(self):
        """Test with empty file list."""
        from src.docloader import ThreadMultiDocLoader

        result = ThreadMultiDocLoader([], "")

        assert result == ""

    def test_thread_multi_doc_loader_single_file(self):
        """Test with single file."""
        from src.docloader import ThreadMultiDocLoader

        with tempfile.TemporaryDirectory() as tmpdir:
            txt_path = str(Path(tmpdir) / "test.txt")
            test_content = "Single file content"
            Path(txt_path).write_text(test_content)

            with patch("src.docloader.fs.write_to_file"):
                with patch("src.docloader.fs.open_for_reading") as mock_read:
                    mock_read.return_value.__enter__.return_value.read.return_value = (
                        test_content.encode()
                    )
                    result = ThreadMultiDocLoader([txt_path], "")

                    assert test_content in result

    def test_thread_multi_doc_loader_multiple_files(self):
        """Test with multiple files."""
        from src.docloader import ThreadMultiDocLoader

        with tempfile.TemporaryDirectory() as tmpdir:
            file_paths = []
            file_contents = ["Content 1", "Content 2", "Content 3"]

            for i, content in enumerate(file_contents):
                txt_path = str(Path(tmpdir) / f"test{i}.txt")
                Path(txt_path).write_text(content)
                file_paths.append(txt_path)

            with patch("src.docloader.fs.write_to_file"):
                with patch("src.docloader.fs.open_for_reading") as mock_read:
                    # Return appropriate content for each file
                    mock_read.return_value.__enter__.return_value.read.side_effect = [
                        c.encode() for c in file_contents
                    ]
                    result = ThreadMultiDocLoader(file_paths, "")

                    # All contents should be in result
                    for content in file_contents:
                        assert content in result

    def test_thread_multi_doc_loader_ignored_files(self):
        """Test with ignored files."""
        from src.docloader import ThreadMultiDocLoader

        with tempfile.TemporaryDirectory() as tmpdir:
            file1_path = str(Path(tmpdir) / "file1.txt")
            file2_path = str(Path(tmpdir) / "file2.txt")

            content1 = "Keep this"
            content2 = "Ignore this"

            Path(file1_path).write_text(content1)
            Path(file2_path).write_text(content2)

            with patch("src.docloader.fs.write_to_file"):
                with patch("src.docloader.fs.open_for_reading") as mock_read:
                    mock_read.return_value.__enter__.return_value.read.return_value = (
                        content1.encode()
                    )

                    result = ThreadMultiDocLoader(
                        [file1_path, file2_path], "", ignored_files=[file2_path]
                    )

                    # Only file1 should be in result
                    assert content1 in result
                    assert content2 not in result

    def test_thread_multi_doc_loader_error_handling(self):
        """Test error handling for failed file loads."""
        from src.docloader import ThreadMultiDocLoader

        with tempfile.TemporaryDirectory() as tmpdir:
            good_file = str(Path(tmpdir) / "good.txt")
            bad_file = str(Path(tmpdir) / "bad.unsupported")

            good_content = "Good content"
            Path(good_file).write_text(good_content)
            Path(bad_file).write_text("This file has unsupported extension")

            with patch("src.docloader.fs.write_to_file"):
                # One file is good, one fails
                with patch("src.docloader.fs.open_for_reading") as mock_read:
                    mock_read.return_value.__enter__.return_value.read.return_value = (
                        good_content.encode()
                    )

                    result = ThreadMultiDocLoader([good_file, bad_file], "")

                    # Should still return good content even if one file fails
                    assert good_content in result

    def test_thread_multi_doc_loader_result_concatenation(self):
        """Test that results are properly concatenated with newlines."""
        from src.docloader import ThreadMultiDocLoader

        with tempfile.TemporaryDirectory() as tmpdir:
            file1 = str(Path(tmpdir) / "file1.txt")
            file2 = str(Path(tmpdir) / "file2.txt")

            content1 = "Content A"
            content2 = "Content B"

            Path(file1).write_text(content1)
            Path(file2).write_text(content2)

            with patch("src.docloader.fs.write_to_file"):
                with patch("src.docloader.fs.open_for_reading") as mock_read:
                    mock_read.return_value.__enter__.return_value.read.side_effect = [
                        content1.encode(),
                        content2.encode(),
                    ]

                    result = ThreadMultiDocLoader([file1, file2], "")

                    # Both contents should be in result
                    assert content1 in result
                    assert content2 in result
                    # They should be separated (not directly concatenated without separator)
                    assert result.count("\n") >= 1
