import io
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from connections.models.flow_operations import IngestDocumentsPayload
from src.services.ingest_documents import IngestDocumentsService

KB_UUID = "11111111-1111-1111-1111-111111111111"
INPUT_BUCKET_UUID = "22222222-2222-2222-2222-222222222222"
DOCUMENT_NAMES = ["doc1.pdf", "doc2.pdf"]

FAKE_WORKSPACE = "workspace-123"
FAKE_BUCKET_FOLDER = "buckets"
FAKE_KB_FOLDER = "knowledge_bases"
FAKE_ORIGINAL_FOLDER = "original"
FAKE_INGESTED_FOLDER = "ingested"

VALID_PAYLOAD_KWARGS = {
    "input_documents_bucket": UUID(INPUT_BUCKET_UUID),
    "knowledge_base_name": "My Knowledge Base",
    "knowledge_base_description": "A test knowledge base",
    "knowledge_base_creator": "test_user",
}


@pytest.fixture
def payload():
    return IngestDocumentsPayload(**VALID_PAYLOAD_KWARGS)


@pytest.fixture
def minimal_payload():
    """Only required fields — relies on model defaults for optional ones."""
    return IngestDocumentsPayload(
        input_documents_bucket=UUID(INPUT_BUCKET_UUID),
        knowledge_base_name="Minimal KB",
    )


@pytest.fixture
def mock_fs():
    """
    fs is globally mocked as an fsspec-backed filesystem wrapper.
    We patch it at the service's module level.
    """
    with patch("src.services.ingest_documents.fs") as mock:
        mock.joinpath.side_effect = lambda *parts: "/".join(str(p) for p in parts)
        mock.joinpaths.side_effect = lambda base, names: [f"{base}/{n}" for n in names]
        mock.filesystem = MagicMock()
        yield mock


@pytest.fixture
def mock_kb():
    with patch("src.services.ingest_documents.KnowledgeBases") as mock:
        kb_instance = MagicMock()
        kb_instance.document_names = DOCUMENT_NAMES
        mock.get_by_uuid.return_value = kb_instance
        yield mock


@pytest.fixture
def mock_thread_loader():
    with patch("src.services.ingest_documents.ThreadMultiDocLoader") as mock:
        yield mock


@pytest.fixture
def mock_storage_constants():
    with (
        patch("src.services.ingest_documents.WORKSPACE_UUID", FAKE_WORKSPACE),
        patch("src.services.ingest_documents.BUCKET_FOLDER", FAKE_BUCKET_FOLDER),
        patch("src.services.ingest_documents.KNOWLEDGE_BASE_FOLDER", FAKE_KB_FOLDER),
        patch("src.services.ingest_documents.KB_ORIGINAL_FOLDER", FAKE_ORIGINAL_FOLDER),
        patch("src.services.ingest_documents.KB_INGESTED_FOLDER", FAKE_INGESTED_FOLDER),
    ):
        yield


class TestIngestDocumentsService:
    def test_init_without_celery_task(self):
        service = IngestDocumentsService()
        assert service.celery_task is None

    def test_init_with_celery_task(self):
        mock_task = MagicMock()
        service = IngestDocumentsService(celery_task=mock_task)
        assert service.celery_task is mock_task

    def test_call_copies_files_to_original_folder(
        self, payload, mock_fs, mock_kb, mock_thread_loader, mock_storage_constants
    ):
        IngestDocumentsService().call(payload, KB_UUID)

        expected_input_path = (
            f"{FAKE_WORKSPACE}/{FAKE_BUCKET_FOLDER}/{INPUT_BUCKET_UUID}"
        )
        expected_original_path = (
            f"{FAKE_WORKSPACE}/{FAKE_KB_FOLDER}/{KB_UUID}/{FAKE_ORIGINAL_FOLDER}"
        )

        mock_fs.filesystem.copy.assert_called_once_with(
            expected_input_path, expected_original_path, recursive=True
        )

    def test_call_fetches_knowledge_base_by_uuid(
        self, payload, mock_fs, mock_kb, mock_thread_loader, mock_storage_constants
    ):
        IngestDocumentsService().call(payload, KB_UUID)

        mock_kb.get_by_uuid.assert_called_once_with(UUID(KB_UUID))

    def test_call_builds_file_paths_from_document_names(
        self, payload, mock_fs, mock_kb, mock_thread_loader, mock_storage_constants
    ):
        IngestDocumentsService().call(payload, KB_UUID)

        expected_original_path = (
            f"{FAKE_WORKSPACE}/{FAKE_KB_FOLDER}/{KB_UUID}/{FAKE_ORIGINAL_FOLDER}"
        )
        mock_fs.joinpaths.assert_called_once_with(
            expected_original_path, DOCUMENT_NAMES
        )

    def test_call_invokes_thread_loader_with_correct_args(
        self, payload, mock_fs, mock_kb, mock_thread_loader, mock_storage_constants
    ):
        IngestDocumentsService().call(payload, KB_UUID)

        expected_file_paths = [
            f"{FAKE_WORKSPACE}/{FAKE_KB_FOLDER}/{KB_UUID}/{FAKE_ORIGINAL_FOLDER}/{name}"
            for name in DOCUMENT_NAMES
        ]
        expected_ingested_path = (
            f"{FAKE_WORKSPACE}/{FAKE_KB_FOLDER}/{KB_UUID}/{FAKE_INGESTED_FOLDER}"
        )

        mock_thread_loader.assert_called_once_with(
            file_paths=expected_file_paths,
            target_dir=expected_ingested_path,
        )

    def test_call_joinpath_called_for_all_paths(
        self, payload, mock_fs, mock_kb, mock_thread_loader, mock_storage_constants
    ):
        IngestDocumentsService().call(payload, KB_UUID)

        # joinpath should be called 3 times: input, original, and ingested paths
        assert mock_fs.joinpath.call_count == 3

    def test_call_operations_order(
        self, payload, mock_fs, mock_kb, mock_thread_loader, mock_storage_constants
    ):
        """Ensure copy happens before ThreadMultiDocLoader is instantiated."""
        call_order = []

        mock_fs.filesystem.copy.side_effect = lambda *a, **kw: call_order.append("copy")
        mock_thread_loader.side_effect = lambda **kw: call_order.append("loader")

        IngestDocumentsService().call(payload, KB_UUID)

        assert call_order == ["copy", "loader"]

    def test_call_with_celery_task_does_not_affect_core_logic(
        self, payload, mock_fs, mock_kb, mock_thread_loader, mock_storage_constants
    ):
        celery_task = MagicMock()
        IngestDocumentsService(celery_task=celery_task).call(payload, KB_UUID)

        mock_fs.filesystem.copy.assert_called_once()
        mock_thread_loader.assert_called_once()

    def test_call_works_with_minimal_payload(
        self,
        minimal_payload,
        mock_fs,
        mock_kb,
        mock_thread_loader,
        mock_storage_constants,
    ):
        """Service should work with only required fields set, using model defaults."""
        IngestDocumentsService().call(minimal_payload, KB_UUID)

        mock_fs.filesystem.copy.assert_called_once()
        mock_thread_loader.assert_called_once()


class TestIngestDocumentsPayload:
    def test_required_fields_missing_raises(self):
        with pytest.raises(Exception):
            IngestDocumentsPayload()

    def test_missing_knowledge_base_name_raises(self):
        with pytest.raises(Exception):
            IngestDocumentsPayload(input_documents_bucket=UUID(INPUT_BUCKET_UUID))

    def test_missing_input_documents_bucket_raises(self):
        with pytest.raises(Exception):
            IngestDocumentsPayload(knowledge_base_name="KB")

    def test_valid_full_payload(self):
        payload = IngestDocumentsPayload(**VALID_PAYLOAD_KWARGS)
        assert payload.input_documents_bucket == UUID(INPUT_BUCKET_UUID)
        assert payload.knowledge_base_name == "My Knowledge Base"
        assert payload.knowledge_base_description == "A test knowledge base"
        assert payload.knowledge_base_creator == "test_user"

    def test_default_description_is_empty_string(self):
        payload = IngestDocumentsPayload(
            input_documents_bucket=UUID(INPUT_BUCKET_UUID),
            knowledge_base_name="KB",
        )
        assert payload.knowledge_base_description == ""

    def test_default_creator_is_guest(self):
        payload = IngestDocumentsPayload(
            input_documents_bucket=UUID(INPUT_BUCKET_UUID),
            knowledge_base_name="KB",
        )
        assert payload.knowledge_base_creator == "guest"

    def test_input_documents_bucket_is_uuid_type(self):
        payload = IngestDocumentsPayload(**VALID_PAYLOAD_KWARGS)
        assert isinstance(payload.input_documents_bucket, UUID)

    def test_input_documents_bucket_accepts_uuid_string(self):
        payload = IngestDocumentsPayload(
            input_documents_bucket=INPUT_BUCKET_UUID,  # string, not UUID object
            knowledge_base_name="KB",
        )
        assert payload.input_documents_bucket == UUID(INPUT_BUCKET_UUID)


class TestIngestDocumentsServiceCSVIntegration:
    """
    Integration test: runs IngestDocumentsService.call end-to-end with a real
    CSV file on a real temp filesystem. No mocking of ThreadMultiDocLoader or
    loadSingleDocument — we verify both storage assertions:

      1. The original CSV is copied verbatim into the `original/` folder.
      2. The extracted `.txt` is written into the `ingested/` folder and its
         content matches the CSV rows.
    """

    CSV_FILENAME = "sales.csv"
    CSV_CONTENT = "name,amount\nAlice,100\nBob,200\nCharlie,300\n"

    @pytest.fixture
    def tmp_dirs(self, tmp_path):
        """Create the bucket source dir and KB target dirs on disk."""
        input_dir = tmp_path / "bucket" / INPUT_BUCKET_UUID
        input_dir.mkdir(parents=True)
        (input_dir / self.CSV_FILENAME).write_text(self.CSV_CONTENT)

        original_dir = tmp_path / "kb" / KB_UUID / "original"
        ingested_dir = tmp_path / "kb" / KB_UUID / "ingested"
        original_dir.mkdir(parents=True)
        ingested_dir.mkdir(parents=True)

        return {
            "input": str(input_dir),
            "original": str(original_dir),
            "ingested": str(ingested_dir),
        }

    @pytest.fixture
    def real_fs(self, tmp_dirs):
        """
        Wire the global `fs` mock to operate on real temp paths so that:
        - fs.filesystem.copy   → shutil.copytree (mirrors fsspec recursive copy)
        - fs.joinpath          → simple string join
        - fs.joinpaths         → list of joined paths
        - fs.open_for_reading  → opens the real file from original/
        - fs.write_to_file     → writes the real .txt into ingested/
        """
        mock = MagicMock()

        def _copy(src, dst, recursive=False):
            # mirrors what fsspec recursive copy does: copy src contents into dst
            shutil.copytree(src, dst, dirs_exist_ok=True)

        mock.filesystem.copy.side_effect = _copy
        mock.joinpath.side_effect = lambda *parts: "/".join(str(p) for p in parts)
        mock.joinpaths.side_effect = lambda base, names: [f"{base}/{n}" for n in names]

        def _open_for_reading(path):
            # path is a joined string — resolve to the real original/ file
            filename = Path(path).name
            real_path = Path(tmp_dirs["original"]) / filename
            cm = MagicMock()
            cm.__enter__ = MagicMock(return_value=io.BytesIO(real_path.read_bytes()))
            cm.__exit__ = MagicMock(return_value=False)
            return cm

        mock.open_for_reading.side_effect = _open_for_reading

        def _write_to_file(path, content):
            filename = Path(path).name
            (Path(tmp_dirs["ingested"]) / filename).write_text(content)

        mock.write_to_file.side_effect = _write_to_file

        return mock

    @pytest.fixture
    def payload(self):
        return IngestDocumentsPayload(
            input_documents_bucket=UUID(INPUT_BUCKET_UUID),
            knowledge_base_name="Sales KB",
        )

    @pytest.fixture
    def mock_kb(self):
        with patch("src.services.ingest_documents.KnowledgeBases") as mock:
            kb_instance = MagicMock()
            kb_instance.document_names = [self.CSV_FILENAME]
            mock.get_by_uuid.return_value = kb_instance
            yield mock

    def _run_service(self, payload, tmp_dirs, real_fs, mock_kb):
        with (
            patch("src.services.ingest_documents.fs", real_fs),
            patch("src.docloader.fs", real_fs),
            patch("src.services.ingest_documents.WORKSPACE_UUID", "ws"),
            patch("src.services.ingest_documents.BUCKET_FOLDER", "bucket"),
            patch("src.services.ingest_documents.KNOWLEDGE_BASE_FOLDER", "kb"),
            patch("src.services.ingest_documents.KB_ORIGINAL_FOLDER", "original"),
            patch("src.services.ingest_documents.KB_INGESTED_FOLDER", "ingested"),
            # Make joinpath resolve to actual temp paths for copy + loader
            patch.object(
                real_fs,
                "joinpath",
                side_effect=lambda *parts: {
                    ("ws", "bucket", INPUT_BUCKET_UUID): tmp_dirs["input"],
                    ("ws", "kb", KB_UUID, "original"): tmp_dirs["original"],
                    ("ws", "kb", KB_UUID, "ingested"): tmp_dirs["ingested"],
                }.get(parts, "/".join(str(p) for p in parts)),
            ),
            patch.object(
                real_fs,
                "joinpaths",
                side_effect=lambda base, names: [
                    str(Path(tmp_dirs["original"]) / n) for n in names
                ],
            ),
        ):
            IngestDocumentsService().call(payload, KB_UUID)

    def test_original_csv_is_saved_in_original_folder(
        self, payload, tmp_dirs, real_fs, mock_kb
    ):
        self._run_service(payload, tmp_dirs, real_fs, mock_kb)

        original_csv = Path(tmp_dirs["original"]) / self.CSV_FILENAME
        assert original_csv.exists(), "Original CSV not found in original/ folder"

    def test_original_csv_content_is_preserved(
        self, payload, tmp_dirs, real_fs, mock_kb
    ):
        self._run_service(payload, tmp_dirs, real_fs, mock_kb)

        original_csv = Path(tmp_dirs["original"]) / self.CSV_FILENAME
        assert original_csv.read_text() == self.CSV_CONTENT

    def test_extracted_txt_is_saved_in_ingested_folder(
        self, payload, tmp_dirs, real_fs, mock_kb
    ):
        self._run_service(payload, tmp_dirs, real_fs, mock_kb)

        ingested_txt = Path(tmp_dirs["ingested"]) / "sales_csv.txt"
        assert ingested_txt.exists(), "Extracted .txt not found in ingested/ folder"

    def test_extracted_txt_contains_csv_row_data(
        self, payload, tmp_dirs, real_fs, mock_kb
    ):
        self._run_service(payload, tmp_dirs, real_fs, mock_kb)

        ingested_txt = Path(tmp_dirs["ingested"]) / "sales_csv.txt"
        extracted = ingested_txt.read_text()

        assert "Alice" in extracted
        assert "Bob" in extracted
        assert "Charlie" in extracted

    def test_extracted_txt_contains_all_csv_values(
        self, payload, tmp_dirs, real_fs, mock_kb
    ):
        self._run_service(payload, tmp_dirs, real_fs, mock_kb)

        ingested_txt = Path(tmp_dirs["ingested"]) / "sales_csv.txt"
        extracted = ingested_txt.read_text()

        assert "100" in extracted
        assert "200" in extracted
        assert "300" in extracted
