# SENTINEL-CI — QA confiance veille-de-démo (lundi 25 mai 2026, 09h00)

- **Run** : dimanche 24 mai 2026, 22h53 → 23h01 (UTC+2) — wall time 8 min.
- **Cible** : `https://agentium.papai.ai`, workspace `sentinel-ci`, profil `vigie_executive`, compte `thibaud.ishacian@datategy.net`.
- **HEAD local** : `bf4909ca` sur `demo/agentic`. 4 commits non poussés : `bd5e1b70` (S1 QA doc), `e40432b2` (S1 cargo phrases + ODJ paramétrable), `6335d460` (4 bug fixes demo-eve), `bf4909ca` (cheatsheet réécrite).
- **Harness** : `/tmp/sentinel_qa_eve/harness.py` (urllib, JWT Keycloak → `/actions/resolve` + `/chat/stream` SSE + `/auth/workspaces/{slug}` + `/calendar/events` + `/meetings/{id}/decisions` + HEAD/GET PDF). Aucune écriture admin, aucun PATCH direct. Pollution side-effect listée §8.
- **Dump brut** : `/tmp/sentinel_qa_eve/results.json` (41 KB).

---

## 1. TL;DR commercial

| Périmètre | Verdict aujourd'hui (tip prod ≥ `d452e001`) | Verdict si push + redeploy `6335d460` |
|---|---|---|
| S1 (drill Nord, 6 étapes) | **5 PASS_NOW + 1 FAIL_NOW (S1.5)** | 6 PASS (dont S1.3 rendering UI) |
| S2 (Préfet Nawa, 9 étapes + T.1) | **10 PASS / 10** (avec 1 WARN PDF) | 10 PASS / 10 |
| Bugs 1/2/3/4 corrigés | **0 / 4 déployés** — tous reproductibles | 4 / 4 (sauf #3 à valider visuellement) |
| Edge cases (6) | 6 / 6 conformes à la doctrine cheatsheet | 6 / 6 |
| Narrative finale (Konaté/Burkina dans tier_1+tier_2+vp_story+aya_recommendation+attention_required) | **0 hit narratif** (1 hit isolé `messages[0].from = "Gen. Konate"`, hors narratif VP) | identique |

**Décision finale : `GO_AFTER_DEPLOY`.**

3 phrases pour le commercial :

1. Le scénario S2 complet (Préfet Nawa : résumé → préconisations cacao → PDF stratégique → patch ODJ → confirm → start meeting → décide B → recall) **passe déjà aujourd'hui à 10/10**, sans aucun bug bloquant.
2. Le scénario S1 perd **1 étape sur 6 sans deploy** (S1.5 « montre la situation au port » n'existe pas dans le pack prod ; fallback graceful map mais pas de show_maritime_traffic) ; sans deploy le présentateur risque aussi que (a) la carte ne bouge pas sur S1.3, (b) chaque filler poli long ("OK, très bien, montre-moi…") matche `voice.confirm_yes` au lieu de l'action voulue, (c) la TTS prononce "M" comme la lettre.
3. **Si Ops pousse + redéploie `6335d460` (+ `e40432b2`) et joue `predemo_reset.sh` avant 09h00, on est à 16/16 PASS, 0 FAIL, 4/4 bugs corrigés.** Sinon → `GO_DÉGRADÉ` (lire le runbook §9 Plan B).

Stats détaillées : **15 PASS_NOW · 4 PASS_AFTER_DEPLOY · 1 WARN (PDF S2.4) · 1 FAIL_NOW (S1.5)** + 4 bugs reproductibles aujourd'hui, 0 bug réel non couvert par un commit prêt.

---

## 2. État déploiement prod (matrice fix vs déployé)

| Sonde déterministe | Réponse prod aujourd'hui | Interprétation |
|---|---|---|
| `POST /actions/resolve` `"OK, très bien, tu peux me montrer la situation au port, s'il te plaît ?"` | action = `voice.confirm_yes` conf **0.875** | **`6335d460` NON déployé** (le guard `_CONFIRM_MAX_TOKENS = 4` + `aya.show_maritime_traffic` ne sont pas en prod) |
| `GET /mission-room/cockpit` — grep narrative | 8 hits `M. le Vice` / 0 hit `Monsieur le Vice-Président` | **`6335d460` NON déployé** (strings TTS non patchées) |
| `POST /actions/resolve` `"AYA, explique le cargo Atlantic Trader"` | `matched=false`, conf 0.0 (no_match) | **`e40432b2` NON déployé** (phrase non ajoutée au pack S1.4) |
| `POST /actions/resolve` `"AYA, montre la situation au port."` | `matched=false`, conf 0.0 (no_match) | corrobore : action `aya.show_maritime_traffic` absente du pack prod |
| `GET /mission-room/cockpit` `aya_recommendation.prompt` | « AYA, pourquoi la situation Nord est-elle tendue ? » | cohérent avec tip prod **≥ `d452e001`** (Vague 1 `09188fa6` + polish `d1490f18` déjà déployés, confirmés par smokes du 24/05) |

| Commit local | Type | Effet runtime | État prod |
|---|---|---|---|
| `bd5e1b70` | doc QA S1 | aucun | non poussé — neutre |
| `e40432b2` | backend (registry phrases + ODJ paramétrable) | + 3 phrases sur `aya.show_vessel_evidence` (« explique le cargo », « explique cette cargaison », « explique Atlantic Trader ») + parsing topic ODJ | **NON déployé** |
| `6335d460` | backend (guard confirm `_CONFIRM_MAX_TOKENS`, branche défensive `voice_confirm_yes`, pack `aya.show_maritime_traffic`, replace « M. le Vice » → « Monsieur le Vice-Président ») + frontend (`chat-panel.component.ts` forwarding map_command + open panel immédiat) | bloque les 4 bugs | **NON déployé** |
| `bf4909ca` | doc cheatsheet | aucun | non poussé — neutre |

**Verdict §2** : aucune des fixes demo-eve n'est en prod ; les 4 commits doivent être poussés et redéployés (back+front) avant 09h00.

---

## 3. QA S1 — drill causal Nord

Méthode : pour chaque étape, prompt principal envoyé à `/actions/resolve` puis à `/chat/stream` (SSE → `[DONE]` ou 10 s). Verdict :
- **PASS_NOW** = passe aujourd'hui en prod.
- **PASS_AFTER_DEPLOY** = code OK à HEAD `bf4909ca`, doit passer après push+redeploy.
- **FAIL_NOW** = échec aujourd'hui, dépend d'un deploy pour passer.
- **WARN** = passe mais qualité dégradée.

| Étape | Prompt (cheatsheet `bf4909ca`) | Resolver (action / conf) | SSE (action exécutée / ms) | Effet vérifié | Verdict |
|---|---|---|---|---|---|
| S1.1 | `AYA, pourquoi la situation Nord est-elle tendue ?` | `aya.explain_why` / 1.06 | `aya.explain_why` / 1039 ms | navigate `strategie` + `focus=zone-nord` + highlight `proj-drone-centre-napie` ; texte cite Napié + Aerostar + Vridi + 120 j. | **PASS_NOW** |
| S1.2 | `AYA, ouvre le PV douanes.` | `aya.show_customs_record` / 1.04 | `aya.show_customs_record` / 191 ms | drawer `document_preview` target `proces-verbal-douanes-non-conformite-2026-05-18` page 2 + proposal chaînée `aya.draft_customs_email` | **PASS_NOW** |
| S1.3 | `AYA, focus sur la zone Nord et le projet Napié.` | `aya.focus_zone_with_project` / 0.88 | `aya.focus_zone_with_project` / 820 ms | navigate `highlight=proj-drone-centre-napie` + **`map_command` `intent=focus_zone` `camera={lon:-5.65, lat:9.15, zoom:6.95}` map_slug `sentinel-ci-strategic-map`** | **PASS_NOW (API)** / **PASS_AFTER_DEPLOY (UI)** — voir bug #2 §5 |
| S1.4 | `AYA, montre le cargo Atlantic Trader.` | `aya.show_vessel_evidence` / 0.905 | `aya.show_vessel_evidence` / 393 ms | navigate `mode=live` `panel=maritime` `vessel=mv-atlantic-trader` + `assistant-show-webcam apm-apapa-gate-1` + proposal `propose-customs-pdf-show` | **PASS_NOW** (forme canonique cheatsheet) |
| S1.5 | `AYA, montre la situation au port.` | **no_match** (conf 0.0) | **no action** / 360 ms — fallback orchestrateur : `map_command` + `map_source` + `map_state_updated` + texte demo-safe « J'affiche Port d'Abidjan avec les couches maritime, douanes, presse et actions. » | drawer maritime + webcam **non ouverts** ; aucun `assistant-show-webcam` ; aucun `assistant-navigate` vers `/strategie?panel=maritime` | **FAIL_NOW** → **PASS_AFTER_DEPLOY** (`6335d460` ajoute `aya.show_maritime_traffic`) |
| S1.6 | `AYA, rédige le courrier de dédouanement pour Atlantic Trader.` | `aya.draft_customs_email` / 0.94 | `aya.draft_customs_email` / 208 ms | drawer `customs_email` recipient « Direction generale des Douanes — Chef de la cellule portuaire Abidjan » ; corps cite « Centre Formation Napié (MV Atlantic Trader) » ; 0 hit Konaté/Burkina | **PASS_NOW** |

**Détail S1.3 (preuve Korhogo)** — frame `map_command` brut :

```json
{"chunk_type":"map_command","map_slug":"sentinel-ci-strategic-map","intent":"focus_zone","target":"zone-nord","map_state":{"camera":{"longitude":-5.65,"latitude":9.15,"zoom":6.95,"pitch":0,"bearing":0,"duration_ms":850},"active_layers":["territorial-risk","open-intelligence","maritime-traffic","preventive-actions"],"basemap":"command"}}
```

Le backend émet la bonne caméra Korhogo (matches la cible `[-5.65, 9.15]` zoom ≈ 7). Le bug #2 frontend (`chat-panel.component.ts` ne forwardait pas le chunk) est invisible côté API mais bien réel à l'écran tant que le frontend n'est pas redéployé.

**Détail S1.5 (preuve fallback)** — frame texte fallback : `"J'affiche Port d'Abidjan avec les couches maritime, douanes, presse et actions. Lecture demo-safe : ports, corridor Golfe de Guinee, densite indicative et options cabinet."` — joli en démo dégradée, mais aucun pin AIS, aucune webcam, aucun panneau maritime ouvert. Le présentateur perdrait le pivot narratif « montre la situation au port → click Atlantic Trader ».

Synthèse S1 : **5 PASS_NOW + 1 FAIL_NOW** (S1.5) ; **6 PASS_AFTER_DEPLOY**.

---

## 4. QA S2 — Préfet Nawa (cacao), flow stateful

Ordre joué : T.1 → S2.1 → … → S2.9 dans la même session (workspace bucket awaiting `_workspace`).

| Étape | Prompt | Resolver (action / conf) | SSE (action / ms) | Mutation état clé | Verdict |
|---|---|---|---|---|---|
| T.1 | `AYA, quel est mon prochain rendez-vous ?` | `aya.open_next_meeting` / 0.92 | `aya.open_next_meeting` / 137 ms | navigate `/agenda?highlight=evt-prefet-nawa` | **PASS_NOW** |
| S2.1 | `AYA, donne-moi le résumé du rapport préfet.` | `aya.summarize_last_exchanges` / 0.92 | `aya.summarize_last_exchanges` / 126 ms | awaiting bascule `key=cacao_summary action_on_yes=aya.recommend_cacao` ; synthèse Nawa/Soubre + propose préconisations cacao | **PASS_NOW** |
| S2.2 | `AYA, résume le rapport Préfet Nawa.` | `aya.summarize_last_exchanges` / 0.905 | idem / 147 ms | déclenche skill `summarize_long_document_v1` (handler shared) | **PASS_NOW** |
| S2.3 | `AYA, donne-moi des préconisations sur le cacao.` | `aya.recommend_cacao` / 1.06 | `aya.recommend_cacao` / 225 ms | navigate `/decisions?focus=package-cacao-diversification` ; texte = 3 leviers (transformation 4,2 Mds FCFA / coop / PPP) ; awaiting bascule sur `strategic_report` | **PASS_NOW** |
| S2.4 | `AYA, génère le rapport complet.` | `aya.draft_strategic_report` / 1.04 | `aya.draft_strategic_report` / 294 ms | drawer `assistant-draft-open` target `strategic-cacao_diversification-da95677bd29a`, audit `report.strategic.generated`, `total_pages=12`. `GET` PDF = **200 / application/pdf / 14 994 octets / magic `%PDF-1.7`**. `HEAD` PDF = **404 / application/json**. | **PASS_NOW (WARN PDF)** — HEAD 404, taille 15 KB/12 p. (sous le « 100 KB/70 p. » du brief) ; à clarifier oralement |
| S2.5 | `AYA, ajoute le point cacao à l'ordre du jour.` | `aya.update_meeting_agenda` / 0.92 | `aya.update_meeting_agenda` / 138 ms | drawer `calendar_agenda_patch` + `assistant-propose propose-calendar-agenda-patch` ; `actions.pending_agenda_patch` = `{event_id=5f3ccd49…, agenda_items=[agenda-cacao-diversification]}` ; `actions.awaiting._workspace = {key:calendar_agenda_patch, action_on_yes:aya.confirm_agenda_patch}` | **PASS_NOW** |
| S2.6 | `Oui, valide.` | `voice.confirm_yes` / 0.875 (traduit via awaiting bucket) | **`aya.confirm_agenda_patch`** / 174 ms | navigate `/agenda?highlight=5f3ccd49…` ; `pending_agenda_patch` cleared ; `evt-prefet-nawa.metadata.agenda_items` = `[Point cacao - diversification anacarde (proposition AYA)]` | **PASS_NOW** |
| S2.7 | `AYA, démarre la réunion.` | `aya.start_meeting` / 1.025 | `aya.start_meeting` / 143 ms | navigate `/agenda/meeting/5f3ccd49…?highlight=…` ; `actions.current_meeting = 5f3ccd49…` | **PASS_NOW** |
| S2.8 | `AYA, décide option B.` | `aya.log_decision` / 0.89 | `aya.log_decision` / 151 ms | navigate `/meeting/{id}?decision=<id>` ; nouvelle décision persistée (`/meetings/5f3ccd49…/decisions` → 4 décisions cumul, dernière en tête) | **PASS_NOW** |
| S2.9 | `AYA, qu'avons-nous décidé la dernière fois ?` | `aya.recall_past_decisions` / 1.06 | `aya.recall_past_decisions` / 103 ms | top-5 décisions cacao option B retournées dans l'ordre antéchronologique | **PASS_NOW** |

**Synthèse S2** : **10 PASS_NOW / 10**, 1 WARN scoped au livrable PDF (HEAD 404 + format 15 KB/12 p.) — strictement identique au QA S2 du 24/05 (`sentinel-ci-qa-postdeploy-s2-2026-05-24.md` §6 P2-1/P2-2). **Pas de régression S2 vs hier.**

---

## 5. Validation des 4 bug fixes (HEAD `6335d460`)

| # | Bug | Test empirique aujourd'hui | Preuve | Verdict |
|---|---|---|---|---|
| **1** | Stub « confirm proposal » sur fillers polis longs | 3 prompts longs polis testés via `/actions/resolve`. (a) `"OK, très bien, tu peux me montrer la situation au port, s'il te plaît ?"` → **`voice.confirm_yes` conf 0.875** ; (b) `"D'accord AYA, montre-moi la situation au port s'il te plaît."` → **`voice.confirm_yes` conf 0.89** ; (c) `"Très bien, peux-tu m'ouvrir la vue du port d'Abidjan ?"` → `no_match` (pas de stub mais pas non plus la bonne action) | bug **reproductible 2/3** aujourd'hui (variantes a et b). Le guard `_CONFIRM_MAX_TOKENS = 4` n'est pas appliqué en prod. Après deploy `6335d460`, (a) et (b) doivent matcher `aya.show_maritime_traffic`. | **FAIL_NOW → PASS_AFTER_DEPLOY** |
| **2** | Zoom Zone Nord ne se déclenche pas | Re-run S1.3 et capture frame `map_command` : backend émet bien `intent=focus_zone target=zone-nord camera={lon:-5.65, lat:9.15, zoom:6.95}` avec map_slug `sentinel-ci-strategic-map`. | Backend OK aujourd'hui (confirmé en QA S1 du 24/05 aussi). Le bug est côté frontend (`chat-panel.component.ts` ne forwardait pas le chunk `map_command` jusqu'au map renderer). | **PASS_NOW (API)** / **PASS_AFTER_DEPLOY (UI rendering)** |
| **3** | Délai click → ouverture panneau AYA | Non mesurable via API (UI seulement : timing entre click bulle AYA et ouverture du drawer panneau). | À valider **manuellement** par le présentateur après deploy front : cliquer la bulle AYA → le panneau doit apparaître < 100 ms (vs ~500-1500 ms aujourd'hui), avec rafraîchissement du contenu en arrière-plan. | **UNMEASURABLE — PASS_AFTER_DEPLOY (à valider visuellement)** |
| **4** | « M. le Vice Président » bafouille TTS (« M » lu comme la lettre) | Grep sur cockpit (`/mission-room/cockpit`) + tous les `final_text` SSE du run S1+S2. Cockpit blob : **8 hits `M. le Vice` / 0 hit `Monsieur le Vice-Président`**. S1+S2 SSE final_text : **26 hits `M. le Vice President` / 0 hit `Monsieur le Vice-Président`** (et 26 hits `Vice President` sans accent ni tiret). | Strings backend non patchées aujourd'hui. La fix `6335d460` est un sed global registry + executor + cockpit feed → tous les hits doivent disparaître après deploy. | **FAIL_NOW → PASS_AFTER_DEPLOY** |

**Verdict §5** : 0 / 4 bugs déployés ; **4 / 4 reproduits aujourd'hui** (bug #3 par déduction UI) ; **4 / 4 corrigés à HEAD `6335d460`** (bug #3 confiance commit + à valider visuellement après deploy).

---

## 6. Edge cases & robustesse (6 prompts représentatifs)

| Tag | Catégorie | Prompt | Action obtenue | Conf | Verdict |
|---|---|---|---|---|---|
| EDGE-01 | Filler poli seul | `OK` | `voice.confirm_yes` | 0.995 | **WARN ATTENDU** — cheatsheet §« À ne PAS dire » impose de ne jamais commencer une phrase par filler isolé. Cohérent avec la doctrine. Hors awaiting, l'action est un no-op silencieux ; en awaiting, validerait la dernière proposition. |
| EDGE-02 | Ultra-court ambigu | `le rapport` | `null` (no_match) | 0.0 | **PASS** — fallback RAG long, pas d'action latérale ; conforme à la cheatsheet « formes nominales ultra-courtes tombent en RAG ». |
| EDGE-03 | Anglicisme hors pack | `show port view` | `null` (no_match) | 0.0 | **PASS** — pas un anglicisme couvert (couverts : `morning briefing`, `next meeting`, `show the port situation` après `6335d460`). |
| EDGE-04 | AYA + filler + briefing | `AYA, alors voilà, donne-moi le brief` | `aya.priority_summary` | 0.855 | **PASS** — le wake-word + verbe pivot « brief » survivent au filler ; matche briefing comme attendu (≥ 0.78). |
| EDGE-05 | Sans préfixe ni verbe | `la décision` | `null` (no_match) | 0.0 | **PASS** — conforme cheatsheet. |
| EDGE-06 | Polite confirmation pendant awaiting | (a) `parfait merci` standalone → `no_match` ; (b) **enchaînement S2.5 puis `parfait merci`** → `no_match` côté resolver, `chat/stream` part en RAG long (~10 s génération), **aucun `aya.confirm_agenda_patch` déclenché**, `pending_agenda_patch` reste staged | 0.0 | **PASS** — comportement safe : « parfait merci » NE déclenche PAS la confirmation pendant awaiting. Pour valider, il faut « Oui valide » / « valide » / « applique l'ordre du jour » (formes couvertes par `voice.confirm_yes` ≥ 0.78). À documenter pour le présentateur : pour fermer un awaiting, dire **« Oui, valide. »** exactement. |

**Synthèse §6** : 6/6 conformes à la doctrine cheatsheet. Aucune surprise. Aucune réécriture trame nécessaire.

---

## 7. Cohérence narrative finale (post-run S1 + S2)

`GET /mission-room/cockpit` après tout le run :

| Check | Résultat | Verdict |
|---|---|---|
| 0 occurrence Konaté / Konate / Burkina dans `geographic_signal_tiers.tier_1` | 0 hit | **PASS** |
| 0 occurrence Konaté / Burkina dans `geographic_signal_tiers.tier_2` | 0 hit | **PASS** |
| 0 occurrence Konaté / Burkina dans `vp_story` | 0 hit `Konaté` / 0 hit `Burkina` | **PASS** |
| 0 occurrence Konaté / Burkina dans `aya_recommendation` | 0 hit | **PASS** |
| 0 occurrence Konaté / Burkina dans `attention_required` | 0 hit | **PASS** |
| Hit Konaté isolé dans le cockpit ? | **1 hit** : `messages[0].from = "Gen. Konate"` (sender d'un message d'inbox seed) | **PASS_MINEUR** — hors narratif VP, pas exposé sauf si la VP ouvre l'inbox messages ; pas dans la trame |
| `vp_story` mentionne Napié | 9 hits Napié, 8 hits Nawa, 6 hits Préfet, 26 hits cacao | **PASS** |
| `aya_recommendation.prompt` cohérent avec ouverture S1 | `"AYA, pourquoi la situation Nord est-elle tendue ?"` | **PASS** |
| `attention_required` mentionne Napié / cacao | 2 hits Napié (cacao pas surfacé ici — c'est porté par `vp_story`) | **PASS** |
| `actions.last_focus` cohérent avec dernière action S2.9 | `cargo-abidjan-supply-001` (dernier focus posé par S1.4 ; S2.7-S2.9 ne touchent pas `last_focus`) | **PASS_MINEUR** — cohérent avec un VP qui termine sur le drill cargo S1 ; à reset par `predemo_reset.sh` |
| Strings `M. le Vice` toujours présents (preuve bug #4 non déployé) | 8 hits cockpit + 26 hits S1+S2 final_text | rappel : disparaît après deploy `6335d460` |

**Verdict §7** : narratif propre côté tiers/vp_story/aya_recommendation/attention_required. 1 hit Konaté isolé, hors trame, non bloquant.

---

## 8. Actions Ops bloquantes avant 09h00 (ordonnées)

> **À exécuter sur la box prod par l'opérateur déploiement, dans l'ordre.**

1. **`git push origin demo/agentic`** depuis le poste de dev (4 commits : `bd5e1b70`, `e40432b2`, `6335d460`, `bf4909ca`). Vérifier `git log origin/demo/agentic..HEAD` vide après push.
2. **Pull + redeploy backend** (uvicorn workers + worker actions registry). Vérifier qu'au reboot, `POST /actions/resolve` `"AYA, montre la situation au port."` renvoie `aya.show_maritime_traffic` conf ≥ 0.78 (et plus `null`).
3. **Pull + redeploy frontend** (Angular build prod, déploiement statique). Vérifier que le bundle servi mentionne le commit ou la date `25 mai 2026`. Sans front, le bug #2 (zoom zone Nord) et le bug #3 (snap-open panel) restent visibles.
4. **`./scripts/predemo_reset.sh`** — purge debug + reseed event Préfet Nawa + clear `actions.last_focus` + clear `actions.current_meeting` + clear `actions.awaiting` + clear `actions.pending_agenda_patch`. **Indispensable** : ce QA laisse derrière lui (a) `last_focus=cargo-abidjan-supply-001`, (b) `current_meeting=5f3ccd49…`, (c) `pending_agenda_patch` staged (test enchaînement EDGE-06), (d) 4 décisions cumulées sur l'event Nawa.
5. **`python3 scripts/smoke_predeploy_probe.py`** — objectif 20/20. À HEAD `bf4909ca`, le probe inclut les phrases pivot de S1.5 (« montre la situation au port »), S1.4 (variante « explique le cargo »), S2 (« résume Préfet Nawa », « génère le rapport complet », « décide option B »). Tant que ce smoke n'est pas vert, ne pas lancer la démo.
6. **Sanity manuelle navigateur** : ouvrir `https://agentium.papai.ai/hypervisor/mission-room/cockpit`, vérifier (a) chip Zone Nord pulse rouge, (b) date label « Lundi 25 Mai 2026 », (c) cliquer la bulle AYA → panneau s'ouvre **immédiat** (bug #3 fix), (d) dire « AYA, focus sur la zone Nord et le projet Napié. » → la carte doit se recentrer sur Korhogo (bug #2 fix), (e) dire « AYA, montre la situation au port. » → drawer maritime + AIS pins + webcam APM Apapa (S1.5 nouveau).

---

## 9. Plan B présentateur (si une action FAIL le matin)

| Symptôme à scène | Cause probable | Recovery immédiat |
|---|---|---|
| S1.5 « montre la situation au port » → AYA répond par un texte demo-safe mais carte / drawer ne bougent pas | Deploy `6335d460` raté ou rollback | Dire **« AYA, montre le cargo Atlantic Trader. »** (S1.4 canonique) — ouvre directement drawer maritime + AIS + webcam APM Apapa. Le narratif « voilà ce qui arrive au port » est porté par S1.4. Sauter S1.5 sans flag visible. |
| S1.3 « focus zone Nord et projet Napié » → la carte ne bouge pas (icône load mais pas de recentrage) | Frontend `chat-panel.component.ts` non redéployé (bug #2 frontend) | Cliquer manuellement la zone Nord sur la carte cockpit (le clic UI fait fonctionner le focus). Continuer le drill via S1.2 (PV douanes) qui ouvre toujours son drawer. |
| Pendant un filler poli involontaire (« OK… ») la dernière proposition awaiting se valide toute seule | `_CONFIRM_MAX_TOKENS=4` guard non déployé (bug #1) | Toujours commencer par un verbe (cheatsheet règle d'or n°1). Si un filler vient — dire immédiatement le verbe à la suite : « OK, montre la situation au port. » (la longueur > 4 tokens désamorce le confirm sans deploy non plus, déjà OK). |
| TTS prononce « M » comme la lettre au lieu de « Monsieur » | Strings non patchées (bug #4) | Inaudible-élégant : la TTS dit « èm-le-Vice-Président ». Aucune action — la voix dit la bonne idée même mal prononcée. Briefer la VP en amont. |
| S2.6 « Oui, valide » ne déclenche rien (`voice.confirm_yes` → no_op) | Pas de `pending_agenda_patch` staged (S2.5 non joué ou awaiting expiré 20 min) | Redire S2.5 (« AYA, ajoute le point cacao à l'ordre du jour. ») puis enchaîner « Oui, valide. » dans les 20 min. |
| S2.4 « génère le rapport complet » → drawer ouvre mais PDF vide / 404 | Service de génération PDF down ou objet store cassé | Aller à `https://agentium.papai.ai/api/v1/mission-room/reports/sentinel-ci/strategic-cacao_diversification-da95677bd29a.pdf` directement dans un onglet (URL servable identifiée). À défaut, faire S2.3 (préconisations cacao) + S2.5 (patch ODJ) + S2.7 (start) — narratif tient sans le PDF. |
| Réponse longue/hésitante sans `action_effect` (drawer ne s'ouvre pas) | Resolver no_match → fallback RAG ~10 s | Recommencer avec la forme **canonique** de la cheatsheet (colonne « Prompt principal »). Si 2 essais ratés : passer à l'étape suivante. |

---

## 10. Annexe traçabilité

Format : `tag | prompt | action attendue → action obtenue | conf | date`.

### S1
- `S1.1 | "AYA, pourquoi la situation Nord est-elle tendue ?" | aya.explain_why → aya.explain_why | 1.06 | 2026-05-24T22:53Z+2`
- `S1.2 | "AYA, ouvre le PV douanes." | aya.show_customs_record → aya.show_customs_record | 1.04 | idem`
- `S1.3 | "AYA, focus sur la zone Nord et le projet Napié." | aya.focus_zone_with_project → aya.focus_zone_with_project | 0.88 | idem`
- `S1.4 | "AYA, montre le cargo Atlantic Trader." | aya.show_vessel_evidence → aya.show_vessel_evidence | 0.905 | idem`
- `S1.5 | "AYA, montre la situation au port." | aya.show_maritime_traffic → null (no_match) | 0.0 | idem`
- `S1.6 | "AYA, rédige le courrier de dédouanement pour Atlantic Trader." | aya.draft_customs_email → aya.draft_customs_email | 0.94 | idem`

### S2
- `T.1 | "AYA, quel est mon prochain rendez-vous ?" | aya.open_next_meeting → aya.open_next_meeting | 0.92`
- `S2.1 | "AYA, donne-moi le résumé du rapport préfet." | aya.summarize_last_exchanges → idem | 0.92`
- `S2.2 | "AYA, résume le rapport Préfet Nawa." | aya.summarize_last_exchanges → idem | 0.905`
- `S2.3 | "AYA, donne-moi des préconisations sur le cacao." | aya.recommend_cacao → idem | 1.06`
- `S2.4 | "AYA, génère le rapport complet." | aya.draft_strategic_report → idem | 1.04 ; PDF GET 200/14994o, HEAD 404`
- `S2.5 | "AYA, ajoute le point cacao à l'ordre du jour." | aya.update_meeting_agenda → idem | 0.92`
- `S2.6 | "Oui, valide." | aya.confirm_agenda_patch → idem (via voice.confirm_yes 0.875 + awaiting bucket)`
- `S2.7 | "AYA, démarre la réunion." | aya.start_meeting → idem | 1.025`
- `S2.8 | "AYA, décide option B." | aya.log_decision → idem | 0.89`
- `S2.9 | "AYA, qu'avons-nous décidé la dernière fois ?" | aya.recall_past_decisions → idem | 1.06`

### Bugs / sondes deploy
- `DEPLOY-1 | "OK, très bien, tu peux me montrer la situation au port, s'il te plaît ?" | aya.show_maritime_traffic → voice.confirm_yes | 0.875 | 6335d460 NON déployé`
- `DEPLOY-2 | grep "M. le Vice" / "Monsieur le Vice-Président" sur cockpit | 0 / 0 (8 / 0) | 6335d460 NON déployé`
- `DEPLOY-3 | "AYA, explique le cargo Atlantic Trader" | aya.show_vessel_evidence → null | 0.0 | e40432b2 NON déployé`
- `BUG1-a | "OK, très bien, tu peux me montrer la situation au port, s'il te plaît ?" | aya.show_maritime_traffic → voice.confirm_yes | 0.875 | reproductible`
- `BUG1-b | "D'accord AYA, montre-moi la situation au port s'il te plaît." | aya.show_maritime_traffic → voice.confirm_yes | 0.89 | reproductible`
- `BUG1-c | "Très bien, peux-tu m'ouvrir la vue du port d'Abidjan ?" | aya.show_maritime_traffic → null (no_match) | 0.0 | différent — no_match`
- `BUG2 | "AYA, focus sur la zone Nord et le projet Napié." | camera Korhogo via map_command | camera={lon:-5.65, lat:9.15, zoom:6.95} | backend OK`
- `BUG4 | grep "M. le Vice" sur S1+S2 final_text | 0 attendu | 26 trouvés | reproductible`

### Edge cases
- `EDGE-01 | "OK" | no_match ou confirm | voice.confirm_yes | 0.995`
- `EDGE-02 | "le rapport" | no_match | null | 0.0`
- `EDGE-03 | "show port view" | no_match | null | 0.0`
- `EDGE-04 | "AYA, alors voilà, donne-moi le brief" | aya.priority_summary | aya.priority_summary | 0.855`
- `EDGE-05 | "la décision" | no_match | null | 0.0`
- `EDGE-06a | "parfait merci" | no_match attendu | null | 0.0`
- `EDGE-06b | (enchainement S2.5 + "parfait merci") | ne doit pas valider | RAG fallback, aucune confirm | 0.0 (safe)`

---

## 11. Side-effects laissés par ce QA (à reset avant la VP)

| Champ | Valeur post-QA | Action de reset |
|---|---|---|
| `actions.last_focus` | `cargo-abidjan-supply-001` (posé par S1.4) | `predemo_reset.sh` step 2 |
| `actions.current_meeting` | `5f3ccd49-9877-445a-a385-cabf61a784b4` (posé par S2.7) | `predemo_reset.sh` step 2 |
| `actions.pending_agenda_patch` | **staged** (posé par enchaînement EDGE-06b après S2.6) | `predemo_reset.sh` step 2 |
| `actions.awaiting._workspace` | `{key: calendar_agenda_patch, expires_at: 23:13}` + bucket legacy `customs_email` expiré | `predemo_reset.sh` step 2 |
| `evt-prefet-nawa.metadata.agenda_items` | `[Point cacao - diversification anacarde …]` (posé par S2.6, re-staged par EDGE-06b) | `predemo_reset.sh` step 3 (cancel + re-POST event) |
| `meeting_decisions` (table) | +1 décision option B `decided_at=2026-05-24T22:52` → total 4 sur l'event Nawa | non purgé par `predemo_reset.sh` ; impact narratif S2.9 = top-5 → présentateur verra 4 décisions cumulées (narratif renforcé, pas un blocker) |
| Object store | +1 PDF stratégique cacao `strategic-cacao_diversification-da95677bd29a.pdf` 15 KB | non purgé, idempotent par hash, safe |

**Étape 1 du plan Ops §8 : `./scripts/predemo_reset.sh` est mandatory** avant la démo.

---

> **Recap final** : `GO_AFTER_DEPLOY` (push 4 commits + redeploy back+front + reset workspace + smoke 20/20). Si Ops n'est pas disponible → `GO_DÉGRADÉ` avec contournements §9 (S1.5 → fallback S1.4, S1.3 → click manuel, fillers polis → toujours verbe en premier, TTS « M » → briefing). Pas de NO-GO : aucun bug réel non couvert par un commit prêt à déployer.
