from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import secure_deposit
from app.core.config import settings
from app.models.audit import AuditLog
from app.models.knowledge_collection import KnowledgeCollection
from app.models.secure_deposit import DepositAccessLink
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.models.workspace_job import WorkspaceJob
from app.services.secure_deposit import (
    SFTP_RELEASE_A_CANARY_ACCESS_ID_PREFIX,
    create_link,
    record_staged_file_from_path,
)
from app.services.secure_deposit_operations import write_sftp_upload_sidecar


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(secure_deposit.internal_router, prefix="/sftp")
    app.dependency_overrides[secure_deposit.get_current_workspace] = lambda: workspace
    app.dependency_overrides[secure_deposit.get_current_user] = lambda: user
    app.dependency_overrides[secure_deposit.get_db] = lambda: db_session
    return TestClient(app)


def _public_client(db_session) -> TestClient:
    app = FastAPI()
    app.include_router(secure_deposit.public_router, prefix="/deposit")
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


def test_public_deposit_session_token_cannot_list_another_access_id(db_session):
    workspace = Workspace(id="ws-public-session", name="Public Session", slug="andritz", settings={"features": {"secure_deposit": True}})
    user = User(id="user-public-session", email="owner@datategy.net", username="owner")
    db_session.add_all([workspace, user])
    db_session.commit()
    first_link, password = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="First supplier",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )
    second_link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="Second supplier",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )
    db_session.commit()

    client = _public_client(db_session)
    session = client.post(f"/deposit/{first_link.access_id}/session", json={"password": password})
    assert session.status_code == 200
    token = session.json()["token"]

    response = client.get(
        f"/deposit/{second_link.access_id}/files",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_non_owner_contributor_cannot_download_deposit_file(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path / "secure-deposit"))
    workspace = Workspace(
        id="ws-download-denied",
        name="Download Denied",
        slug="andritz",
        settings={"features": {"secure_deposit": True, "iam_enforced": True}},
    )
    owner = User(id="user-owner-download", email="owner@datategy.net", username="owner")
    other = User(id="user-other-download", email="other@datategy.net", username="other")
    db_session.add_all([workspace, owner, other])
    db_session.flush()
    db_session.add_all(
        [
            WorkspaceMember(
                user_id=owner.id,
                workspace_id=workspace.id,
                role="member",
                role_template="workspace_contributor",
            ),
            WorkspaceMember(
                user_id=other.id,
                workspace_id=workspace.id,
                role="member",
                role_template="workspace_contributor",
            ),
        ]
    )
    db_session.flush()
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=owner,
        label="Owner supplier upload",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )
    source = tmp_path / "manual.pdf"
    source.write_bytes(b"%PDF owner only")
    row = record_staged_file_from_path(
        db_session,
        link=link,
        source_path=source,
        filename="Manuals/private.pdf",
        content_type="application/pdf",
        actor=f"sftp:{link.access_id}",
        transport="sftp",
    )
    db_session.commit()

    response = _client(db_session, workspace, other).get(f"/sftp/deposits/{row.id}/download")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "WORKSPACE_PERMISSION_DENIED"


def test_owner_can_rotate_then_revoke_link_and_credentials_follow_state(db_session):
    workspace = Workspace(
        id="ws-link-rotate-revoke",
        name="Rotate Revoke",
        slug="andritz",
        settings={"features": {"secure_deposit": True, "iam_enforced": True}},
    )
    owner = User(id="user-link-owner", email="owner@datategy.net", username="owner")
    db_session.add_all([workspace, owner])
    db_session.flush()
    db_session.add(
        WorkspaceMember(
            user_id=owner.id,
            workspace_id=workspace.id,
            role="member",
            role_template="workspace_contributor",
        )
    )
    db_session.flush()
    link, original_password = create_link(
        db_session,
        workspace=workspace,
        user=owner,
        label="Supplier upload",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )
    db_session.commit()

    internal = _client(db_session, workspace, owner)
    public = _public_client(db_session)

    rotated = internal.post(f"/sftp/links/{link.id}/rotate")
    assert rotated.status_code == 200
    rotated_link = rotated.json()["link"]
    rotated_password = rotated_link["generated_password"]
    assert rotated_link["status"] == "active"
    assert rotated_link["access_id"] == link.access_id
    assert rotated_password
    assert rotated_password != original_password

    old_session = public.post(f"/deposit/{link.access_id}/session", json={"password": original_password})
    assert old_session.status_code == 401
    new_session = public.post(f"/deposit/{link.access_id}/session", json={"password": rotated_password})
    assert new_session.status_code == 200

    revoked = internal.post(f"/sftp/links/{link.id}/revoke")
    assert revoked.status_code == 200
    assert revoked.json()["link"]["status"] == "revoked"

    revoked_session = public.post(f"/deposit/{link.access_id}/session", json={"password": rotated_password})
    assert revoked_session.status_code == 403


def test_internal_api_explicitly_marks_release_a_sftp_canary_link(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(secure_deposit, "_enforce", lambda *args, **kwargs: None)
    workspace = Workspace(
        id="ws-release-a-sftp-canary",
        name="Release A SFTP canary",
        slug="release-a-sftp-canary",
        settings={"features": {"secure_deposit": True}},
    )
    user = User(
        id="user-release-a-sftp-canary",
        email="release-a-operator@example.test",
        username="release-a-operator",
    )
    db_session.add_all([workspace, user])
    db_session.commit()
    client = _client(db_session, workspace, user)

    response = client.post(
        "/sftp/links",
        json={
            "label": "Release A disposable SFTP proof",
            "max_file_size_mb": 1,
            "allowed_extensions": [],
            "sftp_auth_audit_profile": "release_a_canary_v1",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()["link"]
    assert payload["sftp_auth_audit_profile"] == "release_a_canary_v1"
    persisted = db_session.get(DepositAccessLink, payload["id"])
    assert persisted is not None
    assert persisted.access_id.startswith(SFTP_RELEASE_A_CANARY_ACCESS_ID_PREFIX)

    invalid = client.post(
        "/sftp/links",
        json={
            "label": "Not a supported audit mode",
            "sftp_auth_audit_profile": "dedupe_all",
        },
    )
    assert invalid.status_code == 422

    forced_access_id = client.post(
        "/sftp/links",
        json={
            "label": "Ordinary link",
            "access_id": f"{SFTP_RELEASE_A_CANARY_ACCESS_ID_PREFIX}forged",
        },
    )
    assert forced_access_id.status_code == 422


def test_promote_deposit_zip_returns_queued_worker_payload(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path / "secure-deposit"))
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "object-store"))
    monkeypatch.setattr(settings, "secure_deposit_archive_promotion_max_files", 50)
    monkeypatch.setattr(secure_deposit, "_enforce", lambda *args, **kwargs: None)

    workspace = Workspace(id="ws-andritz", name="Andritz", slug="andritz", settings={"features": {"secure_deposit": True}})
    user = User(id="user-1", email="operator@example.test", username="thib")
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

    workspace = Workspace(id="ws-andritz", name="Andritz", slug="andritz", settings={"features": {"secure_deposit": True}})
    user = User(id="user-1", email="operator@example.test", username="thib")
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

    workspace = Workspace(id="ws-zip", name="Zip", slug="zip", settings={"features": {"secure_deposit": True}})
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

    workspace = Workspace(id="ws-zip-preview", name="Zip", slug="zip-preview", settings={"features": {"secure_deposit": True}})
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
        archive.writestr("docs/manual.html", b"<html><body><h1>Manual</h1><script>alert(1)</script></body></html>")
        archive.writestr("docs/manual.pdf", b"%PDF-1.4\n% manual")
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

    html_preview = client.get(f"/sftp/deposits/{row.id}/archive/member/preview", params={"path": "docs/manual.html"})
    assert html_preview.status_code == 200
    assert html_preview.json()["kind"] == "html"
    assert "<h1>Manual</h1>" in html_preview.json()["content"]

    pdf_preview = client.get(f"/sftp/deposits/{row.id}/archive/member/preview", params={"path": "docs/manual.pdf"})
    assert pdf_preview.status_code == 200
    assert pdf_preview.json()["kind"] == "pdf"
    assert pdf_preview.json()["download_url"].endswith("path=docs%2Fmanual.pdf")

    download = client.get(f"/sftp/deposits/{row.id}/archive/member/download", params={"path": "docs/readme.txt"})
    assert download.status_code == 200
    assert download.content == b"hello archive"
    assert download.headers["content-type"].startswith("text/plain")


def test_browse_deposit_zip_member_rejects_unsafe_path(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path / "secure-deposit"))
    monkeypatch.setattr(secure_deposit, "_enforce_file_read", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.services.secure_deposit.is_workspace_enabled", lambda workspace: True)

    workspace = Workspace(id="ws-zip-unsafe", name="Zip", slug="zip-unsafe", settings={"features": {"secure_deposit": True}})
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


def test_download_deposit_archive_handles_large_synthetic_queue_without_mutation(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path / "secure-deposit"))
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "object-store"))
    monkeypatch.setattr(secure_deposit, "_enforce", lambda *args, **kwargs: None)

    workspace = Workspace(id="ws-archive-download", name="Archive Download", slug="andritz", settings={"features": {"secure_deposit": True}})
    user = User(id="user-archive-download", email="archive-download@datategy.net", username="archive-download")
    db_session.add_all([workspace, user])
    db_session.commit()
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="Large Queue",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )

    rows = []
    for index in range(80):
        source = tmp_path / f"large-queue-{index:03}.pdf"
        source.write_bytes(b"%PDF-1.4\n" + f"synthetic archive payload {index}".encode())
        rows.append(
            record_staged_file_from_path(
                db_session,
                link=link,
                source_path=source,
                filename=f"1-NON-WOVENS/FRANCE/LARGE/archive-download-{index:03}.pdf",
                content_type="application/pdf",
                actor=f"sftp:{link.access_id}",
                transport="sftp",
            )
        )
    rejected_source = tmp_path / "large-queue-rejected.tmp"
    rejected_source.write_bytes(b"rejected")
    rejected = record_staged_file_from_path(
        db_session,
        link=link,
        source_path=rejected_source,
        filename="1-NON-WOVENS/FRANCE/LARGE/archive-rejected.tmp",
        content_type="application/octet-stream",
        actor=f"sftp:{link.access_id}",
        transport="sftp",
    )
    rejected.status = "rejected"
    rejected.rejection_reason = "Synthetic rejected file must stay out of default archive."
    db_session.commit()

    response = _client(db_session, workspace, user).get("/sftp/deposits/archive")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert "_manifest.json" in names
        manifest = json.loads(archive.read("_manifest.json"))
        archived_files = [item for item in names if item != "_manifest.json"]
        assert len(archived_files) == 80
        assert manifest["workspace"] == "andritz"
        assert manifest["file_count"] == 80
        assert len(manifest["files"]) == 80
        assert all("/received/" in item["archive_path"] for item in manifest["files"])
        assert {item["status"] for item in manifest["files"]} == {"received"}
        assert rejected.id not in {item["file_id"] for item in manifest["files"]}
        assert any(item.endswith("archive-download-079.pdf") for item in archived_files)

    event = (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "deposit.queue.downloaded")
        .one()
    )
    assert event.details["file_count"] == 80
    assert event.details["status"] is None
    assert event.details["archive_filename"].endswith(".zip")
    assert db_session.query(KnowledgeCollection).count() == 0
    assert db_session.query(WorkspaceJob).count() == 0
    for row in rows:
        db_session.refresh(row)
        assert row.status == "received"
        assert row.promoted_at is None
        assert row.worker_job_id is None
        assert row.promotion_result is None
    db_session.refresh(rejected)
    assert rejected.status == "rejected"
    assert rejected.promoted_at is None
    assert rejected.worker_job_id is None


def test_bulk_promote_supported_documents_uses_one_worker_job(db_session, monkeypatch, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path / "secure-deposit"))
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "object-store"))
    monkeypatch.setattr(secure_deposit, "_enforce", lambda *args, **kwargs: None)

    workspace = Workspace(id="ws-andritz", name="Andritz", slug="andritz", settings={"features": {"secure_deposit": True}})
    user = User(id="user-1", email="operator@example.test", username="thib")
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


def test_bulk_promote_with_missing_id_is_atomic_and_read_only(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path / "secure-deposit"))
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "object-store"))
    monkeypatch.setattr(secure_deposit, "_enforce", lambda *args, **kwargs: None)

    workspace = Workspace(id="ws-bulk-missing", name="Bulk Missing", slug="andritz", settings={"features": {"secure_deposit": True}})
    user = User(id="user-bulk-missing", email="bulk-missing@datategy.net", username="bulk-missing")
    db_session.add_all([workspace, user])
    db_session.commit()
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="Synthetic stale-id upload",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )

    rows = []
    for index in range(2):
        source = tmp_path / f"bulk-missing-{index}.pdf"
        source.write_bytes(b"%PDF-1.4\n% synthetic")
        rows.append(
            record_staged_file_from_path(
                db_session,
                link=link,
                source_path=source,
                filename=f"1-NON-WOVENS/FRANCE/GEOTEX/bulk-missing-{index}.pdf",
                content_type="application/pdf",
                actor=f"sftp:{link.access_id}",
                transport="sftp",
            )
        )
    db_session.commit()

    def fail_batch_promote(*_args, **_kwargs):
        raise AssertionError("missing-id validation must happen before batch promotion")

    monkeypatch.setattr(secure_deposit, "promote_files_to_collection_batch", fail_batch_promote)

    response = _client(db_session, workspace, user).post(
        "/sftp/deposits/promote-bulk",
        json={
            "collection_slug": "andritz-non-wovens-france-excel-pilot",
            "file_ids": [rows[0].id, "stale-missing-file-id", rows[1].id],
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "message": "Some deposit files were not found",
        "file_ids": ["stale-missing-file-id"],
    }
    for row in rows:
        db_session.refresh(row)
        assert row.status == "received"
        assert row.promoted_at is None
        assert row.promoted_by_user_id is None
        assert row.promoted_collection_slug is None
        assert row.worker_job_id is None
        assert row.promotion_result is None


def test_bulk_promote_rejects_oversized_selection_before_lookup_or_mutation(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path / "secure-deposit"))
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "object-store"))
    monkeypatch.setattr(secure_deposit, "_enforce", lambda *args, **kwargs: None)

    workspace = Workspace(id="ws-bulk-limit", name="Bulk Limit", slug="andritz", settings={"features": {"secure_deposit": True}})
    user = User(id="user-bulk-limit", email="bulk-limit@datategy.net", username="bulk-limit")
    db_session.add_all([workspace, user])
    db_session.commit()
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="Synthetic bulk limit upload",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )

    rows = []
    for index in range(2):
        source = tmp_path / f"bulk-limit-{index}.pdf"
        source.write_bytes(b"%PDF-1.4\n% synthetic")
        rows.append(
            record_staged_file_from_path(
                db_session,
                link=link,
                source_path=source,
                filename=f"1-NON-WOVENS/FRANCE/GEOTEX/bulk-limit-{index}.pdf",
                content_type="application/pdf",
                actor=f"sftp:{link.access_id}",
                transport="sftp",
            )
        )
    db_session.commit()

    def fail_batch_promote(*_args, **_kwargs):
        raise AssertionError("oversized bulk validation must happen before batch promotion")

    monkeypatch.setattr(secure_deposit, "promote_files_to_collection_batch", fail_batch_promote)

    response = _client(db_session, workspace, user).post(
        "/sftp/deposits/promote-bulk",
        json={
            "collection_slug": "andritz-non-wovens-france-excel-pilot",
            "file_ids": [rows[0].id, rows[1].id] + [f"synthetic-extra-{index}" for index in range(49)],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Bulk promotion is limited to 50 files"
    assert db_session.query(KnowledgeCollection).count() == 0
    assert db_session.query(WorkspaceJob).count() == 0
    for row in rows:
        db_session.refresh(row)
        assert row.status == "received"
        assert row.promoted_at is None
        assert row.promoted_by_user_id is None
        assert row.promoted_collection_slug is None
        assert row.worker_job_id is None
        assert row.promotion_result is None


def test_deposit_indexing_assist_recommends_and_summarizes_collection(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path / "secure-deposit"))
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "object-store"))
    monkeypatch.setattr(settings, "secure_deposit_archive_promotion_max_files", 50)
    monkeypatch.setattr(secure_deposit, "_enforce", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.services.secure_deposit.is_workspace_enabled", lambda workspace: True)

    workspace = Workspace(id="ws-assist", name="Assist", slug="assist", settings={"features": {"secure_deposit": True}})
    user = User(id="user-assist", email="operator@example.test", username="operator")
    collection = KnowledgeCollection(
        id="collection-assist",
        workspace_id=workspace.id,
        name="assist-secure-deposit",
        slug="assist-secure-deposit",
        vector_collection_name="assist-secure-deposit",
        artifact_prefix="workspaces/ws-assist/knowledge/assist-secure-deposit",
        status="ready",
        document_count=1,
        chunk_count=12,
    )
    db_session.add_all([workspace, user, collection])
    db_session.commit()
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="Indexing assist",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )

    manual = tmp_path / "manual.txt"
    manual.write_text("maintenance procedure", encoding="utf-8")
    recommended = record_staged_file_from_path(
        db_session,
        link=link,
        source_path=manual,
        filename="Manuals/manual.txt",
        content_type="text/plain",
        actor=f"sftp:{link.access_id}",
        transport="sftp",
    )

    archive_path = tmp_path / "large-manual.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for index in range(11):
            archive.writestr(f"docs/chapter-{index}.txt", f"chapter {index}")
    inspect_archive = record_staged_file_from_path(
        db_session,
        link=link,
        source_path=archive_path,
        filename="Archives/large-manual.zip",
        content_type="application/zip",
        actor=f"sftp:{link.access_id}",
        transport="sftp",
    )

    promoted_source = tmp_path / "already.pdf"
    promoted_source.write_bytes(b"%PDF already indexed")
    promoted = record_staged_file_from_path(
        db_session,
        link=link,
        source_path=promoted_source,
        filename="Already/already.pdf",
        content_type="application/pdf",
        actor=f"sftp:{link.access_id}",
        transport="sftp",
    )
    promoted.status = "promoted"
    promoted.promoted_collection_slug = collection.slug
    db_session.commit()

    response = _client(db_session, workspace, user).post(
        "/sftp/deposits/indexing-assist",
        json={
            "collection_slug": collection.slug,
            "file_ids": [recommended.id, inspect_archive.id, promoted.id],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["collection"]["exists"] is True
    assert body["collection"]["slug"] == collection.slug
    assert body["collection"]["chunk_count"] == 12
    assert body["summary"]["recommended_file_ids"] == [recommended.id]
    assert body["summary"]["recommended_count"] == 1
    assert body["summary"]["inspect_archive_count"] == 1
    assert body["summary"]["already_promoted_count"] == 1

    recommendations = {item["file_id"]: item for item in body["recommendations"]}
    assert recommendations[recommended.id]["recommendation"] == "promote_now"
    assert recommendations[recommended.id]["eligible_for_batch"] is True
    assert recommendations[inspect_archive.id]["recommendation"] == "inspect_archive"
    assert recommendations[inspect_archive.id]["archive"]["supported_document_count"] == 11
    assert recommendations[promoted.id]["recommendation"] == "already_promoted"


def test_deposit_indexing_assist_unknown_file_is_advisory_and_read_only(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(tmp_path / "secure-deposit"))
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "object-store"))
    monkeypatch.setattr(secure_deposit, "_enforce", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.services.secure_deposit.is_workspace_enabled", lambda workspace: True)

    workspace = Workspace(id="ws-assist-unknown", name="Assist Unknown", slug="andritz", settings={"features": {"secure_deposit": True}})
    user = User(id="user-assist-unknown", email="assist-unknown@example.test", username="assist-unknown")
    db_session.add_all([workspace, user])
    db_session.commit()
    link, _ = create_link(
        db_session,
        workspace=workspace,
        user=user,
        label="Indexing assist unknown",
        expires_at=None,
        max_file_size_mb=30 * 1024,
        allowed_extensions=[],
    )

    source = tmp_path / "equipment.telemetry"
    source.write_bytes(b"raw binary-ish telemetry")
    staged = record_staged_file_from_path(
        db_session,
        link=link,
        source_path=source,
        filename="1-NON-WOVENS/FRANCE/GEOTEX/equipment.telemetry",
        content_type="application/octet-stream",
        actor=f"sftp:{link.access_id}",
        transport="sftp",
    )
    db_session.commit()

    response = _client(db_session, workspace, user).post(
        "/sftp/deposits/indexing-assist",
        json={
            "collection_slug": "andritz-non-wovens-france-excel-pilot",
            "file_ids": [staged.id],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["total_files"] == 1
    assert body["summary"]["found_files"] == 1
    assert body["summary"]["unsupported_count"] == 1
    assert body["summary"]["recommended_count"] == 0
    assert body["summary"]["recommended_file_ids"] == []
    assert len(body["recommendations"]) == 1
    recommendation = body["recommendations"][0]
    assert recommendation["file_id"] == staged.id
    assert recommendation["filename"] == "1-NON-WOVENS/FRANCE/GEOTEX/equipment.telemetry"
    assert recommendation["status"] == "received"
    assert recommendation["extension"] == "telemetry"
    assert recommendation["recommendation"] == "unsupported"
    assert recommendation["label"] == "Unsupported"
    assert recommendation["reason"] == ".telemetry is not currently supported for Knowledge promotion."
    assert recommendation["eligible_for_batch"] is False
    assert recommendation["size_bytes"] == staged.size_bytes
    assert recommendation["archive"] is None
    assert recommendation["target_collection_slug"] == "andritz-non-wovens-france-excel-pilot"
    assert recommendation["promoted_collection_slug"] is None
    assert recommendation["worker_job_id"] is None
    assert recommendation["promotion_result"] is None
    assert db_session.query(KnowledgeCollection).count() == 0
    assert db_session.query(WorkspaceJob).count() == 0
    db_session.refresh(staged)
    assert staged.status == "received"
    assert staged.promoted_at is None
    assert staged.promoted_collection_slug is None
    assert staged.worker_job_id is None
    assert staged.promotion_result is None


def test_sftp_operations_lists_active_sidecar_upload(db_session, monkeypatch, tmp_path):
    storage = tmp_path / "secure-deposit"
    temp_dir = storage / "_sftp_uploads"
    temp_dir.mkdir(parents=True)
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(storage))
    monkeypatch.setattr(settings, "secure_deposit_sftp_temp_dir", str(temp_dir))
    monkeypatch.setattr(secure_deposit, "_enforce", lambda *args, **kwargs: None)

    workspace = Workspace(id="ws-andritz", name="Andritz", slug="andritz", settings={"features": {"secure_deposit": True}})
    user = User(id="user-1", email="operator@example.test", username="thib")
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

    workspace = Workspace(id="ws-andritz", name="Andritz", slug="andritz", settings={"features": {"secure_deposit": True}})
    user = User(id="user-1", email="operator@example.test", username="thib")
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


def test_object_store_reconciliation_is_refused_before_a_job(db_session, monkeypatch, tmp_path):
    storage = tmp_path / "secure-deposit"
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(storage))
    monkeypatch.setattr(settings, "secure_deposit_storage_backend", "object_store")
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "object-store"))
    monkeypatch.setattr(secure_deposit, "_enforce", lambda *args, **kwargs: None)

    workspace = Workspace(
        id="ws-object-reconcile",
        name="Object",
        slug="object-reconcile",
        settings={"features": {"secure_deposit": True}},
    )
    user = User(id="user-object-reconcile", email="operator@example.test", username="thib")
    db_session.add_all([workspace, user])
    db_session.commit()

    response = _client(db_session, workspace, user).post(
        "/sftp/operations/reconcile", json={"mode": "dry_run", "stale_after_hours": 24}
    )

    assert response.status_code == 409
    assert "object store" in response.json()["detail"]
    assert db_session.query(WorkspaceJob).filter(WorkspaceJob.kind == "sftp_reconciliation").count() == 0


def test_sftp_quarantine_skips_partial_that_became_recent(db_session, monkeypatch, tmp_path):
    storage = tmp_path / "secure-deposit"
    temp_dir = storage / "_sftp_uploads"
    temp_dir.mkdir(parents=True)
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(storage))
    monkeypatch.setattr(settings, "secure_deposit_sftp_temp_dir", str(temp_dir))
    monkeypatch.setattr(settings, "worker_eager_mode", True)
    monkeypatch.setattr(secure_deposit, "_enforce", lambda *args, **kwargs: None)

    workspace = Workspace(id="ws-andritz", name="Andritz", slug="andritz", settings={"features": {"secure_deposit": True}})
    user = User(id="user-1", email="operator@example.test", username="thib")
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
