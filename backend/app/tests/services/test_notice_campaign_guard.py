from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models.knowledge_collection import KnowledgeCollectionSource
from app.models.workspace import Workspace
from app.services.knowledge_collections import create_collection
from app.services.notice_campaign_guard import (
    NoticeCampaignGateError,
    assert_notice_disk_capacity,
    verify_notice_collection_gate,
)


def test_disk_capacity_gate_reports_both_volumes(tmp_path):
    report = assert_notice_disk_capacity(
        docker_path=tmp_path,
        deposit_path=tmp_path,
        docker_min_free_ratio=0.0001,
        deposit_min_free_ratio=0.0001,
    )

    assert report["docker"]["free_bytes"] > 0
    assert report["secure_deposit"]["free_bytes"] > 0


def test_disk_capacity_gate_fails_closed_for_missing_path(tmp_path):
    with pytest.raises(NoticeCampaignGateError, match="capacity_path_missing"):
        assert_notice_disk_capacity(
            docker_path=tmp_path / "missing",
            deposit_path=tmp_path,
        )


def test_disk_capacity_gate_enforces_optional_absolute_floor(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.notice_campaign_guard.shutil.disk_usage",
        lambda _path: SimpleNamespace(total=1_000, used=500, free=500),
    )

    with pytest.raises(
        NoticeCampaignGateError,
        match="docker_free_bytes_below_floor:500<501",
    ):
        assert_notice_disk_capacity(
            docker_path=tmp_path,
            deposit_path=tmp_path,
            docker_min_free_ratio=0.25,
            deposit_min_free_ratio=0.15,
            docker_min_free_bytes=501,
        )


def test_disk_capacity_gate_applies_x2_growth_projection(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.notice_campaign_guard.shutil.disk_usage",
        lambda _path: SimpleNamespace(total=1_000, used=500, free=500),
    )

    report = assert_notice_disk_capacity(
        docker_path=tmp_path,
        deposit_path=tmp_path,
        docker_estimated_growth_bytes=100,
        deposit_estimated_growth_bytes=50,
    )

    assert report["docker"]["projected_growth_bytes"] == 200
    assert report["docker"]["projected_free_bytes"] == 300
    assert report["docker"]["projected_free_ratio"] == 0.3
    assert report["secure_deposit"]["projected_growth_bytes"] == 100

    with pytest.raises(
        NoticeCampaignGateError,
        match="docker_projected_free_ratio_below_floor:0.2000<0.2500",
    ):
        assert_notice_disk_capacity(
            docker_path=tmp_path,
            deposit_path=tmp_path,
            docker_estimated_growth_bytes=150,
        )


def _patch_qdrant_gate(
    monkeypatch,
    *,
    total_count: int,
    payloads_by_filter: dict[tuple[str, str], list[dict]],
):
    class FakeClient:
        def get_collection(self, _name):
            return SimpleNamespace(status="green")

    class FakeVectorDB:
        collection_name = "andritz__andritz-notices-techniques-spl-pilot"
        client = FakeClient()

        async def list_payloads(self, *, filters, limit, offset):
            assert limit == 500
            [(field, value)] = filters.items()
            payloads = payloads_by_filter.get((field, str(value)), [])
            return payloads[offset : offset + limit]

    class FakeDocumentService:
        def __init__(self, **_kwargs):
            self.vector_db = FakeVectorDB()

        async def get_document_count(self):
            return total_count

    monkeypatch.setattr(
        "app.services.notice_campaign_guard.get_resolved_settings",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        "app.services.notice_campaign_guard.resolve_vector_db_type",
        lambda _settings: "qdrant",
    )
    monkeypatch.setattr(
        "app.services.notice_campaign_guard.DocumentService",
        FakeDocumentService,
    )


@pytest.mark.asyncio
async def test_collection_gate_checks_wave_parity_and_project_isolation(
    db_session,
    monkeypatch,
):
    workspace = Workspace(id="ws-guard", name="Andritz", slug="andritz")
    db_session.add(workspace)
    db_session.flush()
    collection = create_collection(
        db_session,
        workspace=workspace,
        name="Notices",
        slug="andritz-notices-techniques-spl-pilot",
    )
    collection.status = "ready"
    collection.chunk_count = 501
    source = KnowledgeCollectionSource(
        id="source-guard",
        workspace_id=workspace.id,
        collection_id=collection.id,
        filename="needlepunch__61038__manual.txt",
        normalized_name="needlepunch__61038__manual.txt",
        source_kind="document",
        status="ready",
        chunk_count=501,
        source_metadata={
            "wave_id": "wave-1",
            "project_code": "61038",
            "document_id": "doc-61038",
        },
    )
    db_session.add(source)
    db_session.commit()

    payloads = {
        ("document_id", "doc-61038"): [
            {"document_id": "doc-61038", "project_code": "61038"} for _index in range(501)
        ],
        ("project_code", "61038"): [
            {"document_id": f"doc-{index}", "project_code": "61038"} for index in range(501)
        ],
    }
    _patch_qdrant_gate(
        monkeypatch,
        total_count=501,
        payloads_by_filter=payloads,
    )

    report = await verify_notice_collection_gate(
        db_session,
        workspace=workspace,
        collection=collection,
        document_names=[source.normalized_name],
        wave_id="wave-1",
    )

    assert report["qdrant_status"] == "green"
    assert report["sql_chunk_count"] == report["qdrant_chunk_count"] == 501
    assert report["sources"][0]["document_id"] == "doc-61038"
    assert report["sources"][0]["qdrant_chunk_count"] == 501
    assert report["project_filter_counts"] == {"61038": 501}

    payloads[("project_code", "61038")] = []
    with pytest.raises(NoticeCampaignGateError, match="project_filter_empty:61038"):
        await verify_notice_collection_gate(
            db_session,
            workspace=workspace,
            collection=collection,
            document_names=[source.normalized_name],
            wave_id="wave-1",
        )


@pytest.mark.asyncio
async def test_collection_gate_rejects_zero_chunk_source(db_session):
    workspace = Workspace(id="ws-guard-zero", name="Andritz", slug="andritz-zero")
    db_session.add(workspace)
    db_session.flush()
    collection = create_collection(db_session, workspace=workspace, name="Notices")
    collection.status = "ready"
    source = KnowledgeCollectionSource(
        id="source-guard-zero",
        workspace_id=workspace.id,
        collection_id=collection.id,
        filename="zero.txt",
        normalized_name="zero.txt",
        source_kind="document",
        status="ready",
        chunk_count=0,
        source_metadata={"wave_id": "wave-zero", "project_code": "61038"},
    )
    db_session.add(source)
    db_session.commit()

    with pytest.raises(NoticeCampaignGateError, match="zero_chunks"):
        await verify_notice_collection_gate(
            db_session,
            workspace=workspace,
            collection=collection,
            document_names=[source.normalized_name],
            wave_id="wave-zero",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("suffix", "document_payloads", "expected_error"),
    [
        (
            "drift",
            [{"document_id": "doc-drift", "project_code": "61038"}],
            "wave_source_chunk_drift:drift.txt:2!=1",
        ),
        (
            "document-leak",
            [
                {"document_id": "another-doc", "project_code": "61038"},
                {"document_id": "doc-drift", "project_code": "61038"},
            ],
            "document_filter_leak:doc-drift->another-doc",
        ),
        (
            "project-leak",
            [
                {"document_id": "doc-drift", "project_code": "61009"},
                {"document_id": "doc-drift", "project_code": "61038"},
            ],
            "document_project_leak:doc-drift:61038->61009",
        ),
    ],
)
async def test_collection_gate_rejects_invalid_per_source_qdrant_payloads(
    db_session,
    monkeypatch,
    suffix,
    document_payloads,
    expected_error,
):
    workspace = Workspace(
        id=f"ws-guard-{suffix}",
        name="Andritz",
        slug=f"andritz-{suffix}",
    )
    db_session.add(workspace)
    db_session.flush()
    collection = create_collection(db_session, workspace=workspace, name="Notices")
    collection.status = "ready"
    collection.chunk_count = 2
    source = KnowledgeCollectionSource(
        id="source-guard-drift",
        workspace_id=workspace.id,
        collection_id=collection.id,
        filename="drift.txt",
        normalized_name="drift.txt",
        source_kind="document",
        status="ready",
        chunk_count=2,
        source_metadata={
            "wave_id": "wave-drift",
            "project_code": "61038",
            "document_id": "doc-drift",
        },
    )
    db_session.add(source)
    db_session.commit()
    _patch_qdrant_gate(
        monkeypatch,
        total_count=2,
        payloads_by_filter={
            ("document_id", "doc-drift"): document_payloads,
        },
    )

    with pytest.raises(NoticeCampaignGateError, match=expected_error):
        await verify_notice_collection_gate(
            db_session,
            workspace=workspace,
            collection=collection,
            document_names=[source.normalized_name],
            wave_id="wave-drift",
        )


@pytest.mark.asyncio
async def test_collection_gate_validates_deduplicated_source_canonical(
    db_session,
    monkeypatch,
):
    workspace = Workspace(id="ws-guard-dedup", name="Andritz", slug="andritz-dedup")
    db_session.add(workspace)
    db_session.flush()
    collection = create_collection(db_session, workspace=workspace, name="Notices")
    collection.status = "ready"
    collection.chunk_count = 2
    canonical = KnowledgeCollectionSource(
        id="source-canonical",
        workspace_id=workspace.id,
        collection_id=collection.id,
        filename="canonical.txt",
        normalized_name="canonical.txt",
        source_kind="document",
        status="ready",
        chunk_count=2,
        source_metadata={"project_code": "61038", "document_id": "doc-canonical"},
    )
    duplicate = KnowledgeCollectionSource(
        id="source-duplicate",
        workspace_id=workspace.id,
        collection_id=collection.id,
        filename="copy.txt",
        normalized_name="copy.txt",
        source_kind="document",
        status="deduplicated",
        chunk_count=0,
        source_metadata={
            "wave_id": "wave-dedup",
            "project_code": "61038",
            "duplicate_of": "canonical.txt",
        },
    )
    db_session.add_all([canonical, duplicate])
    db_session.commit()
    canonical_payloads = [
        {"document_id": "doc-canonical", "project_code": "61038"},
        {"document_id": "doc-canonical", "project_code": "61038"},
    ]
    _patch_qdrant_gate(
        monkeypatch,
        total_count=2,
        payloads_by_filter={
            ("document_id", "doc-canonical"): canonical_payloads,
            ("project_code", "61038"): canonical_payloads,
        },
    )

    report = await verify_notice_collection_gate(
        db_session,
        workspace=workspace,
        collection=collection,
        document_names=[duplicate.normalized_name],
        wave_id="wave-dedup",
    )

    assert report["sources"] == [
        {
            "name": "copy.txt",
            "status": "deduplicated",
            "chunk_count": 0,
            "project_code": "61038",
            "duplicate_of": "canonical.txt",
            "canonical_document_id": "doc-canonical",
            "canonical_chunk_count": 2,
            "canonical_qdrant_chunk_count": 2,
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("canonical_status", "canonical_project", "canonical_chunks", "expected_error"),
    [
        (None, "61038", 2, "source_canonical_missing"),
        ("error", "61038", 2, "canonical_not_terminal"),
        ("ready", "61009", 2, "project_mismatch"),
        ("ready", "61038", 0, "canonical_zero_chunks"),
    ],
)
async def test_collection_gate_rejects_invalid_dedup_canonical(
    db_session,
    monkeypatch,
    canonical_status,
    canonical_project,
    canonical_chunks,
    expected_error,
):
    suffix = expected_error.replace("_", "-")
    workspace = Workspace(
        id=f"ws-guard-{suffix}",
        name="Andritz",
        slug=f"andritz-{suffix}",
    )
    db_session.add(workspace)
    db_session.flush()
    collection = create_collection(db_session, workspace=workspace, name="Notices")
    collection.status = "ready"
    collection.chunk_count = 2
    duplicate = KnowledgeCollectionSource(
        id=f"duplicate-{suffix}",
        workspace_id=workspace.id,
        collection_id=collection.id,
        filename="copy.txt",
        normalized_name="copy.txt",
        source_kind="document",
        status="deduplicated",
        chunk_count=0,
        source_metadata={
            "wave_id": "wave-dedup-invalid",
            "project_code": "61038",
            "duplicate_of": "canonical.txt",
        },
    )
    db_session.add(duplicate)
    if canonical_status is not None:
        db_session.add(
            KnowledgeCollectionSource(
                id=f"canonical-{suffix}",
                workspace_id=workspace.id,
                collection_id=collection.id,
                filename="canonical.txt",
                normalized_name="canonical.txt",
                source_kind="document",
                status=canonical_status,
                chunk_count=canonical_chunks,
                source_metadata={
                    "project_code": canonical_project,
                    "document_id": "doc-canonical",
                },
            )
        )
    db_session.commit()
    _patch_qdrant_gate(monkeypatch, total_count=2, payloads_by_filter={})

    with pytest.raises(NoticeCampaignGateError, match=expected_error):
        await verify_notice_collection_gate(
            db_session,
            workspace=workspace,
            collection=collection,
            document_names=[duplicate.normalized_name],
            wave_id="wave-dedup-invalid",
        )


@pytest.mark.asyncio
async def test_collection_gate_rejects_dedup_canonical_without_qdrant_chunks(
    db_session,
    monkeypatch,
):
    workspace = Workspace(
        id="ws-guard-dedup-empty",
        name="Andritz",
        slug="andritz-dedup-empty",
    )
    db_session.add(workspace)
    db_session.flush()
    collection = create_collection(db_session, workspace=workspace, name="Notices")
    collection.status = "ready"
    collection.chunk_count = 2
    canonical = KnowledgeCollectionSource(
        id="canonical-empty",
        workspace_id=workspace.id,
        collection_id=collection.id,
        filename="canonical.txt",
        normalized_name="canonical.txt",
        source_kind="document",
        status="ready",
        chunk_count=2,
        source_metadata={"project_code": "61038", "document_id": "doc-canonical"},
    )
    duplicate = KnowledgeCollectionSource(
        id="duplicate-empty",
        workspace_id=workspace.id,
        collection_id=collection.id,
        filename="copy.txt",
        normalized_name="copy.txt",
        source_kind="document",
        status="deduplicated",
        chunk_count=0,
        source_metadata={
            "wave_id": "wave-dedup-empty",
            "project_code": "61038",
            "duplicate_of": "canonical.txt",
        },
    )
    db_session.add_all([canonical, duplicate])
    db_session.commit()
    _patch_qdrant_gate(monkeypatch, total_count=2, payloads_by_filter={})

    with pytest.raises(
        NoticeCampaignGateError,
        match="canonical_chunk_drift:copy.txt:2!=0",
    ):
        await verify_notice_collection_gate(
            db_session,
            workspace=workspace,
            collection=collection,
            document_names=[duplicate.normalized_name],
            wave_id="wave-dedup-empty",
        )
