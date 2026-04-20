"""One-off connectivity test for the Andritz SharePoint shared folder.

Authenticates the Datategy-registered app (`papAI - SharePoint Reader`) against
the Andritz tenant using a delegated interactive flow, then performs minimal
SharePoint REST calls on the shared folder `Test_partage_externe` to validate
that a future Agentium connector can list and download files there.

Usage:
    python scripts/test_andritz_sharepoint.py

The script opens a browser window so you can complete the OTP + Authenticator
login flow. It prints the HTTP status and a small preview of each response.
"""

from __future__ import annotations

import base64
import json
import sys
from typing import Any

try:
    import msal  # type: ignore
except ImportError:
    print("Missing dependency. Install with: pip install msal requests", file=sys.stderr)
    raise

import requests

CLIENT_ID = "49888603-9866-4c80-80b1-d2d944fcc0be"
ANDRITZ_TENANT_ID = "6785298f-e857-464b-9b4b-807178402632"

ANDRITZ_AUTHORITY = f"https://login.microsoftonline.com/{ANDRITZ_TENANT_ID}"

SHAREPOINT_RESOURCE = "https://andritz.sharepoint.com"
SHAREPOINT_SCOPES = [f"{SHAREPOINT_RESOURCE}/.default"]

GUEST_UPN = "thibaud.ishacian_datategy.net#EXT#@andritz.onmicrosoft.com"

SITE_URL = f"{SHAREPOINT_RESOURCE}/sites/107645"
FOLDER_RELATIVE = "/sites/107645/Shared Documents/Test_partage_externe"


def decode_jwt_claims(token: str) -> dict[str, Any]:
    try:
        payload = token.split(".")[1]
        padded = payload + "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    except Exception as exc:  # pragma: no cover - best effort
        return {"_decode_error": str(exc)}


def acquire_token() -> str:
    app = msal.PublicClientApplication(CLIENT_ID, authority=ANDRITZ_AUTHORITY)

    print(
        "Opening browser. Make sure you are ALREADY signed in to the shared\n"
        "folder at https://andritz.sharepoint.com/sites/107645 in your default\n"
        "browser (OTP + Authenticator). MSAL will reuse that session."
    )
    result = app.acquire_token_interactive(
        scopes=SHAREPOINT_SCOPES,
        prompt="select_account",
        port=8400,
    )

    if "access_token" not in result:
        print("Token acquisition failed:")
        print(json.dumps(result, indent=2))
        sys.exit(2)

    claims = decode_jwt_claims(result["access_token"])
    print("\n=== Token acquired ===")
    for key in ("aud", "iss", "tid", "upn", "unique_name", "scp", "roles", "app_displayname"):
        if key in claims:
            print(f"  {key}: {claims[key]}")
    return result["access_token"]


def call_api(token: str, url: str, label: str) -> None:
    print(f"\n=== {label} ===")
    print("GET", url)
    r = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json;odata=nometadata",
        },
        timeout=30,
    )
    print("status", r.status_code, "content-type", r.headers.get("content-type"))
    body = r.text
    if len(body) > 600:
        body = body[:600] + "…"
    print(body)


def main() -> int:
    token = acquire_token()

    call_api(
        token,
        f"{SITE_URL}/_api/web?$select=Title,Url",
        "Web metadata",
    )
    call_api(
        token,
        f"{SITE_URL}/_api/web/GetFolderByServerRelativeUrl('{FOLDER_RELATIVE}')"
        "/Files?$select=Name,ServerRelativeUrl,Length,TimeLastModified",
        "List files in shared folder",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
