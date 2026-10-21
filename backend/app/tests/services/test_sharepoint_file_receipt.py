from pathlib import Path

from app.services.connectors.sharepoint_otp.receipt import (
    MAX_RECEIPT_FILES,
    FileOutcomeLog,
    relative_filename,
)


def test_receipt_keeps_download_and_ingestion_distinct():
    log = FileOutcomeLog()
    assert log.record("folder/file.pdf", "downloaded")["items"][0]["state"] == "downloaded"
    assert log.record("folder/file.pdf", "ingest_failed")["items"] == [
        {"filename": "folder/file.pdf", "state": "ingest_failed"}
    ]
    assert log.record("other.pdf", "download_failed")["items"][1]["state"] == "download_failed"


def test_large_sync_receipt_is_bounded_and_marks_missing_details():
    log = FileOutcomeLog()
    for index in range(MAX_RECEIPT_FILES + 12):
        result = log.record(f"{index}.pdf", "downloaded")
    assert len(result["items"]) == MAX_RECEIPT_FILES
    assert result["truncated"] is True
    assert log.record("0.pdf", "ingested")["items"][0]["state"] == "ingested"


def test_receipt_never_exposes_absolute_server_paths():
    root = Path("/srv/private/output")
    assert relative_filename(root / "team" / "file.pdf", root) == "team/file.pdf"
    assert relative_filename(Path("/srv/other/private.pdf"), root) == "private.pdf"
