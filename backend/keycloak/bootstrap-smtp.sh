#!/usr/bin/env bash
# Inject SMTP secrets into the papai-org realm after import.
#
# The realm-export.json holds the non-sensitive SMTP settings
# (host, port, ssl, from, displayName). This script adds the
# authentication credentials at runtime so they never land in git.
#
# Required env vars (source /etc/agentium/smtp.env or similar):
#   SMTP_USER          e.g. noreply@datategy.net
#   SMTP_PASSWORD      the OVH mailbox password
#   KC_ADMIN           master-realm admin (e.g. tib-admin after rotation)
#   KC_ADMIN_PASSWORD  password for KC_ADMIN — store in secret manager
# Optional:
#   KC_URL          default http://localhost:8080/kc
#   KC_REALM        default papai-org
#
# Usage:
#   KC_ADMIN=... KC_ADMIN_PASSWORD=... \
#     SMTP_USER=... SMTP_PASSWORD=... ./bootstrap-smtp.sh
#
# The admin credentials are required (no admin/admin fallback) so a
# misconfigured env fails loudly instead of silently using the
# bootstrap defaults that should have been rotated away.

set -euo pipefail

: "${SMTP_USER:?SMTP_USER is required}"
: "${SMTP_PASSWORD:?SMTP_PASSWORD is required}"
: "${KC_ADMIN:?KC_ADMIN is required (master-realm admin username)}"
: "${KC_ADMIN_PASSWORD:?KC_ADMIN_PASSWORD is required}"

KC_URL="${KC_URL:-http://localhost:8080/kc}"
KC_REALM="${KC_REALM:-papai-org}"

echo "[bootstrap-smtp] Authenticating against ${KC_URL}"
TOKEN=$(curl -s -X POST "${KC_URL}/realms/master/protocol/openid-connect/token" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'grant_type=password' \
  -d 'client_id=admin-cli' \
  -d "username=${KC_ADMIN}" \
  --data-urlencode "password=${KC_ADMIN_PASSWORD}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

if [[ -z "$TOKEN" ]]; then
  echo "[bootstrap-smtp] Failed to obtain admin token" >&2
  exit 1
fi

echo "[bootstrap-smtp] Fetching current realm config for ${KC_REALM}"
REALM_FILE=$(mktemp)
trap 'rm -f "$REALM_FILE" "${REALM_FILE}.patched"' EXIT
curl -sf -H "Authorization: Bearer ${TOKEN}" "${KC_URL}/admin/realms/${KC_REALM}" -o "$REALM_FILE"

PATCHED_FILE="${REALM_FILE}.patched"
python3 - "$REALM_FILE" "$PATCHED_FILE" "$SMTP_USER" "$SMTP_PASSWORD" <<'PY'
import json, sys
src, dst, user, password = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
with open(src) as f:
    realm = json.load(f)
smtp = dict(realm.get("smtpServer") or {})
smtp["user"] = user
smtp["password"] = password
realm["smtpServer"] = smtp
with open(dst, "w") as f:
    json.dump(realm, f)
PY

echo "[bootstrap-smtp] Applying SMTP credentials"
curl -fsS -X PUT "${KC_URL}/admin/realms/${KC_REALM}" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H 'Content-Type: application/json' \
  --data-binary "@${PATCHED_FILE}"

echo "[bootstrap-smtp] Testing SMTP connection"
SMTP_BODY_FILE="${PATCHED_FILE}.smtp"
python3 - "$PATCHED_FILE" "$SMTP_BODY_FILE" <<'PY'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
with open(src) as f:
    realm = json.load(f)
with open(dst, "w") as f:
    json.dump(realm["smtpServer"], f)
PY
curl -fsS -o /dev/null -w "testSMTPConnection: HTTP %{http_code}\n" \
  -X POST "${KC_URL}/admin/realms/${KC_REALM}/testSMTPConnection" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H 'Content-Type: application/json' \
  --data-binary "@${SMTP_BODY_FILE}"
rm -f "$SMTP_BODY_FILE"

echo "[bootstrap-smtp] Done"
