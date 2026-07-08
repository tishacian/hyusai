# Audit de grounding — pourquoi l'agentique perd l'A/B (doc compagnon)

> Compagnon de `docs/chat-recherche-agentic-ab-2026-06-26.md`. L'A/B disait « l'agentique perd »
> (composite −5.9, halluc +0.063, self_correct 100 %). Cet audit ouvre le capot **cas par cas**,
> en vérifiant le grounding sur le corpus réel (Qdrant) et sur les chunks réellement remontés par
> le DAG (SkillInvocations des `run_id`). **Contrainte respectée : zéro recompute** (quota OpenAI
> épuisé = pas de génération ni d'embedding). Toute « vérité corpus » ci-dessous est un extrait
> verbatim d'un chunk Qdrant cité par `chunk_id` + document.

## 1. TL;DR — verdict en 5 lignes

1. **TUNABLE, ne PAS invalider le principe.** L'A/B est **contaminé** : sur **58/58** runs agentiques (dont les 20 de la cohorte propre), le retriever du bras B a renvoyé **`raw_chunks_retrieved = 0`** — aucun chunk réel du corpus. Le bras B n'a jamais exécuté de RAG : il a *généré sans contexte*.
2. **Levier #1** : réparer le retrieval du DAG (le bras B n'embed jamais la requête : `embedding_ms = null`, `qdrant_ms = null`, `raw_chunks_retrieved = 0` partout) **et** faire que `task.generate` **consomme** `join.retrieval.results` au lieu de re-retrieve (il l'ignore aujourd'hui).
3. **La cause des divergences factuelles** n'est pas « une recherche agentique moins bonne » : c'est **une recherche agentique vide**. Le brouillon honnête (« aucune source indexée ») est ensuite **réécrit en hallucination confiante** par `self_correct` (action `escalate_deep` qui **ne re-retrieve pas**).
4. **La cause des relances `clarify`** est le planner (gpt-4o-mini) qui renvoie `action=clarify` + un `scope_hint` égal au **placeholder du schéma** (`"perimetre de recherche"`) sur des questions pourtant claires (QMS-12, D.60, ACJ200…).
5. Le verdict `weak` (composite<70) n'est **pas** un faux positif : il détecte correctement le non-grounding (retrieval vide → composite ~50-62). Le défaut est le **remède** (réécriture libre) et le **fait que le bras B n'a jamais retrouvé de contexte**.

## 2. Méthode & sources de vérité (no recompute)

- **Runs durables en base.** `/tmp/ab_clean.jsonl` a disparu (purge `/tmp`), mais les runs sont en DB : workspace `andritz` (`0cce0bee-…`), System « Andritz Chat Agentic » (`874211ee-…`, `active`, `default_model=gpt-4o-mini`, variant `chat_agentic_thinking_v1`), **56 `Run(trigger=ab_spike)` + 2 warmup**, fenêtre **2026-06-25 16:49→17:43**. Chaque cas est rattaché à son `run_id` par matching de `Run.input_ref.query`. Les 20 cas de la cohorte propre sont les runs `completed`.
- **Chunks réellement remontés par le DAG.** Lus dans `SkillInvocation.output_ref` (`semantic_search_v1.results`, `llm_rag_answer_v1.meta`, `response_eval_v1`, `chat_self_correct_v1.action_taken/answer`, `chat_agentic_plan_v1`). Aucune ré-exécution.
- **Vérité corpus via Qdrant, sans OpenAI.** Collection physique `andritz__andritz-notices-techniques-spl-pilot__hybrid_1780665866` (**1 569 384** points = le `chunk_count` vu dans le scope des runs ; dense `size=1536` COSINE, sparse activé). Vérification par **scroll + filtre payload** (`project_code`) + **full-text `MatchText` sur `content`** (index texte multilingue déjà présent, cf. `qdrant_db.py:_content_text_index_schema`). Ces requêtes n'embeddent rien.
- **Référence de parité (classic).** L'A/B classic = `AgentOrchestrator.process_request` (+ `_apply_retrieval_budget_policy`) ; ses réponses contiennent des **valeurs exactes du corpus** (« 0,3 m », « SINAMICS G120 ») → il a retrouvé de vrais chunks, dans la même fenêtre.

## 3. Découverte centrale — le bras B a tourné avec un retriever VIDE

Mesuré sur **toutes** les invocations `llm_rag_answer_v1` (57/57) et confirmé sur `semantic_search_v1` :

| Indicateur (meta retrieval / stage_timings) | Valeur observée | Sur combien de runs |
|---|---|---|
| `raw_chunks_retrieved` | **0** | **57 / 57** |
| `document_chunks_retrieved` | **0** | 57 / 57 |
| `stage_timings.embedding_ms` | **null** | 57 / 57 |
| `stage_timings.qdrant_ms` / `sparse_ms` | **null** | 57 / 57 |
| `chunks_retrieved` (= lignes synthétiques uniquement) | 1 à 10 | 57 / 57 |
| erreurs / `fallback_reason` / trace 429 | **aucune** | 0 / 57 |

Les seules « lignes de contexte » que le DAG a jamais vues sont **synthétiques** :
- le stub `Knowledge guide: ANDRITZ Notices Techniques SPL` (`score=0.01`, pas de `document_filename`, pas de `chunk_id`) ;
- le pseudo-chunk `retrieval-exact-match-guardrail` (« No retrieved source matched the requested identifier ») ;
- des pseudo-chunks `Document analysis evidence: document_warning`.

`raw_chunks_retrieved = 0` + `embedding_ms = null` partout, **sans aucune erreur ni 429 enregistrée**, alors que (a) le corpus contient les réponses (§4) et (b) le classic les a retrouvées dans la même fenêtre → **le wiring de retrieval du bras B est défectueux : il ne franchit jamais l'étage embedding+dense+sparse.** (Je ne peux pas, sous contrainte no-recompute, exclure formellement une coupure embeddings *silencieusement avalée* pendant toute la fenêtre du bras B ; les deux hypothèses mènent à la même conclusion et au même correctif. Le quota épuisé empêche seulement de *re-confirmer maintenant*.)

**Conséquence méthodologique : l'A/B compare classic AVEC retrieval vs agentique SANS retrieval. Le −5.9 / +halluc n'est donc pas une propriété du principe agentique, mais l'empreinte d'un retriever vide sur le bras B.**

## 4. Tableau par cas (grounding)

`porteur agentic ?` = le bras B a-t-il remonté le chunk porteur ? Réponse uniforme **NON** (`raw_chunks_retrieved=0`).

| id | valeur classic | valeur agentic (livrée) | vérité corpus (chunk_id · doc · extrait verbatim) | qui a raison | porteur classic ? | porteur agentic ? | cause DAG |
|---|---|---|---|---|---|---|---|
| `demo_pass_akk200_width_speed` | 0,3 m / 10-20 m/min | **2,5 m / 600 m/min** | `50a149bf-0940-5f74-b92e-0a6195224add_chunk_0` · `AKK200…section_II__II.2.html` · « **Working width 0.3 m** … Mechanical speed 50 m/min … **Production speed 10 to 20 m/min** » | **classic** (agentic = fabrication) | oui (verbatim) | **non** | retrieval vide → brouillon honnête → `self_correct=escalate_deep` **fabrique** 2,5 m/600 |
| `demo_fail_akk200_de` | 0,3 m / 10-20 m/min | **1,6-3,2 m / 50-150 m/min** | idem `50a149bf…chunk_0` | **classic** | oui | **non** | idem (fabrication *différente* du cas FR → preuve d'hallucination pure) |
| `demo_fail_cu250s2_role` | Siemens **SINAMICS G120** Control Unit | « module **Andritz** hydraulique/fluides » (halluc=1.0) | `e63cf052-160e-5fee-aac1-dea4d17a9fd9_chunk_45` (BIO100) · « Converter with the **CU250S-2 Control Unit (vector)** … Permissible encoders: Resolver, HTL, TTL… » ; `04b9b022…chunk_3007` (CMX200) · « **SINAMICS G120 Control Units CU250S-2 List Manual (LH15)** » | **classic** (agentic = hallucination) | oui | **non** (seul guardrail) | retrieval vide → `self_correct` fabrique « Andritz hydraulique » |
| `reg_transversal_uraca` | liste exhaustive de projets (BHX100, AKI500…) — judge halluc=1.0 | « secteur pétrole/gaz, nettoyage HP » (générique) — halluc=0.0 | URACA présent sur **102 `project_code` distincts** dans un échantillon de 400 chunks (BHX100, AVA700, AKI500, TNX100, BCX300, ACJ200, ORL310…) ; docs « …URACA - HP pumps… » | **classic grounded** ; agentic **évasif** (générique, ni faux ni étayé) | oui (inventaire) | **non** | retrieval vide → agentic reste générique ⇒ halluc=0 par **évasivité**, pas par exactitude (paradoxe résolu) |
| `demo_fail_etachrom_spares` | composants (corps, roue, O-ring, garniture méca, bagues d'usure, chemise…) | « consulter la documentation » (aucune liste) | `048b3cf2-e119-5705-9b03-5f907d70aff9_chunk_74` · `BFG100…MES ETACHROM.pdf` · « Pump casing, Intermediate piece, Discharge cover, Pump foot, **Impeller, O-ring, Mechanical seal, Casing wear ring** suction/discharge side, **Shaft sleeve**, Part No. 101 132 163 182.2 230 412.1 433 502.1 502.2 523 » ; `f29fdd1c…chunk_8026` (ESW200 parts manual, « Etachrom BC … impeller clearances ») | **classic grounded** ; agentic punté | oui | **non** | retrieval vide → abstention generique |
| `demo_pass_qms12_function_en` | QMS-12 = système traversant (grammage, humidité, épaisseur) | **question de clarification** | `a1619d2b-893e-5dea-8d9d-40a5d4ea53a0_chunk_7` (BHX100) · « Qualiscan® QMS–12 … measuring bridges … Sensors: Aqualot AMF Moisture, Calipro DML thickness, **Gravimat DFI Basis weight**, FMX/Infralot Basis weight Moisture… » | **classic** | oui | **non** | retrieval vide **+ planner `action=clarify`** (`scope='perimetre de recherche'` = placeholder) → `deliver:clarify` |
| `demo_fail_qms12_de` | QMS-12 décrit (FR) | **clarification** | idem `a1619d2b…chunk_7` | **classic** | oui | **non** | idem (planner clarify) |
| `demo_fail_german_generic` | planning maintenance AKK200 (PIT, Bandfilter, Flotation) | **clarification** | `94cd184c-290f-53fd-887b-8e5db2f4575d_chunk_0` · `AKK200…Filtration_vacuum_maintenance.html` · « SUB-SECTION IV : MAINTENANCE … **IV.3 Table for filtration and vacuum circuit maintenance** » (+ `HP_maintenance.html`) | **classic** | oui | **non** | retrieval vide + planner clarify |
| `demo_d60_greasing` | 40 g (1er graissage + Graissage 3) | **clarification** | non re-épinglé par full-text (donnée de **table** ; classic cite [1][3][4]) ; corpus contient les notices moteur/graissage. **Non contredit** | classic (probable, sourcé) ; agentic punté | probable | **non** | retrieval vide + planner clarify |
| `demo15_acj200_residual_risks` | risques résiduels + consignes (produits chimiques, remise en place gardes) [4 p.2-28] | **clarification** | corpus ACJ200 présent (manuel ACJ200 indexé ; cf. `demo_pass_acj200_carde`). Le retrieve a renvoyé 10 lignes mais **toutes `document_warning`/guardrail** (`raw=0`) | classic grounded ; agentic punté | oui | **non** | retrieval vide (10 pseudo-chunks) + planner clarify |

> Les 10 autres cas de la cohorte suivent le même mécanisme : voir l'A/B pour le texte ; côté agentique, `raw_chunks_retrieved=0` est **universel**.

## 5. Divergence de retrieval — preuves concrètes (4 cas)

### 5.1 `demo_pass_akk200_width_speed` — la preuve marquante
- **Plan** (`chat_agentic_plan_v1`) : `action=answer, mode=fast, scope_hint='système AKK200 Nonwoven'`.
- **`semantic_search_v1`** : `n_results=1`, et l'unique « résultat » = stub *Knowledge guide* `score=0.01` (pas de doc, pas de chunk). `retrieval_scope` détecte pourtant bien `collections=['andritz-notices-techniques-spl-pilot']`, `filters={project_code:['AKK200']}`, conf 0.85 — **le scope marche, le retrieval ne ramène rien** (`raw_chunks_retrieved=0`, `embedding_ms=null`).
- **`llm_rag_answer_v1`** (re-retrieve interne, **ignore** le contexte du join) : 0 citation, brouillon = « **Aucune source indexée ne contient d'informations spécifiques sur la largeur de travail et la vitesse de production du système AKK200** ». Honnête, non hallucinant.
- **`response_eval_v1`** : composite **54.09**, halluc **0.61**, ctx_count **1** → `verdict=weak` (correct : le contexte EST vide).
- **`chat_self_correct_v1`** (`escalate_deep`, **sans re-retrieval**) : réécrit en « **largeur de travail de 2,5 mètres et vitesse jusqu'à 600 m/min** » → **hallucination**, livrée.
- **Corpus** : `50a149bf…chunk_0` (AKK200 II.2.html) = « Working width **0.3 m** / Production speed **10 to 20 m/min** » → exactement la réponse classic. Le bras B n'a jamais touché ce chunk.

### 5.2 `demo_fail_cu250s2_role` — hallucination de rôle
- `semantic_search_v1` : 2 résultats, **tous deux synthétiques** (`retrieval-exact-match-guardrail` `score=1.0` + Knowledge guide `0.01`). `selected_sources=[{source:'retrieval-exact-match-guardrail'}]`, `exact_match_guardrail_inserted=true`, `raw_chunks_retrieved=0`.
- Brouillon honnête → `self_correct` → « module **Andritz** de traitement des fluides/hydraulique » (halluc=1.0).
- Corpus sans ambiguïté : `e63cf052…chunk_45` / `04b9b022…chunk_3007` = **CU250S-2 = Control Unit (vector) des variateurs Siemens SINAMICS G120**. Classic correct.

### 5.3 `reg_transversal_uraca` — le « paradoxe » expliqué
- Agentique (`mode=fast`) : `raw=0` → réponse **sectorielle générique** (« hydrostatique, nettoyage industriel, pétrole/gaz ») ⇒ le juge note halluc=**0.0**. Mais c'est de l'**évasivité**, pas de la connaissance : aucune liste de projets.
- Corpus : URACA sur **102 `project_code` distincts** (échantillon 400 chunks) ⇒ la liste classic est **réellement ancrée** (le judge halluc=1.0 sur classic pénalise la *longueur*/sur-énumération, pas l'existence). Conclusion : l'agentique « évite l'hallu » en **ne répondant pas**.

### 5.4 `demo_pass_qms12_function_en` — relance injustifiée
- Plan : `action=clarify, scope_hint='perimetre de recherche'` (le **placeholder littéral** du prompt, cf. `wrappers.py:_build_plan_prompt`). gpt-4o-mini recopie le schéma.
- `deliver:clarify` ⇒ la réponse livrée = la question de clarification, alors que `self_correct` avait (inutilement) régénéré un texte. **Travail jeté.**
- Corpus : `a1619d2b…chunk_7` décrit complètement le QMS-12. Question parfaitement répondable ; classic répond.

## 6. Causes racines classées + levier de tuning précis

| # | Cause racine (preuve) | Levier précis (fichier · param/condition) |
|---|---|---|
| **C1 — retrieval bras B vide (dominante)** | `raw_chunks_retrieved=0`, `embedding_ms/qdrant_ms/sparse_ms=null` sur **58/58** runs ; corpus contient les données ; classic les retrouve | (a) `task.generate` doit **consommer** `join.retrieval.results` : `wrappers.py:_llm_rag_answer_v1` (≈L144-174) **ignore** `context` et re-retrieve → passer le contexte fourni au lieu de re-chercher. (b) Aligner la requête de `wrappers.py:_semantic_search_v1` (≈L177-221) sur le chemin orchestrateur : il **hardcode `latency_profile="fast"`** (L192) et n'envoie ni `candidate_pool_k`/`synthesis_k` ni la `grounding_policy` que `_apply_retrieval_budget_policy` pose côté classic — l'étage embedding+dense est court-circuité. (c) **Re-confirmer dès quota rétabli** que `raw_chunks_retrieved>0` avant toute autre mesure. |
| **C2 — self_correct fabrique** | brouillon « aucune source » → final « 2,5 m/600 m/min » ; `_chat_self_correct_v1` construit un prompt **query+draft seulement, sans contexte** ; `escalate_deep` **ne ré-escalade pas la recherche** | `wrappers.py:_chat_self_correct_v1` (≈L2110-2182) + `_pick_self_correct_action` (L2126) : faire que `escalate_deep` **relance réellement `retrieve_deep`** (requête originale, sans réécriture/narrowing), régénère **ancré** sur le nouveau contexte ; si toujours vide ⇒ **forcer `declare_partial`/abstention**, **jamais** de génération libre. (Levier #1 anti-hallucination.) |
| **C3 — planner sur-déclenche `clarify` + placeholder** | `action=clarify` + `scope_hint='perimetre de recherche'` sur QMS-12/D.60/ACJ200/german_generic (questions claires) | `wrappers.py:_chat_agentic_plan_v1` / `_build_plan_prompt` (L2014) : (a) **gater `clarify`** derrière le détecteur déterministe déjà présent `agentic_chat_spike.py:assess_sufficiency()` (clarify seulement si `ambiguous`/pas de `project_code`) ; (b) rejeter les plans qui **recopient les placeholders** du schéma (`_coerce_plan`, L2045) ; (c) **défaut `answer`** dès qu'un code projet/identifiant est présent ; (d) planner > gpt-4o-mini ou few-shot. |
| **C4 — route `fast` sur questions factuelles** | plan `mode=fast` sur akk200/etachrom/uraca → `fast_scoped_dense` (`cross_encoder_status=skipped_fast`) | `flows/andritz_chat_agentic_v3.json` (`decision.route_mode`, défaut `balanced`) + prompt planner (L2038) + `_RETRIEVAL_BY_MODE` (L1908) : **interdire `fast`** pour factuel/exact-id/extraction de valeur ; **défaut `balanced`** ; `fast` réservé au trivial. |
| **C5 — échelle du verdict (déjà identifiée)** | composite interne ResponseEvaluator ~0.5-0.62×100 < 70 ⇒ `weak` quasi systématique | `flows/…v3.json:decision.verdict` (`composite<70`) : recalibrer à **~55-60** OU porter le verdict sur `hallucination_rate>0.15 || context_count==0` (composite en tie-breaker). **Mais** : ne corrige rien tant que C1/C2 ne sont pas faits (le `weak` est *correct* ici). |
| **C6 — parité budgets generate vs classic** | generate tourne en `latency_budget.profile=fast` (top_k 6, candidate_pool 20, synthesis 12) même quand `route=balanced` ; classic = balanced (top_k 8, synth 16, pool 40) | corrigé par C1(a) : en consommant `join.retrieval.results`, le generate hérite du budget de la route choisie (fast/balanced/deep) au lieu de re-chercher en fast — supprime aussi la **double recherche** (latence). |

Note gouvernance : **32/58** runs finissent `hitl_pending` (egress_gate `composite<40` → review) — autre symptôme du retrieval vide ; se résorbe avec C1/C5.

## 7. Recommandation finale

**TUNABLE.** Les preuves de grounding **n'invalident pas** le principe agentique : elles montrent que le bras B **n'a jamais fait de RAG** (retriever vide, 58/58). Toutes les pathologies mesurées (composite −5.9, hallucinations factuelles, spam `clarify`, latence) découlent de **C1** (+ C2/C3 qui en amplifient les dégâts). Le principe n'a donc pas été testé équitablement.

**Plan d'expériences minimal à relancer (quota rétabli, in-container) :**
1. **E0 — gate de sanité** : rejouer 3-5 cas et **asserter `raw_chunks_retrieved>0` côté bras B**. Tant que ça échoue, ne rien mesurer d'autre (tout le reste est un artefact).
2. **E1 — C1(a)** : `task.generate` consomme `join.retrieval.results` ; asserter que l'agentique cite le **même chunk** que classic sur `akk200_width` (`50a149bf…chunk_0`).
3. **E2 — C2** : `escalate_deep` = re-retrieve-or-abstain ; asserter **zéro fabrication** sur akk200 (réponse = « 0,3 m / 10-20 m/min » **ou** abstention, jamais 2,5 m/600).
4. **E3 — C3** : `clarify` gaté par `assess_sufficiency` ; asserter que `qms12_function_en` **répond** (plus de `deliver:clarify`).
5. **E4 — C4/C5** : `balanced` par défaut + recalibration verdict ; mesurer self_correct rate (cible ≪ 100 %).
6. **Re-sweep** 20 cas (puis 95) et recomparer composite/halluc/latence — c'est SEULEMENT là qu'un verdict « agentique vs déterministe » sera valide.

**Critère d'invalidation** (à n'invoquer qu'après E0-E4) : si, **avec retriever prouvé non-vide** et self_correct ancré, l'agentique reste < classic sur composite **et** halluc à latence comparable, alors invalider. Les données actuelles ne le permettent pas.

## 8. Annexe — requêtes de vérification (reproductibles, sans OpenAI)

```python
# in-container: ssh omnirag-demo "docker exec -i -w /app/backend agentium-backend python -"
from app.core.config import settings
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchText
c = QdrantClient(host=settings.qdrant_host, port=int(settings.qdrant_port),
                 https=bool(settings.qdrant_https), api_key=(settings.qdrant_api_key or None), timeout=120)
COL = "andritz__andritz-notices-techniques-spl-pilot__hybrid_1780665866"  # 1 569 384 pts, dense 1536d
# vérité AKK200 (full-text sur content + filtre projet, AUCUN embedding) :
recs,_ = c.scroll(collection_name=COL, with_payload=True, limit=8,
  scroll_filter=Filter(must=[FieldCondition(key="project_code", match=MatchValue(value="AKK200")),
                             FieldCondition(key="content", match=MatchText(text="width"))]))
# → chunk 50a149bf… II.2.html : "Working width 0.3 m … Production speed 10 to 20 m/min"
```

```python
# preuve "retriever vide" côté bras B (lecture DB, aucun recompute) :
from app.db.base import SessionLocal
from app.models.run import Run, SkillInvocation
db = SessionLocal(); WS = "0cce0bee-7e86-485d-95b1-672e82f16600"
for r in db.query(Run).filter(Run.workspace_id==WS, Run.trigger.in_(["ab_spike","ab_spike_warmup"])).all():
    inv = db.query(SkillInvocation).filter(SkillInvocation.run_id==r.id,
            SkillInvocation.skill_slug=="llm_rag_answer_v1").first()
    rp = ((inv.output_ref or {}).get("meta") or {}).get("retrieval", {}) if inv else {}
    # rp["raw_chunks_retrieved"] == 0 et rp["stage_timings"]["embedding_ms"] is None pour 57/57
```
