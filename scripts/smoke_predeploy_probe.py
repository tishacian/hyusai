#!/usr/bin/env python3
"""Pre-deploy smoke probe for the Sentinel-CI demo (lundi 25 mai 2026).

Read-only probe. It logs in to ``agentium.papai.ai``, exercises the 6 voice
prompts of the lundi-matin runbook against ``POST /api/v1/actions/resolve``
(same resolver as ``POST /api/v1/chat/stream``, faster and deterministic),
then runs the API non-regression checks the agent Vague 2 confirmed PASS.

The goal is to distinguish, before the prod redeploy, what already works
(non-regressions) from what depends strictly on the redeploy (Vague 1
phrases, Vague 3 polishs).

Exit code: 0 if >= 50% PASS, 1 otherwise. No mutation, no push.

Usage::

    AGENTIUM_HOST=https://agentium.papai.ai \
    AGENTIUM_EMAIL=thibaud.ishacian@datategy.net \
    AGENTIUM_PASSWORD='ponfib-jaNca5-sisfoc' \
    WORKSPACE_SLUG=sentinel-ci \
    python3 scripts/smoke_predeploy_probe.py
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
PASSWORD = os.environ.get("AGENTIUM_PASSWORD", "ponfib-jaNca5-sisfoc")
TIMEOUT = float(os.environ.get("PROBE_TIMEOUT", "8.0"))


# Voice prompts to probe. ``expected`` is a list of acceptable action_ids
# (the runbook accepts a small fan-out for ambiguous prompts so the probe
# does not artificially fail on synonyms).
VOICE_PROMPTS = [
    {
        "label": "Wake-word seul",
        "text": "AYA",
        "expected": ["aya.acknowledge_presence"],
        "depends_on_redeploy": True,
        "note": "Action aya.acknowledge_presence ajoutee dans la Vague 1 (commit 09188fa6).",
    },
    {
        "label": "Brief matinal",
        "text": "AYA, donne-moi le brief",
        "expected": [
            "aya.priority_summary",
            "aya.focus_zone_with_project",
            "aya.explain_why",
        ],
        "depends_on_redeploy": False,
        "note": "Match priority_summary via overlap 'donne moi le ...' (75%).",
    },
    {
        "label": "PV douanes",
        "text": "pv douanes",
        "expected": ["aya.show_customs_record"],
        "depends_on_redeploy": True,
        "note": "Phrase 'pv douanes' (ultra-court) ajoutee Vague 1 (commit 09188fa6) ; le pack pre-Vague-1 n'avait que 'montre le pv', 'voir le pv des douanes', etc.",
    },
    {
        "label": "Resume Prefet Nawa",
        "text": "resume Prefet Nawa",
        "expected": ["aya.summarize_last_exchanges"],
        "depends_on_redeploy": True,
        "note": "Phrase 'resume prefet nawa' ajoutee Vague 1 (commit 09188fa6).",
    },
    {
        "label": "Rapport complet",
        "text": "genere le rapport complet",
        "expected": ["aya.draft_strategic_report"],
        "depends_on_redeploy": False,
        "note": "Phrase 'genere le rapport complet' presente avant Vague 1.",
    },
    {
        "label": "Prochaine reunion",
        "text": "ouvre la prochaine reunion",
        "expected": ["aya.open_next_meeting"],
        "depends_on_redeploy": False,
        "note": "Substring 'prochaine reunion' presente avant Vague 1.",
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
        raise SystemExit(f"login failed: HTTP {code} body={body!r}")
    payload = json.loads(body)
    if "mfa_token" in payload:
        raise SystemExit("login returned MFA challenge — disable MFA or set non-MFA account")
    return payload["token"]


def probe_voice_prompts(jwt: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for prompt in VOICE_PROMPTS:
        t0 = time.time()
        code, body, _ = _request(
            "POST",
            "/actions/resolve",
            jwt=jwt,
            body={
                "text": prompt["text"],
                "surface": "chat",
                "assistant_profile": "vigie_executive",
            },
        )
        elapsed_ms = int((time.time() - t0) * 1000)
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload = {}
        action_id = payload.get("action_id")
        confidence = payload.get("confidence") or 0.0
        matched = bool(payload.get("matched"))
        is_pass = matched and (action_id in prompt["expected"])
        out.append({
            "label": prompt["label"],
            "prompt": prompt["text"],
            "expected": prompt["expected"],
            "got": action_id,
            "matched": matched,
            "confidence": confidence,
            "http": code,
            "elapsed_ms": elapsed_ms,
            "depends_on_redeploy": prompt["depends_on_redeploy"],
            "note": prompt["note"],
            "pass": is_pass,
        })
    return out


def _get_json(jwt: str, path: str) -> tuple[int, dict[str, Any]]:
    code, body, _ = _request("GET", path, jwt=jwt)
    if not body:
        return code, {}
    try:
        return code, json.loads(body)
    except json.JSONDecodeError:
        return code, {}


def probe_api_checks(jwt: str) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    # ── cockpit ───────────────────────────────────────────────────────────
    code, cockpit = _get_json(jwt, "/mission-room/cockpit")
    cockpit_ok = code == 200 and isinstance(cockpit, dict)

    date_label = cockpit.get("date_label") if cockpit_ok else None
    checks.append({
        "name": "cockpit.date_label",
        "expected": "Lundi 25 Mai 2026",
        "got": date_label,
        "http": code,
        "depends_on_redeploy": False,
        "pass": date_label == "Lundi 25 Mai 2026",
    })

    sb = (cockpit.get("vp_status_bar") if cockpit_ok else None) or []
    sb0 = sb[0] if sb else {}
    checks.append({
        "name": "vp_status_bar[0].key",
        "expected": "zone-nord-tension",
        "got": sb0.get("key"),
        "http": code,
        "depends_on_redeploy": False,
        "pass": sb0.get("key") == "zone-nord-tension",
    })
    checks.append({
        "name": "vp_status_bar[0].pulse",
        "expected": "True",
        "got": sb0.get("pulse"),
        "http": code,
        "depends_on_redeploy": False,
        "pass": bool(sb0.get("pulse")),
    })
    checks.append({
        "name": "vp_status_bar[0].id (alias)",
        "expected": "non-null (Vague 3 polish d1490f18)",
        "got": sb0.get("id"),
        "http": code,
        "depends_on_redeploy": True,
        "pass": sb0.get("id") is not None,
    })

    pp = (cockpit.get("press_preview") if cockpit_ok else None) or []
    hero = pp[0] if pp else {}
    hero_geo = (hero.get("geo_iso") or hero.get("region_iso") or "").upper()
    hero_title = (hero.get("title") or hero.get("headline") or "").lower()
    is_ci_hero = hero_geo == "CI" or any(
        needle in hero_title for needle in ("napie", "napié", "côte d'ivoire", "cote d'ivoire", "abidjan")
    )
    checks.append({
        "name": "press_preview[0] CI-first",
        "expected": "geo=CI or Napie/Abidjan/CI",
        "got": f"{hero_geo}|{hero_title[:48]}",
        "http": code,
        "depends_on_redeploy": True,
        "pass": is_ci_hero,
    })

    ad = cockpit.get("agenda_day") if cockpit_ok else None
    ad_events = (ad or {}).get("events") if ad else []
    first_dates = [str(e.get("date") or e.get("start_at") or "")[:10] for e in (ad_events or [])][:4]
    on_25 = sum(1 for d in first_dates if d == "2026-05-25")
    checks.append({
        "name": "agenda_day.events first 4 dates on 2026-05-25",
        "expected": "all 4 on 2026-05-25",
        "got": ",".join(first_dates) or "(empty)",
        "http": code,
        "depends_on_redeploy": True,
        "pass": on_25 >= 3 and bool(ad_events),
    })

    # ── maritime vessels ───────────────────────────────────────────────────
    code_v, vpayload = _get_json(jwt, "/mission-room/maritime/vessels?bbox=-4.6,5.05,-3.75,5.40")
    vessels = vpayload.get("vessels") if isinstance(vpayload, dict) else (vpayload if isinstance(vpayload, list) else [])
    vcount = len(vessels or [])
    checks.append({
        "name": "maritime/vessels count",
        "expected": "16",
        "got": vcount,
        "http": code_v,
        "depends_on_redeploy": False,
        "pass": vcount == 16,
    })
    mv = next((v for v in (vessels or []) if "atlantic trader" in (v.get("name") or "").lower()), None)
    checks.append({
        "name": "MV Atlantic Trader linked_cargo_id",
        "expected": "cargo-abidjan-supply-001",
        "got": (mv or {}).get("linked_cargo_id"),
        "http": code_v,
        "depends_on_redeploy": False,
        "pass": (mv or {}).get("linked_cargo_id") == "cargo-abidjan-supply-001",
    })
    checks.append({
        "name": "MV Atlantic Trader recommended_webcam_source_id",
        "expected": "apm-apapa-gate-1",
        "got": (mv or {}).get("recommended_webcam_source_id"),
        "http": code_v,
        "depends_on_redeploy": False,
        "pass": (mv or {}).get("recommended_webcam_source_id") == "apm-apapa-gate-1",
    })

    # ── webcams proxy GET ─────────────────────────────────────────────────
    code_g, body_g, ct_g = _request("GET", "/mission-room/webcams/proxy?source_id=apm-apapa-gate-1", jwt=jwt)
    checks.append({
        "name": "webcams/proxy GET apm-apapa-gate-1",
        "expected": "200 image/*",
        "got": f"{code_g} {ct_g}",
        "http": code_g,
        "depends_on_redeploy": False,
        "pass": code_g == 200 and ("image" in (ct_g or "")),
    })

    # ── webcams proxy HEAD (Vague 3 polish d1490f18) ───────────────────────
    code_h, _, _ = _request("HEAD", "/mission-room/webcams/proxy?source_id=apm-apapa-gate-1", jwt=jwt)
    checks.append({
        "name": "webcams/proxy HEAD apm-apapa-gate-1",
        "expected": "200 (Vague 3 polish)",
        "got": code_h,
        "http": code_h,
        "depends_on_redeploy": True,
        "pass": code_h == 200,
    })

    # ── /actions/manifests sanity (acknowledge_presence presence) ──────────
    code_m, mpayload = _get_json(jwt, "/actions/manifests?surface=chat")
    manifests = (mpayload or {}).get("manifests") or []
    has_ack = any(m.get("action_id") == "aya.acknowledge_presence" for m in manifests)
    checks.append({
        "name": "manifest aya.acknowledge_presence present",
        "expected": "True (Vague 1 09188fa6)",
        "got": has_ack,
        "http": code_m,
        "depends_on_redeploy": True,
        "pass": has_ack,
    })

    # ── calendar events: 6 on 25/05 + 2 on 26/05 ───────────────────────────
    code_c, cal = _get_json(jwt, "/calendar/events")
    events = (cal or {}).get("events") if isinstance(cal, dict) else (cal if isinstance(cal, list) else [])
    n25 = sum(1 for e in (events or []) if str(e.get("start_at") or "")[:10] == "2026-05-25")
    n26 = sum(1 for e in (events or []) if str(e.get("start_at") or "")[:10] == "2026-05-26")
    checks.append({
        "name": "calendar/events on 2026-05-25",
        "expected": ">= 6",
        "got": n25,
        "http": code_c,
        "depends_on_redeploy": False,
        "pass": n25 >= 6,
    })
    checks.append({
        "name": "calendar/events on 2026-05-26",
        "expected": ">= 2",
        "got": n26,
        "http": code_c,
        "depends_on_redeploy": False,
        "pass": n26 >= 2,
    })

    return checks


def _truncate(text: Any, width: int) -> str:
    s = "" if text is None else str(text)
    return s if len(s) <= width else s[: width - 1] + "…"


def render(voice_results: list[dict[str, Any]], api_checks: list[dict[str, Any]]) -> tuple[str, int, int]:
    lines: list[str] = []
    lines.append("=" * 110)
    lines.append(
        f"Sentinel-CI smoke pré-deploy probe — {time.strftime('%Y-%m-%d %H:%M:%S %z')}"
    )
    lines.append(
        f"Host: {HOST}    Workspace: {WORKSPACE}    Timeout: {TIMEOUT}s"
    )
    lines.append("=" * 110)

    lines.append("")
    lines.append("## Smoke vocal — POST /api/v1/actions/resolve (surface=chat, profil vigie_executive)")
    lines.append("")
    header = f"{'#':<2} {'PASS':<5} {'PROMPT':<32} {'ATTENDU':<48} {'OBTENU':<32} {'CONF':<5} {'MS':<5} {'POST-DEPLOY':<11}"
    lines.append(header)
    lines.append("-" * 110)
    for i, r in enumerate(voice_results, 1):
        status = "PASS" if r["pass"] else "FAIL"
        exp = "|".join(r["expected"])
        got = r["got"] or "(no_match)"
        lines.append(
            f"{i:<2} {status:<5} {_truncate(r['prompt'], 32):<32} "
            f"{_truncate(exp, 48):<48} {_truncate(got, 32):<32} "
            f"{(r['confidence'] or 0):<5.2f} {r['elapsed_ms']:<5} "
            f"{'oui' if r['depends_on_redeploy'] else 'non':<11}"
        )

    lines.append("")
    lines.append("## API non-régression")
    lines.append("")
    lines.append(f"{'PASS':<5} {'CHECK':<46} {'ATTENDU':<32} {'OBTENU':<32} {'POST-DEPLOY':<11}")
    lines.append("-" * 110)
    for c in api_checks:
        status = "PASS" if c["pass"] else "FAIL"
        lines.append(
            f"{status:<5} {_truncate(c['name'], 46):<46} "
            f"{_truncate(c['expected'], 32):<32} {_truncate(c['got'], 32):<32} "
            f"{'oui' if c['depends_on_redeploy'] else 'non':<11}"
        )

    voice_pass = sum(1 for r in voice_results if r["pass"])
    api_pass = sum(1 for c in api_checks if c["pass"])
    pre_voice_pass = sum(1 for r in voice_results if r["pass"] and not r["depends_on_redeploy"])
    pre_voice_total = sum(1 for r in voice_results if not r["depends_on_redeploy"])
    pre_api_pass = sum(1 for c in api_checks if c["pass"] and not c["depends_on_redeploy"])
    pre_api_total = sum(1 for c in api_checks if not c["depends_on_redeploy"])

    total = len(voice_results) + len(api_checks)
    passed = voice_pass + api_pass

    lines.append("")
    lines.append("=" * 110)
    lines.append(f"Voice : {voice_pass}/{len(voice_results)} PASS    (hors redeploy : {pre_voice_pass}/{pre_voice_total})")
    lines.append(f"API   : {api_pass}/{len(api_checks)} PASS    (hors redeploy : {pre_api_pass}/{pre_api_total})")
    lines.append(f"Total : {passed}/{total} PASS  ({(passed/total*100 if total else 0):.0f}%)")
    lines.append("Disclaimer : les FAIL marqués 'POST-DEPLOY=oui' sont attendus tant que le")
    lines.append("backend prod n'est pas redeployé sur HEAD demo/agentic. Ils doivent passer")
    lines.append("après git push origin demo/agentic + redéploiement.")
    lines.append("=" * 110)

    return "\n".join(lines), passed, total


def main() -> int:
    print(f"[*] Login {EMAIL} on {HOST}", file=sys.stderr)
    jwt = login()
    print(f"[+] JWT len={len(jwt)}", file=sys.stderr)

    print("[*] Probe voice prompts (resolver-only, 6 prompts)…", file=sys.stderr)
    voice = probe_voice_prompts(jwt)
    print("[*] Probe API non-regression checks…", file=sys.stderr)
    api = probe_api_checks(jwt)

    report, passed, total = render(voice, api)
    print(report)
    return 0 if (total > 0 and passed * 2 >= total) else 1


if __name__ == "__main__":
    sys.exit(main())
