# Targeted POC — Pre-on-site Qualification Checklist (3 systems/agents)

The **minimum to qualify remotely before travelling**, so the on-site week is *wire → validate → demo*, not *discover*. Scoped to a focused POC on **3 systems/agents**. Companion to `AGENTIUM-agent-design-capture-template.md` (we capture *headlines + 3 examples* per agent here, not full detail).

> Rule: we don't ask the business everything — we ask **enough to pre-build** the workspace, connectors, flow skeletons and golden sets remotely, and to confirm the POC is **feasible and safe** on-site.

---

## 0. How to use
- Each point: ☐ to qualify · **why it matters** · **what it lets us pre-build**.
- Anything unknown after first contact = a **risk flag** for §9 (Go/No-Go).
- Target: complete §1–§7 by remote workshop(s); then §8 pre-build; travel only if §9 is green.

## 1. Target selection — the 3 systems/agents
- ☐ **Which 3** (from the candidate POCs): conversational deflection · proactive RCA · governed provisioning (JML) · approval-orchestrated requests — pick by *value × feasibility × demoability*.
- ☐ Per agent: **the one demoable outcome** at the end of the POC week (a sentence the sponsor will judge).
- ☐ Per agent: **success metric** (e.g. deflection %, cycle-time, 0 out-of-mandate, RCA acceptance) + a baseline to beat.
- ☐ **Scope fence**: in-scope use cases vs explicitly out (no scope creep on-site).

## 2. HITL integration & human availability (per agent)

Default assumption: **the agent is expected to act autonomously.** So we don't ask "does a human approve before acting?" — we qualify **how the human plugs into the loop** and, above all, **how available humans are during the POC** to feed it.

- ☐ **HITL integration pattern**: where/how the human enters — *quality review/scoring of outputs* · *exception handling* (low-confidence / unknown cases) · *correction & reinjection* (feedback loop) · *(rare) sign-off on a genuinely sensitive action*.
- ☐ **Cadence & scope of the human touch**: % of outputs sampled, or which cases are queued for review; what "good vs bad" means (→ seeds evaluation thresholds + golden set).
- ☐ **Exceptions that still need a human green light**: which (sensitive / caps / scope) — expected to be the *minority*.
- ☐ **Human availability during the POC** ★: who (SME / reviewer / business owner), **how much time per day**, to review outputs, give quality feedback and validate the demo. *Without it we can't tune or evaluate — this is the binding POC constraint.*
- ☐ **Demo authority**: who can validate the outcome (and, if any sensitive action, approve one *sandbox* action live).

> *Why:* here HITL is the **feedback/governance layer around an autonomous agent**, not an action gate. *Pre-builds:* the **evaluation + review-queue + golden scaffolding**, and the POC schedule around the experts' availability.

## 3. SAP & enterprise interoperability
- ☐ **Which SAP modules/services** are in play: SuccessFactors (HR/joiner-leaver), S/4HANA / ECC, others?
- ☐ **Interface available per service** (and **read vs write**):
  - ☐ OData / SAP Gateway · ☐ BAPI / RFC · ☐ IDoc · ☐ CDS views · ☐ HANA SQL / JDBC · ☐ SLT / CDC / events.
- ☐ **Auth model**: technical user, OAuth, certs; who provisions it.
- ☐ **Sandbox / non-prod SAP** available for the POC? (read-only first; one safe write).
- ☐ **Other systems of record**: Active Directory / Entra, Microsoft 365 (Graph/Exchange), Oracle (Symphony), ITSM (ServiceNow / Jira / current) — same grid: interface, read/write, auth, sandbox.
> *Why:* SAP/enterprise interop is the usual blocker. *Pre-builds:* connector stubs + mocked responses so flows run before live creds land.

## 4. Where is the data — typology (data lake · MCP · knowledge)
Fill one row per relevant store:

| Store | Where / tech | Access method | R/W | Auth | Sandbox? | Residency | Sample available? |
|---|---|---|---|---|---|---|---|

- ☐ **Systems of record** (AD/M365/SF/Oracle/ITSM): per row above.
- ☐ **Data lake typology**: ☐ object store (S3 / ADLS / GCS / MinIO on-prem) · ☐ warehouse/lakehouse (Snowflake / BigQuery / Databricks) · ☐ HDFS · ☐ relational (PostgreSQL/Oracle/SQL Server) · ☐ NoSQL/search (Mongo / Elastic). **Formats** (Parquet/CSV/JSON/PDF…), **volumes**, **freshness/CDC**, **structured vs unstructured**.
- ☐ **MCP / tool-access typology** — *how agents reach tools/data*:
  - ☐ Existing **MCP servers** at the client? (which systems exposed) · ☐ **REST/OpenAPI** · ☐ **SDK/client lib** · ☐ **direct DB** (JDBC/SQL) · ☐ **files / SFTP / object store** · ☐ **events/webhooks**.
  - ☐ For each target system: the **fastest safe access path** for a POC (often read-only DB/API/file export before MCP).
- ☐ **Knowledge sources for RAG** (deflection/RCA): where are the policies/SOPs/runbooks/ticket history; formats; how to get an export; volume; OCR needed?
- ☐ **PII / governance**: classification, what can leave prod, anonymisation/synthetic-data option for the POC.
> *Why:* determines connectors + the RAG ingestion + sovereignty posture. *Pre-builds:* ingestion config, vector collection, KnowledgeGuide draft, MCP/connector selection.

## 5. Functional needs (headline + 3 examples per agent — not full detail)
For each of the 3 agents, capture only:
- ☐ **The job** (one sentence) + **trigger** (chat / schedule / event).
- ☐ **Inputs in hand** at start + **sources of truth** to consult.
- ☐ **The decision & the rule(s)** that matter (thresholds, "if X then Y").
- ☐ **Output / action** + whether it **writes** to a system.
- ☐ **3–5 real examples** (situation → good outcome → a bad one to avoid) → seeds the **golden set**.
- ☐ **Edge/failure**: what happens when unsure or failing.
> *Why:* enough to design System/Capability/Skills + evaluation. *Pre-builds:* flow skeleton + golden scaffolding. (Use the 12-field capture canvas; stop at headlines.)

## 6. Environment, security & sovereignty readiness
- ☐ **Deployment target**: on-prem / private cloud / air-gap? POC env = client VM / Datategy sandbox?
- ☐ **Compute**: CPU/GPU available for the POC (model serving), or do we bring it?
- ☐ **Connectivity**: VPN, network access to the target systems, egress rules (sovereignty: no phone-home).
- ☐ **Credentials & access**: who provisions accounts/keys, lead time (often the long pole).
- ☐ **Security clearance / NDA / data-handling** approvals needed before on-site.
- ☐ **Workspace isolation**: dedicated workspace/tenant; synthetic identities for writes.

## 7. Stakeholders & logistics
- ☐ **Business owner / sponsor** (judges success) · ☐ **IT / IAM admin** (access, directory) · ☐ **SAP / Basis** (interfaces) · ☐ **Data owner** (lake/exports) · ☐ **Security / governance** (mandates, egress) · ☐ **Decision-maker** (can approve a real action in the demo).
- ☐ **On-site dates, duration, room, network**; remote fallback for blocked systems.
- ☐ **Daily cadence**: who is available each day of the POC week.

## 8. What we pre-build remotely from these answers (so on-site is fast)
- ☐ Provision the **workspace** + roles/mandates.
- ☐ **Connector stubs + mocks** for each system (run flows before live creds).
- ☐ **Flow skeletons** for the 3 agents (happy path + rejected/missed/failed branches + HITL gates).
- ☐ **Ingestion + KnowledgeGuide draft** for the RAG agent; vector collection.
- ☐ **Golden-set scaffolding** from the captured examples; evaluation thresholds.
- ☐ **Demo script** per agent (the outcome to show the sponsor).

## 9. Go / No-Go to travel — minimum set
**Green to travel only if all are answered:**
- ☐ 3 agents chosen, each with a demoable outcome + metric + baseline.
- ☐ HITL tier + approver + mandate known per agent.
- ☐ For each system touched: an interface + **a safe access path** + sandbox (or a mock plan) confirmed.
- ☐ Data location + access method + residency known; sample or synthetic data secured.
- ☐ POC environment + connectivity + credentials path confirmed (lead times started).
- ☐ Sponsor + IT/IAM + SAP/Basis + data owner committed for the week.

**Risk flags (amber = mitigate before / red = don't travel):** no non-prod SAP; no credentials lead-time started; data can't leave prod and no synthetic option; no GPU/compute; no decision-maker for real actions; sources of truth not exportable.

---

### One-line logic
Qualify **target (3) → HITL → interfaces (SAP+) → data/MCP/lake → functional headlines+examples → environment → stakeholders** ⇒ pre-build remotely ⇒ on-site = wire, validate, demo. The four areas you named map to: HITL §2 · SAP §3 · data/MCP/lake §4 · functional §5 — the rest (§1,6,7) is what makes the trip *safe and productive*.
