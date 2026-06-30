"""Smoke test for the Octocity Mission Room workspace.

Usage:
    python -m scripts.smoke_octocity_mission_room \
      --backend-url http://localhost:8000 \
      --workspace-slug octocity-mission-room \
      --username alice@acme.test --password alice-demo
"""
from __future__ import annotations

import argparse
import json
from typing import Any, Callable, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


FORBIDDEN_TERMS = (
    "AYA",
    "SENTINEL-CI",
    "Côte d’Ivoire",
    "Côte d'Ivoire",
    "Cote d'Ivoire",
    "Abidjan",
    "Nawa",
    "CEDEAO",
    "FANCI",
    "cacao",
    "anacarde",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-url", default="http://localhost:8000")
    parser.add_argument("--workspace-slug", default="octocity-mission-room")
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


def forbidden_terms(payload: Any) -> list[str]:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True) if not isinstance(payload, str) else payload
    return [term for term in FORBIDDEN_TERMS if term in text]


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

    def has_workspace(payload: Any) -> bool:
        rows = payload if isinstance(payload, list) else payload.get("workspaces", []) if isinstance(payload, dict) else []
        return any(row.get("slug") == args.workspace_slug for row in rows if isinstance(row, dict))

    def has_systems(payload: Any) -> bool:
        names = {row.get("name") for row in payload.get("systems", [])} if isinstance(payload, dict) else set()
        return {"OCTAVE Mission Room", "Workspace Chat", "Knowledge Capture"}.issubset(names)

    checks: list[tuple[str, str, Callable[[Any], bool], str, Optional[Dict[str, Any]], bool]] = [
        ("workspace listed", "/api/v1/auth/workspaces", has_workspace, "GET", None, False),
        ("systems", "/api/v1/systems", has_systems, "GET", None, False),
        ("mission navigation", "/api/v1/mission-room/navigation", lambda d: d.get("app", {}).get("assistant_label") == "OCTAVE", "GET", None, True),
        ("mission cockpit", "/api/v1/mission-room/cockpit", lambda d: bool(d.get("kpis") or d.get("decision_sentence")), "GET", None, True),
        ("mission map", "/api/v1/mission-room/map", lambda d: bool(d.get("zones") or d.get("layers")), "GET", None, True),
        (
            "chat action",
            "/api/v1/chat/completion",
            lambda d: (
                "OCTAVE" in json.dumps(d, ensure_ascii=False)
                or d.get("action_manifest_id") == "octave.priority_summary"
                or (d.get("registry_action") or {}).get("action_manifest_id") == "octave.priority_summary"
            ),
            "POST",
            {"query": "OCTAVE, donne-moi le cockpit", "stream": False, "assistant_profile": "octave_executive"},
            True,
        ),
        (
            "knowledge capture plan",
            "/api/v1/knowledge-capture/plans",
            lambda d: bool(d.get("id") or d.get("session_id")),
            "POST",
            {
                "title": "Octocity expert capture smoke",
                "objective": "Verifier une session Knowledge Capture sur corpus synthetique Octocity.",
                "duration_minutes": 10,
                "knowledge_refs": ["octocity-knowledge-capture"],
                "capture_domain": "octocity",
            },
            True,
        ),
    ]

    for label, path, predicate, method, data, scan_forbidden in checks:
        code, payload = request_json(
            method,
            f"{base}{path}",
            token=token,
            workspace_slug=args.workspace_slug,
            data=data,
        )
        missing = forbidden_terms(payload) if scan_forbidden else []
        good = code == 200 and predicate(payload or {}) and not missing
        detail = {"code": code}
        if missing:
            detail["forbidden_terms"] = missing
        if ok(label, good, detail):
            passed += 1
        else:
            failed += 1

    print(f"Results: {passed} passed / {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
