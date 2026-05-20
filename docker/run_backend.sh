#!/bin/sh
set -eu

WORKERS="${AGENTIUM_BACKEND_WORKERS:-3}"
KEEP_ALIVE="${AGENTIUM_BACKEND_TIMEOUT_KEEP_ALIVE:-5}"

exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --proxy-headers \
  --forwarded-allow-ips='*' \
  --workers "$WORKERS" \
  --timeout-keep-alive "$KEEP_ALIVE"
