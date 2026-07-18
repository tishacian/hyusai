from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.models.knowledge_collection import KnowledgeCollectionSource
from app.models.knowledge_document_fact import KnowledgeDocumentFact
from app.models.knowledge_table_fact import KnowledgeTableFact
from app.models.secure_deposit import DepositAccessLink, DepositFile
from app.models.user import User
from app.models.workspace import Workspace
from app.services.knowledge_collections import create_collection, create_worker_job
from app.services.notice_campaign_guard import NoticeCampaignGateError
from app.services.notice_campaign_recovery import rollback_rejected_notice_wave
from app.services.object_store import get_object_store
from app.services.rag.bm25_store import bm25_artifact_key


def _completed_wave(db_session):
    workspace = Workspace(id="ws-recovery", name="Andritz", slug="andritz-recovery")
    user = User(
        id="user-recovery",
        username="reviewer-recovery",
        email="reviewer-recovery@example.test",
    )
    db_session.add_all([workspace, user])
    db_session.flush()
    collection = create_collection(
        db_session,
        workspace=workspace,
        name="Notices",
        slug="andritz-notices-techniques-spl-pilot",
    )
    collection.status = "ready"
    collection.document_names = ["baseline.pdf", "wave.pdf"]
    collection.document_count = 2
    collection.chunk_count = 5
    access = DepositAccessLink(
        id="access-recovery",
        workspace_id=workspace.id,
        created_by_user_id=user.id,
        label="Needlepunch",
        access_id="access-recovery-token",
        password_hash="hashed",
    )
    deposit = DepositFile(
        id="deposit-recovery",
        workspace_id=workspace.id,
        access_link_id=access.id,
        filename=(
            "Notices_Techniques_Needlepunch/60000-69999/61038 Project/wave.pdf"
        ),
        object_key="secure_deposit/ws-recovery/wave.pdf",
        size_bytes=42,
        sha256="a" * 64,
        status="promoted",
        promoted_at=datetime.utcnow(),
        promoted_by_user_id=user.id,
        promoted_collection_slug=collection.slug,
        promotion_result={"indexing_status": "indexed"},
    )
    db_session.add_all([access, deposit])
    db_session.flush()
    source = KnowledgeCollectionSource(
        id="source-recovery",
        workspace_id=workspace.id,
        collection_id=collection.id,
        filename="wave.pdf",
        normalized_name="wave.pdf",
        source_kind="document",
        extension="pdf",
        origin="secure_deposit",
        status="ready",
        chunk_count=2,
        source_metadata={
            "wave_id": "wave-recovery-001",
            "project_code": "61038",
            "document_id": "document-wave",
            "source_deposit_file_id": deposit.id,
        },
    )
    db_session.add(source)
    job = create_worker_job(
        db_session,
        workspace_id=workspace.id,
        collection_id=collection.id,
        kind="document_ingest_index",
    )
    job.status = "completed"
    job.progress = 100
    job.result = {
        "ingest_options": {
            "mode": "incremental",
            "wave_id": "wave-recovery-001",
            "document_names": ["wave.pdf"],
            "source_profile": "needlepunch",
        }
    }
    deposit.worker_job_id = job.id
    db_session.add_all(
        [
            KnowledgeTableFact(
                id="table-fact-recovery",
                workspace_id=workspace.id,
                collection_id=collection.id,
                collection_slug=collection.slug,
                document_id="document-wave",
                document_filename="wave.pdf",
                semantic_type="inventory",
                content="wave table fact",
            ),
            KnowledgeDocumentFact(
                id="document-fact-recovery",
                workspace_id=workspace.id,
                collection_id=collection.id,
                collection_slug=collection.slug,
                document_id="document-wave",
                document_filename="wave.pdf",
                semantic_type="statement",
                content="wave document fact",
            ),
        ]
    )
    db_session.commit()
    return workspace, collection, job, source, deposit


@pytest.mark.asyncio
async def test_postflight_recovery_restores_exact_baseline(db_session, monkeypatch):
    workspace, collection, job, source, deposit = _completed_wave(db_session)

    class FakeDocumentService:
        def __init__(self, **_kwargs):
            self.vector_db = SimpleNamespace(
                client=SimpleNamespace(
                    get_collection=lambda _name: SimpleNamespace(status="green")
                ),
                collection_name="andritz__notices",
                list_payloads=self._list_payloads,
            )

        @staticmethod
        async def _list_payloads(**_kwargs):
            return []

        async def delete_by_metadata(self, filters):
            assert filters == {"wave_id": "wave-recovery-001"}
            return True

        async def get_document_count(self):
            return 3

    monkeypatch.setattr(
        "app.services.notice_campaign_recovery.get_resolved_settings",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        "app.services.notice_campaign_recovery.resolve_vector_db_type",
        lambda _settings: "qdrant",
    )
    monkeypatch.setattr(
        "app.services.notice_campaign_recovery.DocumentService",
        FakeDocumentService,
    )

    async def fake_verify_baseline(_db, **kwargs):
        assert kwargs["collection"].status == "ready"
        return {"collection_status": "ready", "qdrant_chunk_count": 3}

    monkeypatch.setattr(
        "app.services.notice_campaign_recovery.verify_notice_collection_gate",
        fake_verify_baseline,
    )
    store = get_object_store()
    bm25_key = bm25_artifact_key(collection, store=store)
    store.write_bytes(bm25_key, b"stale wave artifact")

    report = await rollback_rejected_notice_wave(
        db_session,
        workspace=workspace,
        collection=collection,
        job=job,
        document_names=["wave.pdf"],
        wave_id="wave-recovery-001",
        reason="project_filter_leak",
        actor="reviewer-recovery@example.test",
        baseline_document_names=["baseline.pdf"],
        baseline_document_count=1,
        baseline_chunk_count=3,
    )

    db_session.refresh(collection)
    db_session.refresh(job)
    db_session.refresh(source)
    db_session.refresh(deposit)
    assert report["status"] == "rolled_back"
    assert collection.status == "ready"
    assert collection.last_error is None
    assert collection.document_names == ["baseline.pdf"]
    assert collection.document_count == 1
    assert collection.chunk_count == 3
    assert job.status == "failed"
    assert job.result["stage"] == "postflight_rolled_back"
    assert source.status == "error"
    assert source.chunk_count == 0
    assert deposit.status == "received"
    assert deposit.promoted_at is None
    assert deposit.promoted_collection_slug is None
    assert not store.exists(bm25_key)
    assert db_session.query(KnowledgeTableFact).count() == 0
    assert db_session.query(KnowledgeDocumentFact).count() == 0


@pytest.mark.asyncio
async def test_postflight_recovery_quarantines_when_delete_is_unconfirmed(
    db_session,
    monkeypatch,
):
    workspace, collection, job, source, deposit = _completed_wave(db_session)

    class FakeDocumentService:
        def __init__(self, **_kwargs):
            self.vector_db = SimpleNamespace(
                client=SimpleNamespace(
                    get_collection=lambda _name: SimpleNamespace(status="green")
                ),
                collection_name="andritz__notices",
                list_payloads=self._list_payloads,
            )

        @staticmethod
        async def _list_payloads(**_kwargs):
            return []

        async def delete_by_metadata(self, _filters):
            return False

        async def get_document_count(self):
            return 5

    monkeypatch.setattr(
        "app.services.notice_campaign_recovery.get_resolved_settings",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        "app.services.notice_campaign_recovery.resolve_vector_db_type",
        lambda _settings: "qdrant",
    )
    monkeypatch.setattr(
        "app.services.notice_campaign_recovery.DocumentService",
        FakeDocumentService,
    )

    report = await rollback_rejected_notice_wave(
        db_session,
        workspace=workspace,
        collection=collection,
        job=job,
        document_names=["wave.pdf"],
        wave_id="wave-recovery-001",
        reason="postgres_qdrant_chunk_drift",
        actor="reviewer-recovery@example.test",
        baseline_document_names=["baseline.pdf"],
        baseline_document_count=1,
        baseline_chunk_count=3,
    )

    db_session.refresh(collection)
    db_session.refresh(job)
    db_session.refresh(source)
    db_session.refresh(deposit)
    assert report["status"] == "quarantined"
    assert report["wave_delete_confirmed"] is False
    assert collection.status == "error"
    assert "rollback unconfirmed" in collection.last_error
    assert job.status == "failed"
    assert job.result["stage"] == "postflight_rollback_unconfirmed"
    # No SQL ledger mutation is claimed when vector cleanup is unproven.
    assert source.status == "ready"
    assert source.chunk_count == 2
    assert deposit.status == "promoted"


@pytest.mark.asyncio
async def test_postflight_recovery_rejects_caller_job_ledger_scope_mismatch(
    db_session,
):
    workspace, collection, job, _source, _deposit = _completed_wave(db_session)
    options = dict(job.result["ingest_options"])
    options["document_names"] = ["wave.pdf", "untracked.pdf"]
    job.result = {**dict(job.result or {}), "ingest_options": options}
    db_session.commit()

    report = await rollback_rejected_notice_wave(
        db_session,
        workspace=workspace,
        collection=collection,
        job=job,
        document_names=["wave.pdf"],
        wave_id="wave-recovery-001",
        reason="document_filter_leak",
        actor="reviewer-recovery@example.test",
        baseline_document_names=["baseline.pdf"],
        baseline_document_count=1,
        baseline_chunk_count=3,
    )

    db_session.refresh(collection)
    db_session.refresh(job)
    assert report["status"] == "quarantined"
    assert report["error"] == "postflight_recovery_scope_mismatch"
    assert collection.status == "error"
    assert job.status == "failed"


@pytest.mark.asyncio
async def test_postflight_recovery_keeps_quarantine_when_baseline_is_invalid(
    db_session,
    monkeypatch,
):
    workspace, collection, job, source, _deposit = _completed_wave(db_session)

    class FakeDocumentService:
        def __init__(self, **_kwargs):
            self.vector_db = SimpleNamespace(
                client=SimpleNamespace(
                    get_collection=lambda _name: SimpleNamespace(status="green")
                ),
                collection_name="andritz__notices",
                list_payloads=self._list_payloads,
            )

        @staticmethod
        async def _list_payloads(**_kwargs):
            return []

        async def delete_by_metadata(self, _filters):
            return True

        async def get_document_count(self):
            return 3

    async def reject_baseline(_db, **_kwargs):
        raise NoticeCampaignGateError("baseline_source_chunk_drift")

    monkeypatch.setattr(
        "app.services.notice_campaign_recovery.get_resolved_settings",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        "app.services.notice_campaign_recovery.resolve_vector_db_type",
        lambda _settings: "qdrant",
    )
    monkeypatch.setattr(
        "app.services.notice_campaign_recovery.DocumentService",
        FakeDocumentService,
    )
    monkeypatch.setattr(
        "app.services.notice_campaign_recovery.verify_notice_collection_gate",
        reject_baseline,
    )

    report = await rollback_rejected_notice_wave(
        db_session,
        workspace=workspace,
        collection=collection,
        job=job,
        document_names=["wave.pdf"],
        wave_id="wave-recovery-001",
        reason="already_known_invalid",
        actor="reviewer-recovery@example.test",
        baseline_document_names=["baseline.pdf"],
        baseline_document_count=1,
        baseline_chunk_count=3,
        baseline_validation_names=["baseline.pdf"],
    )

    db_session.refresh(collection)
    db_session.refresh(source)
    assert report["status"] == "quarantined"
    assert "baseline_source_chunk_drift" in report["error"]
    assert collection.status == "error"
    # SQL cleanup is not claimed when the restored baseline cannot be proven.
    assert source.status == "ready"
