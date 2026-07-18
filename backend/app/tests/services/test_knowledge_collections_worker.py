from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.models.knowledge_collection import (
    KnowledgeCollection,
    KnowledgeCollectionSource,
    WorkerJob,
)
from app.models.secure_deposit import DepositAccessLink, DepositFile
from app.models.user import User
from app.models.workspace import Workspace
from app.services.knowledge_collections import (
    create_collection,
    create_worker_job,
    document_manifest_key,
    original_key,
    update_job,
    upsert_collection_source,
)
from app.services.object_store import get_object_store
from app.services.rag.bm25_store import (
    bm25_artifact_key,
    load_bm25_artifact,
    rebuild_bm25_artifact,
)
from app.services.worker_bm25 import run_bm25_rebuild
from app.services.worker_ingest import (
    _finalize_linked_deposit_files,
    run_document_ingest_index,
)


def _workspace(db_session, *, slug: str = "acme") -> Workspace:
    ws = Workspace(id="ws-1", name="Acme", slug=slug)
    db_session.add(ws)
    db_session.commit()
    return ws


def test_collection_slug_is_workspace_unique(db_session):
    ws = _workspace(db_session)

    first = create_collection(db_session, workspace=ws, name="Policies")
    second = create_collection(db_session, workspace=ws, name="Policies")
    db_session.commit()

    assert first.slug == "policies"
    assert second.slug == "policies-2"
    assert first.vector_collection_name == "acme__policies"


def test_worker_job_lifecycle_update(db_session):
    ws = _workspace(db_session)
    collection = create_collection(db_session, workspace=ws, name="Docs")
    job = create_worker_job(
        db_session,
        workspace_id=ws.id,
        collection_id=collection.id,
        kind="document_ingest_index",
    )

    update_job(db_session, job.id, status="running", progress=50)
    update_job(
        db_session, job.id, status="completed", progress=100, result={"ok": True}
    )
    db_session.commit()

    refreshed = db_session.query(WorkerJob).filter(WorkerJob.id == job.id).one()
    assert refreshed.status == "completed"
    assert refreshed.progress == 100
    assert refreshed.started_at is not None
    assert refreshed.completed_at is not None
    assert refreshed.result == {"ok": True}


def test_worker_ingest_skips_terminal_job(db_session, monkeypatch):
    ws = _workspace(db_session)
    collection = create_collection(db_session, workspace=ws, name="Docs")
    job = create_worker_job(
        db_session,
        workspace_id=ws.id,
        collection_id=collection.id,
        kind="document_ingest_index",
    )
    job.status = "cancelled"
    db_session.commit()

    monkeypatch.setattr(
        "app.services.worker_ingest.DocumentParserFactory.get_parser",
        lambda _path: pytest.fail("terminal jobs must not parse documents"),
    )

    result = run_document_ingest_index(job.id)

    db_session.expire_all()
    refreshed = db_session.query(WorkerJob).filter(WorkerJob.id == job.id).one()
    assert result["status"] == "skipped"
    assert result["reason"] == "worker_job_already_terminal"
    assert refreshed.status == "cancelled"


def test_worker_ingest_claim_is_idempotent_for_duplicate_delivery(
    db_session,
    monkeypatch,
):
    ws = _workspace(db_session)
    collection = create_collection(db_session, workspace=ws, name="Claimed Docs")
    job = create_worker_job(
        db_session,
        workspace_id=ws.id,
        collection_id=collection.id,
        kind="document_ingest_index",
    )
    job.status = "running"
    db_session.commit()
    monkeypatch.setattr(
        "app.services.worker_ingest.DocumentParserFactory.get_parser",
        lambda _path: pytest.fail("a duplicate delivery must not parse"),
    )

    result = run_document_ingest_index(job.id)

    assert result == {
        "status": "skipped",
        "reason": "worker_job_not_claimable",
        "job_id": job.id,
        "job_status": "running",
    }


def test_worker_ingest_indexes_collection_and_writes_ingested_text(
    db_session,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "default_vector_db_type", "faiss")

    ws = _workspace(db_session)
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    collection.document_names = ["manual.txt"]
    job = create_worker_job(
        db_session,
        workspace_id=ws.id,
        collection_id=collection.id,
        kind="document_ingest_index",
    )
    get_object_store().write_bytes(
        original_key(collection, "manual.txt"), b"hello world"
    )
    get_object_store().write_text(
        document_manifest_key(collection),
        json.dumps(
            {
                "manual.txt": {
                    "project_code": "BBA120",
                    "source_family": "operating_manual",
                }
            }
        ),
    )
    db_session.commit()

    parse_calls = []

    class FakeParser:
        async def parse(self, _path):
            parse_calls.append(_path)
            return SimpleNamespace(
                chunks=[{"content": "hello world"}], raw_content="hello world"
            )

    class FakeDocumentService:
        def __init__(self, *args, **kwargs):
            self.vector_db = object()
            self.cleared = False

        async def clear_all_documents(self):
            self.cleared = True
            return True

        async def ingest_documents_batch(self, paths, **_kwargs):
            assert self.cleared is True
            assert (
                _kwargs["document_metadata_by_name"]["manual.txt"]["project_code"]
                == "BBA120"
            )
            parsed_by_path = _kwargs["parsed_documents_by_path"]
            assert set(parsed_by_path) == set(paths)
            assert parsed_by_path[paths[0]].chunks == [{"content": "hello world"}]
            assert parsed_by_path[paths[0]].raw_content == ""
            return {
                "total": len(paths),
                "successful": len(paths),
                "failed": 0,
                "results": [{"status": "success", "chunks_processed": 1, "document_id": "doc-1"}],
            }

        async def get_document_count(self):
            return 1

        async def list_documents(self):
            return [{"document_id": "doc-1", "filename": "manual.txt"}]

    async def fake_bm25(**_kwargs):
        return {"status": "ready", "chunk_count": 1}

    monkeypatch.setattr(
        "app.services.worker_ingest.DocumentParserFactory.get_parser",
        lambda _path: FakeParser(),
    )
    monkeypatch.setattr(
        "app.services.worker_ingest.DocumentService", FakeDocumentService
    )
    monkeypatch.setattr("app.services.worker_ingest.rebuild_bm25_artifact", fake_bm25)

    result = run_document_ingest_index(job.id)

    db_session.expire_all()
    refreshed_collection = (
        db_session.query(KnowledgeCollection)
        .filter(KnowledgeCollection.id == collection.id)
        .one()
    )
    refreshed_job = db_session.query(WorkerJob).filter(WorkerJob.id == job.id).one()
    source = (
        db_session.query(KnowledgeCollectionSource)
        .filter(
            KnowledgeCollectionSource.collection_id == collection.id,
            KnowledgeCollectionSource.filename == "manual.txt",
        )
        .one()
    )
    assert result["chunk_count"] == 1
    assert refreshed_collection.status == "ready"
    assert refreshed_collection.document_count == 1
    assert refreshed_job.status == "completed"
    assert source.source_metadata["project_code"] == "BBA120"
    assert source.source_metadata["source_family"] == "operating_manual"
    assert source.source_metadata["document_id"] is not None
    assert len(parse_calls) == 1
    assert (
        get_object_store().read_bytes(
            f"{collection.artifact_prefix}/ingested/manual.txt"
        )
        == b"hello world"
    )


def test_worker_ingest_dedupes_identical_content(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "default_vector_db_type", "faiss")

    ws = _workspace(db_session)
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    collection.document_names = ["manual.txt", "manual-copy.txt"]
    job = create_worker_job(
        db_session,
        workspace_id=ws.id,
        collection_id=collection.id,
        kind="document_ingest_index",
    )
    get_object_store().write_bytes(original_key(collection, "manual.txt"), b"same bytes")
    get_object_store().write_bytes(original_key(collection, "manual-copy.txt"), b"same bytes")
    db_session.commit()

    class FakeParser:
        async def parse(self, _path):
            return SimpleNamespace(chunks=[{"content": "same bytes"}], raw_content="same bytes")

    ingested_batches: list[list[str]] = []

    class FakeDocumentService:
        def __init__(self, *args, **kwargs):
            self.vector_db = object()

        async def clear_all_documents(self):
            return True

        async def ingest_documents_batch(self, paths, **_kwargs):
            ingested_batches.append(list(paths))
            metadata = _kwargs["document_metadata_by_name"]
            assert metadata["manual.txt"]["content_sha256"]
            return {
                "total": len(paths),
                "successful": len(paths),
                "failed": 0,
                "results": [
                    {"status": "success", "chunks_processed": 1, "document_id": "doc-1"}
                ],
            }

        async def get_document_count(self):
            return 1

        async def list_documents(self):
            return [{"document_id": "doc-1", "filename": "manual.txt"}]

    async def fake_bm25(**_kwargs):
        return {"status": "ready", "chunk_count": 1}

    monkeypatch.setattr(
        "app.services.worker_ingest.DocumentParserFactory.get_parser",
        lambda _path: FakeParser(),
    )
    monkeypatch.setattr("app.services.worker_ingest.DocumentService", FakeDocumentService)
    monkeypatch.setattr("app.services.worker_ingest.rebuild_bm25_artifact", fake_bm25)

    run_document_ingest_index(job.id)

    db_session.expire_all()
    # Only the canonical file reached embedding.
    assert len(ingested_batches) == 1
    assert len(ingested_batches[0]) == 1
    duplicate = (
        db_session.query(KnowledgeCollectionSource)
        .filter(
            KnowledgeCollectionSource.collection_id == collection.id,
            KnowledgeCollectionSource.filename == "manual-copy.txt",
        )
        .one()
    )
    assert duplicate.status == "deduplicated"
    assert duplicate.source_metadata["duplicate_of"] == "manual.txt"
    assert duplicate.source_metadata["content_sha256"]
    canonical = (
        db_session.query(KnowledgeCollectionSource)
        .filter(
            KnowledgeCollectionSource.collection_id == collection.id,
            KnowledgeCollectionSource.filename == "manual.txt",
        )
        .one()
    )
    assert canonical.status == "ready"
    assert canonical.source_metadata["content_sha256"] == duplicate.source_metadata["content_sha256"]


def test_worker_ingest_preserves_identical_content_across_projects(
    db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "default_vector_db_type", "faiss")
    ws = _workspace(db_session)
    collection = create_collection(db_session, workspace=ws, name="Needlepunch")
    collection.document_names = ["manual-61001.txt", "manual-61009.txt"]
    for name in collection.document_names:
        get_object_store().write_bytes(original_key(collection, name), b"shared manual")
    get_object_store().write_text(
        document_manifest_key(collection),
        json.dumps(
            {
                "manual-61001.txt": {"project_code": "61001"},
                "manual-61009.txt": {"project_code": "61009"},
            }
        ),
    )
    job = create_worker_job(
        db_session,
        workspace_id=ws.id,
        collection_id=collection.id,
        kind="document_ingest_index",
    )
    db_session.commit()

    class FakeParser:
        async def parse(self, _path):
            return SimpleNamespace(chunks=[{"content": "shared manual"}])

    ingested: list[str] = []

    class FakeDocumentService:
        def __init__(self, *args, **kwargs):
            self.vector_db = object()

        async def clear_all_documents(self):
            return True

        async def ingest_documents_batch(self, paths, **_kwargs):
            ingested.extend(Path(path).name for path in paths)
            return {
                "total": 2,
                "successful": 2,
                "failed": 0,
                "results": [
                    {"status": "success", "chunks_processed": 1, "document_id": "a"},
                    {"status": "success", "chunks_processed": 1, "document_id": "b"},
                ],
            }

        async def get_document_count(self):
            return 2

        async def list_documents(self):
            return [{"document_id": "a"}, {"document_id": "b"}]

    async def fake_bm25(**_kwargs):
        return {"status": "ready", "chunk_count": 2}

    monkeypatch.setattr(
        "app.services.worker_ingest.DocumentParserFactory.get_parser",
        lambda _path: FakeParser(),
    )
    monkeypatch.setattr("app.services.worker_ingest.DocumentService", FakeDocumentService)
    monkeypatch.setattr("app.services.worker_ingest.rebuild_bm25_artifact", fake_bm25)

    run_document_ingest_index(job.id)

    db_session.expire_all()
    assert sorted(ingested) == sorted(collection.document_names)
    statuses = {
        row.filename: row.status
        for row in db_session.query(KnowledgeCollectionSource)
        .filter(KnowledgeCollectionSource.collection_id == collection.id)
        .all()
    }
    assert statuses == {"manual-61001.txt": "ready", "manual-61009.txt": "ready"}


def test_worker_ingest_duplicate_only_incremental_wave_completes(
    db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    ws = _workspace(db_session)
    collection = create_collection(db_session, workspace=ws, name="Needlepunch")
    collection.status = "ready"
    collection.chunk_count = 3
    collection.document_names = ["canonical.txt", "copy.txt"]
    content = b"same project manual"
    content_hash = __import__("hashlib").sha256(content).hexdigest()
    get_object_store().write_bytes(original_key(collection, "copy.txt"), content)
    get_object_store().write_text(
        document_manifest_key(collection),
        json.dumps({"copy.txt": {"project_code": "61001"}}),
    )
    db_session.add(
        KnowledgeCollectionSource(
            workspace_id=ws.id,
            collection_id=collection.id,
            filename="canonical.txt",
            normalized_name="canonical.txt",
            status="ready",
            source_metadata={
                "project_code": "61001",
                "content_sha256": content_hash,
            },
        )
    )
    job = create_worker_job(
        db_session,
        workspace_id=ws.id,
        collection_id=collection.id,
        kind="document_ingest_index",
    )
    job.result = {
        "ingest_options": {
            "mode": "incremental",
            "document_names": ["copy.txt"],
            "wave_id": "needlepunch_61001_1",
            "source_profile": "needlepunch",
        }
    }
    db_session.commit()
    monkeypatch.setattr(
        "app.services.worker_ingest.DocumentService",
        lambda *_args, **_kwargs: pytest.fail("duplicate-only wave must not embed"),
    )

    result = run_document_ingest_index(job.id)

    db_session.expire_all()
    refreshed = db_session.query(WorkerJob).filter(WorkerJob.id == job.id).one()
    duplicate = (
        db_session.query(KnowledgeCollectionSource)
        .filter(
            KnowledgeCollectionSource.collection_id == collection.id,
            KnowledgeCollectionSource.filename == "copy.txt",
        )
        .one()
    )
    assert refreshed.status == "completed"
    assert refreshed.result["postflight_required"] is True
    assert refreshed.result["postflight_status"] == "pending"
    assert result["bm25"]["reason"] == "duplicate_only_wave"
    assert duplicate.status == "deduplicated"
    assert duplicate.source_metadata["project_code"] == "61001"
    assert duplicate.source_metadata["duplicate_of"] == "canonical.txt"


@pytest.mark.parametrize(
    ("rollback_result", "rollback_chunk_count", "expected_collection_status"),
    [(True, 41, "ready"), (True, 42, "error"), (False, 41, "error")],
)
def test_needlepunch_incremental_partial_failure_rolls_back_only_wave(
    db_session,
    tmp_path,
    monkeypatch,
    rollback_result,
    rollback_chunk_count,
    expected_collection_status,
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "default_vector_db_type", "faiss")
    ws = _workspace(db_session)
    collection = create_collection(db_session, workspace=ws, name="Needlepunch")
    collection.status = "ready"
    collection.chunk_count = 41
    collection.document_names = ["good.txt", "broken.txt"]
    for name in collection.document_names:
        get_object_store().write_bytes(original_key(collection, name), name.encode())
    get_object_store().write_text(
        document_manifest_key(collection),
        json.dumps(
            {
                name: {
                    "project_code": "61035",
                    "source_profile": "needlepunch",
                    "wave_id": "needlepunch-test-001",
                }
                for name in collection.document_names
            }
        ),
    )
    job = create_worker_job(
        db_session,
        workspace_id=ws.id,
        collection_id=collection.id,
        kind="document_ingest_index",
    )
    job.result = {
        "ingest_options": {
            "mode": "incremental",
            "source_profile": "needlepunch",
            "wave_id": "needlepunch-test-001",
            "document_names": list(collection.document_names),
            "baseline_document_names": [],
            "baseline_document_count": 0,
            "baseline_chunk_count": 41,
        }
    }
    db_session.commit()

    class FakeParser:
        async def parse(self, path, **_kwargs):
            content = Path(path).name
            return SimpleNamespace(
                chunks=[{"content": content}],
                raw_content=content,
            )

    rolled_back: list[str] = []

    class FakeDocumentService:
        def __init__(self, *args, **kwargs):
            self.vector_db = object()

        async def ingest_documents_batch(self, paths, **_kwargs):
            from app.db.base import SessionLocal

            serving_db = SessionLocal()
            try:
                serving_collection = (
                    serving_db.query(KnowledgeCollection)
                    .filter(KnowledgeCollection.id == collection.id)
                    .one()
                )
                assert serving_collection.status == "ready"
            finally:
                serving_db.close()
            assert [Path(path).name for path in paths] == ["good.txt", "broken.txt"]
            return {
                "total": 2,
                "successful": 1,
                "failed": 1,
                "results": [
                    {
                        "status": "success",
                        "chunks_processed": 2,
                        "document_id": "wave-good-document",
                    },
                    {
                        "status": "error",
                        "chunks_processed": 0,
                        "error": "parser failed",
                    },
                ],
            }

        async def delete_document(self, document_id):
            rolled_back.append(document_id)
            return rollback_result

        async def get_document_count(self):
            return rollback_chunk_count

    monkeypatch.setattr(
        "app.services.worker_ingest.DocumentParserFactory.get_parser",
        lambda _path: FakeParser(),
    )
    monkeypatch.setattr(
        "app.services.worker_ingest.DocumentService", FakeDocumentService
    )

    with pytest.raises(RuntimeError, match="verification failed"):
        run_document_ingest_index(job.id)

    db_session.expire_all()
    refreshed_job = db_session.query(WorkerJob).filter(WorkerJob.id == job.id).one()
    refreshed_collection = (
        db_session.query(KnowledgeCollection)
        .filter(KnowledgeCollection.id == collection.id)
        .one()
    )
    sources = (
        db_session.query(KnowledgeCollectionSource)
        .filter(KnowledgeCollectionSource.collection_id == collection.id)
        .all()
    )
    assert rolled_back == ["wave-good-document"]
    assert refreshed_job.status == "failed"
    assert refreshed_collection.status == expected_collection_status
    assert refreshed_collection.chunk_count == 41
    assert {row.status for row in sources} == {"error"}
    if expected_collection_status == "ready":
        assert refreshed_collection.last_error is None
        assert refreshed_collection.document_names == []
        assert refreshed_collection.document_count == 0
    else:
        assert "baseline chunk cardinality was not restored" in (
            refreshed_collection.last_error or ""
        )


def test_worker_ingest_materialize_error_becomes_document_error(
    db_session,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "default_vector_db_type", "faiss")

    ws = _workspace(db_session)
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    collection.document_names = ["good.pdf", "broken.pdf"]
    job = create_worker_job(
        db_session,
        workspace_id=ws.id,
        collection_id=collection.id,
        kind="document_ingest_index",
    )
    get_object_store().write_bytes(original_key(collection, "good.pdf"), b"hello world")
    get_object_store().write_bytes(original_key(collection, "broken.pdf"), b"not a pdf")
    db_session.commit()

    class FakeParser:
        async def parse(self, path, **_kwargs):
            if Path(path).name == "broken.pdf":
                raise RuntimeError("cannot open pdf")
            return SimpleNamespace(
                chunks=[{"content": "hello world"}], raw_content="hello world"
            )

    class FakeDocumentService:
        def __init__(self, *args, **kwargs):
            self.vector_db = object()

        async def clear_all_documents(self):
            return True

        async def ingest_documents_batch(self, paths, **kwargs):
            parsed_by_path = kwargs["parsed_documents_by_path"]
            assert [Path(path).name for path in parsed_by_path] == ["good.pdf"]
            return {
                "total": len(paths),
                "successful": 1,
                "failed": 1,
                "results": [
                    {"status": "success", "chunks_processed": 1},
                    {
                        "status": "error",
                        "chunks_processed": 0,
                        "error": "cannot open pdf",
                    },
                ],
            }

        async def get_document_count(self):
            return 1

        async def list_documents(self):
            return [{"document_id": "doc-1", "filename": "good.pdf"}]

    async def fake_bm25(**_kwargs):
        return {"status": "ready", "chunk_count": 1}

    monkeypatch.setattr(
        "app.services.worker_ingest.DocumentParserFactory.get_parser",
        lambda _path: FakeParser(),
    )
    monkeypatch.setattr(
        "app.services.worker_ingest.DocumentService", FakeDocumentService
    )
    monkeypatch.setattr("app.services.worker_ingest.rebuild_bm25_artifact", fake_bm25)

    result = run_document_ingest_index(job.id)

    db_session.expire_all()
    refreshed_job = db_session.query(WorkerJob).filter(WorkerJob.id == job.id).one()
    broken_source = (
        db_session.query(KnowledgeCollectionSource)
        .filter(
            KnowledgeCollectionSource.collection_id == collection.id,
            KnowledgeCollectionSource.filename == "broken.pdf",
        )
        .one()
    )
    assert refreshed_job.status == "completed"
    assert result["ingest"]["failed"] == 1
    assert broken_source.status == "error"
    assert broken_source.last_error == "cannot open pdf"


def test_worker_ingest_finalizes_deposit_file_and_records_wave_ledger(
    db_session,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "default_vector_db_type", "faiss")

    ws = _workspace(db_session, slug="andritz")
    user = User(id="user-bhx", username="thib", email="operator@example.test")
    db_session.add(user)
    db_session.flush()
    collection = create_collection(
        db_session,
        workspace=ws,
        name="SPL",
        slug="andritz-notices-techniques-spl-pilot",
    )
    document_name = "B__Manual_BHX100_revD__Carding__page1.pdf"
    collection.document_names = [document_name]
    get_object_store().write_bytes(
        original_key(collection, document_name), b"hello carding"
    )
    get_object_store().write_text(
        document_manifest_key(collection),
        json.dumps(
            {
                document_name: {
                    "source_deposit_path": "Notices_Techniques_SPL/B/Manual_BHX100_revD.zip",
                    "archive_name": "Manual_BHX100_revD.zip",
                    "project_code": "BHX100",
                }
            }
        ),
    )
    job = create_worker_job(
        db_session,
        workspace_id=ws.id,
        collection_id=collection.id,
        kind="document_ingest_index",
    )
    job.result = {
        "ingest_options": {
            "mode": "incremental",
            "document_names": [document_name],
            "wave_id": "spl_v3_7",
            "wave_ledger": {
                "collection_slug": collection.slug,
                "wave_id": "spl_v3_7",
                "filenames": ["Notices_Techniques_SPL/B/Manual_BHX100_revD.zip"],
                "job_id": job.id,
                "new_document_count": 1,
            },
        }
    }
    link = DepositAccessLink(
        id="link-bhx",
        workspace_id=ws.id,
        created_by_user_id=user.id,
        label="SPL",
        access_id="spl-link",
        password_hash="hash",
        max_file_size_mb=1024,
        allowed_extensions=["zip"],
    )
    deposit = DepositFile(
        id="deposit-bhx",
        workspace_id=ws.id,
        access_link_id=link.id,
        filename="Notices_Techniques_SPL/B/Manual_BHX100_revD.zip",
        object_key="obj/bhx",
        size_bytes=123,
        sha256="hash",
        status="promoted",
        promoted_collection_slug=collection.slug,
        worker_job_id=job.id,
        promotion_result={"status": "queued", "indexing_status": "queued"},
    )
    db_session.add_all([link, deposit])
    db_session.commit()

    class FakeParser:
        async def parse(self, _path, **_kwargs):
            return SimpleNamespace(chunks=[{"content": "hello carding"}])

    class FakeDocumentService:
        def __init__(self, *args, **kwargs):
            self.vector_db = object()

        async def ingest_documents_batch(self, paths, **_kwargs):
            return {
                "total": len(paths),
                "successful": len(paths),
                "failed": 0,
                "results": [
                    {
                        "status": "success",
                        "filename": "ignored.pdf",
                        "chunks_processed": 2,
                    }
                ],
            }

        async def get_document_count(self):
            return 2

        async def list_documents(self):
            return [{"document_id": "doc-1", "filename": document_name}]

    async def fake_bm25(**_kwargs):
        return {"status": "ready", "chunk_count": 2}

    monkeypatch.setattr(
        "app.services.worker_ingest.DocumentParserFactory.get_parser",
        lambda _path: FakeParser(),
    )
    monkeypatch.setattr(
        "app.services.worker_ingest.DocumentService", FakeDocumentService
    )
    monkeypatch.setattr("app.services.worker_ingest.rebuild_bm25_artifact", fake_bm25)

    result = run_document_ingest_index(job.id)

    db_session.expire_all()
    refreshed_deposit = (
        db_session.query(DepositFile).filter(DepositFile.id == deposit.id).one()
    )
    refreshed_ws = db_session.query(Workspace).filter(Workspace.id == ws.id).one()
    assert refreshed_deposit.status == "promoted"
    assert refreshed_deposit.promotion_result["indexing_status"] == "indexed"
    assert (
        refreshed_deposit.promotion_result["indexing_verification"]["chunk_count"] == 2
    )
    assert result["deposit_files"][0]["indexing_status"] == "indexed"
    assert result["wave_ledger"]["status"] == "recorded"
    ledger = refreshed_ws.settings["spl_wave_ledger"][collection.slug]
    assert (
        "Notices_Techniques_SPL/B/Manual_BHX100_revD.zip"
        in ledger["promoted_filenames"]
    )


def test_zip_deposit_stays_received_until_postflight_after_all_members_indexed(
    db_session,
):
    ws = _workspace(db_session, slug="andritz")
    user = User(id="user-zip-waves", username="zip-operator")
    db_session.add(user)
    db_session.flush()
    collection = create_collection(
        db_session,
        workspace=ws,
        name="Needlepunch ZIP",
        slug="andritz-notices-techniques-spl-pilot",
    )
    link = DepositAccessLink(
        id="link-zip-waves",
        workspace_id=ws.id,
        created_by_user_id=user.id,
        label="Needlepunch ZIP",
        access_id="zip-waves",
        password_hash="hash",
        allowed_extensions=["zip"],
    )
    first_job = create_worker_job(
        db_session,
        workspace_id=ws.id,
        collection_id=collection.id,
        kind="document_ingest_index",
    )
    archive_sha = "a" * 64
    deposit = DepositFile(
        id="deposit-zip-waves",
        workspace_id=ws.id,
        access_link_id=link.id,
        filename=(
            "Notices_Techniques_Needlepunch/60000-69999/"
            "61038 Line/manuals.zip"
        ),
        object_key="obj/zip-waves",
        size_bytes=200,
        sha256=archive_sha,
        status="received",
        worker_job_id=first_job.id,
        promotion_result={
            "indexing_status": "queued",
            "deposit_expected_document_count": 2,
        },
    )
    db_session.add_all([link, deposit])
    locator = {
        "kind": "secure_deposit_zip_member",
        "deposit_file_id": deposit.id,
        "sha256": archive_sha,
    }

    def add_ready_source(name: str) -> None:
        upsert_collection_source(
            db_session,
            collection=collection,
            filename=name,
            status="ready",
            origin="secure_deposit",
            chunk_count=1,
            source_metadata={
                "source_deposit_path": deposit.filename,
                "source_deposit_file_id": deposit.id,
                "source_locator": {**locator, "member_path": name},
            },
        )

    add_ready_source("member-1.txt")
    db_session.flush()
    first = _finalize_linked_deposit_files(
        db_session,
        job=first_job,
        collection=collection,
        file_names=["member-1.txt"],
        document_metadata_by_name={
            "member-1.txt": {"source_deposit_path": deposit.filename}
        },
        source_results_by_name={
            "member-1.txt": {"status": "success", "chunks_processed": 1}
        },
        ingest_result={"failed": 0},
        defer_promotion=True,
    )
    assert first[0]["indexing_status"] == "partial"
    assert first[0]["awaiting_document_count"] == 1
    assert deposit.status == "received"

    second_job = create_worker_job(
        db_session,
        workspace_id=ws.id,
        collection_id=collection.id,
        kind="document_ingest_index",
    )
    deposit.worker_job_id = second_job.id
    add_ready_source("member-2.txt")
    db_session.flush()
    second = _finalize_linked_deposit_files(
        db_session,
        job=second_job,
        collection=collection,
        file_names=["member-2.txt"],
        document_metadata_by_name={
            "member-2.txt": {"source_deposit_path": deposit.filename}
        },
        source_results_by_name={
            "member-2.txt": {"status": "success", "chunks_processed": 1}
        },
        ingest_result={"failed": 0},
        defer_promotion=True,
    )
    assert second[0]["indexing_status"] == "indexed"
    assert second[0]["cumulative_verified_document_count"] == 2
    assert second[0]["awaiting_document_count"] == 0
    assert deposit.status == "received"
    assert deposit.promoted_at is None
    assert deposit.promoted_collection_slug is None
    assert deposit.promotion_result["postflight_status"] == "pending"


def test_worker_ingest_defers_large_bm25_to_worker_job(
    db_session,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "default_vector_db_type", "faiss")

    ws = _workspace(db_session, slug="defer")
    collection = create_collection(db_session, workspace=ws, name="Large Manuals")
    collection.document_names = ["manual.txt"]
    job = create_worker_job(
        db_session,
        workspace_id=ws.id,
        collection_id=collection.id,
        kind="document_ingest_index",
    )
    get_object_store().write_bytes(
        original_key(collection, "manual.txt"), b"hello world"
    )
    db_session.commit()

    class FakeParser:
        async def parse(self, _path):
            return SimpleNamespace(chunks=[{"content": "hello world"}])

    class FakeDocumentService:
        def __init__(self, *args, **kwargs):
            self.vector_db = object()

        async def clear_all_documents(self):
            return True

        async def ingest_documents_batch(self, paths, **_kwargs):
            return {
                "total": len(paths),
                "successful": len(paths),
                "failed": 0,
                "results": [{"status": "success", "chunks_processed": 10}],
            }

        async def get_document_count(self):
            return 75000

        async def list_documents(self):
            return [{"document_id": "doc-1", "filename": "manual.txt"}]

    async def fake_bm25(**_kwargs):
        return {
            "status": "deferred",
            "reason": "collection_too_large",
            "chunk_count": 75000,
            "threshold": 50000,
        }

    def fake_dispatch(_db, bm25_job):
        assert bm25_job.kind == "bm25_rebuild"
        bm25_job.celery_task_id = "task-bm25"
        return "task-bm25"

    monkeypatch.setattr(
        "app.services.worker_ingest.DocumentParserFactory.get_parser",
        lambda _path: FakeParser(),
    )
    monkeypatch.setattr(
        "app.services.worker_ingest.DocumentService", FakeDocumentService
    )
    monkeypatch.setattr("app.services.worker_ingest.rebuild_bm25_artifact", fake_bm25)
    monkeypatch.setattr(
        "app.services.worker_dispatch.dispatch_worker_job", fake_dispatch
    )

    result = run_document_ingest_index(job.id)

    db_session.expire_all()
    bm25_job = (
        db_session.query(WorkerJob)
        .filter(
            WorkerJob.collection_id == collection.id, WorkerJob.kind == "bm25_rebuild"
        )
        .one()
    )
    refreshed_ingest = db_session.query(WorkerJob).filter(WorkerJob.id == job.id).one()
    assert result["bm25"]["status"] == "queued"
    assert result["bm25"]["worker_job_id"] == bm25_job.id
    assert bm25_job.status == "queued"
    assert bm25_job.celery_task_id == "task-bm25"
    assert refreshed_ingest.result["stage"] == "ready"


def test_bm25_rebuild_worker_forces_sidecar_rebuild(db_session, monkeypatch):
    ws = _workspace(db_session, slug="bm25")
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    job = create_worker_job(
        db_session,
        workspace_id=ws.id,
        collection_id=collection.id,
        kind="bm25_rebuild",
    )
    db_session.commit()

    class FakeDocumentService:
        def __init__(self, *args, **kwargs):
            self.vector_db = object()

    async def fake_rebuild_bm25_artifact(**kwargs):
        assert kwargs["force"] is True
        return {"status": "ready", "chunk_count": 75000, "forced": True}

    monkeypatch.setattr("app.services.worker_bm25.DocumentService", FakeDocumentService)
    monkeypatch.setattr(
        "app.services.worker_bm25.rebuild_bm25_artifact",
        fake_rebuild_bm25_artifact,
    )

    result = run_bm25_rebuild(job.id)

    db_session.expire_all()
    refreshed = db_session.query(WorkerJob).filter(WorkerJob.id == job.id).one()
    assert refreshed.status == "completed"
    assert refreshed.progress == 100
    assert refreshed.result["bm25"]["forced"] is True
    assert result["bm25"]["status"] == "ready"


@pytest.mark.asyncio
async def test_bm25_rebuild_skips_above_hard_chunk_limit(
    db_session, monkeypatch
):
    ws = _workspace(db_session, slug="bm25-limit")
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    monkeypatch.setattr(settings, "bm25_rebuild_max_chunks", 10)

    class FakeVectorDb:
        async def get_count(self):
            return 11

        async def get_all_ids(self):
            raise AssertionError("BM25 rebuild should not load oversized collections")

    result = await rebuild_bm25_artifact(
        collection=collection,
        vector_db=FakeVectorDb(),
        force=True,
    )

    assert result == {
        "status": "skipped",
        "reason": "collection_too_large",
        "chunk_count": 11,
        "max_chunks": 10,
        "forced": True,
    }


@pytest.mark.asyncio
async def test_bm25_artifact_envelope_roundtrip_legacy_and_staleness(
    db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))

    ws = _workspace(db_session)
    collection = create_collection(db_session, workspace=ws, name="Docs")
    db_session.commit()

    class FakeVectorDb:
        async def get_count(self):
            return 2

        async def get_all_ids(self):
            return ["c1", "c2"]

        def get_metadatas_for_chunk_ids(self, ids):
            return [{"content": "alpha"}, {"content": "beta"}]

    result = await rebuild_bm25_artifact(collection=collection, vector_db=FakeVectorDb())
    assert result["status"] == "ready"

    retriever, info = load_bm25_artifact(collection, current_chunk_count=2)
    assert retriever is not None
    assert info["status"] == "ready"
    assert info["format_version"] == 1
    assert info["chunk_count"] == 2
    assert info["built_at"]

    # Vector store moved on without a rebuild → stale.
    _, stale_info = load_bm25_artifact(collection, current_chunk_count=5)
    assert stale_info["status"] == "stale"
    assert stale_info["current_chunk_count"] == 5

    # Legacy bare-retriever artifacts remain readable.
    import pickle

    from app.services.retrieval.bm25_retriever import BM25Retriever

    legacy = BM25Retriever()
    legacy.fit(["alpha"], ["c1"], [{"content": "alpha"}])
    get_object_store().write_bytes(bm25_artifact_key(collection), pickle.dumps(legacy))
    legacy_retriever, legacy_info = load_bm25_artifact(collection)
    assert legacy_retriever is not None
    assert legacy_info["status"] == "legacy"

    # Missing artifact is reported, never raised.
    missing_collection = create_collection(db_session, workspace=ws, name="Empty")
    db_session.commit()
    none_retriever, missing_info = load_bm25_artifact(missing_collection)
    assert none_retriever is None
    assert missing_info["status"] == "missing"
