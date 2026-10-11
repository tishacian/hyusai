#!/usr/bin/env bash
# Rotate the Keycloak master-realm admin password on the VM.
#
# Two-step strategy to avoid lockout:
#   1) Create a *new* admin user (role admin on master realm) with the
#      chosen password. Verify it can obtain an admin token.
#   2) Only after step 1 succeeds, update the password of the legacy
#      bootstrap `admin` user (or optionally disable it).
#
# Usage:
#   NEW_ADMIN_USER=ops-admin \
#   NEW_ADMIN_PASSWORD='...' \
#   ./rotate-keycloak-admin.sh [--disable-bootstrap]
#
# Optional:
#   KC_URL           default http://localhost:8080/kc
#   BOOT_ADMIN       default admin
#   BOOT_PASSWORD    default admin

set -euo pipefail

: "${NEW_ADMIN_USER:?NEW_ADMIN_USER is required}"
: "${NEW_ADMIN_PASSWORD:?NEW_ADMIN_PASSWORD is required}"

KC_URL="${KC_URL:-http://localhost:8080/kc}"
BOOT_ADMIN="${BOOT_ADMIN:-admin}"
BOOT_PASSWORD="${BOOT_PASSWORD:-admin}"
DISABLE_BOOTSTRAP="false"

for arg in "$@"; do
  case "$arg" in
    --disable-bootstrap) DISABLE_BOOTSTRAP="true" ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

echo "[rotate] Logging in as bootstrap admin (${BOOT_ADMIN})"
TOKEN=$(curl -sf -X POST "${KC_URL}/realms/master/protocol/openid-connect/token" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'grant_type=password' \
  -d 'client_id=admin-cli' \
  -d "username=${BOOT_ADMIN}" \
  --data-urlencode "password=${BOOT_PASSWORD}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

if [[ -z "$TOKEN" ]]; then
  echo "[rotate] Bootstrap admin login failed; aborting (cannot rotate without current admin creds)" >&2
  exit 1
fi

echo "[rotate] Step 1 — creating / locating user '${NEW_ADMIN_USER}' in master realm"
EXISTING=$(curl -sf -H "Authorization: Bearer ${TOKEN}" \
  "${KC_URL}/admin/realms/master/users?username=${NEW_ADMIN_USER}&exact=true" \
  | python3 -c 'import sys,json; u=json.load(sys.stdin); print(u[0]["id"] if u else "")')

if [[ -z "$EXISTING" ]]; then
  curl -sf -X POST "${KC_URL}/admin/realms/master/users" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"${NEW_ADMIN_USER}\",\"enabled\":true,\"emailVerified\":true}"
  EXISTING=$(curl -sf -H "Authorization: Bearer ${TOKEN}" \
    "${KC_URL}/admin/realms/master/users?username=${NEW_ADMIN_USER}&exact=true" \
    | python3 -c 'import sys,json; print(json.load(sys.stdin)[0]["id"])')
  echo "[rotate] Created user id=${EXISTING}"
else
  echo "[rotate] User already exists id=${EXISTING}"
fi

echo "[rotate] Setting password (temporary=false)"
PWD_BODY=$(python3 -c 'import json,sys; print(json.dumps({"type":"password","temporary":False,"value":sys.argv[1]}))' "$NEW_ADMIN_PASSWORD")
curl -sf -X PUT "${KC_URL}/admin/realms/master/users/${EXISTING}/reset-password" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H 'Content-Type: application/json' \
  -d "${PWD_BODY}"

echo "[rotate] Granting 'admin' role in master realm"
ADMIN_ROLE=$(curl -sf -H "Authorization: Bearer ${TOKEN}" \
  "${KC_URL}/admin/realms/master/roles/admin")
curl -sf -X POST "${KC_URL}/admin/realms/master/users/${EXISTING}/role-mappings/realm" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H 'Content-Type: application/json' \
  -d "[${ADMIN_ROLE}]"

echo "[rotate] Verifying new admin can obtain a token"
NEW_TOKEN=$(curl -sf -X POST "${KC_URL}/realms/master/protocol/openid-connect/token" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'grant_type=password' \
  -d 'client_id=admin-cli' \
  -d "username=${NEW_ADMIN_USER}" \
  --data-urlencode "password=${NEW_ADMIN_PASSWORD}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

if [[ -z "$NEW_TOKEN" ]]; then
  echo "[rotate] New admin login failed — NOT touching bootstrap user" >&2
  exit 1
fi
echo "[rotate] New admin works."

if [[ "$DISABLE_BOOTSTRAP" == "true" ]]; then
  echo "[rotate] Step 2 — disabling bootstrap user '${BOOT_ADMIN}' (with NEW admin token)"
  BOOT_ID=$(curl -sf -H "Authorization: Bearer ${NEW_TOKEN}" \
    "${KC_URL}/admin/realms/master/users?username=${BOOT_ADMIN}&exact=true" \
    | python3 -c 'import sys,json; u=json.load(sys.stdin); print(u[0]["id"] if u else "")')
  if [[ -n "$BOOT_ID" ]]; then
    curl -sf -X PUT "${KC_URL}/admin/realms/master/users/${BOOT_ID}" \
      -H "Authorization: Bearer ${NEW_TOKEN}" \
      -H 'Content-Type: application/json' \
      -d '{"enabled":false}'
    echo "[rotate] Bootstrap user disabled."
  else
    echo "[rotate] Bootstrap user '${BOOT_ADMIN}' not found — nothing to disable."
  fi
else
  echo "[rotate] Keeping bootstrap '${BOOT_ADMIN}' enabled. Re-run with --disable-bootstrap when you're ready."
fi

cat <<EOF

[rotate] Done. Remember to:
  - Store NEW_ADMIN_PASSWORD in your secret manager.
  - Update any script that referenced admin/admin. On this repo:
      * backend/keycloak/bootstrap-smtp.sh (KC_ADMIN / KC_ADMIN_PASSWORD)
      * backend/app/api/v1/endpoints/auth.py (if it uses admin-cli with hardcoded creds)
      * docker/test_env_files/keycloak.env (local dev only)
  - Rotate KC_BOOTSTRAP_ADMIN_PASSWORD in the container env if you plan
    to recreate the container (it only affects the first bootstrap —
    harmless on an already-populated realm, but no reason to keep 'admin').
EOF
