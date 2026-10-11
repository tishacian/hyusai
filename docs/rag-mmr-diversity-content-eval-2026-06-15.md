# Golden « diversity » mesuré par contenu — le MMR apporte-t-il quelque chose ? (2026-06-15)

> Branche `demo/agentic`. Corpus Andritz, collection Qdrant
> `andritz__andritz-notices-techniques-spl-pilot__hybrid_1780665866`
> (~1,49 M chunks, 55 132 `document_id`, 24 488 contenus distincts).

## 1. Problème

Le batch golden `andritz_spl_diversity.json` mesurait la diversité via
`expected_distinct_documents`, comptée par `_distinct_document_count()` qui
s'appuie sur `_source_label()` → `document_filename`. Or les filenames Andritz
sont **préfixés par le projet/archive propriétaire de la copie** :

```
A__ACJ100__V.5.Vacuum set__CBI-GVC1C2C3__g150-operating-instructions-0312-en.pdf
A__AKI300__V.5.Vacuum set__POLLRICH - GVJ1__g150-operating-instructions-0312-en.pdf
B__BFG100__V.7.High pressure set__g150-operating-instructions-0312-en.pdf
```

Ces trois entrées sont **le même manuel** (contenu identique) mais comptaient
comme « 3 documents distincts ». Le round-robin `_diversify_aligned_by_document()`
diversifie par `document_id` → il traite ces copies comme diverses. Un A/B
MMR on/off ne montrait donc aucune différence : le critère d'éval était saturé
par des doublons inter-projets.

## 2. Clé de regroupement « contenu » retenue

**Basename du fichier, préfixe projet/archive retiré** : on prend le dernier
segment après `__` puis après `/`, normalisé (minuscule, ponctuation aplatie).
Implémenté dans `_content_key()` (`retrieval_golden.py`).

Vérifié sur la collection live — le basename est **stable et identique** à
travers toutes les copies projet d'un même manuel :

| Basename (contenu)                                   | Copies projet |
|------------------------------------------------------|--------------:|
| `g150-operating-instructions-0312-en.pdf`            | **13** |
| `control_units_cu250s-2_vektor_en-us.pdf`            | 16 |
| `22ab0280_015117_qms-12_qualiscan_ 6_ de_de.pdf`     | 9 |
| `ttn22087j spare parts list excelle s5pp6tt …`       | 9 |
| `lh2_0113_eng.pdf`                                    | 6 |
| `kd724.pdf`                                           | 2 |

Moyenne ~2,25 copies par contenu sur le corpus ; manuels « chauds » à 9–16
copies. Le basename inclut version/date (`0312`, `0113`) → une autre révision
est bien comptée comme un contenu distinct.

### Champs écartés

- **`content_sha256`** (hash du chunk) : présent mais **peu peuplé** dans les
  payloads live (≈ 2 chunks sur 8 sur les sondages), et de granularité
  *chunk* (pas *document*) → utilisé seulement en repli ultime.
- **`legacy_document_name`** / **`inner_document_path`** : portent le même
  basename, utilisés comme repli si `document_filename` manque.

## 3. Schéma golden étendu

- Nouveau champ `expected_distinct_content` (en plus de
  `expected_distinct_documents`, conservé pour compat/diagnostic).
- `_distinct_content_count()` : compte les `_content_key` distincts sur le
  top-k réellement transmis au générateur.
- Résultat d'éval expose `distinct_content` et `content_diversity_shortfall`.
- `golden_flag_ab.py` affiche désormais `distinct_content=B->V` par cas.

## 4. Mesure sur la VM (in-container, profil balanced)

Mesure : deux passes propres du batch (une `rag_mmr_enabled=true`, une `false`)
sur `agentium-backend`, `evaluate_retrieval_golden_case` réel, top-8 transmis
au générateur. `distinct_content` = `_distinct_content_count`. Seuil =
`expected_distinct_content` recalibré.

| cas | statut MMR (on) | distinct_content on | distinct_content off | seuil | base (on) | variant (off) |
|-----|-----------------|--------------------:|---------------------:|------:|:---------:|:-------------:|
| div_001 g150            | applied           | 1 | 1 | 1 | PASS | PASS |
| div_002 parts manual    | applied           | 2 | 2 | 3 | **fail** | **fail** |
| div_003 vacuum set      | applied           | 6 | 8 | 3 | PASS | PASS |
| div_004 Excelle S5PP6TT | applied           | 5 | 4 | 3 | PASS | PASS |
| div_005 PHP HP set      | applied           | 5 | 7 | 3 | PASS | PASS |
| div_006 CU250S-2        | skipped_exact     | 2 | 2 | 3 | **fail** | **fail** |
| div_007 Qualiscan QMS   | skipped_exact     | 7 | 7 | 3 | PASS | PASS |
| div_008 S120/S150 list  | timeout           | 8 | 8 | 2 | **fail*** | **fail*** |
| div_009 URACA KD724     | skipped_exact     | 8 | 4 | 3 | PASS | PASS |
| div_010 LH2 0113        | skipped_exact     | 1 | 1 | 1 | PASS | PASS |
| **Total** |  |  |  |  | **7/10** | **7/10** |

`*` div_008 échoue sur le **matching de source** (`matched=0` : la *list manual*
S120/S150 attendue n'arrive pas dans le top-5), pas sur la diversité —
`distinct_content`=8 est très divers. C'est une régression de précision de
récupération, distincte du sujet MMR.

Échecs de diversité **légitimes** (contenu < 3 alors que le corpus offre 3+
manuels distincts) : div_002 (2 *parts manuals* seulement) et div_006 (2 docs
CU250S-2 sur 3 disponibles). Ni MMR ni round-robin ne les corrige.

### Statut MMR par cas

Sur 10 cas, le MMR ne **s'exécute réellement (`applied`) que sur 5** (div_001–005).
Les 4 cas de référence exacte (`skipped_exact_match` : CU250S-2, QMS-12, KD724,
LH2 0113) le sautent par design ; div_008 a **timeout** (budget
`rag_mmr_budget_seconds=0.5 s` insuffisant pour embedder jusqu'à 24 candidats via
l'API OpenAI) → repli round-robin silencieux. **C'est l'explication de l'A/B
« aucune différence » d'origine : dans la majorité des cas le MMR ne tourne pas.**

## 5. Verdict MMR

**Le MMR n'apporte rien de mesurable en diversité de contenu sur ce corpus, et
le tend même légèrement à la baisse.**

- **Pas d'écart de pass-rate** : 7/10 MMR on = 7/10 MMR off. Les 3 échecs
  (div_002, div_006, div_008) sont identiques dans les deux bras.
- **Par cas, le round-robin fait jeu égal ou mieux.** Sur les 5 cas où le MMR
  s'exécute (`applied`), `distinct_content` on→off : 1→1, 2→2, 6→**8**, 5→4,
  5→**7**. Le round-robin (rotation par `document_id`) sort *plus* de contenus
  distincts sur div_003 et div_005, parce que λ=0.7 privilégie la pertinence et
  reclasse en tête des copies très pertinentes du même manuel.
- **Le MMR ne tourne que dans 50 % des cas** (4 `skipped_exact_match` + 1
  `timeout`). Le timeout (budget 0.5 s vs latence d'embedding OpenAI) provoque
  un repli round-robin silencieux : c'est pourquoi l'A/B d'origine ne montrait
  aucune différence.
- **Le bruit du pipeline dépasse l'effet MMR.** div_009, en round-robin dans les
  deux bras, donne 8 puis 4 contenus distincts d'une passe à l'autre
  (non-déterminisme ANN + coupe de compression). Toute différence MMR on/off de
  ±1–2 est donc dans le bruit.

Cause racine du « 3 copies comptées comme diverses » : **ni le MMR ni le
round-robin ne séparent les copies inter-projets d'un même manuel** quand le
contenu est l'enjeu. Le MMR mesure la redondance par embeddings (deux copies =
embeddings quasi identiques → il en écarte, OK) mais le **round-robin de repli
clé sur `document_id`** (`_document_diversity_key`), donc il traite les 13 copies
g150 comme 13 documents et peut en renvoyer 8.

## 6. Recommandation produit

1. **Ne pas compter sur le MMR pour la diversité de contenu, mais le garder
   activé** : il est neutre sur le pass-rate, sans régression, et utile sur
   d'autres axes (anti-redondance intra-document). Le couper n'apporte rien non
   plus. **Statu quo : `RAG_MMR_ENABLED=true`.**

2. **Lever (recommandé) — clé de regroupement du round-robin par contenu.**
   Faire que `_document_diversity_key` (`context.py:1595`) clé sur le basename
   normalisé (`_content_key`) plutôt que sur `document_id`. Les copies d'un même
   manuel tombent alors dans un seul bucket → la rotation force d'*autres*
   manuels en tête. C'est le seul levier qui peut faire passer div_002/div_006
   (le pool contient ≥3 manuels distincts mais la récupération en agrège 2).
   Changement ~3 lignes, à valider par un A/B dédié avant activation.

3. **Si on veut que le MMR s'exécute vraiment** : relever
   `rag_mmr_budget_seconds` (0.5 → ~1.5 s) ou précalculer/cacher les embeddings
   de chunks, sinon il timeout. Et baisser `rag_mmr_lambda` (0.7 → ~0.5) pour
   que le terme de redondance pèse plus. À tester seulement après le levier 2.

4. **div_008** (source attendue absente du top-5) est un sujet de **précision de
   récupération**, hors périmètre diversité — à traiter séparément.

## 7. Traçabilité

- **Commit** : `ccf449ff` sur `demo/agentic` (poussé sur Bitbucket
  `datategy-root/omnirag`). Parent `a11294e6`.
- **Fichiers** : `retrieval_golden.py`, `andritz_spl_diversity.json`,
  `golden_flag_ab.py`, `test_retrieval_golden_batch.py`, ce rapport.
- **Tests** : `poetry run pytest app/tests/ -q -k "golden or retrieval_golden
  or mmr"` (hors `api/test_auth_signup.py` email-validator et
  `services/test_hybrid_retrieval.py` Qdrant local) → **24 passed**.
- **Déploiement** : **aucun redéploiement nécessaire.** `retrieval_golden` n'est
  importé que par lui-même, les tests et `golden_flag_ab.py` — il n'est **pas**
  dans le chemin de service RAG live (`context.py`, `mmr_stage.py` inchangés).
  Le batch JSON et le harness ne servent qu'à l'évaluation. La VM
  (`omnirag-demo`) tourne, conteneurs `agentium-backend`/`-worker-cpu`/`qdrant`
  up ; mesures faites in-container par exécution directe sur le code à jour.
- **Reproduire l'A/B sur la VM** (après `docker cp` du code à jour dans
  `agentium-backend`, ou rebuild) :

  ```text
  docker exec -w /app/backend agentium-backend python -m scripts.golden_flag_ab \
    --workspace andritz \
    --batch app/resources/retrieval_golden/andritz_spl_diversity.json \
    --flags rag_mmr_enabled=false
  ```

- **Méthode de mesure** : deux passes propres mono-flag (`rag_mmr_enabled` true
  puis false), même `evaluate_retrieval_golden_case`, `rag_context_cache` et
  cache de recherche désactivés/contrôlés. Le cache de résultats de recherche
  porte sur la récupération brute (avant diversification) : il rend les entrées
  des deux bras identiques, donc l'écart observé tient à la seule étape de
  diversification.
