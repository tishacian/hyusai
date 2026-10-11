# Agentium × PIH / PowerMind — Synthesis: Systems, Capabilities, Skills & Connectors

**Source:** `PIH_IT_Automation_RFP_PowerMind_1.docx` (RFP PM-RFP-ITSM-2026-001) + `IT Operations Automation Details.xlsx` (39 use cases, manual vs automated process, volumes, times).
**Purpose:** map the PIH IT Service Desk workflow onto the Agentium grammar (Skill → Capability → System → Suite) and the Flow Builder, then recommend **four** systems to prioritise as POCs — selected because their building blocks are **already factorised on Agentium** and they **universalise beyond PIH** (each carrying the original use-case names it covers).

> Confidential — internal analysis. Not for external distribution.

---

## 1. The need in one paragraph

PIH (a diversified conglomerate, multi-entity, distributed workforce) runs **39 live automations** on a conversational platform (Leena AI — "Daizy" bot, "QWIK BOT", desktop agent) across **Active Directory, Microsoft 365, SAP SuccessFactors, Oracle Symphony and internal ITSM**. PowerMind issues the RFP to **consolidate, enhance and scale** these onto a next-generation, **sovereign** AI service desk that (a) automates L1/L2 across channels (Teams, web, mobile, email), (b) reduces and deflects tickets, (c) exposes KPIs/ROI (MTTR, deflection, CSAT), (d) is API-first with OOTB connectors, (e) adds **proactive operations & root-cause analysis**, (f) scales multi-entity, and (g) enables the IT team to own and extend the platform. This is precisely an **Agentium** play: governed agent flows on infrastructure the client controls.

**Client-confirmed sizing & landscape (clarification answers, July 2026):**

- **Volume:** ~**5,800 tickets/month ≈ 70K/year** for group support services — *excluding* the task volume already avoided by the 39 live automations. The new platform therefore (i) re-hosts the 39 automated flows *and* (ii) attacks the ~70K/yr residual human-handled tickets (deflection + new automation headroom).
- **Population:** ~**12,200 active email users** entitled to raise ITSD tickets (≈ 5.7 tickets/user/yr) — across 145+ companies, 289+ sites, 25 countries.
- **Current ITSM:** ManageEngine ServiceDesk Plus ("good for SMB") + Leena AI (workflow-automation model, judged weak on agentic AI, roadmap and SLA performance). The client explicitly frames the target as **"the new Leena"** — a replacement of the conversational/automation layer, with SDP as the current ticket system of record.
- **Confirmed integration targets** (client wording: "mainly but not limited to"): **Microsoft Teams · ITSD Portal (ServiceDesk Plus) · SSO · On-Prem AD + Azure AD (Entra) · Egnyte** (cloud content/file governance) · **SolarWinds ARM** (Access Rights Manager — access audit/remediation) · **Palo Alto / Fortinet firewalls** (network security requests).

---

## 2. From 39 use cases to the Agentium grammar

The 39 use cases collapse into **5 Systems** built from a **shared catalog** of Capabilities, Skills and Connectors. Nothing is bespoke per use case — each use case is a **Flow** assembled from reusable nodes.

| # | System (verticalised) | Use cases covered (xlsx SR#) | Monthly volume (order) |
|---|---|---|---|
| **S1** | **Sovereign Conversational Service Desk & Deflection** (the front door) | 18 (KB Q&A), 19 (ticket create/track ~1 100), 26 (auto-closure) + the conversational/intent/routing layer for **all** | very high |
| **S2** | **Identity & Access Lifecycle (Joiner-Mover-Leaver / IAM)** | 1, 2, 14, 15, 20, 21, 22, 23, 24, 25, 27, 28, 31, 32, 33, 34, 38 | **highest** (offboarding SF 843, on-prem 416, pwd-expiry 1 800, signature 294, Oracle 199, onboarding 100…) |
| **S3** | **Collaboration & Messaging Provisioning** | 4, 5, 6 (email groups), 7, 8, 9 (shared mailboxes), 36 (announcements) | medium, approval-heavy |
| **S4** | **Endpoint & Device Operations** (self-healing + provisioning) | 3 (Outlook), 10–13 (printers), 16 (software), 17 (Win update), 30 (device data), 35 (hardware info) | medium |
| **S5** | **Proactive Operations & Root-Cause Analysis (AIOps)** | 14 (proactive pwd-expiry), 29 (T&A offline detection), 37 (data-sync validation), 39 (analytics) + RFP §4.5 RCA + §4.3 KPIs | the "next-gen" layer |

Cross-cutting through S1–S4: **Approval Orchestration** (Line Manager → IT Management, reminders up to 7×, reject/missed/failed branches — visible in the xlsx as "Main / Rejected / Missed / Failed agents").

---

## 3. Capabilities catalog (reusable business promises)

| Capability | What it delivers | Feeds systems |
|---|---|---|
| **Conversational intake & intent routing** | NLP intent recognition, multi-turn, entity extraction, multi-channel (Teams/web/mobile/email) | S1 (all) |
| **Grounded knowledge answering (RAG)** | Sovereign OmniRAG over KB/policies, cited, low-hallucination | S1, S5 |
| **Ticket triage, deflection & lifecycle** | Classify, route, create/track/close, deflect to self-service | S1 |
| **Identity lifecycle management** | Provision / mutate / deprovision identities & mailboxes across AD/M365/SF/Oracle | S2 |
| **Entitlement & access management** | Licences, group/mailbox membership, VPN/AVD, blocks | S2, S3 |
| **Approval orchestration** | Multi-level approvals, reminders/escalation, reject/missed/failed handling | S2, S3 |
| **Endpoint remediation & provisioning** | Desktop-agent self-heal, printer/software/patch | S4 |
| **Proactive detection & remediation** | Watch signals, detect drift/offline/missing-sync, act before the ticket | S5 |
| **Root-cause & trend analysis** | Recurring-incident clustering, pattern recognition, RCA, remediation recommendations | S5 |
| **Service analytics & ROI** | MTTR, deflection rate, automation effectiveness, CSAT, ROI dashboards | S5 (all) |
| **Human-in-the-loop & privileged-action gating** | Review queues, control-policy guardrails on sensitive writes | all |

---

## 4. Skills catalog (atomic, reusable primitives = flow nodes / tool-calls)

- **Identity & directory:** `ad.reset_password`, `ad.unlock_account`, `ad.create_user`, `ad.disable_user`, `ad.enable_user`, `ad.set_attribute` (signature / office / end-date), `ad.group_add` / `ad.group_remove`.
- **Microsoft 365:** `m365.assign_licence` / `m365.remove_licence`, `m365.create_mailbox`, `m365.block_signin`, `m365.revoke_sessions`, `exo.create_distribution_group`, `exo.create_shared_mailbox`, `exo.membership_change`, `exo.set_forwarding`.
- **HR / ERP:** `sf.read_joiner`, `sf.read_status`, `sf.read_profile`, `oracle.deactivate_account`.
- **Service desk:** `nlu.classify_intent`, `nlu.extract_entities`, `kb.semantic_search` (OmniRAG), `itsm.create_ticket`, `itsm.update_ticket`, `itsm.assign`, `itsm.close`, `notify.send` (email/Teams) — ITSM target = ManageEngine ServiceDesk Plus (REST).
- **Access & network security (client-confirmed integrations):** `arm.review_access`, `arm.revoke_access` (SolarWinds ARM — access audit/remediation), `egnyte.grant_access` / `egnyte.revoke_access` (file/content permissions), `fw.request_rule`, `fw.validate_rule`, `fw.apply_rule` (Palo Alto PAN-OS / Fortinet — **approve-then-act by construction**, mandate-gated privileged writes).
- **Endpoint:** `agent.is_running`, `agent.install`, `endpoint.outlook_selfheal`, `printer.map` / `printer.gen_code` / `printer.upgrade_colour`, `endpoint.push_software`, `endpoint.push_windows_update`, `endpoint.fetch_hardware`, `web.lookup_serial` (model/year).
- **Proactive / analytics:** `monitor.detect_device_offline`, `data.validate_sync` (DB↔SAP push), `analytics.trend`, `analytics.anomaly`, `rca.explain` (Datategy RCA — FA-RAG / Big GCVAE), `kpi.compute` (MTTR / deflection / ROI), `dashboard.extract`.
- **Cross-cutting:** `approval.request`, `approval.remind` (retry ≤ N), `policy.check` (guardrail), `identity.verify`.

---

## 5. Connectors catalog

Active Directory (on-prem) + Azure AD / Entra ID · Microsoft 365 (Graph: licences, mailboxes, sign-in, sessions; Exchange Online) · SAP SuccessFactors (joiner/leaver, status, profile) · Oracle Symphony · **ITSM = ManageEngine ServiceDesk Plus** (client-confirmed; REST API) · Microsoft Teams / Email / Web portal (channels) · SSO (Entra) · **Egnyte** (content/file governance — REST) · **SolarWinds ARM** (access-rights audit & remediation — feeds S2/IAM) · **Palo Alto PAN-OS / Fortinet FortiGate** (firewall-rule & network-access requests — privileged writes, mandate-gated) · Printer-management system · Patch / endpoint-management + desktop agent · Knowledge base → vector index · T&A devices + attendance DB + SAP (attendance push) · IT analytics DB / BI · Vendor warranty web lookup (device data collector).

> RFP §4.4 / §6.2 explicitly require OOTB connectors for **AD, M365, SAP SuccessFactors, Oracle** and ITSM; client clarifications (July 2026) confirm the ITSM is **ServiceDesk Plus** and add **Egnyte, SolarWinds ARM and Palo Alto/Fortinet** ("mainly but not limited to"). All map to Agentium's connector framework + skills-as-tools + MCP surface. The firewall connectors are the clearest case for **signed mandates + control-policy guardrails** (a firewall-change agent must be approve-then-act by construction); SolarWinds ARM extends the IAM system (S2) with access-review and remediation skills (`arm.review_access`, `arm.revoke_access`); Egnyte adds file-permission and content-request skills.

---

## 6. How it lands on the Flow Builder

Every use case becomes one **governed Flow** (a graph) — not bespoke code. Canonical node sequence:

```
Trigger (chat intent / schedule / event)
  → nlu.classify_intent + nlu.extract_entities
  → kb.semantic_search            (deflect first, if answerable)
  → policy.check                  (control-policy guardrail: who/what/cap/scope)
  → approval.request → approval.remind   (HITL, multi-level, reject/missed/failed branches)
  → skill tool-calls              (e.g. ad.create_user → m365.assign_licence → notify.send)
  → itsm.create_ticket / itsm.close
  → Evaluation                    (quality / grounding / outcome scoring)
```

What Agentium adds on top of the bare flow — and what the current Leena setup cannot prove:

- **Stateful, replayable runs + checkpoints** → resume/replay any execution (RFP "robustness"); the *black box* axis.
- **Tool-calling ledger + tamper-evident audit** → every privileged action traced, timestamped, costed, exportable (RFP observability/audit).
- **RBAC + ABAC + distinct agent identity + control-policy guardrails** → an agent can never exceed its mandate (RFP security); the *power-of-attorney* axis — critical for IAM writes.
- **Evaluation loop** → deflection/answer quality scored, thresholds gate auto-resolution vs human review; the *dress-rehearsal* axis for safe change.
- **Sovereign deployment** → models + data + action ledger inside the client boundary (RFP data residency).
- **Hypervisor / analytics** → MTTR, deflection, ROI per capability and per system (RFP §4.3 KPIs).

The xlsx "agents per flow" (e.g. *Email Group Creation* = 9 main / 7 rejected / 12 missed / 10 failed) maps **1:1** to Agentium flow branches — i.e. the migration of the 39 use cases is a **flow-authoring exercise on a shared skill/connector library**, not 39 rebuilds.

---

## 7. The four systems to prioritise as POCs

Selection lens (applied identically to all four): **(a) the building blocks are already factorised on Agentium** (lift-as-is, days not months); **(b) it universalises far beyond PIH** (portable as a reusable Suite); **(c) it showcases Agentium's true differentiators** (owned, sovereign, governed, evaluated) rather than commodity RPA; **(d) fast, measurable.**

> *Original use-case names are quoted verbatim from the RFP / `IT Operations Automation Details.xlsx` (SR# in brackets).*

### ⭐ POC #1 — Sovereign Conversational Service Desk & Knowledge Deflection (S1)

**What:** the multi-channel front door — intent recognition → grounded RAG answer (deflect) → else triage/route/create/track ticket → evaluation.
**Original use cases:** *User Q&A - Knowledgebase Automation* (18) · *Ticket creation & tracking through Daizy* (19) · *Closure of non-responsive tickets* (26) — plus the conversational layer fronting all others.
**Factorised on Agentium (lift-as-is):** OmniRAG engine (`services/rag/*`, `services/retrieval/*`), `/chat/stream` SSE + grounded citations, capture engine to build/maintain the KB, golden-eval harness.
**Universalises beyond PIH:** any org's support front door — IT, **HR, customer support, facilities, finance**; only the KB + ITSM connector change.
**Showcases:** sovereign grounded RAG (cited, low-hallucination, on-prem) vs a generic hosted chatbot. **KPIs:** deflection %, MTTR↓, CSAT, grounded-answer %.

### ⭐ POC #2 — Proactive Operations & Root-Cause Analysis / FA-RAG (S5, "AIOps")

**What:** ingest ITSM history + signals → recurring-incident clustering & trend analysis → **RCA** → proactive remediation + closed-loop detectors.
**Original use cases:** *AD Password Expiry Reminders* (14) · *T&A device proactive detection of failure* (29) · *Proactive Validation of Data Sync with DB/SAP* (37) — plus RCA over the full ticket history (RFP §4.5).
**Factorised on Agentium (lift-as-is):** retrieval-precision blocks (`corpus_planner`, `comparative_retrieval`, `retrieval_policy` required-terms/anti-bleed, `cross_encoder_stage`, `decision_trace`), structured facts (`KnowledgeDocumentFact`/`KnowledgeTableFact` via `/knowledge/document-query` & `/table-query`), `worker_deep_retrieval` — **plus Datategy's owned FA-RAG / Big GCVAE** RCA innovation. *(Only new code: an RCA egress agent.)*
**Universalises beyond PIH:** the **same engine as Datategy's industrial MCO** (AIOps @ Mobilize Financial Services) → IT service desk → IT ops → **equipment MCO across sectors**. The "next-gen" layer the market is weakest on.
**Showcases:** owned RCA ("owned vs rented intelligence"), proactive prevention. **KPIs:** recurring-incident reduction %, tickets prevented, MTTR↓, RCA acceptance.

### ⭐ POC #3 — Identity & Access Lifecycle / Governed Provisioning — JML (S2)

**What:** joiner-mover-leaver across AD / M365 / SuccessFactors / Oracle, every privileged action mandated, signed, replayable.
**Original use cases (highest volume of the 39):** *Password Reset* (1) · *Unlock AD Account* (2) · *User Signature Update* (15) · *User Office address Updates* (20) · *Email Creation* (21) · *Email Reactivation* (22) · *Onboarding through QWIK BOT* (23) · *Offboarding based on On-Prem AD Data* (24) · *Offboarding based on Intra AD Data* (25) · *Oracle Symphony Offboarding Inactive Staff* (27) · *Offboarding based on SF data* (28) · *Consultant Email ID Creation* (31) · *Consultant AVD/VPN access* (32) · *Email Block (HR + IT)* (33) · *Providing VPN/AVD access for users* (34) · *Email Expiry Reminder … (Consultants)* (38).
**Factorised on Agentium (lift-as-is):** the run engine + skill registry (`services/run_engine`, `services/skills_registry`), **control-policy guardrails + HITL approvals** (`services/decisions`, policy), **RBAC + ABAC + distinct agent identity** (`core/iam`, `services/iam`), **tool-calling ledger + tamper-evident audit**, connector framework (AD/M365/SF/Oracle). *(Only new work: the directory/ERP write-skills + connector credentials.)*
**Universalises beyond PIH:** JML across directory + HRIS + ERP is the **most universal IT process** in any enterprise. **This is the exact embodiment of the executive deck's axes** — *power of attorney* (signed mandates) and *black box* (replayable, audited privileged actions).
**Showcases:** governed autonomy on sensitive actions — provable, not promised. **KPIs:** actions automated/month, 0 out-of-mandate actions, offboarding SLA, audit completeness.
**Risk control:** start in **simulate / read-only** + one safe write (e.g. password-expiry reminders), then scale to full provisioning once guardrails + audit are validated.

### ⭐ POC #4 — Approval-Orchestrated Service Requests & Collaboration Provisioning (S3)

**What:** governed self-service requests — request → multi-level approval (Line Manager → IT Management, reminders, reject/missed/failed branches) → provisioning → notify.
**Original use cases:** *Email group – Creation* (4) · *Email group – Members Addition* (5) · *Email group – Members Deletion* (6) · *Shared Mailbox Creation* (7) · *Shared Mailbox User Addition* (8) · *Shared Mailbox User Deletion* (9) · *Announcement Communication Automation* (36).
**Factorised on Agentium (lift-as-is):** the **same approval-orchestration + control-policy + connector machinery as POC #3** (so it is largely *already built once #3's core is in*), composed on the **Flow Builder** — the xlsx "Main / Rejected / Missed / Failed agents" branches map 1:1 to flow branches.
**Universalises beyond PIH:** the *governed self-service request → approval → fulfilment* pattern generalises beyond IT to **HR, finance, facilities, procurement** — any approval-gated request.
**Showcases:** the Flow Builder + multi-level HITL approvals on a **lower-risk surface** (good safe precursor to #3's privileged writes). **KPIs:** request cycle-time↓, approval SLA, % straight-through.

### Why these four, in this order

1. **#1** universal **quick win**, instant ROI (deflection); 2. **#2** the **differentiator** with the widest reach (beyond IT, reusing Datategy's R&D moat); 3. **#3** the **highest-volume** process and the governance showcase (mandates + audit); 4. **#4** the **safe, fast** demonstration of the approval Flow Builder that also pre-builds #3's core. #1/#4 are the lowest-risk fast wins; #2/#3 carry the strategic value.

**Cross-cutting (ships with all four, not a separate POC):** a **Service Analytics & ROI cockpit** reusing Agentium's **Hypervisor** + run ledger + metrics + evaluation — satisfies RFP §4.3 (MTTR, deflection, ROI, SLA) and absorbs *Leena Dashboard Data Extractor* (39).

### Remaining track (after the four POCs)

**S4 — Endpoint & Device Operations** (more RPA-shaped, desktop-agent dependent): *Outlook self-healing* (3) · *Printer installation* (10) · *Printer Code Creation* (11) · *Color Printer Access* (12) · *Print code Queries* (13) · *Software installation* (16) · *Windows Update Installation* (17) · *Device Manufacturing data collector* (30) · *Collecting user hardware information through Daizy* (35).
