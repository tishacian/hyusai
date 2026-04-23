#!/usr/bin/env bash
# Recreate the agentium-kc container so it mounts the Agentium theme and
# the realm-export.json for future imports. Preserves network, ports,
# env, and DB connection as currently configured on the VM.
#
# Requires the theme tree to already exist at:
#   /home/ubuntu/omnirag/backend/keycloak/themes/agentium
# and the realm export at:
#   /home/ubuntu/omnirag/backend/keycloak/realm-export.json
#
# Run: sudo ./redeploy-keycloak.sh

set -euo pipefail

CONTAINER="${CONTAINER:-agentium-kc}"
IMAGE="${IMAGE:-quay.io/keycloak/keycloak:26.1.4}"
NET="${NET:-agentium-net}"
REPO_ROOT="${REPO_ROOT:-/home/ubuntu/omnirag}"
THEME_DIR="${REPO_ROOT}/backend/keycloak/themes/agentium"
REALM_EXPORT="${REPO_ROOT}/backend/keycloak/realm-export.json"

if [[ ! -d "${THEME_DIR}" ]]; then
  echo "Theme directory missing: ${THEME_DIR}" >&2
  exit 1
fi

echo "[redeploy-kc] Capturing current env from ${CONTAINER}"
mapfile -t ENV_LINES < <(docker inspect "${CONTAINER}" \
  --format '{{range .Config.Env}}{{.}}{{"\n"}}{{end}}' \
  | grep -E '^(KC_|KEYCLOAK_|LANG=)' || true)

if [[ ${#ENV_LINES[@]} -eq 0 ]]; then
  echo "[redeploy-kc] Could not capture env from ${CONTAINER} — aborting" >&2
  exit 1
fi

ENV_ARGS=()
for e in "${ENV_LINES[@]}"; do
  ENV_ARGS+=( -e "$e" )
done

echo "[redeploy-kc] Stopping + removing ${CONTAINER}"
docker stop "${CONTAINER}" >/dev/null 2>&1 || true
docker rm   "${CONTAINER}" >/dev/null 2>&1 || true

echo "[redeploy-kc] Starting ${CONTAINER} with theme mount"
docker run -d \
  --name "${CONTAINER}" \
  --network "${NET}" \
  -p 8080:8080 \
  --restart unless-stopped \
  "${ENV_ARGS[@]}" \
  -v "${THEME_DIR}:/opt/keycloak/themes/agentium:ro" \
  -v "${REALM_EXPORT}:/opt/keycloak/data/import/realm.json:ro" \
  "${IMAGE}" \
  start-dev

echo "[redeploy-kc] Waiting for health"
for i in {1..40}; do
  if curl -sf http://localhost:8080/kc/health/ready >/dev/null 2>&1; then
    echo "[redeploy-kc] Keycloak ready after ${i}s"
    exit 0
  fi
  sleep 2
done

echo "[redeploy-kc] Keycloak did not become ready in time" >&2
docker logs --tail 60 "${CONTAINER}"
exit 1
