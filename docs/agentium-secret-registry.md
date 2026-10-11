# Agentium — registre de secrets

Le registre de secrets (`backend/app/services/secrets/`) est le point unique
de stockage des secrets applicatifs d'Agentium : jetons de connecteurs, mots de
passe SMTP, clés d'API, secrets OAuth et secrets consommés par les flows. Une
configuration ne contient jamais la valeur d'un secret : elle contient une
**référence** `secret://…`, résolue au moment de l'usage, auditée, et révocable.

Les secrets d'infrastructure (Postgres, Keycloak, clés Fernet de bootstrap)
restent dans l'environnement d'exécution : voir [ops/secrets.md](ops/secrets.md).

## Modèle

| Table | Rôle |
| ----- | ---- |
| `secrets` | Métadonnées : `scope`, `workspace_id`, `system_id`, `owner_key`, `name`, `kind`, `backend`, `current_version`, `description`, `metadata`, `expires_at`, `rotated_at`, `created_by`, `disabled_at`. Unicité sur `(scope, owner_key, name)`. |
| `secret_versions` | Une ligne par version : `ciphertext` (backend `db`) ou `backend_ref` (backend `openbao`), `destroyed_at`. |

- **Portées** : `platform` (administrateurs plateforme), `workspace`
  (administrateurs de l'espace de travail), `system` (administrateurs du système).
- **Types** (`kind`) : `generic`, `password`, `api_key`, `token`,
  `oauth_client`.
- **Noms** : `^[a-z0-9][a-z0-9._-]{0,119}$`.
- **Versions** : chaque rotation crée une version ; la version courante est
  `current_version`. Une version détruite reste tracée (`destroyed_at`) et ne
  se résout plus (`SECRET_VERSION_DESTROYED`).
- **Désactivation / destruction** : `disable` bloque toute résolution ;
  `destroy` efface une version donnée, ou toutes les versions et désactive
  alors le secret. Les lignes restent pour
  l'historique et l'audit.
- **Valeurs** : `SecretValue` rend `***` dans `repr`, `str` et `format` ;
  la sérialisation JSON et le pickle lèvent une erreur ; seul `reveal()`
  expose la valeur. Les réponses
  d'API ne contiennent que des métadonnées et `value_set`.
- **Audit** : `secret.created`, `secret.rotated`, `secret.disabled`,
  `secret.destroyed`, `secret.resolved`, `secret.resolve_denied`, avec
  l'acteur et le consommateur (`SecretConsumer`), jamais la valeur.
- **Échec fermé** : sans clé de chiffrement ni backend joignable, l'écriture
  et la lecture échouent avec `SecretRegistryError` ; aucune valeur en clair
  n'est stockée par repli.

### Backends

| Backend | Stockage | Configuration |
| ------- | -------- | ------------- |
| `db` (défaut) | `secret_versions.ciphertext`, chiffré Fernet | `SECRET_REGISTRY_FERNET_KEY`, à défaut `CONNECTOR_SECRETS_FERNET_KEY` |
| `openbao` | KV v2 `agentium/data/<scope>/<owner_key>/<secret_id>` (`.../nodes/<secret_id>` pour les jetons serving nodes et Hugging Face), une version KV par version de secret | `OPENBAO_ADDR`, `OPENBAO_MOUNT` (`agentium`), `OPENBAO_ROLE_ID`, `OPENBAO_SECRET_ID`, `OPENBAO_TIMEOUT_SECONDS` |

`SECRET_REGISTRY_DEFAULT_BACKEND` choisit le backend des **nouveaux**
secrets. Chaque secret garde le backend qui l'a créé : basculer le défaut ne
déplace aucun secret existant.

## Références

```text
secret://platform/<name>[#<version>]
secret://workspace/<name>[#<version>]          # espace pris du consommateur
secret://system/<system_id>/<name>[#<version>]
```

Sans `#<version>`, la version courante est résolue. Une référence de portée
`workspace` se résout toujours dans l'espace de travail du consommateur : une
même configuration ne peut pas lire le secret d'un autre espace.

Dans les réglages de connecteurs, un champ secret contient
`{"ref": "secret://…"}` à la place de l'ancienne enveloppe chiffrée. Les
payloads publics continuent d'exposer `*_set: true/false`.

## API et interface

`/api/v1/secrets` (espace de travail courant) :

| Méthode | Chemin | Effet |
| ------- | ------ | ----- |
| `GET` | `/secrets?scope=&system_id=&include_disabled=` | Liste des métadonnées |
| `POST` | `/secrets` | Création (`name`, `value`, `kind`, `scope`, `system_id`) |
| `GET` | `/secrets/{id}` | Métadonnées |
| `GET` | `/secrets/{id}/consumers` | Connecteurs et flows qui référencent le secret |
| `POST` | `/secrets/{id}/rotate` | Nouvelle version |
| `POST` | `/secrets/{id}/disable` | Désactivation |
| `DELETE` | `/secrets/{id}` | Destruction |

L'interface expose la page **Espace de travail → Secrets** et le composant
partagé `app-secret-picker` (`frontend-ng/src/app/shared/secrets/`) : saisie
d'une nouvelle valeur (envoyée une fois, effacée du formulaire) ou choix d'un
secret existant. Le modèle lié est toujours une référence, jamais une valeur.

## Nœud de flow `secret`

Un nœud `secret` accorde à une tâche l'accès **par référence** à un secret :

```json
{
  "kind": "secret",
  "config": {
    "secret_ref": "secret://workspace/erp-api-key",
    "bindings": { "<task_node_id>": "<slot>" }
  }
}
```

- Une arête de données `secret → tâche` **et** une entrée dans `bindings`
  accordent à cette tâche un emplacement (`slot`) nommé.
- La valeur n'entre jamais dans le pool de variables. La tâche reçoit
  `skill_ctx["secrets"]`, un objet `SecretGrants` : `slots()`, `slot in
  grants`, `grants.get(slot)` → `SecretValue`. Chaque résolution est auditée
  (`secret.resolved`) au nom du run.
- Les valeurs révélées pendant un run sont masquées de tout ce que le moteur
  persiste ou publie : ledger d'invocations, checkpoints, SSE, payloads du
  walker, prompts LLM.
- Une Skill déclare ses emplacements dans
  `Skill.execution["secret_slots"]` (liste de noms). Quand la liste existe,
  le validateur refuse un emplacement non déclaré.

Codes du validateur (checklist du Flow Builder) :

| Code | Cause |
| ---- | ----- |
| `secret_unknown` | Référence absente ou secret désactivé dans la portée |
| `secret_scope_violation` | Secret d'un autre système ou d'un autre espace de travail |
| `secret_slot_unknown` | Emplacement non déclaré dans `execution.secret_slots` de la Skill |

L'inspecteur du nœud utilise `app-secret-picker` pour choisir ou créer le
secret, puis un champ d'emplacement par tâche reliée.

## Migration des connecteurs

`backend/app/services/secrets/compat.py` assure la transition :

- **Lecture double** : `read_secret_field` résout d'abord une référence
  `{"ref": …}`, sinon déchiffre l'enveloppe historique avec la clé du service.
- **Écriture** : `write_secret_field` crée (ou fait tourner) le secret nommé
  et stocke la référence. **Repli de transition** : sans
  `SECRET_REGISTRY_FERNET_KEY` (ni `CONNECTOR_SECRETS_FERNET_KEY`), l'écriture
  produit l'enveloppe historique. Ce repli est accepté pour la version de
  transition et disparaît une fois la clé du registre déployée partout.
- Noms dérivés : `secret_name("mcp", "My_Server", "token")` →
  `mcp-my-server-token`.

Script `scripts/agentium_secret_registry_migrate.py` :

```bash
python scripts/agentium_secret_registry_migrate.py --dry-run
python scripts/agentium_secret_registry_migrate.py --backup /chemin/protégé/backup.json
```

- Ordre : connecteurs du catalogue (jeton Hub inclus), MCP, RPA, HANA, portail
  LLM, SMTP Client360, jeton Hub plateforme.
- `--dry-run` n'écrit rien et vérifie que chaque enveloppe se déchiffre.
- Sans `--dry-run`, `workspaces.settings` et la connexion Hub plateforme sont
  sauvegardés en JSON (mode 0600) avant toute écriture.
- Idempotent : un champ qui contient déjà une référence est ignoré.
- La sortie nomme les champs et les secrets, jamais les valeurs ; le code de
  sortie vaut 1 dès qu'une entrée est en erreur.
- Prérequis : anciennes clés par service, `SECRET_REGISTRY_FERNET_KEY` (ou les
  réglages OpenBao) et `DATABASE_URL`.

## OpenBao

OpenBao (API compatible Vault) est un backend **optionnel**, activé par
`AGENTIUM_OPENBAO=1` dans `scripts/agentium-vm-deploy.sh`.

- Image `openbao/openbao` 2.6.4, épinglée par digest
  (`docker/compose.agentium.openbao.yml`), profil Compose `openbao`.
- Nœud unique, stockage raft dans `/srv/agentium-data/openbao`, joignable
  uniquement sur `agentium-net` (aucun port publié, pas d'interface web).
- Conteneur en lecture seule, `cap_drop: ALL` + `IPC_LOCK`,
  `no-new-privileges`.
- **Auto-unseal par clé statique** (`seal "static"`, OpenBao ≥ 2.4) : la clé
  hexadécimale de 32 octets est montée en lecture seule depuis
  `<déploiement>/runtime-env/openbao-unseal.key`.
- Audit fichier déclaratif : `/openbao/data/audit/audit.log` (0600).
- AppRoles et politiques :

| Rôle | Fichier d'identifiants | Droits |
| ---- | ---------------------- | ------ |
| `backend` (backend, migrate) | `runtime-env/openbao-backend.env` | `agentium/data/*` create/read/update, `destroy/*`, `metadata/*` read/list |
| `worker` (worker-cpu, worker-recipes) | `runtime-env/openbao-worker.env` | `agentium/data/*` read |
| `hub-fetch` (overlay Hugging Face) | `runtime-env/openbao-hub-fetch.env` | `agentium/data/platform/+/nodes/*` et `agentium/data/workspace/+/nodes/*` read |
| `snapshot` | `runtime-env/openbao-snapshot.env` | `sys/storage/raft/snapshot` read |

Disposition des chemins KV : `<scope>/<owner_key>/<secret_id>`, sauf les
secrets consommés par le téléchargeur Hub, rangés sous le segment dédié
`<scope>/<owner_key>/nodes/<secret_id>` : jetons des serving nodes du portail
LLM (`nodes-<nœud>-token`) et jeton Hugging Face (`huggingface-token`, portée
`platform` ou `workspace`). Le rôle `hub-fetch` ne lit que ce segment : ni
les autres secrets workspace/platform (clés cloud, connecteurs), ni la portée
`system`.

### Ordre de déploiement

1. Déployer le code et exécuter `migrate` (révision Alembic
   `124_secret_registry`).
2. Exporter `SECRET_REGISTRY_FERNET_KEY` dans l'environnement d'exécution.
3. Lancer la migration des connecteurs avec `--dry-run`, puis avec `--backup`
   vers un chemin protégé.
4. Avec `AGENTIUM_OPENBAO=1` :
   1. `agentium-vm-deploy.sh openbao-prepare` : clé d'unseal (0400, propriété
      de l'uid OpenBao) et répertoires raft/audit ;
   2. `agentium-vm-deploy.sh openbao-init` : démarrage du conteneur,
      `sys/init` avec une clé de récupération, KV v2, audit, AppRoles,
      politiques, fichiers `openbao-<rôle>.env` (0600) ; le jeton root est
      révoqué à la fin ;
   3. `agentium-vm-deploy.sh up` : services clients avec leurs identifiants.
5. `agentium-vm-deploy.sh openbao-status` : `bao status` doit répondre
   initialisé et descellé.
6. Basculer `SECRET_REGISTRY_DEFAULT_BACKEND=openbao` pour que les nouveaux
   secrets aillent dans OpenBao. Les secrets existants gardent leur backend
   (`db`) et se résolvent toujours.

Sur `omnirag-demo`, OpenBao est actif et `SECRET_REGISTRY_DEFAULT_BACKEND=openbao`
depuis le 11/10/2026 (app, workers, hub-fetch) ; les secrets migrés avant
cette date restent sur `db`. Retour arrière : remettre `db` dans les fichiers
runtime-env, puis `agentium-vm-deploy.sh up`.

Pour reconfigurer (nouvelle politique, nouveaux `secret_id`), régénérer un
jeton root à partir de la clé de récupération (`bao operator generate-root`),
le passer dans `BAO_TOKEN` à `agentium_openbao_bootstrap.py configure`, qui le
révoque en fin d'exécution.

### Emplacement de la clé d'unseal : limite

La clé d'unseal statique (`runtime-env/openbao-unseal.key`) et la clé de
récupération (`runtime-env/openbao-recovery.env`) sont sur **la même VM** que
les données raft. Ce choix protège contre la fuite isolée du répertoire de
données ou d'un snapshot, pas contre la compromission de l'hôte : un accès root
à la VM donne accès à la clé et aux données. Les deux fichiers sont copiés hors
de la VM, dans le coffre de l'équipe (`agentium-prod/openbao/`), séparément
des snapshots. Un KMS externe (seal `awskms`, `gcpckms`, `transit`) lève cette
limite ; il n'est pas en place.

### Snapshot et restauration

`agentium-vm-deploy.sh openbao-snapshot` exécute
`scripts/agentium-openbao-snapshot.sh` avec l'AppRole `snapshot` : un fichier
`openbao-<UTC>.snap` (0600) dans `/srv/agentium-data/openbao-backups`,
rétention `AGENTIUM_OPENBAO_BACKUP_RETAIN_DAYS` (14 jours par défaut). Les
identifiants ne passent ni par argv ni par les journaux. Entrée cron
quotidienne (root), installée sur `omnirag-demo` dans
`/etc/cron.d/agentium-openbao-snapshot` :

```text
17 3 * * * root <worktree>/scripts/agentium-openbao-snapshot.sh <déploiement>/runtime-env >>/srv/agentium-data/openbao-backups/snapshot.log 2>&1
```

Restauration (OpenBao ne sert plus de secrets pendant l'opération ; la **même
clé d'unseal** est requise, le snapshot étant scellé par elle) :

1. `docker cp <fichier>.snap agentium-openbao:/tmp/restore.snap`
2. Régénérer un jeton root depuis la clé de récupération
   (`bao operator generate-root`).
3. `docker exec -e BAO_TOKEN=<root> agentium-openbao bao operator raft snapshot restore -force /tmp/restore.snap`
4. Révoquer ce jeton root, puis `agentium-vm-deploy.sh openbao-status`.

Les secrets du backend `db` sont couverts par la sauvegarde Postgres ; la
clé `SECRET_REGISTRY_FERNET_KEY` est indispensable pour les relire.
