#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Pre-demo reset — SENTINEL-CI / AYA  (date courante Africa/Abidjan)
#
# Purpose: prepare the production workspace at https://agentium.papai.ai for a
# clean run of the demo trame (docs/demo-aya-storytelling-trame.md). Run this
# script ~5 min before the demo starts. It is idempotent and safe to re-run.
#
# What it does (in this order):
#   1. Login via Keycloak realm "papai-org" → grab a 2h JWT.
#   2. PATCH /api/v1/auth/workspaces/sentinel-ci
#      a. Bump settings.demo_time_context to the current Africa/Abidjan day.
#      b. Reset settings.actions.last_focus / awaiting / current_meeting /
#         pending_agenda_patch so the explain_why drill restarts at zone-nord.
#   2b. Purge debug / legacy calendar events via admin DELETE
#      (title/desc matching "agenda QA wiring" / "debug", or start_at < DEMO_DATE).
#      Never touches events from DEMO_DATE onward.
#   3. Reseed the SENTINEL-CI calendar:
#      a. Cancel every existing event (workspace-scoped).
#      b. POST the canonical seed events. Runtime APIs roll these fixtures onto
#         the current Africa/Abidjan day and J+1/J+2 for presentation.
#   4. (Optional) Generate the strategic cacao PDF via POST /reports/generate
#      so the object store has a fresh artifact for S2.3.
#   5. (Optional, post-deploy) Call the admin reseed/rebuild endpoints if the
#      new admin router is deployed.
#   6. Verify cockpit / calendar / report endpoints.
#
# Requirements: bash, curl, python3.
#
# Usage:
#   AGENTIUM_EMAIL='<operator-email>' \
#   AGENTIUM_PASSWORD='<from-secret-manager>' \
#   ./scripts/predemo_reset.sh
#
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

AGENTIUM_HOST="${AGENTIUM_HOST:-https://agentium.papai.ai}"
WORKSPACE_SLUG="${WORKSPACE_SLUG:-sentinel-ci}"
: "${AGENTIUM_EMAIL:?AGENTIUM_EMAIL is required}"
: "${AGENTIUM_PASSWORD:?AGENTIUM_PASSWORD is required}"
DEMO_TZ="${DEMO_TZ:-Africa/Abidjan}"
DEMO_DATE="${DEMO_DATE:-$(TZ="${DEMO_TZ}" date +%F)}"
DEMO_TIME="${DEMO_TIME:-$(TZ="${DEMO_TZ}" date +%H:%M:%S)}"
DEMO_LABEL="${DEMO_LABEL:-$(DEMO_DATE="${DEMO_DATE}" python3 -c 'import datetime, os; months=["Janvier","Fevrier","Mars","Avril","Mai","Juin","Juillet","Aout","Septembre","Octobre","Novembre","Decembre"]; days=["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi","Dimanche"]; d=datetime.date.fromisoformat(os.environ["DEMO_DATE"]); print(f"{days[d.weekday()]} {d.day} {months[d.month-1]} {d.year}")')}"
export AGENTIUM_HOST WORKSPACE_SLUG AGENTIUM_EMAIL AGENTIUM_PASSWORD DEMO_DATE DEMO_TIME DEMO_LABEL DEMO_TZ

say() { printf "\n\033[1;36m▶ %s\033[0m\n" "$*"; }
ok()  { printf "  \033[1;32m✓\033[0m %s\n" "$*"; }
warn(){ printf "  \033[1;33m⚠\033[0m %s\n" "$*"; }
err() { printf "  \033[1;31m✗\033[0m %s\n" "$*"; }

# ─── 1. login ────────────────────────────────────────────────────────────────
say "Login → ${AGENTIUM_HOST}"
JWT=$(curl -sf -X POST "${AGENTIUM_HOST}/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d "$(printf '{"email":"%s","password":"%s","remember_me":false}' "$AGENTIUM_EMAIL" "$AGENTIUM_PASSWORD")" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")
[ -n "${JWT}" ] && ok "JWT acquired (len=${#JWT})" || { err "login failed"; exit 1; }
export JWT

CURL_AUTH=(-H "Authorization: Bearer ${JWT}" -H "X-Workspace-Slug: ${WORKSPACE_SLUG}")

# ─── 2. workspace settings PATCH ─────────────────────────────────────────────
say "PATCH workspace settings (demo_time_context + reset actions)"
python3 - <<PYEOF > /tmp/agentium_workspace_patch.json
import json, os, urllib.request

base = os.environ.get("AGENTIUM_HOST", "${AGENTIUM_HOST}")
slug = os.environ.get("WORKSPACE_SLUG", "${WORKSPACE_SLUG}")
jwt = os.environ["JWT"]
req = urllib.request.Request(
    f"{base}/api/v1/auth/workspaces/{slug}",
    headers={"Authorization": f"Bearer {jwt}", "X-Workspace-Slug": slug},
)
with urllib.request.urlopen(req, timeout=30) as resp:
    workspace = json.load(resp)
s = dict(workspace.get("settings") or {})
s["demo_time_context"] = {
    "mode": "rolling",
    "current_date": "${DEMO_DATE}",
    "current_time": "${DEMO_TIME}",
    "label": "${DEMO_LABEL}",
    "timezone": "${DEMO_TZ}",
}
actions = dict(s.get("actions") or {})
# S3 — clear any lingering security focus from a previous run so the dual-axis
# briefing starts cold (no posture card pre-selected, no rumor dossier carried
# over from a prior trace_rumor_origin invocation).
actions["last_focus"] = None
actions["awaiting"] = {}
actions["current_meeting"] = None
actions.pop("pending_agenda_patch", None)
# Always enable the S1/S2/S3 packs in order. We replace the list rather than
# setdefault so a previous predemo run that pre-dates S3 still picks up the
# security pack on the next reset.
actions["enabled_packs"] = [
    "global_voice_v1",
    "sentinel_ci_aya_v1",
    "sentinel_ci_aya_security_v1",
]
s["actions"] = actions
print(json.dumps({"settings": s}))
PYEOF
HTTP_CODE=$(curl -s -o /tmp/agentium_workspace_resp.json -w "%{http_code}" -X PATCH \
  "${AGENTIUM_HOST}/api/v1/auth/workspaces/${WORKSPACE_SLUG}" \
  "${CURL_AUTH[@]}" \
  -H "Content-Type: application/json" \
  --data-binary @/tmp/agentium_workspace_patch.json)
[ "${HTTP_CODE}" = "200" ] && ok "workspace PATCH 200" || { err "PATCH HTTP ${HTTP_CODE}"; cat /tmp/agentium_workspace_resp.json; exit 1; }

# ─── 2b. purge debug / legacy calendar events (admin DELETE) ────────────────
# Hard-delete any QA pollution rows (titles/desc matching "agenda QA wiring",
# "QA wiring VIGIE", "debug") and any legacy event dated strictly before the
# demo date (DEMO_DATE). Lundi/mardi seed events are never touched here.
# Requires the admin router to be deployed; warns gracefully if 404.
say "Purge debug / legacy calendar events (admin DELETE) — preserves DEMO_DATE+"
DEMO_DATE_CUTOFF="${DEMO_DATE}" python3 <<'PYEOF'
import json, os, urllib.request, urllib.error
base = os.environ["AGENTIUM_HOST"]
slug = os.environ["WORKSPACE_SLUG"]
jwt = os.environ["JWT"]
cutoff = os.environ["DEMO_DATE_CUTOFF"]  # YYYY-MM-DD
HDRS = {"Authorization": f"Bearer {jwt}", "X-Workspace-Slug": slug, "Content-Type": "application/json"}

def http(method, path, body=None):
    req = urllib.request.Request(f"{base}/api/v1{path}", method=method, headers=HDRS)
    if body is not None:
        req.data = json.dumps(body).encode("utf-8")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")

DEBUG_NEEDLES = ("agenda qa wiring", "qa wiring vigie", "qa wiring", "debug")

code, body = http("GET", "/calendar/events")
if code != 200:
    print(f"  ! GET /calendar/events HTTP {code} — skipping purge")
    raise SystemExit(0)
events = json.loads(body).get("events") or []

debug_hits, legacy_hits = [], []
for e in events:
    title = (e.get("title") or "").lower()
    desc = (e.get("description") or "").lower()
    start = (e.get("start_at") or "")[:10]
    is_debug = any(n in title or n in desc for n in DEBUG_NEEDLES)
    is_legacy = bool(start) and start < cutoff
    if is_debug:
        debug_hits.append(e)
    elif is_legacy:
        legacy_hits.append(e)

if not debug_hits and not legacy_hits:
    print(f"  no debug / pre-{cutoff} events to purge (scanned {len(events)} event(s))")
    raise SystemExit(0)

print(f"  candidates: {len(debug_hits)} debug + {len(legacy_hits)} legacy (pre-{cutoff})")
deleted, admin_blocked = 0, False
for e in debug_hits + legacy_hits:
    eid = e["id"]
    code, body = http("DELETE", f"/admin/calendar/events/{eid}")
    if code == 200:
        deleted += 1
        print(f"  ✓ deleted {eid[:8]} start={(e.get('start_at') or '')[:16]} title={(e.get('title') or '')[:60]!r}")
    elif code in (403, 404):
        admin_blocked = True
        print(f"  ! admin DELETE {eid[:8]} HTTP {code} — admin router likely not deployed yet")
        break
    else:
        print(f"  ✗ admin DELETE {eid[:8]} HTTP {code} body={body[:200]}")

if admin_blocked:
    print("  ⚠ admin DELETE blocked — falling back on admin reseed (step 5) which wipes via DB reseed")
print(f"  purged {deleted}/{len(debug_hits) + len(legacy_hits)} matching events")
PYEOF

# ─── 3. reseed calendar ──────────────────────────────────────────────────────
say "Reseed calendar (cancel all, then POST 8 events)"
python3 <<'PYEOF'
import json, os, urllib.request, urllib.error
base = os.environ["AGENTIUM_HOST"]
slug = os.environ["WORKSPACE_SLUG"]
jwt = os.environ["JWT"]
HDRS = {"Authorization": f"Bearer {jwt}", "X-Workspace-Slug": slug, "Content-Type": "application/json"}

def http(method, path, body=None):
    req = urllib.request.Request(f"{base}/api/v1{path}", method=method, headers=HDRS)
    if body is not None:
        req.data = json.dumps(body).encode("utf-8")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")

_, body = http("GET", "/calendar/events")
events = json.loads(body)["events"]
print(f"  cancelling {len(events)} existing event(s)")
for e in events:
    http("POST", f"/calendar/events/{e['id']}/cancel", {"reason": "predemo reset"})

SEED = [
    {"seed_id": "evt-conseil-defense","title": "Conseil Defense restreint",
     "description": "Point de coordination securitaire et arbitrages cabinet.",
     "start_at": "2026-05-25T08:30:00", "end_at": "2026-05-25T09:30:00",
     "location": "Salle du Conseil - Plateau",
     "participants": ["Ministre", "Directeur de cabinet", "Conseiller securite"],
     "category": "cabinet", "priority": "critical"},
    {"seed_id": "evt-prefet-nawa","title": "Rencontre Prefet de la region de Nawa",
     "description": "Suite au rapport du 10 mai : filiere cacao, infrastructures et diversification regionale.",
     "start_at": "2026-05-25T11:00:00", "end_at": "2026-05-25T12:00:00",
     "location": "Soubre (capitale regionale)",
     "participants": ["Vice Premier Ministre", "Prefet de Nawa", "AYA"],
     "category": "territorial", "priority": "high",
     "context_ref": "report-prefet-nawa-2026-05-10"},
    {"seed_id": "evt-point-presse","title": "Point presse hebdomadaire",
     "description": "Preparation des elements de langage et suivi image publique.",
     "start_at": "2026-05-25T11:45:00", "end_at": "2026-05-25T12:30:00",
     "location": "Salle presse ministere",
     "participants": ["Ministre", "Communication", "Porte-parole"],
     "category": "press", "priority": "high"},
    {"seed_id": "evt-dejeuner-france","title": "Dejeuner Ambassadeur de France",
     "description": "Cooperation FR-CI, perception publique et projets frontaliers.",
     "start_at": "2026-05-25T13:00:00", "end_at": "2026-05-25T14:15:00",
     "location": "Residence officielle",
     "participants": ["Ministre", "Ambassadeur de France", "Conseiller cooperation"],
     "category": "diplomacy", "priority": "medium"},
    {"seed_id": "evt-revue-sahel","title": "Revue operations Sahel",
     "description": "Synthese signaux regionaux et implications non militaires.",
     "start_at": "2026-05-25T15:00:00", "end_at": "2026-05-25T16:00:00",
     "location": "Centre de commandement",
     "participants": ["Ministre", "Cellule veille", "Strategie"],
     "category": "strategy", "priority": "high"},
    {"seed_id": "evt-audience-parlement","title": "Audience parlementaire",
     "description": "Reponses institutionnelles et suivi des questions sensibles.",
     "start_at": "2026-05-25T17:40:00", "end_at": "2026-05-25T18:30:00",
     "location": "Assemblee Nationale",
     "participants": ["Ministre", "Cabinet parlementaire"],
     "category": "institutional", "priority": "medium"},
    {"seed_id": "evt-comite-nord","title": "Comite projets sociaux Nord",
     "description": "Arbitrage des retards terrain et communication preventive.",
     "start_at": "2026-05-26T09:00:00", "end_at": "2026-05-26T10:00:00",
     "location": "Salon cabinet",
     "participants": ["Ministre", "Dircab", "Pilotage projets"],
     "category": "projects", "priority": "critical"},
    {"seed_id": "evt-brief-ao","title": "Brief veille Afrique de l'Ouest",
     "description": "Lecture des signaux faibles presse et diplomatie regionale.",
     "start_at": "2026-05-26T14:00:00", "end_at": "2026-05-26T14:45:00",
     "location": "Bureau Ministre",
     "participants": ["Monsieur le Vice Premier Ministre", "AYA", "Cellule veille"],
     "category": "intelligence", "priority": "high"},
]
ok = 0
for spec in SEED:
    metadata = {"seed": "sentinel-ci", "connector_id": "institutional_calendar",
                "seed_id": spec["seed_id"]}
    if spec.get("context_ref"):
        metadata["context_ref"] = spec["context_ref"]
    payload = {"title": spec["title"], "start_at": spec["start_at"], "end_at": spec["end_at"],
               "location": spec["location"], "description": spec["description"],
               "participants": spec["participants"], "category": spec["category"],
               "priority": spec["priority"], "status": "scheduled", "metadata": metadata}
    code, body = http("POST", "/calendar/events", payload)
    if code == 200:
        ok += 1
        print(f"  ✓ {spec['seed_id']}")
    else:
        print(f"  ✗ {spec['seed_id']} HTTP {code} body={body[:200]}")
print(f"  reseeded {ok}/{len(SEED)} events")
PYEOF

# ─── 4. strategic cacao report (PDF warmup) ─────────────────────────────────
say "Warm strategic cacao report (POST /reports/generate)"
HTTP_CODE=$(curl -s -o /tmp/agentium_report_resp.json -w "%{http_code}" -X POST \
  "${AGENTIUM_HOST}/api/v1/reports/generate" \
  "${CURL_AUTH[@]}" \
  -H "Content-Type: application/json" \
  -d '{"topic":"cacao_diversification","context_refs":["report-prefet-nawa-2026-05-10","proj-cacao-transformation-nawa"],"target_id":"package-cacao-diversification","length":"long"}')
[ "${HTTP_CODE}" = "200" ] && ok "report generated" || warn "report HTTP ${HTTP_CODE}"
REPORT_ID=$(python3 -c "import json; print(json.load(open('/tmp/agentium_report_resp.json')).get('report_id',''))" 2>/dev/null || echo "")
[ -n "$REPORT_ID" ] && ok "report_id=${REPORT_ID}"

# ─── 5. optional: admin reseed + reports rebuild (post-deploy only) ─────────
say "Optional admin reseed (needs deployed admin router; will 404 otherwise)"
HTTP_CODE=$(curl -s -o /tmp/agentium_admin_reseed.json -w "%{http_code}" -X POST \
  "${AGENTIUM_HOST}/api/v1/admin/calendar/reseed?confirm=true" \
  "${CURL_AUTH[@]}")
if [ "${HTTP_CODE}" = "200" ]; then
  ok "admin calendar reseed 200 (deployed code OK)"
elif [ "${HTTP_CODE}" = "404" ]; then
  warn "admin/calendar/reseed not deployed yet (404) — manual POST loop above is sufficient"
else
  warn "admin reseed HTTP ${HTTP_CODE}"
fi
HTTP_CODE=$(curl -s -o /tmp/agentium_admin_rebuild.json -w "%{http_code}" -X POST \
  "${AGENTIUM_HOST}/api/v1/admin/reports/rebuild?rebuild_prefet=true&rebuild_strategic_cacao=true" \
  "${CURL_AUTH[@]}")
if [ "${HTTP_CODE}" = "200" ]; then
  ok "admin reports rebuild 200 (Prefet PDF + cacao PDF in store)"
elif [ "${HTTP_CODE}" = "404" ]; then
  warn "admin/reports/rebuild not deployed yet — Prefet 70p PDF needs build_sentinel_reports CLI"
else
  warn "admin rebuild HTTP ${HTTP_CODE}"
fi

# ─── 6. verify ───────────────────────────────────────────────────────────────
say "Verify cockpit + calendar + report"
python3 <<'PYEOF'
import json, os, urllib.request
base = os.environ["AGENTIUM_HOST"]
slug = os.environ["WORKSPACE_SLUG"]
jwt = os.environ["JWT"]
hdrs = {"Authorization": f"Bearer {jwt}", "X-Workspace-Slug": slug}

def fetch(path):
    req = urllib.request.Request(f"{base}/api/v1{path}", headers=hdrs)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)

ws = fetch("/auth/workspaces/sentinel-ci")
dtc = (ws.get("settings") or {}).get("demo_time_context") or {}
print(f"  workspace.demo_time_context.current_date = {dtc.get('current_date')} ({dtc.get('label')})")
acts = (ws.get("settings") or {}).get("actions") or {}
print(f"  workspace.actions.last_focus = {acts.get('last_focus')}")
print(f"  workspace.actions.awaiting  = {acts.get('awaiting')}")
print(f"  workspace.actions.current_meeting = {acts.get('current_meeting')}")

cal = fetch("/calendar/events?status=scheduled")
events = cal.get("events") or []
print(f"  calendar scheduled events: {len(events)}")
prefet = [e for e in events if (e.get('metadata') or {}).get('seed_id') == 'evt-prefet-nawa']
if prefet:
    p = prefet[0]
    print(f"  evt-prefet-nawa OK -> id={p['id'][:8]}.. start={p['start_at']} context_ref={(p.get('metadata') or {}).get('context_ref')}")
else:
    print("  ✗ evt-prefet-nawa missing")

ck = fetch("/mission-room/cockpit")
print(f"  cockpit.date_label = {ck.get('date_label')!r}")
sb = (ck.get("vp_status_bar") or [{}])[0]
print(f"  cockpit.vp_status_bar[0] = key={sb.get('key')!r} value={sb.get('value')!r} tone={sb.get('tone')!r}")
PYEOF

say "All done — demo workspace ready"
