#!/usr/bin/env bash
# Reproducible, destructive P4 rehearsal on disposable Docker services only.
set -euo pipefail

SOURCE_DIR="$(pwd)"
TARGET_SHA=""
OUTPUT_DIR=""
RUNNER_IMAGE="agentium-worker:local"
MIN_FREE_DISK_MIB=3072
MIN_AVAILABLE_MEMORY_MIB=6144
MIN_DOCKER_CPUS=4
EXPECTED_JUNIT_TESTS=7

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source) SOURCE_DIR="$2"; shift 2 ;;
    --sha) TARGET_SHA="$2"; shift 2 ;;
    --output) OUTPUT_DIR="$2"; shift 2 ;;
    --runner-image) RUNNER_IMAGE="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

SOURCE_DIR="$(cd "$SOURCE_DIR" && pwd)"
command -v docker >/dev/null
command -v df >/dev/null
command -v dirname >/dev/null
command -v flock >/dev/null
command -v git >/dev/null
command -v install >/dev/null
command -v python3 >/dev/null
command -v sha256sum >/dev/null
command -v tar >/dev/null
command -v timeout >/dev/null
command -v awk >/dev/null

if ! git -C "$SOURCE_DIR" rev-parse --git-dir >/dev/null 2>&1; then
  echo "--source must be a Git worktree" >&2
  exit 2
fi
if [[ -z "$TARGET_SHA" ]]; then
  TARGET_SHA="$(git -C "$SOURCE_DIR" rev-parse HEAD)"
fi
if [[ ! "$TARGET_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "--sha must be the exact 40-character source revision" >&2
  exit 2
fi
if ! git -C "$SOURCE_DIR" cat-file -e "${TARGET_SHA}^{commit}" 2>/dev/null; then
  echo "--sha is not a commit available from --source" >&2
  exit 2
fi
if [[ "$(git -C "$SOURCE_DIR" rev-parse "${TARGET_SHA}^{commit}")" != "$TARGET_SHA" ]]; then
  echo "--sha must identify the commit exactly" >&2
  exit 2
fi

# Only these committed paths are exposed to the candidate runner. In particular,
# the live checkout and backend/.env are never mounted into a container.
SOURCE_PATHS=(
  backend/app
  backend/alembic
  backend/alembic.ini
  backend/poetry.lock
  backend/pyproject.toml
  backend/requirements.txt
)
for source_path in "${SOURCE_PATHS[@]}"; do
  if ! git -C "$SOURCE_DIR" cat-file -e "${TARGET_SHA}:${source_path}" 2>/dev/null; then
    echo "Required path is absent from ${TARGET_SHA}: ${source_path}" >&2
    exit 2
  fi
done

SHORT_SHA="${TARGET_SHA:0:12}"
SUFFIX="${SHORT_SHA}-$$"
NETWORK="agentium-p4-${SUFFIX}"
INSTALLER_CONTAINER="agentium-p4-installer-${SUFFIX}"
POSTGRES_CONTAINER="agentium-p4-postgres-${SUFFIX}"
RABBITMQ_CONTAINER="agentium-p4-rabbitmq-${SUFFIX}"
RUNNER_CONTAINER="agentium-p4-runner-${SUFFIX}"
POSTGRES_PASSWORD="p4-${SUFFIX}"
RABBITMQ_PASSWORD="p4-${SUFFIX}"

exec 9>/tmp/agentium-p4-gate.lock
if ! flock -n 9; then
  echo "Another P4 gate owns /tmp/agentium-p4-gate.lock" >&2
  exit 3
fi

OUTPUT_DIR="${OUTPUT_DIR:-/tmp/agentium-p4-${SUFFIX}/results}"

if [[ ! -r /proc/meminfo ]]; then
  echo "Cannot read /proc/meminfo; the VM resource preflight is mandatory" >&2
  exit 4
fi
AVAILABLE_MEMORY_KIB="$(awk '/^MemAvailable:/ {print $2; exit}' /proc/meminfo)"
if [[ ! "$AVAILABLE_MEMORY_KIB" =~ ^[0-9]+$ ]]; then
  echo "Cannot determine available VM memory" >&2
  exit 4
fi
AVAILABLE_MEMORY_MIB=$((AVAILABLE_MEMORY_KIB / 1024))
if (( AVAILABLE_MEMORY_MIB < MIN_AVAILABLE_MEMORY_MIB )); then
  echo "Insufficient VM memory: ${AVAILABLE_MEMORY_MIB} MiB available, ${MIN_AVAILABLE_MEMORY_MIB} MiB required" >&2
  exit 4
fi

DOCKER_CPUS="$(docker info --format '{{.NCPU}}')"
if [[ ! "$DOCKER_CPUS" =~ ^[0-9]+$ ]] || (( DOCKER_CPUS < MIN_DOCKER_CPUS )); then
  echo "Insufficient Docker CPU capacity: ${DOCKER_CPUS:-unknown} available, ${MIN_DOCKER_CPUS} required" >&2
  exit 4
fi

OUTPUT_PROBE="$OUTPUT_DIR"
while [[ ! -e "$OUTPUT_PROBE" ]]; do
  OUTPUT_PROBE_PARENT="$(dirname "$OUTPUT_PROBE")"
  if [[ "$OUTPUT_PROBE_PARENT" == "$OUTPUT_PROBE" ]]; then
    OUTPUT_PROBE="/"
    break
  fi
  OUTPUT_PROBE="$OUTPUT_PROBE_PARENT"
done
OUTPUT_FREE_KIB="$(df -Pk "$OUTPUT_PROBE" | awk 'NR == 2 {print $4}')"
DOCKER_ROOT_DIR="$(docker info --format '{{.DockerRootDir}}')"
if DOCKER_FREE_KIB="$(df -Pk "$DOCKER_ROOT_DIR" 2>/dev/null | awk 'NR == 2 {print $4}')" \
  && [[ "$DOCKER_FREE_KIB" =~ ^[0-9]+$ ]]; then
  :
else
  DOCKER_FREE_KIB="$(df -Pk / | awk 'NR == 2 {print $4}')"
fi
if [[ ! "$OUTPUT_FREE_KIB" =~ ^[0-9]+$ ]] || [[ ! "$DOCKER_FREE_KIB" =~ ^[0-9]+$ ]]; then
  echo "Cannot determine free space for evidence or Docker storage" >&2
  exit 4
fi
AVAILABLE_DISK_KIB="$OUTPUT_FREE_KIB"
if (( DOCKER_FREE_KIB < AVAILABLE_DISK_KIB )); then
  AVAILABLE_DISK_KIB="$DOCKER_FREE_KIB"
fi
AVAILABLE_DISK_MIB=$((AVAILABLE_DISK_KIB / 1024))
if (( AVAILABLE_DISK_MIB < MIN_FREE_DISK_MIB )); then
  echo "Insufficient VM disk margin: ${AVAILABLE_DISK_MIB} MiB free, ${MIN_FREE_DISK_MIB} MiB required" >&2
  exit 4
fi

if [[ -e "$OUTPUT_DIR" ]] && [[ -n "$(find "$OUTPUT_DIR" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
  echo "--output must be absent or empty: $OUTPUT_DIR" >&2
  exit 2
fi
mkdir -p "$OUTPUT_DIR"
chmod 0700 "$OUTPUT_DIR"

WORK_DIR="$(mktemp -d "/tmp/agentium-p4-source-${SUFFIX}.XXXXXX")"
ARCHIVE_TAR="$WORK_DIR/source.tar"
ARCHIVE_ROOT="$WORK_DIR/source"
VENV_DIR="$WORK_DIR/venv"
RAW_RESULTS_DIR="$WORK_DIR/container-results"

capture_logs() {
  docker logs "$POSTGRES_CONTAINER" >"$OUTPUT_DIR/postgres.log" 2>&1 || true
  docker logs "$RABBITMQ_CONTAINER" >"$OUTPUT_DIR/rabbitmq.log" 2>&1 || true
  docker logs "$RUNNER_CONTAINER" >"$OUTPUT_DIR/runner.log" 2>&1 || true
}

cleanup() {
  docker rm -f \
    "$INSTALLER_CONTAINER" \
    "$RUNNER_CONTAINER" \
    "$POSTGRES_CONTAINER" \
    "$RABBITMQ_CONTAINER" >/dev/null 2>&1 || true
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
  rm -rf "$WORK_DIR"
}

on_exit() {
  status=$?
  trap - EXIT INT TERM
  set +e
  capture_logs
  cleanup
  exit "$status"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

mkdir -p "$ARCHIVE_ROOT"
mkdir -p "$VENV_DIR"
mkdir -p "$RAW_RESULTS_DIR"
chmod 0700 "$VENV_DIR"
chmod 0700 "$RAW_RESULTS_DIR"

git -C "$SOURCE_DIR" archive \
  --format=tar \
  --output="$ARCHIVE_TAR" \
  "$TARGET_SHA" \
  -- "${SOURCE_PATHS[@]}"
tar -xf "$ARCHIVE_TAR" -C "$ARCHIVE_ROOT"
rm -f "$ARCHIVE_TAR"

test -f "$ARCHIVE_ROOT/backend/app/tests/integration/test_subflow_celery_rabbitmq.py"
SENSITIVE_SOURCE="$(find "$ARCHIVE_ROOT/backend" -type f \( \
  -name '.env' -o \
  -name '.env.*' -o \
  -name '*.pem' -o \
  -name '*.key' -o \
  -name '*.p12' -o \
  -name '*.pfx' -o \
  -name 'credentials.json' \
\) -print -quit)"
if [[ -n "$SENSITIVE_SOURCE" ]]; then
  echo "Refusing to expose sensitive candidate path: $SENSITIVE_SOURCE" >&2
  exit 2
fi
chmod -R go-rwx "$ARCHIVE_ROOT"

docker image inspect "$RUNNER_IMAGE" >/dev/null
docker image inspect postgres:17 >/dev/null
docker image inspect rabbitmq:4.1-management >/dev/null
CANDIDATE_RUNNER_IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$RUNNER_IMAGE")"
CANDIDATE_RUNNER_REVISION="$(docker image inspect \
  --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' \
  "$CANDIDATE_RUNNER_IMAGE_ID")"
if [[ "$CANDIDATE_RUNNER_REVISION" != "$TARGET_SHA" ]]; then
  echo "Runner image revision does not match --sha" >&2
  exit 2
fi

# Dependency bootstrap is the only container with outbound access. It sees no
# candidate source and /app is masked, so image-embedded checkout files cannot
# be read by the install process. The resulting disposable venv is then mounted
# read-only into the isolated candidate runner.
docker run --rm --pull=never \
  --name "$INSTALLER_CONTAINER" \
  --network bridge \
  --user "$(id -u):$(id -g)" \
  --cap-drop=ALL \
  --security-opt=no-new-privileges \
  --read-only \
  --memory=768m --memory-swap=768m --cpus=1.0 --pids-limit=128 \
  --tmpfs /app:rw,exec,nosuid,size=16m,mode=1777 \
  --tmpfs /run/secrets:rw,noexec,nosuid,size=1m,mode=0700 \
  --tmpfs /tmp:rw,exec,nosuid,size=256m,mode=1777 \
  -v "$VENV_DIR:/opt/p4-venv" \
  -w /tmp \
  "$CANDIDATE_RUNNER_IMAGE_ID" \
  /bin/sh -ec '
    python -m venv --system-site-packages /opt/p4-venv
    /opt/p4-venv/bin/python -m pip install \
      --disable-pip-version-check --no-cache-dir --only-binary=:all: \
      pytest==7.4.4 pytest-asyncio==0.21.2
  '
chmod -R go-rwx "$VENV_DIR"

# No host ports, no persistent Docker volumes, and no route to the Internet or
# the VM metadata service from candidate code.
docker network create --internal "$NETWORK" >/dev/null

docker run -d --pull=never \
  --name "$POSTGRES_CONTAINER" \
  --network "$NETWORK" --network-alias postgres \
  --memory=768m --memory-swap=768m --cpus=0.5 --pids-limit=128 \
  --log-opt max-size=20m --log-opt max-file=1 \
  --tmpfs /var/lib/postgresql/data:rw,noexec,nosuid,size=1g \
  -e POSTGRES_DB=agentium_p4 \
  -e POSTGRES_USER=agentium_p4 \
  -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  postgres:17 >/dev/null

docker run -d --pull=never \
  --name "$RABBITMQ_CONTAINER" \
  --network "$NETWORK" --network-alias rabbitmq \
  --memory=768m --memory-swap=768m --cpus=0.5 --pids-limit=512 \
  --log-opt max-size=20m --log-opt max-file=1 \
  --tmpfs /var/lib/rabbitmq:rw,noexec,nosuid,size=512m \
  -e RABBITMQ_DEFAULT_USER=agentium_p4 \
  -e RABBITMQ_DEFAULT_PASS="$RABBITMQ_PASSWORD" \
  -e RABBITMQ_DEFAULT_VHOST=agentium_p4 \
  rabbitmq:4.1-management >/dev/null

set +e
timeout 7200 docker run --pull=never \
  --name "$RUNNER_CONTAINER" \
  --network "$NETWORK" \
  --user "$(id -u):$(id -g)" \
  --cap-drop=ALL \
  --security-opt=no-new-privileges \
  --read-only \
  --memory=3g --memory-swap=3g --cpus=1.5 --pids-limit=384 \
  --log-opt max-size=50m --log-opt max-file=1 \
  --tmpfs /app:rw,exec,nosuid,size=64m,mode=1777 \
  --tmpfs /run/secrets:rw,noexec,nosuid,size=1m,mode=0700 \
  --tmpfs /tmp:rw,exec,nosuid,size=1g,mode=1777 \
  --tmpfs /data:rw,noexec,nosuid,size=256m,mode=1777 \
  -v "$ARCHIVE_ROOT/backend:/app/backend:ro" \
  -v "$VENV_DIR:/opt/p4-venv:ro" \
  -v "$RAW_RESULTS_DIR:/results" \
  -w /app/backend \
  -e DATABASE_URL="postgresql://agentium_p4:${POSTGRES_PASSWORD}@postgres:5432/agentium_p4" \
  -e CELERY_BROKER_URL="amqp://agentium_p4:${RABBITMQ_PASSWORD}@rabbitmq:5672/agentium_p4" \
  -e CELERY_TASK_DEFAULT_QUEUE=agentium_p4 \
  -e ENABLE_SUBFLOW_CELERY=true \
  -e ENABLE_RUN_HITL_CELERY=true \
  -e RUN_RABBITMQ_INTEGRATION=1 \
  -e PYTEST_ALLOW_DESTRUCTIVE_DATABASE_RESET=1 \
  -e P4_EXPECT_WORKER_CONCURRENCY=2 \
  -e SUBFLOW_CRASH_PROBE_DIR=/tmp \
  "$CANDIDATE_RUNNER_IMAGE_ID" \
  /bin/sh -ec '
    ulimit -f 262144
    /opt/p4-venv/bin/python - <<"PY"
import socket
import time
for host, port in (("postgres", 5432), ("rabbitmq", 5672)):
    deadline = time.monotonic() + 90
    while True:
        try:
            with socket.create_connection((host, port), timeout=2):
                break
        except OSError:
            if time.monotonic() >= deadline:
                raise SystemExit(f"{host}:{port} did not become ready")
            time.sleep(1)
PY
    # The historical Alembic chain is not a valid empty-database
    # bootstrap (migration 013 expects a pre-existing legacy SharePoint table).
    # The Pytest session fixture creates the current ORM schema in this disposable
    # database before either the worker or integration cases start.
    /opt/p4-venv/bin/python -m pytest -p no:cacheprovider -q \
      app/tests/services/test_subflow_celery_contract.py \
      app/tests/services/test_subflow_orchestration_scoping.py \
      app/tests/services/test_dispatch_outbox.py \
      app/tests/services/test_hitl_watchdog.py \
      app/tests/services/test_p4_maintenance.py \
      app/tests/services/test_run_engine_gate_ttl.py \
      app/tests/services/test_run_engine_inbox_memory.py \
      app/tests/services/test_run_engine_dag_e2e.py \
      app/tests/services/test_chat_agentic_runtime.py \
      app/tests/api/test_runs_hitl_auth.py
    /opt/p4-venv/bin/python -m celery -A app.workers.celery_app:celery_app worker \
      --pool=prefork --concurrency=2 --queues=agentium_p4 --loglevel=INFO \
      --without-gossip --without-mingle --without-heartbeat \
      --hostname="p4@%h" --pidfile=/tmp/p4-worker.pid \
      --logfile=/results/worker.log &
    worker_pid=$!
    trap "kill -TERM $worker_pid 2>/dev/null || true; wait $worker_pid 2>/dev/null || true" EXIT
    ready=0
    for _ in $(seq 1 60); do
      if /opt/p4-venv/bin/python -m celery -A app.workers.celery_app:celery_app inspect ping --timeout=2 >/dev/null 2>&1; then
        ready=1
        break
      fi
      sleep 1
    done
    test "$ready" -eq 1
    /opt/p4-venv/bin/python -m pytest -p no:cacheprovider -m rabbitmq \
      app/tests/integration/test_subflow_celery_rabbitmq.py \
      --junitxml=/results/junit.xml -q
  '
gate_status=$?
runner_exit_status="$gate_status"
set -e

# timeout(1) can return before a remote Docker process has fully stopped. Make
# container quiescence explicit before trusting or copying candidate artifacts.
if [[ "$(docker inspect --format '{{.State.Running}}' "$RUNNER_CONTAINER" 2>/dev/null || true)" == "true" ]]; then
  docker stop --time 30 "$RUNNER_CONTAINER" >/dev/null 2>&1 || \
    docker kill "$RUNNER_CONTAINER" >/dev/null 2>&1 || true
fi
if [[ "$(docker inspect --format '{{.State.Running}}' "$RUNNER_CONTAINER" 2>/dev/null || true)" == "true" ]]; then
  echo "Candidate runner did not stop; refusing its artifacts" >&2
  gate_status=87
else
  # Candidate code never writes to the final evidence directory. Only stopped-
  # container regular files are copied from the disposable staging directory,
  # so a malicious symlink cannot redirect host-side evidence writes.
  if [[ -f "$RAW_RESULTS_DIR/worker.log" ]] && [[ ! -L "$RAW_RESULTS_DIR/worker.log" ]]; then
    install -m 0600 "$RAW_RESULTS_DIR/worker.log" "$OUTPUT_DIR/worker.log"
  fi
  if [[ -f "$RAW_RESULTS_DIR/junit.xml" ]] && [[ ! -L "$RAW_RESULTS_DIR/junit.xml" ]]; then
    install -m 0600 "$RAW_RESULTS_DIR/junit.xml" "$OUTPUT_DIR/junit.xml"
  fi
fi

capture_logs
RUNNER_IMAGE_ID="$(docker inspect --format '{{.Image}}' "$RUNNER_CONTAINER")"
POSTGRES_IMAGE_ID="$(docker inspect --format '{{.Image}}' "$POSTGRES_CONTAINER")"
RABBITMQ_IMAGE_ID="$(docker inspect --format '{{.Image}}' "$RABBITMQ_CONTAINER")"
RUNNER_IMAGE_REVISION="$(docker image inspect \
  --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' \
  "$RUNNER_IMAGE_ID")"
JUNIT_SHA256=""
JUNIT_VALIDATION_STATUS=0
set +e
python3 - \
  "$OUTPUT_DIR/junit.xml" \
  "$OUTPUT_DIR/junit-summary.json" \
  "$EXPECTED_JUNIT_TESTS" <<'PY'
import json
import sys
import xml.etree.ElementTree as ET

junit_path, summary_path, expected_tests_raw = sys.argv[1:]
expected_tests = int(expected_tests_raw)
try:
    root = ET.parse(junit_path).getroot()
except (FileNotFoundError, ET.ParseError) as exc:
    print(f"JUnit is missing or invalid: {exc}", file=sys.stderr)
    raise SystemExit(2)

if root.tag == "testsuite":
    suites = [root]
elif root.tag == "testsuites":
    suites = list(root.findall("./testsuite"))
else:
    print(f"Unsupported JUnit root element: {root.tag}", file=sys.stderr)
    raise SystemExit(2)

def total(attribute: str) -> int:
    try:
        return sum(int(suite.attrib.get(attribute, "0")) for suite in suites)
    except ValueError as exc:
        print(f"Invalid JUnit {attribute} count: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

summary = {
    "tests": total("tests"),
    "failures": total("failures"),
    "errors": total("errors"),
    "skipped": total("skipped"),
}
with open(summary_path, "w", encoding="utf-8") as handle:
    json.dump(summary, handle, indent=2, sort_keys=True)
    handle.write("\n")

if summary["tests"] != expected_tests:
    print(
        f"JUnit test count mismatch: {summary['tests']} != {expected_tests}",
        file=sys.stderr,
    )
    raise SystemExit(3)
if summary["failures"] or summary["errors"]:
    print(f"JUnit reports failures or errors: {summary}", file=sys.stderr)
    raise SystemExit(4)
if summary["skipped"]:
    print(f"JUnit reports skipped tests: {summary}", file=sys.stderr)
    raise SystemExit(5)
PY
JUNIT_VALIDATION_STATUS=$?
set -e

if [[ "$gate_status" -eq 0 ]] && [[ "$JUNIT_VALIDATION_STATUS" -ne 0 ]]; then
  gate_status=86
fi
if [[ "$JUNIT_VALIDATION_STATUS" -eq 0 ]]; then
  JUNIT_SHA256="$(sha256sum "$OUTPUT_DIR/junit.xml" | awk '{print $1}')"
fi

TARGET_SHA="$TARGET_SHA" \
GATE_STATUS="$gate_status" \
RUNNER_EXIT_STATUS="$runner_exit_status" \
RUNNER_IMAGE_ID="$RUNNER_IMAGE_ID" \
RUNNER_IMAGE_REVISION="$RUNNER_IMAGE_REVISION" \
POSTGRES_IMAGE_ID="$POSTGRES_IMAGE_ID" \
RABBITMQ_IMAGE_ID="$RABBITMQ_IMAGE_ID" \
JUNIT_SHA256="$JUNIT_SHA256" \
JUNIT_VALIDATION_STATUS="$JUNIT_VALIDATION_STATUS" \
JUNIT_SUMMARY_PATH="$OUTPUT_DIR/junit-summary.json" \
EXPECTED_JUNIT_TESTS="$EXPECTED_JUNIT_TESTS" \
AVAILABLE_MEMORY_MIB="$AVAILABLE_MEMORY_MIB" \
MIN_AVAILABLE_MEMORY_MIB="$MIN_AVAILABLE_MEMORY_MIB" \
AVAILABLE_DISK_MIB="$AVAILABLE_DISK_MIB" \
MIN_FREE_DISK_MIB="$MIN_FREE_DISK_MIB" \
DOCKER_CPUS="$DOCKER_CPUS" \
MIN_DOCKER_CPUS="$MIN_DOCKER_CPUS" \
python3 - "$OUTPUT_DIR/p4-gate-observation.json" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone

junit_summary = None
if os.environ["JUNIT_VALIDATION_STATUS"] == "0":
    with open(os.environ["JUNIT_SUMMARY_PATH"], encoding="utf-8") as handle:
        junit_summary = json.load(handle)

payload = {
    "evidence_class": "local_vm_observation",
    "trusted_attestation": False,
    "claim": "LOT6-P4-DURABLE-SUBFLOWS",
    "sha": os.environ["TARGET_SHA"],
    "status": "passed"
    if os.environ["GATE_STATUS"] == "0"
    and os.environ["JUNIT_VALIDATION_STATUS"] == "0"
    else "failed",
    "gate_exit_code": int(os.environ["GATE_STATUS"]),
    "runner_exit_code": int(os.environ["RUNNER_EXIT_STATUS"]),
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "junit_sha256": os.environ.get("JUNIT_SHA256") or None,
    "junit_validated": os.environ["JUNIT_VALIDATION_STATUS"] == "0",
    "junit_expected_tests": int(os.environ["EXPECTED_JUNIT_TESTS"]),
    "junit_summary": junit_summary,
    "images": {
        "runner": os.environ["RUNNER_IMAGE_ID"],
        "runner_revision": os.environ["RUNNER_IMAGE_REVISION"],
        "postgres": os.environ["POSTGRES_IMAGE_ID"],
        "rabbitmq": os.environ["RABBITMQ_IMAGE_ID"],
    },
    "isolation": {
        "host_ports": [],
        "persistent_volumes": [],
        "database": "agentium_p4",
        "schema_provisioning": "orm_metadata_create_all",
        "ephemeral_network": True,
        "candidate_network_internal": True,
        "candidate_outbound_access": False,
        "dependency_bootstrap_saw_candidate_source": False,
        "candidate_source": "git_archive_allowlist",
        "candidate_artifacts_host_staged": True,
        "live_checkout_mounted": False,
        "sensitive_files_mounted": False,
    },
    "resource_preflight": {
        "available_memory_mib": int(os.environ["AVAILABLE_MEMORY_MIB"]),
        "required_memory_mib": int(os.environ["MIN_AVAILABLE_MEMORY_MIB"]),
        "available_disk_mib": int(os.environ["AVAILABLE_DISK_MIB"]),
        "required_disk_mib": int(os.environ["MIN_FREE_DISK_MIB"]),
        "docker_cpus": int(os.environ["DOCKER_CPUS"]),
        "required_docker_cpus": int(os.environ["MIN_DOCKER_CPUS"]),
        "container_limits": {
            "installer": {"memory": "768m", "cpus": 1.0, "pids": 128},
            "postgres": {"memory": "768m", "cpus": 0.5, "pids": 128},
            "rabbitmq": {"memory": "768m", "cpus": 0.5, "pids": 512},
            "runner": {"memory": "3g", "cpus": 1.5, "pids": 384},
        },
        "swap_above_memory_limit": False,
    },
}
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY

exit "$gate_status"
