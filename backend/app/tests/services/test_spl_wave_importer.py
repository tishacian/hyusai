from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.services.secure_deposit import (
    _read_supported_archive_documents,
    archive_document_namespace,
)
from app.services.spl_wave_importer import (
    WaveLimits,
    build_v2_wave_plans,
    build_v3_archive_wave_plan,
    build_v3_wave_plans,
    build_wave_plan,
    execute_wave_plan,
    inspect_archive_deposit_file,
    list_remaining_spl_archive_filenames,
)


def test_read_supported_archive_documents_truncates_on_limit(tmp_path: Path):
    archive_path = tmp_path / "sample.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for index in range(5):
            archive.writestr(f"docs/manual-{index:02d}.txt", f"manual {index}")

    documents, stats = _read_supported_archive_documents(
        archive_path,
        max_files=2,
        on_limit="truncate",
    )
    assert len(documents) == 2
    assert stats["truncated_files"] == 3


def test_read_supported_archive_documents_can_scan_without_content(tmp_path: Path):
    archive_path = tmp_path / "sample.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("docs/manual.txt", "manual body")

    documents, stats = _read_supported_archive_documents(
        archive_path,
        include_content=False,
    )

    assert len(documents) == 1
    assert documents[0]["filename"] == "docs__manual.txt"
    assert "content" not in documents[0]
    assert stats["document_count"] == 1


def test_read_supported_archive_documents_truncates_unreadable_members(tmp_path: Path):
    archive_path = tmp_path / "sample.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("docs/bad.pdf", "bad body")
        archive.writestr("docs/good.pdf", "good body")
    with zipfile.ZipFile(archive_path) as archive:
        bad_offset = archive.getinfo("docs/bad.pdf").header_offset
    with archive_path.open("r+b") as archive_file:
        archive_file.seek(bad_offset)
        archive_file.write(b"BAD!")

    documents, stats = _read_supported_archive_documents(
        archive_path,
        on_limit="truncate",
    )

    assert [document["archive_path"] for document in documents] == ["docs/good.pdf"]
    assert stats["document_count"] == 1
    assert stats["truncated_files"] == 1
    assert stats["skipped_read_error_count"] == 1
    assert stats["skipped_read_errors"][0]["archive_path"] == "docs/bad.pdf"


def test_read_supported_archive_documents_bounds_namespaced_document_names(tmp_path: Path):
    archive_path = tmp_path / "sample.zip"
    deep_name = "/".join(
        [
            "AKI300",
            "files",
            "section_IV",
            "Dryer-unit",
            "sub-section_4",
            "IV.1. Dryer manual",
            "BID520541 Hydro-Dry System",
            "3. Purchased Components",
            "Section 2 - Burners",
            "50S1013376-Docu-English",
            "5. Suppliers documentatio",
            "Actuator_ Reversing - SQM5 Document No. 7815_en.pdf",
        ]
    )
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(deep_name, "manual body")

    documents, stats = _read_supported_archive_documents(
        archive_path,
        document_namespace="A__AKI300",
        include_content=False,
    )

    assert stats["document_count"] == 1
    assert len(documents[0]["filename"]) <= 220
    assert documents[0]["filename"].startswith("A__AKI300__")
    assert documents[0]["filename"].endswith(".pdf")
    assert "__" in documents[0]["filename"]


def test_read_supported_archive_documents_errors_on_limit(tmp_path: Path):
    archive_path = tmp_path / "sample.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for index in range(3):
            archive.writestr(f"docs/manual-{index:02d}.txt", f"manual {index}")

    with pytest.raises(HTTPException) as exc:
        _read_supported_archive_documents(archive_path, max_files=1, on_limit="error")
    assert exc.value.status_code == 413


def test_build_wave_plan_dry_run(db_session, monkeypatch, tmp_path):
    from app.models.secure_deposit import DepositFile
    from app.models.workspace import Workspace
    from app.services.secure_deposit import create_link

    workspace = Workspace(id="ws-andritz", name="Andritz", slug="andritz")
    user = __import__("app.models.user", fromlist=["User"]).User(
        id="user-1",
        username="thib",
        email="operator@example.test",
    )
    db_session.add_all([workspace, user])
    db_session.flush()
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="SPL wave test",
        expires_at=None,
        max_file_size_mb=1024,
        allowed_extensions=["zip"],
    )

    archive_path = tmp_path / "ACO140.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("ACO140/manual.txt", "operating manual")

    deposit = DepositFile(
        workspace_id=workspace.id,
        access_link_id=link.id,
        filename="Notices_Techniques_SPL/A/ACO140.zip",
        object_key="obj/aco140",
        status="received",
        size_bytes=archive_path.stat().st_size,
        sha256="abc123",
    )
    db_session.add(deposit)
    db_session.commit()

    monkeypatch.setattr(
        "app.services.spl_wave_importer.staged_file_path",
        lambda _file: archive_path,
    )

    plan = build_wave_plan(
        db_session,
        workspace=workspace,
        collection_slug="andritz-notices-techniques-spl-pilot",
        archive_filenames=("Notices_Techniques_SPL/A/ACO140.zip",),
        dry_run=True,
    )
    assert plan.total_documents == 1
    assert plan.archives[0].promotable is True

    inspected = inspect_archive_deposit_file(deposit)
    assert inspected.supported_files == 1


def test_build_v2_wave_plans_splits_akk200(db_session, monkeypatch, tmp_path):
    from app.models.secure_deposit import DepositFile
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.services.secure_deposit import create_link

    workspace = Workspace(id="ws-andritz", name="Andritz", slug="andritz")
    user = User(id="user-1", username="thib", email="operator@example.test")
    db_session.add_all([workspace, user])
    db_session.flush()
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="SPL wave test",
        expires_at=None,
        max_file_size_mb=1024,
        allowed_extensions=["zip"],
    )

    small = tmp_path / "small.zip"
    with zipfile.ZipFile(small, "w") as archive:
        archive.writestr("ACO150/manual.txt", "manual")
    large = tmp_path / "large.zip"
    with zipfile.ZipFile(large, "w") as archive:
        for index in range(5):
            archive.writestr(f"AKK200/doc-{index:02d}.txt", f"doc {index}")

    d_small = DepositFile(
        workspace_id=workspace.id,
        access_link_id=link.id,
        filename="Notices_Techniques_SPL/A/ACO150.zip",
        object_key="obj-small",
        status="received",
        size_bytes=small.stat().st_size,
        sha256="hash-small",
    )
    d_large = DepositFile(
        workspace_id=workspace.id,
        access_link_id=link.id,
        filename="Notices_Techniques_SPL/A/AKK200.zip",
        object_key="obj-large",
        status="received",
        size_bytes=large.stat().st_size,
        sha256="hash-large",
    )
    db_session.add_all([d_small, d_large])
    db_session.commit()

    def _fake_staged(deposit_file):
        if deposit_file.id == d_small.id:
            return small
        if deposit_file.id == d_large.id:
            return large
        raise FileNotFoundError(deposit_file.filename)

    monkeypatch.setattr("app.services.spl_wave_importer.staged_file_path", _fake_staged)

    plans = build_v2_wave_plans(
        db_session,
        workspace=workspace,
        collection_slug="andritz-notices-techniques-spl-pilot",
        projects=("ACO150", "AKK200"),
        dry_run=True,
    )
    assert len(plans) == 2
    assert plans[0].wave_id == "spl_v2_1"
    assert plans[1].wave_id == "spl_v2_2"


def test_build_wave_plan_allows_solo_archive_over_wave_doc_limit(db_session, monkeypatch, tmp_path):
    from app.models.secure_deposit import DepositFile
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.services.secure_deposit import create_link

    workspace = Workspace(id="ws-andritz", name="Andritz", slug="andritz")
    user = User(id="user-1", username="thib", email="operator@example.test")
    db_session.add_all([workspace, user])
    db_session.flush()
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="SPL wave test",
        expires_at=None,
        max_file_size_mb=1024,
        allowed_extensions=["zip"],
    )
    archive_path = tmp_path / "big.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for index in range(10):
            archive.writestr(f"docs/manual-{index:02d}.txt", f"manual {index}")
    deposit = DepositFile(
        workspace_id=workspace.id,
        access_link_id=link.id,
        filename="Notices_Techniques_SPL/A/BIG900.zip",
        object_key="obj-big",
        status="received",
        size_bytes=archive_path.stat().st_size,
        sha256="abc",
    )
    db_session.add(deposit)
    db_session.commit()
    monkeypatch.setattr("app.services.spl_wave_importer.staged_file_path", lambda _file: archive_path)

    limits = WaveLimits.v3()
    limits = WaveLimits(
        max_archive_mb=limits.max_archive_mb,
        max_files_per_archive=limits.max_files_per_archive,
        max_documents_per_wave=5,
    )
    plan = build_wave_plan(
        db_session,
        workspace=workspace,
        collection_slug="andritz-notices-techniques-spl-pilot",
        archive_filenames=("Notices_Techniques_SPL/A/BIG900.zip",),
        dry_run=True,
        limits=limits,
    )
    assert plan.total_documents == 10
    assert not any(item.filename == "__wave_limit__" for item in plan.archives)


def test_wave_limits_v3():
    limits = WaveLimits.v3()
    assert limits.max_documents_per_wave == 500
    assert limits.max_files_per_archive == 800


def test_build_v3_wave_plans_isolates_large_archive(db_session, monkeypatch, tmp_path):
    from app.models.secure_deposit import DepositFile
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.services.secure_deposit import create_link
    from app.services.spl_wave_importer import record_wave_ledger

    workspace = Workspace(id="ws-andritz", name="Andritz", slug="andritz")
    user = User(id="user-1", username="thib", email="operator@example.test")
    db_session.add_all([workspace, user])
    db_session.flush()
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="SPL wave test",
        expires_at=None,
        max_file_size_mb=10240,
        allowed_extensions=["zip"],
    )

    small = tmp_path / "small.zip"
    with zipfile.ZipFile(small, "w") as archive:
        archive.writestr("AVA100/manual.txt", "manual")
    large = tmp_path / "large.zip"
    with zipfile.ZipFile(large, "w") as archive:
        for index in range(3):
            archive.writestr(f"ASY100/doc-{index:02d}.txt", f"doc {index}")

    d_small = DepositFile(
        workspace_id=workspace.id,
        access_link_id=link.id,
        filename="Notices_Techniques_SPL/A/AVA100.zip",
        object_key="obj-small",
        status="received",
        size_bytes=small.stat().st_size,
        sha256="hash-small",
    )
    d_large = DepositFile(
        workspace_id=workspace.id,
        access_link_id=link.id,
        filename="Notices_Techniques_SPL/A/Manual_ASY100.zip",
        object_key="obj-large",
        status="received",
        size_bytes=int(900 * 1024 * 1024),
        sha256="hash-large",
    )
    db_session.add_all([d_small, d_large])
    db_session.commit()

    def _fake_staged(deposit_file):
        if deposit_file.id == d_small.id:
            return small
        if deposit_file.id == d_large.id:
            return large
        raise FileNotFoundError(deposit_file.filename)

    monkeypatch.setattr("app.services.spl_wave_importer.staged_file_path", _fake_staged)

    remaining = list_remaining_spl_archive_filenames(
        db_session,
        workspace=workspace,
        collection_slug="andritz-notices-techniques-spl-pilot",
    )
    assert set(remaining) == {
        "Notices_Techniques_SPL/A/AVA100.zip",
        "Notices_Techniques_SPL/A/Manual_ASY100.zip",
    }

    plans = build_v3_wave_plans(
        db_session,
        workspace=workspace,
        collection_slug="andritz-notices-techniques-spl-pilot",
        dry_run=True,
        folder="A",
    )
    assert len(plans) == 2
    assert plans[0].wave_id == "spl_v3_1"
    assert "ASY100" in plans[0].archives[0].filename
    assert plans[1].wave_id == "spl_v3_2"
    assert plans[1].archives[0].filename.endswith("AVA100.zip")

    record_wave_ledger(
        db_session,
        workspace=workspace,
        collection_slug="andritz-notices-techniques-spl-pilot",
        wave_id="spl_v3_1",
        filenames=["Notices_Techniques_SPL/A/Manual_ASY100.zip"],
        job_id="job-1",
        new_document_count=3,
    )
    db_session.commit()
    plans_after = build_v3_wave_plans(
        db_session,
        workspace=workspace,
        collection_slug="andritz-notices-techniques-spl-pilot",
        dry_run=True,
        folder="A",
    )
    assert len(plans_after) == 1
    assert plans_after[0].archives[0].filename.endswith("AVA100.zip")
    assert "Manual_ASY100.zip" not in {
        item.filename for plan in plans_after for item in plan.archives
    }


def test_build_v3_archive_wave_plan_targets_exact_archive(db_session, monkeypatch, tmp_path):
    from app.models.secure_deposit import DepositFile
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.services.secure_deposit import create_link
    from app.services.spl_wave_importer import record_wave_ledger

    workspace = Workspace(id="ws-andritz", name="Andritz", slug="andritz")
    user = User(id="user-1", username="thib", email="operator@example.test")
    db_session.add_all([workspace, user])
    db_session.flush()
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="SPL archive target test",
        expires_at=None,
        max_file_size_mb=10240,
        allowed_extensions=["zip"],
    )

    acj = tmp_path / "Manual_ACJ200-revA.zip"
    with zipfile.ZipFile(acj, "w") as archive:
        archive.writestr("acj/manual.txt", "acj")
    bhx = tmp_path / "Manual_BHX100_revD.zip"
    with zipfile.ZipFile(bhx, "w") as archive:
        archive.writestr("bhx/manual.txt", "bhx")

    d_acj = DepositFile(
        workspace_id=workspace.id,
        access_link_id=link.id,
        filename="Notices_Techniques_SPL/A/Manual_ACJ200-revA.zip",
        object_key="obj-acj",
        status="received",
        size_bytes=acj.stat().st_size,
        sha256="hash-acj",
    )
    d_bhx = DepositFile(
        workspace_id=workspace.id,
        access_link_id=link.id,
        filename="Notices_Techniques_SPL/B/Manual_BHX100_revD.zip",
        object_key="obj-bhx",
        status="received",
        size_bytes=bhx.stat().st_size,
        sha256="hash-bhx",
    )
    db_session.add_all([d_acj, d_bhx])
    db_session.commit()

    def _fake_staged(deposit_file):
        if deposit_file.id == d_acj.id:
            return acj
        if deposit_file.id == d_bhx.id:
            return bhx
        raise FileNotFoundError(deposit_file.filename)

    monkeypatch.setattr("app.services.spl_wave_importer.staged_file_path", _fake_staged)

    target = "Notices_Techniques_SPL/B/Manual_BHX100_revD.zip"
    plan = build_v3_archive_wave_plan(
        db_session,
        workspace=workspace,
        collection_slug="andritz-notices-techniques-spl-pilot",
        archive_filenames=[target],
        dry_run=True,
    )

    assert plan.wave_id == "spl_v3_archive_manual_bhx100_revd"
    assert [item.filename for item in plan.archives] == [target]
    assert plan.total_documents == 1

    record_wave_ledger(
        db_session,
        workspace=workspace,
        collection_slug="andritz-notices-techniques-spl-pilot",
        wave_id=plan.wave_id,
        filenames=[target],
        job_id="job-bhx",
        new_document_count=1,
    )
    db_session.commit()

    skipped = build_v3_archive_wave_plan(
        db_session,
        workspace=workspace,
        collection_slug="andritz-notices-techniques-spl-pilot",
        archive_filenames=[target],
        dry_run=True,
    )
    assert skipped.archives == []
    assert skipped.skipped_ledger == [target]


def test_v3_archive_wave_prefers_received_duplicate_over_rejected(db_session, monkeypatch, tmp_path):
    from app.core.config import settings
    from app.models.secure_deposit import DepositFile
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.services.secure_deposit import create_link

    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(
        "app.services.spl_wave_importer.dispatch_worker_job",
        lambda _db, job: setattr(job, "celery_task_id", "fake-task-id") or "fake-task-id",
    )

    workspace = Workspace(id="ws-andritz", name="Andritz", slug="andritz")
    user = User(id="user-1", username="thib", email="operator@example.test")
    db_session.add_all([workspace, user])
    db_session.flush()
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="SPL duplicate test",
        expires_at=None,
        max_file_size_mb=10240,
        allowed_extensions=["zip"],
    )

    archive_path = tmp_path / "Manual_BIO100 rev A.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("bio/manual.txt", "bio")

    filename = "Notices_Techniques_SPL/B/Manual_BIO100 rev A.zip"
    received = DepositFile(
        workspace_id=workspace.id,
        access_link_id=link.id,
        filename=filename,
        object_key="obj-bio-received",
        status="received",
        size_bytes=archive_path.stat().st_size,
        sha256="hash-bio-received",
    )
    rejected = DepositFile(
        workspace_id=workspace.id,
        access_link_id=link.id,
        filename=filename,
        object_key="obj-bio-rejected",
        status="rejected",
        size_bytes=archive_path.stat().st_size + 4096,
        sha256="hash-bio-rejected",
        rejection_reason="superseded by retry cleanup",
    )
    db_session.add_all([received, rejected])
    db_session.commit()

    def _fake_staged(deposit_file):
        if deposit_file.id == received.id:
            return archive_path
        raise AssertionError("rejected duplicate should not be selected")

    monkeypatch.setattr("app.services.spl_wave_importer.staged_file_path", _fake_staged)

    plan = build_v3_archive_wave_plan(
        db_session,
        workspace=workspace,
        collection_slug="andritz-notices-techniques-spl-pilot",
        archive_filenames=[filename],
        dry_run=False,
    )

    assert plan.archives[0].deposit_file_id == received.id
    assert plan.archives[0].promotable is True
    assert plan.total_documents == 1

    result = execute_wave_plan(db_session, workspace=workspace, user=user, plan=plan)
    assert result["status"] == "queued"
    assert result["promoted_archives"][0]["file_id"] == received.id
    db_session.expire_all()
    assert db_session.query(DepositFile).filter_by(id=received.id).one().status == "promoted"
    assert db_session.query(DepositFile).filter_by(id=rejected.id).one().status == "rejected"


# --- Collision-prevention fix (source-namespaced document identity) ----------


def test_archive_document_namespace_distinguishes_prefixes():
    ns_a = archive_document_namespace("Notices_Techniques_SPL/A/Manual_X.zip")
    ns_c = archive_document_namespace("Notices_Techniques_SPL/C/Manual_X.zip")
    assert ns_a == "A__Manual_X"
    assert ns_c == "C__Manual_X"
    assert ns_a != ns_c
    # Very long deposit paths fall back to a bounded, hash-suffixed namespace.
    long_ns = archive_document_namespace("X/" + "Z" * 200 + ".zip")
    assert len(long_ns) <= 80


def test_namespacing_prevents_cross_prefix_collision(tmp_path):
    """Two archives under different prefixes sharing an internal path must
    yield DISTINCT document names so neither clobbers the other."""
    a_zip = tmp_path / "A.zip"
    with zipfile.ZipFile(a_zip, "w") as archive:
        archive.writestr("OPERATING_MANUAL/page1.pdf", "A-CONTENT")
    c_zip = tmp_path / "C.zip"
    with zipfile.ZipFile(c_zip, "w") as archive:
        archive.writestr("OPERATING_MANUAL/page1.pdf", "C-CONTENT")

    shared_used: set[str] = set()
    docs_a, _ = _read_supported_archive_documents(
        a_zip,
        deposit_filename="Notices_Techniques_SPL/A/Manual_X.zip",
        document_namespace=archive_document_namespace("Notices_Techniques_SPL/A/Manual_X.zip"),
        used_names=shared_used,
    )
    docs_c, _ = _read_supported_archive_documents(
        c_zip,
        deposit_filename="Notices_Techniques_SPL/C/Manual_X.zip",
        document_namespace=archive_document_namespace("Notices_Techniques_SPL/C/Manual_X.zip"),
        used_names=shared_used,
    )
    name_a = docs_a[0]["filename"]
    name_c = docs_c[0]["filename"]
    assert name_a == "A__Manual_X__OPERATING_MANUAL__page1.pdf"
    assert name_c == "C__Manual_X__OPERATING_MANUAL__page1.pdf"
    assert name_a != name_c
    # Both names registered in the shared cross-archive de-dup set.
    assert {name_a, name_c} <= shared_used
    # Legacy un-namespaced name is recorded for backward-compatible resolution.
    assert docs_a[0]["metadata"]["legacy_document_name"] == "OPERATING_MANUAL__page1.pdf"


def test_legacy_behavior_unchanged_without_namespace(tmp_path):
    """Default (no namespace) keeps the legacy flat naming so the existing
    2355-document corpus resolves under its original keys."""
    a_zip = tmp_path / "legacy.zip"
    with zipfile.ZipFile(a_zip, "w") as archive:
        archive.writestr("OPERATING_MANUAL/page1.pdf", "X")
    docs, _ = _read_supported_archive_documents(a_zip, deposit_filename="legacy.zip")
    assert docs[0]["filename"] == "OPERATING_MANUAL__page1.pdf"
    assert "document_namespace" not in docs[0]["metadata"]


def test_resolve_original_key_legacy_fallback(tmp_path, monkeypatch):
    from app.core.config import settings
    from app.models.knowledge_collection import KnowledgeCollection
    from app.services.knowledge_collections import original_key, resolve_original_key
    from app.services.object_store import get_object_store

    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))

    coll = KnowledgeCollection(
        id="col-legacy",
        workspace_id="ws-legacy",
        name="Manuals",
        slug="manuals",
        artifact_prefix="workspaces/ws-legacy/knowledge-collections/col-legacy",
    )
    store = get_object_store()
    # Legacy flat-named original (pre-existing corpus) resolves directly.
    store.write_bytes(original_key(coll, "OPERATING_MANUAL__page1.pdf"), b"LEGACY")
    assert resolve_original_key(coll, "OPERATING_MANUAL__page1.pdf", store=store).endswith(
        "OPERATING_MANUAL__page1.pdf"
    )
    assert store.read_bytes(resolve_original_key(coll, "OPERATING_MANUAL__page1.pdf", store=store)) == b"LEGACY"
    # A namespaced lookup whose object only exists under the legacy name falls
    # back to the explicit legacy name when provided.
    resolved = resolve_original_key(
        coll,
        "A__Manual_X__OPERATING_MANUAL__page1.pdf",
        legacy_name="OPERATING_MANUAL__page1.pdf",
        store=store,
    )
    assert store.read_bytes(resolved) == b"LEGACY"


def test_execute_wave_plan_collision_guard_no_clobber(db_session, monkeypatch, tmp_path):
    """A new wave whose document name collides with an existing object from a
    DIFFERENT source must NOT overwrite it: the existing bytes survive and the
    collision is disambiguated + recorded."""
    from app.core.config import settings
    from app.models.secure_deposit import DepositFile
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.services.knowledge_collections import (
        create_or_get_collection,
        document_manifest_key,
        original_key,
    )
    from app.services.object_store import get_object_store
    from app.services.secure_deposit import create_link

    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(
        "app.services.spl_wave_importer.dispatch_worker_job",
        lambda _db, _job: "fake-task-id",
    )

    workspace = Workspace(id="ws-andritz", name="Andritz", slug="andritz")
    user = User(id="user-1", username="thib", email="operator@example.test")
    db_session.add_all([workspace, user])
    db_session.flush()
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="SPL wave test",
        expires_at=None,
        max_file_size_mb=1024,
        allowed_extensions=["zip"],
    )

    archive_path = tmp_path / "Manual_X.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("page1.pdf", "NEW-FROM-A")

    deposit = DepositFile(
        workspace_id=workspace.id,
        access_link_id=link.id,
        filename="Notices_Techniques_SPL/A/Manual_X.zip",
        object_key="obj/manual_x",
        status="received",
        size_bytes=archive_path.stat().st_size,
        sha256="hash-x",
    )
    db_session.add(deposit)
    db_session.commit()
    monkeypatch.setattr("app.services.spl_wave_importer.staged_file_path", lambda _file: archive_path)

    # Pre-seed the collection with an existing object under the *same* name the
    # wave will produce, but owned by a DIFFERENT source.
    collision_name = "A__Manual_X__page1.pdf"
    collection = create_or_get_collection(
        db_session,
        workspace=workspace,
        name="andritz-notices-techniques-spl-pilot",
        slug="andritz-notices-techniques-spl-pilot",
    )
    collection.document_names = [collision_name]
    store = get_object_store()
    store.write_bytes(original_key(collection, collision_name), b"OLD-FROM-B")
    import json as _json

    store.write_text(
        document_manifest_key(collection),
        _json.dumps({collision_name: {"source_deposit_path": "Notices_Techniques_SPL/B/OTHER.zip"}}),
    )
    db_session.commit()

    plan = build_wave_plan(
        db_session,
        workspace=workspace,
        collection_slug="andritz-notices-techniques-spl-pilot",
        archive_filenames=("Notices_Techniques_SPL/A/Manual_X.zip",),
        dry_run=False,
        wave_id="spl_test",
    )
    result = execute_wave_plan(db_session, workspace=workspace, user=user, plan=plan)

    # Existing object is untouched (no clobber).
    assert store.read_bytes(original_key(collection, collision_name)) == b"OLD-FROM-B"
    # Collision recorded and the new document stored under a disambiguated name.
    assert len(result["collisions"]) == 1
    stored_as = result["collisions"][0]["stored_as"]
    assert stored_as != collision_name
    assert store.read_bytes(original_key(collection, stored_as)) == b"NEW-FROM-A"
    db_session.expire_all()
    refreshed = (
        db_session.query(__import__("app.models.knowledge_collection", fromlist=["KnowledgeCollection"]).KnowledgeCollection)
        .filter_by(id=collection.id)
        .one()
    )
    assert collision_name in refreshed.document_names
    assert stored_as in refreshed.document_names


def test_execute_wave_plan_reindexes_existing_archive_documents(db_session, monkeypatch, tmp_path):
    """Force-running a wave must queue existing source documents too.

    This repairs cases where a prior promotion wrote originals/manifest entries
    but Qdrant ended up with zero chunks.
    """
    from app.core.config import settings
    from app.models.secure_deposit import DepositFile
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.services.knowledge_collections import (
        create_or_get_collection,
        document_manifest_key,
        original_key,
    )
    from app.services.object_store import get_object_store
    from app.services.secure_deposit import create_link

    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(
        "app.services.spl_wave_importer.dispatch_worker_job",
        lambda _db, job: setattr(job, "celery_task_id", "fake-task-id") or "fake-task-id",
    )

    workspace = Workspace(id="ws-andritz", name="Andritz", slug="andritz")
    user = User(id="user-1", username="thib", email="operator@example.test")
    db_session.add_all([workspace, user])
    db_session.flush()
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="SPL wave test",
        expires_at=None,
        max_file_size_mb=1024,
        allowed_extensions=["zip"],
    )

    archive_path = tmp_path / "Manual_ASY100.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("page1.pdf", "EXISTING")
    deposit = DepositFile(
        workspace_id=workspace.id,
        access_link_id=link.id,
        filename="Notices_Techniques_SPL/A/Manual_ASY100.zip",
        object_key="obj/asy100",
        status="promoted",
        size_bytes=archive_path.stat().st_size,
        sha256="hash-asy",
    )
    db_session.add(deposit)
    db_session.commit()
    monkeypatch.setattr("app.services.spl_wave_importer.staged_file_path", lambda _file: archive_path)

    collection = create_or_get_collection(
        db_session,
        workspace=workspace,
        name="andritz-notices-techniques-spl-pilot",
        slug="andritz-notices-techniques-spl-pilot",
    )
    existing_name = "A__Manual_ASY100__page1.pdf"
    collection.document_names = [existing_name]
    store = get_object_store()
    store.write_bytes(original_key(collection, existing_name), b"EXISTING")
    import json as _json

    store.write_text(
        document_manifest_key(collection),
        _json.dumps({existing_name: {"source_deposit_path": "Notices_Techniques_SPL/A/Manual_ASY100.zip"}}),
    )
    db_session.commit()

    plan = build_wave_plan(
        db_session,
        workspace=workspace,
        collection_slug=collection.slug,
        archive_filenames=("Notices_Techniques_SPL/A/Manual_ASY100.zip",),
        dry_run=False,
        wave_id="spl_repair",
    )
    result = execute_wave_plan(
        db_session,
        workspace=workspace,
        user=user,
        plan=plan,
        document_ocr={"enabled": False},
    )

    refreshed_job = (
        db_session.query(__import__("app.models.knowledge_collection", fromlist=["WorkerJob"]).WorkerJob)
        .filter_by(id=result["job_id"])
        .one()
    )
    assert result["new_document_count"] == 0
    assert result["job_document_count"] == 1
    assert refreshed_job.result["ingest_options"]["document_names"] == [existing_name]
    assert refreshed_job.result["ingest_options"]["document_ocr"] == {"enabled": False}
