from __future__ import annotations

import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.v1.endpoints import secure_deposit
from app.core.config import settings
from app.models.user import User
from app.models.workspace import Workspace
from app.services.secure_deposit import create_link, record_staged_file_from_path


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(secure_deposit.internal_router, prefix="/sftp")
    app.dependency_overrides[secure_deposit.get_current_workspace] = lambda: workspace
    app.dependency_overrides[secure_deposit.get_current_user] = lambda: user
    app.dependency_overrides[secure_deposit.get_db] = lambda: db_session
    return TestClient(app)


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


def test_bulk_promote_spreadsheets_uses_one_worker_job(db_session, monkeypatch, tmp_path):
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
        job.celery_task_id = "task-excel-bulk"
        return "task-excel-bulk"

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
    assert len(body["files"]) == 2
    skipped_reasons = {item["reason"] for item in body["skipped"]}
    assert skipped_reasons == {"legacy_xls_unsupported", "invalid_office_spreadsheet"}
    assert body["result"]["mode"] == "spreadsheet_bulk"
    assert body["result"]["promoted_count"] == 2
    assert body["result"]["celery_task_id"] == "task-excel-bulk"
    assert len({file["worker_job_id"] for file in body["files"]}) == 1
