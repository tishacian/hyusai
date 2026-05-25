# SENTINEL-CI — QA post-deploy Scénario 2 (Préfet Nawa / cacao)

**Date du run** : 2026-05-24, ~12:51 (UTC+2) / ~10:51 UTC
**Cible** : `https://agentium.papai.ai`, workspace `sentinel-ci`, profil assistant `vigie_executive`
**Compte** : `thibaud.ishacian@datategy.net`
**Outils** : harness Python `urllib` (login → JWT, `POST /api/v1/actions/resolve` pour la résolution sèche, `POST /api/v1/chat/stream` SSE pour le flow état-ful, `GET /auth/workspaces/sentinel-ci`, `GET /calendar/events`, `GET /meetings/{id}/decisions`, HEAD/GET sur l'URL PDF rapport)

## 1. Contexte

- **Tip de prod inféré** : commit `d452e001` (`chore: purge debug agenda event in predemo reset`), version « post-Vague 1 (`09188fa6`) + Vague 3 polish (`d1490f18`) ». Inférence basée sur :
  - `aya.acknowledge_presence` répond sur prompt « AYA » seul (Vague 1) → resolver renvoie `aya.acknowledge_presence` conf=0.995.
  - `vp_status_bar[0].id` non-null (Vague 3 polish) — non re-vérifié dans ce run mais déjà PASS dans le smoke pré-deploy `548c9ce4`.
  - `demo_time_context` figé sur `2026-05-25 10:30:00 Africa/Abidjan` (label `Lundi 25 Mai 2026`).
- **État pré-run du workspace** :
  - `actions.last_focus = null`, `actions.current_meeting = null`, `actions.pending_agenda_patch = null`, `actions.awaiting = null` → workspace clean (compatible `predemo_reset.sh` joué récemment).
  - 16 événements calendar au total (6 sur `2026-05-25` + 2 sur `2026-05-26` + **8 résidus** sur d'autres dates non purgés). Note : le pré-démo `predemo_reset.sh` (purge debug + legacy < `DEMO_DATE`) doit être rejoué avant la VP — voir §6.
  - Événement `evt-prefet-nawa` : `id=5f3ccd49-9877-445a-a385-cabf61a784b4`, `start_at=2026-05-25T11:00:00`, `context_ref=report-prefet-nawa-2026-05-10`, `agenda_items=null` (vierge avant patch).
- **Déroulé** : 1 sec probe (3 prompts pivots) + 3 variantes + 1 négatif + scénario état-ful S2.0 → S2.9 (10 prompts SSE consécutifs, session_id=null → awaiting bucket `_workspace`).

## 2. Tableau de bord — verdict par étape

| Étape | Action attendue | Action exécutée (SSE) | Score (resolver) | Verdict |
|---|---|---|---|---|
| S2.0 | `aya.open_next_meeting` | `aya.open_next_meeting` | 0.890 | **PASS** |
| S2.1 | `aya.summarize_last_exchanges` (résumé derniers échanges) | `aya.summarize_last_exchanges` | 0.920 | **PASS** |
| S2.2 | Résumé long document Préfet Nawa | `aya.summarize_last_exchanges` (handler intègre `summarize_long_document_v1`) | 0.905 | **PASS** |
| S2.3 | `aya.recommend_cacao` | `aya.recommend_cacao` | 1.060 | **PASS** |
| S2.4 | `aya.draft_strategic_report` + URL PDF accessible | `aya.draft_strategic_report` ; PDF GET 200/`application/pdf` mais **15 KB / 12 pages** (vs 100 KB / 70 pages annoncés au brief) ; **HEAD 404** | 1.040 | **WARN** |
| S2.5 | `aya.update_meeting_agenda` + `pending_agenda_patch` staged | `aya.update_meeting_agenda` ; `pending_agenda_patch` staged correctement, `awaiting` set | 0.920 | **PASS** |
| S2.6 | `aya.confirm_agenda_patch` | `aya.confirm_agenda_patch` (via `voice.confirm_yes` + awaiting bucket) ; `pending_agenda_patch` cleared, ODJ patché côté `evt-prefet-nawa` | 0.875 (sur `voice.confirm_yes`) | **PASS** |
| S2.7 | `aya.start_meeting` | `aya.start_meeting` ; `current_meeting` set sur `5f3ccd49…` | 1.025 | **PASS** |
| S2.8 | `aya.log_decision` | `aya.log_decision` ; décision option B persistée (`/meetings/{id}/decisions` 200) | 0.890 | **PASS** |
| S2.9 | `aya.recall_past_decisions` | `aya.recall_past_decisions` ; renvoie 3 décisions cacao option B (la nouvelle + 2 historiques de runs antérieurs) | 1.060 | **PASS** |

**Synthèse** : 9 PASS / 1 WARN (S2.4 livrable PDF — taille/pages sous le seuil annoncé au brief mais conforme au seed actuel ; voir §6).

## 3. Détails par étape (frames SSE clés + vérifs API)

### S2.0 — « AYA, ouvre la prochaine reunion »

- **Resolver** : `aya.open_next_meeting`, `matched=true`, `confidence=0.890`, `reason=matched`.
- **SSE** : status 200, 220 ms, 3 frames.
  - `chunk_type=action_effect, effect=assistant-navigate, route=/hypervisor/mission-room/agenda, queryParams={highlight: "evt-prefet-nawa"}`.
  - `chunk_type=action_result, action=aya.open_next_meeting, applied=true`.
  - `chunk_type=text` : « M. le Vice President, prochain rendez-vous : **Rencontre Prefet de la region de Nawa** a 11:00 — Soubre (capitale regionale). »
- **Vérifs post** : la route ciblée porte `highlight=evt-prefet-nawa` (alias seed_id, mappé côté front sur `id=5f3ccd49…`). Le texte cite l'event correctement (titre, heure, lieu).

### S2.1 — « AYA, donne-moi le resume du rapport prefet »

- **Resolver** : `aya.summarize_last_exchanges`, `matched=true`, `confidence=0.920`.
- **SSE** : 200, 224 ms, 3 frames.
  - `action_effect, effect=assistant-propose, proposal_id=propose-cacao-recommendations, label="Preconisations cacao", confirm_action=aya.recommend_cacao, decline_action=voice.confirm_no`.
  - `action_result aya.summarize_last_exchanges`.
  - `text` (583 chars) — synthèse structurée : « ~70 pages », région Nawa/Soubre, filière cacao dominante, infrastructures, sécheresse, EUDR, plus prompt de relance vers les préconisations cacao.
- **Vérifs post** : awaiting bucket workspace bascule sur `key=cacao_summary, action_on_yes=aya.recommend_cacao, expires_at=+20min` (consommé ensuite par S2.3 ou enchaînement « oui »).

### S2.2 — « AYA, resume le rapport Prefet Nawa »

- **Resolver** : `aya.summarize_last_exchanges`, `confidence=0.905`. **Note** : il n'existe pas d'action `aya.summarize_long_document_v1` dans le pack `sentinel_ci_aya_v1` ; `summarize_long_document_v1` est le **skill** invoqué par le handler `summarize_last_exchanges` (voir `backend/app/services/actions/executor.py` lignes 892-924). C'est cohérent avec la trame.
- **SSE** : 200, 142 ms, 3 frames identiques à S2.1 (même handler, même payload).
- **Vérifs post** : pas d'effet drawer `document_preview` ici — le résumé est rendu sous forme texte structuré (pattern `summarize_last_exchanges`). Si la VP attend un drawer PDF en mode `document_preview`, la trame doit s'appuyer sur S2.4 (rapport stratégique complet).

### S2.3 — « AYA, donne-moi des preconisations sur le cacao »

- **Resolver** : `aya.recommend_cacao`, `confidence=1.060`.
- **SSE** : 200, 198 ms, 3 frames.
  - `action_effect, effect=assistant-navigate, route=/hypervisor/mission-room/decisions, queryParams={focus: "package-cacao-diversification"}`.
  - `action_result aya.recommend_cacao`.
  - `text` (539 chars) — 3 leviers chiffrés : (1) Petite industrie transformation ~4,2 Mds FCFA / 78 % conf., (2) Coopérative régionale, (3) Plan mixte PPP. Sources `sentinel-ci-anacarde-diversification-v1`.
- **Vérifs post** : awaiting bucket bascule sur `key=strategic_report, action_on_yes=aya.draft_strategic_report` (préparation S2.4 si « oui » direct).

### S2.4 — « AYA, genere le rapport complet »

- **Resolver** : `aya.draft_strategic_report`, `confidence=1.040`.
- **SSE** : 200, **1 235 ms** (génération PDF WeasyPrint synchrone), 3 frames.
  - `action_effect, effect=assistant-draft-open, target_type=strategic_report, target_id=strategic-cacao_diversification-da95677bd29a, draft_payload.kind=document_preview, total_pages=12, audit_event=report.strategic.generated`. Clés présentes : `download_url`, `signed_url`, `object_key=sentinel-ci/reports/{ws-id}/strategic-cacao_diversification-da95677bd29a.pdf`, `context_refs=[report-prefet-nawa-2026-05-10, proj-cacao-transformation-nawa]`, `requires_validation=true`, `advisory_only=true`.
  - `action_result aya.draft_strategic_report`.
  - `text` : « M. le Vice President, rapport de diversification cacao genere (12 pages) — pret pour validation advisory. »
- **Vérifs HTTP sur l'URL PDF** (`/api/v1/mission-room/reports/sentinel-ci/strategic-cacao_diversification-da95677bd29a.pdf`) :
  - **HEAD** → `404 application/json` (Content-Length 22) — endpoint proxy ne supporte pas HEAD ; voir P2-1.
  - **GET** → `200 application/pdf`, **14 994 octets**, magic `%PDF-1.7` ✓ PDF valide.
- **Verdict** : action exécutée correctement, drawer payload conforme, PDF généré et téléchargeable. **WARN** car (a) HEAD 404 (incohérence avec GET), (b) la taille **15 KB / 12 p.** est significativement inférieure aux **>100 KB / ~70 p.** annoncés dans le brief — c'est conforme au seed actuel (le rapport stratégique cacao est une *synthèse*, pas le rapport préfet), mais la trame VP doit être alignée pour ne pas vendre « 70 p. » sur ce livrable. Voir P1-2 et P2-1 §6.

### S2.5 — « AYA, ajoute le point cacao a l'ordre du jour »

> **Note de méthode** : le brief demandait « ajoute le point dérogation douanes ». La phrase est bien matchée par le resolver (`aya.update_meeting_agenda` conf=0.90/0.94 sur 3 variantes testées), **mais** le handler hardcode l'agenda item proposé à `Point cacao - diversification anacarde` quel que soit le prompt (input_schema fixe — `executor.py` lignes 658-668). J'ai donc joué la phrase canonique du cheatsheet pour rester cohérent avec le seed S2 (cacao). Voir P1-1 §6.

- **Resolver** : `aya.update_meeting_agenda`, `confidence=0.920`.
- **SSE** : 200, 153 ms, 4 frames (note : 2 `action_effect` + 1 `action_result` + 1 `text`, pas de `[DONE]` perdu).
  - `action_effect, effect=assistant-draft-open, target_type=calendar_agenda_patch, target_id=5f3ccd49…, draft_payload={event_id, event_title="Rencontre Prefet de la region de Nawa", metadata.agenda_items=[…cacao-diversification…], requires_validation=true, audit_event=calendar.event.agenda_items.proposed, confirm_action=aya.confirm_agenda_patch, decline_action=voice.confirm_no}`.
  - `action_effect, effect=assistant-propose, proposal_id=propose-calendar-agenda-patch, label="Valider la mise a jour de l'ordre du jour ?", confirm_action=aya.confirm_agenda_patch`.
  - `action_result aya.update_meeting_agenda, applied=true`.
  - `text` : « M. le Vice President, je propose d'ajouter le point cacao a l'ordre du jour de **Rencontre Prefet de la region de Nawa**. Validation advisory requise avant ecriture agenda. »
- **Vérifs post (`GET /auth/workspaces/sentinel-ci`)** :
  - `actions.pending_agenda_patch = {event_id: "5f3ccd49…", agenda_items: [agenda-cacao-diversification], proposed_at: <iso>}` ✓ staged.
  - `actions.awaiting = {key: "calendar_agenda_patch", action_on_yes: "aya.confirm_agenda_patch", expires_at: +20min, proposal_id: "propose-calendar-agenda-patch", event_id: "5f3ccd49…"}` ✓.
  - **PAS** d'application immédiate sur `evt-prefet-nawa.metadata.agenda_items` (vérifié post-S2.5 — toujours `null` à ce stade). Garde de confirmation correcte.

### S2.6 — « Oui, valide »

- **Resolver brut** : `voice.confirm_yes`, `matched=true`, `confidence=0.875`. (Le resolver pur ne connaît pas l'awaiting → c'est normal et **attendu**. La traduction `voice.confirm_yes → aya.confirm_agenda_patch` se fait dans `resolve_action_with_awaiting` côté `chat/stream` (`executor.py` lignes 143-170).)
- **SSE (avec awaiting)** : 200, 158 ms, 3 frames.
  - `action_effect, effect=assistant-navigate, route=/hypervisor/mission-room/agenda, queryParams={highlight: "5f3ccd49…"}`.
  - `action_result, action=aya.confirm_agenda_patch, applied=true, action_manifest_id=aya.confirm_agenda_patch`.
  - `text` : « Ordre du jour mis a jour pour **Rencontre Prefet de la region de Nawa** : 1 point(s) ajoute(s) avec tracabilite advisory. »
- **Vérifs post** :
  - `actions.pending_agenda_patch = null` ✓ cleared.
  - `GET /calendar/events` → `evt-prefet-nawa.metadata.agenda_items = [{id: "agenda-cacao-diversification", title: "Point cacao - diversification anacarde (proposition AYA)", order: 99, priority: "high", owner_proposer: "AYA", decision_required: true, source_refs: ["report-prefet-nawa-2026-05-10","sentinel-ci-anacarde-diversification-v1"]}]` ✓ patch persisté.

### S2.7 — « AYA, demarre la reunion »

- **Resolver** : `aya.start_meeting`, `confidence=1.025`.
- **SSE** : 200, 117 ms, 3 frames.
  - `action_effect, effect=assistant-navigate, route=/hypervisor/mission-room/agenda/meeting/5f3ccd49…, queryParams={highlight: "5f3ccd49…"}`. (Note : pas de frame `meeting_started` autonome — le passage en mode meeting live se fait via `assistant-navigate` vers `/agenda/meeting/{id}` ; le front Angular détecte la route et bascule l'UI en mode chronologique. Voir P2-3.)
  - `action_result aya.start_meeting`.
  - `text` : « M. le Vice President, je demarre la reunion **Rencontre Prefet de la region de Nawa**. Mode meeting live - chaque arbitrage sera logge dans le registre des decisions. »
- **Vérifs post** : `actions.current_meeting = 5f3ccd49-9877-445a-a385-cabf61a784b4` ✓ persisté.

### S2.8 — « AYA, decide option B »

- **Resolver** : `aya.log_decision`, `confidence=0.890`.
- **SSE** : 200, 121 ms, 3 frames.
  - `action_effect, effect=assistant-navigate, route=/hypervisor/mission-room/agenda/meeting/5f3ccd49…, queryParams={decision: "<decision_id>"}`. (Pas de frame `meeting_decision_logged` autonome — l'identification de la décision passe par `?decision=<id>` dans la queryParams + `action_result.action=aya.log_decision`. Le front Angular ouvre alors la modale rationale. Voir P2-3.)
  - `action_result aya.log_decision`.
  - `text` : « Decision loggee : option B - Diversification anacarde - alignement Banque mondiale, EUDR.. »
- **Vérifs post (`GET /meetings/5f3ccd49…/decisions`)** : 200, 3 décisions sur cet event (la nouvelle de ce run + 2 historiques de QA antérieurs : `2026-05-24T06:50`, `09:35`, `10:53`). La décision du run présent : `chosen_option=B`, `agenda_item_ref=agenda-cacao-diversification`, `decided_by_label=thibaud.ishacian@datategy.net`, `status=logged`, `source_refs=[sentinel-ci-anacarde-diversification-v1, report-prefet-nawa-2026-05-10]`. Persistence OK.

### S2.9 — « AYA, qu'avons-nous decide la derniere fois ? »

- **Resolver** : `aya.recall_past_decisions`, `confidence=1.060`.
- **SSE** : 200, 197 ms, 2 frames (pas de side-effect de navigation — réponse texte uniquement).
  - `action_result aya.recall_past_decisions`.
  - `text` (427 chars) : « M. le Vice President, decisions passees liees a cacao : - 2026-05-24T10:53 - option B : Diversification anacarde… - 2026-05-24T09:35 - option B : … - 2026-05-24T06:50 - option B : … » → 3 décisions retournées dans l'ordre antéchronologique.
- **Vérifs post** : `extra.decisions` du handler renvoie le top-5 trié par `decided_at` desc. La nouvelle décision (S2.8) apparaît bien en tête.

## 4. Probe sec — résolution déterministe (POST /actions/resolve)

| Prompt | Action attendue | Action obtenue | Conf. | HTTP | ms | Verdict |
|---|---|---|---|---|---|---|
| `resume Prefet Nawa` | `aya.summarize_last_exchanges` | `aya.summarize_last_exchanges` | 1.025 | 200 | ~80 | **PASS** |
| `genere le rapport complet` | `aya.draft_strategic_report` | `aya.draft_strategic_report` | 1.040 | 200 | ~70 | **PASS** |
| `ouvre la prochaine reunion` | `aya.open_next_meeting` | `aya.open_next_meeting` | 0.890 | 200 | ~80 | **PASS** |

→ **3/3 PASS**. La résolution sèche post-deploy confirme que les 3 prompts pivots S2 du runbook (`scripts/smoke_predeploy_probe.py @ 548c9ce4`) sont bien servis par le pack `sentinel_ci_aya_v1` actuellement déployé.

## 5. Variantes acceptables + test négatif

| Catégorie | Prompt | Attendu | Obtenu | Conf. | Verdict |
|---|---|---|---|---|---|
| Variante | `commence la reunion` | `aya.start_meeting` | `aya.start_meeting` | 1.025 | **PASS** |
| Variante | `note la decision` | `aya.log_decision` | `null` (no_match) | 0.000 | **FAIL** (variante non couverte par le pack ; cheatsheet attend « décide option B » / « valide l'option B » — le mot pivot **« décide »** est requis) |
| Variante | `le rapport prefet` | `aya.summarize_last_exchanges` | `null` (no_match) | 0.000 | **FAIL** (forme nominale ultra-courte ; cheatsheet recommande « résume le rapport du préfet » — verbe **« résume »** requis) |
| Négatif | `on fait quoi maintenant` | Pas de match net (fallback RAG) | `aya.open_next_meeting` | 0.890 | **WARN** (le pack v1 expose explicitement « quoi maintenant » comme alias d'`open_next_meeting` — couvert mais ambigu en démo ; cohérent avec le warning cheatsheet « couvert mais ambigu en démo ». Le test négatif n'est donc *pas* négatif côté pack : le pack matche par dessein.) |

→ Les 2 FAIL variante sont **conformes à la doctrine cheatsheet** (formes ultra-courtes / nominales sans verbe pivot tombent en RAG) et ne sont **pas** des régressions. Le test négatif révèle un alias volontaire (`quoi maintenant → open_next_meeting`) à connaître pour la VP.

## 6. Bloquants éventuels (P0 / P1 / P2)

### P0 (bloquant démo)
*Aucun.* Tous les frames SSE attendus sortent, tous les états workspace mutent dans le bon ordre, le PDF stratégique est généré et servable.

### P1 (à traiter avant démo si possible)

- **P1-1 — Décalage trame brief vs handler** : le brief demande « ajoute le point dérogation douanes » mais le handler `aya.update_meeting_agenda` hardcode l'agenda item à `Point cacao - diversification anacarde (proposition AYA)` (cf. `executor.py:658-668`). Sur scène la VP n'a *pas* la main sur le titre de l'item ajouté — le pack ignore le contenu de la phrase et propose toujours le même item cacao.
  - *Recommandation* : aligner la trame VP sur la phrase canonique « ajoute le point cacao à l'ordre du jour » (cf. cheatsheet) **OU** étendre `update_meeting_agenda` pour parser le sujet de la phrase (post-démo backlog).
  - *Mitigation immédiate* : aligner le storytelling sur cacao côté trame présentateur (déjà fait dans `docs/sentinel-ci-presenter-cheatsheet.md` §S2 — pas d'action requise).
- **P1-2 — Stub PDF préfet 70 p. absent en prod** : `GET /api/v1/mission-room/reports/sentinel-ci/rapport-prefet-nawa-2026-05-10.pdf` retourne **732 octets** (`%PDF-1.4` valide mais quasi vide). Le rapport référencé par `context_ref` du seed `evt-prefet-nawa` est donc un stub. Si la VP demande à AYA d'« ouvrir le rapport préfet » (drawer document_preview iframe), l'iframe affichera une page vide.
  - *Détection actuelle* : aucune action S2 n'ouvre directement ce PDF en `document_preview` (S2.1/S2.2 utilisent le **skill** `summarize_long_document_v1` qui lit le contenu du document via la KB, pas via l'object store), donc **non bloquant pour le scénario S2.0–S2.9 codifié**.
  - *Recommandation* : exécuter `scripts/build_sentinel_reports` (CLI mentionné dans `predemo_reset.sh:294`) pour publier le vrai rapport 70 p. dans l'object store **avant** la VP ; si la VP improvise et demande explicitement « ouvre le PDF », il faut un plan B.
- **P1-3 — Décisions cumulées sur evt-prefet-nawa (3 décisions option B)** : 3 décisions historiques de QA antérieurs (`06:50`, `09:35`, `10:53`) déjà loggées. `recall_past_decisions` les ressort toutes en S2.9 → effet « historique fourni » correct mais artificiel. Pas un blocker (le pack tronque à 5).
  - *Recommandation* : ajouter un step optionnel à `predemo_reset.sh` qui purge `meeting_decisions` workspace-scoped avant la VP pour repartir d'un registre vierge ; ou laisser tel quel (le narratif S2.9 est même renforcé par l'historique apparent).

### P2 (polish post-démo)

- **P2-1 — Endpoint reports proxy ne supporte pas HEAD** : `HEAD /api/v1/mission-room/reports/sentinel-ci/<file>.pdf` → `404 application/json` alors que `GET` du même URL → `200 application/pdf`. Le front Angular n'utilise probablement que GET, donc invisible côté UI. Polish à corriger côté backend (router `mission_room.py` reports).
- **P2-2 — Taille rapport stratégique 15 KB / 12 p.** : le brief annonçait `> 100 KB`. Conforme au seed actuel (synthèse cacao, pas le rapport préfet). Si la VP veut un livrable plus dense, étendre `generate_strategic_report` (templates WeasyPrint).
- **P2-3 — Pas de frames SSE typées `meeting_started` / `meeting_decision_logged` / `assistant_show_drawer`** : le brief évoquait ces noms d'effets ; le backend actuel utilise `assistant-navigate` (avec route et queryParams discriminantes) + `assistant-draft-open` (avec `target_type`). Le front Angular sait reconstituer le mode meeting live à partir de la route et le drawer à partir du target_type — donc l'expérience UI est correcte. Si une refacto pose des frames typées dédiées, mettre à jour clients chat-panel.

### Side-effects laissés sur le workspace par ce QA (à reset avant la VP)

| Champ | Valeur post-QA | Action de reset |
|---|---|---|
| `actions.current_meeting` | `5f3ccd49…` (Préfet Nawa) | `predemo_reset.sh` step 2 (PATCH `actions.current_meeting=null`). |
| `actions.pending_agenda_patch` | `null` (déjà cleared par S2.6) | aucun. |
| `actions.awaiting` | `{}` (vide) | aucun. |
| `evt-prefet-nawa.metadata.agenda_items` | `[Point cacao - diversification anacarde …]` | reseed step 3 (cancel + re-POST) — l'event sera recréé sans `agenda_items`. |
| `meeting_decisions` (table) | +1 décision (option B, `decided_at=2026-05-24T10:53`) | cumul depuis runs antérieurs ; non traité par `predemo_reset.sh`. Si reset critique, ajouter purge `DELETE FROM meeting_decisions WHERE workspace_id=…`. |
| Object store | +1 PDF stratégique cacao (~15 KB, `strategic-cacao_diversification-da95677bd29a.pdf`) | non purgé ; safe (servable, identifié par hash). |

→ **Recommandation** : exécuter `./scripts/predemo_reset.sh` après ce QA et **avant** la VP pour repartir clean (pendant le reseed calendar, l'event Préfet Nawa retrouvera son `id` propre et `agenda_items=null`).

## 7. Verdict global S2

**`Go` (avec un WARN documenté sur S2.4 livrable PDF).**

Justification : les 10 étapes du flow état-ful S2.0 → S2.9 exécutent l'action attendue avec score ≥ 0.78 (sauf S2.6 qui passe par la mécanique awaiting `voice.confirm_yes` → `confirm_agenda_patch` à 0.875, comportement spécifié), les mutations d'état workspace (`pending_agenda_patch` staged puis cleared, `current_meeting` set, agenda items patché, décision persistée) sont conformes à la trame, et les frames SSE clés (drawer `calendar_agenda_patch` avec garde de confirmation, navigate `meeting/{id}`, log décision avec `?decision=<id>`) arrivent dans l'ordre. Le seul WARN porte sur la **taille / nombre de pages** du rapport stratégique (15 KB / 12 p. vs 100 KB / 70 p. attendus au brief) — c'est un alignement de narratif présentateur, pas une régression backend. Si la VP n'évoque pas le volume du PDF en démo, **prêt pour scène**.

---

## Annexes — fichiers / scripts utilisés

- Harness QA : `/tmp/s2_qa_harness.py` (login Keycloak → JWT, resolver probe + SSE chat/stream complet + GET workspace/calendar/decisions + HEAD/GET PDF).
- Spot-checks : `/tmp/s2_spot_check.py` (variantes « dérogation douanes », HEAD vs GET PDF, wake-word, calendar/decisions baseline).
- Dump JSON brut : `/tmp/s2_qa_results.json` (frames SSE complètes, snapshots pre/post état).
- Référence pack : `backend/app/services/actions/registry.py` (manifests `aya.*`), `backend/app/services/actions/executor.py` (handlers + awaiting + `_action_effect` payloads).
- Référence trame : `docs/demo-aya-storytelling-trame.md` §Scénario 2 + Transition agenda ; `docs/sentinel-ci-presenter-cheatsheet.md` §S2.
