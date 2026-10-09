#!/usr/bin/env bash
# Versioned VM deployment path — supersedes the ad-hoc /root/release-b-deploy.sh
# and the untracked /root/release-b-{images,restart,workers}.yml overlays.
#
# Same invocation shape as the 30/07 release-b landing: Release A base compose
# from the build worktree, frozen env, opened overlay — plus the single
# versioned runtime overlay (restart policies + the agentium-sftp digest pin).
# Since 10/08, `up` also recreates agentium-p4-maintenance (outbox drainer,
# rides AGENTIUM_IMAGE_TAG) and agentium-beat (scheduler_tick source; naming
# the service activates its `beat` profile — the worker itself keeps
# AGENTIUM_CELERY_BEAT=0 below so exactly one beat runs).  Image tags and
# worker count flow through the environment instead of a hardcoded overlay:
#
#   export AGENTIUM_IMAGE_TAG="${SHA:0:12}"   # immutable <sha12>, or demo-agentic
#   export AGENTIUM_BACKEND_WORKERS=8         # default below
#
# Rollback to any iteration: AGENTIUM_IMAGE_TAG=<previous sha12>, then `up`.
set -euo pipefail

readonly D=/srv/agentium-data/release-a-deployments/release-a-2026-07-27-omnirag-demo
readonly R=/srv/agentium-data/worktrees/demo-agentic
readonly W="$R/docker"
readonly ENV_HELPER="$R/scripts/agentium_runtime_env_bundle.py"
readonly DATA_ROOT=/srv/agentium-data
readonly EXPECTED_DATA_SOURCE=/dev/sdb
readonly OBJECT_STORE_ROOT="$DATA_ROOT/object_store"
readonly RECIPE_ENVS_ROOT="$DATA_ROOT/recipe_envs"
readonly ML_DEEP_MODELS_ROOT="$DATA_ROOT/ml-deep-models"
readonly SECURE_DEPOSIT_ROOT=/home/ubuntu/omnirag/backend/data/secure_deposit
readonly EXPECTED_SECURE_SOURCE=/dev/sdc
readonly FAISS_ROOT=/home/ubuntu/omnirag/backend/faiss_db
readonly EXPECTED_ROOT_SOURCE=/dev/sda1
readonly DOCKER_SOCKET=unix:///var/run/docker.sock
readonly DOCKER_VOLUME_ROOT=/var/lib/docker/volumes
readonly COMPOSE_CLEAN_HOME=/home/ubuntu
readonly COMPOSE_CLEAN_PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

fail() {
  printf '%s\n' "$*" >&2
  exit 1
}

# Fail closed on an unset or malformed tag: the compose default (`local`) points
# the backend at the stale pre-release-b image.
TAG="${AGENTIUM_IMAGE_TAG:-}"
case "$TAG" in
  demo-agentic|[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
  *) echo "AGENTIUM_IMAGE_TAG must be 'demo-agentic' or a 12-hex SHA prefix" >&2; exit 2 ;;
esac

WORKERS="${AGENTIUM_BACKEND_WORKERS:-8}"
case "$WORKERS" in
  ''|*[!0-9]*) fail "AGENTIUM_BACKEND_WORKERS must be an integer between 1 and 64" ;;
esac
[ "$WORKERS" -ge 1 ] && [ "$WORKERS" -le 64 ] ||
  fail "AGENTIUM_BACKEND_WORKERS must be an integer between 1 and 64"

# Forecasting workers (Compose profile ml-ts) are opt-in per deployment.
# AGENTIUM_ML_TS=1 renders and storage-checks them, and `up` recreates them
# from the same tag as the rest of the stack; `ml-ts-stop` takes them down,
# which is their rollback. Left at 0, nothing about them changes.
ML_TS="${AGENTIUM_ML_TS:-0}"
case "$ML_TS" in
  0|1) ;;
  *) fail "AGENTIUM_ML_TS must be 0 or 1" ;;
esac
ML_TS_ALL=(agentium-worker-ml-ts agentium-worker-ml-ts-serve)
ML_TS_PROFILE=()
ML_TS_SERVICES=()
if [ "$ML_TS" = 1 ]; then
  ML_TS_PROFILE=(--profile ml-ts)
  ML_TS_SERVICES=("${ML_TS_ALL[@]}")
fi

# Deep-model workers (Compose profile ml-deep), same opt-in shape. They also
# mount the provisioned weights read-only from AGENTIUM_ML_DEEP_MODELS_PATH.
ML_DEEP="${AGENTIUM_ML_DEEP:-0}"
case "$ML_DEEP" in
  0|1) ;;
  *) fail "AGENTIUM_ML_DEEP must be 0 or 1" ;;
esac
ML_DEEP_ALL=(agentium-worker-ml-deep agentium-worker-ml-deep-serve)
ML_DEEP_PROFILE=()
ML_DEEP_SERVICES=()
if [ "$ML_DEEP" = 1 ]; then
  ML_DEEP_PROFILE=(--profile ml-deep)
  ML_DEEP_SERVICES=("${ML_DEEP_ALL[@]}")
fi

clean_exec() {
  /usr/bin/env -i \
    HOME="$COMPOSE_CLEAN_HOME" \
    PATH="$COMPOSE_CLEAN_PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    "$@"
}

readonly_docker() {
  clean_exec docker --host "$DOCKER_SOCKET" "$@"
}

# The admin Qdrant key lives in the running container; the backend needs it or
# the chat comes back read-only. It is read through the scrubbed Docker client
# and never logged.
ADMIN=$(readonly_docker inspect qdrant --format "{{range .Config.Env}}{{println .}}{{end}}" | /usr/bin/sed -n "s/^QDRANT__SERVICE__API_KEY=//p")
[ -n "$ADMIN" ] || fail "Qdrant admin key not found"
readonly ADMIN

compose() {
  /usr/bin/env -i \
    HOME="$COMPOSE_CLEAN_HOME" \
    PATH="$COMPOSE_CLEAN_PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    COMPOSE_PROJECT_NAME=agentium \
    AGENTIUM_IMAGE_TAG="$TAG" \
    AGENTIUM_QDRANT_EFFECTIVE_API_KEY="$ADMIN" \
    AGENTIUM_BACKEND_WORKERS="$WORKERS" \
    AGENTIUM_CELERY_BEAT=0 \
    AGENTIUM_STARTUP_RECONCILIATION=disabled \
    docker --host "$DOCKER_SOCKET" compose -p agentium \
    --env-file "$D/runtime-env/compose.effective.env" \
    -f "$W/compose.agentium.yml" \
    -f "$D/compose.agentium.opened.yml" \
    -f "$W/compose.agentium.vm-runtime.yml" \
    "$@"
}

assert_data_device() {
  local source target
  source="$(clean_exec findmnt -n -o SOURCE --target "$DATA_ROOT")"
  target="$(clean_exec findmnt -n -o TARGET --target "$DATA_ROOT")"
  [[ "$source" == "$EXPECTED_DATA_SOURCE" && "$target" == "$DATA_ROOT" ]] ||
    fail "$DATA_ROOT must be the exact $EXPECTED_DATA_SOURCE mountpoint"
}

assert_protected_data_path() {
  local path="$1"
  local canonical source target data_device path_device
  [[ -d "$path" && ! -L "$path" ]] ||
    fail "$path must be a real directory on $EXPECTED_DATA_SOURCE"
  canonical="$(clean_exec readlink -e -- "$path")"
  [[ "$canonical" == "$path" ]] ||
    fail "$path must be canonical and must not traverse a symlink"
  source="$(clean_exec findmnt -n -o SOURCE --target "$path")"
  target="$(clean_exec findmnt -n -o TARGET --target "$path")"
  data_device="$(clean_exec stat -c %d -- "$DATA_ROOT")"
  path_device="$(clean_exec stat -c %d -- "$path")"
  [[ "$source" == "$EXPECTED_DATA_SOURCE" && "$target" == "$DATA_ROOT" && "$path_device" == "$data_device" ]] ||
    fail "$path must resolve directly through $DATA_ROOT on $EXPECTED_DATA_SOURCE"
}

assert_exact_backing_path() {
  local path="$1"
  local expected_source="$2"
  local expected_mountpoint="$3"
  local canonical source target mount_device path_device
  [[ -d "$path" && ! -L "$path" ]] ||
    fail "$path must be a real directory on $expected_source"
  canonical="$(clean_exec readlink -e -- "$path")"
  [[ "$canonical" == "$path" ]] ||
    fail "$path must be canonical and must not traverse a symlink"
  source="$(clean_exec findmnt -n -o SOURCE --target "$path")"
  target="$(clean_exec findmnt -n -o TARGET --target "$path")"
  mount_device="$(clean_exec stat -c %d -- "$expected_mountpoint")"
  path_device="$(clean_exec stat -c %d -- "$path")"
  [[ "$source" == "$expected_source" && "$target" == "$expected_mountpoint" && "$path_device" == "$mount_device" ]] ||
    fail "$path must resolve directly through $expected_mountpoint on $expected_source"
}

assert_volume_mountpoint() {
  local volume_name="$1"
  local expected_fs_root="$2"
  local mountpoint="$DOCKER_VOLUME_ROOT/$volume_name/_data"
  local expected_source="${EXPECTED_DATA_SOURCE}[${expected_fs_root}]"
  local canonical source target data_device mount_device
  [[ -d "$mountpoint" && ! -L "$mountpoint" ]] ||
    fail "$volume_name Docker mountpoint must be a real directory"
  canonical="$(clean_exec readlink -e -- "$mountpoint")"
  [[ "$canonical" == "$mountpoint" ]] ||
    fail "$volume_name Docker mountpoint must be canonical"
  source="$(clean_exec findmnt -n -o SOURCE --target "$mountpoint")"
  target="$(clean_exec findmnt -n -o TARGET --target "$mountpoint")"
  data_device="$(clean_exec stat -c %d -- "$DATA_ROOT")"
  mount_device="$(clean_exec stat -c %d -- "$mountpoint")"
  [[ "$source" == "$expected_source" && "$target" == "$mountpoint" && "$mount_device" == "$data_device" ]] ||
    fail "$volume_name Docker mountpoint is not the expected $EXPECTED_DATA_SOURCE bind"
}

storage_check() {
  [[ -x "$ENV_HELPER" ]] || fail "Runtime environment helper is unavailable"
  clean_exec python3 "$ENV_HELPER" vm-storage-env-check \
    --env-file "$D/runtime-env/compose.effective.env"
  assert_data_device
  assert_protected_data_path "$DATA_ROOT/minio"
  assert_protected_data_path "$DATA_ROOT/qdrant"
  assert_protected_data_path "$DATA_ROOT/qdrant-snapshots"
  assert_protected_data_path "$OBJECT_STORE_ROOT"
  assert_protected_data_path "$RECIPE_ENVS_ROOT"
  assert_protected_data_path "$ML_DEEP_MODELS_ROOT"
  assert_exact_backing_path \
    "$SECURE_DEPOSIT_ROOT" "$EXPECTED_SECURE_SOURCE" "$SECURE_DEPOSIT_ROOT"
  assert_exact_backing_path "$FAISS_ROOT" "$EXPECTED_ROOT_SOURCE" /
  compose --profile infra --profile tools --profile sftp "${ML_TS_PROFILE[@]}" "${ML_DEEP_PROFILE[@]}" config --format json |
    clean_exec python3 "$ENV_HELPER" vm-storage-compose-check
  readonly_docker volume inspect agentium_minio_block |
    clean_exec python3 "$ENV_HELPER" vm-storage-volume-check \
      --name agentium_minio_block
  assert_volume_mountpoint agentium_minio_block /minio
  readonly_docker volume inspect agentium_qdrant_block |
    clean_exec python3 "$ENV_HELPER" vm-storage-volume-check \
      --name agentium_qdrant_block
  assert_volume_mountpoint agentium_qdrant_block /qdrant
  local recipe_containers=()
  if readonly_docker inspect --type container agentium-worker-recipes >/dev/null 2>&1; then
    recipe_containers=(agentium-worker-recipes)
  fi
  # Forecasting and deep workers mount the object store: checked wherever they
  # exist, including a host that has since switched their flag back to 0.
  local ml_ts_containers=() container
  for container in "${ML_TS_ALL[@]}" "${ML_DEEP_ALL[@]}"; do
    if readonly_docker inspect --type container "$container" >/dev/null 2>&1; then
      ml_ts_containers+=("$container")
    fi
  done
  readonly_docker inspect --type container "${recipe_containers[@]}" "${ml_ts_containers[@]}" \
    agentium-minio qdrant agentium-backend agentium-worker-cpu \
    agentium-p4-maintenance agentium-sftp |
    clean_exec python3 "$ENV_HELPER" vm-storage-runtime-check
  printf 'storage-check passed: block stores and application binds remain on their protected devices\n'
}

# The canonical Skills/Capabilities catalog. The API seeds it at boot only when
# startup reconciliation is enabled, which a transactional deployment keeps
# off; a release that adds a Skill reconciles it here, in the one-off migrate
# container (the release's image, stores read-only). `check` is read-only and
# exits 3 when the catalog is behind the code.
catalog() {
  compose run --rm --no-deps --pull never agentium-migrate python -m app.cli.reconcile_catalog "$@"
}

case "${1:-}" in
  images)        compose "${ML_TS_PROFILE[@]}" "${ML_DEEP_PROFILE[@]}" config --images ;;
  storage-check) storage_check ;;
  migrate)       storage_check; compose run --rm --no-deps --pull never agentium-migrate ;;
  up)            storage_check; compose up -d --no-build --no-deps --pull never agentium-worker-recipes agentium-backend agentium-worker-cpu agentium-frontend agentium-p4-maintenance agentium-beat "${ML_TS_SERVICES[@]}" "${ML_DEEP_SERVICES[@]}"
                 # Said at the end of every switch, never blocking it: new code
                 # whose Skills the database lacks is a feature nobody can see.
                 catalog >/dev/null || printf '%s\n' "WARNING: catalog-check did not pass (verdict above); to bring the Skills catalog to this release: $0 catalog-apply" >&2 ;;
  catalog-check) catalog ;;
  catalog-apply) storage_check; catalog --apply ;;
  ml-ts-stop)    compose --profile ml-ts rm --stop --force "${ML_TS_ALL[@]}" ;;
  ml-deep-stop)  compose --profile ml-deep rm --stop --force "${ML_DEEP_ALL[@]}" ;;
  ps)            compose "${ML_TS_PROFILE[@]}" "${ML_DEEP_PROFILE[@]}" ps ;;
  *)             echo "usage: $0 {images|storage-check|migrate|up|catalog-check|catalog-apply|ml-ts-stop|ml-deep-stop|ps}" >&2; exit 2 ;;
esac
