from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.models.knowledge_collection import KnowledgeCollection, WorkerJob
from app.models.secure_deposit import DepositFile
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.knowledge_collections import document_manifest_key
from app.services.object_store import get_object_store
from app.services.secure_deposit import (
    authenticate_link,
    build_deposit_archive,
    create_link,
    promote_file_to_collection,
    preview_deposit_file,
    record_staged_file_from_path,
    safe_filename,
    safe_relative_path,
    verify_session_token,
)
from app.services.secure_deposit_sftp import (
    _is_root_path,
    _remote_dir_path,
    _remote_relative_path,
    _sftp_longname,
)


def _workspace_user(db_session):
    workspace = Workspace(id="ws-andritz", name="Andritz", slug="andritz")
    user = User(id="user-1", username="thib", email="thibaud.ishacian@datategy.net")
    db_session.add_all([workspace, user])
    db_session.flush()
    db_session.add(
        WorkspaceMember(
            user_id=user.id,
            workspace_id=workspace.id,
            role="owner",
            role_template="workspace_owner",
        )
    )
    db_session.flush()
    return workspace, user


def test_deposit_link_password_is_one_time_and_session_scoped(db_session):
    workspace, user = _workspace_user(db_session)

    link, password = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="Supplier upload",
        expires_at=None,
        max_file_size_mb=20,
        allowed_extensions=["pdf"],
    )
    assert password not in link.password_hash

    authed_link, token, _ = authenticate_link(
        db_session,
        access_id=link.access_id,
        password=password,
    )
    payload = verify_session_token(token, link.access_id)

    assert authed_link.id == link.id
    assert payload["sub"] == link.access_id
    assert payload["workspace_id"] == workspace.id


def test_deposit_link_rejects_bad_password(db_session):
    workspace, user = _workspace_user(db_session)
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="Supplier upload",
        expires_at=None,
        max_file_size_mb=None,
        allowed_extensions=None,
    )

    with pytest.raises(HTTPException) as exc:
        authenticate_link(db_session, access_id=link.access_id, password="wrong")

    assert exc.value.status_code == 401


def test_empty_allowed_extensions_means_any_file_type(db_session):
    workspace, user = _workspace_user(db_session)
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="Any upload",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )

    assert link.allowed_extensions == []
    assert link.max_file_size_mb == 30 * 1024


def test_record_staged_file_from_path_moves_sftp_upload(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path / "store"))
    workspace, user = _workspace_user(db_session)
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="SFTP upload",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )
    staged = tmp_path / "upload.part"
    content = b"drive commissioning report"
    staged.write_bytes(content)

    row = record_staged_file_from_path(
        db_session,
        link=link,
        source_path=staged,
        filename="../../commissioning.zip",
        content_type="application/octet-stream",
        actor=f"sftp:{link.access_id}",
        transport="sftp",
    )

    assert row.filename == "commissioning.zip"
    assert row.size_bytes == len(content)
    assert row.sha256 == hashlib.sha256(content).hexdigest()
    assert row.object_key.endswith("/commissioning.zip")
    assert not staged.exists()
    assert (tmp_path / "store" / row.object_key).read_bytes() == content


def test_record_staged_file_from_path_preserves_safe_relative_path(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path / "store"))
    workspace, user = _workspace_user(db_session)
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="SFTP directory upload",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )
    staged = tmp_path / "upload.part"
    content = b"nested drive report"
    staged.write_bytes(content)

    row = record_staged_file_from_path(
        db_session,
        link=link,
        source_path=staged,
        filename="Line A/../Motor #1/Photos/Tms1.jpg",
        content_type="application/octet-stream",
        actor=f"sftp:{link.access_id}",
        transport="sftp",
    )

    assert row.filename == "Line A/Motor _1/Photos/Tms1.jpg"
    assert row.object_key.endswith("/Line A/Motor _1/Photos/Tms1.jpg")
    assert (tmp_path / "store" / row.object_key).read_bytes() == content


def test_build_deposit_archive_contains_files_and_manifest(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path))
    workspace, user = _workspace_user(db_session)
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="QA unrestricted",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )
    content = b"industrial context"
    object_key = f"workspaces/{workspace.id}/secure-deposit/{link.access_id}/file-1/manuals/drive/demo.txt"
    source = tmp_path / object_key
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(content)
    row = DepositFile(
        workspace_id=workspace.id,
        access_link_id=link.id,
        filename="manuals/drive/demo.txt",
        content_type="text/plain",
        object_key=object_key,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        status="received",
    )
    db_session.add(row)
    db_session.flush()

    archive_path, archive_name = build_deposit_archive(
        [row],
        links_by_id={link.id: link},
        workspace_slug=workspace.slug,
    )
    try:
        assert archive_name.endswith(".zip")
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            assert "_manifest.json" in names
            assert any(name.endswith("received/manuals/drive/demo.txt") for name in names)
            manifest = json.loads(archive.read("_manifest.json"))
            assert manifest["file_count"] == 1
            assert manifest["files"][0]["sha256"] == row.sha256
    finally:
        archive_path.unlink(missing_ok=True)


def test_preview_deposit_file_returns_text_content(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path / "store"))
    workspace, user = _workspace_user(db_session)
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="QA unrestricted",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )
    staged = tmp_path / "upload.part"
    staged.write_text("# Maintenance note\nTorque setting: 42 Nm", encoding="utf-8")
    row = record_staged_file_from_path(
        db_session,
        link=link,
        source_path=staged,
        filename="manuals/drive/note.md",
        content_type="text/markdown",
        actor=f"sftp:{link.access_id}",
        transport="sftp",
    )

    preview = preview_deposit_file(row)

    assert preview["kind"] == "text"
    assert "Torque setting" in preview["content"]
    assert preview["download_url"].endswith(f"/{row.id}/download")


def test_preview_deposit_file_returns_spreadsheet_rows(db_session, monkeypatch, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path / "store"))
    workspace, user = _workspace_user(db_session)
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="QA unrestricted",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )
    staged = tmp_path / "upload.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "AKK"
    sheet.append(["Reference", "Value"])
    sheet.append(["PULP80", 154.8])
    workbook.save(staged)

    row = record_staged_file_from_path(
        db_session,
        link=link,
        source_path=staged,
        filename="AKK-WET-PAT-PULP80.xlsx",
        content_type="application/octet-stream",
        actor=f"sftp:{link.access_id}",
        transport="sftp",
    )

    preview = preview_deposit_file(row)

    assert preview["kind"] == "spreadsheet"
    assert preview["sheet_name"] == "AKK"
    assert preview["rows"][0] == ["Reference", "Value"]
    assert preview["rows"][1] == ["PULP80", "154.8"]


@pytest.mark.asyncio
async def test_promote_spreadsheet_queues_collection_ingest(db_session, monkeypatch, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    workspace, user = _workspace_user(db_session)
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="Excel pilot",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )
    staged = tmp_path / "GEOTEX-SPL-Y25.05.22-PIL.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Def strips"
    sheet.append(["A", 80])
    sheet.append(["B", 85])
    workbook.save(staged)
    staged_bytes = staged.read_bytes()
    row = record_staged_file_from_path(
        db_session,
        link=link,
        source_path=staged,
        filename="1-NON-WOVENS/FRANCE/GEOTEX/2025-05-PIL-tests diff_rents filets/GEOTEX-SPL-Y25.05.22-PIL.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        actor=f"sftp:{link.access_id}",
        transport="sftp",
    )

    def fake_dispatch(db, job):
        job.celery_task_id = "task-excel"
        return "task-excel"

    monkeypatch.setattr("app.services.secure_deposit.dispatch_worker_job", fake_dispatch)

    promoted = await promote_file_to_collection(
        db_session,
        deposit_file=row,
        workspace=workspace,
        user=user,
        collection_slug="andritz-non-wovens-france-excel-pilot",
    )

    collection = (
        db_session.query(KnowledgeCollection)
        .filter(KnowledgeCollection.slug == "andritz-non-wovens-france-excel-pilot")
        .one()
    )
    job = db_session.query(WorkerJob).filter(WorkerJob.id == promoted.worker_job_id).one()

    assert promoted.status == "promoted"
    assert promoted.promoted_collection_slug == "andritz-non-wovens-france-excel-pilot"
    assert promoted.promotion_result["mode"] == "spreadsheet"
    assert promoted.promotion_result["spreadsheet"]["extension"] == "xlsx"
    assert promoted.promotion_result["celery_task_id"] == "task-excel"
    assert collection.status == "queued"
    assert collection.document_count == 1
    assert job.status == "queued"
    assert job.celery_task_id == "task-excel"
    stored_name = collection.document_names[0]
    assert stored_name.endswith("GEOTEX-SPL-Y25.05.22-PIL.xlsx")
    assert (
        tmp_path
        / "objects"
            / collection.artifact_prefix
            / "original"
            / stored_name
        ).read_bytes() == staged_bytes


@pytest.mark.asyncio
async def test_promote_legacy_xls_is_rejected_without_text_fallback(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path / "store"))
    workspace, user = _workspace_user(db_session)
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="Legacy Excel",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )
    staged = tmp_path / "legacy.xls"
    staged.write_bytes(b"legacy binary")
    row = record_staged_file_from_path(
        db_session,
        link=link,
        source_path=staged,
        filename="1-NON-WOVENS/FRANCE/legacy.xls",
        content_type="application/vnd.ms-excel",
        actor=f"sftp:{link.access_id}",
        transport="sftp",
    )

    with pytest.raises(HTTPException) as exc:
        await promote_file_to_collection(
            db_session,
            deposit_file=row,
            workspace=workspace,
            user=user,
            collection_slug="andritz-non-wovens-france-excel-pilot",
        )

    db_session.refresh(row)
    assert exc.value.status_code == 422
    assert row.status == "received"
    assert db_session.query(KnowledgeCollection).count() == 0


def test_preview_deposit_file_returns_docx_text(db_session, monkeypatch, tmp_path):
    docx = pytest.importorskip("docx")
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path / "store"))
    workspace, user = _workspace_user(db_session)
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="QA unrestricted",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )
    staged = tmp_path / "commissioning.docx"
    document = docx.Document()
    document.add_heading("Commissioning report", level=1)
    document.add_paragraph("Inspect the dryer pressure before restart.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Asset"
    table.cell(0, 1).text = "Action"
    table.cell(1, 0).text = "Dryer"
    table.cell(1, 1).text = "Verify pressure"
    document.save(staged)

    row = record_staged_file_from_path(
        db_session,
        link=link,
        source_path=staged,
        filename="reports/commissioning.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        actor=f"sftp:{link.access_id}",
        transport="sftp",
    )

    preview = preview_deposit_file(row)

    assert preview["kind"] == "text"
    assert preview["source_kind"] == "docx"
    assert "Commissioning report" in preview["content"]
    assert "Dryer | Verify pressure" in preview["content"]


def _staged_zip(
    db_session,
    tmp_path,
    *,
    workspace: Workspace,
    link,
    entries: dict[str, bytes],
    filename: str = "Manual_BBA120.zip",
) -> DepositFile:
    staged = tmp_path / filename
    with zipfile.ZipFile(staged, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return record_staged_file_from_path(
        db_session,
        link=link,
        source_path=staged,
        filename=filename,
        content_type="application/zip",
        actor=f"sftp:{link.access_id}",
        transport="sftp",
    )


@pytest.mark.asyncio
async def test_promote_zip_queues_collection_ingest(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    monkeypatch.setattr(settings, "secure_deposit_archive_promotion_max_files", 50)
    workspace, user = _workspace_user(db_session)
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="Manual upload",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )
    row = _staged_zip(
        db_session,
        tmp_path,
        workspace=workspace,
        link=link,
        entries={
            "Manual_BBA120/Declaration/Declaration.pdf": b"%PDF declaration",
            "Manual_BBA120/Operator manual/Chapter 01.pdf": b"%PDF chapter",
            "Manual_BBA120/image.png": b"ocr image",
        },
    )

    def fake_dispatch(db, job):
        job.celery_task_id = "task-bba120"
        return "task-bba120"

    monkeypatch.setattr("app.services.secure_deposit.dispatch_worker_job", fake_dispatch)

    promoted = await promote_file_to_collection(
        db_session,
        deposit_file=row,
        workspace=workspace,
        user=user,
        collection_slug="andritz-manuals-bba120-pilot",
    )

    collection = (
        db_session.query(KnowledgeCollection)
        .filter(KnowledgeCollection.slug == "andritz-manuals-bba120-pilot")
        .one()
    )
    job = db_session.query(WorkerJob).filter(WorkerJob.id == promoted.worker_job_id).one()

    assert promoted.status == "promoted"
    assert promoted.promoted_collection_slug == "andritz-manuals-bba120-pilot"
    assert promoted.promotion_result["archive"]["extracted_count"] == 3
    assert promoted.promotion_result["celery_task_id"] == "task-bba120"
    assert collection.status == "queued"
    assert collection.document_count == 3
    assert job.status == "queued"
    assert job.celery_task_id == "task-bba120"
    stored_names = sorted(collection.document_names)
    assert stored_names == [
        "Manual_BBA120__Declaration__Declaration.pdf",
        "Manual_BBA120__Operator manual__Chapter 01.pdf",
        "Manual_BBA120__image.png",
    ]
    assert (
        tmp_path
        / "objects"
        / collection.artifact_prefix
        / "original"
        / "Manual_BBA120__Declaration__Declaration.pdf"
    ).read_bytes() == b"%PDF declaration"
    manifest = json.loads(get_object_store().read_bytes(document_manifest_key(collection)).decode("utf-8"))
    chapter_metadata = manifest["Manual_BBA120__Operator manual__Chapter 01.pdf"]
    assert chapter_metadata["project_code"] == "BBA120"
    assert chapter_metadata["initial_buyer_code"] == "BBA"
    assert chapter_metadata["project_position"] == "120"
    assert chapter_metadata["project_reference_kind"] == "andritz_project"
    assert chapter_metadata["source_family"] == "operating_manual"
    assert chapter_metadata["archive_name"] == "Manual_BBA120.zip"
    assert chapter_metadata["inner_document_path"] == "Manual_BBA120/Operator manual/Chapter 01.pdf"


@pytest.mark.asyncio
async def test_promote_invalid_zip_leaves_deposit_received(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    workspace, user = _workspace_user(db_session)
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="Manual upload",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )
    staged = tmp_path / "Manual_BHX100_revE.zip"
    staged.write_bytes(b"not a zip")
    row = record_staged_file_from_path(
        db_session,
        link=link,
        source_path=staged,
        filename="Manual_BHX100_revE.zip",
        content_type="application/zip",
        actor=f"sftp:{link.access_id}",
        transport="sftp",
    )

    with pytest.raises(HTTPException) as exc:
        await promote_file_to_collection(
            db_session,
            deposit_file=row,
            workspace=workspace,
            user=user,
            collection_slug="andritz-manuals-bba120-pilot",
        )

    db_session.refresh(row)
    assert exc.value.status_code == 422
    assert row.status == "received"
    assert db_session.query(KnowledgeCollection).count() == 0


@pytest.mark.asyncio
async def test_promote_zip_rejects_path_traversal(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    workspace, user = _workspace_user(db_session)
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="Manual upload",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )
    row = _staged_zip(
        db_session,
        tmp_path,
        workspace=workspace,
        link=link,
        entries={"../evil.pdf": b"%PDF evil"},
    )

    with pytest.raises(HTTPException) as exc:
        await promote_file_to_collection(
            db_session,
            deposit_file=row,
            workspace=workspace,
            user=user,
            collection_slug="andritz-manuals-bba120-pilot",
        )

    db_session.refresh(row)
    assert exc.value.status_code == 422
    assert row.status == "received"


@pytest.mark.asyncio
async def test_promote_zip_rejects_supported_file_count_over_limit(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    monkeypatch.setattr(settings, "secure_deposit_archive_promotion_max_files", 1)
    workspace, user = _workspace_user(db_session)
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="Manual upload",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )
    row = _staged_zip(
        db_session,
        tmp_path,
        workspace=workspace,
        link=link,
        entries={
            "Manual_BBA120/Chapter 01.pdf": b"%PDF one",
            "Manual_BBA120/Chapter 02.pdf": b"%PDF two",
        },
    )

    with pytest.raises(HTTPException) as exc:
        await promote_file_to_collection(
            db_session,
            deposit_file=row,
            workspace=workspace,
            user=user,
            collection_slug="andritz-manuals-bba120-pilot",
        )

    db_session.refresh(row)
    assert exc.value.status_code == 413
    assert row.status == "received"


def test_safe_filename_strips_paths_and_unsafe_characters():
    assert safe_filename("../../secret report?.pdf") == "secret report_.pdf"
    assert safe_filename("..\\..\\motor#1.xlsx") == "motor_1.xlsx"


def test_safe_relative_path_preserves_folders_without_traversal():
    assert safe_relative_path("../../line A/motor#1/photo?.jpg") == "line A/motor_1/photo_.jpg"
    assert safe_relative_path("..\\manuals\\2026\\drive.zip") == "manuals/2026/drive.zip"


def test_sftp_upload_root_alias_maps_to_deposit_root():
    assert _is_root_path("/upload")
    assert _remote_dir_path("/upload") == ""
    assert _remote_relative_path("/upload/manuals/drive.zip") == "manuals/drive.zip"


def test_sftp_longname_marks_virtual_directories_for_filezilla():
    attrs = SimpleNamespace(
        permissions=stat.S_IFDIR | 0o755,
        size=0,
        mtime=1_747_000_000,
    )

    longname = _sftp_longname("1-NON-WOVENS", attrs).decode("utf-8")

    assert longname.startswith("drwxr-xr-x ")
    assert longname.endswith(" 1-NON-WOVENS")
