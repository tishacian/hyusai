# RAG follow-ups — résultats des 4 chantiers (2026-06-16)

> Branche `demo/agentic`, base de départ `3e5ec198`. Corpus Andritz, collection
> `andritz__andritz-notices-techniques-spl-pilot`, workspace `andritz`.
> Suit `docs/rag-follow-ups-plan-2026-06-15.md`.

## Vue d'ensemble

| chantier | nature | commit | déploiement |
|---|---|---|---|
| A — hygiène golden comparatif | golden-only | `2e182f0d` | non (test) |
| B — A/B balanced + flag | mesure + env VM | (env VM, non versionné) | via deploy consolidé |
| C — gap ingestion PG↔Qdrant | diagnostic read-only | `67188785` | non (docs) |
| D — bornage cross-encoder deep | code live + tests | `ee182f45` | deploy consolidé |

---

## A. Hygiène du golden comparatif (golden-only)

**Problème** : les cas comparatifs (hi_003/004/008) avaient `expected_sources` =
noms de composants (CONTINENTAL GVJS, Wilo NOLH) absents des `document_filename`
(exports HTML / part-numbers) → `matched_sources` toujours vide → échec
structurel malgré un rappel correct.

**Fait** : vérification in-container des fragments réellement récupérables, puis
recalibrage (le double-côté est porté par `expected_evidence_terms`, contenu) :

| cas | expected_sources | expected_evidence_terms | min |
|---|---|---|:--:|
| hi_003 | `AKI300` | `CONTINENTAL`, `POLLRICH` | 1 |
| hi_004 | `SINAMICS` | `G150`, `S120` | 1 |
| hi_008 | `702435420` (doc pompe Wilo, REN100) | `Drain`, `NOLH` | 1 |

**Avant/après** (re-run in-container, vrai Qdrant) :

| | deep (décompo ON) | balanced (décompo OFF) |
|---|:--:|:--:|
| hi_003 | PASS | PASS |
| hi_004 | PASS | PASS |
| hi_008 | **PASS** (matched `702435420`) | **fail** (doc Wilo non remonté) |

Global hard-intents : **4/11 → 7/11 deep, 6/11 balanced**. hi_008 est désormais
**discriminant** (passe seulement quand la décomposition récupère la doc Wilo).
Observations corpus : les 2 soufflantes hi_003 sont dans les mêmes pages HTML
AKI300 ; la doc Wilo hi_008 est indexée sous REN100 (part-number), pas BEX200.

Fichiers : `andritz_spl_hard_intents.json`, note dans
`docs/rag-comparative-decomposition-eval-2026-06-15.md §8`. Tests :
`pytest -k "golden or retrieval_golden"` → 17 passed. **Pas de redéploiement.**

## B. A/B balanced global + décision flag

**Objectif** : décider `rag_comparative_decompose_balanced` (défaut code False),
en se gardant des **faux positifs** (décomposition déclenchée sur des requêtes
non-comparatives).

**A/B in-container, profil balanced, `rag_comparative_decompose_balanced` off→on :**

| batch | cas | base | variant | régressions | faux positifs | latence Δ (wall) |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| hard_intents | 11 | 4/11 | 4/11 | 0 | 0 | −687 ms |
| dense | 30 | 29/30 | 29/30 | 0 | 0 | −538 ms |
| scope_filters | 3 | 1/3 | 1/3 | 0 | 0 | −1757 ms |
| multilingual | 6 | 3/6 | 3/6 | 0 | 0 | −1174 ms |

**Règle de bascule (les 4 tenues)** :
- (a) **0 régression** non-comparative sur les 50 cas ;
- (b) **0 faux positif** : `comparative_decompose` reste False sur tous les
  non-comparatifs ; la décomposition ne se déclenche que sur les 3 comparatifs
  (subhits 20–37, 2 entités promues) ;
- (c) **rappel comparatif en hausse** : prouvé en deep (A : hi_008 passe avec
  décompo) et par les diagnostics (subhits, promotions) ;
- (d) **latence dans le budget** : deltas négatifs (sous-requêtes en parallèle
  dans le deadline), ≪ 300 ms.

**Décision : flag ON** → `RAG_COMPARATIVE_DECOMPOSE_BALANCED=true` posé dans
`docker/env/agentium.vm.env` (override env VM, **pas** le défaut code, qui reste
False). Réserve : en balanced la décomposition se **saute proprement** quand le
deadline restant est court (cas lent type hi_008) — dégradation gracieuse, sans
régression ni faux positif.

## C. Gap d'ingestion PG ↔ Qdrant (diagnostic read-only)

Script read-only `backend/scripts/reconcile_pg_qdrant_sources.py` exécuté
in-container (3,3 M points scannés, sans cap). Détail :
`docs/ingestion-gap-pg-qdrant-2026-06-15.md`.

**Conclusion** : ingestion PG↔Qdrant cohérente. Seul écart matériel = **14
documents** sur la collection SPL en `status=ready` avec `chunk_count=0` (échec
d'extraction silencieux : 13 `.txt` "frei zur Wiederverwendung", 1 PDF BHX100),
soit ~0,025 % des docs ready. Le gros `present_count_mismatch` (25 583) est un
**artefact de comptage** (3 index physiques parallèles ≈ 3× le `chunk_count` PG ;
l'index `hybrid` seul colle exactement au PG). 46 247 `deduplicated` = attendu,
27 `error` = échecs déjà journalisés. **Aucune ré-ingestion** (hors périmètre).

## D. Bornage du cross-encoder deep

**Problème** : en deep, le CE L-12 tournait sur tout le pool fusionné avec
`budget_seconds=None` et `pool=len(chunks)` → non borné en temps ni en nombre,
risque de dépasser le deadline deep (120 s).

**Fait** (`config.py`, `cross_encoder_stage.py`, branche deep uniquement —
balanced inchangé) :
- `rag_cross_encoder_budget_seconds_deep=25.0` (fraction du deadline 120 s)
- `rag_cross_encoder_max_candidates_deep=64`
- `rag_cross_encoder_max_length_deep=512`
La voie de budget existante (`wait_for(shield(future), timeout)`) s'applique
désormais au deep (budget ≠ None) et se replie sur l'ordre policy au timeout.
Tests : budget deep honoré (timeout → ordre policy), pool deep cappé (queue
intacte), balanced non affecté. `pytest -k "cross_encoder or rerank or
retrieval"` → 172 passed.

**Smoke post-déploiement** (in-container, code `ee182f4`) :

- Flags live confirmés : `rag_comparative_decompose_balanced=True` (env),
  `rag_cross_encoder_budget_seconds_deep=25.0`, `…_max_candidates_deep=64`.
- Requête comparative hi_003, **deep** : `comparative_decompose=True`, 2 entités
  promues, `cross_encoder_status=applied` (CE deep borné), `retrieval_elapsed_ms
  =1612` (≪ deadline 120 s).
- Même requête, **balanced** : `comparative_decompose=True`, 2 entités promues,
  `retrieval_elapsed_ms=302` (≪ deadline balanced 8 s) — la décomposition
  balanced est bien active via l'env. (`cross_encoder_status=timeout` = budget
  CE balanced 0,5 s historique, **inchangé** par D.)
- Cas lourd hi_008 (Wilo, subhits 48/48) en balanced : la décomposition se
  saute sur le deadline serré → repli propre, sans erreur (comportement attendu).

## Déploiement consolidé & état VM

Un seul `bash scripts/deploy-vm.sh --no-frontend` (094f41e1/6176982 → HEAD) a
embarqué le code D (bornage CE deep) et lu l'env VM avec le flag B :

- **HEAD VM = `ee182f4`** == `origin/demo/agentic`.
- **Audit de dérive post-déploiement VERT** : `agentium-backend` et
  `agentium-worker-cpu` ont un code identique à l'arbre git (`backend/app/*.py`).
- **Migration** : `alembic current` = `041_andritz_default_scope_spl (head)` —
  aucune nouvelle migration introduite par A/C/D (041 déjà appliquée).
- **Conteneurs** : `agentium-backend` healthy (`/api/v1/health=200`),
  `agentium-worker-cpu` up.
- **Env VM** : `RAG_COMPARATIVE_DECOMPOSE_BALANCED=true` (fichier
  `docker/env/agentium.vm.env`, gitignored/local VM, survit au `git reset`).
  Défaut code inchangé (`False`). MMR off, prompt classifier on (inchangés).
- A (golden) et C (diagnostic) n'ont pas nécessité de redéploiement.

## Hashs commits

- A `2e182f0d` · C `67188785` · D `ee182f45` · (golden_flag_ab latence `6176982d`,
  feature décompo `07a7faef`, rapport décompo `4562c285` — chantiers antérieurs).
- B : pas de commit code (flip via env VM non versionné, par conception).
- Ce rapport : `f4f15f05`.
