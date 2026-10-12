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
# Every `migrate` and `up` is recorded in $JOURNAL (tag, previous tag, verified
# revision, database dump): `journal` prints it, and its previous_tag column is
# the rollback target.
#
#   AGENTIUM_RUNTIME_ENV_DIR   frozen env bundle (default: the one derived
#                              from Release A for the 2026-10-12 storage move)
#   AGENTIUM_GATE=1            close the public maintenance gate around
#                              `migrate` and `up`; it stays closed on failure
set -euo pipefail

fail() {
	printf '%s\n' "$*" >&2
	exit 1
}

readonly DATA_ROOT=/srv/agentium-data
readonly DEFAULT_RUNTIME_ENV_DIR="$DATA_ROOT/runtime-env/2026-10-12"

runtime_env_dir() {
	local dir="${AGENTIUM_RUNTIME_ENV_DIR:-$DEFAULT_RUNTIME_ENV_DIR}"
	[[ "$dir" == "$DATA_ROOT"/?* && "$dir" != *..* && "$dir" != *//* && "$dir" != */ ]] ||
		fail "AGENTIUM_RUNTIME_ENV_DIR must be a directory under $DATA_ROOT"
	printf '%s\n' "$dir"
}

D="$(runtime_env_dir)"
readonly D
readonly R=/srv/agentium-data/worktrees/demo-agentic
readonly W="$R/docker"
readonly ENV_HELPER="$R/scripts/agentium_runtime_env_bundle.py"
readonly EXPECTED_DATA_SOURCE=/dev/sdb
readonly OBJECT_STORE_ROOT="$DATA_ROOT/object_store"
readonly RECIPE_ENVS_ROOT="$DATA_ROOT/recipe_envs"
readonly ML_DEEP_MODELS_ROOT="$DATA_ROOT/ml-deep-models"
readonly HUB_CACHE_ROOT="$DATA_ROOT/hub-cache"
readonly HUB_BUNDLES_ROOT="$DATA_ROOT/hub-bundles"
readonly HUB_BUNDLE_KEYS_ROOT="$DATA_ROOT/hf-bundle-keys"
readonly OPENBAO_DATA_ROOT="$DATA_ROOT/openbao"
readonly OPENBAO_BACKUPS_ROOT="$DATA_ROOT/openbao-backups"
readonly OPENBAO_BOOTSTRAP="$R/scripts/agentium_openbao_bootstrap.py"
readonly SECURE_DEPOSIT_ROOT=/srv/agentium-secure-deposit
readonly EXPECTED_SECURE_SOURCE=/dev/sdc
readonly FAISS_ROOT="$DATA_ROOT/faiss_db"
readonly DOCKER_SOCKET=unix:///var/run/docker.sock
readonly DOCKER_VOLUME_ROOT=/var/lib/docker/volumes
readonly COMPOSE_CLEAN_HOME=/home/ubuntu
readonly COMPOSE_CLEAN_PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
readonly DEPLOYMENTS_ROOT="$DATA_ROOT/deployments"
readonly JOURNAL="$DEPLOYMENTS_ROOT/journal.tsv"
readonly MAINTENANCE_GATE="$R/scripts/agentium-maintenance-gate.sh"
readonly BUILD_INFO_ATTEMPTS="${AGENTIUM_BUILD_INFO_ATTEMPTS:-30}"

# Fail closed on an unset or malformed tag: the compose default (`local`) points
# the backend at the stale pre-release-b image.
TAG="${AGENTIUM_IMAGE_TAG:-}"
case "$TAG" in
demo-agentic | [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
*)
	echo "AGENTIUM_IMAGE_TAG must be 'demo-agentic' or a 12-hex SHA prefix" >&2
	exit 2
	;;
esac

WORKERS="${AGENTIUM_BACKEND_WORKERS:-8}"
case "$WORKERS" in
'' | *[!0-9]*) fail "AGENTIUM_BACKEND_WORKERS must be an integer between 1 and 64" ;;
esac
[ "$WORKERS" -ge 1 ] && [ "$WORKERS" -le 64 ] ||
	fail "AGENTIUM_BACKEND_WORKERS must be an integer between 1 and 64"

# Forecasting workers (Compose profile ml-ts) are opt-in per deployment.
# AGENTIUM_ML_TS=1 renders and storage-checks them, and `up` recreates them
# from the same tag as the rest of the stack; `ml-ts-stop` takes them down,
# which is their rollback. Left at 0, nothing about them changes.
ML_TS="${AGENTIUM_ML_TS:-0}"
case "$ML_TS" in
0 | 1) ;;
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
0 | 1) ;;
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

# Hub acquisition is explicit opt-in; the overlay also mounts a read-only
# cache into inference services and a separate retained bundle staging area.
HUGGINGFACE="${AGENTIUM_HUGGINGFACE:-0}"
case "$HUGGINGFACE" in
0 | 1) ;;
*) fail "AGENTIUM_HUGGINGFACE must be 0 or 1" ;;
esac
HUGGINGFACE_PROFILE=()
HUGGINGFACE_SERVICES=()
HUGGINGFACE_OVERLAY=()
if [ "$HUGGINGFACE" = 1 ]; then
	HUGGINGFACE_PROFILE=(--profile huggingface)
	HUGGINGFACE_SERVICES=(agentium-hub-fetch)
	HUGGINGFACE_OVERLAY=(-f "$W/compose.agentium.huggingface.yml")
fi

# OpenBao secret backend, same opt-in shape. The overlay hands each client its
# own AppRole file from runtime-env (written by agentium_openbao_bootstrap.py);
# the db backend stays the default whatever this flag says.
OPENBAO="${AGENTIUM_OPENBAO:-0}"
case "$OPENBAO" in
0 | 1) ;;
*) fail "AGENTIUM_OPENBAO must be 0 or 1" ;;
esac
OPENBAO_PROFILE=()
OPENBAO_SERVICES=()
OPENBAO_OVERLAY=()
OPENBAO_ENV=()
if [ "$OPENBAO" = 1 ]; then
	OPENBAO_PROFILE=(--profile openbao)
	OPENBAO_SERVICES=(agentium-openbao)
	OPENBAO_OVERLAY=(-f "$W/compose.agentium.openbao.yml")
	[ "$HUGGINGFACE" = 1 ] && OPENBAO_OVERLAY+=(-f "$W/compose.agentium.openbao-huggingface.yml")
	OPENBAO_ENV=(
		AGENTIUM_OPENBAO_DATA_PATH="$OPENBAO_DATA_ROOT"
		AGENTIUM_OPENBAO_UNSEAL_KEY_FILE="$D/runtime-env/openbao-unseal.key"
		AGENTIUM_OPENBAO_BACKEND_ENV_FILE="$D/runtime-env/openbao-backend.env"
		AGENTIUM_OPENBAO_WORKER_ENV_FILE="$D/runtime-env/openbao-worker.env"
		AGENTIUM_OPENBAO_HUB_ENV_FILE="$D/runtime-env/openbao-hub-fetch.env"
	)
fi

GATE="${AGENTIUM_GATE:-0}"
case "$GATE" in
0 | 1) ;;
*) fail "AGENTIUM_GATE must be 0 or 1" ;;
esac

readonly_docker() {
	clean_exec docker --host "$DOCKER_SOCKET" "$@"
}

# The admin Qdrant key lives in the running container; the backend needs it or
# the chat comes back read-only. It is read through the scrubbed Docker client
# and never logged.
ADMIN=$(readonly_docker inspect qdrant --format "{{range .Config.Env}}{{println .}}{{end}}" | /usr/bin/sed -n "s/^QDRANT__SERVICE__API_KEY=//p")
[ -n "$ADMIN" ] || fail "Qdrant admin key not found"
readonly ADMIN

# ${A[@]+"${A[@]}"}: bash 3.2 (macOS, where the contract tests run) treats an
# empty array as unbound under set -u.
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
		${OPENBAO_ENV[@]+"${OPENBAO_ENV[@]}"} \
		docker --host "$DOCKER_SOCKET" compose -p agentium \
		--env-file "$D/runtime-env/compose.effective.env" \
		-f "$W/compose.agentium.yml" \
		-f "$D/compose.agentium.opened.yml" \
		-f "$W/compose.agentium.vm-runtime.yml" \
		${HUGGINGFACE_OVERLAY[@]+"${HUGGINGFACE_OVERLAY[@]}"} \
		${OPENBAO_OVERLAY[@]+"${OPENBAO_OVERLAY[@]}"} \
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
	if [ "$HUGGINGFACE" = 1 ]; then
		assert_protected_data_path "$HUB_CACHE_ROOT"
		assert_protected_data_path "$HUB_BUNDLES_ROOT"
		assert_protected_data_path "$HUB_BUNDLE_KEYS_ROOT"
	fi
	if [ "$OPENBAO" = 1 ]; then
		assert_protected_data_path "$OPENBAO_DATA_ROOT"
		assert_protected_data_path "$OPENBAO_BACKUPS_ROOT"
	fi
	assert_exact_backing_path \
		"$SECURE_DEPOSIT_ROOT" "$EXPECTED_SECURE_SOURCE" "$SECURE_DEPOSIT_ROOT"
	assert_protected_data_path "$FAISS_ROOT"
	compose --profile infra --profile tools --profile sftp "${ML_TS_PROFILE[@]}" "${ML_DEEP_PROFILE[@]}" "${HUGGINGFACE_PROFILE[@]}" "${OPENBAO_PROFILE[@]}" config --format json |
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
	for container in "${ML_TS_ALL[@]}" "${ML_DEEP_ALL[@]}" agentium-hub-fetch; do
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

# One private directory per `migrate`/`up` on the data disk: it holds the
# database dump and the maintenance gate's frozen orchestration state.
start_run() {
	local command="$1"
	clean_exec install -d -m 0700 -- "$DEPLOYMENTS_ROOT"
	assert_protected_data_path "$DEPLOYMENTS_ROOT"
	RUN_ID="$(clean_exec date -u +%Y%m%dT%H%M%SZ)-$command"
	RUN_DIR="$DEPLOYMENTS_ROOT/$RUN_ID"
	clean_exec install -d -m 0700 -- "$RUN_DIR"
	PREVIOUS_TAG="$(readonly_docker inspect --type container agentium-backend --format '{{.Config.Image}}' 2>/dev/null || true)"
	PREVIOUS_TAG="${PREVIOUS_TAG##*:}"
	PREVIOUS_TAG="${PREVIOUS_TAG:--}"
}

journal_append() {
	local command="$1" revision="$2" backup="$3" result="$4"
	if [[ ! -s "$JOURNAL" ]]; then
		printf 'recorded_at\trun_id\tcommand\ttag\tprevious_tag\trevision\tbackup\tresult\n' >"$JOURNAL"
	fi
	printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
		"$(clean_exec date -u +%Y-%m-%dT%H:%M:%SZ)" "$RUN_ID" "$command" "$TAG" \
		"$PREVIOUS_TAG" "$revision" "$backup" "$result" >>"$JOURNAL"
}

# pg_dump -Fc, proven readable by pg_restore before it is published, then a
# `.ready` marker carrying its digest and size. migrate never runs without it.
backup_database() {
	local temporary="$RUN_DIR/.postgres-pre-migrate.partial"
	local backup="$RUN_DIR/postgres-pre-migrate.dump"
	local digest bytes
	(
		umask 077
		readonly_docker exec agentium-pg sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' >"$temporary"
	) || fail "pg_dump failed; migrate not started"
	[[ -s "$temporary" ]] || fail "pg_dump produced an empty archive; migrate not started"
	readonly_docker exec -i agentium-pg pg_restore --list <"$temporary" >/dev/null ||
		fail "pg_dump archive is unreadable; migrate not started"
	clean_exec mv -- "$temporary" "$backup"
	digest="$(clean_exec sha256sum -- "$backup")"
	digest="${digest%% *}"
	[[ "$digest" =~ ^[0-9a-f]{64}$ ]] || fail "pg_dump archive digest is invalid"
	bytes="$(clean_exec stat -c %s -- "$backup")"
	(
		umask 077
		printf 'format\t1\nsha256\t%s\nbytes\t%s\n' "$digest" "$bytes" >"$backup.ready"
	)
	BACKUP="$backup"
}

# The gate helper only mutates from a frozen copy next to its orchestration
# metadata; requests to 127.0.0.2 stay open for the build-info probe.
gate() {
	local mode="$1"
	clean_exec \
		OMNIRAG_REPO_DIR="$R" \
		AGENTIUM_SAFE_DEPLOY_ORCHESTRATED=1 \
		AGENTIUM_SAFE_DEPLOYMENT_DIR="$RUN_DIR" \
		AGENTIUM_SAFE_DEPLOYMENT_ID="$RUN_ID" \
		AGENTIUM_SAFE_GATE_PURPOSE=launcher-open \
		bash "$RUN_DIR/agentium-maintenance-gate.sh" "$mode"
}

gate_enter() {
	local candidate
	[ "$GATE" = 1 ] || return 0
	candidate="$(clean_exec git -C "$R" rev-parse HEAD)"
	[[ "$candidate" =~ ^[0-9a-f]{40}$ ]] || fail "Cannot resolve the worktree revision for the gate"
	clean_exec install -m 0700 -- "$MAINTENANCE_GATE" "$RUN_DIR/agentium-maintenance-gate.sh"
	printf 'deployment_id\t%s\ncandidate_sha\t%s\n' "$RUN_ID" "$candidate" >"$RUN_DIR/metadata.tsv"
	printf 'launcher\n' >"$RUN_DIR/phase"
	gate enter
	printf 'maintenance gate closed (run %s); if this command fails, reopen with: %s gate-exit %s\n' \
		"$RUN_ID" "$0" "$RUN_ID" >&2
}

gate_leave() {
	[ "$GATE" = 1 ] || return 0
	gate exit
}

# The running backend must report the deployed revision, attested by its
# image (revision_verified), before the deployment counts as done.
verify_build_info() {
	local expected="$TAG" attempt payload
	[[ "$TAG" == demo-agentic ]] && expected="$(clean_exec git -C "$R" rev-parse HEAD)"
	for ((attempt = 1; attempt <= BUILD_INFO_ATTEMPTS; attempt++)); do
		if payload="$(readonly_docker exec agentium-backend python -I -c 'import http.client;c=http.client.HTTPConnection("127.0.0.1",8000,timeout=5);c.request("GET","/api/v1/build-info");r=c.getresponse();b=r.read(4097);assert r.status==200 and len(b)<=4096;print(b.decode())' 2>/dev/null)" &&
			REVISION="$(printf '%s' "$payload" | clean_exec python3 -I -c '
import json, re, sys
info = json.load(sys.stdin)
revision = info.get("revision") if isinstance(info, dict) else None
if info.get("revision_verified") is not True or not isinstance(revision, str):
    raise SystemExit(1)
if re.fullmatch(r"[0-9a-f]{40}", revision) is None or not revision.startswith(sys.argv[1]):
    raise SystemExit(1)
print(revision)
' "$expected")"; then
			return 0
		fi
		sleep "${AGENTIUM_BUILD_INFO_INTERVAL:-5}"
	done
	return 1
}

case "${1:-}" in
images) compose "${ML_TS_PROFILE[@]}" "${ML_DEEP_PROFILE[@]}" "${HUGGINGFACE_PROFILE[@]}" "${OPENBAO_PROFILE[@]}" config --images ;;
storage-check) storage_check ;;
migrate)
	storage_check
	start_run migrate
	gate_enter
	backup_database
	journal_append migrate - "$BACKUP" started
	compose run --rm --no-deps --pull never agentium-migrate || {
		journal_append migrate - "$BACKUP" failed
		fail "migrate failed; restore point: $BACKUP"
	}
	journal_append migrate - "$BACKUP" passed
	gate_leave
	;;
up)
	storage_check
	start_run up
	gate_enter
	compose up -d --no-build --no-deps --pull never agentium-worker-recipes agentium-backend agentium-worker-cpu agentium-frontend agentium-p4-maintenance agentium-beat "${ML_TS_SERVICES[@]}" "${ML_DEEP_SERVICES[@]}" "${HUGGINGFACE_SERVICES[@]}" "${OPENBAO_SERVICES[@]}"
	verify_build_info || {
		journal_append up - - failed
		fail "build-info did not report $TAG with revision_verified; roll back with AGENTIUM_IMAGE_TAG=$PREVIOUS_TAG $0 up"
	}
	journal_append up "$REVISION" - passed
	gate_leave
	# Said at the end of every switch, never blocking it: new code
	# whose Skills the database lacks is a feature nobody can see.
	catalog >/dev/null || printf '%s\n' "WARNING: catalog-check did not pass (verdict above); to bring the Skills catalog to this release: $0 catalog-apply" >&2
	;;
gate-exit)
	RUN_ID="${2:-}"
	[[ "$RUN_ID" =~ ^[0-9]{8}T[0-9]{6}Z-(migrate|up)$ && -f "$DEPLOYMENTS_ROOT/$RUN_ID/phase" ]] ||
		fail "usage: $0 gate-exit <run-id from $JOURNAL>"
	RUN_DIR="$DEPLOYMENTS_ROOT/$RUN_ID"
	gate exit
	;;
journal) clean_exec cat -- "$JOURNAL" ;;
# The SFTP server is outside `up` (its image is pinned by digest, not tagged
# per release); this recreates it when its bind changes.
sftp-up)
	storage_check
	compose --profile sftp up -d --no-build --no-deps --pull never agentium-sftp
	;;
catalog-check) catalog ;;
catalog-apply)
	storage_check
	catalog --apply
	;;
openbao-prepare)
	[ "$OPENBAO" = 1 ] || fail "openbao-prepare requires AGENTIUM_OPENBAO=1"
	assert_data_device
	assert_protected_data_path "$OPENBAO_DATA_ROOT"
	clean_exec python3 "$OPENBAO_BOOTSTRAP" prepare --runtime-env "$D/runtime-env" --data-path "$OPENBAO_DATA_ROOT"
	;;
openbao-init)
	[ "$OPENBAO" = 1 ] || fail "openbao-init requires AGENTIUM_OPENBAO=1"
	storage_check
	compose up -d --no-build --no-deps --pull never agentium-openbao
	OPENBAO_IP="$(readonly_docker inspect agentium-openbao --format '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' | /usr/bin/awk '{print $1}')"
	[ -n "$OPENBAO_IP" ] || fail "agentium-openbao has no network address"
	clean_exec python3 "$OPENBAO_BOOTSTRAP" init --addr "http://$OPENBAO_IP:8200" --runtime-env "$D/runtime-env"
	;;
openbao-snapshot)
	[ "$OPENBAO" = 1 ] || fail "openbao-snapshot requires AGENTIUM_OPENBAO=1"
	assert_protected_data_path "$OPENBAO_BACKUPS_ROOT"
	clean_exec AGENTIUM_OPENBAO_BACKUPS_PATH="$OPENBAO_BACKUPS_ROOT" bash "$R/scripts/agentium-openbao-snapshot.sh" "$D/runtime-env"
	;;
openbao-status) readonly_docker exec agentium-openbao bao status ;;
ml-ts-stop) compose --profile ml-ts rm --stop --force "${ML_TS_ALL[@]}" ;;
ml-deep-stop) compose --profile ml-deep rm --stop --force "${ML_DEEP_ALL[@]}" ;;
ps) compose "${ML_TS_PROFILE[@]}" "${ML_DEEP_PROFILE[@]}" "${HUGGINGFACE_PROFILE[@]}" "${OPENBAO_PROFILE[@]}" ps ;;
*)
	echo "usage: $0 {images|storage-check|migrate|up|gate-exit|journal|sftp-up|catalog-check|catalog-apply|openbao-prepare|openbao-init|openbao-snapshot|openbao-status|ml-ts-stop|ml-deep-stop|ps}" >&2
	exit 2
	;;
esac
