#!/usr/bin/env bash
# Daily raft snapshot of the Agentium OpenBao (AGENTIUM_OPENBAO=1).
#
#   agentium-openbao-snapshot.sh <runtime-env dir>
#
# Logs in with the `snapshot` AppRole written by agentium_openbao_bootstrap.py
# (policy: read sys/storage/raft/snapshot only), streams the snapshot into
# $AGENTIUM_OPENBAO_BACKUPS_PATH (default /srv/agentium-data/openbao-backups)
# as openbao-<UTC>.snap, mode 0600, and prunes snapshots older than
# $AGENTIUM_OPENBAO_BACKUP_RETAIN_DAYS (default 14). Credentials never reach
# argv or the logs. Suggested cron entry (root):
#
#   17 3 * * * /srv/agentium-data/worktrees/demo-agentic/scripts/agentium-openbao-snapshot.sh \
#     <deployment>/runtime-env >>/srv/agentium-data/openbao-backups/snapshot.log 2>&1
#
# Restore (stops serving secrets until done; same unseal key required, since
# the snapshot is sealed with the static key that wrote it):
#   1. docker cp <file>.snap agentium-openbao:/tmp/restore.snap
#   2. regenerate a root token from the recovery key (bao operator generate-root)
#   3. docker exec -e BAO_TOKEN=<root> agentium-openbao \
#        bao operator raft snapshot restore -force /tmp/restore.snap
#   4. revoke that root token, then `agentium-vm-deploy.sh openbao-status`.
set -euo pipefail

RUNTIME_ENV="${1:?usage: $0 <runtime-env dir>}"
BACKUPS="${AGENTIUM_OPENBAO_BACKUPS_PATH:-/srv/agentium-data/openbao-backups}"
RETAIN_DAYS="${AGENTIUM_OPENBAO_BACKUP_RETAIN_DAYS:-14}"
CONTAINER=agentium-openbao
CREDS="$RUNTIME_ENV/openbao-snapshot.env"

fail() {
	printf '%s\n' "$*" >&2
	exit 1
}

case "$RETAIN_DAYS" in '' | *[!0-9]*) fail "AGENTIUM_OPENBAO_BACKUP_RETAIN_DAYS must be an integer" ;; esac
[[ -d "$BACKUPS" && ! -L "$BACKUPS" ]] || fail "$BACKUPS must be a pre-provisioned real directory"
[[ -f "$CREDS" ]] || fail "$CREDS is missing (run agentium_openbao_bootstrap.py first)"

value() { /usr/bin/sed -n "s/^$1=//p" "$CREDS" | /usr/bin/head -n1; }
ROLE_ID="$(value OPENBAO_ROLE_ID)"
SECRET_ID="$(value OPENBAO_SECRET_ID)"
[[ -n "$ROLE_ID" && -n "$SECRET_ID" ]] || fail "$CREDS lacks OPENBAO_ROLE_ID/OPENBAO_SECRET_ID"

IP="$(docker inspect "$CONTAINER" --format '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' | /usr/bin/awk '{print $1}')"
[[ -n "$IP" ]] || fail "$CONTAINER has no network address (is it running?)"
ADDR="http://$IP:8200"

umask 077
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

printf '{"role_id":"%s","secret_id":"%s"}' "$ROLE_ID" "$SECRET_ID" |
	curl -fsS --max-time 15 -X POST --data @- "$ADDR/v1/auth/approle/login" >"$WORK/login.json" ||
	fail "AppRole login failed"
TOKEN="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["auth"]["client_token"])' "$WORK/login.json")"
printf 'X-Vault-Token: %s\n' "$TOKEN" >"$WORK/headers"
rm -f "$WORK/login.json"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TARGET="$BACKUPS/openbao-$STAMP.snap"
curl -fsS --max-time 300 -H "@$WORK/headers" "$ADDR/v1/sys/storage/raft/snapshot" -o "$TARGET.partial" ||
	{ rm -f "$TARGET.partial"; fail "snapshot download failed"; }
[[ -s "$TARGET.partial" ]] || { rm -f "$TARGET.partial"; fail "snapshot is empty"; }
chmod 0600 "$TARGET.partial"
mv "$TARGET.partial" "$TARGET"
curl -fsS --max-time 15 -X POST -H "@$WORK/headers" "$ADDR/v1/auth/token/revoke-self" >/dev/null || true

find "$BACKUPS" -maxdepth 1 -type f -name 'openbao-*.snap' -mtime +"$RETAIN_DAYS" -delete
printf 'openbao snapshot written: %s\n' "$TARGET"
