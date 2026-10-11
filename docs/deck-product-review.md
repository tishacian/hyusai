---
marp: true
theme: default
paginate: true
class: lead
title: "Agentium — Revue produit"
author: "Équipe Agentium"
description: "Mental model, user stories livrées et parcours personas end-to-end"
---

# Agentium — Revue produit

**OS pour systèmes intelligents.**

Mental model, user stories livrées, parcours personas end-to-end.

<br>

*Document vivant — v0.4.0 · branche `demo/agentic` · `agentium.papai.ai`*

---

## Agenda

1. **Pourquoi** — le problème qu’Agentium résout
2. **Mental model** — entités canoniques et boucle fermée
3. **Architecture runtime** — backend, frontend, skills
4. **Carte UI** — cockpit, zoom sémantique, command palette
5. **Personas** — 6 parcours complets avec drill-down
6. **Mapping capacités backend ↔ UI** — exhaustivité
7. **User stories livrées** — Waves A → F
8. **Invariants & garanties**
9. **Prochaines étapes**
10. **Livraison post-réalignement 2026-04-21** — Outcome hybride, execution_mode, workspace modes, info-bulles persona-aware

---

## 1. Pourquoi

Les plateformes « agent builder » s’arrêtent au composer.
L’équipe produit a besoin de **piloter un portefeuille** :

- Voir l’**impact** en temps réel (coût, valeur, latence, confiance).
- **Ajuster** le comportement sans toucher au code.
- **Prouver** ce qui s’est passé (décisions, runs, audit).
- **Adapter** en boucle fermée (politiques adaptatives).

> Agentium n’est pas un agent builder — c’est un **OS pour systèmes intelligents**.

---

## 2. La boucle fermée

<br>

```
Objective → Capability → System → Run → Outcome → Decision → Adaptation
```

<br>

| Phase        | Lieu dans le produit                     |
|--------------|------------------------------------------|
| Objective    | `/capabilities` (blueprints)              |
| Capability   | `/capabilities/:id`                       |
| System       | `/systems/:id` · `/systems/new`           |
| Run          | `/runs` · `/runs/:id`                     |
| Outcome      | `/observability` · `/runs/:id` (onglet)  |
| Decision     | `/hypervisor` (feed + drawer)             |
| Adaptation   | `/steering` (ControlPolicy + Adaptive)    |

---

## 3. Entités canoniques

| Entité              | Rôle                                                    | API                              |
|---------------------|---------------------------------------------------------|----------------------------------|
| **Capability**      | Blueprint d’outcome métier (universal / industry / client) | `/capabilities`                  |
| **Skill**           | Unité atomique certifiée (RAG, classify, extract, …)   | `/skills`                        |
| **System**          | Graphe exécutable lié à une Capability                  | `/systems/{id}`                  |
| **Context**         | Data refs + mémoires + permissions                      | `/contexts/{id}`                 |
| **Control policy**  | Limites dures (coût, latence, HITL, modèles autorisés)  | `/control-plane/policies`        |
| **Adaptive policy** | Triggers + adaptations autorisées                        | `/control-plane/adaptive`        |
| **Run**             | Exécution unique (skill trail, outcome, confidence)     | `/runs/{id}`                     |
| **Decision**        | Recommandation / what-if / action adaptative            | `/hypervisor/decisions/{id}`     |

> Les alias legacy (`/agents`, `/traces/traces`) renvoient un header `X-Deprecated`.

---

## 4. Hiérarchie & propagation

<br>

```
Workspace
   └── Capability (blueprint)
         └── System (exécutable)
               ├── default_prompt_type
               ├── default_model
               ├── retrieval_mode_default (auto | fast | rich | HAH | CHAH)
               ├── Context (data refs, memory, permissions)
               ├── ControlPolicy (budget, latency, HITL)
               ├── AdaptivePolicy (triggers, allowed_actions)
               └── Run (skill_invocations, outcome, impact)
```

**Règle de précédence** : `per-query override` > `system default` > `workspace default`.

---

## 5. Configuration per-system

Un **System** porte ses propres defaults appliqués à chaque invocation :

| Champ                      | Valeurs                                                              |
|----------------------------|----------------------------------------------------------------------|
| `default_prompt_type`      | `auto`, `summarization`, `comparison`, `multi_hop`, `complex_reasoning`, … |
| `default_model`            | Slug LLM (Ollama, Azure/OpenAI, mistral-nemo, …)                     |
| `retrieval_mode_default`   | `auto`, `fast`, `rich`, `HAH`, `CHAH`                                |

**UI** — Builder step *Policy* + chat panel (overrides per-query).
**Backend** — `run_engine` injecte `ctx.default_*` dans chaque skill call.

---

## 6. Les 4 leviers canoniques

| Levier            | Spectre             | Effet projeté sur la base     |
|-------------------|---------------------|-------------------------------|
| `resource`        | lean → deep         | +coût, +valeur                |
| `velocity`        | thorough → rapid    | −latence, −valeur (léger)     |
| `autonomy`        | HITL → full         | −coût, +risque                |
| `risk_tolerance`  | cautious → bold     | +plafond de valeur            |

- **Hypervisor** — `POST /hypervisor/what-if` (scope portfolio, levers globaux).
- **Steering** — `POST /control-plane/simulate` (scope capability/system).
- **Commit** — `POST /control-plane/policies` ou `/control-plane/adaptive`.

---

## 7. Flux de décisions

**Feed paginé** — `GET /hypervisor/decisions?status=…&limit=…&offset=…`

Chaque Decision porte :
- `scope` ∈ `portfolio | capability | system | run`
- `kind` (recommendation, what-if, adaptive-trigger, …)
- `status` ∈ `open | accepted | rejected | applied`
- `rationale` (texte / structure)
- `impact_estimate` (Δ cost, Δ value, Δ latency, Δ confidence)

**Détail** — `GET /hypervisor/decisions/{id}` ouvre un drawer avec JSON intégral + approbation (accept / reject).

---

## 8. Architecture runtime

<br>

```
┌──────────────────────────────────────────────────────────┐
│  Angular 20 zoneless · signals · cockpit shell           │
│  ⌘K palette · ⌘Z / ⇧⌘Z zoom · theme (light/dark/system) │
└──────────────────────────────────────────────────────────┘
           │ HTTPS · /api/v1/*
           ▼
┌──────────────────────────────────────────────────────────┐
│  FastAPI · SQLAlchemy · Alembic                          │
│  Canonical routers + legacy aliases (X-Deprecated)       │
└──────────────────────────────────────────────────────────┘
      │               │                 │
┌─────▼────┐   ┌──────▼─────┐   ┌───────▼────────┐
│ Run      │   │ Skills     │   │ Model router   │
│ engine   │   │ registry   │   │ (Ollama/Azure) │
└──────────┘   └────────────┘   └────────────────┘
      │               │
┌─────▼────┐   ┌──────▼─────┐
│ Postgres │   │ Qdrant     │
│ (canon)  │   │ (RAG)      │
└──────────┘   └────────────┘
```

---

## 9. Skills runtime — tri-state

`GET /skills/runtime-health` expose pour chaque slug :

- **bound** — wrapper présent *et* module d’implémentation importable.
- **stub** — wrapper présent, retourne un placeholder (credentials manquants).
- **unbound** — aucun wrapper → `_unimplemented` + erreur dans le run.

Exemples bound aujourd’hui :

`llm_rag_answer_v1`, `semantic_search_v1`, `document_ingestion_v1`,
`eval_radar_v1`, `claim_audit_v1`, `intelligence_batch_v1`,
`audit_log_v1`, `ollama_llm_v1`, `azure_llm_v1`,
`chain_naive_v1`, `chain_hybrid_v1`, `chain_mixed_hah_v1`.

> La map complète vit dans `docs/skills-runtime.md`.

---

## 10. Carte UI — routes

| Concept              | Route                              |
|----------------------|------------------------------------|
| Hypervisor (balance sheet) | `/hypervisor`                |
| Steering             | `/steering`                        |
| Contexts             | `/steering/contexts`               |
| Capabilities         | `/capabilities` · `/capabilities/:id` |
| Skills               | `/skills`                          |
| Systems              | `/systems` · `/systems/:id`        |
| System Builder       | `/systems/new`                     |
| Runs                 | `/runs` · `/runs/:runId`           |
| Observability        | `/observability`                   |
| Governance           | `/governance/audit` · `/governance/access` |
| Knowledge            | `/knowledge`                       |
| Intelligence         | `/intelligence`                    |
| Missions             | `/tasks`                           |
| Apps / Resources     | `/apps` · `/resources`             |

---

## 11. Cockpit shell — affordances globales

- **Title bar (48 px)** — brand, breadcrumb zoom sémantique, readouts THRPT / LATENCY / YIELD, live dot, bascule thème, workspace picker, user menu.
- **Side rail (56 px)** — 5 vues cockpit (Hypervisor, Zoom, Steering, Builder, Run) + affordance « More » pour la nav secondaire.
- **Command palette** — `⌘K` / `⌃K` : recherche floue sur vues + actions.
- **Semantic zoom** — `⌘Z` zoom-in / `⇧⌘Z` zoom-out le long du breadcrumb (ex. portfolio → capability → system → run).
- **Thème** — cycle `light → dark → system` avec synchronisation OS en live.

---

## 12. Personas couverts

| # | Persona                          | Rôle clé                             | Vue d’entrée                     |
|---|----------------------------------|--------------------------------------|----------------------------------|
| 1 | **Sarah — Chief AI Officer**     | Piloter le portefeuille              | `/hypervisor`                    |
| 2 | **Mehdi — Capability Steward**    | Régler une capability               | `/steering`                      |
| 3 | **Alex — System Builder**         | Composer un system                   | `/systems/new`                   |
| 4 | **Claire — Business Analyst**     | Exploiter un system (chat + runs)    | `/systems/:id` + chat            |
| 5 | **Léo — Knowledge Curator**       | Courate la donnée / contextes        | `/knowledge` · `/steering/contexts` |
| 6 | **Nadia — Governance Officer**    | Auditer conformité & accès           | `/governance/audit`              |

---

## Persona 1 — Sarah, Chief AI Officer

**Mission** — maximiser la valeur produite sans dérapage budget/risque.

**Jobs-to-be-done**
- Voir d’un coup d’œil où l’on gagne / où l’on perd.
- Tester une orientation stratégique avant de l’engager.
- Approuver ou rejeter les recommandations du système.

**Vue d’entrée** — `/hypervisor` (balance sheet global).

---

### Sarah — Workflow complet

1. **Arrivée sur `/hypervisor`** — tuiles cost / value / ROI / latency + sparklines (alim. `GET /hypervisor/aggregate`).
2. **Drill vers une capability « chaude »** → breadcrumb passe à `/capabilities/:id`, What-If se contextualise (`⌘Z`).
3. **Ouvre le panel What-If** — ajuste `resource`, `velocity`, `autonomy`, `risk_tolerance` → `POST /hypervisor/what-if` en debounce 200 ms.
4. **Projection before/after** — Δ cost, Δ value, Δ ROI, latency index.
5. **Scrolle le Decisions feed** — filtre `status=open`, ouvre une recommandation → drawer `GET /hypervisor/decisions/{id}`.
6. **Accepte** → status `accepted`, l’Adaptive policy ciblée devient active (`POST /control-plane/adaptive/{id}/toggle`).
7. **Retour à la balance sheet** — attend les prochains runs pour voir la projection se matérialiser (`GET /impact`).

**Backend touché** — `hypervisor` · `control-plane/adaptive` · `impact` · `metrics`.

---

## Persona 2 — Mehdi, Capability Steward

**Mission** — garantir qu’une capability reste dans son enveloppe (coût, latence, conformité).

**Jobs-to-be-done**
- Fixer les garde-fous (Control policy).
- Configurer les adaptations autorisées (Adaptive policy).
- Simuler l’impact avant de commit.

**Vue d’entrée** — `/steering`.

---

### Mehdi — Workflow complet

1. **Sélectionne une capability** dans la liste `/steering` — side panel affiche ControlPolicy + AdaptivePolicies filtrées (`GET /control-plane/policies`, `GET /control-plane/adaptive?scope=capability&target_id=…`).
2. **Ajuste les garde-fous** — max cost / run, max latency, HITL threshold, modèles autorisés → `PATCH /control-plane/policies/{id}`.
3. **Simule** l’effet avec les 4 leviers — `POST /control-plane/simulate` retourne projection `before / after` (cost, value, latency).
4. **Crée ou active une Adaptive policy** — triggers (`confidence_below: 0.7`, `latency_above_ms: 5000`), allowed_actions (`switch_model`, `escalate_hitl`, `fallback_skill`) → `POST /control-plane/adaptive`.
5. **Toggle** on/off à volonté → `POST /control-plane/adaptive/{id}/toggle`.
6. **Drill vers Contexts** (`/steering/contexts`) pour vérifier les data refs disponibles à la capability.
7. **Sauvegarde** — la politique est immédiatement prise en compte par le `run_engine`.

**Backend touché** — `control-plane/{policies,adaptive,simulate}` · `contexts` · `capabilities`.

---

## Persona 3 — Alex, System Builder (AI Engineer)

**Mission** — composer un system qui livre la capability cible en coût/latence acceptable.

**Jobs-to-be-done**
- Choisir les skills, le reasoning, le modèle.
- Brancher un Context (données, mémoire, permissions).
- Tester avant de publier.

**Vue d’entrée** — `/systems/new` (wizard multi-étapes).

---

### Alex — Workflow complet (Builder wizard)

1. **Objective** — choisit la capability cible (`GET /capabilities/catalog`).
2. **Skills** — sélectionne les skills bound (badges runtime `bound/stub/unbound`), vérifie `/skills/runtime-health`.
3. **Context** — réutilise un `Context` existant ou en crée un (`POST /contexts` — data refs Qdrant, filtres, permissions).
4. **Policy** — renseigne `default_prompt_type`, `default_model`, `retrieval_mode_default` (`auto | fast | rich | HAH | CHAH`).
5. **Budget** — ControlPolicy locale (cost max, latency max, HITL).
6. **Review** — preview du payload, diff vs. defaults workspace.
7. **Publish** — `POST /systems` — le system est disponible dans `/systems`.
8. **Test immédiat** — bouton *Try in chat* → `/systems/:id` ouvre le chat panel ; chaque message déclenche un Run (`POST /systems/{id}/runs` background).

**Backend touché** — `systems` · `skills` · `capabilities` · `contexts` · `control-plane` · `reasoning`.

---

## Persona 4 — Claire, Business Analyst

**Mission** — obtenir des réponses fiables et traçables, adaptées à son domaine.

**Jobs-to-be-done**
- Poser des questions avec le bon reasoning / retrieval mode.
- Comprendre **pourquoi** la réponse, via un reasoning trail.
- Revenir à un run précédent, le rejouer, exporter.

**Vue d’entrée** — `/systems/:id` (onglet *Chat*).

---

### Claire — Workflow complet

1. **Ouvre le system** `/systems/:id` — overview, onglet *Chat*.
2. **Choisit un reasoning override** (chip dans le chat : `multi_hop`, `comparison`, …) — transmis comme `prompt_type` dans `POST /chat`.
3. **Force un retrieval mode** si besoin — chip `HAH` / `CHAH` → `rag_mode_override` dans la requête.
4. **Reçoit la réponse** en SSE ; bloc « reasoning trail » rend les decision steps + skill invocations (avec coût et latence par skill).
5. **Ouvre l’audit post-chat** — claim audit (`POST /evaluation/score`), radar d’évaluation (`GET /evaluation/latest`).
6. **Clique sur *Runs*** → `/runs` filtré sur ce system, ouvre un `Run` → timeline (skills invoqués), inputs/outcomes JSON, checkpoints, erreurs.
7. **Rejoue** un run ou l’**exporte** (audit log via `POST /audit`).

**Backend touché** — `chat` · `systems/{id}/runs` · `runs` · `evaluation` · `audit` · `voice` (opt.).

---

## Persona 5 — Léo, Knowledge Curator

**Mission** — garantir que les systems disposent des bons datasets, propres et autorisés.

**Jobs-to-be-done**
- Ingérer de la donnée (docs, SharePoint, batch).
- Organiser en collections Qdrant + contexts.
- Monitorer la fraîcheur et l’usage.

**Vue d’entrée** — `/knowledge` + `/steering/contexts`.

---

### Léo — Workflow complet

1. **Dépose des fichiers** dans `/knowledge` — `POST /documents/upload` ou `upload-batch` (PDF, DOCX, TXT, …).
2. **Indexation** — pipeline `document_ingestion_v1` → chunking, embeddings, insertion Qdrant.
3. **Gère les collections** — `GET /documents/collections`, `POST /documents/collections`, `DELETE /documents/collections/{name}`.
4. **Connecte SharePoint** (optionnel) — `POST /sharepoint/connect` (OTP + crypto), sync (`sharepoint_ingestion_v1` — stub aujourd’hui).
5. **Crée un Context** dans `/steering/contexts` → référence une collection, scope des permissions, attache à des systems.
6. **Observe l’usage** — `/resources` affiche quels systems pinnent quels modèles et quels contexts sont branchés.
7. **Intelligence** — programme des batches (`/intelligence` → `intelligence_batch_v1`) pour suivre l’actualité d’un domaine.

**Backend touché** — `documents` · `contexts` · `sharepoint` · `intelligence` · `skills (registry)`.

---

## Persona 6 — Nadia, Governance Officer

**Mission** — garantir la conformité, l’audit et les accès.

**Jobs-to-be-done**
- Consulter l’audit trail complet.
- Gérer les rôles et sessions.
- S’assurer que les politiques de contrôle sont actives et respectées.

**Vue d’entrée** — `/governance/audit` + `/governance/access`.

---

### Nadia — Workflow complet

1. **Audit log** `/governance/audit` — `GET /audit?from=…&to=…&actor=…` ; filtres par scope (system, capability, run, decision).
2. **Detail d’une ligne** — payload JSON intégral, lien vers la Decision source ou le Run.
3. **Rôles & accès** `/governance/access` — utilisateurs, sessions actives (`/sessions`), MFA, password reset.
4. **Vérifie la couverture** — pour chaque capability : ControlPolicy active ? HITL configuré ? Modèles autorisés respectés ?
5. **Examine les Decisions `applied`** — rationale + impact estimé + qui a approuvé (`approved_by`, `approved_at`).
6. **Exporte** — l’audit summary (`GET /audit/summary`) pour rapport trimestriel.

**Backend touché** — `audit` · `sessions` · `auth` · `control-plane` · `hypervisor/decisions`.

---

## 13. Mapping UI ↔ Backend — exhaustif (1/3)

| Écran                           | Endpoints principaux                                                     |
|---------------------------------|--------------------------------------------------------------------------|
| `/hypervisor`                   | `GET /hypervisor/aggregate` · `POST /hypervisor/what-if`                 |
| `/hypervisor` (feed)            | `GET /hypervisor/decisions` · `GET /hypervisor/decisions/{id}`           |
| `/steering`                     | `GET /control-plane/policies` · `PATCH /control-plane/policies/{id}`     |
| `/steering` (adaptive)          | `GET|POST|PATCH|DELETE /control-plane/adaptive` · `POST .../toggle`      |
| `/steering` (simulate)          | `POST /control-plane/simulate`                                           |
| `/steering/contexts`            | `GET|POST|PATCH|DELETE /contexts`                                        |

---

## 13. Mapping UI ↔ Backend — exhaustif (2/3)

| Écran                           | Endpoints principaux                                                     |
|---------------------------------|--------------------------------------------------------------------------|
| `/capabilities`                 | `GET /capabilities/catalog` · `GET|POST /capabilities`                    |
| `/capabilities/:id`             | `GET /capabilities/{id}` · `PATCH …`                                     |
| `/skills`                       | `GET /skills` · `GET /skills/{slug}` · `GET /skills/runtime-health`      |
| `/systems`                      | `GET /systems` · `POST /systems`                                         |
| `/systems/:id`                  | `GET /systems/{id}` · `PATCH …` · `DELETE …`                             |
| `/systems/new`                  | idem + `GET /reasoning/templates` · `GET /models`                        |
| `/systems/:id` (Runs tab)       | `GET /systems/{id}/runs` · `POST /systems/{id}/runs`                     |

---

## 13. Mapping UI ↔ Backend — exhaustif (3/3)

| Écran                           | Endpoints principaux                                                     |
|---------------------------------|--------------------------------------------------------------------------|
| `/runs`                         | `GET /runs?limit=&offset=&status=`                                       |
| `/runs/:runId`                  | `GET /runs/{id}` (skill_invocations, outcome, impact)                    |
| `/knowledge`                    | `POST /documents/upload*` · `GET /documents/list` · `GET /documents/stats` |
| `/observability`                | `GET /metrics` · `GET /metrics/summary` · `GET /metrics/cache`           |
| Chat (dans `/systems/:id`)      | `POST /chat` (SSE) · `POST /evaluation/score` · `POST /audit`            |
| `/governance/audit`             | `GET /audit` · `GET /audit/summary`                                      |
| `/governance/access`            | `GET /sessions` · `POST /auth/*`                                         |
| `/intelligence`                 | `GET /intelligence/*` (batches)                                          |
| `/tasks`                        | `GET|POST /tasks` · `POST /tasks/{id}/run`                               |
| `/resources`                    | `GET /models` + `GET /systems` (usage par modèle)                        |

---

## 14. Capacités RAG — HAH / CHAH / chains

| Mode             | Skill slug            | Chaîne utilisée                          |
|------------------|-----------------------|------------------------------------------|
| `auto` / `fast`  | `llm_rag_answer_v1`   | Routeur par défaut (retrieval + synth.)  |
| `rich`           | `llm_rag_answer_v1`   | Retrieval élargi + reranker               |
| `HAH`            | `chain_hybrid_v1`     | `app.services.rag.chains.hybrid`         |
| `CHAH`           | `chain_mixed_hah_v1`  | `app.services.rag.chains.mixed_hah`      |
| Naïve (baseline) | `chain_naive_v1`      | `app.services.rag.chains.naive`          |

- Migré depuis les modules Streamlit historiques (`src/customchain*.py`) → `backend/app/services/rag/chains/`.
- Archive des modules legacy : `archive/customchains/` (référence).
- Paramétrable via `retrieval_mode_default` (system) ou `rag_mode_override` (per-query).

---

## 15. Reasoning templates

`GET /reasoning/templates` renvoie les templates canoniques :

- `auto` — heuristique de routage.
- `summarization` — condensation.
- `comparison` — mise en parallèle d’items.
- `multi_hop` — chaînes de raisonnement multi-étapes.
- `complex_reasoning` — chain-of-thought étendu.

Exposés en **chip** dans le chat (per-query) et en **champ** dans le Builder step *Policy* (`default_prompt_type`).
Chaque message assistant affiche un **badge** indiquant le template effectif.

---

## 16. Evaluation

Dashboard `/observability` + page dédiée :

- `POST /evaluation/score` — scoring multi-dimensions (faithfulness, relevance, coverage, …).
- `GET /evaluation/dimensions` — liste des axes.
- `GET /evaluation/latest` — dernier radar.
- `GET /evaluation/history` — time-series.
- **Claim audit** — skill `claim_audit_v1` (`POST /evaluation/score` avec claims).
- Bouton *Run evaluation* sur un System.

---

## 17. Intelligence

Veille automatisée (skill `intelligence_batch_v1`) :

- Scheduler horaire (thread Python au démarrage de l’app).
- Sources RSS / web → ingestion → rerank → persist.
- UI `/intelligence` (News Lab) pour parcourir, filtrer, épingler.
- Déclenchable manuellement ; configurable par workspace.

---

## 18. Voice (stub aujourd’hui)

- `POST /voice/transcribe` — Whisper (stub backend, à wirer).
- `POST /voice/synthesize` — TTS (stub backend, utilisé côté client).
- Chat panel supporte le record + bouton TTS sur la réponse.

---

## 19. Connecteurs & Apps

- **SharePoint OTP** — backend complet (`/sharepoint/*`), skill `sharepoint_ingestion_v1` (stub en attente de credentials demo).
- **Apps catalog** (`/apps`) — galerie des intégrations configurables via drawer.
- **Resources** (`/resources`) — vue d’ensemble des modèles et de leur usage par system.

---

## 20. User stories livrées — Wave A

**Thème — Skills runtime & mental model canonique**

1. En tant que AI engineer, je veux un **runtime health** tri-state pour savoir quels skills sont réellement bound.
   → `GET /skills/runtime-health`.
2. En tant que RAG operator, je veux **HAH / CHAH** accessibles comme skills canoniques.
   → `chain_hybrid_v1`, `chain_mixed_hah_v1`, `chain_naive_v1`.
3. En tant qu’opérateur, je veux que tous les appels UI passent par les **routes canoniques** `/systems` + `/runs` (plus de `/agents` ni `/traces`).

---

## 21. User stories livrées — Wave B

**Thème — Reasoning & retrieval modes**

4. En tant qu’analyste, je veux **choisir un template de raisonnement** (multi_hop, comparison, …) directement dans le chat.
   → chip + `ChatRequest.prompt_type`.
5. En tant que builder, je veux fixer un **reasoning template par défaut** sur un system.
   → Builder step *Policy* · `default_prompt_type`.
6. En tant qu’analyste, je veux **forcer HAH / CHAH** pour une question donnée.
   → `ChatRequest.rag_mode_override`.

---

## 22. User stories livrées — Wave C

**Thème — Contexts & defaults per-system**

7. En tant que builder, je veux **épingler un modèle** à un system.
   → `default_model` + `GET /models`.
8. En tant que data curator, je veux **CRUD complet** sur les contexts (PATCH, DELETE).
   → `/contexts` + page `/steering/contexts`.
9. En tant que builder, je veux **réutiliser un context existant** à la création d’un system.
   → Builder step *Context* · picker.
10. En tant qu’opérateur, je veux voir **quels systems pinnent un modèle donné**.
    → `/resources` avec badges d’usage.

---

## 23. User stories livrées — Wave D

**Thème — Runs canoniques & cleanup**

11. En tant qu’opérateur, je veux un **browser de Runs** au lieu de traces.
    → `/runs` + `/runs/:runId` drill-down (timeline skills, outcome JSON, erreurs, checkpoints).
12. En tant qu’utilisateur, je veux que les **bookmarks `/observability/traces` continuent de marcher**.
    → redirect → `/runs`.
13. En tant que governance officer, je veux un **shell gouvernance** avec onglets audit / accès.
    → `/governance/audit` · `/governance/access`.

---

## 24. User stories livrées — Wave E

**Thème — Adaptive policies & What-If**

14. En tant que steward, je veux **activer/désactiver/supprimer** une adaptive policy sans passer par un JSON manuel.
    → `POST /control-plane/adaptive/{id}/toggle`, `DELETE …`, `PATCH …`.
15. En tant que steward, je veux **filtrer les policies** par capability ou system.
    → `GET /control-plane/adaptive?scope=…&target_id=…`.
16. En tant que CAIO, je veux un **What-If global** avec 4 leviers canoniques sur le portefeuille.
    → panel Hypervisor + `POST /hypervisor/what-if`.
17. En tant que CAIO, je veux un **feed de décisions paginable** avec drawer détail.
    → `GET /hypervisor/decisions` (status/scope/kind/limit/offset) + `GET /hypervisor/decisions/{id}`.

---

## 25. User stories livrées — Wave F

**Thème — Documentation & déploiement**

18. En tant qu’équipe produit, je veux **un mental model partagé** (UI / API / runtime).
    → `docs/mental-model.md` réécrit.
19. En tant qu’AI engineer, je veux **la map slug → module** pour savoir ce qui est bound.
    → `docs/skills-runtime.md`.
20. En tant que PM, je veux un **changelog lisible** des waves A → F.
    → `CHANGELOG.md`.
21. En tant qu’utilisateur, je veux que **les icônes du cockpit apparaissent** (rail, thème, breadcrumb).
    → fix sanitizer `ck-glyph` (bypass SVG trust).

---

## 26. Invariants & garanties

- **Un Run appartient à exactement un System.**
  Un System appartient à une Capability (ou `null` pour les sandboxes).
- **Une Decision a un scope** ∈ `portfolio | capability | system | run`.
  `target_id` n’est nullable que pour `portfolio`.
- **Précédence defaults** — per-query > per-system > workspace.
- **Adaptive policies** portent toujours un `scope` + `target_id` pour permettre au cockpit Steering de les filtrer.
- **Legacy API** — `/agents`, `/traces` restent servis mais renvoient `X-Deprecated`.
- **Runtime health** — un skill `unbound` n’émet pas d’exception silencieuse : `_unimplemented` remonte un outcome d’erreur explicite dans le Run.

---

## 27. Ce qui reste à faire (prochaines itérations)

### Court terme
- Wire **voice** (Whisper + TTS) côté backend.
- Wire **sharepoint_ingestion_v1** une fois les credentials demo disponibles.
- Éditeur de **custom chains** dans `/orchestration` (scaffold fait, à compléter).

### Moyen terme
- **Évaluation en boucle** — déclenchement auto d’un scoring post-run selon seuils.
- **Recommandations proactives** — générer des Decisions à partir de l’analyse agrégée.
- **Multi-tenant avancé** — quotas par workspace, facturation, isolation Qdrant renforcée.

### Long terme
- **Marketplace de capabilities** — packs industry prêts à l’emploi.
- **Simulation hors ligne** — rejouer un run sur une policy alternative.

---

## 28. Annexes — Raccourcis clavier

| Raccourci              | Action                                    |
|------------------------|-------------------------------------------|
| `⌘K` / `⌃K`            | Command palette (vues + actions)           |
| `⌘Z`                   | Zoom-in sémantique (breadcrumb)            |
| `⇧⌘Z`                  | Zoom-out sémantique                        |
| `Esc`                  | Ferme drawers et menus                     |
| `/` (futur)            | Focus sur la recherche courante            |

---

## 29. Annexes — Glossaire

- **Capability** — blueprint d’outcome métier, universel ou client-spécifique.
- **Skill** — unité d’exécution atomique (slug versionné, status tri-state).
- **System** — composition opérationnelle liée à une Capability.
- **Run** — exécution unique avec timeline, outcome, impact.
- **Decision** — entrée du journal de pilotage (recommandation / what-if / action).
- **Lever** — dimension de réglage (resource, velocity, autonomy, risk_tolerance).
- **HITL** — Human-In-The-Loop (point de validation manuel).
- **HAH / CHAH** — Hybrid / Composite Hybrid Answer Harvesting.

---

## 30. Livraison post-réalignement — 2026-04-21

Le plan `docs/agentium-realignment-plan.md` a été exécuté intégralement (26 tickets, 5 waves). Ce qui change concrètement :

- **Outcome canonique hybride** — dérivation auto (`cost`, `value`, `confidence`, `efficiency`) + override opérateur tracé via `value_source` et `operator_value_note`.
- **Decision state machine** — `proposed → accepted → rejected → applied`, patch effectif appliqué sur `Capability` / `ControlPolicy` / `AdaptivePolicy`, replayable depuis le feed Hypervisor.
- **4 leviers de contrôle** — `resource`, `velocity`, `autonomy`, `risk_tolerance`, partagés par `/control-plane/simulate`, `/hypervisor/what-if`, le Steering Console et l'Impact Preview universel (<300 ms).
- **Execution mode first-class** — `real_time_decision`, `batch_processing`, `event_driven_automation`, `continuous_monitoring`, `human_augmented` avec `execution_profile` SLA, visible dans System Overview et le Builder.
- **Workspace modes** — bascule `builder` / `operator` / `executive` dans la page workspace, avec révélation progressive de l'Hypervisor et du ROI selon la persona.
- **Runtime health 4 états** — `bound | stub | unbound | catalog_only`. Resources, Apps et Connectors affichent leur statut réel (fin du fake-on). RAG presets gatés par `/skills/runtime-health`.
- **Builder 6 étapes** — Objective → Capability → **Skills** → Context → Policy → Launch, avec gate "cannot launch if any skill is unbound".
- **Gouvernance audit** — filtres actor/kind, pagination, export CSV, bannière RBAC read-only honnête.
- **Info-bulles persona-aware** — `<ck-help>` + `/help-content`, 17 IDs couvrent Hypervisor (feed, what-if, Accept/Reject/Apply, ranking), Steering (4 leviers), Builder (4 étapes), Runs (list + override), Workspace (mode switch). Chaque tooltip sert `builder | operator | executive` avec copy adaptée.
- **Legacy sunset** — `/agents` et `/traces` répondent avec `X-Deprecated: true` + `X-Canonical-Alternative`, retrait prévu en v0.6.

---

## 31. Références

- `docs/mental-model.md` — source de vérité du modèle produit (avec delivery log 2026-04-21 en tête).
- `docs/skills-runtime.md` — mapping slug → module + table des endpoints dépréciés.
- `docs/agentium-realignment-plan.md` — plan d'exécution T1.1 → T5.6 (livré).
- `CHANGELOG.md` — waves A → F.
- Front — `frontend-ng/src/app/features/{hypervisor, steering, systems, runs, contexts, governance, workspace, apps, resources}/…`
- Back — `backend/app/api/v1/endpoints/` + `backend/app/services/{run_engine, skills_registry, rag, decisions}/…`
- Démo — `https://agentium.papai.ai`

---

# Q&A

<br>

> « Tout ce qui se passe dans le produit doit être **nommable**,
> **traçable** et **pilotable**. »

<br>

**Merci.**
