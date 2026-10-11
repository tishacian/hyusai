# Agentium Hypervisor — COMEX MVP

> One page for a COMEX or a product lead. Readable **without already
> knowing Agentium**. Details and acceptance live in
> [`agentium-hypervisor-user-stories.en.md`](./agentium-hypervisor-user-stories.en.md).
>
> Background note: [`agentium-hypervisor-decision-strategy.en.md`](./agentium-hypervisor-decision-strategy.en.md).
> FR: [`agentium-hypervisor-mvp-comex.md`](./agentium-hypervisor-mvp-comex.md).
> Word: [`agentium-hypervisor-mvp-comex.en.docx`](./agentium-hypervisor-mvp-comex.en.docx).

---

## Express glossary

| Word | Meaning |
|---|---|
| **System** | An industrialized AI system (objective, rules, execution). |
| **Run** | One traced execution. Completed ≠ validated ≠ money gained. |
| **Hypervisor / Impact** | The portfolio **ledger**: the past, not the live operations room. |
| **Decision** | A human opinion (accept / reject). It does not apply the change. |
| **Steer** | The screen where you **apply** a change on **one** System, after simulation and approval. |
| **Measured / declared / missing** | Three qualities of a number. Missing **is not** zero. |

---

## Vision in one sentence

The Hypervisor is the **ledger** of the organisation’s AI Systems: an
executive sees what actually ran and on what evidence, the business uses
published applications, each execution leaves a trace, a human decides —
give an opinion, approve in an application, or (if it is open) apply a
rule change on **one** System — **without an invented number** and
**without letting the model sign**.

---

## 1. What the MVP shows today

In papAI, six bricks had to be built *before* the Hypervisor. In
Agentium they already exist, under other names. Do not rebuild them.

| papAI said | Agentium shows | What the COMEX leaves with |
|---|---|---|
| KPI / ROI dashboard | Hypervisor / Impact page | An honest register: measured, declared, missing — **not** audited ROI |
| Top-down targets | Operational objective on a System | Five simple indicators, 1 to 90 days — **not** euros saved |
| Bottom-up metrics | Applications + executions + value conventions | Execution evidence, not a “publish a KPI” form |
| AI assistant | Conversation companion | It **reads** and explains; it does not send an order |
| Catalog / knowledge base | Knowledge + published applications | Sources cited from the work |
| App platform | Work (business) + Cockpit (build / follow) | Two spaces, according to **rights** |
| Governance | Access rights + log | Who sees, who gives an opinion, who applies |

**To show in the room** (reload the page before speaking):

1. **Work** — a question, an opened source. *The business is working.*
2. **One execution** — the evidence. *We monitor: this is not the gain.*
3. **Hypervisor / Impact** — the measured / declared legend, one pending decision. *We observe, we give an opinion.*
4. **Pilot a System** — only if the value loop is really open. Otherwise say so.
5. **Value help** — observed cost / declared value / attested impact.

Session P0 stories: US-AHYP-100, 101, 102, 200, 300, 301, 303, 400
(if open), 500, 501, 601, 800, 801, 900.

---

## 2. Already there — not a prior workstream

| # | papAI | Already in Agentium | COMEX caveat |
|---|---|---|---|
| 1 | Catalog | Knowledge + application publication | A bad source is still a bad source |
| 2 | Document centre | Collections, citations in the work | Freshness = what was actually ingested |
| 3 | App platform | Work and Cockpit | The Hypervisor is not “the first system application” |
| 4 | KPI flow | Executions + objective + value convention + decision | Still the critical brick — and it **is** the ledger, not a separate API |
| 5 | RAG agent | Companion in read mode | The model does not sign |
| 6 | Governance | Rights, log, execution control | Already mandatory |

**Demo** order, not build order:

```text
Rights and log  →  published System + business application  →  executions
     →  Hypervisor (ledger + opinions)
     →  (optional) companion
     →  (optional, limited trial) apply a change on one System
```

---

## 3. MVP user stories (COMEX table)

### A — Read the ledger

| ID | As a… | I want… | So that… |
|---|---|---|---|
| A1 (US-AHYP-100) | Executive | See executions, cost, value, with the state of the evidence | Judge impact without an invented zero |
| A2 (US-AHYP-101) | Executive | Choose 30 days / 90 days | Compare |
| A3 (US-AHYP-102) | Executive | See value conventions | Separate declared from the simple unit |
| A4 (US-AHYP-201) | Executive | See the gap to the objective | Spot a System off track |

### B — Set a heading

| ID | As a… | I want… | So that… |
|---|---|---|---|
| B1 (US-AHYP-200) | Executive | Set a bounded operational objective | Give a heading without talking about money saved |
| B2 (US-AHYP-202) | Owner | Change or remove | Adjust |
| B3 (US-AHYP-203) | Executive | See Systems with no objective or convention | Chase owners, not show €0 |

### C — Raise the field

| ID | As a… | I want… | So that… |
|---|---|---|---|
| C1 (US-AHYP-500) | Designer | Publish an application | Make the work consumable |
| C2 (US-AHYP-501) | Business user | Produce a cited execution | Raise evidence |
| C3 (US-AHYP-503) | Executive | See silence (no executions) | Tell a gap from a measured zero |

### D — Decide

| ID | As a… | I want… | So that… |
|---|---|---|---|
| D1 (US-AHYP-300) | Executive | See what is waiting for a signature | Prioritize |
| D2 (US-AHYP-301) | Executive | Accept / reject (opinion) | Trace **without** applying |
| D3 (US-AHYP-303) | Business user | Approve in the application | Keep the human in the loop |
| D4 (US-AHYP-400) | Pilot | Simulate then measure on one System | Apply **if** the trial is open |

### E — Companion (MVP scope)

| ID | As a… | I want… | So that… |
|---|---|---|---|
| E1 (US-AHYP-600) | Executive | Ask a question in my perimeter | Understand without clicking everything |
| E2 (US-AHYP-601) | Compliance | The model does not sign | Separate speech from decision |
| E3 (US-AHYP-602) | Executive | See the perimeter | Limit leak and over-promise |

### F — Rights and trace

| ID | As a… | I want… | So that… |
|---|---|---|---|
| F1 (US-AHYP-800) | Admin | Separate see / give an opinion / apply | Honour roles |
| F2 (US-AHYP-801) | Admin | Trace everything | Compliance |

---

## 4. If something is missing

| If missing | Stories hit | Severity |
|---|---|---|
| No execution / no application | A1, C1, C2 — empty ledger | Maximum — same “empty shell” risk |
| No value convention | A1 in euros, A3 | High — stay on a simple unit (executions, hours) |
| No rights / no log | D2, D3, F1, F2 | Foundation |
| Value loop off | D4 | Expected: say “not open”, do not improvise “Apply” |
| Companion off | E1 | The Hypervisor screen still works |
| Welcome path off | Default business entry | The Work path exists; it is not everyone’s home |

---

## 5. Risks to name in the room

| Risk | Impact | What we say / do |
|---|---|---|
| Telling “net value” as P&L | COMEX decides on an estimate | *Estimate model, not an audited account* |
| Leak via the companion | It sees too much | Same perimeter as the screen; read-only; it does not sign |
| “Apply” from the ledger | Fake industrialization | Refused on purpose; go through one System’s pilot screen |
| “Adoption is validated” | Over-promise | The path exists, it is off by default, user tests have not run |
| Confusing with Mission Room | Selling an immersive demo as the ledger | Different contract, same URL family |
| “What if” / projection | A simulation sold as a measurement | Not delivered on the portfolio; *a simulation is not a measurement* |

---

## 6. What the MVP does not do

- Apply a change from the Hypervisor
- A live “what if” lever on the whole portfolio
- papAI directives (types, reminder, escalation)
- Create a technical metric from the Hypervisor
- A Standard / PRO edition
- A COMEX PDF / spreadsheet export (written, not built)
- Attested hours or euros saved
- Sharing across workspaces
- Mission Room as portfolio proof
