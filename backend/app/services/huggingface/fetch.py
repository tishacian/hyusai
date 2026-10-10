"""Acquisition entry point used exclusively by the dedicated hub_fetch worker."""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.config import settings
from app.services.huggingface.errors import HFError
from app.services.huggingface.storage import CHUNK_BYTES, HubStore, blob_key, safe_path

_CDN_HOSTS = frozenset(
    {
        "cdn-lfs.huggingface.co",
        "cdn-lfs-us-1.hf.co",
        "cdn-lfs-eu-1.hf.co",
        "cas-bridge.xethub.hf.co",
    }
)
# Regional CloudFront hosts, e.g. us.aws.cdn.hf.co.
_CDN_SUFFIX = ".cdn.hf.co"


def _trusted_download_url(url: str, endpoint: str) -> bool:
    try:
        parsed, origin = urlsplit(url), urlsplit(endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
            or "\\" in url
            or any(c.isspace() for c in url)
        ):
            return False
        if (parsed.scheme, parsed.netloc) == (origin.scheme, origin.netloc):
            return True
        public_hub = endpoint == "https://huggingface.co"
        allowed = set(_CDN_HOSTS) if public_hub else set()
        allowed.update(
            host.strip().lower()
            for host in os.getenv("HF_ALLOWED_DOWNLOAD_HOSTS", "").split(",")
            if host.strip()
        )
        host = parsed.hostname.lower()
        return parsed.port in (None, 443) and (
            host in allowed or (public_hub and host.endswith(_CDN_SUFFIX))
        )
    except ValueError:
        return False


def stream_file(client, metadata: dict, path: str):
    """Follow a short trusted redirect chain, never exporting the Hub token."""
    connection = client.connection
    url = connection.endpoint + client._file_path(metadata, safe_path(path))
    token_allowed = True
    try:
        with httpx.Client(
            timeout=httpx.Timeout(120, connect=15),
            follow_redirects=False,
            transport=client.transport,
        ) as session:
            for _ in range(6):
                if not _trusted_download_url(url, connection.endpoint):
                    raise HFError(
                        "HF_REDIRECT_FORBIDDEN",
                        "The Hub returned an untrusted download destination.",
                        502,
                    )
                same_origin = urlsplit(url)[:2] == urlsplit(connection.endpoint)[:2]
                token_allowed = token_allowed and same_origin
                headers = {"Accept-Encoding": "identity", "User-Agent": "Agentium-Hub-Fetch/1"}
                if token_allowed and connection.token:
                    headers["Authorization"] = "Bearer " + connection.token
                with session.stream("GET", url, headers=headers) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise HFError(
                                "HF_REDIRECT_FORBIDDEN",
                                "The Hub returned an invalid download redirect.",
                                502,
                            )
                        url = urljoin(url, location)
                        continue
                    if response.status_code in (401, 403):
                        raise HFError(
                            "HF_AUTH_REQUIRED",
                            "The workspace connection cannot download this file.",
                            403,
                        )
                    if response.status_code == 404:
                        raise HFError(
                            "HF_NOT_FOUND",
                            "The pinned file is no longer available on the Hub.",
                            404,
                        )
                    if response.status_code != 200:
                        raise HFError(
                            "HF_UPSTREAM_ERROR",
                            "The Hub download failed.",
                            502,
                            {"upstream_status": response.status_code},
                        )
                    if response.headers.get("content-encoding", "identity").lower() not in {
                        "",
                        "identity",
                    }:
                        raise HFError(
                            "HF_UPSTREAM_ERROR",
                            "Hub file downloads must preserve their unencoded byte stream.",
                            502,
                        )
                    yield from response.iter_bytes(CHUNK_BYTES)
                    return
            raise HFError("HF_REDIRECT_FORBIDDEN", "Too many download redirects.", 502)
    except httpx.HTTPError:
        raise HFError("HF_UNREACHABLE", "The Hub download was interrupted.", 502) from None


def _inspect_configuration(store: HubStore, key: str, path: str, size: int):
    if path.rsplit("/", 1)[-1] not in {"config.json", "modules.json", "tokenizer_config.json"}:
        return
    if size > 8 * CHUNK_BYTES:
        raise HFError("HF_TOO_LARGE", "A model configuration exceeds the metadata limit.")
    with store.open(key) as stream:
        try:
            config = json.loads(stream.read(8 * CHUNK_BYTES + 1))
        except (ValueError, UnicodeDecodeError):
            raise HFError("HF_UNSAFE_FORMAT", "The model configuration is invalid JSON.") from None
    if isinstance(config, dict) and (config.get("trust_remote_code") or config.get("auto_map")):
        raise HFError(
            "HF_REMOTE_CODE_REQUIRED",
            "Custom Python model or tokenizer implementations are not supported.",
        )
    if isinstance(config, list):
        from app.services.huggingface.adapters import MODULES

        for module in config:
            if not isinstance(module, dict) or str(module.get("type", "")) not in MODULES:
                raise HFError(
                    "HF_REMOTE_CODE_REQUIRED",
                    "Custom sentence-transformers modules are not supported.",
                )


def base_manifest(artifact) -> dict:
    from app.services.huggingface.policy import license_digest

    metadata = artifact.metadata_json or {}
    return {
        "version": 2,
        "artifact_id": artifact.id,
        "hub_endpoint": artifact.hub_endpoint,
        "kind": artifact.kind,
        "repo_id": artifact.repo_id,
        "revision": artifact.revision,
        "requested_ref": artifact.requested_ref,
        "format": artifact.format,
        "variant": artifact.variant,
        "selection_digest": artifact.selection_digest,
        "selection": dict(artifact.selection_json or {}),
        "license": metadata.get("license"),
        "license_class": metadata.get("license_class"),
        "license_text": metadata.get("license_text", ""),
        "license_digest": license_digest(metadata, metadata.get("license_text", "")),
        "gated": bool(metadata.get("gated")),
        "private": bool(metadata.get("private")),
        "pipeline_tag": metadata.get("pipeline_tag"),
        "library": metadata.get("library"),
    }


def execute_import(db, artifact, job, *, client=None, store: HubStore | None = None) -> dict:
    """Return a published model manifest or a staged dataset acquisition.

    The registry owns admission, lease and final ready transition. The only
    handoff to the dataset worker contains object keys and checksums, never a
    Hub credential or a remotely chosen URL.
    """
    from app.models.workspace import Workspace
    from app.services.huggingface.client import HFClient
    from app.services.huggingface.connection import Connection
    from app.services.huggingface.registry import effective_limits, touch_import

    if client is None:
        workspace = db.query(Workspace).filter(Workspace.id == job.workspace_id).first()
        client = HFClient(Connection.resolve(db, workspace))
    if client.connection.endpoint != artifact.hub_endpoint:
        raise HFError(
            "HF_ACCESS_REVOKED", "The workspace Hub connection changed after admission.", 403
        )
    store = store or HubStore()
    metadata = dict(artifact.metadata_json or {})
    metadata.update(kind=artifact.kind, repo_id=artifact.repo_id, revision=artifact.revision)
    if metadata.get("private") or metadata.get("gated"):
        # Shared bytes do not substitute for proof by this workspace's current
        # credential when a queued import finally executes.
        client.check_access(metadata, require_workspace_token=True)
    selection = artifact.selection_json or {}
    if artifact.kind == "dataset":
        from app.services.huggingface.datasets import validate_plan

        validate_plan(metadata, selection)
    files = dict(artifact.files_json or {})
    if not files:
        raise HFError("HF_UNSAFE_FORMAT", "The artifact has no selected safe files.")
    total = sum(int(entry["size_bytes"]) for entry in files.values())
    limits = effective_limits(db)
    max_bytes = int(
        limits["dataset_max_bytes"] if artifact.kind == "dataset" else limits["model_max_bytes"]
    )
    if total > max_bytes:
        raise HFError("HF_TOO_LARGE", "The selected files exceed the download limit.")
    disk_root = Path(settings.hf_cache_dir)
    while not disk_root.exists() and disk_root != disk_root.parent:
        disk_root = disk_root.parent
    if shutil.disk_usage(disk_root).free - total * 2 < settings.hf_disk_min_free_bytes:
        raise HFError(
            "HF_QUOTA_EXCEEDED", "The worker has insufficient disk headroom for this import.", 409
        )
    lease_owner = (job.result or {}).get("lease_owner")
    transferred, last_touch = 0, 0.0

    def progress(count):
        nonlocal transferred, last_touch
        transferred += count
        now = time.monotonic()
        if now - last_touch >= 5:
            if shutil.disk_usage(disk_root).free < settings.hf_disk_min_free_bytes:
                raise HFError(
                    "HF_QUOTA_EXCEEDED",
                    "The shared disk reached its reserved free-space margin.",
                    409,
                )
            touch_import(
                db,
                job.id,
                "fetching",
                min(85, int(85 * transferred / max(1, total))),
                lease_owner=lease_owner,
            )
            db.commit()
            last_touch = now

    verified = {}
    try:
        for path, expected in files.items():
            path = safe_path(path)
            key = (
                f"hub/tmp/{job.id}/{path}"
                if artifact.kind == "dataset"
                else blob_key(artifact, path)
            )
            chunks = stream_file(client, metadata, path)
            try:
                verified[path] = store.publish_verified(
                    key, chunks, expected, max_bytes=max_bytes, progress=progress
                )
            finally:
                chunks.close()
            _inspect_configuration(store, key, path, verified[path]["size_bytes"])
        manifest = base_manifest(artifact)
        manifest.update(
            files=verified, total_bytes=sum(item["size_bytes"] for item in verified.values())
        )
        if artifact.kind == "dataset":
            manifest.update(pending_dataset=True, source_files=verified)
            return manifest
        store.publish_manifest(artifact.id, manifest)
        return manifest
    except BaseException:
        try:
            store.delete_temporary(job.id)
        except Exception:
            pass  # Recovery retries temporary cleanup; preserve the real error.
        raise
