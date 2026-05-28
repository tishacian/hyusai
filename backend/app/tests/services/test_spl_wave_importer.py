from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.services.secure_deposit import _read_supported_archive_documents
from app.services.spl_wave_importer import (
    WaveLimits,
    build_v2_wave_plans,
    build_v3_wave_plans,
    build_wave_plan,
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
        email="thibaud.ishacian@datategy.net",
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
    user = User(id="user-1", username="thib", email="thibaud.ishacian@datategy.net")
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
    user = User(id="user-1", username="thib", email="thibaud.ishacian@datategy.net")
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
    user = User(id="user-1", username="thib", email="thibaud.ishacian@datategy.net")
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
