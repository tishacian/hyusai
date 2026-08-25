#!/usr/bin/env bash
# Pre-release dump for a VM that carries the data/ML plane.
#
# The release process has always taken a `pg_dump` before migrating, and that was
# sufficient while every fact lived in Postgres. It no longer is: a dataset row
# names a Parquet object and a model row names an MLflow model directory, both in
# the MinIO bucket, and neither is inside a database dump. Restore Postgres alone
# and you get a registry of dangling URIs — every /predict answers
# ML_ARTIFACT_MISSING, every dataset preview fails — which is the worst kind of
# backup, the one that looks like it worked.
#
# So this takes both into one window, and then checks the thing that makes the
# pair a backup rather than two files: that every artifact the restored registry
# would ask for is present in the window.
#
# There is a third part, on the same instance: the `mlflow` database backing the
# MLflow Model Registry — runs, model versions, champion/challenger aliases. It
# is what makes our artifacts loadable by a stock MLflow client, and it does not
# rebuild itself for models already trained, so it is dumped rather than treated
# as a cache. Its absence is not an error (a pre-slice VM, or one running with
# ML_REGISTRY_ENABLED=false) but it is always reported.
#
# Scope comes from the registry, not from a path glob. Only workspaces that own
# datasets or models are mirrored, and only their `tabular/` and `ml/` prefixes
# — never a whole workspace, which would drag in knowledge collections an order
# of magnitude larger for nothing.
#
# Usage (on the VM, as root):
#   sudo scripts/agentium-data-plane-dump.sh <sha12> [slice]
#
# Writes /srv/agentium-data/<slice>-deployments/<date>-<sha12>/ holding
# pre-<sha12>.dump, pre-<sha12>-mlflow.dump, objects/, their checksums,
# MANIFEST.json and .ready. The mirror covers each workspace's whole `ml/`
# prefix, so a model's skore report state — the evaluation its card was read
# from — travels with the model directory rather than needing its own pass.
# `.ready` is written last and only when the artifact check passed, so its
# presence — not the directory's existence — is what says the window is
# restorable.
set -euo pipefail

readonly DATA_ROOT=/srv/agentium-data
readonly PG_CONTAINER=agentium-pg
readonly BACKEND_CONTAINER=agentium-backend
readonly MINIO_CONTAINER=agentium-minio
readonly DB=agentium
# The MLflow Model Registry's backend store: a second database on the same
# instance, holding the runs, model versions and champion/challenger aliases that
# make our artifacts readable by a stock MLflow client. Losing it is survivable —
# `ml_models` keeps training, serving and promoting — but it does not rebuild
# itself for models already trained, so it is dumped, not treated as a cache.
readonly REGISTRY_DB=mlflow
readonly DB_USER=agentium
readonly STAGE=/tmp/agentium-data-plane-dump
# A ceiling, because the mirror stages inside the MinIO container's writable
# layer, which sits on the root device rather than the protected data volume. The
# plane is tens of megabytes today; a run that suddenly wants gigabytes is a
# surprise worth stopping on rather than a root filesystem to fill.
readonly MAX_OBJECT_MB=8192

fail() {
  printf '%s\n' "$*" >&2
  exit 1
}

SHA="${1:-}"
case "$SHA" in
  [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
  *) fail "usage: $0 <sha12> [slice]   (sha12 is exactly 12 hex characters)" ;;
esac

SLICE="${2:-data-plane}"
case "$SLICE" in
  '' | *[!a-z0-9-]*) fail "slice must be lowercase letters, digits and dashes" ;;
esac

TODAY="$(date +%F)"
readonly SHA SLICE TODAY
readonly WINDOW="$DATA_ROOT/$SLICE-deployments/$TODAY-$SHA"
readonly DUMP="$WINDOW/pre-$SHA.dump"
readonly REGISTRY_DUMP="$WINDOW/pre-$SHA-$REGISTRY_DB.dump"

[ -d "$DATA_ROOT" ] || fail "$DATA_ROOT is not mounted"
[ -e "$WINDOW/.ready" ] && fail "$WINDOW is already a completed window"

query() {
  docker exec "$PG_CONTAINER" psql -U "$DB_USER" -d "$DB" -At -c "$1"
}

# One `mc` command inside the MinIO container. `mc` ships in that image and the
# root credentials live in its environment, so the alias is assembled in there:
# no secret reaches this script, this host's process list, or this window. Args
# are forwarded positionally rather than re-split, so a prefix is never reparsed.
mc_in_minio() {
  docker exec "$MINIO_CONTAINER" sh -c '
    MC_HOST_dump="http://$MINIO_ROOT_USER:$MINIO_ROOT_PASSWORD@127.0.0.1:9000"
    export MC_HOST_dump
    exec mc "$@"
  ' mc "$@"
}

# `mc du` on a prefix with no objects is a fatal error rather than a zero, and a
# workspace that owns only datasets legitimately has no `ml/` prefix — so the
# error is an expected answer here and reads as 0.
prefix_bytes() {
  mc_in_minio du --json "$1" 2>/dev/null | python3 -c 'import json, sys
total = 0
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        total += int(json.loads(line).get("size", 0))
    except (ValueError, TypeError):
        pass
print(total)'
}

mkdir -p "$WINDOW"
printf 'window: %s\n' "$WINDOW"

# ---------------------------------------------------------------------------
# Postgres
# ---------------------------------------------------------------------------

docker exec "$PG_CONTAINER" pg_dump -U "$DB_USER" -d "$DB" -Fc -f "/tmp/pre-$SHA.dump"
docker cp "$PG_CONTAINER:/tmp/pre-$SHA.dump" "$DUMP"
docker exec "$PG_CONTAINER" rm -f "/tmp/pre-$SHA.dump"
sha256sum "$DUMP" > "$DUMP.sha256"
printf 'postgres: pre-%s.dump (%s)\n' "$SHA" "$(du -h "$DUMP" | cut -f1)"

# The registry database. Absent before this slice is deployed, and absent on a
# deployment that runs with ML_REGISTRY_ENABLED=false — neither is an error, but
# both are said out loud so a missing file is never mistaken for a failed dump.
REGISTRY_PRESENT=$(docker exec "$PG_CONTAINER" psql -U "$DB_USER" -d postgres -At \
  -c "select 1 from pg_database where datname = '$REGISTRY_DB'")
if [ "${REGISTRY_PRESENT:-}" = "1" ]; then
  docker exec "$PG_CONTAINER" pg_dump -U "$DB_USER" -d "$REGISTRY_DB" -Fc \
    -f "/tmp/pre-$SHA-$REGISTRY_DB.dump"
  docker cp "$PG_CONTAINER:/tmp/pre-$SHA-$REGISTRY_DB.dump" "$REGISTRY_DUMP"
  docker exec "$PG_CONTAINER" rm -f "/tmp/pre-$SHA-$REGISTRY_DB.dump"
  sha256sum "$REGISTRY_DUMP" > "$REGISTRY_DUMP.sha256"
  REGISTRY_VERSIONS=$(docker exec "$PG_CONTAINER" psql -U "$DB_USER" -d "$REGISTRY_DB" -At \
    -c "select count(*) from model_versions" 2>/dev/null || printf '0')
  printf 'registry: pre-%s-%s.dump (%s, %s model versions)\n' \
    "$SHA" "$REGISTRY_DB" "$(du -h "$REGISTRY_DUMP" | cut -f1)" "$REGISTRY_VERSIONS"
else
  REGISTRY_VERSIONS=""
  printf 'registry: none — no %s database on %s yet\n' "$REGISTRY_DB" "$PG_CONTAINER"
fi

# ---------------------------------------------------------------------------
# The objects the registry points at
# ---------------------------------------------------------------------------

PLANE_TABLES=$(query "select count(*) from information_schema.tables
                      where table_name in ('tabular_datasets', 'ml_models')")
OBJECTS=0
WORKSPACES=""

if [ "$PLANE_TABLES" -eq 0 ]; then
  # A database from before the plane landed. Said out loud, because an empty
  # objects/ is otherwise indistinguishable from a mirror that failed.
  printf 'objects: none — this database predates the data plane (no 096/097)\n'
else
  BUCKET=$(docker exec "$BACKEND_CONTAINER" printenv OBJECT_STORE_S3_BUCKET)
  [ -n "$BUCKET" ] || fail "OBJECT_STORE_S3_BUCKET is unset on $BACKEND_CONTAINER"
  printf 'bucket: %s\n' "$BUCKET"

  WORKSPACES=$(query "select workspace_id from tabular_datasets
                      union
                      select workspace_id from ml_models
                      order by 1")
fi

if [ -n "$WORKSPACES" ]; then
  total=0
  for workspace in $WORKSPACES; do
    for kind in tabular ml; do
      total=$((total + $(prefix_bytes "dump/$BUCKET/workspaces/$workspace/$kind")))
    done
  done
  printf 'objects: %s MB across %s workspace(s)\n' \
    "$((total / 1024 / 1024))" "$(printf '%s\n' "$WORKSPACES" | wc -l)"
  [ "$((total / 1024 / 1024))" -le "$MAX_OBJECT_MB" ] ||
    fail "the plane holds $((total / 1024 / 1024)) MB, past the ${MAX_OBJECT_MB} MB ceiling — mirror it deliberately, not from this script"

  docker exec "$MINIO_CONTAINER" rm -rf "$STAGE"
  docker exec "$MINIO_CONTAINER" mkdir -p "$STAGE"
  for workspace in $WORKSPACES; do
    for kind in tabular ml; do
      mc_in_minio mirror --quiet \
        "dump/$BUCKET/workspaces/$workspace/$kind" \
        "$STAGE/workspaces/$workspace/$kind" >/dev/null 2>&1 || true
    done
  done

  mkdir -p "$WINDOW/objects"
  docker cp "$MINIO_CONTAINER:$STAGE/." "$WINDOW/objects/"
  docker exec "$MINIO_CONTAINER" rm -rf "$STAGE"

  OBJECTS=$(find "$WINDOW/objects" -type f | wc -l)
  # -r, or an empty mirror checksums stdin and writes a line for "-": a manifest
  # entry that looks like evidence and is the hash of nothing.
  (cd "$WINDOW/objects" && find . -type f -print0 | sort -z | xargs -0 -r sha256sum) \
    > "$WINDOW/objects.sha256"
  printf 'objects: %s files (%s)\n' "$OBJECTS" "$(du -sh "$WINDOW/objects" | cut -f1)"
elif [ "$PLANE_TABLES" -ne 0 ]; then
  printf 'objects: none — the plane is deployed but holds nothing yet\n'
fi

# ---------------------------------------------------------------------------
# The check that makes the pair a backup
# ---------------------------------------------------------------------------

missing=0
REPORT_STATES=0
REPORT_STATES_MISSING=0
if [ -n "$WORKSPACES" ]; then
  # Checked against the bytes just copied out, not against the store: the store
  # is not what a restore will have. A dataset row names one Parquet object; a
  # model row names a directory whose MLmodel file is what the loader opens.
  while IFS= read -r key; do
    [ -n "$key" ] || continue
    [ -f "$WINDOW/objects/$key" ] || {
      printf 'MISSING dataset object %s\n' "$key" >&2
      missing=$((missing + 1))
    }
  done <<EOF
$(query "select storage_key from tabular_datasets
         where storage_key is not null and status = 'ready'")
EOF
  while IFS= read -r uri; do
    [ -n "$uri" ] || continue
    [ -f "$WINDOW/objects/$uri/MLmodel" ] || {
      printf 'MISSING model artifact %s/MLmodel\n' "$uri" >&2
      missing=$((missing + 1))
    }
  done <<EOF
$(query "select model_uri from ml_models
         where model_uri is not null and status = 'ready'")
EOF
  # The skore report state: the evaluation a model card's numbers were read
  # from. Not fatal — a model whose state was dropped still trains, serves and
  # promotes — but a row that *names* one and a window that lacks it means the
  # restored card would point at nothing, which is worth counting out loud.
  while IFS= read -r key; do
    [ -n "$key" ] || continue
    if [ -f "$WINDOW/objects/$key" ]; then
      REPORT_STATES=$((REPORT_STATES + 1))
    else
      printf 'MISSING report state %s\n' "$key" >&2
      REPORT_STATES_MISSING=$((REPORT_STATES_MISSING + 1))
    fi
  done <<EOF
$(query "select metrics_json->'report'->>'key' from ml_models
         where metrics_json->'report'->>'key' is not null")
EOF
  printf 'evaluations: %s report state(s) kept, %s named but absent\n' \
    "$REPORT_STATES" "$REPORT_STATES_MISSING"
fi

cat > "$WINDOW/MANIFEST.json" <<EOF
{
  "sha12": "$SHA",
  "slice": "$SLICE",
  "taken_at": "$(date -Is)",
  "database": "$DB",
  "postgres_dump": "pre-$SHA.dump",
  "registry_database": $([ "${REGISTRY_PRESENT:-}" = "1" ] && printf '"%s"' "$REGISTRY_DB" || echo null),
  "registry_dump": $([ "${REGISTRY_PRESENT:-}" = "1" ] && printf '"pre-%s-%s.dump"' "$SHA" "$REGISTRY_DB" || echo null),
  "registry_model_versions": ${REGISTRY_VERSIONS:-null},
  "data_plane_deployed": $([ "$PLANE_TABLES" -eq 0 ] && echo false || echo true),
  "object_files": $OBJECTS,
  "registry_artifacts_missing": $missing,
  "report_states": $REPORT_STATES,
  "report_states_missing": $REPORT_STATES_MISSING
}
EOF

[ "$missing" -eq 0 ] ||
  fail "$missing artifact(s) the registry names are absent from this window — do NOT migrate against it"

touch "$WINDOW/.ready"
printf 'ready: %s\n' "$WINDOW"
