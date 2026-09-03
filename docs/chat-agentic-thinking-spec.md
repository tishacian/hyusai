# Chat Agentic « Thinking » — Spécification de conception

> **Statut : SEEDÉ (048) + RECÂBLÉ GROUNDING (049) + PARITÉ A/B (050).** Ce
> document accompagne l'artefact
> `backend/app/resources/flows/andritz_chat_agentic_v3.json`. Le System
> « Andritz Chat Agentic » est seedé en DB (048), recâblé par **049** (grounding)
> puis aligné sur le classic par **050 (idempotente + revertible)** (parité
> recall / OOS / routage). Les trois skills agentiques
> (`chat_agentic_plan_v1`, `chat_self_correct_v1`, `response_eval_v1`) sont
> **construites** (`skills_registry/wrappers.py`), leurs contrats d'I/O **figés**
> ici (§7). Le data-flow est **fidèle au `run_engine`** (bugs P0/P1/P2 corrigés)
> et **PROUVÉ par simulation runtime** (cf. §9) + tests unitaires mockés.
>
> **Correctif de grounding (2026-06-26, cf. §0).** L'audit
> `docs/chat-recherche-agentic-grounding-audit-2026-06-26.md` a montré que le
> bras agentique tournait **sans retrieval** (`raw_chunks_retrieved=0`). Cause
> racine + correctifs C1/C2/C3 : voir la nouvelle **§0** ci-dessous.
>
> **Correctif de parité A/B (2026-06-26, cf. §0bis).** Le smoke live post-049 a
> montré 3 défauts résiduels (recall < classic, faux `reject_oos`, sous-routage
> des questions inventaire). Corrigés via les skills + la migration **050** :
> voir **§0bis**.
>
> **Variante COMPLÈTE.** Ce graphe exécute le fan-out d'évaluation complet
> (3 juges en parallèle) + auto-correction + double porte HITL : il est plus
> **coûteux** que le `/chat` transverse. Le coût est un *knob* assumé (§6) ;
> pour une variante « légère », réduire le fan-out à `response_eval` seul.

---

## 0. Correctif de grounding (C1/C2/C3 — 2026-06-26)

L'audit a établi que sur 58/58 runs le bras agentique avait
`raw_chunks_retrieved=0`, `embedding_ms=null`, `qdrant_ms=null` : **il ne faisait
jamais de RAG**. Trois défauts cumulés, corrigés **sans toucher le moteur** (tout
le correctif est dans les skills provider-neutres + la migration 049) :

### C1 (dominante) — retrieval à vide → cause racine `workspace_slug`
Le `run_engine` (`engine._build_initial_ctx`) n'expose au `ctx` des skills que
`workspace_id`, **pas** `workspace_slug`. Or les collections Qdrant sont
**tenant-préfixées** (`andritz__{collection}__…`). Sans slug, `semantic_search_v1`
visait une collection inexistante → 0 chunk, **embedding jamais appelé**.

- **Fix** : `wrappers._resolve_workspace_slug(payload, ctx)` résout le slug depuis
  l'`id` (lookup DB caché) quand il manque, en parité avec le chemin `/chat`
  classic. Le `latency_profile` hardcodé `"fast"` est supprimé (défaut
  `balanced`, sinon piloté par le plan).
- **Fix C1(a)** : `llm_rag_answer_v1` **CONSOMME** désormais le tableau `context`
  (= `join.retrieval.results`) et synthétise **à partir de ces chunks** (citations
  via metadata) au lieu de relancer une recherche ; `context` vide ⇒ **abstention
  honnête** (jamais de génération libre).
- **Preuve live (quota rétabli)** : via le wrapper corrigé, ctx `{workspace_id}`
  seul → `raw_chunks_retrieved=6` (lane balanced) / `8` (lane deep) sur
  « AKK200 working width / line speed », scope résolu sur
  `andritz-notices-techniques-spl-pilot` (filtre projet `AKK200`).

### C2 — `chat_self_correct_v1 / escalate_deep` fabriquait
L'ancienne action `escalate_deep` réécrivait la réponse **sans re-retrieval** →
transformait une abstention en hallucination. Désormais **re-retrieve-or-abstain** :
re-recherche sur la lane `deep` (requête originale via `scope_hint`), puis
re-ancrage sur le **nouveau** contexte ; si toujours rien → abstention. Les
actions `translate`/`declare_partial` ne transforment que le brouillon déjà ancré.

### C3 — `chat_agentic_plan_v1` sur-clarifiait
Le planner renvoyait `action=clarify` + le placeholder `"perimetre de recherche"`
sur des questions claires. Un **gate déterministe** (`_coerce_plan` +
`_assess_clarify_gate`) : rejette les `scope_hint`/`clarifying_question` qui
recopient un placeholder de schéma, et **rétrograde `clarify` → `answer`** dès
qu'un code projet/identifiant est présent ou que la requête n'est pas réellement
ambiguë.

**Provider-neutralité conservée** : modèles via `system.default_model` /
`ModelRouter` (aucun slug provider hardcodé).

---

## 0bis. Correctif de parité A/B (recall / OOS / routage — 2026-06-26, migration 050)

Après 049, le retrieval fonctionnait mais le smoke live restait **inéquitable**
vs le classic (référence). Trois défauts résiduels, corrigés dans les skills +
le `flow_definition` (migration 050) :

### P1 (priorité) — Parité de recall : le pool de candidats était collapsé
**Cause racine technique.** `get_retrieval_profile` (et `_apply_retrieval_budget_policy`)
traitent un **`top_k` seul** comme un *pin utilisateur* : quand seul `top_k` est
fourni (sans `synthesis_k`/`candidate_pool_k`), `synthesis_k` **et**
`candidate_pool_k` sont **rabattus au `top_k`**. Le DAG ne passait que `top_k`
(6 sur balanced) → pool de 6 ⇒ ~6 contextes vs ~12 pour le classic (qui passe le
**triplet complet** top_k 8 / synthesis_k 16 / candidate_pool_k 40). Le chunk
porteur AKK200 (largeur 0,3 m / 10-20 m/min) ne remontait pas → abstention.

- **Fix** : le plan EXPOSE et les `retrieve_*` TRANSMETTENT le **triplet de
  budgets par lane** (= `chat._apply_retrieval_budget_policy` : balanced 8/16/40,
  deep 8/24/80, fast 5/12/20). En filet de sécurité, `_semantic_search_v1`
  *backfill* aussi ces budgets par lane (`_LANE_BUDGETS`) si le plan
  sous-spécifie. Plus de `top_k` hardcodé à 5.
- **Preuve live** : balanced `top_k=6` seul → `merged=6`, carrier **absent** ;
  balanced budget complet → `merged=38`, 19 résultats, **carrier présent**.

### P2 — Faux `reject_oos` (question valide en allemand)
Le planner classait à tort `QMS-12` (allemand) hors-périmètre.

- **Fix planner** (`_coerce_plan`) : `reject_oos` **rétrogradé en `answer`** dès
  qu'un projet/machine/système connu est cité (`_PROJECT_CODE_RE` ou
  `_KNOWN_ENTITY_RE` : QMS-12, Qualiscan, URACA, Etachrom, SINAMICS…). **Jamais**
  de rejet sur la base de la langue (prompt durci).
- **Backstop runtime** (`decision.deliver`) : `reject_oos` n'est honoré **que si
  `context_count == 0`** (retrieval réellement vide). Un faux `reject_oos` avec
  du contexte pertinent retombe sur `deliver` (réponse ancrée).

### P3 — Routage + énumération des questions inventaire/transversales
Le planner mettait `URACA` (« Quels projets utilisent une pompe URACA ? ») en
`balanced` alors que le classic va en `deep` ; et même en `deep`, le bras B
décrivait la pompe au lieu d'**énumérer les projets**.

- **Routage** (`_coerce_plan` + `_INVENTORY_RE`) : les questions transversales /
  inventaire / énumération multi-projets (« quels projets… », « liste… »,
  « sur quels projets », agrégation) sont **forcées en `mode=deep`** + budget
  deep. `escalate_deep` re-retrieve désormais avec le **budget deep complet**
  (8/24/80) via `_LANE_BUDGETS`.
- **Énumération (parité classic)** : `semantic_search_v1` arme la même **facette
  exhaustive `project_code`** que le classic (`answer_profile =
  transversal_inventory` → `rag.context.build_project_inventory`) pour les
  questions « quels projets… », et **expose l'inventaire comme passage #1
  autoritatif** ; la synthèse liste alors les projets (ex. URACA → **133
  projets** : BHX100, AKI500, BCX200, …), au lieu de décrire l'équipement.

### P4 — Génération qui s'abstenait malgré le contexte (parité dominante)
Le smoke montrait que, même avec le **chunk porteur en tête** (AKK200 :
`Arbeitsbreite 0,3 m / Produktionsgeschwindigkeit 10-20 m/min`, top score), le
bras B **s'abstenait** (« non spécifiée ») là où le classic répondait.

- **Cause** : `_build_grounded_answer_prompt` adoptait un cadrage
  *abstention-first* (« réponds STRICTEMENT… dis-le si absent ») qui rendait
  gpt-4o-mini trop prudent face à des tableaux HTML FR/EN/DE. Plus une
  troncature `[:1500]` qui pouvait couper des tables.
- **Fix** : prompt aligné sur le cadrage **FACTUEL** du classic (« réponse
  factuelle, précise et **complète** » ; EXTRAIRE les valeurs des tableaux même
  en autre langue ; traduire ; ne jamais inventer). Troncature portée à 4000.
  Preuve live : AKK200 → « 0,3 m / 10 à 20 m/min [2] ».

### P5 — `escalate_deep` se déclenchait sur CHAQUE run (cascade)
`decision.verdict` marquait `weak` dès `hallucination_rate > 0.15`. Or
`response_eval` dérive `hallucination_rate = 1 - factuality` d'une similarité
**embedding** (~0.3-0.5 même pour une bonne réponse) → `weak` **toujours** →
`escalate_deep` **toujours** → (a) **latency aborts** (membrane `max_latency_ms`)
et (b) re-retrieve `deep` qui **perd** le chunk porteur (l'expansion deep d'AKK200
remplace la table par du HTML de menu) → bonne réponse **dégradée en abstention**.

- **Fix verdict** : `weak` = `composite < 50 or context_count == 0` (terme
  hallucination retiré). Plancher de qualité réel ; les bonnes réponses sont
  livrées telles quelles, comme le classic (qui ne s'auto-corrige pas).
- **Fix self_correct** : `escalate_deep` (i) ne se déclenche que si le brouillon
  est lui-même une abstention ou si `composite < 50` ; (ii) **FUSIONNE** le
  contexte original (`join.retrieval.results`, câblé en `inputs_map`) avec le
  re-retrieve deep (jamais de perte de chunk porteur) ; (iii) **ne dégrade
  jamais** un brouillon ancré en abstention (si le re-ancrage abstient, le
  brouillon est conservé).

**Provider-neutralité conservée** (ModelRouter / `system.default_model`).
`dag_validator` reste **0/0**, et les tests unitaires + simulation data-flow
couvrent les correctifs (`test_chat_agentic_skills.py`,
`test_chat_agentic_dataflow.py`).

---

## 1. Contexte : `chat_runtime` vs `run_engine_dag`

Deux runtimes coexistent (cf. `backend/app/services/systems/flow_manifest.py:411-444`) :

| Runtime | Comment il est reconnu | Qui le « marche » |
|---|---|---|
| `chat_runtime` | `flow_definition.variant == "chat_transverse_v1"` (`WORKSPACE_CHAT_VARIANT`) | **Personne** dans le run_engine. Le graphe est un *manifeste descriptif* : l'endpoint `/chat` lit des défauts sûrs (`effective_config`, `prompt_contract`, `source_policy`) à chaque tour. Les « nœuds » documentent le code réel (`runtime_ref`), ils ne sont pas exécutés. |
| `run_engine_dag` | tout autre `variant` **avec** au moins un nœud de contrôle (`decision`/`fork`/`join`/`retry`/`loop`/`hitl`/`subflow`) | `execute_run_dag()` dans `backend/app/services/run_engine/dag.py` (file Kahn, fan-out `asyncio.gather`, checkpoints HITL). |

`should_use_dag(system)` (`dag.py:82-102`) renvoie `True` ssi `schema_version >= 2`
**et** il existe un nœud de contrôle. Le chat transverse n'a que des `task`/`decision`
« descriptifs » mais surtout le mauvais `variant`, donc il reste sur le sequential
walker / le runtime `/chat`.

### Décision d'architecture

Le mode « chat agentic thinking » est un **NOUVEAU System `run_engine` custom**,
**pas** une évolution de la variante `chat_transverse_v1`. Raisons :

1. On veut un *vrai* DAG agentique (plan → route → récupère → génère → auto-évalue
   → corrige → gate) réellement exécuté par `execute_run_dag()`, avec décisions,
   parallélisme (`fork`/`join`), boucle bornée et pause HITL — donc des nœuds de
   contrôle, ce que `/chat` n'exécute pas.
2. On ne touche **pas** au flux `/chat` existant (zéro régression sur le chat
   transverse, qui reste le « quick ask » always-on).
3. On réutilise les skills déjà seedées comme **outils** (retrieval, grounding,
   génération RAG, juges). Aucun nouveau moteur, juste un nouveau graphe + des
   bornes (MembraneSpec).

Le System porte donc `variant = "chat_agentic_thinking_v1"` (≠ `chat_transverse_v1`),
ce qui le classe en `runtime_mode = "run_engine_dag"` dans le manifeste.

---

## 2. Graphe agentic (ASCII)

```
   ┌───────────────┐
   │ source.request│  query, conversation_history
   └───────┬───────┘
   ┌───────▼────────┐
   │  plan.thinking │  chat_agentic_plan_v1 → {action, mode, answer_profile,
   │ (Plan/Thinking)│   scope_hint, clarifying_question, oos_reason, lang_target,
   └───────┬────────┘   confidence, retrieval{latency_profile, retrieval_profile,
           │ data                            top_k, rag_pipeline_mode, deep_retrieval}}
   ┌───────▼────────────┐
   │ decision.route_mode│  fast | deep | balanced(défaut)   ⇐ inputs_map: plan.mode
   └──┬──────┬───────┬──┘
 fast│  deep │balanced│   (toutes RETRIEVAL-ONLY, profils ⇐ plan.retrieval via inputs_map)
 ┌───▼──┐ ┌──▼───┐ ┌──▼───┐
 │retr. │ │retr. │ │retr. │   semantic_search_v1  → {results[]}
 │fast  │ │deep  │ │balan.│
 └───┬──┘ └──┬───┘ └──┬───┘
     └───────┼────────┘
       ┌─────▼─────┐
       │join.retr. │  (any) → results[]   ── 1 seule branche vive après route_mode
       └─────┬─────┘
       ┌─────▼─────┐
       │task.gener.│  llm_rag_answer_v1   context ⇐ join.retrieval.results
       └─────┬─────┘                       → {answer, citations, decision_steps}
       ┌─────▼─────┐
       │fork.self_ │  fan-out parallèle
       │   eval    │
       └┬────┬────┬┘
 ┌──────▼┐ ┌─▼────┐ ┌▼─────────┐
 │eval_  │ │claim_│ │response_ │   response_eval_v1 = SOURCE UNIQUE du composite 0-100
 │radar  │ │audit │ │eval      │   {composite, hallucination_rate, context_count, …}
 └──────┬┘ └─┬────┘ └┬─────────┘
        └────┼───────┘
       ┌─────▼─────┐
       │ join.eval │  (all) barrière fan-in
       └─────┬─────┘
       ┌─────▼──────────┐
       │decision.verdict│  weak | strong(défaut)   ⇐ inputs_map: response_eval.{composite,…}
       └──┬──────────┬──┘
     weak │          │ strong (self_correct skip → vide)
 ┌────────▼──────┐   │
 │task.self_corr.│   │   chat_self_correct_v1 → {answer, citations, action_taken}
 └────────┬──────┘   │
          │          │     ┌───────────┐
          │  ┌───────┴─────┤task.gener.│ (arête listée AVANT self_correct)
          │  │   data      └───────────┘
       ┌──▼──▼─────┐
       │join.answer│  (all) merge ordonné : correction ÉCRASE le brouillon sur weak
       └─────┬─────┘        → {answer, citations}
       ┌─────▼──────────────┐
       │decision.egress_gate│  review | ok(défaut)  ⇐ inputs_map: plan.action + response_eval.composite
       └──┬──────────────┬──┘   review SSI action=='answer' AND composite < 40
   review │              │ ok
 ┌────────▼────────┐     │
 │hitl.expert_review│    │
 └────────┬────────┘     │ branch
          │ control      │
       ┌──▼──────────────▼──┐
       │ decision.deliver    │  clarify | reject_oos | deliver(défaut) ⇐ inputs_map: plan.action
       └──┬────────┬─────────┬┘   (placée EN FIN → pruning propre sur sinks-feuilles)
  clarify │reject_ │ deliver │
 ┌────────▼┐ ┌─────▼────┐ ┌──▼──────────────┐
 │sink.ask_│ │ sink.oos │ │sink.final_answer │  answer + citations + trace(mode, composite)
 │  user   │ │ (reason) │ └──────────────────┘
 │(clarif.)│ └──────────┘
 └─────────┘
```

DAG **acyclique** : l'auto-correction est un **nœud `task`** sur la branche `weak`
(remplace l'ancien `loop`, dont la sortie `{iterations, count}` n'exposait pas
`answer`), **pas** une arête de retour.

**Pattern de livraison (clé).** Le routage `clarify`/`reject_oos`/`answer` est
**placé en FIN de graphe** (`decision.deliver` → 3 sinks-feuilles), car le pruning
du moteur n'est **propre que sur l'enfant direct** d'une décision : une *queue*
multi-nœuds d'une branche tuée **s'exécute quand même** (vérifié runtime, cf. §9).
Router en tête contaminerait donc le sink terminal. En routant en fin vers des
sinks-feuilles, chaque sink non choisi est `all_inputs_dead` ⇒ **skippé AVANT toute
résolution `inputs_map`** ⇒ terminal propre (aucune fuite `answer` sur clarify/oos).
Contrepartie assumée : sur `clarify`/`reject_oos`, le pipeline retrieval+génération
tourne *inutilement* (sa sortie est jetée) — acceptable vs un terminal pollué.

---

## 3. Configuration nœud par nœud

| id | kind | skill_slug | config clés |
|---|---|---|---|
| `source.request` | source | — | outputs: `query`, `conversation_history` |
| `plan.thinking` | task | `chat_agentic_plan_v1` *(à construire, neutre)* | `inputs_map` ⇐ `run.query`/`run.conversation_history` **+ `model` ⇐ `system.default_model`**. `params` = **DOCUMENTAIRE** (non transmis). Émet l'objet `retrieval` (cf. §7). Provider-agnostique via `ModelRouter`. |
| `decision.route_mode` | decision | — | branches `fast` (`mode == 'fast'`), `deep` (`mode == 'deep'`) ; `default_branch=balanced` ; `inputs_map.mode` ⇐ `plan.thinking.mode` (questions inventaire/transversales **forcées `deep`** par `_coerce_plan`, cf. §0bis/P3) |
| `task.retrieve_fast` | task | `semantic_search_v1` (RETRIEVAL-ONLY) | `inputs_map` ⇐ `run.query`, `plan.thinking.scope_hint`, `plan.thinking.retrieval.{latency_profile, retrieval_profile, top_k, synthesis_k, candidate_pool_k}` → `{results}`. **Triplet de budgets** transmis (parité recall §0bis/P1) |
| `task.retrieve_balanced` | task | `semantic_search_v1` (RETRIEVAL-ONLY) | idem `retrieve_fast` (branche défaut) ; budgets balanced 8/16/40 → `{results}` |
| `task.retrieve_deep` | task | `semantic_search_v1` (RETRIEVAL-ONLY) | idem + `inputs_map.deep_retrieval` ⇐ `plan.thinking.retrieval.deep_retrieval` ; budgets deep 8/24/80 → `{results}` |
| `join.retrieval` | join | — | `strategy=any` (1ʳᵉ branche non vide = la seule vive) → `{results}` |
| `task.generate` | task | `llm_rag_answer_v1` | `inputs_map` ⇐ `run.query`, **`context` ⇐ `join.retrieval.results`**, `plan.answer_profile`, `plan.lang_target`, `plan.retrieval.rag_pipeline_mode`, `model` ⇐ `system.default_model` → `{answer, citations, decision_steps}` |
| `fork.self_eval` | fork | — | fan-out parallèle vers 3 évaluateurs |
| `task.eval_radar` | task | `eval_radar_v1` | ports = wrapper réel : `{axes, overall, hallucination_rate, drift_rate, note}` ; `inputs_map` ⇐ `generate.answer`, `run.query`, `join.retrieval.results` |
| `task.claim_audit` | task | `claim_audit_v1` | ports = wrapper réel : `{claims, verdict, supported, unsupported}` ; `inputs_map` ⇐ `generate.answer/citations`, `run.query` |
| `task.response_eval` | task | `response_eval_v1` *(à construire)* | **SOURCE UNIQUE composite 0-100** → `{composite, hallucination_rate, context_count, hhem, factuality, coherence}` ; `inputs_map` ⇐ `generate.answer/citations`, `join.retrieval.results`, `run.query` |
| `join.eval` | join | — | `strategy=all` (barrière fan-in des 3) → `{composite, hallucination_rate, context_count}` |
| `decision.verdict` | decision | — | branches `weak` / `strong` (cf. §5) ; `default_branch=strong` ; `inputs_map` ⇐ `response_eval.{composite, hallucination_rate, context_count}` |
| `task.self_correct` | task | `chat_self_correct_v1` *(neutre)* | branche `weak` ; `inputs_map` ⇐ `generate.answer/citations`, `response_eval.{composite, hallucination_rate}`, `plan.{mode, scope_hint, lang_target, answer_profile}`, `model` ⇐ `system.default_model` → `{answer, citations, action_taken}`. **`escalate_deep` = re-retrieve-or-abstain** au **budget deep complet** (8/24/80, cf. §0/C2 + §0bis/P3). Provider-agnostique via `ModelRouter`. |
| `join.answer` | join | — | `strategy=all` ; arête `task.generate` listée **AVANT** `task.self_correct` ⇒ la correction écrase le brouillon sur `weak` → `{answer, citations}` |
| `decision.egress_gate` | decision | — | branches `review` / `ok` (cf. §5) ; `default_branch=ok` ; `inputs_map` ⇐ `plan.action` + `response_eval.composite` |
| `hitl.expert_review` | hitl | — | `prompt` + `approvers=[expert, operator]` ; `inputs_map.answer` ⇐ `join.answer.answer` |
| `decision.deliver` | decision | — | branches `clarify` / `reject_oos` (gardé par `context_count == 0`, cf. §0bis/P2) / `deliver`(défaut) ; `inputs_map` ⇐ `plan.action` + `response_eval.context_count` |
| `sink.ask_user` | sink | — | `inputs_map.clarifying_question` ⇐ `plan.thinking.clarifying_question` |
| `sink.oos` | sink | — | `inputs_map.reason` ⇐ `plan.thinking.oos_reason` |
| `sink.final_answer` | sink | — | `inputs_map` ⇐ `join.answer.answer/citations`, `plan.mode`, `response_eval.composite` (trace) |

**Câblage des paramètres de récupération (bug P0 #1 corrigé).** `config.params`
n'étant **jamais** transmis aux skills, le comportement de retrieval passe
**exclusivement** par `inputs_map` (VariableRef `{node_id, path}`) : chaque
`retrieve_*` tire `latency_profile`, `retrieval_profile`, `top_k`
(et `deep_retrieval` pour `deep`) depuis l'objet **`plan.thinking.retrieval`**
émis par le planner, plus `knowledge_scope` ⇐ `plan.thinking.scope_hint` et
`query` ⇐ `run.query`. Résolu par `apply_inputs_map` contre le `VariablePool`
(`run_engine/variable_pool.py:152`). `semantic_search_v1` lit ces overrides
depuis son **payload** (`skills_registry/wrappers.py:177-221`) — la simulation §9
confirme que `latency_profile="deep"` **atteint** la skill sur `mode=deep`.

> **`config.params` = DOCUMENTAIRE / non-authoritative.** Les `params` restants
> dans le JSON (system_prompt placeholder, response_format) ne pilotent **aucun**
> comportement runtime ; ils documentent l'intention et sont *baked* dans la skill.

---

## 4. Bornes d'autonomie = MembraneSpec + AdaptivePolicy

La MembraneSpec (`backend/app/services/membrane/spec.py`) est le **contrat de membrane
de processus**, stocké dans `ControlPolicy.extra["membrane_spec"]` et résolu par
`resolve_membrane_spec()`. L'artefact JSON embarque le `membrane_spec` ci-dessous
(round-trip validé via `MembraneSpec.from_dict(..., authoritative=True)`).

```jsonc
{
  "version": 1,
  "inbound": {                              // permeabilité retrieval (ce qui entre)
    "reject_cross_project_sources": true,   // pas de fuite inter-projet
    "industrial_grounding": true            // ancrage industriel Andritz
  },
  "outbound": {                             // gate d'égress
    "expert_review_required": false,        // pas de revue systématique…
    "gate_if_confidence_below": 0.4         // …mais gate si confiance < 0.4
  },
  "capabilities": {
    "allowed_skills": [                      // exactement les skills du graphe (slugs NEUTRES)
      "chat_agentic_plan_v1", "chat_self_correct_v1",
      "semantic_search_v1", "llm_rag_answer_v1",
      "eval_radar_v1", "claim_audit_v1", "response_eval_v1"
    ],                                       // chain_mixed_hah_v1 + chat_grounding_policy_v1 RETIRÉS (cf. §7)
    "allowed_models": [],                    // [] = non restreint : modèles résolus par la config workspace / ModelRouter
    "allowed_delegations": []               // pas de subflow autorisé
  },
  "provenance": {
    "require_citations": true,
    "object_store_prefix": "membrane/andritz/chat-agentic/"
  },
  "valves": {                               // garde-fous durs + circuit-breaker
    "max_latency_ms": 45000,
    "token_budget": 24000,
    "max_cost_per_decision": 0.15,
    "hard_abort": true,                     // une breach AVORTE (pas log-only)
    "mandatory_hitl_if_confidence_below": 0.35,
    "circuit_breaker": { "max_passes": 2 }
  }
}
```

Lecture des facettes :

- **inbound** — `reject_cross_project_sources` + `industrial_grounding` : on
  refuse les sources cross-projet et on impose l'ancrage industriel. (Les autres
  champs `collection_allowlist`, `reference_type_filters`,
  `expert_fiche_correction_enabled`, `preserve_reference_types` restent neutres.)
- **outbound** — pas de revue experte par défaut, **mais** gate si confiance < 0.4.
  La confiance d'égress est **post-answer** = `response_eval.composite / 100`
  (seuil `composite < 40`), pas la confiance pré-answer du planner (cf. §5, bug P1 #7).
- **capabilities** — `allowed_skills` = surface exacte d'outils du graphe (slugs
  **neutres** `chat_agentic_plan_v1` / `chat_self_correct_v1`, jamais un slug
  provider-spécifique comme `azure_llm_v1`) ; tout skill hors-liste est bloqué
  (`_execute_task_node` → Decision `policy_block`). `allowed_models = []` = **non
  restreint** : la gouvernance des modèles est déléguée à la config workspace /
  `ModelRouter` (mettre p.ex. `["ollama:deepseek-r1:14b"]` pour borner on-prem) ;
  `allowed_delegations` vide ⇒ aucun `subflow`.
- **provenance** — citations obligatoires + préfixe object-store pour la lignée.
- **valves** — budgets durs. `hard_abort:true` = une breach (coût/latence/HITL
  manquant) **avorte** le run au lieu de seulement le journaliser. Le
  `circuit_breaker.max_passes=2` plafonne le nombre de passes d'auto-correction.

**Réconciliation des deux portes HITL (bug P1 #9).** Il existe **deux** gardes
de confiance, volontairement complémentaires :

| Garde | Où | Quand | Rôle |
|---|---|---|---|
| `decision.egress_gate` → `hitl.expert_review` | nœud du flow | **pendant** le run, post-answer (`composite < 40`) | **Gate métier** explicite : pause HITL réelle, walkée par `execute_run_dag`. **C'est la garde qui agit.** |
| `valves.mandatory_hitl_if_confidence_below = 0.35` | MembraneSpec | à la **finalisation** sur `Run.confidence` | **Backstop** belt-and-suspenders. Seuil légèrement plus bas (0.35 < 0.40) pour ne déclencher que si le gate métier a été contourné. |

> ⚠️ **`adaptive_policy.latency_above_ms` est INERTE en mode DAG.**
> `_dag_should_stop` (`dag.py:1664-1669`) ne teste **que** `cost_above`. La borne
> de latence effective est `valves.max_latency_ms` (vérifiée à la finalisation,
> *post-check*), pas l'`adaptive_policy`. Conservé dans l'artefact pour parité de
> config, mais sans effet runtime sur le walker.

**AdaptivePolicy** (`AdaptivePolicy.triggers`, lue par `_dag_should_stop`) :
l'artefact propose `triggers = { "cost_above": 0.15, "latency_above_ms": 45000 }`.
Seul `cost_above` est actif (hard-stop coût au niveau du DAG) ; `latency_above_ms`
est documentaire (cf. avertissement ci-dessus).

---

## 5. Conditions / seuils du verdict (DSL `condition.py`)

DSL autorisé (`backend/app/services/run_engine/condition.py`) : `and/or/not`,
`== != < <= > >= in "not in"`, noms ctx nus, `ctx.key`, `<namespace>.<key>`.
**Aucun** appel de fonction ni subscript.

| Décision | Branche | Condition | Variables (via `inputs_map`) |
|---|---|---|---|
| `route_mode` | `fast` | `mode == 'fast'` | `mode` ⇐ `plan.thinking.mode` |
| `route_mode` | `deep` | `mode == 'deep'` | idem |
| `verdict` | `weak` | `composite < 70 or hallucination_rate > 0.15 or context_count == 0` | ⇐ `response_eval.{composite, hallucination_rate, context_count}` |
| `verdict` | `strong` | `composite >= 70 and hallucination_rate <= 0.15 and context_count > 0` | idem |
| `egress_gate` | `review` | `action == 'answer' and composite < 40` | `action` ⇐ `plan.action` ; `composite` ⇐ `response_eval.composite` |
| `egress_gate` | `ok` | `action != 'answer' or composite >= 40` | idem |
| `deliver` | `clarify` | `action == 'clarify'` | `action` ⇐ `plan.action` |
| `deliver` | `reject_oos` | `action == 'reject_oos' and context_count == 0` | OOS honoré **uniquement** si retrieval vide (backstop §0bis/P2) |

**Résolution des variables — pas de `ctx` bleed (bug P1 #7 corrigé).** Le DSL
résout d'abord depuis `node_input` (overlay `inputs_map`), puis `ctx`
(`condition.py` : `ctx_with_input = {**ctx, **node_input}`). Chaque décision **tire
explicitement** ses variables du `VariablePool` via `inputs_map`, donc la valeur
testée est **déterministe** et indépendante de ce qui a « bavé » dans le `ctx` par
fusions amont.

**Formule de confiance d'égress (post-answer).** L'ancienne porte testait
`confidence < 0.4` où `confidence` était la confiance **pré-answer** du planner
(bavée dans le `ctx`). Désormais :

```
confidence_egress ≡ response_eval.composite / 100      # composite ∈ [0,100]
review  ⇔  action == 'answer'  AND  composite < 40      # i.e. confidence < 0.40
```

`composite` est émis par `response_eval_v1` (ResponseEvaluator ×100, §7) **après**
génération — c'est une mesure de la *réponse produite*, pas du plan. La porte ne
s'arme que pour `action == 'answer'` (inutile sur clarify/reject_oos).

**Échelle du composite — source unique (bug P1 #6 corrigé).** Le seuil `composite < 70`
du verdict est sur l'échelle **0-100**. La **seule** source autoritative est
`task.response_eval` (`response_eval_v1` = `ResponseEvaluator` dont les scores 0-1
sont ×100). `eval_radar_v1` émet aussi un `overall` 0-100 et un `hallucination_rate`,
mais le verdict **ne lit que** `response_eval` (via `inputs_map`) ⇒ zéro ambiguïté
d'échelle, zéro collision de merge. (`join.eval` liste `response_eval` en dernier,
donc même dans le *bundle* fusionné c'est sa valeur de `hallucination_rate` qui prime.)

---

## 6. Knobs pour challenger l'A/B

Leviers à exposer (toggles System settings / params) pour le test A/B :

| Knob | Où | Effet |
|---|---|---|
| **agentic on/off** | choix du System (`chat_agentic_thinking_v1` vs `chat_transverse_v1`) | bascule entre le DAG agentique et le `/chat` classique |
| **coût eval (fan-out)** | `fork.self_eval` + arêtes vers `eval_radar`/`claim_audit`/`response_eval` | **knob de coût** : variante COMPLÈTE = 3 juges parallèles. Variante légère = garder `response_eval` seul (les conditions du verdict n'ont besoin que de lui) ⇒ ~⅓ du coût d'éval |
| **modes autorisés** | `route_mode.config.branches` (+ défaut) | restreindre à `fast` seul, ou autoriser `deep` |
| **seuils verdict** | `decision.verdict` (`70`, `0.15`) | sévérité de l'auto-correction (qualité vs latence) |
| **max_passes** | `valves.circuit_breaker.max_passes` | nombre de passes de correction (1 passe câblée via `task.self_correct` ; la valve plafonne) |
| **clarify / reject_oos on/off** | `decision.deliver` branches `clarify`/`reject_oos` | activer/désactiver la demande de clarification ou le refus hors-périmètre |
| **action self_correct** | `chat_self_correct_v1` (`escalate_deep`/`translate`/`declare_partial`) | éventail de réparation (la skill choisit l'action) |
| **max_latency_ms** | `valves.max_latency_ms` (post-check) | budget latence. ⚠️ `adaptive_policy.triggers.latency_above_ms` est **inerte** (§4) |
| **gate confiance** | `egress_gate` (`composite < 40` ≡ conf < 0.40, post-answer) ; `valves.mandatory_hitl_if_confidence_below` (`0.35`, backstop) | agressivité de l'escalade HITL |

---

## 7. Skills à construire — contrats d'I/O FIGÉS (avant tout seed réel)

Trois skills restent **à construire** ; leurs contrats sont **figés** ci-dessous et
**alignés sur les ports des nœuds** de l'artefact. Toutes sont **provider-neutres :
elles DOIVENT résoudre leur client via `ModelRouter.get_client({"provider","model"})`
— jamais instancier en dur un client provider** (`OpenAIClient`/`OllamaClient`/…).

1. **`chat_agentic_plan_v1`** *(planner, neutre)* — le planner **émet** `model_tier`
   (`fast` / `balanced` / `strong`) ; le modèle servi est décidé par la politique
   workspace (`routing_policy.resolve_model`), pas par le planner. `system.default_model`
   reste un pin (priorité 2).
   **GATE clarify (fix C3)** : `_coerce_plan` rejette les `scope_hint`/
   `clarifying_question` recopiant un placeholder de schéma et rétrograde
   `clarify → answer` dès qu'un code projet/identifiant est présent ou que la
   requête n'est pas réellement ambiguë (`_assess_clarify_gate`).

   ```jsonc
   // OUT (ports typés du nœud plan.thinking)
   {
     "action": "answer | clarify | reject_oos",
     "mode": "fast | balanced | deep",
     "answer_profile": "string",          // ex: technical, synthesis
     "scope_hint": "string",              // périmètre de recherche
     "clarifying_question": "string",     // si action == clarify
     "oos_reason": "string",              // si action == reject_oos
     "lang_target": "string",             // ex: fr
     "confidence": 0.0,                   // confiance PRÉ-answer (info only — PAS la garde d'égress)
     "model_tier": "fast | balanced | strong",  // émis par le planner ; le modèle est choisi par la politique workspace
     "retrieval": {                       // ⇐ consommé par les retrieve_* via inputs_map (bug P0 #1)
       "latency_profile": "fast | balanced | deep",
       "retrieval_profile": "oracle_fast | chat | deep_async",
       "top_k": 6,
       "rag_pipeline_mode": "chah | auto",
       "deep_retrieval": false
     }
   }
   ```

2. **`chat_self_correct_v1`** *(auto-correction 1 passe, neutre)* — `model` ⇐
   `system.default_model`. Réacteur borné : choisit **une** action
   (`escalate_deep` / `translate` / `declare_partial`). **`escalate_deep` =
   re-retrieve-or-abstain** : re-recherche `deep` (requête originale via
   `scope_hint`) puis re-ancre sur le nouveau contexte, sinon abstention — **jamais
   de génération libre** (fix C2). `translate`/`declare_partial` ne transforment que
   le brouillon déjà ancré. IN : `+scope_hint, +lang_target, +answer_profile`.

   ```jsonc
   // OUT (ports du nœud task.self_correct)
   { "answer": "string", "citations": [], "action_taken": "escalate_deep | translate | declare_partial" }
   ```

3. **`response_eval_v1`** *(wrapper de `ResponseEvaluator`)* — **SOURCE UNIQUE** du
   composite 0-100. Construit dans `skills_registry/wrappers.py` autour de
   `app.services.metrics.evaluator.ResponseEvaluator` (scores 0-1 → ×100).

   ```jsonc
   // OUT (ports du nœud task.response_eval)
   {
     "composite": 0,            // 0-100  ==  ResponseEvaluator score ×100   ← AUTORITATIF
     "hallucination_rate": 0.0, // 0-1
     "context_count": 0,        // nb de chunks fournis
     "hhem": 0.0, "factuality": 0.0, "coherence": 0.0   // 0-1, info
   }
   ```

**Skills existantes — ports alignés sur les wrappers réels** (pas à construire,
juste à câbler ; `skills_registry/wrappers.py`) :

- `semantic_search_v1` → `{results: [...], raw_chunks_retrieved, …}` ; honore les
  overrides `latency_profile`/`retrieval_profile`/`top_k`/`deep_retrieval` **depuis
  le payload** (d'où l'`inputs_map`) ; **résout `workspace_slug`** depuis l'`id`
  (fix C1) ; défaut lane `balanced` (plus de `"fast"` hardcodé). RETRIEVAL-ONLY.
- `llm_rag_answer_v1` → `{answer, citations, decision_steps, meta}` ; **CONSOMME le
  tableau `context`** (= `join.retrieval.results`) → synthèse ancrée, sinon
  abstention ; fallback orchestrateur (slug résolu) si aucun `context` fourni.
- `eval_radar_v1` (`:240-257`) → `{axes, overall, hallucination_rate, drift_rate, note}`.
- `claim_audit_v1` (`:260-281`) → `{claims, verdict, supported, unsupported}`.

**Nœuds RETIRÉS vs le scaffold initial :**

- **`chain_mixed_hah_v1`** (bug P1 #5) — émettait une **réponse complète** (hétérogène
  avec les chunks de `semantic_search_v1`). Les 3 branches sont désormais
  **retrieval-only** (`semantic_search_v1` → `results`) avec une **génération unique**
  (`task.generate`), évitant la double génération. La pipeline RAG choisie est passée
  via `rag_pipeline_mode` ⇐ `plan.retrieval`.
- **`task.ground_policy` / `chat_grounding_policy_v1`** (bug P1 #8) — **stub
  non-exécutable en run** (`wrappers.py:1894`). Hop mort supprimé ; le grounding est
  **interne à `llm_rag_answer_v1`**.
- **`loop.self_correct`** (bugs P0 #2/#4) — remplacé par un **`task`** car la sortie
  `loop` `{iterations, count}` n'exposait pas `answer` proprement au sink.

4. **Palette d'édition incomplète** — `retry`, `hitl`, `subflow` ne sont pas dans la
   palette du Flow Builder : ces nœuds s'autorisent uniquement par **authoring JSON /
   seed manuel** (le présent artefact). Le `hitl.expert_review` est donc à seeder à
   la main pour l'instant.

5. **Résolution `skill_id`** — l'artefact met `config.skill_id = null`. Au seed, il
   faut résoudre chaque `skill_slug` → `Skill.id` (cf. `_skill_lookup` /
   `node(...)` dans `bootstrap.py`). Le run engine n'a besoin que du `skill_slug`,
   mais le manifeste / Flow Builder utilisent `skill_id`.

### Comment seeder (le moment venu — NE PAS faire ici)

Deux options, alignées sur l'existant :

- **Option A — migration Alembic** (modèle : `backend/alembic/versions/047_andritz_membrane_spec.py`).
  Une nouvelle révision `0XX_andritz_chat_agentic` qui : (a) crée le `System`
  (`workspace.slug == "andritz"`), charge `flow_definition` depuis le JSON et résout
  les `skill_id` ; (b) crée un `ControlPolicy` `scope="system"`,
  `extra={"membrane_origin": "...", "membrane_spec": <membrane_spec>}` et le binde
  via `System.control_policy_id` (exactement le pattern 047) ; (c) `downgrade`
  idempotent marqué par `membrane_origin`.

- **Option B — hook bootstrap** (modèle : `ensure_*_system_default` dans
  `backend/app/services/systems/bootstrap.py`). Un
  `ensure_chat_agentic_system_default(db, workspace_id)` idempotent qui lit ce JSON,
  résout capability + skills, et upsert le `System` au boot. Plus simple à itérer,
  mais ne pose pas la `ControlPolicy` membrane (à coupler avec un helper dédié).

> **Recommandation** : Option A (migration type 047) pour le couple
> System + membrane authoritative en une transaction reproductible et réversible.

---

## 8. Indépendance vis-à-vis du provider modèle

**Principe.** L'architecture/orchestration ne dépend **jamais** d'un provider de
modèle. Objectif : un passage *full on-prem* sans toucher au graphe — uniquement
de la config. La dépendance à un provider est confinée à **une seule couche
feuille**, sous trois niveaux nettement séparés :

1. **Orchestration `run_engine` = provider-agnostique.** `execute_run_dag()` et le
   walker (`backend/app/services/run_engine/dag.py`) ne connaissent que des
   `skill_slug` neutres, des décisions, des forks/joins et la membrane. Aucun nom
   de provider/modèle n'apparaît dans la logique d'orchestration. Le moteur se
   contente de *seeder* le modèle par défaut dans le contexte
   (`engine.py` `_build_initial_ctx` ~262-270 : `default_model`) et dans le pool
   sous `system.default_model` (`dag.py` `_seed_pool` ~1548-1567).

2. **Couche de routage `ModelRouter` / `ModelClient`.**
   `backend/app/services/model_router.py` expose
   `ModelRouter.get_client(preferences={"provider", "model"})` avec une
   `fallback_chain` ; **Ollama est toujours disponible** (client initialisé
   inconditionnellement), OpenAI/Anthropic seulement si la clé API est présente.
   L'interface commune est l'ABC `ModelClient`
   (`backend/app/services/model_clients/base.py`), implémentée par
   `ollama_client.py` / `openai_client.py` / `anthropic_client.py` (+ providers
   additionnels sous `backend/app/llm/providers/`, p.ex. `aws_bedrock_provider`).
   C'est *ici*, et nulle part ailleurs dans le graphe, que le choix de provider
   est arbitré (préférence → santé → fallback).

3. **Skills feuilles = seul endroit où un provider est nommé.** Les wrappers
   `azure_llm_v1` (→ `OpenAIClient`) et `ollama_llm_v1` (→ `OllamaClient`)
   (`backend/app/services/skills_registry/wrappers.py:1783-1836`, registre
   `:1966-1967`) sont les **seuls** artefacts qui citent un provider. Ce sont des
   *feuilles* d'implémentation, pas des nœuds du flow agentique.

**Conséquences pour ce flow (à respecter).**

- Le `flow_definition` **ne nomme jamais un provider**. Les nœuds LLM
  (`plan.thinking`, `task.self_correct`) bindent des **skills neutres**
  (`chat_agentic_plan_v1`, `chat_self_correct_v1`) qui, en interne, appellent
  `ModelRouter.get_client(...)` — **jamais** un client provider instancié en dur.
- Le **tier** est décidé par le planner (`plan.thinking.model_tier`, défaut dérivé
  du `mode` : deep/multihop → `strong`, sinon `balanced`). Le **modèle** est
  décidé par `routing_policy.resolve_model` : pin System (`inputs_map.model`) >
  `llm_portal.routing.tiers[tier]` > défaut workspace > `Settings.default_model`,
  puis filtre `capabilities.allowed_models` de la `MembraneSpec`. La gate
  membrane reste le backstop. `allowed_models = []` ⇒ non restreint.
- **Le passage on-prem est de la config, zéro changement au graphe** : on règle
  les tiers (`fast` / `balanced` / `strong`) et le défaut workspace dans le
  portail Modèles, ou `LLM_PROVIDER` / `default_model` ; le DAG, les décisions
  et la membrane restent identiques.

**Exemple on-prem (full local, sans cloud).**

```jsonc
// MembraneSpec.capabilities — borne la gouvernance des modèles
"allowed_models": ["ollama:deepseek-r1:14b"]
```

```bash
# Config d'environnement / déploiement
LLM_PROVIDER=ollama
# System.default_model (seedé dans le pool sous system.default_model)
system.default_model = "ollama:deepseek-r1:14b"
```

Avec cette seule config, `chat_agentic_plan_v1` / `chat_self_correct_v1`
résolvent un `OllamaClient` via `ModelRouter` (Ollama toujours dispo, aucune clé
cloud requise) — **le graphe `andritz_chat_agentic_v3` n'est pas modifié**.

> **À éviter** : binder une skill feuille provider-spécifique (`azure_llm_v1`)
> sur un nœud du flow, ou poser `allowed_models = ["gpt-4o", …]`. Cela
> recouplerait l'orchestration à un provider et casserait le passage on-prem.

---

## 9. Vérification — validation structurelle **+ simulation runtime**

Au-delà du validateur structurel, le flow a été **exécuté** par `execute_run_dag`
contre le schéma v3 réel (venv backend, SQLite), skills **mockées** déterministes
respectant les contrats §7. Script jetable, supprimé après run.

### 9.1 Validation structurelle

- `dag_validator.validate_flow` → **0 error, 0 warn**.
- `DagGraph.from_flow_definition` → **22 nœuds, 27 arêtes**, racine unique
  `source.request`. `should_use_dag(system)` → **True**.
- `membrane_spec` → round-trip `MembraneSpec.from_dict(..., authoritative=True)` OK ;
  `allowed_skills` **== exactement** les 7 skills du graphe ; `allowed_models = []`.

### 9.2 Simulation runtime (6 scénarios)

Pruning vérifié empiriquement (la base du pattern §2) : **une décision ne neutralise
que l'enfant direct** ; la *queue* multi-nœuds d'une branche tuée s'exécute — d'où le
routage de livraison en fin de graphe vers des sinks-feuilles.

| Scénario | Chemin pris | Sink terminal reçoit | Assertions |
|---|---|---|---|
| **(a) strong** | verdict=`strong`, egress=`ok`, deliver=`deliver` | `answer="DRAFT_ANSWER"`, citations, mode, composite | `self_correct` **non invoqué** ; `generate` a reçu `context` ; **aucun** `clarifying_question`/`reason` ✅ |
| **(b) weak→correct** | verdict=`weak`, deliver=`deliver` | `answer="CORRECTED_ANSWER"` | `self_correct` **invoqué** ; la **correction écrase** le brouillon dans `join.answer` ✅ |
| **(c) clarify** | deliver=`clarify` | `{clarifying_question}` **uniquement** | **aucune fuite `answer`** dans le terminal ✅ |
| **(d) reject_oos** | deliver=`reject_oos` | `{reason}` **uniquement** | **aucune fuite `answer`** ✅ |
| **(e) deep-param** | route_mode=`deep`, **1 seul** retrieve tiré | `answer` livré | `semantic_search_v1` a **reçu** `latency_profile="deep"` **et** `deep_retrieval=True` dans son payload ✅ (preuve que P0 #1 est corrigé) |
| **(f) hitl** | egress=`review` (composite=30<40) → **pause** | (après resume HITL) `answer="CORRECTED_ANSWER"` | run `hitl_pending` + `awaiting_decision` ; `resume_run_dag` reprend et **livre** ✅ |

**Résultat : `ALL CHECKS PASSED`** (les 6 scénarios + les 2 assertions deep-param +
les gardes verdict/egress). Le terminal porte en plus `chosen_branch`/`evaluations`
(métadonnée bénigne héritée du prédécesseur `decision.deliver` lors du merge du sink) —
sans impact sur les clés métier (`answer`/`clarifying_question`/`reason`).

### 9.3 Pattern de threading de la réponse (récapitulatif)

```
task.generate ──(arête #1)──┐
                            ├──► join.answer (all) ──► sink.final_answer (inputs_map.answer ⇐ join.answer.answer)
task.self_correct ─(arête #2)┘     # weak : #2 vif ⇒ écrase #1   |   strong : #2 skip ⇒ #1 conservé
```

Le `join.answer` en stratégie `all` fait un **merge ordonné** : `task.generate`
listé **avant** `task.self_correct` ⇒ sur `weak` la réponse corrigée prime, sur
`strong` (self_correct neutralisé) le brouillon reste. Le sink tire `answer`/`citations`
de `join.answer` via `inputs_map` (les décisions ne propagent pas la donnée).

> **MAJ 2026-06-26 — seedé + recâblé + grounding prouvé.** Les 3 skills
> (`chat_agentic_plan_v1`, `chat_self_correct_v1`, `response_eval_v1`) sont
> **construites** (`skills_registry/wrappers.py`), le System est **seedé (048) +
> recâblé (049)** et le correctif de grounding (§0) est **prouvé** :
> `dag_validator` 0/0, tests unitaires + simulation de data-flow verts
> (`app/tests/services/test_chat_agentic_skills.py`,
> `test_chat_agentic_dataflow.py`), et **retrieval live `raw>0`** sur AKK200
> (6 chunks balanced / 8 deep) une fois le quota OpenAI rétabli. Le scénario
> data-flow est désormais un **test pérenne** (plus un script jetable).

---

## Fichiers

- Spéc (ce document) : `docs/chat-agentic-thinking-spec.md`
- Artefact flow + membrane : `backend/app/resources/flows/andritz_chat_agentic_v3.json`
