"""CLI demo of the SharePoint OTP connector.

Downloads every file in a shared folder to a local directory, opening a
Playwright-driven browser window for the first-time OTP + Authenticator flow.
The captured session is persisted (encrypted) to ``./.sharepoint_sessions``
so subsequent runs sync silently until SharePoint expires the cookies.

Two auth backends are supported via ``--auth``:

- ``session`` (default): Playwright cookie capture.
- ``msal``: OAuth delegated token via the ``papAI - SharePoint Reader`` app.

Example (session mode)::

    python scripts/sharepoint_connector_demo.py \
        --sharing-url "https://andritz.sharepoint.com/:f:/s/107645/Ig...?email=..." \
        --folder "/sites/107645/Shared Documents/Test_partage_externe" \
        --output ./downloads/andritz_test_partage_externe
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.services.connectors.sharepoint_otp import (  # noqa: E402
    MsalAppConfig,
    SharedFolderIngester,
    SharePointLoginRequired,
    SharePointMsalAuth,
    SharePointSessionStore,
    derive_session_key,
    generate_master_key,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sharing-url",
        help="Sharing link (required for --auth session).",
    )
    parser.add_argument(
        "--folder",
        required=True,
        help="Server-relative path of the shared folder, e.g. "
        "'/sites/107645/Shared Documents/Test_partage_externe'.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Local directory where the downloaded files are written.",
    )
    parser.add_argument(
        "--auth",
        choices=("session", "msal"),
        default="session",
        help="Authentication backend.",
    )
    parser.add_argument(
        "--session-dir",
        type=Path,
        default=Path(".sharepoint_sessions"),
        help="Directory used to persist session state between runs.",
    )
    parser.add_argument(
        "--force-reauth",
        action="store_true",
        help="Ignore any stored session and force a fresh interactive login.",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Delete local files that disappeared from the remote folder.",
    )
    parser.add_argument(
        "--generate-key",
        action="store_true",
        help="Print a fresh urlsafe Fernet key and exit. Set it as "
        "SHAREPOINT_CONNECTOR_FERNET_KEY in your environment to enable "
        "at-rest encryption of cached sessions/tokens.",
    )
    parser.add_argument(
        "--export-session",
        action="store_true",
        help="After capture, print the session as a JSON body ready to "
        "PUT to /flow_operations/sharepoint/sessions/{key} on the VM. "
        "The body shape is {\"session_dict\": <SharePointSession.to_dict()>}.",
    )
    # MSAL-only options
    parser.add_argument("--client-id", help="Entra app client ID.")
    parser.add_argument(
        "--tenant-host",
        help="SharePoint tenant host, e.g. andritz.sharepoint.com.",
    )
    parser.add_argument(
        "--user-hint",
        help="UPN used as MSAL login_hint (e.g. operator@example.com).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
    )
    return parser.parse_args()


def _build_session_ingester(args: argparse.Namespace) -> SharedFolderIngester:
    if not args.sharing_url:
        raise SystemExit("--sharing-url is required with --auth session")
    store = SharePointSessionStore(args.session_dir)
    key = derive_session_key(args.sharing_url)
    if args.force_reauth:
        store.delete(key)
    return SharedFolderIngester.for_session_client(
        sharing_url=args.sharing_url,
        folder_server_relative_url=args.folder,
        session_store=store,
        session_key=key,
        output_dir=args.output,
        interactive_login_allowed=True,
        prune_local_files=args.prune,
    )


def _build_msal_ingester(args: argparse.Namespace) -> SharedFolderIngester:
    if not args.client_id or not args.tenant_host:
        raise SystemExit("--client-id and --tenant-host are required with --auth msal")
    cfg = MsalAppConfig(client_id=args.client_id, tenant_host=args.tenant_host)
    cache_path = args.session_dir / f"msal_{args.tenant_host}.cache"
    auth = SharePointMsalAuth(
        cfg, cache_path=cache_path, user_hint=args.user_hint
    )
    # Try silent first; if it fails, prompt interactively (CLI-only behaviour).
    try:
        auth.acquire_silent()
    except SharePointLoginRequired:
        print("No cached MSAL account, opening browser for interactive sign-in...")
        auth.acquire_interactive()
    return SharedFolderIngester.for_msal_client(
        msal_auth=auth,
        folder_server_relative_url=args.folder,
        output_dir=args.output,
        prune_local_files=args.prune,
    )


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.generate_key:
        print(generate_master_key())
        return 0

    if args.auth == "session":
        ingester = _build_session_ingester(args)
    else:
        ingester = _build_msal_ingester(args)

    def _log_progress(file, target) -> None:
        print(f"  downloaded {file.name}  ({file.size_bytes} B) -> {target}")

    result = ingester.run(progress=_log_progress)

    if args.export_session and args.auth == "session":
        import json as _json

        from backend.app.services.connectors.sharepoint_otp import (
            SharePointSessionStore,
            derive_session_key,
        )

        store = SharePointSessionStore(args.session_dir)
        key = derive_session_key(args.sharing_url)
        session = store.load(key)
        if session is not None:
            print("\n---- UPLOAD BODY (session_dict) ----")
            print(_json.dumps({"session_dict": session.to_dict()}, indent=2))
            print("---- END ----")

    print()
    print(
        f"Done: {result.files_total} files seen, "
        f"{result.files_downloaded} downloaded, "
        f"{len(result.skipped_paths)} skipped (unchanged), "
        f"{result.bytes_total} bytes transferred"
    )
    if result.pruned_paths:
        print(f"Pruned {len(result.pruned_paths)} stale manifest entries.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
