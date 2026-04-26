# Agentium — Plan Vague E

## Objet du document

Vague E prend le relais de
[`vague-d-plan.md`](./vague-d-plan.md) une fois Vague D CLOSED
(2026-04-22) et la rafale post-D7 hardening stabilisée (2026-04-23).
Le produit est désormais démo-ready pour un client seul ; Vague E vise
le passage à **démo-ready pour plusieurs clients simultanés**, avec la
preuve que le cockpit ferme la boucle (retour d'évaluation →
suggestion → action) au lieu d'être un runner de runs passif.

Invariants et contrat d'arbitrage identiques à Vague D (cf. §15–19 de
vague-d-plan) :
- [Mental model](./mental-model.md) = source normative sémantique
- [Deck produit](./deck-product-review.md) = source normative d'intention
- [Mockups](./mockups) = source normative visuelle

## Contexte — d'où vient Vague E

Trois signaux poussent à ouvrir une Vague E maintenant :

1. **Retour démo (utilisation réelle 23 avril)** — la journée a produit
   ~30 commits de fit-and-finish (citations cliquables, dedup sources,
   page mapping PDF, voice sentence-streaming, pause/resume, KC
   hardening…). Aucun de ces items n'est "Vague E" au sens feature,
   mais ils ont révélé les vrais blockers d'un usage quotidien :
   a) la sécurité reste en `admin/admin` tant qu'on n'a pas forcé la
   rotation à l'échelle de l'infra ; b) le cockpit sait scorer une
   réponse (HHEM, adv_hhem, eval expandable) mais ne fait rien de ce
   score — pas de boucle d'évaluation fermée ; c) l'isolation
   Keycloak est en place mais il manque la couche UX qui rend le
   multi-tenant visible pour un opérateur.

2. **Backlog explicite de Vague D** — section "Hors Vague D" du plan
   précédent listait : boucle d'évaluation, recommandations proactives,
   marketplace, simulation offline, SharePoint v1, custom chains
   editor, voice end-to-end. Le point voice est largement livré dans la
   rafale du 23/04, les autres restent ouverts.

3. **Dette test** — Playwright E2E a été reporté de D6 à "Vague E+"
   parce que la stack complète (Keycloak, Qdrant, Postgres) n'était pas
   disponible en dev local. Elle l'est maintenant sur la VM, donc il
   est temps.

## Invariants à préserver

- Rien ne casse sur `agentium.papai.ai` (les 28 PASS du smoke D7
  restent 28 PASS).
- `admin/admin` disparaît **avant** toute ouverture à un nouveau
  client. E0 est P0 bloquant : pas de E1..E7 avant qu'il soit done.
- Le run engine (DAG walker + sequential) reste inchangé sur son
  comportement observable, comme en Vague D. Vague E ajoute des
  consommateurs d'events (eval loop) mais ne réécrit pas d'exécuteur.
- L'isolation multi-tenant (test_tenant_isolation.sh = 0 FAIL) reste
  une invariante testée en CI ; tout nouvel endpoint passe par
  `get_current_workspace` ou refuse l'appel.

## Plan chiffré — E0 → E7

| # | Titre | Priorité | Taille | Dépend de |
| - | ----- | -------- | ------ | --------- |
| **E0** | **Security hardening — rotation secrets (KC admin, KC client_secret, PG), DKIM activation, secret manager** | **P0** | **M** | — |
| E1 | Boucle d'évaluation — scoring auto post-run + threshold triggers + suggestion UI. **E1 v1 fermé 2026-04-25**, **E1.5 CLOSED 2026-04-25 : boucle game-changer actionnable.** E1.5.1 livré (feedback signal : table `evaluation_feedback`, `accept`/`reject` write feedback, `GET /evaluation/feedback`). E1.5.2 livré (`POST /runs/{id}/replay`, `GET /runs/{id}/replays`, lineage `parent_run_id`/`replay_overrides`, bouton **RE-RUN** review queue, smoke 8/8 VM). E1.5.3 livré (taxonomie Giskard/RAGET native, `question_type`/`failed_components`/`topic`, `GET /evaluation/component-health`, filtre `review-queue?component=`, widget Quality, extra offline `giskard[llm]`, smoke 5/5 + spike RAGET OK avec ≥8 chunks). E1.5.4 livré (auto-onboard preset `enabled=true`, `composite_min=70`, migration `019_eval_default_onboard`, opt-out `/presets/evaluation`). E1.5.5 livré (migration `020_canonical_answers`, `CanonicalAnswer` Dify-style annotation reply, `GET/POST /evaluation/canonical-answers`, chat canonical hit bypass orchestrator, active suggestions LLM/fallback sur Decisions, bouton **APPLY** qui lance un replay avec overrides et marque la Decision applied, smoke VM 3/3, frontend build/deploy VM OK). | ✅ | L | D2, D6 |
| E2 | Playwright E2E — **livré 2026-04-25** : 7 tests VM / 5 flows (auth backend+session+invalid creds, chat drop-and-ask PDF→citation→sources, HITL approve auto-seeded, debug step/continue auto-seeded, E1.5 canonical-answer deterministic hit). `@playwright/test` ajouté en devDep, Chromium installé sur VM, fixtures PDF/systems générées dynamiquement, `workers=1` pour VM partagée. Run VM : `7 passed (20.0s)`. | ✅ | M | D1, D7 |
| E3 | Custom chains editor — finition (node props, validation, save/load versions). **E3.1 backend livré 2026-04-24** (table `system_versions` + rolling window 500 via `CUSTOM_CHAIN_VERSION_WINDOW`, DAG validator gate `PATCH /systems`, routes `/versions` + `/rollback`, audits `chain.*`). **E3.2 UI versioning + rollback + save gate livré 2026-04-24** (`saveSystemFlow` discriminated-union wrapper, panneau Versions droit, modal de rollback, issues serveur spliced dans la strip). **E3.3 node-props kind-specific livré 2026-04-24** (decision/fork/join/loop/retry/HITL/subflow éditeurs + task params rendus depuis `Skill.input_schema`, label éditable, helper `patchSelectedConfig`). **E3.4 export/import JSON livré 2026-04-24** (`GET /systems/{id}/export` envelope canonique, `POST /systems/import` avec re-binding par skill_slug + fallback gracieux, UI download + upload modal avec report). **E3 CLOSED.** | ✅ | L | C6 |
| E4 | SharePoint ingestion v1 — deux connecteurs jumeaux partageant la même sync pipeline : **E4a SharePoint** (OAuth/MSAL standard, cas majoritaire) + **E4b SharePoint Guest Link** (capture session via Agentium Connector local, cas d'accès limité type Andritz). Fondation E4b livrée (`671a3a4`→`df4cf80`), **E4.1 scope commun livré 2026-04-24** (UI dédiée `/connectors/sharepoint`, ingestion RAG via `DocumentService`, audits `sharepoint.session.*` + `sharepoint.sync.*`, migration catch-up `workspace_id`). **E4.2 différé 2026-04-25** (release engineering, pas un blocker démo, voir Journal pour le backlog détaillé). Reste E4.3 OAuth UI (E4a, dépend admin consent). | P1 | L | D0 |
| E5 | Recommandations proactives — Decision générée depuis l'analyse agrégée multi-runs | P2 | L | E1 |
| E6 | Simulation offline — rejouer un run sur une policy alternative | P3 | M | C6 |
| E7 | Deploy + smoke Vague E | P0 | S | E0..E6 |

Taille : S ≈ ½ journée, M ≈ 1 à 2 jours, L ≈ 3 à 5 jours.

### E0 — Security hardening

**Pourquoi P0 bloquant.** Tant que `admin/admin` est accepté sur
Keycloak master, tant que `keycloak_client_secret` et le password PG
n'ont pas été rotatés depuis la copie initiale d'env, et tant que les
emails partent sans DKIM, on ne peut pas ouvrir Agentium à un client
externe sans prendre un risque de compliance.

**Scope :**

1. **Finaliser rotation KC admin** (amorcée en rafale post-D7) —
   exécution de `rotate-keycloak-admin.sh --disable-bootstrap`,
   documentation du nouveau compte dans le secret manager choisi
   (1Password / Vault / Bitwarden — décision hors agent).
2. **Rotation `KEYCLOAK_CLIENT_SECRET`** du client confidentiel
   `core-resource-server` — l'actuel a été copié depuis le bootstrap
   initial et apparaît dans `.env` sur la VM. Générer un nouveau, le
   pousser dans Keycloak (client credentials regenerate), mettre à
   jour `/home/ubuntu/omnirag/backend/.env`, bouncer le backend,
   vérifier que le flow login `/api/v1/auth/login` reste green.
3. **Rotation password PG `agentium`** — idem, regenerate,
   update `keycloak.env` + `backend/.env`, bounce les deux containers.
4. **Activer DKIM OVH** — cf. `docs/ops/email-deliverability.md` :
   générer clé via OVH Manager, publier enregistrement DNS TXT,
   attendre propagation, re-tester `testSMTPConnection` + un envoi
   réel vers Gmail pour vérifier l'alignement DKIM/DMARC (`mail-tester`
   ou équivalent).
5. **Secret manager opérationnel** — choisir 1Password vs Bitwarden vs
   Vault (décision utilisateur), importer les secrets rotatés
   (tib-admin, client_secret, PG, SMTP), documenter le run-book d'accès
   dans `docs/ops/secrets.md`. Idéalement un coffre partagé pour la
   team avec rotation 90j planifiée.

**Done quand :**
- `admin/admin` ne passe plus (assertion dans smoke : POST
  `/realms/master/.../token` avec `username=admin, password=admin`
  retourne 401 invalid_grant).
- Le client secret actuel (celui qui était en `.env` depuis Vague D)
  ne permet plus d'obtenir un token — il a été révoqué côté KC.
- Un email envoyé depuis `noreply@datategy.net` passe le check
  `mail-tester` à ≥ 8/10 avec DKIM = ✔.
- `docs/ops/secrets.md` existe et référence l'endroit réel où vivent
  les secrets (pas le repo).

### E1 — Boucle d'évaluation

**Contrat produit.** Aujourd'hui le cockpit **scorer** des réponses
(HHEM, adv_hhem, faithfulness, relevance) via le panneau eval
expandable livré en post-D7. Vague E ferme la boucle : le score
déclenche une **action** au lieu de juste s'afficher.

**Spécifications :**

1. **Scoring automatique post-run** — quand un `Run.status ==
   "completed"` est produit par un system avec `capability.eval_enabled
   = True`, un job async lance les évaluateurs (HHEM / adv_hhem /
   faithfulness) et écrit le résultat dans `Run.evaluation_scores`
   (nouveau champ JSON). Pas de changement sur `execute_run` : c'est un
   consommateur d'event (`run_end` du bus) qui scorre en arrière-plan.

2. **Threshold config par workspace** — nouveau preset
   `EvaluationPreset` : `{hhem_min: 0.3, adv_hhem_min: 0.1,
   faithfulness_min: 0.7}` modifiable dans `/settings/evaluation`.

3. **Triggers** — quand un `Run.evaluation_scores` passe sous seuil,
   on crée :
   - Un `Decision` de type `review_required` (visible dans le panneau
     Steer) avec le payload du run + suggestion de re-prompt.
   - Un toast côté builder "⚠ Reply scored below threshold — open
     in Steer" avec deeplink.

4. **Suggestion UI** — dans `/steer`, un onglet "Review queue" liste
   les runs bas-score triés par urgence, chacun avec actions : "Mark
   as false positive", "Re-run with override", "Invalidate response".

5. **Métriques agrégées** — dashboard `/observability` gagne un
   widget "Eval trend 7d" : % runs au-dessus/dessous de chaque seuil,
   par capability. Base pour E5.

**Done quand :**
- Un run complet déclenche un job eval dans < 500 ms (observable
  via SSE `evaluation_complete`).
- Un run dont HHEM est < 0.3 apparaît dans la queue Steer, avec les
  actions fonctionnelles.
- Le widget "Eval trend 7d" reflète les scores passés.

**Statut (2026-04-25) : ✅ FERMÉ.** Migration 012 +
`_persist_chat_run` + SSE `eval_pending` + `GET /evaluation/by-run`
+ toast ngx-toastr avec deeplink `/steering/review-queue?decision=…`
livrés. Smoke VM validé — chat → Run → `schedule_eval` → judge →
Decision → toast reviewer. Isolation multi-tenant testée
(cross-workspace → 404, pas de leak). Voir journal 2026-04-25
pour le détail.

### E2 — Playwright E2E

Reporté de D6 (cf. note `backlog Playwright` du vague-d-plan). Stack
VM disponible, donc finissable maintenant.

**Scope livré (5 flows / 7 tests) :**

1. **Auth** — login direct access grant alice → landing workspace,
   session reload, invalid creds 401.
2. **Chat drop-and-ask** — drop 2 PDF → citation `[1]` cliquable →
   scroll to source.
3. **HITL Approve** — fixture system auto-seedée → run `hitl_pending`
   → accept via API auth → resume → completed.
4. **Debug Step/Continue** — run en mode debug → step skill → continue
   → outcome affiché.
5. **E1.5 canonical answer** — crée une canonical answer → chat
   completion hit déterministe → `hit_count` incrémenté.

Les PDFs + systèmes HITL/debug sont générés dynamiquement par les specs
pour éviter un script seed séparé. Exécution contre VM staging partagée,
`workers=1` pour éviter les grants Keycloak concurrents.

**Done :** `E2E_BASE_URL=https://agentium.papai.ai npx playwright test
--project=chromium --reporter=list` → `7 passed (20.0s)` sur VM.

### E3 — Custom chains editor — finition

Le scaffold existe dans `/orchestration` (`workflow-editor.component`),
mais :
- Les node-props (skill picker, param forms) sont placeholders.
- Pas de validation `fork/join` cohérents.
- Pas de versioning des flows sauvés (save écrase, pas de diff).

**Audit 2026-04-24 — état des lieux réel** (à partir des subagents
`explore` backend + frontend, 2110 lignes de `workflow-editor` lues) :

- **Backend** : aucune table `system_versions`, `chains` ou
  `workflows`. Les chaînes vivent comme `systems.flow_definition`
  (JSON) mutée en place par `PATCH /api/v1/systems/{id}`. **Aucun
  historique**, aucun rollback possible.
- **Run ↔ version** : `Run.system_id` seul, **pas** de snapshot DAG
  inline. Les runs relisent `system.flow_definition` à l'exécution
  (`run_engine/dag.py:266-271`). Muter une chaîne après un run rend
  le replay de ce run silencieusement incorrect.
- **Validation** : `validateFlow` existe côté front
  (`core/flow-serializer.service.ts:681-799`), mais (a) `save` n'est
  jamais gaté dessus — seul `execute` l'est, (b) deux types d'issues
  sont déclarés (`unreachable_node`, `port_type_mismatch`) mais
  **jamais émis**, (c) zéro validation côté backend — `PATCH` accepte
  n'importe quel `flow_definition`.
- **Node-props** : seul le skill picker est réel (task nodes).
  Pour decision/fork/join/loop/retry/hitl/subflow, l'inspecteur
  affiche `configSummary()` en **read-only**. Les nouveaux nodes
  sortent avec `config: {}` → validation errors indébloquables.
- **Export/import** : zéro UI, pas de route backend dédiée.
- **Audit events** : aucun `chain.*` / `workflow.*` émis aujourd'hui.

**Scope (décomposé en tranches livrables indépendamment) :**

- **E3.1 — Fondations backend versioning + validation** : table
  `system_versions` (FK `systems.id`, `workspace_id`, `version_number`
  auto-incrémenté par système, `flow_definition` JSON, `created_at`,
  `created_by`, `message`), colonne `runs.flow_snapshot` JSON pour
  garder les runs rejouables après purge d'une version, migration
  Alembic, rolling window 500 via `CUSTOM_CHAIN_VERSION_WINDOW` (purge
  FIFO à chaque nouvelle version), service de validation DAG partagé
  avec le front (cycle, decision sans ≥2 branches, fork sans join,
  node orphelin, edge vers node inexistant, unreachable_node,
  task sans skill), intégration dans `PATCH /systems/{id}` pour
  bloquer les saves invalides (400 structuré), nouvelles routes
  `GET /systems/{id}/versions`, `GET /systems/{id}/versions/{n}`,
  `POST /systems/{id}/versions/{n}/rollback`. Audits
  `chain.version.created`, `chain.rollback`, `chain.version.purged`.

- **E3.2 — UI versioning + rollback** : panneau "Versions" dans le
  `workflow-editor`, liste paginée avec auteur + date + message +
  diff count (node/edge delta vs. courante), bouton "Roll back to"
  qui ouvre un modal de confirmation puis appelle `/rollback` et
  reload la chaîne. Save gate côté UI via la validation serveur
  (affichage structuré des erreurs 400 dans la issues strip).

- **E3.3 — Node-props complets** : formulaires éditables par kind.
  Task : form auto-généré depuis `Skill.input_schema` (ne pas
  réinventer un JSON-schema renderer — récup `ngx-formly` ou un
  petit renderer maison clefs-plates si l'arbo reste simple).
  Decision : éditeur de conditions + true/false branches (picker de
  target node). Fork/join : éditeur de parallelism + strategy.
  Loop : `max_iterations`, break condition. Retry : `max_attempts`,
  backoff. HITL : prompt. Subflow : system picker.

- **E3.4 — Export / import JSON** : `GET /systems/{id}/export`
  serialize flow + `skill_slugs` (pas d'ids cross-workspace),
  `POST /systems/import` re-bind skills par slug dans le workspace
  cible, crée la chaîne + sa version 1. Upload JSON côté UI via
  file picker.

**Ordre d'exécution** : E3.1 → E3.2 → E3.3 → E3.4. E3.1 débloque
tout le reste (le versioning est la fondation).

**Done quand :** un builder peut construire un flow fork/join/decision
depuis zéro, le valider (save bloqué si invalide), le lancer, naviguer
l'historique des versions, rollback à une version antérieure,
l'exporter en JSON, et le réimporter dans un autre workspace — tout
cela sans que la table `system_versions` explose quand on dépasse
les 500 versions par chaîne, et sans que les anciens runs deviennent
orphelins.

### E4 — SharePoint ingestion v1

**Deux connecteurs jumeaux, une pipeline commune.** Les tenants
SharePoint qu'Agentium doit ingérer se répartissent en deux catégories
opérationnelles qu'on traite comme deux connecteurs distincts côté
produit, avec le même backend `/api/v1/sharepoint/*` différencié par
un champ `auth_mode` :

- **E4a — SharePoint** (connecteur standard, `auth_mode="oauth"`). Le
  cas majoritaire : le tenant client enregistre une app Entra ID avec
  permissions déléguées, admin consent accordé. Refresh token géré,
  ingestion continue silencieuse, pas de recapture.
- **E4b — SharePoint Guest Link** (connecteur d'accès limité,
  `auth_mode="guest_link"`). Le cas edge : l'opérateur n'a qu'un
  sharing URL avec code OTP mail + 2FA Authenticator, sans app
  consentée dans le tenant cible (compte invité B2B, `User consent
  disabled`, tenant verrouillé type Andritz, partage externe
  ponctuel). Capture de session via un **Agentium Connector** local
  qui ouvre un Chromium réel, laisse l'opérateur faire son OTP + 2FA,
  extrait le `storage_state` et l'upload chiffré vers Agentium.

**Ce qui est commun** (un seul code, une seule UI) :

- Routes `/api/v1/sharepoint/{sync, sync/{id}, sessions/{key}}` —
  `auth_mode` décide du client à instancier.
- `SharedFolderIngester` (walker + downloader + `SyncManifest`
  incrémental) agnostique de l'auth.
- Chiffrement Fernet au repos (sessions pour E4b, caches MSAL pour
  E4a) via la même infra `crypto.py` (clé dérivée par tenant).
- UI SharePoint unique : à la création d'un connecteur l'opérateur
  choisit "Standard" ou "Guest Link" selon ce que son admin IT
  autorise.
- Ingestion dans le pipeline RAG (Qdrant via
  `DocumentService.ingest_document`) partagée.

**Pivot de parcours — pourquoi E4b a été livré avant E4a.** Le flow
OAuth delegated initialement prévu dans Vague D (`de8bc8b5-...` Graph
Explorer app, puis app dédiée `papAI - SharePoint Reader`) a été
bloqué par la politique Andritz (`AADSTS65001 / Need admin approval`
sur le premier client pilote). Plutôt que de rester suspendu à l'IT
du client, la fondation **Guest Link** a été livrée en parallèle ;
elle débloque Andritz tout de suite et devient la fallback pérenne
pour tout futur client qui aura la même restriction.

#### E4a — SharePoint (standard, OAuth/MSAL)

**Prérequis client :** une app Entra ID enregistrée dans le tenant
du client, permissions déléguées (`Sites.Read.All`, `Files.Read.All`,
`offline_access`, `User.Read`, `AllSites.Read`), admin consent
accordé, ou à défaut `User consent enabled` avec l'utilisateur en
capacité de consentir.

**État :** `SharePointMsalClient` et `SharePointMsalAuth` déjà livrés
dans `671a3a4`, token cache encrypté, refresh silencieux géré, tests
mockés passant (refresh on 401, interactive fallback sur
`SharePointLoginRequired`). Non testé en prod faute de client avec
admin consent à date.

**Scope restant :**

1. Flow OAuth côté frontend : écran "Connect SharePoint (Standard)"
   → redirect Entra ID → callback → token stocké encrypté côté VM →
   `GET /sessions/{key}` retourne "valid".
2. Découverte : liste des sites/libraries accessibles via Graph, UI
   picker au lieu de forcer `folder_server_relative_url` manuel.
3. Sync périodique configurable (cron simple par workspace : daily /
   hourly / on-demand).
4. Premier test en prod : dès qu'un client tiers a une app
   consentée, ou dès qu'Andritz débloque (bascule
   `auth_mode="guest_link"` → `"oauth"` sur le même `session_key`,
   idempotent).

**Done quand :** un workspace admin connecte un SharePoint client
avec une app consentée en < 2 min depuis l'UI, sync tourne en
autonomie, refresh silencieux sur 14 jours sans intervention.

#### E4b — SharePoint Guest Link (accès limité)

**Prérequis client :** un sharing URL (`https://<tenant>.sharepoint.com/:f:/s/.../...?e=xxx`)
pointant vers un dossier explicitement partagé avec l'adresse
Agentium, auth OTP mail + (optionnellement) 2FA Authenticator.
Aucun contact avec l'IT du client côté tenant SharePoint requis.

**État au 2026-04-20 (commits `671a3a4` → `df4cf80`) — déjà livré :**

- `backend/app/services/connectors/sharepoint_otp/` : package
  autonome avec client Playwright capturant le `storage_state` OTP,
  client OAuth `SharePointMsalClient` en miroir (activable via
  `auth_mode='msal'`), ingester incrémental (`SyncManifest` tracke
  `TimeLastModified` + taille pour skip les fichiers inchangés),
  chiffrement Fernet au repos des sessions et caches MSAL (clé
  dérivée par tenant via HKDF depuis une master key).
- Routes `/api/v1/sharepoint/{sync, sync/{id}, sessions/{key}}` —
  scopées au workspace courant (JWT Keycloak +
  `X-Workspace-Slug`), session_key namespacé
  `ws_{workspace_id}__{user_key}` sur disque pour isolation stricte.
  Jobs persistés dans `sharepoint_sync_jobs` (visible multi-worker
  uvicorn) via `BackgroundTasks` — pas de Celery requis.
- Chromium + dépendances système installés sur `omnirag-demo` via
  `playwright install chromium --with-deps`.
- CLI `scripts/sharepoint_connector_demo.py` avec `--force-reauth`
  + `--export-session` : l'opérateur capture sa session localement
  (OTP mail + Authenticator), récupère un JSON prêt à PUT dans
  l'API.
- Tests : 17 unit (crypto roundtrip, manifest incremental, ingester
  mocked, MSAL token refresh sur 401) + 1 smoke integration gated
  par `SHAREPOINT_INTEGRATION_TESTS=1`.
- Déploiement effectué sur `omnirag-demo` ;
  `SHAREPOINT_CONNECTOR_FERNET_KEY` + `REQUIRE_ENCRYPTION=true` dans
  `backend/.env`, routes visibles dans OpenAPI, 401 sans token.

**Flow opérateur aujourd'hui (Andritz-compatible) :**

```text
[local]  python scripts/sharepoint_connector_demo.py --force-reauth --export-session
         → Chromium ouvre, OTP + Authenticator, JSON imprimé
[API]    PUT  /api/v1/sharepoint/sessions/{key}   (workspace admin)
[API]    POST /api/v1/sharepoint/sync             (background job)
[API]    GET  /api/v1/sharepoint/sync/{job_id}    (poll files_downloaded, status)
```

**Limite assumée :** la capture OTP exige un vrai Chromium avec
GUI (cookies `FedAuth` HttpOnly, fingerprinting TLS empêchant
`requests` nu, cross-origin empêchant un front Angular de lire les
cookies d'un autre onglet). Elle se fait donc sur le poste de
l'opérateur via **Agentium Connector**, pas depuis l'UI web.
Fréquence : 1× par TTL de session (~8–24 h selon politique tenant).

**Scope restant E4b :**

1. **Agentium Connector — binaire local CLI packagé (cible démo
   Andritz et au-delà)** :
   - Packager `sharepoint_connector_demo.py` en binaire natif via
     PyInstaller (matrice Linux/macOS/Windows) avec Playwright +
     Chromium bundled (~150 Mo après strip).
   - Enregistrer un URL scheme `agentium-connector://` dans
     l'installer de chaque plateforme (Info.plist macOS,
     registry Windows, `.desktop` Linux).
   - Dans l'UI SharePoint (scope commun plus bas), bouton "Launch
     Agentium Connector" génère un JWT court TTL encodant
     `{sharing_url, session_key, upload_url, bearer}` et ouvre
     `agentium-connector://run?payload=eyJ…` via `window.location`.
   - Le binaire local ouvre Chromium réel, pilote l'OTP + 2FA,
     upload le `storage_state` chiffré vers `PUT /sessions/{key}`
     directement — l'opérateur ne touche jamais au terminal.
   - Fallback gracieux : si le binaire n'est pas installé, l'UI
     retombe sur la commande CLI brute + textarea JSON (manuel
     mais fonctionnel dès aujourd'hui).
   - Distribution : assets attachés aux Releases Bitbucket,
     auto-update via manifest JSON signé (v2).
   - Nommage produit : "Agentium Connector" (plus large qu'un CLI
     SharePoint — premier module d'une future famille de
     connecteurs à capture locale : Google Drive OTP, Dropbox
     Business SSO, etc.).
   - **Signing (décision 2026-04-24)** :
     - Linux : signature GPG sur tarball + checksum SHA256
       publiés avec la release (rapide, gratuit, suffisant pour les
       cibles serveur/poweruser).
     - macOS : **pas de cert Apple Developer** (99 USD/an non
       engagés). Binaire unsigned → l'opérateur doit faire "right-
       click > Open" au premier lancement pour passer Gatekeeper.
       Documenté dans le README de l'installer, acceptable pour un
       outil administrateur qu'on déploie ponctuellement.
     - Windows : **pas de cert EV non plus** (~300 USD/an + démarche
       identité HSM, pas engagés). Le binaire unsigned déclenchera
       SmartScreen "Windows protected your PC" → "More info" → "Run
       anyway". **Conséquence assumée : Windows n'est pas une cible
       réaliste pour une démo client** — on bloque sur Linux +
       macOS (ops internes DATATEGY + Andritz tech lead qui a du
       macOS). Pour un client Windows-only on rebascule sur le flow
       CLI textarea (copy-paste JSON) qui reste le chemin fallback
       universel — ou on signe à ce moment-là, quand un deal
       justifie le cert EV.
     - Conséquence budget : E4.2 ne dépense rien en certs, le code
       signing est reporté au premier deal qui le demande.

2. **Hardening spécifique E4b** :
   - TTL configurable sur les sessions chiffrées (purge auto 7 j
     par défaut, nouveau champ `SharePointSession.expires_at`).
   - Empreinte `storage_state` hashée (jamais le contenu) dans les
     logs pour traçabilité sans fuite de cookies.
   - Signal UI explicite "Reconnect required" quand un sync
     retourne `status=login_required`, CTA qui relance soit
     Agentium Connector soit le flow copy-paste en 2 clics.

#### Scope commun E4a + E4b

Ces livrables bénéficient aux deux connecteurs et ne dépendent
d'aucun tiers :

1. **Page UI SharePoint** dans `frontend-ng` (nouveau feature
   `features/connectors/sharepoint`) :
   - Création d'un connecteur : choix "Standard (OAuth)" ou "Guest
     Link (OTP)" selon ce que l'opérateur peut faire dans son
     tenant cible.
   - Statut de connexion par `session_key` (valide / expirée /
     absente) via `GET /sessions/{key}`.
   - Formulaire de sync : sharing URL (E4b) ou site + library
     picker (E4a), folder, `session_key`. Bouton "Sync now" →
     `POST /sync` + progress bar qui polle `GET /sync/{id}`.
   - Liste des 20 derniers jobs du workspace (date, status,
     `files_downloaded`, `bytes_total`, durée).
   - Empty-state clair selon le mode : OAuth → "Sign in to Entra
     ID" ; Guest Link → "Launch Agentium Connector" ou bloc CLI.

2. **Ingestion dans le pipeline RAG** : aujourd'hui le connecteur
   matérialise les fichiers dans `output_dir` local à la VM. Il
   faut enchaîner avec `DocumentService.ingest_document` pour que
   chaque fichier vectorise + indexe dans Qdrant comme un
   upload-batch, dans la `knowledge_base` du workspace. Nouveaux
   champs `SharePointSyncJob.ingested_count` + `collection_id`
   cible par sync.

3. **Hardening multi-tenant commun** :
   - Rate-limit par `session_key` et par workspace pour éviter
     qu'un workspace sature le BackgroundTasks pool.
   - Audit log `sharepoint.session.uploaded` +
     `sharepoint.session.oauth_consented` +
     `sharepoint.sync.completed` dans `AuditLog`.
   - Bascule non-disruptive `auth_mode` : si un opérateur migre un
     connecteur Guest Link vers Standard (admin consent arrivé
     entre-temps), le `session_key` reste le même et `SyncManifest`
     évite de re-télécharger les fichiers déjà présents.

#### Dépendances externes et dépendance-free

- **E4a.première-prod** : dépend qu'un client (Andritz ou autre)
  accorde l'admin consent sur une app Entra ID consentable. Andritz
  IT sollicité le 2026-04-20 pour `papAI - SharePoint Reader`
  (tenant `aabc1be3-504a-4370-b839-26e514b974f3`, client
  `49888603-9866-4c80-80b1-d2d944fcc0be`, permissions déléguées
  `offline_access User.Read Sites.Read.All Files.Read.All
  AllSites.Read`). En attente.
- **E4b + scope commun** : **aucune dépendance externe**. Peut être
  livré en totalité sans contact client.
- **Décision produit long-terme (post-Vague E)** : cible durable
  du flow E4b parmi extension navigateur MV3, Electron desktop,
  noVNC self-hosted, Browserbase MaaS. Agentium Connector CLI
  (livrable de cette vague) est l'option pragmatique court-terme
  qui ré-utilise 90% du code existant ; la migration éventuelle
  vers extension/Electron se fera sans toucher aux routes backend
  (interface de capture stable).

#### Done quand

- **E4a** : un workspace admin connecte un SharePoint client avec
  une app consentée en < 2 min depuis l'UI, sync tourne en autonomie,
  refresh silencieux sur 14 jours sans intervention.
- **E4b** : un opérateur déclenche un sync Andritz (ou équivalent
  Guest Link) depuis l'UI Agentium (zéro curl), récupère les
  fichiers, les voit indexés dans `/knowledge` et chatte dessus.
  L'Agentium Connector s'installe en < 2 min sur macOS/Linux/Windows
  et capture la session sans ouvrir de terminal. Session expirée →
  état UI "Reconnect required" → relance en 2 clics.
- **Scope commun** : migration `auth_mode` Guest Link → Standard
  non-disruptive pour un connecteur existant ; audit log couvre les
  deux modes ; rate-limit opérationnel en prod.

### E5 — Recommandations proactives

**Dépend de E1.** Une fois que l'eval loop produit des scores
systématiques, l'agrégation peut pointer des tendances : "Cette
capability a 12 runs consécutifs avec faithfulness < 0.5, suggestion :
revoir le prompt système".

**Scope :**
1. Job quotidien qui agrège `Run.evaluation_scores` par `capability_id`
   sur 7/30j.
2. Règles seuil-simple : N runs bas-score consécutifs → `Decision` de
   type `capability_drift` avec payload (metric, trend, proposed_fix).
3. UI dans `/steer` : onglet "Proactive suggestions".

**Done quand :** une capability dont les scores baissent 7 jours
d'affilée génère automatiquement une suggestion actionnable.

### E6 — Simulation offline

**Rejouer un run sur une policy alternative.** Utile pour A/B tester
un nouveau prompt sans casser les vrais runs.

**Scope :**
1. Snapshot d'un run → stock du ctx initial + input + outcomes.
2. `POST /runs/{id}/replay` avec `override_policy: <alt_policy_id>`
   → exécute le même input sur un autre system, retourne le
   résultat en side-by-side.
3. UI `/runs/:id` → bouton "Replay with…" → picker system → diff
   side-by-side des deux outcomes.

**Done quand :** un opérateur peut comparer deux réponses sur le
même input sans consommer d'état prod.

### E7 — Deploy + smoke Vague E

Identique à D7 dans l'esprit :
- `backend/scripts/smoke_vague_e.sh` qui étend `smoke_vague_d.sh` avec
  les nouveaux asserts (E1..E6).
- Playwright en CI post-deploy.
- Journal d'exécution (comme D7 avec les 28 PASS).

**Done quand :** smoke E = 100% green + Playwright E2E = 4/4 + pas de
régression sur les 28 PASS de D7.

## Ordre conseillé

```
E0 (security, P0)  ─▶ toutes les autres
E1 (eval loop)     ─┐
E2 (Playwright)    ├─▶ E7 (deploy)
E3 (chains editor) │
E5 (reco, post-E1) │
E4 (SharePoint)    │
E6 (simulation)    ┘
```

E0 est la seule dépendance dure. E1, E2, E3 peuvent être parallélisés.
E4 est structuré en deux connecteurs jumeaux :
**E4b (SharePoint Guest Link)** — fondation livrée (backend + routes
+ crypto + Playwright VM, 2026-04-20), reste UI commune + ingestion
RAG + Agentium Connector packagé (CLI deep-link), **aucune dépendance
tiers** ; **E4a (SharePoint standard OAuth/MSAL)** — client MSAL
prêt, attend un premier client avec admin consent (Andritz sollicité)
pour la première prod. L'admin consent Andritz débloque uniquement
E4a-première-prod, pas les autres livrables E4. E5 attend E1. E6 est
low-prio sans dépendance.

## Hors Vague E — roadmap long terme

Repris de [`post-demo-roadmap.md`](./post-demo-roadmap.md) et
précisé après Vague D :

- **Multi-tenant avancé** : quotas par workspace, billing, isolation
  Qdrant renforcée (collection-per-tenant vs filter-per-tenant).
- **Marketplace capabilities** : packs industry prêts à l'emploi.
  Dépend d'une décision produit (free tier ? monétisation ?).
- **Observability avancée** : distributed tracing (OpenTelemetry)
  pour suivre une query cross-service.
- **Replay cinématique streaming** : persister les token_deltas
  pour rejouer un run au rythme exact (vs typewriter synthétisé).
- **Mobile companion** : app Flutter/React Native pour alerts +
  approve HITL depuis mobile.

## Critères d'acceptation globaux de Vague E

1. **E0** : aucune surface accepte `admin/admin` ou un secret
   pré-rotation ; email passe `mail-tester` ≥ 8/10.
2. **E1** : un run bas-score génère automatiquement une suggestion
   actionnable dans ≤ 500 ms.
3. **E2** : 4 flows Playwright verts en CI.
4. **E3** : un flow fork/join custom, validé, versionné, rollback
   fonctionnel en < 10 clics.
5. **E4** : (a) un SharePoint client réel avec admin consent ingéré
   et interrogeable depuis l'UI via le connecteur **Standard**
   (OAuth/MSAL) ; (b) un SharePoint réel type Andritz ingéré et
   interrogeable via le connecteur **Guest Link** avec session OTP
   capturée par Agentium Connector local (ou fallback CLI) ; (c)
   bascule non-disruptive `auth_mode` Guest Link → Standard
   fonctionnelle dès admin consent accordé.
6. **E5** : une capability en dérive produit une suggestion
   automatique.
7. **E6** : deux policies comparées side-by-side sur un même input.
8. Smoke E (extending D7) : 100% green.

## Risques et mitigation

| Risque | Impact | Mitigation |
| ------ | ------ | ---------- |
| Rotation client_secret casse le backend | Prod down | Rotation à fenêtre (old + new valides en parallèle) via Keycloak "client credentials list" |
| Eval loop ajoute de la latence visible | UX chat dégradé | Jobs async hors chemin critique, flush côté UI en différé |
| Playwright flaky sur VM partagée | CI rouge | Isolation via docker-compose dédié au test run |
| Admin consent Andritz jamais accordé | Pas de première prod E4a Standard avec Andritz | E4b Guest Link déjà opérationnel pour Andritz (recapture OTP ~1×/jour acceptable pour la démo) ; E4a validable dès qu'un autre client consent |
| Aucun client n'accorde d'admin consent à court terme | E4a "Standard" sans première prod visible | E4b couvre tous les partages externes type Andritz ; E4a reste prêt "on shelf", activation < 1 j dès qu'un client consent |
| Session SharePoint fuitée via logs/backups | Cookies valides entre des mains tierces | Fernet au repos + dérivation par tenant + `SHAREPOINT_CONNECTOR_REQUIRE_ENCRYPTION=true` sur prod ; plus : log-only d'empreintes hashées |
| Session Guest Link expire pendant un sync long | Job mi-parcours échoue, fichiers partiels | Ingester détecte `SharePointLoginRequired`, marque job `status=login_required` sans pertes (manifest reprend au prochain sync) ; UI relance capture via Agentium Connector |
| Agentium Connector bloqué par antivirus / SmartScreen | Deep-link inutilisable sur Windows | **Décision 2026-04-24 : cible initiale Linux + macOS (unsigned, passage Gatekeeper au premier lancement documenté). Windows non prioritaire**, rebascule sur le flow CLI textarea JSON en fallback ou signature EV différée au premier deal qui la justifie (pas de cert engagé dans le budget E4.2) |
| Confusion opérateur entre Standard et Guest Link | Mauvais mode choisi, connecteur qui ne marche pas | UI guide avec question unique "Votre IT a-t-il consenti une app Entra ID ?" → choix auto ; possible de basculer a posteriori |
| Marketplace : question produit non tranchée | Paralysie spec | Hors Vague E tant que décision produit manquante |

## Références

- [`vague-d-plan.md`](./vague-d-plan.md) — Vague précédente, CLOSED
- [`agentium-realignment-plan.md`](./agentium-realignment-plan.md) —
  plan T1.1 → T5.6 (pré-Vague C)
- [`deck-product-review.md`](./deck-product-review.md) — intention
  produit, §27 "reste à faire"
- [`post-demo-roadmap.md`](./post-demo-roadmap.md) — chantiers long
  terme
- [`mental-model.md`](./mental-model.md) — source normative sémantique
- [`ops/keycloak-admin.md`](./ops/keycloak-admin.md) — runbook rotation KC
- [`ops/email-deliverability.md`](./ops/email-deliverability.md) —
  SPF/DKIM/DMARC
- Commits E4 (fondation, 2026-04-20) : `671a3a4` · `c4fd6d8` ·
  `0b4090d` · `df4cf80`
- Démo : `https://agentium.papai.ai`

## Journal

- **2026-04-25 — Changement de cap produit : sortie du mode démo,
  construction du vrai produit.** Décision explicite user : on arrête
  de framer les features par "ce qui rend la démo convaincante" et on
  les implémente comme des capacités produit de bout en bout. En
  pratique, trois conséquences immédiates sur le plan :
  - Les features désormais s'évaluent sur leur cohérence avec le
    **mental model canonique** (Workspace → System → Capability →
    Run → Outcome → Decision), pas sur leur seul poids scénique dans
    un pitch. Exemple concret qui a déclenché le shift : E1 était
    marqué "92% — toast chat parké" alors que le vrai problème était
    architectural (chat ne produisait pas de Run → toute la boucle
    dormait). On ne parke plus un gap sémantique parce qu'il tombe
    hors d'un sprint ; on le ferme.
  - La DoD passe de "démo convaincante sur le happy path seed" à
    "multi-tenant sûr + audit complet + observabilité de prod". Les
    garde-fous (workspace scoping des FK, isolation cross-tenant
    sur tous les lookups, rollback propre sur les migrations) sont
    désormais des critères d'acceptation, plus des "bonus plus tard".
  - On maintient les invariants déjà actés (SPF/DKIM parked OVH,
    `admin/admin` disparu, backup post-rotation) mais on arrête de
    compter "DKIM parké" comme un blocker à E0.5 — c'est une **limite
    produit** à documenter auprès du client, pas un trou roadmap.
    `secrets.md` + `vague-e-plan` journal sont les points d'ancrage
    pour justifier ces décisions en audit client.
  - Décision induite sur le produit : tout workspace hébergeant du
    chat aura désormais un `Run` par tour (cf. E1 closure
    ci-dessous). C'est la source de vérité pour l'audit ET la base
    factuelle sur laquelle la Hypervisor Balance Sheet s'appuiera
    quand on ouvrira le scope cost/value/confidence en Vague F.

- **2026-04-25 — E1 FERMETURE : le chat produit maintenant des Runs,
  toute la boucle d'auto-eval vit pour de vrai. Migration 012 +
  endpoints chat + polling SSE + toast + deeplink review queue.**
  Retour sur le gap exposé la veille (voir entrée 2026-04-24 E1
  journal) : `orchestrator.process_request` streamait la réponse
  mais ne persistait jamais de `Run`, donc `evaluate_run_async`
  ne voyait rien à scorer sur la surface principale du produit.
  Fix end-to-end, stack-wide :
  - **Migration 012 `chat_runs_nullable_sys`** : `runs.system_id`
    passe en nullable. Décision produit : un `Run` est canonique
    à une `Workspace`, optionnel à une `System`. Chat workspace-wide
    (sans System sélectionné) = Run quand même, scope
    workspace. Tous les call-sites downstream vérifient déjà
    `if run.system_id` (audité avant migration : `impact.py`,
    `systems.py`, `auto_eval.py`, `run_engine/*`). Limite du
    rollback documentée dans la migration (purge préalable des
    chat Runs si on veut revenir à NOT NULL).
  - **Backend chat endpoints** : `/chat/completion` et
    `/chat/stream` persistent un `Run(status=completed,
    trigger="chat", system_id=<valid FK or None>,
    input_ref={query}, output_ref={response, sources,
    reasoning_trace})` puis appellent `schedule_eval(run.id)`. Un
    helper `_resolve_system_id` valide que le `agent_id` reçu
    appartient bien au workspace courant (prévient toute tentative
    de FK leak cross-tenant). Le helper `_persist_chat_run`
    avale toute exception de la création Run pour ne jamais
    casser la réponse utilisateur — l'audit est best-effort, la
    réponse est critique.
  - **SSE chunk `eval_pending`** : le stream émet un chunk final
    `{chunk_type: "eval_pending", run_id}` après `[DONE]` pour
    que le front puisse démarrer son polling. Le non-streaming
    endpoint retourne `run_id` dans la réponse JSON.
  - **Endpoint `GET /evaluation/by-run/{run_id}`** : nouveau,
    triple état — `pending` (judge pas encore terminé), `skipped`
    (preset désactivé ou sample_rate exclu le run) ou `completed`
    (scores + breach + decision_id éventuel). Filtrage strict
    sur `workspace_id` + 404 pour tout run d'un autre tenant
    (validé par smoke : cross-workspace run → 404, pas 200).
  - **Frontend chat-panel** : consomme `eval_pending`, poll
    `/evaluation/by-run/:id` toutes les 1.5s (20 tentatives max =
    30s budget), arrêt immédiat sur `skipped`. Sur breach, toast
    warning ngx-toastr cliquable avec deeplink intelligent :
    `/steering/review-queue?decision=:id` si une Decision a été
    filée, sinon `/runs/:id` (raw context). Tap-to-dismiss
    désactivé pour que le reviewer clique réellement au lieu de
    balayer.
  - **Review queue** : lit `?decision=:id`, highlight la row
    correspondante (bordure gauche warn + fond soft) et
    `scrollIntoView` smooth. La surbrillance disparaît au
    changement de filtre — l'utilisateur a "quitté" le contexte
    du toast. "Open run" déjà présent, aucune modif côté actions.
  - **Smoke VM** (`/tmp/e1_chat_smoke.py` + `/tmp/e1_api_probe.py`) :
    2 Runs chat persistés via helper → preset STRICT
    (`composite_min=99.99`) → `composite=99.6` → breach=True,
    `Decision(review_required)` filée, `EvaluationScore(run_id=...)`
    posée, `Run.evaluation_scores.threshold_breach=True`. Preset
    PERMISSIVE → breach=False, aucune Decision, snapshot posé.
    Endpoint `/evaluation/by-run/:id` renvoie `200 completed
    breach=true decision_id=...` sur le Run breaché, `200
    completed breach=false` sur le permissif, `404` sur id
    inconnu ET sur un Run d'un autre tenant. Runs de test
    purgés après validation (workspace revient à l'état
    production-clean).
  - **Ce qui reste en backlog E1** : rien de bloquant. Le flow
    d'activation preset (`enabled=true` sur un workspace client
    depuis le Settings UI) est déjà livré (`EvaluationPresetComponent`,
    commit `2930dbe`), le widget Eval trend 7d tourne en live.
    Le nice-to-have "badge évaluation inline dans la bulle
    assistant" est une itération UX pour Vague F ou après,
    pas un trou fonctionnel : le toast + deeplink ferme la
    boucle actionnable sur la breach.

- **2026-04-24 — E1 auto-eval loop validé bout-en-bout sur la VM
  live. Toutes les briques ship, seul le câblage preset
  workspace-par-défaut reste à activer.** Smoke en 2 passes sur
  `omnirag-demo` :
  - **Passe 1 — pas de breach** : `evaluate_run_async` invoqué
    sur un run existant (`38915b18-…`, prompt "Streaming LLM UX"
    + completion 3 raisons) avec preset permissif. Judge OpenAI
    réel retourne `composite=99.6`, aucune breach. `EvaluationScore`
    row créée avec workspace_id + run_id. `Run.evaluation_scores`
    JSON posé.
  - **Passe 2 — breach forcée** : même run, preset
    ultra-strict (`composite_min=99.99`, `dimension_min.drift=100`,
    `dimension_min.task_success=101`). Judge retourne
    `composite=98.3`, threshold check logge 4 reasons. Hook
    `_file_review_decision` crée la `Decision`
    `1774f960-d4c0-4218-9e1e-237d318463fa` avec
    `scope=run`, `kind=review_required`, `status=proposed`,
    `title="Run below composite threshold (98/100)"`,
    `rationale` contenant {composite_score, hallucination_rate,
    reasons[4]}. Exactement ce que la review queue UI attend.
  - **Endpoints live** (via TestClient avec override
    `get_current_workspace` → workspace "Acme") :
    - `GET /api/v1/evaluation/review-queue?status=proposed`
      → 200, `count=1`, Decision + Run joints.
    - `GET /api/v1/evaluation/trend?since=1d&group_by=day`
      → 200, série `[{bucket:"2026-04-24", count:2,
      avg_composite:98.95, avg_hallucination:0.0}]`,
      `thresholds.composite_min=60` (défauts corrects).
    - `GET /api/v1/evaluation/presets` → 200, renvoie
      `defaults` + `workspace` (null) + `effective` (merged).
    - `GET /api/v1/evaluation/history?since=1d` → 200.
  - **Insight produit** : `DEFAULT_EVAL_CONFIG.enabled = false`
    par défaut. Conséquence : le hook `_finalize_run →
    schedule_eval → evaluate_run_async → preset resolver →
    enabled=false → early return` n'appelle PAS le judge tant
    que le workspace n'a pas fait un `PUT /presets` avec
    `enabled=true`. C'est un choix safe (zéro facture OpenAI
    surprise à l'activation de la feature) mais implique que
    le premier client qui veut l'auto-eval doit explicitement
    opt-in. À surfacer dans l'UI settings `EvaluationPresetComponent`
    livré dans le commit `2930dbe` (master switch déjà présent).
  - **Reste E1 UI** (pas bloquant) : widget "Eval trend 7d"
    dans `/observability` (backend ready), toast "⚠ Reply
    scored below threshold" + deeplink review-queue depuis
    le chat, lien depuis la review queue vers le run dans
    le runs inspector.

- **2026-04-24 — E0 quasi complet : PG rotation exécutée, KC
  cleanup + runbook livrés. DKIM OVH bloqué sur admin externe.**
  Audit préalable sur `omnirag-demo` a clarifié le scope réel :
  - **E0.1 KC admin rotation** : ✅ déjà fait dans la rafale
    post-D7 (`admin/admin` → 404, `tib-admin` opérationnel). Rien à
    refaire.
  - **E0.2 rotation client_secret** : scope revu — le backend
    n'utilise PAS de `KEYCLOAK_CLIENT_SECRET` actuellement (`pgrep
    -f uvicorn` ne le montre pas, `.env` non plus). Le secret est
    seulement requis pour activer l'admin API (`_get_admin_token`
    dans `backend/app/api/v1/endpoints/auth.py`) qui couvre signup
    + programmatic password reset. Tant que ces endpoints ne sont
    pas utilisés, rien à rotater. Documenté comme activation
    optionnelle dans `docs/ops/secrets.md`.
  - **E0.3 rotation PG password** : ✅ exécutée à 06:32 UTC.
    `ALTER USER agentium` en one-shot, backend `.env` patché
    (`DATABASE_URL`), backend restart → `/health: 200` en 5s,
    container `agentium-kc` redéployé via
    `sudo KC_DB_PASSWORD=<new> ./redeploy-keycloak.sh` et
    reconnecté proprement (OIDC discovery 200 sur master +
    papai-org, aucune erreur `password authentication failed`
    dans les logs post-restart). Le redeploy script a dû être
    patché (cf. E0.7) parce qu'il capturait l'ancien password
    depuis `docker inspect` et ignorait l'override d'env.
    Rollback file (8 chars ancien) stashé en `/root/pg-rollback-
    <ts>.txt` chmod 600, à nuker après 24h sans incident. Ancien
    mdp encore accepté sur Unix socket local du container
    (`POSTGRES_HOST_AUTH_METHOD=trust` au loopback) — documenté
    dans `secrets.md`, aucune surface externe.
  - **E0.7 hardening `redeploy-keycloak.sh`** (découvert pendant
    E0.3) : ✅ ajout du mécanisme `OVERRIDABLE_VARS` qui permet à
    `KC_DB_PASSWORD`, `KEYCLOAK_ADMIN_PASSWORD`, `SMTP_USER`,
    `SMTP_PASSWORD` d'être injectés depuis l'env shell et de
    remplacer la valeur capturée depuis `docker inspect`. Sans
    ça, toute rotation de secret forçait une édition manuelle
    du container env ou un wipe. Pattern réutilisable pour les
    futures rotations SMTP + client_secret.
  - **E0.4 cleanup** `KC_BOOTSTRAP_ADMIN_*` : ✅ livré —
    `deploy/redeploy-keycloak.sh` filtre désormais
    `KC_BOOTSTRAP_ADMIN_*` de la capture env avant redeploy.
    `docker/test_env_files/keycloak.env` + `backend/keycloak/
    keycloak.env` vidés de leurs defaults `admin/admin`. Le
    container live garde les vars pour l'instant (ignorées tant
    que `tib-admin` existe en DB) et sera propre au prochain
    redeploy naturel.
  - **E0.5 DKIM** : ⏸ **parké** (décision user 2026-04-24 09:20).
    Investigation complète : OVH MX Plan ne supporte pas DKIM
    self-service sur le SMTP sortant (limitation historique
    du produit, DKIM dispo uniquement sur Email Pro /
    Hosted Exchange). Le formulaire DNS zone OVH demande une
    pubkey base64 que la plateforme mail MX Plan ne génère
    jamais (BYOK non supporté). "Manage elements shared" dans
    MX Plan redirige sur la page de délégation admin, pas DKIM.
    **Insight découvert** : le SPF datategy.net autorise déjà
    `include:spf.mailjet.com` — Mailjet est donc déjà en place
    comme relais potentiel. Chemin propre quand on rouvrira
    le sujet : switcher `SMTP_HOST` Agentium de `ssl0.ovh.net`
    vers `in-v3.mailjet.com` (DKIM natif côté Mailjet, SPF déjà
    aligné, zéro dépendance sur le tier MX Plan OVH). Creds
    Mailjet Datategy à récupérer avant de reprendre. État
    actuel acceptable pour démo : SPF OK + DMARC
    `p=quarantine; pct=90` → ~10% des mails en quarantaine,
    gérable pour démos de faible volume. Ré-ouverture du
    sujet quand premier client production.
  - **E0.6 secret manager runbook** : ✅ `docs/ops/secrets.md`
    livré — inventaire complet (8 secrets), conventions vault
    agnostiques, procédure PG rotation détaillée avec rollback,
    clarification sur KEYCLOAK_CLIENT_SECRET (activation
    optionnelle vs "rotation"), calendrier rotation trimestrielle.

- **2026-04-24 — E2 Playwright scaffolding livré (tests non encore
  exécutés sur la VM).** Opt-in volontaire : `@playwright/test` pas
  ajouté aux deps (pour ne pas forcer un `npm install` de 150 Mo
  overnight sans le user) ; installation en 2 commandes documentée
  dans `frontend-ng/e2e/README.md`.
  - `frontend-ng/playwright.config.ts` — baseURL par défaut
    `https://agentium.papai.ai`, override via `E2E_BASE_URL`,
    `webServer` spawn auto si localhost, retries=2 sur CI,
    trace/video `retain-on-failure`.
  - `frontend-ng/e2e/fixtures/auth.ts` — `loginAsAlice(page)`
    réutilisable, sélecteurs sémantiques (`input#username`) pour
    survivre aux retouches du thème Keycloak "agentium".
  - `e2e/tests/01-auth-keycloak.spec.ts` — 3 tests (login /
    survie reload / creds invalides).
  - `e2e/tests/02-chat-drop-and-ask.spec.ts` — drop 2 PDF, ask,
    citation chip cliquable, panneau sources visible. Dépend de
    `e2e/fixtures/docs/sample-{a,b}.pdf` non encore générés
    (placeholder `.gitkeep`, TODO dans `scripts/test-vm.sh
    seed:e2e`).
  - `e2e/tests/03-hitl-approve.spec.ts` + `04-debug-step-continue
    .spec.ts` — `test.skip` gracieux si la fixture (`hitl-demo`
    / `debug-demo` system) n'est pas seedée, donc l'harness reste
    green sur un env pristine.
  - `frontend-ng/e2e/tsconfig.json` isolé pour que l'IDE
    comprenne les fichiers sans polluer le build Angular
    (`tsconfig.app.json` ne les inclut pas).
  - `package.json` : scripts `test:e2e` + `test:e2e:ui` ajoutés,
    pas de devDep (activation = `npm i -D @playwright/test && npx
    playwright install chromium`).

  **Reste à livrer pour fermer E2 :**
  1. `scripts/test-vm.sh seed:e2e` — seed alice/workspace +
     systems `hitl-demo` + `debug-demo` + PDFs sample.
  2. Run initial des 4 flows contre staging, stabiliser
     sélecteurs (data-cite-chip, data-sources-panel à exposer
     côté composants).
  3. Wire dans CI hebdomadaire (workflow GitHub Actions /
     Bitbucket Pipelines).

- **2026-04-24 — E1 Boucle d'évaluation — backend + UI minimale livrés
  (branche locale, non encore pushée/déployée).** L'utilisateur a
  demandé d'enchaîner pendant la nuit ; E0 (secret rotation + DKIM) a
  été volontairement **différée** parce qu'elle exige de manipuler des
  secrets de prod et d'interagir avec des consoles tierces (OVH DNS,
  Keycloak admin live) — risque non borné à exécuter sans supervision.
  E1 est purement backend/UI, safe à livrer overnight.

  **Backend :**
  - Alembic `011_evaluation_loop` — ajoute `runs.evaluation_scores`
    (JSON), `evaluation_scores.run_id` (+ index), table
    `evaluation_presets` (mirroir de `rag_presets` — scope
    system/capability/workspace, `config` JSON, `is_default`).
  - Modèles : `Run.evaluation_scores`, `EvaluationScore.run_id`,
    nouveau `EvaluationPreset`.
  - Service `EvaluationPresetService` — résolution précédence
    system > capability > workspace > défauts built-in, merge shallow
    (`dimension_min` fusionné un niveau profond pour ne pas écraser
    `safety=80` si le client n'override que `hallucination=50`).
    Défauts : `enabled=False` (opt-in), `composite_min=60`,
    `hallucination_max=0.3`, `dimension_min={safety:80, hallucination:50}`,
    `sample_rate=1.0`.
  - Service `auto_eval.evaluate_run_async` — branché en fire-and-forget
    à la fin de `run_engine.engine._finalize_run`. Ouvre sa **propre
    SessionLocal** pour ne pas bloquer la session request-scope pendant
    le call judge (5–15 s). Extrait `(query, response, context_chunks)`
    depuis `run.input_ref / output_ref / invocations[-1].output_ref`,
    appelle `JudgeService.evaluate`, persiste dans `evaluation_scores`
    (lié via `run_id`), écrit le snapshot dans `run.evaluation_scores`,
    et si un seuil casse, file une `Decision(kind="review_required",
    scope="run", target_id=run.id)` avec rationale =
    `{run_id, system_id, capability_id, composite_score,
    hallucination_rate, reasons[], suggestion}`. Toute exception est
    avalée avec log — un crash eval ne fait **jamais** échouer le run.
    `schedule_eval(run_id)` gère async loop + fallback thread pour les
    tests sync.
  - Endpoints FastAPI (`/api/v1/evaluation/*`) :
    - `GET /presets?capability_id&system_id` → config effective +
      override workspace + défauts built-in.
    - `PUT /presets` → upsert workspace-scope (payload typé
      `EvalPresetIn`, validation Pydantic `Field(ge, le)`).
    - `GET /review-queue?status&limit` → Decisions(kind=review_required)
      du workspace avec run associé (input_ref + output_ref +
      evaluation_scores inlinés, pour éviter une round-trip UI).
    - `GET /trend?since=7d&group_by=day|capability|system` →
      agrégation pour future dashboard observabilité / E5.
    - `GET /history?since=7d` étendu avec filtrage temporel.
  - 12 tests backend `test_auto_eval.py` (preset resolver, threshold
    math, file Decision on breach, skip non-completed, skip no
    response, swallow judge exception) — tous verts. `JudgeService`
    monkey-patché via `_StubJudge` pour éviter GPT-4o en CI.

  **Frontend :**
  - `ReviewQueueComponent` (`/steering/review-queue`) — liste des
    runs flaggés avec filtre status (OPEN/ACCEPTED/REJECTED/ALL),
    actions Accept/Reject (réutilise `POST
    /hypervisor/decisions/{id}/{accept|reject}` existant), lien "Open
    Run" vers `/runs/:id`, preview query+response inline (400c),
    reasons détaillées (metric, observed vs threshold, direction),
    suggestion lexicale du service (pas de nouveau call LLM).
  - `EvaluationPresetComponent` (`/presets/evaluation`) — master
    switch `enabled`, 3 sliders (composite_min 0–100,
    hallucination_max 0–100%, sample_rate 0–100%), éditeur JSON
    power-user pour `dimension_min`. Synced / unsaved state explicite.
  - Wiring nav : rail secondaire Steer gagne "Review queue" (glyph
    `warn`), command palette gagne `view.review-queue` +
    `view.eval-thresholds`. Route `/presets/evaluation` + route
    `/steering/review-queue` ajoutées dans `presets.routes.ts` et
    `app.routes.ts`.
  - `CanonicalApiService.getEvaluationReviewQueue` /
    `getEvaluationPresets` / `updateEvaluationPreset` /
    `getEvaluationTrend` déjà exposées ; `ApiService.put<T>` ajouté
    pour supporter le PUT `/evaluation/presets`.
  - `npx tsc --noEmit` sur les fichiers touchés → 0 erreur (erreurs
    lucide-angular préexistantes dans `icon-registry.ts`, hors scope).

  **Reste à livrer pour fermer E1 complètement :**
  1. Smoke de bout-en-bout sur la VM : activer preset,
     déclencher un run qui casse le seuil (run adversarial),
     vérifier apparition dans review queue + Decision en DB.
  2. Widget "Eval trend 7d" dans `/observability` (backend déjà
     prêt via `GET /evaluation/trend?group_by=day`). Peut être
     poussé en "E1-follow-up" si la review queue suffit pour la
     démo multi-clients.
  3. Toast builder "⚠ Reply scored below threshold" + deeplink →
     dépend du RunEventBus. Pas critique tant que la review queue
     est consultée activement.

- **2026-04-20 — E4b (SharePoint Guest Link) fondation livrée ;
  E4a (SharePoint Standard OAuth) client prêt on-the-shelf.**
  Poussé sur `demo/agentic` et déployé sur `omnirag-demo`. La
  taxonomie "deux connecteurs jumeaux" (Standard OAuth vs Guest Link
  OTP) a été actée dans la section E4 : le backend unique
  `/api/v1/sharepoint/*` sert les deux via `auth_mode`, le package
  `sharepoint_otp/` contient déjà `client.py` (E4b, Playwright) et
  `client_msal.py` (E4a, MSAL). Renommage futur du package envisagé
  (`sharepoint/` plat avec `guest_link.py` + `oauth.py`) non
  bloquant.
  - `671a3a4` — Package `sharepoint_otp` initial (client Playwright +
    client MSAL miroir, ingester incrémental, crypto Fernet
    per-tenant, CLI `scripts/sharepoint_connector_demo.py`, 17 unit
    tests). Nettoyage post-push : cookies `FedAuth` + fichiers test
    Andritz committés par erreur ; purgés via amend + force-push,
    `.gitignore` blindé (`.sharepoint_sessions/`, `downloads/`).
  - `c4fd6d8` — Routes `/api/v1/sharepoint/*` branchées sur
    `backend/app/api/v1` (le FastAPI réellement exposé par la VM —
    `connections/fastapi` n'est pas servi). Intra-package en imports
    relatifs pour que le module fonctionne depuis repo root (CLI/tests)
    et depuis `backend/` (uvicorn VM). Paramètres
    `sharepoint_session_dir` / `sharepoint_download_dir` /
    `sharepoint_connector_fernet_key` ajoutés à `app.core.config`.
  - `0b4090d` — Jobs persistés en SQL (`SharePointSyncJob`) au lieu
    d'un registre en mémoire, pour que `GET /sync/{id}` réponde depuis
    n'importe quel worker uvicorn (la VM tourne `--workers 2`).
  - `df4cf80` — Scoping par workspace : `get_current_workspace` sur
    toutes les routes, `session_key` namespacé
    `ws_{workspace_id}__{user_key}` sur disque, rôle owner/admin
    requis pour PUT/DELETE sessions. Table `sharepoint_sync_jobs`
    gagne `workspace_id` pour filtrer les listes.
  - **VM** : `playwright install chromium --with-deps` exécuté,
    smoke `sync_playwright().chromium.launch()` → "Example Domain"
    OK. `.env` enrichi :
    `SHAREPOINT_SESSION_DIR=/home/ubuntu/omnirag/.sharepoint_sessions`
    + `SHAREPOINT_CONNECTOR_FERNET_KEY=<generated>` +
    `SHAREPOINT_CONNECTOR_REQUIRE_ENCRYPTION=true`. Uvicorn rebouncé,
    openapi expose bien les 5 routes, `401` sans token confirmant le
    gating Keycloak actif.
  - **Reste à livrer pour clôturer E4** :
    - *Scope commun E4a + E4b* : UI SharePoint unique (création
      connecteur avec choix Standard/Guest Link), wiring
      `DocumentService.ingest_document`, hardening (rate-limit +
      audit log + bascule `auth_mode` non-disruptive).
    - *E4b seul* : Agentium Connector (binaire PyInstaller + URL
      scheme `agentium-connector://`), TTL sessions, hashed session
      fingerprint logging.
    - *E4a seul* : flow OAuth UI (redirect Entra ID + callback),
      Graph site/library picker, sync périodique configurable.
      Première prod en attente d'un client avec admin consent
      (Andritz sollicité 2026-04-20, en attente).

- **2026-04-24 — E4.1 (scope commun E4a/E4b) livré : UI SharePoint
  dédiée + ingestion RAG + audit + catch-up migration.** Tout le scope
  commun E4a + E4b identifié le 2026-04-20 est désormais fermé sur
  `demo/agentic` et déployé sur `omnirag-demo`. Les opérateurs peuvent
  enchaîner capture session (Guest Link) ou config tenant (OAuth) →
  sync → ingestion RAG → interrogation chat sans quitter la WebUI.
  - **Backend** :
    - `backend/app/services/audit_logger.py` — helper `emit_audit_event`
      pour écrire `AuditLog` hors contexte HTTP (BackgroundTasks n'a pas
      de `Request` donc `record_audit_log` ne suffisait plus). Ouvre
      son propre `SessionLocal`, commit dédié, exceptions avalées pour
      ne jamais casser le métier.
    - `backend/app/api/v1/endpoints/sharepoint.py` :
      - `SharePointSyncRequest.collection_name` (default `"documents"`)
        — aligne E4.1 avec le flux drop-and-ask qui lit cette
        collection par défaut.
      - `_ingest_downloaded_files()` appelé post-sync sur chaque fichier
        dans `IngestionResult.downloaded_paths`, passe par
        `DocumentService.ingest_document`, tallie succès/échecs.
      - `_run_sync_job()` émet `sharepoint.sync.failed` /
        `sharepoint.sync.completed` / `sharepoint.sync.login_required`
        avec `job_id`, `session_key`, `workspace_id` dans les détails
        (pas de secret). `enqueue_sharepoint_sync` émet
        `sharepoint.sync.enqueued`.
      - Upload/delete session PUT/DELETE émettent
        `sharepoint.session.uploaded` / `sharepoint.session.deleted`
        avec `has_storage_state: bool` (jamais le cookie clair).
    - `backend/app/models/sharepoint_sync_job.py` + migration
      `013_sp_ingest_columns` : colonnes `ingested_count`,
      `ingest_failed_count`, `collection_name` exposées dans
      `SharePointJobSummary`.
    - Migration catch-up `014_sp_workspace_id` : `workspace_id` avait
      été ajouté au modèle dans `df4cf80` **sans migration Alembic**.
      Les environnements où la table avait été créée par `create_all`
      (dont `omnirag-demo`) se vautraient sur `UndefinedColumn:
      workspace_id` au premier `POST /sharepoint/sync`. 014 rattrape
      le coup, idempotent (détecte une éventuelle correction manuelle).
      Docstring du modèle réécrite pour tracer l'historique et éviter
      une prochaine dérive silencieuse.
  - **Frontend** : nouvelle page dédiée
    `frontend-ng/src/app/features/connectors/sharepoint/` (service +
    composant), mountée sur `/connectors/sharepoint` via
    `connectors.routes.ts` (intégrée à `app.routes.ts`). La carte
    SharePoint de `resources-page.component.ts` navigue désormais vers
    cette page au lieu du drawer générique.
    - Mode picker Standard (OAuth/MSAL) vs Guest Link (OTP/session) —
      formulaire spécialisé selon le mode.
    - Mode Guest Link : upload session via bouton avec instructions CLI
      (`scripts/sharepoint_connector_demo.py capture`) affichées
      inline.
    - Champs sync : session key, folder URL, sharing URL (GL) ou
      client_id/tenant_host (OAuth), collection name, toggle prune.
    - Live polling des jobs en cours (2 s), badges colorés par état,
      erreurs affichées en clair.
  - **Smoke VM `omnirag-demo`** (`/tmp/e41_smoke.py`, TestClient avec
    overrides Keycloak) — toutes les assertions vertes :
    - Payloads rejetés : `sharing_url` manquant → 400, prefix invalide
      → 405.
    - Session PUT → 204 + audit `sharepoint.session.uploaded` (détails
      ne contiennent **pas** `storage_state`), GET → 200 `exists=true`.
    - Sync POST → 202 avec `job_id`, réponse inclut bien les 3 nouvelles
      colonnes (`ingested_count`, `ingest_failed_count`,
      `collection_name`), `collection_name` roundtrip OK.
    - Job de bout-en-bout terminal (état `failed` attendu — DNS sur
      `example.sharepoint.com` échoue, sync se ferme proprement au
      lieu de rester `running`), audits `sharepoint.sync.enqueued` +
      `sharepoint.sync.failed` émis avec le bon `job_id`.
    - Isolation multi-tenant : workspace B → session GET `exists=false`,
      job GET 404.
    - Session DELETE → 204 + audit `sharepoint.session.deleted`.
  - **Reste pour clôturer E4 après E4.1** :
    - *E4.2* (E4b seul) : Agentium Connector — binaire PyInstaller +
      URL scheme `agentium-connector://`, TTL sessions, hashed session
      fingerprint. **Décision signing (2026-04-24)** : Linux signé GPG
      (gratuit), macOS + Windows unsigned (pas de cert Apple Developer
      ni EV engagé dans le budget). macOS documente le right-click >
      Open pour passer Gatekeeper au premier lancement. **Windows
      n'est pas une cible viable** pour une démo client avec binaire
      unsigned (SmartScreen bloque) → on se limite à Linux + macOS
      et on rebascule sur le flow CLI textarea JSON comme fallback
      Windows si besoin. Pas de dépendance externe à lever, E4.2 est
      déblocable quand on veut.
    - *E4.3* (E4a seul) : OAuth UI (redirect Entra ID + callback),
      Graph site/library picker, sync périodique configurable.
      Déblocable dès qu'un client accorde admin consent (Andritz
      relancé 2026-04-20, en attente).

- **2026-04-24 — E3.1 (fondations backend versioning + validation)
  livré + smoke vert sur `omnirag-demo`.**
  Scope backend du "custom chains editor" finition est clos : les
  chaînes ont désormais un historique réel (rolling window 500) et
  ne peuvent plus être sauvegardées dans un état structurellement
  cassé. Reste E3.2 (UI versioning panel), E3.3 (node-props
  éditables) et E3.4 (export/import JSON).
  - **Backend** :
    - Nouvelle table `system_versions` (migration
      `015_system_versions`) + colonnes `runs.flow_snapshot` et
      `runs.flow_version_id` pour que les runs restent rejouables
      même après purge de leur version d'origine.
    - `backend/app/services/chains/dag_validator.py` : miroir exact
      de `FlowSerializer.validateFlow` côté frontend + les checks
      qu'il déclarait sans les émettre (`unreachable_node`,
      `node_orphan`). `PATCH /systems/{id}` gate les erreurs en 400
      structuré ; les warnings passent mais sont renvoyés au client.
    - `backend/app/services/chains/version_service.py` :
      `record_new_version` (idempotent sur flows identiques),
      `_purge_window` (FIFO à chaque dépassement du cap
      `CUSTOM_CHAIN_VERSION_WINDOW`), `rollback_to_version` (crée
      une nouvelle version dont `flow_definition` = la cible, ne
      réécrit jamais l'historique).
    - API : `GET /systems/{id}/versions` (paginé, summary), `GET
      /systems/{id}/versions/{n}` (payload complet), `POST
      /systems/{id}/versions/{n}/rollback`. `POST /systems` seede
      désormais v1 à la création.
    - Audits `chain.version.created`, `chain.version.purged`,
      `chain.rollback` émis via session partagée au caller (évite
      le "database is locked" de SQLite en test ; Postgres prod
      reste inchangé).
  - **Tests** : 26 unitaires verts (validator exhaustif + versioning
    rolling window + rollback + isolation workspace). `pytest
    app/tests/services/` reste vert (73 passed).
  - **Smoke VM** (`/tmp/e31_smoke.py`, TestClient avec overrides
    Keycloak) — 22 assertions vertes :
    - Création empty → v1 seedée.
    - POST avec orphan → 400 `node_orphan`.
    - PATCH valide → v2 créée + `new_version` dans la réponse.
    - PATCH identique → no-op (pas de nouvelle version).
    - PATCH avec cycle → 400 `cycle_detected`, versions non mutées.
    - GET /versions latest-first, GET /versions/{n} payload complet.
    - Rollback → v3 avec `rolled_back_from_id` pointant v1, et
      `System.flow_definition` mis à jour en place.
    - Window = 3 : 4 saves supplémentaires, table plafonne à 3,
      `chain.version.purged` émis 4 fois.
    - Isolation multi-tenant : workspace B → 404 sur
      `GET /versions` et `POST /rollback`.
  - **Reste pour clôturer E3 après E3.1** :
    - *E3.2* : panel "Versions" dans `workflow-editor` (liste +
      diff count + CTA rollback), gate du save côté UI sur la
      validation serveur (affichage structuré des erreurs 400).
    - *E3.3* : formulaires éditables par kind (decision branches,
      fork/join strategy, loop budget, retry config, HITL prompt,
      subflow picker, task params depuis `Skill.input_schema`).
    - *E3.4* : `GET /systems/{id}/export` + `POST /systems/import`
      avec re-binding des skills par slug.

- **2026-04-24 — E3.2 (UI versioning + rollback panel + save gate)
  livré + smoke vert sur `omnirag-demo`.**
  Le builder peut désormais consommer tout ce que E3.1 a exposé :
  le save n'avale plus les erreurs serveur, l'historique est visible
  et parcourable, et le rollback se fait en deux clics. Reste E3.3 et
  E3.4 pour clôturer E3.
  - **Frontend** :
    - `canonical-api.service.ts` : nouveaux types `SystemVersionSummary`,
      `SystemVersionFull`, `SystemVersionList`, `SystemRollbackResult`,
      `FlowValidationIssue` (mirror backend) et le **discriminated
      union** `SaveSystemFlowResult` (`ok: true` + warnings optionnels
      + `new_version` ; `ok: false` + `reason: 'invalid' | 'network'` +
      `issues`). Méthodes `saveSystemFlow`, `listSystemVersions`,
      `getSystemVersion`, `rollbackSystemVersion`.
    - `workflow-editor.component.ts` : bouton toolbar "Versions"
      (ouvre un drawer droit), signals `versions`, `versionsTotal`,
      `versionsLoading`, `versionPreviews`, `rollbackTarget`,
      `rollbackPending`, `rollbackMessage`, `serverIssues` +
      computed `allIssues` (merge client + serveur). Le drawer affiche
      v{n}, auteur, timestamp relatif, `node_count`/`edge_count` et un
      diff count vs. canvas (symmetric diff si le payload complet est
      déjà caché, sinon delta directionnel). Row courante marquée
      `CURRENT`, rows issues d'un rollback marquées `ROLLBACK`.
    - Modal de rollback : confirmation + message optionnel (pré-rempli
      `rollback to v{n}`), CTA primary en `signal-warn`. Après succès :
      reload du System, `importFlow` du payload rollback,
      `refreshVersions`, `serverIssues.set([])`, toast confirmant
      `v{old} → new v{new}`.
    - Save gate : `saveToSystem` remplace `canonical.updateSystem` par
      `saveSystemFlow`. Sur `ok: false, reason: 'invalid'`, on publie
      les issues dans `serverIssues` (la strip au-dessus du canvas les
      distingue des client issues avec un tag `SERVER`) et on toast
      "Save blocked — N structural errors". Sur `ok: true`, warnings
      serveur survivent dans la strip (info only).
    - Styles `workflow-editor.styles.scss` : nouveau bloc E3.2
      (`.df-versions-panel`, `.df-version-row[data-current]`,
      `.df-version-row__msg`, `.df-version-btn`, `.df-modal*`).
    - `flow-serializer.service.ts` : union `FlowValidationIssue.code`
      étendue à `node_orphan` pour matcher le validator backend
      (sinon TS rejetait la cast).
  - **Pas de nouveau backend nécessaire** — E3.2 consomme tout ce que
    E3.1 a exposé (`PATCH /systems/{id}` avec 400 structuré,
    `GET /systems/{id}/versions`, `GET /systems/{id}/versions/{n}`,
    `POST /systems/{id}/versions/{n}/rollback`).
  - **Smoke backend** (`/tmp/e32_smoke.py`, TestClient avec overrides
    Keycloak) — 5 scénarios end-to-end verts confirmant que l'enveloppe
    d'erreur 400 est bien `{detail: {error: "flow_invalid", issues:
    [...]}}` (ce que le client Angular parse via
    `err.error.detail.issues`) :
    - Création → 200
    - PATCH invalid (2 tasks sans skill + sans arêtes) → 400 avec 4
      issues (`task_no_skill` × 2, `node_orphan` × 2)
    - PATCH valid (source → sink) → 200 avec `new_version.v=2`
    - `GET /versions` → 2 rows
    - `POST /rollback` vers v1 → 200 avec `new_version.v=3`
  - **Reste pour clôturer E3 après E3.2** :
    - *E3.3* : formulaires éditables par kind dans l'inspector.
    - *E3.4* : export / import JSON avec re-binding des skills.

- **2026-04-24 — E3.3 (node-props éditables par kind) livré + smoke
  vert sur `omnirag-demo`.** L'inspector a cessé d'être un viewer en
  lecture seule pour tout ce qui n'est pas le skill binder. Chaque kind
  a désormais un formulaire dédié qui écrit directement sur
  `canonical_config` via le helper mutualisé `patchSelectedConfig`
  (même pattern que `bindSkill`) :
  - *Label* : input éditable en tête d'inspector, avec sync du DOM
    `.df-node-title` pour refléter immédiatement sur le node canvas.
  - *Decision* : branches `{ label, condition }` avec add/remove (min 2,
    max 8), default_branch dropdown.
  - *Fork* : liste de branch-names free-form avec add/remove.
  - *Join* : picker strategy `all` / `any` / `race` (inline doc dans
    les `<option>` pour clarifier la sémantique).
  - *Loop* : iterator (expression contexte), `max_iterations` borné
    1..1000, `break_on` optionnel.
  - *Retry* : `max_attempts` 1..20, `backoff_ms`, `on_errors` CSV
    → normalisé en liste côté frontend avant write.
  - *HITL* : `prompt` textarea (max 2000), `timeout_ms`, `approvers`
    CSV. `timeout_ms === 0` sérialise `undefined` pour un wait infini.
  - *Subflow* : picker System (lazy-load via `canonical.listSystems`,
    exclut le `systemId` courant pour bloquer l'auto-récursion
    triviale), `input_map` key=value multi-ligne.
  - *Task* : `params` rendus depuis `Skill.input_schema` en
    JSON-schema-lite (types `string` / `number` / `integer` /
    `boolean`, `enum` → select, `required` → astérisque rouge) +
    textareas `inputs_map` / `outputs_map` pour les routings avancés.
  - Styles (`.df-kind-editor`, `.df-field-label`, `.df-branch-row`,
    `.df-ghost-btn`, `.df-icon-btn`, `.df-param-row`) — cohérents avec
    la palette existante (brand violet focus, amber pour les warnings).
  - **Smoke** (`/tmp/e33_smoke.py`, TestClient) : flow de 10 nœuds
    exerçant chaque kind, PATCH → 200 v2, relecture vérifie que les 8
    shapes de config survivent round-trip. Toutes les assertions vertes.
  - **Backend intact** : le DAG validator n'a rien à dire sur les
    nouvelles clés (`params`, `inputs_map`, `outputs_map`, etc.) — il
    vérifie la structure du graphe, pas la forme des configs, donc
    E3.3 est 100% frontend.

- **2026-04-24 — E3.4 (export / import JSON) livré, E3 CLOSED.**
  Un chain peut désormais être emballé dans une enveloppe JSON portable
  (aucun ID DB, skills par `slug`) et réimporté dans un autre workspace,
  avec re-binding automatique contre le catalogue local.
  - **Backend** :
    - `services/chains/export_service.py` (nouveau) : `SCHEMA_VERSION=1`,
      `ENVELOPE_KIND="agentium.system.export"`. `serialize_for_export`
      strip `skill_id` de chaque node task (garde `skill_slug`) et
      résout `skill_ids` → `skill_slugs` au niveau système.
      `prepare_import` fait le chemin inverse : lookup Skill par slug
      (préférence workspace-scoped > global), remplit
      `skill_id` sur les task nodes, renvoie un report
      `{ resolved_skills, unresolved_skills, task_node_rebinds }`. Les
      slugs non-résolus ne bloquent PAS l'import — l'opérateur lie
      manuellement après coup.
    - `api/v1/endpoints/systems.py` : `GET /systems/{id}/export`
      (audit `chain.export`) et `POST /systems/import`
      (audit `chain.import` avec compteur `task_rebind_count` +
      `unresolved_skills`). L'import passe le flow dans le DAG
      validator — un flow structurellement cassé (cycle, orphan…)
      renvoie le même 400 `flow_invalid` que `PATCH /systems`. Envelope
      malformée → 400 `invalid_envelope` (distinct de flow_invalid).
    - 7 tests unitaires dans `test_chain_export_service.py` : round-trip
      export/import, unresolved slugs surfacés sans échec, wrong kind
      / wrong schema_version → `ChainExportError`, override
      `target_name`. **32 tests chains verts au total.**
  - **Frontend** :
    - `canonical-api.service.ts` : types `SystemExportEnvelope`,
      `SystemImportReport`, discriminated union `SystemImportResult`
      (`ok=true` avec system + report ; `ok=false` avec
      `reason: 'invalid_envelope' | 'flow_invalid' | 'network'`).
      Méthodes `exportSystem`, `importSystem`.
    - `workflow-editor.component.ts` : deux nouveaux boutons toolbar
      (**Export** visible seulement sur un System persisté ; **Import**
      toujours dispo). Export déclenche un download Blob en deux clics,
      nom de fichier slugifié. Import ouvre un modal (paste JSON OU
      upload `.json` ≤ 2 MiB), champ optionnel `target_name`, validation
      côté client (kind + schema_version) avant POST. En cas de succès,
      toast + navigation vers le clone. Si des skills sont unresolved,
      le report les liste sous forme de chips amber et le toast est
      "warning" plutôt que "success" pour signaler qu'il reste du
      binding à faire.
    - Styles (`.df-modal--wide`, `.df-modal-textarea`, `.df-import-*`) :
      modal plus large pour accueillir le textarea + le report.
  - **Smoke HTTP** (`/tmp/e34_smoke.py`) : export d'un system avec un
    task node skill-bound → envelope conforme (skill_id stripped,
    skill_slug kept) → import en clone → skill re-binding automatique
    sur le task node (même `skill_id` en target car skill globale),
    params `{temperature: 0.2}` préservés, v1 seeded. Scénarios
    d'erreur vérifiés : envelope `kind: bogus` → 400 `invalid_envelope`,
    flow cyclique → 400 `flow_invalid`. Tous verts.
  - **Résultat** : E3 est bouclé. Un praticien peut désormais construire
    une chain, la valider en live via la strip d'issues, versionner
    chaque save, parcourir et rejouer l'historique, éditer proprement
    chaque kind-spécificité dans l'inspector, et l'exporter/importer
    entre workspaces sans régénérer la config à la main. Les vraies
    limitations restantes (params editor reste JSON-schema-lite, pas
    de drag-drop pour réordonner les branches, pas de diff visuel
    granulaire dans le panneau Versions) sont du polish, pas des gaps
    produit.

- **2026-04-25 — E1.5.1 livré : la boucle d'éval n'est plus
  read-only.** Avant ce patch, accept/reject sur une `Decision(kind=
  review_required)` filée par l'auto-eval ne faisait que flipper le
  status. La copie UI "Rejected = kept for retraining signal" était un
  mensonge — aucune table ne portait ce signal. Maintenant :
  - **Migration 016 `evaluation_feedback`** : `(workspace_id, decision_id?,
    run_id, evaluation_score_id?, label, notes?, corrected_output?,
    created_by, created_at)`. Label fermé enum
    `{false_positive, true_breach, correct_with_fix}` validé app-side.
    `decision_id` nullable pour qu'un futur 👍/👎 from-chat puisse
    écrire ici sans passer par le state-machine Decision. Indexed sur
    `(workspace, created_at desc)`, `run_id`, `decision_id`.
  - **Service `feedback_service.record_feedback`** : single write path,
    valide le label + flush + emit audit `evaluation.feedback.recorded`
    via la session du caller pour transactional co-location.
  - **Endpoints branchés** : `POST /hypervisor/decisions/{id}/accept|
    reject` accepte maintenant `feedback_label`, `feedback_corrected_output`
    dans le body. Default label mappe la transition (accept →
    `false_positive` = "judge over-flagged", reject → `true_breach` =
    "judge was right, response IS bad"). Le wiring est strictement
    no-op sur les Decisions non-eval (scope!=run ou kind!=review_required)
    pour ne pas polluer le canal Hypervisor recommendations
    génériques. Nouveau `GET /evaluation/feedback?run_id|decision_id|
    label` pour les consommateurs analytics (E1.5.3) + future
    surface "this run was triaged by alice" sur le run-detail.
  - **Tests** : 7 unit tests sur le service (108/108 vert sur la
    suite services). Smoke VM `/tmp/e151_smoke.py` 7/7 vert :
    accept/reject default labels, override correct_with_fix +
    corrected_output, label invalide → 400, non-eval Decision skip
    feedback, isolation cross-workspace → 0 rows visible.
  - **Pourquoi c'est P0** : sans cette table, tout le reste de E1.5
    (re-run with override, per-skill breach analytics, LLM-backed
    suggestion) construit sur du sable. C'est la fondation factuelle
    qui transforme le triage manuel en signal exploitable.

- **2026-04-25 — E1.5.2 livré : la review queue peut maintenant
  *agir*, pas seulement triager.** Avant ce patch, un reviewer qui
  voyait un run breaché avait deux options : accepter (= ignorer)
  ou rejeter (= garder en signal). Aucune des deux ne produit une
  meilleure réponse. Maintenant un troisième bouton **RE-RUN** ouvre
  un modal qui re-exécute le run avec un prompt / RAG mode / model
  tweakés, sans quitter la queue. C'est le passage du triage passif
  à la remédiation directe.
  - **Migration 017 `run_replay_lineage`** : `runs` gagne
    `parent_run_id` (String(36) nullable, indexé) et `replay_overrides`
    (JSON nullable). Le trigger enum accepte `"replay"` en plus des
    valeurs existantes. Schéma minimal volontaire : on ne veut pas
    re-modéliser tout le run en double, juste pouvoir répondre
    "comment ce run a-t-il été dérivé d'un autre ?" et "qu'est-ce
    que l'opérateur a changé ?" sans differ deux blobs JSON.
  - **Service `replay_service.replay_run_async`** : assemble le
    request_dict orchestrator depuis `parent.input_ref` + body
    overrides (rule = overrides win, parent fills the rest), drive
    le chat orchestrator, persiste le nouveau Run avec `parent_run_id`
    pointant vers l'original, déclenche `schedule_eval` pour que le
    reviewer ait un nouveau score à comparer. Override surface
    explicite : `query`, `rag_pipeline_mode`, `model`, `provider`,
    `system_prompt`, `temperature`, `max_tokens`, `top_k`,
    `similarity_threshold`, `prompt_type`. Les clés inconnues filent
    dans `agent_preferences.custom_overrides` pour forward-compat.
    *Out of scope MVP* : runs DAG-engine (`flow_snapshot` set + system_id)
    → 400 avec message "open the run and re-launch from the system
    page" ; pas de mock-up silencieux d'un chemin différent.
  - **Endpoints `/runs/{id}/replay` + `/runs/{id}/replays`** : POST
    accepte `overrides` + `actor` + `source_decision_id` +
    `source_feedback_id` (lineage audit pour répondre "combien de
    replays la queue a-t-elle réellement déclenchés ?"). GET liste
    les enfants (newest first) avec `replay_overrides` et
    `evaluation_scores` joints, utilisé par le run-detail futur et
    par la queue pour signaler "ce Decision a déjà X tentatives
    de remédiation". Audit `run.replayed` capture parent / new run
    / overrides / source / status / duration.
  - **UI review queue (RE-RUN modal)** : 3ème bouton à côté de
    ACCEPT / REJECT, désactivé si pas de run lié. Ouvre un modal
    inline avec champs `QUESTION` (préfilled depuis le run parent),
    `RAG MODE` (dropdown auto/naive/hybrid/hah/chah/keep), `MODEL`
    (input texte free-form). Submit POST `/runs/{id}/replay`,
    affiche inline `run_id` + `status` + `duration_ms` +
    `response_preview` + hint "evaluation pending" + lien deep-link
    vers le nouveau run. Toast ngx-toastr en parallèle pour la
    confirmation visible quand le reviewer scroll la queue.
  - **Tests** : 15 unit tests sur le service (123/123 vert sur la
    suite services). Smoke VM `/tmp/e152_smoke.py` 8/8 vert : happy
    path avec model+rag override (assert le request_dict
    orchestrator réellement patché), GET /replays liste correctement,
    replay-of-replay (chained lineage), pending parent → 400, DAG
    engine → 400 avec message engine, run inconnu → 404, isolation
    cross-tenant (POST + GET → 404 sur foreign workspace), audit
    `run.replayed` contient `source_decision_id` et `new_run_id`.
  - **Pourquoi c'est game-changer** : E1.5.1 a transformé "j'ai vu
    le breach" en "j'ai un signal". E1.5.2 transforme "j'ai un
    signal" en "je peux corriger sur place". Le reviewer reste
    *dans la queue*, ne change pas de surface, et obtient une
    nouvelle évaluation comparable au breach initial. Le reste de
    E1.5 (per-skill analytics + auto-onboard + LLM-suggestion) peut
    s'appuyer sur ces deux fondations sans nouvelle table.

- **2026-04-25 — E1.5.3 livré avec décision Giskard : dépendance
  optionnelle offline, taxonomie native dans Agentium.** Après audit
  Dify/Giskard : Dify n'est pas une lib à embarquer (on reprend le
  pattern annotation reply), mais Giskard/RAGET ouvre une vraie
  perspective pour E1.5.5b (synthetic RAG testsets depuis la KB).
  Décision d'architecture :
  - **Pas de Giskard dans le hot path chat/orchestrator.** Le backend
    API et le chat restent utilisables sans `giskard[llm]`.
  - **Extra isolé** : `backend/requirements_giskard.txt` installe
    `giskard[llm]` au-dessus de `requirements.txt` pour worker offline
    / VM / nightly jobs.
  - **Adapter lazy import** : `services/evaluation/giskard_adapter.py`
    expose `configure_giskard_models`, `make_knowledge_base`,
    `generate_rag_testset`, `evaluate_rag_testset` et lève
    `GiskardUnavailable` si l'extra n'est pas installé ou si l'embedding
    model n'est pas configuré. Aucun import transitive côté app startup.
  - **Taxonomie native reprise de RAGET** : composants
    `generator`, `retriever`, `rewriter`, `router`, `knowledge_base`;
    question types `simple`, `complex`, `distracting`, `situational`,
    `double`, `conversational`, `unknown`; mapping question_type →
    composants en constante locale (`rag_components.py`) pour que le
    dashboard fonctionne sans dépendance externe.
  - **E1.5.3 impl livrée** : migration `018_eval_component_analytics`
    ajoute `evaluation_scores.question_type`, `failed_components`,
    `topic`; le judge demande `question_type` + `topic` dans le même
    appel LLM-as-judge; `auto_eval` infère `failed_components` depuis
    question type + seuils; `GET /evaluation/component-health` agrège
    la santé par composant; `GET /evaluation/review-queue?component=`
    filtre les Decisions attribuées à un composant; Quality dashboard
    affiche un strip "RAG component health · Giskard taxonomy" avec
    deeplink vers la queue filtrée.
  - **Tests / smoke** : `test_evaluation_rag_components.py` couvre
    normalisation, heuristique fallback, mapping Giskard, inférence
    de composants et agrégation. `test_giskard_adapter.py` vérifie le
    guard "KB trop petite" avant import Giskard. Suite services locale :
    127 passed, 2 skipped après réinstallation de `qdrant-client` déjà
    listé dans `requirements.txt`. Smoke VM `/tmp/e153_smoke.py` 5/5 :
    taxonomy, component-health, filtre review queue, composant invalide
    → 400, isolation tenant. Migration 018 appliquée sur VM, backend
    redémarré, build Angular VM OK (warning vendor CSS drawflow connu),
    bundle Nginx déployé.
  - **Spike Giskard** : venv isolé `/tmp/giskard-spike-venv`, install
    `giskard[llm]` OK (`giskard 2.19.1`). `KnowledgeBase` OK après
    `configure_giskard_models(embedding_model="text-embedding-3-small")`.
    Génération RAGET OK avec 8 chunks / 3 questions via `gpt-4o-mini`
    (`QATestset`, colonnes `question`, `reference_answer`,
    `reference_context`, `conversation_history`, `metadata`). Avec 2
    chunks, RAGET échoue côté UMAP/HDBSCAN topic discovery ; l'adapter
    impose donc `min_knowledge_rows=8` par défaut avant d'appeler Giskard.

- **2026-04-25 — E1.5.4 livré : l'eval loop est auto-onboardée, plus
  cachée derrière un opt-in.** E1.5.1/2/3 ont donné une boucle utile,
  mais tant que le preset restait `enabled=false` par défaut, un nouveau
  workspace pouvait utiliser Agentium sans jamais produire de signal.
  Ce patch inverse la posture : l'évaluation tourne par défaut, et le
  workspace peut explicitement opt-out.
  - **Defaults service** : `DEFAULT_EVAL_CONFIG.enabled=True`,
    `composite_min=70.0`, `hallucination_max=0.3`, `sample_rate=1.0`.
    Le resolver reste le même : system > capability > workspace >
    built-in defaults. Les overrides partiels continuent de merger sur
    les defaults, donc `{"enabled": false}` suffit à opt-out sans perdre
    les seuils si on réactive plus tard.
  - **Migration 019 `eval_default_onboard`** : seed un preset
    workspace explicite (`Agentium default evaluation loop`) pour chaque
    workspace existant qui n'avait pas déjà de preset. Config seedée :
    `enabled=true`, `composite_min=70`, `hallucination_max=0.3`,
    `dimension_min={safety:80, hallucination:50}`, `sample_rate=1`.
    Les workspaces avec preset existant ne sont pas écrasés.
  - **Opt-out UI documenté** : `/presets/evaluation` indique maintenant
    que l'auto-eval est enabled by default et que le switch sert à
    opt-out workspace-wide. Fallback slider composite côté UI passe à 70.
  - **Validation** : test resolver mis à jour + test opt-out explicite ;
    VM : migration appliquée après création d'un workspace pre-migration
    → preset seedé correctement ; API smoke GET `/evaluation/presets`
    retourne `enabled=true`, `composite_min=70`, puis PUT `enabled=false`
    résout bien `enabled=false` tout en gardant les seuils hérités.
    `test_auto_eval.py` 13/13 vert local + VM. Build Angular VM OK
    (warning vendor CSS drawflow connu), bundle Nginx déployé, backend
    redémarré.

- **2026-04-25 — E1.5.5 livré : suggestion active + canonical answer
  ferment la boucle.** Après E1.5.4, chaque workspace produit du signal
  par défaut ; E1.5.5 transforme ce signal en action appliquer depuis
  la review queue et en réponses déterministes réutilisables.
  - **Active suggestion sur Decision** : l'auto-eval ajoute
    `rationale.active_suggestion` aux Decisions `review_required`.
    `suggestion_service.generate_active_suggestion()` tente un LLM
    `gpt-4o-mini` pour produire un JSON d'action concret
    (`action_type=rerun_with_overrides`, `overrides`, `expected_effect`,
    `confidence`) et retombe sur un fallback déterministe si le LLM
    échoue. Les suggestions ne changent pas la réponse utilisateur :
    elles sont attachées au triage.
  - **Apply button** : nouveau endpoint
    `POST /hypervisor/decisions/{id}/apply-active-suggestion`. Pour
    l'action MVP `rerun_with_overrides`, il appelle `replay_run_async`
    avec les overrides suggérés, puis transitionne la Decision
    `proposed -> accepted -> applied` avec `applied_patch` contenant
    `new_run_id`, `parent_run_id`, `status` et le payload suggestion.
    UI review queue : bloc **ACTIVE SUGGESTION** + bouton **APPLY**.
  - **Canonical answers (pattern Dify annotation reply, natif)** :
    migration 020 crée `canonical_answers` (`question`, `answer`,
    `normalized_question`, source ids, threshold, hit_count). Service
    `canonical_answer_service` expose create/find/hit/serialize avec
    audit `canonical_answer.created` + `canonical_answer.hit`. API
    `GET/POST /evaluation/canonical-answers`.
  - **Chat bypass déterministe** : `/chat/completion` et `/chat/stream`
    cherchent un canonical answer avant l'orchestrator. En hit, la
    réponse canonique est retournée directement, `hit_count` est
    incrémenté, un Run `trigger=canonical_answer` est persisté sans
    re-scorer, et l'orchestrator n'est pas appelé. Le lookup reste
    volontairement léger (normalisation + similarité token/Jaccard)
    pour ne pas introduire Qdrant/Giskard dans le hot path.
  - **Validation** : suite services locale 132 passed / 2 skipped.
    VM migration 020 appliquée ; tests ciblés VM 16/16 ; smoke
    `/tmp/e155_smoke.py` 3/3 : APPLY crée un replay avec overrides et
    marque la Decision applied, POST canonical answer OK, chat completion
    hit canonical et bypass orchestrator même si l'orchestrator stub
    n'est pas initialisé dans le chemin normal. Build Angular VM OK
    (warning drawflow connu), bundle Nginx déployé, backend redémarré.

- **2026-04-25 — E2 livré : Playwright passe enfin sur la VM.**
  Le scaffold existait depuis le 24/04 mais n'était ni installé ni
  exécutable sans fixtures externes. E2 est maintenant un harness
  reproductible contre `https://agentium.papai.ai`.
  - **Activation réelle** : `@playwright/test` ajouté en devDependency,
    `npx playwright install chromium` exécuté sur VM, `workers=1` forcé
    dans `playwright.config.ts` pour éviter les grants Keycloak
    concurrents sur la VM partagée.
  - **Auth robuste** : le helper `loginAsAlice` utilise le vrai
    `/api/v1/auth/login` (direct access grant) puis stocke
    `agentium_token` en localStorage, exactement comme le frontend.
    Credentials VM : `alice@acme.test` / `alice-demo`. Test invalid
    creds = 401 réel.
  - **Fixtures self-contained** : les PDFs drop-and-ask sont générés
    dynamiquement par `fixtures/pdf.ts` ; les systems HITL/debug sont
    créés dynamiquement via API auth dans leurs specs, puis supprimés
    via `DELETE /systems/{id}`. Plus de `scripts/test-vm.sh seed:e2e`
    bloquant.
  - **Flows verts** : `01-auth-keycloak` (3 tests), `02-chat-drop-and-ask`
    (PDF upload → réponse avec citation chip → sources), `03-hitl-approve`
    (run hitl_pending → accept → completed), `04-debug-step-continue`
    (run debug_pending → step → continue → completed), `05-eval-canonical-answer`
    (création canonical answer → chat hit déterministe → hit_count).
  - **Run VM** :
    `E2E_BASE_URL=https://agentium.papai.ai npx playwright test --project=chromium --reporter=list`
    → **7 passed (20.0s)**. Traces/videos restent en retain-on-failure.

- **2026-04-25 — E4.2 (Agentium Connector binaire) explicitement
  différé après E3 closure ; décision : on ne code rien tant que les
  prérequis ops ne sont pas tranchés.** L'utilisateur veut prioriser
  E1 (boucle d'évaluation, P0 game-changer) plutôt que E4.2 maintenant.
  E4.2 n'est PAS abandonné : le scope est figé, les questions
  bloquantes sont listées ici pour reprise propre.
  - **Pourquoi le différer maintenant** :
    - E4.2 est de la *release engineering* (PyInstaller spec + bundle
      Playwright browsers ~200 MiB + workflow GitHub Actions + GPG key
      + canal de distrib), pas du code feature. Aucune boucle de
      feedback exerçable en session : impossible de builder un AppImage
      sans Linux runner ni de déclencher le CI sans tag, qui
      lui-même suppose la clé GPG provisionnée.
    - Le fallback "copy-paste JSON dans la textarea" du connecteur Guest
      Link existe déjà côté UI (cf. `sharepoint-connector.component.ts`)
      donc E4b reste utilisable manuellement par un opérateur.
      L'absence du binaire dégrade l'UX, ne casse pas la feature.
  - **Scope figé pour E4.2 (rappel des décisions user 2026-04-24)** :
    - **Linux** : AppImage GPG-signed (`detached .asc` + `.SHA256SUMS`).
    - **macOS** : `.dmg` unsigned, doc Gatekeeper workaround au premier
      lancement (`xattr -d com.apple.quarantine`).
    - **Windows** : `.exe` unsigned dispo, doc SmartScreen +
      *fallback recommandé = mode CLI textarea JSON existant*. Pas
      d'EV cert (~400 €/an justifié seulement sur premier deal qui le
      finance).
  - **Ce qui reste à faire (livrables) — séquence de travail E4.2** :
    1. *E4.2.1 — PyInstaller spec + build script* (pure code) :
       - `tools/agentium-connector/build.spec` (spec PyInstaller,
         entrypoint = `scripts/sharepoint_connector_demo.py`, bundle
         Playwright browsers via `--collect-data playwright`).
       - `tools/agentium-connector/build.sh` (Linux), `build.ps1`
         (Windows fallback minimal). macOS partage `build.sh`.
       - Smoke local : `./build.sh` produit un binaire qui se lance et
         affiche `--help`. Pas de Playwright en CI sur cette étape (ça
         vient en E4.2.2).
    2. *E4.2.2 — GitHub Actions workflow* (release engineering, ne se
       teste qu'en CI) :
       - `.github/workflows/agentium-connector-release.yml` triggered
         on tag `v-connector-*`, jobs `build-linux` (ubuntu-latest +
         GPG sign si secret `GPG_SIGNING_KEY` présent), `build-macos`
         (macos-13, unsigned), `build-windows` (windows-latest,
         unsigned). Artefact upload sur GitHub Release.
       - Workflow doit échouer *gracieusement* en l'absence de la clé
         GPG (warning, pas error) pour que le premier dry-run sans
         secret reste vert.
    3. *E4.2.3 — Documentation utilisateur* :
       - `docs/agentium-connector-install.md` : instructions par OS,
         how-to GPG verify (Linux), Gatekeeper workaround (macOS),
         SmartScreen workaround (Windows). Lien depuis l'UI
         SharePoint connector quand auth=session.
    4. *E4.2.4 — UI deep-link* (frontend) :
       - Bouton "Launch Agentium Connector" qui ouvre `agentium://capture?token=<JWT>`
         (custom URL scheme enregistré par le binaire à l'install).
       - Fallback déjà présent (textarea copy-paste) si le binaire
         n'est pas installé. Fenêtre 30 s pour résolution avant
         timeout fallback.
  - **Questions bloquantes ops à trancher avant E4.2.2** :
    1. **Clé GPG** : (a) la clé Datategy corp existe-t-elle déjà,
       (b) qui en est custodian (tien personnel, équipe sec, KMS),
       (c) faut-il en générer une nouvelle dédiée
       `agentium-releases@datategy.io` ?
    2. **Canal de distribution** : (a) GitHub Releases sur le repo
       Bitbucket (impossible, pas le même hosting), (b) Bitbucket
       Downloads (limites de quota), (c) bucket S3 self-hosted
       (`releases.agentium.papai.ai`), (d) page de download statique
       sur `agentium.papai.ai/connector` qui tape un bucket privé ?
       Décision orientant le workflow CI (cible upload).
    3. **Apple Developer Program** : confirmé "non engagé" (~99 USD/an)
       — donc macOS reste unsigned avec doc Gatekeeper. À reconsidérer
       si un client réagit mal au warning au premier lancement.
  - **Critère de "E4.2 livré"** : le binaire Linux téléchargeable depuis
    la page `agentium.papai.ai/connector`, GPG-vérifiable via la clé
    publique exposée à `agentium.papai.ai/connector/key.asc`,
    se lance, ouvre Chromium, capture la session SharePoint, et POST
    le payload sur `/api/v1/sharepoint/session/upload` du backend
    cible. macOS + Windows livrables suivent dans la même release.
  - **Sortie** : tickets E4.2.1 → E4.2.4 ouverts dès que ops a tranché
    les 3 questions ci-dessus. En attendant, le fallback textarea reste
    le path utilisable.

- **2026-04-24 — Décisions roadmap E3 + E4.2 confirmées par le lead
  produit.**
  - **E3 versioning** : rolling window fixe de **500 versions par
    chaîne** (au lieu de full history illimité ou last-N configurable
    par workspace). Profondeur d'historique très large (plusieurs mois
    de modifs quotidiennes) avec un plafond dur qui garantit que la
    table `system_versions` ne fera pas dérailler Postgres à long
    terme. Exposé via `CUSTOM_CHAIN_VERSION_WINDOW` (default 500) pour
    ajuster sans migration si un client demande plus/moins.
  - **E4.2 signing** : pas de cert Apple Developer ni cert EV Windows.
    Linux : GPG signé (gratuit). macOS : unsigned, Gatekeeper bypass
    documenté. Windows : non prioritaire (SmartScreen bloque, fallback
    CLI textarea maintenu). Budget certs = 0 USD jusqu'au premier deal
    qui justifie l'engagement.
  - Conséquence : **E3 et E4.2 sont désormais tous deux déblocables
    sans dépendance externe**. La file prioritaire devient E3 → E4.2
    → E4.3 (ce dernier reste en attente d'admin consent client).
