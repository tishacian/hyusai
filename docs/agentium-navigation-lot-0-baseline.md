# Agentium navigation — Lot 0 contract baseline

Date de capture initiale : 2026-07-14
Date de clôture Lot 0 : 2026-07-15
Environnement observé : `https://agentium.papai.ai`, VM `omnirag-demo`
Révision de référence avant Lot 0 : `397fbeb452289f5c5f02d7d5bdd81b057e624540`
Révision applicative Lot 0 déployée et vérifiée : `1df8b79d63ea7eb62fbba3391f7283b40f94181f`
Alembic : `056_andritz_chat_asset_binding`

Le commit qui porte l'attestation finale est documentaire, postérieur au
déploiement et non déployé. Le SHA applicatif exécuté par la VM et les images
OCI reste celui indiqué ci-dessus.

## Objet

Ce document fige le contrat utilisateur et technique existant avant le
réalignement de la navigation Agentium. Il ne décrit pas l'architecture cible :
il définit ce qu'une migration ne doit pas casser.

Les sources de preuve sont :

- les parcours UI réels exécutés contre la plateforme déployée ;
- les endpoints publics authentifiés ;
- un audit VM et base de données strictement en lecture seule ;
- les tests de contrat backend et frontend ajoutés au dépôt.

Les tests du Lot 0 reçoivent les identifiants uniquement par variables
d'environnement et ne les écrivent ni dans les captures, ni dans les rapports
Playwright. L'audit Lot 0 a toutefois retrouvé un ancien secret opérateur dans
le contenu suivi. Le Lot 0 supprime ces valeurs par défaut et ajoute un gate
anti-récidive. La rotation a été confirmée avant déploiement ; l'historique Git
restant concerné, l'ancienne valeur demeure considérée comme compromise.

## Baseline des workspaces

| Workspace | Expérience | Home | Contrat visible |
|---|---|---|---|
| Andritz | `builder` + `business_end_user` | `/chat` | Recherche, Client360 PDR, Capture de connaissances |
| Agentium Showcase | mode legacy `portfolio`, `persona_nav=full` | cockpit standard | rail et surfaces Agentium complets |
| Sentinel-CI | `demo`, shell `immersive` | `/hypervisor/mission-room/cockpit` | Mission Room, AYA, sept entrées métier |
| Octocity Mission Room | `demo`, shell `immersive` | `/hypervisor/mission-room/cockpit` | Mission Room, OCTAVE, sept entrées métier |

`portfolio` n'appartient pas au type frontend actuel des modes. Son maintien
dans Showcase est un comportement legacy à adapter, pas une nouvelle valeur à
propager.

## Contrat Andritz à ne pas régresser

### Profil et surfaces

```json
{
  "key": "business_end_user",
  "default_route": "/chat",
  "primary_surfaces": ["chat", "client360-pdr", "knowledge-capture"],
  "advanced_access": "admin_only"
}
```

Pour un business user, les routes contractuelles sont :

- `/chat` — Recherche ;
- `/client360` — Client360 PDR ;
- `/knowledge/capture` — Capture de connaissances ;
- `/account/**` — compte utilisateur.

La synthèse historique `agentium-andritz-intro-agent-tiers.md` mentionne encore
un mini-shell à deux surfaces (`/chat` et `/knowledge/capture`). La capture
runtime, la configuration `business_end_user` et les contrats Lot 0 établissent
désormais trois applications avec Client360. Cette ligne historique ne doit
donc pas être utilisée comme contrat de régression tant que son auteur ne l'a
pas réconciliée.

Pour un owner/admin, le cockpit Agentium complet reste le comportement par
défaut. Le business shell est une preview explicite et réversible.

Les deep links, reload, back et forward doivent conserver la même route et le
même workspace. Chaque appel authentifié doit porter
`X-Workspace-Slug: andritz`, y compris après renouvellement du token.

### Systems actifs

Les cinq Systems actifs observés doivent rester distincts :

| System | Variant | Rôle |
|---|---|---|
| `Andritz Workspace Chat` | `chat_transverse_v1` | System canonique de `/chat` |
| `Andritz Chat Agentic` | `chat_agentic_thinking_v1` | délégation des intentions agentiques spécialisées |
| `Andritz Expert Knowledge Capture System` | `expert_knowledge_capture` | Capture de connaissances |
| `Client360 PDR` | `client360_pdr` | workspace app Client360 |
| `News Lab` | `intelligence` | intelligence/recherche transverse |

Les deux Systems Chat ne sont pas des doublons. La configuration runtime
`enable_agentic_chat=true` active le dispatch vers le System agentique avec
fallback classique. Une migration ne doit ni les fusionner, ni en retirer un.

### IAM effectif

Configuration Andritz observée :

```json
{
  "version": 3,
  "role_flags": {
    "contributors_see_only_own_sessions": true,
    "reviewers_inherit_contributor": true,
    "require_second_eye_for_ingestion": false
  },
  "capability_overrides": {}
}
```

Contrat d'accès actuel :

| Persona | Recherche | Knowledge Capture | Client360 |
|---|---|---|---|
| viewer | sessions propres | runtime vocal uniquement ; sessions/création refusées | lecture et mutations membership-scoped |
| contributor | sessions propres | crée et opère ses sessions | lecture et mutations membership-scoped |
| reviewer | sessions propres | crée, lit globalement et revoit ; pas de mutation d'une session étrangère | lecture et mutations membership-scoped |
| admin/owner | lecture transverse auditée, mutations propres | accès global et revue | lecture et mutations membership-scoped |
| non-membre | refusé | refusé | refusé |

Le fait que Client360 soit actuellement membership-scoped, y compris pour les
mutations, est une baseline de compatibilité et non la politique IAM cible.
Un futur durcissement doit être shadowé, mesuré et migré séparément de la
navigation.

### Preuve d'usage

Au moment de l'audit, les trois parcours contiennent des données actives :

- Chat : sessions actives et archivées ;
- Capture : plus de deux cents sessions et des propositions publiées/en revue ;
- Client360 : sources prêtes, opportunités, mappings, brouillons d'e-mail et
  événement d'impact.

Ces volumes sont mouvants. Les gates vérifient `> 0`, la visibilité et les
statuts attendus, jamais les nombres exacts.

## Contrat Showcase, Sentinel et Octocity

### Showcase

- shell Agentium standard ;
- title bar, side rail et Object Index présents ;
- sept Systems actifs visibles lors de la capture ;
- aucune Mission Room imposée.

Le chiffre sept est une observation de la capture, pas un invariant de
navigation : les volumes de Systems restent mouvants. Le contrat E2E Showcase
exige donc explicitement au moins un System visible (`> 0`) tout en verrouillant
le type de shell ; il ne transforme pas ce volume observé en égalité stable.

### Sentinel-CI

- shell Mission Room immersif sans chrome Agentium standard ;
- assistant `AYA` et branding Sentinel ;
- sept entrées : cockpit, stratégie/carte, sécurité, réputation, agenda,
  presse et arbitrages ;
- les sept entrées sont reliées à un System actif.

### Octocity

- shell Mission Room immersif ;
- assistant `OCTAVE`, branding Agentium/Octocity ;
- sept entrées visibles et aucun terme Sentinel dans le shell capturé ;
- état de référence avant Lot 0 : seulement trois entrées sur sept étaient
  reliées à un System actif. `cockpit`, `strategie`, `agenda` et `decisions`
  retournent `system_id=null` ;
- état Lot 0 déployé : les sept entrées sont reliées à quatre Systems OCTAVE
  actifs et idempotents (`Mission Room`, `Territorial Map`, `Open
  Intelligence`, `Decision Desk`). Les variants, templates et libellés sont
  propres à Octocity et ne réutilisent pas Sentinel.

Le `xfail(strict=True)` qui matérialisait la dette a été retiré dans le
Lot 0. Sur le rollout initial, la liste seed-owned est passée de un à quatre
Systems, soit trois créations ciblées. Sur le SHA final, les quatre IDs sont
identiques avant/après ; une première réconciliation a restauré le System
générique `Workspace Chat`, puis la seconde exécution a retourné
`systems_created: 0`. La carte runtime reste liée à un System actif et contient
12 layers, 5 zones, 11 signals et 5 scores. Le parcours live final confirme
les sept liaisons actives et l'absence de contenu Sentinel/AYA.

## Couverture automatisée ajoutée

### Backend

`backend/app/tests/api/test_andritz_surface_access_contract.py`

- 31 cas paramétrés persona × surface ;
- vrai resolver workspace et vrai header `X-Workspace-Slug` ;
- Chat ownership/admin read-only ;
- matrice Capture ;
- comportement Client360 membership-only ;
- refus non-membre et isolation inter-workspace.

Résultat consolidé final du candidat : `289 passed` sur 18 fichiers couvrant
Andritz, Chat, Capture, IAM, Client360, Mission Room, cartes/workers, wrappers
de skills, télémétrie, dépôt sécurisé, rollback du seed, ingress, provenance
et credentials. Le gate credentials couvre également les variables du contrat
E2E live et interdit explicitement le suivi des fichiers runtime
`docker/env/*.env`. Aucun `xfail` Octocity ne subsiste.

`backend/app/tests/services/test_mission_room.py`

- Sentinel/Octocity seed et anonymisation ;
- gate de liaison des sept entrées Mission Room ;
- mapping exact, isolation Sentinel/Octocity et idempotence du seed ;
- upgrade cartographique non destructif : settings, lignes opérateur et IDs
  existants sont conservés, tandis que les anciens éléments seed sont migrés ;
- vraies exécutions des wrappers de score/commande, chat OCTAVE France,
  seconde carte (détail, score, commande, cinq wrappers, renderer propre) et
  bounds numériques du cockpit ;
- résultat du fichier Mission Room : `17 passed` dans le run consolidé.

### Frontend unitaire

- `auth.interceptor.spec.ts` : le retry après 401 conserve
  `X-Workspace-Slug`, y compris pour deux 401 concurrents qui partagent un
  seul refresh ;
- `navigation-profile.service.spec.ts` : ordre stable des trois surfaces et
  preview admin opt-in ;
- `navigation-telemetry.service.spec.ts` : résolution directe, redirects,
  canonicalisation des routes et émission différée sans PII.

Résultat frontend final : `76 passed` ; le build Angular réussit avec les
warnings de budget/CommonJS déjà présents avant le lot.

Le défaut de retry détecté par le nouveau test a été corrigé en repassant la
requête déjà enrichie au handler de refresh. Deux tests supplémentaires
verrouillent la conservation d'une décision de redirect lorsqu'Angular annule
une navigation avec `SupersededByNewNavigation`, ainsi que son absence de fuite
vers une destination concurrente.

### E2E live opt-in

`frontend-ng/e2e/tests/09-live-workspace-contract.spec.ts`

La suite exige `E2E_LIVE_CONTRACT=1` et des secrets injectés par variables
d'environnement. Elle est inactive dans une exécution locale/CI ordinaire.
`E2E_BUSINESS_USERNAME` et `E2E_BUSINESS_PASSWORD` ne sont exigés que lorsque
le dixième scénario est activé par `E2E_LIVE_NON_ADMIN=1`.

Elle vérifie et capture :

- le business shell Andritz et ses trois liens exacts ;
- le même shell activé sans preview pour un membre non-admin existant, derrière
  `E2E_LIVE_NON_ADMIN=1` ;
- les trois deep links, reload, back/forward et les headers workspace ;
- la différence preview business / cockpit admin ;
- le profil, les flags IAM et les cinq Systems actifs déployés ;
- le shell standard Showcase après chargement des Systems ;
- les shells immersifs Sentinel et Octocity après chargement complet ;
- sept entrées Mission Room et absence de fuite `SENTINEL` dans Octocity.

La suite désactive explicitement trace et vidéo Playwright : une trace réseau
pourrait sinon sérialiser le corps du login. Les screenshots ne contiennent pas
le secret et chaque refresh token renouvelable est révoqué en `afterEach`.

Résultat live final sur `1df8b79d63ea7eb62fbba3391f7283b40f94181f` :
`9 passed, 1 skipped`. Les neuf contrats owner couvrent les trois applications,
les deep links, le cockpit admin, les cinq Systems Andritz, le refresh forcé,
la télémétrie pseudonymisée, Showcase, Sentinel et Octocity. Le dixième contrat
non-admin est resté ignoré faute de compte business dédié injecté ; sa preuve
n'est donc pas revendiquée.

Le premier run sur le SHA applicatif initial `a5b6082d…` avait produit
`8 passed, 1 failed, 1 skipped` : l'UI redirigeait correctement mais Angular
classait l'événement `/workspace` et sa cible comme deux navigations directes.
Le hotfix final conserve la décision pendant
`NavigationCancel(SupersededByNewNavigation)`. Le rerun prouve désormais une
ligne `navigation.resolved` exacte, canonique, pseudonymisée et sans slug
dynamique dans la route persistée. Les captures sont produites dans
`frontend-ng/e2e/results/` et ne sont pas versionnées.

## Observabilité et sécurité — état Lot 0

### Navigation — contrat déployé et prouvé

Le frontend émet désormais `navigation.resolved` via l'endpoint et la table
d'audit existants. Le payload versionné distingue :

- `requested_route` et `resolved_route` sous forme de chemins canoniques ;
- `effective_workspace`, imposé côté serveur depuis le workspace authentifié ;
- `effective_surface`, dérivé côté serveur de `resolved_route` canonicalisée
  avec les IDs stables du catalogue (`unknown` hors catalogue) ;
- `redirect_owner` et `redirect_reason`, limités à des valeurs machine connues ;
- `redirected` et `schema_version=1`.

Les redirects du profil métier, du shell et de l'entrée workspace enregistrent
leur décision explicite. Les redirects statiques Angular sont inférés depuis
`NavigationStart` / `NavigationEnd`. Une décision annulée ou en erreur est
purgée ; les annulations techniques créées par un `UrlTree` ou une navigation
superseded ne sont conservées que si la navigation suivante vise exactement
leur destination.

Le frontend masque déjà les paramètres de routes connus depuis son catalogue.
La frontière backend, qui reste autoritaire, supprime query et fragment,
canonicalise tous les segments dynamiques depuis le catalogue backend (`:id`,
`:slug`, `:segment`), ignore toute surface déclarée par le client, refuse les
champs additionnels et remplace l'acteur par
`authenticated_user`. Aucun email, identifiant utilisateur, texte libre ou
valeur dynamique de route n'est persisté. Si le premier `NavigationEnd`
précède le chargement des workspaces, la dernière résolution réussie est mise
en attente puis émise une seule fois lorsque le shell connaît le slug actif.

La preuve live finale retrouve le payload exact `/workspace` vers
`/workspace/:slug/settings`, avec surface `workspace-admin`, owner
`workspace_entrypoint`, reason `workspace_settings_entrypoint`, acteur
`authenticated_user`, trace/agent nuls et sévérité `info`.

### Sessions

Sur 96 heures, des rafales de 401 synchrones avaient été observées avant un
login manuel réussi. Les tests unitaires couvrent la conservation du slug après
refresh simple et concurrent. Le scénario live final force un bearer expiré,
observe un seul refresh, puis vérifie que chaque replay Client360 aboutit en
`200` avec le même `X-Workspace-Slug: andritz`.

Les parcours live ont été exécutés avec un owner en preview métier. La matrice
persona est couverte côté API. Le dixième contrat navigateur accepte un compte
business non-admin existant via variables d'environnement, mais il n'a pas été
exécuté lors de cette clôture ; la suite ne provisionne ni ne modifie ce compte.

Un warning Keycloak `Non-secure context detected; cookies are not secured` a
été observé pour le flux backend interne en HTTP. Les réponses OIDC publiques
et leurs cookies sont bien sécurisés derrière TLS. Le candidat durcit tout de
même la frontière `/kc/` en écrasant les headers proxy fournis par le client ;
ce changement ne prétend pas supprimer le warning interne.

### Ingress

Le fallback SPA retournait l'index HTML avec un statut 200 pour `/.env` et
`/.git/config` sur la révision de référence, sans exposer de fichier sensible.
Le Lot 0 refuse désormais tout segment caché avant le fallback SPA, sauf le
chemin ACME explicitement autorisé. La preuve finale donne `404` pour `/.env`,
`/.git/config` et `/assets/.secret`, puis `200` pour `/systems`,
`/api/v1/health` et la découverte OIDC. L'issuer reste canonique malgré les
headers proxy forgés et tous les cookies de session OIDC publics portent
`Secure`.

### Provenance des images

Le Lot 0 ajoute le label OCI `org.opencontainers.image.revision` aux images
frontend, backend et worker. Le script de déploiement injecte le SHA Git complet
explicitement validé et refuse un build si `origin/demo/agentic` ne pointe plus
sur ce SHA. Les audits local/post-build n'effectuent aucun fetch et refusent un
label d'image différent du SHA attendu. Avant le build, chaque image active est
taguée sous un namespace de rollback dédié au SHA candidat et son ID est écrit
dans un état no-clobber validé avant toute réutilisation. Les trois images
exécutées portent exactement `1df8b79d63ea7eb62fbba3391f7283b40f94181f`,
le checkout VM est propre et l'audit `--check-only` ne détecte aucune dérive.
L'état de rollback applicatif est
`/home/ubuntu/.local/state/agentium/deployments/1df8b79d63ea7eb62fbba3391f7283b40f94181f.tsv`.

### Secrets opérateur

Les scripts opérateur et leurs exemples exigent désormais
`AGENTIUM_EMAIL`/`AGENTIUM_PASSWORD` sans valeur réelle par défaut et échouent
avant tout appel réseau si une valeur manque. Un test scanne le contenu suivi à
partir d'une empreinte non réversible du secret retiré et interdit les defaults
d'authentification non vides. Ce gate ne nettoie pas l'historique Git et ne
remplace pas la rotation du compte. La rotation a été confirmée avant le
déploiement, le gate du contenu suivi est vert et l'entrée temporaire du
Trousseau utilisée pour les E2E a été supprimée après le run.

## Résultat de clôture

| Gate | Résultat observé |
|---|---|
| Backend et frontend | `289 passed` backend, `76 passed` frontend, build production vert |
| Live owner | `9 passed`, avec refresh forcé et télémétrie persistée |
| Live non-admin | `1 skipped` ; aucun compte business dédié n'a été injecté |
| Andritz | trois routes, cinq Systems, IAM et données actives conformes |
| Showcase | shell Agentium standard et Systems visibles |
| Sentinel / Octocity | shells immersifs, assistants, branding et sept entrées conformes |
| Octocity 7/7 | quatre Systems OCTAVE actifs, IDs idempotents, aucune fuite Sentinel/AYA |
| Ingress / OIDC | dotpaths `404`, endpoints `200`, issuer canonique, cookies `Secure` |
| Provenance / rollback | trois labels OCI au SHA final, audit sans drift, états applicatif/ingress/seed conservés |
| Secrets | rotation confirmée, gate anti-récidive vert, secret E2E temporaire supprimé |

## Gates avant activation d'une nouvelle navigation

1. Tous les tests backend Andritz restent verts.
2. Les neuf tests live owner, dont la persistance de télémétrie et l'expiration
   forcée, passent contre l'environnement candidat ; le dixième contrat
   non-admin passe lorsqu'un compte business existant est injecté.
3. Les trois routes Andritz, leurs Systems et leurs flags IAM sont identiques.
4. Aucun droit Client360 n'est retiré dans le chantier navigation.
5. Le retry conserve le slug et aucun ID d'un autre workspace n'apparaît.
6. Showcase reste en shell standard.
7. Sentinel et Octocity conservent leur shell, branding, assistant et sept
   entrées.
8. Les sept liaisons Octocity sont actives après seed et aucun identifiant
   Sentinel n'apparaît dans leur payload.
9. Un rollback par feature flag est disponible avant tout changement visible
   sur Andritz.
10. Les dotpaths sont refusés, les endpoints SPA/OIDC restent disponibles et
    les images exécutées portent le SHA déployé.
11. Le secret compromis est absent de tout contenu suivi ; aucune identité
    personnelle ne sert de default ou d'allowlist dans le code exécutable ; le
    secret historique est remplacé avant mise en production. Les identités
    visibles dans des fixtures ou contenus de démonstration ne sont pas, à
    elles seules, un credential exécutable.

## Commandes de vérification

La séquence complète commit → images → ingress → seed → preuves live est
décrite dans `docs/ops/navigation-lot-0-rollout.md`.

```bash
cd backend
.venv/bin/pytest app/tests/api/test_andritz_surface_access_contract.py -q
.venv/bin/pytest app/tests/api/test_navigation_audit_api.py -q
.venv/bin/pytest app/tests/services/test_mission_room.py -q

cd ../frontend-ng
PATH="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH" \
  node scripts/run-unit.mjs

E2E_LIVE_CONTRACT=1 \
E2E_LIVE_FORCE_REFRESH=1 \
E2E_LIVE_ALL_WORKSPACES=1 \
E2E_LIVE_NON_ADMIN=1 \
E2E_WORKSPACE_SLUG=andritz \
E2E_USERNAME=... \
E2E_PASSWORD=... \
E2E_BUSINESS_USERNAME=... \
E2E_BUSINESS_PASSWORD=... \
E2E_CHROMIUM_EXECUTABLE="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  ./node_modules/.bin/playwright test 09-live-workspace-contract.spec.ts --project=chromium
```
