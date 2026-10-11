"""Immutable Hub objects, with bounded streaming and conditional publication.

Multipart parts are invisible until their source checksum has passed. Completion
uses If-None-Match, so retries and simultaneous selections cannot replace a
published key. Every failed upload aborts its multipart transaction.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from app.core.config import settings
from app.services.huggingface.errors import HFError
from app.services.object_store import ObjectStore, get_object_store

CHUNK_BYTES = 1024 * 1024
PART_BYTES = 8 * CHUNK_BYTES


def safe_path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 1000
        or "\\" in value
        or "\0" in value
        or PurePosixPath(value).is_absolute()
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise HFError("HF_PATH_INVALID", "Hub paths must be relative, normalized POSIX paths.")
    return value


def blob_key(artifact, path: str) -> str:
    endpoint = hashlib.sha256(artifact.hub_endpoint.encode()).hexdigest()[:24]
    return safe_path(
        f"hub/blobs/{endpoint}/{artifact.kind}/{artifact.repo_id}/{artifact.revision}/{safe_path(path)}"
    )


def manifest_key(artifact_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", artifact_id):
        raise HFError("HF_PATH_INVALID", "Invalid artifact identifier.")
    return f"hub/artifacts/{artifact_id}/manifest.json"


class _Digest:
    def __init__(self, expected: dict, max_bytes: int):
        self.size = expected.get("size_bytes")
        upstream = expected.get("upstream_hash") or {}
        self.algorithm, self.expected = upstream.get("algorithm"), upstream.get("value")
        length = {"sha256": 64, "git-blob-sha1": 40}.get(self.algorithm)
        if not length or not re.fullmatch(rf"[0-9a-f]{{{length}}}", str(self.expected)):
            raise HFError(
                "HF_CHECKSUM_UNAVAILABLE", "Every file requires a supported source checksum."
            )
        if (
            not isinstance(self.size, int)
            or isinstance(self.size, bool)
            or not 0 <= self.size <= max_bytes
        ):
            raise HFError("HF_TOO_LARGE", "The file exceeds its admitted byte limit.")
        self.count = 0
        self.sha256 = hashlib.sha256()
        self.git = hashlib.sha1(f"blob {self.size}\0".encode())

    def update(self, chunk: bytes):
        self.count += len(chunk)
        if self.count > self.size:
            raise HFError("HF_TOO_LARGE", "The transfer exceeds its admitted byte length.")
        self.sha256.update(chunk)
        self.git.update(chunk)

    def finish(self) -> dict:
        actual = self.sha256.hexdigest() if self.algorithm == "sha256" else self.git.hexdigest()
        if self.count != self.size or actual != self.expected:
            raise HFError(
                "HF_CHECKSUM_MISMATCH", "The file does not match its pinned source checksum."
            )
        return {
            "size_bytes": self.count,
            "sha256": self.sha256.hexdigest(),
            "upstream_hash": {"algorithm": self.algorithm, "value": self.expected},
        }


class HubStore:
    def __init__(
        self,
        object_store: ObjectStore | None = None,
        *,
        s3_client=None,
        use_hub_credentials: bool = True,
    ):
        self.store = object_store or get_object_store()
        self._client = s3_client
        self.use_hub_credentials = use_hub_credentials

    @property
    def client(self):
        if self._client is None:
            import boto3

            # The worker's role-specific identity must be explicitly configured;
            # never silently substitute the API/tabular role for Hub writes.
            access = (
                os.getenv("HF_S3_ACCESS_KEY")
                if self.use_hub_credentials
                else settings.object_store_s3_access_key
            )
            secret = (
                os.getenv("HF_S3_SECRET_KEY")
                if self.use_hub_credentials
                else settings.object_store_s3_secret_key
            )
            if not access or not secret:
                raise HFError(
                    "HF_STORAGE_UNCONFIGURED",
                    "Configure the dedicated Hub object-store identity.",
                    503,
                )
            self._client = boto3.client(
                "s3",
                endpoint_url=settings.object_store_s3_endpoint_url,
                aws_access_key_id=access,
                aws_secret_access_key=secret,
            )
        return self._client

    @property
    def bucket(self):
        if not settings.object_store_s3_bucket:
            raise HFError("HF_STORAGE_UNCONFIGURED", "Configure the Hub object-store bucket.", 503)
        return settings.object_store_s3_bucket

    @contextmanager
    def open(self, key: str):
        key = safe_path(key)
        if self.store.backend == "local":
            with self.store._local_path(key).open("rb") as stream:
                yield stream
        elif self.store.backend == "s3":
            stream = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
            try:
                yield stream
            finally:
                stream.close()
        else:
            raise HFError(
                "HF_STORAGE_UNCONFIGURED", "Hub artifacts require local or S3 storage.", 503
            )

    def exists(self, key: str) -> bool:
        key = safe_path(key)
        if self.store.backend == "local":
            return self.store._local_path(key).is_file()
        if self.store.backend != "s3":
            raise HFError(
                "HF_STORAGE_UNCONFIGURED", "Hub artifacts require local or S3 storage.", 503
            )
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as exc:
            if str(getattr(exc, "response", {}).get("Error", {}).get("Code")) in {
                "404",
                "NoSuchKey",
                "NotFound",
            }:
                return False
            raise

    def verify(self, key: str, expected: dict, *, max_bytes: int, progress=None) -> dict:
        digest = _Digest(expected, max_bytes)
        with self.open(key) as stream:
            for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
                digest.update(chunk)
                if progress:
                    progress(len(chunk))
        result = digest.finish()
        if expected.get("sha256") and result["sha256"] != expected["sha256"]:
            raise HFError(
                "HF_CHECKSUM_MISMATCH", "The stored file does not match the artifact manifest."
            )
        return {**result, "object_key": key}

    def publish_verified(
        self, key: str, chunks: Iterable[bytes], expected: dict, *, max_bytes: int, progress=None
    ) -> dict:
        key = safe_path(key)
        if self.use_hub_credentials and not key.startswith("hub/"):
            raise HFError("HF_PATH_INVALID", "The Hub writer is restricted to hub/.")
        digest = _Digest(expected, max_bytes)
        if self.exists(key):
            return self.verify(key, expected, max_bytes=max_bytes, progress=progress)
        if self.store.backend == "local":
            target = self.store._local_path(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(
                    dir=target.parent, prefix=".hf-part-", delete=False
                ) as stream:
                    temporary = Path(stream.name)
                    for chunk in chunks:
                        digest.update(chunk)
                        stream.write(chunk)
                        if progress:
                            progress(len(chunk))
                    stream.flush()
                    os.fsync(stream.fileno())
                result = digest.finish()
                try:
                    os.link(temporary, target)  # atomic no-replace, same filesystem
                except FileExistsError:
                    return self.verify(key, expected, max_bytes=max_bytes)
                return {**result, "object_key": key}
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        if self.store.backend != "s3":
            raise HFError(
                "HF_STORAGE_UNCONFIGURED", "Hub artifacts require local or S3 storage.", 503
            )
        upload = self.client.create_multipart_upload(Bucket=self.bucket, Key=key)["UploadId"]
        completed = False
        try:
            parts, pending = [], bytearray()

            def send_part(content: bytes):
                number = len(parts) + 1
                response = self.client.upload_part(
                    Bucket=self.bucket, Key=key, UploadId=upload, PartNumber=number, Body=content
                )
                parts.append({"PartNumber": number, "ETag": response["ETag"]})

            for chunk in chunks:
                digest.update(chunk)
                # The caller streams 1 MiB chunks; slicing also bounds memory if
                # another caller yields a larger source buffer.
                view = memoryview(chunk)
                while view:
                    take = min(PART_BYTES - len(pending), len(view))
                    pending.extend(view[:take])
                    view = view[take:]
                    if len(pending) == PART_BYTES:
                        send_part(bytes(pending))
                        pending.clear()
                if progress:
                    progress(len(chunk))
            result = digest.finish()
            if pending or not parts:
                send_part(bytes(pending))
            try:
                self.client.complete_multipart_upload(
                    Bucket=self.bucket,
                    Key=key,
                    UploadId=upload,
                    MultipartUpload={"Parts": parts},
                    IfNoneMatch="*",
                )
                completed = True
            except Exception as exc:
                if str(getattr(exc, "response", {}).get("Error", {}).get("Code")) in {
                    "412",
                    "PreconditionFailed",
                }:
                    return self.verify(key, expected, max_bytes=max_bytes)
                # Unsupported conditional completion fails closed, never retry
                # with an unconditional write on an older S3-compatible server.
                raise
            return {**result, "object_key": key}
        finally:
            if not completed:
                self.client.abort_multipart_upload(Bucket=self.bucket, Key=key, UploadId=upload)

    def publish_file(self, key: str, path: Path, *, max_bytes: int) -> dict:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
                digest.update(chunk)
        expected = {
            "size_bytes": path.stat().st_size,
            "upstream_hash": {"algorithm": "sha256", "value": digest.hexdigest()},
        }
        with path.open("rb") as stream:
            return self.publish_verified(
                key, iter(lambda: stream.read(CHUNK_BYTES), b""), expected, max_bytes=max_bytes
            )

    def publish_manifest(self, artifact_id: str, manifest: dict) -> str:
        content = json.dumps(
            manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
        expected = {
            "size_bytes": len(content),
            "upstream_hash": {"algorithm": "sha256", "value": hashlib.sha256(content).hexdigest()},
        }
        key = manifest_key(artifact_id)
        self.publish_verified(key, [content], expected, max_bytes=8 * CHUNK_BYTES)
        return key

    def copy_verified(self, key: str, path: Path, expected: dict, *, max_bytes: int):
        digest = _Digest(
            {**expected, "upstream_hash": {"algorithm": "sha256", "value": expected["sha256"]}},
            max_bytes,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        created = False
        try:
            with self.open(key) as stream, path.open("xb") as target:
                created = True
                for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
                    digest.update(chunk)
                    target.write(chunk)
            digest.finish()
        except BaseException:
            if created:
                path.unlink(missing_ok=True)
            raise
        return path

    def delete_temporary(self, job_id: str):
        prefix = safe_path(f"hub/tmp/{job_id}") + "/"
        if self.store.backend == "local":
            self.store.delete_prefix(prefix)
            return
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                self.delete(obj["Key"])

    def presign(self, key: str, ttl: int = 300) -> str:
        if self.store.backend != "s3":
            raise HFError("HF_STORAGE_UNCONFIGURED", "Remote nodes require S3 object storage.", 503)
        if not isinstance(ttl, int) or not 1 <= ttl <= 300:
            raise HFError(
                "HF_URL_TTL_INVALID", "Artifact URLs may remain valid for at most five minutes."
            )
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": safe_path(key)}, ExpiresIn=ttl
        )

    def delete(self, key: str):
        """Lifecycle caller must check references and runtime leases first."""
        key = safe_path(key)
        if self.store.backend == "local":
            self.store._local_path(key).unlink(missing_ok=True)
        elif self.store.backend == "s3":
            # MinIO production buckets are versioned. A delete marker is not
            # physical deletion, so remove the exact key's versions as well.
            found = False
            paginator = self.client.get_paginator("list_object_versions")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=key):
                for version in [*page.get("Versions", []), *page.get("DeleteMarkers", [])]:
                    if version["Key"] != key:
                        continue
                    found = True
                    self.client.delete_object(
                        Bucket=self.bucket, Key=key, VersionId=version["VersionId"]
                    )
            if not found:
                self.client.delete_object(Bucket=self.bucket, Key=key)
        else:
            raise HFError(
                "HF_STORAGE_UNCONFIGURED", "Hub artifacts require local or S3 storage.", 503
            )

    def cleanup_abandoned_uploads(self, *, older_than):
        """Release crash-abandoned parts after the maximum import deadline.

        Even a running worker may not publish after that deadline. Model objects
        already completed are never removed by this temporary-space collector.
        """
        cleaned = 0
        if self.store.backend == "local":
            root = self.store._local_path("hub")
            for path in root.rglob(".hf-part-*") if root.exists() else []:
                if path.is_file() and path.stat().st_mtime < older_than.timestamp():
                    path.unlink(missing_ok=True)
                    cleaned += 1
            return cleaned
        paginator = self.client.get_paginator("list_multipart_uploads")
        for page in paginator.paginate(Bucket=self.bucket, Prefix="hub/"):
            for upload in page.get("Uploads", []):
                initiated = upload["Initiated"]
                if initiated.timestamp() < older_than.timestamp():
                    self.client.abort_multipart_upload(
                        Bucket=self.bucket, Key=upload["Key"], UploadId=upload["UploadId"]
                    )
                    cleaned += 1
        return cleaned

    def cleanup_abandoned_sources(self, *, active_job_ids: set[str], older_than):
        """Remove old completed staging objects with no live reservation."""
        cleaned = 0
        if self.store.backend == "local":
            root = self.store._local_path("hub/tmp")
            for path in root.rglob("*") if root.exists() else []:
                if (
                    path.is_file()
                    and path.relative_to(root).parts[0] not in active_job_ids
                    and path.stat().st_mtime < older_than.timestamp()
                ):
                    path.unlink(missing_ok=True)
                    cleaned += 1
            return cleaned
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix="hub/tmp/"):
            for item in page.get("Contents", []):
                parts = item["Key"].split("/")
                if (
                    len(parts) >= 4
                    and parts[2] not in active_job_ids
                    and item["LastModified"].timestamp() < older_than.timestamp()
                ):
                    self.delete(item["Key"])
                    cleaned += 1
        return cleaned
