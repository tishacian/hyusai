# Mémoire de session — grounding AYA générique + déploiement Docker VM

Date : 26 mai 2026  
Branche : `demo/agentic`  
VM : `omnirag-demo`  
Repo VM : `/home/ubuntu/omnirag`

Cette note sert de reprise rapide pour la session où le comportement “chat-first”
d’AYA a été transformé en capacité générique Agentium, puis poussé et déployé sur
la VM de démo. Elle complète les runbooks existants ; elle ne contient pas de
secret.

## Ce qui a été livré

Commit déployé :

```text
44f3920b feat(chat): add inherited answer grounding policy
```

Contenu fonctionnel :

- ajout d’une politique générique `Answer Grounding Policy` côté backend ;
- résolution par héritage : plateforme → workspace → profil assistant → requête ;
- mode `strict` conservateur par défaut pour les assistants non configurés ;
- mode `balanced` possible pour les assistants configurés, avec fallback LLM
  général sans fausse citation quand aucun contexte workspace n’est disponible ;
- garde-fous serveur : documents, état courant, actions, sécurité, OSINT,
  chiffres et faits workspace restent forcés en `strict` ;
- AYA / `vigie_executive` hérite du mode `balanced` via configuration de profil,
  avec shim de compatibilité si la config n’est pas encore seedée ;
- Quick Panel / chat Angular envoie `grounding_mode` depuis la config héritée,
  pas depuis un hardcode spécifique à AYA.

Fichiers clés :

- `backend/app/services/chat_grounding.py`
- `backend/app/api/v1/endpoints/chat.py`
- `backend/app/agents/procurement_agent.py`
- `backend/app/services/mission_room.py`
- `frontend-ng/src/app/features/chat/chat-panel.component.ts`

Tests locaux passés avant push :

```bash
cd backend
poetry run pytest \
  app/tests/services/test_chat_grounding.py \
  app/tests/api/test_chat_stream_hardening.py \
  app/tests/services/test_omnirag_grounding_policy.py \
  app/tests/services/test_mission_room.py
# 30 passed

cd ..
python3 scripts/test_s3_resolver.py
# 12/12 PASS

cd frontend-ng
CI=1 npm run build:prod
# build OK ; warnings budget/CJS déjà connus
```

## Mode opératoire Git local

Flux utilisé :

```bash
git status --short --branch
git add <fichiers de la feature>
git commit -m "feat(chat): add inherited answer grounding policy"
git push origin demo/agentic
```

Attention : plusieurs fichiers QA, screenshots et documents étaient non suivis
pendant la session. Ils ont été laissés intacts. Ne pas faire de `git add .`
dans ce repo sans vérifier le statut.

## Mode opératoire déploiement VM actuel

La prod observée pendant cette session tourne via Docker Compose. Ne pas repartir
sur le flux systemd historique de `docs/vm-deploy-chat-runbook.md` sans vérifier
l’état réel de la VM.

### Pull code

```bash
ssh omnirag-demo
cd /home/ubuntu/omnirag
git fetch origin
git checkout demo/agentic
git pull --ff-only origin demo/agentic
git log -1 --oneline
```

### Compose file et env corrects

Fichier Compose :

```bash
/home/ubuntu/omnirag/docker/compose.agentium.yml
```

Env Docker VM correct :

```bash
/home/ubuntu/omnirag/docker/env/agentium.vm.env
```

Point important : `backend/.env` est une env historique/systemd avec des endpoints
host-local. Pour les conteneurs, il faut utiliser `AGENTIUM_ENV_FILE=./env/agentium.vm.env`.
Sans ça, Compose peut reprendre les valeurs par défaut/exemple et le backend peut
démarrer avec une mauvaise URL Postgres.

### Rebuild/redeploy Docker recommandé

Depuis la VM :

```bash
cd /home/ubuntu/omnirag/docker
AGENTIUM_ENV_FILE=./env/agentium.vm.env \
docker compose -f compose.agentium.yml up -d --build \
  agentium-backend agentium-worker-cpu agentium-frontend
```

Si un rebuild a déjà été fait mais que les conteneurs ont été recréés avec le
mauvais environnement, recréer sans rebuild avec l’env VM :

```bash
cd /home/ubuntu/omnirag/docker
AGENTIUM_ENV_FILE=./env/agentium.vm.env \
docker compose -f compose.agentium.yml up -d --no-build \
  agentium-backend agentium-worker-cpu
```

### Vérifications post-deploy

```bash
docker ps --filter name=agentium
curl -fsS http://127.0.0.1:8001/health/live
curl -fsS http://127.0.0.1:8081/healthz
curl -I https://agentium.papai.ai
docker logs --tail=100 agentium-backend
```

État attendu observé après correction env :

- `agentium-backend` : `Up`, `healthy`
- `agentium-worker-cpu` : `Up`
- `agentium-frontend` : `Up`, `healthy`
- `https://agentium.papai.ai` : `HTTP 200`

Logs notables vus pendant la session :

- erreurs RSS 403 sur certains feeds publics, déjà connues et non bloquantes pour
  ce déploiement ;
- le premier redémarrage backend a échoué à cause d’un mauvais env Postgres ;
  corrigé avec `AGENTIUM_ENV_FILE=./env/agentium.vm.env`.

## Reprise rapide si nouveau hotfix

1. Vérifier `git status --short --branch` local et ne stage que les fichiers du
   hotfix.
2. Lancer les tests ciblés, puis `python3 scripts/test_s3_resolver.py` si Sentinel
   est touché.
3. `git commit`, puis `git push origin demo/agentic`.
4. Sur `omnirag-demo`, `git pull --ff-only origin demo/agentic`.
5. Redéployer avec Compose et l’env VM :

```bash
cd /home/ubuntu/omnirag/docker
AGENTIUM_ENV_FILE=./env/agentium.vm.env \
docker compose -f compose.agentium.yml up -d --build \
  agentium-backend agentium-worker-cpu agentium-frontend
```

6. Vérifier santé backend/frontend et HTTP public.

## À ne pas faire

- Ne pas utiliser `git add .` sans revue, le repo contient souvent des artefacts
  QA non suivis.
- Ne pas lancer Compose sans `AGENTIUM_ENV_FILE=./env/agentium.vm.env` sur la VM.
- Ne pas supposer que le runbook systemd historique reflète l’état prod actuel.
- Ne pas committer de secret Copernicus, OpenAI, Postgres, Keycloak ou MinIO.
- Ne pas activer un mode live OSINT/satellite en démo VP sans gate produit.

