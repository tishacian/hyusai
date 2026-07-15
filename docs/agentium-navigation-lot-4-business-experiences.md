# Agentium — Lot 4 : expériences métier et extensions workspace

Date du candidat : 2026-07-15
Branche de travail : `codex/agentium-lot-4` ; branche VM : `demo/agentic`
Statut : implémenté et validé localement ; rollout live à exécuter par SHA
immuable après le checkpoint Git.

Ce lot promeut le resolver V2 derrière feature flag pour Andritz, extrait
Mission Room comme extension de workspace et introduit des entitlements
d'application explicites. Il ne change ni les trois URLs métier, ni leurs
préfixes d'API.

## 1. Contrats conservés

| Application Andritz | URL publique | API existante | entitlement |
| --- | --- | --- | --- |
| Recherche | `/chat` | `/api/v1/chat/**`, `/api/v1/sessions/**` | `chat` |
| Client360 PDR | `/client360` | `/api/v1/client360/**` | `client360-pdr` |
| Capture de connaissances | `/knowledge/capture` | `/api/v1/knowledge-capture/**` | `knowledge-capture` |

L'ordre du header reste Recherche, Client360 PDR, Capture de connaissances.
Quand `app_entitlements_v1` est absent ou faux, le contrat legacy conserve ces
trois liens, même si une ancienne configuration `primary_surfaces` est
partielle. Le filtrage n'existe que sous le flag.

`NavigationResolverService` reste l'unique propriétaire des redirections. Sous
`workspace_experience_v2`, il exécute la projection V2 ; il ne délègue aucune
décision à un shell ou à un composant métier. Un deep-link Mission Room dans
Andritz aboutit directement à la surface métier autorisée, sans redirection
intermédiaire.

## 2. Canary Showcase auto-découvrant

Le premier scénario de `10-cockpit-axes-canary.spec.ts` ne connaît plus de slug
de Capability. Il charge les Systems et Capabilities réels du workspace,
trouve une arête `Capability → System` traversable, puis sélectionne un Run de
ce System. Il fonctionne donc avec le graphe actuel
`video_contract_risk` et ne référence plus `showcase_contract_risk`.

La découverte échoue explicitement si aucun graphe réel traversable n'existe ;
elle ne remplace jamais ce manque par un identifiant synthétique.

## 3. Entitlements Andritz

### Modèle et enforcement

`workspace_member_app_entitlements` porte une ligne par membership et par app.
La contrainte unique est `(workspace_member_id, app_key)` et la suppression
d'une membership cascade sur ses grants.

Quand `app_entitlements_v1=true` :

- l'absence de ligne refuse l'app, y compris pour un admin ;
- les routers Chat/Sessions, Client360 et Knowledge Capture contrôlent leur clé
  avant les règles IAM internes ;
- les payloads workspace, membres et IAM exposent les clés dans l'ordre
  canonique ;
- une invitation doit fournir une liste explicite, sinon l'API répond
  `APP_ENTITLEMENTS_REQUIRED` avant toute création Keycloak ou membership ;
- l'UI d'invitation envoie explicitement les trois apps cochées par défaut et
  la console IAM permet de les modifier pour les membres administrables.

Quand le flag est absent ou faux, le dependency est un vrai no-op : il ne
charge même pas la membership et préserve les tests/clients historiques.

### Migration et backfill

La migration `057_app_entitlements` :

1. crée la table et ses index ;
2. sous PostgreSQL, prend un lock `SHARE` sur `workspace_members` avec timeout,
   puis verrouille la ligne Andritz par `FOR UPDATE` ;
3. sélectionne le workspace par `slug='andritz'` ;
4. insère les trois grants pour **chaque** `workspace_members.id` présent ;
5. vérifie à la fois `grants = membres × 3` et un anti-join sans grant manquant ;
6. active seulement ensuite `app_entitlements_v1` et
   `workspace_experience_v2`, dans la même transaction.

Elle ne contient aucun email ni ID de membre. Un marqueur versionné mémorise
pour les deux flags l'état exact `absent`, `false` ou `true`. Le downgrade
restaure cet état, préserve les autres settings ajoutés après migration et
retire le marqueur.

Préflight PostgreSQL :

```sql
SELECT w.id, w.slug, count(wm.id) AS members,
       count(wm.id) * 3 AS expected_grants
FROM workspaces w
LEFT JOIN workspace_members wm ON wm.workspace_id = w.id
WHERE w.slug = 'andritz'
GROUP BY w.id, w.slug;
```

Vérification post-migration :

```sql
SELECT count(*) AS grants
FROM workspace_member_app_entitlements e
JOIN workspace_members wm ON wm.id = e.workspace_member_id
JOIN workspaces w ON w.id = wm.workspace_id
WHERE w.slug = 'andritz'
  AND e.app_key IN ('chat', 'client360-pdr', 'knowledge-capture');
```

Le résultat doit être exactement `3 × members`. Vérifier aussi qu'aucune
membership Andritz ne possède moins de trois clés avant le smoke UI.

Gate anti-join bloquant :

```sql
WITH expected(app_key) AS (
  VALUES ('chat'), ('client360-pdr'), ('knowledge-capture')
)
SELECT wm.id, expected.app_key
FROM workspace_members wm
JOIN workspaces w ON w.id = wm.workspace_id
CROSS JOIN expected
LEFT JOIN workspace_member_app_entitlements e
  ON e.workspace_member_id = wm.id
 AND e.app_key = expected.app_key
WHERE w.slug = 'andritz' AND e.id IS NULL;
```

Cette requête doit retourner zéro ligne. Le lock transactionnel ne remplace
pas la quiescence du backend : une requête d'invitation ayant lu l'ancien flag
avant le lock pourrait sinon reprendre après le commit. Le backend reste donc
arrêté entre le drain des anciennes requêtes et l'activation de l'image
candidate.

## 4. Mission Room comme extension

L'extension est activée exclusivement par configuration :

```json
{
  "mission_room": {
    "enabled": true,
    "profile": "sentinel_government_v1"
  }
}
```

Le slug ne décide jamais de la disponibilité. Le registry backend et le
resolver frontend exigent le booléen littéral `true` ; sinon les deep-links
reviennent vers `/hypervisor` et les APIs répondent par un 404 uniforme sans
audit métier.

Le scope fail-closed couvre :

- `/api/v1/mission-room/**` ;
- `/api/v1/mission-room/maritime/**` ;
- `/api/v1/mission-room/webcams/**`, y compris `HEAD /proxy`.

Les URLs restent strictement identiques : parent
`/hypervisor/mission-room`, redirect `cockpit`, routes
`securite/monitor`, `veille-sociale`, `agenda/meeting/:event_id` et `:view`.
Le route table est lazy et passe par un host d'extension. Aucun des composants
métier Mission Room existants n'est modifié.

Le host applique uniquement au sous-arbre de l'extension un adaptateur de
présentation réversible pour les littéraux statiques legacy. Il traite les
text nodes et les attributs accessibles `aria-label`, `aria-description`,
`title`, `placeholder` et `alt`. Les valeurs source sont conservées pour qu'un
switch Octocity → Sentinel restaure le texte d'origine avant le rechargement du
nouveau contexte.

## 5. Vérifications séparées Sentinel et Octocity

### Sentinel

- profile : `sentinel_government_v1` ;
- marque : `SENTINEL-CI` ; assistant : `AYA` ;
- packs exacts : `global_voice_v1`, `sentinel_ci_aya_v1`,
  `sentinel_ci_aya_security_v1` ;
- absence de `Octocity`, `OCTAVE`, `Asteria`, `Meridian`, `Liora` et des alias
  Octave dans le payload effectif et le DOM.

### Octocity

- profile : `octocity_institutional_v1` ;
- marque : `Octocity Mission Room` ; assistant : `OCTAVE` ;
- packs exacts : `global_voice_v1`, `octave_mission_room_v1`,
  `octave_security_v1` ;
- action publique neutre `octave.recommend_diversification`, avec le handler
  legacy conservé uniquement en interne ;
- absence du vocabulaire Sentinel dans les catalogues publics `/effective` et
  `/manifests`, les résultats d'action, le texte DOM et les attributs
  accessibles.

Le contrat Playwright scanne séparément le cockpit Sentinel, puis quatre types
de deep-links Octocity : cockpit, sécurité, veille sociale et réunion agenda.

## 6. Rollout sûr par SHA

1. Partir d'un commit propre et publier atomiquement le **même SHA** sur
   `codex/agentium-lot-4` et `demo/agentic`, sans force. Un avancement
   concurrent de `demo/agentic` doit faire échouer le push.
2. Enregistrer le SHA candidat, le SHA déployé, les IDs d'images et le nombre
   de memberships Andritz. Vérifier le worktree VM ; ne jamais écraser un
   drift.
3. Sauvegarder PostgreSQL en format custom avec permissions privées, vérifier
   que le dump est non vide et que `pg_restore -l` sait le lire.
4. Construire et vérifier les images sans les activer :

   ```bash
   cd /home/ubuntu/omnirag
   test -z "$(git status --porcelain | grep -vE 'uvicorn\.log|\.pyc$')"
   PREVIOUS="$(git rev-parse HEAD)"
   bash scripts/deploy-vm.sh --check-only \
     --branch demo/agentic --sha "$PREVIOUS"
   git fetch origin demo/agentic
   test "$(git rev-parse origin/demo/agentic)" = "$CANDIDATE"
   git reset --hard "$CANDIDATE"
   bash scripts/deploy-vm.sh --build-only \
     --branch demo/agentic --sha "$CANDIDATE" --previous-sha "$PREVIOUS"
   ```

   Ce bootstrap est nécessaire au premier rollout : le script présent sur
   l'ancien SHA ne connaît pas encore les modes `--build-only` et
   `--activate-only`.

5. Ouvrir la courte fenêtre de maintenance en arrêtant le backend avec drain,
   puis lancer 057 avec l'image candidate déjà vérifiée. L'ancien backend ne
   doit jamais être relevé après le commit de 057 :

   ```bash
   cd /home/ubuntu/omnirag/docker
   export AGENTIUM_ENV_FILE=./env/agentium.vm.env
   docker compose --env-file "$AGENTIUM_ENV_FILE" -f compose.agentium.yml \
     stop -t 30 agentium-backend
   docker compose --profile tools --env-file "$AGENTIUM_ENV_FILE" \
     -f compose.agentium.yml run --rm --no-deps agentium-migrate
   ```

   Un code retour non nul ne prouve pas que le commit n'a pas eu lieu (perte de
   connexion juste après `COMMIT`, par exemple). Garder le backend arrêté et
   relire la révision par une connexion PostgreSQL indépendante :

   ```bash
   DB_REVISION="$(docker exec agentium-pg psql -At -v ON_ERROR_STOP=1 \
     -U agentium -d agentium -c 'SELECT version_num FROM alembic_version')"
   printf '%s\n' "$DB_REVISION"
   ```

   `056_andritz_chat_asset_binding` autorise le rollback direct ;
   `057_app_entitlements` impose les gates de l'étape 6 puis le chemin
   « migration commitée ». Toute autre valeur, plusieurs lignes ou une lecture
   impossible maintient la maintenance jusqu'au diagnostic/restauration DB.

6. Backend toujours arrêté, vérifier Alembic `057_app_entitlements`,
   l'anti-join à zéro, `3 × members`, les deux flags strictement `true` et zéro
   grant de backfill hors Andritz.
7. Activer sans rebuild exactement les images déjà contrôlées :

   ```bash
   cd /home/ubuntu/omnirag
   bash scripts/deploy-vm.sh --activate-only \
     --branch demo/agentic --sha "$CANDIDATE" --previous-sha "$PREVIOUS"
   ```

   `--activate-only` exécute un gate supplémentaire avant `compose up` : les
   révisions renvoyées par `alembic current` doivent être exactement celles de
   `alembic heads` dans l'image candidate. Le mode one-shot échoue lui aussi si
   une migration est pendante ; il ne peut donc pas contourner 057.

8. Vérifier santé interne/publique et qu'une invitation Andritz sans décision
   explicite d'apps échoue en 422 avant toute mutation.
9. Smoke Andritz : trois URLs/APIs, reload/deep-link/history et grants de tous
   les membres. Passer le count du préflight via
   `E2E_EXPECTED_ANDRITZ_MEMBERS` ; le test exige trois clés par membre et
   `total = members × 3`.
10. Exécuter le Showcase auto-découvrant, puis Sentinel et Octocity
    séparément. Conserver le checkout au SHA candidat jusqu'à la fin des
    canaries et archiver les preuves avec le SHA.

Les garde-fous généraux de `docs/ops/navigation-lot-0-rollout.md` restent
applicables au worktree et aux images, mais Lot 4 n'utilise aucun état de seed
Octocity. Son rollback autonome est défini ci-dessous.

### Rollback

État d'images créé avant le build :

```bash
STATE="$HOME/.local/state/agentium/deployments/${CANDIDATE}.tsv"
test -s "$STATE"
```

Après un échec du processus de migration, restaurer directement les images et
le checkout précédent **uniquement** si la lecture indépendante ci-dessus
confirme `056_andritz_chat_asset_binding`. Le script sait recréer le backend
arrêté :

```bash
cd /home/ubuntu/omnirag
bash scripts/deploy-vm.sh --branch demo/agentic --rollback-state "$STATE"
```

Si 057 a commité, ou si l'activation/le smoke échoue ensuite :

1. mettre immédiatement `app_entitlements_v1=false` et
   `workspace_experience_v2=false` sur Andritz avec une mise à jour JSONB qui
   préserve le marqueur et tous les autres settings ;
2. exécuter la même commande `--rollback-state "$STATE"` ;
3. confirmer que les trois surfaces legacy sont revenues ;
4. laisser de préférence la table additive en place : le code précédent
   l'ignore. Si un downgrade complet est imposé, l'exécuter sous quiescence
   **avec l'image candidate avant** de restaurer les anciennes images. Le
   marqueur restaure les valeurs préexistantes des flags. Le downgrade refuse
   de supprimer la table si le marqueur Andritz manque ou si des grants
   post-migration/hors Andritz existent ; les exporter et décider explicitement
   de leur traitement au lieu de les perdre.

Désactivation non destructive des deux flags :

```bash
docker exec agentium-pg psql -v ON_ERROR_STOP=1 -U agentium -d agentium -c "
UPDATE workspaces
SET settings = jsonb_set(
  jsonb_set(settings::jsonb, '{features,app_entitlements_v1}', 'false'::jsonb, true),
  '{features,workspace_experience_v2}', 'false'::jsonb, true
)
WHERE slug = 'andritz';"
```

Ne jamais supprimer manuellement les grants avant le downgrade et ne jamais
rejouer un seed Mission Room isolé pendant un rollback.

## 7. Preuves locales

```text
Frontend unit : 267 passed
Angular production build : success
Playwright contract loading : 12 tests listed
Backend integrated Lot 4 : 256 passed
Migration 057 isolated contract : 6 passed
Backend large local : 1640 passed, 3 skipped ; 18 intégrations Qdrant non marquées indisponibles localement
```

Commandes principales :

```bash
cd frontend-ng
npm run test:unit
node node_modules/@angular/cli/bin/ng.js build --configuration production --progress=false
node node_modules/@playwright/test/cli.js test \
  e2e/tests/09-live-workspace-contract.spec.ts \
  e2e/tests/10-cockpit-axes-canary.spec.ts --list
```

Le canary live utilise uniquement `E2E_USERNAME` et `E2E_PASSWORD` fournis par
l'environnement. Traces, vidéos et screenshots Playwright restent désactivés
pour ne jamais sérialiser les credentials.
