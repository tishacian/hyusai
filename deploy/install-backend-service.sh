#!/usr/bin/env bash
# Install (or reinstall) the agentium-backend systemd unit and take over the
# currently running uvicorn processes safely.
#
# Run as: sudo ./install-backend-service.sh
#
# Idempotent: copies the unit, reloads systemd, disables any ad-hoc
# uvicorn processes, then enables+starts the service.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
UNIT_SRC="${HERE}/agentium-backend.service"
UNIT_DST="/etc/systemd/system/agentium-backend.service"

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root: sudo $0" >&2
  exit 1
fi

echo "[install] Copying unit to ${UNIT_DST}"
install -m 0644 "${UNIT_SRC}" "${UNIT_DST}"

echo "[install] systemctl daemon-reload"
systemctl daemon-reload

# Stop any ad-hoc uvicorn master/workers (systemd won't know about them).
ORPHANS=$(pgrep -f "uvicorn app.main:app" || true)
if [[ -n "${ORPHANS}" ]]; then
  echo "[install] Killing orphan uvicorn processes: ${ORPHANS}"
  # shellcheck disable=SC2086
  kill -TERM ${ORPHANS} || true
  sleep 3
  STILL=$(pgrep -f "uvicorn app.main:app" || true)
  if [[ -n "${STILL}" ]]; then
    echo "[install] Force killing: ${STILL}"
    # shellcheck disable=SC2086
    kill -9 ${STILL} || true
    sleep 1
  fi
fi

echo "[install] Enabling + starting agentium-backend"
systemctl enable agentium-backend.service
systemctl restart agentium-backend.service

sleep 4
systemctl --no-pager --full status agentium-backend.service | head -n 25
echo
echo "[install] Smoke check /health"
curl -s -o /dev/null -w "health HTTP %{http_code}\n" http://127.0.0.1:8000/health || true
