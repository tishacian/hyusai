#!/usr/bin/env bash
# Quiesced, retry-safe Lot 6 rollout for the production Agentium VM.
#
# This wrapper never receives credentials on its command line. The one real
# exercise query is read from stdin, kept out of artifacts and passed to the
# rollout CLI over stdin. Database secrets remain in the VM Compose env file.
set -Eeuo pipefail

REPO_DIR="${OMNIRAG_REPO_DIR:-/home/ubuntu/omnirag}"
BRANCH="demo/agentic"
EXPECTED_SHA=""
EXERCISE_QUERY_STDIN=0
STATE_ROOT="${AGENTIUM_DEPLOY_STATE_DIR:-$HOME/.local/state/agentium/deployments}"
COMPOSE_FILE="compose.agentium.yml"
ENV_FILE="./env/agentium.vm.env"
WRITERS_STOPPED=0
MIGRATION_STARTED=0
MIGRATION_VERIFIED=0
PREPARE_ATTEMPTED=0
IMAGE_ACTIVATION_STARTED=0
STAGE="initialization"
TEMP_DEPLOYER=""

say() { printf '%s\n' "==> $*"; }
die() { printf '%s\n' "XX  $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
	case "$1" in
	--repo-dir)
		REPO_DIR="$2"
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
	--exercise-query-stdin)
		EXERCISE_QUERY_STDIN=1
		shift
		;;
	*)
		die "Option inconnue: $1"
		;;
	esac
done

[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || die "--sha doit être un SHA Git complet"
[[ "$BRANCH" =~ ^[A-Za-z0-9._/-]+$ ]] || die "--branch contient des caractères interdits"
[[ "$REPO_DIR" =~ ^/[A-Za-z0-9._/-]+$ ]] || die "--repo-dir doit être un chemin absolu sûr"
[[ "$EXERCISE_QUERY_STDIN" -eq 1 ]] || die "--exercise-query-stdin est obligatoire"

IFS= read -r -d '' EXERCISE_QUERY < <(cat; printf '\0') || true
[[ -n "${EXERCISE_QUERY//[[:space:]]/}" ]] || die "La requête d'exercice reçue sur stdin est vide"
[[ "${#EXERCISE_QUERY}" -le 1000000 ]] || die "La requête d'exercice dépasse 1 000 000 caractères"

mkdir -p "$STATE_ROOT"
chmod 0700 "$STATE_ROOT"
exec 9>"$STATE_ROOT/.lot6-system360.lock"
flock -n 9 || die "Un autre rollout Agentium Lot 6 est déjà actif"

DEPLOY_DIR="$STATE_ROOT/${EXPECTED_SHA}-lot6"
ROLLBACK_STATE="$STATE_ROOT/${EXPECTED_SHA}.tsv"
mkdir -p "$DEPLOY_DIR"
chmod 0700 "$DEPLOY_DIR"

cleanup() {
	[[ -z "$TEMP_DEPLOYER" ]] || rm -f "$TEMP_DEPLOYER"
}

on_error() {
	local code="$1" line="$2"
	local rollback_ok=0
	trap - ERR
	set +e
	printf '%s\n' "XX  Lot 6 interrompu à l'étape '$STAGE' (ligne $line, code $code)." >&2
	printf '%s\n' "XX  État de rollback images: $ROLLBACK_STATE" >&2
	printf '%s\n' "XX  Sauvegarde DB quiescée: $DEPLOY_DIR/postgres-quiesced.dump" >&2
	if [[ "$PREPARE_ATTEMPTED" -eq 1 ]]; then
		printf '%s\n' "XX  Rollback applicatif Lot 6 best-effort…" >&2
		if [[ "$(docker inspect --format '{{.State.Running}}' agentium-backend 2>/dev/null)" == "true" ]]; then
			docker exec -w /app/backend agentium-backend \
				python -m scripts.rollout_system360_canary rollback --apply \
				>"$DEPLOY_DIR/rollout-failure-rollback.json" 2>"$DEPLOY_DIR/rollout-failure-rollback.err"
			rollback_ok=$?
		else
			run_candidate python -m scripts.rollout_system360_canary rollback --apply \
				>"$DEPLOY_DIR/rollout-failure-rollback.json" 2>"$DEPLOY_DIR/rollout-failure-rollback.err"
			rollback_ok=$?
		fi
		if [[ "$rollback_ok" -eq 0 ]]; then
			printf '%s\n' "XX  Projection/axes/Membrane/DAG/flow ont été remis dans l'ordre sûr." >&2
		else
			printf '%s\n' "XX  Rollback applicatif en échec; writers arrêtés pour éviter une exposition partielle." >&2
			docker stop agentium-backend agentium-worker-cpu >/dev/null 2>&1
			WRITERS_STOPPED=1
		fi
	fi
	if [[ "$WRITERS_STOPPED" -eq 1 ]]; then
		if [[ "$IMAGE_ACTIVATION_STARTED" -eq 1 ]]; then
			docker stop agentium-backend agentium-worker-cpu >/dev/null 2>&1
		fi
		if [[ "$IMAGE_ACTIVATION_STARTED" -eq 0 && "$MIGRATION_STARTED" -eq "$MIGRATION_VERIFIED" && "$rollback_ok" -eq 0 ]]; then
			(
				cd "$REPO_DIR/docker"
				docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" start \
					agentium-backend agentium-worker-cpu
			) >/dev/null 2>&1
			if [[ "$(docker inspect --format '{{.State.Running}}' agentium-backend 2>/dev/null)" == "true" \
				&& "$(docker inspect --format '{{.State.Running}}' agentium-worker-cpu 2>/dev/null)" == "true" ]]; then
				WRITERS_STOPPED=0
				printf '%s\n' "XX  Les writers précédents ont été relancés après retour applicatif sûr." >&2
			fi
		fi
		if [[ "$WRITERS_STOPPED" -eq 1 ]]; then
			printf '%s\n' "XX  Les writers restent volontairement arrêtés; aucune restauration DB/image implicite n'a été tentée." >&2
		fi
	fi
	exit "$code"
}
trap cleanup EXIT
trap 'on_error $? $LINENO' ERR

cd "$REPO_DIR" || die "Dépôt introuvable: $REPO_DIR"

read_env_value() {
	local key="$1" path="$REPO_DIR/docker/${ENV_FILE#./}"
	awk -F= -v key="$key" '$1 == key { sub(/^[^=]*=/, ""); sub(/\r$/, ""); print; exit }' "$path"
}

POSTGRES_DB="$(read_env_value AGENTIUM_POSTGRES_DB)"
POSTGRES_USER="$(read_env_value AGENTIUM_POSTGRES_USER)"
IMAGE_TAG="$(read_env_value AGENTIUM_IMAGE_TAG)"
POSTGRES_DB="${POSTGRES_DB:-agentium}"
POSTGRES_USER="${POSTGRES_USER:-agentium}"
IMAGE_TAG="${IMAGE_TAG:-local}"
[[ "$POSTGRES_DB" =~ ^[A-Za-z0-9_.-]+$ ]] || die "Nom de base PostgreSQL invalide"
[[ "$POSTGRES_USER" =~ ^[A-Za-z0-9_.-]+$ ]] || die "Utilisateur PostgreSQL invalide"
[[ "$IMAGE_TAG" =~ ^[A-Za-z0-9_.-]+$ ]] || die "Tag d'image invalide"

current_database_revision() {
	docker exec agentium-pg psql \
		-v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
		-Atqc 'SELECT version_num FROM alembic_version ORDER BY version_num'
}

verify_candidate_images() {
	local ref revision
	for ref in "agentium-backend:$IMAGE_TAG" "agentium-frontend:$IMAGE_TAG" "agentium-worker:$IMAGE_TAG"; do
		revision="$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$ref")"
		[[ "$revision" == "$EXPECTED_SHA" ]] || die "Image candidate $ref non alignée sur $EXPECTED_SHA"
	done
}

verify_backup() {
	local backup="$1"
	local checksum="$backup.sha256" expected actual
	[[ -s "$backup" && -s "$checksum" ]] || return 1
	expected="$(awk 'NR == 1 { print $1 }' "$checksum")"
	actual="$(sha256sum "$backup" | awk '{ print $1 }')"
	[[ "$expected" =~ ^[0-9a-f]{64}$ && "$actual" == "$expected" ]] || return 1
	docker exec -i agentium-pg pg_restore --list <"$backup" >/dev/null
}

create_backup() {
	local label="$1"
	local backup="$DEPLOY_DIR/postgres-${label}.dump"
	local temporary checksum_tmp
	if [[ -e "$backup" || -e "$backup.sha256" ]]; then
		verify_backup "$backup" || die "Sauvegarde existante invalide: $backup"
		say "Sauvegarde existante vérifiée: $backup"
		return
	fi
	temporary="$(mktemp "$DEPLOY_DIR/.postgres-${label}.XXXXXX")"
	checksum_tmp="$temporary.sha256"
	chmod 0600 "$temporary"
	docker exec agentium-pg pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc >"$temporary"
	[[ -s "$temporary" ]] || die "pg_dump a produit une sauvegarde vide"
	docker exec -i agentium-pg pg_restore --list <"$temporary" >/dev/null
	sha256sum "$temporary" | awk '{ print $1 }' >"$checksum_tmp"
	chmod 0600 "$checksum_tmp"
	mv "$temporary" "$backup"
	mv "$checksum_tmp" "$backup.sha256"
	verify_backup "$backup" || die "La sauvegarde atomique n'est pas vérifiable"
	say "Sauvegarde PostgreSQL vérifiée: $backup"
}

run_candidate() {
	(
		cd "$REPO_DIR/docker"
		docker compose --profile tools --env-file "$ENV_FILE" -f "$COMPOSE_FILE" \
			run --rm --no-deps agentium-migrate "$@"
	)
}

run_candidate_report() {
	local name="$1"
	shift
	local target="$DEPLOY_DIR/$name" temporary="$DEPLOY_DIR/.$name.tmp"
	rm -f "$temporary"
	run_candidate "$@" >"$temporary"
	python3 -c 'import json,sys; json.load(open(sys.argv[1], encoding="utf-8"))' "$temporary"
	mv "$temporary" "$target"
	chmod 0600 "$target"
}

run_backend_report() {
	local name="$1"
	shift
	local target="$DEPLOY_DIR/$name" temporary="$DEPLOY_DIR/.$name.tmp"
	rm -f "$temporary"
	docker exec -w /app/backend agentium-backend "$@" >"$temporary"
	python3 -c 'import json,sys; json.load(open(sys.argv[1], encoding="utf-8"))' "$temporary"
	mv "$temporary" "$target"
	chmod 0600 "$target"
}

STAGE="source verification"
git fetch origin "$BRANCH" -q
REMOTE_SHA="$(git rev-parse "origin/$BRANCH")"
[[ "$REMOTE_SHA" == "$EXPECTED_SHA" ]] || die "origin/$BRANCH ne correspond pas au SHA demandé"
git cat-file -e "${EXPECTED_SHA}^{commit}" || die "Commit candidat absent du dépôt"

if [[ -f "$ROLLBACK_STATE" ]]; then
	PREVIOUS_SHA="$(awk -F '\t' '$1 == "previous_sha" { print $2 }' "$ROLLBACK_STATE")"
	PREVIOUS_DB_REVISION="$(awk -F '\t' '$1 == "database_revision" { print $2 }' "$ROLLBACK_STATE")"
else
	PREVIOUS_SHA=""
	for service in agentium-backend agentium-frontend agentium-worker-cpu; do
		image_id="$(docker inspect --format '{{.Image}}' "$service")"
		revision="$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$image_id")"
		if [[ -z "$PREVIOUS_SHA" ]]; then PREVIOUS_SHA="$revision"; fi
		[[ "$revision" == "$PREVIOUS_SHA" ]] || die "Les services actifs ne partagent pas le même SHA précédent"
	done
	PREVIOUS_DB_REVISION="$(current_database_revision)"
fi
[[ "$PREVIOUS_SHA" =~ ^[0-9a-f]{40}$ ]] || die "SHA précédent invalide"
[[ "$PREVIOUS_DB_REVISION" =~ ^[A-Za-z0-9_]+$ ]] || die "Révision DB précédente invalide"

CURRENT_DB_REVISION="$(current_database_revision)"
if [[ ! -f "$ROLLBACK_STATE" || "$CURRENT_DB_REVISION" == "$PREVIOUS_DB_REVISION" ]]; then
	STAGE="candidate build"
	TEMP_DEPLOYER="$(mktemp /tmp/agentium-deploy-vm.XXXXXX)"
	git show "${EXPECTED_SHA}:scripts/deploy-vm.sh" >"$TEMP_DEPLOYER"
	chmod 0700 "$TEMP_DEPLOYER"
	OMNIRAG_REPO_DIR="$REPO_DIR" AGENTIUM_DEPLOY_STATE_DIR="$STATE_ROOT" \
		bash "$TEMP_DEPLOYER" --build-only --branch "$BRANCH" \
		--sha "$EXPECTED_SHA" --previous-sha "$PREVIOUS_SHA"
else
	STAGE="candidate retry verification"
	[[ "$(git rev-parse HEAD)" == "$EXPECTED_SHA" ]] || die "Relance post-migration sur un checkout différent"
	dirty="$(git status --porcelain | grep -vE 'uvicorn\.log|\.pyc$' || true)"
	[[ -z "$dirty" ]] || die "Relance post-migration refusée sur une VM sale"
	verify_candidate_images
	create_backup "pre-quiescence"
fi

STAGE="verified pre-quiescence backup"
create_backup "pre-quiescence"

STAGE="writer quiescence"
(
	cd "$REPO_DIR/docker"
	docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" stop \
		agentium-backend agentium-worker-cpu
)
WRITERS_STOPPED=1
for writer in agentium-backend agentium-worker-cpu; do
	[[ "$(docker inspect --format '{{.State.Running}}' "$writer")" == "false" ]] || die "$writer écrit encore"
done

STAGE="verified quiesced backup"
create_backup "quiesced"

export AGENTIUM_ENV_FILE="$ENV_FILE"
export AGENTIUM_IMAGE_REVISION="$EXPECTED_SHA"

STAGE="candidate migration"
MIGRATION_STARTED=1
run_candidate alembic upgrade head
run_candidate alembic current >"$DEPLOY_DIR/alembic-current.txt"
run_candidate alembic heads >"$DEPLOY_DIR/alembic-heads.txt"
CURRENT_HEADS="$(awk '/\(head\)/ { print $1 }' "$DEPLOY_DIR/alembic-current.txt" | sort -u)"
IMAGE_HEADS="$(awk '/\(head\)/ { print $1 }' "$DEPLOY_DIR/alembic-heads.txt" | sort -u)"
[[ -n "$CURRENT_HEADS" && "$CURRENT_HEADS" == "$IMAGE_HEADS" ]] || die "Migration candidate non alignée sur son head"
MIGRATION_VERIFIED=1

STAGE="canary bootstrap dry-run"
run_candidate_report rollout-bootstrap-dry-run.json \
	python -m scripts.rollout_system360_canary bootstrap

STAGE="canary bootstrap apply"
run_candidate_report rollout-bootstrap-apply.json \
	python -m scripts.rollout_system360_canary bootstrap --apply

STAGE="canary prepare dry-run"
run_candidate_report rollout-prepare-dry-run.json \
	python -m scripts.rollout_system360_canary prepare

STAGE="canary prepare apply"
PREPARE_ATTEMPTED=1
run_candidate_report rollout-prepare-apply.json \
	python -m scripts.rollout_system360_canary prepare --apply
WORKSPACE_ID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["workspace_id"])' "$DEPLOY_DIR/rollout-prepare-apply.json")"
SYSTEM_ID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["system_id"])' "$DEPLOY_DIR/rollout-prepare-apply.json")"
[[ "$WORKSPACE_ID" =~ ^[0-9a-f-]{36}$ && "$SYSTEM_ID" =~ ^[0-9a-f-]{36}$ ]] || die "Découverte structurelle du canari invalide"

STAGE="canary-only variable backfill dry-run"
run_candidate_report variable-backfill-dry-run.json \
	python -m scripts.backfill_flow_v3_variables --cohort showcase \
	--workspace-id "$WORKSPACE_ID" --system-id "$SYSTEM_ID"

STAGE="canary-only variable backfill apply"
run_candidate_report variable-backfill-apply.json \
	python -m scripts.backfill_flow_v3_variables --cohort showcase \
	--workspace-id "$WORKSPACE_ID" --system-id "$SYSTEM_ID" --apply
python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); assert r["summary"]["systems"] == 1 and r["summary"]["ambiguous"] == 0' \
	"$DEPLOY_DIR/variable-backfill-apply.json"

STAGE="candidate activation"
IMAGE_ACTIVATION_STARTED=1
OMNIRAG_REPO_DIR="$REPO_DIR" AGENTIUM_DEPLOY_STATE_DIR="$STATE_ROOT" \
	bash "$REPO_DIR/scripts/deploy-vm.sh" --activate-only --branch "$BRANCH" \
	--sha "$EXPECTED_SHA" --previous-sha "$PREVIOUS_SHA"
WRITERS_STOPPED=0

STAGE="strict flow activation"
run_backend_report rollout-activate-flow.json \
	python -m scripts.rollout_system360_canary activate-flow --apply

STAGE="real strict-flow exercise"
EXERCISE_REPORT="$DEPLOY_DIR/.rollout-exercise.json.tmp"
printf '%s' "$EXERCISE_QUERY" | docker exec -i -w /app/backend agentium-backend \
	python -m scripts.rollout_system360_canary exercise --apply --exercise-query-stdin \
	>"$EXERCISE_REPORT"
python3 -c 'import json,sys; e=json.load(open(sys.argv[1]))["exercise"]; assert e["status"] == "completed" and e["required_skills_observed"] is True and e["grounded_output_verified"] is True and e["canonical_provenance_verified"] is True' \
	"$EXERCISE_REPORT"
mv "$EXERCISE_REPORT" "$DEPLOY_DIR/rollout-exercise.json"
chmod 0600 "$DEPLOY_DIR/rollout-exercise.json"
unset EXERCISE_QUERY

STAGE="Membrane enforce activation"
run_backend_report rollout-activate-membrane.json \
	python -m scripts.rollout_system360_canary activate-membrane --apply

STAGE="axes v4 activation"
run_backend_report rollout-activate-axes.json \
	python -m scripts.rollout_system360_canary activate-axes --apply

STAGE="System 360 projection activation"
run_backend_report rollout-activate-projection.json \
	python -m scripts.rollout_system360_canary activate-projection --apply

STAGE="final rollout verification"
run_backend_report rollout-status.json \
	python -m scripts.rollout_system360_canary status
python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["ready"] is True' \
	"$DEPLOY_DIR/rollout-status.json"

trap - ERR
say "Lot 6 activé et vérifié sur ${EXPECTED_SHA:0:12}; preuves VM: $DEPLOY_DIR"
