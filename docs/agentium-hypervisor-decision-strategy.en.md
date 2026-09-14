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
>
> User stories: [`agentium-hypervisor-user-stories.en.md`](./agentium-hypervisor-user-stories.en.md).
> COMEX MVP: [`agentium-hypervisor-mvp-comex.en.md`](./agentium-hypervisor-mvp-comex.en.md).

How to read: the glossary and §§1–3 are enough for a COMEX. Routes,
switches and API excerpts are notes for whoever prepares a demo or
implements — skip them.

---

## 0. Ten words

| Word | Plain meaning |
|---|---|
| **System** | An industrialized AI system: a business objective, rules, a way to run. Not a chat. |
| **Run** | One traced execution. Completed ≠ validated answer ≠ money gained. |
| **Work** | Where the business does the work, in a published application. |
| **Studio** | The screen of that application: follow, and approve when asked. |
| **Cockpit** | Where people build, follow, improve and administer Systems. |
| **Hypervisor / Impact** | The portfolio **ledger**: what already ran. Not the live operations room. |
| **Decision** | A human opinion (accept / reject). In the Hypervisor this **records** the opinion. It does not apply the change. |
| **Steer** (Pilot) | The screen of **one** System where, if it is open, you can simulate then apply a change, then measure. |
| **Value base** | A signed convention (“this kind of result is worth X hours or Y €”). It is **declared**, not accounting. |
| **Measured / declared / missing** | Three qualities of a number. Missing **is not** a zero. |

Words to avoid on screen: Desk, Board, workflow, pipeline, job, “HITL”.
Say **Flow**, **Run**, **human approval**.

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
| **Action** | Accept, reject, replay, promote a reference answer, or apply a bounded change. |

The Hypervisor is the **portfolio view** of this chain. It is not the place
where someone “presses a magic button” to change the runtime.

---

## 2. Observe, consume, monitor, decide

Four verbs, four contracts. Mixing them is the main demo failure in front
of an executive committee.

| Verb | Question | Where | What the person leaves with |
|---|---|---|---|
| **Observe** | What did the portfolio return? On what evidence? | Hypervisor / Impact | A ledger: measured / declared / missing. No invented zero. |
| **Consume** | Which task must I finish now? | Work, Studio (the published application) | A verifiable result, opened sources, a **human approval** if the rule requires it. |
| **Monitor** | What is running, waiting, drifting? | Executions, review queue, Diagnostics | Execution health and queues — explicitly **not** business success. |
| **Decide** | What is waiting for a signature, and where does the change apply? | Hypervisor queue (opinion) · approval in the application · **Steer** (apply) | A recorded opinion + a trace. The model cannot sign in their place. |

You move from Work to Cockpit by **rights**, not by a “mode” button.
Identifiers, the log and deep links are shared.

*Technical note:* Hypervisor = `/hypervisor` (the menu may say **Impact**
when the welcome path is on). Work = `/work`. Review queue =
`/steering/review-queue`.

---

## 3. The Hypervisor

### 3.1 One sentence

The Hypervisor is the **AI portfolio ledger**: what Systems executed, what
it cost, what is declared as value, what is missing, and **what is waiting
for a signature**.

Two possible readings of the same page: a **value balance sheet** (older
view) or a **ledger** (newer view). The menu may say **Impact**. Renaming
the tab **does not** establish an economic result.

*Technical note:* single route `/hypervisor`. The newer view turns on with
the workspace switch `hypervisor_v2`.

### 3.2 Two readings, one opinion to sign

| | **Older view — Value balance sheet** | **Newer view — Ledger** |
|---|---|---|
| On-screen promise | “Net value generated” — cost, estimated value, ROI, signals, recommendations | “What the portfolio returned” — ink = measured, teal = declared |
| How you read | One page of figures + signals + decisions | **Understand → Detail → Decide** |
| Windows | One page, period of choice (week / month / 30d / 90d) | Direction (hours, 90d) · Operations (executions, 30d) · Compliance (executions, 90d) |
| Value-loop summary | Yes — a read-only aggregate | No — the ledger is not the same dashboard |
| Decide | Accept / Reject | Accept / Reject |

Both views **record an opinion** (accept / reject). Neither **applies** a
rule change via “Apply”: that is refused on purpose, and the screen
points to one System’s pilot screen. That is not a demo bug.

Line to say: *“Validating here records an opinion. Changing a System
goes through its pilot screen: Simulate → Approve → Apply → Measure.”*

*Technical note:* the old apply path returns an explicit refusal
(`LEGACY_DECISION_ACTUATOR_DISABLED`).

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

**Mission Room** is an immersive **workspace application** (government /
city-style briefing). Same address family as the Hypervisor, **different
contract**. Do not present it as the portfolio ledger.

---

## 4. Where a decision becomes an action

Three planes. Do not collapse them.

```text
Portfolio                    One System                   The application
Hypervisor / Impact          Pilot screen (Steer)         Studio
accept / reject              Simulate → Approve           human approval
= an opinion                 → Apply → Measure            = required
                             = bounded change
```

### 4.1 An opinion on the portfolio

Accepting or rejecting in the Hypervisor moves the proposal to *accepted*
or *rejected*. That sometimes feeds a quality review. A **rule-change**
scenario refuses this path: it must go through the System’s pilot screen.

*Technical note:* `POST /hypervisor/decisions/{id}/accept|reject`.

### 4.2 Apply a change — value loop

Visible contract: **Result → Decision → Simulate → Approve → Apply →
Measure**.

- On **one** System, in Steer — not on the whole portfolio.
- Open only if the “value loop” switch is on **and** this System is
  chosen for the trial.
- First allowed change, deliberately narrow: a guardrail adjustment, only
  if the System declares it and execution control allows it. Otherwise:
  *not configured*.
- The starting point is a real execution recorded by the server. An
  example, a trial or a hand-typed figure is **refused**.
- *A simulation is not a measurement.* We close only if an execution
  **after** the change has been observed.
- Detail: [`agentium-lot8-value-loop.md`](./agentium-lot8-value-loop.md).

The older policy screen still exists. The “levers / what if” preview is
**off**. Do not promise a live universal impact preview: it is
**planned**, not wired.

*Technical note:* switches `value_loop_v1` + System canary; actuator
`control_policy.guardrails.patch.v1`; what-if `not_configured`.

### 4.3 Human approval in the application

In a published application (Studio), an approval request is an **explicit
human decision**. The model cannot click in the person’s place. A review
queue handles quality controls. These acts carry human provenance in the
log.

---

## 5. Industrializing AI: what it changes for strategy

Industrializing, in Agentium, is not “putting an LLM in production”.
It is holding **five disciplines** on the same `System` object.

| Discipline | What the executive committee gets | Where to see it |
|---|---|---|
| **Alignment** | Each System serves a business capability, not an orphan prompt | Capabilities, Systems, Work |
| **Publication** | What the business uses is an **application** bound to a published version | Create an app → Work |
| **Evidence** | Every answer has an execution, optional cost, context, lineage | Execution sheet, conversation “Action evidence” |
| **Governance** | Rules, access rights, log, execution control — never “prompt only” | Audit, access |
| **Allocation** | We fund, tighten or stop **on evidence** | Hypervisor + the System’s pilot screen |

Strategic consequences:

1. **The portfolio becomes a management object**, not a pile of PoCs. You
   can say *how many Systems have a value base*, *which ones only have
   runs*, *which ones are waiting for a signature*.
2. **Conversation is not a parallel channel.** It reuses the same
   rules, rights and approvals. It can start an authorized action; it
   cannot invent a right.
3. **Economics is not a decorative badge.** The five **operational
   objective** indicators are not attested ROI. The value loop owns
   economic measurements. “Hours / money saved” remains a **gap**: we
   have not proven it yet.
4. **Autonomy risk is bounded.** One allowed change type, execution
   control, a human on approvals. We industrialize control as much as
   execution.

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
| Business welcome path | Code shipped, **off by default** — not yet user-validated |
| Work / applications | The business can work in a published application; “integrated” ≠ production-accepted |
| EN/FR guides | Start, sources, Systems, executions, value |
| Guided example (NorthForge) | Four steps, on the showcase workspace, example collection required |
| Conversation companion | Present in Work and Cockpit, same perimeter as the screen, the model does not sign |
| Operational objectives | 5 bounded indicators on the System — not ROI |
| Usability sessions | **Not run** (target: 5 business + 5 developers) |
| NorthForge bar | 4/5 business users finish **unaided in 10 minutes** — not measured |
| Default / retirement | Sponsor sequence (trial → default → remove) — **not signed** |

Adoption is **not a permanent edition**. It is a rollout control. Line to
hold: *“the business path exists; it is not yet the default for every
workspace; we do not yet have the acceptance sheet.”*

### 6.2 Three “persona” layers — do not conflate them

| Layer | Values | What it changes | What it does not |
|---|---|---|---|
| **Access rights** | Rights in the workspace | What the person *may* do | — |
| **Workspace mode** | Build / Operate / Direct (+ demo, portfolio) | Screen density, home, what is said in economic or technical terms | Rights |
| **Member preference** (welcome) | Build / Use / Steer value | Tone of the guides | Mode, role, rights |

Demo mode hides providers and models (presentation-safe). Portfolio mode
exists behind the scenes, intentionally absent from the selector.

Story personas (product deck) — useful for a narrative, **not** accounts:

| Persona | Enters through | Job |
|---|---|---|
| Sarah — AI lead | Hypervisor / Impact | Arbitrate the portfolio |
| Mehdi — pilot | Pilot one System | Bound the rules |
| Alex — designer | Create | Compose a System |
| Claire — business | Work first; Cockpit only to drill an execution | Use and trace |
| Léo — curator | Knowledge | Prepare sources |
| Nadia — compliance | Audit log | Control |

Claire does not “live” in a System’s technical sheet. The business works
in **Work**. Cockpit chat is the operator path.

### 6.3 Learning curve

Three **declared** stages, not yet an automatic coach (§38 planned).

```text
1. Complete a task              Work / Studio
2. Bind the result to a Run     Citations, /runs, companion
3. Bind the Run to a decision   Impact + gates + (if on) value loop
```

| Profile | First 15 minutes | First week |
|---|---|---|
| **C-level observer** | Work → one published application → Impact → read measured / declared / missing → value help | 30d / 90d review, value-convention coverage, pending opinions, one audit pass. **No** “hours saved €” without a measurement after a change. |
| **Business user** | Work → question → open the source → (optional) guided example. Preference **Use**. | Daily Work; review queue if assigned; open an execution only to drill. *Completed ≠ validated answer.* |
| **Decision-maker** | An approval in the application **or** a Hypervisor opinion **before** opening the pilot screen | Inbox: approvals + review + Impact queue. One *Simulate → Measure* scenario only if the value loop is open on **this** System. |

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
- “The welcome path = mature product” — it is a tap, off by default.
- “Impact = ROI” — the rename does not establish the outcome.

---

## 7. Honesty contract — lines to hold / to forbid

| Hold | Forbid |
|---|---|
| *Missing data is not a zero.* | Show or narrate €0 / 0 h where the state is `not_measured` / `not_configured`. |
| *A simulation is not a measurement.* | “We simulated, therefore we gained.” |
| *Accepting in the Hypervisor records an opinion.* | “The Hypervisor applies the rule by itself.” |
| *The value loop lives on a System, if it is open.* | “Every workspace closes the loop.” |
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

1. **Work** — a published application, a question, an opened source. *Consume.*
2. **One execution** — the deep link. *Monitor: this is the evidence, not the gain.*
3. **Hypervisor / Impact** — measured / declared legend, one pending
   decision. *Observe, then give an opinion.*
4. **Pilot one System** (only if the value loop is really open) — *Simulate
   is not measure.* Otherwise stop and say so.
5. **Value help** — close on observed cost / declared value / attested
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
