"""Upload-only SFTP gateway for Secure Deposit links."""
from __future__ import annotations

import logging
import os
import stat as stat_module
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import HTTPException

from app.core.config import settings
from app.db.base import SessionLocal
from app.models.secure_deposit import DepositAccessLink, DepositFile
from app.models.workspace import Workspace
from app.services.audit_logger import emit_audit_event
from app.services.secure_deposit import (
    assert_link_usable,
    extension_for,
    is_workspace_enabled,
    record_staged_file_from_path,
    safe_filename,
    safe_relative_path,
    verify_password,
)

logger = logging.getLogger(__name__)


_FXF_READ = 0x00000001
_FXF_WRITE = 0x00000002
_FXF_APPEND = 0x00000004


def _decode_path(path: bytes | str) -> str:
    if isinstance(path, bytes):
        return path.decode("utf-8", errors="replace")
    return path


def _remote_basename(path: bytes | str) -> str:
    raw = _decode_path(path).replace("\\", "/")
    return PurePosixPath(raw).name


def _remote_relative_path(path: bytes | str) -> str:
    raw = _decode_path(path).replace("\\", "/").strip()
    return safe_relative_path(raw.lstrip("/"))


def _remote_dir_path(path: bytes | str) -> str:
    if _is_root_path(path):
        return ""
    return _remote_relative_path(path)


def _is_root_path(path: bytes | str) -> bool:
    raw = _decode_path(path).strip()
    return raw in {"", ".", "/"}


def _sftp_temp_dir() -> Path:
    path = Path(settings.secure_deposit_sftp_temp_dir).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _max_bytes(link: DepositAccessLink) -> int:
    return int(link.max_file_size_mb or settings.secure_deposit_default_max_file_size_mb) * 1024 * 1024


def _load_active_link(access_id: str) -> DepositAccessLink:
    db = SessionLocal()
    try:
        link = db.query(DepositAccessLink).filter(DepositAccessLink.access_id == access_id).first()
        if not link:
            raise HTTPException(status_code=404, detail="Deposit link not found")
        workspace = db.query(Workspace).filter(Workspace.id == link.workspace_id).first()
        if not workspace or not is_workspace_enabled(workspace):
            raise HTTPException(status_code=403, detail="Secure Deposit is not enabled")
        assert_link_usable(db, link)
        db.expunge(link)
        db.commit()
        return link
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _virtual_file_name(file: DepositFile) -> str:
    uploaded = file.uploaded_at or datetime.utcnow()
    stamp = uploaded.strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{file.id[:8]}-{safe_filename(_remote_basename(file.filename))}"


def _list_link_files(access_id: str) -> list[dict[str, Any]]:
    db = SessionLocal()
    try:
        link = db.query(DepositAccessLink).filter(DepositAccessLink.access_id == access_id).first()
        if not link:
            return []
        files = (
            db.query(DepositFile)
            .filter(DepositFile.access_link_id == link.id)
            .order_by(DepositFile.uploaded_at.desc())
            .all()
        )
        return [
            {
                "virtual_name": _virtual_file_name(file),
                "path": safe_relative_path(file.filename),
                "filename": safe_filename(_remote_basename(file.filename)),
                "size_bytes": int(file.size_bytes or 0),
                "mtime": int((file.uploaded_at or datetime.utcnow()).timestamp()),
            }
            for file in files
        ]
    finally:
        db.close()


def _find_link_file(access_id: str, path: bytes | str) -> dict[str, Any] | None:
    rel_path = _remote_relative_path(path)
    basename = _remote_basename(path)
    for file in _list_link_files(access_id):
        if rel_path in {file["path"], file["virtual_name"]}:
            return file
        if basename in {file["virtual_name"], file["filename"]}:
            return file
    return None


def _parent_dirs(path: str) -> set[str]:
    parts = [part for part in PurePosixPath(path).parts if part not in {"", "/", "."}]
    parents: set[str] = set()
    for index in range(1, len(parts)):
        parents.add("/".join(parts[:index]))
    return parents


def _dir_exists(access_id: str, dir_path: str, session_dirs: set[str]) -> bool:
    if not dir_path or dir_path in session_dirs:
        return True
    return any(dir_path in _parent_dirs(file["path"]) for file in _list_link_files(access_id))


def _list_dir(access_id: str, dir_path: str, session_dirs: set[str]) -> list[dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    prefix = f"{dir_path}/" if dir_path else ""
    for directory in session_dirs:
        if directory == dir_path or not directory.startswith(prefix):
            continue
        child = directory[len(prefix) :].split("/", 1)[0]
        if child:
            entries.setdefault(child, {"name": child, "kind": "dir"})
    for file in _list_link_files(access_id):
        if dir_path and not file["path"].startswith(prefix):
            continue
        remainder = file["path"][len(prefix) :]
        if not remainder:
            continue
        child, _, rest = remainder.partition("/")
        if rest:
            entries.setdefault(child, {"name": child, "kind": "dir"})
        else:
            entry = dict(file)
            entry["name"] = child
            entry["kind"] = "file"
            entries[child] = entry
    return sorted(entries.values(), key=lambda item: (item["kind"] != "dir", item["name"].lower()))


def _ensure_host_key(path: Path) -> None:
    if path.exists() and path.stat().st_size > 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(path)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _build_asyncssh_components(asyncssh: Any) -> tuple[type, type]:
    class PendingDepositUpload:
        def __init__(self, *, access_id: str, filename: str, max_bytes: int, workspace_id: str):
            self.access_id = access_id
            self.filename = filename
            self.max_bytes = max_bytes
            self.workspace_id = workspace_id
            self.closed = False
            self.rejected = False
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".sftp-{safe_filename(filename)}-",
                suffix=".part",
                dir=str(_sftp_temp_dir()),
            )
            self.tmp_path = Path(tmp_name)
            self.handle = os.fdopen(fd, "w+b", buffering=0)

        def fileno(self) -> int:
            return self.handle.fileno()

        def flush(self) -> None:
            self.handle.flush()

        def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
            return self.handle.seek(offset, whence)

        def read(self, _size: int = -1) -> bytes:
            raise asyncssh.SFTPPermissionDenied("Secure Deposit is upload-only")

        def write(self, data: bytes) -> int:
            next_size = self.handle.tell() + len(data)
            if next_size > self.max_bytes:
                self.rejected = True
                emit_audit_event(
                    workspace_id=self.workspace_id,
                    event_type="deposit.file.rejected",
                    actor=f"sftp:{self.access_id}",
                    severity="warning",
                    details={
                        "access_id": self.access_id,
                        "filename": self.filename,
                        "reason": "file_too_large",
                        "transport": "sftp",
                    },
                )
                raise asyncssh.SFTPFailure("File is too large")
            return self.handle.write(data)

        def close(self) -> None:
            if self.closed:
                return
            self.closed = True
            try:
                self.handle.close()
                if self.rejected:
                    self.tmp_path.unlink(missing_ok=True)
                    return
                db = SessionLocal()
                try:
                    link = db.query(DepositAccessLink).filter(DepositAccessLink.access_id == self.access_id).first()
                    if not link:
                        raise HTTPException(status_code=404, detail="Deposit link not found")
                    record_staged_file_from_path(
                        db,
                        link=link,
                        source_path=self.tmp_path,
                        filename=self.filename,
                        content_type="application/octet-stream",
                        actor=f"sftp:{self.access_id}",
                        transport="sftp",
                    )
                    db.commit()
                except HTTPException as exc:
                    db.rollback()
                    self.tmp_path.unlink(missing_ok=True)
                    raise asyncssh.SFTPFailure(str(exc.detail))
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    self.tmp_path.unlink(missing_ok=True)
                    logger.exception("SFTP upload failed for access_id=%s filename=%s", self.access_id, self.filename)
                    raise asyncssh.SFTPFailure("Upload failed") from exc
                finally:
                    db.close()
            except asyncssh.SFTPError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.tmp_path.unlink(missing_ok=True)
                raise asyncssh.SFTPFailure("Upload failed") from exc

    class SecureDepositSSHServer(asyncssh.SSHServer):
        def connection_made(self, conn: Any) -> None:
            self._conn = conn

        def begin_auth(self, _username: str) -> bool:
            return True

        def public_key_auth_supported(self) -> bool:
            return False

        def password_auth_supported(self) -> bool:
            return True

        def validate_password(self, username: str, password: str) -> bool:
            db = SessionLocal()
            try:
                link = db.query(DepositAccessLink).filter(DepositAccessLink.access_id == username).first()
                if not link:
                    emit_audit_event(
                        workspace_id=None,
                        event_type="deposit.sftp.auth.failed",
                        actor=f"sftp:{username}",
                        severity="warning",
                        details={"access_id": username, "reason": "unknown_access_id"},
                    )
                    return False
                workspace = db.query(Workspace).filter(Workspace.id == link.workspace_id).first()
                if not workspace or not is_workspace_enabled(workspace):
                    reason = "workspace_disabled"
                    allowed = False
                else:
                    try:
                        assert_link_usable(db, link)
                        reason = ""
                        allowed = True
                    except HTTPException:
                        reason = "inactive_or_expired"
                        allowed = False
                if not allowed:
                    emit_audit_event(
                        db=db,
                        workspace_id=link.workspace_id,
                        event_type="deposit.sftp.auth.failed",
                        actor=f"sftp:{username}",
                        severity="warning",
                        details={"access_id": username, "link_id": link.id, "reason": reason},
                    )
                    db.commit()
                    return False
                if not verify_password(link.password_hash, password):
                    emit_audit_event(
                        db=db,
                        workspace_id=link.workspace_id,
                        event_type="deposit.sftp.auth.failed",
                        actor=f"sftp:{username}",
                        severity="warning",
                        details={"access_id": username, "link_id": link.id, "reason": "bad_password"},
                    )
                    db.commit()
                    return False
                emit_audit_event(
                    db=db,
                    workspace_id=link.workspace_id,
                    event_type="deposit.sftp.auth.success",
                    actor=f"sftp:{username}",
                    details={"access_id": username, "link_id": link.id},
                )
                db.commit()
                return True
            except Exception:  # noqa: BLE001
                db.rollback()
                logger.exception("SFTP auth failed unexpectedly for access_id=%s", username)
                return False
            finally:
                db.close()

    class SecureDepositSFTPServer(asyncssh.SFTPServer):
        def __init__(self, chan: Any):
            self.access_id = str(chan.get_extra_info("username") or "")
            self._directories: set[str] = set()
            super().__init__(chan)

        def _dir_attrs(self) -> Any:
            return asyncssh.SFTPAttrs(permissions=stat_module.S_IFDIR | 0o755)

        def _file_attrs(self, file: dict[str, Any]) -> Any:
            return asyncssh.SFTPAttrs(
                size=file["size_bytes"],
                permissions=stat_module.S_IFREG | 0o444,
                atime=file["mtime"],
                mtime=file["mtime"],
            )

        def realpath(self, path: bytes) -> bytes:
            rel_path = _remote_dir_path(path)
            return f"/{rel_path}".rstrip("/").encode("utf-8") or b"/"

        def stat(self, path: bytes) -> Any:
            if _is_root_path(path):
                return self._dir_attrs()
            rel_path = _remote_relative_path(path)
            file = _find_link_file(self.access_id, path)
            if file:
                return self._file_attrs(file)
            if _dir_exists(self.access_id, rel_path, self._directories):
                return self._dir_attrs()
            raise asyncssh.SFTPNoSuchFile("No such file")

        def lstat(self, path: bytes) -> Any:
            return self.stat(path)

        async def scandir(self, path: bytes) -> Any:
            dir_path = _remote_dir_path(path)
            if not _dir_exists(self.access_id, dir_path, self._directories):
                raise asyncssh.SFTPNoSuchFile("No such directory")
            for entry in _list_dir(self.access_id, dir_path, self._directories):
                attrs = self._dir_attrs() if entry["kind"] == "dir" else self._file_attrs(entry)
                yield asyncssh.SFTPName(
                    entry["name"].encode("utf-8"),
                    attrs=attrs,
                    longname=entry["name"].encode("utf-8"),
                )

        def open(self, path: bytes, pflags: int, _attrs: Any) -> Any:
            if not pflags & _FXF_WRITE:
                raise asyncssh.SFTPPermissionDenied("Secure Deposit is upload-only")
            if pflags & _FXF_APPEND:
                raise asyncssh.SFTPPermissionDenied("Append is not supported")
            filename = _remote_relative_path(path)
            if not filename or filename in {".", ".."}:
                raise asyncssh.SFTPPermissionDenied("Invalid upload filename")

            link = _load_active_link(self.access_id)
            allowed = [item.lower().lstrip(".") for item in (link.allowed_extensions or []) if item]
            ext = extension_for(filename)
            if allowed and ext not in allowed:
                raise asyncssh.SFTPPermissionDenied("File extension is not allowed")
            self._directories.update(_parent_dirs(filename))
            return PendingDepositUpload(
                access_id=self.access_id,
                filename=filename,
                max_bytes=_max_bytes(link),
                workspace_id=link.workspace_id,
            )

        def remove(self, _path: bytes) -> None:
            raise asyncssh.SFTPPermissionDenied("Secure Deposit is upload-only")

        def rename(self, _oldpath: bytes, _newpath: bytes) -> None:
            raise asyncssh.SFTPPermissionDenied("Rename is not supported")

        def mkdir(self, path: bytes, _attrs: Any) -> None:
            dir_path = _remote_dir_path(path)
            if not dir_path:
                return
            self._directories.update(_parent_dirs(f"{dir_path}/placeholder"))
            self._directories.add(dir_path)

        def rmdir(self, _path: bytes) -> None:
            raise asyncssh.SFTPPermissionDenied("Directories are not supported")

        def symlink(self, _oldpath: bytes, _newpath: bytes) -> None:
            raise asyncssh.SFTPPermissionDenied("Symlinks are not supported")

    return SecureDepositSSHServer, SecureDepositSFTPServer


async def run_sftp_server() -> None:
    import asyncssh  # Imported lazily so unit tests can run without the optional server dependency.

    host_key_path = Path(settings.secure_deposit_sftp_host_key_path).expanduser()
    _ensure_host_key(host_key_path)
    ssh_server, sftp_server = _build_asyncssh_components(asyncssh)
    server = await asyncssh.create_server(
        ssh_server,
        settings.secure_deposit_sftp_host,
        int(settings.secure_deposit_sftp_port),
        server_host_keys=[str(host_key_path)],
        sftp_factory=sftp_server,
        reuse_address=True,
    )
    logger.info(
        "Secure Deposit SFTP server listening on %s:%s",
        settings.secure_deposit_sftp_host,
        settings.secure_deposit_sftp_port,
    )
    await server.wait_closed()
