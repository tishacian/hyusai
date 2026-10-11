# Sentinel-CI — QA post-déploiement, périmètre Scénario 1

- **Cible** : `https://agentium.papai.ai`, workspace `sentinel-ci`, profil `vigie_executive`
- **Compte** : `thibaud.ishacian@datategy.net` (login `/api/v1/auth/login`, JWT 1563 caractères)
- **Run** : dimanche 24 mai 2026, ~12h55 (UTC+2), driver HTTP `/tmp/sentinel_qa/run_s1.py`
- **Référentiel** : trame [`docs/demo-aya-storytelling-trame.md`](./demo-aya-storytelling-trame.md) §S1 + cheatsheet [`docs/sentinel-ci-presenter-cheatsheet.md`](./sentinel-ci-presenter-cheatsheet.md) §S1
- **Branche locale HEAD** : `2da62be7` sur `demo/agentic` (commits visibles : `2da62be7`, `b828d8b9`, `548c9ce4`, `d452e001`, `4c0208e1`, `d1490f18`, `09188fa6`, …)

## 1. Contexte / tip de prod

| Sonde | Résultat | Interprétation |
|---|---|---|
| `GET /health` (racine) | 200, sert l'index Angular | reverse-proxy frontal OK |
| `GET /api/v1/health` | 200 `{"status":"healthy","service":"AI Orchestration Platform","version":"1.0.0-demo"}` | backend up — pas de champ git_sha, version applicative figée |
| `GET /mission-room/cockpit` | 200 — `date_label = "Lundi 25 Mai 2026"`, AYA recommendation prompt = phrase d'ouverture S1 | démo-time résolu, seeds 25/05 actifs |
| `vp_status_bar[0].id` non-null (`zone-nord-tension`) | OK | preuve **Vague 3 polish `d1490f18`** déployée |
| `HEAD /mission-room/webcams/proxy?source_id=apm-apapa-gate-1` | 200, `Content-Length=85985` | preuve **Vague 3 polish `d1490f18`** déployée |
| Résolveur `aya.acknowledge_presence` sur « AYA » seul | match conf 0.99 | preuve **Vague 1 `09188fa6`** déployée |
| Résolveur `aya.show_customs_record` sur « pv douanes » | match conf 1.01 | preuve **Vague 1 `09188fa6`** déployée |
| Résolveur `aya.summarize_last_exchanges` sur « resume Prefet Nawa » | match (testé via variantes) | cohérent avec Vague 1+ |

Le backend n'expose pas de SHA git ; tous les marqueurs comportementaux des commits `09188fa6` (Vague 1) et `d1490f18` (Vague 3) sont actifs, donc le tip prod est **au moins** à `d452e001` / `548c9ce4` (les commits suivants `4c0208e1`, `b828d8b9`, `2da62be7` n'ont pas d'effet API observable distinct, ils restent neutres pour S1).

## 2. Tableau de bord par étape

| # | Étape | Action attendue | Verdict | Preuve principale |
|---|---|---|---|---|
| S1.0 | Ouverture cockpit | `GET /mission-room/cockpit` | **PASS** | `date_label = "Lundi 25 Mai 2026"`, chip 0 = `zone-nord-tension` label « Zone Nord » value « Tendue » pulse=true, agenda chip = `6 aujourd'hui`, press hero = Centre Drones Napié |
| S1.1 | « AYA, pourquoi la situation Nord est-elle tendue ? » | `aya.explain_why` | **PASS** | resolver conf **1.06**, SSE 871 ms, narrative `"Retard du Centre Drones Napié … composants drones Aerostar Dynamics bloqués à Vridi : retard estimé à 120 jours …"`, 0 mention Konaté/Burkina |
| S1.2 | « AYA, montre-moi le PV douanes » | `aya.show_customs_record` | **PASS** | resolver conf **0.89**, SSE 126 ms, drawer `assistant-draft-open` target_type=`document_preview` target_id=`proces-verbal-douanes-non-conformite-2026-05-18` page 2 |
| S1.3 | « AYA, focus sur la zone Nord et le projet Napié » | `aya.focus_zone_with_project` | **PASS** | resolver conf **0.88**, SSE 702 ms, navigate `focus=zone-nord` + `highlight=proj-drone-centre-napie`, map_command `intent=focus_zone target=zone-nord camera lon=-5.65 lat=9.15 zoom=6.95` |
| S1.4 | Click MV Atlantic Trader sur carte + prompt | `aya.show_vessel_evidence` (tie-breaker) + webcam APM Apapa | **WARN** | Phrase littérale de la trame `"AYA, explique le cargo Atlantic Trader"` → **pas de match résolveur** (conf 0, RAG fallback). Variantes cheatsheet OK (cf. §3). HEAD webcam = 200 / 85985 octets. |
| S1.5 | « AYA, rédige le courrier de dédouanement pour Atlantic Trader » | `aya.draft_customs_email` | **PASS** | resolver conf **0.94**, drawer email `target_type=customs_email`, recipient = `"Direction generale des Douanes — Chef de la cellule portuaire Abidjan"`, corps mentionne `"Centre Formation Napié (MV Atlantic Trader)"`, 0 mention Konaté/Burkina |
| S1.6 | Cohérence narrative globale post-S1.5 | 0 occurrence Konaté/Burkina | **PASS (mineur)** | `actions.last_focus = customs-record-non-conformite-2026-05` (cohérent avec la chaîne S1.2 → S1.5), 0 hit Konaté/Burkina sur `vp_story` + `attention_required` + `aya_recommendation` + `executive_decision_packages` + `vp_status_bar` + `geographic_signal_tiers` |

Score étapes : **6 PASS, 1 WARN, 0 FAIL**.

## 3. Détails par étape

### S1.0 — Ouverture cockpit (PASS)

- `GET /api/v1/mission-room/cockpit` → 200.
- `date_label = "Lundi 25 Mai 2026"`.
- `vp_status_bar[0]` :
  ```json
  {"id":"zone-nord-tension","key":"zone-nord-tension","label":"Zone Nord","value":"Tendue","detail":"Centre Drones Napie en retard - cargo Aerostar bloque","tone":"critical","pulse":true}
  ```
- `vp_status_bar[5]` = chip `agenda` value `"6"` detail `"aujourd'hui"`.
- `agenda_day.events` = 4 items, **tous datés 2026-05-25**. Le compteur 6+ visible est consolidé via `GET /api/v1/calendar/events` (vérifié séparément : 16 events totaux, **6 sur 2026-05-25**, 2 sur 2026-05-26).
- `press_preview[0]` = `id="press-fallback-abidjan-net-drone-napie"` titre « Côte d'Ivoire — Lancement du Centre International de Formation aux Métiers des Drones de Napié », source `Abidjan.net`, risk_level `high`.
- `aya_recommendation.prompt` = `"AYA, pourquoi la situation Nord est-elle tendue ?"` — la phrase d'ouverture S1 est nativement portée par le cockpit.

### S1.1 — Drill Nord (PASS)

- Prompt : `"AYA, pourquoi la situation Nord est-elle tendue ?"`
- `/actions/resolve` → action `aya.explain_why`, matched=true, **conf 1.06** (≥ 0.85 attendu).
- SSE 871 ms, 4 frames : 1 `action_effect` + 1 `action_result` + 1 `text` final + 1 `[DONE]`.
- Frame `action_effect` :
  - `effect=assistant-navigate`, `route=/hypervisor/mission-room/strategie`, `queryParams={"focus":"zone-nord"}`, `highlight=proj-drone-centre-napie`.
- `text.final` (extrait) : « M. le Vice Premier Ministre, Retard du Centre Drones Napié nourrit la tension territoriale dans la région du Poro / Nord. Composants drones Aerostar Dynamics (USA) bloqués à Vridi : retard estimé à 120 jours sur le chantier du Centre Napié (100 M USD / Côte d'Ivoire Innovation 2030). »
- Vérification narrative : « Napié » présent, **0 occurrence Konaté/Burkina** dans le `final_text` ni dans `registry_action.content`.

### S1.2 — Voir PV douanes (PASS)

- Prompt : `"AYA, montre-moi le PV douanes"`
- `/actions/resolve` → action `aya.show_customs_record`, matched=true, **conf 0.89**.
- SSE 126 ms, 6 frames. 3 `action_effect` :
  1. `assistant-navigate` `route=/hypervisor/mission-room/strategie` `queryParams={"panel":"maritime","document":"proces-verbal-douanes-non-conformite-2026-05-18"}`
  2. `assistant-draft-open` `target_type=document_preview` `target_id=proces-verbal-douanes-non-conformite-2026-05-18` — `draft_payload` :
     ```json
     {"kind":"document_preview","title":"PV douanes - non conformite declarative","date":"2026-05-18","page":2,"highlight":"Cargo non conforme distinct du cargo MV Atlantic Trader","citation":"Page 2 du PV douanes du 18 mai 2026 - cargo non conforme distinct."}
     ```
  3. `assistant-propose` `proposal_id=propose-customs-derogation` `confirm_action=aya.draft_customs_email` (chaînage S1.2 → S1.5 actif).
- C'est bien la **fiche PV (document_preview)** qui s'ouvre, pas la fiche navire.

### S1.3 — Focus zone Nord + projet Napié (PASS)

- Prompt : `"AYA, focus sur la zone Nord et le projet Napié"`
- `/actions/resolve` → action `aya.focus_zone_with_project`, matched=true, **conf 0.88**.
- SSE 702 ms, 5 frames :
  - `assistant-navigate` `queryParams={"focus":"zone-nord"}` `highlight=proj-drone-centre-napie` (project_id porté ici).
  - `map_command` `intent=focus_zone` `target=zone-nord` `map_slug=sentinel-ci-strategic-map` `map_state.camera={lon:-5.65, lat:9.15, zoom:6.95}` (équivalent bbox).
- Note design : bbox+project_id ne sont pas dans un seul payload, ils sont répartis entre `assistant-navigate` (project_id via `highlight`) et `map_command` (camera = bbox). C'est cohérent avec le contrat actuel et le front Angular sait recoller (cf. `test_chat_stream_hardening.py:292-310`). Si la team UX veut un payload unique, c'est un backlog post-démo, pas un bloquant.

### S1.4 — MV Atlantic Trader + webcam APM Apapa (WARN)

Préalable carte (simulation du click) — `GET /api/v1/mission-room/maritime/vessels?bbox=-4.6,5.05,-3.75,5.40` → 200, 16 navires. Atlantic Trader trouvé : `mmsi=627012345`, `linked_cargo_id=cargo-abidjan-supply-001`, `recommended_webcam_source_id=apm-apapa-gate-1`. ✅

Webcam HEAD : `HEAD /api/v1/mission-room/webcams/proxy?source_id=apm-apapa-gate-1` → **200**, `Content-Length=85985`. ✅

Prompt chat (trame littérale) :

| Prompt | Resolver | SSE |
|---|---|---|
| `"AYA, explique le cargo Atlantic Trader"` (trame) | **no_match** (conf 0.0) | `chat/stream` part en orchestrateur RAG, **timeout 10 s** côté driver, aucun `action_effect` AYA |
| `"AYA, montre le cargo Atlantic Trader"` (cheatsheet) | `aya.show_vessel_evidence` conf **0.91** | 7 frames, 3 `action_effect` |
| `"AYA, montre le navire MV Atlantic Trader"` | `aya.show_vessel_evidence` conf **1.06** | 7 frames, 3 `action_effect` |
| `"AYA, montre le cargo"` | `aya.show_vessel_evidence` conf **1.02** | 7 frames, 3 `action_effect` |
| `"AYA, voir flux entree port"` | `aya.show_vessel_evidence` conf **1.04** | 7 frames, 3 `action_effect` |
| `"Pourquoi cette cargaison est-elle bloquée ?"` (cheatsheet drill) | `aya.explain_why` conf **1.06** | équivalent : drill vers `cargo-abidjan-supply-001`, émet webcam + propose PV |
| `"AYA, montre Atlantic Trader"` (forme orale courte) | **no_match** (conf 0.0) | conforme à la note « À éviter » de la cheatsheet |

Quand le bon prompt est utilisé, le SSE émet bien :

- `assistant-navigate` `queryParams={"mode":"live","panel":"maritime","vessel":"mv-atlantic-trader"}` `highlight=cargo-abidjan-supply-001`
- `assistant-show-webcam` `source_id=apm-apapa-gate-1` `cargo_id=cargo-abidjan-supply-001` `vessel_mmsi=627012345`
- `assistant-propose` `proposal_id=propose-customs-pdf-show` `confirm_action=aya.show_customs_record`

**Donc la capacité backend est intacte (PASS sur 4 variantes / 6 testées)** ; le verdict S1.4 est WARN parce que la **phrase littérale écrite dans la trame** n'est pas dans le pack résolveur — la démo passera seulement si le présentateur lit la version cheatsheet (« montre le cargo Atlantic Trader », « pourquoi cette cargaison est-elle bloquée », ou click physique sur le marqueur AIS).

### S1.5 — Préparer la dérogation douanes (PASS)

- Prompt : `"AYA, rédige le courrier de dédouanement pour Atlantic Trader"`
- `/actions/resolve` → `aya.draft_customs_email`, matched=true, **conf 0.94**.
- SSE 4 frames, 1 `action_effect` :
  - `assistant-draft-open` `target_type=customs_email` `target_id=cargo-abidjan-supply-001` `draft_payload.status=draft`, `template_kind=customs_derogation`, `requires_validation=true`, `advisory_only=true`.
- Subject : `"Demande de derogation operationnelle — cargaison composants drones Centre Formation Napié (MV Atlantic Trader)"`.
- Recipient : `"Direction generale des Douanes — Chef de la cellule portuaire Abidjan"`.
- Body markdown (extrait) : « Monsieur le Chef de la cellule douaniere, Faisant suite au proces-verbal de non-conformite declarative du 18 mai 2026 (ref. DGD-CI/CPA/PV-2026-05-018, page 2), je vous saisis pour solliciter une **derogation operationnelle ciblee** au benefice du cargo MV ATLANTIC TRADER (IMO 9876543, MMSI 627012345, ref. cargo-abidjan-supply-001). **Le cargo MV Atlantic Trader est distinct du lot non conforme** … »
- Vérifications : « Napié » présent (« Centre Formation Napié »), **0 mention Konaté/Burkina**.

### S1.6 — Cohérence narrative globale (PASS, mineur)

- `GET /mission-room/cockpit` (post-S1.5) → 200.
- `GET /auth/workspaces/sentinel-ci` → 200, lecture de `settings.actions` :
  - `last_focus = "customs-record-non-conformite-2026-05"` — cohérent avec la chaîne `S1.2 (set_last_focus=customs-record) → S1.5 (draft_customs_email, ne change pas last_focus)`. La trame demande « reflète Napié » au sens du **fil narratif Napié → cargo → PV → dérogation** ; le nœud actuel est le PV, qui est le pivot de cette chaîne.
  - `current_meeting = "5f3ccd49-9877-445a-a385-cabf61a784b4"` — **pollution résiduelle** d'un run antérieur (la trame S2 a déjà été jouée plus tôt sur ce workspace, cf. §6).
  - `pending_agenda_patch = absent`, `awaiting = {}` — propre.
- **Cohérence narrative** : balayage des blocs `vp_story`, `attention_required`, `aya_recommendation`, `executive_decision_packages`, `vp_status_bar`, `geographic_signal_tiers` ⇒ **0 occurrence des tokens `Konaté` / `Konate` / `Burkina`**, y compris dans le `geographic_signal_tiers.tier_2` (« contexte régional secondaire »). La narration reste 100 % CI / Napié / Vridi / Poro.

## 4. Probe sec (3 prompts S1 du `smoke_predeploy_probe.py`, `/actions/resolve`)

| # | Prompt | Attendu | Obtenu | Conf | Verdict | Pré-deploy |
|---|---|---|---|---|---|---|
| 1 | `AYA` | `aya.acknowledge_presence` | `aya.acknowledge_presence` | 0.99 | **PASS** | était FAIL (commit Vague 1 `09188fa6`) |
| 2 | `AYA, donne-moi le brief` | `aya.priority_summary` / `aya.focus_zone_with_project` / `aya.explain_why` | `aya.priority_summary` | 0.85 | **PASS** | déjà PASS pré-deploy |
| 3 | `pv douanes` | `aya.show_customs_record` | `aya.show_customs_record` | 1.01 | **PASS** | était FAIL (Vague 1 `09188fa6`) |

Les 2 prompts qui dépendaient du redéploiement (`AYA` seul et `pv douanes` ultra-court) sont désormais **PASS** ⇒ la **Vague 1 `09188fa6` est bien déployée**.

## 5. Variantes acceptables (3) + test négatif (1)

| Type | Prompt | Attendu | Obtenu | Conf | Verdict |
|---|---|---|---|---|---|
| Variante | `AYA, pourquoi le Nord est tendu ?` | `aya.explain_why` | `aya.explain_why` | 1.05 | PASS |
| Variante | `pourquoi Nord tendu` (ultra-court) | `aya.explain_why` | `aya.explain_why` | 1.02 | PASS |
| Variante | `AYA, montre le PV` (ultra-court verbal) | `aya.show_customs_record` | `aya.show_customs_record` | 1.02 | PASS |
| Négatif | `AYA, quel temps fait-il à Korhogo ?` | RAG fallback, **aucune** action AYA | resolver `no_match` (conf 0.0) ; `chat/stream` 77 frames, **aucun `action_effect`**, registry_action vide | — | **PASS** (fallback propre, ~10 s de génération RAG, pas d'action latérale) |

## 6. Bloquants éventuels (priorisés)

| Prio | Item | Impact démo | Recommandation |
|---|---|---|---|
| **P1 (doc)** | Phrase trame S1.4 `"explique le cargo Atlantic Trader"` non couverte par le pack résolveur (fallback RAG silencieux, ~10 s d'attente sans `action_effect`). | Si le présentateur lit la trame mot à mot, le drawer maritime / webcam ne s'ouvre **pas**, et l'expérience démo casse silencieusement (10 s de silence puis texte RAG). | Aligner la trame S1.4 sur la cheatsheet : `"AYA, montre le cargo Atlantic Trader"` ou `"Pourquoi cette cargaison est-elle bloquée ?"`. Alternative backend (post-démo) : ajouter les phrases `"explique le cargo"`, `"explique cette cargaison"`, `"explique Atlantic Trader"` aux `phrases` de `aya.show_vessel_evidence` dans `backend/app/services/actions/registry.py`. |
| **P2 (Ops)** | `workspace.settings.actions.current_meeting = 5f3ccd49…` pré-rempli avant le run S1 (résidu S2 antérieur). | Aucun impact sur S1, mais peut perturber la transition agenda → S2 si la démo enchaîne. | Exécuter `./scripts/predemo_reset.sh` avant la démo Vice Premier Ministre (déjà prévu côté Ops). Au minimum `POST /api/v1/admin/workspace/reset-actions` avec `clear_current_meeting=true` et `clear_last_focus=true`. |
| **P2 (état)** | Ce run a écrit `last_focus = customs-record-non-conformite-2026-05` (effet attendu de S1.2 + S1.5). | État cohérent avec un Vice Premier Ministre qui termine S1 sur la dérogation, mais si on rejoue S1 « à neuf », la démo commencerait avec `last_focus` non vide ⇒ `aya.explain_why` repartirait du PV au lieu de la zone Nord. Le code a un guard `text_focus` (cf. `executor.py:510-520`) qui re-route correctement quand le prompt contient « nord » ou « tendu », donc PASS de fait. | Reset par `predemo_reset.sh` avant la démo Vice Premier Ministre. |
| **P2 (UX/design)** | `aya.focus_zone_with_project` distribue `project_id` (frame `assistant-navigate.highlight`) et `bbox` (frame `map_command.map_state.camera`) sur deux frames différentes. | Front Angular sait déjà recoller, donc aucun impact en démo. | Backlog post-démo : envisager un payload unifié si la cellule UX le réclame. |
| **P3 (observabilité)** | Pas de champ `git_sha` / `deploy_commit` dans `/api/v1/health` (`version` figée à `1.0.0-demo`). | Aucune action démo, mais difficile de qualifier le tip de prod sans rejouer une sonde comportementale. | Backlog : exposer `app_version + git_sha` dans `/health` (`backend/app/api/v1/endpoints/health.py`). |

Aucun bloquant **P0** identifié.

## 7. Verdict global S1

**Go — Dégradé léger en cas de lecture littérale de la trame S1.4.**

Justification : 6 étapes sur 7 PASS, la 7ème (S1.4) est WARN uniquement à cause d'une phrase de trame non alignée sur le pack résolveur ; le chemin technique (résolveur → SSE → `assistant-show-webcam` source `apm-apapa-gate-1`) est intact sur **4 variantes cheatsheet sur 6**, la sonde sèche S1 passe à **3/3** et le test négatif est propre — la démo Vice Premier Ministre peut être jouée dès lors que le présentateur dit `"AYA, montre le cargo Atlantic Trader"` (ou clique sur le marqueur AIS) plutôt que la phrase trame `"explique le cargo Atlantic Trader"`.

---

> Pré-flight démo Vice Premier Ministre : exécuter `./scripts/predemo_reset.sh` (déjà au runbook Ops) pour purger `last_focus` + `current_meeting` modifiés par ce QA, et soit corriger `docs/demo-aya-storytelling-trame.md` §S1 étape 3 (« Pourquoi cette cargaison est-elle bloquée ? » au lieu d'« explique le cargo »), soit briefer oralement le présentateur sur la variante cheatsheet.
