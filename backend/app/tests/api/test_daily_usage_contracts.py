from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile

from app.api.v1.endpoints import client360, documents


def test_mail_send_requires_explicit_review_before_any_external_effect(monkeypatch):
    def unexpected_send(*args, **kwargs):
        pytest.fail("An unreviewed draft reached the mail sender")

    monkeypatch.setattr(client360, "send_mail_draft", unexpected_send)
    with pytest.raises(HTTPException) as refused:
        client360.client360_mail_draft_send(
            "draft",
            client360.MailDraftSend(to_email="buyer@example.test"),
            workspace=SimpleNamespace(),
            user=SimpleNamespace(),
            db=SimpleNamespace(),
        )
    assert refused.value.status_code == 409
    assert refused.value.detail["code"] == "mail_review_required"


@pytest.mark.asyncio
async def test_partial_upload_names_refused_files_and_retains_their_reason(monkeypatch):
    monkeypatch.setattr(documents.settings, "document_ingest_async_enabled", False)
    monkeypatch.setattr(documents, "require_named_collection_write", lambda *args, **kwargs: None)
    monkeypatch.setattr(documents, "_resolve_document_vector_db_type", lambda *args: "qdrant")

    class Ingest:
        async def ingest_documents_batch(self, paths):
            return {
                "total": 2,
                "successful": 1,
                "failed": 1,
                "results": [
                    {"document_id": "doc-ok", "filename": "ok.txt", "status": "success"},
                    {"document_id": paths[1], "status": "error", "error": "Encrypted document"},
                ],
            }

    monkeypatch.setattr(documents, "DocumentService", lambda **kwargs: Ingest())
    result = await documents.upload_documents_batch(
        files=[
            UploadFile(file=BytesIO(b"ok"), filename="ok.txt"),
            UploadFile(file=BytesIO(b"bad"), filename="blocked.txt"),
        ],
        collection_name="documents",
        vector_db_type=None,
        source=None,
        workspace=SimpleNamespace(slug="test"),
        user=SimpleNamespace(id="person"),
        db=SimpleNamespace(),
    )
    refused = result["documents"][1]
    assert refused["filename"] == "blocked.txt"
    assert refused["error"] == "Encrypted document"
    assert refused["document_id"] is None
