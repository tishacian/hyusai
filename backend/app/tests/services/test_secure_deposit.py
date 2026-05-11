from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.models.secure_deposit import DepositFile
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.secure_deposit import (
    authenticate_link,
    build_deposit_archive,
    create_link,
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
