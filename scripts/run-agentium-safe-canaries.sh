#!/usr/bin/env bash
# Authenticated, tenant-separated validation for deploy-agentium-safe.sh.
#
# This command never opens the maintenance gate, starts SFTP/P4, deploys code,
# or accepts a credential as a command-line argument.  E2E_USERNAME and
# E2E_PASSWORD must be supplied through the process environment.
set +x
set -Eeuo pipefail
umask 077
IFS=$' \t\n'
CANARY_CLEAN_PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin
export PATH="$CANARY_CLEAN_PATH"
export PYTHONDONTWRITEBYTECODE=1
unset BASH_ENV CDPATH ENV GIT_CONFIG_COUNT GIT_CONFIG_GLOBAL GIT_CONFIG_SYSTEM GIT_DIR GIT_INDEX_FILE GIT_WORK_TREE
unset PYTHONBREAKPOINT PYTHONHOME PYTHONINSPECT PYTHONOPTIMIZE PYTHONPATH PYTHONSTARTUP PYTHONUSERBASE PYTHONWARNINGS

EXPECTED_SHA=""
DEPLOYMENT_ID=""
REPO_DIR="${OMNIRAG_REPO_DIR:-/home/ubuntu/omnirag}"
BRANCH="demo/agentic"
STATE_ROOT="${AGENTIUM_SAFE_DEPLOY_STATE_DIR:-/srv/agentium-data/deployments}"
DATA_ROOT="${AGENTIUM_DATA_ROOT:-/srv/agentium-data}"
LOCK_PATH="$STATE_ROOT/.agentium-deploy.lock"
EXPECTED_DATA_SOURCE="${AGENTIUM_SAFE_EXPECTED_DATA_SOURCE:-/dev/sdb}"
EXPECTED_SECURE_SOURCE="${AGENTIUM_SAFE_EXPECTED_SECURE_SOURCE:-/dev/sdc}"

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
  E2E_USERNAME=<secret-env> E2E_PASSWORD=<secret-env> \
    run-agentium-safe-canaries.sh --sha <40-hex> --deployment-id <id>

The candidate must already be in phase validation_pending.  This runner keeps
the public maintenance gate closed and leaves agentium-sftp stopped. On
success it writes only the tenant and storage proofs under the deployment
directory. deploy-agentium-safe.sh resume then captures the PostgreSQL/Qdrant
opening proofs, builds validation.json, revalidates it, and reopens publicly.
EOF
}

while [[ $# -gt 0 ]]; do
	case "$1" in
	--sha) EXPECTED_SHA="$2"; shift 2 ;;
	--deployment-id) DEPLOYMENT_ID="$2"; shift 2 ;;
	--repo-dir) REPO_DIR="$2"; shift 2 ;;
	--branch) BRANCH="$2"; shift 2 ;;
	-h | --help) usage; exit 0 ;;
	*) die "Option inconnue: $1" ;;
	esac
done

[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || die "--sha doit être un SHA Git complet"
[[ "$DEPLOYMENT_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{5,95}$ ]] || die "--deployment-id invalide"
[[ "$BRANCH" =~ ^[A-Za-z0-9._/-]+$ && "$BRANCH" != *..* ]] || die "--branch invalide"
[[ "$REPO_DIR" == /* && "$REPO_DIR" != *..* ]] || die "--repo-dir invalide"
assert_python_runtime
[[ "$STATE_ROOT" == "$DATA_ROOT"/* ]] || die "L'état doit rester sur le disque data dédié"
[[ -n "${E2E_USERNAME:-}" ]] || die "E2E_USERNAME doit être injecté par l'environnement"
[[ -n "${E2E_PASSWORD:-}" ]] || die "E2E_PASSWORD doit être injecté par l'environnement"
CANARY_USERNAME="$E2E_USERNAME"
CANARY_PASSWORD="$E2E_PASSWORD"
unset E2E_USERNAME E2E_PASSWORD
readonly CANARY_USERNAME CANARY_PASSWORD
CONTROLLED_CHAT_MARKER="agentium_safe_chat::${DEPLOYMENT_ID}::${EXPECTED_SHA:0:12}"
readonly CONTROLLED_CHAT_MARKER

DEPLOY_DIR="$STATE_ROOT/$DEPLOYMENT_ID"
PROOFS_DIR="$DEPLOY_DIR/proofs"
PHASE_FILE="$DEPLOY_DIR/phase"
MAINTENANCE_HELPER="$DEPLOY_DIR/agentium-maintenance-gate.sh"
STORAGE_HELPER="$DEPLOY_DIR/agentium_storage_attestation.py"
VALIDATION_HELPER="$DEPLOY_DIR/agentium_safe_validation.py"
ENV_BUNDLE_HELPER="$DEPLOY_DIR/agentium_runtime_env_bundle.py"
SFTP_BOUNDARY_HELPER="$DEPLOY_DIR/audit_sftp_deploy_boundary.py"
ENV_BUNDLE_DIR="$DEPLOY_DIR/runtime-env"
ENV_BUNDLE_MANIFEST="$ENV_BUNDLE_DIR/manifest.json"
METADATA_FILE="$DEPLOY_DIR/metadata.tsv"
WORKSPACE_TARGETS="$DEPLOY_DIR/workspace-targets.json"
STORAGE_QUIESCED="$DEPLOY_DIR/storage-quiesced.json"
STORAGE_AFTER="$DEPLOY_DIR/storage-after.json"
STORAGE_COMPARISON="$DEPLOY_DIR/storage-comparison.json"
STORAGE_POST_CANARY="$DEPLOY_DIR/storage-post-canary.json"
STORAGE_CANARY_COMPARISON="$DEPLOY_DIR/storage-canary-comparison.json"
DATABASE_REVISION_FILE="$DEPLOY_DIR/candidate-database-revision"
PLAYWRIGHT_BIN="$REPO_DIR/frontend-ng/node_modules/.bin/playwright"
PLAYWRIGHT_RUNTIME="$PROOFS_DIR/playwright-runtime.json"
VM_PROVENANCE="$REPO_DIR/scripts/agentium_vm_fallback_attestation.py"
ANDRITZ_PROOF_BUILDER="$REPO_DIR/scripts/agentium_andritz_proof.py"
TENANT_PROOF_BUILDER="$REPO_DIR/scripts/agentium_tenant_proof.py"
ENV_FILE="$ENV_BUNDLE_DIR/compose.effective.env"
SENSITIVE_TMP=""
SENSITIVE_LOG_TMP=""
SENSITIVE_DIR_TMP=""

cleanup_sensitive_tmp() {
	[[ -z "$SENSITIVE_TMP" ]] || rm -f -- "$SENSITIVE_TMP"
	[[ -z "$SENSITIVE_LOG_TMP" ]] || rm -f -- "$SENSITIVE_LOG_TMP"
	[[ -z "$SENSITIVE_DIR_TMP" ]] || rm -rf -- "$SENSITIVE_DIR_TMP"
}
trap cleanup_sensitive_tmp EXIT

[[ -d "$DATA_ROOT" && -d "$DEPLOY_DIR" ]] || die "Répertoire de déploiement absent"
[[ "$(stat -c '%d' "$DATA_ROOT")" != "$(stat -c '%d' /)" ]] ||
	die "Le state root n'est pas sur le filesystem data dédié"
[[ ! -L "$DEPLOY_DIR" ]] || die "deployment-dir ne peut pas être un lien symbolique"
[[ -f "$METADATA_FILE" && ! -L "$METADATA_FILE" ]] || die "Métadonnées sûres absentes"
[[ -f "$PHASE_FILE" && "$(<"$PHASE_FILE")" == "validation_pending" ]] ||
	die "Le déploiement n'est pas en phase validation_pending"
[[ -x "$MAINTENANCE_HELPER" && -x "$STORAGE_HELPER" && -x "$VALIDATION_HELPER" && -x "$ENV_BUNDLE_HELPER" && -x "$SFTP_BOUNDARY_HELPER" ]] ||
	die "Helpers figés incomplets dans le répertoire de déploiement"
ENV_MANIFEST_SHA256="$(awk -F '\t' '$1 == "env_manifest_sha256" {print $2; found++} END {exit found == 1 ? 0 : 1}' "$METADATA_FILE")" ||
	die "Digest env-bundle absent ou dupliqué"
METADATA_SHA="$(awk -F '\t' '$1 == "candidate_sha" {print $2; found++} END {exit found == 1 ? 0 : 1}' "$METADATA_FILE")" ||
	die "SHA candidat metadata absent ou dupliqué"
SFTP_SHA="$(awk -F '\t' '$1 == "sftp_release_sha" {print $2; found++} END {exit found == 1 ? 0 : 1}' "$METADATA_FILE")" ||
	die "SHA SFTP Release A absent ou dupliqué"
METADATA_DEPLOYMENT_ID="$(awk -F '\t' '$1 == "deployment_id" {print $2; found++} END {exit found == 1 ? 0 : 1}' "$METADATA_FILE")" ||
	die "deployment-id metadata absent ou dupliqué"
WORKSPACE_TARGETS_SHA256="$(awk -F '\t' '$1 == "workspace_targets_sha256" {print $2; found++} END {exit found == 1 ? 0 : 1}' "$METADATA_FILE")" ||
	die "Digest des cibles workspace absent ou dupliqué"
[[ "$ENV_MANIFEST_SHA256" =~ ^[0-9a-f]{64}$ && "$WORKSPACE_TARGETS_SHA256" =~ ^[0-9a-f]{64}$ && "$SFTP_SHA" =~ ^[0-9a-f]{40}$ && "$SFTP_SHA" != "$EXPECTED_SHA" && "$METADATA_SHA" == "$EXPECTED_SHA" && "$METADATA_DEPLOYMENT_ID" == "$DEPLOYMENT_ID" ]] ||
	die "Identité env-bundle différente du runner"
ENV_HELPER_BLOB="$(git -C "$REPO_DIR" rev-parse "${EXPECTED_SHA}:scripts/agentium_runtime_env_bundle.py" 2>/dev/null || true)"
[[ "$ENV_HELPER_BLOB" =~ ^[0-9a-f]{40}$ && "$(git -C "$REPO_DIR" hash-object "$ENV_BUNDLE_HELPER")" == "$ENV_HELPER_BLOB" ]] ||
	die "Helper env-bundle différent du SHA candidat"
SFTP_HELPER_BLOB="$(git -C "$REPO_DIR" rev-parse "${EXPECTED_SHA}:backend/scripts/audit_sftp_deploy_boundary.py" 2>/dev/null || true)"
SFTP_RELEASE_A_HELPER_BLOB="$(git -C "$REPO_DIR" rev-parse "${SFTP_SHA}:backend/scripts/audit_sftp_deploy_boundary.py" 2>/dev/null || true)"
[[ "$SFTP_HELPER_BLOB" =~ ^[0-9a-f]{40}$ && "$SFTP_RELEASE_A_HELPER_BLOB" == "$SFTP_HELPER_BLOB" && "$(git -C "$REPO_DIR" hash-object "$SFTP_BOUNDARY_HELPER")" == "$SFTP_HELPER_BLOB" ]] ||
	die "Helper SFTP différent du SHA candidat"
"$ENV_BUNDLE_HELPER" verify --bundle-dir "$ENV_BUNDLE_DIR" \
	--sha "$EXPECTED_SHA" --deployment-id "$DEPLOYMENT_ID" \
	--expected-manifest-sha256 "$ENV_MANIFEST_SHA256" >/dev/null ||
	die "Bundle env figé invalide"
[[ -f "$DATABASE_REVISION_FILE" && -f "$STORAGE_QUIESCED" && -f "$STORAGE_AFTER" && -f "$STORAGE_COMPARISON" ]] ||
	die "Preuves de migration ou de stockage absentes"
[[ -x "$PLAYWRIGHT_BIN" ]] || die "Playwright n'est pas installé sur la VM"
[[ -f "$VM_PROVENANCE" && -f "$ANDRITZ_PROOF_BUILDER" && -f "$TENANT_PROOF_BUILDER" && -f "$ENV_FILE" && -f "$ENV_BUNDLE_MANIFEST" ]] ||
	die "Collecteur, builders de preuve ou env runtime absent"
command -v node >/dev/null 2>&1 || die "Node.js est absent de la VM"
[[ "$(node --version)" =~ ^v22\. ]] || die "Les canaris exigent Node.js 22"

[[ ! -L "$LOCK_PATH" && ( ! -e "$LOCK_PATH" || -f "$LOCK_PATH" ) ]] ||
	die "Lock de déploiement symbolique ou non régulier"
exec 9>"$LOCK_PATH"
chmod 0600 "$LOCK_PATH"
[[ "$(stat -c '%a:%u:%h' "$LOCK_PATH")" == "600:$(id -u):1" ]] ||
	die "Lock de déploiement non privé"
flock -n 9 || die "Un autre déploiement Agentium est actif"

mkdir -p "$PROOFS_DIR"
chmod 0700 "$DEPLOY_DIR" "$PROOFS_DIR"
DEPLOY_DIR="$(realpath -e "$DEPLOY_DIR")"
PROOFS_DIR="$(realpath -e "$PROOFS_DIR")"
[[ "$PROOFS_DIR" == "$DEPLOY_DIR/proofs" ]] || die "Le répertoire de preuves s'est échappé"

load_workspace_targets() {
	local serialized
	[[ "$WORKSPACE_TARGETS" == "$DEPLOY_DIR/workspace-targets.json" ]] ||
		die "Chemin des cibles workspace inattendu"
	[[ -f "$WORKSPACE_TARGETS" && ! -L "$WORKSPACE_TARGETS" ]] ||
		die "Cibles workspace privées absentes ou symboliques"
	[[ "$(stat -c '%a:%u:%h' "$WORKSPACE_TARGETS")" == "600:$(id -u):1" ]] ||
		die "Cibles workspace non privées"
	[[ "$(sha256sum "$WORKSPACE_TARGETS" | awk '{print $1}')" == "$WORKSPACE_TARGETS_SHA256" ]] ||
		die "Digest des cibles workspace différent des métadonnées"
	serialized="$(python3 - "$WORKSPACE_TARGETS" "$EXPECTED_SHA" "$DEPLOYMENT_ID" <<'PY'
import json
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected_sha, expected_deployment = sys.argv[2:]
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

uuid_pattern = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
slug_pattern = re.compile(r"[a-z0-9][a-z0-9._-]{0,99}")
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
ids = []
slugs = []
fields = []
for role in ("showcase", "andritz", "sentinel", "octocity"):
    target = targets.get(role)
    if not isinstance(target, dict) or set(target) != {
        "workspace_id",
        "workspace_slug",
        "selector",
    }:
        raise SystemExit(f"workspace target {role} is malformed")
    workspace_id = target.get("workspace_id")
    workspace_slug = target.get("workspace_slug")
    if not isinstance(workspace_id, str) or not uuid_pattern.fullmatch(workspace_id):
        raise SystemExit(f"workspace target {role} id is invalid")
    if not isinstance(workspace_slug, str) or not slug_pattern.fullmatch(workspace_slug):
        raise SystemExit(f"workspace target {role} slug is invalid")
    if target.get("selector") != expected_selectors[role]:
        raise SystemExit(f"workspace target {role} selector differs")
    ids.append(workspace_id)
    slugs.append(workspace_slug)
    fields.extend((workspace_id, workspace_slug))
operator_ids = payload.get("operator_workspace_ids")
if (
    not isinstance(operator_ids, list)
    or operator_ids != sorted(ids)
    or len(set(ids)) != 4
    or len(set(slugs)) != 4
):
    raise SystemExit("workspace target identities are ambiguous")
print("\t".join(fields))
PY
)" || die "Cibles workspace invalides"
	IFS=$'\t' read -r \
		SHOWCASE_WORKSPACE_ID SHOWCASE_WORKSPACE_SLUG \
		ANDRITZ_WORKSPACE_ID ANDRITZ_WORKSPACE_SLUG \
		SENTINEL_WORKSPACE_ID SENTINEL_WORKSPACE_SLUG \
		OCTOCITY_WORKSPACE_ID OCTOCITY_WORKSPACE_SLUG <<<"$serialized"
	unset serialized
	for value in \
		"$SHOWCASE_WORKSPACE_ID" "$SHOWCASE_WORKSPACE_SLUG" \
		"$ANDRITZ_WORKSPACE_ID" "$ANDRITZ_WORKSPACE_SLUG" \
		"$SENTINEL_WORKSPACE_ID" "$SENTINEL_WORKSPACE_SLUG" \
		"$OCTOCITY_WORKSPACE_ID" "$OCTOCITY_WORKSPACE_SLUG"; do
		[[ -n "$value" ]] || die "Projection des cibles workspace incomplète"
	done
	readonly SHOWCASE_WORKSPACE_ID SHOWCASE_WORKSPACE_SLUG
	readonly ANDRITZ_WORKSPACE_ID ANDRITZ_WORKSPACE_SLUG
	readonly SENTINEL_WORKSPACE_ID SENTINEL_WORKSPACE_SLUG
	readonly OCTOCITY_WORKSPACE_ID OCTOCITY_WORKSPACE_SLUG
}

load_workspace_targets

prepare_output_file() {
	local target="$1"
	[[ "$target" == "$PROOFS_DIR"/* ]] || die "Artefact hors du répertoire de preuves"
	[[ ! -L "$target" ]] || die "Artefact de preuve symbolique refusé: ${target##*/}"
	rm -f -- "$target"
}

assert_candidate_checkout() {
	local dirty
	[[ "$(git -C "$REPO_DIR" rev-parse HEAD)" == "$EXPECTED_SHA" ]] || die "HEAD VM différent du candidat"
	[[ "$(git -C "$REPO_DIR" branch --show-current)" == "$BRANCH" ]] || die "Branche VM inattendue"
	[[ "$(git -C "$REPO_DIR" rev-parse "refs/remotes/origin/$BRANCH")" == "$EXPECTED_SHA" ]] ||
		die "origin/$BRANCH local ne pointe pas sur le candidat"
	dirty="$(git -C "$REPO_DIR" status --porcelain=v1 --untracked-files=all)"
	[[ -z "$dirty" ]] || die "Checkout VM sale; les canaris refusent de s'exécuter"
}

assert_closed_runtime() {
	local service celery_beat legacy_state legacy_sftp_state legacy_sftp_enabled
	local listener_8000 listener_7881 listener_livekit_udp state udp_start udp_end public_code canary_code
	[[ "$(OMNIRAG_REPO_DIR="$REPO_DIR" "$MAINTENANCE_HELPER" status)" == "closed" ]] ||
		die "Le gate public doit rester fermé"
	[[ -f /var/lib/agentium/deploy-maintenance ]] || die "Marqueur de maintenance persistant absent"
	public_code="$(curl --noproxy '*' -k -sS -o /dev/null -w '%{http_code}' \
		--resolve agentium.papai.ai:443:127.0.0.1 \
		https://agentium.papai.ai/api/v1/health || true)"
	canary_code="$(curl --noproxy '*' -k -sS -o /dev/null -w '%{http_code}' \
		--resolve agentium.papai.ai:443:127.0.0.2 \
		https://agentium.papai.ai/api/v1/health || true)"
	[[ "$public_code" == "503" && "$canary_code" == "200" ]] ||
		die "Le gate HTTP ne sépare pas la destination canari 127.0.0.2 de la destination publique"
	for service in agentium-sftp agentium-p4-maintenance; do
		state="$(docker ps -a --filter "name=^/${service}$" --format '{{.State}}')"
		[[ "$state" == "created" || "$state" == "exited" ]] ||
			die "$service doit exister et rester arrêté pendant les canaris"
	done
	for service in agentium-backend agentium-frontend agentium-worker-cpu; do
		[[ "$(docker inspect --format '{{.State.Running}}' "$service")" == "true" ]] ||
			die "$service n'est pas actif"
	done
	celery_beat="$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' agentium-worker-cpu | awk -F= '$1 == "CELERY_BEAT" {print $2}')"
	[[ "$celery_beat" == "0" ]] || die "agentium-worker-cpu doit avoir CELERY_BEAT=0"
	legacy_state="$(systemctl show agentium-backend --property ActiveState --value)"
	[[ "$legacy_state" == "inactive" ]] || die "Le backend systemd historique doit être inactif"
	legacy_sftp_state="$(systemctl show agentium-sftp --property ActiveState --value)"
	legacy_sftp_enabled="$(systemctl is-enabled agentium-sftp 2>/dev/null || true)"
	[[ "$legacy_sftp_state" == "inactive" ]] ||
		die "Le service SFTP systemd historique doit être inactif"
	[[ "$legacy_sftp_enabled" == "disabled" ]] ||
		die "Le service SFTP systemd historique doit être désactivé"
	listener_8000="$(ss -H -ltn | awk '$4 ~ /:8000$/ { count++ } END { print count + 0 }')"
	[[ "$listener_8000" == "0" ]] || die "Un listener historique subsiste sur :8000"
	for service in agentium-livekit agentium-livekit-agent; do
		state="$(docker ps -a --filter "name=^/${service}$" --format '{{.State}}')"
		[[ -z "$state" || "$state" == "created" || "$state" == "exited" ]] ||
			die "$service doit être absent ou arrêté"
	done
	listener_7881="$(ss -H -ltn | awk '$4 ~ /:7881$/ { count++ } END { print count + 0 }')"
	[[ "$listener_7881" == "0" ]] || die "Un listener LiveKit subsiste sur :7881"
	# Prefer the stopped container's effective environment: it is the exact
	# contract that was applied by Compose.  The versioned env/default remains
	# the fallback when the optional LiveKit container does not exist.
	udp_start="$(container_env_value agentium-livekit LIVEKIT_RTC_UDP_RANGE_START)"
	udp_end="$(container_env_value agentium-livekit LIVEKIT_RTC_UDP_RANGE_END)"
	udp_start="${udp_start:-$(read_env_value LIVEKIT_RTC_UDP_RANGE_START)}"
	udp_end="${udp_end:-$(read_env_value LIVEKIT_RTC_UDP_RANGE_END)}"
	udp_start="${udp_start:-50000}"
	udp_end="${udp_end:-50100}"
	[[ "$udp_start" =~ ^[0-9]{1,5}$ && "$udp_end" =~ ^[0-9]{1,5}$ ]] ||
		die "La plage UDP LiveKit est invalide"
	(( 10#$udp_start >= 1 && 10#$udp_end <= 65535 && 10#$udp_start <= 10#$udp_end )) ||
		die "La plage UDP LiveKit est hors limites"
	listener_livekit_udp="$(ss -H -lun | awk -v lo="$udp_start" -v hi="$udp_end" '
		{ port = $4; sub(/^.*:/, "", port) }
		port ~ /^[0-9]+$/ && port + 0 >= lo && port + 0 <= hi { count++ }
		END { print count + 0 }
	')"
	[[ "$listener_livekit_udp" == "0" ]] ||
		die "Un listener UDP LiveKit subsiste dans la plage configurée"
}

assert_workspace_junit_identity() {
	local junit="$1"
	python3 - "$junit" "$EXPECTED_SHA" <<'PY'
import sys
from pathlib import Path
from xml.etree import ElementTree

path, expected_sha = Path(sys.argv[1]), sys.argv[2]
root = ElementTree.parse(path).getroot()
executed = [case for case in root.iter("testcase") if case.find("skipped") is None]
if not executed:
    raise SystemExit("workspace JUnit contains no executed testcase")
if any(
    "".join(node.itertext()).strip()
    for node in root.iter()
    if node.tag.rsplit("}", 1)[-1] in {"system-out", "system-err"}
):
    raise SystemExit("workspace JUnit contains retained console output")
for case in executed:
    values = [
        node.attrib.get("value")
        for node in case.findall("./properties/property")
        if node.attrib.get("name") == "commit_sha"
    ]
    if values != [expected_sha]:
        raise SystemExit("workspace JUnit testcase is not exactly SHA-bound")
PY
}

attest_playwright_runtime() {
	local lock="$REPO_DIR/frontend-ng/package-lock.json" installed_lock="$REPO_DIR/frontend-ng/node_modules/.package-lock.json"
	local git_lock_sha work_lock_sha lock_blob expected_test expected_core installed_test installed_core
	local browser browser_real browser_sha browser_version cli_real cli_sha node_version npm_version temporary durable_target
	[[ -f "$lock" && ! -L "$lock" && -f "$installed_lock" && ! -L "$installed_lock" ]] ||
		die "Lockfiles Playwright source/install absents ou symboliques"
	lock_blob="$(git -C "$REPO_DIR" rev-parse "${EXPECTED_SHA}:frontend-ng/package-lock.json")"
	[[ "$lock_blob" =~ ^[0-9a-f]{40}$ ]] || die "package-lock absent du SHA candidat"
	git_lock_sha="$(git -C "$REPO_DIR" show "${EXPECTED_SHA}:frontend-ng/package-lock.json" | sha256sum | awk '{print $1}')"
	work_lock_sha="$(sha256sum "$lock" | awk '{print $1}')"
	[[ "$git_lock_sha" == "$work_lock_sha" ]] || die "package-lock du checkout différent du SHA candidat"
	read -r expected_test expected_core < <(python3 - "$lock" <<'PY'
import json, sys
p = json.load(open(sys.argv[1], encoding="utf-8"))
packages = p.get("packages", {})
print(packages.get("node_modules/@playwright/test", {}).get("version", ""), packages.get("node_modules/playwright-core", {}).get("version", ""))
PY
	)
	installed_test="$(node -p "require('$REPO_DIR/frontend-ng/node_modules/@playwright/test/package.json').version")"
	installed_core="$(node -p "require('$REPO_DIR/frontend-ng/node_modules/playwright-core/package.json').version")"
	[[ -n "$expected_test" && "$expected_test" == "$installed_test" && -n "$expected_core" && "$expected_core" == "$installed_core" ]] ||
		die "Versions Playwright installées différentes du lock candidat"
	browser="$(cd "$REPO_DIR/frontend-ng" && node -e "console.log(require('@playwright/test').chromium.executablePath())")"
	browser_real="$(realpath -e "$browser")"
	[[ -f "$browser_real" && ! -L "$browser_real" ]] || die "Chromium Playwright non canonique"
	[[ $((8#$(stat -c '%a' "$browser_real") & 0022)) -eq 0 ]] || die "Chromium Playwright modifiable par groupe/monde"
	browser_sha="$(sha256sum "$browser_real" | awk '{print $1}')"
	browser_version="$($browser_real --version)"
	cli_real="$(realpath -e "$PLAYWRIGHT_BIN")"
	[[ -f "$cli_real" ]] || die "CLI Playwright non canonique"
	cli_sha="$(sha256sum "$cli_real" | awk '{print $1}')"
	node_version="$(node --version)"
	npm_version="$(npm --version)"
	temporary="$PROOFS_DIR/.playwright-runtime.$$"
	rm -f -- "$temporary"
	python3 - "$temporary" "$EXPECTED_SHA" "$lock_blob" "$git_lock_sha" \
		"$(sha256sum "$installed_lock" | awk '{print $1}')" "$expected_test" "$expected_core" \
		"$node_version" "$npm_version" "$cli_sha" "$browser_sha" "$browser_version" <<'PY'
import json, os, re, sys
from pathlib import Path

path = Path(sys.argv[1])
sha, lock_blob, lock_sha, installed_lock_sha = sys.argv[2:6]
test_version, core_version, node_version, npm_version, cli_sha, browser_sha, browser_version = sys.argv[6:13]
if not all(re.fullmatch(r"[0-9a-f]{64}", value) for value in (lock_sha, installed_lock_sha, cli_sha, browser_sha)):
    raise SystemExit("Playwright runtime digest is invalid")
payload = {
    "schema_version": 1,
    "kind": "agentium_playwright_runtime",
    "result": "passed",
    "candidate_sha": sha,
    "package_lock_git_blob": lock_blob,
    "package_lock_sha256": lock_sha,
    "installed_lock_sha256": installed_lock_sha,
    "playwright_test_version": test_version,
    "playwright_core_version": core_version,
    "node_version": node_version,
    "npm_version": npm_version,
    "playwright_cli_sha256": cli_sha,
    "chromium_executable_sha256": browser_sha,
    "chromium_version": browser_version,
    "paths_serialized": False,
}
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
PY
	durable_target="$PLAYWRIGHT_RUNTIME"
	prepare_output_file "$durable_target"
	mv "$temporary" "$durable_target"
	chmod 0600 "$durable_target"
}

run_sftp_closed_boundary() {
	local name="$1" output="$PROOFS_DIR/$name.json"
	prepare_output_file "$output"
	say "Preuve SFTP fermée et Secure Deposit read-only: $name"
	"$SFTP_BOUNDARY_HELPER" closed-boundary \
		--sha "$EXPECTED_SHA" --sftp-sha "$SFTP_SHA" \
		--deployment-id "$DEPLOYMENT_ID" \
		--expected-secure-source "$EXPECTED_SECURE_SOURCE" --output "$output"
	[[ -s "$output" && ! -L "$output" && "$(stat -c '%a' "$output")" == "600" ]] ||
		die "Preuve SFTP fermée privée absente: $name"
}

run_workspace_suite() {
	local tenant="$1" grep_expression="$2" live_all="$3" force_refresh="$4"
	local junit="$PROOFS_DIR/$tenant.xml" output_dir="$PROOFS_DIR/playwright-$tenant" retained_media log code
	prepare_output_file "$junit"
	[[ ! -L "$output_dir" ]] || die "Output Playwright symbolique refusé"
	log="$(mktemp "$PROOFS_DIR/.playwright-$tenant.XXXXXX.log")"
	SENSITIVE_TMP="$junit"
	SENSITIVE_LOG_TMP="$log"
	SENSITIVE_DIR_TMP="$output_dir"
	say "Canari workspace indépendant: $tenant"
	set +e
	(
		cd "$REPO_DIR/frontend-ng"
		env -u CI -u CI_SERVER_URL -u CI_PROJECT_ID -u CI_PIPELINE_ID -u CI_JOB_ID \
			-u CI_JOB_URL -u CI_COMMIT_SHA -u CI_COMMIT_REF_NAME -u CI_COMMIT_REF_PROTECTED \
			-u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
			NO_PROXY="127.0.0.1,agentium.papai.ai" no_proxy="127.0.0.1,agentium.papai.ai" \
			E2E_BASE_URL="https://agentium.papai.ai" \
			E2E_HOST_RESOLVER_RULES="MAP agentium.papai.ai 127.0.0.2, EXCLUDE localhost" \
			E2E_LIVE_CONTRACT=1 E2E_LIVE_ALL_WORKSPACES="$live_all" \
			E2E_LIVE_FORCE_REFRESH="$force_refresh" E2E_LIVE_NON_ADMIN=0 \
			E2E_EXPECTED_SHA="$EXPECTED_SHA" E2E_SAFE_CONTENT_FREE=1 \
			E2E_SHOWCASE_WORKSPACE_ID="$SHOWCASE_WORKSPACE_ID" E2E_SHOWCASE_WORKSPACE_SLUG="$SHOWCASE_WORKSPACE_SLUG" \
			E2E_ANDRITZ_WORKSPACE_ID="$ANDRITZ_WORKSPACE_ID" E2E_ANDRITZ_WORKSPACE_SLUG="$ANDRITZ_WORKSPACE_SLUG" \
			E2E_SENTINEL_WORKSPACE_ID="$SENTINEL_WORKSPACE_ID" E2E_SENTINEL_WORKSPACE_SLUG="$SENTINEL_WORKSPACE_SLUG" \
			E2E_OCTOCITY_WORKSPACE_ID="$OCTOCITY_WORKSPACE_ID" E2E_OCTOCITY_WORKSPACE_SLUG="$OCTOCITY_WORKSPACE_SLUG" \
			E2E_USERNAME="$CANARY_USERNAME" E2E_PASSWORD="$CANARY_PASSWORD" \
			PLAYWRIGHT_JUNIT_OUTPUT_NAME="$junit" \
			"$PLAYWRIGHT_BIN" test e2e/tests/09-live-workspace-contract.spec.ts \
			--project=chromium --reporter=junit --output="$output_dir" --grep "$grep_expression"
	) >"$log" 2>&1
	code=$?
	set -e
	if [[ "$code" -ne 0 ]]; then
		rm -f -- "$junit" "$log"
		rm -rf -- "$output_dir"
		SENSITIVE_TMP=""
		SENSITIVE_LOG_TMP=""
		SENSITIVE_DIR_TMP=""
		die "Canari workspace $tenant échoué; sortie potentiellement métier supprimée"
	fi
	rm -f -- "$log"
	SENSITIVE_LOG_TMP=""
	[[ -s "$junit" ]] || die "JUnit $tenant absent"
	if ! assert_workspace_junit_identity "$junit"; then
		rm -f -- "$junit"
		rm -rf -- "$output_dir"
		die "JUnit $tenant non borné; artefacts supprimés"
	fi
	retained_media="$(find "$output_dir" -type f \( \
		-iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' -o \
		-iname '*.webp' -o -iname '*.webm' -o -iname '*.mp4' -o \
		-iname '*.zip' \) -print -quit 2>/dev/null || true)"
	if [[ -n "$retained_media" ]]; then
		rm -f -- "$junit"
		rm -rf -- "$output_dir"
		die "Le canari content-free a conservé un média métier; artefacts supprimés"
	fi
	rm -rf -- "$output_dir"
	chmod 0600 "$junit"
	SENSITIVE_TMP=""
	SENSITIVE_DIR_TMP=""
}

run_system360_suite() {
	local junit="$PROOFS_DIR/system360.xml" output_dir="$PROOFS_DIR/playwright-system360"
	local log code retained_media
	prepare_output_file "$junit"
	prepare_output_file "$PROOFS_DIR/showcase.json"
	prepare_output_file "$PROOFS_DIR/showcase-runner.json"
	[[ ! -L "$output_dir" ]] || die "Output Playwright System 360 symbolique refusé"
	log="$(mktemp "$PROOFS_DIR/.system360.XXXXXX.log")"
	SENSITIVE_TMP="$junit"
	SENSITIVE_LOG_TMP="$log"
	SENSITIVE_DIR_TMP="$output_dir"
	say "Canari Showcase System 360 découvert par marqueur"
	set +e
	(
		cd "$REPO_DIR/frontend-ng"
		env -u CI -u CI_SERVER_URL -u CI_PROJECT_ID -u CI_PIPELINE_ID -u CI_JOB_ID \
			-u CI_JOB_URL -u CI_COMMIT_SHA -u CI_COMMIT_REF_NAME -u CI_COMMIT_REF_PROTECTED \
			-u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
			NO_PROXY="127.0.0.1,agentium.papai.ai" no_proxy="127.0.0.1,agentium.papai.ai" \
			E2E_BASE_URL="https://agentium.papai.ai" \
			E2E_HOST_RESOLVER_RULES="MAP agentium.papai.ai 127.0.0.2, EXCLUDE localhost" \
			E2E_LOT6_CANARY=1 E2E_EXPECTED_SHA="$EXPECTED_SHA" E2E_SAFE_CONTENT_FREE=1 \
			E2E_SHOWCASE_WORKSPACE_ID="$SHOWCASE_WORKSPACE_ID" E2E_SHOWCASE_WORKSPACE_SLUG="$SHOWCASE_WORKSPACE_SLUG" \
			E2E_USERNAME="$CANARY_USERNAME" E2E_PASSWORD="$CANARY_PASSWORD" \
			E2E_LOT6_RUNNER_ATTESTATION="$PROOFS_DIR/showcase-runner.json" \
			E2E_LOT6_BEHAVIOR_ATTESTATION="$PROOFS_DIR/showcase.json" \
			E2E_PLAYWRIGHT_RUNTIME_ATTESTATION="$PLAYWRIGHT_RUNTIME" \
			PLAYWRIGHT_JUNIT_OUTPUT_NAME="$junit" \
			"$PLAYWRIGHT_BIN" test e2e/tests/11-system360-canary.spec.ts \
			--project=chromium --reporter=junit --output="$output_dir"
	) >"$log" 2>&1
	code=$?
	set -e
	if [[ "$code" -ne 0 ]]; then
		rm -f -- "$junit" "$log" "$PROOFS_DIR/showcase.json" "$PROOFS_DIR/showcase-runner.json"
		rm -rf -- "$output_dir"
		SENSITIVE_TMP=""; SENSITIVE_LOG_TMP=""; SENSITIVE_DIR_TMP=""
		die "Canari System 360 échoué; logs et médias potentiellement métier supprimés"
	fi
	for path in "$PROOFS_DIR/showcase.json" "$PROOFS_DIR/showcase-runner.json"; do
		[[ -s "$path" ]] || die "Preuve System 360 absente: ${path##*/}"
		chmod 0600 "$path"
	done
	retained_media="$(find "$output_dir" -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.webp' -o -iname '*.webm' -o -iname '*.mp4' -o -iname '*.zip' \) -print -quit 2>/dev/null || true)"
	if [[ -n "$retained_media" ]]; then
		rm -f -- "$junit" "$log" "$PROOFS_DIR/showcase.json" "$PROOFS_DIR/showcase-runner.json"
		rm -rf -- "$output_dir"
		die "Le canari System 360 a conservé un média; preuves supprimées"
	fi
	# The two JSON attestations are content-free and SHA-bound. JUnit, console
	# output and Playwright work products are deliberately not formal evidence.
	rm -f -- "$junit" "$log"
	rm -rf -- "$output_dir"
	SENSITIVE_TMP=""; SENSITIVE_LOG_TMP=""; SENSITIVE_DIR_TMP=""
}

run_binding_audit() {
	local output="$PROOFS_DIR/runtime-bindings.json"
	prepare_output_file "$output"
	say "Audit des bindings persistés de tous les workspaces"
	docker exec -w /app/backend agentium-backend python \
		-m scripts.audit_persisted_system_bindings >"$output"
	python3 -c 'import json,sys; p=json.load(open(sys.argv[1], encoding="utf-8")); assert p.get("result") == "passed" and p.get("workspace_count", 0) >= 3 and p.get("requested_workspace_slugs") == [] and p.get("missing_workspace_slugs") == []' "$output"
	chmod 0600 "$output"
}

write_chat_intent() {
	local state="$PROOFS_DIR/controlled-chat-state.json"
	python3 - "$state" "$EXPECTED_SHA" "$DEPLOYMENT_ID" "$CONTROLLED_CHAT_MARKER" <<'PY'
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

path, sha, deployment_id, marker = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
    json.dump(
        {
            "schema_version": 1,
            "kind": "controlled_chat_delivery",
            "commit_sha": sha,
            "deployment_id": deployment_id,
            "status": "dispatching",
            "attempt_ceiling": 1,
            "input_marker_sha256": hashlib.sha256(marker.encode("utf-8")).hexdigest(),
            "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
        handle,
        indent=2,
        sort_keys=True,
    )
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
os.replace(temporary, path)
directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PY
}

summarize_spl_probe() {
	local raw="$1" summary="$PROOFS_DIR/spl-probe.json"
	local state="$PROOFS_DIR/controlled-chat-state.json"
	python3 - "$raw" "$summary" "$state" "$EXPECTED_SHA" "$DEPLOYMENT_ID" "$CONTROLLED_CHAT_MARKER" "$ANDRITZ_WORKSPACE_SLUG" <<'PY'
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

raw_path, summary_path, state_path = map(Path, sys.argv[1:4])
sha, deployment_id, marker, expected_workspace_slug = sys.argv[4:8]
raw = json.loads(raw_path.read_text(encoding="utf-8"))
target = raw.get("target") if isinstance(raw.get("target"), dict) else {}
summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
artifacts = raw.get("artifacts") if isinstance(raw.get("artifacts"), dict) else {}
chat_runs = artifacts.get("chat_runs") if isinstance(artifacts.get("chat_runs"), dict) else {}
chat = chat_runs.get("auto") if isinstance(chat_runs.get("auto"), dict) else {}
chat_payload = chat.get("payload") if isinstance(chat.get("payload"), dict) else {}
run_id = str(chat_payload.get("run_id") or "")
checks = raw.get("checks") if isinstance(raw.get("checks"), list) else []
required = [row for row in checks if isinstance(row, dict) and row.get("required") is True]
conditions = {
    "spl_required_checks": bool(required) and all(row.get("passed") is True for row in required),
    "spl_no_required_failure": summary.get("failed_required") == 0,
    "controlled_workspace": target.get("workspace_slug") == expected_workspace_slug,
    "single_mode": target.get("modes") == ["auto"],
    "exactly_one_controlled_chat": target.get("run_chat") is True
    and set(chat_runs) == {"auto"}
    and chat.get("status") == 200
    and len(run_id) == 36,
    "no_stream_or_deep_job": target.get("run_stream") is False
    and target.get("create_deep_job") is False,
}
if not all(conditions.values()):
    raise SystemExit("SPL proof is incomplete")
try:
    from uuid import UUID
    if str(UUID(run_id)) != run_id:
        raise ValueError
except ValueError as exc:
    raise SystemExit("SPL run_id is invalid") from exc
now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
marker_sha256 = hashlib.sha256(marker.encode("utf-8")).hexdigest()
safe_summary = {
    "schema_version": 1,
    "kind": "andritz_spl_controlled_probe",
    "commit_sha": sha,
    "deployment_id": deployment_id,
    "outcome": "passed",
    "actual_chat_requests": 1,
    "run_id": run_id,
    "input_marker_sha256": marker_sha256,
    "collected_at": now,
    "checks": {name: {"passed": passed} for name, passed in conditions.items()},
}
completed_state = {
    "schema_version": 1,
    "kind": "controlled_chat_delivery",
    "commit_sha": sha,
    "deployment_id": deployment_id,
    "status": "completed",
    "attempt_ceiling": 1,
    "actual_chat_requests": 1,
    "run_id": run_id,
    "input_marker_sha256": marker_sha256,
    "completed_at": now,
}
for path, value in ((summary_path, safe_summary), (state_path, completed_state)):
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
PY
}

run_spl_probe_once() {
	local summary="$PROOFS_DIR/spl-probe.json" state="$PROOFS_DIR/controlled-chat-state.json"
	local raw log binding code
	if [[ -f "$summary" && -f "$state" ]]; then
		[[ ! -L "$summary" && ! -L "$state" ]] || die "État symbolique du Chat contrôlé refusé"
		python3 -c 'import json,sys,uuid; s=json.load(open(sys.argv[1])); t=json.load(open(sys.argv[2])); sha=sys.argv[3]; dep=sys.argv[4]; run=str(s.get("run_id") or ""); assert str(uuid.UUID(run)) == run; assert s.get("outcome") == "passed" and s.get("actual_chat_requests") == 1 and s.get("commit_sha") == sha and s.get("deployment_id") == dep; assert t.get("status") == "completed" and t.get("actual_chat_requests") == 1 and t.get("run_id") == run and t.get("commit_sha") == sha and t.get("deployment_id") == dep' "$summary" "$state" "$EXPECTED_SHA" "$DEPLOYMENT_ID" || die "État du Chat contrôlé incohérent"
		ok "Chat SPL contrôlé déjà prouvé; aucune redélivrance"
		return
	fi
	[[ ! -e "$summary" && ! -e "$state" ]] ||
		die "État ambigu du Chat contrôlé; redélivrance automatique refusée"
	binding="$(docker port agentium-backend 8000/tcp | awk 'NR == 1 {print}')"
	[[ "$binding" =~ ^127\.0\.0\.1:[0-9]+$ ]] || die "Binding loopback backend inattendu"
	raw="$(mktemp "$PROOFS_DIR/.spl-probe.XXXXXX.json")"
	log="$(mktemp "$PROOFS_DIR/.spl-probe.XXXXXX.log")"
	SENSITIVE_TMP="$raw"
	SENSITIVE_LOG_TMP="$log"
	write_chat_intent
	say "SPL read probe puis exactement un Chat contrôlé"
	set +e
	(
		cd "$REPO_DIR"
		env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
			NO_PROXY=127.0.0.1 no_proxy=127.0.0.1 AGENTIUM_HOST="http://$binding" \
			AGENTIUM_EMAIL="$CANARY_USERNAME" AGENTIUM_PASSWORD="$CANARY_PASSWORD" \
			WORKSPACE_SLUG="$ANDRITZ_WORKSPACE_SLUG" PROBE_MODES=auto PROBE_RUN_CHAT=1 \
			PROBE_RUN_STREAM=0 PROBE_CREATE_DEEP_JOB=0 PROBE_MAX_TOKENS=120 \
			PROBE_CONTENT_QUERY="Analyse les procédures de sécurité SPL. $CONTROLLED_CHAT_MARKER" \
			PROBE_OUTPUT="$raw" python3 scripts/probe_spl_retrieval_scaling.py
	) >"$log" 2>&1
	code=$?
	set -e
	if [[ "$code" -ne 0 || ! -s "$raw" ]]; then
		rm -f -- "$raw" "$log"
		SENSITIVE_TMP=""
		SENSITIVE_LOG_TMP=""
		die "Probe SPL/Chat en échec; état conservé ambigu pour interdire un doublon"
	fi
	if ! summarize_spl_probe "$raw"; then
		rm -f -- "$raw" "$log"
		SENSITIVE_TMP=""
		SENSITIVE_LOG_TMP=""
		die "Résumé SPL invalide; redélivrance du Chat refusée"
	fi
	rm -f -- "$raw" "$log"
	SENSITIVE_TMP=""
	SENSITIVE_LOG_TMP=""
	chmod 0600 "$summary" "$state"
}

run_chat_ledger_audit() {
	local summary="$PROOFS_DIR/spl-probe.json" output="$PROOFS_DIR/chat-ledger.json" run_id
	run_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["run_id"])' "$summary")"
	[[ "$run_id" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] ||
		die "run_id du Chat contrôlé invalide"
	prepare_output_file "$output"
	say "Audit DB content-free du Run et des SkillInvocations du Chat contrôlé"
	docker exec -w /app/backend agentium-backend python \
		-m scripts.audit_safe_chat_run --run-id "$run_id" \
		--workspace-id "$ANDRITZ_WORKSPACE_ID" \
		--deployment-id "$DEPLOYMENT_ID" --sha "$EXPECTED_SHA" >"$output"
	python3 -c 'import json,re,sys; p=json.load(open(sys.argv[1], encoding="utf-8")); a=p.get("provenance_artifact", {}); assert p.get("outcome") == "passed" and p.get("run_id") == sys.argv[2] and p.get("workspace_id") == sys.argv[3] and p.get("invocation_count", 0) > 0 and p.get("artifact_count") == 1; assert a.get("backend") in {"local", "s3"} and re.fullmatch(r"[0-9a-f]{64}", str(a.get("key_sha256", ""))) and re.fullmatch(r"[0-9a-f]{64}", str(a.get("content_sha256", ""))) and isinstance(a.get("size"), int) and a["size"] > 0; forbidden=("query", "response", "answer", "citation", "source"); raw=open(sys.argv[1], encoding="utf-8").read().lower(); assert not any(f"\"{word}\":" in raw for word in forbidden)' "$output" "$run_id" "$ANDRITZ_WORKSPACE_ID"
	chmod 0600 "$output"
}

build_tenant_proofs() {
	local tenant
	prepare_output_file "$PROOFS_DIR/andritz.json"
	python3 "$ANDRITZ_PROOF_BUILDER" --sha "$EXPECTED_SHA" --deployment-dir "$DEPLOY_DIR"
	for tenant in sentinel octocity; do
		prepare_output_file "$PROOFS_DIR/$tenant.json"
		python3 "$TENANT_PROOF_BUILDER" --tenant "$tenant" \
			--sha "$EXPECTED_SHA" --deployment-dir "$DEPLOY_DIR"
	done
	chmod 0600 "$PROOFS_DIR/andritz.json" "$PROOFS_DIR/sentinel.json" "$PROOFS_DIR/octocity.json"
}

read_env_value() {
	local key="$1"
	"$ENV_BUNDLE_HELPER" verify --bundle-dir "$ENV_BUNDLE_DIR" \
		--sha "$EXPECTED_SHA" --deployment-id "$DEPLOYMENT_ID" \
		--expected-manifest-sha256 "$ENV_MANIFEST_SHA256" >/dev/null ||
		die "Bundle env figé invalide avant lecture"
	awk -F= -v key="$key" '$1 == key { sub(/^[^=]*=/, ""); sub(/\r$/, ""); print; exit }' "$ENV_FILE"
}

container_env_value() {
	local container="$1" key="$2"
	docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$container" 2>/dev/null |
		awk -F= -v key="$key" '$1 == key { sub(/^[^=]*=/, ""); print; exit }' || true
}

refresh_storage_proof() {
	local secure_deposit qdrant_env configured object_store owner app_env minio_bucket minio_port application_bucket
	local -a container_args=(
		--container agentium-backend
		--container agentium-worker-cpu
		--container agentium-rabbitmq
	)
	secure_deposit="$(read_env_value AGENTIUM_SECURE_DEPOSIT_PATH)"
	secure_deposit="${secure_deposit:-/home/ubuntu/omnirag/backend/data/secure_deposit}"
	configured="$(read_env_value AGENTIUM_QDRANT_ENV_FILE)"
	[[ "$configured" == "$ENV_BUNDLE_DIR"/* ]] || die "Env Qdrant hors bundle figé"
	qdrant_env="$configured"
	configured="$(read_env_value AGENTIUM_ENV_FILE)"
	[[ "$configured" == "$ENV_BUNDLE_DIR"/* ]] || die "Env applicatif hors bundle figé"
	app_env="$configured"
	minio_bucket="$(read_env_value AGENTIUM_MINIO_BUCKET)"
	minio_bucket="${minio_bucket:-agentium-artifacts}"
	minio_port="$(read_env_value AGENTIUM_MINIO_API_PORT)"
	minio_port="${minio_port:-9000}"
	"$ENV_BUNDLE_HELPER" verify --bundle-dir "$ENV_BUNDLE_DIR" \
		--sha "$EXPECTED_SHA" --deployment-id "$DEPLOYMENT_ID" \
		--expected-manifest-sha256 "$ENV_MANIFEST_SHA256" >/dev/null || die "Bundle env figé invalide avant lecture app"
	application_bucket="$(awk -F= '$1 == "OBJECT_STORE_S3_BUCKET" {sub(/^[^=]*=/, ""); sub(/\r$/, ""); print; exit}' "$app_env")"
	[[ "$application_bucket" == "$minio_bucket" ]] || die "Bucket MinIO différent du runtime S3"
	object_store="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/data/object_store"}}{{.Source}}{{end}}{{end}}' agentium-backend)"
	if docker inspect agentium-p4-maintenance >/dev/null 2>&1; then
		container_args+=(--container agentium-p4-maintenance)
	fi
	[[ -d "$secure_deposit" && -f "$qdrant_env" && "$object_store" == /* && -d "$object_store" ]] ||
		die "Chemins stockage runtime invalides"
	say "Attestation stockage après tous les canaris"
	# Only the content-free storage inventory is privileged: one Secure Deposit
	# entry is intentionally unreadable to the deploy user.  Canary credentials
	# remain shell-local and are never forwarded through sudo.
	sudo -n python3 "$STORAGE_HELPER" snapshot --output "$STORAGE_POST_CANARY" \
		--secure-deposit "$secure_deposit" --data-root "$DATA_ROOT" --qdrant-env "$qdrant_env" \
		--object-store "$object_store" --minio-url "http://127.0.0.1:$minio_port" \
		--minio-bucket "$minio_bucket" --expected-data-source "$EXPECTED_DATA_SOURCE" \
		--expected-secure-deposit-source "$EXPECTED_SECURE_SOURCE" "${container_args[@]}"
	owner="$(id -u):$(id -g)"
	sudo -n chown "$owner" "$STORAGE_POST_CANARY"
	chmod 0600 "$STORAGE_POST_CANARY"
	python3 "$STORAGE_HELPER" compare --allow-object-additions \
		--before "$STORAGE_AFTER" --after "$STORAGE_POST_CANARY" \
		--output "$STORAGE_CANARY_COMPARISON"
	chmod 0600 "$STORAGE_CANARY_COMPARISON"
}

collect_provenance_for_safe_resume() {
	local revision
	revision="$(<"$DATABASE_REVISION_FILE")"
	python3 "$VM_PROVENANCE" --sha "$EXPECTED_SHA" --branch "$BRANCH" \
		--alembic-revision "$revision" --repo-dir "$REPO_DIR" --deployment-dir "$DEPLOY_DIR"
	chmod 0600 "$PROOFS_DIR/provenance.json"
}

assert_candidate_checkout
assert_closed_runtime
attest_playwright_runtime
run_sftp_closed_boundary sftp-closed-before-canaries
run_workspace_suite andritz \
	'Andritz business preview exposes the three-app shell|the three Andritz surfaces survive deep links, history and reload|a forced access-token expiry|business preview redirects|deployed Andritz profile|resolved navigation' \
	0 1
assert_closed_runtime
run_workspace_suite sentinel '^Sentinel workspace keeps its immersive Mission Room shell$' 1 0
assert_closed_runtime
run_workspace_suite octocity '^Octocity workspace keeps its immersive Mission Room shell$' 1 0
assert_closed_runtime
run_system360_suite
assert_closed_runtime
run_binding_audit
run_spl_probe_once
run_chat_ledger_audit
refresh_storage_proof
build_tenant_proofs
assert_closed_runtime
collect_provenance_for_safe_resume
assert_closed_runtime
run_sftp_closed_boundary sftp-closed-after-canaries
assert_closed_runtime

ok "Canaris indépendants SHA-bound terminés; validation finale, gate et SFTP restent fermés"
workspace_csv="$(awk -F '\t' '$1 == "canary_workspace_ids" {print $2; exit}' "$DEPLOY_DIR/metadata.tsv")"
analysis_sha="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["analysis_sha256"])' "$DEPLOY_DIR/workspace-app-backfill-dry-run.json")"
printf 'Étape suivante explicite (non exécutée): scripts/deploy-agentium-safe.sh resume --sha %q --deployment-id %q' "$EXPECTED_SHA" "$DEPLOYMENT_ID"
IFS=',' read -r -a resume_workspace_ids <<<"$workspace_csv"
for workspace_id in "${resume_workspace_ids[@]}"; do printf ' --canary-workspace-id %q' "$workspace_id"; done
printf ' --workspace-app-analysis-sha %q --validation-artifact %q\n' "$analysis_sha" "$DEPLOY_DIR/validation.json"
