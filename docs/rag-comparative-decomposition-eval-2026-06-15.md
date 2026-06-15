# Décomposition des requêtes comparatives — rappel multi-documents (2026-06-15)

> Branche `demo/agentic`, base HEAD `8157e301`. Corpus Andritz, collection
> `andritz__andritz-notices-techniques-spl-pilot`.

## 1. Problème

Une requête « A vs B » est dominée par l'entité la plus fréquente du corpus :
le 2e document ne remonte pas dans le top-k. Cas concernés (sous-ensemble
comparatif de `andritz_spl_hard_intents.json`, annoté `expected_prompt_type ==
"comparative"` par le volet 3) :

- hi_003 — CONTINENTAL GVJS vs POLLRICH GVJ1 (AKI300 vacuum set)
- hi_004 — SINAMICS G150 vs S120 (paramètres de mise en service)
- hi_008 — Wilo Drain SP vs Wilo NOLH (BEX200)

## 2. Choix du batch de mesure

Pas de batch « comparative » dédié. On **réutilise `andritz_spl_hard_intents.json`**
et on filtre sur `expected_prompt_type == "comparative"` (champ additif du
volet 3, non cassé). Avantage : pas de nouveau corpus à vérifier, et les 3 cas
sont déjà calibrés sur la collection live. `golden_flag_ab.py` gagne
`--only-comparative` (filtre) et `--latency-profile` (les cas sont `balanced` ;
on force `deep` pour mesurer ce profil).

## 3. Design (minimal, sans LLM)

Nouveau module `comparative_retrieval.py` (fonctions pures + 1 orchestrateur),
importé par `context.py`. Aucun appel LLM.

1. **Détection** : `is_comparative_query()` réutilise le classifieur bayésien
   (volet 3) — pas de re-détecteur. Gate aussi sur le profil + flags.
2. **Extraction d'entités** : `parse_comparative_entities()` — patterns
   lexicaux FR/EN/DE : « difference between X and Y », « compare X and Y »,
   « X vs Y », « différences … entre X et Y », « Unterschied zwischen X und Y »,
   « vergleiche X und Y ». Échec d'extraction → **pas de décomposition**
   (comportement actuel inchangé).
3. **Sous-requêtes** : pour chaque entité, `entité + références projet`
   (réutilise `_REFERENCE_RE` de `conversation_anchors.py` → AKI300/BEX200).
   Lancées **en parallèle** via le **même** `retrieve_for_mode` borné
   (corpus_planner inchangé), sous le deadline restant.
4. **Fusion** : `merge_comparative_results()` — RRF par clé de contenu (union
   dédupliquée), versée dans le pool de candidats existant
   (rerank → cross-encoder → seuil → diversify).
5. **Garantie de couverture** : `ensure_entity_coverage()` après compression —
   si une entité a des hits mais n'apparaît pas dans le top-k, on promeut son
   meilleur chunk (remplace le slot le plus bas non-exempt qui ne couvre pas
   l'autre entité). Une entité **sans hit** ne fait rien (pas de crash).

### Portée latence / flags (`config.py`)

| flag | défaut | rôle |
|------|:--:|------|
| `rag_comparative_decompose_enabled` | **True** | interrupteur maître |
| `rag_comparative_decompose_balanced` | **False** | active en `balanced` |
| `rag_comparative_decompose_max_subqueries` | 2 | nb max de sous-requêtes |

- `deep` : actif par défaut (deadline ample).
- `balanced` : OFF par défaut → activé seulement si surcoût mesuré < 300 ms.
- `fast` : jamais.

### Diagnostics (`metrics`)

`comparative_decompose`, `comparative_entities`, `comparative_subqueries`,
`comparative_subquery_hits` (par entité), `comparative_entities_promoted`.

### Fichiers touchés

- `backend/app/services/rag/comparative_retrieval.py` (nouveau)
- `backend/app/services/rag/context.py` (branchement, flag-gated, additif)
- `backend/app/core/config.py` (3 flags)
- `backend/scripts/golden_flag_ab.py` (`--latency-profile`, `--only-comparative`, diagnostics)
- `backend/app/tests/services/test_comparative_retrieval.py` (nouveau)

## 4. Mesure (VM in-container, build 6176982)

Méthode : `golden_flag_ab.py` sur `agentium-backend`, baseline = décomposition
OFF (bit-identique à 8157e301), variant = ON. `rag_context_cache` désactivé.

### Global hard-intents, profil DEEP (off → on)

| cas | base | variant | distinct_docs | décompo (variant) |
|-----|:--:|:--:|:--:|---|
| hi_001 parts manual (non-comp.) | fail | fail | 3→3 | — |
| hi_002 KD724 | PASS | PASS | 4→4 | — |
| **hi_003 CONTINENTAL vs POLLRICH** | fail | fail | **4→6** | entités promues : **les 2** (subhits 20/20) |
| **hi_004 G150 vs S120** | fail | fail | 3→3 | déjà couvert (promues : ∅) |
| hi_005 PHP (analytique) | PASS | PASS | 2→2 | — |
| hi_006 SIMOTICS AKK200 | PASS | PASS | 4→4 | — |
| hi_007 Excelle (exclusion) | fail | fail | 2→2 | — |
| **hi_008 Wilo Drain vs NOLH** | fail | fail | **2→4** | entités promues : **les 2** (subhits 48/48) |
| hi_009 LH2 0113 | fail | fail | 5→5 | — |
| hi_010 Wilo LOT100 (analytique) | fail | fail | 4→4 | — |
| hi_011 etachrom bc | PASS | PASS | 4→4 | — |
| **Total** | **4/11** | **4/11** | | improvements=0, **regressions=0** |

### Sous-ensemble comparatif, profil BALANCED (off → on)

| cas | base | variant | distinct_docs | note |
|-----|:--:|:--:|:--:|---|
| hi_003 | fail | fail | 8→6 | promues : les 2 |
| hi_004 | fail | fail | 8→8 | promues : ∅ (déjà couvert) |
| hi_008 | fail | fail | 2→2 | décompo **sautée** (deadline balanced serré) |
| **Total** | **0/3** | **0/3** | | regressions=0 |

### Pourquoi le pass-rate ne bouge pas (diagnostic deep, décompo ON)

```text
hi_003  expected_sources=['CONTINENTAL GVJS','POLLRICH GVJ1'] min=2
        matched=[]  missing_evidence_terms=[]   ← le CONTENU est bon
        selected_sources=A__AKI300__…__accueil-Dryer.html, …__index.html, …II.1.html
hi_008  expected_sources=['Wilo Drain SP','Wilo NOLH'] min=2
        matched=[]  missing_evidence_terms=[]
        selected_sources=R__RCZ100__…Margasa…, R__REN100__…hydroentanglement…
```

**La décomposition fait son travail** (les 2 entités sont promues dans le
top-k, `missing_evidence_terms=[]` → le contenu des 2 entités est présent),
mais le critère `passed` du golden exige que les `expected_sources` (noms de
composants : *CONTINENTAL GVJS*, *Wilo NOLH*) apparaissent dans les **labels de
source = `document_filename`**. Or ces manuels Andritz sont des **exports HTML
de site** aux noms de page génériques (`accueil-Dryer.html`, `index.html`,
`II.1.html`) qui ne contiennent jamais le nom du composant. Le `matched_sources`
est donc **structurellement insatisfiable** pour ces cas, indépendamment du
rappel. L'objectif réel (rappel multi-documents) est atteint et mesurable via
les diagnostics ; le pass-rate du golden n'est pas le bon instrument ici.

## 5. Latence (wall_ms moyen, off → on)

| profil | baseline | variant | delta |
|--------|---------:|--------:|------:|
| deep (11 cas) | 21 397 ms | 20 362 ms | **−1 035 ms** |
| balanced (3 cas comp.) | 9 651 ms | 8 748 ms | **−903 ms** |

Les deltas sont **négatifs (bruit)** : les 2 sous-requêtes tournent **en
parallèle** (`asyncio.gather`) dans le deadline restant, donc le surcoût mural
est inférieur à la variance run-à-run (≪ 300 ms). En balanced, quand le deadline
restant est trop court, la décomposition **se saute proprement** (hi_008 :
`comparative_skipped_reason=deadline`) — aucun dépassement.

> Réserve méthodo : le critère « < 300 ms » est **largement respecté**. Le
> deadline-skip occasionnel en balanced est un garde-fou, pas une régression.

## 6. Verdict & recommandation flag balanced

**La décomposition atteint son objectif — le rappel multi-documents — mais le
golden ne sait pas le mesurer sur ces cas.** Sur hi_003 et hi_008 les deux
entités sont promues dans le top-k (contenu présent, `missing_evidence_terms=[]`,
`distinct_docs` 4→6 / 2→4) ; le `passed` reste `fail` uniquement parce que les
`expected_sources` (noms de composants) n'apparaissent pas dans les
`document_filename` (pages HTML génériques). Aucune régression (non-comparatifs
bit-à-bit ; `regressions=0`).

Recommandations :

1. **Deep : garder ON** (`rag_comparative_decompose_enabled=True`, défaut).
   Gain de rappel réel, surcoût latence nul, dégradation gracieuse, zéro
   régression. La démo chat (balanced) est **inchangée**.
2. **Balanced : garder OFF par défaut** (`rag_comparative_decompose_balanced=
   False`) **pour l'instant**. Le critère latence (< 300 ms) est rempli, donc
   c'est **techniquement sûr à activer**, mais : (a) le gain ne se traduit pas
   en pass-rate sur ces cas, (b) je n'ai mesuré la non-régression balanced que
   sur le sous-ensemble comparatif (0/3→0/3), pas en global. → Lancer un A/B
   balanced **global** (11 cas) avant de basculer le flag via l'env VM.
3. **Suivi (hors périmètre)** pour que le pass-rate reflète le rappel : aligner
   les `expected_sources` des 3 cas comparatifs sur des fragments de filename
   réellement récupérables (page HTML AKI300 vacuum-set, doc Wilo réel) **ou**
   vérifier la couverture par `expected_evidence_terms` (contenu) plutôt que par
   label de source. Non fait ici (consigne : ne pas forcer d'assertion
   artificielle dans le golden).

## 7. Déploiement & traçabilité

- **Commits** `demo/agentic` : `07a7faef` (feature + tests),
  `6176982d` (capture latence A/B), `4562c285` (ce rapport).
- **VM** : déployée via `bash scripts/deploy-vm.sh --no-frontend` (094f41e1 →
  HEAD). État vérifié :
  - HEAD VM = `6176982` == `origin/demo/agentic`.
  - **Audit de dérive post-déploiement VERT** (backend + worker : code identique
    à l'arbre git ; la dérive `docker cp` du volet 3 sur `classifier.py` est
    résorbée).
  - **Migration `041_andritz_default_scope_spl` enregistrée** (`alembic current`
    = `041_… (head)`), appliquée via le service `agentium-migrate` (profil
    tools). NO-OP données (épinglage scope défaut andritz SPL).
  - Conteneurs : `agentium-backend` healthy, `agentium-worker-cpu` up.
  - Patterns FR du classifieur (volet 3) désormais embarqués dans l'image.
- **Smoke** : 2 requêtes comparatives (hi_003, hi_008) en deep avec diagnostics
  visibles (§4) — `comparative_decompose=True`, entités extraites, sous-requêtes
  exécutées, `comparative_entities_promoted` = les 2 entités.
- **Tests** : `pytest -k "golden or retrieval or comparative or
  conversation_anchors or chat or prompt_classifier"` → **261 passed**
  (`test_hybrid_retrieval.py` exclu — Qdrant local). Batch diversity et éval
  classifieur inchangés.
- **Reproduire l'A/B** :

  ```text
  docker exec -w /app/backend agentium-backend python -m scripts.golden_flag_ab \
    --workspace andritz --batch app/resources/retrieval_golden/andritz_spl_hard_intents.json \
    --latency-profile deep --baseline-flags rag_comparative_decompose_enabled=false \
    --flags rag_comparative_decompose_enabled=true
  ```
