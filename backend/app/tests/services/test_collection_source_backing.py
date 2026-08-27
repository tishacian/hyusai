from __future__ import annotations

import hashlib
import zipfile

import pytest

from app.core.config import settings
from app.models.secure_deposit import DepositAccessLink, DepositFile
from app.models.user import User
from app.models.workspace import Workspace
from app.services.collection_source_backing import (
    SourceBackingError,
    backing_source_meta,
    copy_or_materialize_collection_source,
    materialize_backing_source,
    read_backing_source_bytes,
)


def _deposit(db_session, tmp_path, monkeypatch, *, content: bytes, filename: str):
    root = tmp_path / "secure-deposit"
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(root))
    workspace = Workspace(id="ws-source", slug="source", name="Source")
    user = User(id="user-source", username="source", email="source@example.test")
    link = DepositAccessLink(
        id="link-source",
        workspace_id=workspace.id,
        created_by_user_id=user.id,
        label="Source",
        access_id="source-link",
        password_hash="hash",
        allowed_extensions=[],
    )
    object_key = f"workspaces/{workspace.id}/secure-deposit/source/{filename}"
    path = root / object_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    row = DepositFile(
        id="deposit-source",
        workspace_id=workspace.id,
        access_link_id=link.id,
        filename=filename,
        object_key=object_key,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        status="received",
    )
    db_session.add_all([workspace, user, link, row])
    db_session.commit()
    return workspace, row, path


def test_direct_secure_deposit_source_is_symlinked_and_validated(
    db_session, tmp_path, monkeypatch
):
    workspace, row, source = _deposit(
        db_session,
        tmp_path,
        monkeypatch,
        content=b"Needlepunch manual 61035",
        filename="Notices_Techniques_Needlepunch/60000-69999/61035/manual.pdf",
    )
    locator = {
        "kind": "secure_deposit_file",
        "deposit_file_id": row.id,
        "size_bytes": row.size_bytes,
        "sha256": row.sha256,
    }
    destination = tmp_path / "job" / "manual.pdf"

    materialize_backing_source(
        db_session,
        workspace_id=workspace.id,
        locator=locator,
        destination=destination,
    )

    assert destination.is_symlink()
    assert destination.resolve() == source.resolve()
    assert read_backing_source_bytes(
        db_session, workspace_id=workspace.id, locator=locator
    ) == source.read_bytes()
    assert backing_source_meta(
        db_session, workspace_id=workspace.id, locator=locator
    ) == (True, len(source.read_bytes()))

    source.write_bytes(b"X" * len(source.read_bytes()))
    with pytest.raises(SourceBackingError, match="content_changed"):
        read_backing_source_bytes(
            db_session,
            workspace_id=workspace.id,
            locator=locator,
        )

    source.write_bytes(b"tampered but same physical length"[: row.size_bytes])
    with pytest.raises(SourceBackingError, match="content_changed"):
        read_backing_source_bytes(
            db_session, workspace_id=workspace.id, locator=locator
        )


def test_collection_source_locator_never_calls_object_store_copy(
    db_session, tmp_path, monkeypatch
):
    workspace, row, source = _deposit(
        db_session,
        tmp_path,
        monkeypatch,
        content=b"Needlepunch source remains in Secure Deposit",
        filename="Notices_Techniques_Needlepunch/60000-69999/61035/manual.txt",
    )
    destination = tmp_path / "job" / "manual.txt"

    def _unexpected_copy(_destination):
        raise AssertionError("no-copy source must not read collection object store")

    copy_or_materialize_collection_source(
        db_session,
        workspace_id=workspace.id,
        metadata={
            "source_locator": {
                "kind": "secure_deposit_file",
                "deposit_file_id": row.id,
                "size_bytes": row.size_bytes,
                "sha256": row.sha256,
            }
        },
        destination=destination,
        copy_object_store_source=_unexpected_copy,
    )

    assert destination.is_symlink()
    assert destination.resolve() == source.resolve()


def test_malformed_governed_locator_fails_closed_without_legacy_copy(
    db_session, tmp_path
):
    copied = False

    def _legacy_copy(_destination):
        nonlocal copied
        copied = True

    with pytest.raises(SourceBackingError, match="invalid_secure_deposit"):
        copy_or_materialize_collection_source(
            db_session,
            workspace_id="ws-source",
            metadata={
                "source_locator": {
                    "kind": "secure_deposit_file",
                    # A governed marker without an immutable deposit identity
                    # must never fall through to a same-named legacy original.
                }
            },
            destination=tmp_path / "job" / "manual.pdf",
            copy_object_store_source=_legacy_copy,
        )

    assert copied is False


def test_secure_deposit_source_rejects_workspace_and_sha_mismatch(
    db_session, tmp_path, monkeypatch
):
    workspace, row, _source = _deposit(
        db_session,
        tmp_path,
        monkeypatch,
        content=b"manual",
        filename="manual.pdf",
    )
    locator = {
        "kind": "secure_deposit_file",
        "deposit_file_id": row.id,
        "sha256": "0" * 64,
    }

    with pytest.raises(SourceBackingError, match="sha_mismatch"):
        materialize_backing_source(
            db_session,
            workspace_id=workspace.id,
            locator=locator,
            destination=tmp_path / "bad.pdf",
        )
    with pytest.raises(SourceBackingError, match="not_found"):
        materialize_backing_source(
            db_session,
            workspace_id="another-workspace",
            locator={**locator, "sha256": row.sha256},
            destination=tmp_path / "wrong.pdf",
        )


def test_zip_member_source_is_bounded_and_traversal_is_rejected(
    db_session, tmp_path, monkeypatch
):
    archive_path = tmp_path / "source.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("manual/chapter.pdf", b"chapter 61038")
    workspace, row, source = _deposit(
        db_session,
        tmp_path,
        monkeypatch,
        content=archive_path.read_bytes(),
        filename="Notices_Techniques_Needlepunch/60000-69999/61038/manuals.zip",
    )
    locator = {
        "kind": "secure_deposit_zip_member",
        "deposit_file_id": row.id,
        "sha256": row.sha256,
        "size_bytes": row.size_bytes,
        "member_path": "manual/chapter.pdf",
        "member_size_bytes": len(b"chapter 61038"),
        "member_sha256": hashlib.sha256(b"chapter 61038").hexdigest(),
    }
    destination = tmp_path / "chapter.pdf"

    materialize_backing_source(
        db_session,
        workspace_id=workspace.id,
        locator=locator,
        destination=destination,
    )
    assert destination.read_bytes() == b"chapter 61038"
    assert not destination.is_symlink()
    assert read_backing_source_bytes(
        db_session, workspace_id=workspace.id, locator=locator
    ) == b"chapter 61038"

    changed_archive = bytearray(source.read_bytes())
    changed_archive[-1] ^= 1
    source.write_bytes(changed_archive)
    with pytest.raises(SourceBackingError, match="source_content_changed"):
        read_backing_source_bytes(
            db_session, workspace_id=workspace.id, locator=locator
        )
    source.write_bytes(archive_path.read_bytes())

    with pytest.raises(SourceBackingError, match="member_sha_mismatch"):
        read_backing_source_bytes(
            db_session,
            workspace_id=workspace.id,
            locator={**locator, "member_sha256": "0" * 64},
        )

    for unsafe_member in (
        "../secret.pdf",
        "manual\\chapter.pdf",
        "manual//chapter.pdf",
        "manual/./chapter.pdf",
    ):
        with pytest.raises(SourceBackingError, match="unsafe"):
            materialize_backing_source(
                db_session,
                workspace_id=workspace.id,
                locator={**locator, "member_path": unsafe_member},
                destination=tmp_path / "unsafe.pdf",
            )


def test_an_equal_sized_replacement_is_caught_however_fast_it_happens(
    db_session, tmp_path, monkeypatch
):
    """The check must not depend on the filesystem's clock resolution.

    The archive digest used to be memoised on the source's stat tuple — size,
    inode, mtime, ctime — which reads as a physical revision and is not one. Two
    writes of equal-length content inside a single timestamp tick share that
    tuple, so the second was answered with the first one's digest: the one check
    between a replaced archive and a reader returned a verdict about bytes that
    were gone. Equal size with the timestamps unchanged is the shape a tamper
    takes, so the memo failed on the case it existed to catch — and only where
    timestamps are coarse, which is a mount rather than a laptop.

    Written as a loop because a single pass can straddle a tick by luck and pass
    for the wrong reason. Twenty rewrites in a row cannot all straddle one.
    """

    import os

    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as writer:
        writer.writestr("manual/chapter.pdf", b"chapter 61038")
    workspace, row, source = _deposit(
        db_session,
        tmp_path,
        monkeypatch,
        content=archive.read_bytes(),
        filename="manuals.zip",
    )
    locator = {
        "kind": "secure_deposit_zip_member",
        "deposit_file_id": row.id,
        "sha256": row.sha256,
        "size_bytes": row.size_bytes,
        "member_path": "manual/chapter.pdf",
        "member_size_bytes": len(b"chapter 61038"),
        "member_sha256": hashlib.sha256(b"chapter 61038").hexdigest(),
    }
    honest = source.read_bytes()
    stat_before = source.stat()

    for _ in range(20):
        # The archive is read once so anything memoising has its chance.
        assert read_backing_source_bytes(
            db_session, workspace_id=workspace.id, locator=locator
        ) == b"chapter 61038"

        tampered = bytearray(honest)
        tampered[-1] ^= 1
        source.write_bytes(tampered)
        # Every observable the stat tuple carries, put back: same length by
        # construction, same inode because the file was written in place, and
        # the timestamps restored by hand.
        os.utime(source, ns=(stat_before.st_atime_ns, stat_before.st_mtime_ns))
        assert source.stat().st_size == stat_before.st_size
        assert source.stat().st_ino == stat_before.st_ino

        with pytest.raises(SourceBackingError, match="source_content_changed"):
            read_backing_source_bytes(
                db_session, workspace_id=workspace.id, locator=locator
            )

        source.write_bytes(honest)
        os.utime(source, ns=(stat_before.st_atime_ns, stat_before.st_mtime_ns))
