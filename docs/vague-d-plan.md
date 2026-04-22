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
| D7 | Build + deploy VM + smoke tests Vague D | P0 | S | D0→D6 |

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

*Backlog cosmétique (hors scope)*
- Charts Chart.js dans `quality-dashboard` et `news-lab` ont encore
  des grilles `rgba(255,255,255,0.06)` qui s'évaporent en light. À
  migrer vers une option locale-aware quand on touche les dashboards.
- Auth pages (`signin`, `signup`, `password-reset`) gardent des
  `inset 1px rgba(255,255,255,0.06)` décoratifs invisibles en light,
  sans casse.
- Toast (`ngx-toastr`) utilise encore son thème sombre par défaut.

**Done quand — ✅**
- Les 3 états du toggle bougent proprement `document.documentElement`.
- Surfaces structurelles (title-bar, side-rail, mini-rail, command
  palette, chat overlay, panel, tabs, auth card, run-view) ne cassent
  pas en `[data-theme="light"]`.
- Primitives `ck-tag` solid + `ck-panel` + `ck-tabs` popover rendent
  correctement dans les deux thèmes (contraste texte/fond vérifié).
- `npx tsc --noEmit` clean (hors `icon-registry` pré-existant).

### D5 — Dette technique C11

| Item | Action | Effort |
| ---- | ------ | ------ |
| Sass `@import` deprecation | `sass-migrator import src/**/*.scss` | 30 min |
| `drawflow` CJS bailout | `angular.json → allowedCommonJsDependencies: ["drawflow"]` | 5 min |
| `signin.component.ts` > budget CSS (6 kB) | Soit augmenter le budget (`"maximumWarning": "8kb"`), soit extraire les styles hero vers un SCSS partagé | 15 min |
| Warnings build restants éventuels | Auditer le log `ng build -c production` post-D1..D4 | 30 min |

### D6 — Tests d'intégration walker DAG

**Pytest end-to-end** (le smoke C11 a validé les routes + 401, pas le
comportement runtime) :
- `test_run_engine_dag_e2e.py` :
  - `task → task → task` séquentiel : même outcome que
    `execute_run` (parité de sortie).
  - `source → fork → [task, task] → join → sink` : les deux branches
    s'exécutent, `join` attend le dernier, outcome agrégé.
  - `decision` avec condition vraie / fausse : branche active
    cohérente, l'autre marquée inactive dans les checkpoints.
  - `retry(attempts=3, backoff=…)` autour d'un skill qui fail 2 fois
    puis réussit : outcome `completed`, 3 `SkillInvocation` persistées.
  - `loop` sur une liste de 3 items : 3 `SkillInvocation`, outputs
    concaténés dans le context.
  - `hitl` : run → `hitl_pending` → `POST /hitl accept` → reprise →
    outcome final. Même run avec `reject` → `failed` avec
    `error.reason = "hitl_rejected"`.
  - `subflow` inlined : skills du target system s'exécutent dans le
    contexte du run parent.
- `test_run_engine_events.py` étendu : `token_delta` plug en place
  après D2.

**Playwright e2e** (UI smoke) :
- Connexion Keycloak → `/orchestration` → DAG fork/join → Execute →
  terminal stream `node_start`/`node_end` des deux branches → outcome
  tile rendered.
- DAG avec HITL → run → carte HITL visible → Approve → run complète.
- Debug mode ON + breakpoint sur 1 node → Execute → `debug_pending`
  visible → Step / Continue → complete.
- Replay sur run complété → events cinématiques.

**Done quand**
- `pytest backend/app/tests/services/test_run_engine_dag_e2e.py`
  vert avec ≥ 7 scénarios.
- `npx playwright test` vert avec ≥ 4 scénarios UI.
- Integration dans le CI existant ou un `scripts/test-vm.sh` à lancer
  avant chaque deploy.

### D7 — Build + deploy VM + smoke Vague D

Miroir de C11 : `ng build -c production` sur VM, rsync dist,
`pkill / uvicorn restart`, smoke automatisé sur les routes + 401 + nouveaux
endpoints (`/api/v1/workspaces`, `/api/v1/workspaces/{id}/members`,
`token_delta` dans un run, switch locale, switch thème).

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
- Démo : `https://agentium.papai.ai`
