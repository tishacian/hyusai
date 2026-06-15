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
#   --check-only       N'effectue QUE l'audit de dérive (aucun fetch/reset/build).
#   --no-frontend      Ne rebuild pas agentium-frontend (backend + worker seulement).
#   --services "a b"   Liste explicite de services à rebuild (défaut: backend frontend worker-cpu).
#   --branch <name>    Branche cible (défaut: demo/agentic).
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
FORCE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check-only) CHECK_ONLY=1; shift ;;
    --no-frontend) SERVICES="agentium-backend agentium-worker-cpu"; shift ;;
    --services) SERVICES="$2"; shift 2 ;;
    --branch) BRANCH="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    *) echo "Option inconnue: $1" >&2; exit 2 ;;
  esac
done

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_ylw=$'\033[33m'; c_rst=$'\033[0m'
say()  { printf '%s\n' "==> $*"; }
ok()   { printf '%s\n' "${c_grn}OK${c_rst}  $*"; }
warn() { printf '%s\n' "${c_ylw}!! ${c_rst} $*"; }
die()  { printf '%s\n' "${c_red}XX${c_rst}  $*" >&2; exit 1; }

cd "$REPO_DIR" || die "Dépôt introuvable: $REPO_DIR"

# --- Audit de dérive : manifeste md5 conteneur <-> arbre git (tout backend/app) -------------
drift_audit() {
  local fail=0

  # 1) Le checkout est-il sur le commit poussé ?
  git fetch origin "$BRANCH" -q || die "git fetch a échoué"
  local head origin_head
  head="$(git rev-parse --short HEAD)"
  origin_head="$(git rev-parse --short "origin/$BRANCH")"
  if [[ "$head" == "$origin_head" ]]; then
    ok "git HEAD ($head) == origin/$BRANCH"
  else
    warn "git HEAD ($head) != origin/$BRANCH ($origin_head)"
    fail=1
  fi

  # 2) Arbre propre (hors artefacts gitignored/logs) ?
  local dirty
  dirty="$(git status --porcelain | grep -vE 'uvicorn\.log|\.pyc$' || true)"
  if [[ -z "$dirty" ]]; then
    ok "arbre git propre"
  else
    warn "arbre git modifié (sera écrasé au reset) :"; printf '%s\n' "$dirty"
    fail=1
  fi

  # 3) Code des conteneurs == arbre git (manifeste md5 sur tout backend/app) ?
  for svc in agentium-backend agentium-worker-cpu; do
    docker ps --format '{{.Names}}' | grep -qx "$svc" || { warn "$svc non démarré, audit ignoré"; continue; }
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

if [[ "$CHECK_ONLY" -eq 1 ]]; then
  say "Audit de dérive (lecture seule) — branche $BRANCH"
  if drift_audit; then ok "Aucune dérive détectée."; exit 0; else die "Dérive détectée (voir ci-dessus)."; fi
fi

# --- Déploiement -----------------------------------------------------------------------------
say "Déploiement VM — branche $BRANCH, services: $SERVICES"

# 1) Garde-fou : ne pas écraser silencieusement des modifs suivies non commitées
dirty="$(git status --porcelain | grep -vE 'uvicorn\.log|\.pyc$' || true)"
if [[ -n "$dirty" && "$FORCE" -ne 1 ]]; then
  printf '%s\n' "$dirty"
  die "Arbre VM modifié. Ces changements ne sont PAS dans origin et seront perdus. Commit+push d'abord, ou relance avec --force."
fi

# 2) Aligner sur le commit poussé (source de vérité unique)
git fetch origin "$BRANCH" -q
git reset --hard "origin/$BRANCH"
DEPLOY_SHA="$(git rev-parse --short HEAD)"
ok "checkout aligné sur origin/$BRANCH @ $DEPLOY_SHA"

# 3) Build + recreate avec l'env VM (interpolation Compose + vars internes conteneur)
cd docker
[[ -f "$ENV_FILE" ]] || die "Env file manquant: docker/$ENV_FILE"
export AGENTIUM_ENV_FILE="$ENV_FILE"
export AGENTIUM_POSTGRES_PASSWORD="$(grep -E '^AGENTIUM_POSTGRES_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)"

say "docker compose build $SERVICES"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" build $SERVICES
say "docker compose up -d $SERVICES"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d $SERVICES
cd "$REPO_DIR"

# 4) Vérification de santé (avec retries)
BACKEND_PORT="${AGENTIUM_BACKEND_HOST_PORT:-8001}"
FRONTEND_PORT="${AGENTIUM_FRONTEND_HOST_PORT:-8081}"
say "Attente de la santé backend (port $BACKEND_PORT)…"
health_ok=0
for i in $(seq 1 30); do
  code="$(curl -fsS -o /dev/null -w '%{http_code}' "http://localhost:${BACKEND_PORT}/api/v1/health" 2>/dev/null || true)"
  if [[ "$code" == "200" ]]; then ok "backend /api/v1/health = 200 (après ${i}x)"; health_ok=1; break; fi
  sleep 4
done
[[ "$health_ok" -eq 1 ]] || die "backend pas sain après 120s (dernier code: ${code:-aucun})"

if printf '%s' "$SERVICES" | grep -q 'agentium-frontend'; then
  fcode="$(curl -fsS -o /dev/null -w '%{http_code}' "http://localhost:${FRONTEND_PORT}/healthz" 2>/dev/null || true)"
  [[ "$fcode" == "200" ]] && ok "frontend /healthz = 200" || warn "frontend /healthz = ${fcode:-aucun}"
fi

# 5) Audit de dérive post-déploiement (le code qui TOURNE == le commit déployé)
say "Audit de dérive post-déploiement…"
if drift_audit; then
  ok "Déploiement $DEPLOY_SHA terminé — conteneurs alignés sur origin/$BRANCH."
else
  die "Déploiement terminé mais dérive détectée — investiguer (image rebuild depuis un arbre périmé ?)."
fi
