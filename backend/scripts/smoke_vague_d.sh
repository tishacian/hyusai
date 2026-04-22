#!/usr/bin/env bash
# Smoke test for Vague D (Cockpit polish) — D7.
#
# Exercises every surface the Vague D plan promised against a running
# backend instance. Complements `test_tenant_isolation.sh` (D1) which
# focuses on cross-tenant leaks.
#
# Tiers:
#   1. No-auth gating        — canonical routes + 401 on protected ones
#   2. Authenticated surface — workspaces, members, audit, settings
#   3. Shipped bundle        — i18n FR/EN, light theme tokens, /chat chunk
#   4. Live run + SSE        — optional, gated by SMOKE_RUN_SSE=1
#
# Usage:
#   BACKEND_URL=https://agentium.papai.ai \
#   KEYCLOAK_URL=https://auth.agentium.papai.ai \
#   REALM=agentium \
#   CLIENT_ID=agentium-backend \
#   ALICE_USER=alice@acme.test \
#   ALICE_PASS=alice-demo \
#   FRONTEND_DIST=/srv/agentium/frontend \
#   SMOKE_RUN_SSE=0 \
#   ./backend/scripts/smoke_vague_d.sh
#
# Exits non-zero on the first failure; full pass/fail counts are
# printed at the end.

set -uo pipefail

BACKEND_URL=${BACKEND_URL:-http://localhost:8000}
KEYCLOAK_URL=${KEYCLOAK_URL:-http://localhost:8080}
REALM=${REALM:-agentium}
CLIENT_ID=${CLIENT_ID:-agentium-backend}
CLIENT_SECRET=${CLIENT_SECRET:-}

ALICE_USER=${ALICE_USER:-alice@acme.test}
ALICE_PASS=${ALICE_PASS:-alice-demo}
ALICE_WS_SLUG=${ALICE_WS_SLUG:-acme}

FRONTEND_DIST=${FRONTEND_DIST:-}
SMOKE_RUN_SSE=${SMOKE_RUN_SSE:-0}

PASS=0
FAIL=0
SKIPPED=0

log()  { printf '\033[36m[smoke]\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m  PASS\033[0m %s\n' "$*"; PASS=$((PASS+1)); }
ko()   { printf '\033[31m  FAIL\033[0m %s\n' "$*"; FAIL=$((FAIL+1)); }
skip() { printf '\033[33m  SKIP\033[0m %s\n' "$*"; SKIPPED=$((SKIPPED+1)); }

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

http_code() {
  # http_code <method> <url> [<extra_curl_args>...]
  local method=$1 url=$2; shift 2
  curl -sS -o /tmp/smoke-body -w '%{http_code}' -X "$method" "$@" "$url" 2>/dev/null || echo "000"
}

expect_code() {
  # expect_code <expected> <method> <url> <label> [<extra_curl_args>...]
  local expected=$1 method=$2 url=$3 label=$4; shift 4
  local got=$(http_code "$method" "$url" "$@")
  if [[ "$got" == "$expected" ]]; then
    ok "$label → $got"
  else
    ko "$label → expected $expected, got $got"
  fi
}

get_token() {
  local user=$1 pass=$2
  local data="grant_type=password&client_id=${CLIENT_ID}&username=${user}&password=${pass}"
  if [[ -n "$CLIENT_SECRET" ]]; then data+="&client_secret=${CLIENT_SECRET}"; fi
  curl -sS -f \
    -d "$data" \
    "${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/token" 2>/dev/null \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("access_token",""))' 2>/dev/null
}

# ---------------------------------------------------------------------------
# Tier 1 — No-auth gating
# ---------------------------------------------------------------------------

log "Tier 1 — canonical routes and auth gating"

expect_code 200 GET "$BACKEND_URL/health"                    "GET /health (public)"
expect_code 200 GET "$BACKEND_URL/"                          "GET /  (SPA index)"

# Gated endpoints MUST refuse anonymous requests after D1.
expect_code 401 GET "$BACKEND_URL/api/v1/systems"             "GET /systems   (no token → 401)"
expect_code 401 GET "$BACKEND_URL/api/v1/runs"                "GET /runs      (no token → 401)"
expect_code 401 GET "$BACKEND_URL/api/v1/audit"               "GET /audit     (no token → 401)"
expect_code 401 GET "$BACKEND_URL/api/v1/settings"            "GET /settings  (no token → 401)"
expect_code 401 GET "$BACKEND_URL/api/v1/skills"              "GET /skills    (no token → 401)"
expect_code 401 GET "$BACKEND_URL/api/v1/capabilities"        "GET /caps      (no token → 401)"
expect_code 401 GET "$BACKEND_URL/api/v1/models"              "GET /models    (no token → 401)"
expect_code 401 POST "$BACKEND_URL/api/v1/voice/transcribe"   "POST /voice/transcribe (no token → 401)"
expect_code 401 GET "$BACKEND_URL/api/v1/contexts"            "GET /contexts  (no token → 401)"
expect_code 401 GET "$BACKEND_URL/api/v1/auth/workspaces"     "GET /auth/workspaces (no token → 401)"

# /chat SPA route — must be served by the catch-all (HTTP 200 with HTML).
body=$(curl -sS -o /dev/null -w '%{content_type}' "$BACKEND_URL/chat" 2>/dev/null || true)
case "$body" in
  text/html*) ok "GET /chat (SPA catch-all → text/html)" ;;
  *)          ko "GET /chat → content-type=$body (expected text/html)" ;;
esac

# ---------------------------------------------------------------------------
# Tier 2 — Authenticated surface
# ---------------------------------------------------------------------------

log "Tier 2 — authenticated surface (Alice)"

ALICE_TOKEN=$(get_token "$ALICE_USER" "$ALICE_PASS" || true)
if [[ -z "${ALICE_TOKEN}" ]]; then
  skip "Tier 2 & 4 — no Keycloak token for $ALICE_USER (realm / client not reachable at $KEYCLOAK_URL)"
else
  AUTH_H="Authorization: Bearer $ALICE_TOKEN"
  WS_H="X-Workspace-Slug: $ALICE_WS_SLUG"

  expect_code 200 GET "$BACKEND_URL/api/v1/auth/workspaces"   "list Alice's workspaces"               -H "$AUTH_H"
  grep -q "\"$ALICE_WS_SLUG\"" /tmp/smoke-body \
    && ok "workspace list contains $ALICE_WS_SLUG" \
    || ko "workspace list does NOT contain $ALICE_WS_SLUG"

  expect_code 200 GET "$BACKEND_URL/api/v1/auth/workspaces/$ALICE_WS_SLUG" \
    "get workspace detail $ALICE_WS_SLUG" -H "$AUTH_H"

  expect_code 200 GET "$BACKEND_URL/api/v1/auth/workspaces/$ALICE_WS_SLUG/members" \
    "list members of $ALICE_WS_SLUG" -H "$AUTH_H"

  expect_code 200 GET "$BACKEND_URL/api/v1/systems"    "list systems (scoped)"  -H "$AUTH_H" -H "$WS_H"
  expect_code 200 GET "$BACKEND_URL/api/v1/audit?limit=20" "list audit (scoped)" -H "$AUTH_H" -H "$WS_H"
  expect_code 200 GET "$BACKEND_URL/api/v1/settings"   "list settings (scoped)" -H "$AUTH_H" -H "$WS_H"
  expect_code 200 GET "$BACKEND_URL/api/v1/contexts"   "list contexts (scoped)" -H "$AUTH_H" -H "$WS_H"
fi

# ---------------------------------------------------------------------------
# Tier 3 — shipped bundle (i18n + theme + chat)
# ---------------------------------------------------------------------------

log "Tier 3 — shipped bundle surface"

if [[ -z "$FRONTEND_DIST" || ! -d "$FRONTEND_DIST" ]]; then
  skip "FRONTEND_DIST unset or missing ($FRONTEND_DIST) — bundle checks skipped"
else
  # D3 — FR + EN dictionaries compiled into the JS bundle.
  # Use a few distinctive strings from i18n.dict.ts that are unlikely to
  # appear elsewhere.
  if grep -qrE "Rechercher|Paramètres|Compte" "$FRONTEND_DIST" --include='*.js' 2>/dev/null; then
    ok "FR dictionary present in bundle"
  else
    ko "FR dictionary NOT found in bundle"
  fi
  if grep -qrE "Settings|Account|Search…" "$FRONTEND_DIST" --include='*.js' 2>/dev/null; then
    ok "EN dictionary present in bundle"
  else
    ko "EN dictionary NOT found in bundle"
  fi

  # D4 — light theme tokens compiled into styles. The Angular CSS
  # optimiser strips attribute-selector quotes, so accept both forms.
  if grep -qrE 'data-theme=("?)light\1]' "$FRONTEND_DIST" --include='*.css' 2>/dev/null; then
    ok "light theme tokens compiled in CSS"
  else
    ko "light theme selector [data-theme=light] missing from CSS"
  fi
  if grep -qr '\-\-ck-on-signal' "$FRONTEND_DIST" --include='*.css' 2>/dev/null; then
    ok "--ck-on-signal token present (D4 signal contrast)"
  else
    ko "--ck-on-signal token missing — D4 audit fix did not ship"
  fi
  if grep -qr '\-\-ck-shadow-panel' "$FRONTEND_DIST" --include='*.css' 2>/dev/null; then
    ok "--ck-shadow-panel token present (D4 theme-aware shadows)"
  else
    ko "--ck-shadow-panel token missing"
  fi

  # D0 — /chat lazy route chunk shipped.
  if ls "$FRONTEND_DIST"/*chat* 2>/dev/null | grep -qE 'chat.*\.js$'; then
    ok "chat lazy chunk shipped (*.chat*.js)"
  else
    # Chunk names are hashed — look for the chat-workspace component
    # token string in any chunk as a fallback.
    if grep -qr 'chat-workspace' "$FRONTEND_DIST" --include='*.js' 2>/dev/null; then
      ok "chat-workspace code present in bundle (hashed chunk)"
    else
      ko "chat feature not detected in any shipped chunk"
    fi
  fi
fi

# ---------------------------------------------------------------------------
# Tier 4 — live run + SSE token_delta (opt-in)
# ---------------------------------------------------------------------------

log "Tier 4 — live run + SSE (opt-in via SMOKE_RUN_SSE=1)"

if [[ "$SMOKE_RUN_SSE" != "1" ]]; then
  skip "Tier 4 disabled — set SMOKE_RUN_SSE=1 to exercise it"
elif [[ -z "${ALICE_TOKEN:-}" ]]; then
  skip "Tier 4 — no Keycloak token"
else
  AUTH_H="Authorization: Bearer $ALICE_TOKEN"
  WS_H="X-Workspace-Slug: $ALICE_WS_SLUG"

  # Resolve any streaming-capable system (bound to azure_llm_v1 or
  # llm_rag_answer_v1 — see D2). We just grab the first system; the
  # operator is expected to have seeded one that actually calls an LLM.
  curl -sS -o /tmp/smoke-body -w '' -H "$AUTH_H" -H "$WS_H" \
    "$BACKEND_URL/api/v1/systems?limit=1" 2>/dev/null || true
  SYS_ID=$(python3 -c 'import json,sys;d=json.load(open("/tmp/smoke-body"));print((d[0] if isinstance(d,list) and d else {}).get("id",""))' 2>/dev/null || echo "")
  if [[ -z "$SYS_ID" ]]; then
    skip "Tier 4 — no system available to run"
  else
    log "Scheduling a run against system $SYS_ID …"
    code=$(http_code POST "$BACKEND_URL/api/v1/runs" \
      -H "$AUTH_H" -H "$WS_H" -H "Content-Type: application/json" \
      --data "{\"system_id\":\"$SYS_ID\",\"input_ref\":{\"question\":\"What is OmniRAG?\"}}")
    if [[ "$code" != "200" && "$code" != "201" ]]; then
      ko "POST /runs returned $code"
    else
      RUN_ID=$(python3 -c 'import json;print(json.load(open("/tmp/smoke-body")).get("id",""))' 2>/dev/null)
      [[ -n "$RUN_ID" ]] || { ko "POST /runs did not return an id"; RUN_ID=""; }
      if [[ -n "$RUN_ID" ]]; then
        ok "Run scheduled: $RUN_ID"
        log "Subscribing to SSE for 6s, looking for token_delta…"
        (timeout 6 curl -sS -N -H "$AUTH_H" "$BACKEND_URL/api/v1/runs/$RUN_ID/stream" 2>/dev/null || true) \
          | tee /tmp/smoke-sse > /dev/null
        if grep -q '"kind":"token_delta"' /tmp/smoke-sse; then
          ok "SSE stream delivered token_delta frames"
        else
          # token_delta only fires if the run's active skill actually
          # calls the token sink. Older runs / non-LLM systems won't.
          ko "no token_delta frames observed in 6s SSE window"
        fi
        if grep -q '"kind":"run_end"\|"kind":"node_end"' /tmp/smoke-sse; then
          ok "SSE stream delivered structural events (node_end / run_end)"
        else
          ko "no structural SSE events observed"
        fi
      fi
    fi
  fi
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

printf '\n'
log "Results: \033[32m%d pass\033[0m / \033[31m%d fail\033[0m / \033[33m%d skipped\033[0m" "$PASS" "$FAIL" "$SKIPPED"
[[ "$FAIL" -eq 0 ]] || exit 1
