from __future__ import annotations

import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.v1.endpoints import secure_deposit
from app.core.config import settings
from app.models.audit import AuditLog
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services.secure_deposit import create_link, record_staged_file_from_path
from app.services.secure_deposit_operations import write_sftp_upload_sidecar


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(secure_deposit.internal_router, prefix="/sftp")
    app.dependency_overrides[secure_deposit.get_current_workspace] = lambda: workspace
    app.dependency_overrides[secure_deposit.get_current_user] = lambda: user
    app.dependency_overrides[secure_deposit.get_db] = lambda: db_session
    return TestClient(app)


def _touch_old(path, seconds: int = 48 * 3600) -> None:
    import os
    import time

    old = time.time() - seconds
    os.utime(path, (old, old))


def _touch_now(path) -> None:
    import os
    import time

    now = time.time()
    os.utime(path, (now, now))


def test_promote_deposit_zip_returns_queued_worker_payload(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path / "secure-deposit"))
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "object-store"))
    monkeypatch.setattr(settings, "secure_deposit_archive_promotion_max_files", 50)
    monkeypatch.setattr(secure_deposit, "_enforce", lambda *args, **kwargs: None)

    workspace = Workspace(id="ws-andritz", name="Andritz", slug="andritz")
    user = User(id="user-1", email="thibaud.ishacian@datategy.net", username="thib")
    db_session.add_all([workspace, user])
    db_session.commit()
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="Manual upload",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )
    source = tmp_path / "Manual_BBA120.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("Manual_BBA120/Declaration/Declaration.pdf", b"%PDF declaration")
        archive.writestr("Manual_BBA120/Operator manual/Chapter 01.pdf", b"%PDF chapter")
    row = record_staged_file_from_path(
        db_session,
        link=link,
        source_path=source,
        filename="Manual_BBA120.zip",
        content_type="application/zip",
        actor=f"sftp:{link.access_id}",
        transport="sftp",
    )
    db_session.commit()

    def fake_dispatch(db, job):
        job.celery_task_id = "task-bba120"
        return "task-bba120"

    monkeypatch.setattr("app.services.secure_deposit.dispatch_worker_job", fake_dispatch)

    response = _client(db_session, workspace, user).post(
        f"/sftp/deposits/{row.id}/promote",
        json={"collection_slug": "andritz-manuals-bba120-pilot"},
    )

    assert response.status_code == 200
    body = response.json()["file"]
    assert body["status"] == "promoted"
    assert body["promoted_collection_slug"] == "andritz-manuals-bba120-pilot"
    assert body["worker_job_id"]
    assert body["promotion_result"]["archive"]["extracted_count"] == 2
    assert body["promotion_result"]["celery_task_id"] == "task-bba120"


def test_promote_deposit_spreadsheet_returns_queued_worker_payload(db_session, monkeypatch, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path / "secure-deposit"))
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "object-store"))
    monkeypatch.setattr(secure_deposit, "_enforce", lambda *args, **kwargs: None)

    workspace = Workspace(id="ws-andritz", name="Andritz", slug="andritz")
    user = User(id="user-1", email="thibaud.ishacian@datategy.net", username="thib")
    db_session.add_all([workspace, user])
    db_session.commit()
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="Excel upload",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )
    source = tmp_path / "GEOTEX-SPL-Y25.05.22-PIL.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Def strips"
    sheet.append(["A", 80])
    sheet.append(["B", 85])
    workbook.save(source)
    row = record_staged_file_from_path(
        db_session,
        link=link,
        source_path=source,
        filename="1-NON-WOVENS/FRANCE/GEOTEX/2025-05-PIL-tests diff_rents filets/GEOTEX-SPL-Y25.05.22-PIL.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        actor=f"sftp:{link.access_id}",
        transport="sftp",
    )
    db_session.commit()

    def fake_dispatch(db, job):
        job.celery_task_id = "task-excel"
        return "task-excel"

    monkeypatch.setattr("app.services.secure_deposit.dispatch_worker_job", fake_dispatch)

    response = _client(db_session, workspace, user).post(
        f"/sftp/deposits/{row.id}/promote",
        json={"collection_slug": "andritz-non-wovens-france-excel-pilot"},
    )

    assert response.status_code == 200
    body = response.json()["file"]
    assert body["status"] == "promoted"
    assert body["promoted_collection_slug"] == "andritz-non-wovens-france-excel-pilot"
    assert body["worker_job_id"]
    assert body["promotion_result"]["mode"] == "spreadsheet"
    assert body["promotion_result"]["spreadsheet"]["extension"] == "xlsx"
    assert body["promotion_result"]["celery_task_id"] == "task-excel"


def test_browse_deposit_zip_archive_lists_folders_and_members(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path / "secure-deposit"))
    monkeypatch.setattr(secure_deposit, "_enforce_file_read", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.services.secure_deposit.is_workspace_enabled", lambda workspace: True)

    workspace = Workspace(id="ws-zip", name="Zip", slug="zip")
    user = User(id="user-zip", email="zip@datategy.net", username="zip")
    db_session.add_all([workspace, user])
    db_session.commit()
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="Archive upload",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )
    source = tmp_path / "manual.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("docs/readme.txt", b"hello archive")
        archive.writestr("docs/manual.pdf", b"%PDF-1.4")
        archive.writestr("images/photo.png", b"\x89PNG\r\n\x1a\n")
    row = record_staged_file_from_path(
        db_session,
        link=link,
        source_path=source,
        filename="archives/manual.zip",
        content_type="application/zip",
        actor=f"sftp:{link.access_id}",
        transport="sftp",
    )
    db_session.commit()

    client = _client(db_session, workspace, user)
    root = client.get(f"/sftp/deposits/{row.id}/archive")
    assert root.status_code == 200
    root_items = root.json()["items"]
    assert [item["name"] for item in root_items] == ["docs", "images"]

    docs = client.get(f"/sftp/deposits/{row.id}/archive", params={"path": "docs"})
    assert docs.status_code == 200
    doc_items = docs.json()["items"]
    assert [item["name"] for item in doc_items] == ["manual.pdf", "readme.txt"]
    assert next(item for item in doc_items if item["name"] == "readme.txt")["previewable"] is True


def test_browse_deposit_zip_member_preview_and_download(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path / "secure-deposit"))
    monkeypatch.setattr(secure_deposit, "_enforce_file_read", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.services.secure_deposit.is_workspace_enabled", lambda workspace: True)

    workspace = Workspace(id="ws-zip-preview", name="Zip", slug="zip-preview")
    user = User(id="user-zip-preview", email="zip@datategy.net", username="zip")
    db_session.add_all([workspace, user])
    db_session.commit()
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="Archive upload",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )
    source = tmp_path / "manual.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("docs/readme.txt", b"hello archive")
    row = record_staged_file_from_path(
        db_session,
        link=link,
        source_path=source,
        filename="archives/manual.zip",
        content_type="application/zip",
        actor=f"sftp:{link.access_id}",
        transport="sftp",
    )
    db_session.commit()

    client = _client(db_session, workspace, user)
    preview = client.get(f"/sftp/deposits/{row.id}/archive/member/preview", params={"path": "docs/readme.txt"})
    assert preview.status_code == 200
    assert preview.json()["kind"] == "text"
    assert "hello archive" in preview.json()["content"]

    download = client.get(f"/sftp/deposits/{row.id}/archive/member/download", params={"path": "docs/readme.txt"})
    assert download.status_code == 200
    assert download.content == b"hello archive"
    assert download.headers["content-type"].startswith("text/plain")


def test_browse_deposit_zip_member_rejects_unsafe_path(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path / "secure-deposit"))
    monkeypatch.setattr(secure_deposit, "_enforce_file_read", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.services.secure_deposit.is_workspace_enabled", lambda workspace: True)

    workspace = Workspace(id="ws-zip-unsafe", name="Zip", slug="zip-unsafe")
    user = User(id="user-zip-unsafe", email="zip@datategy.net", username="zip")
    db_session.add_all([workspace, user])
    db_session.commit()
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="Archive upload",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )
    source = tmp_path / "manual.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("readme.txt", b"hello")
    row = record_staged_file_from_path(
        db_session,
        link=link,
        source_path=source,
        filename="manual.zip",
        content_type="application/zip",
        actor=f"sftp:{link.access_id}",
        transport="sftp",
    )
    db_session.commit()

    response = _client(db_session, workspace, user).get(
        f"/sftp/deposits/{row.id}/archive/member/preview",
        params={"path": "../readme.txt"},
    )

    assert response.status_code == 422


def test_bulk_promote_supported_documents_uses_one_worker_job(db_session, monkeypatch, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path / "secure-deposit"))
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "object-store"))
    monkeypatch.setattr(secure_deposit, "_enforce", lambda *args, **kwargs: None)

    workspace = Workspace(id="ws-andritz", name="Andritz", slug="andritz")
    user = User(id="user-1", email="thibaud.ishacian@datategy.net", username="thib")
    db_session.add_all([workspace, user])
    db_session.commit()
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="Knowledge upload",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )

    rows = []
    for label in ("sample-a", "sample-b"):
        source = tmp_path / f"{label}.xlsx"
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "Def strips"
        sheet.append(["A", 80])
        sheet.append(["B", 85])
        workbook.save(source)
        rows.append(
            record_staged_file_from_path(
                db_session,
                link=link,
                source_path=source,
                filename=f"1-NON-WOVENS/FRANCE/GEOTEX/{label}.xlsx",
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                actor=f"sftp:{link.access_id}",
                transport="sftp",
        )
    )

    pdf = tmp_path / "manual.pdf"
    pdf.write_bytes(b"%PDF-1.4\n% sample")
    rows.append(
        record_staged_file_from_path(
            db_session,
            link=link,
            source_path=pdf,
            filename="1-NON-WOVENS/FRANCE/GEOTEX/manual.pdf",
            content_type="application/pdf",
            actor=f"sftp:{link.access_id}",
            transport="sftp",
        )
    )

    legacy = tmp_path / "legacy.xls"
    legacy.write_bytes(b"legacy")
    rows.append(
        record_staged_file_from_path(
            db_session,
            link=link,
            source_path=legacy,
            filename="1-NON-WOVENS/FRANCE/LEMOINE/legacy.xls",
            content_type="application/vnd.ms-excel",
            actor=f"sftp:{link.access_id}",
            transport="sftp",
        )
    )
    invalid_modern = tmp_path / "invalid.xlsx"
    invalid_modern.write_bytes(b"not a workbook")
    rows.append(
        record_staged_file_from_path(
            db_session,
            link=link,
            source_path=invalid_modern,
            filename="1-NON-WOVENS/FRANCE/AHLSTROM/invalid.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            actor=f"sftp:{link.access_id}",
            transport="sftp",
        )
    )
    db_session.commit()

    def fake_dispatch(db, job):
        job.celery_task_id = "task-document-bulk"
        return "task-document-bulk"

    monkeypatch.setattr("app.services.secure_deposit.dispatch_worker_job", fake_dispatch)

    response = _client(db_session, workspace, user).post(
        "/sftp/deposits/promote-bulk",
        json={
            "collection_slug": "andritz-non-wovens-france-excel-pilot",
            "file_ids": [row.id for row in rows],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["files"]) == 3
    skipped_reasons = {item["reason"] for item in body["skipped"]}
    assert skipped_reasons == {"legacy_xls_unsupported", "invalid_office_spreadsheet"}
    assert body["result"]["mode"] == "document_bulk"
    assert body["result"]["promoted_count"] == 3
    assert body["result"]["document_count"] == 3
    assert body["result"]["celery_task_id"] == "task-document-bulk"
    assert {item["extension"] for item in body["result"]["files"]} == {"xlsx", "pdf"}
    assert len({file["worker_job_id"] for file in body["files"]}) == 1


def test_sftp_operations_lists_active_sidecar_upload(db_session, monkeypatch, tmp_path):
    storage = tmp_path / "secure-deposit"
    temp_dir = storage / "_sftp_uploads"
    temp_dir.mkdir(parents=True)
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(storage))
    monkeypatch.setattr(settings, "secure_deposit_sftp_temp_dir", str(temp_dir))
    monkeypatch.setattr(secure_deposit, "_enforce", lambda *args, **kwargs: None)

    workspace = Workspace(id="ws-andritz", name="Andritz", slug="andritz")
    user = User(id="user-1", email="thibaud.ishacian@datategy.net", username="thib")
    db_session.add_all([workspace, user])
    db_session.commit()
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="Andritz SFTP",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )
    part = temp_dir / ".sftp-Manual.zip-abc.part"
    part.write_bytes(b"uploading")
    write_sftp_upload_sidecar(
        part,
        access_id=link.access_id,
        workspace_id=workspace.id,
        filename="Notices_Techniques_SPL/C/Manual.zip",
        max_bytes=link.max_file_size_mb * 1024 * 1024,
    )

    response = _client(db_session, workspace, user).get("/sftp/operations")

    assert response.status_code == 200
    body = response.json()
    assert body["storage_summary"]["temporary_count"] == 1
    assert body["storage_summary"]["active_count"] == 1
    assert body["active_uploads"][0]["filename"] == "Notices_Techniques_SPL/C/Manual.zip"
    assert body["active_uploads"][0]["link_label"] == "Andritz SFTP"
    assert body["active_uploads"][0]["status"] == "receiving"


def test_sftp_reconciliation_dry_run_then_quarantine(db_session, monkeypatch, tmp_path):
    storage = tmp_path / "secure-deposit"
    temp_dir = storage / "_sftp_uploads"
    temp_dir.mkdir(parents=True)
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(storage))
    monkeypatch.setattr(settings, "secure_deposit_sftp_temp_dir", str(temp_dir))
    monkeypatch.setattr(settings, "worker_eager_mode", True)
    monkeypatch.setattr(secure_deposit, "_enforce", lambda *args, **kwargs: None)

    workspace = Workspace(id="ws-andritz", name="Andritz", slug="andritz")
    user = User(id="user-1", email="thibaud.ishacian@datategy.net", username="thib")
    db_session.add_all([workspace, user])
    db_session.commit()
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="Andritz SFTP",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )

    part = temp_dir / ".sftp-stale-abc.part"
    part.write_bytes(b"stale partial")
    write_sftp_upload_sidecar(
        part,
        access_id=link.access_id,
        workspace_id=workspace.id,
        filename="Notices_Techniques_SPL/C/stale.zip",
        max_bytes=link.max_file_size_mb * 1024 * 1024,
    )
    _touch_old(part)

    unattributed = temp_dir / ".sftp-legacy.part"
    unattributed.write_bytes(b"legacy partial")
    _touch_old(unattributed)

    orphan = storage / "workspaces" / workspace.id / "secure-deposit" / link.access_id / "orphan-id" / "orphan.txt"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"orphan")
    _touch_old(orphan)

    client = _client(db_session, workspace, user)
    dry_response = client.post("/sftp/operations/reconcile", json={"mode": "dry_run", "stale_after_hours": 24})

    assert dry_response.status_code == 200, dry_response.text
    dry_job = dry_response.json()["job"]
    assert dry_job["status"] == "completed"
    assert dry_job["result"]["counts"]["stale_partials"] == 1
    assert dry_job["result"]["counts"]["orphan_files"] == 1
    assert dry_job["result"]["counts"]["unattributed_partials"] == 1
    assert part.exists()
    assert orphan.exists()

    quarantine_response = client.post(
        "/sftp/operations/reconcile",
        json={"mode": "quarantine", "stale_after_hours": 24, "confirm_from_job_id": dry_job["id"]},
    )

    assert quarantine_response.status_code == 200, quarantine_response.text
    quarantine_job = quarantine_response.json()["job"]
    assert quarantine_job["status"] == "completed"
    assert quarantine_job["result"]["quarantined_partial_count"] == 1
    assert quarantine_job["result"]["quarantined_orphan_count"] == 1
    assert not part.exists()
    assert not orphan.exists()
    assert unattributed.exists()
    assert db_session.query(WorkspaceJob).filter(WorkspaceJob.kind == "sftp_reconciliation").count() == 2
    event_types = {row.event_type for row in db_session.query(AuditLog).all()}
    assert "deposit.sftp.partial.quarantined" in event_types
    assert "deposit.sftp.orphan.quarantined" in event_types


def test_sftp_quarantine_skips_partial_that_became_recent(db_session, monkeypatch, tmp_path):
    storage = tmp_path / "secure-deposit"
    temp_dir = storage / "_sftp_uploads"
    temp_dir.mkdir(parents=True)
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(storage))
    monkeypatch.setattr(settings, "secure_deposit_sftp_temp_dir", str(temp_dir))
    monkeypatch.setattr(settings, "worker_eager_mode", True)
    monkeypatch.setattr(secure_deposit, "_enforce", lambda *args, **kwargs: None)

    workspace = Workspace(id="ws-andritz", name="Andritz", slug="andritz")
    user = User(id="user-1", email="thibaud.ishacian@datategy.net", username="thib")
    db_session.add_all([workspace, user])
    db_session.commit()
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="Andritz SFTP",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )

    part = temp_dir / ".sftp-resumed-abc.part"
    part.write_bytes(b"stale then resumed")
    write_sftp_upload_sidecar(
        part,
        access_id=link.access_id,
        workspace_id=workspace.id,
        filename="Notices_Techniques_SPL/C/resumed.zip",
        max_bytes=link.max_file_size_mb * 1024 * 1024,
    )
    _touch_old(part)

    client = _client(db_session, workspace, user)
    dry_job = client.post("/sftp/operations/reconcile", json={"mode": "dry_run", "stale_after_hours": 24}).json()["job"]
    _touch_now(part)

    response = client.post(
        "/sftp/operations/reconcile",
        json={"mode": "quarantine", "stale_after_hours": 24, "confirm_from_job_id": dry_job["id"]},
    )

    assert response.status_code == 200, response.text
    job = response.json()["job"]
    assert job["result"]["quarantined_partial_count"] == 0
    assert job["result"]["skipped_count"] == 1
    assert part.exists()
