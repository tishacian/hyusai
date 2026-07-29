# SPEC — Préparation démo Nawa ITSD (29 juillet 2026, 12h00)

Note de délégation autonome. Le lecteur n'a aucun contexte préalable : tout ce
qu'il faut savoir est ici. En cas de doute sur une opération de production,
**s'arrêter et demander à Thibaud** plutôt qu'improviser.

---

## 1. Contexte et objectif

Démo client demain **mercredi 29/07 à 12h00** sur la plateforme Agentium de
production (`https://agentium.papai.ai`). Thème : automatisation des opérations
IT (ITSD) pour le prospect **Nawa** (contexte PIH/Qatar, voir
`docs/pih/Brief-FDE-Onboarding-POC-Qatar.md`).

La démo doit montrer :

1. Un **nouveau workspace `nawa`** avec une **charte graphique propre**
   (différente du thème cockpit sombre par défaut).
2. Un **System avec son flow dans le Flow Builder** qui **simule** la séquence
   de reset de mot de passe ITSD en 6 étapes (détail §6).
3. Une **application front dédiée** (même famille que les apps Andritz) :
   - page **catalogue** des ~40 use cases d'automatisation IT issus du fichier
     `docs/pih/IT Operations Automation Details.xlsx` (placeholders) ;
   - page **détail fonctionnelle de bout en bout** pour le use case
     « Password Reset » (déclenchement d'une simulation, progression des
     étapes, clôture).

## 2. Contraintes critiques — à lire avant toute action

### 2.1 Base de branche : PAS `demo/agentic`

La production tourne sur le SHA **`07f54a68db13cc21b480bdabf1737bfac6b77438`**
(branche `codex/release-a-from-hotfix`). La branche `demo/agentic` locale
contient les lots 7-9 (non déployés, Release B à venir) : **il est interdit de
brancher depuis `demo/agentic`, d'y merger, ou de la pousser**.

```bash
# Création de la branche de dev (depuis le worktree principal ou un worktree dédié)
git fetch origin codex/release-a-from-hotfix
git worktree add ../omnirag-nawa-demo -b feat/nawa-itsd-demo 07f54a68db13cc21b480bdabf1737bfac6b77438
```

### 2.2 Production fragile — périmètre d'intervention strict

La prod vient d'être rouverte le 28/07 au matin après une transaction Release A
interrompue (dérogation documentée dans `/root/night-r5/OPTION-B-OPENING-RECORD.md`
sur la VM). Interdictions absolues sur la VM :

- **Ne pas toucher** : `/srv/agentium-private/**`,
  `/srv/agentium-data/release-a-deployments/**`, les règles iptables, la conf
  nginx, le conteneur `agentium-sftp`, les conteneurs stateful
  (`agentium-pg`, `qdrant`, `agentium-minio`, `agentium-rabbitmq`), les
  restart policies, les unités systemd.
- **Ne pas** faire de `git pull`/`git reset` sur `/home/ubuntu/omnirag` en
  dehors de la procédure de déploiement du §8 (et jamais en tant que root :
  historique de fichiers passés root-owned qui ont cassé le backend).
- **Ne pas** lancer `scripts/deploy-vm.sh` ni
  `scripts/deploy-agentium-release-a-safe.sh` : ils appartiennent aux
  transactions attestées, pas à ce job.
- Aucune donnée des workspaces existants (`andritz`, `agentium-showcase`,
  `sentinel-ci`, `octocity-mission-room`) ne doit être modifiée.

### 2.3 Code rebase-friendly

Tout le nouveau code frontend vit dans **`frontend-ng/src/app/features/nawa/`**
(nouveaux fichiers). Les modifications de fichiers partagés se limitent au
strict enregistrement : `app.routes.ts`, `core/navigation.catalog.ts`, et si
nécessaire `core/workspace-experience.ts`. Idem côté backend : une migration
additive + le minimum dans les fichiers partagés. Objectif : rejeu trivial sur
`demo/agentic` après la démo (Release B apportera un framework
« workspace apps lifecycle » qui généralisera tout ça — ne pas l'anticiper).

## 3. Accès et environnement

| Quoi | Valeur |
| --- | --- |
| Prod UI/API | `https://agentium.papai.ai` |
| VM (SSH) | `ssh ubuntu@agentium.papai.ai` (sudo disponible) |
| Compte opérateur UI/API | `thibaud.ishacian@datategy.net` — mot de passe : `sudo cat /srv/agentium-private/.canary-op-pass` sur la VM |
| Token API (exemple) | `POST http://127.0.0.1:8080/kc/realms/papai-org/protocol/openid-connect/token` avec `grant_type=password`, `client_id=core-service` (depuis la VM) |
| Repo live sur VM | `/home/ubuntu/omnirag` @ `07f54a68` |
| Source use cases | `docs/pih/IT Operations Automation Details.xlsx` (feuille unique `End User Support`) |
| Images | construites localement sur la VM (`AGENTIUM_IMAGE_TAG=local`), pas de registry |

Topologie runtime actuelle (ne pas modifier hors §8) : nginx (hôte) → 
`agentium-frontend` (127.0.0.1:8081), `agentium-backend` (127.0.0.1:8001),
`agentium-kc` (127.0.0.1:8080), `agentium-livekit`, `agentium-sftp`
(0.0.0.0:2222), + stateful (pg, qdrant, minio, rabbitmq).

## 4. Patterns de référence dans le code (base `07f54a68`)

- **Recette complète d'onboarding d'une app surface** :
  `backend/alembic/versions/060_andritz_fse_reports.py`. Elle montre les 4
  gestes exacts : extension de la contrainte CHECK
  `ck_workspace_member_app_entitlements_app_key` (liste fermée des `app_key`),
  grant des entitlements aux membres, ajout de la surface dans
  `navigation_profile.primary_surfaces` des settings du workspace, insertion
  du System associé. **C'est le modèle à calquer pour Nawa.**
- **App workspace codée main** : `frontend-ng/src/app/features/client360/`
  (app métier riche) et `frontend-ng/src/app/features/mission-room/`
  (cockpit Octocity avec charte graphique propre — la preuve que la charte
  par workspace se fait au niveau du composant/feature, SCSS scopé + CSS
  custom properties).
- **Catalogue de navigation** : `frontend-ng/src/app/core/navigation.catalog.ts`
  (entrées avec `id`, `label`, `route`, `lens`, `apiPrefix`… — cf. entrées
  `client360-pdr`, `fse-reports`).
- **Classification/expérience workspace** :
  `frontend-ng/src/app/core/workspace-experience.ts` et
  `features/layout/business-shell-header.component.ts` (le shell « business »
  qui affiche les apps d'un workspace, utilisé par Andritz avec
  `navigation_profile.profile = workspace_experience_v2`).
- **API workspaces** : `backend/app/api/v1/endpoints/auth.py` —
  `POST /api/v1/auth/workspaces` (création),
  `PATCH /api/v1/auth/workspaces/{slug}` (settings),
  `POST /api/v1/auth/workspaces/{slug}/members`.
- **Validation des surfaces côté backend** :
  `backend/app/services/surface_catalog.py` — vérifier si les ids de surface
  sont validés côté backend ; si oui, y ajouter les surfaces Nawa (changement
  additif minimal).
- **Runs/simulation** : `backend/app/api/v1/endpoints/runs.py`,
  `systems.py`, et le pattern « dry-run » (utilisé par Client360). Le front
  déclenche un run et lit la progression via runs/traces.

## 5. Livrable A — Workspace Nawa + charte graphique

1. **Créer le workspace** en prod via l'API (`POST /api/v1/auth/workspaces`,
   slug `nawa`, nom « Nawa ») avec le compte opérateur. Ajouter les membres
   nécessaires à la démo.
2. **Settings** (via `PATCH /api/v1/auth/workspaces/nawa` ou la migration du
   livrable C, au choix du plus fiable — regarder comment 060 écrit
   `navigation_profile`) :
   - `navigation_profile.profile` : réutiliser `workspace_experience_v2`
     (shell business type Andritz) sauf blocage technique ;
   - `navigation_profile.primary_surfaces` : `["nawa-itsd"]` (+ `"chat"` si le
     chat doit être montré dans Nawa — à confirmer avec Thibaud, par défaut
     l'inclure).
3. **Charte graphique** : thème scopé à la feature (`features/nawa/`), via CSS
   custom properties surchargées au niveau du conteneur racine de l'app Nawa
   (palette, typo, logo). Pas de refonte du theming global — le bouton
   « Theme: Dark locked » du shell reste tel quel.
   - **Logo fourni** : `frontend-ng/src/assets/nawa/nawa-logo.png`
     (1024×297, fond **noir opaque**, pas de canal alpha) → à poser sur une
     surface sombre uniquement (header de l'app, écran de titre). Ne pas le
     placer sur fond clair sans redemander une version transparente.
   - **Palette extraite du logo** : noir `#000000`, anthracite `#1C1C1C`,
     accent brique `#C62F00`. Construire le thème Nawa sur ces trois valeurs
     (accent = actions, badges « Live », progression des étapes).
   - **Variante claire ajoutée le 28/07** : un service desk s'utilise toute la
     journée sur des écrans de bureau éclairés, donc l'app métier offre ce que
     le cockpit ne peut pas. Le `<html>` reste épinglé en sombre pour le chrome
     d'administration ; les surfaces WE posent leur propre `data-theme` et ne
     réécrivent que les tokens de marque (fond `#F7F5F3`, surfaces blanches,
     filets en noir-alpha, accent assombri d'un cran à `#B52A00` car la brique
     crie plus sur blanc que sur noir). La bascule pilote la préférence
     partagée du business shell, cycle Auto → Light → Dark, et persiste.
     **Attention en démo** : par défaut la préférence vaut « Auto », donc l'app
     suit le réglage système du portable — fixer explicitement le thème voulu
     d'un clic avant de présenter.
   - **Conséquence sur le logo** : le wordmark livré est un JPEG sur fond noir
     opaque, qui se lirait comme un rectangle noir sur en-tête clair.
     `nawa-logo-transparent.png` est le même dessin avec ce fond détaché (clé
     par remplissage depuis les bords puis nettoyage de l'alpha) ; le thème
     clair y bascule automatiquement.
4. **Nommage — arbitré le 28/07 par le sponsor.** La plateforme en marque
   blanche s'appelle **NAWA** ; l'application métier s'appelle **WE**
   (*Workspace Engine*). À l'écran, le lockup est le wordmark NAWA suivi du
   nom de l'app : les en-têtes titrent « WE · IT Service Desk » et
   « WE · Password Reset », avec « Workspace Engine — … » en sous-titre. Le
   texte ne répète jamais NAWA à côté du logo, qui le dit déjà.
   En prose descriptive (fiches du catalogue, prompts du flow, nom du System),
   le nom complet reste **« NAWA WE »** : « WE » seul se lirait comme le
   pronom anglais en milieu de phrase. **Interdiction absolue de faire
   apparaître le nom d'un concurrent** (voir §5.4).

### 5.4 Purge des marques concurrentes (bloquant)

Le fichier source `IT Operations Automation Details.xlsx` décrit la **cible
d'automatisation** en la formulant avec l'outillage d'un **concurrent, cité 53
fois sur 24 lignes**, plus deux noms de bots (6 + 1 occurrences). Quatre de ces
mentions sont dans des **intitulés de use cases**, donc directement affichées
dans notre catalogue si on extrait le fichier tel quel :

| # | Intitulé source | Intitulé à afficher |
| --- | --- | --- |
| 19 | Ticket creation & tracking through *\<bot\>* | Ticket creation & tracking (assistant) |
| 23 | Onboarding through *\<bot\>* | Onboarding (assistant-driven) |
| 35 | Collecting user hardware information through *\<bot\>* | Collecting user hardware information (assistant) |
| 39 | *\<concurrent\>* Dashboard Data Extractor | Automation Dashboard Data Extractor |

Règles pour le script d'extraction (§7.1) :

- **Substituer** toute occurrence du nom du concurrent par **« NAWA WE »**
  quand la phrase décrit le geste d'automatisation (« *\<concurrent\>* routes
  the requester… » → « NAWA WE routes the requester… »), et par une
  formulation neutre (« the assistant », « the automation ») quand la
  substitution serait fausse ou maladroite.
- **Neutraliser** les deux noms de bots selon le tableau ci-dessus.
- Le script doit **échouer bruyamment** (exit non nul) s'il reste une
  occurrence d'un terme de la liste noire dans le JSON produit : c'est le
  garde-fou, pas une relecture humaine.
- La liste noire vit dans le script (`BANNED_TERMS`), avec un commentaire
  expliquant pourquoi. Ne pas la mettre dans un fichier livré au client.
- Contrôle final avant démo : `rg -i` de la liste noire sur le JSON **et** sur
  le bundle frontend construit.

## 6. Livrable B — System « Password Reset » + flow (simulation)

Un System dans le workspace `nawa` dont le flow modélise les 6 étapes :

1. User contacts ITSD via call, email, or walk-in to request a password reset.
2. Verifies the user's identity (staff ID, manager confirmation, or security questions).
3. IT agent logs in to Active Directory (AD) and resets the user's password.
4. IT sets a temporary password and forces a reset on next login.
5. IT informs the user of the temporary password and guides them to log in and update it.
6. IT confirms the issue is resolved and closes the ticket.

- Construction **par API systems/flows** (et non par glisser-déposer : le nœud
  `hitl` n'est pas dans la palette du Flow Builder au SHA de prod, cf. §6.3).
  **Aucune intégration AD réelle** : les gestes système sont simulés (résultat
  plausible journalisé : identité vérifiée, mot de passe temporaire factice,
  ticket clôturé).
- Le flow doit être **visible et beau dans le Flow Builder** (nommage clair
  des nœuds, 6 étapes lisibles) : il sera montré à l'écran.
- Si la création du System requiert la migration du livrable C (cf. 060 qui
  insère le System en DB), faire porter l'insertion par la migration.

### 6.1 Deux nœuds d'inférence réelle + un gate humain (obligatoire)

**Lecture correcte du fichier source** (`docs/pih/IT Operations Automation
Details.xlsx`) : la colonne « Manual process » décrit **ce qui se fait
aujourd'hui à la main** — les 6 étapes ci-dessus sont exactement ce processus
manuel — et la colonne « Automated Process » décrit **la cible à construire**,
avec un compte d'agents prévisionnel (**469 agents planifiés pour 39
automatisations**). Rien de tout cela ne tourne encore : c'est le périmètre du
projet, pas un existant à concurrencer.

Conséquence pour le flow : il modélise la reprise du **processus manuel** par un
agent, et il doit contenir au moins deux points d'inférence réels et un point de
gouvernance — sinon on présente un enchaînement scripté qui ne se distingue pas
d'un simple RPA. Répartition des 6 étapes :

| Étape | Implémentation | Skill |
| --- | --- | --- |
| 1. Intake (call/email/walk-in) | **LLM — classification d'intention** sur texte libre, sortie **contrainte à un enum** (`password_reset`, `unlock_ad_account`, `password_expiry`, `other`) + score de confiance | `azure_llm_v1` (certifié production) — alternative `chat_action_resolver_v1` ; `ollama_llm_v1` si un modèle local est servi |
| 2. Vérification d'identité | **LLM — appréciation des preuves** (staff ID / confirmation manager / questions de sécurité) vs politique, avec **abstention explicite** si insuffisant → branche vers le gate | `azure_llm_v1` |
| 2b. Gate humain | **Decision / gate durable avec expiration** — franchi uniquement si l'étape 2 s'abstient ; l'approbation se fait dans l'écran natif de la plateforme (run detail / inbox), pas dans l'app Nawa | primitive plateforme |
| 3. Reset AD | Simulé (écriture privilégiée en sémantique dry-run) | step interne |
| 4. Mot de passe temporaire + forçage | Simulé | step interne |
| 5. Information de l'utilisateur | **LLM — rédaction du message EN/AR** (guidage changement de mot de passe) | `azure_llm_v1` |
| 6. Clôture du ticket | Simulé + **écriture au ledger d'audit** | step interne + `audit_log_v1` |

Les étapes 5 et 6 peuvent partager un seul appel LLM si le budget de latence
l'exige (§6.4).

### 6.2 Scénarios injectables — les edge cases qui portent le discours

Le run accepte un paramètre d'entrée `scenario`. Le flow branche dessus et
**les branches doivent être lisibles dans le Flow Builder** (c'est un atout à
montrer, pas un artifice à cacher). Chaque scénario existe pour prouver un
point de positionnement précis :

| Scénario | Entrée | Comportement attendu | Ce que ça prouve |
| --- | --- | --- | --- |
| `nominal` **(P0)** | « I forgot my password, can you reset it? » + preuves d'identité complètes | Les 6 étapes passent, ticket clôturé | Le résultat métier, à parité avec l'existant |
| `ambiguous` **(P0)** | « mon compte est bloqué depuis ce matin, j'ai tapé trois fois » | La classification rend `unlock_ad_account` avec sa justification → le run **ne reset pas** de mot de passe et sort en « routé vers use case #2 » | **Quality** : l'agent discrimine au lieu de deviner. Aujourd'hui c'est un humain de l'ITSD qui fait ce tri au téléphone ; une cible à base de formulaires en ferait un menu par cas. Une seule porte d'entrée couvre leurs #1/#2/#14 qui sont adjacents |
| `weak_identity` **(P0)** | Demande légitime mais preuves insuffisantes (pas de confirmation manager) | L'étape 2 **s'abstient** → gate humain avec expiration → approbation opérateur dans l'écran natif → le run **reprend** et se clôture | **Gouvernance/audit** : pas d'écriture privilégiée sur preuve faible ; qui a approuvé, quand, est au ledger |
| `ad_unreachable` **(P1)** | Injection de panne sur l'étape 3 | Retry, puis run en état d'échec/incident **avec sa trace intacte**, reprenable | **Observability** : l'échec est un état de premier ordre, pas un ticket perdu dans une file |
| `quality_guard` **(P2)** | — | Le message rédigé à l'étape 5 omet l'avertissement de sécurité obligatoire → nœud d'évaluation le signale et bloque | **Quality gates** : l'évaluation est native (`response_eval_v1` / `claim_audit_v1`) |

**Replay (P0, zéro développement)** : la primitive `Rerun` de la plateforme
suffit. Prévoir un **historique de runs pré-existant** dans le workspace nawa
(lancer les 3 scénarios P0 quelques fois avant la démo) pour pouvoir rejouer un
run « d'hier » et comparer deux exécutions côte à côte à l'écran.

Cadrage verbal à tenir en démo : l'injection de panne et les presets sont
annoncés franchement (« je casse l'étape 3 volontairement pour vous montrer ce
qui se passe »). C'est un banc de simulation assumé, pas un tour de passe-passe.

### 6.3 Inventaire plateforme au SHA de prod `07f54a68` — ce qui existe, ce qui manque

Vérifié dans le code **au SHA déployé** (pas sur `demo/agentic`) :

**Disponible côté moteur** (`backend/app/services/run_engine/dag.py`) — kinds de
nœuds : `source`, `sink`, `task` (skill), `decision`, `fork`, `join`, `loop`,
`retry`, `hitl`, `subflow`. Tout ce dont le §6.1 a besoin existe.

- **HITL** : le nœud `hitl` met le run en `hitl_pending`, persiste l'état du
  walker dans `Run.checkpoints`, crée une `Decision` ; reprise via
  `POST /api/v1/runs/{id}/hitl`. Le TTL du gate se configure **dans le config
  du nœud** (`expires_in_days` ou `gate_ttl_days`, `expiry_action` ∈
  `reject` | `approve` | `escalate`) ; défauts plateforme : **3 jours / reject**
  (`backend/app/core/config.py`).
- **Replay** : trois endpoints natifs — `POST /runs/{id}/replay`,
  `GET /runs/{id}/replays`, `POST /runs/{id}/rerun`. Zéro développement.
- **Triggers** dans la palette : `source.schedule` (cron), `source.webhook`
  (HMAC), `source.sftp_arrival` (arrivée de fichier), `source.collection`.
- **Automation/RPA** : skill `rpa_dispatch_v1` (contrat REST générique vers un
  orchestrateur) — se pose comme un nœud `task`, rien à développer.

**Manquant / à contourner :**

| Écart | Contournement |
| --- | --- |
| `hitl`, `retry`, `subflow` **ne sont pas dans `DEFAULT_PALETTE`** (`frontend-ng/.../flow/flow.types.ts`) → non glissables sur le canvas | **Créer le flow par API.** Bonne nouvelle : le builder **sait afficher** un nœud `hitl` (`flow-node.component.ts` → badge « HITL ») et expose déjà l'UI de résolution du gate en attente (`flow-builder.component.ts` → `pendingHitl()` / `resolveHitl`) — donc un gate écrit par API s'affiche proprement **et s'approuve depuis le Flow Builder**, ce qui est excellent en démo |
| Routage vers le walker DAG conditionnel (`should_use_dag`) | Le flow doit avoir `schema_version >= 2` **et au moins un nœud de contrôle** — on en a deux (`decision`, `hitl`), donc le routage est automatique. **Sans nœud de contrôle, le run retombe sur le walker séquentiel qui ne gère pas le HITL** : vérifier ce point au premier run |
| **`AGENTIUM_CELERY_BEAT=0` dans l'invocation compose du §8** → aucune tâche périodique | Conséquences à assumer : (a) le **sweep d'expiration des gates** ne tourne pas → l'expiration ne se déclenchera pas d'elle-même ; (b) les **triggers cron ne partent pas**. Donc : ne **pas** bâtir la démo sur une expiration de gate qui s'exécute à l'écran (la montrer comme **politique configurée** dans le config du nœud), et pour la partie orchestration préférer un **trigger webhook HMAC** (piloté en HTTP, donc opérant) ou un lancement manuel plutôt qu'un cron. Ne pas rallumer le beat : c'est une décision de la réouverture de prod, hors périmètre |

### 6.4 Budget de latence, déterminisme, repli

- **Budget run** : viser < ~45 s pour `nominal` (relevé depuis les ~30 s
  initiaux à cause des appels LLM ; `azure_llm_v1` a un timeout de 60 s par
  appel). Prompts courts, sortie contrainte, et fusion des étapes 5-6 en un
  appel si nécessaire.
- **Déterminisme** : la classification de l'étape 1 doit rendre un **enum**
  (pas du texte libre) et l'étape 5 un gabarit contraint. Objectif : aucune
  dérive possible à l'écran.
- **Flow de repli obligatoire** : conserver une **seconde version du flow,
  100 % simulée sans appel LLM**, dans le même System. Si le provider hoquette
  pendant la démo, on bascule de flow — on ne débugge pas devant le client.
- **Prérequis à vérifier AVANT de développer** (§11) : un workspace **neuf**
  hérite-t-il du routage provider LLM, ou faut-il le configurer explicitement
  dans Models & Providers ? La prod fait déjà de l'inférence (le contrôle de
  non-régression §9.5 exige une réponse RAG sourcée dans le chat Andritz), donc
  la capacité existe ; c'est le rattachement du workspace `nawa` qui est
  l'inconnue (contrôle de non-régression §9.7). **Tester ce point en premier** :
  il conditionne tout le §6.1.

## 7. Livrable C — App front « Nawa ITSD » + migration additive

### 7.1 Frontend (`frontend-ng/src/app/features/nawa/`)

- **Page catalogue** (`/nawa/itsd`) : les ~40 use cases du xlsx en cartes ou
  table — colonnes utiles : nom, description du processus manuel vs automatisé,
  nb d'agents, volume mensuel attendu, temps legacy vs automatisé. Recherche/
  filtre simple. Badge de statut : **« Live »** pour Password Reset,
  **« Planned »** pour les autres (placeholders non cliquables ou fiche
  minimale). Troisième badge **« Same pattern »** sur les 6 entrées
  Email group (création/ajout/suppression) et Shared mailbox
  (création/ajout/suppression) : leur plan prévoit **38 agents chacune** alors
  que ce sont six variantes d'un même pattern « modification d'objet annuaire
  avec approbation » — le badge rend l'argument de factorisation visible à
  l'écran au lieu de le laisser au discours (on ne critique pas un existant : on
  montre que la même couverture se construit avec beaucoup moins d'agents).
- **Page détail Password Reset** (`/nawa/itsd/password-reset`) :
  - visualisation des 6 étapes du flow ;
  - **sélecteur de scénario** (§6.2) : `nominal`, `ambiguous`, `weak_identity`
    (+ `ad_unreachable` si P1 livré) — passé en entrée du run ;
  - bouton « Lancer la simulation » → déclenche un run du System (livrable B)
    via l'API runs ;
  - progression en direct des étapes (polling des traces/du run) jusqu'à l'état
    final, qui **n'est pas toujours « ticket clôturé »** : prévoir aussi les
    états « routé vers un autre use case » (`ambiguous`), « en attente
    d'approbation » (`weak_identity`, avec l'indication d'où approuver) et
    « échec/incident » (`ad_unreachable`) ;
  - **liens vers les écrans natifs de la plateforme**, essentiels à la
    démonstration : « Voir la trace du run » (détail pas à pas, coût, timing),
    « Voir dans le Flow Builder », et « Voir au ledger d'audit » si une route
    d'audit existe déjà côté gouvernance.
- **Données** : extraire le xlsx en JSON statique
  (`frontend-ng/src/assets/nawa/itsd-use-cases.json`) via un petit script
  (`python3` + `zipfile`/`openpyxl`) commité sous `docs/render/` ou
  `frontend-ng/scripts/`. Pas d'appel backend pour le catalogue.
  **Le script applique la purge du §5.4 et échoue si un terme de la liste noire
  survit dans le JSON.**
- **Enregistrement** : entrées `nawa-itsd` dans `navigation.catalog.ts`
  (route `/nawa/itsd`, lens `operate`) + routes lazy dans `app.routes.ts`.
  Vérifier `workspace-experience.ts` pour que le shell business affiche la
  surface.

### 7.2 Migration alembic additive `065_nawa_itsd.py`

Calquée sur 060, elle doit être **idempotente et strictement additive** :

- étendre la CHECK `ck_workspace_member_app_entitlements_app_key` avec
  `nawa-itsd` ;
- granter l'entitlement aux membres du workspace `nawa` (s'il existe déjà au
  moment de la migration — sinon la création §5 doit précéder) ;
- écrire/mettre à jour `navigation_profile` des settings du workspace `nawa` ;
- insérer le System Password Reset si porté par la migration (§6).

**Interdit** : toute modification de données des autres workspaces, tout
`downgrade` destructif, tout backfill massif. La tête alembic actuelle de la
prod correspond à la base `07f54a68` (séries 05x-064) — vérifier avec
`docker exec agentium-backend alembic current` avant d'écrire la révision.

### 7.3 Backend (minimal)

Aucun nouveau endpoint si possible (le front consomme runs/systems/traces
existants). Seule exception attendue : `surface_catalog.py` si les ids de
surface y sont validés. Toute autre modification backend doit être justifiée
et minimale.

## 8. Déploiement (28/07 en fin d'après-midi — avancé, VM libre plus tôt)

Fenêtre initialement prévue à 21h-23h, avancée le 28/07 : la VM est libre et
personne n'est en démonstration, ce qui laisse la soirée entière comme buffer
de correctifs au lieu de la seule matinée du 29.

**Prérequis découvert le 28/07 :** le `.git` du dépôt live conserve 19 fichiers
appartenant à root (dont `index` en `-rw------- root root`), hérités de la
transaction Release A du 27/07 jouée en root. En l'état, l'étape 1 ci-dessous
échoue sur « Permission denied ». Corriger d'abord, sans toucher au reste :

```bash
sudo find /home/ubuntu/omnirag/.git -user root -exec chown ubuntu:ubuntu {} +
sudo -u ubuntu git -C /home/ubuntu/omnirag status -sb   # doit répondre
```

Le déploiement recrée uniquement `agentium-frontend`, `agentium-backend`,
`agentium-worker-cpu` (si le backend change) avec de nouvelles images, en
réutilisant **exactement** l'invocation compose de la réouverture du 28/07 :

```bash
# Sur la VM, en root. D = répertoire du déploiement Release A (NE PAS le modifier,
# on ne fait que réutiliser son env figé et son overlay "opened").
D=/srv/agentium-data/release-a-deployments/release-a-2026-07-27-omnirag-demo

# 1) Récupérer la branche dans le repo live EN TANT QU'ubuntu (jamais root)
sudo -u ubuntu git -C /home/ubuntu/omnirag fetch origin feat/nawa-itsd-demo
sudo -u ubuntu git -C /home/ubuntu/omnirag checkout <SHA_DEV_EXACT>

# 2) Builder les images (backend + frontend) — tag dédié
#    (contextes exacts du compose: context=racine repo, dockerfiles sous docker/)
cd /home/ubuntu/omnirag
docker build -t agentium-backend:nawa-demo  -f docker/Dockerfile.agentium-backend  .
docker build -t agentium-frontend:nawa-demo -f docker/Dockerfile.agentium-frontend .

# 3) Écrire un override d'images /root/nawa-images.yml pinnant ces tags
#    (même format que $D/compose.agentium.candidate-images.yml)

# 4) Migration additive, via une exécution one-off sur la NOUVELLE image backend
#    (dump PG de sécurité AVANT: docker exec agentium-pg pg_dump -U agentium agentium | gzip > /root/nawa-predeploy.sql.gz)
#    puis: alembic upgrade head

# 5) Recréer les conteneurs applicatifs avec la clé Qdrant admin (comme le 28/07)
ADMIN=$(docker inspect qdrant --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^QDRANT__SERVICE__API_KEY=//p')
COMPOSE_PROJECT_NAME=agentium \
AGENTIUM_QDRANT_EFFECTIVE_API_KEY="$ADMIN" AGENTIUM_CELERY_BEAT=0 AGENTIUM_STARTUP_RECONCILIATION=disabled \
docker compose -p agentium \
  --env-file "$D/runtime-env/compose.effective.env" \
  -f compose.agentium.yml -f "$D/compose.agentium.opened.yml" -f /root/nawa-images.yml \
  up -d --no-build --no-deps agentium-backend agentium-worker-cpu agentium-frontend
```

Points durs :

- **Dump PostgreSQL checksummé avant la migration**, conservé sous `/root/`.
- **Ne pas toucher** `agentium-sftp`, `agentium-kc`, `agentium-livekit*`,
  `agentium-p4-maintenance` ni les stateful.
- Rollback : `alembic` ne se downgrade pas ; en cas d'échec → restaurer le
  dump PG, re-checkout `07f54a68` (en ubuntu), recréer les conteneurs avec
  l'override d'images du 28/07 (`$D/compose.agentium.candidate-images.yml`),
  revérifier l'UI.

## 9. Vérification post-déploiement (obligatoire, via l'UI publique)

1. Login opérateur → sélection workspace **nawa** → charte Nawa visible. Le
   chrome de la plateforme porte le wordmark **NAWA** et l'onglet du
   navigateur dit « NAWA » ; un autre workspace (ex. `andritz`) doit rester à
   la marque Agentium — c'est le test d'isolation du réglage `platform_brand`.
2. `/nawa/itsd` : catalogue ~40 use cases, recherche OK, badges corrects
   (« Live » / « Planned » / « Same pattern »), en-tête **« WE · IT Service
   Desk »** sous le wordmark NAWA (§5.3).
   **Aucune marque concurrente à l'écran** — contrôle `rg -i` de la liste noire
   sur le JSON et sur le bundle construit (§5.4).
3. `/nawa/itsd/password-reset` — les trois scénarios P0 passent :
   - `nominal` → 6 étapes → « ticket clôturé », trace consultable ;
   - `ambiguous` → sortie « routé vers use case #2 », **aucun reset effectué** ;
   - `weak_identity` → gate en attente → approbation dans l'écran natif → le
     run reprend et se clôture, l'approbateur est identifiable dans la trace.
4. Trace d'un run lisible pas à pas (entrées/sorties, timing, coût) et **Rerun**
   fonctionnel sur un run antérieur ; historique de runs pré-alimenté.
5. `/orchestration` (workspace nawa) : le flow à 6 nœuds s'affiche, branches de
   scénario lisibles.
6. **Flow de repli** (version 100 % simulée) testé au moins une fois : la
   bascule doit prendre moins d'une minute en démo.
7. **Non-régression Andritz** (critique — c'est la prod du client existant) :
   les 4 apps répondent (`/chat` avec une vraie question RAG sourcée,
   `/client360`, `/knowledge/capture`, `/knowledge/interventions`), et **aucune
   nouvelle entrée d'audit** dans leurs écrans de gouvernance — leur flow de chat
   ne lie aucun nœud `audit_log_v1`, et l'invocation visible dans leur ledger de
   chat est synthétique (fabriquée pour la comptabilité coût/latence, sans appel
   au skill).
8. `curl -s https://agentium.papai.ai/api/v1/health` → 200.
9. **Ledger de conformité** — `audit_log_v1` persiste réellement depuis le 28/07
   (avant, il répondait « recorded » sans rien écrire) :
   `GET /api/v1/audit?event_type=itsd.password_reset.withheld` renvoie une entrée
   sur la voie incident et sur la voie blocage qualité, avec
   `disposition: "withheld"` et les trois booléens `account_modified`,
   `temporary_password_issued`, `requester_notified` à `false` ; sur la voie
   nominale, l'`audit_event_id` de l'outcome référence une ligne réelle.

### 9.1 Journal du déploiement du 28/07 (17h00-17h10 UTC+2)

Déployé depuis le SHA `650f7899`. Dump de sécurité :
`/root/nawa-predeploy.sql.gz` (425 Mo, sha256 `1b46d000…c174c`), archive testée.
Override d'images : `/root/nawa-images.yml` ; invocation rejouable via
`/root/nawa-deploy.sh {images|migrate|up|ps}`.

Trois écarts par rapport au §8 tel qu'écrit, tous constatés sur place :

1. **Trois images, pas deux.** `agentium-worker-cpu` a son propre Dockerfile et
   c'est lui qui exécute les runs : sans le rebuild du worker, le correctif de
   persistance d'`audit_log_v1` ne serait pas dans le chemin d'exécution.
2. **Deux arguments de build obligatoires** : `PIP_INDEX_URL`
   (`https://pypi.org/simple`, le défaut du compose) et
   `AGENTIUM_IMAGE_REVISION` (le SHA), exigé par le contrat de provenance
   d'image. Sans eux, le build échoue à l'étape 4 ou produit une image
   étiquetée `unknown`.
3. **Build en root.** Le contexte contient `backend/.env`, en `600 root`, donc
   illisible par `ubuntu`. Builder en root reproduit à l'identique le contexte
   de l'image en place — seul `git` reste en `ubuntu`.

Vérifié après coup : migration `065_nawa_itsd` appliquée (prod était en `064`),
System `571d067a` adopté sans doublon (28 nœuds), `navigation_profile` ajouté,
`platform_brand` conservé. Révision servie par le frontend et le backend =
`650f7899`. Les six scénarios rejoués, les deux portes humaines résolues, et le
ledger porte quatre entrées neuves (deux `completed`, deux `withheld`) — rien
pour la voie routée ni pour une porte en attente, ce qui est le comportement
voulu. Non-régression Andritz : question RAG neuve répondue avec 6 sources, et
les trois autres apps rendent, tout en restant à la marque Agentium.

Reste à faire à la répétition : §9.4 (trace pas à pas et Rerun), §9.5
(`/orchestration`), §9.6 (bascule vers le flow de repli).

## 10. Hors périmètre / interdits

- Release B, lots 7-9, `demo/agentic` : rien ne bouge.
- Pas de push sur `demo/agentic` ni `codex/release-a-from-hotfix` ; la branche
  de dev est poussée sur `origin feat/nawa-itsd-demo` uniquement.
- Pas d'intégration AD/ITSM réelle : **les gestes système sont simulés**. En
  revanche l'**inférence LLM est réelle** (§6.1) — c'est ce qui distingue la
  démo d'un RPA scripté ; ne pas la remplacer par des réponses en dur.
- Pas de refonte du theming global, pas de refactor des apps existantes.
- **Aucun nom de concurrent** dans la surface, les libellés, le JSON extrait, le
  flow, les noms de System/agent ou les commentaires visibles : l'assistant
  s'appelle **NAWA WE** (§5.4).
- Pas de modification des specs Playwright figées ni des scripts Release A.

## 11. Risques connus et pièges

| Piège | Parade |
| --- | --- |
| CHECK constraint sur `app_key` rejette `nawa-itsd` | Migration 065 calquée sur 060 (extension de la liste) |
| Settings workspace validés côté backend (`surface_catalog.py`) | Vérifier et étendre si nécessaire, sinon le PATCH settings échouera |
| `git` en root sur le repo live | Toujours `sudo -u ubuntu git -C /home/ubuntu/omnirag …` (des fichiers root-owned ont déjà cassé le backend le 27/07) |
| Recréation backend sans la clé Qdrant admin | Toujours l'invocation compose du §8 (sinon le backend repart avec la clé lecture seule → chat cassé) |
| Écrasement du workspace nawa par la future Release B (`seed reconciliation`) | Hors périmètre de ce job, mais noter le slug `nawa` dans la PR pour le check pré-Release B |
| Nœud rouge sur le System bootstrappé « Agentium Workspace Chat » si quelqu'un l'exécute à la main, dans n'importe quel workspace | Conséquence attendue et assumée du correctif `audit_log_v1` : son nœud d'audit ne fournit pas d'`event_type`, donc le skill refuse désormais d'écrire plutôt que de répondre « recorded » à vide. Cosmétique, sur un System que rien n'exécute automatiquement — **ne pas le prendre pour une régression du déploiement** |
| Démo = matin même | Déployer **le 28/07 dès que la VM est libre** (fenêtre avancée en fin d'après-midi), garder la soirée et la matinée du 29 comme buffer de correctifs |
| **Workspace neuf sans routage provider LLM** → les runs échouent au premier nœud d'inférence | **À tester en tout premier** (§6.4) avant d'écrire une ligne de flow ; si le rattachement n'est pas automatique, configurer le provider pour `nawa` dans Models & Providers |
| **Latence LLM** : budget run dépassé, blanc à l'écran | Prompts courts, sortie contrainte, fusion des étapes 5-6, budget affiché relevé à ~45 s |
| **Non-déterminisme LLM** en direct devant le client | Sortie de l'étape 1 contrainte à un enum, gabarit contraint à l'étape 5, scénarios répétés plusieurs fois la veille |
| **Provider indisponible pendant la démo** | **Flow de repli 100 % simulé** dans le même System (§6.4), bascule répétée à l'avance (§9.6) |
| Gate humain jamais franchi → run bloqué en démo | Approbation répétée avant la démo ; connaître par cœur l'écran d'approbation (le Flow Builder lui-même sait résoudre un gate en attente, §6.3). **Ne pas compter sur l'expiration automatique** : le beat Celery est coupé (§6.3) |
| Flow écrit sans nœud de contrôle → run routé vers le walker séquentiel → **HITL ignoré** | Le flow contient `decision` + `hitl` et `schema_version >= 2` ; vérifier au premier run que le walker DAG est bien emprunté (§6.3) |
| Trigger cron configuré mais jamais déclenché (beat coupé) | Pour la partie orchestration, utiliser un **webhook HMAC** ou un lancement manuel ; présenter le cron comme capacité configurée, pas comme démo live (§6.3) |
| **Nom de concurrent affiché à l'écran en démo** (53 occurrences dans le xlsx source, dont 4 intitulés de use cases) | Purge par le script d'extraction avec échec bloquant, assistant renommé **NAWA WE**, contrôle `rg -i` sur le JSON **et** le bundle avant la démo (§5.4) |
| Le contrôle de purge lui-même crie au loup sur le bundle minifié : `toggleEnabled` et `navigationProfileEnabled` contiennent « leEnab » = « leena » en insensible à la casse | Toujours avec frontières de mot : `rg -ci "\b(leena\|daizy\|qwik)\b"`. Sans elles, deux faux positifs à chaque build, et un vrai finirait par passer pour l'un d'eux |

## 12. Jalons

| Quand | Quoi |
| --- | --- |
| 28/07 **en premier** | Test du routage provider LLM sur un workspace neuf (§6.4) — bloquant pour le §6.1 |
| 28/07 journée | Branche + workspace nawa + flow (2 nœuds LLM, gate, branches de scénario) + flow de repli + dev app front + migration |
| 28/07 fin de journée | Pré-alimentation de l'historique de runs (3 scénarios P0 joués plusieurs fois) pour la démo de replay |
| 28/07 fin d'après-midi | Déploiement §8 (précédé du `chown` du `.git`) + vérification §9 |
| 29/07 matin | Buffer correctifs + répétition de la démo |
| 29/07 12h | Démo |

## 13. Itération du 28/07 au soir — l'app cesse de ressembler à un banc

Le socle §5-§9 était livré et déployé, et le reproche était juste : en frontal
métier, l'écran affichait un **sélecteur de scénarios**, des volumes mensuels et
un gain cible. C'est un cahier des charges, pas une application. Quatre
changements, tous côté surface, aucun sur la logique du flow.

1. **File de tickets** à la place du sélecteur. Une ligne = une demande en
   attente (heure d'arrivée, canal, demandeur, objet), lue des seuls réglages du
   System. Rien n'est fabriqué : un champ absent ne s'affiche pas, parce qu'une
   référence de ticket inventée pour la file contredirait celle que le run émet
   à la clôture.
2. **Traitement rendu comme une conversation** demandeur / WE, la liste
   technique des 6 étapes passant derrière une bascule.
3. **Approbation du gate humain dans l'app.** Même endpoint que le cockpit, donc
   la décision atterrit au ledger avec son auteur dans les deux cas ; l'intérêt
   est qu'un superviseur de desk n'a jamais à entrer dans les écrans de la
   plateforme pour débloquer un ticket.
4. **Catalogue recadré** : « Available » / « In the rollout plan » au lieu de
   LIVE/PLANNED, et les colonnes de ROI derrière un onglet « Business case ».

### 13.1 Voie « demande tapée » (flow en version 6)

Le flow porte une branche `free_text` : le cas ne vient plus d'un preset mais du
`input_ref` du run. Les gabarits de prompt vivent dans les réglages du System et
c'est l'app qui substitue les mots de l'appelant, **contre les mêmes trois
constantes** que les presets — le walker ne compose aucune chaîne. Une demande
tapée est donc jugée par le bloc d'instruction identique. Sondé en prod : une
demande en français est classée `password_reset` et se clôture ; « my laptop will
not start » est classée `other` et **aucun reset n'est effectué** ; des preuves
minces ouvrent la porte humaine. Les six presets rejoués derrière : aucun écart.

### 13.2 Assistant Q&R sur la bibliothèque du desk

Deuxième surface disponible du catalogue, et ce n'est pas une surface inventée
pour la démo : c'est **le use case SR#18 de leur propre liste** (« User Q&A —
Knowledgebase Automation »). Elle répond aux demandes qui attendent une réponse
plutôt qu'un geste, quand la page voisine exécute.

- **Bibliothèque** : six politiques de service desk rédigées pour l'occasion
  (`frontend-ng/src/assets/nawa/knowledge/`, ~500 mots chacune, mots de passe,
  MFA, accès distant, arrivées/départs, priorités et cibles, logiciels). Elles
  vivent dans les assets du front et non dans `docs/` : le front les sert pour
  situer la citation (§13.4), et deux copies dériveraient — on citerait un texte
  qui n'est pas celui qui a été indexé.
  Chacune porte une ligne « Sample content prepared for the WE preview
  workspace » : le client doit voir tout de suite que ce ne sont pas ses propres
  documents. Collection `itsd-knowledge`, 25 chunks.
- **Chaîne** : aucun endpoint nouveau. `POST /documents/upload` (asynchrone en
  prod, le worker embarque), puis `PATCH /knowledge/scopes` — qui appelle
  `ensure_workspace_chat_system_default` et **crée le System de chat** branché au
  périmètre. Renommé « WE Assistant » ; le nom par défaut portait notre marque.
- **Écran** : `/nawa/itsd/assistant`. Chaque réponse est affichée avec les
  passages sur lesquels elle s'appuie, numérotés comme les repères `[n]` que le
  modèle a écrits. Une réponse sans source est marquée **non étayée** — c'est le
  comportement attendu hors périmètre, pas une erreur. 0,6 à 5 s par question.
- **Contrat de langue** : le front envoie `response_language: 'en'`. Sans ce
  champ, le backend devine d'après la question et **retombe en français** quand
  il ne tranche pas — une réponse française à une question anglaise devant ce
  public serait un défaut visible.

**Deux pièges rencontrés, tous deux réels en clientèle.** (a) La question « mon
manager peut-il récupérer mon mot de passe temporaire ? » recevait d'abord un
**« oui »** : la phrase qui l'interdit était tombée de l'autre côté d'une
frontière de chunk. Corrigé dans la source, en rendant la règle auto-portante et
en la répétant dans la section « ce que le desk ne fait jamais ». (b) L'extrait
cité est un préfixe de 200 caractères du chunk, donc un document qui s'ouvre sur
son en-tête administratif **cite son en-tête comme preuve** ; le bloc
propriétaire/version a été déplacé en fin de fichier. Les deux corrections sont
dans le corpus, pas dans l'affichage — c'est exactement la boucle de reprise
qu'on vendra au client.

### 13.3 Mode démo (`demo_safe`) sur le workspace nawa

Question soulevée pendant l'itération : **la génération part vers l'API publique
d'OpenAI** (`DEFAULT_PROVIDER=openai`, `DEFAULT_MODEL=gpt-5` sur la VM ; le slug
de skill `azure_llm_v1` est un nom historique et n'implique aucun Azure). Pour un
client dont l'exigence est un déploiement souverain, l'hébergement de l'aperçu
n'est pas la réponse à cette exigence et n'a pas à s'afficher.

Le réglage qu'Andritz porte déjà a donc été appliqué à `nawa`, à l'identique :
`demo_safe: true` + `presentation: {demo_safe, hide_provider_details}`. Il
supprime dans le cockpit la puce de runtime du chat (« managed runtime »), les
onglets du portail modèles et les champs provider des presets. Écrit aussi dans
la migration 065 — avec la règle « on ne remplit qu'un trou » — pour qu'une base
reconstruite le porte. Vérifié à l'écran : aucun nom de modèle ni de fournisseur
sur les surfaces du workspace. Les surfaces WE n'en affichaient aucun de toute
façon : elles montrent des latences et des citations.

**Ce qui reste vrai et doit être dit si la question vient** : l'aperçu SaaS
s'exécute sur l'API du fournisseur ; la cible POC et production est la pile
souveraine on-prem chiffrée dans la réponse RFI. Le mode démo masque un détail
d'hébergement, il ne le change pas.

### 13.4 La citation doit contenir ce que la réponse affirme

Trouvé en prod sur la question qui porte la démonstration. Interrogé sur le
manager qui viendrait chercher un mot de passe temporaire, l'assistant répond
non — correctement — en citant un passage qui dit « passwords must be at least 12
characters long ». Les deux viennent du même document : la règle est quatre
phrases après l'ouverture, et l'extrait était l'ouverture.

La cause est côté plateforme : `sources[].snippet` renvoie le **parent context**
du chunk (`type: parent_context`, `id: chunk-0`), tronqué à **200 caractères**
côté serveur. La phrase justificative ne quitte jamais le backend. C'est le
comportement de citation du produit en général, celui que le chat Andritz montre
déjà — pas un défaut propre à nawa.

Correction sans toucher au backend, à minuit et à douze heures de la démo : le
front sert les six politiques depuis ses propres assets et **localise dans le
document la fenêtre qui porte la réponse** — la phrase qui partage le plus de
vocabulaire avec elle, plus ses voisines, en grandissant vers l'aval d'abord
parce que la phrase qui nuance une règle la suit généralement. Ce que la
recherche établit — quel document répond — est conservé et utilisé ; ce qu'elle
tronque est retrouvé dans le fichier qui **est** celui qui a été indexé.

Propriétés tenues, et testées : verbatim et contigu, une ellipse à l'extrémité
coupée, et **deux mots communs minimum** avant de construire une fenêtre. Ce
plancher n'est pas décoratif : « the canteen closes at four on Fridays » croise
« three of the four following groups » et fabriquait un extrait convaincant sur
une coïncidence. Sous le plancher, retour à l'extrait de la recherche, qui reste
aussi le repli quand l'asset ne charge pas.

Nuance à assumer si la question vient : l'extrait est choisi par l'application
dans le document que la recherche a retenu, il n'est pas renvoyé par la
recherche. Le passage est vérifiable mot pour mot dans la politique publiée.

### 13.5 L'assistant devient la porte d'entrée des demandes

Jusqu'ici l'assistant ne faisait qu'une chose : citer la bibliothèque. Or c'est
l'écran qu'un demandeur ouvre en premier, et une demande de service à laquelle on
répond par un extrait de politique est une demande à laquelle on n'a pas répondu.
Trois issues possibles désormais, décidées avant toute recherche :

1. **Demande pour le service qui tourne ici** — elle est *traitée*. Même flow,
   mêmes prompts, même porte humaine que la page desk : un vrai run au ledger,
   avec les mots du demandeur en entrée.
2. **Demande pour un autre service du catalogue** — réponse avec *leur* procédure
   documentée, citée depuis leur classeur (`manual_process`), et l'état de son
   automatisation dans le plan de déploiement. Leur vocabulaire : ITSD Portal,
   autorisation du Line Manager, Active Directory.
3. **Question sur les règles** — réponse depuis la bibliothèque publiée, avec le
   passage qui la fonde (inchangé).

**Aiguillage** (`nawa-intake.ts`, pur, testé sur le catalogue livré). Un énoncé
est une demande s'il exprime un besoin ou réclame une action ; les
interrogatives sur une règle sont délibérément absentes des marqueurs, sinon
« what identity evidence do you need before you reset a password » deviendrait
une réinitialisation. Le service est choisi par recouplement lexical pondéré par
la rareté du mot dans les 39 noms du catalogue — « password » nomme un service et
décide seul, « request » les nomme presque tous et ne décide rien — les mots étant
comparés sur leurs cinq premières lettres pour que « create » atteigne
« Creation ». Un score doit franchir un plancher *et* battre le second d'une
marge : sinon retour à la bibliothèque, ce qui est l'échec gracieux. Table de
calibration figée en test : 15 demandes / 8 questions. Un cas reste non aiguillé
exprès (« print code for the colour printer » : trois services du catalogue
conviennent, aucun ne se distingue).

**Vérification d'identité avant écriture privilégiée.** La procédure du client
met la vérification en étape 2, donc l'assistant demande les deux preuves que la
plateforme peut contrôler seule : le matricule, contre le dossier RH, et le code
courant de l'authentificateur enregistré — ce sur quoi repose leur propre
politique MFA. Ce qu'il ne fait pas : prendre une affirmation pour une preuve. Un
manager nommé n'est pas une confirmation de ce manager, et le relevé de preuves
écrit lequel des deux il est, parce que le nombre de preuves déposées est ce que
lit le garde-fou en aval. La réplique du demandeur n'est jamais réaffichée : elle
porte un code à usage unique.

**Un écart réel trouvé à cette occasion.** La politique publiée dit « identity is
established when at least **two independent proofs** are on file », alors que le
flow ne refusait qu'à *zéro* preuve. Sondé en prod : sur une seule preuve, le
modèle d'évaluation répond « IDENTITY_VERIFIED — the staff number matched the HR
record, fulfilling one of the requirements » et la réinitialisation était
exécutée sans supervision. Corrigé au seuil de la politique (flow en version 7),
avec deux réserves inscrites dans le générateur :

- l'approbation d'un superviseur *lève* le garde-fou (`human_approved != True`) :
  l'écriture n'est alors plus non supervisée, la décision est au ledger sous son
  nom. Sans cela, approuver une demande mince à la porte aurait été annulé en
  silence juste après.
- « moins de deux » est écrit `== 0 or == 1` et non `< 2` : l'évaluateur de
  prédicats de la plateforme (`run_engine/condition.py`) évalue *tous* les
  opérandes d'un `and` avant de les combiner, donc un garde `evidence_on_file !=
  None and evidence_on_file < 2` exécute quand même la comparaison ordonnée et
  fait échouer le run sur toutes les voies où le compteur est absent. Dette
  plateforme à traiter hors démo : le `and` documenté comme Python devrait
  court-circuiter.

Aucun des six scénarios de la page desk ne change (ceux à une preuve sont déjà
arrêtés en amont par le verdict). Sondage de prod après bascule : 2 preuves →
clôture avec la notice rédigée ; 1 preuve avec verdict « verified » → refus
structurel, compte inchangé ; 0 ou 1 preuve avec verdict insuffisant → porte
superviseur, répondue depuis le chat. Les six presets rejoués sans écart.

**À dire pendant la démo.** Le modèle s'est trompé sous nos yeux en prod : il a
validé une identité sur une seule preuve. C'est la plateforme qui a refusé, sur
la règle publiée du client, avant toute modification du compte — et le refus est
au ledger. C'est exactement l'argument que ni un RPA ni un chatbot ne peut tenir.

### 13.6 La parole s'écrit à l'écran pendant qu'on parle

L'assistant avait déjà une voix : micro, transcription, réponse lue à voix
haute. Mais la dictée ne montrait rien pendant la phrase, et le texte final
n'apparaissait jamais dans l'invite — il partait droit en question. On parlait
dans le vide, sans pouvoir relire ni corriger.

La plateforme n'a pas de reconnaissance en flux exposée pour un assistant de
questions-réponses : la pile temps réel (LiveKit, sidecar agent, transcription
serveur avec interruption) est déployée mais son gateway pilote la machine à
états de la capture de connaissance. Le transcript direct est donc obtenu
autrement : le recorder rend une tranche toutes les 1,5 s, et chaque tranche
déclenche une transcription de tout ce qui est capturé jusque-là. Mesure sur le
runtime de prod : 0,8 s pour six secondes de parole, donc les mots suivent la
phrase.

Deux conséquences assumées, à connaître avant de le montrer :

- chaque passe relit l'enregistrement entier, donc le modèle révise ses propres
  suppositions et les mots déjà affichés **peuvent changer**, ponctuation
  comprise. C'est le comportement d'une reconnaissance en flux avec ses
  résultats provisoires, pas un défaut d'affichage.
- une seule requête est en vol à la fois : une réponse lente coûte de la
  fraîcheur, jamais une file d'attente. Une passe perdue est invisible, la
  tranche suivante redemande. Si la passe de clôture échoue, la phrase déjà à
  l'écran est retenue plutôt que perdue : elle vient du même enregistrement.

Deux gestes, deux issues. Le bouton « Stop and send » finalise et envoie, ce qui
garde la boucle vocale mains libres. **Toucher le champ de saisie** en cours de
phrase reprend la main : l'écoute s'arrête, une passe de clôture récupère la fin
que l'affichage n'avait pas encore atteinte, et les mots attendent dans l'invite
pour être corrigés. Rien n'est envoyé.

Vérifié sur le domaine public en injectant un fichier WAV comme micro
(`frontend-ng/e2e/probe-nawa-dictation.mjs`, qui s'appuie sur
`--use-file-for-fake-audio-capture` de Chrome, donc de la vraie parole et non la
tonalité de test). Relevé : invite vide à 2,2 s, « I forgot my password. » à
4,2 s, « … and I cannot sign in this morning. » à 6,2 s, puis la passe de
clôture ajoute « Can you help me reset it, please? » — la fin de phrase que
l'affichage n'avait pas atteinte. Cinq appels de transcription pour 6,5 s de
parole. Clic dans le champ : phrase complète conservée, bouton revenu à
« Speak », rien d'envoyé. Captures sous `shots/`.

**À dire pendant la démo.** Le texte qui s'écrit pendant qu'on parle passe par
notre propre runtime. Rien ne part vers la reconnaissance vocale du navigateur,
qui expédierait l'audio chez un tiers — ce qui compte quand la conversation
porte sur des comptes et des identités.

## 14. Incident du 29/07 au matin — la pile recréée à la main perd sa configuration

Symptôme initial : plus de connexion possible, l'écran affichant « Invalid
credentials ». Le backend ne démarrait pas du tout, sur un échec
d'authentification Postgres. Une fois la connexion rendue, un second symptôme
bien plus grave est apparu : le scénario nominal se terminait en 0,5 s au lieu
de 5,5 s, la classification revenait en 4 ms, la vérification d'identité, la
porte qualité et l'écriture au ledger étaient **sautées**, et le run
s'affichait tout de même « completed / approved » — exactement l'inverse de ce
que la démo raconte.

**Cause unique.** J'ai recréé le backend avec une invocation compose écrite à la
main (`cd /home/ubuntu/omnirag && docker compose -f docker/compose.agentium.yml
… up -d`). Or la pile en production ne se déploie pas comme ça : elle se déploie
par `/root/nawa-deploy.sh`, qui utilise un autre fichier compose (celui du
worktree `release-a`), une surcouche `compose.agentium.opened.yml`, un
environnement figé (`runtime-env/compose.effective.env`) et quatre variables
exportées, dont la clé admin Qdrant lue dans le conteneur qui tourne. Sans cet
environnement d'interpolation, toutes les valeurs `${…}` du compose sont tombées
à vide ou à leur défaut : le conteneur a démarré **sans clé OpenAI**, avec un
autre mot de passe Postgres, une autre clé Qdrant, d'autres identifiants MinIO,
RabbitMQ et LiveKit, et sans SMTP. La classification n'appelait donc aucun
modèle et rendait `password_reset: false, other_use_case: false`, ce qui
n'ouvrait aucune branche.

Deux enseignements, au-delà du correctif :

1. **Le mode dégradé est silencieux.** Un appel de modèle sans clé s'est
   enregistré comme une invocation `completed`, avec un coût nominal de 0,01 $
   et une latence de 4 ms. Rien dans l'UI ne disait « pas de fournisseur » ; le
   seul signal était le temps. Un run sans branche choisie sur
   `decision.identity_gate` devrait se terminer en échec, pas en `approved` —
   c'est une dette à ouvrir, distincte de la démo.
2. **`Rerun` n'était pas en cause.** L'endpoint recrée bien un run sur le même
   `input_ref` et le même `flow_snapshot` et le fait exécuter par le moteur ; le
   rejeu creux n'était que le symptôme de la clé manquante. Vérifié après
   remise en état : parent et rejeu font tous deux cinq invocations, choisissent
   `verified`, écrivent au ledger et clôturent le ticket.

**Remise en état.** `sudo /root/nawa-deploy.sh up`. Les six secrets contrôlés
portent à nouveau la même empreinte que ceux du worker resté intact, qui a servi
de témoin tout du long. Révisions servies : backend `48a853c5`, frontend
`b4d0af51`, worker `650f7899`. Scénario nominal repassé (5 invocations, porte
`verified`, ledger écrit, `ticket_closed`), `Rerun` repassé à l'identique, RAG
vérifié sur `nawa` **et** sur `andritz` (3 sources) pour écarter toute
régression chez un autre client.

**Règle pour la suite.** Aucune commande compose à la main sur cette pile. Toute
action passe par `/root/nawa-deploy.sh {images|migrate|up|ps}` ; s'il faut un
service seul, on modifie le script, on ne contourne pas.

## 15. Les services planifiés se jouent, au lieu de s'expliquer

Question du sponsor, la veille : « l'intent peut être simulé en démo pour les 32
use cases, sauf que l'action ne sera prise que pour le password reset qui est
intégré, c'est ça ? » — oui, et c'est exactement l'architecture livrée :
l'aiguillage est du vrai code sur les 39 services du classeur, une seule voie
exécute. Le défaut était ailleurs : la réponse pour les 38 autres décrivait la
situation (« pris en charge par le desk aujourd'hui, automatisation au plan de
déploiement ») et renvoyait au portail ITSD. Techniquement honnête, mais lu en
frontal ça sonne comme un refus, dans un espace de travail dont la promesse est
précisément que le desk cesse d'être un portail.

**Ce qui change.** L'assistant déroule le service comme il tournera. La
procédure affichée reste celle du client, mot pour mot ; ce que le code ajoute,
c'est sa lecture : l'étape qui demande de déposer la demande est marquée
`submitted here`, puisque la conversation vient de la satisfaire ; l'étape où
l'IT vérifie une approbation devient une **porte** qui arrête le déroulé, avec
les rôles que la procédure nomme (Line Manager, HR, IT Approver) ; le reste est
marqué `automated`. Après décision, le déroulé reprend et clôture. Même grammaire
que le run réel : mêmes bulles, même orbe d'activité, même porte.

**Trois garde-fous.** Aucun appel plateforme sur cette voie : un preview ne crée
ni run, ni entrée de ledger, ni ticket — la distinction avec Password Reset est
donc réelle, pas déclarative. La marque `Preview` reste sur le tour tant qu'il
est à l'écran, avec bordure pour survivre à une capture d'écran. Et rien n'est
inventé : les 15 services dont la procédure porte une approbation ont une porte,
les 24 autres n'en ont pas et la clôture ne prétend pas le contraire (« Done.
All seven steps carried out » et non « Approved »).

**Ce que la lecture du classeur a révélé au passage.** Trois services
(`closure-of-non-responsive-tickets`, `providing-vpn-avd-access-for-users`,
`collecting-user-hardware-information-assistant`) arrivent avec une colonne
procédure vide. L'assistant le dit plutôt que d'improviser des étapes, et c'est
un point à remonter au BA : une procédure non écrite est une automatisation non
spécifiable.

Livré en `a5a72aa9`, 418 tests verts, vérifié sur le domaine public : déroulé
mesuré à l'écran (une étape, puis deux, puis arrêt sur la porte), approbation qui
reprend jusqu'aux sept étapes, service sans porte joué de bout en bout, aucune
erreur console.

## 16. « I lost my password. » — un synonyme suffisait à perdre la voie réelle

Signalé au matin de la démo, capture à l'appui : la phrase reçoit une citation de
politique au lieu de déclencher le reset. Le déclenchement n'était pas cassé —
`I forgot my password.` demande l'identité, crée le run, atteint la porte, tout
mesuré en prod avant tout correctif. Le défaut était lexical : `forgot` est dans
la liste d'alias de Password Reset, `lost` n'y était pas, donc la phrase passait
sous le plancher de score et tombait dans la bibliothèque. Le repli était propre,
et c'est ce qui l'a rendu invisible : la réponse citait la bonne politique.

**La leçon de méthode.** Toutes les formulations testées jusque-là disaient
`forgot` : la table de calibration avait été écrite à partir du code, pas à
partir de ce qu'un desk reçoit. Une sonde élargie à dix-neuf formulations
plausibles a donné **dix** au but. Quatre autres classes du même défaut :

| Classe | Exemple | Cause |
| --- | --- | --- |
| Verbe de perte | `I lost my password.` | alias absent |
| Impératif nu | `Remove a colleague from the sales distribution list.` | aucun marqueur de demande ne reconnaît une phrase sans « je » |
| Demande pour un tiers | `We have a new hire on Monday, he needs an email.` | idem — le demandeur parle d'un autre |
| Nom synonyme d'un voisin | `Please install Adobe Acrobat on my machine.` | égalité avec Printer installation, tranchée par personne |
| Service jumeau | `My password expired and I cannot log in.` | AD Password Expiry Reminders porte les mêmes mots |

**Vocabulaire et marqueurs seulement.** Le plancher et l'écart restent
inchangés, donc une phrase qui convient encore à plusieurs services part
toujours en bibliothèque. C'est le bon arbitrage : une réponse de politique sur
une demande est un moment faible, un aiguillage confiant vers le mauvais service
est une promesse rompue. Le service des rappels d'expiration passe par la
subsomption déjà en place (un reset résout un mot de passe expiré), pas par un
mot ajouté au hasard.

Dix-sept des dix-neuf sur dix-neuf après correctif ; les deux restantes tombent
en bibliothèque, sans jamais partir sur un autre service. Onze formulations
verrouillées par test, plus un test qui vérifie que `lost` ne transforme pas la
politique du téléphone d'authentification perdu en demande de reset.

Livré en `f6f79acd`, 420 tests verts, frontend recréé via `/root/nawa-deploy.sh`.
Vérifié sur le domaine public : `I lost my password.` → identité demandée, run
créé (POST 200), mot de passe temporaire émis, ticket clôturé ; impératif et
demande pour un tiers jouent leur procédure avec porte ; la question de politique
reste une question.
