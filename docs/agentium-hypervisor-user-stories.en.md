# User stories: Agentium Hypervisor

> Same format as the papAI specs (`USER_STORY_HYPERVISOR`,
> `MVP_HYPERVISOR_COMEX`): macro-story, epics, `As a / I want / so that`,
> acceptance criteria, data, priorities.
>
> The objects changed. **Suite / Workflow / App / AI Service** become
> **System / Capability / Experience / Run / Decision**. The Hypervisor is
> no longer “a papAI App”: it is the **portfolio ledger** (`/hypervisor`,
> **Impact** rail when adoption is on).
>
> Status: **Shipped** (on `demo/agentic`) · **Partial** · **Specified**
> (contract, not yet the behaviour).
>
> Normative: [`mental-model.md`](./mental-model.md),
> [`agentium-reference.md`](./agentium-reference.md),
> [`agentium-hypervisor-decision-strategy.en.md`](./agentium-hypervisor-decision-strategy.en.md).
> COMEX MVP: [`agentium-hypervisor-mvp-comex.en.md`](./agentium-hypervisor-mvp-comex.en.md).
> FR: [`agentium-hypervisor-user-stories.md`](./agentium-hypervisor-user-stories.md).
>
> Word: [`agentium-hypervisor-user-stories.en.docx`](./agentium-hypervisor-user-stories.en.docx).

---

## 0. Macro user story

As an executive or decision-maker, I want to steer the Agentium **System**
portfolio from the Hypervisor: observe what ran and on what evidence
(measured / declared / missing), consume published applications in
**Work**, monitor **Runs** without confusing them with business success,
and decide — record a **signal** in the Hypervisor, sign a **human gate**
in a Studio, or enact a bounded policy via **Steer**
(`Simulate → Approve → Act → Measure`) — so that AI is industrialized as
a management object, **without inventing a zero** and **without the model
signing in my place**.

---

## 1. Overview

### 1.1 Problem

Without the Agentium Hypervisor, the executive committee has no ledger of
what Systems actually returned. Teams have no governed channel to raise
evidence (Run, value base, decision). AI governance falls back to informal
exchanges, or to chrome “ROI” that invents a zero.

papAI framed this as a **top-down / bottom-up** flow between decision-makers
and builders, via Suites and Workflows. Agentium keeps the flow on other
objects: the **bottom** is Runs and published Experiences; the **top** is
operational objectives, Decisions and the value loop.

### 1.2 Value proposition

| Capability | Agentium meaning |
|---|---|
| Ledger | Consolidate Runs, measured cost, declared value, `not_measured` / `not_configured` |
| Top-down objectives | Bounded operational objective on a System (`operational_objective`) |
| Bottom-up | Runs, value bases, Work Experiences, review queue |
| Decisions | `proposed → accepted \| rejected` ; enactment **outside** the Hypervisor |
| Value loop | Steer: `Outcome → Decision → Simulate → Approve → Act → Measure` |
| Companion | First-class conversation, same rights, the model does not sign |
| Governance | IAM, audit, Membrane; never “prompt only” |

### 1.3 Personas

| Persona | Agentium role | Surface |
|---|---|---|
| Executive (Sarah) | Observe the portfolio, sign signals, allocate | `/hypervisor` |
| Steward (Mehdi) | Bound and enact via Steer | `/systems/:id?lens=steer` |
| Builder (Alex) | Compose and publish a System / Experience | `/create`, `/systems/new` |
| Business (Claire) | Consume, cite, sign a gate | `/work`, Studio |
| Governance (Nadia) | Audit, access | `/governance/audit`, `/governance/access` |

`Work ↔ Cockpit` is an RBAC link, not a theme. Do not say Desk, Board,
workflow, pipeline, job, HITL (say **Flow**, **Run**, **human approval**).

### 1.4 Gating — flags, not a PRO edition

Agentium has no Standard / PRO pair. Scope is workspace flags:

| Flag | Effect |
|---|---|
| `experience_v1` | Work / Experiences |
| `adoption_experience_v1` | Business entry, Impact rail, guides, companion — **off** by default, **not accepted** |
| `hypervisor_v2` | Ledger (else v1 value balance sheet) |
| `value_loop_v1` + System canary | Enactment Simulate → Measure |

### 1.5 papAI → Agentium map

| papAI | Agentium | Do not copy as-is |
|---|---|---|
| Suite / Workflow | System bound to a Capability | “Suite KPI” |
| Hypervisor App | Cockpit surface `/hypervisor` | “first system App on NextJS” |
| € target | `operational_objective` (5 metrics) + **declared** value base | chrome ROI = financial truth |
| Directive + ack | Decision + Studio gate + value loop | papAI-style ack workflow |
| Proposal / Alert / Insight | Decision (`recommendation`, `review_required`, `value_loop`) | Six form types |
| Strategic agent + action tools | Companion (`inspect_system`, `compare_runs`, `read_operational_metrics`) | `send_directive()` from chat |
| AI Service health | Diagnostics + Runs — **technical** health | “Healthy” = business success |
| 4-step KPI pipeline | Experience publication + evaluation + Run | Custom Metric Python from the Hypervisor |
| PRO banner | Workspace flags | Paid Standard/PRO edition |

---

## 2. Epic 1 — Ledger (aggregation)

### US-AHYP-100: See what the portfolio returned

**Status: Partial** · **P0**

As an executive, I want to see, on the chosen period, what the portfolio
executed and on what evidence, so that I can judge impact without taking
an invented zero as a measurement.

Acceptance:

- [ ] `/hypervisor` shows Runs, outcomes, cost and value with an explicit
      fact-state: `available` · `not_measured` · `not_configured` ·
      `restricted` · `unavailable`
- [ ] Missing data is **not** rendered as €0 / 0 h
- [ ] v1: “net value” hero is labelled a **capability ROI model**
      (estimated − cost), not a financial attestation
- [ ] v2 (`hypervisor_v2`): legend *ink = measured · teal = declared*;
      Understand → Detail → Decide
- [ ] Breakdown by System / Capability is clickable
- [ ] Displayed ROI is **suppressed** when cost is near zero, and capped

Data: `GET /hypervisor/balance-sheet`, `GET /hypervisor/series`,
`GET /hypervisor/value-bases`.

### US-AHYP-101: Choose the observation period

**Status: Shipped** · **P0**

As an executive, I want to choose the window (30d, 90d, WTD / MTD / QTD
by version) so that I can compare without changing object.

Acceptance:

- [ ] Selector in `/hypervisor` chrome
- [ ] All blocks recompute
- [ ] v2: Direction = 90d / hours; Operations = 30d / runs;
      Compliance = 90d / runs

### US-AHYP-102: Read value bases

**Status: Shipped** · **P0**

As an executive, I want to see which Capabilities have a signed, dated,
versioned value base, so that I know what is declared versus native units
(runs, hours).

Acceptance:

- [ ] `GET /hypervisor/value-bases` lists bases (`declared` | `measured` |
      `none`)
- [ ] Without a base: native unit, no fabricated euro
- [ ] A declared base is **not** a Lot 8 measurement

### US-AHYP-103: Keep v1 and v2 stories distinct

**Status: Shipped** · **P1**

As a steward, I want `hypervisor_v2` to pick the component so that we do
not promise the portfolio value-loop banner on the Ledger.

Acceptance:

- [ ] Flag absent / false → v1 (balance sheet + `GET /hypervisor/value-loop`)
- [ ] Flag true → v2 (no value-loop aggregate)
- [ ] v1 shows *A simulation is not a measurement* on the aggregate

---

## 3. Epic 2 — Top-down objectives

### US-AHYP-200: Set an operational objective on a System

**Status: Shipped** · **P0**

As an executive or owner, I want a bounded operational objective on a
System (metric, target, 1–90 day window, owner, comparison reference) so
that I set a heading **without claiming economic ROI**.

Acceptance:

- [ ] Allowed metrics only: `completed_volume` · `mean_duration_ms` ·
      `human_waits` · `human_validation_rate` · `measured_cost_usd`
- [ ] Write is System-admin guarded
- [ ] Impact / System overview shows the objective and *Not measured* /
      *Economic impact not attested here* when needed
- [ ] This is **not** the papAI € Target, nor O5 (hours / money saved)

Data: `System.settings.operational_objective`.

### US-AHYP-201: See progress toward the objective

**Status: Partial** · **P0**

As an executive, I want the gap between the operational measure and the
target so that I know if the System is inside the window.

Acceptance:

- [ ] Observed vs target, native unit
- [ ] A measured zero (true 0 runs) ≠ `not_measured`
- [ ] No economic “On track” badge derived from a completed Run

### US-AHYP-202: Edit or remove the objective

**Status: Shipped** · **P1**

As an owner, I want to change the target, the window or remove the
objective. Audit keeps the write.

### US-AHYP-203: See Systems with neither objective nor base

**Status: Partial** · **P1**

As an executive, I want Systems that lack both an operational objective
and a value base, so that I chase owners instead of showing a “€0”
portfolio.

---

## 4. Epic 3 — Decisions (portfolio signal)

### US-AHYP-300: See what is waiting for a signature

**Status: Shipped** · **P0**

As an executive, I want the `proposed` `Decision` feed so that I know what
is waiting for a human.

Acceptance:

- [ ] `GET /hypervisor/decisions` paginated, filterable
- [ ] Card: title, rationale, **estimated** impact, target, dates
- [ ] v2 copy: *What is waiting for a signature*
- [ ] Observed `kind`: `recommendation`, `review_required`, `value_loop`

### US-AHYP-301: Accept or reject — signal only

**Status: Shipped** · **P0**

As an executive, I want to accept or reject a proposed Decision so that a
traced **decision signal** is recorded.

Acceptance:

- [ ] accept: `proposed → accepted` ; reject: `proposed → rejected`
- [ ] Human provenance when the UI requires it
- [ ] A `scenario_id` Decision **refuses** this path
- [ ] UI does **not** offer portfolio “Apply”
- [ ] `POST .../apply` returns **409** `LEGACY_DECISION_ACTUATOR_DISABLED`

Line: *Validating here records a signal. Changing a System goes through Steer.*

### US-AHYP-302: Scan recommendations

**Status: Shipped** · **P1**

As an executive, I want SCAN
(`POST /hypervisor/recommendations/generate`) so that the feed is fed
without treating recos as measurements.

### US-AHYP-303: Sign a gate in Work / Studio

**Status: Shipped** · **P0**

As a business user or operational decision-maker, I want to accept or
reject a gate on a published application so that execution waits for a
human.

Acceptance:

- [ ] The model **cannot** accept (`POST /assistant/decisions` needs the
      UI action and observed id; stale → refuse)
- [ ] `/steering/review-queue` for evaluation reviews
- [ ] Audit: human provenance

---

## 5. Epic 4 — Enactment (value loop)

### US-AHYP-400: Enact via Steer, not the Hypervisor

**Status: Shipped (canary)** · **P0**

As a steward, I want
`Outcome → Decision → Simulate → Approve → Act → Measure` on **one**
System so that a policy changes in a bounded, evidenced way.

Acceptance:

- [ ] Gate: `features.value_loop_v1` **and** System activation
- [ ] Surface: `/systems/:id?lens=steer` — not `/hypervisor`
- [ ] Single actuator: `control_policy.guardrails.patch.v1` + Membrane
      `enforce`; else `not_configured`
- [ ] Baseline = `runtime_auto` Run; seed / operator **refused**
- [ ] `simulation_is_measurement: false`
- [ ] Measurement closes only on an observed post-action Run

### US-AHYP-401: Read the portfolio aggregate without calling it a measurement

**Status: Shipped (v1 only)** · **P1**

As an executive, I want v1 observed Δ, risks and scenarios so that I drill
to the System — not to say “the portfolio simulated, therefore we gained”.

---

## 6. Epic 5 — Bottom-up (Work, Runs, Knowledge)

### US-AHYP-500: Publish a consumable Experience

**Status: Shipped** · **P0**

As a builder, I want to publish an Experience bound to a System version so
that the business consumes `/work/:slug` without engine jargon.

### US-AHYP-501: Raise evidence (Run)

**Status: Shipped** · **P0**

As a business user or builder, I want an execution to produce a Run so
that the Hypervisor has something to aggregate.

Acceptance:

- [ ] Deep link `/runs/:id`
- [ ] *Completed ≠ validated answer ≠ economic gain*
- [ ] Diagnostics stay behind a “technical health” disclosure

### US-AHYP-502: Declare a value base

**Status: Shipped** · **P1**

As a steward, I want to declare a base (`value_per_unit`,
`hours_per_unit`, author, `declared`) so that the Ledger can convert
outcomes **without inventing a measurement**.

### US-AHYP-503: See silent Systems

**Status: Partial** · **P1**

As an executive, I want absence of recent Runs as a gap, not as zero
performance.

---

## 7. Epic 6 — Companion (ex “strategic agent”)

### US-AHYP-600: Query the portfolio in natural language

**Status: Partial** · **P1**

As an executive or business user, I want a question scoped to authorized
Systems so that I inspect without browsing — **with the same rights as the
UI**.

Acceptance:

- [ ] Work + Cockpit companion; 0–10 `system_ids`; empty scope = discovery
- [ ] Read tools: `inspect_system`, `compare_runs`,
      `read_operational_metrics`
- [ ] Launch / approval = canonical services
- [ ] papAI `send_directive` / `forecast_value` are **out of contract**

### US-AHYP-601: Stop the model from signing

**Status: Shipped** · **P0**

As governance, I want no model turn to accept a gate.

### US-AHYP-602: Warn about scope

**Status: Partial** · **P1**

As an executive, I want to see scope (Systems, workspace, tools on or off)
so that I do not believe in an omniscient agent.

---

## 8. Epic 7 — Attention and trends

### US-AHYP-700: See what needs attention

**Status: Partial** · **P1**

As an executive, I want `proposed` decisions, out-of-window objectives,
`not_configured` Systems, value-loop risks — not a papAI “AI Service Down”
taken as business failure.

### US-AHYP-701: Read a trend without projection = measurement

**Status: Partial** · **P2**

As an executive, I want v2 series. Portfolio what-if is **not shipped**
(`POST /hypervisor/what-if` → `not_configured`). papAI dashed “future
month” bars stay **out of contract** without provenance.

### US-AHYP-702: Export a COMEX report

**Status: Specified** · **P2**

As an executive, I want a period export (PDF / CSV) with the
measured/declared/missing disclaimer. **Not shipped.**

---

## 9. Epic 8 — Governance

### US-AHYP-800: Control who observes, decides, enacts

**Status: Shipped** · **P0**

As an admin, I want to separate Hypervisor read · accept/reject ·
objective write · Steer Act · Work publish. Workspace mode changes
**density**, not IAM.

### US-AHYP-801: Trace

**Status: Shipped** · **P0**

As governance, I want `/governance/audit` to hold accept/reject, human
gates, adoption progress (metadata only), objective writes, value-loop
steps.

### US-AHYP-802: Isolate Mission Room

**Status: Shipped** · **P0**

As product, I want `/hypervisor/mission-room/*` to remain a **workspace
application**, not the ledger.

---

## 10. Epic 9 — Honesty and adoption

### US-AHYP-900: Refuse the invented zero

**Status: Shipped** · **P0**

As product, I want chrome and API to refuse a substitute financial total.
O5 remains an **acceptance hole**.

### US-AHYP-901: Enter through Work

**Status: Shipped (flag off)** · **P1**

As a business user, I want a first verifiable result (NorthForge, 4 steps,
10 minutes unaided — **unmeasured target**) without opening Cockpit.
`adoption_experience_v1` off by default; 10 sessions **not run**.

---

## 11. Out of scope

- Portfolio enactment (“Apply” on `/hypervisor`)
- What-if / live levers / < 300 ms impact preview
- papAI directives (types, escalation, Broadcast)
- Custom Metric pipeline from the Hypervisor
- Standard / PRO gating
- LLMOps “AI Service” as a business-health object
- Cross-workspace sharing
- KPI favourites (papAI US-HYP-802)
- Mission Room = Hypervisor

---

## 12. Recap

| ID | Epic | Title | P | Status |
|---|---|---|---|---|
| US-AHYP-100 | Ledger | See what the portfolio returned | P0 | Partial |
| US-AHYP-101 | Ledger | Choose the period | P0 | Shipped |
| US-AHYP-102 | Ledger | Read value bases | P0 | Shipped |
| US-AHYP-103 | Ledger | Distinguish v1 / v2 | P1 | Shipped |
| US-AHYP-200 | Objectives | Set an operational objective | P0 | Shipped |
| US-AHYP-201 | Objectives | See progress | P0 | Partial |
| US-AHYP-202 | Objectives | Edit / remove | P1 | Shipped |
| US-AHYP-203 | Objectives | Systems with no objective or base | P1 | Partial |
| US-AHYP-300 | Decisions | Signature feed | P0 | Shipped |
| US-AHYP-301 | Decisions | Accept / reject = signal | P0 | Shipped |
| US-AHYP-302 | Decisions | SCAN recommendations | P1 | Shipped |
| US-AHYP-303 | Decisions | Work / Studio gate | P0 | Shipped |
| US-AHYP-400 | Enactment | Steer Simulate → Measure | P0 | Shipped (canary) |
| US-AHYP-401 | Enactment | v1 aggregate ≠ measurement | P1 | Shipped |
| US-AHYP-500 | Bottom-up | Publish an Experience | P0 | Shipped |
| US-AHYP-501 | Bottom-up | Run evidence | P0 | Shipped |
| US-AHYP-502 | Bottom-up | Declare a base | P1 | Shipped |
| US-AHYP-503 | Bottom-up | Silent Systems | P1 | Partial |
| US-AHYP-600 | Companion | Scoped question | P1 | Partial |
| US-AHYP-601 | Companion | Model does not sign | P0 | Shipped |
| US-AHYP-602 | Companion | Warn about scope | P1 | Partial |
| US-AHYP-700 | Attention | Attention feed | P1 | Partial |
| US-AHYP-701 | Attention | Trend without fake projection | P2 | Partial |
| US-AHYP-702 | Attention | COMEX report export | P2 | Specified |
| US-AHYP-800 | Governance | IAM observe / decide / enact | P0 | Shipped |
| US-AHYP-801 | Governance | Audit | P0 | Shipped |
| US-AHYP-802 | Governance | Isolated Mission Room | P0 | Shipped |
| US-AHYP-900 | Honesty | No invented zero | P0 | Shipped |
| US-AHYP-901 | Adoption | Work entry | P1 | Shipped (flag off) |
