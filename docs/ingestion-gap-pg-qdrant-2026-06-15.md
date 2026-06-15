# Diagnostic de l'écart d'ingestion Postgres ↔ Qdrant — workspace `andritz`

**Date :** 2026-06-15
**Nature :** diagnostic en lecture seule (READ-ONLY). Aucune ré-ingestion, aucune
modification, aucun déploiement. Ce document ne propose **aucune action de
remédiation** : il caractérise uniquement la taille et la nature de l'écart.

---

## 1. Méthode

On rapproche le **registre source** (Postgres) et le **magasin de vecteurs** (Qdrant)
pour chaque collection de connaissances du workspace `andritz`
(`workspace_id = 0cce0bee-7e86-485d-95b1-672e82f16600`).

- **Côté PG** : table `knowledge_collection_sources`, regroupée par collection, avec
  pour chaque document son `status` et son `chunk_count`.
- **Côté Qdrant** : pour chaque collection physique correspondante, on parcourt
  (`scroll`, pages de 2000 points, sans vecteurs, payload limité à `document_id` /
  `document_filename`) et on agrège l'ensemble des `document_id` distincts réellement
  présents, ainsi qu'un comptage de vecteurs/chunks par document.
- **Jointure** sur `document_id` (repli sur `document_filename` / `normalized_name`),
  puis classification de chaque source PG :
  - `present_ok` — présent dans Qdrant, comptages cohérents ;
  - `present_count_mismatch` — présent mais divergence significative (> 25 %) entre
    `chunk_count` PG et nombre de vecteurs Qdrant ;
  - `missing_in_qdrant` — PG en `ready`/`indexed` mais **0 vecteur** dans Qdrant → **l'écart** ;
  - `deduplicated` — statut PG `deduplicated` (**attendu, ce n'est PAS un écart**) ;
  - `error` — statut PG `error` ;
  - `never_enqueued` — statut PG `queued` (jamais mis en file) ;
  - `other` — autres statuts (deleted, ingesting…).

Script (lecture seule) : `backend/scripts/reconcile_pg_qdrant_sources.py`.
Exécution **dans le conteneur** `agentium-backend` sur la VM, via stdin
(sans `docker cp`, sans rebuild) :

```
cat backend/scripts/reconcile_pg_qdrant_sources.py \
  | ssh omnirag-demo "docker exec -i -e RECON_WORKSPACE=andritz agentium-backend python -"
```

Le parcours complet a couvert **3 311 895 points** Qdrant (sans plafonnement).

---

## 2. Collections physiques Qdrant du workspace

| Collection physique Qdrant | Points |
|---|---:|
| `andritz__andritz-manuals-bba120-pilot__hybrid_1780602499` | 568 |
| `andritz__andritz-mvp-knowledge__hybrid_1780602502` | 53 |
| `andritz__andritz-non-wovens-france-excel-pilot__hybrid_1780602503` | 4 998 |
| `andritz__andritz-non-wovens-pilot-archive__hybrid_1780602523` | 45 |
| `andritz__andritz-notices-techniques-spl-pilot__eval_openai_text_embedding_3_large_1536d` | 889 104 |
| `andritz__andritz-notices-techniques-spl-pilot__hybrid_1780665866` | **1 533 687** |
| `andritz__andritz-notices-techniques-spl-pilot__metadata_v1_1780640395` | 889 104 |
| `andritz__documents__hybrid_1780602524` | 9 |

> **Note importante (artefact de comptage).** La collection logique principale
> `andritz-notices-techniques-spl-pilot` possède **trois** collections physiques en
> parallèle : l'index `hybrid` de production (1 533 687 points), un index
> d'évaluation `eval_openai_text_embedding_3_large_1536d` (889 104) et un index
> `metadata_v1` (889 104). Le script additionne les vecteurs de ces trois index
> physiques pour un même document, ce qui gonfle mécaniquement le comptage Qdrant
> (≈ ×3 sur les documents présents dans les trois index). C'est l'origine quasi
> exclusive de la catégorie `present_count_mismatch` ci-dessous (voir §4).

---

## 3. Tableau récapitulatif par collection

| Collection logique | PG sources | PG ready/indexed | PG deduplicated | PG error | Qdrant docs distincts | missing_in_qdrant |
|---|---:|---:|---:|---:|---:|---:|
| `andritz-manuals-bba120-pilot` | 0 | 0 | 0 | 0 | 22 | 0 |
| `andritz-non-wovens-france-excel-pilot` | 0 | 0 | 0 | 0 | 25 | 0 |
| `andritz-non-wovens-pilot-archive` | 0 | 0 | 0 | 0 | 25 | 0 |
| **`andritz-notices-techniques-spl-pilot`** | **102 877** | **56 603** | **46 247** | **27** | **58 042** | **14** |
| `andritz-documents` | 1 | 1 | 0 | 0 | 1 | 0 |

Détail de la classification (sources PG) pour la collection principale
`andritz-notices-techniques-spl-pilot` :

| Classe | Nombre |
|---|---:|
| `present_ok` | 31 006 |
| `present_count_mismatch` | 25 583 |
| `missing_in_qdrant` (**l'écart réel**) | **14** |
| `deduplicated` (attendu, non-écart) | 46 247 |
| `error` | 27 |
| `never_enqueued` | 0 |
| `other` | 0 |

> Les 4 petites collections (`manuals-bba120`, `non-wovens-france-excel`,
> `non-wovens-pilot-archive`, `documents`) n'ont essentiellement **pas de lignes
> dans le registre PG** (`knowledge_collection_sources`) — sauf `documents` avec 1
> source `present_ok`. Leurs vecteurs existent bien côté Qdrant (22 / 25 / 25 / 1
> documents distincts). Il n'y a donc **aucun écart d'ingestion** sur ces
> collections : l'absence de lignes PG reflète un registre source non peuplé pour
> ces pilotes, pas un défaut d'indexation.

---

## 4. Lecture de `present_count_mismatch` (25 583)

Cette catégorie n'est **pas un écart d'ingestion**. Les divergences observées
suivent toutes le même motif : `qdrant_vectors ≈ 3 × pg_chunk_count`. Exemples
représentatifs issus de l'exécution :

| Document | `pg_chunk_count` | vecteurs Qdrant (somme des 3 index) |
|---|---:|---:|
| `…S120_S150_List_Manual_LH1_0414_eng.pdf` | 8 414 | 25 242 (≈ ×3) |
| `…BAN400…parts manual.pdf` | 5 104 | 15 312 (≈ ×3) |
| `…G150…lh2-0113_eng.pdf` | 4 859 | 14 577 (≈ ×3) |
| `…5186004875.pdf` (multiples révisions) | 979 | 2 937 (= ×3) |

L'explication est l'addition des **trois collections physiques** parallèles de la
collection SPL (cf. §2). L'index de production seul (`hybrid_1780665866`,
1 533 687 points) correspond **exactement** au `chunk_count` de la collection en
métadonnées PG (`chunk_count = 1 533 687`). Autrement dit, ces documents sont
correctement indexés ; la divergence est un **artefact de comptage** lié à la
présence d'index d'évaluation/métadonnées additionnels, et non un déficit de
chunks.

---

## 5. L'écart réel : `missing_in_qdrant` (14 documents)

Tous concentrés sur `andritz-notices-techniques-spl-pilot`. Tous ont
`pg_status = ready` mais **`pg_chunk_count = 0`** : ils ont été marqués prêts dans
le registre alors qu'aucun chunk n'a été produit → **échec d'extraction / parsing à
l'ingestion** (aucun vecteur correspondant côté Qdrant). Aucun `last_error` n'est
renseigné sur ces lignes.

Liste complète :

| Fichier | `pg_status` | `pg_chunk_count` | Cause probable |
|---|---|---:|---|
| `A__Manual_ASY200__…__96-003593__001__frei zur Wiederverwendung .txt` | ready | 0 | extraction nulle (0 chunk) |
| `A__Manual_ASY200__…__96-003637__001__frei zur Wiederverwendung .txt` | ready | 0 | extraction nulle (0 chunk) |
| `A__Manual_ASY200__(PDF version)…__96-003593__001__frei zur Wiederverwendung .txt` | ready | 0 | extraction nulle (0 chunk) |
| `A__Manual_ASY200__(PDF version)…__96-003637__001__frei zur Wiederverwendung .txt` | ready | 0 | extraction nulle (0 chunk) |
| `B__Manual_BHX100_revA__(HTML)…__96-003593__001__frei zur Wiederverwendung .txt` | ready | 0 | extraction nulle (0 chunk) |
| `B__Manual_BHX100_revA__(PDF)…__96-003593__001__frei zur Wiederverwendung .txt` | ready | 0 | extraction nulle (0 chunk) |
| `B__Manual_BHX100_revA__(PDF)…__Operator manual_BHX100_EN__…__12325781259.pdf` | ready | 0 | extraction nulle (0 chunk) — seul PDF de la liste |
| `B__Manual_BHX100_revB__(HTML)…__96-003593__001__frei zur Wiederverwendung .txt` | ready | 0 | extraction nulle (0 chunk) |
| `B__Manual_BHX100_revB__(PDF)…__96-003593__001__frei zur Wiederverwendung .txt` | ready | 0 | extraction nulle (0 chunk) |
| `B__Manual_BHX100_revC__(HTML)…__96-003593__001__frei zur Wiederverwendung .txt` | ready | 0 | extraction nulle (0 chunk) |
| `B__Manual_BHX100_revC__(PDF)…__96-003593__001__frei zur Wiederverwendung .txt` | ready | 0 | extraction nulle (0 chunk) |
| `B__Manual_BHX100_revD__(HTML)…__96-003593__001__frei zur Wiederverwendung .txt` | ready | 0 | extraction nulle (0 chunk) |
| `B__Manual_BHX100_revD__(PDF)…__96-003593__001__frei zur Wiederverwendung .txt` | ready | 0 | extraction nulle (0 chunk) |
| `E__Manual_ELM001Y__(HTML)…__96-003593__001__frei zur Wiederverwendung .txt` | ready | 0 | extraction nulle (0 chunk) |

Caractérisation :
- **13/14** sont des fichiers `.txt` au libellé `… frei zur Wiederverwendung .txt`
  (mention allemande « libre de réutilisation »). Le motif récurrent
  `96-003593` / `96-003637` (références de jauges/3rd-party) suggère des fichiers
  texte de placeholder/avis, vraisemblablement vides ou non extractibles → 0 chunk.
- **1/14** est un PDF (`…BHX100…12325781259.pdf`) ayant produit 0 chunk : échec
  d'extraction PDF probable (PDF image/non-textuel ou parsing en échec).

Aucun de ces 14 documents n'a le statut `error` ni de `last_error` : la cause n'est
donc pas une erreur explicitement journalisée, mais une **extraction silencieuse à
0 chunk** suivie d'un marquage `ready`.

À côté de l'écart proprement dit, on note **27 documents en statut `error`** sur la
collection SPL (échecs d'ingestion explicitement journalisés), comptabilisés
séparément, et **46 247 documents `deduplicated`** (doublons écartés — comportement
**attendu**, ce ne sont pas des manquants).

---

## 6. Conclusion sur la taille et la nature de l'écart

- **L'écart d'ingestion réel (PG `ready` mais 0 vecteur dans Qdrant) est très
  faible : 14 documents** sur ~56 600 documents `ready` de la collection principale
  (~0,025 %), tous avec `chunk_count = 0`.
- **Nature de l'écart : extraction/parsing à vide.** Il ne s'agit pas d'un défaut
  d'upsert vers Qdrant ni d'une file de travail interrompue — les documents ont bien
  été traités, mais l'extraction de contenu a produit 0 chunk (13 fichiers `.txt`
  « frei zur Wiederverwendung » probablement vides/non extractibles, 1 PDF non
  textuel). Ils ont néanmoins été marqués `ready` dans le registre PG.
- Les **46 247 `deduplicated`** et **27 `error`** sont en dehors de l'écart : les
  premiers sont attendus, les seconds sont des échecs déjà journalisés côté PG.
- La catégorie volumineuse `present_count_mismatch` (25 583) est un **artefact de
  comptage** dû aux trois index physiques parallèles de la collection SPL, et non un
  manque de chunks : l'index de production (`hybrid`, 1 533 687 points) correspond
  exactement au `chunk_count` PG de la collection.
- Les 4 collections pilotes secondaires n'ont pas (ou quasiment pas) de registre PG,
  mais leurs vecteurs sont présents dans Qdrant : **aucun écart** s'y rapportant.

**Synthèse :** le pipeline d'ingestion PG → Qdrant est globalement cohérent pour le
workspace `andritz`. L'unique écart matériel est constitué de **14 documents à 0
chunk** (échecs d'extraction silencieux) sur la collection
`andritz-notices-techniques-spl-pilot`.
