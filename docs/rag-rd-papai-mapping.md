# R&D RAGGER / HAH / C-HAH — Cartographie dans le repo omnirag

Ce document relie la recherche (papers RAGGER, HAH, OmniRAGGER, etc.) au **code réellement présent** dans le dépôt, et clarifie ce que la **démo FastAPI + frontend vanilla** utilise aujourd’hui.

## 1. Synthèse exécutive

| Concept papier / produit | Où c’est implémenté dans le repo | Actif dans la démo MVP (`backend/app` + `frontend/`) ? |
|--------------------------|----------------------------------|--------------------------------------------------------|
| **Naive RAG** (retrieval simple) | `src/customchain_naive.py`, `benchmarking/customchain_naive.py` | **Partiellement** : équivalent *retrieval vectoriel seul* via `DocumentService.search(..., use_hybrid=False)` — pas la même chaîne LangChain historique. |
| **HAH RAG** (Hybrid Attention / hiérarchique) | `src/customchain.py` (`CustomLLMChain`), `benchmarking/customchain_hah.py` | **Oui (stratégie A)** : [`retrieve_hah_like`](backend/app/services/rag/pipeline_retrieval.py) — deux passes hybrid + fusion RRF sur le **même index** que la démo. Pas byte-identique au Streamlit (pas de `CustomLLMChain` complet). |
| **C-HAH / HAH composite** (asynchrone, multi-stratégies) | `src/customchainmixedhah.py`, enum `PipelineType.HAHCOMPOSITE` dans `backend/app/globalvariables.py` | **Oui (stratégie A)** : [`retrieve_chah_like`](backend/app/services/rag/pipeline_retrieval.py) — recherches hybrid **parallèles** sur variantes de requête + RRF. |
| **Hybrid dense + sparse (BM25) + fusion** | `backend/app/services/retrieval/hybrid_retriever.py`, `RRF`, `DocumentService` | **Oui** — cœur du retrieval (`use_hybrid=True`). |
| **Benchmarks Naive / Hybrid / HAH** | `benchmarking/benchmarking.py`, `benchmarking/README.md` | Outil séparé, pas le chat démo. |

**Conclusion** : les travaux **RAGGER / HAH / C-HAH** au sens **chaînes `CustomLLMChain` complètes** (modèle local, `invoke_async` end-to-end) vivent sous **`src/`** et l’UI **Streamlit**. La plateforme démo exécute désormais des **pipelines HAH-like / C-HAH-like** dans [`pipeline_retrieval.py`](backend/app/services/rag/pipeline_retrieval.py), branchés par `rag_pipeline_mode` lorsque `RAG_HAH_CHAH_ENABLED` est vrai (voir [`Settings`](backend/app/core/config.py)).

## 2. Contrat `retrieve_for_mode` (backend)

Point d’entrée unique : [`retrieve_for_mode`](backend/app/services/rag/pipeline_retrieval.py) dans [`backend/app/services/rag/pipeline_retrieval.py`](backend/app/services/rag/pipeline_retrieval.py).

| Paramètre | Rôle |
|-----------|------|
| `doc_svc` | `DocumentService` (FAISS + embedder démo) |
| `query` | Requête utilisateur (souvent `rewritten_query`) |
| `mode` | `rag_pipeline_mode` : `auto`, `naive`, `hybrid`, `hah`, `chah`, … |
| `top_k` | Nombre de chunks retournés (ex. 5) |
| `use_hybrid` | Pour modes non HAH/C-HAH : vient de [`resolve_retrieval_mode`](backend/app/services/rag/mode_selector.py) |
| `hah_chah_enabled` | `settings.rag_hah_chah_enabled` — si `False`, `hah`/`chah` se comportent comme un search hybrid simple |

**Retour** : `RetrievalPipelineResult` — `chunks`, `scores`, `pipeline` (`naive` \| `hybrid` \| `hah_backend` \| `chah_backend` \| `fallback_hybrid`), `label`, `reason`, `detail` (texte pour les decision steps SSE).

### Correspondance avec `src/` (référence R&D)

| Étape legacy (`src`) | Équivalent backend (stratégie A) |
|----------------------|----------------------------------|
| HAH : `invoke_async` → 1re recherche → filtrage → 2e recherche sur document joint ([`customchain.py`](src/customchain.py) ~L1145–1171) | `retrieve_hah_like` : pass1 `search(query)` → pseudo-document → pass2 `search(pseudo)` → `_merge_rrf` |
| C-HAH : plans parallèles / fusion ([`customchainmixedhah.py`](src/customchainmixedhah.py), `parallel_composite_retrieval`, `RetrievalPlan`) | `retrieve_chah_like` : `asyncio.gather` sur `search(variant_i)` pour variantes dérivées de la requête → `_merge_rrf` |
| Génération : `custom_llm_chain` + modèle local | Inchangé côté démo : [`procurement_agent`](backend/app/agents/procurement_agent.py) + LLM API (`app.llm`) |

## 3. Fichiers clés pour la R&D (référence)

- **Enum des modes** : `backend/app/globalvariables.py` — `PipelineType` : `NAIVE`, `HAH`, `HAHCOMPOSITE` (libellés historiques Streamlit).
- **Sélection Naive / HAH / C-HAH (Streamlit)** : `src/standalone_interface/omnirag.py` — branchement sur `NaiveCustomLLMChain`, `HAHCustomLLMChain`, `CHAHCustomLLMChain`.
- **Agent démo chat** : `backend/app/agents/procurement_agent.py` — `retrieve_for_mode` après résolution `resolve_retrieval_mode`.
- **Retrieval hybride** : `backend/app/services/rag/document_service.py`, `hybrid_retriever.py`, `bm25_retriever.py`, `rrf_retriever.py`.

## 4. Comportement exposé par la démo

- **`rag_pipeline_mode`** dans le corps JSON du chat (`POST /api/v1/chat/stream`) :
  - `auto` — heuristique sur la **taille de l’index** et la **longueur de la requête** pour choisir vectoriel seul vs hybride RRF.
  - `naive` — **vectoriel seul**.
  - `hybrid` — **hybride** RRF.
  - `hah` — **HAH-like** (deux passes + RRF) si `rag_hah_chah_enabled` ; sinon hybrid avec raison affichée.
  - `chah` — **C-HAH-like** (parallèle + RRF) si `rag_hah_chah_enabled` ; sinon hybrid.

Variable d’environnement : **`RAG_HAH_CHAH_ENABLED`** (défaut `true` dans [`Settings`](backend/app/core/config.py)).

## 5. Option stratégie B (sidecar / worker `src`)

Pour une **parité stricte** avec `CustomLLMChain` (même tokenizer, même modèle local, index sous `vector_store/`) :

- Exposer un **service séparé** (Docker) avec les dépendances `src` (torch, etc.).
- Contrat JSON : `{ "query", "mode", "vector_store_name" }` → `{ "answer", "context", "metrics" }` ou uniquement contexte pour laisser la génération au FastAPI.
- Aligner **chemins d’index** ou pipeline d’export depuis la KB démo — hors scope du MVP stratégie A.

## 6. Documents PDF (hors repo)

Les fichiers PDF cités par l’équipe (Google Drive / iCloud) ne sont pas versionnés dans ce repo ; cette note reste la **référence technique** côté code.
