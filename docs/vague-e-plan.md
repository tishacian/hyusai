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
| E1 | Boucle d'évaluation — scoring auto post-run + threshold triggers + suggestion UI | P0 | L | D2, D6 |
| E2 | Playwright E2E — 4 flows critiques (auth Keycloak, chat drop-and-ask, HITL, debug replay) | P1 | M | D1, D7 |
| E3 | Custom chains editor — finition (node props, validation, save/load versions) | P1 | L | C6 |
| E4 | SharePoint ingestion v1 — deux connecteurs jumeaux partageant la même sync pipeline : **E4a SharePoint** (OAuth/MSAL standard, cas majoritaire) + **E4b SharePoint Guest Link** (capture session via Agentium Connector local, cas d'accès limité type Andritz). Fondation E4b livrée (`671a3a4`→`df4cf80`), UI + ingestion RAG commune + CLI packagée deep-link à construire ; E4a activable dès admin consent Andritz ou premier client avec Entra app. | P1 | L | D0 |
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

### E2 — Playwright E2E

Reporté de D6 (cf. note `backlog Playwright` du vague-d-plan). Stack
VM disponible, donc finissable maintenant.

**Scope minimal (4 flows) :**

1. **Auth Keycloak** — login alice → landing workspace → logout.
2. **Chat drop-and-ask** — drop 2 PDF → citation `[1]` cliquable →
   scroll to source.
3. **HITL Approve** — run avec hitl_pending → accept depuis `/runs/:id` →
   resume → completed.
4. **Debug Step/Continue** — run en mode debug → step skill → continue
   → outcome affiché.

Chaque flow a un fixture seedé dans `scripts/test-vm.sh` ; exécution
contre la VM staging (non prod). Run en CI hebdo pour catch les
régressions de surface.

**Done quand :** `npx playwright test` en CI retourne 4/4 green sur la
VM staging.

### E3 — Custom chains editor — finition

Le scaffold existe dans `/orchestration` (`workflow-editor.component`),
mais :
- Les node-props (skill picker, param forms) sont placeholders.
- Pas de validation `fork/join` cohérents.
- Pas de versioning des flows sauvés (save écrase, pas de diff).

**Scope :**
1. Node-props complets (skill picker via `/skills` scopé workspace,
   param form auto-généré depuis `Skill.schema_input`).
2. Validation bloquante : fork sans join correspondant, cycle, node
   orphelin, decision sans `true_branch_id`.
3. Versioning : chaque save crée un `SystemVersion` (id + created_at +
   created_by + dag_json), UI pour naviguer l'historique et rollback.
4. Export JSON → round-trip import (permet partage flow entre
   workspaces).

**Done quand :** un builder peut construire un flow fork/join/decision
depuis zéro, le valider, le lancer, le rollback d'une version.

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
| Agentium Connector bloqué par antivirus / SmartScreen | Deep-link inutilisable sur Windows | Code signing EV (Windows) + notarization (macOS) ; fallback textarea JSON systématique maintenu comme chemin dégradé |
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
