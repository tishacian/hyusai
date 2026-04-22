#!/usr/bin/env bash
# Tenant isolation smoke test (Vague D / D1.4).
#
# Drives two Keycloak users (alice + bob) against a running backend
# instance and asserts that neither can see nor mutate the other's
# workspace data. Exits non-zero on the first leak.
#
# Usage:
#   BACKEND_URL=http://localhost:8000 \
#   KEYCLOAK_URL=http://localhost:8080 \
#   REALM=agentium \
#   CLIENT_ID=agentium-backend \
#   CLIENT_SECRET=<optional> \
#   ./backend/scripts/test_tenant_isolation.sh
#
# The two users must already exist in the realm (see
# backend/keycloak/realm-export.json — alice@acme.test / alice-demo and
# bob@globex.test / bob-demo are seeded by default).

set -euo pipefail

BACKEND_URL=${BACKEND_URL:-http://localhost:8000}
KEYCLOAK_URL=${KEYCLOAK_URL:-http://localhost:8080}
REALM=${REALM:-agentium}
CLIENT_ID=${CLIENT_ID:-agentium-backend}
CLIENT_SECRET=${CLIENT_SECRET:-}

ALICE_USER=${ALICE_USER:-alice@acme.test}
ALICE_PASS=${ALICE_PASS:-alice-demo}
BOB_USER=${BOB_USER:-bob@globex.test}
BOB_PASS=${BOB_PASS:-bob-demo}

PASS=0
FAIL=0

log() { printf '\033[36m[test]\033[0m %s\n' "$*"; }
ok() { printf '\033[32m  PASS\033[0m %s\n' "$*"; PASS=$((PASS+1)); }
ko() { printf '\033[31m  FAIL\033[0m %s\n' "$*"; FAIL=$((FAIL+1)); }

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

get_token() {
  local user=$1 pass=$2
  local data="grant_type=password&client_id=${CLIENT_ID}&username=${user}&password=${pass}"
  if [[ -n "$CLIENT_SECRET" ]]; then
    data+="&client_secret=${CLIENT_SECRET}"
  fi
  curl -sS -f \
    -d "$data" \
    "${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/token" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])'
}

api() {
  # api <token> <method> <path> [<body>] [<extra_curl_args>...]
  local token=$1 method=$2 path=$3; shift 3
  local body=""
  if [[ $# -gt 0 && "$1" != -* ]]; then body=$1; shift; fi
  local args=(-sS -o /tmp/iso-body.json -w '%{http_code}' -X "$method"
              -H "Authorization: Bearer $token"
              -H "Content-Type: application/json")
  if [[ -n "$body" ]]; then args+=(--data "$body"); fi
  curl "${args[@]}" "$@" "${BACKEND_URL}${path}"
}

json_get() { python3 -c "import json,sys; print(json.load(sys.stdin)$1)" < /tmp/iso-body.json; }

# ---------------------------------------------------------------------------
# 1. Log in both users
# ---------------------------------------------------------------------------

log "Obtaining Keycloak tokens…"
ALICE_TOKEN=$(get_token "$ALICE_USER" "$ALICE_PASS")
BOB_TOKEN=$(get_token "$BOB_USER" "$BOB_PASS")
[[ -n "$ALICE_TOKEN" && -n "$BOB_TOKEN" ]] || { echo "Could not get tokens"; exit 2; }
ok "Both users obtained access tokens"

# ---------------------------------------------------------------------------
# 2. Each user creates their own workspace (idempotent — reuse if exists)
# ---------------------------------------------------------------------------

ensure_workspace() {
  local token=$1 slug=$2 name=$3
  local code=$(api "$token" POST "/api/v1/auth/workspaces" "{\"name\":\"$name\",\"slug\":\"$slug\"}")
  if [[ "$code" == "201" || "$code" == "200" ]]; then return; fi
  if [[ "$code" == "409" ]]; then return; fi
  echo "ensure_workspace $slug failed with code $code: $(cat /tmp/iso-body.json)"; exit 2
}

log "Ensuring workspaces exist…"
ensure_workspace "$ALICE_TOKEN" acme "Acme"
ensure_workspace "$BOB_TOKEN" globex "Globex"
ok "acme + globex workspaces present"

# ---------------------------------------------------------------------------
# 3. Each user creates a System in their workspace
# ---------------------------------------------------------------------------

create_system() {
  local token=$1 slug=$2 name=$3
  local code=$(api "$token" POST "/api/v1/systems" \
    "{\"name\":\"$name\",\"description\":\"iso-test\"}" \
    -H "X-Workspace-Slug: $slug")
  [[ "$code" == "200" || "$code" == "201" ]] \
    || { echo "create_system failed: $code $(cat /tmp/iso-body.json)"; exit 2; }
  json_get '["id"]'
}

log "Creating a System in each workspace…"
ACME_SYS=$(create_system "$ALICE_TOKEN" acme "Acme-Guide")
GLOBEX_SYS=$(create_system "$BOB_TOKEN" globex "Globex-Guide")
ok "Alice's system: $ACME_SYS"
ok "Bob's   system: $GLOBEX_SYS"

# ---------------------------------------------------------------------------
# 4. Isolation assertions
# ---------------------------------------------------------------------------

log "Listing Alice's systems in Acme workspace…"
code=$(api "$ALICE_TOKEN" GET "/api/v1/systems" -H "X-Workspace-Slug: acme")
[[ "$code" == "200" ]] || { ko "Alice GET /systems returned $code"; }
grep -q "$ACME_SYS"   /tmp/iso-body.json && ok "Acme list contains Alice's system"  || ko "Acme list missing Alice's system"
grep -q "$GLOBEX_SYS" /tmp/iso-body.json && ko "LEAK: Acme list contains Globex's system" || ok "Acme list does not contain Globex's system"

log "Listing Bob's systems in Globex workspace…"
api "$BOB_TOKEN" GET "/api/v1/systems" -H "X-Workspace-Slug: globex" > /dev/null
grep -q "$GLOBEX_SYS" /tmp/iso-body.json && ok "Globex list contains Bob's system"   || ko "Globex list missing Bob's system"
grep -q "$ACME_SYS"   /tmp/iso-body.json && ko "LEAK: Globex list contains Acme's system" || ok "Globex list does not contain Acme's system"

log "Alice tries to GET Bob's system directly…"
code=$(api "$ALICE_TOKEN" GET "/api/v1/systems/$GLOBEX_SYS" -H "X-Workspace-Slug: acme")
[[ "$code" == "404" || "$code" == "403" ]] \
  && ok "Direct read of cross-tenant system blocked ($code)" \
  || ko "LEAK: Alice got Bob's system via direct GET ($code)"

log "Alice tries to PATCH Bob's system…"
code=$(api "$ALICE_TOKEN" PATCH "/api/v1/systems/$GLOBEX_SYS" '{"name":"stolen"}' -H "X-Workspace-Slug: acme")
[[ "$code" == "404" || "$code" == "403" ]] \
  && ok "Cross-tenant PATCH blocked ($code)" \
  || ko "LEAK: Alice mutated Bob's system ($code)"

log "Alice tries to spoof X-Workspace-Slug to Bob's workspace…"
code=$(api "$ALICE_TOKEN" GET "/api/v1/systems" -H "X-Workspace-Slug: globex")
[[ "$code" == "403" || "$code" == "404" ]] \
  && ok "Workspace-slug spoof blocked ($code)" \
  || ko "LEAK: Alice reached globex via slug spoof ($code)"

# ---------------------------------------------------------------------------
# 5. Audit log isolation
# ---------------------------------------------------------------------------

log "Each user posts an audit event; verify no cross-read…"
api "$ALICE_TOKEN" POST "/api/v1/audit" '{"event_type":"iso.test.acme"}'   -H "X-Workspace-Slug: acme"   > /dev/null
api "$BOB_TOKEN"   POST "/api/v1/audit" '{"event_type":"iso.test.globex"}' -H "X-Workspace-Slug: globex" > /dev/null

api "$ALICE_TOKEN" GET "/api/v1/audit?limit=500" -H "X-Workspace-Slug: acme" > /dev/null
grep -q "iso.test.acme"   /tmp/iso-body.json && ok "Alice sees her own audit event"    || ko "Alice missing her own audit event"
grep -q "iso.test.globex" /tmp/iso-body.json && ko "LEAK: Alice sees Globex audit"     || ok "Alice does not see Globex audit"

api "$BOB_TOKEN" GET "/api/v1/audit?limit=500" -H "X-Workspace-Slug: globex" > /dev/null
grep -q "iso.test.globex" /tmp/iso-body.json && ok "Bob sees his own audit event"      || ko "Bob missing his own audit event"
grep -q "iso.test.acme"   /tmp/iso-body.json && ko "LEAK: Bob sees Acme audit"         || ok "Bob does not see Acme audit"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

printf '\n'
log "Results: \033[32m%d pass\033[0m / \033[31m%d fail\033[0m" "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]] || exit 1
