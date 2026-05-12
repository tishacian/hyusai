# Agentium — Mental Model

_Single source of truth for Agentium's product vision, canonical entities, runtime semantics, and the concrete state of what is currently implemented in the codebase._

---

## Post-realignment delivery log — 2026-04-21

The realignment plan (`docs/agentium-realignment-plan.md`) landed across five waves and 26 tickets. The following concepts moved from 🟡 **Partial** to ✅ **Shipped**:

| Area | Mental model section | Before | After |
|------|----------------------|--------|-------|
| Canonical `Outcome` (cost/value/confidence/efficiency) with `value_source` hybrid (auto-derive + operator override) | §22.3 | 🟡 Partial | ✅ Shipped |
| Decision state machine `proposed → accepted → rejected → applied` with enactment patch | §23.5–§23.6 | 🟡 Partial | ✅ Shipped |
| Hypervisor Act — Accept/Reject/Apply feeds policy patch on `Capability` / `ControlPolicy` / `AdaptivePolicy` | §23.6 | 🟡 Partial | ✅ Shipped |
| `ControlPlaneVector` 4 axes (`resource`, `velocity`, `autonomy`, `risk_tolerance`) used by `simulate`, `what-if`, Steering, Hypervisor | §18.2, §36 | 🟡 Partial | ✅ Shipped |
| Universal Impact Preview (<300ms) on every policy lever | §36 | 🔵 Planned | ✅ Shipped |
| Runtime health 4-state (`bound` / `stub` / `unbound` / `catalog_only`) unified across Skills, RAG presets, Builder | §9, §30 | 🟡 Partial | ✅ Shipped |
| Semantic zoom context shared across Capability → System → Run with persistent breadcrumb | §12, §37 | 🟡 Partial | ✅ Shipped |
| Builder restored to 6 steps (Objective → Capability → Skills → Context → Policy → Launch) with unbound-skill gate | §29 | 🟡 Partial | ✅ Shipped |
| RAG presets (`Auto` / `Semantic` / `Hybrid` / `HAH` / `OmniRAG`) gated by `/skills/runtime-health` | §16 | 🟡 Partial | ✅ Shipped |
| Title-bar live telemetry from `/telemetry/live` with neutral idle state | §38 | 🟡 Partial | ✅ Shipped |
| `execution_mode` first-class on `System` (`real_time_decision` / `batch_processing` / `event_driven_automation` / `continuous_monitoring` / `human_augmented`) with `execution_profile` SLA | §20.6 | 🔵 Planned | ✅ Shipped |
| Workspace modes `builder` / `operator` / `executive` / `demo` with progressive disclosure and demo-safe runtime redaction | §34, §38 | 🔵 Planned | ✅ Shipped |
| Resources / Apps / Connectors honest catalog-only labelling (no fake wiring) | §30 | 🟡 Partial | ✅ Shipped |
| Governance audit — actor / kind filters, CSV export, pagination, read-only RBAC banner | §33 | 🟡 Partial | ✅ Shipped |
| Persona-aware help tooltips (`<ck-help>` + `/help-content` registry, 17 IDs covering Hypervisor / Steering / Builder / Runs / Workspace) | §38 | 🔵 Planned | ✅ Shipped |
| Deprecation headers on `/agents` and `/traces` (`X-Deprecated: true`, `X-Canonical-Alternative: /systems` or `/runs`) | §0.2 | 🟡 Partial | ✅ Shipped |

### Remaining 🟡 / 🔵 concepts (explicitly out of scope for this wave)

- Dynamic RBAC with custom roles (§33) — read-only built-in roles shipped, full CRUD deferred.
- Marketplace / certification / billing (§35) — ledger Tier 4.
- Card-transformation polymorph, Focus Mode, radial steering (§36.4) — ledger Tier 2.
- Backend connector runtime for Apps (§30) — catalog-only with "Request wiring" CTA.
- papAI interop bridge (§40) — ledger Tier 5.

---

## How to read this document

This document fuses two layers:

1. **Vision** — the full 41-section product spec authored as `mental-model-draft.md`. Every conceptual paragraph is preserved verbatim, in its original order.
2. **Reality** — machine-checked annotations describing what is actually shipped in the repository (as of `v0.4.0`, audit waves A–F).

### Status legend

| Badge | Meaning |
|-------|---------|
| ✅ **Shipped** | Fully implemented: backend + API + UI + wired end-to-end. |
| 🟡 **Partial** | Concept present in code but incomplete (stub, scaffold, missing UI, or missing persistence). |
| 🔵 **Planned** | Conceptual only. No backend/UI implementation yet. |
| ⚠️ **Legacy** | Implemented, but deprecated in favor of a canonical path. Retained behind `X-Deprecated` header or compat route. |

Each `## N.` heading carries a status badge. Inline callouts of the form:

> **✅ Shipped in v0.4.0** — `backend/path`, `/api/route`, `frontend-ng/src/.../component.ts`

map the prose to concrete artifacts. Where the text describes an unbuilt concept, a callout begins with **🔵 Vision** or **🟡 Gap**.

### Companion docs

- `docs/skills-runtime.md` — canonical slug → module mapping with tri-state status (`bound | stub | unbound`).
- `docs/deck-product-review.md` — Marp slide deck that narrates the same model for the product team.
- `CHANGELOG.md` — per-wave delivery log (Wave A through Wave F).

---

## 0. Executive summary (canonical, shipped state)

> **✅ Shipped in v0.4.0** — this section replaces the previous concise `mental-model.md`.

Agentium is an **operating system for intelligent systems**: you declare an **objective**, bind it to **capabilities** and **skills**, and let the runtime produce measurable, governed, continuously optimized **decisions**.

### 0.1 Canonical entities (persisted in Postgres)

```
System        objective, capability_id, flow_definition,
              default_prompt_type, default_model,
              retrieval_mode_default, status
Capability    blueprint (input/output contract, required skills,
              default flow)
Skill         slug, version, type, cost_per_call, latency,
              runtime status (bound | stub | unbound)
Context       data_refs, memory, history, environment, constraints
ControlPolicy max_cost, max_latency, HITL threshold, allowed_models
AdaptivePolicy scope, target_id, triggers, allowed_actions,
              constraints, enabled
Run           system_id, status, input_ref, outcome,
              cost, latency, confidence, skill_invocations[]
Decision      scope, target_id, kind, status, rationale,
              impact_estimate, approved_by
Impact        aggregated cost / value / ROI per capability & system
```

### 0.2 Canonical API surface

| Route | Purpose |
|-------|---------|
| `/catalog/endpoints`, `/catalog/surfaces` | Machine-readable Agentium surface catalog (UI route ↔ API ↔ mental object ↔ stability status) |
| `/blueprints/workspace/*` | Workspace Blueprint export/import: structure and configuration without members, secrets, files or vectors |
| `/systems`, `/systems/:id`, `/systems/:id/runs` | CRUD + execution |
| `/capabilities`, `/capabilities/:id` | Business-level catalog |
| `/skills`, `/skills/runtime-health`, `/skills/:slug` | Registry + tri-state health |
| `/runs`, `/runs/:id` | Canonical run surface (replaces `/traces`) |
| `/contexts`, `/contexts/:id` | First-class context objects |
| `/control-plane/policies` | Control policies CRUD |
| `/control-plane/adaptive` (+ `/toggle`) | Adaptive policies CRUD, scoped |
| `/control-plane/simulate` | Simulate a policy change |
| `/hypervisor/aggregate` | Portfolio ROI / cost / value |
| `/hypervisor/what-if` | Portfolio levers (resource, velocity, autonomy, risk_tolerance) |
| `/hypervisor/decisions`, `/hypervisor/decisions/:id` | Decisions feed |
| `/reasoning/templates` | Reasoning prompt catalog |
| `/models` | LLM registry (Ollama + Azure) |
| `/chat` | SSE-streamed chat against a System |
| `/documents/*` | Upload, search, canonical collection ledger, async ingestion jobs, preview |
| `/knowledge-capture/*` | Expert Knowledge Capture workbench: plans, sessions, events, proposals, retrieval prefetch |
| `/voice/*` | STT/TTS and streaming voice session runtime |
| `/iam/*` | Workspace IAM matrix, config, member role templates and dry-run evaluation |
| `/sftp/*` | Secure Deposit administration, staging queue, preview/download/promotion |
| `/deposit-links/*` | Public external deposit portal API, password/session protected |
| `/evaluation/*` | Radar, history, claim audit |
| `/audit` | Governance log |
| `/intelligence`, `/tasks`, `/metrics`, `/presets` | Ops and configuration surfaces |

Compatibility and deprecated routes remain active but must be catalogued:
`/agents` → `/systems`, `/traces` → `/runs`, `/settings` → `/presets`,
plus legacy document collection routes retained for older callers. New
surfaces must appear in `/catalog/endpoints` before shipping.

### 0.3 Canonical skills runtime

| Slug | Status | Module |
|------|--------|--------|
| `llm_rag_answer_v1` | ✅ bound | `backend/app/services/skills/llm_rag_answer.py` |
| `semantic_search_v1` | ✅ bound | `backend/app/services/skills/semantic_search.py` |
| `document_ingestion_v1` | ✅ bound | `backend/app/services/skills/document_ingestion.py` |
| `chain_naive_v1` | ✅ bound | `backend/app/services/skills/chain_naive.py` |
| `chain_hybrid_v1` (HAH) | ✅ bound | `backend/app/services/skills/chain_hybrid.py` |
| `chain_mixed_hah_v1` (CHAH) | ✅ bound | `backend/app/services/skills/chain_mixed.py` |
| `eval_radar_v1` | ✅ bound | `backend/app/services/skills/eval_radar.py` |
| `claim_audit_v1` | ✅ bound | `backend/app/services/skills/claim_audit.py` |
| `intelligence_batch_v1` | ✅ bound | `backend/app/services/skills/intelligence_batch.py` |
| `audit_log_v1` | ✅ bound | `backend/app/services/skills/audit_log.py` |
| `ollama_llm_v1`, `azure_llm_v1` | ✅ bound | `backend/app/services/llm/*` |
| `sharepoint_ingestion_v1` | 🟡 stub | schemas present, ingestion not wired |
| `voice_transcribe_v1`, `voice_tts_v1` | ✅ bound | `backend/app/services/voice_runtime.py` |
| `knowledge_gap_analysis_v1`, `expert_interview_plan_v1` | ✅ bound | `backend/app/services/knowledge_capture.py` |
| `expert_answer_evaluator_v1`, `capture_structuring_v1` | ✅ bound | `backend/app/services/knowledge_capture.py` |

See `docs/skills-runtime.md` for full contract.

### 0.4 Canonical UI routes (Angular 20, zoneless)

```
/hypervisor              Balance sheet + what-if (4 levers) + decisions feed
/steering                Control policies + adaptive policies + simulate
/steering/contexts       First-class context manager
/capabilities            Business catalog (+ drill-down /capabilities/:id)
/skills                  Runtime registry with tri-state health badges
/systems                 List, drill-down /systems/:id, builder /systems/new
/runs                    Canonical run list + /runs/:runId decision trail
/observability           Health, events, SLO
/governance/audit        Structured audit log
/governance/access       Roles & permissions
/governance/blueprints   Workspace Blueprint export/import
/orchestration           Custom chain editor (🟡 scaffold)
/knowledge               Document ingestion, collections, previews
/intelligence            Scheduled batch insights
/tasks                   HITL review queue (🟡 partial)
/resources               Model pinning, provider credentials
/apps                    Connectors & SaaS apps (🟡 catalog only)
```

Global chrome: ⌘K command palette ✅, ⌘Z / ⇧⌘Z semantic zoom ✅, theme `light | dark | system` ✅, custom SVG glyph set ✅ (sanitizer-safe).

### 0.5 Invariants (enforced in code)

1. **Every Run has a canonical decision trail.** The legacy `trace` concept is gone; `skill_invocations[]` is the single source of execution evidence.
2. **Every Skill declares its runtime status.** `bound | stub | unbound` is returned by `/skills/runtime-health` and rendered in the UI — no silent stubs.
3. **Every System carries its defaults.** `default_prompt_type`, `default_model`, `retrieval_mode_default` are persisted fields, consumed by `run_engine` and RAG skill wrappers.
4. **Every adaptive policy is scoped.** `scope ∈ {portfolio, capability, system}` + `target_id` — no dangling global toggles.
5. **Every deprecated endpoint advertises itself.** `/agents`, `/traces` respond with `X-Deprecated: true` and a redirect hint.

---

---

## 1. Vision · ✅ Shipped (vocabulary), 🟡 Partial (papAI convergence)

Agentium is not an agent builder.

Agentium is an **operating system for intelligent systems**, designed to transform business objectives into measurable outcomes through orchestrated, observable and optimizable AI systems.

It is the **agentic counterpart of papAI**:

- papAI = orchestration of data, models and workflows
- Agentium = orchestration of intelligence, reasoning and decision systems

Agentium is designed as a **standalone product**, but shares the same architectural philosophy as papAI to enable a future convergence into a unified platform.

> **✅ Shipped in v0.4.0** — Agentium runs as a standalone product with its own frontend (`frontend-ng/`), backend (`backend/app/`), and deployment (`omnirag-demo` VM, `agentium.papai.ai`).
>
> **🔵 Vision** — Convergence with papAI (shared object model, unified catalog). Not yet wired. See §17 for the detailed phase plan.

---

## 2. Core Paradigm Shift · ✅ Shipped

### From Tools to Systems

Traditional platforms:

- Build workflows
- Configure models
- Execute pipelines

Agentium:

- Defines objectives
- Composes capabilities
- Runs autonomous systems
- Measures value

---

### From Features to Value Loops

Agentium is built around a **closed-loop system**:

Objective → System → Execution → Measurement → Optimization

This loop is the **core mental model** and must be visible in the product at all times.

> **✅ Shipped in v0.4.0** — the loop is materialized end-to-end:
> `System Builder` (`/systems/new`) → `Run trigger` (`POST /systems/:id/runs`) → `Run view` (`/runs/:runId`) with decision trail → `Impact` aggregation (`/impact`) → `Hypervisor what-if` (`/hypervisor/what-if`) closes the loop back to allocation decisions.

---

## 3. Core Concepts (Product Language) · ✅ Shipped

Agentium introduces a structured, layered vocabulary:

### System (central concept)

A System is a self-contained unit that:

- Receives an objective
- Uses capabilities
- Executes tasks
- Produces measurable outcomes

```
System = Objective + Flow + Skills + Knowledge + Runs + Impact
```

> **✅ Shipped** — `backend/app/models/system.py`, `backend/app/schemas/system.py`, UI `/systems/:id`.

---

### Capability

A Capability is a **business-level function**:

- "Contract Risk Detection"
- "Document Understanding"
- "Delay Prediction"
- "Expert Knowledge Capture"

Capabilities are what the business buys and understands.

`Expert Knowledge Capture` is the voice-ready capability for preserving
expert reasoning. It uses a workspace `Context` / Knowledge scope to
identify gaps, prepares a time-boxed interview plan, evaluates expert
answers during the session, and emits a human-reviewed knowledge update
proposal before ingestion. Its first runtime is a robust cascade
`recording → STT → RAG/plan/evaluator → segmented TTS`; GPU realtime
providers are isolated behind `VoiceRuntimeProvider` until user tests
prove a net gain in fluency without losing precision or auditability.

> **✅ Shipped** — `backend/app/models/capability.py`, `/capabilities` route with drill-down. Pricing / ROI model fields exist in the schema but are not yet billed (see §22).

---

### Skill

A Skill is a **cognitive primitive**:

- Typed input/output
- Cost
- Latency
- Metrics
- Version

Examples:

- OCR
- NER
- Classification
- Scoring
- LLM reasoning

Skills are the **atomic units of intelligence**.

> **✅ Shipped** — `backend/app/services/skills_registry/`, `/skills` route with tri-state health. See §0.3 for the canonical list.

---

### Flow

A Flow is a **composition of Skills**.

It represents how intelligence is structured, but is abstracted from most users.

> **🟡 Partial** — `flow_definition` JSONB column exists on `System`, but the **custom chain editor** at `/orchestration` is scaffold only. The System Builder wizard composes flows implicitly via capability selection.

---

### Run

A Run is a **real execution instance** of a System.

> **✅ Shipped** — canonical surface at `/runs` and `/runs/:runId`. Replaces legacy `/traces`.

---

### Impact

Impact is the **measured value produced**:

- Time saved
- Cost reduction
- Risk avoided
- Revenue generated

> **✅ Shipped** — `/impact` aggregate, portfolio view in Hypervisor. Value estimation remains **configurable** (user-supplied ROI model per capability), not inferred.

---

## 4. Layered Abstraction Model · ✅ Shipped

Agentium is built on progressive disclosure:

### Layer 1 — Business (default)
- Systems
- Capabilities
- Impact (ROI)

### Layer 2 — Operational
- Runs
- Performance
- Errors
- Usage

### Layer 3 — Technical
- Skills
- Flows
- Models
- Tools

The UI must **never force complexity**, but always allow access to it.

> **✅ Shipped** — the semantic zoom shortcut `⌘Z` / `⇧⌘Z` (implemented in `frontend-ng/src/app/shared/cockpit/zoom.service.ts`) moves the user across the three layers while preserving context. Default entry is Layer 1 (Hypervisor → Systems).

---

## 5. UX Principles · ✅ Shipped (core), 🟡 Partial (continuous canvas)

### 5.1 Objective-First

The entry point is always:

> "What do you want to achieve?"

Not:
- Create agent
- Configure workflow

> **✅ Shipped** — System Builder wizard step 1 is literally an "Objective" field, not a flow canvas.

---

### 5.2 System-Centric UX

The UI revolves around Systems, not features.

Users interact with:
- Systems
- Runs
- Impact

Not:
- nodes
- prompts
- pipelines

> **✅ Shipped** — the cockpit side rail orders routes as `Hypervisor → Systems → Runs → Capabilities → Skills → Steering → Knowledge → …`, privileging systems over primitives.

---

### 5.3 Continuous Canvas

The interface should feel like a **continuous system surface**, not a set of pages.

- No fragmentation
- Context preserved
- Zoom-based navigation

> **🟡 Partial** — ⌘Z zoom preserves context across layers, and the breadcrumb is persistent. True "one-surface" interaction (no route changes) is not yet implemented.

---

### 5.4 Progressive Complexity

- Default = simple
- Advanced = available

Pattern:
- hover → insight
- click → expand
- focus → deep dive

> **✅ Shipped** — every System card shows KPI summary on default, click opens Overview tab, further tabs (Design / Runs / Intelligence / Settings) are advanced views.

---

### 5.5 Visible Intelligence

Agents are not black boxes.

Minimal "thinking stream":

- Retrieving knowledge
- Running analysis
- Generating output

No technical overload.

> **✅ Shipped** — chat uses SSE streaming with a "reasoning trail" panel that renders `decision_step` events. See `frontend-ng/src/app/features/chat/chat-panel.component.ts`.

---

### 5.6 System as a Living Entity

Each system has:
- Status (Live / Idle / Error)
- Recent activity
- Evolution over time

This creates trust and engagement.

> **✅ Shipped** — System list cards show live status, last run age, and a 7-day spark strip. Hybrid A+B cockpit styling adds subtle radial gradients / glows to reinforce "living organism" feel.

---

## 5bis. Navigation Model — 4 Orthogonal Axes · ✅ Shipped (axes v2), 🟡 (lens-aware data)

Agentium's navigation is deliberately **not menu-first**. It is **cognitive-first** — each surface answers a different question about the same world.

### 5bis.1 The five foundational equations

| Axis        | Question                          | Surface                                           |
| ----------- | --------------------------------- | ------------------------------------------------- |
| Hierarchy   | *Where am I?*                     | Breadcrumb zoom in the title bar                  |
| Function    | *Why am I here?*                  | Side rail — 5 verbs as lenses                     |
| Scope       | *What am I exploring?*            | Mini-rail — **Object Index** (scope switcher)     |
| Depth       | *How do I look at it?*            | `<ck-tabs>` — facets of the same object           |
| Speed       | *Give me direct access*           | Command palette (`⌘K`)                            |

Navigation is a change of **perspective**, never of **context**. The breadcrumb updates *only when the object changes*.

### 5bis.2 Canonical hierarchy (corrected)

```
Portfolio › Capability › System › Run › Skill
```

Rationale:
- **System** is the living asset.
- **Run** is an *instance of execution* of the System — one System spawns many Runs.
- **Skill** is a *component invocation inside a Run* — skills exist in the catalog, but at breadcrumb level they represent "this skill execution within this run".

The previous ordering (`System › Skill › Run`) was wrong: it placed the ephemeral (Run) below the compositional (Skill), which inverts the mental model. ⌘Z / ⇧⌘Z traverse this corrected chain.

### 5bis.3 Function axis — verbs as lenses (Option A — Outcome-injected)

Each verb is both an intent and a lens on the hierarchy. The verb does not change what object you're on; it changes **what projection** of that object you see.

| Verb        | Intent                | Lens (sublabel)                                  |
| ----------- | --------------------- | ------------------------------------------------ |
| Hypervisor  | Decide                | `balance sheet, outcomes, what-if`               |
| Build       | Create                | `Systems, Capabilities, Skills, Knowledge`       |
| Operate     | Run                   | `runtime, runs, missions`                        |
| Steer       | Optimize              | `levers, policies, simulations`                  |
| Govern      | Control               | `audit, access, settings`                        |

Same `System X` under `Operate` shows runtime metrics; under `Steer` it shows impact and levers; under `Govern` it shows audit trail. The **tabs stay identical across lenses** — only the projection of their content changes.

### 5bis.4 Scope axis — mini-rail as **Object Index** (not navigation)

The mini-rail is a **scope switcher**, not a secondary nav bar. It answers *"what type of object am I exploring within the current verb, filtered by my current breadcrumb?"*

Rules:
- The mini-rail is **contextual to the breadcrumb**. If the user is inside `Capability A`, the mini-rail hides `Capabilities` (we're already inside one) and scopes `Systems` to `Systems of Capability A`.
- Clicking an item **does not reset context**. It switches the dataset shown in the canvas; it never destroys the breadcrumb.
- The header eyebrow reads `SCOPE`, not the verb label, to make the scope-switcher role explicit.
- Clicking the already-active item is a **no-op**.

Anti-pattern (forbidden): a mini-rail listing `Systems | Capabilities | Skills` as raw routes is a **duplicated navigation** — it competes with the hierarchy and breaks the mental model, even if presented vertically.

### 5bis.5 Depth axis — tabs as **facets of the same object**

Tabs exist only under a **selected object**. They are representations of that object, never categories or destinations.

**Core rules:**

1. **Scope-locked**: tabs only render when the breadcrumb resolves to a concrete object. There are no global tabs at the route root.
2. **Object invariance**: a persistent `<ck-object-header>` (title + KPI pills like ROI / Cost / Yield) sits above the tab strip and **never changes** when the user switches tabs. This is the test of the model.
3. **Same tabs, different lens**: the tab set for a given object type (e.g. `System`) is identical across verbs. Content adapts to `currentLens()`; the header and tab strip do not.
4. **Max 4–5 visible tabs**, the rest go behind a `More` overflow. The limit is cognitive (human chunking), not arbitrary.
5. **Inline switch <300ms**, panels not destroyed between switches → scroll, selection, filters are **state-preserving**.
6. **Keyboard-first**: `⌘1 … ⌘5` bind to visible tabs via a single `TabShortcutService`; the most recently-mounted `<ck-tabs>` owns the shortcuts (avoids multi-host collisions).
7. **URLs point at objects, not at tabs**: `/systems/:id` is canonical; `?tab=...` is an optional deep-link parameter only.

**Anti-patterns (forbidden):**

- Tabs at route root (`[ Systems | Capabilities | Skills ]`) — that's navigation in disguise.
- Tabs that change the object or the breadcrumb level.
- Tabs that mix views and actions (`[ Overview | Edit | Deploy ]`) — actions belong in the object header or in panels.
- Deep-link entries in the left rail pointing to a specific tab — the rail points at verbs, not at tabs.
- Tabs whose content change resets scroll / selection / filters — breaks the "same object, different view" promise.

**Ultimate test:** *if I mask the tab strip, does the user still know where they are?*
- Yes → the model is sound.
- No → the tabs are hidden navigation and must be refactored.

### 5bis.6 Panels — transient, opportunistic views

What doesn't deserve a tab goes into a `<ck-panel>`:

- `side` panels for detail / edit / settings tied to the current object.
- `bottom` panels for logs / timeline / traces.
- `floating` panels for quick-actions / comparisons / simulations.

Panels preserve the canvas: the user never changes screen, the surface is enriched. Debug, Logs, and Settings are **never tabs** — they are panels.

### 5bis.7 Speed axis — command palette

`⌘K` opens the global palette. The rail footer exposes a `Jump to…` affordance that dispatches `window:ck:command-palette:open` so users discover it without knowing the shortcut. The palette never replaces hierarchy navigation; it accelerates it for power users.

### 5bis.8 Summary diagram

```
┌─ Breadcrumb (hierarchy) ─────────────────────────────────┐
│ Portfolio › Capability A › System X                      │
└──────────────────────────────────────────────────────────┘
┌─ Rail (verbs = lenses) ─┐  ┌─ Mini-rail (Object Index) ─┐
│ Hypervisor              │  │ SCOPE                      │
│ Build  ●                │  │ ● Systems (of Capa. A)     │
│ Operate                 │  │ ○ Skills                   │
│ Steer                   │  │ ○ Knowledge                │
│ Govern                  │  └────────────────────────────┘
└─────────────────────────┘
┌─ Object header (persistent) ─────────────────────────────┐
│ System X    ROI +120%    Cost 0.18€/u    Yield 94%       │
└──────────────────────────────────────────────────────────┘
┌─ Tabs (facets, ⌘1…⌘5) ──────────────────────────────────┐
│ Overview │ Runs │ Skills │ Knowledge │ Flows    ⋯ More  │
└──────────────────────────────────────────────────────────┘
                           │
                           ▼
                    [ Canvas morphs inline ]
                           │
                  opens ◀ ─┴─ ▶ opens
                           │
                    [ <ck-panel> overlay ]
```

> **✅ Shipped** — 5bis.1, 5bis.2 (hierarchy swap), 5bis.3 (verb sublabels), 5bis.4 (mini-rail as Object Index), 5bis.5 (tabs-as-facets via `<ck-tabs>` + `<ck-object-header>`), 5bis.6 (`<ck-panel>` primitive), 5bis.7 (rail footer → palette).
> **🟡 Partial** — 5bis.3 lens-aware *data* projection: tab content currently adapts visually on `system-view` only; capability / skill / knowledge detail pages scaffold the contract but surface neutral content per lens.

---

## 6. Value as First-Class Citizen · 🟡 Partial

### Metrics are Product, not Logs

Agentium surfaces:

#### Business level
- ROI
- Time saved
- Cost per task

#### Operational level
- Latency
- Success rate
- Cost/run

#### Technical level
- Model metrics
- Token usage

> **✅ Shipped (operational + technical)** — Run records persist cost, latency, success, token counts. `/observability` surfaces SLO.
>
> **🟡 Gap (business)** — ROI and time saved require an operator-supplied value model per capability. Presently configurable in Capability detail but not enforced or auto-derived.

---

### Pricing Model

Agentium is priced on **Capabilities**, not tokens.

```
Price = Volume × Capability Unit Price
```

Example:
- 0.20€ per contract analyzed

> **🔵 Vision** — no billing subsystem is shipped. `pricing_unit` and `unit_price` fields exist on `Capability`, but there is no metering / invoicing service.

---

### ROI Loop

Every run contributes to:

- cost tracking
- value estimation
- ROI computation

> **🟡 Partial** — cost tracking ✅, value estimation 🟡 (configurable), ROI computation ✅ (in Hypervisor aggregate, derived from persisted `cost_internal` and operator-declared `revenue_allocated` / `estimated_value`).

---

## 7. Hypervisor — Strategic Layer · ✅ Shipped

The Hypervisor is not a dashboard.

It is a **decision cockpit**.

---

### Functions

- Aggregate ROI across systems
- Compare capabilities
- Suggest optimizations
- Enable actions

---

### Decision Loop

Observe → Understand → Decide → Act → Measure

---

### Example

```
Capability: Contract Risk Detection

Cost: 3k€
Value: 25k€
ROI: +733%

→ Recommendation: Scale usage
→ Action: Increase budget
```

> **✅ Shipped in v0.4.0** — `/hypervisor` route delivers:
> - `/hypervisor/aggregate` — portfolio ROI with per-capability & per-system breakdown.
> - `/hypervisor/what-if` (POST, 4 canonical levers: `resource`, `velocity`, `autonomy`, `risk_tolerance`) — projected cost / value / confidence deltas.
> - `/hypervisor/decisions` (+ `/:id`) — paginated feed of recommendations with filter + detail drawer. UI: `frontend-ng/src/app/features/hypervisor/hypervisor.component.ts`.
>
> **🟡 Gap** — action enactment (actually reallocating budget, flipping execution mode) is informational only; the UI shows an "Approve" button that writes a `Decision` row but does not yet propagate to policy mutations.

---

## 8. Capability Catalog · 🟡 Partial

Structured in 3 layers:

### Universal
- Document understanding
- Risk detection
- Forecasting

### Industry
- Fraud detection
- Maintenance prediction

### Client-specific
- Custom business logic

> **✅ Shipped** — `/capabilities` lists a flat catalog with drill-down, seeded with universal capabilities.
>
> **🟡 Gap** — the 3-layer taxonomy (Universal / Industry / Client) is not yet enforced. Capabilities carry a `scope` field but the UI does not filter by layer. No marketplace / installation flow.

---

## 9. Skill Certification · 🟡 Partial

Each skill is evaluated on:

- Quality
- Performance
- Safety
- Business impact

---

### Certification Levels

- Basic
- Production-ready
- Enterprise-certified

---

This creates:
- trust
- marketplace potential
- differentiation

> **🟡 Partial** — the tri-state **runtime status** (`bound | stub | unbound`) is shipped and visible in `/skills`. The formal **certification level** (Basic / Production-ready / Enterprise-certified) is a planned concept; a `certification_level` column exists on `Skill` but is not evaluated by any certification pipeline.

---

## 10. Strategic Positioning · ✅ Shipped (narrative)

Agentium sits between:

- n8n (automation)
- Dify (AI builder)
- Dataiku (data platform)

But defines a new category:

> **Skill-based Agentic Operating System**

---

## 11. Relationship with papAI · 🔵 Planned

### Today
- Agentium = standalone agentic platform
- papAI = orchestration & data platform

### Tomorrow
- Unified platform:
  - papAI → data + ML + orchestration
  - Agentium → intelligence + systems + ROI

> **🔵 Vision** — Agentium runs standalone today. No cross-product API integration yet.

---

## 12. Core Differentiators · ✅ Shipped (1,2), 🟡 (3,4,5,6)

1. Objective-driven UX  ✅
2. Skill-based architecture  ✅
3. Capability-based pricing  🟡 (model exists, billing absent)
4. Built-in ROI measurement  🟡 (metrics exist, value model configurable)
5. Closed-loop optimization  🟡 (what-if levers shipped, enactment partial)
6. Hypervisor decision layer  ✅

---

## 13. Final Positioning · ✅ Shipped (narrative)

Agentium is not:
- a workflow builder
- an LLM interface
- an agent playground

Agentium is:

> **a system that turns business objectives into measurable, governed, and continuously optimized outcomes**

---

## 14. Key Product Statement · ✅ Shipped (narrative)

> You don't build agents.
> You compose intelligence into systems that generate measurable value.

---

## 15. API & Data Model · ✅ Shipped

Agentium's internal architecture is designed to reflect its conceptual model.

### Core Objects

#### System

```
System {
  id
  name
  objective
  capabilities[]
  flow_id
  status
  roi_metrics
  created_at
}
```

> **✅ Shipped** — `backend/app/models/system.py` adds `default_prompt_type`, `default_model`, `retrieval_mode_default` (see migration `005_system_defaults`). `capability_id` is singular in the implementation (one primary capability) — multi-capability systems are represented via child Runs / skills.

---

#### Capability

```
Capability {
  id
  name
  description
  input_schema
  output_schema
  skill_ids[]
  pricing_unit
  roi_model
}
```

> **✅ Shipped** — `backend/app/models/capability.py`.

---

#### Skill

```
Skill {
  id
  name
  type
  version
  input_schema
  output_schema
  cost_per_call
  latency
  metrics
  certification_level
}
```

> **✅ Shipped (registry)** / **🟡 Partial (certification_level unused)**.

---

#### Flow

```
Flow {
  id
  name
  skill_graph
  execution_mode
}
```

> **🟡 Partial** — Flow is embedded as `flow_definition` JSON on System, not a standalone entity. Editor at `/orchestration` is scaffold.

---

#### Run

```
Run {
  id
  system_id
  input_payload
  output_payload
  cost
  latency
  success
  timestamp
}
```

> **✅ Shipped** — plus `skill_invocations[]` child rows forming the decision trail.

---

#### Impact

```
Impact {
  system_id
  total_cost
  total_value
  roi
  time_saved
  error_reduction
}
```

> **✅ Shipped (aggregate)** — derived in `/impact` endpoint from Runs + capability value model.

---

### API Structure

#### Core (internal)

```
/systems
/capabilities
/skills
/flows
/runs
/impact
```

> **✅ Shipped** (except `/flows` which is not yet split from `/systems`).

---

#### Business-facing (external)

```
/analyze-contract
/predict-delay
/process-document
```

> **🔵 Vision** — no business-facing capability endpoints yet. Capabilities are invoked through the generic `POST /systems/:id/runs` contract.

---

### Design Principles

- Core vocabulary is **stable and versioned**
- External endpoints are **business-oriented and flexible**
- All objects are **traceable and auditable**

> **✅ Shipped** — all mutations are audit-logged (`/audit`) with actor, target, diff.

---

## 16. UX Mapping (Concept → Screens) · ✅ Shipped

Agentium's UI directly reflects its mental model.

---

### Systems

**Screen:** Systems List / System Detail

- List of Systems with:
  - Status
  - ROI
  - Last run
- Entry point for most users

> **✅ Shipped** — `/systems` list, `/systems/:id` detail.

---

### System Detail

Tabs or layered views:

- Overview → business KPIs
- Design → flow + skills
- Runs → execution history
- Intelligence → metrics
- Settings → governance

> **✅ Shipped** — all five tabs present in `system-view.component.ts`. Design tab currently renders a read-only flow preview; editing is deferred to the System Builder wizard.

---

### Capability Catalog

**Screen:** Capability Marketplace

- Browse by:
  - Universal
  - Industry
  - Client
- Each capability shows:
  - Description
  - ROI potential
  - Required inputs

> **🟡 Partial** — flat catalog shipped; 3-layer browsing + ROI-preview not yet.

---

### Skill Registry

**Screen:** Skill Library

- Visible in advanced mode
- Includes:
  - Certification
  - Performance metrics
  - Versioning

> **✅ Shipped** — `/skills` with runtime health, version, module binding, metrics summary.

---

### Runs

**Screen:** Execution Timeline

- Each run shows:
  - Status
  - Cost
  - Output
  - Steps executed

> **✅ Shipped** — `/runs`, `/runs/:runId` with skill invocation trail.

---

### Hypervisor

**Screen:** Strategic Cockpit

- Portfolio view:
  - ROI per capability
  - Cost vs value
- Recommendations:
  - Scale / stop / optimize
- Actions:
  - Allocate budget
  - Deploy systems

> **✅ Shipped** (view, recommendations) / **🟡 Gap** (actions write Decision records but do not yet enact).

---

### UX Principles Applied

- Same concept names across all screens ✅
- Progressive disclosure (Business → Operational → Technical) ✅
- Real-time feedback wherever possible 🟡 (see §31)

---

## 17. Migration Strategy — papAI ↔ Agentium · 🔵 Planned

Agentium is designed to converge with papAI without breaking existing paradigms.

---

### Mapping Concepts

| papAI | Agentium |
|------|----------|
| Workflow | Flow |
| Model | Skill |
| Dataset | Knowledge |
| Pipeline | System |
| Endpoint | Capability |
| Job | Run |

---

### Phase 1 — Coexistence

- Agentium runs as standalone
- papAI handles:
  - Data
  - ML
  - Orchestration
- Agentium handles:
  - Agents
  - Capabilities
  - ROI

> **✅ Shipped** — we are currently in Phase 1.

---

### Phase 2 — Interoperability

- Systems can call papAI workflows
- papAI workflows can call Agentium systems
- Shared:
  - Authentication
  - Governance
  - Logging

> **🔵 Planned** — no cross-platform calls.

---

### Phase 3 — Convergence

Unified platform:

```
papAI = Data + ML + Orchestration
Agentium = Intelligence + Systems + ROI
```

---

### Technical Convergence

- Shared object model (System / Skill / Capability)
- Unified catalog
- Unified monitoring (Hypervisor)

---

### Strategic Goal

> Create a single platform where:
- Data is processed
- Intelligence is composed
- Value is measured
- Decisions are made

---

### Key Constraint

- Never break existing papAI workflows
- Always provide mapping layers

---

### Final Outcome

A unified system where:

> papAI manages computation  
> Agentium manages intelligence  
> Hypervisor manages decisions

---

## 18. Execution & Runtime Model · ✅ Shipped (core), 🟡 (adaptation loop)

Agentium's conceptual model must be grounded in a concrete execution model to ensure scalability, reliability and alignment with papAI orchestration.

---

### 18.1 Runtime Philosophy

Agentium does not execute isolated calls.

It executes **Systems as continuous intelligent processes**.

Each System follows an execution loop:

```
Plan → Act → Observe → Evaluate → Adapt
```

> **✅ Shipped** — `backend/app/services/run_engine/` orchestrates `plan → act → observe → evaluate`. The `adapt` stage is 🟡 (AdaptivePolicy triggers exist, closed-loop re-planning is limited to skill/model switch).

---

### 18.2 System Execution Lifecycle

#### 1. Initialization

- Objective is defined
- Required capabilities are resolved
- Flow is compiled into executable graph
- Dependencies (skills, knowledge, tools) are validated

> **✅ Shipped** — `run_engine.initialize()` validates skills via `skills_registry`.

---

#### 2. Planning Phase

The system determines:
- Which skills to invoke
- In what order or structure
- With what context

This can be:
- Static (predefined flow)
- Dynamic (LLM-driven planning)

> **✅ Shipped (static)** — `flow_definition` on System drives invocation order.
>
> **🟡 Partial (dynamic)** — LLM-driven planning exists for RAG chain choice (HAH / CHAH routing) but not for arbitrary skill graphs.

---

#### 3. Execution Phase

- Skills are invoked according to the flow
- Each skill execution produces:
  - output
  - cost
  - latency
  - status

Execution modes:
- Sequential ✅
- Parallel 🟡 (supported in-chain for CHAH fan-out, not generic)
- Conditional ✅ (via flow branches)
- Event-driven 🔵

---

#### 4. Observation Phase

System collects:
- intermediate outputs
- errors
- metrics

This feeds:
- monitoring
- explainability
- adaptation

> **✅ Shipped** — every `SkillInvocation` row persists input_ref, output, status, cost, latency, confidence.

---

#### 5. Evaluation Phase

System evaluates:
- quality of output
- success criteria
- guardrails compliance

Possible outcomes:
- success
- retry
- fallback
- escalation (HITL)

> **🟡 Partial** — `eval_radar_v1` and `claim_audit_v1` skills evaluate quality when invoked. Automatic escalation to HITL is **not** wired — `tasks` queue exists but is not auto-populated by quality failures.

---

#### 6. Adaptation Phase

System can:
- adjust flow
- switch skills
- re-run steps
- trigger alternative paths

> **🟡 Partial** — AdaptivePolicy rules allow `switch_skill`, `fallback_model`, `hitl_escalation`. Re-plan flow is 🔵.

---

### 18.3 Skill Execution Contract

Each skill follows a strict contract:

```
SkillExecution {
  input
  output
  status
  cost
  latency
  metrics
}
```

---

### Guarantees

- Deterministic I/O schema
- Measurable execution
- Traceability per invocation

> **✅ Shipped** — enforced by `BaseSkill` abstract class in `backend/app/services/skills_registry/base.py` and `SkillInvocation` model.

---

### 18.4 Orchestration Layer

Agentium delegates heavy orchestration to an execution layer:

- papAI workflows (Spark, batch, pipelines)
- Async workers (Celery, queues)
- Event-driven triggers

---

### Integration Pattern

```
Agentium System
    ↓
Flow Execution Engine
    ↓
Skill Calls / papAI Workflows / External APIs
```

> **🟡 Partial** — async execution is handled by FastAPI `BackgroundTasks` + Postgres-backed checkpoints. No Celery or papAI workflow bridge yet.

---

### 18.5 Error Handling & Resilience

Agentium must handle:

- transient failures → retry
- deterministic failures → fallback
- critical failures → escalation

---

### Retry Strategy

- exponential backoff
- max attempts
- alternative skill selection

> **🟡 Partial** — retries on transient LLM failures are implemented at the LLM provider layer (`ollama_llm_v1`, `azure_llm_v1`). Declarative per-skill retry policy (see §19.4) is 🔵.

---

### 18.6 Checkpointing

To support long-running systems:

- intermediate states are persisted
- system can resume from checkpoint
- partial recomputation is possible

---

### Example

```
Run interrupted at step 3
→ Resume from step 3
→ No full recompute
```

> **🟡 Partial** — `skill_invocations` form de-facto checkpoints; resume from a specific invocation is **not** implemented. Re-run is always full re-run.

---

### 18.7 Multi-Agent Coordination

Agentium supports multiple coordination patterns:

---

#### Sequential

```
Agent A → Agent B → Agent C
```

---

#### Parallel

```
Agent A
   ↘
    → Merge → Output
   ↗
Agent B
```

---

#### Hierarchical

```
Supervisor Agent
   ├── Worker Agent 1
   ├── Worker Agent 2
```

---

#### Federated

```
System A ↔ System B ↔ System C
```

> **✅ Shipped** — sequential & parallel within a flow.
> **🟡 Partial** — hierarchical (one System delegating to another) is modeled via `sub_system_id` on `SkillInvocation` but not yet exposed in the builder.
> **🔵 Planned** — federated (System-to-System across tenants).

---

### 18.8 Performance & Scaling

Agentium must support:

- horizontal scaling of runs
- parallel skill execution
- distributed processing via papAI

---

### Optimization Levers

- caching skill outputs
- batching requests
- adaptive routing (model / skill selection)

> **🟡 Partial** — horizontal scaling via uvicorn workers; caching / batching 🔵.

---

### 18.9 Observability

Execution is fully observable:

- per run
- per skill
- per system

---

### Metrics Collected

- cost
- latency
- success rate
- retries
- drift indicators

> **✅ Shipped (cost, latency, success)** / **🟡 (retries, drift)**.

---

### 18.10 Alignment with papAI

papAI acts as:

- compute layer
- data layer
- orchestration backbone

Agentium acts as:

- reasoning layer
- system abstraction
- ROI layer

---

### Final Model

```
Agentium (System Intelligence)
        ↓
papAI (Execution & Data)
        ↓
Infrastructure (Compute, Storage, APIs)
```

---

### Key Insight

Agentium does not replace orchestration.

It **elevates orchestration into intelligent, adaptive and value-driven systems**.

---

## 19. Concrete Runtime Definitions · 🟡 Partial

This section turns the execution model into an explicit product and engineering specification.

---

### 19.1 Runtime Orchestration Modes

Agentium supports three native execution modes.

#### Synchronous Runtime

Used for short, bounded, request-response interactions.

Characteristics:
- single request lifecycle
- immediate response expected
- low orchestration depth
- no long blocking human step
- strict timeout and SLA

Typical use cases:
- short RAG answer
- classification
- lightweight scoring
- contract clause extraction on a single file

Contract:
- a `Run` is still created
- execution must complete within the sync SLA
- no unbounded planning loop is allowed

> **✅ Shipped** — chat and single-shot skill invocations are sync via `/systems/:id/runs` with `mode=sync`.

---

#### Asynchronous Runtime

Used for long-running, batch, high-cost, or resumable systems.

Characteristics:
- durable run state
- worker-based execution
- resumable from checkpoints
- retry and fallback support
- optional HITL pauses

Typical use cases:
- batch document analysis
- narration pipelines
- translation review flows
- multi-agent investigations

Contract:
- every async execution has a persistent `run_id`
- state transitions are auditable
- partial recomputation must be possible

> **🟡 Partial** — async runs via FastAPI `BackgroundTasks` ✅; resumable checkpoints 🔵; HITL pauses 🟡 (the `Task` queue exists but pause-resume semantics are not wired into the run engine).

---

#### Event-Driven Runtime

Used for reactive systems triggered by external or internal events.

Characteristics:
- event subscription or webhook trigger
- automatic run creation
- correlation between source event and execution
- replay-safe and idempotent behavior

Typical triggers:
- new file in SFTP
- new document in GED or SharePoint
- webhook from CRM or ERP
- threshold exceeded in Hypervisor
- model drift alert

Contract:
- each event produces a correlated `Run`
- duplicate events must not create duplicate side effects
- replay must be supported when possible

> **🔵 Planned** — no trigger engine yet. Intelligence scheduler is the only time-based trigger (cron-like).

---

### 19.2 Canonical Agent Loop

Every adaptive system follows the same runtime loop:

```text
Plan → Act → Observe → Evaluate → Adapt
```

#### Plan

The system turns an objective into an executable strategy.

Produces:
- selected capability
- selected skills
- execution ordering
- resource budget
- stopping conditions

Planning can be:
- static
- dynamic
- hybrid

---

#### Act

The system invokes skills, tools, APIs, knowledge retrieval, or sub-systems.

Each action must emit:
- input reference
- output
- status
- latency
- cost
- metrics

---

#### Observe

The system captures execution evidence.

Observed signals:
- intermediate outputs
- confidence
- errors
- cost progression
- time progression
- guardrail flags

---

#### Evaluate

The system compares observed results with success criteria.

Possible decisions:
- continue
- retry
- fallback
- escalate
- finish

---

#### Adapt

The system updates its execution strategy.

Possible adaptations:
- switch skill
- change model
- alter flow path
- reduce cost tier
- invoke HITL

> **✅ Shipped (Plan / Act / Observe)** / **🟡 (Evaluate, Adapt)** — see §18.2 status.

---

### 19.3 Skill Invocation Contract

A Skill is not a loose tool call. It is a typed, metered and versioned execution primitive.

#### Skill Definition Contract

```json
{
  "skill_id": "ocr_layout_v2",
  "version": "2.1.0",
  "type": "perception.v1",
  "input_schema": {},
  "output_schema": {},
  "execution": {
    "mode": "sync",
    "timeout_ms": 15000,
    "retryable": true,
    "idempotent": true
  },
  "pricing": {
    "unit": "page",
    "base_cost": 0.01
  },
  "metrics": {
    "quality": ["confidence", "accuracy"],
    "operational": ["latency_ms", "cost"]
  },
  "certification_level": "production-ready"
}
```

---

#### Skill Execution Record

```json
{
  "invocation_id": "inv_123",
  "skill_id": "ocr_layout_v2",
  "system_id": "sys_contract_risk",
  "run_id": "run_456",
  "input_ref": "blob://doc_001/page_3",
  "output": {},
  "status": "success",
  "cost": 0.01,
  "latency_ms": 928,
  "metrics": {
    "confidence": 0.94
  },
  "trace": {
    "started_at": "...",
    "ended_at": "...",
    "attempt": 1
  }
}
```

---

#### Mandatory Guarantees

Every production skill must guarantee:
- typed input/output
- explicit version
- measurable cost
- measurable latency
- auditable execution
- standard status model
- retry policy declaration

> **✅ Shipped** — the `SkillInvocation` model (`backend/app/models/skill_invocation.py`) closely matches this record.
> **🟡 Gap** — `retry policy declaration` at the skill level is not yet enforced; retries live at the LLM provider layer.

---

### 19.4 Error Handling and Retry Grammar

Failures are part of the runtime. Agentium standardizes them.

#### Failure Classes

##### Transient Failure
- timeout
- temporary API outage
- rate limit

Policy:
- automatic retry
- exponential backoff
- jitter
- max attempts

---

##### Deterministic Failure
- invalid schema
- unsupported input
- corrupted document

Policy:
- no blind retry
- fail fast
- optional alternative path

---

##### Quality Failure
- low confidence
- incomplete output
- weak retrieval
- guardrail soft fail

Policy:
- retry with alternative skill or model
- evaluator pass
- optional human review

---

##### Critical Failure
- safety breach
- severe compliance issue
- hard guardrail failure

Policy:
- stop immediately
- alert
- escalation

---

#### Canonical Retry Policy

```yaml
RetryPolicy:
  transient:
    max_attempts: 3
    strategy: exponential_backoff
    jitter: true
  quality:
    max_attempts: 1
    allow_fallback: true
  deterministic:
    retry: false
  critical:
    retry: false
    escalate: true
```

> **🔵 Planned** — failure classification is ad-hoc today. A declarative `RetryPolicy` per skill + a failure classifier in `run_engine` is the next natural step.

---

### 19.5 Checkpointing Model

Checkpointing is mandatory for long-running or high-cost systems.

#### What is checkpointed
- current step
- completed skill list
- partial outputs
- accumulated cost
- accumulated latency
- execution context
- chosen flow path

---

#### Checkpoint Record

```json
{
  "checkpoint_id": "cp_789",
  "run_id": "run_456",
  "step": "risk_scoring",
  "state": {
    "completed_skills": ["ocr_layout_v2", "clause_extraction_v1"],
    "partial_outputs": {},
    "cost_so_far": 0.11
  },
  "resume_token": "..."
}
```

---

#### Resume Rules
- resume from last valid checkpoint
- avoid full recomputation by default
- preserve cost traceability
- preserve skill version traceability

> **🔵 Planned** — `skill_invocations` act as implicit checkpoints (we know what succeeded), but there is no `resume_token` or resume endpoint.

---

### 19.6 Multi-Agent Coordination Patterns

Agentium supports a limited but explicit set of coordination patterns.

#### Sequential Pattern

```text
Agent A → Agent B → Agent C
```

Use when:
- steps are strictly dependent
- output must be progressively refined

---

#### Parallel Pattern

```text
           → Agent B →
Agent A →                 → Merge
           → Agent C →
```

Use when:
- multiple sources or analyses can run independently
- merge logic is well defined

---

#### Router Pattern

```text
Input → Router Agent → Legal Agent | Finance Agent | Technical Agent
```

Use when:
- different domains require different systems or skills
- knowledge bases are separated
- cost-aware routing matters

---

#### Hierarchical Pattern

```text
Supervisor Agent
 ├── Worker Agent 1
 ├── Worker Agent 2
 └── Worker Agent 3
```

Use when:
- one lead agent plans and coordinates
- workers are specialized
- evaluation and synthesis are centralized

---

#### Evaluator Pattern

```text
Producer Agent → Evaluator Agent → Accept | Retry | Escalate
```

Use when:
- output quality is critical
- a second pass is required before publication

---

#### HITL Pattern

```text
System → Human Review → Resume System
```

Use when:
- confidence is low
- decision risk is high
- regulatory validation is required

> **✅ Shipped** — Sequential, Parallel (within chain_mixed_hah_v1), Evaluator (claim_audit_v1 can gate outputs).
> **🟡 Partial** — Router (`chain_hybrid_v1` routes between dense/sparse/keyword), Hierarchical.
> **🔵 Planned** — HITL pattern wired into run engine state machine.

---

### 19.7 Runtime-to-Pricing Consistency

The runtime and pricing model must remain aligned.

#### Internal Cost Model

Internal runtime cost is computed from:
- skill invocations
- retries
- tool calls
- orchestration overhead
- storage and checkpointing
- optional HITL

```math
Internal\ Cost = \sum SkillInvocations + \sum ToolCalls + Orchestration + Retries + HITL
```

> **✅ Shipped** — `Run.cost_internal` is aggregated from `skill_invocations.cost`.

---

#### External Pricing Model

The client is not charged on raw runtime complexity.

The client buys a Capability unit:
- per contract analyzed
- per document processed
- per prediction generated
- per dossier reviewed

```math
Capability\ Revenue = Volume \times UnitPrice
```

> **🔵 Planned** — no billing.

---

#### ROI Model

```math
ROI = \frac{ValueGenerated - InternalCost}{InternalCost}
```

> **🟡 Partial** — computed in Hypervisor aggregate; `ValueGenerated` is operator-supplied.

---

#### Product Rule

- client buys a **Capability**
- runtime executes a **System**
- system invokes **Skills**
- Hypervisor pilots **Impact**

This is the non-negotiable chain of coherence.

---

### 19.8 Canonical Objects for Execution and Pricing

#### System

```yaml
System:
  id: sys_contract_risk
  objective: Detect contract risk
  capability: contract_risk_detection
  execution_mode: async
  coordination_pattern: hierarchical
  pricing_mode: per_capability_unit
  roi_model: legal_review_time_saved
```

> **🟡 Partial** — `execution_mode`, `coordination_pattern`, `pricing_mode` fields do **not** yet exist on the System model. Only `objective`, `capability_id`, `default_*` exist. Adding these as first-class columns is the next System-model migration.

---

#### Run

```yaml
Run:
  id: run_2026_001
  system_id: sys_contract_risk
  status: completed
  checkpoints: 4
  retries: 1
  cost_internal: 0.14
  revenue_allocated: 0.20
  impact:
    time_saved_minutes: 18
    confidence: 0.92
```

> **🟡 Partial** — `status`, `cost_internal`, `confidence` ✅; `checkpoints`, `retries`, `revenue_allocated` 🔵.

---

#### Hypervisor View

```yaml
HypervisorView:
  capability: contract_risk_detection
  volume_month: 12000
  total_cost: 1680
  total_revenue: 2400
  estimated_value: 84000
  roi: 49.0
  recommendation: Scale usage and allocate premium model only for low-confidence cases
```

> **✅ Shipped** — `/hypervisor/aggregate` returns exactly this structure.

---


### 19.9 Operational Recommendation

The recommended operating model is:
- sync for bounded interactions
- durable async for production systems
- event-driven for reactive automation
- hierarchical coordination as default multi-agent pattern
- strict skill contracts in all production flows
- retry + fallback + escalation as standard resilience grammar
- capability-based pricing in customer-facing packaging
- Hypervisor as the strategic surface where runtime metrics become financial and operational decisions

---

## 20. Execution Modes · 🟡 Partial

Execution Modes make runtime behavior explicit at product level.

They are not only technical settings. They define:
- user expectation
- orchestration semantics
- resilience behavior
- pricing behavior
- observability level

Every System must declare one primary execution mode.

> **🟡 Gap** — `execution_mode` is **not** yet a declared field on System. Mode is inferred from usage (chat = sync, intelligence batch = async). Making this explicit on the System model is a high-impact, low-cost next step.

---

### 20.1 Real-Time Decision Mode

Used when the system must return a result immediately.

Characteristics:
- synchronous request-response
- bounded execution graph
- low latency SLA
- no blocking HITL step
- deterministic surface behavior

Typical use cases:
- instant contract risk preview
- interactive document Q&A
- real-time recommendation
- lightweight scoring

Product behavior:
- user sees immediate result
- run is created in background for traceability
- cost is attached to a single decision event

Pricing logic:
- priced per decision or per analyzed item
- retry budget must remain bounded

> **✅ Shipped (implicit)** — chat, single-shot runs.

---

### 20.2 Batch Processing Mode

Used when the system processes many inputs or long-running workloads.

Characteristics:
- asynchronous execution
- resumable state
- checkpointing enabled
- parallelism possible
- delayed but traceable results

Typical use cases:
- document batches
- nightly classification jobs
- large-scale translation or narration
- portfolio-wide risk analysis

Product behavior:
- system exposes queue state, progress and partial outputs
- user interacts through Runs and execution history
- failures are isolated per item or sub-run when possible

Pricing logic:
- priced per processed business unit
- internal runtime cost amortized over volume

> **🟡 Partial** — intelligence scheduler runs async batches. Generic batch ingestion of user inputs is 🔵.

---

### 20.3 Event-Driven Automation Mode

Used when a System reacts automatically to business events.

Characteristics:
- triggered by event, webhook, file arrival or threshold crossing
- no manual start required
- idempotent execution required
- correlation between event and run mandatory

Typical use cases:
- new contract uploaded
- drift threshold exceeded
- SFTP arrival
- new ticket or CRM event

Product behavior:
- users configure triggers, not manual runs
- Hypervisor can subscribe to strategic thresholds
- replay-safe execution is required

Pricing logic:
- priced per event successfully processed or per downstream business unit

> **🔵 Planned** — no trigger engine.

---

### 20.4 Continuous Monitoring Mode

Used when a System continuously observes signals and decides whether to act.

Characteristics:
- persistent observation layer
- threshold or anomaly based triggering
- low-cost observation loop
- adaptive escalation logic

Typical use cases:
- KPI surveillance
- fraud or anomaly monitoring
- SLA monitoring
- capability health supervision

Product behavior:
- users monitor state, alerts and triggered runs
- Hypervisor consumes outputs directly

Pricing logic:
- subscription or bundled monitoring fee + triggered capability execution costs

> **🔵 Planned** — intelligence scheduler is a precursor but does not continuously decide.

---

### 20.5 Human-Augmented Mode

Used when the system is autonomous by default but requires structured human validation on sensitive steps.

Characteristics:
- system pauses on explicit review states
- HITL is part of normal execution semantics
- review outcomes are typed and auditable

Typical use cases:
- compliance review
- translation validation
- legal clause confirmation
- high-risk decision approval

Product behavior:
- review queue and approval UI are first-class
- resume token is mandatory after review

Pricing logic:
- priced on capability execution
- optional HITL surcharge or premium workflow pricing

> **🟡 Partial** — `/tasks` queue exists with approve/reject UI, but the run engine does not yet pause/resume a Run waiting for a Task.

---

### 20.6 Execution Mode Contract

```yaml
ExecutionMode:
  name: real_time_decision | batch_processing | event_driven_automation | continuous_monitoring | human_augmented
  trigger_type: manual | api | cron | event | threshold | review_resume
  sla_profile:
    latency_target_ms: 5000
    max_runtime_s: 30
  durability:
    checkpointing: true
    replay_safe: true
  pricing_profile:
    unit: decision
    retry_budget: bounded
```

> **🔵 Planned** — formalize this as a `SystemExecutionMode` enum + JSON `execution_profile` column on System.

---

### 20.7 Product Rule

Execution Mode must be visible in:
- System settings
- Run records
- pricing configuration
- Hypervisor

It is a first-class concept, not a hidden technical parameter.

---

## 21. Adaptive Systems · ✅ Shipped (Levels 0–1), 🟡 (Levels 2–3)

Agentium systems are not static pipelines.

An Adaptive System is a System that can change its execution behavior within governed boundaries based on:
- observed quality
- observed cost
- observed latency
- observed context
- observed risk

---

### 21.1 Adaptation Levels

#### Level 0 — Static
- fixed flow
- no runtime adaptation

#### Level 1 — Controlled Adaptation
- limited routing choices
- bounded fallbacks
- deterministic adaptation rules

#### Level 2 — Dynamic Adaptation
- planner can choose between multiple skills or flows
- evaluator can request retries or alternate paths
- cost-aware routing is enabled

#### Level 3 — Self-Optimizing
- system learns preferred execution patterns over time
- optimization policies are updated from historical performance
- always under governance constraints

> **✅ Shipped** — Level 0 (static flow) and Level 1 (AdaptivePolicy with bounded triggers + actions).
> **🟡 Partial** — Level 2 (chain_hybrid_v1 routing between dense/sparse/keyword is cost-aware).
> **🔵 Planned** — Level 3 (no historical-learning policy optimizer).

---

### 21.2 Adaptation Inputs

Adaptation can use:
- confidence score
- cost budget remaining
- latency budget remaining
- skill health
- drift signals
- business priority
- review history

> **✅ Shipped** — `confidence`, `skill health` consumed by AdaptivePolicy triggers.
> **🟡 Partial** — `cost budget remaining`, `drift signals` not yet exposed to policies.

---

### 21.3 Adaptation Outputs

An adaptive decision may:
- switch skill
- switch model tier
- switch knowledge source
- re-plan flow
- invoke evaluator
- escalate to HITL
- stop execution

> **✅ Shipped** — `switch_skill`, `fallback_model`, `hitl_escalation`, `stop_execution`.
> **🟡 Partial** — `switch knowledge source`, `invoke_evaluator`.
> **🔵 Planned** — `re-plan flow`.

---

### 21.4 Adaptive Policy Contract

```yaml
AdaptivePolicy:
  enabled: true
  adaptation_level: controlled
  triggers:
    - low_confidence
    - high_cost
    - guardrail_soft_fail
  allowed_actions:
    - switch_skill
    - fallback_model
    - hitl_escalation
  constraints:
    max_extra_cost: 0.05
    max_retry_count: 1
    forbidden_actions:
      - bypass_guardrails
```

> **✅ Shipped** — `backend/app/models/adaptive_policy.py`, CRUD endpoints at `/control-plane/adaptive`, UI at `/steering`.

---

### 21.5 Governance Rule

Adaptive behavior must always be:
- bounded
- explainable
- auditable
- priced

No adaptive behavior may silently bypass:
- guardrails
- compliance checks
- pricing limits
- human review rules

> **✅ Shipped** — every adaptive action is logged as an audit event with policy ID + triggered run + action taken.

---

### 21.6 Product Positioning

This is where Agentium becomes more than a workflow platform.

Agentium does not only run systems.
It runs **governed adaptive systems**.

---

## 22. Capability Execution Contract · 🟡 Partial

A Capability is the business-level execution object exposed to customers, delivery teams and the Hypervisor.

If a Skill is the atomic execution primitive, a Capability is the atomic business promise.

---

### 22.1 Definition

A Capability Execution is:
- a business-scoped execution unit
- backed by one or more Systems
- composed of one or more Skills
- priced on a business unit
- evaluated on business and operational metrics

Examples:
- one contract analyzed
- one document processed
- one prediction generated
- one compliance review completed

> **🟡 Gap** — there is no distinct `CapabilityExecution` entity. Executions are recorded as `Runs` with the System's `capability_id` as the implicit binding. A dedicated object would enable direct business-unit billing.

---

### 22.2 Capability Contract

```yaml
Capability:
  id: cap_contract_risk_detection
  name: Contract Risk Detection
  description: Detects and explains contractual risks in uploaded agreements
  input_unit: contract
  output_unit: risk_report
  system_ids:
    - sys_contract_risk
  skill_ids:
    - ocr_layout_v2
    - clause_extraction_v1
    - risk_scoring_v3
  pricing:
    unit: contract
    unit_price: 0.20
  sla:
    mode: async
    target_completion_minutes: 5
  roi_model: legal_review_time_saved
```

> **🟡 Partial** — `id`, `name`, `description`, `skill_ids`, `pricing_unit`, `unit_price`, `roi_model` ✅. `input_unit`, `output_unit`, `sla` 🔵.

---

### 22.3 Capability Execution Record

```yaml
CapabilityExecution:
  id: ce_001
  capability_id: cap_contract_risk_detection
  system_id: sys_contract_risk
  run_id: run_2026_001
  business_unit_count: 1
  status: completed
  revenue: 0.20
  internal_cost: 0.14
  quality:
    confidence: 0.92
    success_rate: 1.0
  impact:
    time_saved_minutes: 18
    estimated_value: 24.0
```

> **🔵 Planned** — would be a projection over Runs; requires a `business_unit_count` field on Run.

---

### 22.4 Capability Guarantees

Every Capability must define:
- input business unit
- output business unit
- customer-facing SLA
- pricing unit
- ROI model
- linked Systems
- linked Skills

A Capability cannot exist without runtime traceability to:
- Run
- Skill executions
- cost
- value estimate

---

### 22.5 Capability Metrics

#### Business Metrics
- volume
- revenue
- estimated value
- ROI
- time saved

#### Operational Metrics
- average completion time
- success rate
- fallback rate
- human review rate

#### Technical Metrics
- internal cost
- latency by step
- skill drift

> **✅ Shipped (technical + operational)** / **🟡 (business metrics require operator-declared revenue model)**.

---

### 22.6 Capability as Pricing Object

The customer does not buy Skills.
The customer buys Capabilities.

This is the core pricing rule of Agentium.

Skills explain internal cost.
Capabilities explain external value.

---

## 23. Hypervisor Decision Model · ✅ Shipped (Observe/Interpret/Recommend/Decide), 🟡 (Act)

The Hypervisor must evolve from a reporting layer into a real strategic operating layer.

It must not only show metrics.
It must support decisions.

---

### 23.1 Decision Model Structure

The Hypervisor operates on five levels:

1. Observe
2. Interpret
3. Recommend
4. Decide
5. Act

---

### 23.2 Observe

The Hypervisor ingests:
- run metrics
- capability metrics
- system metrics
- cost metrics
- value metrics
- drift and risk signals

> **✅ Shipped** — aggregate from Runs + Impact.

---

### 23.3 Interpret

The Hypervisor computes portfolio-level views:
- ROI by capability
- cost vs value by system
- trend evolution
- failure concentrations
- adoption concentration

> **✅ Shipped** — `/hypervisor/aggregate` returns exactly these views.

---

### 23.4 Recommend

The Hypervisor generates strategic recommendations such as:
- scale a capability
- reduce a model tier
- move to HITL for low-confidence cases
- stop low-value systems
- allocate more budget to high-margin capabilities

Recommendations must always be backed by:
- observed evidence
- expected impact
- confidence level

> **✅ Shipped** — the `Decision` feed at `/hypervisor/decisions` returns recommendations with rationale, evidence, and impact estimate.

---

### 23.5 Decide

A decision object is created when a strategic action is taken.

```yaml
Decision:
  id: dec_001
  scope: capability
  target_id: cap_contract_risk_detection
  recommendation: scale_usage
  rationale:
    roi: 49.0
    confidence: high
    trend: increasing
  approved_by: cfo_or_ops_lead
  timestamp: 2026-04-21T10:00:00Z
```

> **✅ Shipped** — `backend/app/models/decision.py`, CRUD through `/hypervisor/decisions`.

---

### 23.6 Act

The Hypervisor must support direct actions such as:
- increase budget
- reduce budget
- change execution mode
- enforce HITL threshold
- deploy upgraded System version
- pause capability

A COMEX tool is only truly used when decisions can be enacted from the same interface.

> **🟡 Gap** — approving a Decision today writes the row but does **not** automatically mutate the target's ControlPolicy / AdaptivePolicy / System. The user must manually apply the change in Steering. Closing this gap (Decision → policy patch) is the highest-leverage next step for the Hypervisor.

---

### 23.7 Decision Layers

#### Executive Layer
- portfolio ROI
- top and bottom capabilities
- budget allocation
- strategic recommendations

#### Operational Layer
- run health
- error clusters
- throughput
- review queues

#### Builder Layer
- skill performance
- system adaptation behavior
- fallback and retry analysis

Same object model, different abstraction depth.

> **✅ Shipped** — reflected in Hypervisor tabs + ⌘Z semantic zoom between layers.

---

### 23.8 What-If Simulation

The Hypervisor should support simulated decisions before action.

Examples:
- what if we scale this capability to all business units?
- what if we switch to a cheaper model for low-risk cases?
- what if we increase HITL threshold?

```yaml
WhatIfScenario:
  target: cap_contract_risk_detection
  change: increase_volume_2x
  expected_cost: 3360
  expected_value: 168000
  expected_roi: 49.0
```

> **✅ Shipped** — `/hypervisor/what-if` (POST) accepts 4 canonical levers (`resource`, `velocity`, `autonomy`, `risk_tolerance`) and returns projected cost / value / confidence deltas. UI lever panel in `hypervisor.component.ts`.
>
> **🔵 Next** — named scenarios (e.g. `increase_volume_2x`) stored for later recall.

---

### 23.9 Hypervisor Product Rule

The Hypervisor is not a passive BI layer.
It is a **decision cockpit for AI capability allocation**.

Its core unit is not the chart.
Its core unit is the **recommended and actionable decision**.

---

### 23.10 Final Strategic Model

```text
Skills → Systems → Capabilities → Hypervisor Decisions
```


This is the full business-operational chain of Agentium.

---

## 24. Agent Economics & Decision Units · 🟡 Partial

Agentium introduces a critical layer that does not exist explicitly in most agentic platforms: the economic model of intelligence execution.

Agentium systems are not only technical systems.
They are **decision-producing economic entities**.

---

### 24.1 Core Concept — Decision Unit

A Capability Execution is not only a task.
It is a **Decision Unit**.

A Decision Unit is defined as:

```
Decision Unit =
- input (business context)
- decision produced
- cost
- time
- confidence
- impact (value)
```

Example:

```
1 contract → risk score → cost 0.18€ → value 12€ → confidence 0.92
```

> **🟡 Partial** — a Run already carries input, output, cost, time, confidence. What's missing is the **operator-declared value** per run; presently value is aggregated at the Capability level, not per Run.

---

### 24.2 Why Decision Units Matter

Traditional AI evaluates:
- model accuracy
- system performance

Agentium evaluates:
- economic output of decisions

Because in practice:
- AI agents act as decision-makers in economic systems
- and must be evaluated on their impact, not just their intelligence

The key shift is:

> From "How smart is the system?"
> To "Does the decision generate more value than it costs?"

---

### 24.3 Agent Efficiency Function

Agentium defines a normalized efficiency function:

```math
AgentEfficiency = \frac{Value \times Confidence}{Cost \times Time}
```

This enables:
- comparison across systems
- optimization over time
- routing decisions based on efficiency

> **🟡 Partial** — components are persisted; the composite score is not precomputed and exposed as a first-class metric.

---

### 24.4 Capability Portfolio Model

An organization does not deploy isolated agents.

It manages a **portfolio of capabilities**.

Each capability is evaluated as:
- an investment
- with cost
- with return
- with risk

The Hypervisor therefore acts as:
- capital allocation layer
- performance optimizer
- risk controller

---

### 24.5 Strategic Implication

Agentium shifts the paradigm from:

- AI as tooling

To:

- AI as a system of **decision production and value generation**

---

### 24.6 Product Rule

Every Capability must expose:
- cost per unit
- value per unit
- confidence
- efficiency score

No capability is valid without measurable economics.

> **🟡 Gap** — add `efficiency_score` to Capability's aggregate view.

---

## 25. Control Plane — Governance Layer · ✅ Shipped

Agentium introduces a Control Plane that governs all systems.

The Control Plane is the layer that ensures that intelligence remains:
- safe
- bounded
- aligned
- economically viable

---

### 25.1 Definition

```
Control Plane = Policies + Constraints + Budget + Permissions + Safety + Routing Rules
```

---

### 25.2 Control Policy Example

```yaml
ControlPolicy:
  max_cost_per_decision: 0.25
  max_latency_ms: 5000
  mandatory_hitl_if_confidence_below: 0.85
  allowed_models:
    - mistral_local
    - azure_gpt4
```

> **✅ Shipped** — `backend/app/models/control_policy.py`, endpoints at `/control-plane/policies`, UI at `/steering`.

---

### 25.3 Role of Control Plane

The Control Plane enforces:
- pricing boundaries
- compliance constraints
- execution constraints
- model governance
- safety rules

---

### 25.4 Strategic Importance

Without a Control Plane:
- agent systems drift
- costs explode
- risks accumulate

With a Control Plane:
- systems are enterprise-ready
- decisions are governed
- execution is predictable

---

## 26. Context Layer — First-Class Object · ✅ Shipped

Agentium systems are context-dependent.

Lack of context is one of the main causes of agent failure.

---

### 26.1 Definition

Context is a first-class object:

```
Context =
- data
- documents
- memory
- history
- environment state
- business constraints
```

> **✅ Shipped** — `backend/app/models/context.py` + migration `006_context_first_class`. CRUD at `/contexts`. UI at `/steering/contexts` with builder-side selection (System Builder step "Context").

---

### 26.2 Updated System Definition

```
System = Objective + Capabilities + Context + Flow + Skills + Runs + Impact
```

> **✅ Shipped** — System has `context_ids[]` relation populated through the Builder wizard.

---

### 26.3 Context Role

Context enables:
- better decisions
- better reasoning
- better consistency
- better personalization

---

### 26.4 Context Governance

Context must be:
- permissioned
- versioned
- auditable

> **✅ Shipped** — `permissions` JSON on Context, audit log on mutations.
> **🟡 Gap** — versioning (`context_version_id`) is not yet implemented.

---

### 26.5 Strategic Impact

Agentium does not only orchestrate skills.

It orchestrates **contextualized intelligence**.

---

## 27. Final Strategic Model (Extended) · ✅ Shipped

```text
Context → Skills → Systems → Capabilities → Decision Units → Hypervisor Decisions
```

---

### Final Positioning Reinforcement

Agentium is not an agent platform.

It is:

> A system for producing, measuring and optimizing decisions at scale

---

### Ultimate Product Statement

> We don't deploy agents.
> We control how decisions are produced, governed and optimized.

---

## 28. Deployment Modes — Enterprise & On-Prem Compatibility · 🟡 Partial

Agentium must support both:
- **economic / ROI-driven usage (Hypervisor-first)**
- **technical / execution-driven usage (builder-first)**

This duality is critical because many enterprise use cases:
- start as technical problems
- operate in regulated or air-gapped environments
- require on-prem or sovereign deployments

Agentium must therefore support two entry modes.

---

### 28.1 Dual Entry Model

#### Executive Mode (default)
- Objective-driven
- ROI-first
- Hypervisor as homepage

#### Technical Mode (builder-first)
- System-first
- Flow / Skills visible
- Execution-first approach

> **🟡 Partial** — the cockpit defaults to Hypervisor as homepage (Executive). There is no explicit "Builder mode" toggle that reorders navigation / hides ROI. Progressive disclosure via ⌘Z approximates it but is not a mode switch.

---

### 28.2 On-Prem / Local Deployment Model

Agentium must be deployable:
- fully on-prem
- hybrid (on-prem + cloud LLM)
- sovereign cloud

Key requirements:
- no external dependency mandatory
- local LLM compatibility (vLLM, Ollama, etc.)
- local vector DB (Qdrant)
- local storage (MinIO / S3 compatible)

> **✅ Shipped (technical primitives)** — Ollama-compatible LLM provider ✅, Qdrant vector store ✅, MinIO-compatible storage ✅.
>
> **🟡 Gap** — no curated "on-prem install" artifact (Helm chart, offline Docker Compose bundle). Docker Compose exists but assumes cloud registry access.

---

### 28.3 Product Rule

> Economic layer is optional for entry, but mandatory for scale.

Meaning:
- technical users can ignore ROI initially
- Hypervisor progressively becomes central as usage grows

---

### Strategic Insight

Many agentic AI failures come from lack of governance and infrastructure readiness.

Agentium solves this by allowing:
- technical adoption first
- economic governance later

---

## 29. UX Wireframes (Concrete, Not Conceptual) · 🟡 Partial

---

### 29.1 Run View — Decision Unit Visible

```
---------------------------------
RUN DETAIL
---------------------------------
Status: Completed
System: Contract Risk Detection

Decision (Unit of Value)
---------------------------------
Input: Contract #123
Outcome: Risk = High
Cost: 0.18€
Value: 12€
Confidence: 0.92
Efficiency: 20.4

Execution Trace
---------------------------------
[Step 1] OCR → OK
[Step 2] Extraction → OK
[Step 3] Scoring → OK
```

> **✅ Shipped** — `/runs/:runId` renders header + "Outcome" panel + step-by-step execution trace. Efficiency score 🟡 (not computed).

---

### 29.2 Hypervisor Homepage (C-Level)

```
---------------------------------
AI BALANCE SHEET
---------------------------------

Net Value: 142k€
ROI: +640%

Top Capabilities
---------------------------------
Contract Risk Detection → +120k€
Fraud Detection → +80k€

Liabilities
---------------------------------
Total Cost: 12k€
Risk: Medium
HITL Load: 18%

Actions
---------------------------------
[Scale Capability]
[Reduce Cost]
[Adjust Confidence Threshold]
```

> **✅ Shipped (structure)** — `/hypervisor` renders Net Value, ROI, top/bottom capabilities, cost, HITL load. Action buttons open the what-if panel.
> **🟡 Gap** — "Scale Capability" / "Reduce Cost" do not yet auto-patch policies (see §23.6).

---

### 29.3 Control Plane (Pilot Interface)

```
---------------------------------
SYSTEM CONTROL
---------------------------------
Cost Limit: [-----|----] 0.25€
Latency: [----|---] 5000ms
Confidence Threshold: [---|----] 0.85

Impact Preview
---------------------------------
Cost: +12%
Latency: -18%
ROI: +9%
```

> **✅ Shipped** — `/steering` renders sliders for cost_limit / latency / HITL threshold / allowed_models. `/control-plane/simulate` returns impact preview in real time.

---

## 30. UX Naming Strategy · ✅ Shipped

"Decision Unit" is internally precise but can be too technical and cold for end users.

Agentium must separate **internal rigor** from **external clarity**.

---

### 30.1 Naming Duality

#### Internal (Engineering / Data Model)
- Decision Unit

#### UI (Product / User-facing)
- Outcome
- Decision
- Unit of Value

---

### 30.2 Recommended Default

- Primary UI label: **Outcome**
- Secondary (contextual): Decision

Example in UI:

```
Outcome
-----------------
Risk = High
Cost: 0.18€
Value: 12€
Confidence: 0.92
```

> **✅ Shipped** — `Run` detail uses "Outcome" as the primary label; `Decision` appears only in the Hypervisor decisions feed context.

---

### 30.3 Product Rule

- Never expose "Decision Unit" directly in UI
- Always expose business-readable terms
- Keep semantic consistency across all screens

---

### 30.4 Strategic Insight

Naming is not cosmetic.

It defines:
- cognitive load
- adoption speed
- perceived product maturity

"Outcome" anchors the system in **business value**, not technical abstraction.

---

## 31. Real-Time Feedback & System Responsiveness · 🟡 Partial

Real-time feedback is not a UX enhancement.
It is a **core product requirement**.

---

### 31.1 Why It Matters

Without real-time feedback:
- the system feels static
- decisions feel disconnected from impact
- the platform behaves like a dashboard

With real-time feedback:
- the system feels alive
- users understand cause → effect instantly
- decision-making becomes intuitive

---

### 31.2 Core Interaction Pattern

```
User action (slider / constraint change)
        ↓
Immediate recalculation
        ↓
Live UI update
        ↓
Updated ROI / cost / recommendation
```

> **✅ Shipped (Steering sliders)** — Control Plane sliders trigger `/control-plane/simulate` with debounced calls, updating the impact preview under 300ms.
>
> **✅ Shipped (Hypervisor what-if)** — lever changes trigger `/hypervisor/what-if` with sub-second feedback.
>
> **🟡 Gap (chat → impact)** — chat responses do not update global ROI in real time; aggregate refresh is on navigation.

---

### 31.3 Example — Control Plane

```
User adjusts:
Cost Limit → 0.20€

System reacts instantly:
- Cost ↓
- Confidence ↓ slightly
- ROI ↑
- Recommendation updated
```

---

### 31.4 Mandatory UI Behaviors

- No page reload ✅
- Sub-second feedback (<300ms target for perception) ✅ in Steering + Hypervisor
- Progressive update (numbers animate, not jump) 🟡 (partial — numbers tween in cockpit cards only)
- Visual highlighting of changes ✅

---

### 31.5 Impact Preview as Standard

Every decision must show its impact before being applied.

```
Impact Preview
--------------
Cost: -12%
Latency: +5%
ROI: +8%
Risk: +3%
```

> **✅ Shipped** — Steering simulate + Hypervisor what-if both render impact preview before apply.

---

### 31.6 Product Rule

> Every user action must produce a visible and immediate system reaction

---

### 31.7 Strategic Consequence

Without this:
- Agentium = dashboard

With this:
- Agentium = **interactive decision system**

---

### 31.8 Key Warning

If real-time feedback is not implemented:

- you lose the "wow effect"
- you lose trust in the system
- you lose differentiation

---

### Final Insight

The perception of intelligence does not come from models.

It comes from:

> how fast and clearly the system reacts to user decisions



## 31bis. UI Feedback & System Perception · ✅ Shipped

_(Section authored twice in the draft — preserved for fidelity.)_

Agentium must feel like a **living system**.

---

### 31bis.1 Real-Time Feedback

Every interaction should produce visible feedback.

Example:

User changes slider →
- cost updates instantly
- ROI recalculates
- recommendation updates

---

### 31bis.2 Animation Principles

- micro-animations on change
- progressive updates
- no full page reload

> **✅ Shipped** — Hybrid A+B cockpit styling (radial gradients, glows, number tweens) delivers the "living" feel.

---

### 31bis.3 Goal

Create perception that:

> "The system reacts to my decisions in real time."

---

## 32. UX Pitfalls to Avoid · ✅ Shipped (rules followed)

---

### ❌ Pitfall 1 — Hiding Core Concepts

- Balance Sheet hidden in tabs
- Control Plane buried in settings

❗ Rules:
- Balance Sheet = homepage ✅ (/hypervisor)
- Control Plane = visible in system view ✅ (/steering + inline Steering tab in System detail)

---

### ❌ Pitfall 2 — Over-Technical UX

- too many metrics
- internal jargon
- low signal-to-noise

❗ Rules:
Always prioritize:
- cost
- value
- ROI

> **✅ Shipped** — default cockpit cards surface 3 metrics only (cost, value, ROI); extra metrics behind "More" drawer.

---

### ❌ Pitfall 3 — Static UI

- no feedback
- no adaptation
- no perception of intelligence

❗ Rule:
UI must reflect system behavior dynamically

> **✅ Shipped** — real-time feedback (§31) + live status dots on System cards.

---

## 33. Final Product Completeness Check · 🟡 Partial

Agentium now includes:

- Execution Model ✅
- Runtime Model ✅
- Adaptive Systems ✅ (Levels 0–1)
- Capability Model 🟡 (pricing + ROI partial)
- Decision Unit Model 🟡 (Run-scoped value missing)
- Economic Model 🔵 (no billing)
- Control Plane ✅
- Hypervisor ✅ (observation & recommendation) / 🟡 (act)
- UX Model ✅
- Deployment Model (cloud + on-prem) 🟡 (primitives OK, packaging missing)

---

### Final Positioning (Updated)

Agentium is:

> A platform to design, run and govern intelligent systems
> across both technical and economic dimensions

---

### Final Insight

Agentium succeeds because it allows:
- engineers to build systems
- operators to run them
- executives to optimize them

In one unified model

---

## 34. Builder Onboarding Mode (Adoption First Strategy) · ✅ Shipped, 🟡 Evolving

Agentium must explicitly support a **Builder Onboarding Mode** where ROI is not the primary entry point.

> **✅ Shipped** — workspace modes `builder`, `operator`, `executive`,
> and `demo` are persisted on the workspace and drive progressive
> disclosure in the cockpit chrome. `demo` keeps the product flow intact
> while hiding provider/model implementation details from the UI.
> **🟡 Evolving** — the remaining work is not a mode toggle; it is the
> finer adaptation of surface density and business copy as a workspace
> matures.

---

### 34.1 Why This Mode Is Required

Enterprise reality:
- most AI adoption starts with experimentation
- ROI is unclear at the beginning
- teams need to "build first, measure later"

Studies show that unclear business value and technical readiness are among the main blockers to adoption.

---

### 34.2 Builder Onboarding Mode Definition

Builder Mode is:
- system-first
- execution-first
- ROI-light (initially hidden or optional)

User journey:
```
Create System → Run → Observe → Iterate → Discover Value → Activate ROI layer
```

---

### 34.3 UX Behavior

In Builder Mode:
- focus on Runs, Flow, Skills
- show cost optionally, not ROI
- no Balance Sheet by default
- Hypervisor progressively introduced

---

### 34.4 Transition to Economic Mode

At maturity threshold (usage / volume / stability):
- system prompts user:
  "Do you want to track value and ROI?"

Then:
- Decision Units activated
- Hypervisor becomes visible
- Balance Sheet unlocked

---

### 34.5 Product Rule

> Adoption starts with execution. Scaling requires economics.

> **✅ Shipped** — explicit mode switching exists via `workspace.mode ∈ {builder, operator, executive, demo}`.

---

## 35. Convergence UX — Builder ↔ Hypervisor · ✅ Shipped (zoom primitive), 🟡 (card transformation)

Agentium must unify builder and executive views without breaking cognitive flow.

---

### 35.1 Problem

- Builder view = detailed, technical
- Hypervisor view = aggregated, strategic

Most platforms split them completely → cognitive break.

---

### 35.2 Solution — Zoom-Based Continuum

Agentium uses a continuous zoom model:

```
Skill → Flow → System → Capability → Portfolio
```

---

### 35.3 UX Mechanism

- Zoom in → technical detail (skills, steps)
- Zoom out → aggregated value (ROI, impact)

Same object, different abstraction level.

> **✅ Shipped** — `⌘Z` / `⇧⌘Z` implemented in `cockpit/zoom.service.ts` moves across 5 levels. Breadcrumb updates accordingly.

---

### 35.4 Shared Object Model

Both views rely on the same objects:
- Run
- Outcome (Decision Unit)
- Capability

No duplication, no translation layer.

> **✅ Shipped** — all screens consume the same canonical API; no duplicate types.

---

### 35.5 Key Principle

> Change perspective, not interface

---

### 35.6 Product Rule

- Builder and Hypervisor must never be separate apps
- Only abstraction level changes

> **✅ Shipped** — single Angular app, route-based but sharing chrome.

---

## 36. Control Plane as "AI Steering Wheel" · 🟡 Partial

The Control Plane can become a major visual and conceptual differentiator.

---

### 36.1 Concept

Instead of a configuration panel,
Control Plane becomes a **steering interface for AI systems**.

---

### 36.2 Core Metaphor

```
AI System = Vehicle
User = Driver
Control Plane = Steering Wheel
```

---

### 36.3 Steering Wheel Dimensions

Each axis controls a system trade-off:

- Cost ↔ Quality
- Speed ↔ Accuracy
- Automation ↔ Control (HITL)
- Risk ↔ Performance

> **✅ Shipped** — the 4 canonical Hypervisor levers (`resource`, `velocity`, `autonomy`, `risk_tolerance`) map directly onto these axes.

---

### 36.4 UI Representation

Option 1 — Radial Control
- circular UI
- each axis adjustable
- central equilibrium point

Option 2 — Multi-Slider Panel
- simpler implementation
- linear controls

> **✅ Shipped (Option 2)** — multi-slider panel in Hypervisor + Steering.
> **🔵 Planned (Option 1)** — the radial "steering wheel" is a strong visual differentiator and remains on the roadmap.

---

### 36.5 Real-Time Interaction

Every steering action:
- updates cost
- updates ROI
- updates system behavior

---

### 36.6 Impact Visualization

```
Steering Change → Immediate Simulation → Outcome Projection
```

> **✅ Shipped** — what-if + simulate endpoints deliver this.

---

### 36.7 Strategic Advantage

Transforms Control Plane from:
- technical settings

Into:
- **decision-making interface**

---

### 36.8 Product Rule

> The user must feel they are piloting intelligence, not configuring software

---

## 37. Final UX Integration — Adoption to Mastery · 🟡 Partial

Agentium UX must support the full maturity curve:

---

### Phase 1 — Builder
- focus: execution
- no ROI pressure
- fast iteration

### Phase 2 — Operator
- focus: performance
- cost awareness
- run monitoring

### Phase 3 — Executive
- focus: ROI
- portfolio optimization
- strategic decisions

---

### Unified Model

```text
Build → Run → Measure → Optimize → Allocate
```

---

### Final Strategic Insight

Agentium wins because it does not force users into a single mental model.

It adapts to:
- builders (execution)
- operators (performance)
- executives (value)

while keeping a single coherent system.

> **🟡 Gap** — all three phases' features exist, but there is no adaptive UX that adjusts surface density / ROI visibility to the user's declared maturity (see §34).

---

## 38. Soft Transition UX — Builder → Hypervisor · 🔵 Planned

Agentium must not impose a hard switch between Builder and Hypervisor views.

---

### 38.1 Principle

> ROI must emerge progressively, not be imposed.

Agentic systems adoption typically starts from execution and only later converges toward measurable value.

---

### 38.2 Progressive Reveal Model

Instead of a mode switch, introduce a gradual layering:

#### Stage 1 — Builder (No ROI)
- Runs
- Skills
- Flow
- Basic cost (optional)

#### Stage 2 — Operator (Cost Awareness)
- Cost per run
- Success rate
- Latency

#### Stage 3 — Value Discovery
- Estimated value appears
- "Outcome" block enriched

#### Stage 4 — Hypervisor Activation
- ROI visible
- Balance Sheet appears
- Recommendations enabled

---

### 38.3 UX Mechanism

- ROI appears inline (not via navigation)
- No dedicated "switch mode" button
- System suggests activation ("Track value?")

---

### 38.4 Product Rule

- No abrupt UX transition
- Always additive, never disruptive

---

### Strategic Insight

Users adopt agentic systems through intent and experimentation before governance and ROI layers become critical.

> **🔵 Planned** — progressive stage reveal would require tracking workspace maturity metrics (runs_count, distinct_systems_count, since_first_run) and gating UI elements accordingly.

---

## 39. Visualizing the Zoom — Skill → Portfolio · ✅ Shipped (zoom), 🟡 (card transformation)

Agentium must materialize abstraction levels without overwhelming non-technical users.

---

### 39.1 Problem

Zoom abstraction risks:
- loss of context
- cognitive overload
- disorientation

---

### 39.2 Solution — Semantic Zoom

Instead of geometric zoom, Agentium uses **semantic zoom**:

```
Skill → Flow → System → Capability → Portfolio
```

Each level changes representation, not just scale.

> **✅ Shipped** — `⌘Z` / `⇧⌘Z` semantic zoom navigates levels.

---

### 39.3 UI Patterns

#### Breadcrumb Continuum

```
[Portfolio] > [Capability] > [System] > [Run] > [Skill]
```

- always visible ✅
- clickable ✅
- preserves context ✅

---

#### Card Transformation

- Skill = node / atomic block
- System = structured graph
- Capability = KPI card
- Portfolio = balance sheet

Same object → different representation

> **🟡 Partial** — level-dependent card rendering exists for Skill, System, Capability, Portfolio but is not fully unified (each view is a distinct Angular component rather than a single polymorphic card).

---

#### Focus Mode

- click object → isolates it
- dim others
- reduces cognitive load

> **🔵 Planned** — currently navigation opens a new route rather than dimming siblings.

---

### 39.4 Product Rule

> Never zoom into technical detail without preserving business context

---

### Strategic Insight

Agentic UX is shifting from static interfaces to adaptive, context-driven systems that reshape themselves based on user intent.

---

## 40. Steering Wheel Scope — Global vs Local · ✅ Shipped (Global, Capability), 🟡 (Run-level)

The Control Plane must exist at multiple levels.

---

### 40.1 Problem

- Global only → too abstract
- Local only → no strategic control

---

### 40.2 Solution — Multi-Level Steering Model

#### Global Steering (System / Portfolio)
- budget allocation
- global cost constraints
- model policy
- risk level

Used by:
- C-level
- Ops

> **✅ Shipped** — Hypervisor what-if + portfolio-scoped AdaptivePolicies.

---

#### Capability-Level Steering
- pricing optimization
- model tier routing
- HITL thresholds

Used by:
- product / delivery

> **✅ Shipped** — ControlPolicy + AdaptivePolicy with `scope=capability` and `target_id`.

---

#### Run-Level Steering
- retry decisions
- override execution
- manual validation

Used by:
- operators

> **🟡 Partial** — run cancel exists. Mid-run override / manual step validation is not yet exposed.

---

### 40.3 UX Representation

- Global: Hypervisor cockpit ✅
- Capability: inline control panel ✅ (Capability detail page)
- Run: contextual action panel 🟡 (Run detail shows actions but limited)

---

### 40.4 Product Rule

> Steering must exist at all levels, but be visible only where relevant

---

### 40.5 Default Behavior

- start with global steering (simple) ✅
- progressively expose local controls 🟡

---

### Strategic Insight

Effective agentic systems require balancing autonomy and control across layers, not centralizing everything in a single control point.

---

## 41. Final UX Maturity Model (Extended) · 🟡 Partial

Agentium must support three progressive UX dimensions:

---

### Dimension 1 — Abstraction

Skill → System → Capability → Portfolio

> **✅ Shipped** (via ⌘Z).

---

### Dimension 2 — Value Visibility

Cost → Performance → Value → ROI → Allocation

> **✅ Shipped (Cost, Performance, ROI)** / **🟡 (progressive reveal per §38)**.

---

### Dimension 3 — Control

Local → Capability → System → Portfolio

> **✅ Shipped** (multi-scope policies, §40).

---

### Final Model

```text
Execute → Observe → Understand → Value → Control → Optimize
```

---

### Ultimate Insight

The power of Agentium comes from aligning:
- abstraction
- value visibility
- control

into a single coherent experience.

---

---

## Appendix A — Gap ledger (what to build next)

Aggregated from the status annotations above, sorted by product impact.

### Tier 1 — Highest leverage

1. **Hypervisor Decision → policy enactment.** Approving a Decision must auto-patch the target's ControlPolicy / AdaptivePolicy. Closes the loop of §23.6.
2. **`execution_mode` as first-class System field.** Unlocks mode-aware SLA, pricing, observability (§20.6).
3. **Per-Run value declaration + efficiency score.** Turns §24's Decision Unit from conceptual to operational.

### Tier 2 — Strong UX differentiators

4. **Adaptive maturity coach for Builder / Operator / Executive modes** (§34, §38) — modes are shipped; next gap is automatic surface-density guidance as a workspace matures.
5. **Radial steering wheel** (§36.4 Option 1) — strong visual differentiator.
6. **Full card-transformation semantic zoom** (§39.3) — unified polymorphic card per object across zoom levels.

### Tier 3 — Enterprise & scale

7. **Declarative retry policies per skill** (§19.4) + failure classifier in run engine.
8. **Checkpoint resume tokens** (§19.5, §18.6) — resume long runs without full recompute.
9. **Event-driven runtime** (§19.1, §20.3) — webhook / file / threshold triggers.
10. **On-prem install bundle** (§28.2) — offline Docker Compose + Helm chart, curated local model set.

### Tier 4 — Economic layer

11. **Billing subsystem** (§6 Pricing, §22.6) — metering, invoicing, quotas.
12. **Skill certification pipeline** (§9) — formal Basic / Production-ready / Enterprise-certified gate.
13. **3-layer capability marketplace** (§8, §16) — Universal / Industry / Client with install flow.

### Tier 5 — Convergence

14. **papAI interop** (§17 Phase 2) — bidirectional workflow ↔ system calls.

---

## Appendix B — Source documents

- `docs/mental-model-draft.md` (archived at `docs/archive/mental-model-draft-2026-04-21.md`) — the pristine 3326-line vision document, preserved unedited for historical reference.
- `docs/skills-runtime.md` — canonical skill slug → module mapping with tri-state status.
- `docs/deck-product-review.md` — Marp slide deck version of this model for product team reviews.
- `CHANGELOG.md` — per-wave (A–F) delivery log that populated the status annotations above.

---

_Last reconciled: 2026-04-21. Update this document when either the vision or the shipped state changes — never let them drift._
