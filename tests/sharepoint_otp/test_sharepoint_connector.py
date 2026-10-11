"""Unit tests for the SharePoint OTP connector.

The tests mock out Playwright, MSAL and HTTP calls so they run anywhere
without network access or browser binaries. A smoke test hitting a real
tenant is available but gated by the ``SHAREPOINT_SMOKE_SHARING_URL`` env
variable; see ``test_sharepoint_smoke``.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.connectors.sharepoint_otp import (  # noqa: E402
    ManifestEntry,
    SharePointFile,
    SharePointFolder,
    SharePointLoginRequired,
    SharePointSession,
    SharePointSessionStore,
    SharedFolderIngester,
    SyncManifest,
    decrypt_blob,
    encrypt_blob,
    generate_master_key,
)
from backend.app.services.connectors.sharepoint_otp.crypto import (  # noqa: E402
    ENV_MASTER_KEY,
    ENV_REQUIRE_ENCRYPTION,
    EncryptionNotConfigured,
)


# ---------- tiny fakes for SharePoint responses ------------------------------


def _file(name: str, parent: str, modified: str = "2026-01-01T00:00:00Z", size: int = 10) -> SharePointFile:
    return SharePointFile(
        name=name,
        server_relative_url=f"{parent.rstrip('/')}/{name}",
        size_bytes=size,
        modified_iso=modified,
    )


def _folder(name: str, parent: str) -> SharePointFolder:
    return SharePointFolder(
        name=name,
        server_relative_url=f"{parent.rstrip('/')}/{name}",
    )


class FakeClient:
    """In-memory tree implementing the ``_WalkClient`` protocol."""

    def __init__(
        self,
        root: str,
        *,
        folders: dict[str, list[SharePointFolder]],
        files: dict[str, list[SharePointFile]],
    ) -> None:
        self.root = root
        self.folders = folders
        self.files = files
        self.downloaded: list[tuple[str, Path]] = []

    def walk(self, server_relative_url: str):
        stack = [SharePointFolder(name=server_relative_url.rsplit("/", 1)[-1], server_relative_url=server_relative_url)]
        while stack:
            current = stack.pop()
            subs = self.folders.get(current.server_relative_url, [])
            files = self.files.get(current.server_relative_url, [])
            yield current, subs, files
            stack.extend(reversed(subs))

    def download_file(self, server_relative_url: str, *, destination):
        dest = Path(destination)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"FAKE:" + server_relative_url.encode())
        self.downloaded.append((server_relative_url, dest))
        return dest


# ---------- crypto -----------------------------------------------------------


def test_crypto_roundtrip_with_key(monkeypatch):
    key = generate_master_key()
    monkeypatch.setenv(ENV_MASTER_KEY, key)
    payload = b"top secret payload"
    blob = encrypt_blob(payload, tenant="andritz.sharepoint.com")
    assert payload not in blob, "plaintext must not appear when key is set"
    envelope = json.loads(blob.decode("utf-8"))
    assert envelope["tenant"] == "andritz.sharepoint.com"
    assert "ciphertext" in envelope
    assert decrypt_blob(blob, tenant="andritz.sharepoint.com") == payload


def test_crypto_rejects_wrong_tenant(monkeypatch):
    monkeypatch.setenv(ENV_MASTER_KEY, generate_master_key())
    blob = encrypt_blob(b"x", tenant="tenant-a.sharepoint.com")
    with pytest.raises(ValueError):
        decrypt_blob(blob, tenant="tenant-b.sharepoint.com")


def test_crypto_fallback_plaintext(monkeypatch, caplog):
    monkeypatch.delenv(ENV_MASTER_KEY, raising=False)
    monkeypatch.delenv(ENV_REQUIRE_ENCRYPTION, raising=False)
    blob = encrypt_blob(b"hello", tenant="t")
    envelope = json.loads(blob.decode("utf-8"))
    assert base64.b64decode(envelope["plaintext"]) == b"hello"
    assert decrypt_blob(blob, tenant="t") == b"hello"


def test_crypto_require_encryption_without_key(monkeypatch):
    monkeypatch.delenv(ENV_MASTER_KEY, raising=False)
    monkeypatch.setenv(ENV_REQUIRE_ENCRYPTION, "1")
    with pytest.raises(EncryptionNotConfigured):
        encrypt_blob(b"x", tenant="t")


# ---------- session store ---------------------------------------------------


def test_session_store_encrypts_on_disk(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_MASTER_KEY, generate_master_key())
    store = SharePointSessionStore(tmp_path)
    session = SharePointSession(
        tenant_host="andritz.sharepoint.com",
        sharing_url="https://andritz.sharepoint.com/:f:/s/107645/...",
        storage_state={"cookies": [{"name": "FedAuth", "value": "SECRETVALUE"}]},
    )
    store.save("wk1", session)
    on_disk = (tmp_path / "wk1.json").read_bytes()
    assert b"SECRETVALUE" not in on_disk
    loaded = store.load("wk1")
    assert loaded is not None
    assert loaded.tenant_host == "andritz.sharepoint.com"
    assert loaded.storage_state["cookies"][0]["value"] == "SECRETVALUE"


def test_session_store_missing_key_returns_none(tmp_path):
    store = SharePointSessionStore(tmp_path)
    assert store.load("never-saved") is None


# ---------- manifest ---------------------------------------------------------


def test_manifest_roundtrip(tmp_path):
    m = SyncManifest()
    m.record(_file("a.txt", "/f", modified="T1", size=12), tmp_path / "a.txt")
    m.record(_file("b.txt", "/f", modified="T1", size=7), tmp_path / "b.txt")
    m.save(tmp_path)
    loaded = SyncManifest.load(tmp_path)
    assert len(loaded) == 2
    assert loaded.should_download(_file("a.txt", "/f", modified="T1", size=12)) is False
    assert loaded.should_download(_file("a.txt", "/f", modified="T2", size=12)) is True
    assert loaded.should_download(_file("a.txt", "/f", modified="T1", size=99)) is True
    assert loaded.should_download(_file("c.txt", "/f", modified="T1", size=1)) is True


def test_manifest_prune_detects_deletions(tmp_path):
    m = SyncManifest(
        {
            "/f/a.txt": ManifestEntry(
                server_relative_url="/f/a.txt",
                modified_iso="T",
                size_bytes=1,
                local_path=str(tmp_path / "a.txt"),
            ),
            "/f/b.txt": ManifestEntry(
                server_relative_url="/f/b.txt",
                modified_iso="T",
                size_bytes=1,
                local_path=str(tmp_path / "b.txt"),
            ),
        }
    )
    pruned = m.prune(["/f/a.txt"])
    assert [e.server_relative_url for e in pruned] == ["/f/b.txt"]
    assert len(m) == 1


# ---------- ingester with incremental sync ----------------------------------


def _build_ingester(tmp_path: Path, fake_client: FakeClient, *, prune: bool = False) -> SharedFolderIngester:
    @contextmanager
    def factory():
        yield fake_client

    return SharedFolderIngester(
        folder_server_relative_url=fake_client.root,
        client_factory=factory,
        output_dir=tmp_path / "out",
        prune_local_files=prune,
    )


def test_walk_traverses_nested_folders_and_downloads(tmp_path):
    root = "/sites/x/Shared Documents/Root"
    sub = _folder("Sub", root)
    fake = FakeClient(
        root,
        folders={root: [sub], sub.server_relative_url: []},
        files={
            root: [_file("top.txt", root, size=4)],
            sub.server_relative_url: [_file("nested.md", sub.server_relative_url, size=2)],
        },
    )
    ingester = _build_ingester(tmp_path, fake)
    result = ingester.run()
    assert result.files_total == 2
    assert result.files_downloaded == 2
    assert result.bytes_total == 6
    assert (tmp_path / "out" / "top.txt").exists()
    assert (tmp_path / "out" / "Sub" / "nested.md").exists()


def test_ingester_second_run_is_incremental(tmp_path):
    root = "/sites/x/Shared Documents/Root"
    fake = FakeClient(
        root,
        folders={root: []},
        files={root: [_file("a.txt", root), _file("b.txt", root)]},
    )
    ingester = _build_ingester(tmp_path, fake)
    first = ingester.run()
    assert first.files_downloaded == 2

    fake.downloaded.clear()
    second = ingester.run()
    assert second.files_downloaded == 0
    assert second.files_total == 2
    assert len(second.skipped_paths) == 2
    assert fake.downloaded == []


def test_ingester_redownloads_modified_file(tmp_path):
    root = "/sites/x/Shared Documents/Root"
    fake = FakeClient(
        root,
        folders={root: []},
        files={root: [_file("a.txt", root, modified="T1", size=1)]},
    )
    ingester = _build_ingester(tmp_path, fake)
    ingester.run()

    fake.files[root] = [_file("a.txt", root, modified="T2", size=1)]
    fake.downloaded.clear()
    result = ingester.run()
    assert result.files_downloaded == 1


def test_ingester_prunes_deleted_files(tmp_path):
    root = "/sites/x/Shared Documents/Root"
    fake = FakeClient(
        root,
        folders={root: []},
        files={root: [_file("a.txt", root), _file("b.txt", root)]},
    )
    ingester = _build_ingester(tmp_path, fake, prune=True)
    ingester.run()
    assert (tmp_path / "out" / "a.txt").exists()

    fake.files[root] = [_file("b.txt", root)]
    result = ingester.run()
    stale = tmp_path / "out" / "a.txt"
    assert not stale.exists()
    assert any(str(p).endswith("a.txt") for p in result.pruned_paths)


# ---------- ingester error handling -----------------------------------------


def test_ingester_raises_login_required_when_no_recovery(tmp_path):
    from backend.app.services.connectors.sharepoint_otp.errors import (
        SharePointSessionExpired,
    )

    class ExpiringClient(FakeClient):
        def walk(self, server_relative_url: str):
            raise SharePointSessionExpired("expired")

    fake = ExpiringClient("/sites/x/r", folders={}, files={})
    ingester = _build_ingester(tmp_path, fake)
    with pytest.raises(SharePointLoginRequired):
        ingester.run()


# ---------- MSAL client (mocked) --------------------------------------------


def test_msal_client_list_files_with_mocked_http(monkeypatch, tmp_path):
    from backend.app.services.connectors.sharepoint_otp.client_msal import (
        MsalAppConfig,
        SharePointMsalAuth,
        SharePointMsalClient,
    )

    # Avoid invoking the real msal package by stubbing the auth.
    fake_auth = mock.Mock(spec=SharePointMsalAuth)
    fake_auth.app_config = MsalAppConfig(
        client_id="cid", tenant_host="andritz.sharepoint.com"
    )
    fake_auth.acquire_silent.return_value = "tkn"

    with mock.patch(
        "backend.app.services.connectors.sharepoint_otp.client_msal.requests.Session"
    ) as SessionCls:
        http = mock.MagicMock()
        SessionCls.return_value = http
        resp = mock.Mock()
        resp.status_code = 200
        resp.json.return_value = {
            "value": [
                {
                    "Name": "hello.txt",
                    "ServerRelativeUrl": "/sites/x/f/hello.txt",
                    "Length": "5",
                    "TimeLastModified": "2026-01-01T00:00:00Z",
                }
            ]
        }
        http.request.return_value = resp
        http.headers = {}

        with SharePointMsalClient(fake_auth) as client:
            files = client.list_files("/sites/x/f")

    assert len(files) == 1
    assert files[0].name == "hello.txt"
    fake_auth.acquire_silent.assert_called_once()


def test_msal_client_refreshes_on_401(monkeypatch):
    from backend.app.services.connectors.sharepoint_otp.client_msal import (
        MsalAppConfig,
        SharePointMsalAuth,
        SharePointMsalClient,
    )

    fake_auth = mock.Mock(spec=SharePointMsalAuth)
    fake_auth.app_config = MsalAppConfig(
        client_id="cid", tenant_host="andritz.sharepoint.com"
    )
    fake_auth.acquire_silent.side_effect = ["tkn1", "tkn2"]

    with mock.patch(
        "backend.app.services.connectors.sharepoint_otp.client_msal.requests.Session"
    ) as SessionCls:
        http = mock.MagicMock()
        SessionCls.return_value = http
        http.headers = {}
        first = mock.Mock(status_code=401, text="unauth")
        second = mock.Mock(status_code=200)
        second.json.return_value = {"Name": "n", "ServerRelativeUrl": "/sites/x/f"}
        http.request.side_effect = [first, second]

        with SharePointMsalClient(fake_auth) as client:
            folder = client.get_folder("/sites/x/f")

    assert folder.name == "n"
    assert fake_auth.acquire_silent.call_count == 2


# ---------- celery service translation --------------------------------------


def test_celery_service_returns_login_required_when_no_session(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_MASTER_KEY, generate_master_key())
    from backend.app.services.connectors.sharepoint_otp.celery_service import (
        run_sync_from_payload,
    )

    payload = SimpleNamespace(
        auth_mode="session",
        folder_server_relative_url="/sites/x/Shared Documents/Root",
        output_dir=tmp_path / "out",
        session_key="wk-test",
        session_dir=tmp_path / "sessions",
        sharing_url="https://andritz.sharepoint.com/:f:/s/x/abc",
        prune_local_files=False,
        client_id=None,
        tenant_host=None,
        user_hint=None,
    )

    outcome = run_sync_from_payload(payload)
    assert outcome.status == "login_required"
    assert outcome.login_required_detail


def test_celery_service_completes_when_session_exists(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_MASTER_KEY, generate_master_key())
    from backend.app.services.connectors.sharepoint_otp.celery_service import (
        run_sync_from_payload,
    )

    # Seed a session so the worker path finds a cached state.
    store = SharePointSessionStore(tmp_path / "sessions")
    store.save(
        "wk-test",
        SharePointSession(
            tenant_host="andritz.sharepoint.com",
            sharing_url="https://andritz.sharepoint.com/:f:/s/x/abc",
            storage_state={"cookies": []},
        ),
    )

    root = "/sites/x/Shared Documents/Root"
    fake = FakeClient(
        root,
        folders={root: []},
        files={root: [_file("a.txt", root, size=3)]},
    )

    from backend.app.services.connectors.sharepoint_otp import ingester as ingester_mod

    @contextmanager
    def fake_ctx(session, **kwargs):
        yield fake

    with mock.patch.object(ingester_mod, "SharePointBrowserClient", fake_ctx):
        payload = SimpleNamespace(
            auth_mode="session",
            folder_server_relative_url=root,
            output_dir=tmp_path / "out",
            session_key="wk-test",
            session_dir=tmp_path / "sessions",
            sharing_url="https://andritz.sharepoint.com/:f:/s/x/abc",
            prune_local_files=False,
            client_id=None,
            tenant_host=None,
            user_hint=None,
        )
        outcome = run_sync_from_payload(payload)

    assert outcome.status == "completed"
    assert outcome.result.files_downloaded == 1


# ---------- optional smoke test --------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("SHAREPOINT_SMOKE_SHARING_URL"),
    reason="Set SHAREPOINT_SMOKE_SHARING_URL + SHAREPOINT_SMOKE_FOLDER to run",
)
def test_sharepoint_smoke(tmp_path):
    """End-to-end smoke against a real tenant. Requires:

    - ``SHAREPOINT_SMOKE_SHARING_URL`` — full sharing link.
    - ``SHAREPOINT_SMOKE_FOLDER`` — server-relative folder path.
    - A human to complete OTP + Authenticator on first run.
    - ``playwright install chromium`` once.
    """
    sharing_url = os.environ["SHAREPOINT_SMOKE_SHARING_URL"]
    folder = os.environ["SHAREPOINT_SMOKE_FOLDER"]
    store = SharePointSessionStore(tmp_path / "sessions")
    ingester = SharedFolderIngester.for_session_client(
        sharing_url=sharing_url,
        folder_server_relative_url=folder,
        session_store=store,
        session_key="smoke",
        output_dir=tmp_path / "downloads",
        interactive_login_allowed=True,
    )
    result = ingester.run()
    assert result.files_total >= 0
