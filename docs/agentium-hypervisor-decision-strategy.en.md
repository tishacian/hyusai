# Agentium — Hypervisor, decision and industrializing AI

> Briefing for anyone who prepares, presents or steers Agentium with a
> **C-level**, a **business user**, or an **operational decision-maker**.
>
> This is not the implementation contract. Normative sources remain
> [`mental-model.md`](./mental-model.md) and
> [`agentium-reference.md`](./agentium-reference.md). User-acceptance evidence
> lives in [`agentium-adoption-roadmap.md`](./agentium-adoption-roadmap.md) —
> today **implemented, opt-in, not accepted**.
>
> Presentation deck:
> [`deck-agentium-decision-adoption.en.md`](./deck-agentium-decision-adoption.en.md).
>
> Office pack (rebuild with
> `python3 docs/render/build_hypervisor_decision_pack.py`):
> [`agentium-hypervisor-decision-strategy.en.docx`](./agentium-hypervisor-decision-strategy.en.docx),
> [`deck-agentium-decision-adoption.en.pptx`](./deck-agentium-decision-adoption.en.pptx).
> French twins: [`agentium-hypervisor-decision-strategy.md`](./agentium-hypervisor-decision-strategy.md),
> [`agentium-hypervisor-decision-strategy.fr.docx`](./agentium-hypervisor-decision-strategy.fr.docx),
> [`deck-agentium-decision-adoption.fr.pptx`](./deck-agentium-decision-adoption.fr.pptx).

---

## 1. What Agentium changes in enterprise decision-making

“Agent builder” platforms stop at the composer: a prompt, a tool, a demo.
They do not say **which business objective** is served, **what actually
happened**, **who decided**, or **whether the organisation is improving**.

Agentium industrializes **Systems** — intelligent systems bound to business
capabilities, executed under policy, with canonical evidence.

The product rule (mental model §0.0):

- A **business application** and a **conversation** are first-class ways to
  use and control a published System.
- **Work** serves the task. **Cockpit** exposes construction, operation,
  improvement, impact and administration.
- Success is a **verifiable outcome**, then an **operational or economic
  improvement**. Throughput and latency explain execution health; they do
  not prove business gain.
- Declared value, a projection, an operational measurement and attested
  economic impact remain **distinct**. An hour saved or a euro gained
  requires a baseline, comparable units and attributable evidence. A
  completed Run is not enough.

Canonical chain:

```text
System → Run → Evaluation → Decision → Action
```

| Link | Role for strategy |
|---|---|
| **System** | Industrialized intent: objective, graph, context, policies. |
| **Run** | One traceable execution (cost, latency, context, provenance). |
| **Evaluation** | Score and dimensions — quality is not a feeling. |
| **Decision** | Human or machine proposal: review, recommendation, value scenario. |
| **Action** | Accept, reject, replay, promote a canonical answer, or governed enactment. |

The Hypervisor is the **portfolio view** of this chain. It is not the place
where someone “presses a magic button” to change the runtime.

---

## 2. Observe, consume, monitor, decide

Four verbs, four contracts. Mixing them is the main demo failure in front
of an executive committee.

| Verb | Question | Surface | What the person leaves with |
|---|---|---|---|
| **Observe** | What did the portfolio return? On what evidence? | `/hypervisor` (rail **Impact** when the adoption experience is on) | A ledger: measured / declared / missing. No invented zero. |
| **Consume** | Which task must I finish now? | `/work`, `/work/:slug`, Studio (e.g. `/work/pr-to-po`) | A verifiable result, citations, a human gate if policy requires it. |
| **Monitor** | What is running, waiting, drifting? | `/runs`, `/observability`, `/steering/review-queue`, Diagnostics | Execution health and queues — explicitly **not** business success. |
| **Decide** | What is waiting for a signature, and where is it enacted? | `/hypervisor` feed (signal) · Work/Studio gates · **Steer** value loop | A `Decision` state + an audit. The model cannot sign in their place. |

`Work ↔ Cockpit` is an **RBAC** link, not a theme toggle. Identifiers,
audit and deep links are shared.

Words banned on screen and in a brief: **Desk**, **Board**,
**workflow** / **pipeline** (say **Flow**), **job** (say **Run**),
**HITL** as a label (say **human approval**).

---

## 3. The Hypervisor

### 3.1 One sentence

The Hypervisor is the **AI portfolio ledger**: what Systems executed, what
it cost, what is declared as value, what is missing, and **what is waiting
for a signature**.

Single route: `/hypervisor`. The component (v1 or v2) depends on the
workspace flag `settings.features.hypervisor_v2`. Absent or `false` → v1.

With the adoption experience, the Cockpit rail relabels this zone
**Impact**. The navigation id stays `hypervisor`. Renaming the tab **does
not** establish an economic outcome.

### 3.2 Two readings, one `Decision` object

| | **v1 — Value balance sheet** | **v2 — Ledger** (flag `hypervisor_v2`) |
|---|---|---|
| UI promise | “Net value generated” — cost, estimated value, ROI, signals, SCAN recommendations | “What the portfolio returned” — ink = measured, teal = declared |
| Strata | Hero + KPI + capabilities + signals + recos + decisions | **Understand → Detail → Decide** |
| Views | One page, WTD/MTD/QTD/30d/90d | Direction (hours, 90d) · Operations (runs, 30d) · Compliance (runs, 90d) |
| Portfolio value loop | Yes — read-only aggregate (`GET /hypervisor/value-loop`) | No — v2 is an instrumented ledger, not the same dashboard |
| Decide | Accept / Reject | Accept / Reject |

Both versions **accept and reject** a proposed `Decision`. Neither
**enacts** a policy change via “Apply”: the API returns
`LEGACY_DECISION_ACTUATOR_DISABLED` and points to a System value loop.
That is intentional, not a demo bug.

Line to say: *“Validating here records a decision signal. Changing a
System’s behaviour goes through Steer: Simulate → Approve → Act →
Measure.”*

### 3.3 What the C-level should read (and should not)

**Read**

- The v2 legend: *ink = measured · teal = declared · missing data is not a
  zero*.
- The hero: hours returned, runs executed, or **declared** value — the
  label says so.
- **Value bases**: a base is signed, dated, versioned. Without a base, the
  product shows the native unit.
- The **Decisions** feed: *What is waiting for a signature*.
- v1 only: the banner *A simulation is not a measurement* on the portfolio
  value-loop aggregate.

**Do not read as audited financial truth**

- v1 “net value” = `estimated value − cost` on visible Runs. Chrome calls
  it a **capability ROI model**.
- A displayed ROI when cost is near zero: the backend **suppresses** it
  (~0.01 threshold) and caps the display.
- A geometric zero on a v2 chart: calendar fill, not a measurement.

### 3.4 Mission Room is not the Hypervisor

`/hypervisor/mission-room/*` is an immersive **workspace application**
(Sentinel-CI, Octocity, or the generic provider). Ministerial briefing,
map, watch, cabinet arbitration. Same URL prefix, **different contract**.
Do not present it as the portfolio ledger.

---

## 4. Where a decision becomes an action

Three planes. Do not collapse them.

```text
Portfolio             System                    Application
/hypervisor           /systems/:id?lens=steer   /work/:slug  (Studio)
accept / reject       Simulate → Approve        human gate
= signal              → Act → Measure           = required
                      = bounded enactment       approval
```

### 4.1 Portfolio signal

`POST /hypervisor/decisions/{id}/accept|reject` moves
`proposed → accepted | rejected`. A `kind=review_required` may feed
evaluation feedback. A `scenario_id` (value loop) **refuses** this path:
it must go through the value orchestrator.

### 4.2 Enactment — value loop (Lot 8)

Contract: `Outcome → Decision → Simulate → Approve → Act → Measure`.

- Owned by a **System**, in Steer — not by the portfolio.
- Gate: `features.value_loop_v1` **and** System activation (canary
  `settings.experience.value_loop_canary = "v1"` during rollout).
- First actuator, deliberately bounded:
  `control_policy.guardrails.patch.v1`, only if the System declares it and
  Membrane v2 in `enforce` allows it. Otherwise: `not_configured`.
- Baseline = a completed Run with server provenance `runtime_auto`. A
  seed, a canary or an operator value is **refused** as baseline.
- `simulation_is_measurement: false` everywhere. A measurement closes the
  scenario only on a really observed post-action Run.
- Detail: [`agentium-lot8-value-loop.md`](./agentium-lot8-value-loop.md).

`/steering` (legacy page) still CRUDs policies. The “levers / what-if”
preview is **off**. `POST /hypervisor/what-if` and
`POST /control-plane/simulate` return `not_configured` and point to
`/systems/{id}/value-loop`. Do not promise a universal impact preview
(< 300 ms): it is **planned**, the component is not wired.

### 4.3 Human approval in Work

In a published application (Studio), a gate is an **explicit human
decision**. The model cannot accept in the person’s place
(`POST /assistant/decisions` requires the UI action and the observed id).
`/steering/review-queue` handles evaluation reviews. These acts carry
human provenance in the audit.

---

## 5. Industrializing AI: what it changes for strategy

Industrializing, in Agentium, is not “putting an LLM in production”.
It is holding **five disciplines** on the same `System` object.

| Discipline | What the executive committee gets | Where to see it |
|---|---|---|
| **Alignment** | Each System serves a Capability, not an orphan prompt | `/capabilities`, `/systems`, Work |
| **Publication** | What the business consumes is an **Experience** bound to a published version | `/create/apps` → `/work/:slug` |
| **Evidence** | Every answer has a Run, optional cost, context, lineage | `/runs/:id`, conversation “Action evidence” |
| **Governance** | Policies, IAM, audit, Membrane — never “prompt only” | `/governance/audit`, `/governance/access` |
| **Allocation** | We fund, tighten or stop **on evidence** | `/hypervisor` + the System value loop |

Strategic consequences:

1. **The portfolio becomes a management object**, not a pile of PoCs. You
   can say *how many Systems have a value base*, *which ones only have
   runs*, *which ones are waiting for a signature*.
2. **Conversation is not a parallel channel.** It reuses the same
   contracts, permissions and gates. It can start an authorized action; it
   cannot invent a right.
3. **Economics is not a chrome badge.** The five **operational objective**
   metrics (adoption) are not attested ROI. The value loop owns economic
   measurements. The “hours / money saved” gap (O5) remains a documented
   **acceptance hole**.
4. **Autonomy risk is bounded.** One actuator, a Membrane in enforce, a
   human on the gates. We industrialize control as much as execution.

Target maturity (mental model §37), **without automatic adaptive UX**
today:

```text
Build → Run → Measure → Optimize → Allocate
```

Rule: *adoption starts with execution; scaling requires economics.* Do not
force a C-level onto a balance sheet with no Runs, and do not sell a
balance sheet that is only Runs.

---

## 6. Adoption capability

### 6.1 Actual state

| Item | State |
|---|---|
| Adoption experience | Code shipped behind `settings.features.adoption_experience_v1` (**off** by default) |
| Work / Experiences | `experience_v1` — Work/runtime contract; “integrated” ≠ production-accepted |
| EN/FR guides | `/help/{start,sources,systems,runs,value}` |
| NorthForge path | `/work/getting-started` — 4 steps, Showcase + notices collection required |
| Conversation companion | Work + Cockpit overlay, scope-bound, the model does not sign |
| Operational objectives | 5 bounded metrics on the System — not ROI |
| Usability sessions | **Not run** (target: 5 business + 5 developers) |
| NorthForge bar | 4/5 business users finish **unaided in 10 minutes** — not measured |
| Flag retirement | Sponsor sequence (pilot → default → remove) — **not signed** |

Adoption is **not a permanent edition**. It is a rollout control. Line to
hold: *“the business path exists; it is not yet the default for every
workspace; we do not yet have the acceptance sheet.”*

### 6.2 Three “persona” layers — do not conflate them

| Layer | Values | What it changes | What it does not |
|---|---|---|---|
| **IAM role** | Workspace rights | What the person *may* do | — |
| **Workspace mode** | `builder` / `operator` / `executive` (+ provisioned `demo`, `portfolio`) | Cockpit density, home, economic/technical disclosure | Rights |
| **Member preference** (adoption) | Build / Use / Steer value | Tone of `<ck-help>` guides | Mode, role, entitlements |

`demo` mode hides providers and models (presentation-safe). `portfolio` is
persisted and intentionally absent from the UI selector.

Story personas (product deck) — useful for a narrative, **not** accounts:

| Persona | Entry | Job |
|---|---|---|
| Sarah — CAIO | `/hypervisor` | Arbitrate the portfolio |
| Mehdi — Steward | `/steering` then a System’s Steer | Envelope and policies |
| Alex — Builder | `/create`, `/systems/new` | Compose a System |
| Claire — Analyst | Work first; Cockpit `/runs` to drill | Consume and trace |
| Léo — Curator | `/knowledge` | Prepare sources |
| Nadia — Governance | `/governance/audit` | Compliance |

Claire does not “live” in `/systems/:id`. Business users consume in
**Work**. Cockpit chat is the operator path.

### 6.3 Learning curve

Three **declared** stages, not yet an automatic coach (§38 planned).

```text
1. Complete a task              Work / Studio
2. Bind the result to a Run     Citations, /runs, companion
3. Bind the Run to a decision   Impact + gates + (if on) value loop
```

| Profile | First 15 minutes | First week |
|---|---|---|
| **C-level observer** | `/work` → one published app → `/hypervisor` (Impact) → read measured/declared/missing → `/help/value` | 30d/90d review, value-base coverage, pending decisions, one audit pass. **No** “hours saved €” without a Lot 8 baseline. |
| **Business consumer** | `/work` → question → open the citation → (optional) NorthForge. Persona **Use**. | Daily Work; `/steering/review-queue` if assigned; Run deep link only to drill. *Completed ≠ validated answer.* |
| **Decision-maker** | A Studio gate **or** a Hypervisor decision (signal) **before** opening Steer | Inbox: gates + review + Impact feed. One `Simulate → Measure` scenario only if `value_loop_v1` is active on **this** System. |

Business acceptance target (unmeasured): first verifiable result
**alone, in ten minutes**, on the NorthForge example.

Builder target (reference, not a client promise): adapt the “Operational
Analysis” exercise (Flow → dedicated System → published app) in one
session; the internal run already exceeded the 120-minute budget.

### 6.4 What “adoption-capable” means — and does not

**Means**

- A business user can enter through **Work**, without engine jargon.
- A C-level can open **Impact** and tell evidence from assumption from gap.
- A decision-maker has an **explicit** place to sign, distinct from model
  execution.
- Guides and companion exist in FR/EN.
- Chrome refuses to fabricate a substitute financial total.

**Does not mean**

- “Everyone is autonomous on day one” — not measured.
- “NorthForge certifies” — visited steps certify nothing.
- “The adoption flag = mature product” — the flag is a tap.
- “Impact = ROI” — the rename does not establish the outcome.

---

## 7. Honesty contract — lines to hold / to forbid

| Hold | Forbid |
|---|---|
| *Missing data is not a zero.* | Show or narrate €0 / 0 h where the state is `not_measured` / `not_configured`. |
| *A simulation is not a measurement.* | “We simulated, therefore we gained.” |
| *Accepting in the Hypervisor records a signal.* | “The Hypervisor applies the policy by itself.” |
| *The value loop lives on a System, behind a flag.* | “Every workspace closes the loop.” |
| *Portfolio what-if is retired.* | “Move the lever, ROI updates live.” |
| *Mission Room is a workspace app.* | “Mission Room = the ledger.” |
| *Adoption is opt-in; sessions not run.* | “Adoption is user-validated.” |
| *Generated compliance = repo state, not prod proof.* | Read the mental-model lots table as a customer attestation. |

Shared fact-states: `available` · `not_measured` · `not_configured` ·
`restricted` · `unavailable`.

---

## 8. Recommended presentation path

Hard-reload (Cmd+Shift+R) before speaking. A stale tab yields bare 422s
and “this tab was opened before an update”.

1. **Work** — a published application, a question, a citation. *Consume.*
2. **Run** — deep link. *Monitor: this is the evidence, not the gain.*
3. **Hypervisor / Impact** — measured/declared legend, one pending
   decision. *Observe, then decide (signal).*
4. **System Steer** (only if `value_loop_v1` is actually on) — *Simulate
   is not measure.* Otherwise stop and say so.
5. **`/help/value`** — close on observed cost / declared value / attested
   impact.

For a NAWA client, the PR→PO Studio
(`/work/pr-to-po?workspace=nawa&lang=en`) is presented from the operator
playbook, not from the UI:
[`ops/nawa-pr-to-po-live-demo-playbook.md`](./ops/nawa-pr-to-po-live-demo-playbook.md).

---

## 9. Source map

| Document | Use |
|---|---|
| [`mental-model.md`](./mental-model.md) | Vision, entities, maturity, limits |
| [`agentium-reference.md`](./agentium-reference.md) | Lexicon, surfaces, Work / Cockpit / Studio |
| [`agentium-adoption-roadmap.md`](./agentium-adoption-roadmap.md) | Flag, lots, acceptance protocol |
| [`agentium-lot8-value-loop.md`](./agentium-lot8-value-loop.md) | Enactment Simulate → Measure |
| [`hypervisor-v2-chart-grammar.md`](./hypervisor-v2-chart-grammar.md) | v2 visual grammar, views, fact-states |
| [`deck-product-review.md`](./deck-product-review.md) | Mental-model deck (product team) |
| [`deck-agentium-decision-adoption.en.md`](./deck-agentium-decision-adoption.en.md) | C-level / business deck (this briefing) |
| [`showcase-demo-walkthrough.md`](./showcase-demo-walkthrough.md) | Hypervisor v1 script (SCAN) |

Reuse on-screen copy as-is: `frontend-ng/src/app/core/i18n/hypervisor.dict.ts`,
`experience.dict.ts`, `backend/app/content/help_content.yaml`.
