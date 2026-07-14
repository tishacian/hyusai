# PIH / PowerMind — Business Requirements & Target Operating Model (TOM)

Companion to `AGENTIUM-PIH-systems-synthesis.md` and `AGENTIUM-PIH-reuse-from-andritz.md`.
Source: RFP PM-RFP-ITSM-2026-001 + `IT Operations Automation Details.xlsx` (39 use cases).

> Confidential — internal. Two layers sit **above** the technical scope:
> **Business Requirements** = *what the business needs and why* (outcomes + functional/non-functional + KPIs + constraints).
> **Target Operating Model** = *how the AI-augmented IT Service Desk will run* (service, process, people, technology, data, governance, service-management, sourcing, finance, transition).
> Chain: **Business Requirements → TOM → Solution/technical scope** (the Systems/Skills/Capabilities + the 4 POCs).

---

## PART 1 — Business Requirements

### 1.1 Business outcomes (the "why" — from RFP §3)
| ID | Outcome | Target signal |
|---|---|---|
| BO-1 | Reduce manual L1/L2 IT support effort | effort/ticket↓, automation coverage↑ |
| BO-2 | Improve first-response time & end-user satisfaction | FCR↑, MTTR↓, CSAT↑ |
| BO-3 | Consolidate the **39 existing use cases** onto one unified, scalable, **sovereign** platform | 39/39 migrated & validated |
| BO-4 | Enable **proactive** IT operations (trend analysis + root-cause) | recurring incidents↓, tickets prevented↑ |
| BO-5 | Real-time performance visibility (dashboards/analytics) | MTTR, deflection, ROI, SLA live |
| BO-6 | Empower the IT team (enablement, AI-native service mgmt) | client-run platform, CoE stood up |
| BO-7 | Measurable, reportable ROI | 3-yr TCO, cost-saving dashboards |

### 1.2 Functional business requirements (capability level)
- **FR-1 Conversational deflection & self-service** across web, mobile, **Microsoft Teams**, email — intent recognition, multi-turn, grounded answers. *(→ POC #1)*
- **FR-2 Automated L1/L2 resolution** of the 39 use cases, with intelligent routing for the rest. *(→ POCs #1–#4)*
- **FR-3 Identity & access lifecycle** (joiner-mover-leaver) across AD / M365 / SuccessFactors / Oracle, **governed**. *(→ POC #3)*
- **FR-4 Governed self-service requests** (groups, mailboxes, announcements) with multi-level approval. *(→ POC #4)*
- **FR-5 Proactive operations & RCA** — trend/pattern detection, root-cause, remediation recommendations. *(→ POC #2)*
- **FR-6 Service analytics & ROI cockpit** — MTTR, deflection, automation effectiveness, CSAT, ROI, SLA. *(cross-cutting, Hypervisor)*
- **FR-7 Knowledge capture & curation** — keep the KB current from experts/docs. *(capture engine)*

### 1.3 Non-functional requirements (the differentiators)
| ID | Requirement |
|---|---|
| NFR-1 **Sovereignty / data residency** | models + data + action ledger inside the client boundary (on-prem / private); no foreign-cloud dependency |
| NFR-2 **Security & identity** | RBAC + ABAC, distinct agent identity, control-policy guardrails, multi-tenant/entity isolation |
| NFR-3 **Robustness** | stateful runs, checkpoints, replay & resubmission with full lineage |
| NFR-4 **Observability & auditability** | tool-calling ledger, tamper-evident audit, decision trail, exportable |
| NFR-5 **Scalability** | multi-entity, multi-geography, high concurrency, configurable segmentation |
| NFR-6 **Performance & cost control** | deterministic generation budget, predictable token/compute spend |
| NFR-7 **Availability & SLA** | uptime, incident response, hypercare (≥30 days post-go-live) |
| NFR-8 **Maintainability / extensibility** | API-first, client team can extend flows without vendor lock-in |

### 1.4 Data, integration & compliance
- **Connectors (OOTB):** Active Directory / Entra, Microsoft 365 (Graph/Exchange), SAP SuccessFactors, Oracle Symphony, ITSM (ServiceNow / Jira / current), Teams/email; SharePoint/SFTP/secure-deposit for knowledge.
- **Data:** ITSM ticket history (12–24 mo for RCA), knowledge base/policies, HR feeds (joiner/leaver), directory state.
- **Compliance:** Qatar/Gulf sector rules (central bank, cybersecurity agency), AI-Act extraterritorial reach; human oversight on regulated decisions; data-sovereignty posture.

### 1.5 Constraints & assumptions
- Brownfield: **39 live automations** must be **assessed, migrated and enhanced**, not broken.
- Privileged write-actions (IAM) require staged rollout (simulate → single safe write → full).
- Multi-entity conglomerate → entity-level segmentation and chargeback expected.
- Client retains ownership/extensibility (no lock-in); knowledge transfer mandatory.

### 1.6 Success metrics (business KPIs)
Deflection % · MTTR by category/priority/team · FCR · CSAT · automation coverage (of 39 + new) · recurring-incident reduction % · tickets prevented proactively · ROI / 3-yr TCO · SLA compliance · audit completeness.

### 1.7 Out of scope (this engagement)
Endpoint hardware procurement; network/infra build; non-IT business process automation; replacing the system-of-record applications (AD/M365/SF/Oracle remain authoritative).

---

## PART 2 — Target Operating Model (TOM)

*How the AI-augmented ITSD operates once delivered. Ten dimensions; the distinctive one is the human + agent operating model.*

### 2.1 Service model & channels
- **Tiers:** L0 self-service (deflection) → L1/L2 automated agents → L3 human experts (escalation).
- **Channels:** Teams, web portal, mobile, email — one conversational front door (POC #1).
- **Catalogue:** the 39 use cases + new opportunities, exposed as governed self-service.

### 2.2 Value streams (human + agent), with HITL
| Value stream | Flow | Human-in-the-loop gate |
|---|---|---|
| **Answer / deflect** | ask → grounded RAG answer (cited) → else create ticket | low-confidence → human; escalate to L3 |
| **Request → fulfil** | request → multi-level approval → provision → notify | approvals (Line Manager → IT Mgmt); reject/missed/failed branches |
| **Identity lifecycle** | trigger (HR/schedule) → policy-check → provision/deprovision | mandate + guardrail on every privileged write |
| **Incident → resolve** | detect/route → automated remediation → close | sensitive actions → human approve |
| **Proactive → prevent** | monitor/trend → RCA → recommend remediation | human validates change (dress-rehearsal) |

### 2.3 Human + agent operating model (autonomy tiers)
- **Tier A — Autonomous:** low-risk, high-volume (password reset, KB answer) — agent acts, audited.
- **Tier B — Approve-then-act (HITL):** privileged or approval-bound (provisioning, IAM writes) — agent proposes, human/mandate authorises.
- **Tier C — Recommend-only:** RCA/remediation & change — agent recommends, human decides; proven on past cases before rollout.
- Each agent runs under a **signed mandate** (allowed actions, caps, scope, duration) and can never exceed the principal who mandated it.

### 2.4 Organisation, roles & RACI
| Role (Agentium persona) | Responsibility |
|---|---|
| **Executive** | portfolio value, ROI, priorities (Hypervisor) |
| **Operator** (service manager / agents) | run the desk, handle escalations, monitor runs |
| **Governance officer** | mandates, guardrails, audit, evaluation thresholds, compliance |
| **Builder** | author/extend flows, skills, knowledge guides |
| **IAM / security admin** | identity, RBAC/ABAC, control policies |
| **Knowledge / data steward** | KB capture, curation, knowledge guides |
| **ML engineer (optional)** | RCA models, evaluation, drift |

RACI principle: Datategy/partner **builds & enables**; PIH IT **operates & owns** (CoE handover).

### 2.5 Technology & platform
Agentium (orchestrate / build / evaluate) on **sovereign deployment**; the 4 Systems as Suites; OOTB connectors; Flow Builder for all 39 + new flows; Hypervisor for value steering.

### 2.6 Data & knowledge operating model
Knowledge captured & curated via the capture engine + knowledge guides; data residency inside the boundary; structured facts feed RCA; golden-set evaluation maintains quality.

### 2.7 Governance, risk & control
Signed mandates + control-policy guardrails; RBAC/ABAC + distinct agent identity; tamper-evident audit + replayable runs; evaluation/quality gates before any change (dress-rehearsal); AI oversight aligned to Qatar/Gulf + AI-Act; multi-entity isolation.

### 2.8 Service management
ITSM integration (incident/request/problem/change); SLAs/OLAs; continuous improvement loop (RCA → fix → re-measure); KPI/ROI reporting (Hypervisor); hypercare ≥30 days.

### 2.9 Sourcing, locations & Center of Excellence
**Editor-ESN model:** Datategy edits the platform; delivery/scale via partner ESN/integrator; PIH stands up an internal **AI Academy / CoE** to own and extend. Multi-entity, multi-geography rollout with entity segmentation + chargeback (capacity "priority lane").

### 2.10 Performance management & financials
Value steered in the Hypervisor (cost, quality, ROI per capability/system); deterministic token/compute budget; per-entity chargeback; 3-yr TCO.

### 2.11 Transition roadmap (operating model stand-up)
1. **Mobilise & POC** — 4 POCs (deflection, RCA, governed provisioning, approval-orchestrated requests) + analytics cockpit; baseline KPIs.
2. **Migrate** the 39 use cases onto the Flow Builder (assess → author → validate), enhance/consolidate.
3. **Govern & secure** — mandates, guardrails, audit; IAM writes go simulate → safe-write → full.
4. **Scale** multi-entity + proactive ops; **CoE handover** + enablement; hypercare.

---

## Traceability (one line)

**Business outcome (BO-x) → Functional requirement (FR-y) → TOM value stream + role → System/POC + Skills/Capabilities/Connectors.** Every RFP requirement therefore lands on a named operating-model element and a buildable Agentium artifact — which is exactly what an RFP evaluator scores under *Functional Fit* and *Implementation Approach*.
