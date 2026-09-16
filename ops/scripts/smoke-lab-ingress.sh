#!/bin/sh
# Ingress smoke after Helm. Failure is a red job; it does not roll back the VM.
set -eu

BASE="${AGENTIUM_LAB_INGRESS_URL:?AGENTIUM_LAB_INGRESS_URL is required}"
BASE="${BASE%/}"

fail() { printf '%s\n' "$*" >&2; exit 1; }

check() {
  path="$1"
  expect="$2"
  url="${BASE}${path}"
  code="$(curl -sS -o /tmp/agentium-smoke.body -w '%{http_code}' "$url")"
  if [ "$code" != "$expect" ]; then
    fail "${path} expected ${expect}, got ${code}"
  fi
  printf '%s %s\n' "$path" "$code"
}

check /healthz 200
check /health/live 200
check /.env 404
