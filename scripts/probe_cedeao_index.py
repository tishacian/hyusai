#!/usr/bin/env python3
"""Standalone probe for the SENTINEL-CI /cedeao-index endpoint (Vague 2.2).

Logs into ``agentium.papai.ai`` with the provided credentials, hits
``GET /api/v1/mission-room/cedeao-index`` against the configured workspace,
prints a short verdict line, and dumps the JSON payload to disk so an
operator can confirm the LIVE / CACHE BASELINE bascule without leaving the
shell.

The probe is read-only and demo-safe: it does not mutate state and respects
the demo workspace guard rail (which always returns the baseline composite).

Usage::

    AGENTIUM_HOST=https://agentium.papai.ai \
    AGENTIUM_EMAIL='<operator-email>' \
    AGENTIUM_PASSWORD='<from-secret-manager>' \
    WORKSPACE_SLUG=sentinel-ci \
    python3 scripts/probe_cedeao_index.py

Exit code: 0 if the endpoint returns 200 with a valid composite payload,
1 otherwise.
"""
from __future__ import annotations

import json
import os
import socket
import ssl
import sys
import urllib.error
import urllib.request
from typing import Any, Optional


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required")
    return value


HOST = os.environ.get("AGENTIUM_HOST", "https://agentium.papai.ai").rstrip("/")
WORKSPACE = os.environ.get("WORKSPACE_SLUG", "sentinel-ci")
EMAIL = _required_env("AGENTIUM_EMAIL")
PASSWORD = _required_env("AGENTIUM_PASSWORD")
TIMEOUT = float(os.environ.get("PROBE_TIMEOUT", "12.0"))
OUTPUT_PATH = os.environ.get("PROBE_OUTPUT", "docs/status-screenshots/cedeao-index-probe.json")

REQUIRED_FIELDS = (
    "live",
    "source",
    "source_badge",
    "score",
    "unit",
    "components",
    "component_weights",
    "policy",
)
REQUIRED_COMPONENTS = ("unrest", "conflict", "security_advisories", "information")


def _http_json(
    method: str,
    path: str,
    *,
    body: Optional[dict] = None,
    token: Optional[str] = None,
) -> tuple[int, Any]:
    url = f"{HOST}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT, context=ctx) as response:
            text = response.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(text) if text else None
            except json.JSONDecodeError:
                payload = {"raw": text[:400]}
            return response.status, payload
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(text) if text else None
        except json.JSONDecodeError:
            payload = {"raw": text[:400]}
        return exc.code, payload
    except (urllib.error.URLError, socket.timeout) as exc:
        return 0, {"error": str(exc)}


def _login() -> Optional[str]:
    status, payload = _http_json(
        "POST",
        "/api/v1/auth/login",
        body={"email": EMAIL, "password": PASSWORD, "workspace_slug": WORKSPACE},
    )
    if status == 200 and isinstance(payload, dict):
        return payload.get("access_token") or payload.get("token")
    print(f"[FAIL] login status={status} payload={payload}", file=sys.stderr)
    return None


def _verdict(payload: Any) -> tuple[bool, list[str]]:
    issues: list[str] = []
    if not isinstance(payload, dict):
        return False, ["payload not a dict"]
    for field in REQUIRED_FIELDS:
        if field not in payload:
            issues.append(f"missing field {field!r}")
    components = payload.get("components") or {}
    if not isinstance(components, dict):
        issues.append("components not a dict")
    else:
        for key in REQUIRED_COMPONENTS:
            if key not in components:
                issues.append(f"missing component {key!r}")
    score = payload.get("score")
    if not isinstance(score, (int, float)) or not (0 <= float(score) <= 100):
        issues.append(f"score out of range: {score!r}")
    badge = payload.get("source_badge")
    if badge not in {"LIVE", "CACHE BASELINE"}:
        issues.append(f"unexpected source_badge: {badge!r}")
    return (not issues), issues


def main() -> int:
    token = _login()
    if not token:
        return 1

    status, payload = _http_json(
        "GET",
        f"/api/v1/mission-room/cedeao-index?workspace={WORKSPACE}",
        token=token,
    )
    if status != 200:
        print(f"[FAIL] /cedeao-index status={status} body={payload}", file=sys.stderr)
        return 1

    valid, issues = _verdict(payload)
    badge = (payload or {}).get("source_badge", "?")
    score = (payload or {}).get("score", "?")
    delta = (payload or {}).get("delta_7d", "?")
    live = (payload or {}).get("live", "?")
    print(f"[OK] /cedeao-index workspace={WORKSPACE} badge={badge} live={live} score={score} delta_7d={delta}")
    if not valid:
        print(f"[WARN] payload issues: {issues}", file=sys.stderr)

    if OUTPUT_PATH:
        try:
            os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
        except OSError:
            pass
        try:
            with open(OUTPUT_PATH, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            print(f"[OK] wrote {OUTPUT_PATH}")
        except OSError as exc:
            print(f"[WARN] could not write {OUTPUT_PATH}: {exc}", file=sys.stderr)

    return 0 if valid else 1


if __name__ == "__main__":
    sys.exit(main())
