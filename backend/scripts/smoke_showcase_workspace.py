"""Smoke test for the Agentium showcase workspace.

Usage:
    python -m scripts.smoke_showcase_workspace \
      --backend-url https://agentium.papai.ai \
      --username alice@acme.test --password alice-demo
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-url", default="http://localhost:8000")
    parser.add_argument("--workspace-slug", default="agentium-showcase")
    parser.add_argument("--username", default="alice@acme.test")
    parser.add_argument("--password", default="alice-demo")
    return parser.parse_args()


def request_json(
    method: str,
    url: str,
    *,
    token: Optional[str] = None,
    workspace_slug: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
) -> tuple[int, Any]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if workspace_slug:
        headers["X-Workspace-Slug"] = workspace_slug
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=30) as resp:  # noqa: S310 - operator-provided URL
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else None
    except HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = raw
        return exc.code, payload
    except URLError as exc:
        return 0, str(exc)


def ok(label: str, condition: bool, detail: Any = None) -> bool:
    status = "PASS" if condition else "FAIL"
    print(f"{status:>4} {label}" + (f" :: {detail}" if detail is not None else ""))
    return condition


def main() -> int:
    args = parse_args()
    base = args.backend_url.rstrip("/")
    passed = 0
    failed = 0

    code, login = request_json(
        "POST",
        f"{base}/api/v1/auth/login",
        data={"email": args.username, "password": args.password, "remember_me": False},
    )
    token = login.get("token") if isinstance(login, dict) else None
    if ok("login", code == 200 and bool(token), {"code": code}):
        passed += 1
    else:
        return 1

    checks = [
        ("workspaces", "/api/v1/auth/workspaces", lambda d: any(w.get("slug") == args.workspace_slug for w in (d if isinstance(d, list) else d.get("workspaces", [])))),
        ("systems", "/api/v1/systems", lambda d: len(d.get("systems", [])) >= 3),
        ("runs", "/api/v1/runs", lambda d: len(d.get("runs", [])) >= 8),
        ("recommendations", "/api/v1/hypervisor/recommendations", lambda d: len(d.get("items", [])) >= 2),
        ("component health", "/api/v1/evaluation/component-health", lambda d: len(d.get("components", [])) >= 5),
        ("review queue", "/api/v1/evaluation/review-queue?status=all", lambda d: d.get("count", 0) >= 3),
        ("canonical answers", "/api/v1/evaluation/canonical-answers", lambda d: d.get("total", 0) >= 1),
        ("audit", "/api/v1/audit?limit=20", lambda d: d.get("total", 0) >= 5),
    ]
    for label, path, predicate in checks:
        code, payload = request_json(
            "GET",
            f"{base}{path}",
            token=token,
            workspace_slug=args.workspace_slug,
        )
        good = code == 200 and predicate(payload or {})
        if ok(label, good, {"code": code}):
            passed += 1
        else:
            failed += 1

    print(f"Results: {passed} passed / {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
