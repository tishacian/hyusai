#!/usr/bin/env bash
# Opt-in bench batch. Never source production env files or start provider services.
set -euo pipefail
: "${AGENTIUM_CONNECTOR_RUNNER_IMAGE:?Use the candidate connector image pinned by digest or local image ID}"
: "${CONNECTOR_CERT_CONFIG_DIR:?Private, operator-owned bench configs and golden Parquet files}"
: "${CONNECTOR_CERT_REPORT_DIR:?Dedicated writable report directory}"
: "${CONNECTOR_CERT_NETWORK:?Existing isolated bench Docker network}"
[[ "$AGENTIUM_CONNECTOR_RUNNER_IMAGE" =~ (^sha256:|@sha256:)[0-9a-f]{64}$ ]] || { echo 'CONNECTOR_IMAGE_DIGEST_REQUIRED' >&2; exit 2; }
[[ "$CONNECTOR_CERT_CONFIG_DIR" = /* && "$CONNECTOR_CERT_REPORT_DIR" = /* && "$CONNECTOR_CERT_CONFIG_DIR" != / && "$CONNECTOR_CERT_REPORT_DIR" != / ]] || { echo 'CONNECTOR_BENCH_PATH_INVALID' >&2; exit 2; }
[[ -d "$CONNECTOR_CERT_CONFIG_DIR" && -d "$CONNECTOR_CERT_REPORT_DIR" ]] || { echo 'CONNECTOR_BENCH_DIRECTORY_REQUIRED' >&2; exit 2; }
CONNECTOR_CERT_CONFIG_DIR=$(realpath "$CONNECTOR_CERT_CONFIG_DIR")
CONNECTOR_CERT_REPORT_DIR=$(realpath "$CONNECTOR_CERT_REPORT_DIR")
[[ "$CONNECTOR_CERT_CONFIG_DIR" != "$CONNECTOR_CERT_REPORT_DIR" && "$CONNECTOR_CERT_REPORT_DIR" != "$CONNECTOR_CERT_CONFIG_DIR/"* && "$CONNECTOR_CERT_CONFIG_DIR" != "$CONNECTOR_CERT_REPORT_DIR/"* ]] || { echo 'CONNECTOR_BENCH_PATH_OVERLAP' >&2; exit 2; }
# No container sees the Docker socket, application env, production volumes or
# a host port. Configured credentials are limited to disposable bench targets.
revision=$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$AGENTIUM_CONNECTOR_RUNNER_IMAGE")
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || { echo 'CONNECTOR_IMAGE_REVISION_REQUIRED' >&2; exit 2; }
network=$(docker network inspect --format '{{.Driver}} {{index .Labels "io.agentium.purpose"}}' "$CONNECTOR_CERT_NETWORK")
[[ "$network" == 'bridge connector-certification' ]] || { echo 'CONNECTOR_ISOLATED_NETWORK_REQUIRED' >&2; exit 2; }
running=''
cleanup() { if [[ -n "$running" ]]; then docker rm -f "$running" >/dev/null 2>&1 || true; fi; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
shopt -s nullglob
configs=("$CONNECTOR_CERT_CONFIG_DIR"/*.json)
((${#configs[@]} > 0)) || { echo 'CONNECTOR_BENCH_CONFIG_REQUIRED' >&2; exit 2; }
result=0
for config in "${configs[@]}"; do
  name=$(basename "$config" .json)
  [[ "$name" =~ ^[A-Za-z0-9_-]+$ ]] || { echo 'CONNECTOR_BENCH_NAME_INVALID' >&2; exit 2; }
  # Check the operator's metadata against the exact immutable image selected.
  # A digest is never copied from an unrelated run, and no secret is printed.
  python3 - "$config" "$revision" "${AGENTIUM_CONNECTOR_RUNNER_IMAGE##*sha256:}" <<'PY' || exit 2
import json
import os
import stat
import sys

try:
    descriptor = os.open(sys.argv[1], os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor) as handle:
        mode = os.fstat(handle.fileno())
        if not stat.S_ISREG(mode.st_mode) or stat.S_IMODE(mode.st_mode) != 0o600 or mode.st_uid != os.getuid() or mode.st_size > 65536:
            raise ValueError
        config = json.load(handle)
    if config.get("source_revision") != sys.argv[2] or config.get("runner_image_sha256") != sys.argv[3]:
        raise ValueError
except Exception:
    print("CONNECTOR_BENCH_IDENTITY_OR_PRIVATE_CONFIG_INVALID", file=sys.stderr)
    sys.exit(2)
PY
  destination="$name-$(date -u +%Y%m%dT%H%M%SZ)-$RANDOM"
  running="agentium-cert-$$-$RANDOM"
  docker run --rm --pull=never --name "$running" --network "$CONNECTOR_CERT_NETWORK" --cpus=1 --memory=2g \
    --read-only --cap-drop=ALL --security-opt=no-new-privileges \
    --user "$(id -u):$(id -g)" --tmpfs /tmp:rw,noexec,nosuid,size=536870912 \
    --mount "type=bind,src=$CONNECTOR_CERT_CONFIG_DIR,dst=/bench/config,readonly" \
    --mount "type=bind,src=$CONNECTOR_CERT_REPORT_DIR,dst=/bench/reports" \
    --workdir /app/backend --entrypoint python \
    "$AGENTIUM_CONNECTOR_RUNNER_IMAGE" -m app.tests.connectors.kit.live \
    --config "/bench/config/$name.json" --reports "/bench/reports/$destination" || result=2
  cleanup
  running=''
done
exit "$result"
