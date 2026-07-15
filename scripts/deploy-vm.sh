#!/usr/bin/env bash
# Déploiement VM unique et reproductible pour Agentium / OmniRAG.
#
# Chemin unique : origin/demo/agentic --(git fetch+reset)--> VM --(docker build+up)--> conteneurs.
# Ce script REMPLACE les hotfix manuels (docker cp / scp / édition in-container),
# qui sont la cause racine des dérives "régression réintroduite / amélioration perdue".
#
# À exécuter SUR la VM (le script arrive par git, jamais par scp) :
#   cd /home/ubuntu/omnirag && bash scripts/deploy-vm.sh
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
#   --force            Poursuit même si l'arbre git a des modifications suivies (elles seront écrasées).
#
# Sortie: code 0 si déploiement + audit OK, non-zéro sinon.
set -euo pipefail

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
STATE_DIR="${AGENTIUM_DEPLOY_STATE_DIR:-$HOME/.local/state/agentium/deployments}"

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

	# 2) Arbre propre (hors artefacts gitignored/logs) ?
	local dirty
	dirty="$(git status --porcelain | grep -vE 'uvicorn\.log|\.pyc$' || true)"
	if [[ -z "$dirty" ]]; then
		ok "arbre git propre"
	else
		warn "arbre git modifié (sera écrasé au reset) :"
		printf '%s\n' "$dirty"
		fail=1
	fi

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

	return $fail
}

read_env_value() {
	local key="$1"
	awk -F= -v key="$key" '$1 == key { sub(/^[^=]*=/, ""); print; exit }' "$REPO_DIR/docker/${ENV_FILE#./}"
}

load_compose_env() {
	local env_path="$REPO_DIR/docker/${ENV_FILE#./}"
	[[ -f "$env_path" ]] || die "Env file manquant: $env_path"
	export AGENTIUM_ENV_FILE="$ENV_FILE"
	AGENTIUM_POSTGRES_PASSWORD="$(read_env_value AGENTIUM_POSTGRES_PASSWORD)"
	[[ -n "$AGENTIUM_POSTGRES_PASSWORD" ]] || die "AGENTIUM_POSTGRES_PASSWORD absent de $env_path"
	export AGENTIUM_POSTGRES_PASSWORD
	BACKEND_PORT="${AGENTIUM_BACKEND_HOST_PORT:-$(read_env_value AGENTIUM_BACKEND_HOST_PORT)}"
	FRONTEND_PORT="${AGENTIUM_FRONTEND_HOST_PORT:-$(read_env_value AGENTIUM_FRONTEND_HOST_PORT)}"
	BACKEND_PORT="${BACKEND_PORT:-8001}"
	FRONTEND_PORT="${FRONTEND_PORT:-8081}"
	IMAGE_TAG="${AGENTIUM_IMAGE_TAG:-$(read_env_value AGENTIUM_IMAGE_TAG)}"
	IMAGE_TAG="${IMAGE_TAG:-local}"
	[[ "$BACKEND_PORT" =~ ^[0-9]+$ ]] || die "Port backend invalide: $BACKEND_PORT"
	[[ "$FRONTEND_PORT" =~ ^[0-9]+$ ]] || die "Port frontend invalide: $FRONTEND_PORT"
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
		docker compose --profile tools --env-file "$ENV_FILE" -f "$COMPOSE_FILE" \
			run --rm --no-deps agentium-migrate alembic current |
			awk '/\(head\)/ { print $1 }' | sort -u
	)"
	image_heads="$(
		docker compose --profile tools --env-file "$ENV_FILE" -f "$COMPOSE_FILE" \
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
		code="$(curl -fsS -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || true)"
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
	local format target previous kind svc image_id image_ref rollback_ref tagged_id
	[[ -f "$state_file" ]] || die "État de rollback introuvable: $state_file"
	format="$(awk -F '\t' '$1 == "format" { print $2 }' "$state_file")"
	target="$(awk -F '\t' '$1 == "target_sha" { print $2 }' "$state_file")"
	previous="$(awk -F '\t' '$1 == "previous_sha" { print $2 }' "$state_file")"
	[[ "$format" == "1" ]] || die "Format d'état de rollback invalide"
	validate_full_sha "$target" "target_sha"
	validate_full_sha "$previous" "previous_sha"
	[[ -z "$expected_target" || "$target" == "$expected_target" ]] ||
		die "État de rollback associé à un autre SHA candidat"
	[[ -z "$expected_previous" || "$previous" == "$expected_previous" ]] ||
		die "État de rollback associé à un autre SHA précédent"

	declare -A seen_services=()
	while IFS=$'\t' read -r kind svc image_id image_ref rollback_ref; do
		[[ "$kind" == "service" ]] || continue
		case "$svc" in
		agentium-backend | agentium-frontend | agentium-worker-cpu) ;;
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

	if [[ "$require_selected" -eq 1 ]]; then
		for svc in "${SELECTED_SERVICES[@]}"; do
			[[ -n "${seen_services[$svc]:-}" ]] || die "État de rollback incomplet pour $svc"
		done
	fi
}

record_rollback_state() {
	local target_sha="$1" previous_sha="$2"
	local state_file="$STATE_DIR/${target_sha}.tsv" tmp_file
	local svc image_id image_ref image_revision rollback_ref tagged_id
	mkdir -p "$STATE_DIR"
	chmod 0700 "$STATE_DIR"
	if [[ -e "$state_file" ]]; then
		validate_rollback_state "$state_file" "$target_sha" "" 1
		warn "État et tags de rollback existants validés sans écrasement: $state_file"
		ROLLBACK_STATE_PATH="$state_file"
		return 0
	fi

	tmp_file="$(mktemp "$STATE_DIR/.${target_sha}.XXXXXX")"
	chmod 0600 "$tmp_file"
	{
		printf 'format\t1\n'
		printf 'target_sha\t%s\n' "$target_sha"
		printf 'previous_sha\t%s\n' "$previous_sha"
		for svc in "${SELECTED_SERVICES[@]}"; do
			docker inspect "$svc" >/dev/null 2>&1 || die "Impossible de capturer l'image précédente de $svc"
			image_id="$(docker inspect --format '{{.Image}}' "$svc")"
			image_ref="$(docker inspect --format '{{.Config.Image}}' "$svc")"
			[[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || die "ID d'image invalide pour $svc"
			[[ -n "$image_ref" ]] || die "Référence d'image absente pour $svc"
			image_revision="$(
				docker image inspect \
					--format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' \
					"$image_id" 2>/dev/null || true
			)"
			[[ "$image_revision" == "$previous_sha" ]] ||
				die "$svc : image active non alignée sur le SHA précédent $previous_sha"
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
		done
	} >"$tmp_file"

	# Hard-link atomique : une relance ne peut jamais écraser la première base
	# de rollback associée au SHA candidat.
	if ln "$tmp_file" "$state_file" 2>/dev/null; then
		rm -f "$tmp_file"
	else
		rm -f "$tmp_file"
		die "État de rollback créé concurremment: $state_file"
	fi
	ROLLBACK_STATE_PATH="$state_file"
	ok "images précédentes enregistrées dans $state_file"
}

rollback_from_state() {
	local state_file="$1" previous_sha target_sha
	local kind svc image_id image_ref rollback_ref actual_id dirty
	local current_head runtime_image_id runtime_revision
	validate_rollback_state "$state_file" "" "" 0
	target_sha="$(awk -F '\t' '$1 == "target_sha" { print $2 }' "$state_file")"
	previous_sha="$(awk -F '\t' '$1 == "previous_sha" { print $2 }' "$state_file")"
	git cat-file -e "${previous_sha}^{commit}" || die "Commit précédent absent du dépôt: $previous_sha"

	# Refuse a stale rollback file before any tag, data or checkout mutation.
	# Every service captured by this state must still run the candidate SHA.
	current_head="$(git rev-parse HEAD)"
	[[ "$current_head" == "$target_sha" ]] ||
		die "Checkout courant différent du SHA candidat de l'état de rollback"
	while IFS=$'\t' read -r kind svc image_id image_ref rollback_ref; do
		[[ "$kind" == "service" ]] || continue
		docker inspect "$svc" >/dev/null 2>&1 ||
			die "$svc est introuvable; rollback automatique refusé"
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

	SELECTED_SERVICES=()
	declare -A expected_image_ids=()
	while IFS=$'\t' read -r kind svc image_id image_ref rollback_ref; do
		[[ "$kind" == "service" ]] || continue
		case "$svc" in
		agentium-backend | agentium-frontend | agentium-worker-cpu) ;;
		*) die "Service interdit dans l'état de rollback: $svc" ;;
		esac
		[[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || die "ID d'image invalide pour $svc"
		[[ -n "$image_ref" ]] || die "Référence d'image absente pour $svc"
		docker tag "$rollback_ref" "$image_ref"
		SELECTED_SERVICES+=("$svc")
		expected_image_ids["$svc"]="$image_id"
	done <"$state_file"
	[[ "${#SELECTED_SERVICES[@]}" -gt 0 ]] || die "Aucune image dans l'état de rollback"

	dirty="$(git status --porcelain | grep -vE 'uvicorn\.log|\.pyc$' || true)"
	[[ -z "$dirty" || "$FORCE" -eq 1 ]] || die "Arbre VM modifié; rollback refusé sans --force"
	load_compose_env
	cd "$REPO_DIR/docker"
	docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d \
		--no-build --force-recreate "${SELECTED_SERVICES[@]}"
	cd "$REPO_DIR"
	wait_for_selected_services

	for svc in "${SELECTED_SERVICES[@]}"; do
		actual_id="$(docker inspect --format '{{.Image}}' "$svc")"
		[[ "$actual_id" == "${expected_image_ids[$svc]}" ]] ||
			die "$svc n'utilise pas l'image immuable enregistrée"
		ok "$svc restauré sur ${actual_id:7:12}"
	done
	# Keep the candidate script/check-out available until old images are healthy.
	# A failed Compose/health step can then be replayed with the same state.
	git reset --hard "$previous_sha"
	if drift_audit "$previous_sha" 1; then
		ok "Rollback de $target_sha vers $previous_sha terminé"
	else
		die "Images restaurées mais audit post-rollback en échec"
	fi
}

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
dirty="$(git status --porcelain | grep -vE 'uvicorn\.log|\.pyc$' || true)"
if [[ -n "$dirty" && "$FORCE" -ne 1 ]]; then
	printf '%s\n' "$dirty"
	die "Arbre VM modifié. Commit+push d'abord, ou relance explicite avec --force."
fi

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

# 3) Capturer les images actives avant tout build, puis construire ou vérifier
# le candidat. Le mode en deux temps permet une migration sous quiescence API
# sans exposer le nouveau backend avant que son schéma existe.
load_compose_env
if [[ "$ACTIVATE_ONLY" -eq 1 ]]; then
	ROLLBACK_STATE_PATH="$STATE_DIR/${DEPLOY_SHA}.tsv"
	validate_rollback_state "$ROLLBACK_STATE_PATH" "$DEPLOY_SHA" "$PREVIOUS_SHA" 1
	verify_candidate_images "$DEPLOY_SHA"
else
	record_rollback_state "$DEPLOY_SHA" "$PREVIOUS_SHA"
	cd "$REPO_DIR/docker"
	say "docker compose build $SERVICES"
	docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" build "${SELECTED_SERVICES[@]}"
	cd "$REPO_DIR"
	verify_candidate_images "$DEPLOY_SHA"
	if [[ "$BUILD_ONLY" -eq 1 ]]; then
		ok "Candidat $DEPLOY_SHA construit sans activation; rollback: $ROLLBACK_STATE_PATH"
		exit 0
	fi
fi

# A normal one-shot deploy also fails closed when a migration is pending. Lot 4
# intentionally reaches this gate only on --activate-only, after 057 was run
# while the previous backend was quiesced.
verify_database_at_image_head

cd "$REPO_DIR/docker"
say "docker compose up -d $SERVICES"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --no-build "${SELECTED_SERVICES[@]}"
cd "$REPO_DIR"

# 4) Backend et frontend sélectionnés doivent tous deux devenir sains.
wait_for_selected_services

# 5) Audit local post-déploiement : runtime == SHA épinglé, sans réseau.
say "Audit de dérive post-déploiement…"
if drift_audit "$DEPLOY_SHA"; then
	ok "Déploiement $DEPLOY_SHA terminé; rollback: $ROLLBACK_STATE_PATH"
else
	die "Déploiement activé mais audit en échec; utiliser --rollback-state $ROLLBACK_STATE_PATH"
fi
