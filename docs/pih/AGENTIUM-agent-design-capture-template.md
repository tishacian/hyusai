# Agent Design Capture — from business need to an Agentium System

Re-cast of the Business-Requirements + TOM templates for **one purpose**: capture *just enough* business need to let Agentium architects/engineers design an agent in the Agentium mental model (**System → Run → Evaluation → Decision → Action**; Skill / Capability / System / Suite). We do **not** ask the business everything — we capture the irreducible knowledge only they hold, and **derive** the rest.

> Companion to `AGENTIUM-PIH-TOM-business-requirements.md` (portfolio level). This is the **per-agent** intake canvas that feeds it.

---

## Principles
1. **Capture only what the business uniquely knows** — the objective, the real decision rules, the sources of truth, the must-never-do, the definition of a good outcome. The architect infers skills, retrieval, models, infra.
2. **Examples beat specifications.** 3–5 real past cases (input → what a good human did → output) reveal the implicit rules *and* seed the evaluation golden set. Always ask for examples before asking for rules.
3. **Speak business; map silently.** Every question is plain-language; each answer **lands in** a specific Agentium artifact (shown in the right column — for the architect, not the interviewee).
4. **One canvas per agent/system, iterative.** Start thin, enrich after the first runs (the platform's evaluation loop surfaces the gaps).

---

## 1. The capture canvas (business-facing — ~12 fields)

| # | Ask the business (plain language) | → Lands in (Agentium artifact) |
|---|---|---|
| 1 | **The job.** "What task should this assistant take off your hands? When it works, what's the result?" | **System** objective + success definition |
| 2 | **When it starts.** "What sets it off — someone asks, a schedule, an event, an email arriving?" | **Run trigger** + execution mode (real-time / batch / event / monitor / human-augmented) |
| 3 | **What it starts from.** "What information is in hand when the task begins?" | **Context** (inputs, `data_refs`) |
| 4 | **How you do it today.** "Walk me through the steps you (or your team) take, start to finish." | the **Flow** (each step → a candidate **Skill** / tool-call) |
| 5 | **Where the truth lives.** "Which documents, systems or people do you check to do it right?" | **Connectors** + **knowledge base / retrieval** (RAG) |
| 6 | **The decisions & rules.** "At each step, what do you decide, and on what basis? Any thresholds, 'if X then Y'?" | **Decision** + business rules + **Control Policy** thresholds |
| 7 | **What it produces / does.** "What's the output, and does it *change* anything in a system (write/send/provision)?" | **Action skills** (read vs **write/side-effect**) + outputs |
| 8 | **What it must never do.** "What's off-limits? Limits, amounts, sensitive cases, who it can't act for?" | **Control Policy / mandate** (allowed actions, caps, scope, duration) |
| 9 | **Who approves.** "Which steps need a human to approve or check? Who? What if they don't respond?" | **HITL** gates + autonomy tier + escalation/reminder branches |
| 10 | **What 'good' looks like — show me.** "Give me 3–5 real cases: the situation, what a good outcome was, and a bad one to avoid." | **Evaluation** criteria + **golden set** + thresholds |
| 11 | **When it can't / goes wrong.** "If it's unsure or fails, what should happen?" | **Branches** (rejected / missed / failed) → fallback to human / ticket |
| 12 | **Scale & speed.** "How often does this happen, and how fast must it respond?" | execution mode + performance/token budget + scaling/QoS |
| (13) | **Owner.** "Who owns this process and signs off the result?" | **RACI** (operator / approver / governance) |

> Coverage rule of thumb: fields **1, 6, 8, 10** are the ones that *only the business* can give and that most determine the design — never skip them. Fields 4/5/7 can be co-discovered with the architect.

---

## 2. What we deliberately do NOT ask the business (architect derives)
Skill decomposition & naming · which model/LLM · embedding & chunking strategy · retrieval profile / fusion weights / rerank / MMR · prompt design · vector store & infra · concurrency/scaling mechanics · how mandates/audit are technically enforced. *These are engineering choices the architect makes from fields 1–13 — asking the business would only add noise.*

---

## 3. The operating frame (per-agent "TOM", lightweight)
For each agent, fix only these operating decisions (one line each):
- **Autonomy tier:** Autonomous · Approve-then-act (HITL) · Recommend-only.
- **Trigger & cadence:** chat / schedule / event; volume; SLA.
- **Systems touched (connectors):** read-from / write-to.
- **Mandate:** who the agent acts *as*, what it may do, caps, scope, duration, revocation.
- **Human roles:** operator, approver(s), governance, reviewer.
- **Data boundary:** workspace/entity isolation, residency.
- **Definition of done / KPI:** the one metric the owner will judge it by.

---

## 4. Mental-model coverage check (architect gate before build)
The capture is "enough to design" only when **every** entity below is populated:

☐ **System** (objective + success) · ☐ **Trigger/Run** (mode) · ☐ **Context** (inputs/data_refs) · ☐ **Capabilities** (the business promises) · ☐ **Skills** (read + write primitives) · ☐ **Connectors** (sources/targets) · ☐ **Decision + rules** · ☐ **Control Policy / mandate** (guardrails, caps) · ☐ **HITL gates + autonomy tier** · ☐ **Evaluation + golden set** (≥3 examples) · ☐ **Branches/fallback** · ☐ **KPI/SLA** · ☐ **Owner/RACI**.

If any box is empty, ask **one** targeted follow-up — not a full re-interview.

---

## 5. The output — Agentium System Design Card (architect fills from the capture)
```
System: <name>                         Objective: <field 1>        Success/KPI: <field 1,10,12>
Trigger / execution mode: <field 2>    Autonomy tier: <field 9>    Owner/RACI: <field 13>
Context (inputs/data_refs): <field 3>
Capabilities: <grouped promises from fields 4–7>
Skills:
  - read:   <skill> (engine, connector)        ← steps/sources (fields 4,5)
  - write:  <skill> (connector, idempotent)     ← actions (field 7)  [side-effect]
Connectors: <field 5,7>
Flow (Flow Builder):
  Trigger → retrieve/skills → policy.check → [HITL approve] → action skills → notify/close → Evaluation
  Branches: rejected / missed-approval / failed → <field 11>
Decisions & rules: <field 6>
Control policy / mandate: <field 8>  (allowed actions, caps, scope, duration, revocation)
HITL gates: <field 9>
Evaluation: golden set from <field 10> ; thresholds ; review-queue gate
```

---

## 6. Worked example (PIH — "Email Group Creation", SR#4)
**Capture (business answers):**
1. Job: create an email distribution group on request, correctly and approved. 2. Trigger: a request in the portal. 3. Starts from: requester, group name, members, manager. 4. Steps today: check approvals → create group → add members → set owner/permissions → test → notify. 5. Truth: the mail system + the approval rule (Line Manager → IT Mgmt). 6. Rules: dual approval required; names must follow the naming convention. 7. Output: a provisioned group (a **write**). 8. Never: create without both approvals; never beyond requester's scope. 9. Approvals: Line Manager then IT Management; if no response, remind up to 7×, then fail to an engineer. 10. Good/bad examples: 3 past tickets (approved→created; rejected→cancelled; missed→reminded). 11. On fail: mark Failed, assign IT engineer, notify. 12. Volume ~4/mo, minutes. 13. Owner: ITSD lead.

**→ Design card (architect):**
- System **Collaboration Provisioning · Email Group Creation**; trigger = request (event); autonomy = **approve-then-act**.
- Skills: `exo.create_distribution_group` (write, idempotent), `exo.membership_change` (write), `approval.request`, `approval.remind`, `policy.check`, `notify.send`, `itsm.create_ticket`.
- Connectors: M365/Exchange, ITSM, Teams/email.
- Flow: request → `policy.check` (naming + scope) → `approval.request` (LM→IT, `approval.remind` ≤7) → `exo.create_distribution_group` + `exo.membership_change` → `notify.send` → close. Branches: rejected / missed / failed (→ engineer).
- Control policy/mandate: no provisioning without dual approval; scope ≤ requester.
- Evaluation: golden = the 3 cases; gate = 0 out-of-mandate, naming valid.
- KPI: cycle-time, % straight-through, 0 unapproved creations.

*(The business never had to say "skill", "control policy" or "RRF" — they described the job, the rule, the limit, and gave examples. The architect produced the rest.)*

---

## 7. How per-agent captures roll up
Each capture feeds the portfolio docs without re-interviewing: field 1 → **business outcomes (BO)**; fields 6/8/9 → **TOM value streams + governance**; field 10 → **evaluation / QA golden sets**; fields 5/7 → **connector inventory**; field 12 → **scaling & analytics**. Capture the agent, and the System/Capability/Skills — and the requirements that justify them — fall out by construction.
```
business need (12 fields) → mental-model coverage check → System Design Card → Flow Builder → evaluation/QA → portfolio BR/TOM
```
