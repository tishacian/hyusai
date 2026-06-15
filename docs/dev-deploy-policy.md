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

### Cas realtime LiveKit

LiveKit reste un déploiement applicatif, pas un déploiement `infra`, mais il a
une contrainte supplémentaire : le serveur `agentium-livekit` ne lit pas tout le
fichier backend `AGENTIUM_ENV_FILE`. Compose doit recevoir explicitement les
clés LiveKit dans l'environnement du shell, sinon le serveur média peut démarrer
avec les clés de démo pendant que le backend utilise les vraies clés VM.
Si `LIVEKIT_WEBHOOK_API_KEY` est dédiée, elle doit être présente dans
`LIVEKIT_KEYS` et le backend doit recevoir son secret via
`LIVEKIT_WEBHOOK_API_SECRET`. Le fichier
`docker/livekit/agentium-livekit.yaml` contient seulement un placeholder
`__LIVEKIT_WEBHOOK_API_KEY__` ; le compose le remplace au démarrage du conteneur
avec `LIVEKIT_WEBHOOK_API_KEY` avant de lancer `/livekit-server`.
La plage UDP demo par defaut est courte (`50000-50100`) pour eviter un blocage
Docker lors du publish de milliers de ports sur la VM. Elargir vers
`50000-60000` seulement lors d'un vrai cutover WebRTC production avec firewall
et monitoring prets.
Sur la VM demo mono-domaine, l'ingress public LiveKit peut rester sur
`wss://agentium.papai.ai/livekit` via Nginx, qui strippe le prefixe `/livekit/`
vers `127.0.0.1:7880`. Le sous-domaine `livekit.agentium.papai.ai` n'est pas
obligatoire tant que le certificat/DNS dedie n'existe pas.

Depuis `/home/ubuntu/omnirag/docker` :

```bash
export AGENTIUM_ENV_FILE=./env/agentium.vm.env
export AGENTIUM_POSTGRES_PASSWORD=$(grep -E '^AGENTIUM_POSTGRES_PASSWORD=' env/agentium.vm.env | cut -d= -f2-)
export LIVEKIT_API_KEY="$(grep -E '^LIVEKIT_API_KEY=' env/agentium.vm.env | cut -d= -f2-)"
export LIVEKIT_API_SECRET="$(grep -E '^LIVEKIT_API_SECRET=' env/agentium.vm.env | cut -d= -f2-)"
export LIVEKIT_WEBHOOK_API_KEY="$(grep -E '^LIVEKIT_WEBHOOK_API_KEY=' env/agentium.vm.env | cut -d= -f2-)"
export LIVEKIT_KEYS="$(grep -E '^LIVEKIT_KEYS=' env/agentium.vm.env | cut -d= -f2-)"
export LIVEKIT_RTC_UDP_RANGE_START="${LIVEKIT_RTC_UDP_RANGE_START:-50000}"
export LIVEKIT_RTC_UDP_RANGE_END="${LIVEKIT_RTC_UDP_RANGE_END:-50100}"
test -n "$LIVEKIT_WEBHOOK_API_KEY" || export LIVEKIT_WEBHOOK_API_KEY="$LIVEKIT_API_KEY"
test -n "$LIVEKIT_KEYS" || export LIVEKIT_KEYS="$LIVEKIT_API_KEY: $LIVEKIT_API_SECRET"

docker compose -f compose.agentium.yml --profile realtime build agentium-backend agentium-frontend agentium-livekit-agent
docker compose -f compose.agentium.yml --profile realtime up -d agentium-livekit agentium-backend agentium-frontend agentium-livekit-agent
```

Ne pas sourcer tout `env/agentium.vm.env` : certains champs peuvent contenir des
espaces non quotés.

Checks realtime minimum :

```bash
docker compose -f compose.agentium.yml --profile realtime ps agentium-livekit agentium-livekit-agent agentium-backend agentium-frontend
docker inspect -f "{{.State.Health.Status}}" agentium-livekit-agent
docker inspect -f "{{.State.Health.Status}}" agentium-backend
docker exec agentium-backend python -c "from app.services.livekit_service import LiveKitService; c=LiveKitService().public_config(); print(c['enabled'], c['url'])"
curl -fsS http://127.0.0.1:${AGENTIUM_FRONTEND_HOST_PORT:-8081}/healthz
docker logs --tail=80 agentium-livekit-agent
docker logs --tail=80 agentium-livekit
docker ps --format '{{.Names}}\t{{.Status}}' | grep agentium-sftp
```

La session Knowledge Capture doit emettre au moins ces metriques data-channel :
`livekit_agent_dispatched`, `session_started`, `livekit_agent_joined`,
`time_to_first_text`, puis `livekit_barge_in_audio_reset` et `barge_in` si
l'expert coupe l'IA. Le champ `connect_attempts` sur
`livekit_agent_dispatched`/`session.ready` permet de diagnostiquer une latence de
connexion LiveKit sans ouvrir les logs Node.

Rollback realtime sans toucher l'infra :

```bash
cd /home/ubuntu/omnirag/docker
export AGENTIUM_ENV_FILE=./env/agentium.vm.env
export AGENTIUM_POSTGRES_PASSWORD=$(grep -E '^AGENTIUM_POSTGRES_PASSWORD=' env/agentium.vm.env | cut -d= -f2-)
# Mettre LIVEKIT_ENABLED=false dans docker/env/agentium.vm.env ou dans les settings workspace.
docker compose -f compose.agentium.yml up -d agentium-backend agentium-frontend
docker compose -f compose.agentium.yml --profile realtime stop agentium-livekit-agent agentium-livekit
```

Le rollback remet l'UI sur `backend_ws` / `VoiceSessionGateway`. Il ne lance pas
`--profile infra`, ne recrée pas Postgres/Qdrant/Keycloak et ne touche pas
`agentium-sftp`.

### Cas realtime-scale LiveKit / Redis

Le profil `realtime-scale` est reserve au moment ou LiveKit doit tourner en
multi-node ou ou l'on veut valider explicitement la couche Redis LiveKit. Il
n'est pas requis pour la VM demo single-node.

```bash
cd /home/ubuntu/omnirag/docker
export AGENTIUM_ENV_FILE=./env/agentium.vm.env
export AGENTIUM_POSTGRES_PASSWORD=$(grep -E '^AGENTIUM_POSTGRES_PASSWORD=' env/agentium.vm.env | cut -d= -f2-)
export LIVEKIT_API_KEY="$(grep -E '^LIVEKIT_API_KEY=' env/agentium.vm.env | cut -d= -f2-)"
export LIVEKIT_API_SECRET="$(grep -E '^LIVEKIT_API_SECRET=' env/agentium.vm.env | cut -d= -f2-)"
export LIVEKIT_WEBHOOK_API_KEY="$(grep -E '^LIVEKIT_WEBHOOK_API_KEY=' env/agentium.vm.env | cut -d= -f2-)"
export LIVEKIT_KEYS="$(grep -E '^LIVEKIT_KEYS=' env/agentium.vm.env | cut -d= -f2-)"
export LIVEKIT_REDIS_ADDRESS=agentium-livekit-redis:6379
test -n "$LIVEKIT_WEBHOOK_API_KEY" || export LIVEKIT_WEBHOOK_API_KEY="$LIVEKIT_API_KEY"
test -n "$LIVEKIT_KEYS" || export LIVEKIT_KEYS="$LIVEKIT_API_KEY: $LIVEKIT_API_SECRET"

docker compose -f compose.agentium.yml --profile realtime --profile realtime-scale up -d agentium-livekit-redis agentium-livekit
docker compose -f compose.agentium.yml --profile realtime --profile realtime-scale up -d agentium-backend agentium-frontend agentium-livekit-agent
docker exec agentium-backend python -c "from app.services.livekit_service import LiveKitService; print(LiveKitService().public_config()['scale'])"
```

Ce profil ne doit pas etre ajoute a la commande de deploiement courant tant que
le besoin multi-node n'est pas etabli. Si `LIVEKIT_REDIS_ADDRESS` est vide, le
serveur LiveKit reste en single-node. L'egress/recording reste bloque par
defaut (`LIVEKIT_EGRESS_ENABLED=false`) ; l'autorisation par workspace doit etre
documentee avant tout enregistrement audio.

---

## 4. Vérification post-déploiement (obligatoire)

Un déploiement n'est « fini » que si ces checks passent.

```bash
# Santé
ssh omnirag-demo 'docker inspect -f "{{.State.Health.Status}}" agentium-backend'   # -> healthy
ssh omnirag-demo 'curl -fsS -o /dev/null -w "%{http_code}\n" http://localhost:${AGENTIUM_BACKEND_HOST_PORT:-8001}/health/live'  # -> 200

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

## 6. Script de déploiement unique (recommandé)

`scripts/deploy-vm.sh` codifie tout le §3 + §4 en une commande et **remplace** les
hotfix manuels (`docker cp` / `scp` / édition in-container). Il arrive sur la VM
**par git** (jamais par scp), donc on le lance depuis le checkout :

```bash
# --- LOCAL : livrer ---
git add -u && git commit -m "feat(scope): intention" && git push origin demo/agentic

# --- VM : déployer le commit poussé (fetch+reset -> build 3 images -> health -> audit dérive) ---
ssh omnirag-demo 'cd /home/ubuntu/omnirag && git fetch origin demo/agentic && git reset --hard origin/demo/agentic && bash scripts/deploy-vm.sh'
```

Le script :
- refuse de tourner si l'arbre VM a des modifs suivies non commitées (sauf `--force`) — anti-dérive ;
- aligne le checkout sur `origin/demo/agentic` (`git reset --hard`) ;
- rebuild `agentium-backend` + `agentium-frontend` + `agentium-worker-cpu` avec `--env-file` et `AGENTIUM_POSTGRES_PASSWORD` exporté ;
- attend la santé backend (`/api/v1/health` = 200, retries) et vérifie le frontend ;
- lance un **audit de dérive** : compare le manifeste md5 de tout `backend/app/*.py`
  entre le conteneur et l'arbre git, et vérifie `HEAD == origin` — il échoue
  bruyamment si un `docker cp` a divergé ou si une image a été buildée depuis un
  arbre périmé.

Options : `--check-only` (audit seul, lecture seule), `--no-frontend`,
`--services "…"`, `--branch <name>`, `--force`.

> Audit de dérive à la demande (sans déployer) :
> ```bash
> ssh omnirag-demo 'cd /home/ubuntu/omnirag && bash scripts/deploy-vm.sh --check-only'
> ```

### Procédure manuelle équivalente (si besoin de débrayer le script)

```bash
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
ssh omnirag-demo 'docker inspect -f "{{.State.Health.Status}}" agentium-backend && curl -fsS -o /dev/null -w "live=%{http_code}\n" http://localhost:${AGENTIUM_BACKEND_HOST_PORT:-8001}/health/live'
```
