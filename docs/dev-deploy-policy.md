# Politique de développement & déploiement — Agentium / OmniRAG

> But : un **chemin unique et reproductible** pour développer en local, livrer via
> git, et déployer sur la VM `omnirag-demo` via Docker. Cette note existe pour
> éviter le workflow accidenté qu'on a subi (rsync de fichiers non commités,
> arbre git sale, rebuild à partir d'une copie périmée, VM désynchronisée de
> `origin`).
>
> Pour les opérations d'infra profondes (cutover Nginx, MinIO, migrations FAISS→Qdrant,
> adoption SFTP), la référence reste `docs/agentium-dockerization-runbook.md`.
> Cette note couvre le cycle **quotidien** code → commit → deploy.

---

## 0. Principe directeur

**`origin/demo/agentic` est l'unique source de vérité.** Tout ce qui tourne sur la
VM doit correspondre à un commit poussé. Le code arrive sur la VM **par `git`**,
jamais par `rsync`, `scp`, ou édition directe.

```
local (branche)  ──commit──>  origin/demo/agentic  ──git fetch+reset──>  VM  ──docker build+up──>  conteneurs
```

Si tu ne peux pas répondre à « quel commit tourne sur la VM ? » avec un SHA, le
déploiement est cassé.

---

## 1. Travailler en local

### Prérequis
- Docker Desktop lancé.
- Python (backend) et Node (frontend-ng) pour itérer hors conteneur.
- `backend/.env` local (jamais commité — voir `.gitignore`).

### Boucle de dev
1. Pars d'une branche à jour :
   ```bash
   git checkout demo/agentic
   git pull --ff-only origin demo/agentic
   ```
   Pour une feature isolée : `git checkout -b feat/<sujet>` puis PR vers `demo/agentic`.
2. Backend :
   ```bash
   cd backend && uvicorn app.main:app --reload
   pytest app/tests/...        # cible les tests liés à ta zone
   ```
3. Frontend :
   ```bash
   cd frontend-ng && npm run start     # dev server
   npm run build                       # vérifie que le bundle prod compile
   ```
4. Pré-commit : `pre-commit run --all-files` (la config existe à la racine).

### Règles locales
- **Aucun secret dans le repo** : `.env`, `docker/env/*.vm.env`, clés. Ils sont
  gitignorés — garde-les ainsi.
- **Pas d'instrumentation debug commitée** (ex. `fetch('/api/v1/voice/debug-trace'…)`,
  logs `kc.prefetch` verbeux). Si tu en ajoutes pour diagnostiquer, retire-les
  **avant** le commit de livraison.
- Ne laisse pas traîner un arbre sale : `git status` doit être propre avant de
  changer de tâche.

---

## 2. Livrer via Git (commit + push)

Le déploiement **commence** par un commit propre poussé sur `origin`.

```bash
# 1. Vérifier ce qui part
git status -sb
git diff --stat
git diff --name-only | grep -iE '\.env|secret|credential|\.pem|\.key' && echo "STOP: secret détecté" || echo "ok, pas de secret"

# 2. Stager uniquement le code suivi (pas les artefacts de démo locaux)
git add -u            # fichiers suivis modifiés
# git add <nouveaux fichiers volontaires>

# 3. Commit conventionnel (feat/fix/chore/docs + scope)
git commit -m "feat(scope): description courte de l'intention"

# 4. Pousser
git push origin demo/agentic
```

### Style de commit
Conventional commits, en suivant l'historique du repo :
`fix(rag): …`, `feat(capture): …`, `fix(ui): …`, `docs: …`.
Message qui explique **le pourquoi**, pas seulement le quoi.

### Règles git
- **Ne jamais** `git push --force` sur `demo/agentic` / `main`.
- **Ne jamais** `git commit` sans qu'on te l'ait demandé explicitement.
- `git reset --hard` est réservé aux **cibles de déploiement** (la VM), pas à ton
  poste de dev, et uniquement vers un commit déjà poussé (voir §3).
- Pas de `rsync`/`scp` de code vers la VM. Jamais. C'est la cause racine du bazar.

---

## 3. Déployer sur la VM via Docker

La VM `omnirag-demo` est aussi le **nœud de build** : les images sont construites
sur place et taguées en local (`agentium-backend:local`, `agentium-frontend:local`,
`agentium-worker:local`). Pas de registry externe.

### Coordonnées canoniques
| Élément | Valeur |
|---|---|
| Hôte SSH | `omnirag-demo` |
| Dossier de déploiement | `/home/ubuntu/omnirag` (checkout git) |
| Dossier compose | `/home/ubuntu/omnirag/docker` |
| Fichier compose | `compose.agentium.yml` |
| Env conteneurs | `docker/env/agentium.vm.env` (gitignored, **jamais** dans un commit) |
| `AGENTIUM_ENV_FILE` | `./env/agentium.vm.env` — **relatif au dossier `docker/`** |

> Piège vécu : `AGENTIUM_ENV_FILE=./env/agentium.vm.env` est relatif à `docker/`,
> donc le fichier est `docker/env/agentium.vm.env`, pas `env/` à la racine.
> Sans le bon env file, le backend démarre avec `agentium.env.example` et échoue
> sur l'auth Postgres.

### Procédure standard (rebuild backend + frontend)

```bash
ssh omnirag-demo

# 1. Aligner le checkout sur le commit poussé (source de vérité)
cd /home/ubuntu/omnirag
git fetch origin demo/agentic
git reset --hard origin/demo/agentic      # cible de déploiement: reset OK vers un commit poussé
git rev-parse --short HEAD                  # note le SHA déployé

# 2. Build + recreate avec l'env VM (depuis docker/)
cd docker
export AGENTIUM_ENV_FILE=./env/agentium.vm.env
export AGENTIUM_POSTGRES_PASSWORD=$(grep -E '^AGENTIUM_POSTGRES_PASSWORD=' env/agentium.vm.env | cut -d= -f2-)
docker compose -f compose.agentium.yml build agentium-backend agentium-frontend
docker compose -f compose.agentium.yml up -d agentium-backend agentium-frontend
```

> `git reset --hard origin/demo/agentic` sur la VM est **sûr** : l'arbre de la VM
> ne doit contenir aucune modif unique (tout passe par `origin`). Les fichiers
> gitignored (`docker/env/*.vm.env`, volumes de données) ne sont **pas** touchés
> par le reset.
>
> `AGENTIUM_POSTGRES_PASSWORD` est exporté dans le shell car Compose l'interpole
> (`${AGENTIUM_POSTGRES_PASSWORD}`) ; `--env-file` ne sert qu'aux variables
> **internes aux conteneurs**, pas à l'interpolation Compose.

### Ne touche pas à l'infra par accident
- N'utilise **pas** le profil `infra` (`--profile infra`) en déploiement courant :
  il recrée Postgres / Keycloak / Qdrant.
- Ne redémarre/recrée **jamais** `agentium-sftp` pendant un transfert SFTP Andritz.
- Build/recreate **uniquement** `agentium-backend` et `agentium-frontend` (+
  `agentium-worker-cpu` si la logique worker a changé).

---

## 4. Vérification post-déploiement (obligatoire)

Un déploiement n'est « fini » que si ces checks passent.

```bash
# Santé
ssh omnirag-demo 'docker inspect -f "{{.State.Health.Status}}" agentium-backend'   # -> healthy
ssh omnirag-demo 'curl -fsS -o /dev/null -w "%{http_code}\n" http://localhost:8000/health/live'  # -> 200

# Le code qui TOURNE = le commit attendu (pas juste le checkout hôte)
ssh omnirag-demo 'docker exec agentium-backend python -c "import app; print(\"import ok\")"'
# Vérifier un marqueur de ton changement dans l'image en cours :
ssh omnirag-demo 'docker exec agentium-backend grep -c "<un texte unique de ton fix>" /app/backend/app/services/<fichier>.py'

# Frontend servi
ssh omnirag-demo 'curl -fsSI http://localhost:8081/ | head -1'
```

> Piège vécu : l'image peut être rebuild à partir d'un arbre périmé. Toujours
> vérifier un **marqueur du changement dans le conteneur qui tourne**, pas
> seulement le SHA du checkout hôte.

### Checklist de clôture
- [ ] `git status` local propre, commit poussé sur `origin/demo/agentic`.
- [ ] VM : `git rev-parse HEAD` == `origin/demo/agentic`.
- [ ] `agentium-backend` healthy, `/health/live` = 200.
- [ ] Marqueur du fix présent dans le conteneur (backend et/ou frontend).
- [ ] Aucune instrumentation debug résiduelle (`grep -c debug-trace` == 0).
- [ ] Smoke test fonctionnel (1 requête chat ou 1 prefetch capture selon la zone touchée).

---

## 5. Anti-patterns (ce qu'on ne refait plus)

| Anti-pattern | Pourquoi c'est cassé | À la place |
|---|---|---|
| `rsync`/`scp` de fichiers vers la VM | Aucune traçabilité, dérive silencieuse vs `origin` | `git fetch` + `reset --hard` vers le commit poussé |
| Rebuild VM sans aligner git d'abord | Image construite depuis un arbre périmé (régressions ré-introduites) | §3 étape 1 **avant** le build |
| Laisser la VM en arbre sale / non commité | « quel code tourne ? » sans réponse | La VM ne contient que du code de `origin` |
| Oublier `AGENTIUM_ENV_FILE` | Backend démarre sur `agentium.env.example` → auth Postgres échoue | Toujours exporter `./env/agentium.vm.env` depuis `docker/` |
| Commiter secrets / instrumentation debug | Fuite + bruit en prod | `.gitignore` + nettoyage avant commit |
| Vérifier seulement le SHA du checkout hôte | L'image en cours peut différer du checkout | Vérifier un marqueur **dans le conteneur** |

---

## 6. Récapitulatif express (copier-coller)

```bash
# --- LOCAL : livrer ---
git add -u && git commit -m "feat(scope): intention" && git push origin demo/agentic

# --- VM : déployer le commit poussé ---
ssh omnirag-demo '
  set -e
  cd /home/ubuntu/omnirag
  git fetch origin demo/agentic && git reset --hard origin/demo/agentic
  echo "Deploying $(git rev-parse --short HEAD)"
  cd docker
  export AGENTIUM_ENV_FILE=./env/agentium.vm.env
  export AGENTIUM_POSTGRES_PASSWORD=$(grep -E "^AGENTIUM_POSTGRES_PASSWORD=" env/agentium.vm.env | cut -d= -f2-)
  docker compose -f compose.agentium.yml build agentium-backend agentium-frontend
  docker compose -f compose.agentium.yml up -d agentium-backend agentium-frontend
'

# --- VM : vérifier ---
ssh omnirag-demo 'docker inspect -f "{{.State.Health.Status}}" agentium-backend && curl -fsS -o /dev/null -w "live=%{http_code}\n" http://localhost:8000/health/live'
```
