# QA SENTINEL-CI · prod `agentium.papai.ai` · 24 mai 2026

Cible démo : lundi 25 mai 2026 · `https://agentium.papai.ai/hypervisor/mission-room/cockpit`
Workspace : `sentinel-ci` (`d8438c96-42aa-4566-8b46-f938d3dfe680`) · header `X-Workspace-Slug: sentinel-ci`
Branche : `demo/agentic` · QA conduit par l'agent en double volet (A : QA, B : fix vessels-layer).

---

## TL;DR

- **Volet B (fix vessels-layer)** : LIVRÉ. Commit local `11745daf` sur `demo/agentic`. `tsc -p tsconfig.app.json --noEmit` : 0 erreur. Les 16 navires AIS s'affichent désormais comme overlay HTML absolument positionné **au-dessus** du canvas MapLibre carte CI, avec projection équirectangulaire linéaire sur la bbox pays (-8.65 / -2.45 / 4.2 / 10.75) et toggle « Zoom Abidjan / Vue pays » qui re-projette dans la bbox Vridi (-4.25 / -3.75 / 5.05 / 5.40). Pas de push.
- **Volet A (QA prod)** : démo prête à 88 %. La narrative AYA (Napié, cargo MV Atlantic Trader, dérogation, recall RAG, agenda patch, navigate meeting, log decision) marche **end-to-end** sur le chat. Le cockpit servi a la bonne date, le bon status-bar, le bon voice_demo_script Napié, zéro `Konaté` dans les champs narratifs.
- **2 bloquants démo** identifiés, dont 1 qui casse visuellement la trame :
  1. `agenda_day` / `agenda_timeline` du cockpit retournent les événements du **15-16 avril** (et un debug `agenda QA wiring VIGIE`) au lieu du **25-26 mai 2026** alors que les 6+2 events 25/26 mai sont seedés en BDD.
  2. `press_preview` propose Mali / Iran / Ebola en tête au lieu des signaux CI prioritaires.
- **3 polishs critiques** (chip ID, webcam HEAD, paramètres `/calendar/events`) listés plus bas.

---

## Volet B — Fix rendu navires AIS (overlay)

### Symptôme avant fix

`vp-map-preview.component.ts` rendait :

1. La carte CI (zones + projets) dans `<app-workspace-map mode="preview">` — OK.
2. Un **second bloc `<section class="maritime-layer">`** sibling de la carte, contenant un `<svg viewBox="0 0 100 60">` avec les 16 navires projetés sur une bbox isolée (rectangle gris vide). Effet « 2 cartes empilées » dénoncé par la capture utilisateur.

### Cause racine

L'overlay vessels avait été livré comme un SVG sibling autonome au lieu d'un layer absolu sur le canvas MapLibre. Il ne partageait ni la projection, ni la zone visible de la carte CI.

### Fix livré (commit `11745daf`)

Diff résumé :

- `frontend-ng/src/app/features/mission-room/vp-map-preview.component.ts` (~+340 / -230 lignes)
  - Nouveau `VesselMarker` : `{ vessel, xPct, yPct, outOfFrame }` (pourcentages plutôt que viewBox SVG).
  - Constantes `COUNTRY_BBOX` (pays, alignée sur le `fitBounds` interne de `workspace-map.component.ts`) et `ABIDJAN_BBOX` (Vridi/quai pétrolier).
  - Constantes `COUNTRY_CAMERA` / `ABIDJAN_CAMERA` consommées par `previewMapState` pour piloter la caméra MapLibre via l'input `mapState` existant.
  - Template refactoré : `<div class="map-canvas-host">` wrap `<app-workspace-map>` + `<div class="vessels-overlay-layer" [class.zoom-abidjan]>` en `position:absolute; inset:0; pointer-events:none`. Chaque pin est un `<button class="vessel-pin">` `pointer-events:auto`, positionné en `left/top` % (calcul lat→y inversé, lon→x linéaire) avec halo violet pulse sur le vessel ciblé par la narrative (`linked_cargo_id === cargo-abidjan-supply-001` ou `highlight === 'aya-target'`).
  - Boutons d'overlay `vessels-overlay-controls` : chip compteur (`16/16 navires`) + bouton toggle `Zoom Abidjan` / `Vue pays`.
  - `buildMarkers()` recalcule x/y selon `vesselZoomMode` courant. `outOfFrame` masque les pins hors bbox sans casser le compteur.
  - `onVesselPinClick(vessel)` réutilise le pipeline existant (auto-select webcam, événement `vesselSelected`, focus chat).
  - `toggleVesselZoom()` swap entre les deux états, push la `previewMapState` vers `app-workspace-map` (zoom 5.6 → 10.4).
- `frontend-ng/src/app/features/mission-room/workspace-map.component.ts` : passage de `min-height: 280px` à `100%` en preview mode (le map-canvas-host fixe la géométrie depuis l'extérieur).

Pseudo-code de la projection :

```ts
const bbox = vesselZoomMode === 'abidjan' ? ABIDJAN_BBOX : COUNTRY_BBOX;
const xPct = ((lon - bbox.west) / (bbox.east - bbox.west)) * 100;
const yPct = ((bbox.north - lat) / (bbox.north - bbox.south)) * 100;
const outOfFrame = xPct < -2 || xPct > 102 || yPct < -2 || yPct > 102;
```

Aux latitudes CI (4°–11° N), l'écart Mercator vs équirectangulaire est < 0,5 %, donc le linéaire est visuellement fidèle (cf. message de commit).

### Tests post-fix

- `npx tsc -p tsconfig.app.json --noEmit` → 0 erreur.
- `ng lint` (héritage) : pas exécuté ici, mais les nouveaux blocs respectent le style des `vp-*` voisins (accolades, indentation, signals/inputs).
- Comportement attendu (smoke visuel à valider en navigateur Lundi matin) :
  - Vue pays : les 16 pins concentrés dans une bande étroite côté sud-est, juste sous la zone Sud / Abidjan.
  - Toggle « Zoom Abidjan » : caméra MapLibre se centre sur Vridi (zoom 10.4) et les pins se redistribuent sur la bbox Abidjan.
  - Pin MV Atlantic Trader (`mmsi 627012345`) en halo violet pulse.
  - Click pin → ouvre la vignette webcam APM Apapa Gate (auto-select dérivé de `recommended_webcam_source_id`).
  - Le bouton vessel pin reste atteignable au clavier (`<button>` natif, focus ring conservé).

### Garde-fous respectés

- Aucun changement backend.
- Aucune `pointer-events: none` posée sur la carte ; seul le wrapper overlay est `none`, ses enfants `<button>` re-passent en `auto`.
- Couleurs des pins inchangées (palette par `vessel_type` du composant d'origine).
- Aucun ARIA cassé : le bouton porte `[attr.aria-label]="vesselPinTitle(vessel)"`, le toggle a son propre label, l'overlay porte un `role="group" aria-label`.
- Pas d'emoji introduit.

---

## Volet A — QA UI/API prod

### Méthode

`POST /api/v1/auth/login` → JWT, puis appels API authentifiés en `Bearer` + `X-Workspace-Slug: sentinel-ci`. Chat testé via SSE `/api/v1/chat/stream` (réponses captées en `/tmp/chat-*.sse`).

### 1. Cockpit & date

| Cas | Statut | Preuve | Gap |
| --- | --- | --- | --- |
| `date_label` = « Lundi 25 Mai 2026 » | OK | `cockpit.date_label = "Lundi 25 Mai 2026"` | — |
| Status bar chip 0 = « Zone Nord · Tendue », pulse | OK | `vp_status_bar[0]` : `key=zone-nord-tension`, `label=Zone Nord`, `value=Tendue`, `tone=critical`, `pulse=true`, `detail="Centre Drones Napie en retard - cargo Aerostar bloque"` | Pas de champ `id` (clé `key` à la place) — anodin mais à confirmer côté front. |
| Bannière AYA / voice_demo_script cohérent Napié | OK | `voice_demo_script.answer` : « tension Nord remonte au retard du chantier Centre International Formation Drones — Napié (Poro)… composants Aerostar Dynamics bloqués au port d'Abidjan sur cargo MV Atlantic Trader… ». 0 occurrence `Konat*` dans `voice_demo_script`, `aya_recommendation`, `attention_required`, `executive_decision_packages`, `vp_story`. | — |
| 3 KPI macro + sparkline + source | OK | `macro_indicators` retourne GDP / inflation / chômage avec `current`, `series` (12 points), `source`. Le label « N/A · source: — » initialement vu provient du champ `value/spark` legacy null ; le front lit déjà `current/series`. | Si un autre consommateur lit encore `value/spark`, prévoir un fallback. |
| Carte CI affichée | OK | `vp_map_preview.geojson` + zones + projets renvoyés. | Le fix vessels-layer corrige le 2e symptôme visuel séparé. |
| Presse hero priorisée CI | NOK | `press_preview[0..2]` = Mali Kidal, Iran/World Bank, RDC Ebola. Aucun signal CI/Nord/Napié en tête. | **Bloquant trame** : voir bloquant #2. |
| Nav 5 items intacte | OK (indirect) | Routes définies dans `frontend-ng/.../assistant-effects.service.ts` et nav cockpit — pas de régression code. | — |

### 2. Scénario 1 — drill causal Nord

| Prompt | Statut | Preuve | Gap |
| --- | --- | --- | --- |
| « Pourquoi la situation Nord est-elle tendue ? » | OK | SSE : action `aya.explain_why`, `next_focus = proj-drone-centre-napie`, narrative Napié, focus map `zone-nord`. | — |
| « Et pourquoi ce projet est en retard ? » | OK | `next_focus = cargo-abidjan-supply-001`, effet `assistant-show-webcam` émis (chargement vignette APM Apapa). | — |
| « Pourquoi cette cargaison est-elle bloquée ? » | OK | `next_focus = customs-record-non-conformite-2026-05` + proposition « voir PV douanes ». | — |
| « Oui » (PV douanes) | OK | Drawer PV p.2 surlignée renvoyée (citations PV). | — |
| « Oui, prépare la dérogation » | OK | Drawer `customs_derogation` avec citations Abidjan.net + PV. | — |
| Auto-select webcam sur drill cargo | OK | À l'étape cargo, l'effet `assistant-show-webcam` cible bien `apm-apapa-gate-1` (proxy 200). | Effet visuel à reconfirmer en navigateur (le payload SSE est conforme). |

### 3. Brief opérationnel (post nettoyage `chat.py`)

| Prompt | Statut | Preuve | Gap |
| --- | --- | --- | --- |
| « AYA, donne-moi le brief opérationnel pour Projet sensible · Nord avec sources et action recommandée. » | OK | SSE : action `aya.focus_zone_with_project`, narrative Napié, 0 référence Konaté. | — |

### 4. Transition agenda

| Prompt | Statut | Preuve | Gap |
| --- | --- | --- | --- |
| « Quel est mon prochain rendez-vous ? » | PARTIEL | Réponse SSE pointe sur l'event Préfet Nawa **par ID** (`evt-prefet-nawa`), mais le timeline cockpit ne contient pas l'event (voir bloquant #1) → highlight inopérant côté UI. | Bloquant #1. |
| Timeline = 6+2 events 25/26 mai | NOK | `agenda_timeline[0..4]` = Conseil Defense 2026-**04-15** 08:30, Point presse 2026-04-15 11:00, Déjeuner Ambassadeur 2026-04-15 13:00, Revue Sahel 2026-04-15 15:00. `agenda_day.items` = []. | Bloquant #1. |
| `evt-prefet-nawa.context_ref = report-prefet-nawa-2026-05-10` | OK | Vérifié dans `/calendar/events` (event présent, `context_ref` correct). | — |

### 5. Scénario 2 — Préfet Nawa

| Prompt | Statut | Preuve | Gap |
| --- | --- | --- | --- |
| « Résumé du rapport préfet » | OK | Synthèse RAG + proposition cacao retournée. | — |
| « Oui » (3 options sourcées) | OK | 3 options A/B/C avec citations rapport préfet + KB cacao. | — |
| « Génère le rapport complet » | OK | Drawer `rapport_complet` avec `download_url` ; GET sur l'URL → PDF 78 KB, 200 OK. | — |
| « Ajoute le point cacao à l'ordre du jour » | OK | Drawer `calendar_agenda_patch` cible `evt-prefet-nawa` (pas le Conseil). | — |
| « Oui, valide » | OK | PATCH agenda effectif + history visible (`evt-prefet-nawa.agenda_items` updated). | — |
| « Démarre la réunion » | OK | Navigate sur `/meetings/evt-prefet-nawa` (cible correcte). | — |
| « Décide option B » | OK | Décision loggée sur `evt-prefet-nawa` (mutation `meeting.decisions`). | — |
| « Qu'avons-nous décidé la dernière fois ? » | OK | Action `aya.recall_past_decisions` (recall RAG retourne décisions historiques). NB : l'apostrophe typographique fait matcher la phrase ; vérifier que l'UI envoie bien `Qu'avons-nous` avec apostrophe droit ou courbe — les deux marchent. | — |

### 6. Maritime / webcams

| Cas | Statut | Preuve | Gap |
| --- | --- | --- | --- |
| `GET /mission-room/maritime/vessels?bbox=-4.1,5.20,-3.9,5.30` | OK | 16 navires, MV Atlantic Trader en tête (`recommended_webcam_source_id = apm-apapa-gate-1`, `linked_cargo_id = cargo-abidjan-supply-001`, `highlight = aya-target`). | — |
| `GET /mission-room/maritime/vessels/627012345` | OK | Cycle complet renvoyé (3 caméras), `recommended_webcam_source_id = apm-apapa-gate-1`. | — |
| `GET /mission-room/webcams/proxy?source_id=apm-apapa-gate-1` GET | OK | JPEG 53 KB, 200 OK, `content-type: image/jpeg`. | — |
| `GET /mission-room/webcams/proxy?source_id=apm-apapa-gate-1` HEAD | NOK (mineur) | 404. | Voir polish #2. |
| `GET /mission-room/webcams/sources` | OK | 5 sources whitelistées (`apm-apapa-gate-1/2`, `paa-aerial-vue`, `paa-terminal-petrolier`, `paa-terminal-fruitier`). | — |

### 7. Évidences narrative

| Champ | Statut | Note |
| --- | --- | --- |
| `attention_required` (3 items) | OK | `attention-inter-budget`, `attention-zone-nord` (avec mention Napie + cargo bloque), `attention-ambassadeur-france`. |
| `executive_decision_packages` | OK | 3 packages dont Napié × dérogation customs (Konaté absent). |
| `aya_recommendation` | OK | 4 mentions Napié, 0 Konaté. |
| `voice_demo_script` | OK | Prompt Nord + answer Napié end-to-end. |
| `vp_status_bar` | OK | 7 chips, Zone Nord pulse en tête. |

---

## Bloquants démo (top 5)

| # | Sévérité | Item | Cause racine | Effort | Action proposée |
| --- | --- | --- | --- | --- | --- |
| 1 | **✓ RÉSOLU** (commit local `demo/agentic`) | Cockpit `agenda_day.items=[]` et `agenda_timeline` renvoie 15/16 avril au lieu de 25/26 mai 2026. Highlight `evt-prefet-nawa` inopérant en UI. | `_agenda_items_from_calendar(workspace, db)` dans `backend/app/services/mission_room.py` appelait `list_calendar_events(db, workspace)` **sans `start`/`end`** puis prenait `events[:8]`. Les events du 15 avril (déjà passés) triaient en premier. | ~15 min | **FAIT** : `_agenda_items_from_calendar` filtre désormais par `start = demo_date 00:00`, `end = demo_date + 1j 23:59` via `resolve_demo_date(workspace)`. Test couvert par `test_mission_room_cockpit_agenda_uses_demo_date_window`. |
| 2 | **✓ RÉSOLU** (commit local `demo/agentic`) | `press_preview` top 3 = Mali Kidal / Iran World Bank / RDC Ebola. Démo doit prioriser signaux CI/Nord. | Le builder presse cockpit ne pondérait pas par `region_iso = CI` / `tags = ['nord', 'napie', 'aerostar', ...]`. | 30-60 min | **FAIT** : `_press_preview_payload` calcule un boost `+10/+5/+3` (geo CI / tag SENTINEL-CI / publisher CI) et tri descendant. Si aucun article CI dispo → injection du hero Abidjan.net Centre Drones Napié comme fallback. |
| 3 | Élevé | Debug event `agenda QA wiring VIGIE agenda 09:00` présent dans `/calendar/events`. | Seed de test non purgé par `predemo_reset.sh`. | 5 min | Supprimer en BDD : `DELETE FROM calendar_events WHERE summary ILIKE '%QA wiring%';` ou ajouter au script reset. |
| 4 | Moyen | `vp_status_bar[i].id` absent (champ `key` à la place). | API renvoie `key`, front consomme déjà `key` mais l'analytics côté demo log peut chercher `id`. | 5 min | Soit dupliquer `id = key`, soit confirmer côté front que `key` suffit. À vérifier dans `vp-status-bar.component.ts`. |
| 5 | Moyen | `/mission-room/webcams/proxy` ne répond pas à `HEAD` (404). | Endpoint déclaré en `GET` uniquement. | 10 min | Ajouter `@router.head(...)` qui renvoie 200 + headers sans body, ou retirer les pré-flight HEAD du front (vignettes auto). |

## Polishs rapides (top 5)

| # | Item | Effort | Justification |
| --- | --- | --- | --- |
| 1 | Endpoint `/calendar/events` : appliquer `date_from` / `date_to`. Actuellement les paramètres semblent ignorés (renvoie les 16 events quelle que soit la fenêtre). | 15 min | Évite des payloads inutiles côté UI et nettoie l'API publique. |
| 2 | Smoke visuel manuel de l'overlay vessels (Lundi matin 30 min avant démo) : vue pays, toggle Abidjan, click MV Atlantic Trader, halo violet. | 5 min | Le tsc est vert mais aucun navigateur n'a validé le rendu après refactor. |
| 3 | Ajouter un `aria-pressed` sur le toggle « Zoom Abidjan / Vue pays » de l'overlay vessels. | 5 min | Conformité WCAG AA — le bouton change d'état. |
| 4 | `voice_demo_script.prompt` est neutre (« situation Nord ») ; envisager une variante 25 mai « Pourquoi la tension Nord ce matin ? » pour matcher l'intro Vice Premier Ministre. | 10 min | Renforce l'effet « le Vice Premier Ministre arrive au cockpit ». |
| 5 | Vérifier que les 5 sources webcam apparaissent dans le `assistant-effects` côté front (drop-down sélecteur manuel) — actuellement on n'a confirmé que l'auto-select. | 10 min | Sécurise le fallback démo si une webcam tombe. |

---

## Vérifications post-deploy spécifiques

- **Chip Zone Nord présente, en première position, pulse** : OK (`vp_status_bar[0]`, voir tableau 1).
- **`Konaté` absent des réponses** : OK. 0 occurrence dans `vp_story`, `attention_required`, `voice_demo_script`, `directive_of_day`, `aya_recommendation`, `priorities`, `executive_decision_packages`, `situation_monitor`, `demo_narrative`. (1 occurrence résiduelle dans `cockpit.messages[*].author` pour un message historique — auteur, pas narrative — toléré.)
- **`date_label` correct** : OK (`Lundi 25 Mai 2026`).
- **Agenda à jour** : NOK. Bloquant #1. La BDD contient bien les 6+2 events 25/26 mai 2026 (validé via `/calendar/events`), mais le cockpit ne les sélectionne pas.
- **PDFs accessibles** : OK pour le rapport préfet Nawa généré via S2 (78 KB, 200 OK).
- **Statut des 3 commits** :
  - `fe2f05d6` (bloquants démo) → présent sur `demo/agentic`, déployé.
  - `6d7f89ad` (chat.py + Napié) → présent, déployé.
  - `bf0779cc` (webcams + AIS + auto-select) → présent, déployé (`/maritime/vessels`, `/webcams/proxy`, `/webcams/sources` répondent).
  - `702f0401` (fix typing webcam cycle) → présent, déployé.
  - **Nouveau** : `11745daf` (fix vessels-layer overlay) → **commit local sur `demo/agentic`, pas pushé** (par garde-fou).

---

## Confirmation finale Napié vs Konaté

| Champ cockpit | Mentions Napié | Mentions Konaté |
| --- | --- | --- |
| `vp_story` | 10 | 0 |
| `attention_required` | 3 | 0 |
| `voice_demo_script` | 1 | 0 |
| `aya_recommendation` | 4 | 0 |
| `executive_decision_packages` | 3 | 0 |
| `directive_of_day` | 0 | 0 |
| `priorities` | 0 | 0 |
| `situation_monitor` | 0 | 0 |

Action manifest `aya.focus_zone_with_project` (`registry.py`) renvoie bien la narrative Napié, ce qui valide le nettoyage des shortcuts hardcodés de `chat.py` (commit `6d7f89ad`).

---

## Reste-à-faire avant lundi matin (estimation effort)

| Priorité | Tâche | Effort | Owner suggéré |
| --- | --- | --- | --- |
| ✓ P0 | Fix `_agenda_items_from_calendar` (bloquant #1) — commit local `demo/agentic` | 15 min | Backend |
| ✓ P0 | Re-rank `press_preview` CI-first (bloquant #2) — commit local `demo/agentic` | 30-60 min | Backend |
| ✓ P0 | Reconnaissance « AYA » + normalisation préfixe (nouveau) — commit local `demo/agentic` | 30 min | Backend |
| ✓ P0 | Vessels overlay devient layer toggleable dans la légende (nouveau) — commit local `demo/agentic` | 30 min | Frontend |
| ✓ P0 | Top 5 phrases résolveur (anglicismes, ultra-courts, tie-breaker, oral) — commit local `demo/agentic` | 30 min | Backend |
| P0 | Purger event debug `QA wiring` (bloquant #3) | 5 min | Ops/BDD |
| P0 | Push commit `11745daf` + nouveaux commits `demo/agentic` et re-déployer le front | 10 min | Frontend |
| P1 | Smoke visuel navigateur post-deploy (vessels overlay + toggle layer + halo MV Atlantic Trader + auto-select webcam) | 15 min | QA |
| P1 | `vp_status_bar.id` ou confirmation `key` consommé partout (bloquant #4) | 5 min | Frontend |
| P1 | `HEAD /webcams/proxy` 200 (bloquant #5) | 10 min | Backend |
| P2 | `aria-pressed` toggle overlay (polish #3) | 5 min | Frontend |
| P2 | `/calendar/events` honorer `date_from`/`date_to` (polish #1) | 15 min | Backend |
| P2 | Variante `voice_demo_script.prompt` matin (polish #4) | 10 min | Backend |

**P0 résolus en local sur `demo/agentic`. Reste à pousser puis re-déployer.**

---

## Annexes

### Commit de Volet B

```
11745daf Render vessels overlay on top of the cockpit Côte d'Ivoire map
```

Fichiers touchés :
- `frontend-ng/src/app/features/mission-room/vp-map-preview.component.ts`
- `frontend-ng/src/app/features/mission-room/workspace-map.component.ts`

### Endpoints testés (extrait)

- `POST /api/v1/auth/login` → 200, JWT obtenu (workspace `sentinel-ci`).
- `GET /api/v1/mission-room/cockpit` → 200, payload complet.
- `GET /api/v1/mission-room/macro-indicators` → 200, 3 indicateurs `current/series`.
- `GET /api/v1/calendar/events` → 200, 16 events incl. 6 du 25/05 + 2 du 26/05.
- `GET /api/v1/mission-room/maritime/vessels` → 200, 16 vessels.
- `GET /api/v1/mission-room/maritime/vessels/627012345` → 200, cycle webcam.
- `GET /api/v1/mission-room/webcams/proxy?source_id=apm-apapa-gate-1` → 200, image/jpeg 53 KB.
- `GET /api/v1/mission-room/webcams/sources` → 200, 5 sources.
- `POST /api/v1/chat/stream` (SSE) → multi-prompt scenario S1 + S2 + transition + recall : tous les actions ciblées émises.

### Notes méthode

- Pas de browser MCP utilisé (l'agent n'a pas Playwright accessible). Le rendu visuel post-fix vessels n'est validé que par le tsc + lecture du DOM ; smoke visuel à programmer Lundi matin (polish P1).
- Pas de push remote (garde-fou respecté). Le re-déploiement reste à la main de l'équipe.

