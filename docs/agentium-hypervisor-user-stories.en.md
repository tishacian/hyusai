# User stories: Agentium Hypervisor

> This note carries the Hypervisor specification. It keeps papAI’s shape
> (`As a / I want / so that`, acceptance, priorities) and Agentium’s
> words, **readable without already knowing the product**.
>
> How to read: §0 and the glossary are enough for a COMEX. The epics are
> the product contract. *Technical note* lines are for the team that
> implements — skip them.
>
> Status: **Delivered** (already in the product) · **Partial** (exists,
> still to complete) · **Specified** (written, not built yet).
>
> Short COMEX view: [`agentium-hypervisor-mvp-comex.en.md`](./agentium-hypervisor-mvp-comex.en.md).
> Background note: [`agentium-hypervisor-decision-strategy.en.md`](./agentium-hypervisor-decision-strategy.en.md).
> French: [`agentium-hypervisor-user-stories.md`](./agentium-hypervisor-user-stories.md).
> Word: [`agentium-hypervisor-user-stories.en.docx`](./agentium-hypervisor-user-stories.en.docx).

---

## Glossary — ten words

| Word | Plain meaning |
|---|---|
| **Portfolio** | All of the organisation’s AI systems, in one workspace. |
| **System** | An industrialized AI system: a business objective, rules, a way to run. Not a chat window. |
| **Run** | One traced execution: what happened, optional cost, which sources. A **completed** Run is neither a validated answer nor money gained. |
| **Work** | The business-application space. People do the job there, without engine jargon. |
| **Studio** | The screen of a published application: follow the execution and approve when asked. |
| **Cockpit** | Where people build, follow, improve and administer Systems. |
| **Hypervisor** (also called **Impact**) | The portfolio ledger: what ran, what it cost, what is declared as value, what is missing, what is waiting for a signature. |
| **Decision** | A proposal waiting for a human: accept or reject. In the Hypervisor this **records an opinion**. It does not change the System by itself. |
| **Steer** (Pilot) | The screen of one System where, if it is open, you can simulate then apply a rule change, then measure. |
| **Value base** | A signed convention (“a result of this kind is worth X hours or Y €”). It is a **declaration**, not an accounting measurement. |

Three qualities of a number — never mix them:

- **Measured** — observed on real executions (cost, number of Runs…).
- **Declared** — hypothesis or convention (value base, estimate).
- **Missing** — we do not have the data. **That is not a zero.**

Words to avoid on screen: Desk, Board, workflow, pipeline, job. Say
**Flow**, **Run**, **human approval**.

---

## 0. The story in one sentence

As an executive, I want to see at a glance what our AI systems actually
did, have the business use the applications, follow executions without
taking them for business success, and decide myself — give an opinion in
the Hypervisor, approve in an application, or (if it is open) apply a
rule change on **one** System — so we steer AI like the rest of the
company, **without an invented number** and **without letting the model
sign in my place**.

---

## 1. Overview

### 1.1 The problem

Without a ledger, the COMEX does not know what AI actually produced.
Teams have no official path to raise evidence. People fall back on
email, meetings, or a displayed “ROI” that fabricates €0 where nothing
was measured.

### 1.2 What the Hypervisor gives

| You can… | In practice |
|---|---|
| Read the ledger | See executions, measured costs, declared value, and what is missing |
| Set a heading | Put a simple operational objective on a System (volume, delay, approvals, cost) |
| Raise the field | Published applications and each execution leave a trace |
| Decide | Accept or reject what is waiting for a signature — **recorded opinion**, not an automatic change |
| Apply a change | Only from the pilot screen of **one** System: simulate, approve, apply, measure |
| Talk to the portfolio | A conversation companion, with the same rights as the screen; it does not sign |
| Control | Who sees, who decides, who applies; everything is logged |

### 1.3 Who does what

| Persona | Job | Where |
|---|---|---|
| Executive | See the portfolio, sign opinions, arbitrate | Hypervisor |
| Pilot | Bound a System, apply a rule change if it is open | The System’s pilot screen |
| Designer | Build and publish a System or an application | Cockpit, create |
| Business user | Use the application, open sources, approve if asked | Work, Studio |
| Compliance | Check who did what | Audit log, access |

Work and Cockpit are not two visual themes: you move from one to the
other by **rights**, not by a “mode” button.

### 1.4 What turns on or off

Agentium has no “Standard / PRO” edition. Capabilities open per
workspace:

| Switch (internal name) | What you see |
|---|---|
| Business applications | Work and published applications |
| Adoption path | Business home, “Impact” menu, guides, companion — **off by default**, not yet user-validated |
| Ledger v2 | New reading (measured / declared); otherwise the older value balance sheet |
| Value loop | On **one** chosen System: simulate then apply a change |

### 1.5 If you come from papAI

| We used to say | We say now | Do not still promise |
|---|---|---|
| Suite, Workflow | System, bound to a physical business capability | “Suite KPI” |
| Hypervisor App | Hypervisor / Impact page in the Cockpit | “first system App” |
| Euro target | Operational objective (5 indicators) + **declared** value base | The big number on screen = financial truth |
| Directive to discharge | Decision + approval in the application +, if open, a rule change | papAI discharge circuit |
| Proposal / alert / insight | One decision (recommendation, review, value scenario) | Six distinct forms |
| Strategic agent that acts | Companion that **reads** and explains | Send a directive from chat |
| AI Service health | **Technical** health of executions | “Green” = business success |
| 4-step KPI pipeline | Publish an application + run + trace | Create a technical metric from the Hypervisor |
| PRO banner | Workspace switches | Paid edition |

---

## 2. Epic 1 — Read the ledger

### US-AHYP-100: See what the portfolio returned

**Status: Partial** · **P0**

As an executive, I want to see, on the chosen period, what actually ran
and on what evidence, so I can judge impact **without taking a gap for a
zero**.

Acceptance:

- [ ] The Hypervisor shows executions, results, cost and value, each with
      a clear state: available, not measured, not configured, restricted,
      unavailable
- [ ] Missing data does **not** appear as €0 or 0 h
- [ ] Older view: the big “net value” figure is announced as an
      **estimate model** (declared value minus cost), not an audited
      account
- [ ] Newer view: legend *ink = measured · teal = declared*; you
      understand, detail, decide
- [ ] You can click a row to open the System or its executions
- [ ] An “ROI” does not appear when cost is near zero

*Technical note:* Hypervisor page; shared fact-states; v2 behind the
Ledger switch.

### US-AHYP-101: Choose the period

**Status: Delivered** · **P0**

As an executive, I want to choose 30 days, 90 days or an equivalent
period, so I can compare without changing the subject.

Acceptance:

- [ ] The choice is visible at the top of the Hypervisor
- [ ] The whole screen recalculates (figures, list, decisions, charts)
- [ ] Newer view: Direction = 90 days / hours; Operations = 30 days /
      executions; Compliance = 90 days / executions

### US-AHYP-102: See value bases

**Status: Delivered** · **P0**

As an executive, I want to know which capabilities have a signed, dated,
versioned value convention, so I can separate what is **declared** from
what exists only as a count of executions or hours.

Acceptance:

- [ ] The list of bases is visible, with a status: declared, measured, or
      none
- [ ] Without a base: stay on a simple unit (executions, hours), no
      invented euro
- [ ] A declared base is **not** a proven saving

### US-AHYP-103: Do not tell the same story on both views

**Status: Delivered** · **P1**

As a pilot, I want the older and newer views to stay honest, so we do
not promise a “value-loop summary” where it is not shown.

Acceptance:

- [ ] Without the newer view: balance sheet + portfolio summary, with the
      line *A simulation is not a measurement*
- [ ] With the newer view: ledger; not that summary

---

## 3. Epic 2 — Set a heading (objectives)

### US-AHYP-200: Set an operational objective

**Status: Delivered** · **P0**

As an executive or owner, I want to put a simple objective on a System
(indicator, target, 1 to 90 days, owner, comparison point), so I can set
a heading **without talking about euros saved**.

Acceptance:

- [ ] Only five indicators: volume of completed executions, average
      duration, human waits, human-approval rate, measured cost
- [ ] Only an authorized owner can write it
- [ ] The screen shows it, and says *Not measured* or *Economic impact
      not attested here* when that is the case
- [ ] This is **not** a financial target, nor “hours / money saved”

### US-AHYP-201: See whether we hold the objective

**Status: Partial** · **P0**

As an executive, I want to see the gap between actual and target, so I
know whether the System is on track.

Acceptance:

- [ ] Actual vs target, in the indicator’s unit
- [ ] “Zero executions measured” is not the same as “we do not have the
      data”
- [ ] No economic “on time” badge just because a Run completed

### US-AHYP-202: Change or remove the objective

**Status: Delivered** · **P1**

As an owner, I want to change the target, the dates, or remove the
objective. The log keeps the trace.

### US-AHYP-203: See Systems with no heading and no convention

**Status: Partial** · **P1**

As an executive, I want to see Systems that have neither an objective
nor a value base, so I can chase owners rather than display a portfolio
“at €0”.

---

## 4. Epic 3 — Decide (opinion in the Hypervisor)

### US-AHYP-300: See what is waiting for a signature

**Status: Delivered** · **P0**

As an executive, I want the list of what is proposed and not yet
decided, so I know where I must take a stand.

Acceptance:

- [ ] Filterable queue: recommendations, reviews, value scenarios
- [ ] Each card: title, why, **estimated** impact, object concerned,
      dates
- [ ] If the queue is empty: *the portfolio is not waiting for a
      signature*

### US-AHYP-301: Accept or reject — an opinion, not a switch

**Status: Delivered** · **P0**

As an executive, I want to accept or reject a proposal, so that an
**opinion** is recorded and traceable.

Acceptance:

- [ ] Accepted or rejected, with the person and the time when the screen
      requires it
- [ ] A rule-change scenario is **not** decided here: go to the System’s
      pilot screen
- [ ] The screen does **not** offer “Apply to the whole portfolio”
- [ ] Trying to apply from the Hypervisor is **refused** (on purpose)

Line to say: *Validating here records an opinion. Changing a System is
done from its pilot screen.*

### US-AHYP-302: Ask for a recommendation analysis

**Status: Delivered** · **P1**

As an executive, I want to launch an analysis and see the
recommendations, so I can feed the queue **without taking them for
measured numbers**.

### US-AHYP-303: Approve in the business application

**Status: Delivered** · **P0**

As a business user, I want to accept or reject an approval request in
the application, so the execution waits for a human.

Acceptance:

- [ ] The model **cannot** click in my place
- [ ] A request that is too old is refused
- [ ] A review queue exists for quality controls
- [ ] The log records who signed

---

## 5. Epic 4 — Apply a change (one System at a time)

### US-AHYP-400: Change a rule from the pilot screen, not from the ledger

**Status: Delivered (limited trial)** · **P0**

As a pilot, I want, on **one** System: start from a result, propose,
**simulate**, get approval, **apply**, then **measure** — so I can change
a rule in a limited, proven way.

Acceptance:

- [ ] Open only if the “value loop” switch is on **and** this System is
      chosen for the trial
- [ ] Done on the System’s pilot screen, **not** in the Hypervisor
- [ ] One change type for now (policy guardrails), and only if security
      allows it; otherwise: *not configured*
- [ ] The starting reference is a real execution recorded by the
      server — not an example, not a hand-typed figure
- [ ] *A simulation is not a measurement*
- [ ] We close only if an execution **after** the change has been
      observed

### US-AHYP-401: Read a portfolio summary without claiming victory

**Status: Delivered (older view only)** · **P1**

As an executive, I want to see, on the older view, the observed gap,
risks and scenarios, so I can open the right System — **not** to say
“we simulated, therefore we gained”.

---

## 6. Epic 5 — Raise the field

### US-AHYP-500: Publish a business application

**Status: Delivered** · **P0**

As a designer, I want to publish an application bound to a frozen
version of a System, so the business works in Work, without opening the
engine.

Acceptance:

- [ ] Draft → published version (we do not rewrite it) → in service
      (pilot or live)
- [ ] The business enters through Work, not through the System’s
      technical sheet

### US-AHYP-501: Leave evidence on every execution

**Status: Delivered** · **P0**

As a business user or designer, I want an execution to leave a trace
(optional cost, sources, history), so the ledger has something to talk
about.

Acceptance:

- [ ] You can open the trace from Work, the companion or the Hypervisor
- [ ] *Completed ≠ validated answer ≠ money gained*
- [ ] Throughput and latency stay in a “technical health” drawer

### US-AHYP-502: Declare a value convention

**Status: Delivered** · **P1**

As a pilot, I want to declare “a result of this kind is worth X hours or
Y €”, with my name, so the ledger converts **without inventing a
measurement**.

### US-AHYP-503: See silent Systems

**Status: Partial** · **P1**

As an executive, I want the absence of recent executions to appear as a
**gap**, not as a beautiful zero performance.

---

## 7. Epic 6 — Talk to the portfolio (companion)

### US-AHYP-600: Ask a question in English (or French)

**Status: Partial** · **P1**

As an executive or business user, I want to query the Systems I am
allowed to see, so I can understand without clicking everywhere — **with
the same rights as on the screen**.

Acceptance:

- [ ] The companion is there in Work and in the Cockpit
- [ ] I pick up to ten Systems; if I pick none, we explore, we launch
      nothing
- [ ] It can inspect a System, compare executions, read operational
      indicators
- [ ] It uses the same rules as the on-screen buttons
- [ ] When a System has run: sources and evidence visible
- [ ] Guides exist: start, sources, Systems, executions, value

### US-AHYP-601: Stop the model from signing

**Status: Delivered** · **P0**

As compliance, I want no conversation turn to accept an approval in
place of a human.

### US-AHYP-602: See the perimeter before talking

**Status: Partial** · **P1**

As an executive, I want to see *what* the companion can reach (Systems,
workspace, read-only or not), so I do not take it for an oracle.
Sending a directive or inventing a forecast from chat: **out of
contract**.

---

## 8. Epic 7 — What needs attention

### US-AHYP-700: One attention queue

**Status: Partial** · **P1**

As an executive, I want in one place: pending opinions, late
objectives, Systems without a convention, risks on a rule change — so I
can react. A technical “down” light is **not** a business failure.

### US-AHYP-701: An honest trend

**Status: Partial** · **P2**

As an executive, I want to see day-by-day evolution. A “future month”
projection or a “what if we moved the lever” on the whole portfolio
**is not delivered**. Until we have evidence, we do not draw a dotted
bar.

### US-AHYP-702: Export a COMEX pack

**Status: Specified** · **P2**

As an executive, I want an export of the period (PDF or spreadsheet):
register, bases, decisions, and the measured / declared / missing
mention. **Not built yet.**

---

## 9. Epic 8 — Who may, and the trace

### US-AHYP-800: Separate see, decide, apply

**Status: Delivered** · **P0**

As an administrator, I want distinct rights: read the Hypervisor,
accept or reject, write an objective, apply a change, publish an
application. The workspace “mode” (build, use, steer) changes **screen
density**, not rights.

### US-AHYP-801: Trace everything

**Status: Delivered** · **P0**

As compliance, I want in the log: opinions, human approvals, objective
writes, steps of a rule change. Each line: who, what, on what, when.
(Help-path progress: metadata only, not the content of questions.)

### US-AHYP-802: Do not confuse with Mission Room

**Status: Delivered** · **P0**

As product, I want an immersive briefing room (government / city demos)
to stay a **workspace application**, so we do not sell it as the
ledger.

---

## 10. Epic 9 — Honesty and first use

### US-AHYP-900: Forbid the invented zero

**Status: Delivered** · **P0**

As product, I want no substitute financial total to appear in the
screen chrome. “Hours or euros saved” is **not** yet a number we can
defend.

### US-AHYP-901: Start with a business task

**Status: Delivered (path off by default)** · **P1**

As a business user, I want a first verifiable result (guided example,
four steps, alone, in ten minutes — **target not yet measured**) without
opening the Cockpit. The welcome path is **not** on everywhere; user
tests have **not** happened yet.

---

## 11. We do not promise

- Applying a change from the Hypervisor
- A live “what if” lever on the whole portfolio
- papAI directives (urgent / strategic, reminder, escalation)
- Creating a technical metric from the Hypervisor
- A Standard / PRO edition
- A COMEX export (written, not built)
- Attested hours or euros saved
- Sharing across workspaces
- Mission Room = Hypervisor

---

## 12. Recap

**P0** indispensable in a COMEX session · **P1** desirable · **P2** later.

| ID | Epic | Title | P | Status |
|---|---|---|---|---|
| US-AHYP-100 | Ledger | See what the portfolio returned | P0 | Partial |
| US-AHYP-101 | Ledger | Choose the period | P0 | Delivered |
| US-AHYP-102 | Ledger | See value bases | P0 | Delivered |
| US-AHYP-103 | Ledger | Two views, two honest stories | P1 | Delivered |
| US-AHYP-200 | Objectives | Set an operational objective | P0 | Delivered |
| US-AHYP-201 | Objectives | See whether we hold the objective | P0 | Partial |
| US-AHYP-202 | Objectives | Change or remove | P1 | Delivered |
| US-AHYP-203 | Objectives | Systems with no heading or convention | P1 | Partial |
| US-AHYP-300 | Decisions | See what is waiting for a signature | P0 | Delivered |
| US-AHYP-301 | Decisions | Accept or reject (opinion) | P0 | Delivered |
| US-AHYP-302 | Decisions | Ask for recommendations | P1 | Delivered |
| US-AHYP-303 | Decisions | Approve in the application | P0 | Delivered |
| US-AHYP-400 | Change | Simulate then measure on one System | P0 | Delivered (limited trial) |
| US-AHYP-401 | Change | Read the summary without claiming victory | P1 | Delivered |
| US-AHYP-500 | Field | Publish an application | P0 | Delivered |
| US-AHYP-501 | Field | Leave execution evidence | P0 | Delivered |
| US-AHYP-502 | Field | Declare a value convention | P1 | Delivered |
| US-AHYP-503 | Field | See silent Systems | P1 | Partial |
| US-AHYP-600 | Companion | Ask a question | P1 | Partial |
| US-AHYP-601 | Companion | The model does not sign | P0 | Delivered |
| US-AHYP-602 | Companion | See the perimeter | P1 | Partial |
| US-AHYP-700 | Attention | One attention queue | P1 | Partial |
| US-AHYP-701 | Attention | An honest trend | P2 | Partial |
| US-AHYP-702 | Attention | COMEX pack export | P2 | Specified |
| US-AHYP-800 | Rights | Separate see / decide / apply | P0 | Delivered |
| US-AHYP-801 | Rights | Trace everything | P0 | Delivered |
| US-AHYP-802 | Rights | Mission Room is not the ledger | P0 | Delivered |
| US-AHYP-900 | Honesty | No invented zero | P0 | Delivered |
| US-AHYP-901 | First use | Start with a business task | P1 | Delivered (off by default) |
