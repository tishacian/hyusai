# ADR 0004 — Réorganiser le monorepo omnirag → Agentium

- **Statut** : Accepté
- **Date** : 2026-10-12
- **Portée** : chaîne de déploiement VM, SPA vanilla `/legacy/`, documentation historique, diffusion des lots, chemins gelés
- **Contexte source** : inventaire du dépôt sur `demo/agentic` (`c71f6704`)
- **Prolonge** : [ADR 0003](0003-generalisation-frontieres.md)

---

## Contexte

Le dépôt porte deux strates. La première, omnirag (R&D RAG : `src/`, `benchmarking/`,
`configurations/`, la stack Docker `docker/docker-compose.yml`, la SPA vanilla
`frontend/`), n'est plus exécutée en production. La seconde, Agentium (`backend/`,
`frontend-ng/`, `docker/Dockerfile.agentium-*`, `scripts/agentium-*`), est la seule
déployée sur la VM.

Trois ponts relient encore les deux strates : `src/metadata_extraction/docmeta`
(chargé par un shim `sys.path`), `sample_data/` (lu par l'API documents et le seed de
base de connaissances) et le mount StaticFiles `/legacy/`. Deux chaînes de déploiement
coexistent : `scripts/deploy-agentium-safe.sh` et `scripts/agentium-vm-deploy.sh`.
Enfin `docs/` mélange la documentation vivante, lue par la compliance, les images et
les seeds, et plusieurs centaines de fichiers de preuves, captures et rendus datés.

La réorganisation se fait en six phases, sans casser les modes ops. Cet ADR fixe les
décisions qui la cadrent.

---

## Décisions

### D1 — `agentium-vm-deploy.sh` devient la seule chaîne de déploiement — **Acté**

La chaîne officielle est `scripts/agentium-vm-deploy.sh` (`storage-check`, `migrate`,
`up`, `catalog-check`), lancée en root avec `AGENTIUM_IMAGE_TAG=<sha12>`. Une partie
des garde-fous de la chaîne safe y est reportée (phase 4a : dump `pg_dump -Fc` avant
`migrate`, gate de maintenance optionnelle, vérification de `/api/v1/build-info` après
`up`, journal TSV des déploiements, répertoire d'environnement configurable). La chaîne
safe (`deploy-agentium-safe.sh`, `deploy-vm.sh`, l'unité systemd) est retirée ensuite
(phase 4c), avec ses tests de contrat.

### D2 — La SPA vanilla `/legacy/` est retirée — **Acté**

Sur environ 14 jours de logs nginx, la route `/legacy/` n'a reçu que des requêtes de
scanners vers `.git/config`. La phase 2 supprime `frontend/`, le mount StaticFiles de
`backend/app/main.py`, la location `/legacy/` des trois confs nginx du dépôt et de la
conf nginx de l'hôte. La route Angular `/settings/legacy` n'est pas concernée.

### D3 — Les docs historiques sont rangées dans `docs/archive/AAAA/` — **Acté**

Les dossiers de preuves, captures, rendus et rapports datés vont sous
`docs/archive/<année>/<chemin d'origine>` : `docs/evidence/x` devient
`docs/archive/2026/evidence/x`. Ils restent dans le dépôt : l'historique `git log
--follow` et les liens restent lisibles. Les fichiers lus par du code ou des tests
restent à leur place. Les scripts de QA n'écrivent plus dans `docs/` : leur sortie par
défaut est `artifacts/qa/`, ignoré par git. L'index est
[docs/archive/README.md](../archive/README.md).

### D4 — Chaque phase est diffusée puis déployée — **Acté**

Un lot est un commit (ou une courte série) sur `demo/agentic`. Après la barrière de
validation :

1. push de `demo/agentic` sur `origin` ;
2. `develop` en fast-forward sur `demo/agentic` ;
3. `main` aligné par un commit de merge qui porte l'arbre de HEAD
   (`git commit-tree HEAD^{tree} -p origin/main -p HEAD`) ;
4. synchronisation du miroir ;
5. déploiement VM par `agentium-vm-deploy.sh`, puis vérification de `build-info`
   (`revision_verified`) et de la santé.

Aucun force-push sur `origin`. La barrière de validation est :
`pytest app/tests/infra -q`, la suite backend en `-n 8`,
`python scripts/agentium_compliance.py --check`, et `npx ng test` si `frontend-ng/`
est touché.

### D5 — Les chemins gelés ne bougent qu'avec leurs tests — **Acté**

Un chemin présent à la fois dans un script ou une image (`scripts/`, `docker/`,
`deploy/`) et dans `backend/app/tests/infra` ne bouge que dans un lot qui modifie les
deux. La carte ci-dessous est l'inventaire au `c71f6704`.

---

## Carte des chemins gelés

### Chemins de la VM

| Chemin | Rôle |
|---|---|
| `/srv/agentium-data` et ses sous-dossiers `deployments`, `hub-cache`, `minio`, `ml-deep-models`, `object_store`, `openbao`, `openbao-backups`, `qdrant`, `qdrant-snapshots`, `recipe_envs`, `release-a-deployments` | données de la plateforme (disque `sdb`) |
| `/home/ubuntu/omnirag/backend/data/secure_deposit` | point de montage du dépôt sécurisé (disque `sdc`) ; déplacé en phase 4b |
| `/home/ubuntu/omnirag/backend/faiss_db` | index FAISS ; déplacé en phase 4b |
| `/var/lib/postgresql/data`, `/var/lib/rabbitmq`, `/var/lib/docker/volumes` | volumes des services |
| `/etc/nginx/snippets/agentium-deploy-maintenance.conf`, `/var/lib/agentium/deploy-maintenance` | gate de maintenance |
| `/etc/systemd/system/agentium-backend.service` et `agentium-backend.service.d/99-agentium-safe-runtime-env.conf` | chaîne safe ; retirés en phase 4c |

### Chemins du dépôt

| Famille | Chemins |
|---|---|
| Images | `docker/Dockerfile.agentium-*` et leurs `.dockerignore`, `docker/compose.agentium*.yml`, `docker/nginx/agentium-frontend.conf`, `docker/env/agentium.env.example` |
| Nginx | `deploy/nginx/agentium.conf`, `agentium-container-backend.conf`, `agentium-container-frontend.conf`, `agentium-deploy-maintenance.conf` |
| Dépendances | `backend/requirements*.txt`, `backend/constraints-demo-*.txt`, `backend/rag_models.lock.json`, `frontend-ng/package-lock.json` |
| Backend | `backend/alembic`, `backend/app/main.py`, `backend/app/core/config.py`, `backend/app/core/settings_manager.py`, les services et endpoints `secure_deposit*`, `settings*`, `livekit_service.py`, `rag_preset_service.py`, `system_catalog_bindings.py`, `workspace_blueprints.py`, `backend/keycloak/` |
| Scripts | `scripts/agentium-*.sh`, `scripts/agentium_*.py`, `scripts/deploy-agentium-safe.sh`, `scripts/deploy-vm.sh`, `scripts/run-agentium-safe-canaries.sh`, `backend/scripts/{audit_post_canary_database,audit_qdrant_write_barrier,fetch_rag_models,qualify_giskard_raget}.py` |
| Configuration | `config/agentium/release-a-evidence-authorities.v1.json`, `deploy/agentium-backend.service` |
| Canaries | `frontend-ng/e2e/tests/{09,11,16,17}-*.spec.ts`, `frontend-ng/e2e/fixtures/{accessibility-matrix,experience-canary}.ts` |
| Docs lues par du code | `docs/agentium-compliance-matrix.md`, `docs/mental-model.md`, `docs/adr/0003-generalisation-frontieres.md` |
| Ponts omnirag | `data/hkunlp_embeddings.npy`, `src/metadata_extraction`, `connections`, `sample_data`, `frontend` (retirés en phases 1 et 2) |

La liste `_ALLOWED_PATHS` du profil Release A n'est pas modifiée par cette
réorganisation. Si elle doit changer, un profil v8 est créé avec un nouveau digest ;
le v7 n'est pas réécrit.

---

## Conséquences

- La racine du dépôt ne contient plus, à la fin de la phase 2, que la strate Agentium.
  Le code omnirag reste consultable au tag `archive/omnirag-rd`.
- Un lien vers un document historique passe par `docs/archive/2026/…`.
- Un script de QA lancé sans variable de sortie écrit sous `artifacts/qa/` et ne salit
  plus `git status`.
- Déplacer un chemin gelé sans mettre à jour son test fait échouer `tests/infra`.

## Seuil de réouverture

Rouvrir D1 si `agentium-vm-deploy.sh` ne peut pas porter un garde-fou de la chaîne
safe sans le dupliquer. Rouvrir D2 si un client demande l'accès à la SPA vanilla.
