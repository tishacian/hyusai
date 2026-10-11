# Agentium — Lot 5 : nettoyage et gouvernance

> **Archive de rollout.** Les commandes de cette note décrivent la livraison
> historique du Lot 5 et ne sont plus le chemin opératoire courant. Tout
> nouveau déploiement passe par le
> [runbook VM sûr](./ops/agentium-safe-vm-deployment.md), qui inclut SFTP, les
> attestations de stockage et le rollback v3.

Date du candidat : 2026-07-15
Branche de travail : `codex/agentium-lot-5` ; branche VM : `demo/agentic`
Révision de départ : `349ee3c19a4f1e8dec7f9fa9f47e25a298863d28`

Le lot 5 transforme les conventions de workspace en contrats vérifiables. Il
ne change pas les URLs métier ni l'expérience visible du lot 4.

## 1. Workspace Blueprint v2

Le schéma v2 exporte et applique la projection positive-allowlistée de
l'expérience workspace : mode, family/profile, features, navigation, shell,
assistants, scopes Knowledge, actions et extension Mission Room avec ses
dépendances déclaratives.

Les garanties bloquantes sont les suivantes :

- `workspace.settings` brut est interdit dans un v2 ;
- les clés ressemblant à des credentials sont filtrées à l'export et rejetées
  à l'import dans tous les champs de configuration portables, y compris les
  indirections `name|key|header|variable` + `value` ;
- les états runtime, marqueurs de migration et connecteurs privés ne sont pas
  portables ;
- un apply v2 exige le `plan_token` d'un dry-run lié au Blueprint, au workspace
  cible, à son état pertinent et aux choix opérateur ;
- l'autorité admin est relue sous le verrou du workspace avant le recalcul du
  plan, de sorte qu'une rétrogradation concurrente annule l'apply ;
- `preserve_target`, `merge_missing` et `replace_portable` ont des sémantiques
  explicites et diffables ;
- les imports v1 restent acceptés, mais leur mode et leurs settings historiques
  sont listés comme ignorés et ne gagnent jamais implicitement la sémantique
  v2 ;
- l'enforcement des applications n'est activé qu'après backfill et contrôle de
  couverture de tous les membres existants, dans la transaction d'apply.

Le même mutex de ligne workspace sérialise maintenant Blueprint, IAM,
invitations/seeds et tous les writers identifiés de `workspace.settings`. Le
PATCH workspace générique recharge l'autorité sous ce verrou et ne peut ni
basculer `app_entitlements_v1`, ni changer la family du resolver, ni supprimer
le marqueur de migration 058 ; ces transitions appartiennent aux workflows
gouvernés qui savent appliquer leurs backfills et invariants.

Contrat détaillé : [`workspace-blueprints.md`](./workspace-blueprints.md).

## 2. Contrats canoniques et dette de slug

Les valeurs partagées proviennent désormais de contrats enum :

| Contrat | Valeurs |
|---|---|
| Workspace mode | `builder`, `operator`, `executive`, `demo`, `portfolio` |
| Workspace family | `andritz`, `industrial`, `sentinel_ci`, `generic` |
| System status | `draft`, `active`, `paused`, `retired` |
| Execution mode | `real_time_decision`, `batch_processing`, `event_driven_automation`, `continuous_monitoring`, `human_augmented` |
| Workspace app | `chat`, `client360-pdr`, `knowledge-capture` |
| Action pack | les six IDs du registre `ActionPack` |

Les schémas API valident ces valeurs avant écriture et les colonnes relationnelles
concernées reçoivent un `CHECK` en base. `portfolio` et `demo` restent des modes
persistés valides mais ne sont pas proposés dans le sélecteur utilisateur.

La résolution runtime de `settings.family` est fail-safe `generic`; elle ne
déduit plus une spécialisation métier du slug ou du nom. La migration 058
matérialise une seule fois le comportement legacy avant ce retrait. Le registry
d'actions et l'extension Mission Room utilisent ensuite la configuration
canonique.

Les branches de slug résiduelles ne sont pas déclarées « disparues ». Elles
sont inventoriées dans le manifeste de conformité avec leur expression,
catégorie et justification. Le générateur échoue à la fois lorsqu'une nouvelle
branche apparaît sans déclaration et lorsqu'une exception déclarée devient
obsolète. Alembic, `backend/scripts`, `backend/app/cli`, les tests et les specs
frontend sont exclus ; les bootstraps exécutables sous `backend/app/services`
restent volontairement scannés comme du code runtime.

## 3. Documentation Andritz

La documentation d'introduction distingue maintenant :

- deux lignées métier historiques ;
- cinq Systems actifs dans le workspace réel ;
- trois applications visibles : Research, Client360 PDR et Knowledge Capture.

Référence :
[`agentium-andritz-intro-agent-tiers.md`](./agentium-andritz-intro-agent-tiers.md).

## 4. Conformité générée

`config/agentium/product-compliance.v1.json` est le manifeste sans état manuel.
`python3 scripts/agentium_compliance.py` génère :

- [`agentium-compliance-matrix.md`](./agentium-compliance-matrix.md) ;
- le bloc de conformité de [`mental-model.md`](./mental-model.md).

Le modèle sépare les preuves des états formels :

1. `planned` ou `partial` selon les preuves inspectables présentes ;
2. `static_verified` lorsque toutes les familles de preuves et contrats de test
   requis sont présents dans le dépôt ;
3. les JSON de runner et de déploiement sont enregistrés comme preuves externes
   non fiables, liées à un SHA, mais ne peuvent jamais produire eux-mêmes
   `runner_verified`, `shipped` ou `deployed` ;
4. la promotion formelle reste désactivée jusqu'à ce qu'un collecteur CI
   authentifié dérive la couverture depuis l'identité immuable des jobs et leurs
   artefacts, sans accepter de claims déclaratifs.

Un fichier de test présent ne prouve donc jamais à lui seul qu'il a été
exécuté. Un JSON local complet ne le prouve pas davantage et ne peut pas
s'auto-promouvoir. Les badges formels `Shipped` écrits manuellement dans le
mental model sont rejetés. Un rapport lié à un SHA exige `HEAD` exact,
`CI_COMMIT_SHA` identique lorsqu'il existe et un worktree intégralement propre.
Le contrôle s'exécute en pre-commit, dans GitLab CI et, après le checkout
immuable, avant tout build/activation VM.

## 5. Préflight VM du 15 juillet 2026

Audit en lecture seule sur le SHA de départ :

| Vérification | Résultat |
|---|---|
| Git VM | `demo/agentic` à `349ee3c19a4f1e8dec7f9fa9f47e25a298863d28`, seulement `uvicorn.log` non suivi |
| Alembic | `057_app_entitlements` |
| Workspace modes | builder 1, demo 2, executive 12, portfolio 1 |
| System statuses | active 83, draft 4, retired 7 |
| Execution modes | batch 1, continuous 25, human augmented 35, real-time decision 33 |
| App entitlements | 6 grants pour chacune des trois apps canoniques |
| Families | andritz 1, sentinel_ci 1, generic 12, absente 2 |
| Action packs | uniquement les cinq packs déjà explicites Sentinel/Octocity ; Andritz encore implicite |

La migration doit donc stamper les deux workspaces personnels sans family en
`generic` et ajouter `andritz_industrial_v1` à Andritz. Aucun alias de statut,
mode d'exécution ou app key hors contrat n'a besoin d'être réécrit sur la VM.

## 6. Migration 058 et rollout

`058_canonical_contracts` :

1. verrouille les lignes workspace et snapshotte l'état précédent dans un
   marqueur versionné ;
2. stampe une family canonique pour chaque workspace et matérialise le pack
   Andritz ;
3. normalise uniquement les alias historiques explicitement prévus ;
4. audite toutes les valeurs avant d'installer les contraintes ;
5. refuse les packs inconnus, les identifiants avec whitespace et les doublons
   au lieu de les convertir silencieusement ;
6. restaure au downgrade les valeurs snapshotées tant qu'elles n'ont pas été
   modifiées après migration.

Le rollout reprend le protocole quiescé du lot 4 :

1. commit propre, tests sur le SHA exact, push sans force du même SHA vers la
   branche de travail puis `demo/agentic` ;
2. audit de dérive VM et sauvegarde PostgreSQL vérifiée ;
3. `deploy-vm.sh --build-only` avec enregistrement du rollback ;
4. arrêt avec drain du backend et du worker susceptibles d'écrire ;
5. `alembic upgrade head` avec l'image candidate, puis lecture indépendante de
   `alembic_version` et des contraintes/backfills ;
6. `deploy-vm.sh --activate-only` sur les images déjà construites ;
7. health checks, audit de dérive, canaries workspace séparés et rapport de
   conformité SHA-bound.

Le backend précédent ne doit pas être redémarré après le commit de 058 sans un
downgrade contrôlé ou une restauration de la sauvegarde.

### Commandes opératoires

Sur la VM, avec le SHA candidat déjà poussé :

```bash
cd /home/ubuntu/omnirag
PREVIOUS_SHA="$(git rev-parse HEAD)"
SHA="<sha-candidat-complet>"
BACKUP="$HOME/agentium-before-058-$(date -u +%Y%m%dT%H%M%SZ).dump"

docker exec agentium-pg pg_dump -U agentium -d agentium -Fc > "$BACKUP"
pg_restore --list "$BACKUP" >/dev/null

bash scripts/deploy-vm.sh \
  --branch demo/agentic \
  --sha "$SHA" \
  --previous-sha "$PREVIOUS_SHA" \
  --build-only
ROLLBACK_STATE="$HOME/.local/state/agentium/deployments/${SHA}.tsv"
```

Le fichier de rollback est en format 2 : il fige les IDs d'images, les deux
SHA Git et la révision Alembic précédente. Ensuite seulement, mettre les
writers en quiescence et migrer avec l'image candidate déjà construite :

```bash
cd /home/ubuntu/omnirag/docker
export AGENTIUM_ENV_FILE=./env/agentium.vm.env
export AGENTIUM_POSTGRES_PASSWORD="$(awk -F= '$1 == "AGENTIUM_POSTGRES_PASSWORD" {sub(/^[^=]*=/, ""); print; exit}' "$AGENTIUM_ENV_FILE")"

docker compose --env-file "$AGENTIUM_ENV_FILE" -f compose.agentium.yml \
  stop agentium-backend agentium-worker-cpu
docker compose --profile tools --env-file "$AGENTIUM_ENV_FILE" \
  -f compose.agentium.yml run --rm --no-deps agentium-migrate \
  alembic upgrade head
```

Contrôler via PostgreSQL, indépendamment de la sortie Alembic, avant
l'activation :

```bash
test "$(docker exec agentium-pg psql -U agentium -d agentium -Atqc \
  'SELECT version_num FROM alembic_version')" = "058_canonical_contracts"

test "$(docker exec agentium-pg psql -U agentium -d agentium -Atqc \
  "SELECT count(*) FROM pg_constraint WHERE conname IN \
  ('ck_workspaces_mode','ck_systems_status','ck_systems_execution_mode',\
   'ck_workspace_member_app_entitlements_app_key')")" = "4"

test "$(docker exec agentium-pg psql -U agentium -d agentium -Atqc \
  "SELECT count(*) FROM workspaces WHERE slug='andritz' \
   AND settings::jsonb #> '{actions,enabled_packs}' \
       ? 'andritz_industrial_v1'")" = "1"

cd /home/ubuntu/omnirag
bash scripts/deploy-vm.sh \
  --branch demo/agentic \
  --sha "$SHA" \
  --previous-sha "$PREVIOUS_SHA" \
  --activate-only
```

En cas d'échec après migration, ne jamais restaurer d'abord les anciennes
images. Garder les writers arrêtés, downgrader avec l'image candidate, vérifier
la révision, puis seulement consommer l'état de rollback :

```bash
cd /home/ubuntu/omnirag/docker
docker compose --env-file "$AGENTIUM_ENV_FILE" -f compose.agentium.yml \
  stop agentium-backend agentium-worker-cpu
docker compose --profile tools --env-file "$AGENTIUM_ENV_FILE" \
  -f compose.agentium.yml run --rm --no-deps agentium-migrate \
  alembic downgrade 057_app_entitlements
test "$(docker exec agentium-pg psql -U agentium -d agentium -Atqc \
  'SELECT version_num FROM alembic_version')" = "057_app_entitlements"

cd /home/ubuntu/omnirag
bash scripts/deploy-vm.sh --rollback-state "$ROLLBACK_STATE"
```

Le script refuse désormais ce dernier appel tant que la révision DB ne
correspond pas à celle enregistrée. Si le downgrade refuse une donnée modifiée
après 058, conserver les writers arrêtés et restaurer le dump vérifié selon la
procédure PostgreSQL, puis contrôler `alembic_version` avant de relancer le
rollback des images.
