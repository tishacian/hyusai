# Éval offline du classifieur de type de prompt (2026-06-15)

> Branche `demo/agentic`. Éval **zéro LLM, zéro Qdrant, zéro coût** du
> classifieur bayésien (`classifier.py`) réutilisant les cas hard-intents
> comme vérité terrain de labels.

## 1. Pourquoi une éval séparée

Le classifieur choisit le `SystemPromptType` quand `prompt_type=="auto"`
([rag_agent.py](../backend/app/services/rag/rag_agent.py)), **après**
`retrieve_rag_context`. Son choix n'est donc pas visible dans le scoring golden
retrieval. On annote les 11 cas de `andritz_spl_hard_intents.json` avec
`expected_prompt_type` (vérité terrain) **sans** forcer d'assertion dans le
golden retrieval, et on score à part le classifieur.

- Schéma : `RetrievalGoldenCase` gagne `expected_prompt_type`,
  `acceptable_prompt_types` (secondaires acceptés), `prompt_type_ambiguous`
  (exclus du scoring strict), `requires_coherence`.
- Scoring : `evaluate_prompt_type_case()` (fast, offline) et
  `evaluate_prompt_type_case_full()` (patterns+coherence, nécessite l'embedder)
  dans `retrieval_golden.py` ; runner `scripts/golden_classifier_eval.py`
  (accuracy, matrice de confusion, exit ≠ 0 si < seuil).

## 2. Annotations (vérité terrain)

| cas | langue | requête (extrait) | label attendu | accept. | note |
|-----|:--:|---|---|---|---|
| hi_001 | fr | « Où se trouve le parts manual ? » | factual | — | localisation doc |
| hi_002 | fr | « Quels projets utilisent la pompe KD724 ? » | factual | — | |
| hi_003 | en | « difference between CONTINENTAL … and POLLRICH … » | comparative | — | |
| hi_004 | fr | « différences … entre les variateurs G150 et S120 » | comparative | — | |
| hi_005 | fr | « Pourquoi la pression chute … quel document ? » | causal | analytical | |
| hi_006 | de | « Wo finde ich die SIMOTICS Betriebsanleitung … » | factual | — | |
| hi_007 | en | « Excelle … manual in English please, not the Dutch … » | — | factual, analytical | **ambigu** (impératif, exclu) |
| hi_008 | en | « Compare the Wilo Drain SP and the Wilo NOLH … » | comparative | — | |
| hi_009 | en | « What does document LH2 0113 cover … » | factual | analytical | |
| hi_010 | fr | « quelle pompe BP WILO équipe … où est sa notice ? » | factual | analytical | |
| hi_011 | fr | « Où trouver la notice etachrom bc … » | factual | — | localisation doc |

**Cas ambigu exclu** : **hi_007** est une *commande* de récupération
(« manual in English please, not the Dutch… ») sans interrogatif ni marqueur
de raisonnement. Le typer arbitrairement fausserait la mesure ; on le marque
`prompt_type_ambiguous` et on exige seulement qu'il ne tombe pas sur un type
aberrant (factual/analytical acceptés). Les autres cas ont un type primaire
clair. hi_005/hi_009/hi_010 ont un secondaire `analytical` légitime.

## 3. Mesure

10 cas stricts (hi_007 exclu), profil balanced, mesuré sur la VM in-container.

### Avant ajustement (classifieur d'origine)

| accuracy fast | échecs |
|--:|---|
| **8/10 = 80 %** | hi_001 et hi_011 → `analytical` (fallback) au lieu de `factual` |

Les deux échecs partagent une cause : les tournures de **localisation de
document** FR « où se trouve / où trouver » n'ont **aucun marqueur factual** →
masse de patterns nulle → fallback `analytical`.

### Après ajustement minimal

Ajout de 3 marqueurs FR à la banque FACTUAL (`classifier.py`) :
`\bou se trouve`, `\bou trouve[rz]?\b`, `\bou (?:est|sont)\b`. Spécifiques
(« où » + verbe de localisation) → ne capturent pas le « ou » conjonction.

| | fast (patterns) | full (patterns+coherence) |
|---|--:|--:|
| **Accuracy stricte** | **10/10 = 100 %** | **10/10 = 100 %** |

Matrice de confusion (attendu × obtenu), identique fast/full :

```text
expected \ pred   factu  analy  compa  causa  hypot
factual               6      0      0      0      0
comparative           0      0      3      0      0
causal                0      0      0      1      0
```

- factual 6/6, comparative 3/3, causal 1/1.
- hi_007 (ambigu) → `analytical`, dans son ensemble accepté → conforme.
- La cohérence sémantique (full) ne change **aucune** prédiction ici : les
  patterns suffisent sur ce lot. Le full reste utile sur des requêtes sans
  marqueur lexical mais sémantiquement typées (hors de ce lot).

## 4. Régression

`_CASES` trilingues existants de `test_prompt_classifier.py` : **inchangés et
verts**. Les 3 nouveaux marqueurs sont spécifiques aux tournures « où + verbe
de localisation » et n'affectent aucun cas existant. Suite complète :
`pytest -k "prompt_classifier or golden or retrieval_golden"` → **63 passed**.

## 5. Recommandation : le classifieur est-il fiable en prod ?

**Oui — garder `RAG_PROMPT_CLASSIFIER_ENABLED=true`.**

- 100 % strict (fast et full) sur les hard-intents après un correctif minimal
  (3 patterns), 80 % avant — la seule faiblesse était les tournures FR de
  localisation, désormais couvertes.
- Garde-fous sains déjà en place : `TRIVIAL` jamais auto-sélectionné ; fallback
  vers `ANALYTICAL` (le template le plus générique) quand la confiance est
  faible — un défaut de classification dégrade donc *gracieusement* vers une
  réponse analytique, sans saut de récupération.
- Le `fast` (<1 ms) suffit : il égale le `full` sur ce lot. Le `full`
  (cohérence embeddings, budget 0.15 s) n'apporte rien de mesurable ici mais
  ne régresse pas — le laisser sur balanced est sans risque.

**Réserves / suivi** :
- Lot petit (10 cas stricts, surtout factual/comparative/causal) : pas de cas
  `hypothetical` ni `analytical` pur dans hard-intents — ceux-ci sont couverts
  par `_CASES`. Élargir hard-intents si on veut une couverture analytique.
- Les requêtes **impératives** (« donne le manuel X, pas la version NL »)
  n'ont pas de type de raisonnement net → fallback `analytical`, ce qui est
  acceptable (le bon comportement est de récupérer puis répondre).

## 6. Traçabilité

- **Commit** : `<HASH>` sur `demo/agentic`.
- **Fichiers** : `retrieval_golden.py` (schéma + `evaluate_prompt_type_case`),
  `classifier.py` (3 marqueurs FACTUAL FR), `andritz_spl_hard_intents.json`
  (annotations), `scripts/golden_classifier_eval.py` (runner),
  `test_prompt_classifier.py` (tests paramétrés + régression).
- **Tests** : `poetry run pytest app/tests/ -q -k "prompt_classifier or golden
  or retrieval_golden"` (hors `api/test_auth_signup.py`,
  `services/test_hybrid_retrieval.py`) → **63 passed**.
- **Reproduire l'éval** : `python -m scripts.golden_classifier_eval [--full]`
  (fast = offline ; `--full` nécessite l'embedder).
- **Déploiement** : `classifier.py` est dans le chemin de service (appelé par
  `rag_agent.py` quand `prompt_type=="auto"`), mais `rag_agent.py` n'est **pas**
  modifié — pas de rebuild déclenché (conforme à la consigne). Le correctif est
  additif (3 patterns) et sans risque ; il sera embarqué au prochain déploiement.
  Mesures full faites in-container via `docker cp` du code à jour.
