#!/usr/bin/env bash
# Transactional Agentium deployment orchestrator for the single production VM.
#
# The public gate stays closed from writer quiescence until a SHA-bound tenant
# validation artifact has been checked.  State and database dumps live on the
# dedicated /srv data disk, never in the repository or /tmp.
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
REPO_DIR="${OMNIRAG_REPO_DIR:-/home/ubuntu/omnirag}"
BRANCH="demo/agentic"
EXPECTED_SHA=""
DEPLOYMENT_ID=""
VALIDATION_ARTIFACT=""
ROLLBACK_CONFIRMATION=""
WORKSPACE_APP_ANALYSIS_SHA=""
RELEASE_A_ATTESTATION=""
RELEASE_A_ATTESTATION_SHA256=""
RELEASE_A_MANIFEST=""
RELEASE_A_MANIFEST_SHA256=""
RELEASE_A_REVIEW_POLICY=""
RELEASE_A_REVIEW_POLICY_SHA256=""
declare -a CANARY_WORKSPACE_IDS=()
STATE_ROOT="${AGENTIUM_SAFE_DEPLOY_STATE_DIR:-/srv/agentium-data/deployments}"
DATA_ROOT="${AGENTIUM_DATA_ROOT:-/srv/agentium-data}"
LOCK_NAME=".agentium-deploy.lock"
LOCK_PATH="$STATE_ROOT/$LOCK_NAME"
COMPOSE_FILE="compose.agentium.yml"
LIVE_ENV_FILE="./env/agentium.vm.env"
ENV_FILE="$LIVE_ENV_FILE"
MIN_ROOT_FREE_BYTES="${AGENTIUM_SAFE_MIN_ROOT_FREE_BYTES:-42949672960}"
MIN_DATA_FREE_BYTES="${AGENTIUM_SAFE_MIN_DATA_FREE_BYTES:-68719476736}"
MIN_SECURE_FREE_BYTES="${AGENTIUM_SAFE_MIN_SECURE_FREE_BYTES:-68719476736}"
PREPARATION_MAX_AGE_SECONDS="${AGENTIUM_SAFE_PREPARATION_MAX_AGE_SECONDS:-3600}"
RELEASE_A_ATTESTATION_MAX_AGE_HOURS=24
AUDIT_WORKSPACES="${AGENTIUM_SAFE_AUDIT_WORKSPACES:-}"
EXPECTED_DATA_SOURCE="/dev/sdb"
EXPECTED_SECURE_SOURCE="/dev/sdc"
NGINX_SITE_TARGET="${AGENTIUM_NGINX_SITE_TARGET:-/etc/nginx/sites-enabled/agentium}"
NGINX_SNIPPET_TARGET="${AGENTIUM_MAINTENANCE_SNIPPET:-/etc/nginx/snippets/agentium-deploy-maintenance.conf}"

say() { printf '==> %s\n' "$*"; }
ok() { printf 'OK  %s\n' "$*"; }
die() { printf 'XX  %s\n' "$*" >&2; exit 1; }

assert_python_runtime() {
	[[ "$(python3 -I -c 'import sys; print(sys.flags.optimize)')" == 0 ]] ||
		die "Runtime Python optimisé interdit pour les contrôles de sûreté"
}

assert_no_host_python_bytecode() {
	local first
	first="$(find "$REPO_DIR/backend" -path "$REPO_DIR/backend/.venv" -prune -o -type f -name '*.pyc' -print -quit)" || die "Bytecode Python hôte non auditable"
	[[ -z "$first" ]] || die "Bytecode Python hôte interdit hors .venv: $first"
}

assert_local_docker_socket() {
	local resolved
	[[ "$DOCKER_HOST" == "$DOCKER_LOCAL_HOST" && -S /var/run/docker.sock ]] || die "Socket Docker local requis"
	resolved="$(realpath -e /var/run/docker.sock)"
	[[ "$resolved" == /run/docker.sock || "$resolved" == /var/run/docker.sock ]] || die "Socket Docker redirigé vers un chemin inattendu"
	[[ "$(stat -Lc '%u:%h' /var/run/docker.sock)" == 0:1 ]] || die "Identité du socket Docker inattendue"
}

usage() {
	cat <<'EOF'
Usage:
  deploy-agentium-safe.sh preflight --sha <40-hex> --deployment-id <id> \
    --release-a-manifest <private-json> \
    --release-a-manifest-sha256 <64-hex> \
    --release-a-review-policy <private-json> \
    --release-a-review-policy-sha256 <64-hex> \
    --release-a-attestation <private-json> \
    --release-a-attestation-sha256 <64-hex>
  deploy-agentium-safe.sh prepare   --sha <40-hex> --deployment-id <id>
  deploy-agentium-safe.sh apply     --sha <40-hex> --deployment-id <id>
  deploy-agentium-safe.sh resume    --sha <40-hex> --deployment-id <id> [--validation-artifact <json>]
  deploy-agentium-safe.sh rollback  --sha <40-hex> --deployment-id <id> --confirm-rollback <id>

The branch is demo/agentic by default.  apply intentionally stops at
validation_pending with public traffic closed; resume opens it only after a
fresh validation artifact bound to this deployment has passed.
Every mode requires exactly four repeated --canary-workspace-id <UUID> values.
They must resolve one-to-one to the active Showcase marker, Andritz family,
Sentinel profile and Octocity profile before any forward mutation is allowed.
The first preflight requires the private Release A diff manifest and its
external semantic review policy, both with explicit SHA-256 digests. This
mandatory code-provenance gate is verified before the separate operational
attestation; neither gate can replace the other. Later phases revalidate all
private frozen copies and their SHA-bound receipts.
After migration, resume requires --workspace-app-analysis-sha with the exact
dry-run digest emitted in phase backfill_pending.
EOF
}

while [[ $# -gt 0 ]]; do
	case "$1" in
	--repo-dir) REPO_DIR="$2"; shift 2 ;;
	--branch) BRANCH="$2"; shift 2 ;;
	--sha) EXPECTED_SHA="$2"; shift 2 ;;
	--deployment-id) DEPLOYMENT_ID="$2"; shift 2 ;;
	--validation-artifact) VALIDATION_ARTIFACT="$2"; shift 2 ;;
	--confirm-rollback) ROLLBACK_CONFIRMATION="$2"; shift 2 ;;
	--canary-workspace-id) CANARY_WORKSPACE_IDS+=("$2"); shift 2 ;;
	--workspace-app-analysis-sha) WORKSPACE_APP_ANALYSIS_SHA="$2"; shift 2 ;;
	--release-a-attestation) RELEASE_A_ATTESTATION="$2"; shift 2 ;;
	--release-a-attestation-sha256) RELEASE_A_ATTESTATION_SHA256="$2"; shift 2 ;;
	--release-a-manifest) RELEASE_A_MANIFEST="$2"; shift 2 ;;
	--release-a-manifest-sha256) RELEASE_A_MANIFEST_SHA256="$2"; shift 2 ;;
	--release-a-review-policy) RELEASE_A_REVIEW_POLICY="$2"; shift 2 ;;
	--release-a-review-policy-sha256) RELEASE_A_REVIEW_POLICY_SHA256="$2"; shift 2 ;;
	-h | --help) usage; exit 0 ;;
	*) die "Option inconnue: $1" ;;
	esac
done
validate_operator_inputs() {
	local artifact digest value workspace_id
	[[ "$EXPECTED_DATA_SOURCE" == /dev/* && "$EXPECTED_SECURE_SOURCE" == /dev/* ]] ||
		die "Les sources de stockage attendues doivent être des chemins /dev configurables"
	case "$MODE" in preflight | prepare | apply | resume | rollback) ;; *) usage >&2; exit 2 ;; esac
	[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || die "--sha doit être un SHA Git complet en minuscules"
	[[ "$DEPLOYMENT_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{5,95}$ ]] || die "--deployment-id invalide"
	[[ "$BRANCH" =~ ^[A-Za-z0-9._/-]+$ && "$BRANCH" != *..* ]] || die "--branch invalide"
	mapfile -t CANARY_WORKSPACE_IDS < <(printf '%s\n' "${CANARY_WORKSPACE_IDS[@]}" | sed '/^$/d' | sort -u)
	[[ "${#CANARY_WORKSPACE_IDS[@]}" -eq 4 ]] || die "Exactement quatre --canary-workspace-id explicites sont requis"
	for workspace_id in "${CANARY_WORKSPACE_IDS[@]}"; do
		[[ "$workspace_id" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] ||
			die "--canary-workspace-id doit être un UUID canonique"
	done
	[[ -z "$WORKSPACE_APP_ANALYSIS_SHA" || "$WORKSPACE_APP_ANALYSIS_SHA" =~ ^[0-9a-f]{64}$ ]] ||
		die "--workspace-app-analysis-sha invalide"
	[[ -z "$RELEASE_A_ATTESTATION_SHA256" || "$RELEASE_A_ATTESTATION_SHA256" =~ ^[0-9a-f]{64}$ ]] ||
		die "--release-a-attestation-sha256 invalide"
	[[ -z "$RELEASE_A_ATTESTATION" || ( "$RELEASE_A_ATTESTATION" == /* && "$RELEASE_A_ATTESTATION" != *..* ) ]] ||
		die "--release-a-attestation doit être absolu et sans traversée"
	for digest in "$RELEASE_A_MANIFEST_SHA256" "$RELEASE_A_REVIEW_POLICY_SHA256"; do
		[[ -z "$digest" || "$digest" =~ ^[0-9a-f]{64}$ ]] || die "Digest manifeste/revue Release A invalide"
	done
	for artifact in "$RELEASE_A_MANIFEST" "$RELEASE_A_REVIEW_POLICY"; do
		[[ -z "$artifact" || ( "$artifact" == /* && "$artifact" != *..* ) ]] ||
			die "Les artefacts manifeste/revue Release A doivent être absolus et sans traversée"
	done
	[[ "$REPO_DIR" == /* && "$REPO_DIR" != *..* ]] || die "--repo-dir doit être absolu et sans traversée"
	[[ "$STATE_ROOT" == /* && "$STATE_ROOT" != *..* ]] || die "AGENTIUM_SAFE_DEPLOY_STATE_DIR invalide"
	[[ "$DATA_ROOT" == /* && "$DATA_ROOT" != *..* ]] || die "AGENTIUM_DATA_ROOT invalide"
	for value in "$MIN_ROOT_FREE_BYTES" "$MIN_DATA_FREE_BYTES" "$MIN_SECURE_FREE_BYTES" "$PREPARATION_MAX_AGE_SECONDS"; do
		[[ "$value" =~ ^[0-9]+$ ]] || die "Un seuil numérique de déploiement est invalide"
	done
	(( MIN_ROOT_FREE_BYTES >= 42949672960 )) || die "Le seuil racine ne peut pas être inférieur à 40 Gio"
	(( MIN_DATA_FREE_BYTES >= 68719476736 )) || die "Le seuil data ne peut pas être inférieur à 64 Gio"
	(( MIN_SECURE_FREE_BYTES >= 68719476736 )) || die "Le seuil Secure Deposit ne peut pas être inférieur à 64 Gio"
	(( PREPARATION_MAX_AGE_SECONDS >= 1 && PREPARATION_MAX_AGE_SECONDS <= 3600 )) ||
		die "La durée de préparation doit rester comprise entre 1 et 3600 secondes"
}
SFTP_GATE_COMMENT="agentium-safe-sftp-$DEPLOYMENT_ID"
LIVEKIT_GATE_COMMENT="agentium-safe-livekit-$DEPLOYMENT_ID"
SYSTEMD_GATE_COMMENT="agentium-safe-systemd-backend-$DEPLOYMENT_ID"

DEPLOY_DIR="$STATE_ROOT/$DEPLOYMENT_ID"
METADATA_FILE="$DEPLOY_DIR/metadata.tsv"
PHASE_FILE="$DEPLOY_DIR/phase"
ROLLBACK_DIR="$DEPLOY_DIR/rollback"
ROLLBACK_STATE="$ROLLBACK_DIR/${EXPECTED_SHA}.tsv"
STORAGE_BASELINE="$DEPLOY_DIR/storage-baseline.json"
STORAGE_QUIESCED="$DEPLOY_DIR/storage-quiesced.json"
STORAGE_AFTER="$DEPLOY_DIR/storage-after.json"
STORAGE_COMPARISON="$DEPLOY_DIR/storage-comparison.json"
STORAGE_POST_CANARY="$DEPLOY_DIR/storage-post-canary.json"
STORAGE_CANARY_COMPARISON="$DEPLOY_DIR/storage-canary-comparison.json"
DATABASE_CANARY_BASELINE="$DEPLOY_DIR/database-pre-canary-row-inventory.json"
DATABASE_POST_CANARY_INVENTORY="$DEPLOY_DIR/database-post-canary-row-inventory.json"
DATABASE_FINAL_CANARY_INVENTORY="$DEPLOY_DIR/database-final-open-row-inventory.json"
DATABASE_POST_CANARY_COMPARISON="$DEPLOY_DIR/database-post-canary-comparison.json"
DATABASE_OPENING_RECAPTURE="$DEPLOY_DIR/database-opening-recapture-row-inventory.json"
DATABASE_OPENING_COMPARISON="$DEPLOY_DIR/database-opening-boundary-comparison.json"
WORKSPACE_APP_DRY_RUN="$DEPLOY_DIR/workspace-app-backfill-dry-run.json"
WORKSPACE_APP_APPLY="$DEPLOY_DIR/workspace-app-backfill-apply.json"
WORKSPACE_APP_POST="$DEPLOY_DIR/workspace-app-backfill-post.json"
WORKSPACE_TARGETS="$DEPLOY_DIR/workspace-targets.json"
CANDIDATE_CHECKOUT_INTENT="$DEPLOY_DIR/candidate-checkout.intent"
MAINTENANCE_HELPER="$DEPLOY_DIR/agentium-maintenance-gate.sh"
STORAGE_HELPER="$DEPLOY_DIR/agentium_storage_attestation.py"
VALIDATION_HELPER="$DEPLOY_DIR/agentium_safe_validation.py"
RELEASE_A_HELPER="$DEPLOY_DIR/agentium_release_a_attestation.py"
RELEASE_A_MANIFEST_HELPER="$DEPLOY_DIR/agentium_release_a_manifest.py"
FROZEN_RELEASE_A_ATTESTATION="$DEPLOY_DIR/release-a-attestation.json"
RELEASE_A_RECEIPT="$DEPLOY_DIR/release-a-verification-receipt.json"
FROZEN_RELEASE_A_MANIFEST="$DEPLOY_DIR/release-a-diff-manifest.json"
FROZEN_RELEASE_A_REVIEW_POLICY="$DEPLOY_DIR/release-a-semantic-review.json"
RELEASE_A_MANIFEST_RECEIPT="$DEPLOY_DIR/release-a-manifest-verification-receipt.json"
FROZEN_DEPLOYER="$DEPLOY_DIR/deploy-vm-candidate.sh"
FROZEN_ORCHESTRATOR="$DEPLOY_DIR/deploy-agentium-safe.sh"
FROZEN_NGINX_SITE="$DEPLOY_DIR/nginx-agentium-site.conf"
FROZEN_NGINX_SNIPPET="$DEPLOY_DIR/nginx-agentium-maintenance.conf"
FROZEN_SYSTEMD_UNIT="$DEPLOY_DIR/agentium-backend.service"
FROZEN_SYSTEMD_INSTALLER="$DEPLOY_DIR/install-backend-service.sh"
QDRANT_BARRIER_HELPER="$DEPLOY_DIR/audit_qdrant_write_barrier.py"
SFTP_BOUNDARY_HELPER="$DEPLOY_DIR/audit_sftp_deploy_boundary.py"
ENV_BUNDLE_HELPER="$DEPLOY_DIR/agentium_runtime_env_bundle.py"
ENV_BUNDLE_DIR="$DEPLOY_DIR/runtime-env"
ENV_BUNDLE_INTENT="$DEPLOY_DIR/runtime-env.intent"
ENV_BUNDLE_MANIFEST="$ENV_BUNDLE_DIR/manifest.json"
FROZEN_COMPOSE_ENV="$ENV_BUNDLE_DIR/compose.effective.env"
FROZEN_SYSTEMD_ENV=""
SYSTEMD_ENV_DROPIN_TARGET="/etc/systemd/system/agentium-backend.service.d/99-agentium-safe-runtime-env.conf"
SYSTEMD_ENV_DROPIN_STATE="$DEPLOY_DIR/systemd-env-dropin.state"
SYSTEMD_ENV_DROPIN_BACKUP="$DEPLOY_DIR/systemd-env-dropin.previous"
FROZEN_QDRANT_OVERRIDE="$DEPLOY_DIR/compose.agentium.qdrant-barrier.yml"
FROZEN_OPENED_OVERRIDE="$DEPLOY_DIR/compose.agentium.opened.yml"
CANDIDATE_IMAGE_OVERRIDE="$DEPLOY_DIR/compose.agentium.candidate-images.yml"
ROLLBACK_IMAGE_OVERRIDE="$DEPLOY_DIR/compose.agentium.rollback-images.yml"
PROVENANCE_FILE="$DEPLOY_DIR/proofs/provenance.json"
QDRANT_PREFLIGHT_BARRIER="$DEPLOY_DIR/qdrant-preflight-barrier.json"
QDRANT_VALIDATION_BARRIER="$DEPLOY_DIR/qdrant-validation-barrier.json"
QDRANT_POST_CANARY_BARRIER="$DEPLOY_DIR/qdrant-post-canary-barrier.json"
QDRANT_ADMIN_READY_BARRIER="$DEPLOY_DIR/qdrant-admin-ready-barrier.json"
QDRANT_BACKEND_PROBE="$DEPLOY_DIR/qdrant-backend-probe.json"
QDRANT_WORKER_PROBE="$DEPLOY_DIR/qdrant-worker-probe.json"
QDRANT_P4_PROBE="$DEPLOY_DIR/qdrant-p4-admin-probe.json"
SFTP_CLOSED_BEFORE="$DEPLOY_DIR/proofs/sftp-closed-before-canaries.json"
SFTP_CLOSED_AFTER="$DEPLOY_DIR/proofs/sftp-closed-after-canaries.json"
SFTP_PROTOCOL_PROOF="$DEPLOY_DIR/proofs/sftp-docker-protocol.json"
SFTP_PUBLISHED_PROOF="$DEPLOY_DIR/proofs/sftp-host-banner.json"
SFTP_OPENING_INTENT="$DEPLOY_DIR/sftp-opening-intent"
SFTP_ROLLBACK_CLOSED="$DEPLOY_DIR/proofs/sftp-rollback-closed-boundary.json"
SFTP_ROLLBACK_PROOF="$DEPLOY_DIR/proofs/sftp-rollback-continuity.json"
SFTP_ROLLBACK_OPENING_INTENT="$DEPLOY_DIR/sftp-rollback-opening-intent"
PREPARED_AT_FILE="$DEPLOY_DIR/prepared-at"
RUNTIME_STATE_FILE="$DEPLOY_DIR/runtime-state.tsv"
BUILD_WORKTREE="$DATA_ROOT/deploy-builds/$DEPLOYMENT_ID"
REHEARSAL_BASE="$DATA_ROOT/deploy-rehearsal"
REHEARSAL_INTENT="$DEPLOY_DIR/rehearsal-active.tsv"
MIGRATION_DATABASE_SECRET="$DEPLOY_DIR/migration-database-url.secret"
MIGRATION_NETWORK_KEY="$(printf '%s' "$DEPLOYMENT_ID" | sha256sum | cut -c1-12)"
MIGRATION_NETWORK="agentium-db-migration-${EXPECTED_SHA:0:12}-${MIGRATION_NETWORK_KEY}"
LIVE_WRITER_AUDIT_SECRET="$DEPLOY_DIR/live-writer-audit.secret.json"
LIVE_WRITER_AUDIT_NETWORK="agentium-live-audit-${EXPECTED_SHA:0:12}-${MIGRATION_NETWORK_KEY}"
STAGE="initialization"
ROLLBACK_ACTIVE=0
REHEARSAL_ACTIVE=0
MIGRATION_BOUNDARY_ACTIVE=0
LIVE_WRITER_AUDIT_ACTIVE=0
OPENING_BOUNDARY_SEALED=0
COMPOSE_CLEAN_HOME=""

# These names are accepted only when this frozen script assigns them directly
# to an individual Compose call.  Never inherit transaction controls from the
# operator shell.
unset AGENTIUM_QDRANT_EFFECTIVE_API_KEY AGENTIUM_CELERY_BEAT AGENTIUM_STARTUP_RECONCILIATION AGENTIUM_PIN_CANDIDATE_IMAGES AGENTIUM_PIN_ROLLBACK_IMAGES

# A SIGKILL can leave an opening intent durable while SFTP has already been
# exposed or /dev/sdc has been remounted read-write.  Arm this minimal sealer
# before Docker, filesystem, journal or frozen-orchestrator validation.  It is
# deliberately self-contained: the richer transaction helpers are not trusted
# yet at this point in bootstrap.
BOOTSTRAP_OPENING_ACTIVE=0
BOOTSTRAP_OPENING_SEALED=0

bootstrap_sudo_command() {
	if [[ "$(id -u)" -eq 0 ]]; then "$@"; else sudo -n "$@"; fi
}

bootstrap_secure_deposit_read_only() {
	local options target
	target="$(findmnt -rn -S "$EXPECTED_SECURE_SOURCE" -o TARGET 2>/dev/null | awk 'NF { if (found++) exit 2; print }')" || return 1
	[[ "$target" == /* && -d "$target" ]] || return 1
	options="$(findmnt -n -o OPTIONS --target "$target" 2>/dev/null)" || return 1
	if [[ ",$options," != *,ro,* ]]; then
		sync -f "$target" || return 1
		bootstrap_sudo_command mount -o remount,ro "$target" || return 1
		options="$(findmnt -n -o OPTIONS --target "$target" 2>/dev/null)" || return 1
	fi
	[[ ",$options," == *,ro,* ]]
}

bootstrap_stop_sftp_writers() {
	local code=0 paused running
	if docker inspect agentium-sftp >/dev/null 2>&1; then
		docker update --restart=no agentium-sftp >/dev/null 2>&1 || code=1
		paused="$(docker inspect --format '{{.State.Paused}}' agentium-sftp 2>/dev/null || true)"
		[[ "$paused" != true ]] || docker unpause agentium-sftp >/dev/null 2>&1 || code=1
		running="$(docker inspect --format '{{.State.Running}}' agentium-sftp 2>/dev/null || true)"
		[[ "$running" != true ]] || docker stop --time 15 agentium-sftp >/dev/null 2>&1 || code=1
		[[ "$(docker inspect --format '{{.State.Running}}' agentium-sftp 2>/dev/null || true)" == false ]] || code=1
	elif ! docker info >/dev/null 2>&1; then
		code=1
	fi
	if bootstrap_sudo_command systemctl cat agentium-sftp.service >/dev/null 2>&1; then
		bootstrap_sudo_command systemctl stop agentium-sftp.service >/dev/null 2>&1 || code=1
		if bootstrap_sudo_command systemctl is-active --quiet agentium-sftp.service; then code=1; fi
	fi
	bootstrap_secure_deposit_read_only || code=1
	return "$code"
}

bootstrap_stop_all_writers() {
	local code=0 paused running service
	# SFTP and /dev/sdc are sealed first because this is the only writer with a
	# public non-HTTP ingress and a separately mounted customer deposit.
	bootstrap_stop_sftp_writers || code=1
	for service in agentium-backend agentium-worker-cpu agentium-p4-maintenance agentium-livekit agentium-livekit-agent agentium-kc; do
		if docker inspect "$service" >/dev/null 2>&1; then
			docker update --restart=no "$service" >/dev/null 2>&1 || code=1
			paused="$(docker inspect --format '{{.State.Paused}}' "$service" 2>/dev/null || true)"
			[[ "$paused" != true ]] || docker unpause "$service" >/dev/null 2>&1 || code=1
			running="$(docker inspect --format '{{.State.Running}}' "$service" 2>/dev/null || true)"
			[[ "$running" != true ]] || docker stop --time 15 "$service" >/dev/null 2>&1 || code=1
			[[ "$(docker inspect --format '{{.State.Running}}' "$service" 2>/dev/null || true)" == false ]] || code=1
		fi
	done
	if bootstrap_sudo_command systemctl cat agentium-backend.service >/dev/null 2>&1; then
		bootstrap_sudo_command systemctl stop agentium-backend.service >/dev/null 2>&1 || code=1
		if bootstrap_sudo_command systemctl is-active --quiet agentium-backend.service; then code=1; fi
	fi
	return "$code"
}

bootstrap_sftp_gate_rule() {
	local action="$1" tool="$2" chain="$3" port="$4"
	local -a match
	[[ "$action" == "-C" || "$action" == "-I" ]] || return 2
	if [[ "$chain" == DOCKER-USER ]]; then
		match=(! -i lo -p tcp -m conntrack --ctorigdstport "$port" --ctstate NEW)
	else
		match=(! -i lo -p tcp --dport "$port" -m conntrack --ctstate NEW)
	fi
	if [[ "$action" == -I ]]; then
		bootstrap_sudo_command "$tool" -w 10 -I "$chain" 1 "${match[@]}" \
			-m comment --comment "$SFTP_GATE_COMMENT" -j REJECT --reject-with tcp-reset
	else
		bootstrap_sudo_command "$tool" -w 10 -C "$chain" "${match[@]}" \
			-m comment --comment "$SFTP_GATE_COMMENT" -j REJECT --reject-with tcp-reset
	fi
}

bootstrap_close_sftp_ingress_monotone() {
	local chain code=0 port ports tool
	ports="$(docker port agentium-sftp 2222/tcp 2>/dev/null | awk -F: '{print $NF}' | sort -u)"
	if [[ ! "$ports" =~ ^[0-9]+$ ]]; then
		bootstrap_stop_sftp_writers
		return
	fi
	port="$ports"
	for tool in iptables ip6tables; do
		if ! command -v "$tool" >/dev/null 2>&1; then code=1; continue; fi
		for chain in INPUT DOCKER-USER; do
			if ! bootstrap_sftp_gate_rule -C "$tool" "$chain" "$port" >/dev/null 2>&1; then
				bootstrap_sftp_gate_rule -I "$tool" "$chain" "$port" >/dev/null 2>&1 || code=1
			fi
		done
	done
	for tool in iptables ip6tables; do
		command -v "$tool" >/dev/null 2>&1 || { code=1; continue; }
		for chain in INPUT DOCKER-USER; do
			bootstrap_sftp_gate_rule -C "$tool" "$chain" "$port" >/dev/null 2>&1 || code=1
		done
	done
	if [[ "$code" -ne 0 ]]; then
		# Never delete a rule that was already inserted: the fallback removes the
		# writer itself and makes its data mount read-only.
		bootstrap_stop_sftp_writers
		return
	fi
}

bootstrap_opening_reclosure() {
	local persisted_phase stat_row
	[[ "$DEPLOYMENT_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{5,95}$ ]] || return 0
	[[ "$DATA_ROOT" == /srv/agentium-data && "$STATE_ROOT" == /srv/agentium-data/deployments ]] || return 0
	[[ -e "$DEPLOY_DIR" || -L "$DEPLOY_DIR" ]] || return 0
	[[ -e "$PHASE_FILE" || -L "$PHASE_FILE" ]] || return 0
	if [[ ! -f "$PHASE_FILE" || -L "$PHASE_FILE" ]]; then
		BOOTSTRAP_OPENING_ACTIVE=1
		bootstrap_stop_all_writers
		return 1
	fi
	stat_row="$(stat -c '%a:%u:%h' "$PHASE_FILE" 2>/dev/null || true)"
	if [[ "$stat_row" != "600:$(id -u):1" ]]; then
		BOOTSTRAP_OPENING_ACTIVE=1
		bootstrap_stop_all_writers
		return 1
	fi
	persisted_phase="$(<"$PHASE_FILE")"
	case "$persisted_phase" in opening_forward | rollback_opening) ;; *) return 0 ;; esac
	BOOTSTRAP_OPENING_ACTIVE=1
	bootstrap_close_sftp_ingress_monotone || true
	bootstrap_stop_all_writers || return 1
	BOOTSTRAP_OPENING_SEALED=1
}

bootstrap_on_error() {
	local code="$1"
	trap - ERR
	set +e
	bootstrap_opening_reclosure
	exit "$code"
}

bootstrap_on_exit() {
	local code="$1"
	trap - ERR EXIT HUP INT TERM
	set +e
	if [[ "$BOOTSTRAP_OPENING_ACTIVE" -eq 1 && "$BOOTSTRAP_OPENING_SEALED" -ne 1 ]]; then
		bootstrap_opening_reclosure || code=1
	fi
	exit "$code"
}

trap 'bootstrap_on_error $?' ERR
trap 'bootstrap_on_exit $?' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
bootstrap_opening_reclosure
validate_operator_inputs

assert_local_docker_socket
assert_python_runtime

[[ -d "$DATA_ROOT" ]] || die "Data root absent; aucun répertoire ne sera créé sur la racine: $DATA_ROOT"
[[ "$(stat -c '%d' "$DATA_ROOT")" != "$(stat -c '%d' /)" ]] ||
	die "$DATA_ROOT n'est pas un filesystem dédié; état de déploiement refusé sur la racine"
[[ "$DATA_ROOT" == /srv/agentium-data ]] || die "Data root de déploiement non canonique"
[[ "$STATE_ROOT" == "$DATA_ROOT/deployments" ]] || die "Journal de déploiement non canonique"
[[ -d "$DATA_ROOT" && ! -L "$DATA_ROOT" ]] || die "Data root canonique absent ou symbolique"
python3 -I - "$DATA_ROOT" <<'PY'
import stat
import sys
from pathlib import Path

data = Path(sys.argv[1])
details = data.lstat()
if not stat.S_ISDIR(details.st_mode) or stat.S_ISLNK(details.st_mode):
    raise SystemExit("data root must be a real directory")
if data.resolve(strict=True) != data.absolute():
    raise SystemExit("data root path contains a symbolic component")
PY
state_device="$(findmnt -n -o SOURCE --target "$DATA_ROOT")"
state_device="${state_device%%[*}"
[[ "$(findmnt -n -o TARGET --target "$DATA_ROOT")" == "$DATA_ROOT" && "$state_device" == "$EXPECTED_DATA_SOURCE" ]] ||
	die "Le journal de déploiement doit être porté par le mountpoint $EXPECTED_DATA_SOURCE"

ensure_private_child_dir() {
	local parent="$1" name="$2" create="$3"
	python3 -I - "$parent" "$name" "$create" <<'PY'
import os
import re
import stat
import sys
from pathlib import Path

parent = Path(sys.argv[1])
name = sys.argv[2]
create = sys.argv[3] == "1"
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", name):
    raise SystemExit("unsafe private directory name")
before = parent.lstat()
if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
    raise SystemExit("private directory parent is not a real directory")
flags = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
parent_fd = os.open(parent, flags)
try:
    opened = os.fstat(parent_fd)
    if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
        raise SystemExit("private directory parent changed")
    try:
        row = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        if not create:
            raise SystemExit("required private directory is absent")
        os.mkdir(name, 0o700, dir_fd=parent_fd)
        os.fsync(parent_fd)
        row = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if stat.S_ISLNK(row.st_mode) or not stat.S_ISDIR(row.st_mode):
        raise SystemExit("private directory is not a real directory")
    if row.st_uid != os.geteuid() or stat.S_IMODE(row.st_mode) != 0o700 or row.st_nlink < 2:
        raise SystemExit("private directory owner/mode/link identity differs")
    if row.st_dev != opened.st_dev:
        raise SystemExit("private directory crossed a filesystem boundary")
    child_fd = os.open(name, flags, dir_fd=parent_fd)
    try:
        child = os.fstat(child_fd)
        if (child.st_dev, child.st_ino) != (row.st_dev, row.st_ino):
            raise SystemExit("private directory changed while opening")
    finally:
        os.close(child_fd)
finally:
    os.close(parent_fd)
PY
}

ensure_private_lock_file() {
	local parent="$1" name="$2"
	python3 -I - "$parent" "$name" <<'PY'
import os
import stat
import sys
from pathlib import Path

parent = Path(sys.argv[1])
name = sys.argv[2]
before = parent.lstat()
if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
    raise SystemExit("lock parent is not a real directory")
directory_flags = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
parent_fd = os.open(parent, directory_flags)
try:
    opened_parent = os.fstat(parent_fd)
    if (opened_parent.st_dev, opened_parent.st_ino) != (before.st_dev, before.st_ino):
        raise SystemExit("lock parent changed")
    flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    created = False
    try:
        lock_fd = os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        lock_fd = os.open(name, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent_fd)
        created = True
    try:
        opened_lock = os.fstat(lock_fd)
        path_lock = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISREG(opened_lock.st_mode) or not stat.S_ISREG(path_lock.st_mode):
            raise SystemExit("deployment compatibility lock is not a real file")
        if (opened_lock.st_dev, opened_lock.st_ino) != (path_lock.st_dev, path_lock.st_ino):
            raise SystemExit("deployment compatibility lock changed while opening")
        if opened_lock.st_dev != opened_parent.st_dev:
            raise SystemExit("deployment compatibility lock crossed a filesystem boundary")
        if opened_lock.st_uid != os.geteuid() or stat.S_IMODE(opened_lock.st_mode) != 0o600 or opened_lock.st_nlink != 1:
            raise SystemExit("deployment compatibility lock owner/mode/link identity differs")
        if created:
            os.fsync(lock_fd)
            os.fsync(parent_fd)
    finally:
        os.close(lock_fd)
finally:
    os.close(parent_fd)
PY
}

if [[ -e "$STATE_ROOT" || -L "$STATE_ROOT" ]]; then
	ensure_private_child_dir "$DATA_ROOT" deployments 0
else
	[[ "$MODE" == preflight ]] || die "Journal de déploiement absent; commencer par preflight"
	ensure_private_child_dir "$DATA_ROOT" deployments 1
fi
[[ "$(findmnt -n -o TARGET --target "$STATE_ROOT")" == "$DATA_ROOT" ]] ||
	die "Le journal de déploiement ne doit pas être un mountpoint distinct"

# FD 9 is deliberately inherited by the frozen-orchestrator re-exec.  Reusing
# the same open-file description preserves the lock without a race window.
state_root_identity="$(stat -Lc '%d:%i' "$STATE_ROOT")"
if [[ -e "/proc/$$/fd/9" ]]; then
	[[ "$(stat -Lc '%d:%i' "/proc/$$/fd/9")" == "$state_root_identity" ]] ||
		die "Le FD 9 hérité ne désigne pas le journal vérifié"
else
	exec 9<"$STATE_ROOT"
fi

assert_state_root_fd_identity() {
	[[ -d "$STATE_ROOT" && ! -L "$STATE_ROOT" ]] || die "Journal remplacé par un chemin non sûr"
	[[ "$(stat -Lc '%d:%i' "/proc/$$/fd/9")" == "$state_root_identity" && "$(stat -c '%d:%i' "$STATE_ROOT")" == "$state_root_identity" ]] ||
		die "Journal remplacé pendant son ouverture"
	[[ "$(findmnt -n -o TARGET --target "$STATE_ROOT")" == "$DATA_ROOT" ]] ||
		die "Le FD du journal ne correspond plus au mountpoint data"
}

assert_state_root_fd_identity
flock -n 9 || die "Un autre déploiement Agentium détient le journal $STATE_ROOT"
assert_state_root_fd_identity

# Keep the historical lock-file solely as a secondary compatibility lock for
# the separately executed canary runner.  Creation is nofollow/race-aware and
# FD/path identity is checked before flock; STATE_ROOT remains the primary lock.
ensure_private_lock_file "$STATE_ROOT" "$LOCK_NAME"
lock_identity="$(stat -c '%d:%i' "$LOCK_PATH")"
if [[ -e "/proc/$$/fd/8" ]]; then
	[[ "$(stat -Lc '%d:%i' "/proc/$$/fd/8")" == "$lock_identity" ]] ||
		die "Le FD 8 hérité ne désigne pas le lock de compatibilité vérifié"
else
	exec 8<>"$LOCK_PATH"
fi
[[ ! -L "$LOCK_PATH" && -f "/proc/$$/fd/8" && "$(stat -Lc '%a:%u:%h:%d:%i' "/proc/$$/fd/8")" == "600:$(id -u):1:$lock_identity" && "$(stat -c '%d:%i' "$LOCK_PATH")" == "$lock_identity" ]] ||
	die "Lock de compatibilité remplacé ou non privé pendant son ouverture"
flock -n 8 || die "Un canari ou un autre déploiement Agentium est actif"
assert_state_root_fd_identity

if [[ -e "$DEPLOY_DIR" || -L "$DEPLOY_DIR" ]]; then
	ensure_private_child_dir "$STATE_ROOT" "$DEPLOYMENT_ID" 0
else
	[[ "$MODE" == preflight ]] || die "Déploiement absent; commencer par preflight"
	ensure_private_child_dir "$STATE_ROOT" "$DEPLOYMENT_ID" 1
fi
assert_state_root_fd_identity
[[ "$(findmnt -n -o TARGET --target "$DEPLOY_DIR")" == "$DATA_ROOT" ]] ||
	die "Le journal de déploiement a quitté $EXPECTED_DATA_SOURCE"

# The first invocation may come from a detached candidate worktree because the
# previous live checkout does not contain this orchestrator yet.  Freeze the
# candidate blob on the locked data-disk journal and immediately re-exec it.
# The verified directory and compatibility lock FDs remain inherited, so every
# later phase executes the same bytes without creating a lock race window,
# even after the live checkout moves back and forth during rollback.
candidate_orchestrator_blob="$(git -C "$REPO_DIR" rev-parse "${EXPECTED_SHA}:scripts/deploy-agentium-safe.sh" 2>/dev/null || true)"
[[ "$candidate_orchestrator_blob" =~ ^[0-9a-f]{40}$ ]] ||
	die "Orchestrateur candidat absent du dépôt live; fetcher d'abord le SHA $EXPECTED_SHA"
if [[ ! -f "$FROZEN_ORCHESTRATOR" ]]; then
	temporary_orchestrator="$DEPLOY_DIR/.deploy-agentium-safe.$$"
	(umask 077; git -C "$REPO_DIR" show "${EXPECTED_SHA}:scripts/deploy-agentium-safe.sh" >"$temporary_orchestrator")
	[[ "$(git -C "$REPO_DIR" hash-object "$temporary_orchestrator")" == "$candidate_orchestrator_blob" ]] ||
		die "Extraction de l'orchestrateur candidat altérée"
	if ln "$temporary_orchestrator" "$FROZEN_ORCHESTRATOR" 2>/dev/null; then
		rm -f "$temporary_orchestrator"
	else
		rm -f "$temporary_orchestrator"
		die "Orchestrateur figé créé concurremment"
	fi
	chmod 0700 "$FROZEN_ORCHESTRATOR"
fi
[[ "$(git -C "$REPO_DIR" hash-object "$FROZEN_ORCHESTRATOR")" == "$candidate_orchestrator_blob" ]] ||
	die "Orchestrateur figé différent du SHA candidat"
if [[ "$(realpath -m "${BASH_SOURCE[0]}")" != "$(realpath -e "$FROZEN_ORCHESTRATOR")" ]]; then
	[[ "$(git -C "$REPO_DIR" hash-object "${BASH_SOURCE[0]}")" == "$candidate_orchestrator_blob" ]] ||
		die "Bootstrap refusé depuis un orchestrateur qui n'est pas celui du candidat"
	declare -a frozen_args=("$MODE" --repo-dir "$REPO_DIR" --branch "$BRANCH" --sha "$EXPECTED_SHA" --deployment-id "$DEPLOYMENT_ID")
	for workspace_id in "${CANARY_WORKSPACE_IDS[@]}"; do frozen_args+=(--canary-workspace-id "$workspace_id"); done
	[[ -z "$WORKSPACE_APP_ANALYSIS_SHA" ]] || frozen_args+=(--workspace-app-analysis-sha "$WORKSPACE_APP_ANALYSIS_SHA")
	[[ -z "$RELEASE_A_ATTESTATION" ]] || frozen_args+=(--release-a-attestation "$RELEASE_A_ATTESTATION")
	[[ -z "$RELEASE_A_ATTESTATION_SHA256" ]] || frozen_args+=(--release-a-attestation-sha256 "$RELEASE_A_ATTESTATION_SHA256")
	[[ -z "$RELEASE_A_MANIFEST" ]] || frozen_args+=(--release-a-manifest "$RELEASE_A_MANIFEST")
	[[ -z "$RELEASE_A_MANIFEST_SHA256" ]] || frozen_args+=(--release-a-manifest-sha256 "$RELEASE_A_MANIFEST_SHA256")
	[[ -z "$RELEASE_A_REVIEW_POLICY" ]] || frozen_args+=(--release-a-review-policy "$RELEASE_A_REVIEW_POLICY")
	[[ -z "$RELEASE_A_REVIEW_POLICY_SHA256" ]] || frozen_args+=(--release-a-review-policy-sha256 "$RELEASE_A_REVIEW_POLICY_SHA256")
	[[ -z "$VALIDATION_ARTIFACT" ]] || frozen_args+=(--validation-artifact "$VALIDATION_ARTIFACT")
	[[ -z "$ROLLBACK_CONFIRMATION" ]] || frozen_args+=(--confirm-rollback "$ROLLBACK_CONFIRMATION")
	exec "$FROZEN_ORCHESTRATOR" "${frozen_args[@]}"
fi
cd "$REPO_DIR"
COMPOSE_CLEAN_HOME="$(getent passwd "$(id -u)" | awk -F: 'NR == 1 {print $6}')"
[[ "$COMPOSE_CLEAN_HOME" == /* && -d "$COMPOSE_CLEAN_HOME" ]] ||
	die "HOME effectif du compte de déploiement introuvable"

on_error() {
	local code="$1" line="$2" phase="unknown"
	trap - ERR
	set +e
	[[ -f "$PHASE_FILE" ]] && phase="$(<"$PHASE_FILE")"
	printf 'XX  Déploiement interrompu à %s (ligne %s, code %s, phase %s).\n' \
		"$STAGE" "$line" "$code" "$phase" >&2
	case "$phase" in
	prepared)
		if [[ "$(gate status 2>/dev/null)" == "closed" ]] && (recover_prepared_barrier_failure); then
			printf 'XX  Armement pré-fermeture interrompu: états et ingress historiques restaurés; phase prepared conservée.\n' >&2
		elif [[ "$(gate status 2>/dev/null)" == "closed" ]]; then
			printf 'XX  Récupération pré-fermeture incomplète; gate maintenu fermé.\n' >&2
		fi
		;;
	closing_intent | closing | maintenance_closed | quiesced | recovering_pre_migration | rollback_closing)
		if [[ "$ROLLBACK_ACTIVE" -eq 1 ]]; then
			printf 'XX  Rollback interrompu; aucune reprise automatique, gate maintenu fermé.\n' >&2
		elif (recover_pre_migration_failure); then
			printf 'XX  DB encore sur la révision précédente: writers historiques et gate public restaurés.\n' >&2
		else
			printf 'XX  Récupération automatique pré-migration impossible; gate maintenu fermé.\n' >&2
		fi
		;;
	migrated)
		if (requiesce_partial_candidate); then
			printf 'XX  Activation candidate partielle remise en quiescence; gate maintenu fermé.\n' >&2
		else
			printf 'XX  Requiescence candidate partielle incomplète; gate maintenu fermé.\n' >&2
		fi
		printf 'XX  Utiliser resume ou rollback avec le même deployment-id.\n' >&2
		;;
	backfill_pending | backfill_applying)
		printf 'XX  Backfill Workspace Apps fermé et reprenable; gate maintenu fermé. Utiliser resume avec le SHA d’analyse exact.\n' >&2
		;;
	activated)
		printf 'XX  Gate maintenu fermé. Utiliser resume ou rollback avec le même deployment-id.\n' >&2
		;;
	opening_forward | rollback_opening)
		if (seal_public_opening_boundary_fail_closed "$phase"); then
			OPENING_BOUNDARY_SEALED=1
			printf "XX  Intention d'ouverture interrompue: ingress refermés, writers arrêtés et Secure Deposit remis en lecture seule.\n" >&2
		else
			printf "XX  Reclosure de l'intention d'ouverture incomplète; reprise fail-closed requise.\n" >&2
		fi
		;;
	rolled_back_restored)
		printf 'XX  DB précédente déjà restaurée; reprise forward du rollback requise, nouvelle restauration interdite.\n' >&2
		;;
	rollback_restoring)
		printf 'XX  Restauration DB interrompue; writers et gates restent fermés. Relancer rollback avec le même deployment-id.\n' >&2
		;;
	validation_starting | validation_pending)
		if requiesce_validation_runtime; then
			printf 'XX  Runtime de validation remis en lecture seule; gate maintenu fermé.\n' >&2
		else
			printf 'XX  Requiescence de validation incomplète; gate maintenu fermé.\n' >&2
		fi
		;;
	esac
	exit "$code"
}
trap 'on_error $? $LINENO' ERR

atomic_text() {
	local target="$1" value="$2"
	python3 - "$target" "$value" <<'PY'
import os
import sys
from pathlib import Path

target = Path(sys.argv[1])
value = sys.argv[2]
temporary = target.parent / f".{target.name}.{os.getpid()}"
fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(value + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)
    directory_fd = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
except BaseException:
    try:
        temporary.unlink()
    except FileNotFoundError:
        pass
    raise
PY
	assert_private_state_file "$target"
}

assert_private_state_file() {
	local target="$1"
	[[ -f "$target" && ! -L "$target" ]] || die "Fichier d'état privé absent ou symbolique: ${target##*/}"
	[[ "$(stat -c '%a:%u:%h' "$target")" == "600:$(id -u):1" ]] ||
		die "Permissions, propriétaire ou hardlinks invalides: ${target##*/}"
}

assert_metadata_contract() {
	assert_private_state_file "$METADATA_FILE"
	python3 - "$METADATA_FILE" <<'PY'
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
expected = {
    "format", "deployment_id", "branch", "candidate_sha", "previous_sha",
    "sftp_release_sha", "sftp_image_id",
    "previous_database_revision", "canary_workspace_ids",
    "workspace_targets_sha256", "env_manifest_sha256", "release_a_attestation_sha256",
    "release_a_receipt_sha256", "release_a_manifest_sha256",
    "release_a_review_policy_sha256", "release_a_manifest_receipt_sha256", "created_at",
}
rows = {}
for raw in path.read_text(encoding="utf-8").splitlines():
    fields = raw.split("\t")
    if len(fields) != 2 or fields[0] in rows:
        raise SystemExit("deployment metadata is malformed or duplicated")
    rows[fields[0]] = fields[1]
if set(rows) != expected or rows["format"] != "5":
    raise SystemExit("deployment metadata schema differs")
if not re.fullmatch(r"[0-9a-f]{40}", rows["candidate_sha"]):
    raise SystemExit("deployment metadata candidate SHA is invalid")
if not re.fullmatch(r"[0-9a-f]{40}", rows["previous_sha"]):
    raise SystemExit("deployment metadata previous SHA is invalid")
if not re.fullmatch(r"[0-9a-f]{40}", rows["sftp_release_sha"]):
    raise SystemExit("deployment metadata SFTP SHA is invalid")
if not re.fullmatch(r"sha256:[0-9a-f]{64}", rows["sftp_image_id"]):
    raise SystemExit("deployment metadata SFTP image is invalid")
if not re.fullmatch(r"[0-9a-f]{64}", rows["env_manifest_sha256"]):
    raise SystemExit("deployment metadata environment digest is invalid")
if not re.fullmatch(r"[0-9a-f]{64}", rows["workspace_targets_sha256"]):
    raise SystemExit("deployment metadata workspace target digest is invalid")
if not re.fullmatch(r"[0-9a-f]{64}", rows["release_a_attestation_sha256"]):
    raise SystemExit("deployment metadata Release A attestation digest is invalid")
if not re.fullmatch(r"[0-9a-f]{64}", rows["release_a_receipt_sha256"]):
    raise SystemExit("deployment metadata Release A receipt digest is invalid")
for key in (
    "release_a_manifest_sha256",
    "release_a_review_policy_sha256",
    "release_a_manifest_receipt_sha256",
):
    if not re.fullmatch(r"[0-9a-f]{64}", rows[key]):
        raise SystemExit(f"deployment metadata Release A manifest gate digest is invalid: {key}")
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{5,95}", rows["deployment_id"]):
    raise SystemExit("deployment metadata id is invalid")
if not re.fullmatch(r"[A-Za-z0-9._/-]+", rows["branch"]) or ".." in rows["branch"]:
    raise SystemExit("deployment metadata branch is invalid")
if not re.fullmatch(r"[A-Za-z0-9_]+", rows["previous_database_revision"]):
    raise SystemExit("deployment metadata database revision is invalid")
workspace_ids = rows["canary_workspace_ids"].split(",")
uuid_pattern = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
if len(workspace_ids) != 4 or workspace_ids != sorted(set(workspace_ids)) or not all(
    uuid_pattern.fullmatch(value) for value in workspace_ids
):
    raise SystemExit("deployment metadata workspace inventory is invalid")
try:
    created = datetime.strptime(rows["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
except ValueError as exc:
    raise SystemExit("deployment metadata timestamp is invalid") from exc
if created.year < 2025:
    raise SystemExit("deployment metadata timestamp is implausible")
PY
}

assert_runtime_state_contract() {
	assert_private_state_file "$RUNTIME_STATE_FILE"
	python3 - "$RUNTIME_STATE_FILE" <<'PY'
import ipaddress
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
rows = [line.split("\t") for line in path.read_text(encoding="utf-8").splitlines()]
if not rows or rows.count(["format", "4"]) != 1:
    raise SystemExit("runtime state format is missing or duplicated")
services = {"agentium-livekit", "agentium-livekit-agent", "agentium-kc"}
states = {}
restart = {}
listeners = set()
systemd_state = []
systemd_unit_state = []
beat = []
for fields in rows:
    kind = fields[0] if fields else ""
    if kind == "format":
        if fields != ["format", "4"]:
            raise SystemExit("runtime state format row is malformed")
    elif kind == "worker_celery_beat":
        if len(fields) != 4 or fields[1] != "agentium-worker-cpu" or fields[2] not in {"0", "1"} or fields[3] != "-":
            raise SystemExit("worker scheduler capture is malformed")
        beat.append(tuple(fields))
    elif kind == "runtime_state":
        if len(fields) != 4 or fields[1] not in services or fields[1] in states:
            raise SystemExit("runtime state row is malformed or duplicated")
        if fields[2] not in {"running", "stopped", "absent"}:
            raise SystemExit("runtime state value is invalid")
        if fields[2] == "absent":
            if fields[3] != "-":
                raise SystemExit("absent runtime has an image")
        elif not re.fullmatch(r"sha256:[0-9a-f]{64}", fields[3]):
            raise SystemExit("runtime image identity is invalid")
        states[fields[1]] = (fields[2], fields[3])
    elif kind == "runtime_restart_policy":
        if len(fields) != 4 or fields[1] not in services or fields[1] in restart:
            raise SystemExit("runtime restart policy is malformed or duplicated")
        name, maximum = fields[2:]
        if name == "absent":
            if maximum != "-":
                raise SystemExit("absent runtime restart policy is malformed")
        elif name in {"no", "always", "unless-stopped"}:
            if maximum != "0":
                raise SystemExit("runtime restart maximum is inconsistent")
        elif name == "on-failure":
            if not maximum.isdigit():
                raise SystemExit("runtime restart maximum is invalid")
        else:
            raise SystemExit("runtime restart policy is invalid")
        restart[fields[1]] = (name, maximum)
    elif kind == "listener_binding":
        if len(fields) != 6 or fields[1] not in services or fields[2] not in {"tcp", "udp"}:
            raise SystemExit("runtime listener binding is malformed")
        try:
            ipaddress.ip_address(fields[3])
        except ValueError as exc:
            raise SystemExit("runtime listener address is invalid") from exc
        if not fields[4].isdigit() or not fields[5].isdigit():
            raise SystemExit("runtime listener port is invalid")
        ports = (int(fields[4]), int(fields[5]))
        if any(port < 1 or port > 65535 for port in ports):
            raise SystemExit("runtime listener port is out of range")
        key = tuple(fields[1:])
        if key in listeners:
            raise SystemExit("runtime listener binding is duplicated")
        listeners.add(key)
    elif kind == "systemd_state":
        if len(fields) != 4 or fields[1] != "agentium-backend.service" or fields[2] not in {"active", "stopped", "absent"} or fields[3] != "-":
            raise SystemExit("systemd runtime state is malformed")
        systemd_state.append(tuple(fields))
    elif kind == "systemd_unit_file_state":
        if len(fields) != 4 or fields[1] != "agentium-backend.service" or fields[2] not in {"enabled", "disabled"} or fields[3] != "-":
            raise SystemExit("systemd unit state is malformed")
        systemd_unit_state.append(tuple(fields))
    else:
        raise SystemExit("runtime state contains an unknown row")
if len(beat) != 1 or set(states) != services or set(restart) != services or len(systemd_state) != 1:
    raise SystemExit("runtime state inventory is incomplete")
for service in services:
    if (states[service][0] == "absent") != (restart[service][0] == "absent"):
        raise SystemExit("runtime state and restart policy disagree")
    if states[service][0] == "absent" and any(row[0] == service for row in listeners):
        raise SystemExit("absent runtime exposes a listener")
if systemd_state[0][2] == "absent":
    if systemd_unit_state:
        raise SystemExit("absent systemd unit has a unit-file state")
elif len(systemd_unit_state) != 1:
    raise SystemExit("systemd unit-file state is incomplete")
PY
}

assert_phase_contract() {
	assert_private_state_file "$PHASE_FILE"
	python3 - "$PHASE_FILE" <<'PY'
import sys
from pathlib import Path

allowed = {
    "preflight_ok", "prepared", "closing_intent", "closing",
    "maintenance_closed", "quiesced", "backfill_pending",
    "backfill_applying", "migrated", "activated", "validation_starting",
    "validation_pending", "opening_forward", "opened", "completed",
    "rollback_restoring", "rolled_back_restored", "rollback_opening",
    "rolled_back",
    "recovering_pre_migration", "rollback_closing",
}
raw = Path(sys.argv[1]).read_bytes()
if not raw.endswith(b"\n") or raw.count(b"\n") != 1:
    raise SystemExit("deployment phase must contain exactly one line")
try:
    value = raw[:-1].decode("ascii")
except UnicodeDecodeError as exc:
    raise SystemExit("deployment phase is not ASCII") from exc
if value not in allowed:
    raise SystemExit("deployment phase is unknown")
PY
}

assert_rollback_state_contract() {
	assert_private_state_file "$ROLLBACK_STATE"
	python3 - "$ROLLBACK_STATE" "$EXPECTED_SHA" "$(metadata previous_sha)" "$(metadata previous_database_revision)" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected_target, expected_previous, expected_revision = sys.argv[2:]
services = {
    "agentium-backend", "agentium-frontend", "agentium-worker-cpu",
    "agentium-sftp", "agentium-p4-maintenance",
}
singleton = {}
images = {}
states = {}
restart = {}
for raw in path.read_text(encoding="utf-8").splitlines():
    fields = raw.split("\t")
    if not fields:
        raise SystemExit("rollback state contains an empty row")
    kind = fields[0]
    if kind in {"format", "target_sha", "previous_sha", "database_revision"}:
        if len(fields) != 2 or kind in singleton:
            raise SystemExit("rollback singleton is malformed or duplicated")
        singleton[kind] = fields[1]
    elif kind == "service":
        if len(fields) != 5 or fields[1] not in services or fields[1] in images:
            raise SystemExit("rollback service is malformed or duplicated")
        service, image_id, image_ref, rollback_ref = fields[1:]
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) or not image_ref:
            raise SystemExit("rollback image identity is invalid")
        if rollback_ref != f"agentium-rollback/{service}:{expected_target}":
            raise SystemExit("rollback image tag is invalid")
        images[service] = image_id
    elif kind == "container_state":
        if len(fields) != 4 or fields[1] not in services or fields[1] in states:
            raise SystemExit("rollback container state is malformed or duplicated")
        service, state, revision = fields[1:]
        if state not in {"running", "stopped", "absent"}:
            raise SystemExit("rollback container state is invalid")
        if state == "absent":
            if revision != "-":
                raise SystemExit("absent rollback service has a revision")
        elif not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise SystemExit("rollback service revision is invalid")
        states[service] = (state, revision)
    elif kind == "restart_policy":
        if len(fields) != 4 or fields[1] not in services or fields[1] in restart:
            raise SystemExit("rollback restart policy is malformed or duplicated")
        service, name, maximum = fields[1:]
        if name == "absent":
            if maximum != "-":
                raise SystemExit("absent rollback restart policy is malformed")
        elif name in {"no", "always", "unless-stopped"}:
            if maximum != "0":
                raise SystemExit("rollback restart maximum is inconsistent")
        elif name == "on-failure":
            if not maximum.isdigit():
                raise SystemExit("rollback restart maximum is invalid")
        else:
            raise SystemExit("rollback restart policy is invalid")
        restart[service] = (name, maximum)
    else:
        raise SystemExit("rollback state contains an unknown row")
if singleton != {
    "format": "3", "target_sha": expected_target,
    "previous_sha": expected_previous, "database_revision": expected_revision,
}:
    raise SystemExit("rollback singleton contract differs")
if set(states) != services or set(restart) != services:
    raise SystemExit("rollback runtime inventory is incomplete")
for service in services:
    absent = states[service][0] == "absent"
    if absent != (restart[service][0] == "absent") or absent != (service not in images):
        raise SystemExit("rollback image, state and restart policy disagree")
    if service in {"agentium-backend", "agentium-frontend", "agentium-worker-cpu"}:
        if absent or states[service][1] != expected_previous:
            raise SystemExit("primary rollback service does not match previous SHA")
PY
}

durable_publish_file() {
	local temporary="$1" target="$2"
	[[ "$temporary" == "$DEPLOY_DIR"/.?* && "$target" == "$DEPLOY_DIR"/* ]] ||
		die "Publication durable hors répertoire de déploiement refusée"
	[[ -f "$temporary" && ! -L "$temporary" ]] || die "Fichier temporaire absent ou symbolique: $temporary"
	[[ ! -e "$target" && ! -L "$target" ]] || die "Cible d'état existe déjà: ${target##*/}"
	python3 - "$temporary" "$target" <<'PY'
import os
import sys
from pathlib import Path

temporary, target = map(Path, sys.argv[1:])
os.chmod(temporary, 0o600)
with temporary.open("rb") as handle:
    os.fsync(handle.fileno())
os.replace(temporary, target)
directory_fd = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PY
	assert_private_state_file "$target"
}

durable_replace_file() {
	local temporary="$1" target="$2"
	[[ "$temporary" == "$DEPLOY_DIR"/.?* && "$target" == "$DEPLOY_DIR"/* ]] ||
		die "Remplacement durable hors répertoire de déploiement refusé"
	[[ -f "$temporary" && ! -L "$temporary" ]] || die "Fichier temporaire absent ou symbolique: $temporary"
	if [[ -e "$target" || -L "$target" ]]; then
		assert_private_state_file "$target"
	fi
	python3 - "$temporary" "$target" <<'PY'
import os
import sys
from pathlib import Path

temporary, target = map(Path, sys.argv[1:])
os.chmod(temporary, 0o600)
with temporary.open("rb") as handle:
    os.fsync(handle.fileno())
os.replace(temporary, target)
directory_fd = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PY
	assert_private_state_file "$target"
}

assert_release_a_helper_trust_root() {
	local release_a_sha="$1" release_a_blob candidate_blob
	[[ "$release_a_sha" =~ ^[0-9a-f]{40}$ ]] || die "SHA trust root Release A invalide"
	release_a_blob="$(git -C "$REPO_DIR" rev-parse "${release_a_sha}:scripts/agentium_release_a_attestation.py" 2>/dev/null || true)"
	candidate_blob="$(git -C "$REPO_DIR" rev-parse "${EXPECTED_SHA}:scripts/agentium_release_a_attestation.py" 2>/dev/null || true)"
	[[ "$release_a_blob" =~ ^[0-9a-f]{40}$ ]] ||
		die "Le helper d'attestation manque dans la Release A active"
	[[ "$candidate_blob" =~ ^[0-9a-f]{40}$ && "$candidate_blob" == "$release_a_blob" ]] ||
		die "Le candidat a modifié son propre gate Release A; trust root refusée"
}

assert_release_a_manifest_helper_trust_root() {
	local release_a_sha="$1" release_a_blob candidate_blob path="scripts/agentium_release_a_manifest.py"
	[[ "$release_a_sha" =~ ^[0-9a-f]{40}$ ]] || die "SHA trust root manifeste Release A invalide"
	release_a_blob="$(git -C "$REPO_DIR" rev-parse "${release_a_sha}:${path}" 2>/dev/null || true)"
	candidate_blob="$(git -C "$REPO_DIR" rev-parse "${EXPECTED_SHA}:${path}" 2>/dev/null || true)"
	[[ "$release_a_blob" =~ ^[0-9a-f]{40}$ ]] || die "Le helper manifeste manque dans la Release A active"
	[[ "$candidate_blob" =~ ^[0-9a-f]{40}$ && "$candidate_blob" == "$release_a_blob" ]] ||
		die "La Release B a modifié le gate manifeste Release A; trust root refusée"
}

stage_release_a_manifest_helper() {
	local release_a_sha="$1" blob temporary path="scripts/agentium_release_a_manifest.py"
	assert_release_a_manifest_helper_trust_root "$release_a_sha"
	blob="$(git -C "$REPO_DIR" rev-parse "${release_a_sha}:${path}")"
	if [[ -f "$RELEASE_A_MANIFEST_HELPER" ]]; then
		[[ ! -L "$RELEASE_A_MANIFEST_HELPER" && "$(git -C "$REPO_DIR" hash-object "$RELEASE_A_MANIFEST_HELPER")" == "$blob" ]] ||
			die "Helper manifeste Release A figé altéré"
		chmod 0700 "$RELEASE_A_MANIFEST_HELPER"
		return
	fi
	temporary="$DEPLOY_DIR/.agentium_release_a_manifest.$$"
	(umask 077; git -C "$REPO_DIR" show "${release_a_sha}:${path}" >"$temporary")
	[[ "$(git -C "$REPO_DIR" hash-object "$temporary")" == "$blob" ]] ||
		die "Extraction du helper manifeste Release A altérée"
	chmod 0700 "$temporary"
	if ln "$temporary" "$RELEASE_A_MANIFEST_HELPER" 2>/dev/null; then
		rm -f "$temporary"
	else
		rm -f "$temporary"
		die "Helper manifeste Release A créé concurremment"
	fi
}

assert_sftp_helper_trust_root() {
	local release_a_sha="$1" release_a_blob candidate_blob path="backend/scripts/audit_sftp_deploy_boundary.py"
	[[ "$release_a_sha" =~ ^[0-9a-f]{40}$ ]] || die "SHA trust root SFTP Release A invalide"
	release_a_blob="$(git -C "$REPO_DIR" rev-parse "${release_a_sha}:${path}" 2>/dev/null || true)"
	candidate_blob="$(git -C "$REPO_DIR" rev-parse "${EXPECTED_SHA}:${path}" 2>/dev/null || true)"
	[[ "$release_a_blob" =~ ^[0-9a-f]{40}$ ]] || die "Le helper SFTP manque dans la Release A active"
	[[ "$candidate_blob" =~ ^[0-9a-f]{40}$ && "$candidate_blob" == "$release_a_blob" ]] ||
		die "La Release B a modifié le helper qui atteste le SFTP Release A épinglé"
}

live_sftp_release_sha() {
	local image_id revision
	image_id="$(docker inspect --format '{{.Image}}' agentium-sftp 2>/dev/null || true)"
	[[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || die "Image SFTP live absente ou invalide"
	revision="$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$image_id" 2>/dev/null || true)"
	[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || die "Révision OCI SFTP live absente"
	printf '%s\n' "$revision"
}

stage_release_a_helper() {
	local blob temporary
	blob="$(git -C "$REPO_DIR" rev-parse "${EXPECTED_SHA}:scripts/agentium_release_a_attestation.py" 2>/dev/null || true)"
	[[ "$blob" =~ ^[0-9a-f]{40}$ ]] || die "Helper d'attestation Release A absent du candidat"
	if [[ -f "$RELEASE_A_HELPER" ]]; then
		[[ ! -L "$RELEASE_A_HELPER" && "$(git -C "$REPO_DIR" hash-object "$RELEASE_A_HELPER")" == "$blob" ]] ||
			die "Helper d'attestation Release A figé altéré"
		chmod 0700 "$RELEASE_A_HELPER"
		return
	fi
	temporary="$DEPLOY_DIR/.agentium_release_a_attestation.$$"
	(umask 077; git -C "$REPO_DIR" show "${EXPECTED_SHA}:scripts/agentium_release_a_attestation.py" >"$temporary")
	[[ "$(git -C "$REPO_DIR" hash-object "$temporary")" == "$blob" ]] ||
		die "Extraction du helper d'attestation Release A altérée"
	chmod 0700 "$temporary"
	if ln "$temporary" "$RELEASE_A_HELPER" 2>/dev/null; then
		rm -f "$temporary"
	else
		rm -f "$temporary"
		die "Helper d'attestation Release A créé concurremment"
	fi
}

freeze_release_a_attestation() {
	local source="$1" expected_digest="$2" temporary="$DEPLOY_DIR/.release-a-attestation.$$"
	[[ ! -e "$FROZEN_RELEASE_A_ATTESTATION" && ! -L "$FROZEN_RELEASE_A_ATTESTATION" ]] ||
		die "Attestation Release A figée déjà présente"
	python3 - "$source" "$temporary" "$expected_digest" <<'PY'
import hashlib
import os
import stat
import sys
from pathlib import Path

source, target = map(Path, sys.argv[1:3])
expected = sys.argv[3]
flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
try:
    source_fd = os.open(source, flags)
except OSError as exc:
    raise SystemExit("Release A attestation source is unavailable or unsafe") from exc
try:
    before = os.fstat(source_fd)
    mode = stat.S_IMODE(before.st_mode)
    if not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid():
        raise SystemExit("Release A attestation source type or owner is unsafe")
    if before.st_nlink != 1 or mode not in {0o400, 0o600}:
        raise SystemExit("Release A attestation source links or permissions are unsafe")
    if before.st_size < 2 or before.st_size > 1024 * 1024:
        raise SystemExit("Release A attestation source size is unsafe")
    content = bytearray()
    while True:
        chunk = os.read(source_fd, min(65536, 1024 * 1024 + 1 - len(content)))
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > 1024 * 1024:
            raise SystemExit("Release A attestation source exceeds one MiB")
    after = os.fstat(source_fd)
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    if identity_before != identity_after or len(content) != before.st_size:
        raise SystemExit("Release A attestation source changed while being frozen")
finally:
    os.close(source_fd)
if hashlib.sha256(content).hexdigest() != expected:
    raise SystemExit("Release A attestation SHA-256 differs from the explicit operator digest")
target_fd = os.open(
    target,
    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    0o600,
)
try:
    with os.fdopen(target_fd, "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
except BaseException:
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    raise
PY
	durable_publish_file "$temporary" "$FROZEN_RELEASE_A_ATTESTATION"
}

freeze_release_a_manifest_artifact() {
	local source="$1" expected_digest="$2" target="$3" label="$4" temporary
	temporary="$DEPLOY_DIR/.${target##*/}.$$"
	[[ ! -e "$target" && ! -L "$target" ]] || die "$label figé déjà présent"
	python3 - "$source" "$temporary" "$expected_digest" "$REPO_DIR" "$label" <<'PY'
import hashlib
import os
import stat
import sys
from pathlib import Path

source, target = map(Path, sys.argv[1:3])
expected, repository, label = sys.argv[3:]
try:
    resolved_source = source.resolve(strict=True)
    resolved_repository = Path(repository).resolve(strict=True)
except OSError as exc:
    raise SystemExit(f"{label} source or repository is unavailable") from exc
if resolved_source == resolved_repository or resolved_repository in resolved_source.parents:
    raise SystemExit(f"{label} must live outside the candidate Git worktree")
flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
try:
    source_fd = os.open(source, flags)
except OSError as exc:
    raise SystemExit(f"{label} source is unavailable or unsafe") from exc
try:
    before = os.fstat(source_fd)
    mode = stat.S_IMODE(before.st_mode)
    if not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid():
        raise SystemExit(f"{label} source type or owner is unsafe")
    if before.st_nlink != 1 or mode not in {0o400, 0o600}:
        raise SystemExit(f"{label} source links or permissions are unsafe")
    if before.st_size < 2 or before.st_size > 256 * 1024:
        raise SystemExit(f"{label} source size is unsafe")
    content = bytearray()
    while True:
        chunk = os.read(source_fd, min(65536, 256 * 1024 + 1 - len(content)))
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > 256 * 1024:
            raise SystemExit(f"{label} source exceeds 256 KiB")
    after = os.fstat(source_fd)
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if identity_before != identity_after or len(content) != before.st_size:
        raise SystemExit(f"{label} source changed while being frozen")
finally:
    os.close(source_fd)
if hashlib.sha256(content).hexdigest() != expected:
    raise SystemExit(f"{label} SHA-256 differs from the explicit operator digest")
target_fd = os.open(
    target,
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0),
    0o600,
)
try:
    with os.fdopen(target_fd, "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
except BaseException:
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    raise
PY
	durable_publish_file "$temporary" "$target"
}

assert_release_a_manifest_receipt_contract() {
	local expected_release_sha="$1" expected_manifest_file_digest="$2" expected_review_file_digest="$3" expected_receipt_digest="${4:-}"
	local actual_manifest_digest actual_review_digest actual_receipt_digest
	assert_private_state_file "$FROZEN_RELEASE_A_MANIFEST"
	assert_private_state_file "$FROZEN_RELEASE_A_REVIEW_POLICY"
	assert_private_state_file "$RELEASE_A_MANIFEST_RECEIPT"
	actual_manifest_digest="$(sha256sum "$FROZEN_RELEASE_A_MANIFEST" | awk '{print $1}')"
	actual_review_digest="$(sha256sum "$FROZEN_RELEASE_A_REVIEW_POLICY" | awk '{print $1}')"
	actual_receipt_digest="$(sha256sum "$RELEASE_A_MANIFEST_RECEIPT" | awk '{print $1}')"
	[[ "$actual_manifest_digest" == "$expected_manifest_file_digest" ]] ||
		die "Manifeste Release A figé différent du digest transactionnel"
	[[ "$actual_review_digest" == "$expected_review_file_digest" ]] ||
		die "Revue Release A figée différente du digest transactionnel"
	[[ -z "$expected_receipt_digest" || "$actual_receipt_digest" == "$expected_receipt_digest" ]] ||
		die "Reçu manifeste Release A différent du digest transactionnel"
	python3 - "$FROZEN_RELEASE_A_MANIFEST" "$FROZEN_RELEASE_A_REVIEW_POLICY" "$RELEASE_A_MANIFEST_RECEIPT" "$expected_release_sha" <<'PY'
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

manifest_path, review_path, receipt_path, expected_sha = sys.argv[1:]
try:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    review = json.loads(Path(review_path).read_text(encoding="utf-8"))
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise SystemExit("Release A manifest gate contains invalid JSON") from exc
receipt_keys = {
    "profile", "result", "base_sha", "release_a_sha", "manifest_sha256",
    "review_policy_sha256", "verified_at",
}
if not isinstance(receipt, dict) or set(receipt) != receipt_keys:
    raise SystemExit("Release A manifest receipt schema differs")
if receipt.get("profile") != "agentium-release-a-diff-verification-v6" or receipt.get("result") != "passed":
    raise SystemExit("Release A manifest receipt did not pass")
if not isinstance(manifest, dict) or manifest.get("profile") != "agentium-release-a-diff-manifest-v6":
    raise SystemExit("Release A manifest identity differs")
if not isinstance(review, dict) or review.get("profile") != "agentium-release-a-semantic-review-v1":
    raise SystemExit("Release A review identity differs")
if review.get("approval") != "approved":
    raise SystemExit("Release A semantic review is not approved")
if manifest.get("release_a_sha") != expected_sha or review.get("release_a_sha") != expected_sha:
    raise SystemExit("Release A manifest/review SHA differs from the active Release A")
if receipt.get("release_a_sha") != expected_sha:
    raise SystemExit("Release A manifest receipt SHA differs")
for key, value in {
    "manifest.manifest_sha256": manifest.get("manifest_sha256"),
    "review.review_sha256": review.get("review_sha256"),
    "receipt.manifest_sha256": receipt.get("manifest_sha256"),
    "receipt.review_policy_sha256": receipt.get("review_policy_sha256"),
}.items():
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise SystemExit(f"Release A manifest gate digest is invalid: {key}")
if receipt["manifest_sha256"] != manifest["manifest_sha256"]:
    raise SystemExit("Release A receipt is not bound to the manifest")
if receipt["review_policy_sha256"] != review["review_sha256"]:
    raise SystemExit("Release A receipt is not bound to the semantic review")
verified_at = receipt.get("verified_at")
if not isinstance(verified_at, str):
    raise SystemExit("Release A manifest receipt timestamp is invalid")
try:
    datetime.strptime(verified_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
except ValueError as exc:
    raise SystemExit("Release A manifest receipt timestamp is invalid") from exc
PY
}

run_release_a_manifest_verification() {
	local release_a_sha="$1" output="$2"
	rm -f "$output"
	if ! "$RELEASE_A_MANIFEST_HELPER" verify \
		--repository "$REPO_DIR" \
		--release-a-sha "$release_a_sha" \
		--review-policy "$FROZEN_RELEASE_A_REVIEW_POLICY" \
		--manifest "$FROZEN_RELEASE_A_MANIFEST" >"$output"; then
		rm -f "$output"
		die "Manifeste ou revue sémantique Release A refusé"
	fi
	chmod 0600 "$output"
}

assert_release_a_manifest_reverification() {
	local release_a_sha="$1" temporary="$DEPLOY_DIR/.release-a-manifest-reverification.$$"
	run_release_a_manifest_verification "$release_a_sha" "$temporary"
	if ! python3 - "$RELEASE_A_MANIFEST_RECEIPT" "$temporary" <<'PY'
import json
import sys
from pathlib import Path

frozen_path, current_path = map(Path, sys.argv[1:])
try:
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    current = json.loads(current_path.read_text(encoding="utf-8"))
except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise SystemExit("Release A manifest re-verification receipt is invalid") from exc
stable_keys = {
    "profile", "result", "base_sha", "release_a_sha", "manifest_sha256",
    "review_policy_sha256",
}
if {key: frozen.get(key) for key in stable_keys} != {key: current.get(key) for key in stable_keys}:
    raise SystemExit("Release A manifest re-verification differs from the frozen receipt")
PY
	then
		rm -f "$temporary"
		die "Revalidation du manifeste Release A différente du reçu figé"
	fi
	rm -f "$temporary"
}

ensure_release_a_manifest_gate() {
	local current_sha receipt_temporary
	if [[ -e "$METADATA_FILE" || -L "$METADATA_FILE" ]]; then
		assert_recorded_release_a_manifest_gate
		return
	fi
	[[ -n "$RELEASE_A_MANIFEST" && -n "$RELEASE_A_MANIFEST_SHA256" && -n "$RELEASE_A_REVIEW_POLICY" && -n "$RELEASE_A_REVIEW_POLICY_SHA256" ]] ||
		die "Premier preflight: manifeste, revue Release A et leurs SHA-256 explicites sont obligatoires"
	current_sha="$(active_application_sha)"
	[[ "$(git -C "$REPO_DIR" rev-parse HEAD)" == "$current_sha" ]] ||
		die "Gate manifeste Release A refusé: checkout et runtime actifs divergent"
	[[ "$current_sha" != "$EXPECTED_SHA" ]] || die "La Release B doit être distincte de la Release A"
	git -C "$REPO_DIR" merge-base --is-ancestor "$current_sha" "$EXPECTED_SHA" ||
		die "La Release B n'est pas descendante de la Release A active"
	stage_release_a_manifest_helper "$current_sha"
	if [[ ! -e "$FROZEN_RELEASE_A_MANIFEST" && ! -L "$FROZEN_RELEASE_A_MANIFEST" ]]; then
		freeze_release_a_manifest_artifact "$RELEASE_A_MANIFEST" "$RELEASE_A_MANIFEST_SHA256" "$FROZEN_RELEASE_A_MANIFEST" "Manifeste Release A"
	else
		assert_private_state_file "$FROZEN_RELEASE_A_MANIFEST"
		[[ "$(sha256sum "$FROZEN_RELEASE_A_MANIFEST" | awk '{print $1}')" == "$RELEASE_A_MANIFEST_SHA256" ]] ||
			die "Manifeste Release A déjà figé avec un autre digest"
	fi
	if [[ ! -e "$FROZEN_RELEASE_A_REVIEW_POLICY" && ! -L "$FROZEN_RELEASE_A_REVIEW_POLICY" ]]; then
		freeze_release_a_manifest_artifact "$RELEASE_A_REVIEW_POLICY" "$RELEASE_A_REVIEW_POLICY_SHA256" "$FROZEN_RELEASE_A_REVIEW_POLICY" "Revue sémantique Release A"
	else
		assert_private_state_file "$FROZEN_RELEASE_A_REVIEW_POLICY"
		[[ "$(sha256sum "$FROZEN_RELEASE_A_REVIEW_POLICY" | awk '{print $1}')" == "$RELEASE_A_REVIEW_POLICY_SHA256" ]] ||
			die "Revue Release A déjà figée avec un autre digest"
	fi
	receipt_temporary="$DEPLOY_DIR/.release-a-manifest-verification-receipt.$$"
	run_release_a_manifest_verification "$current_sha" "$receipt_temporary"
	if [[ -e "$RELEASE_A_MANIFEST_RECEIPT" || -L "$RELEASE_A_MANIFEST_RECEIPT" ]]; then
		durable_replace_file "$receipt_temporary" "$RELEASE_A_MANIFEST_RECEIPT"
	else
		durable_publish_file "$receipt_temporary" "$RELEASE_A_MANIFEST_RECEIPT"
	fi
	assert_release_a_manifest_receipt_contract "$current_sha" "$RELEASE_A_MANIFEST_SHA256" "$RELEASE_A_REVIEW_POLICY_SHA256"
}

assert_recorded_release_a_manifest_gate() {
	local release_a_sha manifest_digest review_digest receipt_digest helper_blob
	assert_metadata_contract
	release_a_sha="$(metadata previous_sha)"
	manifest_digest="$(metadata release_a_manifest_sha256)"
	review_digest="$(metadata release_a_review_policy_sha256)"
	receipt_digest="$(metadata release_a_manifest_receipt_sha256)"
	stage_release_a_manifest_helper "$release_a_sha"
	helper_blob="$(git -C "$REPO_DIR" rev-parse "${release_a_sha}:scripts/agentium_release_a_manifest.py")"
	[[ "$(git -C "$REPO_DIR" hash-object "$RELEASE_A_MANIFEST_HELPER")" == "$helper_blob" ]] ||
		die "Helper manifeste Release A figé divergent"
	assert_release_a_manifest_receipt_contract "$release_a_sha" "$manifest_digest" "$review_digest" "$receipt_digest"
	assert_release_a_manifest_reverification "$release_a_sha"
}

assert_release_a_receipt_contract() {
	local expected_release_sha="$1" expected_sftp_sha="$2" expected_attestation_digest="$3" expected_receipt_digest="${4:-}"
	local freshness="${5:-recorded}"
	local actual_attestation_digest actual_receipt_digest runtime_hostname
	[[ "$freshness" == "recorded" || "$freshness" == "fresh" ]] || die "Mode freshness Release A invalide"
	assert_private_state_file "$FROZEN_RELEASE_A_ATTESTATION"
	assert_private_state_file "$RELEASE_A_RECEIPT"
	actual_attestation_digest="$(sha256sum "$FROZEN_RELEASE_A_ATTESTATION" | awk '{print $1}')"
	actual_receipt_digest="$(sha256sum "$RELEASE_A_RECEIPT" | awk '{print $1}')"
	[[ "$actual_attestation_digest" == "$expected_attestation_digest" ]] ||
		die "Attestation Release A figée différente du digest transactionnel"
	[[ -z "$expected_receipt_digest" || "$actual_receipt_digest" == "$expected_receipt_digest" ]] ||
		die "Reçu Release A différent du digest transactionnel"
	runtime_hostname="$(hostname -f)"
	[[ -n "$runtime_hostname" && "$runtime_hostname" != *$'\n'* ]] || die "Hostname runtime Release A invalide"
	python3 - "$RELEASE_A_RECEIPT" "$expected_release_sha" "$expected_sftp_sha" "$expected_attestation_digest" "$runtime_hostname" "$freshness" <<'PY'
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

path, expected_sha, expected_sftp_sha, expected_attestation, hostname, freshness = sys.argv[1:]
def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result
try:
    payload = json.loads(
        Path(path).read_text(encoding="utf-8"), object_pairs_hook=no_duplicates
    )
except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
    raise SystemExit("Release A receipt is not valid JSON") from exc
expected_keys = {
    "schema_version", "kind", "result", "environment", "release_a_sha", "sftp_release_sha",
    "hostname_sha256", "attestation_sha256", "evidence_sha256",
    "verified_at", "fresh_until",
}
if not isinstance(payload, dict) or set(payload) != expected_keys:
    raise SystemExit("Release A receipt schema differs")
if payload.get("schema_version") != 4 or payload.get("kind") != "agentium-release-a-verification-receipt":
    raise SystemExit("Release A receipt identity differs")
if payload.get("result") != "passed" or payload.get("environment") != "production":
    raise SystemExit("Release A receipt did not pass for production")
if payload.get("release_a_sha") != expected_sha or payload.get("sftp_release_sha") != expected_sftp_sha or payload.get("attestation_sha256") != expected_attestation:
    raise SystemExit("Release A receipt is not bound to this transaction")
hostname_digest = hashlib.sha256(hostname.encode("utf-8")).hexdigest()
if payload.get("hostname_sha256") != hostname_digest:
    raise SystemExit("Release A receipt hostname differs from this runtime")
for key in ("hostname_sha256", "attestation_sha256", "evidence_sha256"):
    if not isinstance(payload.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", payload[key]):
        raise SystemExit(f"Release A receipt {key} is invalid")
times = []
for key in ("verified_at", "fresh_until"):
    value = payload.get(key)
    if not isinstance(value, str) or not value.endswith("Z"):
        raise SystemExit(f"Release A receipt {key} is invalid")
    try:
        times.append(datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc))
    except ValueError as exc:
        raise SystemExit(f"Release A receipt {key} is invalid") from exc
if times[1] <= times[0]:
    raise SystemExit("Release A receipt freshness interval is invalid")
if freshness == "fresh" and datetime.now(timezone.utc) > times[1]:
    raise SystemExit("Release A receipt is no longer fresh; use a new deployment-id")
PY
}

assert_completed_release_a_transaction() {
	local expected_release_sha="$1" engine_id runtime_hostname
	engine_id="$(docker info --format '{{.ID}}')"
	[[ "$engine_id" =~ ^[A-Za-z0-9:_-]{8,128}$ ]] || die "Engine ID Docker local non attestable"
	runtime_hostname="$(hostname -f)"
	[[ -n "$runtime_hostname" && "$runtime_hostname" != *$'\n'* ]] || die "Hostname runtime Release A invalide"
	python3 -I - /srv/agentium-data/release-a-deployments "$expected_release_sha" "$engine_id" "$REPO_DIR" "$runtime_hostname" verify-live <<'PY'
import hashlib,json,os,re,stat,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
root=Path(sys.argv[1]); expected_sha=sys.argv[2]; engine_id=sys.argv[3]; repository=Path(sys.argv[4]); hostname=sys.argv[5]; verify_live=len(sys.argv)>6 and sys.argv[6]=="verify-live"; uid=os.geteuid()
sha256=re.compile(r"[0-9a-f]{64}\Z"); git_sha=re.compile(r"[0-9a-f]{40}\Z")
def directory(path,mode=0o700):
    row=path.lstat()
    if stat.S_ISLNK(row.st_mode) or not stat.S_ISDIR(row.st_mode) or row.st_uid!=uid or stat.S_IMODE(row.st_mode)!=mode or row.st_nlink<2:
        raise SystemExit(f"unsafe Release A directory: {path.name}")
    return row
def owned_bytes(path,modes,maximum=2*1024*1024):
    before=path.lstat()
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode) or before.st_uid!=uid or stat.S_IMODE(before.st_mode) not in modes or before.st_nlink!=1 or not 0<before.st_size<=maximum:
        raise SystemExit(f"unsafe Release A artifact: {path.name}")
    fd=os.open(path,os.O_RDONLY|getattr(os,"O_CLOEXEC",0)|getattr(os,"O_NOFOLLOW",0))
    try:
        opened=os.fstat(fd)
        if (opened.st_dev,opened.st_ino)!=(before.st_dev,before.st_ino): raise SystemExit("Release A artifact changed while opening")
        chunks=[]
        while True:
            chunk=os.read(fd,65536)
            if not chunk: break
            chunks.append(chunk)
            if sum(map(len,chunks))>maximum: raise SystemExit("Release A artifact exceeds bound")
        after=os.fstat(fd)
        if (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)!=(opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns): raise SystemExit("Release A artifact changed while reading")
        return b"".join(chunks)
    finally: os.close(fd)
def private_bytes(path,maximum=2*1024*1024):
    return owned_bytes(path,{0o600},maximum)
def executable_bytes(path,maximum=2*1024*1024):
    return owned_bytes(path,{0o700},maximum)
def strict_json(body,label):
    def no_duplicates(pairs):
        result={}
        for key,value in pairs:
            if key in result: raise ValueError(f"duplicate JSON key: {key}")
            result[key]=value
        return result
    try: value=json.loads(body,object_pairs_hook=no_duplicates)
    except (UnicodeDecodeError,json.JSONDecodeError,ValueError) as exc: raise SystemExit(f"invalid Release A JSON: {label}") from exc
    if not isinstance(value,dict): raise SystemExit(f"invalid Release A object: {label}")
    return value
def private_json(path):
    return strict_json(private_bytes(path),path.name)
def tsv(path):
    rows={}
    for raw in private_bytes(path).decode("utf-8").splitlines():
        fields=raw.split("\t")
        if len(fields)!=2 or fields[0] in rows: raise SystemExit("invalid Release A metadata")
        rows[fields[0]]=fields[1]
    return rows
def git_blob(path):
    try:
        process=subprocess.run(["git","-C",str(repository),"cat-file","blob",f"{expected_sha}:{path}"],check=True,capture_output=True,timeout=30)
    except (OSError,subprocess.CalledProcessError,subprocess.TimeoutExpired) as exc:
        raise SystemExit(f"cannot read trusted Release A Git blob: {path}") from exc
    if not process.stdout: raise SystemExit(f"empty trusted Release A Git blob: {path}")
    return process.stdout
if not git_sha.fullmatch(expected_sha): raise SystemExit("invalid expected Release A SHA")
if not repository.is_absolute(): raise SystemExit("Release A repository path is not absolute")
root_row=directory(root)
data_row=root.parent.lstat()
if root_row.st_dev!=data_row.st_dev: raise SystemExit("Release A journal is not on /dev/sdb")
matches=[]; matched_runtime=None; matched_runtime_ready=None; matched_sftp_restart=None; matched_keycloak_contract=None; matched_keycloak_restart=None; matched_path=None; matched_metadata=None; matched_snapshots=None; matched_executables=None
for entry in os.scandir(root):
    if entry.name.startswith("."): continue
    path=root/entry.name
    row=path.lstat()
    if stat.S_ISLNK(row.st_mode): raise SystemExit("Release A journal contains a symlink")
    if not stat.S_ISDIR(row.st_mode): continue
    directory(path)
    metadata_path=path/"metadata.tsv"
    if not metadata_path.exists(): continue
    metadata=tsv(metadata_path)
    if metadata.get("release_a_sha")!=expected_sha: continue
    metadata_keys={"format","deployment_id","branch","live_sha","release_a_sha","candidate_sha","sftp_release_sha","sftp_image_id","docker_engine_id","env_manifest_sha256","manifest_sha256","review_policy_sha256","preconditions_sha256","evidence_authority_keyring_sha256","manifest_receipt_sha256","preconditions_receipt_sha256","preconditions_evidence_receipt_sha256","created_at"}
    if set(metadata)!=metadata_keys or metadata.get("format")!="2" or metadata.get("candidate_sha")!=expected_sha or metadata.get("branch")!="demo/agentic" or metadata.get("deployment_id")!=entry.name:
        raise SystemExit("matching Release A metadata identity differs")
    if metadata.get("docker_engine_id")!=engine_id: raise SystemExit("Release A completed on another Docker engine")
    if git_sha.fullmatch(str(metadata.get("live_sha",""))) is None or git_sha.fullmatch(str(metadata.get("sftp_release_sha",""))) is None or re.fullmatch(r"sha256:[0-9a-f]{64}",str(metadata.get("sftp_image_id",""))) is None:
        raise SystemExit("matching Release A metadata runtime identity differs")
    for key in ("env_manifest_sha256","manifest_sha256","review_policy_sha256","preconditions_sha256","evidence_authority_keyring_sha256","manifest_receipt_sha256","preconditions_receipt_sha256","preconditions_evidence_receipt_sha256"):
        if sha256.fullmatch(str(metadata.get(key,""))) is None: raise SystemExit(f"matching Release A metadata digest differs: {key}")
    sftp_invalidation_path=path/"sftp-runtime-identity-invalidation.json"
    if sftp_invalidation_path.exists() or sftp_invalidation_path.is_symlink():
        raise SystemExit("matching Release A SFTP runtime identity was invalidated")
    if private_bytes(path/"phase").decode("ascii").strip()!="completed": continue
    trusted_programs={
      "agentium_release_a_evidence_bundle.py":"scripts/agentium_release_a_evidence_bundle.py",
      "agentium_release_a_attestation.py":"scripts/agentium_release_a_attestation.py",
      "agentium_release_a_preconditions.py":"scripts/agentium_release_a_preconditions.py",
      "agentium_release_a_sftp_positive_canary.py":"scripts/agentium_release_a_sftp_positive_canary.py",
    }
    snapshots={}
    for name,source in trusted_programs.items():
        body=executable_bytes(path/name)
        if body!=git_blob(source): raise SystemExit(f"versioned Release A helper differs: {name}")
        snapshots[path/name]=body
    keyring_path=path/"release-a-evidence-authority-keyring.json"
    keyring_body=private_bytes(keyring_path)
    if keyring_body!=git_blob("config/agentium/release-a-evidence-authorities.v1.json"):
        raise SystemExit("versioned Release A authority keyring differs")
    keyring_digest=hashlib.sha256(keyring_body).hexdigest()
    if keyring_digest!=metadata.get("evidence_authority_keyring_sha256"):
        raise SystemExit("Release A metadata authority keyring binding differs")
    snapshots[keyring_path]=keyring_body
    runtime_state_path=path/"runtime-state.tsv"
    runtime_state_body=private_bytes(runtime_state_path)
    try: runtime_state_lines=runtime_state_body.decode("ascii").splitlines()
    except UnicodeDecodeError as exc: raise SystemExit("Release A runtime state is not ASCII") from exc
    if not runtime_state_lines or runtime_state_lines[0]!="format\t1" or any(not row or "\0" in row for row in runtime_state_lines):
        raise SystemExit("Release A runtime state schema differs")
    sftp_runtime_rows=[]; keycloak_runtime_rows=[]; keycloak_contract_rows=[]
    for raw in runtime_state_lines[1:]:
        fields=raw.split("\t")
        if len(fields)>=2 and fields[0]=="container" and fields[1]=="agentium-sftp":
            sftp_runtime_rows.append(fields)
        if len(fields)>=2 and fields[0]=="container" and fields[1]=="agentium-kc":
            keycloak_runtime_rows.append(fields)
        if len(fields)>=2 and fields[0]=="keycloak_contract" and fields[1]=="agentium-kc":
            keycloak_contract_rows.append(fields)
    if len(sftp_runtime_rows)!=1:
        raise SystemExit("Release A historical SFTP runtime state cardinality differs")
    sftp_runtime_row=sftp_runtime_rows[0]
    if len(sftp_runtime_row)!=6 or sftp_runtime_row[2]!="true" or sftp_runtime_row[3]!=metadata["sftp_image_id"] or sftp_runtime_row[4] not in {"no","always","unless-stopped","on-failure"} or not sftp_runtime_row[5].isdigit() or (sftp_runtime_row[4]!="on-failure" and sftp_runtime_row[5]!="0"):
        raise SystemExit("Release A historical SFTP restart policy differs")
    historical_sftp_restart=(sftp_runtime_row[4],int(sftp_runtime_row[5]))
    if len(keycloak_runtime_rows)!=1 or len(keycloak_contract_rows)!=1:
        raise SystemExit("Release A historical Keycloak runtime state cardinality differs")
    keycloak_runtime_row=keycloak_runtime_rows[0]; keycloak_contract_row=keycloak_contract_rows[0]
    if len(keycloak_runtime_row)!=6 or keycloak_runtime_row[2]!="true" or keycloak_runtime_row[4] not in {"no","always","unless-stopped","on-failure"} or not keycloak_runtime_row[5].isdigit() or (keycloak_runtime_row[4]!="on-failure" and keycloak_runtime_row[5]!="0"):
        raise SystemExit("Release A historical Keycloak restart policy differs")
    if len(keycloak_contract_row)!=6 or re.fullmatch(r"[0-9a-f]{64}",keycloak_contract_row[2]) is None or re.fullmatch(r"sha256:[0-9a-f]{64}",keycloak_contract_row[3]) is None or sha256.fullmatch(keycloak_contract_row[4]) is None or not keycloak_contract_row[5].isdigit() or not 1<=int(keycloak_contract_row[5])<=65535 or keycloak_runtime_row[3]!=keycloak_contract_row[3]:
        raise SystemExit("Release A historical Keycloak control-plane contract differs")
    historical_keycloak_contract={"container_id":keycloak_contract_row[2],"image_id":keycloak_contract_row[3],"contract_sha256":keycloak_contract_row[4],"host_port":int(keycloak_contract_row[5])}
    historical_keycloak_restart=(keycloak_runtime_row[4],int(keycloak_runtime_row[5]))
    snapshots[runtime_state_path]=runtime_state_body
    completion_path=path/"release-a-transaction-receipt.json"
    completion_body=private_bytes(completion_path)
    completion=strict_json(completion_body,"completion receipt")
    expected_keys={"schema_version","kind","result","deployment_id","release_a_sha","release_a_attestation_receipt_sha256","final_evidence_receipt_sha256","manifest_receipt_sha256","preconditions_receipt_sha256","preconditions_evidence_receipt_sha256","runtime_oci_receipt_sha256","sftp_runtime_ready_receipt_sha256","sftp_postgres_ledger_receipt_sha256","completed_at"}
    if not isinstance(completion,dict) or set(completion)!=expected_keys or completion.get("schema_version")!=3 or completion.get("kind")!="agentium-release-a-transaction-receipt" or completion.get("result")!="passed" or completion.get("deployment_id")!=entry.name or completion.get("release_a_sha")!=expected_sha:
        raise SystemExit("Release A completion receipt differs")
    bindings={
      "release_a_attestation_receipt_sha256":"release-a-verification-receipt.json",
      "final_evidence_receipt_sha256":"release-a-final-evidence-receipt.json",
      "manifest_receipt_sha256":"release-a-manifest-verification-receipt.json",
      "preconditions_receipt_sha256":"release-a-preconditions-receipt.json",
      "preconditions_evidence_receipt_sha256":"release-a-preconditions-evidence-receipt.json",
      "runtime_oci_receipt_sha256":"release-a-runtime-oci-receipt.json",
      "sftp_runtime_ready_receipt_sha256":"sftp-validation-runtime-ready.json",
      "sftp_postgres_ledger_receipt_sha256":"sftp-postgres-ledger-receipt.json",
    }
    bound={}
    for key,name in bindings.items():
        body=private_bytes(path/name); digest=hashlib.sha256(body).hexdigest()
        if completion.get(key)!=digest or sha256.fullmatch(digest) is None: raise SystemExit(f"Release A completion binding differs: {name}")
        bound[name]=strict_json(body,name)
        snapshots[path/name]=body
    def utc_stamp(owner,key,label):
        value=owner.get(key) if isinstance(owner,dict) else None
        if not isinstance(value,str) or not value.endswith("Z"): raise SystemExit(f"Release A {label} timestamp differs: {key}")
        try: parsed=datetime.fromisoformat(value.removesuffix("Z")+"+00:00")
        except ValueError as exc: raise SystemExit(f"Release A {label} timestamp differs: {key}") from exc
        if parsed.tzinfo is None: raise SystemExit(f"Release A {label} timestamp differs: {key}")
        return parsed
    hostname_digest=hashlib.sha256(hostname.encode("utf-8")).hexdigest()
    attestation_path=path/"release-a-attestation.json"
    attestation_body=private_bytes(attestation_path)
    snapshots[attestation_path]=attestation_body
    attestation_receipt=bound["release-a-verification-receipt.json"]
    attestation_receipt_keys={"schema_version","kind","result","environment","release_a_sha","sftp_release_sha","hostname_sha256","attestation_sha256","evidence_sha256","verified_at","fresh_until"}
    if not isinstance(attestation_receipt,dict) or set(attestation_receipt)!=attestation_receipt_keys or attestation_receipt.get("schema_version")!=4 or attestation_receipt.get("kind")!="agentium-release-a-verification-receipt" or attestation_receipt.get("result")!="passed" or attestation_receipt.get("environment")!="production":
        raise SystemExit("Release A attestation receipt schema differs")
    if attestation_receipt.get("release_a_sha")!=expected_sha or attestation_receipt.get("sftp_release_sha")!=metadata["sftp_release_sha"] or attestation_receipt.get("hostname_sha256")!=hostname_digest or attestation_receipt.get("attestation_sha256")!=hashlib.sha256(attestation_body).hexdigest():
        raise SystemExit("Release A attestation receipt binding differs")
    for key in ("hostname_sha256","attestation_sha256","evidence_sha256"):
        if sha256.fullmatch(str(attestation_receipt.get(key,""))) is None: raise SystemExit(f"Release A attestation receipt digest differs: {key}")
    attestation_at=utc_stamp(attestation_receipt,"verified_at","attestation receipt")
    if utc_stamp(attestation_receipt,"fresh_until","attestation receipt")<=attestation_at:
        raise SystemExit("Release A attestation receipt freshness differs")

    runtime_ready=bound["sftp-validation-runtime-ready.json"]
    runtime_ready_keys={"schema_version","kind","result","live_sha","deployment_id","release_a_sha","sftp_sha","hostname_sha256","sftp_container_id","sftp_image_id","image_revision","sftp_port","sftp_started_at","runtime_identity_sha256","host_key_fingerprint","state","health_status","ingress_closed","restart_disabled","restart_policy_disabled","secure_deposit_mode","secure_deposit_source","external_established_connection_count","ready_at","ingress_gate","published_transport","secure_deposit","host_key","credentials_used","authentication_attempted","sftp_subsystem_requested","content_serialized","raw_network_data_serialized","raw_identification_serialized"}
    if not isinstance(runtime_ready,dict) or set(runtime_ready)!=runtime_ready_keys or runtime_ready.get("schema_version")!=1 or runtime_ready.get("kind")!="agentium-release-a-sftp-runtime-ready" or runtime_ready.get("result")!="passed":
        raise SystemExit("Release A SFTP runtime-ready receipt schema differs")
    if runtime_ready.get("live_sha")!=metadata["live_sha"] or runtime_ready.get("release_a_sha")!=expected_sha or runtime_ready.get("sftp_sha")!=metadata["sftp_release_sha"] or runtime_ready.get("deployment_id")!=entry.name or runtime_ready.get("hostname_sha256")!=hostname_digest or runtime_ready.get("sftp_image_id")!=metadata["sftp_image_id"] or runtime_ready.get("image_revision")!=metadata["sftp_release_sha"]:
        raise SystemExit("Release A SFTP runtime-ready receipt identity differs")
    if re.fullmatch(r"[0-9a-f]{64}",str(runtime_ready.get("sftp_container_id",""))) is None or re.fullmatch(r"sha256:[0-9a-f]{64}",str(runtime_ready.get("sftp_image_id",""))) is None or isinstance(runtime_ready.get("sftp_port"),bool) or not isinstance(runtime_ready.get("sftp_port"),int) or not 1<=runtime_ready["sftp_port"]<=65535:
        raise SystemExit("Release A SFTP runtime-ready runtime identity is invalid")
    fixed_ready={"state":"running","health_status":"healthy","ingress_closed":True,"restart_disabled":True,"restart_policy_disabled":True,"secure_deposit_mode":"ro","secure_deposit_source":"/dev/sdc","external_established_connection_count":0,"credentials_used":False,"authentication_attempted":False,"sftp_subsystem_requested":False,"content_serialized":False,"raw_network_data_serialized":False,"raw_identification_serialized":False}
    if any(runtime_ready.get(key)!=value for key,value in fixed_ready.items()):
        raise SystemExit("Release A SFTP runtime-ready safety state differs")
    expected_gate={"ipv4_input":True,"ipv4_docker_user":True,"ipv6_input":True,"ipv6_docker_user":True}
    if runtime_ready.get("ingress_gate")!=expected_gate:
        raise SystemExit("Release A SFTP runtime-ready ingress gate differs")
    transport=runtime_ready.get("published_transport")
    transport_keys={"protocol","container_port","host_port","binding_count","binding_sha256","listener_count","established_connection_count_before","established_connection_count_after","external_established_connection_count","ssh_v2_identification_validated","connection_closed_before_authentication","raw_identification_serialized"}
    if not isinstance(transport,dict) or set(transport)!=transport_keys or transport.get("protocol")!="tcp" or transport.get("container_port")!=2222 or transport.get("host_port")!=runtime_ready["sftp_port"] or transport.get("binding_count") not in {1,2} or isinstance(transport.get("listener_count"),bool) or not isinstance(transport.get("listener_count"),int) or transport["listener_count"]<1 or any(transport.get(key)!=0 for key in ("established_connection_count_before","established_connection_count_after","external_established_connection_count")) or transport.get("ssh_v2_identification_validated") is not True or transport.get("connection_closed_before_authentication") is not True or transport.get("raw_identification_serialized") is not False or sha256.fullmatch(str(transport.get("binding_sha256",""))) is None:
        raise SystemExit("Release A SFTP runtime-ready transport differs")
    secure=runtime_ready.get("secure_deposit")
    secure_keys={"source_matches_dev_sdc","source_device_sha256","autonomous_mountpoint","host_read_only","namespace_autonomous_mountpoint","namespace_read_only","device_id"}
    if not isinstance(secure,dict) or set(secure)!=secure_keys or secure.get("source_matches_dev_sdc") is not True or secure.get("source_device_sha256")!=hashlib.sha256(b"/dev/sdc").hexdigest() or any(secure.get(key) is not True for key in ("autonomous_mountpoint","host_read_only","namespace_autonomous_mountpoint","namespace_read_only")) or isinstance(secure.get("device_id"),bool) or not isinstance(secure.get("device_id"),int) or secure["device_id"]<=0:
        raise SystemExit("Release A SFTP runtime-ready Secure Deposit state differs")
    host_key=runtime_ready.get("host_key")
    host_key_keys={"algorithm","fingerprint","fingerprint_sha256","present","nonempty","regular_file","symlink"}
    fingerprint=str(runtime_ready.get("host_key_fingerprint") or "")
    if not isinstance(host_key,dict) or set(host_key)!=host_key_keys or host_key.get("algorithm")!="ssh-ed25519" or host_key.get("fingerprint")!=fingerprint or re.fullmatch(r"SHA256:[A-Za-z0-9+/]{43}=?",fingerprint) is None or host_key.get("fingerprint_sha256")!=hashlib.sha256(fingerprint.encode("ascii")).hexdigest() or any(host_key.get(key) is not True for key in ("present","nonempty","regular_file")) or host_key.get("symlink") is not False:
        raise SystemExit("Release A SFTP runtime-ready host key differs")
    started_at=utc_stamp(runtime_ready,"sftp_started_at","SFTP runtime-ready")
    ready_at=utc_stamp(runtime_ready,"ready_at","SFTP runtime-ready")
    if started_at>ready_at:
        raise SystemExit("Release A SFTP runtime-ready chronology differs")
    runtime_digest=hashlib.sha256(b"agentium-release-a-sftp-runtime-identity-v1")
    for value in (runtime_ready["live_sha"],runtime_ready["release_a_sha"],runtime_ready["sftp_sha"],runtime_ready["deployment_id"],runtime_ready["hostname_sha256"],runtime_ready["sftp_container_id"],runtime_ready["sftp_image_id"],str(runtime_ready["sftp_port"]),runtime_ready["sftp_started_at"]):
        runtime_digest.update(b"\0"); runtime_digest.update(value.encode("utf-8"))
    if runtime_ready.get("runtime_identity_sha256")!=runtime_digest.hexdigest():
        raise SystemExit("Release A SFTP runtime-ready digest differs")

    sftp_ledger=bound["sftp-postgres-ledger-receipt.json"]
    ledger_keys={"schema_version","kind","result","live_sha","release_a_sha","sftp_sha","deployment_id","hostname_sha256","workspace_id_sha256","link_id_sha256","access_id_sha256","credential_fingerprint_sha256","sftp_container_id","sftp_image_id","sftp_port","runtime_identity_sha256","link_status","auth_failed_reason","remaining_active_link_count","active_sftp_session_count","deposit_file_delta_count","audits","binding_sha256","collected_at"}
    if not isinstance(sftp_ledger,dict) or set(sftp_ledger)!=ledger_keys or sftp_ledger.get("schema_version")!=1 or sftp_ledger.get("kind")!="agentium-release-a-sftp-postgres-ledger" or sftp_ledger.get("result")!="passed":
        raise SystemExit("Release A SFTP PostgreSQL ledger receipt schema differs")
    linked_fields=("live_sha","release_a_sha","sftp_sha","deployment_id","hostname_sha256","sftp_container_id","sftp_image_id","sftp_port","runtime_identity_sha256")
    if any(sftp_ledger.get(key)!=runtime_ready.get(key) for key in linked_fields):
        raise SystemExit("Release A SFTP PostgreSQL ledger/runtime binding differs")
    for key in ("hostname_sha256","workspace_id_sha256","link_id_sha256","access_id_sha256","credential_fingerprint_sha256","runtime_identity_sha256","binding_sha256"):
        if sha256.fullmatch(str(sftp_ledger.get(key,""))) is None: raise SystemExit(f"Release A SFTP PostgreSQL ledger digest differs: {key}")
    if sftp_ledger.get("link_status")!="revoked" or sftp_ledger.get("auth_failed_reason")!="inactive_or_expired" or any(sftp_ledger.get(key)!=0 for key in ("remaining_active_link_count","active_sftp_session_count","deposit_file_delta_count")):
        raise SystemExit("Release A SFTP PostgreSQL ledger cleanup differs")
    expected_events={"created":"deposit.link.created","auth_success":"deposit.sftp.auth.success","revoked":"deposit.link.revoked","auth_failed_inactive":"deposit.sftp.auth.failed"}
    audits=sftp_ledger.get("audits")
    audit_times=[]
    if not isinstance(audits,dict) or set(audits)!=set(expected_events):
        raise SystemExit("Release A SFTP PostgreSQL audit ledger differs")
    for name,event_type in expected_events.items():
        row=audits.get(name); row_keys={"event_type","event_id_sha256","event_digest_sha256","count","occurred_at"}
        if not isinstance(row,dict) or set(row)!=row_keys or row.get("event_type")!=event_type or row.get("count")!=1 or any(sha256.fullmatch(str(row.get(key,""))) is None for key in ("event_id_sha256","event_digest_sha256")):
            raise SystemExit("Release A SFTP PostgreSQL audit ledger differs")
        audit_times.append(utc_stamp(row,"occurred_at","SFTP PostgreSQL audit"))
    ledger_at=utc_stamp(sftp_ledger,"collected_at","SFTP PostgreSQL ledger")
    if not ready_at<=audit_times[0]<=audit_times[1]<=audit_times[2]<=audit_times[3]<=ledger_at<=attestation_at:
        raise SystemExit("Release A SFTP proof chronology differs")

    final=bound["release-a-final-evidence-receipt.json"]
    if attestation_receipt.get("release_a_sha")!=expected_sha or final.get("release_a_sha")!=expected_sha:
        raise SystemExit("Release A evidence receipts refer to another SHA")
    final_keys={"schema_version","kind","result","environment","deployment_id","live_sha","release_a_sha","sftp_release_sha","hostname_sha256","attestation_sha256","preconditions_receipt_sha256","preconditions_sha256","evidence_file_count","evidence_digest_count","evidence_reference_count","evidence_set_sha256","binding_manifest_sha256","authority_keyring_sha256","canonical_reference_count","external_reference_count","external_provenance_set_sha256","verified_at"}
    if not isinstance(final,dict) or set(final)!=final_keys or final.get("schema_version")!=1 or final.get("kind")!="agentium-release-a-final-evidence-receipt" or final.get("result")!="passed" or final.get("environment")!="production":
        raise SystemExit("Release A final evidence receipt schema differs")
    if final.get("deployment_id")!=entry.name or final.get("live_sha")!=metadata["live_sha"] or final.get("release_a_sha")!=expected_sha or final.get("sftp_release_sha")!=metadata["sftp_release_sha"] or final.get("hostname_sha256")!=hostname_digest:
        raise SystemExit("Release A final evidence receipt identity differs")
    if final.get("evidence_reference_count")!=37 or final.get("canonical_reference_count")!=23 or final.get("external_reference_count")!=14:
        raise SystemExit("Release A final evidence receipt cardinality differs")
    for key in ("hostname_sha256","attestation_sha256","preconditions_receipt_sha256","preconditions_sha256","evidence_set_sha256","binding_manifest_sha256","authority_keyring_sha256","external_provenance_set_sha256"):
        if sha256.fullmatch(str(final.get(key,""))) is None: raise SystemExit(f"Release A final evidence digest differs: {key}")
    if final.get("authority_keyring_sha256")!=keyring_digest:
        raise SystemExit("Release A final evidence authority keyring binding differs")
    if final.get("attestation_sha256")!=hashlib.sha256(attestation_body).hexdigest():
        raise SystemExit("Release A final evidence attestation binding differs")
    preconditions_evidence_path=path/"release-a-preconditions-evidence-receipt.json"
    preconditions_evidence_body=private_bytes(preconditions_evidence_path)
    if final.get("preconditions_receipt_sha256")!=hashlib.sha256(preconditions_evidence_body).hexdigest():
        raise SystemExit("Release A final evidence preconditions binding differs")
    snapshots[preconditions_evidence_path]=preconditions_evidence_body
    binding_path=path/"release-a-final-evidence-bindings.json"
    binding_body=private_bytes(binding_path)
    if final.get("binding_manifest_sha256")!=hashlib.sha256(binding_body).hexdigest():
        raise SystemExit("Release A final evidence binding manifest digest differs")
    binding=strict_json(binding_body,"final evidence binding manifest")
    binding_keys={"schema_version","result","environment","deployment_id","live_sha","release_a_sha","hostname_sha256","kind","sftp_release_sha","reference_count","canonical_reference_count","external_reference_count","authority_keyring_sha256","entries","verified_at"}
    if not isinstance(binding,dict) or set(binding)!=binding_keys or binding.get("schema_version")!=1 or binding.get("kind")!="agentium-release-a-final-evidence-bindings" or binding.get("result")!="passed" or binding.get("environment")!="production":
        raise SystemExit("Release A final evidence binding manifest schema differs")
    if binding.get("deployment_id")!=entry.name or binding.get("live_sha")!=metadata["live_sha"] or binding.get("release_a_sha")!=expected_sha or binding.get("sftp_release_sha")!=metadata["sftp_release_sha"] or binding.get("hostname_sha256")!=hostname_digest or binding.get("authority_keyring_sha256")!=keyring_digest:
        raise SystemExit("Release A final evidence binding manifest identity differs")
    if binding.get("reference_count")!=37 or binding.get("canonical_reference_count")!=23 or binding.get("external_reference_count")!=14 or not isinstance(binding.get("entries"),list) or len(binding["entries"])!=37:
        raise SystemExit("Release A final evidence binding manifest cardinality differs")
    snapshots[binding_path]=binding_body
    snapshots[path/"release-a-final-evidence-receipt.json"]=private_bytes(path/"release-a-final-evidence-receipt.json")
    directory(path/"external-final-evidence")
    candidate_body=private_bytes(path/"release-a-candidate-oci-receipt.json")
    snapshots[path/"release-a-candidate-oci-receipt.json"]=candidate_body
    candidate=strict_json(candidate_body,"candidate OCI receipt")
    candidate_keys={"schema_version","kind","result","deployment_id","release_a_sha","docker_engine_id","images","captured_at"}
    if not isinstance(candidate,dict) or set(candidate)!=candidate_keys or candidate.get("schema_version")!=1 or candidate.get("kind")!="agentium-release-a-candidate-oci-receipt" or candidate.get("result")!="passed":
        raise SystemExit("Release A candidate OCI receipt schema differs")
    if candidate.get("deployment_id")!=entry.name or candidate.get("release_a_sha")!=expected_sha or candidate.get("docker_engine_id")!=engine_id:
        raise SystemExit("Release A candidate OCI receipt identity differs")
    images=candidate.get("images")
    expected_services=["agentium-backend","agentium-frontend","agentium-worker-cpu"]
    if not isinstance(images,list) or [row.get("service") if isinstance(row,dict) else None for row in images]!=expected_services:
        raise SystemExit("Release A candidate OCI service inventory differs")
    expected_prefixes={
      "agentium-backend":"agentium-backend:",
      "agentium-frontend":"agentium-frontend:",
      "agentium-worker-cpu":"agentium-worker:",
    }
    image_ids=[]; tags=[]
    for row in images:
        if set(row)!={"service","image_ref","image_id","revision"}:
            raise SystemExit("Release A candidate OCI image schema differs")
        service=row["service"]; image_ref=str(row.get("image_ref", "")); prefix=expected_prefixes[service]
        if not image_ref.startswith(prefix) or re.fullmatch(r"[A-Za-z0-9_.-]+",image_ref[len(prefix):]) is None:
            raise SystemExit("Release A candidate OCI image reference differs")
        if re.fullmatch(r"sha256:[0-9a-f]{64}",str(row.get("image_id",""))) is None or row.get("revision")!=expected_sha:
            raise SystemExit("Release A candidate OCI image identity differs")
        image_ids.append(row["image_id"]); tags.append(image_ref[len(prefix):])
    if len(set(image_ids))!=3 or len(set(tags))!=1:
        raise SystemExit("Release A candidate OCI images are aliased or use divergent tags")
    candidate_by_service={row["service"]:row for row in images}
    runtime=bound["release-a-runtime-oci-receipt.json"]
    runtime_keys={"schema_version","kind","result","deployment_id","release_a_sha","docker_engine_id","candidate_oci_receipt_sha256","containers","backend_build_info","verified_at"}
    if set(runtime)!=runtime_keys or runtime.get("schema_version")!=1 or runtime.get("kind")!="agentium-release-a-runtime-oci-receipt" or runtime.get("result")!="passed":
        raise SystemExit("Release A runtime OCI receipt schema differs")
    if runtime.get("deployment_id")!=entry.name or runtime.get("release_a_sha")!=expected_sha or runtime.get("docker_engine_id")!=engine_id:
        raise SystemExit("Release A runtime OCI receipt identity differs")
    if runtime.get("candidate_oci_receipt_sha256")!=hashlib.sha256(candidate_body).hexdigest():
        raise SystemExit("Release A runtime OCI candidate binding differs")
    containers=runtime.get("containers")
    if not isinstance(containers,list) or [row.get("service") if isinstance(row,dict) else None for row in containers]!=expected_services:
        raise SystemExit("Release A runtime OCI service inventory differs")
    container_ids=[]
    for row in containers:
        if set(row)!={"service","container_id","image_ref","image_id","image_revision","state","health_status"}:
            raise SystemExit("Release A runtime OCI container schema differs")
        if re.fullmatch(r"[0-9a-f]{64}",str(row.get("container_id",""))) is None or re.fullmatch(r"sha256:[0-9a-f]{64}",str(row.get("image_id",""))) is None:
            raise SystemExit("Release A runtime OCI identity is invalid")
        expected_image=candidate_by_service[row["service"]]
        if row.get("image_ref")!=expected_image["image_ref"] or row.get("image_id")!=expected_image["image_id"]:
            raise SystemExit("Release A runtime OCI image differs from its candidate receipt")
        expected_health="not_configured" if row["service"]=="agentium-worker-cpu" else "healthy"
        if row.get("image_revision")!=expected_sha or row.get("state")!="running" or row.get("health_status")!=expected_health:
            raise SystemExit("Release A runtime OCI state differs")
        container_ids.append(row["container_id"])
    if len(set(container_ids))!=3:
        raise SystemExit("Release A runtime OCI containers are aliased")
    build_info=runtime.get("backend_build_info")
    if not isinstance(build_info,dict) or set(build_info)!={"service","revision","revision_verified","version"}:
        raise SystemExit("Release A runtime OCI build-info schema differs")
    if build_info.get("service")!="backend" or build_info.get("revision")!=expected_sha or build_info.get("revision_verified") is not True or not isinstance(build_info.get("version"),str) or not build_info["version"]:
        raise SystemExit("Release A runtime OCI build-info differs")
    timestamps=[]
    for owner,key in ((candidate,"captured_at"),(runtime,"verified_at"),(completion,"completed_at")):
        value=owner.get(key)
        if not isinstance(value,str) or not value.endswith("Z"):
            raise SystemExit(f"Release A OCI timestamp is invalid: {key}")
        try: timestamps.append(datetime.fromisoformat(value.removesuffix("Z")+"+00:00"))
        except ValueError as exc: raise SystemExit(f"Release A OCI timestamp is invalid: {key}") from exc
    if any(value.tzinfo is None for value in timestamps) or not timestamps[0]<=timestamps[1]<=timestamps[2]:
        raise SystemExit("Release A OCI receipt chronology differs")
    final_at=utc_stamp(final,"verified_at","final evidence")
    if not ready_at<=ledger_at<=attestation_at<=final_at<=timestamps[1]<=timestamps[2]:
        raise SystemExit("Release A terminal evidence chronology differs")
    for key in ("manifest_receipt_sha256","preconditions_receipt_sha256","preconditions_evidence_receipt_sha256"):
        if metadata.get(key)!=completion.get(key): raise SystemExit(f"Release A metadata/completion binding differs: {key}")
    if not git_sha.fullmatch(expected_sha): raise SystemExit("invalid expected Release A SHA")
    snapshots[completion_path]=completion_body
    forward_authorization_path=path/"release-a-forward-open-authorization.json"
    forward_authorization_body=private_bytes(forward_authorization_path,65536)
    forward_authorization=strict_json(forward_authorization_body,"forward terminal authorization")
    expected_authorization={
      "schema_version":1,
      "kind":"agentium-release-a-terminal-gate-authorization",
      "deployment_id":entry.name,
      "release_a_sha":expected_sha,
      "purpose":"forward-terminal-open",
      "terminal_phase":"completed",
      "receipt_name":"release-a-transaction-receipt.json",
      "receipt_sha256":hashlib.sha256(completion_body).hexdigest(),
    }
    expected_authorization_body=json.dumps(expected_authorization,separators=(",",":"),sort_keys=True).encode("utf-8")+b"\n"
    if forward_authorization!=expected_authorization or forward_authorization_body!=expected_authorization_body:
        raise SystemExit("Release A forward terminal authorization differs")
    snapshots[forward_authorization_path]=forward_authorization_body
    forward_marker_path=path/"release-a-forward-open-reconciled"
    forward_marker_body=private_bytes(forward_marker_path,4096)
    expected_marker=(f"format=2 direction=forward deployment_id={entry.name} release_a_sha={expected_sha} terminal_phase=completed receipt_sha256={hashlib.sha256(completion_body).hexdigest()} authorization_sha256={hashlib.sha256(forward_authorization_body).hexdigest()}\n").encode("ascii")
    if forward_marker_body!=expected_marker:
        raise SystemExit("Release A forward-open terminal marker differs")
    snapshots[forward_marker_path]=forward_marker_body
    matches.append(entry.name); matched_runtime=runtime; matched_runtime_ready=runtime_ready; matched_sftp_restart=historical_sftp_restart; matched_keycloak_contract=historical_keycloak_contract; matched_keycloak_restart=historical_keycloak_restart; matched_path=path; matched_metadata=metadata; matched_snapshots=snapshots; matched_executables={path/name for name in trusted_programs}
if len(matches)!=1: raise SystemExit(f"expected exactly one completed Release A transaction, found {len(matches)}")
if verify_live:
    def docker_json(*arguments):
        process=subprocess.run(["docker",*arguments],check=True,capture_output=True,text=True,timeout=30)
        value=json.loads(process.stdout)
        if not isinstance(value,list) or len(value)!=1: raise SystemExit("live Release A Docker inspection cardinality differs")
        return value[0]
    assert matched_runtime is not None and matched_runtime_ready is not None and matched_sftp_restart is not None and matched_keycloak_contract is not None and matched_keycloak_restart is not None and matched_metadata is not None
    for expected in matched_runtime["containers"]:
        service=expected["service"]; container=docker_json("inspect","--type","container",service)
        state=container.get("State") or {}; config=container.get("Config") or {}; health=state.get("Health")
        observed_health=str((health or {}).get("Status") or "not_configured")
        if container.get("Image")!=expected["image_id"] or state.get("Running") is not True or state.get("Paused") is not False or observed_health!=expected["health_status"]:
            raise SystemExit(f"live Release A runtime differs from its OCI receipt: {service}")
        image=docker_json("image","inspect",expected["image_id"]); labels=(image.get("Config") or {}).get("Labels") or {}; container_labels=config.get("Labels") or {}
        if labels.get("org.opencontainers.image.revision")!=expected_sha or container_labels.get("org.opencontainers.image.revision")!=expected_sha:
            raise SystemExit(f"live Release A image revision differs: {service}")
    sftp=docker_json("inspect","--type","container","agentium-sftp")
    sftp_state=sftp.get("State") or {}; sftp_health=sftp_state.get("Health") or {}; sftp_host_config=sftp.get("HostConfig") or {}; sftp_restart=sftp_host_config.get("RestartPolicy") or {}
    if sftp.get("Id")!=matched_runtime_ready["sftp_container_id"] or sftp.get("Image")!=matched_runtime_ready["sftp_image_id"] or sftp_state.get("StartedAt")!=matched_runtime_ready["sftp_started_at"] or sftp_state.get("Running") is not True or sftp_state.get("Paused") is not False or sftp_health.get("Status")!="healthy" or (sftp_restart.get("Name"),sftp_restart.get("MaximumRetryCount",0))!=matched_sftp_restart:
        raise SystemExit("live Release A SFTP runtime differs from its runtime-ready receipt")
    sftp_image=docker_json("image","inspect",matched_runtime_ready["sftp_image_id"]); sftp_labels=(sftp_image.get("Config") or {}).get("Labels") or {}
    if sftp_labels.get("org.opencontainers.image.revision")!=matched_metadata["sftp_release_sha"]:
        raise SystemExit("live Release A SFTP image revision differs")
    keycloak=docker_json("inspect","--type","container","agentium-kc")
    keycloak_state=keycloak.get("State") or {}; keycloak_health=keycloak_state.get("Health") or {}; keycloak_host_config=keycloak.get("HostConfig") or {}; keycloak_restart=keycloak_host_config.get("RestartPolicy") or {}
    def keycloak_binding(rows,label,allow_unpublished=False):
        if not isinstance(rows,dict):
            raise SystemExit(f"live Release A Keycloak {label} binding differs")
        if allow_unpublished:
            if not set(rows).issubset({"8080/tcp","8443/tcp","9000/tcp"}):
                raise SystemExit(f"live Release A Keycloak {label} exposed-port inventory differs")
            if any(key!="8080/tcp" and value not in (None,[]) for key,value in rows.items()):
                raise SystemExit(f"live Release A Keycloak {label} contains another published endpoint")
            rows={"8080/tcp":rows.get("8080/tcp")}
        if set(rows)!={"8080/tcp"} or not isinstance(rows["8080/tcp"],list) or len(rows["8080/tcp"])!=1:
            raise SystemExit(f"live Release A Keycloak {label} binding differs")
        row=rows["8080/tcp"][0]
        if not isinstance(row,dict) or row.get("HostIp")!="127.0.0.1" or str(row.get("HostPort") or "")!=str(matched_keycloak_contract["host_port"]):
            raise SystemExit(f"live Release A Keycloak {label} binding is not the attested loopback endpoint")
    keycloak_binding(keycloak_host_config.get("PortBindings") or {},"configured")
    keycloak_binding(((keycloak.get("NetworkSettings") or {}).get("Ports") or {}),"effective",True)
    if keycloak.get("Id")!=matched_keycloak_contract["container_id"] or keycloak.get("Image")!=matched_keycloak_contract["image_id"] or keycloak_state.get("Running") is not True or keycloak_state.get("Paused") is not False or keycloak_state.get("Restarting") is not False or keycloak_state.get("Dead") is not False or keycloak_state.get("OOMKilled") is not False or keycloak_health.get("Status")!="healthy" or (keycloak_restart.get("Name"),keycloak_restart.get("MaximumRetryCount",0))!=matched_keycloak_restart:
        raise SystemExit("live Release A Keycloak runtime differs from its historical control-plane contract")
    probes={
      "agentium-backend":["docker","exec","agentium-backend","python","-I","-c",'import http.client,json;c=http.client.HTTPConnection("127.0.0.1",8000,timeout=5);c.request("GET","/api/v1/build-info");r=c.getresponse();b=r.read(4097);assert r.status==200 and len(b)<=4096;print(json.dumps(json.loads(b)))'],
      "agentium-frontend":["docker","exec","agentium-frontend","wget","-qO-","http://127.0.0.1:8080/build-info.json"],
    }
    for service,command in probes.items():
        process=subprocess.run(command,check=True,capture_output=True,text=True,timeout=15)
        payload=json.loads(process.stdout)
        expected_name="backend" if service=="agentium-backend" else "frontend"
        if not isinstance(payload,dict) or payload.get("service")!=expected_name or payload.get("revision")!=expected_sha or payload.get("revision_verified") is not True or not isinstance(payload.get("version"),str) or not payload["version"]:
            raise SystemExit(f"live Release A build-info differs: {service}")
        if service=="agentium-backend" and payload!=matched_runtime["backend_build_info"]:
            raise SystemExit("live Release A backend build-info differs from its OCI receipt")
assert matched_path is not None and matched_metadata is not None and matched_snapshots is not None and matched_executables is not None
helper=matched_path/"agentium_release_a_evidence_bundle.py"
command=[
  sys.executable,"-I",str(helper),"verify-final-frozen",
  "--attestation",str(matched_path/"release-a-attestation.json"),
  "--preconditions-receipt",str(matched_path/"release-a-preconditions-evidence-receipt.json"),
  "--evidence-receipt",str(matched_path/"release-a-final-evidence-receipt.json"),
  "--binding-manifest",str(matched_path/"release-a-final-evidence-bindings.json"),
  "--evidence-root",str(matched_path/"external-final-evidence"),
  "--journal-root",str(matched_path),
  "--authority-keyring",str(matched_path/"release-a-evidence-authority-keyring.json"),
  "--expected-authority-keyring-sha256",matched_metadata["evidence_authority_keyring_sha256"],
  "--expected-live-sha",matched_metadata["live_sha"],
  "--expected-release-a-sha",expected_sha,
  "--expected-sftp-sha",matched_metadata["sftp_release_sha"],
  "--expected-hostname",hostname,
  "--deployment-id",matched_path.name,
]
try:
    verified=subprocess.run(command,cwd=matched_path,env={"PATH":"/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin","PYTHONDONTWRITEBYTECODE":"1","LANG":"C","LC_ALL":"C"},capture_output=True,text=True,timeout=180)
except (OSError,subprocess.TimeoutExpired) as exc:
    raise SystemExit("Release A frozen evidence helper could not run") from exc
if verified.returncode!=0 or verified.stdout.strip()!="passed":
    raise SystemExit("Release A frozen evidence helper refused the completed transaction")
for artifact,expected in matched_snapshots.items():
    observed=executable_bytes(artifact) if artifact in matched_executables else private_bytes(artifact)
    if observed!=expected: raise SystemExit(f"Release A trust artifact changed during frozen verification: {artifact.name}")
PY
}

ensure_release_a_gate() {
	local current_sha sftp_release_sha runtime_hostname receipt_temporary
	if [[ -e "$METADATA_FILE" || -L "$METADATA_FILE" ]]; then
		assert_recorded_release_a_gate
		return
	fi
	[[ -n "$RELEASE_A_ATTESTATION" && -n "$RELEASE_A_ATTESTATION_SHA256" ]] ||
		die "Premier preflight: --release-a-attestation et son --release-a-attestation-sha256 sont obligatoires"
	stage_release_a_helper
	current_sha="$(active_application_sha)"
	sftp_release_sha="$(live_sftp_release_sha)"
	assert_completed_release_a_transaction "$current_sha"
	[[ "$(git rev-parse HEAD)" == "$current_sha" ]] ||
		die "Attestation Release A refusée: checkout et runtime actifs divergent"
	[[ "$current_sha" != "$EXPECTED_SHA" ]] ||
		die "La Release B candidate doit être distincte de la Release A attestée"
	git merge-base --is-ancestor "$current_sha" "$EXPECTED_SHA" ||
		die "Le candidat n'est pas descendant de la Release A active attestée"
	assert_release_a_helper_trust_root "$current_sha"
	assert_sftp_helper_trust_root "$current_sha"
	if [[ ! -e "$FROZEN_RELEASE_A_ATTESTATION" && ! -L "$FROZEN_RELEASE_A_ATTESTATION" ]]; then
		freeze_release_a_attestation "$RELEASE_A_ATTESTATION" "$RELEASE_A_ATTESTATION_SHA256"
	else
		assert_private_state_file "$FROZEN_RELEASE_A_ATTESTATION"
		[[ "$(sha256sum "$FROZEN_RELEASE_A_ATTESTATION" | awk '{print $1}')" == "$RELEASE_A_ATTESTATION_SHA256" ]] ||
			die "Attestation Release A déjà figée avec un autre digest"
	fi
	runtime_hostname="$(hostname -f)"
	receipt_temporary="$DEPLOY_DIR/.release-a-verification-receipt.$$"
	rm -f "$receipt_temporary"
	if ! "$RELEASE_A_HELPER" verify \
		--attestation "$FROZEN_RELEASE_A_ATTESTATION" \
		--expected-release-a-sha "$current_sha" \
		--expected-sftp-sha "$sftp_release_sha" \
		--expected-hostname "$runtime_hostname" \
		--max-age-hours "$RELEASE_A_ATTESTATION_MAX_AGE_HOURS" >"$receipt_temporary"; then
		rm -f "$receipt_temporary"
		die "Attestation Release A opérateur refusée"
	fi
	chmod 0600 "$receipt_temporary"
	if [[ -e "$RELEASE_A_RECEIPT" || -L "$RELEASE_A_RECEIPT" ]]; then
		durable_replace_file "$receipt_temporary" "$RELEASE_A_RECEIPT"
	else
		durable_publish_file "$receipt_temporary" "$RELEASE_A_RECEIPT"
	fi
	assert_release_a_receipt_contract "$current_sha" "$sftp_release_sha" "$RELEASE_A_ATTESTATION_SHA256" "" fresh
}

assert_recorded_release_a_gate() {
	local attestation_digest receipt_digest helper_blob freshness=recorded current_phase
	assert_metadata_contract
	attestation_digest="$(metadata release_a_attestation_sha256)"
	receipt_digest="$(metadata release_a_receipt_sha256)"
	stage_release_a_helper
	assert_release_a_helper_trust_root "$(metadata previous_sha)"
	assert_sftp_helper_trust_root "$(metadata previous_sha)"
	helper_blob="$(git -C "$REPO_DIR" rev-parse "${EXPECTED_SHA}:scripts/agentium_release_a_attestation.py")"
	[[ "$(git -C "$REPO_DIR" hash-object "$RELEASE_A_HELPER")" == "$helper_blob" ]] ||
		die "Helper Release A figé divergent"
	current_phase="$(phase)"
	if [[ "$MODE" != "rollback" && ( "$current_phase" == "new" || "$current_phase" == "preflight_ok" || "$current_phase" == "prepared" ) ]]; then
		freshness=fresh
	fi
	assert_release_a_receipt_contract "$(metadata previous_sha)" "$(metadata sftp_release_sha)" "$attestation_digest" "$receipt_digest" "$freshness"
}

stage_env_bundle_helper() {
	local blob temporary
	blob="$(git -C "$REPO_DIR" rev-parse "${EXPECTED_SHA}:scripts/agentium_runtime_env_bundle.py" 2>/dev/null || true)"
	[[ "$blob" =~ ^[0-9a-f]{40}$ ]] || die "Helper env-bundle absent du candidat"
	if [[ -f "$ENV_BUNDLE_HELPER" ]]; then
		[[ ! -L "$ENV_BUNDLE_HELPER" && "$(git -C "$REPO_DIR" hash-object "$ENV_BUNDLE_HELPER")" == "$blob" ]] ||
			die "Helper env-bundle figé altéré"
		chmod 0700 "$ENV_BUNDLE_HELPER"
		return
	fi
	temporary="$DEPLOY_DIR/.agentium_runtime_env_bundle.$$"
	(umask 077; git -C "$REPO_DIR" show "${EXPECTED_SHA}:scripts/agentium_runtime_env_bundle.py" >"$temporary")
	[[ "$(git -C "$REPO_DIR" hash-object "$temporary")" == "$blob" ]] || die "Extraction env-bundle altérée"
	chmod 0700 "$temporary"
	if ln "$temporary" "$ENV_BUNDLE_HELPER" 2>/dev/null; then
		rm -f "$temporary"
	else
		rm -f "$temporary"
		die "Helper env-bundle créé concurremment"
	fi
}

verify_runtime_env_bundle() {
	[[ -x "$ENV_BUNDLE_HELPER" && -n "${ENV_MANIFEST_SHA256:-}" ]] || die "Bundle env non initialisé"
	"$ENV_BUNDLE_HELPER" verify \
		--bundle-dir "$ENV_BUNDLE_DIR" --sha "$EXPECTED_SHA" \
		--deployment-id "$DEPLOYMENT_ID" \
		--expected-manifest-sha256 "$ENV_MANIFEST_SHA256"
}

ensure_runtime_env_bundle() {
	local live_main="$REPO_DIR/docker/${LIVE_ENV_FILE#./}" expected_intent="${EXPECTED_SHA}:${DEPLOYMENT_ID}"
	stage_env_bundle_helper
	if [[ -d "$ENV_BUNDLE_DIR" ]]; then
		assert_private_state_file "$ENV_BUNDLE_INTENT"
		[[ "$(<"$ENV_BUNDLE_INTENT")" == "$expected_intent" ]] || die "Bundle env orphelin sans intent correspondant"
	else
		[[ ! -e "$ENV_BUNDLE_DIR" && ! -L "$ENV_BUNDLE_DIR" ]] || die "Chemin bundle env non régulier"
		if [[ -e "$ENV_BUNDLE_INTENT" || -L "$ENV_BUNDLE_INTENT" ]]; then
			assert_private_state_file "$ENV_BUNDLE_INTENT"
			[[ "$(<"$ENV_BUNDLE_INTENT")" == "$expected_intent" ]] || die "Intent bundle env lié à une autre transaction"
		else
			atomic_text "$ENV_BUNDLE_INTENT" "$expected_intent"
			assert_private_state_file "$ENV_BUNDLE_INTENT"
		fi
	fi
	local source_owner_uid
	source_owner_uid="$(stat -c %u "$REPO_DIR")"
	[[ "$source_owner_uid" =~ ^[0-9]+$ ]] || die "UID du propriétaire du dépôt invalide"
	ENV_MANIFEST_SHA256="$("$ENV_BUNDLE_HELPER" freeze \
		--main-env "$live_main" --compose-dir "$REPO_DIR/docker" \
		--systemd-env "$REPO_DIR/backend/.env" --bundle-dir "$ENV_BUNDLE_DIR" \
		--sha "$EXPECTED_SHA" --deployment-id "$DEPLOYMENT_ID" \
		--source-owner-uid "$source_owner_uid")"
	[[ "$ENV_MANIFEST_SHA256" =~ ^[0-9a-f]{64}$ ]] || die "Digest du bundle env invalide"
	ENV_FILE="$FROZEN_COMPOSE_ENV"
	verify_runtime_env_bundle >/dev/null
	FROZEN_SYSTEMD_ENV="$("$ENV_BUNDLE_HELPER" role-path \
		--bundle-dir "$ENV_BUNDLE_DIR" --sha "$EXPECTED_SHA" \
		--deployment-id "$DEPLOYMENT_ID" --role systemd \
		--expected-manifest-sha256 "$ENV_MANIFEST_SHA256")"
	[[ "$FROZEN_SYSTEMD_ENV" == "$ENV_BUNDLE_DIR"/* && -f "$FROZEN_SYSTEMD_ENV" && ! -L "$FROZEN_SYSTEMD_ENV" ]] ||
		die "Env systemd figé invalide"
}

assert_recorded_env_bundle_identity() {
	local recorded
	[[ -f "$METADATA_FILE" ]] || return 0
	assert_metadata_contract
	recorded="$(metadata env_manifest_sha256)"
	[[ "$recorded" =~ ^[0-9a-f]{64}$ && "$recorded" == "$ENV_MANIFEST_SHA256" ]] ||
		die "Le bundle env courant diffère du digest durable de ce déploiement"
	verify_runtime_env_bundle >/dev/null
}

phase() { if [[ -e "$PHASE_FILE" || -L "$PHASE_FILE" ]]; then assert_phase_contract; cat "$PHASE_FILE"; else printf 'new\n'; fi; }
set_phase() {
	local target="$1" current
	current="$(phase)"
	if [[ "$target" != "$current" ]]; then
		case "$current:$target" in
		new:preflight_ok | \
		preflight_ok:prepared | \
		prepared:closing_intent | prepared:rollback_closing | \
		closing_intent:closing | closing_intent:recovering_pre_migration | closing_intent:rollback_closing | \
		closing:maintenance_closed | closing:recovering_pre_migration | closing:rollback_closing | \
		maintenance_closed:quiesced | maintenance_closed:recovering_pre_migration | maintenance_closed:rollback_closing | \
		quiesced:backfill_pending | quiesced:recovering_pre_migration | quiesced:rollback_closing | \
		backfill_pending:backfill_applying | backfill_pending:rollback_closing | \
		backfill_applying:migrated | backfill_applying:rollback_closing | \
		migrated:activated | migrated:rollback_closing | \
		activated:validation_starting | activated:rollback_closing | \
		validation_starting:validation_pending | validation_starting:rollback_closing | \
		validation_pending:opening_forward | validation_pending:rollback_closing | \
		opening_forward:opened | opened:completed | \
		recovering_pre_migration:prepared | recovering_pre_migration:rollback_closing | \
		rollback_closing:rollback_restoring | rollback_closing:rolled_back_restored | \
		rollback_restoring:rolled_back_restored | \
		rolled_back_restored:rollback_opening | rollback_opening:rolled_back) ;;
		*) die "Transition de phase interdite: $current -> $target" ;;
		esac
	fi
	if [[ -e "$METADATA_FILE" || -L "$METADATA_FILE" ]]; then
		assert_recorded_release_a_manifest_gate
	fi
	atomic_text "$PHASE_FILE" "$target"
	assert_phase_contract
	ok "phase = $target"
}
metadata() { assert_metadata_contract; awk -F '\t' -v key="$1" '$1 == key { value=$2; found++ } END { if (found == 1) print value; else exit 1 }' "$METADATA_FILE"; }

assert_workspace_target_gate_contract() {
	local target="${1:-$WORKSPACE_TARGETS}" workspace_csv
	workspace_csv="$(IFS=,; printf '%s' "${CANARY_WORKSPACE_IDS[*]}")"
	assert_private_state_file "$target"
	python3 - "$target" "$EXPECTED_SHA" "$DEPLOYMENT_ID" "$workspace_csv" <<'PY'
import json
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected_sha, expected_deployment, raw_ids = sys.argv[2:]
expected_ids = raw_ids.split(",")
uuid_pattern = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
if len(expected_ids) != 4 or expected_ids != sorted(set(expected_ids)):
    raise SystemExit("operator workspace inventory is not exactly four unique ids")
if not all(uuid_pattern.fullmatch(value) for value in expected_ids):
    raise SystemExit("operator workspace inventory contains a non-canonical UUID")

payload = json.loads(path.read_text(encoding="utf-8"))
if set(payload) != {
    "schema_version",
    "profile",
    "candidate_sha",
    "deployment_id",
    "selection",
    "operator_workspace_ids",
    "targets",
}:
    raise SystemExit("workspace target gate schema differs")
if payload.get("schema_version") != 2 or payload.get("profile") != "agentium-workspace-target-gate-v2":
    raise SystemExit("workspace target gate profile differs")
if payload.get("candidate_sha") != expected_sha or payload.get("deployment_id") != expected_deployment:
    raise SystemExit("workspace target gate is not transaction-bound")
if payload.get("selection") != "explicit_operator_workspace_ids":
    raise SystemExit("workspace target gate selection differs")
if payload.get("operator_workspace_ids") != expected_ids:
    raise SystemExit("workspace target gate operator ids differ")

expected_selectors = {
    "showcase": {"showcase_seed": True},
    "andritz": {"family": "andritz"},
    "sentinel": {
        "family": "sentinel_ci",
        "mission_room_enabled": True,
        "mission_room_profile": "sentinel_government_v1",
        "assistant_profile": "vigie_executive",
    },
    "octocity": {
        "family": "generic",
        "mission_room_enabled": True,
        "mission_room_profile": "octocity_institutional_v1",
        "assistant_profile": "octave_executive",
    },
}
targets = payload.get("targets")
if not isinstance(targets, dict) or set(targets) != set(expected_selectors):
    raise SystemExit("workspace target roles differ")
resolved_ids = []
resolved_slugs = []
for role, selector in expected_selectors.items():
    target = targets.get(role)
    if not isinstance(target, dict) or set(target) != {
        "workspace_id",
        "workspace_slug",
        "selector",
    }:
        raise SystemExit(f"workspace target {role} is malformed")
    workspace_id = target.get("workspace_id")
    if not isinstance(workspace_id, str) or not uuid_pattern.fullmatch(workspace_id):
        raise SystemExit(f"workspace target {role} id is invalid")
    workspace_slug = target.get("workspace_slug")
    if (
        not isinstance(workspace_slug, str)
        or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,99}", workspace_slug)
    ):
        raise SystemExit(f"workspace target {role} slug is invalid")
    if target.get("selector") != selector:
        raise SystemExit(f"workspace target {role} selector differs")
    resolved_ids.append(workspace_id)
    resolved_slugs.append(workspace_slug)
if sorted(resolved_ids) != expected_ids or len(set(resolved_ids)) != 4:
    raise SystemExit("workspace target roles do not map one-to-one to operator ids")
if len(set(resolved_slugs)) != 4:
    raise SystemExit("workspace target roles do not map one-to-one to canonical slugs")
PY
}

render_workspace_target_gate() {
	local output="$1" raw="$DEPLOY_DIR/.workspace-targets.raw.$$" workspace_csv
	workspace_csv="$(IFS=,; printf '%s' "${CANARY_WORKSPACE_IDS[*]}")"
	[[ "$output" == "$DEPLOY_DIR"/.* && ! -e "$output" && ! -L "$output" ]] ||
		die "Cible temporaire du gate workspace invalide"
	rm -f "$raw"
	if ! (umask 077; docker exec agentium-pg psql -X -v ON_ERROR_STOP=1 -qAt \
		-U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "BEGIN TRANSACTION READ ONLY; COPY (
SELECT id,
       slug,
       CASE WHEN COALESCE(settings::jsonb, '{}'::jsonb) @> '{\"showcase_seed\":true}'::jsonb THEN 1 ELSE 0 END,
       COALESCE(settings->>'family', ''),
       CASE WHEN COALESCE(settings::jsonb, '{}'::jsonb) #> '{mission_room,enabled}' = 'true'::jsonb THEN 1 ELSE 0 END,
       COALESCE(settings->'mission_room'->>'profile', ''),
       COALESCE(settings->>'assistant_profile_default', '')
FROM workspaces
WHERE is_active IS TRUE AND deleted_at IS NULL
ORDER BY id
) TO STDOUT WITH (FORMAT text, DELIMITER E'\\t'); COMMIT;" >"$raw"); then
		rm -f "$raw" "$output"
		die "Lecture PostgreSQL read-only du gate workspace en échec"
	fi
	chmod 0600 "$raw"
	if ! python3 - "$raw" "$output" "$EXPECTED_SHA" "$DEPLOYMENT_ID" "$workspace_csv" <<'PY'
import json
import re
import sys
from pathlib import Path

raw_path, output_path = map(Path, sys.argv[1:3])
candidate_sha, deployment_id, raw_expected_ids = sys.argv[3:]
expected_ids = raw_expected_ids.split(",")
uuid_pattern = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
if len(expected_ids) != 4 or expected_ids != sorted(set(expected_ids)):
    raise SystemExit("exactly four sorted operator workspace UUIDs are required")
if not all(uuid_pattern.fullmatch(value) for value in expected_ids):
    raise SystemExit("operator workspace id is not a canonical UUID")

rows = []
seen = set()
for line in raw_path.read_text(encoding="utf-8").splitlines():
    fields = line.split("\t")
    if len(fields) != 7:
        raise SystemExit("workspace identity row is malformed")
    workspace_id, workspace_slug, showcase, family, mission_enabled, profile, assistant = fields
    if not uuid_pattern.fullmatch(workspace_id) or workspace_id in seen:
        raise SystemExit("workspace identity UUID is invalid or duplicated")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,99}", workspace_slug):
        raise SystemExit("workspace identity slug is invalid")
    if showcase not in {"0", "1"} or mission_enabled not in {"0", "1"}:
        raise SystemExit("workspace boolean marker is invalid")
    seen.add(workspace_id)
    rows.append(
        {
            "workspace_id": workspace_id,
            "workspace_slug": workspace_slug,
            "showcase": showcase == "1",
            "family": family,
            "mission_enabled": mission_enabled == "1",
            "profile": profile,
            "assistant": assistant,
        }
    )

selectors = {
    "showcase": lambda row: row["showcase"],
    "andritz": lambda row: row["family"] == "andritz",
    "sentinel": lambda row: (
        row["family"] == "sentinel_ci"
        and row["mission_enabled"]
        and row["profile"] == "sentinel_government_v1"
        and row["assistant"] == "vigie_executive"
    ),
    "octocity": lambda row: (
        row["family"] == "generic"
        and row["mission_enabled"]
        and row["profile"] == "octocity_institutional_v1"
        and row["assistant"] == "octave_executive"
    ),
}
selected = {}
for role, predicate in selectors.items():
    matches = [row for row in rows if predicate(row)]
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one active {role} workspace, found {len(matches)}")
    selected[role] = matches[0]
if len({target["workspace_id"] for target in selected.values()}) != 4:
    raise SystemExit("canonical workspace selectors overlap")
if len({target["workspace_slug"] for target in selected.values()}) != 4:
    raise SystemExit("canonical workspace slugs overlap")
if sorted(target["workspace_id"] for target in selected.values()) != expected_ids:
    raise SystemExit("operator workspace UUIDs do not match the four canonical targets")

payload = {
    "schema_version": 2,
    "profile": "agentium-workspace-target-gate-v2",
    "candidate_sha": candidate_sha,
    "deployment_id": deployment_id,
    "selection": "explicit_operator_workspace_ids",
    "operator_workspace_ids": expected_ids,
    "targets": {
        "showcase": {
            "workspace_id": selected["showcase"]["workspace_id"],
            "workspace_slug": selected["showcase"]["workspace_slug"],
            "selector": {"showcase_seed": True},
        },
        "andritz": {
            "workspace_id": selected["andritz"]["workspace_id"],
            "workspace_slug": selected["andritz"]["workspace_slug"],
            "selector": {"family": "andritz"},
        },
        "sentinel": {
            "workspace_id": selected["sentinel"]["workspace_id"],
            "workspace_slug": selected["sentinel"]["workspace_slug"],
            "selector": {
                "family": "sentinel_ci",
                "mission_room_enabled": True,
                "mission_room_profile": "sentinel_government_v1",
                "assistant_profile": "vigie_executive",
            },
        },
        "octocity": {
            "workspace_id": selected["octocity"]["workspace_id"],
            "workspace_slug": selected["octocity"]["workspace_slug"],
            "selector": {
                "family": "generic",
                "mission_room_enabled": True,
                "mission_room_profile": "octocity_institutional_v1",
                "assistant_profile": "octave_executive",
            },
        },
    },
}
with output_path.open("x", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY
	then
		rm -f "$raw" "$output"
		die "Résolution canonique des quatre workspaces refusée"
	fi
	rm -f "$raw"
	chmod 0600 "$output"
	assert_workspace_target_gate_contract "$output"
}

ensure_workspace_target_gate() {
	local temporary="$DEPLOY_DIR/.workspace-targets.$$"
	rm -f "$temporary"
	render_workspace_target_gate "$temporary"
	if [[ -e "$WORKSPACE_TARGETS" || -L "$WORKSPACE_TARGETS" ]]; then
		assert_workspace_target_gate_contract "$WORKSPACE_TARGETS"
		cmp -s "$temporary" "$WORKSPACE_TARGETS" || {
			rm -f "$temporary"
			die "Identité canonique des workspaces modifiée depuis le preflight"
		}
		rm -f "$temporary"
	else
		durable_publish_file "$temporary" "$WORKSPACE_TARGETS"
	fi
	assert_workspace_target_gate_contract "$WORKSPACE_TARGETS"
}

assert_frozen_workspace_target_gate() {
	local observed
	assert_metadata_contract
	assert_workspace_target_gate_contract "$WORKSPACE_TARGETS"
	observed="$(sha256sum "$WORKSPACE_TARGETS" | awk '{print $1}')"
	[[ "$observed" == "$(metadata workspace_targets_sha256)" ]] ||
		die "Digest du gate workspace différent des métadonnées"
}

assert_recorded_workspace_target_gate() {
	assert_frozen_workspace_target_gate
	ensure_workspace_target_gate
	assert_frozen_workspace_target_gate
}

assert_candidate_checkout_intent() {
	assert_private_state_file "$CANDIDATE_CHECKOUT_INTENT"
	python3 - "$CANDIDATE_CHECKOUT_INTENT" "$DEPLOYMENT_ID" "$(metadata previous_sha)" "$EXPECTED_SHA" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected = {
    "format": "1",
    "deployment_id": sys.argv[2],
    "previous_sha": sys.argv[3],
    "candidate_sha": sys.argv[4],
    "state": "checkout_authorized",
}
rows = {}
for raw in path.read_text(encoding="utf-8").splitlines():
    fields = raw.split("\t")
    if len(fields) != 2 or fields[0] in rows:
        raise SystemExit("candidate checkout intent is malformed or duplicated")
    rows[fields[0]] = fields[1]
if rows != expected:
    raise SystemExit("candidate checkout intent differs from this transaction")
if not all(re.fullmatch(r"[0-9a-f]{40}", rows[key]) for key in ("previous_sha", "candidate_sha")):
    raise SystemExit("candidate checkout intent contains an invalid SHA")
if rows["previous_sha"] == rows["candidate_sha"]:
    raise SystemExit("candidate checkout intent does not cross a release boundary")
PY
}

ensure_candidate_checkout_intent() {
	local temporary="$DEPLOY_DIR/.candidate-checkout.intent.$$"
	if [[ -e "$CANDIDATE_CHECKOUT_INTENT" || -L "$CANDIDATE_CHECKOUT_INTENT" ]]; then
		assert_candidate_checkout_intent
		return
	fi
	(umask 077; {
		printf 'format\t1\n'
		printf 'deployment_id\t%s\n' "$DEPLOYMENT_ID"
		printf 'previous_sha\t%s\n' "$(metadata previous_sha)"
		printf 'candidate_sha\t%s\n' "$EXPECTED_SHA"
		printf 'state\tcheckout_authorized\n'
	} >"$temporary")
	durable_publish_file "$temporary" "$CANDIDATE_CHECKOUT_INTENT"
	assert_candidate_checkout_intent
}

read_env_value() {
	local key="$1" path="$ENV_FILE"
	verify_runtime_env_bundle >/dev/null
	if [[ "$path" != /* ]]; then path="$REPO_DIR/docker/${path#./}"; fi
	awk -F= -v key="$key" '$1 == key { sub(/^[^=]*=/, ""); sub(/\r$/, ""); print; exit }' "$path"
}

read_dotenv_value() {
	local path="$1" key="$2"
	verify_runtime_env_bundle >/dev/null
	[[ "$path" == "$ENV_BUNDLE_DIR"/* && -f "$path" && ! -L "$path" ]] || die "Lecture dotenv hors bundle figé"
	awk -F= -v key="$key" '$1 == key { sub(/^[^=]*=/, ""); sub(/\r$/, ""); print; exit }' "$path"
}

compose() {
	local effective_key override pinned="${AGENTIUM_PIN_CANDIDATE_IMAGES:-}" rollback_pinned="${AGENTIUM_PIN_ROLLBACK_IMAGES:-}" celery_beat="${AGENTIUM_CELERY_BEAT:-}" startup="${AGENTIUM_STARTUP_RECONCILIATION:-}"
	verify_runtime_env_bundle >/dev/null
	effective_key="$(qdrant_effective_client_key)"
	override="$(compose_transaction_override)"
	[[ "${#effective_key}" -ge 32 ]] || die "Clé Qdrant transactionnelle absente"
	[[ -z "$celery_beat" || "$celery_beat" == "0" || "$celery_beat" == "1" ]] ||
		die "Override transactionnel Celery beat invalide"
	[[ -z "$startup" || "$startup" == "enabled" || "$startup" == "disabled" ]] ||
		die "Override transactionnel startup reconciliation invalide"
	[[ -z "$pinned" || "$pinned" == "1" ]] || die "Override d'images candidates invalide"
	[[ -z "$rollback_pinned" || "$rollback_pinned" == "1" ]] || die "Override d'images rollback invalide"
	[[ -z "$pinned" || -z "$rollback_pinned" ]] || die "Overrides OCI candidat et rollback mutuellement exclusifs"
	if [[ "$pinned" == "1" ]]; then assert_candidate_image_override_contract; fi
	if [[ "$rollback_pinned" == "1" ]]; then assert_rollback_image_override_contract; fi
	(
		cd "$REPO_DIR/docker"
		export AGENTIUM_QDRANT_EFFECTIVE_API_KEY="$effective_key"
		export AGENTIUM_COMPOSE_EXEC_HOME="$COMPOSE_CLEAN_HOME"
		export AGENTIUM_COMPOSE_EXEC_PATH="$COMPOSE_CLEAN_PATH"
		[[ -z "$celery_beat" ]] || export AGENTIUM_CELERY_BEAT="$celery_beat"
		[[ -z "$startup" ]] || export AGENTIUM_STARTUP_RECONCILIATION="$startup"
		[[ -z "$pinned" ]] || export AGENTIUM_COMPOSE_CANDIDATE_IMAGE_OVERRIDE="$CANDIDATE_IMAGE_OVERRIDE"
		[[ -z "$rollback_pinned" ]] || export AGENTIUM_COMPOSE_ROLLBACK_IMAGE_OVERRIDE="$ROLLBACK_IMAGE_OVERRIDE"
		/usr/bin/python3 - "$ENV_FILE" "$COMPOSE_FILE" "$override" -- "$@" <<'PY'
import os
import sys

env_file, compose_file, override = sys.argv[1:4]
environment = {
    "HOME": os.environ["AGENTIUM_COMPOSE_EXEC_HOME"],
    "PATH": os.environ["AGENTIUM_COMPOSE_EXEC_PATH"],
    "DOCKER_HOST": "unix:///var/run/docker.sock",
    "AGENTIUM_QDRANT_EFFECTIVE_API_KEY": os.environ[
        "AGENTIUM_QDRANT_EFFECTIVE_API_KEY"
    ],
}
for name in ("AGENTIUM_CELERY_BEAT", "AGENTIUM_STARTUP_RECONCILIATION"):
    if name in os.environ:
        environment[name] = os.environ[name]
arguments = [
    "docker", "compose", "--env-file", env_file,
    "-f", compose_file, "-f", override,
]
candidate_override = os.environ.get("AGENTIUM_COMPOSE_CANDIDATE_IMAGE_OVERRIDE")
if candidate_override:
    arguments.extend(["-f", candidate_override])
rollback_override = os.environ.get("AGENTIUM_COMPOSE_ROLLBACK_IMAGE_OVERRIDE")
if rollback_override:
    arguments.extend(["-f", rollback_override])
arguments.extend(sys.argv[5:])
os.execvpe("docker", arguments, environment)
PY
	)
}

compose_transaction_override() {
	case "$(phase)" in
		opening_forward | opened | completed | rollback_opening | rolled_back) printf '%s\n' "$FROZEN_OPENED_OVERRIDE" ;;
	*) printf '%s\n' "$FROZEN_QDRANT_OVERRIDE" ;;
	esac
}

qdrant_server_key() {
	local key_name="$1" value
	case "$key_name" in admin) key_name=QDRANT__SERVICE__API_KEY ;; read-only) key_name=QDRANT__SERVICE__READ_ONLY_API_KEY ;; *) die "Type de clé Qdrant invalide" ;; esac
	value="$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' qdrant | awk -F= -v key="$key_name" '$1 == key {sub(/^[^=]*=/, ""); print; exit}')"
	[[ "${#value}" -ge 32 ]] || die "Clé Qdrant $key_name absente ou trop courte"
	printf '%s' "$value"
}

assert_qdrant_key_separation() {
	local admin readonly
	admin="$(qdrant_server_key admin)"
	readonly="$(qdrant_server_key read-only)"
	[[ "$admin" != "$readonly" ]] || die "Les clés Qdrant admin et read-only doivent être distinctes"
}

qdrant_effective_client_key() {
	case "$(phase)" in opening_forward | opened | completed | rollback_opening | rolled_back) qdrant_server_key admin ;; *) qdrant_server_key read-only ;; esac
}

assert_systemd_qdrant_admin_contract() {
	local configured admin
	verify_runtime_env_bundle >/dev/null
	[[ "$FROZEN_SYSTEMD_ENV" == "$ENV_BUNDLE_DIR"/* && -f "$FROZEN_SYSTEMD_ENV" && ! -L "$FROZEN_SYSTEMD_ENV" ]] ||
		die "Env systemd figé absent"
	configured="$(awk -F= '$1 == "QDRANT_API_KEY" {sub(/^[^=]*=/, ""); sub(/\r$/, ""); print; exit}' "$FROZEN_SYSTEMD_ENV")"
	admin="$(qdrant_server_key admin)"
	[[ "${#configured}" -ge 32 && "$configured" == "$admin" ]] ||
		die "Le backend systemd n'utilise pas la clé Qdrant admin effective"
}

run_qdrant_host_contract() {
	local output="$1" expected_access="$2" qdrant_port client
	shift 2
	local -a client_args=()
	[[ "$expected_access" == "read-only" || "$expected_access" == "admin" ]] || die "Accès Qdrant attendu invalide"
	qdrant_port="$(read_env_value AGENTIUM_QDRANT_HTTP_PORT)"
	qdrant_port="${qdrant_port:-6333}"
	[[ "$qdrant_port" =~ ^[0-9]+$ && "$qdrant_port" -ge 1 && "$qdrant_port" -le 65535 ]] ||
		die "Port HTTP Qdrant invalide"
	[[ "$#" -gt 0 ]] || die "Le contrat Qdrant exige au moins un client"
	for client in "$@"; do
		[[ "$client" =~ ^[A-Za-z0-9_.-]+$ ]] || die "Nom de client Qdrant invalide"
		client_args+=(--client-container "$client")
	done
	rm -f "$output"
	(umask 077; python3 "$QDRANT_BARRIER_HELPER" host-contract \
		--sha "$EXPECTED_SHA" --deployment-id "$DEPLOYMENT_ID" \
		--qdrant-container qdrant --qdrant-url "http://127.0.0.1:$qdrant_port" \
		--expected-image qdrant/qdrant:v1.12.5-unprivileged \
		--expected-network "$DOCKER_NETWORK" --expected-client-access "$expected_access" \
		"${client_args[@]}" --output "$output")
	chmod 0600 "$output"
	python3 -c 'import json,sys; p=json.load(open(sys.argv[1], encoding="utf-8")); assert p.get("result") == "passed" and p.get("secrets_serialized") is False' "$output" ||
		die "Contrat Qdrant invalide: $output"
}

run_qdrant_client_probe() {
	local container="$1" output="$2" expected_access="$3" temporary="$DEPLOY_DIR/.${output##*/}.$$"
	[[ "$expected_access" == "read-only" || "$expected_access" == "admin" ]] || die "Accès Qdrant attendu invalide"
	[[ "$container" == "agentium-backend" || "$container" == "agentium-worker-cpu" || "$container" == "agentium-p4-maintenance" ]] ||
		die "Client Qdrant candidat non autorisé: $container"
	rm -f "$temporary"
	if ! (umask 077; docker exec -w /app/backend "$container" \
		python -m scripts.audit_qdrant_write_barrier probe-client \
		--sha "$EXPECTED_SHA" --deployment-id "$DEPLOYMENT_ID" \
		--expected-access "$expected_access" --output - >"$temporary"); then
		[[ -s "$temporary" ]] && { chmod 0600 "$temporary"; durable_replace_file "$temporary" "$output"; }
		die "La sonde write-denied Qdrant a échoué dans $container"
	fi
	chmod 0600 "$temporary"
	python3 - "$temporary" "$expected_access" <<'PY' || die "Preuve client Qdrant invalide pour $container"
import json, sys
p = json.load(open(sys.argv[1], encoding="utf-8"))
assert p.get("result") == "passed" and p.get("secrets_serialized") is False
probe = p.get("probe", {})
assert probe.get("expected_access") == sys.argv[2]
assert probe.get("write_rejected") is True if sys.argv[2] == "read-only" else probe.get("write_route_authorized") is True
PY
	durable_replace_file "$temporary" "$output"
}

attest_candidate_qdrant_barrier() {
	local output="$1"
	run_qdrant_host_contract "$output" read-only agentium-backend agentium-worker-cpu
	run_qdrant_client_probe agentium-backend "$QDRANT_BACKEND_PROBE" read-only
	run_qdrant_client_probe agentium-worker-cpu "$QDRANT_WORKER_PROBE" read-only
}

attest_candidate_qdrant_admin_ready() {
	local -a clients=(agentium-backend agentium-worker-cpu)
	if docker inspect agentium-p4-maintenance >/dev/null 2>&1 &&
		[[ "$(docker inspect --format '{{.State.Running}}' agentium-p4-maintenance)" == "true" ]]; then
		clients+=(agentium-p4-maintenance)
	fi
	run_qdrant_host_contract "$QDRANT_ADMIN_READY_BARRIER" admin "${clients[@]}"
	run_qdrant_client_probe agentium-backend "$DEPLOY_DIR/qdrant-backend-admin-probe.json" admin
	run_qdrant_client_probe agentium-worker-cpu "$DEPLOY_DIR/qdrant-worker-admin-probe.json" admin
	if [[ " ${clients[*]} " == *" agentium-p4-maintenance "* ]]; then
		run_qdrant_client_probe agentium-p4-maintenance "$QDRANT_P4_PROBE" admin
	fi
}

attest_live_qdrant_bootstrap() {
	local -a clients=(agentium-backend agentium-worker-cpu)
	if docker inspect agentium-p4-maintenance >/dev/null 2>&1 &&
		[[ "$(docker inspect --format '{{.State.Running}}' agentium-p4-maintenance)" == "true" ]]; then
		clients+=(agentium-p4-maintenance)
	fi
	run_qdrant_host_contract "$QDRANT_PREFLIGHT_BARRIER" admin "${clients[@]}"
}

sudo_command() {
	if [[ "$(id -u)" -eq 0 ]]; then "$@"; else sudo -n "$@"; fi
}

tcp_listener_rows() {
	local port="$1"
	sudo_command ss -Hltpn "sport = :$port"
}

assert_no_tcp_listener() {
	local port="$1" label="$2"
	[[ -z "$(tcp_listener_rows "$port")" ]] || die "$label écoute encore sur TCP/$port"
}

assert_tcp_listener_loopback_only() {
	local port="$1" label="$2" rows
	rows="$(tcp_listener_rows "$port")"
	[[ -n "$rows" ]] || die "$label n'écoute pas sur TCP/$port"
	awk -v port="$port" '
		{
			local_address=$4
			if (local_address == "127.0.0.1:" port || local_address == "[::1]:" port || local_address == "::1:" port) next
			bad=1
		}
		END { exit bad ? 1 : 0 }
	' <<<"$rows" || die "$label expose TCP/$port hors loopback; le gate Nginx serait contourné"
}

sftp_host_port() {
	local ports
	ports="$(docker port agentium-sftp 2222/tcp 2>/dev/null | awk -F: '{print $NF}' | sort -u)"
	[[ "$ports" =~ ^[0-9]+$ ]] || die "Port SFTP publié absent, multiple ou invalide"
	printf '%s\n' "$ports"
}

sftp_gate_rule() {
	local action="$1" tool="$2" chain="$3" port="$4"
	local -a match
	[[ "$action" == "-C" || "$action" == "-I" || "$action" == "-D" ]] || return 2
	if [[ "$chain" == "DOCKER-USER" ]]; then
		# Docker DNAT has already changed the destination by this chain. Match
		# the original published port so the rule also covers non-proxy mode.
		match=(! -i lo -p tcp -m conntrack --ctorigdstport "$port" --ctstate NEW)
	else
		# docker-proxy accepts on the host and therefore traverses INPUT.
		match=(! -i lo -p tcp --dport "$port" -m conntrack --ctstate NEW)
	fi
	if [[ "$action" == "-I" ]]; then
		sudo_command "$tool" -w 10 "$action" "$chain" 1 "${match[@]}" \
			-m comment --comment "$SFTP_GATE_COMMENT" -j REJECT --reject-with tcp-reset
	else
		sudo_command "$tool" -w 10 "$action" "$chain" "${match[@]}" \
			-m comment --comment "$SFTP_GATE_COMMENT" -j REJECT --reject-with tcp-reset
	fi
}

sftp_ingress_gate_is_closed() {
	local port tool chain
	port="$(sftp_host_port)"
	for tool in iptables ip6tables; do
		command -v "$tool" >/dev/null 2>&1 || return 1
		for chain in INPUT DOCKER-USER; do
			sftp_gate_rule -C "$tool" "$chain" "$port" >/dev/null 2>&1 || return 1
		done
	done
}

sftp_fail_closed_fallback() {
	local code=0 options target
	bootstrap_stop_sftp_writers || code=1
	if docker inspect agentium-sftp >/dev/null 2>&1; then
		[[ "$(docker inspect --format '{{.State.Running}}' agentium-sftp 2>/dev/null || true)" == false ]] || code=1
		[[ "$(container_restart_policy agentium-sftp 2>/dev/null || true)" == $'no\t0' ]] || code=1
	fi
	if sudo_command systemctl cat agentium-sftp.service >/dev/null 2>&1 &&
		sudo_command systemctl is-active --quiet agentium-sftp.service; then
		code=1
	fi
	target="$(findmnt -rn -S "$EXPECTED_SECURE_SOURCE" -o TARGET 2>/dev/null | awk 'NF { if (found++) exit 2; print }')" || code=1
	if [[ "$target" == /* && -d "$target" ]]; then
		options="$(findmnt -n -o OPTIONS --target "$target" 2>/dev/null || true)"
		[[ ",$options," == *,ro,* ]] || code=1
	else
		code=1
	fi
	return "$code"
}

leave_sftp_ingress_gate() {
	local port tool chain
	port="$(sftp_host_port)"
	for tool in iptables ip6tables; do
		command -v "$tool" >/dev/null 2>&1 || return 1
		for chain in INPUT DOCKER-USER; do
			while sftp_gate_rule -C "$tool" "$chain" "$port" >/dev/null 2>&1; do
				sftp_gate_rule -D "$tool" "$chain" "$port"
			done
		done
	done
	! sftp_ingress_gate_is_closed
}

enter_sftp_ingress_gate() {
	local port tool chain code=0
	if ! port="$(sftp_host_port)"; then
		sftp_fail_closed_fallback || true
		die "Port SFTP non attestable; service arrêté et Secure Deposit forcé en lecture seule"
	fi
	for tool in iptables ip6tables; do
		if ! command -v "$tool" >/dev/null 2>&1; then code=1; continue; fi
		for chain in INPUT DOCKER-USER; do
			if ! sftp_gate_rule -C "$tool" "$chain" "$port" >/dev/null 2>&1; then
				sftp_gate_rule -I "$tool" "$chain" "$port" || code=1
			fi
		done
	done
	if [[ "$code" -ne 0 ]] || ! sftp_ingress_gate_is_closed; then
		if sftp_fail_closed_fallback; then
			die "Fermeture firewall SFTP incomplète; règles acquises conservées, service arrêté et Secure Deposit en lecture seule"
		fi
		die "Fermeture firewall SFTP et fallback writer/RO incomplets; intervention requise"
	fi
}

assert_no_foreign_sftp_ingress_gate() {
	local dump own_count foreign_count=0 tool
	for tool in iptables-save ip6tables-save; do
		command -v "$tool" >/dev/null 2>&1 || die "$tool est requis pour auditer le gate SFTP"
		dump="$(sudo_command "$tool")"
		own_count="$(awk -v own="$SFTP_GATE_COMMENT" 'index($0, own) {count++} END {print count + 0}' <<<"$dump")"
		foreign_count=$((foreign_count + $(awk -v own="$SFTP_GATE_COMMENT" 'index($0, "agentium-safe-sftp-") && !index($0, own) {count++} END {print count + 0}' <<<"$dump")))
		[[ "$own_count" == "0" ]] || die "Gate SFTP courant déjà présent avant preflight"
	done
	[[ "$foreign_count" -eq 0 ]] || die "Un gate SFTP d'un ancien déploiement subsiste; revue opérateur requise"
}

systemd_backend_gate_rule() {
	local action="$1" tool="$2"
	[[ "$action" == "-C" || "$action" == "-I" || "$action" == "-D" ]] || return 2
	if [[ "$action" == "-I" ]]; then
		sudo_command "$tool" -w 10 "$action" INPUT 1 -p tcp --dport 8000 \
			-m conntrack --ctstate NEW -m comment --comment "$SYSTEMD_GATE_COMMENT" \
			-j REJECT --reject-with tcp-reset
	else
		sudo_command "$tool" -w 10 "$action" INPUT -p tcp --dport 8000 \
			-m conntrack --ctstate NEW -m comment --comment "$SYSTEMD_GATE_COMMENT" \
			-j REJECT --reject-with tcp-reset
	fi
}

systemd_backend_ingress_gate_is_closed() {
	local tool
	for tool in iptables ip6tables; do
		command -v "$tool" >/dev/null 2>&1 || return 1
		systemd_backend_gate_rule -C "$tool" >/dev/null 2>&1 || return 1
	done
}

enter_systemd_backend_ingress_gate() {
	local tool
	for tool in iptables ip6tables; do
		command -v "$tool" >/dev/null 2>&1 || die "$tool est requis pour geler le backend systemd legacy"
		if ! systemd_backend_gate_rule -C "$tool" >/dev/null 2>&1; then
			systemd_backend_gate_rule -I "$tool"
		fi
	done
	systemd_backend_ingress_gate_is_closed || die "Impossible de fermer TCP/8000"
}

leave_systemd_backend_ingress_gate() {
	local tool
	for tool in iptables ip6tables; do
		command -v "$tool" >/dev/null 2>&1 || return 1
		while systemd_backend_gate_rule -C "$tool" >/dev/null 2>&1; do
			systemd_backend_gate_rule -D "$tool"
		done
	done
	! systemd_backend_ingress_gate_is_closed
}

assert_no_foreign_systemd_backend_ingress_gate() {
	local dump own_count foreign_count=0 tool
	for tool in iptables-save ip6tables-save; do
		command -v "$tool" >/dev/null 2>&1 || die "$tool est requis pour auditer TCP/8000"
		dump="$(sudo_command "$tool")"
		own_count="$(awk -v own="$SYSTEMD_GATE_COMMENT" 'index($0, own) {count++} END {print count + 0}' <<<"$dump")"
		foreign_count=$((foreign_count + $(awk -v own="$SYSTEMD_GATE_COMMENT" 'index($0, "agentium-safe-systemd-backend-") && !index($0, own) {count++} END {print count + 0}' <<<"$dump")))
		[[ "$own_count" == "0" ]] || die "Gate TCP/8000 courant déjà présent avant preflight"
	done
	[[ "$foreign_count" -eq 0 ]] || die "Un gate TCP/8000 d'un ancien déploiement subsiste"
}

livekit_gate_bindings() {
	local kind service protocol _host_ip host_port _container_port
	while IFS=$'\t' read -r kind service protocol _host_ip host_port _container_port; do
		[[ "$kind" == "listener_binding" && "$service" == "agentium-livekit" ]] || continue
		printf '%s\t%s\n' "$protocol" "$host_port"
	done <"$RUNTIME_STATE_FILE" | sort -u
}

livekit_gate_rule() {
	local action="$1" tool="$2" chain="$3" protocol="$4" port="$5"
	local -a match
	[[ "$action" == "-C" || "$action" == "-I" || "$action" == "-D" ]] || return 2
	[[ "$protocol" == "tcp" || "$protocol" == "udp" ]] || return 2
	if [[ "$chain" == "DOCKER-USER" ]]; then
		match=(-p "$protocol" -m conntrack --ctorigdstport "$port" --ctstate NEW)
	else
		match=(-p "$protocol" --dport "$port" -m conntrack --ctstate NEW)
	fi
	if [[ "$action" == "-I" ]]; then
		sudo_command "$tool" -w 10 "$action" "$chain" 1 "${match[@]}" -m comment --comment "$LIVEKIT_GATE_COMMENT" -j DROP
	else
		sudo_command "$tool" -w 10 "$action" "$chain" "${match[@]}" -m comment --comment "$LIVEKIT_GATE_COMMENT" -j DROP
	fi
}

livekit_ingress_gate_is_closed() {
	local protocol port tool chain seen=0
	while IFS=$'\t' read -r protocol port; do
		seen=1
		for tool in iptables ip6tables; do
			command -v "$tool" >/dev/null 2>&1 || return 1
			for chain in INPUT DOCKER-USER; do
				livekit_gate_rule -C "$tool" "$chain" "$protocol" "$port" >/dev/null 2>&1 || return 1
			done
		done
	done < <(livekit_gate_bindings)
	[[ "$seen" -eq 1 || "$(historical_runtime_state agentium-livekit 2>/dev/null || true)" == "absent" ]]
}

enter_livekit_ingress_gate() {
	local protocol port tool chain
	while IFS=$'\t' read -r protocol port; do
		for tool in iptables ip6tables; do
			command -v "$tool" >/dev/null 2>&1 || die "$tool est requis pour geler LiveKit"
			for chain in INPUT DOCKER-USER; do
				if ! livekit_gate_rule -C "$tool" "$chain" "$protocol" "$port" >/dev/null 2>&1; then
					livekit_gate_rule -I "$tool" "$chain" "$protocol" "$port"
				fi
			done
		done
	done < <(livekit_gate_bindings)
	livekit_ingress_gate_is_closed || die "Impossible de fermer tous les bindings LiveKit"
}

leave_livekit_ingress_gate() {
	local protocol port tool chain seen=0
	while IFS=$'\t' read -r protocol port; do
		seen=1
		for tool in iptables ip6tables; do
			command -v "$tool" >/dev/null 2>&1 || return 1
			for chain in INPUT DOCKER-USER; do
				while livekit_gate_rule -C "$tool" "$chain" "$protocol" "$port" >/dev/null 2>&1; do
					livekit_gate_rule -D "$tool" "$chain" "$protocol" "$port"
				done
			done
		done
	done < <(livekit_gate_bindings)
	[[ "$seen" -eq 0 ]] || ! livekit_ingress_gate_is_closed
}

assert_no_foreign_livekit_ingress_gate() {
	local dump own_count foreign_count=0 tool
	for tool in iptables-save ip6tables-save; do
		command -v "$tool" >/dev/null 2>&1 || die "$tool est requis pour auditer le gate LiveKit"
		dump="$(sudo_command "$tool")"
		own_count="$(awk -v own="$LIVEKIT_GATE_COMMENT" 'index($0, own) {count++} END {print count + 0}' <<<"$dump")"
		foreign_count=$((foreign_count + $(awk -v own="$LIVEKIT_GATE_COMMENT" 'index($0, "agentium-safe-livekit-") && !index($0, own) {count++} END {print count + 0}' <<<"$dump")))
		[[ "$own_count" == "0" ]] || die "Gate LiveKit courant déjà présent avant preflight"
	done
	[[ "$foreign_count" -eq 0 ]] || die "Un gate LiveKit d'un ancien déploiement subsiste"
}

systemd_backend_state() {
	if ! sudo_command systemctl cat agentium-backend.service >/dev/null 2>&1; then
		printf 'absent\n'
	elif sudo_command systemctl is-active --quiet agentium-backend.service; then
		printf 'active\n'
	else
		printf 'stopped\n'
	fi
}

legacy_sftp_systemd_exists() {
	sudo_command systemctl cat agentium-sftp.service >/dev/null 2>&1
}

assert_legacy_sftp_systemd_safe() {
	local enabled
	legacy_sftp_systemd_exists || return 0
	! sudo_command systemctl is-active --quiet agentium-sftp.service || die "agentium-sftp.service legacy est actif"
	enabled="$(sudo_command systemctl is-enabled agentium-sftp.service 2>/dev/null || true)"
	[[ "$enabled" == "disabled" ]] || die "agentium-sftp.service legacy doit être disabled (observé: ${enabled:-inconnu})"
}

quiesce_legacy_sftp_systemd() {
	legacy_sftp_systemd_exists || return 0
	sudo_command systemctl disable --now agentium-sftp.service >/dev/null
	assert_legacy_sftp_systemd_safe
}

container_listener_bindings() {
	local service="$1"
	docker inspect --format '{{json .NetworkSettings.Ports}}' "$service" | python3 -c '
import json, sys
service = sys.argv[1]
ports = json.load(sys.stdin)
for container_binding, rows in sorted(ports.items()):
    container_port, protocol = container_binding.rsplit("/", 1)
    for row in sorted(rows or [], key=lambda item: (item.get("HostIp", ""), item.get("HostPort", ""))):
        host_port = str(row.get("HostPort", ""))
        if host_port.isdigit() and protocol in {"tcp", "udp"}:
            print("listener_binding", service, protocol, row.get("HostIp", ""), host_port, container_port, sep="\\t")
' "$service"
}

assert_internal_container_bindings_loopback() {
	local service="$1"
	shift
	local ports_json expected_csv
	ports_json="$(docker inspect --format '{{json .NetworkSettings.Ports}}' "$service")"
	expected_csv="$(IFS=,; printf '%s' "$*")"
	python3 - "$service" "$expected_csv" "$ports_json" <<'PY'
import json, sys
service, expected_raw, raw = sys.argv[1:]
expected = {f"{port}/tcp" for port in expected_raw.split(",") if port}
ports = json.loads(raw)
missing = sorted(binding for binding in expected if not ports.get(binding))
if missing:
    raise SystemExit(f"{service}: missing published loopback bindings {missing}")
for binding, rows in ports.items():
    for row in rows or []:
        if row.get("HostIp") not in {"127.0.0.1", "::1"}:
            raise SystemExit(f"{service}: {binding} is published outside loopback")
        if not str(row.get("HostPort", "")).isdigit():
            raise SystemExit(f"{service}: invalid host port for {binding}")
PY
}

assert_internal_service_bindings() {
	assert_internal_container_bindings_loopback agentium-backend 8000
	assert_internal_container_bindings_loopback agentium-frontend 8080
	assert_internal_container_bindings_loopback agentium-kc 8080
	assert_internal_container_bindings_loopback agentium-pg 5432
	assert_internal_container_bindings_loopback agentium-rabbitmq 5672 15672
	assert_internal_container_bindings_loopback qdrant 6333 6334
	assert_internal_container_bindings_loopback agentium-minio 9000 9001
}

assert_no_captured_livekit_listeners() {
	local kind service protocol _host_ip host_port _container_port rows
	while IFS=$'\t' read -r kind service protocol _host_ip host_port _container_port; do
		[[ "$kind" == "listener_binding" && "$service" == "agentium-livekit" ]] || continue
		case "$protocol" in
		tcp) rows="$(sudo_command ss -Hltpn "sport = :$host_port")" ;;
		udp) rows="$(sudo_command ss -Hlupn "sport = :$host_port")" ;;
		*) die "Protocole LiveKit capturé invalide: $protocol" ;;
		esac
		[[ -z "$rows" ]] || die "LiveKit écoute encore sur $protocol/$host_port"
	done <"$RUNTIME_STATE_FILE"
}

wait_systemd_backend_identity() {
	local expected_sha="$1" contract="${2:-exact}" attempt main_pid process_cwd
	[[ "$(git rev-parse HEAD)" == "$expected_sha" ]] || die "HEAD live différent de l'identité systemd attendue"
	case "$contract" in
	exact) assert_systemd_unit_contract ;;
	exact-frozen) assert_systemd_unit_contract; assert_systemd_env_dropin_contract ;;
	adoptable) assert_systemd_unit_adoptable ;;
	*) die "Mode de contrat systemd invalide: $contract" ;;
	esac
	for attempt in $(seq 1 30); do
		if curl --noproxy '*' -fsS --max-time 3 http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1 &&
			curl --noproxy '*' -fsS --max-time 3 http://127.0.0.1:8000/api/v1/build-info 2>/dev/null |
			python3 -c '
import json, sys
expected = sys.argv[1]
raw = sys.stdin.buffer.read(4097)
if not raw or len(raw) > 4096:
    raise SystemExit(1)
try:
    payload = json.loads(raw)
except (UnicodeDecodeError, json.JSONDecodeError):
    raise SystemExit(1)
if not isinstance(payload, dict):
    raise SystemExit(1)
if payload.get("service") != "backend" or payload.get("revision") != expected:
    raise SystemExit(1)
if payload.get("revision_verified") is not True:
    raise SystemExit(1)
' "$expected_sha"; then
			main_pid="$(sudo_command systemctl show agentium-backend.service -p MainPID --value)"
			if [[ "$main_pid" =~ ^[1-9][0-9]*$ ]]; then
				process_cwd="$(sudo_command readlink -f "/proc/$main_pid/cwd" 2>/dev/null || true)"
				[[ "$process_cwd" == "$REPO_DIR/backend" ]] && return
			fi
		fi
		sleep 2
	done
	die "Backend systemd non sain ou processus détaché du checkout $expected_sha"
}

systemd_unit_contract_hashes() {
	local canonical loopback_no_env public_no_env
	[[ -s "$FROZEN_SYSTEMD_UNIT" ]] || die "Unit systemd candidate figée absente"
	canonical="$(sha256sum "$FROZEN_SYSTEMD_UNIT" | awk '{print $1}')"
	loopback_no_env="$(sed '/^Environment=STARTUP_RECONCILIATION=disabled$/d; /^Environment=AGENTIUM_DISABLE_DOTENV=1$/d' "$FROZEN_SYSTEMD_UNIT" | sha256sum | awk '{print $1}')"
	public_no_env="$(sed '/^Environment=STARTUP_RECONCILIATION=disabled$/d; /^Environment=AGENTIUM_DISABLE_DOTENV=1$/d; s/--host 127\.0\.0\.1/--host 0.0.0.0/' "$FROZEN_SYSTEMD_UNIT" | sha256sum | awk '{print $1}')"
	printf '%s\n%s\n%s\n' "$canonical" "$loopback_no_env" "$public_no_env"
}

assert_systemd_unit_adoptable() {
	local actual_hash
	local -a allowed=()
	[[ -s "$FROZEN_SYSTEMD_UNIT" ]] || die "Unit systemd candidate figée absente"
	sudo_command test -f /etc/systemd/system/agentium-backend.service || die "Unit systemd live absente"
	sudo_command test ! -L /etc/systemd/system/agentium-backend.service || die "Unit systemd live symbolique refusée"
	actual_hash="$(sudo_command sha256sum /etc/systemd/system/agentium-backend.service | awk '{print $1}')"
	mapfile -t allowed < <(systemd_unit_contract_hashes)
	[[ "${#allowed[@]}" -eq 3 ]] || die "Inventaire des préimages systemd invalide"
	# Release A alone may adopt the historical public 0.0.0.0 preimage. Release
	# B starts only from the canonical or legacy-no-env loopback variants.
	[[ "$actual_hash" == "${allowed[0]}" || "$actual_hash" == "${allowed[1]}" ]] ||
		die "Unit systemd live non-loopback; adoption obligatoire en Release A"
}

assert_systemd_unit_contract() {
	local expected_hash actual_hash working_directory exec_start
	[[ -s "$FROZEN_SYSTEMD_UNIT" ]] || die "Unit systemd candidate figée absente"
	sudo_command test -f /etc/systemd/system/agentium-backend.service || die "Unit systemd live absente"
	sudo_command test ! -L /etc/systemd/system/agentium-backend.service || die "Unit systemd live symbolique refusée"
	expected_hash="$(sha256sum "$FROZEN_SYSTEMD_UNIT" | awk '{print $1}')"
	actual_hash="$(sudo_command sha256sum /etc/systemd/system/agentium-backend.service | awk '{print $1}')"
	[[ "$actual_hash" == "$expected_hash" ]] || die "Unit systemd live différente du blob candidat exact"
	working_directory="$(sudo_command systemctl show agentium-backend.service -p WorkingDirectory --value)"
	exec_start="$(sudo_command systemctl show agentium-backend.service -p ExecStart --value)"
	[[ "$working_directory" == "$REPO_DIR/backend" ]] || die "WorkingDirectory systemd inattendu"
	[[ "$exec_start" == *"$REPO_DIR/venv/bin/uvicorn"* && "$exec_start" == *"app.main:app"* && \
		"$exec_start" == *"--host 127.0.0.1"* && "$exec_start" == *"--port 8000"* ]] ||
		die "ExecStart systemd n'est pas la version loopback canonique"
}

adopt_systemd_unit_while_stopped() {
	[[ -x "$FROZEN_SYSTEMD_INSTALLER" ]] || die "Installer systemd candidat figé absent"
	[[ "$(systemd_backend_state)" != "active" ]] || die "Adoption systemd refusée pendant que le writer tourne"
	sudo_command env \
		AGENTIUM_BACKEND_UNIT_SOURCE="$FROZEN_SYSTEMD_UNIT" \
		AGENTIUM_BACKEND_EXPECTED_SHA="$EXPECTED_SHA" \
		AGENTIUM_SAFE_DEPLOY_ORCHESTRATED=1 AGENTIUM_SAFE_DEPLOYMENT_DIR="$DEPLOY_DIR" \
		AGENTIUM_BACKEND_ENV_FILE="$FROZEN_SYSTEMD_ENV" \
		AGENTIUM_BACKEND_ENV_DROPIN_TARGET="$SYSTEMD_ENV_DROPIN_TARGET" \
		AGENTIUM_BACKEND_ENV_DROPIN_STATE="$SYSTEMD_ENV_DROPIN_STATE" \
		AGENTIUM_BACKEND_ENV_DROPIN_BACKUP="$SYSTEMD_ENV_DROPIN_BACKUP" \
		"$FROZEN_SYSTEMD_INSTALLER" install
	[[ "$(systemd_backend_state)" != "active" ]] || die "L'installer systemd a redémarré le writer"
	assert_systemd_unit_contract
	assert_systemd_env_dropin_contract
}

assert_systemd_env_dropin_contract() {
	[[ -x "$FROZEN_SYSTEMD_INSTALLER" ]] || die "Installer systemd candidat figé absent"
	verify_runtime_env_bundle >/dev/null
	sudo_command env \
		AGENTIUM_BACKEND_UNIT_SOURCE="$FROZEN_SYSTEMD_UNIT" \
		AGENTIUM_BACKEND_EXPECTED_SHA="$EXPECTED_SHA" \
		AGENTIUM_SAFE_DEPLOYMENT_DIR="$DEPLOY_DIR" \
		AGENTIUM_BACKEND_ENV_FILE="$FROZEN_SYSTEMD_ENV" \
		AGENTIUM_BACKEND_ENV_DROPIN_TARGET="$SYSTEMD_ENV_DROPIN_TARGET" \
		AGENTIUM_BACKEND_ENV_DROPIN_STATE="$SYSTEMD_ENV_DROPIN_STATE" \
		AGENTIUM_BACKEND_ENV_DROPIN_BACKUP="$SYSTEMD_ENV_DROPIN_BACKUP" \
		"$FROZEN_SYSTEMD_INSTALLER" verify
}

restore_previous_systemd_env_dropin() {
	[[ -x "$FROZEN_SYSTEMD_INSTALLER" ]] || die "Installer systemd candidat figé absent"
	[[ -e "$SYSTEMD_ENV_DROPIN_STATE" || -L "$SYSTEMD_ENV_DROPIN_STATE" ]] || return 0
	[[ "$(systemd_backend_state)" != "active" ]] || die "Restauration drop-in refusée pendant que le writer tourne"
	sudo_command env \
		AGENTIUM_BACKEND_UNIT_SOURCE="$FROZEN_SYSTEMD_UNIT" \
		AGENTIUM_BACKEND_EXPECTED_SHA="$EXPECTED_SHA" \
		AGENTIUM_SAFE_DEPLOY_ORCHESTRATED=1 AGENTIUM_SAFE_DEPLOYMENT_DIR="$DEPLOY_DIR" \
		AGENTIUM_BACKEND_ENV_FILE="$FROZEN_SYSTEMD_ENV" \
		AGENTIUM_BACKEND_ENV_DROPIN_TARGET="$SYSTEMD_ENV_DROPIN_TARGET" \
		AGENTIUM_BACKEND_ENV_DROPIN_STATE="$SYSTEMD_ENV_DROPIN_STATE" \
		AGENTIUM_BACKEND_ENV_DROPIN_BACKUP="$SYSTEMD_ENV_DROPIN_BACKUP" \
		"$FROZEN_SYSTEMD_INSTALLER" restore-env
}

assert_known_public_writer_listeners() {
	local state running sftp_port
	state="$(systemd_backend_state)"
	if [[ "$state" == "active" ]]; then
		[[ -n "$(tcp_listener_rows 8000)" ]] || die "agentium-backend.service actif sans listener TCP/8000"
		assert_tcp_listener_loopback_only 8000 "Backend systemd Release A"
		wait_systemd_backend_identity "$(git rev-parse HEAD)" adoptable
	else
		assert_no_tcp_listener 8000 "Writer backend inattendu"
	fi
	running="$(docker inspect --format '{{.State.Running}}' agentium-livekit 2>/dev/null || printf false)"
	if [[ "$running" == "true" ]]; then
		[[ "$(docker inspect --format '{{.State.Paused}}' agentium-livekit)" == "false" ]] || die "LiveKit est déjà en pause avant preflight"
		[[ -n "$(tcp_listener_rows 7881)" ]] || die "LiveKit actif sans listener TCP/7881"
	else
		assert_no_tcp_listener 7881 "Writer LiveKit inattendu"
	fi
	running="$(docker inspect --format '{{.State.Running}}' agentium-sftp 2>/dev/null || printf false)"
	sftp_port="$(sftp_host_port)"
	if [[ "$running" == "true" ]]; then
		[[ "$(docker inspect --format '{{.State.Paused}}' agentium-sftp)" == "false" ]] || die "SFTP est déjà en pause avant preflight"
		[[ "$sftp_port" =~ ^[0-9]+$ ]] || die "SFTP actif sans listener publié"
		[[ -n "$(tcp_listener_rows "$sftp_port")" ]] || die "SFTP actif sans listener TCP/$sftp_port"
	elif [[ "$sftp_port" =~ ^[0-9]+$ ]]; then
		assert_no_tcp_listener "$sftp_port" "Writer SFTP inattendu"
	fi
}

gate() {
	local action="$1" purpose=""
	[[ -x "$MAINTENANCE_HELPER" ]] || die "Helper de maintenance figé absent: $MAINTENANCE_HELPER"
	if [[ "$action" == "exit" ]]; then
		case "$(phase)" in opening_forward) purpose=forward-open ;; rollback_opening) purpose=rollback-open ;; *) die "Phase non autorisée pour ouvrir le gate" ;; esac
	fi
	OMNIRAG_REPO_DIR="$REPO_DIR" \
		AGENTIUM_SAFE_DEPLOY_ORCHESTRATED=1 \
		AGENTIUM_SAFE_DEPLOYMENT_DIR="$DEPLOY_DIR" \
		AGENTIUM_SAFE_DEPLOYMENT_ID="$DEPLOYMENT_ID" \
		AGENTIUM_SAFE_GATE_PURPOSE="$purpose" \
		"$MAINTENANCE_HELPER" "$action"
}

stage_candidate_helpers() {
	local source target temporary expected_blob actual_blob
	while IFS=$'\t' read -r source target; do
		expected_blob="$(git rev-parse "${EXPECTED_SHA}:${source}")" || die "Helper candidat absent: $source"
		if [[ -f "$target" ]]; then
			actual_blob="$(git hash-object "$target")"
			[[ "$actual_blob" == "$expected_blob" ]] || die "Helper figé différent du SHA candidat: $target"
			chmod 0700 "$target"
			continue
		fi
		temporary="$DEPLOY_DIR/.${target##*/}.$$"
		(umask 077; git show "${EXPECTED_SHA}:${source}" >"$temporary")
		[[ "$(git hash-object "$temporary")" == "$expected_blob" ]] || die "Extraction Git altérée pour $source"
		if ln "$temporary" "$target" 2>/dev/null; then rm -f "$temporary"; else rm -f "$temporary"; die "Helper créé concurremment: $target"; fi
		chmod 0700 "$target"
	done <<EOF
scripts/deploy-agentium-safe.sh	$FROZEN_ORCHESTRATOR
scripts/agentium_runtime_env_bundle.py	$ENV_BUNDLE_HELPER
scripts/agentium-maintenance-gate.sh	$MAINTENANCE_HELPER
scripts/agentium_storage_attestation.py	$STORAGE_HELPER
scripts/agentium_safe_validation.py	$VALIDATION_HELPER
scripts/agentium_release_a_attestation.py	$RELEASE_A_HELPER
scripts/deploy-vm.sh	$FROZEN_DEPLOYER
deploy/nginx/agentium-container-frontend.conf	$FROZEN_NGINX_SITE
deploy/nginx/agentium-deploy-maintenance.conf	$FROZEN_NGINX_SNIPPET
deploy/agentium-backend.service	$FROZEN_SYSTEMD_UNIT
deploy/install-backend-service.sh	$FROZEN_SYSTEMD_INSTALLER
backend/scripts/audit_qdrant_write_barrier.py	$QDRANT_BARRIER_HELPER
backend/scripts/audit_sftp_deploy_boundary.py	$SFTP_BOUNDARY_HELPER
docker/compose.agentium.qdrant-barrier.yml	$FROZEN_QDRANT_OVERRIDE
docker/compose.agentium.opened.yml	$FROZEN_OPENED_OVERRIDE
EOF
}

ensure_container_unpaused() {
	local service="$1"
	if docker inspect "$service" >/dev/null 2>&1 &&
		[[ "$(docker inspect --format '{{.State.Paused}}' "$service")" == "true" ]]; then
		docker unpause "$service" >/dev/null
	fi
}

container_restart_policy() {
	local service="$1"
	docker inspect --format '{{.HostConfig.RestartPolicy.Name}}\t{{.HostConfig.RestartPolicy.MaximumRetryCount}}' "$service"
}

historical_application_restart_policy() {
	local service="$1"
	awk -F '\t' -v service="$service" '$1 == "restart_policy" && $2 == service { print $3 "\t" $4; exit }' "$ROLLBACK_STATE"
}

set_application_restart_policies_no() {
	local service
	for service in agentium-backend agentium-worker-cpu agentium-p4-maintenance; do
		docker inspect "$service" >/dev/null 2>&1 || continue
		docker update --restart=no "$service" >/dev/null
		[[ "$(container_restart_policy "$service")" == $'no\t0' ]] || die "$service peut redémarrer pendant la transaction"
	done
}

restore_application_restart_policies() {
	local service expected name maximum policy
	for service in agentium-backend agentium-worker-cpu agentium-p4-maintenance; do
		docker inspect "$service" >/dev/null 2>&1 || continue
		expected="$(historical_application_restart_policy "$service")"
		IFS=$'\t' read -r name maximum <<<"$expected"
		case "$name" in
		no | always | unless-stopped) [[ "$maximum" == "0" ]] || die "Policy historique incohérente pour $service"; policy="$name" ;;
		on-failure) [[ "$maximum" =~ ^[0-9]+$ ]] || die "Policy historique incohérente pour $service"; [[ "$maximum" == "0" ]] && policy=on-failure || policy="on-failure:$maximum" ;;
		*) die "Policy historique absente/invalide pour $service" ;;
		esac
		docker update --restart="$policy" "$service" >/dev/null
		[[ "$(container_restart_policy "$service")" == "$expected" ]] || die "Policy historique non restaurée pour $service"
	done
}

historical_sftp_restart_policy() {
	awk -F '\t' '$1 == "restart_policy" && $2 == "agentium-sftp" { print $3 "\t" $4; exit }' "$ROLLBACK_STATE"
}

assert_sftp_restart_policy_no() {
	local observed
	observed="$(container_restart_policy agentium-sftp)"
	[[ "$observed" == $'no\t0' ]] || die "SFTP doit rester en restart=no pendant la transaction (observé: $observed)"
}

set_sftp_restart_policy_no() {
	docker inspect agentium-sftp >/dev/null 2>&1 || die "Conteneur SFTP requis absent"
	docker update --restart=no agentium-sftp >/dev/null
	assert_sftp_restart_policy_no
}

assert_sftp_restart_policy_matches_capture() {
	local expected observed
	expected="$(historical_sftp_restart_policy)"
	[[ -n "$expected" && "$expected" != $'absent\t-' ]] || die "Policy SFTP historique absente du rollback v3"
	observed="$(container_restart_policy agentium-sftp)"
	[[ "$observed" == "$expected" ]] || die "Policy SFTP modifiée depuis la préparation"
}

restore_sftp_restart_policy() {
	local expected name maximum policy observed
	expected="$(historical_sftp_restart_policy)"
	IFS=$'\t' read -r name maximum <<<"$expected"
	case "$name" in
	no | always | unless-stopped) [[ "$maximum" == "0" ]] || die "Policy SFTP historique incohérente"; policy="$name" ;;
	on-failure)
		[[ "$maximum" =~ ^[0-9]+$ ]] || die "Policy SFTP historique incohérente"
		if [[ "$maximum" == "0" ]]; then policy=on-failure; else policy="on-failure:$maximum"; fi
		;;
	*) die "Policy SFTP historique invalide: $name" ;;
	esac
	docker update --restart="$policy" agentium-sftp >/dev/null
	observed="$(container_restart_policy agentium-sftp)"
	[[ "$observed" == "$expected" ]] || die "Restauration exacte de la policy SFTP impossible"
}

historical_runtime_restart_policy() {
	local service="$1"
	awk -F '\t' -v service="$service" '$1 == "runtime_restart_policy" && $2 == service { print $3 "\t" $4; exit }' "$RUNTIME_STATE_FILE"
}

set_realtime_restart_policies_no() {
	local service observed
	for service in agentium-livekit agentium-livekit-agent agentium-kc; do
		docker inspect "$service" >/dev/null 2>&1 || continue
		docker update --restart=no "$service" >/dev/null
		observed="$(container_restart_policy "$service")"
		[[ "$observed" == $'no\t0' ]] || die "$service doit rester en restart=no pendant la transaction"
	done
}

restore_realtime_restart_policies() {
	local service expected name maximum policy observed
	for service in agentium-livekit agentium-livekit-agent agentium-kc; do
		expected="$(historical_runtime_restart_policy "$service")"
		IFS=$'\t' read -r name maximum <<<"$expected"
		if [[ "$name" == "absent" && "$maximum" == "-" ]]; then
			! docker inspect "$service" >/dev/null 2>&1 || die "$service devait rester absent"
			continue
		fi
		case "$name" in
		no | always | unless-stopped) [[ "$maximum" == "0" ]] || die "Policy historique incohérente pour $service"; policy="$name" ;;
		on-failure)
			[[ "$maximum" =~ ^[0-9]+$ ]] || die "Policy historique incohérente pour $service"
			if [[ "$maximum" == "0" ]]; then policy=on-failure; else policy="on-failure:$maximum"; fi
			;;
		*) die "Policy historique invalide pour $service" ;;
		esac
		docker update --restart="$policy" "$service" >/dev/null
		observed="$(container_restart_policy "$service")"
		[[ "$observed" == "$expected" ]] || die "Policy de restart non restaurée pour $service"
	done
}

secure_deposit_mode() {
	local options
	options="$(findmnt -n -o OPTIONS --target "$SECURE_DEPOSIT_PATH")"
	if [[ ",$options," == *,ro,* ]]; then printf 'ro\n'; else printf 'rw\n'; fi
}

set_secure_deposit_mode() {
	local mode="$1" target
	[[ "$mode" == "ro" || "$mode" == "rw" ]] || die "Mode Secure Deposit invalide"
	target="$(findmnt -n -o TARGET --target "$SECURE_DEPOSIT_PATH")"
	[[ "$target" == "$SECURE_DEPOSIT_PATH" ]] || die "Secure Deposit doit être un mountpoint autonome avant remount"
	[[ "$(secure_deposit_mode)" == "$mode" ]] && return
	[[ "$mode" != "ro" ]] || sync -f "$SECURE_DEPOSIT_PATH"
	sudo_command mount -o "remount,$mode" "$SECURE_DEPOSIT_PATH"
	[[ "$(secure_deposit_mode)" == "$mode" ]] || die "Remount Secure Deposit $mode non effectif"
}

requiesce_validation_runtime() {
	local service
	if [[ "$(gate status 2>/dev/null)" == "open" ]]; then gate enter || return 1; fi
	enter_sftp_ingress_gate || return 1
	enter_livekit_ingress_gate || return 1
	set_sftp_restart_policy_no || return 1
	set_realtime_restart_policies_no || return 1
	quiesce_legacy_sftp_systemd || return 1
	sudo_command systemctl stop agentium-backend.service >/dev/null 2>&1 || true
	assert_no_tcp_listener 8000 "Backend systemd" || return 1
	for service in agentium-livekit-agent agentium-livekit agentium-sftp agentium-p4-maintenance; do
		if docker inspect "$service" >/dev/null 2>&1; then
			ensure_container_unpaused "$service" || return 1
			docker stop --time 30 "$service" >/dev/null 2>&1 || return 1
		fi
	done
	assert_no_tcp_listener 7881 "LiveKit" || return 1
	assert_no_captured_livekit_listeners || return 1
	AGENTIUM_CELERY_BEAT=0 AGENTIUM_PIN_CANDIDATE_IMAGES=1 \
		compose up -d --no-build --force-recreate agentium-worker-cpu >/dev/null || return 1
	assert_candidate_container_image agentium-worker-cpu || return 1
	assert_worker_scheduler_mode 0 || return 1
	set_secure_deposit_mode ro || return 1
}

requiesce_partial_candidate() {
	local service
	# phase=migrated can hide a failed activation after one or more candidate
	# containers started. Re-establish the complete writer barrier without
	# changing the database, candidate checkout, phase, or frontend container.
	if [[ "$(gate status 2>/dev/null)" == "open" ]]; then gate enter || return 1; fi
	[[ "$(gate status 2>/dev/null)" == "closed" ]] || return 1
	enter_systemd_backend_ingress_gate || return 1
	enter_sftp_ingress_gate || return 1
	enter_livekit_ingress_gate || return 1
	disable_systemd_backend_restart || return 1
	set_application_restart_policies_no || return 1
	set_sftp_restart_policy_no || return 1
	set_realtime_restart_policies_no || return 1
	quiesce_legacy_sftp_systemd || return 1
	sudo_command systemctl stop agentium-backend.service >/dev/null 2>&1 || true
	assert_no_tcp_listener 8000 "Backend systemd" || return 1
	for service in agentium-livekit-agent agentium-livekit agentium-sftp agentium-p4-maintenance agentium-backend agentium-worker-cpu; do
		if docker inspect "$service" >/dev/null 2>&1; then
			ensure_container_unpaused "$service" || return 1
			if [[ "$(docker inspect --format '{{.State.Running}}' "$service")" == "true" ]]; then
				docker stop --time 45 "$service" >/dev/null 2>&1 || return 1
			fi
		fi
	done
	assert_no_tcp_listener 7881 "LiveKit" || return 1
	assert_no_captured_livekit_listeners || return 1
	for service in agentium-livekit-agent agentium-livekit agentium-sftp agentium-p4-maintenance agentium-backend agentium-worker-cpu; do
		[[ "$(docker inspect --format '{{.State.Running}}' "$service" 2>/dev/null || printf false)" == "false" ]] || return 1
	done
	set_secure_deposit_mode ro || return 1
	[[ "$(phase)" == "migrated" ]]
}

invalidate_quiesced_artifacts() {
	local destination path timestamp
	local -a stale_paths=(
		"$DEPLOY_DIR/postgres-quiesced.dump"
		"$DEPLOY_DIR/postgres-quiesced.dump.sha256"
		"$DEPLOY_DIR/postgres-quiesced.dump.ready"
		"$STORAGE_QUIESCED"
		"$STORAGE_AFTER"
		"$STORAGE_COMPARISON"
		"$STORAGE_POST_CANARY"
		"$STORAGE_CANARY_COMPARISON"
		"$DATABASE_CANARY_BASELINE"
		"$DATABASE_POST_CANARY_INVENTORY"
		"$DATABASE_FINAL_CANARY_INVENTORY"
		"$DATABASE_POST_CANARY_COMPARISON"
		"$DATABASE_OPENING_RECAPTURE"
		"$DATABASE_OPENING_COMPARISON"
		"$WORKSPACE_APP_DRY_RUN"
		"$WORKSPACE_APP_APPLY"
		"$WORKSPACE_APP_POST"
		"$DEPLOY_DIR/rabbitmq-quiesced.json"
		"$DEPLOY_DIR/rabbitmq-candidate.json"
		"$DEPLOY_DIR/rabbitmq-validation.json"
		"$DEPLOY_DIR/rehearsal-quiesced-alembic-current.txt"
		"$DEPLOY_DIR/rehearsal-quiesced-bindings.json"
		"$DEPLOY_DIR/database-quiesced-all-baseline.tsv"
		"$DEPLOY_DIR/database-post-migration-all.tsv"
		"$DEPLOY_DIR/database-post-activation-all.tsv"
		"$DEPLOY_DIR/database-startup-comparison.json"
		"$DEPLOY_DIR/post-migration-bindings.json"
		"$DEPLOY_DIR/post-activation-bindings.json"
		"$DEPLOY_DIR/live-writer-quiescence.json"
		"$DEPLOY_DIR/candidate-database-revision"
		"$DEPLOY_DIR/alembic-current.txt"
		"$DEPLOY_DIR/alembic-heads.txt"
		"$DEPLOY_DIR/post-activation-bindings.json"
		"$DEPLOY_DIR/validation.json"
		"$DEPLOY_DIR/validation-artifact.sha256"
		"$DEPLOY_DIR/proofs"
	)
	timestamp="$(date -u +%Y%m%dT%H%M%SZ)-$$"
	destination="$DEPLOY_DIR/abandoned/$timestamp"
	for path in "${stale_paths[@]}"; do
		[[ -e "$path" || -L "$path" ]] || continue
		mkdir -p "$destination"
		chmod 0700 "$DEPLOY_DIR/abandoned" "$destination"
		mv -- "$path" "$destination/${path##*/}"
	done
	python3 - "$DEPLOY_DIR" "$DEPLOY_DIR/abandoned" "$destination" <<'PY'
import os
import sys
from pathlib import Path

for raw in sys.argv[1:]:
    path = Path(raw)
    if not path.is_dir() or path.is_symlink():
        continue
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
PY
}

restore_systemd_backend_state() {
	local expected_sha="$1" env_contract="${2:-frozen}" desired wait_contract="exact-frozen"
	[[ "$env_contract" == "frozen" || "$env_contract" == "restored" ]] || die "Contrat env systemd invalide"
	[[ "$env_contract" == "frozen" ]] || wait_contract="exact"
	desired="$(historical_systemd_state)"
	case "$desired" in
	active)
		[[ "$(git rev-parse HEAD)" == "$expected_sha" ]] || die "Checkout incohérent avant reprise du backend systemd"
		sudo_command systemctl start agentium-backend.service
		wait_systemd_backend_identity "$expected_sha" "$wait_contract"
		assert_tcp_listener_loopback_only 8000 "agentium-backend.service restauré"
		;;
	stopped)
		sudo_command systemctl stop agentium-backend.service >/dev/null 2>&1 || true
		[[ "$(systemd_backend_state)" == "stopped" ]] || die "Backend systemd devait rester arrêté"
		assert_no_tcp_listener 8000 "Backend systemd arrêté"
		;;
	absent)
		[[ "$(systemd_backend_state)" == "absent" ]] || die "Backend systemd apparu pendant le déploiement"
		assert_no_tcp_listener 8000 "Backend systemd absent"
		;;
	*) die "État historique systemd invalide: $desired" ;;
	esac
}

current_database_revision() {
	docker exec agentium-pg psql -v ON_ERROR_STOP=1 \
		-U "$POSTGRES_USER" -d "$POSTGRES_DB" \
		-Atqc 'SELECT version_num FROM alembic_version ORDER BY version_num'
}

recover_prepared_barrier_failure() {
	local expected actual service desired expected_image all_ok=1
	[[ "$(phase)" == "prepared" ]] || return 1
	[[ -f "$METADATA_FILE" && -f "$ROLLBACK_STATE" && -f "$RUNTIME_STATE_FILE" && -x "$MAINTENANCE_HELPER" ]] || return 1
	if [[ "$(gate status 2>/dev/null)" == "open" ]]; then gate enter || return 1; fi
	[[ "$(gate status 2>/dev/null)" == "closed" ]] || return 1
	# Keep every public ingress closed while a reboot-interrupted, partially
	# armed restart barrier is restored. No database, checkout, unit or mount
	# mutation is allowed before this recovery has completed.
	enter_systemd_backend_ingress_gate || return 1
	enter_sftp_ingress_gate || return 1
	enter_livekit_ingress_gate || return 1
	expected="$(metadata previous_database_revision)"
	actual="$(docker exec agentium-pg psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc \
		'SELECT version_num FROM alembic_version ORDER BY version_num' 2>/dev/null || true)"
	[[ "$actual" == "$expected" ]] || return 1
	[[ "$(git rev-parse HEAD 2>/dev/null)" == "$(metadata previous_sha)" ]] || return 1
	[[ "$(secure_deposit_mode)" == "rw" ]] || return 1
	for service in agentium-backend agentium-frontend agentium-worker-cpu agentium-p4-maintenance agentium-sftp agentium-livekit agentium-livekit-agent agentium-kc; do
		desired="$(historical_runtime_state "$service")"
		if [[ "$desired" != "absent" ]]; then
			case "$service" in
			agentium-livekit | agentium-livekit-agent | agentium-kc)
				expected_image="$(awk -F '\t' -v service="$service" '$1 == "runtime_state" && $2 == service { print $4; exit }' "$RUNTIME_STATE_FILE")"
				;;
			*) expected_image="$(awk -F '\t' -v service="$service" '$1 == "service" && $2 == service { print $3; exit }' "$ROLLBACK_STATE")" ;;
			esac
			[[ "$(docker inspect --format '{{.Image}}' "$service" 2>/dev/null)" == "$expected_image" ]] || return 1
		fi
	done
	for service in agentium-backend agentium-frontend agentium-worker-cpu agentium-p4-maintenance agentium-sftp agentium-livekit agentium-livekit-agent agentium-kc; do
		desired="$(historical_runtime_state "$service")"
		case "$desired" in
		running) ensure_container_unpaused "$service" || all_ok=0; docker start "$service" >/dev/null 2>&1 || all_ok=0 ;;
		stopped) ensure_container_unpaused "$service" || all_ok=0; docker stop --time 30 "$service" >/dev/null 2>&1 || true ;;
		absent) docker rm -f "$service" >/dev/null 2>&1 || true ;;
		*) all_ok=0 ;;
		esac
	done
	[[ "$all_ok" -eq 1 ]] || return 1
	restore_systemd_backend_state "$(metadata previous_sha)" restored >/dev/null 2>&1 || return 1
	restore_application_restart_policies >/dev/null 2>&1 || return 1
	restore_realtime_restart_policies >/dev/null 2>&1 || return 1
	restore_sftp_restart_policy >/dev/null 2>&1 || return 1
	restore_systemd_backend_unit_file_state >/dev/null 2>&1 || return 1
	assert_runtime_state_matches_capture || return 1
	leave_systemd_backend_ingress_gate >/dev/null 2>&1 || return 1
	leave_livekit_ingress_gate >/dev/null 2>&1 || return 1
	leave_sftp_ingress_gate >/dev/null 2>&1 || return 1
	OMNIRAG_REPO_DIR="$REPO_DIR" \
		AGENTIUM_SAFE_DEPLOY_ORCHESTRATED=1 \
		AGENTIUM_SAFE_DEPLOYMENT_DIR="$DEPLOY_DIR" \
		AGENTIUM_SAFE_DEPLOYMENT_ID="$DEPLOYMENT_ID" \
		AGENTIUM_SAFE_GATE_PURPOSE=pre-closing-recover \
		"$MAINTENANCE_HELPER" exit >/dev/null 2>&1 || return 1
	[[ "$(OMNIRAG_REPO_DIR="$REPO_DIR" "$MAINTENANCE_HELPER" status 2>/dev/null)" == "open" ]] || return 1
	[[ "$(phase)" == "prepared" ]]
}

recover_pre_migration_failure() {
	local expected actual service desired expected_image all_ok=1
	[[ -f "$METADATA_FILE" && -f "$ROLLBACK_STATE" && -x "$MAINTENANCE_HELPER" ]] || return 1
	if [[ "$(gate status 2>/dev/null)" == "open" ]]; then gate enter || return 1; fi
	[[ "$(gate status 2>/dev/null)" == "closed" ]] || return 1
	enter_sftp_ingress_gate || return 1
	enter_livekit_ingress_gate || return 1
	set_sftp_restart_policy_no || return 1
	set_realtime_restart_policies_no || return 1
	quiesce_legacy_sftp_systemd || return 1
	expected="$(metadata previous_database_revision)"
	actual="$(docker exec agentium-pg psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc \
		'SELECT version_num FROM alembic_version ORDER BY version_num' 2>/dev/null || true)"
	[[ "$actual" == "$expected" ]] || return 1
	git reset --hard "$(metadata previous_sha)" >/dev/null 2>&1 || return 1
	[[ "$(git rev-parse HEAD 2>/dev/null)" == "$(metadata previous_sha)" ]] || return 1
	# Quarantine every quiesced proof before any historical writer can restart.
	# A crash after this point therefore forces a fresh dump/snapshot instead of
	# reusing evidence captured before newly accepted writes.
	invalidate_quiesced_artifacts || return 1
	set_phase recovering_pre_migration
	sudo_command systemctl stop agentium-backend.service >/dev/null 2>&1 || true
	assert_systemd_unit_contract || return 1
	restore_previous_systemd_env_dropin || return 1
	previous_systemd_runtime_supports_frozen_dotenv || return 1
	set_secure_deposit_mode rw || return 1
	for service in agentium-backend agentium-frontend agentium-worker-cpu agentium-p4-maintenance agentium-sftp agentium-livekit agentium-livekit-agent agentium-kc; do
		desired="$(historical_runtime_state "$service")"
		if [[ "$desired" != "absent" ]]; then
			case "$service" in
			agentium-livekit | agentium-livekit-agent | agentium-kc)
				expected_image="$(awk -F '\t' -v service="$service" '$1 == "runtime_state" && $2 == service { print $4; exit }' "$RUNTIME_STATE_FILE")"
				;;
			*) expected_image="$(awk -F '\t' -v service="$service" '$1 == "service" && $2 == service { print $3; exit }' "$ROLLBACK_STATE")" ;;
			esac
			[[ "$(docker inspect --format '{{.Image}}' "$service" 2>/dev/null)" == "$expected_image" ]] || return 1
		fi
	done
	for service in agentium-backend agentium-frontend agentium-worker-cpu agentium-p4-maintenance agentium-sftp agentium-livekit agentium-livekit-agent agentium-kc; do
		desired="$(historical_runtime_state "$service")"
		case "$desired" in
		running) ensure_container_unpaused "$service" || all_ok=0; docker start "$service" >/dev/null 2>&1 || all_ok=0 ;;
		stopped) ensure_container_unpaused "$service" || all_ok=0; docker stop --time 30 "$service" >/dev/null 2>&1 || true ;;
		absent) docker rm -f "$service" >/dev/null 2>&1 || true ;;
		*) all_ok=0 ;;
		esac
	done
	for service in agentium-backend agentium-frontend agentium-worker-cpu agentium-p4-maintenance agentium-sftp agentium-livekit agentium-livekit-agent agentium-kc; do
		desired="$(historical_runtime_state "$service")"
		case "$desired" in
		running) [[ "$(docker inspect --format '{{.State.Running}}' "$service" 2>/dev/null)" == "true" ]] || all_ok=0 ;;
		stopped) [[ "$(docker inspect --format '{{.State.Running}}' "$service" 2>/dev/null || printf false)" == "false" ]] || all_ok=0 ;;
		absent) ! docker inspect "$service" >/dev/null 2>&1 || all_ok=0 ;;
		*) all_ok=0 ;;
		esac
	done
	[[ "$all_ok" -eq 1 ]] || return 1
	restore_systemd_backend_state "$(metadata previous_sha)" >/dev/null 2>&1 || return 1
	restore_application_restart_policies >/dev/null 2>&1 || return 1
	restore_systemd_backend_unit_file_state >/dev/null 2>&1 || return 1
	assert_systemd_unit_contract || return 1
	leave_systemd_backend_ingress_gate >/dev/null 2>&1 || return 1
	leave_livekit_ingress_gate >/dev/null 2>&1 || return 1
	restore_realtime_restart_policies >/dev/null 2>&1 || return 1
	leave_sftp_ingress_gate >/dev/null 2>&1 || return 1
	restore_sftp_restart_policy >/dev/null 2>&1 || return 1
	OMNIRAG_REPO_DIR="$REPO_DIR" \
		AGENTIUM_SAFE_DEPLOY_ORCHESTRATED=1 \
		AGENTIUM_SAFE_DEPLOYMENT_DIR="$DEPLOY_DIR" \
		AGENTIUM_SAFE_DEPLOYMENT_ID="$DEPLOYMENT_ID" \
		AGENTIUM_SAFE_GATE_PURPOSE=pre-migration-recover \
		"$MAINTENANCE_HELPER" exit >/dev/null 2>&1 || return 1
	[[ "$(OMNIRAG_REPO_DIR="$REPO_DIR" "$MAINTENANCE_HELPER" status 2>/dev/null)" == "open" ]] || return 1
	set_phase prepared
	return 0
}

historical_runtime_state() {
	local service="$1"
	case "$service" in
	agentium-livekit | agentium-livekit-agent | agentium-kc)
		awk -F '\t' -v service="$service" '$1 == "runtime_state" && $2 == service { print $3; exit }' "$RUNTIME_STATE_FILE"
		;;
	*)
		awk -F '\t' -v service="$service" '$1 == "container_state" && $2 == service { print $3; exit }' "$ROLLBACK_STATE"
		;;
	esac
}

historical_systemd_state() {
	awk -F '\t' '$1 == "systemd_state" && $2 == "agentium-backend.service" { print $3; exit }' "$RUNTIME_STATE_FILE"
}

historical_systemd_unit_file_state() {
	awk -F '\t' '$1 == "systemd_unit_file_state" && $2 == "agentium-backend.service" { print $3; exit }' "$RUNTIME_STATE_FILE"
}

disable_systemd_backend_restart() {
	local state
	state="$(sudo_command systemctl is-enabled agentium-backend.service 2>/dev/null || true)"
	case "$state" in enabled) sudo_command systemctl disable agentium-backend.service >/dev/null ;; disabled) ;; *) die "État enable systemd non supporté: $state" ;; esac
	[[ "$(sudo_command systemctl is-enabled agentium-backend.service 2>/dev/null || true)" == "disabled" ]] ||
		die "agentium-backend.service reste activé au reboot"
}

restore_systemd_backend_unit_file_state() {
	local desired
	desired="$(historical_systemd_unit_file_state)"
	case "$desired" in
	enabled) sudo_command systemctl enable agentium-backend.service >/dev/null ;;
	disabled) sudo_command systemctl disable agentium-backend.service >/dev/null ;;
	*) die "État enable systemd historique invalide: $desired" ;;
	esac
	[[ "$(sudo_command systemctl is-enabled agentium-backend.service 2>/dev/null || true)" == "$desired" ]] ||
		die "État enable systemd non restauré"
}

assert_runtime_state_matches_capture() {
	local service expected observed expected_image
	for service in agentium-livekit agentium-livekit-agent agentium-kc; do
		expected="$(historical_runtime_state "$service")"
		if docker inspect "$service" >/dev/null 2>&1; then
			if [[ "$(docker inspect --format '{{.State.Running}}' "$service")" == "true" ]]; then observed=running; else observed=stopped; fi
			expected_image="$(awk -F '\t' -v service="$service" '$1 == "runtime_state" && $2 == service { print $4; exit }' "$RUNTIME_STATE_FILE")"
			[[ "$(docker inspect --format '{{.Image}}' "$service")" == "$expected_image" ]] || die "$service a changé d'image depuis le preflight"
			[[ "$(container_restart_policy "$service")" == "$(historical_runtime_restart_policy "$service")" ]] || die "$service a changé de policy restart depuis le preflight"
		else
			observed=absent
		fi
		[[ "$observed" == "$expected" ]] || die "$service a changé d'état depuis le preflight"
	done
	[[ "$(systemd_backend_state)" == "$(historical_systemd_state)" ]] || die "agentium-backend.service a changé d'état depuis le preflight"
}

active_application_sha() {
	local service image revision common=""
	for service in agentium-backend agentium-frontend agentium-worker-cpu; do
		image="$(docker inspect --format '{{.Image}}' "$service")"
		revision="$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$image")"
		[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || die "Révision OCI invalide pour $service"
		[[ -z "$common" || "$revision" == "$common" ]] || die "Les services principaux ne partagent pas le même SHA"
		common="$revision"
	done
	printf '%s\n' "$common"
}

available_bytes() { df -B1 --output=avail "$1" | awk 'NR == 2 { print $1 }'; }
total_bytes() { df -B1 --output=size "$1" | awk 'NR == 2 { print $1 }'; }
device_id() { stat -c '%d' "$1"; }
privileged_device_id() { sudo_command stat -c '%d' "$1"; }

container_mount_source() {
	local container="$1" destination="$2"
	docker inspect --format "{{range .Mounts}}{{if eq .Destination \"$destination\"}}{{.Source}}{{end}}{{end}}" "$container"
}

assert_container_mount_device() {
	local container="$1" destination="$2" expected_device="$3" source observed
	source="$(container_mount_source "$container" "$destination")"
	[[ -n "$source" ]] || die "$container ne monte pas $destination"
	sudo_command test -e "$source" || die "Source de montage absente pour $container:$destination"
	observed="$(privileged_device_id "$source")"
	[[ "$observed" == "$expected_device" ]] || die "$container:$destination est sur le mauvais filesystem"
}

assert_rw_mount() {
	local path="$1" options
	options="$(findmnt -n -o OPTIONS --target "$path")"
	[[ ",$options," == *,rw,* ]] || die "$path n'est pas monté en lecture/écriture"
}

assert_inode_margin() {
	local path="$1" total free
	read -r total free < <(df -Pi --output=itotal,iavail "$path" | awk 'NR == 2 { print $1, $2 }')
	[[ "$total" =~ ^[0-9]+$ && "$free" =~ ^[0-9]+$ && "$total" -gt 0 ]] || die "Inodes illisibles pour $path"
	(( free * 100 >= total * 10 )) || die "$path a moins de 10% d'inodes libres"
}

resolve_runtime_paths() {
	local configured application_bucket live_faiss live_object_store
	configured="$(read_env_value AGENTIUM_SECURE_DEPOSIT_PATH)"
	[[ "$configured" == /* && "$configured" != *..* ]] || die "Chemin Secure Deposit explicite invalide"
	SECURE_DEPOSIT_PATH="$configured"
	configured="$(read_env_value AGENTIUM_OBJECT_STORE_PATH)"
	[[ "$configured" == /* && "$configured" != *..* ]] || die "Chemin ObjectStore explicite invalide"
	OBJECT_STORE_PATH="$configured"
	configured="$(read_env_value AGENTIUM_FAISS_PATH)"
	[[ "$configured" == /* && "$configured" != *..* ]] || die "Chemin FAISS explicite invalide"
	FAISS_PATH="$configured"
	configured="$(read_env_value AGENTIUM_QDRANT_ENV_FILE)"
	[[ "$configured" == "$ENV_BUNDLE_DIR"/* ]] || die "Env Qdrant hors bundle figé"
	QDRANT_ENV_PATH="$configured"
	configured="$(read_env_value AGENTIUM_ENV_FILE)"
	[[ "$configured" == "$ENV_BUNDLE_DIR"/* ]] || die "Env applicatif hors bundle figé"
	APPLICATION_ENV_PATH="$configured"
	MINIO_BUCKET="$(read_env_value AGENTIUM_MINIO_BUCKET)"
	MINIO_BUCKET="${MINIO_BUCKET:-agentium-artifacts}"
	MINIO_API_PORT="$(read_env_value AGENTIUM_MINIO_API_PORT)"
	MINIO_API_PORT="${MINIO_API_PORT:-9000}"
	POSTGRES_DB="$(read_env_value AGENTIUM_POSTGRES_DB)"
	POSTGRES_USER="$(read_env_value AGENTIUM_POSTGRES_USER)"
	IMAGE_TAG="$(read_env_value AGENTIUM_IMAGE_TAG)"
	DOCKER_NETWORK="$(read_env_value AGENTIUM_DOCKER_NETWORK)"
	POSTGRES_DB="${POSTGRES_DB:-agentium}"
	POSTGRES_USER="${POSTGRES_USER:-agentium}"
	IMAGE_TAG="${IMAGE_TAG:-local}"
	DOCKER_NETWORK="${DOCKER_NETWORK:-agentium-net}"
	# A crash can leave the backend container absent while the durable
	# transaction still has to reconcile. Resolve storage from the frozen env,
	# then cross-check the live mount whenever the container exists.
	live_object_store="$(container_mount_source agentium-backend /data/object_store 2>/dev/null || true)"
	[[ -z "$live_object_store" || "$live_object_store" == "$OBJECT_STORE_PATH" ]] ||
		die "Le montage ObjectStore live diverge du bundle figé"
	live_faiss="$(container_mount_source agentium-backend /data/faiss_db 2>/dev/null || true)"
	[[ -z "$live_faiss" || "$live_faiss" == "$FAISS_PATH" ]] ||
		die "Le montage FAISS live diverge du bundle figé"
	[[ "$POSTGRES_DB" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "Nom PostgreSQL non sûr"
	[[ "$POSTGRES_USER" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "Utilisateur PostgreSQL non sûr"
	[[ "$IMAGE_TAG" =~ ^[A-Za-z0-9_.-]+$ ]] || die "Tag d'image invalide"
	[[ "$DOCKER_NETWORK" =~ ^[A-Za-z0-9_.-]+$ ]] || die "Réseau Docker invalide"
	[[ "$MINIO_BUCKET" =~ ^[A-Za-z0-9][A-Za-z0-9.-]{1,61}[A-Za-z0-9]$ ]] || die "Bucket MinIO invalide"
	[[ "$MINIO_API_PORT" =~ ^[0-9]+$ && "$MINIO_API_PORT" -ge 1 && "$MINIO_API_PORT" -le 65535 ]] || die "Port MinIO invalide"
	[[ -z "$AUDIT_WORKSPACES" || "$AUDIT_WORKSPACES" =~ ^[a-z0-9._[:space:]-]+$ ]] || die "Liste de workspaces d'audit invalide"
	[[ -d "$SECURE_DEPOSIT_PATH" ]] || die "Secure Deposit absent: $SECURE_DEPOSIT_PATH"
	[[ "$OBJECT_STORE_PATH" == "$DATA_ROOT"/* ]] || die "ObjectStore hors du disque data dédié"
	[[ "$OBJECT_STORE_PATH" == /* && -d "$OBJECT_STORE_PATH" ]] || die "ObjectStore monté du backend introuvable"
	[[ "$FAISS_PATH" == /* && -d "$FAISS_PATH" ]] || die "FAISS monté du backend introuvable"
	[[ "$(realpath -e "$SECURE_DEPOSIT_PATH")" == "$SECURE_DEPOSIT_PATH" ]] || die "Chemin Secure Deposit non canonique"
	[[ "$(realpath -e "$OBJECT_STORE_PATH")" == "$OBJECT_STORE_PATH" ]] || die "Chemin ObjectStore non canonique"
	[[ "$(realpath -e "$FAISS_PATH")" == "$FAISS_PATH" ]] || die "Chemin FAISS non canonique"
	[[ -f "$QDRANT_ENV_PATH" ]] || die "Env Qdrant absent: $QDRANT_ENV_PATH"
	[[ -f "$APPLICATION_ENV_PATH" ]] || die "Env applicatif absent: $APPLICATION_ENV_PATH"
	application_bucket="$(read_dotenv_value "$APPLICATION_ENV_PATH" OBJECT_STORE_S3_BUCKET)"
	[[ "$application_bucket" == "$MINIO_BUCKET" ]] || die "Le bucket MinIO ne correspond pas au bucket S3 du runtime"
}

verify_live_nginx_gate() {
	local dump expected_site actual_site expected_snippet actual_snippet kc_block
	[[ -f "$FROZEN_NGINX_SITE" && -f "$FROZEN_NGINX_SNIPPET" ]] || die "Configuration Nginx candidate figée absente"
	expected_site="$(sha256sum "$FROZEN_NGINX_SITE" | awk '{print $1}')"
	expected_snippet="$(sha256sum "$FROZEN_NGINX_SNIPPET" | awk '{print $1}')"
	actual_site="$(sudo_command sha256sum "$NGINX_SITE_TARGET" | awk '{print $1}')"
	actual_snippet="$(sudo_command sha256sum "$NGINX_SNIPPET_TARGET" | awk '{print $1}')"
	[[ "$actual_site" == "$expected_site" ]] || die "Le site Nginx actif diverge du fichier candidat exact"
	[[ "$actual_snippet" == "$expected_snippet" ]] || die "Le snippet Nginx actif diverge du fichier candidat exact"
	dump="$(sudo_command nginx -T 2>&1)" || die "nginx -T a échoué"
	grep -Fq 'include /etc/nginx/snippets/agentium-deploy-maintenance.conf;' <<<"$dump" ||
		die "Le Nginx live n'inclut pas le gate; installer d'abord la configuration canonique"
	grep -Fq '/var/lib/agentium/deploy-maintenance' <<<"$dump" || die "Le snippet live ne teste pas le marqueur persistant attendu"
	grep -Fq 'return 503' <<<"$dump" || die "Le snippet live ne ferme pas les requêtes publiques"
	grep -Fq 'if ($server_addr = 127.0.0.2)' <<<"$dump" ||
		die "Le bypass canari Nginx n'est pas borné à la destination loopback dédiée"
	kc_block="$(awk '/location \^~ \/kc\// {inside=1} inside {print} inside && /^    }/ {exit}' <<<"$dump")"
	grep -Fq 'include /etc/nginx/snippets/agentium-deploy-maintenance.conf;' <<<"$kc_block" ||
		die "Le endpoint Keycloak /kc/ contourne le gate de maintenance"
}

assert_nginx_unique_edge_topology() {
	local dump sockets suspicious
	dump="$(sudo_command nginx -T 2>&1)"
	[[ "$dump" != *"real_ip_header"* && "$dump" != *"set_real_ip_from"* && "$dump" != *"proxy_protocol"* ]] ||
		die "Nginx réécrit l'identité source; bypass loopback non attestable"
	sockets="$(sudo_command ss -H -ltnp | awk '$4 ~ /:(80|443)$/ {print}')"
	[[ -n "$sockets" ]] || die "Nginx n'écoute pas sur les ports edge attendus"
	while IFS= read -r row; do
		[[ "$row" == *'users:(("nginx"'* ]] || die "Un processus non-Nginx partage un port edge"
	done <<<"$sockets"
	suspicious="$(sudo_command ps -eo args= | grep -E '(^|[ /])(socat|rinetd|ngrok|cloudflared|frpc)([[:space:]]|$)|ssh([^[:alnum:]]|$).*(-R|-L)[[:space:]]' | grep -vE 'grep -E|deploy-agentium-safe' || true)"
	[[ -z "$suspicious" ]] || die "Proxy ou tunnel local susceptible de contourner le gate Nginx"
	# No second active Nginx file may proxy a protected Agentium upstream without
	# the canonical maintenance snippet. Bind every protected proxy directive to
	# the exact, hash-verified site; the only canary exception is selected by the
	# local destination address 127.0.0.2, never by client/source identity.
	python3 - "$NGINX_SITE_TARGET" 3< <(printf '%s\n' "$dump") <<'PY' || die "Un vhost Nginx secondaire peut contourner le gate Agentium"
import os
import re
import sys

site = os.path.abspath(sys.argv[1])
allowed = {site, os.path.realpath(site)}
current = None
violations = []
header = re.compile(r"^# configuration file (.+):$")
pass_directive = re.compile(r"\b(?:proxy_pass|grpc_pass|fastcgi_pass|uwsgi_pass)\s+([^;]+)")
protected = re.compile(
    r"(?::|%3a)(?:7880|8000|8001|8080|8081)\b"
    r"|\b(?:agentium-(?:backend|frontend|kc|livekit)|qdrant|agentium-minio)\b",
    re.IGNORECASE,
)
with os.fdopen(3, encoding="utf-8", errors="strict") as nginx_dump:
  for number, raw in enumerate(nginx_dump, start=1):
    match = header.match(raw.rstrip("\n"))
    if match:
        current = os.path.abspath(match.group(1))
        continue
    code = raw.split("#", 1)[0]
    if current not in allowed:
        if re.search(r"\bserver_name\b[^;]*\bagentium\.papai\.ai\b", code):
            violations.append((current, number, "duplicate Agentium server_name"))
        target = pass_directive.search(code)
        if target and protected.search(target.group(1)):
            violations.append((current, number, "protected upstream outside canonical site"))
        if re.search(r"\bserver\s+[^;]+", code) and protected.search(code):
            violations.append((current, number, "protected upstream alias outside canonical site"))
if violations:
    for filename, line, reason in violations:
        print(f"{filename or '<unknown>'}:{line}: {reason}", file=sys.stderr)
    raise SystemExit(1)
PY
}

snapshot_storage() {
	local output="$1" owner
	local -a container_args=(
		--container agentium-backend
		--container agentium-worker-cpu
		--container agentium-rabbitmq
	)
	[[ -x "$STORAGE_HELPER" ]] || die "Collecteur stockage figé absent: $STORAGE_HELPER"
	if docker inspect agentium-p4-maintenance >/dev/null 2>&1; then
		container_args+=(--container agentium-p4-maintenance)
	fi
	sudo_command python3 "$STORAGE_HELPER" snapshot \
		--output "$output" --secure-deposit "$SECURE_DEPOSIT_PATH" \
		--data-root "$DATA_ROOT" --qdrant-env "$QDRANT_ENV_PATH" \
		--object-store "$OBJECT_STORE_PATH" \
		--minio-url "http://127.0.0.1:$MINIO_API_PORT" \
		--minio-bucket "$MINIO_BUCKET" \
		--expected-data-source "$EXPECTED_DATA_SOURCE" \
		--expected-secure-deposit-source "$EXPECTED_SECURE_SOURCE" \
		"${container_args[@]}"
	owner="$(id -u):$(id -g)"
	sudo_command chown "$owner" "$output"
	chmod 0600 "$output"
}

assert_storage_baseline_contract() {
	assert_private_state_file "$STORAGE_BASELINE"
	python3 - "$STORAGE_BASELINE" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if not isinstance(payload, dict):
    raise SystemExit("storage baseline is not an object")
if payload.get("schema_version") != 1:
    raise SystemExit("storage baseline schema differs")
if payload.get("profile") != "agentium-storage-attestation-v3":
    raise SystemExit("storage baseline profile differs")
PY
}

ensure_storage_baseline() {
	if [[ -e "$STORAGE_BASELINE" || -L "$STORAGE_BASELINE" ]]; then
		# snapshot_storage publishes atomically.  An existing valid baseline is
		# therefore the committed result of an interrupted preflight and must be
		# reused rather than classified as orphaned or recaptured under writers.
		assert_storage_baseline_contract
		return
	fi
	snapshot_storage "$STORAGE_BASELINE"
	assert_storage_baseline_contract
}

assert_storage_capacity_and_layout() {
	local root_device data_device secure_device secure_required docker_root pg_source path service data_source secure_source data_target secure_target
	resolve_runtime_paths
	root_device="$(device_id /)"
	data_device="$(device_id "$DATA_ROOT")"
	secure_device="$(device_id "$SECURE_DEPOSIT_PATH")"
	data_source="$(findmnt -n -o SOURCE --target "$DATA_ROOT")"
	secure_source="$(findmnt -n -o SOURCE --target "$SECURE_DEPOSIT_PATH")"
	data_target="$(findmnt -n -o TARGET --target "$DATA_ROOT")"
	secure_target="$(findmnt -n -o TARGET --target "$SECURE_DEPOSIT_PATH")"
	[[ "$data_source" == "$EXPECTED_DATA_SOURCE" ]] || die "$DATA_ROOT est sur $data_source, attendu $EXPECTED_DATA_SOURCE"
	[[ "$secure_source" == "$EXPECTED_SECURE_SOURCE" ]] || die "Secure Deposit est sur $secure_source, attendu $EXPECTED_SECURE_SOURCE"
	[[ "$data_target" == "$DATA_ROOT" ]] || die "$DATA_ROOT doit être un mountpoint autonome"
	[[ "$secure_target" == "$SECURE_DEPOSIT_PATH" ]] || die "Secure Deposit doit être un mountpoint autonome"
	[[ "$root_device" != "$data_device" && "$root_device" != "$secure_device" && "$data_device" != "$secure_device" ]] ||
		die "Racine, data et Secure Deposit doivent être trois filesystems distincts"
	for path in / "$DATA_ROOT" "$SECURE_DEPOSIT_PATH"; do assert_rw_mount "$path"; assert_inode_margin "$path"; done
	(( $(available_bytes /) >= MIN_ROOT_FREE_BYTES )) || die "Racine sous le seuil de 40 Gio libres"
	(( $(available_bytes "$DATA_ROOT") >= MIN_DATA_FREE_BYTES )) || die "$DATA_ROOT sous le seuil de 64 Gio libres"
	secure_required=$(( $(total_bytes "$SECURE_DEPOSIT_PATH") / 10 ))
	(( secure_required < MIN_SECURE_FREE_BYTES )) && secure_required="$MIN_SECURE_FREE_BYTES"
	(( $(available_bytes "$SECURE_DEPOSIT_PATH") >= secure_required )) || die "Secure Deposit sous le seuil max(64 Gio, 10%)"
	docker_root="$(docker info --format '{{.DockerRootDir}}')"
	pg_source="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Source}}{{end}}{{end}}' agentium-pg)"
	sudo_command test -d "$docker_root" && sudo_command test -d "$pg_source" || die "Stockage Docker/PostgreSQL introuvable"
	[[ "$(privileged_device_id "$docker_root")" == "$root_device" ]] || die "DockerRootDir n'est pas couvert par le seuil racine attendu"
	[[ "$(privileged_device_id "$pg_source")" == "$root_device" ]] || die "PostgreSQL n'est pas couvert par le seuil racine attendu"
	assert_container_mount_device qdrant /qdrant/storage "$data_device"
	assert_container_mount_device qdrant /qdrant/snapshots "$data_device"
	assert_container_mount_device agentium-minio /data "$data_device"
	for service in agentium-backend agentium-worker-cpu; do
		assert_container_mount_device "$service" /data/object_store "$data_device"
		assert_container_mount_device "$service" /data/faiss_db "$root_device"
	done
	for service in agentium-backend agentium-worker-cpu agentium-sftp; do
		assert_container_mount_device "$service" /data/secure_deposit "$secure_device"
	done
	if docker inspect agentium-p4-maintenance >/dev/null 2>&1; then
		assert_container_mount_device agentium-p4-maintenance /data/object_store "$data_device"
		assert_container_mount_device agentium-p4-maintenance /data/faiss_db "$root_device"
		assert_container_mount_device agentium-p4-maintenance /data/secure_deposit "$secure_device"
	fi
	assert_container_mount_device agentium-pg /var/lib/postgresql/data "$root_device"
	assert_container_mount_device agentium-rabbitmq /var/lib/rabbitmq "$root_device"
}

preflight_checks() {
	local remote_sha current_sha dirty
	STAGE="preflight"
	cd "$REPO_DIR"
	assert_storage_capacity_and_layout
	for service in agentium-pg qdrant agentium-minio agentium-rabbitmq agentium-kc agentium-backend agentium-frontend agentium-worker-cpu agentium-sftp; do
		docker inspect "$service" >/dev/null 2>&1 || die "Conteneur requis absent: $service"
		[[ "$(docker inspect --format '{{.State.Paused}}' "$service")" == "false" ]] ||
			die "Conteneur requis déjà pausé avant preflight: $service"
	done
	for service in agentium-pg qdrant agentium-minio agentium-rabbitmq agentium-kc agentium-backend agentium-frontend agentium-worker-cpu; do
		[[ "$(docker inspect --format '{{.State.Running}}' "$service")" == "true" ]] || die "Service requis arrêté avant preflight: $service"
	done
	dirty="$(git status --porcelain --untracked-files=all)"
	[[ -z "$dirty" ]] || die "Arbre VM sale; aucun --force n'est accepté"
	assert_no_host_python_bytecode
	git fetch origin "$BRANCH" -q
	remote_sha="$(git rev-parse "origin/$BRANCH")"
	[[ "$remote_sha" == "$EXPECTED_SHA" ]] || die "origin/$BRANCH ne correspond pas au SHA demandé"
	for source in scripts/deploy-agentium-safe.sh scripts/deploy-vm.sh scripts/agentium-maintenance-gate.sh scripts/agentium_runtime_env_bundle.py scripts/agentium_storage_attestation.py scripts/agentium_safe_validation.py scripts/agentium_release_a_attestation.py scripts/agentium_release_a_manifest.py backend/scripts/audit_livekit_quiescence.py backend/scripts/audit_qdrant_write_barrier.py backend/scripts/audit_sftp_deploy_boundary.py backend/scripts/audit_post_canary_database.py docker/compose.agentium.qdrant-barrier.yml deploy/nginx/agentium-container-frontend.conf deploy/nginx/agentium-deploy-maintenance.conf deploy/agentium-backend.service deploy/install-backend-service.sh; do
		git cat-file -e "${EXPECTED_SHA}:${source}" || die "Script candidat absent: $source"
	done
	stage_candidate_helpers
	assert_qdrant_key_separation
	assert_systemd_qdrant_admin_contract
	attest_live_qdrant_bootstrap
	verify_live_nginx_gate
	assert_nginx_unique_edge_topology
	assert_systemd_unit_adoptable
	assert_no_foreign_sftp_ingress_gate
	assert_no_foreign_livekit_ingress_gate
	assert_no_foreign_systemd_backend_ingress_gate
	assert_legacy_sftp_systemd_safe
	assert_known_public_writer_listeners
	assert_internal_service_bindings
	[[ "$(gate status)" == "open" ]] || die "Un gate de maintenance est déjà fermé"
	current_sha="$(git rev-parse HEAD)"
	[[ "$current_sha" == "$(active_application_sha)" ]] || die "Checkout VM et runtime actif divergent avant préparation"
	git cat-file -e "${EXPECTED_SHA}^{commit}" || die "Commit candidat absent"
}

initialize_metadata() {
	local previous_sha previous_revision sftp_release_sha sftp_image_id metadata_temporary runtime_temporary service state image_id restart_name restart_max workspace_csv workspace_targets_digest worker_beat release_a_attestation_digest release_a_receipt_digest release_a_manifest_digest release_a_review_digest release_a_manifest_receipt_digest
	workspace_csv="$(IFS=,; printf '%s' "${CANARY_WORKSPACE_IDS[*]}")"
	if [[ -e "$METADATA_FILE" || -L "$METADATA_FILE" ]]; then
		assert_metadata_contract
		[[ "$(metadata deployment_id)" == "$DEPLOYMENT_ID" ]] || die "Répertoire lié à un autre deployment-id"
		[[ "$(metadata candidate_sha)" == "$EXPECTED_SHA" ]] || die "deployment-id déjà lié à un autre SHA"
		[[ "$(metadata branch)" == "$BRANCH" ]] || die "deployment-id déjà lié à une autre branche"
		[[ "$(metadata canary_workspace_ids)" == "$workspace_csv" ]] || die "deployment-id lié à une autre sélection de workspaces"
		assert_recorded_workspace_target_gate
		[[ "$(metadata env_manifest_sha256)" == "$ENV_MANIFEST_SHA256" ]] || die "deployment-id lié à un autre bundle env"
		[[ "$(metadata sftp_release_sha)" == "$(live_sftp_release_sha)" ]] || die "SFTP live différent du transport épinglé"
		[[ "$(metadata sftp_image_id)" == "$(docker inspect --format '{{.Image}}' agentium-sftp)" ]] || die "Image SFTP live différente de l'identité épinglée"
		assert_recorded_release_a_manifest_gate
		assert_recorded_release_a_gate
		verify_runtime_env_bundle >/dev/null
		[[ -x "$FROZEN_ORCHESTRATOR" && -x "$ENV_BUNDLE_HELPER" && -x "$MAINTENANCE_HELPER" && -x "$STORAGE_HELPER" && -x "$VALIDATION_HELPER" && -x "$RELEASE_A_HELPER" && -x "$RELEASE_A_MANIFEST_HELPER" && -x "$FROZEN_DEPLOYER" && -x "$FROZEN_SYSTEMD_INSTALLER" && -x "$QDRANT_BARRIER_HELPER" && -x "$SFTP_BOUNDARY_HELPER" && -s "$WORKSPACE_TARGETS" && -s "$FROZEN_RELEASE_A_MANIFEST" && -s "$FROZEN_RELEASE_A_REVIEW_POLICY" && -s "$RELEASE_A_MANIFEST_RECEIPT" && -s "$FROZEN_RELEASE_A_ATTESTATION" && -s "$RELEASE_A_RECEIPT" && -s "$FROZEN_QDRANT_OVERRIDE" && -s "$FROZEN_OPENED_OVERRIDE" && -s "$FROZEN_NGINX_SITE" && -s "$FROZEN_NGINX_SNIPPET" && -s "$FROZEN_SYSTEMD_UNIT" && -s "$RUNTIME_STATE_FILE" ]] || die "Helpers, gates Release A/workspace ou état runtime figés incomplets"
		assert_runtime_state_contract
		return
	fi
	previous_sha="$(active_application_sha)"
	previous_revision="$(current_database_revision)"
	sftp_release_sha="$(live_sftp_release_sha)"
	sftp_image_id="$(docker inspect --format '{{.Image}}' agentium-sftp)"
	assert_workspace_target_gate_contract "$WORKSPACE_TARGETS"
	workspace_targets_digest="$(sha256sum "$WORKSPACE_TARGETS" | awk '{print $1}')"
	[[ "$workspace_targets_digest" =~ ^[0-9a-f]{64}$ ]] || die "Digest du gate workspace invalide"
	[[ "$sftp_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || die "Image SFTP live invalide"
	[[ "$previous_revision" =~ ^[A-Za-z0-9_]+$ ]] || die "Révision DB précédente invalide"
	release_a_attestation_digest="$(sha256sum "$FROZEN_RELEASE_A_ATTESTATION" | awk '{print $1}')"
	release_a_receipt_digest="$(sha256sum "$RELEASE_A_RECEIPT" | awk '{print $1}')"
	release_a_manifest_digest="$(sha256sum "$FROZEN_RELEASE_A_MANIFEST" | awk '{print $1}')"
	release_a_review_digest="$(sha256sum "$FROZEN_RELEASE_A_REVIEW_POLICY" | awk '{print $1}')"
	release_a_manifest_receipt_digest="$(sha256sum "$RELEASE_A_MANIFEST_RECEIPT" | awk '{print $1}')"
	[[ "$release_a_attestation_digest" == "$RELEASE_A_ATTESTATION_SHA256" ]] ||
		die "Digest Release A différent entre le preflight et les métadonnées"
	[[ "$release_a_manifest_digest" == "$RELEASE_A_MANIFEST_SHA256" ]] ||
		die "Digest manifeste Release A différent entre le preflight et les métadonnées"
	[[ "$release_a_review_digest" == "$RELEASE_A_REVIEW_POLICY_SHA256" ]] ||
		die "Digest revue Release A différent entre le preflight et les métadonnées"
	assert_release_a_manifest_receipt_contract "$previous_sha" "$release_a_manifest_digest" "$release_a_review_digest" "$release_a_manifest_receipt_digest"
	assert_release_a_receipt_contract "$previous_sha" "$sftp_release_sha" "$release_a_attestation_digest" "$release_a_receipt_digest" fresh
	metadata_temporary="$DEPLOY_DIR/.metadata.$$"
	(umask 077; {
		printf 'format\t5\n'
		printf 'deployment_id\t%s\n' "$DEPLOYMENT_ID"
		printf 'branch\t%s\n' "$BRANCH"
		printf 'candidate_sha\t%s\n' "$EXPECTED_SHA"
		printf 'previous_sha\t%s\n' "$previous_sha"
		printf 'sftp_release_sha\t%s\n' "$sftp_release_sha"
		printf 'sftp_image_id\t%s\n' "$sftp_image_id"
		printf 'previous_database_revision\t%s\n' "$previous_revision"
		printf 'canary_workspace_ids\t%s\n' "$workspace_csv"
		printf 'workspace_targets_sha256\t%s\n' "$workspace_targets_digest"
		printf 'env_manifest_sha256\t%s\n' "$ENV_MANIFEST_SHA256"
		printf 'release_a_attestation_sha256\t%s\n' "$release_a_attestation_digest"
		printf 'release_a_receipt_sha256\t%s\n' "$release_a_receipt_digest"
		printf 'release_a_manifest_sha256\t%s\n' "$release_a_manifest_digest"
		printf 'release_a_review_policy_sha256\t%s\n' "$release_a_review_digest"
		printf 'release_a_manifest_receipt_sha256\t%s\n' "$release_a_manifest_receipt_digest"
		printf 'created_at\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
	} >"$metadata_temporary")
	stage_candidate_helpers
	if [[ ! -e "$RUNTIME_STATE_FILE" && ! -L "$RUNTIME_STATE_FILE" ]]; then
		runtime_temporary="$DEPLOY_DIR/.runtime-state.$$"
		(umask 077; {
			printf 'format\t4\n'
			worker_beat="$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' agentium-worker-cpu 2>/dev/null | awk -F= '$1 == "CELERY_BEAT" {print $2; exit}')"
			[[ "$worker_beat" == "0" || "$worker_beat" == "1" ]] || die "CELERY_BEAT historique absent ou invalide"
			printf 'worker_celery_beat\tagentium-worker-cpu\t%s\t-\n' "$worker_beat"
			for service in agentium-livekit agentium-livekit-agent agentium-kc; do
				if docker inspect "$service" >/dev/null 2>&1; then
					image_id="$(docker inspect --format '{{.Image}}' "$service")"
					[[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || die "Image runtime invalide pour $service"
					if [[ "$(docker inspect --format '{{.State.Running}}' "$service")" == "true" ]]; then state=running; else state=stopped; fi
					printf 'runtime_state\t%s\t%s\t%s\n' "$service" "$state" "$image_id"
					read -r restart_name restart_max < <(container_restart_policy "$service")
					printf 'runtime_restart_policy\t%s\t%s\t%s\n' "$service" "$restart_name" "$restart_max"
					container_listener_bindings "$service"
				else
					printf 'runtime_state\t%s\tabsent\t-\n' "$service"
					printf 'runtime_restart_policy\t%s\tabsent\t-\n' "$service"
				fi
			done
			if sudo_command systemctl cat agentium-backend.service >/dev/null 2>&1; then
				if sudo_command systemctl is-active --quiet agentium-backend.service; then state=active; else state=stopped; fi
				printf 'systemd_state\tagentium-backend.service\t%s\t-\n' "$state"
				state="$(sudo_command systemctl is-enabled agentium-backend.service 2>/dev/null || true)"
				[[ "$state" == "enabled" || "$state" == "disabled" ]] || die "État enable systemd non supporté: $state"
				printf 'systemd_unit_file_state\tagentium-backend.service\t%s\t-\n' "$state"
			else
				printf 'systemd_state\tagentium-backend.service\tabsent\t-\n'
			fi
		} >"$runtime_temporary")
		durable_publish_file "$runtime_temporary" "$RUNTIME_STATE_FILE"
	else
		assert_runtime_state_contract
	fi
	durable_publish_file "$metadata_temporary" "$METADATA_FILE"
	assert_metadata_contract
	assert_recorded_release_a_manifest_gate
	assert_recorded_workspace_target_gate
	assert_runtime_state_contract
}

verify_backup() {
	local backup="$1" expected actual bytes ready="$backup.ready"
	[[ -s "$backup" && -s "$backup.sha256" && -s "$ready" ]] || return 1
	assert_private_state_file "$backup" || return 1
	assert_private_state_file "$backup.sha256" || return 1
	assert_private_state_file "$ready" || return 1
	expected="$(awk 'NR == 1 { print $1 }' "$backup.sha256")"
	actual="$(sha256sum "$backup" | awk '{ print $1 }')"
	[[ "$expected" =~ ^[0-9a-f]{64}$ && "$actual" == "$expected" ]] || return 1
	bytes="$(stat -c '%s' "$backup")"
	python3 - "$ready" "$actual" "$bytes" <<'PY' || return 1
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected = {"format": "1", "sha256": sys.argv[2], "bytes": sys.argv[3]}
rows = {}
for raw in path.read_text(encoding="utf-8").splitlines():
    fields = raw.split("\t")
    if len(fields) != 2 or fields[0] in rows:
        raise SystemExit(1)
    rows[fields[0]] = fields[1]
if rows != expected:
    raise SystemExit(1)
PY
	docker exec -i agentium-pg pg_restore --list <"$backup" >/dev/null
}

create_backup() {
	local label="$1" backup="$DEPLOY_DIR/postgres-${label}.dump" temporary digest bytes marker
	if [[ -s "$backup.ready" ]]; then
		verify_backup "$backup" || die "Backup publié invalide: $backup"
		return
	fi
	[[ ! -e "$backup.ready" && ! -L "$backup.ready" ]] || die "Marqueur backup incomplet ou non régulier: $backup.ready"
	if [[ -e "$backup" || -L "$backup" ]]; then
		assert_private_state_file "$backup"
		docker exec -i agentium-pg pg_restore --list <"$backup" >/dev/null || die "Dump PostgreSQL interrompu ou invalide: $backup"
	else
		temporary="$(mktemp "$DEPLOY_DIR/.postgres-${label}.XXXXXX")"
		chmod 0600 "$temporary"
		docker exec agentium-pg pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc >"$temporary"
		docker exec -i agentium-pg pg_restore --list <"$temporary" >/dev/null
		durable_publish_file "$temporary" "$backup"
	fi
	digest="$(sha256sum "$backup" | awk '{ print $1 }')"
	[[ "$digest" =~ ^[0-9a-f]{64}$ ]] || die "Digest du dump PostgreSQL invalide"
	if [[ -e "$backup.sha256" || -L "$backup.sha256" ]]; then
		assert_private_state_file "$backup.sha256"
		[[ "$(awk 'NR == 1 {print $1}' "$backup.sha256")" == "$digest" ]] || die "Checksum backup partiellement publiée et divergente"
	else
		atomic_text "$backup.sha256" "$digest  ${backup##*/}"
	fi
	bytes="$(stat -c '%s' "$backup")"
	printf -v marker 'format\t1\nsha256\t%s\nbytes\t%s' "$digest" "$bytes"
	atomic_text "$backup.ready" "$marker"
	verify_backup "$backup" || die "Backup durable invérifiable"
}

run_candidate() {
	run_candidate_database_command "$@"
}

run_candidate_with_readonly_inputs() {
	run_candidate_database_command "$@"
}

run_candidate_live_writer_audit() {
	[[ "$#" -eq 6 && "$1" == "python" && "$2" == "scripts/audit_livekit_quiescence.py" &&
		"$3" == "--expected-sha" && "$4" == "$EXPECTED_SHA" &&
		"$5" == "--deployment-id" && "$6" == "$DEPLOYMENT_ID" ]] || return 64
	run_candidate_live_writer_audit_command "$@"
}

capture_candidate_database_inventory() {
	local output="$1" mode="${2:-baseline}" temporary="$DEPLOY_DIR/.${output##*/}.$$"
	local -a command=(python -m scripts.audit_post_canary_database snapshot
		--sha "$EXPECTED_SHA" --deployment-id "$DEPLOYMENT_ID")
	[[ "$mode" == "baseline" || "$mode" == "controlled" ]] ||
		die "Mode d'inventaire PostgreSQL inconnu: $mode"
	if [[ "$mode" == "controlled" ]]; then
		[[ -s "$DEPLOY_DIR/proofs/chat-ledger.json" ]] ||
			die "Ledger Chat privé absent avant inventaire PostgreSQL contrôlé"
		command+=(--ledger /safe-inputs/chat-ledger.json)
	fi
	rm -f "$temporary"
	if ! (umask 077; if [[ "$mode" == "controlled" ]]; then
		run_candidate_with_readonly_inputs \
			--readonly-input "$DEPLOY_DIR/proofs/chat-ledger.json" chat-ledger.json \
			"${command[@]}"
	else
		run_candidate "${command[@]}"
	fi >"$temporary"); then
		[[ -s "$temporary" ]] && { chmod 0600 "$temporary"; durable_replace_file "$temporary" "$output"; }
		die "Inventaire PostgreSQL content-free en échec"
	fi
	chmod 0600 "$temporary"
	python3 - "$temporary" "$EXPECTED_SHA" "$DEPLOYMENT_ID" "$mode" <<'PY'
import json
import sys
from pathlib import Path

path, expected_sha, deployment_id, mode = sys.argv[1:]
p = json.loads(Path(path).read_text(encoding="utf-8"))
binding = p.get("ledger_binding")
assert p.get("schema_version") == 2
assert p.get("kind") == "postgresql_row_inventory"
assert p.get("profile") == "agentium-postgresql-row-inventory-v2"
assert p.get("candidate_sha") == expected_sha
assert p.get("deployment_id") == deployment_id
assert p.get("content_serialized") is False
assert isinstance(binding, dict)
assert binding.get("provided") is (mode == "controlled")
PY
	durable_replace_file "$temporary" "$output"
}

compare_controlled_canary_database() {
	local final_inventory="$1" output="$2" temporary="$DEPLOY_DIR/.${output##*/}.$$"
	local workspace_id
	local -a workspace_args=()
	for workspace_id in "${CANARY_WORKSPACE_IDS[@]}"; do
		workspace_args+=(--canary-workspace-id "$workspace_id")
	done
	[[ -s "$DATABASE_CANARY_BASELINE" && -s "$DATABASE_POST_CANARY_INVENTORY" && -s "$final_inventory" && -s "$DEPLOY_DIR/proofs/chat-ledger.json" ]] ||
		die "Entrées de comparaison PostgreSQL post-canari incomplètes"
	rm -f "$temporary"
	if ! (umask 077; run_candidate_offline_with_readonly_inputs \
		--readonly-input "$DATABASE_CANARY_BASELINE" baseline.json \
		--readonly-input "$DATABASE_POST_CANARY_INVENTORY" post-canary.json \
		--readonly-input "$final_inventory" final.json \
		--readonly-input "$DEPLOY_DIR/proofs/chat-ledger.json" chat-ledger.json \
		python -m scripts.audit_post_canary_database compare \
		--sha "$EXPECTED_SHA" --deployment-id "$DEPLOYMENT_ID" \
		--baseline /safe-inputs/baseline.json \
		--post-canary /safe-inputs/post-canary.json \
		--final /safe-inputs/final.json \
		--ledger /safe-inputs/chat-ledger.json \
		"${workspace_args[@]}" >"$temporary"); then
		[[ -s "$temporary" ]] && { chmod 0600 "$temporary"; durable_replace_file "$temporary" "$output"; }
		die "Les canaris ont modifié PostgreSQL hors du contrat contrôlé"
	fi
	chmod 0600 "$temporary"
	python3 -c 'import json,sys; p=json.load(open(sys.argv[1], encoding="utf-8")); assert p.get("schema_version") == 2 and p.get("result") == "passed" and p.get("kind") == "controlled_canary_database_comparison" and p.get("profile") == "agentium-controlled-canary-postgresql-v2" and p.get("sha") == sys.argv[2] and p.get("deployment_id") == sys.argv[3] and p.get("content_serialized") is False and p.get("checks") and all(p["checks"].values())' \
		"$temporary" "$EXPECTED_SHA" "$DEPLOYMENT_ID" || die "Comparaison PostgreSQL post-canari invalide"
	durable_replace_file "$temporary" "$output"
}

audit_live_writers_before_stop() {
	local output="$DEPLOY_DIR/live-writer-quiescence.json" temporary="$DEPLOY_DIR/.live-writer-quiescence.$$"
	rm -f "$temporary"
	if ! (umask 077; run_candidate_live_writer_audit python scripts/audit_livekit_quiescence.py \
		--expected-sha "$EXPECTED_SHA" --deployment-id "$DEPLOYMENT_ID" >"$temporary"); then
		[[ -s "$temporary" ]] && { chmod 0600 "$temporary"; durable_replace_file "$temporary" "$output"; }
		die "Sessions temps réel ou Knowledge Capture actives, ou contrôle LiveKit indisponible"
	fi
	chmod 0600 "$temporary"
	python3 - "$temporary" "$EXPECTED_SHA" "$DEPLOYMENT_ID" <<'PY'
import json, sys
from pathlib import Path
p = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert p.get("schema_version") == 1 and p.get("kind") == "live_writer_quiescence_audit"
assert p.get("result") == "passed"
assert p.get("candidate_sha") == sys.argv[2] and p.get("deployment_id") == sys.argv[3]
assert p.get("blockers") == {
    "correlated_recent_active_capture_count": 0,
    "livekit_participant_count": 0,
    "livekit_publisher_count": 0,
}
PY
	durable_replace_file "$temporary" "$output"
}

verify_candidate_images_and_rollback() {
	local service ref expected actual revision kind svc image_id _image_ref rollback_ref tagged_id
	assert_candidate_image_override_contract
	for service in agentium-backend agentium-frontend agentium-worker-cpu; do
		ref="$(candidate_image_reference "$service")"
		expected="$(candidate_override_image_id "$service")"
		actual="$(docker image inspect --format '{{.Id}}' "$ref" 2>/dev/null || true)"
		revision="$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$ref" 2>/dev/null || true)"
		[[ "$actual" == "$expected" && "$revision" == "$EXPECTED_SHA" ]] || die "Image candidate absente, retaggée ou non alignée: $ref"
	done
	[[ -x "$FROZEN_DEPLOYER" ]] || die "Déployeur candidat figé absent"
	[[ "$(git hash-object "$FROZEN_DEPLOYER")" == "$(git rev-parse "${EXPECTED_SHA}:scripts/deploy-vm.sh")" ]] ||
		die "Déployeur figé non aligné sur le candidat"
	[[ -f "$ROLLBACK_STATE" ]] || die "État rollback absent"
	[[ "$(awk -F '\t' '$1 == "format" { print $2 }' "$ROLLBACK_STATE")" == "3" ]] || die "Rollback v3 obligatoire"
	[[ "$(awk -F '\t' '$1 == "target_sha" { print $2 }' "$ROLLBACK_STATE")" == "$EXPECTED_SHA" ]] || die "Rollback lié à un autre candidat"
	[[ "$(awk -F '\t' '$1 == "previous_sha" { print $2 }' "$ROLLBACK_STATE")" == "$(metadata previous_sha)" ]] || die "Rollback lié à un autre runtime précédent"
	while IFS=$'\t' read -r kind svc image_id _image_ref rollback_ref; do
		[[ "$kind" == "service" ]] || continue
		tagged_id="$(docker image inspect --format '{{.Id}}' "$rollback_ref" 2>/dev/null || true)"
		[[ "$tagged_id" == "$image_id" ]] || die "Image rollback absente ou altérée pour $svc"
	done <"$ROLLBACK_STATE"
}

assert_preparation_fresh() {
	[[ -s "$PREPARED_AT_FILE" ]] || die "Horodatage de préparation absent"
	python3 - "$PREPARED_AT_FILE" "$PREPARATION_MAX_AGE_SECONDS" <<'PY'
from datetime import datetime, timezone
from pathlib import Path
import sys
value = datetime.fromisoformat(Path(sys.argv[1]).read_text().strip().replace("Z", "+00:00"))
age = (datetime.now(timezone.utc) - value).total_seconds()
if age < -300 or age > int(sys.argv[2]):
    raise SystemExit("candidate preparation is stale or future-dated")
PY
}

candidate_audit_args() {
	local workspace
	# Empty means the audit's authoritative default: every persisted workspace.
	for workspace in $AUDIT_WORKSPACES; do printf '%s\n' --workspace "$workspace"; done
}

write_rehearsal_intent() {
	local label="$1" root="$2" container="$3" temporary="$DEPLOY_DIR/.rehearsal-active.$$"
	[[ ! -e "$REHEARSAL_INTENT" && ! -L "$REHEARSAL_INTENT" ]] || die "Intent rehearsal déjà présent"
	(umask 077; printf 'format\t1\ndeployment_id\t%s\ncandidate_sha\t%s\nlabel\t%s\nroot\t%s\ncontainer\t%s\nstate\tactive\n' \
		"$DEPLOYMENT_ID" "$EXPECTED_SHA" "$label" "$root" "$container" >"$temporary")
	durable_publish_file "$temporary" "$REHEARSAL_INTENT"
}

validate_rehearsal_intent() {
	local label root container
	assert_private_state_file "$REHEARSAL_INTENT"
	[[ "$(awk -F '\t' '$1 == "format" {print $2; n++} END {exit n == 1 ? 0 : 1}' "$REHEARSAL_INTENT")" == "1" ]] || return 1
	[[ "$(awk -F '\t' '$1 == "deployment_id" {print $2; n++} END {exit n == 1 ? 0 : 1}' "$REHEARSAL_INTENT")" == "$DEPLOYMENT_ID" ]] || return 1
	[[ "$(awk -F '\t' '$1 == "candidate_sha" {print $2; n++} END {exit n == 1 ? 0 : 1}' "$REHEARSAL_INTENT")" == "$EXPECTED_SHA" ]] || return 1
	[[ "$(awk -F '\t' '$1 == "state" {print $2; n++} END {exit n == 1 ? 0 : 1}' "$REHEARSAL_INTENT")" == "active" ]] || return 1
	label="$(awk -F '\t' '$1 == "label" {print $2; n++} END {exit n == 1 ? 0 : 1}' "$REHEARSAL_INTENT")" || return 1
	root="$(awk -F '\t' '$1 == "root" {print $2; n++} END {exit n == 1 ? 0 : 1}' "$REHEARSAL_INTENT")" || return 1
	container="$(awk -F '\t' '$1 == "container" {print $2; n++} END {exit n == 1 ? 0 : 1}' "$REHEARSAL_INTENT")" || return 1
	[[ "$label" =~ ^[a-z]+$ ]] || return 1
	[[ "$root" == "$REHEARSAL_BASE/${DEPLOYMENT_ID}-${label}" ]] || return 1
	[[ "$container" == "agentium-rehearsal-${EXPECTED_SHA:0:12}-${label}" ]] || return 1
	awk -F '\t' 'NF {seen[$1]++} END {for (key in seen) if (seen[key] != 1) exit 1; exit length(seen) == 7 ? 0 : 1}' \
		"$REHEARSAL_INTENT" >/dev/null || return 1
	printf '%s\t%s\t%s\n' "$label" "$root" "$container"
}

cleanup_current_rehearsal() {
	local contract label root container candidate
	[[ -e "$REHEARSAL_INTENT" || -L "$REHEARSAL_INTENT" ]] || { REHEARSAL_ACTIVE=0; return 0; }
	contract="$(validate_rehearsal_intent)" || return 1
	IFS=$'\t' read -r label root container < <(printf '%s\n' "$contract")
	while IFS= read -r candidate; do
		[[ -z "$candidate" ]] || docker rm -f "$candidate" >/dev/null 2>&1 || return 1
	done < <(docker ps -aq --filter "label=ai.papai.agentium.rehearsal.deployment_id=$DEPLOYMENT_ID")
	docker rm -f "$container" >/dev/null 2>&1 || true
	[[ "$root" == "$REHEARSAL_BASE/${DEPLOYMENT_ID}-${label}" ]] || return 1
	if [[ -e "$root" || -L "$root" ]]; then sudo_command rm -rf -- "$root" || return 1; fi
	rm -f -- "$REHEARSAL_INTENT" || return 1
	REHEARSAL_ACTIVE=0
}

assert_no_rehearsal_residue() {
	local residue
	[[ ! -e "$REHEARSAL_INTENT" && ! -L "$REHEARSAL_INTENT" ]] || return 1
	residue="$(docker ps -aq --filter label=ai.papai.agentium.rehearsal=1 | head -n 1)"
	[[ -z "$residue" ]] || return 1
	if [[ -d "$REHEARSAL_BASE" ]]; then
		residue="$(find "$REHEARSAL_BASE" -mindepth 1 -maxdepth 1 -print -quit)"
		[[ -z "$residue" ]] || return 1
	elif [[ -e "$REHEARSAL_BASE" || -L "$REHEARSAL_BASE" ]]; then
		return 1
	fi
}

reconcile_rehearsal_residue() {
	if [[ -e "$REHEARSAL_INTENT" || -L "$REHEARSAL_INTENT" ]]; then
		STAGE="reconcile owned database rehearsal"
		cleanup_current_rehearsal || die "Rehearsal courant orphelin non nettoyable; gate inchangé"
	fi
	assert_no_rehearsal_residue || die "Rehearsal étranger/orphelin détecté; aucune suppression automatique"
}

cleanup_current_candidate_oneoffs() {
	local container revision
	while IFS= read -r container; do
		[[ -z "$container" ]] && continue
		revision="$(docker inspect --format '{{ index .Config.Labels "ai.papai.agentium.safe-deploy.candidate_sha" }}' "$container" 2>/dev/null || true)"
		[[ "$revision" == "$EXPECTED_SHA" ]] || return 1
		docker rm -f "$container" >/dev/null 2>&1 || return 1
	done < <(docker ps -aq --filter "label=ai.papai.agentium.safe-deploy.deployment_id=$DEPLOYMENT_ID")
}

assert_no_candidate_oneoff_residue() {
	local container owner
	while IFS= read -r container; do
		[[ -z "$container" ]] && continue
		owner="$(docker inspect --format '{{ index .Config.Labels "ai.papai.agentium.safe-deploy.deployment_id" }}' "$container" 2>/dev/null || true)"
		[[ "$owner" == "$DEPLOYMENT_ID" ]] || return 1
		return 1
	done < <(docker ps -aq --filter label=ai.papai.agentium.safe-deploy.oneoff=1)
	return 0
}

reconcile_candidate_oneoff_residue() {
	cleanup_current_candidate_oneoffs || die "One-off candidat courant non nettoyable"
	assert_no_candidate_oneoff_residue || die "One-off candidat étranger/orphelin détecté; aucune suppression automatique"
}

migration_secret_is_owned() {
	[[ -f "$MIGRATION_DATABASE_SECRET" && ! -L "$MIGRATION_DATABASE_SECRET" ]] || return 1
	[[ "$(stat -c '%a:%u:%h' "$MIGRATION_DATABASE_SECRET")" == "600:$(id -u):1" ]]
}

assert_candidate_migration_secret_contract() {
	migration_secret_is_owned || return 1
	python3 - "$MIGRATION_DATABASE_SECRET" "$POSTGRES_USER" "$POSTGRES_DB" <<'PY'
import os
import stat
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

path = Path(sys.argv[1])
expected_user, expected_database = sys.argv[2:]
flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
fd = os.open(path, flags)
try:
    details = os.fstat(fd)
    if (
        not stat.S_ISREG(details.st_mode)
        or details.st_uid != os.geteuid()
        or stat.S_IMODE(details.st_mode) != 0o600
        or details.st_nlink != 1
        or details.st_size < 2
        or details.st_size > 8192
    ):
        raise SystemExit("candidate migration secret identity is unsafe")
    raw = os.read(fd, 8193)
finally:
    os.close(fd)
if len(raw) != details.st_size or not raw.endswith(b"\n") or raw.count(b"\n") != 1:
    raise SystemExit("candidate migration secret framing is invalid")
try:
    value = raw[:-1].decode("utf-8")
    parsed = urlsplit(value)
    port = parsed.port or 5432
except (UnicodeDecodeError, ValueError) as exc:
    raise SystemExit("candidate migration DATABASE_URL is invalid") from exc
if (
    parsed.scheme not in {"postgres", "postgresql", "postgresql+psycopg"}
    or unquote(parsed.username or "") != expected_user
    or not unquote(parsed.password or "")
    or parsed.hostname != "agentium-pg"
    or port != 5432
    or parsed.path != f"/{expected_database}"
    or parsed.query
    or parsed.fragment
):
    raise SystemExit("candidate migration DATABASE_URL leaves the PostgreSQL boundary")
PY
}

write_candidate_migration_secret() {
	local database_url
	[[ ! -e "$MIGRATION_DATABASE_SECRET" && ! -L "$MIGRATION_DATABASE_SECRET" ]] || return 1
	verify_runtime_env_bundle >/dev/null || return 1
	database_url="$(read_dotenv_value "$APPLICATION_ENV_PATH" DATABASE_URL)" || return 1
	(umask 077; printf '%s\n' "$database_url" >"$MIGRATION_DATABASE_SECRET") || {
		unset database_url
		return 1
	}
	unset database_url
	assert_candidate_migration_secret_contract || return 1
	python3 - "$MIGRATION_DATABASE_SECRET" <<'PY'
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
with path.open("rb") as handle:
    os.fsync(handle.fileno())
directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PY
}

remove_candidate_migration_secret() {
	[[ -e "$MIGRATION_DATABASE_SECRET" || -L "$MIGRATION_DATABASE_SECRET" ]] || return 0
	migration_secret_is_owned || return 1
	python3 - "$MIGRATION_DATABASE_SECRET" <<'PY'
import os
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
fd = os.open(path, flags)
try:
    details = os.fstat(fd)
    if (
        not stat.S_ISREG(details.st_mode)
        or details.st_uid != os.geteuid()
        or stat.S_IMODE(details.st_mode) != 0o600
        or details.st_nlink != 1
    ):
        raise SystemExit("candidate migration secret ownership changed")
finally:
    os.close(fd)
path.unlink()
directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PY
}

assert_candidate_migration_network_identity() {
	docker network inspect "$MIGRATION_NETWORK" >/dev/null 2>&1 || return 1
	[[ "$(docker network inspect --format '{{.Driver}}' "$MIGRATION_NETWORK")" == "bridge" ]] || return 1
	[[ "$(docker network inspect --format '{{.Internal}}' "$MIGRATION_NETWORK")" == "true" ]] || return 1
	[[ "$(docker network inspect --format '{{.Scope}}' "$MIGRATION_NETWORK")" == "local" ]] || return 1
	[[ "$(docker network inspect --format '{{index .Labels \"ai.papai.agentium.safe-deploy.migration-network\"}}' "$MIGRATION_NETWORK")" == "1" ]] || return 1
	[[ "$(docker network inspect --format '{{index .Labels \"ai.papai.agentium.safe-deploy.deployment_id\"}}' "$MIGRATION_NETWORK")" == "$DEPLOYMENT_ID" ]] || return 1
	[[ "$(docker network inspect --format '{{index .Labels \"ai.papai.agentium.safe-deploy.candidate_sha\"}}' "$MIGRATION_NETWORK")" == "$EXPECTED_SHA" ]] || return 1
}

assert_candidate_migration_boundary_active() {
	local attached name total=0 postgres=0
	assert_candidate_migration_secret_contract || return 1
	assert_candidate_migration_network_identity || return 1
	attached="$(docker network inspect --format '{{range .Containers}}{{println .Name}}{{end}}' "$MIGRATION_NETWORK")" || return 1
	while IFS= read -r name; do
		[[ -z "$name" ]] && continue
		((total += 1))
		[[ "$name" == "agentium-pg" ]] || return 1
		((postgres += 1))
	done < <(printf '%s\n' "$attached")
	[[ "$total" -eq 1 && "$postgres" -eq 1 ]]
}

assert_no_candidate_migration_boundary_residue() {
	local networks containers
	[[ ! -e "$MIGRATION_DATABASE_SECRET" && ! -L "$MIGRATION_DATABASE_SECRET" ]] || return 1
	docker network inspect "$MIGRATION_NETWORK" >/dev/null 2>&1 && return 1
	networks="$(docker network ls -q --filter label=ai.papai.agentium.safe-deploy.migration-network=1)" || return 1
	[[ -z "$networks" ]] || return 1
	containers="$(docker ps -aq --filter label=ai.papai.agentium.safe-deploy.migration-boundary=1)" || return 1
	[[ -z "$containers" ]]
}

cleanup_current_candidate_migration_boundary() {
	local attached name postgres=0
	if [[ -e "$MIGRATION_DATABASE_SECRET" || -L "$MIGRATION_DATABASE_SECRET" ]]; then
		migration_secret_is_owned || return 1
	fi
	if docker network inspect "$MIGRATION_NETWORK" >/dev/null 2>&1; then
		assert_candidate_migration_network_identity || return 1
		attached="$(docker network inspect --format '{{range .Containers}}{{println .Name}}{{end}}' "$MIGRATION_NETWORK")" || return 1
		while IFS= read -r name; do
			[[ -z "$name" ]] && continue
			[[ "$name" == "agentium-pg" ]] || return 1
			postgres=1
		done < <(printf '%s\n' "$attached")
		if [[ "$postgres" -eq 1 ]]; then
			docker network disconnect "$MIGRATION_NETWORK" agentium-pg >/dev/null || return 1
		fi
		docker network rm "$MIGRATION_NETWORK" >/dev/null || return 1
	fi
	remove_candidate_migration_secret || return 1
	MIGRATION_BOUNDARY_ACTIVE=0
}

reconcile_candidate_migration_boundary() {
	if [[ -e "$MIGRATION_DATABASE_SECRET" || -L "$MIGRATION_DATABASE_SECRET" ]] ||
		docker network inspect "$MIGRATION_NETWORK" >/dev/null 2>&1; then
		STAGE="reconcile owned candidate migration boundary"
		cleanup_current_candidate_migration_boundary ||
			die "Frontière migration candidate courante non nettoyable; gate inchangé"
	fi
	assert_no_candidate_migration_boundary_residue ||
		die "Frontière migration candidate étrangère/orpheline détectée; aucune suppression automatique"
}

open_candidate_migration_boundary() {
	assert_no_candidate_migration_boundary_residue || return 1
	MIGRATION_BOUNDARY_ACTIVE=1
	write_candidate_migration_secret || return 1
	docker network create --driver bridge --internal \
		--label ai.papai.agentium.safe-deploy.migration-network=1 \
		--label "ai.papai.agentium.safe-deploy.deployment_id=$DEPLOYMENT_ID" \
		--label "ai.papai.agentium.safe-deploy.candidate_sha=$EXPECTED_SHA" \
		"$MIGRATION_NETWORK" >/dev/null || return 1
	docker network connect --alias agentium-pg "$MIGRATION_NETWORK" agentium-pg >/dev/null || return 1
	assert_candidate_migration_boundary_active
}

parse_candidate_readonly_inputs() {
	local mounts_name="$1" arguments_name="$2" source target canonical size
	local -n mounts_ref="$mounts_name" arguments_ref="$arguments_name"
	local -A seen_targets=()
	shift 2
	mounts_ref=()
	while [[ "${1:-}" == "--readonly-input" ]]; do
		[[ "$#" -ge 3 ]] || return 64
		source="$2"
		target="$3"
		shift 3
		[[ "$source" == "$DEPLOY_DIR"/* && "$source" != *,* ]] || return 1
		canonical="$(realpath -e "$source")" || return 1
		[[ "$canonical" == "$source" && -f "$source" && ! -L "$source" ]] || return 1
		[[ "$(stat -c '%a:%u:%h' "$source")" == "600:$(id -u):1" ]] || return 1
		size="$(stat -c '%s' "$source")" || return 1
		[[ "$size" =~ ^[0-9]+$ && "$size" -ge 2 && "$size" -le 16777216 ]] || return 1
		[[ "$target" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$ ]] || return 1
		[[ -z "${seen_targets[$target]:-}" ]] || return 1
		seen_targets[$target]=1
		mounts_ref+=(--mount "type=bind,src=$source,dst=/safe-inputs/$target,readonly")
	done
	[[ "$#" -gt 0 ]] || return 64
	arguments_ref=("$@")
}

assert_candidate_database_tool_command() {
	local -a command=("$@")
	case "${command[0]:-}:${command[1]:-}:${command[2]:-}:${command[3]:-}" in
	"alembic:upgrade:head:" | "alembic:current::" | "alembic:heads::") ;;
	"python:-m:scripts.backfill_workspace_app_installations:"* | \
		"python:-m:scripts.audit_persisted_system_bindings:"* | \
		"python:-m:scripts.audit_post_canary_database:snapshot") ;;
	*) return 64 ;;
	esac
}

run_candidate_database_tool() {
	local candidate_image
	local -a mounts=() command=()
	parse_candidate_readonly_inputs mounts command "$@" || return $?
	assert_candidate_database_tool_command "${command[@]}" || return $?
	assert_candidate_migration_boundary_active || return 1
	candidate_image="$(candidate_override_image_id agentium-backend)" || return 1
	docker run --rm --read-only --network "$MIGRATION_NETWORK" \
		--name "agentium-db-tool-${EXPECTED_SHA:0:12}-${MIGRATION_NETWORK_KEY}" \
		--label ai.papai.agentium.safe-deploy.oneoff=1 \
		--label ai.papai.agentium.safe-deploy.migration-boundary=1 \
		--label "ai.papai.agentium.safe-deploy.deployment_id=$DEPLOYMENT_ID" \
		--label "ai.papai.agentium.safe-deploy.candidate_sha=$EXPECTED_SHA" \
		--cap-drop ALL --security-opt no-new-privileges:true --pids-limit 256 \
		--tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m \
		--mount "type=bind,src=$MIGRATION_DATABASE_SECRET,dst=/run/secrets/agentium-database-url,readonly" \
		"${mounts[@]}" \
		--env AGENTIUM_DISABLE_DOTENV=1 --entrypoint /bin/sh \
		"$candidate_image" -eu -c '
secret=/run/secrets/agentium-database-url
[ -f "$secret" ] && [ ! -L "$secret" ]
DATABASE_URL="$(cat "$secret")"
export DATABASE_URL
exec "$@"
' agentium-database-tool "${command[@]}"
}

run_candidate_database_command() {
	local code=0 cleanup_failed=0
	if open_candidate_migration_boundary; then
		if run_candidate_database_tool "$@"; then :; else code=$?; fi
	else
		code=$?
	fi
	if cleanup_current_candidate_oneoffs; then :; else cleanup_failed=1; fi
	if cleanup_current_candidate_migration_boundary; then :; else cleanup_failed=1; fi
	[[ "$cleanup_failed" -eq 0 ]] || die "Frontière outil PostgreSQL candidate non nettoyable; gate maintenu fermé"
	return "$code"
}

run_candidate_offline_with_readonly_inputs() {
	local candidate_image
	local -a mounts=() command=()
	parse_candidate_readonly_inputs mounts command "$@" || return $?
	[[ "${command[0]:-}:${command[1]:-}:${command[2]:-}:${command[3]:-}" == \
		"python:-m:scripts.audit_post_canary_database:compare" ]] || return 64
	candidate_image="$(candidate_override_image_id agentium-backend)" || return 1
	docker run --rm --read-only --network none \
		--name "agentium-offline-tool-${EXPECTED_SHA:0:12}-${MIGRATION_NETWORK_KEY}" \
		--label ai.papai.agentium.safe-deploy.oneoff=1 \
		--label "ai.papai.agentium.safe-deploy.deployment_id=$DEPLOYMENT_ID" \
		--label "ai.papai.agentium.safe-deploy.candidate_sha=$EXPECTED_SHA" \
		--cap-drop ALL --security-opt no-new-privileges:true --pids-limit 256 \
		--tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m \
		"${mounts[@]}" \
		--env AGENTIUM_DISABLE_DOTENV=1 \
		"$candidate_image" "${command[@]}"
}

run_candidate_migration() {
	local operation
	case "$*" in
	"alembic upgrade head") operation=upgrade ;;
	"alembic current") operation=current ;;
	"alembic heads") operation=heads ;;
	*) return 64 ;;
	esac
	[[ "$#" -eq 2 || ( "$#" -eq 3 && "$operation" == "upgrade" ) ]] || return 64
	run_candidate_database_tool "$@"
}

live_writer_audit_secret_is_owned() {
	[[ -f "$LIVE_WRITER_AUDIT_SECRET" && ! -L "$LIVE_WRITER_AUDIT_SECRET" ]] || return 1
	[[ "$(stat -c '%a:%u:%h' "$LIVE_WRITER_AUDIT_SECRET")" == "600:$(id -u):1" ]]
}

write_live_writer_audit_secret() {
	[[ ! -e "$LIVE_WRITER_AUDIT_SECRET" && ! -L "$LIVE_WRITER_AUDIT_SECRET" ]] || return 1
	verify_runtime_env_bundle >/dev/null || return 1
	python3 - "$APPLICATION_ENV_PATH" "$FROZEN_COMPOSE_ENV" "$LIVE_WRITER_AUDIT_SECRET" \
		"$POSTGRES_USER" "$POSTGRES_DB" <<'PY'
import json
import os
import re
import stat
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

application_path, compose_path, target_path = map(Path, sys.argv[1:4])
expected_user, expected_database = sys.argv[4:]


def read_dotenv(path: Path) -> dict[str, str]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            raise SystemExit("live-writer source environment is unsafe")
        raw = os.read(fd, 1024 * 1024 + 1)
    finally:
        os.close(fd)
    if len(raw) != details.st_size or len(raw) > 1024 * 1024:
        raise SystemExit("live-writer source environment changed or is oversized")
    values: dict[str, str] = {}
    for line in raw.decode("utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        key, separator, value = stripped.partition("=")
        key = key.strip()
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or key in values:
            raise SystemExit("live-writer source environment is malformed")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


application = read_dotenv(application_path)
compose = read_dotenv(compose_path)
database_url = application.get("DATABASE_URL", "")
try:
    database = urlsplit(database_url)
    database_port = database.port or 5432
except ValueError as exc:
    raise SystemExit("live-writer DATABASE_URL is invalid") from exc
if (
    database.scheme not in {"postgres", "postgresql", "postgresql+psycopg"}
    or unquote(database.username or "") != expected_user
    or not unquote(database.password or "")
    or database.hostname != "agentium-pg"
    or database_port != 5432
    or database.path != f"/{expected_database}"
    or database.query
    or database.fragment
):
    raise SystemExit("live-writer DATABASE_URL leaves the PostgreSQL boundary")
internal_url = application.get("LIVEKIT_INTERNAL_URL", "")
try:
    internal = urlsplit(internal_url)
    internal_port = internal.port or 80
except ValueError as exc:
    raise SystemExit("live-writer LiveKit URL is invalid") from exc
if (
    internal.scheme != "http"
    or internal.hostname != "agentium-livekit"
    or internal_port != 7880
    or internal.path not in {"", "/"}
    or internal.query
    or internal.fragment
    or internal.username
    or internal.password
):
    raise SystemExit("live-writer LiveKit URL leaves the internal boundary")
api_key = application.get("LIVEKIT_API_KEY", "")
api_secret = application.get("LIVEKIT_API_SECRET", "")
if (
    len(api_key) < 6
    or len(api_secret) < 32
    or api_key != compose.get("LIVEKIT_API_KEY")
    or api_secret != compose.get("LIVEKIT_API_SECRET")
    or any(token in api_key + api_secret + database_url for token in ("$", "`", "\x00", "\r", "\n"))
):
    raise SystemExit("live-writer credentials are absent, dynamic, or disagree")
payload = {
    "DATABASE_URL": database_url,
    "LIVEKIT_API_KEY": api_key,
    "LIVEKIT_API_SECRET": api_secret,
    "LIVEKIT_ENABLED": "true",
    "LIVEKIT_INTERNAL_URL": internal_url.rstrip("/"),
    "LIVEKIT_URL": internal_url.rstrip("/"),
}
fd = os.open(
    target_path,
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0),
    0o600,
)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
except BaseException:
    try:
        target_path.unlink()
    except FileNotFoundError:
        pass
    raise
directory_fd = os.open(target_path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PY
	live_writer_audit_secret_is_owned
}

remove_live_writer_audit_secret() {
	[[ -e "$LIVE_WRITER_AUDIT_SECRET" || -L "$LIVE_WRITER_AUDIT_SECRET" ]] || return 0
	live_writer_audit_secret_is_owned || return 1
	python3 - "$LIVE_WRITER_AUDIT_SECRET" <<'PY'
import os
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
fd = os.open(path, flags)
try:
    details = os.fstat(fd)
    if (
        not stat.S_ISREG(details.st_mode)
        or details.st_uid != os.geteuid()
        or stat.S_IMODE(details.st_mode) != 0o600
        or details.st_nlink != 1
    ):
        raise SystemExit("live-writer audit secret ownership changed")
finally:
    os.close(fd)
path.unlink()
directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PY
}

assert_live_writer_audit_network_identity() {
	docker network inspect "$LIVE_WRITER_AUDIT_NETWORK" >/dev/null 2>&1 || return 1
	[[ "$(docker network inspect --format '{{.Driver}}' "$LIVE_WRITER_AUDIT_NETWORK")" == "bridge" ]] || return 1
	[[ "$(docker network inspect --format '{{.Internal}}' "$LIVE_WRITER_AUDIT_NETWORK")" == "true" ]] || return 1
	[[ "$(docker network inspect --format '{{.Scope}}' "$LIVE_WRITER_AUDIT_NETWORK")" == "local" ]] || return 1
	[[ "$(docker network inspect --format '{{index .Labels \"ai.papai.agentium.safe-deploy.live-writer-network\"}}' "$LIVE_WRITER_AUDIT_NETWORK")" == "1" ]] || return 1
	[[ "$(docker network inspect --format '{{index .Labels \"ai.papai.agentium.safe-deploy.deployment_id\"}}' "$LIVE_WRITER_AUDIT_NETWORK")" == "$DEPLOYMENT_ID" ]] || return 1
	[[ "$(docker network inspect --format '{{index .Labels \"ai.papai.agentium.safe-deploy.candidate_sha\"}}' "$LIVE_WRITER_AUDIT_NETWORK")" == "$EXPECTED_SHA" ]] || return 1
}

assert_live_writer_audit_boundary_active() {
	local attached name total=0 postgres=0 livekit=0
	live_writer_audit_secret_is_owned || return 1
	assert_live_writer_audit_network_identity || return 1
	attached="$(docker network inspect --format '{{range .Containers}}{{println .Name}}{{end}}' "$LIVE_WRITER_AUDIT_NETWORK")" || return 1
	while IFS= read -r name; do
		[[ -z "$name" ]] && continue
		((total += 1))
		case "$name" in
		agentium-pg) ((postgres += 1)) ;;
		agentium-livekit) ((livekit += 1)) ;;
		*) return 1 ;;
		esac
	done < <(printf '%s\n' "$attached")
	[[ "$total" -eq 2 && "$postgres" -eq 1 && "$livekit" -eq 1 ]]
}

assert_no_live_writer_audit_boundary_residue() {
	local networks containers
	[[ ! -e "$LIVE_WRITER_AUDIT_SECRET" && ! -L "$LIVE_WRITER_AUDIT_SECRET" ]] || return 1
	docker network inspect "$LIVE_WRITER_AUDIT_NETWORK" >/dev/null 2>&1 && return 1
	networks="$(docker network ls -q --filter label=ai.papai.agentium.safe-deploy.live-writer-network=1)" || return 1
	[[ -z "$networks" ]] || return 1
	containers="$(docker ps -aq --filter label=ai.papai.agentium.safe-deploy.live-writer-boundary=1)" || return 1
	[[ -z "$containers" ]]
}

cleanup_current_live_writer_audit_boundary() {
	local attached name postgres=0 livekit=0
	if [[ -e "$LIVE_WRITER_AUDIT_SECRET" || -L "$LIVE_WRITER_AUDIT_SECRET" ]]; then
		live_writer_audit_secret_is_owned || return 1
	fi
	if docker network inspect "$LIVE_WRITER_AUDIT_NETWORK" >/dev/null 2>&1; then
		assert_live_writer_audit_network_identity || return 1
		attached="$(docker network inspect --format '{{range .Containers}}{{println .Name}}{{end}}' "$LIVE_WRITER_AUDIT_NETWORK")" || return 1
		while IFS= read -r name; do
			[[ -z "$name" ]] && continue
			case "$name" in
			agentium-pg) postgres=1 ;;
			agentium-livekit) livekit=1 ;;
			*) return 1 ;;
			esac
		done < <(printf '%s\n' "$attached")
		if [[ "$livekit" -eq 1 ]]; then
			docker network disconnect "$LIVE_WRITER_AUDIT_NETWORK" agentium-livekit >/dev/null || return 1
		fi
		if [[ "$postgres" -eq 1 ]]; then
			docker network disconnect "$LIVE_WRITER_AUDIT_NETWORK" agentium-pg >/dev/null || return 1
		fi
		docker network rm "$LIVE_WRITER_AUDIT_NETWORK" >/dev/null || return 1
	fi
	remove_live_writer_audit_secret || return 1
	LIVE_WRITER_AUDIT_ACTIVE=0
}

reconcile_live_writer_audit_boundary() {
	if [[ -e "$LIVE_WRITER_AUDIT_SECRET" || -L "$LIVE_WRITER_AUDIT_SECRET" ]] ||
		docker network inspect "$LIVE_WRITER_AUDIT_NETWORK" >/dev/null 2>&1; then
		STAGE="reconcile owned live-writer audit boundary"
		cleanup_current_live_writer_audit_boundary ||
			die "Frontière audit LiveKit courante non nettoyable; gate inchangé"
	fi
	assert_no_live_writer_audit_boundary_residue ||
		die "Frontière audit LiveKit étrangère/orpheline détectée; aucune suppression automatique"
}

open_live_writer_audit_boundary() {
	assert_no_live_writer_audit_boundary_residue || return 1
	LIVE_WRITER_AUDIT_ACTIVE=1
	write_live_writer_audit_secret || return 1
	docker network create --driver bridge --internal \
		--label ai.papai.agentium.safe-deploy.live-writer-network=1 \
		--label "ai.papai.agentium.safe-deploy.deployment_id=$DEPLOYMENT_ID" \
		--label "ai.papai.agentium.safe-deploy.candidate_sha=$EXPECTED_SHA" \
		"$LIVE_WRITER_AUDIT_NETWORK" >/dev/null || return 1
	docker network connect --alias agentium-pg "$LIVE_WRITER_AUDIT_NETWORK" agentium-pg >/dev/null || return 1
	docker network connect --alias agentium-livekit "$LIVE_WRITER_AUDIT_NETWORK" agentium-livekit >/dev/null || return 1
	assert_live_writer_audit_boundary_active
}

run_candidate_live_writer_audit_tool() {
	local candidate_image launcher
	[[ "$#" -eq 6 && "$1" == "python" && "$2" == "scripts/audit_livekit_quiescence.py" &&
		"$3" == "--expected-sha" && "$4" == "$EXPECTED_SHA" &&
		"$5" == "--deployment-id" && "$6" == "$DEPLOYMENT_ID" ]] || return 64
	assert_live_writer_audit_boundary_active || return 1
	candidate_image="$(candidate_override_image_id agentium-backend)" || return 1
	launcher="$(cat <<'PY'
import json
import os
import sys

with open("/run/secrets/live-writer-audit.json", encoding="utf-8") as handle:
    payload = json.load(handle)
expected = {
    "DATABASE_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET",
    "LIVEKIT_ENABLED", "LIVEKIT_INTERNAL_URL", "LIVEKIT_URL",
}
if set(payload) != expected or any(not isinstance(payload[key], str) or not payload[key] for key in expected):
    raise SystemExit("live-writer secret contract differs")
environment = {
    "AGENTIUM_DISABLE_DOTENV": "1",
    "AGENTIUM_IMAGE_REVISION": os.environ.get("AGENTIUM_IMAGE_REVISION", ""),
    "HOME": "/home/agentium",
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONPATH": "/app/backend:/app",
    "PYTHONUNBUFFERED": "1",
    **payload,
}
os.execvpe(sys.argv[1], sys.argv[1:], environment)
PY
)"
	docker run --rm --read-only --network "$LIVE_WRITER_AUDIT_NETWORK" \
		--name "agentium-live-audit-${EXPECTED_SHA:0:12}-${MIGRATION_NETWORK_KEY}" \
		--label ai.papai.agentium.safe-deploy.oneoff=1 \
		--label ai.papai.agentium.safe-deploy.live-writer-boundary=1 \
		--label "ai.papai.agentium.safe-deploy.deployment_id=$DEPLOYMENT_ID" \
		--label "ai.papai.agentium.safe-deploy.candidate_sha=$EXPECTED_SHA" \
		--cap-drop ALL --security-opt no-new-privileges:true --pids-limit 256 \
		--tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m \
		--mount "type=bind,src=$LIVE_WRITER_AUDIT_SECRET,dst=/run/secrets/live-writer-audit.json,readonly" \
		--entrypoint python "$candidate_image" -c "$launcher" \
		agentium-live-writer-launcher "$@"
}

run_candidate_live_writer_audit_command() {
	local code=0 cleanup_failed=0
	if open_live_writer_audit_boundary; then
		if run_candidate_live_writer_audit_tool "$@"; then :; else code=$?; fi
	else
		code=$?
	fi
	if cleanup_current_candidate_oneoffs; then :; else cleanup_failed=1; fi
	if cleanup_current_live_writer_audit_boundary; then :; else cleanup_failed=1; fi
	[[ "$cleanup_failed" -eq 0 ]] || die "Frontière audit LiveKit non nettoyable; gate maintenu fermé"
	return "$code"
}

on_process_exit() {
	local code="$1" persisted_phase=""
	trap - ERR EXIT HUP INT TERM
	set +e
	if [[ -f "$PHASE_FILE" ]]; then persisted_phase="$(<"$PHASE_FILE")"; fi
	case "$persisted_phase" in
	opening_forward | rollback_opening)
		if [[ "$OPENING_BOUNDARY_SEALED" -ne 1 ]]; then
			if (seal_public_opening_boundary_fail_closed "$persisted_phase"); then
				OPENING_BOUNDARY_SEALED=1
			else
				printf 'XX  Reclosure fail-closed incomplète à la sortie (%s).\n' "$persisted_phase" >&2
				code=1
			fi
		fi
		;;
	esac
	if [[ "$REHEARSAL_ACTIVE" -eq 1 || -e "$REHEARSAL_INTENT" || -L "$REHEARSAL_INTENT" ]]; then
		cleanup_current_rehearsal || {
			printf 'XX  Rehearsal privé non nettoyé; gate et phase restent inchangés.\n' >&2
			[[ "$code" -ne 0 ]] || code=1
		}
	fi
	cleanup_current_candidate_oneoffs || {
		printf 'XX  One-off candidat non nettoyé; gate et phase restent inchangés.\n' >&2
		[[ "$code" -ne 0 ]] || code=1
	}
	cleanup_current_candidate_migration_boundary || {
		printf 'XX  Frontière migration candidate non nettoyée; gate et phase restent inchangés.\n' >&2
		[[ "$code" -ne 0 ]] || code=1
	}
	cleanup_current_live_writer_audit_boundary || {
		printf 'XX  Frontière audit LiveKit non nettoyée; gate et phase restent inchangés.\n' >&2
		[[ "$code" -ne 0 ]] || code=1
	}
	exit "$code"
}

rehearse_candidate_database() {
	local dump="$1" label="$2"
	local rehearsal_root="$REHEARSAL_BASE/${DEPLOYMENT_ID}-${label}"
	local pgdata="$rehearsal_root/pgdata" socket_dir="$rehearsal_root/socket"
	local container="agentium-rehearsal-${EXPECTED_SHA:0:12}-${label}"
	local candidate_image postgres_image database_url attempt code=0 value restored_revision
	local -a audit_args=()
	[[ "$label" =~ ^[a-z]+$ ]] || die "Label de rehearsal invalide"
	[[ "$rehearsal_root" == "$REHEARSAL_BASE/${DEPLOYMENT_ID}-${label}" ]] || die "Chemin de rehearsal invalide"
	verify_backup "$dump" || die "Dump de rehearsal invalide: $dump"
	assert_no_rehearsal_residue || die "Résidu rehearsal présent avant création"
	mkdir -p "$REHEARSAL_BASE"
	chmod 0700 "$REHEARSAL_BASE"
	[[ "$(stat -c '%d' "$REHEARSAL_BASE")" == "$(stat -c '%d' "$DATA_ROOT")" ]] || die "Rehearsal hors disque data"
	write_rehearsal_intent "$label" "$rehearsal_root" "$container"
	REHEARSAL_ACTIVE=1
	mkdir -p "$pgdata" "$socket_dir"
	chmod 0700 "$rehearsal_root" "$pgdata"
	chmod 0770 "$socket_dir"
	database_url="postgresql://rehearsal@/rehearsal?host=/run/rehearsal-pg"
	candidate_image="$(candidate_override_image_id agentium-backend)"
	postgres_image="$(docker inspect --format '{{.Image}}' agentium-pg 2>/dev/null || true)"
	[[ "$postgres_image" =~ ^sha256:[0-9a-f]{64}$ ]] || die "Image PostgreSQL live non épinglable pour le rehearsal"
	[[ "$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' agentium-pg | awk -F= '$1 == "PG_MAJOR" {print $2; exit}')" == "17" ]] ||
		die "Le rehearsal exige la même majeure PostgreSQL 17 que le runtime live"
	[[ "$(docker image inspect --format '{{.Id}}' "$postgres_image" 2>/dev/null || true)" == "$postgres_image" ]] ||
		die "Image PostgreSQL live absente du moteur Docker local"
	while IFS= read -r value; do audit_args+=("$value"); done < <(candidate_audit_args)
	if ! docker run --rm --read-only --network none --user root \
		--label ai.papai.agentium.rehearsal=1 \
		--label "ai.papai.agentium.rehearsal.deployment_id=$DEPLOYMENT_ID" \
		-v "$pgdata:/var/lib/postgresql/data" -v "$socket_dir:/var/run/postgresql" "$postgres_image" \
		sh -eu -c 'chown -R postgres:postgres /var/lib/postgresql/data /var/run/postgresql'; then code=1; fi
	if [[ "$code" -eq 0 ]] && ! docker run -d --read-only --name "$container" --network none \
		--label ai.papai.agentium.rehearsal=1 \
		--label "ai.papai.agentium.rehearsal.deployment_id=$DEPLOYMENT_ID" \
		--tmpfs /tmp \
		-v "$pgdata:/var/lib/postgresql/data" \
		-v "$socket_dir:/var/run/postgresql" \
		-e POSTGRES_DB=rehearsal -e POSTGRES_USER=rehearsal -e POSTGRES_HOST_AUTH_METHOD=trust \
		"$postgres_image" >/dev/null; then code=1; fi
	if [[ "$code" -eq 0 ]]; then
		for attempt in $(seq 1 30); do
			docker exec "$container" pg_isready -U rehearsal -d rehearsal >/dev/null 2>&1 && break
			sleep 2
		done
		docker exec "$container" pg_isready -U rehearsal -d rehearsal >/dev/null 2>&1 || code=1
	fi
	if [[ "$code" -eq 0 ]]; then
		[[ "$(docker exec "$container" stat -c '%a' /var/run/postgresql/.s.PGSQL.5432)" == "777" ]] || code=1
	fi
	if [[ "$code" -eq 0 ]] && ! docker run --rm --read-only --network none --tmpfs /tmp \
		--label ai.papai.agentium.rehearsal=1 \
		--label "ai.papai.agentium.rehearsal.deployment_id=$DEPLOYMENT_ID" \
		-v "$socket_dir:/run/rehearsal-pg" "$candidate_image" \
		sh -eu -c 'test -S /run/rehearsal-pg/.s.PGSQL.5432'; then code=1; fi
	if [[ "$code" -eq 0 ]] && ! docker exec -i "$container" pg_restore --exit-on-error --no-owner --no-privileges \
		-U rehearsal -d rehearsal <"$dump"; then code=1; fi
	if [[ "$code" -eq 0 ]]; then
		restored_revision="$(docker exec "$container" psql -v ON_ERROR_STOP=1 -U rehearsal -d rehearsal -Atqc \
			'SELECT version_num FROM alembic_version ORDER BY version_num' 2>/dev/null || true)"
		[[ "$restored_revision" == "$(metadata previous_database_revision)" ]] || code=1
	fi
	if [[ "$code" -eq 0 ]] && ! docker run --rm --read-only --network none --tmpfs /tmp \
		--label ai.papai.agentium.rehearsal=1 \
		--label "ai.papai.agentium.rehearsal.deployment_id=$DEPLOYMENT_ID" \
		-v "$socket_dir:/run/rehearsal-pg" \
		-e DATABASE_URL="$database_url" "$candidate_image" alembic upgrade head; then code=1; fi
	if [[ "$code" -eq 0 ]]; then
		docker run --rm --read-only --network none --tmpfs /tmp \
			--label ai.papai.agentium.rehearsal=1 \
			--label "ai.papai.agentium.rehearsal.deployment_id=$DEPLOYMENT_ID" \
			-v "$socket_dir:/run/rehearsal-pg" \
			-e DATABASE_URL="$database_url" "$candidate_image" alembic current \
			>"$DEPLOY_DIR/rehearsal-${label}-alembic-current.txt" || code=1
	fi
	if [[ "$code" -eq 0 ]]; then
		docker run --rm --read-only --network none --tmpfs /tmp \
			--label ai.papai.agentium.rehearsal=1 \
			--label "ai.papai.agentium.rehearsal.deployment_id=$DEPLOYMENT_ID" \
			-v "$socket_dir:/run/rehearsal-pg" \
			-e DATABASE_URL="$database_url" "$candidate_image" \
			python -m scripts.audit_persisted_system_bindings "${audit_args[@]}" \
			>"$DEPLOY_DIR/rehearsal-${label}-bindings.json" || code=1
	fi
	cleanup_current_rehearsal || die "Nettoyage du rehearsal PostgreSQL impossible"
	unset database_url
	[[ "$code" -eq 0 ]] || die "Rehearsal PostgreSQL candidat en échec"
	python3 -c 'import json,sys; p=json.load(open(sys.argv[1], encoding="utf-8")); assert p["result"] == "passed" and p.get("workspace_count", 0) > 0 and p.get("system_count", 0) > 0' \
		"$DEPLOY_DIR/rehearsal-${label}-bindings.json" || die "Audit catalogue rehearsal en échec"
	chmod 0600 "$DEPLOY_DIR/rehearsal-${label}-alembic-current.txt" "$DEPLOY_DIR/rehearsal-${label}-bindings.json"
}

apply_preflight_checks() {
	local dirty
	STAGE="post-build apply preflight"
	assert_recorded_release_a_manifest_gate
	assert_recorded_workspace_target_gate
	assert_storage_capacity_and_layout
	verify_live_nginx_gate
	[[ "$(gate status)" == "open" ]] || die "Le gate doit être ouvert avant la première phase apply"
	[[ "$(git rev-parse HEAD)" == "$(metadata previous_sha)" ]] || die "Checkout live différent du SHA précédent préparé"
	[[ "$(active_application_sha)" == "$(metadata previous_sha)" ]] || die "Runtime principal différent du SHA précédent"
	assert_runtime_state_matches_capture
	assert_sftp_restart_policy_matches_capture
	assert_legacy_sftp_systemd_safe
	dirty="$(git status --porcelain --untracked-files=all)"
	[[ -z "$dirty" ]] || die "Checkout candidat sale après préparation"
	[[ "$(git rev-parse "origin/$BRANCH")" == "$EXPECTED_SHA" ]] || die "Référence distante locale différente du candidat"
	assert_preparation_fresh
	verify_candidate_images_and_rollback
}

build_candidate_in_worktree() {
	local code=0
	[[ "$BUILD_WORKTREE" == "$DATA_ROOT/deploy-builds/$DEPLOYMENT_ID" ]] || die "Worktree de build hors data root"
	if [[ -e "$BUILD_WORKTREE" ]]; then
		[[ "$(git -C "$BUILD_WORKTREE" rev-parse HEAD 2>/dev/null || true)" == "$EXPECTED_SHA" ]] || die "Worktree de build existant inattendu"
	else
		mkdir -p "$(dirname "$BUILD_WORKTREE")"
		git worktree add --detach "$BUILD_WORKTREE" "$EXPECTED_SHA"
	fi
	verify_runtime_env_bundle >/dev/null
	if ! env -i PATH="$COMPOSE_CLEAN_PATH" HOME="$COMPOSE_CLEAN_HOME" DOCKER_CONFIG="$COMPOSE_CLEAN_HOME/.docker" DOCKER_HOST="$DOCKER_LOCAL_HOST" \
		OMNIRAG_REPO_DIR="$BUILD_WORKTREE" AGENTIUM_DEPLOY_STATE_DIR="$ROLLBACK_DIR" \
		AGENTIUM_SAFE_DEPLOY_ORCHESTRATED=1 AGENTIUM_SAFE_DEPLOYMENT_DIR="$DEPLOY_DIR" \
		AGENTIUM_SAFE_ENV_BUNDLE_DIR="$ENV_BUNDLE_DIR" \
		AGENTIUM_SAFE_ENV_MANIFEST_SHA256="$ENV_MANIFEST_SHA256" \
		AGENTIUM_SAFE_ENV_BUNDLE_HELPER="$ENV_BUNDLE_HELPER" \
		AGENTIUM_SAFE_QDRANT_OVERRIDE_FILE="$FROZEN_QDRANT_OVERRIDE" \
		AGENTIUM_QDRANT_EFFECTIVE_API_KEY="$(qdrant_server_key read-only)" \
		bash "$FROZEN_DEPLOYER" --build-only --branch "$BRANCH" \
		--sha "$EXPECTED_SHA" --previous-sha "$(metadata previous_sha)"; then code=1; fi
	if ! git worktree remove --force "$BUILD_WORKTREE"; then code=1; fi
	git worktree prune
	[[ "$code" -eq 0 ]] || die "Build candidat isolé en échec"
}

prepare_impl() {
	local current
	current="$(phase)"
	[[ "$current" != "new" ]] ||
		die "Preflight obligatoire avant prepare/apply; aucune sauvegarde ni build n'a été lancé"
	if [[ "$current" == "prepared" || "$current" == "recovering_pre_migration" || "$current" == "rollback_closing" || "$current" == "closing_intent" || "$current" == "closing" || "$current" == "maintenance_closed" || "$current" == "quiesced" || "$current" == "backfill_pending" || "$current" == "backfill_applying" || "$current" == "migrated" || "$current" == "activated" || "$current" == "validation_starting" || "$current" == "validation_pending" || "$current" == "opening_forward" || "$current" == "opened" || "$current" == "completed" || "$current" == "rollback_restoring" || "$current" == "rolled_back_restored" || "$current" == "rollback_opening" || "$current" == "rolled_back" ]]; then
		[[ -f "$ROLLBACK_STATE" && "$(awk -F '\t' '$1 == "format" {print $2}' "$ROLLBACK_STATE")" == "3" ]] || die "Rollback v3 absent"
		assert_candidate_image_override_contract
		assert_rollback_image_override_contract
		verify_backup "$DEPLOY_DIR/postgres-preparation.dump" || die "Backup de préparation invalide"
		return
	fi
	preflight_checks
	initialize_metadata
	resolve_runtime_paths
	STAGE="storage baseline"
	ensure_storage_baseline
	STAGE="preparation database backup"
	create_backup preparation
	STAGE="candidate build"
	build_candidate_in_worktree
	[[ "$(awk -F '\t' '$1 == "format" { print $2 }' "$ROLLBACK_STATE")" == "3" ]] || die "Le candidat n'a pas produit un rollback v3"
	STAGE="candidate immutable OCI override"
	capture_candidate_image_override
	STAGE="rollback immutable OCI override"
	capture_rollback_image_override
	STAGE="candidate database rehearsal"
	rehearse_candidate_database "$DEPLOY_DIR/postgres-preparation.dump" preparation
	atomic_text "$PREPARED_AT_FILE" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
	set_phase prepared
}

sftp_open_deposit_fd_count() {
	local pid fd target count=0
	while read -r pid; do
		[[ "$pid" =~ ^[0-9]+$ ]] || continue
		sudo_command test -r "/proc/$pid/fd" || die "FD SFTP illisibles pour le PID $pid"
		while read -r fd; do
			[[ "$fd" =~ ^[0-9]+$ ]] || die "Descripteur SFTP non numérique"
			target="$(sudo_command readlink "/proc/$pid/fd/$fd" 2>/dev/null || true)"
			target="${target% (deleted)}"
			if [[ "$target" == "$SECURE_DEPOSIT_PATH"/* ]] && sudo_command test -f "/proc/$pid/fd/$fd"; then
				count=$((count + 1))
			fi
		done < <(sudo_command find "/proc/$pid/fd" -mindepth 1 -maxdepth 1 -printf '%f\n')
	done < <(docker top agentium-sftp -eo pid | awk 'NR > 1 { print $1 }')
	printf '%s\n' "$count"
}

sftp_established_connection_count() {
	local port
	port="$(sftp_host_port)"
	[[ "$port" =~ ^[0-9]+$ ]] || die "Port SFTP publié introuvable"
	ss -Htn | awk -v suffix=":$port" '$1 != "TIME-WAIT" && $4 ~ (suffix "$") { count++ } END { print count + 0 }'
}

writer_tcp_ports() {
	local kind service protocol _host_ip host_port _container_port
	printf '%s\n' 8000 8001 8080 "$(sftp_host_port)"
	while IFS=$'\t' read -r kind service protocol _host_ip host_port _container_port; do
		[[ "$kind" == "listener_binding" && "$service" == "agentium-livekit" && "$protocol" == "tcp" ]] || continue
		printf '%s\n' "$host_port"
	done <"$RUNTIME_STATE_FILE"
}

wait_for_existing_writer_connections_to_drain() {
	local attempt port count total
	local -a ports=()
	while IFS= read -r port; do
		[[ "$port" =~ ^[0-9]+$ ]] || die "Port writer capturé invalide"
		[[ " ${ports[*]} " == *" $port "* ]] || ports+=("$port")
	done < <(writer_tcp_ports)
	for attempt in $(seq 1 15); do
		total=0
		for port in "${ports[@]}"; do
			count="$(sudo_command ss -Htn state established "sport = :$port" | awk 'END { print NR + 0 }')"
			total=$((total + count))
		done
		[[ "$total" -eq 0 ]] && return
		sleep 2
	done
	die "$total connexion(s) writer établie(s) subsistent; arrêt refusé pour protéger les sessions métier"
}

quiesce_sftp() {
	local running paused connections fds
	enter_sftp_ingress_gate
	set_sftp_restart_policy_no
	running="$(docker inspect --format '{{.State.Running}}' agentium-sftp 2>/dev/null || printf false)"
	[[ "$running" == "true" ]] || { assert_sftp_restart_policy_no; return; }
	paused="$(docker inspect --format '{{.State.Paused}}' agentium-sftp)"
	[[ "$paused" == "true" ]] || docker pause agentium-sftp >/dev/null
	connections="$(sftp_established_connection_count)"
	fds="$(sftp_open_deposit_fd_count)"
	if [[ "$connections" -ne 0 || "$fds" -ne 0 ]]; then
		docker unpause agentium-sftp >/dev/null
		die "Gel refusé: SFTP a $connections connexion(s) et $fds FD dépôt ouvert(s)"
	fi
	# Explicitly leave Docker's Paused state before stop. This makes an
	# interrupted attempt replayable instead of leaving an unstartable SFTP
	# container. The firewall ingress gate remains closed and there are no
	# established sessions or open upload descriptors at this boundary.
	docker unpause agentium-sftp >/dev/null
	docker stop --time 30 agentium-sftp >/dev/null
	[[ "$(docker inspect --format '{{.State.Running}}' agentium-sftp)" == "false" ]] || die "SFTP écrit encore"
	assert_sftp_restart_policy_no
}

assert_rabbitmq_empty() {
	local label="${1:-quiesced}" output temporary
	[[ "$label" =~ ^[a-z-]+$ ]] || die "Label RabbitMQ invalide"
	output="$DEPLOY_DIR/rabbitmq-${label}.json"
	temporary="$DEPLOY_DIR/.rabbitmq-${label}.$$"
	docker exec agentium-rabbitmq rabbitmqctl list_queues --quiet \
		name messages_ready messages_unacknowledged --formatter json >"$temporary"
	chmod 0600 "$temporary"
	python3 - "$temporary" <<'PY'
import json, sys
from pathlib import Path
value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if not isinstance(value, list):
    raise SystemExit("RabbitMQ queue payload is not a list")
for row in value:
    if not isinstance(row, dict) or not isinstance(row.get("name"), str):
        raise SystemExit("RabbitMQ queue row is invalid")
    ready = row.get("messages_ready")
    unack = row.get("messages_unacknowledged")
    if not isinstance(ready, int) or not isinstance(unack, int):
        raise SystemExit("RabbitMQ queue counters are invalid")
    if ready != 0 or unack != 0:
        raise SystemExit("RabbitMQ contient encore des messages")
PY
	durable_replace_file "$temporary" "$output"
}

assert_postgres_quiescent() {
	local count
	count="$(docker exec agentium-pg psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc \
		"SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid();")"
	[[ "$count" == "0" ]] || die "PostgreSQL conserve $count connexion(s) applicative(s), même idle"
}

quiesce_all_writers() {
	local service current
	current="$(phase)"
	STAGE="maintenance gate"
	if [[ "$(gate status)" == "open" ]]; then gate enter; fi
	[[ "$(gate status)" == "closed" ]] || die "Le gate Nginx n'est pas fermé"
	STAGE="durable reboot restart barriers"
	disable_systemd_backend_restart
	set_application_restart_policies_no
	set_realtime_restart_policies_no
	set_sftp_restart_policy_no
	if [[ "$ROLLBACK_ACTIVE" -eq 0 && "$current" == "prepared" ]]; then
		# This durable boundary is recorded only after every reboot policy is
		# neutralised. A reboot from closing_intent therefore cannot revive a
		# public writer even though the host firewall rules are volatile.
		set_phase closing_intent
		current=closing_intent
	fi
	STAGE="runtime ingress barriers"
	enter_systemd_backend_ingress_gate
	enter_livekit_ingress_gate
	enter_sftp_ingress_gate
	if [[ "$ROLLBACK_ACTIVE" -eq 0 && "$current" == "closing_intent" ]]; then
		set_phase closing
		current=closing
	fi
	wait_for_existing_writer_connections_to_drain
	audit_live_writers_before_stop
	quiesce_sftp
	quiesce_identity_writer
	quiesce_legacy_sftp_systemd
	STAGE="legacy systemd writer quiescence"
	if [[ "$(systemd_backend_state)" == "active" ]]; then
		sudo_command systemctl stop agentium-backend.service
	fi
	[[ "$(systemd_backend_state)" != "active" ]] || die "agentium-backend.service écrit encore"
	assert_no_tcp_listener 8000 "Backend systemd"
	STAGE="legacy systemd unit and frozen environment adoption"
	adopt_systemd_unit_while_stopped
	STAGE="realtime writer quiescence"
	for service in agentium-livekit-agent agentium-livekit; do
		if docker inspect "$service" >/dev/null 2>&1 && [[ "$(docker inspect --format '{{.State.Running}}' "$service")" == "true" ]]; then
			ensure_container_unpaused "$service"
			docker stop --time 30 "$service" >/dev/null
		fi
	done
	assert_no_tcp_listener 7881 "LiveKit"
	assert_no_captured_livekit_listeners
	STAGE="application writer quiescence"
	for service in agentium-backend agentium-worker-cpu agentium-p4-maintenance; do
		if docker inspect "$service" >/dev/null 2>&1 && [[ "$(docker inspect --format '{{.State.Running}}' "$service")" == "true" ]]; then
			ensure_container_unpaused "$service"
			docker stop --time 45 "$service" >/dev/null
		fi
	done
	for service in agentium-backend agentium-worker-cpu agentium-p4-maintenance agentium-sftp agentium-livekit-agent agentium-livekit agentium-kc; do
		[[ "$(docker inspect --format '{{.State.Running}}' "$service" 2>/dev/null || printf false)" == "false" ]] || die "$service écrit encore"
	done
	assert_rabbitmq_empty
	assert_postgres_quiescent
	[[ -s "$DEPLOY_DIR/database-quiesced-all-baseline.tsv" ]] ||
		capture_sql_database_fingerprint "$DEPLOY_DIR/database-quiesced-all-baseline.tsv" all
	[[ -s "$DEPLOY_DIR/database-quiesced-migration-stable.tsv" ]] ||
		capture_sql_database_fingerprint "$DEPLOY_DIR/database-quiesced-migration-stable.tsv" migration-stable
	if [[ "$ROLLBACK_ACTIVE" -eq 0 ]]; then set_phase maintenance_closed; fi
	create_backup quiesced
	[[ -f "$STORAGE_QUIESCED" ]] || snapshot_storage "$STORAGE_QUIESCED"
	STAGE="quiesced database rehearsal"
	rehearse_candidate_database "$DEPLOY_DIR/postgres-quiesced.dump" quiesced
	STAGE="Secure Deposit read-only validation boundary"
	set_secure_deposit_mode ro
	STAGE="candidate checkout durable intent"
	ensure_candidate_checkout_intent
	STAGE="candidate source checkout"
	git reset --hard "$EXPECTED_SHA"
	[[ "$(git rev-parse HEAD)" == "$EXPECTED_SHA" ]] || die "Checkout candidat impossible après quiescence"
	if [[ "$ROLLBACK_ACTIVE" -eq 0 ]]; then set_phase quiesced; fi
}

workspace_app_backfill_args() {
	local workspace_id
	for workspace_id in "${CANARY_WORKSPACE_IDS[@]}"; do
		printf '%s\n' --workspace-id "$workspace_id"
	done
}

capture_workspace_app_backfill_analysis() {
	local output="$1" value
	local -a args=()
	assert_recorded_workspace_target_gate
	while IFS= read -r value; do args+=("$value"); done < <(workspace_app_backfill_args)
	[[ "$output" == "$DEPLOY_DIR"/.* && ! -e "$output" && ! -L "$output" ]] ||
		die "Cible temporaire d'analyse Workspace Apps invalide"
	if ! (umask 077; run_candidate python -m scripts.backfill_workspace_app_installations \
		"${args[@]}" >"$output"); then
		[[ -s "$output" ]] && chmod 0600 "$output"
		die "Dry-run Workspace Apps en échec"
	fi
	chmod 0600 "$output"
	assert_private_state_file "$output"
	python3 - "$output" "$(IFS=,; printf '%s' "${CANARY_WORKSPACE_IDS[*]}")" <<'PY'
import json, re, sys
p = json.load(open(sys.argv[1], encoding="utf-8"))
expected = sys.argv[2].split(",")
assert p.get("schema_version") == 1 and p.get("mode") == "dry-run"
assert p.get("selection") == "explicit_workspace_ids" and p.get("database_mutated") is False
assert p.get("requested_workspace_ids") == expected and p.get("workspace_count") == len(expected)
assert sorted(item.get("workspace_id") for item in p.get("workspaces", [])) == expected
assert all(change.get("workspace_id") in expected for change in p.get("changes", []))
assert p.get("ready") is True and p.get("blockers") == []
assert re.fullmatch(r"[0-9a-f]{64}", str(p.get("analysis_sha256") or ""))
PY

}

analyze_workspace_app_backfill() {
	local output="$1" temporary="$DEPLOY_DIR/.${output##*/}.$$"
	rm -f "$temporary"
	capture_workspace_app_backfill_analysis "$temporary"
	if [[ -e "$output" || -L "$output" ]]; then
		# The dry-run is deterministic.  If its durable publication won a race
		# with a crash before the phase transition, reuse it only when a fresh
		# read-only analysis is byte-for-byte identical.
		assert_private_state_file "$output"
		cmp -s "$temporary" "$output" || {
			rm -f "$temporary"
			die "Analyse Workspace Apps durable divergente à la reprise"
		}
		rm -f "$temporary"
	else
		durable_publish_file "$temporary" "$output"
	fi
}

publish_or_verify_workspace_app_post() {
	local temporary="$DEPLOY_DIR/.workspace-app-backfill-post.$$"
	rm -f "$temporary"
	capture_workspace_app_backfill_analysis "$temporary"
	if [[ -e "$WORKSPACE_APP_POST" || -L "$WORKSPACE_APP_POST" ]]; then
		assert_private_state_file "$WORKSPACE_APP_POST"
		cmp -s "$temporary" "$WORKSPACE_APP_POST" || die "Analyse post-backfill durable divergente à la reprise"
		rm -f "$temporary"
	else
		durable_publish_file "$temporary" "$WORKSPACE_APP_POST"
	fi
}

apply_workspace_app_backfill() {
	local phase_now value observed current_analysis expected="$WORKSPACE_APP_ANALYSIS_SHA"
	local temporary="$DEPLOY_DIR/.workspace-app-backfill-apply.$$" recovery="$DEPLOY_DIR/.workspace-app-backfill-recovery.$$"
	local -a args=()
	assert_recorded_workspace_target_gate
	[[ "$expected" =~ ^[0-9a-f]{64}$ ]] || die "--workspace-app-analysis-sha est requis pour appliquer le backfill"
	observed="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["analysis_sha256"])' "$WORKSPACE_APP_DRY_RUN")"
	[[ "$observed" == "$expected" ]] || die "Le SHA d’analyse Workspace Apps ne correspond pas au dry-run figé"
	while IFS= read -r value; do args+=("$value"); done < <(workspace_app_backfill_args)
	phase_now="$(phase)"
	[[ "$phase_now" == "backfill_pending" || "$phase_now" == "backfill_applying" ]] ||
		die "Apply Workspace Apps hors phase fermée"
	if [[ "$phase_now" == "backfill_pending" ]]; then set_phase backfill_applying; fi

	# The database transaction and the CLI report cannot be committed atomically.
	# On resume, a fresh analysis distinguishes the only two safe states:
	# unchanged (replay the idempotent transaction) or fully converged (the
	# commit won and only report publication was interrupted).  Any partial or
	# ambiguous state remains fail-closed.
	if [[ ! -s "$WORKSPACE_APP_APPLY" ]]; then
		rm -f "$recovery"
		capture_workspace_app_backfill_analysis "$recovery"
		current_analysis="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["analysis_sha256"])' "$recovery")"
		if [[ "$current_analysis" == "$expected" ]]; then
			rm -f "$temporary"
			if ! (umask 077; run_candidate python -m scripts.backfill_workspace_app_installations \
				"${args[@]}" --apply --expected-analysis-sha256 "$expected" \
				--actor "safe-deploy:$DEPLOYMENT_ID" >"$temporary"); then
				[[ -s "$temporary" ]] && durable_publish_file "$temporary" "$DEPLOY_DIR/workspace-app-backfill-apply-failed.json"
				die "Apply Workspace Apps en échec"
			fi
			durable_publish_file "$temporary" "$WORKSPACE_APP_APPLY"
		elif python3 - "$recovery" <<'PY'
import json, sys
p = json.load(open(sys.argv[1], encoding="utf-8"))
raise SystemExit(0 if p.get("ready") is True and p.get("blockers") == [] and
                 all(change.get("operation") == "none" for change in p.get("changes", [])) else 1)
PY
		then
			python3 - "$WORKSPACE_APP_DRY_RUN" "$recovery" "$temporary" "$expected" <<'PY'
import hashlib, json, sys
from pathlib import Path
dry_path, post_path, output = map(Path, sys.argv[1:4])
expected = sys.argv[4]
dry = json.loads(dry_path.read_text(encoding="utf-8"))
post = json.loads(post_path.read_text(encoding="utf-8"))
installs = [change for change in dry.get("changes", []) if change.get("operation") == "install"]
contracts = sorted(
    ({
        "workspace_id_sha256": hashlib.sha256(
            json.dumps([str(change["workspace_id"])], separators=(",", ":")).encode()
        ).hexdigest(),
        "app_id": str(change["app_id"]),
    } for change in installs),
    key=lambda item: (item["workspace_id_sha256"], item["app_id"]),
)
payload = {
    "schema_version": 1,
    "mode": "apply-recovered",
    "analysis_sha256": expected,
    "applied_count": len(installs),
    "applied_contracts": contracts,
    "recovered_after_commit": True,
    "post_analysis_sha256": post.get("analysis_sha256"),
    "legacy_settings_mutated": False,
    "member_entitlements_mutated": False,
}
with output.open("x", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY
			durable_publish_file "$temporary" "$WORKSPACE_APP_APPLY"
		else
			die "État Workspace Apps partiel ou ambigu après interruption"
		fi
		rm -f "$recovery"
	else
		assert_private_state_file "$WORKSPACE_APP_APPLY"
	fi
	publish_or_verify_workspace_app_post
	python3 - "$WORKSPACE_APP_APPLY" "$WORKSPACE_APP_POST" "$expected" "$(IFS=,; printf '%s' "${CANARY_WORKSPACE_IDS[*]}")" <<'PY'
import hashlib, json, sys
apply = json.load(open(sys.argv[1], encoding="utf-8"))
post = json.load(open(sys.argv[2], encoding="utf-8"))
expected = sys.argv[3]
workspace_ids = sys.argv[4].split(",")
workspace_hashes = {
    hashlib.sha256(json.dumps([value], separators=(",", ":")).encode()).hexdigest()
    for value in workspace_ids
}
assert apply.get("mode") in {"apply", "apply-recovered"} and apply.get("analysis_sha256") == expected
assert apply.get("legacy_settings_mutated") is False
assert apply.get("member_entitlements_mutated") is False
if apply.get("mode") == "apply":
    assert all(item.get("workspace_id") in workspace_ids for item in apply.get("applied", []))
else:
    assert all(
        item.get("workspace_id_sha256") in workspace_hashes
        for item in apply.get("applied_contracts", [])
    )
assert post.get("ready") is True and post.get("blockers") == []
assert post.get("requested_workspace_ids") == workspace_ids
assert sorted(item.get("workspace_id") for item in post.get("workspaces", [])) == workspace_ids
assert all(change.get("workspace_id") in workspace_ids for change in post.get("changes", []))
assert all(change.get("operation") == "none" for change in post.get("changes", []))
PY
	capture_candidate_binding_contract "$DEPLOY_DIR/post-migration-bindings.json"
	capture_sql_database_fingerprint "$DEPLOY_DIR/database-post-migration-all.tsv" all
	set_phase migrated
}

migrate_candidate() {
	local current_heads image_heads code=0 cleanup_failed=0
	local current_temporary="$DEPLOY_DIR/.alembic-current.$$"
	local heads_temporary="$DEPLOY_DIR/.alembic-heads.$$"
	STAGE="candidate migration"
	assert_recorded_workspace_target_gate
	verify_backup "$DEPLOY_DIR/postgres-quiesced.dump" || die "Backup quiescé durable absent avant migration"
	rm -f "$current_temporary" "$heads_temporary"
	if open_candidate_migration_boundary; then
		if run_candidate_migration alembic upgrade head; then :; else code=$?; fi
		if [[ "$code" -eq 0 ]]; then
			if run_candidate_migration alembic current >"$current_temporary"; then :; else code=$?; fi
		fi
		if [[ "$code" -eq 0 ]]; then
			if run_candidate_migration alembic heads >"$heads_temporary"; then :; else code=$?; fi
		fi
	else
		code=$?
	fi
	if cleanup_current_candidate_oneoffs; then :; else cleanup_failed=1; fi
	if cleanup_current_candidate_migration_boundary; then :; else cleanup_failed=1; fi
	[[ "$cleanup_failed" -eq 0 ]] || die "Frontière migration candidate non nettoyable; gate maintenu fermé"
	if [[ "$code" -ne 0 ]]; then
		rm -f "$current_temporary" "$heads_temporary"
		return "$code"
	fi
	chmod 0600 "$current_temporary" "$heads_temporary"
	durable_replace_file "$current_temporary" "$DEPLOY_DIR/alembic-current.txt"
	durable_replace_file "$heads_temporary" "$DEPLOY_DIR/alembic-heads.txt"
	current_heads="$(awk '/\(head\)/ { print $1 }' "$DEPLOY_DIR/alembic-current.txt" | sort -u)"
	image_heads="$(awk '/\(head\)/ { print $1 }' "$DEPLOY_DIR/alembic-heads.txt" | sort -u)"
	[[ -n "$current_heads" && "$current_heads" == "$image_heads" ]] || die "Migration candidate non alignée"
	atomic_text "$DEPLOY_DIR/candidate-database-revision" "$current_heads"
	assert_additive_migration_contract
	analyze_workspace_app_backfill "$WORKSPACE_APP_DRY_RUN"
	set_phase backfill_pending
	say "Backfill Workspace Apps prêt. Reprendre avec --workspace-app-analysis-sha $(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[\"analysis_sha256\"])' "$WORKSPACE_APP_DRY_RUN")"
}

original_runtime_state() {
	awk -F '\t' -v service="$1" '$1 == "container_state" && $2 == service { print $3; exit }' "$ROLLBACK_STATE"
}

stage_auxiliary_candidate_state() {
	local service desired expected_image actual_image revision
	service=agentium-p4-maintenance
	desired="$(original_runtime_state "$service")"
	case "$desired" in
	running | stopped)
		docker rm -f "$service" >/dev/null 2>&1 || true
		AGENTIUM_PIN_CANDIDATE_IMAGES=1 compose create --no-build --force-recreate "$service"
		assert_candidate_container_image "$service"
		;;
	absent) docker rm -f "$service" >/dev/null 2>&1 || true ;;
	*) die "État runtime v3 absent pour $service" ;;
	esac

	# Release B deliberately does not replace the Secure Deposit transport.
	# Its positive login/subsystem proof belongs to Release A, so preserve the
	# exact attested container and image rather than silently rebuilding it from
	# the candidate backend image and proving only an SSH banner.
	service=agentium-sftp
	desired="$(original_runtime_state "$service")"
	case "$desired" in
	running | stopped)
		docker inspect "$service" >/dev/null 2>&1 || die "SFTP Release A épinglé absent"
		expected_image="$(awk -F '\t' '$1 == "service" && $2 == "agentium-sftp" { print $3; exit }' "$ROLLBACK_STATE")"
		actual_image="$(docker inspect --format '{{.Image}}' "$service")"
		[[ "$actual_image" == "$expected_image" ]] || die "Image SFTP différente de la Release A attestée"
		revision="$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$actual_image")"
		[[ "$revision" == "$(metadata sftp_release_sha)" ]] || die "Révision SFTP non liée au transport épinglé"
		[[ "$actual_image" == "$(metadata sftp_image_id)" ]] || die "Image SFTP différente de l'identité figée"
		ensure_container_unpaused "$service"
		docker stop --time 30 "$service" >/dev/null 2>&1 || true
		[[ "$(docker inspect --format '{{.State.Running}}' "$service")" == "false" ]] || die "SFTP Release A reste actif pendant les canaris"
		set_sftp_restart_policy_no
		;;
	absent) ! docker inspect "$service" >/dev/null 2>&1 || die "SFTP devait rester absent" ;;
	*) die "État runtime v3 absent pour $service" ;;
	esac
}

normalize_binding_contract() {
	local raw="$1" output="$2" temporary="$DEPLOY_DIR/.${output##*/}.$$"
	python3 - "$raw" "$temporary" <<'PY'
import json, sys
from pathlib import Path
p = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert p.get("result") == "passed" and p.get("workspace_count", 0) > 0 and p.get("system_count", 0) > 0
fields = ("workspace_id", "system_id", "status", "capability_id", "effective_skill_count", "adaptive_policy_bound")
rows = []
for row in p.get("systems", []):
    assert row.get("result") == "passed"
    normalized = {field: row.get(field) for field in fields}
    assert isinstance(normalized["workspace_id"], str) and isinstance(normalized["system_id"], str)
    assert isinstance(normalized["effective_skill_count"], int) and not isinstance(normalized["effective_skill_count"], bool)
    assert isinstance(normalized["adaptive_policy_bound"], bool)
    rows.append(normalized)
rows.sort(key=lambda row: (row["workspace_id"], row["system_id"]))
assert len(rows) == p["system_count"]
Path(sys.argv[2]).write_text(json.dumps({"schema_version": 1, "kind": "system_catalog_binding_contract", "systems": rows}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
	chmod 0600 "$temporary"
	durable_replace_file "$temporary" "$output"
}

capture_candidate_binding_contract() {
	local output="$1" value raw="$DEPLOY_DIR/.${output##*/}.raw.$$"
	local -a audit_args=()
	while IFS= read -r value; do audit_args+=("$value"); done < <(candidate_audit_args)
	run_candidate python -m scripts.audit_persisted_system_bindings "${audit_args[@]}" >"$raw"
	normalize_binding_contract "$raw" "$output"
	rm -f "$raw"
}

capture_running_binding_contract() {
	local output="$1" value raw="$DEPLOY_DIR/.${output##*/}.raw.$$"
	local -a audit_args=()
	while IFS= read -r value; do audit_args+=("$value"); done < <(candidate_audit_args)
	docker exec -w /app/backend agentium-backend \
		python -m scripts.audit_persisted_system_bindings "${audit_args[@]}" >"$raw"
	normalize_binding_contract "$raw" "$output"
	rm -f "$raw"
}

capture_sql_database_fingerprint() {
	local output="$1" scope="$2" temporary="$DEPLOY_DIR/.${output##*/}.$$"
	local table sequence row_count digest table_predicate row_expression
	case "$scope" in
	all) table_predicate="TRUE" ;;
	migration-stable)
		table_predicate="tablename NOT IN ('alembic_version','value_loop_operations','value_scenarios','value_simulations','value_action_executions','value_measurements','workspace_app_installations','workspace_app_operations','workspace_app_lifecycle_step_receipts')"
		;;
	tenant-core)
		table_predicate="(tablename IN ('workspaces','systems','system_versions','flows','collections','skills','capabilities') OR tablename LIKE 'workspace\\_%' ESCAPE '\\' OR tablename LIKE 'system\\_%' ESCAPE '\\' OR tablename LIKE '%entitlement%')"
		;;
	*) die "Scope d'empreinte SQL invalide: $scope" ;;
	esac
	(umask 077
		{
			printf 'schema_version\t1\nprofile\tagentium-sql-table-fingerprint-v1\nscope\t%s\n' "$scope"
			while IFS= read -r table; do
				[[ "$table" =~ ^[a-z0-9_]+$ ]] || die "Nom de table PostgreSQL non sûr: $table"
				row_count="$(docker exec agentium-pg psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT count(*) FROM public.\"$table\"")"
				[[ "$row_count" =~ ^[0-9]+$ ]] || die "Comptage PostgreSQL invalide pour $table"
				row_expression='to_jsonb(t)'
				if [[ "$scope" == "migration-stable" ]]; then
					case "$table" in
					system_versions) row_expression="to_jsonb(t) - ARRAY['configuration_snapshot']::text[]" ;;
					skill_invocations) row_expression="to_jsonb(t) - ARRAY['execution_snapshot','cost_measured']::text[]" ;;
					systems | contexts) row_expression="to_jsonb(t) - ARRAY['blueprint_key']::text[]" ;;
					decisions) row_expression="to_jsonb(t) - ARRAY['scenario_id']::text[]" ;;
					esac
				fi
				digest="$(docker exec agentium-pg psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "COPY (SELECT ($row_expression)::text FROM public.\"$table\" AS t ORDER BY md5(($row_expression)::text), ($row_expression)::text) TO STDOUT" | sha256sum | awk '{print $1}')"
				[[ "$digest" =~ ^[0-9a-f]{64}$ ]] || die "Empreinte PostgreSQL invalide pour $table"
				printf 'table\t%s\t%s\t%s\n' "$table" "$row_count" "$digest"
			done < <(docker exec agentium-pg psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='public' AND $table_predicate ORDER BY tablename")
			if [[ "$scope" == "all" ]]; then
				while IFS= read -r sequence; do
					[[ "$sequence" =~ ^[a-z0-9_]+$ ]] || die "Nom de séquence PostgreSQL non sûr: $sequence"
					digest="$(docker exec agentium-pg psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT last_value::text || ':' || is_called::text FROM public.\"$sequence\"" | sha256sum | awk '{print $1}')"
					[[ "$digest" =~ ^[0-9a-f]{64}$ ]] || die "Empreinte PostgreSQL invalide pour la séquence $sequence"
					printf 'sequence\t%s\t%s\n' "$sequence" "$digest"
				done < <(docker exec agentium-pg psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT sequencename FROM pg_catalog.pg_sequences WHERE schemaname='public' ORDER BY sequencename")
			fi
		} >"$temporary"
	)
	[[ "$(awk -F '\t' '$1 == "table" {count++} END {print count + 0}' "$temporary")" -gt 0 ]] || die "Empreinte SQL vide pour $scope"
	chmod 0600 "$temporary"
	durable_replace_file "$temporary" "$output"
}

assert_additive_migration_contract() {
	local before="$DEPLOY_DIR/database-quiesced-migration-stable.tsv"
	local after="$DEPLOY_DIR/database-post-migration-stable.tsv"
	local output="$DEPLOY_DIR/database-migration-comparison.json" table count failed=0
	local source_revision target_revision
	local -a new_tables=(value_loop_operations value_scenarios value_simulations value_action_executions value_measurements workspace_app_installations workspace_app_operations workspace_app_lifecycle_step_receipts)
	capture_sql_database_fingerprint "$after" migration-stable
	cmp -s "$before" "$after" || failed=1
	source_revision="$(metadata previous_database_revision)"
	target_revision="$(current_database_revision)"
	[[ "$source_revision" == "064_run_dispatch_outbox" ]] || failed=1
	[[ "$target_revision" == "076_decision_scenario_lineage" ]] || failed=1
	for table in "${new_tables[@]}"; do
		count="$(docker exec agentium-pg psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT count(*) FROM public.\"$table\"")"
		[[ "$count" == "0" ]] || failed=1
	done
	[[ "$(docker exec agentium-pg psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT count(*) FROM systems WHERE blueprint_key IS DISTINCT FROM id")" == "0" ]] || failed=1
	[[ "$(docker exec agentium-pg psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT count(*) FROM contexts WHERE blueprint_key IS DISTINCT FROM id")" == "0" ]] || failed=1
	[[ "$(docker exec agentium-pg psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT count(*) FROM system_versions WHERE configuration_snapshot IS NOT NULL")" == "0" ]] || failed=1
	[[ "$(docker exec agentium-pg psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT count(*) FROM skill_invocations WHERE execution_snapshot IS NOT NULL OR cost_measured IS NOT NULL")" == "0" ]] || failed=1
	[[ "$(docker exec agentium-pg psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT count(*) FROM decisions WHERE scenario_id IS NOT NULL")" == "0" ]] || failed=1
	python3 - "$before" "$after" "$output" "$failed" "$source_revision" "$target_revision" <<'PY'
import hashlib, json, os, sys
from pathlib import Path
before, after, output = map(Path, sys.argv[1:4])
passed = sys.argv[4] == "0"
source_revision, target_revision = sys.argv[5:]
payload = {
    "schema_version": 1,
    "kind": "additive_database_migration_comparison",
    "profile": "agentium-064-to-076-additive-v1",
    "result": "passed" if passed else "failed",
    "stable_before_sha256": hashlib.sha256(before.read_bytes()).hexdigest(),
    "stable_after_sha256": hashlib.sha256(after.read_bytes()).hexdigest(),
    "source_revision": source_revision,
    "target_revision": target_revision,
    "revision_transition_exact": (
        source_revision == "064_run_dispatch_outbox"
        and target_revision == "076_decision_scenario_lineage"
    ),
    "new_tables_initially_empty": passed,
    "additive_columns_initialized_as_declared": passed,
}
temporary = output.parent / f".{output.name}.{os.getpid()}"
with temporary.open("w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
os.chmod(temporary, 0o600)
os.replace(temporary, output)
directory_fd = os.open(output.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PY
	[[ "$failed" -eq 0 ]] || die "La migration candidate a modifié des lignes historiques ou violé le contrat additif"
}

compare_candidate_startup_database() {
	local before="$DEPLOY_DIR/database-post-migration-all.tsv" after="$DEPLOY_DIR/database-post-activation-all.tsv"
	local output="$DEPLOY_DIR/database-startup-comparison.json" temporary="$DEPLOY_DIR/.database-startup-comparison.$$"
	if python3 - "$before" "$after" "$temporary" <<'PY'
import hashlib, json, sys
from pathlib import Path
before, after, output = map(Path, sys.argv[1:])
before_bytes = before.read_bytes()
after_bytes = after.read_bytes()
same = before_bytes == after_bytes
payload = {
    "schema_version": 1,
    "kind": "candidate_startup_database_comparison",
    "profile": "agentium-sql-table-fingerprint-v1",
    "result": "passed" if same else "failed",
    "before_sha256": hashlib.sha256(before_bytes).hexdigest(),
    "after_sha256": hashlib.sha256(after_bytes).hexdigest(),
}
output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
if not same:
    raise SystemExit("candidate startup changed PostgreSQL")
PY
	then
		chmod 0600 "$temporary"
		durable_replace_file "$temporary" "$output"
	else
		[[ -s "$temporary" ]] && { chmod 0600 "$temporary"; durable_replace_file "$temporary" "$output"; }
		die "Le démarrage candidat a modifié PostgreSQL"
	fi
	if ! python3 -c 'import json,sys; assert json.load(open(sys.argv[1], encoding="utf-8"))["result"] == "passed"' "$output"; then
		die "Le démarrage candidat a modifié PostgreSQL"
	fi
}

run_live_binding_audit() {
	capture_running_binding_contract "$DEPLOY_DIR/post-activation-bindings.json"
	capture_sql_database_fingerprint "$DEPLOY_DIR/database-post-activation-all.tsv" all
	compare_candidate_startup_database
	[[ -s "$DATABASE_CANARY_BASELINE" ]] || capture_candidate_database_inventory "$DATABASE_CANARY_BASELINE"
}

candidate_provenance_rows() {
	assert_private_state_file "$PROVENANCE_FILE"
	python3 -I - "$PROVENANCE_FILE" "$EXPECTED_SHA" "$BRANCH" "$DEPLOYMENT_ID" <<'PY'
import json
import os
import re
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected_sha, expected_branch, expected_deployment = sys.argv[2:]

flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
fd = os.open(path, flags)
try:
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode):
        raise SystemExit("candidate provenance is not regular")
    if before.st_uid != os.geteuid() or stat.S_IMODE(before.st_mode) != 0o600:
        raise SystemExit("candidate provenance ownership/mode differs")
    if before.st_nlink != 1 or not 1 <= before.st_size <= 1_048_576:
        raise SystemExit("candidate provenance links/size differ")
    chunks = []
    remaining = before.st_size
    while remaining:
        chunk = os.read(fd, min(65_536, remaining))
        if not chunk:
            raise SystemExit("candidate provenance was truncated")
        chunks.append(chunk)
        remaining -= len(chunk)
    if os.read(fd, 1):
        raise SystemExit("candidate provenance grew while read")
    after = os.fstat(fd)
finally:
    os.close(fd)
linked = os.stat(path, follow_symlinks=False)
identity = lambda row: (
    row.st_dev,
    row.st_ino,
    row.st_size,
    row.st_mtime_ns,
    row.st_ctime_ns,
    row.st_nlink,
    stat.S_IMODE(row.st_mode),
    row.st_uid,
)
if identity(before) != identity(after) or identity(after) != identity(linked):
    raise SystemExit("candidate provenance changed while read")
try:
    payload = json.loads(b"".join(chunks))
except (UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise SystemExit("candidate provenance JSON is invalid") from exc
expected_top = {
    "schema_version", "kind", "trust_boundary", "promotion_ceiling",
    "commit_sha", "branch", "deployment_id", "collected_at", "outcome",
    "vm", "database_heads", "services", "build_info", "maintenance",
    "writer_exclusion", "checks",
}
if not isinstance(payload, dict) or set(payload) != expected_top:
    raise SystemExit("candidate provenance schema differs")
if payload.get("schema_version") != 1 or payload.get("kind") != "vm_fallback_provenance":
    raise SystemExit("candidate provenance identity differs")
if payload.get("trust_boundary") != "direct_operator_vm_fallback":
    raise SystemExit("candidate provenance trust boundary differs")
if payload.get("promotion_ceiling") != "runner_verified" or payload.get("outcome") != "passed":
    raise SystemExit("candidate provenance did not pass")
if (
    payload.get("commit_sha") != expected_sha
    or payload.get("branch") != expected_branch
    or payload.get("deployment_id") != expected_deployment
):
    raise SystemExit("candidate provenance transaction identity differs")
vm = payload.get("vm")
if not isinstance(vm, dict) or set(vm) != {
    "repo_head", "branch", "origin_head", "clean", "dirty_entry_count"
}:
    raise SystemExit("candidate provenance VM schema differs")
if (
    vm.get("repo_head") != expected_sha
    or vm.get("origin_head") != expected_sha
    or vm.get("branch") != expected_branch
    or vm.get("clean") is not True
    or vm.get("dirty_entry_count") != 0
):
    raise SystemExit("candidate provenance VM identity differs")
services = payload.get("services")
expected_services = {
    "agentium-backend", "agentium-frontend", "agentium-worker-cpu"
}
if not isinstance(services, list) or len(services) != len(expected_services):
    raise SystemExit("candidate provenance service inventory differs")
rows = {}
for row in services:
    if not isinstance(row, dict) or set(row) != {"service", "running", "image_id", "revision"}:
        raise SystemExit("candidate provenance service row differs")
    service = row.get("service")
    if service not in expected_services or service in rows:
        raise SystemExit("candidate provenance service is unknown or duplicated")
    image_id = row.get("image_id")
    if row.get("running") is not True or row.get("revision") != expected_sha:
        raise SystemExit("candidate provenance service did not attest the candidate")
    if not isinstance(image_id, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
        raise SystemExit("candidate provenance image identity is invalid")
    rows[service] = image_id
if set(rows) != expected_services or len(set(rows.values())) != 3:
    raise SystemExit("candidate provenance service inventory is incomplete or aliased")
build_info = payload.get("build_info")
if not isinstance(build_info, dict) or set(build_info) != {"backend", "frontend"}:
    raise SystemExit("candidate provenance build-info schema differs")
for name in ("backend", "frontend"):
    row = build_info.get(name)
    if not isinstance(row, dict):
        raise SystemExit("candidate provenance build-info is invalid")
    if row.get("service") != name or row.get("revision") != expected_sha:
        raise SystemExit("candidate provenance build-info identity differs")
    if row.get("revision_verified") is not True:
        raise SystemExit("candidate provenance build-info is unverified")
checks = payload.get("checks")
if not isinstance(checks, dict) or not checks:
    raise SystemExit("candidate provenance checks are absent")
for check in checks.values():
    if not isinstance(check, dict) or set(check) != {"passed", "expected", "observed"}:
        raise SystemExit("candidate provenance check schema differs")
    if check.get("passed") is not True:
        raise SystemExit("candidate provenance contains a failed check")
for service in sorted(rows):
    print(service, rows[service], sep="\t")
PY
}

candidate_provenance_image_id() {
	local requested="$1" service rows image_id
	case "$requested" in
	agentium-backend | agentium-frontend | agentium-worker-cpu) service="$requested" ;;
	agentium-p4-maintenance) service=agentium-worker-cpu ;;
	*) die "Service candidat non autorisé: $requested" ;;
	esac
	rows="$(candidate_provenance_rows)" || die "Provenance OCI candidate invalide"
	image_id="$(awk -F '\t' -v service="$service" '$1 == service { print $2; exit }' <<<"$rows")"
	[[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || die "ID OCI candidat absent pour $requested"
	printf '%s\n' "$image_id"
}

candidate_image_reference() {
	case "$1" in
	agentium-backend) printf 'agentium-backend:%s\n' "$IMAGE_TAG" ;;
	agentium-frontend) printf 'agentium-frontend:%s\n' "$IMAGE_TAG" ;;
	agentium-worker-cpu | agentium-p4-maintenance) printf 'agentium-worker:%s\n' "$IMAGE_TAG" ;;
	*) die "Référence OCI candidate inconnue: $1" ;;
	esac
}

candidate_override_rows() {
	assert_private_state_file "$CANDIDATE_IMAGE_OVERRIDE"
	python3 -I - "$CANDIDATE_IMAGE_OVERRIDE" <<'PY'
import os
import re
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
fd = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0))
try:
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid():
        raise SystemExit("candidate image override identity differs")
    if before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o600 or not 1 <= before.st_size <= 2048:
        raise SystemExit("candidate image override links/mode/size differ")
    observed = os.read(fd, before.st_size + 1)
    after = os.fstat(fd)
finally:
    os.close(fd)
linked = os.stat(path, follow_symlinks=False)
identity = lambda row: (
    row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns,
    row.st_nlink, stat.S_IMODE(row.st_mode), row.st_uid,
)
if identity(before) != identity(after) or identity(after) != identity(linked):
    raise SystemExit("candidate image override changed while read")
try:
    decoded = observed.decode("ascii")
except UnicodeDecodeError as exc:
    raise SystemExit("candidate image override is not ASCII") from exc
if not decoded.endswith("\n"):
    raise SystemExit("candidate image override is not newline terminated")
lines = decoded.splitlines()
services = (
    "agentium-backend", "agentium-frontend", "agentium-worker-cpu",
    "agentium-p4-maintenance",
)
if len(lines) != 9 or lines[0] != "services:":
    raise SystemExit("candidate image override schema differs")
rows = {}
for index, service in enumerate(services):
    offset = 1 + index * 2
    if lines[offset] != f"  {service}:":
        raise SystemExit("candidate image override service order differs")
    match = re.fullmatch(r"    image: (sha256:[0-9a-f]{64})", lines[offset + 1])
    if match is None:
        raise SystemExit("candidate image override ID is invalid")
    rows[service] = match.group(1)
if rows["agentium-p4-maintenance"] != rows["agentium-worker-cpu"]:
    raise SystemExit("candidate P4 image is not the worker image")
if len({rows[name] for name in services[:3]}) != 3:
    raise SystemExit("candidate primary images are aliased")
for service in services[:3]:
    print(service, rows[service], sep="\t")
PY
}

candidate_override_image_id() {
	local requested="$1" service rows image_id
	case "$requested" in
	agentium-backend | agentium-frontend | agentium-worker-cpu) service="$requested" ;;
	agentium-p4-maintenance) service=agentium-worker-cpu ;;
	*) die "Service candidat non autorisé: $requested" ;;
	esac
	rows="$(candidate_override_rows)" || die "Override OCI candidat invalide"
	image_id="$(awk -F '\t' -v service="$service" '$1 == service {print $2; exit}' <<<"$rows")"
	[[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || die "ID OCI candidat absent pour $requested"
	printf '%s\n' "$image_id"
}

assert_candidate_image_override_contract() {
	local service image_id revision
	candidate_override_rows >/dev/null
	for service in agentium-backend agentium-frontend agentium-worker-cpu; do
		image_id="$(candidate_override_image_id "$service")"
		revision="$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$image_id" 2>/dev/null || true)"
		[[ "$revision" == "$EXPECTED_SHA" ]] || die "Image épinglée différente du SHA candidat pour $service"
	done
}

capture_candidate_image_override() {
	local service backend frontend worker reference image_id revision temporary="$DEPLOY_DIR/.compose.agentium.candidate-images.$$"
	if [[ -e "$CANDIDATE_IMAGE_OVERRIDE" || -L "$CANDIDATE_IMAGE_OVERRIDE" ]]; then
		assert_candidate_image_override_contract
		return
	fi
	for service in agentium-backend agentium-frontend agentium-worker-cpu; do
		reference="$(candidate_image_reference "$service")"
		image_id="$(docker image inspect --format '{{.Id}}' "$reference" 2>/dev/null || true)"
		[[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || die "Image candidate absente: $reference"
		revision="$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$image_id" 2>/dev/null || true)"
		[[ "$revision" == "$EXPECTED_SHA" ]] || die "Révision OCI candidate invalide: $reference"
		case "$service" in
		agentium-backend) backend="$image_id" ;;
		agentium-frontend) frontend="$image_id" ;;
		agentium-worker-cpu) worker="$image_id" ;;
		esac
	done
	[[ "$backend" != "$frontend" && "$backend" != "$worker" && "$frontend" != "$worker" ]] ||
		die "Les images candidates principales ne sont pas distinctes"
	(umask 077; {
		printf 'services:\n'
		printf '  agentium-backend:\n    image: %s\n' "$backend"
		printf '  agentium-frontend:\n    image: %s\n' "$frontend"
		printf '  agentium-worker-cpu:\n    image: %s\n' "$worker"
		printf '  agentium-p4-maintenance:\n    image: %s\n' "$worker"
	} >"$temporary")
	durable_publish_file "$temporary" "$CANDIDATE_IMAGE_OVERRIDE"
	assert_candidate_image_override_contract
}

assert_candidate_provenance_matches_override() {
	local service attested pinned
	for service in agentium-backend agentium-frontend agentium-worker-cpu; do
		attested="$(candidate_provenance_image_id "$service")"
		pinned="$(candidate_override_image_id "$service")"
		[[ "$attested" == "$pinned" ]] || die "Image $service canari différente de l'image épinglée au build"
	done
}

freeze_candidate_image_override() {
	assert_candidate_image_override_contract
	assert_candidate_provenance_matches_override
}

assert_candidate_tags_match_provenance() {
	local service expected reference actual
	assert_candidate_provenance_matches_override
	for service in agentium-backend agentium-frontend agentium-worker-cpu; do
		expected="$(candidate_override_image_id "$service")"
		reference="$(candidate_image_reference "$service")"
		actual="$(docker image inspect --format '{{.Id}}' "$reference" 2>/dev/null || true)"
		[[ "$actual" == "$expected" ]] || die "Tag mutable $reference différent de l'image candidate épinglée"
	done
}

assert_candidate_container_image() {
	local service="$1" expected actual revision
	expected="$(candidate_override_image_id "$service")"
	actual="$(docker inspect --format '{{.Image}}' "$service" 2>/dev/null || true)"
	[[ "$actual" == "$expected" ]] || die "$service n'utilise pas l'image exacte attestée par les canaris"
	revision="$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$actual" 2>/dev/null || true)"
	[[ "$revision" == "$EXPECTED_SHA" ]] || die "$service ne porte pas la révision OCI candidate"
}

rollback_image_id() {
	local service="$1" image_id
	case "$service" in
	agentium-backend | agentium-frontend | agentium-worker-cpu | agentium-p4-maintenance | agentium-sftp) ;;
	*) die "Service rollback non autorisé: $service" ;;
	esac
	assert_rollback_state_contract
	image_id="$(awk -F '\t' -v service="$service" '$1 == "service" && $2 == service {print $3; exit}' "$ROLLBACK_STATE")"
	[[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || die "ID OCI rollback absent pour $service"
	printf '%s\n' "$image_id"
}

rollback_service_revision() {
	local service="$1" revision
	case "$service" in
	agentium-backend | agentium-frontend | agentium-worker-cpu | agentium-p4-maintenance | agentium-sftp) ;;
	*) die "Service rollback non autorisé pour sa révision: $service" ;;
	esac
	assert_rollback_state_contract
	revision="$(awk -F '\t' -v service="$service" '$1 == "container_state" && $2 == service {print $4; exit}' "$ROLLBACK_STATE")"
	[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || die "Révision OCI rollback absente pour $service"
	printf '%s\n' "$revision"
}

assert_rollback_image_override_contract() {
	local backend frontend worker p4="" p4_state sftp="" sftp_state image_id service revision
	assert_private_state_file "$ROLLBACK_IMAGE_OVERRIDE"
	backend="$(rollback_image_id agentium-backend)"
	frontend="$(rollback_image_id agentium-frontend)"
	worker="$(rollback_image_id agentium-worker-cpu)"
	p4_state="$(historical_runtime_state agentium-p4-maintenance)"
	if [[ "$p4_state" != "absent" ]]; then p4="$(rollback_image_id agentium-p4-maintenance)"; fi
	sftp_state="$(historical_runtime_state agentium-sftp)"
	if [[ "$sftp_state" != "absent" ]]; then sftp="$(rollback_image_id agentium-sftp)"; fi
	python3 -I - "$ROLLBACK_IMAGE_OVERRIDE" "$backend" "$frontend" "$worker" "$p4" "$sftp" <<'PY'
import os
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
backend, frontend, worker, p4, sftp = sys.argv[2:]
expected = (
    "services:\n"
    f"  agentium-backend:\n    image: {backend}\n"
    f"  agentium-frontend:\n    image: {frontend}\n"
    f"  agentium-worker-cpu:\n    image: {worker}\n"
)
if p4:
    expected += f"  agentium-p4-maintenance:\n    image: {p4}\n"
if sftp:
    expected += f"  agentium-sftp:\n    image: {sftp}\n"
encoded = expected.encode("ascii")
fd = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0))
try:
    before = os.fstat(fd)
    observed = os.read(fd, len(encoded) + 1)
    after = os.fstat(fd)
finally:
    os.close(fd)
linked = os.stat(path, follow_symlinks=False)
identity = lambda row: (
    row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns,
    row.st_nlink, stat.S_IMODE(row.st_mode), row.st_uid,
)
if identity(before) != identity(after) or identity(after) != identity(linked):
    raise SystemExit("rollback image override changed while read")
if not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid():
    raise SystemExit("rollback image override identity differs")
if before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o600 or observed != encoded:
    raise SystemExit("rollback image override contract differs")
PY
	[[ "$backend" != "$frontend" && "$backend" != "$worker" && "$frontend" != "$worker" ]] ||
		die "Les images rollback principales ne sont pas distinctes"
	for service in agentium-backend agentium-frontend agentium-worker-cpu; do
		image_id="$(rollback_image_id "$service")"
		revision="$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$image_id" 2>/dev/null || true)"
		[[ "$revision" == "$(rollback_service_revision "$service")" ]] || die "Révision OCI rollback invalide pour $service"
	done
	if [[ -n "$p4" ]]; then
		revision="$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$p4" 2>/dev/null || true)"
		[[ "$revision" == "$(rollback_service_revision agentium-p4-maintenance)" ]] || die "Révision OCI rollback invalide pour P4"
	fi
	if [[ -n "$sftp" ]]; then
		revision="$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$sftp" 2>/dev/null || true)"
		[[ "$revision" == "$(rollback_service_revision agentium-sftp)" && "$revision" == "$(metadata sftp_release_sha)" ]] || die "Révision OCI rollback invalide pour SFTP"
	fi
}

capture_rollback_image_override() {
	local backend frontend worker p4="" p4_state sftp="" sftp_state temporary="$DEPLOY_DIR/.compose.agentium.rollback-images.$$"
	if [[ -e "$ROLLBACK_IMAGE_OVERRIDE" || -L "$ROLLBACK_IMAGE_OVERRIDE" ]]; then
		assert_rollback_image_override_contract
		return
	fi
	backend="$(rollback_image_id agentium-backend)"
	frontend="$(rollback_image_id agentium-frontend)"
	worker="$(rollback_image_id agentium-worker-cpu)"
	p4_state="$(historical_runtime_state agentium-p4-maintenance)"
	if [[ "$p4_state" != "absent" ]]; then p4="$(rollback_image_id agentium-p4-maintenance)"; fi
	sftp_state="$(historical_runtime_state agentium-sftp)"
	if [[ "$sftp_state" != "absent" ]]; then sftp="$(rollback_image_id agentium-sftp)"; fi
	(umask 077; {
		printf 'services:\n'
		printf '  agentium-backend:\n    image: %s\n' "$backend"
		printf '  agentium-frontend:\n    image: %s\n' "$frontend"
		printf '  agentium-worker-cpu:\n    image: %s\n' "$worker"
		if [[ -n "$p4" ]]; then printf '  agentium-p4-maintenance:\n    image: %s\n' "$p4"; fi
		if [[ -n "$sftp" ]]; then printf '  agentium-sftp:\n    image: %s\n' "$sftp"; fi
	} >"$temporary")
	durable_publish_file "$temporary" "$ROLLBACK_IMAGE_OVERRIDE"
	assert_rollback_image_override_contract
}

assert_previous_container_image() {
	local service="$1" expected actual revision expected_revision
	expected="$(rollback_image_id "$service")"
	actual="$(docker inspect --format '{{.Image}}' "$service" 2>/dev/null || true)"
	[[ "$actual" == "$expected" ]] || die "$service n'utilise pas l'image rollback exacte"
	revision="$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$actual" 2>/dev/null || true)"
	expected_revision="$(rollback_service_revision "$service")"
	[[ "$revision" == "$expected_revision" ]] || die "$service ne porte pas la révision rollback"
}

assert_served_build_info() {
	local service="$1" expected_sha="$2"
	[[ "$expected_sha" =~ ^[0-9a-f]{40}$ ]] || die "SHA build-info invalide"
	case "$service" in
	agentium-backend)
		docker exec "$service" python -I -c '
import http.client, json, sys
c = http.client.HTTPConnection("127.0.0.1", 8000, timeout=5)
c.request("GET", "/api/v1/build-info", headers={"Accept": "application/json"})
r = c.getresponse()
raw = r.read(4097)
if r.status != 200 or not raw or len(raw) > 4096:
    raise SystemExit(1)
p = json.loads(raw)
if not isinstance(p, dict) or p.get("service") != "backend":
    raise SystemExit(1)
if p.get("revision") != sys.argv[1] or p.get("revision_verified") is not True:
    raise SystemExit(1)
' "$expected_sha" || die "Build-info backend non prouvé pour ${expected_sha:0:12}"
		;;
	agentium-frontend)
		docker exec "$service" wget -qO- http://127.0.0.1:8080/build-info.json |
			python3 -I -c '
import json, sys
raw = sys.stdin.buffer.read(4097)
if not raw or len(raw) > 4096:
    raise SystemExit(1)
p = json.loads(raw)
if not isinstance(p, dict) or p.get("service") != "frontend":
    raise SystemExit(1)
if p.get("revision") != sys.argv[1] or p.get("revision_verified") is not True:
    raise SystemExit(1)
' "$expected_sha" || die "Build-info frontend non prouvé pour ${expected_sha:0:12}"
		;;
	*) die "Build-info non défini pour $service" ;;
	esac
}

assert_candidate_served_build_info() {
	assert_served_build_info "$1" "$EXPECTED_SHA"
}

assert_all_candidate_runtime_images() {
	local service desired
	for service in agentium-backend agentium-frontend agentium-worker-cpu; do
		wait_container_healthy "$service"
		[[ "$(docker inspect --format '{{.State.Running}}' "$service")" == "true" ]] || die "$service n'est pas actif"
		assert_candidate_container_image "$service"
	done
	assert_candidate_served_build_info agentium-backend
	assert_candidate_served_build_info agentium-frontend
	desired="$(original_runtime_state agentium-p4-maintenance)"
	case "$desired" in
	running)
		wait_container_healthy agentium-p4-maintenance
		assert_candidate_container_image agentium-p4-maintenance
		;;
	stopped)
		[[ "$(docker inspect --format '{{.State.Running}}' agentium-p4-maintenance 2>/dev/null || printf false)" == "false" ]] ||
			die "P4 historiquement arrêté est actif"
		assert_candidate_container_image agentium-p4-maintenance
		;;
	absent) ! docker inspect agentium-p4-maintenance >/dev/null 2>&1 || die "P4 devait rester absent" ;;
	*) die "État P4 historique invalide: $desired" ;;
	esac
}

assert_previous_runtime_images_without_sftp() {
	local service desired previous_sha
	previous_sha="$(metadata previous_sha)"
	assert_rollback_image_override_contract
	for service in agentium-backend agentium-frontend agentium-worker-cpu; do
		desired="$(historical_runtime_state "$service")"
		case "$desired" in
		running)
			wait_container_healthy "$service"
			[[ "$(docker inspect --format '{{.State.Running}}' "$service")" == "true" ]] ||
				die "$service rollback n'est pas actif"
			assert_previous_container_image "$service"
			;;
		stopped)
			[[ "$(docker inspect --format '{{.State.Running}}' "$service" 2>/dev/null || printf false)" == "false" ]] ||
				die "$service rollback devait rester arrêté"
			assert_previous_container_image "$service"
			;;
		*) die "État rollback primaire invalide pour $service: $desired" ;;
		esac
	done
	if [[ "$(historical_runtime_state agentium-backend)" == "running" ]]; then
		assert_served_build_info agentium-backend "$previous_sha"
	fi
	if [[ "$(historical_runtime_state agentium-frontend)" == "running" ]]; then
		assert_served_build_info agentium-frontend "$previous_sha"
	fi
	desired="$(historical_runtime_state agentium-p4-maintenance)"
	case "$desired" in
	running)
		wait_container_healthy agentium-p4-maintenance
		assert_previous_container_image agentium-p4-maintenance
		;;
	stopped)
		[[ "$(docker inspect --format '{{.State.Running}}' agentium-p4-maintenance 2>/dev/null || printf false)" == "false" ]] ||
			die "P4 rollback devait rester arrêté"
		assert_previous_container_image agentium-p4-maintenance
		;;
	absent) ! docker inspect agentium-p4-maintenance >/dev/null 2>&1 || die "P4 rollback devait rester absent" ;;
	*) die "État P4 rollback invalide: $desired" ;;
	esac

}

assert_previous_sftp_runtime_image() {
	local desired
	desired="$(historical_runtime_state agentium-sftp)"
	case "$desired" in
	running)
		wait_container_healthy agentium-sftp
		assert_previous_container_image agentium-sftp
		;;
	stopped)
		[[ "$(docker inspect --format '{{.State.Running}}' agentium-sftp 2>/dev/null || printf false)" == "false" ]] ||
			die "SFTP rollback devait rester arrêté"
		assert_previous_container_image agentium-sftp
		;;
	absent) ! docker inspect agentium-sftp >/dev/null 2>&1 || die "SFTP rollback devait rester absent" ;;
	*) die "État SFTP rollback invalide: $desired" ;;
	esac
}

assert_all_previous_runtime_images() {
	assert_previous_runtime_images_without_sftp
	assert_previous_sftp_runtime_image
}

wait_container_healthy() {
	local service="$1" attempt status
	for attempt in $(seq 1 30); do
		status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$service" 2>/dev/null || true)"
		[[ "$status" == "healthy" || "$status" == "running" ]] && return
		sleep 2
	done
	die "$service n'est pas sain"
}

quiesce_identity_writer() {
	set_realtime_restart_policies_no
	if docker inspect agentium-kc >/dev/null 2>&1; then
		ensure_container_unpaused agentium-kc
		if [[ "$(docker inspect --format '{{.State.Running}}' agentium-kc)" == "true" ]]; then
			docker stop --time 45 agentium-kc >/dev/null
		fi
		[[ "$(docker inspect --format '{{.State.Running}}' agentium-kc)" == "false" ]] || die "Keycloak écrit encore"
		[[ "$(container_restart_policy agentium-kc)" == $'no\t0' ]] || die "Keycloak peut redémarrer pendant la transaction"
	fi
}

restore_identity_runtime_state() {
	local desired expected_image actual_image
	[[ "$(gate status)" == "closed" ]] || die "Keycloak ne peut démarrer sans gate HTTP /kc/"
	desired="$(historical_runtime_state agentium-kc)"
	expected_image="$(awk -F '\t' '$1 == "runtime_state" && $2 == "agentium-kc" { print $4; exit }' "$RUNTIME_STATE_FILE")"
	case "$desired" in
	running | stopped)
		docker inspect agentium-kc >/dev/null 2>&1 || die "Keycloak a disparu pendant la transaction"
		actual_image="$(docker inspect --format '{{.Image}}' agentium-kc)"
		[[ "$actual_image" == "$expected_image" ]] || die "Image Keycloak différente de l'image capturée"
		docker update --restart=no agentium-kc >/dev/null
		if [[ "$desired" == "running" ]]; then
			docker start agentium-kc >/dev/null
			wait_container_healthy agentium-kc
		else
			docker stop --time 45 agentium-kc >/dev/null 2>&1 || true
		fi
		[[ "$(container_restart_policy agentium-kc)" == $'no\t0' ]] || die "Keycloak n'est pas fail-closed au reboot"
		;;
	absent) ! docker inspect agentium-kc >/dev/null 2>&1 || die "Keycloak devait rester absent" ;;
	*) die "État Keycloak historique invalide: $desired" ;;
	esac
}

restore_auxiliary_runtime_state() {
	local service desired expected_image actual_image current_phase
	current_phase="$(phase)"
	for service in agentium-p4-maintenance; do
		desired="$(original_runtime_state "$service")"
		case "$desired" in
		running)
			ensure_container_unpaused "$service"
			if [[ "$current_phase" == "opening_forward" || "$current_phase" == "opened" || "$current_phase" == "completed" ]]; then
				AGENTIUM_PIN_CANDIDATE_IMAGES=1 compose up -d --no-build --force-recreate "$service"
				assert_candidate_container_image "$service"
			elif [[ "$current_phase" == "rollback_opening" || "$current_phase" == "rolled_back" ]]; then
				AGENTIUM_PIN_ROLLBACK_IMAGES=1 compose up -d --no-build --force-recreate "$service"
				assert_previous_container_image "$service"
			else
				die "Restauration P4 interdite hors frontière OCI candidate ou rollback"
			fi
			[[ "$(docker inspect --format '{{.State.Running}}' "$service")" == "true" ]] || die "$service n'a pas redémarré"
			;;
		stopped)
			[[ "$(docker inspect --format '{{.State.Running}}' "$service" 2>/dev/null || printf false)" == "false" ]] || die "$service devait rester arrêté"
			;;
		absent)
			! docker inspect "$service" >/dev/null 2>&1 || die "$service devait rester absent"
			;;
		*) die "État auxiliaire historique invalide pour $service" ;;
		esac
	done
	# Realtime services are not candidate images. Restore the exact captured
	# containers, server first and sidecar second, only after validation passed.
	livekit_ingress_gate_is_closed || die "LiveKit ne peut démarrer sans gate ingress"
	set_realtime_restart_policies_no
	for service in agentium-livekit agentium-livekit-agent; do
		desired="$(historical_runtime_state "$service")"
		expected_image="$(awk -F '\t' -v service="$service" '$1 == "runtime_state" && $2 == service { print $4; exit }' "$RUNTIME_STATE_FILE")"
		case "$desired" in
		running | stopped)
			docker inspect "$service" >/dev/null 2>&1 || die "$service a disparu pendant le déploiement"
			ensure_container_unpaused "$service"
			actual_image="$(docker inspect --format '{{.Image}}' "$service")"
			[[ "$actual_image" == "$expected_image" ]] || die "Image non candidate de $service modifiée"
			if [[ "$desired" == "running" ]]; then
				docker start "$service" >/dev/null
				wait_container_healthy "$service"
				[[ "$(container_restart_policy "$service")" == $'no\t0' ]] || die "$service n'est pas fail-closed au reboot"
			else
				[[ "$(docker inspect --format '{{.State.Running}}' "$service")" == "false" ]] || die "$service devait rester arrêté"
			fi
			;;
		absent) ! docker inspect "$service" >/dev/null 2>&1 || die "$service devait rester absent" ;;
		*) die "État realtime historique invalide pour $service" ;;
		esac
	done
}

restore_sftp_runtime_state() {
	local desired expected_image actual_image
	desired="$(original_runtime_state agentium-sftp)"
	case "$desired" in
	running)
		ensure_container_unpaused agentium-sftp
		expected_image="$(awk -F '\t' '$1 == "service" && $2 == "agentium-sftp" { print $3; exit }' "$ROLLBACK_STATE")"
		actual_image="$(docker inspect --format '{{.Image}}' agentium-sftp)"
		[[ "$actual_image" == "$expected_image" ]] || die "SFTP Release A épinglé remplacé avant restauration"
		[[ "$(secure_deposit_mode)" == "ro" ]] || die "SFTP ne peut démarrer qu'avec le Secure Deposit en lecture seule"
		sftp_ingress_gate_is_closed || die "SFTP ne peut démarrer sans gate ingress"
		set_sftp_restart_policy_no
		docker start agentium-sftp >/dev/null
		wait_container_healthy agentium-sftp
		assert_sftp_restart_policy_no
		assert_previous_container_image agentium-sftp
		;;
	stopped)
		[[ "$(docker inspect --format '{{.State.Running}}' agentium-sftp 2>/dev/null || printf false)" == "false" ]] ||
			die "agentium-sftp devait rester arrêté"
		assert_sftp_restart_policy_no
		assert_previous_container_image agentium-sftp
		;;
	absent)
		! docker inspect agentium-sftp >/dev/null 2>&1 || die "agentium-sftp devait rester absent"
		;;
	*) die "État auxiliaire historique invalide pour agentium-sftp" ;;
	esac
}

restore_candidate_worker_with_scheduler() {
	local desired="${1:-1}"
	[[ "$desired" == "0" || "$desired" == "1" ]] || die "Mode scheduler candidat invalide"
	assert_candidate_tags_match_provenance
	AGENTIUM_CELERY_BEAT="$desired" AGENTIUM_PIN_CANDIDATE_IMAGES=1 \
		compose up -d --no-build --force-recreate agentium-worker-cpu
	[[ "$(docker inspect --format '{{.State.Running}}' agentium-worker-cpu)" == "true" ]] || die "Worker normal non démarré"
	assert_candidate_container_image agentium-worker-cpu
	assert_worker_scheduler_mode "$desired"
}

restore_candidate_backend_writer() {
	local observed_key
	assert_candidate_tags_match_provenance
	AGENTIUM_STARTUP_RECONCILIATION=disabled AGENTIUM_PIN_CANDIDATE_IMAGES=1 \
		compose up -d --no-build --force-recreate agentium-backend
	wait_container_healthy agentium-backend
	assert_candidate_container_image agentium-backend
	assert_candidate_served_build_info agentium-backend
	observed_key="$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' agentium-backend | awk -F= '$1 == "QDRANT_API_KEY" {sub(/^[^=]*=/, ""); print; exit}')"
	[[ "${#observed_key}" -ge 32 && "$observed_key" == "$(qdrant_server_key admin)" ]] ||
		die "Backend candidat non recréé avec la clé Qdrant admin"
}

restore_previous_worker_scheduler() {
	local desired beat
	desired="$(historical_runtime_state agentium-worker-cpu)"
	beat="$(awk -F '\t' '$1 == "worker_celery_beat" && $2 == "agentium-worker-cpu" {print $3; exit}' "$RUNTIME_STATE_FILE")"
	[[ "$beat" == "0" || "$beat" == "1" ]] || die "CELERY_BEAT historique absent"
	case "$desired" in
	running)
		AGENTIUM_CELERY_BEAT="$beat" AGENTIUM_PIN_ROLLBACK_IMAGES=1 \
			compose up -d --no-build --force-recreate agentium-worker-cpu
		assert_previous_container_image agentium-worker-cpu
		assert_worker_scheduler_mode "$beat"
		;;
	stopped)
		docker stop --time 45 agentium-worker-cpu >/dev/null 2>&1 || true
		[[ "$(docker inspect --format '{{.State.Running}}' agentium-worker-cpu)" == "false" ]] || die "Worker rollback devait rester arrêté"
		assert_previous_container_image agentium-worker-cpu
		;;
	*) die "État worker rollback invalide: $desired" ;;
	esac
}

restore_previous_worker_without_scheduler() {
	local desired
	desired="$(historical_runtime_state agentium-worker-cpu)"
	case "$desired" in
	running)
		AGENTIUM_CELERY_BEAT=0 AGENTIUM_PIN_ROLLBACK_IMAGES=1 \
			compose up -d --no-build --force-recreate agentium-worker-cpu
		assert_previous_container_image agentium-worker-cpu
		assert_worker_scheduler_mode 0
		;;
	stopped)
		docker stop --time 45 agentium-worker-cpu >/dev/null 2>&1 || true
		assert_previous_container_image agentium-worker-cpu
		;;
	*) die "État worker rollback invalide: $desired" ;;
	esac
}

attest_previous_qdrant_admin_ready() {
	local service
	local -a clients=()
	for service in agentium-backend agentium-worker-cpu agentium-p4-maintenance; do
		if docker inspect "$service" >/dev/null 2>&1 &&
			[[ "$(docker inspect --format '{{.State.Running}}' "$service")" == "true" ]]; then
			clients+=("$service")
		fi
	done
	[[ "${#clients[@]}" -gt 0 ]] || die "Aucun client Qdrant historique actif à attester"
	run_qdrant_host_contract "$DEPLOY_DIR/qdrant-rollback-admin-ready-barrier.json" admin "${clients[@]}"
}

previous_runtime_supports_read_only_startup() {
	git show "$(metadata previous_sha):backend/app/main.py" 2>/dev/null | grep -Fq 'startup_reconciliation_enabled' &&
		git show "$(metadata previous_sha):docker/compose.agentium.yml" 2>/dev/null | grep -Fq 'STARTUP_RECONCILIATION:'
}

previous_systemd_runtime_supports_frozen_dotenv() {
	[[ "$(historical_systemd_state)" != "active" ]] ||
		git show "$(metadata previous_sha):backend/app/core/config.py" 2>/dev/null |
			grep -Fq 'AGENTIUM_DISABLE_DOTENV'
}

restore_previous_backend_container() {
	local desired
	desired="$(historical_runtime_state agentium-backend)"
	case "$desired" in
	running)
		AGENTIUM_STARTUP_RECONCILIATION=disabled AGENTIUM_PIN_ROLLBACK_IMAGES=1 \
			compose up -d --no-build --force-recreate agentium-backend
		assert_previous_container_image agentium-backend
		wait_container_healthy agentium-backend
		;;
	stopped)
		docker stop --time 45 agentium-backend >/dev/null 2>&1 || true
		[[ "$(docker inspect --format '{{.State.Running}}' agentium-backend)" == "false" ]] || die "Backend rollback devait rester arrêté"
		assert_previous_container_image agentium-backend
		;;
	*) die "État backend rollback invalide: $desired" ;;
	esac
}

assert_worker_scheduler_mode() {
	local expected="$1" observed
	[[ "$expected" == "0" || "$expected" == "1" ]] || die "Mode scheduler worker invalide"
	observed="$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' agentium-worker-cpu | awk -F= '$1 == "CELERY_BEAT" {print $2; exit}')"
	[[ "$observed" == "$expected" ]] || die "agentium-worker-cpu CELERY_BEAT=$observed, attendu $expected"
}

historical_worker_scheduler_mode() {
	local observed
	observed="$(awk -F '\t' '$1 == "worker_celery_beat" && $2 == "agentium-worker-cpu" {print $3; exit}' "$RUNTIME_STATE_FILE")"
	[[ "$observed" == "0" || "$observed" == "1" ]] || die "CELERY_BEAT historique absent"
	printf '%s\n' "$observed"
}

reestablish_persisted_phase_boundary() {
	local persisted_phase="$1" service
	case "$persisted_phase" in quiesced | backfill_pending | backfill_applying | migrated | activated | validation_starting | validation_pending) ;; *) die "Phase non sûre à rétablir: $persisted_phase" ;; esac
	verify_backup "$DEPLOY_DIR/postgres-quiesced.dump" || die "Backup quiescé durable absent à la reprise"
	STAGE="reboot-safe phase boundary ($persisted_phase)"
	if [[ "$(gate status)" == "open" ]]; then gate enter; fi
	[[ "$(gate status)" == "closed" ]] || die "Gate HTTP non fermé à la reprise"
	enter_systemd_backend_ingress_gate
	enter_sftp_ingress_gate
	enter_livekit_ingress_gate
	disable_systemd_backend_restart
	set_application_restart_policies_no
	set_sftp_restart_policy_no
	set_realtime_restart_policies_no
	quiesce_legacy_sftp_systemd
	wait_for_existing_writer_connections_to_drain
	quiesce_sftp
	quiesce_identity_writer
	sudo_command systemctl stop agentium-backend.service >/dev/null 2>&1 || true
	assert_no_tcp_listener 8000 "Backend systemd"
	assert_systemd_env_dropin_contract
	for service in agentium-livekit-agent agentium-livekit agentium-p4-maintenance; do
		if docker inspect "$service" >/dev/null 2>&1; then
			ensure_container_unpaused "$service"
			docker stop --time 45 "$service" >/dev/null 2>&1 || true
			[[ "$(docker inspect --format '{{.State.Running}}' "$service")" == "false" ]] || die "$service écrit encore à la reprise"
		fi
	done
	assert_no_tcp_listener 7881 "LiveKit"
	assert_no_captured_livekit_listeners
	set_secure_deposit_mode ro
	if [[ "$persisted_phase" == "quiesced" || "$persisted_phase" == "backfill_pending" || "$persisted_phase" == "backfill_applying" || "$persisted_phase" == "migrated" ]]; then
		for service in agentium-backend agentium-worker-cpu; do
			if docker inspect "$service" >/dev/null 2>&1; then
				ensure_container_unpaused "$service"
				docker stop --time 45 "$service" >/dev/null 2>&1 || true
				[[ "$(docker inspect --format '{{.State.Running}}' "$service")" == "false" ]] || die "$service écrit encore à la reprise"
			fi
		done
		assert_rabbitmq_empty "resume-${persisted_phase}"
		assert_postgres_quiescent
	else
		assert_rabbitmq_empty "resume-${persisted_phase}"
		if docker inspect agentium-worker-cpu >/dev/null 2>&1 &&
			[[ "$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' agentium-worker-cpu | awk -F= '$1 == "CELERY_BEAT" {print $2; exit}')" != "0" ]]; then
			ensure_container_unpaused agentium-worker-cpu
			docker stop --time 45 agentium-worker-cpu >/dev/null 2>&1 || true
			AGENTIUM_CELERY_BEAT=0 AGENTIUM_PIN_CANDIDATE_IMAGES=1 \
				compose up -d --no-build --force-recreate agentium-worker-cpu
		fi
		AGENTIUM_CELERY_BEAT=0 AGENTIUM_STARTUP_RECONCILIATION=disabled \
			AGENTIUM_PIN_CANDIDATE_IMAGES=1 compose up -d --no-build agentium-backend agentium-frontend agentium-worker-cpu
		wait_container_healthy agentium-backend
		wait_container_healthy agentium-frontend
		wait_container_healthy agentium-worker-cpu
		for service in agentium-backend agentium-frontend agentium-worker-cpu; do
			assert_candidate_container_image "$service"
		done
		[[ "$(active_application_sha)" == "$EXPECTED_SHA" ]] || die "Runtime candidat divergent à la reprise"
		assert_worker_scheduler_mode 0
		assert_rabbitmq_empty "resume-${persisted_phase}-ready"
		if [[ "$persisted_phase" == "validation_pending" ]]; then
			capture_running_binding_contract "$DEPLOY_DIR/post-activation-bindings.json"
			python3 -c 'import json,sys; p=json.load(open(sys.argv[1], encoding="utf-8")); assert p.get("result") == "passed"' \
				"$DEPLOY_DIR/database-startup-comparison.json" || die "Preuve startup candidate absente à la reprise"
			restore_identity_runtime_state
		else
			run_live_binding_audit
		fi
	fi
	assert_sftp_restart_policy_no
	assert_legacy_sftp_systemd_safe
	[[ "$(phase)" == "$persisted_phase" ]] || die "La reprise a altéré la phase durable"
}

activate_candidate() {
	STAGE="candidate activation"
	env -i PATH="$COMPOSE_CLEAN_PATH" HOME="$COMPOSE_CLEAN_HOME" DOCKER_CONFIG="$COMPOSE_CLEAN_HOME/.docker" DOCKER_HOST="$DOCKER_LOCAL_HOST" \
		OMNIRAG_REPO_DIR="$REPO_DIR" AGENTIUM_DEPLOY_STATE_DIR="$ROLLBACK_DIR" \
		AGENTIUM_SAFE_DEPLOY_ORCHESTRATED=1 AGENTIUM_SAFE_DEPLOYMENT_DIR="$DEPLOY_DIR" \
		AGENTIUM_SAFE_ENV_BUNDLE_DIR="$ENV_BUNDLE_DIR" \
		AGENTIUM_SAFE_ENV_MANIFEST_SHA256="$ENV_MANIFEST_SHA256" \
		AGENTIUM_SAFE_ENV_BUNDLE_HELPER="$ENV_BUNDLE_HELPER" \
		AGENTIUM_SAFE_QDRANT_OVERRIDE_FILE="$FROZEN_QDRANT_OVERRIDE" \
		AGENTIUM_SAFE_CANDIDATE_IMAGE_OVERRIDE_FILE="$CANDIDATE_IMAGE_OVERRIDE" \
		AGENTIUM_QDRANT_EFFECTIVE_API_KEY="$(qdrant_server_key read-only)" \
		AGENTIUM_CELERY_BEAT=0 AGENTIUM_STARTUP_RECONCILIATION=disabled \
		bash "$FROZEN_DEPLOYER" --activate-only --branch "$BRANCH" \
		--sha "$EXPECTED_SHA" --previous-sha "$(metadata previous_sha)" --defer-auxiliary-start
	stage_auxiliary_candidate_state
	set_application_restart_policies_no
	assert_worker_scheduler_mode 0
	assert_rabbitmq_empty candidate
	STAGE="candidate Qdrant write barrier"
	attest_candidate_qdrant_barrier "$QDRANT_VALIDATION_BARRIER"
	STAGE="post-activation binding audit"
	run_live_binding_audit
	set_phase activated
}

verify_storage_after_activation() {
	STAGE="storage post-activation attestation"
	snapshot_storage "$STORAGE_AFTER"
	python3 "$STORAGE_HELPER" compare \
		--before "$STORAGE_QUIESCED" --after "$STORAGE_AFTER" --output "$STORAGE_COMPARISON"
	chmod 0600 "$STORAGE_COMPARISON"
	# Keycloak is a PostgreSQL writer. Persist the maximal possible state before
	# starting it so SIGKILL/reboot resumes through a quiescing boundary.
	set_phase validation_starting
	STAGE="Keycloak validation-only release under HTTP gate"
	restore_identity_runtime_state
	set_phase validation_pending
}

apply_impl() {
	local current checkout_sha
	prepare_impl
	current="$(phase)"
	if [[ "$current" == "prepared" && "$(gate status 2>/dev/null)" == "closed" ]]; then
		recover_prepared_barrier_failure || die "Récupération d'un armement pré-fermeture interrompu impossible"
		current="$(phase)"
	fi
	if [[ "$current" == "recovering_pre_migration" ]]; then
		recover_pre_migration_failure || die "Récupération pré-migration durable incomplète"
		current="$(phase)"
	fi
	if [[ "$current" == "prepared" ]]; then apply_preflight_checks; fi
	case "$current" in
	closing_intent | closing | maintenance_closed)
		checkout_sha="$(git rev-parse HEAD)"
		if [[ "$checkout_sha" == "$(metadata previous_sha)" ]]; then
			:
		elif [[ "$current" == "maintenance_closed" && "$checkout_sha" == "$EXPECTED_SHA" ]]; then
			# git reset --hard is not atomic with the following phase write.  The
			# durable intent was fsynced first, so rerunning the reset safely
			# completes a crash interrupted at this exact A -> B boundary.
			assert_candidate_checkout_intent
		else
			die "Checkout inattendu avant quiescence complète"
		fi
		verify_candidate_images_and_rollback
		;;
	quiesced | backfill_pending | backfill_applying | migrated | activated | validation_starting | validation_pending | opening_forward | opened | completed)
		[[ "$(git rev-parse HEAD)" == "$EXPECTED_SHA" ]] || die "Resume sur un checkout différent du candidat"
		verify_candidate_images_and_rollback
		;;
	rollback_closing | rollback_restoring | rolled_back_restored | rollback_opening | rolled_back)
		[[ "$(git rev-parse HEAD)" == "$(metadata previous_sha)" ]] || die "Checkout précédent absent pendant la reprise rollback"
		verify_candidate_images_and_rollback
		;;
	esac
	[[ "$current" != "rollback_restoring" ]] || die "Restauration DB en cours: relancer explicitement rollback --confirm-rollback"
	[[ "$current" != "rollback_closing" ]] || die "Rollback engagé: relancer explicitement rollback --confirm-rollback"
	if [[ "$current" == "rolled_back_restored" ]]; then complete_rollback_after_restore; return; fi
	if [[ "$current" == "rollback_opening" ]]; then reconcile_rollback_opening; return; fi
	if [[ "$current" == "rolled_back" ]]; then return; fi
	case "$current" in
	prepared | closing_intent | closing | maintenance_closed) quiesce_all_writers; current="$(phase)" ;;
	esac
	if [[ "$current" == "quiesced" ]]; then reestablish_persisted_phase_boundary "$current"; migrate_candidate; current="$(phase)"; fi
	if [[ "$current" == "backfill_pending" && -z "$WORKSPACE_APP_ANALYSIS_SHA" ]]; then
		say "Backfill Workspace Apps en attente; reprendre avec --workspace-app-analysis-sha $(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding=\"utf-8\"))[\"analysis_sha256\"])' "$WORKSPACE_APP_DRY_RUN")"
		return
	fi
	if [[ "$current" == "backfill_pending" || "$current" == "backfill_applying" ]]; then
		reestablish_persisted_phase_boundary "$current"
		apply_workspace_app_backfill
		current="$(phase)"
	fi
	if [[ "$current" == "migrated" ]]; then reestablish_persisted_phase_boundary "$current"; activate_candidate; current="$(phase)"; fi
	if [[ "$current" == "activated" ]]; then reestablish_persisted_phase_boundary "$current"; verify_storage_after_activation; current="$(phase)"; fi
	if [[ "$current" == "validation_starting" ]]; then reestablish_persisted_phase_boundary "$current"; verify_storage_after_activation; current="$(phase)"; fi
	if [[ "$current" == "validation_pending" ]]; then reestablish_persisted_phase_boundary "$current"; fi
	if [[ "$current" == "opening_forward" ]]; then reconcile_opening_forward; return; fi
	if [[ "$current" == "opened" ]]; then set_phase completed; return; fi
	[[ "$current" == "validation_pending" || "$current" == "completed" ]] || die "Phase non reprenable: $current"
	if [[ "$current" == "validation_pending" ]]; then
		say "Candidat sain; gate public volontairement fermé. Produire les canaris puis exécuter resume --validation-artifact <json>."
	fi
}

verify_validation_artifact() {
	local artifact_real deploy_real expected_artifact database_revision
	[[ -n "$VALIDATION_ARTIFACT" ]] || die "--validation-artifact est obligatoire pour rouvrir le trafic"
	artifact_real="$(realpath -m "$VALIDATION_ARTIFACT")"
	deploy_real="$(realpath -e "$DEPLOY_DIR")"
	database_revision="$(<"$DEPLOY_DIR/candidate-database-revision")"
	[[ "$(current_database_revision)" == "$database_revision" ]] || die "Révision DB modifiée depuis les canaris"
	expected_artifact="$deploy_real/validation.json"
	[[ "$artifact_real" == "$expected_artifact" ]] || die "L'artefact doit être exactement $expected_artifact"
	"$VALIDATION_HELPER" verify \
		--deployment-id "$DEPLOYMENT_ID" --sha "$EXPECTED_SHA" \
		--sftp-sha "$(metadata sftp_release_sha)" \
		--alembic-revision "$database_revision" --deployment-dir "$DEPLOY_DIR" \
		--provenance "$DEPLOY_DIR/proofs/provenance.json" \
		--showcase "$DEPLOY_DIR/proofs/showcase.json" \
		--andritz "$DEPLOY_DIR/proofs/andritz.json" \
		--sentinel "$DEPLOY_DIR/proofs/sentinel.json" \
		--octocity "$DEPLOY_DIR/proofs/octocity.json" \
		--storage-before "$STORAGE_QUIESCED" --storage-after "$STORAGE_AFTER" \
		--storage-comparison "$STORAGE_COMPARISON" \
		--sftp-closed-before "$SFTP_CLOSED_BEFORE" \
		--sftp-closed-after "$SFTP_CLOSED_AFTER" \
		--qdrant-preflight-barrier "$QDRANT_PREFLIGHT_BARRIER" \
		--qdrant-validation-barrier "$QDRANT_VALIDATION_BARRIER" \
		--qdrant-backend-probe "$QDRANT_BACKEND_PROBE" \
		--qdrant-worker-probe "$QDRANT_WORKER_PROBE" \
		--qdrant-post-canary-barrier "$QDRANT_POST_CANARY_BARRIER" \
		--database-canary-baseline "$DATABASE_CANARY_BASELINE" \
		--database-post-canary "$DATABASE_POST_CANARY_INVENTORY" \
		--database-final "$DATABASE_FINAL_CANARY_INVENTORY" \
		--database-post-canary-comparison "$DATABASE_POST_CANARY_COMPARISON"
	sha256sum "$artifact_real" >"$DEPLOY_DIR/validation-artifact.sha256"
	chmod 0600 "$DEPLOY_DIR/validation-artifact.sha256"
}

refresh_and_build_validation() {
	local recomputed="$DEPLOY_DIR/.storage-canary-comparison.$$"
	STAGE="post-canary Qdrant write barrier"
	attest_candidate_qdrant_barrier "$QDRANT_POST_CANARY_BARRIER"
	STAGE="post-canary storage proof verification"
	[[ -s "$STORAGE_POST_CANARY" && -s "$STORAGE_CANARY_COMPARISON" ]] || die "Preuve stockage post-canari absente"
	python3 - "$STORAGE_CANARY_COMPARISON" "$STORAGE_POST_CANARY" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
path = Path(sys.argv[1])
p = json.loads(path.read_text(encoding="utf-8"))
assert p.get("profile") == "agentium-storage-object-additions-v1"
assert p.get("assurance") == "cryptographic_entry_inclusion"
assert p.get("authoritative_exact_comparison_required") is True
assert p.get("result") == "passed" and p.get("failed_checks") == []
for artifact in map(Path, sys.argv[1:]):
    age = datetime.now(timezone.utc).timestamp() - artifact.stat().st_mtime
    assert -300 <= age <= 3600
PY
	python3 "$STORAGE_HELPER" compare --allow-object-additions \
		--before "$STORAGE_AFTER" --after "$STORAGE_POST_CANARY" --output "$recomputed"
	chmod 0600 "$recomputed"
	if ! cmp -s "$recomputed" "$STORAGE_CANARY_COMPARISON"; then
		rm -f "$recomputed"
		die "La preuve append-only ne correspond plus aux snapshots liés par Andritz"
	fi
	rm -f "$recomputed"
	STAGE="post-canary PostgreSQL controlled inventory"
	capture_candidate_database_inventory "$DATABASE_POST_CANARY_INVENTORY" controlled
	capture_candidate_database_inventory "$DATABASE_FINAL_CANARY_INVENTORY" controlled
	compare_controlled_canary_database "$DATABASE_FINAL_CANARY_INVENTORY" "$DATABASE_POST_CANARY_COMPARISON"
	STAGE="validation artifact rebuild"
	"$VALIDATION_HELPER" build \
		--deployment-id "$DEPLOYMENT_ID" --sha "$EXPECTED_SHA" \
		--sftp-sha "$(metadata sftp_release_sha)" \
		--alembic-revision "$(current_database_revision)" --deployment-dir "$DEPLOY_DIR" \
		--provenance "$DEPLOY_DIR/proofs/provenance.json" \
		--showcase "$DEPLOY_DIR/proofs/showcase.json" \
		--andritz "$DEPLOY_DIR/proofs/andritz.json" \
		--sentinel "$DEPLOY_DIR/proofs/sentinel.json" \
		--octocity "$DEPLOY_DIR/proofs/octocity.json" \
		--storage-before "$STORAGE_QUIESCED" --storage-after "$STORAGE_AFTER" \
		--storage-comparison "$STORAGE_COMPARISON" \
		--sftp-closed-before "$SFTP_CLOSED_BEFORE" \
		--sftp-closed-after "$SFTP_CLOSED_AFTER" \
		--qdrant-preflight-barrier "$QDRANT_PREFLIGHT_BARRIER" \
		--qdrant-validation-barrier "$QDRANT_VALIDATION_BARRIER" \
		--qdrant-backend-probe "$QDRANT_BACKEND_PROBE" \
		--qdrant-worker-probe "$QDRANT_WORKER_PROBE" \
		--qdrant-post-canary-barrier "$QDRANT_POST_CANARY_BARRIER" \
		--database-canary-baseline "$DATABASE_CANARY_BASELINE" \
		--database-post-canary "$DATABASE_POST_CANARY_INVENTORY" \
		--database-final "$DATABASE_FINAL_CANARY_INVENTORY" \
		--database-post-canary-comparison "$DATABASE_POST_CANARY_COMPARISON"
}

prepare_sftp_opening_artifact() {
	local target="$1"
	[[ "$target" == "$DEPLOY_DIR/proofs/"* ]] || die "Preuve SFTP hors du deployment privé"
	[[ ! -L "$target" ]] || die "Preuve SFTP symbolique refusée"
	rm -f -- "$target"
}

capture_sftp_rollback_closed_boundary() {
	local sftp_sha
	sftp_sha="$(metadata sftp_release_sha)"
	[[ "$(historical_runtime_state agentium-sftp)" != "absent" ]] ||
		die "SFTP historique absent: continuité rollback non attestable"
	assert_previous_container_image agentium-sftp
	[[ "$(docker inspect --format '{{.State.Running}}' agentium-sftp)" == "false" ]] ||
		die "SFTP doit être arrêté avant la frontière rollback"
	assert_sftp_restart_policy_no
	sftp_ingress_gate_is_closed || die "Gate SFTP ouvert pendant la capture rollback"
	prepare_sftp_opening_artifact "$SFTP_ROLLBACK_CLOSED"
	"$SFTP_BOUNDARY_HELPER" closed-boundary \
		--sha "$EXPECTED_SHA" --sftp-sha "$sftp_sha" \
		--deployment-id "$DEPLOYMENT_ID" \
		--expected-secure-source "$EXPECTED_SECURE_SOURCE" \
		--output "$SFTP_ROLLBACK_CLOSED"
	[[ -s "$SFTP_ROLLBACK_CLOSED" && ! -L "$SFTP_ROLLBACK_CLOSED" && "$(stat -c '%a:%u:%h' "$SFTP_ROLLBACK_CLOSED")" == "600:$(id -u):1" ]] ||
		die "Preuve privée de frontière SFTP rollback absente"
}

assert_sftp_opening_intent_contract() {
	local expected_sha="$1" expected_sftp_sha="$2"
	[[ -e "$SFTP_OPENING_INTENT" || -L "$SFTP_OPENING_INTENT" ]] || return 0
	assert_private_state_file "$SFTP_OPENING_INTENT"
	python3 - "$SFTP_OPENING_INTENT" "$expected_sha" "$expected_sftp_sha" "$SFTP_PROTOCOL_PROOF" "$SFTP_PUBLISHED_PROOF" <<'PY'
import hashlib
import re
import sys
from pathlib import Path

intent = Path(sys.argv[1])
expected_sha, expected_sftp_sha = sys.argv[2:4]
protocol, published = map(Path, sys.argv[4:])
value = intent.read_text(encoding="utf-8").strip()
parts = value.split(":", 3)
if len(parts) != 4 or parts[1] != expected_sha or parts[2] != expected_sftp_sha:
    raise SystemExit("SFTP opening intent identity differs")
state, _, _, detail = parts
if state == "not-applicable":
    if detail != "historically-stopped":
        raise SystemExit("SFTP not-applicable intent is malformed")
elif state in {"pending", "passed"}:
    if re.fullmatch(r"[0-9a-f]{64}", detail) is None:
        raise SystemExit("SFTP opening intent digest is malformed")
    proof = protocol if state == "pending" else published
    if not proof.is_file() or proof.is_symlink():
        raise SystemExit("SFTP opening intent proof is missing")
    if hashlib.sha256(proof.read_bytes()).hexdigest() != detail:
        raise SystemExit("SFTP opening intent proof digest differs")
else:
    raise SystemExit("SFTP opening intent state is unknown")
PY
}

release_sftp_ingress_with_attestation() {
	local runtime_sha="$1" sftp_sha desired port proof_sha
	sftp_sha="$(metadata sftp_release_sha)"
	assert_sftp_opening_intent_contract "$runtime_sha" "$sftp_sha"
	desired="$(original_runtime_state agentium-sftp)"
	case "$desired" in
	running)
		[[ "$(docker inspect --format '{{.State.Running}}' agentium-sftp)" == "true" ]] ||
			die "SFTP historique actif non restauré avant sa preuve d'ouverture"
		assert_sftp_restart_policy_no
		sftp_ingress_gate_is_closed || die "Gate SFTP ouvert avant la preuve interne"
		prepare_sftp_opening_artifact "$SFTP_PROTOCOL_PROOF"
		prepare_sftp_opening_artifact "$SFTP_PUBLISHED_PROOF"
		STAGE="SFTP Docker protocol proof under closed ingress"
		"$SFTP_BOUNDARY_HELPER" docker-protocol \
			--sha "$runtime_sha" --deployment-id "$DEPLOYMENT_ID" \
			--sftp-sha "$sftp_sha" \
			--closed-proof "$SFTP_CLOSED_AFTER" --output "$SFTP_PROTOCOL_PROOF"
		[[ -s "$SFTP_PROTOCOL_PROOF" && ! -L "$SFTP_PROTOCOL_PROOF" && "$(stat -c '%a' "$SFTP_PROTOCOL_PROOF")" == "600" ]] ||
			die "Preuve protocole SFTP privée absente"
		atomic_text "$SFTP_OPENING_INTENT" "pending:${runtime_sha}:${sftp_sha}:$(sha256sum "$SFTP_PROTOCOL_PROOF" | awk '{print $1}')"
		STAGE="SFTP published boundary proof under external ingress gate"
		if ! "$SFTP_BOUNDARY_HELPER" host-banner \
			--sha "$runtime_sha" --deployment-id "$DEPLOYMENT_ID" \
			--sftp-sha "$sftp_sha" \
			--protocol-proof "$SFTP_PROTOCOL_PROOF" \
			--validation-proof "$DEPLOY_DIR/validation.json" \
			--output "$SFTP_PUBLISHED_PROOF"; then
			printf 'XX  Preuve du port SFTP publié en échec; gate maintenu fermé.\n' >&2
			sftp_ingress_gate_is_closed || die "Gate SFTP absent après échec de preuve"
			return 1
		fi
		[[ -s "$SFTP_PUBLISHED_PROOF" && ! -L "$SFTP_PUBLISHED_PROOF" && "$(stat -c '%a' "$SFTP_PUBLISHED_PROOF")" == "600" ]] || {
			enter_sftp_ingress_gate
			die "Attestation publiée SFTP absente; gate réinstallé"
		}
		proof_sha="$(sha256sum "$SFTP_PUBLISHED_PROOF" | awk '{print $1}')"
		[[ "$proof_sha" =~ ^[0-9a-f]{64}$ ]] || {
			enter_sftp_ingress_gate
			die "Digest attestation SFTP publié invalide; gate réinstallé"
		}
		atomic_text "$SFTP_OPENING_INTENT" "passed:${runtime_sha}:${sftp_sha}:${proof_sha}"
		assert_sftp_opening_intent_contract "$runtime_sha" "$sftp_sha"
		;;
	stopped)
		[[ "$(docker inspect --format '{{.State.Running}}' agentium-sftp)" == "false" ]] ||
			die "SFTP historiquement arrêté a été démarré"
		atomic_text "$SFTP_OPENING_INTENT" "not-applicable:${runtime_sha}:${sftp_sha}:historically-stopped"
		;;
	*) die "État historique SFTP non prouvable à l'ouverture: $desired" ;;
	esac
}

remount_secure_deposit_after_sftp_proof() {
	local desired
	desired="$(original_runtime_state agentium-sftp)"
	assert_sftp_opening_intent_contract "$EXPECTED_SHA" "$(metadata sftp_release_sha)"
	case "$desired" in
	running)
		[[ "$(sftp_established_connection_count)" == "0" && "$(sftp_open_deposit_fd_count)" == "0" ]] ||
			die "SFTP conserve une activité avant le remount Secure Deposit"
		;;
	stopped)
		[[ "$(docker inspect --format '{{.State.Running}}' agentium-sftp)" == "false" ]] ||
			die "SFTP historiquement arrêté est actif avant le remount"
		;;
	*) die "État historique SFTP invalide avant le remount Secure Deposit" ;;
	esac
	set_secure_deposit_mode rw
	sftp_ingress_gate_is_closed || die "Gate SFTP retiré pendant le remount Secure Deposit"
}

open_sftp_ingress_after_attestation() {
	local desired port
	desired="$(original_runtime_state agentium-sftp)"
	assert_sftp_opening_intent_contract "$EXPECTED_SHA" "$(metadata sftp_release_sha)"
	[[ "$(secure_deposit_mode)" == "rw" ]] || die "Secure Deposit encore en lecture seule avant ouverture SFTP"
	sftp_ingress_gate_is_closed || die "Gate SFTP déjà retiré avant la dernière frontière"
	if [[ "$desired" == "running" ]]; then
		assert_previous_container_image agentium-sftp
		assert_sftp_restart_policy_no
		[[ "$(sftp_established_connection_count)" == "0" && "$(sftp_open_deposit_fd_count)" == "0" ]] ||
			die "SFTP conserve une activité avant sa frontière publique"
	elif [[ "$desired" != "stopped" ]]; then
		die "État historique SFTP non ouvrable: $desired"
	fi
	leave_sftp_ingress_gate
	if [[ "$desired" == "running" ]]; then
		! sftp_ingress_gate_is_closed || die "Gate SFTP encore fermé après attestation durable"
	else
		port="$(sftp_published_port)"
		assert_no_tcp_listener "$port" "SFTP historiquement arrêté"
	fi
}

assert_sftp_rollback_continuity_receipt() {
	local previous_sha="$1" candidate_sha="$2" sftp_sha="$3" sftp_id backend_id closed_sha
	sftp_id="$(docker inspect --format '{{.Id}}' agentium-sftp)"
	backend_id="$(docker inspect --format '{{.Id}}' agentium-backend)"
	closed_sha="$(sha256sum "$SFTP_ROLLBACK_CLOSED" | awk '{print $1}')"
	python3 -I - "$SFTP_ROLLBACK_PROOF" "$previous_sha" "$candidate_sha" "$sftp_sha" "$DEPLOYMENT_ID" "$sftp_id" "$backend_id" "$closed_sha" <<'PY'
import json
import os
import re
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
previous_sha, candidate_sha, sftp_sha, deployment_id, sftp_id, backend_id, closed_sha = sys.argv[2:]
fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
try:
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1 or not 1 <= before.st_size <= 2 * 1024 * 1024:
        raise SystemExit("unsafe SFTP rollback continuity receipt")
    raw = os.read(fd, before.st_size + 1)
    after = os.fstat(fd)
finally:
    os.close(fd)
linked = path.lstat()
identity = lambda row: (row.st_dev,row.st_ino,row.st_size,row.st_mtime_ns,row.st_ctime_ns,row.st_uid,row.st_nlink,stat.S_IMODE(row.st_mode))
if identity(before) != identity(after) or identity(after) != identity(linked):
    raise SystemExit("SFTP rollback continuity receipt changed while read")
try: value = json.loads(raw)
except (UnicodeDecodeError,json.JSONDecodeError) as exc: raise SystemExit("invalid SFTP rollback continuity receipt") from exc
expected_keys={"schema_version","kind","profile","sha","candidate_sha","sftp_sha","deployment_id","captured_at","result","sftp_identity","client_identity","revision_binding","closed_boundary","ingress_gate","secure_deposit","host_key","protocol","published_transport","authentication_audit","credentials_used","content_serialized","raw_network_data_serialized","raw_identification_serialized","assurance","proof_ceiling"}
if not isinstance(value,dict) or set(value)!=expected_keys or value.get("schema_version")!=1 or value.get("kind")!="agentium_sftp_deploy_boundary" or value.get("profile")!="agentium-sftp-rollback-continuity-v1" or value.get("result")!="passed":
    raise SystemExit("SFTP rollback continuity receipt schema differs")
if (value.get("sha"),value.get("candidate_sha"),value.get("sftp_sha"),value.get("deployment_id"))!=(previous_sha,candidate_sha,sftp_sha,deployment_id):
    raise SystemExit("SFTP rollback continuity receipt identity differs")
sftp=value.get("sftp_identity"); client=value.get("client_identity"); closed=value.get("closed_boundary")
if not isinstance(sftp,dict) or sftp.get("container_id")!=sftp_id or sftp.get("image_id") is None or sftp.get("revision")!=sftp_sha or sftp.get("healthy") is not True or sftp.get("restart_policy_disabled") is not True:
    raise SystemExit("SFTP rollback runtime identity differs")
if not isinstance(client,dict) or client.get("container_id")!=backend_id or client.get("revision")!=previous_sha or client.get("is_previous_runtime") is not True:
    raise SystemExit("SFTP rollback client identity differs")
if not isinstance(closed,dict) or closed.get("sha256")!=closed_sha or any(closed.get(key) is not True for key in ("candidate_sha_bound","sftp_sha_bound","deployment_id_bound","same_container_id","same_image_id","same_host_key_fingerprint","fresh")):
    raise SystemExit("SFTP rollback closed-boundary binding differs")
gate=value.get("ingress_gate")
expected_gate={"ipv4_input":True,"ipv4_docker_user":True,"ipv6_input":True,"ipv6_docker_user":True}
if not isinstance(gate,dict) or gate.get("before")!=expected_gate or gate.get("during_published_probe")!=expected_gate or gate.get("after")!=expected_gate or gate.get("remained_closed") is not True:
    raise SystemExit("SFTP rollback gate evidence differs")
secure=value.get("secure_deposit")
if not isinstance(secure,dict) or secure.get("same_device") is not True or secure.get("remained_read_only") is not True or secure.get("before")!=secure.get("after") or secure.get("before",{}).get("read_only") is not True:
    raise SystemExit("SFTP rollback Secure Deposit evidence differs")
published=value.get("published_transport")
if published!={"ssh_v2_identification_validated":True,"connection_closed_before_authentication":True,"raw_identification_serialized":False,"loopback_probe":True,"external_gate_closed_during_probe":True}:
    raise SystemExit("SFTP rollback published transport evidence differs")
protocol=value.get("protocol"); audit=value.get("authentication_audit")
if not isinstance(protocol,dict) or protocol.get("password_submitted") is not False or protocol.get("sftp_subsystem_requested") is not False or protocol.get("directory_enumeration_requested") is not False:
    raise SystemExit("SFTP rollback protocol evidence differs")
if not isinstance(audit,dict) or audit.get("unchanged") is not True or audit.get("before_inventory_sha256")!=audit.get("after_inventory_sha256") or any(audit.get(key)!=0 for key in ("added_count","removed_count","changed_count")):
    raise SystemExit("SFTP rollback auth evidence differs")
if any(value.get(key) is not False for key in ("credentials_used","content_serialized","raw_network_data_serialized","raw_identification_serialized")) or value.get("proof_ceiling")!="runner_verified":
    raise SystemExit("SFTP rollback evidence safety flags differ")
if re.fullmatch(r"[0-9a-f]{64}",closed_sha) is None:
    raise SystemExit("SFTP rollback closed-boundary digest is invalid")
PY
}

assert_sftp_rollback_opening_intent_contract() {
	local previous_sha="$1" candidate_sha="$2" sftp_sha="$3"
	[[ -e "$SFTP_ROLLBACK_OPENING_INTENT" || -L "$SFTP_ROLLBACK_OPENING_INTENT" ]] || return 0
	assert_private_state_file "$SFTP_ROLLBACK_OPENING_INTENT"
	python3 -I - "$SFTP_ROLLBACK_OPENING_INTENT" "$previous_sha" "$candidate_sha" "$sftp_sha" "$SFTP_ROLLBACK_PROOF" <<'PY'
import hashlib
import re
import sys
from pathlib import Path

intent, proof = Path(sys.argv[1]), Path(sys.argv[5])
previous_sha, candidate_sha, sftp_sha = sys.argv[2:5]
parts = intent.read_text(encoding="ascii").strip().split(":", 4)
if len(parts) != 5 or parts[1:4] != [previous_sha, candidate_sha, sftp_sha]:
    raise SystemExit("SFTP rollback opening intent identity differs")
state, detail = parts[0], parts[4]
if state == "not-applicable":
    if detail != "historically-stopped":
        raise SystemExit("SFTP rollback not-applicable intent is malformed")
elif state == "passed":
    if re.fullmatch(r"[0-9a-f]{64}", detail) is None:
        raise SystemExit("SFTP rollback proof digest is malformed")
    if not proof.is_file() or proof.is_symlink():
        raise SystemExit("SFTP rollback continuity proof is missing")
    if hashlib.sha256(proof.read_bytes()).hexdigest() != detail:
        raise SystemExit("SFTP rollback continuity proof digest differs")
else:
    raise SystemExit("SFTP rollback opening intent state is unknown")
PY
}

release_rollback_sftp_ingress_with_attestation() {
	local previous_sha candidate_sha sftp_sha desired proof_sha
	previous_sha="$(metadata previous_sha)"
	candidate_sha="$EXPECTED_SHA"
	sftp_sha="$(metadata sftp_release_sha)"
	desired="$(historical_runtime_state agentium-sftp)"
	case "$desired" in
	running)
		[[ "$(docker inspect --format '{{.State.Running}}' agentium-sftp)" == "true" ]] ||
			die "SFTP rollback actif non restauré avant preuve"
		assert_previous_container_image agentium-sftp
		assert_sftp_restart_policy_no
		sftp_ingress_gate_is_closed || die "Gate SFTP ouvert avant preuve rollback"
		prepare_sftp_opening_artifact "$SFTP_ROLLBACK_PROOF"
		STAGE="SFTP rollback protocol and published-loopback continuity proof"
		"$SFTP_BOUNDARY_HELPER" rollback-continuity \
			--sha "$previous_sha" --candidate-sha "$candidate_sha" \
			--sftp-sha "$sftp_sha" --deployment-id "$DEPLOYMENT_ID" \
			--closed-proof "$SFTP_ROLLBACK_CLOSED" \
			--expected-secure-source "$EXPECTED_SECURE_SOURCE" \
			--output "$SFTP_ROLLBACK_PROOF"
		[[ -s "$SFTP_ROLLBACK_PROOF" && ! -L "$SFTP_ROLLBACK_PROOF" && "$(stat -c '%a:%u:%h' "$SFTP_ROLLBACK_PROOF")" == "600:$(id -u):1" ]] ||
			die "Preuve privée de continuité SFTP rollback absente"
		assert_sftp_rollback_continuity_receipt "$previous_sha" "$candidate_sha" "$sftp_sha"
		proof_sha="$(sha256sum "$SFTP_ROLLBACK_PROOF" | awk '{print $1}')"
		[[ "$proof_sha" =~ ^[0-9a-f]{64}$ ]] || die "Digest de continuité SFTP rollback invalide"
		atomic_text "$SFTP_ROLLBACK_OPENING_INTENT" "passed:${previous_sha}:${candidate_sha}:${sftp_sha}:${proof_sha}"
		assert_sftp_rollback_opening_intent_contract "$previous_sha" "$candidate_sha" "$sftp_sha"
		[[ "$(sftp_established_connection_count)" == "0" && "$(sftp_open_deposit_fd_count)" == "0" ]] ||
			die "SFTP rollback conserve une activité avant remount"
		;;
	stopped)
		[[ "$(docker inspect --format '{{.State.Running}}' agentium-sftp)" == "false" ]] ||
			die "SFTP rollback historiquement arrêté est actif"
		assert_previous_container_image agentium-sftp
		atomic_text "$SFTP_ROLLBACK_OPENING_INTENT" "not-applicable:${previous_sha}:${candidate_sha}:${sftp_sha}:historically-stopped"
		assert_sftp_rollback_opening_intent_contract "$previous_sha" "$candidate_sha" "$sftp_sha"
		;;
	*) die "État SFTP rollback non prouvable: $desired" ;;
	esac
	sftp_ingress_gate_is_closed || die "Gate SFTP rollback retiré pendant l'attestation"
	[[ "$(secure_deposit_mode)" == "ro" ]] || die "Secure Deposit modifié pendant l'attestation rollback"
}

remount_secure_deposit_after_rollback_sftp_proof() {
	local previous_sha candidate_sha sftp_sha desired
	previous_sha="$(metadata previous_sha)"
	candidate_sha="$EXPECTED_SHA"
	sftp_sha="$(metadata sftp_release_sha)"
	desired="$(historical_runtime_state agentium-sftp)"
	assert_sftp_rollback_opening_intent_contract "$previous_sha" "$candidate_sha" "$sftp_sha"
	if [[ "$desired" == "running" ]]; then
		assert_sftp_rollback_continuity_receipt "$previous_sha" "$candidate_sha" "$sftp_sha"
		assert_sftp_restart_policy_no
		[[ "$(sftp_established_connection_count)" == "0" && "$(sftp_open_deposit_fd_count)" == "0" ]] ||
			die "SFTP rollback conserve une activité avant remount"
	elif [[ "$desired" != "stopped" ]]; then
		die "État SFTP rollback non remountable: $desired"
	fi
	set_secure_deposit_mode rw
	sftp_ingress_gate_is_closed || die "Gate SFTP rollback retiré pendant le remount"
}

open_rollback_sftp_ingress_after_attestation() {
	local previous_sha candidate_sha sftp_sha desired port
	previous_sha="$(metadata previous_sha)"
	candidate_sha="$EXPECTED_SHA"
	sftp_sha="$(metadata sftp_release_sha)"
	desired="$(historical_runtime_state agentium-sftp)"
	assert_sftp_rollback_opening_intent_contract "$previous_sha" "$candidate_sha" "$sftp_sha"
	[[ "$(secure_deposit_mode)" == "rw" ]] || die "Secure Deposit rollback encore en lecture seule avant ouverture SFTP"
	sftp_ingress_gate_is_closed || die "Gate SFTP rollback déjà retiré"
	if [[ "$desired" == "running" ]]; then
		assert_sftp_rollback_continuity_receipt "$previous_sha" "$candidate_sha" "$sftp_sha"
		assert_previous_container_image agentium-sftp
		assert_sftp_restart_policy_no
		[[ "$(sftp_established_connection_count)" == "0" && "$(sftp_open_deposit_fd_count)" == "0" ]] ||
			die "SFTP rollback conserve une activité avant sa frontière publique"
	else
		[[ "$desired" == "stopped" ]] || die "État SFTP rollback non ouvrable: $desired"
	fi
	leave_sftp_ingress_gate
	if [[ "$desired" == "running" ]]; then
		! sftp_ingress_gate_is_closed || die "Gate SFTP rollback encore fermé après preuve durable"
	else
		port="$(sftp_published_port)"
		assert_no_tcp_listener "$port" "SFTP rollback historiquement arrêté"
	fi
}

requiesce_opened_writers_for_reconcile() {
	local label="$1" service
	[[ "$label" =~ ^[a-z-]+$ ]] || die "Label de reconciliation invalide"
	[[ "$(gate status 2>/dev/null)" == "closed" ]] || die "Gate HTTP non fermé pendant la reconciliation"
	sftp_ingress_gate_is_closed || die "Gate SFTP non fermé pendant la reconciliation"
	livekit_ingress_gate_is_closed || die "Gate LiveKit non fermé pendant la reconciliation"
	wait_for_existing_writer_connections_to_drain
	quiesce_sftp
	quiesce_identity_writer
	quiesce_legacy_sftp_systemd
	sudo_command systemctl stop agentium-backend.service >/dev/null 2>&1 || true
	assert_no_tcp_listener 8000 "Backend systemd $label"
	for service in agentium-livekit-agent agentium-livekit agentium-p4-maintenance agentium-backend agentium-worker-cpu; do
		if docker inspect "$service" >/dev/null 2>&1; then
			ensure_container_unpaused "$service"
			docker stop --time 45 "$service" >/dev/null 2>&1 || true
			[[ "$(docker inspect --format '{{.State.Running}}' "$service")" == "false" ]] ||
				die "$service écrit encore pendant la reconciliation"
		fi
	done
	assert_no_tcp_listener 7881 "LiveKit $label"
	assert_no_captured_livekit_listeners
	for service in agentium-backend agentium-worker-cpu agentium-p4-maintenance agentium-sftp agentium-livekit-agent agentium-livekit agentium-kc; do
		[[ "$(docker inspect --format '{{.State.Running}}' "$service" 2>/dev/null || printf false)" == "false" ]] ||
			die "$service reste writer pendant la reconciliation"
	done
	assert_rabbitmq_empty "$label"
	assert_postgres_quiescent
	set_secure_deposit_mode ro
}

seal_public_opening_boundary_fail_closed() {
	local persisted_phase="${1:-$(phase)}" label
	case "$persisted_phase" in
	opening_forward) label=opening-forward ;;
	rollback_opening) label=rollback-opening ;;
	*) return 0 ;;
	esac
	STAGE="fail-closed sealing ($persisted_phase)"
	if [[ "$(gate status 2>/dev/null)" == "open" ]]; then gate enter; fi
	[[ "$(gate status)" == "closed" ]] || die "Gate HTTP non refermé pour $persisted_phase"
	enter_systemd_backend_ingress_gate
	enter_sftp_ingress_gate
	enter_livekit_ingress_gate
	disable_systemd_backend_restart
	set_application_restart_policies_no
	set_sftp_restart_policy_no
	set_realtime_restart_policies_no
	requiesce_opened_writers_for_reconcile "$label"
	[[ "$(gate status)" == "closed" ]] || die "Gate HTTP rouvert pendant la reclosure $persisted_phase"
	sftp_ingress_gate_is_closed || die "Gate SFTP non refermé pour $persisted_phase"
	livekit_ingress_gate_is_closed || die "Gate LiveKit non refermé pour $persisted_phase"
	systemd_backend_ingress_gate_is_closed || die "Gate backend systemd non refermé pour $persisted_phase"
	[[ "$(secure_deposit_mode)" == "ro" ]] || die "Secure Deposit non refermé en lecture seule pour $persisted_phase"
}

reconcile_interrupted_opening_at_startup() {
	local persisted_phase
	persisted_phase="$(phase)"
	case "$persisted_phase" in
	opening_forward | rollback_opening)
		seal_public_opening_boundary_fail_closed "$persisted_phase"
		[[ "$(phase)" == "$persisted_phase" ]] || die "La reclosure startup a altéré l'intention durable"
		;;
	esac
}

finalize_deployment() {
	[[ "$(phase)" == "validation_pending" ]] || die "Le déploiement n'attend pas de validation"
	refresh_and_build_validation
	verify_validation_artifact
	freeze_candidate_image_override
	assert_candidate_tags_match_provenance
	STAGE="final PostgreSQL opening-boundary recapture"
	capture_candidate_database_inventory "$DATABASE_OPENING_RECAPTURE" controlled
	compare_controlled_canary_database "$DATABASE_OPENING_RECAPTURE" "$DATABASE_OPENING_COMPARISON"
	assert_rabbitmq_empty validation
	assert_nginx_unique_edge_topology
	assert_no_rehearsal_residue || die "Résidu rehearsal présent avant la frontière publique"
	assert_no_candidate_oneoff_residue || die "One-off candidat présent avant la frontière publique"
	assert_no_candidate_migration_boundary_residue || die "Frontière migration candidate présente avant la frontière publique"
	assert_no_live_writer_audit_boundary_residue || die "Frontière audit LiveKit présente avant la frontière publique"
	# Persist the irreversible forward-only frontier before releasing the first
	# writer, remounting the deposit RW, or exposing any public transport.
	set_phase opening_forward
	STAGE="candidate Qdrant/FAISS admin clients with scheduler disabled"
	restore_candidate_backend_writer
	restore_candidate_worker_with_scheduler 0
	attest_candidate_qdrant_admin_ready
	STAGE="candidate worker scheduler release"
	restore_candidate_worker_with_scheduler "$(historical_worker_scheduler_mode)"
	STAGE="legacy systemd writer release"
	assert_systemd_env_dropin_contract
	assert_systemd_qdrant_admin_contract
	restore_systemd_backend_state "$EXPECTED_SHA"
	restore_systemd_backend_unit_file_state
	STAGE="auxiliary writer release"
	restore_identity_runtime_state
	restore_auxiliary_runtime_state
	restore_sftp_runtime_state
	STAGE="candidate Qdrant admin readiness after auxiliary restore"
	attest_candidate_qdrant_admin_ready
	assert_all_candidate_runtime_images
	release_sftp_ingress_with_attestation "$EXPECTED_SHA"
	STAGE="systemd backend ingress release"
	leave_systemd_backend_ingress_gate
	STAGE="LiveKit ingress release"
	leave_livekit_ingress_gate
	STAGE="LiveKit restart policy restoration"
	restore_realtime_restart_policies
	restore_application_restart_policies
	assert_no_rehearsal_residue || die "Résidu rehearsal présent avant la réouverture publique"
	assert_no_candidate_oneoff_residue || die "One-off candidat présent avant la réouverture publique"
	assert_no_candidate_migration_boundary_residue || die "Frontière migration candidate présente avant la réouverture publique"
	assert_no_live_writer_audit_boundary_residue || die "Frontière audit LiveKit présente avant la réouverture publique"
	assert_nginx_unique_edge_topology
	assert_all_candidate_runtime_images
	assert_previous_sftp_runtime_image
	STAGE="Secure Deposit writer release after pinned SFTP proof"
	remount_secure_deposit_after_sftp_proof
	STAGE="last public writer frontier: SFTP ingress"
	open_sftp_ingress_after_attestation
	STAGE="SFTP restart policy restoration"
	restore_sftp_restart_policy
	STAGE="public gate reopening"
	gate exit
	[[ "$(gate status)" == "open" ]] || die "Le gate public n'a pas rouvert"
	set_phase opened
	set_phase completed
	ok "Déploiement $DEPLOYMENT_ID terminé sur ${EXPECTED_SHA:0:12}"
}

reconcile_opening_forward() {
	[[ "$(phase)" == "opening_forward" ]] || die "Reconciliation forward candidate hors phase opening_forward"
	[[ "$(git rev-parse HEAD)" == "$EXPECTED_SHA" ]] || die "Checkout candidat absent après ouverture"
	[[ "$(current_database_revision)" == "$(<"$DEPLOY_DIR/candidate-database-revision")" ]] || die "DB candidate divergente après ouverture"
	seal_public_opening_boundary_fail_closed opening_forward
	assert_candidate_image_override_contract
	assert_candidate_tags_match_provenance
	restore_candidate_backend_writer
	restore_candidate_worker_with_scheduler 0
	attest_candidate_qdrant_admin_ready
	restore_candidate_worker_with_scheduler "$(historical_worker_scheduler_mode)"
	assert_systemd_env_dropin_contract
	assert_systemd_qdrant_admin_contract
	restore_systemd_backend_state "$EXPECTED_SHA"
	restore_systemd_backend_unit_file_state
	restore_identity_runtime_state
	restore_auxiliary_runtime_state
	restore_sftp_runtime_state
	attest_candidate_qdrant_admin_ready
	assert_all_candidate_runtime_images
	release_sftp_ingress_with_attestation "$EXPECTED_SHA"
	leave_systemd_backend_ingress_gate
	leave_livekit_ingress_gate
	restore_realtime_restart_policies
	restore_application_restart_policies
	assert_no_rehearsal_residue || die "Résidu rehearsal présent avant la réouverture publique"
	assert_no_candidate_oneoff_residue || die "One-off candidat présent avant la réouverture publique"
	assert_no_candidate_migration_boundary_residue || die "Frontière migration candidate présente avant la réouverture publique"
	assert_no_live_writer_audit_boundary_residue || die "Frontière audit LiveKit présente avant la réouverture publique"
	assert_nginx_unique_edge_topology
	assert_all_candidate_runtime_images
	assert_previous_sftp_runtime_image
	remount_secure_deposit_after_sftp_proof
	open_sftp_ingress_after_attestation
	restore_sftp_restart_policy
	gate exit
	[[ "$(gate status)" == "open" ]] || die "Gate HTTP non rouvert pendant la reconciliation forward"
	assert_legacy_sftp_systemd_safe
	set_phase opened
	set_phase completed
}

force_restore_previous_database() {
	local expected backup="$DEPLOY_DIR/postgres-quiesced.dump" restored="$DEPLOY_DIR/database-rollback-restored-all.tsv"
	expected="$(metadata previous_database_revision)"
	verify_backup "$backup" || die "Backup quiescé invalide; restauration refusée"
	STAGE="database restore"
	printf '%s\n' \
		"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :'target_db' AND pid <> pg_backend_pid();" \
		'DROP DATABASE IF EXISTS :"target_db" WITH (FORCE);' \
		'CREATE DATABASE :"target_db" OWNER :"target_owner";' |
		docker exec -i agentium-pg psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres \
			-v target_db="$POSTGRES_DB" -v target_owner="$POSTGRES_USER"
	docker exec -i agentium-pg pg_restore --exit-on-error --no-owner --no-privileges \
		-U "$POSTGRES_USER" -d "$POSTGRES_DB" <"$backup"
	[[ "$(current_database_revision)" == "$expected" ]] || die "La restauration DB n'a pas retrouvé $expected"
	capture_sql_database_fingerprint "$restored" all
	python3 - "$DEPLOY_DIR/database-quiesced-all-baseline.tsv" "$restored" "$DEPLOY_DIR/database-rollback-comparison.json" <<'PY'
import hashlib, json, os, sys
from pathlib import Path
before, after, output = map(Path, sys.argv[1:])
before_bytes, after_bytes = before.read_bytes(), after.read_bytes()
same = before_bytes == after_bytes
payload = {
    "schema_version": 1,
    "kind": "postgresql_rollback_exact_comparison",
    "result": "passed" if same else "failed",
    "before_sha256": hashlib.sha256(before_bytes).hexdigest(),
    "after_sha256": hashlib.sha256(after_bytes).hexdigest(),
}
temporary = output.parent / f".{output.name}.{os.getpid()}"
with temporary.open("w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
os.chmod(temporary, 0o600)
os.replace(temporary, output)
directory_fd = os.open(output.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
if not same:
    raise SystemExit("restored database differs from the quiesced baseline")
PY
}

establish_rollback_restore_boundary() {
	local service current="$1"
	STAGE="rollback ingress and reboot barriers"
	if [[ "$(gate status 2>/dev/null)" == "open" ]]; then gate enter; fi
	[[ "$(gate status 2>/dev/null)" == "closed" ]] || die "Gate HTTP non fermé pour rollback"
	enter_systemd_backend_ingress_gate
	enter_sftp_ingress_gate
	enter_livekit_ingress_gate
	disable_systemd_backend_restart
	set_application_restart_policies_no
	set_sftp_restart_policy_no
	set_realtime_restart_policies_no
	quiesce_legacy_sftp_systemd
	if [[ "$current" != "rollback_restoring" ]]; then
		wait_for_existing_writer_connections_to_drain
	fi
	quiesce_sftp
	quiesce_identity_writer
	sudo_command systemctl stop agentium-backend.service >/dev/null 2>&1 || true
	assert_no_tcp_listener 8000 "Backend systemd rollback"
	for service in agentium-livekit-agent agentium-livekit agentium-p4-maintenance agentium-backend agentium-worker-cpu; do
		if docker inspect "$service" >/dev/null 2>&1; then
			ensure_container_unpaused "$service"
			docker stop --time 45 "$service" >/dev/null 2>&1 || true
			[[ "$(docker inspect --format '{{.State.Running}}' "$service")" == "false" ]] || die "$service écrit encore pendant rollback"
		fi
	done
	assert_no_captured_livekit_listeners
	assert_rabbitmq_empty rollback
	set_secure_deposit_mode ro
	if [[ "$current" != "rollback_restoring" && ! -s "$DEPLOY_DIR/postgres-quiesced.dump" ]]; then
		create_backup quiesced
	fi
	verify_backup "$DEPLOY_DIR/postgres-quiesced.dump" || die "Backup quiescé absent avant rollback"
	if [[ "$current" != "rollback_restoring" ]]; then
		assert_postgres_quiescent
	fi
}

authorize_append_aware_rollback() {
	local rollback_comparison="$1" database_revision
	[[ -s "$DEPLOY_DIR/validation.json" && -s "$DEPLOY_DIR/proofs/andritz.json" && -s "$STORAGE_CANARY_COMPARISON" ]] ||
		die "Divergence stockage rollback sans preuve validation/Andritz complète"
	database_revision="$(<"$DEPLOY_DIR/candidate-database-revision")"
	"$VALIDATION_HELPER" verify \
		--deployment-id "$DEPLOYMENT_ID" --sha "$EXPECTED_SHA" \
		--sftp-sha "$(metadata sftp_release_sha)" \
		--alembic-revision "$database_revision" --deployment-dir "$DEPLOY_DIR" \
		--provenance "$DEPLOY_DIR/proofs/provenance.json" \
		--showcase "$DEPLOY_DIR/proofs/showcase.json" \
		--andritz "$DEPLOY_DIR/proofs/andritz.json" \
		--sentinel "$DEPLOY_DIR/proofs/sentinel.json" \
		--octocity "$DEPLOY_DIR/proofs/octocity.json" \
		--storage-before "$STORAGE_QUIESCED" --storage-after "$STORAGE_AFTER" \
		--storage-comparison "$STORAGE_COMPARISON" \
		--sftp-closed-before "$SFTP_CLOSED_BEFORE" \
		--sftp-closed-after "$SFTP_CLOSED_AFTER" \
		--qdrant-preflight-barrier "$QDRANT_PREFLIGHT_BARRIER" \
		--qdrant-validation-barrier "$QDRANT_VALIDATION_BARRIER" \
		--qdrant-backend-probe "$QDRANT_BACKEND_PROBE" \
		--qdrant-worker-probe "$QDRANT_WORKER_PROBE" \
		--qdrant-post-canary-barrier "$QDRANT_POST_CANARY_BARRIER" \
		--database-canary-baseline "$DATABASE_CANARY_BASELINE" \
		--database-post-canary "$DATABASE_POST_CANARY_INVENTORY" \
		--database-final "$DATABASE_FINAL_CANARY_INVENTORY" \
		--database-post-canary-comparison "$DATABASE_POST_CANARY_COMPARISON"
	python3 - "$STORAGE_CANARY_COMPARISON" "$rollback_comparison" <<'PY'
import json, sys
from pathlib import Path
canary = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
rollback = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
for payload in (canary, rollback):
    assert payload.get("profile") == "agentium-storage-object-additions-v1"
    assert payload.get("assurance") == "cryptographic_entry_inclusion"
    assert payload.get("result") == "passed" and payload.get("failed_checks") == []
for section in ("additions", "deletions", "modifications"):
    assert rollback.get(section) == canary.get(section), section
additions = rollback["additions"]
assert sum(int(summary.get("count", -1)) for summary in additions.values()) == 1
PY
}

complete_rollback_after_restore() {
	local append_comparison="$DEPLOY_DIR/.storage-rollback-object-additions.$$"
	[[ "$(phase)" == "rolled_back_restored" ]] || die "Finalisation rollback hors phase DB restaurée"
	[[ "$(current_database_revision)" == "$(metadata previous_database_revision)" ]] || die "DB précédente absente avant finalisation rollback"
	if [[ "$(gate status)" == "open" ]]; then gate enter; fi
	enter_systemd_backend_ingress_gate
	enter_sftp_ingress_gate
	enter_livekit_ingress_gate
	disable_systemd_backend_restart
	set_application_restart_policies_no
	set_sftp_restart_policy_no
	set_realtime_restart_policies_no
	quiesce_legacy_sftp_systemd
	set_secure_deposit_mode ro
	STAGE="immutable image rollback"
	assert_rollback_image_override_contract
	env -i PATH="$COMPOSE_CLEAN_PATH" HOME="$COMPOSE_CLEAN_HOME" DOCKER_CONFIG="$COMPOSE_CLEAN_HOME/.docker" DOCKER_HOST="$DOCKER_LOCAL_HOST" \
		OMNIRAG_REPO_DIR="$REPO_DIR" AGENTIUM_DEPLOY_STATE_DIR="$ROLLBACK_DIR" \
		AGENTIUM_SAFE_DEPLOY_ORCHESTRATED=1 AGENTIUM_SAFE_DEPLOYMENT_DIR="$DEPLOY_DIR" \
		AGENTIUM_SAFE_ENV_BUNDLE_DIR="$ENV_BUNDLE_DIR" \
		AGENTIUM_SAFE_ENV_MANIFEST_SHA256="$ENV_MANIFEST_SHA256" \
		AGENTIUM_SAFE_ENV_BUNDLE_HELPER="$ENV_BUNDLE_HELPER" \
		AGENTIUM_SAFE_QDRANT_OVERRIDE_FILE="$FROZEN_QDRANT_OVERRIDE" \
		AGENTIUM_SAFE_ROLLBACK_IMAGE_OVERRIDE_FILE="$ROLLBACK_IMAGE_OVERRIDE" \
		AGENTIUM_QDRANT_EFFECTIVE_API_KEY="$(qdrant_server_key read-only)" \
		AGENTIUM_CELERY_BEAT=0 AGENTIUM_STARTUP_RECONCILIATION=disabled \
		bash "$FROZEN_DEPLOYER" --defer-auxiliary-start --rollback-state "$ROLLBACK_STATE"
	resolve_runtime_paths
	set_application_restart_policies_no
	assert_rabbitmq_empty rollback-restored
	rm -f "$DEPLOY_DIR/storage-rollback.json" "$DEPLOY_DIR/storage-rollback-comparison.json" "$append_comparison"
	snapshot_storage "$DEPLOY_DIR/storage-rollback.json"
	if ! python3 "$STORAGE_HELPER" compare \
		--before "$STORAGE_QUIESCED" --after "$DEPLOY_DIR/storage-rollback.json" \
		--output "$DEPLOY_DIR/storage-rollback-comparison.json"; then
		python3 "$STORAGE_HELPER" compare --allow-object-additions \
			--before "$STORAGE_QUIESCED" --after "$DEPLOY_DIR/storage-rollback.json" \
			--output "$append_comparison"
		authorize_append_aware_rollback "$append_comparison"
		durable_replace_file "$append_comparison" "$DEPLOY_DIR/storage-rollback-comparison.json"
	fi
	previous_runtime_supports_read_only_startup ||
		die "Runtime précédent sans startup non mutatif: DB restaurée, writers arrêtés et gates fermés; reprise manuelle requise"
	restore_previous_systemd_env_dropin
	previous_systemd_runtime_supports_frozen_dotenv ||
		die "Runtime précédent relit .env: DB restaurée, backend systemd arrêté et gates fermés; reprise manuelle requise"
	# LiveKit's public UDP plane is released by the forward-only reconciler.
	set_phase rollback_opening
	reconcile_rollback_opening
}

reconcile_rollback_opening() {
	[[ "$(phase)" == "rollback_opening" ]] || die "Reconciliation rollback hors phase rollback_opening"
	[[ "$(git rev-parse HEAD)" == "$(metadata previous_sha)" ]] || die "Checkout précédent absent après ouverture rollback"
	[[ "$(current_database_revision)" == "$(metadata previous_database_revision)" ]] || die "DB précédente divergente après ouverture rollback"
	seal_public_opening_boundary_fail_closed rollback_opening
	assert_rollback_image_override_contract
	restore_previous_backend_container
	restore_previous_worker_without_scheduler
	attest_previous_qdrant_admin_ready
	restore_identity_runtime_state
	restore_auxiliary_runtime_state
	attest_previous_qdrant_admin_ready
	assert_systemd_qdrant_admin_contract
	restore_systemd_backend_state "$(metadata previous_sha)"
	restore_systemd_backend_unit_file_state
	assert_previous_runtime_images_without_sftp
	# Capture only after every potentially slow non-SFTP restore. The sole work
	# between this fresh stopped boundary and the continuity proof is the pinned
	# SFTP start/healthcheck itself.
	capture_sftp_rollback_closed_boundary
	restore_sftp_runtime_state
	release_rollback_sftp_ingress_with_attestation
	remount_secure_deposit_after_rollback_sftp_proof
	restore_previous_worker_scheduler
	leave_systemd_backend_ingress_gate
	leave_livekit_ingress_gate
	restore_realtime_restart_policies
	restore_application_restart_policies
	assert_previous_runtime_images_without_sftp
	assert_previous_sftp_runtime_image
	assert_sftp_rollback_opening_intent_contract "$(metadata previous_sha)" "$EXPECTED_SHA" "$(metadata sftp_release_sha)"
	if [[ "$(historical_runtime_state agentium-sftp)" == "running" ]]; then
		assert_sftp_rollback_continuity_receipt "$(metadata previous_sha)" "$EXPECTED_SHA" "$(metadata sftp_release_sha)"
	fi
	STAGE="last rollback public writer frontier: SFTP ingress"
	open_rollback_sftp_ingress_after_attestation
	restore_sftp_restart_policy
	gate exit
	[[ "$(gate status)" == "open" ]] || die "Gate HTTP non rouvert pendant la reconciliation rollback"
	assert_legacy_sftp_systemd_safe
	set_phase rolled_back
}

rollback_impl() {
	local current
	ROLLBACK_ACTIVE=1
	[[ "$ROLLBACK_CONFIRMATION" == "$DEPLOYMENT_ID" ]] || die "--confirm-rollback doit répéter le deployment-id"
	current="$(phase)"
	[[ "$current" != "opening_forward" && "$current" != "opened" && "$current" != "completed" ]] || die "Rollback DB automatique interdit après l'intention forward; appliquer un correctif forward"
	if [[ "$current" == "rolled_back_restored" ]]; then complete_rollback_after_restore; return; fi
	if [[ "$current" == "rollback_opening" ]]; then reconcile_rollback_opening; return; fi
	[[ "$current" != "rolled_back" ]] || die "Ce déploiement a déjà été rollbacké"
	[[ "$current" != "new" && "$current" != "preflight_ok" ]] || die "Rien n'a été préparé pour ce rollback"
	resolve_runtime_paths
	if [[ "$current" != "rollback_closing" && "$current" != "rollback_restoring" ]]; then
		set_phase rollback_closing
		current=rollback_closing
	fi
	establish_rollback_restore_boundary "$current"
	if [[ "$current" != "rollback_restoring" ]]; then
		if [[ "$(current_database_revision)" == "$(metadata previous_database_revision)" ]]; then
			set_phase rolled_back_restored
			complete_rollback_after_restore
			ok "Rollback complet de $DEPLOYMENT_ID vérifié"
			return
		fi
		# Persist before DROP/CREATE. A crash from this point is replayed through
		# this dedicated DB-schema-independent boundary and a fresh full restore.
		set_phase rollback_restoring
	fi
	force_restore_previous_database
	set_phase rolled_back_restored
	complete_rollback_after_restore
	ok "Rollback complet de $DEPLOYMENT_ID vérifié"
}

trap 'on_process_exit $?' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

ensure_runtime_env_bundle
assert_recorded_env_bundle_identity
startup_phase="$(phase)"
if [[ -e "$METADATA_FILE" || -L "$METADATA_FILE" ]]; then
	assert_metadata_contract
	assert_recorded_release_a_manifest_gate
	assert_recorded_release_a_gate
	assert_runtime_state_contract
	if [[ -e "$ROLLBACK_STATE" || -L "$ROLLBACK_STATE" ]]; then
		assert_rollback_state_contract
	elif [[ "$startup_phase" != "new" && "$startup_phase" != "preflight_ok" ]]; then
		die "État de rollback durable absent pour la phase $startup_phase"
	fi
fi
resolve_runtime_paths
if [[ -e "$METADATA_FILE" || -L "$METADATA_FILE" ]]; then
	# Startup may be resuming an interrupted database restoration.  Validate
	# the frozen scope here without requiring PostgreSQL to be available; every
	# forward mutation rechecks the live canonical mapping immediately before it.
	assert_frozen_workspace_target_gate
fi
# A SIGKILL cannot be trapped. On the very next invocation, close every public
# writer boundary before cleanup, prepare or resume performs any other work.
reconcile_interrupted_opening_at_startup
reconcile_rehearsal_residue
reconcile_candidate_oneoff_residue
reconcile_candidate_migration_boundary
reconcile_live_writer_audit_boundary
case "$MODE" in
preflight)
	preflight_phase="$(phase)"
	[[ "$preflight_phase" == "new" || "$preflight_phase" == "preflight_ok" ]] ||
		die "Preflight interdit sur une transaction déjà avancée ou terminale: $preflight_phase"
	preflight_checks
	ensure_release_a_manifest_gate
	ensure_release_a_gate
	ensure_workspace_target_gate
	initialize_metadata
	ensure_storage_baseline
	if [[ "$preflight_phase" == "new" ]]; then
		set_phase preflight_ok
	else
		ok "preflight déjà acquis; phase inchangée"
	fi
	;;
prepare)
	prepare_impl
	;;
apply)
	apply_impl
	;;
resume)
	apply_impl
	if [[ "$(phase)" == "validation_pending" ]]; then
		if [[ -n "$VALIDATION_ARTIFACT" ]]; then finalize_deployment; else say "Validation requise; gate maintenu fermé."; fi
	fi
	;;
rollback)
	rollback_impl
	;;
esac
