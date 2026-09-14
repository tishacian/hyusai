# Agentium Hypervisor, COMEX MVP: executive specification

> Audience: executive committee, product leadership.
> Status: papAI concepts (`MVP_HYPERVISOR_COMEX`) translated to Agentium,
> **without** rebuilding “six bricks before the App”. Those bricks already
> exist under other names.
>
> Detailed stories:
> [`agentium-hypervisor-user-stories.en.md`](./agentium-hypervisor-user-stories.en.md).
> Briefing: [`agentium-hypervisor-decision-strategy.en.md`](./agentium-hypervisor-decision-strategy.en.md).
> FR: [`agentium-hypervisor-mvp-comex.md`](./agentium-hypervisor-mvp-comex.md).
> Word: [`agentium-hypervisor-mvp-comex.en.docx`](./agentium-hypervisor-mvp-comex.en.docx).

---

## Vision in one sentence

The Hypervisor is the **ledger** of the Agentium System portfolio: an
executive observes what ran and on what evidence, the business consumes
published Experiences, Runs raise a trace, a human decides (portfolio
signal, Studio gate, or Steer enactment) — inside IAM + audit, **without
an invented zero** and **without the model signing**.

---

## 1. What the MVP delivers (today, `demo/agentic`)

| papAI brick | Agentium equivalent already there | What the committee sees |
|---|---|---|
| KPI / ROI dashboard | `/hypervisor` v1 or v2 | Measured / declared / missing ledger — not audited ROI |
| Top-down objectives | `operational_objective` on a System | Five operational metrics, 1–90 days |
| Bottom-up metrics | Runs + value bases + Work | Execution evidence, not a “publish a KPI” form |
| AI assistant | Conversation companion | Scoped reads; **no** `send_directive` |
| Catalog / KB | Knowledge + Experiences | Citations from Work |
| App platform | Cockpit + Work (not a NextJS App) | `/hypervisor` and `/work` |
| Governance | IAM + `/governance/audit` | Who observes, decides, enacts |

**P0 to show in the room (hard-reload):**

1. Work — a question, a citation. *Consume.*
2. Run — the evidence. *Monitor: not the gain.*
3. `/hypervisor` — legend + one `proposed` Decision. *Observe / signal.*
4. Steer **only** if `value_loop_v1` is actually on. Otherwise say so.
5. `/help/value` — observed cost / declared value / attested impact.

MVP stories: US-AHYP-100, 101, 102, 200, 300, 301, 303, 400 (if flagged),
500, 501, 601, 800, 801, 900.

---

## 2. Prerequisites — already industrialized

The papAI note listed six bricks *before* the Hypervisor. In Agentium they
are the runtime. Do not re-spec them as a prior workstream.

| # | papAI | Agentium | COMEX caveat |
|---|---|---|---|
| 1 | Catalog | Knowledge + Experience publication | Garbage in, garbage out still holds |
| 2 | Document Center / KB | Collections, Work citations | Freshness = real ingestion |
| 3 | App platform | FastAPI + Angular, Work / Cockpit | The Hypervisor is not “the first system App” |
| 4 | Bidirectional KPI flow | Runs + `operational_objective` + `value_basis` + Decision | Still the critical brick — it **is** the ledger |
| 5 | Minimal RAG agent | Companion + read tools | The model does not sign |
| 6 | Governance | IAM, audit, Membrane | Already mandatory |

Demo order, not build order:

```text
IAM / audit  →  published System + Work  →  Runs
     →  Hypervisor (ledger + decisions)
     →  (optional) companion
     →  (optional, canary) Steer value loop
```

---

## 3. MVP user stories (COMEX table)

### Epic A — Ledger

| ID | As a… | I want… | So that… |
|---|---|---|---|
| A1 (US-AHYP-100) | Executive | Runs, cost, value with fact-state | Judge impact without an invented zero |
| A2 (US-AHYP-101) | Executive | Choose 30d / 90d | Compare |
| A3 (US-AHYP-102) | Executive | See value bases | Separate declared from native units |
| A4 (US-AHYP-201) | Executive | See the operational gap | Spot a System outside the window |

### Epic B — Top-down objectives

| ID | As a… | I want… | So that… |
|---|---|---|---|
| B1 (US-AHYP-200) | Executive | Set a bounded operational objective | Give a non-economic heading |
| B2 (US-AHYP-202) | Owner | Edit or remove | Adjust |
| B3 (US-AHYP-203) | Executive | See Systems with no objective or base | Chase owners, not show €0 |

### Epic C — Bottom-up

| ID | As a… | I want… | So that… |
|---|---|---|---|
| C1 (US-AHYP-500) | Builder | Publish an Experience | Make work consumable |
| C2 (US-AHYP-501) | Business | Produce a cited Run | Raise evidence |
| C3 (US-AHYP-503) | Executive | See silence (no Runs) | Distinguish a gap from a measured zero |

### Epic D — Decide

| ID | As a… | I want… | So that… |
|---|---|---|---|
| D1 (US-AHYP-300) | Executive | See what waits for a signature | Prioritize |
| D2 (US-AHYP-301) | Executive | Accept / reject (signal) | Trace without enacting |
| D3 (US-AHYP-303) | Business | Sign a Studio gate | Keep the human in the loop |
| D4 (US-AHYP-400) | Steward | Simulate → Measure on a System | Enact if the canary is on |

### Epic E — Companion (MVP scope)

| ID | As a… | I want… | So that… |
|---|---|---|---|
| E1 (US-AHYP-600) | Executive | Ask a scoped question | Inspect without browsing |
| E2 (US-AHYP-601) | Governance | The model does not sign | Separate speech from decision |
| E3 (US-AHYP-602) | Executive | See the perimeter | Limit leak / overclaim risk |

### Epic F — Governance

| ID | As a… | I want… | So that… |
|---|---|---|---|
| F1 (US-AHYP-800) | Admin | Separate read / signal / Act | Honour roles |
| F2 (US-AHYP-801) | Admin | Trace | Compliance |

---

## 4. Dependency matrix

| If missing | Broken US | Criticality |
|---|---|---|
| No Run / no Experience | A1, C1, C2 — empty ledger | Maximum — same “empty shell” risk as papAI |
| No value base | A1 in euros, A3 | High — stay on native units |
| IAM / audit | D2, D3, F1, F2 | Foundation |
| `value_loop_v1` off | D4 | Expected: say “not configured”, do not improvise Apply |
| Companion / tools off | E1 | Hypervisor UI still works |
| `adoption_experience_v1` off | Default Work home | `/work` exists; it is not home |

---

## 5. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Telling v1 net value as P&L | Committee decides on an estimate | Mandatory: *capability ROI model* ; v2 legend |
| Leak via companion | Same as papAI: scope = authorized Systems | Explicit scope, read tools, no signing |
| Portfolio Apply | Fake industrialization | 409 `LEGACY_DECISION_ACTUATOR_DISABLED` ; Steer only |
| “Adoption validated” | Overclaim | Flag off, sessions not run — say it |
| Mission Room | Ledger / demo-app confusion | URL prefix ≠ same contract |
| What-if / projection | Simulation sold as measurement | `not_configured` ; `simulation_is_measurement: false` |

---

## 6. What the MVP does not do

- No enactment from `/hypervisor`
- No what-if / live levers
- No papAI directives
- No Custom Metric pipeline in the Hypervisor
- No Standard / PRO gating
- No COMEX PDF/CSV export (US-AHYP-702, P2)
- No attested O5 “hours / € saved”
- No cross-workspace sharing
- No Mission Room as portfolio proof
