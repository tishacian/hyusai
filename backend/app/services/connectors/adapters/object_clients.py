"""REST object transports. No ambient cloud credentials, proxy, redirects or deletes.

Signing uses provider protocols; all network traffic uses the common pinned
transport. Provider account qualification is delegated to the external bench.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import format_datetime
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

from app.services.connectors.adapters import http
from app.services.connectors.adapters.sql import AdapterError


def endpoint(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise AdapterError("CONNECTOR_URL_INVALID")
    return value.rstrip("/")


def object_key(value, root=""):
    if (
        not isinstance(value, str)
        or len(value) > 2048
        or any(ord(c) < 32 for c in value)
        or "\\" in value
        or value.startswith("/")
        or any(p in (".", "..") for p in value.split("/"))
    ):
        raise AdapterError("CONNECTOR_OBJECT_KEY_INVALID")
    root = root.rstrip("/")
    if root and value != root and not value.startswith(root + "/"):
        raise AdapterError("CONNECTOR_SOURCE_FORBIDDEN")
    return value


def _xml(payload):
    if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
        raise AdapterError("CONNECTOR_RESPONSE_INVALID")
    try:
        return ET.fromstring(payload)
    except ET.ParseError:
        raise AdapterError("CONNECTOR_RESPONSE_INVALID") from None


def _text(element, name, default=""):
    child = element.find("{*}" + name)
    return child.text if child is not None and child.text is not None else default


def _number(value):
    try:
        result = int(value)
        if result < 0:
            raise ValueError()
        return result
    except (ValueError, TypeError):
        raise AdapterError("CONNECTOR_RESPONSE_INVALID") from None


class ObjectClient:
    def __init__(self, config, credentials, deadline):
        self.config, self.credentials, self.deadline = config, credentials, deadline
        self.root = object_key(config.get("prefix", "")).rstrip("/")
        self.bucket = config["bucket"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,221}", self.bucket):
            raise AdapterError("CONNECTOR_BUCKET_INVALID")

    def key(self, value):
        return object_key(value, self.root)

    def download(self, item, path, max_bytes):
        url, headers = self.signed("GET", self.key(item["key"]), condition=item["etag"])
        result = http.download(
            url, path, deadline_at=self.deadline, headers=headers, max_bytes=max_bytes
        )
        if result[1] != item["size"]:
            raise AdapterError("CONNECTOR_SOURCE_CHANGED")
        return result

    def put(self, key, data: bytes, *, expected_etag=None):
        url, headers = self.signed(
            "PUT",
            self.key(key),
            content=data,
            condition=expected_etag,
            create=expected_etag is None,
        )
        result, _ = http.request(
            "PUT", url, headers=headers, content=data, deadline_at=self.deadline
        )
        return result.get("etag") or result.get("x-goog-generation")

    def read_small(self, key):
        url, headers = self.signed("GET", self.key(key))
        result, data = http.request("GET", url, headers=headers, deadline_at=self.deadline)
        return data, result.get("etag") or result.get("x-goog-generation")


class S3Client(ObjectClient):
    def __init__(self, config, credentials, deadline):
        super().__init__(config, credentials, deadline)
        self.region = config.get("region", "us-east-1")
        if not re.fullmatch(r"[a-z0-9-]{1,63}", self.region):
            raise AdapterError("CONNECTOR_REGION_INVALID")
        self.base = endpoint(config.get("endpoint") or f"https://s3.{self.region}.amazonaws.com")
        self.access_key = credentials.get("access_key")
        self.secret_key = credentials.get("secret_key")
        self.session_token = credentials.get("session_token")
        if not self.access_key or not self.secret_key:
            raise AdapterError("CONNECTOR_CREDENTIAL_REQUIRED")
        if config.get("role_arn"):
            self._assume_role()

    def _sign(self, method, url, headers, content, service="s3"):
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
        from botocore.credentials import Credentials

        req = AWSRequest(method=method, url=url, data=content, headers=headers)
        SigV4Auth(
            Credentials(self.access_key, self.secret_key, self.session_token), service, self.region
        ).add_auth(req)
        return dict(req.headers.items())

    def _assume_role(self):
        url = f"https://sts.{self.region}.amazonaws.com/"
        data = urlencode(
            {
                "Action": "AssumeRole",
                "Version": "2011-06-15",
                "RoleArn": self.config["role_arn"],
                "RoleSessionName": "agentium-connector",
                "DurationSeconds": 900,
                **(
                    {"ExternalId": self.credentials["external_id"]}
                    if self.credentials.get("external_id")
                    else {}
                ),
            }
        ).encode()
        headers = self._sign(
            "POST", url, {"Content-Type": "application/x-www-form-urlencoded"}, data, "sts"
        )
        _, body = http.request(
            "POST", url, headers=headers, content=data, deadline_at=self.deadline
        )
        credentials = _xml(body).find(".//{*}Credentials")
        if credentials is None:
            raise AdapterError("CONNECTOR_AUTH_DENIED")
        self.access_key, self.secret_key, self.session_token = (
            _text(credentials, name) for name in ("AccessKeyId", "SecretAccessKey", "SessionToken")
        )
        if not all((self.access_key, self.secret_key, self.session_token)):
            raise AdapterError("CONNECTOR_AUTH_DENIED")

    def signed(self, method, key="", *, query=None, content=b"", condition=None, create=False):
        base = self.base
        if self.config.get("path_style", True):
            url = base + "/" + quote(self.bucket, safe="") + "/" + quote(key, safe="/")
        else:
            parsed = urlsplit(base)
            if parsed.path not in ("", "/") or parsed.port:
                raise AdapterError("CONNECTOR_ENDPOINT_INVALID")
            url = f"https://{self.bucket}.{parsed.hostname}/" + quote(key, safe="/")
        if query:
            url += "?" + urlencode(query)
        headers = {"x-amz-content-sha256": hashlib.sha256(content).hexdigest()}
        if condition is not None:
            headers["If-Match"] = condition
        if create:
            headers["If-None-Match"] = "*"
        return url, self._sign(method, url, headers, content)

    def list_page(self, prefix, cursor=None):
        query = {"list-type": "2", "prefix": self.key(prefix), "max-keys": "1000"}
        if cursor:
            query["continuation-token"] = cursor
        url, headers = self.signed("GET", query=query)
        _, body = http.request("GET", url, headers=headers, deadline_at=self.deadline)
        root = _xml(body)
        objects = [
            {
                "key": self.key(_text(row, "Key")),
                "size": _number(_text(row, "Size")),
                "etag": _text(row, "ETag"),
                "modified_at": _text(row, "LastModified"),
            }
            for row in root.findall("{*}Contents")
        ]
        return objects, _text(root, "NextContinuationToken") or None


class AzureClient(ObjectClient):
    def __init__(self, config, credentials, deadline):
        super().__init__(config, credentials, deadline)
        self.account = config["account"]
        if not re.fullmatch(r"[a-z0-9]{3,24}", self.account):
            raise AdapterError("CONNECTOR_ACCOUNT_INVALID")
        # The Blob endpoint works for HNS-enabled ADLS Gen2 accounts too. No
        # rename/ACL emulation: only blob GET/list/conditional PUT is exposed.
        self.base = endpoint(
            config.get("endpoint") or f"https://{self.account}.blob.core.windows.net"
        )
        self.token = None
        if config.get("auth_mode") == "service_principal":
            tenant = config.get("tenant_id", "")
            if not re.fullmatch(r"[0-9a-fA-F-]{36}", tenant):
                raise AdapterError("CONNECTOR_TENANT_INVALID")
            _, token = http.json_request(
                "POST",
                f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
                deadline_at=deadline,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                content=urlencode(
                    {
                        "grant_type": "client_credentials",
                        "client_id": config["client_id"],
                        "client_secret": credentials["client_secret"],
                        "scope": "https://storage.azure.com/.default",
                    }
                ).encode(),
            )
            self.token = token.get("access_token")
            if not self.token:
                raise AdapterError("CONNECTOR_AUTH_DENIED")

    def signed(self, method, key="", *, query=None, content=b"", condition=None, create=False):
        path = "/" + quote(self.bucket, safe="") + "/" + quote(key, safe="/")
        query = dict(query or {})
        headers = {
            "x-ms-date": format_datetime(datetime.now(UTC), usegmt=True),
            "x-ms-version": "2023-11-03",
        }
        if method == "PUT":
            headers.update(
                {
                    "x-ms-blob-type": "BlockBlob",
                    "Content-Length": str(len(content)),
                    "Content-Type": "application/octet-stream",
                }
            )
        if condition is not None:
            headers["If-Match"] = condition
        if create:
            headers["If-None-Match"] = "*"
        mode = self.config.get("auth_mode", "account_key")
        if mode == "service_principal":
            headers["Authorization"] = "Bearer " + self.token
        elif mode == "sas":
            sas = dict(
                parse_qsl(self.credentials.get("sas_token", "").lstrip("?"), keep_blank_values=True)
            )
            if not sas.get("sig") or set(query) & set(sas):
                raise AdapterError("CONNECTOR_CREDENTIAL_REQUIRED")
            query.update(sas)
        elif mode == "account_key":
            fields = [
                method,
                "",
                "",
                str(len(content)) if len(content) else "",
                "",
                headers.get("Content-Type", ""),
                "",
                "",
                headers.get("If-Match", ""),
                headers.get("If-None-Match", ""),
                "",
                "",
            ]
            canonical_headers = "".join(
                f"{key}:{value}\n"
                for key, value in sorted(headers.items())
                if key.startswith("x-ms-")
            )
            resource = (
                "/"
                + self.account
                + path
                + "".join(
                    "\n" + key.lower() + ":" + str(value) for key, value in sorted(query.items())
                )
            )
            try:
                key_bytes = base64.b64decode(self.credentials["account_key"], validate=True)
            except (ValueError, KeyError):
                raise AdapterError("CONNECTOR_CREDENTIAL_REQUIRED") from None
            signature = base64.b64encode(
                hmac.new(
                    key_bytes,
                    ("\n".join(fields) + "\n" + canonical_headers + resource).encode(),
                    hashlib.sha256,
                ).digest()
            ).decode()
            headers["Authorization"] = f"SharedKey {self.account}:{signature}"
        else:
            raise AdapterError("CONNECTOR_AUTH_UNSUPPORTED")
        return self.base + path + ("?" + urlencode(query) if query else ""), headers

    def list_page(self, prefix, cursor=None):
        query = {
            "restype": "container",
            "comp": "list",
            "prefix": self.key(prefix),
            "maxresults": "1000",
        }
        if cursor:
            query["marker"] = cursor
        url, headers = self.signed("GET", query=query)
        _, body = http.request("GET", url, headers=headers, deadline_at=self.deadline)
        root = _xml(body)
        rows = []
        for blob in root.findall("./Blobs/Blob"):
            properties = blob.find("Properties")
            if properties is None:
                raise AdapterError("CONNECTOR_RESPONSE_INVALID")
            rows.append(
                {
                    "key": self.key(_text(blob, "Name")),
                    "size": _number(_text(properties, "Content-Length")),
                    "etag": _text(properties, "Etag"),
                    "modified_at": _text(properties, "Last-Modified"),
                }
            )
        return rows, _text(root, "NextMarker") or None


class GCSClient(ObjectClient):
    def __init__(self, config, credentials, deadline):
        super().__init__(config, credentials, deadline)
        self.base = endpoint(config.get("endpoint") or "https://storage.googleapis.com")
        try:
            account = json.loads(credentials["service_account"])
            import jwt

            now = int(datetime.now(UTC).timestamp())
            assertion = jwt.encode(
                {
                    "iss": account["client_email"],
                    "scope": "https://www.googleapis.com/auth/devstorage.read_write"
                    if config.get("_write")
                    else "https://www.googleapis.com/auth/devstorage.read_only",
                    "aud": "https://oauth2.googleapis.com/token",
                    "iat": now,
                    "exp": now + 900,
                },
                account["private_key"],
                algorithm="RS256",
            )
        except (ValueError, KeyError):
            raise AdapterError("CONNECTOR_CREDENTIAL_INVALID") from None
        _, token = http.json_request(
            "POST",
            "https://oauth2.googleapis.com/token",
            deadline_at=deadline,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            content=urlencode(
                {
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                }
            ).encode(),
        )
        self.token = token.get("access_token")
        if not self.token:
            raise AdapterError("CONNECTOR_AUTH_DENIED")

    def signed(self, method, key="", *, query=None, content=b"", condition=None, create=False):
        # XML API supports conditional object PUTs and preserves ETag semantics.
        url = self.base + "/" + quote(self.bucket, safe="") + "/" + quote(key, safe="/")
        headers = {"Authorization": "Bearer " + self.token}
        if condition is not None:
            headers["If-Match"] = condition
        if create:
            headers["x-goog-if-generation-match"] = "0"
        return url + ("?" + urlencode(query) if query else ""), headers

    def list_page(self, prefix, cursor=None):
        query = {"prefix": self.key(prefix), "maxResults": 1000}
        if cursor:
            query["pageToken"] = cursor
        url = self.base + "/storage/v1/b/" + quote(self.bucket, safe="") + "/o?" + urlencode(query)
        _, body = http.json_request(
            "GET", url, deadline_at=self.deadline, headers={"Authorization": "Bearer " + self.token}
        )
        return [
            {
                "key": self.key(row["name"]),
                "size": _number(row["size"]),
                "etag": row["etag"],
                "generation": str(row["generation"]),
                "modified_at": row.get("updated"),
            }
            for row in body.get("items", [])
        ], body.get("nextPageToken")

    def download(self, item, path, max_bytes):
        url = (
            self.base
            + "/download/storage/v1/b/"
            + quote(self.bucket, safe="")
            + "/o/"
            + quote(self.key(item["key"]), safe="")
            + "?"
            + urlencode(
                {
                    "alt": "media",
                    "generation": item["generation"],
                    "ifGenerationMatch": item["generation"],
                }
            )
        )
        result = http.download(
            url,
            path,
            deadline_at=self.deadline,
            headers={"Authorization": "Bearer " + self.token},
            max_bytes=max_bytes,
        )
        if result[1] != item["size"]:
            raise AdapterError("CONNECTOR_SOURCE_CHANGED")
        return result


def client_for(dialect, config, credentials, deadline):
    cls = {
        "s3": S3Client,
        "s3_compatible": S3Client,
        "azure_blob": AzureClient,
        "gcs": GCSClient,
    }.get(dialect)
    if cls is None:
        raise AdapterError("CONNECTOR_DIALECT_UNSUPPORTED")
    return cls(config, credentials, deadline)
