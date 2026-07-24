#!/usr/bin/env bash
# One-time, fail-closed Release A safety adoption for the Agentium production VM.
#
# This executor intentionally has no Alembic, seed, backfill or product-data
# mutation path.  It builds from a persistent reviewed worktree, closes every
# public writer, adopts only the safety runtime, and will not reopen until the
# external schema-closed Release A attestation has been verified.
set -Eeuo pipefail
umask 077
IFS=$' \t\n'
COMPOSE_CLEAN_PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin
export PATH="$COMPOSE_CLEAN_PATH"
export PYTHONDONTWRITEBYTECODE=1
unset BASH_ENV CDPATH COMPOSE_FILE COMPOSE_PATH_SEPARATOR COMPOSE_PROFILES COMPOSE_PROJECT_NAME
unset DOCKER_CERT_PATH DOCKER_CONTEXT DOCKER_HOST DOCKER_TLS_VERIFY ENV GIT_CONFIG_COUNT GIT_CONFIG_GLOBAL GIT_CONFIG_SYSTEM GIT_DIR GIT_INDEX_FILE GIT_WORK_TREE
unset PYTHONBREAKPOINT PYTHONHOME PYTHONINSPECT PYTHONOPTIMIZE PYTHONPATH PYTHONSTARTUP PYTHONUSERBASE PYTHONWARNINGS
DOCKER_LOCAL_HOST=unix:///var/run/docker.sock
export DOCKER_HOST="$DOCKER_LOCAL_HOST"

MODE="${1:-}"
[[ $# -gt 0 ]] && shift
LIVE_REPO="${OMNIRAG_REPO_DIR:-/home/ubuntu/omnirag}"
CANDIDATE_REPO=""
BRANCH="demo/agentic"
DEDICATED_RELEASE_A_BRANCH="codex/release-a-from-hotfix"
LIVE_SHA=""
RELEASE_A_SHA=""
DEPLOYMENT_ID=""
MANIFEST=""
MANIFEST_SHA256=""
REVIEW_POLICY=""
REVIEW_POLICY_SHA256=""
PRECONDITIONS=""
PRECONDITIONS_SHA256=""
PRECONDITIONS_EVIDENCE_ROOT=""
EVIDENCE_AUTHORITY_KEYRING_SHA256=""
RUNTIME_ENV_SOURCE_ROOT=""
SFTP_CANARY_LEDGER=""
SFTP_CANARY_LEDGER_SHA256=""
ATTESTATION=""
ATTESTATION_SHA256=""
FINAL_EVIDENCE_ROOT=""
ROLLBACK_CONFIRMATION=""
STATE_ROOT="${AGENTIUM_RELEASE_A_STATE_DIR:-/srv/agentium-data/release-a-deployments}"
DATA_ROOT="${AGENTIUM_DATA_ROOT:-/srv/agentium-data}"
SECURE_DEPOSIT="${AGENTIUM_SECURE_DEPOSIT_PATH:-/home/ubuntu/omnirag/backend/data/secure_deposit}"
MIN_ROOT_FREE_BYTES=42949672960
MIN_DATA_FREE_BYTES=68719476736
MIN_SECURE_FREE_BYTES=68719476736
OPENING_FAIL_CLOSED_ARMED=0
OPENING_FAIL_CLOSED_RUNNING=0
OPENING_TERMINAL_SYNCED=0

say() { printf '==> %s\n' "$*"; }
ok() { printf 'OK  %s\n' "$*"; }
die() { printf 'XX  %s\n' "$*" >&2; exit 1; }

assert_python_runtime() {
	[[ "$(python3 -I -c 'import sys; print(sys.flags.optimize)')" == 0 ]] ||
		die "Runtime Python optimisé interdit pour les contrôles de sûreté"
}

usage() {
	cat <<'EOF'
Usage:
  deploy-agentium-release-a-safe.sh preflight --live-sha SHA --release-a-sha SHA \
    --deployment-id ID --candidate-repo PATH --branch BRANCH \
    --manifest FILE --manifest-sha256 DIGEST \
    --review-policy FILE --review-policy-sha256 DIGEST \
    --preconditions FILE --preconditions-sha256 DIGEST \
    --preconditions-evidence-root PRIVATE_DIRECTORY \
    --runtime-env-source-root PRIVATE_MIRROR
  deploy-agentium-release-a-safe.sh prepare  --live-sha SHA --release-a-sha SHA --deployment-id ID --candidate-repo PATH
  deploy-agentium-release-a-safe.sh apply    --live-sha SHA --release-a-sha SHA --deployment-id ID --candidate-repo PATH \
    --preconditions-evidence-root PRIVATE_DIRECTORY
  deploy-agentium-release-a-safe.sh resume   --live-sha SHA --release-a-sha SHA --deployment-id ID --candidate-repo PATH
  deploy-agentium-release-a-safe.sh arm-sftp-canary --live-sha SHA --release-a-sha SHA --deployment-id ID --candidate-repo PATH
  deploy-agentium-release-a-safe.sh record-sftp-active --live-sha SHA --release-a-sha SHA --deployment-id ID --candidate-repo PATH \
    --sftp-canary-ledger PRIVATE_FILE --sftp-canary-ledger-sha256 DIGEST
  deploy-agentium-release-a-safe.sh record-sftp-final --live-sha SHA --release-a-sha SHA --deployment-id ID --candidate-repo PATH
  deploy-agentium-release-a-safe.sh finalize --live-sha SHA --release-a-sha SHA --deployment-id ID --candidate-repo PATH \
    --attestation FILE --attestation-sha256 DIGEST \
    --final-evidence-root PRIVATE_DIRECTORY
  deploy-agentium-release-a-safe.sh rollback --live-sha SHA --release-a-sha SHA --deployment-id ID --candidate-repo PATH \
    --confirm-rollback ID
  deploy-agentium-release-a-safe.sh status   --live-sha SHA --release-a-sha SHA --deployment-id ID --candidate-repo PATH

preflight and prepare are non-live preparation. apply/resume keep HTTP, SFTP
and realtime ingress closed. finalize is the only forward reopen path and
requires the fresh v4 operator attestation, including a dedicated non-personal
browser canary principal distinct from the disposable SFTP principal.
EOF
}

if [[ "$MODE" == -h || "$MODE" == --help ]]; then
	usage
	exit 0
fi

while [[ $# -gt 0 ]]; do
	case "$1" in
	--live-repo) LIVE_REPO="$2"; shift 2 ;;
	--candidate-repo) CANDIDATE_REPO="$2"; shift 2 ;;
	--branch) BRANCH="$2"; shift 2 ;;
	--live-sha) LIVE_SHA="$2"; shift 2 ;;
	--release-a-sha) RELEASE_A_SHA="$2"; shift 2 ;;
	--deployment-id) DEPLOYMENT_ID="$2"; shift 2 ;;
	--manifest) MANIFEST="$2"; shift 2 ;;
	--manifest-sha256) MANIFEST_SHA256="$2"; shift 2 ;;
	--review-policy) REVIEW_POLICY="$2"; shift 2 ;;
	--review-policy-sha256) REVIEW_POLICY_SHA256="$2"; shift 2 ;;
	--preconditions) PRECONDITIONS="$2"; shift 2 ;;
	--preconditions-sha256) PRECONDITIONS_SHA256="$2"; shift 2 ;;
	--preconditions-evidence-root) PRECONDITIONS_EVIDENCE_ROOT="$2"; shift 2 ;;
	--runtime-env-source-root) RUNTIME_ENV_SOURCE_ROOT="$2"; shift 2 ;;
	--sftp-canary-ledger) SFTP_CANARY_LEDGER="$2"; shift 2 ;;
	--sftp-canary-ledger-sha256) SFTP_CANARY_LEDGER_SHA256="$2"; shift 2 ;;
	--attestation) ATTESTATION="$2"; shift 2 ;;
	--attestation-sha256) ATTESTATION_SHA256="$2"; shift 2 ;;
	--final-evidence-root) FINAL_EVIDENCE_ROOT="$2"; shift 2 ;;
	--confirm-rollback) ROLLBACK_CONFIRMATION="$2"; shift 2 ;;
	-h | --help) usage; exit 0 ;;
	*) die "Option inconnue: $1" ;;
	esac
done

case "$MODE" in preflight | prepare | apply | resume | arm-sftp-canary | record-sftp-active | record-sftp-final | finalize | rollback | status) ;; *) usage >&2; exit 2 ;; esac
[[ "$LIVE_SHA" =~ ^[0-9a-f]{40}$ ]] || die "--live-sha invalide"
[[ "$RELEASE_A_SHA" =~ ^[0-9a-f]{40}$ && "$RELEASE_A_SHA" != "$LIVE_SHA" ]] || die "--release-a-sha invalide"
[[ "$DEPLOYMENT_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{5,95}$ ]] || die "--deployment-id invalide"
[[ "$BRANCH" =~ ^[A-Za-z0-9._/-]+$ && "$BRANCH" != *..* ]] || die "--branch invalide"
[[ "$BRANCH" == demo/agentic || "$BRANCH" == "$DEDICATED_RELEASE_A_BRANCH" ]] ||
	die "Release A doit utiliser demo/agentic ou la branche dédiée $DEDICATED_RELEASE_A_BRANCH"
for path in "$LIVE_REPO" "$CANDIDATE_REPO" "$STATE_ROOT" "$DATA_ROOT" "$SECURE_DEPOSIT"; do
	[[ "$path" == /* && "$path" != *..* ]] || die "Chemin absolu sans traversée requis: $path"
done
for path in "$PRECONDITIONS_EVIDENCE_ROOT" "$FINAL_EVIDENCE_ROOT"; do
	[[ -z "$path" || ( "$path" == /* && "$path" != *..* ) ]] || die "Chemin de preuves absolu sans traversée requis: $path"
done
[[ -z "$SFTP_CANARY_LEDGER" || ( "$SFTP_CANARY_LEDGER" == /* && "$SFTP_CANARY_LEDGER" != *..* ) ]] ||
	die "Chemin absolu sans traversée requis pour le ledger SFTP"
[[ "$CANDIDATE_REPO" != /tmp/* && "$CANDIDATE_REPO" != /private/tmp/* ]] || die "Le worktree Release A doit être persistant, jamais sous /tmp"

DEPLOY_DIR="$STATE_ROOT/$DEPLOYMENT_ID"
PHASE_FILE="$DEPLOY_DIR/phase"
METADATA_FILE="$DEPLOY_DIR/metadata.tsv"
FROZEN_EXECUTOR="$DEPLOY_DIR/deploy-agentium-release-a-safe.sh"
FROZEN_MANIFEST_HELPER="$DEPLOY_DIR/agentium_release_a_manifest.py"
FROZEN_PRECONDITIONS_HELPER="$DEPLOY_DIR/agentium_release_a_preconditions.py"
FROZEN_ATTESTATION_HELPER="$DEPLOY_DIR/agentium_release_a_attestation.py"
FROZEN_EVIDENCE_HELPER="$DEPLOY_DIR/agentium_release_a_evidence_bundle.py"
FROZEN_ENV_HELPER="$DEPLOY_DIR/agentium_runtime_env_bundle.py"
FROZEN_STORAGE_HELPER="$DEPLOY_DIR/agentium_storage_attestation.py"
FROZEN_STORAGE_CONTRACT_HELPER="$DEPLOY_DIR/agentium_release_a_storage_contract.py"
FROZEN_LIVEKIT_AUDIT="$DEPLOY_DIR/audit_livekit_quiescence.py"
FROZEN_POSTGRES_AUDIT="$DEPLOY_DIR/audit_post_canary_database.py"
FROZEN_SFTP_BOUNDARY_AUDIT="$DEPLOY_DIR/audit_sftp_deploy_boundary.py"
FROZEN_SFTP_POSITIVE_GATE="$DEPLOY_DIR/agentium_release_a_sftp_positive_canary.py"
FROZEN_GATE_HELPER="$DEPLOY_DIR/agentium-maintenance-gate.sh"
FROZEN_DEPLOYER="$DEPLOY_DIR/deploy-vm-candidate.sh"
FROZEN_SYSTEMD_INSTALLER="$DEPLOY_DIR/install-backend-service.sh"
FROZEN_SYSTEMD_UNIT="$DEPLOY_DIR/agentium-backend.service"
FROZEN_NGINX_SITE="$DEPLOY_DIR/nginx-agentium-site.conf"
FROZEN_NGINX_SNIPPET="$DEPLOY_DIR/nginx-agentium-maintenance.conf"
FROZEN_QDRANT_OVERRIDE="$DEPLOY_DIR/compose.agentium.qdrant-barrier.yml"
FROZEN_OPENED_OVERRIDE="$DEPLOY_DIR/compose.agentium.opened.yml"
FROZEN_AUDIT_OVERRIDE="$DEPLOY_DIR/compose.agentium.audit-readonly.yml"
FROZEN_MANIFEST="$DEPLOY_DIR/release-a-diff-manifest.json"
FROZEN_REVIEW="$DEPLOY_DIR/release-a-semantic-review.json"
FROZEN_PRECONDITIONS="$DEPLOY_DIR/release-a-preconditions.json"
FROZEN_EVIDENCE_AUTHORITY_KEYRING="$DEPLOY_DIR/release-a-evidence-authority-keyring.json"
MANIFEST_RECEIPT="$DEPLOY_DIR/release-a-manifest-verification-receipt.json"
PRECONDITIONS_RECEIPT="$DEPLOY_DIR/release-a-preconditions-receipt.json"
PRECONDITIONS_EVIDENCE_RECEIPT="$DEPLOY_DIR/release-a-preconditions-evidence-receipt.json"
FROZEN_ATTESTATION="$DEPLOY_DIR/release-a-attestation.json"
ATTESTATION_RECEIPT="$DEPLOY_DIR/release-a-verification-receipt.json"
FINAL_EVIDENCE_RECEIPT="$DEPLOY_DIR/release-a-final-evidence-receipt.json"
FINAL_EVIDENCE_BINDING_MANIFEST="$DEPLOY_DIR/release-a-final-evidence-bindings.json"
FROZEN_FINAL_EVIDENCE_DIR="$DEPLOY_DIR/external-final-evidence"
RUNTIME_ENV_DIR="$DEPLOY_DIR/runtime-env"
RUNTIME_ENV_MANIFEST="$RUNTIME_ENV_DIR/manifest.json"
SYSTEMD_ENV_SOURCE="$DEPLOY_DIR/systemd-source.env"
RUNTIME_STATE="$DEPLOY_DIR/runtime-state.tsv"
ROLLBACK_STATE="$DEPLOY_DIR/rollback/${RELEASE_A_SHA}.tsv"
CHECKOUT_INTENT="$DEPLOY_DIR/checkout.intent"
STORAGE_BEFORE="$DEPLOY_DIR/storage-before.json"
STORAGE_AFTER="$DEPLOY_DIR/storage-after.json"
STORAGE_COMPARISON="$DEPLOY_DIR/storage-comparison.json"
STORAGE_OPENING="$DEPLOY_DIR/storage-opening.json"
STORAGE_OPENING_COMPARISON="$DEPLOY_DIR/storage-opening-comparison.json"
CANDIDATE_STORAGE_CONTRACT="$DEPLOY_DIR/candidate-storage-contract.json"
CANDIDATE_OCI_RECEIPT="$DEPLOY_DIR/release-a-candidate-oci-receipt.json"
RUNTIME_OCI_RECEIPT="$DEPLOY_DIR/release-a-runtime-oci-receipt.json"
CANDIDATE_IMAGE_OVERRIDE="$DEPLOY_DIR/compose.agentium.candidate-images.yml"
RABBIT_PHASE="$DEPLOY_DIR/rabbitmq-bootstrap.phase"
RABBIT_BODY="$DEPLOY_DIR/rabbitmq-user.json"
RABBIT_PERMISSIONS_BODY="$DEPLOY_DIR/rabbitmq-permissions.json"
RABBIT_GUEST_NETRC="$DEPLOY_DIR/rabbitmq-guest.netrc"
RABBIT_APP_NETRC="$DEPLOY_DIR/rabbitmq-app.netrc"
RABBIT_PROOF="$DEPLOY_DIR/rabbitmq-bootstrap-proof.json"
MINIO_PROOF="$DEPLOY_DIR/minio-bootstrap-proof.json"
QDRANT_PROOF="$DEPLOY_DIR/qdrant-bootstrap-proof.json"
QDRANT_PROBE_INTENT="$DEPLOY_DIR/qdrant-probe.intent"
LIVE_WRITER_PROOF="$DEPLOY_DIR/live-writer-quiescence.json"
LIVE_WRITER_FAILURE="$DEPLOY_DIR/live-writer-quiescence.failed.json"
STATEFUL_ADOPTION_INTENT="$DEPLOY_DIR/stateful-adoption.intent"
SYSTEMD_ENV_BACKUP="$DEPLOY_DIR/backend-dotenv.before"
SYSTEMD_ENV_ATTRS="$DEPLOY_DIR/backend-dotenv.attrs"
MAIN_ENV_BACKUP="$DEPLOY_DIR/compose-main-env.before"
MAIN_ENV_ATTRS="$DEPLOY_DIR/compose-main-env.attrs"
APPLICATION_ENV_BACKUP="$DEPLOY_DIR/application-env.before"
APPLICATION_ENV_ATTRS="$DEPLOY_DIR/application-env.attrs"
KEYCLOAK_ENV_BACKUP="$DEPLOY_DIR/keycloak-env.before"
KEYCLOAK_ENV_ATTRS="$DEPLOY_DIR/keycloak-env.attrs"
SYSTEMD_UNIT_BACKUP="$DEPLOY_DIR/systemd-unit.before"
SYSTEMD_UNIT_ATTRS="$DEPLOY_DIR/systemd-unit.attrs"
QDRANT_ENV_BACKUP="$DEPLOY_DIR/qdrant-env.before"
QDRANT_ENV_ATTRS="$DEPLOY_DIR/qdrant-env.attrs"
COMPLETION_RECEIPT="$DEPLOY_DIR/release-a-transaction-receipt.json"
ROLLBACK_COMPLETION_RECEIPT="$DEPLOY_DIR/release-a-rollback-receipt.json"
FORWARD_OPEN_AUTHORIZATION="$DEPLOY_DIR/release-a-forward-open-authorization.json"
ROLLBACK_OPEN_AUTHORIZATION="$DEPLOY_DIR/release-a-rollback-open-authorization.json"
FORWARD_OPEN_RECONCILED="$DEPLOY_DIR/release-a-forward-open-reconciled"
ROLLBACK_OPEN_RECONCILED="$DEPLOY_DIR/release-a-rollback-open-reconciled"
POSTGRES_DUMP="$DEPLOY_DIR/postgres-release-a.dump"
POSTGRES_INVENTORY_BEFORE="$DEPLOY_DIR/postgres-inventory-before.json"
POSTGRES_INVENTORY_AFTER="$DEPLOY_DIR/postgres-inventory-after.json"
POSTGRES_INVENTORY_OPENING="$DEPLOY_DIR/postgres-inventory-opening.json"
POSTGRES_COMPARISON="$DEPLOY_DIR/postgres-inventory-comparison.json"
POSTGRES_REHEARSAL_INTENT="$DEPLOY_DIR/postgres-rehearsal.intent"
FROZEN_SFTP_CANARY_LEDGER="$DEPLOY_DIR/sftp-canary-ledger.json"
SFTP_RUNTIME_READY="$DEPLOY_DIR/sftp-validation-runtime-ready.json"
SFTP_IDENTITY_INVALIDATION="$DEPLOY_DIR/sftp-runtime-identity-invalidation.json"
SFTP_POSTGRES_ACTIVE="$DEPLOY_DIR/postgres-inventory-sftp-active.json"
SFTP_POSTGRES_FINAL="$DEPLOY_DIR/postgres-inventory-sftp-final.json"
SFTP_POSTGRES_RECEIPT="$DEPLOY_DIR/sftp-postgres-ledger-receipt.json"
ENV_DIGEST=""
STAGE=initialization
WRITER_GATE_COMMENT="agentium-release-a-${DEPLOYMENT_ID}"
SYSTEMD_GUARD_CONTENT='[Service]
Restart=no'

[[ "$STATE_ROOT" == "$DATA_ROOT/release-a-deployments" ]] || die "Journal Release A doit rester sous le data disk canonique"
[[ "$DATA_ROOT" == /srv/agentium-data ]] || die "Data root Release A non canonique"
[[ "$SECURE_DEPOSIT" == /home/ubuntu/omnirag/backend/data/secure_deposit ]] || die "Secure Deposit Release A non canonique"
[[ -d "$DATA_ROOT" && ! -L "$DATA_ROOT" ]] || die "Data root canonique absent"
state_device="$(findmnt -n -o SOURCE --target "$DATA_ROOT")"
state_device="${state_device%%[*}"
[[ "$(findmnt -n -o TARGET --target "$DATA_ROOT")" == "$DATA_ROOT" && "$state_device" == /dev/sdb ]] ||
	die "Le journal Release A doit être porté par le mountpoint /dev/sdb"

# `status` is deliberately handled before mkdir/chmod/flock/helper staging or
# interrupted PostgreSQL cleanup.  It is a strictly read-only inspection path.
if [[ "$MODE" == status ]]; then
	exec python3 -I - "$STATE_ROOT" "$DEPLOYMENT_ID" "$LIVE_SHA" "$RELEASE_A_SHA" "$BRANCH" <<'PY'
import os,re,stat,sys
from pathlib import Path
root=Path(sys.argv[1]); deployment_id,live_sha,release_a_sha,branch=sys.argv[2:]
deployment=root/deployment_id; metadata=deployment/"metadata.tsv"; phase_path=deployment/"phase"
for path,label in ((root,"state root"),(deployment,"deployment directory")):
    value=path.lstat()
    if not stat.S_ISDIR(value.st_mode) or stat.S_ISLNK(value.st_mode): raise SystemExit(f"unsafe {label}")
for path,label in ((metadata,"metadata"),(phase_path,"phase")):
    value=path.lstat()
    if not stat.S_ISREG(value.st_mode) or stat.S_ISLNK(value.st_mode) or value.st_nlink!=1 or value.st_uid!=os.getuid() or stat.S_IMODE(value.st_mode)!=0o600:
        raise SystemExit(f"unsafe Release A {label}")
rows={}
for line in metadata.read_text(encoding="utf-8").splitlines():
    fields=line.split("\t")
    if len(fields)!=2 or fields[0] in rows: raise SystemExit("invalid Release A metadata")
    rows[fields[0]]=fields[1]
if rows.get("deployment_id")!=deployment_id or rows.get("live_sha")!=live_sha or rows.get("release_a_sha")!=release_a_sha or rows.get("candidate_sha")!=release_a_sha or rows.get("branch")!=branch:
    raise SystemExit("Release A status identity differs")
phase=phase_path.read_text(encoding="utf-8").strip()
allowed={"preflight_ok","prepared","closing_intent","maintenance_closed","adopting","validation_pending","sftp_canary_pending","sftp_canary_active_recorded","sftp_canary_recorded","opening_forward","opened","completed","sftp_identity_invalidated","rollback_closing","rollback_restoring","rollback_opening","rolled_back"}
if phase not in allowed or not re.fullmatch(r"[a-z_]+",phase): raise SystemExit("invalid Release A phase")
if phase=="sftp_identity_invalidated":
    invalidation=deployment/"sftp-runtime-identity-invalidation.json"
    row=invalidation.lstat()
    if stat.S_ISLNK(row.st_mode) or not stat.S_ISREG(row.st_mode) or row.st_nlink!=1 or row.st_uid!=os.getuid() or stat.S_IMODE(row.st_mode)!=0o600:
        raise SystemExit("unsafe SFTP identity invalidation")
    import json
    payload=json.loads(invalidation.read_text(encoding="utf-8"))
    if payload.get("schema_version")!=1 or payload.get("kind")!="agentium-release-a-sftp-runtime-identity-invalidation" or payload.get("result")!="invalidated" or payload.get("deployment_id")!=deployment_id or payload.get("release_a_sha")!=release_a_sha or payload.get("recovery")!="new_deployment_id_required" or payload.get("automatic_rearm_allowed") is not False:
        raise SystemExit("invalid SFTP identity invalidation")
print(phase)
PY
fi

DEPLOY_HOME="$(getent passwd "$(id -u)" | awk -F: 'NR==1 {print $6} END {if (NR!=1) exit 1}')" || die "HOME opérateur non résolvable"
[[ "$DEPLOY_HOME" == /* && "$DEPLOY_HOME" != *..* && -d "$DEPLOY_HOME" ]] || die "HOME opérateur invalide"
export HOME="$DEPLOY_HOME"
export DOCKER_CONFIG="$DEPLOY_HOME/.docker"
assert_python_runtime
[[ -S /var/run/docker.sock ]] || die "Socket Docker local absent"
docker_socket_real="$(realpath -e /var/run/docker.sock)"
[[ "$docker_socket_real" == /run/docker.sock || "$docker_socket_real" == /var/run/docker.sock ]] || die "Socket Docker local redirigé vers un chemin inattendu"
[[ "$(stat -Lc '%u:%h' /var/run/docker.sock)" == 0:1 ]] || die "Identité du socket Docker local inattendue"

ensure_private_child_dir() {
	local parent="$1" name="$2" create="$3"
	python3 -I - "$parent" "$name" "$create" <<'PY'
import os, re, stat, sys
from pathlib import Path
parent=Path(sys.argv[1]); name=sys.argv[2]; create=sys.argv[3]=="1"
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}",name):
    raise SystemExit("unsafe private directory name")
before=parent.lstat()
if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
    raise SystemExit("private directory parent is not a real directory")
flags=os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_CLOEXEC",0)|getattr(os,"O_NOFOLLOW",0)
parent_fd=os.open(parent,flags)
try:
    opened=os.fstat(parent_fd)
    if (opened.st_dev,opened.st_ino)!=(before.st_dev,before.st_ino):
        raise SystemExit("private directory parent changed")
    try:
        row=os.stat(name,dir_fd=parent_fd,follow_symlinks=False)
    except FileNotFoundError:
        if not create:
            raise SystemExit("required private directory is absent")
        os.mkdir(name,0o700,dir_fd=parent_fd)
        os.fsync(parent_fd)
        row=os.stat(name,dir_fd=parent_fd,follow_symlinks=False)
    if stat.S_ISLNK(row.st_mode) or not stat.S_ISDIR(row.st_mode):
        raise SystemExit("private directory is not a real directory")
    if row.st_uid!=os.geteuid() or stat.S_IMODE(row.st_mode)!=0o700 or row.st_nlink<2:
        raise SystemExit("private directory owner/mode/link identity differs")
    if row.st_dev!=opened.st_dev:
        raise SystemExit("private directory crossed a filesystem boundary")
    child_fd=os.open(name,flags,dir_fd=parent_fd)
    try:
        child=os.fstat(child_fd)
        if (child.st_dev,child.st_ino)!=(row.st_dev,row.st_ino):
            raise SystemExit("private directory changed while opening")
    finally:
        os.close(child_fd)
finally:
    os.close(parent_fd)
PY
}

if [[ -e "$STATE_ROOT" || -L "$STATE_ROOT" ]]; then
	ensure_private_child_dir "$DATA_ROOT" release-a-deployments 0
else
	[[ "$MODE" == preflight ]] || die "Journal Release A absent; commencer par preflight"
	ensure_private_child_dir "$DATA_ROOT" release-a-deployments 1
fi
[[ "$(findmnt -n -o TARGET --target "$STATE_ROOT")" == "$DATA_ROOT" ]] || die "Le journal Release A ne doit pas être un mountpoint distinct"
state_root_identity="$(stat -Lc '%d:%i' "$STATE_ROOT")"
exec 9<"$STATE_ROOT"
[[ "$(stat -Lc '%d:%i' "/proc/$$/fd/9")" == "$state_root_identity" && "$(stat -Lc '%d:%i' "$STATE_ROOT")" == "$state_root_identity" ]] || die "Journal Release A remplacé pendant le verrouillage"
flock -n 9 || die "Une transaction Release A est déjà active"

if [[ -e "$DEPLOY_DIR" || -L "$DEPLOY_DIR" ]]; then
	ensure_private_child_dir "$STATE_ROOT" "$DEPLOYMENT_ID" 0
else
	[[ "$MODE" == preflight ]] || die "Déploiement Release A absent; commencer par preflight"
	ensure_private_child_dir "$STATE_ROOT" "$DEPLOYMENT_ID" 1
fi
ensure_private_child_dir "$DEPLOY_DIR" rollback "$([[ "$MODE" == preflight ]] && printf 1 || printf 0)"
[[ "$(findmnt -n -o TARGET --target "$DEPLOY_DIR")" == "$DATA_ROOT" ]] || die "Le journal de déploiement a quitté /dev/sdb"

sudo_cmd() { if [[ "$(id -u)" -eq 0 ]]; then "$@"; else sudo "$@"; fi; }

durable_replace() {
	local temporary="$1" target="$2"
	python3 -I - "$temporary" "$target" <<'PY'
import os, stat, sys
from pathlib import Path
source, target = map(Path, sys.argv[1:])
st = source.lstat()
if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
    raise SystemExit("unsafe temporary file")
os.chmod(source, 0o600)
with source.open("rb") as handle:
    os.fsync(handle.fileno())
os.replace(source, target)
directory = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(directory)
finally:
    os.close(directory)
PY
}

atomic_text() {
	local target="$1" value="$2" temporary
	temporary="$DEPLOY_DIR/.${target##*/}.$$"
	printf '%s\n' "$value" >"$temporary"
	durable_replace "$temporary" "$target"
}

phase() { [[ -s "$PHASE_FILE" ]] && cat "$PHASE_FILE" || printf 'new\n'; }
set_phase() {
	local next="$1" current
	[[ "$next" =~ ^[a-z_]+$ ]] || die "Phase Release A invalide"
	if [[ -e "$PHASE_FILE" || -L "$PHASE_FILE" ]]; then assert_private "$PHASE_FILE"; fi
	current="$(phase)"
	[[ "$current" == "$next" ]] && return
	case "$current:$next" in
	new:preflight_ok | \
		preflight_ok:prepared | \
		prepared:closing_intent | \
		closing_intent:maintenance_closed | \
		maintenance_closed:adopting | \
		adopting:validation_pending | \
		validation_pending:sftp_canary_pending | \
		sftp_canary_pending:sftp_canary_active_recorded | \
		sftp_canary_active_recorded:sftp_canary_recorded | \
		sftp_canary_recorded:opening_forward | \
		opening_forward:completed | \
		opened:completed | \
		validation_pending:sftp_identity_invalidated | \
		sftp_canary_pending:sftp_identity_invalidated | \
		sftp_canary_active_recorded:sftp_identity_invalidated | \
		sftp_canary_recorded:sftp_identity_invalidated | \
		opening_forward:sftp_identity_invalidated | \
		opened:sftp_identity_invalidated | \
		completed:sftp_identity_invalidated | \
		prepared:rolled_back | \
		closing_intent:rollback_closing | \
		maintenance_closed:rollback_closing | \
		adopting:rollback_closing | \
		validation_pending:rollback_closing | \
		sftp_canary_pending:rollback_closing | \
		sftp_canary_active_recorded:rollback_closing | \
		sftp_canary_recorded:rollback_closing | \
		rollback_closing:rollback_restoring | \
		rollback_restoring:rollback_opening | \
		rollback_opening:rolled_back) ;;
	*) die "Transition Release A interdite: $current -> $next" ;;
	esac
	atomic_text "$PHASE_FILE" "$next"
}
metadata() { awk -F '\t' -v key="$1" '$1 == key {print $2; exit}' "$METADATA_FILE"; }

assert_private() {
	[[ -f "$1" && ! -L "$1" && "$(stat -c '%a:%u:%h' "$1")" == "600:$(id -u):1" ]] ||
		die "Artefact privé non sûr: $1"
}

assert_private_source() {
	local attributes
	[[ -f "$1" && ! -L "$1" ]] || die "Source privée non sûre: $1"
	attributes="$(stat -c '%a:%u:%h' "$1")"
	[[ "$attributes" == "400:$(id -u):1" || "$attributes" == "600:$(id -u):1" ]] ||
		die "Source privée non sûre (0400 ou 0600 requis): $1"
}

copy_private_once() {
	local source="$1" target="$2" expected="$3" temporary
	temporary="$DEPLOY_DIR/.${target##*/}.$$"
	[[ "$source" == /* && "$source" != *..* ]] || die "Source privée invalide"
	[[ "$expected" =~ ^[0-9a-f]{64}$ ]] || die "Digest privé invalide"
	assert_private_source "$source"
	[[ "$(sha256sum "$source" | awk '{print $1}')" == "$expected" ]] || die "Digest source privée différent"
	if [[ -e "$target" || -L "$target" ]]; then
		assert_private "$target"
		[[ "$(sha256sum "$target" | awk '{print $1}')" == "$expected" ]] || die "Artefact figé divergent"
		return
	fi
	install -m 0600 "$source" "$temporary"
	[[ "$(sha256sum "$temporary" | awk '{print $1}')" == "$expected" ]] || die "Copie privée altérée"
	durable_replace "$temporary" "$target"
}

stage_git_file() {
	local source="$1" target="$2" blob temporary
	temporary="$DEPLOY_DIR/.${target##*/}.$$"
	blob="$(git -C "$CANDIDATE_REPO" rev-parse "${RELEASE_A_SHA}:${source}")"
	if [[ -e "$target" || -L "$target" ]]; then
		[[ -f "$target" && ! -L "$target" && "$(git hash-object "$target")" == "$blob" ]] || die "Helper figé divergent: $source"
		chmod 0700 "$target"
		return
	fi
	git -C "$CANDIDATE_REPO" show "${RELEASE_A_SHA}:${source}" >"$temporary"
	[[ "$(git hash-object "$temporary")" == "$blob" ]] || die "Extraction Git altérée: $source"
	chmod 0700 "$temporary"
	durable_replace "$temporary" "$target"
	chmod 0700 "$target"
}

stage_helpers() {
	stage_git_file scripts/deploy-agentium-release-a-safe.sh "$FROZEN_EXECUTOR"
	stage_git_file scripts/agentium_release_a_manifest.py "$FROZEN_MANIFEST_HELPER"
	stage_git_file scripts/agentium_release_a_preconditions.py "$FROZEN_PRECONDITIONS_HELPER"
	stage_git_file scripts/agentium_release_a_attestation.py "$FROZEN_ATTESTATION_HELPER"
	stage_git_file scripts/agentium_release_a_evidence_bundle.py "$FROZEN_EVIDENCE_HELPER"
	stage_git_file config/agentium/release-a-evidence-authorities.v1.json "$FROZEN_EVIDENCE_AUTHORITY_KEYRING"
	chmod 0600 "$FROZEN_EVIDENCE_AUTHORITY_KEYRING"
	stage_git_file scripts/agentium_runtime_env_bundle.py "$FROZEN_ENV_HELPER"
	stage_git_file scripts/agentium_storage_attestation.py "$FROZEN_STORAGE_HELPER"
	stage_git_file scripts/agentium_release_a_storage_contract.py "$FROZEN_STORAGE_CONTRACT_HELPER"
	stage_git_file backend/scripts/audit_livekit_quiescence.py "$FROZEN_LIVEKIT_AUDIT"
	stage_git_file backend/scripts/audit_post_canary_database.py "$FROZEN_POSTGRES_AUDIT"
	stage_git_file backend/scripts/audit_sftp_deploy_boundary.py "$FROZEN_SFTP_BOUNDARY_AUDIT"
	stage_git_file scripts/agentium_release_a_sftp_positive_canary.py "$FROZEN_SFTP_POSITIVE_GATE"
	stage_git_file scripts/agentium-maintenance-gate.sh "$FROZEN_GATE_HELPER"
	stage_git_file scripts/deploy-vm.sh "$FROZEN_DEPLOYER"
	stage_git_file deploy/install-backend-service.sh "$FROZEN_SYSTEMD_INSTALLER"
	stage_git_file deploy/agentium-backend.service "$FROZEN_SYSTEMD_UNIT"
	stage_git_file deploy/nginx/agentium-container-frontend.conf "$FROZEN_NGINX_SITE"
	stage_git_file deploy/nginx/agentium-deploy-maintenance.conf "$FROZEN_NGINX_SNIPPET"
	stage_git_file docker/compose.agentium.qdrant-barrier.yml "$FROZEN_QDRANT_OVERRIDE"
	stage_git_file docker/compose.agentium.opened.yml "$FROZEN_OPENED_OVERRIDE"
	stage_git_file docker/compose.agentium.audit-readonly.yml "$FROZEN_AUDIT_OVERRIDE"
}

assert_candidate_worktree() {
	[[ -d "$CANDIDATE_REPO" && ! -L "$CANDIDATE_REPO" ]] || die "Worktree candidat absent"
	[[ "$(git -C "$CANDIDATE_REPO" rev-parse --show-toplevel)" == "$CANDIDATE_REPO" ]] || die "--candidate-repo doit être la racine exacte"
	[[ "$(git -C "$CANDIDATE_REPO" rev-parse HEAD)" == "$RELEASE_A_SHA" ]] || die "HEAD worktree différent de Release A"
	[[ -z "$(git -C "$CANDIDATE_REPO" status --porcelain --untracked-files=all)" ]] || die "Worktree Release A sale"
	git -C "$CANDIDATE_REPO" merge-base --is-ancestor "$LIVE_SHA" "$RELEASE_A_SHA" || die "Release A ne descend pas du SHA live"
	[[ -z "$(git -C "$CANDIDATE_REPO" diff --name-only "$LIVE_SHA" "$RELEASE_A_SHA" -- backend/alembic frontend-ng/src/app backend/app/models)" ]] ||
		die "Migration, modèle ou produit frontend interdit en Release A"
	[[ -z "$(git -C "$CANDIDATE_REPO" diff --name-only "$LIVE_SHA" "$RELEASE_A_SHA" | grep -Ei '(^|/)(seed|backfill|bootstrap)' || true)" ]] ||
		die "Seed/backfill/bootstrap interdit en Release A"
}

assert_remote_release_a() {
	local remote_sha
	remote_sha="$(git -C "$CANDIDATE_REPO" ls-remote --exit-code origin "refs/heads/$BRANCH" | awk 'NR==1 {print $1} END {if (NR!=1) exit 1}')" || die "Branche distante $BRANCH non attestable"
	[[ "$remote_sha" == "$RELEASE_A_SHA" ]] || die "$BRANCH distante doit rester exactement sur Release A jusqu'à completed"
}

assert_live_identity() {
	local bytecode
	[[ "$(git -C "$LIVE_REPO" rev-parse HEAD)" == "$LIVE_SHA" ]] || die "Checkout live différent du SHA déclaré"
	[[ -z "$(git -C "$LIVE_REPO" status --porcelain --untracked-files=all)" ]] || die "Checkout VM sale; logs et bytecode doivent être hors du dépôt"
	bytecode="$(find "$LIVE_REPO/backend" -path "$LIVE_REPO/backend/.venv" -prune -o -type f -name '*.pyc' -print -quit)" || die "Bytecode Python hôte non auditable"
	[[ -z "$bytecode" ]] || die "Bytecode Python hôte interdit hors .venv; purger les caches avant Release A"
	for service in agentium-pg agentium-rabbitmq qdrant agentium-minio agentium-backend agentium-frontend agentium-worker-cpu agentium-sftp; do
		docker inspect "$service" >/dev/null 2>&1 || die "Conteneur live absent: $service"
	done
	for service in agentium-pg agentium-rabbitmq qdrant agentium-minio; do
		[[ "$(docker inspect --format '{{.State.Running}}' "$service")" == true ]] || die "Service stateful arrêté: $service"
	done
	for service in agentium-backend agentium-worker-cpu agentium-p4-maintenance agentium-sftp agentium-livekit agentium-livekit-agent agentium-kc; do
		docker inspect "$service" >/dev/null 2>&1 || continue
		[[ "$(docker inspect --format '{{.State.Paused}}' "$service")" == false ]] || die "$service est déjà en pause hors transaction"
	done
	if sudo_cmd systemctl cat agentium-sftp.service >/dev/null 2>&1; then
		[[ "$(sudo_cmd systemctl is-active agentium-sftp.service 2>/dev/null || true)" != active && "$(sudo_cmd systemctl is-enabled agentium-sftp.service 2>/dev/null || true)" != enabled ]] || die "Daemon SFTP systemd historique doit être inactive+disabled avant Release A"
	fi
	if sudo_cmd systemctl list-unit-files 'agentium-*.socket' --no-legend 2>/dev/null | awk '$2=="enabled" {found=1} END{exit !found}'; then die "Socket systemd Agentium activable détecté"; fi
}

assert_capacity_mount() {
	local path="$1" expected="$2" minimum="$3" source target total available total_inodes available_inodes required
	source="$(findmnt -n -o SOURCE --target "$path")"
	target="$(findmnt -n -o TARGET --target "$path")"
	read -r total available < <(df -B1 --output=size,avail "$path" | awk 'NR == 2 {print $1, $2}')
	read -r total_inodes available_inodes < <(df --output=itotal,iavail "$path" | awk 'NR == 2 {print $1, $2}')
	required=$(( (total + 9) / 10 ))
	(( required < minimum )) && required="$minimum"
	[[ "$source" == "$expected" && "$target" == "$path" ]] || die "$path doit être le mountpoint exact $expected"
	[[ "$total" =~ ^[0-9]+$ && "$available" =~ ^[0-9]+$ && "$available" -ge "$required" ]] || die "$path sous max(seuil fixe, 10% libre)"
	[[ "$total_inodes" =~ ^[0-9]+$ && "$available_inodes" =~ ^[0-9]+$ && "$available_inodes" -ge $(( (total_inodes + 9) / 10 )) ]] || die "$path sous 10% d'inodes libres"
}

assert_capacity_and_mounts() {
	local spec service destination device source mounted_source
	assert_capacity_mount / /dev/sda1 "$MIN_ROOT_FREE_BYTES"
	assert_capacity_mount "$DATA_ROOT" /dev/sdb "$MIN_DATA_FREE_BYTES"
	assert_capacity_mount "$SECURE_DEPOSIT" /dev/sdc "$MIN_SECURE_FREE_BYTES"
	[[ "$(stat -c %d /)" != "$(stat -c %d "$DATA_ROOT")" && "$(stat -c %d /)" != "$(stat -c %d "$SECURE_DEPOSIT")" && "$(stat -c %d "$DATA_ROOT")" != "$(stat -c %d "$SECURE_DEPOSIT")" ]] || die "Les trois filesystems doivent être distincts"
	for spec in \
		'qdrant:/qdrant/storage:/dev/sdb' \
		'qdrant:/qdrant/snapshots:/dev/sdb' \
		'agentium-minio:/data:/dev/sdb' \
		'agentium-pg:/var/lib/postgresql/data:/dev/sda1' \
		'agentium-rabbitmq:/var/lib/rabbitmq:/dev/sda1' \
		'agentium-backend:/data/object_store:/dev/sdb' \
		'agentium-backend:/data/secure_deposit:/dev/sdc' \
		'agentium-backend:/data/faiss_db:/dev/sda1' \
		'agentium-worker-cpu:/data/object_store:/dev/sdb' \
		'agentium-worker-cpu:/data/secure_deposit:/dev/sdc' \
		'agentium-worker-cpu:/data/faiss_db:/dev/sda1' \
		'agentium-p4-maintenance:/data/object_store:/dev/sdb' \
		'agentium-p4-maintenance:/data/secure_deposit:/dev/sdc' \
		'agentium-p4-maintenance:/data/faiss_db:/dev/sda1' \
		'agentium-sftp:/data/secure_deposit:/dev/sdc'; do
		IFS=: read -r service destination device <<<"$spec"
		source="$(docker inspect --format "{{range .Mounts}}{{if eq .Destination \"$destination\"}}{{.Source}}{{end}}{{end}}" "$service")"
		[[ "$source" == /* && -e "$source" ]] || die "$service:$destination n'a pas de source hôte attestable"
		mounted_source="$(findmnt -n -o SOURCE --target "$source")"
		mounted_source="${mounted_source%%[*}"
		[[ -n "$source" && "$mounted_source" == "$device" ]] || die "$service:$destination n'est pas sur $device"
	done
}

env_value() {
	"$FROZEN_ENV_HELPER" value --bundle-dir "$RUNTIME_ENV_DIR" --sha "$RELEASE_A_SHA" \
		--deployment-id "$DEPLOYMENT_ID" --expected-manifest-sha256 "$ENV_DIGEST" --role "$1" --key "$2"
}

verify_env_bundle() {
	ENV_DIGEST="$(metadata env_manifest_sha256)"
	[[ "$ENV_DIGEST" =~ ^[0-9a-f]{64}$ ]] || die "Digest env absent"
	"$FROZEN_ENV_HELPER" verify --bundle-dir "$RUNTIME_ENV_DIR" --sha "$RELEASE_A_SHA" \
		--deployment-id "$DEPLOYMENT_ID" --expected-manifest-sha256 "$ENV_DIGEST" >/dev/null
}

assert_runtime_source_tree() {
	[[ "$RUNTIME_ENV_SOURCE_ROOT" == /* && "$RUNTIME_ENV_SOURCE_ROOT" != *..* && -d "$RUNTIME_ENV_SOURCE_ROOT" && ! -L "$RUNTIME_ENV_SOURCE_ROOT" ]] || die "Miroir env privé invalide"
	case "$(realpath -e "$RUNTIME_ENV_SOURCE_ROOT")" in
	"$(realpath -e "$LIVE_REPO")"/* | "$(realpath -e "$CANDIDATE_REPO")"/* | "$(realpath -m "$STATE_ROOT")"/*) die "Le miroir env doit être indépendant du code et du journal" ;;
	esac
	for source in docker/env/agentium.vm.env docker/env/agentium.env docker/env/qdrant.agentium.env docker/env/keycloak.agentium.env backend/.env; do
		assert_private_source "$RUNTIME_ENV_SOURCE_ROOT/$source"
	done
}

verify_immutable_runtime_credentials() {
	local main_env keycloak_env
	main_env="$("$FROZEN_ENV_HELPER" role-path --bundle-dir "$RUNTIME_ENV_DIR" --sha "$RELEASE_A_SHA" --deployment-id "$DEPLOYMENT_ID" --expected-manifest-sha256 "$ENV_DIGEST" --role compose_main)"
	keycloak_env="$("$FROZEN_ENV_HELPER" role-path --bundle-dir "$RUNTIME_ENV_DIR" --sha "$RELEASE_A_SHA" --deployment-id "$DEPLOYMENT_ID" --expected-manifest-sha256 "$ENV_DIGEST" --role keycloak)"
	python3 -I - "$main_env" "$keycloak_env" <<'PY'
import json,re,subprocess,sys
from pathlib import Path
def dotenv(path):
    result={}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        key,sep,value=raw.strip().partition("=")
        if sep and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",key):
            if len(value)>=2 and value[0]==value[-1] and value[0] in "\"'": value=value[1:-1]
            result[key]=value
    return result
def container_env(name):
    proc=subprocess.run(["docker","inspect","--type","container",name],check=True,capture_output=True,text=True,timeout=30)
    rows=json.loads(proc.stdout)
    if not isinstance(rows,list) or len(rows)!=1: raise SystemExit("runtime identity unavailable")
    result={}
    for item in rows[0].get("Config",{}).get("Env",[]):
        key,sep,value=item.partition("=")
        if sep: result[key]=value
    return result
main,keycloak=dotenv(sys.argv[1]),dotenv(sys.argv[2])
pg=container_env("agentium-pg"); minio=container_env("agentium-minio"); kc=container_env("agentium-kc")
for key in ("AGENTIUM_POSTGRES_DB","AGENTIUM_POSTGRES_USER","AGENTIUM_POSTGRES_PASSWORD"):
    runtime_key=key.removeprefix("AGENTIUM_")
    if not main.get(key) or main[key]!=pg.get(runtime_key): raise SystemExit("PostgreSQL immutable identity differs")
for key in ("AGENTIUM_MINIO_ROOT_USER","AGENTIUM_MINIO_ROOT_PASSWORD"):
    runtime_key=key.removeprefix("AGENTIUM_")
    if not main.get(key) or main[key]!=minio.get(runtime_key): raise SystemExit("MinIO root immutable identity differs")
for key in ("KC_DB","KC_DB_URL","KC_DB_USERNAME","KC_DB_PASSWORD"):
    if not keycloak.get(key) or keycloak[key]!=kc.get(key): raise SystemExit("Keycloak database identity differs")
PY
}

assert_new_principals_absent() {
	local suffix rabbit_user minio_user
	suffix="$(printf %s "$DEPLOYMENT_ID" | sha256sum | cut -c1-24)"
	rabbit_user="$(env_value compose_main AGENTIUM_RABBITMQ_USER)"
	minio_user="$(env_value application OBJECT_STORE_S3_ACCESS_KEY)"
	[[ "$rabbit_user" == "agentium_ra_$suffix" ]] || die "Principal RabbitMQ doit être réservé au deployment-id"
	[[ "$minio_user" == "agentium-ra-$suffix" ]] || die "Principal MinIO doit être réservé au deployment-id"
	docker exec agentium-rabbitmq rabbitmqctl list_users --formatter json |
		python3 -I -c 'import json,sys; name=sys.argv[1]; rows=json.load(sys.stdin); raise SystemExit(1 if any(row.get("user")==name for row in rows) else 0)' "$rabbit_user" || die "Principal RabbitMQ candidat existe déjà hors transaction"
	compose --profile tools run --rm --no-deps --entrypoint /bin/sh agentium-minio-init -ec '
		mc alias set agentium http://agentium-minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
		! mc admin user info agentium "$MINIO_APP_ACCESS_KEY" >/dev/null 2>&1
		! mc admin policy info agentium "$MINIO_APP_POLICY" >/dev/null 2>&1
	' || die "Principal/policy MinIO candidat existe déjà hors transaction"
}

assert_metadata() {
	assert_private "$METADATA_FILE"
	python3 -I - "$METADATA_FILE" "$DEPLOYMENT_ID" "$LIVE_SHA" "$RELEASE_A_SHA" "$BRANCH" <<'PY'
import re, sys
from pathlib import Path
rows = {}
for line in Path(sys.argv[1]).read_text().splitlines():
    fields = line.split("\t")
    if len(fields) != 2 or fields[0] in rows:
        raise SystemExit("invalid Release A metadata")
    rows[fields[0]] = fields[1]
expected = {"format","deployment_id","branch","live_sha","release_a_sha","candidate_sha","sftp_release_sha","sftp_image_id","docker_engine_id","env_manifest_sha256","manifest_sha256","review_policy_sha256","preconditions_sha256","evidence_authority_keyring_sha256","manifest_receipt_sha256","preconditions_receipt_sha256","preconditions_evidence_receipt_sha256","created_at"}
if set(rows) != expected or rows["format"] != "2":
    raise SystemExit("Release A metadata schema differs")
if rows["deployment_id"] != sys.argv[2] or rows["live_sha"] != sys.argv[3] or rows["release_a_sha"] != sys.argv[4] or rows["candidate_sha"] != sys.argv[4]:
    raise SystemExit("Release A metadata identity differs")
if rows["branch"] != sys.argv[5]:
    raise SystemExit("Release A branch differs from the requested branch")
for key in ("env_manifest_sha256","manifest_sha256","review_policy_sha256","preconditions_sha256","evidence_authority_keyring_sha256","manifest_receipt_sha256","preconditions_receipt_sha256","preconditions_evidence_receipt_sha256"):
    if re.fullmatch(r"[0-9a-f]{64}", rows[key]) is None:
        raise SystemExit("Release A metadata digest invalid")
if re.fullmatch(r"sha256:[0-9a-f]{64}", rows["sftp_image_id"]) is None or re.fullmatch(r"[0-9a-f]{40}", rows["sftp_release_sha"]) is None:
    raise SystemExit("Release A SFTP identity invalid")
if re.fullmatch(r"[A-Za-z0-9:_-]{8,128}", rows["docker_engine_id"]) is None:
    raise SystemExit("Release A Docker engine identity invalid")
PY
	[[ "$(docker info --format '{{.ID}}')" == "$(metadata docker_engine_id)" ]] || die "Daemon Docker local différent de celui du preflight"
	verify_env_bundle
	[[ "$(sha256sum "$FROZEN_MANIFEST" | awk '{print $1}')" == "$(metadata manifest_sha256)" ]] || die "Manifeste figé divergent"
	[[ "$(sha256sum "$FROZEN_REVIEW" | awk '{print $1}')" == "$(metadata review_policy_sha256)" ]] || die "Revue figée divergente"
	[[ "$(sha256sum "$FROZEN_PRECONDITIONS" | awk '{print $1}')" == "$(metadata preconditions_sha256)" ]] || die "Préconditions figées divergentes"
	assert_private "$FROZEN_EVIDENCE_AUTHORITY_KEYRING"
	[[ "$(sha256sum "$FROZEN_EVIDENCE_AUTHORITY_KEYRING" | awk '{print $1}')" == "$(metadata evidence_authority_keyring_sha256)" ]] || die "Keyring d'autorité de preuves divergent"
	assert_private "$PRECONDITIONS_EVIDENCE_RECEIPT"
	[[ "$(sha256sum "$PRECONDITIONS_EVIDENCE_RECEIPT" | awk '{print $1}')" == "$(metadata preconditions_evidence_receipt_sha256)" ]] || die "Reçu de preuves préconditions divergent"
}

gate() {
	local purpose="${2:-}" authorization="${3:-}"
	env -i PATH="$COMPOSE_CLEAN_PATH" HOME="$DEPLOY_HOME" \
		OMNIRAG_REPO_DIR="$LIVE_REPO" AGENTIUM_SAFE_DEPLOY_ORCHESTRATED=1 \
		AGENTIUM_SAFE_DEPLOYMENT_DIR="$DEPLOY_DIR" AGENTIUM_SAFE_DEPLOYMENT_ID="$DEPLOYMENT_ID" \
		AGENTIUM_SAFE_GATE_PURPOSE="$purpose" AGENTIUM_SAFE_GATE_AUTHORIZATION="$authorization" \
		AGENTIUM_SAFE_GATE_LOCK_FD=9 AGENTIUM_NGINX_SITE_SOURCE="$FROZEN_NGINX_SITE" \
		AGENTIUM_MAINTENANCE_SNIPPET_SOURCE="$FROZEN_NGINX_SNIPPET" "$FROZEN_GATE_HELPER" "$1"
}

assert_nginx_unique_edge_topology() {
	local dump sockets suspicious
	dump="$(sudo_cmd nginx -T 2>&1)" || die "nginx -T a échoué"
	[[ "$dump" != *"real_ip_header"* && "$dump" != *"set_real_ip_from"* && "$dump" != *"proxy_protocol"* ]] ||
		die "Nginx réécrit l'identité source; bypass canari loopback non attestable"
	sockets="$(sudo_cmd ss -H -ltnp | awk '$4 ~ /:(80|443)$/ {print}')"
	[[ -n "$sockets" ]] || die "Nginx n'écoute pas sur les ports edge attendus"
	while IFS= read -r row; do
		[[ "$row" == *'users:(("nginx"'* ]] || die "Un processus non-Nginx partage un port edge"
	done <<<"$sockets"
	suspicious="$(sudo_cmd ps -eo args= | grep -E '(^|[ /])(socat|rinetd|ngrok|cloudflared|frpc)([[:space:]]|$)|ssh([^[:alnum:]]|$).*(-R|-L)[[:space:]]' | grep -vE 'grep -E|deploy-agentium-release-a-safe' || true)"
	[[ -z "$suspicious" ]] || die "Proxy ou tunnel local susceptible de contourner le gate Nginx"
	python3 -I - /etc/nginx/sites-enabled/agentium 3< <(printf '%s\n' "$dump") <<'PY' || die "Un vhost Nginx secondaire peut contourner le gate Agentium"
import os,re,sys
site=os.path.abspath(sys.argv[1]); allowed={site,os.path.realpath(site)}
current=None; violations=[]
header=re.compile(r"^# configuration file (.+):$")
directive=re.compile(r"\b(?:proxy_pass|grpc_pass|fastcgi_pass|uwsgi_pass)\s+([^;]+)")
protected=re.compile(r"(?::|%3a)(?:7880|8000|8001|8080|8081)\b|\b(?:agentium-(?:backend|frontend|kc|livekit)|qdrant|agentium-minio)\b",re.I)
with os.fdopen(3,encoding="utf-8",errors="strict") as stream:
    for number,raw in enumerate(stream,start=1):
        match=header.match(raw.rstrip("\n"))
        if match:
            current=os.path.abspath(match.group(1)); continue
        code=raw.split("#",1)[0]
        if current not in allowed:
            if re.search(r"\bserver_name\b[^;]*\bagentium\.papai\.ai\b",code): violations.append((current,number,"duplicate Agentium server_name"))
            target=directive.search(code)
            if target and protected.search(target.group(1)): violations.append((current,number,"protected upstream outside canonical site"))
            if re.search(r"\bserver\s+[^;]+",code) and protected.search(code): violations.append((current,number,"protected upstream alias outside canonical site"))
if violations:
    for filename,line,reason in violations: print(f"{filename or '<unknown>'}:{line}: {reason}",file=sys.stderr)
    raise SystemExit(1)
PY
}

compose() {
	local qdrant_key probe_key policy_name
	assert_candidate_worktree
	qdrant_key="$(env_value application QDRANT_API_KEY)"
	probe_key=".agentium-release-a-$(printf %s "$DEPLOYMENT_ID" | sha256sum | cut -c1-24)"
	policy_name="agentium-release-a-$(printf %s "$DEPLOYMENT_ID" | sha256sum | cut -c1-24)"
	(
		cd "$CANDIDATE_REPO/docker"
		env -i PATH="$COMPOSE_CLEAN_PATH" HOME="$DEPLOY_HOME" DOCKER_CONFIG="$DEPLOY_HOME/.docker" DOCKER_HOST="$DOCKER_LOCAL_HOST" \
			AGENTIUM_QDRANT_EFFECTIVE_API_KEY="$qdrant_key" AGENTIUM_RELEASE_A_MINIO_PROBE_KEY="$probe_key" AGENTIUM_RELEASE_A_MINIO_POLICY_NAME="$policy_name" AGENTIUM_CELERY_BEAT=0 AGENTIUM_STARTUP_RECONCILIATION=disabled \
			docker compose --env-file "$RUNTIME_ENV_DIR/compose.effective.env" -f compose.agentium.yml -f "$FROZEN_QDRANT_OVERRIDE" "$@"
	)
}

compose_opened() {
	local qdrant_env admin_key
	assert_candidate_worktree
	assert_candidate_image_override
	qdrant_env="$("$FROZEN_ENV_HELPER" role-path --bundle-dir "$RUNTIME_ENV_DIR" --sha "$RELEASE_A_SHA" --deployment-id "$DEPLOYMENT_ID" --expected-manifest-sha256 "$ENV_DIGEST" --role qdrant)"
	admin_key="$(python3 -I - "$qdrant_env" <<'PY'
import re,sys
from pathlib import Path
values={}
for raw in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    key,sep,value=raw.strip().partition("=")
    if sep and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",key):
        if len(value)>=2 and value[0]==value[-1] and value[0] in "\"'": value=value[1:-1]
        values[key]=value
value=values.get("QDRANT__SERVICE__API_KEY","")
if len(value)<32: raise SystemExit("Qdrant admin key missing")
print(value)
PY
)"
	(
		cd "$CANDIDATE_REPO/docker"
		env -i PATH="$COMPOSE_CLEAN_PATH" HOME="$DEPLOY_HOME" DOCKER_CONFIG="$DEPLOY_HOME/.docker" DOCKER_HOST="$DOCKER_LOCAL_HOST" \
			AGENTIUM_QDRANT_EFFECTIVE_API_KEY="$admin_key" AGENTIUM_CELERY_BEAT=0 AGENTIUM_STARTUP_RECONCILIATION=disabled \
			docker compose --env-file "$RUNTIME_ENV_DIR/compose.effective.env" -f compose.agentium.yml -f "$FROZEN_OPENED_OVERRIDE" -f "$CANDIDATE_IMAGE_OVERRIDE" "$@"
	)
}

compose_audit() {
	compose -f "$FROZEN_AUDIT_OVERRIDE" "$@"
}

verify_candidate_storage_contract() {
	assert_candidate_worktree
	local temporary="$DEPLOY_DIR/.candidate-storage-contract.$$"
	compose config --format json | "$FROZEN_STORAGE_CONTRACT_HELPER" verify >"$temporary"
	if [[ -e "$CANDIDATE_STORAGE_CONTRACT" || -L "$CANDIDATE_STORAGE_CONTRACT" ]]; then
		assert_private "$CANDIDATE_STORAGE_CONTRACT"
		cmp -s "$temporary" "$CANDIDATE_STORAGE_CONTRACT" || die "Contrat de stockage candidat divergent"
		rm -f "$temporary"
	else
		durable_replace "$temporary" "$CANDIDATE_STORAGE_CONTRACT"
	fi
	assert_private "$CANDIDATE_STORAGE_CONTRACT"
	python3 -I - "$CANDIDATE_STORAGE_CONTRACT" <<'PY'
import json,sys
p=json.load(open(sys.argv[1],encoding="utf-8"))
if set(p)!={"schema_version","kind","result","protected_service_count","mount_count","contract_sha256","mounts"}:
    raise SystemExit("storage contract receipt schema differs")
if p["schema_version"]!=1 or p["kind"]!="agentium-release-a-candidate-storage-contract" or p["result"]!="passed":
    raise SystemExit("storage contract receipt failed")
if p["protected_service_count"]!=9 or p["mount_count"]!=18:
    raise SystemExit("storage contract receipt cardinality differs")
PY
}

candidate_image_tag() {
	local tag
	tag="$(env_value compose_main AGENTIUM_IMAGE_TAG)"
	[[ "$tag" =~ ^[A-Za-z0-9_.-]+$ ]] || die "Tag OCI candidat invalide"
	printf '%s\n' "$tag"
}

assert_candidate_oci_receipt() {
	assert_private "$CANDIDATE_OCI_RECEIPT"
	local tag
	tag="$(candidate_image_tag)"
	python3 -I - "$CANDIDATE_OCI_RECEIPT" "$DEPLOYMENT_ID" "$RELEASE_A_SHA" "$(metadata docker_engine_id)" "$tag" <<'PY'
import json,re,subprocess,sys
from pathlib import Path

receipt=Path(sys.argv[1]); deployment_id,release_sha,engine_id,tag=sys.argv[2:]
p=json.loads(receipt.read_text(encoding="utf-8"))
expected_keys={"schema_version","kind","result","deployment_id","release_a_sha","docker_engine_id","images","captured_at"}
if set(p)!=expected_keys or p.get("schema_version")!=1 or p.get("kind")!="agentium-release-a-candidate-oci-receipt" or p.get("result")!="passed":
    raise SystemExit("candidate OCI receipt schema/result differs")
if p.get("deployment_id")!=deployment_id or p.get("release_a_sha")!=release_sha or p.get("docker_engine_id")!=engine_id:
    raise SystemExit("candidate OCI receipt identity differs")
actual_engine=subprocess.run(["docker","info","--format","{{.ID}}"],check=True,capture_output=True,text=True,timeout=30).stdout.strip()
if actual_engine!=engine_id:
    raise SystemExit("candidate OCI Docker engine differs")
refs={
    "agentium-backend":f"agentium-backend:{tag}",
    "agentium-frontend":f"agentium-frontend:{tag}",
    "agentium-worker-cpu":f"agentium-worker:{tag}",
}
images=p.get("images")
if not isinstance(images,list) or [row.get("service") for row in images]!=list(refs):
    raise SystemExit("candidate OCI receipt service set/order differs")
for row in images:
    if set(row)!={"service","image_ref","image_id","revision"}:
        raise SystemExit("candidate OCI receipt image schema differs")
    service=row["service"]; expected_ref=refs[service]
    if row.get("image_ref")!=expected_ref or re.fullmatch(r"sha256:[0-9a-f]{64}",str(row.get("image_id",""))) is None or row.get("revision")!=release_sha:
        raise SystemExit("candidate OCI receipt image identity differs")
    proc=subprocess.run(["docker","image","inspect",expected_ref],check=True,capture_output=True,text=True,timeout=30)
    inspected=json.loads(proc.stdout)
    if not isinstance(inspected,list) or len(inspected)!=1:
        raise SystemExit("candidate OCI tag inspection cardinality differs")
    image=inspected[0]; labels=(image.get("Config") or {}).get("Labels") or {}
    if image.get("Id")!=row["image_id"]:
        raise SystemExit(f"candidate OCI tag substituted for {service}")
    if labels.get("org.opencontainers.image.revision")!=release_sha:
        raise SystemExit(f"candidate OCI revision substituted for {service}")
    if expected_ref not in (image.get("RepoTags") or []):
        raise SystemExit(f"candidate OCI tag detached for {service}")
PY
}

candidate_service_image_id() {
	local service="$1"
	[[ "$service" == agentium-backend || "$service" == agentium-frontend || "$service" == agentium-worker-cpu ]] ||
		die "Service OCI candidat non autorisé"
	assert_candidate_oci_receipt
	python3 -I - "$CANDIDATE_OCI_RECEIPT" "$service" <<'PY'
import json,re,sys
from pathlib import Path
p=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
rows=[row for row in p.get("images",[]) if row.get("service")==sys.argv[2]]
if len(rows)!=1 or re.fullmatch(r"sha256:[0-9a-f]{64}",str(rows[0].get("image_id",""))) is None:
    raise SystemExit("candidate service image identity differs")
print(rows[0]["image_id"])
PY
}

capture_candidate_oci_receipt() {
	if [[ -e "$CANDIDATE_OCI_RECEIPT" || -L "$CANDIDATE_OCI_RECEIPT" ]]; then
		assert_candidate_oci_receipt
		return
	fi
	local tag temporary="$DEPLOY_DIR/.candidate-oci-receipt.$$"
	tag="$(candidate_image_tag)"
	[[ ! -e "$temporary" && ! -L "$temporary" ]] || die "Capture OCI candidate concurrente"
	python3 -I - "$temporary" "$DEPLOYMENT_ID" "$RELEASE_A_SHA" "$(metadata docker_engine_id)" "$tag" <<'PY'
import json,os,re,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path

out=Path(sys.argv[1]); deployment_id,release_sha,engine_id,tag=sys.argv[2:]
refs={
    "agentium-backend":f"agentium-backend:{tag}",
    "agentium-frontend":f"agentium-frontend:{tag}",
    "agentium-worker-cpu":f"agentium-worker:{tag}",
}
images=[]
for service,image_ref in refs.items():
    proc=subprocess.run(["docker","image","inspect",image_ref],check=True,capture_output=True,text=True,timeout=30)
    inspected=json.loads(proc.stdout)
    if not isinstance(inspected,list) or len(inspected)!=1:
        raise SystemExit("candidate OCI tag inspection cardinality differs")
    image=inspected[0]; image_id=str(image.get("Id","")).lower(); labels=(image.get("Config") or {}).get("Labels") or {}
    revision=str(labels.get("org.opencontainers.image.revision","")).lower()
    if re.fullmatch(r"sha256:[0-9a-f]{64}",image_id) is None or revision!=release_sha:
        raise SystemExit(f"candidate OCI image is not bound to Release A: {service}")
    if image_ref not in (image.get("RepoTags") or []):
        raise SystemExit(f"candidate OCI tag is not attached: {service}")
    images.append({"service":service,"image_ref":image_ref,"image_id":image_id,"revision":revision})
p={
    "schema_version":1,
    "kind":"agentium-release-a-candidate-oci-receipt",
    "result":"passed",
    "deployment_id":deployment_id,
    "release_a_sha":release_sha,
    "docker_engine_id":engine_id,
    "images":images,
    "captured_at":datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z"),
}
fd=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,"w") as handle:
    json.dump(p,handle,separators=(",",":"),sort_keys=True); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
PY
	durable_replace "$temporary" "$CANDIDATE_OCI_RECEIPT"
	assert_candidate_oci_receipt
}

candidate_image_override_contract() {
	local mode="$1" target="$2"
	[[ "$mode" == "write" || "$mode" == "verify" ]] || die "Mode override OCI candidat invalide"
	python3 -I - "$CANDIDATE_OCI_RECEIPT" "$target" "$DEPLOYMENT_ID" "$RELEASE_A_SHA" "$(metadata docker_engine_id)" "$mode" <<'PY'
import json
import os
import re
import stat
import sys
from pathlib import Path

receipt_path, target = map(Path, sys.argv[1:3])
deployment_id, release_sha, engine_id, mode = sys.argv[3:]
receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
expected_keys = {
    "schema_version", "kind", "result", "deployment_id", "release_a_sha",
    "docker_engine_id", "images", "captured_at",
}
if (
    not isinstance(receipt, dict)
    or set(receipt) != expected_keys
    or receipt.get("schema_version") != 1
    or receipt.get("kind") != "agentium-release-a-candidate-oci-receipt"
    or receipt.get("result") != "passed"
    or receipt.get("deployment_id") != deployment_id
    or receipt.get("release_a_sha") != release_sha
    or receipt.get("docker_engine_id") != engine_id
):
    raise SystemExit("candidate OCI receipt identity differs for image override")
services = ("agentium-backend", "agentium-frontend", "agentium-worker-cpu")
images = receipt.get("images")
if not isinstance(images, list) or [row.get("service") for row in images if isinstance(row, dict)] != list(services):
    raise SystemExit("candidate OCI image inventory differs for image override")
rows = {}
for row in images:
    if not isinstance(row, dict) or set(row) != {"service", "image_ref", "image_id", "revision"}:
        raise SystemExit("candidate OCI image row differs for image override")
    image_id = row.get("image_id")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", str(image_id)) is None or row.get("revision") != release_sha:
        raise SystemExit("candidate OCI image identity differs for image override")
    rows[row["service"]] = image_id
if set(rows) != set(services) or len(set(rows.values())) != len(services):
    raise SystemExit("candidate OCI image inventory is incomplete or aliased")
ordered = (*services, "agentium-p4-maintenance")
ids = {**rows, "agentium-p4-maintenance": rows["agentium-worker-cpu"]}
encoded = (
    "services:\n"
    + "".join(f"  {service}:\n    image: {ids[service]}\n" for service in ordered)
).encode("ascii")

if mode == "write":
    descriptor = os.open(
        target,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
elif mode == "verify":
    before = target.lstat()
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise SystemExit("candidate image override is not a regular file")
    descriptor = os.open(
        target,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        opened = os.fstat(descriptor)
        observed = os.read(descriptor, len(encoded) + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    linked = target.lstat()
    identity = lambda row: (
        row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns,
        row.st_uid, row.st_nlink, stat.S_IMODE(row.st_mode),
    )
    if identity(before) != identity(opened) or identity(opened) != identity(after) or identity(after) != identity(linked):
        raise SystemExit("candidate image override changed while read")
    if before.st_uid != os.geteuid() or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o600:
        raise SystemExit("candidate image override identity differs")
    if observed != encoded:
        raise SystemExit("candidate image override differs from OCI receipt")
else:
    raise SystemExit("candidate image override mode differs")
PY
}

assert_candidate_image_override() {
	assert_candidate_oci_receipt
	assert_private "$CANDIDATE_IMAGE_OVERRIDE"
	candidate_image_override_contract verify "$CANDIDATE_IMAGE_OVERRIDE"
}

ensure_candidate_image_override() {
	local temporary="$DEPLOY_DIR/.compose.agentium.candidate-images.$$"
	assert_candidate_oci_receipt
	if [[ -e "$CANDIDATE_IMAGE_OVERRIDE" || -L "$CANDIDATE_IMAGE_OVERRIDE" ]]; then
		assert_candidate_image_override
		return
	fi
	candidate_image_override_contract write "$temporary"
	durable_replace "$temporary" "$CANDIDATE_IMAGE_OVERRIDE"
	assert_candidate_image_override
}

record_file_backup() {
	local source="$1" backup="$2" attrs="$3" temporary
	temporary="$DEPLOY_DIR/.${backup##*/}.$$"
	if [[ -e "$backup" || -L "$backup" ]]; then assert_private "$backup"; assert_private "$attrs"; return; fi
	[[ -f "$source" && ! -L "$source" ]] || die "Fichier runtime absent: $source"
	install -m 0600 "$source" "$temporary"
	durable_replace "$temporary" "$backup"
	atomic_text "$attrs" "$(stat -c '%a:%u:%g:%h' "$source")"
}

keycloak_control_plane_contract() {
	local mode="$1" liveness="${2:-any}" expected_id="" expected_image="" expected_digest="" expected_port=""
	[[ "$mode" == snapshot || "$mode" == verify ]] || die "Mode contrat Keycloak invalide"
	[[ "$liveness" == any || "$liveness" == running || "$liveness" == stopped ]] ||
		die "État contrat Keycloak invalide"
	if [[ "$mode" == verify ]]; then
		read -r expected_id expected_image expected_digest expected_port < <(
			awk -F '\t' '$1=="keycloak_contract" && $2=="agentium-kc" {print $3, $4, $5, $6}' "$RUNTIME_STATE"
		)
		[[ "$expected_id" =~ ^[0-9a-f]{64}$ && "$expected_image" =~ ^sha256:[0-9a-f]{64}$ &&
			"$expected_digest" =~ ^[0-9a-f]{64}$ && "$expected_port" =~ ^[0-9]+$ ]] ||
			die "Contrat Keycloak historique absent ou invalide"
	fi
	python3 -I - "$mode" "$liveness" "$LIVE_REPO" "$expected_id" "$expected_image" "$expected_digest" "$expected_port" \
		3< <(docker inspect --type container agentium-kc agentium-pg) <<'PY'
import hashlib,json,os,re,stat,sys
from pathlib import Path

mode,liveness,live_repo,expected_id,expected_image,expected_digest,expected_port=sys.argv[1:]
try:
    rows=json.load(os.fdopen(3))
except (json.JSONDecodeError,UnicodeDecodeError) as exc:
    raise SystemExit("Keycloak inspect is invalid JSON") from exc
if not isinstance(rows,list) or len(rows)!=2 or any(not isinstance(row,dict) for row in rows):
    raise SystemExit("Keycloak/PostgreSQL container inventory differs")
by_name={str(row.get("Name") or "").removeprefix("/"):row for row in rows}
if set(by_name)!={"agentium-kc","agentium-pg"}:
    raise SystemExit("Keycloak/PostgreSQL container names differ")
kc=by_name["agentium-kc"]; pg=by_name["agentium-pg"]
container_id=str(kc.get("Id") or ""); image_id=str(kc.get("Image") or "")
if re.fullmatch(r"[0-9a-f]{64}",container_id) is None or re.fullmatch(r"sha256:[0-9a-f]{64}",image_id) is None:
    raise SystemExit("Keycloak immutable identity is invalid")
config=kc.get("Config") or {}; host=kc.get("HostConfig") or {}; state=kc.get("State") or {}
if config.get("Image")!="quay.io/keycloak/keycloak:26.1.4" or config.get("Cmd")!=["start-dev"]:
    raise SystemExit("Keycloak image/command differs")

labels=config.get("Labels") or {}
required_labels={
    "com.docker.compose.service":"agentium-kc",
    "com.docker.compose.oneoff":"False",
    "com.docker.compose.container-number":"1",
}
if any(labels.get(key)!=value for key,value in required_labels.items()):
    raise SystemExit("Keycloak compose identity differs")

env={}
for item in config.get("Env") or []:
    if not isinstance(item,str) or "=" not in item:
        raise SystemExit("Keycloak environment is malformed")
    key,value=item.split("=",1)
    if key in env:
        raise SystemExit("Keycloak environment is ambiguous")
    env[key]=value
required_env={
    "KC_DB":"postgres",
    "KC_HTTP_ENABLED":"true",
    "KC_HTTP_RELATIVE_PATH":"/kc",
    "KC_PROXY_HEADERS":"xforwarded",
    "KC_HEALTH_ENABLED":"true",
    "KC_RUN_IN_CONTAINER":"true",
}
if any(env.get(key)!=value for key,value in required_env.items()):
    raise SystemExit("Keycloak authoritative environment differs")
if not str(env.get("KC_DB_URL") or "").startswith("jdbc:postgresql://agentium-pg:5432/"):
    raise SystemExit("Keycloak database target differs")
if not env.get("KC_DB_USERNAME") or not env.get("KC_DB_PASSWORD") or env.get("KC_DB_PASSWORD")=="change-me":
    raise SystemExit("Keycloak database credentials are not production-grade")
if not re.fullmatch(r"https://[^/\s]+/kc",str(env.get("KC_HOSTNAME") or "")):
    raise SystemExit("Keycloak public hostname differs")
if any(key.startswith(("KEYCLOAK_ADMIN","KC_BOOTSTRAP_ADMIN","JAVA_OPTS")) for key in env):
    raise SystemExit("Keycloak bootstrap/admin environment is forbidden")

health=config.get("Healthcheck") or {}
health_test=health.get("Test")
if (
    not isinstance(health_test,list)
    or health_test[:1]!=["CMD-SHELL"]
    or len(health_test)!=2
    or "/kc/realms/papai-org" not in str(health_test[1])
    or health.get("Interval")!=15_000_000_000
    or health.get("Timeout")!=5_000_000_000
    or health.get("Retries")!=10
    or health.get("StartPeriod")!=60_000_000_000
):
    raise SystemExit("Keycloak healthcheck definition differs")

port_bindings=host.get("PortBindings") or {}
effective_ports=(kc.get("NetworkSettings") or {}).get("Ports") or {}
def binding(value,label,allow_unpublished=False):
    if not isinstance(value,dict):
        raise SystemExit(f"Keycloak {label} publication differs")
    extra=set(value)-{"8080/tcp"}
    if extra and (not allow_unpublished or any(value[key] not in (None,[]) for key in extra)):
        raise SystemExit(f"Keycloak {label} has an unexpected published port")
    if "8080/tcp" not in value or not isinstance(value["8080/tcp"],list) or len(value["8080/tcp"])!=1:
        raise SystemExit(f"Keycloak {label} publication differs")
    row=value["8080/tcp"][0]
    if not isinstance(row,dict) or row.get("HostIp")!="127.0.0.1" or re.fullmatch(r"[0-9]{1,5}",str(row.get("HostPort") or "")) is None:
        raise SystemExit(f"Keycloak {label} is not loopback-only")
    port=int(row["HostPort"])
    if not 1<=port<=65535: raise SystemExit("Keycloak host port is invalid")
    return str(port)
host_port=binding(port_bindings,"configured")
if binding(effective_ports,"effective",allow_unpublished=True)!=host_port:
    raise SystemExit("Keycloak configured/effective ports differ")

expected_sources={
    "/opt/keycloak/themes/agentium":Path(live_repo)/"backend/keycloak/themes/agentium",
    "/opt/keycloak/data/import/realm.json":Path(live_repo)/"backend/keycloak/realm-export.json",
}
mounts={row.get("Destination"):row for row in kc.get("Mounts") or [] if isinstance(row,dict)}
if set(mounts)!=set(expected_sources):
    raise SystemExit("Keycloak mount inventory differs")

def content_digest(path:Path)->str:
    try:
        if path.resolve(strict=True)!=path: raise SystemExit("Keycloak mount source is not canonical")
    except OSError as exc:
        raise SystemExit("Keycloak mount source is unavailable") from exc
    digest=hashlib.sha256(b"agentium-keycloak-mount-v1")
    root=path if path.is_dir() else path.parent
    entries=[path] if path.is_file() else sorted(path.rglob("*"))
    for entry in entries:
        row=entry.lstat()
        if stat.S_ISLNK(row.st_mode): raise SystemExit("Keycloak mount tree contains a symlink")
        relative=str(entry.relative_to(root)) if entry!=root else "."
        digest.update(b"\0"+relative.encode()+b"\0"+oct(stat.S_IMODE(row.st_mode)).encode())
        if stat.S_ISREG(row.st_mode): digest.update(b"\0"+hashlib.sha256(entry.read_bytes()).digest())
        elif not stat.S_ISDIR(row.st_mode): raise SystemExit("Keycloak mount tree contains a special file")
    return digest.hexdigest()

normalized_mounts=[]
for destination,expected_source in expected_sources.items():
    row=mounts[destination]; source=Path(str(row.get("Source") or ""))
    if row.get("Type")!="bind" or row.get("RW") is not False or source!=expected_source:
        raise SystemExit("Keycloak mount source/mode differs")
    normalized_mounts.append({"destination":destination,"source":str(source),"content_sha256":content_digest(source)})

networks=(kc.get("NetworkSettings") or {}).get("Networks") or {}
pg_networks=(pg.get("NetworkSettings") or {}).get("Networks") or {}
network_mode=str(host.get("NetworkMode") or "")
if len(networks)!=1 or set(networks)!=set(pg_networks) or network_mode not in networks or network_mode in {"host","bridge","none"}:
    raise SystemExit("Keycloak network topology differs from PostgreSQL")
network=networks[network_mode]; pg_network=pg_networks[network_mode]
network_id=str(network.get("NetworkID") or "")
if re.fullmatch(r"[0-9a-f]{64}",network_id) is None or pg_network.get("NetworkID")!=network_id:
    raise SystemExit("Keycloak network identity differs from PostgreSQL")
aliases=network.get("Aliases") or []
if "agentium-kc" not in aliases:
    raise SystemExit("Keycloak network alias differs")

if (
    host.get("Privileged") is not False
    or host.get("NetworkMode") in {"host","container"}
    or host.get("PidMode") not in {"",None}
    or host.get("IpcMode") not in {"private","",None}
    or host.get("Devices") not in (None,[])
    or host.get("CapAdd") not in (None,[])
):
    raise SystemExit("Keycloak container security boundary differs")

normalized={
    "image_ref":config.get("Image"),"image_id":image_id,"cmd":config.get("Cmd"),
    "entrypoint":config.get("Entrypoint"),"user":config.get("User"),"working_dir":config.get("WorkingDir"),
    "env":sorted(env.items()),"healthcheck":health,"labels":sorted(labels.items()),
    "port":host_port,"mounts":sorted(normalized_mounts,key=lambda row:row["destination"]),
    "network":{"name":network_mode,"id":network_id,"aliases":sorted(aliases)},
    "security":{"privileged":host.get("Privileged"),"readonly_rootfs":host.get("ReadonlyRootfs"),
        "cap_add":host.get("CapAdd"),"cap_drop":host.get("CapDrop"),"security_opt":host.get("SecurityOpt"),
        "pid_mode":host.get("PidMode"),"ipc_mode":host.get("IpcMode"),"devices":host.get("Devices")},
}
digest=hashlib.sha256(json.dumps(normalized,separators=(",",":"),sort_keys=True).encode()).hexdigest()
if mode=="verify" and (container_id!=expected_id or image_id!=expected_image or digest!=expected_digest or host_port!=expected_port):
    raise SystemExit("Keycloak immutable control-plane contract changed")
running=state.get("Running") is True
if liveness=="running" and (
    not running or state.get("Paused") is not False or state.get("Restarting") is not False
    or state.get("Dead") is not False or state.get("OOMKilled") is not False
    or not isinstance(state.get("Pid"),int) or state.get("Pid")<=0
    or (state.get("Health") or {}).get("Status")!="healthy"
): raise SystemExit("Keycloak live state differs")
if liveness=="stopped" and running: raise SystemExit("Keycloak remains running")
policy=host.get("RestartPolicy") or {}
if mode=="verify" and (policy.get("Name")!="no" or int(policy.get("MaximumRetryCount") or 0)!=0):
    raise SystemExit("Keycloak restart policy is not disabled")
if mode=="snapshot":
    print("keycloak_contract","agentium-kc",container_id,image_id,digest,host_port,sep="\t")
PY
}

record_runtime_state() {
	[[ ! -e "$RUNTIME_STATE" && ! -L "$RUNTIME_STATE" ]] || { assert_private "$RUNTIME_STATE"; return; }
	local temporary="$DEPLOY_DIR/.runtime-state.$$" service state name maximum image
	{
		printf 'format\t1\n'
		for service in agentium-pg agentium-rabbitmq qdrant agentium-minio agentium-backend agentium-frontend agentium-worker-cpu agentium-p4-maintenance agentium-sftp agentium-livekit agentium-livekit-agent agentium-kc; do
			if docker inspect "$service" >/dev/null 2>&1; then
				state="$(docker inspect --format '{{.State.Running}}' "$service")"
				image="$(docker inspect --format '{{.Image}}' "$service")"
				name="$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}' "$service")"
				maximum="$(docker inspect --format '{{.HostConfig.RestartPolicy.MaximumRetryCount}}' "$service")"
				printf 'container\t%s\t%s\t%s\t%s\t%s\n' "$service" "$state" "$image" "$name" "$maximum"
				docker inspect --format '{{json .Mounts}}' "$service" |
					python3 -I -c 'import json,sys; service=sys.argv[1]; rows=json.load(sys.stdin) or []; [(print("mount",service,str(r.get("Destination","")),str(r.get("Source","")),"rw" if r.get("RW") else "ro",str(r.get("Type","")),sep="\t")) for r in sorted(rows,key=lambda x:str(x.get("Destination","")))]' "$service"
				if [[ "$service" == agentium-sftp || "$service" == agentium-livekit || "$service" == agentium-kc ]]; then
					docker inspect --format '{{json .NetworkSettings.Ports}}' "$service" |
						python3 -I -c 'import json,sys; service=sys.argv[1]; ports=json.load(sys.stdin) or {}; [(print("binding",service,key.rsplit("/",1)[1],row.get("HostPort",""),sep="\t")) for key, rows in sorted(ports.items()) for row in (rows or []) if str(row.get("HostPort","")).isdigit()]' "$service"
				fi
				if [[ "$service" == agentium-kc ]]; then keycloak_control_plane_contract snapshot any; fi
			else printf 'container\t%s\tabsent\t-\tabsent\t-\n' "$service"; fi
		done
		if sudo_cmd test -f /etc/systemd/system/agentium-backend.service; then
			printf 'systemd\tagentium-backend.service\t%s\t%s\n' "$(sudo_cmd systemctl is-active agentium-backend.service || true)" "$(sudo_cmd systemctl is-enabled agentium-backend.service 2>/dev/null || true)"
		else printf 'systemd\tagentium-backend.service\tabsent\tabsent\n'; fi
		if sudo_cmd systemctl cat agentium-sftp.service >/dev/null 2>&1; then
			printf 'systemd\tagentium-sftp.service\t%s\t%s\n' "$(sudo_cmd systemctl is-active agentium-sftp.service || true)" "$(sudo_cmd systemctl is-enabled agentium-sftp.service 2>/dev/null || true)"
		else printf 'systemd\tagentium-sftp.service\tabsent\tabsent\n'; fi
	} >"$temporary"
	durable_replace "$temporary" "$RUNTIME_STATE"
}

systemd_guard_path() { printf '/etc/systemd/system/%s.d/00-agentium-release-a-guard.conf\n' "$1"; }

install_systemd_boot_guards() {
	local unit target
	for unit in agentium-backend.service agentium-sftp.service; do
		sudo_cmd systemctl cat "$unit" >/dev/null 2>&1 || continue
		target="$(systemd_guard_path "$unit")"
		if sudo_cmd test -e "$target" || sudo_cmd test -L "$target"; then
			[[ "$(sudo_cmd cat "$target")" == "$SYSTEMD_GUARD_CONTENT" ]] || die "Boot guard systemd divergent: $unit"
		else
			sudo_cmd install -d -m 0755 "$(dirname "$target")"
			printf '%s\n' "$SYSTEMD_GUARD_CONTENT" | sudo_cmd tee "$target" >/dev/null
			sudo_cmd chmod 0644 "$target"
		fi
	done
	sudo_cmd systemctl daemon-reload
}

assert_systemd_boot_guards() {
	local unit target
	for unit in agentium-backend.service agentium-sftp.service; do
		sudo_cmd systemctl cat "$unit" >/dev/null 2>&1 || continue
		target="$(systemd_guard_path "$unit")"
		sudo_cmd test -f "$target" && [[ ! -L "$target" ]] || die "Boot guard systemd absent: $unit"
		[[ "$(sudo_cmd cat "$target")" == "$SYSTEMD_GUARD_CONTENT" ]] || die "Boot guard systemd divergent: $unit"
		[[ "$(sudo_cmd systemctl is-enabled "$unit" 2>/dev/null || true)" != enabled ]] || die "Unité writer activée avant commit terminal: $unit"
	done
}

assert_systemd_boot_guards_absent() {
	local unit target
	for unit in agentium-backend.service agentium-sftp.service; do
		target="$(systemd_guard_path "$unit")"
		if sudo_cmd test -e "$target" || sudo_cmd test -L "$target"; then
			die "Boot guard systemd résiduel après ouverture: $unit"
		fi
	done
}

remove_systemd_boot_guard() {
	local unit="$1" target
	target="$(systemd_guard_path "$unit")"
	if sudo_cmd test -e "$target" || sudo_cmd test -L "$target"; then
		[[ "$(sudo_cmd cat "$target")" == "$SYSTEMD_GUARD_CONTENT" ]] || die "Boot guard non possédé: $unit"
		sudo_cmd rm -f "$target"
	fi
	sudo_cmd systemctl daemon-reload
}

assert_stateful_runtime_identity() {
	local service expected_image actual_image destination source mode type actual_source actual_mode actual_type
	for service in agentium-pg agentium-rabbitmq qdrant agentium-minio; do
		expected_image="$(awk -F '\t' -v service="$service" '$1=="container" && $2==service {print $4}' "$RUNTIME_STATE")"
		actual_image="$(docker inspect --format '{{.Image}}' "$service")"
		[[ "$actual_image" == "$expected_image" ]] || die "$service a changé d'image pendant Release A"
		while IFS=$'\t' read -r destination source mode type; do
			read -r actual_source actual_mode actual_type < <(docker inspect --format "{{range .Mounts}}{{if eq .Destination \"$destination\"}}{{.Source}} {{if .RW}}rw{{else}}ro{{end}} {{.Type}}{{end}}{{end}}" "$service")
			[[ "$actual_source" == "$source" && "$actual_mode" == "$mode" && "$actual_type" == "$type" ]] || die "$service:$destination mount divergent"
		done < <(awk -F '\t' -v service="$service" '$1=="mount" && $2==service {print $3 "\t" $4 "\t" $5 "\t" $6}' "$RUNTIME_STATE")
	done
}

writer_gate_rule() {
	local action="$1" tool="$2" chain="$3" protocol="$4" port="$5"
	local -a match reject
	[[ "$action" == -C || "$action" == -I || "$action" == -D ]] || return 2
	[[ "$protocol" == tcp || "$protocol" == udp ]] || return 2
	if [[ "$chain" == DOCKER-USER ]]; then
		match=(! -i lo -p "$protocol" -m conntrack --ctorigdstport "$port" --ctstate NEW)
	else
		match=(! -i lo -p "$protocol" --dport "$port" -m conntrack --ctstate NEW)
	fi
	if [[ "$protocol" == tcp ]]; then
		reject=(--reject-with tcp-reset)
	elif [[ "$tool" == ip6tables ]]; then
		reject=(--reject-with icmp6-port-unreachable)
	else
		reject=(--reject-with icmp-port-unreachable)
	fi
	if [[ "$action" == -I ]]; then
		sudo_cmd "$tool" -w 10 -I "$chain" 1 "${match[@]}" -m comment --comment "$WRITER_GATE_COMMENT" -j REJECT "${reject[@]}"
	else
		sudo_cmd "$tool" -w 10 "$action" "$chain" "${match[@]}" -m comment --comment "$WRITER_GATE_COMMENT" -j REJECT "${reject[@]}"
	fi
}

writer_bindings() {
	# The historical systemd listener is a host port; SFTP/LiveKit are the exact
	# Docker-published bindings captured before the transaction.
	printf 'tcp\t8000\n'
	awk -F '\t' '$1=="binding" {print $3 "\t" $4}' "$RUNTIME_STATE" | sort -u
}

enter_writer_ingress_gates() {
	local protocol port tool chain
	while IFS=$'\t' read -r protocol port; do
		[[ "$port" =~ ^[0-9]+$ ]] || die "Binding writer invalide"
		for tool in iptables ip6tables; do
			command -v "$tool" >/dev/null || die "$tool requis pour la fermeture writer"
			for chain in INPUT DOCKER-USER; do
				writer_gate_rule -C "$tool" "$chain" "$protocol" "$port" >/dev/null 2>&1 || writer_gate_rule -I "$tool" "$chain" "$protocol" "$port"
			done
		done
	done < <(writer_bindings)
}

assert_writer_ingress_gates() {
	local protocol port tool chain
	while IFS=$'\t' read -r protocol port; do
		for tool in iptables ip6tables; do for chain in INPUT DOCKER-USER; do writer_gate_rule -C "$tool" "$chain" "$protocol" "$port" >/dev/null 2>&1 || die "Gate writer manquant $protocol/$port"; done; done
	done < <(writer_bindings)
}

leave_writer_ingress_gates() {
	local protocol port tool chain
	while IFS=$'\t' read -r protocol port; do
		for tool in iptables ip6tables; do
			for chain in INPUT DOCKER-USER; do while writer_gate_rule -C "$tool" "$chain" "$protocol" "$port" >/dev/null 2>&1; do writer_gate_rule -D "$tool" "$chain" "$protocol" "$port"; done; done
		done
	done < <(writer_bindings)
}

assert_writer_ingress_gates_absent() {
	local protocol port tool chain
	while IFS=$'\t' read -r protocol port; do
		for tool in iptables ip6tables; do
			for chain in INPUT DOCKER-USER; do
				writer_gate_rule -C "$tool" "$chain" "$protocol" "$port" >/dev/null 2>&1 &&
					die "Gate writer résiduel après ouverture $protocol/$port"
			done
		done
	done < <(writer_bindings)
}

restore_restart_policy() {
	local service="$1" name maximum policy
	read -r name maximum < <(awk -F '\t' -v service="$service" '$1=="container" && $2==service {print $5, $6}' "$RUNTIME_STATE")
	[[ "$name" != absent && -n "$name" ]] || return 0
	case "$name" in
	no | always | unless-stopped) policy="$name" ;;
	on-failure) [[ "$maximum" == 0 ]] && policy=on-failure || policy="on-failure:$maximum" ;;
	*) die "Policy historique invalide pour $service" ;;
	esac
	docker update --restart="$policy" "$service" >/dev/null
}

disable_writer_restarts() {
	local service
	install_systemd_boot_guards
	for service in agentium-backend agentium-worker-cpu agentium-p4-maintenance agentium-sftp agentium-livekit agentium-livekit-agent agentium-kc; do
		if docker inspect "$service" >/dev/null 2>&1; then docker update --restart=no "$service" >/dev/null; fi
	done
	sudo_cmd systemctl disable agentium-backend.service >/dev/null 2>&1 || true
	sudo_cmd systemctl disable agentium-sftp.service >/dev/null 2>&1 || true
	for service in agentium-backend agentium-worker-cpu agentium-p4-maintenance agentium-sftp agentium-livekit agentium-livekit-agent agentium-kc; do
		if docker inspect "$service" >/dev/null 2>&1; then
			[[ "$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}:{{.HostConfig.RestartPolicy.MaximumRetryCount}}' "$service")" == no:0 ]] || die "$service peut encore redémarrer"
		fi
	done
	[[ "$(sudo_cmd systemctl is-enabled agentium-backend.service 2>/dev/null || true)" != enabled ]] || die "Backend systemd encore enabled"
	[[ "$(sudo_cmd systemctl is-enabled agentium-sftp.service 2>/dev/null || true)" != enabled ]] || die "SFTP systemd encore enabled"
}

stop_writers() {
	local service
	wait_for_existing_writer_connections_to_drain
	audit_live_writers_before_stop
	quiesce_sftp_before_stop
	for service in agentium-livekit-agent agentium-livekit agentium-kc agentium-p4-maintenance agentium-worker-cpu agentium-backend; do
		stop_container_without_sigkill "$service"
	done
	sudo_cmd systemctl stop agentium-backend.service >/dev/null 2>&1 || true
	sudo_cmd systemctl stop agentium-sftp.service >/dev/null 2>&1 || true
	[[ -z "$(ss -Hlt 'sport = :8000')" ]] || die "Backend systemd écoute encore sur 8000"
	[[ "$(sudo_cmd systemctl is-active agentium-sftp.service 2>/dev/null || true)" != active ]] || die "SFTP systemd encore actif"
	for service in agentium-backend agentium-worker-cpu agentium-p4-maintenance agentium-sftp agentium-livekit agentium-livekit-agent agentium-kc; do
		if docker inspect "$service" >/dev/null 2>&1; then
			[[ "$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}:{{.HostConfig.RestartPolicy.MaximumRetryCount}}:{{.State.Running}}' "$service")" == no:0:false ]] || die "$service n'est pas fail-closed"
		fi
	done
	if [[ -s "$RABBIT_PHASE" && "$(cat "$RABBIT_PHASE")" != guest_neutralized ]]; then bootstrap_rabbitmq; fi
	docker exec agentium-rabbitmq rabbitmqctl list_queues --quiet name messages_ready messages_unacknowledged --formatter json |
		python3 -I -c 'import json,sys; rows=json.load(sys.stdin); raise SystemExit(0 if all(r["messages_ready"] == 0 and r["messages_unacknowledged"] == 0 for r in rows) else 1)'
}

stop_writers_preserving_attested_sftp() {
	local service connections fds mode
	mode="$(current_secure_mode)"
	recover_attested_sftp_pause "$mode"
	wait_for_existing_writer_connections_to_drain
	audit_live_writers_before_stop
	[[ "$(docker inspect --format '{{.State.Running}}:{{.State.Paused}}:{{.HostConfig.RestartPolicy.Name}}:{{.HostConfig.RestartPolicy.MaximumRetryCount}}' agentium-sftp)" == true:false:no:0 ]] ||
		die "SFTP attesté n'est plus exécutable sans restart"
	docker pause agentium-sftp >/dev/null
	if ! connections="$(sudo_cmd ss -Htn state established "sport = :$(sftp_host_port)" | awk 'END {print NR + 0}')"; then
		docker unpause agentium-sftp >/dev/null 2>&1 || true
		die "Connexions SFTP non auditables avant ouverture"
	fi
	if ! fds="$(sftp_open_deposit_fd_count)"; then
		docker unpause agentium-sftp >/dev/null 2>&1 || true
		die "Descripteurs SFTP non auditables avant ouverture"
	fi
	docker unpause agentium-sftp >/dev/null
	[[ "$connections" -eq 0 && "$fds" -eq 0 ]] || die "SFTP attesté non quiescent avant ouverture"
	for service in agentium-livekit-agent agentium-livekit agentium-kc agentium-p4-maintenance agentium-worker-cpu agentium-backend; do
		stop_container_without_sigkill "$service"
	done
	sudo_cmd systemctl stop agentium-backend.service >/dev/null 2>&1 || true
	sudo_cmd systemctl stop agentium-sftp.service >/dev/null 2>&1 || true
	[[ -z "$(ss -Hlt 'sport = :8000')" ]] || die "Backend systemd écoute encore sur 8000"
	[[ "$(sudo_cmd systemctl is-active agentium-sftp.service 2>/dev/null || true)" != active ]] || die "SFTP systemd encore actif"
	for service in agentium-backend agentium-worker-cpu agentium-p4-maintenance agentium-livekit agentium-livekit-agent agentium-kc; do
		if docker inspect "$service" >/dev/null 2>&1; then
			[[ "$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}:{{.HostConfig.RestartPolicy.MaximumRetryCount}}:{{.State.Running}}' "$service")" == no:0:false ]] || die "$service n'est pas fail-closed"
		fi
	done
	if [[ -s "$RABBIT_PHASE" && "$(cat "$RABBIT_PHASE")" != guest_neutralized ]]; then bootstrap_rabbitmq; fi
	docker exec agentium-rabbitmq rabbitmqctl list_queues --quiet name messages_ready messages_unacknowledged --formatter json |
		python3 -I -c 'import json,sys; rows=json.load(sys.stdin); raise SystemExit(0 if all(r["messages_ready"] == 0 and r["messages_unacknowledged"] == 0 for r in rows) else 1)'
	assert_sftp_runtime_identity_live "$mode" disabled
}

writer_tcp_ports() {
	local protocol port
	while IFS=$'\t' read -r protocol port; do
		[[ "$protocol" == tcp ]] || continue
		printf '%s\n' "$port"
	done < <(writer_bindings)
}

wait_for_existing_writer_connections_to_drain() {
	local attempt port count total=0
	local -a ports=()
	command -v ss >/dev/null || die "ss requis pour drainer les connexions writer"
	while IFS= read -r port; do
		[[ "$port" =~ ^[0-9]+$ ]] || die "Port writer capturé invalide"
		[[ " ${ports[*]} " == *" $port "* ]] || ports+=("$port")
	done < <(writer_tcp_ports)
	for attempt in $(seq 1 30); do
		total=0
		for port in "${ports[@]}"; do
			count="$(sudo_cmd ss -Htn state established "sport = :$port" | awk 'END {print NR + 0}')"
			total=$((total + count))
		done
		[[ "$total" -eq 0 ]] && return
		sleep 2
	done
	die "$total connexion(s) writer établie(s) subsistent; arrêt refusé"
}

sftp_open_deposit_fd_count() {
	local pid fd fd_device secure_device count=0
	[[ "$(docker inspect --format '{{.State.Running}}' agentium-sftp 2>/dev/null || printf false)" == true ]] || { printf '0\n'; return; }
	secure_device="$(stat -Lc %d "$SECURE_DEPOSIT")"
	[[ "$secure_device" =~ ^[0-9]+$ ]] || die "Device Secure Deposit non auditable"
	while IFS= read -r pid; do
		[[ "$pid" =~ ^[0-9]+$ ]] || continue
		sudo_cmd test -d "/proc/$pid/fd" || die "FD SFTP non auditables pour PID $pid"
		while IFS= read -r fd; do
			[[ "$fd" =~ ^[0-9]+$ ]] || die "Descripteur SFTP invalide"
			# /proc exposes the target pathname in the process mount namespace,
			# where the same bind is named /data/secure_deposit rather than by its
			# host path.  Compare st_dev instead: /dev/sdc is dedicated to this
			# mount and therefore catches files and directories through either name.
			fd_device="$(sudo_cmd stat -Lc %d "/proc/$pid/fd/$fd" 2>/dev/null || true)"
			[[ "$fd_device" == "$secure_device" ]] && count=$((count + 1))
		done < <(sudo_cmd find "/proc/$pid/fd" -mindepth 1 -maxdepth 1 -printf '%f\n')
	done < <(docker top agentium-sftp -eo pid | awk 'NR > 1 {print $1}')
	printf '%s\n' "$count"
}

sftp_host_port() {
	local port count
	count="$(awk -F '\t' '$1=="binding" && $2=="agentium-sftp" && $3=="tcp" && !seen[$4]++ {count++} END {print count + 0}' "$RUNTIME_STATE")"
	port="$(awk -F '\t' '$1=="binding" && $2=="agentium-sftp" && $3=="tcp" {print $4; exit}' "$RUNTIME_STATE")"
	[[ "$count" == 1 && "$port" =~ ^[0-9]+$ ]] || die "Binding SFTP TCP unique introuvable"
	printf '%s\n' "$port"
}

stop_container_without_sigkill() {
	local service="$1"
	docker inspect "$service" >/dev/null 2>&1 || return 0
	[[ "$(docker inspect --format '{{.State.Running}}' "$service")" == true ]] || return 0
	if [[ "$(docker inspect --format '{{.State.Paused}}' "$service")" == true ]]; then docker unpause "$service" >/dev/null; fi
	docker kill --signal TERM "$service" >/dev/null
	timeout --foreground 120 docker wait "$service" >/dev/null || die "$service ne s'arrête pas sur SIGTERM; SIGKILL interdit"
	[[ "$(docker inspect --format '{{.State.Running}}' "$service")" == false ]] || die "$service écrit encore"
}

quiesce_sftp_before_stop() {
	local connections fds
	[[ "$(docker inspect --format '{{.State.Running}}' agentium-sftp 2>/dev/null || printf false)" == true ]] || return 0
	[[ "$(docker inspect --format '{{.State.Paused}}' agentium-sftp)" == false ]] || die "SFTP déjà en pause hors transaction"
	docker pause agentium-sftp >/dev/null
	connections="$(sudo_cmd ss -Htn state established "sport = :$(sftp_host_port)" | awk 'END {print NR + 0}')"
	fds="$(sftp_open_deposit_fd_count)"
	if [[ "$connections" -ne 0 || "$fds" -ne 0 ]]; then
		docker unpause agentium-sftp >/dev/null
		die "Gel SFTP refusé: $connections connexion(s), $fds FD dépôt ouvert(s)"
	fi
	docker unpause agentium-sftp >/dev/null
	stop_container_without_sigkill agentium-sftp
}

verify_live_writer_proof() {
	local proof="$1"
	assert_private "$proof"
	python3 -I - "$proof" "$RELEASE_A_SHA" "$DEPLOYMENT_ID" <<'PY'
import json, sys
from pathlib import Path
p=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected={
    "correlated_recent_active_capture_count": 0,
    "livekit_participant_count": 0,
    "livekit_publisher_count": 0,
}
if p.get("schema_version") != 1 or p.get("kind") != "live_writer_quiescence_audit" or p.get("result") != "passed":
    raise SystemExit("invalid live-writer proof")
if p.get("candidate_sha") != sys.argv[2] or p.get("deployment_id") != sys.argv[3] or p.get("blockers") != expected:
    raise SystemExit("live-writer proof identity/blockers differ")
PY
}

audit_live_writers_before_stop() {
	local temporary="$DEPLOY_DIR/.live-writer-quiescence.$$"
	if [[ -e "$LIVE_WRITER_PROOF" || -L "$LIVE_WRITER_PROOF" ]]; then
		verify_live_writer_proof "$LIVE_WRITER_PROOF"
	fi
	[[ ! -e "$temporary" && ! -L "$temporary" ]] || die "Audit live-writer concurrent"
	compose_audit run --rm --no-deps -T --entrypoint python agentium-backend \
		scripts/audit_livekit_quiescence.py --expected-sha "$RELEASE_A_SHA" --deployment-id "$DEPLOYMENT_ID" >"$temporary" || {
		[[ -s "$temporary" ]] && durable_replace "$temporary" "$LIVE_WRITER_FAILURE"
		die "Sessions LiveKit/Knowledge Capture actives ou audit indisponible"
	}
	chmod 0600 "$temporary"
	verify_live_writer_proof "$temporary"
	if [[ -e "$LIVE_WRITER_PROOF" || -L "$LIVE_WRITER_PROOF" ]]; then
		rm -f "$temporary"
	else
		durable_replace "$temporary" "$LIVE_WRITER_PROOF"
	fi
	verify_live_writer_proof "$LIVE_WRITER_PROOF"
}

disable_and_stop_writers() {
	disable_writer_restarts
	stop_writers
}

set_secure_mode() {
	local mode="$1"
	case "$mode" in
	ro)
		sudo_cmd sync
		if sudo_cmd fuser -m "$SECURE_DEPOSIT" >/dev/null 2>&1; then die "Secure Deposit encore ouvert par un processus"; fi
		sudo_cmd mount -o remount,ro "$SECURE_DEPOSIT"
		;;
	rw) sudo_cmd mount -o remount,rw "$SECURE_DEPOSIT" ;;
	*) die "Mode Secure Deposit invalide" ;;
	esac
	findmnt -n -o OPTIONS --target "$SECURE_DEPOSIT" | tr , '\n' | grep -qx "$mode" || die "Secure Deposit pas en $mode"
}

assert_secure_mode_in_namespaces() {
	local mode="$1" service
	[[ "$mode" == ro || "$mode" == rw ]] || die "Mode namespace invalide"
	for service in agentium-backend agentium-sftp; do
		if [[ "$(docker inspect --format '{{.State.Running}}' "$service" 2>/dev/null || printf false)" == true ]]; then
			docker exec "$service" python -I -c 'import os,sys; expected=sys.argv[2]=="ro"; actual=bool(os.statvfs(sys.argv[1]).f_flag & os.ST_RDONLY); raise SystemExit(0 if actual==expected else 1)' /data/secure_deposit "$mode" ||
				die "$service ne voit pas Secure Deposit en $mode"
		fi
	done
}

snapshot_storage() {
	local output="$1" baseline="${2:-0}" qdrant_env
	local -a extra=()
	[[ "$baseline" == 1 ]] && extra=(--allow-unversioned-release-a-baseline)
	qdrant_env="$("$FROZEN_ENV_HELPER" role-path --bundle-dir "$RUNTIME_ENV_DIR" --sha "$RELEASE_A_SHA" --deployment-id "$DEPLOYMENT_ID" --expected-manifest-sha256 "$ENV_DIGEST" --role qdrant)"
	"$FROZEN_STORAGE_HELPER" snapshot --output "$output" --secure-deposit "$SECURE_DEPOSIT" --data-root "$DATA_ROOT" --qdrant-env "$qdrant_env" \
		--container agentium-backend --container agentium-worker-cpu --container agentium-p4-maintenance --container agentium-sftp "${extra[@]}"
}

write_checkout_intent() {
	if [[ ! -e "$CHECKOUT_INTENT" && ! -L "$CHECKOUT_INTENT" ]]; then
		temporary="$DEPLOY_DIR/.checkout-intent.$$"
		{
			printf 'format\t1\n'
			printf 'deployment_id\t%s\n' "$DEPLOYMENT_ID"
			printf 'live_sha\t%s\n' "$LIVE_SHA"
			printf 'release_a_sha\t%s\n' "$RELEASE_A_SHA"
			printf 'created_at\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
		} >"$temporary"
		durable_replace "$temporary" "$CHECKOUT_INTENT"
	fi
	assert_checkout_intent
}

assert_checkout_intent() {
	assert_private "$CHECKOUT_INTENT"
	python3 -I - "$CHECKOUT_INTENT" "$DEPLOYMENT_ID" "$LIVE_SHA" "$RELEASE_A_SHA" <<'PY'
import re,sys
from pathlib import Path
rows={}
for line in Path(sys.argv[1]).read_text().splitlines():
    fields=line.split("\t")
    if len(fields)!=2 or fields[0] in rows: raise SystemExit("invalid checkout intent")
    rows[fields[0]]=fields[1]
if set(rows)!={"format","deployment_id","live_sha","release_a_sha","created_at"} or rows["format"]!="1": raise SystemExit("checkout intent schema differs")
if rows["deployment_id"]!=sys.argv[2] or rows["live_sha"]!=sys.argv[3] or rows["release_a_sha"]!=sys.argv[4]: raise SystemExit("checkout intent identity differs")
if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z",rows["created_at"]) is None: raise SystemExit("checkout intent timestamp invalid")
PY
}

publish_runtime_env_files() {
	[[ "$(env_value compose_main AGENTIUM_ENV_FILE)" == ./env/agentium.env ]] || die "Référence application canonique invalide"
	[[ "$(env_value compose_main AGENTIUM_QDRANT_ENV_FILE)" == ./env/qdrant.agentium.env ]] || die "Référence Qdrant canonique invalide"
	[[ "$(env_value compose_main AGENTIUM_KEYCLOAK_ENV_FILE)" == ./env/keycloak.agentium.env ]] || die "Référence Keycloak canonique invalide"
	local role target source temporary
	while IFS=$'\t' read -r role target; do
		source="$("$FROZEN_ENV_HELPER" role-path --bundle-dir "$RUNTIME_ENV_DIR" --sha "$RELEASE_A_SHA" --deployment-id "$DEPLOYMENT_ID" --expected-manifest-sha256 "$ENV_DIGEST" --role "$role")"
		temporary="${target}.release-a.$$"
		install -m 0600 "$source" "$temporary"
		durable_replace "$temporary" "$target"
	done <<EOF
compose_main	$LIVE_REPO/docker/env/agentium.vm.env
application	$LIVE_REPO/docker/env/agentium.env
qdrant	$LIVE_REPO/docker/env/qdrant.agentium.env
keycloak	$LIVE_REPO/docker/env/keycloak.agentium.env
EOF
	temporary="$LIVE_REPO/backend/.env.release-a.$$"
	install -m 0600 "$SYSTEMD_ENV_SOURCE" "$temporary"
	durable_replace "$temporary" "$LIVE_REPO/backend/.env"
	for target in "$LIVE_REPO/docker/env/agentium.vm.env" "$LIVE_REPO/docker/env/agentium.env" "$LIVE_REPO/docker/env/qdrant.agentium.env" "$LIVE_REPO/docker/env/keycloak.agentium.env" "$LIVE_REPO/backend/.env"; do
		[[ "$(stat -c %a "$target")" == 600 ]] || die "Env canonique non privé: $target"
	done
}

bootstrap_rabbitmq() {
	local state user encoded_user main_env queue encoded_queue temporary message messages
	state="$(cat "$RABBIT_PHASE" 2>/dev/null || printf planned)"
	user="$(env_value compose_main AGENTIUM_RABBITMQ_USER)"
	[[ "$user" =~ ^[A-Za-z0-9_.-]{3,64}$ && "$user" != guest ]] || die "Utilisateur RabbitMQ applicatif invalide"
	if [[ "$state" == planned ]]; then
		printf 'machine 127.0.0.1 login guest password guest\n' >"$RABBIT_GUEST_NETRC"
		chmod 0600 "$RABBIT_GUEST_NETRC"
		main_env="$("$FROZEN_ENV_HELPER" role-path --bundle-dir "$RUNTIME_ENV_DIR" --sha "$RELEASE_A_SHA" --deployment-id "$DEPLOYMENT_ID" --expected-manifest-sha256 "$ENV_DIGEST" --role compose_main)"
		rm -f "$RABBIT_BODY" "$RABBIT_PERMISSIONS_BODY" "$RABBIT_APP_NETRC"
		python3 -I - "$main_env" "$RABBIT_BODY" "$RABBIT_PERMISSIONS_BODY" "$RABBIT_APP_NETRC" <<'PY'
import json, os, re, sys
from pathlib import Path
env_path, user_body, permissions_body, netrc = map(Path, sys.argv[1:])
values={}
for raw in env_path.read_text(encoding="utf-8").splitlines():
    line=raw.strip()
    if not line or line.startswith("#"): continue
    key, sep, value=line.partition("=")
    if sep and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",key):
        if len(value)>=2 and value[0]==value[-1] and value[0] in "\"'": value=value[1:-1]
        values[key]=value
user=values.get("AGENTIUM_RABBITMQ_USER","")
password=values.get("AGENTIUM_RABBITMQ_PASSWORD","")
if not re.fullmatch(r"[A-Za-z0-9_.-]{3,64}",user) or user=="guest" or len(password)<16:
    raise SystemExit("RabbitMQ frozen credential is invalid")
for path, payload in ((user_body, {"password": password, "tags": ""}), (permissions_body, {"configure": ".*", "write": ".*", "read": ".*"})):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(payload, handle, separators=(",", ":")); handle.flush(); os.fsync(handle.fileno())
fd = os.open(netrc, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as handle:
    handle.write(f"machine 127.0.0.1 login {user} password {password}\n"); handle.flush(); os.fsync(handle.fileno())
PY
		encoded_user="$(python3 -I -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$user")"
		curl --fail --silent --show-error --netrc-file "$RABBIT_GUEST_NETRC" -H 'content-type: application/json' --data-binary "@$RABBIT_BODY" -X PUT "http://127.0.0.1:15672/api/users/$encoded_user" >/dev/null
		curl --fail --silent --show-error --netrc-file "$RABBIT_GUEST_NETRC" -H 'content-type: application/json' --data-binary "@$RABBIT_PERMISSIONS_BODY" -X PUT "http://127.0.0.1:15672/api/permissions/%2F/$encoded_user" >/dev/null
		curl --fail --silent --show-error --netrc-file "$RABBIT_APP_NETRC" http://127.0.0.1:15672/api/whoami |
			python3 -I -c 'import json,sys; p=json.load(sys.stdin); raise SystemExit(0 if p.get("name") == sys.argv[1] and p.get("tags") == [] else 1)' "$user"
		rm -f "$RABBIT_BODY" "$RABBIT_PERMISSIONS_BODY"
		atomic_text "$RABBIT_PHASE" app_user_configured
		state=app_user_configured
	fi
	queue=cpu
	message="agentium-release-a-control:$DEPLOYMENT_ID"
	encoded_queue="$(python3 -I -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$queue")"
	if [[ "$state" == app_user_configured ]]; then
		encoded_queue="$(python3 -I -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$queue")"
		printf '%s' '{"auto_delete":false,"durable":true,"arguments":{}}' >"$DEPLOY_DIR/rabbitmq-queue.json"
		printf '{"properties":{},"routing_key":"%s","payload":"%s","payload_encoding":"string"}' "$queue" "$message" >"$DEPLOY_DIR/rabbitmq-publish.json"
		printf '%s' '{"count":1,"ackmode":"ack_requeue_false","encoding":"auto","truncate":256}' >"$DEPLOY_DIR/rabbitmq-get.json"
		chmod 0600 "$DEPLOY_DIR"/rabbitmq-{queue,publish,get}.json
		curl --fail --silent --show-error --netrc-file "$RABBIT_APP_NETRC" -H 'content-type: application/json' --data-binary "@$DEPLOY_DIR/rabbitmq-queue.json" -X PUT "http://127.0.0.1:15672/api/queues/%2F/$encoded_queue" >/dev/null
		messages="$(curl --fail --silent --show-error --netrc-file "$RABBIT_APP_NETRC" "http://127.0.0.1:15672/api/queues/%2F/$encoded_queue" | python3 -I -c 'import json,sys; p=json.load(sys.stdin); value=p.get("messages"); raise SystemExit(2) if not isinstance(value,int) or isinstance(value,bool) else None; print(value)')"
		[[ "$messages" == 0 || "$messages" == 1 ]] || die "Queue Celery cpu non vide avant probe"
		if [[ "$messages" == 1 ]]; then
			curl --fail --silent --show-error --netrc-file "$RABBIT_APP_NETRC" -H 'content-type: application/json' --data-binary "@$DEPLOY_DIR/rabbitmq-get.json" -X POST "http://127.0.0.1:15672/api/queues/%2F/$encoded_queue/get" |
				python3 -I -c 'import json,sys; p=json.load(sys.stdin); raise SystemExit(0 if len(p)==1 and p[0].get("payload")==sys.argv[1] and p[0].get("routing_key")=="cpu" else 1)' "$message"
		fi
		curl --fail --silent --show-error --netrc-file "$RABBIT_APP_NETRC" -H 'content-type: application/json' --data-binary "@$DEPLOY_DIR/rabbitmq-publish.json" -X POST http://127.0.0.1:15672/api/exchanges/%2F/amq.default/publish |
			python3 -I -c 'import json,sys; raise SystemExit(0 if json.load(sys.stdin)=={"routed": True} else 1)'
		atomic_text "$RABBIT_PHASE" cpu_probe_published
		state=cpu_probe_published
	fi
	if [[ "$state" == cpu_probe_published ]]; then
		messages="$(curl --fail --silent --show-error --netrc-file "$RABBIT_APP_NETRC" "http://127.0.0.1:15672/api/queues/%2F/$encoded_queue" | python3 -I -c 'import json,sys; p=json.load(sys.stdin); value=p.get("messages"); raise SystemExit(2) if not isinstance(value,int) or isinstance(value,bool) else None; print(value)')"
		[[ "$messages" == 0 || "$messages" == 1 ]] || die "Queue Celery cpu ambiguë pendant probe"
		if [[ "$messages" == 0 ]]; then
			curl --fail --silent --show-error --netrc-file "$RABBIT_APP_NETRC" -H 'content-type: application/json' --data-binary "@$DEPLOY_DIR/rabbitmq-publish.json" -X POST http://127.0.0.1:15672/api/exchanges/%2F/amq.default/publish |
				python3 -I -c 'import json,sys; raise SystemExit(0 if json.load(sys.stdin)=={"routed": True} else 1)'
		fi
		curl --fail --silent --show-error --netrc-file "$RABBIT_APP_NETRC" -H 'content-type: application/json' --data-binary "@$DEPLOY_DIR/rabbitmq-get.json" -X POST "http://127.0.0.1:15672/api/queues/%2F/$encoded_queue/get" |
			python3 -I -c 'import json,sys; p=json.load(sys.stdin); raise SystemExit(0 if len(p)==1 and p[0].get("payload")==sys.argv[1] and p[0].get("routing_key")=="cpu" else 1)' "$message"
		atomic_text "$RABBIT_PHASE" cpu_probe_passed
		state=cpu_probe_passed
		temporary="$DEPLOY_DIR/.rabbitmq-proof.$$"
		printf '{"schema_version":1,"kind":"agentium-release-a-rabbitmq-bootstrap","result":"passed","application_principal_sha256":"%s","celery_cpu_publish_consume_probe":true,"queues_empty_after":true,"guest_permissions_neutralized":false}\n' "$(printf %s "$user" | sha256sum | awk '{print $1}')" >"$temporary"
		durable_replace "$temporary" "$RABBIT_PROOF"
	fi
	if [[ "$state" == cpu_probe_passed && ! -e "$RABBIT_PROOF" && ! -L "$RABBIT_PROOF" ]]; then
		temporary="$DEPLOY_DIR/.rabbitmq-proof.$$"
		printf '{"schema_version":1,"kind":"agentium-release-a-rabbitmq-bootstrap","result":"passed","application_principal_sha256":"%s","celery_cpu_publish_consume_probe":true,"queues_empty_after":true,"guest_permissions_neutralized":false}\n' "$(printf %s "$user" | sha256sum | awk '{print $1}')" >"$temporary"
		durable_replace "$temporary" "$RABBIT_PROOF"
	fi
	if [[ "$state" == cpu_probe_passed ]]; then
		docker exec agentium-rabbitmq rabbitmqctl clear_permissions -p / guest >/dev/null 2>&1 || true
		docker exec agentium-rabbitmq rabbitmqctl list_user_permissions guest --formatter json |
			python3 -I -c 'import json,sys; raise SystemExit(0 if json.load(sys.stdin) == [] else 1)'
		atomic_text "$RABBIT_PHASE" guest_neutralized
		temporary="$DEPLOY_DIR/.rabbitmq-proof-update.$$"
		python3 -I - "$RABBIT_PROOF" "$temporary" <<'PY'
import json,os,sys
from pathlib import Path
p,t=map(Path,sys.argv[1:]); value=json.loads(p.read_text()); value["guest_permissions_neutralized"]=True
fd=os.open(t,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,"w") as h: json.dump(value,h,separators=(",",":"),sort_keys=True); h.write("\n"); h.flush(); os.fsync(h.fileno())
PY
		durable_replace "$temporary" "$RABBIT_PROOF"
		state=guest_neutralized
	fi
	rm -f "$DEPLOY_DIR"/rabbitmq-{queue,publish,get}.json
	[[ "$state" == guest_neutralized ]] || die "Bootstrap RabbitMQ incomplet"
	assert_private "$RABBIT_APP_NETRC"
}

verify_rabbitmq_candidate() {
	local user
	user="$(env_value compose_main AGENTIUM_RABBITMQ_USER)"
	curl --fail --silent --show-error --netrc-file "$RABBIT_APP_NETRC" http://127.0.0.1:15672/api/whoami |
		python3 -I -c 'import json,sys; raise SystemExit(0 if json.load(sys.stdin).get("name") == sys.argv[1] else 1)' "$user"
	docker exec agentium-rabbitmq rabbitmqctl list_queues --quiet name messages_ready messages_unacknowledged --formatter json |
		python3 -I -c 'import json,sys; raise SystemExit(0 if all(r["messages_ready"] == 0 and r["messages_unacknowledged"] == 0 for r in json.load(sys.stdin)) else 1)'
}

postgres_identity() {
	local user database
	user="$(env_value compose_main AGENTIUM_POSTGRES_USER)"
	database="$(env_value compose_main AGENTIUM_POSTGRES_DB)"
	[[ "$user" =~ ^[A-Za-z_][A-Za-z0-9_]*$ && "$database" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "Identité PostgreSQL invalide"
	printf '%s\t%s\n' "$user" "$database"
}

verify_postgres_inventory_v2() {
	local inventory="$1"
	assert_private "$inventory"
	python3 -I - "$inventory" "$RELEASE_A_SHA" "$DEPLOYMENT_ID" <<'PY'
import json,re,sys
from pathlib import Path
p=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected={"schema_version","kind","profile","candidate_sha","deployment_id","content_serialized","detail_policy","table_count","tables","inventory_sha256","business_inventory_sha256","workspace_identities","workspace_identities_sha256","ledger_binding"}
sha256=re.compile(r"[0-9a-f]{64}\Z")
if set(p)!=expected or p.get("schema_version")!=2 or p.get("kind")!="postgresql_row_inventory" or p.get("profile")!="agentium-postgresql-row-inventory-v2":
    raise SystemExit("PostgreSQL inventory v2 schema differs")
if p.get("candidate_sha")!=sys.argv[2] or p.get("deployment_id")!=sys.argv[3] or p.get("content_serialized") is not False:
    raise SystemExit("PostgreSQL inventory v2 identity differs")
tables=p.get("tables")
if not isinstance(tables,dict) or p.get("table_count")!=len(tables) or not tables:
    raise SystemExit("PostgreSQL inventory v2 tables invalid")
if any(sha256.fullmatch(str(p.get(key,""))) is None for key in ("inventory_sha256","business_inventory_sha256","workspace_identities_sha256")):
    raise SystemExit("PostgreSQL inventory v2 digest invalid")
binding=p.get("ledger_binding")
if not isinstance(binding,dict) or binding.get("provided") is not False:
    raise SystemExit("Release A baseline must not contain controlled ledger rows")
PY
}

capture_postgres_inventory() {
	local output="$1" temporary
	temporary="$DEPLOY_DIR/.${output##*/}.$$"
	compose_audit run --rm --no-deps -T --entrypoint python agentium-backend \
		-m scripts.audit_post_canary_database snapshot --sha "$RELEASE_A_SHA" --deployment-id "$DEPLOYMENT_ID" >"$temporary"
	chmod 0600 "$temporary"
	verify_postgres_inventory_v2 "$temporary"
	durable_replace "$temporary" "$output"
	verify_postgres_inventory_v2 "$output"
}

compare_postgres_inventory_v2() {
	local before="$1" after="$2"
	verify_postgres_inventory_v2 "$before"
	verify_postgres_inventory_v2 "$after"
	python3 -I - "$before" "$after" <<'PY'
import json,sys
from pathlib import Path
before,after=(json.loads(Path(path).read_text(encoding="utf-8")) for path in sys.argv[1:])
if before["business_inventory_sha256"]!=after["business_inventory_sha256"]:
    raise SystemExit("PostgreSQL business inventory changed")
if before["workspace_identities_sha256"]!=after["workspace_identities_sha256"] or set(before["tables"])!=set(after["tables"]):
    raise SystemExit("PostgreSQL workspace/table identity changed")
PY
}

capture_postgres_comparison() {
	local before="$1" after="$2" before_digest after_digest temporary
	compare_postgres_inventory_v2 "$before" "$after"
	before_digest="$(sha256sum "$before" | awk '{print $1}')"
	after_digest="$(sha256sum "$after" | awk '{print $1}')"
	if [[ ! -e "$POSTGRES_COMPARISON" && ! -L "$POSTGRES_COMPARISON" ]]; then
		temporary="$DEPLOY_DIR/.postgres-comparison.$$"
		python3 -I - "$temporary" "$DEPLOYMENT_ID" "$RELEASE_A_SHA" "$before_digest" "$after_digest" <<'PY'
import json,os,sys
from datetime import datetime,timezone
out,deployment_id,release_sha,before_digest,after_digest=sys.argv[1:]
payload={"schema_version":1,"kind":"agentium-release-a-postgres-comparison","profile":"business_inventory_exact_v1","result":"passed","deployment_id":deployment_id,"release_a_sha":release_sha,"before_sha256":before_digest,"after_sha256":after_digest,"verified_at":datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")}
descriptor=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(descriptor,"w",encoding="utf-8") as handle:
    json.dump(payload,handle,separators=(",",":"),sort_keys=True); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
PY
		durable_replace "$temporary" "$POSTGRES_COMPARISON"
	fi
	assert_private "$POSTGRES_COMPARISON"
	python3 -I - "$POSTGRES_COMPARISON" "$DEPLOYMENT_ID" "$RELEASE_A_SHA" "$before_digest" "$after_digest" <<'PY'
import json,re,sys
from datetime import datetime
from pathlib import Path
payload=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected={"schema_version","kind","profile","result","deployment_id","release_a_sha","before_sha256","after_sha256","verified_at"}
if set(payload)!=expected or payload.get("schema_version")!=1 or payload.get("kind")!="agentium-release-a-postgres-comparison" or payload.get("profile")!="business_inventory_exact_v1" or payload.get("result")!="passed":
    raise SystemExit("PostgreSQL comparison contract differs")
if payload.get("deployment_id")!=sys.argv[2] or payload.get("release_a_sha")!=sys.argv[3] or payload.get("before_sha256")!=sys.argv[4] or payload.get("after_sha256")!=sys.argv[5]:
    raise SystemExit("PostgreSQL comparison binding differs")
stamp=payload.get("verified_at")
if not isinstance(stamp,str) or not stamp.endswith("Z"):
    raise SystemExit("PostgreSQL comparison timestamp invalid")
try: datetime.fromisoformat(stamp.removesuffix("Z")+"+00:00")
except ValueError as exc: raise SystemExit("PostgreSQL comparison timestamp invalid") from exc
PY
}

reconcile_postgres_rehearsal() {
	[[ -e "$POSTGRES_REHEARSAL_INTENT" || -L "$POSTGRES_REHEARSAL_INTENT" ]] || return 0
	assert_private "$POSTGRES_REHEARSAL_INTENT"
	local user database rehearsal
	read -r user database < <(postgres_identity)
	rehearsal="$(awk -F '\t' '$1=="database" {print $2; exit}' "$POSTGRES_REHEARSAL_INTENT")"
	[[ "$rehearsal" =~ ^agentium_ra_[a-f0-9]{16}$ && "$rehearsal" != "$database" ]] || die "Intent rehearsal PostgreSQL invalide"
	docker exec agentium-pg psql -v ON_ERROR_STOP=1 -U "$user" -d postgres -Atqc "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$rehearsal' AND pid<>pg_backend_pid();" >/dev/null
	docker exec agentium-pg dropdb -U "$user" --if-exists "$rehearsal"
	rm -f "$POSTGRES_REHEARSAL_INTENT"
	python3 -I - "$DEPLOY_DIR" <<'PY'
import os,sys
fd=os.open(sys.argv[1],os.O_RDONLY|getattr(os,"O_DIRECTORY",0)); os.fsync(fd); os.close(fd)
PY
}

ensure_postgres_backup_and_restore_rehearsal() {
	local user database rehearsal temporary expected actual bytes connections
	read -r user database < <(postgres_identity)
	if [[ ! -e "$POSTGRES_DUMP.ready" ]]; then
		connections="$(docker exec agentium-pg psql -v ON_ERROR_STOP=1 -U "$user" -d "$database" -Atqc "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid();")"
		[[ "$connections" == 0 ]] || die "PostgreSQL conserve $connections connexion(s)"
		temporary="$DEPLOY_DIR/.postgres-release-a.dump.$$"
		docker exec agentium-pg pg_dump -U "$user" -d "$database" -Fc >"$temporary"
		chmod 0600 "$temporary"
		durable_replace "$temporary" "$POSTGRES_DUMP"
		actual="$(sha256sum "$POSTGRES_DUMP" | awk '{print $1}')"; bytes="$(stat -c %s "$POSTGRES_DUMP")"
		atomic_text "$POSTGRES_DUMP.sha256" "$actual  postgres-release-a.dump"
		temporary="$DEPLOY_DIR/.postgres-ready.$$"
		printf 'format\t1\nsha256\t%s\nbytes\t%s\n' "$actual" "$bytes" >"$temporary"
		durable_replace "$temporary" "$POSTGRES_DUMP.ready"
	fi
	assert_private "$POSTGRES_DUMP"; assert_private "$POSTGRES_DUMP.sha256"; assert_private "$POSTGRES_DUMP.ready"
	expected="$(awk 'NR==1{print $1}' "$POSTGRES_DUMP.sha256")"; actual="$(sha256sum "$POSTGRES_DUMP" | awk '{print $1}')"
	[[ "$expected" == "$actual" ]] || die "Dump PostgreSQL altéré"
	if [[ ! -e "$DEPLOY_DIR/postgres-restore-proof.json" ]]; then
		rehearsal="agentium_ra_$(printf %s "$DEPLOYMENT_ID" | sha256sum | cut -c1-16)"
		temporary="$DEPLOY_DIR/.postgres-rehearsal-intent.$$"
		printf 'format\t1\ndatabase\t%s\ndump_sha256\t%s\n' "$rehearsal" "$actual" >"$temporary"
		durable_replace "$temporary" "$POSTGRES_REHEARSAL_INTENT"
		docker exec agentium-pg createdb -U "$user" "$rehearsal"
		docker exec -i agentium-pg pg_restore -U "$user" -d "$rehearsal" --exit-on-error <"$POSTGRES_DUMP"
		docker exec agentium-pg psql -v ON_ERROR_STOP=1 -U "$user" -d "$rehearsal" -Atqc "SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname='public'" | grep -Eq '^[1-9][0-9]*$' || die "Rehearsal PostgreSQL vide"
		reconcile_postgres_rehearsal
		temporary="$DEPLOY_DIR/.postgres-restore-proof.$$"
		printf '{"schema_version":1,"kind":"agentium-release-a-postgres-restore-rehearsal","result":"passed","dump_sha256":"%s"}\n' "$actual" >"$temporary"
		durable_replace "$temporary" "$DEPLOY_DIR/postgres-restore-proof.json"
	fi
	if [[ ! -e "$POSTGRES_INVENTORY_BEFORE" ]]; then capture_postgres_inventory "$POSTGRES_INVENTORY_BEFORE"; fi
}

verify_qdrant_keys() {
	local qdrant_env temporary probe_name
	qdrant_env="$("$FROZEN_ENV_HELPER" role-path --bundle-dir "$RUNTIME_ENV_DIR" --sha "$RELEASE_A_SHA" --deployment-id "$DEPLOYMENT_ID" --expected-manifest-sha256 "$ENV_DIGEST" --role qdrant)"
	probe_name="__agentium_release_a_probe_$(printf %s "$DEPLOYMENT_ID" | sha256sum | cut -c1-16)"
	if [[ ! -e "$QDRANT_PROBE_INTENT" && ! -L "$QDRANT_PROBE_INTENT" ]]; then
		atomic_text "$QDRANT_PROBE_INTENT" "format=1 name=$probe_name"
	fi
	assert_private "$QDRANT_PROBE_INTENT"
	[[ "$(cat "$QDRANT_PROBE_INTENT")" == "format=1 name=$probe_name" ]] || die "Intent Qdrant divergent"
	temporary="$DEPLOY_DIR/.qdrant-proof.$$"
	python3 -I - "$qdrant_env" "$temporary" "$probe_name" <<'PY'
import hashlib,json,os,re,sys,urllib.error,urllib.request
from pathlib import Path
values={}
for raw in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    key,sep,value=raw.strip().partition("=")
    if sep and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",key):
        if len(value)>=2 and value[0]==value[-1] and value[0] in "\"'": value=value[1:-1]
        values[key]=value
admin=values.get("QDRANT__SERVICE__API_KEY",""); readonly=values.get("QDRANT__SERVICE__READ_ONLY_API_KEY","")
if min(len(admin),len(readonly))<32 or admin==readonly: raise SystemExit("Qdrant key contract invalid")
def request(method,path,key,body=None):
    req=urllib.request.Request("http://127.0.0.1:6333"+path,data=None if body is None else json.dumps(body).encode(),method=method,headers={"api-key":key,"content-type":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=10) as response: return response.status
    except urllib.error.HTTPError as exc: return exc.code
if request("GET","/collections",admin)!=200 or request("GET","/collections",readonly)!=200: raise SystemExit("Qdrant authenticated reads failed")
name=sys.argv[3]
status=request("GET","/collections/"+name,admin)
if status!=404:
    # The intent reserves the name but cannot atomically prove who created a
    # surviving collection. Never delete or overwrite it on replay: maintenance
    # remains closed until an operator establishes ownership out of band.
    raise SystemExit("Qdrant probe collision/ambiguous interrupted probe")
if request("PUT","/collections/"+name+"?timeout=30",admin,{"vectors":{"size":1,"distance":"Cosine"}})!=200: raise SystemExit("Qdrant admin create failed")
if request("PUT","/collections/"+name+"/points?wait=true",admin,{"points":[{"id":1,"vector":[0.0]}]})!=200: raise SystemExit("Qdrant admin write failed")
status=request("PUT","/collections/"+name+"/points?wait=true",readonly,{"points":[{"id":2,"vector":[1.0]}]})
if status not in {401,403}:
    request("DELETE","/collections/"+name,admin)
    raise SystemExit("Qdrant read-only key unexpectedly wrote")
if request("DELETE","/collections/"+name+"?timeout=30",admin)!=200 or request("GET","/collections/"+name,admin)!=404: raise SystemExit("Qdrant probe cleanup failed")
p={"schema_version":1,"kind":"agentium-release-a-qdrant-bootstrap","result":"passed","admin_key_fingerprint_sha256":hashlib.sha256(admin.encode()).hexdigest(),"read_only_key_fingerprint_sha256":hashlib.sha256(readonly.encode()).hexdigest(),"admin_read":True,"admin_write":True,"read_only_read":True,"read_only_write_denied":True,"probe_absent_after":True}
fd=os.open(sys.argv[2],os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,"w") as h: json.dump(p,h,separators=(",",":"),sort_keys=True); h.write("\n"); h.flush(); os.fsync(h.fileno())
PY
	if [[ -e "$QDRANT_PROOF" || -L "$QDRANT_PROOF" ]]; then
		assert_private "$QDRANT_PROOF"
		cmp -s "$temporary" "$QDRANT_PROOF" || die "Preuve Qdrant rejouée divergente"
		rm -f "$temporary"
	else
		durable_replace "$temporary" "$QDRANT_PROOF"
	fi
	assert_private "$QDRANT_PROOF"
	rm -f "$QDRANT_PROBE_INTENT"
	python3 -I - "$DEPLOY_DIR" <<'PY'
import os,sys
fd=os.open(sys.argv[1],os.O_RDONLY|getattr(os,"O_DIRECTORY",0)); os.fsync(fd); os.close(fd)
PY
}

start_validation_runtime_under_gates() {
	local service desired
	assert_writer_ingress_gates
	for service in agentium-sftp agentium-livekit agentium-livekit-agent; do
		desired="$(awk -F '\t' -v service="$service" '$1=="container" && $2==service {print $3}' "$RUNTIME_STATE")"
		if [[ "$desired" == true ]]; then docker start "$service" >/dev/null; docker update --restart=no "$service" >/dev/null; fi
	done
	sudo_cmd systemctl stop agentium-backend.service
	sudo_cmd systemctl stop agentium-sftp.service >/dev/null 2>&1 || true
	[[ "$(sudo_cmd systemctl is-enabled agentium-backend.service 2>/dev/null || true)" != enabled ]] || die "Backend systemd peut redémarrer en validation"
	[[ "$(sudo_cmd systemctl is-active agentium-sftp.service 2>/dev/null || true)" != active ]] || die "SFTP systemd actif en validation"
	# All positive probes are local while public ingress remains denied.
	curl --noproxy '*' --fail --silent --show-error http://127.0.0.1:8001/api/v1/build-info |
		python3 -I -c 'import json,sys; p=json.load(sys.stdin); raise SystemExit(0 if p.get("revision")==sys.argv[1] and p.get("revision_verified") is True else 1)' "$RELEASE_A_SHA"
	curl --noproxy '*' --fail --silent --show-error http://127.0.0.1:9000/minio/health/live >/dev/null
	[[ -z "$(sudo_cmd ss -Hltpn 'sport = :8000')" ]] || die "Backend systemd écoute pendant la validation read-only"
	if [[ "$(docker inspect --format '{{.State.Running}}' agentium-sftp 2>/dev/null || printf false)" == true ]]; then
		port="$(docker port agentium-sftp 2222/tcp | awk -F: 'NR==1{print $NF}')"
		[[ "$port" =~ ^[0-9]+$ ]] || die "Port SFTP local introuvable"
		timeout 10 bash -c "exec 3<>/dev/tcp/127.0.0.1/$port; IFS= read -r line <&3; [[ \"\$line\" == SSH-* ]]" || die "Banner SFTP local absent"
	fi
	assert_writer_ingress_gates
}

assert_sftp_canary_control_plane() {
	local backend_port expected_backend_image expected_kc_image keycloak_port keycloak_issuer service
	keycloak_control_plane_contract verify running
	backend_port="$(env_value compose_main AGENTIUM_BACKEND_HOST_PORT)"
	[[ "$backend_port" =~ ^[0-9]+$ && "$backend_port" -ge 1 && "$backend_port" -le 65535 ]] ||
		die "Port backend du control plane SFTP invalide"
	expected_backend_image="$(candidate_service_image_id agentium-backend)"
	expected_kc_image="$(awk -F '\t' '$1=="container" && $2=="agentium-kc" {print $4}' "$RUNTIME_STATE")"
	[[ "$expected_kc_image" =~ ^sha256:[0-9a-f]{64}$ ]] || die "Image Keycloak historique non attestable"
	assert_writer_ingress_gates
	assert_secure_mode_in_namespaces ro
	assert_sftp_runtime_ready_live
	python3 -I - "$expected_backend_image" "$expected_kc_image" "$backend_port" "$RELEASE_A_SHA" <<'PY'
import json,re,subprocess,sys

backend_image,kc_image,backend_port,release_sha=sys.argv[1:]

def inspect(name):
    completed=subprocess.run(
        ["docker","inspect","--type","container",name],
        check=True,capture_output=True,text=True,timeout=30,
    )
    rows=json.loads(completed.stdout)
    if not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0],dict):
        raise SystemExit("SFTP canary control-plane container inventory differs")
    return rows[0]

backend=inspect("agentium-backend")
kc=inspect("agentium-kc")
for name,row,expected_image in (
    ("agentium-backend",backend,backend_image),
    ("agentium-kc",kc,kc_image),
):
    state=row.get("State") or {}; policy=(row.get("HostConfig") or {}).get("RestartPolicy") or {}
    health=(state.get("Health") or {}).get("Status")
    if (
        row.get("Image")!=expected_image
        or state.get("Running") is not True
        or state.get("Paused") is not False
        or health!="healthy"
        or policy.get("Name")!="no"
        or int(policy.get("MaximumRetryCount") or 0)!=0
    ):
        raise SystemExit(f"{name} is not an exact restart-disabled SFTP control-plane service")

image_rows=json.loads(subprocess.run(
    ["docker","image","inspect",backend_image],
    check=True,capture_output=True,text=True,timeout=30,
).stdout)
if not isinstance(image_rows,list) or len(image_rows)!=1:
    raise SystemExit("SFTP control-plane backend image inventory differs")
labels=((image_rows[0].get("Config") or {}).get("Labels") or {})
if labels.get("org.opencontainers.image.revision")!=release_sha:
    raise SystemExit("SFTP control-plane backend revision differs")

environment={}
for item in (backend.get("Config") or {}).get("Env") or []:
    if not isinstance(item,str) or "=" not in item:
        continue
    key,value=item.split("=",1)
    if key in environment:
        raise SystemExit("SFTP control-plane backend environment is ambiguous")
    environment[key]=value
if environment.get("STARTUP_RECONCILIATION")!="disabled" or environment.get("AGENTIUM_DISABLE_DOTENV")!="1":
    raise SystemExit("SFTP control-plane backend startup policy differs")

bindings=(backend.get("HostConfig") or {}).get("PortBindings") or {}
rows=bindings.get("8000/tcp")
if set(bindings)!={"8000/tcp"} or not isinstance(rows,list) or len(rows)!=1:
    raise SystemExit("SFTP control-plane backend publication is ambiguous")
if rows[0].get("HostIp")!="127.0.0.1" or rows[0].get("HostPort")!=backend_port:
    raise SystemExit("SFTP control-plane backend is not loopback-only")

mounts={row.get("Destination"):row for row in backend.get("Mounts") or [] if isinstance(row,dict)}
for destination in ("/data/object_store","/data/secure_deposit","/data/faiss_db"):
    row=mounts.get(destination)
    if not isinstance(row,dict) or row.get("Type")!="bind" or row.get("RW") is not False:
        raise SystemExit("SFTP control-plane backend data mounts are not read-only")
PY
	for service in agentium-frontend agentium-worker-cpu agentium-p4-maintenance agentium-livekit agentium-livekit-agent; do
		if docker inspect "$service" >/dev/null 2>&1; then
			[[ "$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}:{{.HostConfig.RestartPolicy.MaximumRetryCount}}:{{.State.Running}}' "$service")" == no:0:false ]] ||
				die "$service actif pendant le control plane SFTP"
		fi
	done
	[[ "$(sudo_cmd systemctl is-active agentium-backend.service 2>/dev/null || true)" != active ]] || die "Backend systemd actif pendant le canari SFTP"
	[[ "$(sudo_cmd systemctl is-active agentium-sftp.service 2>/dev/null || true)" != active ]] || die "SFTP systemd actif pendant le canari SFTP"
	[[ -z "$(ss -Hlt 'sport = :8000')" ]] || die "Backend systemd écoute pendant le canari SFTP"
	docker exec agentium-rabbitmq rabbitmqctl list_queues --quiet name messages_ready messages_unacknowledged --formatter json |
		python3 -I -c 'import json,sys; rows=json.load(sys.stdin); raise SystemExit(0 if all(r["messages_ready"] == 0 and r["messages_unacknowledged"] == 0 for r in rows) else 1)'
	curl --noproxy '*' --fail --silent --show-error "http://127.0.0.1:$backend_port/api/v1/build-info" |
		python3 -I -c 'import json,sys; p=json.load(sys.stdin); raise SystemExit(0 if p.get("revision")==sys.argv[1] and p.get("revision_verified") is True else 1)' "$RELEASE_A_SHA"
	keycloak_port="$(awk -F '\t' '$1=="keycloak_contract" && $2=="agentium-kc" {print $6}' "$RUNTIME_STATE")"
	keycloak_issuer="$(env_value keycloak KC_HOSTNAME)/realms/papai-org"
	curl --noproxy '*' --fail --silent --show-error \
		"http://127.0.0.1:$keycloak_port/kc/realms/papai-org/.well-known/openid-configuration" |
		python3 -I -c 'import json,sys; p=json.load(sys.stdin); raise SystemExit(0 if isinstance(p,dict) and p.get("issuer")==sys.argv[1] else 1)' "$keycloak_issuer"
	[[ "$(sudo_cmd ss -Htn state established "sport = :$backend_port" | awk 'END {print NR + 0}')" -eq 0 ]] ||
		die "Connexion backend résiduelle pendant le canari SFTP"
	assert_writer_ingress_gates
}

start_sftp_canary_control_plane() {
	local service desired keycloak_id
	assert_sftp_runtime_ready_live
	assert_writer_ingress_gates
	assert_secure_mode_in_namespaces ro
	if docker inspect agentium-frontend >/dev/null 2>&1; then
		docker update --restart=no agentium-frontend >/dev/null
		stop_container_without_sigkill agentium-frontend
	fi
	keycloak_control_plane_contract verify any
	keycloak_id="$(awk -F '\t' '$1=="keycloak_contract" && $2=="agentium-kc" {print $3}' "$RUNTIME_STATE")"
	[[ "$keycloak_id" =~ ^[0-9a-f]{64}$ ]] || die "ID Keycloak historique invalide"
	desired="$(awk -F '\t' '$1=="container" && $2=="agentium-kc" {print $3}' "$RUNTIME_STATE")"
	[[ "$desired" == true ]] || die "Keycloak n'était pas historiquement actif; control plane SFTP interdit"
	docker start "$keycloak_id" >/dev/null
	for service in agentium-backend; do
		desired="$(awk -F '\t' -v service="$service" '$1=="container" && $2==service {print $3}' "$RUNTIME_STATE")"
		[[ "$desired" == true ]] || die "$service n'était pas historiquement actif; control plane SFTP interdit"
		docker inspect "$service" >/dev/null 2>&1 || die "$service absent du runtime candidat"
		docker update --restart=no "$service" >/dev/null
		docker start "$service" >/dev/null
	done
	for _ in $(seq 1 90); do
		if [[ "$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' agentium-kc)" == healthy &&
			"$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' agentium-backend)" == healthy ]]; then
			break
		fi
		sleep 1
	done
	assert_sftp_canary_control_plane
}

stop_sftp_canary_control_plane() {
	local backend_port service keycloak_id
	assert_sftp_canary_control_plane
	backend_port="$(env_value compose_main AGENTIUM_BACKEND_HOST_PORT)"
	for _ in $(seq 1 30); do
		[[ "$(sudo_cmd ss -Htn state established "sport = :$backend_port" | awk 'END {print NR + 0}')" -eq 0 ]] && break
		sleep 1
	done
	[[ "$(sudo_cmd ss -Htn state established "sport = :$backend_port" | awk 'END {print NR + 0}')" -eq 0 ]] ||
		die "Connexion control plane SFTP non drainée"
	keycloak_id="$(awk -F '\t' '$1=="keycloak_contract" && $2=="agentium-kc" {print $3}' "$RUNTIME_STATE")"
	for service in agentium-backend "$keycloak_id"; do
		stop_container_without_sigkill "$service"
	done
	for service in agentium-backend agentium-kc; do
		[[ "$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}:{{.HostConfig.RestartPolicy.MaximumRetryCount}}:{{.State.Running}}' "$service")" == no:0:false ]] ||
			die "$service n'est pas arrêté après le control plane SFTP"
	done
	keycloak_control_plane_contract verify stopped
	assert_sftp_runtime_ready_live
	assert_writer_ingress_gates
	assert_secure_mode_in_namespaces ro
}

assert_sftp_canary_control_plane_stopped() {
	local service
	keycloak_control_plane_contract verify stopped
	for service in agentium-backend agentium-kc; do
		docker inspect "$service" >/dev/null 2>&1 || die "$service absent après le canari SFTP"
		[[ "$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}:{{.HostConfig.RestartPolicy.MaximumRetryCount}}:{{.State.Running}}' "$service")" == no:0:false ]] ||
			die "$service reste actif après le canari SFTP"
	done
	assert_sftp_runtime_ready_live
	assert_writer_ingress_gates
	assert_secure_mode_in_namespaces ro
}

capture_sftp_runtime_ready() {
	assert_writer_ingress_gates
	assert_secure_mode_in_namespaces ro
	[[ "$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}:{{.HostConfig.RestartPolicy.MaximumRetryCount}}' agentium-sftp)" == no:0 ]] ||
		die "SFTP peut redémarrer pendant le canari"
	local temporary="$DEPLOY_DIR/.sftp-validation-runtime-ready.$$"
	[[ ! -e "$temporary" && ! -L "$temporary" ]] || die "Capture runtime-ready SFTP concurrente"
	"$FROZEN_SFTP_BOUNDARY_AUDIT" validation-ready \
		--live-sha "$LIVE_SHA" \
		--release-a-sha "$RELEASE_A_SHA" \
		--sftp-sha "$(metadata sftp_release_sha)" \
		--deployment-id "$DEPLOYMENT_ID" \
		--expected-secure-source /dev/sdc \
		--output "$temporary"
	assert_private "$temporary"
	if [[ -e "$SFTP_RUNTIME_READY" || -L "$SFTP_RUNTIME_READY" ]]; then
		assert_private "$SFTP_RUNTIME_READY"
		python3 -I - "$SFTP_RUNTIME_READY" "$temporary" <<'PY' || { rm -f "$temporary"; die "Runtime SFTP différent du reçu armé"; }
import json,sys
from pathlib import Path
original,fresh=(json.loads(Path(path).read_text(encoding="utf-8")) for path in sys.argv[1:])
if {key:value for key,value in original.items() if key!="ready_at"}!={key:value for key,value in fresh.items() if key!="ready_at"}:
    raise SystemExit("SFTP runtime-ready identity changed")
PY
		rm -f "$temporary"
	else
		durable_replace "$temporary" "$SFTP_RUNTIME_READY"
	fi
	assert_private "$SFTP_RUNTIME_READY"
}

assert_sftp_runtime_ready_live() {
	[[ -e "$SFTP_RUNTIME_READY" && ! -L "$SFTP_RUNTIME_READY" ]] || die "Reçu runtime-ready SFTP absent"
	capture_sftp_runtime_ready
}

current_secure_mode() {
	local options mode=""
	options="$(findmnt -n -o OPTIONS --target "$SECURE_DEPOSIT")"
	if tr , '\n' <<<"$options" | grep -qx ro; then mode=ro; fi
	if tr , '\n' <<<"$options" | grep -qx rw; then
		[[ -z "$mode" ]] || die "Secure Deposit annonce simultanément ro et rw"
		mode=rw
	fi
	[[ "$mode" == ro || "$mode" == rw ]] || die "Mode Secure Deposit non attestable"
	printf '%s\n' "$mode"
}

assert_sftp_runtime_identity_live() {
	local mode="$1" restart="${2:-disabled}" paused="${3:-0}"
	local -a arguments=(
		verify-runtime-identity-live
		--runtime-proof "$SFTP_RUNTIME_READY"
		--live-sha "$LIVE_SHA"
		--release-a-sha "$RELEASE_A_SHA"
		--sftp-sha "$(metadata sftp_release_sha)"
		--deployment-id "$DEPLOYMENT_ID"
		--expected-secure-source /dev/sdc
		--expected-secure-mode "$mode"
		--expected-restart "$restart"
	)
	[[ "$mode" == ro || "$mode" == rw ]] || die "Mode identité SFTP invalide"
	[[ "$restart" == disabled || "$restart" == historical ]] || die "Policy identité SFTP invalide"
	[[ "$paused" == 0 || "$paused" == 1 ]] || die "Option paused SFTP invalide"
	assert_private "$SFTP_RUNTIME_READY"
	if [[ "$restart" == historical ]]; then arguments+=(--runtime-state "$RUNTIME_STATE"); fi
	if [[ "$paused" == 1 ]]; then arguments+=(--allow-paused); fi
	"$FROZEN_SFTP_BOUNDARY_AUDIT" "${arguments[@]}" >/dev/null
}

# The positive SFTP proof binds Docker StartedAt.  Once that process disappears
# or restarts, the proof cannot be recreated honestly.  This deliberately
# lightweight probe only answers whether the process identity is still the one
# bound by the private runtime-ready receipt; the full live verifier remains
# authoritative for transport, mount and ingress assertions.
probe_sftp_process_identity_core() {
	python3 -I - "$SFTP_RUNTIME_READY" "$(metadata sftp_release_sha)" <<'PY'
import json,os,re,stat,subprocess,sys
from pathlib import Path

proof=Path(sys.argv[1]); expected_revision=sys.argv[2]
try:
    before=proof.lstat()
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode) or before.st_uid!=os.geteuid() or stat.S_IMODE(before.st_mode)!=0o600 or before.st_nlink!=1:
        raise SystemExit(2)
    raw=proof.read_bytes(); receipt=json.loads(raw)
    canonical=json.dumps(receipt,separators=(",",":"),sort_keys=True).encode("utf-8")+b"\n"
    if (
        raw!=canonical
        or receipt.get("schema_version")!=1
        or receipt.get("kind")!="agentium-release-a-sftp-runtime-ready"
        or receipt.get("result")!="passed"
        or re.fullmatch(r"[0-9a-f]{64}",str(receipt.get("sftp_container_id", ""))) is None
        or re.fullmatch(r"sha256:[0-9a-f]{64}",str(receipt.get("sftp_image_id", ""))) is None
        or re.fullmatch(r"[0-9a-f]{64}",str(receipt.get("runtime_identity_sha256", ""))) is None
        or not isinstance(receipt.get("sftp_started_at"),str)
    ):
        raise SystemExit(2)
except (OSError,UnicodeDecodeError,json.JSONDecodeError,ValueError,TypeError):
    raise SystemExit(2)
try:
    rows=json.loads(subprocess.run(
        ["docker","inspect","--type","container","agentium-sftp"],
        check=True,capture_output=True,text=True,timeout=30,
    ).stdout)
    if not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0],dict):
        raise SystemExit(1)
    row=rows[0]; state=row.get("State") or {}
    if (
        row.get("Id")!=receipt.get("sftp_container_id")
        or row.get("Image")!=receipt.get("sftp_image_id")
        or state.get("StartedAt")!=receipt.get("sftp_started_at")
        or state.get("Running") is not True
    ):
        raise SystemExit(1)
    images=json.loads(subprocess.run(
        ["docker","image","inspect",str(row.get("Image") or "")],
        check=True,capture_output=True,text=True,timeout=30,
    ).stdout)
    labels=((images[0].get("Config") or {}).get("Labels") or {}) if isinstance(images,list) and len(images)==1 else {}
    if labels.get("org.opencontainers.image.revision")!=expected_revision:
        raise SystemExit(1)
except (OSError,json.JSONDecodeError,subprocess.SubprocessError,ValueError,TypeError):
    raise SystemExit(1)
PY
}

observed_sftp_process_identity_sha256() {
	python3 -I - <<'PY'
import hashlib,json,subprocess

observed={"available":False}
try:
    rows=json.loads(subprocess.run(
        ["docker","inspect","--type","container","agentium-sftp"],
        check=True,capture_output=True,text=True,timeout=30,
    ).stdout)
    if isinstance(rows,list) and len(rows)==1 and isinstance(rows[0],dict):
        row=rows[0]; state=row.get("State") or {}
        observed={
            "available":True,
            "container_id":row.get("Id"),
            "image_id":row.get("Image"),
            "started_at":state.get("StartedAt"),
            "running":state.get("Running"),
            "paused":state.get("Paused"),
        }
except (OSError,subprocess.SubprocessError,ValueError,TypeError):
    pass
body=json.dumps(observed,separators=(",",":"),sort_keys=True).encode("utf-8")+b"\n"
print(hashlib.sha256(body).hexdigest())
PY
}

emergency_stop_writers_after_sftp_identity_loss() {
	local service
	# The public/network gates are installed before this function.  Do not run
	# the normal canary audit here: its attested SFTP process is precisely what
	# has been lost.  Stop all execution-plane writers gracefully and fail if a
	# process refuses SIGTERM; this path never escalates to SIGKILL.
	for service in agentium-livekit-agent agentium-livekit agentium-kc agentium-p4-maintenance agentium-worker-cpu agentium-backend agentium-sftp; do
		stop_container_without_sigkill "$service"
	done
	sudo_cmd systemctl stop agentium-backend.service >/dev/null 2>&1 || true
	sudo_cmd systemctl stop agentium-sftp.service >/dev/null 2>&1 || true
	[[ -z "$(ss -Hlt 'sport = :8000')" ]] || die "Backend systemd écoute après invalidation SFTP"
	for service in agentium-backend agentium-worker-cpu agentium-p4-maintenance agentium-sftp agentium-livekit agentium-livekit-agent agentium-kc; do
		if docker inspect "$service" >/dev/null 2>&1; then
			[[ "$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}:{{.HostConfig.RestartPolicy.MaximumRetryCount}}:{{.State.Running}}' "$service")" == no:0:false ]] ||
				die "$service reste écrivain après invalidation SFTP"
		fi
	done
}

assert_sftp_identity_invalidation() {
	assert_private "$SFTP_IDENTITY_INVALIDATION"
	python3 -I - "$SFTP_IDENTITY_INVALIDATION" "$SFTP_RUNTIME_READY" "$COMPLETION_RECEIPT" "$DEPLOYMENT_ID" "$LIVE_SHA" "$RELEASE_A_SHA" "$(metadata sftp_release_sha)" <<'PY'
import hashlib,json,os,re,stat,sys
from datetime import datetime
from pathlib import Path

event,proof,completion=map(Path,sys.argv[1:4])
deployment_id,live_sha,release_a_sha,sftp_sha=sys.argv[4:]
raw=event.read_bytes()
def no_duplicates(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError("duplicate key")
        result[key]=value
    return result
try: payload=json.loads(raw,object_pairs_hook=no_duplicates)
except (UnicodeDecodeError,json.JSONDecodeError,ValueError) as exc: raise SystemExit("invalid SFTP identity invalidation JSON") from exc
canonical=json.dumps(payload,separators=(",",":"),sort_keys=True).encode("utf-8")+b"\n"
expected={"schema_version","kind","result","deployment_id","live_sha","release_a_sha","sftp_sha","detected_phase","reason","old_runtime_ready_receipt_sha256","old_runtime_identity_sha256","observed_runtime_identity_sha256","completion_receipt_sha256","reclosure","recovery","automatic_rearm_allowed","operator_gate","invalidated_at"}
phases={"validation_pending","sftp_canary_pending","sftp_canary_active_recorded","sftp_canary_recorded","opening_forward","opened","completed"}
reclosure=payload.get("reclosure")
if raw!=canonical or set(payload)!=expected or payload.get("schema_version")!=1 or payload.get("kind")!="agentium-release-a-sftp-runtime-identity-invalidation" or payload.get("result")!="invalidated": raise SystemExit("SFTP identity invalidation schema differs")
if payload.get("deployment_id")!=deployment_id or payload.get("live_sha")!=live_sha or payload.get("release_a_sha")!=release_a_sha or payload.get("sftp_sha")!=sftp_sha or payload.get("detected_phase") not in phases or payload.get("reason")!="attested_process_identity_lost" or payload.get("recovery")!="new_deployment_id_required" or payload.get("automatic_rearm_allowed") is not False or payload.get("operator_gate")!="revoke_old_canary_and_verify_zero_active_links_sessions_before_new_deployment": raise SystemExit("SFTP identity invalidation binding differs")
if not isinstance(reclosure,dict) or set(reclosure)!={"http_gate_closed","restart_disabled","secure_deposit_read_only","writer_ingress_closed","writers_stopped"} or any(value not in ("passed","incomplete") for value in reclosure.values()): raise SystemExit("SFTP identity invalidation reclosure differs")
for key in ("old_runtime_ready_receipt_sha256","old_runtime_identity_sha256","observed_runtime_identity_sha256"):
    if re.fullmatch(r"[0-9a-f]{64}",str(payload.get(key,""))) is None: raise SystemExit("SFTP identity invalidation digest differs")
proof_stat=proof.lstat()
if stat.S_ISLNK(proof_stat.st_mode) or not stat.S_ISREG(proof_stat.st_mode) or proof_stat.st_uid!=os.geteuid() or stat.S_IMODE(proof_stat.st_mode)!=0o600 or proof_stat.st_nlink!=1: raise SystemExit("unsafe invalidated SFTP proof")
proof_raw=proof.read_bytes(); proof_payload=json.loads(proof_raw)
proof_canonical=json.dumps(proof_payload,separators=(",",":"),sort_keys=True).encode("utf-8")+b"\n"
if proof_raw!=proof_canonical or proof_payload.get("schema_version")!=1 or proof_payload.get("kind")!="agentium-release-a-sftp-runtime-ready" or proof_payload.get("result")!="passed" or re.fullmatch(r"[0-9a-f]{64}",str(proof_payload.get("runtime_identity_sha256",""))) is None: raise SystemExit("invalid invalidated SFTP proof")
if payload["old_runtime_ready_receipt_sha256"]!=hashlib.sha256(proof_raw).hexdigest() or payload["old_runtime_identity_sha256"]!=proof_payload.get("runtime_identity_sha256"): raise SystemExit("SFTP identity invalidation old-proof binding differs")
completion_present=os.path.lexists(completion)
if completion_present:
    completion_stat=completion.lstat()
    if stat.S_ISLNK(completion_stat.st_mode) or not stat.S_ISREG(completion_stat.st_mode) or completion_stat.st_uid!=os.geteuid() or stat.S_IMODE(completion_stat.st_mode)!=0o600 or completion_stat.st_nlink!=1: raise SystemExit("unsafe completion receipt during SFTP invalidation")
    expected_completion=hashlib.sha256(completion.read_bytes()).hexdigest()
else: expected_completion=None
if payload.get("detected_phase")=="completed" and not completion_present: raise SystemExit("completed SFTP invalidation lost completion receipt")
if payload.get("completion_receipt_sha256")!=expected_completion: raise SystemExit("SFTP identity invalidation completion binding differs")
stamp=payload.get("invalidated_at")
if not isinstance(stamp,str) or not stamp.endswith("Z"): raise SystemExit("SFTP identity invalidation timestamp differs")
try: datetime.fromisoformat(stamp.removesuffix("Z")+"+00:00")
except ValueError as exc: raise SystemExit("SFTP identity invalidation timestamp differs") from exc
PY
}

publish_sftp_identity_invalidation() {
	local detected_phase="$1" observed_sha="$2" restart_status="$3" http_status="$4" ingress_status="$5" writers_status="$6" secure_status="$7"
	if [[ -e "$SFTP_IDENTITY_INVALIDATION" || -L "$SFTP_IDENTITY_INVALIDATION" ]]; then
		assert_sftp_identity_invalidation
		return
	fi
	assert_private "$SFTP_RUNTIME_READY"
	if [[ -e "$COMPLETION_RECEIPT" || -L "$COMPLETION_RECEIPT" ]]; then assert_private "$COMPLETION_RECEIPT"; fi
	[[ "$observed_sha" =~ ^[0-9a-f]{64}$ ]] || die "Empreinte runtime SFTP observée invalide"
	python3 -I - "$SFTP_IDENTITY_INVALIDATION" "$SFTP_RUNTIME_READY" "$COMPLETION_RECEIPT" "$DEPLOYMENT_ID" "$LIVE_SHA" "$RELEASE_A_SHA" "$(metadata sftp_release_sha)" "$detected_phase" "$observed_sha" "$restart_status" "$http_status" "$ingress_status" "$writers_status" "$secure_status" <<'PY'
import hashlib,json,os,sys
from datetime import datetime,timezone
from pathlib import Path

out,proof,completion=map(Path,sys.argv[1:4])
deployment_id,live_sha,release_a_sha,sftp_sha,detected_phase,observed_sha=sys.argv[4:10]
restart_status,http_status,ingress_status,writers_status,secure_status=sys.argv[10:]
proof_raw=proof.read_bytes(); proof_payload=json.loads(proof_raw)
payload={
    "schema_version":1,
    "kind":"agentium-release-a-sftp-runtime-identity-invalidation",
    "result":"invalidated",
    "deployment_id":deployment_id,
    "live_sha":live_sha,
    "release_a_sha":release_a_sha,
    "sftp_sha":sftp_sha,
    "detected_phase":detected_phase,
    "reason":"attested_process_identity_lost",
    "old_runtime_ready_receipt_sha256":hashlib.sha256(proof_raw).hexdigest(),
    "old_runtime_identity_sha256":proof_payload["runtime_identity_sha256"],
    "observed_runtime_identity_sha256":observed_sha,
    "completion_receipt_sha256":hashlib.sha256(completion.read_bytes()).hexdigest() if completion.exists() else None,
    "reclosure":{
        "restart_disabled":restart_status,
        "http_gate_closed":http_status,
        "writer_ingress_closed":ingress_status,
        "writers_stopped":writers_status,
        "secure_deposit_read_only":secure_status,
    },
    "recovery":"new_deployment_id_required",
    "automatic_rearm_allowed":False,
    "operator_gate":"revoke_old_canary_and_verify_zero_active_links_sessions_before_new_deployment",
    "invalidated_at":datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z"),
}
body=json.dumps(payload,separators=(",",":"),sort_keys=True).encode("utf-8")+b"\n"
fd=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,"wb") as handle:
    handle.write(body); handle.flush(); os.fsync(handle.fileno())
directory=os.open(out.parent,os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
try: os.fsync(directory)
finally: os.close(directory)
PY
	assert_sftp_identity_invalidation
}

invalidate_lost_sftp_identity() {
	local detected_phase="$1" observed_sha="$2"
	local restart_status=incomplete http_status=incomplete ingress_status=incomplete writers_status=incomplete secure_status=incomplete
	# Each safety operation runs independently: a failed systemd or Docker check
	# must never prevent the immutable invalidation event from being published.
	if (install_gate_closed); then http_status=passed; fi
	if (enter_writer_ingress_gates && assert_writer_ingress_gates); then ingress_status=passed; fi
	if (disable_writer_restarts); then restart_status=passed; fi
	if (emergency_stop_writers_after_sftp_identity_loss); then writers_status=passed; fi
	if (set_secure_mode ro && assert_secure_mode_in_namespaces ro); then secure_status=passed; fi
	publish_sftp_identity_invalidation "$detected_phase" "$observed_sha" "$restart_status" "$http_status" "$ingress_status" "$writers_status" "$secure_status"
	set_phase sftp_identity_invalidated
	OPENING_FAIL_CLOSED_ARMED=0
	OPENING_TERMINAL_SYNCED=0
	if [[ "$http_status" == passed && "$ingress_status" == passed && "$restart_status" == passed && "$writers_status" == passed && "$secure_status" == passed ]]; then
		die "Identité du processus SFTP attesté perdue; transaction invalidée, ingress maintenu fermé et nouveau deployment-id obligatoire"
	fi
	die "Identité du processus SFTP attesté perdue; invalidation durable mais reclosure incomplète, intervention immédiate et nouveau deployment-id obligatoires"
}

fail_closed_unattestable_sftp_proof() {
	# A corrupt/unsafe proof cannot be cryptographically linked into an honest
	# invalidation event.  It still loses every right to keep production open.
	# Reclose first and leave the phase untouched for forensic intervention.
	(install_gate_closed) || true
	(enter_writer_ingress_gates && assert_writer_ingress_gates) || true
	(disable_writer_restarts) || true
	(emergency_stop_writers_after_sftp_identity_loss) || true
	(set_secure_mode ro && assert_secure_mode_in_namespaces ro) || true
	OPENING_FAIL_CLOSED_ARMED=0
	die "Reçu runtime-ready SFTP non sûr; ingress refermé, preuve non réutilisable et maintenance manuelle obligatoire"
}

guard_sftp_process_identity_or_invalidate() {
	local detected_phase observed_sha probe_status=0
	detected_phase="$(phase)"
	case "$detected_phase" in
	validation_pending | sftp_canary_pending | sftp_canary_active_recorded | sftp_canary_recorded | opening_forward | opened | completed) ;;
	*) return 0 ;;
	esac
	[[ -e "$SFTP_RUNTIME_READY" || -L "$SFTP_RUNTIME_READY" ]] || return 0
	if probe_sftp_process_identity_core; then return 0; else probe_status=$?; fi
	# Exit 2 denotes an unsafe/tampered proof, not an observed process loss.  Do
	# not create an event that pretends it can bind such a proof; existing private
	# artifact checks fail closed and require operator investigation.
	[[ "$probe_status" -ne 2 ]] || fail_closed_unattestable_sftp_proof
	observed_sha="$(observed_sftp_process_identity_sha256)"
	invalidate_lost_sftp_identity "$detected_phase" "$observed_sha"
}

recover_attested_sftp_pause() {
	local mode="$1" paused
	assert_writer_ingress_gates
	paused="$(docker inspect --format '{{.State.Paused}}' agentium-sftp)"
	[[ "$paused" == true || "$paused" == false ]] || die "État paused SFTP non attestable"
	if [[ "$paused" == true ]]; then
		assert_sftp_runtime_identity_live "$mode" disabled 1
		docker unpause agentium-sftp >/dev/null
	fi
	assert_sftp_runtime_identity_live "$mode" disabled
}

reclose_attested_sftp_to_read_only() {
	local mode connections fds
	mode="$(current_secure_mode)"
	recover_attested_sftp_pause "$mode"
	if [[ "$mode" == ro ]]; then
		assert_sftp_runtime_ready_live
		return
	fi
	wait_for_existing_writer_connections_to_drain
	docker pause agentium-sftp >/dev/null
	assert_sftp_runtime_identity_live rw disabled 1
	connections="$(sudo_cmd ss -Htn state established "sport = :$(sftp_host_port)" | awk 'END {print NR + 0}')"
	fds="$(sftp_open_deposit_fd_count)"
	if [[ "$connections" -ne 0 || "$fds" -ne 0 ]]; then
		docker unpause agentium-sftp >/dev/null 2>&1 || true
		die "SFTP attesté non quiescent avant remount lecture seule"
	fi
	if ! set_secure_mode ro; then
		docker unpause agentium-sftp >/dev/null 2>&1 || true
		die "Remount Secure Deposit en lecture seule impossible"
	fi
	docker unpause agentium-sftp >/dev/null
	assert_secure_mode_in_namespaces ro
	assert_sftp_runtime_ready_live
}

capture_sftp_postgres_inventory() {
	local stage="$1" output="$2" temporary
	temporary="$DEPLOY_DIR/.${output##*/}.$$"
	[[ "$stage" == active || "$stage" == revoked ]] || die "Stage PostgreSQL SFTP invalide"
	assert_private "$FROZEN_SFTP_CANARY_LEDGER"
	[[ ! -e "$temporary" && ! -L "$temporary" ]] || die "Capture PostgreSQL SFTP concurrente"
	compose_audit run --rm --no-deps -T \
		-v "$FROZEN_SFTP_CANARY_LEDGER:/run/agentium-release-a/sftp-canary-ledger.json:ro" \
		--entrypoint python agentium-backend \
		-m scripts.audit_post_canary_database snapshot \
		--sha "$RELEASE_A_SHA" \
		--deployment-id "$DEPLOYMENT_ID" \
		--sftp-ledger /run/agentium-release-a/sftp-canary-ledger.json \
		--sftp-stage "$stage" >"$temporary"
	chmod 0600 "$temporary"
	verify_postgres_inventory_v2 "$temporary"
	if [[ -e "$output" || -L "$output" ]]; then
		assert_private "$output"
		cmp -s "$temporary" "$output" || { rm -f "$temporary"; die "Snapshot PostgreSQL SFTP rejoué divergent: $stage"; }
		rm -f "$temporary"
	else
		durable_replace "$temporary" "$output"
	fi
	assert_private "$output"
}

validate_sftp_postgres_receipt() {
	local receipt="$1"
	assert_private "$receipt"
	python3 -I - "$receipt" "$LIVE_SHA" "$RELEASE_A_SHA" "$(metadata sftp_release_sha)" "$DEPLOYMENT_ID" <<'PY'
import hashlib,json,re,sys
from datetime import datetime,timezone,timedelta
from pathlib import Path
def no_duplicates(pairs):
    value={}
    for key,item in pairs:
        if key in value: raise ValueError("duplicate JSON key")
        value[key]=item
    return value
raw=Path(sys.argv[1]).read_bytes()
try: p=json.loads(raw.decode("utf-8"),object_pairs_hook=no_duplicates)
except (UnicodeDecodeError,json.JSONDecodeError,ValueError) as exc: raise SystemExit("SFTP PostgreSQL receipt JSON differs") from exc
if raw!=json.dumps(p,separators=(",",":"),sort_keys=True).encode()+b"\n": raise SystemExit("SFTP PostgreSQL receipt is not canonical")
expected={"schema_version","kind","result","live_sha","release_a_sha","sftp_sha","deployment_id","hostname_sha256","workspace_id_sha256","link_id_sha256","access_id_sha256","credential_fingerprint_sha256","sftp_container_id","sftp_image_id","sftp_port","runtime_identity_sha256","link_status","auth_failed_reason","remaining_active_link_count","active_sftp_session_count","deposit_file_delta_count","audits","binding_sha256","collected_at"}
if set(p)!=expected or p.get("schema_version")!=1 or p.get("kind")!="agentium-release-a-sftp-postgres-ledger" or p.get("result")!="passed": raise SystemExit("SFTP PostgreSQL receipt schema differs")
if p.get("live_sha")!=sys.argv[2] or p.get("release_a_sha")!=sys.argv[3] or p.get("sftp_sha")!=sys.argv[4] or p.get("deployment_id")!=sys.argv[5]: raise SystemExit("SFTP PostgreSQL receipt identity differs")
if p.get("link_status")!="revoked" or p.get("auth_failed_reason")!="inactive_or_expired" or any(p.get(key)!=0 for key in ("remaining_active_link_count","active_sftp_session_count","deposit_file_delta_count")): raise SystemExit("SFTP PostgreSQL cleanup differs")
if any(re.fullmatch(r"[0-9a-f]{64}",str(p.get(key,""))) is None for key in ("hostname_sha256","workspace_id_sha256","link_id_sha256","access_id_sha256","credential_fingerprint_sha256","runtime_identity_sha256","binding_sha256")): raise SystemExit("SFTP PostgreSQL digest differs")
audits=p.get("audits")
names=("created","auth_success","revoked","auth_failed_inactive")
types=("deposit.link.created","deposit.sftp.auth.success","deposit.link.revoked","deposit.sftp.auth.failed")
if not isinstance(audits,dict) or set(audits)!=set(names): raise SystemExit("SFTP PostgreSQL audit ledger differs")
values=[str(p[key]) for key in ("live_sha","release_a_sha","sftp_sha","deployment_id","hostname_sha256","workspace_id_sha256","link_id_sha256","access_id_sha256","credential_fingerprint_sha256","sftp_container_id","sftp_image_id","sftp_port","runtime_identity_sha256","link_status","auth_failed_reason","remaining_active_link_count","active_sftp_session_count","deposit_file_delta_count")]
times=[]
for name,event_type in zip(names,types,strict=True):
    row=audits[name]
    if not isinstance(row,dict) or set(row)!={"event_type","event_id_sha256","event_digest_sha256","count","occurred_at"} or row.get("event_type")!=event_type or row.get("count")!=1: raise SystemExit("SFTP PostgreSQL audit row differs")
    if any(re.fullmatch(r"[0-9a-f]{64}",str(row.get(key,""))) is None for key in ("event_id_sha256","event_digest_sha256")): raise SystemExit("SFTP PostgreSQL audit digest differs")
    values.extend(str(row[key]) for key in ("event_type","event_id_sha256","event_digest_sha256","count","occurred_at"))
    times.append(datetime.fromisoformat(str(row["occurred_at"]).replace("Z","+00:00")))
collected=datetime.fromisoformat(str(p["collected_at"]).replace("Z","+00:00")); values.append(str(p["collected_at"]))
if any(value.tzinfo is None for value in (*times,collected)) or times!=sorted(times) or not times[-1]<=collected<=times[-1]+timedelta(minutes=5) or collected>datetime.now(timezone.utc)+timedelta(minutes=5): raise SystemExit("SFTP PostgreSQL chronology differs")
digest=hashlib.sha256(b"agentium-release-a-sftp-ledger-v1")
for value in values: digest.update(b"\0"); digest.update(value.encode("utf-8"))
if digest.hexdigest()!=p["binding_sha256"]: raise SystemExit("SFTP PostgreSQL receipt binding differs")
PY
}

capture_sftp_postgres_receipt() {
	local output="$1" temporary
	temporary="$DEPLOY_DIR/.${output##*/}.$$"
	assert_private "$POSTGRES_INVENTORY_AFTER"
	assert_private "$SFTP_POSTGRES_ACTIVE"
	assert_private "$SFTP_POSTGRES_FINAL"
	assert_private "$FROZEN_SFTP_CANARY_LEDGER"
	if [[ -e "$output" || -L "$output" ]]; then
		validate_sftp_postgres_receipt "$output"
		return
	fi
	[[ ! -e "$temporary" && ! -L "$temporary" ]] || die "Comparaison PostgreSQL SFTP concurrente"
	compose_audit run --rm --no-deps -T \
		-v "$POSTGRES_INVENTORY_AFTER:/run/agentium-release-a/postgres-baseline.json:ro" \
		-v "$SFTP_POSTGRES_ACTIVE:/run/agentium-release-a/postgres-active.json:ro" \
		-v "$SFTP_POSTGRES_FINAL:/run/agentium-release-a/postgres-final.json:ro" \
		-v "$FROZEN_SFTP_CANARY_LEDGER:/run/agentium-release-a/sftp-canary-ledger.json:ro" \
		--entrypoint python agentium-backend \
		-m scripts.audit_post_canary_database compare-sftp-canary \
		--sha "$RELEASE_A_SHA" \
		--deployment-id "$DEPLOYMENT_ID" \
		--baseline /run/agentium-release-a/postgres-baseline.json \
		--post-canary /run/agentium-release-a/postgres-active.json \
		--final /run/agentium-release-a/postgres-final.json \
		--sftp-ledger /run/agentium-release-a/sftp-canary-ledger.json >"$temporary"
	chmod 0600 "$temporary"
	validate_sftp_postgres_receipt "$temporary"
	if [[ -e "$output" || -L "$output" ]]; then
		rm -f "$temporary"
		die "Publication concurrente du reçu PostgreSQL SFTP"
	else
		durable_replace "$temporary" "$output"
	fi
	validate_sftp_postgres_receipt "$output"
}

revalidate_storage_after_resume() {
	local snapshot="$DEPLOY_DIR/.storage-resume.$$" comparison="$DEPLOY_DIR/.storage-resume-comparison.$$"
	snapshot_storage "$snapshot"
	"$FROZEN_STORAGE_HELPER" compare --before "$STORAGE_AFTER" --after "$snapshot" --output "$comparison"
	python3 -I - "$comparison" <<'PY'
import json,sys
p=json.load(open(sys.argv[1],encoding="utf-8"))
if p.get("result")!="passed" or p.get("failed_checks")!=[]:
    raise SystemExit("storage changed while Release A awaited validation")
PY
	rm -f "$snapshot" "$comparison"
}

reconcile_validation_pending() {
	assert_metadata
	assert_candidate_worktree
	assert_remote_release_a
	disable_writer_restarts
	install_gate_closed
	enter_writer_ingress_gates
	stop_writers
	set_secure_mode ro
	assert_writer_ingress_gates
	verify_candidate_storage_contract
	assert_stateful_runtime_identity
	activate_candidate
	verify_rabbitmq_candidate
	verify_qdrant_keys
	start_validation_runtime_under_gates
	assert_secure_mode_in_namespaces ro
	assert_writer_ingress_gates
	revalidate_storage_after_resume
}

revalidate_preconditions_evidence() {
	local temporary="$DEPLOY_DIR/.preconditions-evidence-recheck.$$"
	[[ -n "$PRECONDITIONS_EVIDENCE_ROOT" ]] || die "--preconditions-evidence-root requis juste avant la première mutation"
	[[ ! -e "$temporary" && ! -L "$temporary" ]] || die "Recheck de preuves concurrent"
	"$FROZEN_EVIDENCE_HELPER" verify-preconditions \
		--preconditions "$FROZEN_PRECONDITIONS" \
		--evidence-root "$PRECONDITIONS_EVIDENCE_ROOT" \
		--expected-live-sha "$LIVE_SHA" \
		--expected-release-a-sha "$RELEASE_A_SHA" \
		--expected-hostname "$(hostname -f)" \
		--deployment-id "$DEPLOYMENT_ID" \
		--output "$temporary" >/dev/null
	assert_private "$temporary"
	python3 -I - "$PRECONDITIONS_EVIDENCE_RECEIPT" "$temporary" <<'PY' || { rm -f "$temporary"; die "Recheck des preuves préconditions divergent"; }
import json,sys
original=json.load(open(sys.argv[1],encoding="utf-8")); fresh=json.load(open(sys.argv[2],encoding="utf-8"))
ignored={"verified_at"}
if {k:v for k,v in original.items() if k not in ignored}!={k:v for k,v in fresh.items() if k not in ignored}:
    raise SystemExit("fresh preconditions evidence differs from frozen receipt")
PY
	rm -f "$temporary"
}

verify_manifest_receipt() {
	local temporary="$DEPLOY_DIR/.manifest-receipt-recheck.$$"
	assert_private "$MANIFEST_RECEIPT"
	[[ ! -e "$temporary" && ! -L "$temporary" ]] || die "Recheck manifeste concurrent"
	if ! "$FROZEN_MANIFEST_HELPER" verify \
		--repository "$CANDIDATE_REPO" \
		--release-a-sha "$RELEASE_A_SHA" \
		--review-policy "$FROZEN_REVIEW" \
		--manifest "$FROZEN_MANIFEST" >"$temporary"; then
		rm -f "$temporary"
		die "Revalidation sémantique du manifeste refusée"
	fi
	assert_private "$temporary"
	python3 -I - "$MANIFEST_RECEIPT" "$temporary" "$RELEASE_A_SHA" <<'PY' || { rm -f "$temporary"; die "Reçu manifeste préexistant divergent"; }
import json,os,stat,sys
from datetime import datetime,timezone,timedelta
from pathlib import Path

def no_duplicates(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError(f"duplicate JSON key: {key}")
        result[key]=value
    return result

def private_json(path):
    path=Path(path); before=path.lstat()
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode) or before.st_uid!=os.geteuid() or stat.S_IMODE(before.st_mode)!=0o600 or before.st_nlink!=1 or not 0<before.st_size<=65536:
        raise SystemExit(f"unsafe manifest receipt: {path.name}")
    descriptor=os.open(path,os.O_RDONLY|getattr(os,"O_CLOEXEC",0)|getattr(os,"O_NOFOLLOW",0))
    try:
        opened=os.fstat(descriptor)
        if (opened.st_dev,opened.st_ino)!=(before.st_dev,before.st_ino): raise SystemExit("manifest receipt changed while opening")
        body=b""
        while len(body)<=65536:
            chunk=os.read(descriptor,min(65536,65537-len(body)))
            if not chunk: break
            body+=chunk
        after=os.fstat(descriptor)
        if len(body)>65536 or (opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns,opened.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns): raise SystemExit("manifest receipt changed while read")
    finally: os.close(descriptor)
    try: value=json.loads(body,object_pairs_hook=no_duplicates)
    except (UnicodeDecodeError,json.JSONDecodeError,ValueError) as exc: raise SystemExit("manifest receipt is not strict JSON") from exc
    return value

expected_keys={"profile","result","base_sha","release_a_sha","manifest_sha256","review_policy_sha256","verified_at"}
original,fresh=(private_json(path) for path in sys.argv[1:3])
for label,payload in (("existing",original),("fresh",fresh)):
    if not isinstance(payload,dict) or set(payload)!=expected_keys or payload.get("profile")!="agentium-release-a-diff-verification-v6" or payload.get("result")!="passed" or payload.get("release_a_sha")!=sys.argv[3]:
        raise SystemExit(f"{label} manifest receipt schema/identity differs")
    value=payload.get("verified_at")
    if not isinstance(value,str) or not value.endswith("Z"): raise SystemExit(f"{label} manifest receipt timestamp invalid")
    try: stamp=datetime.fromisoformat(value.removesuffix("Z")+"+00:00")
    except ValueError as exc: raise SystemExit(f"{label} manifest receipt timestamp invalid") from exc
    if stamp>datetime.now(timezone.utc)+timedelta(minutes=5): raise SystemExit(f"{label} manifest receipt is future-dated")
stable=expected_keys-{"verified_at"}
if {key:original[key] for key in stable}!={key:fresh[key] for key in stable}:
    raise SystemExit("existing manifest receipt does not match a fresh semantic verification")
PY
	rm -f "$temporary"
}

preflight_impl() {
	[[ "$(phase)" == new || "$(phase)" == preflight_ok ]] || die "Preflight hors phase"
	[[ -n "$PRECONDITIONS_EVIDENCE_ROOT" ]] || die "--preconditions-evidence-root requis au preflight"
	assert_candidate_worktree
	assert_remote_release_a
	assert_live_identity
	assert_nginx_unique_edge_topology
	assert_capacity_and_mounts
	assert_runtime_source_tree
	[[ "$MANIFEST_SHA256" =~ ^[0-9a-f]{64}$ && "$REVIEW_POLICY_SHA256" =~ ^[0-9a-f]{64}$ && "$PRECONDITIONS_SHA256" =~ ^[0-9a-f]{64}$ ]] || die "Digests preflight requis"
	stage_helpers
	copy_private_once "$MANIFEST" "$FROZEN_MANIFEST" "$MANIFEST_SHA256"
	copy_private_once "$REVIEW_POLICY" "$FROZEN_REVIEW" "$REVIEW_POLICY_SHA256"
	copy_private_once "$PRECONDITIONS" "$FROZEN_PRECONDITIONS" "$PRECONDITIONS_SHA256"
	EVIDENCE_AUTHORITY_KEYRING_SHA256="$(sha256sum "$FROZEN_EVIDENCE_AUTHORITY_KEYRING" | awk '{print $1}')"
	[[ "$EVIDENCE_AUTHORITY_KEYRING_SHA256" =~ ^[0-9a-f]{64}$ ]] || die "Digest du keyring d'autorité invalide"
	"$FROZEN_EVIDENCE_HELPER" verify-authority-keyring --authority-keyring "$FROZEN_EVIDENCE_AUTHORITY_KEYRING" >/dev/null
	if [[ ! -e "$MANIFEST_RECEIPT" && ! -L "$MANIFEST_RECEIPT" ]]; then
		temporary="$DEPLOY_DIR/.manifest-receipt.$$"
		"$FROZEN_MANIFEST_HELPER" verify --repository "$CANDIDATE_REPO" --release-a-sha "$RELEASE_A_SHA" --review-policy "$FROZEN_REVIEW" --manifest "$FROZEN_MANIFEST" >"$temporary"
		durable_replace "$temporary" "$MANIFEST_RECEIPT"
	fi
	verify_manifest_receipt
	if [[ ! -e "$PRECONDITIONS_RECEIPT" ]]; then
		"$FROZEN_PRECONDITIONS_HELPER" --preconditions "$FROZEN_PRECONDITIONS" --expected-live-sha "$LIVE_SHA" --expected-release-a-sha "$RELEASE_A_SHA" --expected-hostname "$(hostname -f)" --output "$PRECONDITIONS_RECEIPT"
	fi
	if [[ ! -e "$PRECONDITIONS_EVIDENCE_RECEIPT" ]]; then
		"$FROZEN_EVIDENCE_HELPER" verify-preconditions \
			--preconditions "$FROZEN_PRECONDITIONS" \
			--evidence-root "$PRECONDITIONS_EVIDENCE_ROOT" \
			--expected-live-sha "$LIVE_SHA" \
			--expected-release-a-sha "$RELEASE_A_SHA" \
			--expected-hostname "$(hostname -f)" \
			--deployment-id "$DEPLOYMENT_ID" \
			--output "$PRECONDITIONS_EVIDENCE_RECEIPT" >/dev/null
	fi
	assert_private "$MANIFEST_RECEIPT"; assert_private "$PRECONDITIONS_RECEIPT"; assert_private "$PRECONDITIONS_EVIDENCE_RECEIPT"
	if [[ ! -e "$SYSTEMD_ENV_SOURCE" ]]; then
		source_digest="$(sha256sum "$RUNTIME_ENV_SOURCE_ROOT/backend/.env" | awk '{print $1}')"
		copy_private_once "$RUNTIME_ENV_SOURCE_ROOT/backend/.env" "$SYSTEMD_ENV_SOURCE" "$source_digest"
	fi
	[[ "$(stat -c %a "$SYSTEMD_ENV_SOURCE")" == 600 ]] || die "Source systemd figée trop ouverte"
	if [[ ! -d "$RUNTIME_ENV_DIR" ]]; then
		"$FROZEN_ENV_HELPER" freeze --main-env "$RUNTIME_ENV_SOURCE_ROOT/docker/env/agentium.vm.env" --compose-dir "$RUNTIME_ENV_SOURCE_ROOT/docker" --systemd-env "$SYSTEMD_ENV_SOURCE" --bundle-dir "$RUNTIME_ENV_DIR" --source-owner-uid "$(id -u)" --sha "$RELEASE_A_SHA" --deployment-id "$DEPLOYMENT_ID" >/dev/null
	fi
	ENV_DIGEST="$(sha256sum "$RUNTIME_ENV_MANIFEST" | awk '{print $1}')"
	[[ "$ENV_DIGEST" =~ ^[0-9a-f]{64}$ ]] || die "Bundle env invalide"
	verify_immutable_runtime_credentials
	assert_new_principals_absent
	if [[ ! -e "$METADATA_FILE" ]]; then
		sftp_image="$(docker inspect --format '{{.Image}}' agentium-sftp)"
		sftp_sha="$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$sftp_image")"
		docker_engine_id="$(docker info --format '{{.ID}}')"
		[[ "$sftp_image" =~ ^sha256:[0-9a-f]{64}$ && "$sftp_sha" =~ ^[0-9a-f]{40}$ ]] || die "Identité SFTP non attestable"
		[[ "$docker_engine_id" =~ ^[A-Za-z0-9:_-]{8,128}$ ]] || die "Identité du daemon Docker local non attestable"
		temporary="$DEPLOY_DIR/.metadata.$$"
		{
			printf 'format\t2\ndeployment_id\t%s\nbranch\t%s\nlive_sha\t%s\nrelease_a_sha\t%s\ncandidate_sha\t%s\n' "$DEPLOYMENT_ID" "$BRANCH" "$LIVE_SHA" "$RELEASE_A_SHA" "$RELEASE_A_SHA"
			printf 'sftp_release_sha\t%s\nsftp_image_id\t%s\ndocker_engine_id\t%s\nenv_manifest_sha256\t%s\n' "$sftp_sha" "$sftp_image" "$docker_engine_id" "$ENV_DIGEST"
			printf 'manifest_sha256\t%s\nreview_policy_sha256\t%s\npreconditions_sha256\t%s\nevidence_authority_keyring_sha256\t%s\n' "$MANIFEST_SHA256" "$REVIEW_POLICY_SHA256" "$PRECONDITIONS_SHA256" "$EVIDENCE_AUTHORITY_KEYRING_SHA256"
			printf 'manifest_receipt_sha256\t%s\npreconditions_receipt_sha256\t%s\npreconditions_evidence_receipt_sha256\t%s\ncreated_at\t%s\n' \
				"$(sha256sum "$MANIFEST_RECEIPT" | awk '{print $1}')" \
				"$(sha256sum "$PRECONDITIONS_RECEIPT" | awk '{print $1}')" \
				"$(sha256sum "$PRECONDITIONS_EVIDENCE_RECEIPT" | awk '{print $1}')" \
				"$(date -u +%Y-%m-%dT%H:%M:%SZ)"
		} >"$temporary"
		durable_replace "$temporary" "$METADATA_FILE"
	fi
	assert_metadata
	record_runtime_state
	record_file_backup "$LIVE_REPO/backend/.env" "$SYSTEMD_ENV_BACKUP" "$SYSTEMD_ENV_ATTRS"
	record_file_backup "$LIVE_REPO/docker/env/agentium.vm.env" "$MAIN_ENV_BACKUP" "$MAIN_ENV_ATTRS"
	record_file_backup "$LIVE_REPO/docker/env/agentium.env" "$APPLICATION_ENV_BACKUP" "$APPLICATION_ENV_ATTRS"
	record_file_backup "$LIVE_REPO/docker/env/qdrant.agentium.env" "$QDRANT_ENV_BACKUP" "$QDRANT_ENV_ATTRS"
	record_file_backup "$LIVE_REPO/docker/env/keycloak.agentium.env" "$KEYCLOAK_ENV_BACKUP" "$KEYCLOAK_ENV_ATTRS"
	if sudo_cmd test -f /etc/systemd/system/agentium-backend.service; then
		sudo_cmd install -m 0600 /etc/systemd/system/agentium-backend.service "$SYSTEMD_UNIT_BACKUP"
		sudo_cmd chown "$(id -u):$(id -g)" "$SYSTEMD_UNIT_BACKUP"
		atomic_text "$SYSTEMD_UNIT_ATTRS" "$(sudo_cmd stat -c '%a:%u:%g:%h' /etc/systemd/system/agentium-backend.service)"
	fi
	set_phase preflight_ok
	ok "Release A preflight vérifié; aucune mutation live"
}

prepare_impl() {
	assert_metadata; assert_candidate_worktree; assert_remote_release_a; assert_live_identity; assert_capacity_and_mounts
	case "$(phase)" in
	prepared) ensure_candidate_image_override; ok "Release A déjà préparée"; return ;;
	preflight_ok) ;;
	*) die "prepare hors phase" ;;
	esac
	# A crash after publishing the OCI receipt but before the phase fsync must
	# not rebuild or silently replace the already-attested local tags.
	if [[ -e "$CANDIDATE_OCI_RECEIPT" || -L "$CANDIDATE_OCI_RECEIPT" ]]; then
		[[ -s "$ROLLBACK_STATE" ]] || die "Reçu OCI candidat sans état de rollback immuable"
		ensure_candidate_image_override
		set_phase prepared
		ok "Images Release A déjà construites et attestées"
		return
	fi
	env -i PATH="$COMPOSE_CLEAN_PATH" HOME="$DEPLOY_HOME" DOCKER_CONFIG="$DEPLOY_HOME/.docker" DOCKER_HOST="$DOCKER_LOCAL_HOST" \
		AGENTIUM_SAFE_DEPLOY_ORCHESTRATED=1 AGENTIUM_SAFE_DEPLOYMENT_DIR="$DEPLOY_DIR" AGENTIUM_DEPLOY_STATE_DIR="$DEPLOY_DIR/rollback" \
		AGENTIUM_SAFE_ENV_BUNDLE_DIR="$RUNTIME_ENV_DIR" AGENTIUM_SAFE_ENV_MANIFEST_SHA256="$ENV_DIGEST" AGENTIUM_SAFE_ENV_BUNDLE_HELPER="$FROZEN_ENV_HELPER" \
		AGENTIUM_SAFE_QDRANT_OVERRIDE_FILE="$FROZEN_QDRANT_OVERRIDE" AGENTIUM_QDRANT_EFFECTIVE_API_KEY="$(env_value application QDRANT_API_KEY)" \
		AGENTIUM_CELERY_BEAT=0 AGENTIUM_STARTUP_RECONCILIATION=disabled OMNIRAG_REPO_DIR="$CANDIDATE_REPO" \
		bash "$FROZEN_DEPLOYER" --build-only --branch "$BRANCH" --sha "$RELEASE_A_SHA" --previous-sha "$LIVE_SHA" --services 'agentium-backend agentium-frontend agentium-worker-cpu'
	[[ -s "$ROLLBACK_STATE" ]] || die "État de rollback immuable absent"
	capture_candidate_oci_receipt
	ensure_candidate_image_override
	set_phase prepared
	ok "Images Release A construites dans le worktree persistant"
}

install_gate_closed() {
	gate install-closed
	[[ "$(gate status)" == closed ]] || die "Gate HTTP non fermé"
	assert_nginx_unique_edge_topology
}

adopt_stateful_security() {
	# Compose uses the frozen private env.  No volume or bind is recreated; only
	# the exact Qdrant/MinIO service definitions are reconciled under maintenance.
	verify_candidate_storage_contract
	if [[ ! -e "$STATEFUL_ADOPTION_INTENT" && ! -L "$STATEFUL_ADOPTION_INTENT" ]]; then
		atomic_text "$STATEFUL_ADOPTION_INTENT" "format=1 deployment_id=$DEPLOYMENT_ID release_a_sha=$RELEASE_A_SHA one_way=true"
	fi
	assert_private "$STATEFUL_ADOPTION_INTENT"
	[[ "$(cat "$STATEFUL_ADOPTION_INTENT")" == "format=1 deployment_id=$DEPLOYMENT_ID release_a_sha=$RELEASE_A_SHA one_way=true" ]] || die "Intent adoption stateful divergent"
	compose --profile infra up -d --no-build --no-deps agentium-qdrant agentium-minio
	compose --profile tools run --rm --no-deps agentium-minio-init
	# Rebuild the expected content on every replay.  The Compose bootstrap has
	# just re-authenticated the exact application credentials and compared the
	# whitespace-normalized fixed IAM policy exactly; an existing proof is
	# accepted only when it is the exact proof those frozen credentials produce.
	main_env="$("$FROZEN_ENV_HELPER" role-path --bundle-dir "$RUNTIME_ENV_DIR" --sha "$RELEASE_A_SHA" --deployment-id "$DEPLOYMENT_ID" --expected-manifest-sha256 "$ENV_DIGEST" --role compose_main)"
	app_env="$("$FROZEN_ENV_HELPER" role-path --bundle-dir "$RUNTIME_ENV_DIR" --sha "$RELEASE_A_SHA" --deployment-id "$DEPLOYMENT_ID" --expected-manifest-sha256 "$ENV_DIGEST" --role application)"
	temporary="$DEPLOY_DIR/.minio-proof.$$"
	[[ ! -e "$temporary" && ! -L "$temporary" ]] || die "Preuve MinIO temporaire concurrente"
	python3 -I - "$main_env" "$app_env" "$temporary" <<'PY'
import hashlib,json,os,re,sys
from pathlib import Path
def read(path):
    values={}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        key,sep,value=raw.strip().partition("=")
        if sep and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",key):
            if len(value)>=2 and value[0]==value[-1] and value[0] in "\"'": value=value[1:-1]
            values[key]=value
    return values
main,app=read(sys.argv[1]),read(sys.argv[2])
root_user,root_password=main.get("AGENTIUM_MINIO_ROOT_USER",""),main.get("AGENTIUM_MINIO_ROOT_PASSWORD","")
app_user,app_password=app.get("OBJECT_STORE_S3_ACCESS_KEY",""),app.get("OBJECT_STORE_S3_SECRET_KEY","")
if not all((root_user,root_password,app_user,app_password)): raise SystemExit("MinIO credentials are incomplete")
root=(root_user+"\0"+root_password).encode(); application=(app_user+"\0"+app_password).encode()
if root==application: raise SystemExit("MinIO credentials are not separated")
p={"schema_version":1,"kind":"agentium-release-a-minio-bootstrap","result":"passed","versioning":"Enabled","application_credential_fingerprint_sha256":hashlib.sha256(application).hexdigest(),"root_credential_fingerprint_sha256":hashlib.sha256(root).hexdigest(),"application_policy":"object_get_put_list_without_delete_or_admin","delete_denied":True,"config_denied":True}
fd=os.open(sys.argv[3],os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,"w") as h: json.dump(p,h,separators=(",",":"),sort_keys=True); h.write("\n"); h.flush(); os.fsync(h.fileno())
PY
	if [[ -e "$MINIO_PROOF" || -L "$MINIO_PROOF" ]]; then
		assert_private "$MINIO_PROOF"
		cmp -s "$temporary" "$MINIO_PROOF" || die "Preuve MinIO rejouée divergente"
		rm -f "$temporary"
	else
		durable_replace "$temporary" "$MINIO_PROOF"
	fi
	assert_private "$MINIO_PROOF"
	bootstrap_rabbitmq
}

activate_candidate() {
	# Resolve the prepared receipt once into an exact-ID Compose override. The
	# deployer and the later Qdrant writer transition consume the same bytes.
	ensure_candidate_image_override
	env -i PATH="$COMPOSE_CLEAN_PATH" HOME="$DEPLOY_HOME" DOCKER_CONFIG="$DEPLOY_HOME/.docker" DOCKER_HOST="$DOCKER_LOCAL_HOST" \
		AGENTIUM_SAFE_DEPLOY_ORCHESTRATED=1 AGENTIUM_SAFE_DEPLOYMENT_DIR="$DEPLOY_DIR" AGENTIUM_DEPLOY_STATE_DIR="$DEPLOY_DIR/rollback" \
		AGENTIUM_SAFE_ENV_BUNDLE_DIR="$RUNTIME_ENV_DIR" AGENTIUM_SAFE_ENV_MANIFEST_SHA256="$ENV_DIGEST" AGENTIUM_SAFE_ENV_BUNDLE_HELPER="$FROZEN_ENV_HELPER" \
		AGENTIUM_SAFE_QDRANT_OVERRIDE_FILE="$FROZEN_QDRANT_OVERRIDE" AGENTIUM_SAFE_CANDIDATE_IMAGE_OVERRIDE_FILE="$CANDIDATE_IMAGE_OVERRIDE" AGENTIUM_QDRANT_EFFECTIVE_API_KEY="$(env_value application QDRANT_API_KEY)" \
		AGENTIUM_CELERY_BEAT=0 AGENTIUM_STARTUP_RECONCILIATION=disabled OMNIRAG_REPO_DIR="$LIVE_REPO" \
		bash "$FROZEN_DEPLOYER" --activate-only --defer-auxiliary-start --branch "$BRANCH" --sha "$RELEASE_A_SHA" --previous-sha "$LIVE_SHA" --services 'agentium-backend agentium-frontend agentium-worker-cpu'
}

reconcile_closed_adoption() {
	assert_metadata; assert_candidate_worktree; assert_remote_release_a; assert_capacity_and_mounts
	install_gate_closed
	enter_writer_ingress_gates
	assert_writer_ingress_gates
	disable_and_stop_writers
	set_secure_mode ro
	ensure_postgres_backup_and_restore_rehearsal
	if [[ ! -e "$STORAGE_BEFORE" ]]; then snapshot_storage "$STORAGE_BEFORE" 1; fi
	verify_candidate_storage_contract
	write_checkout_intent
	[[ -z "$(git -C "$LIVE_REPO" status --porcelain --untracked-files=no)" ]] || die "Hotfix suivi détecté sur le checkout live"
	if [[ "$(git -C "$LIVE_REPO" rev-parse HEAD)" == "$LIVE_SHA" ]]; then git -C "$LIVE_REPO" reset --hard "$RELEASE_A_SHA"; fi
	[[ "$(git -C "$LIVE_REPO" rev-parse HEAD)" == "$RELEASE_A_SHA" ]] || die "Checkout Release A ambigu"
	publish_runtime_env_files
	systemd_env="$("$FROZEN_ENV_HELPER" role-path --bundle-dir "$RUNTIME_ENV_DIR" --sha "$RELEASE_A_SHA" --deployment-id "$DEPLOYMENT_ID" --expected-manifest-sha256 "$ENV_DIGEST" --role systemd)"
	sudo_cmd env AGENTIUM_BACKEND_UNIT_SOURCE="$FROZEN_SYSTEMD_UNIT" AGENTIUM_BACKEND_EXPECTED_SHA="$RELEASE_A_SHA" AGENTIUM_SAFE_DEPLOY_ORCHESTRATED=1 AGENTIUM_SAFE_DEPLOYMENT_DIR="$DEPLOY_DIR" AGENTIUM_BACKEND_ENV_FILE="$systemd_env" AGENTIUM_BACKEND_ENV_DROPIN_STATE="$DEPLOY_DIR/systemd-env-dropin.state" AGENTIUM_BACKEND_ENV_DROPIN_BACKUP="$DEPLOY_DIR/systemd-env-dropin.previous" "$FROZEN_SYSTEMD_INSTALLER" install
	adopt_stateful_security
	assert_stateful_runtime_identity
	activate_candidate
	verify_rabbitmq_candidate
	verify_qdrant_keys
	assert_stateful_runtime_identity
	if [[ ! -e "$POSTGRES_INVENTORY_AFTER" ]]; then capture_postgres_inventory "$POSTGRES_INVENTORY_AFTER"; fi
	compare_postgres_inventory_v2 "$POSTGRES_INVENTORY_BEFORE" "$POSTGRES_INVENTORY_AFTER" || die "Inventaire PostgreSQL métier modifié pendant Release A"
	capture_postgres_comparison "$POSTGRES_INVENTORY_BEFORE" "$POSTGRES_INVENTORY_AFTER"
	start_validation_runtime_under_gates
	assert_secure_mode_in_namespaces ro
	assert_writer_ingress_gates
	[[ "$(docker inspect --format '{{.Image}}' agentium-sftp)" == "$(metadata sftp_image_id)" ]] || die "Image SFTP remplacée"
	[[ "$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}' agentium-sftp)" == no ]] || die "SFTP peut redémarrer avant attestation"
	if [[ ! -e "$STORAGE_AFTER" ]]; then snapshot_storage "$STORAGE_AFTER"; fi
	if [[ ! -e "$STORAGE_COMPARISON" ]]; then "$FROZEN_STORAGE_HELPER" compare --release-a-versioning-adoption --before "$STORAGE_BEFORE" --after "$STORAGE_AFTER" --output "$STORAGE_COMPARISON"; fi
	set_phase validation_pending
}

apply_impl() {
	case "$(phase)" in
	prepared) ;;
	closing_intent | maintenance_closed | adopting | validation_pending) ;;
	*) die "apply hors phase" ;;
	esac
	[[ "$(phase)" != validation_pending ]] || { ok "Release A déjà en attente d'attestation"; return; }
	if [[ "$(phase)" == prepared ]]; then
		revalidate_preconditions_evidence
		# Durable fail-closed controls must win before the intent is published.
		# A crash before this fsync remains `prepared`, but replay sees the
		# already-closed gates and restart=no writers and can safely continue.
		disable_writer_restarts
		install_gate_closed
		enter_writer_ingress_gates
		stop_writers
		assert_writer_ingress_gates
		set_phase closing_intent
	fi
	[[ "$(phase)" != closing_intent ]] || set_phase maintenance_closed
	set_phase adopting
	reconcile_closed_adoption
	ok "Release A adoptée sous maintenance; reboot contrôlé et cycle SFTP attesté requis"
}

resume_impl() {
	case "$(phase)" in
	closing_intent)
		set_phase maintenance_closed
		set_phase adopting
		reconcile_closed_adoption
		;;
	maintenance_closed)
		set_phase adopting
		reconcile_closed_adoption
		;;
	adopting) reconcile_closed_adoption ;;
	validation_pending)
		if [[ -e "$SFTP_RUNTIME_READY" || -L "$SFTP_RUNTIME_READY" ]]; then
			arm_sftp_canary_impl
		else
			reconcile_validation_pending
		fi
		;;
	sftp_canary_pending | sftp_canary_active_recorded)
		assert_metadata
		assert_candidate_worktree
		assert_remote_release_a
		install_gate_closed
		enter_writer_ingress_gates
		assert_writer_ingress_gates
		assert_secure_mode_in_namespaces ro
		start_sftp_canary_control_plane
		;;
	sftp_canary_recorded)
		assert_metadata
		assert_candidate_worktree
		assert_remote_release_a
		install_gate_closed
		enter_writer_ingress_gates
		assert_sftp_canary_control_plane_stopped
		;;
	opening_forward | opened) reconcile_forward_open ;;
	completed) reconcile_forward_committed_open; ok "Release A complète et réouverture réconciliée"; return ;;
	*) die "resume hors phase" ;;
	esac
	ok "Réconciliation Release A terminée; gate maintenu fermé"
}

arm_sftp_canary_impl() {
	case "$(phase)" in
	sftp_canary_pending | sftp_canary_active_recorded)
		start_sftp_canary_control_plane
		ok "Runtime SFTP canari déjà armé et inchangé"
		return
		;;
	sftp_canary_recorded)
		assert_sftp_canary_control_plane_stopped
		ok "Cycle SFTP canari déjà révoqué et fermé"
		return
		;;
	validation_pending) ;;
	*) die "arm-sftp-canary hors phase" ;;
	esac
	assert_metadata
	assert_candidate_worktree
	assert_remote_release_a
	disable_writer_restarts
	install_gate_closed
	enter_writer_ingress_gates
	if [[ -e "$SFTP_RUNTIME_READY" || -L "$SFTP_RUNTIME_READY" ]]; then
		# A SIGKILL after the durable receipt but before the phase fsync must
		# never stop/restart the attested process: StartedAt is part of the
		# positive-canary identity and cannot be reconstructed afterwards.
		assert_sftp_runtime_ready_live
		set_phase sftp_canary_pending
		start_sftp_canary_control_plane
		ok "Armement SFTP repris sans changement de processus"
		return
	fi
	stop_writers
	set_secure_mode ro
	assert_writer_ingress_gates
	assert_secure_mode_in_namespaces ro
	[[ "$(awk -F '\t' '$1=="container" && $2=="agentium-sftp" {print $3}' "$RUNTIME_STATE")" == true ]] ||
		die "Le SFTP historique n'était pas actif; armement interdit"
	[[ "$(docker inspect --format '{{.Image}}' agentium-sftp)" == "$(metadata sftp_image_id)" ]] || die "Image SFTP remplacée avant armement"
	docker start agentium-sftp >/dev/null
	docker update --restart=no agentium-sftp >/dev/null
	for _ in $(seq 1 60); do
		[[ "$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' agentium-sftp)" == healthy ]] && break
		sleep 1
	done
	[[ "$(docker inspect --format '{{.State.Running}}:{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}:{{.HostConfig.RestartPolicy.Name}}:{{.HostConfig.RestartPolicy.MaximumRetryCount}}' agentium-sftp)" == true:healthy:no:0 ]] ||
		die "Runtime SFTP canari non sain"
	capture_sftp_runtime_ready
	set_phase sftp_canary_pending
	start_sftp_canary_control_plane
	ok "Runtime SFTP exact armé; API canari loopback isolée sous ingress fermé et /dev/sdc en lecture seule"
}

record_sftp_active_impl() {
	case "$(phase)" in
	sftp_canary_active_recorded)
		start_sftp_canary_control_plane
		capture_sftp_postgres_inventory active "$SFTP_POSTGRES_ACTIVE"
		ok "État SFTP actif déjà enregistré et control plane réattesté"
		return
		;;
	sftp_canary_pending) ;;
	*) die "record-sftp-active hors phase" ;;
	esac
	[[ -n "$SFTP_CANARY_LEDGER" && "$SFTP_CANARY_LEDGER_SHA256" =~ ^[0-9a-f]{64}$ ]] ||
		die "Ledger SFTP privé et digest requis"
	start_sftp_canary_control_plane
	wait_for_existing_writer_connections_to_drain
	copy_private_once "$SFTP_CANARY_LEDGER" "$FROZEN_SFTP_CANARY_LEDGER" "$SFTP_CANARY_LEDGER_SHA256"
	capture_sftp_postgres_inventory active "$SFTP_POSTGRES_ACTIVE"
	set_phase sftp_canary_active_recorded
	ok "Principal SFTP actif et authentification positive enregistrés; révocation requise"
}

record_sftp_final_impl() {
	case "$(phase)" in
	sftp_canary_recorded)
		assert_sftp_canary_control_plane_stopped
		capture_sftp_postgres_inventory revoked "$SFTP_POSTGRES_FINAL"
		capture_sftp_postgres_receipt "$SFTP_POSTGRES_RECEIPT"
		ok "Cycle SFTP révoqué déjà enregistré"
		return
		;;
	sftp_canary_active_recorded) ;;
	*) die "record-sftp-final hors phase" ;;
	esac
	assert_sftp_canary_control_plane
	wait_for_existing_writer_connections_to_drain
	capture_sftp_postgres_inventory revoked "$SFTP_POSTGRES_FINAL"
	capture_sftp_postgres_receipt "$SFTP_POSTGRES_RECEIPT"
	stop_sftp_canary_control_plane
	set_phase sftp_canary_recorded
	ok "Révocation SFTP, refus post-révocation et ledger PostgreSQL enregistrés"
}

assert_attestation_receipt() {
	assert_private "$FROZEN_ATTESTATION"; assert_private "$ATTESTATION_RECEIPT"
	assert_private "$PRECONDITIONS_EVIDENCE_RECEIPT"; assert_private "$FINAL_EVIDENCE_RECEIPT"
	assert_private "$FINAL_EVIDENCE_BINDING_MANIFEST"
	"$FROZEN_EVIDENCE_HELPER" verify-final-frozen \
		--attestation "$FROZEN_ATTESTATION" \
		--preconditions-receipt "$PRECONDITIONS_EVIDENCE_RECEIPT" \
		--evidence-receipt "$FINAL_EVIDENCE_RECEIPT" \
		--binding-manifest "$FINAL_EVIDENCE_BINDING_MANIFEST" \
		--evidence-root "$FROZEN_FINAL_EVIDENCE_DIR" \
		--journal-root "$DEPLOY_DIR" \
		--authority-keyring "$FROZEN_EVIDENCE_AUTHORITY_KEYRING" \
		--expected-authority-keyring-sha256 "$(metadata evidence_authority_keyring_sha256)" \
		--expected-live-sha "$LIVE_SHA" \
		--expected-release-a-sha "$RELEASE_A_SHA" \
		--expected-sftp-sha "$(metadata sftp_release_sha)" \
		--expected-hostname "$(hostname -f)" \
		--deployment-id "$DEPLOYMENT_ID" >/dev/null
	python3 -I - "$FROZEN_ATTESTATION" "$ATTESTATION_RECEIPT" "$PRECONDITIONS_EVIDENCE_RECEIPT" "$FINAL_EVIDENCE_RECEIPT" "$FROZEN_PRECONDITIONS" "$LIVE_SHA" "$RELEASE_A_SHA" "$(metadata sftp_release_sha)" "$DEPLOYMENT_ID" "$(hostname -f)" <<'PY'
import hashlib,json,sys
from datetime import datetime,timezone
attestation,receipt,pre_evidence,final_evidence,preconditions=sys.argv[1:6]
live_sha,expected,sftp_sha,deployment_id,hostname=sys.argv[6:]
p=json.load(open(receipt,encoding="utf-8"))
if set(p)!={"schema_version","kind","result","environment","release_a_sha","sftp_release_sha","hostname_sha256","attestation_sha256","evidence_sha256","verified_at","fresh_until"}:
    raise SystemExit("attestation receipt schema differs")
if p["schema_version"]!=4 or p["kind"]!="agentium-release-a-verification-receipt" or p["result"]!="passed" or p["release_a_sha"]!=expected or p["sftp_release_sha"]!=sftp_sha:
    raise SystemExit("attestation receipt identity/result differs")
if p["attestation_sha256"]!=hashlib.sha256(open(attestation,"rb").read()).hexdigest():
    raise SystemExit("attestation receipt digest differs")
fresh=datetime.fromisoformat(p["fresh_until"].replace("Z","+00:00"))
if fresh < datetime.now(timezone.utc):
    raise SystemExit("attestation receipt expired")
pre_bytes=open(pre_evidence,"rb").read(); pre=json.loads(pre_bytes)
final=json.load(open(final_evidence,encoding="utf-8"))
pre_keys={"schema_version","kind","result","environment","deployment_id","live_sha","release_a_sha","hostname_sha256","preconditions_sha256","evidence_file_count","evidence_digest_count","evidence_reference_count","evidence_set_sha256","restore_proof_set_sha256","capacity_proof_set_sha256","verified_at"}
final_keys={"schema_version","kind","result","environment","deployment_id","live_sha","release_a_sha","sftp_release_sha","hostname_sha256","attestation_sha256","preconditions_receipt_sha256","preconditions_sha256","evidence_file_count","evidence_digest_count","evidence_reference_count","evidence_set_sha256","binding_manifest_sha256","authority_keyring_sha256","canonical_reference_count","external_reference_count","external_provenance_set_sha256","verified_at"}
if set(pre)!=pre_keys or set(final)!=final_keys:
    raise SystemExit("evidence receipt schema differs")
host_digest=hashlib.sha256(hostname.encode()).hexdigest()
common={"schema_version":1,"result":"passed","environment":"production","deployment_id":deployment_id,"live_sha":live_sha,"release_a_sha":expected,"hostname_sha256":host_digest}
if any(pre.get(k)!=v for k,v in common.items()) or pre.get("kind")!="agentium-release-a-preconditions-evidence-receipt":
    raise SystemExit("preconditions evidence receipt identity differs")
if any(final.get(k)!=v for k,v in common.items()) or final.get("kind")!="agentium-release-a-final-evidence-receipt" or final.get("sftp_release_sha")!=sftp_sha:
    raise SystemExit("final evidence receipt identity differs")
if pre.get("preconditions_sha256")!=hashlib.sha256(open(preconditions,"rb").read()).hexdigest():
    raise SystemExit("preconditions evidence input digest differs")
if final.get("preconditions_sha256")!=pre.get("preconditions_sha256") or final.get("preconditions_receipt_sha256")!=hashlib.sha256(pre_bytes).hexdigest():
    raise SystemExit("final evidence precondition binding differs")
if final.get("attestation_sha256")!=hashlib.sha256(open(attestation,"rb").read()).hexdigest():
    raise SystemExit("final evidence attestation digest differs")
for row,key in ((pre,"preconditions"),(final,"final")):
    digest_fields=("evidence_set_sha256",) if key=="preconditions" else ("evidence_set_sha256","binding_manifest_sha256","authority_keyring_sha256","external_provenance_set_sha256")
    for field in digest_fields:
        if not isinstance(row.get(field),str) or len(row[field])!=64 or any(c not in "0123456789abcdef" for c in row[field]):
            raise SystemExit(f"{key} evidence digest invalid")
    for field in ("evidence_file_count","evidence_digest_count","evidence_reference_count"):
        if isinstance(row.get(field),bool) or not isinstance(row.get(field),int) or not 1 <= row[field] <= 256:
            raise SystemExit(f"{key} evidence count invalid")
if final.get("evidence_reference_count")!=37 or final.get("canonical_reference_count")!=23 or final.get("external_reference_count")!=14:
    raise SystemExit("final evidence binding cardinality differs")
PY
}

assert_completion_receipt() {
	local artifact
	for artifact in "$COMPLETION_RECEIPT" "$ATTESTATION_RECEIPT" "$FINAL_EVIDENCE_RECEIPT" "$MANIFEST_RECEIPT" "$PRECONDITIONS_RECEIPT" "$PRECONDITIONS_EVIDENCE_RECEIPT" "$RUNTIME_OCI_RECEIPT" "$SFTP_RUNTIME_READY" "$SFTP_POSTGRES_RECEIPT"; do assert_private "$artifact"; done
	python3 -I - "$COMPLETION_RECEIPT" "$DEPLOYMENT_ID" "$RELEASE_A_SHA" "$ATTESTATION_RECEIPT" "$FINAL_EVIDENCE_RECEIPT" "$MANIFEST_RECEIPT" "$PRECONDITIONS_RECEIPT" "$PRECONDITIONS_EVIDENCE_RECEIPT" "$RUNTIME_OCI_RECEIPT" "$SFTP_RUNTIME_READY" "$SFTP_POSTGRES_RECEIPT" <<'PY'
import hashlib,json,os,re,stat,sys
from datetime import datetime,timezone,timedelta
from pathlib import Path
receipt_path=Path(sys.argv[1]); deployment_id,release_sha=sys.argv[2:4]; paths=list(map(Path,sys.argv[4:]))
def private_bytes(path,maximum=2*1024*1024):
    before=path.lstat()
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode) or before.st_uid!=os.geteuid() or stat.S_IMODE(before.st_mode)!=0o600 or before.st_nlink!=1 or not 0<before.st_size<=maximum:
        raise SystemExit(f"unsafe completion artifact: {path.name}")
    descriptor=os.open(path,os.O_RDONLY|getattr(os,"O_CLOEXEC",0)|getattr(os,"O_NOFOLLOW",0))
    try:
        opened=os.fstat(descriptor)
        if (opened.st_dev,opened.st_ino)!=(before.st_dev,before.st_ino): raise SystemExit("completion artifact changed while opening")
        body=b""
        while len(body)<=maximum:
            chunk=os.read(descriptor,min(65536,maximum+1-len(body)))
            if not chunk: break
            body+=chunk
        after=os.fstat(descriptor)
        if len(body)>maximum or (opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns,opened.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns): raise SystemExit("completion artifact changed while read")
        return body
    finally: os.close(descriptor)
def obj(body,label):
    def no_duplicates(pairs):
        result={}
        for key,value in pairs:
            if key in result: raise ValueError(f"duplicate JSON key: {key}")
            result[key]=value
        return result
    try:
        value=json.loads(body,object_pairs_hook=no_duplicates)
    except (UnicodeDecodeError,json.JSONDecodeError,ValueError) as exc: raise SystemExit(f"invalid {label} JSON") from exc
    if not isinstance(value,dict): raise SystemExit(f"invalid {label} object")
    return value
receipt=obj(private_bytes(receipt_path),"completion receipt")
expected={"schema_version","kind","result","deployment_id","release_a_sha","release_a_attestation_receipt_sha256","final_evidence_receipt_sha256","manifest_receipt_sha256","preconditions_receipt_sha256","preconditions_evidence_receipt_sha256","runtime_oci_receipt_sha256","sftp_runtime_ready_receipt_sha256","sftp_postgres_ledger_receipt_sha256","completed_at"}
if set(receipt)!=expected or receipt.get("schema_version")!=3 or receipt.get("kind")!="agentium-release-a-transaction-receipt" or receipt.get("result")!="passed" or receipt.get("deployment_id")!=deployment_id or receipt.get("release_a_sha")!=release_sha:
    raise SystemExit("completion receipt schema/identity differs")
keys=("release_a_attestation_receipt_sha256","final_evidence_receipt_sha256","manifest_receipt_sha256","preconditions_receipt_sha256","preconditions_evidence_receipt_sha256","runtime_oci_receipt_sha256","sftp_runtime_ready_receipt_sha256","sftp_postgres_ledger_receipt_sha256")
bound=[]
for key,path in zip(keys,paths,strict=True):
    body=private_bytes(path); digest=hashlib.sha256(body).hexdigest()
    if receipt.get(key)!=digest or re.fullmatch(r"[0-9a-f]{64}",digest) is None: raise SystemExit(f"completion receipt binding differs: {path.name}")
    bound.append(obj(body,path.name))
def stamp(owner,key):
    value=owner.get(key)
    if not isinstance(value,str) or not value.endswith("Z"): raise SystemExit(f"completion chronology invalid: {key}")
    try: return datetime.fromisoformat(value.removesuffix("Z")+"+00:00")
    except ValueError as exc: raise SystemExit(f"completion chronology invalid: {key}") from exc
attestation_at=stamp(bound[0],"verified_at"); final_at=stamp(bound[1],"verified_at"); runtime_at=stamp(bound[5],"verified_at"); ready_at=stamp(bound[6],"ready_at"); ledger_at=stamp(bound[7],"collected_at"); completed_at=stamp(receipt,"completed_at")
if not ready_at<=ledger_at<=attestation_at<=final_at<=runtime_at<=completed_at: raise SystemExit("completion receipt chronology differs")
if bound[6].get("schema_version")!=1 or bound[6].get("kind")!="agentium-release-a-sftp-runtime-ready" or bound[6].get("result")!="passed" or bound[6].get("deployment_id")!=deployment_id or bound[6].get("release_a_sha")!=release_sha:
    raise SystemExit("completion runtime-ready identity differs")
if bound[7].get("schema_version")!=1 or bound[7].get("kind")!="agentium-release-a-sftp-postgres-ledger" or bound[7].get("result")!="passed" or bound[7].get("deployment_id")!=deployment_id or bound[7].get("release_a_sha")!=release_sha:
    raise SystemExit("completion SFTP ledger identity differs")
for key in ("live_sha","sftp_sha","hostname_sha256","sftp_container_id","sftp_image_id","sftp_port","runtime_identity_sha256"):
    if bound[6].get(key)!=bound[7].get(key): raise SystemExit(f"completion SFTP runtime binding differs: {key}")
if completed_at>datetime.now(timezone.utc)+timedelta(minutes=5): raise SystemExit("completion receipt is future-dated")
PY
}

publish_completion_receipt() {
	if [[ -e "$COMPLETION_RECEIPT" || -L "$COMPLETION_RECEIPT" ]]; then assert_completion_receipt; return; fi
	assert_private "$RUNTIME_OCI_RECEIPT"
	local temporary="$DEPLOY_DIR/.transaction-receipt.$$"
	python3 -I - "$temporary" "$DEPLOYMENT_ID" "$RELEASE_A_SHA" "$ATTESTATION_RECEIPT" "$FINAL_EVIDENCE_RECEIPT" "$MANIFEST_RECEIPT" "$PRECONDITIONS_RECEIPT" "$PRECONDITIONS_EVIDENCE_RECEIPT" "$RUNTIME_OCI_RECEIPT" "$SFTP_RUNTIME_READY" "$SFTP_POSTGRES_RECEIPT" <<'PY'
import hashlib,json,os,sys
from datetime import datetime,timezone
from pathlib import Path
out=Path(sys.argv[1]); files=list(map(Path,sys.argv[4:]))
p={"schema_version":3,"kind":"agentium-release-a-transaction-receipt","result":"passed","deployment_id":sys.argv[2],"release_a_sha":sys.argv[3],"release_a_attestation_receipt_sha256":hashlib.sha256(files[0].read_bytes()).hexdigest(),"final_evidence_receipt_sha256":hashlib.sha256(files[1].read_bytes()).hexdigest(),"manifest_receipt_sha256":hashlib.sha256(files[2].read_bytes()).hexdigest(),"preconditions_receipt_sha256":hashlib.sha256(files[3].read_bytes()).hexdigest(),"preconditions_evidence_receipt_sha256":hashlib.sha256(files[4].read_bytes()).hexdigest(),"runtime_oci_receipt_sha256":hashlib.sha256(files[5].read_bytes()).hexdigest(),"sftp_runtime_ready_receipt_sha256":hashlib.sha256(files[6].read_bytes()).hexdigest(),"sftp_postgres_ledger_receipt_sha256":hashlib.sha256(files[7].read_bytes()).hexdigest(),"completed_at":datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")}
fd=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,"w") as h: json.dump(p,h,separators=(",",":"),sort_keys=True); h.write("\n"); h.flush(); os.fsync(h.fileno())
PY
	durable_replace "$temporary" "$COMPLETION_RECEIPT"
	assert_completion_receipt
}

terminal_gate_authorization_contract() {
	local mode="$1" direction="$2" authorization="$3" receipt="$4" purpose="$5" terminal_phase="$6"
	local expected_name temporary
	[[ "$mode" == write || "$mode" == verify ]] || die "Mode d'autorisation terminale invalide"
	case "$direction:$purpose:$terminal_phase:$authorization:$receipt" in
	"forward:forward-terminal-open:completed:$FORWARD_OPEN_AUTHORIZATION:$COMPLETION_RECEIPT")
		expected_name="release-a-transaction-receipt.json"
		;;
	"rollback:rollback-terminal-open:rolled_back:$ROLLBACK_OPEN_AUTHORIZATION:$ROLLBACK_COMPLETION_RECEIPT")
		expected_name="release-a-rollback-receipt.json"
		;;
	*) die "Contrat d'autorisation terminale incohérent" ;;
	esac
	assert_private "$receipt"
	temporary="$DEPLOY_DIR/.${authorization##*/}.$$"
	if [[ "$mode" == write && ! -e "$authorization" && ! -L "$authorization" ]]; then
		[[ ! -e "$temporary" && ! -L "$temporary" ]] || die "Autorisation terminale concurrente"
		python3 -I - "$temporary" "$DEPLOYMENT_ID" "$RELEASE_A_SHA" "$purpose" "$terminal_phase" "$expected_name" "$receipt" <<'PY'
import hashlib,json,os,sys
from pathlib import Path

out=Path(sys.argv[1]); receipt=Path(sys.argv[7])
payload={
    "schema_version":1,
    "kind":"agentium-release-a-terminal-gate-authorization",
    "deployment_id":sys.argv[2],
    "release_a_sha":sys.argv[3],
    "purpose":sys.argv[4],
    "terminal_phase":sys.argv[5],
    "receipt_name":sys.argv[6],
    "receipt_sha256":hashlib.sha256(receipt.read_bytes()).hexdigest(),
}
body=json.dumps(payload,separators=(",",":"),sort_keys=True).encode("utf-8")+b"\n"
fd=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,"wb") as handle:
    handle.write(body); handle.flush(); os.fsync(handle.fileno())
PY
		durable_replace "$temporary" "$authorization"
	fi
	assert_private "$authorization"
	python3 -I - "$authorization" "$receipt" "$DEPLOYMENT_ID" "$RELEASE_A_SHA" "$purpose" "$terminal_phase" "$expected_name" <<'PY'
import hashlib,json,sys
from pathlib import Path

authorization,receipt=map(Path,sys.argv[1:3])
def no_duplicates(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError("duplicate key")
        result[key]=value
    return result
raw=authorization.read_bytes()
try:
    payload=json.loads(raw,object_pairs_hook=no_duplicates)
except (UnicodeDecodeError,json.JSONDecodeError,ValueError) as exc:
    raise SystemExit("terminal gate authorization is invalid JSON") from exc
expected={
    "schema_version":1,
    "kind":"agentium-release-a-terminal-gate-authorization",
    "deployment_id":sys.argv[3],
    "release_a_sha":sys.argv[4],
    "purpose":sys.argv[5],
    "terminal_phase":sys.argv[6],
    "receipt_name":sys.argv[7],
    "receipt_sha256":hashlib.sha256(receipt.read_bytes()).hexdigest(),
}
canonical=json.dumps(expected,separators=(",",":"),sort_keys=True).encode("utf-8")+b"\n"
if payload!=expected or raw!=canonical:
    raise SystemExit("terminal gate authorization binding differs")
PY
}

publish_terminal_gate_authorization() {
	terminal_gate_authorization_contract write "$@"
}

assert_terminal_gate_authorization() {
	terminal_gate_authorization_contract verify "$@"
}

open_reconciled_payload() {
	local direction="$1" receipt="$2" terminal_phase="$3" authorization
	case "$direction:$terminal_phase" in
	forward:completed) authorization="$FORWARD_OPEN_AUTHORIZATION" ;;
	rollback:rolled_back) authorization="$ROLLBACK_OPEN_AUTHORIZATION" ;;
	*) die "Direction de marker terminal invalide" ;;
	esac
	assert_private "$authorization"
	printf 'format=2 direction=%s deployment_id=%s release_a_sha=%s terminal_phase=%s receipt_sha256=%s authorization_sha256=%s' \
		"$direction" "$DEPLOYMENT_ID" "$RELEASE_A_SHA" "$terminal_phase" \
		"$(sha256sum "$receipt" | awk '{print $1}')" "$(sha256sum "$authorization" | awk '{print $1}')"
}

assert_open_reconciled_marker() {
	local direction="$1" marker="$2" receipt="$3" terminal_phase="$4" expected
	assert_private "$receipt"
	assert_private "$marker"
	expected="$(open_reconciled_payload "$direction" "$receipt" "$terminal_phase")"
	[[ "$(cat "$marker")" == "$expected" ]] || die "Marqueur de réouverture terminale divergent: $direction"
}

publish_open_reconciled_marker() {
	local direction="$1" marker="$2" receipt="$3" terminal_phase="$4"
	if [[ -e "$marker" || -L "$marker" ]]; then
		assert_open_reconciled_marker "$direction" "$marker" "$receipt" "$terminal_phase"
		return
	fi
	atomic_text "$marker" "$(open_reconciled_payload "$direction" "$receipt" "$terminal_phase")"
	assert_open_reconciled_marker "$direction" "$marker" "$receipt" "$terminal_phase"
}

commit_forward_opening() {
	assert_systemd_boot_guards
	publish_completion_receipt
	set_phase completed
}

assert_sftp_process_identity_stable() {
	assert_private "$SFTP_RUNTIME_READY"
	python3 -I - "$SFTP_RUNTIME_READY" "$(metadata sftp_release_sha)" <<'PY'
import json,subprocess,sys
from pathlib import Path
receipt=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
rows=json.loads(subprocess.run(
    ["docker","inspect","--type","container","agentium-sftp"],
    check=True,capture_output=True,text=True,timeout=30,
).stdout)
if not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0],dict):
    raise SystemExit("SFTP process identity unavailable")
row=rows[0]; state=row.get("State") or {}
if (
    row.get("Id")!=receipt.get("sftp_container_id")
    or row.get("Image")!=receipt.get("sftp_image_id")
    or state.get("StartedAt")!=receipt.get("sftp_started_at")
    or state.get("Running") is not True
    or state.get("Paused") is not False
):
    raise SystemExit("SFTP process identity changed after opening")
images=json.loads(subprocess.run(
    ["docker","image","inspect",str(row.get("Image") or "")],
    check=True,capture_output=True,text=True,timeout=30,
).stdout)
labels=((images[0].get("Config") or {}).get("Labels") or {}) if isinstance(images,list) and len(images)==1 else {}
if labels.get("org.opencontainers.image.revision")!=sys.argv[2]:
    raise SystemExit("SFTP process revision changed after opening")
PY
}

assert_forward_terminal_open_state() {
	assert_open_reconciled_marker forward "$FORWARD_OPEN_RECONCILED" "$COMPLETION_RECEIPT" completed
	assert_terminal_gate_authorization forward "$FORWARD_OPEN_AUTHORIZATION" "$COMPLETION_RECEIPT" forward-terminal-open completed
	[[ "$(gate status)" == open ]] || die "Gate HTTP forward terminal physiquement fermé"
	assert_writer_ingress_gates_absent
	assert_secure_mode_in_namespaces rw
	assert_runtime_oci_receipt
	assert_restart_policies_restored
	assert_systemd_boot_guards_absent
	assert_sftp_runtime_identity_live rw historical
	assert_nginx_unique_edge_topology
}

validate_forward_terminal_boundary() {
	local pg_temporary="$DEPLOY_DIR/.postgres-terminal-replay.$$"
	local storage_temporary="$DEPLOY_DIR/.storage-terminal-replay.$$"
	local comparison_temporary="$DEPLOY_DIR/.storage-terminal-replay-comparison.$$"
	assert_private "$SFTP_POSTGRES_FINAL"
	assert_private "$POSTGRES_INVENTORY_OPENING"
	assert_private "$STORAGE_OPENING"
	[[ -f "$FROZEN_STORAGE_HELPER" && ! -L "$FROZEN_STORAGE_HELPER" && -x "$FROZEN_STORAGE_HELPER" ]] ||
		die "Helper storage figé non sûr avant replay terminal"
	assert_sftp_runtime_ready_live
	capture_sftp_postgres_inventory revoked "$pg_temporary"
	cmp -s "$SFTP_POSTGRES_FINAL" "$pg_temporary" || die "PostgreSQL a dérivé après le commit terminal Release A"
	cmp -s "$POSTGRES_INVENTORY_OPENING" "$pg_temporary" || die "Frontière PostgreSQL d'ouverture Release A divergente"
	snapshot_storage "$storage_temporary"
	"$FROZEN_STORAGE_HELPER" compare --before "$STORAGE_OPENING" --after "$storage_temporary" --output "$comparison_temporary"
	python3 -I - "$comparison_temporary" <<'PY'
import json,sys
p=json.load(open(sys.argv[1],encoding="utf-8"))
if p.get("profile")!="agentium-storage-exact-comparison-v1" or p.get("result")!="passed" or p.get("failed_checks")!=[]:
    raise SystemExit("terminal storage replay differs")
PY
	rm -f "$pg_temporary" "$storage_temporary" "$comparison_temporary"
	assert_sftp_runtime_ready_live
}

open_forward_terminal_from_validated_boundary() {
	[[ "$(phase)" == completed ]] || die "Ouverture terminale forward sans commit"
	OPENING_FAIL_CLOSED_ARMED=1
	OPENING_TERMINAL_SYNCED=0
	assert_completion_receipt
	assert_writer_ingress_gates
	[[ "$(gate status)" == closed ]] || die "Gate HTTP non fermé avant ouverture terminale"
	assert_secure_mode_in_namespaces rw
	assert_sftp_runtime_identity_live rw disabled
	[[ "$(sftp_open_deposit_fd_count)" -eq 0 ]] || die "FD SFTP Secure Deposit actif avant ouverture terminale"
	assert_runtime_oci_receipt
	assert_nginx_unique_edge_topology
	publish_terminal_gate_authorization forward "$FORWARD_OPEN_AUTHORIZATION" "$COMPLETION_RECEIPT" forward-terminal-open completed
	if [[ "$(gate status)" == closed ]]; then
		gate exit forward-terminal-open "$FORWARD_OPEN_AUTHORIZATION"
	fi
	leave_writer_ingress_gates
	[[ "$(gate status)" == open ]] || die "Gate HTTP forward terminal non ouvert"
	restore_restart_policies_after_open
	assert_secure_mode_in_namespaces rw
	remove_systemd_boot_guard agentium-backend.service
	remove_systemd_boot_guard agentium-sftp.service
	publish_open_reconciled_marker forward "$FORWARD_OPEN_RECONCILED" "$COMPLETION_RECEIPT" completed
	assert_sftp_process_identity_stable
	assert_forward_terminal_open_state
	OPENING_TERMINAL_SYNCED=1
	OPENING_FAIL_CLOSED_ARMED=0
}

reconcile_forward_committed_open() {
	[[ "$(phase)" == completed ]] || die "Réouverture forward sans phase terminale"
	assert_completion_receipt
	if [[ -e "$FORWARD_OPEN_RECONCILED" || -L "$FORWARD_OPEN_RECONCILED" ]]; then
		assert_open_reconciled_marker forward "$FORWARD_OPEN_RECONCILED" "$COMPLETION_RECEIPT" completed
	fi
	OPENING_FAIL_CLOSED_ARMED=1
	OPENING_TERMINAL_SYNCED=0
	# A new process resuming `completed` cannot trust how far the physical open
	# progressed. Reclose every ingress, preserve the exact attested SFTP
	# process, replay the DB/storage boundary from RO, then rebuild RW before
	# delegating the small terminal opening sequence.
	disable_writer_restarts
	install_gate_closed
	enter_writer_ingress_gates
	stop_writers_preserving_attested_sftp
	reclose_attested_sftp_to_read_only
	assert_writer_ingress_gates
	assert_completion_receipt
	if [[ -e "$FORWARD_OPEN_AUTHORIZATION" || -L "$FORWARD_OPEN_AUTHORIZATION" ]]; then
		assert_terminal_gate_authorization forward "$FORWARD_OPEN_AUTHORIZATION" "$COMPLETION_RECEIPT" forward-terminal-open completed
	else
		# Before the first durable open authorization, public writers have never
		# been admitted and the exact closed boundary must still match.
		validate_forward_terminal_boundary
	fi
	start_runtime_services_without_restart
	activate_qdrant_write_runtime
	set_secure_mode rw
	assert_secure_mode_in_namespaces rw
	assert_sftp_runtime_identity_live rw disabled
	open_forward_terminal_from_validated_boundary
}

reconcile_forward_open() {
	case "$(phase)" in opening_forward | opened) ;; *) die "Reconcile forward hors phase" ;; esac
	OPENING_FAIL_CLOSED_ARMED=1
	OPENING_TERMINAL_SYNCED=0
	# Both the current opening phase and the legacy `opened` phase are treated
	# as untrusted after an interruption.  Reclose before reading any receipt.
	disable_writer_restarts
	install_gate_closed
	enter_writer_ingress_gates
	stop_writers_preserving_attested_sftp
	set_secure_mode ro
	assert_secure_mode_in_namespaces ro
	assert_writer_ingress_gates
	assert_attestation_receipt
	if [[ "$(phase)" == opened ]]; then
		assert_completion_receipt
		set_phase completed
		reconcile_forward_committed_open
		return
	fi
	verify_rabbitmq_candidate
	verify_qdrant_keys
	compare_postgres_inventory_v2 "$POSTGRES_INVENTORY_BEFORE" "$POSTGRES_INVENTORY_AFTER" || die "PostgreSQL divergent avant ouverture"
	python3 -I - "$STORAGE_COMPARISON" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]))
if p.get("profile")!="agentium-storage-release-a-versioning-comparison-v1" or p.get("result")!="passed" or p.get("failed_checks")!=[]:
    raise SystemExit("storage comparison did not pass")
PY
	start_runtime_services_without_restart
	activate_qdrant_write_runtime
	# Bind the exact running containers (not merely their mutable tags) and the
	# served backend build identity before taking any opening snapshot.
	capture_runtime_oci_receipt
	capture_opening_boundary
	set_secure_mode rw
	assert_secure_mode_in_namespaces rw
	# Re-read the immutable runtime receipt before committing the terminal
	# authorization.  No public gate has been removed and every restart path is
	# still durably disabled at this point.
	assert_runtime_oci_receipt
	assert_nginx_unique_edge_topology
	commit_forward_opening
	open_forward_terminal_from_validated_boundary
}

start_runtime_services_without_restart() {
	local service desired preserve_sftp=0 secure_mode=""
	case "$(phase)" in opening_forward | opened | completed) [[ -e "$SFTP_RUNTIME_READY" && ! -L "$SFTP_RUNTIME_READY" ]] && preserve_sftp=1 ;; esac
	if [[ "$preserve_sftp" == 1 ]]; then secure_mode="$(current_secure_mode)"; fi
	for service in agentium-backend agentium-frontend agentium-worker-cpu agentium-p4-maintenance agentium-sftp agentium-livekit agentium-livekit-agent agentium-kc; do
		desired="$(awk -F '\t' -v service="$service" '$1=="container" && $2==service {print $3}' "$RUNTIME_STATE")"
		if [[ "$service" == agentium-sftp && "$preserve_sftp" == 1 ]]; then
			[[ "$desired" == true ]] || die "État historique SFTP incompatible avec le canari attesté"
			assert_sftp_runtime_identity_live "$secure_mode" disabled
			continue
		fi
		if [[ "$desired" == true && "$service" != agentium-backend && "$service" != agentium-worker-cpu && "$service" != agentium-p4-maintenance ]]; then docker start "$service" >/dev/null; fi
		if docker inspect "$service" >/dev/null 2>&1; then docker update --restart=no "$service" >/dev/null; fi
	done
	if awk -F '\t' '$1=="systemd" && $3=="active" {found=1} END{exit !found}' "$RUNTIME_STATE"; then
		sudo_cmd systemctl start agentium-backend.service
		curl --noproxy '*' --fail --silent --show-error http://127.0.0.1:8000/api/v1/build-info |
			python3 -I -c 'import json,sys; p=json.load(sys.stdin); raise SystemExit(0 if p.get("revision")==sys.argv[1] and p.get("revision_verified") is True else 1)' "$RELEASE_A_SHA"
	fi
	[[ "$preserve_sftp" == 0 ]] || assert_sftp_runtime_identity_live "$secure_mode" disabled
}

capture_opening_boundary() {
	local pg_temporary="$DEPLOY_DIR/.postgres-opening.$$" storage_temporary="$DEPLOY_DIR/.storage-opening.$$" comparison_temporary="$DEPLOY_DIR/.storage-opening-comparison.$$"
	assert_sftp_runtime_ready_live
	capture_sftp_postgres_inventory revoked "$pg_temporary"
	cmp -s "$SFTP_POSTGRES_FINAL" "$pg_temporary" || die "PostgreSQL a dérivé après la révocation SFTP; ouverture interdite"
	durable_replace "$pg_temporary" "$POSTGRES_INVENTORY_OPENING"
	snapshot_storage "$storage_temporary"
	"$FROZEN_STORAGE_HELPER" compare --release-a-opening-transition --before "$STORAGE_AFTER" --after "$storage_temporary" --output "$comparison_temporary"
	python3 -I - "$comparison_temporary" <<'PY'
import json,sys
p=json.load(open(sys.argv[1],encoding="utf-8"))
if p.get("profile")!="agentium-storage-release-a-opening-comparison-v1" or p.get("result")!="passed" or p.get("failed_checks")!=[]:
    raise SystemExit("storage opening transition differs")
PY
	durable_replace "$storage_temporary" "$STORAGE_OPENING"
	durable_replace "$comparison_temporary" "$STORAGE_OPENING_COMPARISON"
	verify_rabbitmq_candidate
	assert_sftp_runtime_ready_live
}

activate_qdrant_write_runtime() {
	local -a services=(agentium-backend agentium-worker-cpu)
	if awk -F '\t' '$1=="container" && $2=="agentium-p4-maintenance" && $3=="true" {found=1} END{exit !found}' "$RUNTIME_STATE"; then services+=(agentium-p4-maintenance); fi
	# The exact-ID override is byte-bound to the durable prepare receipt and is
	# appended after every other Compose file before these writers are recreated.
	assert_candidate_image_override
	compose_opened up -d --no-build --no-deps "${services[@]}"
	for service in "${services[@]}"; do docker update --restart=no "$service" >/dev/null; done
	verify_qdrant_keys
}

capture_runtime_oci_receipt() {
	assert_candidate_oci_receipt
	if [[ -e "$RUNTIME_OCI_RECEIPT" || -L "$RUNTIME_OCI_RECEIPT" ]]; then
		assert_runtime_oci_receipt
		return
	fi
	local backend_port temporary="$DEPLOY_DIR/.runtime-oci-receipt.$$"
	backend_port="$(env_value compose_main AGENTIUM_BACKEND_HOST_PORT)"
	[[ "$backend_port" =~ ^[0-9]+$ && "$backend_port" -ge 1 && "$backend_port" -le 65535 ]] || die "Port backend OCI invalide"
	[[ ! -e "$temporary" && ! -L "$temporary" ]] || die "Capture OCI runtime concurrente"
	python3 -I - "$CANDIDATE_OCI_RECEIPT" "$temporary" "$DEPLOYMENT_ID" "$RELEASE_A_SHA" "$(metadata docker_engine_id)" "$backend_port" <<'PY'
import hashlib,http.client,json,os,re,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path

candidate_path,out=map(Path,sys.argv[1:3]); deployment_id,release_sha,engine_id,backend_port=sys.argv[3:]
candidate_bytes=candidate_path.read_bytes(); candidate=json.loads(candidate_bytes)
if candidate.get("deployment_id")!=deployment_id or candidate.get("release_a_sha")!=release_sha or candidate.get("docker_engine_id")!=engine_id:
    raise SystemExit("candidate OCI identity changed before runtime capture")

def docker_json(*args):
    proc=subprocess.run(["docker",*args],check=True,capture_output=True,text=True,timeout=30)
    rows=json.loads(proc.stdout)
    if not isinstance(rows,list) or len(rows)!=1:
        raise SystemExit("runtime OCI inspection cardinality differs")
    return rows[0]

def inspect_runtime(row):
    service=row["service"]; container=docker_json("inspect","--type","container",service)
    container_id=str(container.get("Id","")).lower(); image_id=str(container.get("Image","")).lower()
    config=container.get("Config") or {}; state=container.get("State") or {}; labels=config.get("Labels") or {}
    if re.fullmatch(r"[0-9a-f]{64}",container_id) is None:
        raise SystemExit(f"runtime OCI container ID invalid: {service}")
    if image_id!=row["image_id"] or config.get("Image")!=row["image_ref"]:
        raise SystemExit(f"runtime OCI image substituted: {service}")
    image=docker_json("image","inspect",image_id); image_labels=(image.get("Config") or {}).get("Labels") or {}
    if labels.get("org.opencontainers.image.revision")!=release_sha or image_labels.get("org.opencontainers.image.revision")!=release_sha:
        raise SystemExit(f"runtime OCI revision substituted: {service}")
    if state.get("Dead") is True or state.get("Restarting") is True:
        raise SystemExit(f"runtime OCI terminal state: {service}")
    if state.get("Running") is not True or state.get("Paused") is True:
        return None
    health=state.get("Health")
    if service in {"agentium-backend","agentium-frontend"} and not isinstance(health,dict):
        raise SystemExit(f"runtime OCI healthcheck missing: {service}")
    health_status=str((health or {}).get("Status") or "not_configured")
    if health_status=="starting": return None
    if health_status not in {"healthy","not_configured"}:
        raise SystemExit(f"runtime OCI unhealthy: {service}")
    if service in {"agentium-backend","agentium-frontend"} and health_status!="healthy":
        raise SystemExit(f"runtime OCI health is not authoritative: {service}")
    return {"service":service,"container_id":container_id,"image_ref":row["image_ref"],"image_id":image_id,"image_revision":release_sha,"state":"running","health_status":health_status}

def read_build_info():
    connection=http.client.HTTPConnection("127.0.0.1",int(backend_port),timeout=5)
    try:
        connection.request("GET","/api/v1/build-info",headers={"Host":"127.0.0.1","Connection":"close"})
        response=connection.getresponse(); body=response.read(65537)
    finally:
        connection.close()
    if response.status!=200 or len(body)>65536: return None
    payload=json.loads(body)
    if set(payload)!={"service","revision","revision_verified","version"}:
        raise SystemExit("backend build-info schema differs")
    if payload.get("service")!="backend" or payload.get("revision")!=release_sha or payload.get("revision_verified") is not True or not isinstance(payload.get("version"),str) or not payload["version"]:
        raise SystemExit("backend build-info substituted")
    return payload

deadline=time.monotonic()+120
while True:
    containers=[]; ready=True
    for row in candidate["images"]:
        observed=inspect_runtime(row)
        if observed is None: ready=False
        else: containers.append(observed)
    build_info=None
    if ready:
        try: build_info=read_build_info()
        except (ConnectionError,OSError,TimeoutError,json.JSONDecodeError): build_info=None
    if ready and build_info is not None: break
    if time.monotonic()>=deadline: raise SystemExit("runtime OCI did not become healthy before timeout")
    time.sleep(2)
p={
    "schema_version":1,
    "kind":"agentium-release-a-runtime-oci-receipt",
    "result":"passed",
    "deployment_id":deployment_id,
    "release_a_sha":release_sha,
    "docker_engine_id":engine_id,
    "candidate_oci_receipt_sha256":hashlib.sha256(candidate_bytes).hexdigest(),
    "containers":containers,
    "backend_build_info":build_info,
    "verified_at":datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z"),
}
fd=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,"w") as handle:
    json.dump(p,handle,separators=(",",":"),sort_keys=True); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
PY
	durable_replace "$temporary" "$RUNTIME_OCI_RECEIPT"
	assert_runtime_oci_receipt
}

assert_runtime_oci_receipt() {
	assert_private "$CANDIDATE_OCI_RECEIPT"
	assert_private "$RUNTIME_OCI_RECEIPT"
	assert_candidate_oci_receipt
	local backend_port
	backend_port="$(env_value compose_main AGENTIUM_BACKEND_HOST_PORT)"
	python3 -I - "$CANDIDATE_OCI_RECEIPT" "$RUNTIME_OCI_RECEIPT" "$DEPLOYMENT_ID" "$RELEASE_A_SHA" "$(metadata docker_engine_id)" "$backend_port" <<'PY'
import hashlib,http.client,json,re,subprocess,sys
from pathlib import Path

candidate_path,receipt_path=map(Path,sys.argv[1:3]); deployment_id,release_sha,engine_id,backend_port=sys.argv[3:]
candidate_bytes=candidate_path.read_bytes(); candidate=json.loads(candidate_bytes); receipt=json.loads(receipt_path.read_text(encoding="utf-8"))
expected_keys={"schema_version","kind","result","deployment_id","release_a_sha","docker_engine_id","candidate_oci_receipt_sha256","containers","backend_build_info","verified_at"}
if set(receipt)!=expected_keys or receipt.get("schema_version")!=1 or receipt.get("kind")!="agentium-release-a-runtime-oci-receipt" or receipt.get("result")!="passed":
    raise SystemExit("runtime OCI receipt schema/result differs")
if receipt.get("deployment_id")!=deployment_id or receipt.get("release_a_sha")!=release_sha or receipt.get("docker_engine_id")!=engine_id:
    raise SystemExit("runtime OCI receipt identity differs")
if receipt.get("candidate_oci_receipt_sha256")!=hashlib.sha256(candidate_bytes).hexdigest():
    raise SystemExit("runtime OCI candidate receipt binding differs")
engine=subprocess.run(["docker","info","--format","{{.ID}}"],check=True,capture_output=True,text=True,timeout=30).stdout.strip()
if engine!=engine_id: raise SystemExit("runtime OCI Docker engine differs")

def docker_json(*args):
    proc=subprocess.run(["docker",*args],check=True,capture_output=True,text=True,timeout=30)
    rows=json.loads(proc.stdout)
    if not isinstance(rows,list) or len(rows)!=1: raise SystemExit("runtime OCI inspection cardinality differs")
    return rows[0]

containers=receipt.get("containers")
if not isinstance(containers,list) or [row.get("service") for row in containers]!=[row.get("service") for row in candidate.get("images",[])]:
    raise SystemExit("runtime OCI service set/order differs")
candidate_by_service={row["service"]:row for row in candidate["images"]}
for row in containers:
    if set(row)!={"service","container_id","image_ref","image_id","image_revision","state","health_status"}:
        raise SystemExit("runtime OCI container schema differs")
    service=row["service"]; expected=candidate_by_service[service]
    container=docker_json("inspect","--type","container",service); config=container.get("Config") or {}; state=container.get("State") or {}; labels=config.get("Labels") or {}
    image_id=str(container.get("Image","")).lower(); health=state.get("Health"); health_status=str((health or {}).get("Status") or "not_configured")
    if str(container.get("Id","")).lower()!=row["container_id"]:
        raise SystemExit(f"runtime OCI container substituted: {service}")
    if image_id!=row["image_id"] or image_id!=expected["image_id"] or config.get("Image")!=row["image_ref"] or row["image_ref"]!=expected["image_ref"]:
        raise SystemExit(f"runtime OCI image substituted: {service}")
    image=docker_json("image","inspect",image_id); image_labels=(image.get("Config") or {}).get("Labels") or {}
    if row.get("image_revision")!=release_sha or labels.get("org.opencontainers.image.revision")!=release_sha or image_labels.get("org.opencontainers.image.revision")!=release_sha:
        raise SystemExit(f"runtime OCI revision substituted: {service}")
    if row.get("state")!="running" or state.get("Running") is not True or state.get("Paused") is True or state.get("Restarting") is True or state.get("Dead") is True:
        raise SystemExit(f"runtime OCI state differs: {service}")
    if health_status!=row.get("health_status") or health_status not in {"healthy","not_configured"}:
        raise SystemExit(f"runtime OCI health differs: {service}")
    if service in {"agentium-backend","agentium-frontend"} and health_status!="healthy":
        raise SystemExit(f"runtime OCI healthcheck is not healthy: {service}")
    if re.fullmatch(r"[0-9a-f]{64}",row["container_id"]) is None:
        raise SystemExit(f"runtime OCI container receipt ID invalid: {service}")
connection=http.client.HTTPConnection("127.0.0.1",int(backend_port),timeout=5)
try:
    connection.request("GET","/api/v1/build-info",headers={"Host":"127.0.0.1","Connection":"close"})
    response=connection.getresponse(); body=response.read(65537)
finally:
    connection.close()
if response.status!=200 or len(body)>65536: raise SystemExit("backend build-info unavailable")
build_info=json.loads(body)
if build_info!=receipt.get("backend_build_info") or set(build_info)!={"service","revision","revision_verified","version"} or build_info.get("revision")!=release_sha or build_info.get("revision_verified") is not True:
    raise SystemExit("backend build-info runtime substituted")
PY
}

restore_restart_policies_after_open() {
	local service unit historical_enabled
	for service in agentium-backend agentium-frontend agentium-worker-cpu agentium-p4-maintenance agentium-sftp agentium-livekit agentium-livekit-agent agentium-kc; do
		restore_restart_policy "$service"
	done
	while IFS=$'\t' read -r unit historical_enabled; do
		case "$historical_enabled" in
		enabled) sudo_cmd systemctl enable "$unit" >/dev/null ;;
		disabled) sudo_cmd systemctl disable "$unit" >/dev/null ;;
		absent | static | indirect | generated | transient | masked | masked-runtime | linked | linked-runtime | alias) ;;
		*) die "État systemd historique non attestable pour $unit: $historical_enabled" ;;
		esac
	done < <(awk -F '\t' '$1=="systemd" {print $2 "\t" $4}' "$RUNTIME_STATE")
}

assert_restart_policies_restored() {
	local service expected_name expected_maximum actual_name actual_maximum unit expected_enabled actual_enabled
	while IFS=$'\t' read -r service expected_name expected_maximum; do
		[[ "$expected_name" == absent ]] && continue
		read -r actual_name actual_maximum < <(
			docker inspect --format '{{.HostConfig.RestartPolicy.Name}} {{.HostConfig.RestartPolicy.MaximumRetryCount}}' "$service"
		)
		[[ "$actual_name" == "$expected_name" && "$actual_maximum" == "$expected_maximum" ]] ||
			die "Policy de restart non restaurée pour $service"
	done < <(awk -F '\t' '$1=="container" {print $2 "\t" $5 "\t" $6}' "$RUNTIME_STATE")
	while IFS=$'\t' read -r unit expected_enabled; do
		[[ "$expected_enabled" == absent ]] && continue
		actual_enabled="$(sudo_cmd systemctl is-enabled "$unit" 2>/dev/null || true)"
		[[ "$actual_enabled" == "$expected_enabled" ]] ||
			die "Policy systemd non restaurée pour $unit"
	done < <(awk -F '\t' '$1=="systemd" {print $2 "\t" $4}' "$RUNTIME_STATE")
}

finalize_impl() {
	[[ "$(phase)" == sftp_canary_recorded || "$(phase)" == opening_forward || "$(phase)" == opened || "$(phase)" == completed ]] || die "finalize exige un cycle SFTP positif, révoqué et journalisé"
	assert_metadata
	if [[ "$(phase)" == completed ]]; then reconcile_forward_committed_open; ok "Release A complète et réouverture réconciliée"; return; fi
	if [[ "$(phase)" == opening_forward || "$(phase)" == opened ]]; then reconcile_forward_open; ok "Release A complète et attestée"; return; fi
	assert_candidate_worktree
	assert_remote_release_a
	assert_writer_ingress_gates
	assert_secure_mode_in_namespaces ro
	assert_sftp_runtime_ready_live
	assert_private "$FROZEN_SFTP_CANARY_LEDGER"
	assert_private "$SFTP_POSTGRES_ACTIVE"
	assert_private "$SFTP_POSTGRES_FINAL"
	validate_sftp_postgres_receipt "$SFTP_POSTGRES_RECEIPT"
	capture_sftp_postgres_inventory revoked "$SFTP_POSTGRES_FINAL"
	[[ "$ATTESTATION_SHA256" =~ ^[0-9a-f]{64}$ ]] || die "Attestation v4 et digest requis"
	copy_private_once "$ATTESTATION" "$FROZEN_ATTESTATION" "$ATTESTATION_SHA256"
	if [[ ! -e "$ATTESTATION_RECEIPT" ]]; then
		temporary="$DEPLOY_DIR/.attestation-receipt.$$"
		"$FROZEN_ATTESTATION_HELPER" verify --attestation "$FROZEN_ATTESTATION" --expected-release-a-sha "$RELEASE_A_SHA" --expected-sftp-sha "$(metadata sftp_release_sha)" --expected-hostname "$(hostname -f)" >"$temporary"
		durable_replace "$temporary" "$ATTESTATION_RECEIPT"
	fi
	if [[ ! -e "$FINAL_EVIDENCE_RECEIPT" ]]; then
		[[ -n "$FINAL_EVIDENCE_ROOT" ]] || die "--final-evidence-root requis pour lier les preuves finales"
		"$FROZEN_EVIDENCE_HELPER" verify-final \
			--attestation "$FROZEN_ATTESTATION" \
			--preconditions-receipt "$PRECONDITIONS_EVIDENCE_RECEIPT" \
			--evidence-root "$FINAL_EVIDENCE_ROOT" \
			--journal-root "$DEPLOY_DIR" \
			--authority-keyring "$FROZEN_EVIDENCE_AUTHORITY_KEYRING" \
			--expected-authority-keyring-sha256 "$(metadata evidence_authority_keyring_sha256)" \
			--binding-manifest-output "$FINAL_EVIDENCE_BINDING_MANIFEST" \
			--frozen-evidence-output "$FROZEN_FINAL_EVIDENCE_DIR" \
			--expected-live-sha "$LIVE_SHA" \
			--expected-release-a-sha "$RELEASE_A_SHA" \
			--expected-sftp-sha "$(metadata sftp_release_sha)" \
			--expected-hostname "$(hostname -f)" \
			--deployment-id "$DEPLOYMENT_ID" \
			--output "$FINAL_EVIDENCE_RECEIPT" >/dev/null
	fi
	assert_attestation_receipt
	assert_sftp_runtime_ready_live
	capture_sftp_postgres_inventory revoked "$SFTP_POSTGRES_FINAL"
	set_phase opening_forward
	reconcile_forward_open
	ok "Release A complète et attestée; receipt compatible Release B publié"
}

restore_file_and_mode() {
	local target="$1" backup="$2" attrs="$3" mode uid gid links
	[[ -e "$backup" ]] || return 0
	IFS=: read -r mode uid gid links <"$attrs"
	[[ "$links" == 1 ]] || die "Backup d'attributs invalide"
	sudo_cmd install -o "$uid" -g "$gid" -m "$mode" "$backup" "$target"
}

rollback_impl() {
	[[ "$ROLLBACK_CONFIRMATION" == "$DEPLOYMENT_ID" ]] || die "--confirm-rollback doit répéter le deployment-id"
	case "$(phase)" in completed | opened | opening_forward) die "Rollback automatique interdit après l'intention forward" ;; new | preflight_ok) die "Aucune mutation à rollbacker" ;; prepared) set_phase rolled_back; ok "Release A préparée annulée sans mutation live"; return ;; rolled_back) if [[ -e "$ROLLBACK_COMPLETION_RECEIPT" || -L "$ROLLBACK_COMPLETION_RECEIPT" ]]; then reconcile_rollback_committed_open; fi; ok "Rollback terminé et réouverture réconciliée"; return ;; rollback_opening) reconcile_rollback_open; return ;; rollback_closing | rollback_restoring) ;; esac
	assert_metadata
	[[ ! -e "$STATEFUL_ADOPTION_INTENT" && ! -L "$STATEFUL_ADOPTION_INTENT" ]] || die "Adoption Qdrant/MinIO/Rabbit one-way commencée: rollback automatique interdit, rester fermé"
	[[ "$(phase)" == rollback_closing || "$(phase)" == rollback_restoring ]] || set_phase rollback_closing
	install_gate_closed
	enter_writer_ingress_gates
	disable_and_stop_writers
	assert_writer_ingress_gates
	set_secure_mode ro
	[[ "$(phase)" == rollback_restoring ]] || set_phase rollback_restoring
	# Always replay the immutable rollback state.  deploy-vm accepts either the
	# candidate or previous checkout and verifies every runtime image, so a
	# crash after resetting HEAD cannot skip the remaining restoration.
	env -i PATH="$COMPOSE_CLEAN_PATH" HOME="$DEPLOY_HOME" DOCKER_CONFIG="$DEPLOY_HOME/.docker" DOCKER_HOST="$DOCKER_LOCAL_HOST" \
		AGENTIUM_SAFE_DEPLOY_ORCHESTRATED=1 AGENTIUM_SAFE_DEPLOYMENT_DIR="$DEPLOY_DIR" AGENTIUM_DEPLOY_STATE_DIR="$DEPLOY_DIR/rollback" AGENTIUM_SAFE_ENV_BUNDLE_DIR="$RUNTIME_ENV_DIR" AGENTIUM_SAFE_ENV_MANIFEST_SHA256="$ENV_DIGEST" AGENTIUM_SAFE_ENV_BUNDLE_HELPER="$FROZEN_ENV_HELPER" AGENTIUM_SAFE_QDRANT_OVERRIDE_FILE="$FROZEN_QDRANT_OVERRIDE" AGENTIUM_QDRANT_EFFECTIVE_API_KEY="$(env_value application QDRANT_API_KEY)" AGENTIUM_CELERY_BEAT=0 AGENTIUM_STARTUP_RECONCILIATION=disabled OMNIRAG_REPO_DIR="$LIVE_REPO" bash "$FROZEN_DEPLOYER" --defer-auxiliary-start --rollback-state "$ROLLBACK_STATE"
	[[ "$(git -C "$LIVE_REPO" rev-parse HEAD)" == "$LIVE_SHA" ]] || die "Checkout live non restauré"
	if [[ -e "$DEPLOY_DIR/systemd-env-dropin.state" || -L "$DEPLOY_DIR/systemd-env-dropin.state" ]]; then
		systemd_env="$("$FROZEN_ENV_HELPER" role-path --bundle-dir "$RUNTIME_ENV_DIR" --sha "$RELEASE_A_SHA" --deployment-id "$DEPLOYMENT_ID" --expected-manifest-sha256 "$ENV_DIGEST" --role systemd)"
		sudo_cmd env AGENTIUM_BACKEND_UNIT_SOURCE="$FROZEN_SYSTEMD_UNIT" AGENTIUM_BACKEND_EXPECTED_SHA="$RELEASE_A_SHA" AGENTIUM_SAFE_DEPLOY_ORCHESTRATED=1 AGENTIUM_SAFE_DEPLOYMENT_DIR="$DEPLOY_DIR" AGENTIUM_BACKEND_ENV_FILE="$systemd_env" AGENTIUM_BACKEND_ENV_DROPIN_STATE="$DEPLOY_DIR/systemd-env-dropin.state" AGENTIUM_BACKEND_ENV_DROPIN_BACKUP="$DEPLOY_DIR/systemd-env-dropin.previous" "$FROZEN_SYSTEMD_INSTALLER" restore-env
	fi
	restore_file_and_mode "$LIVE_REPO/backend/.env" "$SYSTEMD_ENV_BACKUP" "$SYSTEMD_ENV_ATTRS"
	restore_file_and_mode "$LIVE_REPO/docker/env/agentium.vm.env" "$MAIN_ENV_BACKUP" "$MAIN_ENV_ATTRS"
	restore_file_and_mode "$LIVE_REPO/docker/env/agentium.env" "$APPLICATION_ENV_BACKUP" "$APPLICATION_ENV_ATTRS"
	restore_file_and_mode "$LIVE_REPO/docker/env/qdrant.agentium.env" "$QDRANT_ENV_BACKUP" "$QDRANT_ENV_ATTRS"
	restore_file_and_mode "$LIVE_REPO/docker/env/keycloak.agentium.env" "$KEYCLOAK_ENV_BACKUP" "$KEYCLOAK_ENV_ATTRS"
	(
		cd "$LIVE_REPO/docker"
		docker compose --env-file ./env/agentium.vm.env -f compose.agentium.yml --profile infra up -d --no-build --no-deps agentium-qdrant agentium-minio
	)
	assert_stateful_runtime_identity
	if [[ -e "$SYSTEMD_UNIT_BACKUP" ]]; then restore_file_and_mode /etc/systemd/system/agentium-backend.service "$SYSTEMD_UNIT_BACKUP" "$SYSTEMD_UNIT_ATTRS"; sudo_cmd systemctl daemon-reload; fi
	set_phase rollback_opening
	reconcile_rollback_open
}

assert_rollback_receipt() {
	assert_private "$ROLLBACK_COMPLETION_RECEIPT"
	assert_private "$ROLLBACK_STATE"
	assert_private "$RUNTIME_STATE"
	python3 -I - "$ROLLBACK_COMPLETION_RECEIPT" "$ROLLBACK_STATE" "$RUNTIME_STATE" "$DEPLOYMENT_ID" "$LIVE_SHA" <<'PY'
import hashlib,json,os,stat,sys
from datetime import datetime,timezone,timedelta
from pathlib import Path
def private(path,maximum=2*1024*1024):
    path=Path(path); before=path.lstat()
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode) or before.st_uid!=os.geteuid() or stat.S_IMODE(before.st_mode)!=0o600 or before.st_nlink!=1 or not 0<before.st_size<=maximum: raise SystemExit(f"unsafe rollback artifact: {path.name}")
    descriptor=os.open(path,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0))
    try:
        opened=os.fstat(descriptor); body=b""
        if (opened.st_dev,opened.st_ino)!=(before.st_dev,before.st_ino): raise SystemExit("rollback artifact changed while opening")
        while len(body)<=maximum:
            chunk=os.read(descriptor,min(65536,maximum+1-len(body)))
            if not chunk: break
            body+=chunk
        after=os.fstat(descriptor)
        if len(body)>maximum or (opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns,opened.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns): raise SystemExit("rollback artifact changed while read")
        return body
    finally: os.close(descriptor)
receipt_body=private(sys.argv[1]); rollback_body=private(sys.argv[2]); runtime_body=private(sys.argv[3])
def no_duplicates(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError(f"duplicate JSON key: {key}")
        result[key]=value
    return result
try: receipt=json.loads(receipt_body,object_pairs_hook=no_duplicates)
except (UnicodeDecodeError,json.JSONDecodeError,ValueError) as exc: raise SystemExit("rollback receipt is invalid JSON") from exc
expected={"schema_version","kind","result","deployment_id","restored_sha","rollback_state_sha256","runtime_state_sha256","completed_at"}
if not isinstance(receipt,dict) or set(receipt)!=expected or receipt.get("schema_version")!=2 or receipt.get("kind")!="agentium-release-a-rollback-receipt" or receipt.get("result")!="passed" or receipt.get("deployment_id")!=sys.argv[4] or receipt.get("restored_sha")!=sys.argv[5]: raise SystemExit("rollback receipt schema/identity differs")
if receipt.get("rollback_state_sha256")!=hashlib.sha256(rollback_body).hexdigest() or receipt.get("runtime_state_sha256")!=hashlib.sha256(runtime_body).hexdigest(): raise SystemExit("rollback receipt state binding differs")
stamp=receipt.get("completed_at")
if not isinstance(stamp,str) or not stamp.endswith("Z"): raise SystemExit("rollback receipt timestamp invalid")
try: completed=datetime.fromisoformat(stamp.removesuffix("Z")+"+00:00")
except ValueError as exc: raise SystemExit("rollback receipt timestamp invalid") from exc
if completed>datetime.now(timezone.utc)+timedelta(minutes=5): raise SystemExit("rollback receipt is future-dated")
PY
}

publish_rollback_receipt() {
	if [[ -e "$ROLLBACK_COMPLETION_RECEIPT" || -L "$ROLLBACK_COMPLETION_RECEIPT" ]]; then assert_rollback_receipt; return; fi
	assert_private "$ROLLBACK_STATE"; assert_private "$RUNTIME_STATE"
	local temporary="$DEPLOY_DIR/.rollback-receipt.$$"
	python3 -I - "$temporary" "$DEPLOYMENT_ID" "$LIVE_SHA" "$ROLLBACK_STATE" "$RUNTIME_STATE" <<'PY'
import hashlib,json,os,sys
from datetime import datetime,timezone
from pathlib import Path
out,deployment_id,restored_sha=sys.argv[1:4]; rollback,runtime=map(Path,sys.argv[4:])
payload={"schema_version":2,"kind":"agentium-release-a-rollback-receipt","result":"passed","deployment_id":deployment_id,"restored_sha":restored_sha,"rollback_state_sha256":hashlib.sha256(rollback.read_bytes()).hexdigest(),"runtime_state_sha256":hashlib.sha256(runtime.read_bytes()).hexdigest(),"completed_at":datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")}
descriptor=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(descriptor,"w",encoding="utf-8") as handle: json.dump(payload,handle,separators=(",",":"),sort_keys=True); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
PY
	durable_replace "$temporary" "$ROLLBACK_COMPLETION_RECEIPT"
	assert_rollback_receipt
}

validate_rollback_opening_boundary() {
	local pg_temporary storage_temporary
	if [[ -e "$POSTGRES_INVENTORY_BEFORE" ]]; then
		pg_temporary="$DEPLOY_DIR/.postgres-rollback.$$"
		capture_postgres_inventory "$pg_temporary"
		compare_postgres_inventory_v2 "$POSTGRES_INVENTORY_BEFORE" "$pg_temporary" || die "PostgreSQL divergent avant réouverture rollback"
		rm -f "$pg_temporary"
	fi
	if [[ -e "$STORAGE_BEFORE" ]]; then
		storage_temporary="$DEPLOY_DIR/.storage-rollback.$$"
		snapshot_storage "$storage_temporary" 1
		python3 -I - "$STORAGE_BEFORE" "$storage_temporary" <<'PY'
import json,sys
left=json.load(open(sys.argv[1],encoding="utf-8")); right=json.load(open(sys.argv[2],encoding="utf-8"))
left.pop("captured_at",None); right.pop("captured_at",None)
if left!=right: raise SystemExit("storage differs before rollback opening")
PY
		rm -f "$storage_temporary"
	fi
}

commit_rollback_opening() {
	assert_systemd_boot_guards
	publish_rollback_receipt
	set_phase rolled_back
}

assert_rollback_terminal_open_state() {
	assert_open_reconciled_marker rollback "$ROLLBACK_OPEN_RECONCILED" "$ROLLBACK_COMPLETION_RECEIPT" rolled_back
	assert_terminal_gate_authorization rollback "$ROLLBACK_OPEN_AUTHORIZATION" "$ROLLBACK_COMPLETION_RECEIPT" rollback-terminal-open rolled_back
	[[ "$(gate status)" == open ]] || die "Gate HTTP rollback terminal physiquement fermé"
	assert_writer_ingress_gates_absent
	assert_secure_mode_in_namespaces rw
	assert_restart_policies_restored
	assert_systemd_boot_guards_absent
	assert_stateful_runtime_identity
	assert_nginx_unique_edge_topology
}

reconcile_rollback_committed_open() {
	[[ "$(phase)" == rolled_back ]] || die "Réouverture rollback sans phase terminale"
	assert_rollback_receipt
	if [[ -e "$ROLLBACK_OPEN_RECONCILED" || -L "$ROLLBACK_OPEN_RECONCILED" ]]; then
		assert_open_reconciled_marker rollback "$ROLLBACK_OPEN_RECONCILED" "$ROLLBACK_COMPLETION_RECEIPT" rolled_back
	fi
	OPENING_FAIL_CLOSED_ARMED=1
	OPENING_TERMINAL_SYNCED=0
	disable_writer_restarts
	install_gate_closed
	enter_writer_ingress_gates
	stop_writers
	set_secure_mode ro
	assert_secure_mode_in_namespaces ro
	assert_writer_ingress_gates
	assert_rollback_receipt
	if [[ -e "$ROLLBACK_OPEN_AUTHORIZATION" || -L "$ROLLBACK_OPEN_AUTHORIZATION" ]]; then
		assert_terminal_gate_authorization rollback "$ROLLBACK_OPEN_AUTHORIZATION" "$ROLLBACK_COMPLETION_RECEIPT" rollback-terminal-open rolled_back
	else
		validate_rollback_opening_boundary
	fi
	start_runtime_services_without_restart
	set_secure_mode rw
	assert_secure_mode_in_namespaces rw
	assert_stateful_runtime_identity
	assert_nginx_unique_edge_topology
	publish_terminal_gate_authorization rollback "$ROLLBACK_OPEN_AUTHORIZATION" "$ROLLBACK_COMPLETION_RECEIPT" rollback-terminal-open rolled_back
	if [[ "$(gate status)" == closed ]]; then
		gate exit rollback-terminal-open "$ROLLBACK_OPEN_AUTHORIZATION"
	fi
	leave_writer_ingress_gates
	[[ "$(gate status)" == open ]] || die "Gate rollback terminal non ouvert"
	restore_restart_policies_after_open
	remove_systemd_boot_guard agentium-backend.service
	remove_systemd_boot_guard agentium-sftp.service
	publish_open_reconciled_marker rollback "$ROLLBACK_OPEN_RECONCILED" "$ROLLBACK_COMPLETION_RECEIPT" rolled_back
	assert_rollback_terminal_open_state
	OPENING_TERMINAL_SYNCED=1
	OPENING_FAIL_CLOSED_ARMED=0
	ok "Release A rollbackée; MinIO versioning reste volontairement additif"
}

reconcile_rollback_open() {
	[[ "$(phase)" == rollback_opening ]] || die "Reconcile rollback hors phase"
	OPENING_FAIL_CLOSED_ARMED=1
	OPENING_TERMINAL_SYNCED=0
	# `rollback_opening` can survive a crash after public ingress was reopened.
	# Close every writer again before validating the rollback boundary.
	disable_writer_restarts
	install_gate_closed
	enter_writer_ingress_gates
	stop_writers
	set_secure_mode ro
	assert_secure_mode_in_namespaces ro
	assert_writer_ingress_gates
	validate_rollback_opening_boundary
	start_runtime_services_without_restart
	set_secure_mode rw
	assert_secure_mode_in_namespaces rw
	assert_systemd_boot_guards
	assert_nginx_unique_edge_topology
	commit_rollback_opening
	reconcile_rollback_committed_open
}

release_a_fail_closed_trap() {
	local original_status="${1:-1}" line="${2:-unknown}" failed=0 trapped_phase=""
	[[ "$OPENING_FAIL_CLOSED_ARMED" == 1 && "$OPENING_TERMINAL_SYNCED" != 1 && "$OPENING_FAIL_CLOSED_RUNNING" != 1 ]] || return "$original_status"
	OPENING_FAIL_CLOSED_RUNNING=1
	trap - ERR EXIT HUP INT TERM
	set +e
	set +u
	set +o pipefail
	printf 'XX  erreur pendant une frontière d’ouverture (ligne %s); reclosure durable immédiate\n' "$line" >&2
	(disable_writer_restarts) || failed=1
	(install_gate_closed) || failed=1
	(enter_writer_ingress_gates) || failed=1
	trapped_phase="$(phase 2>/dev/null || true)"
	if [[ "$trapped_phase" == opening_forward || "$trapped_phase" == opened || "$trapped_phase" == completed ]] &&
		[[ -e "$SFTP_RUNTIME_READY" && ! -L "$SFTP_RUNTIME_READY" ]]; then
		# The immutable canary proof includes StartedAt.  Destroying that process
		# here would make a safe terminal replay impossible, so close every other
		# writer while keeping this exact restart-disabled SFTP runtime alive.
		(stop_writers_preserving_attested_sftp) || failed=1
	else
		(stop_writers) || failed=1
	fi
	(set_secure_mode ro) || failed=1
	(assert_secure_mode_in_namespaces ro) || failed=1
	(assert_writer_ingress_gates) || failed=1
	if [[ "$failed" -ne 0 ]]; then
		printf 'XX  reclosure incomplète: conserver la maintenance et intervenir avant toute reprise\n' >&2
	fi
	if [[ "$original_status" -eq 0 ]]; then original_status=1; fi
	exit "$original_status"
}

trap 'release_a_fail_closed_trap $? $LINENO' ERR
trap 'release_a_fail_closed_trap $? ${BASH_LINENO[0]:-unknown}' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

case "$(phase)" in
opening_forward | opened | rollback_opening)
	OPENING_FAIL_CLOSED_ARMED=1
	OPENING_TERMINAL_SYNCED=0
	;;
completed)
	if [[ ! -e "$FORWARD_OPEN_RECONCILED" || -L "$FORWARD_OPEN_RECONCILED" ]]; then
		OPENING_FAIL_CLOSED_ARMED=1
		OPENING_TERMINAL_SYNCED=0
	fi
	;;
rolled_back)
	if [[ ( -e "$ROLLBACK_COMPLETION_RECEIPT" || -L "$ROLLBACK_COMPLETION_RECEIPT" ) && ( ! -e "$ROLLBACK_OPEN_RECONCILED" || -L "$ROLLBACK_OPEN_RECONCILED" ) ]]; then
		OPENING_FAIL_CLOSED_ARMED=1
		OPENING_TERMINAL_SYNCED=0
	fi
	;;
esac

if [[ "$MODE" != preflight ]]; then
	[[ -s "$METADATA_FILE" && -x "$FROZEN_EXECUTOR" ]] || die "Preflight Release A absent"
	[[ "$(realpath -e "${BASH_SOURCE[0]}")" == "$(realpath -e "$FROZEN_EXECUTOR")" ]] || die "Après preflight, utiliser uniquement l'exécuteur figé $FROZEN_EXECUTOR"
	assert_metadata
	if [[ -e "$SFTP_IDENTITY_INVALIDATION" || -L "$SFTP_IDENTITY_INVALIDATION" ]]; then
		# The append-only invalidation wins even if power was lost before the phase
		# fsync.  Retry the physical close, then make the terminal state explicit;
		# never decide from a newly healthy-looking process that the old proof is
		# reusable.
		(install_gate_closed) || true
		(enter_writer_ingress_gates && assert_writer_ingress_gates) || true
		(disable_writer_restarts) || true
		(emergency_stop_writers_after_sftp_identity_loss) || true
		(set_secure_mode ro && assert_secure_mode_in_namespaces ro) || true
		# Validate only after reclosure: a tampered or symlinked event must never
		# keep a previously completed deployment publicly open while it is refused.
		assert_sftp_identity_invalidation
		[[ "$(phase)" == sftp_identity_invalidated ]] || set_phase sftp_identity_invalidated
		die "Transaction Release A invalidée par perte d'identité SFTP; ne pas réarmer, utiliser un nouveau deployment-id"
	fi
	if [[ "$(phase)" == sftp_identity_invalidated ]]; then
		assert_sftp_identity_invalidation
		die "Transaction Release A invalidée par perte d'identité SFTP; ne pas réarmer, utiliser un nouveau deployment-id"
	fi
	# Run before remote/Git reconciliation: once a runtime-ready receipt exists,
	# losing its exact StartedAt is the most urgent condition and must close the
	# live execution plane before any other resume/finalize work.
	guard_sftp_process_identity_or_invalidate
	stage_helpers
	reconcile_postgres_rehearsal
	if [[ -e "$CHECKOUT_INTENT" || -L "$CHECKOUT_INTENT" ]]; then assert_checkout_intent; fi
fi

case "$MODE" in
preflight) preflight_impl ;;
prepare) prepare_impl ;;
apply) apply_impl ;;
resume) resume_impl ;;
arm-sftp-canary) arm_sftp_canary_impl ;;
record-sftp-active) record_sftp_active_impl ;;
record-sftp-final) record_sftp_final_impl ;;
finalize) finalize_impl ;;
rollback) rollback_impl ;;
status) printf '%s\n' "$(phase)" ;;
esac
