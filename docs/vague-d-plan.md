# Agentium — Plan Vague D

## Objet du document

Ce document formalise **Vague D**, l'ensemble des chantiers qui ont été
explicitement différés pendant Vague C lorsque l'utilisateur a choisi
« Option B » (fold-in maximal dans Vague C), plus la dette technique
collectée pendant le build / deploy de C11.

Vague D n'est **pas** une extension feature : c'est le complément
nécessaire pour passer la démo agentium.papai.ai d'un mode _single-user
guest_ à un mode _multi-tenant production-ready_, avec un fini
multilingue et thématique.

Il s'aligne sur le même contrat d'arbitrage que
[`agentium-realignment-plan.md`](./agentium-realignment-plan.md) :
- [Mental model](./mental-model.md) = source normative sémantique
- [Deck produit](./deck-product-review.md) = source normative d'intention
- [Mockups](./mockups) = source normative visuelle

## Contexte — d'où vient Vague D

Pendant la décision « Option B » de Vague C, quatre chantiers ont été
sortis du périmètre pour ne pas faire déraper la vague au-delà de 11
commits :

1. **Multi-tenant Workspaces via Keycloak** (OIDC réel)
2. **Streaming LLM token-by-token** (C7.2 explicitement cancelled)
3. **i18n FR / EN** (switcher + extraction)
4. **Light theme** (complément du dark actuel)

Par ailleurs, le smoke C11 a confirmé la route fonctionnelle mais a
laissé trois items de dette technique et un trou de couverture
automatisée sur le walker DAG.

**Ajout post-rétro Vague C** : la suppression du vocabulaire `playground`
a laissé un trou d'UX — le `ChatPanelComponent` (~955 lignes, RAG
complet) existe mais n'est accessible que depuis `/systems/:id` →
bouton Chat → side-panel. Aucune surface globale "je veux juste
poser une question maintenant", aucun flow "drop-and-ask" (déposer
des PDF et chatter dessus en 10 s), et aucun lien découvrable depuis
la side-rail. Bloqueur démo immédiat — on ouvre donc Vague D par un
D0 qui rétablit cette surface.

## Invariants à préserver

- Aucun commit de Vague D ne doit casser une route actuellement en
  `200` sur `agentium.papai.ai` (cf. liste des 12 routes du smoke C11).
- Aucun commit ne doit régresser le mental model (pas de retour de
  `agent / trace / playground`, pas de perte de la canonicalité DAG /
  SSE / HITL / Debug livrée en Vague C).
- Le **run engine** (DAG walker + sequential) reste inchangé sur son
  comportement observable : Vague D ne touche pas à `execute_run`,
  `execute_run_dag`, `_execute_task_node`, `_finalize_run`. Seuls des
  points d'extension explicites (token streaming hook) sont ajoutés.
- La cohabitation dark/light et FR/EN doit rester **un seul et même
  bundle** (pas de fork de composants) — un switch de `signal` / CSS
  vars et rien de plus.

## Plan chiffré — D0 → D7

| # | Titre | Priorité | Taille | Dépend de |
| - | ----- | -------- | ------ | --------- |
| **D0** | **Chat workspace surface : route `/chat` plein écran + icône title-bar + ⌘J + commandes palette + context éphémère drop-and-ask** | **P0** | **M** | — |
| D1 | Keycloak OIDC multi-tenant (full auth + workspace scope backend + picker UI) | P0 | L | — |
| ~~D2~~ | ~~Streaming LLM token-by-token via SSE `token_delta`~~ ✅ livré | ~~P1~~ | ~~M~~ | C7 (event bus) |
| ~~D3~~ | ~~i18n FR / EN~~ — infra runtime + switcher livrés, passe complète en backlog | P2 | M | — |
| ~~D4~~ | ~~Light theme~~ — tokens livrés, sweep shadows/scrim/tints, toggle 3-états FR/EN | P2 | S | — |
| D5 | Dette C11 : Sass `@import` → `@use`, drawflow CJS allowlist, signin budget | P3 | S | — |
| D6 | Tests d'intégration walker DAG (pytest e2e + Playwright UI fork/join/HITL/debug) | P1 | M | C6/C8 |
| ~~D7~~ | ~~Build + deploy VM + smoke tests Vague D~~ — scripts prêts, exécution humaine requise | P0 | S | D0→D6 |

Taille : S ≈ ½ journée, M ≈ 1 à 2 jours, L ≈ 3 à 5 jours.

### D0 — Chat workspace surface

**Contrat produit** — le chat doit être **omniprésent sans polluer la
taxonomie des 5 verbes cockpit** (`hypervisor / build / operate /
steer / govern`). Trois portes d'entrée qui pointent vers la même
surface :

1. **Icône `message-square` persistante dans la title-bar (48 px)**,
   entre le `ck-live-dot` et le theme toggle. Tooltip `Chat · ⌘J`.
   Clic → side-panel flottant 560 px (même primitive `ck-panel` que
   le Chat actuel dans `/systems/:id`, mais global).
2. **Raccourci clavier `⌘J` (macOS) / `Ctrl+J` (Linux/Windows)** —
   symétrique à `⌘K` (palette) — ouvre le même side-panel depuis
   n'importe quelle vue. Pas de conflit avec les shortcuts navigateur
   (⌘J = downloads qu'on peut surcharger sans drame sur SPA).
3. **Commandes dans la command palette (⌘K)** :
   - `Ask a question…` (Quick ask, aucun system requis)
   - `Chat with: <system>…` (picker de system dans la commande)
   - `Drop files and ask…` (ouvre direct en mode dropzone)
4. **Route plein écran `/chat`** (pas dans side-rail) pour focus mode
   et démo "drop-and-ask" sur grand écran. Partageable par URL :
   `/chat?system=<id>` ou `/chat?context=<ephemeral-id>`.

**Trois modes dans la surface**

- *Quick ask* — aucun System, utilise les defaults RAG du workspace.
  Bouton "Attach a system →" pour basculer vers mode 2.
- *Ask a system* — System picker (dropdown header du panneau) ; le
  chat utilise la policy / skills / knowledge du system sélectionné.
  Équivalent fonctionnel du bouton Chat actuel dans `/systems/:id`,
  mais accessible partout.
- *Drop-and-ask* — dropzone (copie de celle de `/knowledge`) à gauche
  du chat. On lâche N fichiers → un **Context éphémère**
  (`ephemeral=true`, `ttl_hours=24`, scopé à la session) est créé
  côté backend, le chat s'y attache automatiquement. Bouton
  `Persist as Context` pour le transformer en context permanent.

**Backend**

- Réutiliser `POST /api/v1/chat` (existant, câblé au RAG).
- `Context` model : ajouter colonnes `ephemeral: bool = False` et
  `ttl_expires_at: datetime | None`. Migration Alembic additive.
- `POST /api/v1/contexts` accepte `ephemeral=true` + `ttl_hours`,
  crée un Context avec `ttl_expires_at = now + ttl_hours`.
- Job de cleanup : `DELETE FROM contexts WHERE ephemeral = true AND
  ttl_expires_at < now()` — soit cron, soit purge opportuniste dans
  `GET /contexts` (filtrage + delete en lot). Option pragmatique pour
  démo : purge opportuniste suffit.
- Pas de changement du run engine — chaque message = un `Run` comme
  aujourd'hui, observable dans `/runs`, SSE fonctionne déjà.

**Frontend**

- Nouveau `ChatWorkspaceComponent` qui wrappe le `ChatPanelComponent`
  existant + ajoute :
  - Header avec System picker (signal<Systems[]>), status badge
    `Quick ask / <system name> / Drop-and-ask session`.
  - Panneau latéral gauche (dropzone réutilisée de
    `knowledge-base.component.ts`, extraite dans un
    `DropzoneComponent` partagé).
  - Liste des sources/docs attachés à la session avec bouton
    `Persist as Context`.
- Route `/chat` dans `app.routes.ts` (loadComponent, sous `authGuard`).
- Nouveau `ChatOverlayComponent` qui monte le même
  `ChatWorkspaceComponent` dans un `ck-panel position="side"
  width="560px"` — servi par un `ChatOverlayService`
  (`open()` / `close()` / `isOpen` signal).
- Title-bar : ajouter bouton icône `message-square` qui appelle
  `chatOverlayService.open()`.
- Shell ou app-root : listener global `keydown` pour `⌘J` /
  `Ctrl+J` → `chatOverlayService.open()`.
- Command palette : 3 nouvelles commandes wired au service.
- Extraction du `Dropzone` en composant partagé
  `@app/shared/ui/dropzone.component.ts` pour ne pas dupliquer la
  logique de `knowledge-base.component.ts`.

**Done quand**

- Depuis n'importe quelle vue, `⌘J` (ou clic sur l'icône title-bar)
  ouvre le chat en < 200 ms. Fermé par `Esc` ou re-clic.
- Quick ask fonctionne sans sélectionner de system (utilise defaults
  workspace).
- Drag-drop de 3 PDF sur la dropzone → context éphémère créé,
  question "résume-moi ces docs" répond en s'appuyant sur eux,
  visible dans `/runs` comme un run normal.
- Route `/chat` plein écran accessible et partageable par URL.
- Chaque message produit un `Run` réel observable dans `/runs`.
- Aucun changement sur la side-rail 5-verbes (cockpit taxonomy intact).

### D1 — Keycloak OIDC multi-tenant (hardening)

**Contexte**
L'audit d'avril 2026 a révélé que l'infra OIDC est déjà en place : flux
Authorization Code + PKCE frontend, `get_current_workspace` backend,
`WorkspacePickerComponent` title-bar. D1 passe donc de
« implémentation » à « hardening pour vrais clients ». L'objectif est
d'éliminer les chemins latéraux restants, d'automatiser la preuve
d'isolation et de clore le cycle onboarding/offboarding.

**Contrat produit (inchangé)**
- L'utilisateur s'authentifie via Keycloak (realm `agentium`).
- Un user peut appartenir à N workspaces ; le workspace actif est
  stocké côté backend + reflété dans `X-Workspace-Slug` côté front.
- Toute requête API hors `/api/v1/auth/*` exige un JWT valide + un
  workspace résolu (sinon 401 / 400 explicite).

**Backend — hardening livré**
- Audit exhaustif des 28 fichiers d'endpoints (`agents`, `audit`,
  `settings`, `metrics`, `models`, `voice`, `help_content`, `traces`,
  `reasoning`) : tout ce qui touche à de la donnée tenant passe par
  `get_current_workspace`, le reste est au minimum gated par
  `get_current_user`.
- Correction de deux fuites réelles :
  - `POST/GET /audit` ne posait ni filtre `workspace_id` ni stampe
    d'acteur fiable → le modèle `AuditLog` exposait tous les audits de
    tous les tenants. Corrigé : écriture stampée serveur-side (username
    authentifié), lecture filtrée sur `workspace_id`.
  - Le proxy legacy `/settings` écrivait sur la ligne singleton
    `rag_presets(workspace_id = NULL)` — toute mutation touchait les
    defaults plateforme. Corrigé : scoping via `get_current_workspace`.
- Flow `Invite teammate` finalisé : si l'email cible existe déjà en
  Keycloak → stub le `User` local + ajoute la membership ; sinon →
  provisionne l'user Keycloak avec les required actions
  `UPDATE_PASSWORD` + `VERIFY_EMAIL` et déclenche
  `execute-actions-email`. La réponse remonte `invitation_email_sent`
  pour que l'UI annonce « Invitation email sent » vs « Member added ».

**Frontend — hardening livré**
- Copy de `WorkspaceMembersComponent` mis à jour : plus de message
  « Email invites coming soon » — l'invitation mail est gérée par le
  backend.
- Toast adapté : distingue provisioning Keycloak (email envoyé) et
  simple ajout d'un user existant.

**Onboarding opérateur livré**
- `docs/operator-tenant-provisioning.md` : playbook end-to-end
  (self-service, VIP-driven, offboarding, backup/restore, smoke).
- Seeds réalistes dans `backend/keycloak/realm-export.json` :
  `alice@acme.test` / `alice-demo` et `bob@globex.test` / `bob-demo`
  pour alimenter les POC et le script d'isolation.

**Preuve d'isolation livrée**
- `backend/scripts/test_tenant_isolation.sh` : script bash paramétrable
  qui log Alice + Bob, crée leurs workspaces/systèmes, vérifie qu'aucun
  ne voit l'autre (list, GET direct, PATCH direct, spoof de
  `X-Workspace-Slug`, isolation des audit logs). Exit-code non-nul
  dès la première fuite — à brancher en CI / en smoke post-deploy.

**Reste à faire côté VM (manuel, hors agent)**
- Exposer Keycloak sur un hostname dédié (p. ex.
  `auth.agentium.papai.ai`) ou router `/realms/*` vers le conteneur
  via le reverse-proxy — la sonde externe actuelle renvoie la SPA.
- Lancer `test_tenant_isolation.sh` en prod après exposition publique
  de Keycloak et configuration SMTP.

**Done quand**
- Deux comptes Keycloak distincts voient chacun leurs propres `Run`,
  `System`, `Skill`, `Knowledge` (vérifié par
  `test_tenant_isolation.sh`, 0 fail).
- Un admin peut inviter un email inexistant en Keycloak et le
  destinataire reçoit un lien d'onboarding.
- Plus aucun endpoint hors `/auth`/`/health`/`/help_content GET` ne
  répond à un appel anonyme.

### D2 — Streaming LLM token-by-token ✅ livré

**Contrat produit**
- Pendant un `node.kind = task` dont la skill appelle un LLM, le SSE
  `/runs/{id}/stream` émet un event `token_delta` par chunk LLM
  (typiquement 5–50 ms).
- Le terminal Execution rend chaque delta en mode typewriter dans le
  message courant ; `node_end` fige la version finale.

**Backend — livré**
- Nouveau module `backend/app/services/run_engine/streaming.py` :
  - `TokenSink` (alias `Callable[[str], None]`).
  - `make_token_sink(run_id, node_id, invocation_id, bus)` : closure
    qui publie `{"kind": "token_delta", "node_id", "invocation_id",
    "text", "seq"}` sur `RunEventBus`.
  - Coalescing interne (`min_flush_chars=8`, `min_flush_interval_s=0.04`)
    pour éviter la surcharge SSE quand un LLM crache 100+ tokens/s.
  - `flush_token_sink(sink)` draine le buffer résiduel juste avant
    `node_end` pour garantir que la dernière rafale passe.
- `_execute_task_node` (`engine.py`) :
  - Fork du ctx via `skill_ctx = dict(ctx)` pour éviter qu'un sibling
    DAG ne récupère le sink d'un autre branche.
  - Injecte `ctx["token_sink"]` UNIQUEMENT si `event_bus.is_live(run.id)`
    — donc sequential walker (sans subscriber SSE) reste à coût zéro.
  - Appelle `flush_token_sink()` dans `finally`.
- Skills streamées :
  - `_azure_llm_v1` : consomme `ctx["token_sink"]` via
    `OpenAIClient.stream()` (fallback propre sur `generate()` en cas
    d'erreur de stream).
  - `_llm_rag_answer_v1` : propage le sink à `rag_service.answer()`.
  - `rag_service.answer()` : nouveau param `token_sink` qui ré-émet
    chaque `chunk_type = "text"` de l'orchestrateur.
- Pas de flag workspace — le plumbing est no-op tant que personne
  n'écoute le bus. On ajoutera un `features.llm_streaming = false`
  côté settings si un tenant demande le fallback "logs bruts".

**Frontend — livré**
- `RunStreamService` : déjà agnostique — `token_delta` passe via le
  parser SSE existant (champ `event.event = "token_delta"`).
- `workflow-editor.component` (terminal block) :
  - Nouveau champ `streamId` sur `TerminalEntry`.
  - Nouvel helper `appendStreamToken(streamId, delta, tag, tone)` :
    append in-place si une entrée avec le même `streamId` existe
    déjà, sinon créé une entrée neuve. Groupé par `invocation_id`
    (fallback `node_id`, puis `run_id`).
  - Case `token_delta` dans `emitStreamEvent` : appelle l'helper
    avec tag `LLM` et tone `cyan`.
  - Cap à 200 entrées du terminal conservé.

**Tests — livré**
- `backend/app/tests/services/test_run_engine_streaming.py` :
  - Publication basique (`run_id / node_id / invocation_id / seq`).
  - Coalescing (`min_flush_chars` bloque puis libère).
  - `flush_token_sink` draine le résidu.
  - Safe sur `None` et chunks vides.

**Hors scope / reporté**
- **Replay cinématique** : le frontend simule le typewriter à partir
  de l'output finalisé (`SkillInvocation.output_ref`). Persister les
  deltas pour rejouer au rythme exact serait un gros bloat
  (checkpoint JSON qui explose). Sera ré-examiné si un vrai besoin
  produit apparaît.
- **Flag workspace `features.llm_streaming`** : pas livré — le
  plumbing est déjà opt-in (nécessite un subscriber SSE actif).
- **Chat overlay (D0)** : le panel utilise déjà son propre stream
  via `rag_service` direct ; pas de token_delta à propager. Le
  stream actuel (`chat_stream`) remplit déjà le même rôle côté UX.

**Done quand — ✅**
- Un run `task` avec LLM affiche un flux token visible à l'écran
  via `/runs/:id/stream?event=token_delta`.
- Le walker sequential (sans subscriber SSE) reste inchangé à cost-0.
- Les tests unitaires couvrent publication + coalescing + flush.

### D3 — i18n FR / EN — infra livrée, passe complète en backlog

**Contrat produit**
- Switcher dans l'account menu : FR (défaut) / EN, swap instantané.
- Toutes les chaînes statiques de l'UI sont traduites ; pas de
  traduction des données utilisateur (noms de systèmes, prompts, etc.).

**Stratégie retenue — Option C (hybride runtime + passe progressive)**

Angular i18n "officiel" aurait imposé : `ng add @angular/localize`, passe
`i18n=` sur **chaque** template inline de 80 composants, bundles par
locale, et surtout **pas de live switch** (reload requis pour changer
de locale). Effort réaliste : 3-5 jours pour un résultat rigide.

À la place on livre un service i18n runtime signal-based : un seul
bundle, switch live, dictionnaires flat JSON-like, annotation
progressive. C'est ce que font la majorité des cockpits SaaS parce que
l'UX du switcher est supérieure et l'infra build/nginx reste inchangée.

**Infra livrée**
- `frontend-ng/src/app/core/i18n.service.ts` :
  - `locale: signal<Locale>` persisté en `localStorage`, initialisé
    depuis la clé stockée, `?lang=` query-string, ou `navigator.language`.
  - `t(key, params?) = string` qui lit le signal → toute template qui
    appelle `i18n.t('…')` re-render au flip FR/EN.
  - Fallback chain : `EN[key] → FR[key] → key` — FR est 1st-class,
    EN a le droit d'avoir des trous, la clé brute reste visible pour
    audit.
  - Interpolation minimaliste `{name}` placeholders, pas de pluralisation.
  - Effet side-effect : `document.documentElement.lang = locale`.
- `frontend-ng/src/app/core/i18n.dict.ts` : ~140 clés FR + EN couvrant
  common actions, title-bar, nav/rail, account menu, auth, chat,
  palette, systems/runs shells, workspace shell, empty/error states.
  Export du type `I18nKey` pour vérification compile-time des appels.

**Switcher livré**
- Section "Langue / Language" dans le popover du menu utilisateur
  (title-bar) : deux boutons pill `FR` / `EN` au-dessus de "Sign out".
  Swap instantané via `I18nService.setLocale()`. Persistance automatique.

**Première passe livrée — surfaces critiques**
- Title-bar : tooltip chat, toutes les entrées du menu utilisateur,
  label du switcher.
- Side-rail : les 5 verbes cockpit (Hypervisor/Build/Operate/Steer/Govern)
  + leurs hints + le footer "Jump to…".
- Mini-rail : header `SCOPE <verb>` + labels de sections
  (Systems, Capabilities, Skills, Knowledge, Flows, Runs, Observability,
  Intelligence, Missions, Control plane, Contexts, Apps, Resources,
  Presets…).
- Command palette : placeholder input + état vide / chargement.
- Chat overlay : eyebrow `Chat · ⌘J` + title dynamique selon le mode.

**Backlog explicite (hors scope D3)**
- Passe complète sur les 70+ composants restants : systems-builder,
  workflow-editor, runs-list, run-view, knowledge-base, governance,
  observability dashboards, presets, contexts, chat-workspace body,
  all empty-state components, all confirm dialogs, auth screens
  (signin/signup/reset), account shell.
- Les strings internes aux composants (labels in-code dans des tableaux
  de config comme `COCKPIT_VERBS.sections`, `CommandItem.label`,
  `NodeTypeDef.label` de `workflow-editor`) sont déjà couverts quand
  un key `nav.<key>` existe ; pour les autres il faut ajouter
  l'entrée au dict puis switcher en template `i18n.t(…)`.
- ToastrService messages (`toastr.success('Workspace created')` etc.)
  restent en anglais — un pass dédié viendra quand le backlog passe.
- Dates / nombres : pas encore formatés par locale (`DatePipe` avec
  `LOCALE_ID` dynamique) — à ajouter si un client demande.

**Done quand — ✅ infra**
- Switcher visible, persisté, swap live sans reload.
- Premier lot (~140 clés) traduit FR+EN sur les surfaces structurelles.
- Zéro régression tsc (`npx tsc --noEmit` clean hors `icon-registry` pré-existant).

### D4 — Light theme ✅ livré

**Contrat produit**
- Toggle cockpit 3-états : `dark` / `light` / `system` (suit l'OS).
- Aucun changement fonctionnel, juste un remap de tokens CSS.
- Tooltip du bouton de thème traduit FR/EN, indique l'état courant +
  la prochaine étape du cycle.

**Infra déjà en place avant D4**
- `ThemeService` (`frontend-ng/src/app/core/theme.service.ts`) :
  `signal<'dark' | 'light' | 'system'>` persisté en `localStorage`,
  écoute `prefers-color-scheme` quand `system`, applique `.dark` +
  `data-theme="dark|light"` sur `<html>`.
- Cycle via le bouton cockpit dans la title-bar
  (`cycleTheme()` : light → dark → system → light…).
- Jeux de tokens `[data-theme="light"]` (bg, fg, stroke, signals) déjà
  définis dans `frontend-ng/src/styles/cockpit-tokens.scss` avec une
  palette "papier chaud" (`#f4f2eb` base, `#fafaf6` panel, `#0a0c10` fg).

**Ce que D4 ajoute**

*Nouveaux tokens pour sortir du "50 % noir qui crie sur papier chaud"* :
- `--ck-shadow-panel` / `--ck-shadow-popover` / `--ck-shadow-card` :
  ombres réutilisables, avec un variant light en tons bleus très peu
  opaques (`rgba(17,24,39,0.14)` plutôt que `rgba(0,0,0,0.50)`).
- `--ck-scrim` : scrim des overlays (panel, palette, modales), reste
  sombre mais moins agressif en light (0.28 vs 0.45).
- `--ck-on-signal` : couleur du texte sur fond signal saturé. Dark →
  `#05070a` (texte noir sur vert vif), Light → `#ffffff` (texte blanc
  sur vert foncé). Règle la lisibilité des `ck-tag variant="solid"` et
  de tout bouton primary signal.
- `--ck-tint-faint` / `--ck-tint-soft` : washes neutres qui flippent
  de blanc translucide (dark) à noir translucide (light) — utilisés par
  les pills neutres, hovers, empty-state wells.

*Sweep des hardcodes critiques* :
- `shared/cockpit/panel.component.ts` : boxShadow + scrim passés aux
  tokens.
- `shared/cockpit/tag.component.ts` : `textColor` solid passe par
  `--ck-on-signal`, neutral soft passe par `--ck-tint-faint`.
- `shared/cockpit/tabs.component.ts` : popover shadow → token.
- `shared/cockpit/help-tooltip.component.ts` : card shadow → token.
- `features/layout/title-bar.component.ts` : popovers user/workspace →
  `--ck-shadow-popover`. Tooltip 3-états traduit FR/EN via `i18n.t`.
- `features/auth/auth-shell.component.ts` : carte auth → token (retire
  le triple box-shadow avec halo cool qui brûlait en light).
- `features/runs/run-view.component.ts` : deux inputs inline
  `color:white` + `background:rgba(255,255,255,0.04)` → tokens
  `--ck-bg-inset` / `--ck-fg-1` (étaient illisibles en light).
- `styles/cockpit-utilities.scss` : hover card shadow → token.

*Audit complémentaire post-commit `80dc9d6` → `TBD`*

Un second passage dédié a élargi la couverture des **boutons primary
signal** après vérification exhaustive. Tous les sites où un bouton /
badge avatar utilisait `background: var(--ck-signal-X); color: #020617`
(ou `#0a0a0a`, `#0f172a`, `var(--ck-bg-base)`) ont été convertis à
`color: var(--ck-on-signal)` — blanc en light, noir en dark, APCA safe
dans les deux sens. Sites corrigés :

- `features/orchestration/workflow-editor.styles.scss` — bouton HITL
  accept (`.df-hitl-btn--accept`) qui aurait rendu dark text sur dark
  green en light.
- `features/runs/run-view.component.ts` — "Submit override" button.
- `features/orchestration/workflow-editor.component.ts` — primary
  action bouton du builder.
- `features/systems/system-view.component.ts`,
  `features/systems/system-builder.component.ts` (×2),
  `features/systems/systems-grid.component.ts` (×3) — boutons "Create",
  "Save", avatar initial.
- `features/steering/steering.component.ts` — bouton "Apply levers".
- `features/tasks/tasks-page.component.ts` — bouton "Run task".
- `features/observability/quality-dashboard.component.ts` — bouton
  "Run evaluation".
- `features/layout/title-bar.component.ts` — 5 sites (workspace initial
  badges, user initial avatar, "Create workspace" submit, locale
  switcher pill).

*Backlog documenté (hors scope D4)*
- Charts Chart.js (`quality-dashboard`, `news-lab`) ont des grilles
  `rgba(255,255,255,0.06)` qui s'évaporent en light. À migrer vers
  une option locale-aware quand on touche les dashboards.
- Auth pages (`signin`, `signup`, `password-reset`) gardent des
  `inset 1px rgba(255,255,255,0.06)` décoratifs invisibles en light,
  sans casse structurelle.
- Feature pages legacy rédigées en Tailwind classique (`news-lab` 19
  occurrences, `presets-list` 13, `chat-panel` 8, `rag-settings` 8,
  `workflow-editor` 7 en Tailwind pur) utilisent `text-white`,
  `bg-slate-900`, `bg-black/20` etc. sans préfixe `dark:`. Ces pages
  seraient illisibles en light — à migrer vers la grammaire cockpit
  (`--ck-bg-panel`, `--ck-fg-1`, `ck-tag`…) dans un pass dédié, pas
  à coup de sed Tailwind. Certaines (comme `chat-panel`) sont déjà
  partiellement theme-aware via `dark:text-white` / `text-gray-900`,
  elles n'ont donc pas besoin d'être touchées en priorité.
- Toast (`ngx-toastr`) utilise encore son thème sombre par défaut.

**Done quand — ✅**
- Les 3 états du toggle bougent proprement `document.documentElement`.
- Surfaces structurelles (title-bar, side-rail, mini-rail, command
  palette, chat overlay, panel, tabs, auth card, run-view) ne cassent
  pas en `[data-theme="light"]`.
- Primitives `ck-tag` solid + `ck-panel` + `ck-tabs` popover rendent
  correctement dans les deux thèmes (contraste texte/fond vérifié).
- `npx tsc --noEmit` clean (hors `icon-registry` pré-existant).

### D5 — Dette technique C11 ✅

**Livré (commit `feat(d5)`)** : quatre nettoyages groupés pour faire taire
les warnings build prod accumulés depuis C6.

**Sass `@import` → `@use` (Dart Sass deprecation)**
- Audit : seulement 4 `@import` dans tout le SCSS.
  - `src/styles.scss` → `@import 'styles/cockpit-tokens.scss'` et
    `'styles/cockpit-utilities.scss'` (SCSS modules, affectés par la
    deprecation).
  - `src/styles.scss` → `@import '@angular/cdk/overlay-prebuilt.css'`
    (CSS pur, `@import` reste légitime).
  - `src/app/features/orchestration/workflow-editor.styles.scss` →
    `@import 'drawflow/dist/drawflow.min.css'` (CSS pur, idem).
- Fix : les deux imports SCSS sont migrés vers `@use`. Comme les deux
  fichiers n'émettent que des CSS custom properties (`:root { --ck-* }`)
  et des classes utilitaires globales (`.ck-mono`, `.ck-panel`…), le
  namespacing `@use` n'a aucun impact sur la cascade — la sortie CSS est
  bit-pour-bit identique à l'ancien `@import`.
- Vérifié avec `npx sass --load-path=node_modules src/styles.scss
  /tmp/out.css` : compile proprement, 0 deprecation warning, 28 kB de
  CSS global (inchangé).

**`drawflow` CommonJS bailout**
- `angular.json → architect.build.options.allowedCommonJsDependencies:
  ["drawflow"]` ajouté. Supprime le warning esbuild :
  *"CommonJS or AMD dependencies can cause optimization bailouts"*.
- Pas de risque tree-shaking : `drawflow` est un plugin DOM imperatif
  entièrement chargé par le composant `workflow-editor`.

**Budget CSS `anyComponentStyle` : 6 kB → 8 kB**
- `signin.component.ts` émet un hero SCSS de ~7 kB (gradients, grid,
  typography responsive). Extraire dans un partial partagé coûte plus
  que ça vaut tant que seul `signin` utilise ce chrome.
- Nouveau plafond : `maximumWarning: 8kB`, `maximumError: 20kB`
  inchangé. Marge raisonnable sans désactiver la garde.

**Audit warnings `ng build -c production`**
- Build prod exécuté en CI uniquement (l'env dev local est bloqué en
  Node 17 qui est sous la version min Angular 17+, `ERR_REQUIRE_ESM`
  sur yargs). Documenté comme check CI, plus source-of-truth que le
  poste dev.
- Warnings connus post-D1..D4 et leur statut :
  - Sass `@import` deprecation → fixé ci-dessus.
  - `drawflow` CJS → allowlisté ci-dessus.
  - Budget `signin.component` → budget bumped.
  - Pas de nouveau warning attendu des changements D1..D4 (TS pur,
    tokens CSS, ajouts d'endpoints Python).
- Si un warning surgit au prochain build CI, il sera traité dans la
  PR correspondante.

**Fichiers modifiés**
- `frontend-ng/src/styles.scss` — `@import` SCSS → `@use`, commentaires
  explicatifs. CSS `@import` conservés avec justification inline.
- `frontend-ng/angular.json` — `allowedCommonJsDependencies:
  ["drawflow"]` + budget `anyComponentStyle` 6kB → 8kB.

**Done quand — ✅**
- `npx sass src/styles.scss` compile sans deprecation warning.
- Les `@import` résiduels pointent explicitement vers des fichiers
  `.css` (non affectés par la deprecation Sass).
- `angular.json` allowlist `drawflow`, budget component-style relâché
  à 8 kB.
- `npx tsc --noEmit -p tsconfig.app.json` : inchangé (seulement les
  erreurs `icon-registry` pré-existantes — voir suite C/D).

### D6 — Tests d'intégration walker DAG ✅

**Livré (commit `feat(d6)`)** : 8 scénarios pytest e2e qui couvrent le
runtime complet du walker DAG + deux bugs de walker corrigés au passage.
Playwright reporté (cf. backlog ci-dessous).

**Test harness — `backend/app/tests/conftest.py`**
- Force `DATABASE_URL=sqlite:///tmp/pytest_omnirag.db` avant le premier
  `from app.*` (l'env dev local n'a pas `psycopg2`, Postgres n'est pas
  requis pour les tests d'engine).
- Neutralise `QDRANT_URL` et `REDIS_URL` pour que l'import des models
  et services ne déclenche pas d'appels réseau au collection-time.
- Fixture session `_provision_schema` : `Base.metadata.create_all(engine)`
  une seule fois, 26 tables créées.
- Fixture function `db_session` : TRUNCATE des tables runtime entre
  chaque test (systems, runs, skill_invocations, decisions, skills,
  capabilities, workspaces) — faster qu'un drop/create complet sur
  SQLite.

**Scénarios — `test_run_engine_dag_e2e.py` (8 tests verts)**
1. **`task → task → task` séquentiel** — chaque task reçoit l'output du
   précédent, Run.output_ref reflète le dernier. 3 invocations
   persistées en ordre, checkpoints `run_start` / `run_end` présents.
2. **`source → fork → [task, task] → join → sink`** — les deux branches
   s'exécutent en parallèle, join fusionne les outputs, sink reçoit les
   deux.
3. **`decision` avec condition vraie / fausse** — seule la branche
   `score > 0.5` fire sa task ; le checkpoint `node_end` de la decision
   contient `chosen_branch: "hi"` ; la task de la branche inactive
   n'apparaît jamais dans le ledger.
4. **`retry(max_attempts=3, backoff=0)`** — skill qui fail 2 fois puis
   réussit : 3 `SkillInvocation` rows persistées en ordre
   (`failed, failed, completed`), run `completed` au final.
5. **`loop` sur `ctx.items=[a,b,c]`** — 3 invocations, chacune avec le
   `_loop_index` et `_loop_item` correct dans ctx. Output agrégé
   contient `count: 3`.
6. **`hitl` accept** — premier pass s'arrête en `hitl_pending`, le
   checkpoint `hitl_pause` est bien persisté. On flippe la Decision
   à `accepted`, `resume_run_dag` redémarre, la task post-HITL voit
   `ctx.hitl_approved = True` et le run termine en `completed`.
7. **`hitl` reject** — même pause, mais Decision passée à `rejected` ;
   resume termine le run (pas de hard-stop) avec
   `ctx.hitl_approved = False` propagé à la task aval.
8. **`subflow` inlined** — un System B avec 2 skills, référencé par un
   node `subflow` du System A. Les 2 `SkillInvocation` de B sont bien
   persistées sur le `run_id` de A, et l'output de run contient
   `subflow_system_id` + l'output du dernier skill.

**Bugs walker corrigés au passage (commit inclus)**
- **`_execute_node` : pas de short-circuit sur dead-branches.** Un task
  dont toutes les incoming edges avaient été tuées par une décision
  upstream exécutait quand même son handler (avec input vide). Le
  commentaire explicite de `_settle_node` promettait pourtant le
  contraire. Ajout d'un court-circuit : si `all(in_edges in dead_edges)`,
  on émet un `node_end` avec `status: "skipped", skipped_reason:
  "all_inputs_dead"` et on retourne sans invoquer le skill.
- **`_merge_predecessor_outputs_from_state` retournait `ctx["input"]`
  au lieu de l'output upstream.** Les handlers `_run_task` / `_run_retry`
  / `_run_loop` / `_run_hitl` / `_run_subflow` l'utilisaient → les
  tasks chaînées recevaient l'input run original au lieu de la sortie
  du prédécesseur. Fix : `_execute_node` calcule `merged_input` une
  fois (ce qu'il faisait déjà) puis le passe en param `upstream=` aux
  handlers. Helper mort supprimé.

**Fichiers créés / modifiés**
- `backend/app/tests/conftest.py` (créé) — bootstrap SQLite + fixtures.
- `backend/app/tests/services/test_run_engine_dag_e2e.py` (créé) —
  8 scénarios runtime.
- `backend/app/services/run_engine/dag.py` (modifié) — court-circuit
  dead-branch, param `upstream=` threading dans handlers, suppression
  du helper buggé `_merge_predecessor_outputs_from_state`.

**Done quand — ✅**
- `pytest backend/app/tests/services/test_run_engine_dag_e2e.py` : 8/8
  verts (`8 passed in 0.94s`).
- Pas de régression sur les tests pré-existants : 53 passent, 1 flaky
  pré-existant (`test_subscribe_after_close_resolves_immediately` —
  async timeout indépendant, vérifié sans la branche D6).

**Backlog Playwright (hors scope D6, repoussé à D7+)**
Les scénarios UI (connexion Keycloak → DAG fork/join → terminal
stream → outcome tile ; HITL Approve ; Debug Step/Continue ; Replay)
nécessitent :
- Stack complète up (Keycloak, Qdrant, Postgres) — infra non disponible
  dans l'env dev local qui n'a que Node 17.
- `@playwright/test` + fixtures projet absentes à ce jour.
→ À traiter en bloc avec D7 (deploy VM + smoke) où la stack sera déjà
up ; les 4 flows Playwright deviennent alors un script `test-vm.sh`
post-deploy plutôt qu'une suite CI locale.

### D7 — Build + deploy VM + smoke Vague D — ⚙️ READY-TO-DEPLOY

**Livrables code (prêts, sans accès VM requis) :**

1. **`backend/scripts/smoke_vague_d.sh`** — smoke automatisé en 4 tiers :
   - *Tier 1* : 12 routes canoniques + gating 401 sur `/systems`,
     `/runs`, `/audit`, `/settings`, `/skills`, `/capabilities`,
     `/models`, `/voice`, `/contexts`, `/auth/workspaces` ; `GET /chat`
     sert la SPA (content-type `text/html`).
   - *Tier 2* (auth Alice via Keycloak) : `GET /auth/workspaces`,
     `/auth/workspaces/{slug}`, `/auth/workspaces/{slug}/members`,
     `/systems`, `/audit`, `/settings`, `/contexts` scopés
     `X-Workspace-Slug`. Confirme que la liste workspaces contient bien
     `acme`.
   - *Tier 3* (via `FRONTEND_DIST=…` pointant sur le `dist/` déployé) :
     dictionnaires FR + EN compilés (D3), tokens `data-theme="light"`,
     `--ck-on-signal`, `--ck-shadow-panel` (D4), chunk `chat-workspace`
     (D0).
   - *Tier 4* (opt-in `SMOKE_RUN_SSE=1`) : programme un run, subscribe
     à `/runs/{id}/stream` 6 s, vérifie la présence de frames
     `token_delta` (D2) et d'événements structurels (`node_end` /
     `run_end`).
2. **`docs/operator-deploy-vague-d.md`** — runbook opérateur qui
   déroule pré-flight → build SPA → rsync → bounce uvicorn → smoke →
   walkthrough UI manuel (≤ 3 min) → rollback. Inclut la migration
   Alembic `010_context_ephemeral` (D0) et pointe vers
   `test_tenant_isolation.sh` (D1) pour la vérif multi-tenant.

**À exécuter sur la VM (humain / CI) :**

```bash
# 1. build local
cd frontend-ng && npm ci && npx ng build -c production

# 2. push SPA + backend
rsync -az --delete frontend-ng/dist/frontend-ng/browser/ \
  deploy@agentium.papai.ai:/srv/agentium/frontend/
ssh deploy@agentium.papai.ai \
  'cd /srv/agentium/omnirag && git pull && \
   .venv/bin/pip install -q -r backend/requirements.txt && \
   .venv/bin/alembic -c backend/alembic.ini upgrade head && \
   sudo systemctl restart agentium-backend'

# 3. smoke (depuis laptop)
BACKEND_URL=https://agentium.papai.ai \
KEYCLOAK_URL=https://auth.agentium.papai.ai \
ALICE_USER=alice@acme.test ALICE_PASS=alice-demo \
FRONTEND_DIST=/tmp/agentium-dist SMOKE_RUN_SSE=1 \
  backend/scripts/smoke_vague_d.sh

# 4. isolation multi-tenant
backend/scripts/test_tenant_isolation.sh
```

**Pourquoi le déploiement n'est pas exécuté automatiquement :** le
build Angular échoue localement (Node 17, cf. note D5), la VM
`agentium.papai.ai` requiert un accès SSH/Keycloak qui n'est pas dans
le workspace de l'agent, et le rollout production est un point de
décision humain. Tout ce qui est scriptable est scripté ; il reste un
enchaînement de 4 commandes côté opérateur.

**Critères d'acceptation (identiques au §CA global)** :
- Tier 1 = 11 PASS (routes 401 + `/chat` SPA + `/health`).
- Tier 2 = 7 PASS (workspaces, members, audit/settings/systems/
  contexts scopés).
- Tier 3 = 5 PASS (2× i18n + 3× tokens + 1× chat chunk).
- Tier 4 = 2 PASS (`token_delta` + événements structurels) quand un
  système streaming est seedé.
- `test_tenant_isolation.sh` = 0 FAIL.

→ Couvre indirectement les scénarios Playwright déferrés en D6
(tenant isolation, chat overlay, streaming, i18n, thème) via tests
HTTP + bundle introspection + walkthrough manuel. Une vraie suite
Playwright reste un chantier Vague E.

## Ordre conseillé

```
D0 (chat workspace, 1-2j)      ─┐
D5 (dette C11, 1h)              │
└─▶ D4 (light theme, ½ j)       ├─▶ D7 (deploy + smoke)
└─▶ D3 (i18n, 1-2 j)            │
└─▶ D2 (streaming tokens, 1j)   │
└─▶ D1 (Keycloak, 3-5 j)        │
└─▶ D6 (tests intégration, 2j)  ┘
```

D0 en tête parce que c'est le gap démo le plus visible ; on l'attaque
avant Keycloak car la démo solo ne nécessite pas multi-tenant réel.
D1 et D6 sont les poids lourds ; D3 / D4 / D5 peuvent être tissés en
parallèle par une seconde main. D2 dépend de C7 (déjà en prod),
aucune dépendance dure sur les autres.

## Hors Vague D — reste sur la roadmap long terme

Repris de [`deck-product-review.md §27`](./deck-product-review.md) et
[`post-demo-roadmap.md`](./post-demo-roadmap.md) :

- **Évaluation en boucle** : scoring auto post-run sur seuils
  configurables.
- **Recommandations proactives** : `Decision` générée à partir de
  l'analyse agrégée de plusieurs runs.
- **Multi-tenant avancé** : quotas par workspace, billing, isolation
  Qdrant renforcée.
- **Marketplace de capabilities** : packs industry prêts à l'emploi.
- **Simulation hors ligne** : rejouer un run sur une policy
  alternative.
- **Voice end-to-end** : Whisper ingest + TTS output câblés au
  runtime.
- **Sharepoint ingestion v1** : connecteur réel dès que credentials
  démo disponibles.
- **Custom chains éditeur** : scaffold fait en `/orchestration`,
  finition nécessaire.

Ces chantiers ne rentrent pas dans Vague D : ils nécessitent soit des
décisions produit / commerciales, soit un runtime non encore câblé,
soit un ticket d'infra ouvert. On les traitera en Vague E ou plus tard
en fonction du retour démo.

## Critères d'acceptation globaux de Vague D

1. **D0** : depuis n'importe quelle vue, `⌘J` ou l'icône title-bar
   ouvre le chat en < 200 ms ; quick ask / ask-system / drop-and-ask
   fonctionnent sans quitter la vue en cours.
2. Deux utilisateurs Keycloak distincts sur `agentium.papai.ai` voient
   chacun leurs objets, sans fuite (assert par test Playwright).
3. Un run avec skill streaming LLM affiche les tokens en direct dans
   le terminal, puis les rejoue au même rythme.
4. Le switcher langue change l'ensemble de l'UI sans rechargement
   perceptible > 500 ms et persiste après reload.
5. Le switcher thème idem, sans FOUC ni perte d'animations cockpit.
6. `ng build -c production` n'émet plus de warning bloquant
   (deprecation Sass, CJS bailout, budget signin).
7. `pytest` + `playwright` passent en CI (ou via `scripts/test-vm.sh`).
8. Les 12 routes canoniques + `/chat` + les 5 nouveaux endpoints
   répondent avec les codes attendus dans le smoke C11/D7.

## Risques et mitigation

| Risque | Impact | Mitigation |
| ------ | ------ | ---------- |
| Keycloak realm `agentium` pas provisionné sur la VM | D1 bloqué | Provisionner en amont, `docker-compose up keycloak` déjà scripté |
| Migration workspace_id NOT NULL casse des lignes legacy | Prod down | Migration en deux temps : colonne nullable + backfill, puis contrainte |
| Streaming LLM tokens sature le SSE bus | Latence UI | `token_delta` coalescé côté backend (burst > 30ms) + feature flag workspace |
| i18n extraction casse du texte imbriqué HTML | Régression UI | Revue manuelle par route ; snapshot Playwright avant / après |
| Light theme révèle des contrastes cachés | QA long | Audit `axe-core` automatisé dans Playwright |
| Tests e2e DAG lents | Friction dev | Scénarios DAG en test unitaires (graphe + handlers) + un seul e2e wall-clock |

## Références

- [`agentium-realignment-plan.md`](./agentium-realignment-plan.md) — plan T1.1 → T5.6 (livré pré-Vague C)
- [`deck-product-review.md`](./deck-product-review.md) — intention produit, §27 "reste à faire"
- [`post-demo-roadmap.md`](./post-demo-roadmap.md) — chantiers long terme
- [`mental-model.md`](./mental-model.md) — source normative sémantique
- Commits Vague C : `0da259f` (C1) · `c927af8` (C2) · `b706cc6` (C3) · `29413f7` (C6) · `00d8ee0` (C7) · `b8962ac` (C8) · `5f726dd` (C9) · `68657b1` (C10)
- Commits Vague D : `b08e19e` (D0) · `f230c97` (D1) · `5953dde` (D2) · `c83ec46` (D3) · `80dc9d6` + `824b65c` (D4) · `363db52` (D5) · `2fc1a02` + `453da57` (D6) · D7 livré ci-dessous
- Démo : `https://agentium.papai.ai`

## Journal

- **2026-04-21** — D7 : scripts `smoke_vague_d.sh` + runbook
  `operator-deploy-vague-d.md` livrés. Déploiement effectif à faire
  sur la VM (humain / CI).
