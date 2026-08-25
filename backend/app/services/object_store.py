"""Canonical artifact store for RAG originals, ingested text and derived files."""
from __future__ import annotations

import shutil
from pathlib import Path, PurePosixPath
from typing import Iterable

from app.core.config import settings


def _clean_key(key: str) -> str:
    path = PurePosixPath(str(key).replace("\\", "/"))
    parts = [p for p in path.parts if p not in ("", "/", ".")]
    if any(p == ".." for p in parts):
        raise ValueError(f"Invalid object key: {key!r}")
    return "/".join(parts)


class ObjectStore:
    """Small storage facade with a local default and optional fsspec backend."""

    def __init__(self) -> None:
        self.backend = (settings.object_store_backend or "local").lower()
        self.base_path = Path(settings.object_store_base_path)
        self._fs = None

    def key(self, *parts: object) -> str:
        return _clean_key("/".join(str(p).strip("/") for p in parts if str(p).strip("/")))

    def collection_prefix(self, workspace_id: str, collection_id: str) -> str:
        return self.key("workspaces", workspace_id, "knowledge-collections", collection_id)

    def _local_path(self, key: str) -> Path:
        clean = _clean_key(key)
        path = (self.base_path / clean).resolve()
        root = self.base_path.resolve()
        if root not in path.parents and path != root:
            raise ValueError(f"Object key escapes store root: {key!r}")
        return path

    def _fsspec(self):
        if self._fs is not None:
            return self._fs
        try:
            import fsspec  # type: ignore
        except ImportError as exc:
            raise RuntimeError("fsspec is required for non-local object storage") from exc

        if self.backend == "s3":
            if not settings.object_store_s3_bucket:
                raise RuntimeError("OBJECT_STORE_S3_BUCKET is required for s3 object storage")
            kwargs = {}
            if settings.object_store_s3_endpoint_url:
                kwargs["client_kwargs"] = {
                    "endpoint_url": settings.object_store_s3_endpoint_url,
                }
            self._fs = fsspec.filesystem(
                "s3",
                key=settings.object_store_s3_access_key,
                secret=settings.object_store_s3_secret_key,
                **kwargs,
            )
        else:
            self._fs = fsspec.filesystem(self.backend)
        return self._fs

    def _remote_key(self, key: str) -> str:
        clean = _clean_key(key)
        if self.backend == "s3":
            return f"{settings.object_store_s3_bucket}/{clean}"
        return clean

    def uri(self, key: str) -> str:
        """The absolute URI of a key, for readers that are not this facade.

        Every path *inside* Agentium travels as a bare key and is resolved by
        this class. This method exists for the one reader that is deliberately
        outside it: a stock MLflow client pointed at our registry, which is
        handed a model version's ``source`` and must resolve it with no
        knowledge of our conventions. That portability is the reason the
        artifacts are an MLflow directory in the first place.
        """

        clean = _clean_key(key)
        if self.backend == "s3":
            return f"s3://{settings.object_store_s3_bucket}/{clean}"
        return self._local_path(clean).as_uri()

    def write_bytes(self, key: str, content: bytes) -> str:
        clean = _clean_key(key)
        if self.backend == "local":
            path = self._local_path(clean)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return clean
        fs = self._fsspec()
        remote = self._remote_key(clean)
        parent = str(PurePosixPath(remote).parent)
        if parent and parent != ".":
            fs.makedirs(parent, exist_ok=True)
        with fs.open(remote, "wb") as out:
            out.write(content)
        return clean

    def write_text(self, key: str, content: str) -> str:
        return self.write_bytes(key, content.encode("utf-8"))

    def read_bytes(self, key: str) -> bytes:
        clean = _clean_key(key)
        if self.backend == "local":
            return self._local_path(clean).read_bytes()
        with self._fsspec().open(self._remote_key(clean), "rb") as src:
            return src.read()

    def copy_to_local(self, key: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if self.backend == "local":
            shutil.copy2(self._local_path(key), destination)
        else:
            with self._fsspec().open(self._remote_key(key), "rb") as src, destination.open("wb") as dst:
                shutil.copyfileobj(src, dst)
        return destination

    def exists(self, key: str) -> bool:
        clean = _clean_key(key)
        if self.backend == "local":
            return self._local_path(clean).exists()
        return bool(self._fsspec().exists(self._remote_key(clean)))

    def list_keys(self, prefix: str) -> list[str]:
        clean_prefix = _clean_key(prefix)
        if self.backend == "local":
            root = self._local_path(clean_prefix)
            if not root.exists():
                return []
            if root.is_file():
                return [clean_prefix]
            keys = []
            for path in root.rglob("*"):
                if path.is_file():
                    keys.append(path.relative_to(self.base_path.resolve()).as_posix())
            return sorted(keys)

        fs = self._fsspec()
        remote_prefix = self._remote_key(clean_prefix)
        if not fs.exists(remote_prefix):
            return []
        raw: Iterable[str] = fs.find(remote_prefix)
        bucket = f"{settings.object_store_s3_bucket}/" if self.backend == "s3" else ""
        return sorted(str(p)[len(bucket):] if bucket and str(p).startswith(bucket) else str(p) for p in raw)

    def size(self, key: str) -> int | None:
        clean = _clean_key(key)
        try:
            if self.backend == "local":
                path = self._local_path(clean)
                if path.is_file():
                    return path.stat().st_size
                if path.is_dir():
                    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
                return None
            fs = self._fsspec()
            remote = self._remote_key(clean)
            if fs.isfile(remote):
                return int(fs.size(remote))
            return sum(int(fs.size(p)) for p in fs.find(remote))
        except Exception:
            return None

    def delete_prefix(self, prefix: str) -> None:
        clean = _clean_key(prefix)
        if self.backend == "local":
            path = self._local_path(clean)
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.exists():
                path.unlink()
            return
        fs = self._fsspec()
        remote = self._remote_key(clean)
        if fs.exists(remote):
            fs.rm(remote, recursive=True)


def get_object_store() -> ObjectStore:
    return ObjectStore()
