"""Bounded Hub metadata client; model and dataset bytes belong to hub-fetch."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import quote, urljoin, urlsplit

import httpx

from app.services.huggingface.connection import Connection
from app.services.huggingface.errors import HFError

SHA = re.compile(r"^[0-9a-f]{40}$")
_REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)?$")
MAX_METADATA_BYTES = 8 * 1024 * 1024
MAX_LICENSE_BYTES = 1024 * 1024
MAX_FILES = 20000


def validate_repo(kind: str, repo_id: str) -> tuple[str, str]:
    if kind not in {"model", "dataset"}:
        raise HFError("HF_KIND_INVALID", "Choose a model or dataset repository.")
    if (
        not isinstance(repo_id, str)
        or not _REPO.fullmatch(repo_id)
        or ".." in repo_id
        or len(repo_id) > 200
    ):
        raise HFError("HF_REPO_INVALID", "Invalid Hub repository identifier.")
    return kind + "s", quote(repo_id, safe="/")


def normalize_file(item: dict) -> dict:
    lfs = item.get("lfs") or {}
    source_hash = (
        {"algorithm": "sha256", "value": lfs.get("oid") or lfs.get("sha256")}
        if lfs
        else {"algorithm": "git-blob-sha1", "value": item.get("oid") or item.get("blobId")}
    )
    return {
        "path": item.get("path") or item.get("rfilename"),
        "size_bytes": item.get("size", lfs.get("size")),
        "upstream_hash": source_hash,
    }


class HFClient:
    def __init__(self, connection: Connection, *, transport: httpx.BaseTransport | None = None):
        self.connection = connection
        self.transport = transport

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        # Each bounded request already closes its HTTP client and response.
        return False

    def _request(
        self,
        path: str,
        *,
        params=None,
        method="GET",
        max_bytes=MAX_METADATA_BYTES,
        allow_redirect=False,
        missing_ok=False,
    ) -> httpx.Response:
        url = urljoin(self.connection.endpoint + "/", path)
        if urlsplit(url)[:2] != urlsplit(self.connection.endpoint)[:2]:
            raise HFError(
                "HF_REDIRECT_FORBIDDEN", "The Hub returned an untrusted destination.", 502
            )
        headers = {"Accept": "application/json", "User-Agent": "Agentium-Hub/1"}
        if self.connection.token:
            headers["Authorization"] = "Bearer " + self.connection.token
        try:
            with httpx.Client(
                timeout=httpx.Timeout(30, connect=10),
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                with client.stream(method, url, params=params, headers=headers) as response:
                    status = response.status_code
                    if status in (401, 403):
                        raise HFError(
                            "HF_ACCESS_DENIED",
                            "The selected Hub connection cannot access this resource.",
                            403,
                        )
                    if status == 404 and not missing_ok:
                        raise HFError(
                            "HF_NOT_FOUND",
                            "The repository, revision or file is not accessible.",
                            404,
                        )
                    if status == 429:
                        raise HFError(
                            "HF_RATE_LIMITED", "The Hub rate limit was reached; retry later.", 429
                        )
                    if 300 <= status < 400 and not allow_redirect:
                        raise HFError(
                            "HF_REDIRECT_FORBIDDEN", "A Hub metadata redirect was refused.", 502
                        )
                    if status >= 400 and not (missing_ok and status == 404):
                        raise HFError(
                            "HF_UPSTREAM_ERROR",
                            "The Hub could not complete the request.",
                            502,
                            {"upstream_status": status},
                        )
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            raise HFError(
                                "HF_METADATA_LIMIT",
                                "The Hub response exceeds the metadata limit.",
                                413,
                            )
                    return httpx.Response(
                        status,
                        headers=response.headers,
                        content=bytes(body),
                        request=response.request,
                    )
        except httpx.HTTPError:
            raise HFError("HF_UNREACHABLE", "The Hub is unreachable.", 502) from None

    @staticmethod
    def _json(response: httpx.Response):
        try:
            return response.json()
        except ValueError:
            raise HFError(
                "HF_METADATA_INVALID", "The Hub returned malformed metadata.", 502
            ) from None

    def test(self) -> dict:
        path = "/api/whoami-v2" if self.connection.token else "/api/models"
        self._request(path, params=None if self.connection.token else {"limit": 1})
        return {"status": "connected", **self.connection.public()}

    def search(self, kind: str = "model", query: str = "", limit: int = 20) -> list[dict]:
        plural, _ = validate_repo(kind, "valid")
        if not 1 <= limit <= 100 or len(query) > 200:
            raise HFError(
                "HF_SEARCH_INVALID", "Search accepts up to 200 characters and 1 to 100 results."
            )
        rows = self._json(
            self._request(
                f"/api/{plural}",
                params={"search": query, "limit": limit, "full": "true", "cardData": "true"},
            )
        )
        if not isinstance(rows, list):
            raise HFError("HF_METADATA_INVALID", "The Hub returned an invalid search result.", 502)
        return [self._metadata(kind, row) for row in rows[:limit] if isinstance(row, dict)]

    def _metadata(self, kind: str, data: dict) -> dict:
        card = data.get("cardData") or {}
        if not isinstance(card, dict):
            card = {}
        license_tag = card.get("license")
        if not license_tag:
            license_tag = next(
                (
                    tag[8:]
                    for tag in data.get("tags", [])
                    if isinstance(tag, str) and tag.startswith("license:")
                ),
                None,
            )
        # Ambiguous/multiple author declarations fail closed at policy review.
        if not isinstance(license_tag, str):
            license_tag = "unknown"
        config = data.get("config") or {}
        return {
            "hub_endpoint": self.connection.endpoint,
            "kind": kind,
            "repo_id": data.get("id") or data.get("modelId"),
            "revision": data.get("sha"),
            "license": license_tag.lower(),
            "gated": bool(data.get("gated")),
            "private": bool(data.get("private")),
            "pipeline_tag": data.get("pipeline_tag"),
            "library": data.get("library_name"),
            "card_data": card,
            "security": data.get("securityRepoStatus") or {},
            "requires_remote_code": bool(
                (config.get("auto_map") if isinstance(config, dict) else False)
                or "custom_code" in (data.get("tags") or [])
            ),
        }

    def repo_info(self, kind: str, repo_id: str, revision: str = "main") -> dict:
        plural, repo = validate_repo(kind, repo_id)
        if not revision or len(revision) > 200 or any(c in revision for c in "\x00\r\n"):
            raise HFError("HF_REVISION_INVALID", "Invalid Hub revision.")
        data = self._json(
            self._request(
                f"/api/{plural}/{repo}/revision/{quote(revision, safe='')}",
                params={"blobs": "true"},
            )
        )
        if not isinstance(data, dict) or not SHA.fullmatch(str(data.get("sha", ""))):
            raise HFError(
                "HF_REVISION_INVALID", "The Hub did not resolve this revision to a commit.", 502
            )
        if SHA.fullmatch(revision) and data["sha"] != revision:
            raise HFError("HF_REVISION_MISMATCH", "The Hub returned a different commit.", 502)
        metadata = self._metadata(kind, data)
        metadata.update(
            repo_id=repo_id, requested_ref=revision, files=self.tree(kind, repo_id, data["sha"])
        )
        return metadata

    def tree(self, kind: str, repo_id: str, revision: str) -> list[dict]:
        plural, repo = validate_repo(kind, repo_id)
        if not SHA.fullmatch(revision):
            raise HFError("HF_REVISION_INVALID", "A file tree requires an immutable commit.")
        base = f"/api/{plural}/{repo}/tree/{revision}"
        path, params = base, {"recursive": "true", "expand": "false"}
        files = []
        seen_pages = set()
        for _ in range(200):
            if path in seen_pages:
                raise HFError("HF_METADATA_INVALID", "The Hub returned a cyclic file listing.", 502)
            seen_pages.add(path)
            response = self._request(path, params=params)
            rows = self._json(response)
            if not isinstance(rows, list):
                raise HFError(
                    "HF_METADATA_INVALID", "The Hub returned an invalid file listing.", 502
                )
            files.extend(
                normalize_file(row)
                for row in rows
                if isinstance(row, dict) and row.get("type") == "file"
            )
            if len(files) > MAX_FILES:
                raise HFError("HF_METADATA_LIMIT", "The repository has too many files.", 413)
            path = (response.links.get("next") or {}).get("url")
            if not path:
                return files
            parsed = urlsplit(urljoin(self.connection.endpoint, path))
            if parsed[:2] != urlsplit(self.connection.endpoint)[:2] or parsed.path != base:
                raise HFError(
                    "HF_REDIRECT_FORBIDDEN", "The Hub returned an untrusted pagination URL.", 502
                )
            params = None
        raise HFError("HF_METADATA_LIMIT", "The repository listing exceeds the page limit.", 413)

    def check_access(self, metadata: dict, *, require_workspace_token: bool = True) -> None:
        if not metadata.get("private") and not metadata.get("gated"):
            return
        if not self.connection.token or (
            require_workspace_token and self.connection.source != "workspace"
        ):
            raise HFError(
                "HF_WORKSPACE_TOKEN_REQUIRED",
                "A workspace Hub token must prove access to private or gated repositories.",
                403,
            )
        files = metadata.get("files") or []
        if not files:
            raise HFError("HF_ACCESS_DENIED", "The repository contains no accessible files.", 403)
        # Gated repositories may expose metadata and README while denying weights.
        # Probe every selected payload when provided, or at least a weight/data file.
        payloads = [
            item
            for item in files
            if str(item.get("path", "")).endswith(
                (".safetensors", ".gguf", ".onnx", ".parquet", ".bin", ".pt")
            )
        ]
        for item in payloads[:1] or files[:1]:
            self._request(
                self._file_path(metadata, item["path"]), method="HEAD", allow_redirect=True
            )

    def _file_path(self, metadata: dict, path: str) -> str:
        kind, repo = validate_repo(metadata["kind"], metadata["repo_id"])
        revision = metadata["revision"]
        if (
            not SHA.fullmatch(revision)
            or not path
            or path.startswith("/")
            or any(part in ("", ".", "..") for part in path.split("/"))
            or "\\" in path
        ):
            raise HFError("HF_PATH_INVALID", "The Hub returned an invalid file path.", 502)
        prefix = "datasets/" if kind == "datasets" else ""
        return f"/{prefix}{repo}/resolve/{revision}/{quote(path, safe='/')}"

    def license_evidence(self, metadata: dict) -> dict:
        paths = [
            item["path"]
            for item in metadata.get("files", [])
            if str(item.get("path", "")).upper()
            in {"LICENSE", "LICENSE.TXT", "LICENSE.MD", "LICENCE", "LICENSE-MIT", "LICENSE-APACHE"}
        ]
        text = ""
        for path in sorted(paths):
            response = self._request(
                self._file_path(metadata, path), max_bytes=MAX_LICENSE_BYTES, allow_redirect=True
            )
            # Hub Git files may redirect to its same-origin resolve cache. Never
            # send the token to a CDN or a license_url from author metadata.
            for _ in range(3):
                if not response.is_redirect:
                    break
                response = self._request(
                    response.headers.get("location", ""),
                    max_bytes=MAX_LICENSE_BYTES,
                    allow_redirect=True,
                )
            if response.is_redirect:
                raise HFError("HF_REDIRECT_FORBIDDEN", "Too many license metadata redirects.", 502)
            try:
                text += f"--- {path} ---\n" + response.content.decode("utf-8") + "\n"
            except UnicodeError:
                raise HFError("HF_LICENSE_INVALID", "The license text is not UTF-8.", 422) from None
        return {"license_text": text, "license_digest": hashlib.sha256(text.encode()).hexdigest()}
