#!/usr/bin/env bash
# Idempotent seed of the demo users (and any extras) declared in
# `backend/keycloak/realm-export.json` into a live Keycloak realm.
#
# Why this exists: the realm-export is only consulted when Keycloak
# imports a realm for the first time (`--import-realm` / first boot
# with a bind-mount). After the realm exists, any user added to the
# export file will NOT be back-filled automatically — the team has hit
# this twice (D1 → D7 rollouts) with Alice and Bob.
#
# This script walks the users array in realm-export.json and, for each
# entry, creates the user via the admin REST API if missing, then
# resets their password to the value declared in `credentials[0]`.
# It skips `admin` (bootstrap user, don't clobber).
#
# Usage:
#   KC_URL=http://127.0.0.1:8080/kc \
#   KC_REALM=papai-org \
#   KC_ADMIN_USER=admin KC_ADMIN_PASS=admin \
#   REALM_EXPORT=backend/keycloak/realm-export.json \
#   ./backend/scripts/seed_keycloak_users.sh
#
# Run this from the VM where Keycloak is reachable on localhost, OR
# point KC_URL at the public URL if admin-cli is exposed.

set -euo pipefail

KC_URL=${KC_URL:-http://127.0.0.1:8080/kc}
KC_REALM=${KC_REALM:-papai-org}
KC_ADMIN_USER=${KC_ADMIN_USER:-admin}
KC_ADMIN_PASS=${KC_ADMIN_PASS:-admin}
REALM_EXPORT=${REALM_EXPORT:-backend/keycloak/realm-export.json}

if [[ ! -f "$REALM_EXPORT" ]]; then
  echo "realm-export.json not found at $REALM_EXPORT" >&2
  exit 2
fi

log()  { printf '\033[36m[seed]\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m  OK\033[0m %s\n' "$*"; }
skip() { printf '\033[33m  SKIP\033[0m %s\n' "$*"; }

log "Requesting admin token from $KC_URL/realms/master …"
TOKEN=$(curl -sSf -X POST "$KC_URL/realms/master/protocol/openid-connect/token" \
  -d "client_id=admin-cli" -d "username=$KC_ADMIN_USER" -d "password=$KC_ADMIN_PASS" \
  -d "grant_type=password" \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')
ok "token obtained (${#TOKEN} chars)"

# ---------------------------------------------------------------------------
# Walk the users array — shell out to python for JSON manipulation.
# ---------------------------------------------------------------------------

PAYLOADS=$(python3 - "$REALM_EXPORT" <<'PY'
import json, sys

with open(sys.argv[1]) as f:
    realm = json.load(f)

for u in realm.get("users", []):
    if u.get("username") in (None, "", "admin"):
        continue
    creds = u.get("credentials") or []
    password = ""
    for c in creds:
        if c.get("type") == "password" and c.get("value"):
            password = c["value"]
            break
    if not password:
        continue
    user_payload = {
        "username":      u["username"],
        "email":         u.get("email") or u["username"],
        "enabled":       u.get("enabled", True),
        "emailVerified": u.get("emailVerified", True),
        "firstName":     u.get("firstName") or "",
        "lastName":      u.get("lastName")  or "",
        "attributes":    u.get("attributes") or {},
    }
    print(u["username"])
    print(password)
    print(json.dumps(user_payload))
PY
)

if [[ -z "$PAYLOADS" ]]; then
  log "No seedable users in $REALM_EXPORT (beyond admin). Nothing to do."
  exit 0
fi

# Read triplets of lines: username / password / payload JSON.
while IFS= read -r USERNAME && IFS= read -r PASSWORD && IFS= read -r PAYLOAD; do
  log "user $USERNAME"

  create_code=$(curl -sS -o /tmp/kc-seed.out -w '%{http_code}' -X POST \
    "$KC_URL/admin/realms/$KC_REALM/users" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    --data "$PAYLOAD")

  case "$create_code" in
    201) ok "created" ;;
    409) skip "already exists" ;;
    *)
      echo "  UNEXPECTED HTTP $create_code:" >&2
      cat /tmp/kc-seed.out >&2; echo >&2
      exit 1
      ;;
  esac

  USER_ID=$(curl -sSf "$KC_URL/admin/realms/$KC_REALM/users?username=$USERNAME&exact=true" \
    -H "Authorization: Bearer $TOKEN" \
    | python3 -c 'import json,sys;u=json.load(sys.stdin);print(u[0]["id"] if u else "")')

  if [[ -z "$USER_ID" ]]; then
    echo "  could not resolve user id for $USERNAME" >&2
    exit 1
  fi

  reset_code=$(curl -sS -o /tmp/kc-seed.out -w '%{http_code}' -X PUT \
    "$KC_URL/admin/realms/$KC_REALM/users/$USER_ID/reset-password" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    --data "{\"type\":\"password\",\"value\":\"$PASSWORD\",\"temporary\":false}")

  case "$reset_code" in
    204) ok "password set" ;;
    *)
      echo "  UNEXPECTED reset HTTP $reset_code:" >&2
      cat /tmp/kc-seed.out >&2; echo >&2
      exit 1
      ;;
  esac
done <<< "$PAYLOADS"

log "Done."
