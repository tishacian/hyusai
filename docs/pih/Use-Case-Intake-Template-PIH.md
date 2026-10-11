# Use Case Intake & Evaluation — Datategy × PIH

**Purpose.** This is the structured grid Datategy uses to evaluate a candidate
agent use case submitted by PIH. It serves two goals at once: (1) it returns
the prerequisites and open questions needed to complete the use case, and
(2) it progressively becomes the shared exchange format between the business
requesters, PowerMind and the Datategy CoE — each iteration refines what we
capture and when a direct conversation with the requester is needed.

How it works: PIH sends a use case in any format. We map it onto the grid
below, mark each item **Provided / To clarify / Missing**, and return it with
our questions within [2] working days. Items marked "requester" usually need a
short direct exchange with the business owner rather than a written loop.

---

## 1 · Business framing

| # | Item | Why we need it | Typical source |
|---|---|---|---|
| 1.1 | Business problem in one paragraph — what happens today, who suffers, at what frequency/volume | Anchors scope and success criteria | Requester |
| 1.2 | Requesting entity & business owner (name, role) | Design-card sign-off, acceptance authority | PowerMind / BA |
| 1.3 | Users of the agent (roles, count, languages EN/AR) | UX, permissions, language stack | Requester |
| 1.4 | Expected outcome & how success is measured today (KPI, SLA, cost/time per case) | Golden-set design, value tracking in the Hypervisor | Requester |
| 1.5 | Volume: cases per day/week, peak patterns, seasonality | Sizing, run scheduling | Requester / ops data |

## 2 · Process & decision logic

| # | Item | Why we need it | Typical source |
|---|---|---|---|
| 2.1 | Current process step by step (even informal) — inputs, decisions, outputs, exceptions | Flow design; what stays human | Requester walkthrough |
| 2.2 | Decision points: which are rule-based vs judgement-based | Where gates/human approval sit | Requester |
| 2.3 | 10–20 worked examples of real cases with the expected correct outcome | Seed of the **golden set** (stored at PIH, PIH IP) | Requester / archives |
| 2.4 | Error tolerance: what happens if the agent is wrong; is a human review acceptable and where | Gate placement, risk tier | Requester + PowerMind |

## 3 · Data & systems

| # | Item | Why we need it | Typical source |
|---|---|---|---|
| 3.1 | Systems touched (SAP module/transaction, Databricks tables, file shares, email, other apps) | Connector selection & access requests | IT + requester |
| 3.2 | For each system: read or write? If write — which transactions, with what approval today | Privileged-write policy, parallel-run validation | IT |
| 3.3 | Data samples (anonymised acceptable at intake stage) | Feasibility check, prompt/skill design | BA |
| 3.4 | Documents involved: formats, volumes, languages, quality (scans? handwriting?) | Document Center / OCR / indexing scope | Requester |
| 3.5 | Data sensitivity & residency constraints (personal data, commercial, classified) | Deployment tier, masking rules | IT / compliance |

## 4 · Access & environment (prerequisites we will request)

| # | Item | Why we need it |
|---|---|---|
| 4.1 | Service accounts / API access to the systems in 3.1, sandbox first | Build & test without touching production |
| 4.2 | Test environment or representative extract for the data in 3.3 | Golden-set runs before any production contact |
| 4.3 | Named IT contact per system | Unblocks access issues fast — historically the critical path |
| 4.4 | Where the agent must run: PIH on-prem / sovereign tenancy / Datategy SaaS (POC) | Infrastructure & network prerequisites |

## 5 · Our evaluation (returned by Datategy)

| # | Item | Content |
|---|---|---|
| 5.1 | Feasibility | Feasible now / feasible with conditions / needs de-scoping — with reasons |
| 5.2 | Tier | Simple / Medium / Complex, per the Annex B typology, with the drivers (systems touched, write access, reasoning depth) |
| 5.3 | Reuse | Which existing patterns/skills/connectors apply; what would be first-of-type |
| 5.4 | Effort & lead time | Indicative build window once access in 4.x is confirmed (planning heuristic, not contractual) |
| 5.5 | Open questions | The list that goes back to the BA / requester, each tagged written-answer vs direct-exchange |
| 5.6 | Risks & assumptions | Anything that could invalidate the estimate |

---

## 6 · Where this fits — the delivery-methodology chain

This grid is the **lightweight screening step**. Once a use case is qualified,
it flows into the Datategy delivery-methodology templates (ISO/IEC 42001 &
12792 aligned):

1. **Business Requirements** (`DTG-METH-BR`) — full capture of the why/what:
   personas and trust posture, As-Is → To-Be process, functional and
   non-functional requirements, KPIs. Sections 1–3 of this grid pre-fill it.
2. **Target Operating Model** (`DTG-METH-TOM`) — how the function operates
   once live: human + agent value streams, HITL integration, roles and RACI.
3. **QA Acceptance Record** (`DTG-METH-QA`) — the procès-verbal de recette
   qualifying the delivered system for go-live: entry criteria, golden-set
   gates, must-pass qualification. Item 2.3 of this grid (worked examples)
   seeds the golden set used here.

Templates: `docs/render/out/Datategy-Template-Business-Requirements.docx`,
`Datategy-Template-Target-Operating-Model.docx`,
`Datategy-Template-QA-Acceptance-PV.docx`.

---

*Process note (internal): log for each use case the date received, date
returned, number of clarification round-trips, and which questions required a
direct requester exchange — this is the raw material for refining the
CoE / PowerMind / PIH operating process the sponsor asked for.*
