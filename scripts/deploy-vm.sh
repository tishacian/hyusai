#!/usr/bin/env bash
# Déploiement VM unique et reproductible pour Agentium / OmniRAG.
#
# Chemin unique : origin/demo/agentic --(git fetch+reset)--> VM --(docker build+up)--> conteneurs.
# Ce script REMPLACE les hotfix manuels (docker cp / scp / édition in-container),
# qui sont la cause racine des dérives "régression réintroduite / amélioration perdue".
#
# Les modes qui changent l'état sont réservés à deploy-agentium-safe.sh, qui
# exécute la copie figée de ce script. Seul --check-only est appelable en direct.
#
# Options :
#   --check-only       N'effectue QUE l'audit local de dérive (aucun fetch/reset/build).
#   --build-only       Capture le rollback et construit le candidat sans l'activer.
#   --activate-only    Active des images déjà construites et vérifiées, sans rebuild.
#   --no-frontend      Ne rebuild pas agentium-frontend (backend + worker seulement).
#   --services "a b"   Liste explicite de services à rebuild (défaut: backend frontend worker-cpu).
#   --branch <name>    Branche cible (défaut: demo/agentic).
#   --sha <sha>        SHA Git complet attendu (obligatoire pour un déploiement).
#   --previous-sha <sha> SHA complet déployé avant bootstrap (utile au premier rollout).
#   --rollback-state <path> Restaure les images/check-out enregistrés avant un déploiement.
#   --defer-auxiliary-start Ne démarre pas P4; l'orchestrateur sûr le libère après canaris.
#   --force            Option interne de reprise orchestrée; jamais un chemin opérateur direct.
#
# Sortie: code 0 si déploiement + audit OK, non-zéro sinon.
set -euo pipefail
IFS=$' \t\n'
COMPOSE_CLEAN_PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin"
export PATH="$COMPOSE_CLEAN_PATH"
export PYTHONDONTWRITEBYTECODE=1
unset BASH_ENV CDPATH COMPOSE_FILE COMPOSE_PATH_SEPARATOR COMPOSE_PROJECT_NAME COMPOSE_PROFILES
unset DOCKER_CERT_PATH DOCKER_CONTEXT DOCKER_TLS_VERIFY GIT_CONFIG_COUNT GIT_CONFIG_GLOBAL GIT_CONFIG_SYSTEM GIT_DIR GIT_INDEX_FILE GIT_WORK_TREE
unset PYTHONBREAKPOINT PYTHONHOME PYTHONINSPECT PYTHONOPTIMIZE PYTHONPATH PYTHONSTARTUP PYTHONUSERBASE PYTHONWARNINGS
export DOCKER_HOST=unix:///var/run/docker.sock

REPO_DIR="${OMNIRAG_REPO_DIR:-/home/ubuntu/omnirag}"
BRANCH="demo/agentic"
COMPOSE_FILE="compose.agentium.yml"
ENV_FILE="./env/agentium.vm.env"
SERVICES="agentium-backend agentium-frontend agentium-worker-cpu"
CHECK_ONLY=0
BUILD_ONLY=0
ACTIVATE_ONLY=0
FORCE=0
EXPECTED_SHA=""
PREVIOUS_SHA=""
ROLLBACK_STATE=""
DEFER_AUXILIARY_START=0
STATE_DIR="${AGENTIUM_DEPLOY_STATE_DIR:-$HOME/.local/state/agentium/deployments}"
SAFE_ORCHESTRATED="${AGENTIUM_SAFE_DEPLOY_ORCHESTRATED:-0}"
SAFE_DEPLOYMENT_DIR="${AGENTIUM_SAFE_DEPLOYMENT_DIR:-}"
SAFE_QDRANT_OVERRIDE_FILE="${AGENTIUM_SAFE_QDRANT_OVERRIDE_FILE:-}"
SAFE_CANDIDATE_IMAGE_OVERRIDE_FILE="${AGENTIUM_SAFE_CANDIDATE_IMAGE_OVERRIDE_FILE:-}"
SAFE_ROLLBACK_IMAGE_OVERRIDE_FILE="${AGENTIUM_SAFE_ROLLBACK_IMAGE_OVERRIDE_FILE:-}"
SAFE_QDRANT_KEY="${AGENTIUM_QDRANT_EFFECTIVE_API_KEY:-}"
SAFE_CELERY_BEAT="${AGENTIUM_CELERY_BEAT:-}"
SAFE_STARTUP_RECONCILIATION="${AGENTIUM_STARTUP_RECONCILIATION:-}"
SAFE_ENV_BUNDLE_DIR="${AGENTIUM_SAFE_ENV_BUNDLE_DIR:-}"
SAFE_ENV_MANIFEST_SHA256="${AGENTIUM_SAFE_ENV_MANIFEST_SHA256:-}"
SAFE_ENV_BUNDLE_HELPER="${AGENTIUM_SAFE_ENV_BUNDLE_HELPER:-}"
SAFE_CANDIDATE_SHA=""
SAFE_DEPLOYMENT_ID=""
COMPOSE_CLEAN_HOME=""

while [[ $# -gt 0 ]]; do
	case "$1" in
	--check-only)
		CHECK_ONLY=1
		shift
		;;
	--build-only)
		BUILD_ONLY=1
		shift
		;;
	--activate-only)
		ACTIVATE_ONLY=1
		shift
		;;
	--no-frontend)
		SERVICES="agentium-backend agentium-worker-cpu"
		shift
		;;
	--services)
		SERVICES="$2"
		shift 2
		;;
	--branch)
		BRANCH="$2"
		shift 2
		;;
	--sha)
		EXPECTED_SHA="$2"
		shift 2
		;;
	--previous-sha)
		PREVIOUS_SHA="$2"
		shift 2
		;;
	--rollback-state)
		ROLLBACK_STATE="$2"
		shift 2
		;;
	--defer-auxiliary-start)
		DEFER_AUXILIARY_START=1
		shift
		;;
	--force)
		FORCE=1
		shift
		;;
	*)
		echo "Option inconnue: $1" >&2
		exit 2
		;;
	esac
done

declare -a SELECTED_SERVICES=()

if [[ "$CHECK_ONLY" -eq 0 ]]; then
	[[ "$SAFE_ORCHESTRATED" == "1" ]] || {
		echo "Les modes state-changing exigent scripts/deploy-agentium-safe.sh; seul --check-only est exécutable directement." >&2
		exit 2
	}
	[[ "$SAFE_DEPLOYMENT_DIR" == /* && "$SAFE_DEPLOYMENT_DIR" != *..* ]] || {
		echo "AGENTIUM_SAFE_DEPLOYMENT_DIR invalide" >&2
		exit 2
	}
	[[ "$STATE_DIR" == "$SAFE_DEPLOYMENT_DIR/rollback" && -f "$SAFE_DEPLOYMENT_DIR/metadata.tsv" ]] || {
		echo "État de rollback hors du deployment persistant orchestré" >&2
		exit 2
	}
	[[ "$SAFE_ENV_BUNDLE_DIR" == "$SAFE_DEPLOYMENT_DIR/runtime-env" && -d "$SAFE_ENV_BUNDLE_DIR" && ! -L "$SAFE_ENV_BUNDLE_DIR" ]] || {
		echo "Bundle env figé absent du répertoire de déploiement sûr" >&2
		exit 2
	}
	[[ "$SAFE_ENV_BUNDLE_HELPER" == "$SAFE_DEPLOYMENT_DIR/agentium_runtime_env_bundle.py" && -x "$SAFE_ENV_BUNDLE_HELPER" && ! -L "$SAFE_ENV_BUNDLE_HELPER" ]] || {
		echo "Helper env-bundle figé absent" >&2
		exit 2
	}
	[[ "$SAFE_ENV_MANIFEST_SHA256" =~ ^[0-9a-f]{64}$ && "$(awk -F '\t' '$1 == "env_manifest_sha256" {print $2; exit}' "$SAFE_DEPLOYMENT_DIR/metadata.tsv")" == "$SAFE_ENV_MANIFEST_SHA256" ]] || {
		echo "Digest env-bundle absent ou différent des métadonnées" >&2
		exit 2
	}
	SAFE_CANDIDATE_SHA="$(awk -F '\t' '$1 == "candidate_sha" {print $2; exit}' "$SAFE_DEPLOYMENT_DIR/metadata.tsv")"
	[[ "$SAFE_CANDIDATE_SHA" =~ ^[0-9a-f]{40}$ ]] || {
		echo "SHA candidat absent des métadonnées sûres" >&2
		exit 2
	}
	SAFE_DEPLOYMENT_ID="$(awk -F '\t' '$1 == "deployment_id" {print $2; exit}' "$SAFE_DEPLOYMENT_DIR/metadata.tsv")"
	[[ "$SAFE_DEPLOYMENT_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{5,95}$ ]] || {
		echo "deployment-id absent ou invalide dans les métadonnées sûres" >&2
		exit 2
	}
	[[ "$SAFE_QDRANT_OVERRIDE_FILE" == "$SAFE_DEPLOYMENT_DIR"/* && -s "$SAFE_QDRANT_OVERRIDE_FILE" ]] || {
		echo "Override Qdrant figé absent du répertoire de déploiement sûr" >&2
		exit 2
	}
	[[ -z "$SAFE_CANDIDATE_IMAGE_OVERRIDE_FILE" || -z "$SAFE_ROLLBACK_IMAGE_OVERRIDE_FILE" ]] || {
		echo "Overrides OCI candidat et rollback mutuellement exclusifs" >&2
		exit 2
	}
	if [[ "$ACTIVATE_ONLY" -eq 1 ]]; then
		[[ "$SAFE_CANDIDATE_IMAGE_OVERRIDE_FILE" == "$SAFE_DEPLOYMENT_DIR/compose.agentium.candidate-images.yml" &&
			-f "$SAFE_CANDIDATE_IMAGE_OVERRIDE_FILE" && ! -L "$SAFE_CANDIDATE_IMAGE_OVERRIDE_FILE" &&
			"$(stat -c '%a:%u:%h' "$SAFE_CANDIDATE_IMAGE_OVERRIDE_FILE")" == "600:$(id -u):1" ]] || {
			echo "Override OCI candidat privé absent ou non canonique" >&2
			exit 2
		}
	else
		[[ -z "$SAFE_CANDIDATE_IMAGE_OVERRIDE_FILE" ]] || {
			echo "Override OCI candidat interdit hors activation épinglée" >&2
			exit 2
		}
	fi
	if [[ -n "$ROLLBACK_STATE" ]]; then
		[[ -z "$SAFE_ROLLBACK_IMAGE_OVERRIDE_FILE" ||
			"$SAFE_ROLLBACK_IMAGE_OVERRIDE_FILE" == "$SAFE_DEPLOYMENT_DIR/compose.agentium.rollback-images.yml" ]] || {
			echo "Chemin d'override OCI rollback non canonique" >&2
			exit 2
		}
		SAFE_ROLLBACK_IMAGE_OVERRIDE_FILE="$SAFE_DEPLOYMENT_DIR/compose.agentium.rollback-images.yml"
	else
		[[ -z "$SAFE_ROLLBACK_IMAGE_OVERRIDE_FILE" ]] || {
			echo "Override OCI rollback interdit hors restauration épinglée" >&2
			exit 2
		}
	fi
	[[ "${#SAFE_QDRANT_KEY}" -ge 32 ]] || {
		echo "Clé Qdrant effective absente du contexte orchestré" >&2
		exit 2
	}
	[[ -z "$SAFE_CELERY_BEAT" || "$SAFE_CELERY_BEAT" == "0" || "$SAFE_CELERY_BEAT" == "1" ]] || {
		echo "Override transactionnel Celery beat invalide" >&2
		exit 2
	}
	[[ -z "$SAFE_STARTUP_RECONCILIATION" || "$SAFE_STARTUP_RECONCILIATION" == "enabled" || "$SAFE_STARTUP_RECONCILIATION" == "disabled" ]] || {
		echo "Override transactionnel startup reconciliation invalide" >&2
		exit 2
	}
	if [[ -n "$EXPECTED_SHA" ]]; then
		[[ "$(awk -F '\t' '$1 == "candidate_sha" { print $2; exit }' "$SAFE_DEPLOYMENT_DIR/metadata.tsv")" == "$EXPECTED_SHA" ]] || {
			echo "Marqueur d'orchestration lié à un autre SHA" >&2
			exit 2
		}
	fi
	[[ "$(realpath -e "${BASH_SOURCE[0]}")" == "$(realpath -e "$SAFE_DEPLOYMENT_DIR/deploy-vm-candidate.sh")" ]] || {
		echo "Le deployer state-changing doit être la copie candidate figée" >&2
		exit 2
	}
	expected_deployer_blob="$(git -C "$REPO_DIR" rev-parse "${SAFE_CANDIDATE_SHA}:scripts/deploy-vm.sh" 2>/dev/null || true)"
	expected_env_helper_blob="$(git -C "$REPO_DIR" rev-parse "${SAFE_CANDIDATE_SHA}:scripts/agentium_runtime_env_bundle.py" 2>/dev/null || true)"
	[[ "$expected_deployer_blob" =~ ^[0-9a-f]{40}$ && "$(git -C "$REPO_DIR" hash-object "${BASH_SOURCE[0]}")" == "$expected_deployer_blob" ]] || {
		echo "Deployer figé différent du SHA candidat" >&2
		exit 2
	}
	[[ "$expected_env_helper_blob" =~ ^[0-9a-f]{40}$ && "$(git -C "$REPO_DIR" hash-object "$SAFE_ENV_BUNDLE_HELPER")" == "$expected_env_helper_blob" ]] || {
		echo "Helper env-bundle différent du SHA candidat" >&2
		exit 2
	}
	"$SAFE_ENV_BUNDLE_HELPER" verify \
		--bundle-dir "$SAFE_ENV_BUNDLE_DIR" --sha "$SAFE_CANDIDATE_SHA" \
		--deployment-id "$SAFE_DEPLOYMENT_ID" \
		--expected-manifest-sha256 "$SAFE_ENV_MANIFEST_SHA256" >/dev/null || {
		echo "Bundle env figé invalide" >&2
		exit 2
	}
	ENV_FILE="$SAFE_ENV_BUNDLE_DIR/compose.effective.env"
	COMPOSE_CLEAN_HOME="$(getent passwd "$(id -u)" | awk -F: 'NR == 1 {print $6}')"
	[[ "$COMPOSE_CLEAN_HOME" == /* && -d "$COMPOSE_CLEAN_HOME" ]] || {
		echo "HOME effectif du compte de déploiement introuvable" >&2
		exit 2
	}
fi
read -r -a SELECTED_SERVICES <<<"$SERVICES"

c_red=$'\033[31m'
c_grn=$'\033[32m'
c_ylw=$'\033[33m'
c_rst=$'\033[0m'
say() { printf '%s\n' "==> $*"; }
ok() { printf '%s\n' "${c_grn}OK${c_rst}  $*"; }
warn() { printf '%s\n' "${c_ylw}!! ${c_rst} $*"; }
die() {
	printf '%s\n' "${c_red}XX${c_rst}  $*" >&2
	exit 1
}

assert_no_host_python_bytecode() {
	local first
	first="$(find "$REPO_DIR/backend" -path "$REPO_DIR/backend/.venv" -prune -o -type f -name '*.pyc' -print -quit)" || die "Bytecode Python hôte non auditable"
	[[ -z "$first" ]] || die "Bytecode Python hôte interdit hors .venv: $first"
}

assert_local_docker_socket() {
	local resolved
	[[ "$DOCKER_HOST" == unix:///var/run/docker.sock && -S /var/run/docker.sock ]] || die "Socket Docker local requis"
	resolved="$(realpath -e /var/run/docker.sock)"
	[[ "$resolved" == /run/docker.sock || "$resolved" == /var/run/docker.sock ]] || die "Socket Docker redirigé vers un chemin inattendu"
	[[ "$(stat -Lc '%u:%h' /var/run/docker.sock)" == 0:1 ]] || die "Identité du socket Docker inattendue"
}

dc() {
	local -a extra=()
	if [[ "$CHECK_ONLY" -eq 0 ]]; then
		"$SAFE_ENV_BUNDLE_HELPER" verify \
			--bundle-dir "$SAFE_ENV_BUNDLE_DIR" --sha "$SAFE_CANDIDATE_SHA" \
			--deployment-id "$SAFE_DEPLOYMENT_ID" \
			--expected-manifest-sha256 "$SAFE_ENV_MANIFEST_SHA256" >/dev/null ||
			die "Bundle env figé invalide avant Compose"
	fi
	if [[ -n "$SAFE_QDRANT_OVERRIDE_FILE" ]]; then extra+=(-f "$SAFE_QDRANT_OVERRIDE_FILE"); fi
	if [[ -n "$SAFE_CANDIDATE_IMAGE_OVERRIDE_FILE" ]]; then extra+=(-f "$SAFE_CANDIDATE_IMAGE_OVERRIDE_FILE"); fi
	if [[ -n "$SAFE_ROLLBACK_IMAGE_OVERRIDE_FILE" ]]; then extra+=(-f "$SAFE_ROLLBACK_IMAGE_OVERRIDE_FILE"); fi
	(
		export AGENTIUM_QDRANT_EFFECTIVE_API_KEY="$SAFE_QDRANT_KEY"
		export AGENTIUM_COMPOSE_EXEC_HOME="$COMPOSE_CLEAN_HOME"
		export AGENTIUM_COMPOSE_EXEC_PATH="$COMPOSE_CLEAN_PATH"
		[[ -z "$SAFE_CELERY_BEAT" ]] || export AGENTIUM_CELERY_BEAT="$SAFE_CELERY_BEAT"
		[[ -z "$SAFE_STARTUP_RECONCILIATION" ]] || export AGENTIUM_STARTUP_RECONCILIATION="$SAFE_STARTUP_RECONCILIATION"
		/usr/bin/python3 - "$ENV_FILE" "$COMPOSE_FILE" "${extra[@]}" -- "$@" <<'PY'
import os
import sys

separator = sys.argv.index("--")
prefix, command = sys.argv[1:separator], sys.argv[separator + 1:]
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
arguments = ["docker", "compose", "--env-file", prefix[0], "-f", prefix[1], *prefix[2:], *command]
os.execvpe("docker", arguments, environment)
PY
	)
}

[[ "$BUILD_ONLY" -eq 0 || "$ACTIVATE_ONLY" -eq 0 ]] ||
	die "--build-only et --activate-only sont incompatibles"

cd "$REPO_DIR" || die "Dépôt introuvable: $REPO_DIR"

validate_full_sha() {
	[[ "$1" =~ ^[0-9a-f]{40}$ ]] || die "$2 doit être un SHA Git complet en minuscules"
}

service_is_selected() {
	local candidate
	for candidate in "${SELECTED_SERVICES[@]}"; do
		[[ "$candidate" == "$1" ]] && return 0
	done
	return 1
}

p4_maintenance_container_exists() {
	docker inspect agentium-p4-maintenance >/dev/null 2>&1
}

# --- Audit de dérive : manifeste md5 conteneur <-> arbre git (tout backend/app) -------------
drift_audit() {
	local expected_sha="$1"
	local skip_oci="${2:-0}"
	local fail=0

	# 1) Le checkout est-il exactement sur le commit explicitement attendu ?
	# Aucun fetch ici : --check-only reste lecture seule et l'audit post-build
	# ne peut pas être perturbé par un push concurrent.
	local head current_branch
	head="$(git rev-parse HEAD)"
	current_branch="$(git branch --show-current)"
	if [[ "$head" == "$expected_sha" ]]; then
		ok "git HEAD (${head:0:12}) == SHA attendu"
	else
		warn "git HEAD (${head:0:12}) != SHA attendu (${expected_sha:0:12})"
		fail=1
	fi
	if [[ "$current_branch" == "$BRANCH" ]]; then
		ok "branche active = $BRANCH"
	else
		warn "branche active '${current_branch:-detached}' != '$BRANCH'"
		fail=1
	fi

	# 2) Arbre propre et aucun bytecode hôte exécutable ?
	local dirty
	dirty="$(git status --porcelain --untracked-files=all)"
	if [[ -z "$dirty" ]]; then
		ok "arbre git propre"
	else
		warn "arbre git modifié (sera écrasé au reset) :"
		printf '%s\n' "$dirty"
		fail=1
	fi
	if ! assert_no_host_python_bytecode; then fail=1; fi

	# 3) Provenance OCI des images sélectionnées == commit Git complet ?
	local svc image_id image_revision
	for svc in agentium-backend agentium-frontend agentium-worker-cpu; do
		service_is_selected "$svc" || continue
		if ! docker ps --format '{{.Names}}' | grep -qx "$svc"; then
			warn "$svc non démarré : provenance OCI invérifiable"
			fail=1
			continue
		fi
		image_id="$(docker inspect --format '{{.Image}}' "$svc" 2>/dev/null || true)"
		image_revision="$(
			docker image inspect \
				--format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' \
				"$image_id" 2>/dev/null || true
		)"
		if [[ "$skip_oci" -eq 1 ]]; then
			ok "$svc : provenance OCI contrôlée par l'ID immuable du rollback"
		elif [[ "$image_revision" == "$expected_sha" ]]; then
			ok "$svc : image OCI alignée sur SHA attendu (${expected_sha:0:12})"
		else
			warn "$svc : image OCI revision='${image_revision:-absente}', attendu='$expected_sha'"
			fail=1
		fi
	done
	if [[ "$DEFER_AUXILIARY_START" -eq 0 ]] && service_is_selected "agentium-worker-cpu" && p4_maintenance_container_exists; then
		local maintenance_image_id maintenance_revision
		maintenance_image_id="$(docker inspect --format '{{.Image}}' agentium-p4-maintenance)"
		maintenance_revision="$(docker image inspect \
			--format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' \
			"$maintenance_image_id" 2>/dev/null || true)"
		if [[ "$maintenance_revision" == "$expected_sha" ]]; then
			ok "agentium-p4-maintenance : image OCI alignée sur SHA attendu (${expected_sha:0:12})"
		else
			warn "agentium-p4-maintenance : image OCI revision='${maintenance_revision:-absente}', attendu='$expected_sha'"
			fail=1
		fi
	fi

	# 4) Code des conteneurs == arbre git (manifeste md5 sur tout backend/app) ?
	for svc in agentium-backend agentium-worker-cpu; do
		service_is_selected "$svc" || continue
		if ! docker ps --format '{{.Names}}' | grep -qx "$svc"; then
			warn "$svc non démarré : code conteneur invérifiable"
			fail=1
			continue
		fi
		local host_manifest cont_manifest diff_count
		host_manifest="$(find backend/app -name '*.py' | sort | xargs md5sum 2>/dev/null | awk '{print $1, $2}')"
		cont_manifest="$(docker exec "$svc" sh -c "cd /app && find backend/app -name '*.py' | sort | xargs md5sum 2>/dev/null | awk '{print \$1, \$2}'")"
		diff_count="$(diff <(printf '%s\n' "$host_manifest") <(printf '%s\n' "$cont_manifest") | grep -cE '^[<>]' || true)"
		if [[ "$diff_count" -eq 0 ]]; then
			ok "$svc : code identique à l'arbre git (backend/app/*.py)"
		else
			warn "$svc : $diff_count fichier(s) divergent(s) entre le conteneur et l'arbre git :"
			diff <(printf '%s\n' "$host_manifest") <(printf '%s\n' "$cont_manifest") | grep -E '^[<>]' | head -20
			fail=1
		fi
	done
	if [[ "$DEFER_AUXILIARY_START" -eq 0 ]] && service_is_selected "agentium-worker-cpu" && p4_maintenance_container_exists; then
		if ! docker ps --format '{{.Names}}' | grep -qx agentium-p4-maintenance; then
			warn "agentium-p4-maintenance est arrêté"
			fail=1
		else
			local host_manifest maintenance_manifest maintenance_diff_count
			host_manifest="$(find backend/app -name '*.py' | sort | xargs md5sum 2>/dev/null | awk '{print $1, $2}')"
			maintenance_manifest="$(docker exec agentium-p4-maintenance sh -c "cd /app && find backend/app -name '*.py' | sort | xargs md5sum 2>/dev/null | awk '{print \$1, \$2}'")"
			maintenance_diff_count="$(diff <(printf '%s\n' "$host_manifest") <(printf '%s\n' "$maintenance_manifest") | grep -cE '^[<>]' || true)"
			if [[ "$maintenance_diff_count" -eq 0 ]]; then
				ok "agentium-p4-maintenance : code identique à l'arbre git (backend/app/*.py)"
			else
				warn "agentium-p4-maintenance : $maintenance_diff_count fichier(s) divergent(s)"
				fail=1
			fi
		fi
	fi

	return $fail
}

read_env_value() {
	local key="$1" path="$ENV_FILE"
	if [[ "$CHECK_ONLY" -eq 0 ]]; then
		"$SAFE_ENV_BUNDLE_HELPER" value \
			--bundle-dir "$SAFE_ENV_BUNDLE_DIR" --sha "$SAFE_CANDIDATE_SHA" \
			--deployment-id "$SAFE_DEPLOYMENT_ID" \
			--expected-manifest-sha256 "$SAFE_ENV_MANIFEST_SHA256" \
			--role compose_main --key "$key" ||
			die "Valeur absente ou invalide dans le snapshot Compose figé"
		return
	fi
	if [[ "$path" != /* ]]; then path="$REPO_DIR/docker/${path#./}"; fi
	awk -F= -v key="$key" '$1 == key { sub(/^[^=]*=/, ""); print; exit }' "$path"
}

bundle_role_path() {
	local role="$1"
	"$SAFE_ENV_BUNDLE_HELPER" role-path \
		--bundle-dir "$SAFE_ENV_BUNDLE_DIR" --sha "$SAFE_CANDIDATE_SHA" \
		--deployment-id "$SAFE_DEPLOYMENT_ID" \
		--expected-manifest-sha256 "$SAFE_ENV_MANIFEST_SHA256" \
		--role "$role" || die "Rôle absent ou invalide dans le bundle env figé"
}

load_compose_env() {
	local env_path="$ENV_FILE"
	if [[ "$env_path" != /* ]]; then env_path="$REPO_DIR/docker/${env_path#./}"; fi
	[[ -f "$env_path" ]] || die "Env file manquant: $env_path"
	if [[ "$CHECK_ONLY" -eq 0 ]]; then
		AGENTIUM_ENV_FILE="$(bundle_role_path application)"
	else
		AGENTIUM_ENV_FILE="$(read_env_value AGENTIUM_ENV_FILE)"
	fi
	[[ "$CHECK_ONLY" -eq 1 || "$AGENTIUM_ENV_FILE" == "$SAFE_ENV_BUNDLE_DIR"/* ]] || die "App env hors du bundle figé"
	AGENTIUM_POSTGRES_PASSWORD="$(read_env_value AGENTIUM_POSTGRES_PASSWORD)"
	[[ -n "$AGENTIUM_POSTGRES_PASSWORD" ]] || die "AGENTIUM_POSTGRES_PASSWORD absent de $env_path"
	AGENTIUM_POSTGRES_DB="$(read_env_value AGENTIUM_POSTGRES_DB)"
	AGENTIUM_POSTGRES_USER="$(read_env_value AGENTIUM_POSTGRES_USER)"
	BACKEND_PORT="$(read_env_value AGENTIUM_BACKEND_HOST_PORT)"
	FRONTEND_PORT="$(read_env_value AGENTIUM_FRONTEND_HOST_PORT)"
	IMAGE_TAG="$(read_env_value AGENTIUM_IMAGE_TAG)"
	AGENTIUM_OBJECT_STORE_PATH="$(read_env_value AGENTIUM_OBJECT_STORE_PATH)"
	AGENTIUM_SECURE_DEPOSIT_PATH="$(read_env_value AGENTIUM_SECURE_DEPOSIT_PATH)"
	AGENTIUM_FAISS_PATH="$(read_env_value AGENTIUM_FAISS_PATH)"
	[[ "$AGENTIUM_POSTGRES_DB" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "Nom PostgreSQL invalide dans le snapshot"
	[[ "$AGENTIUM_POSTGRES_USER" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "Utilisateur PostgreSQL invalide dans le snapshot"
	[[ "$BACKEND_PORT" =~ ^[0-9]+$ ]] || die "Port backend invalide: $BACKEND_PORT"
	[[ "$FRONTEND_PORT" =~ ^[0-9]+$ ]] || die "Port frontend invalide: $FRONTEND_PORT"
	(( BACKEND_PORT >= 1 && BACKEND_PORT <= 65535 )) || die "Port backend hors plage"
	(( FRONTEND_PORT >= 1 && FRONTEND_PORT <= 65535 )) || die "Port frontend hors plage"
	[[ "$IMAGE_TAG" =~ ^[A-Za-z0-9_.-]+$ ]] || die "Tag d'image invalide dans le snapshot"
	for storage_path in "$AGENTIUM_OBJECT_STORE_PATH" "$AGENTIUM_SECURE_DEPOSIT_PATH" "$AGENTIUM_FAISS_PATH"; do
		[[ "$storage_path" == /* && "$storage_path" != *..* ]] || die "Chemin de stockage explicite invalide dans le snapshot"
	done
}

validate_compose_storage_contract() {
	local rendered
	[[ "$CHECK_ONLY" -eq 0 ]] || return 0
	rendered="$(cd "$REPO_DIR/docker" && dc --profile tools --profile sftp config --format json)" ||
		die "Rendu Compose candidat impossible"
	if ! python3 - "$AGENTIUM_OBJECT_STORE_PATH" "$AGENTIUM_SECURE_DEPOSIT_PATH" "$AGENTIUM_FAISS_PATH" 3< <(printf '%s\n' "$rendered") <<'PY'
import json
import os
import sys

object_store, secure_deposit, faiss = sys.argv[1:]
try:
    payload = json.load(os.fdopen(3, encoding="utf-8"))
except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise SystemExit("Compose JSON is invalid") from exc
services = payload.get("services")
if not isinstance(services, dict):
    raise SystemExit("Compose services are absent")

expected = {
    "agentium-migrate": {
        "/data/object_store": (object_store, True),
        "/data/secure_deposit": (secure_deposit, True),
        "/data/faiss_db": (faiss, True),
    },
    "agentium-backend": {
        "/data/object_store": (object_store, False),
        "/data/secure_deposit": (secure_deposit, False),
        "/data/faiss_db": (faiss, False),
    },
    "agentium-worker-cpu": {
        "/data/object_store": (object_store, False),
        "/data/secure_deposit": (secure_deposit, True),
        "/data/faiss_db": (faiss, False),
    },
    "agentium-p4-maintenance": {
        "/data/object_store": (object_store, False),
        "/data/secure_deposit": (secure_deposit, True),
        "/data/faiss_db": (faiss, False),
    },
    "agentium-sftp": {
        "/data/secure_deposit": (secure_deposit, False),
    },
}
protected_sources = {object_store, secure_deposit, faiss}
protected_targets = {"/data/object_store", "/data/secure_deposit", "/data/faiss_db"}
observed = {}
for service_name, service in services.items():
    if not isinstance(service, dict):
        raise SystemExit("Compose service is invalid")
    volumes = service.get("volumes", [])
    if not isinstance(volumes, list):
        raise SystemExit("Compose volume list is invalid")
    for volume in volumes:
        if not isinstance(volume, dict):
            raise SystemExit("Compose volume must use canonical structured form")
        source = volume.get("source")
        target = volume.get("target")
        if source not in protected_sources and target not in protected_targets:
            continue
        if service_name not in expected or target not in expected[service_name]:
            raise SystemExit("protected storage is mounted outside the approved service/target")
        key = (service_name, target)
        if key in observed:
            raise SystemExit("protected storage mount is duplicated")
        if volume.get("type") != "bind":
            raise SystemExit("protected storage must remain an explicit bind mount")
        expected_source, expected_read_only = expected[service_name][target]
        read_only = bool(volume.get("read_only", False))
        # The write-barrier override may render a mount read-only where the
        # baseline expects it writable; stricter than expected is acceptable,
        # writable where read-only is expected is not.
        if source != expected_source or (expected_read_only and not read_only):
            raise SystemExit("protected storage source or access mode differs")
        observed[key] = True
required = {
    (service_name, target)
    for service_name, mounts in expected.items()
    for target in mounts
}
if set(observed) != required:
    raise SystemExit("protected storage mount inventory is incomplete")
PY
	then
		die "Le candidat Compose déplace ou ré-expose un stockage protégé"
	fi
	unset rendered
	ok "contrat de stockage Compose figé et vérifié"
}

current_database_revision() {
	local revision
	revision="$(
		docker exec agentium-pg psql \
			-v ON_ERROR_STOP=1 \
			-U "$AGENTIUM_POSTGRES_USER" \
			-d "$AGENTIUM_POSTGRES_DB" \
			-Atqc 'SELECT version_num FROM alembic_version ORDER BY version_num' \
			2>/dev/null
	)" || die "Impossible de lire indépendamment alembic_version dans agentium-pg"
	[[ "$revision" =~ ^[A-Za-z0-9_]+$ ]] ||
		die "Révision DB absente, multiple ou invalide: '${revision:-absente}'"
	printf '%s\n' "$revision"
}

candidate_image_ref() {
	case "$1" in
	agentium-backend) printf 'agentium-backend:%s\n' "$IMAGE_TAG" ;;
	agentium-frontend) printf 'agentium-frontend:%s\n' "$IMAGE_TAG" ;;
	agentium-worker-cpu) printf 'agentium-worker:%s\n' "$IMAGE_TAG" ;;
	*) die "Service sans image candidate vérifiable: $1" ;;
	esac
}

verify_candidate_images() {
	local expected_sha="$1" svc image_ref image_revision
	for svc in "${SELECTED_SERVICES[@]}"; do
		image_ref="$(candidate_image_ref "$svc")"
		image_revision="$(
			docker image inspect \
				--format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' \
				"$image_ref" 2>/dev/null || true
		)"
		[[ "$image_revision" == "$expected_sha" ]] ||
			die "$svc : image candidate '$image_ref' non alignée sur $expected_sha"
		ok "$svc : image candidate vérifiée (${expected_sha:0:12})"
	done
}

verify_database_at_image_head() {
	local current_heads image_heads
	cd "$REPO_DIR/docker"
	current_heads="$(
		dc --profile tools \
			run --rm --no-deps agentium-migrate alembic current |
			awk '/\(head\)/ { print $1 }' | sort -u
	)"
	image_heads="$(
		dc --profile tools \
			run --rm --no-deps agentium-migrate alembic heads |
			awk '/\(head\)/ { print $1 }' | sort -u
	)"
	cd "$REPO_DIR"
	[[ -n "$current_heads" && "$current_heads" == "$image_heads" ]] ||
		die "Schéma DB non aligné sur l'image candidate (current='${current_heads:-absent}', heads='${image_heads:-absent}')"
	ok "schéma DB aligné sur le head candidat: $current_heads"
}

wait_for_http_200() {
	local label="$1" url="$2" attempts="${3:-30}" delay="${4:-4}"
	local code="" i
	say "Attente de $label…"
	for i in $(seq 1 "$attempts"); do
		code="$(curl --noproxy '*' -fsS -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || true)"
		if [[ "$code" == "200" ]]; then
			ok "$label = 200 (après ${i}x)"
			return 0
		fi
		sleep "$delay"
	done
	die "$label pas sain après $((attempts * delay))s (dernier code: ${code:-aucun})"
}

wait_for_selected_services() {
	if service_is_selected "agentium-backend"; then
		wait_for_http_200 "backend /api/v1/health (port $BACKEND_PORT)" \
			"http://localhost:${BACKEND_PORT}/api/v1/health"
	fi
	if service_is_selected "agentium-frontend"; then
		wait_for_http_200 "frontend /healthz (port $FRONTEND_PORT)" \
			"http://localhost:${FRONTEND_PORT}/healthz"
	fi
}

validate_rollback_state() {
	local state_file="$1" expected_target="$2" expected_previous="$3"
	local require_selected="${4:-0}"
	local format target previous database_revision
	local kind svc image_id image_ref rollback_ref tagged_id state revision restart_name restart_max
	[[ -f "$state_file" ]] || die "État de rollback introuvable: $state_file"
	format="$(awk -F '\t' '$1 == "format" { print $2 }' "$state_file")"
	target="$(awk -F '\t' '$1 == "target_sha" { print $2 }' "$state_file")"
	previous="$(awk -F '\t' '$1 == "previous_sha" { print $2 }' "$state_file")"
	database_revision="$(awk -F '\t' '$1 == "database_revision" { print $2 }' "$state_file")"
	[[ "$format" == "2" || "$format" == "3" ]] ||
		die "Format d'état de rollback invalide ou antérieur au garde-fou DB"
	validate_full_sha "$target" "target_sha"
	validate_full_sha "$previous" "previous_sha"
	[[ "$database_revision" =~ ^[A-Za-z0-9_]+$ ]] ||
		die "Révision DB précédente absente ou invalide dans l'état de rollback"
	[[ -z "$expected_target" || "$target" == "$expected_target" ]] ||
		die "État de rollback associé à un autre SHA candidat"
	[[ -z "$expected_previous" || "$previous" == "$expected_previous" ]] ||
		die "État de rollback associé à un autre SHA précédent"

	declare -A seen_services=()
	declare -A seen_states=()
	declare -A seen_restart_policies=()
	while IFS=$'\t' read -r kind svc image_id image_ref rollback_ref; do
		[[ "$kind" == "service" ]] || continue
		case "$svc" in
		agentium-backend | agentium-frontend | agentium-worker-cpu | agentium-sftp | agentium-p4-maintenance) ;;
		*) die "Service interdit dans l'état de rollback: $svc" ;;
		esac
		[[ -z "${seen_services[$svc]:-}" ]] || die "Service dupliqué dans l'état: $svc"
		[[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || die "ID d'image invalide pour $svc"
		[[ -n "$image_ref" ]] || die "Référence active absente pour $svc"
		[[ "$rollback_ref" == "agentium-rollback/${svc}:${target}" ]] ||
			die "Tag de rollback invalide pour $svc"
		tagged_id="$(docker image inspect --format '{{.Id}}' "$rollback_ref" 2>/dev/null || true)"
		[[ "$tagged_id" == "$image_id" ]] || die "Image préservée absente ou altérée pour $svc"
		seen_services["$svc"]=1
	done <"$state_file"
	[[ "${#seen_services[@]}" -gt 0 ]] || die "Aucun service dans l'état de rollback"

	if [[ "$format" == "3" ]]; then
		while IFS=$'\t' read -r kind svc state revision; do
			[[ "$kind" == "container_state" ]] || continue
			case "$svc" in
			agentium-backend | agentium-frontend | agentium-worker-cpu | agentium-sftp | agentium-p4-maintenance) ;;
			*) die "Service interdit dans l'état de rollback: $svc" ;;
			esac
			[[ -z "${seen_states[$svc]:-}" ]] || die "État runtime dupliqué pour $svc"
			[[ "$state" == "running" || "$state" == "stopped" || "$state" == "absent" ]] ||
				die "État runtime invalide pour $svc: $state"
			if [[ "$state" == "absent" ]]; then
				[[ "$revision" == "-" ]] || die "Une révision ne peut pas être attachée à un service absent"
				[[ -z "${seen_services[$svc]:-}" ]] || die "Service $svc à la fois absent et capturé"
			else
				validate_full_sha "$revision" "révision de $svc"
				[[ -n "${seen_services[$svc]:-}" ]] || die "Image de rollback absente pour $svc"
			fi
			seen_states["$svc"]="$state"
		done <"$state_file"
		for svc in "${!seen_services[@]}"; do
			[[ -n "${seen_states[$svc]:-}" ]] || die "État runtime absent pour $svc"
		done
		for svc in agentium-sftp agentium-p4-maintenance; do
			[[ -n "${seen_states[$svc]:-}" ]] || die "État auxiliaire absent pour $svc"
		done
		while IFS=$'\t' read -r kind svc restart_name restart_max; do
			[[ "$kind" == "restart_policy" ]] || continue
			case "$svc" in
			agentium-backend | agentium-frontend | agentium-worker-cpu | agentium-sftp | agentium-p4-maintenance) ;;
			*) die "Service interdit dans la policy de restart: $svc" ;;
			esac
			[[ -z "${seen_restart_policies[$svc]:-}" ]] || die "Policy de restart dupliquée pour $svc"
			if [[ "$restart_name" == "absent" ]]; then
				[[ "$restart_max" == "-" && "${seen_states[$svc]:-}" == "absent" ]] ||
					die "Policy de restart absente incohérente pour $svc"
			else
				case "$restart_name" in no | always | unless-stopped | on-failure) ;; *) die "Policy de restart invalide pour $svc" ;; esac
				[[ "$restart_max" =~ ^[0-9]+$ ]] || die "MaximumRetryCount invalide pour $svc"
				if [[ "$restart_name" != "on-failure" && "$restart_max" != "0" ]]; then
					die "MaximumRetryCount non nul pour une policy $restart_name"
				fi
				[[ "${seen_states[$svc]:-}" == "running" || "${seen_states[$svc]:-}" == "stopped" ]] ||
					die "Policy de restart sans conteneur pour $svc"
			fi
			seen_restart_policies["$svc"]="$restart_name:$restart_max"
		done <"$state_file"
		for svc in "${!seen_states[@]}"; do
			[[ -n "${seen_restart_policies[$svc]:-}" ]] || die "Policy de restart absente pour $svc"
		done
	fi

	if [[ "$require_selected" -eq 1 ]]; then
		for svc in "${SELECTED_SERVICES[@]}"; do
			[[ -n "${seen_services[$svc]:-}" ]] || die "État de rollback incomplet pour $svc"
		done
	fi
}

record_rollback_state() {
	local target_sha="$1" previous_sha="$2"
	local state_file="$STATE_DIR/${target_sha}.tsv" tmp_file
	local svc image_id image_ref image_revision rollback_ref tagged_id runtime_state restart_name restart_max
	local database_revision
	local -a tracked_services=()
	declare -A tracked=()
	mkdir -p "$STATE_DIR"
	chmod 0700 "$STATE_DIR"
	if [[ -e "$state_file" ]]; then
		validate_rollback_state "$state_file" "$target_sha" "" 1
		database_revision="$(awk -F '\t' '$1 == "database_revision" { print $2 }' "$state_file")"
		[[ "$(current_database_revision)" == "$database_revision" ]] ||
			die "État de rollback existant associé à une autre révision DB"
		warn "État et tags de rollback existants validés sans écrasement: $state_file"
		ROLLBACK_STATE_PATH="$state_file"
		return 0
	fi

	database_revision="$(current_database_revision)"
	for svc in "${SELECTED_SERVICES[@]}" agentium-sftp agentium-p4-maintenance; do
		[[ -z "${tracked[$svc]:-}" ]] || continue
		tracked["$svc"]=1
		tracked_services+=("$svc")
	done

	tmp_file="$(mktemp "$STATE_DIR/.${target_sha}.XXXXXX")"
	chmod 0600 "$tmp_file"
	{
		printf 'format\t3\n'
		printf 'target_sha\t%s\n' "$target_sha"
		printf 'previous_sha\t%s\n' "$previous_sha"
		printf 'database_revision\t%s\n' "$database_revision"
		for svc in "${tracked_services[@]}"; do
			if ! docker inspect "$svc" >/dev/null 2>&1; then
				case "$svc" in
				agentium-sftp | agentium-p4-maintenance)
					printf 'container_state\t%s\tabsent\t-\n' "$svc"
					printf 'restart_policy\t%s\tabsent\t-\n' "$svc"
					continue
					;;
				*) die "Impossible de capturer l'image précédente de $svc" ;;
				esac
			fi
			restart_name="$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}' "$svc")"
			restart_max="$(docker inspect --format '{{.HostConfig.RestartPolicy.MaximumRetryCount}}' "$svc")"
			case "$restart_name" in no | always | unless-stopped | on-failure) ;; *) die "Policy de restart illisible pour $svc" ;; esac
			[[ "$restart_max" =~ ^[0-9]+$ ]] || die "MaximumRetryCount illisible pour $svc"
			image_id="$(docker inspect --format '{{.Image}}' "$svc")"
			image_ref="$(docker inspect --format '{{.Config.Image}}' "$svc")"
			[[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || die "ID d'image invalide pour $svc"
			[[ -n "$image_ref" ]] || die "Référence d'image absente pour $svc"
			image_revision="$(
				docker image inspect \
					--format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' \
					"$image_id" 2>/dev/null || true
			)"
			validate_full_sha "$image_revision" "révision OCI de $svc"
			case "$svc" in
			agentium-backend | agentium-frontend | agentium-worker-cpu)
				[[ "$image_revision" == "$previous_sha" ]] ||
					die "$svc : image active non alignée sur le SHA précédent $previous_sha"
				;;
			esac
			rollback_ref="agentium-rollback/${svc}:${target_sha}"
			tagged_id="$(docker image inspect --format '{{.Id}}' "$rollback_ref" 2>/dev/null || true)"
			if [[ -n "$tagged_id" && "$tagged_id" != "$image_id" ]]; then
				die "Tag de rollback existant différent pour $svc; écrasement refusé"
			fi
			if [[ -z "$tagged_id" ]]; then
				docker tag "$image_id" "$rollback_ref"
				tagged_id="$(docker image inspect --format '{{.Id}}' "$rollback_ref")"
			fi
			[[ "$tagged_id" == "$image_id" ]] || die "Échec de préservation de l'image $svc"
			printf 'service\t%s\t%s\t%s\t%s\n' \
				"$svc" "$image_id" "$image_ref" "$rollback_ref"
			if [[ "$(docker inspect --format '{{.State.Running}}' "$svc")" == "true" ]]; then
				runtime_state="running"
			else
				runtime_state="stopped"
			fi
			printf 'container_state\t%s\t%s\t%s\n' "$svc" "$runtime_state" "$image_revision"
			printf 'restart_policy\t%s\t%s\t%s\n' "$svc" "$restart_name" "$restart_max"
		done
	} >"$tmp_file"

	[[ ! -e "$state_file" && ! -L "$state_file" ]] || die "État de rollback créé concurremment: $state_file"
	python3 - "$tmp_file" "$state_file" <<'PY'
import os
import sys
from pathlib import Path

temporary, target = map(Path, sys.argv[1:])
os.chmod(temporary, 0o600)
with temporary.open("rb") as handle:
    os.fsync(handle.fileno())
if os.path.lexists(target):
    raise SystemExit("rollback state target already exists")
try:
    os.link(temporary, target, follow_symlinks=False)
except FileExistsError as exc:
    raise SystemExit("rollback state target appeared concurrently") from exc
os.unlink(temporary)
directory_fd = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PY
	[[ -f "$state_file" && ! -L "$state_file" && "$(stat -c '%a:%u:%h' "$state_file")" == "600:$(id -u):1" ]] ||
		die "État de rollback publié avec une identité de fichier invalide"
	ROLLBACK_STATE_PATH="$state_file"
	ok "images précédentes enregistrées dans $state_file"
}

ensure_rollback_image_override() {
	local state_file="$1"
	[[ "$SAFE_ROLLBACK_IMAGE_OVERRIDE_FILE" == "$SAFE_DEPLOYMENT_DIR/compose.agentium.rollback-images.yml" ]] ||
		die "Cible d'override OCI rollback non canonique"
	python3 -I - "$state_file" "$SAFE_ROLLBACK_IMAGE_OVERRIDE_FILE" <<'PY'
import os
import re
import stat
import sys
from pathlib import Path

state_path, target = map(Path, sys.argv[1:])
uid = os.geteuid()
rows: dict[str, str] = {}
format_version = ""
for raw in state_path.read_text(encoding="utf-8").splitlines():
    fields = raw.split("\t")
    if len(fields) == 2 and fields[0] == "format":
        format_version = fields[1]
    if len(fields) == 5 and fields[0] == "service":
        service, image_id = fields[1], fields[2]
        if service in rows or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
            raise SystemExit("rollback image inventory is malformed")
        rows[service] = image_id
if format_version != "3":
    raise SystemExit("safe rollback requires state format v3")
primary = ("agentium-backend", "agentium-frontend", "agentium-worker-cpu")
if any(service not in rows for service in primary):
    raise SystemExit("rollback primary image inventory is incomplete")
if len({rows[service] for service in primary}) != len(primary):
    raise SystemExit("rollback primary images are aliased")
allowed = {*primary, "agentium-p4-maintenance", "agentium-sftp"}
if not set(rows) <= allowed:
    raise SystemExit("rollback image inventory contains an unknown service")
ordered = [*primary]
for optional in ("agentium-p4-maintenance", "agentium-sftp"):
    if optional in rows:
        ordered.append(optional)
body = "services:\n" + "".join(
    f"  {service}:\n    image: {rows[service]}\n" for service in ordered
)
encoded = body.encode("ascii")

def validate_existing() -> bool:
    try:
        before = target.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise SystemExit("rollback image override is not a regular file")
    if before.st_uid != uid or stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1:
        raise SystemExit("rollback image override identity differs")
    fd = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        opened = os.fstat(fd)
        observed = os.read(fd, len(encoded) + 1)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    linked = target.lstat()
    identity = lambda row: (
        row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns,
        row.st_uid, row.st_nlink, stat.S_IMODE(row.st_mode),
    )
    if identity(before) != identity(opened) or identity(opened) != identity(after) or identity(after) != identity(linked):
        raise SystemExit("rollback image override changed while read")
    if observed != encoded:
        raise SystemExit("rollback image override differs from immutable state")
    return True

if not validate_existing():
    temporary = target.parent / f".{target.name}.{os.getpid()}"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.close(descriptor)
        if target.exists() or target.is_symlink():
            raise SystemExit("rollback image override appeared concurrently")
        os.replace(temporary, target)
        directory = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    validate_existing()
PY
}

rollback_from_state() {
	local state_file="$1" previous_sha target_sha expected_database_revision
	local kind svc image_id image_ref rollback_ref actual_id dirty format desired_state
	local current_head runtime_image_id runtime_revision actual_database_revision
	validate_rollback_state "$state_file" "" "" 0
	target_sha="$(awk -F '\t' '$1 == "target_sha" { print $2 }' "$state_file")"
	previous_sha="$(awk -F '\t' '$1 == "previous_sha" { print $2 }' "$state_file")"
	expected_database_revision="$(awk -F '\t' '$1 == "database_revision" { print $2 }' "$state_file")"
	format="$(awk -F '\t' '$1 == "format" { print $2 }' "$state_file")"
	ensure_rollback_image_override "$state_file"
	git cat-file -e "${previous_sha}^{commit}" || die "Commit précédent absent du dépôt: $previous_sha"

	# Refuse a stale rollback file before any tag, data or checkout mutation.
	# A replay may already be on the previous checkout after a failed Compose
	# step; the immutable state still constrains every runtime image.
	current_head="$(git rev-parse HEAD)"
	[[ "$current_head" == "$target_sha" || "$current_head" == "$previous_sha" ]] ||
		die "Checkout courant différent des SHA candidat/précédent de l'état de rollback"
	while IFS=$'\t' read -r kind svc image_id image_ref rollback_ref; do
		[[ "$kind" == "service" ]] || continue
		if ! docker inspect "$svc" >/dev/null 2>&1; then
			warn "$svc est introuvable; il sera recréé depuis l'image immuable"
			continue
		fi
		runtime_image_id="$(docker inspect --format '{{.Image}}' "$svc")"
		runtime_revision="$(docker image inspect \
			--format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' \
			"$runtime_image_id" 2>/dev/null || true)"
		if [[ "$runtime_revision" != "$target_sha" && "$runtime_image_id" != "$image_id" ]]; then
			die "$svc n'est ni le candidat ni l'image de rollback enregistrée"
		fi
		if ! docker ps --format '{{.Names}}' | grep -qx "$svc"; then
			warn "$svc est arrêté; il sera recréé depuis l'image de rollback"
		fi
	done <"$state_file"

	dirty="$(git status --porcelain --untracked-files=all)"
	[[ -z "$dirty" || "$FORCE" -eq 1 ]] || die "Arbre VM modifié; rollback refusé sans --force"
	assert_no_host_python_bytecode
	[[ -z "$(ss -Hlt 'sport = :8000')" ]] ||
		die "Le backend systemd TCP/8000 doit être arrêté par l'orchestrateur sûr avant rollback"
	# All consumers must be stopped before changing the checkout.  In
	# particular the legacy systemd runtime is handled by the outer safe
	# orchestrator, while these Compose services must not observe half of the
	# previous and half of the candidate source tree.
	for svc in agentium-sftp agentium-p4-maintenance agentium-backend agentium-frontend agentium-worker-cpu; do
		if docker inspect "$svc" >/dev/null 2>&1 && [[ "$(docker inspect --format '{{.State.Running}}' "$svc")" == "true" ]]; then
			if [[ "$(docker inspect --format '{{.State.Paused}}' "$svc")" == "true" ]]; then
				docker unpause "$svc" >/dev/null
			fi
			docker stop --time 45 "$svc" >/dev/null
		fi
	done
	# Compose must come from the previous SHA, never from the candidate whose
	# service topology may have changed. The caller keeps this candidate script
	# in the persistent deployment directory so this transition is replayable.
	if [[ "$current_head" != "$previous_sha" ]]; then
		git reset --hard "$previous_sha"
	fi
	[[ "$(git rev-parse HEAD)" == "$previous_sha" ]] || die "Checkout précédent non restauré"

	# An image rollback cannot safely cross a schema revision. The operator must
	# first downgrade with the candidate image (or restore the verified dump)
	# while every application writer remains stopped.
	load_compose_env
	actual_database_revision="$(current_database_revision)"
	[[ "$actual_database_revision" == "$expected_database_revision" ]] ||
		die "Rollback images refusé: DB=$actual_database_revision, attendue=$expected_database_revision. Downgrade/restaure la DB avec les writers arrêtés avant --rollback-state."

	SELECTED_SERVICES=()
	declare -A expected_image_ids=()
	declare -A expected_image_refs=()
	declare -A rollback_refs=()
	declare -A desired_states=()
	while IFS=$'\t' read -r kind svc image_id image_ref rollback_ref; do
		[[ "$kind" == "service" ]] || continue
		case "$svc" in
		agentium-backend | agentium-frontend | agentium-worker-cpu | agentium-sftp | agentium-p4-maintenance) ;;
		*) die "Service interdit dans l'état de rollback: $svc" ;;
		esac
		[[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || die "ID d'image invalide pour $svc"
		[[ -n "$image_ref" ]] || die "Référence d'image absente pour $svc"
		expected_image_ids["$svc"]="$image_id"
		expected_image_refs["$svc"]="$image_ref"
		rollback_refs["$svc"]="$rollback_ref"
		case "$svc" in
		agentium-backend | agentium-frontend | agentium-worker-cpu) SELECTED_SERVICES+=("$svc") ;;
		esac
	done <"$state_file"
	[[ "${#expected_image_ids[@]}" -gt 0 ]] || die "Aucune image dans l'état de rollback"
	if [[ "$format" == "3" ]]; then
		while IFS=$'\t' read -r kind svc desired_state _revision; do
			[[ "$kind" == "container_state" ]] || continue
			desired_states["$svc"]="$desired_state"
		done <"$state_file"
	else
		for svc in "${!expected_image_ids[@]}"; do desired_states["$svc"]="running"; done
	fi

	cd "$REPO_DIR/docker"
	# Restore shared backend/worker consumers before their primary services so
	# the canonical tags end on backend/worker while each container keeps the
	# exact independently captured image ID.
	for svc in agentium-sftp agentium-p4-maintenance agentium-backend agentium-frontend agentium-worker-cpu; do
		if [[ "$format" == "2" && "$svc" == "agentium-sftp" ]]; then
			continue
		fi
		if [[ "$format" == "2" && "$svc" == "agentium-p4-maintenance" ]]; then
			docker rm -f "$svc" >/dev/null 2>&1 || true
			continue
		fi
		desired_state="${desired_states[$svc]:-absent}"
		if [[ "$desired_state" == "absent" ]]; then
			docker rm -f "$svc" >/dev/null 2>&1 || true
			continue
		fi
		rollback_ref="${rollback_refs[$svc]}"
		image_ref="${expected_image_refs[$svc]}"
		docker tag "$rollback_ref" "$image_ref"
		declare -a profile_args=()
		[[ "$svc" == "agentium-sftp" ]] && profile_args=(--profile sftp)
		if [[ "$svc" == "agentium-sftp" ]]; then
			# The outer safe orchestrator owns the network gate. Recreate SFTP
			# stopped with restart=no so a host reboot cannot bypass volatile
			# iptables rules before that orchestrator releases it explicitly.
			docker rm -f "$svc" >/dev/null 2>&1 || true
			dc "${profile_args[@]}" \
				create --no-build --force-recreate "$svc"
			docker update --restart=no "$svc" >/dev/null
			[[ "$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}' "$svc")" == "no" ]] ||
				die "SFTP rollback n'est pas fail-closed au reboot"
			continue
		fi
		if [[ "$DEFER_AUXILIARY_START" -eq 1 &&
			( "$svc" == "agentium-backend" || "$svc" == "agentium-worker-cpu" || "$svc" == "agentium-p4-maintenance" ) ]]; then
			docker rm -f "$svc" >/dev/null 2>&1 || true
			dc \
				create --no-build --force-recreate "$svc"
			docker update --restart=no "$svc" >/dev/null
			[[ "$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}' "$svc")" == "no" ]] ||
				die "$svc rollback peut redémarrer avant l'attestation"
			continue
		fi
		if [[ "$desired_state" == "running" ]]; then
			dc "${profile_args[@]}" \
				up -d --no-build --force-recreate "$svc"
		else
			docker rm -f "$svc" >/dev/null 2>&1 || true
			dc "${profile_args[@]}" \
				create --no-build --force-recreate "$svc"
		fi
	done
	cd "$REPO_DIR"
	if [[ "$DEFER_AUXILIARY_START" -eq 0 ]]; then wait_for_selected_services; fi

	for svc in "${!expected_image_ids[@]}"; do
		actual_id="$(docker inspect --format '{{.Image}}' "$svc")"
		[[ "$actual_id" == "${expected_image_ids[$svc]}" ]] ||
			die "$svc n'utilise pas l'image immuable enregistrée"
		if [[ "$svc" == "agentium-sftp" ]]; then
			[[ "$(docker inspect --format '{{.State.Running}}' "$svc")" == "false" ]] ||
				die "SFTP rollback devait rester arrêté sous gate"
			[[ "$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}' "$svc")" == "no" ]] ||
				die "SFTP rollback devait conserver restart=no"
		elif [[ "$DEFER_AUXILIARY_START" -eq 1 &&
			( "$svc" == "agentium-backend" || "$svc" == "agentium-worker-cpu" || "$svc" == "agentium-p4-maintenance" ) ]]; then
			[[ "$(docker inspect --format '{{.State.Running}}' "$svc")" == "false" ]] ||
				die "P4 rollback devait rester arrêté sous gate"
		elif [[ "${desired_states[$svc]}" == "running" ]]; then
			[[ "$(docker inspect --format '{{.State.Running}}' "$svc")" == "true" ]] ||
				die "$svc devait être relancé"
		else
			[[ "$(docker inspect --format '{{.State.Running}}' "$svc")" == "false" ]] ||
				die "$svc devait rester arrêté"
		fi
		ok "$svc restauré sur ${actual_id:7:12}"
	done
	if [[ "$format" == "2" ]] && service_is_selected "agentium-worker-cpu"; then
		cd "$REPO_DIR/docker"
		if dc config --services |
			grep -qx agentium-p4-maintenance; then
			dc up -d \
				--no-build --force-recreate agentium-p4-maintenance
		fi
		cd "$REPO_DIR"
	fi
	# Format v3 has already verified auxiliary image IDs and may intentionally
	# restore P4 from an older independent image or keep it stopped.
	[[ "$format" != "3" ]] || DEFER_AUXILIARY_START=1
	if [[ "$DEFER_AUXILIARY_START" -eq 1 ]]; then SELECTED_SERVICES=(); fi
	if drift_audit "$previous_sha" 1; then
		ok "Rollback de $target_sha vers $previous_sha terminé"
	else
		die "Images restaurées mais audit post-rollback en échec"
	fi
}

assert_local_docker_socket

if [[ -n "$ROLLBACK_STATE" ]]; then
	[[ "$CHECK_ONLY" -eq 0 ]] || die "--rollback-state est incompatible avec --check-only"
	[[ "$BUILD_ONLY" -eq 0 && "$ACTIVATE_ONLY" -eq 0 ]] ||
		die "--rollback-state est incompatible avec les modes de rollout par étapes"
	rollback_from_state "$ROLLBACK_STATE"
	exit 0
fi

if [[ "$CHECK_ONLY" -eq 1 ]]; then
	[[ "$BUILD_ONLY" -eq 0 && "$ACTIVATE_ONLY" -eq 0 ]] ||
		die "--check-only est incompatible avec les modes de rollout par étapes"
	EXPECTED_SHA="${EXPECTED_SHA:-$(git rev-parse HEAD)}"
	validate_full_sha "$EXPECTED_SHA" "--sha"
	say "Audit de dérive local (lecture seule) — branche $BRANCH @ ${EXPECTED_SHA:0:12}"
	if drift_audit "$EXPECTED_SHA"; then
		ok "Aucune dérive détectée."
		exit 0
	else
		die "Dérive détectée (voir ci-dessus)."
	fi
fi

# --- Déploiement -----------------------------------------------------------------------------
[[ -n "$EXPECTED_SHA" ]] || die "--sha <SHA complet> est obligatoire pour déployer"
validate_full_sha "$EXPECTED_SHA" "--sha"
if [[ -z "$PREVIOUS_SHA" ]]; then
	PREVIOUS_SHA="$(git rev-parse HEAD)"
fi
validate_full_sha "$PREVIOUS_SHA" "--previous-sha"
ROLLOUT_MODE="deploy"
[[ "$BUILD_ONLY" -eq 1 ]] && ROLLOUT_MODE="build-only"
[[ "$ACTIVATE_ONLY" -eq 1 ]] && ROLLOUT_MODE="activate-only"
say "Déploiement VM ($ROLLOUT_MODE) — branche $BRANCH, SHA ${EXPECTED_SHA:0:12}, services: $SERVICES"

# 1) Garde-fou : ne pas écraser silencieusement des modifs suivies non commitées
dirty="$(git status --porcelain --untracked-files=all)"
if [[ -n "$dirty" && "$FORCE" -ne 1 ]]; then
	printf '%s\n' "$dirty"
	die "Arbre VM modifié. Commit+push d'abord, ou relance explicite avec --force."
fi
assert_no_host_python_bytecode

# 2) Vérifier le SHA distant puis construire exactement ce commit. Il n'y a
# volontairement aucun autre fetch dans le script : un push concurrent ne peut
# ni changer le checkout construit, ni invalider l'audit après activation.
git fetch origin "$BRANCH" -q
REMOTE_SHA="$(git rev-parse "origin/$BRANCH")"
[[ "$REMOTE_SHA" == "$EXPECTED_SHA" ]] ||
	die "origin/$BRANCH vaut $REMOTE_SHA, différent du SHA validé $EXPECTED_SHA"
git cat-file -e "${EXPECTED_SHA}^{commit}" || die "Commit attendu absent: $EXPECTED_SHA"
git reset --hard "$EXPECTED_SHA"
DEPLOY_SHA="$(git rev-parse HEAD)"
[[ "$DEPLOY_SHA" == "$EXPECTED_SHA" ]] || die "Checkout différent du SHA attendu"
export AGENTIUM_IMAGE_REVISION="$DEPLOY_SHA"
ok "checkout épinglé à ${DEPLOY_SHA:0:12}"

# A candidate whose generated product contract drifted is not deployable. This
# is deliberately checked after the immutable checkout and before loading
# runtime secrets or building images.
say "Vérification du contrat de conformité Agentium…"
python3 "$REPO_DIR/scripts/agentium_compliance.py" --check ||
	die "Contrat de conformité Agentium invalide pour $DEPLOY_SHA"
ok "contrat de conformité Agentium cohérent"

# 3) Capturer les images actives avant tout build, puis construire ou vérifier
# le candidat. Le mode en deux temps permet une migration sous quiescence API
# sans exposer le nouveau backend avant que son schéma existe.
load_compose_env
validate_compose_storage_contract
if [[ "$ACTIVATE_ONLY" -eq 1 ]]; then
	ROLLBACK_STATE_PATH="$STATE_DIR/${DEPLOY_SHA}.tsv"
	validate_rollback_state "$ROLLBACK_STATE_PATH" "$DEPLOY_SHA" "$PREVIOUS_SHA" 1
	verify_candidate_images "$DEPLOY_SHA"
else
	record_rollback_state "$DEPLOY_SHA" "$PREVIOUS_SHA"
	cd "$REPO_DIR/docker"
	say "docker compose build $SERVICES"
	# La révision OCI vient du SHA vérifié, via l'option de build dédiée. Elle
	# n'est donc pas une variable d'interpolation Compose héritée du shell.
	dc build --build-arg "AGENTIUM_IMAGE_REVISION=$DEPLOY_SHA" "${SELECTED_SERVICES[@]}"
	cd "$REPO_DIR"
	verify_candidate_images "$DEPLOY_SHA"
	if [[ "$BUILD_ONLY" -eq 1 ]]; then
		ok "Candidat $DEPLOY_SHA construit sans activation; rollback: $ROLLBACK_STATE_PATH"
		exit 0
	fi
fi

# A normal one-shot deploy also fails closed when a migration is pending. Any
# schema-changing rollout reaches this gate only on --activate-only, after the
# candidate migration was run while the previous writers were quiesced.
verify_database_at_image_head

cd "$REPO_DIR/docker"
say "docker compose up -d $SERVICES"
dc up -d --no-build "${SELECTED_SERVICES[@]}"
if [[ "$DEFER_AUXILIARY_START" -eq 0 ]] && service_is_selected "agentium-worker-cpu" && \
	dc config --services |
	grep -qx agentium-p4-maintenance; then
	# This process is safe to create during the additive rollout: its own flag
	# defaults to false. Recreating it with every worker rollout prevents a
	# stale coordinator image from surviving a later deploy.
	dc up -d \
		--no-build --force-recreate agentium-p4-maintenance
fi
cd "$REPO_DIR"

# 4) Backend et frontend sélectionnés doivent tous deux devenir sains.
wait_for_selected_services

# 5) Audit local post-déploiement : runtime == SHA épinglé, sans réseau.
say "Audit de dérive post-déploiement…"
if drift_audit "$DEPLOY_SHA"; then
	ok "Déploiement $DEPLOY_SHA terminé; rollback: $ROLLBACK_STATE_PATH"
else
	die "Déploiement activé mais audit en échec; remettre d'abord la DB à la révision enregistrée avec les writers arrêtés, puis utiliser --rollback-state $ROLLBACK_STATE_PATH"
fi
