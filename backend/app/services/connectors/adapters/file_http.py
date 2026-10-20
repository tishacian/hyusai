"""HTTP files and Graph drive imports; signed download links never enter lineage."""

from __future__ import annotations

import re
from urllib.parse import quote, unquote, urlencode, urlsplit

from app.services.connectors.adapters import http
from app.services.connectors.adapters.object_clients import endpoint, object_key
from app.services.connectors.adapters.sql import AdapterError


class HTTPFile:
    def __init__(self, config, credentials, deadline):
        self.url = endpoint(config["url"])
        self.deadline = deadline
        token = credentials.get("bearer_token") or credentials.get("access_token")
        self.headers = {"Authorization": "Bearer " + token} if token else {}
        self.filename = config.get("filename") or urlsplit(self.url).path.rsplit("/", 1)[-1]
        if not self.filename:
            raise AdapterError("CONNECTOR_FILENAME_REQUIRED")

    def manifest(self):
        headers, _ = http.request("HEAD", self.url, headers=self.headers, deadline_at=self.deadline)
        try:
            size = int(headers["content-length"])
        except (KeyError, ValueError):
            raise AdapterError("CONNECTOR_SOURCE_SIZE_REQUIRED") from None
        if size < 0:
            raise AdapterError("CONNECTOR_SOURCE_SIZE_REQUIRED")
        return [
            {
                "key": self.filename,
                "size": size,
                "etag": headers.get("etag"),
                "modified_at": headers.get("last-modified"),
            }
        ]

    def download(self, item, path, max_bytes):
        headers = dict(self.headers)
        if item.get("etag"):
            headers["If-Match"] = item["etag"]
        result = http.download(
            self.url, path, headers=headers, max_bytes=max_bytes, deadline_at=self.deadline
        )
        if result[1] != item["size"] or (
            item.get("etag") and result[0].get("etag") != item["etag"]
        ):
            raise AdapterError("CONNECTOR_SOURCE_CHANGED")
        return result


class GraphFiles:
    def __init__(self, config, credentials, deadline):
        self.config, self.deadline = config, deadline
        self.root = config.get("prefix", "").strip("/")
        token = credentials.get("access_token") or credentials.get("bearer_token")
        if not token:
            tenant = config.get("tenant_id", "")
            if not re.fullmatch(r"[0-9a-fA-F-]{36}", tenant):
                raise AdapterError("CONNECTOR_TENANT_INVALID")
            _, reply = http.json_request(
                "POST",
                f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
                deadline_at=deadline,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                content=urlencode(
                    {
                        "grant_type": "client_credentials",
                        "client_id": config["client_id"],
                        "client_secret": credentials["client_secret"],
                        "scope": "https://graph.microsoft.com/.default",
                    }
                ).encode(),
            )
            token = reply.get("access_token")
        if not token:
            raise AdapterError("CONNECTOR_AUTH_DENIED")
        self.headers = {"Authorization": "Bearer " + token}
        drive = config["drive_id"]
        if not re.fullmatch(r"[A-Za-z0-9!_-]{1,255}", drive):
            raise AdapterError("CONNECTOR_DRIVE_INVALID")
        self.base = "https://graph.microsoft.com/v1.0/drives/" + quote(drive, safe="")
        self.items = {}

    def _url(self, key):
        return self.base + "/root" + (":/" + quote(key, safe="/") + ":" if key else "")

    def _get(self, url):
        parsed = urlsplit(url)
        decoded = unquote(parsed.path)
        base = urlsplit(self.base)
        if (
            parsed.scheme != "https"
            or parsed.netloc != base.netloc
            or not decoded.startswith(base.path + "/")
            or ".." in decoded.split("/")
            or "\\" in decoded
            or parsed.fragment
        ):
            raise AdapterError("CONNECTOR_PAGINATION_INVALID")
        return http.json_request("GET", url, headers=self.headers, deadline_at=self.deadline)[1]

    def manifest(self, key=None):
        root = object_key(key if key is not None else self.root, self.root)
        entry = self._get(self._url(root))
        pending = [(root, entry)]
        found = []
        while pending:
            path, item = pending.pop()
            if "file" in item:
                if not item.get("eTag") or not isinstance(item.get("size"), int):
                    raise AdapterError("CONNECTOR_OBJECT_IDENTITY_INVALID")
                self.items[item["id"]] = item
                found.append(
                    {
                        "key": path,
                        "size": item["size"],
                        "etag": item["eTag"],
                        "id": item["id"],
                        "modified_at": item.get("lastModifiedDateTime"),
                    }
                )
            elif "folder" in item:
                url = self.base + "/items/" + quote(item["id"], safe="") + "/children?$top=200"
                seen = set()
                while url:
                    if (
                        url in seen
                        or len(seen) > 10000
                        or not url.startswith(self.base + "/items/")
                    ):
                        raise AdapterError("CONNECTOR_PAGINATION_INVALID")
                    seen.add(url)
                    reply = self._get(url)
                    for child in reply.get("value", []):
                        name = child.get("name", "")
                        if "/" in name or "\\" in name or not name:
                            raise AdapterError("CONNECTOR_OBJECT_KEY_INVALID")
                        child_path = object_key((path + "/" if path else "") + name, self.root)
                        pending.append((child_path, child))
                    url = reply.get("@odata.nextLink")
            if len(found) + len(pending) > 10000:
                raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
        return sorted(found, key=lambda row: row["key"])

    def download(self, item, path, max_bytes):
        metadata_url = self.base + "/items/" + quote(item["id"], safe="")
        metadata = self._get(metadata_url)
        if metadata.get("eTag") != item["etag"]:
            raise AdapterError("CONNECTOR_SOURCE_CHANGED")
        url = metadata.get("@microsoft.graph.downloadUrl", "")
        parsed = urlsplit(url)
        hosts = self.config.get("download_hosts", [])
        # Graph's temporary links can use a separate SharePoint origin. Only
        # explicit administrator-selected hosts are allowed, never bearer auth.
        if (
            parsed.scheme != "https"
            or parsed.hostname not in hosts
            or parsed.username
            or parsed.password
        ):
            raise AdapterError("CONNECTOR_DOWNLOAD_ORIGIN_DENIED")
        result = http.download(url, path, deadline_at=self.deadline, max_bytes=max_bytes)
        after = self._get(metadata_url)
        if after.get("eTag") != item["etag"] or result[1] != item["size"]:
            raise AdapterError("CONNECTOR_SOURCE_CHANGED")
        return result


def execute(
    operation,
    config,
    credentials,
    parameters,
    deadline_at,
    output_dir,
    *,
    dialect,
    access=None,
    limits=None,
):
    from app.services.connectors.adapters.object_store import MAX_IMPORT_BYTES, _bounded_int, _stage

    if operation not in ("test", "catalog", "list", "table", "preview", "import"):
        raise AdapterError("CONNECTOR_OPERATION_UNSUPPORTED")
    if set(parameters) - {"key", "limit", "max_rows", "max_bytes"}:
        raise AdapterError("CONNECTOR_PARAMETERS_INVALID")
    client = (
        HTTPFile(config, credentials, deadline_at)
        if dialect == "http_files"
        else GraphFiles(config, credentials, deadline_at)
    )
    objects = (
        client.manifest() if dialect == "http_files" else client.manifest(parameters.get("key"))
    )
    max_bytes = _bounded_int(parameters, "max_bytes", MAX_IMPORT_BYTES, MAX_IMPORT_BYTES)
    if sum(item["size"] for item in objects) > max_bytes:
        raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
    if operation in ("test", "catalog", "list"):
        return {"connected": True, "objects": objects, "source": "real"}
    limit = _bounded_int(
        parameters, "limit", 100, min(1000, (limits or {}).get("preview_rows", 100))
    )
    max_rows = _bounded_int(parameters, "max_rows", 3000000, 10000000)
    return _stage(
        client,
        objects,
        output_dir,
        operation=operation,
        max_rows=max_rows,
        max_bytes=max_bytes,
        deadline=deadline_at,
        preview_limit=limit,
    )
