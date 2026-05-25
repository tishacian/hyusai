#!/usr/bin/env python3
"""Probe `/actions/resolve` with the EXACT deck phrases (verbatim).

Each phrase is taken from `docs/sentinel-ci-demo-presenter-deck-2026-05-25.md`
and sent to the resolver against ``surface=chat, profile=vigie_executive``.

We record the resolver verdict (matched action_id + confidence) so we can
distinguish a deterministic resolver match from an LLM fallback (no_match,
confidence 0). The presenter is going to read these phrases verbatim, so
any phrase that does not match deterministically is a P0 risk.

Usage::

    AGENTIUM_HOST=https://agentium.papai.ai \
    AGENTIUM_EMAIL=thibaud.ishacian@datategy.net \
    AGENTIUM_PASSWORD='***' \
    python3 scripts/qa_deck_phrases_resolve.py
"""
from __future__ import annotations

import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Optional

HOST = os.environ.get("AGENTIUM_HOST", "https://agentium.papai.ai").rstrip("/")
WORKSPACE = os.environ.get("WORKSPACE_SLUG", "sentinel-ci")
EMAIL = os.environ.get("AGENTIUM_EMAIL", "thibaud.ishacian@datategy.net")
PASSWORD = os.environ.get("AGENTIUM_PASSWORD", "")
TIMEOUT = float(os.environ.get("PROBE_TIMEOUT", "12.0"))


# Deck phrases — verbatim copy from the presenter deck. Quotes, accents,
# and punctuation are preserved exactly. A second cheatsheet variant is
# attached when the QA harness used a different phrasing.
DECK_PHRASES = [
    {
        "slide": "S1.1",
        "label": "Brief lundi matin (optionnel)",
        "deck": "AYA, c'est lundi matin. Qu'est-ce qui demande mon attention ?",
        "harness": None,
        "expected_any": [
            "aya.priority_summary",
            "aya.focus_zone_with_project",
            "aya.explain_why",
        ],
        "ui_effect": "Brief AYA inline (cockpit)",
    },
    {
        "slide": "S1.3",
        "label": "Pourquoi Nord tendue",
        "deck": "AYA, pourquoi la situation Nord est-elle tendue ?",
        "harness": "AYA, pourquoi la situation Nord est-elle tendue ?",
        "expected_any": [
            "aya.explain_why",
            "aya.focus_zone_with_project",
            "aya.zoom_zone",
        ],
        "ui_effect": "drill /strategie?zone=zone-nord",
    },
    {
        "slide": "S1.4",
        "label": "Ouvre PV douanes",
        "deck": "AYA, ouvre le PV douanes.",
        "harness": "AYA, ouvre le PV douanes.",
        "expected_any": ["aya.show_customs_record"],
        "ui_effect": "drawer document_preview PV douanes",
    },
    {
        "slide": "S1.5",
        "label": "Cargo Atlantic Trader",
        "deck": "AYA, montre le cargo Atlantic Trader.",
        "harness": "AYA, montre le cargo Atlantic Trader.",
        "expected_any": [
            "aya.show_vessel_evidence",
            "aya.show_vessel_snapshot",
            "aya.show_maritime_traffic",
        ],
        "ui_effect": "panel maritime + webcam APM Apapa",
    },
    {
        "slide": "S1.6",
        "label": "Situation au port",
        "deck": "AYA, montre la situation au port.",
        "harness": "AYA, montre la situation au port.",
        "expected_any": ["aya.show_maritime_traffic"],
        "ui_effect": "panel maritime + flux terrain",
    },
    {
        "slide": "S1.7",
        "label": "Courrier dedouanement",
        "deck": "AYA, rédige le courrier de dédouanement pour Atlantic Trader.",
        "harness": "AYA, rédige le courrier de dédouanement pour Atlantic Trader.",
        "expected_any": [
            "aya.draft_customs_email",
            "aya.propose_customs_derogation",
        ],
        "ui_effect": "drawer email customs_email",
    },
    {
        "slide": "T.1",
        "label": "Prochain rendez-vous",
        "deck": "AYA, quel est mon prochain rendez-vous ?",
        "harness": None,
        "expected_any": [
            "aya.open_next_meeting",
            "aya.open_agenda",
            "aya.show_next_meeting",
        ],
        "ui_effect": "navigation /agenda + Préfet Nawa",
    },
    {
        "slide": "S2.1",
        "label": "Resume rapport prefet",
        "deck": "AYA, donne-moi le résumé du rapport préfet.",
        "harness": "AYA, résume le rapport Préfet Nawa.",
        "expected_any": ["aya.summarize_last_exchanges"],
        "ui_effect": "synthèse Nawa inline",
    },
    {
        "slide": "S2.2",
        "label": "Preconisations cacao",
        "deck": "AYA, donne-moi des préconisations sur le cacao.",
        "harness": "AYA, donne-moi des préconisations sur le cacao.",
        "expected_any": [
            "aya.recommend_cacao",
            "aya.recommend_cacao_diversification",
            "aya.generate_recommendations",
        ],
        "ui_effect": "3 options chiffrees inline",
    },
    {
        "slide": "S2.3",
        "label": "Rapport complet",
        "deck": "AYA, génère le rapport complet.",
        "harness": "AYA, génère le rapport complet.",
        "expected_any": ["aya.draft_strategic_report"],
        "ui_effect": "drawer rapport stratégique",
    },
    {
        "slide": "S2.4",
        "label": "Patch ODJ cacao",
        "deck": "AYA, ajoute le point cacao à l'ordre du jour.",
        "harness": "AYA, ajoute le point cacao à l'ordre du jour.",
        "expected_any": [
            "aya.update_meeting_agenda",
            "aya.propose_agenda_patch",
            "aya.add_meeting_topic",
        ],
        "ui_effect": "bannière ODJ proposée",
    },
    {
        "slide": "S2.5",
        "label": "Valider patch",
        "deck": "Oui, valide.",
        "harness": "Oui, valide.",
        "expected_any": [
            "aya.confirm_yes",
            "aya.confirm_agenda_patch",
            "voice.confirm_yes",
        ],
        "ui_effect": "patch ODJ appliqué",
    },
    {
        "slide": "S2.6",
        "label": "Demarrer reunion",
        "deck": "AYA, démarre la réunion.",
        "harness": "AYA, démarre la réunion.",
        "expected_any": [
            "aya.start_meeting",
            "aya.open_meeting_live",
        ],
        "ui_effect": "vue meeting live",
    },
    {
        "slide": "S2.7",
        "label": "Decide option B",
        "deck": "AYA, décide option B.",
        "harness": "AYA, décide option B.",
        "expected_any": [
            "aya.decide_option_b",
            "aya.log_decision",
        ],
        "ui_effect": "décision option B loggée",
    },
]


def _request(
    method: str,
    path: str,
    *,
    jwt: Optional[str] = None,
    body: Optional[dict[str, Any]] = None,
    timeout: float = TIMEOUT,
) -> tuple[int, bytes, str]:
    url = path if path.startswith("http") else f"{HOST}/api/v1{path}"
    headers: dict[str, str] = {"Accept": "application/json"}
    data: Optional[bytes] = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    if jwt:
        headers["Authorization"] = f"Bearer {jwt}"
        headers["X-Workspace-Slug"] = WORKSPACE
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Content-Type", "")
    except (urllib.error.URLError, socket.timeout, ssl.SSLError, ConnectionError) as exc:
        return 0, str(exc).encode("utf-8"), "text/plain"


def login() -> str:
    code, body, _ = _request(
        "POST",
        "/auth/login",
        body={"email": EMAIL, "password": PASSWORD, "remember_me": False},
    )
    if code != 200:
        raise SystemExit(f"login failed: HTTP {code} body={body[:200]!r}")
    payload = json.loads(body)
    if "mfa_token" in payload:
        raise SystemExit("login returned MFA challenge — disable MFA or set non-MFA account")
    return payload["token"]


def resolve(jwt: str, text: str) -> dict[str, Any]:
    t0 = time.time()
    code, body, _ = _request(
        "POST",
        "/actions/resolve",
        jwt=jwt,
        body={
            "text": text,
            "surface": "chat",
            "assistant_profile": "vigie_executive",
        },
    )
    elapsed_ms = int((time.time() - t0) * 1000)
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        payload = {}
    return {
        "http": code,
        "ms": elapsed_ms,
        "matched": bool(payload.get("matched")),
        "action_id": payload.get("action_id"),
        "confidence": payload.get("confidence") or 0.0,
        "fallback": payload.get("fallback") or False,
        "raw": payload,
    }


def main() -> int:
    if not PASSWORD:
        print("AGENTIUM_PASSWORD is required", file=sys.stderr)
        return 2
    print(f"# Resolver QA — deck phrases verbatim — {HOST}")
    print(f"# {time.strftime('%Y-%m-%d %H:%M:%S UTC%z')}")
    print()
    jwt = login()
    print(f"login OK ({len(jwt)} chars JWT)\n")

    rows: list[dict[str, Any]] = []
    for p in DECK_PHRASES:
        deck_res = resolve(jwt, p["deck"])
        harness_res = None
        if p["harness"] and p["harness"] != p["deck"]:
            harness_res = resolve(jwt, p["harness"])

        deck_match_expected = deck_res["matched"] and (
            deck_res["action_id"] in p["expected_any"]
        )
        deck_match_other = deck_res["matched"] and not deck_match_expected
        verdict = (
            "PASS"
            if deck_match_expected
            else ("PARTIAL" if deck_match_other else ("FAIL" if not deck_res["matched"] else "PARTIAL"))
        )

        row = {
            "slide": p["slide"],
            "label": p["label"],
            "deck_phrase": p["deck"],
            "expected_any": p["expected_any"],
            "ui_effect": p["ui_effect"],
            "deck_resolve": deck_res,
            "harness_phrase": p["harness"] if p["harness"] != p["deck"] else None,
            "harness_resolve": harness_res,
            "verdict": verdict,
        }
        rows.append(row)

        print(f"## {p['slide']} — {p['label']}")
        print(f"  deck    : {p['deck']!r}")
        print(
            f"          → match={deck_res['matched']} "
            f"action={deck_res['action_id']} "
            f"conf={deck_res['confidence']:.2f} "
            f"fallback={deck_res['fallback']} "
            f"http={deck_res['http']} ms={deck_res['ms']}"
        )
        print(f"          expected_any={p['expected_any']}")
        print(f"          → VERDICT {verdict}")
        if harness_res is not None:
            print(f"  harness : {p['harness']!r}")
            print(
                f"          → match={harness_res['matched']} "
                f"action={harness_res['action_id']} "
                f"conf={harness_res['confidence']:.2f} "
                f"fallback={harness_res['fallback']}"
            )
        print()

    pass_n = sum(1 for r in rows if r["verdict"] == "PASS")
    partial_n = sum(1 for r in rows if r["verdict"] == "PARTIAL")
    fail_n = sum(1 for r in rows if r["verdict"] == "FAIL")
    print(f"Total: {len(rows)} phrases — PASS={pass_n} PARTIAL={partial_n} FAIL={fail_n}")

    out_path = os.environ.get(
        "QA_OUT",
        "/Users/thib/Developer/PAPAI/omnirag/docs/status-screenshots/2026-05-25-qa-trame-v2/deck-phrases-resolve.json",
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "host": HOST,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "rows": rows,
                "summary": {"pass": pass_n, "partial": partial_n, "fail": fail_n, "total": len(rows)},
            },
            fh,
            ensure_ascii=False,
            indent=2,
        )
    print(f"\nJSON -> {out_path}")
    return 0 if pass_n == len(rows) and partial_n == 0 and fail_n == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
